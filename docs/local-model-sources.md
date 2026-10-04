# Local System One model sources

Evidence snapshot: **2026-10-02**. This is a bounded, practical shortlist for an
Apple M1 Pro with 16 GB unified memory. It is **not** a claim that these are the
five most popular models worldwide. The local decision-model ecosystem is new,
and Ollama pulls, Hugging Face downloads/likes, and GitHub stars measure
different things and change over time.

## Selection boundary

These five models make typed decisions by scoring caller-supplied alternatives
in one forward pass. They do not produce a free-form answer and then parse it.
That makes them materially closer to Jev than a generic Qwen, Phi, Gemma, or
other autoregressive chat model.

The common interface is `POST /v1/systemone`, with `choice`, `score`, and
`noul` (yes/no) questions. Ollama's endpoint requires version 0.35.0 or later
and only accepts compatible GGUF weights with a scoring-capable runner; it does
not load arbitrary MLX or Safetensors checkpoints. Nimble and OpenThai are the
Ollama-native recommendations here. The other three need their publishers'
local server or an in-process adapter.

Primary interface reference: [Ollama System One API](https://docs.ollama.com/api/systemone).

## Recommended shortlist

| Model | Genuine decision path | Recommended local artifact | License | Current adoption signal | M1 Pro 16 GB recommendation |
| --- | --- | --- | --- | --- | --- |
| [Bespoke Nimble 9B](https://ollama.com/library/nimble) | Answer-token logits through Ollama's scoring runner; no text generation | `nimble:9b-q4_K_M`, registry tag digest `572f1f4c801d`, 5.6 GB | Apache-2.0 | Ollama: 21.1K pulls; HF upstream: 4,262 monthly downloads, 226 likes | **Use.** Best-supported path; run alone or with only one small peer process. |
| [Kev 0.8B](https://huggingface.co/jaredpalmer/kev-0.8b) | Frozen Qwen3.5-0.8B backbone, prefill-only, plus a pointer head | `jaredpalmer/kev-0.8b@v1.0` = `bf75a6a8848ea6960ff2ed108d9ed44c2941174f`, about 1.5 GB MLX weights | Apache-2.0 | GitHub: 8,280 stars; HF: 11,298 monthly downloads, 36 likes | **Use.** Small, but markedly weaker out of domain. |
| [OpenThai-SystemOne v0.3 Q8](https://ollama.com/iapp/openthai-systemone) | Ollama System One answer-letter logits; no text decoding | `iapp/openthai-systemone:0.8b-q8_0`, 812 MB | Apache-2.0 | HF Ollama artifact: 471 downloads, 1 like; Ollama: 17 pulls | **Use with low-adoption caveat.** Publisher-supported Thai + English scoring build; 8,192-token configured context and 26-option limit fit FlightBench. |
| [Von 1.3](https://huggingface.co/wfzyx/von) | Bidirectional ModernBERT encoder plus option-marker head; no generation | HF revision `498ceba33390b32cfefaab6422ec380318ba9b99`, 1.58 GB | Apache-2.0 | HF: 80,938 monthly downloads, 53 likes; GitHub: 812 stars | **Use.** 8,192-token context; avoid long, multi-clause numerical decisions. |
| [Mapika Decider 2B](https://huggingface.co/Mapika/decider-2b-GGUF) | One-pass slot-logit scoring; no decoding | Q4_K_M GGUF revision `ff2e5e687327eda9ac34e9a3ca84d3f400672c87`, 1.27 GB | Apache-2.0 | Full HF model: 275,828 monthly downloads, 97 likes; GitHub: 1,035 stars | **Use in-process for Q4.** Its official HTTP server serves the full Safetensors model, not GGUF. |

Popularity numbers above are publisher/platform counters observed on the
snapshot date. They are useful provenance/adoption signals, not comparable
quality scores. Model-card benchmark claims are publisher-reported, not an
independent FlightBench validation.

## Pinned artifacts and launch paths

All services should bind to `127.0.0.1`, run in isolated virtual environments,
and receive no unrelated secrets. Download first, verify the hashes below, and
only then launch. Pinning package versions alone is insufficient if a command
still resolves model weights from a mutable `main` branch.

### 1. Nimble 9B Q4_K_M

Official sources:

- [Ollama tags](https://ollama.com/library/nimble/tags)
- [Bespoke model card](https://huggingface.co/bespokelabs/Bespoke-Nimble-9B)
- [Bespoke source repository](https://github.com/bespokelabsai/nimble)

```sh
ollama pull nimble:9b-q4_K_M
```

Pinned Ollama model blob:

```text
size:   5,629,108,736 bytes
sha256: 0e228c45932655a4b97b175eba79a578e180778ce0d576a10b86f8726962d993
```

The short tag digest shown by Ollama is `572f1f4c801d`. Record both the tag and
the full blob digest in benchmark metadata. The current upstream Hugging Face
checkpoint is revision `bd792f44...`, but it is not byte-identical to the
merged/quantized Ollama artifact and must not be used as its provenance pin.

Nimble's card reports 75.7% versus Jev's 76.0% on Bespoke's 3,880-decision
suite. Treat this only as a vendor-reported reference; FlightBench is a new
control distribution and needs its own runs and calibration.

### 2. Kev 0.8B

Official sources:

- [Kev 0.8B model card](https://huggingface.co/jaredpalmer/kev-0.8b)
- [Kev repository](https://github.com/jaredpalmer/kev)
- [Kev 1.0 release](https://github.com/jaredpalmer/kev/releases/tag/kev-1.0)

The original `kev-1.0` source tag points to
`6b719c3c3f367295f6ef336f4f751cf5ff970abc`, while the campaign uses the
reviewed current server commit `84847f0a883d900f7de5b7a57eaa341ca7f9a6b4`.
The model-card's first-published revision `9a45d25e` resolves to
`9a45d25eb2ab761841196625383fa1dff0e56c1e`; the campaign intentionally uses
the later immutable `v1.0` revision
`bf75a6a8848ea6960ff2ed108d9ed44c2941174f`. Record that distinction rather
than describing the moving `main` branch as the evaluated checkpoint:

```sh
git clone https://github.com/jaredpalmer/kev.git vendor/kev
cd vendor/kev
git checkout 84847f0a883d900f7de5b7a57eaa341ca7f9a6b4
uv sync --extra serve --frozen
uv run --extra serve python -m kev.serve \
  --run jaredpalmer/kev-0.8b@v1.0 \
  --host 127.0.0.1 --port 8008
```

Artifact checks:

```text
release source tarball sha256:          0ae144c7675f0c3f333be0bb878a0f202ab9e6fa84169fb7cb16efe6176c1ef1
adapter_model.safetensors (43,338,624): 9b908623acb162118575f4e7a94524f9c139c335be4bfb74d6cfceca01e1885a
head.pt (2,103,999):                  f400bd12802b2b105ae45d6b03774a158a3db4fccff42413734ddca2e5c920b6
```

**Security gate:** the reviewed server calls `torch.load` on `head.pt` without
an explicit `weights_only=` argument. PyTorch `.pt` files are pickle-capable.
The campaign's PyTorch 2.8 runtime defaults `weights_only=True`, but that safety
property is version-dependent: do not run it under an older default, execute a
mutable/unverified file, or omit the hash check. An explicit
`weights_only=True` remains preferable. The Safetensors adapter itself does not
carry the same pickle risk. The campaign also pins the Apache-2.0 Qwen base to
`dc7cdfe2ee4154fa7e30f5b51ca41bfa40174e68`.

The card reports a 5.3 GB process at 8K context on an M5/32 GB machine and says
Apple Silicon selects MLX automatically. That is a useful fit signal, not proof
of the M1 Pro peak RSS. Measure it locally before parallel scheduling.

### 3. OpenThai-SystemOne v0.3 Q8

Official sources:

- [Ollama publisher page](https://ollama.com/iapp/openthai-systemone)
- [Pinned Ollama GGUF repository](https://huggingface.co/iapp/OpenThai-SystemOne-Ollama)
- [Training/inference source repository](https://github.com/iapp-technology/openthai-systemone)
- [Main decision-head checkpoint](https://huggingface.co/iapp/OpenThai-SystemOne)

Use the publisher-recommended Q8 build on the isolated Ollama 0.35.0 server:

```sh
OLLAMA_HOST=http://127.0.0.1:11435 \
  scratch/ollama-0.35.0/ollama pull iapp/openthai-systemone:0.8b-q8_0
```

Pinned registry artifact:

```text
HF repository revision: 4c9b06aab79da2cf96368f0a214cbe26496659f5
size:                   811,864,768 bytes
model blob sha256:      24ccacfa663273b160c7c7d8f6d60e4a334dbef472d33b3193fb4a68b1ed7c74
config blob sha256:     c5f7947ef90b7469f193e617106b05e368dac30d7f7fa384db9c8cf2b0bc6110
system blob sha256:     bc311040d7361a272f9e0c101a42785963d8e568dbcca0cb188b409f48bc57de
params blob sha256:     ce4a164fc04605703b485251fe9f1a181688ba0eb6badb80cc6335c0de17ca0d
license blob sha256:    283ea6cc2997a1a70da0049e09adf9317bb60ca1b51279b65196b83a69e1996b
```

This is not an ordinary chat checkpoint substituted for a decision model. The
publisher fine-tuned the weights against Ollama 0.35's exact System One prompt
and scoring path. Ollama runs one prompt per question and returns next-token
probabilities for answer letters without decoding a free-form response. The
Modelfile fixes `num_ctx 8192`; the endpoint accepts 2--26 options per question.
FlightBench has four questions and at most ten options, and its unmodified
seed-42 APPROACH request fits this context.

The publisher reports a 74.3 macro over 13 public English/multilingual subsets
for Q8 and 82.5 over its Thai suite. Those figures are self-reported and are not
flight-control validation. Adoption is also much lower than the other selected
models because this Ollama build was published only the day before this
snapshot. It is selected for genuine System One semantics, exact protocol fit,
Apache-2.0 provenance, and a publisher-supported M1-sized artifact--not because
it is globally popular.

### 4. Von 1.3

Official sources:

- [Von model card](https://huggingface.co/wfzyx/von)
- [Von repository](https://github.com/wfzyx/von)
- [von-sdk package](https://pypi.org/project/von-sdk/)

Download weights to a local directory first so the runtime cannot silently
advance with the Hub's `main` branch. Use `von-sdk==1.3.7`, source tag `v1.3.7`
(commit `587f1022293366b99dd97a0c8a86dd62e5ef8836`):

```sh
hf download wfzyx/von \
  --revision 498ceba33390b32cfefaab6422ec380318ba9b99 \
  --local-dir vendor/von-1.3
uv venv .venv-von --python 3.12
uv pip install --python .venv-von/bin/python "von-sdk==1.3.7"
VON_CHECKPOINT_DIR="$PWD/vendor/von-1.3" \
  .venv-von/bin/von serve --device mps --host 127.0.0.1 --port 8010 \
  --on-overflow refuse
```

Pinned files:

```text
model.safetensors (1,579,143,688): af57d5d2ab15715a753a1eb4add4271d1aecce7e76f3365f629c082df329297a
option_marker.pt (1,581,316,459):   3faf27f88d30aaf9aa37860d4cdef99f1d05450cf40364f6236ac892d4d139ed
```

The reviewed runtime loads `option_marker.pt` using
`torch.load(..., weights_only=True)`, which bounds the usual pickle execution
risk. Keep the hash check because deserialization safety does not establish
model correctness. The card describes Von 1.3 as retaining the 1.2 weights;
1.3.7 is the runtime package pin, not a new weight revision.

### 5. Mapika Decider 2B

Official sources:

- [Full model card](https://huggingface.co/Mapika/decider-2b)
- [GGUF model card](https://huggingface.co/Mapika/decider-2b-GGUF)
- [Decider repository](https://github.com/Mapika/decider)
- [decider-ai package and provenance](https://pypi.org/project/decider-ai/)

Use `decider-ai==1.8.1`, source tag `v1.8.1` (commit
`50d0be0d7cb43d2066965ce5fa7f3fe4e489a60f`). The recommended 16 GB path is
the pinned Q4_K_M GGUF in-process:

```sh
uv venv .venv-decider --python 3.12
uv pip install --python .venv-decider/bin/python "decider-ai[gguf]==1.8.1"
hf download Mapika/decider-2b-GGUF \
  --revision ff2e5e687327eda9ac34e9a3ca84d3f400672c87 \
  --include "*Q4_K_M.gguf" --include "*.json" --include "*.jinja" \
  --local-dir vendor/decider-2b-q4
```

```python
from decider.infer import Decider

model = Decider(
    "vendor/decider-2b-q4",
    gguf_file="decider-2b-v11-Q4_K_M.gguf",
    gguf_options={"n_gpu_layers": -1},
)
response = model.system_one(state, questions)
```

Pinned Q4 artifact:

```text
size:   1,274,396,800 bytes
sha256: b7c132a67934d51c81abc96bb7724800f965ff5a288aed3e1ca7d8bc349c1386
```

The publisher reports about a 0.5-point held-out loss from Q4 quantization.
That needs local confirmation on FlightBench. Metal support may require
building `llama-cpp-python` with `CMAKE_ARGS="-DGGML_METAL=on"`; verify that the
installed wheel actually offloads layers rather than assuming the option did.

The official HTTP server does **not** serve GGUF. For an HTTP-only adapter,
download the full pinned revision
`533964dae8be954c5b5e19fa4948e48408094c1e` and serve it instead:

```sh
uv pip install --python .venv-decider/bin/python \
  "decider-ai[serve,metal]==1.8.1"
hf download Mapika/decider-2b \
  --revision 533964dae8be954c5b5e19fa4948e48408094c1e \
  --local-dir vendor/decider-2b-full
DECIDER_MODEL="$PWD/vendor/decider-2b-full" DECIDER_DEVICE=mps \
  .venv-decider/bin/uvicorn decider.serve:app \
  --host 127.0.0.1 --port 8011
```

The full `model.safetensors` is 3,763,692,048 bytes with SHA-256
`acaef2228b134dcdc20cad4ee79219482c927ec819aa3687b9b8a575c338817f`.
Loading the GGUF in ordinary Ollama or `llama-cli` is not equivalent: those
runners perform text continuation and do not expose Decider's slot-logit
System One answer path.

## Trust and execution policy

1. **No remote custom code.** None of the recommended launch paths needs
   `trust_remote_code=True`. Do not enable it to make an unreviewed revision
   load.
2. **Prefer data-only formats.** Safetensors and GGUF are preferred. The two
   `.pt` exceptions are explicitly accounted for above; Kev is blocked until
   its hash and loader mitigation are in place.
3. **Isolate runtimes.** One virtual environment per publisher, loopback-only
   binding, no credentials, and exact package/source/model revisions.
4. **Capture provenance per run.** Record runtime/package version, Git commit,
   model revision/tag, model-file SHA-256, device/backend, and quantization in
   every result manifest.
5. **Do not reuse benchmark seeds for calibration.** Tune prompt/schema and
   temperature on separate data, then freeze them before the five lockstep and
   five realtime seeds.

## Parallelism on 16 GB unified memory

The selected weight files total about 10.8 GB when Mapika uses Q4, before
Python runtimes, Metal buffers, KV/state caches, JSBSim, and the browser/UI.
Starting all five models together is therefore not a credible 16 GB plan.

Use a bounded worker pool of at most **two model processes**, measure resident
and Metal memory on this exact M1 Pro, and reduce to one on swap, memory
pressure, timeout drift, or backend allocation failure. Keep Nimble out of a
pair if its observed footprint plus the peer exceeds the safe budget. Parallel
benchmark jobs may share a loaded model only if the model server documents
concurrent request isolation; otherwise serialize runs per model and parallelize
across two models. This still shortens the campaign without turning memory
pressure into a model-quality confounder.

## Important exclusions

- **Tev1 4B/0.8B:** the official cards describe a standard next-token head,
  not a non-autoregressive Jev runtime, and say the fine-tuned weight license is
  still being finalized. It is not eligible for this strict open-source list.
  Sources: [Tev1 4B](https://huggingface.co/togethercomputer/Tev1-4B-experimental),
  [Tev1 0.8B](https://huggingface.co/togethercomputer/Tev1-0.8B-experimental).
- **Clef / Clef Flash:** the checkpoints are real System One models under
  Apache-2.0, but the Ollama library pages returned 404 on the snapshot date,
  and the official Clef Flash artifact is about 9B BF16 with no verified
  publisher-supported M1 quantized decision runtime. Re-evaluate when an
  official local scoring artifact exists rather than inventing an Ollama tag.
  Source: [Cloudflare Clef announcement](https://blog.cloudflare.com/clef/).
- **Laya 421M:** downloaded and audited but excluded after full-protocol conformance.
  The official runtime caps each criterion at 48 tokens; FlightBench aileron criteria
  require up to 71 Laya tokens, and its instruction requires 275. Raising the overall
  context does not remove the per-criterion cutoff. A small homemade smoke fixture
  passed but was not FlightBench conformance; the actual unchanged request is refused.
  No Laya result is included in the 50-run matrix.
  Source: [official Laya code](https://github.com/NandhaKishorM/laya).
- **Generic local LLMs:** structured JSON or tool calling does not convert an
  autoregressive generator into a System One decision model. They should be a
  separately labelled controller class, not represented as Jev equivalents.

## Stop conditions before a benchmark claim

A model is usable only after: the artifact hash matches; the pinned server
starts without remote-code execution; a fixed conformance fixture returns
valid `choice`, `score`, and `noul` probabilities; a repeated request is stable
within the backend's stated numerical tolerance; and a short FlightBench smoke
run completes without `controller_error`. Failure is recorded as an invalid
run, not retried until it disappears or included in a best-of graph.
