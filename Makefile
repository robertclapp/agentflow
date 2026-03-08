.DEFAULT_GOAL := help

.PHONY: help test inspect-local doctor-local smoke-local check-local

PYTHON := $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

help:
	@printf '%s\n' \
	  'Available targets:' \
	  '  python        Prefer .venv/bin/python when available, else python3' \
	  '  test          Run the Python test suite' \
	  '  inspect-local Inspect the bundled local Kimi-backed smoke pipeline' \
	  '  doctor-local  Check local Codex/Claude/Kimi smoke prerequisites' \
	  '  smoke-local   Run the bundled local Codex + Claude-on-Kimi smoke test' \
	  '  check-local   Run doctor-local, then smoke-local'

test:
	$(PYTHON) -m pytest -q

inspect-local:
	$(PYTHON) -m agentflow inspect examples/local-real-agents-kimi-smoke.yaml --output summary

doctor-local:
	$(PYTHON) -m agentflow doctor examples/local-real-agents-kimi-smoke.yaml --output summary

smoke-local:
	$(PYTHON) -m agentflow smoke --show-preflight

check-local: doctor-local smoke-local
