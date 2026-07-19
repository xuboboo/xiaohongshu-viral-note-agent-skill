"""改写实体/数字/功效句保留：防止清理规则误伤可核验事实。"""

from __future__ import annotations

import re
from typing import Any

# 数字、百分比、货币、常见单位
_NUM_RE = re.compile(
    r"(?:"
    r"\d+(?:\.\d+)?\s*(?:%|％|元|块|万|千|g|kg|ml|mL|L|cm|mm|寸|小时|分钟|天|周|个月|年)"
    r"|\d+(?:\.\d+)?%"
    r"|¥\s*\d+(?:\.\d+)?"
    r"|￥\s*\d+(?:\.\d+)?"
    r"|\d{2,}"
    r")"
)

# 功效/承诺类短句（改写时不得静默删除）
_CLAIMISH_RE = re.compile(
    r"(?:保证|承诺|根治|治愈|100%|永久|无副作用|药到病除|立刻见效|三天见效)[^\n。！？]{0,24}"
)

# 专有名词启发式：连续中文专名 / 英文品牌
_PROPER_RE = re.compile(r"[A-Za-z][A-Za-z0-9]{1,}(?:\s+[A-Za-z][A-Za-z0-9]+)?|[\u4e00-\u9fff]{2,8}(?:牌|系列|Pro|Max)")


def extract_preserve_tokens(text: str) -> dict[str, list[str]]:
    """从原文抽取应保留的 token 集合。"""
    numbers = list(dict.fromkeys(_NUM_RE.findall(text or "")))
    claims = list(dict.fromkeys(m.group(0).strip() for m in _CLAIMISH_RE.finditer(text or "")))
    propers = list(dict.fromkeys(_PROPER_RE.findall(text or "")))[:20]
    return {
        "numbers": numbers[:30],
        "claim_phrases": claims[:15],
        "proper_nouns": propers,
    }


def check_entity_preservation(original: str, revised: str) -> dict[str, Any]:
    """检查改写是否丢了数字/功效短句；专有名词仅作提示。"""
    tokens = extract_preserve_tokens(original)
    missing_numbers = [n for n in tokens["numbers"] if n not in (revised or "")]
    missing_claims = [c for c in tokens["claim_phrases"] if c not in (revised or "")]
    missing_propers = [p for p in tokens["proper_nouns"] if p not in (revised or "")]
    risk_flags: list[str] = []
    if missing_numbers:
        risk_flags.append("missing_numbers")
    if missing_claims:
        risk_flags.append("missing_claim_phrases")
    if len(missing_propers) >= 2:
        risk_flags.append("missing_proper_nouns")
    return {
        "preserved": not missing_numbers and not missing_claims,
        "tokens": tokens,
        "missing_numbers": missing_numbers,
        "missing_claim_phrases": missing_claims,
        "missing_proper_nouns": missing_propers[:10],
        "risk_flags": risk_flags,
        "hint": (
            "改写应保留可核验数字与功效表述；若需删除请走 QUALIFY/HUMAN_REVIEW，勿静默抹掉。"
            if risk_flags
            else "实体与数字保留检查通过。"
        ),
    }


def restore_missing_numbers(original: str, revised: str) -> tuple[str, list[str]]:
    """若数字被规则误删，在文末以「数据核对」块补回（不编造新数）。"""
    check = check_entity_preservation(original, revised)
    missing = list(check.get("missing_numbers") or [])
    if not missing:
        return revised, []
    block = "【数据核对·请人工确认】" + "、".join(missing[:12])
    if block in revised:
        return revised, missing
    text = (revised or "").rstrip() + "\n\n" + block
    return text, missing