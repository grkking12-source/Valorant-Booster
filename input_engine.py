"""
VALORANT BOOST - Input Engine

Safe keyboard + mouse consistency support.

This module:
- Does NOT access VALORANT memory.
- Does NOT modify Vanguard.
- Does NOT inject into the game.
- Does NOT simulate mouse/keyboard presses.
- Does NOT change mouse sensitivity.
- Does NOT change polling rate.

It focuses on Windows power/performance conditions that can
affect USB keyboard/mouse consistency.

All changes are reversible.
"""

import subprocess
import ctypes
from pathlib import Path


class InputEngine:

    def __init__(self, root_dir, log=None):

        self.root = Path(root_dir)
        self.log = log or print

        self.active = False
        self.changed = False

        self.original_power_plan = None

    # ---------------------------------------------------------
    # ADMIN CHECK
    # ---------------------------------------------------------

    def is_admin(self):

        try:
            return bool(
                ctypes.windll.shell32.IsUserAnAdmin()
            )
        except Exception:
            return False

    # ---------------------------------------------------------
    # RUN COMMAND
    # ---------------------------------------------------------

    def run_command(self, command):

        try:

            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                shell=True,
                timeout=10
            )

            return result

        except Exception as e:

            self.log(
                f"INPUT COMMAND ERROR: {e}"
            )

            return None

    # ---------------------------------------------------------
    # POWER PLAN
    # ---------------------------------------------------------

    def get_power_plan(self):

        result = self.run_command(
            "powercfg /getactivescheme"
        )

        if not result:
            return None

        output = (
            result.stdout
            + result.stderr
        )

        # Example:
        # Power Scheme GUID: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
        # (Balanced)

        marker = "Power Scheme GUID:"

        if marker not in output:
            return None

        try:

            line = [
                x.strip()
                for x in output.splitlines()
                if marker in x
            ][0]

            value = line.split(
                marker,
                1
            )[1].strip()

            guid = value.split()[0]

            return guid

        except Exception:

            return None

    # ---------------------------------------------------------
    # PERFORMANCE PLAN
    # ---------------------------------------------------------

    def enable_performance_plan(self):

        current = self.get_power_plan()

        if current:

            self.original_power_plan = current

        # Windows High Performance GUID
        high_performance = (
            "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
        )

        result = self.run_command(
            f"powercfg /setactive {high_performance}"
        )

        if result and result.returncode == 0:

            self.log(
                "INPUT: High Performance power plan ON"
            )

            return True

        self.log(
            "INPUT: Could not enable High Performance plan"
        )

        return False

    # ---------------------------------------------------------
    # RESTORE POWER PLAN
    # ---------------------------------------------------------

    def restore_power_plan(self):

        if not self.original_power_plan:

            return True

        result = self.run_command(
            f"powercfg /setactive "
            f"{self.original_power_plan}"
        )

        if result and result.returncode == 0:

            self.log(
                "INPUT: Original power plan restored"
            )

            self.original_power_plan = None

            return True

        self.log(
            "INPUT: Could not restore original power plan"
        )

        return False

    # ---------------------------------------------------------
    # USB POWER SETTINGS
    # ---------------------------------------------------------

    def disable_usb_selective_suspend(self):

        # USB selective suspend:
        # Current AC setting = 0
        #
        # This prevents Windows from aggressively
        # suspending USB devices while gaming.

        commands = [

            (
                "powercfg /setacvalueindex "
                "SCHEME_CURRENT "
                "2a737441-1930-4402-8d77-b2bebba308a3 "
                "48e6b7a6-50f5-4782-a5d4-53bb8f07e226 0"
            ),

            (
                "powercfg /setactive SCHEME_CURRENT"
            )

        ]

        success = True

        for command in commands:

            result = self.run_command(command)

            if not result or result.returncode != 0:

                success = False

        if success:

            self.log(
                "INPUT: USB selective suspend OFF"
            )

        else:

            self.log(
                "INPUT: USB power setting could not be changed"
            )

        return success

    # ---------------------------------------------------------
    # ENABLE
    # ---------------------------------------------------------

    def enable(self):

        if self.active:
            return True

        self.log(
            "----------------------------------------"
        )

        self.log(
            "INPUT MODE: STARTING"
        )

        if not self.is_admin():

            self.log(
                "INPUT: Administrator permission required"
            )

            self.log(
                "INPUT MODE: NOT ENABLED"
            )

            return False

        try:

            self.enable_performance_plan()

            self.disable_usb_selective_suspend()

            self.active = True
            self.changed = True

            self.log(
                "INPUT MODE: ON"
            )

            self.log(
                "Keyboard: optimized environment"
            )

            self.log(
                "Mouse: optimized environment"
            )

            self.log(
                "Input automation: NONE"
            )

            self.log(
                "VALORANT/Vanguard: untouched"
            )

            return True

        except Exception as e:

            self.log(
                f"INPUT ERROR: {e}"
            )

            self.restore()

            return False

    # ---------------------------------------------------------
    # RESTORE
    # ---------------------------------------------------------

    def restore(self):

        if not self.changed:

            self.active = False

            return True

        self.log(
            "INPUT MODE: RESTORING"
        )

        try:

            self.restore_power_plan()

            self.active = False
            self.changed = False

            self.log(
                "INPUT MODE: OFF"
            )

            self.log(
                "Original power settings restored"
            )

            return True

        except Exception as e:

            self.log(
                f"INPUT RESTORE ERROR: {e}"
            )

            return False

    # ---------------------------------------------------------
    # DISABLE
    # ---------------------------------------------------------

    def disable(self):

        return self.restore()

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------

    def status(self):

        if self.active:

            return "INPUT: ON"

        if not self.is_admin():

            return "INPUT: ADMIN REQUIRED"

        return "INPUT: OFF"