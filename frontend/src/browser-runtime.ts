import { Euler, Quaternion, MathUtils } from 'three';
import type { RunConfig } from './results.ts';

type Message = { type: string; [key: string]: any };

// Same runway frame as environment.snapshot(): +X forward, +Y up, +Z right.
export function browserSnapshot(data: Message, runId: string): Message {
  const { runway: r, flight: f } = data.observation;
  const rad = MathUtils.degToRad;
  return {
    ...data, run_id: runId, score: data.result.quality, status: data.result.reason,
    position: [r.along_track_m, r.altitude_agl_m, r.centerline_offset_m],
    quaternion: new Quaternion().setFromEuler(new Euler(
      rad(f.roll_deg), -rad(r.heading_error_deg ?? f.heading_deg - 90), rad(f.pitch_deg), 'YZX',
    )).toArray(),
  };
}

export class BrowserRuntime {
  private worker: Worker;
  private ready = false;
  private runwayHeading = 90;
  private attitudeLimits = true;
  private opponents = new Map<string, BrowserRuntime>();
  private raceGeneration = 0;
  private startingRace = false;
  private url: URL;
  private runId: string | null = null;
  private accepted = false;
  private last: Message | null = null;
  private config: RunConfig = {};
  private startedAt = '';
  private receive: (message: Message) => void;

  constructor(url: URL, receive: (message: Message) => void) {
    this.receive = receive;
    this.url = url;
    this.worker = new Worker(url, { type: 'module' });
    this.worker.onmessage = ({ data }) => this.handle(data);
    this.worker.onerror = () => {
      this.worker.terminate();
      this.clearOpponents();
      this.ready = false;
      if (this.accepted) this.finish('controller_error');
      receive({ type: 'offline', message: 'Physics Worker failed. Reload to retry.' });
    };
    this.worker.postMessage({ type: 'init' });
  }

  private finish(reason?: string) {
    if (!this.runId || !this.accepted || !this.last) return;
    const runId = this.runId;
    this.runId = null;
    this.accepted = false;
    const outcome = { ...this.last.result, status: reason ?? this.last.result.reason };
    if (reason) Object.assign(outcome, { reason, success: false, quality: 0 });
    this.receive({ type: 'run_finished', run_id: runId, record: {
      run_id: runId, source: 'browser-wasm', started_at: this.startedAt,
      finished_at: new Date().toISOString(), config: this.config, outcome,
      diagnostics: { persistence: 'none', physics_hz: 120 },
    } });
  }

  private handle(data: Message) {
    if (data.type === 'ready') {
      this.ready = true;
      this.runwayHeading = data.runway_heading_deg ?? 90;
      this.attitudeLimits = data.attitude_limits ?? true;
      this.receive({ type: 'ready' });
      return;
    }
    if (data.type === 'error' && !this.ready) {
      this.receive({ type: 'offline', message: data.message });
      return;
    }
    // Ignore queued telemetry/stop acknowledgements belonging to a reset or old run.
    if (!this.runId || data.run_id !== this.runId) return;
    if (data.type === 'error') {
      if (this.accepted) this.finish('controller_error');
      else {this.runId = null; this.clearOpponents();}
      this.receive({ type: 'error', message: data.message });
    } else if (data.type === 'stopped') this.finish('stopped');
    else if (data.type === 'state') {
      if (!this.accepted) {
        this.accepted = true;
        this.receive({ type: 'run_started', run_id: this.runId, config: this.config });
      }
      this.last = data;
      this.receive(browserSnapshot(data, this.runId));
      if (data.done) this.finish();
    }
  }

  private startRun(message: Message): void {
    const { type, proxy: _proxy, invite: _invite, ...config } = message;
    this.config = {...config, runway_heading_deg: this.runwayHeading, attitude_limits: this.attitudeLimits};
    this.runId = crypto.randomUUID();
    this.accepted = false;
    this.last = null;
    this.startedAt = new Date().toISOString();
    this.worker.postMessage({
      type, run_id: this.runId, mode: config.controller, model: config.model,
      timing_mode: config.mode ?? 'lockstep', scenario: config.scenario ?? 'easy', seed: typeof config.seed === 'number' ? config.seed : 42,
    });
  }

  private clearOpponents(): void {
    this.raceGeneration++;
    this.startingRace = false;
    for (const opponent of this.opponents.values()) {
      opponent.send({type: 'reset'});
      opponent.worker.terminate();
    }
    this.opponents.clear();
  }

  send(message: Message): boolean {
    if (!this.ready) return false;
    if (message.type === 'start' || message.type === 'start_race') {
      if (this.runId || this.startingRace) return false;
      this.clearOpponents();
      const {opponents = [], ...config} = message;
      if (message.type === 'start_race') {
        const ids = ['baseline', 'jev-1.13.0', 'jev-1.14.0'];
        if (!Array.isArray(opponents) || !opponents.length || opponents.length > 3 || new Set(opponents).size !== opponents.length ||
            opponents.some(id => !ids.includes(id))) return false;
        this.startingRace = true;
        const generation = this.raceGeneration;
        const waiting = new Set(opponents);
        const startAll = () => {
          if (waiting.size || generation !== this.raceGeneration) return;
          this.startingRace = false;
          this.startRun({...config, type: 'start'});
          for (const [id, opponent] of this.opponents) {
            opponent.send({...config, type: 'start', controller: id === 'baseline' ? 'baseline' : 'jev',
              model: id === 'baseline' ? null : id,
              human_assistance: {auto_center: false, wing_leveler: false}});
          }
        };
        for (const id of opponents) {
          const opponent = new BrowserRuntime(this.url, event => {
            if (generation !== this.raceGeneration) return;
            if (event.type === 'ready') { waiting.delete(id); startAll(); }
            else if (event.type === 'offline' && this.startingRace) {
              this.clearOpponents();
              this.receive({type: 'error', message: 'Opponent physics could not initialize. Reload to retry.'});
            } else this.receive({type: 'ghost', opponent_id: id, message: event});
          });
          this.opponents.set(id, opponent);
        }
      } else this.startRun({...config, type: 'start'});
    } else if (message.type === 'reset') {
      this.clearOpponents();
      this.finish('reset');
      this.runId = null;
      this.accepted = false;
      this.worker.postMessage({ type: 'stop' });
      this.receive({ type: 'idle' });
    } else if (message.type === 'stop') {
      for (const opponent of this.opponents.values()) opponent.send({type: 'stop'});
      this.worker.postMessage({ type: 'stop' });
    }
    else if (message.type === 'action' && this.runId) {
      const { aileron, elevator, rudder, throttle } = message.action;
      this.worker.postMessage({ type: 'control', command: { aileron, elevator, rudder, throttle } });
    } else return false;
    return true;
  }
}
