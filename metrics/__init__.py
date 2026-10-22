"""Dated metrics. Use the pure builder or the explicit read-only DB adapter."""

from metrics.reader import get_daily_snapshot
from metrics.snapshot import build_daily_snapshot

__all__ = ["build_daily_snapshot", "get_daily_snapshot"]
