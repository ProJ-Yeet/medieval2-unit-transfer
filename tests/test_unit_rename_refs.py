"""Renaming a unit's `type` follows it into every other file that names it.

An EDU `type` is just a string, and recruitment, the campaigns, the voice bank
and the mod's Lua all refer to the unit by it. The editor used to rename the
block and warn that everything else was the user's problem; now it rewrites them
in the same save (and backs them up in the same record, so one Undo puts the lot
back).

Two halves:
  * a hand-built mod with every file shape that matters, so the awkward cases can
    actually be arranged — a name that is the tail of a LONGER unit's name, a
    name inside a longer identifier, a differing-case spelling;
  * the same rename against real files copied out of Third_Age_6 / DaC, to prove
    the scan reaches a real mod's export_descr_buildings.txt, its campaign folder
    and its .lua scripts, and that undo restores them byte-for-byte.
"""
import shutil, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import config, edit, unitrefs
from unittransfer.mod import Mod
from unittransfer.transfer import undo

MODS = Path(r"C:/Users/projy/Downloads/Games/Total War MEDIEVAL II Definitive Edition/mods")
REAL = MODS / "Third_Age_6"

ok = []
def check(label, cond):
    ok.append(bool(cond)); print(f"  [{'OK ' if cond else 'FAIL'}] {label}")

cfg = Path(tempfile.mkdtemp(prefix="ut_cfg_"))
config.CONFIG_DIR = cfg; config.BACKUP_DIR = cfg / "backups"
config.SETTINGS_PATH = cfg / "settings.json"; config.LOG_PATH = cfg / "transfers.json"

EDU = """\
type             Ent Catapult
dictionary       Ent_Catapult
category         siege
class            missile
soldier          ents, 8, 0, 1
attributes       sea_faring
stat_health      1, 0
ownership        slave

type             Catapult
dictionary       Catapult
category         siege
class            missile
soldier          catapult, 8, 0, 1
attributes       sea_faring
stat_health      1, 0
ownership        slave

type             Peasants
dictionary       Peasants
category         infantry
class            light
soldier          peasant, 60, 0, 1
stat_health      1, 0
ownership        slave
"""

EDB = """\
building core_building
{
    levels village town
    {
        village requires factions { slave, }
        {
            capability
            {
                recruit_pool "Catapult"  1   0.5   4  0  requires factions { slave, }
                recruit_pool "Ent Catapult"  1   0.5   4  0  requires factions { slave, }
                recruit_pool "Peasants"  1   0.5   4  0  requires factions { slave, }
            }
        }
    }
}
"""

STRAT = """\
faction	slave, comfortable religion catholic
character	Bob, general, age 20, x 100, y 100
unit		Catapult				exp 0 armour 0 weapon_lvl 0
unit		Ent Catapult			exp 0 armour 0 weapon_lvl 0
unit		Peasants				exp 0 armour 0 weapon_lvl 0
"""

SCRIPT = """\
script
	; a commented-out spawn is still a reference the modder means to keep
	; spawn_army faction slave, unit Catapult exp 0
	monitor_event FactionTurnStart
		spawn_army
			faction slave
			character	Bob, general, age 20, x 100, y 100
			unit		Catapult				exp 0 armour 0 weapon_lvl 0
			unit		Ent Catapult			exp 0 armour 0 weapon_lvl 0
		end
	end_monitor
end_script
"""

LUA = """\
-- the extender does this from Lua, where no .txt records it
local u = M2TWEOP.getEduEntryByType("Catapult")
local other = M2TWEOP.getEduEntryByType("Ent Catapult")
local nope = "Catapult_Heavy"          -- a longer identifier, not this unit
local case = "catapult"                -- different case: reported, not rewritten
"""

VOICE = """\
accent Eastern
    class Light
        unit Catapult
        unit Ent Catapult
"""


def make_mod() -> Path:
    root = Path(tempfile.mkdtemp(prefix="ut_refs_"))
    data = root / "data"
    (data / "text").mkdir(parents=True)
    (data / "unit_models").mkdir(parents=True)
    camp = data / "world" / "maps" / "campaign" / "imperial_campaign"
    camp.mkdir(parents=True)
    (root / "eopData" / "scripts").mkdir(parents=True)
    (data / "export_descr_unit.txt").write_text(EDU, encoding="latin-1")
    (data / "text" / "export_units.txt").write_text(
        "\ufeff{Catapult}Catapult\r\n", encoding="utf-16-le")
    shutil.copy2(REAL / "data" / "unit_models" / "battle_models.modeldb",
                 data / "unit_models" / "battle_models.modeldb")
    (data / "export_descr_buildings.txt").write_text(EDB, encoding="latin-1")
    (data / "export_descr_sounds_units_voice.txt").write_text(VOICE, encoding="latin-1")
    (camp / "descr_strat.txt").write_text(STRAT, encoding="latin-1")
    (camp / "campaign_script.txt").write_text(SCRIPT, encoding="latin-1")
    (root / "eopData" / "scripts" / "spawn.lua").write_text(LUA, encoding="latin-1")
    return root


# ---------- A: what the scan finds ----------
print("\n=== A: finding the references ===")
root = make_mod()
mod = Mod(root)
res = unitrefs.rename_refs(mod, "Catapult", "Trebuchet")
files = {f for f, _n in res.counts()}
check("export_descr_buildings.txt is reached",
      "data/export_descr_buildings.txt" in files)
check("the campaign's descr_strat.txt is reached",
      any(f.endswith("descr_strat.txt") for f in files))
check("the campaign script is reached",
      any(f.endswith("campaign_script.txt") for f in files))
check("the voice bank is reached",
      "data/export_descr_sounds_units_voice.txt" in files)
check("the .lua script is reached (and it is outside data/)",
      any(f.endswith("spawn.lua") for f in files))
check("export_descr_unit.txt is NOT touched here (the block edit owns it)",
      not any("export_descr_unit" in f for f in files))
check("a differing-case spelling is reported, not rewritten",
      len(res.case_refs) == 1 and res.case_refs[0].rel.endswith("spawn.lua"))

new_edb = res.texts[root / "data" / "export_descr_buildings.txt"]
check("its own recruit_pool is renamed", '"Trebuchet"' in new_edb)
check("the LONGER unit's name is left intact — “Ent Catapult” is another unit",
      '"Ent Catapult"' in new_edb and '"Ent Trebuchet"' not in new_edb)
check("the third unit is untouched", '"Peasants"' in new_edb)

new_lua = res.texts[root / "eopData" / "scripts" / "spawn.lua"]
check("Lua: the reference is renamed", 'getEduEntryByType("Trebuchet")' in new_lua)
check("Lua: a longer identifier is not", '"Catapult_Heavy"' in new_lua)
check("Lua: the other unit survives", '"Ent Catapult"' in new_lua)
check("Lua: the differing-case spelling is left alone", '"catapult"' in new_lua)

new_script = res.texts[root / "data" / "world" / "maps" / "campaign"
                       / "imperial_campaign" / "campaign_script.txt"]
check("a commented-out spawn is renamed too (it is code the mod keeps)",
      "; spawn_army faction slave, unit Trebuchet" in new_script)
check("the campaign script's other unit is untouched",
      "unit\t\tEnt Catapult" in new_script)

# ---------- B: the rename through the editor ----------
print("\n=== B: plan + apply + undo ===")
plan = edit.plan_edit(mod, edit.request_from_dict(
    {"unit": "Catapult", "new_type": "Trebuchet"}))
check("no errors", not plan.errors)
check("the plan lists the other files", bool(plan.ref_counts))
check("the change line says how many and where",
      any("reference(s) to 'Catapult' rewritten" in c for c in plan.changes))
check("the old 'update them by hand' warning is gone",
      not any("must be updated by hand" in w for w in plan.warnings))
check("the differing-case spelling is warned about",
      any("different capitalisation" in w for w in plan.warnings))

before = {p: p.read_bytes() for p in unitrefs.scan_paths(mod)}
rec = edit.apply_edit(plan)
edb_after = (root / "data" / "export_descr_buildings.txt").read_text(encoding="latin-1")
check("the EDB on disk now recruits the new name", '"Trebuchet"' in edb_after)
check("...and no longer the old one", '"Catapult"  1' not in edb_after)
check("the other unit's pool is still there", '"Ent Catapult"' in edb_after)
strat_after = (root / "data" / "world" / "maps" / "campaign" / "imperial_campaign"
               / "descr_strat.txt").read_text(encoding="latin-1")
check("the starting army follows the rename", "unit\t\tTrebuchet" in strat_after)
lua_after = (root / "eopData" / "scripts" / "spawn.lua").read_text(encoding="latin-1")
check("the Lua script follows the rename", '"Trebuchet"' in lua_after)
check("the EDU block itself was renamed",
      "type             Trebuchet" in
      (root / "data" / "export_descr_unit.txt").read_text(encoding="latin-1"))

undo(rec["id"])
after = {p: p.read_bytes() for p in unitrefs.scan_paths(Mod(root))}
changed = [p.name for p in before if before[p] != after.get(p)]
check(f"undo restores every rewritten file byte-for-byte ({changed})", not changed)

# ---------- C: a real mod's files ----------
print("\n=== C: against real mod files ===")
real = Mod(REAL)
paths = unitrefs.scan_paths(real)
names = {p.name.lower() for p in paths}
check(f"{len(paths)} files scanned in {real.name}", len(paths) > 20)
check("export_descr_buildings.txt is among them", "export_descr_buildings.txt" in names)
check("a campaign_script.txt is among them", "campaign_script.txt" in names)
check("descr_strat.txt is among them", "descr_strat.txt" in names)
check("some .lua is among them", any(n.endswith(".lua") for n in names))
check("export_descr_unit.txt is not", "export_descr_unit.txt" not in names)
check("data/text/ is not scanned (UTF-16, keyed by dictionary)",
      not any("text" in p.parts and p.name == "export_units.txt" for p in paths))

# a real type with real references, renamed and put straight back
sample = next((u.type for u in real.edu.units
               if unitrefs.rename_refs(real, u.type, u.type + "_x", paths=paths).refs),
              "")
check("a real unit type has references outside the EDU", bool(sample))
if sample:
    r = unitrefs.rename_refs(real, sample, sample + "_x", paths=paths)
    print(f"  {sample!r}: {len(r.refs)} ref(s) in {[f for f, _n in r.counts()]}")
    back = {p: t.replace(sample + "_x", sample) for p, t in r.texts.items()}
    check("rewriting and reversing it is byte-identical",
          all(unitrefs._read(p) == t for p, t in back.items()))

print(f"\n{sum(ok)}/{len(ok)} checks passed")
sys.exit(0 if all(ok) else 1)
