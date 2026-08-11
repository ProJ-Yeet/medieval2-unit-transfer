"""Recruitment checks, city/castle pairing, and editing several lines in one save.

Three mistakes an EDB can hold that no single-level view shows, plus the writes
that fix them. Covers:

  * variant_key strips every marker a real mod uses (``castle_x``, ``c_x``,
    ``x_castle``, ``temple_c_x``, ``city_hall``/``castle_hall``) and nothing else
  * variant_pairs pairs one city line to one castle line, and refuses to guess
    when a key has two candidates on a side
  * pair_levels matches marker-free level names first, then falls back to
    position — a mod that renamed its castle tiers still lines tier 1 up to tier 1
  * line_checks finds a unit that stops being recruitable further up a chain, a
    unit one settlement type has and the other does not, and a unit listed twice
    in one level (flagging identical clauses separately from per-faction ones)
  * unit_instances finds every pool for one unit across every line
  * plan_edit's `also` writes a second building line in the SAME pass, so a
    mirrored pool is one edit and one undo step
  * the recruit-limit warning still counts a mirrored level's EXISTING pools,
    which a payload carrying only the added row would otherwise miss

    python -m tests.test_building_checks
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import buildings, config

ok = []


def check(label, cond):
    ok.append(bool(cond))
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}")


cfg = Path(tempfile.mkdtemp(prefix="ut_cfg_"))
config.CONFIG_DIR = cfg
config.SETTINGS_PATH = cfg / "settings.json"
config.LOG_PATH = cfg / "transfers.json"


# ---------------------------------------------------------------------------
print("\n== variant names ==")

for a, b in [("barracks", "castle_barracks"), ("barracks", "c_barracks"),
             ("anduin_barracks", "anduin_barracks_castle"),
             ("temple_academic", "temple_c_academic"),
             ("core_building", "core_castle_building"),
             ("city_hall", "castle_hall"), ("stables", "c_stables")]:
    check(f"{a!r} and {b!r} key the same",
          buildings.variant_key(a) == buildings.variant_key(b))

check("a name that is only a marker keeps itself",
      buildings.variant_key("castle") == "castle")
check("different buildings do NOT collide",
      buildings.variant_key("meso_barracks") != buildings.variant_key("barracks"))
check("…nor do two temples of different gods",
      buildings.variant_key("temple_c_catholic") != buildings.variant_key("temple_c_muslim"))


# ---------------------------------------------------------------------------
print("\n== pairing and the three checks ==")

EDB = """\
building barracks
{
	levels town_watch militia_barracks
	{
		town_watch city requires factions { england, }
		{
			capability
			{
				recruit_pool "Spearmen"  1  0.5  2  0  requires factions { england, }
				recruit_pool "Spearmen"  1  0.5  2  0  requires factions { france, }
				recruit_pool "Archers"  1  0.5  2  0
			}
			construction  1
			cost  400
		}
		militia_barracks city requires factions { england, }
		{
			capability
			{
				recruit_pool "Spearmen"  1  0.5  2  0
				recruit_pool "Twice"  1  0.5  2  0
				recruit_pool "Twice"  1  0.5  2  0
			}
			construction  2
			cost  800
		}
	}
	plugins
	{
	}
}

building castle_barracks
{
	levels c_town_watch c_militia_barracks
	{
		c_town_watch castle requires factions { england, }
		{
			capability
			{
				recruit_pool "Spearmen"  1  0.5  2  0
			}
			construction  1
			cost  400
		}
		c_militia_barracks castle requires factions { england, }
		{
			capability
			{
				recruit_pool "Spearmen"  1  0.5  2  0
				recruit_pool "Knights"  2  0.25  3  1
			}
			construction  2
			cost  800
		}
	}
	plugins
	{
	}
}
"""

edb = buildings.parse_text(EDB)
check("both lines parsed", len(edb.buildings) == 2)
pairs = buildings.variant_pairs(edb)
check("the city line pairs to the castle one", pairs.get("barracks") == "castle_barracks")
check("…and back the other way", pairs.get("castle_barracks") == "barracks")

bl = edb.get("barracks")
levels = buildings.pair_levels(bl, edb.get("castle_barracks"))
check("levels pair by their marker-free names",
      levels == {"town_watch": "c_town_watch",
                 "militia_barracks": "c_militia_barracks"})

res = buildings.line_checks(edb, bl, pairs)
check("the twin is named", res["twin"] == "castle_barracks")
check("level_pairs covers every tier, not only the differing ones",
      len(res["level_pairs"]) == len(bl.blocks))

gaps = {g["unit"]: g for g in res["gaps"]}
check("Archers is flagged: tier 1 trains it, tier 2 does not", "Archers" in gaps)
check("…naming the tier it drops out of",
      gaps["Archers"]["missing_levels"] == ["militia_barracks"])
check("…and carrying the numbers to copy up",
      gaps["Archers"]["pool"]["maximum"] == "2")
check("Spearmen is trained at both tiers, so it is not a gap", "Spearmen" not in gaps)
check("a unit that only appears at the TOP tier is not a gap either",
      "Knights" not in gaps)

dupes = {d["unit"]: d for d in res["dupes"]}
check("the unit listed twice with the same clause is flagged", "Twice" in dupes)
check("…as identical, which is the bad kind", dupes["Twice"]["same_requires"])
check("the per-faction pair is reported but marked deliberate",
      dupes.get("Spearmen") and not dupes["Spearmen"]["same_requires"])

mirror = {m["level"]: m for m in res["mirror"]}
check("tier 1 differs from its twin", "town_watch" in mirror)
check("…because the city half has Archers and the castle half does not",
      [p["unit"] for p in mirror["town_watch"]["only_here"]] == ["Archers"])
check("the numbers travel with the name, so a copy lands on the twin's figures",
      mirror["militia_barracks"]["only_there"][0]["initial"] == "2")
check("the twin's whole roster is reported, not only the differences",
      set(res["twin_units"]["c_militia_barracks"]) == {"spearmen", "knights"})


# ---------------------------------------------------------------------------
print("\n== unambiguous pairs only ==")

AMBIG = EDB + """\
building c_barracks
{
	levels other_watch
	{
		other_watch castle requires factions { england, }
		{
			capability
			{
				recruit_pool "Spearmen"  1  0.5  2  0
			}
			construction  1
			cost  400
		}
	}
	plugins
	{
	}
}
"""
amb = buildings.variant_pairs(buildings.parse_text(AMBIG))
check("two castle candidates for one key means no pair is guessed",
      "barracks" not in amb)


# ---------------------------------------------------------------------------
print("\n== level pairing falls back to position ==")

RENAMED = EDB.replace("c_town_watch", "gatehouse").replace(
    "c_militia_barracks", "keep")
red = buildings.parse_text(RENAMED)
levels = buildings.pair_levels(red.get("barracks"), red.get("castle_barracks"))
check("a renamed castle tier still faces the tier at the same position",
      levels == {"town_watch": "gatehouse", "militia_barracks": "keep"})


# ---------------------------------------------------------------------------
print("\n== one save, two building lines ==")


class FakeMod:
    """Just enough of a Mod for plan_edit: an EDB on disk and no localisation."""

    def __init__(self, root: Path, text: str):
        self.root = root
        self.data = root / "data"
        self.data.mkdir(parents=True, exist_ok=True)
        self.name = "fake"
        (self.data / buildings.EDB_REL).write_text(text, encoding=buildings.ENCODING)
        self.edb = buildings.parse_text(text)
        self.faction_cultures = {}
        self.building_loc = None

    @property
    def edb_path(self):
        return self.data / buildings.EDB_REL


root = Path(tempfile.mkdtemp(prefix="ut_bldchk_"))
mod = FakeMod(root, EDB)

body = {
    "mod": "fake", "line": "barracks",
    "levels": [{"name": "town_watch",
                "capabilities": [{"line": None, "keyword": "recruit_pool",
                                  "args": '"Archers"  1  0.5  2  0',
                                  "requires": "", "delete": False}]}],
    # the castle twin, edited in the same request
    "also": [{"line": "castle_barracks",
              "levels": [{"name": "c_town_watch",
                          "capabilities": [{"line": None, "keyword": "recruit_pool",
                                            "args": '"Archers"  1  0.5  2  0',
                                            "requires": "factions { england, }",
                                            "delete": False}]}]}],
}
plan = buildings.plan_edit(mod, body)
check("no errors", not plan.errors)
check("the EDB would be rewritten", bool(plan.edb_text))
check("the change to THIS line is reported plainly",
      any(c.startswith("town_watch:") for c in plan.changes))
check("…and the other line's change says which line it is in",
      any(c.startswith("castle_barracks · c_town_watch:") for c in plan.changes))

after = buildings.parse_text(plan.edb_text)
city = [p.unit for p in after.get("barracks").level("town_watch").recruits]
castle = [p.unit for p in after.get("castle_barracks").level("c_town_watch").recruits]
check("the city tier gained the pool", city.count("Archers") == 2)   # it already had one
check("the castle tier gained one too", "Archers" in castle)
check("the mirrored pool kept its clause verbatim",
      any(c.requires.strip() == "factions { england, }"
          for c in after.get("castle_barracks").level("c_town_watch").capabilities
          if c.pool() and c.pool().unit == "Archers"))
check("the rest of the file is untouched",
      after.get("barracks").level("militia_barracks").scalars.get("cost") == "800")
check("a line that does not exist is an error, not a silent skip",
      buildings.plan_edit(mod, {"line": "barracks", "levels": [],
                                "also": [{"line": "nope", "levels": []}]}).errors)


# ---------------------------------------------------------------------------
print("\n== the recruit limit sees the twin's existing pools ==")

# One added row can only push a level over the limit when the rows already there
# are counted too — an `also` payload carries just the addition.
limit = buildings.RECRUIT_LIMIT
big = ["\t\t\t\trecruit_pool \"U%d\"  1  0.5  2  0\n" % i for i in range(limit + 1)]
CROWDED = EDB.replace('\t\t\t\trecruit_pool "Spearmen"  1  0.5  2  0\n'
                      '\t\t\t\trecruit_pool "Knights"  2  0.25  3  1\n',
                      "".join(big))
mod2 = FakeMod(Path(tempfile.mkdtemp(prefix="ut_bldchk2_")), CROWDED)
mod2.faction_cultures = {"england": "northern_european"}
plan2 = buildings.plan_edit(mod2, {
    "mod": "fake", "line": "barracks", "levels": [],
    "also": [{"line": "castle_barracks",
              "levels": [{"name": "c_militia_barracks",
                          "capabilities": [{"line": None, "keyword": "recruit_pool",
                                            "args": '"One More"  1  0.5  2  0',
                                            "requires": "", "delete": False}]}]}]})
check("adding one pool to an already-full twin level warns",
      any("c_militia_barracks" in w for w in plan2.warnings))

import shutil
shutil.rmtree(root, ignore_errors=True)
shutil.rmtree(cfg, ignore_errors=True)
bad = ok.count(False)
print(f"\n{len(ok) - bad}/{len(ok)} checks — " + ("ALL PASSED" if not bad else "SOME FAILED"))
sys.exit(1 if bad else 0)
