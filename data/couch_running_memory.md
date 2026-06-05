# Coach Running Memory

Last updated: 2026-06-04 from db/running_coach.db

## Persistent cues
- Athlete profile in DB: Mohammad, 39, male, 89.0 kg, 174.0 cm, max HR 184, usually 4 training days/week.
- Active goal in DB is My 10K PB: 10.0 km in 50.5 min, target date 2026-05-31, priority A, still marked active.
- Latest 10K prediction snapshot after 2026-05-31 run is 60.5 min with 20.4 confidence, so coach should treat sub-50:30 readiness as behind target and low certainty.
- Full run history has 76 runs, 523.1 km total, average pace 6.07 min/km, average HR 132 bpm, longest run 42.3 km.
- Recent 28-day run load through 2026-05-31: 17 runs, 95.1 km, average run 5.6 km, average pace 6.06 min/km, average HR 133.7, longest recent run 8.6 km.
- Latest 7-day run load through 2026-05-31: 5 runs, 26.2 km, average pace 6.08 min/km, average HR 136.6, longest run 7.8 km.
- Main coaching pattern from stored activity opinions: easy runs are improving but often drift into steady effort late, with HR drift or mild pace fade.
- Watch for medium-hard leakage: short runs on 2026-05-27, 2026-05-29, and 2026-05-30 averaged around 140 bpm and were not truly easy despite modest distance.
- Quality work needs sharper purpose: 2026-05-30 Stride Repeats became mostly steady-to-threshold instead of a crisp speed session.
- Recovery can swing sharply: last 14 health rows averaged sleep score 76.7, but 2026-05-31 had sleep score 40, 5.2 h sleep, body battery 13, stress 39, HRV 38, and recovery time 16.6 h.

## Recent coaching entries
- 2026-06-01 recovery row: sleep score 80, 6.46 h sleep, resting HR 47, HRV 65, stress 13, body battery 74, recovery time 10.4 h. Use this as latest recovery context if no newer health row exists.
- 2026-05-31 Dusseldorf - Goal Pace Repeats: 7.76 km in 48.83 min at 6.30 min/km, avg HR 139, max HR 152, cadence 168.5. Latest prediction worsened to 60.5 min for 10K with 20.4 confidence.
- 2026-05-30 Stride Repeats coach opinion: decent session but not a sharp VO2max/speed workout; mostly steady-to-threshold with brief Zone 5 touches. Recommendation memory: keep speed days crisp and avoid turning them into vague moderate progressions.
- 2026-05-29 Dusseldorf - Easy Run: 6.02 km at 6.21 min/km with avg HR 140 and max HR 170. Treat as evidence that an easy label can still become too hard.
- 2026-05-27 daily coaching decision: mixed day with strength, walking, 6.4 km total running, and main run 5.3 km at 6.38 min/km with 124 bpm avg HR. Coach judged it disciplined enough but not specific enough for the 10K PB target.
- 2026-05-27 Dusseldorf - Easy Run coach opinion: properly controlled easy/aerobic run at 124 bpm average HR, but second half drifted toward steady effort. Recommendation memory: reward early restraint, then ask for more stable late-run control.
- 2026-05-27 Dusseldorf Running coach opinion: 1.16 km short run became upper Zone 3/Zone 4 heavy, too short and too intense to build base. Pattern memory: small runs can become medium-hard efforts.
- 2026-05-23 Easy Run coach opinion: legitimate easy aerobic run with 74.1% Zone 2 and avg HR 124, but still mildly uneven with some Zone 3 drift. Use as positive example of the easy-run discipline to reinforce.
