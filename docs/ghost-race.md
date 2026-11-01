# Ghost Race

Human Pilot settings offer **Previous flight**, **Personal best**, **Latest Jev
flight**, or combined opponents. Off is the default. Every flight is recorded
regardless of this setting. Finish or stop a flight, choose an opponent, then
start another human flight. Availability, outcome, score, and duration appear
before Start. In-flight labels identify the ghost aircraft and a persistent legend
reports playback/terminal status. No API requests are made for playback.

- Previous flight: latest compatible flight, including failures and stopped runs.
- Personal best: highest-score successful human landing only.
- Jev replay: latest compatible Jev flight, including failures.
- Combined choices deduplicate an opponent if the previous flight was itself Jev.

Compatibility requires the same runtime, scenario, seed, timing mode, and cadence.
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

Issue #3 is not fully implemented: durable saved-trajectory import, Live Jev dual
simulations, and time-winner results remain absent. Recorded Jev selection has unit
coverage; paid live Jev racing is not claimed.

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
