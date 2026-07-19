from __future__ import annotations

import hashlib
import math
from datetime import UTC, datetime

from xhs_skill.accounts import AccountService
from xhs_skill.core.config import Settings, get_settings
from xhs_skill.enterprise.postgres import EnterprisePostgresStore
from xhs_skill.operations.assets import AssetLibrary
from xhs_skill.operations.attribution import attribute_performance
from xhs_skill.operations.bandit_context import (
    BANDIT_CONTEXT_DIM,
    build_bandit_context,
    describe_bandit_context,
)
from xhs_skill.operations.bandit_policy import select_arm
from xhs_skill.operations.experiment_analysis import ExperimentAnalysis, analyze_experiment
from xhs_skill.operations.experiments import (
    ExperimentService,
    LinUCBPolicy,
    _dot,
    _inverse,
    _matvec,
)
from xhs_skill.operations.models import (
    AssetRecord,
    BanditDecision,
    ContentCalendarItem,
    Experiment,
    ExperimentAssignment,
    ExperimentOutcome,
    PerformanceAttribution,
    PublishedMetrics,
    Retrospective,
    SeriesPlan,
)
from xhs_skill.operations.planning import build_content_calendar, build_series_plan
from xhs_skill.operations.repository import OperationsRepository
from xhs_skill.operations.retrospective import build_retrospective, enrich_retrospective_dict


class OperationsService:
    def __init__(
        self,
        repository: OperationsRepository | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repository = repository or OperationsRepository(self.settings)
        self.postgres = (
            EnterprisePostgresStore(self.settings)
            if self.settings.postgres_state_enabled
            else None
        )
        self.accounts = AccountService()
        self.experiments = ExperimentService(self.repository)
        self.bandit = LinUCBPolicy(self.repository)
        self.assets = AssetLibrary(repository=self.repository)

    def sync_published_metrics(self, metrics: PublishedMetrics) -> PublishedMetrics:
        return self.repository.save_metrics(metrics)

    def performance_attribution(
        self,
        *,
        tenant_id: str,
        account_id: str,
        note_id: str,
    ) -> PerformanceAttribution:
        history = self.repository.list_metrics(tenant_id, account_id)
        target_candidates = [item for item in history if item.note_id == note_id]
        if not target_candidates:
            raise KeyError(note_id)
        return attribute_performance(target_candidates[-1], history)

    def account_weight_trend(self, account_id: str, tenant_id: str = "local") -> dict:
        history = self.accounts.weight_history(account_id, tenant_id)
        points = [item for item in history if item.score is not None]
        if len(points) < 2:
            slope = 0.0
        else:
            xs = list(range(len(points)))
            x_mean = sum(xs) / len(xs)
            scores = [float(item.score) for item in points if item.score is not None]
            y_mean = sum(scores) / len(scores)
            numerator = sum(
                (x - x_mean) * (score - y_mean)
                for x, score in zip(xs, scores, strict=True)
            )
            denominator = sum((x - x_mean) ** 2 for x in xs) or 1.0
            slope = numerator / denominator
        return {
            "account_id": account_id,
            "points": [item.model_dump(mode="json") for item in history],
            "slope_per_snapshot": round(slope, 6),
            "direction": "UP" if slope > 0.25 else ("DOWN" if slope < -0.25 else "STABLE"),
        }

    def create_calendar(
        self,
        *,
        account_id: str,
        topics: list[str] | None = None,
        tenant_id: str = "local",
        days: int = 30,
        posts_per_week: int = 3,
        fallback_topics: list[str] | None = None,
    ) -> list[ContentCalendarItem]:
        profile = self.accounts.profile(account_id, tenant_id)
        # 空 topics 时：用 fallback（如复盘 next_note_suggestions）或画像 pillars
        items = build_content_calendar(
            account_id=account_id,
            topics=topics or [],
            profile=profile,
            tenant_id=tenant_id,
            days=days,
            posts_per_week=posts_per_week,
            fallback_topics=fallback_topics,
        )
        self.repository.save_calendar_items(items)
        return items

    def create_series(
        self,
        *,
        account_id: str,
        title: str,
        topic: str,
        audience: str,
        episode_count: int = 6,
        tenant_id: str = "local",
    ) -> SeriesPlan:
        return self.repository.save_series(
            build_series_plan(
                account_id=account_id,
                title=title,
                topic=topic,
                audience=audience,
                episode_count=episode_count,
                tenant_id=tenant_id,
            )
        )

    def create_experiment(self, experiment: Experiment) -> Experiment:
        return self.experiments.create(experiment)

    def assign_experiment(self, tenant_id: str, experiment_id: str, subject_id: str) -> ExperimentAssignment:
        return self.experiments.assign(tenant_id, experiment_id, subject_id)

    def record_experiment_outcome(self, tenant_id: str, outcome: ExperimentOutcome) -> ExperimentOutcome:
        return self.experiments.record(tenant_id, outcome)


    def analyze_experiment(
        self, tenant_id: str, experiment_id: str, minimum_samples_per_variant: int = 20
    ) -> ExperimentAnalysis:
        experiment = self.repository.get_experiment(tenant_id, experiment_id)
        if experiment is None:
            raise KeyError(experiment_id)
        outcomes = self.repository.experiment_outcomes(tenant_id, experiment_id)
        return analyze_experiment(
            experiment, outcomes, minimum_samples_per_variant=minimum_samples_per_variant
        )

    def retrospective(self, tenant_id: str, account_id: str, note_id: str) -> Retrospective:
        history = self.repository.list_metrics(tenant_id, account_id)
        targets = [item for item in history if item.note_id == note_id]
        if not targets:
            raise KeyError(note_id)
        item = build_retrospective(targets[-1], history)
        return self.repository.save_retrospective(item)

    def retrospective_enriched(self, tenant_id: str, account_id: str, note_id: str) -> dict:
        """复盘 + calendar/generate 一跳载荷。"""
        item = self.retrospective(tenant_id, account_id, note_id)
        return enrich_retrospective_dict(item.model_dump(mode="json"))


    async def sync_published_metrics_async(self, metrics: PublishedMetrics) -> PublishedMetrics:
        if self.postgres is not None:
            await self.postgres.save_published_metrics(metrics)
            return metrics
        return self.sync_published_metrics(metrics)

    async def performance_attribution_async(
        self, *, tenant_id: str, account_id: str, note_id: str
    ) -> PerformanceAttribution:
        if self.postgres is None:
            return self.performance_attribution(
                tenant_id=tenant_id, account_id=account_id, note_id=note_id
            )
        history = [
            PublishedMetrics.model_validate(item)
            for item in await self.postgres.list_published_metrics(tenant_id, account_id)
        ]
        targets = [item for item in history if item.note_id == note_id]
        if not targets:
            raise KeyError(note_id)
        return attribute_performance(targets[-1], history)


    async def account_weight_trend_async(
        self, account_id: str, tenant_id: str = "local"
    ) -> dict:
        history = await self.accounts.weight_history_async(account_id, tenant_id)
        points = [item for item in history if item.score is not None]
        if len(points) < 2:
            slope = 0.0
        else:
            xs = list(range(len(points)))
            scores = [float(item.score) for item in points if item.score is not None]
            x_mean = sum(xs) / len(xs)
            y_mean = sum(scores) / len(scores)
            numerator = sum(
                (x - x_mean) * (score - y_mean)
                for x, score in zip(xs, scores, strict=True)
            )
            denominator = sum((x - x_mean) ** 2 for x in xs) or 1.0
            slope = numerator / denominator
        return {
            "account_id": account_id,
            "points": [item.model_dump(mode="json") for item in history],
            "slope_per_snapshot": round(slope, 6),
            "direction": "UP" if slope > 0.25 else ("DOWN" if slope < -0.25 else "STABLE"),
        }

    async def create_calendar_async(
        self,
        *,
        account_id: str,
        topics: list[str] | None = None,
        tenant_id: str = "local",
        days: int = 30,
        posts_per_week: int = 3,
        fallback_topics: list[str] | None = None,
    ) -> list[ContentCalendarItem]:
        if self.postgres is None:
            return self.create_calendar(
                account_id=account_id,
                topics=topics or [],
                tenant_id=tenant_id,
                days=days,
                posts_per_week=posts_per_week,
                fallback_topics=fallback_topics,
            )
        profile = await self.accounts.profile_async(account_id, tenant_id)
        items = build_content_calendar(
            account_id=account_id,
            topics=topics or [],
            profile=profile,
            tenant_id=tenant_id,
            days=days,
            posts_per_week=posts_per_week,
            fallback_topics=fallback_topics,
        )
        await self.postgres.save_calendar_items(items)
        return items

    async def create_series_async(
        self,
        *,
        account_id: str,
        title: str,
        topic: str,
        audience: str,
        episode_count: int = 6,
        tenant_id: str = "local",
    ) -> SeriesPlan:
        if self.postgres is None:
            return self.create_series(
                account_id=account_id,
                title=title,
                topic=topic,
                audience=audience,
                episode_count=episode_count,
                tenant_id=tenant_id,
            )
        plan = build_series_plan(
            account_id=account_id,
            title=title,
            topic=topic,
            audience=audience,
            episode_count=episode_count,
            tenant_id=tenant_id,
        )
        await self.postgres.save_series_plan(plan)
        return plan

    async def create_experiment_async(self, experiment: Experiment) -> Experiment:
        if len(experiment.variants) < 2:
            raise ValueError("A/B/n experiment requires at least two variants")
        total = sum(item.allocation for item in experiment.variants)
        if total <= 0:
            raise ValueError("Experiment allocation must be positive")
        if not math.isclose(total, 1.0, rel_tol=1e-6):
            experiment = experiment.model_copy(deep=True)
            for item in experiment.variants:
                item.allocation /= total
        experiment.status = "RUNNING"
        experiment.started_at = datetime.now(UTC)
        if self.postgres is not None:
            await self.postgres.save_content_experiment(experiment)
            return experiment
        return self.create_experiment(experiment)

    async def assign_experiment_async(
        self, tenant_id: str, experiment_id: str, subject_id: str
    ) -> ExperimentAssignment:
        if self.postgres is None:
            return self.assign_experiment(tenant_id, experiment_id, subject_id)
        payload = await self.postgres.get_content_experiment(tenant_id, experiment_id)
        if payload is None:
            raise KeyError(experiment_id)
        experiment = Experiment.model_validate(payload)
        if experiment.status != "RUNNING":
            raise ValueError("Experiment is not running")
        point = int.from_bytes(
            hashlib.sha256(f"{tenant_id}:{experiment_id}:{subject_id}".encode()).digest()[:8],
            "big",
        ) / 2**64
        cumulative = 0.0
        selected = experiment.variants[-1]
        for variant in experiment.variants:
            cumulative += variant.allocation
            if point < cumulative:
                selected = variant
                break
        assignment = ExperimentAssignment(
            experiment_id=experiment_id, subject_id=subject_id, variant_id=selected.id
        )
        stored = await self.postgres.save_experiment_assignment(tenant_id, assignment)
        return ExperimentAssignment.model_validate(stored)

    async def record_experiment_outcome_async(
        self, tenant_id: str, outcome: ExperimentOutcome
    ) -> ExperimentOutcome:
        if self.postgres is not None:
            stored = await self.postgres.save_experiment_outcome(tenant_id, outcome)
            return ExperimentOutcome.model_validate(stored)
        return self.record_experiment_outcome(tenant_id, outcome)

    async def analyze_experiment_async(
        self, tenant_id: str, experiment_id: str, minimum_samples_per_variant: int = 20
    ) -> ExperimentAnalysis:
        if self.postgres is None:
            return self.analyze_experiment(
                tenant_id, experiment_id, minimum_samples_per_variant
            )
        payload = await self.postgres.get_content_experiment(tenant_id, experiment_id)
        if payload is None:
            raise KeyError(experiment_id)
        experiment = Experiment.model_validate(payload)
        outcomes = [
            ExperimentOutcome.model_validate(item)
            for item in await self.postgres.list_experiment_outcomes(tenant_id, experiment_id)
        ]
        return analyze_experiment(
            experiment, outcomes, minimum_samples_per_variant=minimum_samples_per_variant
        )

    async def choose_bandit_async(
        self,
        *,
        tenant_id: str,
        policy_id: str,
        subject_id: str,
        arms: list[str],
        context: list[float] | None = None,
        features: dict | None = None,
        account_id: str | None = None,
        auto_account_weight: bool = True,
    ) -> BanditDecision:
        resolved = await self._resolve_bandit_context(
            tenant_id=tenant_id,
            context=context,
            features=features,
            account_id=account_id,
            auto_account_weight=auto_account_weight,
        )
        if self.postgres is None:
            decision = self.bandit.choose(
                tenant_id=tenant_id,
                policy_id=policy_id,
                subject_id=subject_id,
                arms=arms,
                context=resolved,
            )
        else:
            if not arms or not resolved:
                raise ValueError("arms and context are required")
            scored: list[tuple[str, float, float]] = []
            for arm in arms:
                a, b, _ = await self.postgres.load_bandit_arm(
                    tenant_id, policy_id, arm, len(resolved)
                )
                inverse = _inverse(a)
                theta = _matvec(inverse, b)
                expected = _dot(theta, resolved)
                uncertainty = math.sqrt(
                    max(0.0, _dot(resolved, _matvec(inverse, resolved)))
                )
                exploration = self.settings.bandit_exploration_alpha * uncertainty
                scored.append((arm, expected + exploration, exploration))
            arm, score, exploration = select_arm(
                scored,
                strategy=self.settings.bandit_selection_strategy,
                temperature=self.settings.bandit_boltzmann_temperature,
                seed_material=f"{tenant_id}:{policy_id}:{subject_id}",
            )
            decision = BanditDecision(
                policy_id=policy_id,
                subject_id=subject_id,
                arm_id=arm,
                score=round(score, 8),
                exploration_bonus=round(exploration, 8),
                context=resolved,
            )
        return decision.model_copy(
            update={
                "context_features": describe_bandit_context(resolved),
                "context_schema_version": (
                    "bandit_context_v1" if len(resolved) == BANDIT_CONTEXT_DIM else "custom"
                ),
            }
        )

    async def update_bandit_async(
        self,
        *,
        tenant_id: str,
        policy_id: str,
        arm_id: str,
        context: list[float] | None = None,
        features: dict | None = None,
        account_id: str | None = None,
        auto_account_weight: bool = True,
        reward: float,
    ) -> None:
        resolved = await self._resolve_bandit_context(
            tenant_id=tenant_id,
            context=context,
            features=features,
            account_id=account_id,
            auto_account_weight=auto_account_weight,
        )
        if self.postgres is not None:
            await self.postgres.update_bandit_arm(
                tenant_id, policy_id, arm_id, resolved, reward
            )
            return
        self.bandit.update(
            tenant_id=tenant_id,
            policy_id=policy_id,
            arm_id=arm_id,
            context=resolved,
            reward=reward,
        )

    async def _resolve_bandit_context(
        self,
        *,
        tenant_id: str,
        context: list[float] | None,
        features: dict | None,
        account_id: str | None,
        auto_account_weight: bool,
    ) -> list[float]:
        """优先结构化 features → 固定 12 维；否则使用调用方向量；都缺则默认时段特征。"""
        if features is not None:
            feat = dict(features)
            if auto_account_weight and account_id and feat.get("account_weight") is None:
                try:
                    report = await self.accounts.query_weight_async(
                        account_id, tenant_id=tenant_id
                    )
                    score = report.overall_score
                    if score is not None:
                        feat["account_weight"] = float(score)
                except Exception:
                    pass
            return build_bandit_context(feat)
        if context:
            return list(map(float, context))
        # 无任何输入：仍给出可训练的默认上下文（bias + 当前时段）
        feat: dict = {}
        if auto_account_weight and account_id:
            try:
                report = await self.accounts.query_weight_async(
                    account_id, tenant_id=tenant_id
                )
                if report.overall_score is not None:
                    feat["account_weight"] = float(report.overall_score)
            except Exception:
                pass
        return build_bandit_context(feat)

    async def save_asset_async(self, record: AssetRecord) -> AssetRecord:
        if self.postgres is not None:
            stored = await self.postgres.save_asset_record(record)
            return AssetRecord.model_validate(stored)
        return self.repository.save_asset(record)

    async def search_assets_async(
        self, tenant_id: str, tags: list[str] | None = None
    ) -> list[AssetRecord]:
        if self.postgres is not None:
            return [
                AssetRecord.model_validate(item)
                for item in await self.postgres.search_asset_records(tenant_id, tags)
            ]
        return self.assets.search(tenant_id, tags)

    async def retrospective_async(
        self, tenant_id: str, account_id: str, note_id: str
    ) -> Retrospective:
        if self.postgres is None:
            return self.retrospective(tenant_id, account_id, note_id)
        history = [
            PublishedMetrics.model_validate(item)
            for item in await self.postgres.list_published_metrics(tenant_id, account_id)
        ]
        targets = [item for item in history if item.note_id == note_id]
        if not targets:
            raise KeyError(note_id)
        item = build_retrospective(targets[-1], history)
        stored = await self.postgres.save_retrospective_record(item)
        return Retrospective.model_validate(stored)

    async def retrospective_enriched_async(
        self, tenant_id: str, account_id: str, note_id: str
    ) -> dict:
        item = await self.retrospective_async(tenant_id, account_id, note_id)
        return enrich_retrospective_dict(item.model_dump(mode="json"))

    async def close(self) -> None:
        if self.postgres is not None:
            await self.postgres.close()
