"""Decision-tracking infrastructure for closed-loop Jev feedback.

Records applied control transitions, captures the aircraft state at application
time, and computes observed consequences so the next Jev decision receives
genuine closed-loop feedback about what actually happened.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

# Fields for which delta computation must use wrap-safe angular difference.
_WRAP_FIELDS = frozenset({"heading_deg", "heading_error_deg"})

# Full delta fields for observed_since_previous_action.
_DELTA_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("runway", "altitude_agl_m", "altitude_agl_delta_m"),
    ("flight", "airspeed_mps", "airspeed_delta_mps"),
    ("flight", "groundspeed_mps", "groundspeed_delta_mps"),
    ("flight", "vertical_speed_mps", "vertical_speed_delta_mps"),
    ("flight", "flight_path_angle_deg", "flight_path_angle_delta_deg"),
    ("flight", "angle_of_attack_deg", "angle_of_attack_delta_deg"),
    ("flight", "roll_deg", "roll_delta_deg"),
    ("flight", "pitch_deg", "pitch_delta_deg"),
    ("flight", "heading_deg", "heading_delta_deg"),
    ("runway", "along_track_m", "along_track_delta_m"),
    ("runway", "cross_track_error_m", "cross_track_error_delta_m"),
    ("runway", "glideslope_error_deg", "glideslope_error_delta_deg"),
    ("runway", "heading_error_deg", "heading_error_delta_deg"),
)

# Compact subset for recent-action history entries.
_HISTORY_FIELDS: tuple[str, ...] = (
    "airspeed_delta_mps",
    "vertical_speed_delta_mps",
    "flight_path_angle_delta_deg",
    "angle_of_attack_delta_deg",
    "cross_track_error_delta_m",
    "glideslope_error_delta_deg",
    "heading_error_delta_deg",
)


from .geometry import angle_delta as _angle_delta


def _compute_deltas(
    state_before: dict[str, Any],
    state_after: dict[str, Any],
) -> dict[str, float]:
    """Compute observation deltas between two state snapshots."""
    deltas: dict[str, float] = {}
    for group, key, delta_name in _DELTA_FIELDS:
        grp_before = state_before.get(group, {})
        grp_after = state_after.get(group, {})
        k_before = (
            key if key in grp_before else ("alpha_deg" if key == "angle_of_attack_deg" else key)
        )
        k_after = (
            key if key in grp_after else ("alpha_deg" if key == "angle_of_attack_deg" else key)
        )
        if key == "cross_track_error_m":
            if "centerline_offset_m" in grp_before:
                k_before = "centerline_offset_m"
            if "centerline_offset_m" in grp_after:
                k_after = "centerline_offset_m"
        before_val = float(grp_before.get(k_before, 0.0))
        after_val = float(grp_after.get(k_after, 0.0))
        if key in _WRAP_FIELDS:
            deltas[delta_name] = round(_angle_delta(after_val, before_val), 4)
        else:
            deltas[delta_name] = round(after_val - before_val, 4)
    return deltas


@dataclass
class ActionRecord:
    """Record of a completed control transition and its observed consequence."""

    action_id: str
    action_names: dict[str, str]
    applied_sim_time_s: float
    control_before: dict[str, float]
    control_after: dict[str, float]
    observed_sim_time_s: float | None = None
    elapsed_s: float | None = None
    observed_deltas: dict[str, float] | None = None


class DecisionTracker:
    """Tracks applied control transitions and computes observed consequences.

    Usage::

        tracker = DecisionTracker()

        # When action is applied to JSBSim:
        tracker.record_application(
            action_id, action_names, sim_time,
            control_before, control_after, state_snapshot,
        )

        # Before the next Jev decision:
        feedback = tracker.build_feedback(current_state, current_sim_time)
        # → feedback["previous_control_transition"]
        # → feedback["observed_since_previous_action"]
        # → feedback["recent_action_history"]
    """

    def __init__(self, max_history: int = 3) -> None:
        self._history: deque[ActionRecord] = deque(maxlen=max_history)
        self._pending: ActionRecord | None = None
        self._state_at_application: dict[str, Any] | None = None

    def reset(self) -> None:
        """Clear all tracking state."""
        self._history.clear()
        self._pending = None
        self._state_at_application = None

    def record_application(
        self,
        action_id: str,
        action_names: dict[str, str],
        sim_time: float,
        control_before: dict[str, float],
        control_after: dict[str, float],
        state_snapshot: dict[str, Any],
    ) -> None:
        """Record that a new action was written to JSBSim FCS.

        Args:
            action_id: Joint action key (e.g. ``"aileron=hold|elevator=increase_small|..."``).
            action_names: Per-axis action names ``{axis: name}``.
            sim_time: Simulation time when the action was applied.
            control_before: Control values before this action ``{axis: value}``.
            control_after: Control values after this action ``{axis: value}``.
            state_snapshot: Full observation dict at application time.
        """
        self._pending = ActionRecord(
            action_id=action_id,
            action_names=dict(action_names),
            applied_sim_time_s=sim_time,
            control_before=dict(control_before),
            control_after=dict(control_after),
        )
        # Store only the observation groups needed for delta computation.
        self._state_at_application = {
            "runway": dict(state_snapshot.get("runway", {})),
            "flight": dict(state_snapshot.get("flight", {})),
        }

    def build_feedback(
        self, current_state: dict[str, Any], current_sim_time: float
    ) -> dict[str, Any]:
        """Build feedback for the next Jev decision.

        Finalizes the pending action record by computing observed deltas,
        then returns the complete feedback dict.

        Returns:
            Dict with keys:
              - ``previous_control_transition``: ``dict | None``
              - ``observed_since_previous_action``: ``dict | None``
              - ``recent_action_history``: ``list[dict]``
        """
        previous_transition: dict[str, Any] | None = None
        observed_since: dict[str, Any] | None = None

        if self._pending is not None and self._state_at_application is not None:
            elapsed = round(current_sim_time - self._pending.applied_sim_time_s, 4)
            deltas = _compute_deltas(self._state_at_application, current_state)

            self._pending.observed_sim_time_s = current_sim_time
            self._pending.elapsed_s = elapsed
            self._pending.observed_deltas = deltas

            # Build previous_control_transition.
            previous_transition = {
                "selected_action_id": self._pending.action_id,
                "applied_sim_time_s": self._pending.applied_sim_time_s,
            }
            for axis in ("aileron", "elevator", "rudder", "throttle"):
                before = self._pending.control_before.get(axis, 0.0)
                after = self._pending.control_after.get(axis, 0.0)
                previous_transition[axis] = {
                    "action": self._pending.action_names.get(axis, "hold"),
                    "before": round(before, 4),
                    "after": round(after, 4),
                    "delta": round(after - before, 4),
                }

            # Build observed_since_previous_action.
            observed_since = {
                "from_sim_time_s": self._pending.applied_sim_time_s,
                "to_sim_time_s": current_sim_time,
                "elapsed_s": elapsed,
                **deltas,
            }

            # Move to history ring buffer.
            self._history.appendleft(self._pending)
            self._pending = None
            self._state_at_application = None

        # Build recent_action_history (max 3 entries).
        history: list[dict[str, Any]] = []
        for record in self._history:
            if record.observed_deltas is not None and record.elapsed_s is not None:
                history.append(
                    {
                        "age_s": round(current_sim_time - record.applied_sim_time_s, 2),
                        "elapsed_s": record.elapsed_s,
                        "action": record.action_names,
                        "observed": {
                            name: record.observed_deltas.get(name, 0.0) for name in _HISTORY_FIELDS
                        },
                    }
                )

        return {
            "previous_control_transition": previous_transition,
            "observed_since_previous_action": observed_since,
            "recent_action_history": history,
        }
