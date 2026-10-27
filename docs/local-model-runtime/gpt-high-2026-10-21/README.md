# GPT 6.1 Sol high-effort lockstep trial

One actual episode: easy, seed 42, 2 Hz, lockstep, 1x, 120-second request timeout.
Result: **landed, quality 61.239**. All 143 decisions completed and were applied;
no errors, outstanding requests, fallback or stability hold. Simulation duration 71.3 s.
Mean response latency 5909.539 ms; median 5193.995 ms.

`run.py` uses the standard evaluator and binds the production Codex controller's
`reasoning_effort` constructor argument to `high`. The default remains `low`.
All recorded decisions were checked for `reasoning_effort=high`. Canonical state,
prompts, action mapping, physics and scoring are unchanged. The archived runner and
benchmark source document this binding; metadata records the runner SHA-256.

[Submission and full episode evidence](../../../leaderboard/submissions/gpt-6-1-sol-high-20261021/submission.json)
· [Table and SVG/PNG figures](../../evaluations/gpt-high-2026-10-21/README.md)

The source changed to expose reasoning effort, so this is a separate source cohort.
One successful flight is not an estimated success rate. The previous low-effort
trial timed out and cannot establish a controlled low-versus-high quality comparison.
No provider cost estimate is asserted for subscription inference.
