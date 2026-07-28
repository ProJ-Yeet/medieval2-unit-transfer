"""BMDB mode — the whole battle_models.modeldb, not one unit's slice of it.

Runs on a throwaway copy of Third_Age_Reforged's data files, so the real mods are
never touched. Covers:
  * the audit: what nothing references, what only a `soldier` line names, and
    which files under unit_models no entry mentions at all
  * the safety nets: an entry named in a descr_*.txt is never called unused, and
    the padded first entry of a sentinel-less modeldb is never removed
  * cleanup: entries dropped, their files exported mirroring the mod's layout,
    files a surviving entry still uses left alone, and a standalone modeldb of
    exactly the removed entries that parses back
  * accepted soldier merges rewrite the EDU's soldier line and free the entry
  * mod-wide entry editing (plan_bmdb): a rename chases every unit in the EDU
  * undo restores the mod byte-exact
"""
import shutil, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import config, edit, modeldb
from unittransfer import bmdb as bmdb_mod
from unittransfer.mod import Mod
from unittransfer.transfer import undo

MODS = Path(r"C:/Users/projy/Downloads/Games/Total War MEDIEVAL II Definitive Edition/mods")
TATR = MODS / "Third_Age_Reforged"

ok = []
def check(label, cond):
    ok.append(bool(cond)); print(f"  [{'OK ' if cond else 'FAIL'}] {label}")


def fresh_mod(with_assets=()) -> Path:
    """A copy of the mod's text files, plus any asset files the test needs."""
    root = Path(tempfile.mkdtemp(prefix="ut_bmdb_"))
    data = root / "data"
    (data / "text").mkdir(parents=True)
    (data / "unit_models").mkdir(parents=True)
    for rel in ("export_descr_unit.txt", "text/export_units.txt",
                "unit_models/battle_models.modeldb", "descr_mount.txt",
                "descr_character.txt"):
        src = TATR / "data" / rel
        if src.exists():
            shutil.copy2(src, data / rel)
    for rel in with_assets:
        src, dst = TATR / "data" / rel, data / rel
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    return root


cfg = Path(tempfile.mkdtemp(prefix="ut_cfg_"))
config.CONFIG_DIR = cfg; config.BACKUP_DIR = cfg / "backups"
config.SETTINGS_PATH = cfg / "settings.json"; config.LOG_PATH = cfg / "transfers.json"

root = fresh_mod()
mod = Mod(root)
before_db = mod.modeldb_path.read_bytes()
before_edu = mod.edu_path.read_bytes()

print("\n== audit ==")
a = bmdb_mod.audit(mod)
unused = {u["entry"] for u in a["unused"]}
check(f"{a['entry_count']} entries scanned", a["entry_count"] > 500)
check(f"{len(unused)} entries nothing references", len(unused) > 0)
check("every unused entry really is unreferenced by the EDU",
      not (unused & {m for u in mod.edu.units for m in u.model_names()}))
check("every unused entry really is unreferenced by descr_mount.txt",
      not (unused & set((mod.mounts or {}).values())))
check("descr_character.txt battle_models are never called unused",
      not (unused & set(bmdb_mod._character_models(mod))))
mentioned = {m["entry"] for m in a["mentioned"]}
check(f"{len(mentioned)} entries held back because a descr_*.txt names them",
      bool(mentioned) and not (mentioned & unused))
check(f"{len(a['merges'])} soldier-only merge candidates", len(a["merges"]) > 0)

print("\n== merge candidates ==")
for c in a["merges"][:3]:
    print(f"     {c['entry']} -> {c['into']}  (units: {', '.join(c['units'][:3])})")
entries = mod.modeldb.by_name()
check("every candidate is named ONLY by soldier lines",
      all(not any(u.type in c["units"] and (c["entry"] in [x.lower() for x in u.armour_ug_models]
                                            or c["entry"] in [x.lower() for x in u.officers])
                  for u in mod.edu.units)
          for c in a["merges"]))
check("every candidate's twin has an identical footer",
      all(bmdb_mod.footer_key(entries[c["entry"]]) == bmdb_mod.footer_key(entries[c["into"]])
          for c in a["merges"]))
check("a candidate's twin is never the entry itself",
      all(c["into"] != c["entry"] for c in a["merges"]))
check("candidates are never also on the unused list",
      not ({c["entry"] for c in a["merges"]} & unused))
# Twins suggest each other, so A->B and B->A can both look like a saving. Accept
# both and each soldier line ends up naming an entry the same cleanup deleted --
# M2TW then refuses to read the EDU at all.
sources = {c["entry"] for c in a["merges"]}
check("no candidate points at an entry that is itself merged away",
      not [c for c in a["merges"] if c["into"] in sources])
check("nor is one ever offered as an alternative target",
      not [o for c in a["merges"] for o in c["options"] if o in sources])

print("\n== cleanup plan ==")
target = Path(tempfile.mkdtemp(prefix="ut_export_")) / "unused_assets"
picked = sorted(unused)[:20]
merge = a["merges"][0]
plan = bmdb_mod.plan_cleanup(mod, bmdb_mod.CleanupRequest(
    target=str(target), entries=picked,
    merges=[{"entry": merge["entry"], "into": merge["into"]}]))
check("no errors", not plan.errors)
check(f"{len(plan.entry_deletes)} entries queued for removal (20 picked + 1 merged)",
      len(plan.entry_deletes) == 21 and merge["entry"] in plan.entry_deletes)
check("the EDU is rewritten for the merge", bool(plan.edu_text))
check("every exported file mirrors the mod's own layout",
      all(rel.startswith("data/") for _s, rel in plan.exports))
check("a file a surviving entry still uses is never moved",
      all(f not in [r for _s, r in plan.exports] for f in plan.kept_files))

inside = bmdb_mod.plan_cleanup(mod, bmdb_mod.CleanupRequest(
    target=str(root / "export"), entries=picked))
check("refuses an export folder inside the mod", bool(inside.errors))

# A stale scan can list an entry the mod has started using again. Removing it
# would leave a `soldier` line pointing at nothing, which stops M2TW loading the
# EDU at all -- so the plan re-checks the request instead of trusting it.
used_entry = merge["entry"]                       # named by a soldier line
stale = bmdb_mod.plan_cleanup(mod, bmdb_mod.CleanupRequest(
    target=str(target), entries=picked + [used_entry]))
check("a referenced entry asked for as unused is not removed",
      used_entry not in stale.entry_deletes)
check("...and the warning says what still names it",
      any(used_entry in w and "soldier model for" in w for w in stale.warnings))
check("...while the rest of the request still goes through",
      len(stale.entry_deletes) == len(picked))
check("...and nothing rewrites the EDU, since no merge was accepted",
      not stale.edu_text)

# Same entry, this time as an accepted merge: now it may go, because the merge
# repoints the soldier line naming it.
paired = bmdb_mod.plan_cleanup(mod, bmdb_mod.CleanupRequest(
    target=str(target), entries=picked + [used_entry],
    merges=[{"entry": used_entry, "into": merge["into"]}]))
check("the same entry IS removed when a merge repoints its soldier line",
      used_entry in paired.entry_deletes and bool(paired.edu_text))

# A merge that no longer validates must not delete through the exemption either.
bad = bmdb_mod.plan_cleanup(mod, bmdb_mod.CleanupRequest(
    target=str(target), entries=[used_entry],
    merges=[{"entry": used_entry, "into": "no_such_entry_at_all"}]))
check("a merge that fails its checks takes the entry with it",
      used_entry not in bad.entry_deletes and bool(bad.errors))

# The scan no longer offers a mutual pair, but a hand-built request still can.
mutual = bmdb_mod.plan_cleanup(mod, bmdb_mod.CleanupRequest(
    target=str(target),
    merges=[{"entry": used_entry, "into": merge["into"]},
            {"entry": merge["into"], "into": used_entry}]))
check("a mutual pair of merges is refused rather than applied",
      bool(mutual.errors) and not mutual.entry_deletes)
check("...and the error names both halves",
      any(used_entry in e and merge["into"] in e for e in mutual.errors))
into_doomed = bmdb_mod.plan_cleanup(mod, bmdb_mod.CleanupRequest(
    target=str(target), entries=picked,          # picked[0] is on the unused list
    merges=[{"entry": used_entry, "into": picked[0]}]))
check("merging into an entry the same cleanup deletes is refused",
      bool(into_doomed.errors) and used_entry not in into_doomed.entry_deletes)

print("\n== cleanup apply ==")
orig_raw = {e.name: e.raw for e in mod.modeldb.entries}   # applying reparses `mod`
rec = bmdb_mod.apply_cleanup(plan)
mod2 = Mod(root)
db2 = mod2.modeldb
check(f"modeldb went {a['entry_count']} -> {len(db2.entries)}",
      len(db2.entries) == a["entry_count"] - 21)
check("removed entries are gone", not (set(plan.entry_deletes) & set(db2.by_name())))
check("the header count follows the removal",
      db2.header_ints[5] == len(db2.entries) + (1 if db2.blank_raw else 0))
check("the file still parses to a clean round trip",
      db2.to_text() == mod2.modeldb_path.read_text(encoding=modeldb.ENCODING))

merged_unit = next(u for u in mod2.edu.units if u.type == merge["units"][0])
check(f"'{merged_unit.type}' soldier is now '{merge['into']}'",
      merged_unit.soldier_model.lower() == merge["into"])
check("nothing in the EDU names a removed entry any more",
      not ({m for u in mod2.edu.units for m in u.model_names()} & set(plan.entry_deletes)))

print("\n== the export folder ==")
exp_db = target / bmdb_mod.EXPORT_DB_NAME
check("a standalone modeldb was written next to the assets", exp_db.is_file())
parsed = modeldb.parse_file(exp_db)
check(f"it parses and holds exactly the {len(plan.entry_deletes)} removed entries",
      sorted(parsed.by_name()) == sorted(plan.entry_deletes))
check("its entries are byte-identical to the ones cut out of the mod",
      all(e.raw == orig_raw[e.name] for e in parsed.entries))
check("a README explains how to put it back", (target / bmdb_mod.README_NAME).is_file())
check("it is not called battle_models.modeldb (it would overwrite a real one)",
      not (target / "data" / "unit_models" / "battle_models.modeldb").exists())

print("\n== undo ==")
undo(rec["id"])
mod3 = Mod(root)
check("the modeldb is restored byte-exact", mod3.modeldb_path.read_bytes() == before_db)
check("export_descr_unit.txt is restored byte-exact", mod3.edu_path.read_bytes() == before_edu)
check("the export folder is left alone (it is a copy, not the original)", exp_db.is_file())

print("\n== assets really move ==")
# a fresh mod that actually has the files of one unused entry on disk (a mod's
# modeldb names plenty of files that were never shipped with it, so pick an entry
# whose files really are in the source mod)
mod_a = Mod(fresh_mod())
owners = {}
for e in mod_a.modeldb.entries:
    for f in e.mesh_files() + e.texture_files():
        owners.setdefault(f.lower(), set()).add(e.name)
au = next(u for u in bmdb_mod.audit(mod_a, scan_orphans=False)["unused"]
          if [f for f in u["files"]
              if (TATR / "data" / f).is_file() and owners[f.lower()] == {u["entry"]}])
files = [f for f in au["files"]
         if (TATR / "data" / f).is_file() and owners[f.lower()] == {au["entry"]}][:3]
root_b = fresh_mod(with_assets=files)
mod_b = Mod(root_b)
tgt_b = Path(tempfile.mkdtemp(prefix="ut_export2_")) / "out"
pb = bmdb_mod.plan_cleanup(mod_b, bmdb_mod.CleanupRequest(target=str(tgt_b), entries=[au["entry"]]))
moved = [r for _s, r in pb.exports]
check(f"'{au['entry']}': {len(moved)} of its files are on disk and queued to move", bool(moved))
rec_b = bmdb_mod.apply_cleanup(pb)
check("they are gone from the mod", all(not (mod_b.data / d).exists() for d in pb.deletes))
check("they are in the export folder under the same relative path",
      all((tgt_b / r).is_file() for r in moved))
undo(rec_b["id"])
check("undo brings them back", all((mod_b.data / d).is_file() for d in pb.deletes))

print("\n== orphan files (nothing in the modeldb mentions them) ==")
root_c = fresh_mod()
(Path(root_c) / "data/unit_models/_Junk").mkdir(parents=True)
junk = Path(root_c) / "data/unit_models/_Junk/nobody_reads_this.texture"
junk.write_bytes(b"x" * 4096)
mod_c = Mod(root_c)
ac = bmdb_mod.audit(mod_c)
rels = [o["rel"] for o in ac["orphans"]]
check("the planted file is reported as an orphan",
      "unit_models/_Junk/nobody_reads_this.texture" in rels)
check("no orphan is a file the modeldb actually names",
      not (set(r.lower() for r in rels)
           & {f.lower() for e in mod_c.modeldb.entries
              for f in e.mesh_files() + e.texture_files()}))
check("the modeldb itself is never offered as an orphan",
      not any(".modeldb" in r.lower() for r in rels))
tgt_c = Path(tempfile.mkdtemp(prefix="ut_export3_")) / "out"
pc = bmdb_mod.plan_cleanup(mod_c, bmdb_mod.CleanupRequest(
    target=str(tgt_c), orphans=["unit_models/_Junk/nobody_reads_this.texture"]))
rec_c = bmdb_mod.apply_cleanup(pc)
check("it moves into the export's unused folder, path mirrored",
      (tgt_c / bmdb_mod.UNUSED_SUBDIR / "data/unit_models/_Junk/nobody_reads_this.texture").is_file())
check("and is gone from the mod", not junk.exists())
check("the modeldb was not rewritten — no entry was touched",
      Mod(root_c).modeldb_path.read_bytes() == before_db)
undo(rec_c["id"])
check("undo restores it", junk.is_file())

print("\n== mod-wide entry editing (the unit editor's engine, no unit) ==")
root_d = fresh_mod()
mod_d = Mod(root_d)
# an entry several units reference: the rename has to reach every one of them
counts = {}
for u in mod_d.edu.units:
    for m in u.model_names():
        counts.setdefault(m, []).append(u.type)
name, users = max(counts.items(), key=lambda kv: len(kv[1]))
req = edit.bmdb_request_from_dict(
    {"model_edits": [{"entry": name, "new_name": name + "_renamed"}]})
pd = edit.plan_bmdb(mod_d, req)
check("no errors", not pd.errors)
check(f"'{name}' renamed", pd.entry_renames.get(name) == name + "_renamed")
check(f"all {len(users)} units that named it are rewritten", bool(pd.edu_text))
edit.apply_edit(pd)
mod_e = Mod(root_d)
check("the entry is renamed in the modeldb", name + "_renamed" in mod_e.modeldb.by_name())
check("no unit still names the old entry",
      not any(name in u.model_names() for u in mod_e.edu.units))
check(f"all {len(users)} of them name the new one",
      sum(1 for u in mod_e.edu.units if name + "_renamed" in u.model_names()) == len(users))

print("\n== padded first entry (a modeldb with no 'blank' sentinel) ==")
# Such a file keeps its reserved int-pairs in the FIRST entry, so that entry can
# never be the one we drop — the next entry has no padding and the file would stop
# parsing. Built by hand (same shape as tests/test_modeldb_no_blank_entry.py).
P = "0 0 "
def _padded(name, tex):
    return (f"\n{len(name)} {name} \n1.0 {P}\n1 {P}"
            f"\n{len('m/' + name + '.mesh')} m/{name}.mesh 121 {P}"
            f"\n1 {P}\n4 ever \n{len(tex)} {tex} \n{len(tex)} {tex} \n0 \n0 "
            f"{P}\n1 {P}\n5 horse \n3 pri \n3 sec \n0 \n0 {P}"
            f"\n-1 0.0 0.0 0.0 0.0 0.0 0.0 {P}")
def _plain(name, tex):
    return (f"\n{len(name)} {name} \n1.0 \n1 "
            f"\n{len('m/' + name + '.mesh')} m/{name}.mesh 121 "
            f"\n1 \n4 ever \n{len(tex)} {tex} \n{len(tex)} {tex} \n0 \n0 "
            f"\n1 \n5 horse \n3 pri \n3 sec \n0 \n0 "
            f"\n-1 0.0 0.0 0.0 0.0 0.0 0.0 ")
root_f = fresh_mod()
(Path(root_f) / "data/unit_models/battle_models.modeldb").write_text(
    "22 serialization::archive 3 0 0 0 0 3 0 0"
    + _padded("pad_first", "t/a.texture") + _plain("second_e", "t/b.texture")
    + _plain("third_e", "t/c.texture"), encoding=modeldb.ENCODING)
mod_f = Mod(root_f)
first = mod_f.modeldb.entries[0]
check(f"the first entry '{first.name}' is the padded one", first.first_entry_pad)
af = bmdb_mod.audit(mod_f, scan_orphans=False)
check("it is not even offered as unused",
      first.name not in {u["entry"] for u in af["unused"]}
      and first.name in {m["entry"] for m in af["mentioned"]})
tgt_f = Path(tempfile.mkdtemp(prefix="ut_export4_")) / "out"
pf = bmdb_mod.plan_cleanup(mod_f, bmdb_mod.CleanupRequest(
    target=str(tgt_f), entries=[first.name, "second_e", "third_e"]))
check("asked for anyway, it is refused with a reason",
      pf.entry_deletes == ["second_e", "third_e"] and any("padded" in w for w in pf.warnings))
bmdb_mod.apply_cleanup(pf)
check("what is left still parses, padding intact",
      [e.name for e in Mod(root_f).modeldb.entries] == ["pad_first"])
exported = modeldb.parse_file(tgt_f / bmdb_mod.EXPORT_DB_NAME)
check("the export of a sentinel-less file gets a sentinel of its own so it reads back",
      sorted(exported.by_name()) == ["second_e", "third_e"] and bool(exported.blank_raw))

print(f"\n{sum(ok)}/{len(ok)} checks passed")
sys.exit(0 if all(ok) else 1)
