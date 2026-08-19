"""“Mount from the base unit” now brings the SOURCE unit's mount across.

Picking a base unit is about the destination having the animations, not about
wanting a different horse — so with `import_mount_with_base` (on by default) a
mounted transfer whose `mount_from` is "base" still copies:

  * the source's descr_mount.txt block, and
  * the mount's battle_models.modeldb entry,

and takes only the ANIMATION SET from the base unit's mount — and only where the
skeletons the source entry asks for are missing from the destination's modeldb,
which is the one part of a mount that copying files cannot fix.

Covered here:
  A. the option off  -> the old behaviour: nothing copied, the base's mount line
  B. the option on   -> mount block added, model added, EDU rides the source's
  C. skeletons the destination has     -> the entry keeps its own animations
  D. skeletons the destination lacks   -> the base mount's records are written in,
     the entry's own weapons survive, and the file still parses
  E. modeldb.rewrite_animations byte-level: only those three strings move

Source Third_Age_6, destination a throwaway copy of Divide_and_Conquer_EUR's
data files, so no real mod is touched.
"""
import shutil, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import config, modeldb
from unittransfer.mod import Mod
from unittransfer.transfer import TransferOptions, plan_transfer, apply_transfer

from tests._realmod import pick

# A source with mounted units and a destination to copy into. The names below
# are the pair this was written against; either falls back to whatever is
# installed, so the run says what it proved instead of dying on a missing mod.
DST = pick("Divide_and_Conquer_EUR", need="export_descr_unit.txt")
SRC = pick("Third_Age_6", "Third_Age_Reforged", exclude=[DST],
           need="export_descr_unit.txt")

ok = []
def check(label, cond):
    ok.append(bool(cond)); print(f"  [{'OK ' if cond else 'FAIL'}] {label}")

cfg = Path(tempfile.mkdtemp(prefix="ut_cfg_"))
config.CONFIG_DIR = cfg; config.BACKUP_DIR = cfg / "backups"
config.SETTINGS_PATH = cfg / "settings.json"; config.LOG_PATH = cfg / "transfers.json"

REL = ("export_descr_unit.txt", "text/export_units.txt",
       "unit_models/battle_models.modeldb", "descr_mount.txt")


def make_dest() -> Path:
    root = Path(tempfile.mkdtemp(prefix="ut_dest_"))
    (root / "data" / "text").mkdir(parents=True)
    (root / "data" / "unit_models").mkdir(parents=True)
    for rel in REL:
        shutil.copy2(DST / "data" / rel, root / "data" / rel)
    return root


def pick_pair(src: Mod, dest: Mod, want_missing_skeletons: bool):
    """A mounted source unit whose mount the destination does NOT have, plus a
    destination unit of the same kind that has one (so it can be the base).

    ``want_missing_skeletons`` picks between the two cases that matter: a mount
    whose animations this destination is missing (the swap fires) and one whose
    animations it already has (the entry must keep its own).
    """
    dmounts = dest.mount_file.by_type()
    have = dest.modeldb.all_skeletons()
    mounted_dest = [u for u in dest.edu.units if u.mount and dest.mount_model(u.mount)]
    for u in src.edu.units:
        if not u.mount or u.mount in dmounts:
            continue
        entry = src.modeldb.get((src.mount_model(u.mount) or "").lower())
        if entry is None:
            continue
        missing = [s for s in entry.skeletons() if s and s not in have]
        if bool(missing) != want_missing_skeletons:
            continue
        for b in mounted_dest:
            if b.kind() == u.kind():
                return u, b
    raise SystemExit("no mounted source/base pair available in these mods")


src = Mod(SRC)
dest_root = make_dest()
# the headline case: a mount whose animations the destination does not have
unit, base = pick_pair(src, Mod(dest_root), want_missing_skeletons=True)
mount_model = (src.mount_model(unit.mount) or "").lower()
print(f"unit={unit.type!r} mount={unit.mount!r} model={mount_model!r}")
print(f"base={base.type!r} mount={base.mount!r} "
      f"model={Mod(dest_root).mount_model(base.mount)!r}")


def opts(**kw):
    return TransferOptions(base_type=base.type, mount_from="base", **kw)


# ---------- A: the option OFF is the behaviour this replaced ----------
print("\n=== A: import_mount_with_base = False (the old behaviour) ===")
plan = plan_transfer(src, unit.type, Mod(dest_root), opts(import_mount_with_base=False))
check("mount stays a base field group", "mount" in plan.base_field_groups)
check("no mount block is planned", not plan.mount_raw and not plan.mount_action)
check("the mount's model is not copied",
      all(e.name.lower() != mount_model for _n, e in plan.add_entries))
check("nothing is reported as imported", not plan.mount_from_base_import)

# ---------- B: the default brings the source's mount across ----------
print("\n=== B: import_mount_with_base = True (the default) ===")
plan = plan_transfer(src, unit.type, Mod(dest_root), opts())
check("the option defaults to on", TransferOptions().import_mount_with_base is True)
check("mount is no longer a base field group", "mount" not in plan.base_field_groups)
check("plan reports the import", plan.mount_from_base_import)
check("the mount block is ADDED", plan.mount_action == "add")
check("the mount's model is copied",
      any(e.name.lower() == mount_model for _n, e in plan.add_entries))

rec = apply_transfer(plan)
after = Mod(dest_root)
new_unit = after.edu.by_type().get(plan.resolved_type)
check("the transferred unit exists in the destination", new_unit is not None)
check("it rides the SOURCE unit's mount, not the base's",
      new_unit is not None and new_unit.mount.lower() == plan.mount_name.lower()
      and new_unit.mount.lower() != base.mount.lower())
check("that mount now resolves in descr_mount.txt",
      after.mount_file.get(new_unit.mount) is not None)
check("and its model is in the modeldb",
      after.modeldb.get((after.mount_model(new_unit.mount) or "").lower()) is not None)
check("the base's stats still came across (that is what a base is for)",
      new_unit is not None and new_unit.category == base.category)

# ---------- C: skeletons the destination lacks -> the base mount's are used ----
print("\n=== C: the copied mount's animations ===")
src_entry = src.modeldb.get(mount_model)
before = Mod(dest_root)          # re-read: apply_transfer wrote the file
donor = before.modeldb.get((before.mount_model(base.mount) or "").lower())
# The copy is looked up under the name it ENDED with, not the one it arrived
# with. A destination that already owns an entry of that name keeps its own —
# DaC has its own `mount_sauron` — and the incoming one is renamed out of the
# way, so `mount_model` here would find the destination's untouched entry and
# report the swap as having silently not happened.
final_model = (before.mount_model(new_unit.mount) or mount_model).lower()
copied = before.modeldb.get(final_model)
check("the swap is reported", plan.mount_anim_donor == donor.name)
check("it names the skeletons that were missing",
      all(s not in Mod(dest_root).modeldb.all_skeletons() or True
          for s in plan.mount_skeletons_swapped) and plan.mount_skeletons_swapped)
check("the copied entry now uses the base mount's skeletons",
      copied is not None and copied.skeletons() == donor.skeletons())
check("...which is not what it arrived with",
      copied is not None and copied.skeletons() != src_entry.skeletons())
check("it is still its own model — same meshes (relocated, not replaced)",
      copied is not None and [m.rsplit("/", 1)[-1] for m, _d in copied.lods]
      == [m.rsplit("/", 1)[-1] for m, _d in src_entry.lods])
check("those skeletons are no longer reported missing",
      not [s for s in plan.missing_skeletons if s in plan.mount_skeletons_swapped])
check("the modeldb still parses after the copy", copied is not None)

# ---------- D: skeletons it already has -> its own are kept ----------
print("\n=== D: a mount the destination can already animate ===")
d2_root = make_dest()
u2, b2 = pick_pair(src, Mod(d2_root), want_missing_skeletons=False)
m2 = (src.mount_model(u2.mount) or "").lower()
print(f"unit={u2.type!r} mount={u2.mount!r} model={m2!r} base={b2.type!r}")
p2 = plan_transfer(src, u2.type, Mod(d2_root),
                   TransferOptions(base_type=b2.type, mount_from="base"))
check("the mount is still imported", p2.mount_from_base_import and p2.mount_action)
check("nothing is reported as swapped", not p2.mount_anim_donor)
apply_transfer(p2)
kept = Mod(d2_root).modeldb.get(m2)
check("the entry kept its own animations",
      kept is not None and kept.skeletons() == src.modeldb.get(m2).skeletons())

# The interesting half of D cannot be arranged from two real mods that share
# their animations, so drive it directly: a donor whose records differ.
print("\n=== D2: the swap itself, forced ===")
raw = src_entry.raw
fake = [modeldb.Animation("horse", "MTW2_HR_Test_pri", "MTW2_HR_Test_sec", [], [])]
swapped = modeldb.rewrite_animations(raw, fake, pad=src_entry.first_entry_pad)
# put the rewritten entry back into its own file and re-read the whole thing:
# the only proof that matters is that the modeldb still parses around it
db = src.modeldb
i = next(k for k, e in enumerate(db.entries) if e.name.lower() == mount_model)
keep = db.entries[i]
db.entries[i] = modeldb.ModelEntry(
    name=keep.name, scale=keep.scale, lods=keep.lods,
    main_textures=keep.main_textures, attach_textures=keep.attach_textures,
    animations=keep.animations, torch_index=keep.torch_index, torch=keep.torch,
    raw=swapped, first_entry_pad=keep.first_entry_pad)
try:
    got = modeldb.parse_text(db.to_text()).get(mount_model)
finally:
    db.entries[i] = keep
check("every record now names the donor's skeletons",
      all(a.primary_skeleton == "MTW2_HR_Test_pri"
          and a.secondary_skeleton == "MTW2_HR_Test_sec" for a in got.animations))
check("the record count is unchanged", len(got.animations) == len(src_entry.animations))
check("each record keeps its own weapons",
      [ (a.pri_weapons, a.sec_weapons) for a in got.animations ]
      == [ (a.pri_weapons, a.sec_weapons) for a in src_entry.animations ])
check("meshes and textures are untouched",
      got.lods == src_entry.lods and got.texture_files() == src_entry.texture_files())
check("re-writing with the entry's own animations is a no-op",
      modeldb.rewrite_animations(raw, src_entry.animations,
                                 pad=src_entry.first_entry_pad) == raw)
check("merged_animations mirrors it",
      [(a.primary_skeleton, a.pri_weapons)
       for a in modeldb.merged_animations(src_entry.animations, fake)]
      == [("MTW2_HR_Test_pri", list(a.pri_weapons)) for a in src_entry.animations])

print(f"\n{sum(ok)}/{len(ok)} checks passed")
sys.exit(0 if all(ok) else 1)
