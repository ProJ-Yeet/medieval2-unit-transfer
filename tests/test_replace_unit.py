"""Replace mode: write a transferred unit's models INTO an existing dest unit.

The alternative to "use another unit as base": instead of a new EDU entry that
inherits a destination unit's stats, the destination unit itself is rewritten —
same type, same dictionary, same localisation, same stats — with the transferred
unit's models. Checked here:

  * no unit is added (same EDU unit count, dest_new_units == 0) and the block
    stays exactly where it was in the file
  * identity + stats + ownership stay the replaced unit's; the models become the
    transferred unit's (soldier, officers, armour upgrades)
  * localisation is NOT touched — the unit keeps its name and description
  * icons are opt-in: nothing by default, and `import_card` writes the source
    card under the REPLACED unit's dictionary
  * the officer / armour-upgrade groups can be kept instead of ported
  * a field override (what the composer's B buttons produce) takes one stat from
    the source unit, and a kind mismatch is refused
  * undo puts everything back byte-for-byte

    python -m tests.test_replace_unit
"""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import config, edu
from unittransfer.mod import Mod
from unittransfer.transfer import (TransferOptions, apply_transfer, plan_transfer,
                                   undo)

MODS = Path(r"C:/Users/projy/Downloads/Games/Total War MEDIEVAL II Definitive Edition/mods")
SRC_MOD, DST_MOD = MODS / "Third_Age_6", MODS / "Divide_and_Conquer_EUR"

ok = []


def check(label, cond):
    ok.append(bool(cond))
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}")


cfg = Path(tempfile.mkdtemp(prefix="ut_cfg_"))
config.CONFIG_DIR = cfg
config.BACKUP_DIR = cfg / "backups"
config.SETTINGS_PATH = cfg / "settings.json"
config.LOG_PATH = cfg / "transfers.json"

DEST_RELS = ("export_descr_unit.txt", "text/export_units.txt",
             "unit_models/battle_models.modeldb")


def fresh_dest():
    root = Path(tempfile.mkdtemp(prefix="ut_dest_"))
    data = root / "data"
    (data / "text").mkdir(parents=True)
    (data / "unit_models").mkdir(parents=True)
    for rel in DEST_RELS:
        shutil.copy2(DST_MOD / "data" / rel, data / rel)
    return root


src = Mod(SRC_MOD)


def pick_units():
    """A source unit with models to give, and a same-kind destination unit."""
    dst_probe = Mod(DST_MOD)
    dst_by_kind = {}
    for u in dst_probe.edu.units:
        if u.officers and u.armour_ug_models and not u.is_eop:
            dst_by_kind.setdefault(u.kind(), u)
    for u in src.edu.units:
        if not (u.soldier_model and u.officers and u.armour_ug_models):
            continue
        if u.mount or u.engine or u.mounted_engine:
            continue                       # keep the case simple: plain infantry
        other = dst_by_kind.get(u.kind())
        if other is not None and other.type != u.type:
            return u.type, other.type
    raise SystemExit("no comparable unit pair found in the installed mods")


def fields(unit):
    """{field key: value} of a parsed unit's block (repeats keep the last)."""
    return {k.split("#")[0]: v for k, v in edu.block_fields(unit.raw)}


UNIT, TARGET = pick_units()
print(f"source unit {UNIT!r} ({SRC_MOD.name})  ->  replaces {TARGET!r} ({DST_MOD.name})")

dest_root = fresh_dest()
dest = Mod(dest_root)
before = dest.edu.by_type()[TARGET]
before_count = len(dest.edu.units)
before_index = [u.type for u in dest.edu.units].index(TARGET)
before_loc = (dest_root / "data/text/export_units.txt").read_bytes()
src_unit = src.edu.by_type()[UNIT]
print(f"  replaced unit: soldier={before.soldier_model!r} officers={before.officers} "
      f"ug={before.armour_ug_models}")
print(f"  incoming     : soldier={src_unit.soldier_model!r} officers={src_unit.officers} "
      f"ug={src_unit.armour_ug_models}")

# ---- 1) plan ----------------------------------------------------------------
opts = TransferOptions(mode="replace", replace_type=TARGET)
plan = plan_transfer(src, UNIT, dest, opts)
check("no base error", not plan.base_error)
check("no option error", not plan.option_error)
check("replace_type recorded", plan.replace_type == TARGET)
check("resolves to the replaced unit's type", plan.resolved_type == TARGET)
check("resolves to the replaced unit's dictionary", plan.resolved_dict == before.dictionary)
check("no unit-name conflict to settle", plan.unit_conflict is False)
check("adds no unit to the destination", plan.dest_new_units == 0)
check("no icons planned by default", not plan.icon_files)
check("bmdb texture factions follow the replaced unit",
      set(plan.texture_factions) == set(before.ownership))
check("summary says REPLACING", "REPLACING" in plan.summary())

# ---- 2) apply ---------------------------------------------------------------
rec = apply_transfer(plan)
after = edu.parse_file(dest_root / "data/export_descr_unit.txt")
by_type = after.by_type()
check("unit count unchanged", len(after.units) == before_count)
check("replaced unit still present under its own type", TARGET in by_type)
check("source unit type NOT added", UNIT not in by_type or UNIT == TARGET)
check("block kept its position in the file",
      [u.type for u in after.units].index(TARGET) == before_index)

new = by_type[TARGET]
final = {m: plan.model_renames.get(m, m) for m in src_unit.model_names()}
check("dictionary unchanged", new.dictionary == before.dictionary)
check("ownership unchanged", new.ownership == before.ownership)
check("stats stay the replaced unit's", new.stat_pri == before.stat_pri
      and fields(new)["stat_mental"] == fields(before)["stat_mental"])
check("attributes stay the replaced unit's", new.attributes == before.attributes)
check("soldier model is the transferred unit's",
      new.soldier_model.lower() == final[src_unit.soldier_model.lower()])
check("officers are the transferred unit's",
      [o.lower() for o in new.officers] == [final[o.lower()] for o in src_unit.officers])
check("armour upgrade models are the transferred unit's",
      [m.lower() for m in new.armour_ug_models]
      == [final[m.lower()] for m in src_unit.armour_ug_models])
check("localisation untouched",
      (dest_root / "data/text/export_units.txt").read_bytes() == before_loc)
check("no ui/ folder written at all", not (dest_root / "data/ui").exists())

# ---- 3) undo ----------------------------------------------------------------
undo(rec["id"])
check("undo restores the EDU byte-for-byte",
      (dest_root / "data/export_descr_unit.txt").read_bytes()
      == (DST_MOD / "data/export_descr_unit.txt").read_bytes())
shutil.rmtree(dest_root, ignore_errors=True)

# ---- 4) keeping the officer / upgrade groups --------------------------------
dest_root = fresh_dest()
dest = Mod(dest_root)
plan = plan_transfer(src, UNIT, dest,
                     TransferOptions(mode="replace", replace_type=TARGET,
                                     officer_from="base", upgrade_from="base"))
check("kept groups recorded", set(plan.base_field_groups) >= {"officer", "armour_ug_models"})
apply_transfer(plan)
new = edu.parse_file(dest_root / "data/export_descr_unit.txt").by_type()[TARGET]
check("officers kept from the replaced unit", new.officers == before.officers)
check("armour upgrade models kept from the replaced unit",
      new.armour_ug_models == before.armour_ug_models)
check("soldier still swapped for the transferred unit's",
      new.soldier_model.lower() != before.soldier_model.lower())
shutil.rmtree(dest_root, ignore_errors=True)

# ---- 5) importing the unit card + one stat (a B button) ---------------------
dest_root = fresh_dest()
dest = Mod(dest_root)
src_pri = ", ".join(src_unit.stat_pri)
plan = plan_transfer(src, UNIT, dest,
                     TransferOptions(mode="replace", replace_type=TARGET,
                                     import_card=True,
                                     field_overrides={"stat_pri": src_pri}))
card_rels = [rel for _abs, rel in plan.icon_files]
check("card planned, info card not",
      bool(card_rels) and all(r.startswith("ui/units/") for r in card_rels))
check("card lands under the REPLACED unit's dictionary",
      all(Path(r).stem == "#" + before.dictionary for r in card_rels))
check("card copied into the replaced unit's faction folders",
      {Path(r).parent.name for r in card_rels} >= {f for f in before.ownership
                                                   if f != "slave"})
apply_transfer(plan)
new = edu.parse_file(dest_root / "data/export_descr_unit.txt").by_type()[TARGET]
check("overridden stat_pri came from the source unit", new.stat_pri == src_unit.stat_pri)
check("un-overridden stat_mental still the replaced unit's",
      fields(new)["stat_mental"] == fields(before)["stat_mental"])
check("card file written", any((dest_root / "data" / r).exists() for r in card_rels))
shutil.rmtree(dest_root, ignore_errors=True)

# ---- 6) refusals ------------------------------------------------------------
dest_root = fresh_dest()
dest = Mod(dest_root)
mismatch = next((u.type for u in dest.edu.units if u.kind() != src_unit.kind()), "")
plan = plan_transfer(src, UNIT, dest,
                     TransferOptions(mode="replace", replace_type=mismatch))
check("a different unit kind is refused", "type mismatch" in plan.base_error)
plan = plan_transfer(src, UNIT, dest, TransferOptions(mode="replace"))
check("no target chosen is refused", bool(plan.base_error))
plan = plan_transfer(src, UNIT, dest,
                     TransferOptions(mode="replace", replace_type="no such unit"))
check("an unknown target is refused", "not found" in plan.base_error)
shutil.rmtree(dest_root, ignore_errors=True)

shutil.rmtree(cfg, ignore_errors=True)
print("\n" + ("ALL PASSED" if all(ok) else "SOME FAILED"))
sys.exit(0 if all(ok) else 1)
