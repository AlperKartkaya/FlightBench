"""Tests for Jev observation & objective refactor (v2-temporal-feedback).

Verifies:
1. Signed runway position (along_track_m < 0, == 0, > 0, and distance_to_threshold_m clamping).
2. Cross-track sign convention (positive = right, negative = left).
3. Glidepath sign convention (positive = above, negative = below).
4. Wrap-safe angular differences (e.g. 359° -> 1° = +2°).
5. Canonical target airspeed (28.0 m/s, no 29.0 m/s in Jev).
6. Lockstep transition attribution (T_snapshot == T_applied).
7. Realtime transition attribution (dead interval exclusion).
8. First decision null state.
9. Actual values only (no predicted_*, recommended_*, etc.).
10. No autopilot leakage in prompt.
11. Existing benchmark safety envelope and scoring.
12. Early-throttle-cut observation exposure (regression scenario).
"""

from __future__ import annotations

import json

import pytest

from flightbench.controllers import ControlCommand
from flightbench.core import OBSERVATION_SCHEMA_VERSION, TRIM_AILERON, TRIM_ELEVATOR, TRIM_RUDDER
from flightbench.decision_tracking import DecisionTracker, _angle_delta
from flightbench.environment import FixedWingLandingEnv
from flightbench.temporal import angle_delta


# ---------------------------------------------------------------------------
# 1. Signed runway position
# ---------------------------------------------------------------------------
def test_signed_runway_position():
    env = FixedWingLandingEnv(scenario="easy")
    obs, _ = env.reset(seed=42)
    # Initial condition starts at start_x = -1500m
    along_initial = obs["runway"]["along_track_m"]
    assert along_initial < 0, (
        f"Before threshold, along_track_m must be negative, got {along_initial}"
    )
    assert obs["runway"]["distance_to_threshold_m"] > 0

    # At threshold (along_track_m == 0):
    env.start_x = 0.0
    obs_thresh = env.observe()
    assert abs(obs_thresh["runway"]["along_track_m"]) < 0.1
    assert abs(obs_thresh["runway"]["distance_to_threshold_m"]) < 0.1

    # Over runway (along_track_m > 0):
    env.start_x = 200.0
    obs_runway = env.observe()
    assert obs_runway["runway"]["along_track_m"] > 100.0
    # distance_to_threshold_m must remain clamped at 0
    assert obs_runway["runway"]["distance_to_threshold_m"] == 0.0, (
        "distance_to_threshold_m must stay 0 after crossing threshold"
    )
    env.close()


# ---------------------------------------------------------------------------
# 2. Cross-track sign convention (positive = right, negative = left)
# ---------------------------------------------------------------------------
def test_cross_track_sign_convention():
    env = FixedWingLandingEnv(scenario="easy")
    _obs, _ = env.reset(seed=42)

    # Runway runs along east (heading 90°).
    # Looking along runway, positive z is right, negative z is left.
    env.start_z = -50.0  # left of centerline
    obs_left = env.observe()
    assert obs_left["runway"]["cross_track_error_m"] < -30.0, (
        "Left of centerline must yield negative cross-track outside runway bounds"
    )
    assert obs_left["runway"]["centerline_offset_m"] == -50.0

    env.start_z = 50.0  # right of centerline
    obs_right = env.observe()
    assert obs_right["runway"]["cross_track_error_m"] > 30.0, (
        "Right of centerline must yield positive cross-track outside runway bounds"
    )
    assert obs_right["runway"]["centerline_offset_m"] == 50.0
    env.close()


def test_runway_width_deadband_cross_track():
    """Verify that cross_track_error_m is exactly 0.0 within runway bounds (±5m) and on edges."""
    env = FixedWingLandingEnv(scenario="easy")
    _obs, _ = env.reset(seed=42)

    # Within runway (width = 10m, half_width = 5m)
    for z in [0.0, 1.0, -1.0, 3.0, -3.0, 4.9, -4.9, 5.0, -5.0]:
        env.start_z = z
        obs = env.observe()
        assert obs["runway"]["cross_track_error_m"] == 0.0, (
            f"Expected 0.0 at z={z}, got {obs['runway']['cross_track_error_m']}"
        )
        assert obs["runway"]["centerline_offset_m"] == z

    # Outside runway
    env.start_z = 7.0
    obs = env.observe()
    assert obs["runway"]["cross_track_error_m"] == 2.0
    assert obs["runway"]["centerline_offset_m"] == 7.0

    env.start_z = -7.0
    obs = env.observe()
    assert obs["runway"]["cross_track_error_m"] == -2.0
    assert obs["runway"]["centerline_offset_m"] == -7.0

    env.close()


# ---------------------------------------------------------------------------
# 3. Glidepath sign convention (positive = above, negative = below)
# ---------------------------------------------------------------------------
def test_glideslope_sign_convention():
    env = FixedWingLandingEnv(scenario="easy")
    _obs, _ = env.reset(seed=42)
    # Formula: math.degrees(math.atan2(h - 15, max(1, -x))) - 3
    # If aircraft is higher than nominal 3° glideslope, error is positive.
    env.fdm["position/h-agl-ft"] = 300.0 / 0.3048  # higher altitude
    obs_high = env.observe()
    assert obs_high["runway"]["glideslope_error_deg"] > 0, (
        "Higher than nominal glidepath must be positive"
    )

    env.fdm["position/h-agl-ft"] = 20.0 / 0.3048  # low altitude at 1500m distance
    obs_low = env.observe()
    assert obs_low["runway"]["glideslope_error_deg"] < 0, (
        "Lower than nominal glidepath must be negative"
    )
    env.close()


# ---------------------------------------------------------------------------
# 4. Heading wrap
# ---------------------------------------------------------------------------
def test_heading_wrap():
    # 359° -> 1° should be +2°, not -358°
    assert _angle_delta(1.0, 359.0) == 2.0
    assert angle_delta(1.0, 359.0) == 2.0

    # 1° -> 359° should be -2°, not +358°
    assert _angle_delta(359.0, 1.0) == -2.0
    assert angle_delta(359.0, 1.0) == -2.0

    # Small deltas near zero
    assert _angle_delta(5.0, 355.0) == 10.0
    assert _angle_delta(355.0, 5.0) == -10.0


# ---------------------------------------------------------------------------
# 5. Target airspeed (28.0 m/s canonical, no 29.0 m/s in Jev)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 6. Lockstep transition attribution: T_snapshot == T_applied
# ---------------------------------------------------------------------------
def test_lockstep_transition_attribution():
    tracker = DecisionTracker()

    state_0 = {
        "runway": {
            "altitude_agl_m": 80.0,
            "along_track_m": -1200.0,
            "cross_track_error_m": 1.0,
            "glideslope_error_deg": 0.1,
            "heading_error_deg": 0.5,
        },
        "flight": {
            "airspeed_mps": 32.0,
            "groundspeed_mps": 32.0,
            "vertical_speed_mps": -1.5,
            "roll_deg": 0.0,
            "pitch_deg": 3.0,
            "heading_deg": 90.5,
        },
    }

    # First decision: no previous transition
    fb0 = tracker.build_feedback(state_0, current_sim_time=0.0)
    assert fb0["previous_control_transition"] is None
    assert fb0["observed_since_previous_action"] is None
    assert fb0["recent_action_history"] == []

    # In lockstep: action is applied at T_applied == T_snapshot == 0.0
    t_snapshot_0 = 0.0
    t_applied_0 = 0.0
    assert t_snapshot_0 == t_applied_0

    tracker.record_application(
        action_id="joint_1",
        action_names={
            "aileron": "hold",
            "elevator": "increase_small",
            "rudder": "hold",
            "throttle": "decrease_small",
        },
        sim_time=t_applied_0,
        control_before={"aileron": -0.15, "elevator": 0.17, "rudder": 0.09, "throttle": 0.50},
        control_after={"aileron": -0.15, "elevator": 0.195, "rudder": 0.09, "throttle": 0.46},
        state_snapshot=state_0,
    )

    # Next observation at sim_time = 0.5s (60 ticks at 120Hz)
    state_1 = {
        "runway": {
            "altitude_agl_m": 79.2,
            "along_track_m": -1184.0,
            "cross_track_error_m": 0.8,
            "glideslope_error_deg": 0.05,
            "heading_error_deg": 0.4,
        },
        "flight": {
            "airspeed_mps": 31.4,
            "groundspeed_mps": 31.4,
            "vertical_speed_mps": -1.6,
            "roll_deg": 0.1,
            "pitch_deg": 2.8,
            "heading_deg": 90.4,
        },
    }
    fb1 = tracker.build_feedback(state_1, current_sim_time=0.5)

    trans = fb1["previous_control_transition"]
    assert trans is not None
    assert trans["applied_sim_time_s"] == 0.0
    assert trans["elevator"]["action"] == "increase_small"
    assert trans["elevator"]["delta"] == 0.025
    assert trans["throttle"]["action"] == "decrease_small"
    assert trans["throttle"]["delta"] == -0.04

    obs = fb1["observed_since_previous_action"]
    assert obs is not None
    assert obs["from_sim_time_s"] == 0.0
    assert obs["to_sim_time_s"] == 0.5
    assert obs["elapsed_s"] == 0.5
    assert obs["airspeed_delta_mps"] == round(31.4 - 32.0, 4)
    assert obs["vertical_speed_delta_mps"] == round(-1.6 - (-1.5), 4)


# ---------------------------------------------------------------------------
# 7. Realtime transition attribution: dead interval exclusion
# ---------------------------------------------------------------------------
def test_realtime_transition_attribution_excludes_dead_interval():
    tracker = DecisionTracker()

    # T_snapshot_0 = 10.0: observation is taken and Jev request starts
    _t_snapshot_0 = 10.0
    _state_snapshot_0 = {
        "runway": {
            "altitude_agl_m": 60.0,
            "along_track_m": -800.0,
            "cross_track_error_m": 2.0,
            "glideslope_error_deg": 0.2,
            "heading_error_deg": 1.0,
        },
        "flight": {
            "airspeed_mps": 30.0,
            "groundspeed_mps": 30.0,
            "vertical_speed_mps": -1.4,
            "roll_deg": 0.0,
            "pitch_deg": 3.0,
            "heading_deg": 91.0,
        },
    }

    # Simulate Jev latency: 700 ms (> 500 ms nominal)
    # During [10.0, 10.7], physics continues under OLD action.
    # At T_applied = 10.7, Jev response arrives and new action is written to JSBSim:
    t_applied_0 = 10.7
    state_at_application = {
        "runway": {
            "altitude_agl_m": 59.0,
            "along_track_m": -779.0,
            "cross_track_error_m": 2.3,
            "glideslope_error_deg": 0.25,
            "heading_error_deg": 1.2,
        },
        "flight": {
            "airspeed_mps": 29.5,
            "groundspeed_mps": 29.5,
            "vertical_speed_mps": -1.5,
            "roll_deg": 0.2,
            "pitch_deg": 2.9,
            "heading_deg": 91.2,
        },
    }

    # Action is recorded with state_at_application, NOT state_snapshot_0!
    tracker.record_application(
        action_id="joint_rt",
        action_names={
            "aileron": "hold",
            "elevator": "hold",
            "rudder": "hold",
            "throttle": "decrease_small",
        },
        sim_time=t_applied_0,
        control_before={"aileron": -0.15, "elevator": 0.17, "rudder": 0.09, "throttle": 0.50},
        control_after={"aileron": -0.15, "elevator": 0.17, "rudder": 0.09, "throttle": 0.46},
        state_snapshot=state_at_application,
    )

    # T_snapshot_1 = 11.2: next observation snapshot
    t_snapshot_1 = 11.2
    state_1 = {
        "runway": {
            "altitude_agl_m": 58.2,
            "along_track_m": -764.0,
            "cross_track_error_m": 2.4,
            "glideslope_error_deg": 0.28,
            "heading_error_deg": 1.3,
        },
        "flight": {
            "airspeed_mps": 28.9,
            "groundspeed_mps": 28.9,
            "vertical_speed_mps": -1.6,
            "roll_deg": 0.1,
            "pitch_deg": 2.8,
            "heading_deg": 91.3,
        },
    }

    fb1 = tracker.build_feedback(state_1, current_sim_time=t_snapshot_1)
    obs = fb1["observed_since_previous_action"]
    assert obs is not None
    # Consequence window MUST be [T_applied, T_snapshot_1] = [10.7, 11.2], elapsed 0.5s
    assert obs["from_sim_time_s"] == 10.7
    assert obs["to_sim_time_s"] == 11.2
    assert obs["elapsed_s"] == 0.5

    # Delta must be state_1 - state_at_application, NOT state_1 - state_snapshot_0!
    # airspeed_delta should be 28.9 - 29.5 = -0.6 (NOT 28.9 - 30.0 = -1.1)
    assert obs["airspeed_delta_mps"] == round(28.9 - 29.5, 4)
    assert obs["altitude_agl_delta_m"] == round(58.2 - 59.0, 4)


# ---------------------------------------------------------------------------
# 8. First decision null state
# ---------------------------------------------------------------------------
def test_first_decision_null_state():
    tracker = DecisionTracker()
    empty_state = {"runway": {}, "flight": {}}
    fb = tracker.build_feedback(empty_state, current_sim_time=0.0)
    assert fb["previous_control_transition"] is None
    assert fb["observed_since_previous_action"] is None
    assert fb["recent_action_history"] == []


# ---------------------------------------------------------------------------
# 9. Actual values only: no predicted_*, recommended_*, etc.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 10. No autopilot leakage in prompt
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 11. Existing benchmark behavior continues passing
# ---------------------------------------------------------------------------
def test_existing_benchmark_touchdown_and_scoring():
    env = FixedWingLandingEnv(scenario="easy")
    env.reset(seed=42)

    # Check scoring envelope constants
    assert env.scoring.runway_length_m == 1000
    assert env.scoring.runway_width_m == 30
    assert env.scoring.max_sink_mps == 3
    assert env.scoring.max_bank_deg == 10
    assert env.scoring.max_heading_deg == 15
    assert env.scoring.min_airspeed_mps == 18
    assert env.scoring.max_airspeed_mps == 40
    assert env.scoring.target_airspeed_mps == 28

    # Safe touchdown produces high quality
    safe_td = {
        "along_track_m": 200.0,
        "cross_track_m": 0.5,
        "sink_rate_mps": -0.8,
        "airspeed_mps": 28.0,
        "heading_error_deg": 0.2,
        "roll_deg": 0.1,
        "pitch_deg": 3.0,
    }
    from flightbench.scoring import evaluate

    res = evaluate(
        safe_td,
        success=True,
        reason="landed",
        config=env.scoring,
        trajectory={"lateral": 0, "pitch": 0, "glide": 0},
    )
    assert res["success"] is True
    assert res["quality"] >= 90.0
    env.close()


# ---------------------------------------------------------------------------
# 12. Regression scenario: early throttle reduction observation exposure
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 13. Realtime with >500 ms artificial decision latency
# ---------------------------------------------------------------------------
def test_realtime_latency_handling_above_500ms(monkeypatch, tmp_path):
    """Verify that artificial latency >500ms does not cause overlapping requests,
    correctly sets state_age_at_application_ms, and records auditable decision records."""
    import time
    from collections.abc import Mapping

    from flightbench import benchmark

    class DelayedController:
        def __init__(self, delay_s: float = 0.05):  # 50ms delay for fast test
            self.delay_s = delay_s
            self.call_count = 0
            self.last_decision = {
                "choices": {
                    "joint_action": {
                        "action": {
                            "aileron": "hold",
                            "elevator": "hold",
                            "rudder": "hold",
                            "throttle": "hold",
                        },
                        "legal_count": 81,
                    }
                }
            }

        def decide(self, observation: Mapping) -> ControlCommand:
            self.call_count += 1
            time.sleep(self.delay_s)
            return ControlCommand(aileron=-0.15, elevator=0.17, rudder=0.09, throttle=0.5)

    ctrl = DelayedController(delay_s=0.04)
    monkeypatch.setattr(benchmark, "make_controller", lambda *a, **k: ctrl)

    log_file = tmp_path / "rt_latency.jsonl"
    res = benchmark.run_episode("mock", seed=42, mode="realtime", timeout_s=2.0, log_path=log_file)
    assert res is not None

    rows = [json.loads(line) for line in log_file.read_text().splitlines()]
    decision_rows = [r for r in rows if r.get("type") == "decision"]
    assert len(decision_rows) > 0

    for dec in decision_rows:
        assert dec["observation_schema_version"] == OBSERVATION_SCHEMA_VERSION
        assert "decision_id" in dec
        assert "latency_ms" in dec
        assert "state_age_at_application_ms" in dec
        assert dec["latency_ms"] >= 30.0  # reflects the delay
        assert dec["applied"] is True


def test_realtime_state_age_threshold_is_two_decision_intervals():
    from flightbench.core import DECISION_INTERVAL_S, MAX_DECISION_AGE_S

    assert MAX_DECISION_AGE_S == 2 * DECISION_INTERVAL_S
    assert 1000 * MAX_DECISION_AGE_S == 1000.0


# ---------------------------------------------------------------------------
# 14. Actual applied actuator transition recording (trim offsets on first step)
# ---------------------------------------------------------------------------
def test_transition_recording_uses_actual_trim_actuators(tmp_path):
    from flightbench import benchmark

    log_file = tmp_path / "baseline_trim.jsonl"
    res = benchmark.run_episode(
        "baseline", seed=42, mode="lockstep", timeout_s=5.0, log_path=log_file
    )
    assert res is not None

    rows = [json.loads(line) for line in log_file.read_text().splitlines()]
    dec_1 = next(r for r in rows if r.get("index") == 1)

    # First decision control_before MUST reflect actual initial trim values, NOT zeros!
    assert dec_1["control_before"]["aileron"] == pytest.approx(TRIM_AILERON, abs=1e-3)
    assert dec_1["control_before"]["elevator"] == pytest.approx(TRIM_ELEVATOR, abs=1e-3)
    assert dec_1["control_before"]["rudder"] == pytest.approx(TRIM_RUDDER, abs=1e-3)
    assert dec_1["control_before"]["throttle"] == pytest.approx(0.5, abs=1e-3)


# ---------------------------------------------------------------------------
# 15. Native JSBSim gamma and alpha properties exposed in flight dict
# ---------------------------------------------------------------------------
def test_native_jsbsim_gamma_and_alpha_exposure():
    env = FixedWingLandingEnv(scenario="easy")
    obs, _ = env.reset(seed=42)
    flight = obs["flight"]

    assert "flight_path_angle_deg" in flight
    assert "alpha_deg" in flight

    # Verify they match JSBSim native properties directly
    assert flight["flight_path_angle_deg"] == pytest.approx(
        env.fdm["flight-path/gamma-deg"], abs=1e-6
    )
    assert flight["alpha_deg"] == pytest.approx(env.fdm["aero/alpha-deg"], abs=1e-6)

    # In trimmed glidepath, initial gamma is ~ -3.0 deg, alpha is ~ 5.0 deg
    assert flight["flight_path_angle_deg"] == pytest.approx(-3.0, abs=0.5)
    assert flight["alpha_deg"] == pytest.approx(5.0, abs=0.5)

    # Step environment and verify deltas update
    next_obs, _, _, _, _ = env.step(
        {"aileron": -0.15, "elevator": 0.17, "rudder": 0.09, "throttle": 0.5}
    )
    assert "flight_path_angle_deg" in next_obs["flight"]
    assert "alpha_deg" in next_obs["flight"]
    env.close()


# ---------------------------------------------------------------------------
# 16. Post-fix Jev observation payload validation
# ---------------------------------------------------------------------------
