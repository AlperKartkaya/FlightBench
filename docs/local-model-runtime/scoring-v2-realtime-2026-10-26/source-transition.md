# Audited source transition

The October 22 and October 26 campaigns retain different source identities and flight dates.
Only `flightbench/scoring.py` and `flightbench/benchmark.py` changed between their frozen
archives: strict trajectory-evidence and token-count validation guards. Observations,
controller options, dynamics, timing, score formula and valid-usage pricing are unchanged.

[Exact source diff](source-transition.diff) · [Hashes and validation result](source-transition.json).
All 54 completed non-max October 22 records were evaluated with both archived and current
scoring implementations; full score results were identical. Their `episode_rows` outputs,
including usage/cost, were also identical under both benchmark implementations.

This permits a specifically disclosed comparison of these two audited source versions;
it does not establish equivalence for arbitrary source hashes or realtime versus lockstep.
