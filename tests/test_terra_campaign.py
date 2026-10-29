"""Bounded retry policy and publication without partial cohorts."""

import json
from copy import deepcopy

import pytest

from examples.build_benchmark_visuals import OUTPUT
from examples.build_v2_publication import _svg
from examples.run_terra_campaign import repeat_cohort
from examples.update_benchmark_additions import additions


def test_retry_only_after_all_three_failed():
    records = [{"config": {"seed": s}, "outcome": {"success": False}} for s in (42, 101, 202)]
    assert repeat_cohort(records)
    records[1]["outcome"]["success"] = True
    assert not repeat_cohort(records)
    with pytest.raises(ValueError):
        repeat_cohort(records[:2])


def test_local_evidence_and_no_partial_terra_publication():
    data = additions()
    assert data["local"] == []
    assert len(data["local_provenance"]) == 18
    for group in data["groups"]:
        assert group["model"] == "gpt-6.1-terra"
        assert group["reasoning_effort"] in ("low", "medium", "high", "xhigh")
        assert all(len(c["trials"]) == 3 for c in group["cohorts"])


def test_old_plot_accepts_partial_terra_efforts():
    groups = json.loads((OUTPUT / "results.json").read_text())["groups"]
    terra = deepcopy(groups[0])
    terra.update(model="gpt-6.1-terra", reasoning_effort="low")
    svg = _svg(groups + [terra])
    assert "GPT-6.1 Terra" in svg and "<circle" in svg


def test_additions_wait_for_completed_retry_and_choose_highest(monkeypatch, tmp_path):
    from examples import update_benchmark_additions as update
    from tests.test_v2_publication import episode

    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "source.json").write_text(json.dumps({"identity": {"source_hash": "test"}}))
    monkeypatch.setattr(update, "EVIDENCE", evidence)
    monkeypatch.setattr(update, "DATA", tmp_path / "trials")
    monkeypatch.setattr(update, "EFFORTS", ("low",))

    def fake_read(folder, effort, seed, identity):
        retry = folder.parent.name == "cohort-2"
        return episode(
            "gpt-6.1-terra",
            effort,
            seed,
            seed / 10 + 30 * retry,
            status="landed" if retry else "runway_excursion",
        )

    monkeypatch.setattr(update, "read_trial", fake_read)
    for cohort in (1, 2):
        for seed in (42, 101, 202):
            assert update.additions()["groups"] == []
            folder = update.DATA / "low" / f"cohort-{cohort}" / str(seed)
            folder.mkdir(parents=True)
            (folder / "submission.json").write_text("{}")
    result = update.additions()
    assert result["groups"][0]["selected"]["score"] == 50.2
    assert len(result["groups"][0]["cohorts"]) == 2
    json.dumps(result, allow_nan=False)


def test_provider_failure_does_not_block_local_publication(monkeypatch, tmp_path):
    from examples import update_benchmark_additions as update

    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "source.json").write_text(json.dumps({"identity": {"source_hash": "test"}}))
    monkeypatch.setattr(update, "EVIDENCE", evidence)
    monkeypatch.setattr(update, "DATA", tmp_path / "trials")
    monkeypatch.setattr(update, "EFFORTS", ("low",))
    for seed in (42, 101, 202):
        folder = update.DATA / "low" / "cohort-1" / str(seed)
        folder.mkdir(parents=True)
        (folder / "submission.json").write_text("{}")

    def failed_read(*args):
        raise RuntimeError("Infrastructure failure")

    monkeypatch.setattr(update, "read_trial", failed_read)
    result = update.additions()
    assert result["groups"] == [] and len(result["local_provenance"]) == 18


def test_positive_current_local_result_is_included_without_version_label(monkeypatch):
    from examples import update_benchmark_additions as update

    original = update.validate_trial

    def positive_trial(path, seed, model):
        record = original(path, seed, model)
        if "nimble" in model.lower() and seed == 42:
            record["outcome"].update(quality=12.5, success=True, status="landed")
        return record

    monkeypatch.setattr(update, "validate_trial", positive_trial)
    data = update.additions()
    assert len(data["local"]) == 1
    row = data["local"][0]
    assert row["score"] == 12.5 and row["family"] == "Local" and row["mode"] == "lockstep"
    assert row["api_cost_usd"] is None


def test_successful_landing_retry_updates_all_selected_metrics():
    from examples.build_v2_publication import select_groups
    from examples.update_benchmark_additions import with_landing_retries
    from tests.test_v2_publication import episode

    initial = [
        episode(
            "gpt-6.1-terra",
            "high",
            s,
            53 if s == 42 else 0,
            status="landed" if s == 42 else "runway_excursion",
        )
        for s in (42, 101, 202)
    ]
    cohort = select_groups(initial, expected_groups=(("gpt-6.1-terra", "high"),))[0]
    group = {**cohort, "cohorts": [cohort]}
    retry = episode("gpt-6.1-terra", "high", 101, 81, costlier=True)
    retry["run_id"] = "new-landing"
    result = with_landing_retries(group, [retry])
    assert result["selected_run_id"] == "new-landing"
    assert result["selected"]["score"] == 81
    assert result["selected"]["cost_usd"] > group["selected"]["cost_usd"]
    assert group["selected"]["seed"] == 42
    assert len(result["landing_retries"]) == 1
    failed = deepcopy(retry)
    failed["outcome"].update(success=False, status="runway_excursion", quality=99)
    assert with_landing_retries(group, [failed])["selected_run_id"] == group["selected_run_id"]
    lower = deepcopy(retry)
    lower["outcome"]["quality"] = 20
    assert with_landing_retries(group, [lower])["selected_run_id"] == group["selected_run_id"]
    for records in ([retry, retry], [initial[0]]):
        with pytest.raises(ValueError):
            with_landing_retries(group, records)


def test_terra_order_and_gold_marker():
    from examples.build_benchmark_visuals import FAMILIES, load_rows

    assert (
        FAMILIES.index("GPT-6 Luna")
        < FAMILIES.index("GPT-6.1 Terra")
        < FAMILIES.index("GPT-6.1 Sol")
    )
    rows = load_rows(OUTPUT / "results.json")
    families = [r["family"] for r in rows if r["mode"] == "lockstep"]
    assert (
        families.index("GPT-6 Luna")
        < families.index("GPT-6.1 Terra")
        < families.index("GPT-6.1 Sol")
    )
    groups = json.loads((OUTPUT / "results.json").read_text())["groups"]
    groups += json.loads((OUTPUT / "additional-results.json").read_text())["groups"]
    svg = _svg(groups)
    assert '<g fill="#c27b1b" stroke="white" stroke-width="1.5"><title>GPT-6.1 Terra' in svg
    assert 'paint-order="stroke"' in svg
