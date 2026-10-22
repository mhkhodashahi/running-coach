"""OpenAI-backed LLM client."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from config import get_settings
from llm.base import LLMClient, extract_json
from llm.schemas import CoachOpinionV2, CoachOpinionV21, OpenAICoachOpinionV2, OpinionDraftV22, OpinionDraftV23


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
        settings = get_settings()
        if not settings.allow_remote_llm or not settings.remote_athlete_data_approved:
            raise PermissionError(
                "Remote LLM access is disabled. Set ALLOW_REMOTE_LLM=true and "
                "REMOTE_ATHLETE_DATA_APPROVED=true in .env after approving athlete-data sharing."
            )
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
                if response_schema in (CoachOpinionV2, CoachOpinionV21, OpinionDraftV22, OpinionDraftV23):
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

    def coach_step(self, system_prompt: str, messages: list[dict[str, Any]],
                   tool_specs: list[dict[str, Any]]) -> dict[str, Any]:
        """Use native Responses function calls without storing provider-side state."""
        settings = get_settings()
        if not settings.allow_remote_llm or not settings.remote_athlete_data_approved:
            raise PermissionError("Remote LLM access is disabled. Approve it in .env first.")
        input_items: list[dict[str, Any]] = []
        for item in messages:
            if item["role"] == "function_call":
                input_items.append({"type": "function_call", "call_id": item["call_id"],
                                    "name": item["name"], "arguments": item["arguments"]})
                continue
            if item["role"] == "tool" and item.get("call_id"):
                input_items.append({"type": "function_call_output", "call_id": item["call_id"],
                                    "output": item["content"]})
            elif item["role"] != "tool":
                input_items.append({"role": item["role"], "content": item["content"]})
            else:
                input_items.append({"role": "user", "content": item["content"]})
        response = self.client.responses.create(
            model=self.model, instructions=system_prompt, input=input_items, store=False,
            parallel_tool_calls=False,
            tools=[{"type": "function", **spec} for spec in tool_specs],
        )
        calls = []
        for item in response.output:
            if item.type == "function_call":
                calls.append({"name": item.name, "arguments": item.arguments, "call_id": item.call_id})
        if calls:
            return {"tool_calls": calls}
        from llm.base import extract_json

        return {"reply": extract_json(response.output_text)}
