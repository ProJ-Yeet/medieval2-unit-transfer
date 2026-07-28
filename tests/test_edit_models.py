"""Unit EDITOR — the battle-model half of the editor (Stage 14 layout rework).

Works on a throwaway copy of Third_Age_Reforged's data files, so the real mods
are never touched. Covers what the new bmdb tab drives:
  * renaming an entry rewrites EVERY unit that referenced it, not just the one
    being edited (the old behaviour left the others pointing at a dead name)
  * the faction checklist: adding a skin clones an existing record, removing one
    drops it, and both texture groups keep matching counts
  * "default textures for every faction unless stated otherwise" + per-faction
    overrides, addressed by faction so they survive a faction add/remove
  * standardising an entry's files into one folder: mesh at <base>/, textures at
    <base>/textures/, other entries using the same files reported and (opt-in)
    repointed with it
  * undo of all of the above, byte-exact
"""
import shutil, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import config, edu, modeldb
from unittransfer.mod import Mod
from unittransfer import edit

MODS = Path(r"C:/Users/projy/Downloads/Games/Total War MEDIEVAL II Definitive Edition/mods")
TATR = MODS / "Third_Age_Reforged"

ok = []
def check(label, cond):
    ok.append(bool(cond)); print(f"  [{'OK ' if cond else 'FAIL'}] {label}")


def fresh_mod() -> Path:
    root = Path(tempfile.mkdtemp(prefix="ut_editmodels_"))
    data = root / "data"
    (data / "text").mkdir(parents=True)
    (data / "unit_models").mkdir(parents=True)
    for rel in ("export_descr_unit.txt", "text/export_units.txt",
                "unit_models/battle_models.modeldb", "descr_mount.txt"):
        src = TATR / "data" / rel
        if src.exists():
            shutil.copy2(src, data / rel)
    return root


cfg = Path(tempfile.mkdtemp(prefix="ut_cfg_"))
config.CONFIG_DIR = cfg; config.BACKUP_DIR = cfg / "backups"
config.SETTINGS_PATH = cfg / "settings.json"; config.LOG_PATH = cfg / "transfers.json"

root = fresh_mod()
mod = Mod(root)
entries = mod.modeldb.by_name()

# A unit whose soldier model has several faction skins AND is used by at least
# one OTHER unit — that is what makes the mod-wide rename worth testing.
users = {}
for u in mod.edu.units:
    for m in u.model_names():
        users.setdefault(m, []).append(u.type)
UNIT = SOLDIER = None
for u in mod.edu.units:
    e = entries.get((u.soldier_model or "").lower())
    if e and e.lods and len(e.main_textures) > 2 and len(users.get(e.name, [])) > 1:
        UNIT, SOLDIER = u.type, e.name
        break
assert UNIT, "no suitable unit found in the test mod"
OTHERS = [t for t in users[SOLDIER] if t != UNIT]
print(f"unit={UNIT!r} soldier={SOLDIER!r} also used by {len(OTHERS)} other unit(s)")

# real files on disk for the entry's meshes/textures, so the folder move has
# something to actually move
entry0 = entries[SOLDIER]
for rel in entry0.mesh_files() + entry0.texture_files():
    p = mod.data / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_bytes(b"ASSET:" + rel.encode("latin-1"))

edu_before = (mod.data / "export_descr_unit.txt").read_bytes()
db_before = (mod.data / "unit_models/battle_models.modeldb").read_bytes()
recs = []

# ------------------------------------------------- 1) mod-wide entry rename
print("\n1) renaming a bmdb entry rewrites every unit that used it")
RENAMED = "ut_renamed_entry"
plan = edit.plan_edit(mod, edit.request_from_dict({
    "unit": UNIT, "model_edits": [{"entry": SOLDIER, "new_name": RENAMED}]}))
check("no errors", not plan.errors)
check("rename recorded", plan.entry_renames.get(SOLDIER) == RENAMED)
check("other units mentioned in the preview",
      any("other unit" in c for c in plan.changes))
recs.append(edit.apply_edit(plan))

mod = Mod(root)
check("entry renamed in the modeldb", RENAMED in mod.modeldb.by_name())
check("old entry name gone", SOLDIER not in mod.modeldb.by_name())
by_type = mod.edu.by_type()
check("edited unit repointed", RENAMED in by_type[UNIT].model_names())
check("EVERY other unit repointed too",
      all(RENAMED in by_type[t].model_names() and SOLDIER not in by_type[t].model_names()
          for t in OTHERS))
check("no unit still names the old entry",
      not any(SOLDIER in u.model_names() for u in mod.edu.units))
check("EDU still parses to the same unit count",
      len(mod.edu.units) == len(edu.parse_text(edu_before.decode(edu.ENCODING)).units))

# ------------------------------------------------------- 2) faction skins
print("\n2) faction checklist — add a skin, drop a skin")
e = mod.modeldb.by_name()[RENAMED]
before_facs = [t.faction for t in e.main_textures]
before_attach = len(e.attach_textures)
wanted = before_facs[:-1] + ["ut_newfaction"]           # drop the last, add one
plan = edit.plan_edit(mod, edit.request_from_dict({
    "unit": UNIT, "model_edits": [{"entry": RENAMED, "factions": wanted}]}))
check("no errors", not plan.errors)
check("add + remove both previewed",
      any("added" in c for c in plan.changes) and any("removed" in c for c in plan.changes))
recs.append(edit.apply_edit(plan))

mod = Mod(root)
e = mod.modeldb.by_name()[RENAMED]
check("main texture records match the checklist",
      [t.faction for t in e.main_textures] == wanted)
check("attachment records follow the same list",
      not before_attach or [t.faction for t in e.attach_textures] == wanted)
check("the new skin cloned real texture paths",
      all(t.texture and t.texture != "0" for t in e.main_textures))
check("modeldb round-trips byte-exact",
      mod.modeldb.to_text() == (mod.data / "unit_models/battle_models.modeldb")
      .read_text(encoding=modeldb.ENCODING))

# an empty checklist must be refused, not written
bad = edit.plan_edit(mod, edit.request_from_dict({
    "unit": UNIT, "model_edits": [{"entry": RENAMED, "factions": []}]}))
check("emptying the faction list is an error", any("at least one faction" in x
                                                   for x in bad.errors))

# ------------------------------------- 3) default + per-faction texture paths
print("\n3) default textures for all factions, with a per-faction override")
UNIQUE_FAC = wanted[0]
plan = edit.plan_edit(mod, edit.request_from_dict({
    "unit": UNIT, "model_edits": [{
        "entry": RENAMED,
        "defaults": {"texture": "unit_models/_ut/default.texture",
                     "normal": "unit_models/_ut/default_norm.texture"},
        "faction_paths": {UNIQUE_FAC: {"texture": "unit_models/_ut/unique.texture"}},
    }]}))
check("no errors", not plan.errors)
recs.append(edit.apply_edit(plan))

mod = Mod(root)
e = mod.modeldb.by_name()[RENAMED]
tex = {t.faction: t for t in e.main_textures}
check("the overridden faction got its own texture",
      tex[UNIQUE_FAC].texture == "unit_models/_ut/unique.texture")
check("every other faction got the default",
      all(t.texture == "unit_models/_ut/default.texture"
          for f, t in tex.items() if f != UNIQUE_FAC))
check("the override still took the default normal map",
      tex[UNIQUE_FAC].normal == "unit_models/_ut/default_norm.texture")
check("sprites were left alone", all(t.sprite for t in e.main_textures))
# an attachment has no sprite: the file stores a zero-length string there, and
# the editor never offers that slot, so it must come back untouched
check("attachment sprites are still the format's empty string",
      all(t.sprite == "" for t in e.attach_textures))

# ------------------------------------------------ 4) standardise the folder
print("\n4) standardise an entry's files into one folder")
mod = Mod(root)
e = mod.modeldb.by_name()[RENAMED]
# a second entry sharing any file with ours, so the "who else uses this" path runs
ours = set(e.mesh_files()) | set(e.texture_files())
victim = next((x for x in mod.modeldb.entries if x.name != RENAMED
               and ours & (set(x.mesh_files()) | set(x.texture_files()))), None)
for rel in e.mesh_files() + e.texture_files():
    p = mod.data / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_bytes(b"ASSET:" + rel.encode("latin-1"))

TARGET = "unit_models/_ut_standard"
report = edit.model_folder_report(mod, RENAMED, TARGET)
check("report has moves queued", len(report["moves"]) > 0)
check("report names the sharers" if victim else "report has no sharers",
      bool(report["shared_entries"]) == bool(victim))

plan = edit.plan_edit(mod, edit.request_from_dict({
    "unit": UNIT, "model_edits": [{"entry": RENAMED, "move_dir": TARGET,
                                   "move_shared": True}]}))
check("no errors", not plan.errors)
old_files = [str(mod.data / rel) for rel in e.mesh_files() + e.texture_files()]
recs.append(edit.apply_edit(plan))

mod = Mod(root)
e = mod.modeldb.by_name()[RENAMED]
check("every mesh now sits directly in the target folder",
      all(m.startswith(TARGET + "/") and "/" not in m[len(TARGET) + 1:]
          for m in e.mesh_files()))
tex_files = [t.texture for t in e.main_textures] + [t.normal for t in e.main_textures]
check("every texture now sits in <target>/textures/",
      all(p.startswith(TARGET + "/textures/") for p in tex_files if p and p != "0"))
check("sprites were NOT relocated",
      all(not (t.sprite or "").startswith(TARGET) for t in e.main_textures))
check("the files really are on disk at the new paths",
      all((mod.data / rel).is_file() for rel in e.mesh_files() + e.texture_files()))
check("folder_info now reports it as standardised",
      edit.folder_info(e)["base"] == TARGET)
if victim:
    v = mod.modeldb.by_name()[victim.name]
    check("the sharing entry was repointed with it",
          any(p.startswith(TARGET + "/")
              for p in v.mesh_files() + v.texture_files()))
check("modeldb round-trips byte-exact",
      mod.modeldb.to_text() == (mod.data / "unit_models/battle_models.modeldb")
      .read_text(encoding=modeldb.ENCODING))
check("moving to the folder it already uses is a no-op",
      not edit.folder_moves(e, TARGET))

# ------------------------------------------------------------------ 5) undo
print("\n5) undo every model edit, newest first -> byte-exact original")
from unittransfer.transfer import undo
for rec in reversed(recs):
    undo(rec["id"])
check("EDU restored byte-exact",
      (root / "data/export_descr_unit.txt").read_bytes() == edu_before)
check("modeldb restored byte-exact",
      (root / "data/unit_models/battle_models.modeldb").read_bytes() == db_before)
check("relocated files removed again",
      not (root / "data" / TARGET).exists() or
      not any((root / "data" / TARGET).rglob("*.mesh")))
check("original files back on disk", all(Path(p).is_file() for p in old_files))

print(f"\n{sum(ok)}/{len(ok)} checks passed")
shutil.rmtree(root, ignore_errors=True)
sys.exit(0 if all(ok) else 1)
