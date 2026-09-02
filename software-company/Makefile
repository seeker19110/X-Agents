.PHONY: test demo lint
test:
	uv run pytest software-company/tests -q
demo:
	cd software-company && PYTHONPATH=src uv run python -m company.demo
lint:
	uv run ruff check software-company/src software-company/tests
