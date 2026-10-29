# Local V2 lockstep — three seeds, October 28, 2026

Six installed models (Kev, OpenThai, Decider, Von, Nimble and Clef) completed all
18 lockstep flights. No successful landing occurred; none was added to the graph.
Each model's three-flight cohort is seeds **42, 101 and 202**. The already completed,
validated seed42 flight stays in the [previous campaign](../2026-10-26-local-v2/);
only seeds101/202 are new. Completed failures are retained, not retried for a better
score. A successful landing can qualify the model for the comparison graph using
its best score; a partial cohort must not be described as best-of-three.

Each new trial retains only `submission.json` and its referenced full `.json.gz`
episode. Metadata, temporary raw exports, server logs and attempt diagnostics stay
under ignored `scratch/local-v2-three-seeds-2026-10-28/`. The runner checks the frozen
source and canonical V2 scoring identity, and validates results before publishing.
The matching source archive is retained in the previous campaign's runtime folder.

All 18 unique records passed manifest validation, canonical action-ID/actuator
mapping checks and full offline physics replay of their final states and scores.
Every flight has zero API errors. Original timestamps remain in each record.

## Background operation

The queue can run under the macOS launchd label
`com.flightbench.local-v2-20261028`, independent of the Codex session, with
`caffeinate -i` preventing idle sleep. It does not survive shutdown/logout or a
forced sleep; restarting the runner skips validated finished trials and preserves
incomplete attempts. No simultaneous model servers are started by this queue.

- Progress/successful flights: `scratch/local-v2-three-seeds-2026-10-28/status.json`
- Job state: `launchctl list com.flightbench.local-v2-20261028`
- Stop: `launchctl remove com.flightbench.local-v2-20261028`
- Start/resume in the background: `.venv/bin/python examples/run_local_campaign.py --background`
- Foreground check/resume: `.venv/bin/python examples/run_local_campaign.py`

The background option writes an ignored launchd plist with `KeepAlive=false`: it
runs once and does not restart after completion. Remove an old registered job before
bootstrapping it again. The initial `launchctl submit` job was replaced because it
repeated validation after completion; validated flights were not rerun. Completed
queues now skip model-weight loading as well.

Existing model weights and runtimes are required for pending flights; no new downloads
or paid API calls are used. The graph is not automatically changed by the worker;
verified successful results remain discoverable in its status for publication.
