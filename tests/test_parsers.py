"""Stage 1 validation: parse + round-trip the real mods, non-destructively.

Run:  python -m tests.test_parsers
Reads originals only; writes nothing to the mods.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import shutil, tempfile  # noqa: E402
from unittransfer import edu, factions, localization, modeldb  # noqa: E402
from unittransfer import keyblock as kb  # noqa: E402

#: written out rather than escaped, so the file has no literal control bytes
NL_ = chr(13) + chr(10)
MARK = bytes((0xEF, 0xBB, 0xBF))
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


def test_byte_order_mark():
    """A game file re-saved by Notepad keeps every record, and its mark.

    The mark only bites a file whose FIRST line is a record head rather than a
    comment, which is why both installed mods escaped it: DaC's
    descr_sm_factions.txt is the one real file that opens that way, and it lost
    a faction. So the cases here are built rather than borrowed.
    """
    print("\n=== a UTF-8 byte-order mark ===")
    ok = True
    tmp = Path(tempfile.mkdtemp(prefix="ut_bom_"))
    EDU_TXT = (
        "type             Test Unit" + NL_ + "dictionary       Test_Unit" + NL_
        + "category         infantry" + NL_ + "class            light" + NL_
        + "soldier          testman, 8, 0, 1" + NL_ + "ownership        slave" + NL_)
    FAC_TXT = ("faction\tscripts" + NL_ + "culture\tnorthern_european" + NL_
               + "religion\tcatholic" + NL_)
    # Each parser is held to ITS OWN reading contract, which is the honest
    # comparison: factions keeps the file's line endings (keyblock), while EDU
    # and the modeldb read through universal newlines and always have. What is
    # being asserted either way is that the MARK survives the trip.
    same = lambda f, enc: f.read_text(encoding=enc)          # noqa: E731
    exact = lambda f, enc: kb.read_text(f, enc)              # noqa: E731
    cases = [("EDU", EDU_TXT, edu.parse_file,
              lambda o: len(o.units), lambda o: o.to_text(), same),
             ("factions", FAC_TXT, factions.parse_file,
              lambda o: len(o.records), lambda o: o.text(), exact)]
    for label, body, parse, count, totext, reread in cases:
        for tag, head in (("plain", b""), ("with a BOM", MARK)):
            f = tmp / (label + tag.replace(" ", "_") + ".txt")
            f.write_bytes(head + body.encode("latin-1"))
            obj = parse(f)
            ok &= check(f"{label} {tag}: the record is still found",
                        count(obj) == 1)
            ok &= check(f"{label} {tag}: text is the file, mark and all",
                        totext(obj) == reread(f, "latin-1"))
    # the modeldb is the one whose FIRST token is a number, so it crashed
    # outright rather than losing a record quietly
    src = MODS_ROOT / MODS[0] / "data/unit_models/battle_models.modeldb"
    if src.is_file():
        f = tmp / "bom.modeldb"
        f.write_bytes(MARK + src.read_bytes())
        db = modeldb.parse_file(f)
        ok &= check(f"modeldb with a BOM: parses ({len(db.entries)} entries)",
                    len(db.entries) == len(modeldb.parse_file(src).entries))
        ok &= check("modeldb with a BOM: round-trips with the mark intact",
                    db.to_text() == f.read_text(encoding=modeldb.ENCODING))
    shutil.rmtree(tmp, ignore_errors=True)
    return ok


if __name__ == "__main__":
    all_ok = True
    all_ok &= test_byte_order_mark()
    for name in MODS:
        try:
            all_ok &= test_mod(name)
        except Exception as e:
            import traceback
            traceback.print_exc()
            all_ok = False
    print("\n" + ("ALL PASSED" if all_ok else "SOME FAILED"))
    sys.exit(0 if all_ok else 1)
