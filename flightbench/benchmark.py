"""Headless FlightBench benchmark CLI."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from copy import deepcopy
from pathlib import Path
from statistics import mean
from time import perf_counter, sleep

from .controllers import ControlCommand, make_controller
from .core import (
    OBSERVATION_SCHEMA_VERSION,
    PHYSICS_HZ,
    decision_timing,
)
from .decision_tracking import DecisionTracker
from .environment import FixedWingLandingEnv
from .runs import RunSettings, effective_config, new_run_id, save_record, source_identity
from .runs import now as utc_now
from .temporal import TelemetryHistory

DEFAULT_TIMEOUT_S = 10.0
INCOMPLETE_STATUSES = {"interrupted", "error", "controller_timeout", "controller_error"}
# USD per million tokens, Standard short-context rates (2026-09-27).
# https://developers.openai.com/api/docs/pricing
CODEX_RATES = {
    "gpt-6-luna": (0.10, 0.01, 0.125, 0.50),
    "gpt-6-sol": (2.00, 0.20, 2.50, 10.00),
    "gpt-6-astra": (10.00, 1.00, 12.50, 50.00),
}
JEV_INPUT_RATE = 0.042  # https://typesafe.ai/blog/introducing-system-one-models-and-jev


def _action_dict(action: ControlCommand) -> dict[str, float]:
    if hasattr(action, "model_dump"):
        return action.model_dump()
    return {
        name: float(getattr(action, name)) for name in ("aileron", "elevator", "rudder", "throttle")
    }


def _result(snapshot: dict) -> dict:
    result = snapshot.get("result") or {}
    return {
        "success": bool(result.get("success", False)),
        "quality": float(
            result.get("quality", result.get("score", snapshot.get("score", 0.0))) or 0
        ),
        "status": result.get("reason", snapshot.get("status", "unknown")),
        "touchdown": result.get("touchdown"),
    }


def run_episode(
    controller_name: str,
    seed: int,
    mode: str = "lockstep",
    scenario: str = "easy",
    model: str | None = None,
    decision_hz: int = 2,
    time_scale: float = 1.0,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    log_path: Path | None = None,
    record_dir: Path | None = None,
    run_id: str | None = None,
) -> dict:
    """Run one deterministic episode without making any provider assumptions."""
    settings = RunSettings(
        controller=controller_name,
        seed=seed,
        mode=mode,
        scenario=scenario,
        model=model,
        decision_hz=decision_hz,
        time_scale=time_scale,
    )
    decision_ticks, decision_interval_s = decision_timing(decision_hz)
    if controller_name == "human":
        raise ValueError("human controller is available through the realtime WebSocket UI")
    if log_path and log_path.exists():
        raise FileExistsError(log_path)
    identity = source_identity()
    started_at = utc_now()
    run_id = run_id or new_run_id()
    try:
        env = FixedWingLandingEnv(scenario=scenario, max_time_s=120, decision_hz=decision_hz)
    except TypeError:
        env = FixedWingLandingEnv(scenario=scenario, max_time_s=120)
    env_interval_s = getattr(env, "decision_interval_s", decision_interval_s)
    observation, _ = env.reset(seed=seed)
    initial_observation = observation
    initial_snapshot = env.snapshot()
    controller = make_controller(
        controller_name,
        seed=seed,
        model=model,
        decision_hz=decision_hz,
    )
    from .core import TRIM_AILERON, TRIM_ELEVATOR, TRIM_RUDDER

    action = ControlCommand(
        aileron=TRIM_AILERON,
        elevator=TRIM_ELEVATOR,
        rudder=TRIM_RUDDER,
        throttle=0.5,
    )
    decisions: list[dict] = []
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="flightbench-controller")
    decision_index = 0
    terminal_error = None
    tracker = DecisionTracker()
    telemetry = TelemetryHistory()
    telemetry.add(observation)

    def _enrich(obs: Mapping) -> dict:
        """Build enriched observation for controller with temporal and decision feedback."""
        enriched = dict(obs)
        enriched["temporal"] = telemetry.features(enriched)
        enriched["timing"] = {
            "sim_time_s": enriched.get("time_s", 0.0),
            "decision_interval_s": env_interval_s,
        }
        enriched["decision_feedback"] = tracker.build_feedback(
            enriched, float(enriched.get("time_s", 0.0))
        )
        return enriched

    def _record_transition(
        ctrl: object, old_action: ControlCommand, new_action: ControlCommand, obs: Mapping
    ) -> None:
        """Record a control transition in the tracker if the controller provides details."""
        transition = getattr(ctrl, "last_transition_details", None)
        if transition:
            controls = obs.get("controls", {}) if isinstance(obs, Mapping) else {}
            tracker.record_application(
                action_id=transition["action_id"],
                action_names=transition["action_names"],
                sim_time=float(obs.get("time_s", 0.0)),
                control_before={
                    a: float(controls.get(a, getattr(old_action, a)))
                    for a in ("aileron", "elevator", "rudder", "throttle")
                },
                control_after={
                    a: float(getattr(new_action, a))
                    for a in ("aileron", "elevator", "rudder", "throttle")
                },
                state_snapshot=obs,
            )

    try:
        if mode == "lockstep":
            while not env.done:
                decision_observation = deepcopy(observation)
                enriched = _enrich(decision_observation)
                started = perf_counter()
                error = None
                decision_info = None
                try:
                    next_action = executor.submit(controller.decide, enriched).result(
                        timeout=timeout_s
                    )
                    decision_info = getattr(controller, "last_decision", None)
                except TimeoutError:
                    next_action, error = None, "controller_timeout"
                except Exception:  # noqa: BLE001 - provider errors must stay sanitized
                    next_action, error = None, "controller_error"
                latency_s = perf_counter() - started
                control_before = _action_dict(action)
                if next_action is not None:
                    _record_transition(controller, action, next_action, observation)
                    action = next_action
                control_after = _action_dict(action)
                decision_index += 1
                choices = (decision_info or {}).get("choices", {}).get("joint_action", {})
                decisions.append(
                    {
                        "type": "decision",
                        "decision_id": f"decision_{decision_index}",
                        "index": decision_index,
                        "observation_schema_version": OBSERVATION_SCHEMA_VERSION,
                        "observation_sim_time_s": decision_observation.get("time_s"),
                        "applied_sim_time_s": decision_observation.get("time_s"),
                        "request_wall_time_s": round(started, 4),
                        "response_wall_time_s": round(started + latency_s, 4),
                        "round_trip_ms": round(latency_s * 1000, 3),
                        "latency_ms": round(latency_s * 1000, 3),
                        "state_age_at_application_ms": 0.0,
                        "observation": decision_observation,
                        "legal_joint_action_count": choices.get("legal_count"),
                        "returned_option_count": choices.get("returned_option_count"),
                        "probability_sum": choices.get("probability_sum"),
                        "selected_joint_action": choices.get("action"),
                        "selected_probability": choices.get("selected_probability"),
                        "probabilities": choices.get("probabilities"),
                        "raw_returned_distribution": choices.get("raw_returned_distribution"),
                        "sdk_request": (decision_info or {}).get("sdk_request"),
                        "control_before": control_before,
                        "control_after": control_after,
                        "state_at_application": decision_observation,
                        "action": _action_dict(action),
                        "decision_info": decision_info,
                        "error": error,
                    }
                )
                if error:
                    terminal_error = error
                    break
                observation, _, _, _, _ = env.step(action)
                telemetry.add(observation)
        else:
            pending = None
            pending_started = 0.0
            pending_observation = None
            ticks = 0
            deadline = perf_counter()
            while not env.done:
                now = perf_counter()
                if pending and pending.done():
                    error = None
                    decision_info_rt = None
                    try:
                        new_action_rt = pending.result()
                        decision_info_rt = getattr(controller, "last_decision", None)
                    except Exception:  # noqa: BLE001 - provider errors must stay sanitized
                        new_action_rt = None
                        error = "controller_error"
                    applied_time = observation.get("time_s", 0.0)
                    obs_time = pending_observation.get("time_s", 0.0)
                    state_age_ms = round(max(0.0, (applied_time - obs_time) * 1000), 1)
                    stale = state_age_ms > 2 * env_interval_s * 1000
                    control_before = _action_dict(action)
                    if new_action_rt is not None and not stale:
                        _record_transition(controller, action, new_action_rt, observation)
                        action = new_action_rt
                    control_after = _action_dict(action)
                    decision_index += 1
                    choices_rt = (decision_info_rt or {}).get("choices", {}).get("joint_action", {})
                    decisions.append(
                        {
                            "type": "decision",
                            "decision_id": f"decision_{decision_index}",
                            "index": decision_index,
                            "observation_schema_version": OBSERVATION_SCHEMA_VERSION,
                            "observation_sim_time_s": obs_time,
                            "applied_sim_time_s": applied_time,
                            "request_wall_time_s": round(pending_started, 4),
                            "response_wall_time_s": round(now, 4),
                            "round_trip_ms": round((now - pending_started) * 1000, 3),
                            "latency_ms": round((now - pending_started) * 1000, 3),
                            "state_age_at_application_ms": state_age_ms,
                            "applied": not stale and new_action_rt is not None,
                            "discard_reason": "stale_observation" if stale else None,
                            "observation": pending_observation,
                            "legal_joint_action_count": choices_rt.get("legal_count"),
                            "returned_option_count": choices_rt.get("returned_option_count"),
                            "probability_sum": choices_rt.get("probability_sum"),
                            "selected_joint_action": choices_rt.get("action"),
                            "selected_probability": choices_rt.get("selected_probability"),
                            "probabilities": choices_rt.get("probabilities"),
                            "raw_returned_distribution": choices_rt.get(
                                "raw_returned_distribution"
                            ),
                            "sdk_request": (decision_info_rt or {}).get("sdk_request"),
                            "control_before": control_before,
                            "control_after": control_after,
                            "state_at_application": observation,
                            "action": _action_dict(action),
                            "decision_info": decision_info_rt,
                            "error": error,
                        }
                    )
                    pending = None
                    if error:
                        terminal_error = error
                        break
                elif pending and now - pending_started >= timeout_s:
                    terminal_error = "controller_timeout"
                    decision_index += 1
                    decisions.append(
                        {
                            "type": "decision",
                            "index": decision_index,
                            "observation_schema_version": OBSERVATION_SCHEMA_VERSION,
                            "sim_time_s": pending_observation.get("time_s"),
                            "latency_ms": round(timeout_s * 1000, 3),
                            "observation": pending_observation,
                            "action": _action_dict(action),
                            "error": "controller_timeout",
                        }
                    )
                    break
                if pending is None and ticks % decision_ticks == 0:
                    pending_observation = deepcopy(observation)
                    enriched = _enrich(pending_observation)
                    pending_started = perf_counter()
                    pending = executor.submit(controller.decide, enriched)

                observation, _, _, _, _ = env.advance(action, ticks=1)
                telemetry.add(observation)
                ticks += 1
                deadline += 1 / (PHYSICS_HZ * time_scale)
                sleep(max(0, deadline - perf_counter()))
            if pending:
                pending.cancel()
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    outcome = _result(env.snapshot())
    if terminal_error:
        outcome.update(success=False, quality=0.0, status=terminal_error)
    config = effective_config(settings, controller)
    latencies = [d["latency_ms"] for d in decisions]
    interventions = {"fallback": 0, "stability_hold": 0, "applied": 0}
    for decision in decisions:
        applied = decision.get("applied", True) and not decision.get("error")
        if not applied:
            continue
        choice = ((decision.get("decision_info") or {}).get("choices") or {}).get(
            "joint_action"
        ) or {}
        interventions["applied"] += 1
        interventions["fallback"] += bool((choice.get("fallback") or {}).get("active"))
        interventions["stability_hold"] += bool(
            (choice.get("stability_maintainer") or {}).get("triggered")
        )
    diagnostics = {
        "decision_count": interventions["applied"],
        "mean_latency_ms": mean(latencies) if latencies else 0.0,
        "calls": len(decisions),
        "late_decisions": sum(latency > 1000 / (decision_hz * time_scale) for latency in latencies)
        if mode == "realtime"
        else 0,
        "stale_decisions": sum(d.get("discard_reason") == "stale_observation" for d in decisions),
        "api_errors": sum(bool(d.get("error")) for d in decisions),
        "last_api_error": next((d["error"] for d in reversed(decisions) if d.get("error")), None),
        "interventions": interventions,
        "duration_s": observation.get("time_s", 0.0),
    }
    final_state = env.snapshot()
    record = {
        "schema_version": 1,
        "run_id": run_id,
        "source": "cli",
        "started_at": started_at,
        "finished_at": utc_now(),
        "config": config,
        "source_identity": identity,
        "initial_observation": initial_observation,
        "final_state": final_state,
        "outcome": outcome,
        "diagnostics": diagnostics,
        "type": "episode",
        "controller": controller_name,
        "model": model,
        "scenario": scenario,
        "mode": mode,
        "seed": seed,
        "decision_count": diagnostics["decision_count"],
        "decision_hz": decision_hz,
        "time_scale": time_scale,
        "mean_latency_ms": diagnostics["mean_latency_ms"],
        "decisions": decisions,
        **outcome,
    }
    if record_dir:
        save_record(record, record_dir)
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("x", encoding="utf-8") as output:
            output.write(
                json.dumps(
                    {
                        "type": "metadata",
                        **{
                            key: record[key]
                            for key in ("controller", "model", "scenario", "mode", "seed")
                        },
                        "run_id": run_id,
                        "config": config,
                        "source_identity": record["source_identity"],
                        "versions": record["source_identity"]["versions"],
                        "initial_observation": initial_observation,
                        "scoring": initial_snapshot.get("result", {}).get("scoring"),
                    }
                )
                + "\n"
            )
            for decision in decisions:
                output.write(json.dumps(decision) + "\n")
            if outcome["touchdown"] is not None:
                output.write(json.dumps({"type": "touchdown", "data": outcome["touchdown"]}) + "\n")
            output.write(json.dumps(record) + "\n")
    return record


def summarize(episodes: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for episode in episodes:
        if "config" in episode:
            config = {key: value for key, value in episode["config"].items() if key != "seed"}
        else:
            config = {
                key: episode.get(key)
                for key in (
                    "controller",
                    "model",
                    "scenario",
                    "mode",
                    "action_variant",
                    "decision_hz",
                    "time_scale",
                )
            }
        config["source_hash"] = (episode.get("source_identity") or {}).get("source_hash")
        groups.setdefault(json.dumps(config, sort_keys=True), []).append(episode)
    summaries = []
    for key, rows in groups.items():
        outcomes = [row.get("outcome", row) for row in rows]
        # A stopped experiment is evidence, but not a completed landing trial.
        completed = [row for row in outcomes if row.get("status") not in INCOMPLETE_STATUSES]
        diagnostics = [row.get("diagnostics", row) for row in rows]
        summaries.append(
            {
                **json.loads(key),
                "episodes": len(rows),
                "completed_episodes": len(completed),
                "success_rate": mean(row["success"] for row in completed) if completed else None,
                "mean_quality": mean(row["quality"] for row in completed) if completed else None,
                "mean_latency_ms": mean(row["mean_latency_ms"] for row in diagnostics),
                "failure_counts": dict(
                    Counter(row.get("status", "unknown") for row in completed if not row["success"])
                ),
                "incomplete_counts": dict(
                    Counter(
                        row.get("status", "unknown") for row in outcomes if row not in completed
                    )
                ),
            }
        )
    return summaries


def _csv(path: Path, rows: list[dict]) -> None:
    with path.open("x", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]) if rows else [])
        if rows:
            writer.writeheader()
            writer.writerows(rows)


def _episode_row(episode: dict) -> dict:
    """Build one report row, including usage recorded in the episode log."""
    config = episode.get("config") or {}
    model = config.get("model")
    controller = config.get("controller")
    decisions = episode.get("decisions") or []
    row = {
        "controller": controller,
        "model": model,
        "seed": config.get("seed"),
        "score": float((episode.get("outcome") or {}).get("quality") or 0),
        "status": (episode.get("outcome") or {}).get("status", "unknown"),
        "run_id": episode.get("run_id"),
        "calls": (episode.get("diagnostics") or {}).get("calls", len(decisions)),
        "input_tokens": None,
        "output_tokens": None,
        "cost_usd": None,
        "missing_usage": 0,
    }
    if controller == "codex" and isinstance(model, str):
        rates = CODEX_RATES.get(model.removeprefix("openai-codex/"))
        if rates:
            usage = [((d.get("decision_info") or {}).get("usage") or {}) for d in decisions]
            known = [u for u in usage if "input_tokens" in u and "output_tokens" in u]
            inputs = sum(u["input_tokens"] for u in known)
            outputs = sum(u["output_tokens"] for u in known)
            cached = sum(
                (u.get("input_tokens_details") or {}).get("cached_tokens", 0) for u in known
            )
            writes = sum(
                (u.get("input_tokens_details") or {}).get("cache_write_tokens", 0) for u in known
            )
            input_rate, cached_rate, write_rate, output_rate = rates
            row.update(
                input_tokens=inputs,
                output_tokens=outputs,
                missing_usage=len(usage) - len(known),
                cost_usd=(
                    (inputs - cached - writes) * input_rate
                    + cached * cached_rate
                    + writes * write_rate
                    + outputs * output_rate
                )
                / 1_000_000,
            )
    elif controller == "jev":
        requests = [(d.get("decision_info") or {}) for d in decisions]
        complete = [
            r for r in requests if r.get("input") is not None and r.get("sdk_request") is not None
        ]
        chars = sum(
            len(json.dumps(r["input"], separators=(",", ":")))
            + len(json.dumps(r["sdk_request"], separators=(",", ":")))
            for r in complete
        )
        row.update(
            input_tokens=round(chars / 4),
            missing_usage=len(requests) - len(complete),
            cost_usd=chars / 4 * JEV_INPUT_RATE / 1_000_000,
        )
    return row


def episode_rows(episodes: list[dict]) -> list[dict]:
    """Return one report row per episode, preserving input order."""
    return [_episode_row(episode) for episode in episodes]


def report_rows(episodes: list[dict]) -> list[dict]:
    """Select one highest-scoring completed episode per controller/model."""
    best = {}
    for episode in episodes:
        config = episode.get("config") or {}
        outcome = episode.get("outcome") or {}
        if outcome.get("status") in INCOMPLETE_STATUSES:
            continue
        key = (config.get("controller"), config.get("model"))
        if key[0] is None:
            continue
        previous = best.get(key)
        rank = (float(outcome.get("quality") or 0), -int(config.get("seed") or 0))
        if previous is None or rank > previous[0]:
            best[key] = (rank, episode)

    rows = [_episode_row(episode) for _, episode in best.values()]
    return sorted(
        rows,
        key=lambda row: (
            row["controller"] != "jev",
            row["cost_usd"] if row["cost_usd"] is not None else float("inf"),
            str(row["model"] or row["controller"]),
        ),
    )


def _report_values(row: dict) -> tuple[str, str, str]:
    model = (row["model"] or row["controller"]).removeprefix("openai-codex/")
    name = (
        "Jev"
        if row["controller"] == "jev"
        else ("GPT-6 " + model[6:].title() if model.startswith("gpt-6-") else model)
    )
    tokens = "—"
    if row["input_tokens"] is not None:
        output = f"{row['output_tokens']:,}" if row["output_tokens"] is not None else "—"
        prefix = "~" if row["controller"] == "jev" else ""
        tokens = f"{prefix}{row['input_tokens']:,} / {output}"
    cost = f"${row['cost_usd']:.5f}" if row["cost_usd"] is not None else "—"
    if row["missing_usage"] and row["cost_usd"] is not None:
        cost = "≥" + cost
    return name, tokens, cost


def report_markdown(rows: list[dict]) -> str:
    jev_cost = next((r["cost_usd"] for r in rows if r["controller"] == "jev"), None)
    lines = [
        "# Best completed run per controller/model",
        "",
        "| Controller | Seed | Score | Result | Calls | Input / output tokens | Est. API cost | vs Jev |",
        "| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        name, tokens, cost = _report_values(row)
        ratio = (
            f"{'≈' if row['controller'] != 'jev' else ''}{row['cost_usd'] / jev_cost:.1f}×"
            if jev_cost and row["cost_usd"] is not None
            else "—"
        )
        lines.append(
            f"| {name} | {row['seed']} | {row['score']:.3f} | {row['status']} | {row['calls']} | {tokens} | {cost} | {ratio} |"
        )
    if not rows:
        lines.append("\nNo completed episodes.")
    lines.extend(
        [
            "",
            "Where available, costs use recorded Codex response usage and [OpenAI Standard short-context rates](https://developers.openai.com/api/docs/pricing) as of 2026-09-27; they are not Codex-account charges. Jev input tokens are a rough four-characters-per-token proxy from its logged request data at [TypeSafe's published rate](https://typesafe.ai/blog/introducing-system-one-models-and-jev). Missing usage makes a cost a lower bound. Equal scores select the lowest seed.",
            "",
            "Selected run IDs: "
            + ", ".join(
                f"{('Jev' if r['controller'] == 'jev' else r['model'] or r['controller'])} `{r['run_id']}`"
                for r in rows
            )
            + ".",
        ]
    )
    return "\n".join(lines) + "\n"


def episode_markdown(rows: list[dict]) -> str:
    lines = [
        "# All benchmark episodes",
        "",
        "| Controller | Seed | Score | Result | Calls | Input / output tokens | Est. API cost | Run ID |",
        "| --- | ---: | ---: | --- | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        name, tokens, cost = _report_values(row)
        lines.append(
            f"| {name} | {row['seed']} | {row['score']:.3f} | {row['status']} | {row['calls']} | {tokens} | {cost} | `{row['run_id']}` |"
        )
    if not rows:
        lines.append("\nNo episodes.")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run reproducible FlightBench episodes")
    parser.add_argument("--controllers", default="hold,random,baseline")
    parser.add_argument("--seeds", default="42")
    parser.add_argument("--modes", default="lockstep")
    parser.add_argument("--scenario", default="easy")
    parser.add_argument("--model")
    parser.add_argument("--decision-hz", type=int, choices=(2, 5, 10), default=2)
    parser.add_argument("--time-scale", type=float, choices=(1.0, 0.5, 0.25), default=1.0)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    parser.add_argument("--output-dir", type=Path, default=Path("runs"))
    parser.add_argument("--summary-format", choices=("json", "csv"), default="json")
    parser.add_argument(
        "--report-records",
        nargs="+",
        type=Path,
        help="Render a report from saved episode records without running controllers",
    )
    args = parser.parse_args(argv)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    episodes = []
    if args.report_records:
        episodes = [json.loads(path.read_text(encoding="utf-8")) for path in args.report_records]
    else:
        for controller in args.controllers.split(","):
            for mode in args.modes.split(","):
                for seed_text in args.seeds.split(","):
                    seed = int(seed_text)
                    run_id = new_run_id()
                    name = f"{controller}-{mode}-seed-{seed}-{run_id}.jsonl"
                    episodes.append(
                        run_episode(
                            controller,
                            seed,
                            mode=mode,
                            scenario=args.scenario,
                            model=args.model,
                            decision_hz=args.decision_hz,
                            time_scale=args.time_scale,
                            timeout_s=args.timeout,
                            log_path=args.output_dir / name,
                            record_dir=args.output_dir,
                            run_id=run_id,
                        )
                    )
        summary = summarize(episodes)
        path = args.output_dir / f"summary-{new_run_id()}.{args.summary_format}"
        if args.summary_format == "csv":
            _csv(path, summary)
        else:
            with path.open("x", encoding="utf-8") as output:
                output.write(json.dumps(summary, indent=2) + "\n")
        print(path)

    report_id = new_run_id()
    rows = report_rows(episodes)
    report_path = args.output_dir / f"report-{report_id}.md"
    with report_path.open("x", encoding="utf-8") as output:
        output.write(report_markdown(rows))
    print(report_path)
    episodes_path = args.output_dir / f"episodes-{report_id}.md"
    with episodes_path.open("x", encoding="utf-8") as output:
        output.write(episode_markdown(episode_rows(episodes)))
    print(episodes_path)
