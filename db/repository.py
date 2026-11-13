"""Backward-compatible access to operations not yet moved to domain repositories.

New application code should depend on the focused repository classes in
``db.repositories``. This facade remains for active service and CLI callers
while those call sites are migrated.
"""

from __future__ import annotations

from typing import Any

from db.repositories import compatibility as _compatibility

__all__ = [name for name in dir(_compatibility) if not name.startswith("_")]


def __getattr__(name: str) -> Any:
    return getattr(_compatibility, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
