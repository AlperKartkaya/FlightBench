# /// script
# requires-python = ">=3.11"
# dependencies = ["vl-convert-python==1.9.0"]
# ///
"""Generate Primer-themed static Vega-Lite figures from the recorded benchmark results.

Run: uv run --script examples/build_benchmark_visuals.py
Design sources and licenses: docs/evaluations/2026-10-22-scoring-v2/visualization.md
"""

from __future__ import annotations

import csv
import json
import math
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/evaluations/2026-10-22-scoring-v2"
FAMILIES = [
    "Jev",
    "GPT-6 Luna",
    "GPT-6.1 Terra",
    "GPT-6.2 Sol",
    "GPT-6.1 Sol",
    "GPT-6 Astra",
    "Local",
    "Decision API",
]
EFFORTS = ["low", "medium", "high", "xhigh"]
MODELS = {
    "jev-1.13.0": ("Jev", "Jev 1.13"),
    "jev-1.14.0": ("Jev", "Jev 1.14"),
    "gpt-6-luna": ("GPT-6 Luna", "GPT-6 Luna"),
    "gpt-6.1-sol": ("GPT-6.1 Sol", "GPT-6.1 Sol"),
    "gpt-6-astra": ("GPT-6 Astra", "GPT-6 Astra"),
    "gpt-6.1-terra": ("GPT-6.1 Terra", "GPT-6.1 Terra"),
}
# Primer light/dark semantic colors and matching categorical hues.
THEMES = {
    "light": {
        "bg": "#ffffff",
        "fg": "#1f2328",
        "muted": "#59636e",
        "line": "#d1d9e0",
        "subtle": "#f6f8fa",
        "best": "#1a7f37",
        "families": [
            "#1a7f37",
            "#bc4c00",
            "#0550ae",
            "#00666d",
            "#0969da",
            "#8250df",
            "#59636e",
            "#9a385d",
        ],
        "outcomes": ["#1a7f37", "#b5473d", "#6e7781"],
        "groups": {
            "Jev": "#1a7f37",
            "Codex": "#0550ae",
            "Local": "#8250df",
            "Decision API": "#9a385d",
        },
    },
    "dark": {
        "bg": "#0d1117",
        "fg": "#f0f6fc",
        "muted": "#9198a1",
        "line": "#3d444d",
        "subtle": "#161b22",
        "best": "#3fb950",
        "families": [
            "#3fb950",
            "#ffa657",
            "#79c0ff",
            "#56d4dd",
            "#58a6ff",
            "#bc8cff",
            "#9198a1",
            "#f778ba",
        ],
        "outcomes": ["#3fb950", "#e07d72", "#484f58"],
        "groups": {
            "Jev": "#3fb950",
            "Codex": "#79c0ff",
            "Local": "#bc8cff",
            "Decision API": "#f778ba",
        },
    },
}


def load_rows(source: Path) -> list[dict]:
    """Keep full precision; never treat missing usage or a lower bound as exact cost."""
    groups = json.loads(source.read_text())["groups"]
    expected = {
        (model, effort, "lockstep")
        for model in MODELS
        if not model.startswith("jev-") and model != "gpt-6.1-terra"
        for effort in EFFORTS
    } | {
        (model, None, mode)
        for model in MODELS
        if model.startswith("jev-")
        for mode in ("lockstep", "realtime")
    }
    keys = [(g["model"], g["reasoning_effort"], g["mode"]) for g in groups]
    if len(keys) != len(expected) or set(keys) != expected:
        raise ValueError("Expected the 16 recorded model/effort/mode configurations")
    reference = next(
        g["selected"] for g in groups if g["model"] == "jev-1.14.0" and g["mode"] == "lockstep"
    )
    additions = source.with_name("additional-results.json")
    extra = (
        json.loads(additions.read_text())
        if additions.exists() and source == OUTPUT / "results.json"
        else {}
    )
    groups += extra.get("groups", [])
    rows = []
    for group in groups:
        run = group["selected"]
        family, model = MODELS[group["model"]]
        effort = group["reasoning_effort"]
        latency = run["diagnostics"]["mean_latency_ms"] / 1000
        cost, lower = run["cost_usd"], run.get("cost_lower_bound_usd")
        if not 0 <= run["score"] <= 100:
            raise ValueError("Selected-flight scores must be between 0 and 100")
        if cost is None and lower is None:
            raise ValueError("A plotted flight needs a cost or an explicitly recorded lower bound")
        if (cost if cost is not None else lower) <= 0 or latency <= 0:
            raise ValueError("Cost and latency must be positive for this presentation")
        wall = (
            datetime.fromisoformat(run["finished_at"]) - datetime.fromisoformat(run["started_at"])
        ).total_seconds()
        row = {
            "run_id": run["run_id"],
            "model": model,
            "family": family,
            "effort": effort or "",
            "mode": group["mode"],
            "score": run["score"],
            "sim_time_s": run["diagnostics"]["duration_s"],
            "wall_time_s": wall,
            "calls": run["calls"],
            "mean_latency_s": latency,
            "latency_ratio": latency * 1000 / reference["diagnostics"]["mean_latency_ms"],
            "input_tokens": run["input_tokens"],
            "output_tokens": run["output_tokens"],
            "api_cost_usd": cost,
            "cost_lower_bound_usd": lower if cost is None else None,
            "cost_ratio": cost / reference["cost_usd"] if cost is not None else None,
            "cost_ratio_lower_bound": lower / reference["cost_usd"] if cost is None else None,
        }
        if any(not math.isfinite(v) for v in row.values() if isinstance(v, (int, float))):
            raise ValueError("Benchmark metrics must be finite")
        rows.append(row)
    rows.extend(extra.get("local", []))
    return sorted(
        rows,
        key=lambda r: (
            r["mode"],
            FAMILIES.index(r["family"]),
            0 if r["model"] == "Jev 1.14" else 1,
            r["model"],
            EFFORTS.index(r["effort"]) if r["effort"] else -1,
        ),
    )


def display_rows(rows: list[dict], show_effort=True) -> list[dict]:
    """Score bests are exact; both Jev versions receive requested cost/latency emphasis."""
    displayed = []
    for mode in dict.fromkeys(r["mode"] for r in rows):
        cohort = [r for r in rows if r["mode"] == mode]
        best_score = max((r["score"] for r in cohort if r["score"] is not None), default=None)
        for row in cohort:
            cost = row["api_cost_usd"]
            plotted_cost = cost if cost is not None else row["cost_lower_bound_usd"]
            precision = 4 if row["family"] in ("Jev", "Decision API") else 3
            label = row["model"] + (f" · {row['effort']}" if show_effort and row["effort"] else "")
            displayed.append(
                dict(
                    row,
                    label=label,
                    cost=plotted_cost,
                    score_text="—" if row["score"] is None else f"{row['score']:.3f}",
                    cost_text="—"
                    if plotted_cost is None
                    else ("≥" if cost is None else "") + f"${plotted_cost:.{precision}f}",
                    cost_comparison="1×"
                    if row["family"] == "Jev"
                    else (
                        "—"
                        if plotted_cost is None
                        else ("≥" if cost is None else "")
                        + f"{row['cost_ratio'] or row['cost_ratio_lower_bound']:.1f}×"
                    ),
                    latency_comparison="1×"
                    if row["family"] == "Jev"
                    else ("—" if row["latency_ratio"] is None else f"{row['latency_ratio']:.1f}×"),
                    latency_text="—"
                    if row["mean_latency_s"] is None
                    else f"{row['mean_latency_s']:.3f} s",
                    best_score=row["score"] is not None and row["score"] == best_score,
                    best_latency=row["family"] == "Jev",
                    best_cost=row["family"] == "Jev",
                )
            )
    return displayed


def color_encoding(palette: dict) -> dict:
    return {
        "field": "family",
        "type": "nominal",
        "legend": None,
        "scale": {"domain": FAMILIES, "range": palette["families"]},
    }


def leaderboard(rows: list[dict], mode: str, palette: dict, trial_scores=False) -> dict:
    data = []
    headings = []
    position = 15
    previous_group = None
    for row in (r for r in rows if r["mode"] == mode):
        group = "Codex" if trial_scores and row["effort"] else row["family"]
        if group != previous_group:
            if trial_scores:
                if headings:
                    position += 8
                headings.append(
                    {"row_y": position, "heading": group, "heading_color": palette["groups"][group]}
                )
                position += 24
            elif not trial_scores and previous_group is not None:
                position += 15
        data.append(dict(row, row_y=position))
        position += 30
        previous_group = group
    y = {"field": "row_y", "type": "quantitative", "axis": None, "scale": None}
    base = {"data": {"values": data}, "height": position - 15, "encoding": {"y": y}}

    def column(title, width, layers):
        return dict(
            base,
            title={
                "text": title,
                "anchor": "middle" if trial_scores else "start",
                # A half-line offset keeps single- and two-line titles vertically centered.
                "offset": 11 if isinstance(title, list) else 18,
                **({"lineHeight": 14} if trial_scores else {}),
                "fontSize": 13,
                "color": palette["muted"],
            },
            width=width,
            layer=layers,
        )

    def text(field, x, align="right", best=None, family=False):
        encoding = {"x": {"value": x}, "text": {"field": field}}
        if family:
            encoding["color"] = color_encoding(palette)
        if best:
            encoding["color"] = {
                "condition": {"test": f"datum.{best}", "value": palette["best"]},
                "value": palette["fg"],
            }
        return {
            "mark": {
                "type": "text",
                "align": align,
                "fontSize": 16,
                "color": palette["fg"],
                "fontWeight": {"expr": f"datum.{best} ? 700 : 400"} if best else 400,
            },
            "encoding": encoding,
        }

    names = column(
        "MODEL" if trial_scores else "MODEL / REASONING EFFORT",
        190 if trial_scores else 225,
        [text("label", 0, "left", family=not trial_scores)],
    )
    if headings:
        heading = text("heading", 0, "left")
        heading["data"] = {"values": headings}
        heading["mark"].update(fontSize=13, fontWeight=700)
        heading["encoding"]["color"] = {"field": "heading_color", "type": "nominal", "scale": None}
        names["layer"].append(heading)
    score = column(
        "LANDING SCORE / 100  ↑",
        225,
        [
            {
                "mark": {
                    "type": "bar",
                    "orient": "horizontal",
                    "size": 16,
                    "cornerRadiusEnd": 3,
                    "opacity": 0.72,
                },
                "encoding": {
                    "x": {
                        "field": "score",
                        "type": "quantitative",
                        "axis": None,
                        "scale": {"domain": [0, 100], "range": [0, 150]},
                    },
                    "color": color_encoding(palette),
                },
            },
            text("score_text", 225, best="best_score"),
        ],
    )
    if trial_scores:
        outcomes = column(
            "OUTCOMES",
            118,
            [
                {
                    "transform": [
                        {"flatten": ["segments"], "as": ["segment"]},
                        {"calculate": "5 + datum.segment.i * 12", "as": "segment_x"},
                    ],
                    "mark": {"type": "rect", "width": 10, "height": 10, "cornerRadius": 1.5},
                    "encoding": {
                        "x": {
                            "field": "segment_x",
                            "type": "quantitative",
                            "scale": None,
                            "axis": None,
                        },
                        "color": {
                            "condition": [
                                {
                                    "test": "datum.segment.kind === 'success'",
                                    "value": palette["outcomes"][0],
                                },
                                {
                                    "test": "datum.segment.kind === 'fail'",
                                    "value": palette["outcomes"][1],
                                },
                            ],
                            "value": palette["outcomes"][2],
                        },
                    },
                },
                text("score_source", 0, "left")
                | {
                    "mark": {
                        "type": "text",
                        "align": "left",
                        "fontSize": 10,
                        "color": palette["muted"],
                    },
                },
            ],
        )
        score_columns = [
            outcomes,
            column(["BEST", "SCORE"], 82, [text("trial_best", 41, "center", best="trial_highest")]),
            column(
                ["AVERAGE", "SCORE"],
                75,
                [text("trial_average", 37.5, "center", best="trial_average_highest")],
            ),
        ]
    else:
        score_columns = [score]

    def metric(field, x, width, best):
        return text(field, width / 2, "center", best) if trial_scores else text(field, x, best=best)

    cost = column(
        ["API COST", "PER FLIGHT"] if trial_scores else "API COST / FLIGHT  ↓",
        135,
        [metric("cost_text", 130, 135, "best_cost")],
    )
    cost_comparison = column("COMPARISON", 100, [metric("cost_comparison", 95, 100, "best_cost")])
    latency_comparison = column(
        "COMPARISON", 100, [metric("latency_comparison", 95, 100, "best_latency")]
    )
    latency = column(
        ["MEAN", "LATENCY"] if trial_scores else "MEAN LATENCY  ↓",
        140,
        [metric("latency_text", 135, 140, "best_latency")],
    )
    return {
        "title": {
            "text": mode.upper(),
            "anchor": "middle" if trial_scores else "start",
            "fontSize": 17 if trial_scores else 16,
            "offset": 22,
            "color": palette["fg"],
        },
        "hconcat": [names, *score_columns, cost, cost_comparison, latency, latency_comparison],
        "spacing": 10,
        "resolve": {"scale": {"y": "shared"}},
    }


def figure_spec(rows: list[dict], theme: str, trial_scores=False) -> dict:
    p = THEMES[theme]
    displayed = display_rows(rows, show_effort=not trial_scores)
    family_color = color_encoding(p)
    shapes = {
        "field": "family",
        "type": "nominal",
        "legend": None,
        "scale": {
            "domain": FAMILIES,
            "range": [
                "circle",
                "triangle-up",
                "circle",
                "triangle-down",
                "square",
                "diamond",
                "cross",
                "triangle-right",
            ],
        },
    }
    present_families = [family for family in FAMILIES if any(r["family"] == family for r in rows)]
    legend = {
        "width": 975,
        "height": 20,
        "data": {"values": [{"family": f, "position": i} for i, f in enumerate(present_families)]},
        "encoding": {
            "x": {
                "field": "position",
                "type": "quantitative",
                "axis": None,
                "scale": {"domain": [0, len(present_families)]},
            }
        },
        "layer": [
            {
                "mark": {"type": "point", "filled": True, "size": 80},
                "encoding": {"color": family_color, "shape": shapes},
            },
            {
                "mark": {
                    "type": "text",
                    "align": "left",
                    "dx": 14,
                    "fontSize": 14,
                    "fontWeight": 600,
                },
                "encoding": {"text": {"field": "family"}, "color": family_color},
            },
        ],
    }

    def note(lines):
        return {
            "width": 1010,
            "height": 16 * len(lines),
            "data": {"values": [{"line": line, "y": 8 + 16 * i} for i, line in enumerate(lines)]},
            "mark": {"type": "text", "fontSize": 13, "color": p["muted"]},
            "encoding": {
                "x": {"value": 505},
                "y": {"field": "y", "type": "quantitative", "scale": None, "axis": None},
                "text": {"field": "line"},
            },
        }

    panels = [legend, leaderboard(displayed, "lockstep", p), leaderboard(displayed, "realtime", p)]
    if trial_scores:
        panels = [leaderboard(displayed, "realtime", p, trial_scores=True)]
        if not any(
            r["mode"] == "realtime" and r["family"] != "Jev" and r["score"] is not None
            for r in rows
        ):
            panels.append(
                note(["No other evaluated model achieved a successful realtime landing."])
            )
        panels += [
            leaderboard(displayed, "lockstep", p, trial_scores=True),
            note(
                [
                    "Within each group: highest best score first; unscored models by fastest mean latency.",
                    "All Codex runs shown used low reasoning effort.",
                ]
            ),
            {
                "width": 1010,
                "height": 16,
                "data": {
                    "values": [
                        {"x": x, "description": label, "color": color}
                        for x, label, color in zip(
                            (238, 398, 533),
                            (
                                "Successful landing",
                                "Failed landing",
                                "Identical output, not a separate landing",
                            ),
                            p["outcomes"],
                            strict=True,
                        )
                    ]
                },
                "encoding": {
                    "x": {"field": "x", "type": "quantitative", "scale": None, "axis": None},
                    "y": {"value": 8},
                },
                "layer": [
                    {
                        "mark": {"type": "rect", "width": 10, "height": 10, "cornerRadius": 1.5},
                        "encoding": {"color": {"field": "color", "type": "nominal", "scale": None}},
                    },
                    {
                        "mark": {
                            "type": "text",
                            "align": "left",
                            "dx": 12,
                            "fontSize": 13,
                            "color": p["muted"],
                        },
                        "encoding": {"text": {"field": "description"}},
                    },
                ],
            },
        ]
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
        "description": "FlightBench selected flights, separated by execution mode and scoring version. "
        "Score bests use unrounded measurements; both Jev versions receive cost/latency emphasis. "
        "Complete measurements and provenance are linked in the README.",
        "background": p["bg"],
        "padding": 24 if trial_scores else 10,
        "title": {
            "text": "Landing Performance, Cost And Latency",
            "anchor": "middle",
            "fontSize": 25,
            "subtitleFontSize": 15,
            "offset": 32 if trial_scores else 26,
            "color": p["fg"],
            "subtitleColor": p["muted"],
        },
        "vconcat": panels,
        "spacing": 36 if trial_scores else 30,
        "config": {
            "font": "Arial",
            "view": {"stroke": None},
            "text": {"color": p["fg"]},
            "title": {"color": p["fg"], "subtitleColor": p["muted"]},
            "axis": {
                "labelColor": p["muted"],
                "titleColor": p["muted"],
                "gridColor": p["line"],
                "gridOpacity": 0.45,
                "domain": False,
                "ticks": False,
                "labelFontSize": 12,
                "titleFontSize": 12,
                "titleFontWeight": 400,
                "titlePadding": 12,
                "labelPadding": 8,
            },
        },
    }


def main():
    import vl_convert as vlc

    rows = load_rows(OUTPUT / "results.json")
    for theme in THEMES:
        svg = vlc.vegalite_to_svg(figure_spec(rows, theme), vl_version="6.4")
        (OUTPUT / f"benchmark-{theme}.svg").write_text(svg + "\n")
    with (OUTPUT / "benchmark-data.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
