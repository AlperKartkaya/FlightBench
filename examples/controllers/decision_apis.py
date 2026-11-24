"""Native OpenAI and Gemini Decisions transports for the frozen action space."""

import json
import os
from pathlib import Path
from time import perf_counter, sleep
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from flightbench.protocol import SharedActionDecision, action_space
from flightbench.runs import now


class OpenAIDecisionController:
    model = "gpt-6-luna"
    provider = "OpenAI Decisions API"
    endpoint = "https://api.openai.com/v1/decisions"
    key_name = "OPENAI_API_KEY"
    source_url = "https://developers.openai.com/api/docs/guides/decisions"

    def __init__(self):
        self._key = os.environ[self.key_name]
        self._log = Path(os.environ["FLIGHTBENCH_DECISION_LOG"])
        self._next_request_at = 0.0
        self.metadata = {
            "name": self.provider + " " + self.model,
            "model": self.model,
            "provider": self.provider,
            "controller_type": "ai",
            "local": False,
            "license": "proprietary hosted API",
            "source_url": self.source_url,
            "endpoint": self.endpoint,
        }

    def payload(self, observation, questions):
        return {
            "model": self.model,
            "input": [{"role": "user", "content": [{"type": "input_json", "data": observation}]}],
            "questions": [
                {
                    "type": "choice",
                    "name": axis,
                    "instructions": question["instructions"],
                    "choices": [
                        {"value": value, "description": description}
                        for value, description in question["criteria"].items()
                    ],
                }
                for axis, question in questions.items()
            ],
        }

    def decide(self, observation):
        # ExternalController supplies canonical state, including controls and motion.
        questions = {
            axis: {
                "type": "choice",
                "instructions": spec["instructions"],
                "criteria": {a["id"]: a["criterion"] for a in spec["actions"]},
            }
            for axis, spec in action_space()["phases"][observation["phase"]].items()
        }
        payload = self.payload(observation, questions)
        headers = {"Content-Type": "application/json"}
        headers.update(
            {"x-goog-api-key": self._key}
            if self.key_name == "GEMINI_API_KEY"
            else {"Authorization": "Bearer " + self._key}
        )
        for attempt in range(3):
            if self.key_name == "GEMINI_API_KEY":
                # Observed free-tier limit is 50k input tokens/minute; state uses about 2.4k.
                sleep(max(0, self._next_request_at - perf_counter()))
                self._next_request_at = perf_counter() + 4
            row = {"at": now(), "attempt": attempt + 1, "request": payload, "state": observation}
            started = perf_counter()
            try:
                with urlopen(
                    Request(self.endpoint, json.dumps(payload).encode(), headers), timeout=30
                ) as r:
                    row.update(status=r.status, response=json.load(r))
            except HTTPError as error:
                row.update(status=error.code, error_body=error.read().decode(errors="replace"))
                if self.key_name != "GEMINI_API_KEY" or error.code != 429 or attempt == 2:
                    raise RuntimeError(
                        f"Decision API HTTP {error.code}; see sanitized sidecar"
                    ) from None
            except Exception as error:
                row["exception_type"] = type(error).__name__
                raise
            finally:
                row["latency_ms"] = (perf_counter() - started) * 1000
                with self._log.open("a") as log:
                    log.write(
                        json.dumps(row, allow_nan=False).replace(self._key, "[REDACTED]") + "\n"
                    )
                    log.flush()
                    os.fsync(log.fileno())
            if row["status"] == 200:
                break
            sleep(60)
        response = row["response"]
        if response.get("truncated") or response.get("truncation"):
            raise ValueError("Decision API truncated input")
        if response.get("model", self.model) != self.model:
            raise ValueError("Unexpected decision model")
        answers = response["answers"]
        if isinstance(answers, list):
            if len(answers) != len(questions):
                raise ValueError("Missing or duplicate answers")
            answers = {a["name"]: a for a in answers}
        if set(answers) != set(questions) or any(a["type"] != "choice" for a in answers.values()):
            raise ValueError("Missing, refused, or unexpected decision answers")
        return SharedActionDecision.model_validate(
            {axis: answer["choice"] for axis, answer in answers.items()}
        ).model_dump()


class GeminiDecisionController(OpenAIDecisionController):
    model = "gemini-decision-1"
    provider = "Google Gemini Decisions API"
    endpoint = "https://generativelanguage.googleapis.com/v1beta/decisions"
    key_name = "GEMINI_API_KEY"
    source_url = "https://ai.google.dev/gemini-api/docs/decisions-api"

    def payload(self, observation, questions):
        return {"model": self.model, "input": json.dumps(observation), "questions": questions}
