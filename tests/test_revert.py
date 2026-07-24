"""Focused test for transfer.revert_to — staged 'revert to this stage'.

Applies 3 transfers to a temp dest, snapshots state after #2, applies #3, then
reverts to #2 and checks the mod is byte-exact back to the post-#2 snapshot.
Uses temp config + temp dest so the real mods/config are never touched.
"""
import shutil, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import config
from unittransfer.mod import Mod
from unittransfer.transfer import TransferOptions, plan_transfer, apply_transfer, revert_to

MODS = Path(r"C:/Users/projy/Downloads/Games/Total War MEDIEVAL II Definitive Edition/mods")
TATR, DAC = MODS / "Third_Age_Reforged", MODS / "Divide_and_Conquer_EUR"

ok = []
def check(label, cond):
    ok.append(cond); print(f"  [{'OK ' if cond else 'FAIL'}] {label}")

# temp config
cfg = Path(tempfile.mkdtemp(prefix="ut_cfg_"))
config.CONFIG_DIR = cfg; config.BACKUP_DIR = cfg / "backups"
config.SETTINGS_PATH = cfg / "settings.json"; config.LOG_PATH = cfg / "transfers.json"

# temp dest (3 DB files from DaC)
dest_root = Path(tempfile.mkdtemp(prefix="ut_dest_"))
data = dest_root / "data"
(data / "text").mkdir(parents=True); (data / "unit_models").mkdir(parents=True)
shutil.copy2(DAC / "data/export_descr_unit.txt", data / "export_descr_unit.txt")
shutil.copy2(DAC / "data/text/export_units.txt", data / "text/export_units.txt")
shutil.copy2(DAC / "data/unit_models/battle_models.modeldb", data / "unit_models/battle_models.modeldb")

src = Mod(TATR)

def fresh_dest():
    return Mod(dest_root)

# pick 3 distinct transferable infantry units
dest0 = fresh_dest()
picks = []
for u in src.edu.units:
    if (u.category == "infantry" and not u.mount and u.type not in dest0.edu.by_type()
            and all(src.modeldb.get(m) for m in u.model_names())):
        picks.append(u.type)
    if len(picks) == 3:
        break
print("units:", picks)

def snapshot():
    return {p.relative_to(data).as_posix(): p.read_bytes()
            for p in data.rglob("*") if p.is_file()}

# apply #1, #2
ids = []
for t in picks[:2]:
    plan = plan_transfer(src, t, fresh_dest(), TransferOptions())
    ids.append(apply_transfer(plan)["id"])

snap_after2 = snapshot()
edu_after2 = (data / "export_descr_unit.txt").read_bytes()

# apply #3
plan3 = plan_transfer(src, picks[2], fresh_dest(), TransferOptions())
id3 = apply_transfer(plan3)["id"]
check("unit #3 present in dest EDU after apply", picks[2] in fresh_dest().edu.by_type())
check("state changed after #3", snapshot() != snap_after2)

# revert to stage #2
res = revert_to(ids[1])
print("revert result:", res)
check("revert undid exactly 1 transfer (#3)", res["count"] == 1)
check("revert undone_ids == [id3]", res["undone_ids"] == [id3])

# verify byte-exact back to post-#2 snapshot
now = snapshot()
check("file SET matches post-#2 snapshot", set(now) == set(snap_after2))
check("every file byte-exact vs post-#2", all(now.get(k) == v for k, v in snap_after2.items()))
check("EDU byte-exact vs post-#2", (data / "export_descr_unit.txt").read_bytes() == edu_after2)
check("unit #3 removed from EDU", picks[2] not in fresh_dest().edu.by_type())
check("units #1 & #2 still present", all(p in fresh_dest().edu.by_type() for p in picks[:2]))

# log state
log = config.load_log()
by_id = {e["id"]: e for e in log}
check("#3 marked undone in log", by_id[id3]["undone"] is True)
check("#1 & #2 NOT undone", not by_id[ids[0]]["undone"] and not by_id[ids[1]]["undone"])

# cleanup
shutil.rmtree(dest_root, ignore_errors=True); shutil.rmtree(cfg, ignore_errors=True)
print("\n" + ("ALL PASSED" if all(ok) else "SOME FAILED"))
sys.exit(0 if all(ok) else 1)
