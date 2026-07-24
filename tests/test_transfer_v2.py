"""Stage 4 validation: options, conflict resolution, bmdb dedup/rename, apply+undo.

Uses a TEMP destination mod (only its 3 DB files, copied from DaC) and a TEMP
config dir, so neither the real mods nor the project config are touched.

Run:  python -m tests.test_transfer_v2
"""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from unittransfer import config, edu, localization, modeldb  # noqa: E402
from unittransfer.mod import Mod  # noqa: E402
import unittransfer.transfer as T  # noqa: E402
from unittransfer.transfer import TransferOptions, plan_transfer, apply_transfer, undo  # noqa: E402

MODS = Path(r"C:/Users/projy/Downloads/Games/Total War MEDIEVAL II Definitive Edition/mods")
TATR = MODS / "Third_Age_Reforged"
DAC = MODS / "Divide_and_Conquer_EUR"

results = []
def check(label, cond):
    results.append(cond)
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}")
    return cond


def make_temp_dest(src_mod: Path) -> Path:
    """A minimal dest mod: just the 3 DB files copied from src_mod."""
    tmp = Path(tempfile.mkdtemp(prefix="ut_dest_"))
    data = tmp / "data"
    (data / "text").mkdir(parents=True)
    (data / "unit_models").mkdir(parents=True)
    shutil.copy2(src_mod / "data" / "export_descr_unit.txt", data / "export_descr_unit.txt")
    shutil.copy2(src_mod / "data" / "text" / "export_units.txt", data / "text" / "export_units.txt")
    shutil.copy2(src_mod / "data" / "unit_models" / "battle_models.modeldb",
                 data / "unit_models" / "battle_models.modeldb")
    return tmp


def use_temp_config():
    tmp = Path(tempfile.mkdtemp(prefix="ut_cfg_"))
    config.CONFIG_DIR = tmp
    config.BACKUP_DIR = tmp / "backups"
    config.SETTINGS_PATH = tmp / "settings.json"
    config.LOG_PATH = tmp / "transfers.json"
    return tmp


def main():
    use_temp_config()

    # ---------- A: TATR -> temp DaC, no conflict, include all, apply + undo ----------
    print("\n=== A: transfer + apply + undo (no conflict) ===")
    dest_root = make_temp_dest(DAC)
    src = Mod(TATR)
    dest = Mod(dest_root)
    unit_type = next(u.type for u in src.edu.units
                     if u.category == "infantry" and not u.mount
                     and u.type not in dest.edu.by_type()
                     and all(src.modeldb.get(m) for m in u.model_names()))
    orig_edu = (dest_root / "data" / "export_descr_unit.txt").read_bytes()
    orig_mdb = (dest_root / "data" / "unit_models" / "battle_models.modeldb").read_bytes()

    plan = plan_transfer(src, unit_type, dest, TransferOptions())
    print(plan.summary())
    rec = apply_transfer(plan)
    dest2 = Mod(dest_root)
    check("unit added to dest EDU", unit_type in dest2.edu.by_type())
    check("dest modeldb re-parses clean", dest2.modeldb.to_text() ==
          (dest_root / "data" / "unit_models" / "battle_models.modeldb").read_text(encoding=modeldb.ENCODING))
    check("added models present", all(dest2.modeldb.get(n) for n, _ in plan.add_entries))
    check("log record written + applied", config.load_log() and config.load_log()[-1]["applied"])

    undo(rec["id"])
    check("undo restored EDU byte-exact",
          (dest_root / "data" / "export_descr_unit.txt").read_bytes() == orig_edu)
    check("undo restored modeldb byte-exact",
          (dest_root / "data" / "unit_models" / "battle_models.modeldb").read_bytes() == orig_mdb)
    check("undo marked in log", config.load_log()[-1]["undone"] is True)
    shutil.rmtree(dest_root, ignore_errors=True)

    # ---------- B: exclude officers -> warning + officer models not added ----------
    print("\n=== B: exclude officers ===")
    dest_root = make_temp_dest(DAC)
    dest = Mod(dest_root)
    off_unit = next((u for u in src.edu.units
                     if u.officers and u.type not in dest.edu.by_type()
                     and all(src.modeldb.get(m) for m in u.model_names())), None)
    if off_unit:
        plan = plan_transfer(src, off_unit.type, dest,
                             TransferOptions(include_officers=False))
        added = {n for n, _ in plan.add_entries}
        officer_models = {o.lower() for o in off_unit.officers}
        check(f"officers excluded from add set ({off_unit.type})",
              not (officer_models & added))
        check("excluded secondaries reported", any(o in plan.excluded_secondaries for o in officer_models))
        check("warning present about excluded", any("excluded" in w for w in plan.warnings))
    else:
        check("found a unit with officers to test", False)
    shutil.rmtree(dest_root, ignore_errors=True)

    # ---------- C: unit conflict resolution (DaC -> temp DaC, same unit) ----------
    print("\n=== C: unit conflict overwrite/rename/skip ===")
    dest_root = make_temp_dest(DAC)
    dac = Mod(DAC)
    dest = Mod(dest_root)
    dup_type = dac.edu.units[0].type  # exists in dest (dest is a DaC copy)

    p_skip = plan_transfer(dac, dup_type, dest, TransferOptions(on_conflict="skip"))
    check("conflict skip -> skipped", p_skip.skipped)

    p_ren = plan_transfer(dac, dup_type, dest,
                          TransferOptions(on_conflict="rename", new_type="Zzz Renamed",
                                          new_dictionary="zzz_renamed"))
    check("conflict rename -> new resolved type", p_ren.resolved_type == "Zzz Renamed")
    rec = apply_transfer(p_ren)
    dest2 = Mod(dest_root)
    check("renamed unit present in dest EDU", "Zzz Renamed" in dest2.edu.by_type())
    check("renamed loc key present", dest2.loc.get("zzz_renamed") is not None)
    undo(rec["id"])
    shutil.rmtree(dest_root, ignore_errors=True)

    # ---------- D: bmdb dedup (DaC -> temp DaC) all models identical -> reuse ----------
    print("\n=== D: bmdb dedup (identical models reused) ===")
    dest_root = make_temp_dest(DAC)
    dest = Mod(dest_root)
    # a DaC unit whose models all already exist in dest (they do, dest is DaC) with identical content
    d_unit = next(u for u in dac.edu.units if u.model_names())
    plan = plan_transfer(dac, d_unit.type, dest, TransferOptions(on_conflict="overwrite"))
    reused = [a for a in plan.model_actions if a.action == "reuse_identical"]
    check(f"identical models reused not re-added ({d_unit.type}: {len(reused)} reused)",
          len(reused) == len(plan.model_actions) and len(plan.add_entries) == 0)
    shutil.rmtree(dest_root, ignore_errors=True)

    # ---------- E: bmdb rename (same name, different content) ----------
    print("\n=== E: bmdb rename on name collision with different content ===")
    dest_root = make_temp_dest(DAC)
    dest = Mod(dest_root)
    # pick a TATR unit; force a collision by injecting a differently-scaled dest entry
    e_unit = next(u for u in src.edu.units
                  if u.soldier_model and u.type not in dest.edu.by_type()
                  and src.modeldb.get(u.soldier_model.lower()))
    coll_name = e_unit.soldier_model.lower()
    # craft a dest modeldb that already has coll_name but with different content
    dmdb = dest.modeldb
    fake = modeldb.ModelEntry(name=coll_name, scale=9.9, lods=[("x_lod0.mesh", 6400)],
                              main_textures=[], attach_textures=[], animations=[],
                              torch_index=-1, torch=[0, 0, 0, 0, 0, 0],
                              raw="\n%d %s 9.9 1\n11 x_lod0.mesh 6400\n0\n0\n0\n-1 0 0 0 0 0 0\n"
                                  % (len(coll_name), coll_name))
    dmdb.entries.append(fake)
    (dest_root / "data" / "unit_models" / "battle_models.modeldb").write_text(
        dmdb.to_text(), encoding=modeldb.ENCODING)
    del dmdb.entries[-1]
    dest = Mod(dest_root)   # reparse with the injected collision
    plan = plan_transfer(src, e_unit.type, dest, TransferOptions())
    ren = [a for a in plan.model_actions if a.action == "rename" and a.source_name == coll_name]
    check(f"collision '{coll_name}' triggers rename", len(ren) == 1)
    if ren:
        newn = ren[0].final_name
        check("rename recorded in model_renames map", plan.model_renames.get(coll_name) == newn)
        # apply and confirm EDU soldier line now points to the renamed model
        rec = apply_transfer(plan)
        dest2 = Mod(dest_root)
        u2 = dest2.edu.by_type()[e_unit.type]
        check("EDU soldier ref updated to renamed model", u2.soldier_model.lower() == newn)
        check("renamed model entry present in dest modeldb", dest2.modeldb.get(newn) is not None)
        undo(rec["id"])
    shutil.rmtree(dest_root, ignore_errors=True)

    print("\n" + ("ALL PASSED" if all(results) else f"{results.count(False)} FAILED"))
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
