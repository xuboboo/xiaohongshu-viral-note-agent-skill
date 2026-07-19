from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from xhs_skill.api.dependencies import login_flow
from xhs_skill.api.security import require_scopes
from xhs_skill.core.auth import Principal
from xhs_skill.core.config import get_settings
from xhs_skill.schemas.publishing import AuthSession

router = APIRouter(prefix="/v1/accounts", tags=["authentication"])


@router.post("/{account_id}/auth/start", response_model=AuthSession)
async def start_login(
    account_id: str,
    principal: Principal = Depends(require_scopes("auth:manage", min_auth_level=2)),
) -> AuthSession:
    return await login_flow().start(account_id, principal.tenant_id)


@router.get("/{account_id}/auth/status", response_model=AuthSession)
async def login_status(
    account_id: str,
    principal: Principal = Depends(require_scopes("auth:manage")),
) -> AuthSession:
    return await login_flow().status(account_id, principal.tenant_id)


@router.post("/{account_id}/auth/logout", response_model=AuthSession)
async def logout(
    account_id: str,
    delete_session: bool = True,
    principal: Principal = Depends(require_scopes("auth:manage", min_auth_level=2)),
) -> AuthSession:
    return await login_flow().logout(
        account_id,
        tenant_id=principal.tenant_id,
        delete_session=delete_session,
    )


@router.get("/{account_id}/auth/qr")
async def login_qr(
    account_id: str,
    principal: Principal = Depends(require_scopes("auth:manage")),
):
    status = await login_flow().status(account_id, principal.tenant_id)
    if not status.qr_image_path:
        raise HTTPException(status_code=404, detail="QR image is not available")
    path = Path(status.qr_image_path).resolve()
    root = get_settings().xhs_screenshot_dir.resolve()
    if path.parent != root or path.is_symlink() or not path.is_file():
        raise HTTPException(status_code=404, detail="QR image file is missing")
    return FileResponse(
        path,
        media_type="image/png",
        filename=path.name,
        headers={"Cache-Control": "no-store"},
    )
