"""
VALORANT Optimizer - bufferbloat test (changes nothing on your PC).

Measures ping to 1.1.1.1 while IDLE, then while your connection is saturated
by a download, then by an upload (Cloudflare speed-test endpoints).
Big latency increase under load = bufferbloat = jitter spikes in games
whenever anything else uses your internet (and the fix is on your router).

Usage:  python bufferbloat.py
Takes ~40s. Close streams/downloads first. Don't run during a match.
"""
import json
import os
import re
import statistics
import subprocess
import threading
import time
import urllib.request
from datetime import datetime

print = __import__("functools").partial(print, flush=True)

HOST = "1.1.1.1"
SECS = 12
THREADS = 6
DOWN = "https://speed.cloudflare.com/__down?bytes=25000000"
UP = "https://speed.cloudflare.com/__up"
HDR = {"User-Agent": "Mozilla/5.0"}
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def ping_series(host, n):
    out = subprocess.run(["ping", "-n", str(n), "-w", "2000", host], capture_output=True,
                         text=True, creationflags=NO_WINDOW, errors="replace").stdout
    times = []
    for line in out.splitlines():
        if "TTL" in line.upper():
            m = re.search(r"[=<]\s*(\d+)\s*ms", line, re.I)
            if m:
                times.append(float(m.group(1)))
    return times


def summarize(times, sent):
    if not times:
        return {"avg": None, "max": None, "jitter": None, "loss_pct": 100.0}
    jit = statistics.mean(abs(a - b) for a, b in zip(times, times[1:])) if len(times) > 1 else 0.0
    return {"avg": round(statistics.mean(times), 1), "min": min(times), "max": max(times),
            "jitter": round(jit, 1), "loss_pct": round(100 * (sent - len(times)) / sent, 1)}


def download_worker(stop, counter):
    while not stop.is_set():
        try:
            with urllib.request.urlopen(urllib.request.Request(DOWN, headers=HDR), timeout=10) as r:
                while not stop.is_set():
                    chunk = r.read(65536)
                    if not chunk:
                        break
                    counter[0] += len(chunk)
        except Exception:
            time.sleep(0.5)


def upload_worker(stop, counter):
    data = os.urandom(1_000_000)
    while not stop.is_set():
        try:
            req = urllib.request.Request(UP, data=data, method="POST", headers=HDR)
            urllib.request.urlopen(req, timeout=10).read()
            counter[0] += len(data)
        except Exception:
            time.sleep(0.5)


def loaded_phase(worker):
    stop, counter = threading.Event(), [0]
    threads = [threading.Thread(target=worker, args=(stop, counter), daemon=True) for _ in range(THREADS)]
    for t in threads:
        t.start()
    time.sleep(2)  # let the load ramp up
    c0, t0 = counter[0], time.time()
    times = ping_series(HOST, SECS)
    mbps = (counter[0] - c0) * 8 / max(time.time() - t0, 0.1) / 1e6
    stop.set()
    res = summarize(times, SECS)
    res["throughput_mbps"] = round(mbps, 1)
    return res


def grade(increase):
    if increase is None:
        return "?"
    for limit, g in ((5, "A"), (30, "B"), (60, "C"), (200, "D")):
        if increase < limit:
            return g
    return "F"


def main():
    print("Bufferbloat test (read-only). Don't use the internet meanwhile.\n")
    print("[1/3] idle ping...")
    idle = summarize(ping_series(HOST, SECS), SECS)
    print("[2/3] ping while DOWNLOADING (12s)...")
    down = loaded_phase(download_worker)
    print("[3/3] ping while UPLOADING (12s)...")
    up = loaded_phase(upload_worker)

    report = {"timestamp": datetime.now().isoformat(), "host": HOST,
              "idle": idle, "download": down, "upload": up}
    print("\n=========== RESULT ===========")
    print(f"Idle      : avg {idle['avg']} ms | max {idle['max']} | jitter {idle['jitter']}")
    for name, r in (("Download", down), ("Upload", up)):
        inc = None if r["avg"] is None or idle["avg"] is None else round(r["avg"] - idle["avg"], 1)
        r["increase_ms"], r["grade"] = inc, grade(inc)
        print(f"{name:9} : avg {r['avg']} ms | max {r['max']} | jitter {r['jitter']} | "
              f"loss {r['loss_pct']}% | {r['throughput_mbps']} Mbps | +{inc} ms -> grade {r['grade']}")
    print("\nGrades: A <5ms added, B <30, C <60, D <200, F worse.")
    print("Note: speeds here may not reach your plan's max; the latency increase is what matters.")

    os.makedirs("logs", exist_ok=True)
    path = os.path.join("logs", f"bufferbloat_{datetime.now():%Y%m%d_%H%M%S}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print("Saved:", path)


if __name__ == "__main__":
    main()
