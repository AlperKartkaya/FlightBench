# Jev 1.13 repeat — October 26

The user requested a fresh three-flight repeat in both lockstep and realtime.
Both modes use seeds 42, 101 and 202, scoring V2, the canonical easy scenario,
2 Hz decisions and apply-on-arrival for realtime. Flights ran serially after
the Luna campaign was explicitly stopped; they did not overlap another model.
UTC flight timestamps are retained; the directory date uses Europe/Istanbul.

| Mode | Seed42 | Seed101 | Seed202 | Selected |
| --- | ---: | ---: | ---: | ---: |
| Lockstep | 24.406 (landed) | 78.426 (landed) | 40.918 (landed) | 78.426 |
| Realtime | 0 (runway excursion) | 0 (runway excursion) | 0 (runway excursion) | 0, seed42 tie-break |

The lockstep group remains active. The realtime group was subsequently replaced
by the [second realtime repeat](../2026-10-26-realtime-repeat2/). At collection time,
these groups replaced the previous Jev 1.13 rows;
previous cohorts remain unchanged in their dated directories. Best-of-three means
best within this new batch, not best across every archived attempt.
The selected realtime cost is a lower bound because terminal outstanding usage
is unknown; the publication does not fabricate a complete total.

[Runtime and frozen source](../../../docs/local-model-runtime/jev113-repeat-2026-10-26/).
[Audited source transition](../../../docs/local-model-runtime/scoring-v2-realtime-2026-10-26/source-transition.md).
