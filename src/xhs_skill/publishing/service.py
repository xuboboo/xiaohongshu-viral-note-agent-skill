from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from xhs_skill.browser.login_flow import LoginFlow
from xhs_skill.core.concurrency import get_concurrency_controller
from xhs_skill.core.config import Settings, get_settings
from xhs_skill.core.distributed_lock import get_distributed_lock_manager
from xhs_skill.core.errors import ConfigurationError, PublishBlockedError
from xhs_skill.core.identifiers import validate_identifier
from xhs_skill.core.security import content_hash
from xhs_skill.enterprise.approvals import EnterpriseApprovalService
from xhs_skill.operations.post_publish import PostPublishSyncWorker
from xhs_skill.publishing.adapters import (
    ManualExportPublisher,
    OfficialApiPublisher,
    PublishingAdapter,
)
from xhs_skill.publishing.approvals import create_approval, validate_approval
from xhs_skill.publishing.creator_studio import CreatorStudioPublisher
from xhs_skill.publishing.distributed import PostgresPublishCoordinator
from xhs_skill.publishing.publication_gate import (
    gate_block_details,
    reverify_package,
    reverify_package_async,
)
from xhs_skill.publishing.repository import PublishingRepository
from xhs_skill.publishing.scheduler import InProcessScheduler
from xhs_skill.schemas.content import DeliveryPackage
from xhs_skill.schemas.publishing import (
    PublishApproval,
    PublishDraft,
    PublishMode,
    PublishResult,
    PublishSchedule,
)
from xhs_skill.storage.assets import AssetStore


class PublishingService:
    def __init__(
        self,
        login_flow: LoginFlow | None = None,
        repository: PublishingRepository | None = None,
        settings: Settings | None = None,
        asset_store: AssetStore | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.login_flow = login_flow or LoginFlow(self.settings)
        self.repository = repository or PublishingRepository()
        self.asset_store = asset_store or AssetStore(self.settings)
        self.publisher: PublishingAdapter
        if self.settings.xhs_publish_adapter == "manual_export":
            self.publisher = ManualExportPublisher(self.settings)
        elif self.settings.xhs_publish_adapter == "official_api":
            self.publisher = OfficialApiPublisher()
        else:
            self.publisher = CreatorStudioPublisher(
                self.login_flow, self.settings, self.asset_store
            )
        self.scheduler = InProcessScheduler(self.repository)
        self.distributed_scheduler = (
            PostgresPublishCoordinator(self, self.settings)
            if self.settings.xhs_distributed_scheduling_enabled
            else None
        )
        self.concurrency = get_concurrency_controller()
        self.locks = get_distributed_lock_manager()
        self.enterprise_approvals = EnterpriseApprovalService()
        self.post_publish_sync = PostPublishSyncWorker(
            login_flow=self.login_flow, settings=self.settings
        )

    async def check_selector_health(
        self,
        account_id: str,
        tenant_id: str = "local",
        *,
        alert: bool = True,
    ) -> dict:
        """发布页选择器 canary；仅 Creator Studio 适配器支持。

        附加 selector 文件 sha256 钉扎；失败时可 webhook 告警并落盘快照。
        """
        from xhs_skill.publishing.selector_health import (
            enrich_selector_health,
            maybe_alert_selector_health,
            persist_selector_health_snapshot,
        )

        if not isinstance(self.publisher, CreatorStudioPublisher):
            result = {
                "ok": False,
                "error": "selector_health_unsupported",
                "adapter": self.settings.xhs_publish_adapter,
                "missing": [],
                "ui_version_hint": "unknown",
            }
        else:
            result = await self.publisher.check_selector_health(account_id, tenant_id)
        result = enrich_selector_health(result, self.settings)
        result["account_id"] = account_id
        result["tenant_id"] = tenant_id
        snapshot = persist_selector_health_snapshot(
            result, account_id=account_id, tenant_id=tenant_id, settings=self.settings
        )
        if snapshot:
            result["snapshot_path"] = str(snapshot)
        if alert and not result.get("ok"):
            await maybe_alert_selector_health(result, self.settings)
        return result

    @staticmethod
    def _canonical_content_hash(package: DeliveryPackage) -> str:
        return content_hash(
            package.selected_title,
            package.body,
            *package.media_assets,
            package.cover_asset or "",
            *package.topics,
            package.location or "",
        )

    def _validate_assets(self, tenant_id: str, package: DeliveryPackage) -> None:
        allowed_media = {
            "image/jpeg",
            "image/png",
            "image/webp",
            "image/gif",
            "video/mp4",
            "video/quicktime",
            "video/webm",
        }
        for asset_id in package.media_assets:
            self.asset_store.resolve(tenant_id, asset_id, allowed_types=allowed_media)
        if package.cover_asset:
            self.asset_store.resolve(
                tenant_id,
                package.cover_asset,
                allowed_types={"image/jpeg", "image/png", "image/webp"},
            )

    def _assert_package_publishable(self, package: DeliveryPackage) -> None:
        """仅信任服务端 reverify 后的包；BLOCKED / 未验证 claim / 报告失败均 fail-closed。"""
        if package.publication_status == "BLOCKED":
            raise PublishBlockedError(
                "Content package is blocked by server-side verification",
                details=gate_block_details(package),
            )
        if not package.compliance_report.get("passed", False):
            raise PublishBlockedError(
                "Final compliance verification did not pass",
                details=gate_block_details(package),
            )
        if not package.originality_report.get("publication_allowed", False):
            raise PublishBlockedError(
                "Final originality verification did not pass",
                details=gate_block_details(package),
            )
        unverified = [claim.id for claim in package.claims if not claim.verified]
        if unverified:
            raise PublishBlockedError(
                "Unverified factual claims must be removed or verified before publication",
                details={**gate_block_details(package), "claim_ids": unverified},
            )

    def create_draft(
        self,
        account_id: str,
        package: DeliveryPackage,
        mode: PublishMode = PublishMode.REQUIRE_CONFIRMATION,
        *,
        tenant_id: str = "local",
        created_by: str = "local-cli",
    ) -> PublishDraft:
        validate_identifier(account_id, field="account_id")
        validate_identifier(tenant_id, field="tenant_id")
        self._validate_assets(tenant_id, package)
        # 服务端重验：忽略客户端 compliance/originality/claims.verified
        package = reverify_package(package, settings=self.settings)
        self._assert_package_publishable(package)
        canonical = self._canonical_content_hash(package)
        package = package.model_copy(update={"content_hash": canonical})
        draft = PublishDraft(
            id=str(uuid4()),
            account_id=account_id,
            tenant_id=tenant_id,
            created_by=created_by,
            package=package,
            content_hash=canonical,
            mode=mode,
        )
        self.repository.save_draft(draft)
        return draft

    async def preview(self, draft_id: str, *, tenant_id: str = "local") -> PublishDraft:
        draft = self.repository.load_draft(draft_id, tenant_id)
        async with self.locks.lock(f"publish-preview:{tenant_id}:{draft.account_id}"):
            async with self.concurrency.operation_slot("publish"):
                preview = await self.publisher.prepare(draft)
                draft.preview_path = str(preview)
                draft.preview_url = (
                    f"/v1/publishing/drafts/{draft.id}/preview-image"
                    if preview.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
                    else None
                )
                if draft.mode == PublishMode.DRAFT_ONLY:
                    await self.publisher.save_draft(draft)
                self.repository.save_draft(draft)
                return draft

    def approve(
        self,
        draft_id: str,
        ttl_minutes: int = 30,
        *,
        tenant_id: str = "local",
        approved_by: str = "local-cli",
        approver_auth_level: int = 2,
        ai_disclosure_confirmed: bool = False,
        commercial_disclosure_confirmed: bool = False,
        account_identity_confirmed: bool = False,
        enterprise_approval_id: str | None = None,
    ) -> PublishApproval:
        draft = self.repository.load_draft(draft_id, tenant_id)
        # 审批前再跑一遍，避免对已毒/被篡改草稿发 token
        package = reverify_package(draft.package, settings=self.settings)
        self._assert_package_publishable(package)
        draft.package = package
        self.repository.save_draft(draft)
        if self.settings.enterprise_enforce_publish_quorum:
            if not enterprise_approval_id:
                raise PublishBlockedError("Enterprise approval quorum is required")
            self.enterprise_approvals.require_approved(
                enterprise_approval_id,
                tenant_id=tenant_id,
                resource_type="publish_draft",
                resource_id=draft.id,
                content_hash=draft.content_hash,
            )
        approval = create_approval(
            draft,
            approved_by=approved_by,
            approver_auth_level=approver_auth_level,
            mode=draft.mode,
            ttl_minutes=ttl_minutes,
            ai_disclosure_confirmed=ai_disclosure_confirmed,
            commercial_disclosure_confirmed=commercial_disclosure_confirmed,
            account_identity_confirmed=account_identity_confirmed,
            enterprise_approval_id=enterprise_approval_id,
            settings=self.settings,
        )
        self.repository.save_approval(approval)
        return approval

    async def publish(
        self,
        draft_id: str,
        approval_token: str,
        *,
        tenant_id: str = "local",
    ) -> PublishResult:
        draft = self.repository.load_draft(draft_id, tenant_id)
        if self.distributed_scheduler is not None:
            existing_state = await self.distributed_scheduler.store.get_publish_state_for_draft(
                tenant_id, draft.id
            )
            if existing_state is not None:
                raise PublishBlockedError(
                    "Draft is already bound to a distributed publication state",
                    details={
                        "state_id": str(existing_state["id"]),
                        "state": str(existing_state["state"]),
                    },
                )
        async with self.locks.lock(
            f"publish-account:{tenant_id}:{draft.account_id}",
            ttl_seconds=max(300.0, self.settings.distributed_lock_ttl_seconds),
        ):
            async with self.concurrency.operation_slot("publish"):
                approval = self.repository.load_approval(draft.id, tenant_id)
                if approval is None:
                    raise PublishBlockedError("Explicit approval is required")
                validate_approval(draft, approval, approval_token, self.settings)
                return await self._publish_locked(draft, approval)

    async def _preflight(
        self,
        draft: PublishDraft,
        approval: PublishApproval,
        *,
        enterprise_quorum_prevalidated: bool = False,
    ) -> str:
        if (
            draft.mode == PublishMode.FULLY_AUTOMATED
            and not self.settings.xhs_fully_automated_enabled
        ):
            raise PublishBlockedError("Fully automated publishing is disabled")
        if self._canonical_content_hash(draft.package) != draft.content_hash:
            raise PublishBlockedError("Content hash mismatch")
        if self.settings.enterprise_enforce_publish_quorum:
            if not approval.enterprise_approval_id:
                raise PublishBlockedError("Enterprise approval quorum is missing")
            if not enterprise_quorum_prevalidated:
                self.enterprise_approvals.require_approved(
                    approval.enterprise_approval_id,
                    tenant_id=draft.tenant_id,
                    resource_type="publish_draft",
                    resource_id=draft.id,
                    content_hash=draft.content_hash,
                )
        # 发布前强制 async 服务端重验（含语义 embedding；防草稿篡改报告字段）
        draft.package = await reverify_package_async(draft.package, settings=self.settings)
        ai_required = str(draft.package.ai_labeling.get("explicit_label_required", "")).upper() in {
            "REVIEW",
            "REQUIRED",
            "TRUE",
        }
        if ai_required and not approval.ai_disclosure_confirmed:
            raise PublishBlockedError("AI disclosure decision must be explicitly confirmed")
        commercial_status = str(draft.package.strategy.get("commercial_status", "NON_COMMERCIAL"))
        if commercial_status != "NON_COMMERCIAL" and not approval.commercial_disclosure_confirmed:
            raise PublishBlockedError("Commercial relationship disclosure must be confirmed")
        if (
            isinstance(self.publisher, CreatorStudioPublisher)
            and not approval.account_identity_confirmed
        ):
            raise PublishBlockedError(
                "Target account identity must be confirmed before browser publication"
            )
        self._assert_package_publishable(draft.package)
        self._validate_assets(draft.tenant_id, draft.package)
        return content_hash(
            draft.tenant_id,
            draft.account_id,
            draft.package.selected_title,
            draft.package.body,
            draft.content_hash,
        )

    async def _publish_locked(
        self,
        draft: PublishDraft,
        approval: PublishApproval,
    ) -> PublishResult:
        fingerprint = await self._preflight(draft, approval)
        existing = self.repository.find_by_fingerprint(
            draft.account_id, fingerprint, draft.tenant_id
        )
        if existing:
            raise PublishBlockedError(
                "The same content was already published",
                details={"existing_job_id": existing.job_id, "note_url": existing.note_url},
            )
        recent = sorted(
            [
                item
                for item in self.repository.submitted_results(draft.account_id, draft.tenant_id)
                if item.published_at
            ],
            key=lambda item: item.published_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
        today = datetime.now(UTC).date()
        if (
            sum(1 for item in recent if item.published_at and item.published_at.date() == today)
            >= self.settings.xhs_daily_publish_limit
        ):
            raise PublishBlockedError("Daily publish limit reached")
        if recent and recent[0].published_at:
            elapsed = (datetime.now(UTC) - recent[0].published_at).total_seconds() / 60
            if elapsed < self.settings.xhs_min_publish_interval_minutes:
                raise PublishBlockedError("Minimum publish interval has not elapsed")

        self.repository.consume_approval(draft.id, draft.tenant_id)
        result = PublishResult(
            job_id=str(uuid4()),
            draft_id=draft.id,
            account_id=draft.account_id,
            status="RUNNING",
            audit={
                "fingerprint": fingerprint,
                "mode": draft.mode,
                "tenant_id": draft.tenant_id,
                "approved_by": approval.approved_by,
                "approval_id": approval.id,
            },
        )
        try:
            await self.publisher.prepare(draft)
            payload = await self.publisher.submit(draft)
            result.status = "VERIFIED" if payload.get("verified") else "SUBMITTED_UNVERIFIED"
            result.note_url = payload.get("url")
            result.note_id = payload.get("note_id")
            result.published_at = datetime.now(UTC)
            result.audit["verification_text"] = payload.get("page_text", "")[:500]
            result.audit["submission_detected"] = bool(payload.get("submission_detected"))
        except Exception as exc:
            result.status = "FAILED"
            result.failure_code = getattr(exc, "code", type(exc).__name__)
            result.failure_message = str(exc)
            self.repository.save_result(result, draft.tenant_id)
            raise
        self.repository.save_result(result, draft.tenant_id)
        if result.status == "VERIFIED" and (result.note_id or result.note_url):
            from xhs_skill.ranking.ltr_dataset import package_title_snapshot

            sync_note_id = result.note_id or content_hash(result.note_url or "")[:24]
            package = draft.package
            ltr_features = package_title_snapshot(
                topic=str(
                    (package.keyword_map or {}).get("primary_keyword")
                    or package.selected_title
                    or ""
                ),
                selected_title=package.selected_title,
                mechanism=str((package.strategy or {}).get("content_angle") or ""),
                title_candidates=package.title_candidates,
            )
            tasks = await self.post_publish_sync.enqueue_for_result(
                tenant_id=draft.tenant_id,
                account_id=draft.account_id,
                note_id=sync_note_id,
                note_url=result.note_url,
                content_features=ltr_features,
            )
            result.audit["post_publish_sync_task_ids"] = [task.id for task in tasks]
            result.audit["ltr_content_features"] = ltr_features
            self.repository.save_result(result, draft.tenant_id)
        return result

    async def schedule(
        self,
        draft_id: str,
        approval_token: str,
        scheduled_at: datetime,
        *,
        tenant_id: str = "local",
    ) -> PublishSchedule:
        if not self.settings.xhs_scheduling_enabled:
            raise ConfigurationError("Scheduled publishing is disabled")
        if self.settings.xhs_distributed_scheduling_enabled and self.distributed_scheduler is None:
            raise ConfigurationError("PostgreSQL distributed scheduler is not configured")
        draft = self.repository.load_draft(draft_id, tenant_id)
        async with self.locks.lock(f"publish-schedule:{tenant_id}:{draft.id}"):
            approval = self.repository.load_approval(draft_id, tenant_id)
            if approval is None:
                raise PublishBlockedError("Explicit approval is required")
            validate_approval(draft, approval, approval_token, self.settings)
            if approval.scheduled_for:
                raise PublishBlockedError("This approval is already bound to a schedule")
            if approval.expires_at <= scheduled_at:
                raise PublishBlockedError("Approval must remain valid until the scheduled time")
            if self.distributed_scheduler is not None:
                schedule = await self.distributed_scheduler.schedule(draft, approval, scheduled_at)
            else:
                schedule = await self.scheduler.create(
                    draft_id=draft.id,
                    account_id=draft.account_id,
                    tenant_id=draft.tenant_id,
                    approval_id=approval.id,
                    scheduled_at=scheduled_at,
                    callback=self._publish_scheduled,
                )
            approval.scheduled_for = schedule.id
            try:
                self.repository.save_approval(approval)
            except Exception:
                if self.distributed_scheduler is not None:
                    await self.distributed_scheduler.cancel(tenant_id, schedule.id)
                raise
            return schedule

    async def _publish_scheduled(
        self,
        draft_id: str,
        approval_id: str,
        tenant_id: str,
        schedule_id: str,
    ) -> PublishResult:
        draft = self.repository.load_draft(draft_id, tenant_id)
        approval = self.repository.load_approval(draft_id, tenant_id)
        if approval is None or approval.id != approval_id or approval.scheduled_for != schedule_id:
            raise PublishBlockedError("Scheduled approval is missing or mismatched")
        if approval.used_at is not None or datetime.now(UTC) >= approval.expires_at:
            raise PublishBlockedError("Scheduled approval is expired or consumed")
        async with self.locks.lock(
            f"publish-account:{tenant_id}:{draft.account_id}",
            ttl_seconds=max(300.0, self.settings.distributed_lock_ttl_seconds),
        ):
            async with self.concurrency.operation_slot("publish"):
                return await self._publish_locked(draft, approval)

    async def cancel_schedule(self, schedule_id: str, *, tenant_id: str = "local") -> bool:
        if self.distributed_scheduler is not None:
            state = await self.distributed_scheduler.store.get_publish_state(tenant_id, schedule_id)
            cancelled = await self.distributed_scheduler.cancel(tenant_id, schedule_id)
            if cancelled and state is not None:
                try:
                    approval = self.repository.load_approval(str(state["draft_id"]), tenant_id)
                except (FileNotFoundError, ValueError):
                    approval = None
                if approval and approval.scheduled_for == schedule_id and approval.used_at is None:
                    approval.scheduled_for = None
                    self.repository.save_approval(approval)
            return cancelled
        schedule = self.repository.load_schedule(schedule_id, tenant_id)
        async with self.locks.lock(f"publish-schedule:{tenant_id}:{schedule.draft_id}"):
            cancelled = await self.scheduler.cancel(schedule_id, tenant_id)
            if cancelled:
                approval = self.repository.load_approval(schedule.draft_id, tenant_id)
                if approval and approval.scheduled_for == schedule_id and approval.used_at is None:
                    approval.scheduled_for = None
                    self.repository.save_approval(approval)
            return cancelled

    async def run_scheduler_worker(self) -> None:
        if self.distributed_scheduler is None:
            raise ConfigurationError(
                "Enable XHS_DISTRIBUTED_SCHEDULING_ENABLED and POSTGRES_STATE_ENABLED"
            )
        await self.distributed_scheduler.run_worker()


    async def shutdown(self) -> None:
        if self.distributed_scheduler is not None:
            await self.distributed_scheduler.stop()
        await self.post_publish_sync.close()
