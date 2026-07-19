"""交付包元素联动：标题簇、封面、分页、口播一览 + 校验。"""

from __future__ import annotations

import re
from typing import Any

from xhs_skill.core.title_mechanisms import normalize_mechanism, tag_title_mechanisms
from xhs_skill.schemas.content import DeliveryPackage


def polish_title_cluster(selected: str, candidates: list[str], *, limit: int = 5) -> list[str]:
    """围绕主标题生成/清洗标题簇，去重截断。"""
    base = (selected or "").strip()
    out: list[str] = []
    seen: set[str] = set()

    def _add(text: str) -> None:
        t = re.sub(r"\s+", " ", text).strip()[:48]
        key = t.casefold()
        if t and key not in seen:
            seen.add(key)
            out.append(t)

    _add(base)
    for c in candidates:
        _add(c)
    if base:
        if "？" not in base and "?" not in base:
            _add(base.rstrip("。！") + "？")
        if "避坑" not in base:
            _add(f"{base[:20]}｜避坑版" if len(base) > 4 else f"{base}避坑")
        if "适合谁" not in base:
            _add(f"{base[:18]}适合谁" if len(base) > 4 else f"{base}适合谁")
    return out[:limit]


def align_cover_with_title(package: DeliveryPackage) -> list[dict[str, Any]]:
    """让封面 headline 与 selected_title / outline 对齐，并校验字数档。"""
    title = package.selected_title
    options: list[dict[str, Any]] = []
    for i, cover in enumerate(package.cover_options[:3]):
        headline = cover.headline
        if i == 0 and title:
            headline = title[:28]
        hl = (headline or "")[:28]
        sub = (cover.subheadline or "")[:20]
        checks = _cover_copy_checks(hl, sub, title=title if i == 0 else None)
        options.append(
            {
                "headline": hl,
                "subheadline": sub,
                "supporting_tag": cover.supporting_tag,
                "composition": cover.composition,
                "visual_subject": cover.visual_subject,
                "aligned_to_title": i == 0,
                "headline_len": len(hl),
                "subheadline_len": len(sub),
                "copy_checks": checks,
            }
        )
    if not options and title:
        hl = title[:28]
        options.append(
            {
                "headline": hl,
                "subheadline": "先看场景与边界",
                "supporting_tag": "怎么选",
                "composition": "主体居中，标题上方",
                "visual_subject": title[:12],
                "aligned_to_title": True,
                "headline_len": len(hl),
                "subheadline_len": 7,
                "copy_checks": _cover_copy_checks(hl, "先看场景与边界", title=title),
            }
        )
    return options


def _cover_copy_checks(headline: str, subheadline: str, *, title: str | None) -> dict[str, Any]:
    hl_len = len(headline or "")
    sub_len = len(subheadline or "")
    issues: list[str] = []
    # 主标题建议 8–14 字（允许到 28 截断展示）
    if hl_len and (hl_len < 6 or hl_len > 16):
        issues.append("headline_length_out_of_sweet_spot")
    if sub_len and (sub_len < 4 or sub_len > 12):
        issues.append("subheadline_length_out_of_sweet_spot")
    if title and headline and title[:8] not in headline and headline[:8] not in title:
        issues.append("headline_title_mismatch")
    return {
        "ok": not issues,
        "issues": issues,
        "headline_sweet_spot": "8-14",
        "subheadline_sweet_spot": "6-10",
    }


def page_headline_suggestions(package: DeliveryPackage) -> list[dict[str, Any]]:
    """从图文页提炼短标题 + 角色 + 可截图金句。"""
    role_cycle = ["钩子", "证据", "对比或清单", "边界", "CTA"]
    rows: list[dict[str, Any]] = []
    for i, page in enumerate(package.graphic_pages[:8]):
        headline = (page.headline or "").strip()
        short = re.sub(r"^【|】$", "", headline)[:16]
        body = (page.body_copy or "").strip()
        # 取首句作金句
        gold = re.split(r"[。！？\n]", body)[0].strip()[:28] if body else short
        purpose = (page.purpose or "").strip() or role_cycle[i % len(role_cycle)]
        rows.append(
            {
                "page": page.page,
                "purpose": purpose,
                "role": role_cycle[i % len(role_cycle)],
                "headline": headline,
                "short_title": short,
                "gold_line": gold,
                "body_preview": body[:60],
            }
        )
    return rows


def script_beat_summary(package: DeliveryPackage) -> dict[str, Any] | None:
    script = package.video_script
    if not script:
        return None
    duration = float(script.duration_seconds or 0) or 1.0
    full_narration = " ".join(s.narration for s in script.scenes)
    chars = len(re.sub(r"\s+", "", full_narration))
    # 中文口播约 4 字/秒
    cps = chars / duration if duration else 0
    issues: list[str] = []
    if not (script.hook_0_3s or "").strip():
        issues.append("missing_hook_0_3s")
    if cps > 5.5:
        issues.append("narration_too_dense")
    if cps < 2.0 and chars > 0:
        issues.append("narration_too_sparse")
    subtitle_cards = [
        {
            "start": s.start,
            "end": s.end,
            "text": (s.subtitle or s.narration or "")[:24],
            "max_chars": 24,
        }
        for s in script.scenes
    ]
    return {
        "duration_seconds": script.duration_seconds,
        "hook": script.hook_0_3s,
        "scene_count": len(script.scenes),
        "beats": [
            {
                "start": s.start,
                "end": s.end,
                "subtitle": s.subtitle,
                "narration": s.narration[:60],
            }
            for s in script.scenes
        ],
        "subtitle_cards": subtitle_cards,
        "ending": script.ending,
        "cover_copy": script.cover_copy,
        "voice_checks": {
            "char_count": chars,
            "chars_per_second": round(cps, 2),
            "target_cps": "3.5-5.0",
            "issues": issues,
            "ok": not issues,
        },
    }


def _readiness(bundle: dict[str, Any]) -> dict[str, Any]:
    score = 0.4
    notes: list[str] = []
    if bundle.get("title_cluster"):
        score += 0.15
    covers = bundle.get("covers") or []
    if covers and all((c.get("copy_checks") or {}).get("ok", True) for c in covers[:1]):
        score += 0.15
    else:
        notes.append("封面文案字数或对齐需人工微调")
    if bundle.get("pages"):
        score += 0.1
    video = bundle.get("voiceover") or bundle.get("video")
    if video:
        score += 0.1
        vc = video.get("voice_checks") or {}
        if not vc.get("ok", True):
            notes.append("口播密度需调整")
            score -= 0.05
    if bundle.get("hashtags") or bundle.get("topics"):
        score += 0.1
    score = max(0.0, min(1.0, round(score, 3)))
    return {"score": score, "notes": notes, "ready_for_draft": score >= 0.65}


def build_creation_bundle(package: DeliveryPackage) -> dict[str, Any]:
    """标题/封面/分页/口播一览，便于宿主直接展示。"""
    candidate_titles = [c.title for c in package.title_candidates]
    cluster = polish_title_cluster(package.selected_title, candidate_titles)
    mechanisms = []
    for t in [package.selected_title, *cluster]:
        mechanisms.extend(tag_title_mechanisms(t))
    mech_present = list(dict.fromkeys(normalize_mechanism(m) for m in mechanisms))
    voice = script_beat_summary(package)
    bundle: dict[str, Any] = {
        "schema": "creation_bundle.v1",
        "selected_title": package.selected_title,
        "title_cluster": cluster,
        "title_mechanisms": mech_present,
        "covers": align_cover_with_title(package),
        "pages": page_headline_suggestions(package),
        "voiceover": voice,
        "video": voice,  # 兼容旧字段
        "cta": package.cta,
        "pinned_comment": package.pinned_comment,
        "topics": package.topics,
        "hashtags": package.hashtags,
        "seo_tags": {
            "topics": package.topics,
            "hashtags": package.hashtags,
        },
    }
    # 封面资产是否真图
    has_asset = bool(getattr(package, "cover_asset", None) or package.quality_report.get("cover_asset"))
    bundle["cover_media"] = {
        "mode": "image_asset" if has_asset else "text_only_cover_spec",
        "has_image_asset": has_asset,
    }
    bundle["readiness"] = _readiness(bundle)
    return bundle


def rewrite_title_and_hook(
    body: str,
    title: str = "",
    *,
    prefer_question: bool = True,
) -> dict[str, str | list[str]]:
    """从正文抽一句作标题/钩子建议（规则，不调用模型）。"""
    chunks = [p.strip() for p in body.split("\n\n") if p.strip()]
    first = chunks[0] if chunks else title or "先看场景再决定"
    first = re.sub(r"^【[^】]+】", "", first).strip()
    first = first.split("\n")[0][:40]
    new_title = title.strip() or first[:28]
    if prefer_question and "？" not in new_title and "?" not in new_title and len(new_title) < 24:
        new_title = new_title.rstrip("。！") + "？"
    hook = first[:48]
    mechs = tag_title_mechanisms(new_title) or tag_title_mechanisms(hook)
    risk_flags: list[str] = []
    if any(x in (new_title + hook) for x in ("根治", "100%", "闭眼冲", "永久")):
        risk_flags.append("hype_or_absolute_claim")
    if len(new_title) > 30:
        risk_flags.append("title_too_long")
    return {
        "suggested_title": new_title,
        "opening_hook": hook,
        "mechanism": mechs[0] if mechs else "决策搜索",
        "mechanisms": mechs,
        "risk_flags": risk_flags,
    }