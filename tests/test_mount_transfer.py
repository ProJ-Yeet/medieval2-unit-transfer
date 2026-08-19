"""Mounted-unit transfer: descr_mount.txt entry + the mount's modeldb entry.

A unit's EDU `mount` names a block in descr_mount.txt whose `model` names a
battle_models.modeldb entry. Copying only the EDU left a dangling mount
reference, so the unit never appeared in game. This covers all three cases:
  * mount absent in destination      -> block appended, model copied
  * mount present & identical        -> reused, nothing written
  * mount present but different      -> renamed, EDU repointed at the new name
Uses temp config + temp dest so the real mods are never touched.
"""
import shutil, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import config, edu, modeldb, mounts
from unittransfer import keyblock as kb
from unittransfer.mod import Mod
from unittransfer.transfer import TransferOptions, plan_transfer, apply_transfer, undo

MODS = Path(r"C:/Users/projy/Downloads/Games/Total War MEDIEVAL II Definitive Edition/mods")
TATR, DAC = MODS / "Third_Age_Reforged", MODS / "Divide_and_Conquer_EUR"

ok = []
def check(label, cond):
    ok.append(bool(cond)); print(f"  [{'OK ' if cond else 'FAIL'}] {label}")

cfg = Path(tempfile.mkdtemp(prefix="ut_cfg_"))
config.CONFIG_DIR = cfg; config.BACKUP_DIR = cfg / "backups"
config.SETTINGS_PATH = cfg / "settings.json"; config.LOG_PATH = cfg / "transfers.json"

REL = ("export_descr_unit.txt", "text/export_units.txt",
       "unit_models/battle_models.modeldb", "descr_mount.txt")

def make_dest():
    root = Path(tempfile.mkdtemp(prefix="ut_dest_"))
    (root / "data" / "text").mkdir(parents=True)
    (root / "data" / "unit_models").mkdir(parents=True)
    for rel in REL:
        shutil.copy2(DAC / "data" / rel, root / "data" / rel)
    return root

src = Mod(TATR)

# ---------- A: mount MISSING in destination -> must be added ----------
print("\n=== A: mount absent in destination ===")
dest_root = make_dest()
dm = Mod(dest_root).mount_file.by_type()
unit = next(u for u in src.edu.units if u.mount and u.mount not in dm)
print(f"unit={unit.type!r}  mount={unit.mount!r}  model={src.mount_model(unit.mount)!r}")
mpath = dest_root / "data" / "descr_mount.txt"
orig_mount_bytes = mpath.read_bytes()

plan = plan_transfer(src, unit.type, Mod(dest_root), TransferOptions())
check("plan says mount is ADDED", plan.mount_action == "add")
rec = apply_transfer(plan)

after = Mod(dest_root)
mt = after.mount_file.get(unit.mount)
check("mount block now present in destination descr_mount.txt", mt is not None)
check("descr_mount.txt still parses + round-trips",
      after.mount_file.to_text() == kb.read_text(mpath, mounts.ENCODING))
model_name = (mt.model or "").lower() if mt else ""
check("mount block keeps a model reference", bool(model_name))
check("that model exists in the destination modeldb",
      after.modeldb.get(model_name) is not None)
# the EDU must point at a mount that actually exists now
new_unit = after.edu.units[-1]
check("EDU mount value resolves in destination descr_mount.txt",
      after.mount_file.get(new_unit.mount) is not None)
print(f"     EDU mount={new_unit.mount!r} -> model={model_name!r}")

undo(rec["id"])
check("undo restored descr_mount.txt byte-exact", mpath.read_bytes() == orig_mount_bytes)
shutil.rmtree(dest_root, ignore_errors=True)

# ---------- B: mount PRESENT and identical -> reused ----------
print("\n=== B: mount already in destination ===")
dest_root = make_dest()
d = Mod(dest_root)
same = None
for u in src.edu.units:
    if not u.mount:
        continue
    a, b = src.mount_def(u.mount), d.mount_def(u.mount)
    if a is not None and b is not None and a.content_equals(b):
        same = u
        break
if same is None:
    print("  (no identical shared mount found — skipped)")
else:
    print(f"unit={same.type!r}  mount={same.mount!r}")
    mpath = dest_root / "data" / "descr_mount.txt"
    before = mpath.read_bytes()
    p = plan_transfer(src, same.type, Mod(dest_root), TransferOptions())
    check("plan says mount is REUSED", p.mount_action == "reuse")
    apply_transfer(p)
    check("descr_mount.txt untouched when reusing", mpath.read_bytes() == before)
shutil.rmtree(dest_root, ignore_errors=True)

# ---------- C: mount name clashes with different stats -> renamed ----------
print("\n=== C: mount name clash, different definition ===")
dest_root = make_dest()
d = Mod(dest_root)
diff = None
for u in src.edu.units:
    if not u.mount:
        continue
    a, b = src.mount_def(u.mount), d.mount_def(u.mount)
    if a is not None and b is not None and not a.content_equals(b):
        diff = u
        break
if diff is None:
    print("  (no clashing mount found — skipped)")
else:
    print(f"unit={diff.type!r}  mount={diff.mount!r}")
    p = plan_transfer(src, diff.type, Mod(dest_root), TransferOptions())
    check("plan says mount is RENAMED", p.mount_action == "rename")
    check("renamed to a new name", p.mount_name != diff.mount)
    apply_transfer(p)
    after = Mod(dest_root)
    check("renamed mount present in destination", after.mount_file.get(p.mount_name) is not None)
    check("original destination mount still intact",
          after.mount_file.get(diff.mount) is not None)
    nu = after.edu.units[-1]
    check("EDU repointed at the renamed mount", nu.mount == p.mount_name)
    check("EDU mount resolves in descr_mount.txt",
          after.mount_file.get(nu.mount) is not None)
    print(f"     EDU mount={nu.mount!r}")
shutil.rmtree(dest_root, ignore_errors=True)

shutil.rmtree(cfg, ignore_errors=True)
print("\n" + ("ALL PASSED" if all(ok) else "SOME FAILED"))
sys.exit(0 if all(ok) else 1)
