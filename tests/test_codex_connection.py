import sys
from types import SimpleNamespace

import pytest

from flightbench import controllers


def test_codex_auth_check_is_quiet_and_bounded(monkeypatch):
    captured = {}

    def run(command, **kwargs):
        captured.update(command=command, **kwargs)
        return SimpleNamespace(returncode=0, stdout="Logged in using ChatGPT", stderr="")

    monkeypatch.setattr(controllers.shutil, "which", lambda _name: "/usr/local/bin/codex")
    monkeypatch.setattr(controllers.subprocess, "run", run)

    assert controllers._codex_authenticated() is True
    assert captured["command"] == ["codex", "login", "status"]
    assert captured["capture_output"] is True
    assert captured["text"] is True
    assert captured["timeout"] == 5

    monkeypatch.setattr(
        controllers.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0, stdout="Logged in using an API key", stderr=""
        ),
    )
    assert controllers._codex_authenticated() is False


def test_model_discovery_does_not_advertise_fallback_models_when_logged_out(monkeypatch):
    monkeypatch.setattr(controllers, "_codex_authenticated", lambda: False)
    monkeypatch.setattr(controllers, "_import_llm", lambda: None)

    assert controllers.discover_models() == []


def test_selected_model_is_rejected_before_first_flight_when_logged_out(monkeypatch):
    fake_llm = SimpleNamespace(get_models=list, get_model=lambda _model: object())
    monkeypatch.setitem(sys.modules, "llm", fake_llm)
    monkeypatch.setattr(controllers, "_codex_authenticated", lambda: False)

    with pytest.raises(RuntimeError, match="No authenticated openai-codex models"):
        controllers.CodexController("openai-codex/gpt-test")
