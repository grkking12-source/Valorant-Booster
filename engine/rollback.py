"""
Write-ahead rollback journal (SQLite).

RULE: every optimizer must call record() BEFORE it changes anything.
If the app crashes (even mid-change), the next launch calls recover_on_startup()
which restores the saved original values, newest change first.

Reverting is idempotent: restoring an original value is safe even if the change
never actually happened. A revert that fails stays 'pending' and is retried.

Use the helpers (set_registry_value, set_process_priority, record_*_before_stop)
so a change can never be applied without being recorded first.
"""
import json
import ntpath
import os
import platform
import sqlite3
import subprocess
import time
from datetime import datetime

IS_WIN = platform.system() == "Windows"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
ABSENT = "__ABSENT__"
REVERTORS = {}


def register_revertor(kind, fn):
    REVERTORS[kind] = fn


class RollbackJournal:
    def __init__(self, db_path="logs/rollback.db"):
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self.db = sqlite3.connect(db_path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS changes(
            id INTEGER PRIMARY KEY AUTOINCREMENT, created TEXT, kind TEXT, target TEXT,
            original TEXT, reverted INTEGER DEFAULT 0, error TEXT)""")
        self.db.commit()

    def record(self, kind, target, original):
        """Save original state. Committed to disk before the caller changes anything."""
        cur = self.db.execute(
            "INSERT INTO changes(created,kind,target,original) VALUES(?,?,?,?)",
            (datetime.now().isoformat(), kind, target, json.dumps(original)))
        self.db.commit()
        return cur.lastrowid

    def pending(self):
        return self.db.execute(
            "SELECT id,kind,target,original FROM changes WHERE reverted=0 ORDER BY id DESC").fetchall()

    def revert_all(self):
        """Undo everything pending, newest first. Returns [(id, kind, target, ok, message)]."""
        results = []
        for cid, kind, target, original in self.pending():
            try:
                fn = REVERTORS.get(kind)
                if fn is None:
                    raise RuntimeError(f"no revertor registered for kind '{kind}'")
                msg = fn(target, json.loads(original)) or "restored"
                self.db.execute("UPDATE changes SET reverted=1,error=NULL WHERE id=?", (cid,))
                results.append((cid, kind, target, True, msg))
            except Exception as e:  # stays pending -> retried next launch
                self.db.execute("UPDATE changes SET error=? WHERE id=?", (str(e), cid))
                results.append((cid, kind, target, False, str(e)))
            self.db.commit()
        return results

    def recover_on_startup(self):
        """Call at every app launch. Restores anything a crashed session left changed."""
        return self.revert_all() if self.pending() else []


# ------------------------------------------------------------------ registry
_HIVES = {}
if IS_WIN:
    import winreg
    _HIVES = {"HKCU": winreg.HKEY_CURRENT_USER, "HKLM": winreg.HKEY_LOCAL_MACHINE}


def _revert_registry(target, o):
    import winreg
    with winreg.CreateKeyEx(_HIVES[o["hive"]], o["path"], 0, winreg.KEY_SET_VALUE) as key:
        if o["value"] == ABSENT:
            try:
                winreg.DeleteValue(key, o["name"])
            except FileNotFoundError:
                pass
        else:
            winreg.SetValueEx(key, o["name"], 0, o["type"], o["value"])


def set_registry_value(journal, hive, path, name, value, reg_type):
    """Record the original, THEN set the new value."""
    import winreg
    try:
        with winreg.OpenKey(_HIVES[hive], path) as k:
            cur, cur_type = winreg.QueryValueEx(k, name)
    except OSError:
        cur, cur_type = ABSENT, reg_type
    journal.record("registry_value", f"{hive}\\{path}\\{name}",
                   {"hive": hive, "path": path, "name": name, "value": cur, "type": cur_type})
    with winreg.CreateKeyEx(_HIVES[hive], path, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, name, 0, reg_type, value)


# ------------------------------------------------------------------ process priority
def _revert_priority(target, o):
    import psutil
    try:
        p = psutil.Process(o["pid"])
        if abs(p.create_time() - o["create_time"]) > 1:  # PID was reused by another program
            return
        p.nice(o["nice"])
    except psutil.NoSuchProcess:
        return  # process already gone: nothing to restore


def set_process_priority(journal, pid, new_priority):
    import psutil
    p = psutil.Process(pid)
    journal.record("process_priority", f"{p.name()}[{pid}]",
                   {"pid": pid, "create_time": p.create_time(), "nice": p.nice()})
    p.nice(new_priority)


# ------------------------------------------------------------------ stopped apps / services
GENERIC = {"python.exe", "pythonw.exe", "node.exe", "java.exe", "javaw.exe"}


def _same_app(o, exe, cmdline):
    """Is a running process the app we stopped? Interpreters (python/node/java) are
    compared by full command line, because many unrelated apps share the same exe."""
    if (exe or "").lower() != (o["exe"] or "").lower():
        return False
    if ntpath.basename(o["exe"] or "").lower() in GENERIC:
        return list(cmdline or []) == list(o["cmdline"])
    return True


def _revert_restart_app(target, o):
    import psutil
    me = os.getpid()
    for p in psutil.process_iter(["exe", "cmdline"]):
        if p.pid != me and _same_app(o, p.info["exe"], p.info["cmdline"]):
            return f"skipped: already running (pid {p.pid})"
    flags = (0x00000008 | 0x00000200) if IS_WIN else 0  # DETACHED | NEW_PROCESS_GROUP
    proc = subprocess.Popen(o["cmdline"], cwd=o["cwd"] or None, creationflags=flags,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.5)
    if proc.poll() is not None:  # never claim success for an app that died at once
        raise RuntimeError(f"relaunched app exited immediately (code {proc.returncode})")
    return f"relaunched as pid {proc.pid}"


def record_app_before_stop(journal, proc):
    """Call BEFORE terminating a psutil.Process the user approved."""
    journal.record("restart_app", proc.name(),
                   {"exe": proc.exe(), "cmdline": proc.cmdline(), "cwd": proc.cwd()})


def _revert_service(target, o):
    if o["was_running"]:
        subprocess.run(["sc", "start", o["name"]], capture_output=True, creationflags=NO_WINDOW)


def record_service_before_stop(journal, name, was_running):
    journal.record("service_state", name, {"name": name, "was_running": was_running})


register_revertor("registry_value", _revert_registry)
register_revertor("process_priority", _revert_priority)
register_revertor("restart_app", _revert_restart_app)
register_revertor("service_state", _revert_service)
