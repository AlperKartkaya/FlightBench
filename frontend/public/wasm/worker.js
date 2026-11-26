import {Landing, baseline, loadRuntime, validateControl} from './engine.js';

const PROXY = 'https://flightbench-jev.alperkartkaya.workers.dev/decide';
let runtime, contract, landing, timer, mode, model, command, generation = 0;
let jevCost, runId, decisionInfo = null, decisionCount = 0, latencyMs = null;
let timingMode = "lockstep", deciding = false, startedAt = 0, totalLatencyMs = 0;
const emit = type => {
  const elapsed = Math.max(.001, (performance.now() - startedAt) / 1000);
  const info = {...(decisionInfo ?? {controller: mode}), live_status: {
    calls: decisionCount, is_deciding: deciding,
    effective_decision_hz: decisionCount / elapsed,
    avg_latency_ms: decisionCount ? totalLatencyMs / decisionCount : null,
    latency_ms: latencyMs, state_age_ms: decisionInfo?.timing?.state_age_at_application_ms ?? 0,
  }};
  postMessage({type, observation: landing.observation,
    result: landing.result(), done: landing.done, mode, run_id: runId,
    decision_count: decisionCount, decision_info: info, latency_ms: latencyMs,
    jev_cost: mode === 'jev' ? jevCost : undefined});
};
const stop = () => {generation++; clearTimeout(timer);};
const fail = (run, error) => {
  if (run !== generation) return;
  stop(); postMessage({type: 'error', run_id: runId, jev_cost: mode === 'jev' ? jevCost : undefined, message: error instanceof Error ? error.message : 'Physics failed'});
};

async function decision(run) {
  if (mode === 'baseline') {
    command = baseline(landing.observation, contract.trim); decisionCount++;
    decisionInfo = {controller: 'baseline', command: {...command}};
  }
  if (mode === 'jev') {
    const input = landing.decisionState(), started = performance.now();
    const phase = contract.action_space.phases[input.phase];
    const controller = new AbortController();
    const cost = jevCost, requestRunId = runId;
    cost.pending = true;
    let nanos = null;
    const timeout = setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch(PROXY, {method: 'POST', cache: 'no-store', redirect: 'error',
        signal: controller.signal, headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({...input, model})});
      const data = await response.json().catch(() => null);
      if (Number.isSafeInteger(data?.cost_nanos) && data.cost_nanos >= 0) nanos = data.cost_nanos;
      if (run !== generation) return;
      if (response.status === 429) throw Error('Jev request limit reached (429). Try again in up to one minute.');
      if (!response.ok) throw Error(`Jev proxy HTTP ${response.status}; flight stopped`);
      if (data?.model !== model) throw Error('Unexpected Jev model');
      validateControl(data.command);
      for (const axis of Object.keys(contract.trim)) {
        const action = phase[axis].actions.find(a => a.id === data.action_ids?.[axis]);
        if (!action || action.command !== data.command[axis]) throw Error('Invalid Jev action');
      }
      command = data.command;
      latencyMs = performance.now() - started; totalLatencyMs += latencyMs; decisionCount++;
      const choices = Object.fromEntries(Object.keys(contract.trim).map(axis => {
        const actions = phase[axis].actions;
        const action = actions.find(a => a.id === data.action_ids[axis]);
        return [axis, {choice: action.id, command: action.command, label: action.criterion,
          confidence: null}];
      }));
      decisionInfo = {controller: 'jev', model: data.model, policy: 'direct-categorical',
        command: {...command}, choices, input, timing: {applied: true,
          state_age_at_application_ms: Math.max(0, (landing.observation.time_s - input.time_s) * 1000)}};
    } finally {
      clearTimeout(timeout);
      cost.pending = false;
      if (nanos === null) cost.incomplete = true;
      else cost.nanos += nanos;
      // A stopped flight can still be billed; settle it without applying stale controls.
      if (run !== generation) postMessage({type: 'run_cost_updated', run_id: requestRunId, jev_cost: cost});
    }
  }
}

async function realtimeDecision(run) {
  if (run !== generation || landing.done || deciding) return;
  deciding = true;
  try {
    await decision(run);
    if (run !== generation || landing.done) return;
    deciding = false;
  } catch (error) { fail(run, error); }
}

async function tick(run) {
  try {
    if (run !== generation || landing.done) return;
    if (!(mode === 'jev' && timingMode === 'realtime') && landing.ticks % 60 === 0) {
      deciding = true;
      await decision(run);
      if (run === generation) deciding = false;
    }
    if (run !== generation) return;
    // 4 exact 1/120 s physics ticks; never change dt to catch up a delayed UI.
    landing.advance(command, 4);
    // Request from the state after applying the previous reply, never the old controls.
    if (mode === 'jev' && timingMode === 'realtime' && !landing.done) realtimeDecision(run);
    if (landing.ticks % 60 === 0 || landing.done) landing.remember();
    emit('state');
    if (landing.done) {stop(); return;}
    timer = setTimeout(() => tick(run), 1000 / 30);
  } catch (error) {
    fail(run, error);
  }
}

onmessage = async ({data}) => {
  try {
    if (data.type === 'init') {
      const response = await fetch('./flightbench.json');
      if (!response.ok) throw Error('Missing aircraft assets; run prepare_wasm.py');
      contract = await response.json(); runtime = await loadRuntime(contract);
      postMessage({type: 'ready', runway_heading_deg: contract.runway_heading_deg ?? 90,
        attitude_limits: contract.attitude_limits ?? true,
        versions: {python: contract.python_jsbsim, wasm: contract.wasm_jsbsim}});
    } else if (data.type === 'start') {
      stop(); landing?.destroy(); runId = data.run_id;
      decisionCount = 0; decisionInfo = null; latencyMs = null; deciding = false; totalLatencyMs = 0;
      timingMode = data.timing_mode ?? "lockstep";
      if (!["lockstep", "realtime"].includes(timingMode)) throw Error("Unknown timing mode");
      mode = data.mode;
      jevCost = {nanos: 0, pending: false, incomplete: false};
      if (!['human', 'baseline', 'jev'].includes(mode)) throw Error('Unknown mode');
      if (mode === 'jev') {
        model = data.model ?? 'jev-1.13.0';
        if (!['jev-1.13.0', 'jev-1.14.0'].includes(model)) throw Error('Unsupported Jev model');
      }
      const scenario = data.scenario ?? 'easy';
      if (!['easy', 'medium', 'hard'].includes(scenario)) throw Error('Unknown scenario');
      const seed = Number.isInteger(data.seed) && data.seed >= 0 && data.seed <= 0xffffffff ? data.seed : 42;
      landing = new Landing(runtime, contract, 120, scenario, seed); command = {...contract.trim};
      startedAt = performance.now();
      emit('state'); tick(generation);
    } else if (data.type === 'control' && mode === 'human') command = {...validateControl(data.command)};
    else if (data.type === 'stop') {stop(); postMessage({type: 'stopped', run_id: runId, jev_cost: mode === 'jev' ? jevCost : undefined});}
  } catch (error) {stop(); postMessage({type: 'error', run_id: runId, jev_cost: mode === 'jev' ? jevCost : undefined, message: error instanceof Error ? error.message : 'Physics failed'});}
};
