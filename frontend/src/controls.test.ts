import test from "node:test";
import assert from "node:assert/strict";
import { updateHumanControls, adjustControl, centerSurfaces, defaultControls, type Control } from "./controls.ts";

const apply = (key: string) => {
  const control: Control = { aileron: 0, elevator: 0, rudder: 0, throttle: .5 };
  updateHumanControls(control, new Set([key]), .1);
  return control;
};

test("keyboard follows experimentally measured c172x command signs", () => {
  assert.ok(apply("KeyW").elevator > 0, "W commands nose down");
  assert.ok(apply("KeyS").elevator < 0, "S commands nose up");
  assert.ok(apply("KeyA").aileron < 0, "A commands left bank");
  assert.ok(apply("KeyD").aileron > 0, "D commands right bank");
  assert.ok(apply("KeyQ").rudder > 0, "Q commands yaw left");
  assert.ok(apply("KeyE").rudder < 0, "E commands yaw right");
});

test("surfaces auto-center to trim while throttle retains its setting", () => {
  const control: Control = { aileron: .4, elevator: -.4, rudder: .4, throttle: .7 };
  updateHumanControls(control, new Set(), 1.0);
  assert.equal(control.aileron, -0.15);
  assert.equal(control.elevator, 0.17);
  assert.equal(control.rudder, 0.09);
  assert.equal(control.throttle, 0.7);
});

test("surfaces retain their settings when autoCenter is disabled", () => {
  const control: Control = { aileron: .4, elevator: -.4, rudder: .4, throttle: .7 };
  updateHumanControls(control, new Set(), .1, { autoCenter: false });
  assert.deepEqual(control, { aileron: .4, elevator: -.4, rudder: .4, throttle: .7 });
});

test("adjustControl increments correctly and centers surfaces to stable trim", () => {
  const control = defaultControls();
  assert.deepEqual(control, { aileron: -0.15, elevator: 0.17, rudder: 0.09, throttle: 0.5 });
  adjustControl(control, "elevator", -0.05);
  assert.equal(control.elevator, 0.12);
  centerSurfaces(control);
  assert.deepEqual(control, { aileron: -0.15, elevator: 0.17, rudder: 0.09, throttle: 0.5 });
});

test("wingLeveler actively counteracts roll and stabilizes pitch", () => {
  const control: Control = defaultControls();
  // Aircraft banked right (+15 deg) with positive roll rate
  updateHumanControls(control, new Set(), 0.1, {
    autoCenter: true,
    wingLeveler: true,
    currentRollDeg: 15,
    rollRateRadS: 0.1,
  });
  // Must command negative aileron (left bank) stronger than trim (-0.15) to level wings
  assert.ok(control.aileron < -0.3, "commands left aileron to recover right bank");

  // Aircraft diving nose-down (-5 deg pitch, -5 m/s sink)
  updateHumanControls(control, new Set(), 0.1, {
    autoCenter: true,
    wingLeveler: true,
    currentPitchDeg: -5,
    verticalSpeedMps: -5,
  });
  // Must command nose-up elevator (< trim 0.17) to arrest the dive
  assert.ok(control.elevator < 0.10, "commands nose-up elevator to recover from dive");
});

test("wingLeveler actively corrects X-track offset toward runway centerline", () => {
  const controlLeft: Control = defaultControls();
  // Aircraft is 60m left of runway centerline (cross_track_error_m = -60) with 0 deg roll
  updateHumanControls(controlLeft, new Set(), 0.1, {
    autoCenter: true,
    wingLeveler: true,
    currentRollDeg: 0,
    crossTrackErrorM: -60,
    headingErrorDeg: 0,
  });
  // Must command positive aileron (right bank) to intercept centerline from the left
  assert.ok(controlLeft.aileron > -0.15, "commands right aileron to steer right toward centerline");

  const controlRight: Control = defaultControls();
  // Aircraft is 60m right of runway centerline (cross_track_error_m = +60) with 0 deg roll
  updateHumanControls(controlRight, new Set(), 0.1, {
    autoCenter: true,
    wingLeveler: true,
    currentRollDeg: 0,
    crossTrackErrorM: 60,
    headingErrorDeg: 0,
  });
  // Must command negative aileron (left bank) to steer back toward centerline
  assert.ok(controlRight.aileron < -0.15, "commands left aileron to steer left toward centerline");

  // Pilot input takes immediate full priority
  const controlPilot: Control = defaultControls();
  updateHumanControls(controlPilot, new Set(["KeyA"]), 0.1, {
    autoCenter: true,
    wingLeveler: true,
    currentRollDeg: 0,
    crossTrackErrorM: -60,
  });
  assert.ok(controlPilot.aileron < -0.2, "pilot KeyA immediately commands bank left despite X-track");
});

test("centerSurfaces resets throttle along with all aerodynamic surfaces", () => {
  const control: Control = { aileron: 0.5, elevator: -0.3, rudder: -0.2, throttle: 0.85 };
  centerSurfaces(control);
  assert.equal(control.throttle, 0.5);
  assert.equal(control.aileron, -0.15);
  assert.equal(control.elevator, 0.17);
  assert.equal(control.rudder, 0.09);
});

test("wingLeveler manages throttle during approach, flare, and touchdown", () => {
  // 1. Final approach: regulates airspeed toward ~29 m/s
  const controlFast: Control = defaultControls();
  updateHumanControls(controlFast, new Set(), 0.5, {
    wingLeveler: true,
    altitudeAglM: 40,
    airspeedMps: 34, // fast approach
  });
  assert.ok(controlFast.throttle < 0.50, "reduces throttle when approaching too fast");

  const controlSlow: Control = defaultControls();
  updateHumanControls(controlSlow, new Set(), 0.5, {
    wingLeveler: true,
    altitudeAglM: 40,
    airspeedMps: 24, // slow approach
  });
  assert.ok(controlSlow.throttle > 0.50, "adds throttle when approaching too slow");

  // 2. Landing flare: below 18m, smoothly retards throttle toward idle
  const controlFlare: Control = defaultControls();
  updateHumanControls(controlFlare, new Set(), 1.0, {
    wingLeveler: true,
    altitudeAglM: 6.0, // flare height
  });
  assert.ok(controlFlare.throttle < 0.35, "smoothly reduces throttle during flare");

  // 3. Touchdown / On Ground: cuts throttle to 0.0 for rollout braking
  const controlGround: Control = defaultControls();
  updateHumanControls(controlGround, new Set(), 2.0, {
    wingLeveler: true,
    altitudeAglM: 0.5,
    onGround: true,
  });
  assert.equal(controlGround.throttle, 0.0, "cuts throttle to 0.0 on touchdown / rollout");

  // 4. Pilot manual override: holding KeyR increases throttle despite auto-throttle
  const controlOverride: Control = defaultControls();
  updateHumanControls(controlOverride, new Set(["KeyR"]), 0.2, {
    wingLeveler: true,
    altitudeAglM: 5.0,
  });
  assert.ok(controlOverride.throttle > 0.50, "pilot throttle up overrides flare idle");
});
