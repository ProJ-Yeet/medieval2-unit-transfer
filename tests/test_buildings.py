"""Buildings mode: parse, edit and write data/export_descr_buildings.txt.

The EDB is the biggest hand-maintained file in a mod (Divide and Conquer's is
17.5k lines) and it is full of things a re-emitting parser destroys — trailing
``;ok old_pool=…`` comments on recruit_pool lines, mixed tabs and spaces, comma
separated ``levels`` lists. So the load-bearing checks here are:

  * every installed mod round-trips byte-for-byte through the parser
  * every level named in a ``levels`` line has a block, and vice versa
  * an edit is a SPLICE: only the lines that changed change, and re-saving an
    untouched level writes nothing at all
  * capabilities compare by meaning, not by text — re-sending
    ``1 0.135 3 0`` with different spacing is not an edit
  * apply writes the file, logs a backup manifest, and undo restores it exactly
  * a building rename rewrites text/export_buildings.txt with all three keys

    python -m tests.test_buildings
"""
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import buildings, config, localization
from unittransfer.mod import Mod
from unittransfer.transfer import undo

MODS = Path(r"C:/Users/projy/Downloads/Games/Total War MEDIEVAL II Definitive Edition/mods")
#: Every mod installed on this machine — the parser must cope with all of them.
CANDIDATES = ("Divide_and_Conquer_EUR", "Third_Age_6", "third_age_3")
#: The one edits are applied to (copied into a temp folder first, never in place).
EDIT_MOD = "Divide_and_Conquer_EUR"

ok = []


def check(label, cond):
    ok.append(bool(cond))
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}")


cfg = Path(tempfile.mkdtemp(prefix="ut_cfg_"))
config.CONFIG_DIR = cfg
config.BACKUP_DIR = cfg / "backups"
config.SETTINGS_PATH = cfg / "settings.json"
config.LOG_PATH = cfg / "transfers.json"

installed = [m for m in CANDIDATES if (MODS / m / "data").is_dir()]
if not installed:
    print(f"none of {CANDIDATES} is installed under {MODS} — nothing to test")
    sys.exit(0)

# ---- 1) parse every installed mod ------------------------------------------
print("\n1) parsing every installed EDB")
for name in installed:
    mod = Mod(MODS / name)
    if not mod.edb_path.exists():
        print(f"  [skip] {name} has no EDB")
        continue
    raw = mod.edb_path.read_text(encoding=buildings.ENCODING)
    edb = buildings.parse_text(raw)
    check(f"{name}: round-trips byte-for-byte", edb.to_text() == raw)
    check(f"{name}: found building lines", len(edb.buildings) > 0)
    check(f"{name}: no parse warnings", not edb.warnings)
    declared_ok = all(lv in [b.name for b in bl.blocks]
                      for bl in edb.buildings for lv in bl.levels)
    blocks_ok = all(b.name in bl.levels for bl in edb.buildings for b in bl.blocks)
    check(f"{name}: every declared level has a block, and vice versa",
          declared_ok and blocks_ok)
    pools = [p for bl in edb.buildings for b in bl.blocks for p in b.recruits]
    check(f"{name}: recruit pools parsed ({len(pools)})", len(pools) > 0)
    check(f"{name}: every pool has a unit and four numbers",
          all(p.unit and p.initial and p.per_turn and p.maximum and p.experience != ""
              for p in pools))
    # spans must nest: a capability block sits inside its level
    spans_ok = all(b.start < b.cap_span[0] <= b.cap_span[1] < b.end
                   for bl in edb.buildings for b in bl.blocks if b.cap_span != (0, 0))
    check(f"{name}: capability blocks sit inside their level", spans_ok)

# ---- 2) a copy to edit ------------------------------------------------------
print(f"\n2) editing a copy of {EDIT_MOD}")
src_root = MODS / EDIT_MOD
work = Path(tempfile.mkdtemp(prefix="ut_edb_")) / EDIT_MOD
(work / "data" / "text").mkdir(parents=True)
shutil.copy2(src_root / "data" / buildings.EDB_REL, work / "data" / buildings.EDB_REL)
for rel in (buildings.LOC_REL, "export_descr_unit.txt", "text/export_units.txt",
            # the ownership check needs to know which factions and cultures exist,
            # and the fix needs the battle models it would add textures to
            "descr_sm_factions.txt", "descr_cultures.txt", "text/expanded.txt",
            "unit_models/battle_models.modeldb"):
    src = src_root / "data" / rel
    if src.exists():
        (work / "data" / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, work / "data" / rel)

# A mod's cultures are its data/ui/<culture>/buildings folders, and the copy
# above brings no art across — recreate the folders (empty) so the per-culture
# name keys have the same culture list to work against as the real mod.
for c in buildings.cultures_of(Mod(src_root)):
    (work / "data" / "ui" / c / "buildings").mkdir(parents=True, exist_ok=True)

mod = Mod(work)
original = mod.edb_path.read_text(encoding=buildings.ENCODING)
edb = mod.edb

# pick a level that has recruit pools AND at least one plain capability, so the
# edit below can touch a pool, a scalar and a non-pool capability in one go
pairs = [(bl, b) for bl in edb.buildings for b in bl.blocks if b.recruits]
line, target = next(((bl, b) for bl, b in pairs
                     if len(b.capabilities) > len(b.recruits)), pairs[0])
print(f"  using {line.name} / {target.name} "
      f"({len(target.recruits)} pools, {len(target.capabilities)} capabilities)")

# ---- 3) re-saving an untouched level changes nothing -------------------------
print("\n3) a no-op save")


def level_payload(blk, **over):
    """What the page sends for one level: everything, unchanged unless overridden."""
    caps = [{"line": c.line, "keyword": c.keyword,
             # deliberately re-spaced, the way the browser rebuilds a pool line
             "args": " ".join(c.args.split()), "requires": c.requires, "delete": False}
            for c in blk.capabilities]
    out = {"name": blk.name, "settlement": blk.settlement, "requires": blk.requires,
           "scalars": dict(blk.scalars), "upgrades": list(blk.upgrades),
           "capabilities": caps}
    out.update(over)
    return out


plan = buildings.plan_edit(mod, {"line": line.name, "levels": [level_payload(target)]})
check("re-sending a level unchanged is not a change", not plan.changes)
check("…and rewrites nothing", not plan.edb_text and not plan.loc_text)
check("…even though the pool numbers were re-spaced",
      any("  " in c.args for c in target.recruits and target.capabilities))

# ---- 4) a real edit is a surgical splice ------------------------------------
print("\n4) a real edit")
pool_cap = next(c for c in target.capabilities if c.is_recruit)
pool = pool_cap.pool()
pool.per_turn, pool.maximum = "0.9", "7"
plain = next((c for c in target.capabilities if not c.is_recruit), None)
caps = [{"line": c.line, "keyword": c.keyword, "args": c.args,
         "requires": c.requires, "delete": False} for c in target.capabilities]
for c in caps:
    if c["line"] == pool_cap.line:
        c["args"] = pool.to_args()
if plain is not None:
    caps = [c for c in caps if c["line"] != plain.line] + \
           [{"line": plain.line, "keyword": plain.keyword, "args": plain.args,
             "requires": plain.requires, "delete": True}]
caps.append({"line": None, "keyword": "recruit_pool",
             "args": '"Peasant Militia"  1  0.5  2  0', "requires": "", "delete": False})

new_cost = str(int(target.scalars.get("cost", "100")) + 111)
payload = {"line": line.name,
           "levels": [level_payload(target, scalars={**target.scalars, "cost": new_cost},
                                    capabilities=caps)]}
plan = buildings.plan_edit(mod, payload)
check("the plan has exactly the four intended changes", len(plan.changes) == 4)
check("no errors or warnings", not plan.errors and not plan.warnings)
check("the EDB would be rewritten", bool(plan.edb_text))

old_lines = original.splitlines()
new_lines = plan.edb_text.splitlines()
# one capability added, one removed — so the file grows by one line only when
# there was no plain capability to delete
check("the file grows by the added line and shrinks by the removed one",
      len(new_lines) == len(old_lines) + 1 - (1 if plain is not None else 0))
# the added line shifts everything under it, so compare the untouched HEAD only
head = min(pool_cap.line, plain.line if plain else pool_cap.line)
check("nothing above the edited block moved",
      old_lines[:head] == new_lines[:head])
check("the pool line kept its trailing comment",
      pool_cap.comment == "" or pool_cap.comment in plan.edb_text)

reparsed = buildings.parse_text(plan.edb_text)
rblk = reparsed.get(line.name).level(target.name)
check("the result still parses", not reparsed.warnings)
check("cost was written", rblk.scalars.get("cost") == new_cost)
rpool = next((p for p in rblk.recruits if p.unit == pool.unit), None)
check("the pool's new rate is there", rpool and rpool.per_turn == "0.9" and rpool.maximum == "7")
check("the new unit was added",
      any(p.unit == "Peasant Militia" for p in rblk.recruits))
if plain is not None:
    check("the deleted capability is gone",
          not any(c.keyword == plain.keyword and c.args == plain.args
                  for c in rblk.capabilities))

# ---- 5) apply + undo --------------------------------------------------------
print("\n5) apply, then undo")
rec = buildings.apply_edit(plan)
after = mod.edb_path.read_text(encoding=buildings.ENCODING)
check("the file on disk changed", after != original)
check("the file on disk is the planned text", after == plan.edb_text)
check("a backup was recorded", buildings.EDB_REL in rec["manifest"]["backed_up"])
check("the backup file exists",
      (Path(rec["backup_root"]) / "data" / buildings.EDB_REL).exists())
check("the log entry says it was a buildings edit", rec["mode"] == "buildings")

undo(rec["id"])
check("undo restores the EDB byte-for-byte",
      mod.edb_path.read_text(encoding=buildings.ENCODING) == original)

# ---- 6) renaming a building writes all three localisation keys --------------
print("\n6) renaming a building")
mod = Mod(work)                      # fresh, the undo above changed the file
if mod.building_loc_path.exists():
    loc_before = mod.building_loc_path.read_text(encoding=localization.ENCODING)
    plan = buildings.plan_edit(mod, {"line": line.name, "levels": [
        level_payload(target, loc={"name": "Test Barracks of Testing",
                                   "descr": "A long description.",
                                   "descr_short": "A short one."})]})
    check("the rename is a change", any("Test Barracks" in c for c in plan.changes))
    check("the localisation file would be rewritten", bool(plan.loc_text))
    check("the EDB is NOT touched by a rename alone", not plan.edb_text)
    parsed = localization.parse_text(plan.loc_text, descr_suffix="_desc")
    entry = parsed.get(target.name)
    check("name written", entry and entry.name == "Test Barracks of Testing")
    check("description written", entry and entry.descr == "A long description.")
    check("short description written", entry and entry.descr_short == "A short one.")
    rec = buildings.apply_edit(plan)
    check("the localisation file was backed up",
          buildings.LOC_REL in rec["manifest"]["backed_up"])
    undo(rec["id"])
    check("undo restores the localisation file",
          mod.building_loc_path.read_text(encoding=localization.ENCODING) == loc_before)
else:
    print("  [skip] this mod has no text/export_buildings.txt")

# ---- 6b) per-culture names ---------------------------------------------------
# A level is named once for everyone ({stables}) and again for each culture
# ({stables_northern_european}). Mods that use the per-culture keys leave the
# shared one as a placeholder equal to its own key, and reading only that key is
# what made every building in DaC show its code name instead of its name.
print("\n6b) per-culture names")
mod = Mod(work)
if mod.building_loc_path.exists() and mod.cultures:
    culture = mod.cultures[0]
    recs = buildings._loc_all(mod, target.name)
    check("every culture has a slot, plus the shared key",
          set(recs) == set([""] + list(mod.cultures)))
    check("each slot names the key it writes",
          recs[culture]["key"] == target.name + "_" + culture and recs[""]["key"] == target.name)
    check("a key equal to its own name is not a name",
          buildings._placeholder("stables", "stables")
          and not buildings._placeholder("stables", "Stables"))

    loc_before = mod.building_loc_path.read_text(encoding=localization.ENCODING)
    other = mod.cultures[-1]
    plan = buildings.plan_edit(mod, {"line": line.name, "levels": [
        level_payload(target, loc_cultures={culture: {
            "name": "Culture Barracks", "descr": "Only for one culture.",
            "descr_short": "One culture."}})]})
    check("a per-culture rename is a change",
          any("Culture Barracks" in c for c in plan.changes))
    parsed = localization.parse_text(plan.loc_text, descr_suffix="_desc")
    entry = parsed.get(target.name + "_" + culture)
    check("it lands on the culture's own key", entry and entry.name == "Culture Barracks")
    check("the shared key is left alone",
          (parsed.get(target.name) or localization.LocEntry()).name
          == (mod.building_loc.get(target.name) or localization.LocEntry()).name)
    if other != culture:
        was = mod.building_loc.get(target.name + "_" + other)
        now = parsed.get(target.name + "_" + other)
        check("another culture's key is left alone",
              (was is None and now is None)
              or (was and now and was.name == now.name))

    # the name a level SHOWS falls through the same way the game reads it
    best = buildings._best_loc(mod, target.name, culture)
    check("the label prefers the culture being looked at, when it has one",
          best["culture"] == culture if recs[culture]["present"]
          and not buildings._placeholder(recs[culture]["key"], recs[culture]["name"])
          else True)
    check("_label never returns an empty string",
          bool(buildings._label(mod, target.name, "", culture)))
    check("planning alone wrote nothing",
          mod.building_loc_path.read_text(encoding=localization.ENCODING) == loc_before)
else:
    print("  [skip] this mod has no building localisation or no culture folders")

# ---- 7) the payloads the UI reads ------------------------------------------
print("\n7) UI payloads")
mod = Mod(work)
ov = buildings.overview(mod)
check("overview lists every line", len(ov["lines"]) == len(mod.edb.buildings))
check("overview carries the capability vocabulary", len(ov["capabilities"]) > 20)
check("every line has a settlement kind",
      all(l["settlement"] in ("city", "castle", "both") for l in ov["lines"]))
d = buildings.detail(mod, line.name)
check("detail has one entry per level", len(d["levels"]) == len(line.blocks))
check("detail carries every culture's text, so the editor never re-asks",
      all(set(lv["loc_all"]) == set([""] + list(mod.cultures)) for lv in d["levels"]))
check("detail says which culture each label came from",
      all(lv["loc_culture"] in lv["loc_all"] for lv in d["levels"]))
check("detail resolves the units its pools name",
      all(u.get("type") for u in d["units"].values()))
check("detail is JSON-serialisable", bool(json.dumps(d)))
try:
    buildings.detail(mod, "no such building line")
    check("an unknown line raises", False)
except KeyError:
    check("an unknown line raises", True)

# ---- 8) requires clauses, as structure -------------------------------------
print("\n8) requires clauses")
CLAUSES = [
    "factions { gondor, northern_european, } and hidden_resource unlocked",
    "factions { portugal, }  and region_religion catholic 75 and not hidden_resource GondorEast",
    "not event_counter civil_war 1 and region_religion nomadic 15",
    "factions { sicily, } and building_present_min_level masons_lodge north_lodge"
    " or building_present_min_level masons_lodge south_lodge",
    "resource silk",
    "woe_unlock_siege.",                    # malformed, and in a real mod
    "",
]
for clause in CLAUSES:
    conds = buildings.parse_clause(clause)
    back = buildings.clause_text(conds)
    check(f"round-trips: {clause[:44] or '(empty)'!r}",
          " ".join(back.split()) == " ".join(clause.split()))
check("`not` is parsed off the term, not into it",
      buildings.parse_clause("not hidden_resource x")[0].negate)
check("a malformed term is kept verbatim as raw",
      buildings.parse_clause("woe_unlock_siege.")[0].kind == "raw")
check("a keyword with the wrong argument count stays raw",
      buildings.parse_clause("event_counter only_one_arg")[0].kind == "raw")
check("an `and` inside a faction list can't split the clause",
      len(buildings.parse_clause("factions { and, or, } and resource silk")) == 2)

# every clause in every installed mod
for name in installed:
    m2 = Mod(MODS / name)
    if not m2.edb_path.exists():
        continue
    clauses = []
    for bl in m2.edb.buildings:
        for b in bl.blocks:
            clauses.append(b.requires)
            clauses += [c.requires for c in b.capabilities + b.faction_capabilities]
    bad = [c for c in clauses if c
           and " ".join(buildings.clause_text(buildings.parse_clause(c)).split())
           != " ".join(c.split())]
    check(f"{name}: {len(clauses)} clauses, {len(bad)} not byte-identical",
          len(bad) < len(clauses) / 100)
    # Every difference must be the parser TIDYING, never losing: emitting again
    # is a fixed point, and the same factions come back out.
    unstable = [c for c in bad
                if buildings.clause_text(buildings.parse_clause(
                    buildings.clause_text(buildings.parse_clause(c))))
                != buildings.clause_text(buildings.parse_clause(c))]
    check(f"{name}: every tidied clause is a fixed point", not unstable)
    lossy = [c for c in bad
             if set(buildings.clause_factions(c))
             != set(buildings.clause_factions(
                 buildings.clause_text(buildings.parse_clause(c))))]
    check(f"{name}: no faction is lost by tidying", not lossy)

# ---- 9) structured edits go through plan_edit -------------------------------
print("\n9) editing a clause structurally")
mod = Mod(work)
edb = mod.edb
line2 = next(bl for bl in edb.buildings if any(b.recruits for b in bl.blocks))
blk2 = next(b for b in line2.blocks if b.recruits)
conds = [{"join": "", "negate": False, "kind": "factions",
          "values": ["england", "venice"], "values_raw": ""},
         {"join": "and", "negate": True, "kind": "hidden_resource",
          "values": ["nowhere"]}]
plan = buildings.plan_edit(mod, {"line": line2.name, "levels": [
    {"name": blk2.name, "conditions": conds, "scalars": dict(blk2.scalars),
     "upgrades": list(blk2.upgrades), "settlement": blk2.settlement}]})
check("a structured clause is written as text",
      "factions { england, venice, } and not hidden_resource nowhere"
      in "\n".join(plan.changes))
reparsed = buildings.parse_text(plan.edb_text).get(line2.name).level(blk2.name)
check("…and reads back the same", buildings.clause_factions(reparsed.requires)
      == ["england", "venice"])
check("sending the SAME clause as text is not a change",
      not buildings.plan_edit(mod, {"line": line2.name, "levels": [
          {"name": blk2.name, "requires": blk2.requires}]}).changes)

# ---- 10) ownership: the check and the fix -----------------------------------
print("\n10) unit ownership")
pool = blk2.recruits[0]
unit = next((u for u in mod.edu.units if u.type.lower() == pool.unit.lower()), None)
if unit is None:
    print("  [skip] the first pool names a unit this mod's EDU doesn't have")
else:
    outsider = next(f for f in mod.faction_cultures
                    if f not in unit.ownership and f != "slave")
    rows = buildings.ownership_report(mod, [{"unit": unit.type,
                                             "factions": [outsider]}])
    check("a faction the unit doesn't belong to is reported",
          rows[0]["missing_ownership"] == [outsider])
    check("one it does belong to is not",
          not buildings.ownership_report(
              mod, [{"unit": unit.type, "factions": [unit.ownership[0]]}]
          )[0]["missing_ownership"])
    check("an unknown unit is flagged rather than silently ignored",
          not buildings.ownership_report(mod, [{"unit": "no such unit",
                                                "factions": ["england"]}])[0]["known"])
    culture = next((c for c in set(mod.faction_cultures.values())), "")
    check("a culture expands to its factions",
          set(buildings._expand_factions(mod, [culture]))
          == {f for f, c in mod.faction_cultures.items()
              if c == culture and f != "slave"})
    check("`all` expands to every faction",
          len(buildings._expand_factions(mod, ["all"]))
          == len([f for f in mod.faction_cultures if f != "slave"]))

    # the fix, through a real plan
    caps = [{"line": c.line, "keyword": c.keyword, "args": c.args,
             "requires": c.requires, "delete": False} for c in blk2.capabilities]
    for c in caps:
        if c["keyword"] == "recruit_pool" and pool.unit in c["args"]:
            c["conditions"] = [{"join": "", "negate": False, "kind": "factions",
                                "values": [outsider]}]
    body = {"line": line2.name, "fix_ownership": True, "levels": [
        {"name": blk2.name, "scalars": dict(blk2.scalars),
         "upgrades": list(blk2.upgrades), "settlement": blk2.settlement,
         "requires": blk2.requires, "capabilities": caps}]}
    plan = buildings.plan_edit(mod, body)
    check("the plan says it will extend ownership",
          any("ownership +=" in c for c in plan.changes))
    check("the EDU would be rewritten", bool(plan.edu_text))
    before_edu = mod.edu_path.read_bytes()
    rec = buildings.apply_edit(plan)
    after = Mod(work)
    fixed = next(u for u in after.edu.units if u.type == unit.type)
    check("the faction is now in the unit's ownership", outsider in fixed.ownership)
    check("its existing ownership is untouched",
          all(f in fixed.ownership for f in unit.ownership))
    check("the EDU was backed up",
          "export_descr_unit.txt" in rec["manifest"]["backed_up"])
    undo(rec["id"])
    check("undo restores the EDU byte-for-byte",
          mod.edu_path.read_bytes() == before_edu)

    # and the opt-out
    plan = buildings.plan_edit(mod, dict(body, fix_ownership=False))
    check("without fix_ownership the EDU is left alone", not plan.edu_text)

shutil.rmtree(work.parent, ignore_errors=True)
shutil.rmtree(cfg, ignore_errors=True)
print("\n" + ("ALL PASSED" if all(ok) else "SOME FAILED"))
sys.exit(0 if all(ok) else 1)
