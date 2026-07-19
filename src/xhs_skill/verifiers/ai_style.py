from __future__ import annotations

AI_PATTERNS = ["宝子们", "谁懂啊", "狠狠拿捏", "闭眼冲", "首先", "其次", "最后", "总而言之"]


def ai_style_report(text: str) -> dict:
    matches = [pattern for pattern in AI_PATTERNS if pattern in text]
    score = min(100, len(matches) * 18 + (15 if text.count("✨") > 3 else 0))
    return {
        "ai_style_score": score,
        "detected_patterns": matches,
        "rewrite_actions": ["删除空泛套话", "增加具体场景", "说明适用边界"] if matches else [],
    }
