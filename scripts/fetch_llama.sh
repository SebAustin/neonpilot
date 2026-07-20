#!/usr/bin/env bash
# Fetch + build the pinned llama.cpp commit (tag b10069), CPU-only, llama-bench target only.
#
# Idempotent: if a build already exists at vendor/llama.cpp/build/bin/llama-bench AND that
# checkout is at the pinned SHA, this script does nothing (skips clone/build). This lets CI
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

if [[ -x "$BINARY" ]]; then
  built_sha=$(git -C "$VENDOR" rev-parse HEAD 2>/dev/null || echo "")
  if [[ "$built_sha" == "$LLAMA_CPP_SHA" ]]; then
    echo "neonpilot: llama-bench already built at pinned SHA $LLAMA_CPP_SHA -- skipping fetch/build."
    echo "neonpilot: binary at $BINARY"
    exit 0
  fi
  echo "neonpilot: found $BINARY but it is not at the pinned SHA (found: ${built_sha:-unknown}, want: $LLAMA_CPP_SHA)." >&2
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

echo "neonpilot: build complete: $BINARY"
