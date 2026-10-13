"""Seed a complete, explicitly synthetic order-to-cash scenario atomically."""

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.client import Client, MeridianError

DEMO_COMMANDS = [
    "ACCOUNT|CASH|ASSET|Cash and bank",
    "ACCOUNT|AR|ASSET|Trade receivables",
    "ACCOUNT|INVENTORY|ASSET|Finished goods inventory",
    "ACCOUNT|AP|LIABILITY|Trade payables",
    "ACCOUNT|EQUITY|EQUITY|Owner capital",
    "ACCOUNT|SALES|REVENUE|Product revenue",
    "ACCOUNT|TAX|LIABILITY|Sales tax payable",
    "ACCOUNT|COGS|EXPENSE|Cost of goods sold",
    "ACCOUNT|ADJUSTMENT|EXPENSE|Inventory variance",
    "POST|CAPITAL_01|20261013|CASH|EQUITY|1000000|Synthetic opening capital",
    "ITEM|WIDGET|Precision widget|1250|10",
    "ITEM|GADGET|Field service gadget|875|5",
    "RECEIVE|RCPT_W|20261013|WIDGET|40|INVENTORY|AP|Synthetic supplier receipt",
    "RECEIVE|RCPT_G|20261013|GADGET|20|INVENTORY|AP|Synthetic supplier receipt",
    "CUSTOMER|ACME|Acme Example Company|billing@example.com",
    "INVOICE|INV_0001|ACME|20261013|20261112",
    "LINE|INV_0001|WIDGET|3|2500|1800",
    "LINE|INV_0001|GADGET|2|1750|1800",
    "ISSUE|INV_0001|AR|SALES|TAX|COGS|INVENTORY",
    "PAY|PAY_0001|INV_0001|20261014|5000|CASH|AR",
    "INVOICE|INV_0002|ACME|20261013|20261014",
    "LINE|INV_0002|WIDGET|2|2500|0",
    "ISSUE|INV_0002|AR|SALES|TAX|COGS|INVENTORY",
    "ADJUST|COUNT_01|20261014|WIDGET|-1|INVENTORY|ADJUSTMENT|Synthetic stock count",
]


def seed(data_dir):
    client = Client(data_dir)
    if client.journal.exists() and client.journal.stat().st_size:
        raise MeridianError("Demo refuses to overwrite an existing journal; choose a fresh directory")
    client.execute("BATCH|" + "~".join(DEMO_COMMANDS))
    return client


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("demo-data"))
    options = parser.parse_args()
    try:
        client = seed(options.data_dir)
    except MeridianError as exc:
        parser.exit(2, f"Demo failed: {exc}\n")
    print(f"Synthetic scenario created in {client.data_dir}")
    for row in client.execute("SUMMARY")["rows"]:
        print(" | ".join(row))
    print(f"Open the console: python3 tools/server.py --data-dir {client.data_dir}")


if __name__ == "__main__":
    main()
