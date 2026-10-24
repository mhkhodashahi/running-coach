"""Bounded, self-contained SVG charts for the Today view."""

from html import escape

from web.formatting import short_date

SPARKLINE_COLORS = {"heart": "var(--heart)", "sleep": "var(--sleep)", "muted": "var(--ink-muted)"}


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


def load_bars(values: list[tuple[str, float | None]], average: float | None, last_sync: str) -> str:
    maximum = max([value for _, value in values if value is not None] + [average or 0, 1])
    bars = []
    for index, (day, value) in enumerate(values[-14:]):
        x = index * 32 + 6
        if value is None:
            bars.append(f'<rect x="{x}" y="105" width="19" height="7" fill="var(--line)">'
                        f'<title>{escape(short_date(day))}: No data; {escape(last_sync)}</title></rect>'
                        f'<text x="{x + 9}" y="135" text-anchor="middle" class="axis-label">{escape(day[-2:])}</text>')
            continue
        height = max(1, round(value / maximum * 104)) if value else 0
        bars.append(
            f'<rect x="{x}" y="{112 - height}" width="19" height="{height}" rx="3" '
            f'fill="var(--load)"><title>{escape(short_date(day))}: {value:.1f} load</title></rect>'
            f'<text x="{x + 9}" y="135" text-anchor="middle" class="axis-label">{escape(day[-2:])}</text>'
        )
    line = ""
    if average is not None:
        y = 112 - average / maximum * 104
        line = f'<line x1="0" y1="{y:.1f}" x2="448" y2="{y:.1f}" stroke="var(--ink-muted)" stroke-dasharray="4 4"/>'
    return '<svg class="load-chart" viewBox="0 0 448 144" role="img" aria-label="Training load for the last fourteen days">' + line + "".join(bars) + "</svg>"


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
