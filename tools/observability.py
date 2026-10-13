"""Bounded HTTP telemetry with no request content or sensitive dimensions."""

import json
import logging
import math
import sys
import threading
import time
from datetime import datetime, timezone

ROUTES = frozenset(
    {"/health", "/ready", "/metrics", "/api/health", "/api/report", "/api/command", "static", "unmatched"}
)
METHODS = frozenset({"GET", "POST", "OPTIONS", "HEAD", "PUT", "DELETE", "OTHER"})
STATUSES = frozenset({200, 400, 401, 403, 404, 405, 408, 411, 413, 414, 415, 422, 500, 501, 503, 505})
BUCKETS = (0.005, 0.025, 0.1, 0.5, 1.0, 5.0, 20.0, 60.0)


def fixed_route(path, assets=()):
    if path in assets:
        return "static"
    return path if path in ROUTES else "unmatched"


class JSONFormatter(logging.Formatter):
    """Emit only a fixed set of server-generated fields."""

    def format(self, record):
        value = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            "event": "http_request",
            "request_id": record.request_id,
            "method": record.method,
            "route": record.route,
            "status": record.status,
            "duration_ms": record.duration_ms,
        }
        return json.dumps(value, separators=(",", ":"))


def request_logger():
    logger = logging.getLogger("meridian.http")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


class Metrics:
    """One lock protects cumulative counters and latency histograms."""

    def __init__(self):
        self.started = time.monotonic()
        self._lock = threading.Lock()
        self._requests = {}
        self._latencies = {}

    def record(self, method, route, status, duration):
        method = method if method in METHODS else "OTHER"
        route = route if route in ROUTES else "unmatched"
        status = str(status) if status in STATUSES else "other"
        duration = max(0.0, duration) if math.isfinite(duration) else 0.0
        with self._lock:
            key = (method, route, status)
            self._requests[key] = self._requests.get(key, 0) + 1
            latency = self._latencies.setdefault(
                (method, route), {"count": 0, "sum": 0.0, "buckets": [0] * len(BUCKETS)}
            )
            latency["count"] += 1
            latency["sum"] += duration
            for index, boundary in enumerate(BUCKETS):
                if duration <= boundary:
                    latency["buckets"][index] += 1

    def snapshot(self):
        with self._lock:
            requests = dict(self._requests)
            latencies = {
                key: {"count": value["count"], "sum": value["sum"], "buckets": list(value["buckets"])}
                for key, value in self._latencies.items()
            }
        return {"requests": requests, "latencies": latencies}

    def render(self):
        snapshot = self.snapshot()
        lines = [
            "# HELP meridian_http_requests_total Completed HTTP requests by fixed route, method and status.",
            "# TYPE meridian_http_requests_total counter",
        ]
        for (method, route, status), count in sorted(snapshot["requests"].items()):
            labels = f'method="{method}",route="{route}",status="{status}"'
            lines.append(f"meridian_http_requests_total{{{labels}}} {count}")
        lines.extend(
            [
                "# HELP meridian_http_request_duration_seconds HTTP request duration including engine execution.",
                "# TYPE meridian_http_request_duration_seconds histogram",
            ]
        )
        for (method, route), value in sorted(snapshot["latencies"].items()):
            labels = f'method="{method}",route="{route}"'
            for boundary, count in zip(BUCKETS, value["buckets"]):
                lines.append(
                    f'meridian_http_request_duration_seconds_bucket{{{labels},le="{boundary:g}"}} {count}'
                )
            lines.append(
                f'meridian_http_request_duration_seconds_bucket{{{labels},le="+Inf"}} {value["count"]}'
            )
            lines.append(f"meridian_http_request_duration_seconds_count{{{labels}}} {value['count']}")
            lines.append(f"meridian_http_request_duration_seconds_sum{{{labels}}} {value['sum']:.9f}")
        lines.extend(
            [
                "# HELP meridian_process_uptime_seconds Seconds since the HTTP server was created.",
                "# TYPE meridian_process_uptime_seconds gauge",
                f"meridian_process_uptime_seconds {max(0.0, time.monotonic() - self.started):.3f}",
            ]
        )
        return ("\n".join(lines) + "\n").encode("ascii")
