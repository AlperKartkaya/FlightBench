"""Run native JSBSim then WASM with the same inputs; keep large traces in scratch/."""

import json
import os
import subprocess
from pathlib import Path

from flightbench.core import ControlCommand
from flightbench.environment import FixedWingLandingEnv
from flightbench.protocol import canonical_observation
from flightbench.scoring import ScoringConfig, evaluate
from flightbench.temporal import TelemetryHistory

ROOT = Path(__file__).resolve().parents[1]


def main():
    # Import only for the baseline calculation; never load local provider credentials.
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    from flightbench.controllers import BaselineController

    cases = []
    for name, command, duration in (
        ("trim-10s", {"aileron": -0.15, "elevator": 0.17, "rudder": 0.09, "throttle": 0.5}, 10),
        ("left-10s", {"aileron": -0.20, "elevator": 0.17, "rudder": 0.09, "throttle": 0.5}, 10),
        (
            "pitch-power-10s",
            {"aileron": -0.15, "elevator": 0.20, "rudder": 0.05, "throttle": 0.4},
            10,
        ),
        ("trim-full", {"aileron": -0.15, "elevator": 0.17, "rudder": 0.09, "throttle": 0.5}, 120),
        ("baseline-full", None, 120),
    ):
        env = FixedWingLandingEnv(max_time_s=duration)
        baseline = BaselineController()
        history = TelemetryHistory()
        history.add(env.observe())
        samples = [{"observation": env.observe(), "result": env.info()["result"]}]
        decisions = []
        action = ControlCommand(**command) if command else None
        while not env.done:
            if env.ticks % 60 == 0:
                obs = env.observe()
                state = canonical_observation({**obs, "temporal": history.features(obs)})
                if command is None:
                    action = baseline.decide(obs)
                decisions.append(
                    {
                        "tick": env.ticks,
                        "state": state,
                        "baseline": baseline.decide(obs).model_dump(),
                        "action": action.model_dump(),
                    }
                )
            obs, _, _, _, info = env.advance(action)
            samples.append({"observation": obs, "result": info["result"]})
            if env.ticks % 60 == 0 or env.done:
                history.add(obs)
        cases.append(
            {"name": name, "duration": duration, "decisions": decisions, "samples": samples}
        )
        env.close()
    path = ROOT / "scratch/wasm-python-traces.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(cases, allow_nan=False))
    c = ScoringConfig()
    touchdown = {
        "along_track_m": 200,
        "cross_track_m": 0,
        "sink_rate_mps": -0.8,
        "airspeed_mps": 28,
        "heading_error_deg": 0,
        "roll_deg": 0,
        "pitch_deg": 3,
    }
    fixtures = []
    for touch, success, reason in (
        (None, False, "running"),
        (touchdown, True, "landed"),
        (touchdown, False, "runway_excursion"),
        ({**touchdown, "sink_rate_mps": -3.01}, True, "unsafe_touchdown"),
    ):
        trajectory = {"lateral": 0.2, "pitch": 0.3, "glide": 0.4}
        fixtures.append(
            {
                "touchdown": touch,
                "success": success,
                "reason": reason,
                "trajectory": trajectory,
                "expected": evaluate(touch, success, reason, c, trajectory),
            }
        )
    (ROOT / "docs/wasm/scoring-fixtures.json").write_text(json.dumps(fixtures, indent=2) + "\n")
    subprocess.run(["node", "examples/wasm/compare.mjs", str(path)], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
