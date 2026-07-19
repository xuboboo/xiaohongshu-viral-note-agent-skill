from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from xhs_skill.api.app import create_app
from xhs_skill.browser.session_store import EncryptedSessionStore
from xhs_skill.core.auth import TokenError, issue_token, verify_token
from xhs_skill.core.config import Settings
from xhs_skill.publishing.approvals import create_approval
from xhs_skill.publishing.repository import PublishingRepository
from xhs_skill.schemas.content import DeliveryPackage
from xhs_skill.schemas.publishing import AuthSession, LoginStatus, PublishDraft
from xhs_skill.storage.assets import AssetStore


def _strong_secret() -> str:
    return "A9!secure-random-looking-secret-for-tests-Z7@"


def _package() -> DeliveryPackage:
    return DeliveryPackage(
        task_id="task",
        trace_id="trace",
        selected_title="标题",
        body="正文",
        content_hash="hash",
    )


def test_production_rejects_placeholder_or_low_entropy_secrets():
    with pytest.raises(ValueError, match="high-entropy"):
        Settings(
            app_env="production",
            app_secret_key="replace-with-at-least-32-random-bytes",
        )
    settings = Settings(app_env="production", app_secret_key=_strong_secret())
    assert settings.auth_required is True


def test_bearer_tokens_validate_tenant_scopes_and_auth_level():
    settings = Settings(app_secret_key=_strong_secret())
    token = issue_token(
        subject="operator-1",
        tenant_id="tenant-1",
        scopes={"research:read"},
        auth_level=2,
        settings=settings,
    )
    principal = verify_token(token, settings)
    assert principal.tenant_id == "tenant-1"
    assert principal.has("research:read")

    parts = token.split(".")
    with pytest.raises(TokenError):
        verify_token(".".join([parts[0], parts[1], "tampered"]), settings)
    with pytest.raises(TokenError):
        verify_token("x" * 20_000, settings)


def test_remote_api_requires_scope_and_step_up_authentication():
    client = TestClient(create_app())
    assert client.get("/v1/providers").status_code == 401

    limited = issue_token(
        subject="reader",
        tenant_id="tenant-a",
        scopes={"research:read"},
        auth_level=1,
    )
    headers = {"Authorization": f"Bearer {limited}"}
    assert client.get("/v1/providers", headers=headers).status_code == 403
    assert (
        client.post(
            "/v1/publishing/drafts/missing/approve",
            json={},
            headers=headers,
        ).status_code
        == 403
    )


def test_asset_store_is_tenant_scoped_private_and_rejects_traversal(tmp_path: Path):
    import sys

    settings = Settings(
        app_secret_key=_strong_secret(),
        object_storage_dir=tmp_path / "objects",
    )
    store = AssetStore(settings)
    item = store.save_bytes(
        tenant_id="tenant-a",
        filename="cover.png",
        content_type="image/png",
        content=b"\x89PNG\r\n\x1a\n" + b"0" * 32,
    )
    path = store.resolve("tenant-a", item.asset_id)
    # Windows 对 POSIX mode 支持有限，chmod(0o600) 常落成 0o666；仅 *nix 强断言
    if sys.platform != "win32":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with pytest.raises(FileNotFoundError):
        store.resolve("tenant-b", item.asset_id)
    with pytest.raises(ValueError):
        store.resolve("../tenant-a", item.asset_id)


def test_session_store_rejects_unsafe_key_and_uses_private_permissions(tmp_path: Path):
    import sys

    settings = Settings(
        app_secret_key=_strong_secret(),
        xhs_session_dir=tmp_path / "sessions",
    )
    store = EncryptedSessionStore(settings)
    with pytest.raises(ValueError):
        store.save("../escape", {"cookies": []})
    path = store.save("safe-key", {"cookies": []})
    if sys.platform != "win32":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    else:
        assert path.is_file()
        assert path.parent.is_dir()


def test_approval_token_is_not_persisted_and_is_one_time(tmp_path: Path):
    settings = Settings(app_secret_key=_strong_secret())
    repository = PublishingRepository(tmp_path / "publishing")
    draft = PublishDraft(
        id="draft-1",
        account_id="account-1",
        tenant_id="tenant-1",
        package=_package(),
        content_hash="hash",
    )
    repository.save_draft(draft)
    approval = create_approval(draft, settings=settings)
    token = approval.approval_token
    assert token
    repository.save_approval(approval)
    persisted = next((tmp_path / "publishing" / "tenant-1").glob("approval-*.json"))
    body = persisted.read_text(encoding="utf-8")
    assert token not in body
    assert json.loads(body)["approval_token"] is None
    repository.consume_approval(draft.id, draft.tenant_id)
    with pytest.raises(ValueError, match="already been consumed"):
        repository.consume_approval(draft.id, draft.tenant_id)


def test_private_server_paths_are_excluded_from_serialized_models():
    session = AuthSession(
        id="s",
        account_id="a",
        status=LoginStatus.QR_CODE_READY,
        qr_image_path="/private/qr.png",
        qr_image_url="/v1/accounts/a/auth/qr",
    )
    assert "qr_image_path" not in session.model_dump()
    draft = PublishDraft(
        id="d",
        account_id="a",
        package=_package(),
        content_hash="hash",
        preview_path="/private/preview.png",
        preview_url="/v1/publishing/drafts/d/preview-image",
    )
    assert "preview_path" not in draft.model_dump()
