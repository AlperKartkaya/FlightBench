import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import type { Control } from "./controls.ts";
import { updateHumanControls, defaultControls, adjustControl, centerSurfaces } from "./controls.ts";
import { nextRunState, outcomeLabel, touchdownValues } from "./results.ts";
import type { RunState, RunEvent, RunRecord, RunConfig, Outcome } from "./results.ts";
import { isRunwayLightOn } from "./runway-lights.ts";
import "./style.css";

type Observation = {
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
    <div class="brand-section"><strong class="brand-title">FlightBench</strong><a class="profile-link profile-github" href="https://github.com/alperkartkaya" target="_blank" rel="noopener noreferrer" aria-label="AlperKartkaya on GitHub"><svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 .5a11.5 11.5 0 0 0-3.64 22.4c.58.1.79-.25.79-.56v-2.02c-3.22.7-3.9-1.37-3.9-1.37-.52-1.33-1.28-1.68-1.28-1.68-1.05-.72.08-.71.08-.71 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.7 1.26 3.36.96.1-.75.4-1.26.73-1.55-2.57-.29-5.27-1.29-5.27-5.73 0-1.27.45-2.3 1.19-3.12-.12-.29-.52-1.48.11-3.08 0 0 .97-.31 3.16 1.19a11 11 0 0 1 5.75 0c2.19-1.5 3.15-1.19 3.15-1.19.63 1.6.24 2.79.12 3.08.74.82 1.18 1.85 1.18 3.12 0 4.45-2.7 5.43-5.28 5.72.41.36.78 1.07.78 2.16v3.19c0 .31.21.67.79.56A11.5 11.5 0 0 0 12 .5Z"/></svg><span>AlperKartkaya</span></a><a class="profile-link profile-linkedin" href="https://www.linkedin.com/in/alper-kartkaya-boun-cmpe" target="_blank" rel="noopener noreferrer" aria-label="Alper Kartkaya on LinkedIn"><svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M20.45 2H3.55C2.7 2 2 2.67 2 3.5v17C2 21.33 2.7 22 3.55 22h16.9c.85 0 1.55-.67 1.55-1.5v-17c0-.83-.7-1.5-1.55-1.5ZM8 18.75H4.9V9H8v9.75ZM6.45 7.66a1.8 1.8 0 1 1 0-3.6 1.8 1.8 0 0 1 0 3.6Zm12.3 11.09h-3.1V14c0-1.13-.02-2.58-1.57-2.58-1.57 0-1.81 1.23-1.81 2.5v4.83h-3.1V9h2.98v1.33h.04c.42-.78 1.43-1.6 2.94-1.6 3.15 0 3.62 2.07 3.62 4.76v5.26Z"/></svg><span>Alper Kartkaya</span></a></div>
    <div class="status-group"><span class="sr-only" id="runStatus" role="status">Connecting…</span><span class="flight-state-pill" id="flightStatePill" data-state="IDLE">IDLE</span><i class="status-dot" id="connectionDot" aria-hidden="true"></i><span id="connectionText" role="status">OFFLINE</span></div>
  </header>
  <main class="workspace">
    <!-- Simulation Center Column (~74%) -->
    <section class="sim-column">
      <div class="viewport-container">
        <canvas id="viewport" aria-label="3D flight simulation"></canvas>
        <div id="renderUnavailable" class="render-unavailable" hidden><strong>3D view unavailable</strong><p>This browser could not initialize WebGL. Telemetry, controls and saved results still work. Try a browser with hardware acceleration enabled.</p></div>

        <div class="viewer-toolbar" id="viewerToolbar">
          <button class="btn-secondary" id="configureToggle" type="button" aria-label="Flight settings" aria-controls="configPanel" aria-expanded="false">Baseline · 2 Hz ▾</button>
          <button class="btn-primary" id="start" disabled>Start flight</button><button class="btn-secondary" id="stop" aria-label="Stop and save" disabled>Stop</button><button class="btn-secondary" id="reset" disabled>Reset</button>
          <div class="viewer-config-panel" id="configPanel" hidden>
            <fieldset id="experimentSettings"><legend class="sr-only">Experiment settings</legend>
              <div class="config-group">
                <div class="config-item"><label for="controller">Controller</label><select id="controller" class="select-input">
                  <option value="baseline" selected>Baseline · rule-based</option><option value="human">Human pilot</option>
                  <option value="jev">Jev · experimental</option><option value="codex">Codex model</option>
                  <option value="hold">Hold · negative control</option><option value="random">Random · negative control</option></select></div>
                <div class="config-item" id="modelGroup" hidden><label for="model">Model</label><select id="model" class="select-input"></select></div>
                <div class="config-item" id="decisionRateGroup"><label for="decisionRate">Decision rate</label><select id="decisionRate" class="select-input"><option value="2" selected>2 Hz</option><option value="5">5 Hz</option><option value="10">10 Hz</option></select></div>
                <div class="config-item"><label for="seed">Seed</label><input class="number-input" id="seed" type="number" value="42" min="0" max="4294967295" step="1" required /></div>
              </div>
            </fieldset>
          </div>
        </div>

        <!-- Primary HUD (Top-Left Canvas Overlay) -->
        <div class="hud-overlay">
          <div class="hud-panel">
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

        <div class="flight-readout" aria-label="Live controller and actuator output">
          <div class="flight-readout-head"><strong id="overlayController">Baseline Controller</strong><span id="overlayCadence">2 Hz</span></div>
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
            <span>⚡</span>
            <strong id="ctrlBrandTitle">TypeSafe Jev</strong>
          </div>
          <span class="jev-model-tag" id="ctrlModelTag">System One</span>
        </div>
        <div class="ctrl-chips-row">
          <div class="meta-chip" id="chipDecisionNum">Applied <strong>#—</strong></div>
          <div class="meta-chip">Cadence <strong id="cadenceValue">2 Hz</strong></div>
          <div class="meta-chip">Effective Rate <strong id="effectiveRate">— Hz</strong></div>
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

      <details class="diagnostics"><summary>Decision diagnostics</summary>
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
            <button class="ctrl-btn" data-axis="elevator" data-dir="-1" title="Nose Up (Key S)">
              <span>▲ Nose Up</span>
              <kbd>S</kbd>
            </button>
            <button class="ctrl-btn" data-axis="elevator" data-dir="1" title="Nose Down (Key W)">
              <span>▼ Nose Down</span>
              <kbd>W</kbd>
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
            <button class="ctrl-btn" data-axis="aileron" data-dir="-1" title="Bank Left (Key A)">
              <span>◄ Bank Left</span>
              <kbd>A</kbd>
            </button>
            <button class="ctrl-btn" data-axis="aileron" data-dir="1" title="Bank Right (Key D)">
              <span>► Bank Right</span>
              <kbd>D</kbd>
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
      <div class="outcome-stats-grid">
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
  new THREE.PlaneGeometry(1000, 30),
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
for (const z of [-14.5, 14.5]) {
  const edge = new THREE.Mesh(
    new THREE.PlaneGeometry(1000, 0.35),
    markingMaterial,
  );
  edge.rotation.x = -Math.PI / 2;
  edge.position.set(500, 0.06, z);
  markings.add(edge);
}
for (const z of [-10, -6, -2, 2, 6, 10]) {
  const threshold = new THREE.Mesh(
    new THREE.PlaneGeometry(20, 1.2),
    markingMaterial,
  );
  threshold.rotation.x = -Math.PI / 2;
  threshold.position.set(12, 0.061, z);
  markings.add(threshold);
}
scene.add(markings);

const edgeLightPositions: number[] = [];
// Twenty rows make the four-row cadence wrap without a double-lit pause.
for (let x = 25; x < 1000; x += 50) {
  for (const z of [-16, 16]) edgeLightPositions.push(x, 0.3, z);
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
    "/models/aircraft.glb",
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
const desiredPosition = aircraft.position.clone();
const desiredQuaternion = aircraft.quaternion.clone();
const lastOrbitTarget = aircraft.position.clone();

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
  if (!boundKeys.has(event.code)) return;
  if (!event.code.startsWith("Digit") && (runState !== "running" || controllerSelect.value !== "human")) return;
  event.preventDefault();
  if (["Digit1", "Digit2", "Digit3"].includes(event.code)) {
    setCamera(({ Digit1: "chase", Digit2: "orbit", Digit3: "tower" } as const)[event.code as "Digit1" | "Digit2" | "Digit3"]);
    return;
  }
  if (event.code === "KeyC" || event.code === "KeyX") {
    centerSurfaces(controls);
    showControls(controls);
    if (controllerSelect.value === "human") send({ type: "action", action: controls });
    return;
  }
  if (!event.repeat) {
    if (!autoCenterEnabled) {
      if (event.code === "KeyW") adjustControl(controls, "elevator", 0.04);
      else if (event.code === "KeyS") adjustControl(controls, "elevator", -0.04);
      else if (event.code === "KeyA") adjustControl(controls, "aileron", -0.04);
      else if (event.code === "KeyD") adjustControl(controls, "aileron", 0.04);
      else if (event.code === "KeyQ") adjustControl(controls, "rudder", 0.04);
      else if (event.code === "KeyE") adjustControl(controls, "rudder", -0.04);
    }
    if (event.code === "KeyR") adjustControl(controls, "throttle", 0.05);
    else if (event.code === "KeyF") adjustControl(controls, "throttle", -0.05);
    showControls(controls);
    if (controllerSelect.value === "human") send({ type: "action", action: controls });
  }
  pressed.add(event.code);
});
addEventListener("keyup", (event) => pressed.delete(event.code));
addEventListener("blur", () => pressed.clear());

// Interactive Manual Controls
function setupInteractiveControls() {
  const btnKeyMap: Record<string, string> = {
    "elevator:-1": "KeyS",
    "elevator:1": "KeyW",
    "aileron:-1": "KeyA",
    "aileron:1": "KeyD",
    "rudder:1": "KeyQ",
    "rudder:-1": "KeyE",
    "throttle:1": "KeyR",
    "throttle:-1": "KeyF",
  };

  let repeatTimer: number | null = null;
  let intervalTimer: number | null = null;

  const stopRepeat = () => {
    if (repeatTimer !== null) { clearTimeout(repeatTimer); repeatTimer = null; }
    if (intervalTimer !== null) { clearInterval(intervalTimer); intervalTimer = null; }
  };

  document.querySelectorAll<HTMLButtonElement>(".ctrl-btn").forEach((btn) => {
    const axis = btn.dataset.axis as keyof Control | undefined;
    const dir = Number(btn.dataset.dir || 0);
    if (!axis || !dir) return;

    const mappedKey = btnKeyMap[`${axis}:${dir}`];

    const startAction = (e: Event) => {
      e.preventDefault();
      if (runState !== "running") return;
      if (mappedKey) pressed.add(mappedKey);

      if (!autoCenterEnabled || axis === "throttle") {
        const delta = axis === "throttle" ? dir * 0.05 : dir * 0.04;
        const continuousDelta = axis === "throttle" ? dir * 0.02 : dir * 0.015;
        adjustControl(controls, axis, delta);
        showControls(controls);
        if (controllerSelect.value === "human") send({ type: "action", action: controls });

        stopRepeat();
        repeatTimer = window.setTimeout(() => {
          intervalTimer = window.setInterval(() => {
            adjustControl(controls, axis, continuousDelta);
            showControls(controls);
            if (controllerSelect.value === "human") send({ type: "action", action: controls });
          }, 40);
        }, 220);
      }
    };

    const stopAction = () => {
      if (mappedKey) pressed.delete(mappedKey);
      stopRepeat();
    };

    btn.addEventListener("keydown", (event) => {
      if ((event.code === "Space" || event.code === "Enter") && !event.repeat) startAction(event);
    });
    btn.addEventListener("keyup", stopAction);
    btn.addEventListener("blur", stopAction);
    btn.addEventListener("mousedown", startAction);
    btn.addEventListener("touchstart", startAction, { passive: false });
    btn.addEventListener("mouseup", stopAction);
    btn.addEventListener("mouseleave", stopAction);
    btn.addEventListener("touchend", stopAction);
    btn.addEventListener("touchcancel", stopAction);
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
    pressed.has("KeyW") || pressed.has("KeyS") ||
    pressed.has("KeyA") || pressed.has("KeyD") ||
    pressed.has("KeyQ") || pressed.has("KeyE");
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
  if (busy) setConfigOpen(false);
  byId<HTMLButtonElement>("start").disabled = busy || runState === "offline";
  byId<HTMLButtonElement>("stop").disabled = runState !== "running";
  byId<HTMLButtonElement>("reset").disabled = runState === "starting" || runState === "offline";
  for (const id of ["autoCenterToggle", "wingLevelerToggle"]) byId<HTMLInputElement>(id).disabled = busy;
  const text: Record<RunState, string> = {
    offline: "Disconnected", ready: "Ready", starting: "Initializing controller…",
    running: "In flight", complete: "Saved",
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

function updateLiveDecision(info: DecisionInfo, call: number, latencyMs: number | null) {
  if (call <= lastRenderedDecisionCall || (!info.choices && !info.command)) return;
  lastRenderedDecisionCall = call;
  if (info.controller === "jev" && info.input?.flight && info.input.runway) {
    const { flight, runway, current_controls: controls, motion, status, phase, time_s } = info.input;
    const num = (value: number | undefined, digits = 1) => value == null ? "—" : value.toFixed(digits);
    const signed = (value: number | undefined, digits = 1) => value == null ? "—" : `${value >= 0 ? "+" : ""}${value.toFixed(digits)}`;
    byId("decisionInputTime").textContent = `${phase ?? "—"} · t=${num(time_s)}s`;
    byId("decisionInputFlight").textContent = `IAS ${num(flight.airspeed_mps)} · V/S ${signed(flight.vertical_speed_mps)} · Roll ${signed(flight.roll_deg)}° · Pitch ${signed(flight.pitch_deg)}°`;
    byId("decisionInputRunway").textContent = `AGL ${num(runway.altitude_agl_m)}m · Offset ${signed(runway.centerline_offset_m ?? runway.cross_track_error_m)}m · Glide ${signed(runway.glideslope_error_deg)}° · Hdg ${signed(runway.heading_error_deg)}°`;
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
  if (info.live_status) {
    const cadence = `${info.live_status.cadence_hz} Hz`;
    byId("cadenceValue").textContent = cadence;
    byId("overlayCadence").textContent = cadence;
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
    byId("effectiveRate").textContent = s.effective_decision_hz == null ? "— Hz" : `${s.effective_decision_hz.toFixed(1)} Hz`;
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
    byId("jointSourceBadge").textContent = isJev ? "MODEL · EXPERIMENTAL" : "CODEX MODEL";
    byId("jointStabilityBadge").style.display = "none";
    byId("actionCount").textContent = "4 axes";
    byId("axisMarginalsSection").style.display = "none";
    byId("openAllOptionsBtn").style.display = "none";
    byId("toggleMarginalsBtn").style.display = "none";
    byId("inputSummaryGrid").textContent = "View the exact flight state supplied to the model. Proposed choices below are not proof of application; the actuator panel shows backend-applied controls.";
    for (const id of ["consequenceCard", "decisionHistoryCard"]) byId(id).style.display = "none";
    const commands = info.command || Object.fromEntries(Object.entries(info.choices!).map(([axis, choice]) => [axis, choice.command!]));
    const rows = Object.entries(commands).map(([axis, command]) => {
      const choice = info.choices?.[axis];
      const row = document.createElement("p");
      row.textContent = `${axis}: ${command.toFixed(3)}` + (choice ? ` · confidence ${choice.confidence == null ? "N/A" : (choice.confidence * 100).toFixed(0) + "%"} — ${choice.label}` : "");
      return row;
    });
    byId("topProbBars").replaceChildren(...rows);
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
  byId("stripScore").textContent = message.score.toFixed(1);

  if (runState === "running") {
    byId("flightStatePill").textContent = message.status === "running" ? "IN FLIGHT" : outcomeLabel(message.status, message.result?.success);
  }
  updateDecisionCards(message.decision_info, message.decision_count, message.latency_ms);
}

function showOutcomeModal(record: RunRecord) {
  const result = record.outcome;
  const success = Boolean(result.success);
  byId("outcomeCard").className = `modal-card outcome-modal-card ${success ? "landed" : ""}`;
  byId("outcomeTitle").className = `outcome-title ${success ? "landed" : ""}`;
  byId("outcomeIcon").textContent = success ? "✓" : "—";
  byId("outcomeTitle").textContent = outcomeLabel(result.status, success);
  byId("outcomeDesc").textContent = success
    ? "Safe main-gear contact and rollout completed. Values below are frozen at touchdown."
    : `Recorded outcome: ${outcomeLabel(result.status)}. ${result.touchdown ? "Values below are frozen at touchdown." : "No main-gear touchdown was recorded."}`;
  byId("outcomeScoreVal").textContent = `${(result.quality ?? 0).toFixed(1)} / 100`;
  const values = touchdownValues(result);
  ["outcomeIasVal", "outcomeVsiVal", "outcomeXtrackVal", "outcomePitchVal", "outcomeRollVal"].forEach((id, i) => byId(id).textContent = values[i]);
  openDialog("outcomeModal");
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
let reconnectTimer = 0;
function connect() {
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
    activeRunId = null;
    transitionRun("disconnect");
    clearTimeout(reconnectTimer);
    reconnectTimer = window.setTimeout(connect, 1500);
  });

  connection.addEventListener("message", ({ data }) => {
    if (socket !== connection) return;
    try {
      const message = JSON.parse(data);
      if (message.type === "error") {
        transitionRun("error");
        if (message.code === "storage_error") byId<HTMLButtonElement>("stop").disabled = false;
        showError(message.message);
        return;
      }
      if (message.type === "run_started") {
        activeRunId = message.run_id;
        transitionRun("accepted");
        return;
      }
      if (message.type === "run_finished") {
        if (message.run_id !== activeRunId) return;
        activeRunId = null;
        transitionRun("finished");
        showOutcomeModal(message.record);
        return;
      }
      if (message.type === "idle") { transitionRun("reset"); return; }
      if (message.type !== "state" || message.run_id !== activeRunId) return;
      applyFlightBenchState(message as StateMessage);
    } catch (error) {
      console.error("Failed to process backend telemetry", error);
      showError("Telemetry stream error");
    }
  });
}

function applyFlightBenchState(message: StateMessage) {
  desiredPosition.fromArray(message.position);
  desiredQuaternion.fromArray(message.quaternion).normalize();

  updateHudAndTelemetry(message);
  if (byId<HTMLSelectElement>("controller").value !== "human") {
    Object.assign(controls, message.observation.controls);
    showControls(controls);
  }
}
function send(message: { type: string; [key: string]: unknown }): boolean {
  if (socket?.readyState !== WebSocket.OPEN) return false;
  if (message.type === "action" && runState !== "running") return false;
  socket.send(JSON.stringify(message));
  return true;
}

const controllerSelect = byId<HTMLSelectElement>("controller");
const modelSelect = byId<HTMLSelectElement>("model");
const manualPanel = byId("manualControlsCard");
function setConfigOpen(open: boolean) {
  byId("configPanel").hidden = !open;
  byId("configureToggle").setAttribute("aria-expanded", String(open));
}
byId("configureToggle").addEventListener("click", () => setConfigOpen(byId("configPanel").hidden));
document.addEventListener("pointerdown", (event) => {
  if (!byId("configPanel").hidden && !byId("viewerToolbar").contains(event.target as Node)) setConfigOpen(false);
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !byId("configPanel").hidden) {
    setConfigOpen(false);
    byId("configureToggle").focus();
  }
});

function updateControllerUi() {
  const isCodex = controllerSelect.value === "codex";
  const isHuman = controllerSelect.value === "human";
  const isJevOrAi = controllerSelect.value === "jev" || isCodex;

  byId("modelGroup").hidden = !isCodex;
  byId("decisionRateGroup").hidden = isHuman;
  byId("cadenceValue").textContent = `${byId<HTMLSelectElement>("decisionRate").value} Hz`;
  byId("overlayCadence").textContent = `${byId<HTMLSelectElement>("decisionRate").value} Hz`;
  byId("configureToggle").textContent = `${controllerSelect.selectedOptions[0]?.textContent?.split(" · ")[0] ?? "Controller"} · ${byId<HTMLSelectElement>("decisionRate").value} Hz ▾`;
  byId("overlayController").textContent = controllerSelect.selectedOptions[0]?.textContent ?? "Controller";
  byId("liveDecisionCard").hidden = !isJevOrAi;
  byId("decisionInput").hidden = controllerSelect.value !== "jev";
  byId("decisionOutputTitle").textContent = controllerSelect.value === "jev" ? "JEV CHOSE · REQUESTED CONTROLS" : "MODEL CHOSE · REQUESTED CONTROLS";
  byId("overlayDecision").hidden = !isJevOrAi;
  if (manualPanel) manualPanel.style.display = isHuman ? "flex" : "none";

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
  if (isHuman) {
    if (brandTitle) brandTitle.textContent = "Human Pilot";
    if (modelTag) modelTag.textContent = "Keyboard Flight Controls";
  } else if (controllerSelect.value === "baseline") {
    if (brandTitle) brandTitle.textContent = "Baseline Controller";
    if (modelTag) modelTag.textContent = "Rule-Based ILS";
  } else if (controllerSelect.value === "hold") {
    if (brandTitle) brandTitle.textContent = "Hold Controller";
    if (modelTag) modelTag.textContent = "Fixed Controls";
  } else if (controllerSelect.value === "random") {
    if (brandTitle) brandTitle.textContent = "Random Controller";
    if (modelTag) modelTag.textContent = "Uniform Random";
  } else if (controllerSelect.value === "jev") {
    if (brandTitle) brandTitle.textContent = "TypeSafe Jev";
    if (modelTag) modelTag.textContent = "jev-1.13.0 · experimental";
  } else if (isCodex) {
    if (brandTitle) brandTitle.textContent = "Codex Controller";
    if (modelTag) modelTag.textContent = modelSelect.value || "Select an authenticated model";
  }

  autoCenterEnabled = byId<HTMLInputElement>("autoCenterToggle").checked;
  wingLevelerEnabled = byId<HTMLInputElement>("wingLevelerToggle").checked;
  updateAssistPill();


}
controllerSelect.addEventListener("change", () => { clearDecisionView(); updateControllerUi(); });
byId("decisionRate").addEventListener("change", updateControllerUi);
updateControllerUi();

fetch("/api/models")
  .then((res) => (res.ok ? res.json() : Promise.reject()))
  .then(({ models }: { models: string[] }) => {
    modelSelect.replaceChildren(
      ...(models.length ? models.map((m) => new Option(m, m)) : [new Option("No Codex models", "")]),
    );
    if (!models.length) modelSelect.options[0].disabled = true;
  })
  .catch(() => {
    modelSelect.innerHTML = "<option disabled>Models unavailable</option>";
  });

function clearDecisionView() {
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
  for (const id of ["decisionInputTime", "decisionInputFlight", "decisionInputRunway", "decisionInputControls", "decisionInputMotion"]) byId(id).textContent = "—";
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
  if (!seedInput.reportValidity()) return;
  if (controllerSelect.value === "codex" && !modelSelect.value) { showError("No Codex model is available. Check local authentication and refresh."); return; }
  closeDialog("outcomeModal");
  hideError();
  clearDecisionView();
  centerSurfaces(controls);
  showControls(controls);
  const config: RunConfig = {
    scenario: "easy",
    controller: controllerSelect.value,
    mode: controllerSelect.value === "codex" ? "lockstep" : "realtime",
    seed: Number(seedInput.value),
    decision_hz: Number(byId<HTMLSelectElement>("decisionRate").value),
    time_scale: 1,
    human_assistance: { auto_center: autoCenterEnabled, wing_leveler: wingLevelerEnabled },
    model: controllerSelect.value === "codex" ? modelSelect.value : null,
  };
  if (!send({ type: "start", ...config })) { transitionRun("disconnect"); return; }
  transitionRun("start");
});
byId("stop").addEventListener("click", () => {
  if (runState === "running" && send({ type: "stop" })) byId<HTMLButtonElement>("stop").disabled = true;
});
byId("reset").addEventListener("click", () => {
  if (!send({ type: "reset" })) return;
  closeDialog("outcomeModal");
  hideError();
  clearDecisionView();
  lastObservation = null;
  centerSurfaces(controls);
  showControls(controls);
  desiredPosition.set(-1500, 94, 0);
  desiredQuaternion.identity();
  aircraft.position.copy(desiredPosition);
  aircraft.quaternion.identity();
  for (const id of ["hudAgl", "hudIas", "hudVsi", "hudFpa", "hudXtrack", "hudGlide", "hudHdgErr", "hudAoa", "stripAlong", "stripThresh", "stripRoll", "stripPitch", "stripScore"]) byId(id).textContent = "—";
  byId("stripPhase").textContent = "READY";
  transitionRun("reset");
});

// Camera controls
function setCamera(mode: typeof cameraMode) {
  cameraMode = mode;
  orbit.enabled = mode === "orbit";
  if (orbit.enabled) {
    orbit.target.copy(aircraft.position);
    lastOrbitTarget.copy(aircraft.position);
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

function animate(now: number) {
  requestAnimationFrame(animate);
  const dt = Math.min((now - previous) / 1000, 0.05);
  previous = now;
  updateEdgeLights(now);

  aircraft.position.lerp(desiredPosition, 1 - Math.exp(-10 * dt));
  aircraft.quaternion.slerp(desiredQuaternion, 1 - Math.exp(-10 * dt));
  sun.position.copy(aircraft.position).add(sunOffset);

  const propeller = aircraft.userData.propeller as THREE.Object3D | undefined;
  if (propeller) propeller.rotation.z += dt * (20 + controls.throttle * 90);

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

  if (cameraMode === "chase") {
    // Chase camera behind and slightly above aircraft, looking down towards runway
    const targetCamPos = aircraft.position.clone().add(chaseOffset.clone().applyQuaternion(aircraft.quaternion));
    camera.position.lerp(targetCamPos, 1 - Math.exp(-6 * dt));
    camera.up.set(0, 1, 0);
    const lookTarget = aircraft.position.clone().add(chaseLookAtOffset.clone().applyQuaternion(aircraft.quaternion));
    camera.lookAt(lookTarget);
  } else if (cameraMode === "orbit") {
    const delta = aircraft.position.clone().sub(lastOrbitTarget);
    camera.position.add(delta);
    orbit.target.copy(aircraft.position);
    lastOrbitTarget.copy(aircraft.position);
    orbit.update();
  } else {
    // Tower camera fixed near threshold looking at aircraft
    camera.position.set(-15, 6, 25);
    camera.up.set(0, 1, 0);
    camera.lookAt(aircraft.position);
  }

  renderer?.render(scene, camera);
}
requestAnimationFrame(animate);

function resizeCanvas() {
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
