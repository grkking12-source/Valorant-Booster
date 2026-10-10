"""Plans and performs stopping of USER-APPROVED background apps. Nothing is stopped unless it is
named in config/safe_list.json AND is not protected. Every stop is journaled first, so
'RESTORE' relaunches it. Apps are first asked to close normally (so they can offer to save);
only apps in 'force_ok' (windowless servers) are ended instantly if that is not possible."""
import json
import os
import subprocess

from engine.rollback import record_app_before_stop, record_service_before_stop

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
ALWAYS_PROTECTED = {
    "vgc.exe", "vgtray.exe", "valorant.exe", "valorant-win64-shipping.exe", "riotclientservices.exe",
    "riotclientux.exe", "riotclientuxrender.exe", "msmpeng.exe", "nissrv.exe", "securityhealthservice.exe",
    "svchost.exe", "explorer.exe", "dwm.exe", "csrss.exe", "winlogon.exe", "services.exe", "lsass.exe",
    "audiodg.exe", "system", "registry", "memcompression", "nvcontainer.exe", "nvdisplay.container.exe", "nzxt cam.exe",
}
PROTECTED_PATH_PARTS = ("\\windows\\", "\\riot games\\", "vanguard", "defender", "antivirus",
                        "malwarebytes", "kaspersky", "avast", "norton", "bitdefender", "eset", "sophos")


def load_config(path):
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    for k in ("stop_processes", "stop_if_cmdline_contains", "stop_services", "keep_running", "force_ok"):
        cfg[k] = [x.lower() for x in cfg.get(k, [])]
    return cfg


def protected_reason(name, exe, pid, own_pids, cfg):
    n, e = (name or "").lower(), (exe or "").lower()
    if pid in own_pids:
        return "this app or its terminal"
    if n in ALWAYS_PROTECTED:
        return "built-in protected process"
    if n in cfg["keep_running"]:
        return "in your keep_running list"
    if any(part in e for part in PROTECTED_PATH_PARTS):
        return "Windows / Riot / security software path"
    return None


def is_approved(name, cmdline, cfg):
    n, c = (name or "").lower(), (cmdline or "").lower()
    return n in cfg["stop_processes"] or any(s in c for s in cfg["stop_if_cmdline_contains"])


def own_pids():
    import psutil
    pids, p = {os.getpid()}, psutil.Process()
    for parent in p.parents():
        pids.add(parent.pid)
    return pids


def build_plan(cfg):
    import psutil
    own, procs = own_pids(), []
    for p in psutil.process_iter(["pid", "ppid", "name", "exe", "cmdline", "memory_info"]):
        try:
            i = p.info
            procs.append({
                "pid": i["pid"], "ppid": i["ppid"], "name": i["name"] or "?", "exe": i["exe"] or "",
                "ram_mb": round((i["memory_info"].rss if i["memory_info"] else 0) / 2**20),
                "protected": protected_reason(i["name"], i["exe"], i["pid"], own, cfg),
                "approved": is_approved(i["name"], " ".join(i["cmdline"] or []), cfg)})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    ok = [x for x in procs if x["approved"] and not x["protected"]]
    ids = {x["pid"] for x in ok}
    stop = [x for x in ok if x["ppid"] not in ids]  # top-level only; children exit with parent
    refused = {x["name"]: x["protected"] for x in procs if x["approved"] and x["protected"]}
    services = []
    for s in cfg["stop_services"]:
        try:
            services.append({"name": s, "running": psutil.win_service_get(s).status() == "running"})
        except Exception:
            services.append({"name": s, "running": False})
    others = sorted((x for x in procs if not x["approved"] and x["ram_mb"] > 150 and x["name"] != "?"),
                    key=lambda x: -x["ram_mb"])
    return {"stop": stop, "refused": refused, "services": services, "keeping": others[:8],
            "force_ok": set(cfg["force_ok"])}


def _graceful_close(pid):
    """Ask the app to close like the X button would (no /F). True if the request was accepted."""
    r = subprocess.run(["taskkill", "/PID", str(pid)], capture_output=True, text=True,
                       creationflags=NO_WINDOW)
    return r.returncode == 0


def save_config(path, cfg):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in cfg.items() if isinstance(v, list) or k.startswith("_")}, f, indent=2)


def heavy_apps(cfg, min_mb=150):
    """Apps (grouped by name) that are big enough to matter. Protected / unverifiable ones never appear."""
    import psutil
    own, agg = own_pids(), {}
    for p in psutil.process_iter(["pid", "name", "exe", "memory_info"]):
        try:
            i = p.info
            name = i["name"] or "?"
            if name == "?" or not i["exe"] or protected_reason(name, i["exe"], i["pid"], own, cfg):
                continue
            a = agg.setdefault(name.lower(), {"name": name, "count": 0, "ram_mb": 0.0})
            a["count"] += 1
            a["ram_mb"] += (i["memory_info"].rss if i["memory_info"] else 0) / 2**20
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    rows = []
    for k, a in agg.items():
        a["ram_mb"], a["approved"] = round(a["ram_mb"]), k in cfg["stop_processes"]
        if a["ram_mb"] >= min_mb or a["approved"]:
            rows.append(a)
    return sorted(rows, key=lambda r: -r["ram_mb"])


def apply_plan(journal, plan):
    """Stop approved apps. Returns list of (label, outcome)."""
    import psutil
    out = []
    for e in plan["stop"]:
        try:
            p = psutil.Process(e["pid"])
            record_app_before_stop(journal, p)  # saved BEFORE stopping; failure => not stopped
        except Exception as ex:
            out.append((e["name"], f"SKIPPED (cannot save restore info: {ex})"))
            continue
        try:
            asked = _graceful_close(e["pid"])
            if not asked and e["name"].lower() in plan.get("force_ok", ()):
                p.terminate()  # windowless server on your force_ok list
                asked = True
            if not asked:
                out.append((e["name"], "LEFT RUNNING (no window to close politely; not in force_ok)"))
                continue
            _, alive = psutil.wait_procs([p], timeout=8)
            out.append((e["name"], "LEFT RUNNING (still open - maybe asking to save)" if alive else "STOPPED"))
        except Exception as ex:
            out.append((e["name"], f"FAILED: {ex}"))
    for s in plan["services"]:
        if not s["running"]:
            continue
        record_service_before_stop(journal, s["name"], True)
        r = subprocess.run(["sc", "stop", s["name"]], capture_output=True, text=True,
                           creationflags=NO_WINDOW)
        out.append((s["name"], "STOP REQUESTED" if r.returncode == 0 else "FAILED (needs admin?)"))
    return out
