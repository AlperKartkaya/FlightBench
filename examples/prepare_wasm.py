"""Prepare browser aircraft assets and the frozen simulation contract. Never reads .env or calls an AI provider."""

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import jsbsim

from flightbench.core import PHYSICS_HZ, TRIM_AILERON, TRIM_ELEVATOR, TRIM_RUDDER
from flightbench.environment import FixedWingLandingEnv
from flightbench.protocol import action_space, protocol_metadata
from flightbench.scoring import ScoringConfig

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "frontend/public/wasm"


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")


def main():
    if jsbsim.__version__ != "1.3.1":
        raise RuntimeError("Browser runtime requires Python JSBSim 1.3.1")
    model_root = Path(jsbsim.get_default_root_dir())
    paths = [*sorted((model_root / "aircraft/c172x").glob("*.xml"))]
    paths += [
        model_root / p
        for p in (
            "engine/eng_io320.xml",
            "engine/prop_75in2f.xml",
            "systems/GNCUtilities.xml",
            "systems/Autopilot.xml",
        )
    ]
    files = {str(p.relative_to(model_root)): p.read_text() for p in paths}
    env = FixedWingLandingEnv()
    # Read resolved IC values from the existing environment rather than inventing a scenario.
    initial = {
        k: env.fdm[k]
        for k in (
            "ic/lat-geod-deg",
            "ic/long-gc-deg",
            "ic/terrain-elevation-ft",
            "ic/h-agl-ft",
            "ic/vc-kts",
            "ic/psi-true-deg",
            "ic/gamma-deg",
            "ic/alpha-deg",
            "fcs/flap-cmd-norm",
            "fcs/flaps-control",
            "fcs/flap-pos-deg",
            "fcs/mixture-cmd-norm",
            "fcs/throttle-cmd-norm",
            "atmosphere/wind-north-fps",
        )
    }
    # run_ic resolves IC properties; use the original literal IC inputs where they differ.
    import math

    initial.update(
        {
            "ic/h-agl-ft": (1500 * math.tan(math.radians(3)) + 15) / 0.3048,
            "ic/vc-kts": 65,
            "ic/gamma-deg": -3,
            "ic/alpha-deg": 5,
            "fcs/flap-pos-deg": 20,
        }
    )
    contract = {
        **protocol_metadata(),
        "python_jsbsim": jsbsim.__version__,
        "wasm_jsbsim": "1.3.1",
        "physics_hz": PHYSICS_HZ,
        "initial": initial,
        "trim": {
            "aileron": TRIM_AILERON,
            "elevator": TRIM_ELEVATOR,
            "rudder": TRIM_RUDDER,
            "throttle": 0.5,
        },
        "scoring": asdict(ScoringConfig()),
        "action_space": action_space(),
        "files": files,
        "model_sha256": {
            name: hashlib.sha256(text.encode()).hexdigest() for name, text in files.items()
        },
    }
    write_json(OUT / "flightbench.json", contract)
    # Proxy gets frozen actions only, never aircraft data or browser-supplied instructions.
    write_json(ROOT / "workers/jev-proxy/action-space.json", action_space())
    env.close()
    print(f"Prepared {OUT}; Python JSBSim {jsbsim.__version__}, WASM 1.3.1")


if __name__ == "__main__":
    main()
