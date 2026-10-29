# Design
## Source of truth
Active — 2026-09-23. Local FlightBench browser workbench. Evidence: README.md,
frontend/src/main.ts, controls.ts, style.css, existing scratch/screenshots, backend contracts.
## Brand
Calm research instrument: precise, inspectable, honest. Avoid game-like victory/crash
counters, emoji-heavy headings and decorative dashboards.
## Product goals
Configure a reproducible flight and read its live state and decisions in one screen.
Not certified training, multiplayer hosting or a general flight simulator.
Success means trustworthy metrics and understandable experiments, not more controls.
## Personas and jobs
Researcher records controller flights. Developer diagnoses control decisions.
Human pilot explores the same task with explicitly labeled optional assistance.
## Information architecture
One viewport-filling workbench: 3D scene, settings popover, applied actuators and
live model decisions. No page-level Prepare/Observe/Review sections or history table.
## Design principles
Backend truth over optimistic UI. Frozen touchdown separate from final state.
Show applied actuator truth separately from proposed model decisions. The browser fixes
new runs to easy; Codex uses lockstep because provider latency exceeds realtime's stale
threshold, while other controllers use realtime. Keep timing out of the UI and retain
full conditions in saved records. Keep deep diagnostics optional.
## Visual language
Retain dark slate/mint palette and aircraft asset. System sans for explanations,
monospace for measurements. Restrained borders, 8/12/16/24px spacing; no new asset set.
Status uses text plus color. Decision markers animate between categorical choices;
changed/same badges always carry text. The 3D scene uses sunset tones, an unseen
right-side warm sun and aircraft self-shadow; paired runway lights cycle seamlessly,
with steady lights for reduced motion.
Motion is informational, not celebratory.
## Components
Native selects, buttons, details, tables and dialogs. Existing CSS variables own tokens.
Visible labels on every input. Reuse telemetry/diagnostic components; keep the
existing server-side saved-run archive without a browser history table.
## Accessibility
Keyboard-operable controls, visible focus, labeled dialogs, live status/errors,
readable muted text and reduced-motion handling. Target WCAG AA basics; no certification claim.
## Responsive behavior
Desktop keeps scene and controller panel side by side without page scrolling.
Narrow screens stack inside the fixed-height workspace and can scroll that workspace.
Human mode places compact 44px touch controls first, with the scene sticky above them.
Phone landscape keeps scene and controls side by side. Pointer capture releases held
inputs on lift/cancel; distinct buttons support simultaneous fingers.
## Interaction states
Disconnected/ready/starting/running/completed/interrupted/error are distinct.
Disable start offline or pending; lock experiment settings during a run; explicit stop.
Missing touchdown shows N/A. History loading/empty/failure states have explanatory text.
## Content voice
English to match existing UI. Plain descriptions, explicit units, failure != crash.
Keep copy terse. Do not show introductory slogans or quota notices in the workbench.
## Implementation constraints
Vanilla TypeScript + Three.js + CSS, no new dependencies. Local JSON files, no database.
Test pure result helpers and lifecycle API; verify browser desktop and narrow layout.
## Open questions
Full timeline replay and distributed benchmark execution remain outside this implementation.
Both Pages URLs are published; live validation and remaining device/provider gaps
are recorded in docs/wasm/validation.md.

## Pages simulator (2026-10-29)
Reuse the same 3D workbench, keyboard/onscreen controls, assistance, cameras and outcome
dialog. Pages connects it to a Web Worker; default local builds keep Python. Use
concise product labels, no separate demonstration page or development notices.
Completed browser sessions are not labeled Saved; persistence remains documented in
setup instructions. Settings are fixed to easy/seed 42, 2 Hz AI and Jev 1.13; Codex
remains local only. Jev settings accept an endpoint and a separate access token,
never a provider API key. Preserve recording links under an archive, not the site root.
