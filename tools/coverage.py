#!/usr/bin/env python3
"""Build an instrumented engine, run real tests, and report mapped source coverage.

Uses only the Python standard library, GnuCOBOL and GCC/Clang's gcov toolchain.
Generated C and copybook initialization do not enter COBOL source percentages.
"""

import argparse
import datetime
import html
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "build" / "coverage"
COBOL_SOURCES = tuple(
    ROOT / "src" / name
    for name in (
        "main.cob",
        "validate.cob",
        "ledger.cob",
        "inventory.cob",
        "sales.cob",
    )
)
NATIVE_SOURCE = ROOT / "native" / "store.c"
COUNT_LINE = re.compile(r"^\s*([^:]+):\s*(\d+):(.*)$")
BRANCH_LINE = re.compile(r"^branch\s+(\d+)\s+(?:taken\s+(\d+)|never executed)")


class CoverageError(Exception):
    """The toolchain or measured test run could not produce a valid report."""


def command(argv, cwd=ROOT, env=None):
    result = subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.returncode:
        raise CoverageError(f"Command failed ({result.returncode}): {shlex.join(argv)}\n{result.stdout}")
    return result.stdout


def find_gcov(compiler, explicit=None):
    if explicit:
        return shlex.split(explicit)
    version = command(compiler + ["--version"])
    if "clang" in version.lower():
        llvm = shutil.which("llvm-cov")
        if not llvm and shutil.which("xcrun"):
            try:
                llvm = command(["xcrun", "--find", "llvm-cov"]).strip()
            except CoverageError:
                pass
        if llvm:
            return [llvm, "gcov"]
        raise CoverageError(
            "Clang requires llvm-cov for gcov reports. Install its matching LLVM "
            "tools or pass --gcov '/path/to/llvm-cov gcov'."
        )
    gcov = shutil.which("gcov")
    if gcov:
        return [gcov]
    raise CoverageError("GCC coverage requires gcov. Install matching GCC tools or pass --gcov.")


def build_instrumented(cobc, compiler):
    # Cleaning only this fixed generated directory makes runs independent.
    if OUTPUT.is_symlink():
        raise CoverageError("Coverage output directory must not be a symbolic link")
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    OUTPUT.mkdir(parents=True)
    environment = os.environ.copy()
    # Use one C toolchain for generated COBOL and native storage so gcov versions agree.
    environment["COB_CC"] = shlex.join(compiler)
    build_log = []
    native_command = compiler + [
        "--coverage",
        "-O0",
        "-g",
        "-std=c11",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-c",
        str(NATIVE_SOURCE),
        "-o",
        "store.o",
    ]
    build_log.append("$ " + shlex.join(native_command))
    build_log.append(command(native_command, OUTPUT, environment))
    cobol_command = cobc + [
        "-free",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-O0",
        "-debug",
        # -g emits original COBOL line directives on both GnuCOBOL 3.1 and 3.2.
        # Passing coverage flags through -A/-Q also supports 3.1, whose driver
        # does not recognize the --coverage convenience option.
        "-g",
        "-A",
        "--coverage",
        "-Q",
        "--coverage",
        "--save-temps",
        "-I",
        str(ROOT / "copybooks"),
        "-x",
        *(str(path) for path in COBOL_SOURCES),
        "store.o",
        "-o",
        "meridian",
    ]
    build_log.append("$ " + shlex.join(cobol_command))
    build_log.append(command(cobol_command, OUTPUT, environment))
    (OUTPUT / "build.log").write_text("\n".join(build_log), encoding="utf-8")
    notes = sorted(OUTPUT.glob("*.gcno"))
    if len(notes) != len(COBOL_SOURCES) + 1:
        raise CoverageError(f"Expected six instrumented units, found {len(notes)} gcno files")
    return OUTPUT / "meridian"


def run_tests(engine, pattern):
    environment = os.environ.copy()
    environment["MERIDIAN_ENGINE"] = str(engine)
    argv = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", pattern, "-v"]
    print("Running the actual unittest suite with the instrumented engine...", flush=True)
    result = subprocess.run(
        argv,
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    (OUTPUT / "tests.log").write_text(result.stdout, encoding="utf-8")
    match = re.search(r"Ran (\d+) tests? in ([\d.]+)s", result.stdout)
    if match:
        print(
            f"Ran {match.group(1)} tests in {match.group(2)}s; exit status {result.returncode}.", flush=True
        )
    else:
        print(f"Test process exit status {result.returncode}; see tests.log.", flush=True)
    if result.returncode:
        print(result.stdout, file=sys.stderr)
    if not match or int(match.group(1)) == 0:
        raise CoverageError("No unittest results were measured; inspect build/coverage/tests.log")
    return {
        "command": argv,
        "pattern": pattern,
        "passed": result.returncode == 0,
        "returncode": result.returncode,
        "count": int(match.group(1)) if match else None,
        "seconds": float(match.group(2)) if match else None,
        "log": "tests.log",
    }


def instrumented_count(marker):
    marker = marker.strip()
    if marker in {"#####", "====="}:
        return 0
    if marker == "-":
        return None
    if re.fullmatch(r"\d+\*?", marker):
        return int(marker.rstrip("*"))
    raise CoverageError(f"Unsupported gcov execution counter {marker!r}")


def parse_gcov(path):
    source = None
    counts = {}
    branches = []
    current_line = 0
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        row = COUNT_LINE.match(raw)
        if row:
            marker, number, text = row.groups()
            current_line = int(number)
            if current_line == 0 and text.startswith("Source:"):
                source = Path(text[len("Source:") :])
                if not source.is_absolute():
                    source = OUTPUT / source
                source = source.resolve()
            if current_line > 0:
                count = instrumented_count(marker)
                if count is not None:
                    counts[current_line] = counts.get(current_line, 0) + count
            continue
        branch = BRANCH_LINE.match(raw)
        if branch and current_line > 0:
            ordinal, taken = branch.groups()
            branches.append(
                {
                    "line": current_line,
                    "ordinal": int(ordinal),
                    "taken": int(taken) if taken else 0,
                }
            )
    return source, counts, branches


def percentage(covered, total):
    return round(100 * covered / total, 2) if total else None


def collect(gcov):
    report_dir = OUTPUT / "gcov"
    report_dir.mkdir()
    logs = []
    records = {}
    known = {source.resolve() for source in (*COBOL_SOURCES, NATIVE_SOURCE)}
    if not list(OUTPUT.glob("*.gcda")):
        raise CoverageError("Tests produced no engine coverage data; verify MERIDIAN_ENGINE support")
    for notes in sorted(OUTPUT.glob("*.gcno")):
        # A directory per object prevents shared copybook reports overwriting each other.
        unit_dir = report_dir / notes.stem
        unit_dir.mkdir()
        # Generated headers use compiler-relative paths; gcov reads them from
        # its current directory even though original COBOL paths are absolute.
        for suffix in (".c", ".c.h", ".c.l.h"):
            generated = OUTPUT / (notes.stem + suffix)
            if generated.exists():
                shutil.copyfile(generated, unit_dir / generated.name)
        argv = gcov + ["-b", "-c", "-p", str(notes)]
        logs.append("$ " + shlex.join(argv))
        logs.append(command(argv, unit_dir))
        for report in sorted(unit_dir.glob("*.gcov")):
            source, counts, branches = parse_gcov(report)
            if source not in known:
                continue
            relative = source.relative_to(ROOT).as_posix()
            record = records.setdefault(
                relative,
                {
                    "source": relative,
                    "kind": "cobol" if source.suffix == ".cob" else "native-c",
                    "line_counts": {},
                    "branches": [],
                    "gcov_files": [],
                },
            )
            for line, count in counts.items():
                record["line_counts"][line] = record["line_counts"].get(line, 0) + count
            record["branches"].extend(branches)
            record["gcov_files"].append(report.relative_to(OUTPUT).as_posix())
    (OUTPUT / "gcov.log").write_text("\n".join(logs), encoding="utf-8")
    missing = sorted(
        source.relative_to(ROOT).as_posix()
        for source in known
        if source.relative_to(ROOT).as_posix() not in records
    )
    if missing:
        raise CoverageError("Missing original-source gcov mappings: " + ", ".join(missing))
    for record in records.values():
        counts = record["line_counts"]
        record["executable_lines"] = len(counts)
        record["covered_lines"] = sum(count > 0 for count in counts.values())
        record["line_percent"] = percentage(record["covered_lines"], record["executable_lines"])
        record["uncovered_lines"] = sorted(line for line, count in counts.items() if count == 0)
        record["compiler_branches"] = len(record["branches"])
        record["taken_compiler_branches"] = sum(branch["taken"] > 0 for branch in record["branches"])
        record["compiler_branch_percent"] = percentage(
            record["taken_compiler_branches"], record["compiler_branches"]
        )
    return [records[key] for key in sorted(records)]


def totals(files, kind):
    selected = [record for record in files if record["kind"] == kind]
    covered = sum(record["covered_lines"] for record in selected)
    executable = sum(record["executable_lines"] for record in selected)
    branches = sum(record["compiler_branches"] for record in selected)
    taken = sum(record["taken_compiler_branches"] for record in selected)
    return {
        "covered_lines": covered,
        "executable_lines": executable,
        "line_percent": percentage(covered, executable),
        "taken_compiler_branches": taken,
        "compiler_branches": branches,
        "compiler_branch_percent": percentage(taken, branches),
    }


def write_reports(summary):
    (OUTPUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    rows = []
    lcov = []
    details = []
    for record in summary["files"]:
        source = ROOT / record["source"]
        rows.append(
            f"| {record['source']} | {record['covered_lines']}/{record['executable_lines']} "
            f"| {record['line_percent']:.2f}% | "
            f"{record['taken_compiler_branches']}/{record['compiler_branches']} |"
        )
        lcov.extend(["TN:Meridian unittest suite", "SF:" + str(source)])
        for line, count in sorted(record["line_counts"].items()):
            lcov.append(f"DA:{line},{count}")
        for block, branch in enumerate(record["branches"]):
            lcov.append(f"BRDA:{branch['line']},{block},0,{branch['taken']}")
        lcov.extend(
            [
                f"LF:{record['executable_lines']}",
                f"LH:{record['covered_lines']}",
                f"BRF:{record['compiler_branches']}",
                f"BRH:{record['taken_compiler_branches']}",
                "end_of_record",
            ]
        )
        source_rows = []
        for line, text in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
            count = record["line_counts"].get(line)
            status = "unmeasured" if count is None else "covered" if count > 0 else "missed"
            source_rows.append(
                f'<tr class="{status}"><td>{line}</td><td>{"—" if count is None else count}</td>'
                f"<td><pre>{html.escape(text)}</pre></td></tr>"
            )
        details.append(
            f"<details><summary>{html.escape(record['source'])}: {record['line_percent']:.2f}% "
            f"({record['covered_lines']}/{record['executable_lines']} mapped executable lines)</summary>"
            "<table class='source'><tbody>" + "".join(source_rows) + "</tbody></table></details>"
        )
    explanation = (
        "COBOL line coverage uses GnuCOBOL's source mappings in instrumented generated C. "
        "Only gcov executable lines mapped to src/*.cob enter the COBOL denominator. "
        "Generated runtime code, copybook initialization and declarations are excluded. "
        "Compiler branches include generated control flow and runtime checks; "
        "they are not a count of COBOL business decisions. Native C is reported separately."
    )
    markdown = (
        "# Measured test coverage\n\n"
        f"Test success: {summary['tests']['passed']}; tests: {summary['tests']['count']}.\n\n"
        "| Source | Covered executable lines | Line coverage | Taken compiler branches |\n"
        "| --- | --- | --- | --- |\n" + "\n".join(rows) + "\n\n" + explanation + "\n"
    )
    (OUTPUT / "summary.md").write_text(markdown, encoding="utf-8")
    (OUTPUT / "coverage.info").write_text("\n".join(lcov) + "\n", encoding="utf-8")
    document = (
        "<!doctype html><html lang='en'><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Meridian measured coverage</title><style>"
        "body{font:16px system-ui;margin:2rem auto;max-width:1100px;padding:0 1rem;color:#142e3a}"
        "h1{font-size:1.8rem}details{margin:1rem 0;border:1px solid #d4e0e5;border-radius:8px}"
        "summary{padding:1rem;cursor:pointer;font-weight:600}.source{width:100%;border-collapse:collapse}"
        "td{padding:2px 8px;border-bottom:1px solid #e6ecef}td:first-child,td:nth-child(2){text-align:right}"
        "pre{margin:0;white-space:pre-wrap;font-size:12px}.covered{background:#effcf3}"
        ".missed{background:#ffe8e8}.unmeasured{color:#687c86}.note{line-height:1.6}"
        "</style><body><h1>Measured test coverage</h1>"
        f"<p>Tests passed: {summary['tests']['passed']}; tests run: {summary['tests']['count']}.</p>"
        f"<p>COBOL mapped executable line coverage: {summary['cobol']['line_percent']:.2f}%. "
        f"Native C line coverage: {summary['native_c']['line_percent']:.2f}%.</p>"
        f"<p class='note'>{html.escape(explanation)}</p>"
        "<p>Green rows executed; red rows are executable but uncovered; gray rows have no measured counter. "
        "Execution counts can include durable replay of earlier commands.</p>"
        + "".join(details)
        + "</body></html>"
    )
    (OUTPUT / "index.html").write_text(document, encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cobc", default=os.environ.get("COBC", "cobc"))
    parser.add_argument("--cc", default=os.environ.get("CC", "cc"))
    parser.add_argument("--gcov", help="Gcov command, e.g. 'llvm-cov gcov' or 'gcov-13'")
    parser.add_argument("--pattern", default="test*.py", help="Unittest discovery pattern")
    parser.add_argument("--fail-under", type=float, help="Optional minimum measured COBOL line percentage")
    options = parser.parse_args(argv)
    if options.fail_under is not None and not 0 <= options.fail_under <= 100:
        parser.error("--fail-under must be between 0 and 100")
    compiler = shlex.split(options.cc)
    cobc = shlex.split(options.cobc)
    if not compiler or not cobc:
        parser.error("Compiler commands must not be empty")
    try:
        gcov = find_gcov(compiler, options.gcov)
        engine = build_instrumented(cobc, compiler)
        tests = run_tests(engine, options.pattern)
        files = collect(gcov)
        summary = {
            "format_version": 1,
            "measured_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "toolchain": {
                "cobc": command(cobc + ["--version"]).splitlines()[0],
                "cc": command(compiler + ["--version"]).splitlines()[0],
                "gcov": gcov,
            },
            "tests": tests,
            "cobol": totals(files, "cobol"),
            "native_c": totals(files, "native-c"),
            "files": files,
        }
        write_reports(summary)
        for label, kind in (("COBOL", "cobol"), ("Native C", "native_c")):
            result = summary[kind]
            print(
                f"{label}: {result['covered_lines']}/{result['executable_lines']} executable "
                f"lines ({result['line_percent']:.2f}%)."
            )
        print(f"Reports: {OUTPUT / 'index.html'}")
        if not tests["passed"]:
            return 1
        if options.fail_under is not None and summary["cobol"]["line_percent"] < options.fail_under:
            print(f"COBOL line coverage is below {options.fail_under:.2f}%.", file=sys.stderr)
            return 1
        return 0
    except (CoverageError, OSError) as error:
        print("Coverage failed: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
