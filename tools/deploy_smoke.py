"""Exercise an isolated Terraform deployment with synthetic journal records."""

import argparse
import json
import os
import secrets
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {
    ".git",
    ".terraform",
    ".venv",
    "node_modules",
    "build",
    "var",
    "data",
    "demo-data",
    "restored-data",
    "assessment-results",
    "backups",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
}


def ignore_private(_directory: str, names: list[str]) -> set[str]:
    return {
        name
        for name in names
        if name in EXCLUDED
        or (name.startswith(".env") and name != ".env.example")
        or name.endswith((".tfstate", ".tfstate.backup", ".tfplan", ".tfvars", ".tfvars.json"))
    }


def unused_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def run(
    command: list[str], directory: Path, environment: dict[str, str], *, required: bool = True
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(  # noqa: S603 -- Executable paths and argument arrays, never a shell.
        command,
        cwd=directory,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=900,
        check=False,
    )
    if required and result.returncode:
        token = environment.get("TF_VAR_api_token", "")
        output = result.stdout.replace(token, "[redacted]") if token else result.stdout
        raise RuntimeError(f"{Path(command[0]).name} {command[1]} failed:\n{output[-12000:]}")
    return result


class Probe:
    def __init__(self, port: int, token: str):
        self.origin = f"http://127.0.0.1:{port}"
        self.token = token

    def request(
        self, path: str, *, authenticated: bool = True, command: str | None = None
    ) -> tuple[int, bytes]:
        headers = {"Authorization": "Bearer " + self.token} if authenticated else {}
        body = None
        if command is not None:
            body = json.dumps({"command": command}).encode()
            headers.update({"Origin": self.origin, "Content-Type": "application/json"})
        request = Request(self.origin + path, data=body, headers=headers)  # noqa: S310 -- Fixed loopback origin.
        try:
            with urlopen(request, timeout=5) as response:  # noqa: S310 -- Fixed loopback origin only.
                return response.status, response.read()
        except HTTPError as error:
            return error.code, error.read()

    def ready(self) -> None:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                status, content = self.request("/ready")
                if status == 200 and json.loads(content).get("status") == "ready":
                    return
            except (OSError, URLError):
                pass
            time.sleep(1)
        raise RuntimeError("Synthetic deployment did not become ready within 90 seconds")

    def report(self, command: str) -> dict[str, Any]:
        status, content = self.request("/api/report?" + urlencode({"command": command}))
        if status != 200:
            raise RuntimeError(f"Report {command} failed with HTTP {status}")
        return json.loads(content)


def exercise(terraform: str, docker: str, docker_host: str) -> dict[str, Any]:
    name = "meridian-smoke-" + secrets.token_hex(5)
    token = secrets.token_urlsafe(32)
    port = unused_port()
    environment = dict(os.environ)
    environment.update(
        TF_IN_AUTOMATION="1",
        TF_VAR_api_token=token,
        TF_VAR_name=name,
        TF_VAR_host_port=str(port),
        TF_VAR_docker_host=docker_host,
        DOCKER_HOST=docker_host,
    )
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="meridian-terraform-") as temporary:
        source = Path(temporary) / "source"
        shutil.copytree(ROOT, source, ignore=ignore_private)
        module = source / "infra" / "terraform"
        docker_command = [docker, "--host", docker_host]
        try:
            run([terraform, "init", "-input=false", "-lockfile=readonly", "-no-color"], module, environment)
            print("Applying isolated Terraform deployment", flush=True)
            run([terraform, "apply", "-auto-approve", "-input=false", "-no-color"], module, environment)
            probe = Probe(port, token)
            probe.ready()
            if probe.request("/ready", authenticated=False)[0] != 401:
                raise RuntimeError("Readiness accepted an unauthenticated request")
            if probe.request("/metrics", authenticated=False)[0] != 401:
                raise RuntimeError("Metrics accepted an unauthenticated request")
            command = (
                "BATCH|ACCOUNT|CASH|ASSET|Synthetic cash~ACCOUNT|CAPITAL|EQUITY|Synthetic capital"
                "~POST|DEPLOY1|20261014|CASH|CAPITAL|12345|Synthetic deployment check"
            )
            status, content = probe.request("/api/command", command=command)
            if status != 200 or not json.loads(content).get("ok"):
                raise RuntimeError(f"Synthetic posting failed with HTTP {status}")
            before = probe.report("ACCOUNTS")
            balances = {row[1]: int(row[4]) for row in before["rows"]}
            if balances != {"CASH": 12345, "CAPITAL": -12345}:
                raise RuntimeError("Synthetic posting produced unexpected balances")
            print("Checking journal persistence across container restart", flush=True)
            run(docker_command + ["restart", name], module, environment)
            probe.ready()
            if probe.report("ACCOUNTS") != before:
                raise RuntimeError("Restart changed synthetic journal balances")
            if probe.report("TRIAL")["rows"][-1] != ["TOTAL", "12345", "12345"]:
                raise RuntimeError("Trial balance changed after restart")
            status, metrics = probe.request("/metrics")
            if status != 200 or b"meridian_http_requests_total" not in metrics:
                raise RuntimeError("Protected metrics did not contain request counters")
            destroy = run(
                [terraform, "plan", "-destroy", "-input=false", "-no-color"],
                module,
                environment,
                required=False,
            )
            if destroy.returncode == 0 or "prevent_destroy" not in destroy.stdout:
                raise RuntimeError("Terraform allowed destruction of the protected journal volume")
            return {
                "ok": True,
                "checks": [
                    "authenticated readiness",
                    "protected metrics",
                    "balanced posting",
                    "restart persistence",
                    "protected volume",
                ],
                "elapsed_seconds": round(time.monotonic() - started, 2),
            }
        finally:
            # Only this invocation's randomly named, synthetic resources are eligible for removal.
            errors = []
            for arguments in (
                ["container", "rm", "--force", name],
                ["network", "rm", name + "-network"],
                ["volume", "rm", name + "-journal"],
                ["image", "rm", name + ":managed"],
            ):
                result = run(docker_command + arguments, module, environment, required=False)
                if result.returncode and not any(
                    message in result.stdout.lower() for message in ("no such", "not found", "does not exist")
                ):
                    errors.append(result.stdout.strip())
            if errors:
                raise RuntimeError("Synthetic resource cleanup failed: " + "; ".join(errors))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--terraform", default="terraform")
    parser.add_argument("--docker", default="docker")
    parser.add_argument(
        "--docker-host", default=os.environ.get("TF_VAR_docker_host", "unix:///var/run/docker.sock")
    )
    arguments = parser.parse_args()
    if not arguments.docker_host.startswith("unix:///"):
        parser.error("Use a local Docker Unix socket")
    terraform = shutil.which(arguments.terraform)
    docker = shutil.which(arguments.docker)
    if not terraform or not docker:
        parser.error("Terraform and Docker executables are required")
    os.umask(0o077)
    result = exercise(terraform, docker, arguments.docker_host)
    destination = ROOT / "build" / "test-results" / "terraform-smoke.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
