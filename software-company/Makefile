.PHONY: test demo lint fix
test:
	uv run pytest -q
demo:
	PYTHONPATH=src uv run python -m company.demo
lint:
	uv run ruff check src tests
fix:
	uv run ruff check --fix src tests
