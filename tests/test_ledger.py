"""Accounting invariants checked through independently launched COBOL processes."""

import random
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tools.client import Client, MeridianError


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="meridian-ledger-")
        self.addCleanup(self.directory.cleanup)
        self.client = Client(self.directory.name)
        self.client.execute(
            "BATCH|ACCOUNT|CASH|ASSET|Cash~ACCOUNT|CAPITAL|EQUITY|Capital"
            "~ACCOUNT|SALES|REVENUE|Sales~ACCOUNT|EXPENSE|EXPENSE|Expenses"
        )

    def reject(self, command):
        before = self.client.journal.read_bytes()
        with self.assertRaises(MeridianError):
            self.client.execute(command)
        self.assertEqual(self.client.journal.read_bytes(), before)

    def balances(self):
        return {row[1]: int(row[4]) for row in self.client.execute("ACCOUNTS")["rows"]}

    def test_capital_income_expense_trial_and_financial_summary(self):
        self.client.execute("POST|CAP1|20261013|CASH|CAPITAL|100000|Initial capital")
        self.client.execute("POST|SALE1|20261013|CASH|SALES|20000|Cash sale")
        self.client.execute("POST|COST1|20261013|EXPENSE|CASH|7000|Operating costs")
        self.assertEqual(
            self.balances(), {"CASH": 113000, "CAPITAL": -100000, "SALES": -20000, "EXPENSE": 7000}
        )
        total = self.client.execute("TRIAL")["rows"][-1]
        self.assertEqual(total, ["TOTAL", "120000", "120000"])
        summary = self.client.execute("SUMMARY")["rows"]
        self.assertIn(["SUMMARY", "REVENUE", "20000"], summary)
        self.assertIn(["SUMMARY", "EXPENSE", "7000"], summary)
        self.assertIn(["RESULT", "13000"], summary)

    def test_reversal_keeps_original_and_rejects_duplicate_reversal(self):
        self.client.execute("POST|P1|20261013|CASH|CAPITAL|251|Capital")
        self.client.execute("REVERSE|P1|R1|20261014|Correction")
        self.assertEqual(self.balances()["CASH"], 0)
        entries = self.client.execute("JOURNAL")["rows"]
        self.assertEqual(entries[0][-1], "R1")
        self.assertEqual(entries[1][3:6], ["CAPITAL", "CASH", "251"])
        self.reject("REVERSE|P1|R2|20261015|Duplicate")

    def test_reversal_cannot_precede_original_or_use_duplicate_reference(self):
        self.client.execute("POST|P1|20261013|CASH|CAPITAL|251|Capital")
        self.reject("REVERSE|P1|R1|20261012|Backdated")
        self.reject("REVERSE|P1|P1|20261014|Reference collision")
        self.reject("REVERSE|UNKNOWN|R1|20261014|Missing posting")

    def test_closing_period_blocks_postings_and_reversals(self):
        self.client.execute("POST|P1|20261013|CASH|CAPITAL|251|Capital")
        self.client.execute("CLOSE|20261013")
        self.reject("POST|P2|20261013|CASH|CAPITAL|251|Closed date")
        self.reject("REVERSE|P1|R1|20261013|Closed reversal")
        self.reject("CLOSE|20261012")
        self.reject("CLOSE|20261013")
        self.client.execute("POST|P2|20261014|CASH|CAPITAL|251|Open period")
        self.assertIn(["PERIOD", "20261013"], self.client.execute("SUMMARY")["rows"])

    def test_amount_account_and_reference_validation(self):
        for amount in ["0", "-1", "+1", "01", "1.00", "1e2", " 1", "1000000000000", "NaN"]:
            with self.subTest(amount=amount):
                self.reject(f"POST|P1|20261013|CASH|CAPITAL|{amount}|Invalid amount")
        self.reject("POST|P1|20261013|MISSING|CAPITAL|1|Unknown account")
        self.reject("POST|P1|20261013|CASH|CASH|1|Same account")
        self.client.execute("POST|P1|20261013|CASH|CAPITAL|1|Valid")
        self.reject("POST|P1|20261013|CASH|CAPITAL|1|Duplicate")

    def test_calendar_and_identifier_validation(self):
        for date in ["20260229", "20261301", "20260431", "00000101", "2026101", "2026-10-13"]:
            with self.subTest(date=date):
                self.reject(f"POST|P1|{date}|CASH|CAPITAL|1|Invalid date")
        self.client.execute("POST|LEAP|20240229|CASH|CAPITAL|1|Valid leap day")
        for identifier in ["lowercase", "A B", "A.B", "../BAD", "X" * 13]:
            self.reject(f"ACCOUNT|{identifier}|ASSET|Invalid ID")
        self.reject("ACCOUNT|VALID|OTHER|Invalid kind")
        self.reject("ACCOUNT|CASH|ASSET|Duplicate")
        self.reject("ACCOUNT|VALID|ASSET| Leading space")

    def test_maximum_post_and_balance_overflow_prevented(self):
        for chunk in range(2):
            commands = [
                f"POST|LIMIT_{chunk}_{i}|20261013|CASH|CAPITAL|999999999999|Large post" for i in range(50)
            ]
            self.client.execute("BATCH|" + "~".join(commands))
        self.assertEqual(self.balances()["CASH"], 99999999999900)
        self.reject("POST|OVER|20261013|CASH|CAPITAL|100|Overflow")
        self.assertEqual(self.balances()["CASH"], 99999999999900)

    def test_randomized_transfers_preserve_total_zero_and_expected_balances(self):
        rng = random.Random(1826)
        expected = dict.fromkeys(["CASH", "CAPITAL", "SALES", "EXPENSE"], 0)
        commands = []
        for i in range(50):
            debit, credit = rng.sample(list(expected), 2)
            amount = rng.randrange(1, 50000)
            commands.append(f"POST|RANDOM_{i}|20261013|{debit}|{credit}|{amount}|Randomized invariant")
            expected[debit] += amount
            expected[credit] -= amount
        self.client.execute("BATCH|" + "~".join(commands))
        actual = self.balances()
        self.assertEqual(actual, expected)
        self.assertEqual(sum(actual.values()), 0)
        total = self.client.execute("TRIAL")["rows"][-1]
        self.assertEqual(total[1], total[2])

    def test_statement_filters_activity_and_reports_balance(self):
        self.client.execute("POST|P1|20261013|CASH|CAPITAL|100|Capital")
        self.client.execute("POST|P2|20261013|EXPENSE|SALES|50|Accrual")
        rows = self.client.execute("STATEMENT|CASH")["rows"]
        self.assertEqual([row[1] for row in rows if row[0] == "ENTRY"], ["P1"])
        self.assertEqual(rows[-1], ["BALANCE", "CASH", "100"])
        self.reject("STATEMENT|MISSING")

    def test_concurrent_writers_do_not_lose_updates(self):
        def write(i):
            return Client(self.directory.name).execute(
                f"POST|THREAD_{i}|20261013|CASH|CAPITAL|17|Concurrent writer"
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(write, range(32)))
        self.assertTrue(all(item["ok"] for item in results))
        self.assertEqual(self.balances()["CASH"], 32 * 17)
        self.assertEqual(len(self.client.execute("JOURNAL")["rows"]), 32)

    def test_concurrent_duplicate_reference_is_accepted_once(self):
        def write(_):
            try:
                Client(self.directory.name).execute("POST|ONCE|20261013|CASH|CAPITAL|101|Idempotency")
                return True
            except MeridianError:
                return False

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(write, range(16)))
        self.assertEqual(sum(results), 1)
        self.assertEqual(self.balances()["CASH"], 101)

    def test_account_capacity_is_enforced(self):
        for start in range(0, 196, 50):
            commands = [f"ACCOUNT|A{i}|ASSET|Account {i}" for i in range(start, min(start + 50, 196))]
            self.client.execute("BATCH|" + "~".join(commands))
        self.assertEqual(len(self.client.execute("ACCOUNTS")["rows"]), 200)
        self.reject("ACCOUNT|EXTRA|ASSET|Beyond capacity")


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="meridian-journal-")
        self.addCleanup(self.directory.cleanup)
        self.client = Client(self.directory.name)
        self.client.execute("ACCOUNT|CASH|ASSET|Cash")

    def test_batch_rollback_and_single_durable_event(self):
        before = self.client.journal.read_bytes()
        with self.assertRaises(MeridianError):
            self.client.execute("BATCH|ACCOUNT|A1|ASSET|First~ACCOUNT|CASH|ASSET|Duplicate")
        self.assertEqual(self.client.journal.read_bytes(), before)
        self.assertEqual(len(self.client.execute("ACCOUNTS")["rows"]), 1)
        self.client.execute("BATCH|ACCOUNT|A1|ASSET|First~ACCOUNT|A2|ASSET|Second")
        self.assertEqual(len(self.client.journal.read_bytes().splitlines()), 3)
        self.assertEqual(len(self.client.execute("ACCOUNTS")["rows"]), 3)

    def test_batch_rejects_empty_query_nested_or_too_many_operations(self):
        for command in [
            "BATCH|",
            "BATCH|ACCOUNTS",
            "BATCH|ACCOUNT|A|ASSET|A~",
            "BATCH|BATCH|ACCOUNT|A|ASSET|A",
            "BATCH|" + "~".join(f"ACCOUNT|A{i}|ASSET|Account" for i in range(65)),
        ]:
            before = self.client.journal.read_bytes()
            with self.assertRaises(MeridianError):
                self.client.execute(command)
            self.assertEqual(self.client.journal.read_bytes(), before)

    def test_corruption_header_checksum_sequence_and_partial_tail_fail_closed(self):
        original = self.client.journal.read_bytes()
        corruptions = [
            original.replace(b"MERIDIAN", b"MERIXIAN", 1),
            original.replace(b"Cash", b"Cazh", 1),
            original.replace(b"00000001|", b"00000002|", 1),
            original.replace(b"00000001|", b" 0000001|", 1),
            original[:-1],
            original + b"partial",
            original + b"\n",
        ]
        for corrupted in corruptions:
            with self.subTest(corrupted=corrupted[-30:]):
                self.client.journal.write_bytes(corrupted)
                with self.assertRaises(MeridianError) as caught:
                    self.client.execute("ACCOUNTS")
                self.assertEqual(caught.exception.returncode, 3)
                self.assertEqual(self.client.journal.read_bytes(), corrupted)
        self.client.journal.write_bytes(original)
        self.assertEqual(self.client.execute("ACCOUNTS")["rows"][0][1], "CASH")

    def test_query_does_not_write_and_files_are_private(self):
        original = self.client.journal.read_bytes()
        self.client.execute("ACCOUNTS")
        self.assertEqual(self.client.journal.read_bytes(), original)
        self.assertEqual(self.client.journal.stat().st_mode & 0o777, 0o600)
        self.assertEqual(Path(self.directory.name).stat().st_mode & 0o777, 0o700)

    def test_journal_symlink_rejected_without_modifying_target(self):
        target = Path(self.directory.name) / "target"
        target.write_bytes(b"do not modify\n")
        self.client.journal.unlink()
        self.client.journal.symlink_to(target)
        with self.assertRaises(MeridianError):
            Client(self.directory.name)
        with self.assertRaises(MeridianError):
            self.client.execute("ACCOUNTS")
        self.assertEqual(target.read_bytes(), b"do not modify\n")


if __name__ == "__main__":
    unittest.main()
