# Streamlit Retirement Decisions

This is the owner's retirement decision record, not a claim of complete parity.
Streamlit was retired after Settings was available and its source was subsequently
removed. Existing nutrition and body-scan data remain untouched.

| Previous capability | Current surface | Owner decision |
| --- | --- | --- |
| Profile, CSV activity/health import, Garmin sync | `/settings` | Port now |
| Goals and races: create, edit, active/archive | `/settings` | Port now |
| Activities, activity detail, reviews, effort | `/activities`, `/activities/{id}` | Port |
| Daily decision and weekly proposals | `/`, `/plan` | Port |
| Recovery and load charts | `/trends`, `/insights/dashboard` | Port |
| Coach conversation | `/coach` | Port |
| Goal readiness/prediction card | Not a complete replacement | Later: Trends Goal card |
| Weekly running km and long-run progression | Dashboard best efforts is not equivalent | Later: Trends Running |
| Key sessions | No equivalent quality-session filter | Later: Activities filter |
| Digest controls/history | Settings Messages, Coach History, worker | Milestone 6 |
| Sleep-performance correlation | Not ported | Drop |
| Distance/pace scenario tool | Not ported | Drop |
| Route map/export | Running replay later added; export absent | Export remains dropped |
| Legacy Today prediction charts | Not ported | Covered by later running/goal cards |
| Nutrition and body scans | No UI | Keep data only |
