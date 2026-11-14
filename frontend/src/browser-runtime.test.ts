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

test('northbound aircraft render straight ahead and wrap heading errors across north', () => {
  const data: any = state();
  for (const [heading, error] of [[0, 0], [359, -1], [1, 1]]) {
    data.observation.flight.heading_deg = heading;
    data.observation.runway.heading_error_deg = error;
    const q = new Quaternion().fromArray(browserSnapshot(data, 'north').quaternion);
    const forward = new Vector3(1, 0, 0).applyQuaternion(q);
    assert.ok(Math.abs(forward.x - Math.cos(error * Math.PI / 180)) < 1e-12);
    assert.ok(Math.abs(forward.z - Math.sin(error * Math.PI / 180)) < 1e-12);
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
  w.emit({type: 'ready', runway_heading_deg: 0});
  r.send({type: 'start', controller: 'human', seed: 42});
  const id = w.sent.at(-1).run_id;
  assert.equal(received.at(-1).type, 'ready');
  w.emit(state(id));
  assert.equal(received.at(-2).type, 'run_started');
  assert.equal(received.at(-2).config.runway_heading_deg, 0);
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
  assert.equal(received.at(-2).record.outcome.status, 'reset');
  r.send({type: 'start', controller: 'jev', model: 'jev-1.14.0', proxy: 'https://example.org/decide', invite: 'private-invite'});
  assert.equal(w.sent.at(-1).model, 'jev-1.14.0');
  assert.equal(w.sent.at(-1).invite, undefined);
  assert.equal(w.sent.at(-1).proxy, undefined);
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
  assert.equal(record.config.model, 'jev-1.14.0');
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

test('all-AI race waits for every worker and keeps independent runs alive', t => {
  const {runtime: r, worker: primary, received} = runtime(t);
  const created: FakeWorker[] = [];
  const original = globalThis.Worker;
  globalThis.Worker = class extends FakeWorker { constructor() { super(); created.push(this); } } as any;
  t.after(() => { globalThis.Worker = original; });
  assert.equal(r.send({type: 'start_race', controller: 'jev', model: 'jev-1.14.0',
    scenario: 'hard', seed: 101, mode: 'realtime', opponents: ['baseline', 'jev-1.13.0']}), true);
  assert.equal(created.length, 2);
  assert.equal(primary.sent.at(-1).type, 'init');
  created[0].emit({type: 'ready'});
  assert.equal(primary.sent.at(-1).type, 'init');
  created[1].emit({type: 'ready'});
  const starts = [primary, ...created].map(w => w.sent.at(-1));
  assert.deepEqual(starts.map(m => m.mode), ['jev', 'baseline', 'jev']);
  assert.equal(new Set(starts.map(m => m.run_id)).size, 3);
  for (const start of starts) {
    assert.equal(start.scenario, 'hard'); assert.equal(start.seed, 101);
    assert.equal(start.timing_mode, 'realtime');
  }
  primary.emit(state(starts[0].run_id, true));
  created[0].emit(state(starts[1].run_id));
  created[1].emit(state(starts[2].run_id));
  assert.equal(received.at(-1).opponent_id, 'jev-1.13.0');
  assert.equal(received.at(-1).message.type, 'state');
  assert.equal(created[0].sent.at(-1).type, 'start'); // primary finish does not stop opponents
  r.send({type: 'reset'});
  assert.ok(created.every(w => w.sent.at(-1).type === 'stop'));
  const count = received.length;
  created[1].emit(state(starts[2].run_id, true));
  assert.equal(received.length, count);
});

test('reset while race workers load prevents a delayed paid start', t => {
  const {runtime: r, worker: primary} = runtime(t);
  r.send({type: 'start_race', controller: 'baseline', opponents: ['jev-1.14.0']});
  const opponent = FakeWorker.instance;
  r.send({type: 'reset'});
  opponent.emit({type: 'ready'});
  assert.equal(primary.sent.at(-1).type, 'stop');
  assert.ok(!opponent.sent.some(m => m.type === 'start'));
});

test('invalid opponents are rejected before creating a race', t => {
  const {runtime: r, worker: w} = runtime(t);
  for (const opponents of [null, [], ['baseline', 'baseline'], ['unknown'], [{}]]) {
    assert.equal(r.send({type: 'start_race', controller: 'baseline', opponents}), false);
    assert.equal(FakeWorker.instance, w);
  }
});

test('opponent initialization failure cancels startup without starting the primary', t => {
  const {runtime: r, worker: primary, received} = runtime(t);
  r.send({type: 'start_race', controller: 'jev', opponents: ['baseline']});
  FakeWorker.instance.emit({type: 'error', message: 'fixture assets unavailable'});
  assert.equal(received.at(-1).type, 'error');
  assert.equal(primary.sent.at(-1).type, 'init');
  assert.equal(r.send({type: 'start', controller: 'baseline'}), true);
  assert.equal(primary.sent.at(-1).type, 'start');
});

test('primary startup failure stops every opponent before returning control', t => {
  const {runtime: r, worker: primary, received} = runtime(t);
  r.send({type: 'start_race', controller: 'jev', opponents: ['jev-1.14.0']});
  const opponent = FakeWorker.instance;
  opponent.emit({type: 'ready'});
  primary.emit({type: 'error', run_id: primary.sent.at(-1).run_id, message: 'fixture initialization failed'});
  assert.equal(opponent.sent.at(-1).type, 'stop');
  assert.equal(received.at(-1).type, 'error');
  const count = received.length;
  opponent.emit(state(opponent.sent.find(m => m.type === 'start').run_id));
  assert.equal(received.length, count);
});
