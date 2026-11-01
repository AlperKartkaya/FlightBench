import { Color, Material, MeshStandardMaterial, Quaternion, Vector3 } from 'three';

export type Sample = { time: number; position: number[]; quaternion: number[] };
export type Ghost = { key: string; controller: string; score: number; success?: boolean; status?: string; samples: Sample[] };

export function bestGhost(runs: Ghost[], key: string, controller: string): Ghost | undefined {
  return runs.filter(run => run.key === key && run.controller === controller)
    .reduce<Ghost | undefined>((best, run) => !best || run.score > best.score ? run : best, undefined);
}

export function poseAt(samples: Sample[], time: number) {
  let low = 0, high = samples.length - 1;
  while (low < high) {
    const mid = Math.floor((low + high) / 2);
    if (samples[mid].time < time) low = mid + 1;
    else high = mid;
  }
  const b = samples[low], a = samples[Math.max(0, low - 1)];
  const alpha = b.time === a.time ? 0 : Math.max(0, Math.min(1, (time - a.time) / (b.time - a.time)));
  return {
    position: new Vector3().fromArray(a.position).lerp(new Vector3().fromArray(b.position), alpha),
    quaternion: new Quaternion().fromArray(a.quaternion).normalize().slerp(new Quaternion().fromArray(b.quaternion).normalize(), alpha),
  };
}

export function selectGhost(runs: Ghost[], key: string, choice: string): Ghost | undefined {
  const compatible = runs.filter(run => run.key === key);
  if (choice === 'human') return bestGhost(compatible.filter(run => run.success), key, 'human');
  return compatible.filter(run => choice === 'previous' || run.controller === choice).at(-1);
}

export function smoothReplayTime(current: number, target: number, dt: number): number {
  return current + (target - current) * (1 - Math.exp(-10 * Math.max(0, dt)));
}

export function ghostMaterial(source: Material, color: number): Material {
  const copy = source.clone();
  copy.transparent = true;
  copy.opacity = 0.45;
  copy.depthWrite = false;
  // Coincident human/ghost surfaces must not fight for the same depth value.
  copy.polygonOffset = true;
  copy.polygonOffsetFactor = -1;
  copy.polygonOffsetUnits = -1;
  if ('color' in copy) (copy.color as Color).set(color);
  if (copy instanceof MeshStandardMaterial) {
    copy.emissive.set(color);
    copy.emissiveIntensity = 0.4;
  }
  return copy;
}
