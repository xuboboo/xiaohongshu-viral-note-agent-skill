"""热门机制 → 标题候选强制覆盖（不足则从 hook 库补，不洗稿）。"""

from __future__ import annotations

from uuid import uuid4

from xhs_skill.core.title_mechanisms import (
    mechanism_coverage,
    normalize_mechanism,
    tag_title_mechanisms,
)
from xhs_skill.generation.hooks import expand_title_hooks
from xhs_skill.schemas.content import GenerateRequest, TitleCandidate
from xhs_skill.schemas.research import HotNotesReport


def preferred_mechanisms_from_report(
    report: HotNotesReport | None, *, limit: int = 3
) -> list[str]:
    if report is None:
        return []
    stats = (report.hot_insights or {}).get("title_mechanism_stats") or []
    out: list[str] = []
    for row in stats:
        if isinstance(row, dict) and row.get("mechanism"):
            out.append(normalize_mechanism(str(row["mechanism"])))
        if len(out) >= limit:
            break
    if not out and report.mechanisms:
        for m in report.mechanisms[:limit]:
            if m.title_mechanism:
                out.append(normalize_mechanism(m.title_mechanism))
    return list(dict.fromkeys(out))[:limit]


def ensure_mechanism_coverage(
    candidates: list[TitleCandidate],
    request: GenerateRequest,
    *,
    preferred: list[str],
    limit: int | None = None,
) -> tuple[list[TitleCandidate], dict]:
    """确保候选标题覆盖 preferred 机制；返回 (候选, 覆盖报告)。"""
    pool = list(candidates)
    cap = limit or max(request.candidate_count, 8)
    titles = [c.title for c in pool]
    cov = mechanism_coverage(titles, preferred)
    missing = list(cov.get("missing") or [])
    if not missing:
        return pool[:cap], {**cov, "supplemented": []}

    # 从 hook 库补机制
    hooks = expand_title_hooks(request)
    supplemented: list[str] = []
    seen = {c.title.casefold() for c in pool}
    for need in missing:
        for hook in hooks:
            hm = normalize_mechanism(hook.mechanism or "")
            tags = tag_title_mechanisms(hook.title)
            if need != hm and need not in tags:
                continue
            key = hook.title.casefold()
            if key in seen:
                continue
            seen.add(key)
            pool.append(
                TitleCandidate(
                    id=str(uuid4()),
                    title=hook.title[:60],
                    mechanism=need,
                    target_audience=request.target_audience or "正在做决策的用户",
                    primary_keyword=request.topic,
                )
            )
            supplemented.append(need)
            break
        # 仍缺则造极简结构标题（不抄原文）
        if need not in supplemented:
            synthetic = f"{request.topic}｜{need}"[:48]
            if synthetic.casefold() not in seen:
                seen.add(synthetic.casefold())
                pool.append(
                    TitleCandidate(
                        id=str(uuid4()),
                        title=synthetic,
                        mechanism=need,
                        target_audience=request.target_audience or "正在做决策的用户",
                        primary_keyword=request.topic,
                    )
                )
                supplemented.append(need)

    final_titles = [c.title for c in pool]
    cov2 = mechanism_coverage(final_titles, preferred)
    return pool[:cap], {**cov2, "supplemented": supplemented, "preferred": preferred}