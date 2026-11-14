import { Quaternion, Vector3 } from 'three';

export function updateChasePosition(
  camera: Vector3, subject: Vector3, previousSubject: Vector3,
  rotation: Quaternion, offset: Vector3, dt: number, starting = false,
): void {
  // Only the startup fly-in eases world position; normal flight must not pump during AI pauses.
  if (!starting) camera.add(subject.clone().sub(previousSubject));
  camera.lerp(subject.clone().add(offset.clone().applyQuaternion(rotation)), 1 - Math.exp(-6 * dt));
  previousSubject.copy(subject);
}
