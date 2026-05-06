"""Ollama-backed LLM client."""

from __future__ import annotations

from typing import Any

import requests
from pydantic import BaseModel

from llm.base import LLMClient, extract_json


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
