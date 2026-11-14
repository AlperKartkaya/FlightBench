import { Quaternion, Vector3 } from 'three';

export function updateChasePosition(
  camera: Vector3, subject: Vector3, previousSubject: Vector3,
  rotation: Quaternion, offset: Vector3, dt: number,
): void {
  // Follow translation immediately; damping world position pumps the distance during AI pauses.
  camera.add(subject.clone().sub(previousSubject));
  camera.lerp(subject.clone().add(offset.clone().applyQuaternion(rotation)), 1 - Math.exp(-6 * dt));
  previousSubject.copy(subject);
}
