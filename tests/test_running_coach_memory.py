from __future__ import annotations

from services.running_coach_memory import (
    build_memory_entry_from_decision,
    load_running_memory,
    update_running_memory,
)


def test_running_memory_file_is_created_and_updated(tmp_path) -> None:
    path = tmp_path / "couch_running_memory.md"

    initial = load_running_memory(path=path)
    assert "Coach Running Memory" in initial
    assert "Persistent cues" in initial

    entry = build_memory_entry_from_decision(
        "daily",
        "2026-06-04",
        {
            "summary": "Recovery is the main limiter.",
            "key_limiters": ["Sleep and recovery are weak."],
            "key_positives": ["The athlete kept volume steady."],
            "daily_advice": "Keep the next session easy.",
            "priority": "Protect recovery first.",
            "evidence": ["Sleep score 66", "Recovery time 28 h"],
        },
    )

    updated = update_running_memory(entry=entry, path=path)

    assert "2026-06-04 [decision:daily] Daily coaching (moderate): Recovery is the main limiter." in updated
    assert "Protect recovery first." in updated
    assert "Keep the next session easy." in updated
    assert "Sleep score 66" in updated

    reloaded = load_running_memory(path=path)
    assert "Recovery is the main limiter." in reloaded
    assert "Sleep and recovery are weak." in reloaded
