"""Offline transport and frozen-protocol checks for the self-hosted adapter."""

import json
import os
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from examples.controllers.glide import GlideController
from flightbench.protocol import action_space


class GlideTests(unittest.TestCase):
    def test_complete_json_episode_is_retained_and_compressed_without_rerunning(self):
        from examples.run_glide_twenty import load_trial

        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            raw = folder / "flight.json"
            raw.write_text('{"type":"episode","run_id":"preserve"}')
            original = raw.read_bytes()
            self.assertEqual(load_trial(folder)["run_id"], "preserve")
            self.assertEqual(raw.read_bytes(), original)
            self.assertTrue((folder / "flight.json.gz").is_file())
            (folder / "replay.json").write_text('{"type":"replay"}')
            self.assertEqual(load_trial(folder)["run_id"], "preserve")
            (folder / "duplicate.json").write_bytes(original)
            with self.assertRaises(AssertionError):
                load_trial(folder)

    def test_twenty_trial_plan_and_continuous_realtime_settings(self):
        from examples import run_glide_twenty as campaign

        self.assertEqual(len(campaign.SEEDS), 10)
        self.assertEqual(len(set(campaign.SEEDS)), 10)
        self.assertEqual(len(campaign.MODES) * len(campaign.SEEDS), 20)
        for mode, expected in (("realtime", "continuous"), ("lockstep", "fixed")):
            with tempfile.TemporaryDirectory() as directory:
                folder = Path(directory) / "flight"
                with patch.dict(os.environ), patch.object(campaign, "run_episode") as run:
                    campaign.trial(mode, 42, folder)
                    self.assertTrue(folder.exists())
                    self.assertEqual(
                        os.environ["FLIGHTBENCH_DECISION_LOG"], str(folder / "provider.jsonl")
                    )
                self.assertEqual(run.call_args.kwargs["decision_schedule"], expected)
                self.assertEqual(
                    run.call_args.kwargs["realtime_response_policy"], "apply-on-arrival"
                )
                self.assertEqual(run.call_args.kwargs["scenario"], "easy")
                self.assertEqual(run.call_args.kwargs["time_scale"], 1.0)
                self.assertEqual(run.call_args.kwargs["decision_hz"], 2)

    def test_summary_distinguishes_all_run_and_success_only_mean(self):
        from examples.run_glide_campaign import summarize

        self.assertIsNone(summarize([{"success": False, "quality": 0}])["mean_successful_only"])
        result = summarize([{"success": True, "quality": 60}, {"success": False, "quality": 0}])
        self.assertEqual(result["mean_all_runs"], 30)
        self.assertEqual(result["mean_successful_only"], 60)
        self.assertEqual(result["successful_only_denominator"], 1)

    def test_raw_recovery_keeps_manifest_boundary_and_rejects_api_failure(self):
        from examples.run_glide_campaign import group
        from examples.run_ten_trial_campaign import verify, verify_episode

        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            with self.assertRaises(FileNotFoundError):
                verify(folder, group("realtime"), 42, {})
            record = {
                "source_identity": {"source_hash": "frozen", "git_commit": None},
                "config": {
                    "controller": group("realtime")[1],
                    "model": "glide-v1.2",
                    "mode": "realtime",
                    "seed": 42,
                    "scenario": "easy",
                    "decision_hz": 2,
                    "time_scale": 1.0,
                    "reasoning_effort": "low",
                },
                "outcome": {"status": "out_of_bounds"},
                "diagnostics": {"api_errors": 1},
            }
            with self.assertRaisesRegex(RuntimeError, "Infrastructure failure"):
                verify_episode(record, folder, group("realtime"), 42, {"source_hash": "frozen"})
            self.assertIsNone(record["source_identity"]["git_commit"])

    def test_frozen_questions_input_and_actions_are_retained(self):
        phase = next(iter(action_space()["phases"]))
        observation = {"phase": phase, "canonical_sentinel": "preserve unchanged"}
        axes = action_space()["phases"][phase]
        choices = {axis: spec["actions"][0]["id"] for axis, spec in axes.items()}
        response = {
            "model": "glide-v1.2",
            "answers": {axis: {"choice": value} for axis, value in choices.items()},
        }
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "provider.jsonl"
            with patch.dict(os.environ, FLIGHTBENCH_DECISION_LOG=str(log)):
                controller = GlideController()
            stream = BytesIO(json.dumps(response).encode())
            stream.status = 200
            with patch("examples.controllers.glide.urlopen", return_value=stream) as call:
                self.assertEqual(controller.decide(observation), choices)
            sent = json.loads(call.call_args.args[0].data)
            self.assertEqual(sent["state"], observation)
            self.assertEqual(sent["model"], "glide-v1.2")
            for axis, spec in axes.items():
                self.assertEqual(
                    sent["questions"][axis],
                    {
                        "type": "choice",
                        "instructions": spec["instructions"],
                        "criteria": {a["id"]: a["criterion"] for a in spec["actions"]},
                    },
                )
            self.assertEqual(json.loads(log.read_text())["response"], response)
            self.assertEqual(call.call_args.args[0].full_url, controller.endpoint)

    def test_wrong_identity_and_network_error_are_logged_not_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "provider.jsonl"
            with patch.dict(os.environ, FLIGHTBENCH_DECISION_LOG=str(log)):
                controller = GlideController()
            stream = BytesIO(b'{"model":"wrong"}')
            stream.status = 200
            with (
                patch("examples.controllers.glide.urlopen", return_value=stream),
                self.assertRaisesRegex(ValueError, "Unexpected model identity"),
            ):
                controller._request("systemone", {"state": {}})
            with patch(
                "examples.controllers.glide.urlopen", side_effect=URLError("offline")
            ) as call:
                with self.assertRaises(URLError):
                    controller._request("systemone", {"state": {}})
                self.assertEqual(call.call_count, 1)
            rows = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual([r["exception_type"] for r in rows], ["ValueError", "URLError"])

    def test_truncation_is_still_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, FLIGHTBENCH_DECISION_LOG=str(Path(directory) / "raw")):
                controller = GlideController()
            phase = next(iter(action_space()["phases"]))
            with (
                patch.object(controller, "_request", return_value={"truncated": True}),
                self.assertRaisesRegex(ValueError, "truncated"),
            ):
                controller.decide({"phase": phase})


if __name__ == "__main__":
    unittest.main()
