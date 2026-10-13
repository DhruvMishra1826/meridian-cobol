COBC ?= cobc
CC ?= cc
COBFLAGS ?= -free -Wall -Wextra -Werror -debug -I copybooks
CFLAGS ?= -std=c11 -Wall -Wextra -Werror -O2
SOURCES := src/main.cob src/validate.cob src/ledger.cob src/inventory.cob src/sales.cob
COPYBOOKS := $(wildcard copybooks/*.cpy)

.PHONY: all test check lint coverage clean demo serve
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
	python3 -m ruff check tools tests
	python3 -m ruff format --check tools tests

coverage:
	python3 tools/coverage.py

test: all
	python3 -m unittest discover -s tests -v

demo: all
	python3 tools/demo.py

serve: all
	python3 tools/server.py

clean:
	rm -rf build
