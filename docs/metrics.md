# Metrics and Units

Code computes every metric. LLMs describe the results; they do not calculate
Recovery, session load or the training decision. Missing values remain missing.

## Units

Activities store distance in kilometres, duration in minutes and pace in minutes
per kilometre. Garmin raw units are normalized on import; laps and streams have
their own documented adapters. Do not format raw Garmin seconds as stored minutes.
HR is bpm, HRV is ms, sleep is hours internally. Displays use runner-friendly units.

## Recovery

Readiness v1.2 is displayed as Recovery. HRV uses a three-night mean with at least
two observations against the preceding twenty-eight-day baseline:
`clamp(70 + (recent_hrv / usual_hrv - 1) * 150, 0, 100)`.
Resting HR uses `clamp(70 - (rhr - usual_7d_rhr) * 7, 0, 100)`.
Sleep is duration divided by the configured goal; load is scored by existing
load-score rules. Available components are weight-normalized (HRV 35, sleep 25,
resting HR 20, load 20); at least two and HRV or resting HR are required.
Illness signals use last night's HRV, not the three-night mean. They are not a diagnosis.
Charts leave missing health days as gaps; decisions may use a marked older day.

## Session Load and Effort

HR-based TRIMP is the base session load. Missing HR may use the existing own-sport
median imputation; missing evidence is not converted to zero. sRPE is rating
times duration in minutes. There is no default conversion factor: fewer than
five rated HR-backed sessions means no sRPE contribution anywhere.

After calibration, k is the median TRIMP/sRPE. A team sport or gym also needs at
least three rated HR-backed sessions before using its common scale. Rated load
is `max(TRIMP, k * sRPE)`; unrated load uses the sport's median final-load/TRIMP
multiplier, so acute/chronic windows and the planner use the same scale. Running
retains TRIMP. Ratings still inform hard-session rules before calibration.

## Usual Week and Weekly Limit

Use `coach.load_model`: median load of the latest eight complete weeks containing
training. Empty weeks, walking, excluded activities and non-training mobility
are excluded. Weeks with missing load cannot provide a complete reference.
Fewer than four qualifying weeks means "baseline still building", with no weekly
cap. Otherwise the visible limit is 110% of usual. Expected walking is informational
only and excluded from both reference and planned training totals.

Planned load uses the athlete's own median load per minute for sport and intent,
falling back to the sport median. Fixed commitments and protected habits stay;
the flexible plan and daily suggestions must respect safety rules. The internal
acute/chronic ratio is not a user-facing safety rule. Constants are owner-tuned.
