.PHONY: run open decide test cov lint types fix
run:           # console chỉ đọc tại http://127.0.0.1:8200
	PYTHONPATH=src uv run python -m console
open:          # như run, kèm mở trình duyệt
	PYTHONPATH=src uv run python -m console --open
decide:        # bật quyền duyệt gate từ trang (đọc kỹ phần bảo mật trong API.md trước)
	PYTHONPATH=src uv run python -m console --allow-decide
test:
	uv run pytest -q
cov:
	uv run pytest -q --cov
types:
	uv run mypy src/console --ignore-missing-imports
lint:
	uv run ruff check src tests
	uv run mypy src/console --ignore-missing-imports
fix:
	uv run ruff check --fix src tests
