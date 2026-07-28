"""Unit EDITOR mode (edits inside one mod): fields, names, bmdb, delete, undo.

Works on a throwaway copy of Third_Age_Reforged's data files (plus fake icons and
fake mesh/texture imports) so the real mods are never touched. Covers:
  * editing an EDU field, and REMOVING a field outright (blanking != removing)
  * editing the localised name / description
  * renaming `dictionary` -> localisation record moves, unit cards follow
  * renaming a bmdb entry -> the unit's EDU refs follow it
  * repointing an existing bmdb path slot
  * creating a NEW bmdb entry cloned from the unit's own (mesh + texture imported
    and copied in, sprites/ownership/animations kept from the clone)
  * duplicating a unit via the transfer engine with source == destination
  * deleting a unit (localisation + orphaned model entries)
  * undo of every one of those, byte-exact
"""
import shutil, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import config, edu, localization, modeldb
from unittransfer.mod import Mod
from unittransfer import edit
from unittransfer.transfer import TransferOptions, plan_transfer, apply_transfer, undo

MODS = Path(r"C:/Users/projy/Downloads/Games/Total War MEDIEVAL II Definitive Edition/mods")
TATR = MODS / "Third_Age_Reforged"

ok = []
def check(label, cond):
    ok.append(bool(cond)); print(f"  [{'OK ' if cond else 'FAIL'}] {label}")


def fresh_mod() -> Path:
    root = Path(tempfile.mkdtemp(prefix="ut_edit_"))
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

# a unit whose soldier model is a real entry with LODs + faction textures
entries = mod.modeldb.by_name()
UNIT = None
for u in mod.edu.units:
    e = entries.get((u.soldier_model or "").lower())
    if e and e.lods and e.main_textures and u.dictionary and not u.mount:
        UNIT = u.type
        break
assert UNIT, "no suitable unit found in the test mod"
unit = mod.edu.by_type()[UNIT]
soldier = unit.soldier_model.lower()
print(f"unit={UNIT!r} dict={unit.dictionary!r} soldier={soldier!r}")

# fake unit cards, so the dictionary rename has something to move. They go in the
# folders the unit ACTUALLY resolves icons from (card_pic_dir can pin the card to
# `mercs` while the info card stays under the ownership faction).
CARD_DIR, INFO_DIR = unit.card_dirs()[0], unit.info_dirs()[0]
card_p = mod.data / "ui/units" / CARD_DIR / f"#{unit.dictionary}.tga"
card_p.parent.mkdir(parents=True, exist_ok=True); card_p.write_bytes(b"CARD")
info_p = mod.data / "ui/unit_info" / INFO_DIR / f"{unit.dictionary}_info.tga"
info_p.parent.mkdir(parents=True, exist_ok=True); info_p.write_bytes(b"INFO")

# fake import sources for the new model entry
imports = Path(tempfile.mkdtemp(prefix="ut_import_"))
mesh_src = imports / "brand_new_soldier.mesh"; mesh_src.write_bytes(b"MESHDATA")
tex_src = imports / "brand_new_soldier.texture"; tex_src.write_bytes(b"TEXDATA")

edu_before = (mod.data / "export_descr_unit.txt").read_bytes()
db_before = (mod.data / "unit_models/battle_models.modeldb").read_bytes()
loc_before = (mod.data / "text/export_units.txt").read_bytes()

# ---------------------------------------------------------------- 1) fields
print("\n1) EDU field edit + field removal")
has_era2 = any(edu.line_key(l) == "era 2" for l in unit.raw.splitlines(keepends=True))
req = edit.request_from_dict({
    "unit": UNIT,
    "field_overrides": {"stat_health": "3, 0", "stat_charge_dist": "42"},
    "remove_fields": ["era 2"] if has_era2 else [],
    "loc": {"name": "Edited Test Name", "descr": "Long text.", "descr_short": "Short text."},
})
plan = edit.plan_edit(mod, req)
check("no errors", not plan.errors)
rec1 = edit.apply_edit(plan)

mod = Mod(root)
u2 = mod.edu.by_type()[UNIT]
fields = dict(edu.block_fields(u2.raw))
check("stat_health updated", fields.get("stat_health") == "3, 0")
check("stat_charge_dist updated", fields.get("stat_charge_dist") == "42")
if has_era2:
    check("era 2 line GONE (not blanked)", "era 2" not in fields)
check("other fields untouched", fields.get("type") == UNIT and fields.get("soldier"))
loc_e = mod.loc.get(u2.dictionary)
check("localised name updated", loc_e and loc_e.name == "Edited Test Name")
check("descr updated", loc_e and loc_e.descr == "Long text.")
check("descr_short updated", loc_e and loc_e.descr_short == "Short text.")
check("EDU still parses to the same unit count",
      len(mod.edu.units) == len(edu.parse_text(edu_before.decode(edu.ENCODING)).units))

# --------------------------------------------------------- 2) new bmdb entry
print("\n2) new bmdb entry cloned from the unit's own model")
clone = mod.modeldb.by_name()[soldier]
new_name = "ut_test_new_model"
req = edit.request_from_dict({
    "unit": UNIT,
    "new_models": [{
        "name": new_name, "clone_from": soldier,
        "dest_dir": "unit_models/_ut_test",
        "mesh_src": str(mesh_src), "texture_src": str(tex_src),
        "mesh_all_lods": True, "assign_to": "soldier",
    }],
})
plan = edit.plan_edit(mod, req)
check("plan has no errors", not plan.errors)
check("2 files queued for copy", len(plan.copies) == 2)
rec2 = edit.apply_edit(plan)

mod = Mod(root)
db = mod.modeldb
e_new = db.by_name().get(new_name)
check("new entry present", e_new is not None)
check("old entry still present", db.by_name().get(soldier) is not None)
check("entry count +1", len(db.entries) ==
      len(modeldb.parse_text(db_before.decode(modeldb.ENCODING)).entries) + 1)
check("modeldb round-trips byte-exact",
      db.to_text() == (mod.data / "unit_models/battle_models.modeldb").read_text(
          encoding=modeldb.ENCODING))
check("every LOD points at the imported mesh",
      all(m == "unit_models/_ut_test/brand_new_soldier.mesh" for m, _ in e_new.lods))
check("every faction texture points at the imported texture",
      all(t.texture == "unit_models/_ut_test/brand_new_soldier.texture"
          for t in e_new.main_textures))
check("sprites kept from the clone",
      [t.sprite for t in e_new.main_textures] == [t.sprite for t in clone.main_textures])
check("ownership (faction list) kept from the clone",
      e_new.factions() == clone.factions())
check("footer kept: animations/skeletons",
      [a.primary_skeleton for a in e_new.animations] ==
      [a.primary_skeleton for a in clone.animations])
check("footer kept: torch", e_new.torch_index == clone.torch_index
      and [round(x, 4) for x in e_new.torch] == [round(x, 4) for x in clone.torch])
check("imported files copied in",
      (mod.data / "unit_models/_ut_test/brand_new_soldier.mesh").read_bytes() == b"MESHDATA"
      and (mod.data / "unit_models/_ut_test/brand_new_soldier.texture").read_bytes() == b"TEXDATA")
u3 = mod.edu.by_type()[UNIT]
check("unit's soldier now points at the new entry",
      u3.soldier_model.lower() == new_name)
check("soldier line kept its other CSV values",
      len(dict(edu.block_fields(u3.raw))["soldier"].split(",")) ==
      len(dict(edu.block_fields(unit.raw))["soldier"].split(",")))

# ------------------------------------------- 3) rename entry + repoint a path
print("\n3) rename a bmdb entry + repoint one path slot")
slots = modeldb.path_slots(mod.modeldb.by_name()[new_name])
tex_slot = next(s for s in slots if s["kind"] == "texture")
req = edit.request_from_dict({
    "unit": UNIT,
    "model_edits": [{"entry": new_name, "new_name": "ut_test_renamed",
                     "paths": {str(tex_slot["i"]): "unit_models/_ut_test/other.texture"}}],
})
plan = edit.plan_edit(mod, req)
check("no errors", not plan.errors)
edit.apply_edit(plan)
mod = Mod(root)
check("entry renamed", "ut_test_renamed" in mod.modeldb.by_name()
      and new_name not in mod.modeldb.by_name())
check("EDU soldier ref followed the rename",
      mod.edu.by_type()[UNIT].soldier_model.lower() == "ut_test_renamed")
ren = mod.modeldb.by_name()["ut_test_renamed"]
check("only the targeted texture slot changed",
      ren.main_textures[0].texture == "unit_models/_ut_test/other.texture"
      and all(t.texture == "unit_models/_ut_test/brand_new_soldier.texture"
              for t in ren.main_textures[1:]))
check("modeldb still round-trips",
      mod.modeldb.to_text() ==
      (mod.data / "unit_models/battle_models.modeldb").read_text(encoding=modeldb.ENCODING))

# -------------------------------------------------- 4) dictionary rename
print("\n4) dictionary rename carries text entry + unit cards")
old_dict = mod.edu.by_type()[UNIT].dictionary
req = edit.request_from_dict({"unit": UNIT, "new_dictionary": old_dict + "_ren"})
plan = edit.plan_edit(mod, req)
check("no errors", not plan.errors)
check("icon copies planned", len(plan.icon_copies) >= 2)
edit.apply_edit(plan)
mod = Mod(root)
u4 = mod.edu.by_type()[UNIT]
check("dictionary changed", u4.dictionary == old_dict + "_ren")
check("new text entry exists", mod.loc.get(u4.dictionary) is not None)
check("new text entry kept the name",
      mod.loc.get(u4.dictionary).name == "Edited Test Name")
check("old text entry removed", mod.loc.get(old_dict) is None)
check("card found under the new name", mod.find_unit_card(u4) is not None)
check("info card found under the new name", mod.find_unit_info(u4) is not None)

# ------------------------------------------------ 5) duplicate (new unit)
print("\n5) new unit from an existing one (transfer engine, source == dest)")
n_before = len(mod.edu.units)
opts = TransferOptions(on_conflict="rename", new_type="UT Test Clone",
                       new_dictionary="ut_test_clone",
                       asset_conflict="use_existing", icon_conflict="use_existing")
dup = plan_transfer(mod, UNIT, mod, opts)
check("clone reuses the existing models (nothing added)", not dup.add_entries)
apply_transfer(dup)
mod = Mod(root)
check("unit count +1", len(mod.edu.units) == n_before + 1)
clone_u = mod.edu.by_type().get("UT Test Clone")
check("clone exists with its own dictionary",
      clone_u is not None and clone_u.dictionary == "ut_test_clone")
check("clone points at the same models",
      clone_u.soldier_model.lower() == "ut_test_renamed")

# ------------------------------------------------------------ 6) delete
print("\n6) delete a unit (localisation + orphaned model entries)")
n_before = len(mod.edu.units)
db_entries_before = len(mod.modeldb.entries)
req = edit.request_from_dict({
    "unit": "UT Test Clone", "delete": True,
    "delete_options": {"remove_loc": True, "remove_models": True,
                       "remove_assets": True, "remove_icons": False},
})
plan = edit.plan_edit(mod, req)
check("delete plan has no errors", not plan.errors)
# the clone shares its models with the original unit -> nothing may be removed
check("shared model entries are NOT deleted", not plan.entry_deletes)
rec_del = edit.apply_edit(plan)
mod = Mod(root)
check("unit removed", "UT Test Clone" not in mod.edu.by_type())
check("unit count -1", len(mod.edu.units) == n_before - 1)
check("text entry removed", mod.loc.get("ut_test_clone") is None)
check("shared models untouched", len(mod.modeldb.entries) == db_entries_before)
check("original unit still there", UNIT in mod.edu.by_type())

# now delete the original: its (renamed, unique) model entry must go with it
u_orig = mod.edu.by_type()[UNIT]
req = edit.request_from_dict({
    "unit": UNIT, "delete": True,
    "delete_options": {"remove_loc": True, "remove_models": True,
                       "remove_assets": True, "remove_icons": True},
})
plan = edit.plan_edit(mod, req)
check("orphaned entry queued for removal", "ut_test_renamed" in plan.entry_deletes)
check("its imported mesh queued for deletion",
      "unit_models/_ut_test/brand_new_soldier.mesh" in plan.deletes)
edit.apply_edit(plan)
mod = Mod(root)
check("unit gone", UNIT not in mod.edu.by_type())
check("orphaned model entry gone", "ut_test_renamed" not in mod.modeldb.by_name())
check("imported mesh deleted",
      not (mod.data / "unit_models/_ut_test/brand_new_soldier.mesh").exists())
check("icons deleted", mod.find_unit_card(u_orig) is None)
check("modeldb header count correct after removal",
      mod.modeldb.header_ints[5] ==
      len(mod.modeldb.entries) + (1 if mod.modeldb.blank_raw else 0))
check("modeldb round-trips after removal",
      mod.modeldb.to_text() ==
      (mod.data / "unit_models/battle_models.modeldb").read_text(encoding=modeldb.ENCODING))

# ------------------------------------------------------------- 7) undo all
print("\n7) undo every edit, newest first -> byte-exact original")
for rec in reversed(config.load_log()):
    if rec.get("applied") and not rec.get("undone"):
        undo(rec["id"])
check("EDU restored byte-exact",
      (root / "data/export_descr_unit.txt").read_bytes() == edu_before)
check("modeldb restored byte-exact",
      (root / "data/unit_models/battle_models.modeldb").read_bytes() == db_before)
check("export_units restored byte-exact",
      (root / "data/text/export_units.txt").read_bytes() == loc_before)
check("imported files removed by undo",
      not (root / "data/unit_models/_ut_test").exists()
      or not any((root / "data/unit_models/_ut_test").iterdir()))
check("deleted icons restored by undo",
      card_p.read_bytes() == b"CARD" and info_p.read_bytes() == b"INFO")

print(f"\n{sum(ok)}/{len(ok)} checks passed")
for p in (root, cfg, imports):
    shutil.rmtree(p, ignore_errors=True)
sys.exit(0 if all(ok) else 1)
