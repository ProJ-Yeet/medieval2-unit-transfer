"""Ownership-override icon-folder pinning (no base template).

Reported bug: overriding `ownership` via TransferOptions.field_overrides
(rather than via a base-unit template) changed the unit's faction, but the
copied unit card / info card icons kept their SOURCE faction's *_pic_dir
lookup unpinned -- so in-game the icon vanished (game looks for it under the
new ownership faction's ui/units folder, but the file was only ever copied
under the source faction's folder). This mirrors the fix already in place
for the base-template case (test_base_ownership.py) and checks the same
pinning now also fires for a plain ownership override.
"""
import shutil, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import config, edu
from unittransfer.mod import Mod
from unittransfer.transfer import TransferOptions, plan_transfer, apply_transfer

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
check("icon_dir_overrides pins card_pic_dir to the source faction folder",
      plan.icon_dir_overrides.get("card_pic_dir") == src_faction)
check("icon_dir_overrides pins info_pic_dir to the source faction folder",
      plan.icon_dir_overrides.get("info_pic_dir") == src_faction)

apply_transfer(plan)
text = (data / "export_descr_unit.txt").read_text(encoding=edu.ENCODING)
parsed = edu.parse_text(text)
new_unit = parsed.units[-1]
check(f"appended unit parses as {plan.resolved_type!r}", new_unit.type == plan.resolved_type)
check("ownership rewritten to the override", new_unit.ownership == [NEW_OWNER])
check("card_pic_dir written into the EDU block", new_unit.card_pic_dir == src_faction)
check("info_pic_dir written into the EDU block", new_unit.info_pic_dir == src_faction)

shutil.rmtree(dest_root, ignore_errors=True); shutil.rmtree(cfg, ignore_errors=True)
print("\n" + ("ALL PASSED" if all(ok) else "SOME FAILED"))
sys.exit(0 if all(ok) else 1)
