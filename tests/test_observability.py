"""Probe recovery, content-free request logs and bounded concurrent metrics."""

import http.client
import json
import logging
import os
import secrets
import shutil
import tempfile
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

from tools.client import ROOT, Client
from tools.observability import JSONFormatter, Metrics
from tools.server import create_server

ENGINE = Path(os.environ.get("MERIDIAN_ENGINE", "").strip() or str(ROOT / "build" / "meridian"))


class CaptureHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []
        self.condition = threading.Condition()
        self.setFormatter(JSONFormatter())

    def emit(self, record):
        encoded = self.format(record)
        with self.condition:
            self.records.append(encoded)
            self.condition.notify_all()

    def wait_for_count(self, count):
        with self.condition:
            return self.condition.wait_for(lambda: len(self.records) >= count, timeout=3)


class HealthyClient:
    def __init__(self):
        self.calls = []

    def execute(self, command):
        self.calls.append(command)
        return {
            "ok": True,
            "message": "Private Customer account",
            "rows": [["CUSTOMER", "PRIVATE", "Private Customer", "private@example.com"]],
        }

    def readiness(self):
        return {"ok": True, "status": "ready"}


class ServerTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.handler = CaptureHandler()
        self.logger = logging.getLogger("meridian-observability-test-" + uuid.uuid4().hex)
        self.logger.addHandler(self.handler)
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        self.addCleanup(self.logger.removeHandler, self.handler)
        self.addCleanup(self.handler.close)
        self.token = secrets.token_urlsafe(32)
        self.observed_requests = 0

    def start(self, client):
        self.client = client
        self.server = create_server(
            self.temp.name, port=0, token=self.token, client=client, logger=self.logger
        )
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def request(self, path, method="GET", command=None, authenticated=True, headers=None):
        values = {"Authorization": "Bearer " + self.token} if authenticated else {}
        values.update(headers or {})
        body = None
        if command is not None:
            values["Content-Type"] = "application/json"
            values["Origin"] = "http://127.0.0.1:%s" % self.server.server_port
            body = json.dumps({"command": command})
        with closing(
            http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        ) as connection:
            connection.request(method, path, body=body, headers=values)
            response = connection.getresponse()
            result = response.status, dict(response.getheaders()), response.read()
        self.observed_requests += 1
        self.assertTrue(self.handler.wait_for_count(self.observed_requests))
        return result


class HTTPObservabilityTests(ServerTestCase):
    def setUp(self):
        super().setUp()
        self.start(HealthyClient())

    def test_public_liveness_has_no_engine_or_business_data(self):
        status, _, body = self.request("/health", authenticated=False)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"ok": True, "status": "alive"})
        self.assertEqual(self.client.calls, [])
        for path in ("/ready", "/metrics", "/api/health"):
            with self.subTest(path=path):
                self.assertEqual(self.request(path, authenticated=False)[0], 401)
        self.assertEqual(self.request("/ready")[0], 200)
        self.assertEqual(self.request("/health", headers={"Host": "attacker.example"})[0], 403)

    def test_structured_logs_redact_request_and_response_content(self):
        private_path = "/private@example.com?token=" + self.token
        status, headers, _ = self.request(
            "/api/command",
            method="POST",
            command="CUSTOMER|PRIVATE|Private Customer|private@example.com",
            headers={"X-Request-ID": "user-secret-id"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(self.request("/api/report?command=STATEMENT%7CPRIVATE")[0], 200)
        self.assertEqual(self.request(private_path)[0], 404)
        self.assertEqual(self.request("/health", method="PRIVATE_METHOD")[0], 501)
        self.assertTrue(self.handler.wait_for_count(4))
        encoded = "\n".join(self.handler.records)
        for content in [
            self.token,
            "Private Customer",
            "private@example.com",
            "CUSTOMER|",
            "STATEMENT%7C",
            "PRIVATE_METHOD",
            "user-secret-id",
            self.temp.name,
        ]:
            self.assertNotIn(content, encoded)
        records = [json.loads(line) for line in self.handler.records]
        self.assertEqual(
            set(records[0]), {"timestamp", "event", "request_id", "method", "route", "status", "duration_ms"}
        )
        self.assertEqual(records[0]["request_id"], headers["X-Request-ID"])
        self.assertRegex(records[0]["request_id"], r"^[0-9a-f]{32}$")
        self.assertEqual(records[0]["route"], "/api/command")
        self.assertEqual(records[2]["route"], "unmatched")
        self.assertEqual(records[3]["method"], "OTHER")
        self.assertEqual(len({record["request_id"] for record in records}), 4)
        self.assertTrue(all(record["duration_ms"] >= 0 for record in records))

    def test_metrics_count_statuses_without_sensitive_labels(self):
        self.request("/health", authenticated=False)
        self.request("/ready", authenticated=False)
        self.request("/missing/private@example.com")
        self.assertTrue(self.handler.wait_for_count(3))
        status, headers, body = self.request("/metrics")
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/plain; version=0.0.4"))
        text = body.decode("ascii")
        self.assertIn('meridian_http_requests_total{method="GET",route="/health",status="200"} 1', text)
        self.assertIn('meridian_http_requests_total{method="GET",route="/ready",status="401"} 1', text)
        self.assertIn('meridian_http_requests_total{method="GET",route="unmatched",status="404"} 1', text)
        self.assertIn('route="/health",le="+Inf"} 1', text)
        self.assertNotIn("private@example.com", text)
        self.assertNotIn(self.token, text)


class MetricsConcurrencyTests(unittest.TestCase):
    def test_parallel_updates_preserve_counters_and_histograms(self):
        metrics = Metrics()

        def worker():
            for _ in range(250):
                metrics.record("GET", "/health", 200, 0.08)

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(worker) for _ in range(8)]
            for future in futures:
                future.result()
        snapshot = metrics.snapshot()
        self.assertEqual(snapshot["requests"], {("GET", "/health", "200"): 2000})
        latency = snapshot["latencies"][("GET", "/health")]
        self.assertEqual(latency["count"], 2000)
        self.assertAlmostEqual(latency["sum"], 160.0)
        self.assertEqual(latency["buckets"], [0, 0, 2000, 2000, 2000, 2000, 2000, 2000])
        latency["buckets"][2] = 0
        self.assertEqual(metrics.snapshot()["latencies"][("GET", "/health")]["buckets"][2], 2000)

    def test_arbitrary_dimensions_collapse_to_fixed_labels(self):
        metrics = Metrics()
        for index in range(1000):
            metrics.record(
                "secret-method-" + str(index), "/customer/private-" + str(index), 10000 + index, 0.01
            )
        snapshot = metrics.snapshot()
        self.assertEqual(snapshot["requests"], {("OTHER", "unmatched", "other"): 1000})
        self.assertEqual(len(snapshot["latencies"]), 1)
        self.assertNotIn("private", metrics.render().decode("ascii"))
        self.assertNotIn("secret-method", metrics.render().decode("ascii"))


@unittest.skipUnless(ENGINE.exists(), "Build the COBOL engine with make")
class ReadinessRecoveryTests(ServerTestCase):
    def start_real(self, engine=None):
        client = Client(Path(self.temp.name) / "data", engine=engine or ENGINE)
        self.start(client)
        return client

    def assert_reason(self, reason):
        status, _, body = self.request("/ready")
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body), {"ok": False, "status": "not_ready", "reason": reason})
        self.assertNotIn(self.temp.name.encode(), body)
        self.assertEqual(self.request("/health", authenticated=False)[0], 200)

    def test_missing_engine_installation_recovers_without_restart(self):
        missing = Path(self.temp.name) / "missing-engine"
        self.start_real(engine=missing)
        self.assert_reason("missing_engine")
        shutil.copy2(ENGINE, missing)
        self.assertEqual(self.request("/ready")[0], 200)
        self.assertEqual(self.request("/api/health")[0], 200)

    def test_corrupt_header_checksum_and_incomplete_tail_fail_closed(self):
        client = self.start_real()
        self.assertEqual(self.request("/ready")[0], 200)
        client.execute("ACCOUNT|A|ASSET|Private account")
        valid = client.journal.read_bytes()
        altered = valid.replace(b"Private account", b"Changed account")
        for corruption in (b"invalid header\n", altered, valid + b"incomplete tail"):
            with self.subTest(corruption=corruption[:20]):
                client.journal.write_bytes(corruption)
                self.assert_reason("journal_corrupt")
                client.journal.write_bytes(valid)
                self.assertEqual(self.request("/ready")[0], 200)

    def test_storage_permission_and_recovery(self):
        client = self.start_real()
        self.assertEqual(self.request("/ready")[0], 200)
        for path, restricted, normal in ((client.data_dir, 0o500, 0o700), (client.journal, 0o400, 0o600)):
            try:
                os.chmod(path, restricted)
                self.assert_reason("storage_permission")
            finally:
                os.chmod(path, normal)
            self.assertEqual(self.request("/ready")[0], 200)


if __name__ == "__main__":
    unittest.main()
