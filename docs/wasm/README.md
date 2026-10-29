# Browser simulator

The Pages build reuses the **existing localhost 3D workbench**, aircraft, cameras,
keyboard/onscreen controls, landing assistance, telemetry and outcome dialog at
`https://alperkartkaya.github.io/FlightBench/`. Only its transport changes: a module
Web Worker replaces the local Python WebSocket. The default local build still uses
Python and keeps its controllers and saved-run archive. The local Codex integration is unchanged. Human and baseline need no backend. Public Jev uses the fixed Cloudflare proxy without asking visitors for credentials. Provider credentials remain Worker secrets.

## Run locally

Requirements: the existing Python environment with **JSBSim 1.3.1**, CMake >= 3.20,
Node >= 22, and an activated Emscripten **4.0.18** SDK.

```sh
# From the repository root; exports aircraft/model/protocol data, not environment variables.
.venv/bin/python examples/prepare_wasm.py

# If emcmake is not available, install an isolated build SDK, not a global tool upgrade.
git clone https://github.com/emscripten-core/emsdk.git scratch/emsdk
git -C scratch/emsdk checkout d7b4130688bfa348392b921ab04015aa15c4f154
scratch/emsdk/emsdk install 4.0.18
scratch/emsdk/emsdk activate 4.0.18
source scratch/emsdk/emsdk_env.sh
bash examples/wasm/build.sh
```

To run the same 3D interface as the planned Pages site, after building WASM:

```sh
npm --prefix frontend ci
npm --prefix frontend run build:pages
npm --prefix frontend run preview -- --mode pages --outDir dist-pages --host 127.0.0.1 --port 5190
# Open http://127.0.0.1:5190/FlightBench/
```

`build:pages` writes `frontend/dist-pages/`, not the Python server's `frontend/dist/`.
The normal `npm --prefix frontend run build` and `scripts/dev.sh` retain their local
WebSocket/backend behavior. Pages does not request `/ws` or `/api/models`. It offers
human/baseline/Jev only, frozen easy/seed-42 conditions, 2 Hz AI and Jev 1.13/1.14.
Browser results last for the current session only; the status is Completed, not Saved.
Official benchmark submissions and persistent local records still use the Python workflow.
This UI-only preview does not download recordings; the workflow packaging stage adds
the existing release recording pages/media. A complete local package was also assembled
at `scratch/pages-package/site/` (see [validation](validation.md)).

If `scratch/emsdk` already exists, reuse it; do not clone over it. Export runs pin the
Python version and refuse silent model/version changes. Generated runtime assets and
large parity traces stay ignored. `flightbench.json` and the proxy's `action-space.json`
are reproducible exports guarded against Python contract drift.

Human pilot uses the existing keyboard/onscreen controls and explicitly labeled
assistance settings. Stop ends the current flight; Start restores the canonical easy
initial conditions. Baseline runs at 2 Hz. Physics uses a module Web Worker at fixed
**1/120 s**, four ticks per UI update; slow frames never enlarge dt. Jev waits in
lockstep at each 0.5 s decision boundary.

## Parity evidence

```sh
.venv/bin/python examples/compare_wasm.py
node --test frontend/public/wasm/*.test.js workers/jev-proxy/worker.test.js
uv run --frozen --isolated --extra dev pytest -q
uv run --frozen --isolated --extra dev ruff check examples/prepare_wasm.py examples/compare_wasm.py tests/test_wasm_contract.py
npm --prefix frontend test
npm --prefix frontend run build
```

`parity.json` records errors at **every physics tick**, initialization included, against
native Python JSBSim 1.3.1. WASM uses the same upstream version, current installed C172x
XML, engine/system files (SHA-256 included), ICs and 120 Hz timestep. The only JSBSim
source patch handles Emscripten's POSIX `strerror_r` return type; it does not change physics.
The prebuilt `@0x62/jsbsim-wasm@1.2.4-beta.4` was rejected: its actual runtime is
1.2.5.dev1 and it cannot load the current C172x system XML. It is not used or shipped.

| Case | Fixed controls (aileron/elevator/rudder/throttle) | Ticks | Result |
|---|---|---:|---|
| trim-10s | -0.15 / 0.17 / 0.09 / 0.50 | 1200 | time_limit, score 0 |
| left-10s | -0.20 / 0.17 / 0.09 / 0.50 | 1200 | time_limit, score 0 |
| pitch-power-10s | -0.15 / 0.20 / 0.05 / 0.40 | 1200 | time_limit, score 0 |
| trim-full | -0.15 / 0.17 / 0.09 / 0.50 | 4111 | out_of_bounds, score 0 |
| baseline-full | same Python-generated command trace in both engines | 8370 | landed, score 86.519 |

All comparisons pass **1e-6 absolute tolerance**, with identical terminal tick, reason,
success and rounded V2 score. Across these cases, maximum along-track error is
3.87e-8 m, altitude error 3.81e-9 m, airspeed error 1.13e-8 m/s, and pitch error 5.20e-8°.
The largest compared state error is glideslope angle, 1.38e-7°. These are local
floating-point results, not a cross-platform determinism guarantee.

The independent browser/Node baseline also lands, but at **8369 ticks / 86.544**,
versus Python **8370 ticks / 86.519**. This is a separate closed-loop test, not the
identical-input comparison. Small numerical feedback differences grow over the
approach/contact sequence; bit-identical autonomous scores are **not** claimed.
`parity.json` records this separately under `autonomous_baseline`.

The baseline case replays identical commands to isolate engine parity; separately,
its command calculation and canonical temporal observation are compared at every
2 Hz boundary. V2 score fixtures include successful stopped rollout, failed rollout,
unsafe contact and running. Ground-contact detection, pre-contact sink sampling,
trajectory integrals, idle plus symmetric 0.7 braking, terminal ordering and V2 failure
score 0 match the existing environment. No score is submitted to the leaderboard.

## Cloudflare connection

The Worker exposes only `POST /decide` (and CORS preflight). It constructs the four
frozen `Choice` questions server-side, allows only `jev-1.13.0` or `jev-1.14.0`, calls only
`https://api.typesafe.ai/v1/systemone`, rejects redirects, and never retries. HTTP API
`answers` are validated and mapped to canonical IDs and absolute commands. Only model,
action IDs and controls leave the proxy; upstream errors and headers do not.
[TypeSafe API reference](https://docs.typesafe.ai/api/system-one).

The Worker name is `flightbench-jev`; its allowed origin is
`https://alperkartkaya.github.io`. The deployed endpoint is
`https://flightbench-jev.alperkartkaya.workers.dev/decide`. The owner provisioned the
secrets directly in Cloudflare. See `validation.md` for verification boundaries.

### What the owner needs to provide

1. Confirm the target account uses **Workers Free**; do not enable a paid plan.
2. Have a separate, revocable TypeSafe API key ready. Do not send it in chat.
3. Create a separate 32-random-byte base64url token (at least 43 characters)
   in a password manager. It salts stored IP hashes and enables optional private access;
   it is not the provider API key and is never shared with public visitors.
4. After the disabled Worker has been deployed, enter these two values directly in
   Cloudflare Dashboard → **Workers & Pages → flightbench-jev → Settings → Variables
   and Secrets → Add → Secret**:
   - `TYPESAFE_API_KEY`: provider API key, never exposed to the browser.
   - `JEV_ACCESS_TOKEN`: server-only IP-hash salt and optional private-mode bearer secret.

The operator handles deployment, the endpoint URL, CORS, Durable Object binding and
rate-limit checks. No custom domain or DNS setup is required for `workers.dev`. Store secrets
only as Worker secrets, not `.env`, `.dev.vars`, Wrangler vars, GitHub secrets, frontend
build variables, URLs or browser storage. Do not log headers or use credential debug dumps.

### Operator deployment sequence

1. Initially keep `ENABLED = "false"` and `PUBLIC_ACCESS = "false"`. Verify `ALLOWED_ORIGIN` matches the exact Pages origin
   (no repository path or trailing slash). For an initial deployment, temporarily
   set `ENABLED` to false; the checked-in configuration enables the existing Worker.
2. Use a separate, revocable TypeSafe key with a provider-side spending limit if
   available. Create a separate 32-random-byte base64url access token in a password
   manager. Do not use the TypeSafe key as the access token.
3. With explicit publishing authority, authenticate and deploy the disabled Worker:

   ```sh
   cd workers/jev-proxy
   export WRANGLER_SEND_METRICS=false
   npm exec --yes --package=wrangler@4.155.0 -- wrangler whoami
   # If needed: same command prefix, then `wrangler login`.
   npm exec --yes --package=wrangler@4.155.0 -- wrangler deploy
   npm exec --yes --package=wrangler@4.155.0 -- wrangler secret put TYPESAFE_API_KEY
   npm exec --yes --package=wrangler@4.155.0 -- wrangler secret put JEV_ACCESS_TOKEN
   # Each secret command prompts privately; never put the value in the command.
   ```

4. Verify the account is on **Workers Free**, not a paid plan. Keep observability off.
   Set `ENABLED = "true"` and `PUBLIC_ACCESS = "true"` only when the owner agrees to
   sponsor anonymous use, then redeploy. These are the current checked-in settings.
   Visitors select Jev and a version, then start; no endpoint/token fields are shown.
   Both secrets remain server-side. The fixed proxy URL is still visible in source
   and browser network tools; hiding a form field does not make a URL secret.
   Set `PUBLIC_ACCESS = "false"` to require the server's bearer secret again. The
   public frontend intentionally has no credential entry for that private mode.
5. Verify public access, private-mode authentication, strict telemetry validation and minute-rate rejection.
   Set `ENABLED = "false"` and redeploy to disable new calls. Revoke the TypeSafe key
   for an immediate provider-side stop; already-sent requests cannot be recalled.

### Protection and spending boundary

- Public mode deliberately allows anonymous visitors to spend the owner's Jev
  credit. CORS is only a browser-origin restriction, not identity or authentication;
  a non-browser client can spoof Origin. Global and per-IP rate limits, strict schema
  and fixed questions apply independently. No browser token is embedded or required.
  Private mode (`PUBLIC_ACCESS != "true"`) retains hashed bearer-token comparison.
- Exact numeric telemetry schema, enum phase, finite/ranged numbers, control bounds,
  8 KiB streaming body limit. No prompts, models outside the two pinned versions, assets, URL relay or
  user-provided criteria. The response is size-limited and rejects invalid IDs,
  model drift and explicit truncation.
- One **SQLite Durable Object** atomically reserves a minute-rate slot **before**
  upstream fetch. All visitors/POPs share it. Errors/timeouts/disconnects do not
  refund that minute's slot; there are no automatic retries. Storage failure fails
  closed. The deployed class/binding and object name `lifetime-v1` are retained for
  compatibility, but there is **no lifetime or total request quota**, by owner choice.
- Fixed-minute abuse limits remain: **120/client IP**, **180/global**. Trusted Cloudflare
  IP is hashed with the access token before storage. Raw IPs and credentials are not stored
  by application code. Public callers can spend the provider balance; IP rotation cannot
  bypass the global minute rate. NAT users share a rate. Private-mode authentication failures never reach storage
  or TypeSafe. Network-level denial of service is still possible.
- This bounds short-term request rate and prompt size, **not total spending**.
  Provider credit, top-ups, pricing and billing remain external; the proxy does not
  inspect the balance or enforce a money limit. Cloudflare being free does not make
  Jev free. Keep both secrets private. To stop public spending, disable the Worker
  or turn public mode off; rotating the bearer secret alone does not close public mode.
- Workers Free currently has 100,000 requests/day and 10 ms CPU/request; network wait
  does not count as CPU. SQLite Durable Objects are available on Free. This design
  uses one object and tiny transactional state, no paid-only KV-backed DO, Workers AI,
  cron, queue or paid rate-limit binding. Free-limit exhaustion can deny service;
  local tests/dry-run do not certify production CPU or billing.
  [Workers limits](https://developers.cloudflare.com/workers/platform/limits/),
  [DO pricing](https://developers.cloudflare.com/durable-objects/platform/pricing/),
  [transactional storage](https://developers.cloudflare.com/durable-objects/api/sqlite-storage-api/),
  [Worker secrets](https://developers.cloudflare.com/workers/configuration/secrets/).

## GitHub Pages deployment

The updated manual `deploy-pages.yml` builds the WASM runtime and **the existing 3D
UI at the site root** using `/FlightBench/` asset paths. The release recording pages
and media URLs (`human-flight/`, `jev-flight/`, `baseline-flight/`, `media/`) stay intact;
the former recording landing page moves to `recordings/`. The workflow still requires
the selected release's three existing MP4 assets (default `v0.1.0`). It uses existing
Pages environment authorization; no TypeSafe/Cloudflare secret belongs in GitHub.

Publication is a separate release step. The prepared workflow and runtime must first
become available in the remote repository, then the operator dispatches
**Deploy FlightBench simulator to GitHub Pages**.
GitHub's deployment API requires an Actions artifact and Actions-issued OIDC token.
[Pages deployment API](https://docs.github.com/en/rest/pages/pages#create-a-github-pages-deployment).

For the personal-site copy, build with
`npm --prefix frontend run build:pages -- --base=/flightbench/ --outDir=dist-personal`
and publish its contents under `flightbench/` in `alperkartkaya.github.io`.
Both copies use the same physics and Worker; recording links point to `/FlightBench/recordings/`.
For another static host, serve `frontend/dist-pages/` under `/FlightBench/`.
`wasm/` contains runtime assets only, not a second application. Serve `.wasm` as `application/wasm`.
No COOP/COEP, SharedArrayBuffer, service worker or threaded WASM is required. Ship
`wasm/NOTICE.txt` and `wasm/vendor/` source/license/relink files with the binary,
including the 21 MiB source archive. Runtime downloads are about 2.2 MiB plus the 3D
frontend/aircraft; the source archive is an optional download. Pages CSP restricts
network requests to self and `*.workers.dev`; a custom proxy domain requires a deliberate
CSP change. Existing dynamic UI styles require `style-src 'unsafe-inline'`; script
execution remains self-only plus WebAssembly compilation.

## Limits and verification boundaries

- Only easy/no-wind and default V2 scoring; no medium randomization or V1 UI. Tests
  guard the generated contract, not every possible numerical rounding tie.
- Pages uses the existing 3D UI. Human/baseline are paced near realtime, not a timing-certified benchmark. Background
  tabs and slow devices can run slower. Lockstep Jev wall time includes network delay.
- No export/official run provenance, public scores, autopublish, multiplayer, persistent
  credentials or Codex. Existing saved runs and campaigns are untouched.
- Proxy unit tests use fake keys and mock upstream fetch; they test concurrent rates,
  persistence across object reconstruction, authentication, validation and failure paths.
  Public Pages deployment, desktop baseline and emulated phone touch checks passed;
  see `validation.md` for release commits and evidence. Both pinned versions also
  returned validated HTTP 200 decisions through the real public proxy. Production
  Cloudflare CPU/concurrency/billing and Safari/Firefox/physical-device execution
  still require separate live validation.
