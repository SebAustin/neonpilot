.PHONY: venv lint format test fetch-llama benchmark clean

VENV := .venv
PYTHON := $(VENV)/bin/python

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
	@echo "neonpilot: full probe -> optimize -> report -> apply pipeline"
	uv run neonpilot probe
	@echo "neonpilot: 'optimize'/'report'/'apply' land in milestones M3/M4 -- see PLAN.md section 6."

clean:
	rm -rf $(VENV) .pytest_cache .ruff_cache .coverage htmlcov
