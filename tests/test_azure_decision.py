"""Offline adapter checks; executable with stdlib unittest and the project Python."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from examples.controllers.azure_decision import MODEL, AzureDecisionController
from flightbench.loading import ExternalController
from flightbench.protocol import action_space, canonical_observation, command_from_action_ids


class RealtimeInputTests(unittest.TestCase):
    def test_tick_reconstruction_checks_motion_controls_and_trailing_request(self):
        from copy import deepcopy

        from examples.run_azure_decision_campaign import realtime_inputs
        from flightbench.core import TRIM_AILERON, TRIM_ELEVATOR, TRIM_RUDDER, ControlCommand
        from flightbench.environment import FixedWingLandingEnv
        from flightbench.temporal import TelemetryHistory

        env = FixedWingLandingEnv()
        try:
            observation, _ = env.reset(seed=42)
            history = TelemetryHistory()
            history.add(observation)
            action = ControlCommand(
                aileron=TRIM_AILERON, elevator=TRIM_ELEVATOR, rudder=TRIM_RUDDER, throttle=0.5
            )
            decisions, requests = [], []
            for tick in range(120):
                if tick in (0, 40, 90):
                    requests.append(
                        {
                            "state": canonical_observation(
                                observation | {"temporal": history.features(observation)}
                            )
                        }
                    )
                if tick in (7, 53):
                    action = command_from_action_ids(
                        {"aileron": "3", "elevator": "7", "rudder": "3", "throttle": "3"}
                    )
                    decisions.append(
                        {
                            "applied": True,
                            "applied_sim_time_s": tick / 120,
                            "control_after": action.model_dump(),
                        }
                    )
                observation, _, _, _, _ = env.advance(action, ticks=1)
                history.add(observation)
            episode = {
                "config": {"scenario": "easy", "seed": 42},
                "decisions": decisions,
                "final_state": env.snapshot(),
            }
        finally:
            env.close()
        realtime_inputs(episode, requests)
        for field in ("current_controls", "motion"):
            altered = deepcopy(requests)
            altered[0]["state"][field] = {}
            with self.assertRaises(ValueError):
                realtime_inputs(episode, altered)


class AzureDecisionTests(unittest.TestCase):
    def test_network_failure_is_logged_and_retried_without_changing_input(self):
        from io import BytesIO

        with tempfile.TemporaryDirectory() as directory:
            controller = object.__new__(AzureDecisionController)
            controller._key = "test-secret"
            controller._log = Path(directory) / "requests.jsonl"
            stream = BytesIO(json.dumps({"model": MODEL.lower()}).encode())
            stream.status = 200
            with (
                patch(
                    "examples.controllers.azure_decision.urlopen",
                    side_effect=[URLError("offline"), stream],
                ),
                patch("examples.controllers.azure_decision.sleep"),
            ):
                controller._request("systemone", {"model": MODEL, "state": {"test": True}})
            rows = [json.loads(line) for line in controller._log.read_text().splitlines()]
            assert [row["status"] for row in rows] == [0, 200]
            assert rows[0]["request"] == rows[1]["request"]
            assert "test-secret" not in controller._log.read_text()

    def test_transport_preserves_frozen_protocol_and_never_logs_key(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "requests.jsonl"
            response = {
                "model": MODEL.lower(),
                "answers": {
                    axis: {"type": "choice", "choice": "3"}
                    for axis in ("aileron", "elevator", "rudder", "throttle")
                },
                "usage": {"input_tokens": 123, "output_tokens": 4},
            }
            from io import BytesIO

            stream = BytesIO(json.dumps(response).encode())
            stream.status = 200
            with (
                patch.dict(os.environ, FLIGHTBENCH_AZURE_LOG=str(log)),
                patch(
                    "examples.controllers.azure_decision.subprocess.check_output",
                    return_value=b'{"key1":"test-secret"}',
                ),
                patch("examples.controllers.azure_decision.urlopen", return_value=stream) as call,
            ):
                controller = ExternalController(
                    "examples.controllers.azure_decision:AzureDecisionController"
                )
                observation = {
                    "flight": {},
                    "runway": {"altitude_agl_m": 30},
                    "controls": {"aileron": -0.15, "elevator": 0.17, "throttle": 0.5},
                    "temporal": {"rates": {"altitude_agl_m_per_s": -1.5}},
                }
                command = controller.decide(observation)
            row = json.loads(log.read_text())
            state = row["request"]["state"]
            assert state == canonical_observation(observation)
            axes = action_space()["phases"][state["phase"]]
            assert row["request"]["questions"] == {
                axis: {
                    "type": "choice",
                    "instructions": spec["instructions"],
                    "criteria": {a["id"]: a["criterion"] for a in spec["actions"]},
                }
                for axis, spec in axes.items()
            }
            assert row["request"]["model"] == "decision-1"
            assert "keep_alive" not in row["request"]
            assert "test-secret" not in log.read_text()
            assert call.call_args.args[0].get_header("Api-key") == "test-secret"
            assert command == command_from_action_ids(controller.last_decision["action_ids"])
            assert controller.metadata["local"] is False

    def test_truncation_and_invalid_actions_fail_closed(self):
        controller = object.__new__(AzureDecisionController)
        controller.model_id = MODEL
        base = {
            "answers": {a: {"choice": "3"} for a in ("aileron", "elevator", "rudder", "throttle")}
        }
        for signal in (
            {"truncated": True},
            {"truncation": {"dropped": 1}},
            {"usage": {"state_tokens": 100, "state_tokens_used": 99}},
            {"answers": {"aileron": {"choice": "invalid"}}},
        ):
            with (
                patch.object(controller, "_request", return_value=base | signal),
                self.assertRaises(ValueError),
            ):
                controller.decide(
                    canonical_observation({"flight": {}, "runway": {"altitude_agl_m": 30}})
                )
            assert not hasattr(controller, "last_decision")


if __name__ == "__main__":
    unittest.main()
