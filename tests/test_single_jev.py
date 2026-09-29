"""One selectable Jev policy: archived records may retain old names, new runs may not."""

import pytest

from flightbench.controllers import make_controller


@pytest.mark.parametrize("name", ["jev-micro", "jev-decomposed", "jev-33", "jev-9", "jev-81"])
def test_retired_jev_names_are_rejected(name):
    with pytest.raises(ValueError, match="Unknown controller"):
        make_controller(name)


def test_direct_jev_applies_selected_commands_without_fallback_or_blending(monkeypatch):
    import sys
    from types import SimpleNamespace

    from flightbench.controllers import (
        JEV_COMMANDS,
        JEV_CRITERIA,
        JEV_MODEL,
        JEV_NEAR_GROUND_ELEVATOR,
        JevController,
    )
    from flightbench.environment import FixedWingLandingEnv
    from flightbench.runs import RunSettings, effective_config

    requests = []
    selected = {"aileron": "4", "elevator": "6", "rudder": "3", "throttle": "3"}

    class Client:
        def system_one(self, **kwargs):
            requests.append(kwargs)
            return SimpleNamespace(
                choices={
                    axis: SimpleNamespace(
                        choice=choice, confidence=0.01, probabilities={choice: 0.4, "0": 0.6}
                    )
                    for axis, choice in selected.items()
                }
            )

    monkeypatch.setitem(
        sys.modules,
        "typesafe_sdk",
        SimpleNamespace(
            Choice=lambda **kw: SimpleNamespace(**kw),
            RetryPolicy=lambda **kw: SimpleNamespace(**kw),
            TypeSafeClient=lambda **kw: Client(),
        ),
    )
    controller = JevController()
    env = FixedWingLandingEnv()
    obs, _ = env.reset(seed=42)
    obs["temporal"] = {"rates": {"cross_track_rate_mps": -1.25}}

    def forbidden_baseline(*args, **kwargs):
        pytest.fail("Jev must never call baseline")

    monkeypatch.setattr("flightbench.controllers.BaselineController.decide", forbidden_baseline)
    action = controller.decide(obs)
    assert action.model_dump() == {axis: JEV_COMMANDS[axis][int(i)] for axis, i in selected.items()}
    assert len(requests) == 1 and requests[0]["model"] == JEV_MODEL
    assert set(requests[0]["questions"]) == set(JEV_COMMANDS)
    assert requests[0]["state"]["flight"] == obs["flight"]
    assert requests[0]["state"]["runway"] == obs["runway"]
    assert requests[0]["state"]["motion"] == obs["temporal"]["rates"]
    assert requests[0]["state"]["status"] == obs["status"]
    assert list(requests[0]["questions"]["elevator"].criteria.values()) == JEV_CRITERIA["elevator"]
    assert controller.last_decision["policy"] == "direct-categorical"
    config = effective_config(RunSettings(controller="jev"), controller)
    assert config["assistance"] == "none" and config["experimental"] is True
    obs["runway"]["altitude_agl_m"] = 8
    controller.decide(obs)
    assert requests[-1]["state"]["phase"] == "FLARE"
    assert list(requests[-1]["questions"]["elevator"].criteria.values()) == JEV_NEAR_GROUND_ELEVATOR
    assert (
        requests[-1]["questions"]["elevator"].criteria.keys()
        == requests[0]["questions"]["elevator"].criteria.keys()
    )
    assert controller.last_decision["choices"]["elevator"]["label"] == JEV_NEAR_GROUND_ELEVATOR[6]
    assert controller.last_decision["command"]["elevator"] == JEV_COMMANDS["elevator"][6]
    obs["status"]["on_ground"] = True
    ground_action = controller.decide(obs)
    assert requests[-1]["state"]["phase"] == "ROLLOUT"
    assert ground_action.throttle == 0.5  # Still model-selected; no automatic idle override.
    obs["status"]["on_ground"] = False
    obs["runway"]["altitude_agl_m"] = 30
    controller.decide(obs)
    assert requests[-1]["state"]["phase"] == "APPROACH"
    assert list(requests[-1]["questions"]["elevator"].criteria.values()) == JEV_CRITERIA["elevator"]
    selected["elevator"] = "illegal"
    with pytest.raises(ValueError, match="invalid actuator"):
        controller.decide(obs)
    with pytest.raises(ValueError, match="one pinned model"):
        JevController(model="another-model")
    env.close()


@pytest.mark.parametrize("field", ["action_variant", "stability_maintainer", "delta_scale"])
def test_retired_policy_settings_rejected_at_request_boundary(field):
    from flightbench.runs import RunSettings

    with pytest.raises(ValueError):
        RunSettings.model_validate({"controller": "jev", field: "legacy"})


def test_jev_options_are_complete_absolute_commands_with_matching_descriptions():
    from flightbench.controllers import JEV_COMMANDS, JEV_CRITERIA, JEV_INSTRUCTIONS
    from flightbench.core import ControlCommand

    assert set(JEV_COMMANDS) == set(ControlCommand.model_fields)
    assert set(JEV_COMMANDS) == set(JEV_CRITERIA) == set(JEV_INSTRUCTIONS)
    for axis, values in JEV_COMMANDS.items():
        assert len(values) == len(JEV_CRITERIA[axis])
        assert len(values) == len(set(values))
        for value in values:
            controls = {"aileron": 0.0, "elevator": 0.0, "rudder": 0.0, "throttle": 0.5}
            ControlCommand(**(controls | {axis: value}))


def test_bank_recovery_priority_does_not_overlap_gentle_or_trim_choices():
    from flightbench.controllers import JEV_CRITERIA, JEV_INSTRUCTIONS

    assert "Arrest a bank of 3 degrees or more BEFORE" in JEV_INSTRUCTIONS["aileron"]
    assert "Only with bank below 3 degrees" in JEV_INSTRUCTIONS["aileron"]
    for choice in (2, 3, 4):
        assert JEV_CRITERIA["aileron"][choice].startswith(
            "Only with bank between -3 and +3 degrees:"
        )
