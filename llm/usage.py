"""Persist OpenAI request accounting without prompts, responses or credentials."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from db.repositories.openai_usage import OpenAIUsageRepository
from db.session import session_scope


def _field(value: Any, name: str, default: Any = None) -> Any:
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def record_openai_call(
    db_path: Path,
    response: Any | None,
    request_kind: str,
    requested_model: str,
    input_rate: Decimal | None,
    cached_input_rate: Decimal | None,
    output_rate: Decimal | None,
) -> None:
    """Write one row per SDK request; unknown usage or pricing remains NULL."""
    usage = _field(response, "usage")
    input_tokens = _field(usage, "input_tokens")
    output_tokens = _field(usage, "output_tokens")
    total_tokens = _field(usage, "total_tokens")
    details = _field(usage, "input_tokens_details")
    cached_tokens = _field(details, "cached_tokens", 0) if input_tokens is not None else None
    cost = None
    if (input_tokens is not None and output_tokens is not None and input_rate is not None
            and output_rate is not None and (not cached_tokens or cached_input_rate is not None)):
        cost = ((Decimal(input_tokens - cached_tokens) * input_rate
                 + Decimal(cached_tokens) * (cached_input_rate or Decimal(0))
                 + Decimal(output_tokens) * output_rate) / Decimal(1_000_000))

    with session_scope(f"sqlite:///{db_path.resolve()}") as session:
        OpenAIUsageRepository(session).record_call(
            response_id=_field(response, "id"),
            request_kind=request_kind,
            model=_field(response, "model") or requested_model,
            status="completed" if response is not None else "failed",
            input_tokens=input_tokens,
            cached_input_tokens=cached_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=str(cost) if cost is not None else None,
            input_rate_usd_per_1m=str(input_rate) if input_rate is not None else None,
            cached_input_rate_usd_per_1m=str(cached_input_rate) if cached_input_rate is not None else None,
            output_rate_usd_per_1m=str(output_rate) if output_rate is not None else None,
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
