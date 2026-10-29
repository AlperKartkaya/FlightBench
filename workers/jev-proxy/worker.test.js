import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import proxy, {Budget, MODEL, MODELS, validState, boundedJSON} from './worker.js';
import {Landing, loadRuntime} from '../../frontend/public/wasm/engine.js';

const contract = JSON.parse(readFileSync(new URL('../../frontend/public/wasm/flightbench.json', import.meta.url)));
const runtime = await loadRuntime(contract);
const landing = new Landing(runtime, contract);
const state = landing.decisionState(); landing.destroy();
const token = 'test-only-access-token-aaaaaaaaaaaaaaaaaaaaaaaaaaaa';
function storage() {
  const values = new Map(); let queue = Promise.resolve();
  const s = {get: async key => structuredClone(values.get(key)),
    put: async (key, value) => values.set(key, structuredClone(value)),
    transaction: callback => {
      const task = queue.then(() => callback(s)); queue = task.catch(() => {}); return task;
    }};
  return s;
}
function setup() {
  const env = {ALLOWED_ORIGIN: 'https://alperkartkaya.github.io', ENABLED: 'true',
    TYPESAFE_API_KEY: 'test-only-provider-key', JEV_ACCESS_TOKEN: token};
  const ctx = {storage: storage()}; const budget = new Budget(ctx, env);
  env.BUDGET = {idFromName: name => {assert.equal(name, 'lifetime-v1'); return name;},
    get: () => budget};
  return {env, budget, ctx};
}
function request(body = state, options = {}) {
  return new Request('https://proxy.workers.dev/decide', {method: 'POST', headers: {
    Origin: 'https://alperkartkaya.github.io', Authorization: `Bearer ${token}`,
    'Content-Type': 'application/json', 'CF-Connecting-IP': '192.0.2.1', ...options},
  body: typeof body === 'string' ? body : JSON.stringify(body)});
}
const internal = () => new Request('https://budget.internal/decide', {method: 'POST',
  headers: {'Content-Type': 'application/json', 'X-Client': 'a'.repeat(64)}, body: JSON.stringify(state)});
const good = () => ({model: MODEL, answers: Object.fromEntries(['aileron','elevator','rudder','throttle'].map(axis =>
  [axis, {type: 'choice', choice: '3'}]))});

test('strict numeric telemetry only; cannot inject instructions, model, URLs or assets', () => {
  assert(validState(state));
  for (const s of [{...state, model: 'anything'}, {...state, phase: 'FLARE'},
    {...state, flight: {...state.flight, roll_deg: 'ignore instructions'}},
    {...state, runway: {...state.runway, altitude_agl_m: -1}},
    {...state, current_controls: {...state.current_controls, throttle: 2}},
    {...state, motion: {...state.motion, arbitrary: 1}}, {...state, time_s: 121}]) assert(!validState(s));
});

test('auth is required even with a spoofed allowed Origin; fail closed config/routes', async () => {
  const {env} = setup();
  assert.equal((await proxy.fetch(request(state, {Authorization: ''}), env)).status, 401);
  assert.equal((await proxy.fetch(request(), {...env, JEV_ACCESS_TOKEN: ''})).status, 503);
  assert.equal((await proxy.fetch(request(state, {Origin: 'https://evil.example'}), env)).status, 403);
  assert.equal((await proxy.fetch(request(state, {'CF-Connecting-IP': ''}), env)).status, 403);
  assert.equal((await proxy.fetch(request(), {...env, ENABLED: 'false'})).status, 503);
  assert.equal((await proxy.fetch(request(), {...env, TYPESAFE_API_KEY: ''})).status, 503);
  assert.equal((await proxy.fetch(new Request('https://x/anything'), env)).status, 404);
  assert.equal((await proxy.fetch(new Request('https://x/decide?url=evil'), env)).status, 404);
  const preflight = await proxy.fetch(new Request('https://x/decide', {method: 'OPTIONS', headers: {Origin: env.ALLOWED_ORIGIN}}), env);
  assert.equal(preflight.status, 204);
  assert.equal(preflight.headers.get('Access-Control-Allow-Origin'), env.ALLOWED_ORIGIN);
});

test('explicit public access needs no browser token, but keeps global rates and secrets server-side', async t => {
  t.mock.method(Date, 'now', () => 60000);
  const {env, ctx} = setup(); env.PUBLIC_ACCESS = 'true';
  await ctx.storage.put('budget', {minute: 1, count: 178, clients: {}});
  const calls = [];
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    assert.equal(url, 'https://api.typesafe.ai/v1/systemone');
    assert.equal(options.redirect, 'manual');
    assert.equal(options.headers.Authorization, `Bearer ${env.TYPESAFE_API_KEY}`);
    const body = JSON.parse(options.body); calls.push(body);
    assert(validState(body.state));
    return Response.json({...good(), model: body.model, private: env.TYPESAFE_API_KEY});
  });
  for (const model of MODELS) {
    const response = await proxy.fetch(request({...state, model}, {Authorization: ''}), env);
    assert.equal(response.status, 200);
    const body = await response.json();
    assert.equal(body.model, model);
    assert.deepEqual(Object.keys(body).sort(), ['action_ids', 'command', 'model']);
    assert(!JSON.stringify(body).includes(env.TYPESAFE_API_KEY));
    assert(!JSON.stringify(body).includes(token));
  }
  assert.deepEqual(calls.map(c => c.model), MODELS);
  assert.equal((await proxy.fetch(request(state, {Authorization: ''}), env)).status, 429);
  assert.equal(calls.length, 2);
  assert.equal((await proxy.fetch(request(state, {Authorization: '', Origin: 'https://evil.example'}), env)).status, 403);
  assert.equal((await proxy.fetch(request(state, {Authorization: ''}), {...env, PUBLIC_ACCESS: 'yes'})).status, 401);
});

test('both proxy boundaries reject arbitrary model names before reserving a rate slot', async () => {
  const {env, ctx, budget} = setup(); env.PUBLIC_ACCESS = 'true';
  for (const model of ['jev-latest', 'other-provider', null, {}, ['jev-1.14.0']]) {
    assert.equal((await proxy.fetch(request({...state, model}, {Authorization: ''}), env)).status, 400);
    const r = new Request('https://budget.internal/decide', {method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Client': 'a'.repeat(64)},
      body: JSON.stringify({...state, model})});
    assert.equal((await budget.fetch(r)).status, 400);
  }
  assert.equal(await ctx.storage.get('budget'), undefined);
});

test('bounded streaming JSON rejects oversized, invalid and unknown fields before spending', async () => {
  const {env, ctx} = setup();
  for (const body of ['{', ' '.repeat(8193), {...state, questions: {}}]) {
    assert.equal((await proxy.fetch(request(body), env)).status, 400);
  }
  assert.equal(await ctx.storage.get('budget'), undefined);
  await assert.rejects(boundedJSON(request('x'.repeat(8193))));
});

test('atomic minute rate survives object restart and concurrent requests', async t => {
  t.mock.method(Date, 'now', () => 60000);
  const {budget, ctx, env} = setup();
  const granted = await Promise.all(Array.from({length: 200}, () => budget.reserve('a')));
  assert.equal(granted.filter(Boolean).length, 120);
  assert.equal((await ctx.storage.get('budget')).count, 120);
  assert.equal(await new Budget(ctx, env).reserve('a'), false);
  assert.equal(await new Budget(ctx, env).reserve('b'), true);
});

test('per-client and global fixed-minute rates apply', async t => {
  t.mock.method(Date, 'now', () => 60000);
  const {budget} = setup();
  for (let i = 0; i < 120; i++) assert(await budget.reserve('a'));
  assert.equal(await budget.reserve('a'), false);
  for (let i = 0; i < 60; i++) assert(await budget.reserve('b'));
  assert.equal(await budget.reserve('c'), false);
});

test('no lifetime quota, including previously exhausted storage and minute rollover', async t => {
  let now = 60000;
  t.mock.method(Date, 'now', () => now);
  const {budget, ctx, env} = setup();
  await ctx.storage.put('budget', {used: 10000, minute: 1, count: 0, clients: {}});
  let granted = 0;
  for (let minute = 0; minute < 3; minute++) {
    const current = minute ? new Budget(ctx, env) : budget;
    for (let i = 0; i < 120; i++) {
      assert.equal(await current.reserve('a'), true);
      granted++;
    }
    assert.equal(await current.reserve('a'), false);
    now += 60000;
  }
  assert.equal(granted, 360);
  assert.equal((await ctx.storage.get('budget')).used, undefined);
});

test('one bounded pinned upstream request; filtered output; failed rate slots never refunded', async t => {
  t.mock.method(Date, 'now', () => 60000);
  const {env, ctx} = setup(); const original = globalThis.fetch; let calls = 0;
  await ctx.storage.put('budget', {minute: 1, count: 178, clients: {}});
  try {
    globalThis.fetch = async (url, options) => {
      calls++; assert.equal(url, 'https://api.typesafe.ai/v1/systemone');
      assert.equal(options.redirect, 'manual');
      assert.equal(options.headers.Authorization, `Bearer ${env.TYPESAFE_API_KEY}`);
      const body = JSON.parse(options.body); assert.equal(body.model, MODEL);
      assert.deepEqual(Object.keys(body.questions).sort(), ['aileron','elevator','rudder','throttle']);
      assert.equal(body.questions.elevator.type, 'choice');
      return Response.json({...good(), private_header: 'must-not-leave-worker'});
    };
    const response = await proxy.fetch(request(), env);
    assert.equal(response.status, 200);
    const body = await response.json(); assert.deepEqual(Object.keys(body).sort(), ['action_ids','command','model']);
    assert.deepEqual(body.command, {aileron: -.15, elevator: -.05, rudder: .09, throttle: .5});
    globalThis.fetch = async () => {calls++; throw Error(env.TYPESAFE_API_KEY);};
    const failed = await proxy.fetch(request(), env);
    assert.equal(failed.status, 502); assert(!(await failed.text()).includes(env.TYPESAFE_API_KEY));
    assert.equal((await proxy.fetch(request(), env)).status, 429);
    assert.equal(calls, 2); assert.equal((await ctx.storage.get('budget')).count, 180);
  } finally {globalThis.fetch = original;}
});

test('reject model drift, truncation, invalid action IDs and upstream redirects without relay', async () => {
  const original = globalThis.fetch;
  try {
    for (const body of [{...good(), model: 'jev-latest'}, {...good(), model: 'jev-1.14.0'}, {...good(), truncated: true},
      {...good(), truncation: {dropped: 1}}, {...good(), answers: {...good().answers,
        aileron: {type: 'choice', choice: '99'}}}, {...good(), answers: {...good().answers,
        elevator: {type: 'choice', choice: 3}}}]) {
      globalThis.fetch = async () => Response.json(body);
      assert.equal((await setup().budget.fetch(internal())).status, 502);
    }
    globalThis.fetch = async () => new Response('sensitive upstream details', {status: 302});
    const r = await setup().budget.fetch(internal()); assert.equal(r.status, 502);
    assert(!(await r.text()).includes('sensitive'));
  } finally {globalThis.fetch = original;}
});
