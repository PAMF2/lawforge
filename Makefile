.PHONY: help preflight test smoke loop data clean push lint

PY ?= python3

help:
	@echo "lawforge make targets:"
	@echo "  make preflight  -- run pipeline health checks"
	@echo "  make test       -- run unit tests"
	@echo "  make data       -- download + split HF dataset (needs HF_TOKEN)"
	@echo "  make smoke      -- one Karpathy generation"
	@echo "  make loop       -- run Karpathy loop until plateau/deadline"
	@echo "  make lint       -- ruff check"
	@echo "  make clean      -- remove caches"

preflight:
	bash scripts/preflight.sh

test:
	$(PY) -m pytest -q tests/

data:
	$(PY) scripts/prep_data.py

smoke:
	PYTHONPATH=$$(pwd) bash evolve/loop.sh smoke

loop:
	PYTHONPATH=$$(pwd) bash evolve/loop.sh infinite

lint:
	ruff check evolve/ lean/ tests/ scripts/ solver/ || true

submission:
	mkdir -p dist
	cd dist && rm -f lawforge_solo.zip && \
	  zip -rq lawforge_solo.zip ../solver/ -x "*/__pycache__/*"
	@du -h dist/lawforge_solo.zip

eval-dev:
	LAWFORGE_ALLOW_MOCK=1 $(PY) -m eval_harness --split dev --limit 200 \
	  --workers 4 --timeout 60

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache .mypy_cache
