# Ghost Race: recorded opponents

Human Pilot settings now offer Off (default), Personal Best, Jev replay, and both.
Complete a successful human or Jev flight first, then start Human Pilot with the
same seed, scenario, timing mode, decision rate, and assistance settings. The
highest-score successful flight becomes that controller's reference. The legend
reports score and recorded duration. Ghosts freeze at their final recorded pose.

References live in this browser session only, capped at twelve setup/controller
pairs. Reloading clears them. This intentionally avoids claiming compatibility
across simulator upgrades. Existing server run files are not imported. Ghosts use
telemetry simulation time, linear position interpolation, quaternion interpolation,
and cloned translucent materials; they never enter physics or control messages.
Benchmark scoring is unchanged. Recorded playback makes no API requests.

This is a bounded implementation of issue #3, not all its acceptance criteria.
Deferred: persistent/imported records, live dual-simulator races, time-winner
results, and advanced progress HUD. Live racing requires synchronized independent
simulation lifecycle and cancellation tests before enabling paid requests.

## Reference coding

Installed XERJ v1.0.0-rc.100 using https://xerj.org/llms.txt instructions.
Local node data: `~/.local/share/xerj-flightbench` (loopback only).
Clones: `~/.local/share/flightbench-references/`.

- three.js: `3fd3e4ec0b454bcc171e5256fd5240251c92340b`
  Indexed `src` with prefix `three`; queried `slerpQuaternions` before coding.
  `src/math/Quaternion.js:771` delegates to copy plus slerp; reuse Three.js interpolation.
- SuperTuxKart: `14349de87845bc8af6236bf54a69a74da40aa30c`
  Indexed `src/replay` with prefix `stk`; queried `interpolation`.
  `replay_recorder.hpp:81` separates transform events from physics information.
- FlightBench: indexed `frontend/src` and `flightbench` with prefixes
  `flightbench` and `flightbench-python`.

Repeat searches with `~/.local/bin/xerj search --prefix three 'slerpQuaternions'`.
No external feedback report or source upload was authorized or sent.

Validation: frontend unit tests and TypeScript/Vite build. Browser visual checks
and real successful simulator flights have not been verified for this change.

## Browser follow-up

Verified in headless Chrome with SwiftShader: real WASM startup and human flight,
Off default, unavailable-opponent messages, PB replay after a synthetic successful
result, reset, and 390px mobile layout without horizontal overflow or page errors.
Inspected desktop/mobile screenshots. Fixed the ghost selector to reuse existing
select styling. `tests/browser_ghost_smoke.js` preserves the fixture-driven check.
The synthetic outcome is not evidence of a real successful landing. Recorded Jev
and simultaneous two-ghost rendering still need browser coverage.
