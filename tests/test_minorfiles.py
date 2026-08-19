"""The five minor campaign files: round-trip fidelity, the edit splices, the checks.

Phase 10a's gate is the gate every editor since Phase 8 has had: these parsers
save by splicing lines back into a hand-aligned file, so they are worth nothing
unless they can read every one of the 15 real files on this machine and hand each
one back byte for byte.

What is specific to these five, and what each part is here to catch:

  * **a religion's key is ``pip_path``, inside a brace block** — not the
    reference tool's ``icon`` / ``pip`` / ``anti_pip``, none of which appears in
    any real file. Its serialiser also drops the braces and the ``religions { … }``
    list, which is a file the engine cannot read at all.
  * **a resource's model line is ``item``, not ``model``** — same failure.
  * **a rebel ``unit`` line is a unit type and nothing else.** Their serialiser
    appends ``, 1, 1``; no real ``unit`` line has a comma and the names have
    spaces in them, so the rest of the line IS the name.
  * **a religion is written down three times** and Third Age 3 disagrees with
    itself on all three: a duplicate ``heretic`` block, a name missing from the
    ``religions`` list, and three religions in the lookup file that no longer
    exist.
  * **a culture's record does not end at its closing brace** — the forts, ports,
    watchtowers and agents come after it, and a parser that stops at the brace
    loses two thirds of the record.
  * **``descr_names.txt`` has no keywords at all**: a section header and a name
    are both one bare word, told apart the way the engine tells them apart.

Needs no game install for any of the above. When mods ARE installed it also
sweeps every real file, which is the check that actually matters.

    python -m tests.test_minorfiles
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import codeview, config, keyblock as kb, minorfiles as mf
from unittransfer.mod import Mod

ok = []


def check(label, cond):
    ok.append(bool(cond))
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}")


# --------------------------------------------------------------------------
# the samples — everything the real files do: comment banners, tab alignment,
# inline comments, blank lines inside a record, CRLF throughout.

REBELS_TXT = (
    ";;;;;;;;;;;;\t;;;;;;;;;;;;;;;;;;;;;;;;;;;;;\r\n"
    ";non region\t\t\tbased\r\n"
    "\r\n"
    "rebel_type\t\t\tbrigands\r\n"
    "category\t\t\tbrigands\r\n"
    "chance\t\t\t\t50\t; half the time\r\n"
    "description\t\t\tbrigands\r\n"
    "unit\t\t\t\tPeasants\r\n"
    "\r\n"
    ";===============================\r\n"
    "rebel_type\t\t\tEvil_Rebels\r\n"
    "category\t\t\tpeasant_revolt \r\n"
    "chance\t\t\t\t0\r\n"
    "description\t\t\tEvil_Rebels\r\n"
    "unit\t\t\t\tCave Trolls2\r\n"
    "unit\t\t\t\tMordor Orcs Invasion\r\n"
)

RESOURCES_TXT = (
    ";trade value of zero indicates it cannot be traded\r\n"
    "\r\n"
    "mine\t\t\t\tdata/models_strat/resource_mine.CAS\r\n"
    "\r\n"
    "type\t\t\t\ttimber\r\n"
    "trade_value\t\t\t5\r\n"
    "item\t\t\t\tdata/models_strat/resource_timber.CAS\r\n"
    "icon\t\t\t\tdata/ui/resources/resource_timber.tga\r\n"
    "\r\n"
    "type\t\t\t\tgold\r\n"
    "trade_value\t\t\t15\r\n"
    "item\t\t\t\tdata/models_strat/resource_gold.CAS\r\n"
    "icon\t\t\t\tdata/ui/resources/resource_gold.tga\r\n"
    "has_mine\r\n"
)

RELIGIONS_TXT = (
    "religions\r\n"
    "{\r\n"
    "\tcatholic\r\n"
    "\tislam\r\n"
    "\theretic\r\n"
    "}\r\n"
    "\r\n"
    "religion catholic\r\n"
    "{\r\n"
    "\tpip_path\tui/pips/pip_evil.tga\r\n"
    "}\r\n"
    "\r\n"
    "religion islam\r\n"
    "{\r\n"
    "\tpip_path\tui/pips/pip_numenorian.tga\r\n"
    "}\r\n"
)

CULTURES_TXT = (
    "symbol\tdata/models_strat/residences/symbol.CAS\r\n"
    "siege\tdata/models_strat/residences/siege_icon.CAS\r\n"
    "\r\n"
    "culture\t\t\tsouthern_european\r\n"
    "portrait_mapping\tsouthern_european\r\n"
    "rebel_standard_index\t0\r\n"
    "{\r\n"
    "village\r\n"
    "{\r\n"
    "\tnormal\t\tdata/models_strat/se_village.CAS,\t\tsettlement_eastern_level_1\r\n"
    "\tcard\t\tdata/ui/southern_european/cities/village.tga\r\n"
    "}\r\n"
    "town\r\n"
    "{\r\n"
    "\tnormal\t\tdata/models_strat/se_town.CAS,\t\tsettlement_eastern_level_2\r\n"
    "\tcard\t\tdata/ui/southern_european/cities/town.tga\r\n"
    "}\r\n"
    "}\r\n"
    "fort\t\t\tdata/models_strat/ne_fort.cas,\t\tfort_roman\r\n"
    "fort_cost\t\t500\r\n"
    "fort_wall\t\tdata/models_strat/ne_fort_buildings.cas\r\n"
    "fishing_village\t\tdata/models_strat/SE_port_villiage.CAS,\tport_roman_level_1\r\n"
    "port_land\t\tdata/models_strat/SE_port_02_wall.CAS,\tport_roman_level_2\r\n"
    "port_sea\t\tdata/models_strat/SE_port_02_buildings.CAS,\r\n"
    "watchtower\t\tdata/models_strat/DE_watchtower.CAS,\twatchtower_roman\r\n"
    "watchtower_cost\t\t200\r\n"
    "spy\t\t\tspy.tga\t\tspy_info.tga\t\tspy.tga\t\t350\t1\t1\r\n"
    "assassin\t\tassassin.tga\tassassin_info.tga\tassassin.tga\t500\t1\t1\r\n"
    ";;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;\r\n"
    "culture\t\t\tnorthern_european\r\n"
    "portrait_mapping\tnorthern_european\r\n"
    "rebel_standard_index\t1\r\n"
    "{\r\n"
    "village\r\n"
    "{\r\n"
    "\tnormal\t\tdata/models_strat/ne_village.CAS,\t\tsettlement_north_level_1\r\n"
    "\tcard\t\tdata/ui/northern_european/cities/village.tga\r\n"
    "}\r\n"
    "}\r\n"
)

NAMES_TXT = (
    ";; Holds non-localised names, per faction.\r\n"
    "\r\n"
    "faction: papal_states\r\n"
    "\r\n"
    "\tcharacters\r\n"
    "\t\tPopeSauron\r\n"
    "\t\tAzog\r\n"
    "\t\tBolg\r\n"
    "\r\n"
    "\twomen\r\n"
    "\t\tShelob\r\n"
    "\r\n"
    "faction: england\r\n"
    "\r\n"
    "\tcharacters\r\n"
    "\t\tGrishnakh\r\n"
)

print("round-tripping the samples")
rebels = mf.parse_rebels(REBELS_TXT)
check("a rebel file comes back byte for byte", rebels.text() == REBELS_TXT)
check("with no unknown constructs", rebels.warnings == [])
check("two rebel factions, the second with two units",
      [r.name for r in rebels.records] == ["brigands", "Evil_Rebels"]
      and [u.value for u in rebels.records[1].repeats]
      == ["Cave Trolls2", "Mordor Orcs Invasion"])
check("a unit name with spaces in it is the whole rest of the line",
      rebels.records[1].repeats[1].value == "Mordor Orcs Invasion")
check("an inline comment is not part of the value",
      rebels.records[0].get("chance") == "50")

resources = mf.parse_resources(RESOURCES_TXT)
check("a resources file comes back byte for byte",
      resources.text() == RESOURCES_TXT)
check("with no unknown constructs", resources.warnings == [])
check("`mine` is a file-level line, not a resource",
      list(resources.preamble) == ["mine"] and len(resources.records) == 2)
check("`item` is the model line, and `has_mine` is a flag",
      resources.records[1].get("item").endswith("resource_gold.CAS")
      and resources.records[1].flag("has_mine")
      and not resources.records[0].flag("has_mine"))

religions = mf.parse_religions(RELIGIONS_TXT)
check("a religions file comes back byte for byte",
      religions.text() == RELIGIONS_TXT)
check("with no unknown constructs", religions.warnings == [])
check("the `religions { … }` list is read as a list, not as blocks",
      religions.listed == ["catholic", "islam", "heretic"]
      and [r.name for r in religions.religions] == ["catholic", "islam"])
check("a religion's key is `pip_path`",
      religions.get("catholic").pip_path == "ui/pips/pip_evil.tga")

cultures = mf.parse_cultures(CULTURES_TXT)
check("a cultures file comes back byte for byte", cultures.text() == CULTURES_TXT)
check("with no unknown constructs", cultures.warnings == [])
se = cultures.get("southern_european")
check("the record does NOT end at the closing brace — the tail is part of it",
      se is not None and se.get("fort_cost") == "500"
      and "spy" in se.agents and len(se.ports) == 2)
check("the settlement ladder is read inside the brace",
      [l.name for l in se.levels] == ["village", "town"])
check("a `normal` line is a model and its settlement plan",
      se.level("village").model == "data/models_strat/se_village.CAS"
      and se.level("village").plan == "settlement_eastern_level_1")
check("a `port_sea` line's trailing comma is an empty second half",
      mf.split_pair(se.ports[1][1]) ==
      ("data/models_strat/SE_port_02_buildings.CAS", ""))
check("the preamble is not mistaken for a culture",
      sorted(cultures.preamble) == ["siege", "symbol"]
      and len(cultures.cultures) == 2)

names = mf.parse_names(NAMES_TXT)
check("a names file comes back byte for byte", names.text() == NAMES_TXT)
check("with no unknown constructs", names.warnings == [])
papal = names.get("papal_states")
check("a faction's sections are told apart from its names",
      [s.name for s in papal.sections] == ["characters", "women"]
      and [e.value for e in papal.section("characters").entries]
      == ["PopeSauron", "Azog", "Bolg"])
check("and the next faction starts a new record",
      [f.name for f in names.factions] == ["papal_states", "england"])

print("\nthe splices — an unchanged box must not rewrite its line")
for shape, text in ((mf.REBELS, REBELS_TXT), (mf.RESOURCES, RESOURCES_TXT)):
    rf = mf.parse_records(shape, text)
    same = True
    for rec in rf.records:
        block = rf.block_text(rec)
        edits = {"name": rec.name}
        for key in shape.order:
            edits[key] = rec.flag(key) if key in shape.flags else rec.get(key)
        if shape.repeat_kw:
            edits["units"] = [r.value for r in rec.repeats]
        same = same and mf.render_record(shape, block, edits) == block
    check(f"{shape.label.lower()}: a full-form save changes nothing", same)

block = rebels.block_text(rebels.records[1])
out = mf.render_record(mf.REBELS, block, {"chance": "25"})
check("changing one value rewrites one line and keeps its tab stops",
      out.count("\n") == block.count("\n")
      and "chance\t\t\t\t25" in out and "Cave Trolls2" in out)
out = mf.render_record(mf.REBELS, block, {"units": ["Cave Trolls2"]})
check("dropping a unit drops exactly its line", "Mordor Orcs" not in out
      and out.count("unit\t") == 1)
out = mf.render_record(mf.REBELS, block,
                       {"units": ["Cave Trolls2", "Mordor Orcs Invasion", "Bandits"]})
check("adding one copies the indent of the unit above it",
      out.rstrip().endswith("unit\t\t\t\tBandits"))

try:
    mf.render_record(mf.REBELS, block, {"category": ""})
    check("a blanked required line is refused", False)
except mf.MinorError as e:
    check("a blanked required line is refused", "category" in str(e))

gold = resources.block_text(resources.records[1])
out = mf.render_record(mf.RESOURCES, gold, {"has_mine": False})
check("clearing a flag deletes its whole line", "has_mine" not in out)
out = mf.render_record(mf.RESOURCES,
                       resources.block_text(resources.records[0]), {"has_mine": True})
check("setting one puts it back at its place in the order",
      out.rstrip().endswith("has_mine"))

cat = religions.block_text(religions.get("catholic"))
out = mf.render_religion(cat, {"pip_path": "ui/pips/pip_new.tga"})
check("a religion's pip is rewritten in place",
      "pip_path\tui/pips/pip_new.tga" in out and out.count("\n") == cat.count("\n"))
try:
    mf.render_religion(cat, {"pip_path": ""})
    check("a religion without a pip is refused", False)
except mf.MinorError:
    check("a religion without a pip is refused", True)

cul = cultures.block_text(se)
out = mf.render_culture(cul, {"fort_cost": "750"})
check("a culture's tail line is editable", "fort_cost\t\t750" in out)
out = mf.render_culture(cul, {"levels": {"village": {"card": "data/ui/x.tga"}}})
check("so is one settlement level's card, and nothing else moves",
      "card\t\tdata/ui/x.tga" in out and out.count("\n") == cul.count("\n")
      and "se_village.CAS" in out)
out = mf.render_culture(cul, {"levels": {"village": {"plan": "settlement_x"}}})
check("a level's model and plan are one line, rewritten together",
      "data/models_strat/se_village.CAS,\t\tsettlement_x" in out)
out = mf.render_culture(cul, {"agents": {"spy": {"cost": "900"}}})
check("an agent's cost is edited by position, and its seven columns stay put",
      "spy\t\t\tspy.tga\t\tspy_info.tga\t\tspy.tga\t\t900\t1\t1" in out)
try:
    mf.render_culture(cul, {"levels": {"citadel": {"card": "x.tga"}}})
    check("editing a level this culture has not got is refused", False)
except mf.MinorError as e:
    check("editing a level this culture has not got is refused", "citadel" in str(e))

fac = names.block_text(papal)
out = mf.render_names(fac, {"sections": {"characters": ["PopeSauron", "Azog", "Bolg"]}})
check("names: a full-form save changes nothing", out == fac)
out = mf.render_names(fac, {"sections": {"characters": ["PopeSauron", "Grond", "Bolg"]}})
check("renaming the second name rewrites one line",
      "\t\tGrond" in out and "Azog" not in out and out.count("\n") == fac.count("\n"))
out = mf.render_names(fac, {"sections": {"characters": ["PopeSauron"]}})
check("shortening the list drops the lines it lost",
      "Azog" not in out and "Shelob" in out)
try:
    mf.render_names(fac, {"sections": {"characters": ["Two Words"]}})
    check("a name with a space in it is refused", False)
except mf.MinorError:
    check("a name with a space in it is refused", True)

print("\nspans and fields, for the Code View widget")
spans = mf.record_spans(mf.REBELS, block)
check("a rebel's spans name every line it has",
      spans["name"] == [[1, 1]] and spans["chance"] == [[3, 3]]
      and spans["unit#2"] == [[6, 6]])
fields = dict(mf.record_fields(mf.REBELS, block))
check("and its fields carry the values", fields["category"] == "peasant_revolt"
      and fields["unit#1"] == "Cave Trolls2")
cspans = mf.culture_spans(cul)
check("a culture's level spans cover the whole level block",
      cspans["level.village"] == [[5, 9]]
      and cspans["level.village.card"] == [[8, 8]]
      and cspans["agent.spy"][0][0] > cspans["fort_cost"][0][0])
nspans = mf.names_spans(fac)
check("a faction's section span covers its names",
      nspans["characters"] == [[3, 6]] and nspans["characters#2"] == [[5, 5]])
check("but its fields are one row per section, not per name",
      dict(mf.names_fields(fac))["characters"] == "3 name(s)")

print("\nthe checks")
bad = mf.parse_rebels(REBELS_TXT.replace("category\t\t\tbrigands",
                                         "category\t\t\tbandit_revolt"))
found = mf.check_records(mf.REBELS, bad)
check("a category the engine does not know is reported",
      [f["kind"] for f in found] == ["unknown-category"])
found = mf.check_records(
    mf.RESOURCES, mf.parse_resources(RESOURCES_TXT.replace("type\t\t\t\tgold",
                                                           "type\t\t\t\tmithril")))
check("a resource the engine does not know is reported",
      any(f["kind"] == "unknown-resource" for f in found))

found = mf.check_religions(religions, ["catholic", "islam", "heretic", "pagan"],
                           {"catholic": "Catholic", "islam": "Islam"})
kinds = sorted(f["kind"] for f in found)
check("a religion in the list with no block is reported",
      "listed-without-block" in kinds)
check("a lookup entry this file no longer defines is reported",
      "stale-in-lookup" in kinds)
check("and a religion with no name in text/religions.txt is reported",
      "missing-name" in kinds)

twice = mf.parse_religions(RELIGIONS_TXT + "\r\nreligion islam\r\n{\r\n"
                           "\tpip_path\tui/pips/pip_islam.tga\r\n}\r\n")
check("a second block for the same religion is reported as dead text",
      any(f["kind"] == "duplicate-block" for f in mf.check_religions(twice)))

found = mf.check_cultures(cultures)
check("a level the other cultures here have is reported missing",
      any(f["kind"] == "missing-levels" and f["name"] == "northern_european"
          for f in found))
check("and a culture with no agents cannot recruit them",
      any(f["kind"] == "missing-agent" for f in found))
check("but a level NO culture here defines is not reported at all",
      not any("citadel" in f["message"] for f in found))

dupes = mf.parse_names(NAMES_TXT.replace("\t\tBolg\r\n", "\t\tBolg\r\n\t\tAzog\r\n"))
check("a name listed twice in one section is reported",
      any(f["kind"] == "duplicate-name" for f in mf.check_names(dupes)))

print("\nthe Code View kinds")
for kind in ("rebels", "resources", "religions", "cultures", "names"):
    check(f"`{kind}` is a registered kind", kind in codeview.KINDS)

doc = codeview.parse("rebels", block, {"ident": "Evil_Rebels"})
check("a rebel block parses into a document", doc.ident == "Evil_Rebels"
      and doc.spans["chance"] == [[3, 3]])
doc = codeview.render("rebels", block, {"chance": "25"}, {"ident": "Evil_Rebels"})
check("and a GUI edit round-trips through the same serialiser the save uses",
      "chance\t\t\t\t25" in doc.text)
for kind, text, ident in (("rebels", block, "Evil_Rebels"),
                          ("resources", gold, "gold"),
                          ("religions", cat, "catholic"),
                          ("cultures", cul, "southern_european"),
                          ("names", fac, "papal_states")):
    try:
        codeview.parse(kind, text, {"ident": ident + "_renamed"})
        check(f"`{kind}` refuses a rename in the text pane", False)
    except codeview.CodeViewError as e:
        check(f"`{kind}` refuses a rename in the text pane", "orphan" in str(e))
try:
    codeview.parse("religions", RELIGIONS_TXT, {})
    check("a pane holding two records is refused", False)
except codeview.CodeViewError as e:
    check("a pane holding two records is refused", "one at a time" in str(e))

print("\nthe editor: overview, detail, and saves that go to disk")
work = Path(tempfile.mkdtemp(prefix="tk-minor-")) / "TestMod"
(work / "data" / "text").mkdir(parents=True)
for rel, body in ((mf.REBELS.rel, REBELS_TXT), (mf.RESOURCES.rel, RESOURCES_TXT),
                  (mf.RELIGIONS_REL, RELIGIONS_TXT), (mf.CULTURES_REL, CULTURES_TXT),
                  (mf.NAMES_REL, NAMES_TXT),
                  (mf.RELIGIONS_LOOKUP_REL, "catholic\r\nislam\r\nheretic\r\n")):
    kb.write_text(work / "data" / rel, body, mf.ENCODING)
kb.write_text(work / "data" / mf.RELIGIONS_LOC_REL,
              "﻿¬ test\r\n{catholic}Followers of Sauron\r\n{islam}Men of the West\r\n",
              "utf-16")
kb.write_text(work / "data" / mf.REBELS_LOC_REL,
              "﻿¬ test\r\n{brigands}Brigands\r\n", "utf-16")
mod = Mod(work)

ov = mf.overview(mod, "rebels")
check("overview lists every record of the tab",
      [r["name"] for r in ov["records"]] == ["brigands", "Evil_Rebels"])
check("the localised name leads, the code name follows",
      ov["records"][0]["label"] == "Brigands (brigands)")
check("a row carries what that tab's list shows",
      ov["records"][1]["units"] == 2 and ov["records"][1]["category"] == "peasant_revolt")
check("and the tab strip comes with it, so the module needs one call",
      [t["id"] for t in ov["tabs"]] == ["rebels", "religions", "resources",
                                        "cultures", "names"])
check("an edit-only tab says so instead of offering dead buttons",
      mf.overview(mod, "resources")["actions"] == ["edit"]
      and "closed" in mf.overview(mod, "resources")["refused"]
      and mf.overview(mod, "cultures")["actions"] == ["edit"])

d = mf.detail(mod, "rebels", "Evil_Rebels")
check("detail carries the record, its spans and its text key",
      d["record"]["chance"] == "0" and d["spans"]["chance"] == [[3, 3]]
      and d["loc_tag"] == "Evil_Rebels" and d["loc_writable"] is True)
check("…and the four categories the engine knows, for the picker",
      d["vocab"]["categories"] == list(mf.REBEL_CATEGORIES))
d = mf.detail(mod, "resources", "timber")
check("a resource's name is read-only here, and says where to change it",
      d["loc_tag"] == "SMT_RESOURCE_TIMBER" and d["loc_writable"] is False
      and "Strings module" in d["loc_note"])

p = mf.plan(mod, {"tab": "rebels", "name": "Evil_Rebels", "action": "edit",
                  "edits": {"chance": "25", "units": ["Cave Trolls2",
                                                      "Mordor Orcs Invasion",
                                                      "Bandits"]},
                  "loc": {"Evil_Rebels": "Looters"}})
check("an edit plans the file and its text key together",
      p.payload()["ok"] and any("chance" in c for c in p.changes)
      and p.loc_writes == {"Evil_Rebels": "Looters"} and p.loc_new == ["Evil_Rebels"])
mf.apply(p)
rec = mf.parse_rebels(kb.read_text(work / "data" / mf.REBELS.rel,
                                   mf.ENCODING)).get("Evil_Rebels")
check("the edit landed on the right lines, tab stops and all",
      rec.get("chance") == "25" and len(rec.repeats) == 3
      and rec.repeats[2].value == "Bandits")
check("and the wording reached rebel_faction_descr.txt",
      mf.rebel_loc(Mod(work))["Evil_Rebels"] == "Looters")

p = mf.plan(mod, {"tab": "rebels", "name": "sea_raiders", "action": "add",
                  "edits": {"category": "pirates", "chance": "40",
                            "description": "sea_raiders",
                            "units": ["Peasants"]}})
check("a create writes the lines in the order the real files write them",
      [ln.split()[0] for ln in p.block.split("\n") if ln.strip()]
      == ["rebel_type", "category", "chance", "description", "unit"])
mf.apply(p)
check("it is on disk and the file still parses",
      mf.parse_rebels(kb.read_text(work / "data" / mf.REBELS.rel,
                                   mf.ENCODING)).get("sea_raiders") is not None)

print("\n  religions: one record, four files")
p = mf.plan(mod, {"tab": "religions", "name": "elven", "action": "add",
                  "edits": {"pip_path": "ui/pips/pip_elven.tga"},
                  "loc": {"elven": "The Firstborn"}})
check("adding a religion plans its block, the list, the lookup and its name",
      p.payload()["ok"]
      and any("religions` list" in c for c in p.changes)
      and mf.RELIGIONS_LOOKUP_REL in p.extra
      and p.loc_writes == {"elven": "The Firstborn"})
check("and it does not warn about the two files it is itself writing",
      not [f for f in p.findings
           if f["kind"] in ("missing-from-lookup", "missing-name")])
mf.apply(p)
after = mf.parse_religions(kb.read_text(work / "data" / mf.RELIGIONS_REL, mf.ENCODING))
check("all four landed",
      after.get("elven") is not None and "elven" in after.listed
      and "elven" in mf.parse_lookup(kb.read_text(
          work / "data" / mf.RELIGIONS_LOOKUP_REL, mf.ENCODING))
      and mf.religion_loc(Mod(work))["elven"] == "The Firstborn")
check("and the religion is not reported as half-defined",
      not [f for f in mf.check_any(Mod(work), "religions", after)
           if f["name"] == "elven"])

p = mf.plan(mod, {"tab": "religions", "name": "elven", "action": "delete"})
mf.apply(p)
after = mf.parse_religions(kb.read_text(work / "data" / mf.RELIGIONS_REL, mf.ENCODING))
check("deleting takes the block and the listing with it",
      after.get("elven") is None and "elven" not in after.listed
      and "elven" not in mf.parse_lookup(kb.read_text(
          work / "data" / mf.RELIGIONS_LOOKUP_REL, mf.ENCODING)))

print("\n  the refusals, and the rest of the tabs")
p = mf.plan(mod, {"tab": "resources", "name": "mithril", "action": "add"})
check("creating a resource is refused, with the reason",
      not p.payload()["ok"] and "closed" in p.errors[0])
p = mf.plan(mod, {"tab": "cultures", "name": "southern_european", "action": "delete"})
check("deleting a culture is refused, with the reason",
      not p.payload()["ok"] and "orphans every faction" in p.errors[0])
p = mf.plan(mod, {"tab": "resources", "name": "timber", "action": "edit",
                  "edits": {"trade_value": "9"},
                  "loc": {"SMT_RESOURCE_TIMBER": "Wood"}})
check("a resource edits its own file but never text/strat.txt",
      p.payload()["ok"] and not p.loc_writes
      and any("Strings module" in w for w in p.warnings))
mf.apply(p)
check("and the value landed", mf.parse_resources(kb.read_text(
      work / "data" / mf.RESOURCES.rel, mf.ENCODING)).get("timber")
      .get("trade_value") == "9")

p = mf.plan(mod, {"tab": "cultures", "name": "southern_european", "action": "edit",
                  "edits": {"fort_cost": "750",
                            "levels": {"village": {"card": "data/ui/x.tga"}}}})
mf.apply(p)
cul = mf.parse_cultures(kb.read_text(work / "data" / mf.CULTURES_REL,
                                     mf.ENCODING)).get("southern_european")
check("a culture's tail line and one settlement card save together",
      cul.get("fort_cost") == "750"
      and cul.level("village").values["card"] == "data/ui/x.tga")

p = mf.plan(mod, {"tab": "names", "name": "papal_states", "action": "edit",
                  "edits": {"sections": {"characters": ["PopeSauron", "Grond"]}}})
mf.apply(p)
fac = mf.parse_names(kb.read_text(work / "data" / mf.NAMES_REL,
                                  mf.ENCODING)).get("papal_states")
check("a names section is index-aligned: one rewritten, one dropped",
      [e.value for e in fac.section("characters").entries] == ["PopeSauron", "Grond"]
      and [e.value for e in fac.section("women").entries] == ["Shelob"])
p = mf.plan(mod, {"tab": "names", "name": "milan", "action": "add",
                  "edits": {"sections": {"characters": ["Ottone", "Guido"]}}})
mf.apply(p)
nf = mf.parse_names(kb.read_text(work / "data" / mf.NAMES_REL, mf.ENCODING))
check("a new faction arrives with a characters heading under it",
      nf.get("milan") is not None
      and [e.value for e in nf.get("milan").section("characters").entries]
      == ["Ottone", "Guido"])
check("and every file it has touched still round-trips byte for byte",
      all(mf.parse_any(t.id, kb.read_text(work / "data" / t.rel, mf.ENCODING)).text()
          == kb.read_text(work / "data" / t.rel, mf.ENCODING) for t in mf.TABS))

from unittransfer import transfer
rec = config.load_log()[-1]
transfer.undo(rec["id"])
check("and the log puts a whole job back",
      mf.parse_names(kb.read_text(work / "data" / mf.NAMES_REL,
                                  mf.ENCODING)).get("milan") is None)

print("\nthe real files")
root = config.get_med2_root()
mods = sorted((Path(root) / "mods").glob("*/data")) if root else []
mods = [m for m in mods if any((m / t.rel).exists() for t in mf.TABS)]
if not mods:
    print("  (no mods installed — the sweep that matters is skipped)")
else:
    swept = 0
    for data in mods:
        m = Mod(data.parent)
        for t in mf.TABS:
            path = data / t.rel
            if not path.exists():
                continue
            swept += 1
            text = kb.read_text(path, mf.ENCODING)
            if t.id in ("rebels", "resources"):
                shape = mf.REBELS if t.id == "rebels" else mf.RESOURCES
                parsed = mf.parse_records(shape, text)
                records = parsed.records
                found = mf.check_records(shape, parsed, m)
                rerender = [mf.render_record(
                    shape, parsed.block_text(r),
                    dict({"name": r.name},
                         **{k: (r.flag(k) if k in shape.flags else r.get(k))
                            for k in shape.order},
                         units=[u.value for u in r.repeats]))
                    == parsed.block_text(r) for r in records]
            elif t.id == "religions":
                parsed = mf.parse_religions(text)
                records = parsed.religions
                lookup = data / mf.RELIGIONS_LOOKUP_REL
                found = mf.check_religions(
                    parsed,
                    mf.parse_lookup(kb.read_text(lookup, mf.ENCODING))
                    if lookup.exists() else None,
                    mf.religion_loc(m))
                rerender = [mf.render_religion(parsed.block_text(r),
                                               {"name": r.name,
                                                "pip_path": r.pip_path})
                            == parsed.block_text(r) for r in records]
            elif t.id == "cultures":
                parsed = mf.parse_cultures(text)
                records = parsed.cultures
                found = mf.check_cultures(parsed)
                rerender = [mf.render_culture(parsed.block_text(c), dict(
                    {"name": c.name},
                    **{k: c.get(k) for k in mf.CULTURE_HEAD + mf.CULTURE_TAIL
                       if k in c.lines},
                    levels={l.name: {"model": l.model, "plan": l.plan,
                                     "card": l.values.get("card", "")}
                            for l in c.levels},
                    agents={a: {"card": tk[0], "info_card": tk[1], "pip": tk[2],
                                "cost": tk[3]}
                            for a, (tk, _) in c.agents.items() if len(tk) >= 4}))
                    == parsed.block_text(c) for c in records]
            else:
                parsed = mf.parse_names(text)
                records = parsed.factions
                found = mf.check_names(parsed, m)
                rerender = [mf.render_names(parsed.block_text(f), {
                    "name": f.name,
                    "sections": {s.name: [e.value for e in s.entries]
                                 for s in f.sections}})
                    == parsed.block_text(f) for f in records]

            name = f"{data.parent.name}/{t.rel}"
            check(f"{name}: {len(records)} {t.noun}(s) come back byte for byte",
                  parsed.text() == text)
            check(f"{name}: every construct in it is named", parsed.warnings == [])
            check(f"{name}: every record re-renders to itself unchanged",
                  all(rerender))
            check(f"{name}: {len(found)} findings, and they are not a flood",
                  len(found) < max(4, len(records) * 2))
    print(f"  swept {swept} real file(s) across {len(mods)} mod(s)")

    # the two facts the whole module rests on, measured rather than assumed
    seen = set()
    for data in mods:
        path = data / mf.RESOURCES.rel
        if path.exists():
            seen |= {r.name for r in
                     mf.parse_resources(kb.read_text(path, mf.ENCODING)).records}
    if seen:
        check("every real resource name is one of the 28 the engine knows",
              seen <= set(mf.KNOWN_RESOURCES))
    commas = 0
    for data in mods:
        path = data / mf.REBELS.rel
        if path.exists():
            commas += sum(
                1 for r in mf.parse_rebels(kb.read_text(path, mf.ENCODING)).records
                for u in r.repeats if "," in u.value)
    check("no real rebel `unit` line has a comma in it — the name is the whole line",
          commas == 0)

print(f"\n{sum(ok)}/{len(ok)} checks passed")
sys.exit(0 if all(ok) else 1)
