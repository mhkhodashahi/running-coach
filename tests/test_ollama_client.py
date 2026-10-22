from __future__ import annotations

import pytest

from llm.ollama_client import OLLAMA_INPUT_TOKEN_LIMIT, OllamaClient, estimate_input_tokens
from llm.schemas import CoachOpinionV2, CoachOpinionV21, OpinionDraftV22


def test_ollama_client_rejects_prompts_at_token_limit(monkeypatch) -> None:
    def fail_post(*args, **kwargs):
        raise AssertionError("Ollama should not be called when the input is too large")

    monkeypatch.setattr("llm.ollama_client.requests.post", fail_post)
    client = OllamaClient(base_url="http://localhost:11434", model="qwen3:14b")

    with pytest.raises(ValueError, match="under 7500"):
        client.generate_json("", "token " * OLLAMA_INPUT_TOKEN_LIMIT)


def test_ollama_token_estimate_counts_words_and_punctuation() -> None:
    assert estimate_input_tokens("Run easy, then stop.") == 6


def test_ollama_sends_json_schema_as_format(monkeypatch) -> None:
    sent = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"response": '{"headline":"Test"}'}

    def post(*args, **kwargs):
        sent.update(kwargs["json"])
        return Response()

    monkeypatch.setattr("llm.ollama_client.requests.post", post)
    client = OllamaClient(base_url="http://localhost:11434", model="synthetic")
    client.generate_json("system", "prompt", response_schema=CoachOpinionV2)
    assert sent["format"]["properties"]["schema_version"]["const"] == 2


def test_ollama_v21_uses_closed_schema_and_configured_timeout(monkeypatch) -> None:
    seen = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"response": '{"headline":"Test"}'}

    def post(*args, **kwargs):
        seen.update(kwargs)
        return Response()

    monkeypatch.setattr("llm.ollama_client.requests.post", post)
    OllamaClient(base_url="http://localhost:11434", model="synthetic", timeout_seconds=600).generate_json(
        "system", "prompt", response_schema=CoachOpinionV21)
    assert seen["timeout"] == 600
    schema = seen["json"]["format"]
    assert schema["$defs"]["EmptyOpinionSession"]["additionalProperties"] is False
    assert schema["$defs"]["PlannedOpinionSession"]["additionalProperties"] is False


def test_ollama_v22_sends_draft_only_schema(monkeypatch) -> None:
    seen = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"response": '{"headline":"Invented"}'}

    def post(*args, **kwargs):
        seen.update(kwargs["json"])
        return Response()

    monkeypatch.setattr("llm.ollama_client.requests.post", post)
    OllamaClient(base_url="http://localhost:11434", model="synthetic").generate_json(
        "system", "prompt", response_schema=OpinionDraftV22)
    assert "evidence_ids" in seen["format"]["properties"]
    assert "data_notes" not in seen["format"]["properties"]
    assert "intent" not in seen["format"]["properties"]
