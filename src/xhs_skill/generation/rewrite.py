"""内容改写管线：纯函数清理规则 + 结构化变更日志。

有模型时走 provider 结构化输出；无模型时走确定性规则降噪。
两种路径都经过 compliance + ai_style 门禁。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class CleanupChange:
    """单条结构化变更记录。"""
    rule_id: str
    before: str
    after: str
    reason: str


@dataclass
class CleanupResult:
    """清理结果。"""
    original: str
    revised: str
    changes: list[CleanupChange] = field(default_factory=list)


# 结确定性清理规则：(rule_id, pattern, replacement, reason)
_CLEANUP_RULES: list[tuple[str, str | re.Pattern[str], str, str]] = [
    ("empty_hype", r"宝子们谁懂啊", "", "删除空泛情绪套话"),
    ("empty_hype", r"狠狠拿捏", "适合这个具体场景", "替换空泛夸赞为场景化表达"),
    ("empty_hype", r"闭眼冲", "建议先核对自己的使用需求", "替换盲目推荐为理性建议"),
    ("empty_hype", r"绝绝子", "在这个场景下表现突出", "替换空泛夸赞为场景化表达"),
    ("empty_hype", r"真的会谢", "", "删除空泛网络烂梗"),
    ("empty_hype", r"YYDS", "在这个场景下更省心", "替换口号式夸赞"),
    ("structure_wordy", r"首先[，,]?", "第一，", "简化连接词"),
    ("structure_wordy", r"其次[，,]?", "第二，", "简化连接词"),
    ("structure_wordy", r"最后[，,]?", "第三，", "简化连接词"),
    ("structure_wordy", r"总而言之[，,]?\s*", "", "删除冗余总结开头"),
    ("ai_filler", r"✨{2,}", "✨", "限制装饰符号数量"),
    ("ai_filler", r"家人们[，,]?\s*", "", "删除 AI 风格称呼"),
    ("ai_filler", r"作为一名AI[，,]?\s*", "", "删除 AI 自我介绍式套话"),
]


def apply_cleanup_rules(text: str) -> CleanupResult:
    """应用确定性清理规则，返回结构化变更日志。"""
    revised = text
    changes: list[CleanupChange] = []

    for rule_id, pattern, replacement, reason in _CLEANUP_RULES:
        compiled = re.compile(pattern) if isinstance(pattern, str) else pattern
        matches = compiled.findall(revised)
        if matches:
            for match in matches:
                before_str = match if isinstance(match, str) else match[0] if match else ""
                changes.append(CleanupChange(
                    rule_id=rule_id,
                    before=before_str,
                    after=replacement,
                    reason=reason,
                ))
            revised = compiled.sub(replacement, revised)

    # 清理多余空行
    revised = re.sub(r"\n{3,}", "\n\n", revised).strip()

    # 数字被误删时补回核对块（不编造新数）
    from xhs_skill.generation.entity_guard import restore_missing_numbers

    restored, missing_nums = restore_missing_numbers(text, revised)
    if missing_nums:
        changes.append(
            CleanupChange(
                rule_id="entity_preserve",
                before=",".join(missing_nums[:8]),
                after="【数据核对·请人工确认】",
                reason="清理规则误删数字，已补回核对块",
            )
        )
        revised = restored

    return CleanupResult(original=text, revised=revised, changes=changes)


def assemble_rewrite_response(
    original: str,
    revised: str,
    changes: list[CleanupChange],
    compliance: dict,
    ai_style: dict,
    originality: dict | None = None,
) -> dict:
    """组装 API/MCP 统一返回结构。"""
    from xhs_skill.generation.entity_guard import check_entity_preservation

    compliance_blocked = not compliance.get("passed", True)
    originality_blocked = bool(
        originality is not None and not originality.get("publication_allowed", True)
    )
    blocked = compliance_blocked or originality_blocked
    high_ai = ai_style.get("ai_style_score", 0) > 50
    entity_guard = check_entity_preservation(original, revised)
    if entity_guard.get("risk_flags") and not blocked:
        publication_status = "HUMAN_REVIEW_REQUIRED"
    else:
        publication_status = (
            "BLOCKED"
            if blocked
            else ("HUMAN_REVIEW_REQUIRED" if high_ai else "REVIEW")
        )

    quality_report: dict = {
        "compliance": compliance,
        "ai_style": ai_style,
        "change_count": len(changes),
        "entity_preservation": entity_guard,
    }
    if originality is not None:
        quality_report["originality"] = originality

    return {
        "original": original,
        "revised": revised,
        "changes": [
            {"rule_id": c.rule_id, "before": c.before, "after": c.after, "reason": c.reason}
            for c in changes
        ],
        "quality_report": quality_report,
        "entity_preservation": entity_guard,
        "publication_status": publication_status,
    }