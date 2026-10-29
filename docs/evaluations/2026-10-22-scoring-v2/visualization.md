# Benchmark figures

Regenerate both SVGs and the complete measurement CSV from the repository root:

```sh
uv run --script examples/build_benchmark_visuals.py
```

The script pins `vl-convert-python==1.9.0` and Vega-Lite 6.4. `uv` creates an
isolated script environment; FlightBench's runtime dependencies are unchanged.
No browser, Node server or network resources are needed to view the generated SVGs.
The initial generator setup needs network access to download its renderer.

## Data and interpretation

[`results.json`](results.json) is the existing full-precision source of truth.
The generator reads its 16 original selected runs plus verified additions from
[`additional-results.json`](additional-results.json). Neither command launches or
rescores flights. The CSV retains full precision for all metrics and run identities.
Wall time is the difference between recorded start and finish timestamps.

The leaderboard groups model families and separates lockstep and realtime execution.
Score emphasis uses the highest exact score within each panel. Both Jev versions
receive cost/latency emphasis as requested, not a claim of identical measurements.
Each Jev row displays 1×; other hosted rows compare against Jev 1.14 lockstep using
unrounded measurements. The CSV keeps raw ratios even for Jev rows. Cost uses three
decimals (four for Jev); score and latency use three. `≥` preserves an incomplete
recorded cost lower bound, not an exact price.

The original performance/API-cost figure is restored separately. Terra uses a blue
circle in the same gold as the other GPT markers; only completed effort cohorts are added. Highest scores are selected across
seeds 42, 101 and 202; if none lands successfully, the cohort is repeated once.
Provider errors are not treated as completed flights. Attempts and source identity
remain available in the campaign evidence directories.

All published scores use the current canonical scoring configuration. Local models
are validated against the same configuration and included only when their score is
positive. [Local physics replay verification](local-score-verification.json) records
the recalculation of all 18 local flights. No obsolete scores are carried into the
leaderboard; unknown local hardware/electricity prices are not plotted as API costs.

Refresh additions and the original plot before rebuilding the theme variants:

```sh
.venv/bin/python examples/update_benchmark_additions.py
uv run --script examples/build_benchmark_visuals.py
```

The background Terra runner performs both commands after each completed effort.
Campaign progress is recorded in `scratch/terra-v2-2026-10-28/status.json`;
`failure.json` signals a stopped campaign requiring inspection, not a flight failure.
The archived benchmark source differs from the prior source revision; the new Terra
pricing entry is $1/M input, $0.05/M cached input and $5/M output, from the
[official model page](https://developers.openai.com/api/docs/models/gpt-6.1-terra).
The frozen source archive and trial manifests preserve the exact revision used.

## Design sources and reuse

The implementation uses **Vega-Lite's chart grammar and static SVG renderer**, not
hand-positioned SVG primitives. It adapts the upstream
[layered bar + numeric label example](https://vega.github.io/vega-lite/examples/layer_bar_labels.html):
shared data encodings, proportional score bars, and reserved label space.
[VlConvert](https://github.com/vega/vl-convert) handles scales, layout, axes, shapes,
text and SVG export. The Python generator creates declarative specifications only.

Reviewed designs and the specific patterns carried forward:

- [Primer data visualization](https://primer.style/product/ui-patterns/data-visualization/),
  [typography](https://primer.style/product/getting-started/foundations/typography/) and
  [color primitives](https://primer.style/product/primitives/color/): restrained
  hierarchy, explicit units, semantic light/dark colors, numeric labels, minimal
  grid lines, multiple visual encodings, and a linked complete dataset.
- [GitHub diagram guidance](https://docs.github.com/en/contributing/writing-for-github-docs/creating-diagrams-for-github-docs):
  readable static output, useful alt text and no unnecessary decoration.
- [Aider leaderboard](https://aider.chat/docs/leaderboards/) and
  [its OSS implementation](https://github.com/Aider-AI/aider/blob/5dc9490bb35f9729ef2c95d00a19ccd30c26339c/aider/website/_includes/leaderboard.js):
  primary score/cost summary, with complete measurements kept outside the main view.
- [Artificial Analysis](https://artificialanalysis.ai/): separate quality, latency
  and price; cost–performance scatter as a secondary view. Information hierarchy
  only; no proprietary code, artwork or branded chart styling is copied.
- [FlashAttention performance figures](https://github.com/Dao-AILab/flash-attention#performance):
  separate panels for distinct execution conditions rather than one mixed ranking.
- [Hindsight benchmarks](https://benchmarks.hindsight.vectorize.io/) and
  [bar component source](https://github.com/vectorize-io/hindsight/blob/bf511d9798c26cd5ed42b27a351cc66f86c7fd5b/hindsight-docs/src/components/HomeBenchmarks.tsx):
  direct numeric labels alongside proportional horizontal bars.
- [Hyperfine plotting scripts](https://github.com/sharkdp/hyperfine/blob/master/scripts/README.md):
  recorded JSON → a standalone, reproducible plotting command.

Alternatives considered: [Observable Plot](https://observablehq.com/plot/getting-started#plot-in-node-js)
needs a DOM implementation for Node export; [ECharts SVG SSR](https://echarts.apache.org/handbook/en/how-to/cross-platform/server/)
adds a Node toolchain; [Satori](https://github.com/vercel/satori) supplies layout but
not scientific chart scales/axes. Vega-Lite + a single isolated Python renderer is
the smallest suitable fit for this repository.

### Licenses

Vega-Lite and VlConvert: BSD-3-Clause. Primer primitives: MIT.
Aider: Apache-2.0; Hindsight: MIT; Observable Plot: ISC; ECharts: Apache-2.0;
Satori: MPL-2.0. Aider/Hindsight/other tool implementations were inspected, not
copied or redistributed. Applicable Vega-Lite/VlConvert and Primer notices are
retained in [visualization-licenses.txt](visualization-licenses.txt).

## Rendering verification

Both theme variants are self-contained SVG, selected in the main README using
GitHub's `#gh-dark-mode-only` / `#gh-light-mode-only` image fragments.
Render at README width for local inspection, for example:

```sh
rsvg-convert -w 830 benchmark-light.svg -o /tmp/benchmark-light.png
rsvg-convert -w 830 benchmark-dark.svg -o /tmp/benchmark-dark.png
```

Run the data, layout, theme-parity and export regression checks:

```sh
uv run --no-project --with vl-convert-python==1.9.0 --with pytest \
  python -m pytest tests/test_benchmark_visuals.py -q
```

## Additional Terra landing retries

After the initial campaign completed, the user requested one extra attempt for each
failed high/xhigh seed: high 101/202 and xhigh 42/101. Originals are unchanged; retry
evidence lives under each effort's `landing-retry-1/<seed>` directory. Each completed
retry is disclosed in `additional-results.json`. Only a successful retry with a higher
score replaces the selected run, including all its measurements, cost and token usage.
Progress: `scratch/terra-v2-2026-10-28/landing-retry-1/status.json`.
