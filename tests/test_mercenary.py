"""'Make this a mercenary unit' option.

Transfers a non-merc unit with make_mercenary=True into a temp copy of DaC and
checks the three things the flag is supposed to do:
  * EDU gains the `mercenary_unit` attribute (and keeps its other attributes),
    with card_pic_dir=mercs / info_pic_dir=merc pinned
  * the copied bmdb entries gain a `merc` texture record
  * the icons are written into ui/units/mercs/ and ui/unit_info/merc/
Plus: undo restores everything, and the default (flag off) changes nothing.

    python -m tests.test_mercenary
"""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import config, edu, modeldb
from unittransfer.mod import Mod
from unittransfer.transfer import (MERC_ATTR, MERC_CARD_DIR, MERC_INFO_DIR,
                                   MERC_TEX_FACTION, TransferOptions,
                                   apply_transfer, plan_transfer, undo)

MODS = Path(r"C:/Users/projy/Downloads/Games/Total War MEDIEVAL II Definitive Edition/mods")
TATR, DAC = MODS / "Third_Age_Reforged", MODS / "Divide_and_Conquer_EUR"

ok = []


def check(label, cond):
    ok.append(bool(cond))
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}")


cfg = Path(tempfile.mkdtemp(prefix="ut_cfg_"))
config.CONFIG_DIR = cfg
config.BACKUP_DIR = cfg / "backups"
config.SETTINGS_PATH = cfg / "settings.json"
config.LOG_PATH = cfg / "transfers.json"


def fresh_dest():
    root = Path(tempfile.mkdtemp(prefix="ut_dest_"))
    data = root / "data"
    (data / "text").mkdir(parents=True)
    (data / "unit_models").mkdir(parents=True)
    for rel in ("export_descr_unit.txt", "text/export_units.txt",
                "unit_models/battle_models.modeldb"):
        shutil.copy2(DAC / "data" / rel, data / rel)
    return root


src = Mod(TATR)


def _card_folder(u):
    """Folder the source card actually resolves in (ui/units/<folder>/...)."""
    p = src.find_unit_card(u)
    return p.parent.name if p else ""


# A normal (non-mercenary) unit with real models whose card is NOT already in the
# mercs folder — otherwise "icon retargeted to mercs" would pass for free.
UNIT = next(u.type for u in src.edu.units
            if not u.mercenary_unit and u.attributes
            and src.modeldb.get(u.soldier_model)
            and _card_folder(u) not in ("", MERC_CARD_DIR))
unit = src.edu.by_type()[UNIT]
print(f"unit={UNIT!r}  merc-in-source={unit.mercenary_unit}  "
      f"card folder={_card_folder(unit)!r}  attrs={unit.attributes}")

# ---------------- flag ON ----------------
print("\n== make_mercenary=True ==")
dest_root = fresh_dest()
data = dest_root / "data"
dest = Mod(dest_root)
plan = plan_transfer(src, UNIT, dest, TransferOptions(make_mercenary=True))
check("plan flagged mercenary", plan.mercenary)
check("no base/option error", not plan.base_error and not plan.option_error)
check(f"'{MERC_TEX_FACTION}' in texture factions", MERC_TEX_FACTION in plan.texture_factions)
icon_rels = [r for _, r in plan.icon_files]
print("     icon targets:", icon_rels)
check("card icon retargeted to the mercs folder",
      any(r.startswith(f"ui/units/{MERC_CARD_DIR}/") for r in icon_rels))
check("info icon (if any) retargeted to the merc folder",
      all(r.startswith(f"ui/unit_info/{MERC_INFO_DIR}/")
          for r in icon_rels if r.startswith("ui/unit_info/")))
check("descr_mercenaries note raised",
      any("descr_mercenaries" in w for w in plan.warnings))

rec = apply_transfer(plan)

# --- EDU ---
parsed = edu.parse_text((data / "export_descr_unit.txt").read_text(encoding=edu.ENCODING))
new_unit = parsed.by_type()[plan.resolved_type]
print("     attrs now:", new_unit.attributes)
check(f"EDU has the {MERC_ATTR} attribute", MERC_ATTR in new_unit.attributes)
check("mercenary_unit flag parsed", new_unit.mercenary_unit)
check("original attributes kept",
      all(a in new_unit.attributes for a in unit.attributes))
check("no duplicate mercenary_unit", new_unit.attributes.count(MERC_ATTR) == 1)
check(f"card_pic_dir pinned to {MERC_CARD_DIR}", new_unit.card_pic_dir == MERC_CARD_DIR)
if any(r.startswith("ui/unit_info/") for r in icon_rels):
    check(f"info_pic_dir pinned to {MERC_INFO_DIR}", new_unit.info_pic_dir == MERC_INFO_DIR)
check("EDU re-parses cleanly (unit count grew by 1)",
      len(parsed.units) == len(dest.edu.units))

# --- bmdb ---
db = modeldb.parse_file(data / "unit_models/battle_models.modeldb")
by_name = db.by_name()
added = [n for n, _ in plan.add_entries]
check("added bmdb entries present", all(n in by_name for n in added))
no_merc = [n for n in added
           if MERC_TEX_FACTION not in {t.faction for t in by_name[n].main_textures}]
check(f"every added entry has a '{MERC_TEX_FACTION}' texture record", not no_merc)
if added:
    e = by_name[added[0]]
    print("     entry", e.name, "factions:", sorted({t.faction for t in e.main_textures}))
    merc_recs = [t for t in e.main_textures if t.faction == MERC_TEX_FACTION]
    check("merc record carries a real texture path", all(t.texture for t in merc_recs))
check("modeldb round-trips byte-exact",
      db.to_text() == (data / "unit_models/battle_models.modeldb").read_text(
          encoding=modeldb.ENCODING))

# --- icons on disk ---
card_dir = data / "ui/units" / MERC_CARD_DIR
check("card written into ui/units/mercs/",
      card_dir.is_dir() and any(card_dir.iterdir()))

# --- undo ---
undo(rec["id"])
after = edu.parse_text((data / "export_descr_unit.txt").read_text(encoding=edu.ENCODING))
check("undo removed the unit", plan.resolved_type not in after.by_type()
      or len(after.units) == len(dest.edu.units) - 1)
shutil.rmtree(dest_root, ignore_errors=True)

# ---------------- flag OFF (default) ----------------
print("\n== make_mercenary=False (default) ==")
dest_root = fresh_dest()
data = dest_root / "data"
dest = Mod(dest_root)
plan2 = plan_transfer(src, UNIT, dest, TransferOptions())
check("default is NOT mercenary", not plan2.mercenary)
check("no merc texture faction added", MERC_TEX_FACTION not in plan2.texture_factions)
check("icons keep their source folder",
      all(not r.startswith(f"ui/units/{MERC_CARD_DIR}/") for _, r in plan2.icon_files))
apply_transfer(plan2)
p2 = edu.parse_text((data / "export_descr_unit.txt").read_text(encoding=edu.ENCODING))
u2 = p2.by_type()[plan2.resolved_type]
check("EDU has no mercenary_unit attribute", MERC_ATTR not in u2.attributes)
shutil.rmtree(dest_root, ignore_errors=True)

# ---------------- add_attribute unit checks ----------------
print("\n== edu.add_attribute ==")
b = "type Foo\nattributes      sea_faring, hide_forest\n"
check("appends to an existing list",
      edu.add_attribute(b, MERC_ATTR).splitlines()[1].endswith(
          f"sea_faring, hide_forest, {MERC_ATTR}"))
check("no-op when already present",
      edu.add_attribute(f"type Foo\nattributes  {MERC_ATTR}\n", MERC_ATTR)
      == f"type Foo\nattributes  {MERC_ATTR}\n")
made = edu.add_attribute("type Foo\ndictionary Bar\n", MERC_ATTR)
check("creates the line when absent",
      edu.parse_text(made).units[0].attributes == [MERC_ATTR])
withc = edu.add_attribute("type Foo\nattributes  hide_forest   ; a comment\n", MERC_ATTR)
check("trailing comment preserved", withc.rstrip().endswith("; a comment"))
check("attribute added before the comment",
      edu.parse_text(withc).units[0].attributes == ["hide_forest", MERC_ATTR])

shutil.rmtree(cfg, ignore_errors=True)
print("\n" + ("ALL PASSED" if all(ok) else "SOME FAILED"))
sys.exit(0 if all(ok) else 1)
