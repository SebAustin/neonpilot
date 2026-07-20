# neonpilot — Assumptions

Every assumption below states what we assumed, why, and how to override it. Update this file
whenever an assumption is validated, invalidated, or changed.

## Product / Scope Assumptions

1. **"Staged sweep" definition** — Assumed to mean: a small, hand-curated set of candidate
   configs per knob (2-3 thread configs, 3 KV-cache types, 2 flash-attention states, 2
   batch/ubatch pairs) combined with early stopping, rather than the full Cartesian product
   (~36+ combinations). *Why*: fits the 15-minute budget on a 3B-class model on M1 Max.
   *Override*: if the 15-min budget proves loose, expand candidate counts per knob before
   adding new knobs.

2. **Reference "full tune" model** — **RESOLVED (Day-1 spike S5):** **Qwen2.5-3B-Instruct
   GGUF, Q4_K_M** (`Qwen/Qwen2.5-3B-Instruct-GGUF` → `qwen2.5-3b-instruct-q4_k_m.gguf`,
   ~2.1 GB) for the < 15 minute / ≥10% speedup success criteria, distinct from the tiny CI
   test model. *Why*: a 3B Q4_K_M is a realistic local-inference model that developers actually
   run, fits the 15-min budget comfortably on M1 Max (smaller than a 7-8B model → more
   headroom), and shows meaningful KV-cache/flash-attention deltas. Downloaded and cached at
   `~/.neonpilot/models/`. *Override*: if a larger model is wanted for a bigger "WOW" number,
   re-pin here and in README and re-record demo numbers; keep the ≥10% bar honest.

3. **CI test model choice** — **RESOLVED (Day-1 spike S5):** **SmolLM2-135M-Instruct GGUF,
   Q4_K_M** (`unsloth/SmolLM2-135M-Instruct-GGUF` → `SmolLM2-135M-Instruct-Q4_K_M.gguf`,
   101 MB), superseding the earlier Qwen2.5-0.5B assumption. *Why*: at 101 MB it downloads and
   builds a full pipeline run well inside the CI budget, and the concern that "135M is too small
   to show t/s deltas" is **moot for CI** — the integration test asserts *structure*
   (well-formed artifacts, fields present, budget respected), never a performance delta. Real
   deltas are proven on the Qwen2.5-3B reference model (#2), not in CI. Downloaded and cached at
   `~/.neonpilot/models/`. *Override*: swap for a slightly larger sub-300 MB model only if a
   structural test genuinely needs it.

4. **llama.cpp pinned commit** — **RESOLVED (Day-1 spike S2):** pinned to release tag
   **`b10069`** = SHA **`178a6c44937154dc4c4eff0d166f4a044c4fceba`** (2026-07-20). Builds clean
   on Apple Silicon with `-DGGML_METAL=OFF -DGGML_CPU_KLEIDIAI=ON` (also `-DGGML_BLAS=OFF`),
   target `llama-bench`; exposes `-o json` with the expected field set (S4) and `-fa
   on/off/auto`. *Why*: reproducibility requires a fixed SHA. SHA is recorded in
   `scripts/fetch_llama.sh` and `neonpilot/_llama_pin.py` and asserted equal by
   `tests/test_pin.py`. *Override*: do not silently re-pin; a SHA change requires a PLAN.md
   Revision-log note and an update here.

5. **KleidiAI activation is real on M1 Max** — **RESOLVED / VERIFIED (Day-1 spike S3).**
   KleidiAI *does* engage on M1 Max via the pinned build: verbose `llama-bench -v` logs show
   `kleidiai: primary q4 kernel feature DOTPROD`, `primary q8 kernel feature DOTPROD`,
   `kleidiai: SME disabled`, and a `CPU_KLEIDIAI` model buffer alongside a `CPU_REPACK`
   (`q6_K_8x4`) buffer for the remaining quant types. **Conclusion for probe copy:** on M1 Max
   (no i8mm, no SME) KleidiAI selects **DOTPROD-tier** micro-kernels for q4/q8 weights; SME
   kernels are disabled; other quant types use ggml's generic CPU_REPACK/CPU paths. Probe copy
   must therefore say "i8mm ABSENT → DOTPROD-tier KleidiAI kernels engaged" — **no i8mm
   overclaim**. On SME2-capable M5 the same log is expected to select SME-tier kernels (to be
   captured during the M5 run). *Override*: none needed — verified.

6. **M5 access is real but timing-uncertain** — Assumed the user has physical/remote access
   to an Apple M5 Mac at some point before Aug 14, 2026, since the brief calls it "user's
   Apple M5 machine." *Why*: needed for the cross-generation differentiator (FR4, success
   criterion 3). *Override*: if M5 access falls through or slips past the deadline, ship with
   M1 Max as the only fully-measured preset and clearly label any M5 numbers as
   "unverified" / remove them rather than fabricate data — success criterion 3 explicitly
   requires *real* measured presets, not synthesized ones.

7. **Graviton/Linux stretch scope has no hard commitment** — Assumed AWS Graviton support
   stays "designed to work, untested" per the brief's non-goals, and no AWS spend is required
   for the core submission. *Why*: keeps budget at effectively $0 and avoids scope creep into
   a second full hardware target under deadline pressure. *Override*: if time permits after
   core criteria are met, spin up a Graviton instance (see credential-scope preflight below)
   as a bonus, but do not let it block core work.

## Technical / Constraint Assumptions

8. **Thermal telemetry availability** — Assumed macOS exposes usable core-temperature or
   throttle-state signals (via `powermetrics` or similar, possibly requiring `sudo`) for the
   cooldown guard in `optimize`. *Why*: needed for rigorous methodology (differentiator (e)).
   *Override*: if `powermetrics` requires interactive `sudo` incompatible with a smooth CLI UX,
   fall back to a fixed wall-clock cooldown delay (e.g., 30-60s between candidates) and
   document that thermal *state* is inferred from elapsed time, not measured directly, on
   platforms without an accessible sensor API. Linux/Graviton will likely need this fallback
   since sensor access varies (`untested` per non-goals).

9. **Budget** — Assumed effectively **$0 cloud spend** for the primary submission (all
   benchmarking on owner-controlled Apple Silicon hardware). *Why*: brief marks Graviton as
   optional/stretch and gives no budget figure. *Override*: if Graviton stretch work proceeds,
   cap spend at a single small arm64 instance (e.g., `t4g.small` or `c7g.large`) run for
   at most a few hours, then terminated — not a persistent resource.

10. **Performance target is 10% minimum, not a specific number** — Assumed "measurably beat
    llama.cpp defaults" from the brief translates to a concrete, checkable **≥10% generation
    t/s improvement** floor, since "measurable" alone isn't independently verifiable by a
    judge/verifier without a number. *Why*: gives the verifier and the team an unambiguous
    pass/fail bar while leaving room to report a larger real number. *Override*: if early
    spikes show typical llama.cpp-config tuning on M1 Max only yields ~5-8% for this model
    class, revisit the number honestly in this file rather than quietly lowering the bar in
    README only.

11. **Compliance / data handling** — Assumed no PII, no user data collection, no telemetry
    phone-home in the shipped tool. *Why*: it's a local CLI benchmarking tool; nothing in the
    brief suggests data collection, and adding any would be an unnecessary compliance surface
    for a hackathon entry. *Override*: if telemetry is ever added (e.g., opt-in preset
    submission to a shared registry), it must be explicit opt-in and documented separately.

## Strategic / Competitive Assumptions

12. **Differentiation is a hard requirement, not polish** — Per the competitive intelligence
    brief (two existing "armtune" entrants doing generic Arm64/Graviton auto-tune), we treat
    the five differentiators (ISA-probe depth, cross-generation Apple Silicon story, reusable
    preset registry, polished self-contained HTML report, rigorous thermal-aware methodology)
    as **binding requirements**, reflected in FR1-FR4 and success criteria 3 and 10, not
    optional nice-to-haves. *Why*: WOW factor (25 pts) and Potential Impact (20 pts) are 45 of
    100 judging points, and generic "prove a speedup" framing is already occupied by other
    entrants. *Override*: none — if any differentiator is dropped under time pressure, it must
    be a conscious, documented tradeoff in this file with a note on which judging category
    absorbs the hit.

## Credential-Scope Preflight

For every external service the project calls or deploys to, record the credential needed,
its required scope, and how to verify that scope **now** (Day-1), not at demo/deploy time.

| Service | Credential | Required scope | Verify now (Day-1) |
|---|---|---|---|
| GitHub (public repo, Apache-2.0, Actions CI) | GitHub account / PAT or default `GITHUB_TOKEN` in Actions | Repo: **write** (push code, manage Actions workflows, create releases if used for preset distribution). `GITHUB_TOKEN` default scope is sufficient for CI; a personal PAT is only needed if automating repo creation/settings outside the Actions runner. | Confirm repo exists and current user has push access via `git push` to a test branch; confirm Actions is enabled for the repo (Settings > Actions) before relying on CI as a success criterion. |
| Hugging Face Hub (downloading GGUF test model + reference model) | HF access token (optional for public models; required only if any chosen model is gated) | **Read-only** — no write/upload scope needed unless we later publish neonpilot's own presets or a demo Space. | Both chosen models (`unsloth/SmolLM2-135M-Instruct-GGUF`, `Qwen/Qwen2.5-3B-Instruct-GGUF`) are public and downloaded unauthenticated (spike S5). If a future model 401s, switch to a public alternative or generate a **read-only** HF token stored as a GitHub Actions secret (`HF_TOKEN`), never committed. |
| Hugging Face Hub (optional: hosting a demo Space for the report or preset registry) | HF token with **write** scope to the target Space | **Write** — required only if we build a demo HF Space; not required for the core CLI submission. | Not pursued in v1 core scope (no HF Space is a stated deliverable in the approved plan). If added later as a stretch, generate a fine-grained token scoped to *that Space only*, verify with a trivial `huggingface_hub` file upload to the Space before wiring it into any automated workflow. |
| AWS (optional Graviton stretch benchmarking) | AWS IAM credentials (access key or SSO profile) | Minimum: `ec2:RunInstances`, `ec2:TerminateInstances`, `ec2:Describe*` scoped to a single throwaway instance; explicitly **no** persistent infra, no IAM-modifying permissions. | Not required for core submission. If pursued, verify scope with `aws sts get-caller-identity` and a dry-run `ec2:DescribeInstances` call before launching anything; set a billing alert before first launch. |
| PyPI (optional: `pip install neonpilot` from a real PyPI package rather than `pip install -e .`) | PyPI API token | **Upload/write** scoped to the `neonpilot` project only (not account-wide). | Not required for judging (brief only requires reproducible install from source per success criterion 9). If pursued as DX polish, verify by publishing to **TestPyPI** first with a project-scoped token before any real PyPI upload. |
| llama.cpp upstream (GitHub, source dependency) | None (public repo, pinned commit, cloned/fetched read-only) | **Read-only** — we only fetch a pinned commit, never push upstream. | Confirmed (spike S2): pinned SHA `178a6c44937154dc4c4eff0d166f4a044c4fceba` (tag `b10069`) is fetchable via a plain shallow `git fetch` with no auth, so CI doesn't depend on any token for this step. |

**Summary**: the only credential with any write scope that's actually load-bearing for the
core (non-stretch) submission is the GitHub push/Actions access the user already has as repo
owner. All other write-scoped credentials (HF Space, AWS, PyPI) belong exclusively to
optional stretch scope and are explicitly not Day-1 blockers for the primary deliverable.
