"""Transfer a unit between mods from the command line (writes a safe overlay).

Usage:
  python transfer_cli.py --from "<mod path>" --to "<mod path>" --unit "Unit Type" --out "<out dir>"
  python transfer_cli.py --from ... --to ... --list                 # list transferable unit types in source
  python transfer_cli.py --from ... --to ... --unit "..." --dry-run  # plan only, write nothing

The output is a patch/overlay: only changed files, with the EDU / export_units /
modeldb written in full (destination + the new entries) so you can drop the
overlay's data/ folder over your destination mod to merge. Real mods are never modified.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from unittransfer.mod import Mod
from unittransfer.transfer import plan_transfer, apply_transfer


def main():
    ap = argparse.ArgumentParser(description="Transfer an M2TW unit between mods (safe overlay).")
    ap.add_argument("--from", dest="src", required=True, help="source mod folder")
    ap.add_argument("--to", dest="dest", required=True, help="destination mod folder")
    ap.add_argument("--unit", help="unit 'type' (display name) to transfer")
    ap.add_argument("--out", help="output overlay dir (default: ./transfers/<unit>)")
    ap.add_argument("--list", action="store_true", help="list source unit types and exit")
    ap.add_argument("--dry-run", action="store_true", help="plan only; write nothing")
    args = ap.parse_args()

    src, dest = Mod(args.src), Mod(args.dest)

    if args.list:
        for u in src.edu.units:
            print(u.type)
        return 0

    if not args.unit:
        ap.error("--unit is required (or use --list)")

    plan = plan_transfer(src, args.unit, dest)
    print(plan.summary())

    if args.dry_run:
        print("\n(dry run - nothing written)")
        return 0

    out = Path(args.out) if args.out else Path("transfers") / _safe(args.unit)
    res = apply_transfer(plan, out)
    print()
    print(res.report())
    print("\nMerge: copy the overlay's data/ folder over your destination mod.")
    return 0


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)


if __name__ == "__main__":
    raise SystemExit(main())
