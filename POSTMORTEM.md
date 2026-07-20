# neonpilot — Blameless Post-mortem

**Project:** neonpilot — Arm CPU llama.cpp runtime tuner (Arm "Create — AI Optimization Challenge").
**Type:** greenfield, one-day agency build. **Date:** 2026-07-20.
**Acceptance commit:** `9520829` (working tree clean at retro time).
**Method:** evidence-based (PLAN.md + Revision log, ACCEPTANCE.md build log, SECURITY.md audit,
`docs/dev/build-notes.md`, git history). Blameless — every finding is framed as a process/role/
skill gap, never a person.

---

## 1. Summary metrics

| Dimension | Result |
|---|---|
| Success criteria | 7/10 PASS, 3 OPEN-by-design (SC2 idle reference number, SC3 committed presets, SC6 M5 half) — all gated on quiet-machine / second-hardware access, none failed by defect or silence |
| Plan loop | 3 critic rounds: **87 → 87 → 98/100** (PASS threshold 90). Round 2 scored flat because verified Day-1 spike facts were not propagated into the plan |
| Build loop | 1 builder pass M0–M2, 1 pass M3–M4; SOLID **100/100 first verification try** (M0–M4) |
| Escaped defects to late stages | 0. Test-engineer caught the noise artifact before verify; security audit found 0 Critical/High |
| Security findings | 0 Critical / 0 High; 10 MEDIUM/LOW (F1–F10) fixed in one batch, F11–F13 accepted-documented |
| Tests / coverage | 203 unit + 3 gated integration passing; **96.83%** coverage (floor 80) |
| Headline number | +144.2% gen t/s, statistically dominant, but measured under ambient load — reframed honestly as a load-contaminated case study, not the reference number |

---

## 2. What went well

- **Day-1 spikes ran in parallel with the plan loop and de-risked everything.** Hardware probe
  (S1), pinned llama.cpp build (S2), KleidiAI kernel-path verification (S3), real `llama-bench -o
  json` shape capture (S4), and model downloads (S5) turned every "assumed" live-dependency fact
  into a verified one before code was written. This is why the M0–M4 build hit SOLID on the first
  verification pass.
- **Disjoint-file-ownership parallelism + resumed builder context.** Background agents worked in
  parallel with non-overlapping path ownership; the same builder agent was resumed across
  milestones (M0–M2, then M3–M4) so architectural context carried forward instead of being
  re-derived. Recorded deviations stayed small and never changed a `models.py` dataclass contract.
- **"Gate is run, not claimed."** Every acceptance number in ACCEPTANCE.md was produced by the
  verifier re-running the command on the reference machine with verbatim output — no self-reported
  metric was trusted. The SC1 pipeline was even proven via a fail-fast spot-check rather than a
  claimed 15-minute run.
- **Test-engineer caught a noise artifact before it could become a headline.** A real 180s-budget
  run reported `+394.2%` "speedup"; the test-engineer traced it to `--reps 2` (below the
  documented ≥3 minimum) amplifying intra-config variance on a shared machine — not an engine or
  parser defect — and added a statistical-credibility guard (reuse of the existing
  `stats.dominates()` test) that fires a caveat whenever the best does not statistically dominate
  the baseline or reps is below minimum.
- **Honest handling of a contaminated result.** The one real full-model number (+144.2% on
  Qwen2.5-3B) was genuine and statistically dominant but measured under loadavg 7.6–12.2
  (Docker/VM/Webex running). Rather than publish it as the reference figure, it was explicitly
  labeled an adaptive case study and the idle-machine reference was left OPEN. No criterion was
  passed by an unfair or unstated baseline.
- **Security posture designed in.** Argv-only subprocess boundary, `shlex.quote` on re-emitted
  invocations, self-contained zero-fetch HTML report, SHA-pinned llama.cpp — the audit surfaced
  only MEDIUM/LOW hardening items, all fixed in one batch.

---

## 3. What was hard / root causes (blameless)

### 3.1 Plan round 2 was a wasted cycle — spike facts weren't propagated
**Observation:** Rounds 1 and 2 both scored 87. Round 2 did not improve because the architect
fixed the structural defects from round 1 but did not absorb the *new empirical data* that the
Day-1 spikes produced in parallel between rounds (M1 Max has dotprod but **not** i8mm; `llama-cli`
target doesn't exist with examples off; KleidiAI engages DOTPROD-tier, not i8mm/SME; real model
sizes; the real pin SHA). Round 3 finally propagated all of it and jumped to 98.

**Root cause (process gap):** when live probes/spikes run *concurrently* with the plan loop, there
is no explicit rule that a revision must reconcile the plan against facts that landed since the
last version. Structural fixes and fact propagation are two different kinds of revision, and only
the first was requested/verified in round 2. The plan-critic scored structure without checking
that freshly verified facts had been folded in.

### 3.2 A headline metric was measured under uncontrolled system load
**Observation:** the reference benchmark ran while the machine was under heavy ambient load
(loadavg 7.6–12.2; Docker/VM/Webex). The +144.2% result was real and statistically dominant but
not a clean idle-machine reference, so it could not serve as the canonical SC2 number.

**Root cause (methodology gap):** system load was not checked *before* launching the reference
benchmark, and the benchmark tooling does not record ambient load as run metadata. The same root
cause produced the earlier +394% `--reps 2` artifact: both are "measurement taken under conditions
that invalidate the number" and neither was caught by the tooling at capture time — the test-engineer
caught them after the fact by reasoning about plausibility.

### 3.3 Intake nearly shipped a colliding name/concept
**Observation:** the planned name/concept ("armtune") was already in use by two competing hackathon
entrants. Intake caught it, forced a rename to **neonpilot**, and made differentiation a binding
requirement (SC10). This was a save, but a late one — it surfaced during intake review, not as a
standard intake step.

**Root cause (role gap):** the requirements-analyst intake has no explicit step to run a
competitive name/concept search, so name/concept collision is caught only opportunistically.

---

## 4. Lessons

### Project-specific (stay here)
- Linux probe cannot report real RAM or P/E-core split from the PLAN-specified signature
  (`ram_gb=0.0`, `p_cores=total`); acceptable because Linux is "designed to work, untested". If
  Linux support is ever hardened, add an optional `meminfo_text` parameter (build-notes #3).
- `presets/` intentionally stays empty until an idle-machine winner exists; the M1 Max and M5
  presets, the SC2 idle reference number, and the M5 `sme2=true` capture are all gated on
  quiet-machine / second-hardware access — carry them as OPEN next-steps, not defects.
- **Future neonpilot feature (do not build now):** the benchmark harness should record ambient
  system load (loadavg / core count / notable processes) as run metadata in `result.json`, and
  `report`/`optimize` should warn when a reference run is launched under elevated load. This is a
  product feature for neonpilot itself, not an agency-skill change.

### Generalizable (candidates → `SKILL-UPDATES.md`)
1. **Competitive name/concept search should be a standard intake step**, not an opportunistic
   catch (§3.3).
2. **When live probes/spikes complete during the plan loop, the plan-critic must verify their
   verified findings were propagated into the plan** before PASS — an unpropagated verified fact is
   a REVISE defect regardless of structural quality (§3.1).
3. **A headline performance metric must be captured under controlled, recorded measurement
   conditions** (reps ≥ documented minimum, statistical dominance over the baseline, and system
   load recorded); a load-contaminated or noise-dominated number must be labeled non-reference,
   never published as the canonical figure (§3.2).

---

## 5. Action items

| # | Action | Owner | Status |
|---|--------|-------|--------|
| A1 | Propose the three generalizable lessons as gated, additive skill updates | retrospective | Done → `SKILL-UPDATES.md` (awaiting user approval) |
| A2 | Run one quiet-machine `make benchmark` on the M1 Max → fill SC2 idle reference + first committed preset | user | Open |
| A3 | Run on an Apple M5 → complete SC3/SC6 M5 half + second preset | user | Open |
| A4 | Add ambient-load metadata capture to neonpilot's benchmark harness (product feature) | future build | Backlog |
| A5 | Publish public repo (Apache-2.0) and replace repo-URL placeholders | user | Open |

---

*No skill file was edited by this retrospective. All improvement proposals live in
`SKILL-UPDATES.md` and require the user's explicit approval before anything is applied.*
