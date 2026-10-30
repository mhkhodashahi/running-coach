"""Ollama-backed LLM client."""

from __future__ import annotations

import re
from typing import Any

import requests
from pydantic import BaseModel

from llm.base import LLMClient, extract_json
from llm.schemas import CoachOpinionV2, CoachOpinionV21, OpinionDraftV22, OpinionDraftV23, OpinionDraftV26

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

    def __init__(self, base_url: str, model: str, timeout_seconds: int = 120) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

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
                "format": response_schema.model_json_schema()
                if response_schema in (CoachOpinionV2, CoachOpinionV21, OpinionDraftV22, OpinionDraftV23,
                                       OpinionDraftV26) else "json",
                "stream": False,
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        text = response.json().get("response", "").strip()
        payload = extract_json(text)
        if payload:
            return payload
        return {"explanation": text}

    def coach_step(self, system_prompt: str, messages: list[dict[str, Any]],
                   tool_specs: list[dict[str, Any]]) -> dict[str, Any]:
        """Use Ollama chat tools, falling back to a JSON tool request for older servers."""
        chat_messages = [{"role": "system", "content": system_prompt}]
        chat_messages.extend({"role": item["role"], "content": item["content"]} for item in messages
                             if item["role"] != "function_call")
        payload = {"model": self.model, "messages": chat_messages, "stream": False,
                   "tools": [{"type": "function", "function": spec} for spec in tool_specs]}
        response = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=self.timeout_seconds)
        if response.status_code in (400, 404):
            fallback = self.generate_json(system_prompt + " If a tool is needed, return JSON "
                                          "{\"tool_call\":{\"name\":\"tool_name\",\"arguments\":{}}}. "
                                          "Available tools: " + str(tool_specs),
                                          str(messages), response_schema=None)
            if "tool_call" in fallback:
                return {"tool_calls": [fallback["tool_call"]]}
            return {"reply": fallback}
        response.raise_for_status()
        message = response.json().get("message") or {}
        calls = [{"name": item.get("function", {}).get("name"),
                  "arguments": item.get("function", {}).get("arguments", {})}
                 for item in message.get("tool_calls") or []]
        if calls:
            return {"tool_calls": calls}
        parsed = extract_json(message.get("content") or "")
        if "tool_call" in parsed:
            return {"tool_calls": [parsed["tool_call"]]}
        return {"reply": parsed}
