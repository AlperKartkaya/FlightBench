from __future__ import annotations

import pytest

from flightbench import benchmark


def _episode(controller: str, usage: object, *, model: str | None = None) -> dict:
    return {
        "config": {"controller": controller, "model": model, "seed": 42},
        "outcome": {"quality": 1, "status": "landed"},
        "diagnostics": {"calls": 1},
        "decisions": [
            {
                "decision_info": {
                    "usage": usage,
                    "input": {"state": "test"},
                    "sdk_request": {"question": "hold"},
                }
            }
        ],
    }


@pytest.mark.parametrize("invalid", [-1, 1.5, "1", True])
@pytest.mark.parametrize("field", ["input_tokens", "output_tokens"])
def test_codex_malformed_token_counts_are_unknown(field: str, invalid: object) -> None:
    usage = {"input_tokens": 10, "output_tokens": 2}
    usage[field] = invalid

    row = benchmark.episode_rows([_episode("codex", usage, model="openai-codex/gpt-6-sol")])[0]

    assert row["input_tokens"] is None
    assert row["output_tokens"] is None
    assert row["cost_usd"] is None
    assert row["missing_usage"] == 1


@pytest.mark.parametrize("invalid", [-1, 1.5, "1", True])
@pytest.mark.parametrize("field", ["input_tokens", "output_tokens"])
def test_jev_malformed_actual_usage_is_not_replaced_by_proxy(field: str, invalid: object) -> None:
    usage = {"input_tokens": 10, "output_tokens": 0}
    usage[field] = invalid
    row = benchmark.episode_rows([_episode("jev", usage)])[0]

    assert row["input_tokens"] is None
    assert row["input_tokens_estimated"] is False
    assert row["cost_usd"] is None
    assert row["missing_usage"] == 1


@pytest.mark.parametrize("invalid", [-1, 1.5, "1", True])
def test_api_equivalent_cost_rejects_non_integer_token_counts(invalid: object) -> None:
    assert (
        benchmark.api_equivalent_cost("gpt-6-sol", {"input_tokens": invalid, "output_tokens": 0})
        is None
    )
