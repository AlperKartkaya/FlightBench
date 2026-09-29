"""Frozen first-main-gear touchdown metrics; success requires a safe rollout."""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ScoringConfig:
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


def evaluate(touchdown, success=False, reason="running", config=None):
    c = config or ScoringConfig()
    quality = 0.0
    safe = False
    components = {}
    if touchdown:
        t = touchdown
        x = t["along_track_m"]
        zone_distance = max(c.zone_start_m - x, 0, x - c.zone_end_m)
        values = [
            max(0, 1 - zone_distance / 300),
            max(0, 1 - abs(t["cross_track_m"]) / (c.runway_width_m / 2)),
            max(0, 1 - abs(t["sink_rate_mps"]) / c.max_sink_mps),
            max(0, 1 - abs(t["heading_error_deg"]) / c.max_heading_deg),
            max(0, 1 - abs(t["roll_deg"]) / c.max_bank_deg),
            max(0, 1 - abs(t["airspeed_mps"] - c.target_airspeed_mps) / 12),
        ]
        components = dict(
            zip(
                ("zone", "centerline", "sink", "heading", "bank", "airspeed"),
                [v * w for v, w in zip(values, c.weights)],
            )
        )
        quality = 100 * sum(components.values()) / sum(c.weights)
        safe = (
            0 <= x <= c.runway_length_m
            and abs(t["cross_track_m"]) <= c.runway_width_m / 2
            and abs(t["sink_rate_mps"]) <= c.max_sink_mps
            and abs(t["roll_deg"]) <= c.max_bank_deg
            and abs(t["heading_error_deg"]) <= c.max_heading_deg
            and c.min_airspeed_mps <= t["airspeed_mps"] <= c.max_airspeed_mps
        )
    success = bool(success and safe)
    score = max(c.success_floor, quality) if success else min(c.failure_cap, quality)
    return {
        "success": success,
        "quality": round(score, 3),
        "raw_quality": round(quality, 3),
        "reason": reason,
        "touchdown": touchdown,
        "touchdown_safe": safe,
        "components": components,
        "scoring": asdict(c),
    }
