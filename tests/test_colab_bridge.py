"""Exercise the Colab cell's HTTP boundary without opening a public tunnel."""

import json
import sys
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from scripts.colab_bridge import make_server


def test_bridge_serves_only_authorized_jobs_and_artifacts(tmp_path):
    token = "test-token"
    exports = tmp_path / "exports"
    exports.mkdir()
    (exports / "result.json").write_text('{"score": 64.61}')
    (tmp_path / "private").write_text("not exported")
    (exports / "link").symlink_to(tmp_path / "private")
    runner = tmp_path / "runner.py"
    runner.write_text(
        "from pathlib import Path\n"
        "from time import monotonic, sleep\n"
        "deadline = monotonic() + 5\n"
        "while not Path('finish').exists() and monotonic() < deadline: sleep(0.01)\n"
        "print('done', flush=True)\n"
    )
    jobs = {name: [sys.executable, str(runner)] for name in ("benchmark", "other")}
    processes = {}
    with make_server(token, jobs, tmp_path, exports, processes) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def request(path, *, data=None, authorized=True):
            headers = {"Authorization": f"Bearer {token}"} if authorized else {}
            query = Request(
                f"http://127.0.0.1:{server.server_port}{path}", data=data, headers=headers
            )
            try:
                with urlopen(query, timeout=3) as response:
                    return response.status, response.read()
            except HTTPError as error:
                with error:
                    return error.code, error.read()

        try:
            assert request("/health", authorized=False)[0] == 403
            assert request("/jobs/benchmark/start", data=b"", authorized=False)[0] == 403
            assert json.loads(request("/health")[1]) == {"status": "ready", "protocol": 2}
            assert json.loads(request("/status")[1])["jobs"]["benchmark"]["state"] == "not-started"
            assert request("/", data=b'{"cmd":"echo never"}')[0] == 404
            assert request("/jobs/benchmark/start", data=b'{"cmd":"echo never"}')[0] == 400
            for path in ("/files/%2e%2e/private", "/files/link", "/files/.env"):
                assert request(path)[0] == 404
            assert request("/files/result.json") == (200, b'{"score": 64.61}')
            assert request("/jobs/benchmark/start", data=b"")[0] == 202
            assert request("/jobs/other/start", data=b"")[0] == 409
            assert json.loads(request("/status")[1])["jobs"]["benchmark"]["state"] == "running"
            (tmp_path / "finish").touch()
            assert processes["benchmark"].wait(timeout=5) == 0
            status = json.loads(request("/status")[1])
            assert status["jobs"]["benchmark"] == {"state": "exited", "returncode": 0}
            assert request("/jobs/benchmark/start", data=b"")[0] == 409
            assert request("/files/benchmark.log") == (200, b"done\n")
        finally:
            (tmp_path / "finish").touch()
            for process in processes.values():
                process.wait(timeout=6)
            server.shutdown()
            thread.join(timeout=2)
