"""The 14i additions: city/castle comparison, editable banners, unit marks.

Three pieces of new surface, and the one property each of them has to keep.

  * ``buildings.variant_compare`` — one building line beside its twin, tier by
    tier. Every unit either half trains appears exactly once per tier, marked
    ``both`` / ``a`` / ``b``; ``diff`` names the fields that disagree rather
    than answering yes-or-no, because on a real pair almost every shared unit
    differs in ``requires`` alone and a bare flag would report the whole roster.
    A line with no twin is an answer, not an error.
  * ``edusort.banner_style`` / ``banner`` — the section banner is the only text
    the cleanup authors, so its shape is the user's. The default has to stay
    byte for byte what it was before the style existed, a banner written in any
    style has to be read back by ``BANNER_RE``, and a nonsense style out of a
    text box must fall back rather than raise.
  * ``edusort.apply_marks`` and ``special_of`` — tier, variant and
    classification written onto the unit's own ``;@m2gt`` line. Setting one may
    not touch another unit or another key, clearing one has to remove it, and a
    marked general has to sort where the marker says rather than where its
    ``attributes`` say.

Then the same three against every installed mod, because the only interesting
question about a whole-file rewrite is what it does to a real file.

    python -m tests.test_variants_and_marks
"""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _realmod  # noqa: E402

from unittransfer import buildings, config, edu, edusort  # noqa: E402
from unittransfer.mod import Mod  # noqa: E402

ok = []


def check(label, cond):
    ok.append(bool(cond))
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}")


cfg = Path(tempfile.mkdtemp(prefix="ut_cfg_"))
config.CONFIG_DIR = cfg
config.SETTINGS_PATH = cfg / "settings.json"
config.LOG_PATH = cfg / "transfers.json"


# ---------------------------------------------------------------------------
# a city/castle pair with one of everything worth reporting
EDB = """building barracks
{
    levels militia_barracks city_barracks
    {
        militia_barracks city requires factions { england, }
        {
            capability
            {
                recruit_pool "Spearmen"  1  0.5  2  0 requires factions { england, }
                recruit_pool "Archers"  1  0.5  2  0 requires factions { england, }
            }
            material wooden
            construction  2
            cost  400
            settlement_min town
            upgrades
            {
                city_barracks
            }
        }
        city_barracks city requires factions { england, }
        {
            capability
            {
                recruit_pool "Spearmen"  2  0.5  3  0 requires factions { england, }
            }
            material wooden
            construction  3
            cost  800
            settlement_min large_town
            upgrades
            {
            }
        }
    }
    plugins
    {
    }
}

building castle_barracks
{
    levels c_militia_barracks c_city_barracks
    {
        c_militia_barracks castle requires factions { england, }
        {
            capability
            {
                recruit_pool "Spearmen"  1  0.5  2  0 requires factions { scotland, }
                recruit_pool "Knights"  1  0.25  2  1 requires factions { england, }
            }
            material wooden
            construction  2
            cost  400
            settlement_min town
            upgrades
            {
                c_city_barracks
            }
        }
        c_city_barracks castle requires factions { england, }
        {
            capability
            {
                recruit_pool "Spearmen"  9  0.5  3  0 requires factions { england, }
            }
            material wooden
            construction  3
            cost  800
            settlement_min large_town
            upgrades
            {
            }
        }
    }
    plugins
    {
    }
}

building lonely
{
    levels lonely_one
    {
        lonely_one requires factions { england, }
        {
            capability
            {
            }
            material wooden
            construction  1
            cost  100
            settlement_min village
            upgrades
            {
            }
        }
    }
    plugins
    {
    }
}
"""


class FakeEdu:
    """A mod with no units at all — every pool then reads as "not in the EDU",
    which is a real state and the one that exercises the fallback."""
    units = ()


class FakeLoc:
    def get(self, key):
        return None


class FakeMod:
    """The smallest thing ``variant_compare`` will read: an EDB and a name."""

    def __init__(self, root, text):
        self.root = Path(root)
        self.name = "fake"
        self.data = self.root / "data"
        self.data.mkdir(parents=True, exist_ok=True)
        (self.data / buildings.EDB_REL).write_text(text, encoding=buildings.ENCODING)
        self.edb = buildings.parse_text(text)
        self.edu = FakeEdu()
        self.loc = FakeLoc()
        self.cultures = ["northern_european"]
        self.faction_cultures = {"england": "northern_european"}
        self.faction_names = {"england": "England"}
        self.building_loc = FakeLoc()

    @property
    def edb_path(self):
        return self.data / buildings.EDB_REL


root = Path(tempfile.mkdtemp(prefix="ut_variants_"))
mod = FakeMod(root, EDB)

print("== city and castle, side by side ==")
r = buildings.variant_compare(mod, "barracks")
check("the twin is found", r["twin"] == "castle_barracks")
check("this half is the city one", r["settlement"] == "city")
check("the other half is the castle one", r["twin_settlement"] == "castle")
check("both tiers are listed", len(r["levels"]) == 2)

lv0 = r["levels"][0]
check("tier 1 faces the twin's tier 1", lv0["twin_level"] == "c_militia_barracks")
units = {u["unit"]: u for u in lv0["units"]}
check("every unit either half trains is listed once",
      sorted(units) == ["Archers", "Knights", "Spearmen"])
check("a unit both halves train is marked both", units["Spearmen"]["where"] == "both")
check("a unit only this half trains is marked a", units["Archers"]["where"] == "a")
check("a unit only the twin trains is marked b", units["Knights"]["where"] == "b")
check("a one-sided unit carries the numbers of the side that has it",
      units["Archers"]["a"] is not None and units["Archers"]["b"] is None
      and units["Knights"]["b"] is not None and units["Knights"]["a"] is None)

# Spearmen: same four numbers, different `requires` (england vs scotland).
check("a requires-only difference is reported as a difference",
      units["Spearmen"]["diff"] == ["requires"])
check("…but NOT as a difference in the numbers",
      units["Spearmen"]["numbers_differ"] is False)

lv1 = r["levels"][1]
sp = next(u for u in lv1["units"] if u["unit"] == "Spearmen")
check("a number that really differs is named", "initial" in sp["diff"])
check("…and counts as a number difference", sp["numbers_differ"] is True)
check("the per-tier counts add up",
      lv0["only_a"] == 1 and lv0["only_b"] == 1 and lv1["differs"] == 1)
check("the line's totals are the sum of its tiers",
      r["only_a"] == 1 and r["only_b"] == 1 and r["differs"] == 1)

# The comparison is symmetric: run it from the castle side and the sides swap.
back = buildings.variant_compare(mod, "castle_barracks")
bu = {u["unit"]: u for u in back["levels"][0]["units"]}
check("from the other side, the same gaps point the other way",
      bu["Archers"]["where"] == "b" and bu["Knights"]["where"] == "a")

lone = buildings.variant_compare(mod, "lonely")
check("a line with no twin is an answer, not an error",
      lone["twin"] == "" and lone["levels"] == [] and lone.get("reason"))
try:
    buildings.variant_compare(mod, "no_such_line")
    check("a line that does not exist raises", False)
except KeyError:
    check("a line that does not exist raises", True)


# ---------------------------------------------------------------------------
print("\n== the section banner's shape is the user's ==")

default = edusort.banner("GONDOR TIER 2 INFANTRY")
check("the default is what it always was",
      default == ";" + "-" * 35 + " GONDOR TIER 2 INFANTRY " + "-" * 35)
check("…and its width is stated honestly", len(default) == edusort.BANNER_WIDTH)
check("an empty style is the default style",
      edusort.banner("GONDOR TIER 2 INFANTRY", {}) == default)
check("the default does NOT force capitals",
      "Gondor" in edusort.banner("Gondor Tier 2 Infantry"))
check("capitals can be asked for",
      "GONDOR" in edusort.banner("Gondor Tier 2 Infantry", {"upper": True}))

narrow = edusort.banner("GONDOR TIER 2 INFANTRY", {"width": 60, "fill": "="})
check("width is obeyed", len(narrow) == 60)
check("the fill character is obeyed", "=" * 5 in narrow and "-" not in narrow)

for style in ({"width": 40}, {"width": 200, "fill": "#"}, {"fill": "*"},
              {"width": 60, "upper": True}, {"prefix": ";;"}):
    m = edusort.BANNER_RE.match(edusort.banner("GONDOR TIER 2 INFANTRY", style))
    check(f"a banner drawn as {style} still reads back",
          m is not None and m.group("tier") == "2")

check("a title longer than the width still ends in a readable banner",
      edusort.BANNER_RE.match(
          edusort.banner("A VERY LONG SECTION NAME " * 6 + "INFANTRY",
                         {"width": 30})) is not None)

# Whatever a text box can produce has to be survivable: this is a display
# choice, and a bad one must not be able to stop a cleanup.
for bad in ({"width": "not a number"}, {"width": None}, {"fill": ""},
            {"fill": "AB"}, {"prefix": "rm -rf"}, {"width": 1}, {"width": 99999}):
    s = edusort.banner_style(bad)
    check(f"a nonsense style {bad} falls back instead of raising",
          20 <= s["width"] <= 200 and len(s["fill"]) == 1
          and s["prefix"].startswith(";"))


# ---------------------------------------------------------------------------
print("\n== tier, variant and classification, on the unit's own marker ==")

MARKED = (
    "type\t\t\tGondor Bodyguard\n"
    "dictionary\t\tGondor_Bodyguard\n"
    "category\t\tcavalry\n"
    "attributes\t\tgeneral_unit, hide_forest\n"
    "ownership\t\tsicily\n"
    "\n"
    "type\t\t\tGondor Spearmen\n"
    "dictionary\t\tGondor_Spearmen\n"
    "category\t\tinfantry\n"
    "attributes\t\thide_forest\n"
    "ownership\t\tsicily\n"
)

f = edu.parse_text(MARKED)
guard, spear = f.units[0], f.units[1]
check("a general is detected from its own attributes",
      edusort.detected_special(guard) == "general")
check("an ordinary unit detects as nothing",
      edusort.detected_special(spear) == "")
check("special_of falls back to what was detected",
      edusort.special_of(guard) == "general" and edusort.special_of(spear) == "")

out, touched = edusort.apply_marks(MARKED, {
    "Gondor Spearmen": {"tier": "2", "variant": "aor", "special": "hero"}})
check("only the unit named is changed", touched == ["Gondor Spearmen"])
f2 = edu.parse_text(out)
g2, s2 = f2.units[0], f2.units[1]
check("the marked unit reads its tier back", s2.tier == "2")
check("…and its variant", s2.variant == "aor")
check("…and its classification", s2.special == "hero")
check("the other unit is untouched, byte for byte", g2.raw == guard.raw)
check("every field line survives",
      edu.block_fields(s2.raw) == edu.block_fields(spear.raw))

check("a hero sorts in front of the tiered units",
      edusort.tier_rank(s2) < edusort.tier_rank(spear))
check("a general still leads even that", edusort.tier_rank(g2) < edusort.tier_rank(s2))

# `none` is a real value, not a blank: it is how you overrule a detection.
over, _ = edusort.apply_marks(MARKED, {"Gondor Bodyguard": {"special": "none"}})
g3 = edu.parse_text(over).units[0]
check("special=none overrules a detected general",
      edusort.special_of(g3) == "none" and not edusort.is_general(g3))
check("…and it then sorts on its tier like anything else",
      edusort.tier_rank(g3) == edusort.UNTIERED)

cleared, _ = edusort.apply_marks(out, {"Gondor Spearmen": {"special": ""}})
s4 = edu.parse_text(cleared).units[1]
check("an empty value REMOVES that key", s4.special == "")
check("…and leaves the other keys alone", s4.tier == "2" and s4.variant == "aor")

wiped, _ = edusort.apply_marks(
    out, {"Gondor Spearmen": {"tier": "", "variant": "", "special": ""}})
check("clearing every key deletes the marker line outright",
      edu.MARKER not in wiped)
check("…and the block is back to what it was",
      edu.parse_text(wiped).units[1].raw == spear.raw)

check("no marks at all is a no-op", edusort.apply_marks(MARKED, {})[0] == MARKED)
check("a mark for a unit that is not there is a no-op",
      edusort.apply_marks(MARKED, {"Nobody": {"tier": "3"}})[0] == MARKED)


# ---------------------------------------------------------------------------
print("\n== against the installed mods ==")

edb_mods = [m for m in _realmod.installed()
            if (m / "data" / "export_descr_buildings.txt").is_file()]
if not edb_mods:
    print("  (no installed mod with an EDB — the sweep is skipped)")
for src in edb_mods:
    real = Mod(src)
    pairs = buildings.variant_pairs(real.edb)
    lines = [n for n in pairs if real.edb.get(n) is not None]
    if not lines:
        print(f"  ({src.name} has no city/castle pair — skipped)")
        continue
    both_ways = 0
    for name in lines[:6]:
        got = buildings.variant_compare(real, name)
        # every unit exactly once per tier, and the counts consistent with the rows
        for lv in got["levels"]:
            seen = [u["unit"] for u in lv["units"]]
            if len(seen) != len(set(seen)):
                check(f"{src.name}: {name}/{lv['level']} lists a unit twice", False)
                break
            if (lv["only_a"] != sum(1 for u in lv["units"] if u["where"] == "a")
                    or lv["only_b"] != sum(1 for u in lv["units"] if u["where"] == "b")):
                check(f"{src.name}: {name}/{lv['level']} counts disagree with its rows",
                      False)
                break
        else:
            both_ways += 1
    check(f"{src.name}: {both_ways} of {min(6, len(lines))} pair(s) compare cleanly",
          both_ways == min(6, len(lines)))

    # the halves have to agree about each other
    name = lines[0]
    there = buildings.variant_compare(real, name)
    back2 = buildings.variant_compare(real, there["twin"])
    check(f"{src.name}: the two halves report the same number of gaps",
          there["only_a"] + there["only_b"] == back2["only_a"] + back2["only_b"])
    check(f"{src.name}: and they point opposite ways",
          there["only_a"] == back2["only_b"] and there["only_b"] == back2["only_a"])

edu_mods = [m for m in _realmod.installed()
            if (m / "data" / "export_descr_unit.txt").is_file()]
for src in edu_mods:
    work = Path(tempfile.mkdtemp()) / src.name
    (work / "data").mkdir(parents=True)
    for rel in ("export_descr_unit.txt", "descr_sm_factions.txt", "text/expanded.txt"):
        s = src / "data" / rel
        if s.is_file():
            (work / "data" / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s, work / "data" / rel)
    path = work / "data" / "export_descr_unit.txt"
    before = path.read_text(encoding=edu.ENCODING)

    # the ordering screen has to say something usable about every unit
    view = edusort.overview(Mod(work))
    rows = [u for s in view["sections"] for u in s["units"]]
    check(f"{src.name}: every unit is on the ordering screen exactly once",
          len(rows) == len({u["type"] for u in rows})
          == len(edu.parse_text(before).main_units))
    check(f"{src.name}: every drop-down has something to offer",
          view["tiers"] and view["variants"] and view["specials"])
    check(f"{src.name}: the detected classification is one the drop-down offers",
          all(u["detected_special"] in ("",) + tuple(view["specials"]) for u in rows))

    # marking a unit from that screen survives a cleanup, and changes nothing else
    victim = rows[len(rows) // 2]["type"]
    marks = {victim: {"tier": "4", "variant": "aor", "special": "hero"}}
    p = edusort.plan(Mod(work), marks=marks)
    check(f"{src.name}: a marked cleanup plans cleanly", p.errors == [])
    if p.errors or not p.text:
        continue
    check(f"{src.name}: the plan says which unit it marked", p.marked == [victim])
    after = edu.parse_text(p.text)
    got = next(u for u in after.main_units if u.type == victim)
    check(f"{src.name}: the mark reaches the written text",
          (got.tier, got.variant, got.special) == ("4", "aor", "hero"))
    fa = {u.type: edu.block_fields(u.raw) for u in edu.parse_text(before).main_units}
    fb = {u.type: edu.block_fields(u.raw) for u in after.main_units}
    check(f"{src.name}: no unit gained or lost a field", fa == fb)

    # a banner style is a display choice: it may not move a single unit
    plain = edusort.plan(Mod(work))
    styled = edusort.plan(Mod(work), style={"width": 60, "fill": "=", "upper": True})
    check(f"{src.name}: a different banner style moves nobody",
          plain.moved == styled.moved)
    check(f"{src.name}: …and is still a clean plan", styled.errors == [])
    shutil.rmtree(work.parent, ignore_errors=True)


shutil.rmtree(root, ignore_errors=True)
shutil.rmtree(cfg, ignore_errors=True)
bad = ok.count(False)
print(f"\n{len(ok) - bad}/{len(ok)} checks — " + ("ALL PASSED" if not bad else "SOME FAILED"))
sys.exit(1 if bad else 0)
