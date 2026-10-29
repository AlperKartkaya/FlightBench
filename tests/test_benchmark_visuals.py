"""Recorded-data fidelity, mode-separated comparisons and self-contained theme exports."""

import csv
import json
import xml.etree.ElementTree as ET
from copy import deepcopy
from datetime import datetime
from itertools import pairwise
from pathlib import Path

import pytest

from examples.build_benchmark_visuals import (
    OUTPUT,
    THEMES,
    display_rows,
    figure_spec,
    load_rows,
)

SOURCE = OUTPUT / "results.json"
NS = {"s": "http://www.w3.org/2000/svg"}


def test_all_measurements_match_recorded_runs_and_csv():
    raw = SOURCE.read_bytes()
    selected = {g["selected"]["run_id"]: g for g in json.loads(raw)["groups"]}
    rows = [r for r in load_rows(SOURCE) if r["run_id"] in selected]
    assert len(rows) == 16
    assert len({r["run_id"] for r in rows}) == 16
    assert [sum(r["mode"] == mode for r in rows) for mode in ("lockstep", "realtime")] == [14, 2]
    with (OUTPUT / "benchmark-data.csv").open() as handle:
        exported = {r["run_id"]: r for r in csv.DictReader(handle)}
    assert len(exported) >= 16
    for row in rows:
        group = selected[row["run_id"]]
        run = group["selected"]
        assert row["mode"] == group["mode"]
        for field in ("score", "calls", "input_tokens", "output_tokens"):
            assert row[field] == run[field]
        assert row["api_cost_usd"] == run["cost_usd"]
        assert row["sim_time_s"] == run["diagnostics"]["duration_s"]
        assert row["mean_latency_s"] == run["diagnostics"]["mean_latency_ms"] / 1000
        assert (
            row["wall_time_s"]
            == (
                datetime.fromisoformat(run["finished_at"])
                - datetime.fromisoformat(run["started_at"])
            ).total_seconds()
        )
        for field, value in row.items():
            assert exported[row["run_id"]][field] == ("" if value is None else str(value))
    assert SOURCE.read_bytes() == raw


def test_bests_are_mode_specific_and_calculated_before_rounding():
    rows = load_rows(SOURCE)
    before = deepcopy(rows)
    displayed = display_rows(rows)
    for mode in ("lockstep", "realtime"):
        cohort = [r for r in displayed if r["mode"] == mode]
        best_score = [r for r in cohort if r["best_score"]]
        assert all(r["score"] == max(r["score"] for r in cohort) for r in best_score)
        cheapest = [r for r in cohort if r["best_cost"]]
        assert {r["model"] for r in cheapest} == {"Jev 1.13", "Jev 1.14"}
        fastest = [r for r in cohort if r["best_latency"]]
        assert {r["model"] for r in fastest} == {"Jev 1.13", "Jev 1.14"}
        assert all(r["cost_comparison"] == r["latency_comparison"] == "1×" for r in cheapest)
    realtime = [r for r in displayed if r["mode"] == "realtime"]
    assert realtime[0]["api_cost_usd"] is None
    assert realtime[0]["cost_text"] == "≥$0.0150"
    assert realtime[0]["cost"] == realtime[0]["cost_lower_bound_usd"]
    sol_xhigh = next(r for r in displayed if r["model"] == "GPT-6.1 Sol" and r["effort"] == "xhigh")
    assert sol_xhigh["cost_text"] == "$1.120"
    assert rows == before


def test_only_current_positive_local_results_are_eligible():
    rows = load_rows(SOURCE)
    assert not any("historical" in r["mode"].lower() or "V1" in r["family"] for r in rows)
    assert all(r["score"] > 0 for r in rows if r["family"] == "Local")
    for theme in THEMES:
        spec = json.dumps(figure_spec(rows, theme))
        assert "HISTORICAL" not in spec and "V1" not in spec and "V2" not in spec


@pytest.mark.parametrize("damage", ["missing", "duplicate", "nan", "zero_cost"])
def test_invalid_data_fails_instead_of_silently_dropping_points(tmp_path, damage):
    data = json.loads(SOURCE.read_text())
    if damage == "missing":
        data["groups"].pop()
    elif damage == "duplicate":
        data["groups"][-1] = data["groups"][0]
    elif damage == "nan":
        data["groups"][0]["selected"]["score"] = float("nan")
    else:
        data["groups"][0]["selected"]["cost_usd"] = 0
    path = tmp_path / "results.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_rows(path)


def test_chart_modes_encodings_and_theme_layouts_are_equivalent():
    rows = load_rows(SOURCE)
    for theme in THEMES:
        spec = figure_spec(rows, theme)
        assert len(spec["vconcat"]) == 3
        assert spec["title"]["anchor"] == "middle"
        assert "subtitle" not in spec["title"]
        assert "COST–PERFORMANCE" not in json.dumps(spec)
        for panel, mode in zip(spec["vconcat"][1:3], ("lockstep", "realtime")):
            count = sum(r["mode"] == mode for r in rows)
            labels = panel["hconcat"][0]["data"]["values"]
            assert len(labels) == count
            assert all(row["mode"] == mode for row in labels)
        for panel in spec["vconcat"][1:]:
            assert len(panel["hconcat"]) == 6
            assert [panel["hconcat"][i]["title"]["text"] for i in (3, 5)] == ["COMPARISON"] * 2
        assert '"url":' not in json.dumps(spec)


def test_svg_theme_parity_safety_and_readme_references():
    parsed = []
    for theme in THEMES:
        path = OUTPUT / f"benchmark-{theme}.svg"
        assert path.stat().st_size < 150_000
        root = ET.parse(path).getroot()
        texts = root.findall(".//s:text", NS)
        values = ["".join(node.itertext()) for node in texts]
        for row in display_rows(load_rows(SOURCE)):
            assert row["label"] in values
            assert row["score_text"] in values
            assert row["cost_text"] in values
            assert row["latency_text"] in values
        for tag in ("script", "image", "foreignObject"):
            assert root.find(f".//s:{tag}", NS) is None
        for node in root.iter():
            assert not any(k.lower().startswith("on") for k in node.attrib)
            assert not any(k.endswith("href") for k in node.attrib)
        assert any(
            node.text
            == f"{max(r['score'] for r in load_rows(SOURCE) if r['mode'] == 'lockstep'):.3f}"
            and node.get("font-weight") == "700"
            for node in texts
        )
        parsed.append(
            (root.get("viewBox"), values, [node.get("d") for node in root.findall(".//s:path", NS)])
        )
    assert parsed[0] == parsed[1]
    readme = (Path(__file__).parents[1] / "README.md").read_text()
    for theme in THEMES:
        assert f"benchmark-{theme}.svg#gh-{theme}-mode-only" in readme
    benchmark = readme.split("## Benchmark results — landing score and API cost", 1)[1].split(
        "## Landing score calculation", 1
    )[0]
    assert "| Controller |" not in benchmark
    assert (OUTPUT / "benchmark-data.csv").exists() and SOURCE.exists()
    assert "Bold/green" not in benchmark


def test_text_palette_contrast():
    def luminance(color):
        rgb = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in rgb]
        return sum(v * weight for v, weight in zip(linear, (0.2126, 0.7152, 0.0722)))

    for palette in THEMES.values():
        for color in [palette["fg"], palette["muted"], palette["best"], *palette["families"]]:
            low, high = sorted((luminance(color), luminance(palette["bg"])))
            assert (high + 0.05) / (low + 0.05) >= 4.5


def test_renderer_reproduces_committed_theme_assets():
    vlc = pytest.importorskip("vl_convert")
    rows = load_rows(SOURCE)
    for theme in THEMES:
        fresh = vlc.vegalite_to_svg(figure_spec(rows, theme), vl_version="6.4") + "\n"
        # Vega assigns new clip-path IDs per conversion; compare data-bearing text instead.
        expected = ET.parse(OUTPUT / f"benchmark-{theme}.svg").getroot()
        actual = ET.fromstring(fresh)
        assert expected.get("viewBox") == actual.get("viewBox")
        assert [e.text for e in expected.findall(".//s:text", NS)] == [
            e.text for e in actual.findall(".//s:text", NS)
        ]


def test_models_have_half_row_spacing_without_changing_metrics():
    rows = load_rows(SOURCE)
    before = deepcopy(rows)
    for theme in THEMES:
        spec = figure_spec(rows, theme)
        for panel in spec["vconcat"][1:]:
            columns = panel["hconcat"]
            assert columns[1]["layer"][0]["mark"]["orient"] == "horizontal"
            data = columns[0]["data"]["values"]
            for previous, current in pairwise(data):
                expected = 30 if previous["family"] == current["family"] else 45
                assert current["row_y"] - previous["row_y"] == expected
            assert all(column["data"]["values"] == data for column in columns)
            assert columns[0]["height"] == data[-1]["row_y"] + 15
    assert rows == before
