"""Render repeatability charts from checked-in trial data; no provider calls.

Run: uv run --no-sync --with vl-convert-python==1.9.0 python -m examples.build_trial_visuals
Use --refresh-local to re-export from locally retained, replay-verified episodes.
"""

import argparse
import csv
import gzip
import hashlib
import json
from collections import defaultdict
from math import isfinite
from statistics import mean
from uuid import UUID

from examples.build_benchmark_visuals import (
    MODELS as HISTORICAL_MODELS,
)
from examples.build_benchmark_visuals import (
    OUTPUT as HISTORICAL_OUTPUT,
)
from examples.build_benchmark_visuals import (
    ROOT,
    THEMES,
    figure_spec,
    load_rows,
)

OUTPUT = ROOT / "docs/benchmark"
SOURCE = OUTPUT / "ten-trial-results.csv"
SEEDS = (42, 101, 202, 303, 404, 505, 606, 707, 808, 909)
MODES = ("realtime", "lockstep")
SOL_MODEL = "openai-codex/gpt-6.2-sol"
DECISION_RATES = {
    "Microsoft-Decision-1": ("decision-1", "input_tokens", 0.042),
    "Microsoft-Decision-1.1": ("decision-1-1", "input_tokens", 0.042),
    "gpt-6-luna": ("gpt-6-luna", "input_tokens", 0.10),
    "gemini-decision-1": ("gemini-decision-1", "total_input_tokens", 0.10),
}
SCORED_STATUSES = {
    "landed",
    "unsafe_touchdown",
    "crash",
    "runway_excursion",
    "nose_first_contact",
    "out_of_bounds",
    "time_limit",
}
MODELS = {
    (model if model.startswith("jev-") else f"openai-codex/{model}"): (
        family,
        name,
        "" if model.startswith("jev-") else "low",
    )
    for model, (family, name) in HISTORICAL_MODELS.items()
} | {
    SOL_MODEL: ("GPT-6.2 Sol", "GPT-6.2 Sol", "low"),
    "Microsoft-Decision-1": ("Decision API", "Microsoft Decision 1", ""),
    "Microsoft-Decision-1.1": ("Decision API", "Microsoft Decision 1.1", ""),
    "gpt-6-luna": ("Decision API", "Luna Decision API", ""),
    "gemini-decision-1": ("Decision API", "Gemini Decision 1", ""),
    "glide-v1.2": ("Local", "GLiDE v1.2", ""),
    "bison-1": ("Local", "Bison 1", ""),
    "pplx-decider-v1.3": ("Local", "Decider v1.3 27B", ""),
    "knowline-31b-gen2": ("Local", "KnowLine-31B Gen2", ""),
    "groundhog-1": ("Local", "Groundhog 1", ""),
}
TRIAL_GROUPS = ("Jev", "Codex", "Local", "Decision API")
# Provider release dates (YYYYMMDD); see docs/benchmark/README.md.
RELEASE_DATES = {
    "Jev 1.14": 2026_10_14,
    "Jev 1.13": 2026_09_15,
    "GPT-6.2 Sol": 2026_11_17,
    "GPT-6.1 Terra": 2026_10_26,
    "GPT-6.1 Sol": 2026_09_29,
    "GPT-6 Luna": 2026_09_22,
    "GPT-6 Astra": 2026_09_03,
    "Bison 1": 2026_11_20,
    "Groundhog 1": 2026_11_20,
    "KnowLine-31B Gen2": 2026_11_13,
    "Decider v1.3 27B": 2026_11_12,
    "GLiDE v1.2": 2026_10_22,
    "Microsoft Decision 1.1": 2026_11_17,
    "Gemini Decision 1": 2026_11_11,
    "Luna Decision API": 2026_10_22,
    "Microsoft Decision 1": 2026_10_09,
}
GLIDE = "2026-11-20-glide-v1.2-easy-20-continuous"
BISON = "2026-11-21-bison-31b-easy-20"
SOL = "2026-11-24-gpt-6.2-sol-easy"
MS_11 = "2026-11-19-microsoft-decision-1.1-easy"
MS_11_REALTIME = "2026-11-25-microsoft-decision-1.1-realtime"
DECISION_REALTIME_MODELS = {
    "2026-11-26-decision-realtime-microsoft": "Microsoft-Decision-1",
    "2026-11-26-decision-realtime-luna": "gpt-6-luna",
    "2026-11-26-decision-realtime-gemini": "gemini-decision-1",
}
A100 = "2026-11-25-a100-lockstep"
CAMPAIGNS = (
    "2026-11-15-ten-trial-easy",
    MS_11,
    MS_11_REALTIME,
    *DECISION_REALTIME_MODELS,
    GLIDE,
    BISON,
    SOL,
)
FIELDS = (
    "campaign",
    "group",
    "mode",
    "model",
    "seed",
    "run_id",
    "status",
    "score",
    "mean_latency_ms",
    "api_cost_usd",
    "episode_sha256",
)


def summarize(trials):
    groups = defaultdict(dict)
    run_ids = set()
    for row in trials:
        mode, model = row["mode"], row["model"]
        key = (mode, model, row["campaign"], row["group"])
        seed, run_id = int(row["seed"]), UUID(row["run_id"])
        score = float(row["score"])
        latency = float(row["mean_latency_ms"])
        success = row["status"] == "landed"
        if (
            mode not in MODES
            or model not in MODELS
            or seed not in SEEDS
            or row["status"] not in SCORED_STATUSES
            or run_id in run_ids
            or seed in groups[key]
            or not isfinite(score)
            or not 0 <= score <= 100
            or (not success and score != 0)
            or not isfinite(latency)
            or latency <= 0
        ):
            raise ValueError(f"Invalid trial: {row}")
        run_ids.add(run_id)
        cost = float(row["api_cost_usd"]) if model == SOL_MODEL or model in DECISION_RATES else None
        if cost is not None and (not isfinite(cost) or cost <= 0):
            raise ValueError(f"Invalid flight cost: {row}")
        groups[key][seed] = (score if success else None, latency, cost)

    results = {}
    for (mode, model, _, _), runs in groups.items():
        expected = SEEDS[:1] if mode == "lockstep" and MODELS[model][0] == "Local" else SEEDS
        if set(runs) != set(expected) or (mode, model) in results:
            raise ValueError(f"Expected exactly one complete cohort for {mode}/{model}")
        successful = [score for score, _, _ in runs.values() if score is not None]
        stats = results[mode, model] = {
            "successful": len(successful),
            "failed": len(runs) - len(successful),
            "best": max(successful, default=None),
            "average": mean(successful) if successful else None,
            "mean_latency_s": mean(latency for _, latency, _ in runs.values()) / 1000,
        }
        if model == SOL_MODEL:
            # Match the historical columns: use the best flight, with the lowest seed on a tie.
            seed = max(runs, key=lambda s: (runs[s][0] if runs[s][0] is not None else -1, -s))
            _, latency, cost = runs[seed]
            stats.update(api_cost_usd=cost, mean_latency_s=latency / 1000)
        elif model in DECISION_RATES:
            stats["api_cost_usd"] = mean(cost for _, _, cost in runs.values())
    return results


def read_json(path):
    return json.loads(path.read_bytes())


def sha(data):
    return hashlib.sha256(data).hexdigest()


def decision_flight_cost(run, responses):
    """Price recorded provider responses, including a drained realtime response."""
    from flightbench.benchmark import api_equivalent_cost

    config = run["config"]
    model = config["model"]
    request_model, tokens_key, rate = DECISION_RATES[model]
    diagnostics = run["diagnostics"]
    decisions = run["decisions"]
    realtime = config["mode"] == "realtime"
    if (
        not responses
        or len(decisions) != diagnostics["calls"]
        or len(responses) != diagnostics["requests_started" if realtime else "calls"]
        or not 0 <= len(responses) - len(decisions) <= int(realtime)
        or (
            model.startswith("Microsoft-")
            and config["controller_metadata"]["deployment_type"] != "GlobalStandard"
        )
    ):
        raise ValueError("Decision usage does not match the priced deployment or call count")
    costs = []
    for index, event in enumerate(responses):
        response = event["response"]
        answers = response["answers"]
        if isinstance(answers, list):
            answers = {answer["name"]: answer for answer in answers}
        usage = response["usage"]
        tokens = usage[tokens_key]
        if (
            event["at"] < run["started_at"]
            or (index < len(decisions) and event["at"] > run["finished_at"])
            or event["request"]["model"] != request_model
            or response.get("model", model).lower() != model.lower()
            or (
                index < len(decisions)
                and {axis: answer["choice"] for axis, answer in answers.items()}
                != decisions[index]["decision_info"]["action_ids"]
            )
            or type(tokens) is not int
            or tokens <= 0
        ):
            raise ValueError("Decision response does not match the flight evidence")
        if model == "gpt-6-luna":
            # The /decisions endpoint uses Luna's standard input/cache rates but no output fee.
            cost = api_equivalent_cost(model, usage | {"output_tokens": 0})
            if cost is None or tokens > 272_000:
                raise ValueError("Incomplete or ineligible Luna Decisions usage")
        else:
            cost = tokens * rate / 1_000_000
        costs.append(cost)
    return sum(costs)


def refresh_local():
    from flightbench.benchmark import episode_rows

    trials = []
    for campaign in CAMPAIGNS:
        evidence = ROOT / "docs/evaluations" / campaign
        path = evidence / "status.json"
        if campaign in (SOL, MS_11_REALTIME, *DECISION_REALTIME_MODELS) and (
            not path.exists() or read_json(path)["state"] != "complete"
        ):
            continue
        status = read_json(path)
        if status["state"] != "complete":
            raise ValueError(f"Incomplete campaign: {campaign}")
        realtime_model = DECISION_REALTIME_MODELS.get(campaign)
        if realtime_model:
            source_hash = read_json(evidence / "source.json")["identity"]["source_hash"]
        elif campaign == MS_11_REALTIME:
            realtime_model = "Microsoft-Decision-1.1"
            source_hash = status["source_hash"]
        if campaign == MS_11:
            audit = read_json(evidence / "identical-score-audit.json")
            if (audit["audited_runs"], audit["unique_response_sequences"]) != (len(SEEDS), 1):
                raise ValueError("Microsoft Decision 1.1 repeats were not verified")

        glide_hashes = (
            read_json(evidence / "final-audit.json")["file_sha256"] if campaign == GLIDE else {}
        )
        bison_hashes = (
            {
                row["run_id"]: row["raw_episode_sha256"]
                for mode in read_json(evidence / "final-verification.json")["groups"].values()
                for row in mode["records"]
            }
            if campaign == BISON
            else {}
        )
        for group, runs in status["groups"].items():
            for row in runs:
                folder = ROOT / row["folder"]
                run_id = row["run_id"]
                episode_path = folder / f"{run_id}.json.gz"
                episode = episode_path.read_bytes()
                raw = gzip.decompress(episode)
                digest = "sha256:" + sha(episode)
                if campaign == GLIDE:
                    expected = "sha256:" + glide_hashes[str(episode_path.relative_to(ROOT))]
                elif campaign == BISON:
                    expected = digest if sha(raw) == bison_hashes[run_id] else None
                else:
                    (artifact,) = read_json(folder / "submission.json")["artifacts"]
                    expected = artifact["sha256"] if artifact["path"] == episode_path.name else None

                run, replay = json.loads(raw), read_json(folder / "replay.json")
                config, outcome = run["config"], run["outcome"]
                rescored = replay["rescored_result"]
                local = campaign in (GLIDE, BISON)
                schedule = "continuous" if local and group == "realtime" else "fixed"
                if not (
                    expected == digest
                    and replay["source_run_id"] == run["run_id"] == run_id
                    and replay["physics_replay_verified"]
                    and row["replay_verified"]
                    and all(outcome[f] == row[f] for f in ("status", "success", "quality"))
                    and outcome["status"] == rescored["reason"]
                    and all(outcome[f] == rescored[f] for f in ("success", "quality"))
                    and row["seed"] == config["seed"]
                    and outcome["success"] == (outcome["status"] == "landed")
                    and run["diagnostics"]["api_errors"] == 0
                    and config["scoring_version"] == "v2"
                    and config["scenario"] == "easy"
                    and config["decision_hz"] == 2
                    and config["time_scale"] == 1
                    and config["decision_schedule"] == schedule
                    and (not local or group == config["mode"])
                    and config["realtime_response_policy"]
                    == ("apply-on-arrival" if local else "discard-stale")
                    and config["reasoning_effort"] == "low"
                    and (
                        not realtime_model
                        or (
                            config["mode"] == "realtime"
                            and config["model"] == realtime_model
                            and run["source_identity"]["source_hash"] == source_hash
                        )
                    )
                ):
                    raise ValueError(f"Trial did not match its verified evidence: {folder}")
                if local and group == "lockstep" and row["seed"] != SEEDS[0]:
                    continue
                cost = None
                if campaign == SOL:
                    (usage,) = episode_rows([run])
                    cost = usage["cost_usd"]
                    if (
                        usage["missing_usage"]
                        or cost is None
                        or any(
                            decision["decision_info"]["usage"]["input_tokens"] > 272_000
                            for decision in run["decisions"]
                        )
                    ):
                        raise ValueError(f"Incomplete or ineligible short-context usage: {folder}")
                elif config["model"] in DECISION_RATES:
                    with (folder / "provider.jsonl").open() as journal:
                        responses = [
                            event
                            for line in journal
                            if (event := json.loads(line)).get("status") == 200
                        ]
                    cost = decision_flight_cost(run, responses)
                trials.append(
                    {
                        "campaign": campaign,
                        "group": group,
                        "mode": config["mode"],
                        "model": config["model"],
                        "seed": row["seed"],
                        "run_id": run_id,
                        "status": outcome["status"],
                        "score": outcome["quality"],
                        "mean_latency_ms": run["diagnostics"]["mean_latency_ms"],
                        "api_cost_usd": cost,
                        "episode_sha256": digest,
                    }
                )
    trials.extend(a100_trials())
    summarize(trials)
    with SOURCE.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(trials)


def a100_trials():
    evidence = ROOT / "docs/evaluations" / A100
    for path in sorted(evidence.glob("*-status.json")):
        status = read_json(path)
        if status.get("protocol") != "one-lockstep-ten-realtime":
            continue
        ((model, runs),) = status["groups"].items()
        realtime_complete = {r["seed"] for r in runs if r["mode"] == "realtime"} == set(SEEDS)
        for row in runs:
            mode = row["mode"]
            if mode == "realtime" and not realtime_complete:
                continue
            folder = ROOT / "leaderboard/campaigns" / A100 / model
            if mode == "realtime":
                folder /= mode
            folder /= str(row["seed"])
            run_id = row["run_id"]
            data = (folder / f"{run_id}.json.gz").read_bytes()
            digest = "sha256:" + sha(data)
            run = json.loads(gzip.decompress(data))
            config, outcome = run["config"], run["outcome"]
            replay = read_json(folder / "replay.json")
            rescored = replay["rescored_result"]
            if not (
                digest == row["episode_sha256"]
                and run_id == run["run_id"] == replay["source_run_id"]
                and row["input_question_answer_audit"]
                and row["replay_verified"]
                and replay["physics_replay_verified"]
                and all(outcome[key] == row[key] for key in ("status", "quality", "success"))
                and outcome["status"] == rescored["reason"]
                and all(outcome[key] == rescored[key] for key in ("quality", "success"))
                and outcome["success"] == (outcome["status"] == "landed")
                and run["diagnostics"]["api_errors"] == 0
                and run["source_identity"]["source_hash"] == status["source_hash"]
                and config["controller_metadata"]["model_revision"] == status["revision"]
                and config["model"] == model
                and config["mode"] == mode
                and config["scenario"] == "easy"
                and config["scoring_version"] == "v2"
                and config["decision_hz"] == 2
                and config["decision_schedule"] == ("fixed" if mode == "lockstep" else "continuous")
                and config["realtime_response_policy"] == "apply-on-arrival"
                and config["time_scale"] == 1
                and config["seed"] == row["seed"]
            ):
                raise ValueError(f"A100 trial did not match its verified evidence: {folder}")
            yield {
                "campaign": A100,
                "group": model,
                "mode": mode,
                "model": model,
                "seed": row["seed"],
                "run_id": run_id,
                "status": outcome["status"],
                "score": outcome["quality"],
                "mean_latency_ms": run["diagnostics"]["mean_latency_ms"],
                "api_cost_usd": None,
                "episode_sha256": digest,
            }


def merge_rows(historical, results):
    """Keep selected-flight metrics and show only low effort where applicable."""
    cohorts = {(mode, *MODELS[model]): stats for (mode, model), stats in results.items()}
    rows = []
    for row in historical:
        if row["effort"] not in ("", "low"):
            continue
        key = tuple(row[field] for field in ("mode", "family", "model", "effort"))
        stats = cohorts.pop(key, None)
        rows.append(with_scores(row, stats))
    reference = {r["mode"]: r for r in historical if r["model"] == "Jev 1.14"}
    for (mode, family, model, effort), stats in cohorts.items():
        cost = stats.get("api_cost_usd")
        reference_cost = reference[mode]["api_cost_usd"]
        reference_latency = reference[mode]["mean_latency_s"]
        row = {
            "mode": mode,
            "family": family,
            "model": model,
            "effort": effort,
            "api_cost_usd": cost,
            "cost_lower_bound_usd": None,
            "cost_ratio": cost / reference_cost if cost is not None and reference_cost else None,
            "mean_latency_s": stats["mean_latency_s"],
            "latency_ratio": stats["mean_latency_s"] / reference_latency
            if reference_latency
            else None,
        }
        rows.append(with_scores(row, stats))
    for mode in MODES:
        eligible = [
            r for r in rows if r["mode"] == mode and r["segments"] and r["score"] is not None
        ]
        best = max((r["score"] for r in eligible), default=None)
        average = max((r["trial_average_score"] for r in eligible), default=None)
        for row in eligible:
            row["trial_highest"] = row["score"] == best
            row["trial_average_highest"] = row["trial_average_score"] == average
    return sorted(
        (
            row
            for row in rows
            if row["mode"] != "realtime" or (row["segments"] and row["score"] is not None)
        ),
        key=lambda row: (
            MODES.index(row["mode"]),
            TRIAL_GROUPS.index("Codex" if row["effort"] else row["family"]),
            row["score"] is None,
            -RELEASE_DATES[row["model"]],
            row["model"],
        ),
    )


def with_scores(row, stats):
    if stats is None:
        return dict(
            row,
            segments=[],
            trial_best=f"{row['score']:.2f}",
            trial_average="—",
            score_source="Historical",
            trial_highest=False,
            trial_average_highest=False,
        )
    count = stats["successful"]
    if row["mode"] == "lockstep" and row["model"] == "Microsoft Decision 1.1":
        if count != len(SEEDS) or stats["best"] != stats["average"]:
            raise ValueError("Microsoft Decision 1.1 display requires ten identical successes")
        kinds = ["repeat"] * 9 + ["success"]
    elif row["mode"] == "lockstep" and row["family"] == "Local":
        if count + stats["failed"] != 1:
            raise ValueError("Local lockstep requires exactly one flight")
        kinds = ["repeat"] * 9 + ["success" if count else "fail"]
    else:
        kinds = ["success"] * count + ["fail"] * stats["failed"]
    return dict(
        row,
        score=stats["best"],
        segments=[{"i": i, "kind": kind} for i, kind in enumerate(kinds)],
        trial_best=f"{stats['best']:.2f}" if count else "—",
        trial_average=f"{stats['average']:.2f}" if count else "—",
        trial_average_score=stats["average"],
        score_source="",
        trial_highest=False,
        trial_average_highest=False,
    )


def chart(results, theme):
    import vl_convert as vlc

    historical = load_rows(HISTORICAL_OUTPUT / "results.json")
    spec = figure_spec(merge_rows(historical, results), theme, trial_scores=True)
    return vlc.vegalite_to_svg(spec, vl_version="6.4") + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-local", action="store_true")
    if parser.parse_args().refresh_local:
        refresh_local()
    with SOURCE.open(newline="") as handle:
        results = summarize(csv.DictReader(handle))
    for theme in THEMES:
        (OUTPUT / f"ten-trial-{theme}.svg").write_text(chart(results, theme))


if __name__ == "__main__":
    main()
