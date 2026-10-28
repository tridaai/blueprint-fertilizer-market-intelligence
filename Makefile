# Trida AI Blueprint — Fertilizer & Agrochemical Market Intelligence Agent
#
# Primary workflow is uv (https://docs.astral.sh/uv/):
#   make install     uv sync --extra dev
#   make demo        generate the dataset and walk the planted truth, offline
#   make test        pytest
#   make evals       eval gate, offline
#   make serve       the API on http://localhost:8000
#   make harness     boot the app and exercise the HTTP surface in-process
#   make cli         the CLI surface (an outlook, as an example)
#
# No uv? python3 -m venv .venv && source .venv/bin/activate, then:
#   make install-pip

.PHONY: install install-pip demo test evals serve harness cli

install:
	uv sync --extra dev

install-pip:
	# The frozen, hash-verified set first, then the package itself with
	# --no-deps: pip refuses an editable install under a hashed
	# constraints file, so the two steps never mix.
	pip install -r constraints.txt
	pip install --no-deps -e .
	pip install "pytest==9.1.1" "httpx==0.28.1"

demo:
	uv run python scripts/demo.py

test:
	uv run pytest -q

evals:
	uv run python evals/run_evals.py

serve:
	uv run uvicorn fertilizer_intelligence.api:app --port 8000

harness:
	uv run python scripts/local_harness.py

cli:
	uv run python scripts/cli.py outlook --crop-year 2025-26 --season kharif
