"""
VALORANT BOOST - Audio Engine

Uses Equalizer APO for external Windows audio EQ.
Does NOT access VALORANT, Vanguard, memory, packets, or game state.

Requires:
    Equalizer APO installed and configured for your headset.
"""

import os
from pathlib import Path


PROFILE = """# VALORANT BOOST - Audio Profile
# Moderate competitive clarity profile

Preamp: -2 dB

# Reduce low-end boom/rumble
Filter: ON LS Fc 90 Hz Gain -3 dB Q 0.70

# Reduce low-mid masking
Filter: ON PK Fc 220 Hz Gain -1 dB Q 1.00

# Improve detail
Filter: ON PK Fc 1800 Hz Gain 1.5 dB Q 0.90

# Footstep/detail region
Filter: ON PK Fc 3500 Hz Gain 2 dB Q 0.90

# Small treble lift
Filter: ON HS Fc 6500 Hz Gain 1.5 dB Q 0.70
"""


class AudioEngine:

    MARKER = "# VALORANT_BOOST_AUDIO"

    def __init__(self, root_dir, log=None):
        self.root = Path(root_dir)
        self.log = log or print

        self.config_dir = self.root / "config"
        self.logs_dir = self.root / "logs"

        self.config_dir.mkdir(exist_ok=True)
        self.logs_dir.mkdir(exist_ok=True)

        self.profile_file = (
            self.config_dir / "valorant_audio_profile.txt"
        )

        self.backup_file = (
            self.logs_dir / "equalizerapo_backup.txt"
        )

        self.active = False

        self.apo_config = self.find_equalizer_apo()

    # ---------------------------------------------------------
    # FIND EQUALIZER APO
    # ---------------------------------------------------------

    def find_equalizer_apo(self):

        locations = [
            Path(os.environ.get(
                "ProgramFiles",
                r"C:\Program Files"
            )) / "EqualizerAPO" / "config" / "config.txt",

            Path(os.environ.get(
                "ProgramFiles(x86)",
                r"C:\Program Files (x86)"
            )) / "EqualizerAPO" / "config" / "config.txt",
        ]

        for path in locations:
            if path.exists():
                return path

        return None

    # ---------------------------------------------------------
    # CHECK INSTALLATION
    # ---------------------------------------------------------

    def installed(self):

        self.apo_config = self.find_equalizer_apo()

        return self.apo_config is not None

    # ---------------------------------------------------------
    # CREATE PROFILE
    # ---------------------------------------------------------

    def create_profile(self):

        self.profile_file.write_text(
            PROFILE,
            encoding="utf-8"
        )

    # ---------------------------------------------------------
    # ENABLE
    # ---------------------------------------------------------

    def enable(self):

        if self.active:
            return True

        if not self.installed():

            self.log(
                "SOUND: Equalizer APO not found."
            )

            return False

        try:

            self.create_profile()

            # Save the ORIGINAL Equalizer APO configuration.
            original = self.apo_config.read_text(
                encoding="utf-8",
                errors="replace"
            )

            self.backup_file.write_text(
                original,
                encoding="utf-8"
            )

            # Remove an old VALORANT BOOST entry
            # if one somehow remains.
            lines = []

            for line in original.splitlines():

                if self.MARKER not in line:

                    lines.append(line)

                elif line.strip().startswith(
                    "Include:"
                ):
                    continue

            clean_config = "\n".join(lines).rstrip()

            profile_path = (
                self.profile_file
                .resolve()
                .as_posix()
            )

            addition = (
                f"\n\n{self.MARKER}\n"
                f"Include: {profile_path}\n"
            )

            new_config = clean_config + addition

            self.apo_config.write_text(
                new_config,
                encoding="utf-8"
            )

            self.active = True

            self.log(
                "SOUND MODE ON"
            )

            self.log(
                "Audio profile: clarity mode"
            )

            return True

        except PermissionError:

            self.log(
                "SOUND ERROR: Administrator permission required."
            )

            return False

        except Exception as e:

            self.log(
                f"SOUND ERROR: {e}"
            )

            return False

    # ---------------------------------------------------------
    # DISABLE / RESTORE
    # ---------------------------------------------------------

    def disable(self):

        if not self.installed():

            self.active = False

            return True

        try:

            # Restore the EXACT configuration
            # that existed before Sound Mode.
            if self.backup_file.exists():

                original = self.backup_file.read_text(
                    encoding="utf-8",
                    errors="replace"
                )

                self.apo_config.write_text(
                    original,
                    encoding="utf-8"
                )

                self.backup_file.unlink(
                    missing_ok=True
                )

            self.active = False

            self.log(
                "SOUND MODE OFF"
            )

            self.log(
                "Previous audio configuration restored."
            )

            return True

        except PermissionError:

            self.log(
                "SOUND RESTORE ERROR: Administrator permission required."
            )

            return False

        except Exception as e:

            self.log(
                f"SOUND RESTORE ERROR: {e}"
            )

            return False

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------

    def status(self):

        if self.active:
            return "SOUND: ON"

        if not self.installed():
            return "SOUND: APO NOT FOUND"

        return "SOUND: OFF"