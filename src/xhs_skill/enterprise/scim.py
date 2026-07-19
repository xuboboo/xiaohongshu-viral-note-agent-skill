from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from xhs_skill.api.security import require_scopes
from xhs_skill.core.auth import Principal
from xhs_skill.enterprise.models import EnterpriseGroup, EnterpriseUser
from xhs_skill.enterprise.policy import get_policy_engine
from xhs_skill.enterprise.repository import EnterpriseRepository

SCIM_USER = "urn:ietf:params:scim:schemas:core:2.0:User"
SCIM_GROUP = "urn:ietf:params:scim:schemas:core:2.0:Group"
SCIM_LIST = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
SCIM_PATCH = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
SCIM_ERROR = "urn:ietf:params:scim:api:messages:2.0:Error"

router = APIRouter(prefix="/scim/v2", tags=["enterprise-scim"])
_repo = EnterpriseRepository()


def _authorize(principal: Principal, operation: str) -> None:
    decision = get_policy_engine().evaluate(principal, operation)
    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.reason)


def _error(detail: str, status_code: int = 400, scim_type: str | None = None) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={
            "schemas": [SCIM_ERROR],
            "status": str(status_code),
            "detail": detail,
            **({"scimType": scim_type} if scim_type else {}),
        },
    )


def _user_resource(user: EnterpriseUser) -> dict[str, Any]:
    return {
        "schemas": [SCIM_USER],
        "id": user.id,
        "externalId": user.external_id,
        "userName": user.user_name,
        "displayName": user.display_name,
        "active": user.active,
        "emails": [{"value": item, "primary": index == 0} for index, item in enumerate(user.emails)],
        "roles": [{"value": item} for item in user.roles],
        "groups": [{"value": item} for item in user.groups],
        "meta": {
            "resourceType": "User",
            "created": user.created_at.isoformat(),
            "lastModified": user.updated_at.isoformat(),
            "location": f"/scim/v2/Users/{user.id}",
            "version": f'W/"{int(user.updated_at.timestamp())}"',
        },
    }


def _group_resource(group: EnterpriseGroup) -> dict[str, Any]:
    return {
        "schemas": [SCIM_GROUP],
        "id": group.id,
        "externalId": group.external_id,
        "displayName": group.display_name,
        "members": [{"value": item} for item in group.members],
        "roles": [{"value": item} for item in group.roles],
        "meta": {
            "resourceType": "Group",
            "created": group.created_at.isoformat(),
            "lastModified": group.updated_at.isoformat(),
            "location": f"/scim/v2/Groups/{group.id}",
            "version": f'W/"{int(group.updated_at.timestamp())}"',
        },
    }


def _values(items: Any, key: str = "value") -> list[str]:
    if not isinstance(items, list):
        return []
    output: list[str] = []
    for item in items:
        if isinstance(item, dict) and item.get(key):
            output.append(str(item[key]))
        elif isinstance(item, str):
            output.append(item)
    return output


@router.get("/ServiceProviderConfig")
async def service_provider_config(
    principal: Principal = Depends(require_scopes("scim:read")),
) -> dict[str, Any]:
    _authorize(principal, "scim.read")
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
        "patch": {"supported": True},
        "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": 200},
        "changePassword": {"supported": False},
        "sort": {"supported": False},
        "etag": {"supported": True},
        "authenticationSchemes": [
            {
                "type": "oauthbearertoken",
                "name": "OAuth Bearer Token",
                "description": "OIDC/OAuth bearer token scoped for SCIM",
                "specUri": "https://www.rfc-editor.org/info/rfc6750",
                "primary": True,
            }
        ],
    }


@router.get("/ResourceTypes")
async def resource_types(
    principal: Principal = Depends(require_scopes("scim:read")),
) -> dict[str, Any]:
    _authorize(principal, "scim.read")
    resources = [
        {"id": "User", "name": "User", "endpoint": "/Users", "schema": SCIM_USER},
        {"id": "Group", "name": "Group", "endpoint": "/Groups", "schema": SCIM_GROUP},
    ]
    return {"schemas": [SCIM_LIST], "totalResults": len(resources), "Resources": resources}


@router.get("/Schemas")
async def schemas(
    principal: Principal = Depends(require_scopes("scim:read")),
) -> dict[str, Any]:
    _authorize(principal, "scim.read")
    resources = [
        {"id": SCIM_USER, "name": "User", "description": "Enterprise user schema", "attributes": []},
        {"id": SCIM_GROUP, "name": "Group", "description": "Enterprise group schema", "attributes": []},
    ]
    return {"schemas": [SCIM_LIST], "totalResults": len(resources), "Resources": resources}


@router.get("/Users")
async def list_users(
    filter_: str | None = Query(default=None, alias="filter"),
    start_index: int = Query(default=1, alias="startIndex", ge=1),
    count: int = Query(default=100, ge=1, le=200),
    principal: Principal = Depends(require_scopes("scim:read")),
) -> dict[str, Any]:
    _authorize(principal, "scim.read")
    users = _repo.list_users(principal.tenant_id)
    if filter_:
        match = re.fullmatch(r'\s*userName\s+eq\s+"([^"]+)"\s*', filter_, flags=re.I)
        if not match:
            raise _error("Only userName eq filters are supported", scim_type="invalidFilter")
        expected = match.group(1).casefold()
        users = [item for item in users if item.user_name.casefold() == expected]
    total = len(users)
    selected = users[start_index - 1 : start_index - 1 + count]
    return {
        "schemas": [SCIM_LIST],
        "totalResults": total,
        "startIndex": start_index,
        "itemsPerPage": len(selected),
        "Resources": [_user_resource(item) for item in selected],
    }


@router.post("/Users", status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: dict[str, Any],
    response: Response,
    principal: Principal = Depends(require_scopes("scim:write")),
) -> dict[str, Any]:
    _authorize(principal, "scim.write")
    user_name = str(payload.get("userName", "")).strip()
    if not user_name:
        raise _error("userName is required", scim_type="invalidValue")
    if _repo.find_user_by_name(principal.tenant_id, user_name):
        raise _error("userName already exists", 409, "uniqueness")
    tenant = _repo.get_tenant(principal.tenant_id)
    if len(_repo.list_users(principal.tenant_id)) >= tenant.policy.max_users:
        raise _error("Tenant user limit reached", 409, "tooMany")
    user = EnterpriseUser(
        tenant_id=principal.tenant_id,
        user_name=user_name,
        display_name=str(payload.get("displayName", "")),
        active=bool(payload.get("active", True)),
        external_id=str(payload.get("externalId")) if payload.get("externalId") else None,
        emails=_values(payload.get("emails")),
        roles=_values(payload.get("roles")),
    )
    _repo.save_user(user)
    response.headers["Location"] = f"/scim/v2/Users/{user.id}"
    response.headers["ETag"] = f'W/"{int(user.updated_at.timestamp())}"'
    return _user_resource(user)


@router.get("/Users/{user_id}")
async def get_user(
    user_id: str,
    principal: Principal = Depends(require_scopes("scim:read")),
) -> dict[str, Any]:
    _authorize(principal, "scim.read")
    user = _repo.get_user(principal.tenant_id, user_id)
    if not user:
        raise _error("User not found", 404)
    return _user_resource(user)


@router.put("/Users/{user_id}")
async def replace_user(
    user_id: str,
    payload: dict[str, Any],
    principal: Principal = Depends(require_scopes("scim:write")),
) -> dict[str, Any]:
    _authorize(principal, "scim.write")
    existing = _repo.get_user(principal.tenant_id, user_id)
    if not existing:
        raise _error("User not found", 404)
    existing.user_name = str(payload.get("userName", existing.user_name))
    existing.display_name = str(payload.get("displayName", ""))
    existing.active = bool(payload.get("active", True))
    existing.external_id = str(payload.get("externalId")) if payload.get("externalId") else None
    existing.emails = _values(payload.get("emails"))
    existing.roles = _values(payload.get("roles"))
    return _user_resource(_repo.save_user(existing))


@router.patch("/Users/{user_id}")
async def patch_user(
    user_id: str,
    payload: dict[str, Any],
    principal: Principal = Depends(require_scopes("scim:write")),
) -> dict[str, Any]:
    _authorize(principal, "scim.write")
    user = _repo.get_user(principal.tenant_id, user_id)
    if not user:
        raise _error("User not found", 404)
    for operation in payload.get("Operations", []):
        op = str(operation.get("op", "replace")).lower()
        path = str(operation.get("path", "")).lower()
        value = operation.get("value")
        if op not in {"add", "replace", "remove"}:
            raise _error("Unsupported patch operation", scim_type="invalidSyntax")
        if path == "active":
            user.active = False if op == "remove" else bool(value)
        elif path == "displayname":
            user.display_name = "" if op == "remove" else str(value)
        elif path == "roles":
            user.roles = [] if op == "remove" else _values(value)
        elif not path and isinstance(value, dict):
            if "active" in value:
                user.active = bool(value["active"])
            if "displayName" in value:
                user.display_name = str(value["displayName"])
        else:
            raise _error(f"Unsupported patch path: {path}", scim_type="invalidPath")
    return _user_resource(_repo.save_user(user))


@router.delete("/Users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    principal: Principal = Depends(require_scopes("scim:write")),
) -> Response:
    _authorize(principal, "scim.write")
    if not _repo.delete_user(principal.tenant_id, user_id):
        raise _error("User not found", 404)
    return Response(status_code=204)


@router.get("/Groups")
async def list_groups(
    start_index: int = Query(default=1, alias="startIndex", ge=1),
    count: int = Query(default=100, ge=1, le=200),
    principal: Principal = Depends(require_scopes("scim:read")),
) -> dict[str, Any]:
    _authorize(principal, "scim.read")
    groups = _repo.list_groups(principal.tenant_id)
    selected = groups[start_index - 1 : start_index - 1 + count]
    return {
        "schemas": [SCIM_LIST],
        "totalResults": len(groups),
        "startIndex": start_index,
        "itemsPerPage": len(selected),
        "Resources": [_group_resource(item) for item in selected],
    }


@router.post("/Groups", status_code=status.HTTP_201_CREATED)
async def create_group(
    payload: dict[str, Any],
    response: Response,
    principal: Principal = Depends(require_scopes("scim:write")),
) -> dict[str, Any]:
    _authorize(principal, "scim.write")
    display_name = str(payload.get("displayName", "")).strip()
    if not display_name:
        raise _error("displayName is required", scim_type="invalidValue")
    group = EnterpriseGroup(
        tenant_id=principal.tenant_id,
        display_name=display_name,
        external_id=str(payload.get("externalId")) if payload.get("externalId") else None,
        members=_values(payload.get("members")),
        roles=_values(payload.get("roles")),
    )
    _repo.save_group(group)
    response.headers["Location"] = f"/scim/v2/Groups/{group.id}"
    return _group_resource(group)


@router.get("/Groups/{group_id}")
async def get_group(
    group_id: str,
    principal: Principal = Depends(require_scopes("scim:read")),
) -> dict[str, Any]:
    _authorize(principal, "scim.read")
    group = _repo.get_group(principal.tenant_id, group_id)
    if not group:
        raise _error("Group not found", 404)
    return _group_resource(group)


@router.patch("/Groups/{group_id}")
async def patch_group(
    group_id: str,
    payload: dict[str, Any],
    principal: Principal = Depends(require_scopes("scim:write")),
) -> dict[str, Any]:
    _authorize(principal, "scim.write")
    group = _repo.get_group(principal.tenant_id, group_id)
    if not group:
        raise _error("Group not found", 404)
    for operation in payload.get("Operations", []):
        op = str(operation.get("op", "replace")).lower()
        path = str(operation.get("path", "")).lower()
        value = operation.get("value")
        if path == "displayname":
            group.display_name = "" if op == "remove" else str(value)
        elif path == "members":
            members = _values(value)
            if op == "remove":
                group.members = [item for item in group.members if item not in set(members)]
            elif op == "add":
                group.members = sorted(set(group.members + members))
            else:
                group.members = members
        elif path == "roles":
            group.roles = [] if op == "remove" else _values(value)
        else:
            raise _error(f"Unsupported patch path: {path}", scim_type="invalidPath")
    return _group_resource(_repo.save_group(group))


@router.delete("/Groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: str,
    principal: Principal = Depends(require_scopes("scim:write")),
) -> Response:
    _authorize(principal, "scim.write")
    if not _repo.delete_group(principal.tenant_id, group_id):
        raise _error("Group not found", 404)
    return Response(status_code=204)
