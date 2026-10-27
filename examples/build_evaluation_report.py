"""Build one evidence-validated cohort's Markdown, JSON, SVG and PNG report."""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flightbench.leaderboard import (
    _display_rows,
    _svg_best,
    _svg_delta,
    _svg_scatter,
    load_submissions,
)


def build_report(submissions: Path, suffix: str, output: Path) -> None:
    selected = [(p, s) for p, s in load_submissions(submissions) if p.parent.name.endswith(suffix)]
    if not selected:
        raise ValueError("No submissions match the requested suffix")
    rows = _display_rows(selected, {})
    if len({row["comparison_cohort"]["id"] for row in rows}) != 1:
        raise ValueError("Select one matching experimental cohort; do not mix conditions")
    renderer = shutil.which("rsvg-convert")
    if renderer is None:
        raise RuntimeError("PNG rendering requires the native rsvg-convert executable")
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").write_text(json.dumps(rows, indent=2) + "\n")
    lines = [
        "# Live evaluation results",
        "",
        rows[0]["comparison_cohort"]["label"],
        "",
        "Community/self-reported. One seed is not an accuracy or success-rate estimate.",
        "Latency is completed-request wall time; applied Hz uses simulation time.",
        "Provider costs remain unknown where full episode charges were not recorded.",
        "",
        "| Model | Mode | Landings | Score | Mean / p50 / p95 (ms) | Completed / applied | Applied Hz | Outcome | Evidence |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for row, (path, _) in zip(rows, selected, strict=True):
        link = Path(os.path.relpath(path, output)).as_posix()
        for mode in ("lockstep", "realtime"):
            m = row[mode]
            if m is None:
                continue
            flow = m["decision_flow"]
            latency = " / ".join(
                f"{m[key]:.1f}" for key in ("mean_latency_ms", "p50_latency_ms", "p95_latency_ms")
            )
            outcomes = ", ".join(
                f"{key} ({count})" for key, count in m["terminal_outcomes"].items()
            )
            lines.append(
                f"| {row['controller']} | {mode} | {m['successful_landings']}/{m['total_runs']} | "
                f"{m['median_score']:.3f} | {latency} | {flow['completed']} / {flow['applied']} | "
                f"{flow['effective_applied_rate_hz']:.3f} | {outcomes} | [submission]({link}) |"
            )
    charts = {"best-of": _svg_best(rows), "mode-delta": _svg_delta(rows)}
    for mode in ("lockstep", "realtime"):
        for kind, key, units in (
            ("latency", "p95_latency_ms", "p95 decision latency (ms)"),
            ("cost", "cost_per_run_usd", "Provider cost per run (USD)"),
        ):
            charts[f"{mode}-{kind}-score"] = _svg_scatter(
                rows, mode, key, f"{mode.title()}: {kind} versus score", units
            )
    lines += ["", "## Figures", ""]
    for name, svg in charts.items():
        path = output / f"{name}.svg"
        path.write_text(svg)
        subprocess.run(
            [renderer, "-b", "white", str(path), "-o", str(path.with_suffix(".png"))], check=True
        )
        lines.append(f"- {name}: [SVG]({name}.svg) · [PNG]({name}.png)")
    (output / "README.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submissions", type=Path, default=Path("leaderboard/submissions"))
    parser.add_argument("--suffix", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build_report(args.submissions, args.suffix, args.output)
