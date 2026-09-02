.PHONY: test cov lint types fix demo golden gate eval eval-record eval-replay run watch status report metrics
test:
	uv run pytest -q
cov:
	uv run pytest -q --cov
types:
	uv run mypy src/company --ignore-missing-imports
demo:
	PYTHONPATH=src uv run python -m company.demo
lint:
	uv run ruff check src tests
	uv run mypy src/company --ignore-missing-imports
fix:
	uv run ruff check --fix src tests
golden:
	UPDATE_GOLDEN=1 uv run pytest -q tests/test_golden_agents.py
gate:
	PYTHONPATH=src uv run python -m company.gate_cli list
eval:
	PYTHONPATH=src uv run python -m company.evals $(AGENT)
eval-record:   # chạy model thật, lưu evals/recordings/$(AGENT).json — bắt buộc sau khi đổi prompt/skill (ADR-0010)
	PYTHONPATH=src uv run python -m company.evals $(AGENT) --record
eval-replay:   # như CI: phát lại từ bản ghi, không gọi model
	PYTHONPATH=src uv run python -m company.evals all --replay
run:
	PYTHONPATH=src uv run python -m company.orchestrator run
watch:
	PYTHONPATH=src uv run python -m company.orchestrator run --watch 5
status:
	PYTHONPATH=src uv run python -m company.orchestrator status
report:
	PYTHONPATH=src uv run python -m company.orchestrator report
metrics:       # gọi/token/USD/thời gian theo agent, model, ticket; thêm PROM=1 để xuất Prometheus text
	PYTHONPATH=src uv run python -m company.orchestrator metrics $(if $(PROM),--prometheus,)
