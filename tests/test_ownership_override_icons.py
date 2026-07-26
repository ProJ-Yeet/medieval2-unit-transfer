"""Ownership-override icon placement (no base template, no merc_icons).

Reported bug: overriding `ownership` via TransferOptions.field_overrides
(rather than via a base-unit template) changed the unit's faction, but the
copied unit card / info card icon was only ever copied under the SOURCE
faction's folder -- so in-game the icon vanished (the game looks under the
NEW ownership faction's ui/units folder). The fix copies the icon into every
faction the unit ends up owned by (plus the mercs/merc fallback), so no
*_pic_dir pin is needed at all -- each faction finds its own copy.
"""
import shutil, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import config, edu
from unittransfer.mod import Mod
from unittransfer.transfer import (MERC_CARD_DIR, MERC_INFO_DIR,
                                   TransferOptions, plan_transfer, apply_transfer)

MODS = Path(r"C:/Users/projy/Downloads/Games/Total War MEDIEVAL II Definitive Edition/mods")
TATR, DAC = MODS / "Third_Age_Reforged", MODS / "Divide_and_Conquer_EUR"
UNIT = "Umbar Heavy Spearmen"
NEW_OWNER = "byzantium"

ok = []
def check(label, cond):
    ok.append(bool(cond)); print(f"  [{'OK ' if cond else 'FAIL'}] {label}")

cfg = Path(tempfile.mkdtemp(prefix="ut_cfg_"))
config.CONFIG_DIR = cfg; config.BACKUP_DIR = cfg / "backups"
config.SETTINGS_PATH = cfg / "settings.json"; config.LOG_PATH = cfg / "transfers.json"

dest_root = Path(tempfile.mkdtemp(prefix="ut_dest_"))
data = dest_root / "data"
(data / "text").mkdir(parents=True); (data / "unit_models").mkdir(parents=True)
for rel in ("export_descr_unit.txt", "text/export_units.txt",
            "unit_models/battle_models.modeldb"):
    shutil.copy2(DAC / "data" / rel, data / rel)

src, dest = Mod(TATR), Mod(dest_root)
unit = src.edu.by_type()[UNIT]
card = src.find_unit_card(unit)
src_faction = card.relative_to(src.data).as_posix().split("/")[2]
print(f"unit={UNIT!r} source ownership={unit.ownership} icon folder={src_faction!r} "
      f"-> override ownership to {NEW_OWNER!r}")

opts = TransferOptions(field_overrides={"ownership": NEW_OWNER})
plan = plan_transfer(src, UNIT, dest, opts)
check("plan has no option error", not plan.option_error)
check("no *_pic_dir pin needed (icon copied straight into the new faction's folder)",
      not plan.icon_dir_overrides)
icon_rels = [r for _, r in plan.icon_files]
print("     icon targets:", icon_rels)
check(f"card copied into ui/units/{NEW_OWNER}/",
      any(r.startswith(f"ui/units/{NEW_OWNER}/") for r in icon_rels))
check("card ALSO copied into the mercs/ fallback folder",
      any(r.startswith(f"ui/units/{MERC_CARD_DIR}/") for r in icon_rels))
if any(r.startswith("ui/unit_info/") for r in icon_rels):
    check(f"info copied into ui/unit_info/{NEW_OWNER}/",
          any(r.startswith(f"ui/unit_info/{NEW_OWNER}/") for r in icon_rels))
    check("info ALSO copied into the merc/ fallback folder",
          any(r.startswith(f"ui/unit_info/{MERC_INFO_DIR}/") for r in icon_rels))

apply_transfer(plan)
text = (data / "export_descr_unit.txt").read_text(encoding=edu.ENCODING)
parsed = edu.parse_text(text)
new_unit = parsed.units[-1]
check(f"appended unit parses as {plan.resolved_type!r}", new_unit.type == plan.resolved_type)
check("ownership rewritten to the override", new_unit.ownership == [NEW_OWNER])
check("no card_pic_dir written into the EDU block", new_unit.card_pic_dir is None)
check("no info_pic_dir written into the EDU block", new_unit.info_pic_dir is None)
check(f"card actually landed on disk under ui/units/{NEW_OWNER}/",
      (data / "ui/units" / NEW_OWNER).is_dir() and any((data / "ui/units" / NEW_OWNER).iterdir()))

shutil.rmtree(dest_root, ignore_errors=True); shutil.rmtree(cfg, ignore_errors=True)
print("\n" + ("ALL PASSED" if all(ok) else "SOME FAILED"))
sys.exit(0 if all(ok) else 1)
