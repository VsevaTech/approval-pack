"""Snapshot file storage.

Files land at ``<storage_dir>/<approval_id><ext>``. The name is built from the
approval's random id plus an extension taken from our own allowlist, so no byte
of user input ever reaches the filesystem path.
"""

from __future__ import annotations

from pathlib import Path

from app.security import ALLOWED_EXTENSIONS, extension_of, resolve_within


class StorageError(RuntimeError):
    pass


class SnapshotStorage:
    def __init__(self, base_dir: Path | str) -> None:
        self.base_dir = Path(base_dir)

    def ensure_ready(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def stored_name(self, approval_id: str, sanitized_filename: str) -> str:
        ext = extension_of(sanitized_filename)
        if ext not in ALLOWED_EXTENSIONS:
            raise StorageError(f"extension not allowed: {ext or '(none)'}")
        if not approval_id.isalnum():
            raise StorageError("approval id must be alphanumeric")
        return f"{approval_id}{ext}"

    def path_for(self, stored_name: str) -> Path:
        if not stored_name or "/" in stored_name or "\\" in stored_name or ".." in stored_name:
            raise StorageError(f"unsafe stored name: {stored_name!r}")
        return resolve_within(self.base_dir, Path(stored_name))

    def write(self, stored_name: str, payload: bytes) -> Path:
        self.ensure_ready()
        path = self.path_for(stored_name)
        path.write_bytes(payload)
        path.chmod(0o600)
        return path

    def read(self, stored_name: str) -> bytes:
        return self.path_for(stored_name).read_bytes()

    def exists(self, stored_name: str) -> bool:
        try:
            return self.path_for(stored_name).is_file()
        except (StorageError, ValueError):
            return False
