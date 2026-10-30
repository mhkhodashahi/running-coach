"""Usage accounting is per SDK request and never stores provider content."""

import sqlite3
from decimal import Decimal
from types import SimpleNamespace

import pytest

from db.migration_runner import upgrade_database
from llm.openai_client import OpenAIClient
from llm.schemas import ActivityCoachInsightSchema, CoachOpinionV2


def _client(create):
    client = OpenAIClient.__new__(OpenAIClient)
    client.model = "synthetic"
    client.client = SimpleNamespace(responses=SimpleNamespace(create=create))
    return client


def _settings(path, *, prices=True):
    return SimpleNamespace(
        db_path=path, allow_remote_llm=True, remote_athlete_data_approved=True,
        openai_input_usd_per_1m=Decimal("2") if prices else None,
        openai_cached_input_usd_per_1m=Decimal("0.5") if prices else None,
        openai_output_usd_per_1m=Decimal("8") if prices else None,
    )


def test_each_chat_step_saves_usage_and_cost(tmp_path, monkeypatch):
    path = tmp_path / "usage.db"
    upgrade_database(path)
    monkeypatch.setattr("llm.openai_client.get_settings", lambda: _settings(path))
    response = SimpleNamespace(
        id="resp-synthetic", model="synthetic", output=[], output_text='{"answer":"Done"}',
        usage=SimpleNamespace(input_tokens=1000, output_tokens=100, total_tokens=1100,
                              input_tokens_details=SimpleNamespace(cached_tokens=200)),
    )
    client = _client(lambda **kwargs: response)
    client.coach_step("system", [{"role": "user", "content": "private question"}], [])
    client.coach_step("system", [{"role": "user", "content": "another private question"}], [])
    with sqlite3.connect(path) as connection:
        rows = connection.execute("SELECT request_kind,input_tokens,cached_input_tokens,output_tokens,"
                                  "estimated_cost_usd FROM openai_api_calls ORDER BY id").fetchall()
        assert rows == [("chat", 1000, 200, 100, "0.0025")] * 2
        schema = connection.execute("SELECT sql FROM sqlite_master WHERE name='openai_api_calls'").fetchone()[0]
        assert "private question" not in str(rows) + schema


def test_unknown_price_stays_null_and_failure_is_recorded(tmp_path, monkeypatch):
    path = tmp_path / "usage.db"
    upgrade_database(path)
    monkeypatch.setattr("llm.openai_client.get_settings", lambda: _settings(path, prices=False))
    response = SimpleNamespace(output=[], output_text='{"answer":"Done"}',
                               usage=SimpleNamespace(input_tokens=10, output_tokens=20, total_tokens=30))
    _client(lambda **kwargs: response).coach_step("system", [], [])

    def fail(**kwargs):
        raise RuntimeError("provider unavailable")

    with pytest.raises(RuntimeError, match="provider unavailable"):
        _client(fail).coach_step("system", [], [])
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT status,estimated_cost_usd FROM openai_api_calls ORDER BY id").fetchall() == [
            ("completed", None), ("failed", None)]


def test_structured_and_fallback_requests_are_separate_rows(tmp_path, monkeypatch):
    path = tmp_path / "usage.db"
    upgrade_database(path)
    monkeypatch.setattr("llm.openai_client.get_settings", lambda: _settings(path))
    structured = CoachOpinionV2(headline="Useful run", assessment="Measured.", confidence="medium",
                                intent={"planned": None, "detected": "easy"})
    client = OpenAIClient.__new__(OpenAIClient)
    client.model = "synthetic"
    calls = 0

    def parse(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return SimpleNamespace(output_parsed=structured,
                                   usage=SimpleNamespace(input_tokens=20, output_tokens=10))
        raise ValueError("unsupported legacy schema")

    client.client = SimpleNamespace(responses=SimpleNamespace(
        parse=parse,
        create=lambda **kwargs: SimpleNamespace(output_text='{"summary":"ok"}', usage=None),
    ))
    client.generate_json("system", "private input", response_schema=CoachOpinionV2)
    client.generate_json("system", "private input", response_schema=ActivityCoachInsightSchema)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT request_kind,status,estimated_cost_usd FROM openai_api_calls ORDER BY id").fetchall() == [
            ("structured", "completed", "0.00012"),
            ("structured", "failed", None),
            ("json", "completed", None),
        ]
