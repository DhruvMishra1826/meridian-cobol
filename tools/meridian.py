#!/usr/bin/env python3
"""Command line access to Meridian. Run from any working directory."""

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.client import REPORTS, Client, MeridianError, validate_command, validate_report


def safe_csv_cell(value):
    """Keep text from becoming a spreadsheet formula; preserve signed amounts."""
    if value.startswith(("=", "+", "@", "-")) and not re.fullmatch(r"-?[0-9]+", value):
        return "'" + value
    return value


def read_batch(path):
    source = Path(path)
    if source.stat().st_size > 16384:
        raise MeridianError("Batch file exceeds 16384 bytes")
    operations = [
        line
        for line in source.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not operations or len(operations) > 64:
        raise MeridianError("A batch needs between 1 and 64 commands")
    for command in operations:
        validate_command(command)
        if "~" in command or command.split("|", 1)[0] == "BATCH":
            raise MeridianError("Batch entries cannot contain ~ or nested BATCH commands")
    return validate_command("BATCH|" + "~".join(operations))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Meridian inventory, invoicing and double-entry accounting")
    parser.add_argument(
        "--data-dir", default=os.environ.get("MERIDIAN_DATA_DIR", str(Path.home() / ".local/share/meridian"))
    )
    parser.add_argument("--format", choices=("text", "json", "csv"), default="text")
    commands = parser.add_subparsers(dest="action", required=True)
    command = commands.add_parser("command", help="Execute one pipe-delimited COBOL command")
    command.add_argument("value")
    batch = commands.add_parser("batch", help="Atomically execute a file of up to 64 mutation commands")
    batch.add_argument("file")
    report = commands.add_parser("report", help="Read a report")
    report.add_argument("name", choices=sorted(REPORTS))
    report.add_argument("arguments", nargs="*")
    serve = commands.add_parser("serve", help="Run the local HTTP console")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8080)
    args = parser.parse_args(argv)
    try:
        if args.action == "serve":
            from tools.server import run

            run(args.data_dir, args.host, args.port)
            return 0
        client = Client(args.data_dir)
        if args.action == "command":
            value = args.value
        elif args.action == "batch":
            value = read_batch(args.file)
        else:
            value = validate_report("|".join([args.name] + args.arguments))
        result = client.execute(value)
        if args.format == "json":
            print(json.dumps(result, ensure_ascii=False))
        elif args.format == "csv":
            writer = csv.writer(sys.stdout, lineterminator="\n")
            writer.writerows([safe_csv_cell(value) for value in row] for row in result["rows"])
        else:
            print("OK | " + result["message"])
            for row in result["rows"]:
                print(" | ".join(row))
        return 0
    except (MeridianError, ValueError, OSError) as exc:
        if args.format == "json":
            print(json.dumps({"ok": False, "message": str(exc), "rows": []}), file=sys.stderr)
        else:
            print("ERROR | " + str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
