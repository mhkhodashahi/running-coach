"""Structured OpenAI calls use a mocked SDK client, never the network."""

from types import SimpleNamespace

import pytest
from openai.lib._pydantic import to_strict_json_schema

from config import get_settings
from llm.openai_client import OpenAIClient
from llm.schemas import (
    ActivityCoachInsightSchema,
    CoachOpinionV2,
    CoachOpinionV21,
    OpenAICoachOpinionV2,
    OpinionDraftV22,
)


@pytest.fixture(autouse=True)
def approve_remote_only_for_mocked_sdk(monkeypatch):
    monkeypatch.setattr("llm.openai_client.get_settings",
                        lambda: SimpleNamespace(remote_athlete_data_approved=True))


def test_openai_parse_uses_v2_schema_and_rejects_empty_result():
    seen = {}

    def parse(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(output_parsed=None)

    client = OpenAIClient.__new__(OpenAIClient)
    client.model = "synthetic"
    client.client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    with pytest.raises(ValueError, match="empty"):
        client.generate_json("system", "user", response_schema=CoachOpinionV2)
    assert seen["text_format"] is OpenAICoachOpinionV2
    assert seen["model"] == "synthetic"
    assert seen["store"] is False


def test_coach_opinion_v2_has_closed_session_schema():
    schema = to_strict_json_schema(OpenAICoachOpinionV2)
    session = schema["$defs"]["OpenAIOpinionSession"]
    assert session["type"] == "object"
    assert session["additionalProperties"] is False
    assert CoachOpinionV2.model_validate({
        "headline": "Measured run", "assessment": "Useful.", "confidence": "medium",
        "intent": {"planned": None, "detected": "easy"},
        "recommendations": [{"text": "Rest.", "session": {"metric": "invented"}}],
    }).recommendations[0].session == {"metric": "invented"}


def test_openai_default_is_gpt_6_luna(monkeypatch):
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    get_settings.cache_clear()
    try:
        assert get_settings().openai_model == "gpt-6-luna"
    finally:
        get_settings.cache_clear()


def test_remote_athlete_data_approval_is_explicit(monkeypatch):
    monkeypatch.setenv("REMOTE_ATHLETE_DATA_APPROVED", "false")
    get_settings.cache_clear()
    try:
        assert get_settings().remote_athlete_data_approved is False
        monkeypatch.setenv("REMOTE_ATHLETE_DATA_APPROVED", "true")
        get_settings.cache_clear()
        assert get_settings().remote_athlete_data_approved is True
    finally:
        get_settings.cache_clear()


def test_openai_parse_returns_validated_payload():
    expected = CoachOpinionV2(headline="Measured run", assessment="Useful.", confidence="medium",
                              intent={"planned": None, "detected": "easy"})
    client = OpenAIClient.__new__(OpenAIClient)
    client.model = "synthetic"
    client.client = SimpleNamespace(responses=SimpleNamespace(parse=lambda **kwargs: SimpleNamespace(output_parsed=expected)))
    assert client.generate_json("system", "user", response_schema=CoachOpinionV2) == expected.model_dump()


def test_legacy_openai_schema_keeps_json_object_fallback():
    def fail_parse(**kwargs):
        raise ValueError("old schema not accepted")

    response = SimpleNamespace(output_text='{"summary":"legacy"}')
    seen = {}

    def create(**kwargs):
        seen.update(kwargs)
        return response

    client = OpenAIClient.__new__(OpenAIClient)
    client.model = "synthetic"
    client.client = SimpleNamespace(responses=SimpleNamespace(parse=fail_parse,
                                                               create=create))
    assert client.generate_json("system", "user", response_schema=ActivityCoachInsightSchema) == {"summary": "legacy"}
    assert seen["store"] is False
    assert seen["input"].startswith("Return only JSON.")


def test_v21_openai_uses_closed_recommendation_session_schema():
    seen = {}

    def parse(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(output_parsed=None)

    client = OpenAIClient.__new__(OpenAIClient)
    client.model = "synthetic"
    client.client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    with pytest.raises(ValueError, match="empty"):
        client.generate_json("system", "user", response_schema=CoachOpinionV21)
    assert seen["text_format"] is CoachOpinionV21
    assert seen["store"] is False
    schema = to_strict_json_schema(CoachOpinionV21)
    assert schema["$defs"]["EmptyOpinionSession"]["additionalProperties"] is False
    planned = schema["$defs"]["PlannedOpinionSession"]
    assert planned["additionalProperties"] is False
    assert set(planned["required"]) == {"sport", "intent", "duration_min", "hr_cap_bpm"}


def test_v22_openai_uses_draft_schema_without_code_owned_fields():
    seen = {}

    def parse(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(output_parsed=None)

    client = OpenAIClient.__new__(OpenAIClient)
    client.model = "synthetic"
    client.client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    with pytest.raises(ValueError, match="empty"):
        client.generate_json("system", "user", response_schema=OpinionDraftV22)
    assert seen["text_format"] is OpinionDraftV22
    schema = to_strict_json_schema(OpinionDraftV22)
    assert {"evidence_ids", "headline", "assessment"} <= set(schema["properties"])
    assert not {"intent", "data_notes", "evidence", "confidence"} & set(schema["properties"])
    assert schema["$defs"]["EmptyOpinionSession"]["additionalProperties"] is False
    assert schema["$defs"]["PlannedOpinionSession"]["additionalProperties"] is False


def test_openai_refuses_remote_call_without_config_approval(monkeypatch):
    monkeypatch.setattr("llm.openai_client.get_settings",
                        lambda: SimpleNamespace(remote_athlete_data_approved=False))
    client = OpenAIClient.__new__(OpenAIClient)
    client.client = SimpleNamespace(responses=SimpleNamespace(parse=lambda **kwargs: pytest.fail("sent data")))
    with pytest.raises(PermissionError, match="REMOTE_ATHLETE_DATA_APPROVED"):
        client.generate_json("system", "athlete context", response_schema=OpinionDraftV22)
