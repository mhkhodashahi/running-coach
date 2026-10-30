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
from llm.schemas import (
    CoachOpinionV2,
    CoachOpinionV21,
    CoachOpinionV22,
    CoachOpinionV23,
    OpinionDraftV22,
    OpinionDraftV23,
    OpinionDraftV26,
)
from services.activity_coaching_service import ActivityCoachingService, _update_activity_memory
from services.coach_facts import IntentDecision
from services.coach_opinion import (
    assemble_opinion,
    assemble_opinion_v23,
    assemble_opinion_v26,
    collect_v23_evidence_ids,
    draft_validation_errors,
    load_opinion,
    opinion_rule_errors,
    unsupported_evidence,
    unsupported_numbers,
)


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


def test_legacy_headline_is_first_sentence_without_rewriting_json():
    original = '{"brutally_honest_conclusion":"Start controlled. Then build gradually."}'
    row = SimpleNamespace(schema_version=None, payload_json=original)
    opinion = load_opinion(row)
    assert opinion.headline == "Start controlled."
    assert opinion.conclusion == "Then build gradually."
    assert row.payload_json == original


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
        user.max_hr = 200
        repository.bulk_upsert_activities(session, [{
            "user_id": user.id, "external_id": "invented-1", "date": date(2026, 5, 22),
            "type": "running", "distance": 5.0, "duration": 30.0, "pace": 6.0,
            "avg_hr": 120, "notes": "Manual easy session",
        }])
    with factory() as session:
        activity_id = repository.activity_ids_by_external_id(session, 1, ["invented-1"])["invented-1"]
    with factory.begin() as session:
        repository.replace_activity_track_points(session, activity_id, [
            {"point_index": index, "elapsed_seconds": index * 30, "distance_km": index / 12,
             "heart_rate": 120, "cadence": 160, "pace": 6.0}
            for index in range(61)
        ])
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


def draft_payload(*, worked=None, evidence_ids=None):
    return {
        "headline": "A measured run", "conclusion": "Keep it controlled.",
        "assessment": "I see a measured effort.",
        "verdicts": [{"aspect": aspect, "rating": "good", "word": "Moderate" if aspect == "Aerobic stimulus" else "Good"}
                     for aspect in ("Pacing", "Intensity vs plan", "Aerobic stimulus", "HR control")],
        "worked": worked if worked is not None else [{"lead": "You kept the effort controlled.", "detail": ""}],
        "fix": [{"lead": "Start the next run gently.", "detail": ""}],
        "sections": {}, "recommendations": [],
        "evidence_ids": evidence_ids if evidence_ids is not None else ["DISTANCE", "DURATION", "AVG_PACE", "AVG_HR"],
    }


def draft_payload_v23(**changes):
    payload = draft_payload()
    payload["worked"] = [
        {"lead": "You kept the effort controlled.", "detail": ""},
        {"lead": "You stayed patient.", "detail": ""},
    ]
    return payload | changes


def draft_payload_v26(**changes):
    payload = draft_payload_v23()
    payload.update({
        "assessment": "I saw 5.0 km at 6:00 /km. You kept your average HR at 120 bpm. I would keep that control.",
        "worked": [
            {"lead": "You held a measured pace.", "detail": "The 6:00 /km pace stayed controlled.",
             "evidence_ids": ["AVG_PACE"]},
            {"lead": "You kept the effort contained.", "detail": "The average HR was 120 bpm.",
             "evidence_ids": ["AVG_HR"]},
            {"lead": "You completed the distance.", "detail": "The run covered 5.0 km.",
             "evidence_ids": ["DISTANCE"]},
        ],
        "fix": [
            {"lead": "Keep the next effort steady.", "detail": "Use 6:00 /km as a reference.",
             "evidence_ids": ["AVG_PACE"]},
            {"lead": "Watch your effort near the finish.", "detail": "Compare it with 120 bpm.",
             "evidence_ids": ["AVG_HR"]},
        ],
        "sections": {
            "pacing": "I see 6:00 /km as the reference. Your start was controlled. Keep that rhythm.",
            "aerobic": "I see 120 bpm on average. That is useful context. Keep the effort deliberate.",
            "recovery": "Baseline still building means the trend is thin. I cannot judge a trend yet. Keep the next effort controlled.",
            "mental": "I see a controlled 6:00 /km effort.",
        },
        "section_evidence_ids": {"pacing": ["AVG_PACE"], "aerobic": ["AVG_HR"],
                                 "recovery": ["WEEKLY_LIMIT"], "mental": ["AVG_PACE"]},
        "recommendations": [
            {"text": "On the next outing, use 6:00 /km as a reference.", "action": "none", "session": {},
             "evidence_ids": ["AVG_PACE"]},
            {"text": "Tomorrow, keep the effort near 120 bpm.", "action": "none", "session": {},
             "evidence_ids": ["AVG_HR"]},
        ],
        "evidence_ids": ["DISTANCE", "DURATION", "AVG_PACE", "AVG_HR", "WEEKLY_LIMIT"],
    })
    return payload | changes


@pytest.mark.parametrize("change", [
    {"assessment": "Only one sentence."},
    {"worked": []},
    {"fix": []},
    {"sections": {"pacing": "Too brief.", "aerobic": "Three sentences. Are needed. Here.",
                  "recovery": "Three sentences. Are needed. Here."}},
    {"recommendations": []},
])
def test_v26_schema_enforces_depth(change):
    with pytest.raises(ValidationError):
        OpinionDraftV26.model_validate(draft_payload_v26(**change))


def test_v26_evidence_comes_only_from_explicit_known_citations():
    draft = OpinionDraftV26.model_validate(draft_payload_v26())
    facts = [{"id": name, "metric": name, "display": display, "source": f"fixture.{name}"}
             for name, display in (("DISTANCE", "5.0 km"), ("DURATION", "30:00"),
                                   ("AVG_PACE", "6:00 /km"), ("AVG_HR", "120 bpm"),
                                   ("WEEKLY_LIMIT", "baseline still building"),
                                   ("UNUSED", "999 bpm"))]
    opinion = assemble_opinion_v26(draft, facts, IntentDecision("recovery", ("AVG_HR",)), None, [])
    assert {item.source for item in opinion.evidence} == {f"fixture.{name}" for name in
                                                        ("DISTANCE", "DURATION", "AVG_PACE", "AVG_HR", "WEEKLY_LIMIT")}
    assert "evidence_ids" not in opinion.model_dump_json()


def test_v26_unknown_point_fact_id_is_rejected():
    draft = OpinionDraftV26.model_validate(draft_payload_v26())
    facts = [{"id": name, "metric": name, "display": display, "source": name}
             for name, display in (("DISTANCE", "5.0 km"), ("DURATION", "30:00"),
                                   ("AVG_PACE", "6:00 /km"), ("AVG_HR", "120 bpm"),
                                   ("WEEKLY_LIMIT", "baseline still building"))]
    draft.worked[0].evidence_ids = ["UNKNOWN"]
    with pytest.raises(ValueError, match="unknown fact ID UNKNOWN"):
        assemble_opinion_v26(draft, facts, IntentDecision("recovery", ("AVG_HR",)), None, [])


def test_v26_accepts_cited_percent_short_form_but_not_changed_units():
    payload = draft_payload_v26()
    payload["sections"]["recovery"] = "The weekly limit is 110%. I would stay controlled. Recovery still matters."
    draft = OpinionDraftV26.model_validate(payload)
    facts = [{"id": name, "metric": name, "display": display, "source": name}
             for name, display in (("DISTANCE", "5.0 km"), ("DURATION", "30:00"),
                                   ("AVG_PACE", "6:00 /km"), ("AVG_HR", "120 bpm"),
                                   ("WEEKLY_LIMIT", "110% of usual"))]
    assert assemble_opinion_v26(draft, facts, IntentDecision("recovery", ("AVG_HR",)), None, []).sections.recovery
    draft.sections.recovery = "The weekly limit is 110 bpm. I would stay controlled. Recovery still matters."
    with pytest.raises(ValueError, match="uncited or unsupported numbers"):
        assemble_opinion_v26(draft, facts, IntentDecision("recovery", ("AVG_HR",)), None, [])


def test_v26_single_fix_requires_a_clear_intent_match(opinion_db):
    factory, _, activity_id = opinion_db
    service = service_for(opinion_db, MockLLM())
    with factory() as session:
        user = repository.get_or_create_default_user(session, 1)
        context, _, _ = service._prepare(session, user, activity_id)
    payload = draft_payload_v26()
    payload["fix"] = payload["fix"][:1]
    draft = OpinionDraftV26.model_validate(payload)
    opinion = assemble_opinion_v26(draft, context["facts_pack"],
                                   IntentDecision(context["detected_intent"], ("AVG_HR",)), None, [])
    assert "fix needs two items" in " ".join(opinion_rule_errors(opinion, context))
    opinion.intent.planned = opinion.intent.detected
    context["planned_intent"] = opinion.intent.detected
    assert "fix needs two items" not in " ".join(opinion_rule_errors(opinion, context))


def test_v26_repair_retry_saves_only_repaired_draft(opinion_db):
    factory, _, activity_id = opinion_db
    bad = draft_payload_v26(assessment="Too brief.")
    llm = MockLLM(bad, draft_payload_v26())
    with factory.begin() as session:
        user = repository.get_or_create_default_user(session, 1)
        result = service_for(opinion_db, llm).generate(session, user=user, activity_id=activity_id)
    assert len(llm.prompts) == 2
    assert "Validation errors" in llm.prompts[1][1]
    assert len(result["worked"]) == 3


def test_v26_preparation_reuses_dated_similar_session_tool(opinion_db):
    factory, _, activity_id = opinion_db
    with factory.begin() as session:
        repository.bulk_upsert_activities(session, [{
            "user_id": 1, "external_id": "invented-prior", "date": date(2026, 5, 10),
            "type": "running", "distance": 5.1, "duration": 31.0, "pace": 6.1,
            "avg_hr": 118, "notes": "Prior invented session",
        }])
    with factory() as session:
        user = repository.get_or_create_default_user(session, 1)
        context, _, _ = service_for(opinion_db, MockLLM())._prepare(session, user, activity_id)
    facts = {fact["id"]: fact for fact in context["facts_pack"]}
    assert facts["SIMILAR_8W_MEDIAN_PACE"]["display"] == "6:06 /km"
    assert facts["SIMILAR_1_DATE"]["display"] == "Sun 10 May"
    assert any(item["id"].startswith("COMPARE_") for item in context["similar_session_facts"])


def service_for(opinion_db, llm):
    return ActivityCoachingService(settings=replace(get_settings(), db_path=opinion_db[1]), llm_client=llm)


def test_valid_v26_saved_and_plan_passed_to_prompt(opinion_db):
    factory, _, activity_id = opinion_db
    llm = MockLLM(draft_payload_v26())
    service = service_for(opinion_db, llm)
    with factory.begin() as session:
        repository.set_activity_planned_intent(session, activity_id=activity_id, user_id=1, planned_intent="easy")
    with factory.begin() as session:
        user = repository.get_or_create_default_user(session, 1)
        result = service.generate(session, user=user, activity_id=activity_id)
    assert result["schema_version"] == 2
    assert '"planned_intent": "easy"' in llm.prompts[0][1]
    assert "<running_memory>" in llm.prompts[0][1]
    assert llm.prompts[0][2] is OpinionDraftV26
    with factory() as session:
        row = repository.get_activity_coaching_insight(session, activity_id, 1)
        assert row.schema_version == "2" and row.prompt_version == "opinion-v2.6"
        assert row.validation_notes is None
        assert json.loads(row.payload_json)["intent"]["planned"] == "easy"
        assert json.loads(row.payload_json)["intent"]["detected"] == "recovery"
        assert len(json.loads(row.payload_json)["evidence"]) == 5
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


def test_unsupported_number_retry_does_not_save(opinion_db):
    factory, _, activity_id = opinion_db
    bad = draft_payload_v26()
    bad["worked"][0]["detail"] = "The effort was 42 bpm."
    llm = MockLLM(bad, bad)
    with factory.begin() as session:
        user = repository.get_or_create_default_user(session, 1)
        with pytest.raises(RuntimeError, match="validation failed after retry"):
            service_for(opinion_db, llm).generate(session, user=user, activity_id=activity_id)
    assert "unsupported numbers" in llm.prompts[1][1]
    with factory() as session:
        assert repository.get_activity_coaching_insight(session, activity_id, 1) is None


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
        service_for(opinion_db, MockLLM(draft_payload_v26())).generate(session, user=user,
                                                                 activity_id=activity_id, regenerate=True)
    with factory() as session:
        history = session.scalars(select(ActivityCoachingOpinionHistory)).one()
        assert history.payload_json == original and history.prompt_context_json == context
        assert history.schema_version is None and history.replaced_at is not None
        current = repository.get_activity_coaching_insight(session, activity_id, 1)
        assert current.schema_version == "2" and current.payload_json != original
        assert session.scalars(select(ActivityCoachingOpinionHistory)).one().payload_json == original


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


def test_v23_unknown_fact_id_retry_rejects_without_saving(opinion_db):
    factory, _, activity_id = opinion_db
    bad = draft_payload_v26(evidence_ids=["DISTANCE", "DURATION", "AVG_PACE", "NOT_A_FACT"])
    llm = MockLLM(bad, bad)
    with factory.begin() as session:
        user = repository.get_or_create_default_user(session, 1)
        with pytest.raises(RuntimeError, match="unknown fact ID"):
            service_for(opinion_db, llm).generate(session, user=user, activity_id=activity_id)
    with factory() as session:
        assert repository.get_activity_coaching_insight(session, activity_id, 1) is None


@pytest.mark.parametrize("change", [
    {"verdicts": []},
    {"verdicts": [{"aspect": "Pacing", "rating": "good", "word": "Very very very hard"}]},
    {"worked": []},
    {"fix": []},
    {"headline": "Elmwood was easy"},
    {"assessment": "I missed the Invented 10K goal"},
    {"evidence_ids": []},
    {"recommendations": [{"text": "Rest", "action": "none", "session": {"sport": "running"}}]},
])
def test_v23_mocked_generation_retries_invalid_rules(opinion_db, change):
    factory, _, activity_id = opinion_db
    bad = draft_payload_v23() | change
    llm = MockLLM(bad, bad)
    service = service_for(opinion_db, llm)
    with factory.begin() as session:
        user = repository.get_or_create_default_user(session, 1)
        context, _, _ = service._prepare(session, user, activity_id)
    context["selected_activity"]["activity_name"] = "Elmwood Run"
    context["active_goal"]["name"] = "Invented 10K"
    with pytest.raises(RuntimeError, match="validation failed after retry"):
        service._request_opinion(context, None)
    assert len(llm.prompts) == 2
    assert "Validation errors" in llm.prompts[1][1]


def test_v21_goal_reference_is_allowed_in_recommendation():
    payload = invented_v21_payload()
    payload["recommendations"] = [{"text": "Use this easy pace while preparing for Invented 10K.",
                                   "action": "none", "session": {}}]
    opinion = CoachOpinionV21.model_validate(payload)
    assert opinion_rule_errors(opinion, invented_v21_context()) == ()


def test_v24_rejects_stored_goal_name_in_recommendation_but_accepts_type_and_distance():
    context = invented_v21_context()
    context["prompt_version"] = "opinion-v2.4"
    context["active_goal"].update({"goal_type": "10k_pb", "target_distance_km": 10})
    payload = invented_v21_payload()
    payload["recommendations"] = [{"text": "Prepare for Invented 10K.", "action": "none", "session": {}}]
    opinion = CoachOpinionV23.model_validate(payload)
    assert "stored name" in " ".join(opinion_rule_errors(opinion, context))
    payload["recommendations"][0]["text"] = "Prepare for your 10K goal."
    opinion = CoachOpinionV23.model_validate(payload)
    assert not any("stored name" in error for error in opinion_rule_errors(opinion, context))
    payload["recommendations"][0]["text"] = "Prepare for your goal."
    opinion = CoachOpinionV23.model_validate(payload)
    assert "type and distance" in " ".join(opinion_rule_errors(opinion, context))


def test_v25_rejects_internal_ratio_wording():
    context = invented_v21_context()
    context["prompt_version"] = "opinion-v2.5"
    payload = invented_v21_payload()
    payload["assessment"] = "I see the load ratio is high."
    opinion = CoachOpinionV23.model_validate(payload)
    assert "internal ratio" in " ".join(opinion_rule_errors(opinion, context))


def invented_draft_facts():
    return [
        {"id": "DISTANCE", "metric": "Distance", "display": "5.0 km", "source": "selected_activity.distance_km"},
        {"id": "DURATION", "metric": "Duration", "display": "30:00", "source": "selected_activity.duration_min"},
        {"id": "AVG_PACE", "metric": "Pace", "display": "6:00 /km", "source": "selected_activity.pace"},
        {"id": "AVG_HR", "metric": "HR", "display": "120 bpm", "source": "selected_activity.avg_hr"},
        {"id": "Z3_PLUS_SHARE", "metric": "Z3+ time", "display": "40.0%", "source": "metrics_snapshot.zones"},
    ]


def test_v22_draft_forbids_code_owned_fields_and_allows_moderate_good():
    draft = OpinionDraftV22.model_validate(draft_payload())
    assert draft.verdicts[2].rating == "good" and draft.verdicts[2].word == "Moderate"
    assert "data_notes" not in draft.model_dump() and "intent" not in draft.model_dump()
    for key in ("intent", "data_notes", "evidence", "confidence", "schema_version"):
        with pytest.raises(ValidationError):
            OpinionDraftV22.model_validate(draft_payload() | {key: []})
    changed = draft_payload()
    changed["verdicts"][0]["word"] = "Hard but fair"
    assert OpinionDraftV22.model_validate(changed).verdicts[0].word == "Hard but fair"
    changed["verdicts"][0]["word"] = "Too many words here"
    with pytest.raises(ValidationError):
        OpinionDraftV22.model_validate(changed)


def test_v22_assembles_intent_notes_and_evidence_from_code_only():
    draft = OpinionDraftV22.model_validate(draft_payload())
    facts = invented_draft_facts()
    notes = ["Invented recording note"]
    opinion = assemble_opinion(draft, facts, IntentDecision("steady", ("Z3_PLUS_SHARE",)), "easy", notes)
    assert isinstance(opinion, CoachOpinionV22)
    assert opinion.intent.model_dump() == {"planned": "easy", "detected": "steady"}
    assert opinion.data_notes == notes
    assert opinion.confidence == "medium"
    assert opinion.evidence[0].model_dump() == {"metric": "Distance", "value": "5.0 km",
                                               "source": "selected_activity.distance_km"}
    assert facts[0]["display"] == "5.0 km"


def test_v22_rejects_unknown_ids_duplicate_ids_and_uncited_numbers():
    facts = invented_draft_facts()
    bad_id = OpinionDraftV22.model_validate(draft_payload(evidence_ids=["DISTANCE", "DURATION", "AVG_PACE", "FAKE"]))
    assert "Unknown evidence ID" in " ".join(draft_validation_errors(bad_id, facts))
    duplicated = OpinionDraftV22.model_validate(draft_payload(evidence_ids=["DISTANCE"] * 4))
    assert "Duplicate evidence IDs" in draft_validation_errors(duplicated, facts)
    numeric = draft_payload(evidence_ids=["DISTANCE", "DURATION", "AVG_PACE", "AVG_HR"])
    numeric["assessment"] = "I saw 40.0% in Z3+."
    draft = OpinionDraftV22.model_validate(numeric)
    assert "Unsupported numbers: 40.0" in draft_validation_errors(draft, facts)
    numeric["evidence_ids"].append("Z3_PLUS_SHARE")
    assert draft_validation_errors(OpinionDraftV22.model_validate(numeric), facts) == ()


def test_v23_attaches_uncited_numeric_fact_and_strips_internal_recommendation_ids():
    facts = invented_draft_facts()
    payload = draft_payload_v23()
    payload["assessment"] = "I saw 40.0% in Z3+."
    payload["recommendations"] = [{"text": "Hold 6:00 /km on a similar session.", "action": "none",
                                   "session": {}, "evidence_ids": ["AVG_PACE"]}]
    draft = OpinionDraftV23.model_validate(payload)
    ids = collect_v23_evidence_ids(draft, facts)
    assert "Z3_PLUS_SHARE" in ids
    opinion = assemble_opinion_v23(draft, facts, IntentDecision("steady", ("Z3_PLUS_SHARE",)), None, [])
    assert isinstance(opinion, CoachOpinionV23)
    assert any(item.value == "40.0%" for item in opinion.evidence)
    assert opinion.recommendations[0].model_dump() == {
        "text": "Hold 6:00 /km on a similar session.", "action": "none", "session": {},
    }


@pytest.mark.parametrize("field", [
    "headline", "assessment", "conclusion", "worked_lead", "worked_detail",
    "fix_lead", "fix_detail", "sections", "recommendations",
])
def test_v23_rejects_known_fact_ids_in_public_text(field):
    payload = draft_payload_v23()
    if field in ("headline", "assessment", "conclusion"):
        payload[field] = "I saw AVG_PACE in the data."
    elif field == "sections":
        payload["sections"] = {"pacing": "I saw AVG_PACE in the data."}
    elif field == "recommendations":
        payload["recommendations"] = [{
            "text": "Hold 6:00 /km; AVG_PACE is the target.",
            "action": "none", "session": {}, "evidence_ids": ["AVG_PACE"],
        }]
    else:
        group, part = field.split("_")
        payload[group][0][part] = "I saw AVG_PACE in the data."
    draft = OpinionDraftV23.model_validate(payload)
    with pytest.raises(ValueError, match="Fact IDs must not appear in opinion text: AVG_PACE"):
        collect_v23_evidence_ids(draft, invented_draft_facts())


def test_v23_unknown_uppercase_token_is_not_treated_as_fact_id():
    draft = OpinionDraftV23.model_validate(draft_payload_v23(assessment="I saw NOT_A_FACT in the data."))
    assert collect_v23_evidence_ids(draft, invented_draft_facts())


def test_v23_fact_id_validation_retries_and_preserves_existing_opinion(opinion_db):
    factory, _, activity_id = opinion_db
    original = '{ "overall_assessment": "Keep this exactly" }'
    with factory.begin() as session:
        repository.upsert_activity_coaching_insight(
            session, user_id=1, activity_id=activity_id, summary="Keep this exactly",
            payload_json=original, prompt_context_json='{"context":true}',
            model_provider="old", model_name="old",
        )
    bad = draft_payload_v26(assessment="I saw AVG_PACE in the data. The run was steady. I would keep control.")
    llm = MockLLM(bad, bad)
    with factory.begin() as session:
        user = repository.get_or_create_default_user(session, 1)
        with pytest.raises(RuntimeError, match="validation failed after retry"):
            service_for(opinion_db, llm).generate(
                session, user=user, activity_id=activity_id, regenerate=True,
            )
    assert len(llm.prompts) == 2
    assert "fact ID in prose AVG_PACE" in llm.prompts[1][1]
    with factory() as session:
        assert repository.get_activity_coaching_insight(session, activity_id, 1).payload_json == original
        assert session.scalars(select(ActivityCoachingOpinionHistory)).all() == []


def test_v23_conditional_easy_cap_cites_zone_bound_even_when_lap_hr_matches():
    facts = invented_draft_facts() + [
        {"id": "KM1_AVG_HR", "metric": "Lap HR", "display": "139 bpm", "source": "lap"},
        {"id": "ZONE_Z2_UPPER_BPM", "metric": "Z2 upper cap", "display": "139 bpm", "source": "zones"},
    ]
    draft = OpinionDraftV23.model_validate(draft_payload_v23(fix=[
        {"lead": "If this was meant as an easy run, cap HR at 139 bpm.", "detail": ""},
    ]))
    assert "ZONE_Z2_UPPER_BPM" in collect_v23_evidence_ids(draft, facts)


@pytest.mark.parametrize("change,expected", [
    ({"assessment": "I saw 41.0% in Z3+."}, "Unsupported numbers"),
    ({"recommendations": [{"text": "Hold 6:00 /km.", "action": "none", "session": {},
                           "evidence_ids": ["MISSING"]}]}, "Unknown recommendation evidence ID"),
    ({"recommendations": [{"text": "Be patient.", "action": "none", "session": {},
                           "evidence_ids": ["AVG_PACE"]}]}, "cited pace, duration or HR-cap target"),
    ({"recommendations": [{"text": "For the next run, hold 6:00 /km.", "action": "none",
                           "session": {}, "evidence_ids": ["AVG_PACE"]}]}, "next session requires add_to_plan"),
])
def test_v23_rejects_unsupported_numbers_and_bad_recommendations(change, expected):
    draft = OpinionDraftV23.model_validate(draft_payload_v23(**change))
    with pytest.raises(ValueError, match=expected):
        collect_v23_evidence_ids(draft, invented_draft_facts())


def test_v23_add_to_plan_requires_closed_session_targets_from_facts():
    facts = invented_draft_facts() + [
        {"id": "PLAN_DURATION_MIN", "metric": "Plan duration", "display": "30 min", "source": "activity"},
        {"id": "ZONE_Z2_UPPER_BPM", "metric": "Z2 cap", "display": "139 bpm", "source": "zones"},
    ]
    recommendation = {"text": "For the next easy run, cap at 139 bpm for 30 min.",
                      "action": "add_to_plan", "session": {"sport": "running", "intent": "easy",
                      "duration_min": 30, "hr_cap_bpm": 139},
                      "evidence_ids": ["ZONE_Z2_UPPER_BPM", "PLAN_DURATION_MIN"]}
    draft = OpinionDraftV23.model_validate(draft_payload_v23(recommendations=[recommendation]))
    assert {"ZONE_Z2_UPPER_BPM", "PLAN_DURATION_MIN"} <= set(collect_v23_evidence_ids(draft, facts))
    with pytest.raises(ValidationError):
        OpinionDraftV23.model_validate(draft_payload_v23(recommendations=[
            recommendation | {"session": recommendation["session"] | {"extra": 1}},
        ]))
    with pytest.raises(ValueError, match="Unsupported session target"):
        collect_v23_evidence_ids(draft, invented_draft_facts())


def invented_v23_opinion_and_context():
    payload = v2_payload(planned=None, worked=[
        {"lead": "You started conservatively at 6:25 /km.", "detail": ""},
        {"lead": "You finished steadily.", "detail": ""},
    ])
    payload["intent"] = {"planned": None, "detected": "steady"}
    payload["fix"] = [{"lead": "If this was meant as an easy run, cap HR at 139 bpm.", "detail": ""}]
    payload["sections"] = {"recovery": "Load ratio is above safe range 0.8–1.3; keep tomorrow light."}
    context = invented_v21_context()
    context["planned_intent"] = None
    context["facts_pack"] = [
        {"id": "CONSERVATIVE_START", "display": "yes"},
        {"id": "FIRST_FULL_KM_PACE", "display": "6:25 /km"},
        {"id": "ZONE_Z2_UPPER_BPM", "display": "139 bpm"},
        {"id": "LOAD_RATIO_STATUS", "display": "above safe range 0.8–1.3"},
        {"id": "READINESS", "display": "70/100"},
    ]
    return CoachOpinionV23.model_validate(payload), context


def test_v23_context_rules_accept_required_recovery_easy_condition_and_start():
    opinion, context = invented_v23_opinion_and_context()
    assert opinion_rule_errors(opinion, context) == ()


@pytest.mark.parametrize("field,value,expected", [
    ("worked", [{"lead": "You started conservatively at 6:25 /km.", "detail": ""}], "worked needs"),
    ("fix", [{"lead": "Ease off next time.", "detail": ""}], "conditional easy-run"),
    ("sections", {"recovery": ""}, "recovery section is required"),
    ("sections", {"recovery": "Recovery looks fine."}, "out-of-range load ratio status"),
])
def test_v23_context_rules_reject_missing_contract_parts(field, value, expected):
    opinion, context = invented_v23_opinion_and_context()
    changed = opinion.model_dump()
    changed[field] = value
    assert expected in " ".join(opinion_rule_errors(CoachOpinionV23.model_validate(changed), context))


def test_v21_saved_row_still_reads_without_revalidation_or_rewrite():
    old = invented_v21_payload()
    old["verdicts"][2]["word"] = "Moderate"
    raw = json.dumps(old, separators=(",", ":"))
    row = SimpleNamespace(schema_version="2", prompt_version="opinion-v2.1", payload_json=raw)
    assert load_opinion(row).verdicts[2].word == "Moderate"
    assert row.payload_json == raw
