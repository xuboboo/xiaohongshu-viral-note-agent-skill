"""清单型正文：自动拆 checkbox 条目与图文分页。"""

from __future__ import annotations

import re
from typing import Any

from xhs_skill.schemas.content import GenerateRequest, GraphicPage

_CHECK_LINE = re.compile(
    r"^(?:[-*•]|\d+[\.\)、]|□|☑|\[ \]|\[x\])\s*(.+)$",
    re.IGNORECASE | re.MULTILINE,
)
_SECTION_HEAD = re.compile(r"^【([^】]+)】")


def extract_checklist_items(body: str, *, max_items: int = 12) -> list[str]:
    """从正文提取可勾选条目（优先真正的列表行，其次章节标题）。"""
    items: list[str] = []
    seen: set[str] = set()

    def _push(text: str) -> None:
        text = text.strip()
        if not (2 <= len(text) <= 60):
            return
        key = text.casefold()
        if key in seen:
            return
        seen.add(key)
        items.append(text)

    # 1) 真正的列表 / checkbox 行
    for raw in (body or "").splitlines():
        line = raw.strip()
        match = _CHECK_LINE.match(line)
        if match:
            _push(match.group(1))
        if len(items) >= max_items:
            return items[:max_items]

    # 2) 「围绕：a；b」
    if len(items) < 3:
        for raw in (body or "").splitlines():
            line = raw.strip()
            if line.startswith("围绕："):
                for part in re.split(r"[；;、]", line[3:]):
                    _push(part.strip(" 。."))
                    if len(items) >= max_items:
                        return items[:max_items]

    # 3) 章节标题兜底
    if len(items) < 3:
        for raw in (body or "").splitlines():
            head = _SECTION_HEAD.match(raw.strip())
            if head:
                _push(head.group(1))
            if len(items) >= max_items:
                break

    return items[:max_items]


def ensure_checkbox_body(body: str, items: list[str] | None = None) -> str:
    """确保正文含 □ 勾选清单块。"""
    text = (body or "").rstrip()
    if text.count("□") >= 3:
        return _normalize_checkboxes_in_body(text) + ("\n" if not text.endswith("\n") else "")

    pool = list(items or [])
    if len(pool) < 3:
        pool.extend(extract_checklist_items(text))
    # 去重
    seen: set[str] = set()
    uniq: list[str] = []
    for item in pool:
        key = item.casefold()
        if key not in seen:
            seen.add(key)
            uniq.append(item)
    pool = uniq

    if len(pool) < 3:
        for part in text.split("\n\n"):
            first = part.strip().split("\n", 1)[0].strip()
            first = re.sub(r"^【|】$", "", first)
            if 4 <= len(first) <= 40 and first.casefold() not in seen:
                seen.add(first.casefold())
                pool.append(first)
            if len(pool) >= 5:
                break
    if not pool:
        return text + "\n"

    # 去掉旧的核对清单块再追加，避免重复
    lines = [ln for ln in text.splitlines() if not ln.strip().startswith("【核对清单】")]
    # 保留非纯 checkbox 正文
    body_core = "\n".join(
        ln for ln in lines if not (ln.strip().startswith("□") and "核对" not in ln)
    ).rstrip()
    block_lines = ["", "【核对清单】", *[f"□ {item}" for item in pool[:10]]]
    return body_core + "\n" + "\n".join(block_lines) + "\n"


def _normalize_checkboxes_in_body(text: str) -> str:
    lines: list[str] = []
    for raw in text.splitlines():
        match = _CHECK_LINE.match(raw.strip())
        if match and not raw.strip().startswith("□"):
            lines.append(f"□ {match.group(1).strip()}")
        else:
            lines.append(raw)
    return "\n".join(lines)


def checklist_pages(
    request: GenerateRequest,
    body: str,
    *,
    items_per_page: int = 3,
) -> list[GraphicPage]:
    """封面 + 每页 2–3 条 checkbox + 收尾页。"""
    items = extract_checklist_items(body)
    if not items:
        items = [f"确认{request.topic}使用场景", "写下不能接受的两点", "核对可验证证据", "划定不适合人群"]

    pages: list[GraphicPage] = [
        GraphicPage(
            page=1,
            purpose="cover",
            headline=f"{request.topic}清单",
            body_copy="按优先级勾选，不按情绪下单",
            visual_direction="大字标题 + 勾选预览",
            layout="上标题下清单预览",
        )
    ]
    n = max(2, min(int(items_per_page), 4))
    page_no = 2
    for i in range(0, len(items), n):
        chunk = items[i : i + n]
        body_copy = "\n".join(f"□ {item}" for item in chunk)
        pages.append(
            GraphicPage(
                page=page_no,
                purpose="checklist",
                headline=f"核对 {i + 1}-{i + len(chunk)}",
                body_copy=body_copy[:200],
                visual_direction="checkbox 列表卡片",
                layout="竖向勾选列表",
            )
        )
        page_no += 1
        if page_no > 9:
            break

    pages.append(
        GraphicPage(
            page=page_no,
            purpose="summary",
            headline="勾完再决定",
            body_copy="未勾选项先补信息；不适合的维度直接排除，避免硬买。",
            visual_direction="收尾总结页",
            layout="居中结论",
        )
    )
    return pages


def is_checklist_style(request: GenerateRequest, outline: dict[str, Any] | None = None) -> bool:
    style = (outline or {}).get("note_style") or getattr(request, "note_style", None) or ""
    return str(style).lower() in {"checklist", "清单"}