"""选择器版本钉扎、健康快照与失败告警。"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xhs_skill.core.config import Settings, get_settings
from xhs_skill.core.http_client import get_http_pool

logger = logging.getLogger(__name__)


def selector_bundle_fingerprint(selector_path: Path) -> dict[str, str]:
    """对选择器 YAML 做内容哈希，用于版本钉扎。"""
    if not selector_path.is_file():
        return {
            "path": str(selector_path),
            "sha256": "",
            "error": "selector_file_missing",
        }
    raw = selector_path.read_bytes()
    return {
        "path": str(selector_path.resolve()),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": str(len(raw)),
    }


def enrich_selector_health(
    result: dict[str, Any],
    settings: Settings | None = None,
) -> dict[str, Any]:
    """附加版本钉扎字段；若配置了 pin 且不匹配则标 degraded。"""
    settings = settings or get_settings()
    pin = selector_bundle_fingerprint(settings.xhs_selector_config)
    expected = (settings.selector_pin_version or "").strip().lower()
    actual = pin.get("sha256", "")
    pin_ok = True
    pin_note = "unpinned"
    if expected:
        pin_ok = bool(actual) and actual.lower() == expected
        pin_note = "match" if pin_ok else "mismatch"
    enriched = {
        **result,
        "checked_at": datetime.now(UTC).isoformat(),
        "selector_pin": {
            **pin,
            "expected_sha256": expected or None,
            "status": pin_note,
            "ok": pin_ok if expected else True,
        },
    }
    if expected and not pin_ok:
        enriched["ok"] = False
        enriched.setdefault("missing", [])
        if "selector_pin_mismatch" not in enriched.get("alerts", []):
            alerts = list(enriched.get("alerts") or [])
            alerts.append("selector_pin_mismatch")
            enriched["alerts"] = alerts
    return enriched


async def maybe_alert_selector_health(result: dict[str, Any], settings: Settings | None = None) -> None:
    """失败时 POST webhook（best-effort，不抛到主路径）。"""
    settings = settings or get_settings()
    if result.get("ok"):
        return
    webhook = (settings.selector_canary_alert_webhook or "").strip()
    if not webhook:
        logger.warning(
            "selector canary failed: missing=%s error=%s pin=%s",
            result.get("missing"),
            result.get("error"),
            (result.get("selector_pin") or {}).get("status"),
        )
        return
    payload = {
        "event": "selector_canary_failed",
        "checked_at": result.get("checked_at"),
        "ok": result.get("ok"),
        "missing": result.get("missing"),
        "error": result.get("error"),
        "ui_version_hint": result.get("ui_version_hint"),
        "selector_pin": result.get("selector_pin"),
        "alerts": result.get("alerts"),
    }
    try:
        client = await get_http_pool().get()
        response = await client.post(webhook, json=payload, timeout=15.0)
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001 — 告警失败不可阻断 canary
        logger.warning("selector canary webhook failed: %s", type(exc).__name__)


def persist_selector_health_snapshot(
    result: dict[str, Any],
    *,
    account_id: str,
    tenant_id: str,
    settings: Settings | None = None,
) -> Path | None:
    """落盘最近一次 canary 结果，供定时任务/人工对账。"""
    settings = settings or get_settings()
    try:
        root = Path("./data/canary")
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{tenant_id}_{account_id}.json"
        path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path
    except OSError:
        return None