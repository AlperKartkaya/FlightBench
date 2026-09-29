export type Control = { aileron: number; elevator: number; rudder: number; throttle: number };

export type ControlOptions = {
  /** If true, control surfaces spring back to trim when keys are released. Default: true. */
  autoCenter?: boolean;
  /** If true and pilot is hands-off, actively levels wings, aligns with runway centerline, and stabilizes pitch. */
  wingLeveler?: boolean;
  /** Current aircraft roll angle in degrees. */
  currentRollDeg?: number;
  /** Roll rate in rad/s (for damping). */
  rollRateRadS?: number;
  /** Pitch angle in degrees. */
  currentPitchDeg?: number;
  /** Vertical speed in m/s. */
  verticalSpeedMps?: number;
  /** Pitch rate in rad/s. */
  pitchRateRadS?: number;
  /** Current altitude above ground level in meters. */
  altitudeAglM?: number;
  /** Airspeed in m/s. */
  airspeedMps?: number;
  /** True if aircraft wheels are on ground. */
  onGround?: boolean;
  /** Cross-track error in meters (+ right of centerline, - left of centerline). */
  crossTrackErrorM?: number;
  /** Heading error in degrees relative to runway (+ right/clockwise, - left). */
  headingErrorDeg?: number;
  /** Glideslope error in degrees (+ above, - below). */
  glideslopeErrorDeg?: number;
  /** Yaw rate in rad/s. */
  yawRateRadS?: number;
};

// Trim offsets matching the C172 backend (see flightbench/core.py) that counter
// propeller torque, P-factor, and gyroscopic precession for stable flight.
export const TRIM_AILERON = -0.15;
export const TRIM_ELEVATOR = 0.17;
export const TRIM_RUDDER = 0.09;

export const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

export const moveToward = (current: number, target: number, maxStep: number) => {
  if (Math.abs(target - current) <= maxStep) return target;
  return current + Math.sign(target - current) * maxStep;
};

// Deflection rates (units per second) when keys or buttons are held
const SURFACE_RATE = 1.4;
const CENTER_RATE = 2.2;
const THROTTLE_RATE = 0.45;

/**
 * Updates human control state.
 * By default, aerodynamic surfaces smoothly deflect while keys are held and
 * return to stable trim when released (flight stick behavior).
 * Throttle retains its value when keys are released.
 * When wingLeveler is active and pilot is hands-off, actively stabilizes roll,
 * guides the aircraft onto the runway centerline (cross-track correction),
 * aligns heading, and maintains a stable 3° approach glideslope.
 */
export function updateHumanControls(
  controls: Control,
  pressed: ReadonlySet<string>,
  dt: number,
  options: ControlOptions = {},
) {
  const autoCenter = options.autoCenter ?? true;
  const axis = (negative: string, positive: string) =>
    Number(pressed.has(positive)) - Number(pressed.has(negative));

  const aileronDir = axis("KeyA", "KeyD");
  const elevatorDir = axis("KeyS", "KeyW");
  const rudderDir = axis("KeyE", "KeyQ");
  const throttleDir = axis("KeyF", "KeyR");

  if (autoCenter) {
    // Aileron (Roll & Lateral Guidance to Runway Centerline)
    if (aileronDir !== 0) {
      const target = clamp(TRIM_AILERON + aileronDir * 0.85, -1, 1);
      controls.aileron = moveToward(controls.aileron, target, SURFACE_RATE * dt);
    } else if (options.wingLeveler && options.currentRollDeg != null) {
      // Calculate target bank angle to intercept runway centerline (X-track)
      let targetRoll = 0.0;
      if (options.crossTrackErrorM != null) {
        // Intercept heading offset: if left (z < 0), turn right (positive heading offset)
        const interceptHeading = clamp(-0.35 * options.crossTrackErrorM, -20.0, 20.0);
        const headingErr = options.headingErrorDeg ?? 0;
        const deltaHeading = headingErr - interceptHeading;
        // Bank into the required heading correction
        targetRoll = clamp(-0.75 * deltaHeading, -14.0, 14.0);

        // Near ground (< 15m), enforce wings-level touchdown to protect wingtips
        if (options.altitudeAglM != null && options.altitudeAglM < 15.0) {
          const groundFactor = clamp(options.altitudeAglM / 15.0, 0, 1);
          targetRoll *= groundFactor;
        }
      }

      const rollError = options.currentRollDeg - targetRoll;
      const rollRate = options.rollRateRadS ?? 0;
      const rollKp = 0.065;
      const rollKd = 0.22;
      const aileronCorrection = -(rollKp * rollError + rollKd * rollRate);
      const levelerAileron = clamp(TRIM_AILERON + aileronCorrection, -0.85, 0.85);
      controls.aileron = moveToward(controls.aileron, levelerAileron, Math.max(CENTER_RATE * 1.5, 3.5) * dt);
    } else {
      controls.aileron = moveToward(controls.aileron, TRIM_AILERON, CENTER_RATE * dt);
    }

    // Elevator (Pitch & Glideslope Stabilization)
    if (elevatorDir !== 0) {
      const target = clamp(TRIM_ELEVATOR + elevatorDir * 0.85, -1, 1);
      controls.elevator = moveToward(controls.elevator, target, SURFACE_RATE * dt);
    } else if (options.wingLeveler && (options.currentPitchDeg != null || options.verticalSpeedMps != null)) {
      const targetPitch = 3.0;
      const pitchError = (options.currentPitchDeg ?? targetPitch) - targetPitch;
      const targetVs = -1.8;
      const vsError = (options.verticalSpeedMps ?? targetVs) - targetVs;
      const pitchRate = options.pitchRateRadS ?? 0;
      let elevatorCorrection = 0.04 * pitchError + 0.06 * vsError - 0.18 * pitchRate;

      // Glideslope correction: gently pull or push to stay on the 3° glidepath
      if (options.glideslopeErrorDeg != null) {
        elevatorCorrection += clamp(0.08 * options.glideslopeErrorDeg, -0.22, 0.22);
      }

      // Ground flare assist: below 18m AGL, gently ease the nose up to prevent hard nose contact
      if (options.altitudeAglM != null && options.altitudeAglM < 18.0) {
        const flareBias = clamp((18.0 - options.altitudeAglM) / 18.0, 0, 1) * -0.22;
        elevatorCorrection += flareBias;
      }

      const levelerElevator = clamp(TRIM_ELEVATOR + elevatorCorrection, -0.65, 0.65);
      controls.elevator = moveToward(controls.elevator, levelerElevator, Math.max(CENTER_RATE * 1.2, 2.5) * dt);
    } else {
      controls.elevator = moveToward(controls.elevator, TRIM_ELEVATOR, CENTER_RATE * dt);
    }

    // Rudder (Yaw & Runway Heading Alignment)
    if (rudderDir !== 0) {
      const target = clamp(TRIM_RUDDER + rudderDir * 0.85, -1, 1);
      controls.rudder = moveToward(controls.rudder, target, SURFACE_RATE * dt);
    } else if (options.wingLeveler && options.headingErrorDeg != null) {
      const yawRate = options.yawRateRadS ?? 0;
      const rudderCorrection = 0.025 * options.headingErrorDeg - 0.12 * yawRate;
      const levelerRudder = clamp(TRIM_RUDDER + rudderCorrection, -0.65, 0.65);
      controls.rudder = moveToward(controls.rudder, levelerRudder, CENTER_RATE * dt);
    } else {
      controls.rudder = moveToward(controls.rudder, TRIM_RUDDER, CENTER_RATE * dt);
    }
  } else {
    // Step / sticky mode: retains position on release, but with assist support
    if (aileronDir !== 0) {
      controls.aileron = clamp(controls.aileron + aileronDir * SURFACE_RATE * dt, -1, 1);
    } else if (options.wingLeveler && options.currentRollDeg != null) {
      let targetRoll = 0.0;
      if (options.crossTrackErrorM != null) {
        const interceptHeading = clamp(-0.35 * options.crossTrackErrorM, -18.0, 18.0);
        const headingErr = options.headingErrorDeg ?? 0;
        targetRoll = clamp(-0.75 * (headingErr - interceptHeading), -12.0, 12.0);
      }
      const aileronCorrection = -(0.065 * (options.currentRollDeg - targetRoll) + 0.22 * (options.rollRateRadS ?? 0));
      const levelerAileron = clamp(TRIM_AILERON + aileronCorrection, -0.85, 0.85);
      controls.aileron = moveToward(controls.aileron, levelerAileron, CENTER_RATE * dt);
    }

    if (elevatorDir !== 0) {
      controls.elevator = clamp(controls.elevator + elevatorDir * SURFACE_RATE * dt, -1, 1);
    } else if (options.wingLeveler && options.currentPitchDeg != null) {
      const pitchError = options.currentPitchDeg - 3.0;
      const elevatorCorrection = 0.04 * pitchError - 0.18 * (options.pitchRateRadS ?? 0);
      const levelerElevator = clamp(TRIM_ELEVATOR + elevatorCorrection, -0.6, 0.6);
      controls.elevator = moveToward(controls.elevator, levelerElevator, CENTER_RATE * dt);
    }

    if (rudderDir !== 0) {
      controls.rudder = clamp(controls.rudder + rudderDir * SURFACE_RATE * dt, -1, 1);
    } else if (options.wingLeveler && options.headingErrorDeg != null) {
      const rudderCorrection = 0.02 * options.headingErrorDeg;
      controls.rudder = moveToward(controls.rudder, clamp(TRIM_RUDDER + rudderCorrection, -0.6, 0.6), CENTER_RATE * dt);
    }
  }

  // Throttle
  if (throttleDir !== 0) {
    // Manual pilot input via KeyR/KeyF or buttons has 100% priority
    controls.throttle = clamp(controls.throttle + throttleDir * THROTTLE_RATE * dt, 0, 1);
  } else if (options.wingLeveler) {
    // Intelligent Auto-Throttle for Approach & Landing
    let targetThrottle = 0.50;

    // 1. On ground or touchdown rollout (< 1.5m AGL): pull throttle to 0.0 (idle) for braking
    if (options.onGround || (options.altitudeAglM != null && options.altitudeAglM < 1.5)) {
      targetThrottle = 0.0;
    }
    // 2. Landing flare stage (< 18m AGL): smoothly retard throttle toward idle
    else if (options.altitudeAglM != null && options.altitudeAglM < 18.0) {
      const flareRatio = clamp(options.altitudeAglM / 18.0, 0, 1);
      targetThrottle = 0.50 * flareRatio;
    }
    // 3. Final approach (>= 18m AGL): maintain standard ~29 m/s approach airspeed
    else if (options.airspeedMps != null) {
      const airspeedError = options.airspeedMps - 29.0;
      targetThrottle = clamp(0.50 - 0.04 * airspeedError, 0.25, 0.70);
    }

    controls.throttle = moveToward(controls.throttle, targetThrottle, THROTTLE_RATE * 1.5 * dt);
  }
}

/** Adjusts a single control channel by a discrete step (e.g. for button clicks). */
export function adjustControl(controls: Control, channel: keyof Control, delta: number) {
  const min = channel === "throttle" ? 0 : -1;
  controls[channel] = clamp(Number((controls[channel] + delta).toFixed(4)), min, 1);
}

/** Resets all controls (pitch, roll, yaw surfaces and throttle) back to stable flight trim. */
export function centerSurfaces(controls: Control) {
  controls.aileron = TRIM_AILERON;
  controls.elevator = TRIM_ELEVATOR;
  controls.rudder = TRIM_RUDDER;
  controls.throttle = 0.5;
}

/** Default initial controls: all surfaces set to stable flight trim, throttle at 50%. */
export function defaultControls(): Control {
  return { aileron: TRIM_AILERON, elevator: TRIM_ELEVATOR, rudder: TRIM_RUDDER, throttle: 0.5 };
}

/** Retained for backward compatibility. */
export function trimControls(): Control {
  return defaultControls();
}
