"""Exercise the process boundary, local HTTP security and real-engine integration."""

import csv
import http.client
import io
import json
import os
import stat
import subprocess
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tools.client import ROOT, Client, MeridianError, validate_command, validate_report
from tools.meridian import main, read_batch
from tools.server import create_server


class ClientBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.client = Client(Path(self.temp.name) / "private")

    def test_private_directory(self):
        self.assertEqual(stat.S_IMODE(self.client.data_dir.stat().st_mode), 0o700)

    def test_explicit_engine_precedes_environment(self):
        external = Path(self.temp.name) / "external-engine"
        explicit = Path(self.temp.name) / "explicit-engine"
        with patch.dict(os.environ, {"MERIDIAN_ENGINE": str(external)}):
            self.assertEqual(Client(self.client.data_dir).engine, external.resolve())
            self.assertEqual(Client(self.client.data_dir, engine=explicit).engine, explicit.resolve())

    def test_symlink_directory_rejected(self):
        alias = Path(self.temp.name) / "alias"
        alias.symlink_to(self.client.data_dir, target_is_directory=True)
        with self.assertRaises(MeridianError):
            Client(alias)

    def test_commands_reject_controls_and_byte_overflow(self):
        for value in [
            "",
            None,
            3,
            "STOCK\nPOST|A",
            "STOCK\r",
            "STOCK\x00",
            "STOCK\x7f",
            "é" * 2049,
            "\ud800",
        ]:
            with self.subTest(value=repr(value)), self.assertRaises(MeridianError):
                validate_command(value)
        self.assertEqual(validate_command("X" * 4096), "X" * 4096)

    def test_report_allowlist_and_argument_counts(self):
        for value in [
            "POST|A",
            "BATCH|ITEM|A",
            "STOCK|A",
            "AGING",
            "STATEMENT|",
            "SUMMARY|",
            "INVOICE-SHOW|A|B",
        ]:
            with self.subTest(value=value), self.assertRaises(MeridianError):
                validate_report(value)
        self.assertEqual(validate_report("AGING|20261013"), "AGING|20261013")

    def test_protocol_and_shell_free_process(self):
        response = subprocess.CompletedProcess(
            [], 0, "OK|Accepted\nACCOUNT|CASH|ASSET|Cash $(touch nope)|0\n", ""
        )
        with patch("tools.client.subprocess.run", return_value=response) as call:
            command = "ACCOUNT|CASH|ASSET|Cash $(touch nope)"
            result = self.client.execute(command)
            self.assertEqual(result["rows"][0][3], "Cash $(touch nope)")
            args, options = call.call_args
            self.assertEqual(args[0][2], command)
            self.assertIs(options["shell"], False)
            self.assertEqual(options["timeout"], 20)

    def test_rejection_and_malformed_protocol(self):
        for status, text, expected in [
            (2, "ERROR|Duplicate reference\n", "Duplicate reference"),
            (3, "OK|Unexpected success\n", "Engine failed"),
            (0, "malformed\n", "invalid response"),
            (0, "WHAT|unknown\n", "Engine failed"),
        ]:
            response = subprocess.CompletedProcess([], status, text, "")
            with self.subTest(text=text), patch("tools.client.subprocess.run", return_value=response):
                with self.assertRaisesRegex(MeridianError, expected):
                    self.client.execute("SUMMARY")

    def test_startup_and_timeout_failures(self):
        failures = [
            (FileNotFoundError(), "missing"),
            (subprocess.TimeoutExpired("engine", 20), "inspect the journal"),
        ]
        for failure, message in failures:
            with self.subTest(message=message), patch("tools.client.subprocess.run", side_effect=failure):
                with self.assertRaisesRegex(MeridianError, message) as caught:
                    self.client.execute("SUMMARY")
                self.assertEqual(caught.exception.returncode, 3)

    def test_atomic_batch_file(self):
        path = Path(self.temp.name) / "operations.txt"
        path.write_text(
            "# Bootstrap\n\nACCOUNT|CASH|ASSET|Cash\nACCOUNT|EQUITY|EQUITY|Equity\n", encoding="utf-8"
        )
        self.assertEqual(read_batch(path), "BATCH|ACCOUNT|CASH|ASSET|Cash~ACCOUNT|EQUITY|EQUITY|Equity")
        for content in [
            "",
            "BATCH|ACCOUNT|X|ASSET|X",
            "ACCOUNT|X|ASSET|Bad~Name",
            "\n".join(["CLOSE|20260101"] * 65),
            "POST|" + "a" * 4096,
        ]:
            path.write_text(content, encoding="utf-8")
            with self.subTest(content=content[:30]), self.assertRaises(MeridianError):
                read_batch(path)

    def test_cli_json_report(self):
        with patch("tools.meridian.Client") as client, patch("builtins.print") as output:
            client.return_value.execute.return_value = {
                "ok": True,
                "message": "Ready",
                "rows": [["RESULT", "0"]],
            }
            self.assertEqual(main(["--data-dir", self.temp.name, "--format", "json", "report", "SUMMARY"]), 0)
            self.assertEqual(json.loads(output.call_args.args[0])["rows"], [["RESULT", "0"]])

    def test_csv_escapes_formula_text_and_preserves_signed_amounts(self):
        rows = [
            ["ACCOUNT", "A", "ASSET", "=1+1", "-12345"],
            ["ACCOUNT", "B", "ASSET", "+SUM(A1:A2)", "2345"],
            ["ACCOUNT", "C", "ASSET", "@SUM(A1)", "0"],
            ["ACCOUNT", "D", "ASSET", "-1+1", "-1"],
        ]
        output = io.StringIO()
        with patch("tools.meridian.Client") as client, redirect_stdout(output):
            client.return_value.execute.return_value = {"ok": True, "message": "Ready", "rows": rows}
            self.assertEqual(main(["--data-dir", self.temp.name, "--format", "csv", "report", "ACCOUNTS"]), 0)
        exported = list(csv.reader(io.StringIO(output.getvalue())))
        self.assertEqual([row[3] for row in exported], ["'=1+1", "'+SUM(A1:A2)", "'@SUM(A1)", "'-1+1"])
        self.assertEqual([row[4] for row in exported], ["-12345", "2345", "0", "-1"])


class RecordingClient:
    def __init__(self):
        self.calls = []

    def execute(self, command):
        validate_command(command)
        self.calls.append(command)
        if command == "BROKEN":
            raise MeridianError("Journal integrity check failed", 3)
        return {"ok": True, "message": "Ready", "rows": [["RESULT", "0"]]}


class HTTPBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.client = RecordingClient()
        self.server = create_server(self.temp.name, port=0, token="", client=self.client)
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.origin = "http://127.0.0.1:%s" % self.server.server_port

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        self.addCleanup(connection.close)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        data = response.read()
        return response.status, dict(response.getheaders()), data

    def post(self, command, origin=None, extra=None):
        headers = {
            "Content-Type": "application/json",
            "Origin": origin if origin is not None else self.origin,
        }
        headers.update(extra or {})
        return self.request("POST", "/api/command", json.dumps({"command": command}), headers)

    def test_health_and_static_assets(self):
        status, headers, data = self.request("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(data)["ok"])
        self.assertEqual(self.client.calls, ["SUMMARY"])
        for path in ["/", "/app.js", "/style.css"]:
            status, headers, data = self.request("GET", path)
            self.assertEqual(status, 200)
            self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertEqual(self.request("GET", "/../../tools/client.py")[0], 404)
        self.assertEqual(self.request("GET", "/?asset=../../journal.dat")[0], 404)

    def test_get_report_is_read_only(self):
        self.assertEqual(self.request("GET", "/api/report?command=STOCK")[0], 200)
        count = len(self.client.calls)
        for path in [
            "/api/report?command=POST%7CA",
            "/api/report?command=STOCK&command=JOURNAL",
            "/api/report?file=journal.dat",
            "/api/report?command=STOCK%0APOST",
        ]:
            with self.subTest(path=path):
                self.assertEqual(self.request("GET", path)[0], 422)
        self.assertEqual(len(self.client.calls), count)

    def test_origin_and_fetch_site_checks(self):
        self.assertEqual(self.post("ACCOUNT|CASH|ASSET|Cash")[0], 200)
        count = len(self.client.calls)
        for origin in [
            "http://attacker.example",
            "null",
            self.origin + "/path",
            self.origin + "#fragment",
            "http://name@127.0.0.1:%s" % self.server.server_port,
        ]:
            with self.subTest(origin=origin):
                self.assertEqual(self.post("POST|X", origin)[0], 403)
        self.assertEqual(self.post("POST|X", extra={"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(
            self.request("POST", "/api/command", "{}", {"Content-Type": "application/json"})[0], 403
        )
        self.assertEqual(len(self.client.calls), count)

    def test_host_rebinding_and_cors(self):
        self.assertEqual(
            self.request(
                "GET", "/api/health", headers={"Host": "attacker.example:%s" % self.server.server_port}
            )[0],
            403,
        )
        self.assertEqual(
            self.request("OPTIONS", "/api/command", headers={"Origin": "http://attacker.example"})[0], 403
        )
        self.assertEqual(self.client.calls, [])

    def test_body_limits_and_types(self):
        headers = {"Content-Type": "application/json", "Origin": self.origin}
        self.assertEqual(self.request("POST", "/api/command", "x" * 4097, headers)[0], 413)
        for body in [
            "{}",
            "[]",
            '{"command": "STOCK", "file":"/etc/passwd"}',
            '{"command":"STOCK","command":"JOURNAL"}',
            "not-json",
            '{"command":"STOCK\\nPOST"}',
        ]:
            with self.subTest(body=body):
                self.assertIn(self.request("POST", "/api/command", body, headers)[0], [400, 422])
        self.assertEqual(
            self.request(
                "POST",
                "/api/command",
                "command=STOCK",
                {"Content-Type": "application/x-www-form-urlencoded", "Origin": self.origin},
            )[0],
            415,
        )
        self.assertEqual(self.post("SUMMARY", extra={"Transfer-Encoding": "chunked"})[0], 400)
        self.assertEqual(self.post("BROKEN")[0], 503)

    def test_malformed_host_does_not_crash_request_handler(self):
        valid = "127.0.0.1:%s" % self.server.server_port
        for host in [
            "127.0.0.1:invalid",
            valid + "?query",
            valid + "#fragment",
            valid + "/path",
            "user@" + valid,
            "127.0.0.1:999999",
            "[unterminated",
            valid + " ",
            "127.0.0.1:0",
        ]:
            with self.subTest(host=host):
                self.assertEqual(self.request("GET", "/api/health", headers={"Host": host})[0], 403)
        self.assertEqual(self.client.calls, [])
        self.assertEqual(self.request("GET", "/api/health")[0], 200)

    def test_deep_json_rejected_and_server_remains_healthy(self):
        nested = '{"command":' + "[" * 1100 + "0" + "]" * 1100 + "}"
        headers = {"Content-Type": "application/json", "Origin": self.origin}
        # Decoder recursion limits vary by Python version: reject during parsing
        # with 400, or after parsing when the command is not a string with 422.
        self.assertIn(self.request("POST", "/api/command", nested, headers)[0], (400, 422))
        self.assertEqual(self.client.calls, [])
        self.assertEqual(self.request("GET", "/api/health")[0], 200)

    def test_remote_binding_requires_strong_token(self):
        with self.assertRaisesRegex(ValueError, "MERIDIAN_API_TOKEN"):
            create_server(self.temp.name, host="0.0.0.0", port=0, token="", client=self.client)
        with self.assertRaisesRegex(ValueError, "24 printable"):
            create_server(self.temp.name, port=0, token="short", client=self.client)
        token = "test-token-with-at-least-24-characters"
        server = create_server(self.temp.name, host="0.0.0.0", port=0, token=token, client=self.client)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            connection.request("GET", "/api/health")
            response = connection.getresponse()
            response.read()
            self.assertEqual(response.status, 401)
            connection.close()
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            connection.request("GET", "/api/health", headers={"Authorization": "Bearer " + token})
            response = connection.getresponse()
            response.read()
            self.assertEqual(response.status, 200)
            connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


@unittest.skipUnless(
    Path(os.environ.get("MERIDIAN_ENGINE", str(ROOT / "build/meridian"))).exists(),
    "Build the COBOL engine with make",
)
class RealEngineInterfaceTests(unittest.TestCase):
    def test_real_process_parser_and_persistence(self):
        with tempfile.TemporaryDirectory() as data:
            client = Client(data)
            result = client.execute(
                "BATCH|ACCOUNT|CASH|ASSET|Operating cash~ACCOUNT|EQUITY|EQUITY|Owner equity~POST|OPEN_1|20261013|CASH|EQUITY|12345|Capital"
            )
            self.assertTrue(result["ok"])
            balances = Client(data).execute("ACCOUNTS")["rows"]
            self.assertEqual(balances[0], ["ACCOUNT", "CASH", "ASSET", "Operating cash", "12345"])
            self.assertEqual(balances[1][-1], "-12345")
            with self.assertRaises(MeridianError):
                client.execute("POST|OPEN_1|20261013|CASH|EQUITY|1|Duplicate")
            self.assertEqual(client.execute("ACCOUNTS")["rows"], balances)


if __name__ == "__main__":
    unittest.main()
