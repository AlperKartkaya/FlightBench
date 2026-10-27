import math

import numpy as np
import pytest
from gymnasium.utils.env_checker import check_env

from flightbench.environment import FixedWingLandingEnv
from flightbench.geometry import attitude_quaternion
from flightbench.scoring import ScoringConfig, evaluate, trajectory_error_rate


def rotate(q, v):
    q = np.array(q)
    return v + 2 * np.cross(q[:3], np.cross(q[:3], v) + q[3] * np.array(v))


def test_orientation():
    assert np.allclose(attitude_quaternion(0, 0, 90), [0, 0, 0, 1])
    assert rotate(attitude_quaternion(0, 20, 90), [1, 0, 0])[1] > 0
    assert rotate(attitude_quaternion(20, 0, 90), [0, 0, 1])[1] < 0
    assert rotate(attitude_quaternion(0, 0, 110), [1, 0, 0])[2] > 0
    for heading in (0, 90, 180, 270, 360):
        assert math.isclose(np.linalg.norm(attitude_quaternion(0, 0, heading)), 1)


def test_determinism_and_gym():
    env = FixedWingLandingEnv("medium")
    check_env(env, skip_render_check=True)
    a = [0, 0, 0, 0.5]
    initial, _ = env.reset(seed=42)
    first = env.step(a)
    assert first[0]["time_s"] == 0.50
    assert first[0]["controls"]["flaps_deg"] == pytest.approx(20)
    assert initial["flight"]["pitch_deg"] == pytest.approx(2, abs=0.1)
    env.reset(seed=42)
    assert first == env.step(a)
    other, _ = env.reset(seed=43)
    assert initial != other


def test_actual_jsbsim_control_signs():
    env = FixedWingLandingEnv()
    responses = {}
    for axis in ("neutral", "aileron", "elevator", "rudder"):
        env.reset(seed=1)
        action = {"aileron": 0, "elevator": 0, "rudder": 0, "throttle": 0.5}
        if axis != "neutral":
            action[axis] = 0.3
        responses[axis] = env.step(action)[0]["flight"]
    neutral = responses["neutral"]
    assert responses["aileron"]["p_rad_s"] > neutral["p_rad_s"]
    assert responses["elevator"]["q_rad_s"] < neutral["q_rad_s"]
    assert responses["rudder"]["r_rad_s"] < neutral["r_rad_s"]
    assert responses["rudder"]["beta_deg"] > neutral["beta_deg"]


def test_control_commands_are_reported_from_jsbsim():
    env = FixedWingLandingEnv("easy", decision_hz=2)
    env.reset(seed=42)
    trim = env.step({"aileron": -0.15, "elevator": 0.17, "rudder": 0.09, "throttle": 0.5})[0]
    env.reset(seed=42)
    deflected = env.step({"aileron": 0.5, "elevator": 0.17, "rudder": 0.09, "throttle": 0.5})[0]
    assert trim["controls"]["aileron"] == pytest.approx(-0.15)
    assert deflected["controls"]["aileron"] == pytest.approx(0.5)
    assert abs(deflected["flight"]["roll_deg"]) > abs(trim["flight"]["roll_deg"])


def test_action_and_timeout():
    env = FixedWingLandingEnv(max_time_s=0.1)
    with pytest.raises(ValueError):
        env.step([0, 0, 0, 2])
    with pytest.raises(ValueError):
        env.step([0, 0, 0, float("nan")])
    _, _, terminated, truncated, info = env.step([0, 0, 0, 0.5])
    assert not terminated and truncated and info["result"]["reason"] == "time_limit"
    with pytest.raises(RuntimeError):
        env.step([0, 0, 0, 0.5])


def test_score_tiers():
    touchdown = {
        "along_track_m": 200,
        "cross_track_m": 0,
        "sink_rate_mps": -0.5,
        "airspeed_mps": 28,
        "heading_error_deg": 0,
        "roll_deg": 0,
        "pitch_deg": 5,
    }
    trajectory = {"lateral": 0, "pitch": 0, "glide": 0}
    assert evaluate(touchdown, False, trajectory=trajectory)["quality"] == 0
    assert evaluate(touchdown, True, trajectory=trajectory)["success"]
    assert not evaluate({**touchdown, "sink_rate_mps": -8}, True, trajectory=trajectory)["success"]
    assert evaluate(None, trajectory=trajectory)["quality"] == 0


def test_v1_score_is_preserved_and_explicit():
    touchdown = {
        "along_track_m": 200,
        "cross_track_m": 0,
        "sink_rate_mps": -0.5,
        "airspeed_mps": 28,
        "heading_error_deg": 0,
        "roll_deg": 0,
        "pitch_deg": 5,
    }
    result = evaluate(touchdown, True, config=ScoringConfig(version="v1"))
    assert result["quality"] == 95.833
    assert result["scoring_version"] == "v1"
    assert result["scoring"]["version"] == "v1"


def test_v2_rewards_stable_approach_and_gates_failures():
    touchdown = {
        "along_track_m": 200,
        "cross_track_m": 0,
        "sink_rate_mps": -1,
        "airspeed_mps": 28,
        "heading_error_deg": 0,
        "roll_deg": 0,
        "pitch_deg": 5,
    }
    stable = evaluate(
        touchdown,
        True,
        trajectory={"lateral": 0, "pitch": 0, "glide": 0},
    )
    unstable = evaluate(
        touchdown,
        True,
        trajectory={"lateral": 60, "pitch": 60, "glide": 60},
    )
    failed = evaluate(
        touchdown,
        False,
        trajectory={"lateral": 0, "pitch": 0, "glide": 0},
    )
    assert stable["quality"] > unstable["quality"]
    assert failed["quality"] == 0
    assert stable["scoring_version"] == "v2"
    assert stable["scoring"]["version"] == "v2"


def test_v2_rejects_invalid_constants_and_trajectory():
    with pytest.raises(ValueError, match="positive and finite"):
        ScoringConfig(reference_duration_s=0)
    with pytest.raises(ValueError, match="finite, nonnegative, and complete"):
        evaluate(None, trajectory={"lateral": -1, "pitch": 0, "glide": 0})
    with pytest.raises(ValueError, match="finite, nonnegative, and complete"):
        evaluate(None, trajectory={"lateral": 0, "pitch": float("nan"), "glide": 0})


@pytest.mark.parametrize(
    "trajectory",
    [
        None,
        {},
        {"lateral": 0, "pitch": 0},
        {"lateral": 0, "pitch": 0, "glide": 0, "extra": 0},
        {"lateral": True, "pitch": 0, "glide": 0},
        {"lateral": "0", "pitch": 0, "glide": 0},
    ],
)
def test_v2_requires_complete_numeric_trajectory_evidence(trajectory):
    with pytest.raises(ValueError, match="finite, nonnegative, and complete"):
        evaluate(None, trajectory=trajectory)


def test_v2_sample_uses_centerline_and_allows_low_altitude_flare():
    observation = {
        "runway": {
            "centerline_offset_m": 4,
            "altitude_agl_m": 5,
            "distance_to_threshold_m": 0,
        },
        "flight": {"pitch_deg": 8, "q_rad_s": 0},
    }
    flare = trajectory_error_rate(observation, ScoringConfig())
    observation["runway"]["altitude_agl_m"] = 20
    approach = trajectory_error_rate(observation, ScoringConfig())
    assert flare == {"lateral": pytest.approx(0.16), "pitch": 0, "glide": 0}
    assert approach["pitch"] > flare["pitch"]
    assert approach["glide"] > 0


def test_v2_trajectory_uses_physics_time_not_advance_size():
    action = [0, 0, 0, 0.5]
    batched = FixedWingLandingEnv()
    stepped = FixedWingLandingEnv()
    batched.reset(seed=42)
    stepped.reset(seed=42)
    batched.advance(action, ticks=30)
    for _ in range(30):
        stepped.advance(action, ticks=1)
    assert batched._trajectory_error == pytest.approx(stepped._trajectory_error)


def test_first_touchdown_frozen_and_rollout(monkeypatch):
    from copy import deepcopy

    env = FixedWingLandingEnv()
    observation = deepcopy(env._last_obs)
    observation["runway"].update(
        along_track_m=200, cross_track_error_m=0, altitude_agl_m=1.5, heading_error_deg=0
    )
    observation["flight"].update(
        roll_deg=0, pitch_deg=5, airspeed_mps=28, vertical_speed_mps=-1, groundspeed_mps=28
    )
    env._last_obs = deepcopy(observation)
    observation["status"].update(on_ground=True, main_gear_on_ground=True)
    monkeypatch.setattr(env, "observe", lambda: deepcopy(observation))
    env.advance([0, 0, 0, 0.5])
    frozen = deepcopy(env.touchdown)
    frozen_trajectory = deepcopy(env._trajectory_error)
    observation["runway"]["along_track_m"] = 250
    observation["flight"]["groundspeed_mps"] = 2
    _, _, terminated, _, info = env.advance([0, 0, 0, 0.5])
    assert terminated and info["result"]["success"]
    assert env.touchdown == frozen
    assert env._trajectory_error == frozen_trajectory
    assert env.action.throttle == 0


def test_excursion_after_safe_contact(monkeypatch):
    from copy import deepcopy

    env = FixedWingLandingEnv()
    observation = deepcopy(env._last_obs)
    env.touchdown = {
        "along_track_m": 200,
        "cross_track_m": 0,
        "sink_rate_mps": -1,
        "airspeed_mps": 28,
        "heading_error_deg": 0,
        "roll_deg": 0,
        "pitch_deg": 5,
    }
    observation["runway"].update(along_track_m=250, cross_track_error_m=16)
    monkeypatch.setattr(env, "observe", lambda: observation)
    *_, info = env.advance([0, 0, 0, 0.5])
    assert env.done and info["result"]["reason"] == "runway_excursion"
    assert not info["result"]["success"]
