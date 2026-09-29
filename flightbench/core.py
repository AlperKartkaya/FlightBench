"""Shared constants and the canonical four-channel control command."""

from pydantic import BaseModel, ConfigDict, Field

# Trim offsets that counter propeller torque / P-factor / gyroscopic precession
# on the c172x at 65 KIAS, 20° flaps, 50 % throttle, −3° flight-path angle.
# Empirically verified: keeps roll < 5° and heading ≈ 90° for > 10 s.
TRIM_ELEVATOR = 0.17
TRIM_AILERON = -0.15
TRIM_RUDDER = 0.09

# Canonical physics and decision cadence (single source of truth)
PHYSICS_HZ: int = 120
DECISION_HZ: int = 2
DECISION_TICKS: int = 60  # 60 / 120 ticks = 0.50 s = 2 Hz
DECISION_INTERVAL_S: float = 0.5  # DECISION_TICKS / PHYSICS_HZ
MAX_DECISION_AGE_S: float = 2 * DECISION_INTERVAL_S
MICRO_DECISION_HZ = (2, 5, 10)
MICRO_SIM_SPEEDS = (1.0, 0.5, 0.25)
ACTUATOR_RATE_PER_S = {
    "aileron": 0.12,
    "elevator": 0.10,
    "rudder": 0.12,
    "throttle": 0.16,
}


def decision_timing(hz: int) -> tuple[int, float]:
    """Return exact physics ticks and simulation seconds for a supported rate."""
    if hz <= 0 or PHYSICS_HZ % hz:
        raise ValueError(f"decision rate must divide {PHYSICS_HZ} Hz")
    ticks = PHYSICS_HZ // hz
    return ticks, ticks / PHYSICS_HZ


OBSERVATION_SCHEMA_VERSION = "v2-temporal-feedback"


class ControlCommand(BaseModel):
    """Canonical FlightBench action."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    aileron: float = Field(ge=-1.0, le=1.0)
    elevator: float = Field(ge=-1.0, le=1.0)
    rudder: float = Field(ge=-1.0, le=1.0)
    throttle: float = Field(ge=0.0, le=1.0)
