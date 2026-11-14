# Design
## Source of truth
Active — 2026-11-14. Local FlightBench browser workbench. Evidence: README.md,
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
Show applied actuator truth separately from proposed model decisions. Scenario selection has its own toolbar button. Model controllers expose realtime/lockstep,
not nominal Hz. Interactive realtime sends one request at a time and immediately requests
the next after application; Codex realtime requires low reasoning effort. Show measured
wall-clock mean applied rate (one decimal, refreshed every five seconds) and mean latency;
retain timing conditions in saved records. Keep deep diagnostics optional.
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
Phone landscape keeps scene and controls side by side; hide the duplicate scene actuator
readout there to leave space for the wind instrument. Pointer capture releases held
inputs on lift/cancel; distinct buttons support simultaneous fingers.
Mobile flight instruments start closed and open with the gauge icon left of controller
settings; desktop instruments remain visible.
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
setup instructions. Scenarios are easy (calm), medium (steady wind), and hard (dynamic wind). A compact compass
shows wind FROM bearing and speed live outside the optional instruments; Jev offers 1.13
and 1.14. Codex remains local only. Public Jev uses the fixed rate-limited proxy
without credential/endpoint fields; both secrets stay in the Worker. Preserve
recording links under an archive, not the site root.

## Ghost Race correction — 2026-11-01
Replay is opt-in and records flights even when disabled. Previous flight includes
stopped and failed flights; Personal Best means highest-score successful human
landing only. Recorded Jev means latest compatible Jev flight, not necessarily a
successful landing. Explain unavailable choices before Start, show duration and
outcome, and keep a visible in-scene legend while racing. Use full-width settings,
existing dark selects, 44px targets, and text labels in addition to tint. Session
scope must be explicit. Do not imply that replay is live Jev.

## Live race and setup controls — 2026-11-01
Controller choice uses single-select cards; opponents use independent checkbox
cards, never combination presets. Hide unavailable opponents and controllers.
Offer live baseline and both Jev versions for every primary controller, not only human.
Local Jev requires configured credentials; Pages uses the existing public proxy. Each live
participant has independent physics, the same scenario/seed, and a shared ready/start barrier.
Continue spectator mode when the primary ends. Stop/Reset/disconnect/new run ends all participants.
Realtime model latency never blocks any simulator. Mode differences remain labeled. API usage is disclosed
on its card. Replay poses and human visuals share the same smoothing time constant;
project labels after updating the camera to avoid one-frame wobble.


## Race camera and results — 2026-11-03
On primary completion, automatically follow an unfinished opponent (live first,
then replay). Do not block this transition with the primary modal; retain it behind
Your result. Label terminal dialogs by flight owner. Opponent-first completion must
not steal input or camera. All camera modes share the same viewed aircraft. Hide
manual controls when spectating, and never label primary telemetry as replay data.
Stop ends viewing; Reset clears it and must not reopen delayed result dialogs.

## Live instruments and diagnostics — 2026-11-14
Keep controller and scenario popovers separate and mutually exclusive, with labeled controls
and 44px touch targets. Wind compass uses N/E/S/W, a FROM arrow, numeric degrees and m/s;
show changing horizontal and vertical wind without depending on color. Easy hides the compass.
Propellers are stationary before Start and after Reset/terminal state.
Diagnostics uses bounded per-axis choice cards: command value, action ID, full criterion,
and applied/discarded state. Compact input measurements and optional raw JSON provide
progressive disclosure; do not invent joint probabilities or confidence when unavailable.
