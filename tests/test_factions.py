"""The faction roster: the shape it shares, the things only a faction means.

Phase 11's first result was that there was nothing to parse. ``descr_sm_factions.txt``
is the fourth file to be a run of ``<head> <name>`` records with ``keyword value``
lines under it, so it is a :class:`unittransfer.flatrecord.Shape` and no more —
all 90 factions in the three installed mods parse byte-exact and re-render
unchanged against it with no code of its own. What is tested here is therefore
mostly what a *faction* means, plus the sweep that proves the claim above.

What each part is here to catch:

  * **the canonical line order is derived, not guessed.** Thirteen orderings
    appear across the 90 real factions and a topological sort finds zero
    conflicts between them, so an inserted line has one right place to go.
  * **the head line can carry a modifier** — ``faction egypt, spawned_on_event``,
    and ``shadowing`` / ``shadowed_by`` naming another faction. The slot is the
    part before the comma, and everything else in the mod points at the slot.
  * **``has_family_tree`` is not a boolean.** yes / no / ``teutonic``, and 24 of
    the 90 say the third. A checkbox would have overwritten every one of them.
  * **``horde_unit`` repeats**, like a rebel faction's ``unit``.
  * **the colours are the one genuinely visual thing in the file**, and they
    round-trip through hex without moving.
  * **a slot cannot be renamed** — in the form or in the text pane.
  * **art is never called missing.** Not one of the 90 real factions ships its
    ``loading_logo`` unpacked; they are all inside ``.pack`` archives.

Needs no game install for any of the above. When mods ARE installed it also
sweeps every real roster, which is the check that actually matters.

    python -m tests.test_factions
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import codeview, config, factions as fa, keyblock as kb
from unittransfer.mod import Mod

ok = []


def check(label, cond):
    ok.append(bool(cond))
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}")


# Everything a real roster does: tab columns, a comment banner, an inline
# comment, a head-line modifier, a horde, a shadowing pair, and CRLF throughout.
FILE = (
    ";;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;\r\n"
    "faction\t\t\t\tsicily\r\n"
    "culture\t\t\t\tsouthern_european\r\n"
    "religion\t\t\tcatholic\r\n"
    "symbol\t\t\t\tmodels_strat/symbol_sicily.CAS\r\n"
    "rebel_symbol\t\tmodels_strat/symbol_rebels.CAS\r\n"
    "primary_colour\t\tred 220, green 220, blue 220\t; near white\r\n"
    "secondary_colour\tred 0, green 0, blue 0\r\n"
    "loading_logo\t\tloading_screen/symbols/symbol128_sicily.tga\r\n"
    "standard_index\t\t8\r\n"
    "logo_index\t\t\tFACTION_LOGO_SICILY\r\n"
    "small_logo_index\tSMALL_FACTION_LOGO_SICILY\r\n"
    "triumph_value\t\t5\r\n"
    "custom_battle_availability\tyes\r\n"
    "can_sap\t\t\t\tno\r\n"
    "prefers_naval_invasions\tyes\r\n"
    "can_have_princess\tno\r\n"
    "has_family_tree\t\tteutonic\r\n"
    "\r\n"
    "faction\t\t\t\tegypt, spawned_on_event\r\n"
    "culture\t\t\t\tmiddle_eastern\r\n"
    "religion\t\t\tislam\r\n"
    "symbol\t\t\t\tmodels_strat/symbol_egypt.CAS\r\n"
    "rebel_symbol\t\tmodels_strat/symbol_rebels.CAS\r\n"
    "primary_colour\t\tred 55, green 75, blue 48\r\n"
    "secondary_colour\tred 143, green 156, blue 149\r\n"
    "loading_logo\t\tloading_screen/symbols/symbol128_egypt.tga\r\n"
    "standard_index\t\t10\r\n"
    "logo_index\t\t\tFACTION_LOGO_EGYPT\r\n"
    "small_logo_index\tSMALL_FACTION_LOGO_EGYPT\r\n"
    "triumph_value\t\t5\r\n"
    "custom_battle_availability\tno\r\n"
    "horde_min_units\t\t15\r\n"
    "horde_max_units\t\t30\r\n"
    "horde_max_units_reduction_every_horde\t2\r\n"
    "horde_unit_per_settlement_population\t100\r\n"
    "horde_min_named_characters\t2\r\n"
    "horde_max_percent_army_stack\t80\r\n"
    "horde_disband_percent_on_settlement_capture\t25\r\n"
    "horde_unit\t\t\tMiners\r\n"
    "horde_unit\t\t\tPeasants\r\n"
    "can_sap\t\t\t\tno\r\n"
    "prefers_naval_invasions\tno\r\n"
    "can_have_princess\tno\r\n"
    "has_family_tree\t\tyes\r\n"
)

print("the shape it shares — no parser of its own")
rf = fa.parse_text(FILE)
check("a roster comes back byte for byte", rf.text() == FILE)
check("with no unknown constructs", rf.warnings == [])
check("two factions, the second with a horde of two",
      [r.name for r in rf.records] == ["sicily", "egypt, spawned_on_event"]
      and [u.value for u in rf.records[1].repeats] == ["Miners", "Peasants"])
check("an inline comment is not part of the value",
      rf.records[0].get("primary_colour") == "red 220, green 220, blue 220")

print("\nthe head line is a slot and possibly a modifier")
check("the slot is the part before the comma",
      fa.slot_of("egypt, spawned_on_event") == "egypt"
      and fa.slot_of("sicily") == "sicily")
check("and the modifier is the rest",
      fa.modifier_of("spain, shadowed_by hrebels") == "shadowed_by hrebels"
      and fa.modifier_of("sicily") == "")

print("\nthe colours, the one visual thing in the file")
check("a colour line parses to rgb", fa.parse_colour("red 55, green 75, blue 48")
      == (55, 75, 48))
check("and writes back in the file's own words",
      fa.format_colour((55, 75, 48)) == "red 55, green 75, blue 48")
check("hex round-trips without moving",
      fa.from_hex(fa.hex_colour("red 55, green 75, blue 48"))
      == "red 55, green 75, blue 48")
check("a value out of range is not a colour", fa.parse_colour("red 300, green 0, blue 0") is None)
check("nor is a line that is not one at all", fa.parse_colour("bright red") is None)

print("\nthe splice — an unchanged box must not rewrite its line")
same = True
for rec in rf.records:
    block = rf.block_text(rec)
    edits = {k: rec.get(k) for k in fa.ORDER}
    edits["units"] = [u.value for u in rec.repeats]
    same = same and fa.render_block(block, edits) == block
check("a full-form save changes nothing", same)

sic = rf.block_text(rf.records[0])
out = fa.render_block(sic, {"religion": "islam"})
check("changing one value rewrites one line and keeps its tab stops",
      out.count("\n") == sic.count("\n") and "religion\t\t\tislam" in out)
out = fa.render_block(sic, {"can_build_siege_towers": "yes"})
check("an added optional line goes to its canonical place, not the end",
      out.index("has_family_tree") < out.index("can_build_siege_towers")
      and out.rstrip().endswith("can_build_siege_towers\tyes"))
check("…and a keyword too long to reach that column takes one tab, as the real "
      "long ones do", out.rstrip().endswith("can_build_siege_towers\tyes"))
out = fa.render_block(sic, {"disband_to_pools": "no"})
added = [ln for ln in out.split("\n") if "disband_to_pools" in ln][0]
check("a keyword that CAN reach the column joins it, rather than copying one "
      "line's tab count",
      kb.value_column(added, "disband_to_pools")
      == kb.value_column("culture\t\t\t\tsouthern_european", "culture"))
out = fa.render_block(sic, {"primary_colour": fa.from_hex("#ff0000")})
check("a colour picked in the GUI reaches the line in the file's words",
      "primary_colour\t\tred 255, green 0, blue 0\t; near white" in out)
try:
    fa.render_block(sic, {"culture": ""})
    check("a blanked required line is refused", False)
except fa.FactionError as e:
    check("a blanked required line is refused", "culture" in str(e))

egy = rf.block_text(rf.records[1])
out = fa.render_block(egy, {"units": ["Miners"]})
check("dropping a horde unit drops exactly its line",
      "Peasants" not in out and out.count("horde_unit\t") == 1)
out = fa.render_block(egy, {"units": ["Miners", "Peasants", "Cave Trolls2"]})
check("adding one copies the indent of the unit above it",
      "horde_unit\t\t\tCave Trolls2" in out)

print("\nspans and fields, for the Code View widget")
spans = fa.block_spans(sic)
check("a faction's spans name every line it has",
      spans["name"] == [[1, 1]] and spans["religion"] == [[3, 3]]
      and spans["has_family_tree"] == [[17, 17]])
fields = dict(fa.block_fields(egy))
check("and its fields carry the values and the repeats",
      fields["culture"] == "middle_eastern" and fields["horde_unit#2"] == "Peasants")

print("\nthe checks")
def kinds(text, mod=None):
    return sorted(f["kind"] for f in fa.check_file(fa.parse_text(text), mod))

check("a clean roster has nothing to say", fa.check_file(rf) == [])
check("has_family_tree = maybe is reported",
      "bad-family-tree" in kinds(FILE.replace("has_family_tree\t\tteutonic",
                                              "has_family_tree\t\tmaybe")))
check("but `teutonic` is not — 24 of 90 real factions say it",
      "bad-family-tree" not in kinds(FILE))
check("a yes/no line that is neither is reported",
      "bad-yes-no" in kinds(FILE.replace("can_sap\t\t\t\tno", "can_sap\t\t\t\tsometimes")))
check("a malformed colour is reported",
      "bad-colour" in kinds(FILE.replace("red 220, green 220, blue 220", "grey")))
check("a non-number where a number goes is reported",
      "bad-number" in kinds(FILE.replace("standard_index\t\t8", "standard_index\t\teight")))
check("a head-line modifier the engine does not know is reported",
      "unknown-modifier" in kinds(FILE.replace("egypt, spawned_on_event",
                                               "egypt, teleported_on_tuesday")))
check("a `shadowing` naming nobody is reported",
      "unknown-shadow" in kinds(FILE.replace("egypt, spawned_on_event",
                                             "egypt, shadowing atlantis")))
check("horde settings with no horde_unit are reported",
      "horde-no-units" in kinds(FILE.replace("horde_unit\t\t\tMiners\r\n"
                                             "horde_unit\t\t\tPeasants\r\n", "")))
check("a part-built horde is reported",
      "part-horde" in kinds(FILE.replace("horde_min_named_characters\t2\r\n", "")))
check("a missing required line is reported",
      "missing-line" in kinds(FILE.replace("religion\t\t\tcatholic\r\n", "")))
check("a duplicated slot is reported", "duplicate" in kinds(FILE + FILE.split(";;;")[-1]))
check("a special_faction_type the engine does not know is reported",
      "unknown-special-type" in kinds(FILE.replace(
          "culture\t\t\t\tsouthern_european",
          "special_faction_type\tholy_faction\r\nculture\t\t\t\tsouthern_european")))

print("\nthe Code View kind")
check("`factions` is a registered kind", "factions" in codeview.KINDS)
doc = codeview.parse("factions", sic, {"faction": "sicily"})
check("a faction block parses into a document",
      doc.ident == "sicily" and doc.spans["religion"] == [[3, 3]])
doc = codeview.render("factions", sic, {"religion": "islam"}, {"faction": "sicily"})
check("and a GUI edit round-trips through the serialiser the save uses",
      "religion\t\t\tislam" in doc.text)
try:
    codeview.parse("factions", sic.replace("sicily", "venice", 1), {"faction": "sicily"})
    check("renaming a slot in the text pane is refused", False)
except codeview.CodeViewError as e:
    check("renaming a slot in the text pane is refused", "orphan" in str(e))
doc = codeview.parse("factions", egy, {"faction": "egypt, spawned_on_event"})
check("but the head-line modifier is not mistaken for a rename",
      doc.ident == "egypt, spawned_on_event")
try:
    codeview.parse("factions", FILE, {})
    check("a pane holding two factions is refused", False)
except codeview.CodeViewError as e:
    check("a pane holding two factions is refused", "one at a time" in str(e))

print("\nthe editor: overview, detail, and a save that goes to disk")
work = Path(tempfile.mkdtemp(prefix="tk-fac-")) / "TestMod"
(work / "data" / "text").mkdir(parents=True)
kb.write_text(work / "data" / fa.REL, FILE, fa.ENCODING)
kb.write_text(work / "data" / fa.LOC_REL,
              "﻿¬ test\r\n{SICILY}Kingdom of Gondor\r\n", "utf-16")
kb.write_text(work / "data" / "descr_cultures.txt",
              "culture\t\t\tsouthern_european\r\nportrait_mapping\tse\r\n"
              "rebel_standard_index\t0\r\n{\r\n}\r\n"
              "culture\t\t\tmiddle_eastern\r\nportrait_mapping\tme\r\n"
              "rebel_standard_index\t1\r\n{\r\n}\r\n", fa.ENCODING)
kb.write_text(work / "data" / "descr_religions.txt",
              "religions\r\n{\r\n\tcatholic\r\n\tislam\r\n}\r\n"
              "religion catholic\r\n{\r\n\tpip_path\tui/pips/pip_c.tga\r\n}\r\n",
              fa.ENCODING)
mod = Mod(work)

ov = fa.overview(mod)
check("overview lists every faction",
      [r["slot"] for r in ov["factions"]] == ["sicily", "egypt"])
check("the localised name leads, the slot follows — the whole point here",
      ov["factions"][0]["label"] == "Kingdom of Gondor (sicily)")
check("a faction with no expanded.txt entry shows its slot alone",
      ov["factions"][1]["label"] == "egypt")
check("a row carries both map colours as hex",
      ov["factions"][0]["primary"] == "#dcdcdc"
      and ov["factions"][1]["secondary"] == "#8f9c95")
check("and the head modifier rides along", ov["factions"][1]["modifier"]
      == "spawned_on_event")
check("the roster says how full it is", ov["limit"] == fa.FACTION_LIMIT
      and ov["count"] == 2)
check("creating and deleting are refused, with the reason",
      ov["actions"] == ["edit"] and "eight or nine files" in ov["refused"])

d = fa.detail(mod, "sicily")
check("detail carries the record, its spans and its text key",
      d["faction"]["religion"] == "catholic" and d["loc_tag"] == "SICILY"
      and d["spans"]["religion"] == [[3, 3]])
check("…the colours as hex for a picker", d["colours"]["primary_colour"] == "#dcdcdc")
check("…this mod's own cultures and religions for the pickers",
      d["vocab"]["cultures"] == ["southern_european", "middle_eastern"]
      and d["vocab"]["religions"] == ["catholic", "islam"])
check("…and which art is actually on disk, with no verdict about the rest",
      d["art_found"] == {"symbol": False, "rebel_symbol": False,
                         "loading_logo": False})
check("a faction can be opened by slot even when its head line has a modifier",
      fa.detail(mod, "egypt")["name"] == "egypt, spawned_on_event")

p = fa.plan(mod, {"faction": "sicily", "action": "edit",
                  "edits": {"religion": "islam",
                            "primary_colour": fa.from_hex("#ff0000")},
                  "loc": {"SICILY": "Kingdom of Sicily"}})
check("an edit plans the roster and the name together",
      p.payload()["ok"] and len(p.changes) >= 2
      and p.loc_writes == {"SICILY": "Kingdom of Sicily"})
fa.apply(p)
after = fa.parse_file(work / "data" / fa.REL)
check("the edit landed on the right lines",
      after.get("sicily").get("religion") == "islam"
      and after.get("sicily").get("primary_colour") == "red 255, green 0, blue 0")
check("and the reworded name with it",
      fa.loc(Mod(work))["SICILY"] == "Kingdom of Sicily")
check("the rest of the file is untouched",
      after.records[1].name == "egypt, spawned_on_event"
      and [u.value for u in after.records[1].repeats] == ["Miners", "Peasants"])

p = fa.plan(mod, {"faction": "sicily", "action": "add"})
check("creating a faction is refused, with the reason",
      not p.payload()["ok"] and "eight or nine files" in p.errors[0])
p = fa.plan(mod, {"faction": "sicily", "action": "delete"})
check("so is deleting one", not p.payload()["ok"])
p = fa.plan(mod, {"faction": "sicily", "action": "edit",
                  "edits": {"name": "venice", "religion": "islam"}})
check("and a rename sent from the form is ignored rather than written",
      fa.parse_text(p.text or kb.read_text(work / "data" / fa.REL, fa.ENCODING))
      .get("sicily") is not None)

p = fa.plan(mod, {"faction": "egypt", "action": "edit",
                  "edits": {"units": ["Miners", "Peasants", "Cave Trolls2"]}})
fa.apply(p)
check("a horde unit added in the GUI reaches disk",
      [u.value for u in fa.parse_file(work / "data" / fa.REL)
       .get("egypt, spawned_on_event").repeats]
      == ["Miners", "Peasants", "Cave Trolls2"])

from unittransfer import transfer
rec = config.load_log()[-1]
transfer.undo(rec["id"])
check("and the log puts the whole job back",
      [u.value for u in fa.parse_file(work / "data" / fa.REL)
       .get("egypt, spawned_on_event").repeats] == ["Miners", "Peasants"])

print("\nthe buildings module reads this file through here now")
from unittransfer import buildings
check("faction_cultures comes from the faction module",
      buildings.faction_cultures(mod) == {"sicily": "southern_european",
                                          "egypt": "middle_eastern"})
check("…and it gets the head-line modifier right",
      "egypt" in buildings.faction_cultures(mod))

print("\nthe real files")
root = config.get_med2_root()
mods = sorted((Path(root) / "mods").glob("*/data")) if root else []
mods = [m for m in mods if (m / fa.REL).exists()]
if not mods:
    print("  (no mods installed — the sweep that matters is skipped)")
else:
    total = logos = symbols = teutonic = 0
    orders = set()
    for data in mods:
        m = Mod(data.parent)
        text = kb.read_text(data / fa.REL, fa.ENCODING)
        parsed = fa.parse_text(text)
        found = fa.check_file(parsed, m)
        resave = []
        for rec in parsed.records:
            block = parsed.block_text(rec)
            edits = {k: rec.get(k) for k in fa.ORDER if k in rec.lines}
            edits["units"] = [u.value for u in rec.repeats]
            resave.append(fa.render_block(block, edits) == block)
            orders.add(tuple(k for k in fa.ORDER if k in rec.lines))
            logos += bool(fa.art_path(m, rec.get("loading_logo")))
            symbols += bool(fa.art_path(m, rec.get("symbol")))
            teutonic += rec.get("has_family_tree") == "teutonic"
        total += len(parsed.records)
        name = data.parent.name
        check(f"{name}: {len(parsed.records)} factions come back byte for byte",
              parsed.text() == text)
        check(f"{name}: every construct in it is named", parsed.warnings == [])
        check(f"{name}: every faction re-renders to itself unchanged", all(resave))
        check(f"{name}: {len(found)} findings, and they are not a flood",
              len(found) < max(4, len(parsed.records)))
        check(f"{name}: every faction's culture is one it defines",
              not [f for f in found if f["kind"] == "unknown-culture"])

    print(f"  swept {total} real factions across {len(mods)} mod(s)")
    # the three facts the module rests on, measured rather than assumed
    check(f"every one of the {len(orders)} observed line orders is a subset of "
          "the canonical one",
          all(list(o) == [k for k in fa.ORDER if k in o] for o in orders))
    check(f"{teutonic} real factions say has_family_tree teutonic — it is not a "
          "boolean", teutonic > 0)
    check(f"not one of the {total} loading_logo files is unpacked ({logos} found) "
          "— so a missing one is never a fault", logos == 0)
    check(f"symbols, by contrast, often ARE shipped ({symbols}/{total}) — which is "
          "why they are marked when found", symbols > 0)

print(f"\n{sum(ok)}/{len(ok)} checks passed")
sys.exit(0 if all(ok) else 1)
