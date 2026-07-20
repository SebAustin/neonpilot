# neonpilot — Demo script (screen recording, <3:00)

Narrated walkthrough of the real `probe → optimize → report → apply` pipeline on the Apple M1 Max
reference machine. Every number spoken in this script is drawn from
[`README.md`](../README.md) and [`docs/results/m1-max-loaded-20260720/`](../docs/results/m1-max-loaded-20260720/)
— nothing here is scripted fiction. Hand this to `ai-video-producer` for a recorded/edited pass if
a produced video is wanted; the beats below are also enough to run live.

## Recording setup (do this before hitting record)

- **Terminal:** font size 18–20pt, window 1280x800, dark theme, no visible desktop clutter.
- **Quit Docker Desktop, any VM, and Webex/video-call apps before recording** — the whole point of
  this demo is to show the sweep adapting to the machine as it actually is; if you want to
  reproduce the *loaded-machine* story on camera, leave them running instead and say so explicitly
  on camera (don't silently misrepresent an idle recording as the loaded case study, or vice
  versa — pick one and narrate which one it is).
- **Model:** if recording time is tight, use `SmolLM2-135M-Instruct-Q4_K_M.gguf` with
  `--budget 180` instead of the full 900s Qwen2.5-3B sweep — narrate that you're using the fast
  CI-scale model/budget for time, not the full-model defaults.
- **No copyrighted music.** No third-party trademarks beyond fair, factual references (e.g. saying
  "Apple M1 Max," "llama.cpp," "KleidiAI" is fine — these are factual identifiers of what the tool
  measures, not endorsements).
- Pre-open a terminal tab already `cd`'d into the repo, and a browser tab ready (but not yet
  navigated) for the HTML report.

---

## Shot list

### 0:00–0:15 — Hook

**Visual:** black screen or terminal prompt, no motion yet.

**Narration:** "`llama.cpp` ships defaults that assume your machine is idle. Your machine is never
idle — you've got Docker running, a VM, maybe a video call. neonpilot is the tuner that adapts to
your machine as it actually is, and tells you why."

### 0:15–0:45 — `neonpilot probe`

**Visual:** run `uv run neonpilot probe` on the M1 Max. Camera/screen holds on the Rich table long
enough to read the ISA feature row and the fast-path "why" column.

**Narration:** "This is an Apple M1 Max. `neonpilot probe` doesn't just say 'NEON: yes' and stop —
it reports the exact sysctl truth: NEON true, DotProd true, I8MM false, SME2 false. And it maps
that straight to which KleidiAI kernel tier actually loads: on this chip, DOTPROD-tier kernels
engage for q4 and q8 weights, SME is disabled, and everything else falls through to a generic
CPU_REPACK path. That's verified against a real verbose `llama-bench` log, not a guess from
documentation."

*(Optional B-roll: cut to the verbose `llama-bench -v` log lines showing
`kleidiai: primary q4 kernel feature DOTPROD` / `kleidiai: SME disabled` for ~3 seconds as visual
proof.)*

### 0:45–1:45 — `neonpilot optimize` (timelapse)

**Visual:** run `uv run neonpilot optimize <model> --budget 180 --reps 3` (or the full 900s run if
you have the recording budget — cut/timelapse to ~8x speed between stage transitions so the live
trial table is visible but the dead air is compressed). Show at least one full stage transition
(baseline → Stage A thread sweep → Stage B flash-attn/KV-cache → Stage C batch/ubatch → confirm)
and one pruned trial in the live table.

**Narration (over the timelapse):** "This is the staged sweep — not a brute-force grid. It
measures the baseline first, exactly what `llama.cpp` does out of the box with zero flags. Then it
sweeps thread count, locks in the winner, sweeps flash-attention and KV-cache type, locks that in,
then sweeps batch size. Every candidate gets at least three repetitions, and once a leading
candidate statistically dominates the rest of a stage, the remaining trials in that stage get
pruned — that's what you're seeing marked here — so it finishes in minutes, not hours."

### 1:45–2:10 — HTML report

**Visual:** open `report.html` in the browser (from `~/.neonpilot/runs/latest/report.html`). Scroll
to the baseline-vs-tuned bar chart.

**Narration:** "This is the self-contained report — one HTML file, inline SVG and CSS, zero
external requests, opens straight from disk. On a real run on this machine — under heavy ambient
load, Docker and a VM and Webex all fighting for the same P-cores — the tuner found threads=6 beat
the shipped default of threads=8, and generation throughput went from 9.05 tokens/sec to 22.11 —
a 144% improvement. That's not because threads=6 is universally better; it's because leaving two
P-cores free gave the OS scheduler room to service the other processes without stalling
`llama.cpp`'s own per-layer thread barrier. The report says this in plain language, and it flags
explicitly when a result doesn't statistically hold up — it will never hand you a clean headline
number the data can't back."

### 2:10–2:30 — `neonpilot apply`

**Visual:** run `uv run neonpilot apply --run-dir ~/.neonpilot/runs/latest` (or, if this is the
loaded-machine run specifically, narrate that no preset gets committed from a loaded run per
project policy — show `apply` loading an existing committed preset instead and printing its
invocation).

**Narration:** "`apply` packages the winning config into a versioned JSON preset with full
provenance — the chip snapshot, the pinned `llama.cpp` commit, the measured numbers. Anyone with
the same chip can load that preset and get the exact `llama-bench` invocation printed back to
them — reviewed and copy-pasted, never auto-executed — without re-running the sweep themselves."

### 2:30–2:50 — Close

**Visual:** cut back to the terminal or a static title card with repo link.

**Narration:** "neonpilot — Arm AI Optimization Challenge 2026, Mobile AI track. Apache-2.0,
open source, link in the description."

**On-screen text:** repo URL placeholder `[REPO-URL]`, license `Apache-2.0`.

---

## Fallback if something fails live

- **If the sweep stalls or a stage errors on camera:** cut away to the pre-recorded
  `docs/results/m1-max-loaded-20260720/report.html` (the real, already-captured loaded-machine run)
  and narrate "here's a completed run captured earlier under the same conditions" rather than
  dead air. This is real, already-run output — not fabricated — so it's an honest fallback, not a
  fake demo.
- **If the HTML report doesn't render correctly in the recording browser:** switch to `report.md`
  in a terminal pager or editor preview; the content is identical, just less visual.
- **If `apply` errors on a preset path:** fall back to describing the JSON schema fields on
  screen (`schema_version`, `server_flags`, provenance) rather than forcing a live retry loop.
- **Always keep the actual `docs/results/m1-max-loaded-20260720/` artifacts open in a second tab**
  as a safety net for the whole recording — every number in this script traces back to that
  directory, so it doubles as your source-of-truth reference if you get a question live.
