from examples.controllers.bison import BisonController


def test_bison_identity_and_transport(tmp_path, monkeypatch):
    monkeypatch.setenv("FLIGHTBENCH_DECISION_LOG", str(tmp_path / "provider.jsonl"))
    controller = BisonController()
    assert controller.model_id == controller.metadata["model"] == "bison-1"
    assert controller.metadata["slug"] == "bison-1"
    assert controller.metadata["name"] == "Bison 1 (31B)"
    assert controller.metadata["model_revision"] == "bf8350b2c59eb6c36e95d02a2af870aec18724a7"
    assert "GLiDE" not in str(controller.metadata)
    assert controller.endpoint == "http://127.0.0.1:8000/v1/systemone"
    assert controller.metadata["quantized"] is False
    assert "unverified" in controller.metadata["provenance_limit"]
