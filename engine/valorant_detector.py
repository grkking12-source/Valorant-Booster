"""Detects VALORANT and Vanguard using normal process/service queries only.
Never opens, injects into, or inspects the game process itself."""
import subprocess
import time

import psutil

GAME = "valorant-win64-shipping.exe"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def game_pids():
    return [p.pid for p in psutil.process_iter(["name"])
            if (p.info["name"] or "").lower() == GAME]


def vanguard_status():
    names = {(p.info["name"] or "").lower() for p in psutil.process_iter(["name"])}
    svc = "unknown"
    try:
        out = subprocess.run(["sc", "query", "vgc"], capture_output=True, text=True,
                             timeout=5, creationflags=NO_WINDOW).stdout
        svc = "RUNNING" if "RUNNING" in out else "STOPPED" if "STOPPED" in out else "unknown"
    except Exception:
        pass
    return {"process_visible": "vgc.exe" in names, "service": svc}


def watch(on_start, on_stop, interval=2.0, should_stop=lambda: False):
    running = False
    while not should_stop():
        now = bool(game_pids())
        if now and not running:
            on_start()
        elif running and not now:
            on_stop()
        running = now
        time.sleep(interval)
