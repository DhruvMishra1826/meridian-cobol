# Architecture and design decisions

## Boundaries

`src/main.cob` handles command parsing, event replay, transaction snapshots and orchestration. `ledger.cob`, `inventory.cob`, and `sales.cob` own accounting, stock and receivables rules respectively. `validate.cob` provides canonical field validation. Shared copybooks define the sole state/command/result contracts.

`native/store.c` supplies a narrow POSIX I/O boundary. It knows about bytes, sequence numbers, CRC chaining, file locks and durability; it does not know about invoices, money or accounts. `tools/client.py` launches the engine with an argument list and no shell. The HTTP server and console consume the same report protocol as the CLI.

## Decision: one journal is the transaction boundary

A stock receipt creates both a movement and a ledger posting. An issued invoice creates several ledger postings and movements. Separate mutable files would require a cross-file commit/recovery protocol. Meridian instead persists the original successful business command as one journal record. Replaying that event deterministically rebuilds all affected subledgers.

Every process holds an exclusive `flock` from before replay until after its mutation is `fsync`ed. Concurrent submissions serialize, so duplicate references and stock availability are checked against the latest committed state. Queries also hold the same lock and see a consistent dataset.

## Decision: fixed-point arithmetic

Prices, totals and payments are integer minor units. Quantities are whole units. Tax is an integer rate in basis points, rounded half up on each line: `(line_net * basis_points + 5000) / 10000`, with intermediate range checks. Individual transactions and invoice totals fit 12 digits; wider working values prevent multiplication/addition overflow before checking the limits. Account balances fit signed 14 digits.

## Decision: explicit posting provenance

Ledger entries record their creating subsystem internally: MANUAL, INVENTORY, INVOICE or PAYMENT. Only manual entries support the general reversal operation. Recognizing ownership from reference suffixes would wrongly protect unrelated manual postings; explicit source attribution avoids that ambiguity. Original entries remain visible after reversal.

## Decision: bounded structures and fail-closed replay

Bounded COBOL tables provide predictable storage and permit whole-state rollback. Every module validates capacities before appending records. Report buffers are 1 MiB, sufficient for the declared collections; overflow is an explicit error rather than a truncated success.

Each journal begins with `MERIDIAN-JOURNAL-1` and has ordered records `8hex_sequence|8hex_chained_crc32|command`. Corrupt headers, invalid sequences, checksum mismatches, invalid commands, control characters, and incomplete final records prevent further operations. CRC is accidental-corruption detection, not cryptographic authenticity. Backups add a SHA-256 envelope, also without making an authentication claim.

## Crash semantics

The native adapter writes a complete record, then calls `fsync` before the engine returns success. Initial file creation also syncs its directory. Ordinary write/sync errors trigger truncation to the pre-operation length. A crash during a write can leave an incomplete tail: startup refuses it, and recovery uses a verified backup. It does not silently discard possibly committed business records.

A caller timeout or connection loss can occur after a commit. Callers must inspect journal references before retrying; references make duplicate business submissions reject safely. Batch commands have one durable record and either acknowledge the entire mutation set or fail without adding it.

## Growth path

Journal replay is linear in dataset history, and writers are serialized. The documented limits deliberately describe the current application. Scaling further would require verified checkpoints/compaction, pagination, schema migrations and integration-preserving credit/refund workflows. A relational adapter could retain the same COBOL business contracts while replacing the journal, but that adapter is not implemented here.
