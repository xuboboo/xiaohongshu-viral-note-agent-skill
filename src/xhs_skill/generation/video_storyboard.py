"""口播分镜：按时长模板切场景（15/30/45/60 秒）。"""

from __future__ import annotations

from typing import Any

from xhs_skill.schemas.content import GenerateRequest, VideoScene, VideoScript

# duration -> list of (end_ratio cumulative or absolute segments as (start, end, role, default_subtitle))
_DURATION_TEMPLATES: dict[int, list[dict[str, Any]]] = {
    15: [
        {"start": 0, "end": 3, "role": "hook", "subtitle": "钩子", "visual": "标题卡/问题特写"},
        {"start": 3, "end": 10, "role": "core", "subtitle": "核心一点", "visual": "主体演示"},
        {"start": 10, "end": 15, "role": "cta", "subtitle": "互动", "visual": "字幕引导评论"},
    ],
    30: [
        {"start": 0, "end": 3, "role": "hook", "subtitle": "钩子", "visual": "痛点开场"},
        {"start": 3, "end": 12, "role": "scene", "subtitle": "场景", "visual": "使用场景切换"},
        {"start": 12, "end": 22, "role": "proof", "subtitle": "标准/证据", "visual": "要点列表"},
        {"start": 22, "end": 30, "role": "cta", "subtitle": "行动", "visual": "总结+评论引导"},
    ],
    45: [
        {"start": 0, "end": 3, "role": "hook", "subtitle": "钩子", "visual": "快速展示主题与问题"},
        {"start": 3, "end": 15, "role": "scene", "subtitle": "1 使用场景", "visual": "场景切换"},
        {"start": 15, "end": 27, "role": "pain", "subtitle": "2 核心痛点", "visual": "问题清单"},
        {"start": 27, "end": 39, "role": "proof", "subtitle": "3 具体证据", "visual": "证据与边界"},
        {"start": 39, "end": 45, "role": "cta", "subtitle": "说说你的场景", "visual": "总结与评论引导"},
    ],
    60: [
        {"start": 0, "end": 4, "role": "hook", "subtitle": "钩子", "visual": "标题+冲突"},
        {"start": 4, "end": 14, "role": "scene", "subtitle": "场景分层", "visual": "多场景快切"},
        {"start": 14, "end": 28, "role": "educate", "subtitle": "判断标准", "visual": "分步讲解"},
        {"start": 28, "end": 42, "role": "proof", "subtitle": "证据与误区", "visual": "对比/打叉示意"},
        {"start": 42, "end": 52, "role": "boundary", "subtitle": "不适合谁", "visual": "边界卡片"},
        {"start": 52, "end": 60, "role": "cta", "subtitle": "行动+互动", "visual": "结尾字幕"},
    ],
}


def normalize_video_duration(seconds: int | None) -> int:
    if seconds is None:
        return 45
    try:
        value = int(seconds)
    except (TypeError, ValueError):
        return 45
    allowed = (15, 30, 45, 60)
    return min(allowed, key=lambda item: abs(item - value))


def build_video_script(
    request: GenerateRequest,
    body: str,
    *,
    duration_seconds: int | None = None,
    outline: dict[str, Any] | None = None,
) -> VideoScript:
    """按时长模板生成分镜；口播优先取正文段落与大纲开场。"""
    duration = normalize_video_duration(
        duration_seconds
        if duration_seconds is not None
        else getattr(request, "video_duration_seconds", None)
    )
    template = _DURATION_TEMPLATES[duration]
    chunks = [part.strip() for part in body.split("\n\n") if part.strip()]
    opening = ""
    if outline and outline.get("opening_hook"):
        opening = str(outline["opening_hook"])[:60]
    hook = (opening or (chunks[0][:48] if chunks else "") or f"选{request.topic}，先别急着看卖点。").strip()
    if not hook:
        hook = f"选{request.topic}，先看场景。"

    # 为非 hook 段落准备旁白池
    narrations = chunks[1:] if len(chunks) > 1 else chunks
    if not narrations:
        narrations = [
            f"先确认{request.topic}的使用场景。",
            "写下你最不能接受的两点。",
            "只相信具体证据和边界。",
        ]

    scenes: list[VideoScene] = []
    narr_idx = 0
    for slot in template:
        role = slot["role"]
        if role == "hook":
            narration = hook[:80]
        elif role == "cta":
            cta = ""
            if outline and outline.get("closing_cta"):
                cta = str(outline["closing_cta"])[:80]
            narration = cta or f"你选{request.topic}最在意什么？评论区说一个场景。"
        else:
            narration = narrations[narr_idx % len(narrations)][:80]
            narr_idx += 1
        scenes.append(
            VideoScene(
                start=float(slot["start"]),
                end=float(slot["end"]),
                visual=str(slot["visual"]),
                narration=narration,
                subtitle=str(slot["subtitle"])[:24],
                b_roll=f"role:{role}",
            )
        )

    cover = f"{request.topic}｜{duration}s"
    if outline and outline.get("note_style_label"):
        cover = f"{request.topic}｜{outline['note_style_label']}"

    return VideoScript(
        duration_seconds=duration,
        hook_0_3s=hook[:48],
        scenes=scenes,
        ending=f"你选{request.topic}最在意什么？",
        cover_copy=cover[:28],
        post_caption=body[:500],
    )