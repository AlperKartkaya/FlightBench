"""Build the dated scoring-v2 Jev/Codex comparison from validated submissions."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import re
import shutil
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flightbench.benchmark import INCOMPLETE_STATUSES, episode_rows
from flightbench.leaderboard import _read_artifact, load_submissions, scoring_config_hash
from flightbench.scoring import ScoringConfig

EFFORTS = ("low", "medium", "high", "xhigh")
TRIAL_SEEDS = (42, 101, 202)
EXPECTED_GROUPS = (
    *(("gpt-6.1-sol", effort) for effort in EFFORTS),
    *(("gpt-6-astra", effort) for effort in EFFORTS),
    *(("gpt-6-luna", effort) for effort in EFFORTS),
    ("jev-1.13.0", None),
    ("jev-1.14.0", None),
)
FAMILIES = (
    "gpt-6-luna",
    "gpt-6.1-sol",
    "gpt-6-astra",
    "jev-1.13.0",
    "jev-1.14.0",
)
GROUP_ORDER = {group: index for index, group in enumerate(EXPECTED_GROUPS, 1)}
EXCLUDED_MAX_GROUPS = {(model, "max") for model in (*FAMILIES[:3], "gpt-6-sol")} | {
    ("gpt-6-sol", effort) for effort in EFFORTS
}
DATE_RE = re.compile(r"20\d\d-\d\d-\d\d")
CANONICAL_SCORING = asdict(ScoringConfig())
CANONICAL_SCORING_CONFIG_SHA256 = hashlib.sha256(
    json.dumps(CANONICAL_SCORING, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()


def _group_key(episode: dict) -> tuple[str, str | None]:
    config = episode.get("config") or {}
    model = str(config.get("model") or "").removeprefix("openai-codex/")
    return model, None if model.startswith("jev-") else config.get("reasoning_effort")


def _submission_group(submission: object) -> tuple[str, str | None]:
    model = str(submission.controller.model).removeprefix("openai-codex/")
    effort = (
        None if model.startswith("jev-") else submission.controller.metadata.get("reasoning_effort")
    )
    return model, effort


def select_groups(
    episodes: list[dict],
    *,
    mode="lockstep",
    expected_groups=EXPECTED_GROUPS,
    trial_seeds=TRIAL_SEEDS,
) -> list[dict]:
    """Validate and select the highest-scoring completed trial in each fixed group."""
    grouped: dict[tuple[str, str | None], list[dict]] = {}
    for episode in episodes:
        config = episode.get("config") or {}
        if config.get("scoring_version") != "v2" or config.get("mode") != mode:
            raise ValueError("Every publication trial must use scoring v2 in the requested mode")
        if scoring_config_hash(episode) != CANONICAL_SCORING_CONFIG_SHA256:
            raise ValueError("Official V2 publication requires the canonical scoring configuration")
        key = _group_key(episode)
        if key not in expected_groups:
            raise ValueError(f"Unexpected V2 publication group: {key}")
        grouped.setdefault(key, []).append(episode)
    if set(grouped) != set(expected_groups):
        missing = sorted(set(expected_groups) - set(grouped), key=str)
        raise ValueError(f"Expected exactly the requested fixed V2 groups; missing: {missing}")

    result = []
    for key in expected_groups:
        trials = grouped[key]
        seeds = {(episode.get("config") or {}).get("seed") for episode in trials}
        if len(trials) != len(trial_seeds) or seeds != set(trial_seeds):
            raise ValueError(f"{key} must contain exactly seeds {trial_seeds}")
        rows = episode_rows(trials)
        completed = [
            (episode, row)
            for episode, row in zip(trials, rows, strict=True)
            if row["status"] not in INCOMPLETE_STATUSES
        ]
        if len(completed) != len(trial_seeds):
            raise ValueError(
                f"{key} requires three completed flights; rerun interrupted trials first"
            )
        selected = max(
            completed,
            key=lambda pair: (pair[1]["score"], -int(pair[1]["seed"])),
            default=None,
        )
        trial_rows = []
        for episode, row in zip(trials, rows, strict=True):
            trial_rows.append(
                {
                    "run_id": row["run_id"],
                    "seed": row["seed"],
                    "score": row["score"],
                    "success": bool((episode.get("outcome") or {}).get("success")),
                    "status": row["status"],
                    "completed": row["status"] not in INCOMPLETE_STATUSES,
                }
            )
        selected_row = None
        if selected is not None:
            selected_episode, row = selected
            actual_cost = (
                row["cost_usd"]
                if row["missing_usage"] == 0 and not row["input_tokens_estimated"]
                else None
            )
            selected_row = {
                **next(trial for trial in trial_rows if trial["run_id"] == row["run_id"]),
                "calls": row["calls"],
                "diagnostics": selected_episode.get("diagnostics", {}),
                "started_at": selected_episode.get("started_at"),
                "finished_at": selected_episode.get("finished_at"),
                "cost_lower_bound_usd": row["cost_usd"],
                "input_tokens": row["input_tokens"],
                "output_tokens": row["output_tokens"],
                "cost_usd": actual_cost,
                "full_actual_usage": actual_cost is not None,
            }
        result.append(
            {
                "model": key[0],
                "mode": mode,
                "reasoning_effort": key[1],
                "trials": sorted(trial_rows, key=lambda row: row["seed"]),
                "selected_run_id": selected_row["run_id"] if selected_row else None,
                "selected": selected_row,
            }
        )
    return result


def _load_episodes(submissions: Path) -> list[dict]:
    dated = next(
        (match.group() for part in submissions.parts if (match := DATE_RE.search(part))), None
    )
    if dated is None:
        raise ValueError("The V2 campaign submissions directory must include an ISO date")
    loaded = load_submissions(submissions)
    included = []
    for path, submission in loaded:
        key = _submission_group(submission)
        if key in GROUP_ORDER:
            included.append((path, submission))
        elif key not in EXCLUDED_MAX_GROUPS:
            raise ValueError(f"Unexpected V2 publication submission group: {key}")
    keys = [_submission_group(submission) for _, submission in included]
    if len(included) != len(EXPECTED_GROUPS) or set(keys) != set(EXPECTED_GROUPS):
        missing = sorted(set(EXPECTED_GROUPS) - set(keys), key=str)
        raise ValueError(f"Expected exactly the 14 fixed V2 submissions; missing: {missing}")
    if len({submission.flightbench.source_hash for _, submission in included}) != 1:
        raise ValueError("All V2 publication submissions must share one benchmark source hash")
    episodes = []
    for path, submission in included:
        if submission.evaluation.scoring_version != "v2":
            raise ValueError(f"Submission is not scoring v2: {path}")
        if submission.evaluation.scoring_config_sha256 != CANONICAL_SCORING_CONFIG_SHA256:
            raise ValueError(f"Submission uses a non-canonical scoring configuration: {path}")
        if submission.evaluation.modes != ["lockstep"] or len(submission.runs) != len(TRIAL_SEEDS):
            raise ValueError(f"Submission must contain three lockstep trials: {path}")
        artifacts = {artifact.sha256: artifact.path for artifact in submission.artifacts}
        for run in submission.runs:
            episodes.append(_read_artifact(path.parent / artifacts[run.artifact_sha256]))
    return episodes


def _model_name(model: str) -> str:
    return {
        "gpt-6.1-terra": "GPT-6.1 Terra",
        "gpt-6.1-sol": "GPT-6.1 Sol",
        "gpt-6-astra": "GPT-6 Astra",
        "gpt-6-luna": "GPT-6 Luna",
        "jev-1.13.0": "Jev 1.13",
        "jev-1.14.0": "Jev 1.14",
    }[model]


def _money(value: float) -> str:
    return f"${value:.6f}"


def _svg(groups: list[dict]) -> str:
    plotted = [
        group
        for group in groups
        if group["selected"]
        and (group["selected"]["cost_usd"] or group["selected"].get("cost_lower_bound_usd"))
    ]
    costs = [
        (group["selected"]["cost_usd"] or group["selected"].get("cost_lower_bound_usd"))
        for group in plotted
    ]
    low, high = (min(costs), max(costs)) if costs else (0.001, 1.0)
    tick = 10 ** math.floor(math.log10(low))
    cost_ticks = [tick]
    while cost_ticks[-1] < high:
        cost_ticks.append(cost_ticks[-1] * 4)
    if len(cost_ticks) == 1:
        cost_ticks.append(cost_ticks[-1] * 4)
    axis_low, axis_high = cost_ticks[0], cost_ticks[-1]

    def x(cost: float) -> float:
        return 90 + math.log(cost / axis_low) / math.log(axis_high / axis_low) * 980

    def y(score: float) -> float:
        return 620 - max(0.0, min(100.0, score)) * 5.0

    colors = {
        "gpt-6.1-terra": "#c27b1b",
        "gpt-6.1-sol": "#c27b1b",
        "gpt-6-astra": "#c27b1b",
        "gpt-6-luna": "#c27b1b",
        "jev-1.13.0": "#000c8b",
        "jev-1.14.0": "#0b5551",
    }
    shapes = {
        "gpt-6.1-terra": "earth",
        "gpt-6-luna": "moon",
        "gpt-6.1-sol": "sun",
        "gpt-6-astra": "star",
        "jev-1.13.0": "plane",
        "jev-1.14.0": "plane",
    }

    def marker(model: str, cx: float, cy: float, size: float = 8, title: str = "") -> str:
        color = colors[model]
        title_tag = f"<title>{html.escape(title)}</title>" if title else ""
        if shapes[model] == "earth":
            body = f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{size * 0.8:.1f}"/>'
        elif shapes[model] == "plane":
            body = f'<path transform="translate({cx:.1f} {cy:.1f}) scale({size / 13:.3f})" d="M0-13l3 10 10 5v4l-10-2-2 7 4 3v2l-5-1-5 1v-2l4-3-2-7-10 2v-4l10-5z"/>'
        elif shapes[model] == "moon":
            body = f'<path transform="translate({cx:.1f} {cy:.1f}) scale({size / 13:.3f})" d="M5-12A13 13 0 1 0 5 12A12.5 12.5 0 0 1 5-12Z"/>'
        elif shapes[model] == "sun":
            body = f'<g transform="translate({cx:.1f} {cy:.1f}) scale({size / 16:.3f})"><circle r="8"/><path d="M0-11V-16 M0 11V16 M-11 0H-16 M11 0H16 M-8-8l-4-4 M8 8l4 4 M8-8l4-4 M-8 8l-4 4" stroke="{color}" stroke-width="2.5"/></g>'
        else:
            points = []
            for index in range(10):
                radius = size if index % 2 == 0 else size * 0.42
                angle = math.radians(-90 + index * 36)
                points.append(
                    f"{cx + radius * math.cos(angle):.1f},{cy + radius * math.sin(angle):.1f}"
                )
            body = f'<polygon points="{" ".join(points)}"/>'
        return f'<g fill="{color}" stroke="white" stroke-width="1.5">{title_tag}{body}</g>'

    lines = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1180 700" role="img" aria-labelledby="title desc">',
        '<title id="title">FlightBench landing score versus API-equivalent cost</title>',
        '<desc id="desc">Selected-flight scores; the accompanying text explains three-flight selection and user-selected retry exceptions. Modes are written beside Jev points. Incomplete costs are plotted at their recorded lower bound and identified in the accompanying table. GPT model families connect low, medium, high and xhigh reasoning effort in that order. Costs use only complete recorded token usage and are not subscription charges.</desc>',
        '<rect width="1180" height="700" rx="18" fill="#f8fafc"/>',
        '<text x="90" y="34" font-family="system-ui,sans-serif" font-size="21" font-weight="700" fill="#172033">FlightBench: landing score vs API-equivalent cost</text>',
    ]
    active_families = (
        *FAMILIES,
        *(("gpt-6.1-terra",) if any(g["model"] == "gpt-6.1-terra" for g in groups) else ()),
    )
    for index, model in enumerate(active_families):
        legend_x = 92 + (index % 3) * 335
        legend_y = 65 + (index // 3) * 30
        lines.append(marker(model, legend_x, legend_y - 4, 14))
        lines.append(
            f'<text x="{legend_x + 24}" y="{legend_y:.1f}" font-family="system-ui,sans-serif" font-size="18" font-weight="600" fill="#273549">{html.escape(_model_name(model))}</text>'
        )
    for score in range(0, 101, 20):
        yy = y(score)
        lines.append(f'<path d="M90 {yy:.1f}H1070" stroke="#dbe3ec"/>')
        lines.append(
            f'<text x="78" y="{yy + 4:.1f}" text-anchor="end" font-family="system-ui,sans-serif" font-size="16" fill="#526174">{score}</text>'
        )
    for value in cost_ticks:
        xx = x(value)
        label = f"{value:g}"
        lines.append(f'<path d="M{xx:.1f} 120V620" stroke="#e6ebf1"/>')
        lines.append(
            f'<text x="{xx:.1f}" y="642" text-anchor="middle" font-family="system-ui,sans-serif" font-size="16" fill="#526174">${label}</text>'
        )
    lines += [
        '<path d="M90 120V620H1070" fill="none" stroke="#405066" stroke-width="1.5"/>',
        '<text x="580" y="680" text-anchor="middle" font-family="system-ui,sans-serif" font-size="19" fill="#273549">API-equivalent cost per selected full run (USD, log scale)</text>',
        '<text transform="translate(25 370) rotate(-90)" text-anchor="middle" font-family="system-ui,sans-serif" font-size="19" fill="#273549">Landing score (0–100)</text>',
    ]
    by_key = {(group["model"], group["reasoning_effort"]): group for group in groups}
    effort_labels = dict(zip(EFFORTS, ("low", "med", "high", "xhigh"), strict=True))
    # Keep clustered effort labels on opposite sides of their own markers.
    effort_offsets = {
        "gpt-6-luna": (
            (-1, 32, "middle"),
            (0, -25, "middle"),
            (0, 32, "middle"),
            (8, -25, "middle"),
        ),
        "gpt-6.1-sol": ((-12, -24, "end"), (-16, 35, "end"), (10, -34, "start"), (22, 7, "start")),
        "gpt-6.1-terra": (
            (-12, -25, "end"),
            (-22, -10, "end"),
            (-24, 7, "end"),
            (22, 20, "start"),
        ),
        "gpt-6-astra": ((-21, -12, "end"), (-18, 35, "end"), (15, -29, "start"), (22, 20, "start")),
    }
    for model in (*FAMILIES[:3], "gpt-6.1-terra"):
        points = []
        segments = []
        segment = []
        for effort in EFFORTS:
            selected = by_key.get((model, effort), {}).get("selected")
            if selected and selected["cost_usd"]:
                point = (effort, selected, x(selected["cost_usd"]), y(selected["score"]))
                points.append(point)
                segment.append(point)
            elif segment:
                segments.append(segment)
                segment = []
        if segment:
            segments.append(segment)
        for connected in segments:
            if len(connected) < 2:
                continue
            coordinates = " ".join(f"{xx:.1f},{yy:.1f}" for _, _, xx, yy in connected)
            lines.append(
                f'<polyline points="{coordinates}" fill="none" stroke="{colors[model]}" stroke-width="2" stroke-linejoin="round" opacity="0.8"/>'
            )
        for effort, selected, xx, yy in points:
            title = f"{_model_name(model)} · {effort}: score {selected['score']:.3f}, {_money(selected['cost_usd'])}"
            lines.append(marker(model, xx, yy, 16, title))
            dx, dy, anchor = effort_offsets[model][EFFORTS.index(effort)]
            tx, ty = xx + dx, yy + dy
            effort_label = effort_labels[effort]
            lines.append(
                f'<text x="{tx:.1f}" y="{ty:.1f}" text-anchor="{anchor}" font-family="system-ui,sans-serif" font-size="16" font-weight="600" fill="{colors[model]}" paint-order="stroke" stroke="#f8fafc" stroke-width="5" stroke-linejoin="round">{effort_label}</text>'
            )
    for group in groups:
        model = group["model"]
        if not model.startswith("jev-"):
            continue
        selected = group["selected"]
        cost = selected["cost_usd"] or selected.get("cost_lower_bound_usd")
        if not cost:
            continue
        xx, yy = x(cost), y(selected["score"])
        mode = group.get("mode", "lockstep")
        bound = selected["cost_usd"] is None
        title = f"{_model_name(model)} {mode}: score {selected['score']:.3f}, {'at least ' if bound else ''}{_money(cost)}"
        lines.append(marker(model, xx, yy, 24, title))
        tx, ty = xx + 30, yy + 5
        if model == "jev-1.14.0" and mode == "lockstep":
            ty = yy - 24
        elif model == "jev-1.13.0" and mode == "lockstep":
            ty = yy + 27
        lines.append(
            f'<text x="{tx:.1f}" y="{ty:.1f}" font-family="system-ui,sans-serif" font-size="16" font-weight="700" fill="{colors[model]}">{mode}</text>'
        )
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def comparison_table(groups: list[dict]) -> str:
    reference = next(
        (
            g["selected"]
            for g in groups
            if g["model"] == "jev-1.14.0" and g.get("mode") == "lockstep"
        ),
        groups[-1]["selected"],
    )
    ref_latency = reference.get("diagnostics", {}).get("mean_latency_ms", 0)
    ref_cost = reference["cost_usd"]
    lines = [
        "| Controller | Score and result | Sim time and wall time (s) | Calls | Mean latency per call (s) | Latency vs Jev | Input / output tokens | Est. API cost | Cost vs Jev |",
        "| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for group in groups:
        row = group["selected"]
        d = row.get("diagnostics", {})
        effort = f" ({group['reasoning_effort']})" if group["reasoning_effort"] else ""
        mode = group.get("mode", "lockstep")
        latency = d.get("mean_latency_ms", 0) / 1000
        wall = (
            (
                datetime.fromisoformat(row["finished_at"])
                - datetime.fromisoformat(row["started_at"])
            ).total_seconds()
            if row.get("started_at") and row.get("finished_at")
            else None
        )
        wall_text = f"{wall:.1f}" if wall is not None else "—"
        sim = d.get("duration_s")
        sim_text = f"{sim:.1f}" if sim is not None else "—"
        latency_ratio = f"{latency * 1000 / ref_latency:.1f}×" if ref_latency else "—"
        cost = row["cost_usd"]
        lower = row.get("cost_lower_bound_usd")
        cost_text = (
            _money(cost)
            if cost is not None
            else ("≥" + _money(lower) + "†" if lower else "unknown")
        )
        ratio = (
            (
                f"{cost / ref_cost:.1f}×"
                if cost is not None
                else f"≥{lower / ref_cost:.1f}×"
                if lower
                else "—"
            )
            if ref_cost
            else "—"
        )
        tokens = " / ".join(
            f"{row[k]:,}" if row[k] is not None else "—" for k in ("input_tokens", "output_tokens")
        )
        lines.append(
            f"| {_model_name(group['model'])}{effort} · {mode} | {row['score']:.3f} · {row['status']} | {sim_text} / {wall_text} ({mode}) | {row['calls']} | {latency:.3f} | {latency_ratio} | {tokens} | {cost_text} | {ratio} |"
        )
    return "\n".join(lines)


def write_publication(
    groups: list[dict], output: Path, *, attempt_history: dict | None = None
) -> None:
    renderer = shutil.which("rsvg-convert")
    if renderer is None:
        raise RuntimeError("PNG rendering requires the native rsvg-convert executable")
    output.mkdir(parents=True, exist_ok=True)
    replacement = next(
        (g for g in groups if g.get("selection") == "user-selected successful seed42 retry"), None
    )
    retry_note = (
        "Luna high uses the successful seed42 retry selected by the user (78.507); this is not best-of-three attempts. After the original three failures, retries included a preflight HTTP429, one completed runway excursion and one timeout before the successful seed42 retry; seed101 was cancelled and seed202 was not started. All original and retry evidence is retained."
        if replacement
        else "Luna high retry evidence is not supplied; original results are displayed."
    )
    payload = {
        "schema_version": 1,
        "scoring_version": "v2",
        "scoring_config_sha256": CANONICAL_SCORING_CONFIG_SHA256,
        "selection": "highest score among three completed trials per model/effort/mode; lower seed breaks ties"
        + ("; Luna high uses user-selected successful seed42 retry" if replacement else ""),
        "cost": "selected full run; exact only with complete usage; lower bounds explicitly marked",
        "groups": groups,
        "attempt_history": attempt_history or {},
    }
    (output / "results.json").write_text(json.dumps(payload, indent=2) + "\n")
    count = len((attempt_history or {}).get("excluded_attempts", []))
    repeat_argument = (
        " --jev113-submissions leaderboard/campaigns/2026-10-26-jev113-repeat/submissions"
        if any(g.get("selection", "").startswith("best of new") for g in groups)
        else ""
    )
    if any(g.get("repeat_campaign") == "2026-10-26-realtime-repeat2" for g in groups):
        repeat_argument += " --jev113-realtime-submissions leaderboard/campaigns/2026-10-26-realtime-repeat2/submissions"
    text = f"""# FlightBench comparison

Except the explicitly selected Luna high retry below, each row uses the highest-scoring completed flight for seeds 42, 101 and 202, separately by model, effort and mode. A tie uses the lower seed. Jev 1.13 uses its new three-flight repeat in each mode when supplied; superseded trials remain in the JSON provenance. Max is excluded.

**Retry disclosure:** {count} interrupted controller/infrastructure attempts were archived for the original campaign; this is not a claim of only three total attempts per group. {retry_note}

{comparison_table(groups)}

† Realtime flights can finish with an outstanding request. These prices are **lower bounds**, not complete costs. The graph plots the recorded lower bound; this table marks the uncertainty. Ratios use the complete Jev 1.14 lockstep flight as reference, with lower-bound ratios marked ≥. Codex costs are API-equivalent estimates, not subscription charges; no flight cost is scaled.

The original lockstep source and October 26 realtime source differ only by audited validation guards; see [source transition](../../local-model-runtime/scoring-v2-realtime-2026-10-26/source-transition.md). Modes and measurement dates remain distinct. Only canonical scoring configuration `{CANONICAL_SCORING_CONFIG_SHA256}` is accepted.

![Landing score V2 versus API-equivalent cost](landing-score-vs-api-cost.svg)

[PNG version](landing-score-vs-api-cost.png) · [machine-readable results](results.json)

Reproduce the current comparison from the repository root:

```sh
.venv/bin/python examples/build_v2_publication.py \
  --submissions leaderboard/campaigns/2026-10-22-scoring-v2/submissions \
  --realtime-submissions leaderboard/campaigns/2026-10-26-realtime/submissions{repeat_argument} \
  --output docs/evaluations/2026-10-22-scoring-v2
```
"""
    (output / "README.md").write_text(text)
    svg = output / "landing-score-vs-api-cost.svg"
    svg.write_text(_svg(groups))
    subprocess.run(
        [renderer, "-b", "white", str(svg), "-o", str(svg.with_suffix(".png"))], check=True
    )


def realtime_groups(submissions: Path) -> list[dict]:
    expected = (("jev-1.13.0", None), ("jev-1.14.0", None))
    episodes = []
    for model, _ in expected:
        folder = submissions / (model.replace(".", "-") + "-realtime")
        from flightbench.leaderboard import validate_submission

        sub = validate_submission(json.loads((folder / "submission.json").read_text()), folder)
        if (
            sub.flightbench.source_hash
            != "sha256:ebbaf763d742e79e847f43f8f64f701ec923160f770960b0d6cecfe3c81fa128"
        ):
            raise ValueError("Realtime source is not the audited October 26 source")
        for artifact in sub.artifacts:
            episode = _read_artifact(folder / artifact.path)
            if episode["config"].get("realtime_response_policy") != "apply-on-arrival":
                raise ValueError("Realtime publication requires apply-on-arrival")
            episodes.append(episode)
    return select_groups(episodes, mode="realtime", expected_groups=expected)


def luna_replacement(submissions: Path) -> dict | None:
    from flightbench.leaderboard import validate_submission

    folder = submissions / "gpt-6-luna-high-landing-retry"
    path = folder / "submission.json"
    if not path.exists():
        return None
    sub = validate_submission(json.loads(path.read_text()), folder)
    if (
        sub.flightbench.source_hash
        != "sha256:ebbaf763d742e79e847f43f8f64f701ec923160f770960b0d6cecfe3c81fa128"
    ):
        raise ValueError("Replacement source is not the audited October 26 source")
    episodes = [_read_artifact(folder / a.path) for a in sub.artifacts]
    if not all(e["outcome"]["success"] for e in episodes):
        raise ValueError("Replacement requires a successful landing")
    group = select_groups(episodes, expected_groups=(("gpt-6-luna", "high"),), trial_seeds=(42,))[0]
    group["selection"] = "user-selected successful seed42 retry"
    group["attempt_evidence"] = "leaderboard/campaigns/2026-10-26-realtime/"
    history = submissions.parent / "attempt-history.json"
    if history.exists():
        group["attempt_history"] = json.loads(history.read_text())
    return group


def jev113_replacements(submissions: Path, modes=("lockstep", "realtime")) -> list[dict]:
    from flightbench.leaderboard import validate_submission

    groups = []
    for mode in modes:
        folder = submissions / ("jev-1-13-0-" + mode)
        sub = validate_submission(json.loads((folder / "submission.json").read_text()), folder)
        if (
            sub.flightbench.source_hash
            != "sha256:ebbaf763d742e79e847f43f8f64f701ec923160f770960b0d6cecfe3c81fa128"
        ):
            raise ValueError("Jev replacement source is not the audited October 26 source")
        episodes = [_read_artifact(folder / a.path) for a in sub.artifacts]
        if mode == "realtime" and any(
            e["config"].get("realtime_response_policy") != "apply-on-arrival" for e in episodes
        ):
            raise ValueError("Realtime publication requires apply-on-arrival")
        group = select_groups(episodes, mode=mode, expected_groups=(("jev-1.13.0", None),))[0]
        group["selection"] = "best of new three-flight repeat; previous cohort archived"
        groups.append(group)
    return groups


def build_publication(
    submissions: Path,
    output: Path,
    realtime_submissions: Path | None = None,
    jev113_submissions: Path | None = None,
    jev113_realtime_submissions: Path | None = None,
) -> None:
    history_path = submissions.parent / "attempt-history.json"
    history = json.loads(history_path.read_text()) if history_path.exists() else None
    episodes = _load_episodes(submissions)
    groups = select_groups(episodes)
    if realtime_submissions:
        if {e["source_identity"]["source_hash"] for e in episodes} != {
            "sha256:2583efb1a0c1437a432ab694a2bc05dd1b4dcffae64075618a1f04ad201f1d3e"
        }:
            raise ValueError("Combined publication requires the audited October 22 source")
        groups += realtime_groups(realtime_submissions)
        replacement = luna_replacement(realtime_submissions)
        if replacement:
            index = next(
                i
                for i, g in enumerate(groups)
                if g["model"] == "gpt-6-luna" and g["reasoning_effort"] == "high"
            )
            replacement["superseded_trials"] = groups[index]["trials"]
            groups[index] = replacement
    if jev113_submissions:
        if realtime_submissions is None:
            raise ValueError("Jev repeats require the audited base realtime campaign")
        for replacement in jev113_replacements(jev113_submissions):
            index = next(
                i
                for i, g in enumerate(groups)
                if g["model"] == "jev-1.13.0" and g["mode"] == replacement["mode"]
            )
            replacement["superseded_trials"] = groups[index]["trials"]
            groups[index] = replacement
    if jev113_realtime_submissions:
        if jev113_submissions is None:
            raise ValueError("Realtime repeat requires the earlier Jev repeat cohort")
        replacement = jev113_replacements(jev113_realtime_submissions, modes=("realtime",))[0]
        index = next(
            i
            for i, g in enumerate(groups)
            if g["model"] == "jev-1.13.0" and g["mode"] == "realtime"
        )
        replacement["superseded_trials"] = groups[index]["trials"]
        replacement["repeat_campaign"] = "2026-10-26-realtime-repeat2"
        groups[index] = replacement
    write_publication(groups, output, attempt_history=history)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submissions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--realtime-submissions", type=Path)
    parser.add_argument("--jev113-submissions", type=Path)
    parser.add_argument("--jev113-realtime-submissions", type=Path)
    args = parser.parse_args()
    build_publication(
        args.submissions,
        args.output,
        args.realtime_submissions,
        args.jev113_submissions,
        args.jev113_realtime_submissions,
    )
