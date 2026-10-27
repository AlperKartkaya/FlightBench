"""Fixed-state local scoring replay, not a flight or optimal-action accuracy test."""

from __future__ import annotations

import argparse
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from time import perf_counter

from .local import SystemOneController
from .protocol import protocol_metadata
from .runs import now, source_identity


def replay(controller, cases: list[dict], repeats: int = 2) -> list[dict]:
    """Keep the first pass visible; repeated identical inputs expose warm/cache effects."""
    if repeats < 1:
        raise ValueError("repeats must be positive")
    results = []
    for repeat in range(repeats):
        for case in cases:
            started = perf_counter()
            command = controller.decide(deepcopy(case["observation"]))
            elapsed = perf_counter() - started
            results.append(
                {
                    "case": case["id"],
                    "repeat": repeat,
                    "latency_ms": elapsed * 1000,
                    "command": command.model_dump(),
                    "decision_info": deepcopy(controller.last_decision),
                }
            )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--states", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument(
        "--conditions", required=True, help="Hardware, load, warmup and awake conditions"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output exists; preserve prior evidence and choose a new path")
    controller = SystemOneController(args.model, args.endpoint)
    raw = args.states.read_bytes()
    result = {
        "kind": "fixed-state-diagnostic-v1",
        "started_at": now(),
        **protocol_metadata(),
        "source_identity": source_identity(),
        "states_sha256": hashlib.sha256(raw).hexdigest(),
        "cases": json.loads(raw),
        "controller": controller.metadata,
        "conditions": args.conditions,
        "interpretation": "No physics, no accuracy labels, no landing score; first pass retained. "
        "Repeat order is fixed; latency includes transport and possible runtime prefix cache. "
        "Native rendered tokens are not exposed by every backend.",
    }
    result["results"] = replay(controller, result["cases"], args.repeats)
    result["finished_at"] = now()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as output:
        output.write(json.dumps(result, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
