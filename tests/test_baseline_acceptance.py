"""Local, provider-free reference controller acceptance cases."""

import pytest

from flightbench.controllers import BaselineController
from flightbench.environment import FixedWingLandingEnv


@pytest.mark.parametrize("scenario,seed", [("easy", 42), *[("medium", n) for n in range(40, 50)]])
@pytest.mark.parametrize("runway_heading_deg", [0, 90])
def test_baseline_safe_touchdown_and_rollout(scenario, seed, runway_heading_deg):
    env = FixedWingLandingEnv(scenario=scenario, runway_heading_deg=runway_heading_deg)
    observation, _ = env.reset(seed=seed)
    controller = BaselineController()
    while not env.done:
        observation, _, _, _, info = env.step(controller.decide(observation))
    assert info["result"]["success"], info["result"]
    assert info["result"]["touchdown_safe"]
    assert observation["flight"]["groundspeed_mps"] < 3
    env.close()
