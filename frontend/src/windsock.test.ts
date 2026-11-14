import assert from 'node:assert/strict';
import test from 'node:test';
import { Mesh, Vector3 } from 'three';
import { createWindsock } from './windsock.ts';

const settle = (wind: {headwind_mps: number; crosswind_mps: number; vertical_wind_mps?: number}) => {
  const sock = createWindsock();
  for (let i = 0; i < 600; i++) sock.update(wind, i / 60, 1 / 60, true);
  return sock;
};
const tail = (sock: ReturnType<typeof createWindsock>) => {
  const cloth = sock.object.getObjectByName('windsock-cloth') as Mesh;
  const positions = cloth.geometry.getAttribute('position');
  const point = new Vector3();
  // Average the last cross-section, excluding its duplicated seam vertex.
  for (let i = positions.count - 13; i < positions.count - 1; i++) {
    point.add(new Vector3().fromBufferAttribute(positions, i));
  }
  cloth.updateWorldMatrix(true, false);
  return cloth.localToWorld(point.divideScalar(12)).sub(sock.object.position);
};

test('windsock points downstream for runway headwind and crosswind', () => {
  assert.ok(tail(settle({headwind_mps: 8, crosswind_mps: 0})).x < -3);
  assert.ok(tail(settle({headwind_mps: -8, crosswind_mps: 0})).x > 3);
  assert.ok(tail(settle({headwind_mps: 0, crosswind_mps: 8})).z > 3);
  assert.ok(tail(settle({headwind_mps: 0, crosswind_mps: -8})).z < -3);
});

test('calm fabric hangs down; stronger wind lifts and extends it', () => {
  const calm = tail(settle({headwind_mps: 0, crosswind_mps: 0}));
  const windy = tail(settle({headwind_mps: 8, crosswind_mps: 0}));
  assert.ok(calm.y < windy.y - 2);
  assert.ok(Math.hypot(calm.x, calm.z) < 1);
});

test('wind reversal is damped; reduced motion disables fabric flutter', () => {
  const sock = settle({headwind_mps: 8, crosswind_mps: 0});
  const before = tail(sock);
  sock.update({headwind_mps: -8, crosswind_mps: 0}, 10, 1 / 60, true);
  assert.ok(tail(sock).distanceTo(before) < .8);
  const cloth = sock.object.getObjectByName('windsock-cloth') as Mesh;
  const positions = () => Array.from(cloth.geometry.getAttribute('position').array);
  const steady = settle({headwind_mps: 8, crosswind_mps: 0});
  const steadyCloth = steady.object.getObjectByName('windsock-cloth') as Mesh;
  const fixed = Array.from(steadyCloth.geometry.getAttribute('position').array);
  steady.update({headwind_mps: 8, crosswind_mps: 0}, 100, 0, true);
  assert.deepEqual(Array.from(steadyCloth.geometry.getAttribute('position').array), fixed);
  const still = positions();
  sock.update({headwind_mps: -8, crosswind_mps: 0}, 11, 0, false);
  assert.notDeepEqual(positions(), still);
  assert.ok(positions().every(Number.isFinite));
});
