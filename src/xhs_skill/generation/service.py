from __future__ import annotations

import json
import re
from pathlib import Path
from uuid import uuid4

from xhs_skill.accounts import AccountService, adapt_request_to_profile
from xhs_skill.core.concurrency import get_concurrency_controller
from xhs_skill.core.config import get_settings
from xhs_skill.core.security import content_hash
from xhs_skill.generation.brief import build_content_brief
from xhs_skill.generation.checklist_pages import ensure_checkbox_body, is_checklist_style
from xhs_skill.generation.covers import build_cover_options
from xhs_skill.generation.fallback import (
    build_body,
    build_titles,
    build_video,
    pages_from_body,
)
from xhs_skill.generation.hooks import pick_pinned_comment
from xhs_skill.generation.keyword_seo import build_keyword_map
from xhs_skill.generation.outline import build_content_outline
from xhs_skill.generation.quality_score import score_delivery_package
from xhs_skill.generation.rewrite import (
    CleanupChange,
    apply_cleanup_rules,
    assemble_rewrite_response,
)
from xhs_skill.generation.tags import append_hashtags_to_body, build_topics_and_hashtags
from xhs_skill.generation.voice import apply_voice_to_text, voice_system_hint
from xhs_skill.intelligence.embeddings import get_embedding_provider
from xhs_skill.providers.base import ImageProvider
from xhs_skill.providers.openai_images import get_image_provider
from xhs_skill.providers.registry import ProviderRegistry
from xhs_skill.ranking import HybridTitleRanker, LambdaMARTRanker
from xhs_skill.schemas.content import (
    DeliveryPackage,
    GenerateRequest,
)
from xhs_skill.schemas.provider import GenerationRequest
from xhs_skill.schemas.research import HotNotesReport
from xhs_skill.storage.assets import AssetStore
from xhs_skill.verifiers import (
    ai_style_report,
    check_text,
    extract_claims,
    originality_report_async,
)

SYSTEM_PROMPT = """你是“小红书爆款笔记生成 agent Skill”的内容生成器。
必须基于用户提供的事实、brief 与 outline（叙事框架阶段），不得编造使用经历、互动数据、用户评价、检测结果或平台规则。
不得洗稿。按 outline.sections 顺序展开，开场使用 outline.opening_hook 的意图，结尾呼应 closing_cta。
输出具体、克制、可执行的中文内容。遵守 voice 约束与 forbidden 清单。"""


class GenerationService:
    def __init__(
        self,
        providers: ProviderRegistry | None = None,
        image_provider: ImageProvider | None = None,
        asset_store: AssetStore | None = None,
    ) -> None:
        self.providers = providers or ProviderRegistry()
        self.image_provider = image_provider or get_image_provider()
        self.asset_store = asset_store or AssetStore()
        self.concurrency = get_concurrency_controller()
        self.accounts = AccountService()
        settings = getattr(self.concurrency, "settings", None) or get_settings()
        self.learning_ranker = LambdaMARTRanker(
            getattr(settings, "learning_ranker_model_path", None)
        )
        self.hybrid_ranker = HybridTitleRanker(
            self.learning_ranker,
            rrf_k=int(getattr(settings, "hybrid_rrf_k", 60)),
            mmr_lambda=float(getattr(settings, "hybrid_mmr_lambda", 0.72)),
            cross_encoder_enabled=bool(
                getattr(settings, "cross_encoder_rerank_enabled", True)
            ),
            cross_encoder_weight=float(
                getattr(settings, "cross_encoder_rrf_weight", 1.15)
            ),
            cross_encoder_top_k=int(getattr(settings, "cross_encoder_top_k", 12)),
            cross_encoder_timeout_seconds=float(
                getattr(settings, "cross_encoder_timeout_seconds", 4.0)
            ),
            cross_encoder_cache_ttl_seconds=float(
                getattr(settings, "cross_encoder_cache_ttl_seconds", 300.0)
            ),
            cross_encoder_max_provider_attempts=int(
                getattr(settings, "cross_encoder_max_provider_attempts", 1)
            ),
            providers=self.providers,
        )
        self.hybrid_ranker_enabled = bool(getattr(settings, "hybrid_ranker_enabled", True))

    async def generate(
        self,
        request: GenerateRequest,
        report: HotNotesReport | None = None,
        *,
        tenant_id: str = "local",
    ) -> DeliveryPackage:
        task_id, trace_id = str(uuid4()), str(uuid4())
        # 选题一跳：suggested_topic 覆盖 topic 种子（保留原 topic 进 strategy）
        seed_topic = request.topic
        if request.suggested_topic and request.suggested_topic.strip():
            request = request.model_copy(
                update={"topic": request.suggested_topic.strip()[:300]}
            )
        # 低质量研究样本 → 注入边界约束（不覆盖用户已写的同名约束）
        quality_guards: dict = {}
        if report is not None:
            from xhs_skill.research.quality import generation_guards_from_quality

            quality_guards = generation_guards_from_quality(report.search_quality)
            guard_constraints = list(quality_guards.get("constraints") or [])
            if guard_constraints:
                existing = list(request.constraints or [])
                merged = existing + [c for c in guard_constraints if c not in existing]
                request = request.model_copy(update={"constraints": merged})
        account_profile = None
        if request.account_id:
            account_profile = await self.accounts.profile_async(request.account_id, tenant_id)
            if account_profile is not None:
                request = adapt_request_to_profile(request, account_profile)
        from xhs_skill.generation.mechanism_force import preferred_mechanisms_from_report
        from xhs_skill.generation.title_proxy import annotate_title_candidates

        preferred_mechs = preferred_mechanisms_from_report(report)
        titles = build_titles(request, report)
        topic_vector: list[float] | None = None
        title_vectors: dict[str, list[float]] | None = None
        rank_meta: dict[str, object] = {"channels": ["legacy"]}
        try:
            title_embedder = get_embedding_provider()
            embed_inputs = [request.topic, *[item.title for item in titles]]
            vectors = await title_embedder.embed(embed_inputs)
            topic_vector = vectors[0]
            title_vectors = {
                item.id: vector for item, vector in zip(titles, vectors[1:], strict=True)
            }
        except Exception:
            topic_vector, title_vectors = None, None

        if self.hybrid_ranker_enabled:
            titles, relevance, rank_meta = await self.hybrid_ranker.rank_async(
                titles,
                request.topic,
                topic_vector=topic_vector,
                title_vectors=title_vectors,
                limit=len(titles),
                apply_mmr=True,
            )
        else:
            ranked_titles, relevance = self.learning_ranker.rank(titles, request.topic)
            from xhs_skill.ranking import mmr_rerank

            titles = mmr_rerank(
                ranked_titles,
                relevance=relevance,
                limit=len(ranked_titles),
                embeddings=title_vectors,
            )
            rank_meta = {
                "channels": [
                    "lambdamart"
                    if self.learning_ranker.model is not None
                    else "audited-rule-fallback"
                ],
                "hybrid": False,
            }
        title_proxy_board = annotate_title_candidates(
            titles, topic=request.topic, preferred_mechanisms=preferred_mechs
        )

        body, pages = build_body(request, report)
        providers = self.providers.candidates(request.provider)
        generation_assumptions = ["未提供的信息按通用场景处理；发布前需由账号所有者确认。"]
        # 质量边界 assumptions（已在 constraints 注入；再写 assumptions 供人审阅）
        if quality_guards.get("strength") in {"hard", "soft"}:
            for asm in list(quality_guards.get("assumptions") or []):
                if asm not in generation_assumptions:
                    generation_assumptions.append(asm)
        selected_provider_name: str | None = None
        selected_model: str | None = None
        content_brief = build_content_brief(request, report)
        content_outline = build_content_outline(
            request,
            report,
            note_style=request.note_style,
            narrative_framework=request.narrative_framework,
            variant_index=int(request.variant_index or 0),
        )
        selected_title, cta, pinned_comment = (
            titles[0].title if titles else request.topic,
            content_outline.get("closing_cta") or "欢迎补充你的具体使用场景。",
            pick_pinned_comment(request, int(request.variant_index or 0)),
        )

        prompt = {
            "task": request.model_dump(mode="json"),
            "brief": content_brief,
            "outline": content_outline,
            "voice": voice_system_hint(request),
            "research": report.model_dump(mode="json") if report else None,
            "fallback_title": titles[0].title if titles else request.topic,
            "fallback_body": body,
        }
        schema = {
            "type": "object",
            "properties": {
                "selected_title": {"type": "string"},
                "body": {"type": "string"},
                "cta": {"type": "string"},
                "pinned_comment": {"type": "string"},
            },
            "required": ["selected_title", "body", "cta", "pinned_comment"],
            "additionalProperties": False,
        }

        provider_errors: list[str] = []
        for provider in providers:
            model = request.model if request.provider == provider.name and request.model else getattr(
                provider, "default_model", None
            )
            if not model:
                continue
            try:
                circuit = await self.concurrency.circuits.get(f"model:{provider.name}")
                await self.concurrency.provider_rate_limiter.require(f"model:{provider.name}")
                async with self.concurrency.operation_slot("generation", provider=provider.name):
                    await circuit.before_call()
                    try:
                        response = await provider.generate(
                            GenerationRequest(
                                model=model,
                                system=SYSTEM_PROMPT,
                                prompt=json.dumps(prompt, ensure_ascii=False),
                                output_schema=schema,
                            )
                        )
                    except Exception:
                        await circuit.record_failure()
                        raise
                    else:
                        await circuit.record_success()
                if response.data:
                    body = str(response.data.get("body", body))
                    body, _voice_notes = apply_voice_to_text(body, request)
                    selected_title = str(
                        response.data.get(
                            "selected_title", titles[0].title if titles else request.topic
                        )
                    )
                    cta = str(response.data.get("cta", "欢迎补充你的具体使用场景。"))
                    pinned_comment = str(
                        response.data.get("pinned_comment", pick_pinned_comment(request, 0))
                    )
                    selected_provider_name = provider.name
                    selected_model = model
                    break
                provider_errors.append(f"{provider.name}: structured output unavailable")
            except Exception as exc:
                provider_errors.append(f"{provider.name}: {type(exc).__name__}")

        if provider_errors and selected_provider_name is None:
            generation_assumptions.append(
                "模型调用未成功，已使用确定性离线回退（模板骨架，非个性化成稿）："
                + "; ".join(provider_errors[:5])
            )
        elif selected_provider_name is None:
            generation_assumptions.append(
                "未配置可用模型：交付为确定性离线模板，请人工改写场景与事实后再发布。"
            )

        # 离线路径也套用声线禁用词
        body, voice_notes = apply_voice_to_text(body, request)
        if is_checklist_style(request, content_outline):
            body = ensure_checkbox_body(body)
        topics, hashtags = build_topics_and_hashtags(request, report)
        from xhs_skill.generation.seo_balance import balance_tags

        seo_balance = balance_tags(topics, report)
        if seo_balance.get("topics"):
            topics = list(seo_balance["topics"])
            hashtags = list(seo_balance["hashtags"])
        body = append_hashtags_to_body(body, hashtags)
        # 正文（含模型改写/标签追加）确定后，分页与分镜与 body 对齐
        pages: list = []
        if request.format == "graphic":
            pages = pages_from_body(request, body, report, outline=content_outline)
        video_script = (
            build_video(
                request,
                body,
                outline=content_outline,
                duration_seconds=request.video_duration_seconds,
            )
            if request.format == "video"
            else None
        )
        keyword_map = build_keyword_map(request, report, topics=topics)

        claims = extract_claims(body, request.evidence)
        compliance = check_text(f"{selected_title}\n{body}", request.commercial_status)
        original_references = [
            note.body or note.snippet or note.title for note in (report.notes if report else [])
        ]
        originality = await originality_report_async(body, original_references)
        ai_style = ai_style_report(body)
        unverified_claims = [claim for claim in claims if not claim.verified]
        blocked = (
            not compliance["passed"]
            or not originality["publication_allowed"]
            or bool(unverified_claims)
        )
        digest = content_hash(
            selected_title,
            body,
            *(page.body_copy for page in pages) if request.format == "graphic" else (),
        )
        cover_options = build_cover_options(
            request,
            titles=titles,
            report=report,
            selected_title=selected_title,
            outline=content_outline,
        )

        package = DeliveryPackage(
            task_id=task_id,
            trace_id=trace_id,
            assumptions=generation_assumptions,
            research_summary={
                "coverage_warning": report.coverage_warning,
                "content_gaps": report.content_gaps,
            } if report else {},
            hot_notes=report.notes[:10] if report else [],
            trend_insights=report.trends[:10] if report else [],
            mechanisms=report.mechanisms[:5] if report else [],
            strategy={
                "objective": request.objective,
                "audience": request.target_audience or "正在做决策的用户",
                "content_angle": request.topic_angle or content_brief.get("angle") or "场景化决策支持",
                "distribution_mode": request.distribution_mode,
                "commercial_status": request.commercial_status,
                "seed_topic": seed_topic,
                "suggested_topic": request.suggested_topic,
                "topic_reason": request.topic_reason,
                "preferred_mechanisms": preferred_mechs,
                "title_proxy_board": title_proxy_board[:8],
                "seo_tag_balance": seo_balance,
                "brief": content_brief,
                "outline": {
                    "note_style": content_outline.get("note_style"),
                    "narrative_framework": content_outline.get("narrative_framework"),
                    "framework_label": content_outline.get("framework_label"),
                    "opening_hook": content_outline.get("opening_hook"),
                    "emotion_arc": content_outline.get("emotion_arc"),
                    "sections": content_outline.get("sections"),
                },
                "voice": voice_system_hint(request),
            },
            title_candidates=titles,
            selected_title=selected_title,
            cover_options=cover_options,
            body=body,
            graphic_pages=pages if request.format == "graphic" else [],
            video_script=video_script,
            keyword_map=keyword_map,
            topics=topics,
            hashtags=hashtags,
            pinned_comment=pinned_comment,
            cta=cta,
            claims=claims,
            originality_report=originality,
            compliance_report={**compliance, "ai_style": ai_style},
            ai_labeling={
                "ai_provenance": {
                    "text_generated": True,
                    "text_human_edited": False,
                    "images_generated": False,
                },
                "explicit_label_required": "REVIEW",
                "implicit_metadata_required": "REVIEW",
                "metadata_preservation": True,
            },
            quality_report={
                "title_diversity": len({title.mechanism for title in titles}),
                "fact_review_required": bool(unverified_claims),
                "unverified_claim_ids": [claim.id for claim in unverified_claims],
                "selected_provider": selected_provider_name,
                "selected_model": selected_model,
                "provider_attempts": provider_errors,
                "ranker": (
                    "hybrid-rrf-mmr"
                    if self.hybrid_ranker_enabled
                    else (
                        "lambdamart"
                        if self.learning_ranker.model is not None
                        else "audited-rule-fallback"
                    )
                ),
                "ranker_meta": rank_meta,
                "account_profile_applied": account_profile is not None,
                "account_profile_confidence": account_profile.confidence if account_profile else None,
                "content_brief": content_brief,
                "content_outline": content_outline,
                "voice_notes": voice_notes,
            },
            content_hash=digest,
            publication_status="BLOCKED" if blocked else "HUMAN_REVIEW_REQUIRED",
            human_review_required=[
                "确认所有个人经历和产品事实",
                "确认商业合作披露",
                "确认 AI 内容标识要求",
                "预览并批准最终发布版本",
            ],
        )
        readiness = score_delivery_package(package)
        package.quality_report["overall_score"] = readiness["overall_score"]
        package.quality_report["readiness"] = readiness
        # 质量边界写入 report，供 ux/发布流感知
        if quality_guards.get("strength") in {"hard", "soft"}:
            package.quality_report["search_quality_guards"] = quality_guards
            package.quality_report["disclaimer"] = quality_guards.get("disclaimer")
            if quality_guards.get("strength") == "hard":
                # 低质量强约束时加人审提示
                extra_review = "研究样本质量偏低，需人工核对所有事实与数字"
                if extra_review not in package.human_review_required:
                    package.human_review_required.append(extra_review)
        if blocked and quality_guards.get("disclaimer"):
            package.assumptions.append(quality_guards["disclaimer"])
        # 搜索质量置信注记：always present（good 也写，便于下游 ux/发布流感知）
        if report is not None:
            sq = dict(report.search_quality or {})
            package.quality_report["search_quality"] = {
                "score": sq.get("score"),
                "label": sq.get("label"),
                "delta": sq.get("delta"),
                "guards": quality_guards,
                "confidence_note": (
                    "研究样本质量良好，可信任选题与标题建议。"
                    if (quality_guards.get("strength") or "none") == "none"
                    else quality_guards.get("disclaimer") or ""
                ),
                "recommendations": sq.get("recommendations") or [],
            }

        # 可选：封面图生成旁路（失败不影响正文交付）；成功后入库为 asset_id 供发布使用
        try:
            cover_prompt = f"小红书封面：{request.topic}，风格：真实、克制、有场景感"
            img_result = await self.image_provider.generate_cover(cover_prompt)
            local_path = Path(img_result.path)
            package.quality_report["cover_image_local_path"] = str(local_path)
            if local_path.is_file():
                suffix = local_path.suffix.lower() or ".png"
                safe_topic = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", request.topic)[:40] or "cover"
                meta = self.asset_store.save_bytes(
                    tenant_id=tenant_id,
                    filename=f"cover-{safe_topic}{suffix}",
                    content_type=img_result.media_type,
                    content=local_path.read_bytes(),
                )
                package.cover_asset = meta.asset_id
                package.media_assets = [meta.asset_id, *package.media_assets]
                package.quality_report["cover_image_pending_ingest"] = False
                package.quality_report["cover_asset_id"] = meta.asset_id
                package.ai_labeling["ai_provenance"]["images_generated"] = True
                package.assumptions.append(
                    f"封面图已生成并入库为 asset_id={meta.asset_id}，可直接用于发布。"
                )
            else:
                package.quality_report["cover_image_pending_ingest"] = True
                package.assumptions.append(
                    "封面图 provider 返回了路径但文件不存在，已跳过入库。"
                )
        except (NotImplementedError, Exception) as exc:
            package.quality_report["cover_image_error"] = type(exc).__name__

        from xhs_skill.generation.creation_bundle import build_creation_bundle

        package.quality_report["creation_bundle"] = build_creation_bundle(package)
        return package

    async def rewrite(
        self,
        body: str,
        *,
        title: str = "",
        commercial_status: str = "NON_COMMERCIAL",
        constraints: list[str] | None = None,
        references: list[str] | None = None,
        tenant_id: str = "local",
    ) -> dict:
        """内容改写：有模型走 provider，无模型走确定性规则。

        两种路径都经过 compliance + ai_style + originality 门禁。
        """
        from xhs_skill.schemas.content import CommercialStatus

        try:
            commercial = CommercialStatus(commercial_status)
        except ValueError:
            commercial = CommercialStatus.NON_COMMERCIAL
        constraints = constraints or []
        references = [item for item in (references or []) if item]

        # 尝试 provider 结构化输出
        providers = self.providers.candidates(None)
        provider_result: str | None = None
        provider_changes: list[CleanupChange] = []
        provider_errors: list[str] = []

        prompt = {
            "task": "rewrite",
            "original_body": body,
            "constraints": [
                "删除空泛套话和无法验证的效果承诺",
                "增加具体场景、限制条件和不适合人群",
                "不编造事实、不添加未提供的数据",
            ] + constraints,
        }
        schema = {
            "type": "object",
            "properties": {
                "revised_body": {"type": "string"},
                "changes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "rule_id": {"type": "string"},
                            "before": {"type": "string"},
                            "after": {"type": "string"},
                            "reason": {"type": "string"},
                        },
                    },
                },
            },
            "required": ["revised_body"],
            "additionalProperties": False,
        }

        for provider in providers:
            model = getattr(provider, "default_model", None)
            if not model:
                continue
            try:
                circuit = await self.concurrency.circuits.get(f"model:{provider.name}")
                await self.concurrency.provider_rate_limiter.require(f"model:{provider.name}")
                async with self.concurrency.operation_slot("rewrite", provider=provider.name):
                    await circuit.before_call()
                    try:
                        response = await provider.generate(
                            GenerationRequest(
                                model=model,
                                system="你是内容改写助手。删套话、补场景边界、不编造事实。输出改写后的正文。",
                                prompt=json.dumps(prompt, ensure_ascii=False),
                                output_schema=schema,
                            )
                        )
                    except Exception:
                        await circuit.record_failure()
                        raise
                    else:
                        await circuit.record_success()
                if response.data and response.data.get("revised_body"):
                    provider_result = str(response.data["revised_body"])
                    raw_changes = response.data.get("changes") or []
                    if isinstance(raw_changes, list):
                        for item in raw_changes:
                            if not isinstance(item, dict):
                                continue
                            provider_changes.append(
                                CleanupChange(
                                    rule_id=str(item.get("rule_id") or "provider_rewrite"),
                                    before=str(item.get("before") or "")[:200],
                                    after=str(item.get("after") or "")[:200],
                                    reason=str(item.get("reason") or "模型结构化改写"),
                                )
                            )
                    break
                provider_errors.append(f"{provider.name}: structured output unavailable")
            except Exception as exc:
                provider_errors.append(f"{provider.name}: {type(exc).__name__}")

        # 确定性规则降噪（provider 失败时作为可解释回退；成功时仍作对照）
        cleanup = apply_cleanup_rules(body)

        # 使用 provider 结果或规则结果
        used_provider = provider_result is not None
        revised = provider_result if used_provider else cleanup.revised
        # provider 若返回结构化 changes 优先；否则用规则命中；再否则补一条汇总
        changes = provider_changes if provider_changes else cleanup.changes
        if used_provider and not changes and revised != body:
            # provider 改写了正文但未返回 changes 且规则未命中：避免“无改动”假象
            changes = [
                CleanupChange(
                    rule_id="provider_rewrite",
                    before=body[:200],
                    after=revised[:200],
                    reason="模型结构化改写（规则日志无命中）",
                )
            ]

        # 门禁：compliance + ai_style + originality（可选 references）
        compliance = check_text(f"{title}\n{revised}" if title else revised, commercial)
        ai_style = ai_style_report(revised)
        originality = await originality_report_async(revised, references)

        response = assemble_rewrite_response(
            original=body,
            revised=revised,
            changes=changes,
            compliance=compliance,
            ai_style=ai_style,
            originality=originality,
        )
        response["quality_report"]["rewrite_path"] = "provider" if used_provider else "deterministic_rules"
        response["quality_report"]["reference_count"] = len(references)
        if provider_errors:
            response["quality_report"]["provider_attempts"] = provider_errors[:5]
        if not used_provider and revised == body:
            response["quality_report"]["noop"] = True
            response["quality_report"]["note"] = "无模型可用且规则未命中，正文未改写"
        from xhs_skill.generation.diagnose_structure import structure_checks

        response["structure_checks"] = structure_checks(
            title=title, body=revised, cta="", pinned_comment=""
        )
        return response

    async def generate_variants(
        self,
        request: GenerateRequest,
        report: HotNotesReport | None = None,
        *,
        tenant_id: str = "local",
        variant_count: int = 3,
    ) -> dict:
        """多变体生成：同一 brief 下换标题钩子/置顶评角度，便于 A/B。"""
        n = max(1, min(int(variant_count), 5))
        packages = []
        styles_cycle = [
            request.note_style,
            "avoid_pitfall",
            "checklist",
            "comparison",
            "review",
        ]
        frameworks_cycle = [
            request.narrative_framework or "auto",
            "pas",
            "aida",
            "bab",
            "scqa",
        ]
        for i in range(n):
            variant_req = request.model_copy(
                update={
                    "candidate_count": max(request.candidate_count, 6 + i),
                    "variant_index": i,
                    "note_style": styles_cycle[i % len(styles_cycle)] or request.note_style,
                    "narrative_framework": frameworks_cycle[i % len(frameworks_cycle)],
                    "constraints": list(request.constraints)
                    + ([f"variant_angle:{i}"] if i else []),
                }
            )
            package = await self.generate(variant_req, report, tenant_id=tenant_id)
            from xhs_skill.generation.hooks import pick_pinned_comment

            package.pinned_comment = pick_pinned_comment(request, i)
            package.quality_report["variant_index"] = i
            packages.append(package)
        ranked = sorted(
            packages,
            key=lambda p: int((p.quality_report.get("readiness") or {}).get("overall_score") or 0),
            reverse=True,
        )
        return {
            "variants": [p.model_dump(mode="json") for p in ranked],
            "recommended_index": 0,
            "count": len(ranked),
        }
