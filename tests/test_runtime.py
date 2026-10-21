"""Portable stdlib tests. Run: python -m unittest discover -s tests -p 'test_runtime*.py'."""
import http.client
import ipaddress
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
import urllib.error

from windows.collector import Collector, rate, safe, usage_record, has_network_address
from windows.feeds import Feeds, MAX_RESPONSE, NoRedirect, SOURCES, fetch_json, normalize
from windows.speech import BusyError, Speech, discover
from windows.wopr import LOOPBACK, MAX_BODY, Runtime, Server


FIXTURES = {
    "isc": {"infocon": {"status": "green", "date": "2026-10-21"}},
    "cisa": {"count": 1, "catalogVersion": "1", "dateReleased": "2026-10-21T00:00:00Z",
             "vulnerabilities": [{"cveID": "CVE-2026-0001", "dateAdded": "2026-10-21",
                                  "vendorProject": "Example", "vulnerabilityName": "<script>bad()</script>"}]},
    "noaa": [["time_tag", "Kp"], ["2026-10-21 00:00:00", "3.33"]],
    "usgs": {"metadata": {"generated": 1792540800000}, "features": [
        {"id": "test", "properties": {"mag": 3.2, "place": "<img src=x onerror=bad()>",
                                     "time": 1792540800000, "url": "javascript:bad()"},
         "geometry": {"coordinates": [10.5, 20.5, 3]}}]},
}


def fixture_fetch(url):
    key = next(key for key, (_, source, _) in SOURCES.items() if source == url)
    return FIXTURES[key]


class CollectorTests(unittest.TestCase):
    def test_missing_network_counters_are_not_zero_traffic(self):
        with mock.patch("windows.collector.psutil.net_io_counters", return_value=None):
            result = Collector().collect()
        for key in ("rx_mb", "tx_mb", "rx_rate_kbs", "tx_rate_kbs"):
            self.assertIsNone(result["network"][key])

    def test_windows_local_area_connection_is_not_a_loopback_name(self):
        address = str(ipaddress.IPv4Address(0xC0000201))  # RFC 5737 documentation address
        self.assertTrue(has_network_address({"name": "Local Area Connection", "addresses": [address]}))
        self.assertFalse(has_network_address({"addresses": ["::1"]}))
    def test_counter_reset_and_first_sample(self):
        self.assertIsNone(rate(1000, None, 2))
        self.assertIsNone(rate(1000, 2000, 2))
        self.assertIsNone(rate(1000, 0, 0))
        self.assertEqual(rate(4096, 2048, 2), 1)

    def test_access_denied_is_unavailable(self):
        import psutil
        self.assertIsNone(safe(mock.Mock(side_effect=psutil.AccessDenied())))
        self.assertIsNone(usage_record(None)["percent"])

    def test_real_stats_contract_and_no_fabricated_sensors(self):
        collector = Collector()
        result = collector.collect()
        json.dumps(result, allow_nan=False)
        for key in ("hostname", "os", "timestamp", "uptime", "uptime_seconds", "cpu", "memory",
                    "disk", "network", "processes", "services", "log_entries", "auth_failures",
                    "per_core", "top_processes", "battery", "disks", "adapters", "windows_services", "security"):
            self.assertIn(key, result)
        self.assertEqual(result["platform"], "windows")
        self.assertIsNone(result["cpu"]["temp_c"])
        self.assertIsNone(result["cpu"]["gpu_temp_c"])
        self.assertLessEqual(len(result["top_processes"]), 10)
        self.assertTrue(all(set(p) == {"name", "cpu_percent", "memory_mb"} for p in result["top_processes"]))
        self.assertIsNone(result["security"]["defender"]["enabled"])
        self.assertTrue(result["log_entries"])
        self.assertIn("Read-only telemetry", result["log_entries"][0]["msg"])
        collector.events.extend([{"time": "", "msg": "fixture"}] * 30)
        self.assertEqual(len(collector.events), 20)

    def test_no_windows_probe_on_linux(self):
        with mock.patch("windows.collector.os.name", "posix"), mock.patch("windows.collector.subprocess.run") as run:
            Collector().probe_windows()
            run.assert_not_called()

    def test_denied_windows_probe_stays_unavailable(self):
        with mock.patch("windows.collector.os.name", "nt"), \
                mock.patch("windows.collector.psutil.win_service_get", create=True,
                           side_effect=OSError("denied")), \
                mock.patch("windows.collector.subprocess.run", side_effect=OSError("denied")):
            collector = Collector()
            collector.probe_windows()
        self.assertTrue(all(v["status"] == "unavailable" for v in collector.slow["windows_services"]))
        self.assertIsNone(collector.slow["security"]["firewall"]["enabled"])

    def test_successful_windows_probe_uses_fixed_readonly_command(self):
        data = {"defender": {"enabled": True, "signatures_updated": "2026-10-21T00:00:00Z"},
                "firewall": [True, False, True]}
        with mock.patch("windows.collector.os.name", "nt"), \
                mock.patch("windows.collector.psutil.win_service_get", create=True) as service, \
                mock.patch("windows.collector.subprocess.run") as run:
            service.return_value.status.return_value = "running"
            run.return_value.stdout = json.dumps(data).encode()
            collector = Collector()
            collector.probe_windows()
            args, kwargs = run.call_args
            self.assertIn("-NonInteractive", args[0])
            self.assertNotIn("shell", kwargs)
        self.assertEqual(collector.slow["security"]["defender"]["state"], "available")
        self.assertFalse(collector.slow["security"]["firewall"]["enabled"])


class FeedTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "settings.json"
        self.feeds = Feeds(config_path=self.path, fetcher=fixture_fetch)

    def test_no_network_without_consent(self):
        self.feeds.fetcher = mock.Mock()
        self.feeds.tick()
        self.feeds.fetcher.assert_not_called()
        self.assertTrue(all(v["state"] == "offline" for v in self.feeds.get()["feeds"].values()))
        self.assertFalse(self.path.exists())

    def test_consent_persists_only_boolean(self):
        self.feeds.set_enabled(True)
        self.assertTrue(all(v["state"] == "loading" for v in self.feeds.get()["feeds"].values()))
        self.assertEqual(json.loads(self.path.read_text()), {"feeds_enabled": True})
        self.assertTrue(Feeds(config_path=self.path).enabled)
        self.feeds.set_enabled(False)
        self.assertFalse(Feeds(config_path=self.path).enabled)

    def test_forced_offline_cannot_enable(self):
        feeds = Feeds(offline=True, config_path=self.path)
        with self.assertRaises(ValueError):
            feeds.set_enabled(True)
        self.assertFalse(feeds.enabled)

    def test_boolean_consent_only(self):
        for invalid in ("true", 1, None):
            with self.assertRaises(ValueError):
                self.feeds.set_enabled(invalid)

    def test_independent_normalized_feeds(self):
        self.feeds.set_enabled(True)
        self.feeds.tick()
        feeds = self.feeds.get()["feeds"]
        self.assertTrue(all(v["state"] == "live" for v in feeds.values()))
        self.assertEqual(feeds["isc"]["data"]["level"], "green")
        self.assertEqual(feeds["noaa"]["data"]["kp"], 3.33)
        self.assertEqual(feeds["usgs"]["data"]["items"][0]["url"], "")
        self.assertIn("<script>", feeds["cisa"]["data"]["items"][0]["name"])
        self.assertTrue(feeds["noaa"]["observed_at"].endswith("Z"))
        old = feeds["isc"]["fetched_at"]
        self.feeds.tick()
        self.assertEqual(self.feeds.get()["feeds"]["isc"]["fetched_at"], old)

    def test_current_isc_root_shape_and_historical_wrapper(self):
        root, observed = normalize("isc", {"status": "yellow"})
        self.assertEqual(root["level"], "yellow")
        self.assertIsNone(observed)
        wrapped, observed = normalize("isc", FIXTURES["isc"])
        self.assertEqual(wrapped["level"], "green")
        self.assertEqual(observed, "2026-10-21")

    def test_current_noaa_object_rows_and_historical_array_rows(self):
        current = [{"time_tag": "2026-10-21T03:00:00", "Kp": 3.33,
                    "a_running": 18, "station_count": 6}]
        result, observed = normalize("noaa", current)
        self.assertEqual(result, {"kp": 3.33, "observed_at": "2026-10-21T03:00:00Z"})
        self.assertEqual(observed, result["observed_at"])
        historical, _ = normalize("noaa", FIXTURES["noaa"])
        self.assertEqual(historical["kp"], 3.33)

    def test_current_feed_shapes_through_fetch_manager(self):
        self.feeds.set_enabled(True)
        def fetch(url):
            if url == SOURCES["isc"][1]:
                return {"status": "yellow"}
            if url == SOURCES["noaa"][1]:
                return [{"time_tag": "2026-10-21T03:00:00Z", "Kp": 2}]
            return fixture_fetch(url)
        self.feeds.fetcher = fetch
        self.feeds.tick()
        self.assertTrue(all(v["state"] == "live" for v in self.feeds.get()["feeds"].values()))

    def test_backoff_stale_and_offline_states(self):
        self.feeds.set_enabled(True)
        self.feeds.tick()
        self.feeds.next_due = dict.fromkeys(SOURCES, 0)
        self.feeds.fetcher = mock.Mock(side_effect=OSError("private error should not escape"))
        self.feeds.tick()
        self.assertTrue(all(v["state"] == "stale" for v in self.feeds.get()["feeds"].values()))
        self.assertTrue(all(n > time.monotonic() for n in self.feeds.next_due.values()))
        self.assertNotIn("private error", json.dumps(self.feeds.get()))
        self.feeds.set_enabled(False)
        self.assertTrue(all(v["state"] == "offline" for v in self.feeds.get()["feeds"].values()))

    def test_first_failure_is_unavailable_and_retry_after_respected(self):
        self.feeds.set_enabled(True)
        self.feeds.fetcher = mock.Mock(side_effect=urllib.error.HTTPError("fixed", 429, "slow", {"Retry-After": "900"}, None))
        self.feeds.tick()
        self.assertTrue(all(v["state"] == "unavailable" for v in self.feeds.get()["feeds"].values()))
        self.assertTrue(all(n > time.monotonic() + 890 for n in self.feeds.next_due.values()))

    def test_retry_after_cannot_shorten_five_minute_minimum(self):
        self.feeds.set_enabled(True)
        for value in ("0", "30", "not-a-valid-date"):
            self.feeds.next_due = dict.fromkeys(SOURCES, 0)
            self.feeds.failures = dict.fromkeys(SOURCES, 0)
            self.feeds.fetcher = mock.Mock(side_effect=urllib.error.HTTPError(
                "fixed", 429, "slow", {"Retry-After": value}, None))
            self.feeds.tick()
            self.assertTrue(all(n > time.monotonic() + 290 for n in self.feeds.next_due.values()))

    def test_invalid_coordinates_kp_and_level(self):
        for key, data in (("isc", {"infocon": {"status": "healthy"}}),
                          ("noaa", [["2026-01-01", 10]]),
                          ("usgs", {"features": [{"properties": {}, "geometry": {"coordinates": [200, 0]}}]})):
            with self.assertRaises(ValueError):
                normalize(key, data)

    def test_fetch_response_size_and_no_redirects(self):
        response = mock.MagicMock()
        response.headers = {}
        response.read1.side_effect = [b"x" * 65536] * (MAX_RESPONSE // 65536) + [b"x"]
        response.__enter__.return_value = response
        with mock.patch("windows.feeds.urllib.request.build_opener") as build:
            build.return_value.open.return_value = response
            with self.assertRaises(ValueError):
                fetch_json(SOURCES["isc"][1])
            self.assertEqual(response.read1.call_args.args[0], 1)
        with self.assertRaises(ValueError):
            NoRedirect().redirect_request(None, None, 302, "", {}, "http://not-allowed/")


class SpeechTests(unittest.TestCase):
    def test_closed_speech_cannot_launch(self):
        speech = Speech(executable="/fixed/espeak-ng")
        speech.close()
        with mock.patch("windows.speech.subprocess.run") as run:
            with self.assertRaises(FileNotFoundError):
                speech.synthesize({"text": "test"})
            run.assert_not_called()
    def test_frozen_speech_prefers_sibling_then_internal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / "internal"
            for path in (root / "speech", bundle / "speech"):
                path.mkdir(parents=True)
                (path / "espeak-ng.exe").write_bytes(b"fixture")
            with mock.patch.object(sys, "frozen", True, create=True), \
                    mock.patch.object(sys, "executable", str(root / "WOPR.exe")), \
                    mock.patch.object(sys, "_MEIPASS", str(bundle), create=True):
                self.assertEqual(discover(), str(root / "speech" / "espeak-ng.exe"))
                (root / "speech" / "espeak-ng.exe").unlink()
                self.assertEqual(discover(), str(bundle / "speech" / "espeak-ng.exe"))
    def test_invalid_input_and_controls(self):
        speech = Speech(executable="/fixed/espeak-ng")
        for data in ({"text": ""}, {"text": "x" * 501}, {"text": "\x00"},
                     {"text": "a", "speed": True}, {"text": "a", "pitch": 100},
                     {"text": "a", "volume": -1}):
            with self.assertRaises(ValueError):
                speech.synthesize(data)

    def test_fixed_args_stdin_no_shell(self):
        speech = Speech(executable="/fixed/espeak-ng")
        wav = b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 40
        def run(args, **kwargs):
            kwargs["stdout"].write(wav)
            self.assertNotIn("shell", kwargs)
            self.assertEqual(kwargs["input"], b"--help; $(do-not-execute)")
            self.assertNotIn("--help; $(do-not-execute)", args)
            self.assertEqual(kwargs["timeout"], 15)
        with mock.patch("windows.speech.subprocess.run", side_effect=run):
            self.assertEqual(speech.synthesize({"text": "--help; $(do-not-execute)"}), wav)

    def test_concurrency_limit(self):
        speech = Speech(executable="/fixed/espeak-ng")
        speech.slot.acquire()
        try:
            with self.assertRaises(BusyError):
                speech.synthesize({"text": "test"})
        finally:
            speech.slot.release()

    def test_timeout_releases_slot(self):
        speech = Speech(executable="/fixed/espeak-ng")
        with mock.patch("windows.speech.subprocess.run", side_effect=subprocess.TimeoutExpired("espeak", 15)):
            with self.assertRaises(subprocess.TimeoutExpired):
                speech.synthesize({"text": "test"})
        self.assertTrue(speech.slot.acquire(blocking=False))

    def test_real_local_wav(self):
        executable = discover()
        if not executable:
            self.skipTest("eSpeak is not installed")
        wav = Speech(executable).synthesize({"text": "Greetings professor Falken."})
        self.assertEqual(wav[:4], b"RIFF")
        self.assertEqual(wav[8:12], b"WAVE")
        self.assertGreater(len(wav), 1000)


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.runtime = Runtime(config_path=Path(cls.directory.name) / "settings.json")
        cls.runtime.collector.collect()
        cls.server = Server(0, cls.runtime)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(2)
        cls.runtime.close()
        cls.directory.cleanup()

    def request(self, method="GET", path="/api/config", body=None, headers=None, token=False):
        connection = http.client.HTTPConnection(LOOPBACK, self.server.server_port, timeout=10)
        h = dict(headers or {})
        if token:
            h["X-WOPR-Token"] = self.runtime.token
        if isinstance(body, dict):
            body = json.dumps(body)
            h.setdefault("Content-Type", "application/json")
        connection.request(method, path, body=body, headers=h)
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def test_loopback_only(self):
        self.assertTrue(ipaddress.ip_address(self.server.server_address[0]).is_loopback)
        self.assertEqual(self.server.address_family, socket.AF_INET)

    def test_config_and_security_headers(self):
        status, headers, raw = self.request()
        self.assertEqual(status, 200)
        config = json.loads(raw)
        self.assertEqual(config["platform"], "windows")
        self.assertGreaterEqual(len(config["session_token"]), 40)
        self.assertIn("sha256-", headers["Content-Security-Policy"])
        self.assertNotIn("unsafe-inline", headers["Content-Security-Policy"].split(";")[1])
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertEqual(headers["X-Frame-Options"], "DENY")

    def test_host_dns_rebinding_rejected(self):
        for host in ("attacker.example", "localhost", "localhost:" + str(self.server.server_port), "0.0.0.0"):
            self.assertEqual(self.request(headers={"Host": host})[0], 403)

    def test_cross_origin_get_and_post(self):
        for method in ("GET", "POST"):
            self.assertEqual(self.request(method, headers={"Origin": "https://evil.example"},
                                          body={} if method == "POST" else None, token=True)[0], 403)
        self.assertEqual(self.request(headers={"Sec-Fetch-Site": "cross-site"})[0], 403)

    def test_token_missing_invalid_nonascii(self):
        for headers in ({}, {"X-WOPR-Token": "wrong"}, {"X-WOPR-Token": "\u00e9"}):
            self.assertEqual(self.request("POST", "/api/config", {"feeds_enabled": False}, headers=headers)[0], 403)

    def test_same_origin_mutation_and_persistence(self):
        status, _, _ = self.request("POST", "/api/config", {"feeds_enabled": False},
                                    headers={"Origin": self.server.origin}, token=True)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(self.runtime.feeds.path.read_text()), {"feeds_enabled": False})

    def test_unknown_config_and_wrong_boolean(self):
        for data in ({"feeds_enabled": "true"}, {"feeds_enabled": False, "command": "bad"}):
            self.assertEqual(self.request("POST", "/api/config", data, token=True)[0], 400)

    def test_request_body_limits_and_types(self):
        self.assertEqual(self.request("POST", "/api/speak", b"x" * (MAX_BODY + 1), token=True)[0], 413)
        self.assertEqual(self.request("POST", "/api/speak", "{}", token=True)[0], 415)
        self.assertEqual(self.request("POST", "/api/speak", "{", {"Content-Type": "application/json"}, token=True)[0], 400)

    def test_no_proxy_shell_traversal_or_directory_access(self):
        for path in ("/windows/wopr.py", "/wopr-stats.sh", "/api/exec", "/api/speak?text=test",
                     "/../SECURITY.md", "/%2e%2e/SECURITY.md", "/data/", "/?file=../SECURITY.md"):
            status = self.request(path=path)[0]
            self.assertEqual(status, 200 if path.startswith("/?") else 404, path)

    def test_static_dashboard_and_offline_map(self):
        self.assertEqual(self.request(path="/")[0], 200)
        self.assertEqual(self.request(path="/data/ne_110m_land.json")[0], 200)

    def test_stats_and_offline_intel(self):
        status, _, raw = self.request(path="/api/stats.json")
        self.assertEqual(status, 200)
        self.assertIn("memory", json.loads(raw))
        _, _, raw = self.request(path="/api/intel")
        self.assertTrue(all(record["state"] == "offline" for record in json.loads(raw)["feeds"].values()))

    def test_speak_returns_wav_or_visible_unavailable(self):
        status, headers, body = self.request("POST", "/api/speak", {"text": "Shall we play a game?"}, token=True)
        if not self.runtime.speech.executable:
            self.assertEqual(status, 503)
        else:
            self.assertEqual(status, 200)
            self.assertEqual(headers["Content-Type"], "audio/wav")
            self.assertEqual(body[:4], b"RIFF")

    def test_duplicate_host_and_content_length(self):
        with socket.create_connection((LOOPBACK, self.server.server_port), timeout=5) as client:
            host = f"{LOOPBACK}:{self.server.server_port}"
            client.sendall(f"GET /api/config HTTP/1.1\r\nHost: {host}\r\nHost: {host}\r\n\r\n".encode())
            self.assertIn(b"403", client.recv(1024).split(b"\r\n")[0])
        with socket.create_connection((LOOPBACK, self.server.server_port), timeout=5) as client:
            client.sendall((f"POST /api/config HTTP/1.1\r\nHost: {host}\r\nX-WOPR-Token: {self.runtime.token}"
                            "\r\nContent-Length: 2\r\nContent-Length: 2\r\nContent-Type: application/json\r\n\r\n{}").encode())
            self.assertIn(b"400", client.recv(1024).split(b"\r\n")[0])

    def test_worker_limit_drops_excess_connections(self):
        for _ in range(8):
            self.assertTrue(self.server.workers.acquire(blocking=False))
        try:
            with socket.create_connection((LOOPBACK, self.server.server_port), timeout=5) as client:
                client.sendall(b"GET /api/config HTTP/1.1\r\n\r\n")
                try:
                    self.assertEqual(client.recv(1024), b"")
                except ConnectionResetError:
                    pass
        finally:
            for _ in range(8):
                self.server.workers.release()

    def test_head_and_options_not_supported(self):
        for method in ("HEAD", "OPTIONS", "PUT"):
            self.assertEqual(self.request(method)[0], 501)


class CLITests(unittest.TestCase):
    def test_real_cli_port_file_and_secure_shutdown(self):
        with tempfile.TemporaryDirectory(prefix="WOPR test spaces ") as directory:
            handshake = Path(directory) / "port.json"
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve().parents[1] / "windows" / "wopr.py"),
                                        "--no-browser", "--offline", "--port", "0", "--port-file", str(handshake)],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 20
                while not handshake.exists() and time.monotonic() < deadline and process.poll() is None:
                    time.sleep(0.05)
                self.assertTrue(handshake.exists())
                info = json.loads(handshake.read_text())
                self.assertEqual(info["pid"], process.pid)
                self.assertGreater(info["port"], 0)
                conn = http.client.HTTPConnection(LOOPBACK, info["port"], timeout=10)
                conn.request("GET", "/api/config")
                config = json.loads(conn.getresponse().read())
                conn.close()
                conn = http.client.HTTPConnection(LOOPBACK, info["port"], timeout=10)
                conn.request("POST", "/api/shutdown", "{}", {"Content-Type": "application/json",
                                                            "X-WOPR-Token": config["session_token"]})
                self.assertEqual(conn.getresponse().status, 200)
                conn.close()
                stdout, stderr = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 0, stderr.decode())
                self.assertNotIn(config["session_token"].encode(), stdout)
            finally:
                if process.poll() is None:
                    process.terminate()
                process.communicate(timeout=10)


if __name__ == "__main__":
    unittest.main()
