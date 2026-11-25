from datetime import UTC, datetime

from web.calendar_export import session_ical


def test_calendar_export_contains_day_and_structured_workout():
    session = {
        "id": 17, "date": "2026-11-25", "sport": "running", "intent": "tempo",
        "duration_min": 44, "hr_cap_bpm": 160, "workout_json": {
            "title": "Threshold run 44 min", "purpose": "Build controlled strength.",
            "why_day": "It is spaced from harder sessions.", "how_it_feels": "comfortably hard",
            "steps": [{"label": "Main set", "reps": 3, "duration_min": 8,
                       "hr_target": "150–160 bpm", "pace_target": "5:00–5:10 /km"}],
        },
    }
    output = session_ical(session, generated_at=datetime(2026, 11, 25, tzinfo=UTC))

    assert "DTSTART;VALUE=DATE:20261125" in output
    assert "DTEND;VALUE=DATE:20261126" in output
    assert "SUMMARY:Threshold run 44 min" in output
    assert "3 repetitions" in output
    assert "150–160 bpm" in output
    assert "5:00–5:10 /km" in output
    assert output.endswith("END:VCALENDAR\r\n")


def test_calendar_export_escapes_injection_and_folds_utf8_lines():
    session = {"id": 2, "date": "2026-11-25", "sport": "gym", "intent": "light",
               "duration_min": 30, "hr_cap_bpm": None,
               "workout_json": {"title": "Gym,\nInjected: event", "purpose": "é" * 80}}
    output = session_ical(session, generated_at=datetime(2026, 11, 25, tzinfo=UTC))

    assert "SUMMARY:Gym\\,\\nInjected: event" in output
    assert "\r\n " in output
    assert all(len(line.encode("utf-8")) <= 75 for line in output.split("\r\n") if line)
