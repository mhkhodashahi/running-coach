"""Verify model-written numeric claims against code-owned display facts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import TypedDict


class NumberFact(TypedDict):
    id: str
    metric: str
    display: str
    source: str


@dataclass(frozen=True)
class NumberClaim:
    text: str
    kind: str
    value: float | tuple[int, int, int]


@dataclass(frozen=True)
class NumberVerification:
    matched: tuple[NumberFact, ...]
    unmatched: tuple[str, ...]
    claims: int
    verified: int


_CLAIM = re.compile(
    r"(?<![\w])(?:\d{4}-\d{2}-\d{2}|\d{1,2}\s+"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)(?:\w*)?"
    r"|\d+h\s*\d{1,2}m|\d{1,2}:\d{2}(?:\s*/\s*km)?"
    r"|\d+(?:\.\d+)?\s*/\s*10|\d+(?:\.\d+)?\s*%"
    r"|\d+(?:\.\d+)?\s*(?:s/km|bpm|spm|ms|km|hours?|hrs?|min(?:utes?)?|secs?|seconds?|load|m)\b"
    r"|\d+(?:\.\d+)?)(?![\w])", re.I
)
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_MONTHS = {name.lower(): index for index, name in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1)}


def _claim(raw: str, prefix: str) -> NumberClaim | None:
    value = re.sub(r"\s+", " ", raw.strip()).lower()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        day = datetime.fromisoformat(value).date()
        return NumberClaim(raw, "date", (day.year, day.month, day.day))
    dated = re.fullmatch(r"(\d{1,2}) (\w+)", value)
    if dated and dated.group(2)[:3] in _MONTHS:
        return NumberClaim(raw, "date", (0, _MONTHS[dated.group(2)[:3]], int(dated.group(1))))
    if "h" in value and value.endswith("m"):
        hours, minutes = re.findall(r"\d+", value)
        return NumberClaim(raw, "duration", int(hours) * 60 + int(minutes))
    if ":" in value:
        minutes, seconds = map(int, value.split("/")[0].strip().split(":"))
        if "/km" in value or re.search(r"\bpace\b", prefix[-28:], re.I):
            kind = "pace"
        elif re.search(r"\b(?:at|bedtime|woke|wake|asleep|started)\s*$", prefix[-24:], re.I):
            kind = "clock"
        else:
            kind = "colon"
        return NumberClaim(raw, kind, minutes * 60 + seconds)
    number = _NUMBER.match(value)
    if number is None:
        return None
    amount = float(number.group())
    suffix = value[number.end():].replace(" ", "")
    kind = {
        "/10": "rating", "%": "percent", "bpm": "bpm", "spm": "spm",
        "ms": "ms", "km": "km", "m": "m", "s/km": "pace_delta",
        "h": "duration", "hr": "duration", "hrs": "duration", "hour": "duration",
        "hours": "duration", "min": "duration", "minute": "duration",
        "minutes": "duration", "sec": "seconds", "secs": "seconds",
        "second": "seconds", "seconds": "seconds", "load": "load",
    }.get(suffix, "number")
    if suffix in {"h", "hr", "hrs", "hour", "hours"}:
        amount *= 60
    elif suffix in {"sec", "secs", "second", "seconds"}:
        amount /= 60
        kind = "duration"
    return NumberClaim(raw, kind, amount)


def extract_numbers(text: str) -> tuple[NumberClaim, ...]:
    """Extract dated and unit-bearing claims without splitting composite values."""
    result: list[NumberClaim] = []
    for match in _CLAIM.finditer(text):
        # Zone names and kilometre/lap indices identify labels, not measured claims.
        if re.search(r"(?:\bZ|\bZone\s+|\blap\s+|\bkm\s+)$", text[max(0, match.start() - 8):match.start()], re.I):
            if not re.search(r"[A-Za-z/%]", match.group()):
                continue
        claim = _claim(match.group(), text[:match.start()])
        if claim is not None:
            result.append(claim)
    return tuple(result)


def _matches(claim: NumberClaim, fact_claim: NumberClaim) -> bool:
    if claim.kind == "date" or fact_claim.kind == "date":
        if claim.kind != fact_claim.kind:
            return False
        claim_year, claim_month, claim_day = claim.value
        fact_year, fact_month, fact_day = fact_claim.value
        return claim_month == fact_month and claim_day == fact_day and (
            claim_year == 0 or (fact_year != 0 and claim_year == fact_year))
    if claim.kind == "colon":
        compatible = fact_claim.kind in {"pace", "duration", "clock", "colon"}
    elif fact_claim.kind == "colon":
        compatible = claim.kind in {"pace", "duration", "clock"}
    else:
        compatible = claim.kind == fact_claim.kind
    if not compatible:
        return False
    if claim.kind == "clock" or fact_claim.kind == "clock":
        return claim.value == fact_claim.value
    tolerance = 1 if claim.kind in {"pace", "colon"} or fact_claim.kind == "pace" else 0.0
    if claim.kind == "duration" or fact_claim.kind == "duration":
        tolerance = 1.0
    if tolerance == 0:
        precision = len(claim.text.split(".")[-1].split()[0]) if "." in claim.text else 0
        tolerance = 0.5 * (10 ** -precision) + 1e-8
    return abs(float(claim.value) - float(fact_claim.value)) <= tolerance


def verify_numbers(facts: list[NumberFact], text: str) -> NumberVerification:
    """Return code-owned facts supporting claims, plus all unverified claims."""
    fact_claims = [(fact, claim) for fact in facts for claim in extract_numbers(fact["display"])]
    matched: list[NumberFact] = []
    unmatched: list[str] = []
    claims = extract_numbers(text)
    verified = 0
    for claim in claims:
        found = next((fact for fact, candidate in fact_claims if _matches(claim, candidate)), None)
        if found is None:
            if claim.text not in unmatched:
                unmatched.append(claim.text)
        else:
            verified += 1
            if found not in matched:
                matched.append(found)
    return NumberVerification(tuple(matched), tuple(unmatched), len(claims), verified)


def derive_difference(first: NumberFact, second: NumberFact, fact_id: str) -> NumberFact:
    """Add a code-calculated difference only for compatible scalar facts."""
    left, right = extract_numbers(first["display"]), extract_numbers(second["display"])
    if len(left) != 1 or len(right) != 1 or left[0].kind != right[0].kind:
        raise ValueError("Difference needs two facts with the same scalar unit")
    kind = left[0].kind
    if kind in {"date", "clock", "colon", "number"}:
        raise ValueError("Difference needs an explicit measurable unit")
    delta = float(left[0].value) - float(right[0].value)
    unit = {"duration": "min", "percent": "%"}.get(kind, kind)
    return {"id": fact_id, "metric": f"{first['metric']} minus {second['metric']}",
            "display": f"{delta:+g}{'' if unit == '%' else ' '}{unit}",
            "source": f"{first['source']} - {second['source']}"}


def derive_sum(first: NumberFact, second: NumberFact, fact_id: str) -> NumberFact:
    """Add a code-calculated sum only for compatible scalar facts."""
    left, right = extract_numbers(first["display"]), extract_numbers(second["display"])
    if len(left) != 1 or len(right) != 1 or left[0].kind != right[0].kind:
        raise ValueError("Sum needs two facts with the same scalar unit")
    kind = left[0].kind
    if kind in {"date", "clock", "colon", "number"}:
        raise ValueError("Sum needs an explicit measurable unit")
    total = float(left[0].value) + float(right[0].value)
    unit = {"duration": "min", "percent": "%"}.get(kind, kind)
    return {"id": fact_id, "metric": f"{first['metric']} plus {second['metric']}",
            "display": f"{total:g}{'' if unit == '%' else ' '}{unit}",
            "source": f"{first['source']} + {second['source']}"}
