"""Unit-kind classification (cavalry split) + sprite-sheet collection.

Read-only: parses the real mods and plans (never applies) a transfer.

    python -m tests.test_kinds_and_sprites
"""
from __future__ import annotations

from pathlib import Path

from unittransfer import edu, transfer
from unittransfer.mod import Mod

MODS = Path(r"C:\Users\projy\Downloads\Games\Total War MEDIEVAL II Definitive Edition\mods")
TATR = MODS / "Third_Age_Reforged"
DAC = MODS / "Divide_and_Conquer_EUR"

ok = fail = 0


def check(cond, label):
    global ok, fail
    if cond:
        ok += 1
        print(f"  ok   {label}")
    else:
        fail += 1
        print(f"  FAIL {label}")


def block(cat, pri, sec):
    return (f"type            Test\ncategory        {cat}\nclass           heavy\n"
            f"stat_pri        {pri}\nstat_sec        {sec}\n")


print("== classification rules ==")
LANCE_SEC = "7, 2, no, 0, 0, melee, melee_blade, slashing, sword, 25, 1"
NONE_SEC = "0, 0, no, 0, 0, no, melee_simple, blunt, none, 25, 1"
MELEE_PRI = "20, 10, no, 0, 0, melee, melee_blade, slashing, sword, 0, 1"
MISSILE_PRI = ("6, 7, elite_horsearcher_arrow, 140, 24, missile, "
               "missile_mechanical, piercing, none, 25, 1")
THROWN_PRI = "7, 3, javelin, 40, 4, thrown, missile_mechanical, piercing, spear, 25, 1"

cases = [
    ("cavalry", MELEE_PRI, NONE_SEC, "Cavalry"),
    ("cavalry", MELEE_PRI, LANCE_SEC, "Cavalry_Lance"),
    ("cavalry", MISSILE_PRI, NONE_SEC, "Cavalry_Archer"),
    ("cavalry", MISSILE_PRI, LANCE_SEC, "Cavalry_Archer"),   # missile wins
    ("cavalry", THROWN_PRI, LANCE_SEC, "Cavalry_Javelin"),   # thrown beats the sidearm->lance
    ("cavalry", THROWN_PRI, NONE_SEC, "Cavalry_Javelin"),
    ("infantry", MELEE_PRI, LANCE_SEC, "Infantry"),          # melee infantry
    ("infantry", MISSILE_PRI, NONE_SEC, "Infantry_Archer"),  # missile infantry
    ("infantry", THROWN_PRI, NONE_SEC, "Infantry_Javelin"),  # javelin infantry
    ("siege", MELEE_PRI, NONE_SEC, "siege"),                 # other categories untouched
]
for cat, pri, sec, want in cases:
    u = edu.parse_text(block(cat, pri, sec)).units[0]
    check(u.kind() == want, f"{cat} pri={pri.split(',')[5].strip()} "
                            f"sec={sec.split(',')[5].strip()} -> {u.kind()} (want {want})")

# a cavalry block with no stat_sec line at all
u = edu.parse_text("type X\ncategory cavalry\nstat_pri " + MELEE_PRI + "\n").units[0]
check(u.kind() == "Cavalry", f"cavalry without any stat_sec line -> {u.kind()}")

print("\n== real mods ==")
for root in (TATR, DAC):
    if not root.exists():
        print(f"  skip {root.name} (not present)")
        continue
    m = Mod(root)
    counts = {}
    for un in m.edu.units:
        counts[un.kind()] = counts.get(un.kind(), 0) + 1
    cav = {k: v for k, v in counts.items() if k.startswith("Cavalry")}
    print(f"  {m.name}: {counts}")
    check("cavalry" not in counts, f"{m.name}: no raw 'cavalry' kind left")
    check(len(cav) >= 2, f"{m.name}: cavalry split into {len(cav)} kinds")
    # spot-check: every Cavalry_Archer really has a missile primary
    bad = [un.type for un in m.edu.units
           if un.kind() == "Cavalry_Archer" and un.stat_pri[5].strip() != "missile"]
    check(not bad, f"{m.name}: all Cavalry_Archer have missile stat_pri")
    bad = [un.type for un in m.edu.units
           if un.kind() == "Cavalry" and len(un.stat_sec) > 5
           and un.stat_sec[5].strip() != "no"]
    check(not bad, f"{m.name}: no plain Cavalry has a secondary weapon")
    # infantry split too: Infantry_Archer <=> missile stat_pri
    check("infantry" not in counts, f"{m.name}: no raw 'infantry' kind left")
    inf = {k: v for k, v in counts.items() if k.startswith("Infantry")}
    check(len(inf) >= 2, f"{m.name}: infantry split into {len(inf)} kinds")
    bad = [un.type for un in m.edu.units
           if un.kind() == "Infantry_Archer" and un.stat_pri[5].strip() != "missile"]
    check(not bad, f"{m.name}: all Infantry_Archer have missile stat_pri")
    bad = [un.type for un in m.edu.units
           if un.kind() == "Infantry" and len(un.stat_pri) > 5
           and un.stat_pri[5].strip() == "missile"]
    check(not bad, f"{m.name}: no plain Infantry has a missile stat_pri")
    # javelin split: every *_Javelin unit has a thrown primary, and no plain
    # Infantry/Cavalry is a thrown unit anymore
    for jk in ("Cavalry_Javelin", "Infantry_Javelin"):
        js = [un for un in m.edu.units if un.kind() == jk]
        check(bool(js), f"{m.name}: has {jk} units ({len(js)})")
        bad = [un.type for un in js
               if not (len(un.stat_pri) > 5 and un.stat_pri[5].strip() == "thrown")]
        check(not bad, f"{m.name}: all {jk} have thrown stat_pri")
    bad = [un.type for un in m.edu.units
           if un.kind() in ("Infantry", "Cavalry") and len(un.stat_pri) > 5
           and un.stat_pri[5].strip() == "thrown"]
    check(not bad, f"{m.name}: no plain Infantry/Cavalry has a thrown stat_pri")

print("\n== sprite sheets ==")
if TATR.exists() and DAC.exists():
    src, dst = Mod(TATR), Mod(DAC)
    # pick a unit whose models reference a .spr that has sheets on disk
    picked = None
    for un in src.edu.units:
        entry = src.modeldb.get(un.soldier_model) if un.soldier_model else None
        if entry is None:
            continue
        sprs = [f for f in entry.texture_files() if f.lower().endswith(".spr")
                and (src.data / f).exists()]
        if sprs and transfer._sprite_sheets(src, sprs[0]):
            picked = (un, sprs[0])
            break
    if picked is None:
        print("  skip (no unit with an on-disk .spr found)")
    else:
        un, spr = picked
        sheets = transfer._sprite_sheets(src, spr)
        print(f"  unit={un.type!r} spr={spr} sheets={len(sheets)}")
        check(all(a.exists() for a, _ in sheets), "all resolved sheets exist on disk")
        check(all(r.endswith(".texture") for _, r in sheets), "sheets are .texture files")
        plan = transfer.plan_transfer(src, un.type, dst)
        rels = {r for _, r in plan.asset_files}
        check(spr in rels, f"plan copies the .spr itself ({spr})")
        missing = [r for _, r in sheets if r not in rels]
        check(not missing, f"plan copies all {len(sheets)} sheet texture(s)"
                           + (f" — missing {missing[:3]}" if missing else ""))
        check(not plan.applied if hasattr(plan, "applied") else True, "plan only (nothing applied)")
else:
    print("  skip (test mods not present)")

print(f"\n{ok} passed, {fail} failed")
raise SystemExit(1 if fail else 0)
