.PHONY: venv lint format test fetch-llama benchmark clean

VENV := .venv
PYTHON := $(VENV)/bin/python

# Full-model reference for `make benchmark` (SC1: reproducible probe -> optimize -> report ->
# apply on a clean clone). Override with `MODEL=/path/to/model.gguf make benchmark` to point at
# any other GGUF (e.g. the tiny SmolLM2 CI model for a fast smoke test).
MODEL ?= $(HOME)/.neonpilot/models/qwen2.5-3b-instruct-q4_k_m.gguf
RUN_DIR := $(HOME)/.neonpilot/runs/latest

venv:
	uv venv $(VENV)
	uv pip install --python $(PYTHON) -e ".[dev]"

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .
	uv run ruff check --fix .

test:
	uv run pytest --cov=neonpilot --cov-report=term-missing

fetch-llama:
	./scripts/fetch_llama.sh

benchmark: fetch-llama
	@if [ ! -f "$(MODEL)" ]; then \
		echo "neonpilot: model not found at $(MODEL)" >&2; \
		echo "neonpilot: override the path with 'MODEL=/path/to/model.gguf make benchmark', or download the reference model:" >&2; \
		echo "" >&2; \
		echo "  mkdir -p ~/.neonpilot/models" >&2; \
		echo "  curl -L -o $(MODEL) \\" >&2; \
		echo "    \"https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf\"" >&2; \
		exit 1; \
	fi
	@echo "neonpilot: full probe -> optimize -> report -> apply pipeline (model: $(MODEL))"
	uv run neonpilot probe
	uv run neonpilot optimize "$(MODEL)"
	uv run neonpilot report --run-dir "$(RUN_DIR)"
	uv run neonpilot apply --run-dir "$(RUN_DIR)"

clean:
	rm -rf $(VENV) .pytest_cache .ruff_cache .coverage htmlcov
