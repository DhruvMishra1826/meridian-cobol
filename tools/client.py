"""Safe subprocess boundary; all domain decisions remain in COBOL."""

import os
import stat
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

    def __init__(self, message, returncode=None, kind=None):
        super().__init__(message)
        self.returncode = returncode
        self.kind = kind


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
        selected_engine = engine or os.environ.get("MERIDIAN_ENGINE", "").strip()
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
            raise MeridianError("Engine is missing. Run make first.", 3, "missing_engine") from exc
        except subprocess.TimeoutExpired as exc:
            raise MeridianError(
                "Engine timed out; inspect the journal before retrying a mutation", 3, "engine_timeout"
            ) from exc
        except PermissionError as exc:
            raise MeridianError("The COBOL engine is not executable", 3, "engine_unavailable") from exc
        except (OSError, UnicodeError) as exc:
            raise MeridianError("Unable to execute the COBOL engine", 3, "engine_unavailable") from exc
        lines = result.stdout.splitlines()
        if not lines or "|" not in lines[0]:
            raise MeridianError("Engine returned an invalid response", result.returncode or 3)
        status, message = lines[0].split("|", 1)
        if status == "ERROR":
            kind = None
            if result.returncode == 3:
                if message.startswith(
                    ("Invalid journal business event", "Journal checksum, sequence or encoding failure")
                ):
                    kind = "journal_corrupt"
                elif message.startswith("Cannot open journal:"):
                    kind = "journal_unavailable"
                elif message.startswith("Journal durability failure"):
                    kind = "storage_unavailable"
                else:
                    kind = "engine_unavailable"
            raise MeridianError(message or "Operation rejected", result.returncode, kind)
        if status != "OK" or result.returncode != 0:
            raise MeridianError("Engine failed: " + (message or "unknown error"), result.returncode)
        return {"ok": True, "message": message, "rows": [line.split("|") for line in lines[1:] if line]}

    def readiness(self):
        """Probe engine and storage without returning paths, history or balances."""
        try:
            if not self.engine.is_file():
                return {"ok": False, "status": "not_ready", "reason": "missing_engine"}
            if not os.access(str(self.engine), os.X_OK):
                return {"ok": False, "status": "not_ready", "reason": "engine_unavailable"}
            directory_mode = self.data_dir.stat().st_mode
            if (
                not stat.S_ISDIR(directory_mode)
                or not directory_mode & stat.S_IWUSR
                or not directory_mode & stat.S_IXUSR
                or not os.access(str(self.data_dir), os.W_OK | os.X_OK)
            ):
                return {"ok": False, "status": "not_ready", "reason": "storage_permission"}
            if self.journal.is_symlink():
                return {"ok": False, "status": "not_ready", "reason": "journal_corrupt"}
            if self.journal.exists():
                mode = self.journal.stat().st_mode
                if not stat.S_ISREG(mode):
                    return {"ok": False, "status": "not_ready", "reason": "journal_corrupt"}
                if (
                    not mode & stat.S_IRUSR
                    or not mode & stat.S_IWUSR
                    or not os.access(str(self.journal), os.R_OK | os.W_OK)
                ):
                    return {"ok": False, "status": "not_ready", "reason": "storage_permission"}
            self.execute("SUMMARY")
            return {"ok": True, "status": "ready"}
        except PermissionError:
            reason = "storage_permission"
        except OSError:
            reason = "storage_unavailable"
        except MeridianError as exc:
            reason = exc.kind or "engine_unavailable"
            if reason == "journal_unavailable":
                reason = self._journal_open_failure()
        return {"ok": False, "status": "not_ready", "reason": reason}

    def _journal_open_failure(self):
        """Disambiguate the native open error's permissions/header/tail cases."""
        try:
            with self.journal.open("rb") as stream:
                header = stream.read(len(b"MERIDIAN-JOURNAL-1\n"))
                if header != b"MERIDIAN-JOURNAL-1\n":
                    return "journal_corrupt"
                stream.seek(-1, os.SEEK_END)
                if stream.read(1) != b"\n":
                    return "journal_corrupt"
        except PermissionError:
            return "storage_permission"
        except OSError:
            return "storage_unavailable"
        return "storage_unavailable"
