"""Shared helpers for structured LLM workflow calls."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

PayloadNormalizer = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class LLMWorkflowResult:
    """Result of one structured LLM generation attempt."""

    payload: dict[str, Any]
    warning: str | None = None
    error: Exception | None = None

    @property
    def ok(self) -> bool:
        return self.warning is None and self.error is None


def generate_structured_payload(
    *,
    llm_client: Any,
    system_prompt: str,
    user_prompt: str,
    response_schema: type[BaseModel] | None = None,
    normalize: PayloadNormalizer | None = None,
    unavailable_message: str = "Model unavailable",
) -> LLMWorkflowResult:
    """Call an LLM for structured JSON and normalize the response."""

    try:
        payload = llm_client.generate_json(
            system_prompt,
            user_prompt,
            response_schema=response_schema,
        )
        if normalize is not None:
            payload = normalize(payload)
        return LLMWorkflowResult(payload=payload)
    except Exception as exc:
        return LLMWorkflowResult(payload={}, warning=f"{unavailable_message}: {exc}", error=exc)
