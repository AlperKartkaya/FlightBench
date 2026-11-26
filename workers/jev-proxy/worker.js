import actionSpace from './action-space.json' with {type: 'json'};

const AXES = ['aileron', 'elevator', 'rudder', 'throttle'];
export const MODEL = 'jev-1.13.0';
export const MODELS = [MODEL, 'jev-1.14.0'];
const ENDPOINT = 'https://api.typesafe.ai/v1/systemone';
// https://help.typesafe.ai/articles/5187202169-how-much-does-jev-cost
const NANOS_PER_INPUT_TOKEN = 42;
const MONTHLY_CREDIT_NANOS = 5_000_000_000;
const RENEWAL_DAY = 17;

function creditCycle(now = Date.now()) {
  const date = new Date(now), year = date.getUTCFullYear(), month = date.getUTCMonth();
  const offset = date.getUTCDate() < RENEWAL_DAY ? -1 : 0;
  return {
    key: 'jev-spend:' + new Date(Date.UTC(year, month + offset, RENEWAL_DAY)).toISOString().slice(0, 10),
    renews_at: new Date(Date.UTC(year, month + offset + 1, RENEWAL_DAY)).toISOString(),
  };
}
const json = (body, status = 200, headers = {}) => Response.json(body, {status, headers: {
  'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', ...headers,
}});
const exact = (o, keys) => o && typeof o === 'object' && !Array.isArray(o) &&
  Object.keys(o).sort().join() === [...keys].sort().join();
const fields = {
  flight: ['airspeed_mps', 'groundspeed_mps', 'vertical_speed_mps', 'flight_path_angle_deg',
    'angle_of_attack_deg', 'alpha_deg', 'roll_deg', 'pitch_deg', 'heading_deg',
    'p_rad_s', 'q_rad_s', 'r_rad_s', 'beta_deg'],
  runway: ['distance_to_threshold_m', 'along_track_m', 'cross_track_error_m', 'centerline_offset_m',
    'runway_width_m', 'altitude_agl_m', 'glideslope_error_deg', 'heading_error_deg'],
  environment: ['headwind_mps', 'crosswind_mps', 'vertical_wind_mps', 'wind_speed_mps', 'wind_dir_deg'],
  current_controls: [...AXES, 'flaps_deg'],
  motion: ['airspeed_rate_mps2', 'vertical_speed_rate_mps2', 'cross_track_rate_mps',
    'glideslope_error_rate_deg_s', 'heading_error_rate_deg_s', 'flight_path_angle_rate_deg_s',
    'angle_of_attack_rate_deg_s', 'distance_closure_rate_mps', 'cross_track_accel_mps2'],
};

export function validState(s) {
  if (!exact(s, ['flight', 'runway', 'environment', 'current_controls', 'time_s', 'motion', 'status', 'phase']) ||
      !Number.isFinite(s.time_s) || s.time_s < 0 || s.time_s > 120 ||
      !exact(s.status, ['on_ground', 'main_gear_on_ground']) ||
      Object.values(s.status).some(v => typeof v !== 'boolean')) return false;
  for (const [group, keys] of Object.entries(fields)) {
    if (!exact(s[group], keys) || Object.values(s[group]).some(v =>
      typeof v !== 'number' || !Number.isFinite(v) || Math.abs(v) > 10000)) return false;
  }
  if (AXES.some(k => s.current_controls[k] < (k === 'throttle' ? 0 : -1) ||
      s.current_controls[k] > 1) || s.runway.runway_width_m !== 40 ||
      s.runway.altitude_agl_m < 0 || s.flight.airspeed_mps < 0 || s.flight.groundspeed_mps < 0 ||
      s.environment.wind_speed_mps < 0 || s.environment.wind_dir_deg < 0 || s.environment.wind_dir_deg > 360 ||
      Math.abs(s.flight.roll_deg) > 180 || Math.abs(s.flight.pitch_deg) > 90) return false;
  const phase = s.status.on_ground ? 'ROLLOUT' : s.runway.altitude_agl_m < 20 ? 'FLARE' : 'APPROACH';
  return s.phase === phase;
}

export async function boundedJSON(request, max = 8192) {
  if (request.headers.get('Content-Type')?.split(';')[0].trim() !== 'application/json') throw Error('Content type');
  if (Number(request.headers.get('Content-Length')) > max) throw Error('Body too large');
  const reader = request.body?.getReader();
  if (!reader) throw Error('Missing body');
  const chunks = []; let size = 0;
  try {
    for (;;) {
      const {value, done} = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > max) {await reader.cancel(); throw Error('Body too large');}
      chunks.push(value);
    }
  } finally {reader.releaseLock();}
  const bytes = new Uint8Array(size); let offset = 0;
  for (const chunk of chunks) {bytes.set(chunk, offset); offset += chunk.byteLength;}
  return JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(bytes));
}

async function digest(value) {
  return new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value)));
}
async function authorized(header, secret) {
  if (!secret || secret.length < 43 || !header?.startsWith('Bearer ') || header.length > 256) return false;
  const [a, b] = await Promise.all([digest(header.slice(7)), digest(secret)]);
  let diff = 0; for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  return diff === 0;
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const origin = request.headers.get('Origin');
    const cors = origin === env.ALLOWED_ORIGIN ? {
      'Access-Control-Allow-Origin': origin, 'Vary': 'Origin',
      'Access-Control-Allow-Methods': 'GET, POST',
      'Access-Control-Allow-Headers': 'Authorization, Content-Type',
    } : {};
    const credits = url.pathname === '/credits';
    if ((!credits && url.pathname !== '/decide') || url.search) return json({error: 'Not found'}, 404, cors);
    if (!env.ALLOWED_ORIGIN || origin !== env.ALLOWED_ORIGIN) return json({error: 'Origin denied'}, 403);
    if (request.method === 'OPTIONS') return new Response(null, {status: 204, headers: cors});
    if (request.method !== (credits ? 'GET' : 'POST')) return json({error: 'Method denied'}, 405, cors);
    if (!env.TYPESAFE_API_KEY || !env.BUDGET || env.ENABLED !== 'true' ||
        typeof env.JEV_ACCESS_TOKEN !== 'string' || env.JEV_ACCESS_TOKEN.length < 43) return json({error: 'Jev disabled'}, 503, cors);
    if (env.PUBLIC_ACCESS !== 'true' && !await authorized(request.headers.get('Authorization'), env.JEV_ACCESS_TOKEN)) return json({error: 'Unauthorized'}, 401, cors);
    try {
      // Keep the deployed singleton identity; all POPs share rates and usage.
      const budget = env.BUDGET.get(env.BUDGET.idFromName('lifetime-v1'));
      if (credits) {
        const response = await budget.fetch(new Request('https://budget.internal/credits'));
        return json(await response.json(), response.status, cors);
      }
      let state, model;
      try {({model = MODEL, ...state} = await boundedJSON(request));} catch {return json({error: 'Invalid telemetry'}, 400, cors);}
      if (!MODELS.includes(model) || !validState(state)) return json({error: 'Invalid telemetry'}, 400, cors);
      const ip = request.headers.get('CF-Connecting-IP');
      if (!ip) return json({error: 'Client identity unavailable'}, 403, cors);
      const hash = await digest(`${env.JEV_ACCESS_TOKEN}:${ip}`);
      const client = Array.from(hash, b => b.toString(16).padStart(2, '0')).join('');
      const decision = budget.fetch(new Request('https://budget.internal/decide', {
        method: 'POST', headers: {'Content-Type': 'application/json', 'X-Client': client},
        body: JSON.stringify({...state, model}),
      }));
      // Finish metering requests already sent to TypeSafe even when the browser stops.
      ctx?.waitUntil(decision.then(() => {}, () => {}));
      const response = await decision;
      return new Response(response.body, {status: response.status, headers: {...cors,
        'Content-Type': 'application/json', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'}});
    } catch {
      // Never return/log exceptions, upstream bodies, headers, tokens, or environment bindings.
      return json({error: 'Proxy unavailable'}, 503, cors);
    }
  },
};

export class Budget {
  constructor(ctx, env) {this.ctx = ctx; this.env = env;}
  async reserve(client) {
    const minute = Math.floor(Date.now() / 60000);
    // Commit before network I/O. Failures, disconnects and timeouts never refund a slot.
    return this.ctx.storage.transaction(async storage => {
      const old = await storage.get('budget') ?? {minute, count: 0, clients: {}};
      const b = old.minute === minute ? old : {minute, count: 0, clients: {}};
      if (b.count >= 1000 || (b.clients[client] ?? 0) >= 1000) return false;
      b.count++; b.clients[client] = (b.clients[client] ?? 0) + 1;
      await storage.put('budget', b);
      return true;
    });
  }
  async recordSpend(key, nanos) {
    await this.ctx.storage.transaction(async storage => {
      const spend = await storage.get(key) ?? {spent_nanos: 0, unpriced_requests: 0};
      if (nanos === null) spend.unpriced_requests++;
      else spend.spent_nanos += nanos;
      await storage.put(key, spend);
    });
  }
  async fetch(request) {
    if (this.env.ENABLED !== 'true' || !this.env.TYPESAFE_API_KEY) return json({error: 'Jev disabled'}, 503);
    const cycle = creditCycle();
    if (request.method === 'GET' && new URL(request.url).pathname === '/credits') {
      const spend = await this.ctx.storage.get(cycle.key) ?? {spent_nanos: 0, unpriced_requests: 0};
      return json({monthly_nanos: MONTHLY_CREDIT_NANOS, ...spend, renews_at: cycle.renews_at});
    }
    let state, model;
    try {({model = MODEL, ...state} = await boundedJSON(request));} catch {return json({error: 'Invalid telemetry'}, 400);}
    if (!MODELS.includes(model) || !validState(state)) return json({error: 'Invalid telemetry'}, 400);
    const client = request.headers.get('X-Client');
    if (!/^[a-f0-9]{64}$/.test(client ?? '')) return json({error: 'Invalid client'}, 400);
    if (!await this.reserve(client)) return json({error: 'Rate limited', cost_nanos: 0}, 429);
    const axes = actionSpace.phases[state.phase];
    const questions = Object.fromEntries(AXES.map(axis => [axis, {type: 'choice',
      instructions: axes[axis].instructions,
      criteria: Object.fromEntries(axes[axis].actions.map(a => [a.id, a.criterion])),
    }]));
    let received = false, data;
    try {
      // Exactly one fixed request with an allowlisted version; no URL/question relay or retries.
      // Workers supports manual, not redirect:error; !ok below rejects every redirect.
      const response = await fetch(ENDPOINT, {method: 'POST', redirect: 'manual',
        signal: AbortSignal.timeout(10000), headers: {'Content-Type': 'application/json',
          Authorization: `Bearer ${this.env.TYPESAFE_API_KEY}`},
        body: JSON.stringify({model, state, questions})});
      if (!response.ok) {
        await response.body?.cancel();
        return json({error: 'Jev request failed', cost_nanos: 0}, 502);
      }
      received = true;
      data = await boundedJSON(response, 32768);
    } catch {
      await this.recordSpend(cycle.key, null);
      return json({error: received ? 'Invalid Jev response' : 'Jev request unavailable', cost_nanos: null}, 502);
    }
    const inputTokens = data?.usage?.input_tokens;
    const priced = Number.isSafeInteger(inputTokens) && inputTokens >= 0 &&
      inputTokens <= Number.MAX_SAFE_INTEGER / NANOS_PER_INPUT_TOKEN;
    const nanos = priced ? inputTokens * NANOS_PER_INPUT_TOKEN : null;
    await this.recordSpend(cycle.key, nanos);
    const bad = error => json({error, cost_nanos: nanos}, 502);
    if (data?.model !== model) return bad('Unexpected Jev model');
    if (data.truncated === true || (data.truncation && Object.keys(data.truncation).length)) return bad('Jev context truncated');
    if (!exact(data.answers, AXES)) return bad('Invalid Jev answers');
    const action_ids = {}, command = {};
    for (const axis of AXES) {
      const answer = data.answers[axis];
      if (answer?.type !== 'choice' || typeof answer.choice !== 'string') return bad('Invalid Jev choice');
      const action = axes[axis].actions.find(a => a.id === answer.choice);
      if (!action) return bad('Invalid Jev action');
      action_ids[axis] = action.id; command[axis] = action.command;
    }
    return json({model, action_ids, command, cost_nanos: nanos});
  }
}
