# Contributing

Open an issue describing the business behavior and a minimal synthetic example before a substantial change. Do not include real customer records or credentials.

1. Build with `make` on Linux or macOS.
2. Add an integration regression using a temporary dataset and the real compiled engine.
3. Run `make check test` and the pinned Ruff checks in the README.
4. Preserve integer-minor-unit arithmetic, explicit limits and atomic rollback.
5. Update command contracts and relevant operations documentation.
6. Submit a focused pull request with the problem, resulting behavior and validation evidence.

Keep modules responsible for one domain. Adapters may format and authenticate requests; business rules belong in COBOL. Do not introduce hidden coercion, real-network dependencies into tests, unsafe shell commands, or unverified production claims.

Use meaningful commit messages describing actual changes. Tests should establish externally observable invariants and failure behavior. Format Python using Ruff; COBOL/C warnings are errors, and shared copybooks are versioned contracts.
