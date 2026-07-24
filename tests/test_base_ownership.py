"""Base-unit transfer fixes: bmdb texture ownership, EDU spacing, no stray tail.

Reproduces the reported case (Dismounted Dunedain Knights from Third_Age_Reforged
into Divide_and_Conquer_EUR using Citadel Guard as the stat base) and checks:
  * the copied bmdb entries gain a texture record for every faction the base owns
    (previously 'sicily' etc. had no skin, so the unit didn't import correctly)
  * the appended EDU unit is separated by exactly two blank lines
  * base fields the unit lacked land INSIDE the block, not dangling at the bottom
Uses temp config + temp dest so the real mods are never touched.
"""
import shutil, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import config, edu, modeldb
from unittransfer.mod import Mod
from unittransfer.transfer import TransferOptions, plan_transfer, apply_transfer

MODS = Path(r"C:/Users/projy/Downloads/Games/Total War MEDIEVAL II Definitive Edition/mods")
TATR, DAC = MODS / "Third_Age_Reforged", MODS / "Divide_and_Conquer_EUR"
UNIT, BASE = "Dismounted Dunedain Knights", "Citadel Guard"

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
base_unit = dest.edu.by_type()[BASE]
unit = src.edu.by_type()[UNIT]
print(f"unit={UNIT!r} ({unit.category}) base={BASE!r} ({base_unit.category})")
print("base ownership:", base_unit.ownership)

plan = plan_transfer(src, UNIT, dest, TransferOptions(base_type=BASE))
check("plan has no base error", not plan.base_error)
check("texture factions recorded", set(plan.texture_factions) == set(base_unit.ownership))
apply_transfer(plan)

# ---- 1) bmdb: every faction the base owns must now have a texture ----
db = modeldb.parse_file(data / "unit_models/battle_models.modeldb")
by_name = db.by_name()
added = [n for n, _ in plan.add_entries]
check("added entries present", all(n in by_name for n in added))
missing_any = []
for n in added:
    facs = {t.faction for t in by_name[n].main_textures}
    for f in base_unit.ownership:
        if f not in facs:
            missing_any.append((n, f))
check("every base faction has a main texture", not missing_any)
if missing_any:
    print("     missing:", missing_any[:5])
sample = by_name[added[0]]
print("     entry", sample.name, "factions:", sorted({t.faction for t in sample.main_textures}))
check("cloned records carry a real texture path",
      all(t.texture for t in sample.main_textures if t.faction in base_unit.ownership))
check("modeldb re-parses + round-trips",
      db.to_text() == (data / "unit_models/battle_models.modeldb").read_text(encoding=modeldb.ENCODING))

# ---- 2) EDU spacing + no stray trailing fields ----
text = (data / "export_descr_unit.txt").read_text(encoding=edu.ENCODING)
idx = text.rindex("\ntype ")            # start of the appended unit block
before = text[:idx + 1]
check("exactly two blank lines before the appended unit", before.endswith("\n\n\n"))
check("not three+ blank lines", not before.endswith("\n\n\n\n"))

parsed = edu.parse_text(text)
new_unit = parsed.units[-1]
# NB: compare against the RESOLVED name — the destination may already contain the
# unit (e.g. from an earlier real transfer), in which case it is renamed.
check(f"appended unit parses as {plan.resolved_type!r}", new_unit.type == plan.resolved_type)
check("ownership inherited from base", set(new_unit.ownership) == set(base_unit.ownership))
# base-only fields must land in their proper slot, not be appended at the bottom
keys = [edu.line_key(l) for l in new_unit.raw.splitlines() if edu.line_key(l)]
def directly_after(a, b):
    return a in keys and b in keys and keys.index(b) == keys.index(a) + 1
check("accent sits directly after voice_type", directly_after("voice_type", "accent"))
check("era 2 sits directly after era 1", directly_after("era 1", "era 2"))
check("block does not end on a base-only field",
      keys[-1] not in ("accent", "era 2", "mount_effect"))

# nothing may follow an internal blank line — that's what the stray tail looked like
lines = new_unit.raw.splitlines()
blank_seen = False
stray = []
for ln in lines:
    if not ln.strip():
        blank_seen = True
    elif blank_seen:
        stray.append(ln.strip())
check("no field lines after an internal blank line (no trailing accent/era)", not stray)
if stray:
    print("     stray:", stray[:5])

shutil.rmtree(dest_root, ignore_errors=True); shutil.rmtree(cfg, ignore_errors=True)
print("\n" + ("ALL PASSED" if all(ok) else "SOME FAILED"))
sys.exit(0 if all(ok) else 1)
