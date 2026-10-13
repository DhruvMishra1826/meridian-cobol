# Command and HTTP API

Meridian has one business interface: a validated command executed by the COBOL engine. The CLI and HTTP server translate transport formats; they do not calculate ledger balances, stock values, tax, invoice totals or aging.

## Values and conventions

| Value | Representation |
| --- | --- |
| Money | Integer minor units, such as `12500` for 125.00; a workspace uses one currency convention |
| Quantity | Integer stock units; adjustments may be negative |
| Date | Valid Gregorian `YYYYMMDD` |
| Identifier | Uppercase ASCII letters, digits, `_` and `-` |
| Text | Names/memos without `|`, `~`, newlines or control characters |
| Tax | Integer basis points; `1000` is 10%, with each line rounded to the nearest minor unit |

Account, SKU and customer IDs are at most 12 characters; invoice IDs are at most 24; journal, movement and payment references are at most 32. Business modules validate their own field sizes before storing values. See [engine contracts](INTERFACE.md), [inventory](INVENTORY.md), and [sales](SALES.md) for domain constraints.

## CLI

```sh
python3 tools/meridian.py --data-dir ./data/example command 'ACCOUNT|CASH|ASSET|Operating cash'
python3 tools/meridian.py --data-dir ./data/example --format json report ACCOUNTS
python3 tools/meridian.py --data-dir ./data/example --format csv report JOURNAL
python3 tools/meridian.py --data-dir ./data/example report STATEMENT CASH
python3 tools/meridian.py --data-dir ./data/example report AGING 20261013
```

All monetary values remain integer minor units in text, JSON and CSV. CLI success exits 0; invalid input or a rejected operation exits 2. An interrupted CLI exits 130. Error JSON is written to standard error when `--format json` is selected.

The default data directory is `~/.local/share/meridian`. `MERIDIAN_DATA_DIR` overrides it; `--data-dir` takes precedence. `MERIDIAN_ENGINE` can select an alternative compiled binary; an empty or whitespace-only value uses the repository default. `Client(data_dir, engine=...)` explicitly overrides that environment variable.

### Atomic command files

```text
# bootstrap.txt
ACCOUNT|CASH|ASSET|Operating cash
ACCOUNT|EQUITY|EQUITY|Owner equity
POST|CAPITAL_001|20261013|CASH|EQUITY|100000|Opening capital
```

```sh
python3 tools/meridian.py --data-dir ./data/example batch bootstrap.txt
```

Blank lines and lines beginning with `#` after indentation are ignored. The CLI translates up to 64 commands to `BATCH|command~command`. The combined UTF-8 command must fit within 4096 bytes; batch files are limited to 16384 bytes. Nested batches and `~` within individual commands are rejected. The engine accepts mutation commands in a batch and rejects report commands. A failed operation rejects the entire batch; a successful batch is one durable journal event.

## Native process protocol

```text
build/meridian JOURNAL_PATH PIPE_COMMAND
```

The data directory must exist. The Python client creates it with owner-only `0700` permissions. The compiled engine opens and locks the journal, validates and replays history, applies the requested operation and appends successful mutations. It returns:

```text
OK|Human-readable message
RECORD-TYPE|field|field
```

or:

```text
ERROR|Reason for rejection
```

Native exit codes are 0 for success, 2 for a business/input rejection and 3 for journal integrity or storage failure. The client invokes the process with an argument list and `shell=False`, rejects commands larger than 4096 UTF-8 bytes and prohibits control characters. A 20-second process timeout returns an error. If a mutation times out or the connection is lost, query the relevant reference before retrying: the request may already have committed.

## HTTP routes

Start a local server:

```sh
python3 tools/meridian.py --data-dir ./data/example serve --host 127.0.0.1 --port 8080
```

Open `http://127.0.0.1:8080`. The console uses the same routes described here.

| Method and route | Behavior |
| --- | --- |
| `GET /health` | Public minimal process liveness; does not access the engine or journal |
| `GET /ready` | Authenticated readiness check of executable, storage permissions and journal replay |
| `GET /metrics` | Authenticated Prometheus counters, latency histograms and process uptime |
| `GET /api/health` | Replays the journal and executes `SUMMARY`; detects an unusable engine or invalid history |
| `GET /api/report?command=...` | Executes an allowed read-only report |
| `POST /api/command` | Executes one command, including an atomic `BATCH` |
| `GET /`, `/index.html`, `/app.js`, `/style.css`, `/favicon.svg` | Serves the packaged console assets |

The console loads packaged ES modules at `/api.js`, `/catalog.js`, `/dom.js`, `/forms.js`, `/navigation.js`, `/operations.js`, `/reports.js` and `/state.js`. Static routes use an exact asset allowlist; they do not map arbitrary URL paths to files.

The server exposes no filesystem path, backup, deletion or engine configuration endpoint. Report routes allow `ACCOUNTS`, `TRIAL`, `JOURNAL`, `STATEMENT`, `SUMMARY`, `STOCK`, `MOVEMENTS`, `REORDER`, `CUSTOMERS`, `INVOICES`, `INVOICE-SHOW` and `AGING`. `STATEMENT`, `INVOICE-SHOW` and `AGING` require one argument; other reports take no arguments.

### Request examples

```sh
curl 'http://127.0.0.1:8080/api/report?command=STOCK'
curl 'http://127.0.0.1:8080/api/report?command=STATEMENT%7CCASH'

curl --request POST 'http://127.0.0.1:8080/api/command' \
  --header 'Origin: http://127.0.0.1:8080' \
  --header 'Content-Type: application/json' \
  --data '{"command":"ACCOUNT|CASH|ASSET|Operating cash"}'
```

POST requires one JSON field, `command`, with a string value. Bodies must have `Content-Type: application/json` and one valid `Content-Length`, must not use `Transfer-Encoding`, and may not exceed 4096 bytes. This body limit includes JSON syntax, so the maximum HTTP command is slightly smaller than the native command limit. Duplicate JSON fields and extra fields are rejected.

### Response

```json
{
  "ok": true,
  "message": "Current financial summary in natural account signs",
  "rows": [
    ["SUMMARY", "ASSET", "0"],
    ["SUMMARY", "LIABILITY", "0"],
    ["SUMMARY", "EQUITY", "0"],
    ["SUMMARY", "REVENUE", "0"],
    ["SUMMARY", "EXPENSE", "0"],
    ["RESULT", "0"],
    ["PERIOD", "00000000"],
    ["COUNTS", "0", "0", "0", "0", "0"]
  ]
}
```

All business-report row fields are strings. Business API errors have `{"ok": false, "message": "...", "rows": []}`. Probe responses use the schemas below. No CORS permission is sent. Responses disable caching, include a restrictive content security policy and return a server-generated `X-Request-ID` for log correlation. A supplied request ID is not reused.

| HTTP status | Meaning |
| --- | --- |
| `200` | Operation/report completed |
| `400` | Malformed JSON/request or unsupported transfer encoding |
| `401` | Missing/incorrect bearer token |
| `403` | Disallowed Host/Origin, cross-site POST or preflight |
| `404` | Unknown route |
| `411` | Invalid/missing Content-Length |
| `413` | Body exceeds the limit |
| `415` | Unsupported content type |
| `422` | Command/report validation or business rejection |
| `503` | Engine startup, timeout, storage or journal integrity failure |

### Authentication and origins

A loopback bind accepts only loopback Host headers matching its port. Every POST, including local requests, requires an `Origin` matching the Host and rejects a cross-site `Sec-Fetch-Site` value. Read-only GET requests never accept mutation commands.

Set `MERIDIAN_API_TOKEN` to at least 24 printable ASCII characters without spaces to require bearer authentication. A non-loopback bind requires this token at startup. All `/api/` routes, `/ready` and `/metrics` then require `Authorization: Bearer TOKEN`; `/health` and static assets remain accessible. The token is compared in constant time and held only in the console tab's memory. Do not put it in a URL. Host checks apply to public and authenticated routes alike.

The non-loopback server accepts a matching `http` or `https` Origin, allowing a TLS reverse proxy to preserve the original Host header. The built-in server does not terminate TLS, enforce roles, rate-limit requests or offer multi-tenant isolation.

## Health and telemetry

`/health` returns HTTP 200 with `{"ok": true, "status": "alive"}` while the HTTP process handles requests. It reveals no balances, records, engine path or storage state. Liveness remains successful if the journal is corrupt or the engine is missing; deployment tooling should check readiness separately.

`/ready` returns HTTP 200 with `{"ok": true, "status": "ready"}` after validating permissions and executing `SUMMARY`. Failure returns HTTP 503 with a coarse reason:

```json
{"ok": false, "status": "not_ready", "reason": "journal_corrupt"}
```

| Readiness reason | Meaning |
| --- | --- |
| `missing_engine` | The configured executable is absent |
| `engine_unavailable` | The executable cannot run or its response is invalid |
| `engine_timeout` | The engine exceeded its 20-second limit |
| `storage_permission` | Journal/directory lacks required owner permissions or filesystem access |
| `storage_unavailable` | Storage cannot be inspected/opened/locked or a durability error occurred |
| `journal_corrupt` | Invalid header, incomplete tail, checksum/sequence error or invalid replay |

The readiness payload contains neither filesystem paths nor exception details. A fresh workspace may initialize its journal header during the first probe; readiness does not append a business event. Repairing the executable, restoring a valid journal or correcting permissions allows the next probe to recover without restarting the server. `/api/health` retains its original report payload for existing clients.

```sh
curl 'http://127.0.0.1:8080/health'
curl --header "Authorization: Bearer $MERIDIAN_API_TOKEN" 'http://127.0.0.1:8080/ready'
curl --header "Authorization: Bearer $MERIDIAN_API_TOKEN" 'http://127.0.0.1:8080/metrics'
```

`/metrics` serves Prometheus text format 0.0.4:

- `meridian_http_requests_total`: completed requests labeled by fixed route, method and status.
- `meridian_http_request_duration_seconds`: latency histogram with 0.005, 0.025, 0.1, 0.5, 1, 5, 20 and 60-second buckets, plus `+Inf`, count and sum.
- `meridian_process_uptime_seconds`: HTTP server uptime.

Known API/probe routes retain their names; all packaged assets use the `static` label and unknown targets use `unmatched`. Methods/statuses also collapse to fixed sets. Labels never contain request IDs, customer IDs, raw paths, query parameters, tokens or commands. One lock protects counters and histogram updates; snapshots are copied before serialization. Counters reset on process restart, are not durable business statistics, and the scrape includes requests completed before its own response.

Each completed request emits one JSON event through Python's standard logging module to standard error. The fixed fields are UTC `timestamp`, `event`, generated `request_id`, normalized `method`, fixed `route`, numeric `status` and `duration_ms`. Duration includes request processing and any engine work. Logs contain no headers, bodies, raw URLs, response messages, customer content or local paths. Status 0 indicates a request whose connection ended before a response was sent.

## Report row schemas

Fields below follow the first record-type column. A report can return multiple record types.

| Record type | Fields in order |
| --- | --- |
| `ACCOUNT` | ID, account class, name, debit-minus-credit balance |
| `ENTRY` | Reference, date, debit account, credit account, amount, memo, reversal reference |
| `TRIAL` | Account ID, name, debit balance, credit balance |
| `TOTAL` | Total debit balances, total credit balances |
| `BALANCE` | Account ID, current debit-minus-credit balance |
| `SUMMARY` | Account class, balance in that class's natural sign |
| `RESULT` | Net income: revenue minus expenses |
| `PERIOD` | Closed-through date; `00000000` before the first close |
| `COUNTS` | Accounts, ledger entries, items, customers, invoices |
| `STOCK` | SKU, name, quantity, standard cost, stock value, reorder point |
| `MOVEMENT` | Reference, date, SKU, signed quantity, memo |
| `REORDER` | SKU, name, quantity, reorder point, shortfall |
| `CUSTOMER` | Customer ID, name, email |
| `INVOICE` | Invoice ID, customer ID, date, due date, status, net, tax, total, paid, outstanding, line count |
| `LINE` | Ordinal, SKU, quantity, unit price, tax basis points, net, tax |
| `PAYMENT` | Reference, date, amount |
| `AGE` | Customer ID, invoice ID, due date, overdue days, bucket, outstanding |
| `AGE-TOTAL` | Current, 1–30, 31–60, 61–90, over 90 outstanding, open invoice count |

`AGING` reports current unpaid balances classified against the requested as-of date. It does not reconstruct historical payment state. `ACCOUNT` balances are debit minus credit; `SUMMARY` changes the sign for liability, equity and revenue presentation. Browser and CLI CSV exports prefix spreadsheet formula markers in text fields with an apostrophe; signed integer amounts are preserved. Use JSON when you need unchanged text fields for machine interchange.
