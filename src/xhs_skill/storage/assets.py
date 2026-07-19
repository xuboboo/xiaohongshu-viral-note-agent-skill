from __future__ import annotations

import json
import mimetypes
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

from xhs_skill.core.config import Settings, get_settings
from xhs_skill.core.identifiers import atomic_write_private, private_mkdir, validate_identifier

_ALLOWED = {
    "application/json": {".json"},
    "image/jpeg": {".jpg", ".jpeg"},
    "image/png": {".png"},
    "image/webp": {".webp"},
    "image/gif": {".gif"},
    "video/mp4": {".mp4"},
    "video/quicktime": {".mov"},
    "video/webm": {".webm"},
}


@dataclass(slots=True)
class AssetMetadata:
    asset_id: str
    tenant_id: str
    filename: str
    content_type: str
    size_bytes: int
    path: str


class AssetStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.root = private_mkdir(self.settings.object_storage_dir)

    def _tenant_root(self, tenant_id: str) -> Path:
        tenant = validate_identifier(tenant_id, field="tenant_id")
        return private_mkdir(self.root / tenant)

    @staticmethod
    def _sniff(content: bytes, declared: str, suffix: str) -> str:
        if declared == "application/json" or suffix == ".json":
            try:
                json.loads(content.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("Invalid JSON asset") from exc
            return "application/json"
        if content.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if content.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if content.startswith((b"GIF87a", b"GIF89a")):
            return "image/gif"
        if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
            return "image/webp"
        if len(content) >= 12 and content[4:8] == b"ftyp":
            return "video/quicktime" if suffix == ".mov" else "video/mp4"
        if content.startswith(b"\x1aE\xdf\xa3"):
            return "video/webm"
        raise ValueError("Unsupported or unrecognized asset content")

    def save_bytes(
        self,
        *,
        tenant_id: str,
        filename: str,
        content_type: str | None,
        content: bytes,
    ) -> AssetMetadata:
        if not content:
            raise ValueError("Asset is empty")
        if len(content) > self.settings.asset_upload_max_bytes:
            raise ValueError("Asset exceeds configured size limit")
        original = Path(filename).name
        suffix = Path(original).suffix.lower()
        declared = (content_type or mimetypes.guess_type(original)[0] or "").lower()
        detected = self._sniff(content, declared, suffix)
        if detected not in _ALLOWED or suffix not in _ALLOWED[detected]:
            raise ValueError("File extension does not match detected content type")
        if (
            detected == "application/json"
            and len(content) > self.settings.authorized_import_max_bytes
        ):
            raise ValueError("Authorized import exceeds configured size limit")
        asset_id = f"asset_{uuid4().hex}"
        tenant_root = self._tenant_root(tenant_id)
        path = tenant_root / f"{asset_id}{suffix}"
        atomic_write_private(path, content)
        metadata = AssetMetadata(
            asset_id=asset_id,
            tenant_id=tenant_id,
            filename=original,
            content_type=detected,
            size_bytes=len(content),
            path=str(path),
        )
        atomic_write_private(
            tenant_root / f"{asset_id}.json",
            json.dumps(asdict(metadata), ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        )
        return metadata

    def metadata(self, tenant_id: str, asset_id: str) -> AssetMetadata:
        validate_identifier(asset_id, field="asset_id")
        path = self._tenant_root(tenant_id) / f"{asset_id}.json"
        if path.is_symlink() or not path.is_file():
            raise FileNotFoundError(asset_id)
        data = json.loads(path.read_text(encoding="utf-8"))
        item = AssetMetadata(**data)
        if item.tenant_id != tenant_id or item.asset_id != asset_id:
            raise PermissionError("Asset ownership mismatch")
        return item

    def resolve(
        self,
        tenant_id: str,
        asset_id: str,
        *,
        allowed_types: set[str] | None = None,
    ) -> Path:
        item = self.metadata(tenant_id, asset_id)
        if allowed_types and item.content_type not in allowed_types:
            raise ValueError(f"Asset type {item.content_type} is not allowed here")
        path = Path(item.path).resolve()
        tenant_root = self._tenant_root(tenant_id).resolve()
        if path.parent != tenant_root or path.is_symlink() or not path.is_file():
            raise PermissionError("Unsafe asset path")
        return path

    def delete(self, tenant_id: str, asset_id: str) -> bool:
        try:
            item = self.metadata(tenant_id, asset_id)
        except FileNotFoundError:
            return False
        Path(item.path).unlink(missing_ok=True)
        (self._tenant_root(tenant_id) / f"{asset_id}.json").unlink(missing_ok=True)
        return True
