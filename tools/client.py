"""Safe subprocess boundary; all domain decisions remain in COBOL."""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_COMMAND_BYTES = 4096
REPORTS = frozenset(
    {
        "ACCOUNTS",
        "TRIAL",
        "JOURNAL",
        "STATEMENT",
        "SUMMARY",
        "STOCK",
        "MOVEMENTS",
        "REORDER",
        "CUSTOMERS",
        "INVOICES",
        "INVOICE-SHOW",
        "AGING",
    }
)


class MeridianError(Exception):
    """An invalid request, rejected business operation, or engine failure."""

    def __init__(self, message, returncode=None):
        super().__init__(message)
        self.returncode = returncode


def validate_command(command):
    if not isinstance(command, str) or not command:
        raise MeridianError("Command must be a nonempty string")
    try:
        size = len(command.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise MeridianError("Command must be valid UTF-8") from exc
    if size > MAX_COMMAND_BYTES:
        raise MeridianError("Command exceeds 4096 bytes")
    if any(ord(char) < 32 or ord(char) == 127 for char in command):
        raise MeridianError("Command cannot contain control characters")
    return command


def validate_report(command):
    validate_command(command)
    parts = command.split("|")
    operation = parts[0]
    if operation not in REPORTS:
        raise MeridianError("Only report commands are allowed here")
    expected = 2 if operation in {"STATEMENT", "INVOICE-SHOW", "AGING"} else 1
    if len(parts) != expected or (expected == 2 and not parts[1]):
        raise MeridianError("Report has the wrong number of arguments")
    return command


class Client:
    def __init__(self, data_dir, engine=None):
        directory = Path(data_dir).expanduser()
        if directory.is_symlink():
            raise MeridianError("Data directory cannot be a symbolic link")
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not directory.is_dir():
            raise MeridianError("Data path must be a directory")
        os.chmod(str(directory), 0o700)
        self.data_dir = directory.resolve()
        self.journal = self.data_dir / "journal.dat"
        if self.journal.is_symlink():
            raise MeridianError("Journal cannot be a symbolic link")
        selected_engine = engine or os.environ.get("MERIDIAN_ENGINE")
        self.engine = Path(selected_engine).resolve() if selected_engine else ROOT / "build" / "meridian"

    def execute(self, pipe_command):
        command = validate_command(pipe_command)
        try:
            result = subprocess.run(
                [str(self.engine), str(self.journal), command],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding="utf-8",
                errors="strict",
                timeout=20,
                check=False,
                shell=False,
            )
        except FileNotFoundError as exc:
            raise MeridianError("Engine is missing. Run make first.", 3) from exc
        except subprocess.TimeoutExpired as exc:
            raise MeridianError(
                "Engine timed out; inspect the journal before retrying a mutation", 3
            ) from exc
        except (OSError, UnicodeError) as exc:
            raise MeridianError("Unable to execute the COBOL engine: " + str(exc), 3) from exc
        lines = result.stdout.splitlines()
        if not lines or "|" not in lines[0]:
            raise MeridianError("Engine returned an invalid response", result.returncode or 3)
        status, message = lines[0].split("|", 1)
        if status == "ERROR":
            raise MeridianError(message or "Operation rejected", result.returncode)
        if status != "OK" or result.returncode != 0:
            raise MeridianError("Engine failed: " + (message or "unknown error"), result.returncode)
        return {"ok": True, "message": message, "rows": [line.split("|") for line in lines[1:] if line]}
