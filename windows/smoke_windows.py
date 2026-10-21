"""Exercise an actual extracted portable package, including offline speech."""
from __future__ import annotations

import http.client
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import wave


def smoke(package: Path, expected_host: str = "windows") -> None:
    with tempfile.TemporaryDirectory(prefix="WOPR package with spaces ") as temporary:
        folder = Path(temporary) / "WOPR command center"
        shutil.copytree(package, folder)
        port_file = Path(temporary) / "runtime.json"
        process = subprocess.Popen(
            [str(folder / "WOPR.exe"), "--no-browser", "--offline", "--port", "0",
             "--port-file", str(port_file)],
            cwd=folder,
        )
        try:
            deadline = time.monotonic() + 45
            while not port_file.exists():
                if process.poll() is not None:
                    raise RuntimeError(f"Packaged process exited: {process.returncode}")
                if time.monotonic() > deadline:
                    raise RuntimeError("Packaged server did not start")
                time.sleep(0.2)
            info = json.loads(port_file.read_text(encoding="utf-8"))
            origin = info["url"].rstrip("/")

            def get(path):
                with urllib.request.urlopen(origin + path, timeout=15) as response:
                    return response.read()

            config = json.loads(get("/api/config"))
            assert config["platform"] == "windows"
            assert config["host_platform"] == expected_host
            assert config["feeds_enabled"] is False
            assert config["speech"]["available"], "Bundled speech engine not discovered"
            assert b"voice-toggle" in get("/")
            assert json.loads(get("/data/ne_110m_land.json"))["features"]
            stats = json.loads(get("/api/stats.json"))
            assert stats["cpu"]["cores"] > 0
            assert stats["memory"]["total_mb"] > 0
            assert stats["top_processes"] is not None
            feeds = json.loads(get("/api/intel"))["feeds"]
            assert all(feed["state"] == "offline" for feed in feeds.values())

            def post(path, data):
                request = urllib.request.Request(
                    origin + path, data=json.dumps(data).encode(),
                    headers={"Content-Type": "application/json", "Origin": origin,
                             "X-WOPR-Token": config["session_token"]})
                with urllib.request.urlopen(request, timeout=35) as response:
                    return response.read()

            wav = post("/api/speak", {"text": "Greetings Professor Falken. Shall we play a game?",
                                     "speed": 165, "pitch": 35, "volume": 90})
            with wave.open(io.BytesIO(wav)) as audio:
                assert audio.getframerate() > 0 and len(audio.readframes(2000)) > 1000
            # DNS rebinding must not bypass a loopback bind.
            connection = http.client.HTTPConnection(urllib.parse.urlsplit(origin).hostname, info["port"], timeout=10)
            connection.request("GET", "/api/stats.json", headers={"Host": "attacker.example"})
            response = connection.getresponse()
            assert response.status in (400, 403)
            response.read()
            connection.close()
            post("/api/shutdown", {})
            process.wait(timeout=15)
            assert process.returncode == 0
            print(f"PASS: {expected_host} packaged runtime, spaces in path, telemetry, offline mode, WAV, Host rejection, shutdown")
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)


if __name__ == "__main__":
    smoke(Path(sys.argv[1]).resolve())
