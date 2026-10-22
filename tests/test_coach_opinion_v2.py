"""V2 opinion contract tests use only invented athlete data."""

import json
from dataclasses import replace
from datetime import date
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from config import get_settings
from db import repository
from db.models import ActivityCoachingOpinionHistory, Base
from llm.schemas import CoachOpinionV2, CoachOpinionV21
from services.activity_coaching_service import ActivityCoachingService, _update_activity_memory
from services.coach_opinion import load_opinion, opinion_rule_errors, unsupported_evidence, unsupported_numbers


def test_legacy_mapping_every_field_does_not_rewrite_source():
    raw = {
        "overall_assessment": "Controlled effort.",
        "what_was_good": ["Even pace."],
        "mistakes_or_inefficiencies": ["Late surge."],
        "pacing_analysis": "Even early.",
        "aerobic_efficiency_analysis": "Stable HR.",
        "recovery_analysis": "Rested.",
        "mental_performance_insights": "Patient.",
        "training_recommendations": ["Repeat easy next time."],
        "brutally_honest_conclusion": "Useful session.",
        "evidence": ["Pace 6:22 /km"],
        "confidence": 70,
    }
    original = json.dumps(raw, separators=(",", ":"))
    row = SimpleNamespace(schema_version=None, payload_json=original)
    opinion = load_opinion(row)
    assert row.payload_json == original
    assert opinion.schema_version == 2
    assert opinion.headline == "Useful session."
    assert opinion.assessment == "Controlled effort."
    assert opinion.confidence == "high"
    assert opinion.worked[0].model_dump() == {"lead": "Even pace.", "detail": ""}
    assert opinion.fix[0].lead == "Late surge."
    assert opinion.sections.model_dump() == {"pacing": "Even early.", "aerobic": "Stable HR.",
                                            "recovery": "Rested.", "mental": "Patient."}
    assert opinion.recommendations[0].model_dump() == {"text": "Repeat easy next time.",
                                                      "action": "none", "session": {}}
    assert opinion.evidence[0].model_dump() == {"metric": "", "value": "Pace 6:22 /km", "source": "legacy"}
    assert opinion.intent is None and not opinion.verdicts and not opinion.data_notes


@pytest.mark.parametrize("confidence,expected", [(0, "low"), (39, "low"), (40, "medium"),
                                                   (69, "medium"), (70, "high"), (None, "low")])
def test_sparse_legacy_mapping_and_confidence(confidence, expected):
    payload = {} if confidence is None else {"confidence": confidence}
    row = SimpleNamespace(schema_version=None, payload_json=json.dumps(payload))
    opinion = load_opinion(row)
    assert opinion.confidence == expected
    assert opinion.headline == ""
    assert opinion.assessment == ""
    assert opinion.worked == [] and opinion.evidence == []


def test_v2_enums_and_version_are_strict():
    valid = {"schema_version": 2, "headline": "Steady run", "assessment": "Useful.", "confidence": "medium",
             "intent": {"planned": None, "detected": "steady"}}
    assert load_opinion(SimpleNamespace(schema_version="2", payload_json=json.dumps(valid))).intent.detected == "steady"
    for change in ({"confidence": "uncertain"}, {"schema_version": 3},
                   {"intent": {"planned": "sprint", "detected": "steady"}}):
        with pytest.raises(ValidationError):
            CoachOpinionV2.model_validate(valid | change)


def test_v2_reader_keeps_existing_session_payload():
    payload = {
        "schema_version": 2, "headline": "Steady run", "assessment": "Useful.",
        "confidence": "medium", "intent": {"planned": None, "detected": "steady"},
        "recommendations": [{"text": "Repeat this session.", "action": "none",
                             "session": {"metric": "invented pace", "value": "6:00 /km"}}],
    }
    row = SimpleNamespace(schema_version="2", payload_json=json.dumps(payload))
    original = row.payload_json
    opinion = load_opinion(row)
    assert opinion.recommendations[0].session == payload["recommendations"][0]["session"]
    assert row.payload_json == original


def test_evidence_checker_normalizes_pace_duration_and_decimal():
    opinion = CoachOpinionV2.model_validate({
        "headline": "Evidence", "assessment": "Review.", "confidence": "medium",
        "intent": {"planned": None, "detected": "steady"},
        "worked": [{"lead": "Held 6:22 /km for lap 3", "detail": "Slept 7h 42m"}],
        "fix": [{"lead": "Slow by 5.30 sec", "detail": "Target 10 km"}],
        "sections": {"pacing": "Cadence 170 spm and sleep 7.65h"},
        "evidence": [{"metric": "pace", "value": "6:22 /km", "source": "activity"},
                     {"metric": "sleep", "value": "7h42m", "source": "health"},
                     {"metric": "gap", "value": "5.3 sec", "source": "activity"},
                     {"metric": "distance", "value": "10 km", "source": "activity"}],
    })
    assert unsupported_numbers(opinion) == ("170", "7.65")


class MockLLM:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.prompts = []

    def generate_json(self, system_prompt, user_prompt, response_schema=None):
        self.prompts.append((system_prompt, user_prompt, response_schema))
        return next(self.responses)


@pytest.fixture
def opinion_db(tmp_path, monkeypatch):
    from services import activity_coaching_service

    monkeypatch.setattr(activity_coaching_service, "load_running_memory", lambda: "Invented memory")
    monkeypatch.setattr(activity_coaching_service, "_update_activity_memory", lambda *args: None)
    path = tmp_path / "invented.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory.begin() as session:
        user = repository.get_or_create_default_user(session, 1)
        repository.bulk_upsert_activities(session, [{
            "user_id": user.id, "external_id": "invented-1", "date": date(2026, 5, 22),
            "type": "running", "distance": 5.0, "duration": 30.0, "pace": 6.0,
            "avg_hr": 120, "notes": "Manual easy session",
        }])
    with factory() as session:
        activity_id = repository.activity_ids_by_external_id(session, 1, ["invented-1"])["invented-1"]
    yield factory, path, activity_id
    engine.dispose()


def v2_payload(*, planned=None, worked=None, evidence=None):
    return {
        "schema_version": 2, "headline": "A measured run", "confidence": "medium",
        "conclusion": "Keep it steady.", "assessment": "I saw a controlled session.",
        "intent": {"planned": planned, "detected": "easy"},
        "verdicts": [{"aspect": aspect, "rating": "good", "word": "Good"}
                     for aspect in ("Pacing", "Intensity vs plan", "Aerobic stimulus", "HR control")],
        "worked": worked or [], "fix": [], "data_notes": [], "sections": {},
        "recommendations": [], "evidence": evidence if evidence is not None else [
            {"metric": "sport", "value": "running", "source": "selected_activity.type"},
            {"metric": "distance", "value": "5.0", "source": "selected_activity.distance_km"},
            {"metric": "duration", "value": "30.0", "source": "selected_activity.duration_min"},
            {"metric": "heart rate", "value": "120.0", "source": "selected_activity.avg_hr"},
        ],
    }


def service_for(opinion_db, llm):
    return ActivityCoachingService(settings=replace(get_settings(), db_path=opinion_db[1]), llm_client=llm)


def test_valid_v2_saved_and_plan_passed_to_prompt(opinion_db):
    factory, _, activity_id = opinion_db
    llm = MockLLM(v2_payload(planned="easy"))
    service = service_for(opinion_db, llm)
    with factory.begin() as session:
        repository.set_activity_planned_intent(session, activity_id=activity_id, user_id=1, planned_intent="easy")
    with factory.begin() as session:
        user = repository.get_or_create_default_user(session, 1)
        result = service.generate(session, user=user, activity_id=activity_id)
    assert result["schema_version"] == 2
    assert '"planned_intent": "easy"' in llm.prompts[0][1]
    assert "<running_memory>" in llm.prompts[0][1]
    assert llm.prompts[0][2] is CoachOpinionV21
    with factory() as session:
        row = repository.get_activity_coaching_insight(session, activity_id, 1)
        assert row.schema_version == "2" and row.prompt_version == "opinion-v2.1"
        assert row.validation_notes is None
        assert json.loads(row.payload_json)["intent"]["planned"] == "easy"
        assert json.loads(row.prompt_context_json)["metrics_snapshot"]["as_of"] == "2026-05-22"


def test_invalid_retry_keeps_existing_opinion(opinion_db):
    factory, _, activity_id = opinion_db
    original = '{ "overall_assessment": "Keep this exactly" }'
    with factory.begin() as session:
        repository.upsert_activity_coaching_insight(session, user_id=1, activity_id=activity_id,
                                                   summary="Keep this exactly", payload_json=original,
                                                   prompt_context_json='{"context":true}', model_provider="old", model_name="old")
    llm = MockLLM({"unexpected": "bad"}, {"unexpected": "still bad"})
    with factory.begin() as session:
        user = repository.get_or_create_default_user(session, 1)
        with pytest.raises(RuntimeError, match="validation failed after retry"):
            service_for(opinion_db, llm).generate(session, user=user, activity_id=activity_id, regenerate=True)
    assert len(llm.prompts) == 2
    assert "Validation errors" in llm.prompts[1][1]
    with factory() as session:
        assert repository.get_activity_coaching_insight(session, activity_id, 1).payload_json == original
        assert session.scalars(select(ActivityCoachingOpinionHistory)).all() == []


def test_provider_failure_does_not_consume_validation_retry(opinion_db):
    factory, _, activity_id = opinion_db

    class Unavailable:
        calls = 0

        def generate_json(self, *args, **kwargs):
            self.calls += 1
            raise TimeoutError("local model unavailable")

    llm = Unavailable()
    with factory.begin() as session:
        user = repository.get_or_create_default_user(session, 1)
        with pytest.raises(RuntimeError, match="model unavailable"):
            service_for(opinion_db, llm).generate(session, user=user, activity_id=activity_id)
    assert llm.calls == 1
    with factory() as session:
        assert repository.get_activity_coaching_insight(session, activity_id, 1) is None


def test_evidence_retry_still_unsupported_saves_low(opinion_db):
    factory, _, activity_id = opinion_db
    bad = v2_payload(worked=[{"lead": "Held 42 bpm", "detail": ""}])
    llm = MockLLM(bad, bad)
    with factory.begin() as session:
        user = repository.get_or_create_default_user(session, 1)
        result = service_for(opinion_db, llm).generate(session, user=user, activity_id=activity_id)
    assert result["confidence"] == "low"
    assert "Unsupported numbers" in llm.prompts[1][1]
    with factory() as session:
        row = repository.get_activity_coaching_insight(session, activity_id, 1)
        assert row.validation_notes == "Unsupported numbers: 42"


def test_regeneration_archives_legacy_payload_in_same_transaction(opinion_db):
    factory, _, activity_id = opinion_db
    original = '{ "overall_assessment": "old" }'
    context = '{ "old": true }'
    with factory.begin() as session:
        repository.upsert_activity_coaching_insight(session, user_id=1, activity_id=activity_id,
                                                   summary="old", payload_json=original,
                                                   prompt_context_json=context, model_provider="old", model_name="old")
    with factory.begin() as session:
        user = repository.get_or_create_default_user(session, 1)
        service_for(opinion_db, MockLLM(v2_payload())).generate(session, user=user,
                                                                 activity_id=activity_id, regenerate=True)
    with factory() as session:
        history = session.scalars(select(ActivityCoachingOpinionHistory)).one()
        assert history.payload_json == original and history.prompt_context_json == context
        assert history.schema_version is None and history.replaced_at is not None
        assert repository.get_activity_coaching_insight(session, activity_id, 1).schema_version == "2"


def test_v2_memory_entry_uses_assessment_and_points(monkeypatch):
    from services import activity_coaching_service as module

    saved = []
    monkeypatch.setattr(module, "update_running_memory", lambda *, entry: saved.append(entry))
    opinion = CoachOpinionV2.model_validate(v2_payload(
        worked=[{"lead": "Even effort", "detail": ""}],
        evidence=[{"metric": "pace", "value": "6:00 /km", "source": "activity"}],
    ))
    _update_activity_memory("2026-05-22", "Invented run", opinion)
    assert saved
    assert "I saw a controlled session" in saved[0].summary


def invented_v21_context():
    return {
        "planned_intent": "easy",
        "selected_activity": {"type": "running", "activity_name": "Elmwood Run", "location": "Elmwood",
                              "pace": "6:00 /km", "avg_hr": 120.0, "distance_km": 5.0,
                              "duration_min": 30.0, "aerobic_effect": 2.0},
        "lap_analysis": {"available": True, "laps": [{"pace": "6:00 /km"}]},
        "stream_analysis": {"available": True, "heart_rate": {"avg": 120.0}},
        "active_goal": {"name": "Invented 10K", "goal_label": "10K"},
    }


def invented_v21_payload():
    payload = v2_payload(planned="easy", worked=[{"lead": "Held 6:00 /km", "detail": ""}])
    payload["fix"] = [{"lead": "Keep the first lap controlled", "detail": ""}]
    payload["evidence"][0] = {"metric": "pace", "value": "6:00 /km", "source": "selected_activity.pace"}
    return payload


def test_v21_context_rules_accept_supported_opinion():
    context = invented_v21_context()
    opinion = CoachOpinionV21.model_validate(invented_v21_payload())
    assert opinion_rule_errors(opinion, context) == ()
    assert unsupported_evidence(opinion, context) == ()
    assert unsupported_numbers(opinion) == ()


@pytest.mark.parametrize("change,expected", [
    ({"verdicts": []}, "verdict aspects"),
    ({"worked": []}, "worked and fix"),
    ({"fix": []}, "worked and fix"),
    ({"headline": "Elmwood was easy"}, "location"),
    ({"headline": "Elmwood Run was easy"}, "activity name"),
    ({"assessment": "I missed the Invented 10K goal"}, "long-term goal"),
    ({"intent": {"planned": None, "detected": "easy"}}, "intent.planned"),
])
def test_v21_context_rules_reject_invalid_judgement(change, expected):
    opinion = CoachOpinionV21.model_validate(invented_v21_payload() | change)
    assert any(expected in error for error in opinion_rule_errors(opinion, invented_v21_context()))


def test_v21_allows_only_available_verdicts():
    context = invented_v21_context()
    context["selected_activity"].update({"aerobic_effect": None, "avg_hr": None})
    context["stream_analysis"] = {"available": False}
    opinion = CoachOpinionV21.model_validate(invented_v21_payload())
    assert "verdict aspects" in " ".join(opinion_rule_errors(opinion, context))


@pytest.mark.parametrize("change", [
    {"verdicts": [{"aspect": "Speed", "rating": "good", "word": "Good"}]},
    {"verdicts": [{"aspect": "Pacing", "rating": "excellent", "word": "Good"}]},
    {"verdicts": [{"aspect": "Pacing", "rating": "good", "word": "Very Very Good"}]},
    {"verdicts": [{"aspect": "Pacing", "rating": "good", "word": "Too hard"}]},
    {"verdicts": [{"aspect": "Pacing", "rating": "poor", "word": "Good"}]},
    {"evidence": []},
    {"evidence": [{"metric": "x", "value": "x", "source": "x"}] * 11},
    {"recommendations": [{"text": "Rest", "action": "none", "session": {"sport": "running"}}]},
    {"recommendations": [{"text": "Run", "action": "add_to_plan", "session": {}}]},
    {"recommendations": [{"text": "Run", "action": "add_to_plan", "session": {
        "sport": "running", "intent": "easy", "duration_min": 30, "hr_cap_bpm": 140, "extra": 1}}]},
])
def test_v21_rejects_invalid_schema(change):
    with pytest.raises(ValidationError):
        CoachOpinionV21.model_validate(invented_v21_payload() | change)


def test_v21_closed_plan_session_and_verbatim_evidence():
    payload = invented_v21_payload()
    payload["recommendations"] = [{"text": "Use a short easy run.", "action": "add_to_plan",
                                   "session": {"sport": "running", "intent": "easy",
                                               "duration_min": 30, "hr_cap_bpm": 140}}]
    opinion = CoachOpinionV21.model_validate(payload)
    assert opinion.recommendations[0].session.duration_min == 30
    payload["evidence"][0]["value"] = "6:00/km"
    assert unsupported_evidence(CoachOpinionV21.model_validate(payload), invented_v21_context()) == (
        "selected_activity.pace=6:00/km",)
    payload["evidence"][0] = {"metric": "pace", "value": "6:00 /km", "source": "wrong.path"}
    assert unsupported_evidence(CoachOpinionV21.model_validate(payload), invented_v21_context()) == (
        "wrong.path=6:00 /km",)


def test_v21_evidence_retry_sets_low_confidence(opinion_db):
    factory, _, activity_id = opinion_db
    bad = v2_payload()
    bad["evidence"][0]["value"] = "fabricated"
    llm = MockLLM(bad, bad)
    with factory.begin() as session:
        user = repository.get_or_create_default_user(session, 1)
        result = service_for(opinion_db, llm).generate(session, user=user, activity_id=activity_id)
    assert result["confidence"] == "low"
    with factory() as session:
        row = repository.get_activity_coaching_insight(session, activity_id, 1)
        assert "Unsupported evidence" in row.validation_notes
        assert row.prompt_version == "opinion-v2.1"
