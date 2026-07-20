# neonpilot — Proposed Team-Skill Updates

> **STATUS: PROPOSALS ONLY — NOT APPLIED.** Every item below requires the user's **explicit
> approval** before anything is changed. This retrospective edited **no** shared skill or agent
> file. On approval, each accepted item lands on a `skill-updates/neonpilot-20260720` branch and
> opens a **PR against the branch-protected `main`** (never a direct merge), bumps `version` in
> both manifests, adds a `CHANGELOG.md` entry, and regenerates ports via
> `node scripts/build-ports.mjs` in the same PR. Merging is a human (admin) decision.
>
> All targets are the single source of truth under
> `plugins/ai-project-agency/{skills,agents}/…` — never a generated `cursor/**` or `claude-ai/**`
> port. Every proposal is **additive and tightening only** — none weakens a guardrail or lowers a
> quality bar.

---

## 1. Add a competitive name/concept search to intake

- **Target:** `plugins/ai-project-agency/agents/requirements-analyst.md`
- **Change (additive):** add one bullet to the `Do:` list, after the
  **Credential-scope preflight** bullet:

  ```markdown
  - **Competitive name/concept scan.** Before locking the project name and positioning, run a
    quick search (web + the relevant registry/marketplace/hackathon gallery) for existing
    products or entrants using the same name or the same core concept. If a collision exists,
    flag it, propose a distinct name, and record differentiation from the closest match as a
    binding success criterion in `PLAN.md`. A name/concept collision found late is a
    positioning risk, not a cosmetic one.
  ```

  (`requirements-analyst` already has `WebSearch` in its `tools:` line, so no tool change is
  needed.)

- **Evidence:** the planned name/concept "armtune" was already in use by **two** competing
  hackathon entrants. Intake caught it opportunistically and forced the rename to **neonpilot**,
  with differentiation made a binding requirement (SC10, `README.md#Differentiation`). Making this
  a standard intake step turns a lucky late save into a reliable early check. (POSTMORTEM §3.3.)

---

## 2. Make the plan-critic enforce propagation of verified probe/spike facts

- **Target:** `plugins/ai-project-agency/agents/plan-critic.md`
- **Change (additive):** append one paragraph to the agent body, after the
  "Do not edit the plan…" paragraph:

  ```markdown
  If any live probe, spike, or environment check completed **since the plan version you are
  scoring was last revised**, verify that its verified findings are actually propagated into the
  plan — not just that the structure improved. An architecture that was restructured but still
  carries a now-disproven assumption (a hardware feature that was measured absent, a build target
  that was found not to exist, a corrected model size or pin) is a **REVISE**, and you must quote
  the stale statement and name the verified fact it contradicts — regardless of how sound the rest
  of the plan reads.
  ```

- **Evidence:** the plan loop scored **87 → 87 → 98**. Round 2 stalled at 87 because the architect
  fixed round-1 structural defects but did **not** absorb the Day-1 spike facts that landed in
  parallel between rounds (M1 Max has dotprod but **not** i8mm per `FEAT_I8MM=0`; the `llama-cli`
  target does not exist with examples off; KleidiAI engages DOTPROD-tier not i8mm/SME; corrected
  model sizes; the real pin SHA). Round 3 propagated all of it and jumped to 98. A propagation
  check would have caught round 2 as a REVISE on fact-staleness and saved a full critic cycle.
  This complements the existing `plan-rubric` Feasibility guidance ("the probe's findings are
  reflected in the design — not assumed") by making the *between-rounds* reconciliation an explicit
  reviewer duty. (POSTMORTEM §3.1.)

---

## 3. Require controlled, recorded measurement conditions for any headline performance metric

- **Target:** `plugins/ai-project-agency/skills/solution-rubric/SKILL.md`
- **Change (additive):** add one bullet under `## Criterion guidance`, immediately after the
  existing "Any comparative or headline metric … honest baseline" bullet:

  ```markdown
  - **Measurement conditions must be controlled and recorded.** A headline performance number
    (throughput, latency, speedup) only counts toward "criteria met" when the run's conditions
    make it trustworthy: repetitions at or above the tool's documented minimum, the winning
    result **statistically dominating** the baseline (not within noise bands), and the ambient
    system state (e.g. load average, contending processes) recorded alongside the number. A result
    taken under uncontrolled load, or with too few reps to separate signal from variance, must be
    labeled a **non-reference / illustrative** figure — never published as the canonical metric.
  ```

- **Evidence:** two distinct manifestations of the same root cause in one build. (a) A real
  180s-budget run reported `+394.2%` "speedup" that the test-engineer traced to `--reps 2` (below
  the documented ≥3 minimum) amplifying intra-config variance on a shared machine — a noise
  artifact, not an engine defect — prompting a statistical-credibility guard
  (`report/*` + `cli.py` now caveat whenever `not dominates(best, baseline)` or reps < 3). (b) The
  one full-model number, `+144.2%` on Qwen2.5-3B, was genuine and statistically dominant but taken
  under loadavg 7.6–12.2 (Docker/VM/Webex), so it was correctly demoted to a labeled case study and
  the idle-machine reference left OPEN. This bullet generalizes the "gate is run, not claimed"
  discipline to *the conditions under which the gate was run*, and reinforces (does not replace)
  the existing honest-baseline and canonical-metrics guidance. (POSTMORTEM §3.2.)

---

## Notes on scope

- **No new agent proposed.** All three gaps map cleanly onto existing roles
  (`requirements-analyst`, `plan-critic`, `solution-verifier` via `solution-rubric`). Adding a role
  would be overlap, not coverage — the roster stays lean.
- **Deliberately not proposed as a skill change:** neonpilot's own benchmark harness recording
  ambient load as run metadata. That is a *product* feature for neonpilot (POSTMORTEM §4, A4), not
  an agency-skill update, so it stays out of this funnel.
- **Evidence strength:** items 1 and 3 are each supported by a clear in-project failure (and item 3
  by two independent manifestations of one root cause). Item 2 is supported by one measurable wasted
  critic cycle; if the reviewers consider a single project weak evidence for a hard rule, item 2 can
  be adopted as a "watch item" rather than a binding REVISE trigger.
