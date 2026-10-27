"""Pure message shape tests with invented values."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from worker.messages import (
    data_update,
    day_review,
    decision_reason,
    morning,
    proposal_items,
    public_link,
    rating_keyboard,
    short_date,
    weekly_review,
)

DAY = date(2026, 10, 26)


def _decision(*, provisional: bool = False, intensity: str = "hard", rule: str = "hard_allowed"):
    return SimpleNamespace(provisional=provisional, intensity=intensity, rule=rule,
                           based_on="2026-10-23" if provisional else "2026-10-26", readiness=81,
                           sports=({"sport": "running", "session": {"intent": "tempo", "duration_min": 48,
                                    "structure": "10 min easy, 3 x 8 min at 150-165 bpm"}},))


def test_morning_final_and_stale_have_distinct_shapes_and_safe_links():
    final = morning(_decision(), ["Run tempo 48 min"], 0.99, (17, "run on Sun 25 Oct"),
                    public_url="https://coach.example")
    assert final.html.splitlines()[0] == "<b>Hard day — tempo run</b>"
    assert final.plain.splitlines()[1] == "Readiness 81 · load normal (0.99)"
    assert "Run 48 min:" in final.plain
    assert "rpe:17:10" in str(final.keyboard)
    assert final.keyboard[-1][0]["url"] == "https://coach.example/"
    stale = morning(_decision(provisional=True, intensity="easy", rule="stale_data"), [], None,
                    public_url="http://127.0.0.1:8000")
    assert stale.html.splitlines()[0] == "<b>Easy day — waiting for your data</b>"
    assert "Fri 23 Oct" in stale.plain
    assert "127.0.0.1" not in str(stale.keyboard)
    assert data_update("Hard today.").plain == "Data is in. Hard today."


def test_day_review_omits_zero_counts_and_limits_rating_keyboards():
    message = day_review(DAY, ["Run 30 min (extra)"], ["Gym light 30 min"],
                         [(1, "run"), (2, "gym"), (3, "football")], ["Run easy 30 min"],
                         "easy", "recovery needs more time")
    assert message.html.splitlines()[0] == "<b>Mon 26 Oct — day review</b>"
    assert "Done: Run 30 min (extra)" in message.plain
    assert "Skipped: Gym light 30 min" in message.plain
    assert "rpe:3:5" not in str(message.keyboard)
    assert len(rating_keyboard([(1, "run"), (2, "gym"), (3, "team")])) == 4
    rest = day_review(DAY, [], [], [], [], "easy", "recovery needs more time")
    assert len(rest.plain.splitlines()) == 2
    assert "Rest day today. Tomorrow: nothing planned" in rest.plain


def test_weekly_review_uses_counts_signed_trends_and_explicit_links():
    message = weekly_review(DAY, 187.8, 250.0, 2, 3, {"running": 2, "gym": 1, "football": 0},
                            "HRV +3 ms · resting HR -2 bpm vs baseline", "Easy run; light gym", 9,
                            public_url="https://coach.example")
    assert message.html.splitlines()[0] == "<b>Week of Mon 26 Oct — review</b>"
    assert "Load 188 of 250 · 2 of 3 planned sessions done" in message.plain
    assert "Football 0" not in message.plain
    assert message.keyboard[0][0]["callback_data"] == "proposal:9:apply"
    assert message.keyboard[-1][0]["url"] == "https://coach.example/plan"
    assert public_link("http://localhost:8000", "/plan") is None
    assert public_link("https://127.0.0.1", "/plan") is None
    assert public_link("https://coach.example/?token=bad", "/plan") is None
    assert public_link("", "/plan") is None
    assert short_date(DAY) == "Mon 26 Oct"


def test_user_text_is_escaped_in_html():
    message = weekly_review(DAY, 1, None, 0, 0, {}, "", "Run <script>alert(1)</script>", None)
    assert "<script>" not in message.html
    assert "&lt;script&gt;" in message.html


def test_numeric_reasons_only_use_decision_facts_and_illness_adds_doctor_advice():
    illness = SimpleNamespace(rule="illness_signal", facts=(
        {"id": "RHR_DELTA", "display": "+17 bpm"},
        {"id": "HRV_DELTA", "display": "−35 ms"},
        {"id": "LOAD_RATIO", "display": "1.32"},
    ))
    reason = decision_reason(illness)
    assert reason == "resting HR +17 bpm and HRV −35 ms vs your baseline"
    update = data_update("Rest today.", reason, illness=True)
    assert update.plain == ("Data is in. Rest today: resting HR +17 bpm and HRV −35 ms "
                            "vs your baseline. If this persists, see a doctor.")
    load = SimpleNamespace(rule="load_ratio_above_1_3", facts=(
        {"id": "TRAINING_SESSIONS_7D", "display": "2 sessions in the last 7 days"},
        {"id": "LOAD_RATIO", "display": "1.32"},
    ))
    assert decision_reason(load) == "load 1.32, above usual"
    review = day_review(DAY, ["Run 30 min (extra)"], [], [], [], "easy", decision_reason(load))
    assert "outlook easy (load 1.32, above usual)" in review.plain


def test_no_acute_sessions_suppresses_zero_ratio():
    decision = _decision()
    decision.facts = ({"id": "TRAINING_SESSIONS_7D", "display": "0 sessions in the last 7 days"},
                      {"id": "LOAD_RATIO", "display": "0.00"})
    message = morning(decision, [], 0.0)
    assert "no sessions in the last 7 days" in message.plain
    assert "0.00" not in message.plain
    assert decision_reason(decision) == "no sessions in the last 7 days"


def test_weekly_proposal_items_have_day_duration_and_four_item_limit():
    changes = [{"change_type": "add", "session": {"sport": "running", "intent": "easy",
                "duration_min": 32, "date": "2026-10-26"}},
               {"change_type": "add", "session": {"sport": "gym", "intent": "light",
                "duration_min": 30, "date": "2026-10-28"}}]
    assert proposal_items(changes) == "easy run 32 min Mon · light gym 30 min Wed"
    assert len(proposal_items(changes * 3).split(" · ")) == 4
