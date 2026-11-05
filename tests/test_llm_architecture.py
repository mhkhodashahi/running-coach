from __future__ import annotations

from pydantic import BaseModel

from llm.base import NullLLMClient, extract_json
from llm.schemas import (
    CoachOpinionV2,
    OpenAICoachOpinionV2,
    openai_schema,
    supports_structured_response,
)


class UnsupportedSchema(BaseModel):
    value: str


def test_json_extraction_handles_fences_and_surrounding_prose() -> None:
    assert extract_json('Result: {"answer": {"text": "done"}} trailing') == {
        "answer": {"text": "done"}
    }
    assert extract_json('```json\n{"answer": "done"}\n```') == {"answer": "done"}
    assert extract_json("```json```") == {}


def test_structured_output_capabilities_are_centralized() -> None:
    assert supports_structured_response(CoachOpinionV2)
    assert not supports_structured_response(UnsupportedSchema)
    assert openai_schema(CoachOpinionV2) is OpenAICoachOpinionV2
    assert openai_schema(UnsupportedSchema) is UnsupportedSchema


def test_null_provider_implements_chat_and_generation_contracts() -> None:
    client = NullLLMClient()
    assert client.generate_json("system", "prompt") == {}
    assert client.coach_step("system", [], []) == {"reply": {}}
