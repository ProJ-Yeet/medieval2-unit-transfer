"""M2TWEOP units + the Lua safety net.

Two features that share one idea: a mod holds more than its ``data/*.txt`` files
say. Runs on throwaway copies of a real mod's text files, with an ``eopData``
folder and a ``.lua`` script planted in them, so nothing real is touched.

Covers:
  * **Lua protection** — an entry only a ``.lua`` script names is never called
    unused, is never offered as a merge source, and ``plan_cleanup`` refuses to
    remove it even when it is asked to outright. Comments count too.
  * **EOP units** — files under the mod's EOP folder are parsed into the roster,
    flagged, and kept OUT of ``export_descr_unit.txt``; a file that is not unit
    blocks is ignored; the folder can be auto-detected or configured.
  * **EOP writes** — editing an EOP unit rewrites its own file and leaves the EDU
    byte-identical; deleting one removes its file; a voice edit and a bmdb soldier
    merge both follow it there; and undo puts all of it back byte-exact.
  * **EOP transfers** — a unit transferred as an EOP unit lands in its own file,
    the EDU is untouched, and it does not count against the 500-unit cap.
"""
import shutil, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import bmdb as bmdb_mod
from unittransfer import config, edit, eop, luascan, sounds
from unittransfer.mod import Mod
from unittransfer.transfer import (TransferOptions, apply_transfer, plan_transfer,
                                   undo)

MODS = Path(r"C:/Users/projy/Downloads/Games/Total War MEDIEVAL II Definitive Edition/mods")
SRC = next((MODS / n for n in ("third_age_3", "Third_Age_6", "Divide_and_Conquer_EUR",
                               "Third_Age_Reforged")
            if (MODS / n / "data" / "export_descr_unit.txt").is_file()), None)

ok = []
def check(label, cond):
    ok.append(bool(cond)); print(f"  [{'OK ' if cond else 'FAIL'}] {label}")


def fresh_mod(prefix="ut_eop_") -> Path:
    """A copy of the mod's text files only — enough for every path under test."""
    root = Path(tempfile.mkdtemp(prefix=prefix))
    data = root / "data"
    (data / "text").mkdir(parents=True)
    (data / "unit_models").mkdir(parents=True)
    for rel in ("export_descr_unit.txt", "text/export_units.txt",
                "unit_models/battle_models.modeldb", "descr_mount.txt",
                "descr_character.txt",
                "export_descr_sounds_units_voice.txt"):
        src = SRC / "data" / rel
        if src.exists():
            shutil.copy2(src, data / rel)
    return root


cfg = Path(tempfile.mkdtemp(prefix="ut_cfg_"))
config.CONFIG_DIR = cfg; config.BACKUP_DIR = cfg / "backups"
config.SETTINGS_PATH = cfg / "settings.json"; config.LOG_PATH = cfg / "transfers.json"

if SRC is None:
    print("No source mod available under", MODS)
    sys.exit(1)
print(f"source mod: {SRC.name}")


# ---------------------------------------------------------------------------
print("\n== the Lua scanner ==")
lroot = fresh_mod("ut_lua_")
# Three entries the tool ITSELF proves are removable before any Lua exists: one
# gets named by a live line, one only inside a comment, one is never named at all
# and stays the control. Taking them from the audit's own unused list is what
# makes the later "not offered any more" checks mean something.
baseline = bmdb_mod.audit(Mod(lroot), scan_orphans=False)
spare = [u["entry"] for u in baseline["unused"]]
check(f"{len(spare)} entries nothing in the mod references (need 3)", len(spare) >= 3)
live_name, commented_name, control_name = spare[0], spare[1], spare[2]

(lroot / "eopData").mkdir(parents=True, exist_ok=True)
(lroot / "eopData" / "spawner.lua").write_text(
    "-- M2TWEOP unit spawner\n"
    "local M = {}\n"
    f'function M.spawn(g) g:setModel("{live_name}") end\n'
    f'-- TODO next patch: M.spawn2 uses "{commented_name}"\n'
    f'local unrelated = "{control_name}_variant_b"\n'
    "return M\n", encoding="utf-8")

hits = luascan.scan(Mod(lroot))
check("the live reference is found", live_name in hits and not hits[live_name].in_comment)
check("the commented reference is found and marked as a comment",
      commented_name in hits and hits[commented_name].in_comment)
check("the hit names the script and a line number",
      hits[live_name].file == "eopData/spawner.lua" and hits[live_name].line == 3)
check("a name that is only the PREFIX of one in the script is not a hit",
      control_name not in hits)

print("\n== the audit never offers a Lua-named entry ==")
lmod = Mod(lroot)
a = bmdb_mod.audit(lmod, scan_orphans=False)
unused = {u["entry"] for u in a["unused"]}
check("the live-referenced entry is not on the unused list", live_name not in unused)
check("the commented-referenced entry is not on the unused list either",
      commented_name not in unused)
check("the control entry — named nowhere — IS still offered as unused",
      control_name in unused)
check(f"the audit reports {a['lua_files']} lua file(s) scanned", a["lua_files"] == 1)
kept = {m["entry"]: m for m in a["lua_kept"]}
check("both are reported as kept by Lua", live_name in kept and commented_name in kept)
check("the commented one says so", kept[commented_name]["in_comment"] is True)
check("neither is offered as a merge source",
      not ({c["entry"] for c in a["merges"]} & {live_name, commented_name}))
check("nor as a merge target",
      not any(c["into"] in (live_name, commented_name) for c in a["merges"]))

print("\n== plan_cleanup refuses to remove one even when asked ==")
before_db = lmod.modeldb_path.read_bytes()
plan = bmdb_mod.plan_cleanup(lmod, bmdb_mod.CleanupRequest(
    target=str(Path(tempfile.mkdtemp(prefix="ut_exp_"))),
    entries=[live_name, commented_name]))
check("neither entry is in the delete list",
      not (set(plan.entry_deletes) & {live_name, commented_name}))
check("the warning names the script, not just 'still used'",
      any("spawner.lua" in w for w in plan.warnings))
check("the warning explains why (M2TWEOP names models by string)",
      any("M2TWEOP" in w for w in plan.warnings))
check("nothing is exported for them", not plan.exports)
res = bmdb_mod.apply_cleanup(plan)
check("the modeldb is byte-identical after applying that cleanup",
      lmod.modeldb_path.read_bytes() == before_db)
undo(res["id"])


# ---------------------------------------------------------------------------
print("\n== EOP units are read into the roster ==")
eroot = fresh_mod()
base = Mod(eroot)
donor = next(u for u in base.edu.units if u.soldier_model and u.dictionary)
edu_bytes = base.edu_path.read_bytes()
edu_text_before = base.edu.to_text()
edu_count = len(base.edu.units)

eopdir = eroot / "eopData" / "units"
eopdir.mkdir(parents=True)
block = donor.raw.replace(f"type {donor.type}", "type eop_test_guard", 1) \
    if f"type {donor.type}" in donor.raw else donor.raw
# rebuild the block properly rather than by string luck
from unittransfer import edu as edu_mod
block = edu_mod.rewrite_block(edu_mod.strip_trailing_filler(donor.raw),
                              type_new="eop_test_guard",
                              dict_new=donor.dictionary)
(eopdir / "eop_test_guard.txt").write_text("; M2TWEOP unit\n" + block,
                                           encoding=edu_mod.ENCODING)
# a file in the same folder that is NOT unit blocks — must be ignored
(eopdir / "notes.txt").write_text("just some notes about the type of thing\n",
                                  encoding="utf-8")

m = Mod(eroot)
check("the EOP folder is auto-detected", [p.name for p in m.eop_dirs] == ["eopData"])
check("only the real unit file is read",
      [p.name for p in eop.unit_files(m)] == ["eop_test_guard.txt"])
check(f"the roster grew by one ({edu_count} -> {len(m.edu.units)})",
      len(m.edu.units) == edu_count + 1)
guard = m.edu.by_type().get("eop_test_guard")
check("the new unit is in the roster", guard is not None)
check("it is flagged as an EOP unit", guard is not None and guard.is_eop)
check("it knows its own file",
      guard is not None and Path(guard.eop_file).name == "eop_test_guard.txt")
check("main_units excludes it", len(m.edu.main_units) == edu_count)
check("eop_units is exactly it", [u.type for u in m.edu.eop_units] == ["eop_test_guard"])
check("to_text() still produces exactly the original EDU text",
      m.edu.to_text() == edu_text_before)

print("\n== editing an EOP unit writes its own file, not the EDU ==")
p = edit.plan_edit(m, edit.EditRequest(
    unit="eop_test_guard", field_overrides={"stat_health": "9, 0"}))
check("the EDU is not rewritten", p.edu_text == "")
check("exactly one EOP file is rewritten", len(p.eop_texts) == 1)
check("it is the unit's own file",
      Path(next(iter(p.eop_texts))).name == "eop_test_guard.txt")
rec = edit.apply_edit(p)
check("export_descr_unit.txt is byte-identical after the save",
      (eroot / "data" / "export_descr_unit.txt").read_bytes() == edu_bytes)
check("the EOP file really changed",
      "stat_health" in (eopdir / "eop_test_guard.txt").read_text(encoding=edu_mod.ENCODING)
      and "9, 0" in (eopdir / "eop_test_guard.txt").read_text(encoding=edu_mod.ENCODING))
after_edit = (eopdir / "eop_test_guard.txt").read_bytes()
undo(rec["id"])
check("undo restores the EOP file byte-exact",
      (eopdir / "eop_test_guard.txt").read_bytes() != after_edit
      and "eop_test_guard" in (eopdir / "eop_test_guard.txt").read_text(
          encoding=edu_mod.ENCODING))

print("\n== a voice edit follows the unit into its own file ==")
m = Mod(eroot)
guard_voice = sounds.unit_voice_fields(m.edu.by_type()["eop_test_guard"])
# The donor must sit in a DIFFERENT accent/class block, or the EDU-side edit is a
# no-op and the test would pass without proving anything about where it is written.
src_voice = next((e for e in m.sounds.unit_entries()
                  if (e.accent, e.voice_class) != guard_voice), None)
if m.eds_path.exists() and src_voice is not None:
    sp = sounds.plan_sounds(m, [sounds.SoundOp(
        unit="eop_test_guard", accent=src_voice.accent,
        voice_class=src_voice.voice_class, donor=src_voice.name)])
    check("the voice plan has no errors", not sp.errors)
    check("the voice edit does not rewrite the EDU", sp.edu_text == "")
    check("it rewrites the unit's EOP file instead", len(sp.eop_texts) == 1)
    check("and that file is the unit's own",
          not sp.eop_texts or Path(next(iter(sp.eop_texts))).name == "eop_test_guard.txt")
else:
    print("  [skip] this mod ships no voice bank")

print("\n== deleting an EOP unit removes its file ==")
m = Mod(eroot)
p = edit.plan_edit(m, edit.EditRequest(unit="eop_test_guard", delete=True))
check("the EDU is not rewritten by the delete", p.edu_text == "")
check("its file is marked for removal",
      len(p.eop_removes) == 1 and Path(p.eop_removes[0]).name == "eop_test_guard.txt")
rec = edit.apply_edit(p)
check("the file is gone", not (eopdir / "eop_test_guard.txt").exists())
check("export_descr_unit.txt is still byte-identical",
      (eroot / "data" / "export_descr_unit.txt").read_bytes() == edu_bytes)
undo(rec["id"])
check("undo brings the deleted unit file back",
      (eopdir / "eop_test_guard.txt").is_file()
      and "eop_test_guard" in (eopdir / "eop_test_guard.txt").read_text(
          encoding=edu_mod.ENCODING))


print("\n== a bmdb soldier merge follows an EOP unit into its own file ==")
# A merge repoints a `soldier` line. When the unit owning that line is an EOP
# unit, the rewrite belongs in its file — writing it into the EDU would both miss
# the unit and leave the merged entry named by a model that is no longer there.
mroot = fresh_mod("ut_merge_")
mm = Mod(mroot)
groups = {}
for e in mm.modeldb.entries:
    groups.setdefault(bmdb_mod.footer_key(e), []).append(e.name)
free = {u["entry"] for u in bmdb_mod.audit(mm, scan_orphans=False)["unused"]}
pair = next(((a, b) for names in groups.values() if len(names) >= 2
             for a in names if a in free
             for b in names if b != a), None)
if pair is None:
    print("  [skip] this mod has no footer-twin pair with a free member")
else:
    A, B = pair
    mdonor = next(u for u in mm.edu.units if u.soldier_model)
    mblock = edu_mod.set_model_slot(
        edu_mod.rewrite_block(edu_mod.strip_trailing_filler(mdonor.raw),
                              type_new="eop_merge_test"), "soldier", A)
    mdir = mroot / "eopData"
    mdir.mkdir(parents=True, exist_ok=True)
    (mdir / "eop_merge_test.txt").write_text(mblock, encoding=edu_mod.ENCODING)
    mm = Mod(mroot)
    m_edu_bytes = mm.edu_path.read_bytes()
    check(f"the EOP unit's soldier line names '{A}'",
          mm.edu.by_type()["eop_merge_test"].soldier_model.lower() == A)
    mp = bmdb_mod.plan_cleanup(mm, bmdb_mod.CleanupRequest(
        target=str(Path(tempfile.mkdtemp(prefix="ut_exp2_"))),
        merges=[{"entry": A, "into": B}]))
    check("the merge is planned", not mp.errors and (A, B) in mp.merges)
    check("the EDU is NOT rewritten for it", mp.edu_text == "")
    check("the EOP unit's own file is rewritten instead",
          len(mp.eop_texts) == 1
          and Path(next(iter(mp.eop_texts))).name == "eop_merge_test.txt")
    mrec = bmdb_mod.apply_cleanup(mp)
    check("export_descr_unit.txt is byte-identical after the merge",
          mm.edu_path.read_bytes() == m_edu_bytes)
    check("the EOP unit now names the twin",
          Mod(mroot).edu.by_type()["eop_merge_test"].soldier_model.lower() == B)
    check("the merged entry is gone from the modeldb",
          A not in Mod(mroot).modeldb.by_name())
    undo(mrec["id"])
    check("undo puts the EOP unit's soldier line back",
          Mod(mroot).edu.by_type()["eop_merge_test"].soldier_model.lower() == A)


# ---------------------------------------------------------------------------
print("\n== transferring a unit AS an EOP unit ==")
droot = fresh_mod("ut_eop_dst_")
(droot / "eopData").mkdir()
dest = Mod(droot)
dest_edu_bytes = dest.edu_path.read_bytes()
dest_main = len(dest.edu.main_units)
src = Mod(SRC)
# The destination is a copy of the same mod, so every type collides — rename is
# the realistic shape of this transfer anyway (that is what the composer does).
pick = next(u for u in src.edu.units if u.soldier_model)
NEW_TYPE = "eop_xfer_test"
tp = plan_transfer(src, pick.type, dest, TransferOptions(
    eop_target="eop", on_conflict="rename", new_type=NEW_TYPE,
    new_dictionary="eop_xfer_test"))
check(f"'{pick.type}' is bound for an EOP file", bool(tp.eop_file))
check("it does not count towards the 500-unit cap", tp.dest_new_units == 0)
check("the summary says where it goes", "M2TWEOP UNIT" in tp.summary())
rec = apply_transfer(tp)
check("export_descr_unit.txt is byte-identical after the transfer",
      (droot / "data" / "export_descr_unit.txt").read_bytes() == dest_edu_bytes)
newfile = Path(tp.eop_file)
check("the unit's own file was written", newfile.is_file())
after = Mod(droot)
got = after.edu.by_type().get(NEW_TYPE)
check("it reads back as a unit of the destination", got is not None)
check("and reads back flagged as EOP", got is not None and got.is_eop)
check("the EDU unit count is unchanged", len(after.edu.main_units) == dest_main)
undo(rec["id"])
check("undo removes the created EOP file", not newfile.exists())

print("\n== with no EOP folder, the unit falls back to the EDU with a warning ==")
nroot = fresh_mod("ut_noeop_")
nodest = Mod(nroot)
tp2 = plan_transfer(src, pick.type, nodest, TransferOptions(
    eop_target="eop", on_conflict="rename", new_type=NEW_TYPE,
    new_dictionary="eop_xfer_test"))
check("no EOP file is chosen", tp2.eop_file == "")
check("it counts against the cap again", tp2.dest_new_units == 1)
check("the warning says how to fix it",
      any("EOP folder" in w for w in tp2.warnings))

print("\n== a configured folder overrides detection ==")
custom = eroot / "MyEopUnits"
custom.mkdir()
mm = Mod(eroot)
eop.set_configured_dirs(mm, [str(custom)])
mm2 = Mod(eroot)
check("the configured folder is the only one used",
      [str(p) for p in mm2.eop_dirs] == [str(custom)])
check("so the auto-detected units are no longer read", len(mm2.edu.eop_units) == 0)
eop.set_configured_dirs(mm2, [])
check("clearing it goes back to detection",
      [p.name for p in Mod(eroot).eop_dirs] == ["eopData"])


print(f"\n{sum(ok)}/{len(ok)} checks — {'ALL PASSED' if all(ok) else 'SOME FAILED'}")
sys.exit(0 if all(ok) else 1)
