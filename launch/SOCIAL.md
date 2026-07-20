# neonpilot — Social drafts

> Draft only. Nothing here has been posted, scheduled, or sent. Copy the text you want and post it
> yourself — publishing is a gated human action, not something this draft (or any agent) does for
> you. Replace `[REPO-URL]` and `[VIDEO-URL]` before posting.

---

## LinkedIn post (~150 words)

I spent the last stretch building **neonpilot** for the Arm AI Optimization Challenge — a CLI that
auto-tunes `llama.cpp` for Arm CPUs and explains *why* a config wins, not just what it is.

The most interesting result wasn't a clean-room benchmark. I ran a full sweep on my M1 Max while
Docker, a VM, and Webex were all fighting for the same P-cores (load average up to 12 on a 10-core
machine). The tuner still found a config that pushed generation throughput from 9.05 to 22.11
tokens/sec — +144% — by leaving two P-cores unrequested instead of grabbing all eight like
`llama.cpp`'s default does. Turns out that gives the OS scheduler room to service everything else
without stalling `llama.cpp`'s own per-layer thread barrier.

I'm framing that honestly: it's a real, measured, adaptive result under load, not the clean idle-
machine number the challenge's speedup bar is checked against — that run is still open, and I'd
rather say so than round up.

Repo (Apache-2.0): [REPO-URL]
Demo: [VIDEO-URL]

#ArmAIOptimizationChallenge #llamacpp #EdgeAI #AppleSilicon

---

## X / short-thread version (3 posts)

**1/3**
`llama.cpp` defaults assume your machine is idle. Mine wasn't — Docker + a VM + Webex all fighting
for the same P-cores. Built neonpilot to find the config that actually works under real load, and
explain why. Arm AI Optimization Challenge entry. 🧵

**2/3**
Real M1 Max run, ambient load, loadavg up to 12/10 cores: neonpilot's tuned config hit +144% gen
throughput vs `llama.cpp` defaults (9.05 → 22.11 tok/s) — by leaving 2 P-cores free instead of
grabbing all 8. Less contention on llama.cpp's own thread barrier = faster, not slower.

**3/3**
This is the loaded-machine case study, not the clean idle-machine number — I'm not rounding that
up. Repo (Apache-2.0): [REPO-URL] · Demo: [VIDEO-URL] · Mobile AI track.

---

## Short-video hook (for a <15s cut)

"llama.cpp assumes your machine is idle. Mine had Docker, a VM, and a video call running — and my
tuner still found a config that's 144% faster than the default, just by leaving two cores free."

---

## Notes for the human posting this

- The +144.2% / +21.9% numbers trace to exactly one canonical source:
  [`docs/results/m1-max-loaded-20260720/`](../docs/results/m1-max-loaded-20260720/) (the same
  source cited in `DEVPOST.md` and `README.md`). If that directory is ever regenerated, update
  this file, `DEVPOST.md`, and `README.md` together — don't let a re-run's numbers drift out of
  sync with what's already been posted.
- Do not claim the idle-machine ≥10% reference number or the M5/SME2 comparison as achieved —
  both are explicitly open items in `README.md` and are omitted from these drafts for that reason.
- CTA is a repo link and (optional) a demo link; there is no product, waitlist, or signup to push.
