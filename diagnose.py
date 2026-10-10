"""
VALORANT Optimizer - Phase 1: READ-ONLY diagnostics.

Changes NOTHING on your system. It only:
  - reads a few registry values
  - runs ping / powercfg / nvidia-smi / PowerShell Get-* (read) commands
  - lists running processes

Usage (Windows):
    pip install psutil
    python diagnose.py
Optional: python diagnose.py --valorant-host <host>   (extra ping target)

Output: console summary + logs/diagnostic_<timestamp>.json
Later phases will split these functions into network/, hardware/,
process_manager/, optimizer/ modules. Keep run() read-only here.
"""
import argparse
import json
import os
import platform
import random
import re
import socket
import statistics
import subprocess
import sys
import time
from datetime import datetime

try:
    import psutil
except ImportError:
    print("Missing dependency: pip install psutil")
    sys.exit(1)

print = __import__("functools").partial(print, flush=True)
PING_COUNT = 20
DO_TRACE = False
IS_WIN = platform.system() == "Windows"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# ----------------------------------------------------------------- helpers
def run(cmd, timeout=60):
    """Run a command, return (returncode, stdout). Never raises."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           creationflags=NO_WINDOW, errors="replace")
        return p.returncode, (p.stdout or "").strip()
    except Exception as e:
        return -1, f"ERROR: {e}"


def powershell_json(script, timeout=30):
    rc, out = run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout)
    if rc != 0 or not out:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


def read_reg(hive, path, name):
    if not IS_WIN:
        return None
    import winreg
    try:
        with winreg.OpenKey(hive, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None  # value not set (Windows default applies)

# ----------------------------------------------------------------- network
def ping_stats(host, count=20):
    """Ping via Windows ping.exe. Jitter = mean |delta| between consecutive replies."""
    rc, out = run(["ping", "-n", str(count), "-w", "1000", host], timeout=count * 2 + 10)
    times = []
    for line in out.splitlines():
        if "TTL" in line.upper():  # reply lines only (locale-independent-ish)
            m = re.search(r"[=<]\s*(\d+)\s*ms", line, re.I)
            if m:
                times.append(float(m.group(1)))
    if not times:
        return {"host": host, "ok": False, "loss_pct": 100.0}
    jitter = statistics.mean(abs(a - b) for a, b in zip(times, times[1:])) if len(times) > 1 else 0.0
    return {
        "host": host, "ok": True, "sent": count, "received": len(times),
        "loss_pct": round(100 * (count - len(times)) / count, 1),
        "min": min(times), "avg": round(statistics.mean(times), 1), "max": max(times),
        "jitter": round(jitter, 2),
    }


def tcp_ping(host, port=443, count=10):
    """TCP handshake time (works where ICMP is blocked, e.g. AWS)."""
    try:
        ip = socket.gethostbyname(host)  # resolve once so DNS isn't timed
    except OSError:
        return {"host": host, "ok": False, "loss_pct": 100.0}
    times = []
    for _ in range(count):
        t = time.perf_counter()
        try:
            with socket.create_connection((ip, port), timeout=2):
                times.append(round((time.perf_counter() - t) * 1000, 1))
        except OSError:
            pass
        time.sleep(0.2)
    if not times:
        return {"host": host, "ok": False, "loss_pct": 100.0}
    jit = statistics.mean(abs(a - b) for a, b in zip(times, times[1:])) if len(times) > 1 else 0.0
    return {"host": host, "ok": True, "method": "tcp443", "sent": count, "received": len(times),
            "loss_pct": round(100 * (count - len(times)) / count, 1), "min": min(times),
            "avg": round(statistics.mean(times), 1), "max": max(times), "jitter": round(jit, 2)}


def adapter_and_gateway():
    ps = r"""
$r = Get-NetRoute -DestinationPrefix 0.0.0.0/0 | Sort-Object RouteMetric | Select-Object -First 1
$a = Get-NetAdapter -InterfaceIndex $r.InterfaceIndex
$d = (Get-DnsClientServerAddress -InterfaceIndex $r.InterfaceIndex -AddressFamily IPv4).ServerAddresses
[pscustomobject]@{Gateway=$r.NextHop; Name=$a.Name; Desc=$a.InterfaceDescription;
  Media=[string]$a.PhysicalMediaType; Speed=$a.LinkSpeed; Dns=$d} | ConvertTo-Json
"""
    info = powershell_json(ps) or {}
    media = (info.get("Media") or "").lower()
    if "802.3" in media:
        info["ConnectionType"] = "Ethernet"
    elif "802.11" in media:
        info["ConnectionType"] = "Wi-Fi"
    else:
        info["ConnectionType"] = info.get("Media") or "Unknown"
    return info


def dns_latency(samples=5):
    """Time to resolve unique non-existent names = real round trip to your resolver
    (unique names can't be answered from cache)."""
    times = []
    for _ in range(samples):
        name = f"x{random.randint(10**9, 10**10)}.example.com"
        t = time.perf_counter()
        try:
            socket.getaddrinfo(name, None)
        except OSError:
            pass
        times.append((time.perf_counter() - t) * 1000)
    return {"avg_ms": round(statistics.mean(times), 1), "max_ms": round(max(times), 1)}


def network_load(seconds=3):
    """Current NIC throughput - detects background saturation."""
    a = psutil.net_io_counters()
    time.sleep(seconds)
    b = psutil.net_io_counters()
    return {"down_mbps": round((b.bytes_recv - a.bytes_recv) * 8 / seconds / 1e6, 2),
            "up_mbps": round((b.bytes_sent - a.bytes_sent) * 8 / seconds / 1e6, 2)}


def traceroute(host):
    # -d no DNS lookups (faster), -h 15 hops, -w 800 ms timeout
    rc, out = run(["tracert", "-d", "-h", "15", "-w", "800", host], timeout=90)
    return out


def network_report(extra_host=None):
    print("   - detecting adapter/gateway (PowerShell can take 10-20s the first time)")
    info = adapter_and_gateway()
    gw = info.get("Gateway")
    # NOTE: AWS us-east-1 endpoint is only a *proxy* for the Virginia region.
    # It is NOT a Riot server. Real Riot endpoints are not assumed here.
    targets = {"internet_1.1.1.1": "1.1.1.1",
               "virginia_proxy_aws": "ec2.us-east-1.amazonaws.com"}
    if extra_host:
        targets["custom"] = extra_host
    print("   - measuring NIC load (3s)")
    rep = {"adapter": info, "load": network_load(), "dns": dns_latency(), "ping": {}}
    if gw:
        print(f"   - pinging gateway {gw}")
        rep["ping"]["gateway"] = ping_stats(gw, PING_COUNT)
    for k, h in targets.items():
        print(f"   - pinging {h} ({PING_COUNT} pings)")
        rep["ping"][k] = tcp_ping(h, 443, PING_COUNT) if k.startswith("virginia") else ping_stats(h, PING_COUNT)
    if DO_TRACE:
        print("   - traceroute (up to 90s)")
        rep["traceroute_virginia_proxy"] = traceroute(targets["virginia_proxy_aws"])
    rep["findings"] = network_findings(rep)
    return rep


def network_findings(rep):
    f = []
    p = rep["ping"]
    gw = p.get("gateway", {})
    if gw.get("ok"):
        if gw["avg"] > 5 or gw["jitter"] > 2 or gw["loss_pct"] > 0:
            f.append("LOCAL problem: gateway latency/jitter/loss is elevated "
                     "(Wi-Fi, bad cable, or router issue).")
    if rep["adapter"].get("ConnectionType") == "Ethernet" and gw.get("ok") and gw["avg"] > 2:
        f.append("Gateway latency is higher than a direct wired link normally shows (<1 ms): "
                 "a wireless booster, powerline adapter or switch chain is likely in the path.")
    for k, v in p.items():
        if k == "gateway" or not v.get("ok"):
            continue
        if v["loss_pct"] > 0:
            f.append(f"Packet loss to {k}: {v['loss_pct']}%")
        if v["jitter"] > 5:
            f.append(f"High jitter to {k}: {v['jitter']} ms")
    if rep["adapter"].get("ConnectionType") == "Wi-Fi":
        f.append("Connected via Wi-Fi - Ethernet is the biggest possible jitter fix.")
    if rep["load"]["up_mbps"] > 5 or rep["load"]["down_mbps"] > 20:
        f.append(f"Background traffic during test: {rep['load']} (can cause bufferbloat).")
    if rep["dns"]["avg_ms"] > 100:
        f.append("Slow DNS resolver (affects page loads/lookups, NOT in-game ping).")
    if not f:
        f.append("No local network problems detected in this sample.")
    f.append("Bufferbloat test (latency under load) is NOT included in phase 1.")
    return f

# ----------------------------------------------------------------- hardware
def gpu_report():
    rc, out = run(["nvidia-smi",
                   "--query-gpu=name,driver_version,utilization.gpu,temperature.gpu,"
                   "clocks.gr,clocks.max.gr,power.draw,pstate",
                   "--format=csv,noheader"])
    if rc != 0:
        return {"available": False, "detail": out}
    parts = [x.strip() for x in out.splitlines()[0].split(",")]
    keys = ["name", "driver", "util_pct", "temp_c", "clock_mhz", "clock_max_mhz", "power", "pstate"]
    return {"available": True, **dict(zip(keys, parts))}


def cpu_report():
    return {"model": platform.processor(), "physical_cores": psutil.cpu_count(logical=False),
            "logical_cores": psutil.cpu_count(logical=True),
            "usage_pct_3s": psutil.cpu_percent(interval=3),
            "ram_total_gb": round(psutil.virtual_memory().total / 2**30, 1),
            "ram_used_pct": psutil.virtual_memory().percent}

# ----------------------------------------------------------------- windows settings (READ ONLY)
def windows_settings():
    if not IS_WIN:
        return {"note": "Not Windows - skipped"}
    import winreg as w
    hags = read_reg(w.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers", "HwSchMode")
    rc, plan = run(["powercfg", "/getactivescheme"])
    pm = powershell_json(
        "Get-NetAdapterPowerManagement | Select-Object Name,AllowComputerToTurnOffDevice,"
        "SelectiveSuspend | ConvertTo-Json") or "unavailable (may need admin)"
    return {
        "hags": {"value": hags, "meaning": {2: "ON", 1: "OFF"}.get(hags, "not set / default")},
        "game_mode_auto": read_reg(w.HKEY_CURRENT_USER, r"Software\Microsoft\GameBar", "AutoGameModeEnabled"),
        "game_dvr_gameconfig": read_reg(w.HKEY_CURRENT_USER, r"System\GameConfigStore", "GameDVR_Enabled"),
        "background_recording": read_reg(w.HKEY_CURRENT_USER,
                                         r"Software\Microsoft\Windows\CurrentVersion\GameDVR", "AppCaptureEnabled"),
        "fullscreen_opt_fse_behavior": read_reg(w.HKEY_CURRENT_USER, r"System\GameConfigStore",
                                                "GameDVR_FSEBehaviorMode"),
        "power_plan": plan,
        "adapter_power_management": pm,
        "timer_resolution_note": "Not read in phase 1",
    }

# ----------------------------------------------------------------- processes
PROTECTED = {"vgc.exe", "vgtray.exe", "riotclientservices.exe", "riotclientux.exe",
             "valorant.exe", "valorant-win64-shipping.exe", "msmpeng.exe", "mssense.exe",
             "explorer.exe", "dwm.exe", "csrss.exe", "winlogon.exe", "services.exe",
             "lsass.exe", "svchost.exe", "system", "registry", "nvcontainer.exe"}
CANDIDATES = {  # may be closed ONLY if you approve in config (phase 3)
    "ollama.exe": "AI runtime", "ollama app.exe": "AI runtime",
    "postgres.exe": "PostgreSQL", "node.exe": "dev server", "python.exe": "Python (check which!)",
    "pythonw.exe": "Python (check which!)", "docker desktop.exe": "Docker", "wslservice.exe": "WSL",
    "vmmem": "WSL/VM memory",
}
CLOUD_SYNC = {"onedrive.exe", "dropbox.exe", "googledrivefs.exe", "megasync.exe"}
USER_CONFIG = {"chrome.exe", "msedge.exe", "firefox.exe", "discord.exe", "spotify.exe", "obs64.exe"}


def classify(name):
    n = name.lower()
    if n in PROTECTED:
        return "PROTECTED"
    if n in CANDIDATES:
        return "CANDIDATE"
    if n in CLOUD_SYNC:
        return "CLOUD_SYNC"
    if n in USER_CONFIG:
        return "USER_CONFIGURE"
    return "OTHER"


def process_report(top=25):
    for p in psutil.process_iter():
        try:
            p.cpu_percent(None)
        except Exception:
            pass
    time.sleep(2)
    agg = {}
    for p in psutil.process_iter(["name", "memory_info"]):
        try:
            name = p.info["name"] or "?"
            e = agg.setdefault(name, {"name": name, "count": 0, "ram_mb": 0.0, "cpu_pct": 0.0})
            e["count"] += 1
            e["ram_mb"] += (p.info["memory_info"].rss if p.info["memory_info"] else 0) / 2**20
            e["cpu_pct"] += p.cpu_percent(None) / (psutil.cpu_count() or 1)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    rows = sorted(agg.values(), key=lambda r: r["ram_mb"] + r["cpu_pct"] * 50, reverse=True)[:top]
    for r in rows:
        r["ram_mb"], r["cpu_pct"] = round(r["ram_mb"]), round(r["cpu_pct"], 1)
        r["class"] = classify(r["name"])
    valorant = [p.info["pid"] for p in psutil.process_iter(["name", "pid"])
                if (p.info["name"] or "").lower() == "valorant-win64-shipping.exe"]
    vanguard = any((p.info["name"] or "").lower() == "vgc.exe" for p in psutil.process_iter(["name"]))
    return {"valorant_running": bool(valorant), "valorant_pids": valorant,
            "vanguard_running": vanguard, "top_processes": rows}

# ----------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--valorant-host", help="optional extra host to ping")
    ap.add_argument("--quick", action="store_true", help="10 pings, ~30s total")
    ap.add_argument("--trace", action="store_true", help="also run traceroute (slow)")
    args = ap.parse_args()
    global PING_COUNT, DO_TRACE
    PING_COUNT = 10 if args.quick else 20
    DO_TRACE = args.trace

    print("VALORANT Optimizer - READ-ONLY diagnostic (nothing is modified)\n")
    report = {"timestamp": datetime.now().isoformat(), "os": platform.platform()}
    steps = [("cpu", cpu_report), ("gpu", gpu_report), ("windows_settings", windows_settings),
             ("processes", process_report), ("network", lambda: network_report(args.valorant_host))]
    for key, fn in steps:
        print(f"[..] {key}")
        try:
            report[key] = fn()
        except Exception as e:  # one failure must not kill the whole report
            report[key] = {"error": str(e)}

    os.makedirs("logs", exist_ok=True)
    path = os.path.join("logs", f"diagnostic_{datetime.now():%Y%m%d_%H%M%S}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    # ---- console summary
    n = report.get("network", {})
    pg = n.get("ping", {})
    print("\n================ SUMMARY ================")
    print("Connection :", n.get("adapter", {}).get("ConnectionType"), "-", n.get("adapter", {}).get("Desc"))
    for k, v in pg.items():
        if v.get("ok"):
            print(f"{k:22} avg {v['avg']} ms | min {v['min']} | max {v['max']} | "
                  f"jitter {v['jitter']} | loss {v['loss_pct']}%")
        else:
            print(f"{k:22} no reply")
    print("DNS resolver:", n.get("dns"))
    print("NIC load    :", n.get("load"))
    print("GPU         :", report.get("gpu"))
    print("VALORANT    :", report.get("processes", {}).get("valorant_running"),
          "| Vanguard:", report.get("processes", {}).get("vanguard_running"))
    print("\nFindings:")
    for line in n.get("findings", []):
        print(" -", line)
    print(f"\nFull report saved: {path}")
    print("Paste that JSON (or the summary) back to continue to Phase 2.")


if __name__ == "__main__":
    main()
