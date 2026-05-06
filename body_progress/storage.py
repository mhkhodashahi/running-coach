"""Storage helpers for body progress uploads and outputs."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path


@dataclass(frozen=True)
class StoredUpload:
    """Stored upload metadata."""

    path: Path
    sha256: str
    size_bytes: int
    content_type: str


class LocalBodyScanStorage:
    """Store body scan files under a user/date based local directory."""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)

    def save_upload(
        self,
        *,
        user_id: int,
        scan_date: date,
        filename: str,
        content: bytes,
        content_type: str,
    ) -> StoredUpload:
        if not content:
            raise ValueError("Uploaded body scan image is empty.")

        digest = hashlib.sha256(content).hexdigest()
        suffix = Path(filename).suffix.lower() or ".jpg"
        safe_suffix = suffix if suffix in {".jpg", ".jpeg", ".png", ".webp"} else ".jpg"
        target_dir = self.root_dir / f"user_{user_id}" / scan_date.isoformat()
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{datetime.now(UTC).strftime('%H%M%S')}_{digest[:12]}{safe_suffix}"
        target.write_bytes(content)
        return StoredUpload(
            path=target,
            sha256=digest,
            size_bytes=len(content),
            content_type=content_type or "application/octet-stream",
        )
