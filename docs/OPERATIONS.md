# Operations guide

## Supported deployment model

Meridian is a bounded, single-workspace local application with a durable journal. Its COBOL domain modules run as a process for each command. Python provides a CLI and a small standard-library HTTP console. There are no Python or JavaScript runtime package dependencies.

Use a POSIX system with GnuCOBOL, a C compiler, Make and Python 3.9 or newer. CI exercises Ubuntu with Python 3.11 and 3.13; the container uses Debian Bookworm's GnuCOBOL runtime. The native storage adapter uses POSIX file locking and `fsync`, so native Windows is not a supported target; use a Linux container or WSL environment.

```sh
make all
make check
make test
python3 tools/meridian.py --data-dir ./data/workspace serve
```

The last command opens the console at `http://127.0.0.1:8080`. Keep the process attached during local use; `Ctrl+C` stops it. The browser navigation exposes accounts, trial balances, journal entries, stock, reorder levels, customers, invoices and aging. The transaction desk guides each mutation and displays the exact command before recording it.

## Configuration

| Setting | Default | Purpose |
| --- | --- | --- |
| `MERIDIAN_DATA_DIR` | `~/.local/share/meridian` | Journal directory when `--data-dir` is omitted |
| `MERIDIAN_ENGINE` | Repository `build/meridian` | Optional compiled-engine override |
| `MERIDIAN_API_TOKEN` | Empty on loopback | Bearer token; mandatory for non-loopback bind |
| `MERIDIAN_HTTP_PORT` | `8080` | Docker Compose host loopback port; does not change native server flags |
| `serve --host` | `127.0.0.1` | HTTP bind address |
| `serve --port` | `8080` | HTTP port |

CLI flags take precedence over environment defaults. `.env.example` contains an entry for every application/Compose environment variable; blank `MERIDIAN_ENGINE` selects the compiled repository default. The native server does not automatically read `.env`. Export values into its environment. Docker Compose reads `.env` using its usual behavior.

## Demonstration workspace

```sh
python3 tools/demo.py --data-dir ./demo-data
python3 tools/server.py --data-dir ./demo-data
```

The demo creates an explicitly synthetic, internally balanced scenario in a new empty workspace. It includes capital, stock receipts, invoice issue, payment and a stock adjustment. It is separate from your real operational data. The transaction templates use the demo's `CASH`, `AR`, `INVENTORY`, `AP`, `EQUITY`, `SALES`, `TAX`, `COGS` and `ADJUSTMENT` accounts, `ACME` customer and `WIDGET` item.

## Journal and durability

The data directory is private (`0700`). Its `journal.dat` contains a format header followed by sequenced CRC-protected records. A command holds an exclusive journal lock while replaying, applying and committing an event. A successful response is emitted after durable append. Mutations are validated before persistence, and an atomic batch restores its entire in-memory state on failure.

Queries replay the journal and do not append events. The full replay checks sequence and CRC consistency and runs domain validation. A truncated record, malformed event, checksum mismatch or invalid replay fails closed. CRC detects accidental corruption; it is not a cryptographic signature against an attacker who can rewrite the journal.

Store the journal on a local filesystem with working advisory file locks and `fsync`. Do not share the same workspace across hosts or put it on a filesystem whose locking/durability semantics are uncertain. Back up the complete journal rather than generated reports. A lost HTTP response or client timeout may occur after commit; look up the posting/payment/invoice reference before retrying a mutation.

### Backup and restore

```sh
python3 tools/backup.py create --data-dir ./demo-data --output ./backups/demo.json
python3 tools/backup.py restore --input ./backups/demo.json --data-dir ./restored-data
python3 tools/meridian.py --data-dir ./restored-data report SUMMARY
```

Backup takes a shared journal lock to copy a consistent snapshot and packages it with a SHA-256 integrity envelope. Restore requires a fresh, nonexistent destination and verifies the snapshot before it is installed. Treat backups as sensitive: the envelope contains the full journal, not just aggregate balances. Store copies separately and periodically restore them into a temporary workspace to test recovery.

### Capacity limits

| Record class | Maximum |
| --- | ---: |
| Accounts | 200 |
| Ledger entries | 4096 |
| Inventory items | 500 |
| Stock movements | 4096 |
| Customers | 500 |
| Invoices | 500 |
| Lines per invoice | 30 |
| Payments | 2048 |
| Commands per atomic batch | 64 |

These are explicit working-storage bounds, enforced by the business modules before writes. There is no automatic partitioning, archival or database migration. Workload latency grows with journal replay. Review capacity and latency before committing a real operational workload; create a new workspace through an explicit migration plan rather than editing history.

## Docker Compose

Install Docker with the Compose and Buildx plugins. The conventional `docker-compose.yml` is discovered automatically from the repository root. Verify your toolchain and generate an API token in the shell environment:

```sh
docker compose version
docker buildx version
export MERIDIAN_API_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
docker compose up --build --detach --wait
docker compose ps
```

Open `http://127.0.0.1:8080`, choose **Connection**, and enter the exported token. The image runs as UID/GID 10001, compiles the engine in a separate builder, uses a read-only root filesystem in Compose, and stores the journal in the `meridian-data` named volume. Compose publishes the service only on the host's loopback address. The container's wildcard bind still requires its bearer token.

If port 8080 is in use, set `MERIDIAN_HTTP_PORT` to an available host port before `up`; for example, `export MERIDIAN_HTTP_PORT=8081`, then open `http://127.0.0.1:8081`. The container continues to listen on port 8080. Keep tokens out of command URLs and version-controlled files.

```sh
docker compose logs --tail 100 meridian
docker compose stop
docker compose start
```

`stop` and `down` preserve the named volume. `docker compose down --volumes` removes the journal volume; use it only when intentionally discarding that workspace. A Docker health check calls authenticated `/ready` to verify the executable, storage permissions and valid journal replay. `up --wait` waits for this health check. A bind-mounted data directory must be writable by UID 10001 and private to the intended operator. The Docker build context excludes real `.env` files, virtual environments, `node_modules`, Terraform working directories/state and variable/plan files.

## Health, logs and metrics

Use `/health` for public process liveness and authenticated `/ready` before routing operational traffic. Liveness has a minimal payload and remains alive while an engine/storage fault is being repaired. Readiness returns 503 with a coarse error category and no local path or business data; after recovery it returns 200 on the next request. `/api/health` remains available with its original summary-report response.

```sh
curl 'http://127.0.0.1:8080/health'
curl --header "Authorization: Bearer $MERIDIAN_API_TOKEN" 'http://127.0.0.1:8080/ready'
curl --header "Authorization: Bearer $MERIDIAN_API_TOKEN" 'http://127.0.0.1:8080/metrics'
docker compose logs --follow meridian
```

Request logs use one JSON event per completed request, with a generated request ID, fixed route/method labels, status and elapsed milliseconds. The same ID is returned as `X-Request-ID`. Request/response bodies, query parameters, raw unknown paths, tokens and customer content are excluded. Send standard error to your chosen log collector; configure retention and access in that deployment.

Prometheus-format metrics include request counters, fixed-bucket latency histograms and process uptime. Auth protects metrics whenever a bearer token is configured. The counters are thread-safe and limited to predefined dimensions, so arbitrary customer URLs cannot expand metric cardinality. They reset at process restart and do not represent accounting totals. Protect scraper credentials and use `/ready` rather than a metrics scrape to decide whether journal operations are available. Detailed fields and readiness categories are in [API.md](API.md#health-and-telemetry).

## Network access

For a trusted network or a TLS reverse proxy:

```sh
export MERIDIAN_API_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
python3 tools/meridian.py --data-dir ./data/workspace serve --host 0.0.0.0 --port 8080
```

Keep the bearer token private and use TLS for network transport. A reverse proxy must preserve the original Host header; POST Origin must match it. The built-in server has no role separation, tenancy, audit identity, login flow, rate limiting, request queue limit or TLS termination. It is intended for local/trusted operators rather than an unauthenticated public service.

## Verification and maintenance

`make check` runs COBOL/C syntax checks with warnings treated as errors and compiles Python sources. `make test` exercises state transitions, arithmetic bounds, rejected operations, journal replay, the subprocess boundary and HTTP security. Observability tests prove missing-engine installation recovery, corrupt header/CRC/tail rejection and restoration, storage-permission recovery, log redaction and concurrent metric consistency. CI runs checks on two Python versions and builds/smoke-tests the container. GitHub Actions are pinned to release commit SHAs, and Dependabot checks Python development tools, Actions and Docker updates monthly.

The web console uses packaged HTML, CSS and JavaScript without a CDN. It formats integer amounts with grouping but does not change their values or invent a currency. Filtered tables leave the report unchanged; CSV export downloads all rows returned by the selected report. User-controlled values are inserted as text rather than HTML.

To upgrade, stop the HTTP process, make a consistent journal backup, compile the new version and run the full test suite. Verify the restored copy with `SUMMARY` and key reports before reopening the workspace. The current journal format does not have an automated version migration facility.

## Troubleshooting

| Symptom | Resolution |
| --- | --- |
| “Engine is missing” | Run `make all` or check `MERIDIAN_ENGINE` |
| Connection dialog appears | Enter the server's bearer token for this browser tab |
| POST returns 403 | Supply an Origin matching the exact Host and port; do not use cross-site requests |
| POST returns 422 | Read the engine rejection, verify account/item/customer IDs and posting dates |
| HTTP 503 / invalid journal | Stop mutations, preserve the journal and restore a verified backup; do not truncate failed records |
| Invalid data-directory permission | Check ownership and filesystem support for POSIX permissions |
| Bind fails | Pick an available port; a non-loopback bind also needs a strong token |
| Container exits immediately | Set a token of at least 24 printable ASCII characters with no spaces |
| Docker Compose build cannot find Buildx | Install the Buildx plugin alongside Compose; verify `docker buildx version` |
| `/ready` reports `storage_permission` | Restore owner read/write permissions and directory execute access; Docker data must belong to UID 10001 |
| `/health` is alive but `/ready` fails | Inspect the coarse readiness reason; liveness only checks the HTTP process |
| Amount appears 100 times larger | Values are minor units: `12500` means 125.00 in a two-decimal currency convention |

The full route, response and security contract is documented in [API.md](API.md).
