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
changed/same badges always carry text. The 3D scene uses muted slate/amber sunset tones with a desaturated horizon and matching fog, an unseen
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
Use the existing FlightBench icon before the header title (22px) and in the controller
identity badge (18px), not a lightning emoji. Its controller name uses the same mint as panel headings. Allow header links to wrap on narrow screens.
## Interaction states
Disconnected/ready/starting/running/completed/interrupted/error are distinct.
Restore the reference video's brief world-space camera fly-in on the first acknowledged
flight pose (1.5s only), from the same render-only runway view on first Start, Reset → Start
and a new run. Aim at the aircraft center, blending to the normal forward look over the
last 300ms. Normal chase follows translation immediately; never restart the fly-in on
control decisions. Disable it for reduced motion and cancel it on camera switches/reset.
After the primary ends, background recordings advance on their own playback clock,
not the watched live pilot's clock. A spectator handoff must not freeze, rewind or
skip their runway rollout; live opponents continue to follow their own telemetry.
An unwatched live pilot finishing must not reset the current camera or spectator view.
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
shows wind flow TO bearing and speed live outside the optional instruments; Jev offers 1.13
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
Controller choice uses compact single-select tiles; opponents use matching independent
checkbox tiles with grouped Jev version badges, never combination presets. Hide unavailable opponents and controllers.
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
and 44px touch targets. Wind compass uses N/E/S/W, a downstream arrow, explicit destination bearing and m/s;
show changing horizontal and vertical wind without depending on color. Easy hides the compass.
Propellers are stationary before Start and after Reset/terminal state.
Diagnostics uses bounded per-axis choice cards: command value, action ID, full criterion,
and applied/discarded state. Compact input measurements and optional raw JSON provide
progressive disclosure; do not invent joint probabilities or confidence when unavailable.

## Compact flight configuration — 2026-11-14
Use a compact slate-glass panel with one shared icon-tile language for primary controllers
and opponents. Primary selection stays single-choice; opponent selection stays multi-choice.
Group Jev versions under one Jev identity with small selectable version badges, not repeated
full cards. Keep descriptions to a short secondary line, with API/replay scope still explicit.
Use system sans for headings, labels, buttons and explanations; monospace only for numeric
telemetry, version badges and technical values. Preserve 44px touch targets and keyboard focus.
Place the wind instrument alongside the top-left flight instruments with matching surfaces,
borders and spacing; keep wind visible when the optional mobile telemetry is collapsed.
A red/cream, open-ended 3D windsock stands just left of the near runway threshold. Observed
wind drives its downstream direction, inflation, droop and damped response; traveling fabric
flutter is visual-only, suppressed by reduced motion. No new physics/scoring or dependencies.
Validation: wind direction/calm/damping/reduced-motion geometry tests, existing race/settings
smokes, desktop/mobile screenshots and build/typecheck. This is a visual fabric approximation,
not a cloth or local surface-wind solver.

## Instrument alignment and race identity — 2026-11-14
Anchor instruments at the viewport's top-left inset, not below a reserved toolbar row.
The toolbar shares a wrapping top rail: when space is tight, controls move below the
instruments instead of pushing instruments toward the middle or overlapping them.
Scenario details use two labeled groups (wind, initial approach) and a reproducibility note,
plain language first and a compact definition list for numeric envelopes. No telemetry abbreviations
or long range strings in prose. Preserve all scenario bounds and seed semantics.
The north-up wind graphic shows downstream flow, like the physical windsock, with the
same damped bearing. Label its destination "To"; the telemetry strip retains source bearing.
Use restrained rose, amethyst, navy, ocean and forest tones for racer identities, with
extra muted replay tones. Only ghost racers receive an overall tint; never recolor the original aircraft livery.
Colors persist through model loading, camera changes and spectator mode; match ghost tint,
opponent selection accents, markers and legend. Text labels remain
mandatory; colors never affect physics/scoring or replace race identity text.

## Instrument readability correction — 2026-11-14
Restore the pre-wind desktop telemetry footprint (440px, 22px values); never shrink it to
make room for weather. Adjacent wind and telemetry cards stretch to equal height. Wrap
cards on narrow screens; mobile telemetry remains optional, expanding the portrait scene
while open so the toolbar stays reachable. Stacked mobile wind uses a compact 74px row. Wind uses a north-up flow
arrow and horizontal speed/direction readings, explicitly marked "To". The 3D red/cream
windsock remains physical, not a compass: its tail and the arrow share the same damped
flow bearing, speed and vertical motion. Describe this distinction in the hover guide.
Racer labels use uniform one-pixel neutral borders and a small identity-color dot, not
colored frames or a thick left edge. Preserve the original aircraft livery.
Use one restrained hover/focus guide across instrument abbreviations: mint term heading,
plain-language definition, unit badge and short sign/direction cue. Keyboard focus and
tap must also reveal it; Escape and outside tap dismiss. Scroll dismisses hover guides;
keyboard-focused guides stay anchored. No image assets needed.
Plan: lock wind-to-geometry agreement in tests, restore existing typography/layout,
replace the ambiguous glyph, then verify responsive bounds and guide interactions.
Scoring analysis is proposal-only: do not alter V2, old records or safety gates.

## Northbound interactive runway — 2026-11-14
New local-browser and Pages flights approach runway 36 on 000° north. Keep Three.js
runway-relative axes (+X along runway, +Y up, +Z right); +X is now north and +Z east.
Rotate actual interactive initial headings, physical wind components, displacement
projection, source bearings and aircraft attitude together. Keep the compass north-up
and the windsock/arrow downstream. Show the runway designation in the instrument card.
Canonical benchmark defaults remain eastbound (090°), as do archived offline replays
without orientation metadata. New interactive records explicitly store runway_heading_deg.
Do not alter safety/scoring formulas or rewrite old results. Verify both orientations,
wrapped headings, wind cardinal directions, native/Pages rendering and baseline landings.

### Heading compass

- Keep a separate north-up aircraft compass immediately beside wind, with the original aircraft silhouette, mint fill and an unpadded signed heading around true north (300° becomes −60°, west −90°, east 90°, south 180°). Keep arrow orientation geographic and wind bearings unchanged. Wind uses the same mint and explicitly shows its source direction.
- Read the latest watched flight attitude, bypassing scene smoothing: primary state, latest live-opponent sample, or current replay time. Never follow the camera or stale primary telemetry when spectating. No CSS rotation interpolation across 359°/0°.
- Omit the runway designator/bearing header from the telemetry panel; the separate aircraft compass provides direction.
- Keep both navigation cards in one row on narrow screens and use the existing accessible instrument-definition style for heading help.

## Wind convention and attitude freedom — 2026-11-14

- Wind-panel arrow and bearing show **FROM**, the standard meteorological source direction (NOAA/NWS glossary). The 3D sock's wide mouth faces that source; its narrow tail streams downstream, 180° opposite. Preserve shared damping, not identical arrow/tail direction. Update accessible descriptions and guides together.
- Use the same mint for compass aircraft and wind arrow. Keep the original compass aircraft silhouette (restored on request). Display heading without zero padding (14°, not 014°).
- New interactive native/Pages flights do not terminate solely at 70° bank or 45° pitch, for any controller. Keep actual impact/contact, unsafe touchdown, excursion, bounds, time and nonfinite-state checks. This permits attempted rolls; it does not certify aerobatic model fidelity or change landing scoring.
- Preserve canonical benchmark and legacy replay attitude cutoffs. Store `attitude_limits: false` in new interactive configs and the WASM manifest; replay respects the recorded rule, defaulting to historical limits when absent. No extra UI mode or dependency.
- Verify high-roll/high-pitch continuation, physical crash checks, legacy replay, source/cloth opposition, symbol color, unpadded headings and responsive layout.
