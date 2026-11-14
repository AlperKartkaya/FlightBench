import assert from 'node:assert/strict';
import test from 'node:test';
import { Quaternion, Vector3 } from 'three';
import { updateChasePosition } from './camera.ts';

test('chase distance stays fixed through lockstep decisions and mobile frame stalls', () => {
  const subject = new Vector3(-1500, 94, 0);
  const previous = subject.clone();
  const offset = new Vector3(-14, 3.8, 0);
  const camera = subject.clone().add(offset);
  const rotation = new Quaternion();
  for (let frame = 0; frame < 240; frame++) {
    // Advance, pause for an AI reply, then resume; include a dropped mobile frame.
    if (frame % 120 < 60) subject.x += frame % 10 === 0 ? 1.5 : 0.5;
    updateChasePosition(camera, subject, previous, rotation, offset, frame % 10 === 0 ? 0.05 : 1 / 60);
    assert.ok(Math.abs(camera.distanceTo(subject) - offset.length()) < 1e-9);
  }
});

test('chase rotation remains damped instead of snapping after a control change', () => {
  const subject = new Vector3(10, 20, 30), previous = subject.clone();
  const offset = new Vector3(-14, 3.8, 0), camera = subject.clone().add(offset);
  const rotation = new Quaternion().setFromAxisAngle(new Vector3(0, 1, 0), Math.PI / 2);
  const target = subject.clone().add(offset.clone().applyQuaternion(rotation));
  const distance = camera.distanceTo(target);
  updateChasePosition(camera, subject, previous, rotation, offset, 1 / 60);
  assert.ok(camera.distanceTo(target) > 0);
  assert.ok(camera.distanceTo(target) < distance);
});

test('flight-start fly-in eases the restart jump, then returns to stable chase', () => {
  const previous = new Vector3(225, 1, 0), offset = new Vector3(-14, 3.8, 0);
  const camera = previous.clone().add(offset), subject = new Vector3(-1500, 94, 0);
  const rotation = new Quaternion();
  const expected = camera.clone().lerp(subject.clone().add(offset), 1 - Math.exp(-6 / 60));
  updateChasePosition(camera, subject, previous, rotation, offset, 1 / 60, true);
  assert.ok(camera.distanceTo(expected) < 1e-9);
  assert.ok(camera.distanceTo(subject) > 1000, 'Restart snapped directly behind the plane');
  for (let frame = 1; frame < 240; frame++) {
    subject.x += .5;
    updateChasePosition(camera, subject, previous, rotation, offset, 1 / 60, frame < 90);
  }
  assert.ok(Math.abs(camera.distanceTo(subject) - offset.length()) < 1e-5);
});
