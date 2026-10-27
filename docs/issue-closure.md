# Issue #1 and #2 closure evidence

Reviewed against the live GitHub issue bodies on 2026-10-20. This document proposes closure
through the branch's PR; it does not claim that the PR was merged, CI ran remotely, or the issues
were closed. Successful aircraft landings are not either issue's acceptance criterion.

## Issue #1 — canonical shared action space

| Acceptance criterion | Implemented evidence |
| --- | --- |
| Jev and Codex/LLMs select identical discrete actions | `protocol.py:SharedActionDecision`, `command_from_action_ids`; adapters in `controllers.py`, `local.py`, `loading.py` |
| Shared control hierarchy and provider-independent definitions | `protocol.py` owns instructions, criteria, commands and phase rules; `build_llm_control_prompt` exposes the same information |
| Official AI controllers cannot invent continuous outputs | Strict string-ID validation; common mapping; evidence validator checks applied command against recorded IDs |
| Explicit version in every benchmark record | `protocol_metadata`, `runs.py:effective_config`, submission `flightbench` identity |
| Regression/snapshot protection | `tests/test_protocol.py`, `tests/test_single_jev.py`, `tests/test_controllers.py`, `tests/test_local_and_loading.py` |
| New-model contribution rules documented | `docs/controllers.md`, README and categorical example |

The source version does not determine model quality. No provider-specific stabilization or
handcrafted flight fallback was inserted to improve results.

## Issue #2 — external controllers and community leaderboard

| Acceptance criterion | Implemented evidence |
| --- | --- |
| Public extension interface and examples | `Controller.decide`, documented metadata, `examples/controllers/` |
| Standard CLI evaluates one controller in either/both modes and multiple seeds | `flightbench eval`, trusted `module:Class` / `file.py:Class` loader |
| Versioned, portable submission artifacts | `leaderboard/schema/submission-v1.schema.json`, strict Pydantic schema, compressed full episode records and SHA-256 binding |
| Contributors submit entries by PR | `.github/PULL_REQUEST_TEMPLATE/`, `docs/controllers.md`, `leaderboard/submissions/` |
| CI validates without paid provider execution | `.github/workflows/validate-leaderboard.yml`; no provider secrets, offline tests; registry authority comes from the base branch |
| Data-generated leaderboard and figures | `flightbench leaderboard build`; dedicated cohort report produces Markdown/JSON/SVG/PNG |
| Both modes represented without architecture-specific competitions | Same action protocol and renderer; group only by recorded source/experiment/timing conditions |
| Every result has enough provenance | Exact model/runtime pins, configuration, source snapshots, hashes, raw commands and application counters |

Tests also cover built-in Jev/Codex exports, long external-controller paths, evaluation-claim
mutation, raw counter inconsistencies, and timing-policy mismatches. Verification status remains
community/self-reported; hashes are integrity checks, not independent reproduction certificates.

## Avoiding false model-failure attribution

- Native adapters submit complete canonical state and questions; known truncation signals fail closed.
- Canonical IDs map to the same bounded `ControlCommand` for every provider.
- `environment.py` writes all four commands to JSBSim before advancing physics. Its shared ground
  rollout handling idles throttle and adds symmetric brakes; this is not model-specific assistance.
- Raw records distinguish completed responses from applied commands and terminal outstanding work.
- The new apply-on-arrival experiment applies valid returned commands without rejecting them for
  age. Original evidence is retained, not relabeled as equivalent to this experiment.
- Lockstep separates decision quality from request delay; realtime reports full-system behavior.
  Neither one seed nor unlabeled fixed-state probes establish general decision accuracy.

See the [PR validation record](pr-readiness.md). Raw dated runtime evidence remains under
`docs/local-model-runtime/` and full episode records remain under `leaderboard/submissions/`.
