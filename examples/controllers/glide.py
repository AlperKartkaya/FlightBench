"""Use the pinned GLiDE decision server on the same Colab machine as the simulator."""

import json
import os
from pathlib import Path
from time import perf_counter
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from examples.controllers.azure_decision import AzureDecisionController
from flightbench.runs import now


class GlideController(AzureDecisionController):
    model = "glide-v1.2"
    deployment = model
    endpoint = "http://127.0.0.1:8000/v1/systemone"

    def __init__(self):
        self.model_id = self.model
        self._log = Path(os.environ["FLIGHTBENCH_DECISION_LOG"])
        self._log.parent.mkdir(parents=True, exist_ok=True)
        self.metadata = {
            "name": "GLiDE v1.2",
            "slug": self.model,
            "model": self.model,
            "provider": "Fastino weights, self-hosted on Colab",
            "controller_type": "ai",
            "local": True,
            "policy": "direct-categorical",
            "source_url": "https://huggingface.co/fastino/GLiDE-27B",
            "model_revision": "19a948f812af30c8962337fbbec2472e575eee7d",
            "precision": "bf16",
            "quantized": False,
            "endpoint": self.endpoint,
            "transport": "systemone",
            "inference_hardware": "NVIDIA A100-SXM4-80GB",
            "cost_methodology": "Colab compute units; no provider API token charges. Invoice not checked.",
        }

    def _request(self, method, payload):
        if method != "systemone":
            raise ValueError("Only the decision endpoint is supported")
        row = {"at": now(), "attempt": 1, "request": payload, "status": 0}
        started = perf_counter()
        try:
            request = Request(
                self.endpoint,
                json.dumps(payload, allow_nan=False).encode(),
                {"Content-Type": "application/json"},
            )
            with urlopen(request, timeout=180) as response:
                row.update(status=response.status, response=json.load(response))
            if row["response"].get("model") != self.model:
                raise ValueError("Unexpected model identity")
            return row["response"]
        except HTTPError as error:
            row.update(status=error.code, error_body=error.read().decode(errors="replace"))
            raise
        except Exception as error:
            row["exception_type"] = type(error).__name__
            raise
        finally:
            row["latency_ms"] = (perf_counter() - started) * 1000
            with self._log.open("a") as log:
                log.write(json.dumps(row, allow_nan=False) + "\n")
                log.flush()
                os.fsync(log.fileno())
