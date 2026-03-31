from __future__ import annotations

import hashlib
import mimetypes
import shutil
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile

from app.core.config import settings


@dataclass(slots=True)
class StoredFile:
    absolute_path: Path
    relative_path: str
    mime_type: str | None
    file_size_bytes: int
    checksum_sha256: str


class LocalStorageService:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.raw_root = self.root / "raw"
        self.export_root = self.root / "exports"

    def ensure_directories(self) -> None:
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.export_root.mkdir(parents=True, exist_ok=True)

    async def save_upload(self, case_id: str, upload: UploadFile, doc_type: str) -> StoredFile:
        contents = await upload.read()
        destination_dir = self.raw_root / case_id / doc_type
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / upload.filename
        destination.write_bytes(contents)
        return self._build_stored_file(destination)

    def register_existing_file(self, case_id: str, source_path: Path, doc_type: str) -> StoredFile:
        destination_dir = self.raw_root / case_id / doc_type
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / source_path.name
        shutil.copy2(source_path, destination)
        return self._build_stored_file(destination)

    def build_export_path(self, case_id: str, filename: str) -> Path:
        destination_dir = self.export_root / case_id
        destination_dir.mkdir(parents=True, exist_ok=True)
        return destination_dir / filename

    def resolve(self, relative_path: str) -> Path:
        return self.root / relative_path

    def _build_stored_file(self, destination: Path) -> StoredFile:
        checksum = hashlib.sha256(destination.read_bytes()).hexdigest()
        mime_type, _ = mimetypes.guess_type(destination.name)
        relative_path = destination.relative_to(self.root).as_posix()
        return StoredFile(
            absolute_path=destination,
            relative_path=relative_path,
            mime_type=mime_type,
            file_size_bytes=destination.stat().st_size,
            checksum_sha256=checksum,
        )


local_storage_service = LocalStorageService(settings.storage_root)
