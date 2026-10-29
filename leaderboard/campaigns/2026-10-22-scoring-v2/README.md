# 2026-10-22 scoring V2 campaign

The directory date is the campaign start date (Europe/Istanbul). Resumed flights
may occur on later dates; every run and resume bundle retains its actual UTC
timestamps. Pricing is frozen to the documented 2026-10-22 basis.

Original serial lockstep evaluation: four GPT model families at low, medium, high
and xhigh; Jev 1.13 and 1.14. One GPT family is now excluded from publication,
while its raw historical evidence is retained. Original target: three completed
flights per group (seeds 42, 101 and 202), 54 flights across 18 groups.

Seeds repeat the same easy physical initialization, not distinct landing scenarios.
For the original campaign, select the highest-scoring completed flight in each group, with the API-equivalent
cost of that same full flight. Completed poor landings are retained. The later Luna high same-seed success-retry
request is a separately disclosed October 26 extension, not a rewrite of these records.

## Interruptions and retries

The non-max campaign is **complete: 54 flights / 18 groups**. Each group has
three completed flights. [Published comparison](../../../docs/evaluations/2026-10-22-scoring-v2/README.md).
[Attempt history](attempt-history.json) lists excluded controller/time-out/startup
attempts and their preserved raw evidence. Those are additional attempts, not
part of a claim that only three total attempts were made per group. An exported
`controller_error` does not by itself establish a provider fault: the sanitized
record does not preserve its underlying exception.

The [runtime directory](../../../docs/local-model-runtime/scoring-v2-2026-10-22/)
contains the original frozen source archive, active runner/status/log, and dated
resume bundles. Each resume preserves its runner and hashes. Benchmark source
must remain identical throughout. Following repeated max interruptions, max groups were initially moved after the non-max groups; execution remains serial.

After repeated sanitized controller errors, `diagnostic_entry.py` was added as a
campaign-only launcher. It delegates to the same benchmark and controller,
logging only exception class, integer HTTP status, validation categories and
allowlisted limit indicators before reraising the original exception. It does
not alter observations, decisions, provider options, scoring or retries inside a
flight. Its exact version is hashed in each subsequent resume bundle. The first
observed category was `APIError`, without an HTTP status; that alone does not
prove a quota, sleep or connectivity cause.

## Best-of-three extension

The user expanded the original best-of-two request on 2026-10-24. Starting from 39 completed flights, `run-third.py` resumes missing original
flights and appends seed 202 to each group using
the same frozen benchmark source. Existing two-flight combined submissions and metadata
are preserved as `*-best-of-two.json`; individual flight records are unchanged.

Max flights were initially deferred, then excluded from the active campaign and
publication at the user's request on 2026-10-25. Existing max evidence is retained
for later work; it is not plotted or ranked.

## Post-campaign validation

The benchmark implementation was frozen throughout the flights; its exact source
is in the runtime archive. After completion, validation was hardened to reject
missing/empty V2 trajectory integrals and malformed token counts. These guards
do not change any recorded flight's score or cost: all published flights contain
complete integrals and valid actual usage. Reproduce the flight implementation
from the archived source, rather than relabeling it as the later checkout hash.
