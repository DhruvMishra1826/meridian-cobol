# Customers, invoicing and receivables

Meridian supports customer master records, inventory-backed invoice drafts, line-level sales tax, issue, partial payments and current receivables aging. Every successful mutation enters the durable command journal. Invoice issue posts revenue, tax and cost of goods sold together with stock depletion; a failed posting restores all records and leaves the journal unchanged.

## Prepare customer and account records

```text
ACCOUNT|CASH|ASSET|Cash
ACCOUNT|AR|ASSET|Trade receivables
ACCOUNT|INV|ASSET|Inventory
ACCOUNT|AP|LIABILITY|Trade payables
ACCOUNT|REV|REVENUE|Sales revenue
ACCOUNT|TAX|LIABILITY|Sales tax payable
ACCOUNT|COGS|EXPENSE|Cost of goods sold
ITEM|WIDGET|Precision widget|125|10
RECEIVE|RCV1|20260101|WIDGET|50|INV|AP|Opening receipt
CUSTOMER|ACME|Acme Manufacturing|billing@example.com
```

Customer IDs accept up to 12 uppercase ASCII letters, digits, hyphens or underscores. Names are required and accept 80 characters; email addresses accept 100 characters, one `@`, no internal spaces and a domain dot. Email validation checks structure; it does not verify mailbox ownership or deliverability. Customer IDs remain unique and records cannot be silently overwritten.

## Draft and issue an invoice

```text
INVOICE|INV1|ACME|20260115|20260214
LINE|INV1|WIDGET|2|199|750
LINE|INV1|WIDGET|1|1|5000
INVOICE-SHOW|INV1
ISSUE|INV1|AR|REV|TAX|COGS|INV
```

An invoice ID accepts 24 identifier characters. Dates use valid Gregorian `YYYYMMDD` values, and the due date cannot precede the invoice date. The customer and each SKU must exist. Draft lines require a positive whole-unit quantity up to 999,999,999, a positive unit price up to 9,999,999,999 minor units, and a tax rate of 0–9,999 basis points. One basis point is 0.01 percent; `750` means 7.50 percent. Each invoice accepts 30 lines, including repeated SKUs.

All monetary inputs and outputs are integer currency minor units. A line net amount is `quantity × unitPrice`; tax is `floor((net × taxBasisPoints + 5000) / 10000)`. This rounds half a minor unit upward, separately for every line. Invoice totals sum those rounded line amounts. Wide intermediate fields prevent multiplication from wrapping; each line and the complete invoice must fit 999,999,999,999 minor units. Draft totals are visible before issue and do not alter stock or ledger accounts.

The example has net 399, tax 31 and total 430 minor units. Issue creates:

| Reference | Debit | Credit | Amount |
| --- | --- | --- | --- |
| `INV1_REV` | `AR` | `REV` | 399 |
| `INV1_TAX` | `AR` | `TAX` | 31 |
| `INV1_COGS` | `COGS` | `INV` | 375 |

The tax posting is omitted when tax is zero. Cost of goods sold uses the immutable standard cost of each SKU. Issue first aggregates quantities across every line for each SKU, rejects insufficient stock, checks movement and posting capacities, and checks total cost against the posting amount limit. It then creates depletion movement references `INV1_001`, `INV1_002`, and so on. All movement and posting references must be unique in their respective audit records.

The supplied receivables and inventory accounts must be `ASSET` accounts and must differ. Revenue must be `REVENUE`, tax must be `LIABILITY`, and cost of goods sold must be `EXPENSE`. The invoice date must be later than the ledger closed-through date. After successful issue the invoice becomes `OPEN`; its lines, totals, date and customer are immutable.

## Record partial or full payments

```text
PAY|P1|INV1|20260116|130|CASH|AR
PAY|P2|INV1|20260117|300|CASH|AR
```

A payment debits cash and credits receivables. Both accounts must be distinct `ASSET` accounts, and the receivables account must match the account used when the invoice was issued. References accept 32 identifier characters and must be unique across payments and ledger entries. Amounts must be positive canonical integers, fit the posting limit and not exceed the current unpaid total. Payment dates cannot precede the invoice date or fall in a closed period. Draft, void and already paid invoices reject payments.

Partial payments preserve `OPEN` status; exact settlement changes the status to `PAID`. Each accepted payment retains its original reference, date and amount. Invoice issue and payment errors leave all balances, quantities, subledger records and durable history unchanged, including when a later ledger posting fails after an earlier one succeeded.

Ledger reversal rejects entries linked to issued invoices, payments and stock movements. This prevents a raw reversal from changing accounting balances while leaving the corresponding operational records intact. Use a separate correcting transaction when one is supported by the relevant workflow.

## Void a draft

```text
VOID|INV1
```

Only a draft can be voided. Its retained lines and totals remain available for audit, and no stock movement or ledger entry is created. Voided invoices cannot be issued, paid, edited or voided again. Issued invoices require a separate credit-note workflow for commercial corrections; this release does not implement credit notes or returns.

## Report schemas

The CLI and Python client return these pipe-delimited rows. A query never adds a journal record.

| Command | Rows |
| --- | --- |
| `CUSTOMERS` | `CUSTOMER\|id\|name\|email` |
| `INVOICES` | `INVOICE\|id\|customerId\|date\|dueDate\|status\|net\|tax\|total\|paid\|outstanding\|lineCount` |
| `INVOICE-SHOW\|id` | One `INVOICE` row, then `LINE\|ordinal\|sku\|quantity\|unitPrice\|taxBasisPoints\|net\|tax`, then matching `PAYMENT\|reference\|date\|amount` rows |
| `AGING\|asOfDate` | `AGE\|customerId\|invoiceId\|dueDate\|overdueDays\|bucket\|outstanding`, followed by `AGE-TOTAL\|current\|1To30\|31To60\|61To90\|over90\|openInvoiceCount` |

## Receivables aging

`AGING|20260501` groups the current unpaid total of every open invoice into `CURRENT`, `1-30`, `31-60`, `61-90` or `OVER90`, according to the number of calendar days after its due date. Invoices due on the report date or later show zero overdue days in `CURRENT`. Paid, draft and void invoices are excluded. The final total row is always present, including when no invoices are open.

This is an operational report of current balances aged against a chosen date. It does not reconstruct historical receivables: a payment made after an earlier report cutoff is still reflected in the current outstanding amount. Ledger statements and the durable journal provide the underlying accounting audit trail.

## Limits and verification

The module supports 500 customers, 500 invoices, 30 lines per invoice and 2,048 payments. Inventory movements and ledger postings each have a 4,096-record shared capacity. Capacity checks run before the associated record is written, and generated references reserve enough identifier space for suffixes. Response output is bounded by the engine response buffer and fails explicitly if exceeded.

`tests/test_sales.py` checks durable drafts and issued records, line-level tax rounding, zero-tax posting, aggregated repeated-SKU demand, unique depletion references, rollback on later posting failures, partial settlement, closed periods, correct account kinds, correct receivables linkage, aging boundaries, Gregorian leap dates, numeric overflow, field validation and record capacities. Reconciliation tests check that receivables equal invoice outstanding totals, the inventory control balance equals stock valuation, recognized costs equal depleted standard cost, and the trial balance remains balanced after each issue and payment:

```sh
python3 -m unittest discover -s tests -p 'test_sales.py' -v
```

The application uses one currency per journal and whole inventory units. Credit notes, foreign exchange, discounts, customer statement dispatch and an invoice-number generator are outside this release. Use ledger reports to reconcile receivables whenever posting manual entries to control accounts.
