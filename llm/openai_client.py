"""OpenAI-backed LLM client."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from llm.base import LLMClient, extract_json
from llm.schemas import CoachOpinionV2, OpenAICoachOpinionV2


class OpenAIClient(LLMClient):
    """Generate structured coaching with the OpenAI Responses API."""

    def __init__(self, api_key: str, model: str) -> None:
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key)
        self.model = model

    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: type[BaseModel] | None = None,
    ) -> dict[str, Any]:
        if response_schema is not None:
            try:
                output_schema = OpenAICoachOpinionV2 if response_schema is CoachOpinionV2 else response_schema
                response = self.client.responses.parse(
                    model=self.model,
                    instructions=system_prompt,
                    input=user_prompt,
                    text_format=output_schema,
                    store=False,
                )
                if response.output_parsed is None:
                    raise ValueError("Structured model response was empty")
                return response.output_parsed.model_dump()
            except Exception:
                if response_schema is CoachOpinionV2:
                    raise

        response = self.client.responses.create(
            model=self.model,
            instructions=system_prompt,
            input=f"Return only JSON.\n\n{user_prompt}",
            text={"format": {"type": "json_object"}},
            store=False,
        )
        text = response.output_text
        payload = extract_json(text)
        if payload:
            return payload
        return {"explanation": text.strip()}
