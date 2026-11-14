import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import type { Control } from "./controls.ts";
import { copyControls, updateHumanControls, defaultControls, adjustControl, centerSurfaces, humanKey } from "./controls.ts";
import { nextRunState, outcomeLabel, touchdownValues } from "./results.ts";
import type { RunState, RunEvent, RunRecord, RunConfig, Outcome } from "./results.ts";
import { isRunwayLightOn } from "./runway-lights.ts";
import { BrowserRuntime } from "./browser-runtime.ts";
import { updateChasePosition } from "./camera.ts";
import { createWindsock } from "./windsock.ts";
import { setupInstrumentHelp } from "./instrument-help.ts";
import "./style.css";
import { selectGhost, poseAt, smoothReplayTime, ghostMaterial, racerColor, spinGhostPropeller, type Ghost, type Sample } from "./ghosts.ts";

const pagesRuntime = import.meta.env.MODE === "pages";

type Observation = {
  time_s: number;
  runway: {
    distance_to_threshold_m: number;
    along_track_m?: number;
    cross_track_error_m: number;
    centerline_offset_m?: number;
    runway_width_m?: number;
    altitude_agl_m: number;
    glideslope_error_deg: number;
    heading_error_deg: number;
  };
  flight: {
    airspeed_mps: number;
    groundspeed_mps?: number;
    vertical_speed_mps: number;
    flight_path_angle_deg?: number;
    angle_of_attack_deg?: number;
    roll_deg: number;
    pitch_deg: number;
    heading_deg: number;
    p_rad_s?: number;
    q_rad_s?: number;
    r_rad_s?: number;
  };
  environment?: {
    headwind_mps: number;
    crosswind_mps: number;
    vertical_wind_mps?: number;
    wind_speed_mps?: number;
    wind_dir_deg?: number;
  };
  controls: Control & { flaps_deg: number };
  status?: { on_ground?: boolean; main_gear_on_ground?: boolean };
  ground_contact?: {
    any_gear_wow?: boolean;
    nose_gear_wow?: boolean;
    left_main_gear_wow?: boolean;
    right_main_gear_wow?: boolean;
  };
};

type JevChoiceDetail = {
  choice?: string;
  command?: number;
  id?: string;
  action: string | Record<string, string>;
  delta: number | Record<string, number>;
  previous_value?: number;
  new_value?: number;
  previous_values?: Record<string, number>;
  new_values?: Record<string, number>;
  legal_count: number;
  legal_options: Record<string, string>;
  legal_deltas?: Record<string, Record<string, number>>;
  label?: string;
  confidence?: number | null;
  probabilities?: Record<string, number> | null;
  returned_option_count?: number;
  probability_sum?: number;
  selected_probability?: number | null;
  model_selected_id?: string;
  model_selected_probability?: number | null;
  last_micro_action?: {
    axis: string;
    delta: number;
  } | null;
  fallback?: {
    active: boolean;
    reason?: string | null;
    confidence_floor?: number;
    baseline_action_id?: string | null;
  };
};

type LiveStatus = {
  is_deciding: boolean;
  cadence_hz: number;
  calls: number;
  latency_ms: number | null;
  avg_latency_ms: number | null;
  late_decisions: number;
  stale_decisions: number;
  api_errors: number;
  last_api_error: string | null;
  state_age_ms: number | null;
  nominal_decision_hz?: number;
  effective_decision_hz?: number;
  simulation_speed?: number;
};

type DecisionInfo = {
  command?: Record<string, number>;
  policy?: string;
  controller: string;
  model?: string;
  summary?: string;
  observation_schema_version?: string;
  input?: {
    phase?: string;
    time_s?: number;
    flight?: Observation["flight"];
    runway?: Observation["runway"];
    environment?: Observation["environment"];
    motion?: Record<string, number>;
    status?: Observation["status"];
    current_controls?: Record<string, number>;
    previous_selected_actions?: Record<string, string>;
    aircraft_telemetry?: Record<string, number>;
    aircraft_state?: Record<string, number>;
    angular_rates?: Record<string, number>;
    runway_relative?: Record<string, number>;
    ground_contact?: Record<string, boolean>;
    rates?: Record<string, number>;
    current_rates?: Record<string, number>;
    recent_change?: Record<string, number>;
    timing?: { sim_time_s?: number; decision_interval_s?: number };
    control_change?: Record<string, number>;
    previous_control_transition?: Record<string, any> | null;
    observed_since_previous_action?: Record<string, any> | null;
    recent_action_history?: Array<Record<string, any>>;
  };
  choices?: Record<string, JevChoiceDetail>;
  live_status?: LiveStatus;
  timing?: { applied?: boolean; discard_reason?: string };
};

type StateMessage = {
  type: "state";
  run_id?: string;
  observation: Observation;
  position: [number, number, number];
  quaternion: [number, number, number, number];
  score: number;
  status: string;
  decision_count: number;
  latency_ms: number | null;
  decision_info?: DecisionInfo | null;
  result?: Outcome;
};

const app = document.querySelector<HTMLDivElement>("#app")!;
app.innerHTML = `
  <header class="topbar">
    <div class="brand-section"><strong class="brand-title"><img class="brand-logo-icon" src="${import.meta.env.BASE_URL}flightbench-icon.png" width="22" height="22" alt=""/>FlightBench</strong><a class="profile-link profile-github" href="https://github.com/alperkartkaya" target="_blank" rel="noopener noreferrer" aria-label="AlperKartkaya on GitHub"><svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 .5a11.5 11.5 0 0 0-3.64 22.4c.58.1.79-.25.79-.56v-2.02c-3.22.7-3.9-1.37-3.9-1.37-.52-1.33-1.28-1.68-1.28-1.68-1.05-.72.08-.71.08-.71 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.7 1.26 3.36.96.1-.75.4-1.26.73-1.55-2.57-.29-5.27-1.29-5.27-5.73 0-1.27.45-2.3 1.19-3.12-.12-.29-.52-1.48.11-3.08 0 0 .97-.31 3.16 1.19a11 11 0 0 1 5.75 0c2.19-1.5 3.15-1.19 3.15-1.19.63 1.6.24 2.79.12 3.08.74.82 1.18 1.85 1.18 3.12 0 4.45-2.7 5.43-5.28 5.72.41.36.78 1.07.78 2.16v3.19c0 .31.21.67.79.56A11.5 11.5 0 0 0 12 .5Z"/></svg><span>AlperKartkaya</span></a><a class="profile-link profile-linkedin" href="https://www.linkedin.com/in/alper-kartkaya-boun-cmpe" target="_blank" rel="noopener noreferrer" aria-label="Alper Kartkaya on LinkedIn"><svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M20.45 2H3.55C2.7 2 2 2.67 2 3.5v17C2 21.33 2.7 22 3.55 22h16.9c.85 0 1.55-.67 1.55-1.5v-17c0-.83-.7-1.5-1.55-1.5ZM8 18.75H4.9V9H8v9.75ZM6.45 7.66a1.8 1.8 0 1 1 0-3.6 1.8 1.8 0 0 1 0 3.6Zm12.3 11.09h-3.1V14c0-1.13-.02-2.58-1.57-2.58-1.57 0-1.81 1.23-1.81 2.5v4.83h-3.1V9h2.98v1.33h.04c.42-.78 1.43-1.6 2.94-1.6 3.15 0 3.62 2.07 3.62 4.76v5.26Z"/></svg><span>Alper Kartkaya</span></a></div>
    <div class="status-group"><span class="sr-only" id="runStatus" role="status">Connecting…</span><span class="flight-state-pill" id="flightStatePill" data-state="IDLE">IDLE</span><i class="status-dot" id="connectionDot" aria-hidden="true"></i><span id="connectionText" role="status">OFFLINE</span></div>
  </header>
  <main class="workspace">
    <!-- Simulation Center Column (~74%) -->
    <section class="sim-column">
      <div class="viewport-container">
        <canvas id="viewport" aria-label="3D flight simulation"></canvas>
        <div id="renderUnavailable" class="render-unavailable" hidden><strong>3D view unavailable</strong><p>This browser could not initialize WebGL. Telemetry, controls and saved results still work. Try a browser with hardware acceleration enabled.</p></div>

        <div class="viewport-topbar">
        <div class="viewer-toolbar" id="viewerToolbar">
          <button class="btn-secondary" id="hudToggle" type="button" aria-label="Flight instruments" title="Flight instruments" aria-controls="hudOverlay" aria-expanded="false"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M4.2 17a9 9 0 1 1 15.6 0M12 3v2M3 12h2m14 0h2M12 12l4-4"/><circle cx="12" cy="12" r="1.5"/></svg></button>
          <button class="btn-secondary" id="configureToggle" type="button" aria-label="Flight settings" aria-controls="configPanel" aria-expanded="false">Human pilot ▾</button>
          <button class="btn-secondary" id="scenarioToggle" type="button" aria-label="Scenario settings" aria-controls="scenarioPanel" aria-expanded="false">Easy ▾</button>
          <button class="btn-primary" id="start" disabled>Start flight</button><button class="btn-secondary" id="stop" aria-label="Stop and save" disabled>Stop</button><button class="btn-secondary" id="reset" disabled>Reset</button>
          <div class="viewer-config-panel" id="configPanel" hidden>
            <div class="configuration-header"><span class="panel-eyebrow">FLIGHT SETUP</span><h2>Flight configuration</h2></div>
            <fieldset id="experimentSettings"><legend class="sr-only">Experiment settings</legend>
              <div class="config-group">
                <div class="config-item"><div class="settings-heading">Your controller</div><div id="controllerCards" class="controller-cards" role="radiogroup" aria-label="Your controller"></div><select id="controller" aria-label="Controller" hidden>
                  <option value="human" selected>Human pilot</option><option value="baseline">Baseline · rule-based</option>
                  <option value="jev">Jev</option><option value="codex">Codex model</option></select></div>
                <div class="config-item" id="modelGroup" hidden><label for="model">Model</label><select id="model" class="select-input"></select></div>
                <div class="config-item" id="jevModelGroup" hidden><span class="settings-label">Jev version</span><div id="jevVersionChoices" class="version-choices" role="radiogroup" aria-label="Jev version"></div><select id="jevModel" hidden><option value="jev-1.13.0">1.13</option><option value="jev-1.14.0">1.14</option></select></div>
                <div class="config-item" id="reasoningEffortGroup" hidden><label for="reasoningEffort">Reasoning effort</label><select id="reasoningEffort" class="select-input"><option value="low">low</option><option value="medium">medium</option><option value="high">high</option><option value="xhigh">xhigh</option><option value="max">max</option></select></div>
                <div class="config-item" id="timingModeGroup"><label for="timingMode">Execution</label><select id="timingMode" class="select-input"><option value="realtime" selected>Realtime</option><option value="lockstep">Lockstep</option></select><small>Realtime keeps flying while the model thinks. Lockstep waits for each reply.</small></div>
                <div class="config-item" id="ghostSettings"><div class="settings-heading">Race opponents <span class="selection-hint">Select multiple</span></div><div id="ghostChoices" class="opponent-grid" role="group" aria-label="Race opponents"></div><div id="ghostStatus" role="status"></div><small id="ghostHelp">Live pilots share your scenario and seed. Each live Jev uses the API; rate limits apply. Replays stay in this tab.</small></div>
              </div>
            </fieldset>
          </div>
          <div class="viewer-config-panel scenario-panel" id="scenarioPanel" hidden>
            <fieldset id="scenarioSettings"><legend class="settings-heading">Flight conditions</legend><div class="config-group">
                <div class="config-item" id="scenarioGroup" style="grid-column: 1 / -1;"><label for="scenario">Scenario</label><select id="scenario" class="select-input"><option value="easy" selected>Easy · calm air</option><option value="medium">Medium · steady wind</option><option value="hard">Hard · dynamic wind / gusts</option></select><div id="scenarioSummary" class="scenario-conditions" aria-live="polite"></div></div>
                <div class="config-item" id="seedGroup" hidden><label for="seed">Seed</label><input class="number-input" id="seed" type="number" value="42" min="0" max="4294967295" step="1" required /></div>
            </div></fieldset>
          </div>
        </div>

        <!-- Primary HUD (Top-Left Canvas Overlay) -->
        <div class="flight-instruments">
        <div class="hud-overlay" id="hudOverlay" data-open="false">
          <div class="hud-panel">
            <div class="runway-bearing"><strong class="instrument-label">RUNWAY 36</strong><span>0° · NORTH</span></div>
            <div class="hud-primary-grid">
              <div class="hud-metric">
                <span class="hud-label">AGL</span>
                <span class="hud-value highlight" id="hudAgl">—<small>m</small></span>
              </div>
              <div class="hud-metric">
                <span class="hud-label">IAS</span>
                <span class="hud-value" id="hudIas">—<small>m/s</small></span>
              </div>
              <div class="hud-metric">
                <span class="hud-label">V/S</span>
                <span class="hud-value" id="hudVsi">—<small>m/s</small></span>
              </div>
              <div class="hud-metric">
                <span class="hud-label">FPA</span>
                <span class="hud-value" id="hudFpa">—<small>°</small></span>
              </div>
            </div>
            <div class="hud-secondary-row">
              <div class="hud-sub-metric">
                <span class="hud-sub-label">OFFSET</span>
                <span class="hud-sub-val" id="hudXtrack">—</span>
              </div>
              <div class="hud-sub-metric">
                <span class="hud-sub-label">GLIDE</span>
                <span class="hud-sub-val" id="hudGlide">—</span>
              </div>
              <div class="hud-sub-metric">
                <span class="hud-sub-label">HDG ERR</span>
                <span class="hud-sub-val" id="hudHdgErr">—</span>
              </div>
              <div class="hud-sub-metric">
                <span class="hud-sub-label">AOA</span>
                <span class="hud-sub-val" id="hudAoa">—</span>
              </div>
            </div>
          </div>
        </div>

        <div class="navigation-instruments">
        <div class="wind-instrument" id="windInstrument" hidden aria-label="Live wind">
          <svg class="wind-compass" viewBox="0 0 80 80" role="img" aria-label="Direction wind comes from, north up">
            <circle cx="40" cy="40" r="26"/><path class="compass-ticks" d="M40 12v5m28 23h-5M40 68v-5M12 40h5"/>
            <text x="40" y="9">N</text><text x="74" y="43">E</text><text x="40" y="78">S</text><text x="6" y="43">W</text>
            <g id="windArrow"><path d="M40 19 32 32h6v27h4V32h6z"/></g>
          </svg>
          <div class="wind-readings"><span class="wind-label">WIND FROM</span><div class="wind-reading-row"><strong id="windSpeed">— m/s</strong><span id="windBearing">From —°</span></div><small id="windVertical">Awaiting flight</small></div>
        </div>
        <div class="heading-instrument" id="headingInstrument" aria-label="Aircraft heading, north up">
          <svg class="wind-compass heading-compass" viewBox="0 0 80 80" role="img" aria-label="Aircraft nose direction, true north up">
            <circle cx="40" cy="40" r="26"/><path class="compass-ticks" d="M40 12v5m28 23h-5M40 68v-5M12 40h5M59 21l-3 3m3 35-3-3M21 59l3-3m-3-35 3 3"/>
            <text class="compass-north" x="40" y="9">N</text><text x="74" y="43">E</text><text x="40" y="78">S</text><text x="6" y="43">W</text>
            <g id="headingNeedle"><path d="M40 20 43 35 54 44v3l-12-4v10l4 4v2l-6-2-6 2v-2l4-4V43l-12 4v-3l11-9z"/></g>
          </svg>
          <div class="heading-readings"><span class="instrument-label">HEADING</span><strong id="compassHeading">0°</strong><small>TRUE NORTH</small></div>
        </div>
        </div>

        </div>

        </div>

        <div class="flight-readout" aria-label="Live controller and actuator output">
          <div class="flight-readout-head"><strong id="overlayController">Baseline Controller</strong><span id="overlayCadence">— Hz</span></div>
          <div class="flight-readout-grid">
            <div><span>AIL</span><strong id="overlayAileron">—</strong></div>
            <div><span>ELE</span><strong id="overlayElevator">—</strong></div>
            <div><span>RUD</span><strong id="overlayRudder">—</strong></div>
            <div><span>THR</span><strong id="overlayThrottle">—</strong></div>
          </div>
          <div class="flight-decision" id="overlayDecision" hidden><span id="overlayDecisionStatus">JEV DECISION</span><strong id="overlayDecisionText">Awaiting first response</strong></div>
        </div>

        <!-- Camera Switcher Overlay (Bottom-Right Canvas Overlay) -->
        <div class="camera-controls">
          <button class="camera-btn active" data-camera="chase">1 Chase</button>
          <button class="camera-btn" data-camera="orbit">2 Orbit</button>
          <button class="camera-btn" data-camera="tower">3 Tower</button>
        </div>
      </div>

      <!-- Horizontal Telemetry Strip (Docked Below Canvas) -->
      <footer class="telemetry-strip" id="telemetryStrip">
        <div class="strip-item">
          <span class="strip-label">PHASE</span>
          <span class="strip-value highlight-accent" id="stripPhase">APPROACH</span>
        </div>
        <div class="strip-divider"></div>
        <div class="strip-item">
          <span class="strip-label">ALONG</span>
          <span class="strip-value" id="stripAlong">—</span>
        </div>
        <div class="strip-divider"></div>
        <div class="strip-item">
          <span class="strip-label">THRESHOLD</span>
          <span class="strip-value" id="stripThresh">—</span>
        </div>
        <div class="strip-divider"></div>
<div class="strip-item">
          <span class="strip-label">ROLL</span>
          <span class="strip-value" id="stripRoll">—</span>
        </div>
        <div class="strip-divider"></div>
        <div class="strip-item">
          <span class="strip-label">PITCH</span>
          <span class="strip-value" id="stripPitch">—</span>
        </div>
        <div class="strip-divider"></div>
        <div class="strip-item">
          <span class="strip-label">WIND</span>
          <span class="strip-value" id="stripWind">Calm</span>
        </div>
        <div class="strip-divider"></div>
<div class="strip-item">
          <span class="strip-label">SCORE</span>
          <span class="strip-value" id="stripScore">0.0</span>
        </div>
      </footer>
    </section>

    <!-- AI & Controller Sidebar (~26%, 380-440px) -->
    <aside class="controller-column" id="controllerSidebar">
      <!-- Controller Banner & Health -->
      <section class="ctrl-card jev-header-banner" id="ctrlIdentityCard">
        <div class="jev-title-row">
          <div class="jev-brand-badge">
            <img class="brand-logo-icon" src="${import.meta.env.BASE_URL}flightbench-icon.png" width="18" height="18" alt=""/>
            <strong id="ctrlBrandTitle">TypeSafe Jev</strong>
          </div>
          <span class="jev-model-tag" id="ctrlModelTag">System One</span>
        </div>
        <div class="ctrl-chips-row">
          <div class="meta-chip" id="chipDecisionNum">Applied <strong>#—</strong></div>
          <div class="meta-chip"><span class="instrument-label">Mean latency</span><strong id="cadenceValue">— ms</strong></div>
          <div class="meta-chip"><span class="instrument-label">Effective Rate</span><strong id="effectiveRate">— Hz</strong></div>
          <div class="meta-chip" id="chipLatency">Latency <strong>— ms</strong></div>
          <div class="meta-chip" id="chipStateAge">Age <strong>— ms</strong></div>
          <div class="meta-chip">Actions <strong id="actionCount">—</strong></div>
        </div>
      </section>

      <section class="ctrl-card live-decision-card" id="liveDecisionCard" hidden aria-label="Live model decisions">
        <div class="ctrl-card-header"><span class="ctrl-card-title">Latest model exchange</span><span class="decision-state" id="decisionState">WAITING</span></div>
        <div class="decision-count-line"><strong id="decisionSequence">#—</strong><span id="decisionLatency">— ms</span></div>
        <div class="decision-input" id="decisionInput" hidden>
          <div class="decision-section-title">SENT TO JEV <span id="decisionInputTime">—</span></div>
          <div class="decision-input-row"><span>FLIGHT</span><strong id="decisionInputFlight">—</strong></div>
          <div class="decision-input-row"><span>RUNWAY</span><strong id="decisionInputRunway">—</strong></div>
          <div class="decision-input-row"><span>WIND</span><strong id="decisionInputWind">—</strong></div>
          <div class="decision-input-row"><span>CURRENT</span><strong id="decisionInputControls">—</strong></div>
          <div class="decision-input-row"><span>MOTION</span><strong id="decisionInputMotion">—</strong></div>
        </div>
        <div class="decision-section-title" id="decisionOutputTitle">MODEL CHOSE · REQUESTED CONTROLS</div>
        <div class="decision-axes" id="decisionAxes">
          <div class="decision-axis" id="decisionAxisAileron" data-axis="aileron"><span>AILERON</span><strong id="decisionAileron">—</strong><b id="decisionAileronValue">—</b><em id="decisionAileronChange">—</em><div class="decision-axis-track"><i id="decisionAileronMarker"></i></div></div>
          <div class="decision-axis" id="decisionAxisElevator" data-axis="elevator"><span>ELEVATOR</span><strong id="decisionElevator">—</strong><b id="decisionElevatorValue">—</b><em id="decisionElevatorChange">—</em><div class="decision-axis-track"><i id="decisionElevatorMarker"></i></div></div>
          <div class="decision-axis" id="decisionAxisRudder" data-axis="rudder"><span>RUDDER</span><strong id="decisionRudder">—</strong><b id="decisionRudderValue">—</b><em id="decisionRudderChange">—</em><div class="decision-axis-track"><i id="decisionRudderMarker"></i></div></div>
          <div class="decision-axis" id="decisionAxisThrottle" data-axis="throttle"><span>THROTTLE</span><strong id="decisionThrottle">—</strong><b id="decisionThrottleValue">—</b><em id="decisionThrottleChange">—</em><div class="decision-axis-track"><i id="decisionThrottleMarker"></i></div></div>
        </div>
      </section>

      <!-- Actuator Output -->
      <section class="ctrl-card">
        <div class="ctrl-card-header">
          <span class="ctrl-card-title">Actuator Output</span>
          <span class="ctrl-header-btn" id="ctrlTrimIndicator">Applied controls</span>
        </div>
        <div class="actuator-list" id="actuatorRows">
          <!-- Aileron, Elevator, Rudder, Throttle rendered dynamically -->
        </div>
      </section>

      <details class="diagnostics" id="decisionDiagnostics"><summary>Decision diagnostics <span>Input, choices & application</span></summary><p class="diagnostic-help">Requested commands are shown below. Applied controls are shown in the actuator panel; discarded replies do not move them.</p>
      <!-- Current Joint Decision Card -->
      <section class="ctrl-card" id="jointDecisionCard">
        <div class="ctrl-card-header">
          <span class="ctrl-card-title">Current Joint Action</span>
          <div class="ctrl-header-actions">
            <button class="ctrl-header-btn active" id="toggleMarginalsBtn" title="Toggle 1D axis marginal distributions">Axis Marginals</button>
            <button class="ctrl-header-btn" id="openAllOptionsBtn">View All Options</button>
          </div>
        </div>
        <div class="joint-decision-box">
          <div class="joint-id-row">
            <span class="joint-code-pill" id="jointCodePill">A0_E0_R0_T0</span>
            <span class="joint-confidence-badge" id="jointConfidenceBadge">Confidence —%</span>
            <span class="joint-confidence-badge" id="jointSourceBadge">MODEL</span>
            <span class="joint-confidence-badge joint-stability-badge" id="jointStabilityBadge" style="display: none;">🛡️ STABILITY HOLD</span>
          </div>
          <div class="prob-bars-group" id="topProbBars">
            <!-- Top 5 options rendered dynamically -->
          </div>

          <!-- Expanded Axis Marginals Diagnostics (Section 13) -->
          <div class="axis-marginals-section" id="axisMarginalsSection">
            <div class="axis-marginals-title">
              <span>AXIS MARGINALS (1D PROJECTIONS)</span>
              <span class="marginals-badge" id="marginalsHoldBadge">P(HOLD ALL) —%</span>
            </div>
            <div class="axis-marginals-grid" id="axisMarginalsGrid">
              <!-- Rendered dynamically for Aileron, Elevator, Rudder, Throttle -->
            </div>
          </div>
        </div>
      </section>

      <!-- Last Action -> Observed Consequence Feedback -->
      <section class="ctrl-card" id="consequenceCard">
        <div class="ctrl-card-header">
          <span class="ctrl-card-title">Action → Observed Effect</span>
          <span class="meta-chip" id="consequenceElapsedChip">dt = 0.50 s</span>
        </div>
        <div class="feedback-box">
          <div class="feedback-transition-grid" id="transitionGrid">
            <!-- 4 axes before -> after -->
          </div>
          <div class="observed-deltas-grid" id="observedGrid">
            <!-- dIAS, dVSI, dFPA, dAoA, dALT, dXTRACK, dGLIDE, dHDG, dROLL, dPITCH -->
          </div>
        </div>
      </section>

      <!-- Input Sent to Jev -->
      <section class="ctrl-card" id="inputSummaryCard">
        <div class="ctrl-card-header">
          <span class="ctrl-card-title">Input Sent to Model</span>
          <button class="ctrl-header-btn" id="openRawInputBtn">View Raw JSON</button>
        </div>
        <div class="input-summary-grid" id="inputSummaryGrid">
          <!-- Motion, Runway, Timing summary items -->
        </div>
      </section>

      <!-- Decision History -->
      <section class="ctrl-card" id="decisionHistoryCard">
        <div class="ctrl-card-header">
          <span class="ctrl-card-title">Recent Decisions</span>
          <button class="ctrl-header-btn" id="openFullHistoryBtn">Full History Log</button>
        </div>
        <div class="history-cards-list" id="historyCardsList">
          <!-- Last 3 cards rendered dynamically -->
        </div>
      </section>

      </details>
      <!-- Manual Pilot Controls (Shown when Controller == "Human") -->
      <section class="ctrl-card manual-panel" id="manualControlsCard" style="display: none;">
        <div class="ctrl-card-header">
          <span class="ctrl-card-title">Manual Flight Controls</span>
        </div>
        <div class="assist-toolbar">
          <label class="assist-toggle" title="Spring-loaded return to flight trim when keys released">
            <input type="checkbox" id="autoCenterToggle" checked />
            <span>Auto-Center</span>
          </label>
          <label class="assist-toggle" title="Optional approach, flare, heading and throttle assistance">
            <input type="checkbox" id="wingLevelerToggle" />
            <span>Landing assistance</span>
          </label>
          <span class="assist-status-pill" id="assistStatusPill">OFF</span>
        </div>

        <!-- Pitch -->
        <div class="axis-group">
          <div class="axis-visual">
            <svg class="motion-svg" viewBox="0 0 44 44" aria-hidden="true">
              <path d="M38 12 A 22 22 0 0 0 38 32" fill="none" stroke="#375549" stroke-width="1.5" stroke-dasharray="2 2" />
              <polygon points="38,9 35,14 41,14" fill="#78b794" />
              <polygon points="38,35 35,30 41,30" fill="#78b794" />
              <g id="planeSideGroup" style="transform-origin: 20px 22px; transition: transform 0.08s ease-out;">
                <path d="M6 22 L18 20 L20 15 L23 15 L22 20 L32 21 L35 19 L36 21 L33 23 L22 23 L14 27 L11 27 L13 23 Z" fill="#95d6ad" />
                <path d="M12 20 L16 16 L18 16 L15 20 Z" fill="#6ba783" />
              </g>
            </svg>
            <div class="axis-meta">
              <span class="axis-title">PITCH (Elevator)</span>
              <span class="axis-desc">Nose Up / Down</span>
            </div>
          </div>
          <div class="axis-btns">
            <button class="ctrl-btn" data-axis="elevator" data-dir="-1" title="Nose Up (W / ↑)">
              <span>▲ Nose Up</span>
              <kbd>W / ↑</kbd>
            </button>
            <button class="ctrl-btn" data-axis="elevator" data-dir="1" title="Nose Down (S / ↓)">
              <span>▼ Nose Down</span>
              <kbd>S / ↓</kbd>
            </button>
          </div>
        </div>

        <!-- Roll -->
        <div class="axis-group">
          <div class="axis-visual">
            <svg class="motion-svg" viewBox="0 0 44 44" aria-hidden="true">
              <path d="M12 13 A 16 16 0 0 1 32 13" fill="none" stroke="#375549" stroke-width="1.5" stroke-dasharray="2 2" />
              <polygon points="9,14 14,10 14,16" fill="#78b794" />
              <polygon points="35,14 30,16 30,10" fill="#78b794" />
              <g id="planeRearGroup" style="transform-origin: 22px 22px; transition: transform 0.08s ease-out;">
                <path d="M5 22 L18 21 L20 13 L24 13 L26 21 L39 22 L39 24 L26 23 L25 26 L22 27 L19 26 L18 23 L5 24 Z" fill="#95d6ad" />
                <circle cx="22" cy="22" r="3" fill="#13201d" stroke="#95d6ad" stroke-width="1.5" />
              </g>
            </svg>
            <div class="axis-meta">
              <span class="axis-title">ROLL (Aileron)</span>
              <span class="axis-desc">Bank Left / Right</span>
            </div>
          </div>
          <div class="axis-btns">
            <button class="ctrl-btn" data-axis="aileron" data-dir="-1" title="Bank Left (A / ←)">
              <span>◄ Bank Left</span>
              <kbd>A / ←</kbd>
            </button>
            <button class="ctrl-btn" data-axis="aileron" data-dir="1" title="Bank Right (D / →)">
              <span>► Bank Right</span>
              <kbd>D / →</kbd>
            </button>
          </div>
        </div>

        <!-- Yaw -->
        <div class="axis-group">
          <div class="axis-visual">
            <svg class="motion-svg" viewBox="0 0 44 44" aria-hidden="true">
              <path d="M10 11 A 18 18 0 0 1 34 11" fill="none" stroke="#375549" stroke-width="1.5" stroke-dasharray="2 2" />
              <polygon points="8,13 13,8 14,14" fill="#78b794" />
              <polygon points="36,13 30,14 31,8" fill="#78b794" />
              <g id="planeTopGroup" style="transform-origin: 22px 22px; transition: transform 0.08s ease-out;">
                <path d="M22 6 L24 16 L38 24 L38 27 L24 23 L24 34 L29 38 L29 40 L22 38 L15 40 L15 38 L20 34 L20 23 L6 27 L6 24 L20 16 Z" fill="#95d6ad" />
              </g>
            </svg>
            <div class="axis-meta">
              <span class="axis-title">YAW (Rudder)</span>
              <span class="axis-desc">Nose Left / Right</span>
            </div>
          </div>
          <div class="axis-btns">
            <button class="ctrl-btn" data-axis="rudder" data-dir="1" title="Yaw Left (Key Q)">
              <span>↶ Yaw Left</span>
              <kbd>Q</kbd>
            </button>
            <button class="ctrl-btn" data-axis="rudder" data-dir="-1" title="Yaw Right (Key E)">
              <span>↷ Yaw Right</span>
              <kbd>E</kbd>
            </button>
          </div>
        </div>

        <!-- Throttle & Reset -->
        <div class="axis-group">
          <div class="throttle-row">
            <span class="axis-title">THROTTLE</span>
            <div class="axis-btns sm">
              <button class="ctrl-btn" data-axis="throttle" data-dir="-1" title="Throttle Down (Key F)">
                <span>➖ Down</span>
                <kbd>F</kbd>
              </button>
              <button class="ctrl-btn" data-axis="throttle" data-dir="1" title="Throttle Up (Key R)">
                <span>➕ Up</span>
                <kbd>R</kbd>
              </button>
            </div>
          </div>
          <button class="center-btn" id="centerSurfacesBtn" title="Reset controls to stable flight trim (Key C / X)">
            <span>⟲ Reset Control Surfaces to Trim</span>
            <kbd>C</kbd>
          </button>
        </div>
      </section>
      <footer class="model-credit">FlightBench: MIT License<br>Aircraft visual: <a href="https://poly.pizza/m/7cvx6ex-xfL" target="_blank" rel="noopener noreferrer">Small Airplane</a> by Vojtěch Balák · <a href="https://creativecommons.org/licenses/by/3.0/" target="_blank" rel="noopener noreferrer">CC BY 3.0</a></footer>
    </aside>
  </main>

  <!-- Floating Error Banner -->
  <div class="error-banner" id="errorBanner" role="alert"></div>

  <!-- Native Dialog Modals -->
  <!-- 1. Raw Input Payload Modal -->
  <dialog class="fb-modal" id="rawInputModal" aria-label="Controller input">
    <div class="modal-card wide">
      <div class="modal-header">
        <span class="modal-title"><span>{ }</span> Raw input sent to controller</span>
        <button class="modal-close-btn" aria-label="Close dialog" data-close="rawInputModal">✕</button>
      </div>
      <div class="modal-body">
        <pre class="modal-code-block" id="rawInputCodeBlock">// Waiting for decision input...</pre>
      </div>
      <div class="modal-footer">
        <button class="btn-secondary" id="copyRawInputBtn">Copy JSON</button>
        <button class="btn-primary" data-close="rawInputModal">Close</button>
      </div>
    </div>
  </dialog>

  <!-- 2. All 81 Options Modal -->
  <dialog class="fb-modal" id="allOptionsModal" aria-label="Legal action candidates">
    <div class="modal-card wide">
      <div class="modal-header">
        <span class="modal-title" id="allOptionsModalTitle"><span>☰</span> Legal Joint Action Candidates</span>
        <button class="modal-close-btn" aria-label="Close dialog" data-close="allOptionsModal">✕</button>
      </div>
      <div class="modal-body options-table-container">
        <table class="options-table">
          <thead>
            <tr>
              <th>Compact ID</th>
              <th>Aileron Δ</th>
              <th>Elevator Δ</th>
              <th>Rudder Δ</th>
              <th>Throttle Δ</th>
              <th>Probability</th>
            </tr>
          </thead>
          <tbody id="allOptionsTableBody">
            <!-- 81 rows rendered dynamically -->
          </tbody>
        </table>
      </div>
      <div class="modal-footer">
        <button class="btn-primary" data-close="allOptionsModal">Close</button>
      </div>
    </div>
  </dialog>

  <!-- 3. Full History Modal -->
  <dialog class="fb-modal" id="fullHistoryModal" aria-label="Decision history">
    <div class="modal-card wide">
      <div class="modal-header">
        <span class="modal-title"><span>⏱</span> Complete Decision History Log</span>
        <button class="modal-close-btn" aria-label="Close dialog" data-close="fullHistoryModal">✕</button>
      </div>
      <div class="modal-body options-table-container">
        <table class="history-table">
          <thead>
            <tr>
              <th>Step</th>
              <th>Sim Time</th>
              <th>Action ID</th>
              <th>Confidence</th>
              <th>Latency</th>
              <th>Observed response</th>
            </tr>
          </thead>
          <tbody id="fullHistoryTableBody">
            <!-- Full history rows -->
          </tbody>
        </table>
      </div>
      <div class="modal-footer">
        <button class="btn-primary" data-close="fullHistoryModal">Close</button>
      </div>
    </div>
  </dialog>

  <!-- 4. Benchmark Outcome Modal -->
  <dialog class="fb-modal" id="outcomeModal" aria-labelledby="outcomeTitle">
    <div class="modal-card outcome-modal-card" id="outcomeCard">
      <div class="outcome-icon" id="outcomeIcon">🛬</div>
      <h2 class="outcome-title" id="outcomeTitle">SAFE LANDING</h2>
      <p class="outcome-desc" id="outcomeDesc">Aircraft established touchdown within safety envelopes.</p>
      <div id="raceStandings" class="race-standings" hidden></div>
      <div class="outcome-stats-grid" id="outcomeStats">
        <div class="outcome-stat">
          <span class="outcome-stat-label">FINAL SCORE</span>
          <span class="outcome-stat-val" id="outcomeScoreVal">—</span>
        </div>
        <div class="outcome-stat">
          <span class="outcome-stat-label">TOUCHDOWN IAS</span>
          <span class="outcome-stat-val" id="outcomeIasVal">—</span>
        </div>
        <div class="outcome-stat">
          <span class="outcome-stat-label">SINK RATE (V/S)</span>
          <span class="outcome-stat-val" id="outcomeVsiVal">—</span>
        </div>
        <div class="outcome-stat">
          <span class="outcome-stat-label">X-TRACK OFFSET</span>
          <span class="outcome-stat-val" id="outcomeXtrackVal">—</span>
        </div>
        <div class="outcome-stat">
          <span class="outcome-stat-label">TOUCHDOWN PITCH</span>
          <span class="outcome-stat-val" id="outcomePitchVal">—</span>
        </div>
        <div class="outcome-stat">
          <span class="outcome-stat-label">TOUCHDOWN ROLL</span>
          <span class="outcome-stat-val" id="outcomeRollVal">—</span>
        </div>
      </div>
      <div style="display: flex; gap: 10px; width: 100%; justify-content: center; margin-top: 6px;">
        <button class="btn-secondary" data-close="outcomeModal">Close result</button>
        <button class="btn-primary" id="outcomeRestartBtn">Start Next Run</button>
      </div>
    </div>
  </dialog>
`;

const byId = <T extends HTMLElement>(id: string) => document.querySelector<T>(`#${id}`)!;
setupInstrumentHelp();
const canvas = byId<HTMLCanvasElement>("viewport");

// Initialize Three.js Scene
let renderer: THREE.WebGLRenderer | null = null;
try {
  renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.setSize(canvas.clientWidth || innerWidth, canvas.clientHeight || innerHeight);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
} catch {
  canvas.hidden = true;
  byId("renderUnavailable").hidden = false;
}

const scene = new THREE.Scene();
const skyCanvas = document.createElement("canvas");
skyCanvas.width = skyCanvas.height = 512;
const skyContext = skyCanvas.getContext("2d")!;
const skyGradient = skyContext.createLinearGradient(0, 0, 0, 512);
skyGradient.addColorStop(0, "#43495e");
skyGradient.addColorStop(0.55, "#9b7078");
skyGradient.addColorStop(1, "#c88972");
skyContext.fillStyle = skyGradient;
skyContext.fillRect(0, 0, 512, 512);
const sunsetGlow = skyContext.createRadialGradient(580, 260, 0, 580, 260, 350);
sunsetGlow.addColorStop(0, "rgba(255, 187, 115, 0.65)");
sunsetGlow.addColorStop(1, "rgba(255, 187, 115, 0)");
skyContext.fillStyle = sunsetGlow;
skyContext.fillRect(0, 0, 512, 512);
const skyTexture = new THREE.CanvasTexture(skyCanvas);
skyTexture.colorSpace = THREE.SRGBColorSpace;
scene.background = skyTexture;
scene.fog = new THREE.Fog(0x9b7078, 700, 3400);
scene.add(new THREE.HemisphereLight(0xd6a7a3, 0x423039, 1.15));
const sun = new THREE.DirectionalLight(0xffbd78, 2.8);
const sunOffset = new THREE.Vector3(-60, 40, 50);
sun.castShadow = true;
sun.shadow.mapSize.set(1024, 1024);
sun.shadow.camera.left = -15;
sun.shadow.camera.right = 15;
sun.shadow.camera.top = 15;
sun.shadow.camera.bottom = -15;
sun.shadow.camera.near = 0.5;
sun.shadow.camera.far = 140;
sun.shadow.camera.updateProjectionMatrix();
sun.shadow.normalBias = 0.1;
scene.add(sun);

// Ground & Runway
const ground = new THREE.Mesh(
  new THREE.PlaneGeometry(8000, 8000),
  new THREE.MeshStandardMaterial({ color: 0x595052, roughness: 1 }),
);
ground.rotation.x = -Math.PI / 2;
ground.receiveShadow = true;
scene.add(ground);

const runway = new THREE.Mesh(
  new THREE.PlaneGeometry(1000, 40),
  new THREE.MeshStandardMaterial({
    color: 0x282632, roughness: 0.92,
    polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1,
  }),
);
runway.rotation.x = -Math.PI / 2;
runway.position.set(500, 0.035, 0);
runway.receiveShadow = true;
scene.add(runway);

const markings = new THREE.Group();
const markingMaterial = new THREE.MeshBasicMaterial({
  color: 0xf4ead7,
  polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2,
});
const centerlineMaterial = markingMaterial.clone();
centerlineMaterial.color.setHex(0xe8e2d0);
for (let x = 25; x < 1000; x += 50) {
  const line = new THREE.Mesh(
    new THREE.PlaneGeometry(18, 0.65),
    centerlineMaterial,
  );
  line.rotation.x = -Math.PI / 2;
  line.position.set(x, 0.055, 0);
  markings.add(line);
}
for (const z of [-19.5, 19.5]) {
  const edge = new THREE.Mesh(
    new THREE.PlaneGeometry(1000, 0.35),
    markingMaterial,
  );
  edge.rotation.x = -Math.PI / 2;
  edge.position.set(500, 0.06, z);
  markings.add(edge);
}
for (const z of [-14, -10, -6, -2, 2, 6, 10, 14]) {
  const threshold = new THREE.Mesh(
    new THREE.PlaneGeometry(20, 1.2),
    markingMaterial,
  );
  threshold.rotation.x = -Math.PI / 2;
  threshold.position.set(12, 0.061, z);
  markings.add(threshold);
}
scene.add(markings);
const windsock = createWindsock();
scene.add(windsock.object);

const edgeLightPositions: number[] = [];
// Twenty rows make the four-row cadence wrap without a double-lit pause.
for (let x = 25; x < 1000; x += 50) {
  for (const z of [-21, 21]) edgeLightPositions.push(x, 0.3, z);
}
const edgeLightGeometry = new THREE.BufferGeometry();
edgeLightGeometry.setAttribute("position", new THREE.Float32BufferAttribute(edgeLightPositions, 3));
const edgeLightColors = new Float32Array(edgeLightPositions.length);
const edgeLightColorAttribute = new THREE.BufferAttribute(edgeLightColors, 3);
edgeLightColorAttribute.setUsage(THREE.DynamicDrawUsage);
edgeLightGeometry.setAttribute("color", edgeLightColorAttribute);
scene.add(new THREE.Points(edgeLightGeometry, new THREE.PointsMaterial({
  vertexColors: true, size: 4, sizeAttenuation: false, depthWrite: false, toneMapped: false,
})));
const litEdgeColor = new THREE.Color(0xffe9b5);
const darkEdgeColor = new THREE.Color(0x101d23);
const edgeLightRows = edgeLightPositions.length / (2 * 3);
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
let edgeLightStart = -1;
let lastEdgeLightStep = Number.NaN;
function updateEdgeLights(now: number) {
  if (edgeLightStart < 0) edgeLightStart = now;
  const step = reducedMotion.matches ? -1 : Math.floor((now - edgeLightStart) / 300) % edgeLightRows;
  if (step === lastEdgeLightStep) return;
  lastEdgeLightStep = step;
  for (let row = 0; row < edgeLightRows; row++) {
    const color = step < 0 || isRunwayLightOn(row, step) ? litEdgeColor : darkEdgeColor;
    color.toArray(edgeLightColors, row * 6);
    color.toArray(edgeLightColors, row * 6 + 3);
  }
  edgeLightColorAttribute.needsUpdate = true;
}

// Aircraft Object
const aircraft = new THREE.Group();
aircraft.name = "aircraftRoot";
aircraft.position.set(-1500, 94, 0);
scene.add(aircraft);
sun.target = aircraft;

const aircraftVisualRoot = new THREE.Group();
aircraftVisualRoot.name = "aircraftVisualRoot";
aircraftVisualRoot.rotation.y = -Math.PI / 2;
aircraftVisualRoot.position.x = 2.35;
aircraft.add(aircraftVisualRoot);

function loadAircraft() {
  const loader = new GLTFLoader();
  loader.load(
    `${import.meta.env.BASE_URL}models/aircraft.glb`,
    (gltf) => {
      gltf.scene.name = "aircraftGLB";
      gltf.scene.traverse((object) => {
        if (object instanceof THREE.Mesh) {
          object.castShadow = true;
          object.receiveShadow = true;
        }
      });
      aircraftVisualRoot.add(gltf.scene);
      aircraft.userData.propeller = gltf.scene.getObjectByName("Propeller_Cone");
    },
    undefined,
    () => showError("Aircraft 3D model could not be loaded"),
  );
}
loadAircraft();

// Camera setup
const initialAspect = (canvas.clientWidth || innerWidth) / (canvas.clientHeight || innerHeight);
const camera = new THREE.PerspectiveCamera(52, initialAspect, 0.5, 5000);
camera.position.copy(aircraft.position).add(new THREE.Vector3(-14, 3.8, 0));
const orbit = new OrbitControls(camera, canvas);
orbit.enableDamping = true;
orbit.enabled = false;
orbit.minDistance = 6;
orbit.maxDistance = 120;
orbit.target.copy(aircraft.position);

let cameraMode: "chase" | "orbit" | "tower" = "chase";
// Session-only storage avoids replaying trajectories across simulator upgrades.
const ghostRuns: Ghost[] = [];
let raceTime = 0;
let replayTime = 0;
let renderRaceTime = 0;
let startCameraUntil = 0;
let startViewPending = false;
let liveJevAvailable = false;
type LiveOpponent = {runId: string | null; run: Ghost; label: string; state: StateMessage | null; renderTime: number};
const liveOpponents = new Map<string, LiveOpponent>();
const liveEntry = (run: Ghost | null) => [...liveOpponents.values()].find(entry => entry.run === run);
const liveRunning = () => [...liveOpponents.values()].some(entry => entry.runId);

let watchedGhost: Ghost | null = null;
let spectatorRunning = false;
let primaryResult: RunRecord | null = null;
let dismissingRace = false;
let resettingRace = false;
const ghostRecords = new WeakMap<Ghost, RunRecord>();
const primaryResultButton = document.createElement("button");
primaryResultButton.className = "btn-secondary race-result-button";
primaryResultButton.textContent = "Your result";
primaryResultButton.hidden = true;
primaryResultButton.addEventListener("click", () => { if (primaryResult) showOutcomeModal(primaryResult, "Your flight"); });
document.querySelector("#viewport")!.parentElement!.append(primaryResultButton);
const selectedGhosts = new Set<string>();
const ghostLegend = document.createElement("div");
ghostLegend.id = "ghostLegend"; ghostLegend.hidden = true;
document.querySelector("#viewport")!.parentElement!.append(ghostLegend);
let ghostKey = "";
let recordingController = "";
let ghostSamples: Sample[] = [];
let activeGhosts: { run: Ghost; visual: THREE.Group; label: string; marker: HTMLDivElement; color: number }[] = [];
function clearGhosts() {
  for (const { visual, marker } of activeGhosts) {
    marker.remove();
    scene.remove(visual);
    visual.traverse(object => {
      if (object instanceof THREE.Mesh) {
        for (const material of Array.isArray(object.material) ? object.material : [object.material]) material.dispose();
      }
    });
  }
  activeGhosts = [];
  ghostLegend.hidden = true; ghostLegend.replaceChildren();
}
function ghostSetupKey(config?: RunConfig): string {
  return JSON.stringify([pagesRuntime, config?.scenario ?? byId<HTMLSelectElement>("scenario").value,
    config?.mode ?? (["jev", "codex"].includes(controllerSelect.value) ? byId<HTMLSelectElement>("timingMode").value : "realtime"), config?.decision_hz ?? 2]);
}
function ghostTitle(choice: string): string {
  if (choice.startsWith("live:")) return choice === "live:baseline" ? "Live baseline" : `Live Jev ${choice.slice(9).replace(".0", "")}`;
  return choice === "human" ? "Personal best" : choice === "jev" ? "Jev replay" : "Previous flight";
}
function raceAccent(element: HTMLElement, color: number): void {
  element.style.setProperty("--racer-color", `#${color.toString(16).padStart(6, "0")}`);
}
function choiceContent(kind: string, title: string, detail: string): DocumentFragment {
  const paths: Record<string, string> = {
    human: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8M5 21v-2a7 7 0 0 1 14 0v2",
    baseline: "M4 8h16M4 16h16M8 4v8m8 0v8",
    jev: "m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5Z",
    codex: "m8 6-6 6 6 6m8-12 6 6-6 6m-3-15-2 18",
    replay: "M4 10a8 8 0 1 1 1 8M4 4v6h6m2-3v5l3 2",
  };
  const content = document.createDocumentFragment();
  const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  icon.setAttribute("viewBox", "0 0 24 24"); icon.setAttribute("aria-hidden", "true");
  icon.classList.add("choice-icon");
  const path = document.createElementNS(icon.namespaceURI, "path");
  path.setAttribute("d", paths[kind] ?? paths.replay); icon.append(path);
  const text = document.createElement("span"); text.className = "choice-copy";
  const name = document.createElement("strong"); name.textContent = title;
  const description = document.createElement("small"); description.textContent = detail;
  text.append(name, description); content.append(icon, text);
  return content;
}
function refreshGhostStatus() {
  const host = byId("ghostChoices");
  const primary = controllerSelect?.value === "jev" ? jevModelSelect.value : controllerSelect?.value;
  const live = ["baseline", ...(liveJevAvailable || pagesRuntime ? ["jev-1.13.0", "jev-1.14.0"] : [])]
    .filter(id => id !== primary).map(id => `live:${id}`);
  const available = [...["previous", "human", "jev"].filter(choice => Boolean(selectGhost(ghostRuns, ghostSetupKey(), choice))), ...live];
  for (const choice of selectedGhosts) if (!available.includes(choice)) selectedGhosts.delete(choice);
  host.replaceChildren();
  let jevVersions: HTMLDivElement | null = null;
  for (const choice of available) {
    const run = choice.startsWith("live:") ? null : selectGhost(ghostRuns, ghostSetupKey(), choice);
    const label = document.createElement("label"); label.className = "opponent-card";
    raceAccent(label, racerColor(choice.startsWith("live:") ? choice.slice(5) : `replay:${choice}`));
    const input = document.createElement("input"); input.type = "checkbox"; input.value = choice;
    input.checked = selectedGhosts.has(choice); input.setAttribute("aria-label", ghostTitle(choice));
    input.addEventListener("change", () => {
      if (input.checked) selectedGhosts.add(choice); else selectedGhosts.delete(choice);
      byId("ghostStatus").textContent = selectedGhosts.size ? `${selectedGhosts.size} opponent(s) selected` : "Solo flight · replay recording on";
    });
    if (choice.startsWith("live:jev")) {
      if (!jevVersions) {
        const group = document.createElement("div"); group.className = "opponent-model-group";
        group.append(choiceContent("jev", "Jev", "Live · API usage"));
        jevVersions = document.createElement("div"); jevVersions.className = "version-choices";
        jevVersions.setAttribute("role", "group"); jevVersions.setAttribute("aria-label", "Live Jev opponents");
        group.append(jevVersions); host.append(group);
      }
      label.className = "version-badge";
      const version = document.createElement("span"); version.textContent = choice.slice(9).replace(".0", "");
      label.append(input, version); jevVersions.append(label);
    } else {
      const detail = run ? `${run.score.toFixed(1)} pts · ${outcomeLabel(run.status, run.success)}` : "Live · no API usage";
      label.title = run ? `${run.samples.at(-1)!.time.toFixed(1)} s · ${detail}` : "Independent rule-based pilot";
      label.append(input, choiceContent(choice === "live:baseline" ? "baseline" : "replay",
        choice === "live:baseline" ? "Baseline" : ghostTitle(choice), detail));
      host.append(label);
    }
  }
  byId("ghostStatus").textContent = selectedGhosts.size ? `${selectedGhosts.size} opponent(s) selected` : "Solo flight · replay recording on";
}
function createGhostVisual(color: number): THREE.Group {
    const visual = aircraft.clone(true);
    visual.traverse(object => {
      if (object instanceof THREE.Mesh) {
        const clone = (material: THREE.Material) => ghostMaterial(material, color);
        object.material = Array.isArray(object.material) ? object.material.map(clone) : clone(object.material);
        object.castShadow = false; object.receiveShadow = false;
      }
    });
    return visual;
}
function startGhosts(config: RunConfig) {
  clearGhosts();
  ghostSamples = []; raceTime = 0; replayTime = 0; renderRaceTime = 0; liveOpponents.clear(); watchedGhost = null; spectatorRunning = false;
  primaryResult = null; primaryResultButton.hidden = true; dismissingRace = false; resettingRace = false;
  recordingController = String(config.controller);
  ghostKey = ghostSetupKey(config);
  for (const choice of selectedGhosts) {
    if (choice.startsWith("live:")) continue;
    const run = selectGhost(ghostRuns, ghostKey, choice);
    if (!run || activeGhosts.some(ghost => ghost.run === run)) continue;
    const color = racerColor(`replay:${choice}`);
    const label = ghostTitle(choice);
    const visual = createGhostVisual(color);
    visual.visible = false;
    const marker = document.createElement("div");
    marker.className = "ghost-marker"; raceAccent(marker, color);
    marker.textContent = label;
    ghostLegend.parentElement!.append(marker);
    scene.add(visual); activeGhosts.push({ run, visual, label, marker, color });
  }
  refreshGhostStatus();
  ghostLegend.hidden = activeGhosts.length === 0;
}
const desiredPosition = aircraft.position.clone();
const desiredQuaternion = aircraft.quaternion.clone();
const lastOrbitTarget = aircraft.position.clone();
const lastChaseTarget = aircraft.position.clone();

// Camera offset tuning: chase camera behind and slightly above aircraft, looking slightly down and forward at runway
const chaseOffset = new THREE.Vector3(-14, 3.8, 0);
const chaseLookAtOffset = new THREE.Vector3(12, -0.6, 0);

// Human Controls & Assist
const controls: Control = defaultControls();
const pressed = new Set<string>();
const boundKeys = new Set([
  "KeyW", "KeyS", "KeyA", "KeyD", "KeyQ", "KeyE", "KeyR", "KeyF", "KeyC", "KeyX",
  "Digit1", "Digit2", "Digit3",
]);
let autoCenterEnabled = true;
let wingLevelerEnabled = false;
let lastKnownRollDeg = 0;
let lastObservation: Observation | null = null;

// Actuator rows setup in sidebar
const actuatorList = byId("actuatorRows");
actuatorList.innerHTML = (["aileron", "elevator", "rudder", "throttle"] as const)
  .map((name) => `
    <div class="actuator-row" id="actuatorRow_${name}">
      <div class="actuator-top-line">
        <span class="actuator-name">${name}</span>
        <span class="actuator-meta" id="${name}Value">0.000</span>
      </div>
      <div class="actuator-gauge">
        ${name !== "throttle" ? '<div class="actuator-center-line"></div>' : ""}
        <div class="actuator-fill" id="${name}Bar"></div>
      </div>
      <div class="actuator-delta-readout">
        <span id="${name}Delta">Δ —</span>
      </div>
    </div>
  `)
  .join("");

let lastShownControls: Control | null = null;
function showControls(c: Control) {
  for (const name of ["aileron", "elevator", "rudder", "throttle"] as const) {
    const bar = byId(`${name}Bar`);
    const valEl = byId(`${name}Value`);
    const deltaEl = byId(`${name}Delta`);

    if (name === "throttle") {
      bar.style.width = `${Math.max(0, Math.min(100, c[name] * 100))}%`;
      bar.style.left = "0";
    } else {
      const pct = Math.abs(c[name]) * 50;
      bar.style.width = `${pct}%`;
      bar.style.left = c[name] >= 0 ? "50%" : `${50 - pct}%`;
    }
    valEl.textContent = c[name].toFixed(3);
    byId(`overlay${name[0].toUpperCase()}${name.slice(1)}`).textContent = c[name].toFixed(3);
    const delta = lastShownControls ? c[name] - lastShownControls[name] : 0;
    if (Math.abs(delta) >= 0.0005) deltaEl.textContent = `Δ ${delta >= 0 ? "+" : ""}${delta.toFixed(3)}`;
  }
  lastShownControls = { ...c };

  // Visual feedback on SVG silhouettes in manual controls
  const sidePlane = document.getElementById("planeSideGroup");
  if (sidePlane) sidePlane.style.transform = `rotate(${-c.elevator * 22}deg)`;
  const rearPlane = document.getElementById("planeRearGroup");
  if (rearPlane) rearPlane.style.transform = `rotate(${c.aileron * 25}deg)`;
  const topPlane = document.getElementById("planeTopGroup");
  if (topPlane) topPlane.style.transform = `rotate(${c.rudder * 25}deg)`;
}
showControls(controls);

// Keyboard interaction
addEventListener("keydown", (event) => {
  if (event.target instanceof Element && event.target.closest("input, select, textarea, button, summary, dialog")) return;
  const key = humanKey(event.code);
  if (!boundKeys.has(key)) return;
  if (!key.startsWith("Digit") && (runState !== "running" || controllerSelect.value !== "human")) return;
  event.preventDefault();
  if (["Digit1", "Digit2", "Digit3"].includes(key)) {
    setCamera(({ Digit1: "chase", Digit2: "orbit", Digit3: "tower" } as const)[key as "Digit1" | "Digit2" | "Digit3"]);
    return;
  }
  if (key === "KeyC" || key === "KeyX") {
    centerSurfaces(controls);
    showControls(controls);
    if (controllerSelect.value === "human") send({ type: "action", action: controls });
    return;
  }
  if (!event.repeat) {
    if (!autoCenterEnabled) {
      if (key === "KeyW") adjustControl(controls, "elevator", -0.04);
      else if (key === "KeyS") adjustControl(controls, "elevator", 0.04);
      else if (key === "KeyA") adjustControl(controls, "aileron", -0.04);
      else if (key === "KeyD") adjustControl(controls, "aileron", 0.04);
      else if (key === "KeyQ") adjustControl(controls, "rudder", 0.04);
      else if (key === "KeyE") adjustControl(controls, "rudder", -0.04);
    }
    if (key === "KeyR") adjustControl(controls, "throttle", 0.05);
    else if (key === "KeyF") adjustControl(controls, "throttle", -0.05);
    showControls(controls);
    if (controllerSelect.value === "human") send({ type: "action", action: controls });
  }
  pressed.add(event.code);
});
addEventListener("keyup", (event) => pressed.delete(event.code));
addEventListener("blur", () => pressed.clear());
document.addEventListener("visibilitychange", () => { if (document.hidden) pressed.clear(); });

// Interactive Manual Controls
function setupInteractiveControls() {
  const btnKeyMap: Record<string, string> = {
    "elevator:-1": "KeyW",
    "elevator:1": "KeyS",
    "aileron:-1": "KeyA",
    "aileron:1": "KeyD",
    "rudder:1": "KeyQ",
    "rudder:-1": "KeyE",
    "throttle:1": "KeyR",
    "throttle:-1": "KeyF",
  };

  document.querySelectorAll<HTMLButtonElement>(".ctrl-btn").forEach((btn) => {
    const axis = btn.dataset.axis as keyof Control | undefined;
    const dir = Number(btn.dataset.dir || 0);
    if (!axis || !dir) return;

    const mappedKey = btnKeyMap[`${axis}:${dir}`];
    let repeatTimer: number | null = null;
    let intervalTimer: number | null = null;
    let active = false;

    const startAction = (e: Event) => {
      e.preventDefault();
      if (active || runState !== "running" || controllerSelect.value !== "human") return;
      active = true;
      if (mappedKey) pressed.add(mappedKey);

      if (!autoCenterEnabled || axis === "throttle") {
        const delta = axis === "throttle" ? dir * 0.05 : dir * 0.04;
        const continuousDelta = axis === "throttle" ? dir * 0.02 : dir * 0.015;
        adjustControl(controls, axis, delta);
        showControls(controls);
        if (controllerSelect.value === "human") send({ type: "action", action: controls });

        repeatTimer = window.setTimeout(() => {
          intervalTimer = window.setInterval(() => {
            if (runState !== "running" || controllerSelect.value !== "human") { stopAction(); return; }
            adjustControl(controls, axis, continuousDelta);
            showControls(controls);
            if (controllerSelect.value === "human") send({ type: "action", action: controls });
          }, 40);
        }, 220);
      }
    };

    const stopAction = () => {
      active = false;
      if (mappedKey) pressed.delete(mappedKey);
      if (repeatTimer !== null) { clearTimeout(repeatTimer); repeatTimer = null; }
      if (intervalTimer !== null) { clearInterval(intervalTimer); intervalTimer = null; }
    };

    btn.addEventListener("keydown", (event) => {
      if ((event.code === "Space" || event.code === "Enter") && !event.repeat) startAction(event);
    });
    btn.addEventListener("keyup", stopAction);
    btn.addEventListener("blur", stopAction);
    btn.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 || active) return;
      startAction(event);
      if (active) btn.setPointerCapture(event.pointerId);
    });
    btn.addEventListener("pointerup", stopAction);
    btn.addEventListener("pointercancel", stopAction);
    btn.addEventListener("lostpointercapture", stopAction);
    addEventListener("blur", stopAction);
    document.addEventListener("visibilitychange", () => { if (document.hidden) stopAction(); });
  });

  byId("centerSurfacesBtn")?.addEventListener("click", () => {
    centerSurfaces(controls);
    showControls(controls);
    if (controllerSelect.value === "human") send({ type: "action", action: controls });
  });

  byId<HTMLInputElement>("autoCenterToggle")?.addEventListener("change", (e) => {
    autoCenterEnabled = (e.target as HTMLInputElement).checked;
  });
  byId<HTMLInputElement>("wingLevelerToggle")?.addEventListener("change", (e) => {
    wingLevelerEnabled = (e.target as HTMLInputElement).checked;
    updateAssistPill();
  });
}
setupInteractiveControls();

function updateAssistPill() {
  const pill = byId("assistStatusPill");
  if (!pill) return;
  if (!wingLevelerEnabled) {
    pill.textContent = "OFF";
    pill.className = "assist-status-pill disabled";
    return;
  }
  const r = lastObservation?.runway;
  const isHumanSteering =
    [...pressed].some((code) => ["KeyW", "KeyS", "KeyA", "KeyD", "KeyQ", "KeyE"].includes(humanKey(code)));
  if (isHumanSteering) {
    pill.textContent = "MANUAL OVERRIDE";
    pill.className = "assist-status-pill";
    return;
  }
  const xtrack = r?.cross_track_error_m ?? 0;
  if (r && r.altitude_agl_m < 1.5) {
    pill.textContent = "🛬 TOUCHDOWN (IDLE)";
    pill.className = "assist-status-pill active";
  } else if (r && r.altitude_agl_m < 18.0) {
    pill.textContent = "⚡ FLARE PHASE";
    pill.className = "assist-status-pill active";
  } else if (Math.abs(xtrack) > 3.0) {
    pill.textContent = `⚡ TRACKING (${Math.abs(xtrack).toFixed(1)}m)`;
    pill.className = "assist-status-pill active";
  } else {
    pill.textContent = "● ON CENTERLINE";
    pill.className = "assist-status-pill";
  }
}

// Lifecycle belongs to backend acknowledgements, not button clicks.
let runState: RunState = "offline";
let activeRunId: string | null = null;

function transitionRun(event: RunEvent) {
  runState = nextRunState(runState, event);
  const busy = runState === "starting" || runState === "running";
  byId<HTMLFieldSetElement>("experimentSettings").disabled = busy;
  byId<HTMLButtonElement>("configureToggle").disabled = busy;
  byId<HTMLButtonElement>("scenarioToggle").disabled = busy;
  byId<HTMLFieldSetElement>("scenarioSettings").disabled = busy;
  if (busy) {setConfigOpen(false); setScenarioOpen(false);}
  byId<HTMLButtonElement>("start").disabled = busy || runState === "offline";
  byId<HTMLButtonElement>("stop").disabled = runState !== "running" && !liveRunning();
  byId<HTMLButtonElement>("reset").disabled = runState === "starting" || runState === "offline";
  for (const id of ["autoCenterToggle", "wingLevelerToggle"]) byId<HTMLInputElement>(id).disabled = busy;
  const text: Record<RunState, string> = {
    offline: "Disconnected", ready: "Ready", starting: "Initializing controller…",
    running: "In flight", complete: pagesRuntime ? "Completed" : "Saved",
  };
  byId("runStatus").textContent = text[runState];
  byId("flightStatePill").textContent = runState === "running" ? "IN FLIGHT" : runState.toUpperCase();
  byId("flightStatePill").dataset.state = runState;
  pressed.clear();
}

// Dialog Modals Management
function openDialog(id: string) {
  const dlg = byId<HTMLDialogElement>(id);
  if (dlg && !dlg.open) {
    dlg.showModal();
  }
}

function closeDialog(id: string) {
  const dlg = byId<HTMLDialogElement>(id);
  if (dlg && dlg.open) {
    dlg.close();
  }
}

document.querySelectorAll<HTMLElement>("[data-close]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const targetId = btn.getAttribute("data-close");
    if (targetId) closeDialog(targetId);
  });
});

// Close dialog when clicking backdrop
document.querySelectorAll<HTMLDialogElement>("dialog.fb-modal").forEach((dlg) => {
  dlg.addEventListener("click", (e) => {
    const rect = dlg.getBoundingClientRect();
    const isInDialog = (
      rect.top <= e.clientY &&
      e.clientY <= rect.top + rect.height &&
      rect.left <= e.clientX &&
      e.clientX <= rect.left + rect.width
    );
    if (!isInDialog) {
      dlg.close();
    }
  });
});

byId("openRawInputBtn")?.addEventListener("click", () => openDialog("rawInputModal"));
byId("openAllOptionsBtn")?.addEventListener("click", () => openDialog("allOptionsModal"));
byId("openFullHistoryBtn")?.addEventListener("click", () => openDialog("fullHistoryModal"));
byId("toggleMarginalsBtn")?.addEventListener("click", () => {
  const sec = byId("axisMarginalsSection");
  const btn = byId("toggleMarginalsBtn");
  if (sec && btn) {
    const isHidden = sec.classList.toggle("hidden");
    btn.classList.toggle("active", !isHidden);
  }
});

function computeMarginalsFromProbs(probabilities: Record<string, number>): Record<string, { decrease: number; hold: number; increase: number }> {
  const marginals: Record<string, { decrease: number; hold: number; increase: number }> = {
    aileron: { decrease: 0, hold: 0, increase: 0 },
    elevator: { decrease: 0, hold: 0, increase: 0 },
    rudder: { decrease: 0, hold: 0, increase: 0 },
    throttle: { decrease: 0, hold: 0, increase: 0 },
  };

  const symbolMap: Record<string, "decrease" | "hold" | "increase"> = {
    "-": "decrease",
    "0": "hold",
    "+": "increase",
  };

  for (const [key, p] of Object.entries(probabilities)) {
    if (key.length >= 11 && key[0] === "A" && key[3] === "E" && key[6] === "R" && key[9] === "T") {
      const a = symbolMap[key[1]];
      const e = symbolMap[key[4]];
      const r = symbolMap[key[7]];
      const t = symbolMap[key[10]];
      if (a) marginals.aileron[a] += p;
      if (e) marginals.elevator[e] += p;
      if (r) marginals.rudder[r] += p;
      if (t) marginals.throttle[t] += p;
    }
  }

  return marginals;
}
byId("outcomeRestartBtn")?.addEventListener("click", () => {
  closeDialog("outcomeModal");
  byId("start").click();
});
byId("copyRawInputBtn")?.addEventListener("click", () => {
  const code = byId("rawInputCodeBlock").textContent || "";
  navigator.clipboard.writeText(code).then(() => {
    const btn = byId("copyRawInputBtn");
    const orig = btn.textContent;
    btn.textContent = "Copied!";
    setTimeout(() => { btn.textContent = orig; }, 1500);
  }).catch(() => showError("Clipboard unavailable. Select and copy the JSON text manually."));
});

// Decision tracking
let allDecisions: Array<{
  count: number;
  simTime: number;
  id: string;
  confidence: number | null;
  latencyMs: number | null;
  observedText: string;
  info: DecisionInfo;
  stabilityTriggered?: boolean;
}> = [];
let lastDecisionInfo: DecisionInfo | null = null;
let lastDecisionCount = -1;
let lastRenderedDecisionCall = -1;
let lastDetailedDecisionCall = -1;
let lastAxisChoices: Record<string, { choice?: string; label?: string; command: number }> = {};

function formatWindSummary(env?: Observation["environment"]): string {
  if (!env) return "Calm (0.0 m/s)";
  const hw = env.headwind_mps ?? 0;
  const xw = env.crosswind_mps ?? 0;
  const vw = env.vertical_wind_mps ?? 0;
  const spd = env.wind_speed_mps ?? Math.hypot(hw, xw);
  const dir = env.wind_dir_deg ?? (((Math.atan2(-xw, hw) * 180 / Math.PI) % 360 + 360) % 360);
  if (spd < 0.05 && Math.abs(vw) < 0.05) return "Calm (0.0 m/s)";
  const s = (n: number) => `${n >= 0 ? "+" : ""}${n.toFixed(1)}`;
  const vwPart = Math.abs(vw) >= 0.05 ? ` · VW ${s(vw)}` : "";
  return `${spd.toFixed(1)} m/s @ ${dir.toFixed(0)}° (HW ${s(hw)} · XW ${s(xw)}${vwPart})`;
}

function updateLiveDecision(info: DecisionInfo, call: number, latencyMs: number | null) {
  if (call <= lastRenderedDecisionCall || (!info.choices && !info.command)) return;
  lastRenderedDecisionCall = call;
  if (info.controller === "jev" && info.input?.flight && info.input.runway) {
    const { flight, runway, environment, current_controls: controls, motion, status, phase, time_s } = info.input;
    const num = (value: number | undefined, digits = 1) => value == null ? "—" : value.toFixed(digits);
    const signed = (value: number | undefined, digits = 1) => value == null ? "—" : `${value >= 0 ? "+" : ""}${value.toFixed(digits)}`;
    byId("decisionInputTime").textContent = `${phase ?? "—"} · t=${num(time_s)}s`;
    byId("decisionInputFlight").textContent = `IAS ${num(flight.airspeed_mps)} · V/S ${signed(flight.vertical_speed_mps)} · Roll ${signed(flight.roll_deg)}° · Pitch ${signed(flight.pitch_deg)}°`;
    byId("decisionInputRunway").textContent = `AGL ${num(runway.altitude_agl_m)}m · Offset ${signed(runway.centerline_offset_m ?? runway.cross_track_error_m)}m · Glide ${signed(runway.glideslope_error_deg)}° · Hdg ${signed(runway.heading_error_deg)}°`;
    byId("decisionInputWind").textContent = formatWindSummary(environment ?? lastObservation?.environment);
    byId("decisionInputControls").textContent = `A ${num(controls?.aileron, 2)} · E ${num(controls?.elevator, 2)} · R ${num(controls?.rudder, 2)} · T ${num(controls?.throttle, 2)}`;
    byId("decisionInputMotion").textContent = `Drift ${signed(motion?.cross_track_rate_mps)} m/s · ${status?.on_ground ? "ON GROUND" : "AIRBORNE"}`;
  }
  const applied = info.timing?.applied !== false;
  const state = applied ? "APPLIED" : "DISCARDED";
  byId("decisionState").textContent = state;
  byId("decisionState").dataset.state = state.toLowerCase();
  byId("decisionSequence").textContent = `#${call}`;
  byId("decisionLatency").textContent = latencyMs == null ? "— ms" : `${latencyMs.toFixed(0)} ms`;
  byId("overlayDecisionStatus").textContent = `DECISION #${call} · ${state}`;
  const values: string[] = [];
  for (const axis of ["aileron", "elevator", "rudder", "throttle"] as const) {
    const choice = info.choices?.[axis];
    const value = choice?.command ?? info.command?.[axis];
    const short = { aileron: "A", elevator: "E", rudder: "R", throttle: "T" }[axis];
    values.push(`${short} ${value == null ? "—" : value.toFixed(2)}`);
    const key = `decision${axis[0].toUpperCase()}${axis.slice(1)}`;
    const field = byId(key);
    const intent = choice?.label?.replace(/^Only with bank[^:]+:\s*/, "").split(/[:,;]| at | for | during /)[0] ?? "selected";
    field.textContent = value == null ? "—" : choice ? intent : "Command";
    field.title = choice?.label ?? "Controller command";
    byId(`${key}Value`).textContent = value == null ? "—" : value.toFixed(3);
    const previous = lastAxisChoices[axis];
    const changed = previous != null && (previous.command !== value || previous.choice !== choice?.choice || previous.label !== choice?.label);
    const change = byId(`${key}Change`);
    change.textContent = !previous ? "FIRST" : !changed ? "SAME" : `CHANGED ${value == null ? "" : `${value - previous.command >= 0 ? "+" : ""}${(value - previous.command).toFixed(3)}`}`;
    change.dataset.change = !previous ? "first" : changed ? "changed" : "same";
    const index = Number(choice?.choice);
    const count = axis === "elevator" ? 10 : 7;
    const position = choice && Number.isInteger(index) && index >= 0 && index < count
      ? index / (count - 1) : axis === "throttle" ? value ?? 0 : ((value ?? 0) + 1) / 2;
    byId(`${key}Marker`).style.left = `${Math.max(0, Math.min(100, position * 100))}%`;
    if (value != null) lastAxisChoices[axis] = { choice: choice?.choice, label: choice?.label, command: value };
  }
  byId("overlayDecisionText").textContent = values.join("  /  ");
}

function updateDecisionCards(info: DecisionInfo | null | undefined, decisionCount: number, latencyMs: number | null) {
  if (!info) return;
  lastDecisionInfo = info;
  if (info.live_status && performance.now() - lastMetricUpdate >= 5000) {
    displayedRate = `${(info.live_status.effective_decision_hz ?? 0).toFixed(1)} Hz`;
    displayedMeanLatency = info.live_status.avg_latency_ms == null ? "— ms" : `${info.live_status.avg_latency_ms.toFixed(0)} ms`;
    lastMetricUpdate = performance.now();
    updateTimingLabels();
  }

  // Header / Identity
  const brandTitle = byId("ctrlBrandTitle");
  const modelTag = byId("ctrlModelTag");
  if (brandTitle) {
    if (info.controller === "jev" || info.controller === "jev-micro") brandTitle.textContent = info.controller === "jev-micro" ? "TypeSafe Jev Micro" : "TypeSafe Jev";
    else if (info.controller === "codex") brandTitle.textContent = "Codex Controller";
  }
  if (modelTag) {
    if (info.model) modelTag.textContent = info.model;
  }

  if (info.live_status) {
    const s = info.live_status;
    byId("chipLatency").querySelector("strong")!.textContent = `${s.latency_ms != null ? s.latency_ms.toFixed(0) : (latencyMs != null ? latencyMs.toFixed(0) : "—")} ms`;
    byId("chipStateAge").querySelector("strong")!.textContent = `${s.state_age_ms != null ? s.state_age_ms.toFixed(0) : "—"} ms`;
  } else if (latencyMs != null) {
    byId("chipLatency").querySelector("strong")!.textContent = `${latencyMs.toFixed(0)} ms`;
  }
  byId("chipDecisionNum").querySelector("strong")!.textContent = `#${decisionCount}`;
  const call = info.live_status?.calls ?? decisionCount;
  updateLiveDecision(info, call, latencyMs);
  if (call === lastDetailedDecisionCall) return;
  lastDetailedDecisionCall = call;

  // Raw Input payload modal update
  if (info.input) {
    byId("rawInputCodeBlock").textContent = JSON.stringify(info.input, null, 2);
  }

  if ((info.policy === "direct-categorical" && info.choices) || (info.controller === "codex" && info.command)) {
    const isJev = info.controller === "jev";
    document.querySelector<HTMLElement>("#jointDecisionCard .ctrl-card-title")!.textContent = isJev ? "Jev actuator decisions" : "Codex actuator decisions";
    byId("jointCodePill").textContent = isJev ? Object.values(info.choices!).map(c => c.choice).join(" / ") : "4 controls";
    byId("jointConfidenceBadge").textContent = isJev ? "4 independent choices · 1 model request" : "Validated structured response";
    byId("jointSourceBadge").textContent = isJev ? "JEV MODEL" : "CODEX MODEL";
    byId("jointStabilityBadge").style.display = "none";
    byId("actionCount").textContent = "4 axes";
    byId("axisMarginalsSection").style.display = "none";
    byId("openAllOptionsBtn").style.display = "none";
    byId("toggleMarginalsBtn").style.display = "none";
    byId("jointDecisionCard").dataset.kind = "direct";
    for (const id of ["consequenceCard", "decisionHistoryCard"]) byId(id).style.display = "none";
    const input = info.input;
    const measurements: [string, string][] = input ? [
      ["Phase / time", `${input.phase ?? "—"} · ${(input.time_s ?? 0).toFixed(1)} s`],
      ["Airspeed", `${input.flight?.airspeed_mps?.toFixed(1) ?? "—"} m/s`],
      ["Altitude AGL", `${input.runway?.altitude_agl_m?.toFixed(1) ?? "—"} m`],
      ["Centerline", `${(input.runway?.centerline_offset_m ?? input.runway?.cross_track_error_m)?.toFixed(1) ?? "—"} m`],
      ["Wind", formatWindSummary(input.environment)],
    ] : [["Input", "Waiting for a model request"]];
    byId("inputSummaryGrid").replaceChildren(...measurements.map(([label, value]) => {
      const row = document.createElement("div"); row.className = "diagnostic-measurement";
      const key = document.createElement("span"); key.textContent = label;
      const text = document.createElement("strong"); text.textContent = value;
      row.append(key, text); return row;
    }));
    const commands = info.command || Object.fromEntries(Object.entries(info.choices!).map(([axis, choice]) => [axis, choice.command!]));
    byId("topProbBars").replaceChildren(...Object.entries(commands).map(([axis, command]) => {
      const choice = info.choices?.[axis];
      const row = document.createElement("article"); row.className = "diagnostic-choice";
      const header = document.createElement("header");
      const title = document.createElement("strong"); title.textContent = axis;
      const value = document.createElement("strong"); value.textContent = command.toFixed(3);
      header.append(title, value);
      const status = document.createElement("span"); status.className = "diagnostic-application";
      status.textContent = info.timing?.applied === false ? "Not applied · stale reply" : info.timing?.applied === true ? "Applied" : "Requested";
      const criterion = document.createElement("p"); criterion.textContent = choice?.label ?? "Validated model command";
      const detail = document.createElement("small");
      detail.textContent = [choice?.choice != null ? `Action ${choice.choice}` : "Structured output",
        choice?.confidence != null ? `${(choice.confidence * 100).toFixed(0)}% confidence` : ""].filter(Boolean).join(" · ");
      row.append(header, status, criterion, detail); return row;
    }));
    return;
  }

  // Current Joint Action & Probabilities
  const jointChoice = info.choices?.joint_action;
  if (jointChoice) {
    const isMicro = info.controller === "jev-micro";
    const title = document.querySelector<HTMLElement>("#jointDecisionCard .ctrl-card-title");
    if (title) title.textContent = isMicro ? "Current Micro Decision" : "Current Joint Action";
    const marginalSection = byId<HTMLElement>("axisMarginalsSection");
    if (marginalSection) marginalSection.style.display = isMicro ? "none" : "block";
    const allOptionsButton = byId<HTMLElement>("openAllOptionsBtn");
    if (allOptionsButton) allOptionsButton.textContent = isMicro ? "View 9 Actions" : "View All Options";
    const compactId = jointChoice.id || (typeof jointChoice.action === "string" ? jointChoice.action : "A0_E0_R0_T0");
    byId("jointCodePill").textContent = compactId;
    const confPct = jointChoice.confidence != null ? `${(jointChoice.confidence * 100).toFixed(0)}%` : "—%";
    const microAction = isMicro ? jointChoice.last_micro_action : null;
    byId("jointConfidenceBadge").textContent = microAction
      ? `${microAction.axis} ${microAction.delta >= 0 ? "+" : ""}${microAction.delta.toFixed(4)}`
      : `Confidence ${confPct}`;
    const sourceBadge = byId("jointSourceBadge");
    if (sourceBadge) {
      sourceBadge.textContent = jointChoice.fallback?.active ? "BASELINE FALLBACK" : "MODEL";
    }
    const stabInfo = (jointChoice as any).stability_maintainer;
    const stabBadge = byId<HTMLElement>("jointStabilityBadge");
    if (stabBadge) {
      if (stabInfo?.triggered) {
        stabBadge.style.display = "inline-flex";
        const threshPct = Math.round((stabInfo.threshold ?? 0.10) * 100);
        let overrideDetail = "";
        if (stabInfo.overrides) {
          const overriddenAxes = Object.keys(stabInfo.overrides).filter((k) => stabInfo.overrides[k]?.triggered);
          if (overriddenAxes.length > 0) {
            overrideDetail = ` (${overriddenAxes.join(", ")})`;
          }
        }
        stabBadge.textContent = `🛡️ STABILITY HOLD${overrideDetail}`;
        stabBadge.title = `Stability Maintainer held control because active option margin was < ${threshPct}% over HOLD`;
      } else {
        stabBadge.style.display = "none";
      }
    }
    byId("actionCount").textContent = String(jointChoice.legal_count ?? "—");

    const probabilities = jointChoice.probabilities ?? {};
    const legalOptions = Object.keys(jointChoice.legal_options ?? {});
    const probs = (legalOptions.length
      ? legalOptions.map((id) => [id, probabilities[id] ?? 0] as [string, number])
      : Object.entries(probabilities)
    ).sort(([, a], [, b]) => b - a);
    const top5 = probs.slice(0, 5);
    const probContainer = byId("topProbBars");
    probContainer.innerHTML = top5.map(([actId, p]) => {
      const pct = (p * 100).toFixed(0);
      return `
        <div class="prob-bar-row">
          <span class="prob-bar-label" title="${actId}">${actId}</span>
          <div class="prob-bar-track"><div class="prob-bar-fill" style="width: ${pct}%;"></div></div>
          <span class="prob-bar-pct">${pct}%</span>
        </div>
      `;
    }).join("");

    const modalTitle = byId("allOptionsModalTitle");
    if (modalTitle) {
      modalTitle.innerHTML = `<span>☰</span> ${jointChoice.legal_count} Legal Joint Action Candidates`;
    }

    // Populate every legal option, including zero-probability options.
    const tableBody = byId("allOptionsTableBody");
    tableBody.innerHTML = probs.map(([actId, p]) => {
      const isChosen = actId === compactId;
      let a = "0.000"; let e = "0.000"; let r = "0.000"; let t = "0.000";
      const deltas = jointChoice.legal_deltas?.[actId];
      if (deltas) {
        a = (deltas.aileron ?? 0).toFixed(4);
        e = (deltas.elevator ?? 0).toFixed(4);
        r = (deltas.rudder ?? 0).toFixed(4);
        t = (deltas.throttle ?? 0).toFixed(4);
      }
      return `
        <tr class="${isChosen ? "selected" : ""}">
          <td><strong>${actId}</strong> ${isChosen ? "★" : ""}</td>
          <td>${a}</td>
          <td>${e}</td>
          <td>${r}</td>
          <td>${t}</td>
          <td>${(p * 100).toFixed(1)}%</td>
        </tr>
      `;
    }).join("");

    // Axis Marginals Diagnostics (Section 13)
    let marginals = isMicro ? null : (jointChoice as any).axis_marginals;
    if (!marginals || Object.keys(marginals).length === 0) {
      marginals = computeMarginalsFromProbs(jointChoice.probabilities ?? {});
    }

    const pHoldAll = ((jointChoice.probabilities?.[isMicro ? "HOLD" : "A0_E0_R0_T0"] ?? 0) * 100);
    const holdBadge = byId("marginalsHoldBadge");
    if (holdBadge) {
      holdBadge.textContent = `P(HOLD ALL) ${pHoldAll.toFixed(0)}%`;
    }

    const marginalsGrid = byId("axisMarginalsGrid");
    if (marginalsGrid && marginals) {
      const axesList = [
        { key: "aileron", label: "AILERON" },
        { key: "elevator", label: "ELEVATOR" },
        { key: "rudder", label: "RUDDER" },
        { key: "throttle", label: "THROTTLE" },
      ] as const;

      marginalsGrid.innerHTML = axesList.map(({ key, label }) => {
        const ax = marginals[key] ?? { decrease: 0, hold: 1, increase: 0 };
        const pDec = Math.round((ax.decrease ?? 0) * 100);
        const pHld = Math.round((ax.hold ?? 0) * 100);
        const pInc = Math.round((ax.increase ?? 0) * 100);
        const pChg = Math.round(((ax.decrease ?? 0) + (ax.increase ?? 0)) * 100);

        return `
          <div class="marginal-axis-card">
            <div class="marginal-axis-header">
              <span class="marginal-axis-name">${label}</span>
              <span class="marginal-axis-chg">P(chg) ${pChg}%</span>
            </div>
            <div class="marginal-row">
              <span class="m-lbl">decrease</span>
              <div class="m-track"><div class="m-fill m-dec" style="width: ${pDec}%;"></div></div>
              <span class="m-pct">${pDec}%</span>
            </div>
            <div class="marginal-row">
              <span class="m-lbl">hold</span>
              <div class="m-track"><div class="m-fill m-hld" style="width: ${pHld}%;"></div></div>
              <span class="m-pct">${pHld}%</span>
            </div>
            <div class="marginal-row">
              <span class="m-lbl">increase</span>
              <div class="m-track"><div class="m-fill m-inc" style="width: ${pInc}%;"></div></div>
              <span class="m-pct">${pInc}%</span>
            </div>
          </div>
        `;
      }).join("");
    }

  }

  // Action -> Consequence Feedback Section
  const prev = info.input?.previous_control_transition;
  const obs = info.input?.observed_since_previous_action;
  const transGrid = byId("transitionGrid");
  const obsGrid = byId("observedGrid");

  if (prev) {
    const axes = ["aileron", "elevator", "rudder", "throttle"] as const;
    transGrid.innerHTML = axes.map((axis) => {
      const entry = prev[axis];
      if (!entry) return "";
      const signBefore = entry.before >= 0 ? "+" : "";
      const signAfter = entry.after >= 0 ? "+" : "";
      return `
        <div class="transition-col">
          <span class="trans-axis">${axis[0].toUpperCase() + axis.slice(1, 3)}</span>
          <span class="trans-vals">${signBefore}${entry.before.toFixed(2)} → ${signAfter}${entry.after.toFixed(2)}</span>
          <span class="trans-action">${entry.action}</span>
        </div>
      `;
    }).join("");
  } else {
    transGrid.innerHTML = '<div style="color: var(--text-muted); font-size: 11.5px; padding: 2px;">Initial step (no prior transition)</div>';
  }

  let observedSummaryText = "—";
  if (obs) {
    const fmt = (val: number | undefined, unit: string) => {
      if (val == null) return "—";
      const sign = val >= 0 ? "+" : "";
      const cls = val > 0 ? "neutral-pos" : val < 0 ? "neutral-neg" : "";
      return `<span class="obs-val ${cls}">${sign}${val.toFixed(2)} ${unit}</span>`;
    };
    obsGrid.innerHTML = `
      <div class="obs-item"><span class="obs-key">dIAS</span>${fmt(obs.airspeed_delta_mps, "m/s")}</div>
      <div class="obs-item"><span class="obs-key">dVSI</span>${fmt(obs.vertical_speed_delta_mps, "m/s")}</div>
      <div class="obs-item"><span class="obs-key">dFPA</span>${fmt(obs.flight_path_angle_delta_deg, "°")}</div>
      <div class="obs-item"><span class="obs-key">dAoA</span>${fmt(obs.angle_of_attack_delta_deg, "°")}</div>
      <div class="obs-item"><span class="obs-key">dALT</span>${fmt(obs.altitude_agl_delta_m, "m")}</div>
      <div class="obs-item"><span class="obs-key">dXTRK</span>${fmt(obs.cross_track_error_delta_m, "m")}</div>
      <div class="obs-item"><span class="obs-key">dGLIDE</span>${fmt(obs.glideslope_error_delta_deg, "°")}</div>
      <div class="obs-item"><span class="obs-key">dHDG</span>${fmt(obs.heading_error_delta_deg, "°")}</div>
      <div class="obs-item"><span class="obs-key">dROLL</span>${fmt(obs.roll_delta_deg, "°")}</div>
      <div class="obs-item"><span class="obs-key">dPITCH</span>${fmt(obs.pitch_delta_deg, "°")}</div>
    `;
    const dt = obs.elapsed_s != null ? `${obs.elapsed_s.toFixed(2)}s` : "unknown interval";
    byId("consequenceElapsedChip").textContent = `Observed after ${dt}`;
    observedSummaryText = `dIAS ${obs.airspeed_delta_mps >= 0 ? "+" : ""}${obs.airspeed_delta_mps?.toFixed(1)} m/s, dVSI ${obs.vertical_speed_delta_mps >= 0 ? "+" : ""}${obs.vertical_speed_delta_mps?.toFixed(1)} m/s`;
  } else {
    obsGrid.innerHTML = '<div style="color: var(--text-muted); font-size: 11.5px; padding: 4px;">Awaiting first consequence observation...</div>';
  }

  // Structured Input Sent to Jev
  if (info.input) {
    const inp = info.input;
    const ac = inp.aircraft_state || inp.aircraft_telemetry || {};
    const rw = inp.runway_relative || {};
    const cr = inp.current_rates || inp.rates || {};
    const n = (v: number | undefined, d = 2) => (v == null ? "—" : v.toFixed(d));

    byId("inputSummaryGrid").innerHTML = `
      <div class="input-item"><span class="input-key">FPA / AoA</span><span class="input-val">${n(ac.flight_path_angle_deg, 1)}° / ${n(ac.angle_of_attack_deg, 1)}°</span></div>
      <div class="input-item"><span class="input-key">IAS / GS</span><span class="input-val">${n(ac.calibrated_airspeed_mps ?? ac.airspeed_mps, 1)} / ${n(ac.groundspeed_mps, 1)} m/s</span></div>
      <div class="input-item"><span class="input-key">ROLL / PITCH</span><span class="input-val">${n(ac.roll_deg, 1)}° / ${n(ac.pitch_deg, 1)}°</span></div>
      <div class="input-item"><span class="input-key">HEADING / ERR</span><span class="input-val">${n(ac.heading_deg, 1)}° (${n(rw.heading_error_deg, 1)}°)</span></div>
      <div class="input-item"><span class="input-key">ALONG / XTRK</span><span class="input-val">${rw.along_track_m != null ? `${rw.along_track_m >= 0 ? "+" : ""}${rw.along_track_m.toFixed(0)}m` : "—"} / ${n(rw.cross_track_error_m, 1)}m</span></div>
      <div class="input-item"><span class="input-key">GLIDE ERR</span><span class="input-val">${n(rw.glideslope_error_deg, 2)}°</span></div>
      <div class="input-item"><span class="input-key">dFPA/dt</span><span class="input-val">${n(cr.flight_path_angle_rate_deg_s, 2)} °/s</span></div>
      <div class="input-item"><span class="input-key">dAoA/dt</span><span class="input-val">${n(cr.angle_of_attack_rate_deg_s, 2)} °/s</span></div>
      <div class="input-item"><span class="input-key">SIM TIME</span><span class="input-val">${n(inp.timing?.sim_time_s, 2)} s</span></div>
      <div class="input-item"><span class="input-key">CADENCE DT</span><span class="input-val">${n(inp.timing?.decision_interval_s, 2)} s</span></div>
    `;
  }

  // History tracking
  if (decisionCount > lastDecisionCount && jointChoice) {
    lastDecisionCount = decisionCount;
    const simTime = info.input?.timing?.sim_time_s ?? decisionCount / (info.live_status?.cadence_hz ?? 2);
    const compactId = jointChoice.id || "A0_E0_R0_T0";
    const isStabTriggered = Boolean((jointChoice as any).stability_maintainer?.triggered);
    allDecisions.unshift({
      count: decisionCount,
      simTime,
      id: compactId,
      confidence: jointChoice.confidence ?? null,
      latencyMs,
      observedText: observedSummaryText,
      info: JSON.parse(JSON.stringify(info)) as DecisionInfo,
      stabilityTriggered: isStabTriggered,
    });

    // Update last 3 cards in sidebar
    const last3 = allDecisions.slice(0, 3);
    byId("historyCardsList").innerHTML = last3.map((entry) => `
      <div class="history-card">
        <div class="history-card-top">
          <span class="hist-num">Decision #${entry.count} (${entry.simTime.toFixed(1)}s)</span>
          <span class="hist-code">${entry.id}${entry.stabilityTriggered ? " <span title=\"Stability Maintainer Override\" style=\"color:#38bdf8;font-size:10px;\">🛡️</span>" : ""}</span>
          <span class="hist-conf">${entry.confidence != null ? `${(entry.confidence * 100).toFixed(0)}%` : "—"}</span>
        </div>
        <div class="hist-deltas-line">${entry.observedText}</div>
      </div>
    `).join("");

    // Update Full History Modal Table
    byId("fullHistoryTableBody").innerHTML = allDecisions.map((entry) => `
      <tr>
        <td>#${entry.count}</td>
        <td>${entry.simTime.toFixed(2)} s</td>
        <td><strong>${entry.id}</strong>${entry.stabilityTriggered ? " <span title=\"Stability Maintainer Override\" style=\"color:#38bdf8;\">🛡️</span>" : ""}</td>
        <td>${entry.confidence != null ? `${(entry.confidence * 100).toFixed(0)}%` : "—"}</td>
        <td>${entry.latencyMs != null ? `${entry.latencyMs.toFixed(0)} ms` : "—"}</td>
        <td>${entry.observedText}</td>
      </tr>
    `).join("");
  }
}

// HUD & Telemetry Updates
function updateHudAndTelemetry(message: StateMessage) {
  lastObservation = message.observation;
  const { runway: r, flight: f } = message.observation;
  lastKnownRollDeg = f.roll_deg;

  // Viewport Primary HUD
  byId("hudAgl").innerHTML = `${r.altitude_agl_m.toFixed(1)}<small>m</small>`;
  byId("hudIas").innerHTML = `${f.airspeed_mps.toFixed(1)}<small>m/s</small>`;
  byId("hudVsi").innerHTML = `${f.vertical_speed_mps.toFixed(1)}<small>m/s</small>`;
  const fpaVal = f.flight_path_angle_deg != null ? `${f.flight_path_angle_deg.toFixed(1)}°` : "—";
  byId("hudFpa").innerHTML = `${fpaVal}<small></small>`;

  // Viewport Secondary HUD
  const offset = r.centerline_offset_m ?? r.cross_track_error_m;
  byId("hudXtrack").textContent = `${offset >= 0 ? "+" : ""}${offset.toFixed(1)} m`;
  byId("hudXtrack").title = "Actual centerline offset (+ runway-right), without the model observation deadband.";
  byId("hudGlide").textContent = `${r.glideslope_error_deg >= 0 ? "+" : ""}${r.glideslope_error_deg.toFixed(1)}°`;
  byId("hudHdgErr").textContent = `${r.heading_error_deg >= 0 ? "+" : ""}${r.heading_error_deg.toFixed(1)}°`;
  byId("hudAoa").textContent = f.angle_of_attack_deg != null ? `${f.angle_of_attack_deg.toFixed(1)}°` : "—";

  // Horizontal Telemetry Strip
  const phaseVal = (message.observation as any).phase ?? "APPROACH";
  byId("stripPhase").textContent = phaseVal;
  const alongVal = r.along_track_m ?? -r.distance_to_threshold_m;
  byId("stripAlong").textContent = `${alongVal >= 0 ? "+" : ""}${alongVal.toFixed(0)} m`;
  byId("stripThresh").textContent = `${r.distance_to_threshold_m.toFixed(0)} m`;
  byId("stripRoll").textContent = `${f.roll_deg >= 0 ? "+" : ""}${f.roll_deg.toFixed(1)}°`;
  byId("stripPitch").textContent = `${f.pitch_deg >= 0 ? "+" : ""}${f.pitch_deg.toFixed(1)}°`;
  byId("stripWind").textContent = formatWindSummary(message.observation.environment);
  byId("stripScore").textContent = message.score.toFixed(1);

  if (runState === "running") {
    byId("flightStatePill").textContent = message.status === "running" ? "IN FLIGHT" : outcomeLabel(message.status, message.result?.success);
  }
  updateDecisionCards(message.decision_info, message.decision_count, message.latency_ms);
}

function showOutcomeModal(record: RunRecord, owner = "Your flight") {
  byId("raceStandings").hidden = true;
  byId("outcomeStats").hidden = false;
  const result = record.outcome;
  const success = Boolean(result.success);
  byId("outcomeCard").className = `modal-card outcome-modal-card ${success ? "landed" : ""}`;
  byId("outcomeTitle").className = `outcome-title ${success ? "landed" : ""}`;
  byId("outcomeIcon").textContent = success ? "✓" : "—";
  byId("outcomeTitle").textContent = `${owner} · ${outcomeLabel(result.status, success)}`;
  byId("outcomeDesc").textContent = success
    ? "Safe main-gear contact and rollout completed. Values below are frozen at touchdown."
    : `Recorded outcome: ${outcomeLabel(result.status)}. ${result.touchdown ? "Values below are frozen at touchdown." : "No main-gear touchdown was recorded."}`;
  byId("outcomeScoreVal").textContent = `${(result.quality ?? 0).toFixed(1)} / 100`;
  const values = touchdownValues(result);
  ["outcomeIasVal", "outcomeVsiVal", "outcomeXtrackVal", "outcomePitchVal", "outcomeRollVal"].forEach((id, i) => byId(id).textContent = values[i]);
  const watchButton = document.querySelector<HTMLElement>('[data-close="outcomeModal"]');
  if (watchButton) watchButton.textContent = spectatorRunning ? liveRunning() ? "Watch live opponents" : "Continue watching" : "Close result";
  byId("outcomeRestartBtn").textContent = liveRunning() ? "Stop opponents & start next run" : "Start Next Run";
  openDialog("outcomeModal");
}

function showRaceResults() {
  if (!primaryResult) return;
  const opponents = activeGhosts.map(({ run, label }) => ({ run, label }));
  // A live controller may fail before sending its first pose.
  for (const entry of liveOpponents.values()) if (!opponents.some(({run}) => run === entry.run)) opponents.push({run: entry.run, label: entry.label});
  showOutcomeModal(primaryResult);
  if (!opponents.length) return;
  const entries = [
    { label: "Your flight", controller: recordingController, record: primaryResult, outcome: primaryResult.outcome },
    ...opponents.map(({ run, label }) => ({ label, controller: run.controller, record: ghostRecords.get(run),
      outcome: ghostRecords.get(run)?.outcome ?? { quality: run.score, status: run.status, success: run.success } })),
  ].sort((a, b) => (b.outcome.quality ?? 0) - (a.outcome.quality ?? 0));
  byId("outcomeTitle").textContent = "Race standings";
  byId("outcomeTitle").className = "outcome-title";
  byId("outcomeCard").className = "modal-card outcome-modal-card";
  byId("outcomeIcon").textContent = "≡";
  byId("outcomeDesc").textContent = "Highest score first · Ties share a rank. Replay scores belong to their recorded flights; seeds may differ.";
  byId("outcomeStats").hidden = true;
  const standings = byId("raceStandings");
  standings.replaceChildren(); standings.hidden = false;
  let rank = 1;
  entries.forEach((entry, index) => {
    const score = entry.outcome.quality ?? 0;
    if (index && score !== (entries[index - 1].outcome.quality ?? 0)) rank = index + 1;
    const row = document.createElement("div"); row.className = "race-standing";
    const place = document.createElement("strong"); place.textContent = `#${rank}`;
    const identity = document.createElement("div");
    const name = document.createElement("strong"); name.textContent = `${entry.label} · ${entry.controller}`;
    const detail = document.createElement("small");
    detail.textContent = [entry.record?.config?.model, entry.record?.config?.seed != null ? `Seed ${entry.record.config.seed}` : null,
      outcomeLabel(entry.outcome.status, entry.outcome.success)].filter(Boolean).join(" · ");
    identity.append(name, detail);
    const points = document.createElement("strong"); points.textContent = `${score.toFixed(1)} pts`;
    row.append(place, identity, points); standings.append(row);
  });
}

function showError(msg: string) {
  const banner = byId("errorBanner");
  banner.textContent = msg;
  banner.classList.add("visible");
}
function hideError() {
  byId("errorBanner").classList.remove("visible");
}

// WebSocket Connection
let socket: WebSocket;
let browserRuntime: BrowserRuntime;
let reconnectTimer = 0;
function connect() {
  if (pagesRuntime) {
    byId("connectionText").textContent = "LOADING WASM";
    browserRuntime = new BrowserRuntime(new URL(`${import.meta.env.BASE_URL}wasm/worker.js?v=interactive-races-3`, location.origin), receiveMessage);
    return;
  }
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const connection = new WebSocket(`${protocol}://${location.host}/ws`);
  socket = connection;

  connection.addEventListener("open", () => {
    if (socket !== connection) return;
    byId("connectionDot").classList.add("online");
    byId("connectionText").textContent = "ONLINE";
    hideError();
    transitionRun("connect");
  });

  connection.addEventListener("close", () => {
    if (socket !== connection) return;
    byId("connectionDot").classList.remove("online");
    byId("connectionText").textContent = "OFFLINE";
    activeRunId = null; liveOpponents.clear(); spectatorRunning = false;
    closeDialog("outcomeModal");
    transitionRun("disconnect");
    clearTimeout(reconnectTimer);
    reconnectTimer = window.setTimeout(connect, 1500);
  });

  connection.addEventListener("message", ({ data }) => {
    if (socket !== connection) return;
    try {
      const message = JSON.parse(data);
      receiveMessage(message);
    } catch (error) {
      console.error("Failed to process backend telemetry", error);
      showError("Telemetry stream error");
    }
  });
}

function receiveMessage(message: any) {
  if (message.type === "ghost") {
    const event = message.message;
    const id = message.opponent_id ?? "live";
    let entry = liveOpponents.get(id);
    if (event.type === "run_started") {
      if (dismissingRace || (runState !== "starting" && runState !== "running")) return;
      const run: Ghost = {key: ghostKey, controller: event.config?.controller ?? "jev", score: 0, status: "running", samples: []};
      entry = {runId: event.run_id, run, label: id === "live" ? "Live Jev" : ghostTitle(`live:${id}`), state: null, renderTime: 0};
      liveOpponents.set(id, entry);
    } else if (entry && event.run_id === entry.runId && event.type === "state") {
      const time = event.observation.time_s;
      entry.state = event;
      if (watchedGhost === entry.run && spectatorRunning && Number.isFinite(time)) { raceTime = time; updateHudAndTelemetry(event); }
      if (Number.isFinite(time) && (!entry.run.samples.length || time > entry.run.samples.at(-1)!.time)) {
        entry.run.samples.push({time, position: event.position, quaternion: event.quaternion});
        if (entry.run.samples.length === 1) {
          const color = racerColor(id === "live" ? "jev-1.13.0" : id);
          const visual = createGhostVisual(color); visual.visible = false;
          const marker = document.createElement("div"); marker.className = "ghost-marker"; marker.textContent = entry.label;
          raceAccent(marker, color);
          ghostLegend.parentElement!.append(marker); scene.add(visual);
          activeGhosts.push({run: entry.run, visual, label: entry.label, marker, color}); ghostLegend.hidden = false;
        }
      }
    } else if (entry && event.run_id === entry.runId && event.type === "run_finished") {
      Object.assign(entry.run, {score: event.record.outcome.quality ?? 0, status: event.record.outcome.status, success: event.record.outcome.success});
      ghostRecords.set(entry.run, event.record);
      if (entry.run.samples.length > 1) ghostRuns.push(entry.run);
      entry.runId = null; refreshGhostStatus();
      byId<HTMLButtonElement>("stop").disabled = runState !== "running" && !liveRunning();
      if (!activeRunId && !resettingRace && (dismissingRace || !followRemainingOpponent())) finishSpectating(entry.run);
    } else if (event.type === "error" || event.type === "offline") {
      if (entry) {entry.run.status = "controller_error"; entry.runId = null;}
      showError(`${entry?.label ?? id}: ${event.message}`);
      if (!activeRunId && !resettingRace && !followRemainingOpponent()) showRaceResults();
    }
    return;
  }
  if (message.type === "ready") {
    byId("connectionDot").classList.add("online");
    byId("connectionText").textContent = "WASM · LOCAL PHYSICS";
    hideError(); transitionRun("connect"); return;
  }
  if (message.type === "offline") {
    liveOpponents.clear(); spectatorRunning = false;
    closeDialog("outcomeModal");
    byId("connectionDot").classList.remove("online");
    byId("connectionText").textContent = "OFFLINE";
    activeRunId = null; transitionRun("disconnect"); showError(message.message); return;
  }
  if (message.type === "error") {
    transitionRun("error");
    if (spectatorRunning) updateSpectatorLabel();
    if (message.code === "storage_error") byId<HTMLButtonElement>("stop").disabled = false;
    showError(message.message);
    return;
  }
  if (message.type === "run_started") {
    activeRunId = message.run_id;
    startViewPending = true;
    transitionRun("accepted");
    return;
  }
  if (message.type === "run_finished") {
    if (message.run_id !== activeRunId) return;
    activeRunId = null;
    transitionRun("finished");
    const quality = message.record.outcome.quality;
    if (ghostSamples.length > 1) {
      const recordedGhost: Ghost = { key: ghostKey, controller: recordingController, score: Number.isFinite(quality) ? quality : 0,
        success: message.record.outcome.success === true, status: message.record.outcome.status,
        samples: ghostSamples };
      ghostRecords.set(recordedGhost, message.record);
      ghostRuns.push(recordedGhost);
      // Retain latest flights plus each setup's PB, rather than evicting PB after a failed attempt.
      while (ghostRuns.length > 24) {
        const oldest = ghostRuns.findIndex(run => run !== selectGhost(ghostRuns, run.key, "human"));
        ghostRuns.splice(oldest >= 0 ? oldest : 0, 1);
      }
      refreshGhostStatus();
    }
    primaryResult = message.record;
    primaryResultButton.hidden = resettingRace;
    if (resettingRace) return;
    if (dismissingRace || !followRemainingOpponent()) showRaceResults();
    return;
  }
  if (message.type === "idle") {
    transitionRun("reset");
    if (spectatorRunning) { updateSpectatorLabel(); byId<HTMLButtonElement>("stop").disabled = false; }
    else if (watchedGhost && !resettingRace) byId("flightStatePill").textContent = "RACE FINISHED";
    return;
  }
  if (message.type !== "state" || message.run_id !== activeRunId) return;
  applyFlightBenchState(message as StateMessage);
}

function applyFlightBenchState(message: StateMessage) {
  const time = message.observation.time_s;
  if (Number.isFinite(time) && (!ghostSamples.length || time > ghostSamples.at(-1)!.time)) {
    ghostSamples.push({ time, position: [...message.position], quaternion: [...message.quaternion] });
  }
  if (Number.isFinite(time)) raceTime = replayTime = time;
  desiredPosition.fromArray(message.position);
  desiredQuaternion.fromArray(message.quaternion).normalize();
  if (startViewPending) {
    startViewPending = false;
    if (cameraMode === "chase" && !reducedMotion.matches) {
      // Match the reference's runway-to-flight view, independently of Reset or the previous run.
      aircraft.position.set(225, 1, 0);
      aircraft.quaternion.identity();
      setCamera("chase");
      startCameraUntil = performance.now() + 1500;
    }
  }

  updateHudAndTelemetry(message);
  if (byId<HTMLSelectElement>("controller").value !== "human") {
    copyControls(controls, message.observation.controls);
    showControls(controls);
  }
}
function send(message: { type: string; [key: string]: unknown }): boolean {
  if (message.type === "action" && runState !== "running") return false;
  if (pagesRuntime) return browserRuntime?.send(message) ?? false;
  if (socket?.readyState !== WebSocket.OPEN) return false;
  socket.send(JSON.stringify(message));
  return true;
}

let displayedRate = "— Hz";
let displayedMeanLatency = "— ms";
let lastMetricUpdate = performance.now();
const controllerSelect = byId<HTMLSelectElement>("controller");
const scenarioSelect = byId<HTMLSelectElement>("scenario");
const modelSelect = byId<HTMLSelectElement>("model");
const jevModelSelect = byId<HTMLSelectElement>("jevModel");
const reasoningEffortSelect = byId<HTMLSelectElement>("reasoningEffort");
const manualPanel = byId("manualControlsCard");
const SCENARIO_DETAILS: Record<string, {description: string; wind: [string, string][]; approach: [string, string][]; note: string}> = {
  easy: {
    description: "Still air. A stable, aligned final approach.",
    wind: [["Wind", "Calm · 0 m/s"]],
    approach: [["Glideslope", "3°"], ["Airspeed", "65 KIAS"]],
    note: "Identical starting conditions. No seed needed.",
  },
  medium: {
    description: "Steady wind. A small variation in your starting approach.",
    wind: [["Crosswind", "±5 m/s"], ["Tailwind / headwind", "2 / 6 m/s"]],
    approach: [["Centerline", "±35 m"], ["Heading", "±5°"], ["Glidepath height", "±8 m"], ["Airspeed", "±4 kt"]],
    note: "The same seed repeats the wind and starting conditions.",
  },
  hard: {
    description: "Wind shear and gusts change with time and height.",
    wind: [["Base crosswind", "±8 m/s"], ["Base tail / headwind", "4 / 10 m/s"], ["Base down / updraft", "1 / 0.5 m/s"]],
    approach: [["Centerline", "±60 m"], ["Heading", "±10°"], ["Glidepath height", "±18 m"], ["Airspeed", "±8 kt"]],
    note: "Gusts vary beyond the base wind. The same seed repeats the conditions.",
  },
};
function renderScenarioConditions() {
  const details = SCENARIO_DETAILS[scenarioSelect.value];
  const host = byId("scenarioSummary"); host.replaceChildren();
  const description = document.createElement("p"); description.className = "conditions-description";
  description.textContent = details.description; host.append(description);
  for (const [title, values] of [["Wind conditions", details.wind], [scenarioSelect.value === "easy" ? "Starting approach" : "Starting variation", details.approach]] as const) {
    const section = document.createElement("section"), heading = document.createElement("h3"); heading.textContent = title;
    const grid = document.createElement("dl"); grid.className = "condition-grid";
    for (const [label, value] of values) {
      const cell = document.createElement("div"), term = document.createElement("dt"), datum = document.createElement("dd");
      term.textContent = label; datum.textContent = value; cell.append(term, datum); grid.append(cell);
    }
    section.append(heading, grid); host.append(section);
  }
  const note = document.createElement("p"); note.className = "conditions-note"; note.textContent = details.note; host.append(note);
}
function positionConfigPanels() {
  const top = byId("viewerToolbar").getBoundingClientRect().bottom + 8;
  byId("viewerToolbar").style.setProperty("--config-top", `${top}px`);
}
function setConfigOpen(open: boolean) {
  if (open) {setScenarioOpen(false); positionConfigPanels();}
  byId("configPanel").hidden = !open;
  byId("configureToggle").setAttribute("aria-expanded", String(open));
}
byId("configureToggle").addEventListener("click", () => setConfigOpen(byId("configPanel").hidden));
function setScenarioOpen(open: boolean) {
  if (open) {setConfigOpen(false); positionConfigPanels();}
  byId("scenarioPanel").hidden = !open;
  byId("scenarioToggle").setAttribute("aria-expanded", String(open));
}
byId("scenarioToggle").addEventListener("click", () => setScenarioOpen(byId("scenarioPanel").hidden));
function setHudOpen(open: boolean) {
  byId("hudOverlay").dataset.open = String(open);
  byId("hudToggle").setAttribute("aria-expanded", String(open));
  positionConfigPanels();
}
byId("hudToggle").addEventListener("click", () => setHudOpen(byId("hudOverlay").dataset.open !== "true"));
document.addEventListener("pointerdown", (event) => {
  if (!byId("configPanel").hidden && !byId("viewerToolbar").contains(event.target as Node)) setConfigOpen(false);
  if (!byId("scenarioPanel").hidden && !byId("viewerToolbar").contains(event.target as Node)) setScenarioOpen(false);
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !byId("scenarioPanel").hidden) {
    setScenarioOpen(false); byId("scenarioToggle").focus();
  } else if (event.key === "Escape" && !byId("configPanel").hidden) {
    setConfigOpen(false);
    byId("configureToggle").focus();
  } else if (event.key === "Escape" && byId("hudToggle").offsetParent && byId("hudOverlay").dataset.open === "true") {
    setHudOpen(false);
    byId("hudToggle").focus();
  }
});

function updateControllerUi() {
  const restoreControllerFocus = (document.activeElement as HTMLInputElement)?.name === "controller-choice";
  const cards = byId("controllerCards"); cards.replaceChildren();
  const descriptions: Record<string, string> = {human: "Keyboard & touch", baseline: "Rule-based autopilot", jev: "TypeSafe AI", codex: "Local Codex"};
  for (const option of controllerSelect.options) {
    if (option.disabled || option.hidden) continue;
    const label = document.createElement("label"); label.className = "controller-card";
    const radio = document.createElement("input"); radio.type = "radio"; radio.name = "controller-choice";
    radio.value = option.value; radio.checked = controllerSelect.value === option.value;
    radio.addEventListener("change", () => {controllerSelect.value = option.value; controllerSelect.dispatchEvent(new Event("change"));});
    label.append(radio, choiceContent(option.value, option.text.split(" · ")[0], descriptions[option.value]));
    cards.append(label);
  }
  const versions = byId("jevVersionChoices");
  const focusedVersion = (document.activeElement as HTMLInputElement)?.name === "jev-version";
  versions.replaceChildren();
  for (const option of jevModelSelect.options) {
    const badge = document.createElement("label"); badge.className = "version-badge";
    const radio = document.createElement("input"); radio.type = "radio"; radio.name = "jev-version";
    radio.value = option.value; radio.checked = jevModelSelect.value === option.value;
    radio.setAttribute("aria-label", `Jev ${option.text}`);
    radio.addEventListener("change", () => {jevModelSelect.value = option.value; jevModelSelect.dispatchEvent(new Event("change"));});
    const text = document.createElement("span"); text.textContent = option.text;
    badge.append(radio, text); versions.append(badge);
  }
  if (focusedVersion) versions.querySelector<HTMLInputElement>("input:checked")?.focus();
  if (restoreControllerFocus) cards.querySelector<HTMLInputElement>("input:checked")?.focus();
  const isCodex = controllerSelect.value === "codex";
  const isHuman = controllerSelect.value === "human";
  refreshGhostStatus();
  byId("ghostSettings").hidden = false;
  const viewController = watchedGhost?.controller ?? controllerSelect.value;
  const isJevOrAi = viewController === "jev" || viewController === "codex";
  document.querySelector<HTMLElement>(".workspace")!.dataset.controller = viewController;

  byId("modelGroup").hidden = !isCodex;
  byId("jevModelGroup").hidden = controllerSelect.value !== "jev";
  byId("reasoningEffortGroup").hidden = !isCodex;
  byId("timingModeGroup").hidden = !isJevOrAi;
  const timing = byId<HTMLSelectElement>("timingMode");
  if (isCodex && timing.value === "realtime") reasoningEffortSelect.value = "low";
  for (const option of reasoningEffortSelect.options) option.disabled = isCodex && timing.value === "realtime" && option.value !== "low";
  byId("seedGroup").hidden = scenarioSelect.value === "easy";
  renderScenarioConditions();
  byId("scenarioToggle").textContent = `${scenarioSelect.selectedOptions[0]?.textContent?.split(" · ")[0]} ▾`;
  byId("windInstrument").hidden = scenarioSelect.value === "easy";
  updateTimingLabels();
  byId("overlayController").textContent = controllerSelect.selectedOptions[0]?.textContent ?? "Controller";
  byId("liveDecisionCard").hidden = !isJevOrAi;
  byId("decisionDiagnostics").hidden = !isJevOrAi;
  byId("decisionInput").hidden = viewController !== "jev";
  byId("decisionOutputTitle").textContent = viewController === "jev" ? "JEV CHOSE · REQUESTED CONTROLS" : "MODEL CHOSE · REQUESTED CONTROLS";
  byId("overlayDecision").hidden = !isJevOrAi;
  if (manualPanel) manualPanel.style.display = isHuman && !watchedGhost ? "flex" : "none";

  const aiCards = ["jointDecisionCard", "consequenceCard", "inputSummaryCard", "decisionHistoryCard"]
    .map((id) => byId<HTMLElement>(id))
    .filter((el): el is HTMLElement => el !== null);
  aiCards.forEach((c) => { c.style.display = isJevOrAi ? "flex" : "none"; });
  const decisionTitle = document.querySelector<HTMLElement>("#jointDecisionCard .ctrl-card-title");
  if (decisionTitle) decisionTitle.textContent = "Current Joint Action";
  const marginalToggle = byId<HTMLElement>("toggleMarginalsBtn");
  if (marginalToggle) marginalToggle.style.display = "";
  const marginalSection = byId<HTMLElement>("axisMarginalsSection");
  if (marginalSection) marginalSection.style.display = "";

  const brandTitle = byId("ctrlBrandTitle");
  const modelTag = byId("ctrlModelTag");
  if (watchedGhost) {
    if (brandTitle) brandTitle.textContent = `${viewController.toUpperCase()} · Spectator`;
    if (modelTag) modelTag.textContent = Boolean(liveEntry(watchedGhost)) ? "Live opponent · API usage" : "Recorded flight";
  } else if (isHuman) {
    if (brandTitle) brandTitle.textContent = "Human Pilot";
    if (modelTag) modelTag.textContent = "Keyboard / touch controls";
  } else if (controllerSelect.value === "baseline") {
    if (brandTitle) brandTitle.textContent = "Baseline Controller";
    if (modelTag) modelTag.textContent = "Rule-Based ILS";
  } else if (controllerSelect.value === "jev") {
    if (brandTitle) brandTitle.textContent = "TypeSafe Jev";
    if (modelTag) modelTag.textContent = jevModelSelect.value;
  } else if (isCodex) {
    if (brandTitle) brandTitle.textContent = "Codex Controller";
    if (modelTag) modelTag.textContent = modelSelect.value ? `${modelSelect.value} · ${reasoningEffortSelect.value}` : "Select an authenticated model";
  }

  autoCenterEnabled = byId<HTMLInputElement>("autoCenterToggle").checked;
  wingLevelerEnabled = byId<HTMLInputElement>("wingLevelerToggle").checked;
  updateAssistPill();


}

byId("seed").addEventListener("input", refreshGhostStatus);
scenarioSelect.addEventListener("change", () => { updateControllerUi(); refreshGhostStatus(); positionConfigPanels(); });
controllerSelect.addEventListener("change", () => { clearDecisionView(); updateControllerUi(); });
for (const select of [byId("timingMode"), modelSelect, jevModelSelect, reasoningEffortSelect]) {
  select.addEventListener("change", () => { clearDecisionView(); updateControllerUi(); });
}
if (pagesRuntime) {
  controllerSelect.querySelector('option[value="codex"]')?.remove();
  byId("stop").setAttribute("aria-label", "Stop flight");
  document.querySelector(".model-credit")?.insertAdjacentHTML("beforeend", `<br><a href="/FlightBench/recordings/">Flight recordings</a>`);
}
updateControllerUi();

if (!pagesRuntime) {
  for (const value of ["jev", "codex"]) controllerSelect.querySelector<HTMLOptionElement>(`option[value="${value}"]`)!.hidden = true;
  updateControllerUi();
}
if (!pagesRuntime) fetch("/api/capabilities").then(res => res.json()).then(data => {
  liveJevAvailable = data.live_jev === true;
  if (liveJevAvailable) controllerSelect.querySelector<HTMLOptionElement>('option[value="jev"]')!.hidden = false;
  if (!liveJevAvailable) controllerSelect.querySelector('option[value="jev"]')?.remove();
  updateControllerUi();
}).catch(() => { liveJevAvailable = false; refreshGhostStatus(); });

if (!pagesRuntime) fetch("/api/models")
  .then((res) => (res.ok ? res.json() : Promise.reject()))
  .then(({ models }: { models: string[] }) => {
    modelSelect.replaceChildren(
      ...(models.length ? models.map((m) => new Option(m, m)) : [new Option("No Codex models", "")]),
    );
    if (models.length) controllerSelect.querySelector<HTMLOptionElement>('option[value="codex"]')!.hidden = false;
    if (!models.length) {modelSelect.options[0].disabled = true; controllerSelect.querySelector('option[value="codex"]')?.remove();}
    updateControllerUi();
  })
  .catch(() => {
    modelSelect.innerHTML = "<option disabled>Models unavailable</option>";
  });

function updateTimingLabels() {
  const controller = controllerSelect.value;
  const model = controller === "jev" ? `Jev ${jevModelSelect.selectedOptions[0]?.text}` : controller === "codex" ? modelSelect.value || "Codex" : controller === "human" ? "Human pilot" : "Baseline";
  const mode = ["jev", "codex"].includes(controller) ? byId<HTMLSelectElement>("timingMode").value : "realtime";
  byId("configureToggle").textContent = `${model}${["jev", "codex"].includes(controller) ? ` · ${displayedRate}` : ""} ▾`;
  byId("overlayCadence").textContent = controller === "human" ? "Manual" : `${mode} · ${displayedRate}`;
  byId("effectiveRate").textContent = displayedRate;
  byId("cadenceValue").textContent = displayedMeanLatency;
}

function clearDecisionView() {
  displayedRate = "— Hz"; displayedMeanLatency = "— ms"; lastMetricUpdate = performance.now();
  updateTimingLabels();
  allDecisions = [];
  lastDecisionCount = -1;
  lastDecisionInfo = null;
  lastRenderedDecisionCall = -1;
  lastDetailedDecisionCall = -1;
  lastShownControls = null;
  for (const id of ["historyCardsList", "fullHistoryTableBody", "topProbBars", "axisMarginalsGrid", "inputSummaryGrid", "transitionGrid", "observedGrid", "allOptionsTableBody"]) byId(id).replaceChildren();
  lastAxisChoices = {};
  byId("decisionState").textContent = "WAITING";
  byId("decisionState").removeAttribute("data-state");
  byId("decisionSequence").textContent = "#—";
  byId("decisionLatency").textContent = "— ms";
  for (const id of ["decisionInputTime", "decisionInputFlight", "decisionInputRunway", "decisionInputWind", "decisionInputControls", "decisionInputMotion"]) byId(id).textContent = "—";
  byId("overlayDecisionStatus").textContent = "MODEL DECISION";
  byId("overlayDecisionText").textContent = "Awaiting first response";
  for (const axis of ["aileron", "elevator", "rudder", "throttle"]) {
    const key = `decision${axis[0].toUpperCase()}${axis.slice(1)}`;
    byId(key).textContent = "—";
    byId(`${key}Value`).textContent = "—";
    byId(`${key}Change`).textContent = "—";
    byId(`${key}Change`).removeAttribute("data-change");
    byId(`${key}Marker`).style.left = "50%";
    byId(`${axis}Delta`).textContent = "Δ —";
  }
  byId("rawInputCodeBlock").textContent = "No decision input yet.";
  byId("jointCodePill").textContent = "—";
  byId("jointConfidenceBadge").textContent = "No decision yet";
  byId("chipDecisionNum").querySelector("strong")!.textContent = "#—";
  byId("chipLatency").querySelector("strong")!.textContent = "— ms";
  byId("chipStateAge").querySelector("strong")!.textContent = "— ms";
  byId("effectiveRate").textContent = "— Hz";
  byId("jointSourceBadge").textContent = "—";
  byId("jointStabilityBadge").style.display = "none";
  byId("actionCount").textContent = "—";
}

byId("start").addEventListener("click", () => {
  if (runState !== "ready" && runState !== "complete") return;
  const seedInput = byId<HTMLInputElement>("seed");
  if (scenarioSelect.value !== "easy" && !seedInput.reportValidity()) return;
  if (controllerSelect.value === "codex" && !modelSelect.value) { showError("No Codex model is available. Check local authentication and refresh."); return; }
  closeDialog("outcomeModal");
  hideError();
  clearDecisionView();
  centerSurfaces(controls);
  showControls(controls);
  const config: RunConfig = {
    scenario: scenarioSelect.value,
    controller: controllerSelect.value,
    mode: ["jev", "codex"].includes(controllerSelect.value) ? byId<HTMLSelectElement>("timingMode").value : "realtime",
    decision_schedule: ["jev", "codex"].includes(controllerSelect.value) ? "continuous" : "fixed",
    seed: scenarioSelect.value === "easy" ? 42 : Number(seedInput.value),
    decision_hz: 2,
    time_scale: 1,
    realtime_response_policy: "apply-on-arrival",
    human_assistance: { auto_center: autoCenterEnabled, wing_leveler: wingLevelerEnabled },
    model: controllerSelect.value === "codex" ? modelSelect.value : controllerSelect.value === "jev" ? jevModelSelect.value : null,
    reasoning_effort: controllerSelect.value === "codex" ? reasoningEffortSelect.value : "low",
  };
  const opponents = [...selectedGhosts].filter(choice => choice.startsWith("live:")).map(choice => choice.slice(5));
  if (!send({ type: opponents.length ? "start_race" : "start", ...config, ...(opponents.length ? {opponents} : {}) })) { transitionRun("disconnect"); return; }
  startGhosts(config);
  updateControllerUi();
  setCamera(cameraMode);
  transitionRun("start");
});
byId("stop").addEventListener("click", () => {
  if ((runState === "running" || liveRunning() || spectatorRunning) && send({ type: "stop" })) {
    dismissingRace = true;
    spectatorRunning = false;
    byId<HTMLButtonElement>("stop").disabled = true;
    if (!activeRunId && watchedGhost && !liveRunning()) finishSpectating(watchedGhost);
  }
});
byId("reset").addEventListener("click", () => {
  const wasDismissing = dismissingRace;
  dismissingRace = true; resettingRace = true;
  if (!send({ type: "reset" })) { dismissingRace = wasDismissing; resettingRace = false; return; }
  liveOpponents.clear();
  clearGhosts(); watchedGhost = null; spectatorRunning = false;
  raceTime = replayTime = renderRaceTime = 0;
  primaryResultButton.hidden = true;
  updateControllerUi();
  closeDialog("outcomeModal");
  hideError();
  clearDecisionView();
  lastObservation = null;
  byId("windSpeed").textContent = "— m/s"; byId("windBearing").textContent = "From —°";
  byId("windVertical").textContent = "Awaiting flight";
  centerSurfaces(controls);
  showControls(controls);
  desiredPosition.set(-1500, 94, 0);
  desiredQuaternion.identity();
  aircraft.position.copy(desiredPosition);
  aircraft.quaternion.identity();
  setCamera(cameraMode);
  for (const id of ["hudAgl", "hudIas", "hudVsi", "hudFpa", "hudXtrack", "hudGlide", "hudHdgErr", "hudAoa", "stripAlong", "stripThresh", "stripRoll", "stripPitch", "stripWind", "stripScore"]) byId(id).textContent = "—";
  byId("stripPhase").textContent = "READY";
  transitionRun("reset");
});

function cameraSubject(): THREE.Object3D {
  return activeGhosts.find(ghost => ghost.run === watchedGhost)?.visual ?? aircraft;
}
function updateSpectatorLabel() {
  const label = activeGhosts.find(ghost => ghost.run === watchedGhost)?.label ?? "Jev";
  byId("flightStatePill").textContent = `WATCHING ${label.toUpperCase()}`;
  byId("overlayController").textContent = `WATCHING ${label.toUpperCase()}`;
  byId("runStatus").textContent = Boolean(liveEntry(watchedGhost)) ? "Watching live opponent" : `Watching ${label}`;
}
function followRemainingOpponent(): boolean {
  // Another pilot finishing must not restart the current spectator view.
  if (watchedGhost && liveEntry(watchedGhost)?.runId) return true;
  const next = [...liveOpponents.values()].find(entry => entry.runId)?.run ?? activeGhosts.find(({run}) => !liveEntry(run) && run.samples.at(-1)!.time > replayTime)?.run;
  if (!next) return false;
  watchedGhost = next; spectatorRunning = true;
  closeDialog("outcomeModal");
  clearDecisionView();
  updateControllerUi();
  const liveState = liveEntry(next)?.state;
  if (liveState) {
    raceTime = liveState.observation.time_s;
    updateHudAndTelemetry(liveState);
  } else if (!liveEntry(next)) {
    raceTime = replayTime;
    renderRaceTime = replayTime;
  }
  // Snap to the new subject before smoothing subsequent motion.
  const visual = cameraSubject();
  if (next.samples.length) {
    const pose = poseAt(next.samples, raceTime);
    visual.position.copy(pose.position); visual.quaternion.copy(pose.quaternion);
  }
  camera.position.copy(visual.position).add(chaseOffset.clone().applyQuaternion(visual.quaternion));
  setCamera(cameraMode);
  if (!liveEntry(next)) {
    for (const id of ["hudAgl", "hudIas", "hudVsi", "hudFpa", "hudXtrack", "hudGlide", "hudHdgErr", "hudAoa", "stripAlong", "stripThresh", "stripRoll", "stripPitch", "stripWind", "stripScore"]) byId(id).textContent = "—";
    byId("stripPhase").textContent = "REPLAY";
  }
  updateSpectatorLabel();
  byId<HTMLButtonElement>("stop").disabled = false;
  return true;
}
function finishSpectating(run: Ghost) {
  spectatorRunning = false;
  byId<HTMLButtonElement>("stop").disabled = !activeRunId && !liveRunning();
  const label = activeGhosts.find(ghost => ghost.run === run)?.label ?? "Jev";
  byId("flightStatePill").textContent = `${label.toUpperCase()} FINISHED`;
  byId("runStatus").textContent = `${label} · ${outcomeLabel(run.status, run.success)}`;
  showRaceResults();
}

// Camera controls
function setCamera(mode: typeof cameraMode) {
  startCameraUntil = 0;
  startViewPending = false;
  cameraMode = mode;
  orbit.enabled = mode === "orbit";
  if (mode === "chase") {
    const subject = cameraSubject();
    camera.position.copy(subject.position).add(chaseOffset.clone().applyQuaternion(subject.quaternion));
    lastChaseTarget.copy(subject.position);
  }
  if (orbit.enabled) {
    const subject = cameraSubject();
    // Preserve the camera offset when changing the orbit center.
    orbit.target.copy(subject.position);
    lastOrbitTarget.copy(subject.position);
    if (camera.position.distanceTo(subject.position) > orbit.maxDistance) camera.position.copy(subject.position).add(chaseOffset);
    orbit.update();
  }
  document.querySelectorAll<HTMLButtonElement>("[data-camera]").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.camera === mode);
  });
}
document.querySelectorAll<HTMLButtonElement>("[data-camera]").forEach((btn) => {
  btn.addEventListener("click", () => setCamera(btn.dataset.camera as typeof cameraMode));
});

// Animation & Render Loop
let previous = performance.now();
let lastHumanSend = 0;
const compassForward = new THREE.Vector3();

function animate(now: number) {
  requestAnimationFrame(animate);
  const dt = Math.min((now - previous) / 1000, 0.05);
  previous = now;
  updateEdgeLights(now);
  windsock.update(lastObservation?.environment ?? {headwind_mps: 0, crosswind_mps: 0}, now / 1000, dt, reducedMotion.matches);
  byId("windArrow").setAttribute("transform", `rotate(${windsock.sourceBearingDeg} 40 40)`);
  byId("windArrow").style.visibility = lastObservation?.environment && windsock.speedMps > .05 ? "visible" : "hidden";
  if (lastObservation?.environment) {
    byId("windSpeed").textContent = `${windsock.speedMps.toFixed(1)} m/s`;
    byId("windBearing").textContent = windsock.speedMps > .05 ? `From ${Math.round(windsock.sourceBearingDeg) % 360}°` : "Calm";
    const vertical = windsock.verticalMps;
    byId("windVertical").textContent = Math.abs(vertical) >= .05 ? `${vertical > 0 ? "↑" : "↓"} ${Math.abs(vertical).toFixed(1)} m/s vertical` : "Horizontal wind";
  }

  // Background recordings keep playing even when the watched live pilot waits or changes.
  if (spectatorRunning) replayTime += dt;
  if (spectatorRunning && watchedGhost && !liveEntry(watchedGhost)) {
    raceTime = Math.min(replayTime, watchedGhost.samples.at(-1)!.time);
    if (replayTime >= watchedGhost.samples.at(-1)!.time && !followRemainingOpponent()) finishSpectating(watchedGhost);
  }
  renderRaceTime = smoothReplayTime(renderRaceTime, replayTime, dt);
  for (const ghost of activeGhosts) {
    if (!ghost.visual.getObjectByName("aircraftGLB") && aircraft.getObjectByName("aircraftGLB")) {
      scene.remove(ghost.visual);
      ghost.visual = createGhostVisual(ghost.color);
      scene.add(ghost.visual);
    }
    const { run, visual } = ghost;
    const live = liveEntry(run);
    if (live?.state) live.renderTime = smoothReplayTime(live.renderTime, live.state.observation.time_s, dt);
    const pose = poseAt(run.samples, live ? live.renderTime : renderRaceTime);
    visual.visible = true; visual.position.copy(pose.position); visual.quaternion.copy(pose.quaternion);
    if (live ? live.runId : renderRaceTime < run.samples.at(-1)!.time) spinGhostPropeller(visual, dt);

  }
  if (activeGhosts.length) {
    if (ghostLegend.children.length !== activeGhosts.length + 1) {
      ghostLegend.replaceChildren(document.createElement("strong"));
      for (const color of activeGhosts.map(ghost => ghost.color)) {
        const row = document.createElement("div"); row.className = "race-legend-row"; raceAccent(row, color); ghostLegend.append(row);
      }
    }
    ghostLegend.children[0].textContent = `Race · ${raceTime.toFixed(1)} s`;
    activeGhosts.forEach(({run, label}, i) => {
      const live = liveEntry(run);
      const playing = live ? Boolean(live.runId) : replayTime < run.samples.at(-1)!.time;
      const status = playing ? live ? "Live" : "Replaying" : outcomeLabel(run.status, run.success);
      ghostLegend.children[i + 1].textContent = `${label} · ${status} · ${run.score.toFixed(1)} pts`;
    });
  }
  aircraft.position.lerp(desiredPosition, 1 - Math.exp(-10 * dt));
  aircraft.quaternion.slerp(desiredQuaternion, 1 - Math.exp(-10 * dt));
  // Instruments follow flight attitude immediately, without the scene's visual smoothing.
  const compassAttitude = watchedGhost?.samples.length
    ? poseAt(watchedGhost.samples, liveEntry(watchedGhost)?.state?.observation.time_s ?? raceTime).quaternion
    : desiredQuaternion;
  const nose = compassForward.set(1, 0, 0).applyQuaternion(compassAttitude);
  const heading = (Math.atan2(nose.z, nose.x) * 180 / Math.PI + 360) % 360;
  byId("headingNeedle").setAttribute("transform", `rotate(${heading} 40 40)`);
  const headingDegrees = Math.round(heading) % 360;
  byId("compassHeading").textContent = `${headingDegrees > 180 ? headingDegrees - 360 : headingDegrees}°`;
  sun.position.copy(cameraSubject().position).add(sunOffset);

  const propeller = aircraft.userData.propeller as THREE.Object3D | undefined;
  if (propeller && runState === "running") propeller.rotation.z += dt * (20 + controls.throttle * 90);

  if (controllerSelect.value === "human" && runState === "running") {
    const f = lastObservation?.flight;
    const r = lastObservation?.runway;
    const s = lastObservation?.status;
    updateHumanControls(controls, pressed, dt, {
      autoCenter: autoCenterEnabled,
      wingLeveler: wingLevelerEnabled,
      currentRollDeg: f?.roll_deg ?? lastKnownRollDeg,
      rollRateRadS: f?.p_rad_s ?? 0,
      currentPitchDeg: f?.pitch_deg ?? 0,
      verticalSpeedMps: f?.vertical_speed_mps ?? 0,
      pitchRateRadS: f?.q_rad_s ?? 0,
      altitudeAglM: r?.altitude_agl_m ?? 50,
      crossTrackErrorM: r?.centerline_offset_m ?? r?.cross_track_error_m ?? 0,
      headingErrorDeg: r?.heading_error_deg ?? 0,
      glideslopeErrorDeg: r?.glideslope_error_deg ?? 0,
      yawRateRadS: f?.r_rad_s ?? 0,
      airspeedMps: f?.airspeed_mps ?? 29,
      onGround: s?.on_ground ?? false,
    });
    showControls(controls);
    updateAssistPill();
    if (now - lastHumanSend > 33) {
      send({ type: "action", action: controls });
      lastHumanSend = now;
    }
  }

  const subject = cameraSubject();
  canvas.dataset.subject = watchedGhost ? "opponent" : "primary";
  canvas.dataset.camera = cameraMode;
  if (cameraMode === "chase") {
    updateChasePosition(camera.position, subject.position, lastChaseTarget, subject.quaternion, chaseOffset, dt, now < startCameraUntil && !reducedMotion.matches);
    camera.up.set(0, 1, 0);
    const lookBlend = reducedMotion.matches ? 1 : THREE.MathUtils.clamp(1 - (startCameraUntil - now) / 300, 0, 1);
    const lookTarget = subject.position.clone().add(chaseLookAtOffset.clone().multiplyScalar(lookBlend).applyQuaternion(subject.quaternion));
    camera.lookAt(lookTarget);
  } else if (cameraMode === "orbit") {
    const delta = subject.position.clone().sub(lastOrbitTarget);
    camera.position.add(delta);
    orbit.target.copy(subject.position);
    lastOrbitTarget.copy(subject.position);
    orbit.update();
  } else {
    // Tower camera fixed near threshold looking at aircraft
    camera.position.set(-15, 6, 25);
    camera.up.set(0, 1, 0);
    camera.lookAt(subject.position);
  }

  camera.updateMatrixWorld();
  for (const ghost of activeGhosts) {
    const projected = ghost.visual.position.clone().add(new THREE.Vector3(0, 3, 0)).project(camera);
    const bounds = ghostLegend.parentElement!.getBoundingClientRect();
    ghost.marker.hidden = projected.z < -1 || projected.z > 1 || Math.abs(projected.x) > 1 || Math.abs(projected.y) > 1;
    ghost.marker.style.left = `${(projected.x + 1) * bounds.width / 2}px`;
    ghost.marker.style.top = `${(1 - projected.y) * bounds.height / 2}px`;
  }
  renderer?.render(scene, camera);
}
requestAnimationFrame(animate);

function resizeCanvas() {
  positionConfigPanels();
  if (!renderer) return;
  const container = byId<HTMLElement>("viewport").parentElement;
  const width = container ? container.clientWidth : innerWidth;
  const height = container ? container.clientHeight : innerHeight;
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
  renderer.setSize(width, height);
}
new ResizeObserver(resizeCanvas).observe(canvas.parentElement!);
addEventListener("resize", resizeCanvas);
setTimeout(resizeCanvas, 100);

connect();
