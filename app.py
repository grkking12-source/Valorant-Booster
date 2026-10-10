"""
VALORANT BOOST
Simple Windows gaming support tool.

Run:
    python app.py

Requires:
    pip install PySide6 psutil

Audio:
    Requires Equalizer APO + audio_engine.py

Microphone:
    Requires Equalizer APO + mic_engine.py

Input:
    Requires input_engine.py

This program does NOT:
- modify VALORANT
- modify Vanguard
- inject into the game
- read game memory
- modify packets
"""

import re
import sys
import json
import time
import threading
import subprocess
import traceback
from pathlib import Path

import psutil

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QLabel,
    QPlainTextEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


# ============================================================
# ENGINE IMPORTS (CHANGED: app no longer crashes if missing)
# ============================================================

def make_missing_engine(label, module_name, error):

    class MissingEngine:

        def __init__(self, root, log=print):

            self.active = False
            self.log = log

            self.log(
                f"{label}: {module_name}.py failed to load ({error})"
            )

        def enable(self):

            self.log(
                f"{label}: unavailable ({module_name}.py missing)"
            )

        def disable(self):

            pass

        def status(self):

            return f"{label}: MODULE MISSING"

    return MissingEngine


try:
    from audio_engine import AudioEngine
except Exception as e:
    AudioEngine = make_missing_engine("SOUND", "audio_engine", e)

try:
    from mic_engine import MicEngine
except Exception as e:
    MicEngine = make_missing_engine("MIC", "mic_engine", e)

try:
    from input_engine import InputEngine
except Exception as e:
    InputEngine = make_missing_engine("INPUT", "input_engine", e)


# ============================================================
# PATHS
# ============================================================

ROOT = Path(__file__).resolve().parent

CONFIG_DIR = ROOT / "config"
LOG_DIR = ROOT / "logs"

CONFIG_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

CONFIG_FILE = CONFIG_DIR / "config.json"
CRASH_LOG = LOG_DIR / "crash.log"

# CHANGED: stops black console windows flashing on Windows
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ============================================================
# DEFAULT CONFIG
# ============================================================

DEFAULT_CONFIG = {
    "stop_processes": [
        "ollama.exe",
        "ollama app.exe"
    ],

    "stop_if_cmdline_contains": [],

    "stop_services": [],

    "keep_running": [
        "discord.exe",
        "chrome.exe",
        "nzxt cam.exe"
    ],

    "force_ok": [
        "ollama.exe",
        "ollama app.exe"
    ]
}


# ============================================================
# LOGGING
# ============================================================

def write_crash_log():

    try:

        with open(
            CRASH_LOG,
            "a",
            encoding="utf-8"
        ) as f:

            f.write("\n")
            f.write("=" * 70)
            f.write("\n")
            f.write(time.strftime("%Y-%m-%d %H:%M:%S"))
            f.write("\n")
            f.write(traceback.format_exc())
            f.write("\n")

    except Exception:
        pass


# ============================================================
# CONFIG
# ============================================================

def load_config():

    if not CONFIG_FILE.exists():

        CONFIG_FILE.write_text(
            json.dumps(
                DEFAULT_CONFIG,
                indent=4
            ),
            encoding="utf-8"
        )

        return DEFAULT_CONFIG.copy()

    try:

        data = json.loads(
            CONFIG_FILE.read_text(
                encoding="utf-8"
            )
        )

        return data

    except Exception:

        return DEFAULT_CONFIG.copy()


# ============================================================
# VALORANT DETECTOR
# ============================================================

class ValorantDetector:

    PROCESS_NAMES = {
        "valorant.exe",
        "valorant-win64-shipping.exe"
    }

    def is_running(self):

        try:

            for proc in psutil.process_iter(
                ["name"]
            ):

                try:

                    name = (
                        proc.info["name"] or ""
                    ).lower()

                    if name in self.PROCESS_NAMES:

                        return True

                except (
                    psutil.NoSuchProcess,
                    psutil.AccessDenied
                ):

                    continue

        except Exception:

            pass

        return False


# ============================================================
# ROLLBACK JOURNAL
# ============================================================

class RollbackJournal:

    def __init__(self, root):

        self.file = (
            Path(root)
            / "logs"
            / "rollback.json"
        )

    def save(self, data):

        try:

            self.file.write_text(
                json.dumps(
                    data,
                    indent=4
                ),
                encoding="utf-8"
            )

        except Exception:
            pass

    def load(self):

        if not self.file.exists():

            return {}

        try:

            return json.loads(
                self.file.read_text(
                    encoding="utf-8"
                )
            )

        except Exception:

            return {}

    def clear(self):

        try:

            self.file.unlink(
                missing_ok=True
            )

        except Exception:
            pass


# ============================================================
# GAMING MODE
# ============================================================

class GamingMode:

    def __init__(
        self,
        root,
        config,
        log=print
    ):

        self.root = Path(root)

        self.config = config

        self.log = log

        self.active = False

        self.stopped = []

    # --------------------------------------------------------
    # FIND PROCESSES
    # --------------------------------------------------------

    def find_processes(self):

        found = []

        targets = {
            x.lower()
            for x in self.config.get(
                "stop_processes",
                []
            )
        }

        command_terms = [
            x.lower()
            for x in self.config.get(
                "stop_if_cmdline_contains",
                []
            )
        ]

        keep = {
            x.lower()
            for x in self.config.get(
                "keep_running",
                []
            )
        }

        force_ok = {
            x.lower()
            for x in self.config.get(
                "force_ok",
                []
            )
        }

        for proc in psutil.process_iter(
            ["pid", "name", "cmdline"]
        ):

            try:

                name = (
                    proc.info["name"] or ""
                ).lower()

                if name in keep:
                    continue

                if name in force_ok:
                    found.append(proc)
                    continue

                if name in targets:

                    found.append(proc)

                    continue

                cmdline = " ".join(
                    proc.info["cmdline"] or []
                ).lower()

                for term in command_terms:

                    if term in cmdline:

                        found.append(proc)

                        break

            except (
                psutil.NoSuchProcess,
                psutil.AccessDenied
            ):

                continue

        return found

    # --------------------------------------------------------
    # ENABLE
    # --------------------------------------------------------

    def enable(self):

        if self.active:
            return

        self.log("GAMING MODE: ON")

        self.stopped = []

        processes = self.find_processes()

        for proc in processes:

            try:

                name = (
                    proc.info["name"]
                    or f"PID {proc.pid}"
                )

                self.log(
                    f"Stopping: {name}"
                )

                proc.terminate()

                try:

                    proc.wait(
                        timeout=3
                    )

                except psutil.TimeoutExpired:

                    proc.kill()

                self.stopped.append({
                    "name": name
                })

            except (
                psutil.NoSuchProcess,
                psutil.AccessDenied
            ):

                continue

            except Exception as e:

                self.log(
                    f"Process error: {e}"
                )

        self.active = True

    # --------------------------------------------------------
    # DISABLE
    # --------------------------------------------------------

    def disable(self):

        if not self.active:
            return

        self.log(
            "GAMING MODE: OFF"
        )

        self.log(
            "Background process restoration is handled by Windows/apps."
        )

        self.stopped = []

        self.active = False


# ============================================================
# METRICS
# ============================================================

class Metrics:

    def __init__(self):

        self.last_ping = None

        self.gpu_usage = None

        # CHANGED: background thread flag
        self._running = False

    # --------------------------------------------------------
    # PING
    # --------------------------------------------------------

    def ping(self):

        try:

            result = subprocess.run(
                [
                    "ping",
                    "1.1.1.1",
                    "-n",
                    "1",
                    "-w",
                    "1000"
                ],
                capture_output=True,
                text=True,
                timeout=2,
                creationflags=NO_WINDOW
            )

            output = (
                result.stdout
                + result.stderr
            )

            match = re.search(
                r"(\d+)\s*ms",
                output
            )

            if match:

                self.last_ping = int(
                    match.group(1)
                )

            else:

                self.last_ping = None

        except Exception:

            self.last_ping = None

    # --------------------------------------------------------
    # GPU
    # --------------------------------------------------------

    def gpu(self):

        try:

            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=utilization.gpu",
                    "--format=csv,noheader,nounits"
                ],
                capture_output=True,
                text=True,
                timeout=2,
                creationflags=NO_WINDOW
            )

            value = result.stdout.strip()

            if value:

                self.gpu_usage = int(
                    value.splitlines()[0]
                )

            else:

                self.gpu_usage = None

        except Exception:

            self.gpu_usage = None

    # --------------------------------------------------------
    # UPDATE
    # --------------------------------------------------------

    def update(self):

        self.ping()

        self.gpu()

    # --------------------------------------------------------
    # UPDATE IN BACKGROUND (CHANGED: UI no longer freezes)
    # --------------------------------------------------------

    def update_async(self):

        if self._running:
            return

        self._running = True

        def worker():

            try:

                self.update()

            finally:

                self._running = False

        threading.Thread(
            target=worker,
            daemon=True
        ).start()


# ============================================================
# MAIN WINDOW
# ============================================================

class Window(QWidget):

    def __init__(self):

        super().__init__()

        self.setWindowTitle(
            "VALORANT BOOST"
        )

        self.resize(
            850,
            700
        )

        # CHANGED: UI is built first so self.log works
        # even when engines log during their own startup

        self.build_ui()

        # ----------------------------------------------------
        # CORE SYSTEMS
        # ----------------------------------------------------

        self.config = load_config()

        self.detector = ValorantDetector()

        self.journal = RollbackJournal(ROOT)

        self.gm = GamingMode(
            ROOT,
            self.config,
            log=self.log
        )

        # ----------------------------------------------------
        # AUDIO ENGINE
        # ----------------------------------------------------

        self.audio = AudioEngine(
            ROOT,
            log=self.log
        )

        # ----------------------------------------------------
        # MICROPHONE ENGINE
        # ----------------------------------------------------

        self.mic = MicEngine(
            ROOT,
            log=self.log
        )

        # ----------------------------------------------------
        # INPUT ENGINE
        # ----------------------------------------------------

        self.input = InputEngine(
            ROOT,
            log=self.log
        )

        # ----------------------------------------------------
        # METRICS
        # ----------------------------------------------------

        self.metrics = Metrics()

        # ----------------------------------------------------
        # AUTO STATE
        # ----------------------------------------------------

        self.auto_mode = True

        self.valorant_was_running = False

        # ----------------------------------------------------
        # TIMER
        # ----------------------------------------------------

        self.timer = QTimer(self)

        self.timer.timeout.connect(
            self.tick
        )

        self.timer.start(
            2000
        )

        # Initial refresh

        self.refresh()

        self.log(
            "VALORANT BOOST READY"
        )

    # ========================================================
    # UI
    # ========================================================

    def build_ui(self):

        layout = QVBoxLayout(
            self
        )

        # ----------------------------------------------------
        # TITLE
        # ----------------------------------------------------

        title = QLabel(
            "VALORANT BOOST"
        )

        title.setStyleSheet(
            "font-size: 24px; font-weight: bold;"
        )

        layout.addWidget(title)

        # ----------------------------------------------------
        # STATUS
        # ----------------------------------------------------

        self.mode_label = QLabel(
            "STATUS: READY"
        )

        self.valorant_label = QLabel(
            "VALORANT: NOT DETECTED"
        )

        self.network_label = QLabel(
            "PING: --"
        )

        self.gpu_label = QLabel(
            "GPU: --"
        )

        self.sound_label = QLabel(
            "SOUND: --"
        )

        self.mic_label = QLabel(
            "MIC: --"
        )

        self.input_label = QLabel(
            "INPUT: --"
        )

        layout.addWidget(
            self.mode_label
        )

        layout.addWidget(
            self.valorant_label
        )

        layout.addWidget(
            self.network_label
        )

        layout.addWidget(
            self.gpu_label
        )

        layout.addWidget(
            self.sound_label
        )

        layout.addWidget(
            self.mic_label
        )

        layout.addWidget(
            self.input_label
        )

        # ----------------------------------------------------
        # BUTTON GRID
        # ----------------------------------------------------

        buttons = QGridLayout()

        # GAMING BUTTON

        self.gaming_button = QPushButton(
            "ENABLE GAMING MODE"
        )

        self.gaming_button.clicked.connect(
            self.toggle_gaming
        )

        buttons.addWidget(
            self.gaming_button,
            0,
            0
        )

        # SOUND BUTTON

        self.sound_button = QPushButton(
            "ENABLE SOUND MODE"
        )

        self.sound_button.clicked.connect(
            self.toggle_sound
        )

        buttons.addWidget(
            self.sound_button,
            0,
            1
        )

        # MIC BUTTON

        self.mic_button = QPushButton(
            "ENABLE MIC MODE"
        )

        self.mic_button.clicked.connect(
            self.toggle_mic
        )

        buttons.addWidget(
            self.mic_button,
            1,
            0
        )

        # INPUT BUTTON

        self.input_button = QPushButton(
            "ENABLE INPUT MODE"
        )

        self.input_button.clicked.connect(
            self.toggle_input
        )

        buttons.addWidget(
            self.input_button,
            1,
            1
        )

        # REFRESH BUTTON

        self.refresh_button = QPushButton(
            "REFRESH"
        )

        self.refresh_button.clicked.connect(
            self.refresh
        )

        buttons.addWidget(
            self.refresh_button,
            2,
            0
        )

        # AUTO BUTTON

        self.auto_button = QPushButton(
            "AUTO MODE: ON"
        )

        self.auto_button.clicked.connect(
            self.toggle_auto
        )

        buttons.addWidget(
            self.auto_button,
            2,
            1
        )

        layout.addLayout(
            buttons
        )

        # ----------------------------------------------------
        # RUNNING APPS
        # ----------------------------------------------------

        apps_label = QLabel(
            "RUNNING / TARGET PROCESSES"
        )

        layout.addWidget(
            apps_label
        )

        self.apps_list = QListWidget()

        layout.addWidget(
            self.apps_list
        )

        # ----------------------------------------------------
        # LOG
        # ----------------------------------------------------

        log_label = QLabel(
            "LOG"
        )

        layout.addWidget(
            log_label
        )

        self.logbox = QPlainTextEdit()

        self.logbox.setReadOnly(
            True
        )

        layout.addWidget(
            self.logbox
        )

    # ========================================================
    # LOG
    # ========================================================

    def log(self, message):

        timestamp = time.strftime(
            "%H:%M:%S"
        )

        line = (
            f"[{timestamp}] {message}"
        )

        try:

            self.logbox.appendPlainText(
                line
            )

        except Exception:

            print(line)

    # ========================================================
    # BUSY
    # ========================================================

    def busy(self, text):

        self.mode_label.setText(
            f"STATUS: {text}"
        )

        QApplication.processEvents()

    # ========================================================
    # GAMING MODE
    # ========================================================

    def enable(self):

        self.busy(
            "WORKING..."
        )

        # Background optimization

        self.gm.enable()

        # Headset sound

        self.audio.enable()

        # Microphone

        self.mic.enable()

        # Keyboard + mouse input

        self.input.enable()

        self.refresh()

    # ========================================================
    # DISABLE / RESTORE
    # ========================================================

    def disable(self):

        self.busy(
            "RESTORING..."
        )

        # Restore input

        self.input.disable()

        # Restore microphone

        self.mic.disable()

        # Restore headset audio

        self.audio.disable()

        # Restore gaming mode

        self.gm.disable()

        self.refresh()

    # ========================================================
    # TOGGLE GAMING
    # ========================================================

    def toggle_gaming(self):

        if self.gm.active:

            self.disable()

        else:

            self.enable()

    # ========================================================
    # SOUND MODE
    # ========================================================

    def toggle_sound(self):

        if self.audio.active:

            self.audio.disable()

        else:

            self.audio.enable()

        self.refresh()

    # ========================================================
    # MIC MODE
    # ========================================================

    def toggle_mic(self):

        if self.mic.active:

            self.mic.disable()

        else:

            self.mic.enable()

        self.refresh()

    # ========================================================
    # INPUT MODE
    # ========================================================

    def toggle_input(self):

        if self.input.active:

            self.input.disable()

        else:

            self.input.enable()

        self.refresh()

    # ========================================================
    # AUTO MODE
    # ========================================================

    def toggle_auto(self):

        self.auto_mode = (
            not self.auto_mode
        )

        self.auto_button.setText(
            "AUTO MODE: ON"
            if self.auto_mode
            else "AUTO MODE: OFF"
        )

        self.log(
            "AUTO MODE: "
            + (
                "ON"
                if self.auto_mode
                else "OFF"
            )
        )

    # ========================================================
    # AUTO DETECTION
    # ========================================================

    def tick(self):

        try:

            running = (
                self.detector.is_running()
            )

            # VALORANT STARTED

            if (
                running
                and not self.valorant_was_running
            ):

                self.log(
                    "VALORANT detected."
                )

                if self.auto_mode:

                    self.log(
                        "Starting Gaming Mode."
                    )

                    self.enable()

            # VALORANT CLOSED

            if (
                not running
                and self.valorant_was_running
            ):

                self.log(
                    "VALORANT closed."
                )

                if self.auto_mode:

                    self.log(
                        "Restoring system."
                    )

                    self.disable()

            self.valorant_was_running = (
                running
            )

            self.refresh()

        except Exception as e:

            self.log(
                f"TICK ERROR: {e}"
            )

    # ========================================================
    # REFRESH
    # ========================================================

    def refresh(self):

        try:

            running = (
                self.detector.is_running()
            )

            # VALORANT STATUS

            if running:

                self.valorant_label.setText(
                    "VALORANT: RUNNING"
                )

            else:

                self.valorant_label.setText(
                    "VALORANT: NOT DETECTED"
                )

            # GAMING STATUS

            if self.gm.active:

                self.mode_label.setText(
                    "STATUS: GAMING MODE ON"
                )

                self.gaming_button.setText(
                    "DISABLE GAMING MODE"
                )

            else:

                self.mode_label.setText(
                    "STATUS: READY"
                )

                self.gaming_button.setText(
                    "ENABLE GAMING MODE"
                )

            # SOUND STATUS

            self.sound_label.setText(
                self.audio.status()
            )

            if self.audio.active:

                self.sound_button.setText(
                    "DISABLE SOUND MODE"
                )

            else:

                self.sound_button.setText(
                    "ENABLE SOUND MODE"
                )

            # MICROPHONE STATUS

            self.mic_label.setText(
                self.mic.status()
            )

            if self.mic.active:

                self.mic_button.setText(
                    "DISABLE MIC MODE"
                )

            else:

                self.mic_button.setText(
                    "ENABLE MIC MODE"
                )

            # INPUT STATUS

            self.input_label.setText(
                self.input.status()
            )

            if self.input.active:

                self.input_button.setText(
                    "DISABLE INPUT MODE"
                )

            else:

                self.input_button.setText(
                    "ENABLE INPUT MODE"
                )

            # NETWORK / GPU
            # CHANGED: runs in background, shows last known values

            self.metrics.update_async()

            if self.metrics.last_ping is None:

                self.network_label.setText(
                    "PING: --"
                )

            else:

                self.network_label.setText(
                    f"PING: {self.metrics.last_ping} ms"
                )

            if self.metrics.gpu_usage is None:

                self.gpu_label.setText(
                    "GPU: --"
                )

            else:

                self.gpu_label.setText(
                    f"GPU: {self.metrics.gpu_usage}%"
                )

            # PROCESS LIST

            self.refresh_process_list()

        except Exception as e:

            self.log(
                f"REFRESH ERROR: {e}"
            )

    # ========================================================
    # PROCESS LIST
    # ========================================================

    def refresh_process_list(self):

        self.apps_list.clear()

        targets = []

        configured_names = {
            x.lower()
            for x in self.config.get(
                "stop_processes",
                []
            )
        }

        for proc in psutil.process_iter(
            ["pid", "name"]
        ):

            try:

                name = (
                    proc.info["name"]
                    or ""
                )

                lower = name.lower()

                if lower in configured_names:

                    targets.append(
                        (
                            proc.info["pid"],
                            name
                        )
                    )

            except (
                psutil.NoSuchProcess,
                psutil.AccessDenied
            ):

                continue

        if not targets:

            item = QListWidgetItem(
                "No target processes running"
            )

            self.apps_list.addItem(
                item
            )

            return

        for pid, name in targets:

            item = QListWidgetItem(
                f"{name}   PID: {pid}"
            )

            self.apps_list.addItem(
                item
            )

    # ========================================================
    # CLOSE
    # ========================================================

    def closeEvent(self, event):

        try:

            self.log(
                "Closing VALORANT BOOST..."
            )

            self.timer.stop()

            # Restore input

            self.input.disable()

            # Restore microphone

            self.mic.disable()

            # Restore audio

            self.audio.disable()

            # Restore gaming mode

            self.gm.disable()

            self.log(
                "System restored."
            )

        except Exception:

            write_crash_log()

        event.accept()


# ============================================================
# MAIN
# ============================================================

def main():

    try:

        app = QApplication(
            sys.argv
        )

        window = Window()

        window.show()

        sys.exit(
            app.exec()
        )

    except Exception:

        write_crash_log()

        raise


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()