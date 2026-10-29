import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {Landing, loadRuntime, validateControl, evaluate} from './engine.js';
const contract = JSON.parse(readFileSync(new URL('./flightbench.json', import.meta.url)));
const runtime = await loadRuntime(contract);

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
