import actionSpace from './action-space.json' with {type: 'json'};

const AXES = ['aileron', 'elevator', 'rudder', 'throttle'];
export const MODEL = 'jev-1.13.0';
export const MODELS = [MODEL, 'jev-1.14.0'];
const ENDPOINT = 'https://api.typesafe.ai/v1/systemone';
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
  current_controls: [...AXES, 'flaps_deg'],
  motion: ['airspeed_rate_mps2', 'vertical_speed_rate_mps2', 'cross_track_rate_mps',
    'glideslope_error_rate_deg_s', 'heading_error_rate_deg_s', 'flight_path_angle_rate_deg_s',
    'angle_of_attack_rate_deg_s', 'distance_closure_rate_mps', 'cross_track_accel_mps2'],
};

export function validState(s) {
  if (!exact(s, ['flight', 'runway', 'current_controls', 'time_s', 'motion', 'status', 'phase']) ||
      !Number.isFinite(s.time_s) || s.time_s < 0 || s.time_s > 120 ||
      !exact(s.status, ['on_ground', 'main_gear_on_ground']) ||
      Object.values(s.status).some(v => typeof v !== 'boolean')) return false;
  for (const [group, keys] of Object.entries(fields)) {
    if (!exact(s[group], keys) || Object.values(s[group]).some(v =>
      typeof v !== 'number' || !Number.isFinite(v) || Math.abs(v) > 10000)) return false;
  }
  if (AXES.some(k => s.current_controls[k] < (k === 'throttle' ? 0 : -1) ||
      s.current_controls[k] > 1) || s.runway.runway_width_m !== 30 ||
      s.runway.altitude_agl_m < 0 || s.flight.airspeed_mps < 0 || s.flight.groundspeed_mps < 0 ||
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
  async fetch(request, env) {
    const url = new URL(request.url);
    const origin = request.headers.get('Origin');
    const cors = origin === env.ALLOWED_ORIGIN ? {
      'Access-Control-Allow-Origin': origin, 'Vary': 'Origin',
      'Access-Control-Allow-Methods': 'POST',
      'Access-Control-Allow-Headers': 'Authorization, Content-Type',
    } : {};
    if (url.pathname !== '/decide' || url.search) return json({error: 'Not found'}, 404, cors);
    if (!env.ALLOWED_ORIGIN || origin !== env.ALLOWED_ORIGIN) return json({error: 'Origin denied'}, 403);
    if (request.method === 'OPTIONS') return new Response(null, {status: 204, headers: cors});
    if (request.method !== 'POST') return json({error: 'Method denied'}, 405, cors);
    if (!env.TYPESAFE_API_KEY || !env.BUDGET || env.ENABLED !== 'true' ||
        typeof env.JEV_ACCESS_TOKEN !== 'string' || env.JEV_ACCESS_TOKEN.length < 43) return json({error: 'Jev disabled'}, 503, cors);
    if (env.PUBLIC_ACCESS !== 'true' && !await authorized(request.headers.get('Authorization'), env.JEV_ACCESS_TOKEN)) return json({error: 'Unauthorized'}, 401, cors);
    try {
      let state, model;
      try {({model = MODEL, ...state} = await boundedJSON(request));} catch {return json({error: 'Invalid telemetry'}, 400, cors);}
      if (!MODELS.includes(model) || !validState(state)) return json({error: 'Invalid telemetry'}, 400, cors);
      // Keep the deployed singleton identity; all POPs share the same minute rates.
      const budget = env.BUDGET.get(env.BUDGET.idFromName('lifetime-v1'));
      const ip = request.headers.get('CF-Connecting-IP');
      if (!ip) return json({error: 'Client identity unavailable'}, 403, cors);
      const hash = await digest(`${env.JEV_ACCESS_TOKEN}:${ip}`);
      const client = Array.from(hash, b => b.toString(16).padStart(2, '0')).join('');
      const response = await budget.fetch(new Request('https://budget.internal/decide', {
        method: 'POST', headers: {'Content-Type': 'application/json', 'X-Client': client},
        body: JSON.stringify({...state, model}),
      }));
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
      if (b.count >= 180 || (b.clients[client] ?? 0) >= 120) return false;
      b.count++; b.clients[client] = (b.clients[client] ?? 0) + 1;
      await storage.put('budget', b);
      return true;
    });
  }
  async fetch(request) {
    if (this.env.ENABLED !== 'true' || !this.env.TYPESAFE_API_KEY) return json({error: 'Jev disabled'}, 503);
    let state, model;
    try {({model = MODEL, ...state} = await boundedJSON(request));} catch {return json({error: 'Invalid telemetry'}, 400);}
    if (!MODELS.includes(model) || !validState(state)) return json({error: 'Invalid telemetry'}, 400);
    const client = request.headers.get('X-Client');
    if (!/^[a-f0-9]{64}$/.test(client ?? '')) return json({error: 'Invalid client'}, 400);
    if (!await this.reserve(client)) return json({error: 'Rate limited'}, 429);
    const axes = actionSpace.phases[state.phase];
    const questions = Object.fromEntries(AXES.map(axis => [axis, {type: 'choice',
      instructions: axes[axis].instructions,
      criteria: Object.fromEntries(axes[axis].actions.map(a => [a.id, a.criterion])),
    }]));
    let received = false;
    try {
      // Exactly one fixed request with an allowlisted version; no URL/question relay or retries.
      // Workers supports manual, not redirect:error; !ok below rejects every redirect.
      const response = await fetch(ENDPOINT, {method: 'POST', redirect: 'manual',
        signal: AbortSignal.timeout(10000), headers: {'Content-Type': 'application/json',
          Authorization: `Bearer ${this.env.TYPESAFE_API_KEY}`},
        body: JSON.stringify({model, state, questions})});
      if (!response.ok) {await response.body?.cancel(); return json({error: 'Jev request failed'}, 502);}
      received = true;
      const data = await boundedJSON(response, 32768);
      if (data.model !== model) return json({error: 'Unexpected Jev model'}, 502);
      if (data.truncated === true || (data.truncation && Object.keys(data.truncation).length)) return json({error: 'Jev context truncated'}, 502);
      if (!exact(data.answers, AXES)) return json({error: 'Invalid Jev answers'}, 502);
      const action_ids = {}, command = {};
      for (const axis of AXES) {
        const answer = data.answers[axis];
        if (answer?.type !== 'choice' || typeof answer.choice !== 'string') return json({error: 'Invalid Jev choice'}, 502);
        const action = axes[axis].actions.find(a => a.id === answer.choice);
        if (!action) return json({error: 'Invalid Jev action'}, 502);
        action_ids[axis] = action.id; command[axis] = action.command;
      }
      return json({model, action_ids, command});
    } catch {return json({error: received ? 'Invalid Jev response' : 'Jev request unavailable'}, 502);}
  }
}
