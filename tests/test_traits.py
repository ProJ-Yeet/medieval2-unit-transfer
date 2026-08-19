"""The trait definitions: round-trip fidelity, the edit splices, and the checks.

Phase 8a's gate is the same one Phase 7's was, for the same reason: the traits
editor saves by splicing lines back into a file its author has spent years
hand-formatting, so nothing built on this parser is worth anything unless it can
read every trait in every EDCT on the machine and hand the file back byte for
byte.

What each part is here to catch:

  * ``parse_text(t).text() == t`` on a hand-built file with everything real ones
    do: CRLF, comment banners between traits, inline comments, tabs and spaces
    mixed, blank lines inside a level, a hidden trait with no levels at all
  * the header's **line order**, which is the one thing in this format that
    crashes the game hundreds of lines away from the mistake — an inserted
    ``Hidden`` or ``ExcludeCultures`` must land at its canonical place, never
    appended, and ``check`` must say so when a file already has it wrong
  * edits as splices: an untouched line keeps its exact bytes (indent and inline
    comment included), an emptied optional field deletes its line, an emptied
    required one is refused, and added or removed levels and effects move only
    themselves
  * the findings that reading the file cannot show you — a level whose threshold
    a lower level already reached (so it never appears), and an ``Affects`` line
    naming a trait the file does not define
  * Code View: the span map lands on the right lines, and renaming the trait in
    the text pane is refused because that name is a key four other places use
  * the editor's whole round trip against a scratch mod on disk: create a trait
    and its text keys, edit it, build a trigger for it in the GUI's own shape,
    delete it and watch the triggers that only fed it go with it — then undo the
    lot and get every file back

Needs no game install for any of the above. When mods ARE installed it also
sweeps every real EDCT, which is the check that actually matters.

    python -m tests.test_traits
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import codeview, config, keyblock, traits, triggers
from unittransfer.mod import Mod

ok = []


def check(label, cond):
    ok.append(bool(cond))
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}")


def _undo_puts_back(work, edct, before):
    """Undo the last job and say whether BOTH files went back to what they were.

    A trait save can write the EDCT and the text file and its compiled cache, so
    the thing worth testing is not that undo restores a file — it is that it
    restores all of them. An undo that put the EDCT back and left the new text
    keys behind would leave a mod the log claims is untouched.
    """
    from unittransfer import transfer
    rec = config.load_log()[-1]
    vnv = work / "data" / "text" / "export_VnVs.txt"
    had_bin = (work / "data" / "text" / "export_VnVs.txt.strings.bin").read_bytes() \
        if (work / "data" / "text" / "export_VnVs.txt.strings.bin").exists() else None
    transfer.undo(rec["id"])
    back = keyblock.read_text(edct, traits.ENCODING) == before
    keys = "Watchful" not in traits.loc(Mod(work))
    # and the cache the save recompiled came back with it
    now = (work / "data" / "text" / "export_VnVs.txt.strings.bin")
    cache = (not now.exists()) or (had_bin is not None and now.read_bytes() != had_bin)
    return back and keys and cache and vnv.exists()


# Everything a real EDCT does that a naive parser gets wrong: a banner between
# traits, an inline comment on a value line, tabs and spaces mixed within one
# block, a blank line inside a level, a hidden trait with no levels, an optional
# header line, and a trait whose second level can never be reached.
FILE = (
    ";------ RACES ------\r\n"
    "\r\n"
    "Trait Brave\r\n"
    "  Characters family\r\n"
    "  Hidden\r\n"
    "  ExcludeCultures greek, noldor\r\n"
    "  NoGoingBackLevel 2\r\n"
    "  AntiTraits Coward\r\n"
    "\r\n"
    "  Level Brave\r\n"
    "    Description Brave_desc\t; the short one\r\n"
    "    EffectsDescription Brave_effects_desc\r\n"
    "    Threshold 1\r\n"
    "\r\n"
    "\t\tEffect Command 1\r\n"
    "\t\tEffect TroopMorale 2\r\n"
    "\r\n"
    "  Level VeryBrave\r\n"
    "    Description VeryBrave_desc\r\n"
    "    EffectsDescription VeryBrave_effects_desc\r\n"
    "    Epithet VeryBrave_epithet_desc\r\n"
    "    Threshold 1\r\n"
    "\r\n"
    ";------------------------------------\r\n"
    "Trait Coward\r\n"
    "  Characters family\r\n"
    "\r\n"
    "  Level Coward\r\n"
    "    Description Coward_desc\r\n"
    "    EffectsDescription Coward_effects_desc\r\n"
    "    Threshold 1\r\n"
    "\r\n"
    "Trait Marker\r\n"
    "  Characters all\r\n"
    "  Hidden\r\n"
    "\r\n"
    ";== TRIGGER DATA STARTS HERE ==\r\n"
    "\r\n"
    "Trigger battle_won\r\n"
    "  WhenToTest PostBattle\r\n"
    "  Condition IsGeneral\r\n"
    "  Affects Brave 1 Chance 100\r\n"
    "\r\n"
    "Trigger typo\r\n"
    "  WhenToTest PostBattle\r\n"
    "  Affects Trait Brave 1 Chance 100\r\n"
)

print("parsing")
tf = traits.parse_text(FILE)
check("the file comes back byte for byte", tf.text() == FILE)
check("three traits, and the trigger section is not one of them", len(tf.traits) == 3)
check("nothing to warn about", tf.warnings == [])
check("the trigger section is found", tf.lines[tf.trigger_start].startswith("Trigger"))

brave = tf.get("Brave")
check("header: Characters", brave.characters == ["family"])
check("header: Hidden is a line, not a value", brave.hidden is True)
check("header: ExcludeCultures splits on commas",
      brave.exclude_cultures == ["greek", "noldor"])
check("header: NoGoingBackLevel", brave.values["NoGoingBackLevel"] == "2")
check("header: AntiTraits", brave.anti_traits == ["Coward"])
check("two levels", [lv.name for lv in brave.levels] == ["Brave", "VeryBrave"])
check("a level's value ignores the inline comment",
      brave.levels[0].get("Description") == "Brave_desc")
check("effects belong to the level, in order",
      [(e.attribute, e.amount) for e in brave.levels[0].effects]
      == [("Command", "1"), ("TroopMorale", "2")])
check("a level with no effects has none", brave.levels[1].effects == [])
check("an optional level line is read", brave.levels[1].get("Epithet")
      == "VeryBrave_epithet_desc")
check("a hidden trait with no levels is fine", tf.get("Marker").levels == [])
check("the block text stops before the banner below it",
      tf.block_text(tf.get("Coward")).rstrip().endswith("Threshold 1"))

print("\nparse_block: a pane holds exactly one trait")
one = traits.parse_block(tf.block_text(brave))
check("one block parses", one.name == "Brave" and len(one.levels) == 2)
for label, text, want in (
        ("no Trait line", "  Characters family\r\n", "starts with"),
        ("two traits", "Trait A\n  Characters all\nTrait B\n  Characters all\n",
         "one at a time"),
        ("a trigger in the pane", "Trait A\n  Characters all\nTrigger x\n", "Trigger")):
    try:
        traits.parse_block(text)
        check(f"refused: {label}", False)
    except traits.TraitError as e:
        check(f"refused: {label} ({e.message[:40]}…)", want in e.message)

print("\nediting: a splice, so untouched lines stay untouched")
base = tf.block_text(brave)

same = traits.render_block(base, {})
check("no edits changes no bytes", same == base)

out = traits.render_block(base, {"no_going_back_level": "3"})
check("a changed value changes its line", "NoGoingBackLevel 3" in out)
check("and nothing else moves — one line differs, in place",
      [a == b for a, b in zip(out.split("\r\n"), base.split("\r\n"))].count(False) == 1
      and len(out.split("\r\n")) == len(base.split("\r\n")))
check("the whole file is still one trait", len(traits.parse_text(out + "\n").traits) == 1)

out = traits.render_block(base, {"levels": [{"description": "Brave_new_desc"}, {}]})
check("a level value is rewritten in place", "Description Brave_new_desc" in out)
check("its inline comment survives", "Brave_new_desc\t; the short one" in out)
check("the untouched level is untouched",
      "Description VeryBrave_desc" in out and "Epithet VeryBrave" in out)

out = traits.render_block(base, {"exclude_cultures": []})
check("an emptied optional header line is deleted", "ExcludeCultures" not in out)
check("and its neighbours are not", "Hidden" in out and "NoGoingBackLevel 2" in out)

out = traits.render_block(base, {"hidden": False})
check("Hidden switched off deletes the line", "Hidden" not in out)
check("Hidden switched on again puts it back, under Characters",
      traits.render_block(out, {"hidden": True}).split("\r\n")[1:3]
      == ["  Characters family", "  Hidden"])

try:
    traits.render_block(base, {"characters": []})
    check("refused: emptying the Characters line", False)
except traits.TraitError as e:
    check(f"refused: emptying the Characters line ({e.message[:34]}…)",
          "Characters" in e.message)
try:
    traits.render_block(base, {"levels": [{"threshold": ""}, {}]})
    check("refused: emptying a Threshold", False)
except traits.TraitError as e:
    check(f"refused: emptying a Threshold ({e.message[:30]}…)",
          "Threshold" in e.message)

print("\nediting: inserting a line lands where the engine wants it")
plain = "Trait Sober\n  Characters family\n\n  Level Sober\n    Description Sober_desc\n" \
        "    EffectsDescription Sober_effects_desc\n    Threshold 1\n"
out = traits.render_block(plain, {"anti_traits": ["Drunk"], "hidden": True,
                                  "exclude_cultures": ["greek"],
                                  "no_going_back_level": "1"})
check("all four optional header lines land in engine order",
      [ln.strip().split()[0] for ln in out.split("\n")[1:6]]
      == ["Characters", "Hidden", "ExcludeCultures", "NoGoingBackLevel", "AntiTraits"])
check("the new lines copy the indent beside them",
      all(ln.startswith("  ") for ln in out.split("\n")[1:6]))
check("check() is happy with the result", traits.check(traits.parse_block(out)) == [])

out = traits.render_block(plain, {"anti_traits": ["Drunk"]})
out = traits.render_block(out, {"exclude_cultures": ["greek"]})
check("a line inserted later still lands above the one it precedes",
      out.split("\n").index("  ExcludeCultures greek")
      < out.split("\n").index("  AntiTraits Drunk"))

out = traits.render_block(plain, {"levels": [{"gain_message": "Sober_gain_desc"}]})
check("a level's optional line lands before Threshold",
      out.split("\n").index("    GainMessage Sober_gain_desc")
      < out.split("\n").index("    Threshold 1"))

print("\nediting: levels and effects come and go")
out = traits.render_block(base, {"levels": [{}, {}, {"name": "Fearless",
                                                    "threshold": "8",
                                                    "effects": [{"attribute": "Command",
                                                                 "amount": "3"}]}]})
grown = traits.parse_block(out)
check("a third level is appended", [lv.name for lv in grown.levels]
      == ["Brave", "VeryBrave", "Fearless"])
check("its required lines are written for it",
      grown.levels[2].get("Description") == "Fearless_desc"
      and grown.levels[2].get("EffectsDescription") == "Fearless_effects_desc"
      and grown.levels[2].threshold == "8")
check("its effect came with it",
      [(e.attribute, e.amount) for e in grown.levels[2].effects] == [("Command", "3")])
check("the two levels above it are byte-identical",
      out.split("\r\n")[:len(base.split("\r\n"))] == base.split("\r\n"))

out = traits.render_block(base, {"levels": [{}]})
shrunk = traits.parse_block(out)
check("dropping a level drops only its lines", [lv.name for lv in shrunk.levels]
      == ["Brave"])
check("and leaves the level above whole", len(shrunk.levels[0].effects) == 2)

out = traits.render_block(base, {"levels": [{"effects": [{"attribute": "Command",
                                                          "amount": "1"},
                                                         {"attribute": "TroopMorale",
                                                          "amount": "2"},
                                                         {"attribute": "Piety",
                                                          "amount": "1"}]}, {}]})
check("a new effect copies the tabs of the ones above it",
      "\t\tEffect Piety 1" in out)
out = traits.render_block(base, {"levels": [{"effects": [{"attribute": "Command",
                                                          "amount": "-1"}]}, {}]})
check("changing one effect and dropping the other",
      [(e.attribute, e.amount) for e in traits.parse_block(out).levels[0].effects]
      == [("Command", "-1")])

print("\nreplace_block puts an edited trait back in the file")
edited = traits.render_block(base, {"no_going_back_level": "4"})
whole = traits.replace_block(tf, brave, edited)
check("the file is intact around it", whole.count("Trait ") == FILE.count("Trait "))
check("the edit is in it", "NoGoingBackLevel 4" in whole)
check("the trigger section is untouched",
      whole.split(";== TRIGGER DATA")[1] == FILE.split(";== TRIGGER DATA")[1])
check("and it still parses as one file",
      len(traits.parse_text(whole).traits) == 3)

print("\nchecks: what is wrong with a file that parses")
kinds = lambda findings: sorted({f["kind"] for f in findings})
found = traits.check_file(tf, triggers.parse_text(FILE))
check("the second level nobody can reach is found",
      any(f["kind"] == "unreachable-level" and "VeryBrave" not in f["message"]
          for f in found))
check("`Affects Trait Brave` is reported against the trigger's line",
      any(f["kind"] == "unknown-affects" and f["trait"] == "Trait" for f in found))
check("and nothing else is", kinds(found) == ["unknown-affects", "unreachable-level"])

bad = traits.parse_block("Trait Odd\n  Hidden\n  Characters family\n")
check("Characters below another header line is the crash the guide describes",
      any(f["kind"] == "header-order" for f in traits.check(bad)))
check("a trait with no Characters line at all",
      any(f["kind"] == "no-characters"
          for f in traits.check(traits.parse_block("Trait Odd\n  Hidden\n"))))
check("a comma-separated Characters list (only the first works)",
      any(f["kind"] == "characters-list" for f in traits.check(
          traits.parse_block("Trait Odd\n  Characters spy, diplomat\n  Hidden\n"))))
check("an antitrait no trait defines",
      any(f["kind"] == "unknown-antitrait" for f in traits.check(
          traits.parse_block("Trait Odd\n  Characters all\n  AntiTraits Nonesuch\n"),
          {"Odd"})))
check("a level missing its Description",
      any(f["kind"] == "missing-level-line" for f in traits.check(
          traits.parse_block("Trait Odd\n  Characters all\n  Level L\n"
                             "    Threshold 1\n"))))
check("a threshold below the hardcoded minimum",
      any(f["kind"] == "bad-threshold" for f in traits.check(
          traits.parse_block("Trait Odd\n  Characters all\n  Level L\n"
                             "    Description d\n    EffectsDescription e\n"
                             "    Threshold 0\n"))))
check("an attribute that is not one",
      any(f["kind"] == "unknown-attribute" for f in traits.check(
          traits.parse_block("Trait Odd\n  Characters all\n  Level L\n"
                             "    Description d\n    EffectsDescription e\n"
                             "    Threshold 1\n    Effect Bravery 1\n"))))
check("but Combat_V_Faction_<anything> is",
      not any(f["kind"] == "unknown-attribute" for f in traits.check(
          traits.parse_block("Trait Odd\n  Characters all\n  Level L\n"
                             "    Description d\n    EffectsDescription e\n"
                             "    Threshold 1\n    Effect Combat_V_Faction_Gondor 1\n"))))
check("and so are the two the spreadsheet misspells",
      not any(f["kind"] == "unknown-attribute" for f in traits.check(
          traits.parse_block("Trait Odd\n  Characters all\n  Level L\n"
                             "    Description d\n    EffectsDescription e\n"
                             "    Threshold 1\n    Effect HitPoints 1\n"
                             "    Effect Chivalry 1\n"))))
check("a duplicate trait name",
      any(f["kind"] == "duplicate-trait" for f in traits.check_file(
          traits.parse_text("Trait A\n  Characters all\n  Hidden\n"
                            "Trait A\n  Characters all\n  Hidden\n"))))

print("\nCode View")
doc = codeview.parse("traits", base, {"trait": "Brave"})
lines = base.split("\r\n")
spans = doc.spans


def on(label, wanted):
    span = spans.get(label)
    return bool(span) and lines[span[0][0] - 1].strip().startswith(wanted)


check("the name span is the Trait line", on("name", "Trait Brave"))
check("a header span is its own line", on("hidden", "Hidden")
      and on("anti_traits", "AntiTraits"))
check("a level span covers the whole level",
      spans["level#1"] == [[8, 14]] and lines[7].strip() == "Level Brave")
check("a level field span is one line", on("level#1.threshold", "Threshold"))
check("an effect has its own span", on("level#1.effect#2", "Effect TroopMorale"))
check("every span points inside the block",
      all(1 <= a <= b <= len(lines) for v in spans.values() for a, b in v))
check("fields and spans use the same labels",
      {f[0] for f in doc.fields} <= set(spans))
check("the fields are in the order the lines are",
      [f[0] for f in doc.fields][:3] == ["name", "characters", "hidden"])

rendered = codeview.render("traits", base, {"no_going_back_level": "5"},
                           {"trait": "Brave"})
check("render goes through the save's own serialiser",
      rendered.text == traits.render_block(base, {"no_going_back_level": "5"}))
try:
    codeview.parse("traits", base.replace("Trait Brave", "Trait Bold"),
                   {"trait": "Brave"})
    check("refused: renaming the trait in the text pane", False)
except codeview.CodeViewError as e:
    check(f"refused: renaming the trait in the text pane ({e.message[:32]}…)",
          "orphan" in e.message)

print("\nthe editor: overview, detail, and a save that goes to disk")
# A scratch mod, so add/edit/delete can be applied for real and read back. Only
# the two files this module touches are copied — that IS the mod, as far as
# traits are concerned.
work = Path(tempfile.mkdtemp(prefix="tk-traits-")) / "TestMod"
(work / "data" / "text").mkdir(parents=True)
# written the module's own way: Path.write_text would turn every \n in these
# strings into \r\n on Windows, so the CRLF file would land with \r\r\n
keyblock.write_text(work / "data" / "export_descr_character_traits.txt",
                    FILE, traits.ENCODING)
keyblock.write_text(work / "data" / "text" / "export_VnVs.txt",
                    "﻿¬ test\r\n{Brave}Brave Heart\r\n{Brave_desc}Fearless.\r\n"
              "{Brave_effects_desc}\\nGood at fighting.\r\n", "utf-16")
mod = Mod(work)
edct = work / "data" / "export_descr_character_traits.txt"

ov = traits.overview(mod)
check("overview lists every trait", [r["name"] for r in ov["traits"]]
      == ["Brave", "Coward", "Marker"])
check("a row carries what the list shows",
      ov["traits"][0]["levels"] == 2 and ov["traits"][0]["hidden"] is True
      and ov["traits"][0]["triggers"] == 1)
check("the localised name leads, the code name follows",
      ov["traits"][0]["label"] == "Brave Heart (Brave)")
check("a text entry that is just its own key is not a name",
      traits.label(traits.parse_block("Trait X\n  Characters all\n  Level X\n"),
                   {"X": "X"}) == "X")

d = traits.detail(mod, "Brave")
check("detail brings the triggers that feed the trait",
      [t["name"] for t in d["triggers"]] == ["battle_won"])
check("…and the text keys its levels name",
      set(d["loc"]) == set(traits.text_tags(traits.parse_block(d["text"]))))
check("…and says which of them the mod has not got",
      "VeryBrave" in d["missing_loc"] and "Brave" not in d["missing_loc"])
check("…and the attribute list the effect boxes offer",
      "Command" in d["attributes"] and "HitPoints" in d["attributes"])

p = traits.plan(mod, {"trait": "Wary", "action": "add", "edits": {
    "characters": ["spy"], "hidden": True,
    "levels": [{"name": "Watchful", "threshold": "1",
                "effects": [{"attribute": "Subterfuge", "amount": "1"}]}]}})
check("a create plans a block, its text keys and nothing else",
      p.payload()["ok"] and p.changes[0] == "+ Trait Wary"
      and set(p.loc_writes) == {"Watchful", "Watchful_desc", "Watchful_effects_desc"}
      and sorted(p.loc_new) == sorted(p.loc_writes))
check("the new block is written in the engine's order",
      [ln.split()[0] for ln in p.block.split("\n") if ln.strip()][:3]
      == ["Trait", "Characters", "Hidden"])
check("and it passes its own checks", traits.check(traits.parse_block(p.block)) == [])
traits.apply(p)
after = traits.parse_file(edct)
check("the trait is on disk, above the trigger section",
      after.get("Wary") is not None and after.get("Wary").start < after.trigger_start)
check("the traits either side of it are untouched",
      after.get("Brave") is not None and after.get("Coward") is not None)
check("the text keys reached export_VnVs.txt",
      "Watchful" in traits.loc(Mod(work)))
check("the compiled archive was written too",
      (work / "data" / "text" / "export_VnVs.txt.strings.bin").exists())

check("…and the log can undo the whole job — every file it wrote",
      _undo_puts_back(work, edct, FILE))
traits.apply(traits.plan(mod, {"trait": "Wary", "action": "add", "edits": {
    "characters": ["spy"], "hidden": True,
    "levels": [{"name": "Watchful", "threshold": "1",
                "effects": [{"attribute": "Subterfuge", "amount": "1"}]}]}}))

p = traits.plan(mod, {"trait": "Wary", "action": "edit", "edits": {
    "no_going_back_level": "1",
    "levels": [{"threshold": "2", "effects": [{"attribute": "Subterfuge",
                                               "amount": "2"}]}]}})
traits.apply(p)
w = traits.parse_file(edct).get("Wary")
check("an edit lands on the right lines",
      w.values["NoGoingBackLevel"] == "1" and w.levels[0].threshold == "2"
      and w.levels[0].effects[0].amount == "2")

p = traits.plan(mod, {"trait": "Wary", "action": "edit",
                      "loc": {"Watchful": "Watchful", "Watchful_desc": "Misses nothing."}})
check("retyped wording is planned as a text write, and unchanged wording is not",
      p.loc_writes == {"Watchful_desc": "Misses nothing."} and p.loc_new == [])
traits.apply(p)
names = traits.loc(Mod(work))
check("the words reach export_VnVs.txt", names["Watchful_desc"] == "Misses nothing.")
check("…in place, without disturbing the entries around it",
      names["Brave"] == "Brave Heart" and names["Brave_desc"] == "Fearless."
      and names["Brave_effects_desc"] == "\nGood at fighting.")
check("…and the compiled archive says the same",
      __import__("unittransfer.stringsbin", fromlist=["x"]).load_pairs(
          work / "data" / "text" / "export_VnVs.txt.strings.bin")["Watchful_desc"]
      == "Misses nothing.")

p = traits.plan(mod, {"trait": "Wary", "action": "add"})
check("adding a name the file already has is refused",
      not p.payload()["ok"] and "already a trait" in p.errors[0])
p = traits.plan(mod, {"trait": "Brave", "action": "edit",
                      "raw_block": "Trait Bold\n  Characters family\n"})
check("renaming a trait through the text pane is refused",
      not p.payload()["ok"] and "orphan" in p.errors[0])

p = traits.plan(mod, {"trait": "Brave", "action": "delete"})
check("deleting a trait takes the triggers that only fed it",
      any(c == "- Trigger battle_won" for c in p.changes))
traits.apply(p)
gone = traits.parse_file(edct)
check("the trait is gone and the file still parses", gone.get("Brave") is None)
check("no trigger is left pointing at it",
      not [f for f in traits.check_file(gone, triggers.parse_file(edct))
           if f["kind"] == "unknown-affects" and f["trait"] == "Brave"])

p = traits.plan(mod, {"trait": "Coward", "action": "edit", "triggers": {"adds": [
    {"trigger": {"name": "coward_runs", "when_to_test": "PostBattle",
                 "conditions": [{"term": "IsGeneral", "args": []},
                                {"term": "WonBattle", "args": [], "joiner": "and",
                                 "negated": True}],
                 "effects": [{"keyword": "Affects",
                              "args": ["Coward", "1", "Chance", "100"]}]}}]}})
traits.apply(p)
made = triggers.parse_file(edct).get("coward_runs")
check("a trigger built in the GUI reaches disk in the language",
      made is not None and made.when_to_test == "PostBattle"
      and [c.term for c in made.conditions] == ["IsGeneral", "WonBattle"]
      and made.conditions[1].negated is True)
check("…and it is at the end, where order cannot change what already fires",
      triggers.parse_file(edct).triggers[-1].name == "coward_runs")
check("…and nothing in the file objects to it",
      not [f for f in traits.check_file(traits.parse_file(edct),
                                        triggers.parse_file(edct))
           if f["line"] >= made.start + 1])

print("\nthe real files")
root = config.get_med2_root()
mods = sorted((Path(root) / "mods").glob("*/data/export_descr_character_traits.txt")) \
    if root else []
if not mods:
    print("  (no mods installed — the sweep that matters is skipped)")
else:
    total_traits = total_levels = 0
    for path in mods:
        text = path.read_text(encoding=traits.ENCODING)
        parsed = traits.parse_text(text)
        found = traits.check_file(parsed, triggers.parse_text(text))
        total_traits += len(parsed.traits)
        total_levels += sum(len(t.levels) for t in parsed.traits)
        name = path.parts[-3]
        check(f"{name}: {len(parsed.traits)} traits come back byte for byte",
              parsed.text() == text)
        check(f"{name}: every construct in it is named", parsed.warnings == [])
        check(f"{name}: every trait re-renders to itself unchanged",
              all(traits.render_block(parsed.block_text(t), {})
                  == parsed.block_text(t) for t in parsed.traits))
        check(f"{name}: every trait is a valid one-block pane",
              all(traits.parse_block(parsed.block_text(t)).name == t.name
                  for t in parsed.traits if t.name))
        check(f"{name}: {len(found)} findings, and they are not a flood",
              len(found) < len(parsed.traits) / 20)
    print(f"  swept {len(mods)} file(s), {total_traits} traits, {total_levels} levels")

print(f"\n{sum(ok)}/{len(ok)} checks passed")
sys.exit(0 if all(ok) else 1)
