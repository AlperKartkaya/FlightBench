// Browser scenario port of environment.py + default V2 scoring. No benchmark writes.
export const FT = 0.3048;
const rad = n => n * Math.PI / 180;
const deg = n => n * 180 / Math.PI;
const round = (n, digits = 4) => Number(n.toFixed(digits));
const wrap = n => ((n + 180) % 360 + 360) % 360 - 180;
const clip = (n, lo = -1, hi = 1) => Math.max(lo, Math.min(hi, n));
export const AXES = ['aileron', 'elevator', 'rudder', 'throttle'];

export const SCENARIOS = {
  easy: {
    start_z_m: [0, 0], heading_offset_deg: [0, 0], altitude_offset_m: [0, 0],
    airspeed_offset_kts: [0, 0], crosswind_mps: [0, 0], headwind_mps: [0, 0], vertical_wind_mps: [0, 0],
  },
  medium: {
    start_z_m: [-35, 35], heading_offset_deg: [-5, 5], altitude_offset_m: [-8, 8],
    airspeed_offset_kts: [-4, 4], crosswind_mps: [-5, 5], headwind_mps: [-2, 6], vertical_wind_mps: [0, 0],
  },
  hard: {
    start_z_m: [-60, 60], heading_offset_deg: [-10, 10], altitude_offset_m: [-18, 18],
    airspeed_offset_kts: [-8, 8], crosswind_mps: [-8, 8], headwind_mps: [-4, 10], vertical_wind_mps: [-1, .5],
  },
};

export function splitmix32(seed) {
  let state = seed >>> 0;
  const next = () => {
    state = (state + 0x9e3779b9) >>> 0;
    let z = state;
    z = Math.imul(z ^ (z >>> 16), 0x85ebca6b) >>> 0;
    z = Math.imul(z ^ (z >>> 13), 0xc2b2ae35) >>> 0;
    z = (z ^ (z >>> 16)) >>> 0;
    return z / 4294967296;
  };
  return (lo, hi) => lo + (hi - lo) * next();
}

export function sampleScenario(scenario = 'easy', seed = 42) {
  if (!SCENARIOS[scenario]) throw Error(`Unknown scenario: ${scenario}`);
  if (scenario === 'easy') {
    return {start_z_m: 0, heading_offset_deg: 0, altitude_offset_m: 0, airspeed_offset_kts: 0,
      base_crosswind_mps: 0, base_headwind_mps: 0, base_vertical_wind_mps: 0};
  }
  const u = splitmix32(seed), r = SCENARIOS[scenario];
  const params = {
    start_z_m: u(...r.start_z_m),
    heading_offset_deg: u(...r.heading_offset_deg),
    altitude_offset_m: u(...r.altitude_offset_m),
    airspeed_offset_kts: u(...r.airspeed_offset_kts),
    base_crosswind_mps: u(...r.crosswind_mps),
    base_headwind_mps: u(...r.headwind_mps),
    base_vertical_wind_mps: u(...r.vertical_wind_mps),
  };
  if (scenario === 'hard') {
    Object.assign(params, {
      gust_amp_x_mps: u(.8, 2.6),
      gust_amp_h_mps: u(.8, 2.4),
      gust_amp_v_mps: u(.15, .55),
      omega1: 2 * Math.PI / u(14, 24),
      omega2: 2 * Math.PI / u(6, 11),
      phase_x1: u(0, 2 * Math.PI),
      phase_x2: u(0, 2 * Math.PI),
      phase_h1: u(0, 2 * Math.PI),
      phase_h2: u(0, 2 * Math.PI),
      phase_v: u(0, 2 * Math.PI),
      veer_deg: u(-18, 18),
    });
  }
  return params;
}

export function windComponents(scenario, params, timeS, altitudeAglM) {
  if (scenario === 'easy') return [0, 0, 0];
  if (scenario === 'medium') return [params.base_headwind_mps, params.base_crosswind_mps, 0];
  const alt = Math.max(0, altitudeAglM);
  const shear = .65 + .35 * Math.min(1.5, (alt / 80) ** .25);
  const veerRad = rad(params.veer_deg * Math.min(1, alt / 90));
  const hw0 = params.base_headwind_mps * shear, xw0 = params.base_crosswind_mps * shear;
  const cosV = Math.cos(veerRad), sinV = Math.sin(veerRad);
  const hwSteady = hw0 * cosV - xw0 * sinV;
  const xwSteady = hw0 * sinV + xw0 * cosV;
  const {omega1: o1, omega2: o2} = params;
  const gustX = params.gust_amp_x_mps * (.65 * Math.sin(o1 * timeS + params.phase_x1) +
    .35 * Math.sin(o2 * timeS + params.phase_x2));
  const gustH = params.gust_amp_h_mps * (.65 * Math.sin(o1 * timeS + params.phase_h1) +
    .35 * Math.sin(o2 * timeS + params.phase_h2));
  const vwScale = Math.min(1, alt / 25);
  const vw = (params.base_vertical_wind_mps + params.gust_amp_v_mps * Math.sin(o2 * timeS + params.phase_v)) * vwScale;
  return [hwSteady + gustH, xwSteady + gustX, vw];
}

export function windPolar(hw, xw) {
  const speed = Math.hypot(hw, xw);
  if (speed < 1e-6) return [0, 0];
  const dir = ((deg(Math.atan2(hw, xw)) % 360) + 360) % 360;
  return [round(speed, 4), round(dir, 2)];
}

export function validateControl(command) {
  if (!command || Object.keys(command).sort().join() !== [...AXES].sort().join() ||
      AXES.some(k => !Number.isFinite(command[k]) || command[k] > 1 ||
        command[k] < (k === 'throttle' ? 0 : -1))) throw Error('Invalid four-channel command');
  return command;
}

export function baseline(o, trim) {
  const r = o.runway, f = o.flight, e = o.environment ?? {};
  const xw = e.crosswind_mps ?? 0, hw = e.headwind_mps ?? 0, vw = e.vertical_wind_mps ?? 0;
  const wSpd = e.wind_speed_mps ?? Math.hypot(hw, xw);
  const crab = clip(-1.85 * xw, -10.5, 10.5);
  const hdgErr = r.heading_error_deg - crab;
  const targetIas = 30 + Math.min(0, hw) + .35 * Math.max(0, hw);
  const gsSink = 1.65 - .052 * hw + .5 * vw;
  const command = {
    aileron: clip(trim.aileron - .013 - .022 * r.centerline_offset_m - .030 * hdgErr -
      .085 * f.roll_deg - .30 * f.p_rad_s),
    elevator: clip(trim.elevator + .12 * r.glideslope_error_deg + .08 * (f.vertical_speed_mps + gsSink) +
      .04 * (f.pitch_deg - 2.5) - .20 * f.q_rad_s),
    rudder: clip(trim.rudder - .03 + .03 * hdgErr - .04 * f.beta_deg - .15 * f.r_rad_s),
    throttle: clip(.5 + .05 * (targetIas - f.airspeed_mps), 0, 1),
  };
  if (r.altitude_agl_m < 20) {
    const wBlend = Math.min(1, wSpd);
    const hwFactor = clip(1 - .035 * hw, .55, 1.15);
    const maxDesc = (-2.4 + .2 * wBlend) * hwFactor + .4 * Math.min(0, vw);
    const targetSink = Math.max(maxDesc, -.35 - (.28 - .03 * wBlend) * Math.max(0, r.altitude_agl_m - 1.4));
    const thrCut = 16 - .6 * Math.max(0, hw);
    command.elevator = clip(-.02 + (.12 - .03 * wBlend) * (f.vertical_speed_mps - targetSink) +
      (.03 + .02 * wBlend) * (f.pitch_deg - (2.5 + .5 * wBlend)) - (.25 - .09 * wBlend) * f.q_rad_s);
    command.throttle = r.altitude_agl_m < thrCut ? 0 : clip(command.throttle - .25 + .02 * Math.max(0, hw), 0, .40);
  }
  return command;
}

export function touchdownSafe(t, c) {
  return Boolean(t && t.along_track_m >= 0 && t.along_track_m <= c.runway_length_m &&
    Math.abs(t.cross_track_m) <= c.runway_width_m / 2 && Math.abs(t.sink_rate_mps) <= c.max_sink_mps &&
    Math.abs(t.roll_deg) <= c.max_bank_deg && Math.abs(t.heading_error_deg) <= c.max_heading_deg &&
    t.airspeed_mps >= c.min_airspeed_mps && t.airspeed_mps <= c.max_airspeed_mps);
}

export function evaluate(t, success, reason, c, trajectory) {
  if (c.version !== 'v2') throw Error('Browser runtime requires default V2 scoring');
  const safe = touchdownSafe(t, c);
  success = Boolean(success && safe);
  const lateral = trajectory.lateral / c.reference_duration_s;
  const pitch = trajectory.pitch / c.reference_duration_s;
  const glide = trajectory.glide / c.reference_duration_s;
  const touchdown = t ? .50 * (Math.abs(t.sink_rate_mps) / c.touchdown_sink_normalization_mps) ** 2 +
    .25 * (Math.abs(t.cross_track_m) / c.touchdown_lateral_normalization_m) ** 2 +
    .25 * (Math.abs(t.along_track_m - c.touchdown_target_m) / c.touchdown_longitudinal_normalization_m) ** 2 : 0;
  const total = .30 * lateral + .25 * pitch + .20 * glide + .25 * touchdown;
  const quality = 100 * Math.exp(-total);
  return {success, quality: round(success ? quality : 0, 3), raw_quality: round(quality, 3), reason,
    touchdown: t, touchdown_safe: safe, scoring_version: c.version, scoring: c,
    components: {lateral_error: lateral, pitch_error: pitch, glide_error: glide,
      touchdown_error: touchdown, total_error: total}, trajectory_error_integrals: {...trajectory}};
}

export class Landing {
  constructor(module, contract, maxTime = 120, scenario = 'easy', seed = 42) {
    this.contract = contract;
    this.hz = contract.physics_hz;
    this.c = contract.scoring;
    this.maxTime = maxTime;
    this.scenario = scenario;
    this.seed = seed >>> 0;
    this.scenarioParams = sampleScenario(this.scenario, this.seed);
    this.startZ = this.scenarioParams.start_z_m;
    this.f = new module.FGFDMExec();
    const f = this.f;
    f.SetDebugLevel(0);
    f.DisableOutput();
    f.SetRootDir('/data');
    f.SetAircraftPath('aircraft'); f.SetEnginePath('engine'); f.SetSystemsPath('systems');
    if (!f.LoadModel('c172x', true)) throw Error('C172x model unavailable');
    f.Setdt(1 / this.hz);
    const baseAlt = 1500 * Math.tan(rad(3)) + 15 + this.scenarioParams.altitude_offset_m;
    const initial = this.scenario === 'easy' ? contract.initial : {
      ...contract.initial,
      'ic/h-agl-ft': baseAlt / FT,
      'ic/vc-kts': 65 + this.scenarioParams.airspeed_offset_kts,
      'ic/psi-true-deg': 90 + this.scenarioParams.heading_offset_deg,
      'atmosphere/wind-north-fps': 0,
    };
    for (const [key, value] of Object.entries(initial)) f.SetPropertyValue(key, value);
    if (!f.RunIC()) throw Error('JSBSim initial conditions failed');
    f.SetPropertyValue('propulsion/set-running', -1);
    this.applyWind(0, baseAlt);
    this.control = {...contract.trim};
    for (const k of AXES) f.SetPropertyValue(`fcs/${k}-cmd-norm`, this.control[k]);
    this.ticks = 0; this.done = false; this.reason = 'running'; this.success = false;
    this.touchdown = null; this.trajectory = {lateral: 0, pitch: 0, glide: 0};
    this.observation = this.observe();
    this.history = [this.observation];
  }
  applyWind(timeS, altitudeAglM) {
    [this.headwind, this.crosswind, this.verticalWind] = windComponents(this.scenario, this.scenarioParams, timeS, altitudeAglM);
    if (this.scenario !== 'easy') {
      this.f.SetPropertyValue('atmosphere/wind-north-fps', -this.crosswind / FT);
      this.f.SetPropertyValue('atmosphere/wind-east-fps', -this.headwind / FT);
      this.f.SetPropertyValue('atmosphere/wind-down-fps', -this.verticalWind / FT);
    }
  }
  observe() {
    const g = k => this.f.GetPropertyValue(k);
    const x = -1500 + g('position/from-start-neu-e-ft') * FT;
    const z = this.startZ - g('position/from-start-neu-n-ft') * FT;
    const h = g('position/h-agl-ft') * FT;
    const heading = g('attitude/psi-deg');
    const ground = Boolean(g('gear/wow'));
    const speed = Math.hypot(g('velocities/v-north-fps'), g('velocities/v-east-fps')) * FT;
    const phase = ground ? (speed < 3 ? 'STOPPED' : this.touchdown ? 'ROLLOUT' : 'MAIN-GEAR TOUCHDOWN') : 'AIRBORNE / APPROACH';
    const [wind_speed_mps, wind_dir_deg] = windPolar(this.headwind, this.crosswind);
    return {
      time_s: this.ticks / this.hz, decision_dt_s: .5, phase,
      runway: {distance_to_threshold_m: Math.max(0, -x), along_track_m: x,
        cross_track_error_m: round(z > 5 ? z - 5 : z < -5 ? z + 5 : 0),
        centerline_offset_m: round(z), runway_width_m: this.c.runway_width_m, altitude_agl_m: h,
        glideslope_error_deg: deg(Math.atan2(h - 15, Math.max(1, -x))) - 3,
        heading_error_deg: wrap(heading - 90)},
      flight: {airspeed_mps: g('velocities/vc-fps') * FT, groundspeed_mps: speed,
        vertical_speed_mps: g('velocities/h-dot-fps') * FT, flight_path_angle_deg: g('flight-path/gamma-deg'),
        angle_of_attack_deg: g('aero/alpha-deg'), alpha_deg: g('aero/alpha-deg'),
        roll_deg: g('attitude/phi-deg'), pitch_deg: g('attitude/theta-deg'), heading_deg: heading,
        p_rad_s: g('velocities/p-rad_sec'), q_rad_s: g('velocities/q-rad_sec'), r_rad_s: g('velocities/r-rad_sec'), beta_deg: g('aero/beta-deg')},
      environment: {
        headwind_mps: round(this.headwind),
        crosswind_mps: round(this.crosswind),
        vertical_wind_mps: round(this.verticalWind),
        wind_speed_mps,
        wind_dir_deg,
      },
      controls: Object.fromEntries([...AXES.map(k => [k, g(`fcs/${k}-cmd-norm`)]), ['flaps_deg', g('fcs/flap-pos-deg')]]),
      status: {on_ground: ground, main_gear_on_ground: Boolean(g('gear/unit[1]/WOW') || g('gear/unit[2]/WOW'))},
      ground_contact: {any_gear_wow: ground, nose_gear_wow: Boolean(g('gear/unit[0]/WOW')),
        left_main_gear_wow: Boolean(g('gear/unit[1]/WOW')), right_main_gear_wow: Boolean(g('gear/unit[2]/WOW'))},
    };
  }
  advance(command, ticks = 1) {
    if (this.done) throw Error('Episode ended; reset before stepping');
    if (!Number.isInteger(ticks) || ticks < 1) throw Error('Invalid tick count');
    this.control = {...validateControl(command)};
    for (const k of AXES) this.f.SetPropertyValue(`fcs/${k}-cmd-norm`, command[k]);
    for (let i = 0; i < ticks && !this.done; i++) {
      const previous = this.observation;
      if (this.scenario === 'hard') this.applyWind((this.ticks + 1) / this.hz, previous.runway.altitude_agl_m);
      if (this.touchdown) {
        this.f.SetPropertyValue('fcs/throttle-cmd-norm', 0);
        this.f.SetPropertyValue('fcs/left-brake-cmd-norm', .7);
        this.f.SetPropertyValue('fcs/right-brake-cmd-norm', .7);
        this.control.throttle = 0;
      }
      if (!this.f.Run()) {this.done = true; this.reason = 'simulation_failure'; break;}
      this.ticks++;
      const o = this.observe(), r = o.runway, f = o.flight;
      if (![...Object.values(r), ...Object.values(f)].every(Number.isFinite)) {
        this.done = true; this.reason = 'nonfinite_state'; break;
      }
      this.observation = o;
      if (!this.touchdown) {
        const limit = r.altitude_agl_m <= this.c.flare_altitude_m ? this.c.flare_pitch_limit_deg : this.c.approach_pitch_limit_deg;
        const pitchExcess = Math.max(0, Math.abs(f.pitch_deg) - limit);
        const glide = r.altitude_agl_m > this.c.flare_altitude_m ?
          (r.altitude_agl_m - (15 + r.distance_to_threshold_m * Math.tan(rad(3)))) / this.c.glide_normalization_m : 0;
        this.trajectory.lateral += (r.centerline_offset_m / this.c.lateral_normalization_m) ** 2 / this.hz;
        this.trajectory.pitch += (.7 * (pitchExcess / this.c.pitch_excess_normalization_deg) ** 2 +
          .3 * (deg(f.q_rad_s) / this.c.pitch_rate_normalization_deg_s) ** 2) / this.hz;
        this.trajectory.glide += glide ** 2 / this.hz;
      }
      const end = reason => {this.done = true; this.reason = reason;};
      const lateral = r.centerline_offset_m;
      if (!this.touchdown && o.status.main_gear_on_ground) {
        this.touchdown = {along_track_m: r.along_track_m, cross_track_m: lateral,
          sink_rate_mps: previous.flight.vertical_speed_mps, airspeed_mps: previous.flight.airspeed_mps,
          heading_error_deg: r.heading_error_deg, roll_deg: f.roll_deg, pitch_deg: f.pitch_deg};
        if (!touchdownSafe(this.touchdown, this.c)) end('unsafe_touchdown');
      }
      if (Math.abs(f.roll_deg) > 70 || Math.abs(f.pitch_deg) > 45 || r.altitude_agl_m < 0) end('crash');
      if (this.touchdown) {
        if (r.along_track_m < 0 || r.along_track_m > this.c.runway_length_m || Math.abs(lateral) > this.c.runway_width_m / 2) end('runway_excursion');
        else if (o.status.on_ground && f.groundspeed_mps < 3 && !this.done) {end('landed'); this.success = true;}
      } else if (o.status.on_ground) end('nose_first_contact');
      if (Math.abs(lateral) > 500 || r.along_track_m > this.c.runway_length_m + 200) end('out_of_bounds');
      if (this.ticks / this.hz >= this.maxTime && !this.done) end('time_limit');
    }
    return this.observation;
  }
  decisionState() {
    const o = this.observation, now = o.time_s;
    const before = time => this.history.findLast(s => s.time_s <= time);
    const reference = before(now - .5) ?? this.history[0];
    const dt = Math.max(now - reference.time_s, 1e-6);
    const fields = [['flight', 'airspeed_mps', 'airspeed_rate_mps2'],
      ['flight', 'vertical_speed_mps', 'vertical_speed_rate_mps2'],
      ['runway', 'centerline_offset_m', 'cross_track_rate_mps'],
      ['runway', 'glideslope_error_deg', 'glideslope_error_rate_deg_s'],
      ['runway', 'heading_error_deg', 'heading_error_rate_deg_s'],
      ['flight', 'flight_path_angle_deg', 'flight_path_angle_rate_deg_s'],
      ['flight', 'angle_of_attack_deg', 'angle_of_attack_rate_deg_s']];
    const motion = Object.fromEntries(fields.map(([group, field, key]) => [key,
      round((field === 'heading_error_deg' ? wrap(o[group][field] - reference[group][field]) : o[group][field] - reference[group][field]) / dt)]));
    const closureRef = before(now - .5);
    motion.distance_closure_rate_mps = closureRef ? round(-(o.runway.distance_to_threshold_m - closureRef.runway.distance_to_threshold_m) / Math.max(now - closureRef.time_s, 1e-6)) : 0;
    const available = Math.max(now - this.history[0].time_s, 0);
    const window = available > .04 ? Math.min(.5, Math.max(.08, available / 2)) : .5;
    const r1 = before(now - window) ?? (this.history.length >= 2 ? this.history[0] : null);
    const r2 = r1 && (before(r1.time_s - window) ?? (this.history.length >= 3 ? this.history[0] : null));
    const dt01 = r1 && Math.max(now - r1.time_s, 1e-6), dt12 = r2 && Math.max(r1.time_s - r2.time_s, 1e-6);
    motion.cross_track_accel_mps2 = r2 && dt01 >= .02 && dt12 >= .02 ? round(
      ((o.runway.centerline_offset_m - r1.runway.centerline_offset_m) / dt01 -
        (r1.runway.centerline_offset_m - r2.runway.centerline_offset_m) / dt12) / (.5 * (dt01 + dt12))) : 0;
    return {flight: {...o.flight}, runway: {...o.runway}, environment: {...o.environment}, current_controls: {...o.controls}, time_s: now,
      motion, status: {...o.status}, phase: o.status.on_ground ? 'ROLLOUT' : o.runway.altitude_agl_m < 20 ? 'FLARE' : 'APPROACH'};
  }
  remember() {this.history.push(this.observation); if (this.history.length > 240) this.history.shift();}
  result() {return evaluate(this.touchdown, this.success, this.reason, this.c, this.trajectory);}
  destroy() {this.f.delete();}
}

export async function loadRuntime(contract, options = {}) {
  const {default: create} = await import('./vendor/jsbsim_wasm.mjs');
  const module = await create({print() {}, printErr() {}, ...options});
  for (const [path, text] of Object.entries(contract.files)) {
    const target = `/data/${path}`;
    module.FS.mkdirTree(target.slice(0, target.lastIndexOf('/')));
    module.FS.writeFile(target, text);
  }
  return module;
}
