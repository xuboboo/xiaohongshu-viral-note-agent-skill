from __future__ import annotations

import hashlib
import mimetypes
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from xhs_skill.core.config import Settings, get_settings
from xhs_skill.core.identifiers import private_mkdir, validate_identifier
from xhs_skill.operations.models import AssetRecord
from xhs_skill.operations.repository import OperationsRepository

if TYPE_CHECKING:
    from xhs_skill.storage.assets import AssetStore


class AssetLibrary:
    def __init__(
        self,
        settings: Settings | None = None,
        repository: OperationsRepository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repository = repository or OperationsRepository(self.settings)
        self.root = private_mkdir(self.settings.asset_library_dir)

    def import_file(
        self,
        path: str | Path,
        *,
        tenant_id: str = "local",
        account_id: str | None = None,
        tags: list[str] | None = None,
        rights_status: str = "USER_OWNED",
        source: str = "UPLOAD",
    ) -> AssetRecord:
        source_path = Path(path).expanduser().resolve()
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        tenant = validate_identifier(tenant_id, field="tenant_id")
        digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
        tenant_root = private_mkdir(self.root / tenant / digest[:2])
        destination = tenant_root / f"{digest}{source_path.suffix.lower()}"
        if not destination.exists():
            shutil.copy2(source_path, destination)
            destination.chmod(0o600)
        record = AssetRecord(
            tenant_id=tenant,
            account_id=account_id,
            sha256=digest,
            filename=source_path.name,
            media_type=mimetypes.guess_type(source_path.name)[0] or "application/octet-stream",
            size_bytes=source_path.stat().st_size,
            storage_path=str(destination),
            tags=tags or [],
            rights_status=rights_status,
            source=source,
        )
        return self.repository.save_asset(record)


    def import_asset_id(
        self,
        asset_id: str,
        *,
        asset_store: AssetStore,
        tenant_id: str = "local",
        account_id: str | None = None,
        tags: list[str] | None = None,
        rights_status: str = "USER_OWNED",
        source: str = "ASSET_STORE",
    ) -> AssetRecord:
        metadata = asset_store.metadata(tenant_id, asset_id)
        safe_path = asset_store.resolve(tenant_id, asset_id)
        record = self.import_file(
            safe_path,
            tenant_id=tenant_id,
            account_id=account_id,
            tags=tags,
            rights_status=rights_status,
            source=source,
        )
        return record.model_copy(
            update={
                "metadata": {**record.metadata, "source_asset_id": metadata.asset_id},
            }
        )

    def search(self, tenant_id: str = "local", tags: list[str] | None = None) -> list[AssetRecord]:
        return self.repository.search_assets(tenant_id, tags)
