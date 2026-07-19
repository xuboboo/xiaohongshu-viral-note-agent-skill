"""标题钩子模板：按意图扩展候选，减少同质八句。"""

from __future__ import annotations

from uuid import uuid4

from xhs_skill.core.title_mechanisms import normalize_mechanism
from xhs_skill.schemas.content import GenerateRequest, TitleCandidate

# (intent, mechanism, template) — {topic} {audience} {product}
HOOK_BANK: list[tuple[str, str, str]] = [
    # intent, mechanism, template
    ("search", "搜索精准", "{topic}怎么选？先看这5个真实场景"),
    ("search", "长尾场景", "{audience}选{topic}，真正该盯哪几项"),
    ("search", "清单", "{topic}避坑清单：5个容易忽略的细节"),
    ("search", "对比决策", "{topic}对比：别只看参数表上的数字"),
    ("avoid", "避坑警示", "第一次选{topic}，别只看宣传页"),
    ("avoid", "失败边界", "{topic}翻车点：这3类人不适合"),
    ("avoid", "经验教训", "关于{topic}，我更建议先确认这3件事"),
    ("recommend", "决策支持", "{topic}适合谁？优缺点一次讲清"),
    ("recommend", "人群定位", "{audience}用{product}，边界先说清"),
    ("recommend", "克制专业", "从使用场景出发，重新判断{topic}"),
    ("story", "反差", "看起来都差不多的{topic}，实际差在这里"),
    ("story", "场景切片", "通勤/居家/出差：{topic}该怎么换思路"),
    ("seo", "关键词前置", "{topic}怎么选｜{audience}版判断标准"),
    ("seo", "问答体", "为什么{topic}总踩坑？先回答这2个问题"),
]


def _fill(template: str, request: GenerateRequest) -> str:
    audience = (request.target_audience or "普通人").strip()[:12]
    product = ""
    if isinstance(request.product, dict):
        product = str(request.product.get("name") or "")[:16]
    product = product or request.topic
    try:
        return template.format(topic=request.topic, audience=audience, product=product)
    except (KeyError, ValueError):
        return template.replace("{topic}", request.topic)


def expand_title_hooks(request: GenerateRequest) -> list[TitleCandidate]:
    """按分发意图挑选钩子，再补全库内多样性。"""
    intent = str(request.distribution_mode or "hybrid").lower()
    preferred: set[str] = set()
    if "search" in intent:
        preferred |= {"search", "seo", "avoid"}
    elif "recommend" in intent:
        preferred |= {"recommend", "story", "avoid"}
    else:
        preferred |= {"search", "recommend", "avoid", "story", "seo"}

    if request.objective and "search" in request.objective.lower():
        preferred.add("search")
        preferred.add("seo")

    ordered = [row for row in HOOK_BANK if row[0] in preferred]
    ordered += [row for row in HOOK_BANK if row[0] not in preferred]

    candidates: list[TitleCandidate] = []
    seen: set[str] = set()
    for _intent, mechanism, template in ordered:
        title = _fill(template, request).strip()
        key = title.casefold()
        if not title or key in seen:
            continue
        seen.add(key)
        candidates.append(
            TitleCandidate(
                id=str(uuid4()),
                title=title[:60],
                mechanism=normalize_mechanism(mechanism),
                target_audience=request.target_audience or "正在做决策的用户",
                primary_keyword=request.topic,
            )
        )
        if len(candidates) >= max(request.candidate_count, 8):
            break
    return candidates


def build_pinned_comment_templates(request: GenerateRequest) -> list[str]:
    topic = request.topic
    return [
        f"你选{topic}最在意哪一点？预算 / 场景 / 耐用，评论区说一个就行。",
        f"如果你已经买过{topic}，最想提醒新手避开的是哪一步？",
        "需要我按「通勤 / 居家 / 差旅」拆一版对照表吗？留言你的场景。",
    ]


def pick_pinned_comment(request: GenerateRequest, index: int = 0) -> str:
    options = build_pinned_comment_templates(request)
    return options[index % len(options)]