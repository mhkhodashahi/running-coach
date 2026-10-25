"""Bounded, self-contained SVG charts for the Today view."""

from collections import defaultdict
from datetime import date
from html import escape
from math import ceil, floor
from typing import Any

from services.fact_display import hours as display_hours
from web.formatting import short_date

SPARKLINE_COLORS = {"heart": "var(--heart)", "sleep": "var(--sleep)", "muted": "var(--ink-muted)"}
TREND_COLORS = {**SPARKLINE_COLORS, "load": "var(--load)"}
TREND_X = 48
TREND_WIDTH = 510
TREND_TOP = 28
TREND_HEIGHT = 126


def _axis_dates(values: list[tuple[str, float | None]]) -> str:
    if not values:
        return ""
    indices = sorted({round((len(values) - 1) * part / 3) for part in range(4)})
    return "".join(f'<text x="{TREND_X + index / max(len(values) - 1, 1) * TREND_WIDTH:.1f}" '
                   f'y="190" text-anchor="middle" class="axis-label">{escape(short_date(values[index][0]))}</text>'
                   for index in indices)


def _axis_limits(low: float, high: float, unit: str) -> str:
    def label(number: float) -> str:
        value = "0" if number == 0 else f"{number:.2f}" if high - low < 3 else str(round(number))
        return value + (f" {unit}" if unit else "")
    return (f'<text x="2" y="{TREND_TOP + 4}" class="axis-label">{escape(label(high))}</text>'
            f'<text x="2" y="{TREND_TOP + TREND_HEIGHT + 4}" class="axis-label">{escape(label(low))}</text>')


def _trend_path(values: list[tuple[str, float | None]], low: float, high: float,
                width: int = TREND_WIDTH, height: int = TREND_HEIGHT) -> str:
    """Use separate move commands across missing dates, never interpolate gaps."""
    parts = []
    active = False
    for index, (_, value) in enumerate(values):
        if value is None:
            active = False
            continue
        x = TREND_X + index / max(len(values) - 1, 1) * width
        y = TREND_TOP + (high - value) / max(high - low, 0.01) * height
        parts.append(f"{'L' if active else 'M'}{x:.1f},{y:.1f}")
        active = True
    return " ".join(parts)


def trend_line(values: list[tuple[str, float | None]], label: str, color: str,
               baseline: list[tuple[str, float | None]] | None = None,
               *, markers: dict[str, str] | None = None,
               safe_band: tuple[float, float] | None = None, unit: str = "") -> dict[str, str]:
    if color not in TREND_COLORS:
        raise ValueError("Unknown trend color")
    known = [value for _, value in values if value is not None]
    reference = [value for _, value in baseline or [] if value is not None]
    if safe_band:
        reference += list(safe_band)
    last = (f"{known[-1]:.2f}" if unit == "" else f"{round(known[-1])} {unit}") if known else "No data"
    summary = (f"{label}: {len(known)} of {len(values)} days have data; "
               f"{len(values) - len(known)} missing. Latest {last}.")
    if not known:
        return {"svg": "", "summary": summary}
    low, high = min(known + reference), max(known + reference)
    padding = max((high - low) * .12, .15 if safe_band else 1)
    low, high = (0 if safe_band else low - padding), high + padding
    grid = ''.join(f'<line x1="{TREND_X}" x2="{TREND_X + TREND_WIDTH}" y1="{y}" y2="{y}" '
                   'stroke="var(--line)"/>' for y in (TREND_TOP, TREND_TOP + TREND_HEIGHT / 2,
                                                       TREND_TOP + TREND_HEIGHT))
    base = (f'<path d="{_trend_path(baseline, low, high)}" fill="none" '
            'stroke="var(--ink-muted)" stroke-dasharray="5 4" stroke-width="1.5"/>') if baseline else ""
    band = ""
    if safe_band:
        top = TREND_TOP + (high - safe_band[1]) / (high - low) * TREND_HEIGHT
        bottom = TREND_TOP + (high - safe_band[0]) / (high - low) * TREND_HEIGHT
        band = (f'<rect x="{TREND_X}" y="{top:.1f}" width="{TREND_WIDTH}" height="{bottom - top:.1f}" '
                'fill="var(--surface-raised)"/>'
                f'<text x="{TREND_X + 4}" y="{top - 3:.1f}" text-anchor="start" '
                'class="axis-label">1.3</text>'
                f'<text x="{TREND_X + 4}" y="{bottom + 11:.1f}" text-anchor="start" '
                'class="axis-label">0.8</text>')
    marks = []
    for index, (stamp, value) in enumerate(values):
        choice = (markers or {}).get(stamp)
        if value is None or choice not in ("rest", "easy", "hard"):
            continue
        x = TREND_X + index / max(len(values) - 1, 1) * TREND_WIDTH
        y = TREND_TOP + (high - value) / (high - low) * TREND_HEIGHT
        mark = (f'<rect x="{x - 4:.1f}" y="{y - 4:.1f}" width="8" height="8" '
                'fill="var(--ink)"/>' if choice == "rest" else
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="var(--ink)"/>' if choice == "easy" else
                f'<path d="M{x:.1f},{y - 5:.1f} l5,9 h-10 z" fill="var(--ink)"/>')
        marks.append(f'<g><title>{escape(stamp)}: {escape(choice.title())}</title>{mark}</g>')
    if marks:
        summary += " Decision markers: square rest, circle easy, triangle hard."
    latest_index, (_, latest) = next((index, pair) for index, pair in reversed(list(enumerate(values)))
                                     if pair[1] is not None)
    latest_x = TREND_X + latest_index / max(len(values) - 1, 1) * TREND_WIDTH
    latest_y = TREND_TOP + (high - latest) / (high - low) * TREND_HEIGHT
    latest_label = f"{latest:.2f}" if unit == "" else f"{round(latest)} {unit}"
    marker = (f'<circle cx="{latest_x:.1f}" cy="{latest_y:.1f}" r="4" fill="{TREND_COLORS[color]}"/>'
              f'<text x="{min(latest_x - 9, 546):.1f}" y="{latest_y + (22 if latest_y < 43 else -13):.1f}" '
              f'text-anchor="end" class="latest-label">{escape(latest_label)}</text>')
    svg = (f'<svg class="trend-chart" viewBox="0 0 604 205" role="img" aria-label="{escape(summary)}">'
           f'<title>{escape(summary)}</title>{band}{grid}{base}{_axis_limits(low, high, unit)}{_axis_dates(values)}'
           f'<path d="{_trend_path(values, low, high)}" fill="none" stroke="{TREND_COLORS[color]}" '
           'stroke-width="2.5" vector-effect="non-scaling-stroke"/>' + ''.join(marks) + marker + '</svg>')
    return {"svg": svg, "summary": summary}


def trend_bars(values: list[tuple[str, float | None]], label: str,
               goal: float, color: str) -> dict[str, str]:
    if color not in TREND_COLORS:
        raise ValueError("Unknown trend color")
    known = [value for _, value in values if value is not None]
    summary = (f"{label}: {len(known)} of {len(values)} days have data; "
               f"goal {display_hours(goal)}; gaps mean missing data.")
    if not known:
        return {"svg": "", "summary": summary}
    maximum = max(known + [goal, 1]) * 1.08
    bars = []
    width = TREND_WIDTH / max(len(values), 1)
    for index, (stamp, value) in enumerate(values):
        x = TREND_X + index * width + 1
        if value is None:
            bars.append(f'<line x1="{x:.1f}" x2="{x + width - 2:.1f}" y1="{TREND_TOP + TREND_HEIGHT}" '
                        f'y2="{TREND_TOP + TREND_HEIGHT}" '
                        'stroke="var(--ink-muted)" stroke-dasharray="2 2"/>')
            continue
        height = value / maximum * TREND_HEIGHT
        bars.append(f'<rect x="{x:.1f}" y="{TREND_TOP + TREND_HEIGHT - height:.1f}" '
                    f'width="{max(width - 2, 1):.1f}" '
                    f'height="{height:.1f}" fill="{TREND_COLORS[color]}"><title>{escape(stamp)}: '
                    f'{display_hours(value)}</title></rect>')
    goal_y = TREND_TOP + TREND_HEIGHT - goal / maximum * TREND_HEIGHT
    latest_index, (_, latest) = next((index, pair) for index, pair in reversed(list(enumerate(values)))
                                     if pair[1] is not None)
    latest_x = TREND_X + (latest_index + .5) * width
    latest_y = TREND_TOP + TREND_HEIGHT - latest / maximum * TREND_HEIGHT
    svg = (f'<svg class="trend-chart" viewBox="0 0 604 205" role="img" aria-label="{escape(summary)}">'
           f'<title>{escape(summary)}</title><line x1="{TREND_X}" y1="{goal_y:.1f}" '
           f'x2="{TREND_X + TREND_WIDTH}" y2="{goal_y:.1f}" '
           'stroke="var(--ink-muted)" stroke-dasharray="5 4"/>'
           f'{_axis_limits(0, maximum, "h")}{_axis_dates(values)}' + ''.join(bars) +
           f'<text x="{min(latest_x, 545):.1f}" y="{latest_y - 7:.1f}" text-anchor="end" '
           f'class="latest-label">{escape(display_hours(latest) or "No data")}</text></svg>')
    summary += f" Latest {display_hours(latest)}."
    return {"svg": svg, "summary": summary}


def weekly_sport_bars(weeks: dict[str, dict[str, float]], sports: tuple[str, ...],
                      cap: float | None) -> dict[str, str]:
    """Vertical weekly totals are stacked by sport; walking is excluded."""
    week_names = sorted(weeks)
    summary = f"Weekly training load by sport for {len(week_names)} weeks."
    if cap is not None:
        summary += f" Weekly cap {round(cap)} TRIMP."
    if not week_names:
        return {"svg": "", "summary": summary}
    totals = [sum(weeks[week].values()) for week in week_names]
    maximum = max([cap or 0, 1, *totals]) * 1.1
    width = TREND_WIDTH / len(week_names)
    rows = [_axis_limits(0, maximum, "TRIMP")]
    if cap is not None:
        y = TREND_TOP + TREND_HEIGHT - cap / maximum * TREND_HEIGHT
        rows.append(f'<line x1="{TREND_X}" x2="{TREND_X + TREND_WIDTH}" y1="{y:.1f}" y2="{y:.1f}" '
                    'stroke="var(--ink-muted)" stroke-dasharray="5 4"/>'
                    f'<text x="{TREND_X + TREND_WIDTH}" y="{y - 4:.1f}" text-anchor="end" '
                    f'class="axis-label">Cap {round(cap)} TRIMP</text>')
    for index, week in enumerate(week_names):
        x = TREND_X + index * width + width * .18
        bar_width = width * .64
        bottom = TREND_TOP + TREND_HEIGHT
        segment_count = 0
        for sport_index, sport in enumerate(sports):
            value = weeks[week].get(sport, 0)
            height = value / maximum * TREND_HEIGHT
            if height <= 0:
                continue
            bottom -= height
            gap = 1 if segment_count else 0
            if gap:
                rows.append(f'<line x1="{x:.1f}" x2="{x + bar_width:.1f}" y1="{bottom + .5:.1f}" '
                            f'y2="{bottom + .5:.1f}" stroke="var(--ground)" stroke-width="1"/>')
            rows.append(f'<rect x="{x:.1f}" y="{bottom + gap:.1f}" width="{bar_width:.1f}" '
                        f'height="{max(height - gap, 0):.1f}" fill="var(--load)" '
                        f'opacity="{.35 + sport_index * .2:.2f}">'
                        f'<title>{escape(short_date(week))}: {escape(sport)} {round(value)} TRIMP</title></rect>')
            if height >= 18:
                label = {"running": "Run", "gym": "Gym", "team sports": "Team", "other": "Other"}.get(sport, sport)
                rows.append(f'<text x="{x + bar_width / 2:.1f}" y="{bottom + height / 2 + 3:.1f}" '
                            f'text-anchor="middle" class="bar-segment-label">{escape(label)}</text>')
            segment_count += 1
        rows.append(f'<text x="{x + bar_width / 2:.1f}" y="190" text-anchor="middle" '
                    f'class="axis-label">{escape(date.fromisoformat(week).strftime("%d %b"))}</text>')
        rows.append(f'<text x="{x + bar_width / 2:.1f}" y="{max(bottom - 5, 18):.1f}" '
                    f'text-anchor="middle" class="latest-label">{round(totals[index])}</text>')
    summary += f" Latest week {round(totals[-1])} TRIMP."
    svg = (f'<svg class="weekly-sport-chart" viewBox="0 0 604 205" role="img" aria-label="{escape(summary)}">'
           f'<title>{escape(summary)}</title>' + ''.join(rows) + '</svg>')
    return {"svg": svg, "summary": summary}


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
    zone_lows = [bound for _, bound, _ in zones]
    zone_highs = [bound for _, _, bound in zones if bound is not None]
    low = max(20, floor((min([hr for _, hr in samples] + zone_lows or [60]) - 10) / 20) * 20)
    high = ceil((max([hr for _, hr in samples] + zone_highs or [180]) + 10) / 20) * 20
    max_time = max(samples[-1][0], (duration_min or 0) * 60, 1)
    def y(value: float) -> float:
        return 175 - (value - low) / max(high - low, 1) * 145

    bands = []
    for index, (name, lower, upper) in enumerate(zones[:5], 1):
        top = y(min(upper if upper is not None else high, high))
        bottom = y(max(lower, low))
        if bottom > top:
            bands.append(f'<rect x="45" y="{top:.1f}" width="660" height="{bottom - top:.1f}" '
                         f'fill="var(--zone-{index})" opacity="0.12"/>')
            bands.append(f'<text x="712" y="{(top + bottom) / 2 + 3:.1f}" class="axis-label">'
                         f'{escape(name)}</text>')
    path = " ".join(f"{45 + elapsed / max_time * 660:.1f},{y(hr):.1f}" for elapsed, hr in samples)
    peak = round(max(hr for _, hr in samples))
    summary = f"Heart rate over {round(max_time / 60)} minutes; peak {peak} bpm."
    grid = []
    for bpm in range(low, high + 1, 20):
        position = y(bpm)
        grid.append(f'<line x1="45" y1="{position:.1f}" x2="705" y2="{position:.1f}" '
                    'stroke="var(--line)" stroke-width="1"/>')
        grid.append(f'<text x="2" y="{position + 3:.1f}" class="axis-label">{bpm}</text>')
    tick_minutes = 5 if max_time < 1800 else 10
    for minute in range(0, int(max_time // 60) + 1, tick_minutes):
        x = 45 + minute * 60 / max_time * 660
        grid.append(f'<text x="{x:.1f}" y="205" text-anchor="middle" class="axis-label">'
                    f'{minute} min</text>')
    svg = ('<svg class="hr-chart" viewBox="0 0 800 215" role="img" '
           f'aria-label="{escape(summary)}"><title>{escape(summary)}</title>' + "".join(bands + grid) +
           f'<polyline points="{path}" fill="none" stroke="var(--heart)" stroke-width="2" '
           'vector-effect="non-scaling-stroke"/></svg>')
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
