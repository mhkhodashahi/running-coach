"""File-backed running coach memory for prompt continuity."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

MEMORY_FILENAME = "couch_running_memory.md"
MAX_PERSISTENT_CUES = 10
MAX_RECENT_ENTRIES = 8


@dataclass(frozen=True)
class CoachMemoryEntry:
    """Compact coaching memory entry derived from a finished coaching run."""

    source: str
    date_text: str
    headline: str
    summary: str
    positives: list[str]
    limiters: list[str]
    recommendations: list[str]
    evidence: list[str]


def memory_path(base_dir: Path | None = None) -> Path:
    """Return the markdown file used for coach memory."""

    root = base_dir or Path(__file__).resolve().parents[1]
    return root / "data" / MEMORY_FILENAME


def default_memory_text() -> str:
    """Seed text for a brand-new coach memory file."""

    return (
        "# Coach Running Memory\n\n"
        "Last updated: never\n\n"
        "## Persistent cues\n"
        "- Prioritize recovery when sleep, body battery, HRV, or recovery time are weak.\n"
        "- Keep easy days truly easy and watch for pace creep.\n"
        "- Build endurance with one long run and one quality session rather than random intensity.\n"
        "- Use the active goal as the main filter for weekly coaching decisions.\n\n"
        "## Recent coaching entries\n"
        "- None yet.\n"
    )


def ensure_memory_file(path: Path | None = None) -> Path:
    """Create the memory file if it does not exist."""

    target = path or memory_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_text(default_memory_text(), encoding="utf-8")
    return target


def load_running_memory(path: Path | None = None, *, max_chars: int = 7000) -> str:
    """Load the markdown memory file, trimming from the front if it grows too large."""

    target = ensure_memory_file(path)
    text = target.read_text(encoding="utf-8").strip()
    if len(text) <= max_chars:
        return text
    trimmed = text[-max_chars:]
    cut = trimmed.find("\n## ")
    if cut > 0:
        return trimmed[cut + 1 :].strip()
    return trimmed.strip()


def running_memory_block(memory_text: str | None) -> str:
    """Wrap memory in a prompt-friendly block."""

    text = (memory_text or "").strip()
    if not text:
        text = "No prior running memory stored yet."
    return f"<running_memory>\n{text}\n</running_memory>"


def build_memory_entry(
    *,
    source: str,
    date_text: str,
    headline: str,
    summary: str,
    positives: Iterable[str] = (),
    limiters: Iterable[str] = (),
    recommendations: Iterable[str] = (),
    evidence: Iterable[str] = (),
) -> CoachMemoryEntry:
    """Create a sanitized memory entry."""

    return CoachMemoryEntry(
        source=_clean_text(source),
        date_text=_clean_text(date_text),
        headline=_clean_text(headline),
        summary=_clean_text(summary),
        positives=_clean_list(positives),
        limiters=_clean_list(limiters),
        recommendations=_clean_list(recommendations),
        evidence=_clean_list(evidence),
    )


def update_running_memory(
    *,
    entry: CoachMemoryEntry,
    path: Path | None = None,
) -> str:
    """Merge a finished coaching run into the markdown memory file."""

    target = ensure_memory_file(path)
    existing = target.read_text(encoding="utf-8")
    persistent_cues = _merge_cues(_extract_section_items(existing, "Persistent cues"), _entry_cues(entry))
    recent_entries = _merge_recent_entries(_extract_section_items(existing, "Recent coaching entries"), entry)
    updated = (
        "# Coach Running Memory\n\n"
        f"Last updated: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %Z')}\n\n"
        "## Persistent cues\n"
        + _render_bullets(persistent_cues, empty_item="- None yet.")
        + "\n## Recent coaching entries\n"
        + _render_bullets(recent_entries, empty_item="- None yet.")
    )
    target.write_text(updated.rstrip() + "\n", encoding="utf-8")
    return updated


def build_memory_entry_from_decision(decision_type: str, decision_date_text: str, decision_payload: dict[str, Any]) -> CoachMemoryEntry:
    """Derive a compact memory entry from a daily or weekly coaching decision."""

    summary = str(decision_payload.get("summary") or decision_payload.get("explanation") or "").strip()
    if not summary:
        summary = "No summary provided."
    positives = _string_items(decision_payload.get("key_positives"))
    limiters = _string_items(decision_payload.get("key_limiters"))
    recommendations = _string_items(
        [
            decision_payload.get("priority"),
            decision_payload.get("daily_advice"),
            decision_payload.get("weekly_advice"),
            decision_payload.get("tomorrow_recommendation"),
            decision_payload.get("weekly_outlook"),
            decision_payload.get("readiness_assessment"),
        ]
    )
    evidence = _string_items(decision_payload.get("evidence"))
    if not evidence and decision_payload.get("goal_alignment"):
        evidence = [str(decision_payload["goal_alignment"]).strip()]
    headline = f"{decision_type.title()} coaching"
    if decision_payload.get("risk_level"):
        headline = f"{headline} ({str(decision_payload.get('risk_level')).strip().lower()})"
    return build_memory_entry(
        source=f"decision:{decision_type}",
        date_text=decision_date_text,
        headline=headline,
        summary=summary,
        positives=positives,
        limiters=limiters,
        recommendations=recommendations,
        evidence=evidence,
    )


def build_memory_entry_from_activity(activity_date_text: str, activity_payload: dict[str, Any]) -> CoachMemoryEntry:
    """Derive a compact memory entry from a per-workout coach opinion."""

    summary = str(
        activity_payload.get("overall_assessment")
        or activity_payload.get("brutally_honest_conclusion")
        or ""
    ).strip()
    if not summary:
        summary = "No summary provided."
    positives = _string_items(activity_payload.get("what_was_good"))
    limiters = _string_items(activity_payload.get("mistakes_or_inefficiencies"))
    recommendations = _string_items(activity_payload.get("training_recommendations"))
    evidence = _string_items(activity_payload.get("evidence"))
    headline = str(activity_payload.get("selected_activity_name") or activity_payload.get("activity_name") or "Workout").strip()
    if not headline:
        headline = "Workout"
    return build_memory_entry(
        source="activity_coaching",
        date_text=activity_date_text,
        headline=headline,
        summary=summary,
        positives=positives,
        limiters=limiters,
        recommendations=recommendations,
        evidence=evidence,
    )


def _extract_section_items(text: str, heading: str) -> list[str]:
    marker = f"## {heading}"
    start = text.find(marker)
    if start == -1:
        return []
    tail = text[start + len(marker) :]
    next_heading = tail.find("\n## ")
    section = tail[:next_heading] if next_heading != -1 else tail
    items: list[str] = []
    for line in section.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            items.append(stripped[2:].strip())
    return [item for item in items if item and item.lower() not in {"none yet.", "none yet"}]


def _merge_cues(existing: list[str], new_items: list[str]) -> list[str]:
    merged: list[str] = []
    for item in [*new_items, *existing]:
        normalized = _shorten(item)
        if normalized and normalized.lower() not in {x.lower() for x in merged}:
            merged.append(normalized)
        if len(merged) >= MAX_PERSISTENT_CUES:
            break
    return merged


def _merge_recent_entries(existing: list[str], entry: CoachMemoryEntry) -> list[str]:
    rendered = _render_entry(entry)
    items = [rendered, *existing]
    cleaned: list[str] = []
    for item in items:
        normalized = item.strip()
        if normalized and normalized.lower() not in {x.lower() for x in cleaned}:
            cleaned.append(normalized)
        if len(cleaned) >= MAX_RECENT_ENTRIES:
            break
    return cleaned


def _render_bullets(items: Iterable[str], *, empty_item: str) -> str:
    rows = [f"- {item.strip()}" for item in items if item and item.strip()]
    if not rows:
        rows = [empty_item]
    return "\n".join(rows) + "\n\n"


def _render_entry(entry: CoachMemoryEntry) -> str:
    pieces = [f"{entry.date_text} [{entry.source}] {entry.headline}: {entry.summary}"]
    if entry.positives:
        pieces.append(f"Positives: {'; '.join(entry.positives[:3])}")
    if entry.limiters:
        pieces.append(f"Limiters: {'; '.join(entry.limiters[:3])}")
    if entry.recommendations:
        pieces.append(f"Next steps: {'; '.join(entry.recommendations[:3])}")
    if entry.evidence:
        pieces.append(f"Evidence: {'; '.join(entry.evidence[:3])}")
    return " | ".join(pieces)


def _entry_cues(entry: CoachMemoryEntry) -> list[str]:
    cues: list[str] = []
    for text in [entry.summary, *entry.positives, *entry.limiters, *entry.recommendations]:
        cue = _shorten(text)
        if cue and cue.lower() not in {item.lower() for item in cues}:
            cues.append(cue)
    return cues[:MAX_PERSISTENT_CUES]


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _clean_list(values: Iterable[Any]) -> list[str]:
    cleaned: list[str] = []
    for value in values:
        if value is None:
            continue
        text = _clean_text(value)
        if not text:
            continue
        if text.lower() not in {item.lower() for item in cleaned}:
            cleaned.append(text)
    return cleaned


def _string_items(value: Any) -> list[str]:
    if isinstance(value, list):
        return _clean_list(value)
    if isinstance(value, str):
        text = _clean_text(value)
        return [text] if text else []
    return []


def _shorten(text: str, *, max_words: int = 16) -> str:
    cleaned = _clean_text(text)
    if not cleaned:
        return ""
    words = cleaned.split()
    if len(words) <= max_words:
        return cleaned
    return " ".join(words[:max_words]).rstrip(",;:") + "..."
