"""Inventory integration checks against the compiled COBOL engine."""

import tempfile
import unittest
from pathlib import Path

from tools.client import Client, MeridianError


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="meridian-inventory-")
        self.addCleanup(self.directory.cleanup)
        self.client = Client(self.directory.name)
        for command in (
            "ACCOUNT|INV|ASSET|Inventory",
            "ACCOUNT|AP|LIABILITY|Trade payables",
            "ACCOUNT|VAR|EXPENSE|Inventory variance",
            "ACCOUNT|CASH|ASSET|Cash",
            "ITEM|WIDGET|Precision widget|1250|10",
        ):
            self.client.execute(command)

    def stock(self):
        return self.client.execute("STOCK")["rows"]

    def receive(self, reference="RCV1", quantity=20, date="20261013", memo="Receipt"):
        return self.client.execute(f"RECEIVE|{reference}|{date}|WIDGET|{quantity}|INV|AP|{memo}")

    def reject_without_changes(self, command, error_pattern=None):
        before_stock = self.stock()
        before_movements = self.client.execute("MOVEMENTS")["rows"]
        before_journal = Path(self.client.journal).read_bytes()
        rejection = (
            self.assertRaisesRegex(MeridianError, error_pattern)
            if error_pattern
            else self.assertRaises(MeridianError)
        )
        with rejection:
            self.client.execute(command)
        self.assertEqual(self.stock(), before_stock)
        self.assertEqual(self.client.execute("MOVEMENTS")["rows"], before_movements)
        self.assertEqual(Path(self.client.journal).read_bytes(), before_journal)

    def test_receipt_records_fixed_cost_value_and_audit_movement(self):
        self.receive()
        self.assertEqual(self.stock(), [["STOCK", "WIDGET", "Precision widget", "20", "1250", "25000", "10"]])
        self.assertEqual(
            self.client.execute("MOVEMENTS")["rows"],
            [["MOVEMENT", "RCV1", "20261013", "WIDGET", "20", "Receipt"]],
        )
        self.assertEqual(
            self.client.execute("JOURNAL")["rows"],
            [["ENTRY", "RCV1", "20261013", "INV", "AP", "25000", "Receipt", ""]],
        )
        balances = {row[1]: row[3:5] for row in self.client.execute("TRIAL")["rows"] if row[0] == "TRIAL"}
        self.assertEqual(balances["INV"], ["25000", "0"])
        self.assertEqual(balances["AP"], ["0", "25000"])
        # A new process reconstructs the same stock solely from durable history.
        reopened = Client(self.directory.name)
        self.assertEqual(reopened.execute("STOCK")["rows"], self.stock())

    def test_positive_and_negative_adjustments_preserve_cost(self):
        self.receive(quantity=20)
        self.client.execute("ADJUST|COUNT1|20261013|WIDGET|-7|INV|VAR|Count shortage")
        self.client.execute("ADJUST|COUNT2|20261013|WIDGET|3|INV|VAR|Recovered units")
        self.assertEqual(self.stock()[0][3:6], ["16", "1250", "20000"])
        movements = self.client.execute("MOVEMENTS")["rows"]
        self.assertEqual([row[4] for row in movements], ["20", "-7", "3"])
        entries = self.client.execute("JOURNAL")["rows"]
        self.assertEqual(entries[1][3:6], ["VAR", "INV", "8750"])
        self.assertEqual(entries[2][3:6], ["INV", "VAR", "3750"])
        balances = {row[1]: row[3:5] for row in self.client.execute("TRIAL")["rows"] if row[0] == "TRIAL"}
        self.assertEqual(balances["INV"], ["20000", "0"])
        self.assertEqual(balances["VAR"], ["5000", "0"])
        self.reject_without_changes("ITEM|WIDGET|New cost|9999|10")

    def test_reorder_shortfall_tracks_stock(self):
        self.assertEqual(
            self.client.execute("REORDER")["rows"],
            [["REORDER", "WIDGET", "Precision widget", "0", "10", "10"]],
        )
        self.receive(quantity=10)
        self.assertEqual(self.client.execute("REORDER")["rows"], [])
        self.client.execute("ADJUST|COUNT1|20261013|WIDGET|-3|INV|VAR|Count")
        self.assertEqual(self.client.execute("REORDER")["rows"][0][-3:], ["7", "10", "3"])

    def test_underflow_and_failed_ledger_posts_are_atomic(self):
        self.receive(quantity=2)
        for command in (
            "ADJUST|BAD1|20261013|WIDGET|-3|INV|VAR|Shortage",
            "RECEIVE|BAD2|20261013|WIDGET|1|MISSING|AP|Unknown account",
            "RECEIVE|BAD3|20261013|WIDGET|1|INV|INV|Same account",
            "RECEIVE|BAD4|20261013|UNKNOWN|1|INV|AP|Unknown item",
        ):
            with self.subTest(command=command):
                self.reject_without_changes(command)

    def test_inventory_account_must_be_an_asset_for_both_movement_types(self):
        self.client.execute("ACCOUNT|REV|REVENUE|Revenue")
        self.receive(quantity=2)
        for command in (
            "RECEIVE|BAD1|20261013|WIDGET|1|REV|AP|Wrong inventory kind",
            "ADJUST|BAD2|20261013|WIDGET|-1|REV|VAR|Wrong inventory kind",
            "ADJUST|BAD3|20261013|WIDGET|1|AP|VAR|Wrong inventory kind",
        ):
            with self.subTest(command=command):
                self.reject_without_changes(command, "Inventory account must have kind ASSET")

    def test_inventory_movement_posting_cannot_be_reversed(self):
        self.receive()
        self.reject_without_changes("REVERSE|RCV1|REVERSAL|20261013|Correction")
        self.client.execute("ADJUST|CORRECTION|20261013|WIDGET|-2|INV|VAR|Compensating count")
        self.assertEqual(self.stock()[0][3:6], ["18", "1250", "22500"])

    def test_references_cannot_be_reused_across_movements_or_ledger(self):
        self.receive()
        self.reject_without_changes("RECEIVE|RCV1|20261013|WIDGET|1|INV|AP|Duplicate")
        self.reject_without_changes("ADJUST|RCV1|20261013|WIDGET|-1|INV|VAR|Duplicate")
        self.client.execute("POST|MANUAL|20261013|CASH|AP|1|Prior posting")
        self.reject_without_changes("RECEIVE|MANUAL|20261013|WIDGET|1|INV|AP|Collision")

    def test_quantity_limit_and_value_limit_use_exact_integer_arithmetic(self):
        self.client.execute("ITEM|BULK|Bulk component|1|0")
        self.client.execute("RECEIVE|BULK1|20261013|BULK|999999999|INV|AP|Maximum units")
        self.assertEqual(self.stock()[1][3:6], ["999999999", "1", "999999999"])
        self.reject_without_changes("RECEIVE|BULK2|20261013|BULK|1|INV|AP|Overflow")
        self.client.execute("ITEM|COSTLY|High value component|9999999999|1")
        self.client.execute("RECEIVE|COST1|20261013|COSTLY|100|INV|AP|Within value bound")
        self.assertEqual(self.stock()[2][3:6], ["100", "9999999999", "999999999900"])
        self.reject_without_changes("RECEIVE|COST2|20261013|COSTLY|1|INV|AP|Value overflow")
        self.reject_without_changes("RECEIVE|COST3|20261013|COSTLY|1000|INV|AP|Posting overflow")

    def test_malformed_integer_inputs_never_mutate_stock(self):
        self.receive(quantity=20)
        for quantity in ("0", "-0", "+1", "01", "-01", "1.5", "1e2", "--1", "1000000000", "-1000000000"):
            with self.subTest(quantity=quantity):
                self.reject_without_changes(f"ADJUST|BAD|20261013|WIDGET|{quantity}|INV|VAR|Bad quantity")
        for quantity in ("0", "-1", "+1", "01", "1.5", "1000000000"):
            with self.subTest(receive_quantity=quantity):
                self.reject_without_changes(f"RECEIVE|BAD|20261013|WIDGET|{quantity}|INV|AP|Bad quantity")

    def test_item_validation_and_movement_field_lengths(self):
        for command in (
            "ITEM|bad|Lowercase id|1|0",
            "ITEM|THIS_IDENTIFIER_IS_LONG|Long id|1|0",
            "ITEM|NEW||1|0",
            "ITEM|NEW|Zero cost|0|0",
            "ITEM|NEW|Cost overflow|10000000000|0",
            "ITEM|NEW|Fractional cost|1.25|0",
            "ITEM|NEW|Bad reorder|1|-1",
            "ITEM|NEW|Too much reorder|1|1000000000",
            "ITEM|NEW|Missing reorder|1",
            "RECEIVE|BAD|20260230|WIDGET|1|INV|AP|Invalid date",
            "RECEIVE|BAD|20261013|WIDGET|1|INV|AP|" + "x" * 81,
            "RECEIVE|BAD|20261013|WIDGET|1|INV|AP|",
            "RECEIVE|BAD|20261013|WIDGET|1|INV|AP|Memo|Extra",
            "STOCK|Extra",
            "MOVEMENTS|Extra",
            "REORDER|Extra",
        ):
            with self.subTest(command=command):
                self.reject_without_changes(command)
        self.client.execute("ITEM|EXACT|" + "n" * 80 + "|1|999999999")
        self.receive(reference="R" * 32, quantity=1, memo="m" * 80)
        self.assertEqual(len(self.client.execute("MOVEMENTS")["rows"][0][-1]), 80)

    def test_closed_period_failure_does_not_consume_reference(self):
        self.client.execute("CLOSE|20261012")
        self.reject_without_changes("RECEIVE|RETRY|20261012|WIDGET|1|INV|AP|Closed period")
        self.receive(reference="RETRY", quantity=1)
        self.assertEqual(self.stock()[0][3], "1")

    def test_deterministic_adjustment_sequence_conserves_units_and_value(self):
        self.receive(quantity=100)
        expected = 100
        for index, change in enumerate((-13, 7, -21, 35, -80, 19, -12, 3)):
            expected += change
            self.client.execute(f"ADJUST|COUNT_{index}|20261013|WIDGET|{change}|INV|VAR|Cycle count {index}")
            row = self.stock()[0]
            self.assertEqual(int(row[3]), expected)
            self.assertEqual(int(row[5]), expected * 1250)
        self.assertEqual(sum(int(row[4]) for row in self.client.execute("MOVEMENTS")["rows"]), expected)

    def test_queries_do_not_append_to_history(self):
        self.receive()
        before = Path(self.client.journal).read_bytes()
        for report in ("STOCK", "MOVEMENTS", "REORDER"):
            self.client.execute(report)
        self.assertEqual(Path(self.client.journal).read_bytes(), before)

    def test_item_capacity_rejects_overflow_without_overwriting_last_item(self):
        commands = [f"ITEM|SKU{index}|Component {index}|1|0" for index in range(499)]
        for start in range(0, len(commands), 64):
            self.client.execute("BATCH|" + "~".join(commands[start : start + 64]))
        rows = self.stock()
        self.assertEqual(len(rows), 500)
        self.assertEqual(rows[-1][1:3], ["SKU498", "Component 498"])
        self.reject_without_changes("ITEM|OVERFLOW|Capacity exceeded|1|0")

    def test_movement_capacity_preserves_complete_audit_report(self):
        for start in range(0, 4096, 64):
            commands = [
                f"RECEIVE|MAX{index}|20261013|WIDGET|1|INV|AP|R" for index in range(start, start + 64)
            ]
            self.client.execute("BATCH|" + "~".join(commands))
        self.assertEqual(self.stock()[0][3:6], ["4096", "1250", "5120000"])
        rows = self.client.execute("MOVEMENTS")["rows"]
        self.assertEqual(len(rows), 4096)
        self.assertEqual(rows[-1], ["MOVEMENT", "MAX4095", "20261013", "WIDGET", "1", "R"])
        before = Path(self.client.journal).read_bytes()
        with self.assertRaisesRegex(MeridianError, "Movement capacity reached"):
            self.receive(reference="OVERFLOW", quantity=1)
        self.assertEqual(Path(self.client.journal).read_bytes(), before)
        self.assertEqual(self.stock()[0][3], "4096")


if __name__ == "__main__":
    unittest.main()
