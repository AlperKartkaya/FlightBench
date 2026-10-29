# GPT-6.1 Terra lockstep campaign

Started 2026-10-28 via `examples/run_terra_campaign.py`, using the existing Codex
login and canonical V2 scoring configuration. No local models are rerun.

- Efforts: low, medium, high, xhigh (no max).
- Seeds: 42, 101, 202, serially; repeat the entire cohort once if no run succeeds.
- Selection: highest score across all completed attempts for each effort.
- Frozen source: `source.json` and `benchmark-source.tar.gz`.
- Trials: `leaderboard/campaigns/2026-10-28-terra-v2/<effort>/cohort-<n>/<seed>/`.
- Progress/logs: `scratch/terra-v2-2026-10-28/`.
- Background job: `com.flightbench.terra-v2-20261028` (launchd + caffeinate).

Each completed effort refreshes additional-results.json, both themed leaderboards,
the CSV and the original performance/API-cost plot. Partial cohorts are not
published. Infrastructure failures stop the runner without overwriting evidence;
they are not classified as failed landings. Retry policy is bounded to two cohorts.
