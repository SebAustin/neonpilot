#!/usr/bin/env bash
# Fetch + build the pinned llama.cpp commit (tag b10069), CPU-only, llama-bench target only.
#
# Idempotent: if a build already exists at vendor/llama.cpp/build/bin/llama-bench AND its pin
# stamp matches the pinned SHA, this script does nothing (skips clone/build). This lets CI
# and local dev re-run `make fetch-llama` safely after the first successful build.
#
# See PLAN.md section 3.2 for the design rationale (why llama-bench only, why no llama-cli,
# why -DGGML_METAL=OFF/-DGGML_BLAS=OFF/-DGGML_CPU_KLEIDIAI=ON).
set -euo pipefail

# Pinned commit: tag b10069. Must match neonpilot/_llama_pin.py::LLAMA_CPP_COMMIT exactly
# (tests/test_pin.py asserts this).
LLAMA_CPP_SHA="178a6c44937154dc4c4eff0d166f4a044c4fceba"
LLAMA_CPP_REPO="https://github.com/ggml-org/llama.cpp"

VENDOR="${NEONPILOT_VENDOR:-vendor/llama.cpp}"
BINARY="$VENDOR/build/bin/llama-bench"
# SECURITY.md F4: CI caches only $VENDOR/build (not .git), so a cache-restored binary has no
# git history to check `rev-parse HEAD` against. This stamp file lives *inside* build/ (so it
# travels with the cache) and is the integrity check for both the local idempotent-rebuild
# path and a cache-restored binary -- a cache poisoned with a different binary but no matching
# stamp (or a stamp for the wrong SHA) is rejected and triggers a full rebuild.
PIN_STAMP="$VENDOR/build/bin/llama-bench.pin"

if [[ -x "$BINARY" ]]; then
  stamped_sha=""
  if [[ -f "$PIN_STAMP" ]]; then
    stamped_sha=$(cat "$PIN_STAMP")
  elif [[ -d "$VENDOR/.git" ]]; then
    # Migration path: a checkout built before the .pin stamp existed. Verify via git (the
    # source of truth for a real local checkout) and self-heal by writing the stamp, so this
    # and any future cache can rely on the stamp alone (CI caches build/ but not .git).
    git_sha=$(git -C "$VENDOR" rev-parse HEAD 2>/dev/null || echo "")
    if [[ "$git_sha" == "$LLAMA_CPP_SHA" ]]; then
      stamped_sha="$git_sha"
      echo "$stamped_sha" > "$PIN_STAMP"
    fi
  fi
  if [[ "$stamped_sha" == "$LLAMA_CPP_SHA" ]]; then
    echo "neonpilot: llama-bench already built at pinned SHA $LLAMA_CPP_SHA (verified via $PIN_STAMP) -- skipping fetch/build."
    echo "neonpilot: binary at $BINARY"
    exit 0
  fi
  echo "neonpilot: found $BINARY but its pin stamp does not match (found: '${stamped_sha:-<none>}', want: $LLAMA_CPP_SHA)." >&2
  echo "neonpilot: remove $VENDOR and re-run to rebuild at the pinned commit." >&2
  exit 1
fi

echo "neonpilot: fetching llama.cpp @ $LLAMA_CPP_SHA into $VENDOR ..."
if [[ ! -d "$VENDOR/.git" ]]; then
  mkdir -p "$VENDOR"
  git init "$VENDOR"
fi
git -C "$VENDOR" fetch --depth 1 "$LLAMA_CPP_REPO" "$LLAMA_CPP_SHA"
git -C "$VENDOR" checkout FETCH_HEAD

# SECURITY.md F8: assert the checkout actually landed on the pinned SHA before building
# anything from it -- do not assume `checkout FETCH_HEAD` silently did the right thing.
checked_out_sha=$(git -C "$VENDOR" rev-parse HEAD)
if [[ "$checked_out_sha" != "$LLAMA_CPP_SHA" ]]; then
  echo "neonpilot: checked-out commit $checked_out_sha does not match pinned SHA $LLAMA_CPP_SHA -- aborting." >&2
  exit 1
fi

echo "neonpilot: configuring CMake (CPU-only, KleidiAI on, llama-bench target only) ..."
cmake -S "$VENDOR" -B "$VENDOR/build" \
  -DCMAKE_BUILD_TYPE=Release \
  -DGGML_METAL=OFF \
  -DGGML_BLAS=OFF \
  -DGGML_CPU_KLEIDIAI=ON \
  -DLLAMA_BUILD_TESTS=OFF \
  -DLLAMA_BUILD_EXAMPLES=OFF \
  -DLLAMA_BUILD_SERVER=OFF \
  -DLLAMA_BUILD_TOOLS=ON

echo "neonpilot: building llama-bench ..."
cmake --build "$VENDOR/build" --config Release --target llama-bench -j

echo "$LLAMA_CPP_SHA" > "$PIN_STAMP"
echo "neonpilot: build complete: $BINARY (pin stamp written to $PIN_STAMP)"
