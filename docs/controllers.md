# External controllers and leaderboard submissions

FlightBench accepts a local controller reference in either `package.module:ClassName` or
`path/to/file.py:ClassName` form. Loading a controller executes local code, so only evaluate code
you trust. Pull-request CI validates submitted JSON and evidence; it does not execute controllers or
use provider credentials.

## Public controller contract

A controller class needs a zero-argument constructor and one method:

```python
def decide(self, observation): ...
```

Set a `metadata` dictionary with `name`, `controller_type`, `provider`, `model`, `source_url`,
`license`, and `local`. `controller_type` is one of `ai`, `classical`, `human`, or `reference`.
Model digest, parameter count, quantization, adapter hash, endpoint version, and generation options
are retained as audit metadata when supplied.

AI controllers return exactly one canonical string action ID for each of `aileron`, `elevator`,
`rudder`, and `throttle`. FlightBench validates the IDs and maps them to `ControlCommand`; JSBSim
alone computes aircraft motion. Classical controllers may return a validated `ControlCommand`
directly. See [`examples/controllers/categorical.py`](../examples/controllers/categorical.py).

The public frozen semantics are `flightbench-v1` and `flightbench-action-space-v1`. The exact
choices, prompt helper, and SHA-256 fingerprint live in [`flightbench/protocol.py`](../flightbench/protocol.py).
Do not copy those choices into an adapter.

## Evaluate

Run both modes with the same seeds:

```bash
flightbench eval \
  --controller examples/controllers/categorical.py:ExampleController \
  --modes lockstep,realtime \
  --seeds 42,101,202,303,404 \
  --jobs 4 \
  --output-dir leaderboard/submissions/example-v1
```

The command writes `submission.json` and deterministic gzip evidence containing every full episode
record. Realtime and lockstep are modes over the same architecture-neutral roster, not separate
model categories.

## Validate and submit

```bash
flightbench leaderboard validate leaderboard/submissions/example-v1/submission.json
flightbench leaderboard build
```

Open a pull request containing the submission and all referenced evidence. CI checks the v1 schema,
protocol and action-space fingerprints, aggregate metrics, run summaries, evidence hashes, and
evidence provenance. New entries remain **community / self-reported** until a maintainer reproduces
them or a trusted isolated workflow does so. Schema validation alone never grants verified status.

Provider cost must remain unknown when unavailable. For a local model, a zero provider fee does not
include hardware or electricity; record that boundary in `cost_methodology` metadata. Pre-v1 Jev
and Codex records may appear only as explicitly labeled legacy/reference data and are never relabeled
as v1 submissions.

## Maintainer-owned verification

Submission JSON accepts only `community / self-reported`. It cannot claim `verified`, even by
naming a maintainer or trusted workflow. After an independent reproduction, a maintainer records
the exact submission-file SHA-256 in `leaderboard/verified.json`, with `method` and evidence `notes`.
Changing any submission byte invalidates that publication label. The generated leaderboard reads
this separate trusted registry; PR CI uses the **base branch's** registry, never the proposed PR's
verification claims. All local campaign entries currently remain community results.

Evidence must share a controller, model, type, protocol, source identity and evaluation settings.
AI evidence must contain canonical action IDs and matching commands. Claimed runtime audit
metadata, hardware and dependency versions must match the full records. These checks detect
inconsistency; they do not prove that self-reported evidence was honestly generated.

## Timing and incomplete provider usage

New full records separate `requests_started` (submitted work), `requests_completed`,
`requests_cancel_requested`, `requests_cancelled_before_start`, and `requests_outstanding`.
`calls` remains the number of recorded decision events for compatibility; timeout events are
not completed provider responses. `decision_count` counts applied, non-error commands.
Outstanding work is frozen at terminal cleanup and may finish later; cancellation of a Python
thread is not guaranteed. Browser accounting conservatively includes work whose cancellation
cannot be proven. Terminal physics and saved evidence never change after a late response.

`usage_unknown_requests` also covers completed responses that reached terminal before their
usage was collected. Such remote-provider totals stay unknown in submissions; lower-bound CLI
estimates retain their missing-usage count. Zero local provider fees still exclude compute,
hardware and electricity. Old records have no started/outstanding counters: publication displays
unknown rather than retrospectively inventing them.

Plots conservatively separate source hashes, execution paths, declared hardware/load, and
evaluation settings. A validator-only edit can therefore create another cohort; equivalence is
not inferred solely from an unchanged action-space hash. Undeclared execution conditions remain
unknown, never proof of identical hardware performance. A result's effective applied Hz uses
simulation seconds, not wall-clock throughput.

Long local file references are supported without copying their path into short display metadata.
Without explicit model metadata the class name is only an identifier, not a claimed checkpoint;
provide real checkpoint/digest information for reproducible model submissions.

## Applying realtime responses on arrival

Use `--realtime-response-policy apply-on-arrival` to apply every valid completed model command
while the episode is active. Physics continues at the requested realtime scale; there is one
pending request, no command blending, and no age-based rejection in this mode. Invalid responses,
transport failures and episode termination still retain their explicit error/accounting behavior.
The browser uses this policy too. The CLI's historical `discard-stale` default remains available
for reproducing older records; choose the policy explicitly when comparing experiments.

The selected policy is recorded in run config and submission evaluation, checked against evidence,
and included in comparison grouping. It does not change the frozen observation, action vocabulary,
phase instructions, actuator mapping or scoring. Results with different timing policies must not
be silently combined.

## Pinned live Jev versions

The built-in Jev controller supports `jev-1.13.0` (default) and `jev-1.14.0` (preview).
It requires the returned model version to match the requested pin and retains actual provider
input/output token counts. Credentials are loaded from `TYPESAFE_API_KEY`/the ignored `.env` file;
do not put credentials in a command argument or metadata file.

```sh
uv run flightbench eval --controller jev --model jev-1.14.0 \
  --modes lockstep,realtime --seeds 42 --jobs 1 --decision-hz 2 --time-scale 1 \
  --realtime-response-policy apply-on-arrival \
  --output-dir scratch/jev-preview-new-run
```

The preview model is selected through the CLI; the browser retains its stable Jev selection.
Model/version and API fields were checked against [official models](https://docs.typesafe.ai/models.md)
and [System One API documentation](https://docs.typesafe.ai/api/system-one.md) on 2026-10-20.

## Scoring V2 and Codex effort sweeps

New CLI/browser runs use scoring V2. The categorical action protocol remains `flightbench-v1`;
scoring version and complete scoring-configuration hash are separate evidence fields. V1
records remain unchanged and default to V1 when the historical field is absent.
See [the formulas and calibration](scoring/README.md).

```sh
uv run flightbench eval --controller codex --model openai-codex/gpt-6.1-sol \
  --reasoning-effort max --modes lockstep --seeds 42,101 --jobs 1 \
  --decision-hz 2 --timeout 300 --output-dir runs/2026-10-22-sol-max
```

Supported explicit efforts: `low`, `medium`, `high`, `xhigh`, `max`; default remains `low`.
The installed plugin's older option enum is extended per-model for literal `max`, without
replacing it with another effort or changing the SDK installation. Every decision records
the requested effort; exported metadata is checked against the actual decision records.

For the dated curated campaign, regenerate only its selected best-of-three rows and figures:

```sh
.venv/bin/python examples/build_v2_publication.py \
  --submissions leaderboard/campaigns/2026-10-22-scoring-v2/submissions \
  --output docs/evaluations/2026-10-22-scoring-v2
```

The curated chart excludes historical/open-model campaigns. Those raw records remain dated
in the [archive index](local-model-runtime/archive-index.json). Codex cost means API-equivalent
Standard pricing applied to the selected flight's full actual usage, not subscription billing.
Unknown usage is not shown as zero cost; neither calls nor cost is normalized to another flight.
