"""Siege-engine transfer: descr_engines.txt + descr_engine_skeleton.txt + assets.

Covers:
  * byte-exact round-trip of descr_engines.txt / descr_engine_skeleton.txt (both mods)
  * engine block parsing: model groups, skeletons, file refs, attack_stat projectiles
  * texture extraction from a .mesh binary (the paths exist in NO text file)
  * a plan ADDS the engine block, its skeleton entries, its files and its baked textures
  * vanilla references (absent from the source) are reported, not copied — and the
    "destination overrides a vanilla file" case is flagged
  * a name collision RENAMES the engine and repoints the EDU `engine` field
  * apply writes all three engine files; undo restores them byte-exact
  * differing siege-engine files keep the DESTINATION's version by default
  * include_engine=False ports nothing
  * regression: `engine`/`mounted_engine` no longer leak into missing_models

    python -m tests.test_engines
"""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import config, edu, engines
from unittransfer.mod import Mod
from unittransfer.transfer import (TransferOptions, apply_transfer,
                                   plan_transfer, undo)

MODS = Path(r"C:/Users/projy/Downloads/Games/Total War MEDIEVAL II Definitive Edition/mods")
TATR, DAC = MODS / "Third_Age_Reforged", MODS / "Divide_and_Conquer_EUR"

# files a dest copy needs so apply works end-to-end
DEST_FILES = ("export_descr_unit.txt", "text/export_units.txt",
              "unit_models/battle_models.modeldb", "descr_projectile.txt",
              "descr_mount.txt", "descr_engines.txt", "descr_mounted_engines.txt",
              "descr_engine_skeleton.txt", "descr_effect_impacts.txt",
              "descr_arrow_trail_effects.txt", "descr_arrow_trail_custom_effects.txt",
              "descr_artillery_effects.txt")

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
    """A DaC-shaped destination with only the DB files (assets copied on demand)."""
    root = Path(tempfile.mkdtemp(prefix="ut_dest_"))
    data = root / "data"
    data.mkdir(parents=True)
    for rel in DEST_FILES:
        srcp = DAC / "data" / rel
        if srcp.exists():
            dstp = data / rel
            dstp.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(srcp, dstp)
    return root


src, dac = Mod(TATR), Mod(DAC)

# ---- parsers ------------------------------------------------------------
print("== parsers ==")
for mod in (src, dac):
    ef = mod.engine_file
    check(f"{mod.name}: descr_engines parsed ({len(ef.engines)} blocks)",
          len(ef.engines) > 50)
    check(f"{mod.name}: descr_engines round-trips byte-exact",
          ef.to_text() == mod.descr_engines_path.read_text(encoding=engines.ENCODING))
    sf = mod.engine_skeleton_file
    check(f"{mod.name}: descr_engine_skeleton parsed ({len(sf.skeletons)})",
          len(sf.skeletons) > 20)
    check(f"{mod.name}: descr_engine_skeleton round-trips byte-exact",
          sf.to_text() == mod.descr_engine_skeleton_path.read_text(encoding=engines.ENCODING))
    check(f"{mod.name}: descr_mounted_engines round-trips byte-exact",
          mod.mounted_engine_file.to_text() ==
          mod.descr_mounted_engines_path.read_text(encoding=engines.ENCODING))

# a known engine, checked field by field
hb = src.engine_file.get("huge_bombard")
check("huge_bombard found", hb is not None)
check("huge_bombard has 3 model groups (normal/dying/dead)",
      [g.name for g in hb.groups] == ["normal", "dying", "dead"])
check("huge_bombard skeletons = normal + dying (dead has none)",
      hb.skeletons() == ["huge_bombard", "huge_bombard_dying"])
check("huge_bombard reference_points parsed",
      hb.reference_points == "siege_engines/siege_huge_bombard.modelReferencePoints")
check("huge_bombard normal group has 3 mesh LODs", len(hb.groups[0].meshes) == 3)
check("huge_bombard bone map + collision parsed",
      hb.groups[0].bone_map == "siege_engines/BoneMaps/huge_bombard.xml"
      and hb.groups[0].collision.lower().endswith("siege_huge_bombard_collision.cas"))
check("pathfinding_data 'none' is not treated as a file", hb.pathfinding_data == "")
refs = [r.lower() for r in hb.file_refs()]
# 5 distinct files: refpoints, 2 bone maps, 1 collision (shared by all 3 groups),
# 1 mesh (all LODs and all groups point at the same file here)
check("file_refs covers refpoints+bonemaps+collision+meshes, deduped",
      refs == ["siege_engines/siege_huge_bombard.modelreferencepoints",
               "siege_engines/bonemaps/huge_bombard.xml",
               "siege_engines/collision_models/siege_huge_bombard_collision.cas",
               "siege_engines/siege_dragoncannon_lod0.mesh",
               "siege_engines/bonemaps/huge_bombard_destroy.xml"])

# Both test mods happen to give every culture's tower its own type name, but the
# format allows one type to span several culture/variant blocks — a lookup has to
# return all of them or the engine only half-exists in the destination.
multi = engines.parse_text(
    "type\tsiege_tower\nculture\tdwarves\nvariant\tsmall\n"
    "engine_model_group\tnormal\nengine_mesh\tsiege_engines/a.mesh, max\n\n"
    "type\tsiege_tower\nculture\telves\nvariant\tlarge\n"
    "engine_model_group\tnormal\nengine_mesh\tsiege_engines/b.mesh, max\n")
check("one engine type can span several culture/variant blocks",
      len(multi.get_all("siege_tower")) == 2)
check("those blocks keep their own culture/variant/mesh",
      [(e.culture, e.variant, e.groups[0].meshes)
       for e in multi.get_all("siege_tower")]
      == [("dwarves", "small", ["siege_engines/a.mesh"]),
          ("elves", "large", ["siege_engines/b.mesh"])])
check("lookup is case-insensitive", len(multi.get_all("SIEGE_Tower")) == 2)

# attack_stat -> projectile
gb = next((e for e in src.engine_file.engines if e.attack_stats), None)
check("attack_stat projectiles extracted",
      gb is not None and all(p.lower() != "no" for p in gb.projectiles()))

# engine skeleton anims resolve to data-relative CAS/evt paths
sk = src.engine_skeleton_def("huge_bombard")
files = sk.anim_files()
check("engine skeleton anim files are data-relative",
      files and all(f.startswith("animations/engine/") for f in files))
check("-evt: files picked up too", any(f.lower().endswith(".evt") for f in files))
check("every named engine animation exists on disk",
      all((TATR / "data" / f).exists() for f in files))

# ---- texture extraction from the mesh binary ----------------------------
print("\n== mesh texture extraction ==")
mesh = TATR / "data/siege_engines/erebor_ballista_lod0.mesh"
texs = engines.mesh_textures(mesh)
check("textures read out of erebor_ballista_lod0.mesh",
      texs == ["siege_engines/textures/erebor_ballista.texture",
               "siege_engines/textures/template_att_norm.texture",
               "OverlayTextures/dirt_02.texture"])
check("a missing mesh yields [] rather than raising",
      engines.mesh_textures(TATR / "data/siege_engines/nope.mesh") == [])
# every siege mesh in the mod should yield textures (the format is uniform)
meshes = sorted((TATR / "data/siege_engines").rglob("*.mesh"))
no_tex = [m.name for m in meshes if not engines.mesh_textures(m)]
check(f"all {len(meshes)} engine meshes yield texture paths", not no_tex)

# ---- add case -----------------------------------------------------------
print("\n== add case: 'Erebor Ballista' (engine erebor_ballista) ==")
dr = fresh_dest()
dest = Mod(dr)
plan = plan_transfer(src, "Erebor Ballista", dest, TransferOptions())
acts = {n: (a, d) for n, a, d in plan.engine_actions}
check("engine ADDED", acts.get("erebor_ballista", ("",))[0] == "add")
check("engine block queued for descr_engines.txt", len(plan.engine_raws) == 1)
eassets = [r.lower() for r in plan.engine_assets]
check("engine mesh copied",
      "siege_engines/erebor_ballista_lod0.mesh" in eassets)
check("BAKED textures copied (named in no text file)",
      "siege_engines/textures/erebor_ballista.texture" in eassets)
check("reference_points file copied",
      any(r.endswith(".modelreferencepoints") for r in eassets))
check("engine files are in asset_files too",
      all(r in [rel.lower() for _, rel in plan.asset_files] for r in eassets))
check("vanilla references reported, not copied", len(plan.engine_vanilla_refs) >= 3)
check("no engine file was queued that the source lacks",
      all((TATR / "data" / r).exists() for r in plan.engine_assets))
check("engine's projectile ported alongside the unit's",
      any(a[0].lower() == "isengard_ballista" for a in plan.projectile_actions))

# regression: engine names must not be reported as missing battle models
check("engine name does NOT leak into missing_models",
      "erebor_ballista" not in [m.lower() for m in plan.missing_models])

rec = apply_transfer(plan)
data = dr / "data"
after = engines.parse_file(data / "descr_engines.txt")
check("engine present in the destination descr_engines.txt",
      after.get("erebor_ballista") is not None)
check("destination descr_engines round-trips after write",
      after.to_text() == (data / "descr_engines.txt").read_text(encoding=engines.ENCODING))
check("copied engine files landed in the destination",
      all((data / r).exists() for r in plan.engine_assets))
check("destination engine blocks intact (count grew by exactly 1)",
      len(after.engines) == len(dac.engine_file.engines) + 1)

undo(rec["id"])
check("undo restores descr_engines.txt byte-exact",
      (data / "descr_engines.txt").read_bytes() ==
      (DAC / "data/descr_engines.txt").read_bytes())
check("undo removes the copied engine files",
      not any((data / r).exists() for r in plan.engine_assets))
shutil.rmtree(dr, ignore_errors=True)

# ---- destination-override detection -------------------------------------
print("\n== vanilla refs + destination override ==")
dr = fresh_dest()
# give the destination a file the engine references but the SOURCE does not have
over = "siege_engines/BoneMaps/Great_Bell_Tower_standard.xml"
p = dr / "data" / over
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text("<destination override/>")
plan = plan_transfer(src, "Crawlers_Tower", Mod(dr), TransferOptions())
check("source does NOT contain the overridden file",
      not (TATR / "data" / over).exists())
check("destination override flagged",
      over in plan.engine_dest_overrides)
check("override warning raised",
      any("ENGINE OVERRIDE WARNING" in w for w in plan.warnings))
check("the overridden file is NOT copied over",
      over.lower() not in [r.lower() for r in plan.engine_assets])
shutil.rmtree(dr, ignore_errors=True)

# ---- collision case: engine name exists in dest with different content ----
print("\n== collision case: 'khand launcher' (engine rocket_launcher) ==")
dr = fresh_dest()
dest = Mod(dr)
plan = plan_transfer(src, "khand launcher", dest, TransferOptions())
acts = {n: a for n, a, d in plan.engine_actions}
check("colliding engine RENAMED", acts.get("rocket_launcher") == "rename")
new_name = plan.engine_renames.get("engine")
check("rename recorded", bool(new_name) and new_name.lower() != "rocket_launcher")
rec = apply_transfer(plan)
data = dr / "data"
ep = edu.parse_text((data / "export_descr_unit.txt").read_text(encoding=edu.ENCODING))
check("EDU `engine` field repointed at the renamed engine",
      ep.by_type()[plan.resolved_type].engine == new_name)
af = engines.parse_file(data / "descr_engines.txt")
check("renamed engine present in destination", af.get(new_name) is not None)
check("destination's own rocket_launcher untouched",
      af.get("rocket_launcher").content_equals(dac.engine_file.get("rocket_launcher")))
undo(rec["id"])
shutil.rmtree(dr, ignore_errors=True)

# ---- engine file conflicts default to keeping the destination's ----------
print("\n== engine_conflict default = use_existing ==")
dr = fresh_dest()
shared = "siege_engines/textures/erebor_ballista.texture"
p = dr / "data" / shared
p.parent.mkdir(parents=True, exist_ok=True)
p.write_bytes(b"DESTINATION VERSION")
dest = Mod(dr)
plan = plan_transfer(src, "Erebor Ballista", dest, TransferOptions())
conf = {c.rel.lower(): c for c in plan.asset_conflicts}
check("differing engine file detected as an 'engine' conflict",
      conf.get(shared.lower()) is not None
      and conf[shared.lower()].kind == "engine"
      and not conf[shared.lower()].identical)
check("siege-engine conflict warning raised",
      any("SIEGE-ENGINE file(s) exist in the destination" in w for w in plan.warnings))
apply_transfer(plan)
check("destination's version kept (not overwritten)",
      (dr / "data" / shared).read_bytes() == b"DESTINATION VERSION")
shutil.rmtree(dr, ignore_errors=True)

dr = fresh_dest()
p = dr / "data" / shared
p.parent.mkdir(parents=True, exist_ok=True)
p.write_bytes(b"DESTINATION VERSION")
plan = plan_transfer(src, "Erebor Ballista", Mod(dr),
                     TransferOptions(engine_conflict="overwrite"))
rec = apply_transfer(plan)
check("engine_conflict='overwrite' replaces it",
      (dr / "data" / shared).read_bytes() == (TATR / "data" / shared).read_bytes())
undo(rec["id"])
check("undo restores the overwritten engine file",
      (dr / "data" / shared).read_bytes() == b"DESTINATION VERSION")
shutil.rmtree(dr, ignore_errors=True)

# ---- include_engine=False ----------------------------------------------
print("\n== include_engine=False ==")
dr = fresh_dest()
plan = plan_transfer(src, "Erebor Ballista", Mod(dr),
                     TransferOptions(include_engine=False))
check("nothing engine-related planned",
      not plan.engine_raws and not plan.engine_actions and not plan.engine_assets
      and not plan.engine_skeleton_raws)
shutil.rmtree(dr, ignore_errors=True)

# ---- mounted_engine -----------------------------------------------------
# resolved out of descr_mounted_engines.txt, written back to that file (not
# descr_engines.txt) and repointed via the EDU's `mounted_engine` field.
print("\n== mounted_engine ==")
dr = fresh_dest()
plan = plan_transfer(src, "Sauron Elephants2", Mod(dr), TransferOptions())
acts = {n: a for n, a, d in plan.engine_actions}
check("mounted_engine resolved from descr_mounted_engines.txt",
      acts.get("elephant_serpentine") in ("add", "rename", "reuse"))
check("its block goes to descr_mounted_engines.txt, not descr_engines.txt",
      len(plan.mounted_engine_raws) == 1 and not plan.engine_raws)
check("mounted_engine name does NOT leak into missing_models",
      "elephant_serpentine" not in [m.lower() for m in plan.missing_models])
if acts.get("elephant_serpentine") == "rename":
    new_me = plan.engine_renames.get("mounted_engine")
    rec = apply_transfer(plan)
    ep = edu.parse_text((dr / "data/export_descr_unit.txt").read_text(encoding=edu.ENCODING))
    check("EDU `mounted_engine` repointed at the renamed engine",
          ep.by_type()[plan.resolved_type].mounted_engine == new_me)
    mf = engines.parse_file(dr / "data/descr_mounted_engines.txt")
    check("renamed mounted engine written to descr_mounted_engines.txt",
          mf.get(new_me) is not None)
    check("descr_engines.txt untouched",
          (dr / "data/descr_engines.txt").read_bytes()
          == (DAC / "data/descr_engines.txt").read_bytes())
    undo(rec["id"])
    check("undo restores descr_mounted_engines.txt byte-exact",
          (dr / "data/descr_mounted_engines.txt").read_bytes()
          == (DAC / "data/descr_mounted_engines.txt").read_bytes())
shutil.rmtree(dr, ignore_errors=True)

# ---- every siege unit plans without raising ------------------------------
print("\n== all siege units plan cleanly ==")
dr = fresh_dest()
dest = Mod(dr)
siege = [u.type for u in src.edu.units if u.engine or u.mounted_engine]
bad = []
for ut in siege:
    try:
        pl = plan_transfer(src, ut, dest, TransferOptions())
        if pl.missing_models:
            bad.append(f"{ut}: missing_models={pl.missing_models}")
    except Exception as exc:                       # noqa: BLE001 - surfacing it is the point
        bad.append(f"{ut}: {exc!r}")
for b in bad:
    print("     ", b)
check(f"all {len(siege)} siege units plan with no bogus missing models", not bad)
shutil.rmtree(dr, ignore_errors=True)

shutil.rmtree(cfg, ignore_errors=True)
print(f"\n{sum(ok)}/{len(ok)} checks — " + ("ALL PASSED" if all(ok) else "SOME FAILED"))
sys.exit(0 if all(ok) else 1)
