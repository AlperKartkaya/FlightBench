# Von local runtime

This runtime is isolated under `scratch/von-runtime`; it does not modify FlightBench's Python environment.

## Pinned provenance

- Official source: `https://github.com/wfzyx/von.git`
- Git revision: `a72b19c25bd3a90e5f7133999155a9213f61994a`
- Built package: `von-sdk 1.3.7` (local wheel hash in `scratch/von-runtime/wheel.sha256`)
- Official model: `wfzyx/von`
- Hugging Face revision: `498ceba33390b32cfefaab6422ec380318ba9b99`
- Served model identity: `von-1.3.0` (Von 1.3 engine using the published 1.2 weights)
- License: Apache-2.0

Only `config.json`, `tokenizer.json`, `tokenizer_config.json`, `model.safetensors`,
`option_marker.pt`, and `marker_calibration.json` are downloaded. `manifest.json` records their
sizes and SHA-256 digests.

## Security and benchmark isolation

The backbone is loaded from local safetensors. The official runtime loads `option_marker.pt`
with `torch.load(..., weights_only=True)` and strict state-dict validation. It never enables
`trust_remote_code`, never loads secrets, and runs Hugging Face/Transformers offline after the
pinned download. The HTTP server binds only to `127.0.0.1:11437`.

`serve.sh` forces plain CPU inference with two-thread ceilings, refuses context overflow, and
disables chain-of-options. Thus benchmark decisions come only from the published model forward
pass, without truncation or deterministic handcrafted chain computation.

## Start and verify

```bash
scratch/von-runtime/serve.sh > scratch/von-runtime/logs/server.log 2>&1
curl -fsS http://127.0.0.1:11437/health
curl -fsS -H 'Content-Type: application/json' \
  --data @scratch/von-runtime/canonical-request.json \
  http://127.0.0.1:11437/v1/systemone
```

The smoke request contains the four frozen FlightBench v1 categorical actuator questions.

## Verified runtime

The pinned CPU server returned HTTP 200 from `/v1/systemone` with model
`von-1.3.0`, all four actuator answers, 2,338 input tokens, four output decisions, and no
truncation. Cold-load smoke latency was 7.618 s; the immediately repeated byte-identical
response took 6.135 s. An oversized-state probe returned HTTP 422 with the configured
"refusing rather than truncating" error. Exact request/response hashes and selected IDs are in
`scratch/von-runtime/manifest.json`.
