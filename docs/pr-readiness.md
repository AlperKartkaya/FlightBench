# PR readiness: canonical controllers and community evaluations

Target branch: `feat/community-local-model-benchmarks`. Intended issues: #1 and #2.
No commit, push, PR creation, issue closure, or deployment is performed by this work.

## Delivered

- Frozen categorical action semantics remain unchanged; scoring V2 is separately versioned. Jev and Codex export their validated canonical IDs;
  mock-provider tests cover actual adapters, real short JSBSim episodes, both evaluation modes,
  portable export, and strict validation. Selected versus held stale commands remain distinct.
- Submission evaluation claims are bound to every full record's scenario, rate and mode scale.
  Raw decision/final-state evidence independently checks counts and duration; contradictory
  request accounting is rejected. Tests mutate fields even after updating evidence hashes.
- CLI and browser terminal handling disclose outstanding/uncollected work, without applying late
  actions. Provider errors end headless runs instead of silently continuing held controls.
  Unknown remote usage does not become a complete cost total; no thread-cancellation guarantee
  is made.
- External `module:Class` and long `file.py:Class` references export in both modes. Small default
  display identifiers no longer inherit an arbitrarily long filesystem path.
- Generated publication exposes conditions, source identity, execution conditions, recorded/
  completed/applied/stale/late decisions, unknown historical started counts and simulation-time
  rate basis. Different source/config/execution cohorts and legacy references are not silently
  ranked together. Failed trials say no successful landing.
- Native truncation signals fail closed. Seven fixed diagnostic states exercise signs,
  priorities, phase thresholds and overlapping criteria. A 28-response pinned local Kev cache
  experiment records unchanged choices and its limited latency result; see
  [diagnostic evidence and reproduction](decision-diagnostics.md).
- PR validation runs offline Python regressions and lint/format checks, validates the published
  schema and data, and continues to use the base branch's verification registry without paid
  provider credentials or executing contributed controllers for benchmarks.

## Validation

- Full Python suite: **225 passed**, with four existing Starlette/Gymnasium warnings.
- Frontend: **13 passed**; TypeScript check and Vite build passed. Existing large-bundle warning
  remains. The browser now explicitly requests apply-on-arrival.
- Ruff check/format passed for production code, tests and the publication generator; archived
  runtime scripts are preserved verbatim. Published-schema comparison passed. Staged diff whitespace checks pass outside verbatim
  runtime archives, whose original trailing whitespace is retained for hash provenance.
- All staged leaderboard submission manifests validate, including twenty historical submissions;
  the original V2 campaign retains 54 completed flights. The revised publication includes
  16 groups: best-of-three except the explicitly user-selected successful Luna high seed42
  retry. Jev 1.13 uses the first lockstep repeat and second realtime repeat (best 38.577); prior cohorts remain archived.
  Four additional failed Jev episodes are preserved separately as DNS/infrastructure evidence.
  Historical records, protocol hash and archived
  measurement source were not rewritten. Archive SHA-256 was checked independently.
- Actual external-controller CLI smoke completed both modes and exported a submission. It was
  a fixed-choice example, not evidence of successful model landings.

## Explicit boundaries

Archived model runs retain their dated runtime metadata and full episode evidence. `easy` seeds
repeat the same physical initialization. The shortlist is not a verified global popularity
ranking. No result is independently reproduced/verified by this PR.

Frozen wording ambiguities and possible precision/rendering/model-capability limitations are
research hypotheses, not bugs fixed by secretly changing v1. Scoring V2 has an explicit version, complete configuration hash, and new controlled evidence. Native token bytes and cache hits were not invented where a
runtime did not expose them. Remote GitHub CI execution and hosted publication remain untested
locally. Review these limits with the PR rather than claiming universally flawless behavior.

## Scoring V2 publication gate

- Default V2 score follows `scoring_v2.md`; V1 remains selectable and historical records are unchanged.
- Physics-time integrals freeze at first main-gear contact; failed rollout scores zero.
- Publication requires the canonical full scoring configuration, exact requested model/effort groups,
  and three completed seeds per group. Luna high uses the successful seed42 retry selected by the user,
  with failed/interrupted attempts archived and the different selection disclosed.
  Missing usage does not become zero cost: realtime outstanding requests produce explicit
  lower-bound prices in the table, not invented complete totals.
- Codex efforts are explicit CLI/run/decision metadata. The published 16-group comparison
  includes low/medium/high/xhigh only; max evidence is archived, not plotted.
- New campaign: `leaderboard/campaigns/2026-10-22-scoring-v2/`. Runtime/attempt timestamps and source
  archive are under `docs/local-model-runtime/scoring-v2-2026-10-22/`.
- Open-model result prose/SVG/PNG were removed; dated raw evidence remains archived.

## Minimal archive and offline replay

- Removed 234 redundant sidecars from the publish set; unique complete/completed-failure
  records and infrastructure evidence remain. Status/resume history is consolidated,
  not silently discarded.
- Physics-only rescoring reproduced all 16 selected flights without provider calls;
  source logs remain immutable. See the runtime README for parameter and replay limits.
- Graph labels are enlarged and placed beside their markers; no effort callout lines,
  realtime rings, cost arrows or Luna high asterisk remain. Lower-bound costs remain
  explicit in the table and SVG accessibility descriptions.
