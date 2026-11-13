"""Azure transport for the existing frozen System One categorical controller."""

import json
import os
import subprocess
from pathlib import Path
from time import perf_counter, sleep
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flightbench.protocol import SharedActionDecision, action_space
from flightbench.runs import now

ENDPOINT = "https://alperkartkaya-flightbench.cognitiveservices.azure.com"
DEPLOYMENT = "decision-1"
MODEL = "Microsoft-Decision-1"
SOURCE_URL = (
    "https://learn.microsoft.com/en-us/azure/foundry/foundry-models/"
    "how-to/use-foundry-models-microsoft-decision"
)


class AzureDecisionController:
    def __init__(self):
        self.model_id = MODEL
        self._log = Path(os.environ["FLIGHTBENCH_AZURE_LOG"])
        self._log.parent.mkdir(parents=True, exist_ok=True)
        self._key = json.loads(
            subprocess.check_output(
                [
                    "az",
                    "cognitiveservices",
                    "account",
                    "keys",
                    "list",
                    "-g",
                    "flightbench",
                    "-n",
                    "AlperKartkaya-flightbench",
                    "-o",
                    "json",
                ],
                stderr=subprocess.DEVNULL,
            )
        )["key1"]
        self.metadata = {
            "name": MODEL,
            "slug": "microsoft-decision-1",
            "model": MODEL,
            "provider": "Microsoft Azure Foundry",
            "controller_type": "ai",
            "local": False,
            "license": "proprietary hosted API",
            "source_url": SOURCE_URL,
            "endpoint": ENDPOINT,
            "deployment": DEPLOYMENT,
            "model_version": "1",
            "deployment_type": "GlobalStandard",
            "transport": "systemone",
            "cost_methodology": "Provider token usage retained; invoiced cost not verified.",
        }

    def _request(self, method, payload):
        if method != "systemone":
            raise ValueError("Only the decision endpoint is supported")
        payload = {k: v for k, v in payload.items() if k != "keep_alive"}
        payload["model"] = DEPLOYMENT
        request = Request(
            ENDPOINT + "/providers/microsoft/v1/systemone",
            data=json.dumps(payload, allow_nan=False).encode(),
            headers={"Content-Type": "application/json", "api-key": self._key},
        )
        for attempt in range(4):
            started = perf_counter()
            row = {"at": now(), "attempt": attempt + 1, "request": payload}
            try:
                with urlopen(request, timeout=20) as response:
                    row.update(status=response.status, response=json.load(response))
            except HTTPError as error:
                row.update(status=error.code, error_body=error.read().decode(errors="replace"))
            except (URLError, TimeoutError) as error:
                row.update(status=0, exception_type=type(error).__name__)
            except Exception as error:
                row["exception_type"] = type(error).__name__
                raise
            finally:
                row["latency_ms"] = (perf_counter() - started) * 1000
                # Never serialize request headers or credentials.
                with self._log.open("a") as log:
                    log.write(
                        json.dumps(row, allow_nan=False).replace(self._key, "[REDACTED]") + "\n"
                    )
                    log.flush()
                    os.fsync(log.fileno())
            if row["status"] == 200:
                if row["response"].get("model", "").lower() != MODEL.lower():
                    raise ValueError("Unexpected model identity")
                return row["response"]
            if row["status"] not in {0, 429, 500, 502, 503, 504} or attempt == 3:
                raise RuntimeError(f"Azure decision HTTP {row['status']}; see sanitized sidecar")
            sleep(2 ** (attempt + 1))

    def decide(self, observation):
        # ExternalController already supplies the canonical observation; do not rebuild it.
        axes = action_space()["phases"][observation["phase"]]
        questions = {
            axis: {
                "type": "choice",
                "instructions": spec["instructions"],
                "criteria": {action["id"]: action["criterion"] for action in spec["actions"]},
            }
            for axis, spec in axes.items()
        }
        response = self._request(
            "systemone", {"model": DEPLOYMENT, "state": observation, "questions": questions}
        )
        usage = response.get("usage") or {}
        if (
            response.get("truncated")
            or response.get("truncation")
            or usage.get("truncated")
            or (
                usage.get("state_tokens_used") is not None
                and usage.get("state_tokens") is not None
                and usage["state_tokens_used"] < usage["state_tokens"]
            )
        ):
            raise ValueError("Azure model truncated the canonical observation")
        return SharedActionDecision.model_validate(
            {axis: answer["choice"] for axis, answer in response["answers"].items()}
        ).model_dump()
