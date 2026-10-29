"""Guard the separate browser port against drift in the frozen Python contract."""

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import jsbsim

from flightbench.core import PHYSICS_HZ, TRIM_AILERON, TRIM_ELEVATOR, TRIM_RUDDER
from flightbench.protocol import action_space, protocol_metadata
from flightbench.scoring import ScoringConfig, evaluate

ROOT = Path(__file__).resolve().parents[1]


def test_wasm_export_matches_current_contract():
    contract = json.loads((ROOT / "frontend/public/wasm/flightbench.json").read_text())
    assert contract["python_jsbsim"] == jsbsim.__version__ == "1.3.1"
    assert contract["wasm_jsbsim"] == "1.3.1"
    assert contract["physics_hz"] == PHYSICS_HZ == 120
    assert contract["trim"] == {
        "aileron": TRIM_AILERON,
        "elevator": TRIM_ELEVATOR,
        "rudder": TRIM_RUDDER,
        "throttle": 0.5,
    }
    assert contract["action_space"] == action_space()
    for key, value in protocol_metadata().items():
        assert contract[key] == value
    assert contract["scoring"] == json.loads(json.dumps(asdict(ScoringConfig())))
    assert json.loads((ROOT / "workers/jev-proxy/action-space.json").read_text()) == action_space()
    for name, contents in contract["files"].items():
        assert contents == (Path(jsbsim.get_default_root_dir()) / name).read_text()
        assert hashlib.sha256(contents.encode()).hexdigest() == contract["model_sha256"][name]


def test_wasm_score_fixtures_still_match_python():
    fixtures = json.loads((ROOT / "docs/wasm/scoring-fixtures.json").read_text())
    for f in fixtures:
        expected = evaluate(
            f["touchdown"], f["success"], f["reason"], ScoringConfig(), f["trajectory"]
        )
        assert json.loads(json.dumps(expected)) == f["expected"]


def test_browser_uses_one_application_entrypoint():
    public = ROOT / "frontend/public/wasm"
    for name in ("index.html", "demo.js", "demo.css"):
        assert not (public / name).exists()
    for name in ("engine.js", "worker.js", "flightbench.json", "NOTICE.txt"):
        assert (public / name).is_file()
    assert (ROOT / "examples/prepare_wasm.py").is_file()
    assert not (ROOT / "examples/prepare_wasm_demo.py").exists()
