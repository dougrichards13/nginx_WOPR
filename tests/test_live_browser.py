"""Optional real Chromium integration against the secure loopback runtime.

Install requirements-test.txt and Chromium (or Playwright's browser).
Use WOPR_TEST_SPEECH to test a newly built eSpeak binary instead of PATH.
"""
import importlib.util
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from windows.wopr import Runtime, Server
from windows.speech import Speech

HAS_PLAYWRIGHT = importlib.util.find_spec("playwright") is not None


@unittest.skipUnless(HAS_PLAYWRIGHT, "Install requirements-test.txt for live browser checks")
class LiveBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.temporary = tempfile.TemporaryDirectory(prefix="wopr-live-browser-")
        cls.runtime = Runtime(offline=True, config_path=Path(cls.temporary.name) / "settings.json")
        if os.environ.get("WOPR_TEST_SPEECH"):
            cls.runtime.speech = Speech(executable=os.environ["WOPR_TEST_SPEECH"])
        cls.server = Server(0, cls.runtime)
        cls.runtime.start()
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.playwright = sync_playwright().start()
        executable = os.environ.get("WOPR_BROWSER_EXECUTABLE") or shutil.which("chromium")
        kwargs = {"executable_path": executable} if executable else {}
        try:
            cls.browser = cls.playwright.chromium.launch(headless=True, **kwargs)
        except Exception:
            cls.playwright.stop()
            cls.server.shutdown()
            cls.runtime.close()
            cls.server.server_close()
            cls.temporary.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.runtime.close()
        cls.server.server_close()
        cls.thread.join(timeout=3)
        cls.temporary.cleanup()

    def setUp(self):
        self.context = self.browser.new_context(viewport={"width": 1920, "height": 1080})
        self.page = self.context.new_page()
        self.errors = []
        self.external = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.on("console", lambda msg: self.errors.append(msg.text)
                     if msg.type == "error" and ("Content Security Policy" in msg.text
                                                or "Refused to load" in msg.text) else None)
        origin = self.server.origin
        self.page.on("request", lambda req: self.external.append(req.url)
                     if not req.url.startswith((origin + "/", "data:", "blob:")) else None)
        self.page.goto(origin + "/")
        self.page.locator("#skip-boot").click()
        self.wait_js("runtimeConfig?.platform === 'windows' && lastStats?.timestamp")

    def wait_js(self, expression, timeout=20):
        # Evaluate via the debugging protocol, not injected eval-based pollers.
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.page.evaluate(expression):
                return
            self.page.wait_for_timeout(50)
        self.fail("Browser condition timed out: " + expression)

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [], "JavaScript/CSP failure")
        self.assertEqual(self.external, [], "Unexpected external browser request")

    def test_real_runtime_csp_font_helper_controls_and_games(self):
        self.wait_js("document.fonts.check('18px VT323')")
        self.assertIn("LIVE", self.page.locator("#data-status").inner_text())
        self.assertIn("N/A", self.page.locator("#cpu-temp").inner_text())
        self.assertFalse(self.page.locator("#thermal-readings").is_visible())
        self.assertTrue(self.page.locator("#activity-readings").is_visible())
        self.assertEqual(self.page.locator("#world-clocks time").count(), 4)
        self.assertEqual(self.page.locator("#map-mode").input_value(), "daylight")
        self.assertIn("OFFLINE READY", self.page.locator("#map-state").inner_text())
        self.assertGreater(self.page.locator("#per-core span").count(), 0)
        self.assertTrue(self.page.locator("#feed-consent").is_visible())
        self.assertIn("OFFLINE", self.page.locator("#intel-feeds").inner_text())
        self.assertTrue(self.page.locator("body").evaluate("el=>el.classList.contains('wallboard')"))
        self.page.locator("#wallboard-toggle").click()
        self.assertTrue(self.page.locator("#terminal-box").is_visible())
        # Direct API fixture calls deliberately test stale rendering without freezing the backend.
        self.page.evaluate("updateTelemetryFreshness({timestamp:new Date(Date.now()-60000).toISOString()})")
        self.assertIn("STALE", self.page.locator("#data-status").inner_text())
        self.page.evaluate("fetchStats()")
        self.wait_js("document.getElementById('data-status').textContent.includes('LIVE')")
        self.page.locator("#voice-toggle").click()  # Don't speak reference examples in this test.
        self.page.locator("#joshua-input").fill("azure storage")
        self.page.locator("#joshua-input").press("Enter")
        self.assertIn("az storage", self.page.locator("#terminal-output").inner_text())
        self.assertGreater(self.page.locator("#terminal-output a[href^='https://learn.microsoft.com/']").count(), 0)
        self.page.locator("#privacy-toggle").click()
        self.assertIn("MASKED", self.page.locator("#header-hostname").inner_text())
        self.assertEqual(self.page.locator("#net-ip").inner_text(), "MASKED")
        self.page.locator("#theme-toggle").click()
        self.assertTrue(self.page.locator("body").evaluate("el=>el.classList.contains('amber')"))
        self.page.locator("#motion-toggle").click()
        self.page.locator("#map-mode").select_option("earthquakes")
        self.assertIn("REAL PUBLIC EVENTS", self.page.locator("#map-title").inner_text())
        self.assertFalse(self.page.locator(".map-overlay").is_visible())
        for name, title in (("tictactoe", "TIC-TAC-TOE"), ("missile", "MISSILE COMMAND"), ("snake", "SNAKE")):
            self.page.locator(f"[data-game='{name}']").click()
            self.assertTrue(self.page.locator("#game-modal").is_visible())
            self.assertIn(title, self.page.locator("#game-title").inner_text())
            self.page.locator("#game-close").click()
            self.assertFalse(self.page.locator("#game-modal").is_visible())
        if os.environ.get("WOPR_SCREENSHOT"):
            self.page.locator("#consent-offline").click()
            self.page.locator("#map-mode").select_option("daylight")
            self.page.locator("#wallboard-toggle").click()
            self.page.wait_for_timeout(150)
            self.page.screenshot(path=os.environ["WOPR_SCREENSHOT"], full_page=True)

    def test_real_voice_post_and_browser_wav_playback(self):
        if not self.runtime.speech.executable:
            self.skipTest("No local speech engine; packaged smoke test requires one")
        with self.page.expect_response(
            lambda response: response.url.endswith("/api/speak") and response.request.method == "POST",
            timeout=20000,
        ) as response:
            self.page.locator("#voice-test").click()
        self.assertEqual(response.value.status, 200)
        self.assertIn("audio/wav", response.value.headers["content-type"])
        self.assertGreater(int(response.value.headers["content-length"]), 44)
        # Some Chromium builds omit fetch-stream bodies from the debugging
        # protocol after blob consumption. Validate the actual media decoder.
        self.wait_js("currentAudio && currentAudio.readyState >= 2 && currentAudio.duration > 0 && !currentAudio.error")
        self.page.locator("#voice-stop").click()
        self.assertIn("STOPPED", self.page.locator("#voice-status").inner_text())
        self.assertEqual(self.page.evaluate("speechQueue.length"), 0)

    def test_observed_map_and_session_fallback_over_real_runtime(self):
        payload = {"feeds": {"cyber": {"state": "live", "source": "SANS ISC",
                   "url": "https://isc.sans.edu/api/country?json",
                   "fetched_at": "2026-10-26T12:00:00Z", "observed_at": None,
                   "data": {"items": [
                       {"country": "US", "reports": 120, "sources": 10, "targets": 5},
                       {"country": "ZZ", "reports": 20, "sources": 2, "targets": 1}]}}}}
        import json
        self.page.route("**/api/intel", lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(payload)))
        self.page.evaluate("fetchIntel()")
        self.wait_js("mapMode === 'cyber' && mappedCyber().length === 1")
        self.assertIn("120 reports", self.page.locator("#cyber-ranking").inner_text())
        self.assertIn("1 zero or unmapped", self.page.locator("#map-state").inner_text())
        self.assertIn("SANS Technology Institute", self.page.locator("#map-source").inner_text())
        payload["feeds"]["cyber"]["state"] = "stale"
        self.page.evaluate("fetchIntel()")
        self.wait_js("document.getElementById('map-state').textContent.includes('STALE')")
        self.page.route("**/api/intel", lambda route: route.fulfill(status=503, body="unavailable"))
        self.page.evaluate("fetchIntel()")
        self.wait_js("lastIntel.feeds.cyber.error")
        self.assertIn("120 reports", self.page.locator("#cyber-ranking").inner_text())
        self.page.locator("#map-mode").select_option("daylight")
        self.assertFalse(self.page.locator(".map-overlay").is_visible())
        self.page.evaluate("""() => {
          const fixture={...lastStats, timestamp:'fallback-fixture', top_processes:[],
            battery:null, security:null, cpu:{...lastStats.cpu,temp_c:42,gpu_temp_c:null}};
          updateDashboard(fixture);
        }""")
        self.assertTrue(self.page.locator("#thermal-readings").is_visible())
        self.assertFalse(self.page.locator("#gpu-reading").is_visible())
        self.assertIn("SESSION RESOURCE", self.page.locator("#process-title").inner_text())
        self.assertIn("SYSTEM DRIVE", self.page.locator("#process-list").inner_text())
        self.assertFalse(self.page.locator("#security-status").is_visible())

    def test_wallboard_does_not_clip_at_common_screen_sizes(self):
        clipped = self.page.evaluate("""[...document.querySelectorAll('.grid>.panel')]
            .filter(el=>el.scrollHeight>el.clientHeight+2).map(el=>el.className)""")
        self.assertEqual(clipped, [], "First-run consent compressed the wallboard")
        self.page.locator("#consent-offline").click()
        for width, height in ((1920, 1080), (1366, 768), (390, 844)):
            with self.subTest(width=width, height=height):
                self.page.set_viewport_size({"width": width, "height": height})
                self.page.wait_for_timeout(250)
                layout = self.page.evaluate("""() => ({
                  width:document.documentElement.scrollWidth,
                  clipped:[...document.querySelectorAll('.grid>.panel')]
                    .filter(el=>el.scrollHeight>el.clientHeight+2).map(el=>el.className),
                  map:document.getElementById('threat-canvas').height
                })""")
                self.assertLessEqual(layout["width"], width)
                self.assertEqual(layout["clipped"], [])
                self.assertGreater(layout["map"], 100)


if __name__ == "__main__":
    unittest.main()
