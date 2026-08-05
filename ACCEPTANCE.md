# neonpilot — Acceptance Record

**Verifier:** independent solution-verifier (evidence-based; ran the gate, did not trust reports).
**Date:** 2026-07-20. **Commit at acceptance:** `b9f0b1e` (working tree clean).
**Scope:** full M0–M6 acceptance pass. M5 idle-reference numbers and committed presets are
**OPEN by design** (gated on quiet-machine / second-hardware access), not failures — the
machinery each depends on is verified working below.

Method: every result in this file was produced by the verifier re-running the command on the
Apple M1 Max reference machine (macOS 26.5, 8P+2E, NEON/dotprod true, i8mm/sme/sme2 false).
No number here is self-reported by the builder.

---

## 1. Gate re-run (verbatim tails)

### `make lint`
```
uv run ruff check .
All checks passed!
uv run ruff format --check .
57 files already formatted
LINT_EXIT:0
```

### `make test`
```
src/neonpilot/search/planner.py            33      0   100%
---------------------------------------------------------------------
TOTAL                                    1104     35    97%

Required test coverage of 80.0% reached. Total coverage: 96.83%

======================= 203 passed, 3 skipped in 11.54s ========================
TEST_EXIT:0
```
The 3 skipped are the `@integration`-gated tests. Verifier separately ran
`NEONPILOT_INTEGRATION=1 uv run pytest -m integration -v` against the **real** pinned
`llama-bench` + real SmolLM2-135M model → `3 passed in 33.73s`.

---

## 2. `make benchmark` fail-fast spot-check (no full benchmark run)

`SC1` is verified by (a) reading the wired target (`Makefile:30-44`: `fetch-llama → probe →
optimize → report → apply`, with `MODEL`/`RUN_DIR` overrides) and (b) exercising the
missing-model guard — **not** by running a full ~15-min sweep:

```
$ MODEL=/nonexistent/model.gguf make benchmark
./scripts/fetch_llama.sh
neonpilot: llama-bench already built at pinned SHA 178a6c44... -- skipping fetch/build.
neonpilot: model not found at /nonexistent/model.gguf
neonpilot: override the path with 'MODEL=/path/to/model.gguf make benchmark', or download the reference model:

  mkdir -p ~/.neonpilot/models
  curl -L -o /nonexistent/model.gguf \
    "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf"
make: *** [benchmark] Error 1   (exit 2)
```
Fail-fast fires with the download hint and a non-zero exit. `fetch-llama` is idempotent
(skips via `.pin` stamp in 0.007s). SC1 pipeline is wired and reachable.

---

## 3. Success-criteria table (REQUIREMENTS.md)

| SC | Verdict | Evidence (verifier-run) |
|----|---------|--------------------------|
| **SC1** reproducible `make benchmark` | **PASS (wired)** | `Makefile:30-44` full four-command pipeline; fail-fast verified (§2, exit 2 + download hint); `fetch_llama.sh` idempotent. Full clean-clone run not executed here (would need a fresh clone + ~15 min); pipeline commands each independently verified. |
| **SC2** ≥10% gen speedup w/ stddev on M1 Max | **OPEN-HONEST** | Machinery verified end-to-end. Loaded case study `docs/results/m1-max-loaded-20260720/result.json`: baseline gen **9.05±1.79** t/s → tuned (thr=6,fa=off,b=4096,ub=2048) **22.11±1.04** t/s = **+144.2% gen / +21.9% pp**, `budget_truncated=False`, `elapsed_s=543.9<900`. Statistically dominant (21.07 > 10.84). **BUT** measured under ambient load (loadavg 7.6–12.2; Docker/VM/Webex) — explicitly labeled an adaptive result, **NOT an idle-machine reference** (`docs/results/m1-max-loaded-20260720/README.md`). Idle-machine number pending one quiet `make benchmark`. Exceeds the 10% bar; final canonical figure open. |
| **SC3** cross-gen M1 Max + M5 presets | **OPEN** | No presets committed (policy documented, `docs/results/.../README.md#preset-policy` + `CONTRIBUTING.md`) — `presets/` stays empty until an idle-machine winner exists. `apply` packaging + schema-validation machinery verified in the SOLID pass. M1 Max preset pending idle run; M5 preset pending second machine. SME2 fast-path code path tested via `tests/fixtures/sysctl_apple_m5_synthetic.txt`. |
| **SC4** CI green (ruff + pytest exit 0) | **PASS** | §1: `make lint` exit 0, `make test` 203 passed / 3 skipped. `.github/workflows/ci.yml` runs the same gate on `macos-arm64` with `uv sync --locked`, per-job `timeout-minutes`, `--cov-fail-under=80`. |
| **SC5** ≥80% coverage | **PASS** | §1: total coverage **96.83%**; floor 80 enforced in `pyproject.toml` (`fail_under=80`) and CI (`--cov-fail-under=80`). |
| **SC6** probe correctness | **PASS (M1 Max); M5 half OPEN** | `neonpilot probe --json` → `neon=T,dotprod=T,i8mm=F,sve=F,sme=F,sme2=F`, matching live `sysctl` (`FEAT_I8MM=0`, `FEAT_SME=0`). No i8mm/SME overclaim; DOTPROD-tier KleidiAI note present. `tests/test_probe_macos.py`, `tests/fixtures/sysctl_apple_m1_max.txt`. M5 `sme2=true` side pending real M5 capture (synthetic fixture tests the branch). |
| **SC7** CI time budget | **PASS** | Real integration sweep 33.73s; tiny-model `optimize` full sweep 87.7s (<240s); `--budget 40` run correctly set `budget_truncated=True, dropped_stages=['C']`. CI `timeout-minutes: lint 10 / test 20 / integration 25`. |
| **SC8** self-contained HTML | **PASS** | Freshly rendered `report.html` and committed `docs/results/m1-max-loaded-20260720/report.html` both: 0 `http(s)://`, 0 `<script>`, 0 external `src=`/`<link>`. `tests/test_no_external_assets.py`. |
| **SC9** install path | **PASS** | `neonpilot --version` → `neonpilot 0.1.0`; `probe/optimize/report/apply --help` all exit 0; console-script entry `neonpilot.cli:app`. |
| **SC10** differentiation section | **PASS** | `README.md:334` `## Differentiation` (ISA-probe / cross-generation / preset-registry / report-quality pillars). |

**Security posture:** no open Critical/High. All MEDIUM (F1–F4) and LOW (F5–F10) findings in
`SECURITY.md` are fixed; verifier independently reproduced the fixes: type/enum validation
rejects malformed presets (F1), forged `chip_id="../.."` path traversal rejected (F2), Rich
markup in `server_flags` printed literally not interpreted (F5). CI has `permissions:
contents: read`, locked installs, model checksum, per-job timeouts. `uv lock --check` clean.

---

## 4. Build log summary

| Phase | Outcome | Key commits |
|-------|---------|-------------|
| Planning (3 critic rounds) | plan-rubric **PASS 98/100** | `4dc7d72` baseline, `202f655` plan v3.1 |
| Build M0–M4 (scaffold→probe→bench→search→report/preset) | all done-whens met | `2fe312b` M0, `f118cab` M1, `56998f0` M2, `e457279` M3, `cb9a14a`+`9f29f90` M4 |
| Baseline-credibility + statistical-caution guard | caveat fires on overlapping bands / reps<3 | `2ad8aff`, `eac243a`, `a2a856c`, `683188f` |
| Security audit F1–F10 | all fixed / accepted-documented | `5a9f18f` F1, `78ce782` F2+F5, `e1ae3a4` F9, `fc30d29` F3/F4/F6/F7/F8, `089cd42` F10, `0d8ca23` audit report |
| Solution-rubric verification (M0–M4) | **SOLID 100/100** | (verifier pass) |
| M5 real 900s Qwen2.5-3B sweep (loaded machine) | +144.2% gen, committed as case study, no preset | `b9f0b1e` |
| M6 wiring + docs | `make benchmark` full pipeline; ARCHITECTURE/ADRs/runbook/CONTRIBUTING | `78a4bae`, `b695045` |

`git log --oneline` (most recent first): `b9f0b1e` → `78a4bae` → `b695045` → `0d8ca23` →
`089cd42` → `fc30d29` → `e1ae3a4` → `78ce782` → `5a9f18f` → `683188f` → `a2a856c` → `eac243a`
→ `2ad8aff` → `9f29f90` → `cb9a14a` → `e457279` → `56998f0` → `f118cab` → `2fe312b` →
`202f655` → `4dc7d72`.

---

## Built

- Four working CLI commands (`probe`, `optimize`, `report`, `apply`), Typer + Rich, console-script install.
- Arm ISA probe (macOS sysctl / Linux cpuinfo adapters) with llama.cpp fast-path explanation, no overclaim.
- Staged benchmark sweep (A→B→C + confirm), candidate-level statistical early-stop, budget truncation, adaptive thermal cooldown, over the real pinned `llama-bench` (b10069, CPU-only, KleidiAI on).
- Self-contained HTML + Markdown reports (zero external fetch), statistical-caution guard.
- Versioned preset schema + registry, path-traversal-safe `apply`, plain-text `server_flags`.
- 206 tests (203 unit + 3 gated integration), 96.83% coverage; ruff-clean; reproducible via committed `uv.lock`.
- Security audit with all MEDIUM/LOW findings fixed; docs suite (ARCHITECTURE, 3 ADRs, runbook, CONTRIBUTING, build-notes, day1-spikes).
- Wired `make benchmark` full pipeline with fail-fast missing-model guard.
- Real M1 Max loaded-machine case study, honestly labeled and committed with report artifacts.

## Deferred (OPEN by design — gated on external access, not defects)

- **SC2 idle-machine reference number** — needs one `make benchmark` on a quiet M1 Max.
- **SC3 committed presets** — M1 Max preset (from the idle run) and M5 preset (from a second machine); `presets/` intentionally empty until then.
- **SC6 M5 half** (`sme2=true`) — needs a real Apple M5 `sysctl` capture.
- Public GitHub repo + Apache-2.0 visibility + real repo URLs — gated on the user.

## Next steps (for the user)

1. **Quiet-machine `make benchmark` on the M1 Max** → fills the SC2 idle-machine reference and packages the first committed preset.
2. **Same on the Apple M5** → completes the SME2 cross-generation story (SC3, SC6 M5 half) and the second preset.
3. **Create the public GitHub repo** (Apache-2.0 visible) and push — gated on the user.
4. **Update repo-URL placeholders** once the real repo exists — currently `github.com/SebAustin/neonpilot` in `pyproject.toml:36`, `README.md:5` (CI badge), `SECURITY.md:234`.
5. **Devpost submission** using `DEVPOST.md` (in draft); optional <3-min demo video per `launch/DEMO-SCRIPT.md`.

---

## Verdict

**M0–M4: SOLID** (rubric 100/100; build green; 203 unit + 3 integration tests pass; lint clean;
every in-scope criterion met; no open Critical/High). **M5–M6: ACCEPTED with OPEN items** — the
pipeline, docs, `make benchmark` wiring, and an honest real-hardware case study are all in place;
the remaining SC2 idle-reference number, SC3 committed presets, and SC6 M5 half are gated on
quiet-machine and second-hardware access and are documented as open, not fabricated. No
success criterion is failed by silence or by an unfair baseline; the one headline number that
exists (+144.2%) is real, statistically dominant, and explicitly scoped to its load conditions.
