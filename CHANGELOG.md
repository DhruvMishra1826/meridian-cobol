# Changelog

## 1.1.0 — 2026-10-14

* Added protected readiness and Prometheus metrics endpoints, bounded request counters, and structured HTTP completion logs.
* Split the operations console into focused browser modules and added full invoice/payment, report, CSV and mobile browser regressions.
* Added discoverable pytest execution, JUnit reports, Python coverage, Mypy checks, hashed Python dependency exports and dependency audits in CI.
* Renamed the Compose manifest to `docker-compose.yml` and documented alternate loopback ports and build prerequisites.
* Added a pinned Terraform deployment with loopback HTTP publication, a non-root container, protected journal storage, validation tests and a synthetic deployment smoke check.
* Corrected CLI report examples and documented runtime, development tooling and operational limits separately.

## 1.0.0 — 2026-10-13

Initial application release:

* COBOL ledger, inventory and receivables engine with integer-cent accounting.
* Atomic invoice issue, stock movements, payment reconciliation and batch commands.
* Durable locked journal, checksum validation, backup/restore and recovery checks.
* CLI, authenticated local/private HTTP API and browser operations console.
* Compiled-engine, concurrency, capacity, corruption, HTTP and disaster-recovery tests.
* Reproducible builds, pinned development tooling, CI and container packaging.
