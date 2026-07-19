"""统一工具响应体验信封。

设计原则：
- 业务字段保持顶层（兼容已有 Agent / CLI 契约）
- 额外挂 `ux` 块：status / summary / next_step / warnings
- 顶层同步 `next_step`（若原 payload 没有），方便 Agent 少读一层
"""

from __future__ import annotations

from typing import Any

UX_SCHEMA = "tool_ux.v1"

# 稳定状态机：Agent 可按 status 分支，不必解析长文
STATUS_OK = "ok"
STATUS_NEEDS_WEB_SEARCH = "needs_web_search"
STATUS_NEEDS_HUMAN_REVIEW = "needs_human_review"
STATUS_BLOCKED = "blocked"
STATUS_SUGGESTIONS_READY = "suggestions_ready"
STATUS_GENERATED = "generated"
STATUS_ERROR = "error"


def attach_ux(
    payload: dict[str, Any],
    *,
    status: str,
    summary: str,
    next_step: str,
    warnings: list[str] | None = None,
    agent_hint: str | None = None,
    promote_status: bool = True,
) -> dict[str, Any]:
    """把体验字段挂到业务 payload 上（浅拷贝，不改入参）。"""
    out = dict(payload)
    warns = [w for w in (warnings or []) if w]
    ux: dict[str, Any] = {
        "schema": UX_SCHEMA,
        "status": status,
        "summary": summary,
        "next_step": next_step,
        "warnings": warns,
    }
    if agent_hint:
        ux["agent_hint"] = agent_hint
    out["ux"] = ux
    if promote_status and "status" not in out:
        out["status"] = status
    if next_step and "next_step" not in out:
        out["next_step"] = next_step
    return out


def enrich_needs_web_search(payload: dict[str, Any]) -> dict[str, Any]:
    """增强 needs_web_search：补齐人话摘要、上次质量与 Agent 可执行下一步。"""
    queries = list(payload.get("suggested_queries") or [])
    query = str(payload.get("query") or "").strip()
    # 附带上次质量记忆，帮助 Agent 决定要搜多少 / 怎么扩
    previous_quality: dict[str, Any] | None = None
    strategy: dict[str, Any] | None = None
    if query:
        try:
            from xhs_skill.research.search_memory import (
                SearchQualityMemory,
                plan_search_strategy,
            )

            previous_quality = SearchQualityMemory().load(query)
            strategy = plan_search_strategy(previous_quality)
            # 质量差时加深 suggested_queries
            if strategy.get("has_baseline") and previous_quality:
                from xhs_skill.research.query_expansion import expand_query

                deeper = expand_query(
                    query,
                    max_variants=int(strategy.get("max_variants") or 8),
                    prefer_crowd_angles=bool(strategy.get("prefer_crowd_angles")),
                    force_site_queries=bool(strategy.get("force_site_queries")),
                )
                # 合并去重，保留原顺序优先
                seen = set(queries)
                for q in deeper:
                    if q not in seen:
                        queries.append(q)
                        seen.add(q)
                queries = queries[: max(6, int(strategy.get("variant_cap") or 6))]
        except Exception:
            previous_quality = None
            strategy = None

    q0 = queries[0] if queries else query or ""
    n_q = len(queries)
    summary = (
        f"当前环境没有可用的搜索 API，也未传入 web_results。"
        f"请先用宿主 websearch 检索（示例：{q0}），再重调同一工具。"
    )
    if previous_quality:
        summary += (
            f" 上次同 query 质量 {previous_quality.get('score')}（{previous_quality.get('label')}），"
            f"已按自适应策略加深查询变体。"
        )
    next_step = (
        "1) 宿主 websearch 执行 suggested_queries；"
        "2) 整理为 web_results[{url,title,snippet?}]（尽量含 snippet/互动）；"
        "3) 再次调用同一工具并传入 web_results。"
    )
    agent_hint = (
        "Do not invent notes. Run host websearch on suggested_queries, "
        "then re-call the same tool with web_results."
    )
    enriched = dict(payload)
    enriched["suggested_queries"] = queries
    enriched.setdefault("status", STATUS_NEEDS_WEB_SEARCH)
    if not enriched.get("instructions"):
        enriched["instructions"] = next_step
    min_results = min(max(n_q * 3, 5), 20)
    if previous_quality and float(previous_quality.get("score") or 0) < 40:
        min_results = min(max(min_results, 12), 25)
    enriched["minimum_results_hint"] = min_results
    if previous_quality:
        enriched["previous_search_quality"] = {
            "score": previous_quality.get("score"),
            "label": previous_quality.get("label"),
            "as_of": previous_quality.get("as_of"),
            "recommendations": previous_quality.get("recommendations") or [],
        }
    if strategy:
        enriched["adaptive_strategy"] = {
            "max_variants": strategy.get("max_variants"),
            "variant_cap": strategy.get("variant_cap"),
            "reason": strategy.get("reason"),
            "prefer_crowd_angles": strategy.get("prefer_crowd_angles"),
            "force_site_queries": strategy.get("force_site_queries"),
        }
    warnings = [
        "PUBLIC_INDEX_TREND：公开网页索引 ≠ 小红书站内热榜",
        f"建议至少 {min_results} 条有效结果以获得足够的多样性",
    ]
    if queries:
        warnings.append(f"已展开 {n_q} 条查询变体，全部执行后传入 web_results")
    if previous_quality and previous_quality.get("recommendations"):
        warnings.extend(str(r) for r in previous_quality["recommendations"][:2])
    return attach_ux(
        enriched,
        status=STATUS_NEEDS_WEB_SEARCH,
        summary=summary,
        next_step=next_step,
        warnings=warnings,
        agent_hint=agent_hint,
        promote_status=False,
    )


def ux_for_research(
    payload: dict[str, Any],
    *,
    tool: str,
) -> dict[str, Any]:
    """研究类工具：告诉用户看选题还是直接生成。"""
    suggestions = payload.get("topic_suggestions") or []
    notes = payload.get("notes") or []
    trends = payload.get("trends") or []
    n_s = len(suggestions)
    n_n = len(notes) if isinstance(notes, list) else 0
    n_t = len(trends) if isinstance(trends, list) else 0
    coverage = str(payload.get("coverage_warning") or "").strip()
    quality = payload.get("search_quality") or {}
    q_label = str(quality.get("label") or "")
    q_score = quality.get("score")
    q_recs = list(quality.get("recommendations") or [])
    q_delta = quality.get("delta") if isinstance(quality.get("delta"), dict) else {}
    strategy = quality.get("strategy") if isinstance(quality.get("strategy"), dict) else {}

    if tool == "search_trending_topics":
        summary = f"拿到 {n_t} 个趋势主题、{n_s} 条可点选选题。"
        next_step = (
            "选 topic_suggestions[i]，调用 generate_xhs_note(**generate_payload)；"
            "或 generate_from_hot(query=..., dry_run=false, suggestion_index=i)。"
        )
    elif tool == "analyze_hot_notes":
        summary = f"分析完成：{payload.get('notes_analyzed', n_n)} 条笔记机制与缺口，{n_s} 条选题。"
        next_step = (
            "优先 content_gaps / topic_suggestions；"
            "用 generate_payload 调 generate_xhs_note，或 dry_run 先看 generate_from_hot。"
        )
    else:
        quality_part = ""
        if q_score is not None:
            quality_part = f"搜索质量 {q_score:.0f}（{q_label}）。"
            if q_delta.get("score_delta") is not None:
                quality_part += f" 相对上次 Δ={q_delta['score_delta']:+.1f}。"
        summary = f"检索完成：{n_n} 条笔记线索、{n_s} 条选题建议。{quality_part}"
        next_step = (
            "浏览 hot_insights 与 topic_suggestions（含 confidence）；"
            "选定后 generate_xhs_note 或 generate_from_hot(dry_run=true) 先选题。"
        )

    warnings: list[str] = []
    if coverage:
        warnings.append(coverage[:240])
    if n_n == 0 and n_s == 0 and n_t == 0:
        warnings.append("结果偏空：可换 query、放宽 time_range，或补充 web_results。")
    if q_label == "poor" and q_recs:
        warnings.extend(str(r) for r in q_recs[:3])
    elif q_label == "fair" and q_recs:
        warnings.extend(str(r) for r in q_recs[:2])
    if q_delta.get("regressed"):
        warnings.append("搜索质量较上次下降，建议换词或补充 web_results。")
    if strategy.get("reason") and strategy.get("has_baseline"):
        warnings.append(f"自适应：{strategy.get('reason')}")

    return attach_ux(
        payload,
        status=STATUS_OK,
        summary=summary,
        next_step=next_step,
        warnings=warnings,
        agent_hint=(
            "Prefer topic_suggestions[].generate_payload; "
            "respect confidence/confidence_note when quality is poor."
        ),
    )


def ux_for_delivery_package(payload: dict[str, Any]) -> dict[str, Any]:
    """生成交付包：按门禁/就绪分给出下一步。"""
    pub = str(payload.get("publication_status") or "")
    qr = payload.get("quality_report") or {}
    readiness = qr.get("readiness") if isinstance(qr, dict) else None
    if not isinstance(readiness, dict):
        readiness = {}
    score = readiness.get("overall_score")
    blockers = list(readiness.get("blockers") or [])
    fixes = list(readiness.get("recommended_fixes") or [])
    title = str(payload.get("selected_title") or "").strip()
    bundle = payload.get("creation_bundle") or {}
    bundle_ready = bool((bundle.get("readiness") or {}).get("ready_for_draft"))

    warnings: list[str] = []
    if blockers:
        warnings.extend(str(b) for b in blockers[:6])
    if fixes:
        warnings.extend(f"fix:{f}" for f in fixes[:4])

    if pub == "BLOCKED" or "compliance_failed" in blockers or "originality_blocked" in blockers:
        status = STATUS_BLOCKED
        summary = f"文案已生成但不可发布（{pub or 'BLOCKED'}）" + (f"：{title}" if title else "。")
        next_step = (
            "按 blockers / recommended_fixes 改写后 rewrite_xhs_note 或重新 generate；"
            "通过 check_compliance / check_originality / verify_claims 后再建草稿。"
        )
        agent_hint = "Do not create_publish_draft while status is blocked."
    elif blockers or pub in {"HUMAN_REVIEW_REQUIRED", "NEEDS_REVIEW"} or not readiness.get(
        "ready_for_human_review", True
    ):
        status = STATUS_NEEDS_HUMAN_REVIEW
        score_part = f"就绪分 {score}。" if score is not None else ""
        summary = f"文案待人工审阅。{score_part}" + (f"主标题：{title}" if title else "")
        next_step = (
            "人工核对 claims / 合规 / 原创；"
            "确认后 create_publish_draft → preview → approve → publish（需 approved=true）。"
        )
        agent_hint = "Surface blockers to the user; never skip human review for objective claims."
    else:
        status = STATUS_OK
        score_part = f"就绪分 {score}。" if score is not None else ""
        draft_hint = "创作一览包可直接展示。" if bundle_ready else "可先微调封面/口播再出草稿。"
        summary = f"交付包已就绪。{score_part}{draft_hint}" + (f" 标题：{title}" if title else "")
        next_step = (
            "展示 creation_bundle（标题簇/封面/分页/口播）；"
            "用户确认后 create_publish_draft，再走预览与审批发布。"
        )
        agent_hint = "Show creation_bundle first; publishing requires explicit user approval."

    return attach_ux(
        payload,
        status=status,
        summary=summary.strip(),
        next_step=next_step,
        warnings=warnings,
        agent_hint=agent_hint,
    )


def ux_for_rewrite(payload: dict[str, Any]) -> dict[str, Any]:
    structure = payload.get("structure_checks") or {}
    passed = structure.get("passed")
    fixes = structure.get("recommended_fixes") or []
    hook = payload.get("title_hook") or {}
    risk = list(hook.get("risk_flags") or []) if isinstance(hook, dict) else []
    warnings = [str(f) for f in fixes[:5]] + [f"title_risk:{r}" for r in risk[:3]]
    if passed is False:
        status = STATUS_NEEDS_HUMAN_REVIEW
        summary = "改写完成，结构检查未全过，请按 recommended_fixes 再修。"
        next_step = "根据 structure_checks.recommended_fixes 调整，或再调 rewrite_xhs_note。"
    else:
        status = STATUS_OK
        summary = "改写完成，可对照 title_hook 选用新标题。"
        next_step = "若满意则写入交付包 / create_publish_draft；否则继续 rewrite 或 diagnose_xhs_note。"
    return attach_ux(
        payload,
        status=status,
        summary=summary,
        next_step=next_step,
        warnings=warnings,
        agent_hint="Keep entity/number fidelity from title_hook and entity checks when present.",
    )


def ux_for_hot_to_note(payload: dict[str, Any]) -> dict[str, Any]:
    """热门一键：dry_run 与 generated 两条路径。"""
    raw_status = str(payload.get("status") or "")
    if raw_status == "error" or payload.get("error"):
        return attach_ux(
            payload,
            status=STATUS_ERROR,
            summary=f"热门一键失败：{payload.get('error') or 'unknown'}",
            next_step="检查 query / suggestion_index / suggestion_topic，或先 dry_run=true。",
            agent_hint="Fix arguments then retry generate_from_hot.",
            promote_status=False,
        )
    if payload.get("dry_run") or raw_status == "suggestions_ready":
        n = len(payload.get("topic_suggestions") or [])
        selected = payload.get("selected_suggestion") or {}
        topic = selected.get("topic") if isinstance(selected, dict) else None
        summary = f"选题就绪（{n} 条）。" + (f"当前选中：{topic}" if topic else "")
        next_step = payload.get("next_step") or (
            "generate_from_hot(dry_run=false) 成稿，"
            "或 generate_xhs_note(**selected_suggestion.generate_payload)。"
        )
        return attach_ux(
            payload,
            status=STATUS_SUGGESTIONS_READY,
            summary=summary,
            next_step=str(next_step),
            warnings=[str(payload.get("coverage_warning") or "")[:240]]
            if payload.get("coverage_warning")
            else None,
            agent_hint="Confirm selected_index/topic with user before dry_run=false.",
            promote_status=False,
        )

    package = payload.get("package")
    if isinstance(package, dict):
        # 对内嵌 package 也挂 ux，外层给总览
        payload = dict(payload)
        payload["package"] = ux_for_delivery_package(package)
        pkg_ux = (payload["package"].get("ux") or {})
        return attach_ux(
            payload,
            status=STATUS_GENERATED,
            summary=str(pkg_ux.get("summary") or "已从热门选题生成交付包。"),
            next_step=str(pkg_ux.get("next_step") or "审阅 package.creation_bundle 后走发布草稿流。"),
            warnings=list(pkg_ux.get("warnings") or []),
            agent_hint=str(pkg_ux.get("agent_hint") or ""),
            promote_status=False,
        )

    return attach_ux(
        payload,
        status=raw_status or STATUS_OK,
        summary="热门一键流程已返回。",
        next_step=str(payload.get("next_step") or "检查返回字段后继续。"),
        promote_status=False,
    )


def ux_for_diagnose(payload: dict[str, Any]) -> dict[str, Any]:
    compliance = payload.get("compliance") or {}
    originality = payload.get("originality") or {}
    structure = payload.get("structure_checks") or {}
    fixes = list(payload.get("recommended_fixes") or structure.get("recommended_fixes") or [])
    warnings: list[str] = []
    if not compliance.get("passed", True):
        warnings.append("compliance_failed")
    if originality and not originality.get("publication_allowed", True):
        warnings.append("originality_blocked")
    if structure.get("passed") is False:
        warnings.append("structure_incomplete")
    if warnings:
        status = STATUS_NEEDS_HUMAN_REVIEW
        summary = f"诊断发现问题：{', '.join(warnings)}。"
        next_step = "按 recommended_fixes 改写后 rewrite_xhs_note 或重新 generate，再 check_compliance。"
    else:
        status = STATUS_OK
        summary = "诊断通过：合规/原创/结构未见硬阻断。"
        next_step = "可继续 create_publish_draft，或先 plan_content_outline 优化结构。"
    return attach_ux(
        payload,
        status=status,
        summary=summary,
        next_step=next_step,
        warnings=warnings + [str(f) for f in fixes[:4]],
        agent_hint="Do not publish while diagnose reports compliance or originality failures.",
    )


def ux_for_verify(payload: dict[str, Any], *, tool: str) -> dict[str, Any]:
    if tool == "verify_claims":
        claims = payload.get("claims") or []
        unverified = [
            c
            for c in claims
            if isinstance(c, dict) and not c.get("verified", False)
        ]
        if unverified:
            return attach_ux(
                payload,
                status=STATUS_NEEDS_HUMAN_REVIEW,
                summary=f"声明台账：{len(claims)} 条中 {len(unverified)} 条未核验。",
                next_step="对未核验声明 DELETE/QUALIFY/CONVERT_TO_SUBJECTIVE/HUMAN_REVIEW，禁止编造证据。",
                warnings=[f"unverified_claims:{len(unverified)}"],
                agent_hint="Never invent evidence for unverified claims.",
            )
        return attach_ux(
            payload,
            status=STATUS_OK,
            summary=f"声明台账 {len(claims)} 条均已标记核验状态。",
            next_step="继续 check_compliance / check_originality，或写入交付包。",
        )
    if tool == "check_originality":
        allowed = payload.get("publication_allowed")
        if allowed is False:
            return attach_ux(
                payload,
                status=STATUS_BLOCKED,
                summary="原创性门禁未通过，禁止直接发布。",
                next_step="加大改写幅度或换机制角度后 rewrite_xhs_note，再重跑 check_originality。",
                agent_hint="Do not create_publish_draft while originality blocks publication.",
            )
        return attach_ux(
            payload,
            status=STATUS_OK,
            summary="原创性检查通过（仍需人工审阅独特表达）。",
            next_step="可继续 check_compliance 或 create_publish_draft。",
        )
    if tool == "check_compliance":
        passed = payload.get("passed")
        if passed is False:
            return attach_ux(
                payload,
                status=STATUS_BLOCKED,
                summary="合规检查未通过。",
                next_step="按 findings 删除极限词/虚构功效/未披露商业后重写，再 check_compliance。",
                warnings=[str(f) for f in (payload.get("findings") or [])[:5]],
                agent_hint="Blocked content must not enter publish draft.",
            )
        return attach_ux(
            payload,
            status=STATUS_OK,
            summary="合规检查通过。",
            next_step="可 create_publish_draft；商业内容确认披露后再 approve。",
        )
    return attach_ux(
        payload,
        status=STATUS_OK,
        summary="校验结果已返回。",
        next_step="根据结果决定改写或进入发布流。",
    )


def ux_for_account(payload: dict[str, Any], *, tool: str) -> dict[str, Any]:
    if tool == "query_account_weight":
        score = payload.get("estimated_weight") or payload.get("score") or payload.get("weight")
        summary = "账号权重为 ESTIMATED_ACCOUNT_WEIGHT（非官方分）。"
        if score is not None:
            summary = f"估算账号权重：{score}（ESTIMATED_ACCOUNT_WEIGHT，非官方分）。"
        return attach_ux(
            payload,
            status=STATUS_OK,
            summary=summary,
            next_step="可 query_content_health / diagnose_account；选题用 suggest_topics_by_health。",
            warnings=["非小红书官方权重/ thrift 分"],
            agent_hint="Always label as ESTIMATED_ACCOUNT_WEIGHT.",
        )
    if tool == "query_content_health":
        return attach_ux(
            payload,
            status=STATUS_OK,
            summary="内容健康度估算已返回（非官方推荐）。",
            next_step="结合弱项用 suggest_topics_by_health 或 generate_from_hot(use_account_health=true)。",
            agent_hint="Health scores are estimates for topic routing, not platform rank.",
        )
    if tool == "diagnose_account":
        suggestions = payload.get("topic_suggestions") or payload.get("generate_payload")
        n = len(suggestions) if isinstance(suggestions, list) else (1 if suggestions else 0)
        return attach_ux(
            payload,
            status=STATUS_OK,
            summary=f"账号诊断完成，含 {n} 条可执行选题/生成线索。",
            next_step="用 generate_payload 调 generate_xhs_note，或先 create_content_calendar。",
            agent_hint="Prefer generate_payload over free-form topics.",
        )
    if tool == "suggest_topics_by_health":
        items = payload.get("topic_suggestions") or payload.get("suggestions") or []
        n = len(items) if isinstance(items, list) else 0
        return attach_ux(
            payload,
            status=STATUS_SUGGESTIONS_READY if n else STATUS_OK,
            summary=f"健康度驱动选题 {n} 条。",
            next_step="选一条 generate_xhs_note(**generate_payload) 或 generate_from_hot。",
            agent_hint="Confirm topic with user before generating full package.",
        )
    if tool == "sync_account_analytics":
        return attach_ux(
            payload,
            status=STATUS_OK,
            summary="授权分析数据已同步。",
            next_step="query_account_weight / query_content_health 刷新估算。",
        )
    if tool == "start_account_login":
        return attach_ux(
            payload,
            status=STATUS_OK,
            summary="已发起登录：需账号主人扫码确认。",
            next_step="展示二维码后轮询 check_account_login；勿自动化绕过验证码。",
            agent_hint="User must scan QR; stop on captcha/risk verification.",
        )
    if tool == "check_account_login":
        state = str(payload.get("status") or payload.get("state") or "")
        if state.lower() in {"authenticated", "logged_in", "ready", "success"}:
            return attach_ux(
                payload,
                status=STATUS_OK,
                summary=f"登录状态：{state or 'ok'}。",
                next_step="可 create_publish_draft / publish_note（仍需审批 token）。",
            )
        return attach_ux(
            payload,
            status=STATUS_OK,
            summary=f"登录未完成：{state or 'pending'}。",
            next_step="等待用户扫码；超时则 start_account_login 重开。",
            promote_status=False,
        )
    if tool == "logout_account":
        return attach_ux(
            payload,
            status=STATUS_OK,
            summary="已退出登录会话。",
            next_step="再次发布前需 start_account_login。",
            agent_hint="High-impact: only after explicit user approval.",
        )
    return attach_ux(
        payload,
        status=STATUS_OK,
        summary="账号工具结果已返回。",
        next_step="按业务字段继续。",
    )


def ux_for_publish(payload: dict[str, Any], *, tool: str) -> dict[str, Any]:
    if tool == "create_publish_draft":
        draft_id = payload.get("draft_id") or payload.get("id")
        return attach_ux(
            payload,
            status=STATUS_OK,
            summary=f"发布草稿已创建{f'：{draft_id}' if draft_id else ''}。",
            next_step="preview_publish_draft → 用户确认后 approve_publish_draft → publish_note。",
            agent_hint="Never skip preview/approve; approval binds content hash.",
        )
    if tool == "preview_publish_draft":
        return attach_ux(
            payload,
            status=STATUS_NEEDS_HUMAN_REVIEW,
            summary="草稿预览就绪，等待人工确认。",
            next_step="用户确认后 approve_publish_draft（含 AI/商业/身份披露确认）。",
            agent_hint="Surface preview to user before approve.",
        )
    if tool == "approve_publish_draft":
        return attach_ux(
            payload,
            status=STATUS_OK,
            summary="草稿已审批，获得短期 approval_token。",
            next_step="在 TTL 内 publish_note 或 schedule_note（需 approved=true）。",
            agent_hint="Token is single-use/hash-bound; content change invalidates approval.",
        )
    if tool == "publish_note":
        pub = str(payload.get("status") or payload.get("publication_status") or "")
        if "block" in pub.lower() or payload.get("blocked"):
            return attach_ux(
                payload,
                status=STATUS_BLOCKED,
                summary=f"发布被阻断：{pub or 'blocked'}。",
                next_step="按错误修复后重新 draft→preview→approve；验证码/风控立即停止。",
                agent_hint="Stop on captcha/risk; do not bypass.",
            )
        return attach_ux(
            payload,
            status=STATUS_OK,
            summary="发布请求已执行（请核对平台侧结果）。",
            next_step="成功后 sync_published_metrics / generate_retrospective。",
        )
    if tool == "schedule_note":
        return attach_ux(
            payload,
            status=STATUS_OK,
            summary="定时发布已登记。",
            next_step="用 get_publish_windows 校验窗口；到点后确认任务状态。",
        )
    if tool == "get_publish_windows":
        windows = payload.get("windows") or payload.get("items") or payload
        n = len(windows) if isinstance(windows, list) else 0
        return attach_ux(
            payload if isinstance(payload, dict) else {"data": payload},
            status=STATUS_OK,
            summary=f"推荐发帖窗口 {n or '若干'} 个（估算，非官方）。",
            next_step="选窗口后 schedule_note；仍需审批与用户确认。",
        )
    return attach_ux(
        payload,
        status=STATUS_OK,
        summary="发布流结果已返回。",
        next_step="按 draft/approve/publish 顺序继续。",
    )


def ux_for_operations(payload: dict[str, Any], *, tool: str) -> dict[str, Any]:
    if tool == "generate_retrospective":
        nexts = payload.get("next_note_suggestions") or []
        n = len(nexts) if isinstance(nexts, list) else 0
        return attach_ux(
            payload,
            status=STATUS_OK,
            summary=f"复盘完成，{n} 条下一篇建议。",
            next_step="用 next_note_suggestions[].generate_payload 调 generate_xhs_note。",
            agent_hint="next_action is usually generate_xhs_note.",
        )
    if tool == "analyze_performance":
        return attach_ux(
            payload,
            status=STATUS_OK,
            summary="描述性表现复盘（非因果结论）。",
            next_step=str(
                "；".join(str(x) for x in (payload.get("next_experiments") or [])[:3])
                or "设计单变量 A/B 后再 create_abn_experiment。"
            ),
            warnings=[str(payload.get("caveat") or "")] if payload.get("caveat") else None,
        )
    if tool == "sync_published_metrics":
        return attach_ux(
            payload,
            status=STATUS_OK,
            summary="授权侧发布后指标已同步。",
            next_step="get_performance_attribution / generate_retrospective。",
        )
    if tool == "get_performance_attribution":
        return attach_ux(
            payload,
            status=STATUS_OK,
            summary="归因结果为相关性线索，非确定因果。",
            next_step="结合 create_abn_experiment 验证标题/封面单变量。",
            warnings=["correlation_not_causation"],
        )
    if tool == "get_account_weight_trend":
        return attach_ux(
            payload,
            status=STATUS_OK,
            summary="账号权重趋势（估算序列）。",
            next_step="弱项下降时 suggest_topics_by_health 调整选题。",
        )
    if tool == "create_content_calendar":
        items = payload.get("items") or []
        return attach_ux(
            payload,
            status=STATUS_OK,
            summary=f"内容日历 {len(items) if isinstance(items, list) else 0} 条。",
            next_step="按日历条目 generate_xhs_note / create_content_series。",
        )
    if tool == "create_content_series":
        return attach_ux(
            payload,
            status=STATUS_OK,
            summary="系列规划已创建。",
            next_step="按 episode 逐篇 generate_xhs_note。",
        )
    if tool in {
        "create_abn_experiment",
        "assign_experiment_variant",
        "record_experiment_outcome",
        "analyze_abn_experiment",
        "choose_content_bandit",
        "update_content_bandit",
    }:
        return attach_ux(
            payload,
            status=STATUS_OK,
            summary=f"实验/ bandit 工具 {tool} 已完成。",
            next_step="记录结果后回流 generate 或 update_content_bandit。",
        )
    if tool == "search_asset_library":
        items = payload.get("items") or []
        return attach_ux(
            payload,
            status=STATUS_OK,
            summary=f"素材库命中 {len(items) if isinstance(items, list) else 0} 条。",
            next_step="选用 asset_id 作为封面/参考图传入生成或诊断工具。",
        )
    if tool == "draft_comment_reply":
        return attach_ux(
            payload,
            status=STATUS_NEEDS_HUMAN_REVIEW,
            summary="评论回复草稿仅供人工提交（不可自动发评）。",
            next_step="展示候选给用户；用户手动发送。",
            agent_hint="requires_human_submit=true; never auto-post comments.",
        )
    return attach_ux(
        payload,
        status=STATUS_OK,
        summary=f"运营工具 {tool} 结果已返回。",
        next_step="按 next_note_suggestions 或实验结论继续生成。",
    )


def ux_for_enterprise(payload: dict[str, Any], *, tool: str) -> dict[str, Any]:
    if tool == "enterprise_dlp_scan":
        blocking = bool(payload.get("blocking"))
        findings = payload.get("findings") or []
        if blocking:
            return attach_ux(
                payload,
                status=STATUS_BLOCKED,
                summary=f"DLP 发现阻断项（{len(findings)} findings）。",
                next_step="处理 redacted_text / findings 后再提交业务工具。",
                agent_hint="Do not forward CRITICAL secrets to external providers.",
            )
        return attach_ux(
            payload,
            status=STATUS_OK,
            summary=f"DLP 扫描完成，{len(findings)} 条发现。",
            next_step="必要时使用 redacted_text 继续流程。",
        )
    if tool in {"create_enterprise_approval", "decide_enterprise_approval"}:
        return attach_ux(
            payload,
            status=STATUS_OK,
            summary=f"企业审批 {tool} 已处理。",
            next_step="审批通过后绑定 publish approve；申请人不得自批。",
            agent_hint="SoD: requester cannot approve own publish.",
        )
    return attach_ux(
        payload,
        status=STATUS_OK,
        summary=f"企业工具 {tool} 结果已返回。",
        next_step="核对 tenant/budget/audit 后再执行高风险操作。",
    )


def ux_for_outline(payload: dict[str, Any]) -> dict[str, Any]:
    sections = payload.get("sections") or payload.get("outline") or []
    n = len(sections) if isinstance(sections, list) else 0
    return attach_ux(
        payload,
        status=STATUS_OK,
        summary=f"内容大纲已生成（约 {n} 段）。",
        next_step="确认大纲后 generate_xhs_note（可带 note_style/narrative_framework）。",
    )


def ux_for_variants(payload: dict[str, Any]) -> dict[str, Any]:
    variants = payload.get("variants") or []
    n = len(variants) if isinstance(variants, list) else 0
    rec = payload.get("recommended_index", 0)
    # 给每个变体挂交付 ux（若是完整 package）
    out = dict(payload)
    if isinstance(variants, list):
        enriched: list[Any] = []
        for item in variants:
            if isinstance(item, dict) and (
                "selected_title" in item or "quality_report" in item or "body" in item
            ):
                enriched.append(ux_for_delivery_package(item))
            else:
                enriched.append(item)
        out["variants"] = enriched
    return attach_ux(
        out,
        status=STATUS_GENERATED if n else STATUS_OK,
        summary=f"多变体 {n} 条，推荐 index={rec}。",
        next_step="对比 variants[].ux 与 readiness，选中后 create_publish_draft。",
        agent_hint="Present top variants to user; do not auto-publish.",
    )


def ux_for_jobs(payload: dict[str, Any], *, tool: str) -> dict[str, Any]:
    if tool == "list_job_dead_letters":
        items = payload.get("items") or []
        return attach_ux(
            payload,
            status=STATUS_OK,
            summary=f"死信 {len(items) if isinstance(items, list) else 0} 条。",
            next_step="确认后 replay_job_dead_letter（需 approved=true）。",
        )
    if tool == "replay_job_dead_letter":
        return attach_ux(
            payload,
            status=STATUS_OK,
            summary="死信已重放。",
            next_step="观察任务状态与下游指标。",
        )
    return attach_ux(
        payload,
        status=STATUS_OK,
        summary="任务运维结果已返回。",
        next_step="按运维手册继续。",
    )


def ux_generic(payload: dict[str, Any], *, tool: str) -> dict[str, Any]:
    return attach_ux(
        payload,
        status=STATUS_OK,
        summary=f"工具 {tool} 已完成。",
        next_step="阅读返回字段；不确定时回到 search_hot_notes 或 doctor。",
    )


def enrich_tool_result(tool_name: str, payload: Any) -> dict[str, Any]:
    """按工具名给返回值挂 ux。已有 ux 且 schema 匹配则跳过（幂等）。"""
    if not isinstance(payload, dict):
        payload = {"result": payload}
    existing = payload.get("ux")
    if isinstance(existing, dict) and existing.get("schema") == UX_SCHEMA:
        return payload
    if payload.get("status") == STATUS_NEEDS_WEB_SEARCH or (
        isinstance(existing, dict) and existing.get("status") == STATUS_NEEDS_WEB_SEARCH
    ):
        return enrich_needs_web_search(payload)

    name = tool_name
    if name in {"search_hot_notes", "search_trending_topics", "analyze_hot_notes"}:
        return ux_for_research(payload, tool=name)
    if name == "generate_xhs_note":
        return ux_for_delivery_package(payload)
    if name == "rewrite_xhs_note":
        return ux_for_rewrite(payload)
    if name == "generate_from_hot":
        return ux_for_hot_to_note(payload)
    if name == "diagnose_xhs_note":
        return ux_for_diagnose(payload)
    if name in {"verify_claims", "check_originality", "check_compliance"}:
        return ux_for_verify(payload, tool=name)
    if name in {
        "query_account_weight",
        "query_content_health",
        "diagnose_account",
        "suggest_topics_by_health",
        "sync_account_analytics",
        "start_account_login",
        "check_account_login",
        "logout_account",
    }:
        return ux_for_account(payload, tool=name)
    if name in {
        "create_publish_draft",
        "preview_publish_draft",
        "approve_publish_draft",
        "publish_note",
        "schedule_note",
        "get_publish_windows",
    }:
        return ux_for_publish(payload, tool=name)
    if name == "plan_content_outline":
        return ux_for_outline(payload)
    if name == "generate_xhs_note_variants":
        return ux_for_variants(payload)
    if name in {
        "sync_published_metrics",
        "get_performance_attribution",
        "get_account_weight_trend",
        "create_content_calendar",
        "create_content_series",
        "create_abn_experiment",
        "assign_experiment_variant",
        "record_experiment_outcome",
        "analyze_abn_experiment",
        "choose_content_bandit",
        "update_content_bandit",
        "search_asset_library",
        "generate_retrospective",
        "analyze_performance",
        "draft_comment_reply",
    }:
        return ux_for_operations(payload, tool=name)
    if name in {
        "get_enterprise_controls",
        "get_enterprise_budget",
        "create_enterprise_approval",
        "decide_enterprise_approval",
        "verify_enterprise_audit",
        "enterprise_dlp_scan",
    }:
        return ux_for_enterprise(payload, tool=name)
    if name in {"list_job_dead_letters", "replay_job_dead_letter"}:
        return ux_for_jobs(payload, tool=name)
    if name == "doctor":
        ready = payload.get("ready")
        summary_block = payload.get("summary") or {}
        errors = summary_block.get("errors", 0) if isinstance(summary_block, dict) else 0
        if ready is False or errors:
            return attach_ux(
                payload,
                status=STATUS_ERROR if ready is False else STATUS_OK,
                summary=f"Doctor：环境未就绪（errors={errors}）。" if ready is False else "Doctor 有告警。",
                next_step=str(
                    (payload.get("golden_path") or ["按 checks[].hint 修复"])[0]
                    if isinstance(payload.get("golden_path"), list)
                    else "按 checks[].hint 修复后重跑 xhs-skill doctor"
                ),
                warnings=[
                    f"{c.get('name')}:{c.get('hint') or c.get('detail')}"
                    for c in (payload.get("checks") or [])
                    if isinstance(c, dict) and not c.get("ok")
                ][:8],
                agent_hint="Fix error-level checks before generate/publish.",
                promote_status=False,
            )
        return attach_ux(
            payload,
            status=STATUS_OK,
            summary="Doctor：环境就绪。",
            next_step=str(
                (payload.get("golden_path") or ["xhs-skill generate --topic ..."])[1]
                if isinstance(payload.get("golden_path"), list)
                and len(payload.get("golden_path") or []) > 1
                else "开始 search_hot_notes 或 generate_xhs_note"
            ),
            promote_status=False,
        )
    if name == "publish_canary":
        ok = payload.get("ok")
        if ok is False:
            return attach_ux(
                payload,
                status=STATUS_BLOCKED,
                summary="发布页选择器 canary 失败，UI 可能变更。",
                next_step="更新 creator_studio_selectors 或设置 SELECTOR_PIN_VERSION 后重试。",
                agent_hint="Do not publish while canary fails.",
            )
        return attach_ux(
            payload,
            status=STATUS_OK,
            summary="发布页选择器 canary 通过。",
            next_step="可继续 draft → preview → approve → publish。",
        )
    return ux_generic(payload, tool=name)