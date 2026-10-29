"""Port reservation and real Vite configuration checks without opening a browser."""

import importlib.util
import os
import shutil
import socket
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("dev_launcher", ROOT / "scripts/dev.py")
dev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dev)


def test_backend_skips_occupied_port_and_keeps_socket_reserved():
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        start = occupied.getsockname()[1]
        with dev.bind_backend(start) as selected:
            assert selected.getsockname()[1] > start
            with socket.socket() as contender:
                assert contender.connect_ex(("127.0.0.1", selected.getsockname()[1])) != 0
                try:
                    contender.bind(selected.getsockname())
                except OSError:
                    pass
                else:
                    raise AssertionError("Backend port was not reserved")


def test_vite_fallback_proxy_and_browser_configuration():
    subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            """
import assert from 'node:assert/strict';
import net from 'node:net';
import { createServer, resolveConfig } from 'vite';
process.env.FLIGHTBENCH_BACKEND_PORT = '8123';
const config = await resolveConfig({}, 'serve');
assert.equal(config.server.open, true);
assert.equal(config.server.strictPort, false);
assert.equal(config.server.proxy['/api'].target, 'http://127.0.0.1:8123');
assert.equal(config.server.proxy['/ws'].target, 'ws://127.0.0.1:8123');
const occupied = net.createServer();
await new Promise(resolve => occupied.listen(0, '127.0.0.1', resolve));
const port = occupied.address().port;
let server;
try {
  server = await createServer({server: {host: '127.0.0.1', port, open: false}});
  await server.listen();
  assert.ok(server.httpServer.address().port > port);
} finally {
  if (server) await server.close();
  await new Promise(resolve => occupied.close(resolve));
}
""",
        ],
        cwd=ROOT / "frontend",
        check=True,
        timeout=20,
    )


def test_shell_delegates_to_python_and_inherits_key(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    launcher = scripts / "dev.sh"
    shutil.copyfile(ROOT / "scripts/dev.sh", launcher)
    binaries = tmp_path / "bin"
    binaries.mkdir()
    python = binaries / "python3"
    python.write_text(
        '#!/bin/sh\nprintf "%s" "$TYPESAFE_API_KEY" > "$CAPTURE_KEY"\nprintf "%s\\n" "$@" > "$CAPTURE_PYTHON"\n'
    )
    python.chmod(0o755)
    env = dict(
        os.environ,
        PATH=str(binaries) + os.pathsep + os.environ["PATH"],
        TYPESAFE_API_KEY="test-key-not-a-secret",
        CAPTURE_KEY=str(tmp_path / "key"),
        CAPTURE_PYTHON=str(tmp_path / "python-args"),
    )
    subprocess.run(["bash", str(launcher)], env=env, check=True, timeout=10)
    assert (tmp_path / "key").read_text() == "test-key-not-a-secret"
    assert (tmp_path / "python-args").read_text().splitlines() == ["scripts/dev.py"]


@pytest.mark.parametrize(
    "platform,executable",
    [("win32", "Scripts/python.exe"), ("darwin", "bin/python"), ("linux", "bin/python")],
)
def test_python_bootstrap_installs_extras_and_hands_off_once(
    monkeypatch, tmp_path, platform, executable
):
    calls = []
    monkeypatch.setattr(dev, "ROOT", tmp_path)
    monkeypatch.setattr(dev.sys, "platform", platform)
    monkeypatch.setattr(dev.shutil, "which", lambda name: "/tools/uv" if name == "uv" else None)
    monkeypatch.setattr(
        dev.subprocess, "run", lambda command, **kwargs: calls.append((command, kwargs))
    )
    monkeypatch.setattr(dev.os, "execv", lambda path, args: calls.append((path, args)))
    dev.bootstrap()
    assert calls[0] == (
        ["/tools/uv", "sync", "--extra", "jev", "--extra", "codex"],
        {"cwd": tmp_path, "check": True},
    )
    python = str(tmp_path / ".venv" / executable)
    assert calls[1] == (python, [python, str(ROOT / "scripts/dev.py"), "--serve"])


def test_bootstrap_requires_uv_and_never_launches_after_sync_failure(monkeypatch):
    monkeypatch.setattr(dev.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="uv is required"):
        dev.bootstrap()
    monkeypatch.setattr(dev.shutil, "which", lambda _: "/tools/uv")

    def failed_sync(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0])

    monkeypatch.setattr(dev.subprocess, "run", failed_sync)
    monkeypatch.setattr(
        dev.os, "execv", lambda *_: pytest.fail("Must not launch after failed setup")
    )
    with pytest.raises(subprocess.CalledProcessError):
        dev.bootstrap()
