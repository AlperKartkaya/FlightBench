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

test('north-up flow bearing follows the cloth downstream, opposite the source bearing', () => {
  for (const [headwind_mps, crosswind_mps, expected] of [[8, 0, 180], [-8, 0, 0], [0, 8, 90], [0, -8, 270]]) {
    const sock = settle({headwind_mps, crosswind_mps});
    const delta = ((sock.flowBearingDeg - expected + 540) % 360) - 180;
    assert.ok(Math.abs(delta) < .001);
  }
  const sock = settle({headwind_mps: 8, crosswind_mps: 0});
  sock.update({headwind_mps: -8, crosswind_mps: 0}, 10, 1 / 60, true);
  assert.notEqual(Math.round(sock.flowBearingDeg), 0, 'Graphic must not jump ahead of damped cloth');
});

test('instrument readings follow the same damped wind as the 3D fabric', () => {
  for (const wind of [
    {headwind_mps: 5, crosswind_mps: 4, vertical_wind_mps: -.6},
    {headwind_mps: -3, crosswind_mps: -7, vertical_wind_mps: .4},
  ]) {
    const sock = settle(wind);
    const point = tail(sock);
    const actual = (Math.atan2(point.z, point.x) * 180 / Math.PI + 360) % 360;
    assert.ok(Math.abs(((actual - sock.flowBearingDeg + 540) % 360) - 180) < .001);
    assert.ok(Math.abs(sock.speedMps - Math.hypot(wind.headwind_mps, wind.crosswind_mps)) < .001);
    assert.ok(Math.abs(sock.verticalMps - wind.vertical_wind_mps) < .001);
    const before = sock.speedMps;
    sock.update({headwind_mps: 0, crosswind_mps: 0}, 10, 1 / 60, true);
    assert.ok(sock.speedMps < before && sock.speedMps > 0, 'Readings must not jump ahead of cloth');
  }
});
