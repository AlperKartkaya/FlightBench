"""Paste into one Colab cell. Configure local jobs and an export folder before running."""

import atexit
import hmac
import json
import platform
import re
import secrets
import shutil
import subprocess
import threading
import time
from http.client import HTTPException, HTTPSConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

# Notebook-owned settings. Do not put a shell interpreter, secrets, or a broad folder here.
WORK_DIR = Path("/content")
EXPORT_DIR = Path("/content/colab-exports")
JOBS = {
    # "benchmark": ["/content/project/.venv/bin/python", "/content/project/approved_runner.py"],
}


def cloudflared(cache):
    installed = shutil.which("cloudflared")
    if installed:
        return installed
    arch = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}
    variant = arch.get(platform.machine().lower())
    if not variant:
        raise RuntimeError("Unsupported architecture; install cloudflared before running this cell")
    binary = cache / "cloudflared"
    if not binary.is_file():
        temporary = binary.with_suffix(".download")
        url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{variant}"
        try:
            subprocess.run(
                ["curl", "-fsSL", "--retry", "3", "--max-time", "120", "-o", str(temporary), url],
                check=True,
                timeout=510,
            )
            temporary.chmod(0o700)
            subprocess.run([str(temporary), "--version"], check=True, timeout=10)
            temporary.replace(binary)
        finally:
            temporary.unlink(missing_ok=True)
    return str(binary)


def make_server(token, jobs, work_dir, export_dir, processes):
    """Bind to loopback. Only exact, notebook-configured jobs can be started."""
    export_dir = export_dir.resolve()
    expected_auth = ("Bearer " + token).encode()
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def log_message(self, *_args):
            pass

        def send_json(self, code, value):
            body = json.dumps(value).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def authorized(self):
            if hmac.compare_digest(self.headers.get("Authorization", "").encode(), expected_auth):
                return True
            self.send_json(403, {"error": "unauthorized"})
            return False

        def do_GET(self):
            if not self.authorized():
                return
            if self.path == "/health":
                self.send_json(200, {"status": "ready", "protocol": 2})
            elif self.path == "/status":
                with lock:
                    status = {name: proc.poll() for name, proc in processes.items()}
                    self.send_json(
                        200,
                        {
                            "jobs": {
                                name: (
                                    {"state": "not-started"}
                                    if name not in status
                                    else {"state": "running"}
                                    if status[name] is None
                                    else {"state": "exited", "returncode": status[name]}
                                )
                                for name in jobs
                            }
                        },
                    )
            elif self.path.startswith("/files/"):
                relative = unquote(self.path.removeprefix("/files/"), errors="replace")
                if not all(part and not part.startswith(".") for part in relative.split("/")):
                    self.send_json(404, {"error": "file not found"})
                    return
                try:
                    requested = export_dir / relative
                    path = requested.resolve(strict=True)
                    if path != requested or not path.is_file():
                        raise FileNotFoundError
                    file = path.open("rb")
                except (OSError, ValueError, RuntimeError):
                    self.send_json(404, {"error": "file not found"})
                    return
                with file:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    shutil.copyfileobj(file, self.wfile)
            else:
                self.send_json(404, {"error": "unknown route"})

        def do_POST(self):
            if not self.authorized():
                return
            match = re.fullmatch(r"/jobs/([A-Za-z0-9_-]+)/start", self.path)
            if not match or match[1] not in jobs:
                self.send_json(404, {"error": "unknown job"})
                return
            if (
                self.headers.get("Content-Length", "0") != "0"
                or "Transfer-Encoding" in self.headers
            ):
                self.send_json(400, {"error": "this endpoint does not accept a body"})
                return
            name = match[1]
            with lock:
                if name in processes or any(p.poll() is None for p in processes.values()):
                    self.send_json(409, {"error": "job already started or another job is active"})
                    return
                try:
                    with (export_dir / f"{name}.log").open("ab") as log:
                        processes[name] = subprocess.Popen(
                            jobs[name],
                            cwd=work_dir,
                            stdin=subprocess.DEVNULL,
                            stdout=log,
                            stderr=subprocess.STDOUT,
                            start_new_session=True,
                        )
                except OSError:
                    self.send_json(500, {"error": "job failed to start"})
                    return
            self.send_json(202, {"job": name, "state": "started"})

    return ThreadingHTTPServer(("127.0.0.1", 0), Handler)


def stop_colab_bridge():
    """Close only this cell's tunnel and server; leave benchmark jobs running."""
    bridge = globals().pop("_colab_bridge", None)
    if bridge:
        server, tunnel = bridge
        tunnel.terminate()
        try:
            tunnel.wait(timeout=5)
        except subprocess.TimeoutExpired:
            tunnel.kill()
            tunnel.wait(timeout=5)
        server.shutdown()
        server.server_close()


def start_colab_bridge():
    stop_colab_bridge()
    cache = WORK_DIR / ".colab-bridge"
    cache.mkdir(exist_ok=True)
    if WORK_DIR.resolve().is_relative_to(EXPORT_DIR.resolve()):
        raise ValueError("EXPORT_DIR must be a dedicated output folder, not the workspace")
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    binary = cloudflared(cache)
    processes = globals().setdefault("_colab_bridge_jobs", {})
    token = secrets.token_urlsafe(32)
    server = make_server(token, JOBS.copy(), WORK_DIR, EXPORT_DIR, processes)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log_path = cache / "tunnel.log"
    try:
        with log_path.open("w") as log:
            tunnel = subprocess.Popen(
                [
                    binary,
                    "tunnel",
                    "--no-autoupdate",
                    "--url",
                    f"http://127.0.0.1:{server.server_port}",
                ],
                stdout=log,
                stderr=log,
            )
        globals()["_colab_bridge"] = (server, tunnel)
        deadline = time.monotonic() + 75
        while tunnel.poll() is None and time.monotonic() < deadline:
            match = re.search(r"https://([a-z0-9-]+\.trycloudflare\.com)\b", log_path.read_text())
            if match:
                connection = HTTPSConnection(match[1], timeout=3)
                try:
                    connection.request(
                        "GET", "/health", headers={"Authorization": "Bearer " + token}
                    )
                    response = connection.getresponse()
                    if response.status == 200 and json.loads(response.read(4096)) == {
                        "status": "ready",
                        "protocol": 2,
                    }:
                        print(
                            "Colab bridge ready. Share this JSON privately; do not save it to Git."
                        )
                        print(json.dumps({"url": match[0], "token": token, "protocol": 2}))
                        return
                except (HTTPException, OSError, ValueError):
                    pass
                finally:
                    connection.close()
            time.sleep(1)
        raise RuntimeError(f"Tunnel did not become ready. Inspect {log_path} in Colab.")
    except BaseException:
        if "_colab_bridge" in globals():
            stop_colab_bridge()
        else:
            server.shutdown()
            server.server_close()
        raise


if __name__ == "__main__":
    if not globals().get("_colab_bridge_exit_registered"):
        atexit.register(stop_colab_bridge)
        _colab_bridge_exit_registered = True
    start_colab_bridge()
