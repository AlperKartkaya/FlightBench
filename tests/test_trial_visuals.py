"""The README uses complete cohorts, not historical best-run selections."""

import csv
import xml.etree.ElementTree as ET

import pytest

from examples import build_trial_visuals
from examples.build_benchmark_visuals import display_rows, figure_spec, load_rows
from examples.build_trial_visuals import (
    A100,
    A100_FOLLOWUP,
    DECISION_REALTIME_MODELS,
    HISTORICAL_OUTPUT,
    MS_11_REALTIME,
    OUTPUT,
    ROOT,
    SOL_MODEL,
    SOURCE,
    THEMES,
    chart,
    decision_flight_cost,
    merge_rows,
    summarize,
)


@pytest.fixture
def trials():
    with SOURCE.open(newline="") as handle:
        return list(csv.DictReader(handle))


def test_cohorts_keep_modes_separate_and_average_only_successful_flights(trials):
    results = summarize(trials)
    a100_cohorts = {
        (t["mode"], t["model"]) for t in trials if t["campaign"] in (A100, A100_FOLLOWUP)
    }
    decision_cohorts = {
        (t["mode"], t["model"])
        for t in trials
        if t["campaign"] in (MS_11_REALTIME, *DECISION_REALTIME_MODELS)
    }
    assert len(results) == 17 + len(a100_cohorts) + len(decision_cohorts)
    assert all(
        mode == "realtime"
        and results[mode, model]["successful"] + results[mode, model]["failed"] == 10
        for mode, model in decision_cohorts
    )
    assert all(
        results[key]["successful"] + results[key]["failed"] == (1 if key[0] == "lockstep" else 10)
        for key in a100_cohorts
    )
    assert sum(mode == "realtime" for mode, _ in results) == (
        4 + len(decision_cohorts) + sum(mode == "realtime" for mode, _ in a100_cohorts)
    )
    assert results["realtime", "jev-1.13.0"] | {"mean_latency_s": None} == {
        "mean_latency_s": None,
        "successful": 7,
        "failed": 3,
        "best": 77.586,
        "average": pytest.approx(44.3002857143),
    }
    assert results["realtime", "jev-1.14.0"] | {"mean_latency_s": None} == {
        "mean_latency_s": None,
        "successful": 8,
        "failed": 2,
        "best": 79.302,
        "average": pytest.approx(53.4795),
    }
    assert results["lockstep", "jev-1.14.0"] | {"mean_latency_s": None} == {
        "mean_latency_s": None,
        "successful": 7,
        "failed": 3,
        "best": 79.825,
        "average": pytest.approx(75.1961428571),
    }
    assert results["lockstep", "gpt-6-luna"] | {"mean_latency_s": None} == {
        "mean_latency_s": None,
        "api_cost_usd": pytest.approx(0.0137289),
        "successful": 0,
        "failed": 10,
        "best": None,
        "average": None,
    }


def test_unfinished_a100_cohort_is_not_exported(tmp_path, monkeypatch):
    monkeypatch.setattr(build_trial_visuals, "ROOT", tmp_path)
    evidence = tmp_path / "docs/evaluations" / A100
    evidence.mkdir(parents=True)
    (evidence / "groundhog-1-status.json").write_text(
        '{"protocol":"one-lockstep-ten-realtime","state":"running",'
        '"groups":{"groundhog-1":[{"mode":"realtime","seed":42}]}}'
    )
    assert list(build_trial_visuals.a100_trials()) == []


def test_a100_followup_adds_only_verified_lockstep_rows(trials):
    followup = [t for t in trials if t["campaign"] == A100_FOLLOWUP]
    assert {(t["model"], t["mode"], t["status"], float(t["score"])) for t in followup} == {
        ("strands-decider-31B-gemma4-v2-2611", "lockstep", "landed", 74.504),
        ("kudhab", "lockstep", "landed", 67.141),
        ("karpo-decision-31B", "lockstep", "runway_excursion", 0.0),
    }
    rows = merge_rows(load_rows(HISTORICAL_OUTPUT / "results.json"), summarize(trials))
    assert all(row["family"] != "Local" for row in rows if row["mode"] == "realtime")
    by_name = {row["model"]: row for row in rows if row["mode"] == "lockstep"}
    assert by_name["Strands Decider v2 31B"]["trial_best"] == "74.50"
    assert by_name["Kudhab"]["trial_average"] == "67.14"
    assert by_name["Karpo Decision 31B"]["segments"][-1]["kind"] == "fail"


def test_unfinished_decision_realtime_cohort_is_not_exported(tmp_path, monkeypatch):
    campaign = next(iter(DECISION_REALTIME_MODELS))
    evidence = tmp_path / "docs/evaluations" / campaign
    evidence.mkdir(parents=True)
    (evidence / "status.json").write_text('{"state":"running","groups":{"current":[{}]}}')
    output = tmp_path / "trials.csv"
    monkeypatch.setattr(build_trial_visuals, "CAMPAIGNS", (campaign,))
    monkeypatch.setattr(build_trial_visuals, "ROOT", tmp_path)
    monkeypatch.setattr(build_trial_visuals, "SOURCE", output)
    build_trial_visuals.refresh_local()
    assert list(csv.DictReader(output.read_text().splitlines())) == []


@pytest.mark.parametrize(
    "damage",
    ["duplicate", "incomplete", "provider_error", "missing_sol_cost", "missing_decision_cost"],
)
def test_invalid_cohort_is_rejected(trials, damage):
    if damage == "duplicate":
        trials.append(trials[0])
    elif damage == "incomplete":
        trials.pop(0)
    elif damage == "missing_sol_cost":
        next(row for row in trials if row["model"] == SOL_MODEL)["api_cost_usd"] = ""
    elif damage == "missing_decision_cost":
        next(row for row in trials if row["model"] == "gemini-decision-1")["api_cost_usd"] = ""
    else:
        trials[0]["status"] = "controller_error"
    with pytest.raises(ValueError):
        summarize(trials)


def test_local_lockstep_cannot_count_an_extra_flight(trials):
    row = next(t for t in trials if t["model"] == "bison-1" and t["mode"] == "lockstep")
    trials.append(row | {"seed": 101, "run_id": "cbd2641b-b742-4f4f-af55-3b342fa2fefe"})
    with pytest.raises(ValueError, match="complete cohort"):
        summarize(trials)


def test_readme_assets_reproduce_with_realtime_first(trials):
    results = summarize(trials)
    rows = merge_rows(load_rows(HISTORICAL_OUTPUT / "results.json"), results)
    segment_kinds = [
        segment["kind"]
        for mode in ("realtime", "lockstep")
        for row in rows
        if row["mode"] == mode
        for segment in row["segments"]
    ]
    readme = (ROOT / "README.md").read_text()
    ns = {"s": "http://www.w3.org/2000/svg"}
    for theme in THEMES:
        path = OUTPUT / f"ten-trial-{theme}.svg"
        assert f"docs/benchmark/{path.name}#gh-{theme}-mode-only" in readme
        raw = path.read_text()
        svg = ET.fromstring(raw)
        labels = [" ".join(node.itertext()) for node in svg.findall(".//s:text", ns)]
        assert labels.index("REALTIME") < labels.index("LOCKSTEP")
        mode_titles = [
            node for node in svg.findall(".//s:text", ns) if node.text in ("REALTIME", "LOCKSTEP")
        ]
        assert [node.get("text-anchor") for node in mode_titles] == ["middle", "middle"]
        assert [node.get("font-size") for node in mode_titles] == ["17px", "17px"]
        realtime_note = "No other evaluated model achieved a successful realtime landing."
        if all(r["family"] == "Jev" for r in rows if r["mode"] == "realtime"):
            assert labels.index("REALTIME") < labels.index(realtime_note) < labels.index("LOCKSTEP")
        else:
            assert realtime_note not in labels
        for header in ("BEST SCORE", "AVERAGE SCORE", "API COST PER FLIGHT", "MEAN LATENCY"):
            assert labels.count(header) == 2
        assert labels.count("COMPARISON") == 4
        assert labels.count("MODEL") == 2
        assert "MODEL / REASONING EFFORT" not in labels
        assert not any((label or "").startswith("LANDING SCORE / 100") for label in labels)
        ordering_note = (
            "Within each group: highest best score first; unscored models by fastest mean latency."
        )
        assert labels.index("LOCKSTEP") < labels.index(ordering_note)
        assert labels.index(ordering_note) < labels.index(
            "All Codex runs shown used low reasoning effort."
        )
        assert labels[-5:-1] == [
            "All Codex runs shown used low reasoning effort.",
            "Successful landing",
            "Failed landing",
            "Identical output, not a separate landing",
        ]
        assert not any(" · " in label for label in labels if label)
        model_nodes = [
            node
            for node in svg.findall(".//s:text", ns)
            if "; label:" in node.get("aria-label", "")
        ]
        model_labels = [node.text for node in model_nodes]
        assert {node.get("fill") for node in model_nodes} == {THEMES[theme]["fg"]}
        assert {node.get("text-anchor") for node in model_nodes} == {"start"}
        local = (
            ("strands-decider-31B-gemma4-v2-2611", "Strands Decider v2 31B"),
            ("kudhab", "Kudhab"),
            ("groundhog-1", "Groundhog 1"),
            ("karpo-decision-31B", "Karpo Decision 31B"),
            ("bison-1", "Bison 1"),
            ("glide-v1.2", "GLiDE v1.2"),
            ("pplx-decider-v1.3", "Decider v1.3 27B"),
            ("knowline-31b-gen2", "KnowLine-31B Gen2"),
        )
        decisions = (
            ("Microsoft-Decision-1.1", "Microsoft Decision 1.1"),
            ("gpt-6-luna", "Luna Decision API"),
            ("Microsoft-Decision-1", "Microsoft Decision 1"),
            ("gemini-decision-1", "Gemini Decision 1"),
        )
        assert model_labels == [
            "Jev 1.14",
            "Jev 1.13",
            *[
                label
                for model, label in (*local, *decisions)
                if results.get(("realtime", model), {}).get("successful", 0)
            ],
            "Jev 1.14",
            "Jev 1.13",
            "GPT-6 Luna",
            "GPT-6.2 Sol",
            "GPT-6.1 Sol",
            "GPT-6.1 Terra",
            "GPT-6 Astra",
            *[label for model, label in local if ("lockstep", model) in results],
            *[label for _, label in decisions],
        ]
        headings = [
            node.get("fill")
            for node in svg.findall(".//s:text", ns)
            if "; heading:" in node.get("aria-label", "")
        ]
        groups = THEMES[theme]["groups"]
        realtime_groups = dict.fromkeys(r["family"] for r in rows if r["mode"] == "realtime")
        assert headings == [*(groups[group] for group in realtime_groups), *groups.values()]
        segments = [
            node for node in svg.iter() if node.get("aria-label", "").startswith("segment_x:")
        ]
        assert len(segments) == len(segment_kinds)
        colors = dict(zip(("success", "fail", "repeat"), THEMES[theme]["outcomes"], strict=True))
        assert [node.get("fill") for node in segments] == [colors[kind] for kind in segment_kinds]
        swatches = [
            node
            for node in svg.iter()
            if node.get("aria-label", "").startswith("x:")
            and node.get("aria-roledescription") == "rect mark"
        ]
        assert [node.get("fill") for node in swatches] == list(colors.values())
        for value, highlight in (
            ("trial_best", "trial_highest"),
            ("trial_average", "trial_average_highest"),
        ):
            highlighted = [
                node.text
                for node in svg.findall(".//s:text", ns)
                if f"{value}:" in node.get("aria-label", "")
                and node.get("fill") == THEMES[theme]["best"]
            ]
            assert highlighted
            assert highlighted == [row[value] for row in rows if row[highlight]]
    repeated = next(
        r for r in rows if r["model"] == "Microsoft Decision 1.1" and r["mode"] == "lockstep"
    )
    assert [s["kind"] for s in repeated["segments"]] == ["repeat"] * 9 + ["success"]
    for row in rows:
        if row["family"] == "Local" and row["mode"] == "lockstep":
            assert [s["kind"] for s in row["segments"]] == ["repeat"] * 9 + [
                "fail" if row["score"] is None else "success"
            ]


def test_highlights_are_independent_per_group_and_mode(trials):
    results = summarize(trials)
    results["lockstep", SOL_MODEL]["average"] = 78
    historical = load_rows(HISTORICAL_OUTPUT / "results.json")
    rows = merge_rows(historical, results)
    for column, codex in (
        ("trial_highest", "GPT-6 Luna"),
        ("trial_average_highest", "GPT-6.2 Sol"),
    ):
        assert [(r["mode"], r["model"]) for r in rows if r[column]] == [
            ("realtime", "Jev 1.14"),
            ("lockstep", "Jev 1.14"),
            ("lockstep", codex),
            ("lockstep", "Strands Decider v2 31B"),
            ("lockstep", "Microsoft Decision 1.1"),
        ]


def test_realtime_hides_failures_and_shows_successful_microsoft_without_repeat_style(trials):
    results = summarize(trials)
    key = ("realtime", "Microsoft-Decision-1.1")
    results[key] = {
        "successful": 0,
        "failed": 10,
        "best": None,
        "average": None,
        "api_cost_usd": 0.005,
        "mean_latency_s": 0.8,
    }
    historical = load_rows(HISTORICAL_OUTPUT / "results.json")
    assert not any(
        r["model"] == "Microsoft Decision 1.1" and r["mode"] == "realtime"
        for r in merge_rows(historical, results)
    )
    results[key].update(successful=1, failed=9, best=60.0, average=60.0)
    (row,) = [
        r
        for r in merge_rows(historical, results)
        if r["mode"] == "realtime" and r["model"] == "Microsoft Decision 1.1"
    ]
    assert row["model"] == "Microsoft Decision 1.1"
    assert [s["kind"] for s in row["segments"]] == ["success"] + ["fail"] * 9


def test_existing_non_score_columns_are_unchanged(trials):
    historical = load_rows(HISTORICAL_OUTPUT / "results.json")
    merged = merge_rows(historical, summarize(trials))
    updated = {(r["mode"], r["label"]): r for r in display_rows(merged)}
    for old in display_rows(historical):
        if old["effort"] not in ("", "low"):
            assert (old["mode"], old["label"]) not in updated
            continue
        new = updated[old["mode"], old["label"]]
        for field in ("cost_text", "cost_comparison", "latency_comparison", "latency_text"):
            assert new[field] == old[field]

    spec = figure_spec(merged, "light", trial_scores=True)
    assert spec["padding"] == 24
    for panel in (p for p in spec["vconcat"] if "hconcat" in p):
        columns = panel["hconcat"]
        assert {column["title"]["fontSize"] for column in columns} == {13}
        assert {column["title"]["anchor"] for column in columns} == {"middle"}
        assert [column["title"]["text"] for column in columns] == [
            "MODEL",
            "OUTCOMES",
            ["BEST", "SCORE"],
            ["AVERAGE", "SCORE"],
            ["API COST", "PER FLIGHT"],
            "COMPARISON",
            ["MEAN", "LATENCY"],
            "COMPARISON",
        ]
        assert columns[0]["width"] < 225
        assert columns[1]["layer"][0]["mark"] == {
            "type": "rect",
            "width": 10,
            "height": 10,
            "cornerRadius": 1.5,
        }


def test_sol62_uses_best_flight_cost_and_latency(trials):
    rows = merge_rows(load_rows(HISTORICAL_OUTPUT / "results.json"), summarize(trials))
    sol = next(row for row in display_rows(rows) if row["model"] == "GPT-6.2 Sol")
    assert sol["trial_best"] == "80.04"
    assert sol["trial_average"] == "70.40"
    assert sol["api_cost_usd"] == pytest.approx(0.700822)
    assert sol["cost_text"] == "$0.701"
    assert sol["cost_comparison"] == "46.7×"
    assert sol["latency_text"] == "2.213 s"
    assert sol["latency_comparison"] == "9.2×"


def test_local_latency_comparison_does_not_require_api_cost(trials):
    historical = load_rows(HISTORICAL_OUTPUT / "results.json")
    reference = {r["mode"]: r["mean_latency_s"] for r in historical if r["model"] == "Jev 1.14"}
    results = summarize(trials)
    results["realtime", "bison-1"].update(successful=1, failed=9, best=60, average=60)
    rows = [r for r in display_rows(merge_rows(historical, results)) if r["family"] == "Local"]
    assert {r["mode"] for r in rows} == {"lockstep", "realtime"}
    for row in rows:
        assert row["cost_comparison"] == "—"
        assert row["latency_comparison"] == f"{row['mean_latency_s'] / reference[row['mode']]:.1f}×"


def test_decision_rows_use_mean_logged_cost(trials):
    rows = merge_rows(load_rows(HISTORICAL_OUTPUT / "results.json"), summarize(trials))
    decisions = [
        r for r in display_rows(rows) if r["family"] == "Decision API" and r["mode"] == "lockstep"
    ]
    assert {
        r["model"]: (r["latency_text"], r["cost_text"], r["cost_comparison"]) for r in decisions
    } == {
        "Microsoft Decision 1.1": ("0.778 s", "$0.0149", "1.0×"),
        "Gemini Decision 1": ("3.988 s", "$0.0313", "2.1×"),
        "Luna Decision API": ("0.275 s", "$0.0137", "0.9×"),
        "Microsoft Decision 1": ("0.895 s", "$0.0116", "0.8×"),
    }
    assert {r["model"]: r["api_cost_usd"] for r in decisions} == pytest.approx(
        {
            "Microsoft Decision 1.1": 0.01493877,
            "Gemini Decision 1": 0.0313087,
            "Luna Decision API": 0.0137289,
            "Microsoft Decision 1": 0.0116339706,
        }
    )


def test_luna_decisions_prices_cache_but_not_output():
    run = {
        "config": {"model": "gpt-6-luna", "mode": "lockstep"},
        "started_at": "2026-11-15T10:00:00+00:00",
        "finished_at": "2026-11-15T10:00:02+00:00",
        "diagnostics": {"calls": 1},
        "decisions": [{"decision_info": {"action_ids": {"aileron": "3"}}}],
    }
    response = {
        "at": "2026-11-15T10:00:01+00:00",
        "request": {"model": "gpt-6-luna"},
        "response": {
            "model": "gpt-6-luna",
            "answers": [{"name": "aileron", "choice": "3"}],
            "usage": {
                "input_tokens": 2400,
                "output_tokens": 200,
                "input_tokens_details": {
                    "cached_tokens": 400,
                    "cache_write_tokens": 300,
                    "cache_write_tokens_details": {"ttl_30m_tokens": 200, "ttl_12h_tokens": 100},
                },
            },
        },
    }
    assert decision_flight_cost(run, [response]) == pytest.approx(0.000224)
    response["response"]["answers"][0]["choice"] = "2"
    with pytest.raises(ValueError, match="does not match"):
        decision_flight_cost(run, [response])


def test_microsoft_realtime_prices_one_drained_response():
    run = {
        "config": {
            "model": "Microsoft-Decision-1.1",
            "mode": "realtime",
            "controller_metadata": {"deployment_type": "GlobalStandard"},
        },
        "started_at": "2026-11-25T20:00:00+00:00",
        "finished_at": "2026-11-25T20:00:02+00:00",
        "diagnostics": {"calls": 1, "requests_started": 2},
        "decisions": [{"decision_info": {"action_ids": {"aileron": "3"}}}],
    }
    applied = {
        "at": "2026-11-25T20:00:01+00:00",
        "request": {"model": "decision-1-1"},
        "response": {
            "model": "Microsoft-Decision-1.1",
            "answers": {"aileron": {"choice": "3"}},
            "usage": {"input_tokens": 2000},
        },
    }
    drained = applied | {"at": "2026-11-25T20:00:03+00:00"}
    assert decision_flight_cost(run, [applied, drained]) == pytest.approx(0.000168)
    with pytest.raises(ValueError):
        decision_flight_cost(run, [applied])


def test_rendered_labels_reproduce(trials):
    pytest.importorskip("vl_convert")
    results = summarize(trials)
    ns = {"s": "http://www.w3.org/2000/svg"}
    for theme in THEMES:
        prev = ET.parse(OUTPUT / f"ten-trial-{theme}.svg").getroot()
        fresh = ET.fromstring(chart(results, theme))
        assert [list(n.itertext()) for n in prev.findall(".//s:text", ns)] == [
            list(n.itertext()) for n in fresh.findall(".//s:text", ns)
        ]
