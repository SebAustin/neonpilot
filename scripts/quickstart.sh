#!/usr/bin/env bash
# One-command turnkey setup + full benchmark run for a fresh neonpilot clone on an Arm Mac
# (target: the user's Apple M5 machine). See docs/M5-RUNBOOK.md for the human-facing version
# of these steps (what to expect, what to bring back).
#
# Steps: (a) verify arm64 macOS, (b) verify/brew-install cmake + uv, (c) `uv sync --locked`,
# (d) build the pinned llama.cpp, (e) download + sha256-verify the reference model, (f) probe
# this host (screenshot-worthy ISA table), (g) run the full benchmark pipeline (neonpilot's own
# ambient-load preflight warns if the machine looks busy), (h) print next steps.
#
# Idempotent in the sense that matters here: every step either skips already-satisfied work
# (prerequisites present, model already downloaded + verified, llama.cpp already built at the
# pinned SHA) or fails loudly with an actionable message rather than silently corrupting state.
# `make benchmark` itself always creates a fresh, timestamped run directory by design (see
# README.md's "Where artifacts land") -- re-running this script safely produces another
# benchmark run rather than erroring or clobbering the previous one.
set -euo pipefail

# --- 0. Always operate from the repo root, regardless of the caller's cwd ------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$REPO_ROOT" || exit 1

log() { echo "neonpilot: $*"; }
err() { echo "neonpilot: $*" >&2; }

# --- Pinned reference-model checksum (SECURITY.md F7 pattern: computed locally via
# `shasum -a 256` against a known-good copy, verified post-download before any use). This is
# the same Qwen2.5-3B-Instruct Q4_K_M file the M1 Max case studies in docs/results/ were
# measured against.
MODEL_URL="https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf"
MODEL_SHA256="626b4a6678b86442240e33df819e00132d3ba7dddfe1cdc4fbb18e0a9615c62d"
MODEL_PATH="$HOME/.neonpilot/models/qwen2.5-3b-instruct-q4_k_m.gguf"
COMPARE_AGAINST="docs/results/m1-max-moderate-load-20260806"

# --- (a) verify arm64 macOS -----------------------------------------------------------------

log "checking platform ..."
os_name="$(uname -s)"
arch_name="$(uname -m)"
if [[ "$os_name" != "Darwin" ]]; then
  err "this quickstart targets macOS (Darwin) on Apple Silicon; detected OS '$os_name'."
  err "neonpilot is macOS/Linux arm64 only -- see README.md's 'Setup instructions' for a"
  err "manual, non-macOS-specific walkthrough (Linux arm64 is supported, just not by this script)."
  exit 1
fi
if [[ "$arch_name" != "arm64" ]]; then
  err "this quickstart targets arm64 (Apple Silicon); detected architecture '$arch_name'."
  err "neonpilot is Arm-specific and CPU-only by design -- an Intel/x86_64 Mac is not a"
  err "supported target for the ISA-probe/tuning story this tool exists for."
  exit 1
fi
log "OK: macOS arm64 (Apple Silicon) detected."

# --- (b) verify or brew-install cmake + uv (never install Homebrew itself) -----------------

require_or_brew_install() {
  local cmd_name="$1" brew_formula="$2" manual_url="$3"
  local cmd_path
  if cmd_path=$(command -v "$cmd_name" 2>/dev/null); then
    log "OK: found $cmd_name ($cmd_path)"
    return 0
  fi
  if command -v brew >/dev/null 2>&1; then
    log "$cmd_name not found -- installing via 'brew install $brew_formula' ..."
    if ! brew install "$brew_formula"; then
      err "'brew install $brew_formula' failed. Install $cmd_name manually and re-run this"
      err "script -- see $manual_url"
      exit 1
    fi
  else
    err "$cmd_name not found, and Homebrew is not installed."
    err "This script will NOT install Homebrew for you. Either:"
    err "  1. install Homebrew yourself (https://brew.sh), then re-run this script, or"
    err "  2. install $cmd_name manually -- see $manual_url"
    exit 1
  fi
}

log "checking prerequisites (cmake, uv) ..."
require_or_brew_install cmake cmake "https://cmake.org/download/"
require_or_brew_install uv uv "https://docs.astral.sh/uv/getting-started/installation/"

# --- (c) install neonpilot + runtime dependencies from the committed lockfile ---------------

log "installing neonpilot (uv sync --locked) ..."
uv sync --locked

# --- (d) fetch + build the pinned llama.cpp (idempotent: scripts/fetch_llama.sh handles this
# itself via a pin-stamp check) ---------------------------------------------------------------

log "building the pinned llama.cpp (this is the one-time ~5 min step; skips if already built) ..."
bash scripts/fetch_llama.sh

# --- (e) download + sha256-verify the reference model ---------------------------------------

verify_model_checksum() {
  echo "$MODEL_SHA256  $MODEL_PATH" | shasum -a 256 -c - >/dev/null 2>&1
}

model_dir=$(dirname "$MODEL_PATH")
mkdir -p "$model_dir"
if [[ -f "$MODEL_PATH" ]] && verify_model_checksum; then
  log "OK: reference model already present and sha256-verified at $MODEL_PATH -- skipping download."
else
  if [[ -f "$MODEL_PATH" ]]; then
    err "a file exists at $MODEL_PATH but failed the pinned sha256 check -- re-downloading."
  fi
  log "downloading the reference model (Qwen2.5-3B-Instruct Q4_K_M, ~2.1 GB) to $MODEL_PATH ..."
  curl -L --fail -o "$MODEL_PATH" "$MODEL_URL"
  log "verifying sha256 checksum ..."
  if ! verify_model_checksum; then
    err "downloaded file at $MODEL_PATH does NOT match the pinned sha256"
    err "($MODEL_SHA256). Refusing to use it -- delete $MODEL_PATH and re-run this script."
    rm -f "$MODEL_PATH"
    exit 1
  fi
  log "OK: sha256 checksum verified."
fi

# --- (f) probe this host: the M5 ISA/SME2 feature table is itself a deliverable -------------

log "probing this host's Arm ISA features ..."
echo ""
uv run neonpilot probe
echo ""
log "^^ SCREENSHOT THE TWO TABLES ABOVE ('ISA features' and 'llama.cpp fast-path"
log "   activation') -- on an Apple M5 this is expected to show sme2=true and SME-tier"
log "   KleidiAI kernel activation (vs. the M1 Max reference's DOTPROD-tier), and is"
log "   itself one of the deliverables this run produces. See docs/M5-RUNBOOK.md."

chip_id=$(uv run neonpilot probe --json | uv run python3 -c 'import json,sys; print(json.load(sys.stdin)["chip_id"])')
model_class=$(basename "$MODEL_PATH" .gguf | tr '[:upper:]' '[:lower:]')

# --- (g) run the full benchmark pipeline -----------------------------------------------------
# `make benchmark` runs probe -> optimize -> report -> apply against $MODEL_PATH.
# `neonpilot optimize`'s own ambient-load preflight (feature F-A) will print a warning here if
# this machine's loadavg looks busy relative to its core count -- no extra step needed, that's
# the tool's own built-in telemetry doing its job (see README.md's "Idle-machine reference and
# the first preset" section for what that warning being present or absent means for this run).

log "running the full probe -> optimize -> report -> apply pipeline (~15 min sweep) ..."
echo ""
MODEL="$MODEL_PATH" make benchmark
echo ""

# --- (h) next steps ---------------------------------------------------------------------------

latest_run="$HOME/.neonpilot/runs/latest"
runs_dir=$(dirname "$latest_run")
# `latest` is a relative symlink (just the run directory's basename, see artifacts.mark_latest)
# -- resolve it against its parent directory rather than assuming an absolute target.
resolved_run=$(readlink "$latest_run" 2>/dev/null || true)
if [[ -n "$resolved_run" ]]; then
  run_dir="$runs_dir/$resolved_run"
else
  run_dir="$latest_run"
fi

echo "=============================================================================="
log "quickstart complete."
echo "=============================================================================="
log "Run directory:   $run_dir"
log "Preset (if the tuner beat the baseline): presets/$chip_id/$model_class.json"
log "  (re-print its invocation any time with:"
log "   uv run neonpilot apply presets/$chip_id/$model_class.json)"
echo ""
log "Compare this run against the M1 Max moderate-load case study:"
printf 'neonpilot:   uv run neonpilot compare "%s" "%s"\n' "$run_dir" "$COMPARE_AGAINST"
echo ""
log "Bring back to the main machine:"
log "  1. The run directory: $run_dir"
log "  2. The preset, if one was written: presets/$chip_id/$model_class.json"
log "  3. Your screenshot(s) of the 'neonpilot probe' ISA/fast-path tables from step (f) above"
