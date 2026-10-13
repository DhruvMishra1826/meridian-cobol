# Security model

Meridian is for a local operator or a small trusted private network. It is not a multi-tenant financial service. The HTTP server has no user accounts or per-user roles; an authenticated token holder can perform all business commands.

## Controls

* Loopback binding by default; remote binding requires `MERIDIAN_API_TOKEN`.
* Constant-time bearer comparison; tokens stay outside repository files.
* Host/Origin checks on browser requests, strict JSON types, bounded bodies and responses.
* No shell interpolation: commands are passed as subprocess arguments.
* Canonical identifiers, dates and integers; no control/delimiter characters in text fields.
* Journal file opened with `O_NOFOLLOW`, exclusive writer lock and private creation modes.
* CRC-linked history, fail-closed replay, atomic batches, verified backup restoration.
* Console renders external fields as text rather than executable HTML.
* No third-party runtime Python packages; development tools are pinned and update-monitored.

## Deployment requirements

Keep the service behind TLS when used remotely. Do not publish bearer tokens, real journals, backups, or customer information. Do not use shared writable data directories. Use supported Python/compiler releases, a dedicated operating-system account and a trusted local filesystem with working file locks/fsync. POSIX advisory locks protect cooperating processes; an actor with direct write access can modify or delete a dataset.

CRC and backup SHA-256 detect accidental changes, not malicious tampering by someone who controls the file and can recompute checksums. Encrypt confidential backups separately and keep them outside the live dataset directory. Restore into a fresh path and verify reconciliation before switching operations.

## Reporting

Report security issues privately to the repository owner using GitHub's private vulnerability reporting where available. Include an isolated reproducer and affected version; do not include live secrets or customer data. Ordinary reproducible bugs may be reported through repository issues.
