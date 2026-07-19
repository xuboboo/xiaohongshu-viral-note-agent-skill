from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from xhs_skill.api.dependencies import asset_store, operations_service
from xhs_skill.api.security import require_scopes
from xhs_skill.core.auth import Principal
from xhs_skill.operations import (
    Experiment,
    ExperimentOutcome,
    PublishedMetrics,
)

router = APIRouter(prefix="/v1/operations", tags=["operations"])


class CalendarRequest(BaseModel):
    account_id: str
    topics: list[str] = Field(default_factory=list, max_length=100)
    fallback_topics: list[str] = Field(default_factory=list, max_length=100)
    days: int = Field(default=30, ge=7, le=365)
    posts_per_week: int = Field(default=3, ge=1, le=7)


class SeriesRequest(BaseModel):
    account_id: str
    title: str
    topic: str
    audience: str
    episode_count: int = Field(default=6, ge=2, le=30)


class AssignmentRequest(BaseModel):
    subject_id: str


class BanditDecisionRequest(BaseModel):
    policy_id: str
    subject_id: str
    arms: list[str] = Field(min_length=1, max_length=100)
    # 原始向量（高级用法）；若提供 features 则服务端编码覆盖
    context: list[float] = Field(default_factory=list, max_length=128)
    # 结构化特征：账号权重/时段/类目等 → 固定 12 维
    features: dict | None = None
    account_id: str | None = None
    auto_account_weight: bool = True


class BanditUpdateRequest(BaseModel):
    policy_id: str
    arm_id: str
    context: list[float] = Field(default_factory=list, max_length=128)
    features: dict | None = None
    account_id: str | None = None
    auto_account_weight: bool = True
    reward: float


class AssetImportRequest(BaseModel):
    asset_id: str
    account_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    rights_status: str = "USER_OWNED"


@router.post("/metrics/sync")
async def sync_metrics(
    metrics: PublishedMetrics,
    principal: Principal = Depends(require_scopes("account:sync")),
) -> dict:
    payload = metrics.model_copy(update={"tenant_id": principal.tenant_id})
    return (await operations_service().sync_published_metrics_async(payload)).model_dump(mode="json")


@router.get("/accounts/{account_id}/notes/{note_id}/attribution")
async def performance_attribution(
    account_id: str,
    note_id: str,
    principal: Principal = Depends(require_scopes("account:read")),
) -> dict:
    return (
        await operations_service().performance_attribution_async(
            tenant_id=principal.tenant_id,
            account_id=account_id,
            note_id=note_id,
        )
    ).model_dump(mode="json")


@router.get("/accounts/{account_id}/weight-trend")
async def weight_trend(
    account_id: str,
    principal: Principal = Depends(require_scopes("account:read")),
) -> dict:
    return await operations_service().account_weight_trend_async(
        account_id, principal.tenant_id
    )


@router.post("/calendar")
async def create_calendar(
    request: CalendarRequest,
    principal: Principal = Depends(require_scopes("content:plan")),
) -> dict:
    items = await operations_service().create_calendar_async(
        account_id=request.account_id,
        topics=request.topics,
        tenant_id=principal.tenant_id,
        days=request.days,
        posts_per_week=request.posts_per_week,
        fallback_topics=request.fallback_topics or None,
    )
    return {"items": [item.model_dump(mode="json") for item in items]}


@router.post("/series")
async def create_series(
    request: SeriesRequest,
    principal: Principal = Depends(require_scopes("content:plan")),
) -> dict:
    return (await operations_service().create_series_async(
        account_id=request.account_id,
        title=request.title,
        topic=request.topic,
        audience=request.audience,
        episode_count=request.episode_count,
        tenant_id=principal.tenant_id,
    )).model_dump(mode="json")


@router.post("/experiments")
async def create_experiment(
    experiment: Experiment,
    principal: Principal = Depends(require_scopes("experiments:write")),
) -> dict:
    payload = experiment.model_copy(update={"tenant_id": principal.tenant_id})
    return (await operations_service().create_experiment_async(payload)).model_dump(mode="json")


@router.post("/experiments/{experiment_id}/assign")
async def assign_experiment(
    experiment_id: str,
    request: AssignmentRequest,
    principal: Principal = Depends(require_scopes("experiments:write")),
) -> dict:
    return (
        await operations_service().assign_experiment_async(
            principal.tenant_id, experiment_id, request.subject_id
        )
    ).model_dump(mode="json")


@router.post("/experiments/outcomes")
async def record_experiment_outcome(
    outcome: ExperimentOutcome,
    principal: Principal = Depends(require_scopes("experiments:write")),
) -> dict:
    return (
        await operations_service().record_experiment_outcome_async(
            principal.tenant_id, outcome
        )
    ).model_dump(mode="json")




@router.get("/experiments/{experiment_id}/analysis")
async def analyze_experiment(
    experiment_id: str,
    minimum_samples_per_variant: int = 20,
    principal: Principal = Depends(require_scopes("experiments:read")),
) -> dict:
    return (
        await operations_service().analyze_experiment_async(
            principal.tenant_id,
            experiment_id,
            minimum_samples_per_variant=max(
                2, min(minimum_samples_per_variant, 100_000)
            ),
        )
    ).model_dump(mode="json")


@router.post("/bandit/choose")
async def choose_bandit(
    request: BanditDecisionRequest,
    principal: Principal = Depends(require_scopes("experiments:write")),
) -> dict:
    from xhs_skill.operations.bandit_context import describe_bandit_context

    decision = await operations_service().choose_bandit_async(
        tenant_id=principal.tenant_id,
        policy_id=request.policy_id,
        subject_id=request.subject_id,
        arms=request.arms,
        context=request.context or None,
        features=request.features,
        account_id=request.account_id,
        auto_account_weight=request.auto_account_weight,
    )
    payload = decision.model_dump(mode="json")
    payload["context_features"] = describe_bandit_context(decision.context)
    return payload


@router.post("/bandit/update")
async def update_bandit(
    request: BanditUpdateRequest,
    principal: Principal = Depends(require_scopes("experiments:write")),
) -> dict:
    await operations_service().update_bandit_async(
        tenant_id=principal.tenant_id,
        policy_id=request.policy_id,
        arm_id=request.arm_id,
        context=request.context or None,
        features=request.features,
        account_id=request.account_id,
        auto_account_weight=request.auto_account_weight,
        reward=request.reward,
    )
    return {"updated": True}


@router.post("/assets/import")
async def import_asset(
    request: AssetImportRequest,
    principal: Principal = Depends(require_scopes("assets:write")),
) -> dict:
    record = operations_service().assets.import_asset_id(
        request.asset_id,
        asset_store=asset_store(),
        tenant_id=principal.tenant_id,
        account_id=request.account_id,
        tags=request.tags,
        rights_status=request.rights_status,
    )
    stored = await operations_service().save_asset_async(record)
    return stored.model_dump(mode="json", exclude={"storage_path"})


@router.get("/assets")
async def search_assets(
    tags: str | None = None,
    principal: Principal = Depends(require_scopes("assets:read")),
) -> dict:
    requested = [item.strip() for item in (tags or "").split(",") if item.strip()]
    items = await operations_service().search_assets_async(
        principal.tenant_id, requested or None
    )
    return {"items": [item.model_dump(mode="json", exclude={"storage_path"}) for item in items]}


@router.post("/accounts/{account_id}/notes/{note_id}/retrospective")
async def retrospective(
    account_id: str,
    note_id: str,
    principal: Principal = Depends(require_scopes("account:read")),
) -> dict:
    return (
        await operations_service().retrospective_async(
            principal.tenant_id, account_id, note_id
        )
    ).model_dump(mode="json")
