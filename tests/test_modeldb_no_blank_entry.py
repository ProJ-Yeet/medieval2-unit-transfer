"""Vanilla M2TW quirk: when a modeldb has no leading ``blank`` sentinel entry,
the game pads the very first real entry with 8 extra reserved int-pairs
threaded through the body. Confirmed against the reference C# ModdingTool's
``FirstEntryPad`` calls (``Model/Databases/BattleModelDb.cs``) and against a
real file (Third Age Total War 3's battle_models.modeldb, 1764 entries, no
blank sentinel) that used to crash with
``ValueError: invalid literal for int() with base 10: '<a texture path>'``.

    python -m tests.test_modeldb_no_blank_entry
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import modeldb

ok = []


def check(label, cond):
    ok.append(bool(cond))
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}")


def padded_entry(name, tex):
    """The first real entry in a blank-less modeldb: 1 LOD, 1 main texture,
    0 attach, 1 anim -- with the 8 vanilla padding int-pairs (P) inserted."""
    P = "0 0 "
    return (
        f"\n{len(name)} {name} \n1.0 {P}"
        f"\n1 {P}"
        f"\n{len('m/' + name + '.mesh')} m/{name}.mesh 121 {P}"
        f"\n1 {P}\n4 ever \n{len(tex)} {tex} \n{len(tex)} {tex} \n0 "
        f"\n0 "                      # attach count -- no padding around this one
        f"{P}\n1 {P}"
        f"\n5 horse \n3 pri \n3 sec \n0 \n0 {P}"
        f"\n-1 0.0 0.0 0.0 0.0 0.0 0.0 {P}"
    )


def one_entry(name, tex):
    """A normal (unpadded) entry, as in test_modeldb_header.py."""
    return (
        f"\n{len(name)} {name} \n1.0 \n1 "
        f"\n{len('m/' + name + '.mesh')} m/{name}.mesh 121 "
        f"\n1 \n4 ever \n{len(tex)} {tex} \n{len(tex)} {tex} \n0 "
        f"\n0 "
        f"\n1 \n5 horse \n3 pri \n3 sec \n0 \n0 "
        f"\n-1 0.0 0.0 0.0 0.0 0.0 0.0 "
    )


BODY = padded_entry("mount_pony", "unit_models/mounts/pony.texture") \
     + one_entry("mount_cob", "unit_models/mounts/cob.texture")
# 2 entries, NO blank sentinel -- header count is the real entry count.
TEXT = "22 serialization::archive 3 0 0 0 0 2 0 0" + BODY

print("== parses without a blank sentinel ==")
db = modeldb.parse_text(TEXT)
check("2 entries parsed", len(db.entries) == 2)
check("no blank_raw captured", db.blank_raw == "")
check("names intact", [e.name for e in db.entries] == ["mount_pony", "mount_cob"])
check("first entry flagged first_entry_pad", db.entries[0].first_entry_pad is True)
check("second entry NOT flagged", db.entries[1].first_entry_pad is False)
check("first entry's mesh/texture paths survived the padding",
      db.entries[0].mesh_files() == ["m/mount_pony.mesh"])
check("first entry's texture paths survived the padding",
      db.entries[0].texture_files() == ["unit_models/mounts/pony.texture"])
check("second entry unaffected",
      db.entries[1].texture_files() == ["unit_models/mounts/cob.texture"])
check("round-trips byte-exact", db.to_text() == TEXT)
check("header count == entries (no +1, since there's no blank entry)",
      db.header_ints[5] == 2 and len(db.entries) == 2)

print("\n== reroute / faction-texture helpers stay pad-aware on the first entry ==")
raw = db.entries[0].raw
rerouted = modeldb.rewrite_entry_paths(
    raw, {"unit_models/mounts/pony.texture": "unit_models/moved/pony.texture"},
    pad=db.entries[0].first_entry_pad)
db2 = modeldb.parse_text(TEXT[:TEXT.index(raw)] + rerouted + TEXT[TEXT.index(raw) + len(raw):])
check("rewrite_entry_paths relocates the texture on a padded entry",
      db2.entries[0].texture_files() == ["unit_models/moved/pony.texture"])
check("rewrite_entry_paths leaves the mesh path untouched",
      db2.entries[0].mesh_files() == ["m/mount_pony.mesh"])

added = modeldb.add_texture_factions(raw, ["mongols"], pad=db.entries[0].first_entry_pad)
db3 = modeldb.parse_text(TEXT[:TEXT.index(raw)] + added + TEXT[TEXT.index(raw) + len(raw):],)
check("add_texture_factions adds the new faction on a padded entry",
      "mongols" in db3.entries[0].factions())
check("add_texture_factions keeps the original faction",
      "ever" in db3.entries[0].factions())

print("\n== the real Third Age Total War 3 file, if present ==")
sample = Path(r"C:\Users\projy\Downloads\Games\Total War MEDIEVAL II Definitive Edition"
              r"\mods\third_age_3\data\unit_models\battle_models.modeldb")
if sample.is_file():
    text = sample.read_text(encoding=modeldb.ENCODING)
    real = modeldb.parse_text(text)
    check(f"parses ({len(real.entries)} entries)", len(real.entries) > 0)
    check("no blank sentinel in this file", real.blank_raw == "")
    check("first entry is padded", real.entries[0].first_entry_pad is True)
    check("later entries are not padded", real.entries[1].first_entry_pad is False)
    check("round-trips byte-exact", real.to_text() == text)
else:
    print("  (skipped -- sample file not on this machine)")

print(f"\n{sum(ok)}/{len(ok)} checks — " + ("ALL PASSED" if all(ok) else "SOME FAILED"))
sys.exit(0 if all(ok) else 1)
