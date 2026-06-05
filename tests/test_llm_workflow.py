from __future__ import annotations

from typing import Any

from services.llm_workflow import generate_structured_payload


class FakeLLM:
    def __init__(self, payload: dict[str, Any] | None = None, error: Exception | None = None) -> None:
        self.payload = payload or {}
        self.error = error

    def generate_json(self, system_prompt, user_prompt, response_schema=None):
        if self.error is not None:
            raise self.error
        return self.payload


def test_generate_structured_payload_normalizes_successful_response() -> None:
    result = generate_structured_payload(
        llm_client=FakeLLM({"confidence": "72"}),
        system_prompt="system",
        user_prompt="user",
        normalize=lambda payload: {"confidence": float(payload["confidence"])},
    )

    assert result.ok is True
    assert result.payload == {"confidence": 72.0}
    assert result.warning is None


def test_generate_structured_payload_returns_warning_on_failure() -> None:
    error = RuntimeError("offline")

    result = generate_structured_payload(
        llm_client=FakeLLM(error=error),
        system_prompt="system",
        user_prompt="user",
        unavailable_message="Coach unavailable",
    )

    assert result.ok is False
    assert result.payload == {}
    assert result.warning == "Coach unavailable: offline"
    assert result.error is error
