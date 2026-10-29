import assert from 'node:assert/strict';
import {readFileSync, writeFileSync} from 'node:fs';
import {Landing, baseline, loadRuntime, evaluate} from '../../frontend/public/wasm/engine.js';

const contract = JSON.parse(readFileSync('frontend/public/wasm/flightbench.json'));
const traces = JSON.parse(readFileSync(process.argv[2]));
const runtime = await loadRuntime(contract);
const tolerance = 1e-6; // Port-level numerical parity, not a benchmark scoring change.
const report = {python_jsbsim: contract.python_jsbsim, wasm_jsbsim: contract.wasm_jsbsim,
  emscripten: '4.0.18', physics_hz: contract.physics_hz, scenario: 'easy',
  action_space_sha256: contract.action_space_sha256, model_sha256: contract.model_sha256,
  absolute_tolerance: tolerance, cases: []};
function compare(actual, expected, maxima, prefix = '') {
  assert.deepEqual(Object.keys(actual).sort(), Object.keys(expected).sort(), prefix);
  for (const key of Object.keys(expected)) {
    const path = prefix ? `${prefix}.${key}` : key, a = actual[key], e = expected[key];
    if (typeof e === 'number') {
      assert(Number.isFinite(a), path);
      const delta = Math.abs(a - e);
      maxima[path] = Math.max(maxima[path] ?? 0, delta);
      assert(delta <= tolerance, `${path}: WASM ${a}, Python ${e}, delta ${delta}`);
    } else if (e && typeof e === 'object') compare(a, e, maxima, path);
    else assert.equal(a, e, path);
  }
}
for (const trace of traces) {
  const env = new Landing(runtime, contract, trace.duration), maxima = {};
  let command;
  const decisions = new Map(trace.decisions.map(d => [d.tick, d]));
  for (let tick = 0; tick < trace.samples.length; tick++) {
    compare(env.observation, trace.samples[tick].observation, maxima, 'observation');
    compare(env.result(), trace.samples[tick].result, maxima, 'result');
    const decision = decisions.get(tick);
    if (decision) {
      compare(env.decisionState(), decision.state, maxima, 'canonical');
      compare(baseline(env.observation, contract.trim), decision.baseline, maxima, 'baseline');
      command = decision.action;
    }
    if (tick + 1 < trace.samples.length) {
      assert(!env.done, `WASM ended early at tick ${tick}`);
      env.advance(command);
      if (env.ticks % 60 === 0 || env.done) env.remember();
    }
  }
  assert(env.done, 'WASM must end at the same tick');
  const fields = ['runway.along_track_m', 'runway.centerline_offset_m', 'runway.altitude_agl_m',
    'flight.airspeed_mps', 'flight.roll_deg', 'flight.pitch_deg', 'flight.heading_deg'];
  report.cases.push({name: trace.name, ticks: env.ticks, sim_time_s: env.observation.time_s,
    reason: env.reason, success: env.result().success, score: env.result().quality,
    max_absolute_error: maxima,
    key_maxima: Object.fromEntries(fields.map(k => [k, maxima[`observation.${k}`]])),
    final_observation: env.observation, passed: true});
  env.destroy();
}
for (const f of JSON.parse(readFileSync('docs/wasm/scoring-fixtures.json'))) {
  compare(evaluate(f.touchdown, f.success, f.reason, contract.scoring, f.trajectory), f.expected, {}, 'scoreFixture');
}
// A separate autonomous feedback run is not identical-command engine parity.
const autonomous = new Landing(runtime, contract);
let command;
while (!autonomous.done) {
  if (autonomous.ticks % 60 === 0) command = baseline(autonomous.observation, contract.trim);
  autonomous.advance(command, 4);
}
const nativeBaseline = traces.find(t => t.name === 'baseline-full');
report.autonomous_baseline = {
  wasm_ticks: autonomous.ticks, wasm_score: autonomous.result().quality, wasm_reason: autonomous.reason,
  python_ticks: nativeBaseline.samples.length - 1,
  python_score: nativeBaseline.samples.at(-1).result.quality,
  python_reason: nativeBaseline.samples.at(-1).result.reason,
  identical_command_replay: false,
  note: 'Independent floating-point feedback paths diverge; no closed-loop score identity claim.',
};
assert.equal(autonomous.reason, 'landed');
autonomous.destroy();
report.passed = true;
writeFileSync('docs/wasm/parity.json', JSON.stringify(report, null, 2) + '\n');
console.log(JSON.stringify({passed: true, cases: report.cases.map(({name, ticks, reason, key_maxima}) => ({name, ticks, reason, key_maxima}))}, null, 2));
