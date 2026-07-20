# neonpilot

Probe an Arm CPU, explain which llama.cpp Arm fast paths activate, and auto-tune llama.cpp
runtime flags via a staged, thermally guarded benchmark sweep -- CPU-only, Apple Silicon
authoritative, Linux/Graviton "designed to work, untested".

Status: milestones M0-M2 (scaffold, probe, bench harness) implemented. See
[`PLAN.md`](./PLAN.md) section 6 for the full milestone roadmap (`optimize`/`report`/`apply`
land in M3-M4).

## Setup

Requires Python 3.11+, [`uv`](https://docs.astral.sh/uv/), and `cmake` (`brew install cmake`
on macOS).

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e ".[dev]"
```

## Usage

```bash
uv run neonpilot --help
uv run neonpilot probe            # Rich table: chip, topology, ISA features, fast paths
uv run neonpilot probe --json     # machine-readable ChipReport
```

`optimize`, `report`, and `apply` are scaffolded (exit non-zero with a "not implemented yet"
message) pending milestones M3/M4.

## Development

```bash
make lint      # ruff check + ruff format --check
make format    # ruff format + ruff check --fix
make test      # pytest with coverage
make fetch-llama   # build the pinned llama.cpp (idempotent; see scripts/fetch_llama.sh)
```

Gated integration tests (real llama-bench + tiny model) run with:

```bash
NEONPILOT_INTEGRATION=1 uv run pytest -m integration
```

## Differentiation

See `PLAN.md` section 5 and `ASSUMPTIONS.md` #12 for the full rationale: ISA-probe depth
(exact KleidiAI kernel-tier explanation, not just "NEON present"), a cross-generation Apple
Silicon story (M1 Max vs. M5), a reusable versioned preset registry, and a self-contained
zero-dependency HTML report -- differentiators against generic Arm64 auto-tune entries.

## License

Apache-2.0. See [`LICENSE`](./LICENSE).
