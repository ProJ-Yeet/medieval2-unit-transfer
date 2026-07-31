"""BMDB mode — the whole battle_models.modeldb, not one unit's slice of it.

Runs on a throwaway copy of Third_Age_Reforged's data files, so the real mods are
never touched. Covers:
  * the audit: what nothing references, what only a `soldier` line names, and
    which files under unit_models no entry mentions at all
  * the safety nets: an entry named in a descr_*.txt — or inline in a campaign's
    descr_strat.txt / campaign_script.txt — is never called unused, and the padded
    first entry of a sentinel-less modeldb is never removed
  * mounts no unit rides: reported, removable from descr_mount.txt, and the model
    entry they were the last referrer of comes free with them
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
steps = []
a = bmdb_mod.audit(mod, progress=lambda pct, label: steps.append((pct, label)))
check(f"the audit reported {len(steps)} progress steps, each with a label",
      len(steps) > 5 and all(label for _pct, label in steps))
check("progress never goes backwards and ends at 100%",
      all(b[0] >= x[0] for x, b in zip(steps, steps[1:])) and steps[-1][0] == 100)
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
# Only referenced entries are offered to move onto: that is what keeps them off
# the unused list and what makes plan_cleanup refuse to delete them. An entry
# held back only because a descr_*.txt mentions it is deletable, so it is out.
users_now = bmdb_mod.entry_users(mod)
def is_referenced(n):
    s = users_now.get(n)
    return bool(s and any(s[k] for k in bmdb_mod.SLOT_KINDS))
check("every target offered is an entry something still references",
      all(is_referenced(o) for c in a["merges"] for o in c["options"]))
check("...including the default pick",
      all(is_referenced(c["into"]) for c in a["merges"]))
# "already an armour tier of the same unit" is a fact about the picked twin, so the
# audit says it for EVERY option — the UI's picker can be changed after the scan.
by_type = mod.edu.by_type()
def _own_tiers(c):
    return {x.lower() for t in c["units"] if by_type.get(t)
            for x in by_type[t].armour_ug_models}
check("each candidate flags which of its options are armour tiers of the same unit",
      all(set(c["own_options"]) <= set(c["options"]) for c in a["merges"])
      and all(set(c["own_options"]) == set(c["options"]) & _own_tiers(c)
              for c in a["merges"]))
check("the default pick's badge agrees with that list",
      all(c["own_upgrade"] == (c["into"] in c["own_options"]) for c in a["merges"]))
check("an entry only a descr_*.txt mentions is never offered as a target",
      not ({m["entry"] for m in a["mentioned"]}
           & {o for c in a["merges"] for o in c["options"]}))

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

print("\n== campaign references (descr_strat.txt / campaign_script.txt) ==")
# A named character on the campaign map can carry its own battle_model, written
# inline in a comma-separated line rather than on one of its own. Nothing in the
# EDU or descr_mount points at it, so without this pass it looks stone dead.
root_e = fresh_mod()
dead = [u["entry"] for u in bmdb_mod.audit(Mod(root_e), scan_orphans=False)["unused"]]
in_strat, in_script, in_comment = dead[0], dead[1], dead[2]
camp = root_e / "data/world/maps/campaign/imperial_campaign"
camp.mkdir(parents=True)
(camp / "descr_strat.txt").write_text(
    "character\tGrishnakh, general, male, age 23, x 346, y 250, "
    f"portrait Grishnak, battle_model {in_strat}, hero_ability WHIPING\n",
    encoding="latin-1")
(camp / "campaign_script.txt").write_text(
    f"    spawn_character England, agent spy, battle_model {in_script}, x 10, y 20\n"
    f"    ;spawn_character England, agent spy, battle_model {in_comment}, x 1, y 2\n",
    encoding="latin-1")
mod_e2 = Mod(root_e)
a_e = bmdb_mod.audit(mod_e2, scan_orphans=False)
unused_e = {u["entry"] for u in a_e["unused"]}
check("both campaign files are found", len(a_e["campaign_files"]) == 2)
check(f"'{in_strat}' (descr_strat.txt, inline after a comma) is no longer unused",
      in_strat not in unused_e)
check(f"'{in_script}' (campaign_script.txt) is no longer unused", in_script not in unused_e)
check(f"'{in_comment}' (only in a commented-out line) is still unused",
      in_comment in unused_e)
slots_e = bmdb_mod.entry_users(mod_e2)
check("the reference is attributed to the campaign file it came from",
      slots_e[in_strat]["campaign"] == ["file:imperial_campaign/descr_strat.txt"])
pe = bmdb_mod.plan_cleanup(mod_e2, bmdb_mod.CleanupRequest(
    target=str(Path(tempfile.mkdtemp(prefix="ut_exp_"))), entries=[in_strat]))
check("asked to remove it anyway, the cleanup refuses", not pe.entry_deletes)
check("and says which campaign file still names it",
      any("descr_strat.txt" in w for w in pe.warnings))

print("\n== descr_model_strat.txt is not a reference ==")
# The "any descr_*.txt that mentions it" net is deliberately over-cautious, but
# descr_model_strat.txt only ever names STRAT-map models (data/models_strat) — a
# battle-model name matching in there is a coincidence that would pin a genuinely
# dead entry in place forever.
root_g = fresh_mod()
dead_g = [u["entry"] for u in bmdb_mod.audit(Mod(root_g), scan_orphans=False)["unused"]][0]
strat_block = (f"type {dead_g}\nskeleton strat_named_with_army\n"
               f"model_flexi data/models_strat/{dead_g}_high.cas, 15\n")
(root_g / "data/descr_model_strat.txt").write_text(strat_block, encoding="latin-1")
a_g = bmdb_mod.audit(Mod(root_g), scan_orphans=False)
check(f"'{dead_g}' named in descr_model_strat.txt is still reported as unused",
      dead_g in {u["entry"] for u in a_g["unused"]})
check("and is not held back as 'mentioned somewhere else'",
      dead_g not in {m["entry"] for m in a_g["mentioned"]})
(root_g / "data/descr_model_strat.txt").unlink()
(root_g / "data/descr_ut_other.txt").write_text(strat_block, encoding="latin-1")
a_g2 = bmdb_mod.audit(Mod(root_g), scan_orphans=False)
check("the same text in any OTHER descr_*.txt still holds it back",
      dead_g in {m["entry"] for m in a_g2["mentioned"]})

print("\n== mounts no unit rides ==")
# Removing the mount is what takes the last referrer off its model, so the entry
# only comes free as part of the same cleanup.
root_f = fresh_mod()
free_me = [u["entry"] for u in bmdb_mod.audit(Mod(root_f), scan_orphans=False)["unused"]][0]
dmp = root_f / "data/descr_mount.txt"
before_mounts = dmp.read_bytes()
dmp.write_text(dmp.read_text(encoding="latin-1") +
               f"\ntype\t\t\tut_test_mount\nclass\t\t\thorse\nmodel\t\t\t{free_me}\n"
               "radius\t\t\t1.2\nheight\t\t\t2.0\nmass\t\t\t1.0\n", encoding="latin-1")
mod_f = Mod(root_f)
a_f = bmdb_mod.audit(mod_f, scan_orphans=False)
check("the planted mount's model is no longer 'unused' — the mount references it",
      free_me not in {u["entry"] for u in a_f["unused"]})
row = next((r for r in a_f["unused_mounts"] if r["mount"] == "ut_test_mount"), None)
check("the mount is reported as ridden by nobody", row is not None)
check("and flagged as freeing its model entry", bool(row and row["frees_model"]))
ridden = next(u.mount for u in mod_f.edu.units if u.mount)
check(f"a mount a unit actually rides ('{ridden}') is not offered",
      ridden not in {r["mount"] for r in a_f["unused_mounts"]})
pf = bmdb_mod.plan_cleanup(mod_f, bmdb_mod.CleanupRequest(
    target=str(Path(tempfile.mkdtemp(prefix="ut_exp_"))), mounts=[ridden]))
check("and asked for anyway it is refused, with the riders named",
      not pf.mount_deletes and any(ridden in w for w in pf.warnings))

tgt_f = Path(tempfile.mkdtemp(prefix="ut_exp_"))
n_mounts = len(mod_f.mount_file.mounts)     # applying invalidates mod_f's cached parse
pf2 = bmdb_mod.plan_cleanup(mod_f, bmdb_mod.CleanupRequest(
    target=str(tgt_f), mounts=["ut_test_mount"], entries=[free_me]))
check("planning the removal is clean", not pf2.errors)
check("the mount block goes", pf2.mount_deletes == ["ut_test_mount"])
check("and its model entry goes with it", free_me in pf2.entry_deletes)
rec_f = bmdb_mod.apply_cleanup(pf2)
mod_f2 = Mod(root_f)
check("descr_mount.txt no longer defines it", mod_f2.mount_file.get("ut_test_mount") is None)
check("every other mount is untouched",
      len(mod_f2.mount_file.mounts) == n_mounts - 1)
check("the entry is gone from the modeldb", free_me not in mod_f2.modeldb.by_name())
check("the removed block is exported verbatim so it can be pasted back",
      (tgt_f / bmdb_mod.EXPORT_MOUNTS_NAME).is_file()
      and "ut_test_mount" in (tgt_f / bmdb_mod.EXPORT_MOUNTS_NAME).read_text(encoding="latin-1"))
undo(rec_f["id"])
check("undo restores descr_mount.txt byte-exact",
      (root_f / "data/descr_mount.txt").read_bytes() != before_mounts
      and "ut_test_mount" in (root_f / "data/descr_mount.txt").read_text(encoding="latin-1"))
check("undo restores the modeldb byte-exact",
      (root_f / "data/unit_models/battle_models.modeldb").read_bytes() == before_db)

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
