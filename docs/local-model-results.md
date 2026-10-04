# Local decision-model campaign results

Completed **50 actual episodes**: five models × five seeds × two modes. Seeds: `42,101,202,303,404`. Each model ran independently for every seed; no trajectory was reused. No controller errors/timeouts occurred. No new Jev or Codex evaluations were performed.

## Outcome

| Model | Lockstep landings | Lockstep median score | Lockstep outcome | Realtime landings | Realtime median score | Realtime outcome | Evidence |
| --- | ---: | ---: | --- | ---: | ---: | --- | --- |
| Decider 2B v11 Q4_K_M | 0/5 | 0.000 | out_of_bounds (5) | 0/5 | 0.000 | out_of_bounds (5) | [Submission](../leaderboard/submissions/decider-2b-v11-q4/submission.json) |
| Kev 0.8B v1.0 | 0/5 | 0.000 | nose_first_contact (5) | 0/5 | 0.000 | out_of_bounds (5) | [Submission](../leaderboard/submissions/kev-0.8b-v1/submission.json) |
| Bespoke Nimble 9B Q4_K_M | 0/5 | 23.414 | runway_excursion (5) | 0/5 | 0.000 | out_of_bounds (5) | [Submission](../leaderboard/submissions/nimble-9b-q4/submission.json) |
| OpenThai-SystemOne v0.3 Q8 | 0/5 | 0.000 | nose_first_contact (5) | 0/5 | 0.000 | nose_first_contact (5) | [Submission](../leaderboard/submissions/openthai-v0.3-q8/submission.json) |
| Von 1.3 | 0/5 | 0.000 | crash (5) | 0/5 | 0.000 | out_of_bounds (5) | [Submission](../leaderboard/submissions/von-1.3/submission.json) |

None of the five local models successfully landed in this campaign. Nimble obtained nonzero lockstep quality but left the runway; this is a failed trial, not a landing.

## Graphs

[Lockstep latency](../leaderboard/lockstep-latency-score.svg) · [Lockstep provider cost](../leaderboard/lockstep-cost-score.svg) · [Realtime latency](../leaderboard/realtime-latency-score.svg) · [Realtime provider cost](../leaderboard/realtime-cost-score.svg) · [Mode delta](../leaderboard/mode-delta.svg) · [Best-of](../leaderboard/best-of.svg)

Best-of includes existing Jev and three Codex models as **pre-v1 references**, not current-protocol participants. It prefers a successful landing when one exists; otherwise it explicitly shows the best completed failed trial. Missing historical mode data is never inferred.

## Measurement boundary

- Aircraft: existing JSBSim C172x, 120 Hz physics, `easy` scenario; all models used the same frozen v1 observation, action IDs, criteria and phase semantics.
- Decision rate: 2 Hz; realtime scale 1.0. Lockstep waits for inference. Realtime continues physics and discards stale results according to the existing benchmark rules.
- Five easy seeds have identical physical initial conditions. These are repeated executions, not five different weather/initialization conditions.
- Hardware: Apple M1 Pro, 16 GB unified memory. The model jobs used a two-at-a-time schedule (Kev+Decider, Von+OpenThai, then Nimble). Latencies include shared-device contention; model servers used one episode job each.
- The long Nimble campaign crossed host sleep/suspend intervals. Calendar elapsed time is not inference throughput. Recorded monotonic call latencies remain the measurement evidence; no latency samples were removed or corrected. These results are not isolated-hardware performance claims.
- Local provider fee is zero; hardware, energy, downloads and development costs are excluded. Historical API-price estimates retain their original methodology/pricing date and are not Codex-account charges.
- All 50 records share source hash `sha256:16e73c3adef4646edfeee6e0b68a2366eb43e1ffe8fd93c992ffe9f721a460b8`. The [source snapshot and runtime manifests](local-model-runtime/README.md) retain the actual pre-validation-hardening code and pinned artifacts.
- All five submissions remain **community / self-reported**. Integrity/consistency validation is not independent reproduction or a verified performance certificate.
- This is a practical protocol-compatible shortlist, not a proven global popularity top five. OpenThai is a low-adoption replacement for Laya, whose 48-token criterion limit cannot accept the frozen FlightBench questions. See [primary sources, licenses and selection caveats](local-model-sources.md).
