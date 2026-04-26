from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from newsletter.config import get_settings


@dataclass(slots=True)
class StoredObject:
    object_key: str
    byte_size: int
    checksum: str


class FilesystemObjectStore:
    def __init__(self, root: Path | None = None) -> None:
        settings = get_settings()
        self.root = root or settings.object_store_root
        self.root.mkdir(parents=True, exist_ok=True)

    def put_bytes(self, object_key: str, data: bytes) -> StoredObject:
        destination = self.root / object_key
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        checksum = hashlib.sha256(data).hexdigest()
        return StoredObject(object_key=object_key, byte_size=len(data), checksum=checksum)

