"""Persistence boundary for metadata-only OpenAI usage accounting."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from db.models import OpenAIAPICall


class OpenAIUsageRepository:
    """Store token/cost metadata without provider prompts or responses."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def record_call(self, *, response_id: str | None, request_kind: str, model: str,
                    status: str, input_tokens: int | None, cached_input_tokens: int | None,
                    output_tokens: int | None, total_tokens: int | None,
                    estimated_cost_usd: str | None, input_rate_usd_per_1m: str | None,
                    cached_input_rate_usd_per_1m: str | None, output_rate_usd_per_1m: str | None,
                    created_at: datetime) -> None:
        self._session.add(OpenAIAPICall(
            response_id=response_id,
            request_kind=request_kind,
            model=model,
            status=status,
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=estimated_cost_usd,
            input_rate_usd_per_1m=input_rate_usd_per_1m,
            cached_input_rate_usd_per_1m=cached_input_rate_usd_per_1m,
            output_rate_usd_per_1m=output_rate_usd_per_1m,
            created_at=created_at,
        ))
