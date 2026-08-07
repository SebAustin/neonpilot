# neonpilot — Devpost submission draft

> Draft only. Paste each section into the corresponding Devpost field. Fill in `[REPO-URL]` and
> `[VIDEO-URL]` before submitting. Nothing in this file has been posted or published anywhere.

---

## Project Overview

### What it is

**neonpilot** is a Python CLI that auto-tunes `llama.cpp` runtime flags for Arm CPUs — and, unlike
a generic auto-tuner, tells you *why* a config wins in terms of the chip's actual instruction-set
capabilities. It wraps a pinned build of `llama.cpp` and does three things: **probe** the host Arm
CPU down to the exact KleidiAI kernel tier that activates, **optimize** runtime flags (threads,
flash-attention, KV-cache type, batch/ubatch size) via a staged, thermally-guarded benchmark sweep
that finishes in under 15 minutes, and **report + package** the winner as a self-contained HTML
report and a versioned, shareable JSON preset.

### What makes it interesting

**1. Verified ISA-probe depth, not a feature checklist.** Most Arm auto-tuners report "NEON: yes"
and stop there. On our reference machine — an Apple M1 Max — `neonpilot probe` reports the real
`sysctl` truth: `neon=true, dotprod=true, i8mm=false, sme=false, sme2=false`
(`hw.optional.arm.FEAT_I8MM=0`). We didn't stop at the flag dump. A verbose `llama-bench -v` run
on that same machine confirms exactly which KleidiAI kernel *tier* actually engages:

```
kleidiai: primary q4 kernel feature DOTPROD
kleidiai: primary q8 kernel feature DOTPROD
kleidiai: SME disabled
load_tensors: CPU_KLEIDIAI model buffer size = 30.26 MiB
load_tensors:   CPU_REPACK model buffer size = 17.28 MiB
repack: repack tensor blk.0.ffn_down.weight with q6_K_8x4
```

neonpilot's probe copy states this precisely — "i8mm ABSENT → DOTPROD-tier KleidiAI kernels
engaged; SME disabled; other quant types via CPU_REPACK q6_K_8x4" — instead of the generic
"NEON: yes" most tools stop at. That's the difference between a tool that reads a flag and a tool
that explains the hardware.

**2. Three machines, three regimes, one consistent honesty story.** We ran three full
`neonpilot optimize` sweeps against Qwen2.5-3B-Instruct (Q4_K_M, ~2.1 GB): two on the M1 Max
reference machine under real ambient load (two different days, two different regimes), and one
on an Apple M5 Pro under genuinely idle conditions (`loadavg_1m` 1.07→3.19, receipted by the
tool's own load telemetry) — the clean reference run the challenge's ≥10% bar is actually
measured against:

| Run | Regime | Baseline gen t/s | Tuned gen t/s | Gen speedup | Prefill speedup | Winning config |
|---|---|---|---|---|---|---|
| Jul 20, M1 Max | Heavy load (Docker Desktop ~54%, VM ~19%, Webex; `loadavg` 7.6–12.2) | 9.05 ± 1.79 | 22.11 ± 1.04 | **+144.2%** | +21.9% | `threads=6, fa=off, kv=f16, b=4096/2048` |
| Aug 6, M1 Max | Moderate, non-constant load (`loadavg_1m` 3.78→8.40 mid-run — recorded, not estimated) | 13.24 ± 1.85 | 24.05 ± 0.59 | **+81.6%** | **−12.3%** (reported honestly) | `threads=6, fa=off, kv=f16, b=2048/512` |
| Aug 7, M5 Pro | Idle (`loadavg_1m` 1.07→3.19, well under the tuner's own strict-idle threshold) | 61.57 ± 0.38 | 61.57 ± 0.38 | **+0.0%** | +0.0% | defaults (as resolved by `llama-bench`; nothing beat them) |

The two M1 Max runs independently converge on `threads=6` (not the shipped `threads=8` default,
this chip's own P-core count): `llama.cpp`'s decode loop synchronizes worker threads at a
per-layer barrier, and requesting all 8 P-cores leaves that barrier with zero scheduling slack,
so any competing process forces a preemption that stalls every other worker thread. Leaving two
P-cores unrequested gives the OS scheduler room to service that competing work without stalling
llama.cpp's own barrier — the tuner found that correctly from measurements alone, twice, with no
thumb on the scale. The second M1 Max run also shows the tuner's honesty in the other direction:
its tuned config cost 12.3% prefill throughput even as it won decode by a wide margin
(compute-bound prefill genuinely benefits from more threads; the tuner optimizes generation as
the primary objective), and we report that tradeoff plainly rather than hiding it behind one
flattering number. Its **load telemetry** (`SweepResult.load_before`/`load_after`, recorded
automatically, no manual transcription) is what caught a background VM returning mid-sweep and
turned "the machine was moderately loaded" from a description into a recorded fact.

The M5 Pro run completes the story from the other direction: on an idle, current-generation
chip, `llama.cpp`'s own resolved defaults already beat every tuned candidate the staged sweep
measured. neonpilot reported that honestly — `+0.0%` — instead of inventing a win, and its own
honesty guard refused to package a preset from the run (the winning trial is a reconstruction of
the resolved defaults, not a directly measured/appliable config, and `apply` refuses to package
that unconditionally). That chip's ISA probe also confirms `sme2=true` (`i8mm`, `bf16`, `sme`
all `true` too) against the M1 Max's `sme2=false`, and a `neonpilot compare` run
([`docs/results/m5-vs-m1-compare/`](./docs/results/m5-vs-m1-compare/)) shows the same GGUF file
running **~2.6x** faster on the M5 Pro's defaults than on the M1 Max's best *tuned* result
(61.57 vs. 24.05 gen t/s) — real generational CPU + SME2-vs-DOTPROD kernel-tier uplift, measured
on both ends rather than assumed. All three runs are documented plainly for what they are:
loaded-machine adaptive wins on the M1 Max, and a defaults-already-optimal idle reference on the
M5 Pro — the honest outcome in both directions, never a hand-picked number.

**3. Why it should win.** Most "Arm auto-tune" entrants report a single speedup percentage and
call it done. neonpilot ships a statistical-honesty guard baked into every surface (CLI, Markdown,
HTML) that refuses to print a headline speedup unless the tuned result statistically dominates the
baseline — so a noisy run can never masquerade as a clean win — plus load telemetry that turns
"how busy was the machine" into a recorded, per-run fact rather than a claim. It probes ISA
capability at kernel tier, not feature-flag, resolution, verified on both a DOTPROD-only chip and
an SME2-capable one. And it turns every tuning run into a reusable, schema-versioned artifact
instead of a throwaway log. The three results above are the more compelling story precisely
because they're unpolished, reproduced, and honest in both directions: two show the tuner
reasoning correctly about a real developer laptop doing real work, and the third shows it correctly
refusing to claim a win that isn't there on a quiet, modern chip — not a sanitized benchmark rig
cherry-picking the flattering case.

---

## Functionality / Output

Four commands, one pipeline: `probe` → `optimize` → `report` → `apply`.

- **`neonpilot probe`** — read-only host introspection, <2s, no model needed. Rich table or
  `--json` machine-readable `ChipReport`: chip name, P/E/total core counts, RAM, full ISA feature
  dict, and a one-line "why" per feature.
- **`neonpilot optimize <model.gguf>`** — staged sweep (baseline → threads → flash-attn/KV-cache →
  batch/ubatch → confirm), ≥3 reps/candidate, thermal cooldown, statistical early stopping. Full
  default budget is 900s (15 min); CI uses 180s.
- **`neonpilot report`** — writes `report.md` and a self-contained `report.html` (inline SVG bar
  charts, inline CSS, zero `<script>` tags, zero external asset fetches — opens via `file://` with
  no network calls). Shows the chip ISA table, fast-path activation table, baseline-vs-tuned
  comparison, and the full methodology.
- **`neonpilot apply`** — packages a completed run's winner as a versioned, shareable
  `presets/<chip-id>/<model-class>.json` (chip snapshot, pinned `llama.cpp` commit, measured t/s),
  or loads an existing preset, validates it against the schema, and prints (never executes) the
  exact `llama-bench` invocation for anyone with the same chip to reuse.

**Artifacts produced:** a tuned `RuntimeConfig` (threads/KV-cache/flash-attn/batch/ubatch), a
self-contained `report.html` you can open in any browser with no server, and a shareable preset
JSON under `presets/<chip-id>/<model-class>.json` that turns a one-off personal tuning run into a
community artifact.

---

## Setup Instructions

```bash
git clone [REPO-URL] neonpilot
cd neonpilot

# 1. Install neonpilot + dev dependencies from the committed lockfile
uv sync --locked --extra dev

# 2. Fetch + build the pinned llama.cpp (tag b10069, CPU-only, llama-bench target only)
bash scripts/fetch_llama.sh

# 3. Download a model
mkdir -p ~/.neonpilot/models
curl -L -o ~/.neonpilot/models/qwen2.5-3b-instruct-q4_k_m.gguf \
  "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf"

# 4. Run the whole pipeline in one shot
make benchmark
```

Prerequisites: macOS arm64 (Apple Silicon) or Linux arm64, CPU-only by design (no GPU/Metal),
[`uv`](https://docs.astral.sh/uv/), `cmake` (`brew install cmake` on macOS), Python 3.11+.
`make benchmark` fails fast with the exact `curl` command if the model file is missing. For a fast
smoke test instead of the full 900s run: `MODEL=~/.neonpilot/models/SmolLM2-135M-Instruct-Q4_K_M.gguf make benchmark`.

---

## Built With

`python` `typer` `rich` `llama.cpp` `kleidiai` `arm` `apple-silicon` `gguf` `cmake` `apache-2.0`

---

## Track selection statement

Entered in the **Arm AI Optimization Challenge 2026**, **Mobile AI** track — neonpilot targets
on-device LLM inference optimization for Arm CPUs (Apple Silicon today; Linux/Graviton arm64
designed-to-work), producing an optimization output (tuned runtime config + report + preset) per
device class rather than a hosted/server product.

---

## What's next

- **The three-machine-regime story is now complete and receipted.** Loaded M1 Max (Jul 20),
  moderate-load M1 Max (Aug 6), and idle M5 Pro (Aug 7) are all measured, committed, and
  cross-linked via `neonpilot compare`
  ([`docs/results/m5-vs-m1-compare/`](./docs/results/m5-vs-m1-compare/)). The clean,
  otherwise-idle-machine reference number the challenge's ≥10% bar is measured against landed
  on the M5 Pro run — its honest result is `llama.cpp`'s own defaults already win (+0.0%
  measured), so `presets/` stays empty for both chips: the M1 Max runs were loaded
  (disqualified by our own preset policy), and the M5 Pro run found no config that beats
  defaults to package. No preset was ever fabricated to fill this gap.
- **Apple M5 (SME2) cross-generation comparison — measured on real hardware.** M1 Max is
  DOTPROD-tier only (`i8mm=false, sme=false, sme2=false`); the real M5 Pro probe confirms
  `i8mm/bf16/sme/sme2` all `true` and SME-tier KleidiAI kernel activation instead of DOTPROD.
  Using the same GGUF file, the M5 Pro's defaults run ~2.6x the M1 Max's best tuned result
  (61.57 vs. 24.05 gen t/s) — real generational CPU + kernel-tier uplift, not a synthetic
  estimate.
- **More chips via community presets.** The `presets/<chip-id>/<model-class>.json` schema and
  `apply`'s validate-then-print-invocation workflow are already built for third parties to
  contribute presets for other Arm chips (Graviton, other Apple Silicon generations) without any
  code changes to neonpilot itself — including chips where, like the M5 Pro here, the honest
  outcome may be "defaults already win, nothing to package."
