"""Read-only telemetry. No local metric history is persisted."""
import datetime as dt
from collections import deque
import itertools
import ipaddress
import json
import os
import platform
import socket
import subprocess
import threading
import time

import psutil


def timestamp(value=None):
    return dt.datetime.fromtimestamp(time.time() if value is None else value,
                                     dt.timezone.utc).isoformat().replace("+00:00", "Z")


def safe(call, default=None):
    try:
        return call()
    except (psutil.Error, OSError, AttributeError, ValueError, NotImplementedError):
        return default


def rate(current, previous, seconds):
    """Counter resets and the first sample have no measured rate."""
    if previous is None or seconds <= 0 or current < previous:
        return None
    return round((current - previous) / seconds / 1024, 2)


def usage_record(usage):
    if usage is None:
        return dict.fromkeys(("total_gb", "used_gb", "free_gb", "percent"))
    return {"total_gb": round(usage.total / 1024**3, 2),
            "used_gb": round(usage.used / 1024**3, 2),
            "free_gb": round(usage.free / 1024**3, 2), "percent": usage.percent}


def has_network_address(adapter):
    for address in adapter["addresses"]:
        try:
            parsed = ipaddress.ip_address(address.split("%", 1)[0])
            if not parsed.is_loopback and not parsed.is_unspecified:
                return True
        except ValueError:
            continue
    return False


class Collector:
    def __init__(self):
        self.lock = threading.Lock()
        self.snapshot = {}
        self.previous = {}
        self.previous_time = None
        self.events = deque(maxlen=20)
        self.thresholds = {}
        self.slow = {"windows_services": [], "security": {
            "defender": {"state": "unavailable", "enabled": None, "signatures_updated": None},
            "firewall": {"state": "unavailable", "enabled": None}}}
        self.capabilities = {"temperature": False, "gpu": False,
                             "windows_services": os.name == "nt", "security": os.name == "nt"}

    def rates(self, key, values, elapsed):
        previous = self.previous.get(key)
        self.previous[key] = values
        return [rate(value, previous[i] if previous else None, elapsed)
                for i, value in enumerate(values)]

    def collect(self):
        now = time.monotonic()
        elapsed = now - self.previous_time if self.previous_time is not None else 0
        self.previous_time = now
        per_core = safe(lambda: psutil.cpu_percent(percpu=True), [])
        memory = safe(psutil.virtual_memory)
        root = os.environ.get("SystemDrive", "C:") + "\\" if os.name == "nt" else "/"
        disks = []
        for part in safe(lambda: psutil.disk_partitions(all=False), [])[:32]:
            usage = safe(lambda: psutil.disk_usage(part.mountpoint))
            if usage:
                disks.append({"mountpoint": part.mountpoint, **usage_record(usage)})
        measured_net = safe(lambda: psutil.net_io_counters(pernic=True))
        net = measured_net or {}
        addresses = safe(psutil.net_if_addrs, {}) or {}
        nic_stats = safe(psutil.net_if_stats, {}) or {}
        adapters = []
        for name, counters in list(net.items())[:64]:
            rx, tx = self.rates("nic:" + name, (counters.bytes_recv, counters.bytes_sent), elapsed)
            adapters.append({"name": name, "addresses": [
                a.address for a in addresses.get(name, []) if a.family in (socket.AF_INET, socket.AF_INET6)],
                "is_up": nic_stats[name].isup if name in nic_stats else None,
                "rx_rate_kbs": rx, "tx_rate_kbs": tx})
        total_rx = sum(c.bytes_recv for c in net.values())
        total_tx = sum(c.bytes_sent for c in net.values())
        if measured_net is not None:
            rx, tx = self.rates("net", (total_rx, total_tx), elapsed)
        else:
            rx = tx = None
            self.previous.pop("net", None)
        io = safe(psutil.disk_io_counters)
        read, write = self.rates("io", (io.read_bytes, io.write_bytes), elapsed) if io else (None, None)
        if io is None:
            self.previous.pop("io", None)
        processes = []
        for process in itertools.islice(psutil.process_iter(), 4096):
            try:
                processes.append({"name": process.name()[:128], "cpu_percent": process.cpu_percent(),
                                  "memory_mb": round(process.memory_info().rss / 1024**2, 1)})
            except (psutil.Error, OSError):
                continue
        processes.sort(key=lambda p: (p["cpu_percent"], p["memory_mb"]), reverse=True)
        battery = safe(psutil.sensors_battery)
        freq = safe(psutil.cpu_freq)
        uptime = max(0, int(time.time() - safe(psutil.boot_time, time.time())))
        selected = next((a for a in adapters if a["is_up"] and has_network_address(a)), None)
        connections = safe(lambda: sum(c.status == "ESTABLISHED" for c in psutil.net_connections(kind="inet")))
        result = {"platform": "windows", "host_platform": platform.system().lower(),
                  "hostname": socket.gethostname(), "os": platform.platform(), "timestamp": timestamp(),
                  "uptime_seconds": uptime,
                  "uptime": f"{uptime // 86400}d {uptime // 3600 % 24}h {uptime // 60 % 60}m",
                  "cpu": {"usage_percent": round(sum(per_core) / len(per_core), 1) if per_core else None,
                          "temp_c": None, "gpu_temp_c": None, "freq_mhz": freq.current if freq else None,
                          "cores": psutil.cpu_count(), "load_1m": None, "load_5m": None,
                          "load_15m": None, "throttled": None},
                  "per_core": per_core,
                  "memory": {"total_mb": round(memory.total / 1024**2, 1) if memory else None,
                             "used_mb": round((memory.total - memory.available) / 1024**2, 1) if memory else None,
                             "available_mb": round(memory.available / 1024**2, 1) if memory else None,
                             "percent": memory.percent if memory else None},
                  "disk": usage_record(safe(lambda: psutil.disk_usage(root))), "disks": disks,
                  "disk_io": {"read_rate_kbs": read, "write_rate_kbs": write},
                  "network": {"ip": selected["addresses"][0] if selected else None,
                              "interface": selected["name"] if selected else None,
                              "rx_mb": round(total_rx / 1024**2, 1) if measured_net is not None else None,
                              "tx_mb": round(total_tx / 1024**2, 1) if measured_net is not None else None,
                              "rx_rate_kbs": rx, "tx_rate_kbs": tx, "connections": connections},
                  "adapters": adapters, "processes": safe(lambda: len(psutil.pids())),
                  "top_processes": processes[:10],
                  "battery": {"percent": battery.percent, "plugged": battery.power_plugged,
                              "seconds_left": battery.secsleft if battery.secsleft >= 0 else None} if battery else None,
                  "services": {}, "log_entries": [], "auth_failures": [],
                  "capabilities": dict(self.capabilities)}
        if not self.events:
            self.events.append({"time": result["timestamp"],
                                "msg": f"Read-only telemetry online / {result['cpu']['cores'] or 'unknown'} logical cores."})
        for label, value, threshold in (
            ("CPU utilization", result["cpu"]["usage_percent"], 85),
            ("Memory use", result["memory"]["percent"], 85),
            ("System-drive use", result["disk"]["percent"], 90),
        ):
            if value is None:
                continue
            elevated = value >= threshold
            if self.thresholds.get(label) != elevated:
                self.events.append({"time": result["timestamp"],
                                    "msg": f"{label}: {value:.1f}% / {'above' if elevated else 'below'} {threshold}% display threshold."})
            self.thresholds[label] = elevated
        result["log_entries"] = list(self.events)
        with self.lock:
            result.update(self.slow)
            self.snapshot = result
        return result

    def get(self):
        with self.lock:
            return dict(self.snapshot)

    def probe_windows(self):
        """Fixed read-only PowerShell query; never evaluates user input."""
        if os.name != "nt":
            return
        services = []
        for name in ("WinDefend", "MpsSvc", "EventLog", "wuauserv", "Dnscache"):
            status = safe(lambda: psutil.win_service_get(name).status())
            services.append({"name": name, "status": status or "unavailable"})
        security = {"defender": {"state": "unavailable", "enabled": None, "signatures_updated": None},
                    "firewall": {"state": "unavailable", "enabled": None}}
        script = (
            "$ErrorActionPreference='Stop'; $d=$null; $f=$null;"
            "try {$s=Get-MpComputerStatus; $d=@{enabled=[bool]$s.AntivirusEnabled;"
            "signatures_updated=$s.AntivirusSignatureLastUpdated.ToUniversalTime().ToString('o')}} catch {};"
            "try {$f=@(Get-NetFirewallProfile | Select-Object -ExpandProperty Enabled)} catch {};"
            "@{defender=$d;firewall=$f}|ConvertTo-Json -Compress -Depth 4"
        )
        executable = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                                  "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
        try:
            output = subprocess.run([executable, "-NoProfile", "-NonInteractive", "-Command", script],
                                    capture_output=True, timeout=12, check=True,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            data = json.loads(output.stdout.decode("utf-8-sig"))
            defender = data.get("defender")
            if isinstance(defender, dict) and type(defender.get("enabled")) is bool:
                security["defender"].update(defender, state="available")
            firewall = data.get("firewall")
            if isinstance(firewall, list) and firewall and all(type(v) is bool for v in firewall):
                security["firewall"].update(state="available", enabled=all(firewall))
        except (OSError, subprocess.SubprocessError, ValueError, UnicodeError):
            pass
        with self.lock:
            self.slow = {"windows_services": services, "security": security}
