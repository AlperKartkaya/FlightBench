# Local V2 lockstep campaign — October 26–27, 2026

Five models completed one seed42 flight each, serially at 2 Hz under scoring V2.
The five submission manifests reference one compressed full episode apiece;
model/runtime metadata is embedded in each manifest. All applied action IDs matched
the recorded actuator commands, and offline physics replay reproduced every final
state and score. No API errors were recorded. These are archived trials, not additions
to the public comparison graph.

Clef was explicitly stopped by the user on October 27 before episode export.
It has **no completed flight score** and is not a model failure. Its interruption
status, pinned metadata and restart script are retained under the runtime directory.
Do not rerun the five completed models when resuming.

[Source and runtime provenance](../../../docs/local-model-runtime/local-v2-lockstep-2026-10-26/).
The directory date identifies campaign start; embedded timestamps identify each run.

## Resume Clef only

Preserve `docs/local-model-runtime/local-v2-lockstep-2026-10-26/clef-flash/` under a
new dated interrupted-attempt directory before invoking `run-clef.py` in the parent
runtime directory. The script deliberately refuses to overwrite existing evidence.
It needs the installed local model/runtime under `scratch/`; no download or model
run is required to inspect/rescore the five completed records.
