import json
import shutil
import xml.etree.ElementTree as ET
from copy import deepcopy
from types import SimpleNamespace

import pytest

from examples.build_v2_publication import (
    CANONICAL_SCORING,
    CANONICAL_SCORING_CONFIG_SHA256,
    EXPECTED_GROUPS,
    select_groups,
    write_publication,
)


def episode(model, effort, seed, score, *, status="landed", costlier=False):
    controller = "jev" if model.startswith("jev-") else "codex"
    usage = {"input_tokens": 1000 + 100 * costlier, "output_tokens": 10}
    if controller == "codex":
        usage["input_tokens_details"] = {
            "cached_tokens": 100,
            "cache_write_tokens": 200,
            "cache_write_tokens_details": {"ttl_30m_tokens": 50, "ttl_12h_tokens": 150},
        }
    return {
        "run_id": f"{model}-{effort}-{seed}",
        "config": {
            "controller": controller,
            "model": model,
            "reasoning_effort": effort or "low",
            "seed": seed,
            "mode": "lockstep",
            "scoring_version": "v2",
            "scoring_config_sha256": CANONICAL_SCORING_CONFIG_SHA256,
        },
        "outcome": {"quality": score, "success": status == "landed", "status": status},
        "diagnostics": {"calls": 1, "usage_unknown_requests": 0},
        "decisions": [{"decision_info": {"usage": usage}}],
        "final_state": {"result": {"scoring": deepcopy(CANONICAL_SCORING)}},
    }


def campaign():
    episodes = []
    for model, effort in EXPECTED_GROUPS:
        episodes += [
            episode(model, effort, 42, 40, costlier=True),
            episode(model, effort, 101, 60),
            episode(model, effort, 202, 50),
        ]
    return episodes


def fake_submission(model, effort, *, source_hash="same"):
    slug = f"{model}-{effort or 'jev'}"
    artifacts = [
        SimpleNamespace(sha256=f"sha-{slug}-{seed}", path=f"{slug}-{seed}.json")
        for seed in (42, 101, 202)
    ]
    return SimpleNamespace(
        controller=SimpleNamespace(
            model=model,
            metadata={"reasoning_effort": effort} if effort else {},
        ),
        flightbench=SimpleNamespace(source_hash=source_hash),
        evaluation=SimpleNamespace(
            scoring_version="v2",
            scoring_config_sha256=CANONICAL_SCORING_CONFIG_SHA256,
            modes=["lockstep"],
        ),
        runs=[SimpleNamespace(artifact_sha256=artifact.sha256) for artifact in artifacts],
        artifacts=artifacts,
    )


def test_selects_highest_score_not_cheapest_and_lower_seed_breaks_ties():
    episodes = campaign()
    episodes[0]["outcome"]["quality"] = 70
    episodes[1]["outcome"]["quality"] = 70
    episodes[5]["outcome"]["quality"] = 80
    groups = select_groups(episodes)
    assert groups[0]["selected_run_id"].endswith("-42")
    assert groups[1]["selected"]["seed"] == 202
    assert groups[0]["selected"]["cost_usd"] == pytest.approx(0.002585)
    assert groups[1]["selected"]["cost_usd"] == pytest.approx(0.002385)
    assert all("cost_usd" not in trial for trial in groups[0]["trials"])
    assert len(groups) == 14 and all(len(group["trials"]) == 3 for group in groups)


def test_incomplete_trials_are_not_ranked_and_missing_groups_fail():
    episodes = campaign()
    episodes[0]["outcome"].update(quality=99, status="controller_error", success=False)
    episodes[1]["outcome"].update(quality=98, status="controller_timeout", success=False)
    with pytest.raises(ValueError, match="three completed flights"):
        select_groups(episodes)
    episodes[0]["outcome"]["status"] = "landed"
    with pytest.raises(ValueError, match="three completed flights"):
        select_groups(episodes)
    with pytest.raises(ValueError, match="requested fixed V2 groups"):
        select_groups(episodes[:-3])


def test_selected_cost_requires_complete_actual_usage():
    episodes = campaign()
    episodes[1]["decisions"][0]["decision_info"]["usage"].pop("output_tokens")
    selected = select_groups(episodes)[0]["selected"]
    assert selected["seed"] == 101
    assert selected["cost_usd"] is None
    assert selected["full_actual_usage"] is False


def test_rejects_custom_scoring_configuration():
    episodes = campaign()
    episodes[0]["final_state"]["result"]["scoring"]["max_sink_mps"] = 99
    with pytest.raises(ValueError, match="canonical scoring configuration"):
        select_groups(episodes)


@pytest.mark.skipif(not shutil.which("rsvg-convert"), reason="native PNG renderer not installed")
def test_writes_table_json_and_clean_svg_png(tmp_path):
    groups = select_groups(campaign())
    write_publication(groups, tmp_path)
    readme = (tmp_path / "README.md").read_text()
    assert all(name in readme for name in ("GPT-6.1 Sol", "GPT-6 Astra", "GPT-6 Luna", "Jev 1.14"))
    assert "highest-scoring completed flight" in readme
    assert "| max |" not in readme
    payload = json.loads((tmp_path / "results.json").read_text())
    assert len(payload["groups"]) == 14
    assert all(len(group["trials"]) == 3 for group in payload["groups"])
    svg_path = tmp_path / "landing-score-vs-api-cost.svg"
    ET.parse(svg_path)
    svg = svg_path.read_text()
    assert svg.count("<polyline") == 3
    assert all(name in svg for name in ("GPT-6 Luna", "Jev 1.13", "Jev 1.14"))
    assert ">max<" not in svg
    assert "1. GPT" not in svg
    assert (
        (tmp_path / "landing-score-vs-api-cost.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    )


@pytest.mark.skipif(not shutil.which("rsvg-convert"), reason="native PNG renderer not installed")
def test_publication_discloses_archived_infrastructure_retries(tmp_path):
    history = {"excluded_attempts": [{"seed": 42, "status": "controller_timeout"}]}
    write_publication(select_groups(campaign()), tmp_path, attempt_history=history)
    assert json.loads((tmp_path / "results.json").read_text())["attempt_history"] == history
    readme = (tmp_path / "README.md").read_text()
    assert "1 interrupted controller/infrastructure attempts" in readme
    assert "not a claim of only three total attempts" in readme


def test_publication_rejects_mixed_source_cohorts(monkeypatch, tmp_path):
    from examples import build_v2_publication as publication

    loaded = [
        (tmp_path / str(i), fake_submission(model, effort, source_hash=str(i % 2)))
        for i, (model, effort) in enumerate(EXPECTED_GROUPS)
    ]
    monkeypatch.setattr(publication, "load_submissions", lambda _: loaded)
    with pytest.raises(ValueError, match="one benchmark source hash"):
        publication._load_episodes(tmp_path / "2026-10-22" / "submissions")


def test_load_ignores_archived_max_submissions_but_rejects_other_groups(monkeypatch, tmp_path):
    from examples import build_v2_publication as publication

    loaded = [
        (tmp_path / f"required-{i}" / "submission.json", fake_submission(model, effort))
        for i, (model, effort) in enumerate(EXPECTED_GROUPS)
    ]
    loaded += [
        (
            tmp_path / f"archived-max-{i}" / "submission.json",
            fake_submission(model, "max", source_hash="excluded-source"),
        )
        for i, model in enumerate(("gpt-6.1-sol", "gpt-6-astra", "gpt-6-luna", "gpt-6-sol"))
    ]
    records = {
        artifact.path: episode(model, effort, seed, 50)
        for model, effort in EXPECTED_GROUPS
        for seed, artifact in zip(
            (42, 101, 202), fake_submission(model, effort).artifacts, strict=True
        )
    }
    monkeypatch.setattr(publication, "load_submissions", lambda _: loaded)
    monkeypatch.setattr(publication, "_read_artifact", lambda path: records[path.name])
    episodes = publication._load_episodes(tmp_path / "2026-10-22" / "submissions")
    assert len(episodes) == 42
    assert all(item["config"]["reasoning_effort"] != "max" for item in episodes)

    loaded.append(
        (tmp_path / "unexpected" / "submission.json", fake_submission("gpt-other", "low"))
    )
    with pytest.raises(ValueError, match="Unexpected V2 publication submission group"):
        publication._load_episodes(tmp_path / "2026-10-22" / "submissions")


def test_realtime_groups_remain_separate_and_incomplete_cost_is_lower_bound():
    models = (("jev-1.13.0", None), ("jev-1.14.0", None))
    records = [
        episode(model, effort, seed, seed / 10)
        for model, effort in models
        for seed in (42, 101, 202)
    ]
    for record in records:
        record["config"]["mode"] = "realtime"
        record["diagnostics"]["usage_unknown_requests"] = 1
    groups = select_groups(records, mode="realtime", expected_groups=models)
    assert len(groups) == 2
    assert all(g["mode"] == "realtime" for g in groups)
    assert all(g["selected"]["cost_usd"] is None for g in groups)
    assert all(g["selected"]["cost_lower_bound_usd"] > 0 for g in groups)
    with pytest.raises(ValueError, match="requested mode"):
        select_groups(records, expected_groups=models)


def test_plot_retains_original_family_symbols_and_realtime_cost_uncertainty():
    from examples.build_v2_publication import _svg

    groups = select_groups(campaign())
    assert all(g["model"] != "gpt-6-sol" for g in groups)
    for g in groups[-2:]:
        g["mode"] = "realtime"
        g["selected"]["cost_usd"] = None
    next(g for g in groups if g["model"] == "gpt-6-luna" and g["reasoning_effort"] == "high")[
        "selection"
    ] = "user-selected successful seed42 retry"
    svg = _svg(groups)
    assert "high*" not in svg
    assert 'stroke-width="0.8"' not in svg
    assert "#000c8b" in svg and "#c27b1b" in svg
    assert "Jev 1.14 realtime" in svg
    assert "at least $" in svg
    assert "stroke-dasharray" not in svg
    assert "right arrow" not in svg.lower()
    assert "GPT-6 Sol" not in svg
    ns = {"s": "http://www.w3.org/2000/svg"}
    root = ET.fromstring(svg)
    labels = [t for t in root.findall("s:text", ns) if t.text in {"low", "med", "high", "xhigh"}]
    points = [
        tuple(map(float, point.split(",")))
        for line in root.findall("s:polyline", ns)
        for point in line.attrib["points"].split()
    ]
    assert len(labels) == len(points) == 12
    for label, (x, y) in zip(labels, points, strict=True):
        assert abs(float(label.attrib["x"]) - x) <= 22
        assert abs(float(label.attrib["y"]) - y) <= 35


def test_luna_replacement_requires_selected_successful_seed42(monkeypatch, tmp_path):
    from examples import build_v2_publication as publication
    from flightbench import leaderboard

    assert publication.luna_replacement(tmp_path) is None
    folder = tmp_path / "gpt-6-luna-high-landing-retry"
    folder.mkdir()
    (folder / "submission.json").write_text("{}")
    sub = fake_submission(
        "gpt-6-luna",
        "high",
        source_hash="sha256:ebbaf763d742e79e847f43f8f64f701ec923160f770960b0d6cecfe3c81fa128",
    )
    sub.artifacts = sub.artifacts[:1]
    records = {
        artifact.path: episode("gpt-6-luna", "high", seed, 70)
        for seed, artifact in zip((42,), sub.artifacts, strict=True)
    }
    monkeypatch.setattr(leaderboard, "validate_submission", lambda *args: sub)
    monkeypatch.setattr(publication, "_read_artifact", lambda path: records[path.name])
    result = publication.luna_replacement(tmp_path)
    assert result["selection"] == "user-selected successful seed42 retry"
    assert result["selected"]["seed"] == 42
    records[sub.artifacts[0].path]["outcome"]["success"] = False
    with pytest.raises(ValueError, match="successful landing"):
        publication.luna_replacement(tmp_path)


def test_jev_repeat_selects_new_best_separately_in_each_mode(monkeypatch, tmp_path):
    from examples import build_v2_publication as publication
    from flightbench import leaderboard

    sub = fake_submission(
        "jev-1.13.0",
        None,
        source_hash="sha256:ebbaf763d742e79e847f43f8f64f701ec923160f770960b0d6cecfe3c81fa128",
    )
    records = {}
    for mode in ("lockstep", "realtime"):
        folder = tmp_path / ("jev-1-13-0-" + mode)
        folder.mkdir()
        (folder / "submission.json").write_text("{}")
        for seed, artifact in zip((42, 101, 202), sub.artifacts, strict=True):
            row = episode(
                "jev-1.13.0", None, seed, 90 if seed == (42 if mode == "lockstep" else 202) else 60
            )
            row["config"].update(mode=mode, realtime_response_policy="apply-on-arrival")
            records[str(folder / artifact.path)] = row
    monkeypatch.setattr(leaderboard, "validate_submission", lambda *args: sub)
    monkeypatch.setattr(publication, "_read_artifact", lambda path: records[str(path)])
    groups = publication.jev113_replacements(tmp_path)
    assert [(g["mode"], g["selected"]["seed"]) for g in groups] == [
        ("lockstep", 42),
        ("realtime", 202),
    ]
    assert all("previous cohort archived" in g["selection"] for g in groups)
    assert len(publication.jev113_replacements(tmp_path, modes=("realtime",))) == 1
    sub.flightbench.source_hash = "unreviewed"
    with pytest.raises(ValueError, match="audited October 26 source"):
        publication.jev113_replacements(tmp_path)
