import test from 'node:test';
import assert from 'node:assert/strict';
import { bestGhost, poseAt } from './ghosts.ts';
const samples = [
  { time: 0, position: [0, 0, 0], quaternion: [0, 0, 0, 1] },
  { time: 2, position: [10, 4, 2], quaternion: [0, 1, 0, 0] },
];
test('replay interpolates simulation time and clamps endpoints without mutating samples', () => {
  const before = JSON.stringify(samples);
  assert.deepEqual(poseAt(samples, 1).position.toArray(), [5, 2, 1]);
  assert.ok(Math.abs(poseAt(samples, 1).quaternion.length() - 1) < 1e-12);
  assert.deepEqual(poseAt(samples, -1).position.toArray(), [0, 0, 0]);
  assert.deepEqual(poseAt(samples, 3).position.toArray(), [10, 4, 2]);
  assert.equal(JSON.stringify(samples), before);
});
test('best score requires matching setup and controller; higher score replaces PB', () => {
  const runs = [
    { key: 'a', controller: 'human', score: 20, samples },
    { key: 'b', controller: 'human', score: 100, samples },
    { key: 'a', controller: 'jev', score: 90, samples },
    { key: 'a', controller: 'human', score: 30, samples },
  ];
  assert.equal(bestGhost(runs, 'a', 'human')?.score, 30);
  assert.equal(bestGhost(runs, 'a', 'jev')?.score, 90);
  assert.equal(bestGhost(runs, 'missing', 'human'), undefined);
});
test('previous flight includes failures while PB only includes safe landings', async () => {
  const { selectGhost } = await import('./ghosts.ts');
  const runs = [
    { key: 'a', controller: 'human', score: 70, success: true, status: 'landed', samples },
    { key: 'a', controller: 'human', score: 90, success: false, status: 'interrupted', samples },
    { key: 'a', controller: 'jev', score: 0, success: false, status: 'crash', samples },
  ];
  assert.equal(selectGhost(runs, 'a', 'previous')?.score, 0);
  assert.equal(selectGhost(runs, 'a', 'human')?.score, 70);
  assert.equal(selectGhost(runs, 'a', 'jev')?.status, 'crash');
  assert.equal(selectGhost(runs, 'other', 'previous'), undefined);
});
test('replay clock advances smoothly between telemetry updates without overshoot', async () => {
  const { smoothReplayTime } = await import('./ghosts.ts');
  const first = smoothReplayTime(1, 1.1, 1 / 60);
  const second = smoothReplayTime(first, 1.1, 1 / 60);
  assert.ok(first > 1 && second > first && second < 1.1);
  assert.equal(smoothReplayTime(1, 1.1, 0), 1);
});
test('ghost materials avoid coplanar flicker without mutating the human material', async () => {
  const { MeshStandardMaterial } = await import('three');
  const { ghostMaterial } = await import('./ghosts.ts');
  const human = new MeshStandardMaterial({color: 0xffffff});
  const ghost = ghostMaterial(human, 0x00ffff);
  assert.notEqual(ghost, human);
  assert.equal(ghost.polygonOffset, true);
  assert.equal(ghost.depthWrite, false);
  assert.equal(ghost.transparent, true);
  assert.equal(human.transparent, false);
  assert.equal(human.depthWrite, true);
  assert.equal(human.color.getHex(), 0xffffff);
  ghost.dispose(); human.dispose();
});
test('ghost propeller rotates independently of the human visual', async () => {
  const { Group, Object3D } = await import('three');
  const { spinGhostPropeller } = await import('./ghosts.ts');
  const human = new Group(); const propeller = new Object3D(); propeller.name = 'Propeller_Cone'; human.add(propeller);
  const ghost = human.clone(true);
  spinGhostPropeller(ghost, .1);
  assert.equal(propeller.rotation.z, 0);
  assert.equal(ghost.getObjectByName('Propeller_Cone')!.rotation.z, 6.5);
});

test('live pilots and replay identities have distinct, stable muted race colors', async () => {
  const { racerColor } = await import('./ghosts.ts');
  const ids = ['baseline', 'jev-1.13.0', 'jev-1.14.0', 'replay:previous', 'replay:human', 'replay:jev'];
  assert.equal(new Set(ids.map(racerColor)).size, ids.length);
  for (const id of ids) assert.equal(racerColor(id), racerColor(id));
});

test('muted ghost tints never change the original aircraft material', async () => {
  const { MeshStandardMaterial } = await import('three');
  const { racerColor, ghostMaterial } = await import('./ghosts.ts');
  const source = new MeshStandardMaterial({color: 0xa53226});
  const original = source.color.getHex();
  for (const id of ['baseline', 'jev-1.13.0', 'jev-1.14.0', 'replay:previous']) {
    const ghost = ghostMaterial(source, racerColor(id));
    assert.equal((ghost as typeof source).color.getHex(), racerColor(id));
    assert.equal(source.color.getHex(), original);
    ghost.dispose();
  }
  source.dispose();
});
