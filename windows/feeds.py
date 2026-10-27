"""Optional fixed public feeds; no local data enters network requests."""
import copy
import datetime as dt
import email.utils
import json
import math
import os
from pathlib import Path
import threading
import tempfile
import time
import urllib.error
import urllib.request

try:
    from .collector import timestamp
except ImportError:
    from collector import timestamp


SOURCES = {
    "isc": ("SANS Internet Storm Center", "https://isc.sans.edu/api/infocon?json", 900),
    "cyber": ("SANS ISC / DShield country activity", "https://isc.sans.edu/api/country?json", 3600),
    "cisa": ("CISA Known Exploited Vulnerabilities", "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json", 21600),
    "noaa": ("NOAA SWPC Planetary K-index", "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json", 900),
    "usgs": ("USGS Earthquakes", "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson", 300),
}
MAX_RESPONSE = 8 * 1024 * 1024


def text(value, limit=400):
    return str(value or "")[:limit]


def number(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("non-finite value")
    return result


def normalize(key, raw):
    if key == "cyber":
        if not isinstance(raw, list) or len(raw) > 512:
            raise ValueError("invalid country summary")
        countries = {}
        for record in raw:
            code = record["country"]
            # Empty/unknown locations are omitted, never placed at (0, 0).
            if not isinstance(code, str) or len(code) != 2 or not code.isascii() or not code.isalpha():
                continue
            code = code.upper()
            counts = {}
            for field in ("reports", "sources", "targets"):
                value = record[field]
                if type(value) is not int or not 0 <= value <= 10**15:
                    raise ValueError("invalid country count")
                counts[field] = value
            if code in countries:
                raise ValueError("duplicate country")
            countries[code] = {"country": code, **counts}
        # No event time or source-to-target route is present in this endpoint.
        return {"items": sorted(countries.values(), key=lambda row: row["reports"], reverse=True),
                "attribution": "SANS Technology Institute, Internet Storm Center, https://isc.sans.edu",
                "scope": "Country aggregates from participating DShield sensors; not a live event stream."}, None
    if key == "isc":
        # ISC currently returns a root status object; older API responses wrap it.
        record = raw.get("infocon", raw)
        level = text(record["status"], 16).lower()
        if level not in ("green", "yellow", "orange", "red"):
            raise ValueError("unknown InfoCon level")
        return {"level": level, "description": text(record.get("description") or
                "Global Internet condition; not a local compromise assessment.")}, record.get("date")
    if key == "cisa":
        items = [{"cve_id": text(v.get("cveID"), 40), "vendor": text(v.get("vendorProject"), 80),
                  "product": text(v.get("product"), 100), "name": text(v.get("vulnerabilityName"), 200),
                  "date_added": text(v.get("dateAdded"), 32), "due_date": text(v.get("dueDate"), 32),
                  "required_action": text(v.get("requiredAction"))}
                 for v in sorted(raw["vulnerabilities"], key=lambda v: text(v.get("dateAdded")), reverse=True)[:30]]
        return {"catalog_version": text(raw.get("catalogVersion"), 40),
                "date_released": text(raw.get("dateReleased"), 40),
                "total": int(raw["count"]), "items": items}, raw.get("dateReleased")
    if key == "noaa":
        row = raw[-1]
        # SWPC has published both object rows and header + positional rows.
        kp = number(row["Kp"] if isinstance(row, dict) else row[1])
        if not 0 <= kp <= 9:
            raise ValueError("invalid Kp")
        observed = row["time_tag"] if isinstance(row, dict) else row[0]
        parsed = dt.datetime.fromisoformat(str(observed).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        observed = parsed.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")
        return {"kp": kp, "observed_at": observed}, observed
    if key == "usgs":
        items = []
        for feature in raw["features"][:100]:
            p, coordinates = feature["properties"], feature["geometry"]["coordinates"]
            longitude, latitude = number(coordinates[0]), number(coordinates[1])
            if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
                raise ValueError("invalid earthquake coordinates")
            url = text(p.get("url"), 300)
            if not url.startswith("https://earthquake.usgs.gov/"):
                url = ""
            items.append({"id": text(feature.get("id"), 80), "magnitude": number(p["mag"]) if p.get("mag") is not None else None,
                          "place": text(p.get("place"), 200), "time": timestamp(number(p["time"]) / 1000),
                          "longitude": longitude, "latitude": latitude, "url": url})
        return {"items": items}, timestamp(number(raw["metadata"]["generated"]) / 1000)
    raise ValueError("unknown feed")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("feed redirects disabled")


def fetch_json(url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(url, headers={"User-Agent": "WOPR-Public-Feeds/1.0 (+https://github.com/dougrichards13/nginx_WOPR)",
                                                  "Accept": "application/json"})
    with opener.open(request, timeout=6) as response:
        size = response.headers.get("Content-Length")
        if size and int(size) > MAX_RESPONSE:
            raise ValueError("feed too large")
        deadline = time.monotonic() + 6
        chunks = []
        total = 0
        while True:
            if time.monotonic() > deadline:
                raise ValueError("feed read deadline exceeded")
            chunk = response.read1(min(65536, MAX_RESPONSE + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_RESPONSE:
                raise ValueError("feed too large")
        return json.loads(b"".join(chunks))


def consent_path():
    base = os.environ.get("LOCALAPPDATA") if os.name == "nt" else os.environ.get("XDG_CONFIG_HOME")
    return (Path(base) if base else Path.home() / ".config") / "WOPR" / "settings.json"


class Feeds:
    def __init__(self, offline=False, config_path=None, fetcher=fetch_json):
        self.lock = threading.Lock()
        self.path = Path(config_path) if config_path else consent_path()
        self.offline = offline
        self.enabled = False
        self.fetcher = fetcher
        self.records = {}
        self.next_due = {}
        self.failures = {}
        try:
            if self.path.stat().st_size <= 4096:
                self.enabled = json.loads(self.path.read_text("utf-8")).get("feeds_enabled") is True
        except (OSError, ValueError, AttributeError):
            pass
        if offline:
            self.enabled = False
        for key, (source, url, _) in SOURCES.items():
            self.records[key] = {"state": "loading" if self.enabled else "offline",
                                 "source": source, "url": url, "fetched_at": None,
                                 "observed_at": None, "data": None}
            self.next_due[key] = 0
            self.failures[key] = 0

    def set_enabled(self, enabled):
        if type(enabled) is not bool:
            raise ValueError("feeds_enabled must be boolean")
        if self.offline and enabled:
            raise ValueError("offline mode is locked for this session")
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix=".settings-", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                json.dump({"feeds_enabled": enabled}, handle)
            try:
                temporary.replace(self.path)
            finally:
                temporary.unlink(missing_ok=True)
            self.enabled = enabled
            if enabled:
                # Re-enabling must not bypass provider refresh limits or backoff.
                for record in self.records.values():
                    record["state"] = "stale" if record["data"] is not None else "loading"

    def get(self):
        with self.lock:
            result = copy.deepcopy(self.records)
            for key, record in result.items():
                if not self.enabled:
                    record["state"] = "offline"
                elif record["data"] is not None and time.monotonic() > self.next_due[key]:
                    record["state"] = "stale"
            return {"feeds": result}

    def tick(self):
        for key, (_, url, interval) in SOURCES.items():
            with self.lock:
                if not self.enabled or time.monotonic() < self.next_due[key]:
                    continue
            try:
                data, observed = normalize(key, self.fetcher(url))
                # Only publish syntactically valid observation timestamps.
                if observed:
                    try:
                        parsed = dt.datetime.fromisoformat(str(observed).replace("Z", "+00:00"))
                        if parsed.tzinfo is None:
                            parsed = parsed.replace(tzinfo=dt.timezone.utc)
                        observed = parsed.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")
                    except ValueError:
                        observed = None
                with self.lock:
                    self.records[key].update(state="live", data=data, fetched_at=timestamp(), observed_at=observed)
                    self.records[key].pop("error", None)
                    self.failures[key] = 0
                    self.next_due[key] = time.monotonic() + interval
            except (OSError, ValueError, KeyError, TypeError, IndexError, OverflowError,
                    AttributeError, RecursionError) as exc:
                retry_after = 0
                if isinstance(exc, urllib.error.HTTPError):
                    try:
                        retry_after = min(86400, max(0, int(exc.headers.get("Retry-After", "0"))))
                    except (ValueError, TypeError):
                        try:
                            retry_after = min(86400, max(0, email.utils.parsedate_to_datetime(
                                exc.headers["Retry-After"]).timestamp() - time.time()))
                        except (ValueError, TypeError, KeyError, OverflowError):
                            pass
                with self.lock:
                    self.failures[key] = min(10, self.failures[key] + 1)
                    # ISC guidance requires waiting at least five minutes after
                    # failure/rate limiting; apply that courtesy to all feeds.
                    self.next_due[key] = time.monotonic() + max(
                        retry_after, min(21600, 300 * 2 ** (self.failures[key] - 1)))
                    self.records[key]["state"] = "stale" if self.records[key]["data"] is not None else "unavailable"
                    self.records[key]["error"] = "Public feed unavailable; retry scheduled."
