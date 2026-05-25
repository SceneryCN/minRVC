"""模型加载与本地缓存管理。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional


def sha256_of(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def verify_or_remove(path: Path, expected_sha256: Optional[str]) -> bool:
    if not path.exists():
        return False
    if expected_sha256 is None:
        return True
    actual = sha256_of(path)
    if actual.lower() == expected_sha256.lower():
        return True
    path.unlink(missing_ok=True)
    return False
