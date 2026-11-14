# Difficulty scoring review — 2026-11-14

Proposal only. V2, safety thresholds, existing records and benchmark rankings are unchanged.

## Why a safe landing displayed zero

Local run `4c89b357-7bed-4594-b06e-56dac1ec060a` (human, hard, seed 42)
has `success=true`, `touchdown_safe=true`, and completed rollout. Touchdown was
3.35 m past the threshold, 5.78 m off center, at −1.80 m/s sink, 20.70 m/s airspeed,
−3.06° bank and 4.46° heading error: all current safety gates passed.

V2 scores the whole approach, not just touchdown: `100 × exp(−E)`. Its normalized
lateral error was 48.7573, contributing 14.6272 of total error 15.2105 (96.2%). The
unrounded score was **0.0000248**, stored as 0.000. This is exponential compression
plus rounding, not failure to recognize the safe landing. Initial offset alone does
not explain this much accumulated error. A recovery should count, but it should
not erase a poorly controlled approach.

## Fresh reference runs

Provider-free Python JSBSim baseline from `55452d1` (simulation/scoring unchanged by
this UI patch), default 2 Hz, complete rollout.
Fixed seeds: 42, 101, 202, 303, 404, 40, 41, 43, 44, 45 for each scenario.
Local raw results: `scratch/instrument-scoring-2026-11-14/baseline.json` (ignored).

| Scenario | Safe / attempted | V2 mean, all attempts | V2 mean, safe only |
|---|---:|---:|---:|
| Easy | 10 / 10 | 99.17 | 99.17 |
| Medium | 10 / 10 | 83.23 | 83.23 |
| Hard | 8 / 10 | 43.68 | 54.61 |

Hard seed 101 left the runway; seed 40 had unsafe contact. Those zeros are not
scoring harshness and should remain zero. Among successful runs, average lateral
error was 0.486 in medium and 1.883 in hard; lateral tracking dominates the loss.
This is a small diagnostic set, not a full performance benchmark or WASM parity study.

## Recommended V3 direction

Separate **landing success** from **approach precision**:

- Keep the same touchdown/rollout safety gates in every difficulty. Wind does not
  make an off-runway, excessive-sink, excessive-bank or uncontrolled rollout safe.
- Failure/incomplete flight: **0**. Safe landing: **50 + 50 × exp(−E_d)**.
  The lower half communicates completion; the upper half rewards technique. This
  restores the success/failure separation V1 had, without V1's component clipping.
- Keep existing weights, pitch/rate penalties and touchdown targets/normalizations.
  Do not give a blanket wind bonus or divide by the baseline's score.
- For the approach only, provisionally use lateral scales **10 / 15 / 20 m** and
  glide scales **15 / 20 / 25 m** for easy / medium / hard. These soften precision
  penalties, not safety gates. Each error term is still squared and integrated
  over the same 60-second reference. Initial recovery remains measurable.
- Always display outcome separately from score, and compare rankings within the
  same difficulty. Label V3 explicitly; never silently rescore V2 leaderboard runs.

Offline application to the same diagnostic set gives safe-only means **99.58 /
95.14 / 90.59**, and hard all-attempt mean **72.47**. The human safe-zero example
would score **50.86**: successful recovery, but poor approach precision. These
numbers illustrate the proposal, not a fitted target for the baseline.

Before adopting: freeze scales against a wider held-out seed set and human/other
controller trajectories, inspect component distributions and incentives (long
approaches, intentional drift, weak but safe landings), add V3 fixtures in both
Python and WASM, and version config hashes/reporting. A simpler first step is the
same safety-separated formula with current scales; difficulty calibration should
not be tuned just to make one controller reach 99.
