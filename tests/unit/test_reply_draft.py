"""授权评论回复草稿。"""
import pytest

from xhs_skill.generation.reply_draft import (
    build_authorized_reply_drafts,
    reply_draft_to_dict,
)


def test_reply_draft_never_auto_submits():
    draft = build_authorized_reply_drafts("这个适合油皮吗？", note_context="防晒")
    payload = reply_draft_to_dict(draft)
    assert payload["auto_submit"] is False
    assert payload["requires_human_submit"] is True
    assert len(payload["draft_replies"]) >= 1


def test_reply_draft_flags_risks():
    draft = build_authorized_reply_drafts("假货吧？加我微信代理")
    assert draft.risks
    assert any("导流" in r or "负面" in r for r in draft.risks)


def test_empty_comment_rejected():
    with pytest.raises(ValueError):
        build_authorized_reply_drafts("  ")