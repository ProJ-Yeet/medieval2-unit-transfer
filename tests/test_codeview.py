"""Code View: the span map, the two edit directions, and the save that follows.

The widget's whole claim is that the text pane is not a picture of the file but
the file — so this suite is about fidelity, not about pixels:

  * a span map that lands on the right lines, including repeated keys, comments,
    blank lines and a block that does not start at line 1
  * ``render`` (a box was typed into) goes through the SAME serialiser as a save,
    so what the pane shows is what gets written — checked by planning the edit
    and comparing bytes
  * ``parse`` (the text was typed into) either returns fields or says why not,
    and the refusals are the two that would corrupt a file: no ``type`` line, and
    two unit blocks in a pane that replaces one
  * a hand-edited block survives to disk verbatim — line order, indent, comments
    and all — which is the thing field overrides alone cannot do
  * the endpoints stay fast enough to run on every keystroke (they are debounced
    at 250 ms; the budget is 50 ms) against a DaC-sized EDU

Needs no game install: the EDU here is written by the test.

    python -m tests.test_codeview
"""
import json
import shutil
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import codeview, config, edit
from unittransfer import edu as edu_mod

ok = []


def check(label, cond):
    ok.append(bool(cond))
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}")


# A block with everything the span map has to survive: a leading comment, blank
# lines, a repeated key (three officers), a multi-word key (`era 0`), an inline
# comment and a trailing comment before the next unit.
BLOCK = """type             Test Spearmen
dictionary       test_spearmen      ; Test Spearmen
category         infantry
class            spearmen
voice_type       Light
soldier          test_spear, 60, 0, 1.2

officer          test_officer_flag
officer          test_officer_drum
officer          test_officer_horn
mount_effect     elephant -4, camel -4
attributes       sea_faring, hide_forest, can_withdraw
formation        1.2, 1.4, 2.4, 2.8, 4, square
stat_health      1, 0
stat_pri         7, 3, no, 0, 0, melee, melee_blade, piercing, spear, 25, 1
stat_pri_attr    spear, spear_bonus_4
ownership        england, france
era 0            england
era 1            england, france
era 2            france
; the last line of this unit is a comment
"""

SECOND = """type             Test Archers
dictionary       test_archers       ; Test Archers
category         infantry
class            missile
soldier          test_archer, 40, 0, 1
"""

PREAMBLE = ";; export_descr_unit.txt - written by tests/test_codeview.py\n\n"


# ---------------------------------------------------------------------------
print("\n== the span map lands on the right lines ==")

spans = edu_mod.block_spans(BLOCK)
lines = BLOCK.splitlines()


def line_of(label):
    got = spans.get(label)
    return lines[got[0][0] - 1] if got else None


check("every field has exactly one span",
      all(len(v) == 1 and v[0][0] == v[0][1] for v in spans.values()))
check("`type` is line 1", spans["type"] == [[1, 1]])
check("`dictionary` (with an inline comment) is line 2", spans["dictionary"] == [[2, 2]])
check("the three officers are numbered and separate",
      [spans["officer"], spans["officer#2"], spans["officer#3"]]
      == [[[8, 8]], [[9, 9]], [[10, 10]]])
check("each officer span points at its own line",
      (line_of("officer").split()[1], line_of("officer#3").split()[1])
      == ("test_officer_flag", "test_officer_horn"))
check("the multi-word key `era 1` is one field, not two",
      line_of("era 1").startswith("era 1"))
check("no span points at the blank line (line 7)",
      all(v[0][0] != 7 for v in spans.values()))
check("no span points at the trailing comment",
      all(not lines[v[0][0] - 1].lstrip().startswith(";") for v in spans.values()))

fields = dict(edu_mod.block_fields(BLOCK))
check("block_fields and block_spans agree label for label",
      set(fields) == set(spans))
check("every span's line really starts with its key",
      all(lines[spans[l][0][0] - 1].strip().startswith(edu_mod.split_label(l)[0].split()[0])
          for l in spans))


# ---------------------------------------------------------------------------
print("\n== parsing what the user typed ==")

doc = codeview.parse("edu", BLOCK)
check("a good block parses", doc.ident == "Test Spearmen" and doc.kind == "edu")
check("the text comes back byte-identical", doc.text == BLOCK)
check("fields and spans are both populated",
      len(doc.fields) == len(doc.spans) == len(spans))
check("payload() is JSON-serialisable for the page",
      isinstance(json.dumps(doc.payload()), str))

try:
    codeview.parse("edu", "category infantry\nclass spearmen\n")
    check("text with no `type` line is refused", False)
except codeview.CodeViewError as e:
    check("text with no `type` line is refused", "`type` line" in e.message)

try:
    codeview.parse("edu", BLOCK + SECOND)
    check("two unit blocks in one pane are refused", False)
except codeview.CodeViewError as e:
    check("two unit blocks in one pane are refused", "2 unit blocks" in e.message)
    check("…and it points at the second block's line",
          e.line == len(BLOCK.splitlines()) + 1)

# A block that does not start at line 1 — the pane shows whatever text it is
# given, so the spans have to be shifted by the lines above it.
shifted = codeview.parse("edu", ";; a note above the unit\n\n" + BLOCK)
check("spans shift when the block starts further down",
      shifted.spans["type"] == [[3, 3]] and shifted.spans["officer#3"] == [[12, 12]])
check("…and the shifted spans still point at the right text",
      (";; a note above the unit\n\n" + BLOCK).splitlines()[
          shifted.spans["stat_pri"][0][0] - 1].startswith("stat_pri "))

try:
    codeview.parse("nope", BLOCK)
    check("an unknown kind is refused", False)
except codeview.CodeViewError as e:
    check("an unknown kind is refused", "no code view" in e.message)


# ---------------------------------------------------------------------------
print("\n== rendering what the user typed in a box ==")

r = codeview.render("edu", BLOCK, {"overrides": {"stat_health": "2, 0"}})
check("a box edit reaches the text", "stat_health      2, 0" in r.text)
check("…and only that line changed",
      sum(1 for a, b in zip(BLOCK.splitlines(), r.text.splitlines()) if a != b) == 1)
check("the indent of the edited line is kept",
      r.text.splitlines()[spans["stat_health"][0][0] - 1].startswith("stat_health   "))
check("comments and blank lines survive a render",
      r.text.splitlines()[6] == "" and r.text.splitlines()[-1].lstrip().startswith(";"))
check("the render's spans match its own text",
      r.spans == edu_mod.block_spans(r.text))

r2 = codeview.render("edu", BLOCK, {"removals": ["officer#2"]})
check("a removal drops exactly one line",
      len(r2.text.splitlines()) == len(BLOCK.splitlines()) - 1)
check("…the right one", "test_officer_drum" not in r2.text
      and "test_officer_flag" in r2.text and "test_officer_horn" in r2.text)
check("the officers renumber after a removal",
      r2.spans.get("officer#3") is None and "officer#2" in r2.spans)

check("no edits at all is a byte-identical round trip",
      codeview.render("edu", BLOCK, {}).text == BLOCK)


# ---------------------------------------------------------------------------
print("\n== the pane shows what a save would write ==")

cfg = Path(tempfile.mkdtemp(prefix="ut_cfg_"))
config.CONFIG_DIR = cfg
config.BACKUP_DIR = cfg / "backups"
config.SETTINGS_PATH = cfg / "settings.json"
config.LOG_PATH = cfg / "transfers.json"

med2 = Path(tempfile.mkdtemp(prefix="ut_med2_"))
mod_root = med2 / "mods" / "CodeViewMod"
data = mod_root / "data"
(data / "text").mkdir(parents=True)
(data / "unit_models").mkdir(parents=True)
(data / "export_descr_unit.txt").write_text(PREAMBLE + BLOCK + SECOND,
                                            encoding=edu_mod.ENCODING)
(data / "text" / "export_units.txt").write_text(
    "﻿{test_spearmen}Test Spearmen\r\n{test_spearmen_descr}Spears.\r\n"
    "{test_spearmen_descr_short}Spears.\r\n", encoding="utf-16-le")
# an empty but valid archive header — nothing here edits a model, but plan_edit
# parses the modeldb on the way past
(data / "unit_models" / "battle_models.modeldb").write_text(
    "22 serialization::archive 3 0 0 0 0 0 0 0\n", encoding="latin-1")
config.save_settings(med2_root=str(med2))

from unittransfer.mod import Mod

mod = Mod(mod_root)
edu_path = data / "export_descr_unit.txt"


def fresh_mod():
    return Mod(mod_root)


doc = codeview.unit_document(mod, "Test Spearmen")
check("the mod's unit loads into a code view", doc.ident == "Test Spearmen")
check("the loaded text is the block as the file stores it", doc.text == BLOCK)

# what the pane would show after a box edit…
shown = codeview.render("edu", doc.text, {"overrides": {"stat_cost": "1, 500, 250, 90, 120, 500"}})
check("a field the unit does not have is added by the render",
      "stat_cost" in shown.spans)
# …and what the save actually writes
plan = edit.plan_edit(fresh_mod(), edit.request_from_dict(
    {"unit": "Test Spearmen",
     "field_overrides": {"stat_cost": "1, 500, 250, 90, 120, 500"}}))
check("the pane's text is byte-identical to the block the save plans",
      plan.edu_block == shown.text)


# ---------------------------------------------------------------------------
print("\n== a hand-edited block reaches disk verbatim ==")

# Reordered lines, a new comment, a doubled indent: none of it is expressible as
# a field override, which is exactly why raw_block exists.
HAND = BLOCK.replace("category         infantry\nclass            spearmen\n",
                     "class            spearmen\ncategory         infantry\n") \
            .replace("stat_health      1, 0",
                     "; buffed for the test\nstat_health      3, 0")

plan = edit.plan_edit(fresh_mod(), edit.request_from_dict(
    {"unit": "Test Spearmen", "raw_block": HAND}))
check("a hand-edited block plans without errors", not plan.errors)
check("the plan says so", "unit block edited as text" in plan.changes)
check("the planned block is what was typed, to the byte", plan.edu_block == HAND)

# a box edited *after* the text still lands, on top of the typed block
plan = edit.plan_edit(fresh_mod(), edit.request_from_dict(
    {"unit": "Test Spearmen", "raw_block": HAND,
     "field_overrides": {"voice_type": "Heavy"}}))
check("a later box edit applies on top of the typed block",
      "voice_type       Heavy" in plan.edu_block
      and "; buffed for the test" in plan.edu_block)

edit.apply_edit(plan)
after = edu_path.read_text(encoding=edu_mod.ENCODING)
check("the file keeps its preamble", after.startswith(PREAMBLE))
check("the other unit is untouched", after.endswith(SECOND))
check("the reordered lines are on disk",
      "class            spearmen\ncategory         infantry\n" in after)
check("the hand-written comment is on disk", "; buffed for the test" in after)
check("the mod still parses to two units",
      len(edu_mod.parse_text(after).units) == 2)
check("…and the edited one reads back as one code view",
      codeview.parse("edu", fresh_mod().edu.by_type()["Test Spearmen"].raw).ident
      == "Test Spearmen")

# and undo puts it all back
from unittransfer.transfer import undo as undo_transfer

recs = config.load_log()
undo_transfer(recs[-1]["id"])
check("undo restores the original file",
      edu_path.read_text(encoding=edu_mod.ENCODING) == PREAMBLE + BLOCK + SECOND)


# ---------------------------------------------------------------------------
print("\n== text the parser rejects never reaches the file ==")

before = edu_path.read_bytes()
plan = edit.plan_edit(fresh_mod(), edit.request_from_dict(
    {"unit": "Test Spearmen", "raw_block": "category infantry\nclass spearmen\n"}))
check("a block with no `type` line is a plan error",
      any("isn't a valid unit block" in e for e in plan.errors))
try:
    edit.apply_edit(plan)
    check("…and applying it is refused", False)
except ValueError as e:
    check("…and applying it is refused", "cannot apply" in str(e))
check("the file was not touched", edu_path.read_bytes() == before)

plan = edit.plan_edit(fresh_mod(), edit.request_from_dict(
    {"unit": "Test Spearmen", "raw_block": BLOCK + SECOND}))
check("two blocks in the pane is a plan error", bool(plan.errors))

renamed = BLOCK.replace("type             Test Spearmen", "type             Renamed Spearmen")
plan = edit.plan_edit(fresh_mod(), edit.request_from_dict(
    {"unit": "Test Spearmen", "raw_block": renamed}))
check("renaming `type` in the text is allowed but warned about",
      not plan.errors and any("Identity tab" in w for w in plan.warnings))
plan = edit.plan_edit(fresh_mod(), edit.request_from_dict(
    {"unit": "Test Spearmen", "raw_block": BLOCK, "new_type": "Proper Rename"}))
check("an Identity-tab rename beside a text edit still rewrites the line",
      "type             Proper Rename" in plan.edu_block and not plan.warnings)


# ---------------------------------------------------------------------------
print("\n== the EDB kind: one building line ==")

from unittransfer import buildings as bld_mod

EDB = """;; export_descr_buildings.txt - written by tests/test_codeview.py

hidden_resources sherwood

building test_barracks
{
\tconvert_to 1
\tlevels test_muster, test_barracks
\t{
\t\ttest_muster requires factions { england, }
\t\t{
\t\t\tcapability
\t\t\t{
\t\t\t\trecruit_pool "Test Spearmen"  1  0.5  2  0  requires factions { england, }
\t\t\t\thappiness_bonus bonus 1        ; a hand-written comment
\t\t\t}
\t\t\tmaterial wooden
\t\t\tconstruction  1
\t\t\tcost  400
\t\t\tsettlement_min village
\t\t\tupgrades
\t\t\t{
\t\t\t\ttest_barracks
\t\t\t}
\t\t}
\t\ttest_barracks requires factions { england, }
\t\t{
\t\t\tcapability
\t\t\t{
\t\t\t\trecruit_pool "Test Archers"  1  0.4  2  0  requires factions { england, }
\t\t\t}
\t\t\tmaterial wooden
\t\t\tconstruction  2
\t\t\tcost  800
\t\t\tsettlement_min town
\t\t\tupgrades
\t\t\t{
\t\t\t}
\t\t}
\t}
\tplugins
\t{
\t}
}

building other_line
{
\tlevels other_one
\t{
\t\tother_one requires factions { france, }
\t\t{
\t\t\tmaterial stone
\t\t\tcost  100
\t\t}
\t}
}
"""

(data / "export_descr_buildings.txt").write_text(EDB, encoding=bld_mod.ENCODING)
(data / "text").mkdir(exist_ok=True)
(data / "text" / "export_buildings.txt").write_text(
    "﻿{test_muster}Muster Field\r\n{test_barracks}Barracks\r\n", encoding="utf-16-le")

edb_mod = fresh_mod()
edoc = codeview.building_document(edb_mod, "test_barracks")
edb_lines = edoc.text.split("\n")
check("a building line loads into a code view", edoc.ident == "test_barracks")
check("the text is the block only — not the file, not the next line",
      edoc.text.startswith("building test_barracks")
      and "other_line" not in edoc.text and "hidden_resources" not in edoc.text)
check("`building` is line 1", edoc.spans["building"] == [[1, 1]])
check("a level's whole block is one span",
      edb_lines[edoc.spans["level:test_muster"][0][0] - 1].strip()
      .startswith("test_muster requires"))
check("a scalar lands on its own line",
      edb_lines[edoc.spans["level:test_muster:cost"][0][0] - 1].strip() == "cost  400")
check("the same scalar in the other level is a different line",
      edb_lines[edoc.spans["level:test_barracks:cost"][0][0] - 1].strip() == "cost  800")
check("upgrades is a range, brace to brace",
      edb_lines[edoc.spans["level:test_muster:upgrades"][0][0] - 1].strip() == "upgrades"
      and edb_lines[edoc.spans["level:test_muster:upgrades"][0][1] - 1].strip() == "}")
check("each capability line has its own span",
      "recruit_pool" in edb_lines[edoc.spans["level:test_muster:cap#1"][0][0] - 1]
      and "happiness_bonus" in edb_lines[edoc.spans["level:test_muster:cap#2"][0][0] - 1])
check("a capability is also addressable by the line number its row carries",
      any(k.startswith("capline#") for k in edoc.spans))
check("the boxes can be rebuilt from it (a detail payload rides along)",
      edoc.detail and [l["name"] for l in edoc.detail["levels"]]
      == ["test_muster", "test_barracks"])

check("a block with no `building` line is refused", True)
for text, why in ((";\tnot a building\n", "building line"),
                  (edoc.text + "\nbuilding second\n{\n\tlevels a\n\t{\n\t}\n}\n",
                   "building lines")):
    try:
        codeview.parse("edb", text)
        check(f"refused: {why}", False)
    except codeview.CodeViewError as e:
        check(f"refused: {why}", why in e.message)

r = codeview.render("edb", edoc.text,
                    {"levels": [{"name": "test_muster", "scalars": {"cost": "4242"}}]},
                    {"mod": edb_mod})
check("a box edit reaches the building text", "cost 4242" in r.text)
check("…and the hand-written comment beside another line survives",
      "; a hand-written comment" in r.text)
check("no edits is a byte-identical round trip",
      codeview.render("edb", edoc.text, {}, {"mod": edb_mod}).text == edoc.text)

# what the pane shows must be what the save writes, to the byte
body = {"mod": "CodeViewMod", "line": "test_barracks",
        "levels": [{"name": "test_muster", "scalars": {"cost": "4242"}}]}
bplan = bld_mod.plan_edit(fresh_mod(), body)
bl = fresh_mod().edb.get("test_barracks")
written = "".join(bplan.edb_text.splitlines(keepends=True)[bl.start:bl.end])
check("the building pane is byte-identical to the block the save plans",
      written == r.text)

# hand-edited text reaches disk verbatim
EDB_HAND = edoc.text.replace("\t\t\tmaterial wooden\n\t\t\tconstruction  1\n",
                             "\t\t\t; reordered by hand\n"
                             "\t\t\tconstruction  1\n\t\t\tmaterial stone\n", 1)
bplan = bld_mod.plan_edit(fresh_mod(),
                          {"mod": "CodeViewMod", "line": "test_barracks",
                           "raw_block": EDB_HAND})
check("a hand-edited building line plans without errors", not bplan.errors)
check("the plan says so", any("edited as text" in c for c in bplan.changes))
bld_mod.apply_edit(bplan)
after_edb = (data / "export_descr_buildings.txt").read_text(encoding=bld_mod.ENCODING)
check("the reordered lines are on disk",
      "construction  1\n\t\t\tmaterial stone" in after_edb)
check("the hand-written comment is on disk", "; reordered by hand" in after_edb)
check("the file's other building line is untouched",
      "building other_line" in after_edb and "cost  100" in after_edb)
check("what came before the line is untouched",
      after_edb.startswith(";; export_descr_buildings.txt"))
check("the EDB still parses to two lines",
      len(bld_mod.parse_text(after_edb).buildings) == 2)

undo_transfer(config.load_log()[-1]["id"])
check("undo restores the EDB",
      (data / "export_descr_buildings.txt").read_text(encoding=bld_mod.ENCODING) == EDB)

bplan = bld_mod.plan_edit(fresh_mod(),
                          {"mod": "CodeViewMod", "line": "test_barracks",
                           "raw_block": edoc.text.replace("building test_barracks",
                                                          "building renamed_barracks")})
check("renaming a building line in the text is refused, not warned about",
      any("has to stay" in e for e in bplan.errors))
bplan = bld_mod.plan_edit(fresh_mod(),
                          {"mod": "CodeViewMod", "line": "test_barracks",
                           "raw_block": "; nothing here\n"})
check("text that is not a building line is a plan error",
      any("isn't a valid building line" in e for e in bplan.errors))


# ---------------------------------------------------------------------------
print("\n== the BMDB kind: one battle-model entry ==")

from unittransfer import modeldb as mdb


def s(x):
    return f"{len(x)} {x}"


ENTRY = (" \n" + s("test_model") + " \n1 1 \n"
         + s("unit_models/test/test_lod0.mesh") + " 10000 \n1 \n"
         + s("england") + " \n"
         + s("unit_models/test/textures/test.texture") + " \n"
         + s("unit_models/test/textures/test_normal.texture") + " \n"
         + s("unit_sprites/test_sprite.spr") + " \n0 \n1 \n"
         + s("MTW2_Spear") + " " + s("MTW2_Spear_Primary") + " " + s("fs_test_shield")
         + " 1 " + s("MTW2_Spear") + " 1 " + s("MTW2_Sword") + " \n0 0 0 0 0 0 0 \n")
# the vanilla "blank" sentinel: without it the engine pads the first real entry
# with reserved ints, a quirk this test has no reason to carry
BLANK = s("blank") + " " + " ".join(["0"] * 39) + "\n"
MODELDB = "22 serialization::archive 3 0 0 0 0 2 0 0\n" + BLANK + ENTRY
(data / "unit_models" / "battle_models.modeldb").write_text(MODELDB, encoding=mdb.ENCODING)

bm_mod = fresh_mod()
check("the hand-built modeldb parses to one entry", len(bm_mod.modeldb.entries) == 1)
bdoc = codeview.entry_document(bm_mod, "test_model")
bm_lines = bdoc.text.split("\n")
check("an entry loads into a code view", bdoc.ident == "test_model")
check("the text is the entry byte for byte", bdoc.text == bm_mod.modeldb.entries[0].raw)
check("the entry's name has a span",
      "test_model" in bm_lines[bdoc.spans["name"][0][0] - 1])
check("each path slot has a span",
      "test_lod0.mesh" in bm_lines[bdoc.spans["path#0"][0][0] - 1]
      and "test.texture" in bm_lines[bdoc.spans["path#1"][0][0] - 1])
check("a texture is also addressable by faction and kind, as the boxes are",
      bdoc.spans["fac:england:texture"] == bdoc.spans["path#1"]
      and bdoc.spans["fac:england:sprite"] == bdoc.spans["path#3"])
check("the card can be rebuilt from it",
      bdoc.detail and bdoc.detail["factions"] == ["england"])
check("the note warns about the length prefixes", "length" in bdoc.note)

bctx = {"pad": False, "base": ENTRY}
check("no edits is a byte-identical round trip",
      codeview.render("bmdb", ENTRY, {}, bctx).text == ENTRY)
r = codeview.render("bmdb", ENTRY, {"paths": {1: "unit_models/test/textures/new.texture"}}, bctx)
check("a box edit reaches the entry text, prefix and all",
      f"{len('unit_models/test/textures/new.texture')} "
      "unit_models/test/textures/new.texture" in r.text)
check("…and the entry still reads back",
      mdb.path_slots_raw(r.text)[1]["value"] == "unit_models/test/textures/new.texture")

# the whole point of this kind's repair
STALE = ENTRY.replace("unit_models/test/textures/test.texture",
                      "unit_models/test/textures/test_v2.texture")
try:
    codeview.parse("bmdb", STALE, bctx)
    check("a stale length prefix is refused", False)
except codeview.CodeViewError as e:
    stale_line = next(i for i, l in enumerate(STALE.split("\n"), 1) if "test_v2" in l)
    right = len("unit_models/test/textures/test_v2.texture")
    check("a stale length prefix is refused", "length says" in e.message)
    check("…naming the line and the number it should be",
          e.line == stale_line and f"{right} characters" in e.message)
fixed = codeview.repair("bmdb", STALE, bctx)
check("Fix lengths makes it readable",
      mdb.path_slots_raw(fixed.text)[1]["value"]
      == "unit_models/test/textures/test_v2.texture")
stale_rows, fixed_rows = STALE.split("\n"), fixed.text.split("\n")
check("…and changes nothing but that one number",
      len(stale_rows) == len(fixed_rows)
      and [i for i, (a, b) in enumerate(zip(stale_rows, fixed_rows), 1) if a != b]
      == [stale_line]
      and fixed_rows[stale_line - 1] == f"{right} " + stale_rows[stale_line - 1]
                                                      .split(" ", 1)[1])
check("repairing text that is already right changes nothing",
      codeview.repair("bmdb", ENTRY, bctx).text == ENTRY)
try:
    codeview.parse("bmdb", ENTRY + s("stray") + "\n", bctx)
    check("a second record in the pane is refused", False)
except codeview.CodeViewError as e:
    check("a second record in the pane is refused", "left over" in e.message)

# and the hand-edited entry reaches disk
HAND_ENTRY = codeview.repair("bmdb", STALE, bctx).text
eplan = edit.plan_edit(fresh_mod(), edit.request_from_dict(
    {"unit": "Test Spearmen",
     "model_edits": [{"entry": "test_model", "raw_entry": HAND_ENTRY}]}))
check("a hand-edited entry plans without errors", not eplan.errors)
check("the plan says so", any("edited as text" in c for c in eplan.changes))
edit.apply_edit(eplan)
after_db = (data / "unit_models" / "battle_models.modeldb").read_text(encoding=mdb.ENCODING)
check("the edited path is on disk", "test_v2.texture" in after_db)
check("the modeldb still parses", len(mdb.parse_text(after_db).entries) == 1)
undo_transfer(config.load_log()[-1]["id"])
check("undo restores the modeldb",
      (data / "unit_models" / "battle_models.modeldb").read_text(
          encoding=mdb.ENCODING) == MODELDB)

eplan = edit.plan_edit(fresh_mod(), edit.request_from_dict(
    {"unit": "Test Spearmen",
     "model_edits": [{"entry": "test_model", "raw_entry": STALE}]}))
check("text with a stale prefix never reaches the modeldb",
      any("isn't a valid modeldb entry" in e for e in eplan.errors))
eplan = edit.plan_edit(fresh_mod(), edit.request_from_dict(
    {"unit": "Test Spearmen",
     "model_edits": [{"entry": "test_model",
                      "raw_entry": mdb.rename_entry_raw(ENTRY, "other_name")}]}))
check("renaming an entry in the text is refused — the rename box chases the EDU",
      any("use the rename box" in e for e in eplan.errors))


# ---------------------------------------------------------------------------
print("\n== hiding the comment lines is DISPLAY ONLY ==")

# The block as a real mod has it: a faction distinguisher above it, a note
# somebody left in the middle, an inline comment that belongs to a field, and a
# comment as the last line. Only three of those four are comment-ONLY lines.
COMMENTED = ";; ---- England ----\n" + BLOCK.replace(
    "stat_health      1, 0", "; buffed by hand\nstat_health      1, 0")

cdoc = codeview.parse("edu", COMMENTED)
view, hid = codeview.hide_comments("edu", COMMENTED)
vlines = view.split("\n")

check("no comment-only line survives into the view",
      not any(l.strip().startswith(";") for l in vlines))
check("a field's own trailing comment is untouched",
      "dictionary       test_spearmen      ; Test Spearmen" in vlines)
check("all three comment-only lines were taken out", len(hid) == 3)
check("the view is exactly that much shorter",
      len(vlines) == len(COMMENTED.split("\n")) - 3)
check("putting them back is byte-exact",
      codeview.show_comments("edu", view, hid) == COMMENTED)

# …and the payload the pane is actually handed
off = codeview.view_payload(cdoc, False)
on = codeview.view_payload(cdoc, True)
check("with hiding off the pane is handed the record unchanged",
      off["text"] == COMMENTED and off["hidden"] == [] and off["comments"] == 3)
check("`full` is the real bytes either way",
      off["full"] == COMMENTED and on["full"] == COMMENTED)
check("with hiding on the box holds the view", on["text"] == view)
check("…and the line count is the view's", on["lines"] == len(view.splitlines()))
check("the spans move onto the view's numbering",
      cdoc.spans["type"] == [[2, 2]] and on["spans"]["type"] == [[1, 1]])
check("…every one of them, not just the first",
      all(on["spans"][k][0][0] == vlines.index(
          COMMENTED.split("\n")[cdoc.spans[k][0][0] - 1]) + 1 for k in on["spans"]))
check("the value highlight is measured against the view too",
      on["part_spans"]["type"][0][0] == 1)
check("a kind with no comment convention says so",
      codeview.view_payload(codeview.parse("bmdb", ENTRY), True)["can_hide"] is False)

# ---- editing THROUGH the hidden view -------------------------------------
# This is the promise: the user only ever sees and types the view, and every
# comment still reaches the file, byte for byte, where it sat.
typed = view.replace("stat_health      1, 0", "stat_health      4, 0")
restored = codeview.show_comments("edu", typed, hid)
check("a value typed in the view comes back with every comment",
      restored == COMMENTED.replace("stat_health      1, 0", "stat_health      4, 0"))
check("…and the note above it is still above it",
      "; buffed by hand\nstat_health      4, 0" in restored)

# the edit is not confined to the anchor lines: add a field, drop another
typed2 = "\n".join(
    [l for l in typed.split("\n") if not l.startswith("voice_type")]
    + ["stat_stl         12"])
back2 = codeview.show_comments("edu", typed2, hid)
check("a line deleted above a comment does not take it with it",
      sum(1 for l in back2.split("\n") if l.strip().startswith(";;")
          or l.strip().startswith("; ")) == 3)
check("…and the comment is still on the line it was written above",
      "; buffed by hand\nstat_health      4, 0" in back2)
check("the added field is there and the dropped one is gone",
      "stat_stl         12" in back2 and "voice_type" not in back2)

# ---- and it reaches disk ---------------------------------------------------
# The block a code view is handed is `unit.raw`, which begins at the `type`
# line: a distinguisher written ABOVE a unit belongs to the file and not to the
# block, so the pane never had that one to hide in the first place.
before_hide = edu_path.read_bytes()
edu_path.write_text(PREAMBLE + COMMENTED + SECOND, encoding=edu_mod.ENCODING)
real = fresh_mod().edu.by_type()["Test Spearmen"].raw
check("the line above the block belongs to the file, not to the pane",
      not real.startswith(";;") and ";; ---- England ----" in COMMENTED)
rview, rhid = codeview.hide_comments("edu", real)
check("the block's own comment lines are still hidden", len(rhid) == 2)
rtyped = rview.replace("stat_health      1, 0", "stat_health      4, 0")
hplan = edit.plan_edit(fresh_mod(), edit.request_from_dict(
    {"unit": "Test Spearmen",
     "raw_block": codeview.show_comments("edu", rtyped, rhid)}))
check("a block edited through the hidden view plans cleanly", not hplan.errors)
edit.apply_edit(hplan)
disk = edu_path.read_text(encoding=edu_mod.ENCODING)
check("every comment line is on disk, in its place",
      ";; ---- England ----\ntype" in disk
      and "; buffed by hand\nstat_health      4, 0" in disk
      and "; the last line of this unit is a comment" in disk)
check("the round trip through the view is byte-exact bar the value typed",
      disk == PREAMBLE + COMMENTED.replace("stat_health      1, 0",
                                           "stat_health      4, 0") + SECOND)
undo_transfer(config.load_log()[-1]["id"])
edu_path.write_bytes(before_hide)

# ---- the EDB's `#` annotations count as comments there ---------------------
edbv, edbh = codeview.hide_comments("edb", "#  a modder's note\nbuilding x\n; and a real one\n")
check("the EDB hides `#` annotations as well as `;` (Phase 13's ruling)",
      edbv == "building x\n" and len(edbh) == 2)
check("…and the EDU does not — `#` is not a comment there",
      codeview.hide_comments("edu", "#3 something\ntype x\n")[1] == [])

# ---------------------------------------------------------------------------
print("\n== over HTTP, and fast enough to run on every keystroke ==")

from unittransfer.server import Registry, Handler, _Server

BASE = ""


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


# A DaC-sized file: the endpoints only ever touch one block, but the mod behind
# them holds ~1700 units, and the registry parse is on the same request path.
big = PREAMBLE + BLOCK + "".join(
    SECOND.replace("Test Archers", f"Filler {i}").replace("test_archers", f"filler_{i}")
    for i in range(1700))
edu_path.write_text(big, encoding=edu_mod.ENCODING)

Handler.registry = Registry(cfg / "icons")
srv = _Server(("127.0.0.1", 0), Handler)
BASE = f"http://127.0.0.1:{srv.server_address[1]}"
threading.Thread(target=srv.serve_forever, daemon=True).start()

try:
    r = get("/api/codeview?mod=CodeViewMod&kind=edu&id=Test%20Spearmen")
    check("GET /api/codeview returns the block", r.get("text") == BLOCK)
    check("…with its span map", r["spans"]["officer#3"] == [[10, 10]])
    check("…and its line count", r["lines"] == len(BLOCK.splitlines()))

    r = post("/api/codeview/parse", {"kind": "edu", "text": HAND})
    check("POST parse reads hand-edited text", r.get("ok") and r["text"] == HAND)
    r = post("/api/codeview/parse", {"kind": "edu", "text": "nonsense\n"})
    check("POST parse reports bad text as data, not an HTTP error",
          r.get("ok") is False and r.get("line") == 1 and "`type` line" in r["error"])

    r = get("/api/codeview?mod=CodeViewMod&kind=edu&id=Test%20Spearmen&hide=1")
    check("GET with hide=1 leaves the comment-only line out of the box",
          not any(l.strip().startswith(";") for l in r["text"].split("\n")))
    check("…hands back the real bytes beside it", r["full"] == BLOCK)
    check("…and says how to put them back",
          codeview.show_comments("edu", r["text"], r["hidden"]) == BLOCK)
    r2 = post("/api/codeview/parse", {"kind": "edu", "hide": 1,
                                      "hidden": r["hidden"],
                                      "text": r["text"].replace("Light", "Heavy")})
    check("POST parse rebuilds the comments before it reads the text",
          r2.get("ok") and r2["full"] == BLOCK.replace("Light", "Heavy"))
    check("…and answers with the view again, comments still hidden",
          not any(l.strip().startswith(";") for l in r2["text"].split("\n")))
    r3 = post("/api/codeview/parse", {"kind": "edu", "hide": 1,
                                      "hidden": r["hidden"],
                                      "text": "nonsense\n"})
    check("a refusal points at the line the BOX shows, not the file's",
          r3.get("ok") is False and r3.get("line") == 1)

    r = post("/api/codeview/render", {"kind": "edu", "base": BLOCK,
                                      "edits": {"overrides": {"stat_health": "2, 0"},
                                                "removals": ["officer#2"]}})
    check("POST render applies boxes to the text",
          r.get("ok") and "stat_health      2, 0" in r["text"]
          and "test_officer_drum" not in r["text"])

    def timed(fn, n=20):
        t = time.perf_counter()
        for _ in range(n):
            fn()
        return (time.perf_counter() - t) / n * 1000

    ms_parse = timed(lambda: post("/api/codeview/parse", {"kind": "edu", "text": BLOCK}))
    ms_render = timed(lambda: post("/api/codeview/render",
                                   {"kind": "edu", "base": BLOCK,
                                    "edits": {"overrides": {"stat_health": "2, 0"}}}))
    ms_get = timed(lambda: get("/api/codeview?mod=CodeViewMod&kind=edu&id=Test%20Spearmen"), 5)
    print(f"       parse {ms_parse:.1f} ms · render {ms_render:.1f} ms · "
          f"get {ms_get:.1f} ms (1701-unit EDU)")
    check(f"parse is under 50 ms ({ms_parse:.1f})", ms_parse < 50)
    check(f"render is under 50 ms ({ms_render:.1f})", ms_render < 50)
    check(f"the initial load is under 50 ms ({ms_get:.1f})", ms_get < 50)
finally:
    srv.shutdown()
    srv.server_close()

shutil.rmtree(med2, ignore_errors=True)
shutil.rmtree(cfg, ignore_errors=True)

print(f"\n{sum(ok)}/{len(ok)} checks — " + ("ALL PASSED" if all(ok) else "SOME FAILED"))
sys.exit(0 if all(ok) else 1)
