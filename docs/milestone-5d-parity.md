# Milestone 5d parity and retirement decisions

| Streamlit page or action | New UI | Owner decision |
| --- | --- | --- |
| Today: daily decision, override, recovery, load, plan, effort | `/` | PORTED |
| Today: legacy fitness and prediction charts | Partial `/trends` | LATER, through Goal and Running items below |
| Training: browse, filter, open activity | `/activities`, `/activities/{id}` | PORTED |
| Training: weekly kilometres, long-run progression | Partial `/trends` | LATER, Trends Running |
| Health: HRV, resting HR, sleep, Body Battery | `/`, `/trends` | PORTED |
| Health: sleep-vs-performance correlation | Missing | DROP |
| Goal Readiness: projection and interpretation | Missing | LATER, Trends Goal |
| Goal Readiness: distance/pace scenario controls | Missing | DROP |
| Coach: chat and follow-ups | `/coach` | PORTED |
| Coach: digest generation, optional Telegram send, preview and decision history | Missing | MILESTONE 6 |
| Goals: list, create, edit, activate and archive | `/settings` | PORT NOW |
| Goals: digest and Telegram delivery history | Missing | MILESTONE 6 |
| Plan: commitments, habits, manual sessions, proposals and undo | `/plan` | PORTED |
| Key Sessions: detected quality sessions, types and volume | Missing | LATER, Quality sessions filter on `/activities` |
| Activity Detail: statistics, laps, HR zones, opinion, rating, similar sessions and coach question | `/activities/{id}` | PORTED |
| Activity Detail: map and export | Missing | DROP for now |
| Activity Detail: prediction/context charts | Missing | LATER, Trends Goal and Running |
| Shared sidebar: profile and max HR edit | `/settings` | PORT NOW |
| Shared sidebar: active goal view and management | `/settings` | PORT NOW |
| Shared sidebar: Garmin sync status and manual sync | `/settings` | PORT NOW |
| Shared sidebar: activity and health CSV upload | `/settings` | PORT NOW |
| Nutrition and body scans | No Streamlit page in this checkout | KEEP DATA ONLY; no UI, tables untouched |

The legacy Streamlit app remains runnable through the optional extra until its removal before the first public release. A LATER decision is not a claim of feature parity.
