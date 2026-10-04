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
