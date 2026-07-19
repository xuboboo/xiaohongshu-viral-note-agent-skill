from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from xhs_skill.api.dependencies import provider_registry, search_registry
from xhs_skill.api.security import require_scopes
from xhs_skill.core.auth import Principal
from xhs_skill.enterprise.enforcement import enforce_enterprise_policy

router = APIRouter(prefix="/v1", tags=["providers"])


@router.get("/providers")
async def providers(
    principal: Principal = Depends(require_scopes("providers:read")),
) -> dict:
    enforce_enterprise_policy(principal, "provider.read")
    return {
        "model_providers": provider_registry().list(),
        "search_providers": search_registry().list(),
    }


@router.post("/providers/{provider_id}/probe")
async def probe(
    provider_id: str,
    model: str,
    principal: Principal = Depends(require_scopes("providers:read")),
) -> dict:
    enforce_enterprise_policy(principal, "provider.read")
    try:
        capabilities = await provider_registry().get(provider_id).probe(model)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Provider not configured") from exc
    return {"provider": provider_id, "model": model, "capabilities": capabilities}
