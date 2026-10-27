# Benchmark evidence archive

Published comparisons are in the [project README](../README.md). Historical submissions and
`leaderboard.json` are retained as raw evidence, not a current model ranking.

Open-model campaign dates and runtime paths: [archive index](../docs/local-model-runtime/archive-index.json).
New scoring-V2 campaign: `campaigns/2026-10-22-scoring-v2/`.

Validate without executing any contributed controller:
```sh
uv run flightbench leaderboard validate leaderboard/submissions/*/submission.json
```

The generic renderer remains available for local previews; it does not overwrite the curated README:
```sh
uv run flightbench leaderboard build --output-dir scratch/leaderboard-preview
```
