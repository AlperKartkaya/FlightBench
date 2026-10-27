# Fixed-state decision diagnostics

These are diagnostics, **not landing trials or optimal-action accuracy**. The frozen v1
observation, criteria and actuator mapping are unchanged. No fallback flies for a model.

`tests/fixtures/decision-states-v1.json` contains seven synthetic variants of the easy initial
observation: growing right/left bank, lateral braking against position, ambiguous normal descent
below glidepath, exact thresholds, flare, and rollout. Their notes identify clear rules versus
ambiguity; they do not pretend every state has one uniquely optimal four-axis answer.
`tests/test_diagnostics.py` replays them through the real Jev, Codex and local adapter methods with
offline transports, checking identical canonical state and phase-specific questions/criteria.
This tests adapter fidelity, not the mocked models' capability.

## Recorded local experiment — 2026-10-07

One pinned Kev 0.8B v1.0 MLX server ran serially on Apple M1 Pro / 16 GiB, offline, with
`caffeinate -i`. No Jev/Codex calls or new flight campaign were made. Artifact files were rehashed
against `docs/local-model-runtime/kev-manifest.json`; the installed source revision matched.
Other desktop/agent work remained, so this is not an idle-machine latency certification.

The only intentional runtime intervention was `KEV_PREFIX_CACHE=0` versus `8`, with a fresh
server for each arm. Each arm ran all seven states twice in the same order. No warmup response
was discarded. The second pass repeats exact states; a live flight normally does **not**.
Date preprocessing and state truncation were disabled in both arms. The runtime refuses overflow;
missing response truncation fields are recorded as null, not claimed to be an affirmative audit.

| Cache capacity | First-pass median | Second-pass median | Responses |
| --- | ---: | ---: | ---: |
| 0 | 1,105.3 ms | 1,068.1 ms | 14 |
| 8 | 1,052.2 ms | 867.0 ms | 14 |

All 14 paired canonical ID vectors were unchanged between arms. Both arms selected aileron
`5` (-0.05) for the growing +9-degree right-bank fixture, opposite the frozen instruction's
left correction relative to trim -0.15. Cache-enabled repeated inputs were faster here but did
not repair that policy contradiction. This small fixed-order observation cannot establish a
population speedup, live-flight cache hit rate, or improved landing/realtime performance.
In particular, do not replace the existing campaign with these numbers.

Evidence retains every canonical state, question, returned probability vector, chosen ID,
command, latency and reported usage, plus model manifests and source identity:

- [Cache disabled](diagnostics/kev-cache-0.json), [runtime configuration](diagnostics/kev-cache-0-runtime.json)
- [Cache capacity eight](diagnostics/kev-cache-8.json), [runtime configuration](diagnostics/kev-cache-8-runtime.json)

Native tokenizer/rendered bytes and per-request cache-hit telemetry are not exposed by this
transport and are not fabricated. The source identities include concurrent validator/reporting
work in the dirty branch; this is a bounded diagnostic, not an independently reproduced release.
The runtime configurations, model/weight pins, states and decision semantics are the comparison
contract. Both temporary servers and the awake assertion were stopped after measurement.

## Reproduce on a trusted local runtime

Start the pinned Kev server from [runtime instructions](local-model-runtime/README.md), with
`HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 KEV_PREFIX_CACHE=0`; repeat with cache `8` after stopping
only that server. Keep the original evidence untouched. Use metadata copied from the Kev manifest
**without its historical `campaign` field**, since this is a different execution condition:

```sh
FLIGHTBENCH_LOCAL_METADATA=scratch/kev-diagnostic-metadata.json \
uv run python -m flightbench.diagnostics \
  --states tests/fixtures/decision-states-v1.json \
  --model kev-0.8b-v1.0 --endpoint http://127.0.0.1:11436 --repeats 2 \
  --conditions 'Record actual hardware, load, warmup, cache and host-awake conditions here' \
  --output scratch/kev-diagnostic-cache-0.json
```

The replay command never starts a server, downloads weights, calls hosted providers, or advances
physics. Existing output paths are refused. Other vetted native scoring runtimes can use the same
states and loopback endpoint contract. Model-specific serialization/precision/permutation studies
remain separate experiments, not silent edits to frozen v1 or claims of solved model capability.
