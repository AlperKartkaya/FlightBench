"""Deterministic temporal features for controller observations."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field

_FIELDS = (
    ("flight", "airspeed_mps", "airspeed_rate_mps2"),
    ("flight", "vertical_speed_mps", "vertical_speed_rate_mps2"),
    ("runway", "cross_track_error_m", "cross_track_rate_mps"),
    ("runway", "glideslope_error_deg", "glideslope_error_rate_deg_s"),
    ("runway", "heading_error_deg", "heading_error_rate_deg_s"),
    ("flight", "flight_path_angle_deg", "flight_path_angle_rate_deg_s"),
    ("flight", "angle_of_attack_deg", "angle_of_attack_rate_deg_s"),
)


from .geometry import angle_delta


@dataclass
class TelemetryHistory:
    samples: deque[tuple[float, Mapping]] = field(default_factory=lambda: deque(maxlen=240))

    def add(self, observation: Mapping) -> None:
        self.samples.append((float(observation.get("time_s", 0.0)), observation))

    def features(self, observation: Mapping) -> dict:
        now = float(observation.get("time_s", 0.0))
        result: dict[str, dict[str, float]] = {"rates": {}, "recent_change": {}}
        for group, value_name, rate_name in _FIELDS:
            if group not in observation:
                continue
            actual_key = value_name
            if actual_key not in observation[group]:
                if actual_key == "angle_of_attack_deg" and "alpha_deg" in observation[group]:
                    actual_key = "alpha_deg"
                else:
                    continue
            eval_key = actual_key
            if value_name == "cross_track_error_m" and "centerline_offset_m" in observation[group]:
                eval_key = "centerline_offset_m"
            current = float(observation[group][eval_key])
            for window in (0.5, 1.0):
                reference = self._before(now - window)
                if reference is None:
                    reference = self.samples[0] if self.samples else (now, observation)
                ref_obs = reference[1]
                if group not in ref_obs or eval_key not in ref_obs[group]:
                    continue
                then = float(ref_obs[group][eval_key])
                dt = max(now - reference[0], 1e-6)
                delta = current - then
                if value_name == "heading_error_deg":
                    delta = angle_delta(current, then)
                if window == 0.5:
                    result["rates"][rate_name] = round(delta / dt, 4)
                result["recent_change"][
                    f"{value_name}_delta_{'short' if window == 0.5 else 'medium'}"
                ] = round(delta, 4)
        result["rates"]["distance_closure_rate_mps"] = self._rate(
            observation, "runway", "distance_to_threshold_m", now, 0.5, negate=True
        )
        xtrack_accel_field = (
            "centerline_offset_m"
            if "centerline_offset_m" in observation.get("runway", {})
            else "cross_track_error_m"
        )
        xtrack_accel = self._acceleration(observation, "runway", xtrack_accel_field, now, 0.5)
        result["accelerations"] = {
            "cross_track_accel_mps2": xtrack_accel,
        }
        result["rates"]["cross_track_accel_mps2"] = xtrack_accel
        return result

    def _before(self, timestamp: float) -> tuple[float, Mapping] | None:
        candidates = [sample for sample in self.samples if sample[0] <= timestamp]
        return candidates[-1] if candidates else None

    def _rate(
        self,
        observation: Mapping,
        group: str,
        field: str,
        now: float,
        window: float,
        negate: bool = False,
    ) -> float:
        if group not in observation or field not in observation[group]:
            return 0.0
        reference = self._before(now - window)
        if reference is None:
            return 0.0
        ref_obs = reference[1]
        if group not in ref_obs or field not in ref_obs[group]:
            return 0.0
        delta = float(observation[group][field]) - float(ref_obs[group][field])
        rate = delta / max(now - reference[0], 1e-6)
        return round(-rate if negate else rate, 4)

    def _acceleration(
        self,
        observation: Mapping,
        group: str,
        field: str,
        now: float,
        window: float = 0.5,
    ) -> float:
        if group not in observation or field not in observation[group]:
            return 0.0

        t_start = self.samples[0][0] if self.samples else now
        dt_available = max(now - t_start, 0.0)
        eff_window = min(window, max(0.08, dt_available / 2.0)) if dt_available > 0.04 else window

        ref1 = self._before(now - eff_window)
        if ref1 is None and len(self.samples) >= 2:
            ref1 = self.samples[0]
        if ref1 is None:
            return 0.0

        ref2 = self._before(ref1[0] - eff_window)
        if ref2 is None and len(self.samples) >= 3:
            ref2 = self.samples[0]
        if ref2 is None:
            return 0.0

        t0 = now
        t1, obs1 = ref1
        t2, obs2 = ref2

        if (
            group not in obs1
            or field not in obs1[group]
            or group not in obs2
            or field not in obs2[group]
        ):
            return 0.0

        dt01 = max(t0 - t1, 1e-6)
        dt12 = max(t1 - t2, 1e-6)
        if dt01 < 0.02 or dt12 < 0.02:
            return 0.0

        y0 = float(observation[group][field])
        y1 = float(obs1[group][field])
        y2 = float(obs2[group][field])

        v01 = (y0 - y1) / dt01
        v12 = (y1 - y2) / dt12
        dt_mid = 0.5 * (dt01 + dt12)
        accel = (v01 - v12) / dt_mid
        return round(accel, 4)
