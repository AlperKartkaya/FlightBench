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
