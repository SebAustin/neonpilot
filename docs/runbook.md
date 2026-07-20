# neonpilot — Runbook

How to run, operate, monitor, and troubleshoot neonpilot. For architecture background see
[`ARCHITECTURE.md`](../ARCHITECTURE.md); for setup see the [README](../README.md#setup-instructions).

## Running

### One-off commands

```bash
uv run neonpilot probe                                    # read-only, <2s
uv run neonpilot optimize <model.gguf> [--budget SECONDS] [--reps N] \
    [--prompt-n N] [--gen-n N] [--out DIR] [--llama-bin PATH] [--cooldown-s SECONDS]
uv run neonpilot report [--run-dir DIR]                    # defaults to ~/.neonpilot/runs/latest
uv run neonpilot apply [PRESET_JSON] [--run-dir DIR] [--presets-root DIR]
```

Every command and subcommand supports `--help`. `neonpilot --version` prints the installed
version.

### Full pipeline

```bash
make benchmark   # fetch-llama + probe today; optimize/report/apply invoked manually until
                  # the Makefile target is extended alongside the M5 real-hardware run
```

or manually, in order: `probe` → `optimize <model>` → `report` → `apply --run-dir <run>`.

### Env var overrides

| Variable | Effect | Default |
|---|---|---|
| `NEONPILOT_LLAMA_BIN` | Override the discovered `llama-bench` binary path | `vendor/llama.cpp/build/bin/llama-bench` (repo-relative) |
| `NEONPILOT_VENDOR` | Override where `scripts/fetch_llama.sh` clones/builds `llama.cpp` | `vendor/llama.cpp` |
| `NEONPILOT_INTEGRATION` | Set to `1` to enable the gated integration test suite | unset (disabled) |

## Operating

### Budgets and timing

- Full-model default: `--budget 900` (15 min), `--reps 3`, `--prompt-n 512`, `--gen-n 128`.
- CI-scale: `--budget 180`, same reps floor recommended.
- Cooldown between candidates auto-selects 3s (cap) for `--budget <= 300`, else 20s, unless
  `--cooldown-s` is passed explicitly. Cooldown is adaptive/idle-skip — it only waits the full
  cap when the CPU isn't already cool (best-effort, no `sudo` required).
- If a run finishes early via pruning, that's expected and healthy — check
  `result.json`'s `trials[].status` for the mix of `ok`/`pruned`/`error`.

### Monitoring a run

- Console output during `optimize` prints the chip name, budget/reps, the winning trial and its
  `gen_ts`, the speedup percentages, a `budget truncated` warning if triggered, and a
  "statistical caution" warning if the tuned result doesn't statistically dominate baseline.
- `run.log` inside the run directory has one structured JSON line per trial (config, t/s, stddev,
  thermal snapshot, status) — tail it during a long run for live progress:
  ```bash
  tail -f ~/.neonpilot/runs/latest/run.log
  ```
- `result.json` is the authoritative machine-readable outcome (`SweepResult`), consumed by
  `report` and `apply`.

### Verifying an environment before a real run

```bash
uv run neonpilot probe --json        # confirm ISA features match expectations for this chip
ls -la vendor/llama.cpp/build/bin/llama-bench   # confirm the pinned binary exists
uv run neonpilot probe                # sanity check before a long optimize run
```

## Common failures and troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `model not found: <path>` (exit 1) | Bad path passed to `optimize` | Check the path; models live under `~/.neonpilot/models/` by convention but any path works. |
| `llama-bench binary not found at ...; run make fetch-llama first.` (exit 1) | `vendor/llama.cpp/build/bin/llama-bench` doesn't exist yet | Run `bash scripts/fetch_llama.sh` (or `make fetch-llama`). Requires `cmake` (`brew install cmake` on macOS). |
| `fetch_llama.sh` aborts with "checked-out commit ... does not match pinned SHA" | Network fetch landed on the wrong ref, or a corrupted `vendor/` checkout | `rm -rf vendor/llama.cpp` and re-run the script — it clones fresh into an empty `vendor/`. |
| `fetch_llama.sh` says the found binary's pin stamp doesn't match | Stale/foreign build at `vendor/llama.cpp/build` (e.g. from a different SHA) | `rm -rf vendor/llama.cpp` and re-run; the script won't silently rebuild over a mismatched binary. |
| `no run directory given and no ~/.neonpilot/runs/latest found.` (exit 1) on `report`/`apply` | `optimize` was never run, or `latest` symlink is missing/broken | Run `optimize` first, or pass `--run-dir` explicitly to `report`/`apply`. |
| `<dir> is missing chip.json/result.json (run neonpilot optimize first).` | Pointed `--run-dir` at an incomplete or wrong directory | Re-run `optimize` to completion, or point at a run directory that has both `chip.json` and `result.json`. |
| `invalid preset: ...` on `apply <preset.json>` | Preset fails `schema_version`/type/enum/range validation (SECURITY.md F1) | Check the printed reason — it's a specific, human-readable rejection (wrong `schema_version`, bad `flash_attn` value, `model_file` with a path separator, etc.). Fix the preset JSON or regenerate it via `apply --run-dir`. |
| `refusing to save preset: ...` on `apply --run-dir` | Forged/unsafe `chip_id` or `model_class` in the run's `chip.json`/`result.json` (path-traversal guard, SECURITY.md F2) | Only trust run directories you generated yourself or that came from a trusted source; do not import arbitrary shared run dirs without review. |
| `optimize`/report shows `budget_truncated=True` | The projected remaining cost of the sweep exceeded `--budget` | Expected under a tight budget (e.g. CI's 180s); check `dropped_stages` to see what was cut (only ever "adaptive extras"/"C"/"confirm", never A/B). Increase `--budget` for a fuller sweep if needed. |
| Console prints "warning: speedup may not be statistically significant" | Tuned result doesn't statistically dominate the baseline (`bench.stats.dominates` fails) | This is the credibility guard working as intended (see `docs/dev/build-notes.md` item 15) — treat the headline speedup number with caution; consider re-running with `--reps` >= 3 on an otherwise-idle machine. |
| Console prints "warning: --reps=N is below the recommended minimum of 3" | `--reps` was set below 3 | Informational; re-run with `--reps 3` or higher for a more reliable result, especially before recording numbers for the report. |
| Wildly inconsistent generation t/s between runs on the same config | Thermal throttling or background CPU contention on the host (observed on a shared dev laptop, see `docs/dev/build-notes.md` item 15) | Run on an otherwise-idle machine; use `--reps 3` or higher; treat the "statistical caution" warning as a signal to re-run rather than ignore. |
| Gated integration test fails/skips | `NEONPILOT_INTEGRATION` not set, or the pinned binary/tiny model aren't present | Set `NEONPILOT_INTEGRATION=1`, ensure `scripts/fetch_llama.sh` has run and the tiny model (`SmolLM2-135M-Instruct-Q4_K_M.gguf`) is downloaded to `~/.neonpilot/models/`. |
| CI job times out | Cold `llama.cpp` build (~6-9 min) plus a hung `llama-bench` | Each CI job has an explicit `timeout-minutes` cap (`lint: 10`, `test: 20`, `integration: 25`) so a hang is reaped rather than burning the Actions default; a cache miss on the `llama-bench` build is a slowdown, not a failure. |
| `ruff check`/`ruff format --check` fails in `make lint` | Formatting/lint drift | Run `make format` to auto-fix, then re-run `make lint`. |
| `pytest --cov` fails below 80% | Coverage floor enforced in `pyproject.toml` (`fail_under = 80`) | Add tests for the newly-uncovered lines; the floor applies to the `neonpilot` package (`vendor/` excluded). |

## Observability reference

- **`run.log`** — one JSON line per trial (baseline + every candidate incl. pruned/errored):
  `trial_id`, `stage`, `status`, `config`, `gen_ts`, `gen_stddev_ts`, `prefill_ts`, `thermal`,
  `error`.
- **`result.json`** — the full `SweepResult`: baseline, all trials, best, both speedup
  percentages, elapsed time, `budget_truncated`, `dropped_stages`.
- **`chip.json`** — the `ChipReport` snapshot used for this run (probe result, ISA dict,
  fast-path notes) — this is what a report/preset's provenance is built from.
- **`plan.json`** — the `SearchPlan` (candidate sets per stage) actually used.
- Failures from the `llama-bench` subprocess surface the exact argv and captured stderr in the
  `TrialResult.error` field for reproduction — copy the argv and run it directly to debug further.
