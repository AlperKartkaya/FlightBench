import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {Landing, baseline, loadRuntime, validateControl, evaluate, windPolar, FT} from './engine.js';
const contract = JSON.parse(readFileSync(new URL('./flightbench.json', import.meta.url)));
const runtime = await loadRuntime(contract);

test('northbound contract rotates physical wind and displacement, not just displayed headings', () => {
  assert.equal(contract.runway_heading_deg, 0);
  assert.equal(contract.initial['ic/psi-true-deg'], 0);
  for (const [hw, xw, bearing] of [[8, 0, 0], [0, 8, 270], [-8, 0, 180], [0, -8, 90]]) {
    assert.deepEqual(windPolar(hw, xw, 0), [8, bearing]);
  }
  for (const scenario of ['easy', 'medium', 'hard']) {
    const env = new Landing(runtime, contract, 2, scenario, 42);
    try {
      const g = key => env.f.GetPropertyValue(key);
      const o = env.observation;
      assert(Math.abs(((o.flight.heading_deg - env.scenarioParams.heading_offset_deg + 540) % 360) - 180) < 1e-6);
      assert(Math.abs(g('atmosphere/wind-north-fps') * FT + env.headwind) < 1e-6);
      assert(Math.abs(g('atmosphere/wind-east-fps') * FT - env.crosswind) < 1e-6);
      env.advance(contract.trim, 60);
      assert.equal(env.observation.runway.along_track_m, -1500 + g('position/from-start-neu-n-ft') * FT);
      assert(Math.abs(env.observation.runway.centerline_offset_m - (env.startZ + g('position/from-start-neu-e-ft') * FT)) < .0001);
      assert(env.observation.runway.along_track_m > -1500);
    } finally {env.destroy();}
  }
});

test('initial altitude, dt, bounds and ended episodes', () => {
  const env = new Landing(runtime, contract, .5);
  assert(Math.abs(env.observation.runway.altitude_agl_m - (1500 * Math.tan(Math.PI / 60) + 15)) < 1e-6);
  assert.throws(() => validateControl({...contract.trim, throttle: NaN}));
  assert.throws(() => validateControl({...contract.trim, extra: 1}));
  assert.throws(() => env.advance({...contract.trim, rudder: 2}));
  assert.throws(() => env.advance(contract.trim, 0));
  env.advance(contract.trim, 60);
  assert.equal(env.ticks, 60); assert.equal(env.reason, 'time_limit');
  assert.equal(env.result().quality, 0); assert.equal(env.result().success, false);
  assert.throws(() => env.advance(contract.trim)); env.destroy();
});

test('V2 score fixtures include safe stop, unsafe contact, failure and running', () => {
  for (const f of JSON.parse(readFileSync(new URL('../../../docs/wasm/scoring-fixtures.json', import.meta.url)))) {
    const result = evaluate(f.touchdown, f.success, f.reason, contract.scoring, f.trajectory);
    assert.equal(result.quality, f.expected.quality);
    assert.equal(result.success, f.expected.success);
    assert.equal(result.touchdown_safe, f.expected.touchdown_safe);
    assert(Math.abs(result.components.total_error - f.expected.components.total_error) < 1e-12);
  }
});

test('medium steady wind and hard dynamic wind are seed-deterministic', () => {
  const med1 = new Landing(runtime, contract, 2, 'medium', 42);
  const med2 = new Landing(runtime, contract, 2, 'medium', 42);
  const e0 = med1.observation.environment;
  assert.deepEqual(e0, med2.observation.environment);
  assert(e0.wind_speed_mps > 0);
  assert.equal(e0.vertical_wind_mps, 0);
  med1.advance(contract.trim, 60);
  assert.deepEqual(med1.observation.environment, e0);
  med1.destroy(); med2.destroy();

  const hard1 = new Landing(runtime, contract, 2, 'hard', 42);
  const hard2 = new Landing(runtime, contract, 2, 'hard', 42);
  const h0 = {...hard1.observation.environment};
  assert.deepEqual(h0, hard2.observation.environment);
  hard1.advance(contract.trim, 60);
  hard2.advance(contract.trim, 60);
  assert.notDeepEqual(hard1.observation.environment, h0);
  assert.deepEqual(hard1.observation.environment, hard2.observation.environment);
  hard1.destroy(); hard2.destroy();
});


test('wind initialization preserves requested airspeed on the first physics tick', () => {
  for (const scenario of ['medium', 'hard']) {
    const env = new Landing(runtime, contract, 2, scenario, 42);
    const initial = env.observation.flight;
    const targetIas = (65 + env.scenarioParams.airspeed_offset_kts) * 1852 / 3600;
    assert(Math.abs(initial.airspeed_mps - targetIas) < 1e-6);
    env.advance(contract.trim, 1);
    assert(Math.abs(env.observation.flight.airspeed_mps - initial.airspeed_mps) < .1);
    assert(Math.abs(initial.alpha_deg - 5) < 1e-6);
    env.destroy();
  }
});

for (const heading of [0, 90]) for (const [scenario, seed, minimum] of [['easy', 42, heading === 0 ? 95 : 99], ['medium', 17, 90], ['hard', 42, 55], ['hard', 97, 75]]) {
  test(`baseline wind regression: runway ${heading} / ${scenario} / ${seed}`, () => {
    // Earth-axis rotation changes touchdown timing; legacy benchmark keeps its stricter easy fixture.
    const c = {...contract, runway_heading_deg: heading, initial: {...contract.initial, 'ic/psi-true-deg': heading}};
    const env = new Landing(runtime, c, 120, scenario, seed);
    try {
      while (!env.done) env.advance(baseline(env.observation, contract.trim), 60);
      assert.equal(env.result().success, true);
      assert(env.result().quality >= minimum);
    } finally {env.destroy();}
  });
}
