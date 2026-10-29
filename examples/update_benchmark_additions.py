"""Publish completed Terra cohorts and positive current-scoring local runs."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from examples.build_v2_publication import _svg, select_groups
from examples.run_local_campaign import NEW, OLD, validate_trial
from examples.run_terra_campaign import (
    DATA,
    EFFORTS,
    EVIDENCE,
    SEEDS,
    read_trial,
    repeat_cohort,
    write,
)
from flightbench.benchmark import episode_rows

OUTPUT = ROOT / "docs/evaluations/2026-10-22-scoring-v2"


def with_landing_retries(group, records):
    """Only requested failed seeds may retry; failed retries cannot replace a landing."""
    trials = [trial for cohort in group["cohorts"] for trial in cohort["trials"]]
    successful = {trial["seed"] for trial in trials if trial["success"]}
    eligible = {trial["seed"] for trial in trials if not trial["success"]} - successful
    seen = set()
    retries = []
    selected = group["selected"]
    for record in records:
        seed = record["config"]["seed"]
        if (
            group["reasoning_effort"] not in ("high", "xhigh")
            or seed not in eligible
            or seed in seen
        ):
            raise ValueError("Only one retry per failed high/xhigh seed is authorized")
        seen.add(seed)
        candidate = select_groups(
            [record],
            expected_groups=(("gpt-6.1-terra", group["reasoning_effort"]),),
            trial_seeds=(seed,),
        )[0]
        retries.append(candidate)
        if candidate["selected"]["success"] and candidate["selected"]["score"] > selected["score"]:
            selected = candidate["selected"]
    return {
        **group,
        "selected": selected,
        "selected_run_id": selected["run_id"],
        "landing_retries": retries,
    }


def additions():
    groups = []
    if (EVIDENCE / "source.json").exists():
        identity = json.loads((EVIDENCE / "source.json").read_text())["identity"]["source_hash"]
        for effort in EFFORTS:
            cohorts = []
            for cohort in (1, 2):
                folders = [DATA / effort / f"cohort-{cohort}" / str(seed) for seed in SEEDS]
                if not all((folder / "submission.json").exists() for folder in folders):
                    break
                try:
                    records = [
                        read_trial(folder, effort, seed, identity)
                        for folder, seed in zip(folders, SEEDS, strict=True)
                    ]
                except RuntimeError:
                    # Incomplete provider trials cannot be published as a completed cohort.
                    break
                cohorts.append(
                    select_groups(records, expected_groups=(("gpt-6.1-terra", effort),))[0]
                )
                if not repeat_cohort(records) or cohort == 2:
                    chosen = {
                        **max(cohorts, key=lambda group: group["selected"]["score"]),
                        "cohorts": cohorts,
                        "source_hash": identity,
                    }
                    retries = []
                    if effort in ("high", "xhigh"):
                        for seed in SEEDS:
                            folder = DATA / effort / "landing-retry-1" / str(seed)
                            if (folder / "submission.json").exists():
                                try:
                                    retries.append(read_trial(folder, effort, seed, identity))
                                except RuntimeError:
                                    continue
                    groups.append(with_landing_retries(chosen, retries))
                    break
    local = []
    provenance = []
    best_local = {}
    for folder in (OLD, NEW):
        for path in sorted(folder.rglob("submission.json")):
            raw = json.loads(path.read_text())
            seeds = raw["evaluation"]["seeds"]
            if len(seeds) != 1:
                continue
            record = validate_trial(path, seeds[0], raw["controller"]["model"])
            model = record["config"]["model"]
            provenance.append(str(path.relative_to(ROOT)))
            if record["outcome"]["quality"] > best_local.get(model, {}).get("outcome", {}).get(
                "quality", 0
            ):
                best_local[model] = record
    for name, record in sorted(best_local.items()):
        row = episode_rows([record])[0]
        local.append(
            {
                "run_id": record["run_id"],
                "model": name,
                "family": "Local",
                "effort": "",
                "mode": "lockstep",
                "score": row["score"],
                "sim_time_s": record["diagnostics"]["duration_s"],
                "wall_time_s": (
                    datetime.fromisoformat(record["finished_at"])
                    - datetime.fromisoformat(record["started_at"])
                ).total_seconds(),
                "calls": row["calls"],
                "mean_latency_s": record["diagnostics"]["mean_latency_ms"] / 1000,
                "latency_ratio": None,
                "input_tokens": row["input_tokens"],
                "output_tokens": row["output_tokens"],
                "api_cost_usd": None,
                "cost_lower_bound_usd": None,
                "cost_ratio": None,
                "cost_ratio_lower_bound": None,
            }
        )
    return {
        "groups": groups,
        "local": local,
        "local_provenance": provenance,
        "selection": "Highest score across a completed three-seed cohort; repeat all three seeds once if none landed successfully. Failed high/xhigh seeds receive one user-requested landing retry; only successful retries can improve the selected result. Only positive current-scoring local runs are included; local hardware costs are not estimated.",
    }


def main():
    extra = additions()
    write(OUTPUT / "additional-results.json", extra)
    groups = json.loads((OUTPUT / "results.json").read_text())["groups"] + extra["groups"]
    svg = _svg(groups)
    # Local costs are unknown: a separate score-only panel avoids fake log-axis prices.
    if extra["local"]:
        svg = svg.replace('viewBox="0 0 1180 700"', 'viewBox="0 0 1480 700"').replace(
            '<rect width="1180"', '<rect width="1480"'
        )
        parts = [
            '<path d="M1140 40V650" stroke="#dbe3ec"/>',
            '<g font-family="system-ui,sans-serif" fill="#273549"><text x="1165" y="65" font-size="18" font-weight="700">Local Models</text><text x="1165" y="94" font-size="14">Landing scores</text>',
        ]
        for i, row in enumerate(extra["local"]):
            y = 160 + i * 150
            parts.extend(
                [
                    f'<text x="1165" y="{y}" font-size="17">{row["model"]}</text>',
                    f'<rect x="1165" y="{y + 18}" width="{row["score"] * 2.3:.2f}" height="12" rx="3" fill="#59636e"/>',
                    f'<text x="1165" y="{y + 59}" font-size="17">Score {row["score"]:.3f} / 100</text>',
                ]
            )
        parts += [
            '<text x="1165" y="550" font-size="14">Hardware cost not estimated;</text><text x="1165" y="572" font-size="14">not placed on the cost axis.</text></g>'
        ]
        svg = svg.replace("</svg>", "\n".join(parts) + "</svg>")
    target = OUTPUT / "landing-score-vs-api-cost.svg"
    target.write_text(svg)
    subprocess.run(
        ["rsvg-convert", "-w", "2360", str(target), "-o", str(target.with_suffix(".png"))],
        check=True,
    )


if __name__ == "__main__":
    main()
