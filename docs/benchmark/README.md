# Benchmark flight data

[CSV](ten-trial-results.csv) contains one row per scored flight: campaign and group,
model, mode, seed, run ID, terminal status, V2 score, mean latency, API-equivalent
cost for GPT‑6.2 Sol and the Decision APIs, and SHA-256 of the compressed episode.
Failures count in the outcome bar, but not in the best or average score. No successful
landing means both scores are unavailable.

The ten seed labels (42, 101, …, 909) identify ten repeats of the same calm-air Easy
scenario; they are not ten different weather conditions. Lockstep waits for each
response at fixed 2 Hz. Hosted realtime runs use fixed 2 Hz, 1× speed and discard stale
responses. Local realtime runs use 1× continuous dispatch and apply responses on arrival
rather than fixed 2 Hz request timing. A gray block adds neither a success nor a failure:
for local lockstep only the reference flight (seed 42) is counted; for Microsoft Decision 1.1
lockstep the green block stands for all ten identical results. Codex ten-flight rows use
low reasoning. No score-based retries are part of the data. Realtime cohorts without
a successful landing are retained in the CSV but omitted from the chart.

Within each group, models with at least one successful landing come first.
Within each outcome tier, models are sorted by provider release date, newest first.
We use the dated general-availability launch where documented; otherwise we use
the provider's public release announcement. Decision APIs are dated by the endpoint
release, not the underlying model's release.

| Group | Release dates (2026) |
| --- | --- |
| Jev | [1.14: Oct 14](https://typesafe.ai/blog/jev-1-14), [1.13: Sep 15](https://typesafe.ai/blog/introducing-system-one-models-and-jev) |
| Codex | [OpenAI changelog](https://developers.openai.com/api/docs/changelog): 6.2 Sol: Nov 17; 6.1 Terra: Oct 26; 6.1 Sol: Sep 29; 6 Luna: Sep 22; 6 Astra: Sep 3 |
| Local | [Bison 1: Nov 20](https://www.baseten.co/resources/changelog/bison-1-and-groundhog-1-available-on-baseten/), [GLiDE v1.2: Oct 22](https://fastino.ai/blog/training-glide-sota-decision-model) |
| Decision API | [Microsoft Decision 1.1: Nov 17](https://commandline.microsoft.com/microsoft-decision-model-ga/), [Gemini Decision 1: Nov 11](https://blog.google/innovation-and-ai/technology/developers-tools/gemini-decisions-api/), [Luna: Oct 22](https://openai.com/index/decisions-api/), [Microsoft Decision 1: Oct 9](https://commandline.microsoft.com/microsoft-decision-1-model-foundry/) |

| Local campaign | Eligible evidence | Excluded attempts |
| --- | --- | ---: |
| `2026-11-15-ten-trial-easy` | 110 audited flights; both Jev modes, Codex and three Decision APIs in lockstep | 21 |
| `2026-11-19-microsoft-decision-1.1-easy` | 10 audited Microsoft Decision 1.1 lockstep flights | 1 |
| `2026-11-20-glide-v1.2-easy-20-continuous` | GLiDE v1.2: 0/1 lockstep, 0/10 realtime | 9 identical lockstep repeats not plotted |
| `2026-11-21-bison-31b-easy-20` | Bison 1: 0/1 lockstep, 0/10 realtime | 9 identical lockstep repeats not plotted |
| `2026-11-24-gpt-6.2-sol-easy` | 10 audited GPT‑6.2 Sol lockstep flights; 8/10 | 1 |
| `2026-11-25-microsoft-decision-1.1-realtime` | 10 audited realtime flights; 0/10 (9 nose-first contacts, 1 runway excursion) | 0 |
| `2026-11-26-decision-realtime-microsoft` | Microsoft Decision 1: 0/10 realtime (9 nose-first contacts, 1 runway excursion) | 0 |
| `2026-11-26-decision-realtime-luna` | Luna: 0/10 realtime (6 nose-first contacts, 2 runway excursions, 2 out of bounds) | 0 |
| `2026-11-26-decision-realtime-gemini` | Gemini Decision 1: 0/10 realtime (10 out of bounds) | 0 |

The A100 campaign (`2026-11-25-a100-lockstep`) completed all 33 scored flights.
Decider's first audited lockstep flight is retained; extra lockstep repeats and
the interrupted tenth lockstep attempt are not counted.

| Colab model and release date | Lockstep landings | Realtime landings |
| --- | ---: | ---: |
| Groundhog 1 ([Nov 20](https://www.baseten.co/resources/changelog/bison-1-and-groundhog-1-available-on-baseten/)) | 1/1 (64.61) | 0/10 |
| KnowLine‑31B Gen2 ([Nov 13](https://huggingface.co/PelaAI/KnowLine-31B-Gen2#releases)) | 0/1 | 0/10 |
| Decider v1.3 27B ([Nov 12](https://www.perplexity.ai/hub/blog/perplexity-decider)) | 0/1 | 0/10 |

Campaigns have a `status.json` and audit report under `docs/evaluations/<campaign>/`.
The corresponding manifests, episode archives, replays and provider journals are
retained locally under `leaderboard/campaigns/<campaign>/`, not bundled in this checkout.
The local cohorts were replay-audited in their original environment; no strict leaderboard
submission or hosted Bison API parity is claimed. Earlier Decision API realtime pilots are not
pooled across different timing policies. The Gemini Decision 1 realtime adapter spaces HTTP
requests by at least four seconds for quota; its result reflects that pacing, not unthrottled
provider performance. Microsoft Decision 1.1's realtime series uses
the archived seed-42 flight plus nine repeats on the same simulator source and protocol.
Its ten lockstep flights had identical requests, answers and applied actions. In realtime,
all ten applied action sequences differed even though identical recorded requests received
identical categorical answers and probabilities.

The original rows retain their historical cost, latency and comparison values.
GPT‑6.2 Sol uses the best-scoring flight (seed 101) for cost and latency; both comparisons
use the same historical Jev 1.14 lockstep reference as the original rows. Cost uses the
recorded provider token usage and [OpenAI Standard short-context rates](https://developers.openai.com/api/docs/models/gpt-6.2-sol),
not actual Codex billing. Local models show average per-flight latency relative to the
same mode's historical Jev 1.14 time, without assuming a comparable API price.
The separate historical cost chart is unchanged.

Decision API costs are the arithmetic mean of the ten per-flight costs, including
failed landings. The exporter prices recorded successful responses from the provider
journals; transport retries without reported usage are not included. Comparisons use
the historical Jev 1.14 reference for the same mode when a reference value is available.
These are list-price estimates, not invoices or free-tier charges.

| Decision endpoint | Input tokens across ten flights | Published USD per 1M input tokens |
| --- | ---: | --- |
| Luna Decision API | 1,372,890 | [$0.10 uncached](https://developers.openai.com/api/docs/guides/decisions#pricing-and-availability); the journals show no cache activity |
| Microsoft Decision 1.1 | 3,556,850 | [$0.042 Global Standard](https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/introducing-microsoft-decision-1-1-build-faster-more-efficient-ai-applications-w/4573877) |
| Microsoft Decision 1 | 2,769,993 | [$0.042](https://commandline.microsoft.com/microsoft-decision-1-model-foundry/) |
| Gemini Decision 1 | 3,130,870 | [$0.10 paid tier](https://blog.google/innovation-and-ai/technology/developers-tools/gemini-decisions-api/) |

All four endpoints have no output-token charge.

Rebuild the two theme charts from the CSV:

```sh
uv run --no-sync --with vl-convert-python==1.9.0 python -m examples.build_trial_visuals
```

On the machine with the original logs, add `--refresh-local` to re-export the CSV
after checking the manifests and replay outputs. The Sol 6.2 campaign is included
only after all ten runs pass its audit.
