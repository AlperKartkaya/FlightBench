import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('./worker.js', import.meta.url), 'utf8').replace(/^import[^\n]+\n/, '');
const trim = {aileron: -.15, elevator: .17, rudder: .09, throttle: .5};
const contract = {trim, action_space: {phases: {APPROACH: Object.fromEntries(
  Object.entries(trim).map(([axis, command]) => [axis, {actions: [{id: '0', command, criterion: 'trim'}]}]),
)}}};
const settle = () => new Promise(resolve => setImmediate(resolve));
function fixture(replies = []) {
  const messages = [], timers = [];
  let calls = 0;
  class Landing {
    ticks = 0; done = false; observation = {time_s: 0};
    result() { return {reason: 'running', quality: 0}; }
    advance(command, ticks) { assert.deepEqual({...command}, trim); this.ticks += ticks; }
    decisionState() { return {time_s: this.ticks / 120, phase: 'APPROACH'}; }
    remember() {} destroy() {}
  }
  const context = vm.createContext({Landing, baseline: () => ({...trim}), loadRuntime: async () => ({}),
    validateControl: command => command, URL, AbortController, performance,
    postMessage: message => messages.push(message), clearTimeout() {},
    setTimeout: fn => {timers.push(fn); return timers.length;},
    fetch: async url => {
      if (url === './flightbench.json') return {ok: true, json: async () => contract};
      calls++;
      return replies.shift() ?? {ok: false, status: 429};
    },
  });
  vm.runInContext(source, context);
  return {messages, timers, calls: () => calls, send: data => context.onmessage({data})};
}

test('Worker tags acknowledgements and ignores a stopped generation timer', async () => {
  const f = fixture();
  await f.send({type: 'init'});
  assert.equal(f.messages[0].type, 'ready');
  await f.send({type: 'start', mode: 'baseline', run_id: 'first'});
  await settle();
  assert.equal(f.messages.at(-1).run_id, 'first');
  assert.equal(f.messages.at(-1).decision_count, 1);
  const queued = f.timers.at(-1);
  await f.send({type: 'stop'});
  assert.equal(f.messages.at(-1).type, 'stopped');
  await f.send({type: 'start', mode: 'human', run_id: 'second'});
  await settle();
  const count = f.messages.length;
  await queued();
  assert.equal(f.messages.length, count);
  assert.equal(f.messages.at(-1).run_id, 'second');
});

test('Worker rejects unsafe Jev URLs before fetch and quota rejection ends the run', async () => {
  const f = fixture();
  await f.send({type: 'init'});
  await f.send({type: 'start', mode: 'jev', run_id: 'bad', proxy: 'http://example.org/decide', invite: 'x'.repeat(43)});
  assert.equal(f.messages.at(-1).type, 'error');
  assert.equal(f.messages.at(-1).run_id, 'bad');
  assert.equal(f.calls(), 0);
  await f.send({type: 'start', mode: 'jev', run_id: 'quota', proxy: 'https://example.workers.dev/decide', invite: 'x'.repeat(43)});
  await settle();
  assert.equal(f.messages.at(-1).type, 'error');
  assert.equal(f.messages.at(-1).run_id, 'quota');
  assert.match(f.messages.at(-1).message, /429/);
  assert.equal(f.calls(), 1);
  assert.equal(f.messages.filter(m => m.run_id === 'quota' && m.type === 'state').length, 1);
});


test('Jev UI metadata uses canonical phase criteria, never the invitation', async () => {
  const f = fixture([{ok: true, json: async () => ({model: 'jev-1.13.0',
    action_ids: Object.fromEntries(Object.keys(trim).map(k => [k, '0'])), command: {...trim}})}]);
  await f.send({type: 'init'});
  await f.send({type: 'start', mode: 'jev', run_id: 'ok', proxy: 'https://example.workers.dev/decide', invite: 'private-invite'.repeat(4)});
  await settle();
  const state = f.messages.at(-1);
  assert.equal(state.type, 'state');
  assert.equal(state.decision_count, 1);
  assert.equal(state.decision_info.policy, 'direct-categorical');
  assert.equal(state.decision_info.choices.aileron.label, 'trim');
  assert.equal(state.decision_info.choices.aileron.confidence, null);
  assert.equal(state.decision_info.input.time_s, 0);
  assert.ok(!JSON.stringify(state).includes('private-invite'));
});
