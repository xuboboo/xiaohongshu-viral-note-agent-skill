"""账号声线：把 brand_voice / 画像约束落到文案提示与后处理。"""

from __future__ import annotations

import re
from typing import Any

from xhs_skill.schemas.content import GenerateRequest


def voice_constraints(request: GenerateRequest) -> dict[str, Any]:
    voice = request.brand_voice if isinstance(request.brand_voice, dict) else {}
    tone = str(voice.get("tone") or voice.get("style") or "克制专业").strip()
    banned = voice.get("banned_phrases") or voice.get("avoid") or []
    if isinstance(banned, str):
        banned = [banned]
    preferred = voice.get("preferred_phrases") or voice.get("prefer") or []
    if isinstance(preferred, str):
        preferred = [preferred]
    formality = str(voice.get("formality") or "neutral")
    return {
        "tone": tone[:40],
        "formality": formality[:20],
        "banned_phrases": [str(x)[:40] for x in list(banned)[:12]],
        "preferred_phrases": [str(x)[:40] for x in list(preferred)[:8]],
        "persona": str(voice.get("persona") or "")[:60],
    }


def apply_voice_to_text(text: str, request: GenerateRequest) -> tuple[str, list[str]]:
    """删除声线禁用词，返回 (text, notes)。"""
    vc = voice_constraints(request)
    notes: list[str] = []
    revised = text
    for phrase in vc["banned_phrases"]:
        if phrase and phrase in revised:
            revised = revised.replace(phrase, "")
            notes.append(f"removed_banned:{phrase}")
    revised = re.sub(r"\n{3,}", "\n\n", revised).strip()
    # 口语/书面轻微调整标记（不大幅改写）
    if vc["formality"] == "formal":
        for a, b in (("宝子", "你"), ("家人们", "各位"), ("绝绝子", "表现突出")):
            if a in revised:
                revised = revised.replace(a, b)
                notes.append(f"formalize:{a}")
    return revised, notes


def voice_system_hint(request: GenerateRequest) -> str:
    vc = voice_constraints(request)
    parts = [f"语气：{vc['tone']}"]
    if vc["persona"]:
        parts.append(f"人设：{vc['persona']}")
    if vc["banned_phrases"]:
        parts.append("禁止使用：" + "、".join(vc["banned_phrases"][:6]))
    if vc["preferred_phrases"]:
        parts.append("可适当使用：" + "、".join(vc["preferred_phrases"][:4]))
    return "；".join(parts)