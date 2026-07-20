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

**2. The loaded-machine case study — the honest, real-world result.** We ran a full 900-second
`neonpilot optimize` sweep against Qwen2.5-3B-Instruct (Q4_K_M, ~2.1 GB) on the M1 Max reference
machine — but the machine wasn't idle. Docker Desktop was pulling ~54% CPU, a VM ~19%, plus Webex
and WindowServer, pushing `loadavg` to 7.6–12.2 on a 10-core machine. The sweep still completed in
full (`budget_truncated=false`, 543.9s elapsed, back-to-back confirm pass) and found:

| Metric | Baseline (`llama.cpp` defaults, threads=8) | Tuned (`threads=6, fa=off, kv=f16, b=4096/2048`) | Speedup |
|---|---|---|---|
| Generation t/s (median ± stddev) | 9.05 ± 1.79 | 22.11 ± 1.04 | **+144.2%** |
| Prefill t/s (median ± stddev) | 137.8 ± 56.6 | 168.0 ± 2.2 | **+21.9%** |

We frame this honestly, not as a headline "2.4x" flex: `llama.cpp`'s decode loop synchronizes
worker threads at a per-layer barrier. Requesting all 8 P-cores (the shipped default) leaves that
barrier with zero scheduling slack — on an idle machine that's optimal, but under this machine's
real ambient load, the OS had to preempt one of llama.cpp's own worker threads to service Docker/
the VM/Webex, and every other thread then stalled at the barrier waiting for it. That's exactly
what the baseline's wildly unstable prefill (±56.6 t/s stddev on a 137.8 t/s mean) shows. Leaving
two P-cores unrequested (`threads=6`) gave the OS scheduler room to service the competing
processes without stalling llama.cpp's own barrier — and the tuner found that correctly from
measurements alone, with no thumb on the scale. This is explicitly documented as **"measured under
ambient load; adaptive result, not an idle-machine reference"** — the clean idle-machine number
that the challenge's ≥10% bar is meant to be checked against is still an open item (see "What's
next" below), and we say so plainly rather than presenting a loaded-machine number as a clean-room
one.

**3. Why it should win.** Most "Arm auto-tune" entrants report a single speedup percentage and
call it done. neonpilot ships a statistical-honesty guard baked into every surface (CLI, Markdown,
HTML) that refuses to print a headline speedup unless the tuned result statistically dominates the
baseline — so a noisy run can never masquerade as a clean win. It probes ISA capability at kernel
tier, not feature-flag, resolution. And it turns every tuning run into a reusable, schema-versioned
artifact instead of a throwaway log. The loaded-machine result above is the more compelling story
precisely because it's unpolished: it shows the tuner reasoning correctly about a real developer
laptop with Docker and video calls running, not a sanitized benchmark rig.

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

- **Idle-machine reference number.** The loaded-M1-Max case study above proves the pipeline and
  tuning logic end-to-end on real hardware, but the clean, otherwise-idle-machine number that the
  challenge's ≥10% speedup bar is measured against is not yet captured — re-running
  `make benchmark` on a quiet machine is the next step, and no number will be published for it
  until that real run exists.
- **Apple M5 (SME2) cross-generation comparison.** M1 Max is DOTPROD-tier only (`i8mm=false,
  sme2=false`); we expect an Apple M5 run to show `sme2=true` and SME-tier KleidiAI kernel
  activation instead of DOTPROD, demonstrating the ISA-driven cross-generation story the report
  format already supports. This is `[unverified]` pending access to M5 hardware.
- **More chips via community presets.** The `presets/<chip-id>/<model-class>.json` schema and
  `apply`'s validate-then-print-invocation workflow are already built for third parties to
  contribute presets for other Arm chips (Graviton, other Apple Silicon generations) without any
  code changes to neonpilot itself.
