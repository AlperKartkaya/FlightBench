"""Offline checks for the requested cohort, transports, and scoring summary."""

import json
from io import BytesIO
from unittest.mock import patch

import pytest

from examples.controllers.decision_apis import GeminiDecisionController, OpenAIDecisionController
from examples.run_ten_trial_campaign import GROUPS, SEEDS, summarize
from flightbench.loading import ExternalController
from flightbench.protocol import action_space, canonical_observation


def test_exact_requested_cohort_and_success_count():
    assert len(GROUPS) * len(SEEDS) == 110
    assert len(set(SEEDS)) == 10
    assert sum(g[1] == "jev" for g in GROUPS) == 4
    assert sum(g[1] == "codex" for g in GROUPS) == 4
    assert summarize(
        {"model": [{"success": False, "quality": 0}, {"success": True, "quality": 73.5}]}
    ) == [{"group": "model", "completed": 2, "successful_landings": 1, "highest_score": 73.5}]
    assert summarize({"pending": []})[0]["highest_score"] is None


def test_microsoft_11_campaign_is_isolated_and_reuses_ten_seeds(monkeypatch, tmp_path):
    import examples.run_ten_trial_campaign as campaign

    for name in ("DATA", "EVIDENCE", "GROUPS"):
        monkeypatch.setattr(campaign, name, getattr(campaign, name))
    with (
        patch(
            "sys.argv",
            [
                "campaign",
                "--microsoft-decision-1-1",
                "--trial",
                "0",
                "--seed",
                "42",
                "--folder",
                str(tmp_path),
            ],
        ),
        patch.object(campaign, "trial") as trial,
    ):
        campaign.main()
    assert campaign.DATA.name == "2026-11-19-microsoft-decision-1.1-easy"
    assert campaign.EVIDENCE.name == campaign.DATA.name
    assert len(campaign.GROUPS) * len(campaign.SEEDS) == 10
    group = campaign.GROUPS[0]
    assert group[1:] == (
        "examples.controllers.azure_decision:AzureDecision11Controller",
        "Microsoft-Decision-1.1",
        "lockstep",
    )
    trial.assert_called_once_with(group, 42, tmp_path)


@pytest.mark.parametrize("cls", [OpenAIDecisionController, GeminiDecisionController])
def test_native_transports_preserve_protocol_and_log_without_keys(tmp_path, cls):
    response = {
        "model": cls.model,
        "answers": {
            axis: {"type": "choice", "choice": "3"}
            for axis in ("aileron", "elevator", "rudder", "throttle")
        },
    }
    if cls is OpenAIDecisionController:
        response["answers"] = [
            {"name": axis, **answer} for axis, answer in response["answers"].items()
        ]
    stream = BytesIO(json.dumps(response).encode())
    stream.status = 200
    log = tmp_path / "provider.jsonl"
    with (
        patch.dict(
            "os.environ", {cls.key_name: "test-secret", "FLIGHTBENCH_DECISION_LOG": str(log)}
        ),
        patch("examples.controllers.decision_apis.urlopen", return_value=stream),
    ):
        controller = ExternalController(f"examples.controllers.decision_apis:{cls.__name__}")
        observation = {
            "flight": {},
            "runway": {},
            "controls": {"elevator": 0.17},
            "temporal": {"rates": {"altitude_agl_m_per_s": -1.5}},
        }
        controller.decide(observation)
    row = json.loads(log.read_text())
    state = canonical_observation(observation)
    assert row["state"] == state
    assert "test-secret" not in log.read_text()
    payload = row["request"]
    assert payload["model"] == cls.model
    if cls is OpenAIDecisionController:
        assert payload["input"][0]["content"][0] == {"type": "input_json", "data": state}
        questions = {
            q["name"]: {
                "instructions": q["instructions"],
                "criteria": {c["value"]: c["description"] for c in q["choices"]},
            }
            for q in payload["questions"]
        }
    else:
        assert json.loads(payload["input"]) == state
        questions = payload["questions"]
    for axis, spec in action_space()["phases"][state["phase"]].items():
        assert questions[axis]["instructions"] == spec["instructions"]
        assert questions[axis]["criteria"] == {a["id"]: a["criterion"] for a in spec["actions"]}


@pytest.mark.parametrize(
    "answer",
    [
        {"type": "refusal", "name": "aileron"},
        {"type": "choice", "name": "aileron", "choice": "99"},
    ],
)
def test_refusals_and_invalid_actions_fail_closed(tmp_path, answer):
    controller = OpenAIDecisionController
    stream = BytesIO(json.dumps({"answers": [answer]}).encode())
    stream.status = 200
    with (
        patch.dict(
            "os.environ",
            {
                controller.key_name: "secret",
                "FLIGHTBENCH_DECISION_LOG": str(tmp_path / "raw.jsonl"),
            },
        ),
        patch("examples.controllers.decision_apis.urlopen", return_value=stream),
        pytest.raises(ValueError),
    ):
        controller().decide(canonical_observation({"flight": {}, "runway": {}}))


def test_successful_transport_retry_is_accepted_only_for_identical_payload():
    from examples.run_ten_trial_campaign import successful_responses

    request = {"state": {"time_s": 1}}
    rows = [{"status": 0, "request": request}, {"status": 200, "request": request}]
    assert successful_responses(rows) == [rows[1]]
    with pytest.raises(AssertionError):
        successful_responses(rows[:1])
    with pytest.raises(AssertionError):
        successful_responses([rows[0], {"status": 200, "request": {"state": {"time_s": 2}}}])


def test_gemini_throttle_retry_preserves_and_logs_each_attempt(tmp_path):
    from urllib.error import HTTPError

    response = {
        "answers": {
            axis: {"type": "choice", "choice": "3"}
            for axis in ("aileron", "elevator", "rudder", "throttle")
        }
    }
    stream = BytesIO(json.dumps(response).encode())
    stream.status = 200
    error = HTTPError(
        "https://example.test", 429, "throttled", {}, BytesIO(b'{"error":"throttle"}')
    )
    log = tmp_path / "raw.jsonl"
    with (
        patch.dict(
            "os.environ", {"GEMINI_API_KEY": "secret", "FLIGHTBENCH_DECISION_LOG": str(log)}
        ),
        patch("examples.controllers.decision_apis.urlopen", side_effect=[error, stream]) as call,
        patch("examples.controllers.decision_apis.sleep") as sleep,
    ):
        GeminiDecisionController().decide(canonical_observation({"flight": {}, "runway": {}}))
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    assert [row["status"] for row in rows] == [429, 200]
    assert rows[0]["request"] == rows[1]["request"]
    assert call.call_count == 2
    assert any(args.args == (60,) for args in sleep.call_args_list)


def test_codex_retry_journal_requires_an_identical_request():
    from examples.run_ten_trial_campaign import completed_codex_requests

    request = {"input": "same state", "reasoning": {"effort": "low"}}
    rows = [
        {"event": "request", "request": request},
        {"event": "controller_error"},
        {"event": "quota_wait"},
        {"event": "request", "request": request},
        {"event": "response.completed"},
    ]
    assert completed_codex_requests(rows) == [request]
    with pytest.raises(AssertionError):
        completed_codex_requests(rows[:2])
    with pytest.raises(AssertionError):
        completed_codex_requests(rows[:3] + [{"event": "request", "request": {"input": "changed"}}])


@pytest.mark.parametrize("suspend_seconds", [0, 3600])
def test_codex_quota_wait_retries_without_advancing_observation(tmp_path, suspend_seconds):
    import httpx2 as httpx
    from llm_openai_via_codex import CodexResponsesModel
    from openai import RateLimitError

    from examples.run_ten_trial_campaign import install_logging
    from flightbench.controllers import CodexController

    error = RateLimitError(
        "quota",
        response=httpx.Response(429, request=httpx.Request("POST", "https://example.test")),
        body={"error": {"type": "usage_limit_reached", "resets_at": 1060}},
    )
    clock = [1000]

    def advance(seconds):
        clock[0] += seconds + suspend_seconds

    state, action = {"time_s": 3}, object()
    log = tmp_path / "provider.jsonl"
    with (
        patch.object(CodexResponsesModel, "_build_kwargs", CodexResponsesModel._build_kwargs),
        patch.object(CodexResponsesModel, "_handle_event", CodexResponsesModel._handle_event),
        patch.object(
            CodexResponsesModel, "_get_client_kwargs", CodexResponsesModel._get_client_kwargs
        ),
        patch.object(CodexController, "decide", side_effect=[error, action]) as decide,
        patch("examples.run_ten_trial_campaign.time", side_effect=lambda: clock[0]),
        patch("examples.run_ten_trial_campaign.sleep", side_effect=advance) as sleep,
    ):
        install_logging(log, "codex")
        controller = object.__new__(CodexController)
        assert controller.decide(state) is action
        assert decide.call_count == 2
        assert all(call.args == (controller, state) for call in decide.call_args_list)
        assert [c.args[0] for c in sleep.call_args_list] == (
            [60, 5] if suspend_seconds == 0 else [60]
        )
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    assert [row["event"] for row in rows] == ["controller_error", "quota_wait"]


@pytest.mark.parametrize("failures", [1, 3])
@pytest.mark.parametrize("error_name", ["APIConnectionError", "APITimeoutError", "overloaded"])
def test_codex_network_retry_is_bounded_and_preserves_observation(tmp_path, failures, error_name):
    import httpx2
    import openai
    from llm_openai_via_codex import CodexResponsesModel

    from examples.run_ten_trial_campaign import install_logging
    from flightbench.controllers import CodexController

    request = httpx2.Request("POST", "https://example.test")
    error = (
        openai.APIError("overloaded", request, body={"code": "server_is_overloaded"})
        if error_name == "overloaded"
        else getattr(openai, error_name)(request=request)
    )
    state, action = {"time_s": 3}, object()
    log = tmp_path / "provider.jsonl"
    with (
        patch.object(CodexResponsesModel, "_build_kwargs", CodexResponsesModel._build_kwargs),
        patch.object(CodexResponsesModel, "_handle_event", CodexResponsesModel._handle_event),
        patch.object(CodexResponsesModel, "_get_client_kwargs", return_value={"api_key": "secret"}),
        patch.object(
            CodexController, "decide", side_effect=[error] * failures + [action]
        ) as decide,
        patch("examples.run_ten_trial_campaign.sleep") as sleep,
    ):
        install_logging(log, "codex")
        model = object.__new__(CodexResponsesModel)
        assert model._get_client_kwargs() == {"api_key": "secret", "timeout": 60, "max_retries": 0}
        controller = object.__new__(CodexController)
        if failures == 3:
            with pytest.raises(type(error)):
                controller.decide(state)
        else:
            assert controller.decide(state) is action
        assert decide.call_count == min(failures + 1, 3)
        assert sleep.call_count == min(failures, 2)
        assert all(
            c.args == (5 if error_name == "overloaded" else 1,) for c in sleep.call_args_list
        )
        assert all(call.args == (controller, state) for call in decide.call_args_list)
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    assert len(rows) == failures
    assert all(row["event"] == "controller_error" for row in rows)
    assert "secret" not in log.read_text()


@pytest.mark.parametrize("phase", [None, "final_answer"])
def test_codex_final_text_excludes_commentary_and_rejects_ambiguity(phase):
    from examples.run_ten_trial_campaign import codex_final_text

    commentary = {
        "type": "message",
        "phase": "commentary",
        "content": [{"type": "output_text", "text": "not the answer"}],
    }
    final = {
        "type": "message",
        "phase": phase,
        "content": [{"type": "output_text", "text": '{"aileron":"3"}'}],
    }
    assert codex_final_text({"output": [commentary, final]}) == '{"aileron":"3"}'
    for output in ([commentary], [final, final]):
        with pytest.raises(AssertionError):
            codex_final_text({"output": output})


def test_codex_stream_uses_final_answer_but_logs_all_channels(tmp_path):
    from types import SimpleNamespace

    from llm_openai_via_codex import CodexResponsesModel

    from examples.run_ten_trial_campaign import install_logging
    from flightbench.controllers import CodexController

    answer = '{"aileron":"3","elevator":"7","rudder":"3","throttle":"3"}'
    payload = {
        "output": [
            {
                "type": "message",
                "phase": "commentary",
                "content": [{"type": "output_text", "text": "commentary"}],
            },
            {
                "type": "message",
                "phase": "final_answer",
                "content": [{"type": "output_text", "text": answer}],
            },
        ]
    }
    completed = SimpleNamespace(
        type="response.completed",
        response=SimpleNamespace(model_dump=lambda **kw: payload),
        model_dump=lambda **kw: {"type": "response.completed", "response": payload},
    )
    log = tmp_path / "provider.jsonl"
    with (
        patch.object(CodexResponsesModel, "_build_kwargs", CodexResponsesModel._build_kwargs),
        patch.object(CodexResponsesModel, "_handle_event", return_value="stream chunk") as event,
        patch.object(
            CodexResponsesModel, "_get_client_kwargs", CodexResponsesModel._get_client_kwargs
        ),
        patch.object(CodexController, "decide", CodexController.decide),
    ):
        install_logging(log, "codex")
        model = object.__new__(CodexResponsesModel)
        response = object()
        assert (
            model._handle_event(SimpleNamespace(type="response.output_text.delta"), response)
            is None
        )
        assert model._handle_event(completed, response) == answer
        event.assert_called_with(model, completed, response)
    assert json.loads(log.read_text())["response"]["response"] == payload
