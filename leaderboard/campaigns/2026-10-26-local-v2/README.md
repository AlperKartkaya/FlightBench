# Local V2 lockstep campaign — October 26–27, 2026

Six models completed one seed 42 flight each, serially at 2 Hz under scoring V2.
Each submission contains a manifest and a compressed full episode with model and
runtime metadata. All applied action IDs matched the recorded actuator commands,
and offline physics replay reproduced every final state and score. No API errors
were recorded. None achieved a successful landing; these archived trials are not
additions to the public comparison graph.

Clef's first attempt was explicitly stopped by the user before episode export; it
is not a scored model failure. A fresh attempt subsequently completed with
`runway_excursion` and score 0. The original interruption evidence remains under
the runtime directory. The completed retry's diagnostics and logs are retained in
`scratch/clef-v2-lockstep-2026-10-27-retry/` (ignored by Git).

[Source and runtime provenance](../../../docs/local-model-runtime/local-v2-lockstep-2026-10-26/).
The directory date identifies campaign start; embedded timestamps identify each run.
