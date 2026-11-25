---
name: flightbench-colab-local-models
description: Run and verify FlightBench benchmarks for self-hosted decision models on Google Colab GPUs. Use for GPU/model setup, serial lockstep and realtime campaigns, reconnecting to a notebook, collecting evidence, or publishing verified results. Not for hosted Decision APIs or changing the flight policy or scoring.
---

# FlightBench local models on Colab

Use the user's approved models, order, hardware and flight count. “Local” means
the model and simulator run on the same Colab VM; there is no hosted model API and
no tunnel hop in measured inference latency. Start with evidence from any existing
campaign before spending more GPU time. Do not swap checkpoints, precision or
backends silently.

## Notebook and control

- Copy the complete [Colab cell](../../../scripts/colab_bridge.py) into a notebook.
  Set `WORK_DIR`, a dedicated `EXPORT_DIR` containing only shareable outputs, and
  `JOBS`, a map of names to exact argument lists for trusted runners. Prepare the
  checkout and environments in the notebook before starting jobs. Keep every job
  in the foreground of its own process: the bridge runs one job at a time and
  does not treat the exit of a background launcher as campaign completion.
- Share the printed URL/token/protocol privately; never commit them. Protocol 2
  uses `Authorization: Bearer <token>` on every request. Use `GET /health`,
  `GET /status`, empty `POST /jobs/<name>/start`, and
  `GET /files/<relative-path>`. Fetch named outputs from the dedicated folder.
  There is no arbitrary shell endpoint or remote file upload. Keep the model
  server on localhost; the temporary [Quick Tunnel](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)
  fronts only the bridge and is not a production endpoint.
- A tunnel disconnect does not prove a run interrupted. Rerunning the cell
  rotates the URL and token without stopping the jobs it started on this VM.
  Check process and campaign status before relaunching. After VM replacement,
  rehydrate from downloaded evidence and configure only the missing work.
  Use `stop_colab_bridge()` to close the tunnel when done.

## Model and run

1. Check GPU model/free VRAM with `nvidia-smi`. Pin the weight revision, tokenizer
   and native decision runtime; record GPU, backend, precision and dependency
   versions. Separate the simulator and vendor Python environments. Prefetch
   weights on disk if useful, but load one GPU model at a time. Explicitly stop
   its server and check GPU memory is released before loading the next.
2. Run the vendor's native categorical readout behind a loopback
   `/v1/systemone` adapter. Use
   [GlideController](../../../examples/controllers/glide.py) as the logging
   adapter example. Reuse the canonical state and phase questions, with no
   chat fallback or input truncation. Check served identity/revision, then smoke
   test real observations, returned action IDs and latency before scoring.
   For varied backend examples, see the
   [runtime manifests](../../../docs/local-model-runtime/README.md).
3. Use `flightbench.benchmark.run_episode` with scoring V2, Easy, 2 Hz and 1×
   for this leaderboard's local cohort, unless the user specifies a different
   experiment. The default local cohort is one lockstep flight (seed 42,
   `decision_schedule="fixed"`) and ten realtime flights
   (42, 101, 202, 303, 404, 505, 606, 707, 808, 909,
   `decision_schedule="continuous"`, `realtime_response_policy="apply-on-arrival"`).
   These are repeats of the same calm-air setup, not different weather conditions.
   Do not mix this realtime policy with hosted fixed-rate/discard-stale cohorts.
   Equal scores alone do not establish determinism.

## Evidence and resume

- Record source and adapter hashes, runtime metadata, a provider request/response
  JSONL and a UUID-named episode per flight. Keep benchmark status separate from
  bridge exit status. Sync verified artifacts incrementally; do not wait for
  all models before downloading results.
- In [the campaign runner](../../../examples/run_ten_trial_campaign.py), reuse
  `verify_episode` for input/action mapping and offline physics replay. Also
  verify the provider's embedded state, frozen questions, valid answers and
  input-integrity fields against the journal. Account for a response drained
  after realtime termination without treating it as a flown action. Store the
  replay and SHA-256 of the compressed episode alongside the verified seed
  ledger. A blocked or interrupted attempt is not a scored failure.
- Resume only missing seeds after confirming the original runner is stopped and
  model revision, source and timing match. Archive partial attempts. Never retry
  a valid flight just to improve its score. A prior A100 runner may be available
  locally at `docs/evaluations/2026-11-25-a100-lockstep/local_a100.py`; it and its
  campaign journals are local artifacts, not clean-checkout prerequisites.
- For README output, use the repo's trial visual exporter if present. Include
  complete verified cohorts in the data; show a realtime row only if it landed
  successfully. Best/average are success-only. Separate hardware time from
  API fees, and do not infer publisher-hosted parity from Colab results.
