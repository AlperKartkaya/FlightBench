import json

import pytest

from examples import run_local_campaign as campaign


def test_existing_seed42_is_strictly_validated_for_all_six_models():
    assert len(campaign._models()) == 6
    for model in campaign._models():
        metadata, model_name = campaign._metadata(model)
        episode = campaign.validate_trial(
            campaign.OLD / model.old_slug / "submission.json", 42, model_name
        )
        assert episode["config"]["mode"] == "lockstep"
        assert episode["diagnostics"]["api_errors"] == 0
        assert metadata["model"] == model_name


def test_metadata_reuses_controller_identity_but_updates_campaign():
    metadata, model_name = campaign._metadata(campaign._models()[0])
    assert model_name == "kev-0.8b-v1.0"
    assert metadata["controller_type"] == "ai"
    assert metadata["campaign"]["seeds"] == [42, 101, 202]
    assert metadata["campaign"]["model_parallelism"] == 1


def test_pinned_model_file_verification_uses_manifest_hashes(monkeypatch, tmp_path):
    model_file = tmp_path / "scratch/von-runtime/model/model.bin"
    model_file.parent.mkdir(parents=True)
    model_file.write_bytes(b"pinned")
    monkeypatch.setattr(campaign, "ROOT", tmp_path)
    model = campaign.Model("von", "unused", 1, "/", (), {})
    campaign._verify_model(
        model,
        {"files": {"model.bin": {"sha256": campaign._sha256(model_file), "bytes": 6}}},
    )
    model_file.write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed"):
        campaign._verify_model(model, {"files": {"model.bin": {"sha256": "0" * 64, "bytes": 7}}})


def test_invalid_existing_work_is_archived_before_retry(monkeypatch, tmp_path):
    monkeypatch.setattr(campaign, "WORK", tmp_path)
    model = campaign._models()[0]
    current = tmp_path / "current" / model.name / "101"
    current.mkdir(parents=True)
    (current / "partial.log").write_text("keep")
    fresh = campaign._fresh_work(model, 101)
    assert fresh.is_dir() and not any(fresh.iterdir())
    archives = list((tmp_path / "interrupted").iterdir())
    assert len(archives) == 1
    assert (archives[0] / "partial.log").read_text() == "keep"


def test_atomic_status_write_leaves_valid_json(tmp_path):
    path = tmp_path / "status.json"
    campaign._write(path, {"state": "running", "models": {}})
    assert json.loads(path.read_text()) == {"state": "running", "models": {}}
    assert not path.with_suffix(".json.tmp").exists()


def test_publish_refuses_uncompressed_artifact(monkeypatch, tmp_path):
    model = campaign._models()[0]
    source = tmp_path / "source"
    source.mkdir()
    (source / "submission.json").write_text("{}")
    monkeypatch.setattr(campaign, "validate_trial", lambda *_: {})
    monkeypatch.setattr(campaign, "NEW", tmp_path / "published")
    monkeypatch.setattr(
        campaign,
        "json",
        type("JSON", (), {"loads": staticmethod(lambda _: {"artifacts": [{"path": "run.json"}]})}),
    )
    (source / "run.json").write_text("{}")
    with pytest.raises(ValueError, match="compressed"):
        campaign._publish(source, model, 101, "kev-0.8b-v1.0")


def test_lock_prevents_a_duplicate_queue(monkeypatch, tmp_path):
    monkeypatch.setattr(campaign, "WORK", tmp_path)
    (tmp_path / "runner.lock").write_text("123")
    with pytest.raises(RuntimeError, match="already active"):
        campaign.run_campaign()


def test_stop_terminates_only_the_owned_process_group(monkeypatch):
    calls = []

    class Process:
        pid = 123
        waits = 0

        def poll(self):
            return None

        def wait(self, timeout=None):
            self.waits += 1
            if self.waits == 1:
                raise campaign.subprocess.TimeoutExpired("test", timeout)

    monkeypatch.setattr(campaign.os, "killpg", lambda pid, sig: calls.append((pid, sig)))
    campaign._stop(Process())
    assert calls == [(123, campaign.signal.SIGTERM), (123, campaign.signal.SIGKILL)]


def test_invalid_export_never_replaces_existing_publication(monkeypatch, tmp_path):
    model = campaign._models()[0]
    source = tmp_path / "source"
    source.mkdir()
    (source / "submission.json").write_text("invalid")
    published = tmp_path / "published" / "submission.json"
    published.parent.mkdir()
    published.write_text("keep")
    monkeypatch.setattr(campaign, "_published", lambda *_: published)
    monkeypatch.setattr(
        campaign, "validate_trial", lambda *_: (_ for _ in ()).throw(ValueError("invalid"))
    )
    with pytest.raises(ValueError, match="invalid"):
        campaign._publish(source, model, 101, "kev-0.8b-v1.0")
    assert published.read_text() == "keep"


def test_existing_publication_is_archived_before_valid_replacement(monkeypatch, tmp_path):
    model = campaign._models()[0]
    source = tmp_path / "source"
    source.mkdir()
    artifact = source / "run.json.gz"
    artifact.write_bytes(b"new")
    (source / "submission.json").write_text(json.dumps({"artifacts": [{"path": artifact.name}]}))
    published = tmp_path / "published" / "submission.json"
    published.parent.mkdir(parents=True)
    published.write_text("old evidence")
    monkeypatch.setattr(campaign, "WORK", tmp_path / "work")
    monkeypatch.setattr(campaign, "_published", lambda *_: published)
    monkeypatch.setattr(campaign, "validate_trial", lambda *_: {})
    campaign._publish(source, model, 101, "kev-0.8b-v1.0")
    archives = list((campaign.WORK / "interrupted").iterdir())
    assert len(archives) == 1
    assert (archives[0] / "submission.json").read_text() == "old evidence"
    assert published.read_text() != "old evidence"


def test_warmup_stop_terminates_owned_process(monkeypatch, tmp_path):
    stopped = []

    class Process:
        returncode = None

        def poll(self):
            return None

    process = Process()
    monkeypatch.setattr(campaign.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(campaign, "_stop", lambda value: stopped.append(value))
    assert not campaign._warmup({}, "model", 101, tmp_path / "warmup.json", lambda: True)
    assert stopped == [process, process]


def test_wrong_model_cannot_satisfy_a_resume_slot():
    model = campaign._models()[0]
    with pytest.raises(ValueError, match="wrong local controller/model"):
        campaign.validate_trial(
            campaign.OLD / model.old_slug / "submission.json", 42, "different-model"
        )


def test_resumed_success_is_recorded_once_and_errors_return_nonzero():
    status = {"successful": []}
    outcome = {"success": True, "quality": 75.0, "status": "landed"}
    campaign._remember_success(status, "kev", 101, outcome)
    campaign._remember_success(status, "kev", 101, outcome)
    assert status["successful"] == [{"model": "kev", "seed": 101, "outcome": outcome}]
    assert campaign._completion(False, True) == ("complete_with_errors", 1)
    assert campaign._completion(True, False) == ("interrupted", 130)


def test_background_job_is_one_shot_and_logs_are_in_scratch():
    job = campaign.background_job()
    assert job["KeepAlive"] is False
    assert job["RunAtLoad"] is True
    assert job["ProgramArguments"] == [
        str(campaign.PYTHON),
        str(campaign.Path(campaign.__file__).resolve()),
    ]
    assert job["WorkingDirectory"] == str(campaign.ROOT)
    assert campaign.Path(job["StandardOutPath"]).is_relative_to(campaign.WORK)


def test_completed_queue_does_not_load_models(monkeypatch, tmp_path):
    model = campaign._models()[0]
    monkeypatch.setattr(campaign, "WORK", tmp_path)
    monkeypatch.setattr(campaign, "_models", lambda: (model,))
    monkeypatch.setattr(campaign, "_metadata", lambda _: ({}, "test-model"))
    monkeypatch.setattr(campaign, "validate_trial", lambda *args: {"outcome": {"success": False}})
    monkeypatch.setattr(campaign, "_verify_model", lambda *args: pytest.fail("No pending flight"))

    class Awake:
        def poll(self):
            return 0

    def popen(command, **kwargs):
        assert command[0] == "/usr/bin/caffeinate"
        return Awake()

    monkeypatch.setattr(campaign.subprocess, "Popen", popen)
    assert campaign.run_campaign() == 0
    assert json.loads((tmp_path / "status.json").read_text())["state"] == "complete"
