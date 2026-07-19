from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from xhs_skill.api.dependencies import account_service, browser_analytics_sync, research_service
from xhs_skill.api.security import require_scopes
from xhs_skill.core.auth import Principal
from xhs_skill.enterprise.enforcement import enforce_enterprise_policy
from xhs_skill.research.topic_suggest import suggest_topics_from_report
from xhs_skill.schemas.account import AccountAnalytics, AccountWeightReport
from xhs_skill.schemas.research import SearchQuery
from xhs_skill.search.adaptive import ClientWebSearchRequired

router = APIRouter(prefix="/v1/accounts", tags=["accounts"])


class HealthTopicsRequest(BaseModel):
    """健康度选题：可叠加热门研究后重排。"""

    analytics: AccountAnalytics | None = None
    base_topic: str | None = Field(default=None, max_length=200)
    query: str | None = Field(default=None, max_length=200)
    providers: list[str] | None = None
    web_results: list[dict] = Field(default_factory=list)
    limit: int = Field(default=8, ge=3, le=12)


@router.post("/{account_id}/analytics/sync", response_model=AccountAnalytics)
async def sync_account(
    account_id: str,
    analytics: AccountAnalytics,
    principal: Principal = Depends(require_scopes("account:sync")),
) -> AccountAnalytics:
    enforce_enterprise_policy(principal, "account.sync")
    item = analytics.model_copy(update={"account_id": account_id})
    return await account_service().sync_async(item, principal.tenant_id)


@router.post("/{account_id}/weight/query", response_model=AccountWeightReport)
async def query_weight(
    account_id: str,
    analytics: AccountAnalytics | None = None,
    principal: Principal = Depends(require_scopes("account:read")),
) -> AccountWeightReport:
    enforce_enterprise_policy(principal, "account.read")
    item = analytics.model_copy(update={"account_id": account_id}) if analytics else None
    return await account_service().query_weight_async(account_id, item, principal.tenant_id)


@router.get("/{account_id}/weight", response_model=AccountWeightReport)
async def get_weight(
    account_id: str,
    principal: Principal = Depends(require_scopes("account:read")),
) -> AccountWeightReport:
    enforce_enterprise_policy(principal, "account.read")
    return await account_service().query_weight_async(account_id, tenant_id=principal.tenant_id)


@router.post("/{account_id}/content-health")
async def content_health(
    account_id: str,
    analytics: AccountAnalytics | None = None,
    principal: Principal = Depends(require_scopes("account:read")),
) -> dict:
    enforce_enterprise_policy(principal, "account.read")
    item = analytics.model_copy(update={"account_id": account_id}) if analytics else None
    return await account_service().content_health_async(account_id, item, principal.tenant_id)


class DiagnoseRequest(BaseModel):
    analytics: AccountAnalytics | None = None
    base_topic: str | None = Field(default=None, max_length=200)


@router.post("/{account_id}/diagnose")
async def diagnose_account(
    account_id: str,
    payload: DiagnoseRequest | None = None,
    principal: Principal = Depends(require_scopes("account:read")),
) -> dict:
    enforce_enterprise_policy(principal, "account.read")
    body = payload or DiagnoseRequest()
    analytics = (
        body.analytics.model_copy(update={"account_id": account_id})
        if body.analytics is not None
        else None
    )
    return account_service().account_diagnosis(
        account_id, analytics, principal.tenant_id, base_topic=body.base_topic
    )


@router.post("/{account_id}/topics/by-health")
async def topics_by_health(
    account_id: str,
    payload: HealthTopicsRequest,
    principal: Principal = Depends(require_scopes("account:read")),
) -> dict:
    """按内容健康度生成/重排选题（可叠加热门研究）。"""
    enforce_enterprise_policy(principal, "account.read")
    item = (
        payload.analytics.model_copy(update={"account_id": account_id})
        if payload.analytics
        else None
    )
    research_suggestions = None
    query = (payload.query or payload.base_topic or "").strip()
    if query:
        try:
            report = await research_service().search_hot_notes(
                SearchQuery(query=query, time_range="7d", limit=30),
                providers=payload.providers,
                web_results=payload.web_results or None,
            )
            research_suggestions = list(
                report.topic_suggestions or suggest_topics_from_report(report)
            )
        except ClientWebSearchRequired as exc:
            raise HTTPException(status_code=409, detail=exc.to_payload()) from exc
    result = account_service().suggest_topics_from_health(
        account_id,
        analytics=item,
        base_topic=payload.base_topic or (query or None),
        research_suggestions=research_suggestions,
        tenant_id=principal.tenant_id,
        limit=payload.limit,
    )
    if research_suggestions is not None and query:
        result["query"] = query
    return result


@router.post("/{account_id}/analytics/browser-sync", response_model=AccountAnalytics)
async def sync_account_from_browser(
    account_id: str,
    principal: Principal = Depends(require_scopes("account:sync", "auth:manage")),
) -> AccountAnalytics:
    enforce_enterprise_policy(principal, "account.sync")
    analytics = await browser_analytics_sync().sync(account_id, principal.tenant_id)
    return await account_service().sync_async(analytics, principal.tenant_id)
