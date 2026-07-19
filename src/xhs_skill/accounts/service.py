from __future__ import annotations

from xhs_skill.accounts.content_health import estimate_content_health
from xhs_skill.accounts.profile import build_account_profile
from xhs_skill.accounts.repository import AccountRepository
from xhs_skill.accounts.weight_estimator import estimate_account_weight
from xhs_skill.core.config import Settings, get_settings
from xhs_skill.enterprise.postgres import EnterprisePostgresStore
from xhs_skill.schemas.account import (
    AccountAnalytics,
    AccountProfile,
    AccountWeightReport,
    AccountWeightSnapshot,
)


class AccountService:
    def __init__(
        self,
        repository: AccountRepository | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repository = repository or AccountRepository()
        self.postgres = (
            EnterprisePostgresStore(self.settings)
            if self.settings.postgres_state_enabled
            else None
        )

    def sync(self, analytics: AccountAnalytics, tenant_id: str = "local") -> AccountAnalytics:
        self.repository.save_analytics(analytics, tenant_id)
        self.repository.save_profile(build_account_profile(analytics, tenant_id=tenant_id))
        return analytics

    def query_weight(
        self,
        account_id: str,
        analytics: AccountAnalytics | None = None,
        tenant_id: str = "local",
    ) -> AccountWeightReport:
        data = analytics or self.repository.load_analytics(account_id, tenant_id)
        if data is None:
            data = AccountAnalytics(account_id=account_id)
        report = estimate_account_weight(data)
        self.repository.save_report(account_id, report, tenant_id)
        return report

    def content_health(
        self,
        account_id: str,
        analytics: AccountAnalytics | None = None,
        tenant_id: str = "local",
    ) -> dict:
        from xhs_skill.accounts.anomaly import coldstart_prior, detect_analytics_anomalies

        data = analytics or self.repository.load_analytics(account_id, tenant_id)
        if data is None:
            data = AccountAnalytics(account_id=account_id)
        health = estimate_content_health(data)
        health["account_id"] = account_id
        health["tenant_id"] = tenant_id
        health["analytics_anomalies"] = detect_analytics_anomalies(data)
        health["coldstart"] = coldstart_prior(data)
        return health

    def account_diagnosis(
        self,
        account_id: str,
        analytics: AccountAnalytics | None = None,
        tenant_id: str = "local",
        *,
        base_topic: str | None = None,
    ) -> dict:
        """权重 + 内容健康度联合诊断，并输出 generate_payload。"""
        from xhs_skill.accounts.anomaly import detect_weight_anomalies
        from xhs_skill.accounts.diagnosis import assemble_diagnosis

        weight = self.query_weight(account_id, analytics, tenant_id)
        health = self.content_health(account_id, analytics, tenant_id)
        history = self.weight_history(account_id, tenant_id)
        weight_anomalies = detect_weight_anomalies(history)
        profile = self.profile(account_id, tenant_id)
        topic = base_topic
        if not topic and profile and profile.content_pillars:
            topic = str(profile.content_pillars[0])
        return assemble_diagnosis(
            account_id=account_id,
            weight=weight.model_dump(mode="json"),
            health=health,
            base_topic=topic,
            weight_anomalies=weight_anomalies,
        )

    def suggest_topics_from_health(
        self,
        account_id: str,
        *,
        analytics: AccountAnalytics | None = None,
        base_topic: str | None = None,
        research_suggestions: list[dict] | None = None,
        tenant_id: str = "local",
        limit: int = 8,
    ) -> dict:
        """账号健康度驱动选题（可叠加热门选题重排）。"""
        from xhs_skill.accounts.health_topics import merge_health_and_research_suggestions

        data = analytics or self.repository.load_analytics(account_id, tenant_id)
        if data is None:
            data = AccountAnalytics(account_id=account_id)
        health = estimate_content_health(data)
        health["account_id"] = account_id
        profile = self.profile(account_id, tenant_id)
        pillars = list(profile.content_pillars) if profile and profile.content_pillars else []
        merged = merge_health_and_research_suggestions(
            health=health,
            research_suggestions=research_suggestions,
            base_topic=base_topic,
            pillars=pillars,
            limit=limit,
        )
        merged["account_id"] = account_id
        merged["content_health"] = health
        if profile:
            merged["profile_pillars"] = pillars
        return merged

    def profile(self, account_id: str, tenant_id: str = "local") -> AccountProfile | None:
        return self.repository.load_profile(account_id, tenant_id)

    def weight_history(self, account_id: str, tenant_id: str = "local") -> list[AccountWeightSnapshot]:
        return self.repository.weight_history(account_id, tenant_id)


    async def sync_async(
        self, analytics: AccountAnalytics, tenant_id: str = "local"
    ) -> AccountAnalytics:
        item = self.sync(analytics, tenant_id)
        if self.postgres is not None:
            profile = self.repository.load_profile(analytics.account_id, tenant_id)
            if profile is not None:
                await self.postgres.save_account_profile(profile)
        return item

    async def query_weight_async(
        self,
        account_id: str,
        analytics: AccountAnalytics | None = None,
        tenant_id: str = "local",
    ) -> AccountWeightReport:
        report = self.query_weight(account_id, analytics, tenant_id)
        if self.postgres is not None:
            history = self.repository.weight_history(account_id, tenant_id)
            if history:
                await self.postgres.save_account_weight_snapshot(tenant_id, history[-1])
        return report

    async def content_health_async(
        self,
        account_id: str,
        analytics: AccountAnalytics | None = None,
        tenant_id: str = "local",
    ) -> dict:
        return self.content_health(account_id, analytics, tenant_id)

    async def account_diagnosis_async(
        self,
        account_id: str,
        analytics: AccountAnalytics | None = None,
        tenant_id: str = "local",
        *,
        base_topic: str | None = None,
    ) -> dict:
        return self.account_diagnosis(
            account_id, analytics, tenant_id, base_topic=base_topic
        )

    async def profile_async(
        self, account_id: str, tenant_id: str = "local"
    ) -> AccountProfile | None:
        if self.postgres is not None:
            payload = await self.postgres.get_account_profile(tenant_id, account_id)
            if payload is not None:
                return AccountProfile.model_validate(payload)
        return self.profile(account_id, tenant_id)

    async def weight_history_async(
        self, account_id: str, tenant_id: str = "local"
    ) -> list[AccountWeightSnapshot]:
        if self.postgres is not None:
            return [
                AccountWeightSnapshot.model_validate(item)
                for item in await self.postgres.list_account_weight_snapshots(
                    tenant_id, account_id
                )
            ]
        return self.weight_history(account_id, tenant_id)

    async def close(self) -> None:
        if self.postgres is not None:
            await self.postgres.close()
