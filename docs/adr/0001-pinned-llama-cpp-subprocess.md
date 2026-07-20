# ADR 0001 — Drive `llama.cpp` via a pinned `llama-bench` subprocess, not in-process bindings

## Context

neonpilot needs to (a) measure real prefill/generation throughput under many candidate runtime
configs, (b) attribute results to an exact, reproducible `llama.cpp` build, and (c) isolate
third-party native code from the Python process. Two integration options were on the table:
shell out to the `llama-bench` CLI tool, or use an in-process Python binding such as
`llama-cpp-python`.

## Decision

Pin `llama.cpp` to a specific commit SHA (`178a6c44937154dc4c4eff0d166f4a044c4fceba`, tag
`b10069`), build only the `llama-bench` target from source
(`scripts/fetch_llama.sh`, CPU-only: `-DGGML_METAL=OFF -DGGML_BLAS=OFF
-DGGML_CPU_KLEIDIAI=ON`), and drive every measurement through `bench/runner.py` spawning that
binary with `-o json`, argv lists, `shell=False`, and a hard timeout. `bench/parser.py` validates
the JSON shape before use. `llama-cli` is deliberately not built — it doesn't even exist as a
target with examples/server off in this pinned commit, and `llama-bench` alone covers every
measurement `optimize` needs.

## Consequences

- **Full fidelity to the pinned binary and exact flag control.** `-o json` is a stable machine
  contract (`build_commit`, `avg_ts`, `stddev_ts`, `samples_ts[]`, etc., confirmed against a real
  capture in `docs/dev/day1-spikes.md` S4), so the parser has a fixed shape to validate against.
- **Reproducibility.** The exact commit SHA is recorded in two places
  (`scripts/fetch_llama.sh`, `neonpilot/_llama_pin.py`) and asserted equal by `tests/test_pin.py`,
  so a preset's provenance can never silently drift from the binary that produced it.
  Content-addressed git fetch (`git fetch --depth 1 <repo> <SHA>`) plus a post-checkout SHA
  assertion means a moved tag or a MITM cannot substitute different code for the same SHA.
- **Isolation.** A crash, hang, or resource-hungry run in the untrusted native binary cannot
  crash the Python process; it is bounded by `timeout_s` and surfaces as
  `TrialResult(status="error")`.
- **Trade-off accepted.** Every measurement pays subprocess spawn + full model load cost per
  invocation (mitigated by `-r reps` running all repetitions inside one call, per
  `docs/dev/build-notes.md` item 1's baseline-argv handling). An in-process binding would avoid
  repeated model loads but would couple neonpilot to a pip wheel's own build flags (which may
  silently enable Metal, may not match the pinned SHA) and would put a crash in that binding
  inside neonpilot's own process.
- **Rejected alternative:** `llama-cpp-python` bindings — harder to pin an exact upstream SHA,
  in-process crash risk, and no guarantee the wheel's build flags match neonpilot's CPU-only,
  KleidiAI-on requirement.
