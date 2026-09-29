export type RunState = 'offline' | 'ready' | 'starting' | 'running' | 'complete';
export type RunEvent = 'connect' | 'disconnect' | 'start' | 'accepted' | 'finished' | 'error' | 'reset';

export function nextRunState(state: RunState, event: RunEvent): RunState {
  if (event === 'disconnect') return 'offline';
  if (event === 'connect' || event === 'reset') return 'ready';
  if (event === 'accepted') return 'running';
  if (event === 'finished') return 'complete';
  if (event === 'start' && (state === 'ready' || state === 'complete')) return 'starting';
  if (event === 'error' && state === 'starting') return 'ready';
  return state;
}

export type Touchdown = {
  airspeed_mps?: number; sink_rate_mps?: number; cross_track_m?: number;
  along_track_m?: number; pitch_deg?: number; roll_deg?: number;
};
export type Outcome = { success?: boolean; quality?: number; status?: string; reason?: string; touchdown?: Touchdown | null };
export type RunConfig = Record<string, string | number | boolean | null | undefined | { auto_center: boolean; wing_leveler: boolean }>;
export type RunRecord = {
  run_id: string; source: string; started_at: string; finished_at: string;
  config: RunConfig; outcome: Outcome; diagnostics: Record<string, number | string | null | Record<string, number>>;
  source_identity?: { source_hash?: string; versions?: Record<string, string> };
  final_state?: unknown; decisions?: unknown[];
};

export function measurement(value: unknown, digits: number, unit: string): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(digits)}${unit}` : 'N/A';
}

export function touchdownValues(result: Outcome): string[] {
  const t = result.touchdown;
  return [measurement(t?.airspeed_mps, 1, ' m/s'), measurement(t?.sink_rate_mps, 2, ' m/s'),
    measurement(t?.cross_track_m, 1, ' m'), measurement(t?.pitch_deg, 1, '°'), measurement(t?.roll_deg, 1, '°')];
}

export function outcomeLabel(status = 'unknown', success = false): string {
  if (success) return 'Safe landing';
  const labels: Record<string, string> = {
    interrupted: 'Interrupted', stopped: 'Stopped', reset: 'Reset', disconnected: 'Disconnected',
    time_limit: 'Time limit', crash: 'Crash', unsafe_touchdown: 'Unsafe touchdown',
    nose_first_contact: 'Nose-first contact', runway_excursion: 'Runway excursion',
    out_of_bounds: 'Out of bounds', nonfinite_state: 'Invalid simulation state',
    controller_error: 'Controller error', controller_timeout: 'Controller timeout',
    controller_unavailable: 'Controller unavailable', running: 'In flight', idle: 'Ready',
  };
  return labels[status] ?? status.replaceAll('_', ' ');
}

export function comparisonDifferences(a: RunConfig, b: RunConfig): string[] {
  return [...new Set([...Object.keys(a), ...Object.keys(b)])].sort()
    .filter((key) => JSON.stringify(a[key]) !== JSON.stringify(b[key]));
}

export function policyLabel(config: RunConfig): string {
  if (config.controller === 'human') {
    const assist = config.human_assistance;
    if (typeof assist === 'object' && assist) {
      if (assist.wing_leveler) return 'Human · landing assistance';
      if (assist.auto_center) return 'Human · auto-center';
    }
    return 'Human · unassisted';
  }
  if (String(config.controller).startsWith('jev')) {
    if (config.policy === 'direct-categorical') return 'Jev · experimental / direct controls';
    const variant = config.controller === 'jev-micro' ? 'micro' : config.action_variant;
    return `Jev · ${variant}${variant === 'guided' ? ' / baseline-assisted' : ''}${config.stability_maintainer ? ' / stability filter' : ''}`;
  }
  return String(config.controller ?? 'Unknown');
}
