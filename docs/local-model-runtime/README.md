# Campaign runtime manifests

The commands below describe the original five-seed campaign. Later evidence is retained under
date-stamped directories and mapped to its submission paths in
[`archive-index.json`](archive-index.json).

These manifests pin the downloaded weights, official inference code and isolated dependencies.
Weight files and environments stay outside Git under `scratch/`; the benchmark submission includes
full compressed episode evidence, not redistributed model binaries.

## Kev

The campaign used source `84847f0a883d900f7de5b7a57eaa341ca7f9a6b4`, weights
`jaredpalmer/kev-0.8b@bf75a6a8848ea6960ff2ed108d9ed44c2941174f`, the pinned base revision
in `kev-manifest.json`, and the official MLX server. PyTorch 2.8.0 defaults to
`weights_only=True` for the checkpoint head; safetensors supplies the backbone/adapter.

```sh
KEV_BACKEND=mlx KEV_DATE_FACTS=0 KEV_TRUNCATE_STATES=0 \
  scratch/kev-runtime/.venv/bin/python -m kev.serve \
  --run jaredpalmer/kev-0.8b@bf75a6a8848ea6960ff2ed108d9ed44c2941174f \
  --host 127.0.0.1 --port 11436
```

## Decider

The official GGUF engine has no HTTP server. The small wrapper uses its unmodified
`Decider.system_one` with independent questions, native per-type temperatures, one sequence per
decode, an 8,192-token context, Metal offload and two CPU threads. It refuses overlong state/rows;
no question, criterion or observation is shortened.

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 OMP_NUM_THREADS=2 \
  scratch/decider-runtime/.venv/bin/python examples/local/decider_gguf_server.py \
  scratch/decider-runtime/model
```

The model checkpoint and tokenizer are the pinned official files in `decider-manifest.json`.
The server binds only to `127.0.0.1:11439`. Building the Metal dependency on this machine required
`CMAKE_OSX_SYSROOT` pointing to the installed Xcode 26.5 SDK, not a system toolchain upgrade.

## Evaluation

Each model uses the standard `flightbench eval` CLI, one episode at a time per server. Set
`FLIGHTBENCH_SYSTEMONE_URL` and `FLIGHTBENCH_LOCAL_METADATA` to its endpoint/manifest and pass
`--controller systemone --model <served-model> --metadata <manifest>`.
All models use `--decision-hz 2 --time-scale 1.0 --modes lockstep,realtime
--seeds 42,101,202,303,404 --jobs 1`.

At most two benchmark model jobs share this Apple M1 Pro / 16 GB machine. Measured latency and
realtime performance therefore include shared-device contention, not isolated peak throughput.
The easy scenario has the same physical initialization for every seed; the five seeds provide
repeated execution, not five weather conditions. Local provider fees exclude hardware/electricity.

## Ollama and Von

Nimble and OpenThai use the dedicated official Ollama 0.35.0 binary on port 11435; the existing
system Ollama installation is unchanged. Its release archive SHA-256 is
`2608dbb0a0f0136a198db9d48b4f74ece55f452314a39452fca35b7cf20c2589`.
Use `SystemOneController`, including for OpenThai: its registry capability list omits `decision`,
but its publisher-trained `/v1/systemone` scoring artifact was verified directly. No chat fallback
was used in this campaign. Pinned manifests describe both quantized artifacts and their runtime.

```sh
OLLAMA_HOST=127.0.0.1:11435 OLLAMA_NO_CLOUD=1 OLLAMA_NUM_PARALLEL=1 \
  OLLAMA_MAX_LOADED_MODELS=2 OLLAMA_CONTEXT_LENGTH=8192 \
  OLLAMA_KV_CACHE_TYPE=q8_0 OLLAMA_FLASH_ATTENTION=1 \
  scratch/ollama-0.35.0/ollama serve

# In another terminal, after the server is ready:
FLIGHTBENCH_SYSTEMONE_URL=http://127.0.0.1:11435 \
  FLIGHTBENCH_LOCAL_METADATA=docs/local-model-runtime/nimble-manifest.json \
  uv run flightbench eval --controller systemone --model nimble:9b-q4_K_M \
  --metadata docs/local-model-runtime/nimble-manifest.json \
  --modes lockstep,realtime --seeds 42,101,202,303,404 --jobs 1 \
  --decision-hz 2 --time-scale 1.0 --timeout 120 \
  --output-dir scratch/nimble-reproduction
```

For OpenThai, substitute its manifest and `iapp/openthai-systemone:0.8b-q8_0` tag.
These commands are reproduction instructions; the completed campaign is not rerun when building
the leaderboard. The campaign-owned servers were stopped after all 50 episodes finished; their
downloaded weights and isolated environments remain available.

Von uses the offline two-thread CPU launcher described in [Von runtime](../von-runtime.md).
Chains and truncation are disabled. The pairing schedule was Kev+Decider, then Von+OpenThai,
then Nimble while Von finished; remaining Nimble episodes ran without another benchmark job.
One incomplete Kev warmup trial was stopped before its first episode record when the code freeze
changed. It is not a completed matrix episode.

`benchmark-source-pre-hardening.tar.gz` preserves every file used in the actual source fingerprint.
The 50 episodes record that source hash and the original Git commit plus dirty-worktree flag.
Later submission-validator hardening does not change aircraft physics, prompts, model inference,
action IDs, scoring, or the original recorded source identity.

## Minimal retained evidence and offline rescoring

Each full episode is retained **once** as `.json.gz`, referenced by a combined
`submission.json`. Compression is the original run log, not an additional log of
that log: it contains config, timestamps, observations, every applied command and
its simulation time, provider usage/errors, outcome and scoring evidence. Keep
these records, their manifests and frozen measurement source. Small model manifests
pin weights/runtime; unique interrupted-attempt evidence remains distinguishable
from completed poor landings.

Redundant per-trial manifests, successful-evaluation stdout, identical historical
runner copies and 44 metadata sidecars were removed from the publish set. Every
removed metadata field is preserved in the corresponding submission’s `controller`
fields or `controller.metadata`; no model/runtime information was discarded. The October 22 status/resume
snapshots are consolidated into
[`attempt-provenance.json`](scoring-v2-2026-10-22/attempt-provenance.json), alongside
the final campaign status. Historical command paths are provenance, not instructions
to recreate the removed sidecars. Use the standard evaluation CLI for new flights.

To recompute a V2 flight without any model/provider calls:

```sh
.venv/bin/python examples/rescore_episode.py path/to/run.json.gz \
  --scoring-config path/to/scoring-config.json --output scratch/rescored.json
```

The optional config is a JSON object of `ScoringConfig` fields; omit it to use the
current defaults. The utility replays the recorded commands at their exact physics
ticks, first verifies the original initial/final state and score, and integrates the
new trajectory terms at 120 Hz. Existing outputs and original records are never
overwritten. All 16 currently published flights (lockstep and realtime) reproduced
the original final states/integrals/scores on the pinned JSBSim 1.3.1 environment.

**Boundary:** logs do not contain every 120 Hz sample. Changed trajectory formulas
therefore require local simulator replay, not model inference. Replay fails closed
if simulator behavior differs; use the matching frozen source/environment. V1-only
and incomplete/infrastructure-interrupted records are not promised exact replay.
Recorded landing success is retained; stricter new safety checks may disqualify it,
but this tool does not relabel a recorded failed rollout as a successful landing.
