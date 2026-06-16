"""Ollama-backed LLM client."""

from __future__ import annotations

import re
from typing import Any

import requests
from pydantic import BaseModel

from llm.base import LLMClient, extract_json

OLLAMA_INPUT_TOKEN_LIMIT = 7500
_TOKEN_PATTERN = re.compile(r"\w+|[^\w\s]", re.UNICODE)


def estimate_input_tokens(text: str) -> int:
    """Return a conservative local estimate for Ollama prompt input tokens."""

    if not text:
        return 0
    regex_count = len(_TOKEN_PATTERN.findall(text))
    char_count = (len(text) + 3) // 4
    return max(regex_count, char_count)


class OllamaClient(LLMClient):
    """Generate structured coaching with a local Ollama model."""

    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: type[BaseModel] | None = None,
    ) -> dict[str, Any]:
        input_tokens = estimate_input_tokens(f"{system_prompt}\n{user_prompt}")
        if input_tokens >= OLLAMA_INPUT_TOKEN_LIMIT:
            raise ValueError(
                f"Ollama input is estimated at {input_tokens} tokens; it must be under "
                f"{OLLAMA_INPUT_TOKEN_LIMIT} tokens. Shorten the activity context or use OpenAI."
            )
        response = requests.post(
            f"{self.base_url}/api/generate",
            json={
                "model": self.model,
                "system": system_prompt,
                "prompt": user_prompt,
                "format": "json",
                "stream": False,
            },
            timeout=120,
        )
        response.raise_for_status()
        text = response.json().get("response", "").strip()
        payload = extract_json(text)
        if payload:
            return payload
        return {"explanation": text}
