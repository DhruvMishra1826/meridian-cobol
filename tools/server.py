"""Dependency-free local HTTP console. COBOL is the only business engine."""

import argparse
import ipaddress
import json
import os
import secrets
import sys
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.client import ROOT, Client, MeridianError, validate_report

MAX_BODY = 4096
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
}


def is_loopback(host):
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


class MeridianHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class Handler(BaseHTTPRequestHandler):
    server_version = "Meridian/1"
    sys_version = ""
    protocol_version = "HTTP/1.0"

    def __init__(self, *args, client, token, local, **kwargs):
        self.client = client
        self.token = token
        self.local = local
        super().__init__(*args, **kwargs)

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, format, *args):
        # Avoid writing commands, customer data, or tokens into access logs.
        print("Meridian HTTP %s %s" % (self.command, urlsplit(self.path).path), file=sys.stderr)

    def respond(self, status, content, content_type="application/json; charset=utf-8"):
        if not isinstance(content, bytes):
            content = json.dumps(content, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'",
        )
        self.end_headers()
        self.wfile.write(content)

    def error(self, status, message):
        self.respond(status, {"ok": False, "message": message, "rows": []})

    def valid_host(self):
        values = self.headers.get_all("Host", [])
        if len(values) != 1 or any(char in values[0] for char in "/\\@?#"):
            return False
        if any(ord(char) < 33 or ord(char) > 126 for char in values[0]):
            return False
        try:
            host = urlsplit("http://" + values[0])
            hostname = host.hostname
            port = host.port if host.port is not None else 80
            if (
                not hostname
                or not 0 < port <= 65535
                or host.path
                or host.query
                or host.fragment
                or host.username is not None
                or host.password is not None
            ):
                return False
            return (port == self.server.server_port and is_loopback(hostname)) if self.local else True
        except ValueError:
            return False

    def authorized(self):
        if not self.valid_host():
            self.error(403, "Host header is not allowed")
            return False
        if self.token:
            supplied = self.headers.get("Authorization", "")
            expected = "Bearer " + self.token
            if not secrets.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
                self.error(401, "A valid bearer token is required")
                return False
        return True

    def valid_origin(self):
        values = self.headers.get_all("Origin", [])
        if len(values) != 1:
            return False
        try:
            origin = urlsplit(values[0])
            host = urlsplit(origin.scheme + "://" + self.headers.get("Host", ""))
            default_port = 443 if origin.scheme == "https" else 80
            allowed_schemes = {"http"} if self.local else {"http", "https"}
            return (
                origin.scheme in allowed_schemes
                and origin.hostname == host.hostname
                and (origin.port or default_port) == (host.port or default_port)
                and not origin.path
                and not origin.query
                and not origin.fragment
                and not origin.username
                and not origin.password
            )
        except ValueError:
            return False

    def do_GET(self):
        if not self.valid_host():
            self.error(403, "Host header is not allowed")
            return
        try:
            route = urlsplit(self.path)
            if route.path in ASSETS and not route.query:
                filename, media = ASSETS[route.path]
                self.respond(200, (ROOT / "web" / filename).read_bytes(), media)
                return
            if not route.path.startswith("/api/"):
                self.error(404, "Route not found")
                return
            if not self.authorized():
                return
            if route.path == "/api/health" and not route.query:
                self.respond(200, self.client.execute("SUMMARY"))
            elif route.path == "/api/report":
                query = parse_qs(route.query, keep_blank_values=True, max_num_fields=2)
                if set(query) != {"command"} or len(query["command"]) != 1:
                    raise MeridianError("Supply one command query parameter")
                self.respond(200, self.client.execute(validate_report(query["command"][0])))
            else:
                self.error(404, "Route not found")
        except MeridianError as exc:
            self.error(422 if exc.returncode in (None, 2) else 503, str(exc))
        except (OSError, ValueError) as exc:
            self.error(
                400, "Invalid request" if isinstance(exc, ValueError) else "Unable to read application asset"
            )

    def do_POST(self):
        if not self.authorized():
            return
        if urlsplit(self.path).path != "/api/command" or urlsplit(self.path).query:
            self.error(404, "Route not found")
            return
        if not self.valid_origin() or self.headers.get("Sec-Fetch-Site", "same-origin") not in {
            "same-origin",
            "none",
        }:
            self.error(403, "A matching Origin header is required")
            return
        if self.headers.get("Transfer-Encoding"):
            self.error(400, "Transfer-Encoding is not supported")
            return
        if self.headers.get_content_type() != "application/json":
            self.error(415, "Content-Type must be application/json")
            return
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit():
            self.error(411, "Supply one valid Content-Length header")
            return
        if len(lengths[0]) > 5:
            self.error(413, "Request body exceeds 4096 bytes")
            return
        size = int(lengths[0])
        if size > MAX_BODY:
            self.error(413, "Request body exceeds 4096 bytes")
            return
        if not size:
            self.error(400, "Request body is empty")
            return
        try:
            raw = self.rfile.read(size)
            if len(raw) != size:
                raise ValueError("Incomplete body")
            body = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object)
            if not isinstance(body, dict) or set(body) != {"command"}:
                raise ValueError("Expected one command field")
            result = self.client.execute(body["command"])
            self.respond(200, result)
        except (ValueError, UnicodeError, TimeoutError, RecursionError):
            self.error(400, "Body must be a JSON object containing one command string")
        except MeridianError as exc:
            self.error(422 if exc.returncode in (None, 2) else 503, str(exc))

    def do_OPTIONS(self):
        self.error(403, "Cross-origin requests are not allowed")


def create_server(data_dir, host="127.0.0.1", port=8080, token=None, client=None):
    if not isinstance(port, int) or not 0 <= port <= 65535:
        raise ValueError("Port must be between 0 and 65535")
    token = os.environ.get("MERIDIAN_API_TOKEN", "") if token is None else token
    local = is_loopback(host)
    if not local and not token:
        raise ValueError("Set MERIDIAN_API_TOKEN before binding to a non-loopback address")
    if token and (len(token.encode("utf-8")) < 24 or any(ord(c) < 33 or ord(c) > 126 for c in token)):
        raise ValueError("MERIDIAN_API_TOKEN must have at least 24 printable ASCII characters without spaces")
    handler = partial(Handler, client=client or Client(data_dir), token=token, local=local)
    return MeridianHTTPServer((host, port), handler)


def run(data_dir, host="127.0.0.1", port=8080):
    with create_server(data_dir, host, port) as server:
        print("Meridian console: http://%s:%s" % (host, server.server_port), flush=True)
        server.serve_forever(poll_interval=0.25)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir", default=os.environ.get("MERIDIAN_DATA_DIR", str(Path.home() / ".local/share/meridian"))
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    options = parser.parse_args()
    try:
        run(options.data_dir, options.host, options.port)
    except (ValueError, MeridianError, OSError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2) from error
    except KeyboardInterrupt:
        pass
