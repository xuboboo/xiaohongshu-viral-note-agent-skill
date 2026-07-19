"""从公开索引样本蒸馏「可复用机制」，禁止复用原文独特表达。"""

from __future__ import annotations

from collections import Counter
from typing import Any

from xhs_skill.core.title_mechanisms import primary_title_mechanism, tag_title_mechanisms
from xhs_skill.research.query_expansion import classify_query_intent, keyword_matrix_from_query
from xhs_skill.schemas.research import ContentMechanism, HotNoteCandidate

# 机制 → 默认结构（公开创作者实践 + 站内决策内容常见骨架）
_STRUCTURES: dict[str, list[str]] = {
    "决策搜索": ["结论/推荐立场", "评价标准", "场景匹配", "边界与不适合", "行动建议"],
    "避坑警示": ["常见坑", "为什么踩", "如何自检", "替代思路", "适合谁"],
    "对比决策": ["对比维度表", "场景 A 胜出", "场景 B 胜出", "预算线", "怎么选"],
    "清单收藏": ["清单总览", "逐项要点", "可截图汇总", "自检表", "收藏理由"],
    "教程转化": ["目标", "步骤", "材料/条件", "失败点", "验收标准"],
    "实证种草": ["使用场景", "可观察变化", "限制条件", "不适合", "结论"],
    "人群边界": ["谁适合", "谁不适合", "信号清单", "例外情况", "决策"],
    "场景切片": ["场景还原", "约束条件", "方案", "体验顺序", "避雷"],
    "数字结果": ["数字承诺边界", "证据层级", "过程", "可复现条件", "CTA"],
    "价格锚点": ["预算档", "同档对比", "性价比标准", "省钱边界", "推荐"],
    "问答体": ["问题重述", "直接答案", "依据", "例外", "追问引导"],
    "新手友好": ["零基础定义", "最小步骤", "常见误区", "升级路径", "资源"],
}


def _opening_for(mechanism: str) -> str:
    return {
        "决策搜索": "结论先行 + 核心词前置",
        "避坑警示": "先报坑名，再给自检",
        "对比决策": "维度表开场",
        "清单收藏": "可截图总览",
        "教程转化": "目标与耗时",
        "实证种草": "场景+边界，禁编造亲测数据",
        "问答体": "复述用户问题",
    }.get(mechanism, "结论先行")


def _promise_for(mechanism: str, query: str) -> str:
    return {
        "决策搜索": f"用明确标准判断「{query}」是否适合自己",
        "避坑警示": f"标出「{query}」常见坑与自检清单",
        "对比决策": f"按场景拆开「{query}」选项差异",
        "清单收藏": f"可收藏的「{query}」核对清单",
        "教程转化": f"可照做的「{query}」步骤与验收",
        "实证种草": f"在可核对场景下描述「{query}」观察点（不编造数据）",
    }.get(mechanism, f"帮助用户在具体场景下决策「{query}」")


def distill_mechanisms(
    notes: list[HotNoteCandidate],
    query: str,
    *,
    limit: int = 8,
) -> list[ContentMechanism]:
    """按标题机制聚合，而非「一文一机制」重复灌水。"""
    counter: Counter[str] = Counter()
    evidence: dict[str, list[str]] = {}
    for note in notes[:40]:
        mech = primary_title_mechanism(note.title)
        counter[mech] += 1
        evidence.setdefault(mech, []).append(note.id)

    intent = classify_query_intent(query)
    primary_intent = str(intent.get("primary") or "decision")

    # 保证主意图对应机制至少出现
    intent_to_mech = {
        "decision": "决策搜索",
        "comparison": "对比决策",
        "avoid": "避坑警示",
        "tutorial": "教程转化",
        "review": "实证种草",
        "checklist": "清单收藏",
        "budget": "价格锚点",
        "scene": "场景切片",
    }
    seed_mech = intent_to_mech.get(primary_intent, "决策搜索")
    if seed_mech not in counter:
        counter[seed_mech] = max(1, counter.get(seed_mech, 0))

    ranked = counter.most_common(limit)
    mechanisms: list[ContentMechanism] = []
    for mech, count in ranked:
        share = count / max(sum(counter.values()), 1)
        structure = list(_STRUCTURES.get(mech) or _STRUCTURES["决策搜索"])
        mechanisms.append(
            ContentMechanism(
                audience="准备做决策、正在搜索对比的用户",
                audience_stage="方案研究" if primary_intent in {"decision", "comparison"} else "问题认知",
                user_problem=f"不确定如何判断{query}是否匹配自己的场景与预算",
                topic_angle=mech,
                content_promise=_promise_for(mech, query),
                title_mechanism=mech,
                cover_mechanism="人群/场景 + 单一承诺（封面字尽量含核心词）",
                opening_mechanism=_opening_for(mech),
                body_structure=structure,
                trust_signals=["具体场景", "评价标准", "缺点/边界", "不适合人群"],
                emotional_strategy="克制、可核对",
                search_intent=query,
                product_exposure_position=0.55,
                cta_type="评论补充场景或预算",
                reusable_principles=[
                    "核心词前置标题前 10–12 字（公开 SEO 实践启发）",
                    "每段只承载一个信息点",
                    "用清单/对比/边界提高可收藏性",
                    f"样本中「{mech}」约占标题机制 {share:.0%}（n≈{count}）",
                    "话题标签建议 3–5 个：核心 + 长尾 + 时令",
                ],
                prohibited_reuse=["原句", "原作者经历", "原图", "未验证互动数据", "虚假亲测"],
            )
        )
        # 把证据 id 塞进 reusable 不合适；保留在 principles 的 n 即可
        _ = evidence.get(mech)
    return mechanisms


def distill_search_playbook(
    notes: list[HotNoteCandidate],
    query: str,
) -> dict[str, Any]:
    """可执行的搜索向创作 playbook（挂到 hot_insights）。"""
    titles = [n.title for n in notes[:30]]
    matrix = keyword_matrix_from_query(query, notes_titles=titles)
    mech_counts = Counter(primary_title_mechanism(t) for t in titles)
    front_loaded = 0
    core = (query or "").strip()[:8]
    for title in titles:
        head = (title or "")[:12]
        if core and any(ch in head for ch in core if len(ch.strip()) >= 1) and any(token and token in head for token in re_split_tokens(core)):
            # 粗检：query 字符命中标题前缀
            front_loaded += 1
    n = max(len(titles), 1)
    return {
        "schema": "search_playbook.v1",
        "query_intent": matrix.get("query_intent"),
        "keyword_matrix": matrix,
        "title_mechanism_mix": [
            {"mechanism": k, "count": v, "share": round(v / max(sum(mech_counts.values()), 1), 3)}
            for k, v in mech_counts.most_common(6)
        ],
        "sample_title_frontload_rate": round(front_loaded / n, 3),
        "seo_checklist": [
            "标题：主词尽量前 10–12 字",
            "封面：文案与标题/标签语义一致",
            "正文：前段出现主词与场景，结构用清单或对比",
            "标签：3–5 个，首 tag 对齐核心词",
            "互动：引导具体场景评论，提高有效讨论（非刷量）",
            "收藏钩子：清单/对照表/边界表",
        ],
        "engagement_priority_hint": (
            "公开营销文常强调：收藏/评论/分享权重往往高于纯点赞；"
            "本 skill 排序在有指标时提高 saves/comments/shares 权重（估算，非官方 CES）。"
        ),
        "disclaimer": "策略来自公开 SEO/营销文蒸馏 + 样本统计，不是站内官方算法。",
    }


def re_split_tokens(text: str) -> list[str]:
    import re as _re

    parts = _re.split(r"[\s,，、/|]+", text or "")
    out: list[str] = []
    for p in parts:
        p = p.strip()
        if len(p) >= 2:
            out.append(p)
        # 中文无空格时切 2–4 字滑动窗
    if len(out) <= 1 and text and not _re.search(r"[A-Za-z]", text):
        t = _re.sub(r"\s+", "", text)
        for size in (3, 2):
            for i in range(0, max(0, len(t) - size + 1)):
                out.append(t[i : i + size])
            if out:
                break
    return list(dict.fromkeys(out))[:12]


def multi_tag_notes(notes: list[HotNoteCandidate], *, limit: int = 10) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for note in notes[:limit]:
        rows.append(
            {
                "note_id": note.id,
                "title": note.title,
                "mechanisms": tag_title_mechanisms(note.title),
            }
        )
    return rows