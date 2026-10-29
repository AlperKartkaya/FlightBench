import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from decider.infer import Decider
from decider.systemone import render_state

parser = argparse.ArgumentParser(
    description="Serve pinned official Decider GGUF with no truncation"
)
parser.add_argument("model_dir", type=Path)
args = parser.parse_args()
MODEL = args.model_dir.resolve()
d = Decider(
    str(MODEL),
    gguf_file="decider-2b-v11-Q4_K_M.gguf",
    gguf_options={"n_ctx": 8192, "n_seq_max": 1, "n_threads": 2, "n_gpu_layers": -1},
)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(
            json.dumps(
                {
                    "model": d.name,
                    "backend": "llama.cpp Metal",
                    "n_ctx": 8192,
                    "truncation": "refuse",
                }
            ).encode()
        )

    def do_POST(self):
        try:
            if self.path != "/v1/systemone":
                raise ValueError("Unknown route")
            length = int(self.headers["Content-Length"])
            if not 0 < length <= 65536:
                raise ValueError("Request must fit within 64 KiB")
            payload = json.loads(self.rfile.read(length))
            state = payload["state"]
            questions = payload["questions"]
            n = len(d.m.tok.encode("Context:\n" + render_state(state), add_special_tokens=False))
            if n > 32768:
                raise ValueError("State exceeds native maximum; no truncation allowed")
            started = time.monotonic()
            result = d.system_one(state, questions, independent=True, max_state_tokens=32768)
            result["latency_ms"] = (time.monotonic() - started) * 1000
            result["truncated"] = False
            data = json.dumps(result, allow_nan=False).encode()
            code = 200
        except (ValueError, KeyError, TypeError, RuntimeError) as exc:
            data = json.dumps({"error": str(exc)}).encode()
            code = 422
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)


HTTPServer(("127.0.0.1", 11439), Handler).serve_forever()
