"""Secure loopback-only WOPR Windows edition runtime (also testable on Linux)."""
import argparse
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import platform
import re
import secrets
import socket
from socketserver import ThreadingMixIn
import subprocess
import sys
import threading
from urllib.parse import urlsplit
import webbrowser

try:
    from .collector import Collector
    from .feeds import Feeds
    from .speech import BusyError, Speech
except ImportError:
    from collector import Collector
    from feeds import Feeds
    from speech import BusyError, Speech


LOOPBACK = "127.0.0.1"
ASSETS = {"/": ("index.html", "text/html; charset=utf-8"),
          "/index.html": ("index.html", "text/html; charset=utf-8"),
          "/windows.js": ("windows.js", "text/javascript; charset=utf-8"),
          "/windows.css": ("windows.css", "text/css; charset=utf-8"),
          "/data/ne_110m_land.json": ("data/ne_110m_land.json", "application/json"),
          "/data/country-labels.json": ("data/country-labels.json", "application/json"),
          "/world-map.json": ("world-map.json", "application/json")}
MAX_BODY = 4096


def asset_directory():
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "src"
    return Path(__file__).resolve().parent.parent / "src"


class Runtime:
    def __init__(self, assets=None, offline=False, config_path=None):
        self.assets = Path(assets) if assets else asset_directory()
        self.token = secrets.token_urlsafe(32)
        self.collector = Collector()
        self.feeds = Feeds(offline=offline, config_path=config_path)
        self.speech = Speech()
        self.stop = threading.Event()
        self.threads = []
        self.static = {}
        for route, (name, content_type) in ASSETS.items():
            path = self.assets / name
            if (path.is_file() and not path.is_symlink() and
                    path.resolve().is_relative_to(self.assets.resolve()) and
                    path.stat().st_size <= 4 * 1024 * 1024):
                self.static[route] = (path.read_bytes(), content_type)
        if "/" not in self.static:
            raise FileNotFoundError("WOPR dashboard assets are missing")
        # HTML parsers normalize CRLF before hashing script text.
        html = self.static["/"][0].decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        hashes = ["'sha256-" + base64.b64encode(hashlib.sha256(body.encode("utf-8")).digest()).decode() + "'"
                  for body in re.findall(r"<script\b[^>]*>(.*?)</script\s*>", html, re.I | re.S)]
        self.csp = ("default-src 'none'; script-src 'self' " + " ".join(hashes) +
                    "; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; "
                    "connect-src 'self'; media-src 'self' blob:; object-src 'none'; "
                    "base-uri 'none'; frame-ancestors 'none'; form-action 'none'")

    def config(self):
        return {"platform": "windows", "host_platform": platform.system().lower(),
                "session_token": self.token, "feeds_enabled": self.feeds.enabled,
                "speech": self.speech.capability(), "capabilities": dict(self.collector.capabilities)}

    def start(self):
        self.collector.collect()
        def loop(call, interval):
            while not self.stop.is_set():
                try:
                    call()
                except Exception:
                    # A failed platform probe must not kill other telemetry or disclose data.
                    pass
                self.stop.wait(interval)
        for call, interval in ((self.collector.collect, 2), (self.collector.probe_windows, 60),
                               (self.feeds.tick, 1)):
            thread = threading.Thread(target=loop, args=(call, interval), daemon=True)
            thread.start()
            self.threads.append(thread)

    def close(self):
        self.stop.set()
        with self.feeds.lock:
            self.feeds.enabled = False
        self.speech.close()
        for thread in self.threads:
            thread.join(timeout=13)


class Server(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    block_on_close = False
    request_queue_size = 8
    allow_reuse_address = False

    def __init__(self, port, runtime):
        self.runtime = runtime
        self.workers = threading.BoundedSemaphore(8)
        super().__init__((LOOPBACK, port), Handler)
        self.origin = f"http://{LOOPBACK}:{self.server_port}"

    def get_request(self):
        request, address = super().get_request()
        request.settimeout(4)
        return request, address

    def process_request(self, request, client_address):
        if not self.workers.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.workers.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.workers.release()

    def handle_error(self, request, client_address):
        # No request bodies, telemetry, speech text, paths or tokens in logs.
        pass


class Handler(BaseHTTPRequestHandler):
    server_version = "WOPR"
    sys_version = ""

    def log_message(self, *args):
        pass

    def send_error(self, code, message=None, explain=None):
        self.reply(code, {"error": "Request rejected"})

    def reply(self, code, body, content_type="application/json; charset=utf-8"):
        if isinstance(body, dict):
            body = json.dumps(body, allow_nan=False, separators=(",", ":")).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Content-Security-Policy", self.server.runtime.csp)
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        if self.command != "HEAD":
            self.wfile.write(body)

    def secure(self, mutation=False):
        expected_host = f"{LOOPBACK}:{self.server.server_port}"
        if self.headers.get_all("Host") != [expected_host]:
            self.reply(403, {"error": "Invalid Host"})
            return False
        origins = self.headers.get_all("Origin") or []
        if origins and origins != [self.server.origin]:
            self.reply(403, {"error": "Invalid Origin"})
            return False
        if self.headers.get("Sec-Fetch-Site") not in (None, "same-origin", "none"):
            self.reply(403, {"error": "Cross-site request rejected"})
            return False
        if mutation:
            tokens = self.headers.get_all("X-WOPR-Token") or []
            if len(tokens) != 1 or not secrets.compare_digest(tokens[0].encode("utf-8"), self.server.runtime.token.encode("ascii")):
                self.reply(403, {"error": "Session token required"})
                return False
        return True

    def route(self):
        parsed = urlsplit(self.path)
        if parsed.scheme or parsed.netloc or parsed.fragment or "%" in parsed.path or "\\" in parsed.path:
            return None
        return parsed.path

    def do_GET(self):
        if not self.secure():
            return
        route = self.route()
        runtime = self.server.runtime
        if route == "/api/config":
            self.reply(200, runtime.config())
        elif route == "/api/stats.json":
            self.reply(200, runtime.collector.get())
        elif route == "/api/intel":
            self.reply(200, runtime.feeds.get())
        elif route in runtime.static:
            content, content_type = runtime.static[route]
            self.reply(200, content, content_type)
        else:
            self.reply(404, {"error": "Not found"})

    def do_POST(self):
        if not self.secure(mutation=True):
            return
        route = self.route()
        if route not in ("/api/config", "/api/speak", "/api/shutdown"):
            self.reply(404, {"error": "Not found"})
            return
        lengths = self.headers.get_all("Content-Length") or []
        if self.headers.get("Transfer-Encoding") or len(lengths) != 1 or not lengths[0].isdigit():
            self.reply(400, {"error": "A single Content-Length is required"})
            return
        length = int(lengths[0])
        if length > MAX_BODY:
            self.reply(413, {"error": "Request too large"})
            return
        if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
            self.reply(415, {"error": "JSON required"})
            return
        try:
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("Incomplete request")
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("JSON object required")
            runtime = self.server.runtime
            if route == "/api/config":
                if set(data) != {"feeds_enabled"}:
                    raise ValueError("Only feeds_enabled may be configured")
                runtime.feeds.set_enabled(data["feeds_enabled"])
                self.reply(200, runtime.config())
            elif route == "/api/speak":
                if set(data) - {"text", "speed", "pitch", "volume"}:
                    raise ValueError("Unknown speech option")
                wav = runtime.speech.synthesize(data)
                self.reply(200, wav, "audio/wav")
            else:
                if data:
                    raise ValueError("Shutdown body must be empty")
                self.reply(200, {"stopping": True})
                runtime.stop.set()
                threading.Thread(target=self.server.shutdown, daemon=True).start()
        except (ValueError, UnicodeError) as exc:
            self.reply(400, {"error": str(exc)[:100]})
        except BusyError:
            self.reply(429, {"error": "Voice busy; try again"})
        except (OSError, subprocess.SubprocessError):
            self.reply(503, {"error": "Local operation unavailable"})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--port-file", type=Path)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("--port must be 0 through 65535")
    runtime = Runtime(offline=args.offline)
    server = Server(args.port, runtime)
    try:
        runtime.start()
        url = server.origin + "/"
        if args.port_file:
            # Caller-selected handshake file contains no token or telemetry.
            temporary = args.port_file.with_suffix(args.port_file.suffix + ".tmp")
            temporary.write_text(json.dumps({"port": server.server_port, "url": url, "pid": os.getpid()}), encoding="utf-8")
            temporary.replace(args.port_file)
        print(f"WOPR local command center: {url}", flush=True)
        print("Press Ctrl+C to stop. Public feeds require consent.", flush=True)
        if not args.no_browser:
            webbrowser.open(url)
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        runtime.close()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
