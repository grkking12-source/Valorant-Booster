"""VALORANT BOOST - simple window.  Run:  python app.py   (needs: pip install PySide6 psutil)
Watches for VALORANT automatically. Gaming mode turns ON when the game starts and is restored
when it closes. The button starts it manually / restores. Closing the window restores everything.
It never touches the VALORANT process."""
import collections
import os
import re
import statistics
import subprocess
import sys
import threading
import time
from audio_engine import AudioEngine

# When packaged as an .exe, keep config + logs NEXT TO the exe (not in a temp folder).
ROOT = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
        else os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
os.makedirs(os.path.join(ROOT, "config"), exist_ok=True)
DEFAULT_CFG = """{
  "stop_processes": ["ollama.exe", "ollama app.exe"],
  "stop_if_cmdline_contains": [],
  "stop_services": [],
  "keep_running": ["discord.exe", "chrome.exe", "nzxt cam.exe"],
  "force_ok": ["ollama.exe", "ollama app.exe"]
}
"""
CFG_PATH = os.path.join(ROOT, "config", "safe_list.json")
if not os.path.exists(CFG_PATH):
    with open(CFG_PATH, "w", encoding="utf-8") as _f:
        _f.write(DEFAULT_CFG)


def _crash_log(exc_type, exc, tb):  # a windowed exe has no console, so errors go to a file
    import traceback
    with open(os.path.join(ROOT, "logs", "error.log"), "a", encoding="utf-8") as f:
        f.write("".join(traceback.format_exception(exc_type, exc, tb)) + "\n")


sys.excepthook = _crash_log
import psutil  # noqa: E402
from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import (QApplication, QGridLayout, QLabel, QPlainTextEdit,  # noqa: E402
                               QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget)

from engine import valorant_detector as vd  # noqa: E402
from engine.gaming_mode import GamingMode  # noqa: E402
from engine.rollback import RollbackJournal  # noqa: E402
from process_manager import manager as pm  # noqa: E402

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
STYLE = """QWidget{background:#14161a;color:#e8e8e8;font-size:14px}
QPushButton{background:#2b6cff;border:0;padding:14px;font-size:16px;font-weight:bold;border-radius:6px}
QPushButton:disabled{background:#444}QPlainTextEdit{background:#0e0f12;border:1px solid #2a2d33}"""


class Metrics:
    """Background samplers. Ping goes to 1.1.1.1 (NOT a Riot server) - it shows your local line health."""
    def __init__(self):
        self.pings, self.gpu, self.stop = collections.deque(maxlen=30), "---", False
        threading.Thread(target=self._ping, daemon=True).start()
        threading.Thread(target=self._gpu, daemon=True).start()

    def _ping(self):
        while not self.stop:
            val = None
            try:
                out = subprocess.run(["ping", "-n", "1", "-w", "1000", "1.1.1.1"], capture_output=True,
                                     text=True, creationflags=NO_WINDOW, errors="replace", timeout=5).stdout
                m = re.search(r"[=<]\s*(\d+)\s*ms", out) if "TTL" in out.upper() else None
                val = float(m.group(1)) if m else None
            except Exception:
                pass
            self.pings.append(val)
            time.sleep(0.5)

    def _gpu(self):
        while not self.stop:
            try:
                out = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,temperature.gpu",
                                      "--format=csv,noheader,nounits"], capture_output=True, text=True,
                                     creationflags=NO_WINDOW, timeout=5).stdout.strip().split(",")
                self.gpu = f"{out[0].strip()}%  ({out[1].strip()} C)"
            except Exception:
                self.gpu = "n/a"
            time.sleep(2)

    def ping_summary(self):
        n = len(self.pings)
        vals = [x for x in self.pings if x is not None]
        if not n:
            return "---", "---", "---"
        loss = f"{100 * (n - len(vals)) / n:.0f}%"
        if not vals:
            return "no reply", "---", loss
        jit = statistics.mean(abs(a - b) for a, b in zip(vals, vals[1:])) if len(vals) > 1 else 0.0
        return f"{vals[-1]:.0f} ms (avg {statistics.mean(vals):.0f})", f"{jit:.1f} ms", loss


class Window(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VALORANT BOOST")
        self.resize(420, 760)
        self.setStyleSheet(STYLE)
        lay = QVBoxLayout(self)
        self.mode = QLabel("")
        self.mode.setStyleSheet("font-size:20px;font-weight:bold")
        lay.addWidget(self.mode)
        grid, self.vals = QGridLayout(), {}
        for r, name in enumerate(["VALORANT", "CPU", "GPU", "PING (1.1.1.1)", "JITTER", "PACKET LOSS", "FPS"]):
            grid.addWidget(QLabel(name), r, 0)
            self.vals[name] = QLabel("---")
            grid.addWidget(self.vals[name], r, 1)
        lay.addLayout(grid)
        lay.addWidget(QLabel("Apps to close in gaming mode (tick = close, asks them nicely first):"))
        self.apps = QListWidget()
        lay.addWidget(self.apps)
        self.btn_refresh = QPushButton("Refresh app list")
        self.btn_refresh.clicked.connect(lambda: self.refresh_apps())
        lay.addWidget(self.btn_refresh)
        self.btn = QPushButton("")
        self.btn.clicked.connect(self.on_button)
        lay.addWidget(self.btn)
        self.logbox = QPlainTextEdit()
        self.logbox.setReadOnly(True)
        lay.addWidget(self.logbox)

        self.journal = RollbackJournal(os.path.join(ROOT, "logs", "rollback.db"))
        self.cfg = pm.load_config(CFG_PATH)
        self.metrics = Metrics()
        self.gm = GamingMode(lambda: pm.build_plan(self.cfg), lambda p: pm.apply_plan(self.journal, p),
                             self.journal.revert_all, log=self.log)
        self.game = False
        for _, _, target, ok, msg in self.journal.recover_on_startup():
            self.log(f"Recovered from last session: {target}: {msg}")
        self.refresh_apps()
        self.apps.itemChanged.connect(self.on_item_changed)
        psutil.cpu_percent(None)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(2000)
        self.refresh()

    def refresh_apps(self):
        self.apps.blockSignals(True)
        self.apps.clear()
        for a in pm.heavy_apps(self.cfg):
            it = QListWidgetItem(f"{a['name']}  -  {a['ram_mb']} MB  ({a['count']} processes)")
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if a["approved"] else Qt.Unchecked)
            it.setData(Qt.UserRole, a["name"])
            self.apps.addItem(it)
        self.apps.blockSignals(False)

    def on_item_changed(self, it):
        name, lst = it.data(Qt.UserRole).lower(), self.cfg["stop_processes"]
        if it.checkState() == Qt.Checked and name not in lst:
            lst.append(name)
            self.log(f"Will close {name} in gaming mode (takes effect next time it starts)")
        elif it.checkState() != Qt.Checked and name in lst:
            lst.remove(name)
            self.log(f"Will leave {name} alone")
        pm.save_config(CFG_PATH, self.cfg)

    def log(self, text):
        self.logbox.appendPlainText(text.strip())

    def busy(self, text):
        self.mode.setText(text)
        QApplication.processEvents()

    def enable(self):
        self.busy("WORKING...")
        self.gm.enable()
        self.refresh()

    def disable(self):
        self.busy("RESTORING...")
        self.gm.disable()
        self.refresh()

    def on_button(self):
        self.disable() if self.gm.active else self.enable()

    def tick(self):
        now = bool(vd.game_pids())
        if now and not self.game:
            self.game = True
            self.log("VALORANT detected -> gaming mode ON")
            self.enable()
        elif self.game and not now:
            self.game = False
            self.log("VALORANT closed -> restoring")
            QTimer.singleShot(3000, lambda: None if self.game else self.disable())
        self.refresh()

    def refresh(self):
        self.mode.setText("GAMING MODE ON" if self.gm.active else "GAMING MODE OFF")
        self.btn.setText("RESTORE" if self.gm.active else "START GAMING MODE")
        ping, jit, loss = self.metrics.ping_summary()
        for k, v in {"VALORANT": "RUNNING" if self.game else "NOT RUNNING",
                     "CPU": f"{psutil.cpu_percent(None):.0f}%", "GPU": self.metrics.gpu,
                     "PING (1.1.1.1)": ping, "JITTER": jit, "PACKET LOSS": loss,
                     "FPS": "needs PresentMon (later)"}.items():
            self.vals[k].setText(v)

    def closeEvent(self, event):
        self.metrics.stop = True
        if self.gm.active or self.journal.pending():
            self.gm.disable()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = Window()
    w.show()
    sys.exit(app.exec())
