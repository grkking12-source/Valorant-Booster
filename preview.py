"""Safe preview / test runner.  python preview.py            -> shows what WOULD be stopped (changes nothing)
                              python preview.py --apply    -> stops approved apps (asks YES first)
                              python preview.py --restore  -> restores everything saved"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from engine import valorant_detector as vd  # noqa: E402
from engine.rollback import RollbackJournal  # noqa: E402
from process_manager import manager as pm  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--restore", action="store_true")
    a = ap.parse_args()
    journal = RollbackJournal(os.path.join(ROOT, "logs", "rollback.db"))

    if a.restore:
        res = journal.revert_all()
        for _, kind, target, ok, msg in res:
            print(f"{'OK  ' if ok else 'FAIL'} {kind}: {target} - {msg}")
        print("Nothing to restore." if not res else "Restore finished.")
        return

    cfg = pm.load_config(os.path.join(ROOT, "config", "safe_list.json"))
    pend = journal.pending()
    print("=" * 40)
    print("VALORANT:", "RUNNING" if vd.game_pids() else "NOT RUNNING", "| Vanguard:", vd.vanguard_status())
    if pend:
        print(f"WARNING: {len(pend)} saved change(s) are pending. Run: python preview.py --restore")
    plan = pm.build_plan(cfg)
    print("\nWOULD STOP (approved in safe_list.json):")
    for e in plan["stop"] or []:
        print(f"  - {e['name']} (pid {e['pid']}, {e['ram_mb']} MB)")
    for s in plan["services"]:
        print(f"  - service {s['name']} ({'running' if s['running'] else 'not running'})")
    if not plan["stop"] and not any(s["running"] for s in plan["services"]):
        print("  (nothing approved is running)")
    for n, why in plan["refused"].items():
        print(f"  REFUSED {n}: {why}")
    print("\nLEFT ALONE (largest):", ", ".join(f"{x['name']} {x['ram_mb']}MB" for x in plan["keeping"]))
    if a.apply:
        if pend:
            print("\nRefusing to apply: restore the pending changes first (--restore).")
            return
        if input("\nType YES to stop the apps listed above: ").strip() != "YES":
            print("Cancelled.")
            return
        for label, outcome in pm.apply_plan(journal, plan):
            print(f"  {label}: {outcome}")
        print("\nRestore any time with: python preview.py --restore")
    else:
        print("\n(dry run - nothing changed)")


if __name__ == "__main__":
    main()
