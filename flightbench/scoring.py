"""Versioned landing scores; success requires a safe rollout."""

import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from numbers import Real


@dataclass(frozen=True)
class ScoringConfig:
    version: str = "v2"
    runway_length_m: float = 1000
    runway_width_m: float = 30
    zone_start_m: float = 50
    zone_end_m: float = 350
    max_sink_mps: float = 3
    max_bank_deg: float = 10
    max_heading_deg: float = 15
    min_airspeed_mps: float = 18
    max_airspeed_mps: float = 40
    target_airspeed_mps: float = 28
    failure_cap: float = 49
    success_floor: float = 50
    weights: tuple = (25, 20, 25, 10, 10, 10)
    reference_duration_s: float = 60
    lateral_normalization_m: float = 10
    approach_pitch_limit_deg: float = 6
    flare_pitch_limit_deg: float = 10
    pitch_excess_normalization_deg: float = 10
    pitch_rate_normalization_deg_s: float = 10
    flare_altitude_m: float = 6
    glide_normalization_m: float = 15
    touchdown_sink_normalization_mps: float = 3
    touchdown_lateral_normalization_m: float = 15
    touchdown_target_m: float = 200
    touchdown_longitudinal_normalization_m: float = 200

    def __post_init__(self):
        if self.version not in ("v1", "v2"):
            raise ValueError("scoring version must be v1 or v2")
        positive = (
            self.reference_duration_s,
            self.lateral_normalization_m,
            self.approach_pitch_limit_deg,
            self.flare_pitch_limit_deg,
            self.pitch_excess_normalization_deg,
            self.pitch_rate_normalization_deg_s,
            self.flare_altitude_m,
            self.glide_normalization_m,
            self.touchdown_sink_normalization_mps,
            self.touchdown_lateral_normalization_m,
            self.touchdown_target_m,
            self.touchdown_longitudinal_normalization_m,
        )
        if not all(math.isfinite(value) and value > 0 for value in positive):
            raise ValueError("V2 scoring constants must be positive and finite")


def trajectory_error_rate(observation, config):
    """Return V2 dimensionless error rates for one physics sample."""
    runway, flight = observation["runway"], observation["flight"]
    altitude = runway["altitude_agl_m"]
    pitch_limit = (
        config.flare_pitch_limit_deg
        if altitude <= config.flare_altitude_m
        else config.approach_pitch_limit_deg
    )
    pitch_excess = max(0.0, abs(flight["pitch_deg"]) - pitch_limit)
    pitch_rate = math.degrees(flight["q_rad_s"])
    glide_error = 0.0
    if altitude > config.flare_altitude_m:
        target_altitude = 15 + runway["distance_to_threshold_m"] * math.tan(math.radians(3))
        glide_error = (altitude - target_altitude) / config.glide_normalization_m
    return {
        "lateral": (runway["centerline_offset_m"] / config.lateral_normalization_m) ** 2,
        "pitch": 0.7 * (pitch_excess / config.pitch_excess_normalization_deg) ** 2
        + 0.3 * (pitch_rate / config.pitch_rate_normalization_deg_s) ** 2,
        "glide": glide_error**2,
    }


def _touchdown_safe(touchdown, config):
    if not touchdown:
        return False
    return (
        0 <= touchdown["along_track_m"] <= config.runway_length_m
        and abs(touchdown["cross_track_m"]) <= config.runway_width_m / 2
        and abs(touchdown["sink_rate_mps"]) <= config.max_sink_mps
        and abs(touchdown["roll_deg"]) <= config.max_bank_deg
        and abs(touchdown["heading_error_deg"]) <= config.max_heading_deg
        and config.min_airspeed_mps <= touchdown["airspeed_mps"] <= config.max_airspeed_mps
    )


def _evaluate_v1(touchdown, success, config):
    quality = 0.0
    components = {}
    if touchdown:
        x = touchdown["along_track_m"]
        zone_distance = max(config.zone_start_m - x, 0, x - config.zone_end_m)
        values = [
            max(0, 1 - zone_distance / 300),
            max(0, 1 - abs(touchdown["cross_track_m"]) / (config.runway_width_m / 2)),
            max(0, 1 - abs(touchdown["sink_rate_mps"]) / config.max_sink_mps),
            max(0, 1 - abs(touchdown["heading_error_deg"]) / config.max_heading_deg),
            max(0, 1 - abs(touchdown["roll_deg"]) / config.max_bank_deg),
            max(
                0,
                1 - abs(touchdown["airspeed_mps"] - config.target_airspeed_mps) / 12,
            ),
        ]
        components = dict(
            zip(
                ("zone", "centerline", "sink", "heading", "bank", "airspeed"),
                [value * weight for value, weight in zip(values, config.weights)],
            )
        )
        quality = 100 * sum(components.values()) / sum(config.weights)
    score = max(config.success_floor, quality) if success else min(config.failure_cap, quality)
    return score, quality, components


def _evaluate_v2(touchdown, success, config, trajectory):
    if (
        not isinstance(trajectory, Mapping)
        or set(trajectory) != {"lateral", "pitch", "glide"}
        or not all(
            isinstance(value, Real)
            and not isinstance(value, bool)
            and math.isfinite(value)
            and value >= 0
            for value in trajectory.values()
        )
    ):
        raise ValueError("trajectory errors must be finite, nonnegative, and complete")
    lateral = trajectory["lateral"] / config.reference_duration_s
    pitch = trajectory["pitch"] / config.reference_duration_s
    glide = trajectory["glide"] / config.reference_duration_s
    touchdown_error = 0.0
    if touchdown:
        touchdown_error = (
            0.50 * (abs(touchdown["sink_rate_mps"]) / config.touchdown_sink_normalization_mps) ** 2
            + 0.25
            * (abs(touchdown["cross_track_m"]) / config.touchdown_lateral_normalization_m) ** 2
            + 0.25
            * (
                abs(touchdown["along_track_m"] - config.touchdown_target_m)
                / config.touchdown_longitudinal_normalization_m
            )
            ** 2
        )
    total = 0.30 * lateral + 0.25 * pitch + 0.20 * glide + 0.25 * touchdown_error
    components = {
        "lateral_error": lateral,
        "pitch_error": pitch,
        "glide_error": glide,
        "touchdown_error": touchdown_error,
        "total_error": total,
    }
    raw_quality = 100 * math.exp(-total)
    return (raw_quality if success else 0.0), raw_quality, components


def evaluate(touchdown, success=False, reason="running", config=None, trajectory=None):
    config = config or ScoringConfig()
    safe = _touchdown_safe(touchdown, config)
    success = bool(success and safe)
    if config.version == "v1":
        score, raw_quality, components = _evaluate_v1(touchdown, success, config)
    else:
        score, raw_quality, components = _evaluate_v2(touchdown, success, config, trajectory)
    return {
        "success": success,
        "quality": round(score, 3),
        "raw_quality": round(raw_quality, 3),
        "reason": reason,
        "touchdown": touchdown,
        "touchdown_safe": safe,
        "components": components,
        "scoring_version": config.version,
        "scoring": asdict(config),
        "trajectory_error_integrals": dict(trajectory or {}),
    }
