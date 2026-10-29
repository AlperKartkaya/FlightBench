import assert from 'node:assert/strict';
import test from 'node:test';
import { Vector3, Quaternion } from 'three';
import { BrowserRuntime, browserSnapshot } from './browser-runtime.ts';

const state = (run_id = 'run', done = false) => ({
  type: 'state', run_id, done,
  observation: { runway: {along_track_m: -1200, altitude_agl_m: 90, centerline_offset_m: 3},
    flight: {roll_deg: 0, pitch_deg: 0, heading_deg: 90} },
  result: {reason: done ? 'landed' : 'running', success: done, quality: done ? 86.544 : 0},
});

test('browser snapshot keeps the Python runway frame and aviation attitude signs', () => {
  const data = state();
  const snapshot = browserSnapshot(data, 'id');
  assert.deepEqual(snapshot.position, [-1200, 90, 3]);
  assert.deepEqual(snapshot.quaternion, [0, 0, 0, 1]);
  assert.equal(snapshot.run_id, 'id');
  for (const [angles, vector, expected] of [
    [[30, 0, 90], [0, 0, 1], [0, -.5, Math.sqrt(.75)]],
    [[0, 30, 90], [1, 0, 0], [Math.sqrt(.75), .5, 0]],
    [[0, 0, 180], [1, 0, 0], [0, 0, 1]],
    [[0, 0, 270], [1, 0, 0], [-1, 0, 0]],
  ]) {
    const [roll_deg, pitch_deg, heading_deg] = angles;
    data.observation.flight = {roll_deg, pitch_deg, heading_deg};
    const q = new Quaternion().fromArray(browserSnapshot(data, 'id').quaternion);
    const actual = new Vector3(...vector).applyQuaternion(q).toArray();
    actual.forEach((v, i) => assert.ok(Math.abs(v - expected[i]) < 1e-12));
  }
});

class FakeWorker {
  static instance: FakeWorker;
  sent: any[] = [];
  onmessage?: (event: { data: any }) => void;
  onerror?: () => void;
  constructor() { FakeWorker.instance = this; }
  postMessage(message: any) { this.sent.push(message); }
  terminate() {}
  emit(data: any) { this.onmessage!({data}); }
}

function runtime(t: any) {
  const original = globalThis.Worker;
  globalThis.Worker = FakeWorker as any;
  t.after(() => { globalThis.Worker = original; });
  const received: any[] = [];
  const runtime = new BrowserRuntime(new URL('https://example.org/FlightBench/wasm/worker.js'), m => received.push(m));
  const worker = FakeWorker.instance;
  assert.equal(runtime.send({type: 'start'}), false);
  worker.emit({type: 'ready'});
  return {runtime, worker, received};
}

test('start is acknowledged by physics; stop never becomes a scored safe landing', t => {
  const {runtime: r, worker: w, received} = runtime(t);
  r.send({type: 'start', controller: 'human', seed: 42});
  const id = w.sent.at(-1).run_id;
  assert.equal(received.at(-1).type, 'ready');
  w.emit(state(id));
  assert.equal(received.at(-2).type, 'run_started');
  r.send({type: 'action', action: {aileron: 0, elevator: .1, rudder: 0, throttle: .5, flaps_deg: 0}});
  assert.deepEqual(w.sent.at(-1).command, {aileron: 0, elevator: .1, rudder: 0, throttle: .5});
  r.send({type: 'stop'});
  assert.equal(received.at(-1).type, 'state');
  w.emit({type: 'stopped', run_id: id});
  assert.equal(received.at(-1).record.outcome.status, 'stopped');
  assert.equal(received.at(-1).record.outcome.success, false);
  assert.equal(received.at(-1).record.outcome.quality, 0);
});

test('reset rejects stale state and finish; a new run can complete without storing invite', t => {
  const {runtime: r, worker: w, received} = runtime(t);
  r.send({type: 'start', controller: 'baseline'});
  const old = w.sent.at(-1).run_id;
  w.emit(state(old));
  r.send({type: 'reset'});
  r.send({type: 'start', controller: 'jev', proxy: 'https://example.org/decide', invite: 'private-invite'});
  const id = w.sent.at(-1).run_id;
  const count = received.length;
  w.emit(state(old, true));
  w.emit({type: 'stopped', run_id: old});
  assert.equal(received.length, count);
  w.emit(state(id, true));
  const record = received.at(-1).record;
  assert.equal(record.outcome.quality, 86.544);
  assert.equal(record.outcome.status, 'landed');
  assert.equal(record.outcome.success, true);
  assert.equal(record.config.invite, undefined);
  assert.equal(record.config.proxy, undefined);
  assert.equal(record.diagnostics.persistence, 'none');
  assert.equal(record.source, 'browser-wasm');
});

test('failed startup recovers; midflight proxy error ends once, without fallback', t => {
  const {runtime: r, worker: w, received} = runtime(t);
  r.send({type: 'start', controller: 'jev'});
  w.emit({type: 'error', run_id: w.sent.at(-1).run_id, message: 'Private invite required'});
  assert.equal(received.at(-1).type, 'error');
  assert.ok(r.send({type: 'start', controller: 'jev'}));
  const id = w.sent.at(-1).run_id;
  w.emit(state(id));
  w.emit({type: 'error', run_id: id, message: 'Jev proxy HTTP 429'});
  assert.equal(received.at(-2).record.outcome.status, 'controller_error');
  assert.equal(received.at(-1).message, 'Jev proxy HTTP 429');
  assert.equal(received.filter(m => m.type === 'run_finished').length, 1);
});
