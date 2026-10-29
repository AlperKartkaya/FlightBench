# Additional realtime flights — October 26, 2026

Serial flights using scoring V2, 2 Hz decisions, wall-time simulation and
apply-on-arrival responses. UTC timestamps and frozen source are retained in
[the runtime archive](../../../docs/local-model-runtime/jev113-repeat2-luna-realtime-2026-10-26/).

| Model | Effort | Seed | Score | Outcome | Applied commands |
| --- | --- | ---: | ---: | --- | ---: |
| Jev 1.13 | — | 42 | 0 | runway_excursion | 114 |
| Jev 1.13 | — | 101 | 0 | runway_excursion | 132 |
| Jev 1.13 | — | 202 | 38.577 | landed | 130 |
| GPT-6 Luna | low | 42 | 0 | runway_excursion | 11 |

The active Jev 1.13 realtime row is replaced by the best of this new three-flight
batch (seed202), not the best across all historical attempts. Its complete
reported usage costs $0.014681058; all 130 requests completed, with no API errors.
Previous cohorts remain archived unchanged. Luna low is a single exploratory
realtime flight, not included in the main best-of-three comparison.

The first process failed before provider access because optional environment
packages were missing. Its startup evidence is retained; the existing frozen
lockfile extras were restored before restarting. This is not a model failure.
