"""Start the local backend and frontend on available loopback ports."""

import multiprocessing
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def bootstrap():
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("uv is required; install uv and make sure it is on PATH")
    subprocess.run([uv, "sync", "--extra", "jev", "--extra", "codex"], cwd=ROOT, check=True)
    python = ROOT / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    os.execv(str(python), [str(python), str(Path(__file__).resolve()), "--serve"])


def bind_backend(start=8000):
    for port in range(start, 65536):
        sock = socket.socket()
        try:
            sock.bind(("127.0.0.1", port))
        except OSError as exc:
            sock.close()
            if exc.errno not in {48, 98, 10048}:  # Address already in use.
                raise
        else:
            return sock
    raise RuntimeError("No available backend port")


def serve(sock):
    import uvicorn

    config = uvicorn.Config("flightbench.server:app", host="127.0.0.1", port=sock.getsockname()[1])
    uvicorn.Server(config).run(sockets=[sock])


def main():
    os.chdir(ROOT)
    npm = shutil.which("npm")
    if not npm:
        raise RuntimeError("npm is required; install Node.js first")
    subprocess.run([npm, "--prefix", "frontend", "ci"], check=True)
    sock = bind_backend()
    port = sock.getsockname()[1]
    backend = multiprocessing.Process(target=serve, args=(sock,))
    frontend = None

    def stop(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        backend.start()
        sock.close()
        # Do not open the browser until the backend has started accepting connections.
        while backend.is_alive():
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            return backend.exitcode or 1
        print(f"Backend: http://127.0.0.1:{port}", flush=True)
        frontend = subprocess.Popen(
            [
                shutil.which("node"),
                "frontend/node_modules/vite/bin/vite.js",
                "frontend",
                "--host",
                "127.0.0.1",
                "--port",
                "5173",
            ],
            env=dict(os.environ, FLIGHTBENCH_BACKEND_PORT=str(port)),
        )
        while backend.is_alive() and frontend.poll() is None:
            time.sleep(0.2)
        return backend.exitcode or frontend.poll() or 1
    except KeyboardInterrupt:
        return 130
    finally:
        sock.close()
        if frontend is not None and frontend.poll() is None:
            frontend.terminate()
            frontend.wait()
        if backend.pid is not None:
            if backend.is_alive():
                backend.terminate()
            backend.join()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    try:
        if sys.argv[1:] == ["--serve"]:
            raise SystemExit(main())
        bootstrap()
    except KeyboardInterrupt:
        raise SystemExit(130)
