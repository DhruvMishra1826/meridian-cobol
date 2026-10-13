# Inventory and standard costing

Meridian maintains perpetual inventory with integer quantities and immutable standard costs in currency minor units. Each receipt or count adjustment creates both a stock movement and a balanced ledger entry in one durable transaction. The journal replays these operations to reconstruct the stock position; reports use the same reconstructed state as accounting and invoicing.

## Configure items

Create ledger accounts before receiving stock, then establish item master records:

```text
ACCOUNT|INV|ASSET|Inventory
ACCOUNT|AP|LIABILITY|Trade payables
ACCOUNT|VAR|EXPENSE|Inventory variance
ITEM|WIDGET|Precision widget|1250|10
```

`1250` represents a standard cost of 12.50 for a currency with two decimal places. Quantities are whole units. SKU identifiers contain uppercase ASCII letters, digits, underscores or hyphens and are at most 12 characters. Item names allow 80 characters. Standard cost must be 1–9,999,999,999 minor units; the reorder point must be 0–999,999,999 units. An existing SKU cannot be recreated or have its cost silently changed.

## Receive stock

```text
RECEIVE|RCV-001|20261013|WIDGET|20|INV|AP|Supplier receipt
```

This adds 20 units, debits inventory by 25,000 minor units and credits trade payables by the same amount. The movement reference is also the ledger posting reference. References allow 32 characters and must be unique across stock movements and ledger postings. A receipt quantity must be positive.

## Record a count adjustment

```text
ADJUST|COUNT-001|20261013|WIDGET|-3|INV|VAR|Physical count shortage
ADJUST|COUNT-002|20261013|WIDGET|2|INV|VAR|Recovered units
```

A negative quantity credits inventory and debits the variance account. A positive quantity debits inventory and credits variance. Adjustment quantity is a nonzero canonical integer with an optional leading minus sign: `-3` and `3` are valid; `+3`, `03`, `-0`, decimals and exponent notation are rejected. All movement memos are required and allow 80 characters. Dates must be valid Gregorian `YYYYMMDD` dates later than the ledger's closed-through date. Accounts must already exist and be distinct, and the inventory account must have kind `ASSET`.

Each SKU is limited to 999,999,999 units and 999,999,999,999 minor units of stock value. Each movement's absolute quantity multiplied by standard cost must also fit the 999,999,999,999 posting limit. Multiplication and stock bounds are checked before the ledger is called. Failed postings leave quantities, movements, balances and the durable journal unchanged, and the rejected reference can be retried after correcting the problem.

## Inspect inventory

The native reports return pipe-delimited rows:

| Command | Row schema |
| --- | --- |
| `STOCK` | `STOCK\|sku\|name\|quantity\|standardCost\|value\|reorderPoint` |
| `MOVEMENTS` | `MOVEMENT\|reference\|date\|sku\|signedQuantity\|memo` |
| `REORDER` | `REORDER\|sku\|name\|quantity\|reorderPoint\|shortfall` |

`STOCK` includes zero-stock items. `REORDER` includes items strictly below their reorder point and calculates the units needed to reach that point. `MOVEMENTS` preserves transaction insertion order and includes invoice depletion movements recorded by the sales module. Reports do not append to history.

## Operating boundaries

The configured limits are 500 items and 4,096 stock movements. All three report commands accept no arguments. Report output is bounded by the shared engine response capacity and returns an explicit error if that capacity is exceeded.

Invoice issue uses each item's standard cost for cost of goods sold and depletes inventory atomically with revenue and tax postings. Ledger `REVERSE` rejects postings linked to stock movements, issued invoices and payments to preserve their subledgers. Use a compensating `ADJUST` or `RECEIVE` to correct stock quantities; the original movement remains in the audit history. Reconcile inventory balances with `STOCK`, `MOVEMENTS` and ledger account statements when manual ledger postings affect inventory accounts.

This module implements a single stock pool per SKU. Warehouse locations, fractional quantities, lot or serial tracking, FIFO valuation, purchasing documents and supplier management require additional modules.

## Verification

`tests/test_inventory.py` exercises durable replay, signed adjustments, reorder behavior, duplicate references, failed ledger posting rollback, stock underflow, exact quantity and value limits, closed periods, immutable costs, field validation, and conservation of stock quantity/value over a sequence of adjustments. It also fills all 500 item slots and all 4,096 movement slots, verifies the complete movement report, and checks rejection beyond each capacity. Ledger entries and trial balances are checked against the standard-cost movement amounts. Run it against the compiled engine with:

```sh
python3 -m unittest discover -s tests -p 'test_inventory.py' -v
```
