from __future__ import annotations

import re
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import NAMESPACE_URL, uuid5

from dateutil.parser import parse as parse_date

from xhs_skill.schemas.research import HotNoteCandidate, SearchResult

_TRACKING_PREFIXES = ("utm_", "spm", "source", "share_", "xhsshare")
_METRIC_PATTERNS = {
    "likes": re.compile(
        r"(?:点赞|赞|likes?|❤|❤️)\s*[:：]?\s*([\d.]+\s*[万wWkK]?)", re.I
    ),
    "saves": re.compile(
        r"(?:收藏|collect|saves?|collects?)\s*[:：]?\s*([\d.]+\s*[万wWkK]?)", re.I
    ),
    "comments": re.compile(
        r"(?:评论|comments?|回复)\s*[:：]?\s*([\d.]+\s*[万wWkK]?)", re.I
    ),
    "shares": re.compile(
        r"(?:分享|转发|shares?|reposts?)\s*[:：]?\s*([\d.]+\s*[万wWkK]?)", re.I
    ),
    "views": re.compile(
        r"(?:浏览|阅读|播放|views?|reads?)\s*[:：]?\s*([\d.]+\s*[万wWkK]?)", re.I
    ),
}


def canonicalize_url(url: str) -> str:
    split = urlsplit(url)
    query = [
        (key, value)
        for key, value in parse_qsl(split.query, keep_blank_values=True)
        if not key.lower().startswith(_TRACKING_PREFIXES)
    ]
    return urlunsplit(
        (split.scheme.lower(), split.netloc.lower(), split.path.rstrip("/"), urlencode(query), "")
    )


def parse_metric(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return max(0, int(value))
    text = str(value).strip().replace(",", "")
    match = re.fullmatch(r"([\d.]+)\s*([万wWkK]?)", text)
    if not match:
        return None
    number = float(match.group(1))
    suffix = match.group(2).lower()
    if suffix in {"万", "w"}:
        number *= 10000
    elif suffix == "k":
        number *= 1000
    return int(number)


def extract_metrics(text: str) -> dict[str, int | None]:
    metrics: dict[str, int | None] = {}
    for name, pattern in _METRIC_PATTERNS.items():
        match = pattern.search(text)
        metrics[name] = parse_metric(match.group(1)) if match else None
    return metrics


def result_to_candidate(result: SearchResult) -> HotNoteCandidate:
    metadata = result.metadata or {}
    combined = f"{result.title} {result.snippet or ''}"
    extracted = extract_metrics(combined)
    published_at = result.published_at
    if isinstance(published_at, str):
        try:
            published_at = parse_date(published_at)
        except (ValueError, TypeError):
            published_at = None
    canonical = canonicalize_url(result.url)

    def metric(name: str) -> int | None:
        parsed = parse_metric(metadata.get(name))
        return parsed if parsed is not None else extracted.get(name)

    return HotNoteCandidate(
        id=str(uuid5(NAMESPACE_URL, canonical)),
        url=result.url,
        canonical_url=canonical,
        title=result.title.strip(),
        snippet=result.snippet,
        body=metadata.get("body"),
        author_name=metadata.get("author_name"),
        published_at=published_at,
        likes=metric("likes"),
        saves=metric("saves"),
        comments=metric("comments"),
        shares=metric("shares"),
        views=parse_metric(metadata.get("views"))
        if parse_metric(metadata.get("views")) is not None
        else extracted.get("views"),
        followers=parse_metric(metadata.get("followers")),
        source_provider=result.source_provider,
        source_rank=result.source_rank,
        indexed_at=datetime.now(UTC),
        commercial_probability=metadata.get("commercial_probability"),
        data_confidence=0.9 if metadata.get("rights_status") == "AUTHORIZED" else 0.55,
        rights_status=metadata.get("rights_status", "PUBLIC_INDEX_ONLY"),
    )
