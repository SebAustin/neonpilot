# Apple M5 runbook — turnkey benchmark run

For whoever is sitting at the Apple M5 machine, in a hurry. This is the whole thing.

## The 3 commands

```bash
git clone https://github.com/SebAustin/neonpilot.git
cd neonpilot
bash scripts/quickstart.sh
```

That's it. `scripts/quickstart.sh` does everything else: checks you're on arm64 macOS, installs
`cmake`/`uv` via Homebrew if they're missing (it will **not** install Homebrew itself — if you
don't have `brew`, the script tells you exactly what to install manually and stops), syncs
neonpilot's dependencies, builds the pinned `llama.cpp`, downloads the reference model with a
checksum check, probes this chip, and runs the full benchmark. It's safe to re-run if anything
fails partway through or you close the terminal — every step skips work that's already done.

## What to expect

| Step | Time | Notes |
|---|---|---|
| Prerequisite checks + `uv sync` | seconds | Skips cleanly if `cmake`/`uv` are already installed. |
| Build `llama.cpp` | **~5 min, one-time only** | Skipped on any re-run (checks a pin stamp against the exact commit neonpilot is pinned to). |
| Download the reference model | **~2 GB** | Qwen2.5-3B-Instruct Q4_K_M. Skipped if already present and its checksum verifies. On a slow connection this is the longest step. |
| `neonpilot probe` | <2s | Prints two tables: ISA features and llama.cpp fast-path kernel activation. **Screenshot both** — see below. |
| The benchmark sweep | **~15 min** | `probe → optimize → report → apply` against the reference model, 900s budget / 3 reps (the same settings the M1 Max case studies used). |

Total: budget **roughly 20-25 minutes** end-to-end on a fresh clone (dominated by the one-time
`llama.cpp` build and the model download); **~15 minutes** on any re-run once both are cached.

If the terminal shows a load-average warning right before the sweep starts, that's neonpilot's
own ambient-load telemetry (feature F-A) doing its job — it just means something else on the
machine is using CPU. Not a failure; just note it if you screenshot the report later (the report
itself records this in its "Measurement conditions" line).

## What to bring back

When it finishes, the script prints the exact paths. Bring back:

1. **The run directory** — printed by the script, something like
   `~/.neonpilot/runs/20260901T120000Z/`. Contains `chip.json`, `result.json`, `report.md`,
   `report.html`, `run.log` — everything needed to verify the numbers.
2. **The preset**, if the tuner found a winner — `presets/<chip-id>/<model-class>.json`, printed
   by the script (e.g. `presets/apple-m5/qwen2.5-3b-instruct-q4_k_m.json`). This is the first
   preset this project will have committed from *any* machine — see the main
   [README's "Idle-machine reference and the first preset"](../README.md#results) section for
   why neither M1 Max case study produced one.
3. **Your screenshot(s)** of the `neonpilot probe` output from step (f) — the ISA features table
   (expect `sme2=true`, `i8mm=true`) and the fast-path activation table (expect SME-tier KleidiAI
   kernels engaging, not the DOTPROD tier the M1 Max reference machine uses). This table is
   itself one of the deliverables — it's the concrete, verifiable proof of the cross-generation
   ISA story this project is built around.

Copy the run directory back to the main machine (e.g. `scp -r`, AirDrop, a USB drive — whatever's
easiest) and drop it under `docs/results/` there, following the same pattern as the two existing
M1 Max case studies (`result.json` + `report.md` + `report.html` + a short `README.md`
explaining the conditions).

## Comparing against the M1 Max case studies

Once you have the M5 run directory (either on the M5 machine itself, if this repo clone also has
the M1 Max evidence checked out, or after copying both onto the same machine), run:

```bash
uv run neonpilot compare <path-to-m5-run-dir> docs/results/m1-max-moderate-load-20260806
```

This writes `compare.md` + a self-contained `compare.html` into the M5 run directory: a
side-by-side chip-feature table (with the i8mm/SME2 delta highlighted), each machine's own
baseline-vs-tuned throughput charts, and a winning-config diff table. This is the artifact that
makes the cross-generation ISA story concrete instead of a claim.

## If something goes wrong

See [`docs/runbook.md`](./runbook.md)'s "Common failures and troubleshooting" table for anything
not covered by `scripts/quickstart.sh`'s own error messages (each failure in the script prints
what went wrong and what to do about it — read the last few lines of output before asking for
help). The short version: `bash scripts/quickstart.sh` is safe to just run again after fixing
whatever it complained about.
