> **Superseded.** Event tagging now runs on the DeepSeek API instead of an
> offline local model — the 4GB RAM constraint below made local models
> impractical anyway. See `classification.md` (taxonomy + prompt design)
> and `src/helpers/tagging.py` (implementation). This folder and file are
> kept for reference in case local tagging is revisited later.

# Event tagging model

This folder is a placeholder for downloading an offline model used to tag
scraped events with `topic` and `event_type` (see the taxonomy in
`src/helpers/schema.py` / the tagging spec discussed in planning).

## Hardware reality check

The tagging job runs on the cloud server, which is **CPU-only with 4GB of
RAM**. The "50GB" budget mentioned early on is disk space for model
weights/cache, not RAM — RAM is what actually limits which model can be
*loaded*, and 4GB is a hard, tight ceiling once the OS, Python, and any
other pipeline process (scraper, DB writer) are accounted for.

**Qwen3-8B does not fit.** Even at 4-bit (Q4_K_M) quantization it needs
~5GB just for weights, before KV-cache and runtime overhead — that alone
exceeds the box's total RAM. It was never going to run here regardless of
disk space.

## Recommendation: don't use a generative LLM at all

Tagging events into a **fixed, closed taxonomy** (11 topic categories /
~100 leaf topics, 14 event-type categories / ~100 leaf types) is a
classification problem, not a generation problem. A prompted decoder LLM
(Qwen3, Llama, etc.) has to be told the whole label list in the prompt,
has to be trusted to only output labels that actually exist, and burns a
lot of RAM/compute on autoregressive decoding for what is ultimately a
"pick from a list" task. A small **NLI-based zero-shot classifier**
(encoder-only, cross-encoder scoring `event text` against `label text` via
entailment) fits this task better and is 10-40x lighter:

- **Primary pick: [`MoritzLaurer/deberta-v3-base-zeroshot-v2.0`](https://huggingface.co/MoritzLaurer/deberta-v3-base-zeroshot-v2.0)**
  (~184M params, ~370-450MB on disk in fp32, smaller if cast to fp16/int8).
  Purpose-built for exactly this: zero-shot classification against an
  arbitrary candidate label list, with a HF `pipeline("zero-shot-classification")`
  one-liner and native multi-label support (independent entailment score
  per label, so an event can get both "STEM & Technology" and "Education").
  Comfortably fits in 4GB RAM alongside the rest of the pipeline.
- **If RAM is still tight in practice: [`MoritzLaurer/deberta-v3-small-zeroshot-v2.0`](https://huggingface.co/MoritzLaurer/deberta-v3-small-zeroshot-v2.0)
  or `...-xsmall-zeroshot-v1.1-all-33`** (~142MB) — small accuracy trade-off
  for a much smaller footprint and faster CPU inference.
- Export to **ONNX** (`optimum[onnxruntime]`) instead of running full
  PyTorch if inference is too slow on CPU — cuts both memory and latency
  noticeably versus eager PyTorch, and drops the (large) `torch` runtime
  dependency.

### Why not a generative model at all, even a tiny one?

If you'd rather keep a generative LLM (e.g. to also sanity-check/repair
the `audience` field, or handle titles too terse for the classifier to
work with), the smallest reasonable *current* options that fit 4GB RAM at
Q4 GGUF are **Qwen3-1.7B** (~1.1GB) or the newer **Qwen3.5-0.8B**
(~0.5-0.6GB, released Feb 2026, better instruction-following per size than
Qwen3 was). Both leave real headroom in 4GB. But at ~100 leaf labels per
taxonomy, a small decoder model is much more prone to inventing labels,
picking near-duplicates, or breaking JSON formatting than the NLI
classifier is — you'd need grammar-constrained decoding (e.g.
`llama.cpp` GBNF grammar restricted to the exact label set) to make it
reliable. **Not recommended as the primary approach**; the zero-shot
classifier above should be tried first.

### Recommended architecture: two-stage hierarchical classification

Both taxonomies are two-level (category → subcategory), and flattening
~100 leaf labels into one classification call invites confusion between
near-duplicate labels. Instead:

1. Classify the top-level category first (11-way for topic, 14-way for
   event_type) — few options, much more reliable.
2. Classify the subcategory using only the leaf labels under the chosen
   top-level category — a much smaller, less ambiguous candidate set.

This also keeps each classifier call cheap (fewer candidate labels =
fewer entailment forward passes), which matters on a CPU-only box.

### Cheap win: use the existing `categories` field as a prior

Scraped events already carry a `categories` field from TAMU's own calendar
(e.g. `"Sports & Athletics"`, `"Academic Calendar"`) — see
`data/sample_events.json`. For events where that maps unambiguously to a
tag (e.g. "Sports & Athletics" → event_type "Sporting Event" / "Athletic
Competition"), skip the model entirely and rule-map it. Reserve model
inference for events where the source category is missing, generic, or
doesn't cleanly map — cuts CPU load substantially given the 4GB ceiling.

## New dependency

Whichever path is chosen, `requirements.txt` will need `transformers`
(+ `torch` or `optimum[onnxruntime]` for a lighter CPU runtime) — not
added yet since tagging isn't implemented (`src/helpers/tagging.py` is
still an empty placeholder).
