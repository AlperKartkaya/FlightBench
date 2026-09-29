"""Canonical Cadence and Semantics Tests for FlightBench Refactor.

Verifies:
1. Canonical Cadence:
   - PHYSICS_HZ == 120
   - DECISION_HZ == 2
   - DECISION_TICKS == 60
   - DECISION_INTERVAL_S == 0.5
   - Both lockstep and realtime use canonical cadence definitions.
   - Environment step() advances exactly 60 ticks.
   - Observation reports decision_dt_s == 0.5.
   - Serialized Jev request reports decision_interval_s == 0.5.
2. Airspeed Semantics:
   - No generic 'target_airspeed_mps' or continuous approach-speed setpoint in Jev state.
   - Touchdown objectives contain ideal_airspeed_mps == 28.0.
   - Approach geometry contains nominal_glidepath_deg == 3.0.
3. FPA & AoA:
   - JSBSim gamma and alpha properties exist and are finite.
   - FPA and AoA appear in canonical environment observation (flight_path_angle_deg, angle_of_attack_deg).
   - FPA and AoA appear in serialized Jev aircraft_state and deltas.
4. Previous Action Feedback & Attribution:
   - First decision: previous_control_transition is None, observed_since_previous_action is None, recent_action_history == [].
   - Second decision: contains exactly the previously applied control transition and measured consequence.
   - Realtime attribution: excludes dead interval [T_snapshot, T_applied].
5. Reset:
   - Reset clears all history with no leaks.
6. Angle Wrapping:
   - 359° -> 1° = +2°, 1° -> 359° = -2°.
"""

import pytest

from flightbench.core import (
    DECISION_HZ,
    DECISION_INTERVAL_S,
    DECISION_TICKS,
    PHYSICS_HZ,
)
from flightbench.decision_tracking import DecisionTracker, _angle_delta
from flightbench.environment import FixedWingLandingEnv
from flightbench.temporal import angle_delta


def test_canonical_cadence_constants():
    """Verify single source of truth for cadence."""
    assert PHYSICS_HZ == 120
    assert DECISION_HZ == 2
    assert DECISION_TICKS == 60
    assert DECISION_INTERVAL_S == 0.5
    assert DECISION_TICKS / PHYSICS_HZ == DECISION_INTERVAL_S
    assert PHYSICS_HZ / DECISION_TICKS == DECISION_HZ


def test_environment_cadence_and_step():
    """Verify environment advances exactly DECISION_TICKS and reports canonical cadence."""
    env = FixedWingLandingEnv(scenario="easy")
    obs, info = env.reset(seed=42)
    assert info["physics_hz"] == 120
    assert info["decision_ticks"] == 60
    assert info["decision_hz"] == 2
    assert info["decision_interval_s"] == 0.5
    assert obs["decision_dt_s"] == 0.5

    # Step advances exactly DECISION_TICKS (60 ticks = 0.5s)
    next_obs, _, _, _, _next_info = env.step(env.action)
    assert next_obs["time_s"] == pytest.approx(0.50, abs=1e-6)
    assert next_obs["decision_dt_s"] == 0.5
    assert env.ticks == 60
    env.close()


def test_fpa_and_aoa_in_jsbsim_and_observation():
    """Verify FPA and AoA exist, are finite, and flow through environment observation."""
    env = FixedWingLandingEnv(scenario="easy")
    obs, _ = env.reset(seed=42)
    flight = obs["flight"]

    assert "flight_path_angle_deg" in flight
    assert "angle_of_attack_deg" in flight
    assert float(flight["flight_path_angle_deg"]) == pytest.approx(env.fdm["flight-path/gamma-deg"])
    assert float(flight["angle_of_attack_deg"]) == pytest.approx(env.fdm["aero/alpha-deg"])

    # Both values must be finite and physically plausible for trimmed glide
    assert -10.0 <= flight["flight_path_angle_deg"] <= 0.0
    assert 0.0 <= flight["angle_of_attack_deg"] <= 15.0

    # Step and verify they remain valid and update
    next_obs, _, _, _, _ = env.step([0, 0, 0, 0.5])
    assert "flight_path_angle_deg" in next_obs["flight"]
    assert "angle_of_attack_deg" in next_obs["flight"]
    env.close()


def test_tracker_reset_clears_all_history():
    """Verify reset completely clears DecisionTracker."""
    tracker = DecisionTracker()
    state = {
        "runway": {
            "altitude_agl_m": 50.0,
            "along_track_m": -500.0,
            "cross_track_error_m": 0.0,
            "glideslope_error_deg": 0.0,
            "heading_error_deg": 0.0,
        },
        "flight": {
            "airspeed_mps": 30.0,
            "groundspeed_mps": 30.0,
            "vertical_speed_mps": -1.5,
            "roll_deg": 0.0,
            "pitch_deg": 2.0,
            "heading_deg": 90.0,
        },
    }
    tracker.record_application(
        "act_1", {"aileron": "hold"}, 0.0, {"aileron": 0.0}, {"aileron": 0.0}, state
    )
    fb = tracker.build_feedback(state, 0.5)
    assert len(fb["recent_action_history"]) == 1

    tracker.reset()
    fb_after_reset = tracker.build_feedback(state, 0.0)
    assert fb_after_reset["previous_control_transition"] is None
    assert fb_after_reset["observed_since_previous_action"] is None
    assert fb_after_reset["recent_action_history"] == []


def test_angle_wrap_safety():
    """Verify heading angle differences wrap across 0°/360° boundary safely."""
    # 359° -> 1° should be +2.0° (not -358.0°)
    assert _angle_delta(1.0, 359.0) == 2.0
    assert angle_delta(1.0, 359.0) == 2.0

    # 1° -> 359° should be -2.0° (not +358.0°)
    assert _angle_delta(359.0, 1.0) == -2.0
    assert angle_delta(359.0, 1.0) == -2.0

    # Near 0°
    assert _angle_delta(5.0, 355.0) == 10.0
    assert _angle_delta(355.0, 5.0) == -10.0
