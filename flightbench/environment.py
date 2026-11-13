"""Deterministic C172x landing environment. No kinematic motion shortcuts."""

import math
from typing import ClassVar

import gymnasium as gym
import jsbsim
import numpy as np
from gymnasium import spaces

from .core import (
    DECISION_HZ,
    PHYSICS_HZ,
    TRIM_AILERON,
    TRIM_ELEVATOR,
    TRIM_RUDDER,
    ControlCommand,
    decision_timing,
)
from .geometry import attitude_quaternion, wrap_degrees
from .scoring import ScoringConfig, evaluate, trajectory_error_rate

FT = 0.3048

SCENARIOS = {
    "easy": {
        "label": "Easy",
        "summary": "Calm air · aligned on 3° glideslope · 65 KIAS",
        "seeded": False,
        "wind_mode": "calm",
        "ranges": {
            "start_z_m": (0.0, 0.0),
            "heading_offset_deg": (0.0, 0.0),
            "altitude_offset_m": (0.0, 0.0),
            "airspeed_offset_kts": (0.0, 0.0),
            "crosswind_mps": (0.0, 0.0),
            "headwind_mps": (0.0, 0.0),
            "vertical_wind_mps": (0.0, 0.0),
        },
    },
    "medium": {
        "label": "Medium",
        "summary": "Steady wind · moderate initial offset (±35m, ±5°, ±8m AGL, ±4 kt)",
        "seeded": True,
        "wind_mode": "steady",
        "ranges": {
            "start_z_m": (-35.0, 35.0),
            "heading_offset_deg": (-5.0, 5.0),
            "altitude_offset_m": (-8.0, 8.0),
            "airspeed_offset_kts": (-4.0, 4.0),
            "crosswind_mps": (-5.0, 5.0),
            "headwind_mps": (-2.0, 6.0),
            "vertical_wind_mps": (0.0, 0.0),
        },
    },
    "hard": {
        "label": "Hard",
        "summary": "Time & altitude-varying wind shear/gusts · wide offset (±60m, ±10°, ±18m AGL, ±8 kt)",
        "seeded": True,
        "wind_mode": "dynamic",
        "ranges": {
            "start_z_m": (-60.0, 60.0),
            "heading_offset_deg": (-10.0, 10.0),
            "altitude_offset_m": (-18.0, 18.0),
            "airspeed_offset_kts": (-8.0, 8.0),
            "crosswind_mps": (-8.0, 8.0),
            "headwind_mps": (-4.0, 10.0),
            "vertical_wind_mps": (-1.0, 0.5),
        },
    },
}


def _splitmix32(seed: int):
    state = int(seed) & 0xFFFFFFFF

    def next_u01() -> float:
        nonlocal state
        state = (state + 0x9E3779B9) & 0xFFFFFFFF
        z = state
        z = ((z ^ (z >> 16)) * 0x85EBCA6B) & 0xFFFFFFFF
        z = ((z ^ (z >> 13)) * 0xC2B2AE35) & 0xFFFFFFFF
        z = (z ^ (z >> 16)) & 0xFFFFFFFF
        return z / 4294967296.0

    def uniform(low: float, high: float) -> float:
        return low + (high - low) * next_u01()

    return uniform


def _sample_scenario_params(scenario: str, seed: int) -> dict[str, float]:
    if scenario == "easy":
        return {
            "start_z_m": 0.0,
            "heading_offset_deg": 0.0,
            "altitude_offset_m": 0.0,
            "airspeed_offset_kts": 0.0,
            "base_crosswind_mps": 0.0,
            "base_headwind_mps": 0.0,
            "base_vertical_wind_mps": 0.0,
        }
    u = _splitmix32(seed)
    ranges = SCENARIOS[scenario]["ranges"]
    params = {
        "start_z_m": u(*ranges["start_z_m"]),
        "heading_offset_deg": u(*ranges["heading_offset_deg"]),
        "altitude_offset_m": u(*ranges["altitude_offset_m"]),
        "airspeed_offset_kts": u(*ranges["airspeed_offset_kts"]),
        "base_crosswind_mps": u(*ranges["crosswind_mps"]),
        "base_headwind_mps": u(*ranges["headwind_mps"]),
        "base_vertical_wind_mps": u(*ranges["vertical_wind_mps"]),
    }
    if scenario == "hard":
        params.update(
            {
                "gust_amp_x_mps": u(0.8, 2.6),
                "gust_amp_h_mps": u(0.8, 2.4),
                "gust_amp_v_mps": u(0.15, 0.55),
                "omega1": 2.0 * math.pi / u(14.0, 24.0),
                "omega2": 2.0 * math.pi / u(6.0, 11.0),
                "phase_x1": u(0.0, 2.0 * math.pi),
                "phase_x2": u(0.0, 2.0 * math.pi),
                "phase_h1": u(0.0, 2.0 * math.pi),
                "phase_h2": u(0.0, 2.0 * math.pi),
                "phase_v": u(0.0, 2.0 * math.pi),
                "veer_deg": u(-18.0, 18.0),
            }
        )
    return params


def _wind_components(
    scenario: str, params: dict[str, float], time_s: float, altitude_agl_m: float
) -> tuple[float, float, float]:
    if scenario == "easy":
        return 0.0, 0.0, 0.0
    if scenario == "medium":
        return (
            params["base_headwind_mps"],
            params["base_crosswind_mps"],
            0.0,
        )
    alt = max(0.0, altitude_agl_m)
    shear = 0.65 + 0.35 * min(1.5, (alt / 80.0) ** 0.25)
    veer_rad = math.radians(params["veer_deg"] * min(1.0, alt / 90.0))
    hw0 = params["base_headwind_mps"] * shear
    xw0 = params["base_crosswind_mps"] * shear
    cos_v, sin_v = math.cos(veer_rad), math.sin(veer_rad)
    hw_steady = hw0 * cos_v - xw0 * sin_v
    xw_steady = hw0 * sin_v + xw0 * cos_v
    o1, o2 = params["omega1"], params["omega2"]
    gust_x = params["gust_amp_x_mps"] * (
        0.65 * math.sin(o1 * time_s + params["phase_x1"])
        + 0.35 * math.sin(o2 * time_s + params["phase_x2"])
    )
    gust_h = params["gust_amp_h_mps"] * (
        0.65 * math.sin(o1 * time_s + params["phase_h1"])
        + 0.35 * math.sin(o2 * time_s + params["phase_h2"])
    )
    vw_scale = min(1.0, alt / 25.0)
    vw = (
        params["base_vertical_wind_mps"]
        + params["gust_amp_v_mps"] * math.sin(o2 * time_s + params["phase_v"])
    ) * vw_scale
    return hw_steady + gust_h, xw_steady + gust_x, vw


def _wind_polar(headwind_mps: float, crosswind_mps: float) -> tuple[float, float]:
    speed = math.hypot(headwind_mps, crosswind_mps)
    if speed < 1e-6:
        return 0.0, 0.0
    direction = math.degrees(math.atan2(headwind_mps, crosswind_mps)) % 360.0
    return round(speed, 4), round(direction, 2)


def observation_space(value):
    if isinstance(value, dict):
        return spaces.Dict({k: observation_space(v) for k, v in value.items()})
    if isinstance(value, bool):
        return spaces.Discrete(2)
    if isinstance(value, str):
        import string

        return spaces.Text(max_length=64, charset=frozenset(string.printable))
    return spaces.Box(-np.inf, np.inf, shape=(), dtype=np.float64)


class FixedWingLandingEnv(gym.Env):
    metadata: ClassVar[dict] = {"render_modes": []}

    def __init__(self, scenario="easy", max_time_s=120, scoring=None, decision_hz=DECISION_HZ):
        if scenario not in SCENARIOS:
            raise ValueError("scenario must be easy, medium, or hard")
        if not math.isfinite(max_time_s) or max_time_s <= 0:
            raise ValueError("max_time_s must be positive and finite")
        self.scenario, self.max_time_s = scenario, max_time_s
        self.decision_ticks, self.decision_interval_s = decision_timing(decision_hz)
        self.scoring = scoring or ScoringConfig()
        self.action_space = spaces.Box(
            np.array([-1, -1, -1, 0], dtype=np.float64), np.ones(4), dtype=np.float64
        )
        self.fdm = None
        self._seed = 0
        obs, _ = self.reset(seed=0)
        self.observation_space = observation_space(obs)

    def _apply_wind(self, time_s: float, altitude_agl_m: float) -> None:
        self.headwind, self.crosswind, self.vertical_wind = _wind_components(
            self.scenario, self._scenario_params, time_s, altitude_agl_m
        )
        if self.scenario != "easy":
            self.fdm["atmosphere/wind-north-fps"] = -self.crosswind / FT
            self.fdm["atmosphere/wind-east-fps"] = -self.headwind / FT
            self.fdm["atmosphere/wind-down-fps"] = -self.vertical_wind / FT

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        if seed is not None:
            self._seed = int(seed) & 0xFFFFFFFF
        else:
            self._seed = (getattr(self, "_seed", 0) + 1) & 0xFFFFFFFF
        f = self.fdm = jsbsim.FGFDMExec(None)
        f.set_debug_level(0)
        f.disable_output()
        if not f.load_model("c172x"):
            raise RuntimeError("JSBSim c172x model unavailable")
        f.set_dt(1 / PHYSICS_HZ)
        self._scenario_params = _sample_scenario_params(self.scenario, self._seed)
        self.start_x = -1500.0
        self.start_z = self._scenario_params["start_z_m"]
        heading = 90 + self._scenario_params["heading_offset_deg"]
        altitude = 1500 * math.tan(math.radians(3)) + 15 + self._scenario_params["altitude_offset_m"]
        airspeed_kts = 65 + self._scenario_params["airspeed_offset_kts"]
        for key, value in {
            "ic/lat-geod-deg": 37,
            "ic/long-gc-deg": -122,
            "ic/terrain-elevation-ft": 0,
            "ic/h-agl-ft": altitude / FT,
            "ic/vc-kts": airspeed_kts,
            "ic/psi-true-deg": heading,
            "ic/gamma-deg": -3,
            "ic/alpha-deg": 5,
            "fcs/flap-cmd-norm": 2 / 3,
            "fcs/flaps-control": 20,
            "fcs/flap-pos-deg": 20,
            "fcs/mixture-cmd-norm": 1,
            "fcs/throttle-cmd-norm": 0.5,
            "atmosphere/wind-north-fps": 0.0,
        }.items():
            f[key] = value
        if not f.run_ic():
            raise RuntimeError("JSBSim initial conditions failed")
        f["propulsion/set-running"] = -1
        self._apply_wind(0.0, altitude)
        # Apply trim offsets so the aircraft doesn't spiral from prop torque.
        f["fcs/elevator-cmd-norm"] = TRIM_ELEVATOR
        f["fcs/aileron-cmd-norm"] = TRIM_AILERON
        f["fcs/rudder-cmd-norm"] = TRIM_RUDDER
        self.action = ControlCommand(
            aileron=TRIM_AILERON,
            elevator=TRIM_ELEVATOR,
            rudder=TRIM_RUDDER,
            throttle=0.5,
        )
        self.ticks = 0
        self.done = False
        self.truncated = False
        self.reason = "running"
        self.touchdown = None
        self.touchdown_time = None
        self._trajectory_error = {"lateral": 0.0, "pitch": 0.0, "glide": 0.0}
        self.success = False
        self._last_obs = self.observe()
        return self._last_obs, self.info()

    def observe(self):
        f = self.fdm
        # JSBSim local displacements are signed east/north distances from IC (NEU frame).
        x = self.start_x + f["position/from-start-neu-e-ft"] * FT
        z = self.start_z - f["position/from-start-neu-n-ft"] * FT
        h = f["position/h-agl-ft"] * FT
        heading = f["attitude/psi-deg"]
        dist_to_threshold = max(0, -x)
        groundspeed = math.hypot(f["velocities/v-north-fps"], f["velocities/v-east-fps"]) * FT
        on_ground = bool(f["gear/wow"])

        if on_ground and groundspeed < 3.0:
            phase = "STOPPED"
        elif on_ground:
            if self.touchdown is None:
                phase = "MAIN-GEAR TOUCHDOWN"
            else:
                phase = "ROLLOUT"
        else:
            phase = "AIRBORNE / APPROACH"

        # X-TRACK deadband: -5 to +5 is 0.0; > 5 is z - 5; < -5 is z + 5
        xtrack_deadband_m = 5.0
        if z > xtrack_deadband_m:
            xtrack_error = round(z - xtrack_deadband_m, 4)
        elif z < -xtrack_deadband_m:
            xtrack_error = round(z + xtrack_deadband_m, 4)
        else:
            xtrack_error = 0.0

        wind_speed, wind_dir = _wind_polar(self.headwind, self.crosswind)

        return {
            "time_s": self.ticks / PHYSICS_HZ,
            "decision_dt_s": self.decision_interval_s,
            "phase": phase,
            "runway": {
                "distance_to_threshold_m": dist_to_threshold,
                "along_track_m": x,
                "cross_track_error_m": xtrack_error,
                "centerline_offset_m": round(z, 4),
                "runway_width_m": self.scoring.runway_width_m,
                "altitude_agl_m": h,
                "glideslope_error_deg": math.degrees(math.atan2(h - 15, max(1, -x))) - 3,
                "heading_error_deg": wrap_degrees(heading - 90),
            },
            "flight": {
                "airspeed_mps": f["velocities/vc-fps"] * FT,
                "groundspeed_mps": groundspeed,
                "vertical_speed_mps": f["velocities/h-dot-fps"] * FT,
                "flight_path_angle_deg": f["flight-path/gamma-deg"],
                "angle_of_attack_deg": f["aero/alpha-deg"],
                "alpha_deg": f["aero/alpha-deg"],
                "roll_deg": f["attitude/phi-deg"],
                "pitch_deg": f["attitude/theta-deg"],
                "heading_deg": heading,
                "p_rad_s": f["velocities/p-rad_sec"],
                "q_rad_s": f["velocities/q-rad_sec"],
                "r_rad_s": f["velocities/r-rad_sec"],
                "beta_deg": f["aero/beta-deg"],
            },
            "environment": {
                "headwind_mps": round(self.headwind, 4),
                "crosswind_mps": round(self.crosswind, 4),
                "vertical_wind_mps": round(self.vertical_wind, 4),
                "wind_speed_mps": wind_speed,
                "wind_dir_deg": wind_dir,
            },
            "controls": {
                "aileron": f["fcs/aileron-cmd-norm"],
                "elevator": f["fcs/elevator-cmd-norm"],
                "rudder": f["fcs/rudder-cmd-norm"],
                "throttle": f["fcs/throttle-cmd-norm"],
                "flaps_deg": f["fcs/flap-pos-deg"],
            },
            "status": {
                "on_ground": bool(f["gear/wow"]),
                "main_gear_on_ground": bool(f["gear/unit[1]/WOW"] or f["gear/unit[2]/WOW"]),
            },
            "ground_contact": {
                "any_gear_wow": bool(f["gear/wow"]),
                "nose_gear_wow": bool(f["gear/unit[0]/WOW"]),
                "left_main_gear_wow": bool(f["gear/unit[1]/WOW"]),
                "right_main_gear_wow": bool(f["gear/unit[2]/WOW"]),
            },
        }

    def step(self, action):
        return self.advance(action, self.decision_ticks)

    def advance(self, action, ticks=1):
        if self.done:
            raise RuntimeError("Episode ended; reset before stepping")
        if not isinstance(ticks, int) or ticks < 1:
            raise ValueError("ticks must be a positive integer")
        if not isinstance(action, ControlCommand):
            if not isinstance(action, dict):
                a = np.asarray(action)
                if a.shape != (4,):
                    raise ValueError("Expected exactly four controls")
                action = dict(zip(("aileron", "elevator", "rudder", "throttle"), a.tolist()))
            action = ControlCommand.model_validate(action)
        self.action = action
        for key, value in action.model_dump().items():
            self.fdm[f"fcs/{key}-cmd-norm"] = value
        for _ in range(ticks):
            previous = self._last_obs
            if self.scenario == "hard":
                self._apply_wind(
                    (self.ticks + 1) / PHYSICS_HZ,
                    previous["runway"]["altitude_agl_m"],
                )
            if self.touchdown is not None:
                # Environment-owned rollout: idle engine and symmetric braking.
                self.fdm["fcs/throttle-cmd-norm"] = 0
                self.fdm["fcs/left-brake-cmd-norm"] = 0.7
                self.fdm["fcs/right-brake-cmd-norm"] = 0.7
                self.action = action.model_copy(update={"throttle": 0.0})
            if not self.fdm.run():
                self.done, self.reason = True, "simulation_failure"
                break
            self.ticks += 1
            obs = self.observe()
            if not all(
                math.isfinite(v) for group in ("runway", "flight") for v in obs[group].values()
            ):
                self.done, self.reason = True, "nonfinite_state"
                break
            self._last_obs = obs
            r, flight = obs["runway"], obs["flight"]
            if self.touchdown is None and self.scoring.version == "v2":
                for name, rate in trajectory_error_rate(obs, self.scoring).items():
                    self._trajectory_error[name] += rate / PHYSICS_HZ
            lat_pos = r.get("centerline_offset_m")
            if lat_pos is None or (
                lat_pos == 0.0
                and abs(r.get("cross_track_error_m", 0.0)) > self.scoring.runway_width_m / 2
            ):
                lat_pos = r.get("cross_track_error_m", 0.0)
            if self.touchdown is None and obs["status"]["main_gear_on_ground"]:
                self.touchdown_time = obs["time_s"]
                self.touchdown = {
                    "along_track_m": r["along_track_m"],
                    "cross_track_m": lat_pos,
                    "sink_rate_mps": previous["flight"]["vertical_speed_mps"],
                    "airspeed_mps": previous["flight"]["airspeed_mps"],
                    "heading_error_deg": r["heading_error_deg"],
                    "roll_deg": flight["roll_deg"],
                    "pitch_deg": flight["pitch_deg"],
                }
                if not self.info()["result"]["touchdown_safe"]:
                    self.done, self.reason = True, "unsafe_touchdown"
            if (
                abs(flight["roll_deg"]) > 70
                or abs(flight["pitch_deg"]) > 45
                or r["altitude_agl_m"] < 0
            ):
                self.done, self.reason = True, "crash"
            if self.touchdown is not None:
                if (
                    not (0 <= r["along_track_m"] <= self.scoring.runway_length_m)
                    or abs(lat_pos) > self.scoring.runway_width_m / 2
                ):
                    self.done, self.reason = True, "runway_excursion"
                elif obs["status"]["on_ground"] and flight["groundspeed_mps"] < 3 and not self.done:
                    self.done, self.success, self.reason = True, True, "landed"
            elif obs["status"]["on_ground"]:
                self.done, self.reason = True, "nose_first_contact"
            if abs(lat_pos) > 500 or r["along_track_m"] > self.scoring.runway_length_m + 200:
                self.done, self.reason = True, "out_of_bounds"
            if self.ticks / PHYSICS_HZ >= self.max_time_s and not self.done:
                self.done, self.truncated, self.reason = True, True, "time_limit"
            if self.done:
                break
        info = self.info()
        return (
            self._last_obs,
            info["result"]["quality"] / 100 if self.done else 0.0,
            self.done and not self.truncated,
            self.truncated,
            info,
        )

    def info(self):
        return {
            "result": evaluate(
                self.touchdown,
                self.success,
                self.reason,
                self.scoring,
                self._trajectory_error,
            ),
            "scenario": self.scenario,
            "physics_hz": PHYSICS_HZ,
            "decision_ticks": self.decision_ticks,
            "decision_hz": PHYSICS_HZ / self.decision_ticks,
            "decision_interval_s": self.decision_interval_s,
        }

    def snapshot(self):
        o = self._last_obs
        r, f = o["runway"], o["flight"]
        result = self.info()["result"]
        return {
            "type": "state",
            "observation": o,
            "position": [
                r["along_track_m"],
                r["altitude_agl_m"],
                r.get("centerline_offset_m", r["cross_track_error_m"]),
            ],
            "quaternion": attitude_quaternion(f["roll_deg"], f["pitch_deg"], f["heading_deg"]),
            "score": result["quality"],
            "status": self.reason,
            "result": result,
        }

    def close(self):
        self.fdm = None
