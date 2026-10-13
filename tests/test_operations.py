"""End-to-end demo reconciliation and disaster-recovery behavior."""

import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import backup
from tools.backup import restore, snapshot
from tools.client import Client, MeridianError
from tools.demo import seed


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="meridian-operations-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.client = seed(self.root / "original")
        self.backup = self.root / "snapshot.json"

    def test_demo_is_one_event_and_reconciles_subledgers(self):
        self.assertEqual(len(self.client.journal.read_bytes().splitlines()), 2)
        balances = {row[1]: int(row[4]) for row in self.client.execute("ACCOUNTS")["rows"]}
        self.assertEqual(balances["CASH"], 1005000)
        self.assertEqual(balances["AR"], 12980)
        self.assertEqual(balances["INVENTORY"], 58250)
        self.assertEqual(sum(balances.values()), 0)
        stock = self.client.execute("STOCK")["rows"]
        self.assertEqual(sum(int(row[5]) for row in stock), balances["INVENTORY"])
        self.assertIn(["RESULT", "6750"], self.client.execute("SUMMARY")["rows"])

    def test_demo_refuses_to_replace_existing_data(self):
        before = self.client.journal.read_bytes()
        with self.assertRaises(MeridianError):
            seed(self.client.data_dir)
        self.assertEqual(self.client.journal.read_bytes(), before)

    def test_backup_restoration_replays_identical_state(self):
        document = snapshot(self.client.data_dir, self.backup)
        self.assertEqual(document["sha256"], hashlib.sha256(self.client.journal.read_bytes()).hexdigest())
        restored = restore(self.backup, self.root / "restored")
        for report in ["ACCOUNTS", "JOURNAL", "INVOICES", "STOCK", "SUMMARY"]:
            self.assertEqual(restored.execute(report), self.client.execute(report))
        self.assertEqual(self.backup.stat().st_mode & 0o777, 0o600)
        restored.execute("POST|AFTER_RESTORE|20261015|CASH|EQUITY|1|New capital")
        self.assertNotEqual(restored.journal.read_bytes(), self.client.journal.read_bytes())

    def test_restore_and_backup_never_overwrite_existing_paths(self):
        snapshot(self.client.data_dir, self.backup)
        original_backup = self.backup.read_bytes()
        with self.assertRaises(MeridianError):
            snapshot(self.client.data_dir, self.backup)
        with self.assertRaises(MeridianError):
            restore(self.backup, self.client.data_dir)
        self.assertEqual(self.backup.read_bytes(), original_backup)

    def test_backup_checksum_tampering_rejected_before_creating_data(self):
        snapshot(self.client.data_dir, self.backup)
        document = json.loads(self.backup.read_text())
        document["sha256"] = "0" * 64
        self.backup.write_text(json.dumps(document))
        with self.assertRaises(MeridianError):
            restore(self.backup, self.root / "bad")
        self.assertFalse((self.root / "bad").exists())

    def test_valid_envelope_with_corrupt_journal_is_rejected_and_removed(self):
        document = snapshot(self.client.data_dir, self.backup)
        corrupt = self.client.journal.read_bytes().replace(b"Synthetic", b"Corrupted", 1)
        document.update(
            bytes=len(corrupt),
            sha256=hashlib.sha256(corrupt).hexdigest(),
            journal_base64=base64.b64encode(corrupt).decode("ascii"),
        )
        self.backup.write_text(json.dumps(document))
        with self.assertRaises(MeridianError):
            restore(self.backup, self.root / "bad")
        self.assertFalse((self.root / "bad").exists())

    def test_snapshot_of_corrupt_source_is_refused(self):
        self.client.journal.write_bytes(self.client.journal.read_bytes()[:-1])
        with self.assertRaises(MeridianError):
            snapshot(self.client.data_dir, self.backup)
        self.assertFalse(self.backup.exists())

    def test_unsupported_or_malformed_envelopes_are_rejected(self):
        for document in [
            {},
            {"format": "meridian-backup-1"},
            {"format": "meridian-backup-1", "journal_base64": "!not-base64!"},
        ]:
            self.backup.write_text(json.dumps(document))
            with self.assertRaises(MeridianError):
                restore(self.backup, self.root / "bad")
        self.assertFalse((self.root / "bad").exists())

    def test_restore_publication_race_preserves_acknowledged_concurrent_data(self):
        snapshot(self.client.data_dir, self.backup)
        destination = self.root / "raced"
        publish = backup._publish_directory

        def concurrent_publish(staging, final):
            concurrent = Client(final)
            concurrent.execute("ACCOUNT|CONCURRENT|ASSET|Concurrent acknowledged account")
            publish(staging, final)

        with mock.patch.object(backup, "_publish_directory", side_effect=concurrent_publish):
            with self.assertRaises(FileExistsError):
                restore(self.backup, destination)
        concurrent = Client(destination)
        self.assertEqual(concurrent.execute("ACCOUNTS")["rows"][0][1], "CONCURRENT")
        self.assertFalse(list(self.root.glob(".meridian-restore-*")))

    def test_late_restore_sync_failure_preserves_published_dataset(self):
        snapshot(self.client.data_dir, self.backup)
        destination = self.root / "late-sync"
        sync = backup._sync_directory

        def failing_parent_sync(directory):
            if Path(directory) == destination.parent:
                Client(destination).execute("POST|LATE|20261015|CASH|EQUITY|11|Concurrent capital")
                raise OSError("Injected parent sync failure")
            sync(directory)

        with mock.patch.object(backup, "_sync_directory", side_effect=failing_parent_sync):
            with self.assertRaises(OSError):
                restore(self.backup, destination)
        concurrent = Client(destination)
        self.assertEqual(concurrent.execute("JOURNAL")["rows"][-1][1], "LATE")
        self.assertFalse(list(self.root.glob(".meridian-restore-*")))


if __name__ == "__main__":
    unittest.main()
