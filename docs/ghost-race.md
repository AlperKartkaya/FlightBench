# Ghost Race

Human Pilot settings offer separate **Previous flight**, **Personal best**,
**Jev replay**, and **Live Jev** cards when available. Select any combination; none
are selected by default. Every flight is recorded
regardless of this setting. Finish or stop a flight, choose an opponent, then
start another human flight. Availability, outcome, score, and duration appear
before Start. In-flight labels identify the ghost aircraft and a persistent legend
reports playback/terminal status. No API requests are made for playback.

- Previous flight: latest compatible flight, including failures and stopped runs.
- Personal best: highest-score successful human landing only.
- Jev replay: latest compatible Jev flight, including failures.
- Combined choices deduplicate an opponent if the previous flight was itself Jev.

Compatibility requires the same runtime, scenario, timing mode, and cadence; seed is deliberately excluded for Personal best, Previous flight, and Jev replay.
Controllers and assistance can differ: they are opponents, not identical policies.
Trajectories stay in this tab, with up to 24 references. Reload clears them; source
upgrades therefore cannot silently replay an older simulator trajectory. Existing
server JSON records do not contain the sampled transforms and are not imported.
PB is retained preferentially when pruning. No database or dependencies were added.

Playback uses simulation time, linear position interpolation, quaternion slerp,
cloned tinted/emissive transparent materials, and labeled visual-only scene nodes.
A late-loading aircraft model is attached to existing ghosts. Terminal ghosts
freeze at the last recorded pose and can pass out of camera view. Human physics,
controls, and benchmark scoring are unchanged. Reset preserves the ended flight
for replay, including in the browser runtime.

## Evidence and scope

Real local-browser check: human flight with Ghost Race Off, stop, select Previous
flight, start again, inspect labeled replay, then stop. No synthetic success or
paid provider requests. Desktop and 390px screenshots were inspected. See
`tests/browser_previous_ghost_smoke.js`. The separate Pages PB smoke uses a synthetic
success to test PB plumbing; it does not prove a successful landing.

Issue #3 still lacks durable saved-trajectory import and time-winner results.
Live Jev support and its validation are described below.

## Reference coding

XERJ v1.0.0-rc.100 is installed. Local data: `~/.local/share/xerj-flightbench`.
Clones: `~/.local/share/flightbench-references/`.

- Three.js `3fd3e4ec0b454bcc171e5256fd5240251c92340b`: indexed `src` as `three`;
  searched `slerpQuaternions`; `src/math/Quaternion.js:771` reuses copy plus slerp.
- SuperTuxKart `14349de87845bc8af6236bf54a69a74da40aa30c`: indexed `src/replay`
  as `stk`; searched `interpolation`; `replay_recorder.hpp:81` separates transforms
  from physics information.
- Project `frontend/src` and `flightbench` indexed as `flightbench` and
  `flightbench-python`. No source uploads or external feedback were sent.

## Live Jev and multi-select setup (2026-11-01)

The local backend now supports Live Jev: one `start_race` operation initializes
independent human/Jev simulations behind a shared asyncio barrier and gives both
the same realtime clock origin. Seed, scenario, cadence, and environment match.
Jev latency never pauses human physics. Stop, reset, disconnect, and starting another run stop the opponent. Human
terminal outcomes leave Jev flying in spectator mode; Jev failure leaves the human running. Both runs use the
normal JSON record store. An in-flight provider request may finish after cancellation;
existing outstanding-request diagnostics retain that distinction.

The UI shows live Jev only after `/api/capabilities` confirms configured credentials.
Secrets remain server-side. Local credential presence is not proof of validity.
Pages has replay opponents only: its existing browser worker uses lockstep, not the
realtime semantics required for live racing. Controller cards are single-select;
available opponent cards are independent checkboxes. No combination presets remain.

Replay now follows the same exponential visual smoothing clock as the human aircraft.
Labels are projected after the camera update, eliminating the previous-frame offset.
Ghost materials use polygon offset to prevent coplanar depth flicker when aircraft overlap.

Validation: 24 frontend tests, 38 backend tests (including real JSBSim with a fake
slow/failing provider), TypeScript/Vite builds, and Ruff. A short real local-browser
Live Jev race returned two actual Jev decisions, streamed 29 states per aircraft,
and stopped both runs without errors. Desktop and 390px mobile UI screenshots were
inspected. This is not a safe-landing or full-flight performance result.


## Spectator continuation and propellers

After the primary finishes, the camera automatically follows a remaining opponent
without a blocking primary-result dialog. Live Jev takes priority, then unfinished
replays. The primary result stays accessible through **Your result**. When the
last watched opponent finishes, its labeled result opens automatically. An opponent
finishing before the primary does not interrupt primary flight. Live spectating follows Jev telemetry. The replay clock continues from Jev telemetry rather than the finished
human clock. Stop/Reset remain available; starting another run first stops the old
opponent. The result button discloses that provider usage continues while watching.
Ghost propellers animate on their own cloned scene nodes; they do not mutate the
human model. Completed replay ghosts remain frozen at the terminal pose.

Validation includes a fixture-driven browser spectator test (not a real landing),
a cloned-propeller regression, and backend lifecycle tests covering continuation,
explicit stop, and replacement by both solo flights and new races.


Spectator transition regression: `tests/browser_spectator_smoke.js` covers automatic
live/replay handoff, Chase/Orbit/Tower selection, separate primary/opponent results,
replay completion, opponent-first completion, reset stale events, and disconnect.
It uses real local human telemetry plus synthetic opponent lifecycle events; it
makes no provider calls and does not prove a real successful landing. Recorded
replays store poses, not full telemetry: spectator HUD measurements are blank rather
than showing stale primary values. Live spectating retains provider API usage.

The final race dialog ranks the primary and all selected opponents by descending score, with shared ranks for ties. Replay entries retain their recorded results and identify their original seed; this is not a same-seed benchmark comparison.
