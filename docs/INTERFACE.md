# Engine contracts

The engine receives two arguments: an existing data directory's journal path and one pipe-delimited command. Each successful mutation is one durable journal record. Queries never write. Monetary inputs/outputs are integer minor units; quantities are integer units. Dates are Gregorian `YYYYMMDD`. Names cannot contain pipe/newline/control characters. Identifiers are uppercase ASCII letters, digits, hyphen or underscore.

COBOL subprograms `MD-LEDGER`, `MD-INVENTORY`, `MD-SALES` take `app-state`, `command-request`, `operation-result` by reference in that order. Each call initializes operation-result, validates field count/length/type/range before mutation, sets result-code 0 on success or 2 on business errors, result-mutating 1 only for successful mutations. Read responses contain newline-separated pipe-delimited rows in result-output; status is printed by the driver as `OK|message` or `ERROR|message`. No subprogram displays output or performs file I/O. Driver restores the complete state if any module fails; failing commands never enter the journal. Replay uses identical validation and fails closed on invalid history.

Shared helper `MD-VALIDATE`: call using value PIC X(256), kind PIC X(8), maximum BINARY-LONG, validity BINARY-LONG. Kinds: ID (length 1..maximum, `[A-Z0-9_-]`), TEXT (length 1..maximum, no delimiters/control characters), UINT (canonical 0 or leading-nonzero digits, length <=maximum), DATE (YYYYMMDD valid Gregorian). Validity is 1 for success, 0 for invalid. Amount limits must also be checked by business modules.

## Ledger commands

* `ACCOUNT|id|ASSET/LIABILITY/EQUITY/REVENUE/EXPENSE|name`
* `POST|reference|date|debitAccount|creditAccount|amount|memo`
* `REVERSE|reference|newReference|date|memo`
* `CLOSE|date`
* `ACCOUNTS`, `TRIAL`, `JOURNAL`, `STATEMENT|accountId`, `SUMMARY`

Balances are debit minus credit for every account. Ledger queries label record types and emit integer cents. POST enforces distinct existing accounts, positive amount <=999999999999, unique reference, date later than closed-through, total balance bounds. REVERSE creates one opposite entry and records its reference on the original.

## Inventory commands

* `ITEM|sku|name|standardCost|reorderPoint` (cost 1..9999999999)
* `RECEIVE|reference|date|sku|quantity|inventoryAccount|offsetAccount|memo`
* `ADJUST|reference|date|sku|signedQuantity|inventoryAccount|adjustmentAccount|memo`
* `STOCK`, `MOVEMENTS`, `REORDER`

Use standard cost (fixed upon creation). RECEIVE posts inventory debit / offset credit. ADJUST accepts nonzero signed integer (`-N` or `N`; no plus) and posts according to sign. Units/value/record bounds must be enforced. Movement references unique. Internal invoice depletion is performed by MD-SALES (issue), using same items/movements state, not via public commands.

## Sales commands

* `CUSTOMER|id|name|email`
* `INVOICE|id|customerId|date|dueDate`
* `LINE|invoiceId|sku|quantity|unitPrice|taxBasisPoints`
* `ISSUE|invoiceId|receivablesAccount|revenueAccount|taxAccount|cogsAccount|inventoryAccount`
* `PAY|paymentReference|invoiceId|date|amount|cashAccount|receivablesAccount`
* `VOID|invoiceId` (draft only)
* `CUSTOMERS`, `INVOICES`, `INVOICE-SHOW|id`, `AGING|asOfDate`

Draft creation/line changes do not post to ledger. ISSUE validates aggregate stock demand across repeated SKU lines before depletion, computes line tax rounded to nearest cent from integer basis points, updates stock, creates movements, and posts net revenue, tax (if nonzero), and standard-cost COGS atomically. Entry references are invoice ID plus `_REV`, `_TAX`, `_COGS`; movement references invoice ID plus `_` plus three-digit line ordinal. PAY posts cash debit / receivables credit, rejects overpayment and duplicate references, updates OPEN to PAID when settled. Date cannot precede invoice date or closed-through. Invoices and payments retain their own immutable records. AGE emits current outstanding amounts aged by due date as of the requested date; it is an operational current balance report, not a historical ledger reconstruction.

Subprogram cross-calls use local request/result groups made with `COPY ... REPLACING` or equivalent manual structures. Preserve original command fields. No calls to driver. All capacities from copybook are limits to validate before writing.
