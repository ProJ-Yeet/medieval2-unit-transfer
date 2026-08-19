"""Phase 12: creating a whole building tree, and the facts that shape one.

Every other buildings operation edits a line the EDB already has. A new tree is
the first one that writes a block that was not there, and it lands in two files
at once — the EDB and ``text/export_buildings.txt`` — so the checks here are
mostly about refusing rather than writing.

What each part is here to catch:

  * **a level name is the EDB's one global namespace.** Two lines cannot share
    one: the text keys, the icon stems and every settlement plan are keyed on it,
    so a new tree that reuses one is refused before either file is touched.
  * **the levels chain forward.** All 771 upgrade entries in the three installed
    mods point at a level listed *after* them on the `levels` line, which is
    what TWCenter's hardcoded-limits note says the engine requires — so the
    scaffold builds the chain in that direction and the test asserts the sweep.
  * **an `upgrades` entry can carry its own clause** (``ce_wooden_wall requires
    event_counter … 1``), 41 of those 771. `upgrade_name` is the one place that
    knows the level is the first word.
  * **three text keys per level or the game crashes** at the construction panel.
    All 1099 real levels have all three, and a mod with no
    ``text/export_buildings.txt`` to write them into is refused rather than half
    served.
  * **the prefixes are measured, not asserted.** `guild_` needs a matching entry
    in ``export_descr_guilds.txt`` (all 19 real ones have one), every `temple_`
    line also carries a `religion`, and `core_` is two engine chains that both
    already exist.
  * **the cards are art.** They are listed, never written, and a blank one is
    never called a fault — Phase 10a's ruling about pips and settlement cards.
  * **create → undo puts the mod back byte for byte**, both files.

The scaffold, the refusals and the render need no game install. The sweeps and
the create/undo round trip run only when mods are there.

    python -m tests.test_edb_tree
"""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import buildings as B, config
from unittransfer.mod import Mod
from unittransfer.transfer import undo

ok = []


def check(label, cond):
    ok.append(bool(cond))
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}")


# Read where the game is BEFORE the config paths are redirected below — the
# scratch settings.json the rest of this file writes into knows about no install.
_root = config.get_med2_root()
MODS = (Path(_root) / "mods") if _root else None

cfg = Path(tempfile.mkdtemp(prefix="ut_cfg_"))
config.CONFIG_DIR = cfg
config.BACKUP_DIR = cfg / "backups"
config.SETTINGS_PATH = cfg / "settings.json"
config.LOG_PATH = cfg / "transfers.json"


# ---------------------------------------------------------------------------
print("\n1) the rendered block is one this module can read back")

SPEC = {
    "name": "forge",
    "levels": [
        {"name": "forge_1", "settlement": "city", "requires": "factions { greek, }",
         "material": "wooden", "construction": "2", "cost": "600",
         "settlement_min": "village"},
        {"name": "forge_2", "settlement": "city", "requires": "factions { greek, }",
         "material": "stone", "construction": "3", "cost": "1200",
         "settlement_min": "town"},
    ],
}

text = B.new_tree_text(SPEC, "    ")
edb = B.parse_text(text)
bl = edb.get("forge")
check("the block parses", bl is not None and not edb.warnings)
check("both levels are there", [b.name for b in bl.blocks] == ["forge_1", "forge_2"])
check("the `levels` line lists them in order", bl.levels == ["forge_1", "forge_2"])
check("level 1 upgrades into level 2", bl.blocks[0].upgrades == ["forge_2"])
check("the last level upgrades into nothing", bl.blocks[1].upgrades == [])
check("the settlement word is on the header", bl.blocks[0].settlement == "city")
check("the requires clause survives", bl.blocks[0].requires == "factions { greek, }")
check("the scalars are written",
      bl.blocks[1].scalars == {"material": "stone", "construction": "3",
                               "cost": "1200", "settlement_min": "town"})
check("there is a capability block for the editor to add pools to",
      bl.blocks[0].cap_span != (0, 0) and bl.blocks[0].capabilities == [])
check("and an empty plugins block — optional, but every real one is empty",
      bl.plugins_span != (0, 0) and bl.plugins == [])
check("the block round-trips through the parser",
      B.block_text(edb, bl) == text)
check("rendering it twice gives the same bytes",
      B.new_tree_text(SPEC, "    ") == text)

tabbed = B.new_tree_text(SPEC, "\t")
check("the indent is the caller's, not this module's",
      "\tlevels forge_1 forge_2\n" in tabbed and "    levels" not in tabbed)

conv = B.parse_text(B.new_tree_text(dict(SPEC, convert_to="castle_forge",
                                         religion="catholic"), "    "))
check("convert_to and religion land on the line",
      conv.get("forge").convert_to == "castle_forge"
      and conv.get("forge").religion == "catholic")

both = B.parse_text(B.new_tree_text(
    {"name": "f2", "levels": [{"name": "f2_1"}]}, "    "))
check("a level with no settlement word is 'both'",
      both.get("f2").settlement == "both")


# ---------------------------------------------------------------------------
print("\n1b) a `#` annotation line is not a keyword")
# The EDB's comment marker is `;`. A line starting with `#` is therefore not a
# comment as far as the format goes — but it is not a keyword either, and the
# engine ignores it: Divide and Conquer ships 109 of them inside one capability
# block, grouping its recruit_pool lines by faction, and the mod runs. Reading
# one as a capability put `#` in the capability picker as engine vocabulary.
ANNOTATED = """building hash_test
{
	levels hash_1
	{
		hash_1 city requires factions { greek, }
		{
			capability
			{
				# GONDOR
				recruit_pool "Spearmen"  1  0.5  2  0  requires factions { greek, }
				# ERIADOR
				happiness_bonus bonus 1
			}
			material wooden
			# a stray note among the scalars
			construction 2
			cost 600
			settlement_min village
			upgrades
			{
				# not an upgrade
			}
		}
	}
	plugins
	{
	}
}
"""
ha = B.parse_text(ANNOTATED)
hb = ha.get("hash_test")
hl = hb.blocks[0]
check("the line still parses", hb is not None and not ha.warnings)
check("the two real capabilities are read, the two `#` lines are not",
      [c.keyword for c in hl.capabilities] == ["recruit_pool", "happiness_bonus"])
check("a `#` line among the scalars is not a scalar",
      sorted(hl.scalars) == ["construction", "cost", "material", "settlement_min"])
check("a `#` line in an upgrades block is not an upgrade", hl.upgrades == [])
check("and the file is given back byte for byte — the annotations survive "
      "because nothing re-emits the block",
      B.block_text(ha, hb) == ANNOTATED)


# ---------------------------------------------------------------------------
print("\n2) upgrade_name: the level is the first word")
check("a bare entry is its own name", B.upgrade_name("stone_wall") == "stone_wall")
check("an entry with a clause gives the level only",
      B.upgrade_name("ce_wooden_wall requires event_counter cex_avail 1")
      == "ce_wooden_wall")
check("an empty entry is empty", B.upgrade_name("") == "")


# ---------------------------------------------------------------------------
print("\n3) what the module refuses, and what it only warns about")
installed = ([d.parent.parent for d in sorted(MODS.glob("*/data/" + B.EDB_REL))]
             if MODS and MODS.is_dir() else [])

if not installed:
    print("  (no mods installed — the refusals and the sweeps are skipped)")
else:
    mod = Mod(installed[0])
    taken_line = mod.edb.buildings[0].name
    taken_level = mod.edb.buildings[0].blocks[0].name

    def errs(spec):
        return B.plan_new_tree(mod, spec).errors

    def warns(spec):
        return B.plan_new_tree(mod, spec).warnings

    check("a nameless line is refused",
          errs({"name": "", "levels": [{"name": "zz_1"}]}))
    check("a name with a space is refused",
          errs({"name": "zz forge", "levels": [{"name": "zz_1"}]}))
    check("a name the EDB already has is refused",
          any("already has a building line" in e
              for e in errs({"name": taken_line, "levels": [{"name": "zz_1"}]})))
    check("a line with no levels is refused",
          errs({"name": "zz_forge", "levels": []}))
    check("a level name another line already owns is refused",
          any("already has a level" in e
              for e in errs({"name": "zz_forge", "levels": [{"name": taken_level}]})))
    check("a line named after an existing LEVEL is refused too",
          any("already the name of a level" in e
              for e in errs({"name": taken_level, "levels": [{"name": "zz_1"}]})))
    check("the same level twice in one new line is refused",
          any("twice" in e for e in errs({"name": "zz_forge",
                                          "levels": [{"name": "zz_1"},
                                                     {"name": "zz_1"}]})))
    check("nothing is written when the plan is refused",
          not B.plan_new_tree(mod, {"name": taken_line,
                                    "levels": [{"name": "zz_1"}]}).edb_text)

    deep = {"name": "zz_deep",
            "levels": [{"name": f"zz_d{i}"} for i in range(B.VANILLA_MAX_LEVELS + 2)]}
    check(f"past {B.VANILLA_MAX_LEVELS} levels is a warning, not a refusal — mods "
          "run deeper on M2TWEOP",
          not errs(deep) and any("vanilla stops" in w for w in warns(deep)))
    check("a guild_ line says it needs an export_descr_guilds entry",
          any("export_descr_guilds" in w
              for w in warns({"name": "guild_zz", "levels": [{"name": "zz_g1"}]})))
    check("a temple_ line with no religion says so",
          any("temple_" in w
              for w in warns({"name": "temple_zz", "levels": [{"name": "zz_t1"}]})))
    check("a convert_to naming nothing is a warning",
          any("convert_to" in w
              for w in warns({"name": "zz_c", "convert_to": "zz_nothing",
                              "levels": [{"name": "zz_c1"}]})))
    check("a create cannot delete or rename a tree",
          B.TREE_ACTIONS["create"] and not B.TREE_ACTIONS["delete"]
          and not B.TREE_ACTIONS["rename"]
          and set(B.TREE_REFUSED) == {"delete", "rename"})

    # ---- the defaults come from the mod, not from vanilla ----
    spec = B.new_tree_spec(mod, {"name": "zz_forge", "settlement": "city",
                                 "levels": [{"name": "zz_1"}, {"name": "zz_2"}]})
    clause = spec["levels"][0]["requires"]
    used = sorted(set(B.faction_cultures(mod).values()))
    check(f"the default clause names this mod's own {len(used)} culture(s), not "
          "vanilla's five",
          all(c in clause for c in used) and clause.startswith("factions {"))
    check("costs climb with the tier",
          int(spec["levels"][1]["cost"]) > int(spec["levels"][0]["cost"]))
    check("the settlement word is carried onto every level",
          all(lv["settlement"] == "city" for lv in spec["levels"]))
    check("a level with no label gets one from its name",
          spec["levels"][0]["label"] == "Zz 1")
    # the form sends "" rather than omitting the key, and an empty {name} key is
    # a blank row in the construction panel
    blank = B.new_tree_spec(mod, {"name": "zz_forge",
                                  "levels": [{"name": "zz_1", "label": "  "}]})
    check("an empty shown-name box is absent, not blank",
          blank["levels"][0]["label"] == "Zz 1")


# ---------------------------------------------------------------------------
print("\n3b) an upgrade's own clause survives being edited")
UPG = """building zz
{
    levels zz_1 zz_2
    {
        zz_1 city requires factions { greek, }
        {
            capability
            {
            }
            material wooden
            construction 2
            cost 600
            settlement_min village
            upgrades
            {
                zz_2 requires event_counter zz_open 1
            }
        }
        zz_2 city requires factions { greek, }
        {
            capability
            {
            }
            material wooden
            construction 2
            cost 600
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
sub = B.parse_text(UPG)
blk = sub.buildings[0].blocks[0]
check("the entry keeps its clause verbatim through a parse",
      blk.upgrades == ["zz_2 requires event_counter zz_open 1"])
check("and the level is still the first word",
      B.upgrade_name(blk.upgrades[0]) == "zz_2")
check("the detail payload takes it apart for the picker",
      B.clause_payload("event_counter zz_open 1")[0]["kind"] == "event_counter")
check("re-sending the same entry rewrites nothing",
      B.render_block(UPG, {"levels": [{"name": "zz_1",
                                       "upgrades": blk.upgrades}]}) == UPG)
edited = B.render_block(UPG, {"levels": [
    {"name": "zz_1", "upgrades": ["zz_2  requires event_counter zz_open 2"]}]})
check("an edited clause reaches the file on its own line",
      "zz_2  requires event_counter zz_open 2\n" in edited
      and B.parse_text(edited).buildings[0].blocks[0].upgrades
      == ["zz_2  requires event_counter zz_open 2"])
check("and nothing else in the block moved",
      len(edited.splitlines()) == len(UPG.splitlines()))
check("dropping the clause leaves a bare level name",
      "                zz_2\n" in B.render_block(
          UPG, {"levels": [{"name": "zz_1", "upgrades": ["zz_2"]}]}))


print("\n4) the sweeps: what the real files say about a tree")
if not installed:
    print("  (no mods installed — skipped)")
else:
    refs = clauses = backward = unknown = 0
    lines = levels = triple = deepest = 0
    plugins_missing = plugins_filled = temples = temples_with_religion = 0
    firstword_bad = 0
    guild_lines = guild_paired = 0
    for path in installed:
        m = Mod(path)
        for bl in m.edb.buildings:
            lines += 1
            deepest = max(deepest, len(bl.blocks))
            plugins_missing += bl.plugins_span == (0, 0)
            plugins_filled += bool(bl.plugins)
            if bl.name.startswith("temple_"):
                temples += 1
                temples_with_religion += bool(bl.religion)
            if bl.name.startswith("guild_"):
                guild_lines += 1
                g = m.data / "export_descr_guilds.txt"
                if g.exists():
                    body = g.read_text(encoding=B.ENCODING, errors="replace")
                    guild_paired += any(
                        ln.split()[1:2] == [bl.name]
                        for ln in body.splitlines()
                        if ln.strip().startswith("building "))
            order = {n: i for i, n in enumerate(bl.levels)}
            for blk in bl.blocks:
                levels += 1
                rec = m.building_loc.get(blk.name)
                triple += bool(rec and rec.name is not None
                               and rec.descr is not None
                               and rec.descr_short is not None)
                here = order.get(blk.name, -1)
                for entry in blk.upgrades:
                    refs += 1
                    clauses += len(entry.split()) > 1
                    firstword_bad += B.upgrade_name(entry) != entry.split()[0]
                    there = order.get(B.upgrade_name(entry))
                    if there is None:
                        unknown += 1
                    elif there <= here:
                        backward += 1

    print(f"  swept {lines} building lines / {levels} levels across "
          f"{len(installed)} mod(s)")
    check(f"all {refs} upgrade entries point at a level of their own line "
          f"({unknown} do not)", unknown == 0)
    check(f"and every one of them points FORWARD ({backward} do not) — which is "
          "why the scaffold chains in that direction", backward == 0)
    # How many real entries carry a clause depends entirely on which mods are
    # installed — 41 of 771 when the Phase 12 audit measured it, 0 of these 248
    # lines today. So that is reported, and what is ASSERTED is our own function
    # against every real entry; `upgrade_name`'s clause handling has a synthetic
    # case of its own in section 2, which is where the behaviour is pinned.
    print(f"  upgrade entries carrying their own requires clause: {clauses} "
          f"of {refs}")
    check(f"upgrade_name() is the first word of all {refs} real entries "
          f"({firstword_bad} disagree)", firstword_bad == 0)
    # The block is OPTIONAL: Third Age Reforged omits it on 45 of its 112 lines
    # and runs. What the scaffold actually leans on is that a real one is always
    # empty, so writing an empty one can lose nothing — that is what is asserted;
    # how many lines carry one at all is reported, not required.
    print(f"  plugins blocks: {lines - plugins_missing} of {lines} real lines "
          f"carry one ({plugins_missing} omit it entirely)")
    check(f"every plugins block in the {lines} real lines is empty "
          f"({plugins_filled} are not), which is why writing an empty one is safe",
          plugins_filled == 0)
    check(f"all {levels} real levels have all three text keys ({triple}) — which "
          "is why the scaffold writes three", triple == levels)
    check(f"all {temples} temple_ lines also carry a religion "
          f"({temples_with_religion})", temples == temples_with_religion)
    check(f"all {guild_lines} guild_ lines are named in export_descr_guilds.txt "
          f"({guild_paired})", guild_lines == guild_paired)
    check(f"the deepest real tree is {deepest} levels — past vanilla's "
          f"{B.VANILLA_MAX_LEVELS}, so that limit is said and not enforced",
          deepest > B.VANILLA_MAX_LEVELS)

    # ---- the capability vocabulary the picker offers ----
    used = {}
    for path in installed:
        for bl in Mod(path).edb.buildings:
            for blk in bl.blocks:
                for c in blk.capabilities + blk.faction_capabilities:
                    used[c.keyword] = used.get(c.keyword, 0) + 1
    unknown = sorted(k for k in used if k not in B.CAP_HELP)
    check(f"every one of the {len(used)} capability keywords the real files use "
          f"is in the picker ({unknown or 'none missing'})", not unknown)
    adopted = ("construction_cost_bonus_defensive", "construction_cost_bonus_military",
               "construction_cost_bonus_other", "construction_cost_bonus_religious",
               "construction_time_bonus_military", "construction_time_bonus_stone",
               "construction_time_bonus_wooden", "fire_risk", "gate_defences",
               "upgrade_bodyguard", "weapon_melee_simple")
    check(f"the {len(adopted)} taken from the reference sheet are all in the "
          "picker", all(k in B.CAP_HELP for k in adopted))
    check("and not one of them is used by any installed mod — they are adopted as "
          "engine vocabulary, not as a habit of these three files",
          not [k for k in adopted if k in used])
    check("every keyword has a group and the group is one the picker shows",
          all(B.CAP_META.get(k, ("Other", ""))[0] in B.CAP_GROUPS
              for k in B.CAP_HELP))
    check("and every keyword the picker knows is filed under a real group",
          all(k in B.CAP_META for k in B.CAP_HELP))
    check("a bonus keyword is one the sheet says takes `bonus n`",
          "law_bonus" in B.BONUS_CAPS
          and "construction_cost_bonus_defensive" in B.BONUS_CAPS
          and "wall_level" not in B.BONUS_CAPS)


# ---------------------------------------------------------------------------
print("\n5) create it for real, then undo it")
if not installed:
    print("  (no mods installed — skipped)")
else:
    src_root = installed[0]
    work = Path(tempfile.mkdtemp(prefix="ut_newtree_")) / src_root.name
    (work / "data" / "text").mkdir(parents=True)
    for rel in (B.EDB_REL, B.LOC_REL, "descr_sm_factions.txt", "descr_cultures.txt",
                "descr_religions.txt", "text/expanded.txt"):
        src = src_root / "data" / rel
        if src.exists():
            (work / "data" / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, work / "data" / rel)
    for c in B.cultures_of(Mod(src_root)):
        (work / "data" / "ui" / c / "buildings").mkdir(parents=True, exist_ok=True)

    mod = Mod(work)
    before_edb = mod.edb_path.read_bytes()
    before_loc = (mod.data / B.LOC_REL).read_bytes()
    lines_before = len(mod.edb.buildings)

    plan = B.plan_new_tree(mod, {
        "name": "toolkit_forge", "label": "Toolkit Forge", "settlement": "city",
        "levels": [{"name": "toolkit_forge_1", "label": "Toolkit Forge"},
                   {"name": "toolkit_forge_2", "label": "Great Toolkit Forge"},
                   {"name": "toolkit_forge_3", "label": "Toolkit Foundry"}]})
    check("the plan has no errors", not plan.errors)
    check("it says it is a create", plan.created)
    check("it rewrites both files", bool(plan.edb_text) and bool(plan.loc_text))
    check("it lists the cards rather than writing them",
          plan.slots and all("small" in s and "large" in s for s in plan.slots))
    check("one card row per level and culture",
          len(plan.slots) == 3 * len(B.cultures_of(mod)))
    check("the summary names the new line",
          "toolkit_forge" in plan.summary())

    rec = B.apply_edit(plan)
    after = Mod(work)
    fresh = after.edb.get("toolkit_forge")
    check("the line is in the file on disk", fresh is not None)
    check("with its three levels",
          fresh is not None and [b.name for b in fresh.blocks]
          == ["toolkit_forge_1", "toolkit_forge_2", "toolkit_forge_3"])
    check("and nothing else moved",
          len(after.edb.buildings) == lines_before + 1)
    check("the rest of the EDB is byte-identical",
          after.edb_path.read_bytes().startswith(before_edb.rstrip(b"\r\n")))
    check("the EDB still parses with no warnings", not after.edb.warnings)
    got = after.building_loc.get("toolkit_forge_2")
    check("the middle level's name reached the text file",
          got is not None and got.name == "Great Toolkit Forge")
    check("its two description keys are there too",
          got is not None and got.descr is not None and got.descr_short is not None)
    check("the tree's own heading key is written",
          (after.building_loc.get("toolkit_forge_name") or None) is not None
          and after.building_loc.get("toolkit_forge_name").name == "Toolkit Forge")
    found = B.line_checks(after.edb, fresh)
    check("the new line produces no findings from our own building checks",
          not found["gaps"] and not found["dupes"] and not found["mirror"])
    check("and a whole-mod check run is no worse than before it",
          len(B.checks(after, "")["lines"])
          <= len(B.checks(Mod(src_root), "")["lines"]))
    check("the log says it was a create", rec.get("action") == "building-new")
    check("both files were backed up",
          B.EDB_REL in rec["manifest"]["backed_up"]
          and B.LOC_REL in rec["manifest"]["backed_up"])

    check("a second create of the same name is refused",
          B.plan_new_tree(Mod(work), {"name": "toolkit_forge",
                                      "levels": [{"name": "zz_9"}]}).errors)

    undo(rec["id"])
    check("undo restores the EDB byte for byte",
          mod.edb_path.read_bytes() == before_edb)
    check("undo restores export_buildings.txt byte for byte",
          (mod.data / B.LOC_REL).read_bytes() == before_loc)

    # ---- a mod with no text file cannot have a tree created in it ----
    bare = Path(tempfile.mkdtemp(prefix="ut_bare_")) / "bare"
    (bare / "data").mkdir(parents=True)
    shutil.copy2(src_root / "data" / B.EDB_REL, bare / "data" / B.EDB_REL)
    p = B.plan_new_tree(Mod(bare), {"name": "zz_forge", "levels": [{"name": "zz_1"}]})
    check("no text/export_buildings.txt means refused, not half written",
          p.errors and not p.loc_text)
    shutil.rmtree(bare.parent, ignore_errors=True)
    shutil.rmtree(work.parent, ignore_errors=True)

shutil.rmtree(cfg, ignore_errors=True)
print(f"\n{sum(ok)}/{len(ok)} checks passed")
sys.exit(0 if all(ok) else 1)
