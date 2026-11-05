"""Common LLM interfaces and helpers."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


def extract_json(text: str) -> dict[str, Any]:
    """Parse the first JSON object found in a text response."""
    stripped = text.strip()
    if not stripped:
        return {}
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) < 3 or not lines[-1].strip().startswith("```"):
            return {}
        stripped = "\n".join(lines[1:-1]).strip()
    decoder = json.JSONDecoder()
    for index, character in enumerate(stripped):
        if character != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(stripped[index:])
        except json.JSONDecodeError:
            continue
        return payload if isinstance(payload, dict) else {}
    return {}


class LLMClient(ABC):
    """Structured coaching interface."""

    @abstractmethod
    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: type[BaseModel] | None = None,
    ) -> dict[str, Any]:
        """Return a JSON-like dictionary from the model."""

    @abstractmethod
    def coach_step(self, system_prompt: str, messages: list[dict[str, Any]],
                   tool_specs: list[dict[str, Any]]) -> dict[str, Any]:
        """Run one chat step, returning either tool calls or a final reply."""


class NullLLMClient(LLMClient):
    """Fallback client when no external model is configured."""

    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: type[BaseModel] | None = None,
    ) -> dict[str, Any]:
        return {}

    def coach_step(self, system_prompt: str, messages: list[dict[str, Any]],
                   tool_specs: list[dict[str, Any]]) -> dict[str, Any]:
        return {"reply": {}}
