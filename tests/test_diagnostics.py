"""Replay identical diagnostic states through actual adapters with offline transports."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

from flightbench import controllers
from flightbench.controllers import CodexController, JevController
from flightbench.diagnostics import replay
from flightbench.local import SystemOneController
from flightbench.protocol import action_space, canonical_observation, command_from_action_ids

CASES = json.loads((Path(__file__).parent / "fixtures/decision-states-v1.json").read_text())
IDS = {"aileron": "0", "elevator": "7", "rudder": "4", "throttle": "3"}


def test_frozen_states_preserve_information_across_adapters(monkeypatch):
    requests = {}

    def local_request(self, method, payload):
        requests["local"] = payload
        return {"answers": {k: {"choice": v} for k, v in IDS.items()}}

    def system_one(**kwargs):
        requests["jev"] = kwargs
        return SimpleNamespace(
            model=kwargs["model"],
            choices={
                k: SimpleNamespace(choice=v, confidence=1.0, probabilities={v: 1.0})
                for k, v in IDS.items()
            },
        )

    def prompt(payload, **kwargs):
        requests["codex"] = (json.loads(payload), kwargs["system"])
        return SimpleNamespace(text=lambda: json.dumps(IDS), response_json={})

    monkeypatch.setattr(SystemOneController, "_request", local_request)
    monkeypatch.setitem(
        sys.modules,
        "typesafe_sdk",
        SimpleNamespace(
            Choice=lambda **kw: SimpleNamespace(**kw),
            RetryPolicy=lambda **kw: None,
            TypeSafeClient=lambda: SimpleNamespace(system_one=system_one),
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "llm",
        SimpleNamespace(
            get_models=lambda: [SimpleNamespace(model_id="openai-codex/test")],
            get_model=lambda model: SimpleNamespace(prompt=prompt),
        ),
    )
    monkeypatch.setattr(controllers, "_codex_authenticated", lambda: True)
    adapters = [SystemOneController("test"), JevController(), CodexController()]
    for case in CASES:
        state = canonical_observation(case["observation"])
        for adapter in adapters:
            assert adapter.decide(case["observation"]) == command_from_action_ids(IDS)
            assert adapter.last_decision["input"] == state
        assert requests["local"]["state"] == requests["jev"]["state"] == requests["codex"][0]
        spec = action_space()["phases"][state["phase"]]
        for axis, question in requests["local"]["questions"].items():
            jev_question = requests["jev"]["questions"][axis]
            assert (
                question["instructions"] == jev_question.instructions == spec[axis]["instructions"]
            )
            assert question["criteria"] == jev_question.criteria
            for criterion in question["criteria"].values():
                assert criterion in requests["codex"][1]
    phases = [canonical_observation(c["observation"])["phase"] for c in CASES]
    assert phases == ["APPROACH"] * 5 + ["FLARE", "ROLLOUT"]


def test_replay_retains_first_pass_and_copies_decision_records():
    class Controller:
        def __init__(self):
            self.last_decision = {}

        def decide(self, observation):
            self.last_decision["input"] = canonical_observation(observation)
            return command_from_action_ids(IDS)

    records = replay(Controller(), CASES, repeats=2)
    assert len(records) == 2 * len(CASES)
    assert [r["repeat"] for r in records] == [0] * len(CASES) + [1] * len(CASES)
    assert records[0]["decision_info"]["input"] == canonical_observation(CASES[0]["observation"])
    assert all(r["latency_ms"] >= 0 for r in records)
