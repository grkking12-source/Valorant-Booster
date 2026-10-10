"""Gaming Mode runner.
  python run.py        -> waits for VALORANT; stops approved apps when it starts, restores when it closes.
                          Press Ctrl+C to quit (everything is restored first).
  python run.py --now  -> test mode: enables immediately, waits for Enter, then restores.
"""
import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from engine import valorant_detector as vd  # noqa: E402
from engine.gaming_mode import GamingMode  # noqa: E402
from engine.rollback import RollbackJournal  # noqa: E402
from process_manager import manager as pm  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--now", action="store_true")
    a = ap.parse_args()

    journal = RollbackJournal(os.path.join(ROOT, "logs", "rollback.db"))
    cfg = pm.load_config(os.path.join(ROOT, "config", "safe_list.json"))
    left = journal.recover_on_startup()
    if left:
        print("Restored leftovers from a previous session:")
        for _, kind, target, ok, msg in left:
            print(f"  {'OK  ' if ok else 'FAIL'} {target}: {msg}")

    gm = GamingMode(lambda: pm.build_plan(cfg), lambda plan: pm.apply_plan(journal, plan),
                    journal.revert_all)

    if a.now:
        print("GAMING MODE ON (test)")
        gm.enable()
        input("\nPress Enter to restore everything... ")
        print("RESTORING")
        gm.disable()
        return

    def on_start():
        print("\nVALORANT detected -> GAMING MODE ON")
        gm.enable()

    def on_stop():
        print("\nVALORANT closed -> RESTORING")
        time.sleep(3)  # let the game finish exiting
        gm.disable()

    print("Waiting for VALORANT... (Ctrl+C to quit)")
    try:
        vd.watch(on_start, on_stop)
    except KeyboardInterrupt:
        pass
    finally:
        if gm.active or journal.pending():
            print("\nQuitting -> restoring everything")
            gm.disable()


if __name__ == "__main__":
    main()
