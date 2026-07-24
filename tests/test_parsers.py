"""Stage 1 validation: parse + round-trip the real mods, non-destructively.

Run:  python -m tests.test_parsers
Reads originals only; writes nothing to the mods.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from unittransfer import edu, localization, modeldb  # noqa: E402
from unittransfer.mod import Mod  # noqa: E402

MODS_ROOT = Path(r"C:/Users/projy/Downloads/Games/Total War MEDIEVAL II Definitive Edition/mods")
MODS = ["Third_Age_Reforged", "Divide_and_Conquer_EUR"]


def check(label, cond):
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}")
    return cond


def test_mod(name):
    print(f"\n=== {name} ===")
    m = Mod(MODS_ROOT / name)
    ok = True

    # ---- EDU ----
    ef = m.edu
    raw = m.edu_path.read_text(encoding=edu.ENCODING)
    ok &= check(f"EDU parsed {len(ef.units)} units", len(ef.units) > 100)
    ok &= check("EDU round-trip byte-exact", ef.to_text() == raw)
    sample = ef.units[0]
    ok &= check(f"EDU first unit has type+dictionary ({sample.type!r})",
                bool(sample.type) and bool(sample.dictionary))
    with_models = [u for u in ef.units if u.model_names()]
    ok &= check(f"EDU {len(with_models)} units reference models", len(with_models) > 100)

    # ---- localization ----
    loc = m.loc
    ok &= check(f"loc parsed {len(loc.entries)} keys", len(loc.entries) > 100)
    # every unit dictionary should resolve to a name (spot check coverage)
    matched = sum(1 for u in ef.units if u.dictionary and loc.get(u.dictionary))
    ok &= check(f"loc covers {matched}/{len(ef.units)} unit dictionaries",
                matched > len(ef.units) * 0.5)

    # ---- modeldb ----
    db = m.modeldb
    mtext = m.modeldb_path.read_text(encoding=modeldb.ENCODING)
    ok &= check(f"modeldb parsed {len(db.entries)} models", len(db.entries) > 100)
    ok &= check("modeldb round-trip byte-exact", db.to_text() == mtext)
    ok &= check(f"modeldb has {len(db.all_skeletons())} distinct skeletons",
                len(db.all_skeletons()) > 10)

    # ---- cross links: unit -> model -> skeletons ----
    resolved = 0
    for u in ef.units:
        for mn in u.model_names():
            if db.get(mn):
                resolved += 1
                break
    ok &= check(f"{resolved}/{len(ef.units)} units resolve >=1 model in modeldb",
                resolved > len(ef.units) * 0.5)

    # ---- icons ----
    ok &= check(f"{len(m.icon_factions)} icon faction folders", len(m.icon_factions) > 5)
    found_card = 0
    for u in ef.units[:60]:
        if m.find_unit_card(u):
            found_card += 1
    ok &= check(f"unit cards found for {found_card}/60 sampled units", found_card > 10)

    return ok


if __name__ == "__main__":
    all_ok = True
    for name in MODS:
        try:
            all_ok &= test_mod(name)
        except Exception as e:
            import traceback
            traceback.print_exc()
            all_ok = False
    print("\n" + ("ALL PASSED" if all_ok else "SOME FAILED"))
    sys.exit(0 if all_ok else 1)
