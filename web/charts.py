"""Bounded, self-contained SVG charts for the Today view."""

from collections import defaultdict
from html import escape
from typing import Any

from web.formatting import short_date

SPARKLINE_COLORS = {"heart": "var(--heart)", "sleep": "var(--sleep)", "muted": "var(--ink-muted)"}


def heart_rate_chart(points: list[dict[str, Any]], zones: tuple[tuple[str, int, int | None], ...],
                     max_hr: int | None, duration_min: float | None) -> dict[str, str] | None:
    """Render at most one mean HR sample per 10 s; never send raw samples to the template."""
    buckets: dict[int, list[float]] = defaultdict(list)
    for point in points:
        elapsed, hr = point.get("elapsed_seconds"), point.get("heart_rate")
        if elapsed is not None and hr is not None and elapsed >= 0 and hr > 0:
            buckets[int(elapsed // 10)].append(float(hr))
    if len(buckets) < 2:
        return None
    samples = [(bucket * 10, sum(values) / len(values)) for bucket, values in sorted(buckets.items())]
    if len(samples) > 1200:
        stride = max(1, len(samples) // 1200)
        samples = samples[::stride]
    if not zones and max_hr:
        fractions = ((0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.0))
        zones = tuple((f"Z{index}", round(low * max_hr), round(high * max_hr))
                      for index, (low, high) in enumerate(fractions, 1))
    low = max(30, int(min(hr for _, hr in samples) // 10 * 10 - 10))
    high = int(max(hr for _, hr in samples) // 10 * 10 + 20)
    max_time = max(samples[-1][0], (duration_min or 0) * 60, 1)
    def y(value: float) -> float:
        return 180 - (value - low) / max(high - low, 1) * 150

    bands = []
    for index, (_, lower, upper) in enumerate(zones[:5], 1):
        top = y(min(upper if upper is not None else high, high))
        bottom = y(max(lower, low))
        if bottom > top:
            bands.append(f'<rect x="40" y="{top:.1f}" width="740" height="{bottom - top:.1f}" '
                         f'fill="var(--zone-{index})" opacity="0.12"/>')
    path = " ".join(f"{40 + elapsed / max_time * 740:.1f},{y(hr):.1f}" for elapsed, hr in samples)
    peak = round(max(hr for _, hr in samples))
    summary = f"Heart rate over {round(max_time / 60)} minutes; peak {peak} bpm."
    axis = (f'<text x="4" y="30" class="axis-label">{high} bpm</text>'
            f'<text x="4" y="181" class="axis-label">{low} bpm</text>'
            f'<text x="40" y="205" class="axis-label">0:00</text>'
            f'<text x="740" y="205" class="axis-label">{round(max_time / 60)} min</text>')
    svg = ('<svg class="hr-chart" viewBox="0 0 800 215" role="img" '
           f'aria-label="{escape(summary)}"><title>{escape(summary)}</title>' + "".join(bands) +
           f'<polyline points="{path}" fill="none" stroke="var(--heart)" stroke-width="2" '
           'vector-effect="non-scaling-stroke"/>' + axis + '</svg>')
    return {"svg": svg, "summary": summary}


def readiness_ring(value: float | None) -> str:
    score = max(0.0, min(100.0, value or 0.0))
    label = "No data" if value is None else f"{round(value):d}"
    return (
        '<svg class="readiness-ring" viewBox="0 0 160 160" role="img" '
        f'aria-label="Readiness {escape(label)}">'
        '<circle cx="80" cy="80" r="65" fill="none" stroke="var(--line)" stroke-width="10"/>'
        f'<circle cx="80" cy="80" r="65" fill="none" stroke="var(--volt)" stroke-width="10" '
        f'stroke-dasharray="{score * 4.084:.1f} 408.4" transform="rotate(-90 80 80)"/>'
        f'<text x="80" y="88" text-anchor="middle" class="ring-value">{escape(label)}</text>'
        '<text x="80" y="111" text-anchor="middle" class="ring-label">READINESS</text></svg>'
    )


def load_bars(values: list[tuple[str, float | None]], average: float | None, last_sync: str,
              today: str | None = None) -> str:
    maximum = max([value for _, value in values if value is not None] + [average or 0, 1])
    bars = []
    patterns = ('<defs><pattern id="missing-load" width="4" height="4" patternUnits="userSpaceOnUse" '
                'patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="4" '
                'stroke="var(--ink-muted)" stroke-width="1"/></pattern></defs>')
    for index, (day, value) in enumerate(values[-14:]):
        x = index * 32 + 6
        label = f"{short_date(day)}{' (today, in progress)' if day == today else ''}"
        axis = "today" if day == today else day[-2:]
        if value is None:
            bars.append(f'<rect x="{x}" y="105" width="19" height="7" fill="url(#missing-load)">'
                        f'<title>{escape(label)}: No data; {escape(last_sync)}</title></rect>'
                        f'<text x="{x + 9}" y="135" text-anchor="middle" class="axis-label">{axis}</text>')
            continue
        height = max(2, round(value / maximum * 104)) if value else 4
        color = "var(--ink-muted)" if value == 0 else "var(--load)"
        progress = ' opacity="0.6"' if day == today else ""
        bars.append(
            f'<rect x="{x}" y="{112 - height}" width="19" height="{height}" rx="3" '
            f'fill="{color}"{progress}>'
            f'<title>{escape(label)}: {value:.1f} load</title></rect>'
            f'<text x="{x + 9}" y="135" text-anchor="middle" class="axis-label">{axis}</text>'
        )
    line = ""
    if average is not None:
        y = 112 - average / maximum * 104
        line = f'<line x1="0" y1="{y:.1f}" x2="448" y2="{y:.1f}" stroke="var(--ink-muted)" stroke-dasharray="4 4"/>'
    return ('<svg class="load-chart" viewBox="0 0 448 144" role="img" '
            'aria-label="Training load for the last fourteen days">' + patterns + line + "".join(bars) + "</svg>")


def sparkline(values: list[float | None], label: str, color: str = "muted",
              baseline: float | None = None) -> str:
    if color not in SPARKLINE_COLORS:
        raise ValueError("Unknown sparkline color")
    known = [value for value in values if value is not None]
    if len(known) < 2:
        return ""
    if baseline is not None:
        known.append(baseline)
    low, high = min(known), max(known)
    span = high - low or 1
    coordinates = [f"{index * 13},{32 - (value - low) / span * 25:.1f}"
                   for index, value in enumerate(values) if value is not None]
    if len(coordinates) < 2:
        return ""
    baseline_line = (f'<line x1="0" y1="{32 - (baseline - low) / span * 25:.1f}" '
                     f'x2="84" y2="{32 - (baseline - low) / span * 25:.1f}" '
                     'stroke="var(--ink-muted)" stroke-width="1" stroke-dasharray="3 3"/>') if baseline is not None else ""
    return (f'<svg class="sparkline" viewBox="0 0 84 40" role="img" '
            f'aria-label="{escape(label)} recent trend">{baseline_line}'
            f'<polyline points="{" ".join(coordinates)}" '
            f'fill="none" stroke="{SPARKLINE_COLORS[color]}" stroke-width="2"/></svg>')
