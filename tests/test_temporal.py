import pytest

from flightbench.temporal import TelemetryHistory, angle_delta


def sample(time_s, *, airspeed=29.0, cross_track=0.0, heading_error=0.0, distance=1000.0):
    return {
        "time_s": time_s,
        "flight": {"airspeed_mps": airspeed, "vertical_speed_mps": -1.5},
        "runway": {
            "cross_track_error_m": cross_track,
            "glideslope_error_deg": 0.0,
            "heading_error_deg": heading_error,
            "distance_to_threshold_m": distance,
        },
    }


def test_temporal_rates_use_sim_time_and_signs():
    history = TelemetryHistory()
    history.add(sample(0.0))
    history.add(sample(0.5, airspeed=30.0, cross_track=2.0, distance=985.0))
    features = history.features(sample(1.0, airspeed=31.0, cross_track=1.0, distance=970.0))

    assert features["rates"]["airspeed_rate_mps2"] == pytest.approx(2.0)
    assert features["rates"]["cross_track_rate_mps"] == pytest.approx(-2.0)
    assert features["rates"]["distance_closure_rate_mps"] == pytest.approx(30.0)


def test_heading_delta_wraps_at_180_degrees():
    assert angle_delta(1.0, 359.0) == pytest.approx(2.0)
    assert angle_delta(359.0, 1.0) == pytest.approx(-2.0)


def test_constant_state_has_zero_rate():
    history = TelemetryHistory()
    history.add(sample(0.0))
    history.add(sample(0.5))
    features = history.features(sample(1.0))
    assert features["rates"]["airspeed_rate_mps2"] == pytest.approx(0.0)
    assert features["rates"]["cross_track_rate_mps"] == pytest.approx(0.0)
