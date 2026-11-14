# Baseline wind regression check (2026-11-14)

Local deterministic JSBSim runs at the existing internal 2 Hz cadence. Both columns
include corrected wind initialization; only the baseline controller differs. No scoring,
scenario ranges, or published leaderboard entries were changed. The development
seeds informed the fix; the held-out seeds were checked only after selecting it.

| Group | Scenario | Mean score before → after | Safe landings before → after |
| --- | --- | --- | --- |
| development | easy | 99.2 → 99.2 | 10/10 → 10/10 |
| development | medium | 74.8 → 83.2 | 10/10 → 10/10 |
| development | hard | 27.5 → 43.7 | 6/10 → 8/10 |
| held-out | easy | 99.2 → 99.2 | 10/10 → 10/10 |
| held-out | medium | 78.0 → 83.9 | 10/10 → 10/10 |
| held-out | hard | 43.1 → 61.0 | 9/10 → 10/10 |

Development seeds: 42, 101, 202, 303, 404, 40, 41, 43, 44, 45.

Held-out seeds: 7, 17, 27, 37, 47, 57, 67, 77, 87, 97.

The fix steers by ground drift while allowing a crosswind crab, avoids reducing
target airspeed in tailwinds, and retains power / reduces sink before the runway.
Easy remains unchanged. Hard still fails on development seeds 101 (short landing)
and 40 (heading at contact); this remains a small baseline, not a robust autopilot.

Regression gates run in both `tests/test_controllers.py` and
`frontend/public/wasm/engine.test.js`; native/WASM parity is checked with
`uv run python examples/compare_wasm.py`. To reproduce the table, reset
`FixedWingLandingEnv(scenario)` with each listed seed, repeatedly call
`env.step(BaselineController().decide(observation))` until done, and average
`info["result"]["quality"]` (including failed runs at zero). The same loop before
the controller change gives the before column. These checks do not establish
performance on all seeds, mobile-device throughput, or provider behavior.
