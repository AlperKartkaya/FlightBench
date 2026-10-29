<p align="center">
  <img src="frontend/public/flightbench-icon.png" alt="FlightBench icon" width="96">
</p>
<h1 align="center">FlightBench</h1>
<p align="center"><b>Can you land a plane better than Jev?<br>FlightBench is a landing simulator and benchmark for decision models, LLMs, and classical controllers.<br>Try landing it yourself first, and compete with Jev, Codex, or your friends!</b></p>
<p align="center">
  <a href="LICENSE"><img alt="MIT license" src="https://img.shields.io/badge/license-MIT-4caa27"></a>
  <img alt="Python 3.11–3.13" src="https://img.shields.io/badge/Python-3.11--3.13-3776AB?logo=python&logoColor=white">
  <img alt="JSBSim" src="https://img.shields.io/badge/physics-JSBSim-3973a9">
  <img alt="FastAPI" src="https://img.shields.io/badge/backend-FastAPI-009688?logo=fastapi&logoColor=white">
  <a href="https://typesafe.ai"><img alt="TypeSafe AI" src="https://img.shields.io/badge/AI-TypeSafe_AI-6e2559?logo=data:image/svg%2bxml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyMSAzMiI%2BPHBhdGggZmlsbC1ydWxlPSJldmVub2RkIiBjbGlwLXJ1bGU9ImV2ZW5vZGQiIGQ9Ik0xMC4zNiAwLjA3QzEwLjU1IC0wLjA1IDEwLjcxIC0wLjAxIDEwLjc2IDAuMTdMMTUuNTcgMi43OUwxNS4zMyAzLjIzTDE1Ljc1IDIuOTVWOC44MUwyMC41NCAxMS40MkwyMC4yMiAxMi4wMUwyMC43NCAxMS42NlYyMy42MUMyMC43NCAyMy44OSAyMC41NiAyNC4yNCAyMC4zMyAyNC4zOUwxMC4zOCAzMS4wMlYzMC40TDEwLjEyIDMwLjg4TDUuMzIgMjguMjdDNS4xMiAyOC4zNyA0Ljk3IDI4LjI2IDQuOTcgMjguMDFWMjIuMTVMMC40IDE5LjY2QzAuMTggMTkuOCAwIDE5LjcgMCAxOS40M1Y3LjQ4QzAgNy4yIDAuMTkgNi44NSAwLjQyIDYuN0wxMC4zNiAwLjA3Wk02LjI3IDI3LjY1TDEwLjQ5IDI5Ljk1TDE5LjQzIDIzLjk5TDE1LjIxIDIxLjY4TDYuMjcgMjcuNjVaTTEwLjc4IDEyLjc0VjE4LjIyQzEwLjc4IDE4LjQ5IDEwLjU5IDE4Ljg0IDEwLjM2IDE4LjlMNS44IDIyLjAzVjI2Ljk2TDE0LjkyIDIwLjg4VjkuOThMMTAuNzggMTIuNzRaTTE1Ljc1IDIwLjgzQzE1Ljc1IDIwLjgzIDE1Ljc1IDIwLjgzIDE1Ljc1IDIwLjg0TDE5LjkxIDIzLjExVjEyLjIyTDE1Ljc1IDkuOTVWMjAuODNaTTEuMzQgMTkuMDNMNS40IDIxLjI1TDkuNDMgMTguNTZMNS4zNyAxNi4zNEwxLjM0IDE5LjAzWk0wLjgzIDcuNDJWMTguMzdMNC45NyAxNS42MVYxMC4xNEM0Ljk3IDkuODYgNS4xNiA5LjUxIDUuMzkgOS4zNkw5Ljk0IDYuMzJWMS4zNUwwLjgzIDcuNDJaTTUuOCAxNS40NEw5Ljk0IDE3LjdWMTIuOTFMNS44IDEwLjY2VjE1LjQ0Wk02LjI3IDkuNzdMMTAuMzQgMTEuOTlDMTAuMzQgMTEuOTggMTAuMzUgMTEuOTggMTAuMzYgMTEuOTdMMTQuMzcgOS4yOUwxMC4zMSA3LjA4TDYuMjcgOS43N1pNMTAuNzggNi4xOUwxNC45MiA4LjQ1VjMuNTdMMTAuNzggMS4zMlY2LjE5WiIgZmlsbD0id2hpdGUiLz48L3N2Zz4=&labelColor=3D2C30"></a>
  <img alt="Three.js" src="https://img.shields.io/badge/visuals-Three.js-202b34?logo=threedotjs&logoColor=white">
  <img alt="TypeScript" src="https://img.shields.io/badge/UI-TypeScript-3178C6?logo=typescript&logoColor=white">
  <img alt="Vite" src="https://img.shields.io/badge/build-Vite-646CFF?logo=vite&logoColor=white">
  <img alt="Weather" src="https://img.shields.io/badge/weather-☀️_sunny-005f8b">
</p>

## Jev lands the plane!

<a href="https://alperkartkaya.github.io/FlightBench/jev-flight/">
  <img
    src="https://github.com/AlperKartkaya/FlightBench/releases/download/v0.1.0/jev-preview.gif"
    alt="Jev flight recording preview"
    width="960"
  >
</a>

[Jev](https://docs.typesafe.ai/introduction) is [TypeSafe](https://www.typesafe.ai)'s System One decision model. Given a state and typed questions, it returns structured choices and probabilities. Here, the right panel shows the state sent to Jev and the four actuator commands that Jev chose. **[Watch the full flight!](https://alperkartkaya.github.io/FlightBench/jev-flight/)**


## Can you beat my landing?

<a href="https://alperkartkaya.github.io/FlightBench/human-flight/">
  <img
    src="https://github.com/AlperKartkaya/FlightBench/releases/download/v0.1.0/snap-pilot.png"
    alt="Human-pilot flight recording preview"
    width="960"
  >
</a>

**[Watch my flight!](https://alperkartkaya.github.io/FlightBench/human-flight/)** My best record is **70.1/100**. Try the same setup and beat my score, then [send me your run or recording](mailto:alperkartkaya@gmail.com)! You can also [watch the baseline controller](https://alperkartkaya.github.io/FlightBench/baseline-flight/).

## Quick take-off

There are two options to run FlightBench:

### 1. Launch FlightBench in your browser!

No installation required. Just click [here](https://alperkartkaya.github.io/FlightBench/) and start landing!

### 2. Run locally

Clone the repository and change into the cloned directory:

```sh
git clone https://github.com/AlperKartkaya/FlightBench.git
cd FlightBench
```

On macOS or Linux, install dependencies and start both servers with one command:

```sh
./scripts/dev.sh
```

On Windows (PowerShell), use:

```powershell
python scripts/dev.py
```

You are all set! Choose a controller and select **Start flight**.

For Jev and Codex authentication, [see the setup guide](docs/controller-setup/README.md).

## Benchmark results — landing score and API cost

![FlightBench benchmark results (dark theme)](docs/evaluations/2026-10-22-scoring-v2/benchmark-dark.svg#gh-dark-mode-only)
![FlightBench benchmark results (light theme)](docs/evaluations/2026-10-22-scoring-v2/benchmark-light.svg#gh-light-mode-only)

**In our evaluation, all the Codex/LLM controllers failed to achieve a successful realtime landing;
their results above are lockstep runs.**

> While **Realtime** means simulation time equals wall clock time, **Lockstep** means the simulation is paused for each step to let the model respond. Hence, simulation and wall time can differ in lockstep.

## Landing Score vs. Estimated API Cost

![Landing score versus API-equivalent cost](docs/evaluations/2026-10-22-scoring-v2/landing-score-vs-api-cost.svg)

## Landing score calculation

![Landing score: formula, variables and default constants](docs/scoring/scoring-v2.png)

## How is Jev's API used?

![How Jev steers FlightBench: an aircraft-state snapshot leads to four textual Choice answers, fixed commands, and a JSBSim physics step](docs/jev-control-loop.svg)

*Illustrative choices from the mock request and response below.*

### What Jev sees

The following **mock request** shows the structure of the state and questions sent to Jev.

```json
{
  "model": "jev-1.13.0",
  "state": {
    "flight": {"airspeed_mps": 30.1, "vertical_speed_mps": -2.0, "roll_deg": 1.5, "pitch_deg": 2.8},
    "runway": {"altitude_agl_m": 45, "centerline_offset_m": 3.0, "heading_error_deg": 1.5, "glideslope_error_deg": 0.2},
    "current_controls": {"aileron": -0.15, "elevator": 0.17, "rudder": 0.09, "throttle": 0.5},
    "time_s": 35,
    "motion": {"cross_track_rate_mps": 0.6},
    "status": {"on_ground": false},
    "phase": "APPROACH"
  },
  "questions": {
    "aileron": {
      "type": "choice",
      "instructions": "Choose an absolute aileron correction; arrest bank, then sideways motion, then offset.",
      "criteria": {
        "0": "Strong left roll", "1": "Moderate left roll", "2": "Gentle left roll",
        "3": "Maintain a small bank", "4": "Gentle right roll",
        "5": "Moderate right roll", "6": "Strong right roll"
      }
    },
    "elevator": {
      "type": "choice",
      "instructions": "Choose an absolute elevator correction for the approach glidepath.",
      "criteria": {
        "0": "Emergency nose-up", "1": "Strong nose-up", "2": "Firm nose-up",
        "3": "Nose-up recovery", "4": "Nose-up support", "5": "Moderate nose-up support",
        "6": "Mild nose-up support", "7": "Normal descent",
        "8": "Moderate nose-down", "9": "Strong nose-down"
      }
    },
    "rudder": {
      "type": "choice",
      "instructions": "Choose an absolute rudder correction for heading and yaw.",
      "criteria": {
        "0": "Strong yaw right", "1": "Moderate yaw right", "2": "Gentle yaw right",
        "3": "Trim yaw", "4": "Gentle yaw left",
        "5": "Moderate yaw left", "6": "Strong yaw left"
      }
    },
    "throttle": {
      "type": "choice",
      "instructions": "Choose absolute throttle for airspeed and flight phase.",
      "criteria": {
        "0": "Idle", "1": "Reduced flare power", "2": "Slightly reduced approach power",
        "3": "Normal approach power", "4": "Increased approach power",
        "5": "High approach power", "6": "Full power"
      }
    }
  }
}
```

### What Jev delivers

The following **mock response** shows the selected labels and the *per actuator* probability distributions, along with the confidence.

```json
{
  "model": "jev-1.13.0",
  "answers": {
    "aileron": {
      "type": "choice", "choice": "2", "confidence": 0.64,
      "probabilities": {"0": 0.02, "1": 0.06, "2": 0.70, "3": 0.16, "4": 0.04, "5": 0.01, "6": 0.01}
    },
    "elevator": {
      "type": "choice", "choice": "7", "confidence": 0.51,
      "probabilities": {"0": 0, "1": 0, "2": 0, "3": 0.01, "4": 0.02, "5": 0.05, "6": 0.17, "7": 0.65, "8": 0.08, "9": 0.02}
    },
    "rudder": {
      "type": "choice", "choice": "4", "confidence": 0.58,
      "probabilities": {"0": 0.01, "1": 0.02, "2": 0.06, "3": 0.16, "4": 0.65, "5": 0.08, "6": 0.02}
    },
    "throttle": {
      "type": "choice", "choice": "3", "confidence": 0.68,
      "probabilities": {"0": 0, "1": 0.01, "2": 0.09, "3": 0.72, "4": 0.12, "5": 0.04, "6": 0.02}
    }
  }
}
```

## A few remarks

- **Jev's control loop.** FlightBench sends Jev a snapshot of the aircraft, runway, current controls, motion, and flight phase. Each request asks Jev to choose an aileron, elevator, rudder, and throttle correction. Jev returns a selected label and a separate probability distribution for each actuator. The controller maps those labels to fixed absolute commands. JSBSim computes the resulting flight based on these commands and the aircraft's state.

- **Codex and realtime.** Codex models ran in **2 Hz lockstep**: physics waited for each answer, so slow responses did not directly cause those failed landings. Sol and Astra ended in runway excursions in all five runs; Luna had two nose-first contacts and three crashes. Their mean decision latencies of 2.53–4.50 seconds are far beyond the 0.5-second interval needed for 2 Hz realtime control. This reveals one of the most important advantages of decision models like Jev over general purpose LLMs.

- **Runway excursions.** A runway excursion is still a failed landing, but it is useful in means of showing an improvement over crash scenerios: in a runway excursion, the aircraft reaches touchdown before leaving the runway bounds. In the further studies and revisions, the controller can be improved to be less prone to runway excursions; as it showed up to be the biggest challenge for the LLMs.

- **Controller design.** During the development process, I found it useful to use acceptance thresholds on the probabilities of the selected choices to foster robustness. As the simulation was very prone to lose the stability, I also needed to tune the sensitivity of the choices Jev returned. It was difficult to initialize a balanced delta value, which was used to increase or decrease each of the four actuators, according to Jev's decisions. These were the challenges until I introduced fixed choices of values, which had a textual correspondence, hence making it easier for Jev to work with the controller.

- **Decision rate.** In terms of the practical concerns, besides the obvious trade-off between the request rate and the API-cost, it is important to note that there is an upper limit on the effective request rate, which was 2.4 calls per second during my evaluation. To increase this effective request rate of 2.4 Hz, you can consider decreasing the simulation speed. I managed to increase it up to 10 Hz, halving the simulation speed twice. Note that this is currently not supported in the UI.

## Contributing

Contributions of any size are welcome: report a bug, share a flight recording, suggest a controller, improve the docs, or send a pull request.

## License and credits

FlightBench is [MIT licensed](LICENSE).

Aircraft visual: [Small Airplane](https://poly.pizza/m/7cvx6ex-xfL) by Vojtěch Balák · [CC BY 3.0](frontend/public/models/LICENSE.md).

Built with [JSBSim](https://jsbsim-team.github.io/jsbsim/python/FGFDMExec.html), [Gymnasium](https://gymnasium.farama.org/api/env/), [Three.js](https://threejs.org/), [TypeSafe Jev](https://typesafe.ai/), [llm-openai-via-codex](https://github.com/simonw/llm-openai-via-codex), and *passion*.
