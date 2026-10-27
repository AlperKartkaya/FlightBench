import json
import xml.etree.ElementTree as ET
from pathlib import Path

from flightbench.leaderboard import build_leaderboard


def test_publication_exposes_conditions_and_decision_flow_without_ranking_legacy(tmp_path):
    root = Path(__file__).parents[1]
    result = build_leaderboard(
        root / "leaderboard/submissions",
        tmp_path,
        root / "leaderboard/historical/manifest.json",
        root / "leaderboard/verified.json",
    )

    kev = next(row for row in result["rows"] if row["controller"] == "Kev 0.8B v1.0")
    assert kev["evaluation"] == {
        "seeds": [42, 101, 202, 303, 404],
        "modes": ["lockstep", "realtime"],
        "scenario": "easy",
        "decision_hz": 2,
        "time_scale_by_mode": {"lockstep": 1.0, "realtime": 1.0},
        "realtime_response_policy": "discard-stale",
        "scoring_version": "v1",
        "scoring_config_sha256": None,
    }
    assert kev["realtime"]["decision_flow"] == {
        "completed": 63,
        "recorded": 63,
        "started": None,
        "outstanding": None,
        "errors": 0,
        "applied": 0,
        "stale": 63,
        "late": 63,
        "zero_applied_runs": 5,
        "effective_applied_rate_hz": 0.0,
        "rate_basis": "applied decisions / simulation seconds",
    }
    assert kev["protocol"] == "flightbench-v1"
    assert kev["source_identity"]["source_hash"].startswith("sha256:")
    assert "Apple M1 Pro" in kev["execution_cohort"]["label"]

    readme = (tmp_path / "README.md").read_text()
    assert "repeated executions of the same physical initialization" in readme
    assert "no successful landing" in readme
    assert "simulation-time basis" in readme
    assert "legacy/reference (pre-v1; not comparable to canonical v1)" in readme
    assert "decision-diagnostics.md" in readme

    rendered = json.loads((tmp_path / "leaderboard.json").read_text())
    assert rendered == result["rows"]
    for path in tmp_path.glob("*.svg"):
        ET.parse(path)
        text = path.read_text()
        assert "legacy/reference" in text
        assert "not plotted" in text.lower()
    best = (tmp_path / "best-of.svg").read_text()
    assert "not a cross-cohort ranking" in best
    assert "no successful landing" in best
    assert "Jev: 0.01224" not in best
    outcome_labels = ET.fromstring(best).findall(
        ".//{http://www.w3.org/2000/svg}text[@class='outcome-label']"
    )
    assert outcome_labels
    assert all(float(label.attrib["x"]) == 218 for label in outcome_labels)
    for label in outcome_labels:
        assert label.find("{http://www.w3.org/2000/svg}title") is not None
    assert (
        "No recorded evidence for this axis/mode; not plotted: different/legacy cohort"
        not in (tmp_path / "realtime-latency-score.svg").read_text()
    )


def test_different_sources_are_not_one_plotted_cohort(tmp_path):
    from flightbench.leaderboard import build_submission
    from tests.test_leaderboard import METADATA, episode, write_records

    for i in (1, 2):
        record = episode(str(i), "lockstep", 42, 0)
        record["source_identity"]["source_hash"] = "sha256:" + str(i) * 64
        build_submission(
            [record],
            METADATA,
            write_records(tmp_path, [record]),
            tmp_path / "submissions" / str(i) / "submission.json",
        )
    rows = build_leaderboard(tmp_path / "submissions", tmp_path / "output")["rows"]
    assert rows[0]["comparison_cohort"]["id"] != rows[1]["comparison_cohort"]["id"]
