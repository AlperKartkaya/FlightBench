# October 26 realtime and Luna high extension

Directory date uses Europe/Istanbul; actual UTC timestamps are retained per flight.
Jev 1.13 and 1.14 each completed realtime seeds 42, 101, 202, serially with
apply-on-arrival at 2 Hz and scoring V2. Best scores: **0** and **66.719** respectively.
Jev 1.14 landed twice; Jev 1.13 had three runway excursions.

Selected realtime flights have one outstanding request at terminal cleanup. Recorded
token costs are lower bounds, not full totals; publication labels this uncertainty.

Luna high was first attempted with new seed 303, but HTTP 429 occurred before any
command was applied. Original seed42 was then repeated: one runway excursion,
one controller timeout after 138 commands, and a **successful landing scoring 78.507**.
The user selected that successful retry, cancelled the running seed101 retry,
and cancelled seed202 before it started. This is **not best-of-three attempts**.
The single selected replacement is in the combined Luna submission; original October 22
records remain unchanged. [Attempt history](attempt-history.json) preserves dates,
commands, outcomes and the explicit user cancellation. No complete final record exists
for the cancelled seed101 flight, so it has no invented score or cost.

Runtime/source archive, status, logs and resumable runner:
[`docs/local-model-runtime/scoring-v2-realtime-2026-10-26`](../../../docs/local-model-runtime/scoring-v2-realtime-2026-10-26/).
[Audited source transition](../../../docs/local-model-runtime/scoring-v2-realtime-2026-10-26/source-transition.md).
The runner does not introduce inter-call sleeps in lockstep.
