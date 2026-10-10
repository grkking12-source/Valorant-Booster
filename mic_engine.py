"""
VALORANT BOOST - Microphone Engine

External microphone processing using Equalizer APO.

IMPORTANT:
- This does NOT access VALORANT.
- This does NOT access Vanguard.
- This does NOT read game memory.
- This does NOT modify packets.
- It only changes the Windows audio processing configuration.

Your microphone must have Equalizer APO installed/configured
for the microphone/capture device.
"""

import os
import re
from pathlib import Path


MIC_PROFILE = """# VALORANT BOOST - Microphone Profile
# Moderate voice clarity profile

Preamp: -2 dB

# Remove very low rumble
Filter: ON HP Fc 80 Hz

# Reduce muddy/boomy voice
Filter: ON PK Fc 250 Hz Gain -1.5 dB Q 1.00

# Improve voice presence
Filter: ON PK Fc 1500 Hz Gain 1.5 dB Q 0.90

# Improve speech clarity
Filter: ON PK Fc 3000 Hz Gain 2 dB Q 0.90

# Small high-frequency clarity boost
Filter: ON HS Fc 7000 Hz Gain 1 dB Q 0.70
"""


class MicEngine:

    START_MARKER = "# >>> VALORANT_BOOST_MIC_START"
    END_MARKER = "# <<< VALORANT_BOOST_MIC_END"

    def __init__(self, root_dir, log=None):

        self.root = Path(root_dir)

        self.log = log or print

        self.config_dir = self.root / "config"
        self.logs_dir = self.root / "logs"

        self.config_dir.mkdir(
            exist_ok=True
        )

        self.logs_dir.mkdir(
            exist_ok=True
        )

        self.profile_file = (
            self.config_dir
            / "valorant_mic_profile.txt"
        )

        self.backup_file = (
            self.logs_dir
            / "equalizerapo_mic_backup.txt"
        )

        self.active = False

        self.apo_config = (
            self.find_equalizer_apo()
        )

    # ========================================================
    # FIND EQUALIZER APO
    # ========================================================

    def find_equalizer_apo(self):

        locations = [

            Path(
                os.environ.get(
                    "ProgramFiles",
                    r"C:\Program Files"
                )
            )
            / "EqualizerAPO"
            / "config"
            / "config.txt",

            Path(
                os.environ.get(
                    "ProgramFiles(x86)",
                    r"C:\Program Files (x86)"
                )
            )
            / "EqualizerAPO"
            / "config"
            / "config.txt",

        ]

        for path in locations:

            if path.exists():

                return path

        return None

    # ========================================================
    # CHECK
    # ========================================================

    def installed(self):

        self.apo_config = (
            self.find_equalizer_apo()
        )

        return self.apo_config is not None

    # ========================================================
    # CREATE PROFILE
    # ========================================================

    def create_profile(self):

        self.profile_file.write_text(
            MIC_PROFILE,
            encoding="utf-8"
        )

    # ========================================================
    # REMOVE OUR OLD BLOCK
    # ========================================================

    def remove_existing_block(
        self,
        text
    ):

        pattern = (
            re.escape(self.START_MARKER)
            + r".*?"
            + re.escape(self.END_MARKER)
        )

        return re.sub(
            pattern,
            "",
            text,
            flags=re.DOTALL
        ).rstrip()

    # ========================================================
    # ENABLE
    # ========================================================

    def enable(self):

        if self.active:

            return True

        if not self.installed():

            self.log(
                "MIC: Equalizer APO not found."
            )

            return False

        try:

            self.create_profile()

            # ------------------------------------------------
            # BACKUP ORIGINAL CONFIG
            # ------------------------------------------------

            if not self.backup_file.exists():

                original = (
                    self.apo_config.read_text(
                        encoding="utf-8",
                        errors="replace"
                    )
                )

                self.backup_file.write_text(
                    original,
                    encoding="utf-8"
                )

            else:

                original = (
                    self.apo_config.read_text(
                        encoding="utf-8",
                        errors="replace"
                    )
                )

            # ------------------------------------------------
            # REMOVE OLD MIC BLOCK
            # ------------------------------------------------

            clean_config = (
                self.remove_existing_block(
                    original
                )
            )

            # ------------------------------------------------
            # PROFILE PATH
            # ------------------------------------------------

            profile_path = (
                self.profile_file
                .resolve()
                .as_posix()
            )

            # ------------------------------------------------
            # ADD MIC PROFILE
            # ------------------------------------------------

            block = (
                "\n\n"
                f"{self.START_MARKER}\n"
                f"Include: {profile_path}\n"
                f"{self.END_MARKER}\n"
            )

            new_config = (
                clean_config
                + block
            )

            self.apo_config.write_text(
                new_config,
                encoding="utf-8"
            )

            self.active = True

            self.log(
                "MIC MODE: ON"
            )

            self.log(
                "Microphone profile: voice clarity"
            )

            return True

        except PermissionError:

            self.log(
                "MIC ERROR: Administrator permission required."
            )

            return False

        except Exception as e:

            self.log(
                f"MIC ERROR: {e}"
            )

            return False

    # ========================================================
    # DISABLE / RESTORE
    # ========================================================

    def disable(self):

        if not self.installed():

            self.active = False

            return True

        try:

            if self.backup_file.exists():

                original = (
                    self.backup_file.read_text(
                        encoding="utf-8",
                        errors="replace"
                    )
                )

                self.apo_config.write_text(
                    original,
                    encoding="utf-8"
                )

                self.backup_file.unlink(
                    missing_ok=True
                )

            else:

                current = (
                    self.apo_config.read_text(
                        encoding="utf-8",
                        errors="replace"
                    )
                )

                clean = (
                    self.remove_existing_block(
                        current
                    )
                )

                self.apo_config.write_text(
                    clean,
                    encoding="utf-8"
                )

            self.active = False

            self.log(
                "MIC MODE: OFF"
            )

            self.log(
                "Previous microphone configuration restored."
            )

            return True

        except PermissionError:

            self.log(
                "MIC RESTORE ERROR: Administrator permission required."
            )

            return False

        except Exception as e:

            self.log(
                f"MIC RESTORE ERROR: {e}"
            )

            return False

    # ========================================================
    # STATUS
    # ========================================================

    def status(self):

        if self.active:

            return "MIC: ON"

        if not self.installed():

            return "MIC: APO NOT FOUND"

        return "MIC: OFF"