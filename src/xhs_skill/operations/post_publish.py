"""发后指标同步：解析纯函数 + 浏览器抓取编排。

职责拆分：
- parse_published_metrics(text, labels?) → 纯函数，可单测
- BrowserPublishedMetricsSync.sync → 浏览器编排，调用纯函数
"""
from __future__ import annotations

import asyncio
import re
import socket
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from xhs_skill.browser import LoginFlow
from xhs_skill.core.config import Settings, get_settings
from xhs_skill.core.errors import AuthenticationRequiredError
from xhs_skill.enterprise.postgres import EnterprisePostgresStore
from xhs_skill.operations.models import PostPublishSyncTask, PublishedMetrics
from xhs_skill.operations.repository import OperationsRepository
from xhs_skill.schemas.publishing import LoginStatus

# 默认标签别名：中文 → 英文字段名
DEFAULT_METRIC_LABELS: dict[str, tuple[str, ...]] = {
    "views": ("观看", "阅读", "曝光"),
    "likes": ("点赞",),
    "saves": ("收藏",),
    "comments": ("评论",),
    "shares": ("分享",),
    "follows": ("新增关注", "涨粉"),
    "profile_visits": ("主页访问",),
    "search_views": ("搜索", "搜索流量"),
    "recommendation_views": ("推荐", "推荐流量"),
}

# 策略一：标签 → 邻近数字（原始实现）
_LABEL_ADJACENT_RE = re.compile(
    r"(?P<label>[^\d\n]{1,10})(?:[^。\n]{0,24}?)(?P<number>[\d,.]+\s*[万亿wWkK]?)",
)

# 策略二：key:value / key：value / key value
_KV_RE = re.compile(
    r"(?P<key>[观看点赞收藏评论分享曝光搜索推荐新增关注涨粉主页访问搜索流量推荐流量]+)"
    r"\s*[：:]\s*(?P<number>[\d,.]+\s*[万亿wWkK]?)",
)


def parse_number(value: str) -> int | None:
    """解析含万/k/K 后缀的数字字符串。"""
    match = re.search(r"([\d,.]+)\s*([万亿wWkK]?)", value)
    if not match:
        return None
    number = float(match.group(1).replace(",", ""))
    suffix = match.group(2).lower()
    if suffix in {"万", "w"}:
        number *= 10_000
    elif suffix in {"亿"}:
        number *= 100_000_000
    elif suffix == "k":
        number *= 1_000
    return int(number)


@dataclass
class MetricParseResult:
    """解析结果 + 诊断信息。"""
    values: dict[str, int | None] = field(default_factory=dict)
    hit_labels: dict[str, str] = field(default_factory=dict)   # field → 命中标签
    strategy_used: str = "none"
    text_length: int = 0
    null_fields: list[str] = field(default_factory=list)


def parse_published_metrics(
    text: str,
    labels: dict[str, tuple[str, ...]] | None = None,
) -> MetricParseResult:
    """从页面文本中解析发布指标。纯函数，无副作用。

    多策略顺序：
    1. KV 策略：key:value / key：value（适用于结构化表格）
    2. 标签邻近策略：标签后 0-24 字符内出现数字（适用于连续文本）

    缺字段保持 null，绝不编造值。
    """
    if labels is None:
        labels = DEFAULT_METRIC_LABELS

    values: dict[str, int | None] = {}
    hit_labels: dict[str, str] = {}
    strategy_used = "none"

    # 策略一：KV 模式
    kv_hits: dict[str, int] = {}
    for m in _KV_RE.finditer(text):
        key_text = m.group("key")
        num = parse_number(m.group("number"))
        if num is None:
            continue
        for field_name, label_aliases in labels.items():
            if field_name in kv_hits:
                continue
            # 较长别名优先，避免「搜索」抢占「搜索流量」
            for alias in sorted(label_aliases, key=len, reverse=True):
                if alias in key_text:
                    kv_hits[field_name] = num
                    hit_labels[field_name] = alias
                    break
    if kv_hits:
        strategy_used = "kv"
        for field_name in labels:
            values[field_name] = kv_hits.get(field_name)

    # 策略二：标签邻近（补齐 KV 未命中字段；数字不得跨行，降低标签互抢）
    missing_fields = [f for f in labels if values.get(f) is None]
    if missing_fields:
        adjacent_hits: dict[str, int] = {}
        for field_name in missing_fields:
            label_aliases = labels[field_name]
            for alias in sorted(label_aliases, key=len, reverse=True):
                escaped = re.escape(alias)
                # 同段内：标签后 0–24 非数字字符，禁止跨行吞并下一行的数字
                match = re.search(
                    rf"{escaped}[^\d\n]{{0,24}}([\d,.]+\s*[万亿wWkK]?)",
                    text,
                )
                if match:
                    num = parse_number(match.group(1))
                    if num is not None:
                        adjacent_hits[field_name] = num
                        hit_labels[field_name] = alias
                        break
        if adjacent_hits:
            strategy_used = "kv+label_adjacent" if kv_hits else "label_adjacent"
            for field_name in labels:
                if values.get(field_name) is None:
                    values[field_name] = adjacent_hits.get(field_name)

    # 保证所有声明字段都在 values 中（含全 null）
    for field_name in labels:
        values.setdefault(field_name, None)

    null_fields = [f for f, v in values.items() if v is None]

    return MetricParseResult(
        values=values,
        hit_labels=hit_labels,
        strategy_used=strategy_used,
        text_length=len(text),
        null_fields=null_fields,
    )


class BrowserPublishedMetricsSync:
    """Best-effort post-publication metric sync from an authorized creator session.

    Missing values stay null. UI changes fail the task and are retried; values are never fabricated.
    """

    def __init__(self, login_flow: LoginFlow, settings: Settings | None = None) -> None:
        self.login_flow = login_flow
        self.settings = settings or get_settings()

    async def _collect_structured_metric_text(self, page) -> tuple[str, str]:
        """优先从结构化节点抽取指标文本，再回退 body.inner_text。

        返回 (text, source) source ∈ structured_dom | body_text
        """
        # 常见创作者中心指标卡片/列表选择器（失败则静默回退）
        candidate_css = [
            "[class*='data']",
            "[class*='metric']",
            "[class*='statistic']",
            "[class*='interact']",
            "[class*='note-info']",
            "table",
            "[role='table']",
            "dl",
        ]
        chunks: list[str] = []
        for css in candidate_css:
            try:
                loc = page.locator(css)
                count = min(await loc.count(), 12)
                for index in range(count):
                    try:
                        piece = (await loc.nth(index).inner_text(timeout=800))[:4_000]
                    except Exception:
                        continue
                    if piece and any(ch.isdigit() for ch in piece):
                        chunks.append(piece)
            except Exception:
                continue
        if chunks:
            # 去重保序
            seen: set[str] = set()
            ordered: list[str] = []
            for item in chunks:
                key = item.strip()
                if key and key not in seen:
                    seen.add(key)
                    ordered.append(key)
            text = "\n".join(ordered)[:80_000]
            if text.strip():
                return text, "structured_dom"
        body = (await page.locator("body").inner_text())[:80_000]
        return body, "body_text"

    async def sync(self, task: PostPublishSyncTask) -> PublishedMetrics:
        status = await self.login_flow.status(task.account_id, task.tenant_id)
        session = self.login_flow.get_active(task.account_id, task.tenant_id)
        if status.status != LoginStatus.AUTHENTICATED or not session:
            raise AuthenticationRequiredError("Authorized creator session is required")
        target = task.note_url or "https://creator.xiaohongshu.com/creator/notes"
        await session.page.goto(target, wait_until="domcontentloaded")
        await asyncio.sleep(1)
        text, text_source = await self._collect_structured_metric_text(session.page)

        result = parse_published_metrics(text)

        if all(v is None for v in result.values.values()):
            raise RuntimeError(
                f"No recognizable note metrics were found on the authorized page "
                f"(text_length={result.text_length}, strategy={result.strategy_used}, "
                f"text_source={text_source})"
            )

        # 诊断写入 content_features，避免“有解析诊断但成功路径丢掉”
        debug_features: dict[str, str | int | bool] = {
            "parse_strategy": result.strategy_used,
            "parse_text_length": result.text_length,
            "parse_null_count": len(result.null_fields),
            "parse_text_source": text_source,
        }
        if result.hit_labels:
            debug_features["parse_hit_labels"] = ",".join(
                f"{k}:{v}" for k, v in sorted(result.hit_labels.items())
            )
        if result.null_fields:
            debug_features["parse_null_fields"] = ",".join(result.null_fields)

        return PublishedMetrics(
            note_id=task.note_id,
            account_id=task.account_id,
            tenant_id=task.tenant_id,
            snapshot_at=datetime.now(UTC),
            source="AUTHORIZED_BROWSER",
            content_features={**(task.content_features or {}), **debug_features},
            **result.values,
        )


class PostPublishSyncWorker:
    def __init__(
        self,
        login_flow: LoginFlow | None = None,
        repository: OperationsRepository | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.login_flow = login_flow or LoginFlow(self.settings)
        self.repository = repository or OperationsRepository(self.settings)
        self.adapter = BrowserPublishedMetricsSync(self.login_flow, self.settings)
        self.postgres = (
            EnterprisePostgresStore(self.settings)
            if self.settings.postgres_state_enabled
            else None
        )
        self._stop = asyncio.Event()

    async def enqueue_for_result(
        self,
        *,
        tenant_id: str,
        account_id: str,
        note_id: str,
        note_url: str | None,
        content_features: dict | None = None,
    ) -> list[PostPublishSyncTask]:
        if not self.settings.post_publish_sync_enabled:
            return []
        tasks = []
        now = datetime.now(UTC)
        for delay in sorted(set(self.settings.post_publish_sync_delays_minutes)):
            task = PostPublishSyncTask(
                tenant_id=tenant_id,
                account_id=account_id,
                note_id=note_id,
                note_url=note_url,
                content_features=dict(content_features or {}),
                due_at=now + timedelta(minutes=max(1, int(delay))),
                max_attempts=self.settings.post_publish_sync_max_attempts,
            )
            if self.postgres is not None:
                await self.postgres.enqueue_post_publish_sync(task)
                tasks.append(task)
            else:
                tasks.append(self.repository.enqueue_post_publish_sync(task))
        return tasks

    async def run_once(self, tenant_id: str, worker_id: str | None = None) -> int:
        worker = worker_id or f"{socket.gethostname()}-{uuid4().hex[:8]}"
        if self.postgres is not None:
            rows = await self.postgres.claim_post_publish_sync(
                tenant_id=tenant_id,
                worker_id=worker,
                lease_seconds=self.settings.post_publish_sync_lease_seconds,
                limit=20,
            )
            tasks = [PostPublishSyncTask.model_validate(dict(row["payload"])) for row in rows]
        else:
            tasks = self.repository.claim_post_publish_sync(
                tenant_id=tenant_id,
                worker_id=worker,
                now=datetime.now(UTC),
                lease_seconds=self.settings.post_publish_sync_lease_seconds,
                limit=20,
            )
        for task in tasks:
            try:
                metrics = await self.adapter.sync(task)
                if self.postgres is not None:
                    await self.postgres.save_published_metrics(metrics)
                    await self.postgres.finish_post_publish_sync(
                        tenant_id=tenant_id,
                        task_id=task.id,
                        worker_id=worker,
                        success=True,
                    )
                else:
                    self.repository.save_metrics(metrics)
                    self.repository.finish_post_publish_sync(task, success=True)
            except Exception as exc:
                retry_delay = min(24 * 60, 5 * (2 ** min(task.attempts, 8)))
                retry_at = datetime.now(UTC) + timedelta(minutes=retry_delay)
                if self.postgres is not None:
                    await self.postgres.finish_post_publish_sync(
                        tenant_id=tenant_id,
                        task_id=task.id,
                        worker_id=worker,
                        success=False,
                        error=f"{type(exc).__name__}: {exc}",
                        retry_at=retry_at,
                    )
                else:
                    self.repository.finish_post_publish_sync(
                        task,
                        success=False,
                        error=f"{type(exc).__name__}: {exc}",
                        retry_at=retry_at,
                    )
        return len(tasks)

    async def run_forever(self, tenant_id: str = "local", poll_seconds: float = 10.0) -> None:
        while not self._stop.is_set():
            if tenant_id == "*" and self.postgres is not None:
                processed = sum(
                    [
                        await self.run_once(item)
                        for item in await self.postgres.list_tenant_ids()
                    ]
                )
            else:
                processed = await self.run_once(tenant_id)
            if processed == 0:
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=poll_seconds)
                except TimeoutError:
                    pass

    async def close(self) -> None:
        self._stop.set()
        if self.postgres is not None:
            await self.postgres.close()