"""Sales integration tests exercise the real compiled engine and durable journal."""

import tempfile
import unittest
from pathlib import Path

from tools.client import Client, MeridianError


class SalesTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="meridian-sales-")
        self.addCleanup(self.directory.cleanup)
        self.client = Client(self.directory.name)
        for command in (
            "ACCOUNT|CASH|ASSET|Cash",
            "ACCOUNT|AR|ASSET|Trade receivables",
            "ACCOUNT|OTHERAR|ASSET|Other receivables",
            "ACCOUNT|INV|ASSET|Inventory",
            "ACCOUNT|AP|LIABILITY|Trade payables",
            "ACCOUNT|TAX|LIABILITY|Sales tax payable",
            "ACCOUNT|REV|REVENUE|Sales revenue",
            "ACCOUNT|COGS|EXPENSE|Cost of goods sold",
            "ITEM|WIDGET|Precision widget|125|10",
            "RECEIVE|RECEIPT|20260101|WIDGET|50|INV|AP|Opening receipt",
            "CUSTOMER|ACME|Acme Manufacturing|billing@example.com",
        ):
            self.client.execute(command)

    def draft(self, identifier="INV1", date="20260115", due="20260214"):
        self.client.execute(f"INVOICE|{identifier}|ACME|{date}|{due}")

    def line(self, identifier="INV1", quantity=2, price=199, tax=750):
        self.client.execute(f"LINE|{identifier}|WIDGET|{quantity}|{price}|{tax}")

    def issue(self, identifier="INV1"):
        return self.client.execute(f"ISSUE|{identifier}|AR|REV|TAX|COGS|INV")

    def invoice(self, identifier="INV1"):
        return self.client.execute(f"INVOICE-SHOW|{identifier}")["rows"][0]

    def snapshot(self):
        return {
            command: self.client.execute(command)["rows"]
            for command in ("STOCK", "MOVEMENTS", "ACCOUNTS", "JOURNAL", "INVOICES", "CUSTOMERS")
        }, Path(self.client.journal).read_bytes()

    def reject_without_changes(self, command, message=None):
        before = self.snapshot()
        with self.assertRaises(MeridianError) as error:
            self.client.execute(command)
        if message:
            self.assertIn(message.lower(), str(error.exception).lower())
        self.assertEqual(self.snapshot(), before)

    def batch(self, commands):
        chunk = []
        size = len("BATCH|")
        for command in commands:
            if len(chunk) >= 64 or size + len(command) + 1 > 4000:
                self.client.execute("BATCH|" + "~".join(chunk))
                chunk, size = [], len("BATCH|")
            chunk.append(command)
            size += len(command) + 1
        if chunk:
            self.client.execute("BATCH|" + "~".join(chunk))

    def test_customer_and_draft_are_durable_without_ledger_postings(self):
        ledger = self.client.execute("JOURNAL")["rows"]
        self.draft()
        self.line()
        self.assertEqual(
            self.invoice(),
            [
                "INVOICE",
                "INV1",
                "ACME",
                "20260115",
                "20260214",
                "DRAFT",
                "398",
                "30",
                "428",
                "0",
                "428",
                "1",
            ],
        )
        self.assertEqual(self.client.execute("JOURNAL")["rows"], ledger)
        self.assertEqual(self.client.execute("STOCK")["rows"][0][3], "50")
        reopened = Client(self.directory.name)
        self.assertEqual(reopened.execute("INVOICES")["rows"], [self.invoice()])
        self.assertEqual(
            reopened.execute("CUSTOMERS")["rows"],
            [["CUSTOMER", "ACME", "Acme Manufacturing", "billing@example.com"]],
        )

    def test_issue_posts_revenue_tax_cost_and_unique_line_movements(self):
        self.draft()
        self.line()
        self.line(quantity=1, price=1, tax=5000)
        self.issue()
        self.assertEqual(self.invoice()[5:], ["OPEN", "399", "31", "430", "0", "430", "2"])
        self.assertEqual(self.client.execute("STOCK")["rows"][0][3:6], ["47", "125", "5875"])
        self.assertEqual(
            self.client.execute("MOVEMENTS")["rows"][-2:],
            [
                ["MOVEMENT", "INV1_001", "20260115", "WIDGET", "-2", "Invoice INV1"],
                ["MOVEMENT", "INV1_002", "20260115", "WIDGET", "-1", "Invoice INV1"],
            ],
        )
        ledger = self.client.execute("JOURNAL")["rows"]
        for reference, amount in (("INV1_REV", "399"), ("INV1_TAX", "31"), ("INV1_COGS", "375")):
            posting = next(row for row in ledger if reference in row)
            self.assertIn(amount, posting)
        reopened = Client(self.directory.name)
        self.assertEqual(
            reopened.execute("INVOICE-SHOW|INV1")["rows"], self.client.execute("INVOICE-SHOW|INV1")["rows"]
        )

    def test_tax_rounds_each_line_half_up_in_integer_minor_units(self):
        self.draft()
        for price, rate in ((1, 4999), (1, 5000), (1, 9999), (333, 725)):
            self.line(quantity=1, price=price, tax=rate)
        rows = self.client.execute("INVOICE-SHOW|INV1")["rows"]
        self.assertEqual([row[-1] for row in rows[1:]], ["0", "1", "1", "24"])
        self.assertEqual(rows[0][6:9], ["336", "26", "362"])
        self.issue()
        self.assertEqual(self.invoice()[5], "OPEN")

    def test_two_half_cent_lines_round_to_two_cents(self):
        self.draft()
        self.line(quantity=1, price=1, tax=5000)
        self.line(quantity=1, price=1, tax=5000)
        self.assertEqual(self.invoice()[6:9], ["2", "2", "4"])

    def test_zero_tax_issue_creates_exactly_two_postings(self):
        self.draft()
        self.line(quantity=1, price=200, tax=0)
        before = len(self.client.execute("JOURNAL")["rows"])
        self.issue()
        after = self.client.execute("JOURNAL")["rows"]
        self.assertEqual(len(after), before + 2)
        self.assertFalse(any("INV1_TAX" in row for row in after))

    def test_repeated_sku_demand_is_aggregated_before_depletion(self):
        self.draft()
        self.line(quantity=30, price=200, tax=0)
        self.line(quantity=30, price=200, tax=0)
        self.reject_without_changes("ISSUE|INV1|AR|REV|TAX|COGS|INV", "Insufficient stock")
        self.assertEqual(self.invoice()[5], "DRAFT")
        self.client.execute("RECEIVE|MORE|20260115|WIDGET|10|INV|AP|Additional stock")
        self.issue()
        self.assertEqual(self.client.execute("STOCK")["rows"][0][3], "0")

    def test_later_posting_collision_rolls_back_earlier_revenue_post(self):
        self.draft()
        self.line()
        self.client.execute("POST|INV1_TAX|20260115|CASH|TAX|1|Prior reference")
        self.reject_without_changes("ISSUE|INV1|AR|REV|TAX|COGS|INV")
        self.assertFalse(any("INV1_REV" in row for row in self.client.execute("JOURNAL")["rows"]))

    def test_cost_post_collision_rolls_back_revenue_tax_and_stock(self):
        self.draft()
        self.line()
        self.client.execute("POST|INV1_COGS|20260115|CASH|AP|1|Prior reference")
        self.reject_without_changes("ISSUE|INV1|AR|REV|TAX|COGS|INV")

    def test_movement_collision_rejects_issue_before_posting(self):
        self.draft()
        self.line()
        self.client.execute("RECEIVE|INV1_001|20260115|WIDGET|1|INV|AP|Prior movement")
        self.reject_without_changes("ISSUE|INV1|AR|REV|TAX|COGS|INV", "movement reference")

    def test_partial_payment_then_settlement_has_immutable_payment_rows(self):
        self.draft()
        self.line()
        self.issue()
        self.client.execute("PAY|P1|INV1|20260116|128|CASH|AR")
        self.assertEqual(self.invoice()[5:11], ["OPEN", "398", "30", "428", "128", "300"])
        self.client.execute("PAY|P2|INV1|20260117|300|CASH|AR")
        self.assertEqual(self.invoice()[5:11], ["PAID", "398", "30", "428", "428", "0"])
        self.assertEqual(
            self.client.execute("INVOICE-SHOW|INV1")["rows"][-2:],
            [
                ["PAYMENT", "P1", "20260116", "128"],
                ["PAYMENT", "P2", "20260117", "300"],
            ],
        )
        self.assertEqual(
            self.client.execute("AGING|20260301")["rows"], [["AGE-TOTAL", "0", "0", "0", "0", "0", "0"]]
        )
        self.reject_without_changes("PAY|P3|INV1|20260118|1|CASH|AR")

    def test_payment_rejects_overpayment_duplicate_wrong_ar_and_dates(self):
        self.draft()
        self.line()
        self.issue()
        self.client.execute("PAY|P1|INV1|20260116|100|CASH|AR")
        for command in (
            "PAY|P1|INV1|20260117|1|CASH|AR",
            "PAY|P2|INV1|20260117|329|CASH|AR",
            "PAY|P2|INV1|20260114|1|CASH|AR",
            "PAY|P2|INV1|20260230|1|CASH|AR",
            "PAY|P2|INV1|20260117|1|CASH|OTHERAR",
            "PAY|P2|INV1|20260117|1|AR|AR",
            "PAY|P2|INV1|20260117|1|AP|AR",
            "PAY|P2|INV1|20260117|1|CASH|REV",
        ):
            with self.subTest(command=command):
                self.reject_without_changes(command)
        self.client.execute("CLOSE|20260116")
        self.reject_without_changes("PAY|P2|INV1|20260116|1|CASH|AR")
        self.client.execute("PAY|P2|INV1|20260117|1|CASH|AR")

    def test_draft_and_void_invoices_cannot_accept_payment(self):
        self.draft()
        self.line()
        self.reject_without_changes("PAY|P1|INV1|20260116|1|CASH|AR")
        self.client.execute("VOID|INV1")
        self.assertEqual(self.invoice()[5], "VOID")
        for command in (
            "PAY|P1|INV1|20260116|1|CASH|AR",
            "LINE|INV1|WIDGET|1|1|0",
            "ISSUE|INV1|AR|REV|TAX|COGS|INV",
            "VOID|INV1",
        ):
            self.reject_without_changes(command)

    def test_issued_invoice_cannot_be_edited_reissued_or_voided(self):
        self.draft()
        self.line()
        self.issue()
        for command in ("LINE|INV1|WIDGET|1|1|0", "ISSUE|INV1|AR|REV|TAX|COGS|INV", "VOID|INV1"):
            self.reject_without_changes(command)

    def test_issue_rejects_empty_draft_closed_date_and_wrong_account_kinds(self):
        self.draft()
        self.reject_without_changes("ISSUE|INV1|AR|REV|TAX|COGS|INV")
        self.line()
        for command in (
            "ISSUE|INV1|AP|REV|TAX|COGS|INV",
            "ISSUE|INV1|AR|CASH|TAX|COGS|INV",
            "ISSUE|INV1|AR|REV|CASH|COGS|INV",
            "ISSUE|INV1|AR|REV|TAX|CASH|INV",
            "ISSUE|INV1|AR|REV|TAX|COGS|AP",
            "ISSUE|INV1|AR|REV|TAX|COGS|AR",
            "ISSUE|INV1|AR|REV|TAX|COGS|MISSING",
        ):
            with self.subTest(command=command):
                self.reject_without_changes(command)
        self.client.execute("CLOSE|20260115")
        self.reject_without_changes("ISSUE|INV1|AR|REV|TAX|COGS|INV")

    def test_aging_bucket_boundaries_and_current_paid_amounts(self):
        dates = (
            "20260501",
            "20260430",
            "20260401",
            "20260331",
            "20260302",
            "20260301",
            "20260131",
            "20260130",
            "20260502",
        )
        expected = ("CURRENT", "1-30", "1-30", "31-60", "31-60", "61-90", "61-90", "OVER90", "CURRENT")
        for index, due in enumerate(dates):
            identifier = f"A{index}"
            self.draft(identifier, "20260115", due)
            self.line(identifier, quantity=1, price=200, tax=0)
            self.issue(identifier)
        self.client.execute("PAY|PARTIAL|A1|20260430|50|CASH|AR")
        rows = self.client.execute("AGING|20260501")["rows"]
        self.assertEqual([row[5] for row in rows[:-1]], list(expected))
        self.assertEqual(rows[-1], ["AGE-TOTAL", "400", "350", "400", "400", "200", "9"])
        # Aging measures current unpaid balances against this date, even for a
        # payment recorded later than an earlier aging cutoff.
        past = self.client.execute("AGING|20260116")["rows"]
        self.assertEqual(past[-1], ["AGE-TOTAL", "1750", "0", "0", "0", "0", "9"])

    def test_monetary_bounds_precede_wide_tax_multiplication(self):
        self.draft()
        for quantity, price, rate in (
            (999999999, 9999999999, 9999),
            (1000, 1000000000, 0),
            (100, 9999999999, 1),
        ):
            self.reject_without_changes(f"LINE|INV1|WIDGET|{quantity}|{price}|{rate}")
        self.line(quantity=100, price=9999999999, tax=0)
        self.assertEqual(self.invoice()[6:9], ["999999999900", "0", "999999999900"])
        self.reject_without_changes("LINE|INV1|WIDGET|1|100|0")
        self.line(quantity=1, price=99, tax=0)
        self.assertEqual(self.invoice()[8], "999999999999")

    def test_cogs_total_across_multiple_skus_must_fit_posting_limit(self):
        self.client.execute("ITEM|HIGH1|High value one|9999999999|0")
        self.client.execute("ITEM|HIGH2|High value two|9999999999|0")
        self.client.execute("RECEIVE|H1|20260101|HIGH1|100|INV|AP|Receipt")
        self.client.execute("RECEIVE|H2|20260101|HIGH2|100|INV|AP|Receipt")
        self.draft()
        self.client.execute("LINE|INV1|HIGH1|100|1|0")
        self.client.execute("LINE|INV1|HIGH2|100|1|0")
        self.reject_without_changes("ISSUE|INV1|AR|REV|TAX|COGS|INV", "cost of goods")

    def test_high_value_tax_and_settlement_preserve_all_cents(self):
        self.draft()
        self.line(quantity=50, price=9999999999, tax=9999)
        net = 50 * 9999999999
        tax = (net * 9999 + 5000) // 10000
        total = net + tax
        self.assertEqual(self.invoice()[6:9], [str(net), str(tax), str(total)])
        self.issue()
        self.client.execute(f"PAY|HIGH|INV1|20260116|{total}|CASH|AR")
        self.assertEqual(self.invoice()[5], "PAID")
        balances = {row[1]: int(row[4]) for row in self.client.execute("ACCOUNTS")["rows"]}
        self.assertEqual(balances["AR"], 0)
        self.assertEqual(balances["CASH"], total)
        self.assertEqual(balances["REV"], -net)
        self.assertEqual(balances["TAX"], -tax)
        self.assertEqual(balances["INV"], 0)

    def test_control_balances_reconcile_over_multiple_invoices_and_payments(self):
        for index in range(8):
            identifier = f"RECON{index}"
            self.draft(identifier)
            self.line(identifier, quantity=2, price=101 + index, tax=725)
            self.line(identifier, quantity=1, price=7 + index, tax=5000)
            self.issue(identifier)
            self.client.execute(f"PAY|PART{index}|{identifier}|20260116|100|CASH|AR")
            balances = {row[1]: int(row[4]) for row in self.client.execute("ACCOUNTS")["rows"]}
            invoices = self.client.execute("INVOICES")["rows"]
            stock_value = sum(int(row[5]) for row in self.client.execute("STOCK")["rows"])
            self.assertEqual(balances["AR"], sum(int(row[10]) for row in invoices))
            self.assertEqual(balances["REV"], -sum(int(row[6]) for row in invoices))
            self.assertEqual(balances["TAX"], -sum(int(row[7]) for row in invoices))
            self.assertEqual(balances["INV"], stock_value)
            self.assertEqual(balances["COGS"], (50 * 125) - stock_value)
            trial = self.client.execute("TRIAL")["rows"][-1]
            self.assertEqual(trial[1], trial[2])

    def test_linked_invoice_and_payment_entries_cannot_be_reversed_independently(self):
        self.draft()
        self.line()
        self.issue()
        self.client.execute("PAY|PART|INV1|20260116|100|CASH|AR")
        for reference in ("INV1_REV", "INV1_TAX", "INV1_COGS", "PART"):
            self.reject_without_changes(f"REVERSE|{reference}|UNDO|20260117|Correction")

    def test_draft_invoice_prefix_does_not_block_manual_post_reversal(self):
        self.draft()
        self.client.execute("POST|INV1_REV|20260115|CASH|AP|50|Manual deposit")
        self.client.execute("REVERSE|INV1_REV|MANUAL_UNDO|20260116|Reverse deposit")
        self.assertEqual(self.invoice()[5], "DRAFT")
        balances = {row[1]: int(row[4]) for row in self.client.execute("ACCOUNTS")["rows"]}
        self.assertEqual(balances["CASH"], 0)

    def test_zero_tax_invoice_suffix_does_not_block_unrelated_manual_post_reversal(self):
        self.draft()
        self.line(quantity=1, price=200, tax=0)
        self.issue()
        self.client.execute("POST|INV1_TAX|20260115|CASH|AP|50|Manual deposit")
        self.client.execute("REVERSE|INV1_TAX|MANUAL_UNDO|20260116|Reverse deposit")
        self.assertEqual(self.invoice()[5], "OPEN")
        self.assertEqual(self.invoice()[7], "0")
        balances = {row[1]: int(row[4]) for row in self.client.execute("ACCOUNTS")["rows"]}
        self.assertEqual(balances["CASH"], 0)

    def test_payment_ledger_reference_collision_keeps_subledger_unchanged(self):
        self.draft()
        self.line()
        self.issue()
        self.client.execute("POST|PAYREF|20260116|CASH|AP|1|Earlier ledger reference")
        self.reject_without_changes("PAY|PAYREF|INV1|20260116|100|CASH|AR")

    def test_leap_year_due_and_payment_dates_use_gregorian_calendar(self):
        self.draft(date="20280228", due="20280229")
        self.line(quantity=1, price=200, tax=0)
        self.issue()
        self.client.execute("PAY|LEAP|INV1|20280229|100|CASH|AR")
        self.assertEqual(self.client.execute("AGING|20280301")["rows"][0][4:7], ["1", "1-30", "100"])
        self.reject_without_changes("INVOICE|NONLEAP|ACME|20270228|20270229")

    def test_line_capacity_and_three_digit_movement_ordinals(self):
        self.draft()
        for _ in range(30):
            self.line(quantity=1, price=1, tax=0)
        self.assertEqual(self.invoice()[-1], "30")
        self.reject_without_changes("LINE|INV1|WIDGET|1|1|0", "capacity")
        self.issue()
        self.assertEqual(self.client.execute("MOVEMENTS")["rows"][-1][1], "INV1_030")

    def test_customer_capacity_and_full_length_report_are_bounded(self):
        self.batch(f"CUSTOMER|C{i}|{'n' * 80}|{'x' * 86}@example.com" for i in range(499))
        rows = self.client.execute("CUSTOMERS")["rows"]
        self.assertEqual(len(rows), 500)
        self.assertEqual(len(rows[-1][2]), 80)
        self.assertEqual(len(rows[-1][3]), 98)
        self.reject_without_changes("CUSTOMER|FULL|Overflow|full@example.com", "capacity")

    def test_invoice_capacity_does_not_overwrite_last_draft(self):
        self.batch(f"INVOICE|I{i}|ACME|20260115|20260214" for i in range(500))
        rows = self.client.execute("INVOICES")["rows"]
        self.assertEqual(len(rows), 500)
        self.assertEqual(rows[-1][1], "I499")
        self.reject_without_changes("INVOICE|FULL|ACME|20260115|20260214", "capacity")

    def test_payment_capacity_preserves_remaining_outstanding_amount(self):
        self.draft()
        self.line(quantity=1, price=3000, tax=0)
        self.issue()
        self.batch(f"PAY|P{i}|INV1|20260116|1|CASH|AR" for i in range(2048))
        self.assertEqual(self.invoice()[9:11], ["2048", "952"])
        self.reject_without_changes("PAY|FULL|INV1|20260116|1|CASH|AR", "capacity")

    def test_identifier_limits_leave_room_for_generated_posting_suffixes(self):
        identifier = "I" * 24
        self.draft(identifier)
        self.line(identifier, quantity=1, price=1, tax=0)
        self.issue(identifier)
        self.assertEqual(self.client.execute("MOVEMENTS")["rows"][-1][1], identifier + "_001")
        self.client.execute(f"PAY|{'P' * 32}|{identifier}|20260116|1|CASH|AR")
        self.assertEqual(self.invoice(identifier)[5], "PAID")

    def test_invalid_sales_fields_counts_and_canonical_numbers_are_atomic(self):
        self.draft()
        for command in (
            "CUSTOMER|ACME|Duplicate|x@example.com",
            "CUSTOMER|bad|Invalid ID|x@example.com",
            "CUSTOMER|C2||x@example.com",
            "CUSTOMER|C2|Customer|invalid-email",
            "CUSTOMER|C2|Customer|two@@example.com",
            "CUSTOMER|C2|Customer|x @example.com",
            "CUSTOMER|C2|Customer|x@example.",
            "CUSTOMER|C2|Customer|x@example.com|extra",
            "INVOICE|INV1|ACME|20260115|20260214",
            "INVOICE|I2|MISSING|20260115|20260214",
            "INVOICE|I2|ACME|20260230|20260301",
            "INVOICE|I2|ACME|20260115|20260114",
            "INVOICE|" + "X" * 25 + "|ACME|20260115|20260214",
            "LINE|INV1|UNKNOWN|1|1|0",
            "LINE|INV1|WIDGET|0|1|0",
            "LINE|INV1|WIDGET|1|0|0",
            "LINE|INV1|WIDGET|01|1|0",
            "LINE|INV1|WIDGET|1|1.5|0",
            "LINE|INV1|WIDGET|1|1|10000",
            "LINE|INV1|WIDGET|1|1|-1",
            "LINE|INV1|WIDGET|1|1|00",
            "LINE|INV1|WIDGET|1000000000|1|0",
            "LINE|INV1|WIDGET|1|10000000000|0",
            "LINE|INV1|WIDGET|1|1|0|extra",
            "ISSUE|INV1|AR|REV|TAX|COGS",
            "PAY|P1|INV1|20260115|1|CASH",
            "VOID|MISSING",
            "CUSTOMERS|extra",
            "INVOICES|extra",
            "INVOICE-SHOW|MISSING",
            "INVOICE-SHOW|INV1|extra",
            "AGING|20260230",
            "AGING|20260115|extra",
        ):
            with self.subTest(command=command):
                self.reject_without_changes(command)

    def test_payment_numeric_validation_does_not_coerce_values(self):
        self.draft()
        self.line()
        self.issue()
        for amount in ("0", "-1", "+1", "01", "1.5", "1e2", "1000000000000", ""):
            with self.subTest(amount=amount):
                self.reject_without_changes(f"PAY|P1|INV1|20260116|{amount}|CASH|AR")

    def test_reports_are_read_only_and_empty_aging_is_explicit(self):
        self.draft()
        self.line()
        before = Path(self.client.journal).read_bytes()
        for report in ("CUSTOMERS", "INVOICES", "INVOICE-SHOW|INV1", "AGING|20260115"):
            self.client.execute(report)
        self.assertEqual(Path(self.client.journal).read_bytes(), before)
        self.assertEqual(
            self.client.execute("AGING|20260115")["rows"], [["AGE-TOTAL", "0", "0", "0", "0", "0", "0"]]
        )


if __name__ == "__main__":
    unittest.main()
