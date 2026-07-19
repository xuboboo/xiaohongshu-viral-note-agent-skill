from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from xhs_skill.api.dependencies import asset_store, research_service
from xhs_skill.api.security import require_scopes
from xhs_skill.core.auth import Principal
from xhs_skill.enterprise.enforcement import enforce_enterprise_policy
from xhs_skill.research import ResearchService
from xhs_skill.schemas.research import HotNotesReport, SearchQuery
from xhs_skill.search import SearchRegistry
from xhs_skill.search.adaptive import ClientWebSearchRequired

router = APIRouter(prefix="/v1/research", tags=["research"])


class HotNotesRequest(SearchQuery):
    sources: list[str] = Field(default_factory=list)
    authorized_import_asset_id: str | None = None
    # Host / client websearch hits: [{url, title, snippet?, ...}]
    web_results: list[dict[str, Any]] = Field(default_factory=list)


async def _run_search(request: HotNotesRequest, principal: Principal) -> HotNotesReport:
    providers = request.sources or None
    if providers:
        for provider in providers:
            enforce_enterprise_policy(
                principal, "research.search", context={"search_provider": provider}
            )
    elif request.web_results:
        enforce_enterprise_policy(
            principal, "research.search", context={"search_provider": "client_web"}
        )
    else:
        enforce_enterprise_policy(principal, "research.search")
    service = research_service()
    if request.authorized_import_asset_id:
        path = asset_store().resolve(
            principal.tenant_id,
            request.authorized_import_asset_id,
            allowed_types={"application/json"},
        )
        registry = SearchRegistry()
        registry.configure_authorized_import(path)
        service = ResearchService(registry)
        providers = providers or ["authorized_import"]
    try:
        return await service.search_hot_notes(
            request,
            providers=providers,
            web_results=request.web_results or None,
        )
    except ClientWebSearchRequired as exc:
        raise HTTPException(status_code=409, detail=exc.to_payload()) from exc
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown search provider: {exc}") from exc


@router.post("/hot-notes", response_model=HotNotesReport)
async def hot_notes(
    request: HotNotesRequest,
    principal: Principal = Depends(require_scopes("research:read")),
) -> HotNotesReport:
    return await _run_search(request, principal)


@router.post("/trends")
async def trends(
    request: HotNotesRequest,
    principal: Principal = Depends(require_scopes("research:read")),
) -> dict:
    report = await _run_search(request, principal)
    return {
        "query": report.query,
        "time_range": report.time_range,
        "score_type": report.score_type,
        "trends": [item.model_dump(mode="json") for item in report.trends],
        "hot_insights": report.hot_insights,
        "topic_suggestions": report.topic_suggestions,
        "content_gaps": report.content_gaps,
        "coverage_warning": report.coverage_warning,
        "disclaimer": "公开索引/授权估算，不是站内官方热榜。",
    }
