# FlightBench benchmark protocol v1

Official AI benchmark controllers use one frozen provider-independent protocol:

- benchmark protocol: `flightbench-v1`
- action space: `flightbench-action-space-v1`
- source: `flightbench/protocol.py`

Every AI model receives the same canonical observation fields: flight state, runway state,
current controls, time, temporal motion rates, status, and derived phase (`APPROACH`, `FLARE`,
or `ROLLOUT`). It selects exactly one **string action ID** for each of `aileron`, `elevator`,
`rudder`, and `throttle`. FlightBench strictly validates those four IDs and maps them to the
frozen absolute actuator commands. Unknown, missing, extra, numeric, or continuous outputs are
invalid.

The frozen phase-selection rule enters `FLARE` below 20 m AGL and enters `ROLLOUT` when
`status.on_ground` is true; otherwise the phase is `APPROACH`.

The v1 source preserves the former Jev commands, instructions, decision criteria, bank and
lateral-motion priority, sign conventions, throttle targets, and near-ground elevator rules.
Jev `Choice` questions and categorical LLM prompts are generated from that same source. FLARE
and ROLLOUT replace only the elevator criteria and instructions with the frozen near-ground
rules; the action IDs and command values do not change.

`action_space_json()` provides deterministic canonical JSON. `protocol_metadata()` records the
benchmark version, action-space version, and SHA-256 of that JSON. A change to any command,
criterion, instruction, or phase rule requires a new action-space version; existing v1 results
must keep their original version and hash.

Human, hold, random, and classical baseline controllers are reference participants outside the
shared AI action-space protocol. Any future AI model included in the comparable leaderboard
must consume the canonical observation and return `SharedActionDecision` IDs mapped through
`command_from_action_ids()`; provider-specific transport must not change benchmark semantics.
