# Contributing to neonpilot

## Dev setup

```bash
git clone <this-repo-url> neonpilot
cd neonpilot
uv sync --locked --extra dev
bash scripts/fetch_llama.sh   # builds the pinned llama.cpp (tag b10069), needed for
                              # integration tests and any real optimize run
```

## The gate

Before opening a PR, all of the following must pass:

```bash
make lint    # ruff check . && ruff format --check .
make test    # pytest --cov=neonpilot --cov-report=term-missing (80% coverage floor)
```

Optionally, run the gated integration suite (spawns the real pinned `llama-bench` binary against
the real tiny CI model, `SmolLM2-135M-Instruct-Q4_K_M.gguf`):

```bash
NEONPILOT_INTEGRATION=1 uv run pytest -m integration
```

CI (`.github/workflows/ci.yml`) runs `lint`, `test`, and `integration` on `macos-14` for every
push to `main` and every pull request, and must be green before merge.

### Style notes

- Dataclasses in `neonpilot/models.py` are `@dataclass(frozen=True)` — never add a mutable
  field or a method that mutates in place.
- No module outside `cli.py` may import `cli.py` (keeps `probe/`, `bench/`, `search/`, `report/`,
  `preset/` independently testable).
- `bench/runner.py` is the only module allowed to spawn the `llama-bench` subprocess; `probe/`
  adapters take injected text, they never call `subprocess` themselves.
- All subprocess calls use argv lists with `shell=False` and an explicit timeout — never
  `shell=True`, `os.system`, or string-interpolated shell commands. `tests/test_shell_quoting.py`
  greps scripts for unquoted `$VAR` usage.
- If a change deviates from `PLAN.md`'s stated design in a small, non-contract-breaking way,
  record it in `docs/dev/build-notes.md` rather than silently diverging.

## Contributing a preset for a new chip

The preset registry (`presets/<chip-id>/<model-class>.json`) is a community deliverable — anyone
with Arm hardware can contribute a measured, versioned preset without touching Python code.

**Policy: presets must come from an otherwise-idle machine** — run the sweep with nothing else
competing for CPU (no Docker/VMs/heavy background apps), since the report's own
ambient-load/variance caveat (the "statistical caution" note, and a wide prefill stddev) is the
check that a run wasn't contaminated by system load; see
[`docs/results/m1-max-loaded-20260720/`](./docs/results/m1-max-loaded-20260720/) for a worked
example of a real, honestly-labeled run that was correctly *not* packaged as a preset for this
reason.

1. **Set up neonpilot** on the target chip per the [README quickstart](./README.md#setup-instructions)
   (clone, `uv sync --locked --extra dev`, `bash scripts/fetch_llama.sh`, download a model).
2. **Run the sweep:**
   ```bash
   uv run neonpilot probe             # sanity-check the ISA features are what you expect
   uv run neonpilot optimize <model.gguf>   # full-model defaults: --budget 900 --reps 3
   ```
   Use `--reps 3` or higher — this is the documented minimum for a statistically reliable
   result (`PLAN.md` §4.3); the CLI will warn if you go below it.
3. **Generate the report** (for your own records and to attach to the PR):
   ```bash
   uv run neonpilot report
   ```
4. **Package the preset:**
   ```bash
   uv run neonpilot apply --run-dir ~/.neonpilot/runs/latest
   ```
   This writes `presets/<chip-id>/<model-class>.json` (schema-validated on write) and prints the
   `llama-bench` invocation plus `server_flags` for the winning config.
5. **Open a PR** that adds the new `presets/<chip-id>/<model-class>.json` file, with:
   - The generated `report.html` (or `report.md`) attached or linked in the PR description, so
     reviewers can see the full methodology (reps, cooldown, budget, all trials incl. pruned)
     without re-running anything.
   - A short note on the chip (name, core topology, ISA features from `probe --json`) and the
     model used.
   - Confirmation that `--reps >= 3` was used and the run wasn't truncated
     (`budget_truncated=False` in `result.json`), or an explanation if it was.

A malformed or forged preset is rejected at load time by `preset/schema.py::validate` (wrong
`schema_version`, out-of-range/unknown enum values, a `model_file` containing a path separator,
etc.) — so a reviewer only needs to sanity-check the *numbers and methodology*, not defend against
schema-level attacks.

## Reporting security issues

See [`SECURITY.md`](./SECURITY.md) §7 — report privately via GitHub Security Advisories, not a
public issue.
