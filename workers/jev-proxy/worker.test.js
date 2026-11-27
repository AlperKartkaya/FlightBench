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
  await ctx.storage.put('budget', {minute: 1, count: 998, clients: {}});
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
    assert.equal(body.cost_nanos, null);
    assert.deepEqual(Object.keys(body).sort(), ['action_ids', 'command', 'cost_nanos', 'model']);
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
  const granted = await Promise.all(Array.from({length: 1001}, () => budget.reserve('a')));
  assert.equal(granted.filter(Boolean).length, 1000);
  assert.equal((await ctx.storage.get('budget')).count, 1000);
  assert.equal(await new Budget(ctx, env).reserve('a'), false);
});

test('clients share the global fixed-minute rate', async t => {
  t.mock.method(Date, 'now', () => 60000);
  const {budget} = setup();
  for (let i = 0; i < 500; i++) assert(await budget.reserve('a'));
  for (let i = 0; i < 500; i++) assert(await budget.reserve('b'));
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
    for (let i = 0; i < 1000; i++) {
      assert.equal(await current.reserve('a'), true);
      granted++;
    }
    assert.equal(await current.reserve('a'), false);
    now += 60000;
  }
  assert.equal(granted, 3000);
  assert.equal((await ctx.storage.get('budget')).used, undefined);
});

test('one bounded pinned upstream request; filtered output; failed rate slots never refunded', async t => {
  t.mock.method(Date, 'now', () => 60000);
  const {env, ctx} = setup(); const original = globalThis.fetch; let calls = 0;
  await ctx.storage.put('budget', {minute: 1, count: 998, clients: {}});
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
    const body = await response.json(); assert.deepEqual(Object.keys(body).sort(), ['action_ids','command','cost_nanos','model']);
    assert.deepEqual(body.command, {aileron: -.15, elevator: -.05, rudder: .09, throttle: .5});
    globalThis.fetch = async () => {calls++; throw Error(env.TYPESAFE_API_KEY);};
    const failed = await proxy.fetch(request(), env);
    assert.equal(failed.status, 502); assert(!(await failed.text()).includes(env.TYPESAFE_API_KEY));
    assert.equal((await proxy.fetch(request(), env)).status, 429);
    assert.equal(calls, 2); assert.equal((await ctx.storage.get('budget')).count, 1000);
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

test('shared UTC cycle charges both versions from provider tokens, not results or request counts', async t => {
  let now = Date.UTC(2026, 11, 16, 23, 59, 59);
  t.mock.method(Date, 'now', () => now);
  const {env, ctx} = setup(); env.PUBLIC_ACCESS = 'true';
  const creditRequest = (origin = env.ALLOWED_ORIGIN) =>
    new Request('https://proxy.workers.dev/credits', {headers: {Origin: origin}});
  const credits = async () => (await proxy.fetch(creditRequest(), env)).json();
  assert.equal((await proxy.fetch(creditRequest('https://other.example'), env)).status, 403);
  assert.equal((await proxy.fetch(creditRequest(), {...env, PUBLIC_ACCESS: 'false'})).status, 401);
  assert.equal((await proxy.fetch(creditRequest(), env)).headers.get('Cache-Control'), 'no-store');

  const replies = [1000, 2500, undefined, '7000', 125, 450, 75];
  let release, signalArrival;
  const arrived = new Promise(resolve => { signalArrival = resolve; });
  t.mock.method(globalThis, 'fetch', async (_url, options) => {
    const {model} = JSON.parse(options.body);
    const tokens = replies.shift();
    if (tokens === 450) return new Response(null, {status: 402});
    if (tokens === 75) {
      signalArrival();
      await new Promise(resolve => { release = resolve; });
    }
    return Response.json({...good(), model, usage: {input_tokens: tokens, output_tokens: 6000},
      ...(tokens === 125 ? {truncated: true} : {})});
  });
  const responses = await Promise.all(MODELS.map(model => proxy.fetch(request({...state, model}), env)));
  const nanos = await Promise.all(responses.map(async r => (await r.json()).cost_nanos));
  assert.deepEqual(nanos.sort((a, b) => a - b), [42000, 105000]);
  for (let i = 0; i < 2; i++) assert.equal((await (await proxy.fetch(request(), env)).json()).cost_nanos, null);
  const truncated = await proxy.fetch(request(), env);
  assert.equal(truncated.status, 502); assert.equal((await truncated.json()).cost_nanos, 5250);
  assert.equal((await (await proxy.fetch(request(), env)).json()).cost_nanos, 0);
  assert.deepEqual(await credits(), {
    monthly_nanos: 5_000_000_000, spent_nanos: 152250, unpriced_requests: 2, renews_at: '2026-12-17T00:00:00.000Z',
  });
  const late = proxy.fetch(request(), env);
  await arrived;
  now = Date.UTC(2026, 11, 17);
  release();
  await late;
  assert.equal((await ctx.storage.get('jev-spend:2026-11-17')).spent_nanos, 155400);
  assert.deepEqual(await credits(), {
    monthly_nanos: 5_000_000_000, spent_nanos: 0, unpriced_requests: 0, renews_at: '2027-01-17T00:00:00.000Z',
  });
});

test('the reported balance starts at the snapshot and only subtracts subsequent proxy spend', async t => {
  let now = Date.UTC(2026, 10, 27);
  t.mock.method(Date, 'now', () => now);
  const {env, ctx} = setup();
  env.PUBLIC_ACCESS = 'true';
  const snapshot = {cycle: 'jev-spend:2026-11-17', balance_nanos: 4_300_000_000, spent_nanos: 195_730_584};
  env.JEV_CREDIT_BASELINE = snapshot;
  await ctx.storage.put(snapshot.cycle, {spent_nanos: snapshot.spent_nanos, unpriced_requests: 0});
  const remaining = async () => {
    const req = new Request('https://proxy.workers.dev/credits', {headers: {Origin: env.ALLOWED_ORIGIN}});
    const {monthly_nanos, spent_nanos} = await (await proxy.fetch(req, env)).json();
    return monthly_nanos - spent_nanos;
  };
  assert.equal(await remaining(), 4_300_000_000);
  t.mock.method(globalThis, 'fetch', async () => Response.json({...good(), usage: {input_tokens: 2500}}));
  assert.equal((await proxy.fetch(request(), env)).status, 200);
  assert.equal(await remaining(), 4_299_895_000);
  now = Date.UTC(2026, 11, 17);
  assert.equal(await remaining(), 5_000_000_000);
});
