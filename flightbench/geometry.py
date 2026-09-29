"""Aviation NED/body → runway Three.js (+X forward, +Y up, +Z right)."""

import math

import numpy as np


def wrap_degrees(angle: float) -> float:
    return (angle + 180.0) % 360.0 - 180.0


def angle_delta(current: float, previous: float) -> float:
    return float(wrap_degrees(current - previous))


def attitude_quaternion(roll_deg, pitch_deg, heading_deg, runway_heading_deg=90):
    phi, theta, psi = map(math.radians, (roll_deg, pitch_deg, heading_deg))
    c, s = math.cos, math.sin
    # Body forward/right/down to north/east/down, aerospace 3-2-1 rotation.
    rotation = np.array(
        [
            [
                c(theta) * c(psi),
                s(phi) * s(theta) * c(psi) - c(phi) * s(psi),
                c(phi) * s(theta) * c(psi) + s(phi) * s(psi),
            ],
            [
                c(theta) * s(psi),
                s(phi) * s(theta) * s(psi) + c(phi) * c(psi),
                c(phi) * s(theta) * s(psi) - s(phi) * c(psi),
            ],
            [-s(theta), s(phi) * c(theta), c(phi) * c(theta)],
        ]
    )
    h = math.radians(runway_heading_deg)
    world = np.array([[c(h), s(h), 0], [0, 0, -1], [-s(h), c(h), 0]])
    model = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]])
    m = world @ rotation @ model
    # Largest-component conversion remains stable at 180 degrees.
    candidates = np.array(
        [
            1 + m[0, 0] - m[1, 1] - m[2, 2],
            1 - m[0, 0] + m[1, 1] - m[2, 2],
            1 - m[0, 0] - m[1, 1] + m[2, 2],
            1 + np.trace(m),
        ]
    )
    i = int(np.argmax(candidates))
    q = np.zeros(4)
    q[i] = math.sqrt(max(0, candidates[i])) / 2
    d = 4 * q[i]
    if i == 3:
        q[:3] = [(m[2, 1] - m[1, 2]) / d, (m[0, 2] - m[2, 0]) / d, (m[1, 0] - m[0, 1]) / d]
    else:
        j, k = (i + 1) % 3, (i + 2) % 3
        q[j], q[k] = (m[j, i] + m[i, j]) / d, (m[k, i] + m[i, k]) / d
        q[3] = (m[k, j] - m[j, k]) / d
    return (q / np.linalg.norm(q)).tolist()
