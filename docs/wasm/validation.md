# Local validation — 2026-10-29

These are local checks, not deployment or live-provider evidence.

- JSBSim 1.3.1 compiled with Emscripten 4.0.18; original source checksum checked.
- Python/WASM replay: 5 cases, 16,081 physics ticks plus initial states; every
  observation/result and every decision-state/baseline calculation passed 1e-6.
  Detailed maxima and independent closed-loop discrepancy: [parity.json](parity.json).
- Python suite: 269 passed, 1 skipped; existing Gym warnings remain.
- Browser engine/Worker/proxy Node tests: 12 passed; upstream requests use fake credentials
  and mocks, not TypeSafe. Atomic storage is mocked in unit tests.
- Frontend tests: 18 passed (14 existing, 4 new adapter tests). TypeScript/Vite
  local and Pages builds passed;
  existing >500 kB bundle-size warning remains.
- Ruff check + format checks passed for flightbench/, tests/, and both new Python
  entry points. Node syntax checks, Bash syntax check and git diff whitespace check passed.
- Wrangler 4.155.0 dry-run passed. Actual local workerd started, recognized the SQLite
  Durable Object binding, and returned a no-store CORS-filtered 503 with ENABLED=false.
  Dry-run alone had missed a runtime export issue; the final entry point exports
  only the handler and Budget class and was checked in local workerd.
- Chromium desktop: loaded the module Web Worker and WASM, human aileron keyboard
  input reached -0.16, stop/reset worked. Independent baseline completed a real
  browser flight: landed, 69.74 simulation seconds, V2 score 86.544.
- Initial engine checks at `/FlightBench/wasm/` (standalone page subsequently removed): relative assets/Worker imports loaded.
  Mocked Jev produced two decisions at simulation times 0 and 0.5 s; invitation input
  cleared on start. Mocked 429 stopped physics and re-enabled reset, without fallback.
- Chromium 390×844 layout had no horizontal overflow; native range controls have
  explicit accessible names. Screenshots and CLI logs remain in ignored scratch/.

No real TypeSafe key was provisioned or sent to the proxy/browser by this integration.
The comparison command disables dotenv loading before importing the baseline. No Cloudflare
production deploy, GitHub Pages deploy, live Jev call, production quota/CPU/billing
verification, Firefox/Safari/device test, git staging or commit was performed.
No sub-agent was spawned. The updated CI workflow was inspected but not
executed on GitHub. Existing run/campaign/leaderboard evidence was not modified.


## Existing 3D UI / Pages-root validation

- `npm --prefix frontend run build` still targets `dist/`, root asset paths and the
  existing Python WebSocket. `build:pages` targets a separate ignored `dist-pages/`,
  `/FlightBench/` asset paths and the module Worker. No backend code, frozen protocol,
  scoring implementation or prior run evidence changed in this integration.
- Chromium loaded the actual 3D aircraft/scene at a static `/FlightBench/` prefix,
  including after adding the Pages CSP. Two independent baseline flights reached
  safe landing; the original outcome dialog displayed **86.5 / 100**, not a saved-run claim.
  Backend-independent JS baseline precision remains 86.544 in the parity evidence.
- Human keyboard A reached applied aileron **-0.512**; stop produced **Stopped**, score
  **0.0**, and the previous completion label. Start/reset/camera controls remain the same UI.
- Mocked Jev produced calls at **0, 0.5, 1.0 simulation seconds**. Two responses updated
  the existing live-decision cards; the third (429) ended with **Controller error**,
  a visible HTTP error and no fallback. Invite input cleared. This is not live Jev.
- Chromium 390×844: WebGL initialized, proxy fields visible, document scroll width
  **390**, no horizontal page overflow. Desktop/mobile screenshots are in ignored
  `scratch/pages-*.png`. Console had only a password-input-not-in-form advisory,
  no network/CSP/script errors in the 3D checks. The archived recording player
  still requests the absent site-root `/favicon.ico` (404); video metadata loaded.
- Actual Python-backed UI smoke test used port 8190 and an isolated ignored
  `FLIGHTBENCH_RUNS_DIR`, with dotenv disabled. Human keyboard input reached **-0.290**;
  human and baseline runs started/stopped and saved **two interrupted records** there.
  Both returned to Ready/ONLINE as before. `/api/models` was mocked empty solely to
  avoid invoking optional local Codex discovery; no Codex model was run or integrated.
- The existing recording-page build shell ran locally against release `v0.1.0`;
  all three original MP4 assets were downloaded unchanged (about 103 MB). Its old
  landing page moved to `recordings/`; original player/media URLs remain present.
  Player and MP4 responses returned HTTP 200 at the local Pages prefix. Chromium
  followed the archive → human-player link and loaded MP4 metadata (52.58 s).
- Complete ignored package: `scratch/pages-package/site/` and
  `scratch/flightbench-pages.tar` (about 123 MiB), including the runtime source/licenses,
  3D model and recordings. No `.env` or proxy deployment/secret files are in it.
  SHA-256: `dbb2bed5b2d1fb72833f6d6fb534e7f407f8a420fbba2e92490486ef4de2f2cb`.
- GitHub read-only checks confirmed Actions-based Pages and the old remote recording
  workflow. No workflow was dispatched, setting changed, artifact uploaded, stage or
  commit performed. The public recording landing page remains unchanged.

Remaining publication prerequisite: the remote workflow revision must first receive
these files; current no-commit instructions prevent that supported route. The Pages
API requires an Actions-issued OIDC token and repository artifact; local `gh` auth
alone does not supply either. Cloudflare secrets/live Jev and hosted Linux CI remain
unverified. The browser runtime does not persist results or replace official evidence.


## Release cleanup plan

1. Remove the redundant standalone 2D page and its JS/CSS; retain the shared physics,
   Worker, parity fixtures, build bindings and license/source distribution.
2. Replace development labels with product copy; keep truthful completed vs saved
   status, fixed-scenario settings, authentication, quotas and actionable errors.
3. Standardize asset preparation, Worker name and access-secret names across code,
   configuration, tests and deployment instructions. Do not deploy or reset a budget.
4. Re-run existing frontend/Worker security tests, Python contract checks and both
   builds; verify the generated site has no retired page or stale development copy.

Before cleanup: 18 frontend and 12 engine/Worker/proxy tests passed.


### Release cleanup results

- Removed the redundant 2D HTML/JS/CSS, retired development labels and repeated UI
  notices. The sole application is the existing 3D workbench; browser completion is
  labeled Completed rather than Saved. Physics, scoring and safety guards are unchanged.
- Renamed asset preparation to `examples/prepare_wasm.py`, Worker to `flightbench-jev`
  and its separate client credential to `JEV_ACCESS_TOKEN`; updated all active callers,
  tests and setup instructions. Set the allowed origin to the actual Pages origin.
- Fresh checks: 18 frontend tests, 12 engine/Worker/proxy tests and 3 Python contract
  tests passed. Both builds, Ruff check/format and Wrangler dry-run passed. Existing
  Three.js bundle-size warning remains a build diagnostic, not a removed safety check.
- Chromium confirmed Jev endpoint/access-token labels, absence of development copy,
  human aileron -0.430, Stopped outcome and Completed status at `/FlightBench/`.
- Reassembled the complete local package without the retired page or stale bundles;
  updated the checksum above. No production deployment or credential provisioning ran.
- `wrangler whoami` verified the existing Cloudflare OAuth session and Worker-write
  scope. Account billing plan and live TypeSafe remain unverified. The provider key
  still needs to be supplied directly as a Worker secret by the owner.

## Cloudflare activation — 2026-10-29

This supersedes the unpublished/unprovisioned status recorded above; GitHub Pages
has not been updated in this step.

- Deployed `https://flightbench-jev.alperkartkaya.workers.dev/decide`, version
  `5d57a890-038e-4e03-b00e-f208a1f6490d`, with `ENABLED=true`, the existing SQLite
  Durable Object binding, observability off and a 240-attempt lifetime quota.
  No namespace/object reset or quota increase was performed.
- The owner entered `TYPESAFE_API_KEY` and `JEV_ACCESS_TOKEN` through the Dashboard.
  Wrangler listed both as `secret_text` before and after activation; secret values
  were not read or supplied to local commands, the frontend or repository files.
- All 7 proxy tests passed. Seven live HTTP checks passed: missing/invalid bearer
  401, denied/missing origin 403, preflight 204 with the exact allowed origin,
  wrong method 405 and query relay 404. Python's default HTTP client encountered
  Cloudflare error 1010; the same checks succeeded using curl.
- No valid access token was used in these checks, so no Jev upstream call was made
  and no quota slot was consumed by them. Provider-key validity, authenticated
  browser-to-Jev execution, live quota exhaustion and account billing plan remain
  unverified. The quota limits attempts through this Worker, not other key usage.

## Release completion plan — 2026-10-29

1. Replace lifetime-quota tests with regressions for unlimited total usage and retained
   atomic minute-rate limits; remove only the lifetime cap, preserving deployed bindings.
2. Verify phone-sized touch controls while the scene remains visible; fix input release,
   multi-touch and layout without changing desktop physics, scoring or keyboard controls.
3. Verify favicon paths, both static prefixes and the local build; publish FlightBench
   and the personal-site copy, preserving the owner's root README and recording URLs.

### Pre-publication checks

- Removed the lifetime request limit at the owner's request. The deployed Worker
  version `e5572d91-b7e4-499b-978c-543fad72aa2b` has no `TOTAL_CALLS` variable;
  the existing Durable Object binding/identity and 120/client-IP, 180/global minute
  limits remain. Unit tests allow 360 attempts across minutes even with previously
  exhausted legacy storage. Missing bearer still returns 401 in production.
- 270 Python tests passed, 1 skipped, 4 existing warnings. 18 frontend and 13
  engine/Worker/proxy tests passed. Both local and Pages TypeScript/build checks passed.
  Scoped Ruff check/format passed for 44 current code/test files. Repository-wide Ruff
  also inspected archived campaign scripts and reported 16 existing errors there;
  immutable campaign evidence was not reformatted. Existing Three.js chunk warning remains.
- Chromium touch emulation passed at 390×844, 320×667 and 844×390: 44px control targets,
  simultaneous pitch/roll, independent release, pointer cancellation, stop/reset and
  no horizontal overflow. The same 3D scene remains visible while reaching controls.
  The existing PNG favicon resolves under the Pages base; no substitute icon was added.
- The owner's root README checksum remains
  `06c195d79ac411c1a44f32a9cefe3f4aff8dd3dd3e27aa4d716a5796fb14fbf5`.
  No real phone/Safari or authenticated TypeSafe call was tested in this step.
