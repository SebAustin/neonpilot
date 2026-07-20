# neonpilot Security Audit & Threat Model

**Scope:** `neonpilot` v0.1.0 — a local developer CLI (Typer) that probes Arm CPUs, shells out
to a vendored, pinned `llama-bench` binary, parses its JSON, writes run artifacts under
`~/.neonpilot/runs/`, renders Markdown/HTML reports, and loads/validates community-shared preset
JSON files.

**What this tool is NOT:** no network service, no listening ports, no authentication, no user
accounts, no runtime network calls, no secrets, no telemetry. Severities below are calibrated to
that reality — this is a single-user local CLI, not a server. The genuinely elevated surfaces are
(a) **untrusted community-shared preset JSON / run directories** ("apply this preset" is the
intended workflow) and (b) the **build/CI supply chain**. Those get the real scrutiny.

Audit date: 2026-07-20. Method: STRIDE decomposition + manual code review + non-destructive
static scans (secret scan, dangerous-pattern grep, dependency inspection). No code was modified —
remediation is deferred to the builder per task scope.

---

## 1. System decomposition

### Trust boundaries

| # | Boundary | Untrusted side | Trusted side |
|---|----------|----------------|--------------|
| TB1 | Preset JSON / shared run dirs | Third-party preset files, shared `chip.json`/`result.json` | neonpilot process |
| TB2 | `llama-bench` subprocess | The binary's stdout/stderr, and the GGUF it loads | neonpilot parser |
| TB3 | Host introspection | `sysctl -a`, `/proc/cpuinfo`, `getauxval` output | probe parsers |
| TB4 | Report consumer | The rendered HTML opened in a browser / Markdown in a viewer | report renderer |
| TB5 | Build/CI supply chain | GitHub upstream (llama.cpp), Actions cache, HF model download | committed source |

### Entry points

- CLI commands: `probe`, `optimize <model.gguf>`, `report`, `apply <preset.json | --run-dir>`.
- Env overrides: `NEONPILOT_LLAMA_BIN`, `NEONPILOT_VENDOR`, `NEONPILOT_INTEGRATION`.
- File inputs: preset JSON (`apply`), run artifacts `chip.json`/`result.json` (`report`, `apply --run-dir`),
  the GGUF model path (`optimize`).
- Build entry point: `scripts/fetch_llama.sh` (clone + cmake build of pinned llama.cpp).

### Data stores

- `~/.neonpilot/runs/<timestamp>/` — `chip.json`, `plan.json`, `trials.json`, `result.json`,
  `run.log`, `report.md`, `report.html`, plus a `latest` symlink.
- `presets/<chip-id>/<model-class>.json` — the in-tree preset registry.
- `vendor/llama.cpp/build/bin/llama-bench` — compiled binary.

### Sensitive data

None. No credentials, tokens, PII, or secrets are handled, stored, or transmitted. Confirmed by
secret scan (clean) and `.env.example` (documents only non-secret path/flag overrides).

---

## 2. STRIDE threat model

### Spoofing
Low relevance — no auth, no identity, no sessions. The only identity-ish claim is preset
*provenance* (`chip`, `llama_cpp_commit`, `generated_at` fields inside a preset). A malicious
preset can forge these freely; they are self-attested and must be treated as untrusted display
data, never as a trust signal. **Mitigation in place:** neonpilot never executes a loaded preset,
so forged provenance yields only misleading text, not code execution.

### Tampering
- **Preset JSON (TB1):** the community workflow is "download and `apply` someone's preset." A
  tampered preset can carry arbitrary values in every field. Mitigations: `apply` only *prints*
  the re-emitted invocation (never runs it), and `preset/io.py::invocation` wraps every argv token
  in `shlex.quote`, neutralizing shell metacharacters and argument-splitting in the copy-paste
  string. **Gaps (fixed, see section 4):** scalar preset fields are not type/enum-validated (F1),
  and packaging a shared *run directory* into a preset can traverse paths via forged
  `chip_id`/`model_class` (F2).
- **Run artifacts (TB1/TB4):** `report` re-hydrates `result.json`/`chip.json` and renders HTML.
  String fields are `html.escape`d, but numeric/bool fields were interpolated raw and hydration
  did not enforce their type (F1/F9, fixed, see section 4).
- **Build cache (TB5):** a poisoned Actions cache could ship a tampered `llama-bench` (F4, fixed,
  see section 4).

### Repudiation
Minimal. `run.log` records structured per-trial JSON locally; adequate for a single-user tool. No
audit/tamper-evidence requirement for a local CLI.

### Information disclosure
Very low. No secrets exist to leak. Reports embed only host chip info and benchmark numbers the
user already owns. HTML report is self-contained with zero external fetches (verified in
`report/html.py`: inlined CSS, hand-rolled inline SVG, no `<script>`, no CDN) — so opening a report
leaks nothing to the network. Error messages surface local paths only (acceptable for a local CLI).

### Denial of service
- A crafted GGUF or huge `--prompt-n/--gen-n` can make `llama-bench` consume large CPU/RAM. Bounded
  by a hard per-invocation `timeout_s` (default 120s) but **not** by memory/CPU rlimits (F10,
  accepted and documented in-code, see section 4 -- disproportionate for a local, no-privilege-
  boundary tool).
- `sysctl -a` and the subprocess both carry timeouts. Self-inflicted DoS only; not a security
  priority for a local tool.

### Elevation of privilege
No privilege boundary is crossed — no setuid, no sudo, no daemon, runs entirely as the invoking
user. The subprocess boundary (TB2) is the main EoP-adjacent surface: **well-controlled** — argv
lists only, `shell=False`, hard timeout, stdout validated by `bench/parser.py` before use
(`bench/runner.py:70-88`). The realistic EoP path is the build/CI chain (F3, F4, both fixed, see
section 4).

---

## 3. Attack-surface deep dives (per task focus)

### (a) Untrusted preset JSON — injection into the re-emitted command line
**Assessment: largely mitigated, with a validation gap.** `invocation()` (`preset/io.py:39-67`)
builds an argv list and joins `shlex.quote(part)` for every element, including `model_file`,
`cache_type_k/v`, and `flash_attn`. `shlex.quote` prevents both shell-metacharacter injection
(`; rm -rf`, `$(...)`, backticks) **and** argument-splitting (a value like `on -extra-flag` becomes
one quoted token). The invocation is printed, never executed by neonpilot. **Residual risks
(fixed, see section 4):** F1 (scalar fields un-validated, so e.g. `flash_attn` was not
constrained to `on/off/auto`), and F2 (path traversal when packaging a shared run dir). Path
traversal via a preset's `model_file` is only realized if the user copy-pastes and runs the
printed command against an attacker-named path — low, and outside neonpilot's execution; F1's
`model_file` bare-filename check now also closes this at validation time.

### (b) HTML report XSS — is escaping applied?
**Yes.** `report/html.py` applies `html.escape` to every string field that reaches the DOM:
chip name, model class/file, llama.cpp commit, schema version, ISA feature names, fast-path
`feature`/`kernel`/`why`, and per-trial `trial_id`/`stage`/`status`/`cache_type_k`/`flash_attn`,
plus chart titles/labels. Numeric values use `:.2f`/`:+.1f` formatting. **Residual (F9, fixed,
see section 4):** a few numeric/bool fields (`config.threads`, ISA `present`, fast-path `active`)
were interpolated without escaping, relying on their declared type — but hydration (F1, also
fixed) did not enforce type, so a *tampered local run artifact* could have smuggled markup
through an `int`-typed field. This required local artifact tampering (or importing a shared run
dir), so it was LOW, but real and rooted in F1; both are now closed.

### (c) The fetch script — pin verification, protocol, MITM/tag-move resistance
**Strong.** `scripts/fetch_llama.sh` uses HTTPS (`https://github.com/ggml-org/llama.cpp`) and pins
by **full 40-char commit SHA** (`178a6c...fceba`), fetching that exact object
(`git fetch --depth 1 <repo> <SHA>` then `checkout FETCH_HEAD`). Because git objects are
content-addressed, a moved tag or a MITM cannot substitute different code for the same SHA — git
rejects any object whose hash doesn't match (modulo the theoretical SHA-1 collision weakness). The
pin is single-sourced in `_llama_pin.py` and asserted equal by `tests/test_pin.py`. **Gap (F8,
fixed, see section 4):** on the fresh-build path the script did not assert
`git rev-parse HEAD == LLAMA_CPP_SHA` after checkout (the SHA check only guarded the idempotent
rebuild path) -- it now does, on both paths.

### (d) Subprocess boundary — argv injection, timeouts, resource limits
**Well-controlled.** `bench/runner.py` and `probe/collector.py` both use fixed argv lists,
`shell=False`, `capture_output=True`, and explicit `timeout=`. No user string is ever concatenated
into a shell command anywhere in the codebase (grep for `shell=True`/`os.system`/`eval`/`exec` is
clean). **Gap (F10, accepted/documented, see section 4):** no memory/CPU rlimit on the child, so a
hostile GGUF can drive resource exhaustion up to the timeout -- deliberately not implemented for a
local, no-privilege-boundary tool; rationale is now an inline comment at the call site.

### (e) GGUF model files as untrusted input to llama-bench
**Inherited llama.cpp risk, documented.** neonpilot passes a user-supplied GGUF path straight to
`llama-bench`. GGUF parsing happens entirely inside the pinned third-party binary; any parser
vulnerability there is an inherited llama.cpp risk, not a neonpilot defect. **Mitigation:** the
binary is pinned to an audited SHA and rebuilt from source; models are user-sourced (neonpilot
downloads nothing at runtime). Users should only benchmark GGUFs they trust.

### (f) CI workflow — cache poisoning, pull_request permissions
- **Trigger safety: good.** Uses `pull_request` (not `pull_request_target`), so forked-PR code runs
  with a read-only token and no repo secrets exposed.
- **F3 (MEDIUM, fixed):** a `uv.lock` is committed; CI now installs via `uv sync --locked --extra
  dev` in all three jobs (was `uv pip install --system -e ".[dev]"`, which re-resolved from the
  pyproject version *ranges* and ignored the lockfile).
- **F4 (MEDIUM, fixed):** `actions/cache@v4` still stores the compiled `llama-bench` build, but
  `fetch_llama.sh` now verifies a `.pin` stamp file (written next to the binary, inside the cached
  `build/` dir) before trusting a cache hit, rebuilding on any mismatch or missing stamp.
- **F6 (LOW, fixed):** a top-level `permissions: contents: read` block is now present.
- **F7 (LOW, fixed):** the tiny test model download is now followed by a pinned sha256 checksum
  verification (`shasum -a 256 -c -`), failing the job on mismatch.

---

## 4. Findings

| ID | Severity | Location | Finding | Remediation | Status |
|----|----------|----------|---------|-------------|--------|
| F1 | MEDIUM | `src/neonpilot/_hydrate.py:41-57`, `src/neonpilot/preset/schema.py:36-43` | `from_dict` performs **no scalar type/enum validation or coercion** (only field presence + nested-dataclass shape). `validate()`'s docstring claims it rejects "a field of the wrong shape," but a preset can carry arbitrary strings in `threads`/`batch` (declared `int`) and unconstrained values in `flash_attn`/`cache_type_k/v`. | Enforce scalar types and allow-lists in `validate()`: `flash_attn ∈ {on,off,auto}`, `cache_type_* ∈` known set, `threads/batch/ubatch/reps` are non-negative ints in a sane range, `model_file` is a bare filename (no `/`, no `..`). Coerce or reject on mismatch. | **Fixed in `5a9f18f`.** `_hydrate._convert` strictly validates every scalar leaf (bool checked before int, since `bool` subclasses `int`); `preset/schema.validate` enforces `flash_attn`/`cache_type_k/v` allow-lists, positive-int ranges, and a bare-filename `model_file`. Tests: `tests/test_hydrate.py`, `tests/test_preset_schema.py`. |
| F2 | MEDIUM | `src/neonpilot/preset/io.py:20-24` (`save`) via `src/neonpilot/cli.py:334-336` | Packaging a **shared run directory** (`apply --run-dir <shared>`) builds `chip_id`/`model_class` from untrusted `chip.json`/`result.json`, then writes `root / chip_id / f"{model_class}.json"`. A forged `chip_id="../../etc"` (or `model_class` with separators) escapes `presets_root` (path traversal / arbitrary-location file write). | Slug-sanitize `chip_id` and `model_class` to `[a-z0-9._-]` and reject any value containing a path separator or `..` before joining. Resolve the final path and assert it stays under `presets_root`. | **Fixed in `78ce782`.** `preset/io._sanitize_slug` + `_resolved_under` gate both `save()` and `load()`; `cli.apply` catches the new `UnsafePresetPathError` and exits cleanly. Tests: `tests/test_preset_io.py`, `tests/test_cli.py::test_apply_rejects_forged_chip_id_path_traversal`. |
| F3 | MEDIUM | `.github/workflows/ci.yml:17,31,43` | Committed `uv.lock` is not enforced — CI uses `uv pip install -e ".[dev]"` which re-resolves version ranges, defeating reproducibility and lockfile-based supply-chain control. | Install from the lockfile: `uv sync --frozen` (or `uv pip install --require-hashes` against a compiled requirements file). Fail CI if the lock is stale. | **Fixed in `fc30d29`.** All three jobs install via `uv sync --locked --extra dev`; verified locally (`uv sync --locked --extra dev` + `uv run pytest`/`ruff` succeed against the committed lock). |
| F4 | MEDIUM | `.github/workflows/ci.yml:46-50` | Actions cache stores the compiled `llama-bench` binary with no integrity verification; a poisoned cache (writable from PR branches) could inject a tampered binary into later runs. | Prefer rebuilding from the pinned SHA over caching the binary, or add a content hash to the cache key and verify a known checksum of the restored binary before use. Restrict cache scope. | **Fixed in `fc30d29`.** `scripts/fetch_llama.sh` writes/checks a `.pin` stamp file next to the binary (inside the cached `build/` dir, since `.git` isn't cached); a missing or mismatched stamp triggers a full rebuild instead of trusting the cached binary. |
| F5 | LOW | `src/neonpilot/cli.py:327,330-331,339` | Untrusted preset fields (`server_flags`, and `invocation()` output containing preset values, plus validation-error `exc` text) are printed via `console.print(...)` with **Rich markup enabled**, allowing markup/hyperlink injection (`[link=...]`, color spoofing) into terminal output. | Print untrusted content with `markup=False` or wrap in `rich.markup.escape(...)`. | **Fixed in `78ce782`.** `_print_preset_summary` prints with `markup=False`; the validation-error path uses `rich.markup.escape`. Test: `tests/test_cli.py::test_apply_existing_preset_prints_server_flags_without_markup_injection`. |
| F6 | LOW | `.github/workflows/ci.yml:1-7` | No explicit `permissions:` block; workflow inherits default `GITHUB_TOKEN` scope. | Add top-level `permissions: contents: read` (least privilege); elevate per-job only if needed. | **Fixed in `fc30d29`.** Top-level `permissions: contents: read` added. |
| F7 | LOW | `.github/workflows/ci.yml:58-64` | Test model fetched via `curl -L` from Hugging Face with no checksum verification. | Pin an expected SHA-256 and verify after download; fail on mismatch. | **Fixed in `fc30d29`.** Pinned `sha256=ed5fa30c...` (computed locally via `shasum -a 256` against the cached model), verified post-download with `shasum -a 256 -c -`. |
| F8 | LOW | `scripts/fetch_llama.sh:37-38` | Fresh-build path does not assert `git rev-parse HEAD == LLAMA_CPP_SHA` after `checkout FETCH_HEAD` (the SHA guard only protects the idempotent-rebuild path). | Add a post-checkout `test "$(git -C "$VENDOR" rev-parse HEAD)" = "$LLAMA_CPP_SHA"` and abort on mismatch. | **Fixed in `fc30d29`.** Post-checkout assertion added; aborts with a clear message on mismatch. |
| F9 | LOW | `src/neonpilot/report/html.py:81-84,109,142` | Numeric/bool fields (`config.threads`, ISA `present`, fast-path `active`) are interpolated into HTML without `html.escape`, relying on a declared type that hydration (F1) does not enforce — a tampered/imported run artifact could inject markup through an `int` field. | Fix F1 (enforce types on hydration); as defense-in-depth, coerce these to `int(...)`/`bool(...)` or `html.escape(str(...))` at render time. | **Fixed in `e1ae3a4`** (on top of the F1 fix in `5a9f18f`). A `_esc()` helper (`html.escape(str(value))`) now wraps every interpolation, string and numeric/bool alike. Golden fixture unchanged (no-op for values without HTML metacharacters). Test: `tests/test_report_html.py::test_render_html_escapes_numeric_and_bool_fields`. |
| F10 | LOW | `src/neonpilot/bench/runner.py:71-83` | `llama-bench` child has a hard timeout but no memory/CPU rlimit; a hostile GGUF can drive resource exhaustion until timeout. | Optionally apply `resource.setrlimit(RLIMIT_AS/RLIMIT_CPU)` via `preexec_fn`, or document the bound. Low priority for a local tool. | **Accepted, documented in `089cd42`.** No rlimit applied (disproportionate for a LOW, local-only, no-privilege-boundary finding); the decision and rationale are now an inline comment at the `subprocess.run` call site, cross-referencing this finding. |
| F11 | INFO | `src/neonpilot/bench/runner.py` (design) | GGUF files are untrusted input parsed inside the third-party `llama-bench`; any GGUF-parsing vuln is an inherited llama.cpp risk. | Mitigated by SHA pin + user-sourced models. Document that users should benchmark only trusted GGUFs. | Accepted (INFO, already documented here and in `runner.py`'s module docstring). No code change required. |
| F12 | INFO | `src/neonpilot/artifacts.py:42-50`, `cli.py:216-222` | `report`/`apply` follow the `~/.neonpilot/runs/latest` symlink; a locally planted symlink could redirect reads. | Local-only, user-owned dir; acceptable. Optionally resolve and validate the target stays under the runs root. | Accepted (INFO). Out of scope for this pass; local-only threat model makes this a non-priority hardening item. |
| F13 | INFO | `scripts/fetch_llama.sh:41-52` | Building from source runs upstream CMake/build scripts with user privileges. | Inherent to source builds; bounded by the SHA pin. | Accepted (INFO). Inherent to the "build from pinned source" design; no further action. |

**No CRITICAL or HIGH findings.** All MEDIUM findings (F1-F4) and all LOW findings (F5-F10) are fixed as of the commits above; INFO items (F11-F13) are accepted/documented, not code defects.

### Positive controls confirmed
- `invocation()` shell-quotes every argv token (`preset/io.py:67`) — argv/shell injection into the
  re-emitted command line is neutralized; covered by `tests/test_shell_quoting.py`.
- `report/html.py` applies `html.escape` to all string interpolations and ships a zero-external-fetch,
  script-free HTML report — XSS surface is small and the report leaks nothing to the network.
- All subprocess calls use argv lists with `shell=False` and hard timeouts (`bench/runner.py`,
  `probe/collector.py`). Scan for `shell=True`/`os.system`/`eval`/`exec`/`pickle` is clean.
- Build pin is a full commit SHA over HTTPS, content-addressed and test-asserted — resistant to
  tag-moving and MITM code substitution.
- No secrets anywhere (secret scan clean); no runtime network calls; runs unprivileged.

---

## 5. Dependency review

- **Runtime deps (verified in `pyproject.toml`):** `typer>=0.12,<1.0` and `rich>=13.7,<14.0` only.
  Transitively (per `uv.lock`): `click`/`shellingham`/`annotated-doc` (via typer),
  `markdown-it-py`/`mdurl`/`pygments`/`colorama` (via rich). All mainstream, well-maintained.
- **Supply-chain posture:** a `uv.lock` **is** committed and, as of F3's fix (`fc30d29`), **is now
  enforced in CI** via `uv sync --locked --extra dev` — the committed lock is the single source of
  truth for CI installs. Recommendation for future hardening: enable Dependabot / periodic
  `uv lock --check` drift checks in a scheduled workflow. No pinned-hash install today (not
  required for two mainstream, actively-maintained direct dependencies).
- No known-vulnerable dependency was identified in the direct set; the residual risk was drift due
  to unenforced ranges, closed by F3.

---

## 6. Remediation status

All findings from this audit are now fixed or explicitly accepted-and-documented; see the
**Status** column in section 4 for the exact commit per finding. Order applied: **F1 → F2** (both
harden the untrusted-preset / shared-run-dir workflow; F1 also closes the type-safety half of F9),
then **F9** (the remaining defense-in-depth escaping half), then **F3/F4/F6/F7/F8** (CI/build
supply chain), then **F5** (CLI markup escaping) and **F10** (documented, not code-changed).
Verified with the full gate (`ruff check`, `ruff format --check`, `pytest --cov`) plus the gated
integration suite (real pinned binary + real tiny model) after every change; see the builder's
final summary for verbatim output.

---

## 7. Reporting a vulnerability

Please report security issues privately via GitHub Security Advisories:
**https://github.com/neonpilot/neonpilot/security/advisories/new** (replace with the canonical repo
URL on publish). Do not open a public issue for undisclosed vulnerabilities. Include repro steps,
affected version/commit, and impact. As a local, network-less CLI with no secrets, most issues are
non-emergency; expect acknowledgement within a reasonable window for an open-source project.
