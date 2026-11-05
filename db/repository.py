"""Backward-compatible access to the repositories' legacy operations.

New application code should depend on the focused repository classes in
``db.repositories``. This module remains for the retired Streamlit UI and
older service entry points while those callers are migrated.
"""

from __future__ import annotations

from typing import Any

from db.repositories import compatibility as _compatibility

__all__ = [name for name in dir(_compatibility) if not name.startswith("_")]


def __getattr__(name: str) -> Any:
    return getattr(_compatibility, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
