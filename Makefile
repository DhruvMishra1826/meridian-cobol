COBC ?= cobc
CC ?= cc
COBFLAGS ?= -free -Wall -Wextra -Werror -debug -I copybooks
CFLAGS ?= -std=c11 -Wall -Wextra -Werror -O2
COVERAGE_FLAGS ?=
PYTHON ?= python3
UV ?= uv
SOURCES := src/main.cob src/validate.cob src/ledger.cob src/inventory.cob src/sales.cob
COPYBOOKS := $(wildcard copybooks/*.cpy)

.PHONY: all test test-pytest check lint typecheck lock lock-check audit coverage clean demo serve
all: build/meridian

build:
	mkdir -p build

build/store.o: native/store.c | build
	$(CC) $(CFLAGS) -c $< -o $@

build/meridian: $(SOURCES) $(COPYBOOKS) build/store.o | build
	$(COBC) $(COBFLAGS) -x $(SOURCES) build/store.o -o $@

check:
	$(COBC) $(COBFLAGS) -fsyntax-only $(SOURCES)
	$(CC) $(CFLAGS) -fsyntax-only native/store.c
	python3 -m compileall -q tools tests

lint:
	$(PYTHON) -m ruff check tools tests
	$(PYTHON) -m ruff format --check tools tests

typecheck:
	$(PYTHON) -m mypy tools

lock:
	$(UV) lock
	$(UV) export --locked --quiet --no-header --group dev --no-emit-project --output-file requirements-dev.txt
	$(UV) export --locked --quiet --no-header --no-dev --no-emit-project --output-file requirements.txt

lock-check:
	$(UV) lock --check
	@set -eu; meridian_lock_tmp=$$(mktemp -d); \
	trap 'rm -rf "$$meridian_lock_tmp"' EXIT; \
	$(UV) export --locked --quiet --no-header --group dev --no-emit-project --output-file "$$meridian_lock_tmp/dev.txt"; \
	$(UV) export --locked --quiet --no-header --no-dev --no-emit-project --output-file "$$meridian_lock_tmp/runtime.txt"; \
	diff -u requirements-dev.txt "$$meridian_lock_tmp/dev.txt"; \
	diff -u requirements.txt "$$meridian_lock_tmp/runtime.txt"

audit:
	$(PYTHON) -m pip_audit --requirement requirements-dev.txt --require-hashes
	npm audit --audit-level=high

coverage:
	python3 tools/coverage.py $(COVERAGE_FLAGS)

test: all
	$(PYTHON) -m unittest discover -s tests -v

test-pytest: all
	$(PYTHON) -m pytest tests --junitxml=build/test-results/junit.xml --cov=tools --cov-report=term-missing --cov-report=xml:coverage.xml --cov-report=html:build/python-coverage

demo: all
	python3 tools/demo.py

serve: all
	python3 tools/server.py

clean:
	rm -rf build
