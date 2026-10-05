# Root của uv workspace — một lệnh cho cả năm package. Target riêng của từng package (demo, run, login...)
# vẫn nằm trong Makefile của thư mục đó; `make -C platform/gateway login` hoặc `cd platform/gateway && make login`.
MEMBERS := platform/console platform/gateway platform/xagents-core companies/keeper companies/software-company

.PHONY: sync test cov lint types fix build clean ecc-vendor ecc-check $(MEMBERS)

sync:          # một .venv chung ở root, cài cả năm package editable theo uv.lock
	uv sync --locked

test:          # pytest từng package (ngưỡng coverage của từng package nằm trong pyproject của nó)
	@for d in $(MEMBERS); do echo "== $$d"; $(MAKE) -C $$d test || exit 1; done

cov:
	@for d in $(MEMBERS); do echo "== $$d"; $(MAKE) -C $$d cov || exit 1; done

lint:          # ruff + mypy từng package
	@for d in $(MEMBERS); do echo "== $$d"; $(MAKE) -C $$d lint || exit 1; done

types:
	@for d in $(MEMBERS); do echo "== $$d"; $(MAKE) -C $$d types || exit 1; done

fix:
	@for d in $(MEMBERS); do echo "== $$d"; $(MAKE) -C $$d fix || exit 1; done

build:         # wheel + sdist của cả năm vào dist/
	uv build --all-packages

clean:
	rm -rf dist build */build */src/*.egg-info

ecc-vendor:    # sinh lại tập ECC vendor ở .claude/ từ commit ghim trong docs/integrations/ecc.lock.json (ADR gốc 0028)
	uv run python scripts/ecc_vendor.py build

ecc-check:     # tập ECC vendor có đúng là output tại commit ghim không — cùng lệnh job CI `ecc-check`, cần github.com
	uv run python scripts/ecc_vendor.py check

# `make platform/console` = `make -C platform/console` (chạy target mặc định của package đó)
$(MEMBERS):
	$(MAKE) -C $@
