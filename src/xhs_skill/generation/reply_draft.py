"""授权评论回复草稿：只生成建议文案，绝不自动提交。

死守边界：不调用发布/点赞/评论 API；输出仅供账号所有者人工粘贴。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class ReplyDraft:
    comment_id: str | None
    note_id: str | None
    original_comment: str
    tone: str
    draft_replies: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    requires_human_submit: bool = True
    auto_submit: bool = False  # 永远 False


_HYPE = re.compile(r"(宝子们|绝绝子|闭眼冲|狠狠拿捏)")


def build_authorized_reply_drafts(
    original_comment: str,
    *,
    note_context: str = "",
    tone: str = "helpful",
    comment_id: str | None = None,
    note_id: str | None = None,
    max_candidates: int = 3,
) -> ReplyDraft:
    """根据用户评论生成 1–3 条可人工发送的回复草稿。"""
    text = (original_comment or "").strip()
    if not text:
        raise ValueError("original_comment is required")

    risks: list[str] = []
    if _HYPE.search(text):
        risks.append("评论含情绪化套话，回复避免跟着起哄")
    if any(token in text for token in ("微信", "私信", "加我", "代理")):
        risks.append("疑似导流/私下交易，回复勿给联系方式")
    if any(token in text for token in ("假货", "骗人", "差评", "退款")):
        risks.append("负面情绪，先共情再给可核验信息")

    context_hint = (note_context or "").strip()[:80]
    drafts: list[str] = []

    if tone == "brief":
        drafts.append("感谢反馈。你说的场景很具体，我补充一点适用边界：先确认自己的使用频率和预算再决定。")
    elif tone == "empathetic":
        drafts.append(
            "理解你的担心。我不会替所有人打包票；更建议按你的实际场景核对参数和缺点，再决定是否适合。"
        )
    else:
        drafts.append(
            "谢谢提问。我更建议先对照自己的使用场景："
            "频率、最不能接受的问题、以及证据是否具体。"
            + (f"（笔记侧重点：{context_hint}）" if context_hint else "")
        )
        drafts.append(
            "如果你愿意补充预算和主要使用场景，我可以按条件帮你缩小选择范围，"
            "但不会给“闭眼入”式结论。"
        )
        drafts.append(
            "关于效果类问题：没有你自己的实测数据前，我只写可核对的判断标准，不承诺结果。"
        )

    drafts = drafts[: max(1, min(max_candidates, 5))]
    return ReplyDraft(
        comment_id=comment_id,
        note_id=note_id,
        original_comment=text,
        tone=tone,
        draft_replies=drafts,
        risks=risks,
        requires_human_submit=True,
        auto_submit=False,
    )


def reply_draft_to_dict(draft: ReplyDraft) -> dict:
    return {
        "comment_id": draft.comment_id,
        "note_id": draft.note_id,
        "original_comment": draft.original_comment,
        "tone": draft.tone,
        "draft_replies": draft.draft_replies,
        "risks": draft.risks,
        "requires_human_submit": True,
        "auto_submit": False,
        "policy": "authorized_human_submit_only",
    }