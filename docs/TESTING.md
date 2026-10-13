# Testing and measured coverage

Meridian's tests execute the compiled COBOL engine against temporary journals. They check business invariants, persisted replay, accounting and operational record consistency, transaction rollback, file corruption detection, concurrent requests, record limits, command validation, and the local HTTP boundary. The suite uses Python's standard `unittest` framework; no third-party test packages are required.

## Run validation

```sh
make check
make test
```

`make check` treats COBOL and native C warnings as errors and checks Python syntax. The normal engine build enables GnuCOBOL runtime checks. Each domain integration test creates its own temporary data directory and invokes the real executable. A rejected operation is checked against both report state and journal bytes wherever atomicity is material. Tests never use a live journal.

The sales reconciliation tests verify after each issue and payment that:

- The receivables control balance equals the current outstanding invoice total.
- The inventory control balance equals stock quantity multiplied by standard cost.
- Recognized cost of goods sold equals the standard cost of depleted units.
- The trial balance has equal debit and credit totals.

Tax tests include line-level half-cent rounding and values near the monetary limit. Repeated-SKU tests require aggregated stock demand. Later-posting failures verify that earlier successful postings in the same operation are rolled back. Source attribution regression tests distinguish manual ledger entries from entries owned by invoices, payments and inventory movements.

## Measure compiled code coverage

```sh
python3 tools/coverage.py
```

The coverage tool builds an isolated, unoptimized executable at `build/coverage/meridian`, instrumenting both generated COBOL C and `native/store.c`. It sets `MERIDIAN_ENGINE` for the actual unittest run, then reads execution counters with the matching `gcov` tool. It never replaces the normal `build/meridian` binary. Each invocation clears only the generated `build/coverage` directory before collecting a fresh run.

GnuCOBOL's `--coverage` option enables native compiler instrumentation and emits source mappings from generated C to the original COBOL files. GCC installations need a matching `gcov`; Clang installations need `llvm-cov gcov`. On macOS the tool can locate `llvm-cov` through `xcrun`. Override toolchain commands when necessary:

```sh
python3 tools/coverage.py --cc gcc --gcov gcov
python3 tools/coverage.py --cc clang --gcov 'llvm-cov gcov'
```

The tool exits unsuccessfully if a compiler or report command fails, the tests fail, no tests run, no runtime counters appear, or original source mappings are missing. It still writes reports when test failures permit collection, so uncovered and failing paths remain inspectable.

## Inspect reports

All generated artifacts remain under the ignored `build/coverage` directory:

| Artifact | Purpose |
| --- | --- |
| `index.html` | Per-file percentages and annotated source with covered, uncovered and unmeasured lines |
| `summary.json` | Machine-readable toolchain, test results, per-line counters, branch counters and totals |
| `summary.md` | Readable measured coverage summary |
| `coverage.info` | LCOV format for compatible reporting services |
| `tests.log` | Actual unittest results |
| `build.log`, `gcov.log` | Compiler and source-mapping evidence |
| `gcov/` | Raw annotated gcov reports, separated by compilation unit |
| `*.c`, `*.h`, `*.gcno`, `*.gcda` | Preserved generated C, compile-time metadata and runtime counters |

COBOL percentages count only executable lines mapped to the five original `src/*.cob` files. Data declarations, copybook initialization and generated runtime helper code are excluded from that denominator. Native storage C has a separate percentage. Execution counts include the replay of earlier durable commands, because replay exercises the same business validation and mutation paths as live requests.

Compiler branch coverage is also recorded, but includes generated dispatch, arithmetic and runtime-check control flow. It must not be described as coverage of every COBOL business decision. A covered source line can still contain an uncovered condition. Line coverage alone does not prove accounting correctness or the absence of bugs; the assertions and reconciliation checks establish the tested behavior.

## Measured baseline

A full instrumented run on 13 October 2026 passed all 94 tests in 46.21 seconds with GnuCOBOL 3.2.0, Apple Clang 21.0.0 and `llvm-cov gcov`. The run measured 1,476 of 1,564 executable COBOL source lines (94.37 percent) and 89 of 97 native storage C lines (91.75 percent).

| Original source | Covered executable lines | Line coverage |
| --- | --- | --- |
| `src/main.cob` | 124 / 141 | 87.94% |
| `src/validate.cob` | 31 / 33 | 93.94% |
| `src/ledger.cob` | 311 / 344 | 90.41% |
| `src/inventory.cob` | 322 / 333 | 96.70% |
| `src/sales.cob` | 688 / 713 | 96.49% |
| `native/store.c` | 89 / 97 | 91.75% |

These are results from that compiler and test workload. Run the coverage tool to reproduce a fresh measurement; its reports record the actual toolchain, count, time, uncovered lines and raw execution counters. This baseline does not claim complete branch coverage or coverage of Python and browser code.

## Optional coverage gate

Set a threshold only after examining a measured baseline for the selected compiler and suite:

```sh
python3 tools/coverage.py --fail-under 80
```

This example gates the aggregate percentage of mapped executable COBOL lines. It does not gate native C or compiler branches. There is no default threshold or assumed percentage. Compiler versions can change executable line mappings, so compare reports with their recorded toolchain. For a focused investigation, `--pattern 'test_sales.py'` runs only that suite and reports coverage from that smaller workload.

The coverage run does not instrument Python adapters, browser JavaScript or the external GnuCOBOL runtime library. Failures involving full disks, power loss, inaccessible hardware and every possible system-call error are not all reproducible in normal unit tests. Native storage error-handling gaps remain visible in the report rather than being excluded to inflate coverage.
