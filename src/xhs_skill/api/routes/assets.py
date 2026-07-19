from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from xhs_skill.api.dependencies import asset_store
from xhs_skill.api.security import require_scopes
from xhs_skill.core.auth import Principal
from xhs_skill.core.config import get_settings

router = APIRouter(prefix="/v1/assets", tags=["assets"])


@router.post("")
async def upload_asset(
    file: UploadFile = File(...),
    principal: Principal = Depends(require_scopes("assets:write")),
) -> dict:
    settings = get_settings()
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1_048_576)
        if not chunk:
            break
        total += len(chunk)
        if total > settings.asset_upload_max_bytes:
            raise HTTPException(status_code=413, detail="Asset exceeds configured size limit")
        chunks.append(chunk)
    content = b"".join(chunks)
    item = asset_store().save_bytes(
        tenant_id=principal.tenant_id,
        filename=file.filename or "upload.bin",
        content_type=file.content_type,
        content=content,
    )
    return {
        "asset_id": item.asset_id,
        "filename": item.filename,
        "content_type": item.content_type,
        "size_bytes": item.size_bytes,
    }


@router.delete("/{asset_id}")
async def delete_asset(
    asset_id: str,
    principal: Principal = Depends(require_scopes("assets:write")),
) -> dict:
    return {"deleted": asset_store().delete(principal.tenant_id, asset_id)}
