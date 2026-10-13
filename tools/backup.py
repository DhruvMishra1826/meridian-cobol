"""Locked, checksummed snapshots and verified restoration to a fresh directory."""

import argparse
import base64
import binascii
import ctypes
import fcntl
import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.client import Client, MeridianError

MAX_JOURNAL_BYTES = 32 * 1024 * 1024
MAX_BACKUP_BYTES = 48 * 1024 * 1024


def _sync_directory(directory):
    descriptor = os.open(str(directory), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _publish_directory(staging, destination):
    """Atomically publish without replacing even an empty concurrent directory."""
    library = ctypes.CDLL(None, use_errno=True)
    source_bytes, destination_bytes = os.fsencode(staging), os.fsencode(destination)
    if sys.platform == "darwin":
        operation = library.renamex_np
        operation.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        operation.restype = ctypes.c_int
        status = operation(source_bytes, destination_bytes, 0x00000004)  # RENAME_EXCL
    elif sys.platform.startswith("linux") and hasattr(library, "renameat2"):
        operation = library.renameat2
        operation.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        operation.restype = ctypes.c_int
        status = operation(-100, source_bytes, -100, destination_bytes, 1)  # AT_FDCWD, RENAME_NOREPLACE
    else:
        raise MeridianError("Atomic no-replace restoration requires supported Linux or macOS")
    if status:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(destination))


def snapshot(data_dir, destination):
    client = Client(data_dir)
    client.execute("SUMMARY")  # Refuse to back up an already corrupt history.
    destination = Path(destination)
    if destination.exists():
        raise MeridianError("Backup destination already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(str(client.journal), os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_SH)
        data = stream.read(MAX_JOURNAL_BYTES + 1)
    if len(data) > MAX_JOURNAL_BYTES:
        raise MeridianError("Journal exceeds the backup size limit")
    document = {
        "format": "meridian-backup-1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "journal_base64": base64.b64encode(data).decode("ascii"),
    }
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=destination.parent, prefix=".meridian-backup-", delete=False
        ) as stream:
            temporary = Path(stream.name)
            os.chmod(temporary, 0o600)
            json.dump(document, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        # Link is atomic and refuses an existing destination, even in a race.
        os.link(str(temporary), str(destination))
        _sync_directory(destination.parent)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return document


def restore(source, data_dir):
    source = Path(source)
    if source.stat().st_size > MAX_BACKUP_BYTES:
        raise MeridianError("Backup exceeds the size limit")
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(document, dict) or document.get("format") != "meridian-backup-1":
            raise MeridianError("Unsupported backup format")
        data = base64.b64decode(document["journal_base64"], validate=True)
        if len(data) > MAX_JOURNAL_BYTES or document.get("bytes") != len(data):
            raise MeridianError("Backup length mismatch")
        if hashlib.sha256(data).hexdigest() != document.get("sha256"):
            raise MeridianError("Backup checksum mismatch")
    except (KeyError, ValueError, TypeError, binascii.Error, RecursionError) as exc:
        raise MeridianError("Malformed backup") from exc
    destination = Path(data_dir)
    if destination.exists() or destination.is_symlink():
        raise MeridianError("Restore requires a new, nonexistent data directory")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".meridian-restore-", dir=destination.parent))
    try:
        journal = staging / "journal.dat"
        descriptor = os.open(str(journal), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        client = Client(staging)
        client.execute("SUMMARY")  # Full CRC, sequence and business-event replay.
        _sync_directory(staging)
        _publish_directory(staging, destination)
        _sync_directory(destination.parent)
    finally:
        # Never remove a published destination: another process may have written
        # there, and even a late sync failure must preserve acknowledged records.
        if staging.exists():
            shutil.rmtree(staging)
    return Client(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    create = commands.add_parser("create")
    create.add_argument("--data-dir", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    recover = commands.add_parser("restore")
    recover.add_argument("--input", type=Path, required=True)
    recover.add_argument("--data-dir", type=Path, required=True)
    options = parser.parse_args()
    try:
        if options.operation == "create":
            document = snapshot(options.data_dir, options.output)
            print(f"Backup created: {options.output} ({document['bytes']} journal bytes)")
        else:
            client = restore(options.input, options.data_dir)
            print(f"Verified journal restored: {client.data_dir}")
    except (MeridianError, OSError) as exc:
        parser.exit(2, f"Backup operation failed: {exc}\n")


if __name__ == "__main__":
    main()
