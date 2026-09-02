.PHONY: test demo lint fix golden gate eval
test:
	uv run pytest -q
demo:
	PYTHONPATH=src uv run python -m company.demo
lint:
	uv run ruff check src tests
fix:
	uv run ruff check --fix src tests
golden:
	UPDATE_GOLDEN=1 uv run pytest -q tests/test_golden_agents.py
gate:
	PYTHONPATH=src uv run python -m company.gate_cli list
eval:
	PYTHONPATH=src uv run python -m company.evals $(AGENT)
