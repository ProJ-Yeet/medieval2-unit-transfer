"""Projectile transfer: descr_projectile.txt port + effect placeholdering.

Covers:
  * parser round-trip of descr_projectile.txt
  * a missile unit's projectile is ADDED, effects the dest lacks become the
    placeholder, physics lines are preserved, .cas model files are copied
  * a name collision RENAMES the projectile and repoints the EDU stat line
  * the effects-not-imported warning is raised
  * apply writes descr_projectile.txt and undo restores it byte-exact
  * a base-templated transfer does NOT port a projectile (stats come from base)

    python -m tests.test_projectiles
"""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import config, edu, projectiles
from unittransfer import keyblock as kb
from unittransfer.mod import Mod
from unittransfer.transfer import (TransferOptions, apply_transfer,
                                   plan_transfer, undo)
from unittransfer.projectiles import PLACEHOLDER

MODS = Path(r"C:/Users/projy/Downloads/Games/Total War MEDIEVAL II Definitive Edition/mods")
TATR, DAC = MODS / "Third_Age_Reforged", MODS / "Divide_and_Conquer_EUR"

# files a dest copy needs so apply + effect_sets work
DEST_FILES = ("export_descr_unit.txt", "text/export_units.txt",
              "unit_models/battle_models.modeldb", "descr_projectile.txt",
              "descr_effect_impacts.txt", "descr_arrow_trail_effects.txt",
              "descr_arrow_trail_custom_effects.txt", "descr_artillery_effects.txt")

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
    for rel in DEST_FILES:
        srcp = DAC / "data" / rel
        if srcp.exists():
            dstp = data / rel
            dstp.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(srcp, dstp)
    return root


src = Mod(TATR)

# ---- parser round-trip ----
print("== parser ==")
pf = src.projectile_file
check("parsed many projectiles", len(pf.projectiles) > 50)
check("descr_projectile round-trips byte-exact",
      pf.to_text() == kb.read_text(TATR / "data/descr_projectile.txt", projectiles.ENCODING))

# find an add-case: missile unit whose projectile is absent from DaC with >=1 effect
# the dest lacks (so the placeholder kicks in)
dac = Mod(DAC)
dac_names = {n.lower() for n in dac.projectile_file.by_name()}
UNIT = PROJ = None
for u in src.edu.units:
    for pn in u.projectiles():
        sp = src.projectile_def(pn)
        if sp and pn.lower() not in dac_names and sp.effects and \
           any(v.lower() not in dac.effect_sets for v in sp.effects.values()):
            UNIT, PROJ = u.type, pn
            break
    if UNIT:
        break
assert UNIT, "no add-case unit found"
sp = src.projectile_def(PROJ)
print(f"\n== add case: unit={UNIT!r} projectile={PROJ!r} "
      f"({len(sp.effects)} effects, {len(sp.models)} models) ==")

dest_root = fresh_dest()
data = dest_root / "data"
dest = Mod(dest_root)
plan = plan_transfer(src, UNIT, dest, TransferOptions())
acts = {n: (a, d) for n, a, d in plan.projectile_actions}
print("  projectile actions:", plan.projectile_actions)
check("projectile is ADDED", acts.get(PROJ, ("",))[0] == "add")
missing_effects = [v for v in sp.effects.values() if v.lower() not in dest.effect_sets]
check("some effects were blanked", plan.projectile_effects_blanked == len(missing_effects))
check("effects-not-imported warning raised",
      any("special effects are NOT imported" in w for w in plan.warnings))

apply_transfer(plan)

# descr_projectile.txt now has the projectile, with placeholdered effects
after = projectiles.parse_file(data / "descr_projectile.txt")
np = after.get(PROJ)
check("projectile written to dest descr_projectile.txt", np is not None)
if np:
    for k, v in np.effects.items():
        want_blank = sp.effects[k].lower() not in dest.effect_sets
        good = (v == PLACEHOLDER) if want_blank else (v.lower() == sp.effects[k].lower())
        if not good:
            print(f"     effect {k}: got {v!r} src {sp.effects[k]!r} want_blank={want_blank}")
        ok.append(good)
    print(f"  [{'OK ' if all(ok[-len(np.effects):]) else 'FAIL'}] every effect line correct "
          f"(kept if present in dest, else '{PLACEHOLDER}')")
    # physics preserved: pick a stat line that isn't an effect
    def field_of(block, key):
        for line in block.splitlines():
            p = line.split(";", 1)[0].split()
            if p and p[0] == key:
                return line.split(";", 1)[0].strip()
        return None
    for key in ("damage", "velocity", "min_angle"):
        if field_of(sp.raw, key):
            check(f"physics line '{key}' preserved",
                  field_of(np.raw, key) == field_of(sp.raw, key))
check("descr_projectile round-trips after write",
      after.to_text() == kb.read_text(data / "descr_projectile.txt", projectiles.ENCODING))
# .cas models copied
for rel in sp.models:
    check(f"projectile model copied: {rel}", (data / rel).exists())

# EDU stat line keeps the (unchanged) projectile name for the add case
eparsed = edu.parse_text((data / "export_descr_unit.txt").read_text(encoding=edu.ENCODING))
newu = eparsed.by_type()[plan.resolved_type]
check("EDU stat_pri still names the projectile", PROJ.lower() in [p.lower() for p in newu.projectiles()])

rec = plan_id = None
# ---- undo restores descr_projectile.txt ----
orig_proj = (DAC / "data/descr_projectile.txt").read_text(encoding=projectiles.ENCODING)
# re-plan+apply to get a record id, then undo
dest2root = fresh_dest()
d2 = Mod(dest2root)
p2 = plan_transfer(src, UNIT, d2, TransferOptions())
r2 = apply_transfer(p2)
undo(r2["id"])
restored = (dest2root / "data/descr_projectile.txt").read_text(encoding=projectiles.ENCODING)
check("undo restores descr_projectile.txt byte-exact", restored == orig_proj)
shutil.rmtree(dest2root, ignore_errors=True)

# ---- collision case: projectile exists in dest with different content -> rename ----
UNIT2 = PROJ2 = None
for u in src.edu.units:
    for pn in u.projectiles():
        sp2 = src.projectile_def(pn)
        dp = dac.projectile_file.get(pn)
        if sp2 and dp is not None and not dp.content_equals(sp2):
            UNIT2, PROJ2 = u.type, pn
            break
    if UNIT2:
        break
if UNIT2:
    print(f"\n== collision case: unit={UNIT2!r} projectile={PROJ2!r} ==")
    dr = fresh_dest()
    dd = Mod(dr)
    pl = plan_transfer(src, UNIT2, dd, TransferOptions())
    acts2 = {n: a for n, a, d in pl.projectile_actions}
    print("  actions:", pl.projectile_actions)
    check("colliding projectile RENAMED", acts2.get(PROJ2) == "rename")
    new_name = pl.projectile_renames.get(PROJ2.lower())
    check("rename recorded", bool(new_name) and new_name.lower() != PROJ2.lower())
    apply_transfer(pl)
    ep = edu.parse_text((dr / "data/export_descr_unit.txt").read_text(encoding=edu.ENCODING))
    nu = ep.by_type()[pl.resolved_type]
    check("EDU stat line repointed to the renamed projectile",
          new_name and new_name.lower() in [p.lower() for p in nu.projectiles()])
    af = projectiles.parse_file(dr / "data/descr_projectile.txt")
    check("renamed projectile present in dest", af.get(new_name) is not None)
    check("original dest projectile untouched",
          af.get(PROJ2).content_equals(dac.projectile_file.get(PROJ2)))
    shutil.rmtree(dr, ignore_errors=True)
else:
    print("  (no collision case found — skipped)")

# ---- base template does NOT port a projectile (stats come from base) ----
print("\n== base template skips projectile ==")
# a missile unit + a same-kind dest base
base_u = next((u for u in dac.edu.units if u.kind() == src.edu.by_type()[UNIT].kind()), None)
if base_u:
    dr = fresh_dest()
    dd = Mod(dr)
    pl = plan_transfer(src, UNIT, dd, TransferOptions(base_type=base_u.type))
    check("no projectile ported when a base supplies the stats",
          not pl.projectile_raws and not pl.projectile_actions)
    shutil.rmtree(dr, ignore_errors=True)

shutil.rmtree(dest_root, ignore_errors=True)
shutil.rmtree(cfg, ignore_errors=True)
print("\n" + ("ALL PASSED" if all(ok) else "SOME FAILED"))
sys.exit(0 if all(ok) else 1)
