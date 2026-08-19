"""The ancillary definitions: round-trip fidelity, the edit splices, and the checks.

Phase 9's gate is Phase 8's gate: this parser saves by splicing lines back into a
hand-formatted file, so it is worth nothing unless it can read every ancillary in
every EDA on the machine and hand the file back byte for byte.

What is specific to this format, and what each part is here to catch:

  * ``Type`` and ``Transferable`` — two required lines the RTW guide does not
    mention at all, because they are M2TW's. All 1134 real ancillaries have both,
    always as lines two and three.
  * the two silent hardcoded limits: more than 3 ``ExcludedAncillaries`` is an
    errorless crash, and more than 8 ``Effect`` lines makes the ancillary
    impossible to gain from a trigger. No installed mod is over either, so a
    finding here means something.
  * ``AcquireAncillary`` is EDA's ``Affects``: deleting an ancillary has to take
    the triggers that only granted it, or the next one to fire crashes.
  * an ancillary has a *picture*, and DaC has two that name a file nobody
    shipped — a blank slot on the character screen and nothing in any log.
  * the shared machinery actually being shared: the block splices are
    :mod:`unittransfer.keyblock` and the trigger section is
    :mod:`unittransfer.triggers`, both written for the traits editor first.

Needs no game install for any of the above. When mods ARE installed it also
sweeps every real EDA, which is the check that actually matters.

    python -m tests.test_ancillaries
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import ancillaries, codeview, config, keyblock, triggers
from unittransfer.mod import Mod

ok = []


def check(label, cond):
    ok.append(bool(cond))
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}")


# Everything a real EDA does: a comment banner, an inline comment on a value, a
# blank line inside a record, a Unique with its own exclusion, an ancillary with
# no effects, and a trigger granting one that does not exist.
FILE = (
    ";------ ITEMS ------\r\n"
    "\r\n"
    "Ancillary iron_guard\r\n"
    "    Type follower\r\n"
    "    Transferable 0\r\n"
    "    Image iron_guard.tga\t; the old one\r\n"
    "    Unique\r\n"
    "    ExcludedAncillaries iron_guard, rohan_horn\r\n"
    "    ExcludeCultures greek,  noldor\r\n"
    "    Description iron_guard_desc\r\n"
    "    EffectsDescription iron_guard_effects_desc\r\n"
    "\r\n"
    "    Effect Command 1\r\n"
    "    Effect PersonalSecurity 2\r\n"
    "\r\n"
    ";--------------------------------\r\n"
    "Ancillary rohan_horn\r\n"
    "    Type item\r\n"
    "    Transferable 1\r\n"
    "    Image rohan_horn.tga\r\n"
    "    Description rohan_horn_desc\r\n"
    "    EffectsDescription rohan_horn_effects_desc\r\n"
    "\r\n"
    ";== TRIGGER DATA ==\r\n"
    "\r\n"
    "Trigger gains_guard\r\n"
    "    WhenToTest CharacterTurnEnd\r\n"
    "    Condition IsGeneral\r\n"
    "    AcquireAncillary iron_guard chance 5\r\n"
    "\r\n"
    "Trigger gains_ghost\r\n"
    "    WhenToTest CharacterTurnEnd\r\n"
    "    AcquireAncillary no_such_thing Chance 100\r\n"
)

print("parsing")
af = ancillaries.parse_text(FILE)
check("the file comes back byte for byte", af.text() == FILE)
check("two ancillaries, and the triggers are not among them", len(af.ancillaries) == 2)
check("nothing to warn about", af.warnings == [])

guard = af.get("iron_guard")
check("Type and Transferable — the two lines the guide never mentions",
      guard.get("Type") == "follower" and guard.transferable is False)
check("Image ignores the inline comment", guard.get("Image") == "iron_guard.tga")
check("Unique is a line, not a value", guard.unique is True)
check("ExcludedAncillaries splits on commas",
      guard.excluded_ancillaries == ["iron_guard", "rohan_horn"])
check("so does ExcludeCultures, spacing and all",
      guard.exclude_cultures == ["greek", "noldor"])
check("effects, in order",
      [(e.attribute, e.amount) for e in guard.effects]
      == [("Command", "1"), ("PersonalSecurity", "2")])
check("an ancillary with no effects has none", af.get("rohan_horn").effects == [])
check("Transferable 1 reads as transferable", af.get("rohan_horn").transferable is True)
check("the block stops before the banner below it",
      af.block_text(af.get("rohan_horn")).rstrip().endswith("rohan_horn_effects_desc"))

print("\nparse_block: a pane holds exactly one ancillary")
for label, text, want in (
        ("no Ancillary line", "    Type item\r\n", "starts with"),
        ("two ancillaries", "Ancillary a\n  Type i\nAncillary b\n  Type i\n",
         "one at a time"),
        ("a trigger in the pane", "Ancillary a\n  Type i\nTrigger x\n", "Trigger")):
    try:
        ancillaries.parse_block(text)
        check(f"refused: {label}", False)
    except ancillaries.AncillaryError as e:
        check(f"refused: {label} ({e.message[:38]}…)", want in e.message)

print("\nediting: a splice, so untouched lines stay untouched")
base = af.block_text(guard)
check("no edits changes no bytes", ancillaries.render_block(base, {}) == base)

out = ancillaries.render_block(base, {"type": "item"})
check("a changed value changes its line, in place",
      "Type item" in out
      and [a == b for a, b in zip(out.split("\r\n"), base.split("\r\n"))].count(False) == 1)
check("its neighbours are untouched", "Transferable 0" in out and "Unique" in out)

out = ancillaries.render_block(base, {"image": "new_guard.tga"})
check("the inline comment survives an edit", "new_guard.tga\t; the old one" in out)

out = ancillaries.render_block(base, {"unique": False})
check("Unique switched off deletes the line", "Unique" not in out)
check("switched on again it lands between Image and ExcludedAncillaries",
      [ln.strip().split()[0] for ln in
       ancillaries.render_block(out, {"unique": True}).split("\r\n")[1:7]]
      == ["Type", "Transferable", "Image", "Unique", "ExcludedAncillaries",
          "ExcludeCultures"])

out = ancillaries.render_block(base, {"exclude_cultures": []})
check("an emptied optional line is deleted", "ExcludeCultures" not in out)
check("…and nothing else went with it",
      "ExcludedAncillaries" in out and "Description" in out)
check("a list re-sent unchanged rewrites nothing — `greek,  noldor` has two spaces",
      ancillaries.render_block(base, {"exclude_cultures": ["greek", "noldor"]}) == base)

for field_, why in (("type", "Type"), ("image", "Image"),
                    ("description", "Description")):
    try:
        ancillaries.render_block(base, {field_: ""})
        check(f"refused: emptying {why}", False)
    except ancillaries.AncillaryError as e:
        check(f"refused: emptying {why} ({e.message[:34]}…)", why in e.message)

plain = ("Ancillary bare\n    Type item\n    Transferable 1\n    Image bare.tga\n"
         "    Description bare_desc\n    EffectsDescription bare_effects_desc\n")
out = ancillaries.render_block(plain, {"unique": True,
                                       "excluded_ancillaries": ["bare"],
                                       "exclude_cultures": ["greek"]})
check("three lines inserted at once land in the engine's order",
      [ln.strip().split()[0] for ln in out.split("\n")[1:9]]
      == ["Type", "Transferable", "Image", "Unique", "ExcludedAncillaries",
          "ExcludeCultures", "Description", "EffectsDescription"])
check("and check() is happy with the result",
      ancillaries.check(ancillaries.parse_block(out)) == [])

out = ancillaries.render_block(base, {"effects": [{"attribute": "Command", "amount": "1"},
                                                  {"attribute": "PersonalSecurity",
                                                   "amount": "2"},
                                                  {"attribute": "Piety", "amount": "1"}]})
check("a new effect copies the indent of the ones above it",
      "    Effect Piety 1" in out)
out = ancillaries.render_block(base, {"effects": [{"attribute": "Command",
                                                   "amount": "-1"}]})
check("changing one effect and dropping the other",
      [(e.attribute, e.amount)
       for e in ancillaries.parse_block(out).effects] == [("Command", "-1")])

print("\nchecks: what is wrong with a file that parses")
found = ancillaries.check_file(af, triggers.parse_text(FILE))
check("a trigger granting an ancillary that does not exist",
      any(f["kind"] == "unknown-acquire" and f["ancillary"] == "no_such_thing"
          for f in found))
check("and nothing else is wrong with this file",
      sorted({f["kind"] for f in found}) == ["unknown-acquire"])

bad = lambda text, known=None: {f["kind"] for f in ancillaries.check(
    ancillaries.parse_block(text), known)}
STEM = "Ancillary x\n    Type item\n    Transferable 1\n    Image x.tga\n"
TAIL = "    Description d\n    EffectsDescription e\n"
check("a missing required line",
      "missing-line" in bad("Ancillary x\n    Type item\n"))
check("Transferable that is neither 0 nor 1",
      "bad-transferable" in bad("Ancillary x\n    Type item\n    Transferable 2\n"
                                "    Image x.tga\n" + TAIL))
check("more than 3 excluded ancillaries (an errorless crash)",
      "too-many-excluded" in bad(STEM + "    ExcludedAncillaries a, b, c, d\n" + TAIL))
check("more than 8 effects (cannot be gained from a trigger)",
      "too-many-effects" in bad(STEM + TAIL + "    Effect Command 1\n" * 9))
check("a Unique that is not on its own exclusion list",
      "unique-not-excluded" in bad(STEM + "    Unique\n" + TAIL))
check("…and none reported when it is",
      "unique-not-excluded" not in bad(STEM + "    Unique\n"
                                       "    ExcludedAncillaries x\n" + TAIL))
check("an excluded ancillary the file does not define",
      "unknown-excluded" in bad(STEM + "    ExcludedAncillaries nope\n" + TAIL, {"x"}))
check("an attribute that is not one",
      "unknown-attribute" in bad(STEM + TAIL + "    Effect Bravery 1\n"))
check("lines in an order no real ancillary writes",
      "line-order" in bad("Ancillary x\n    Image x.tga\n    Type item\n"
                          "    Transferable 1\n" + TAIL))
check("a duplicate name",
      any(f["kind"] == "duplicate-ancillary" for f in ancillaries.check_file(
          ancillaries.parse_text("Ancillary a\n    Type i\n    Transferable 1\n"
                                 "    Image a.tga\n" + TAIL +
                                 "Ancillary a\n    Type i\n    Transferable 1\n"
                                 "    Image a.tga\n" + TAIL))))

print("\nCode View")
doc = codeview.parse("ancillaries", base, {"ancillary": "iron_guard"})
lines = base.split("\r\n")
on = lambda label, want: (doc.spans.get(label)
                          and lines[doc.spans[label][0][0] - 1].strip().startswith(want))
check("the name span is the Ancillary line", on("name", "Ancillary iron_guard"))
check("each line has its own span",
      on("type", "Type") and on("image", "Image") and on("unique", "Unique"))
check("an effect has its own span", on("effect#2", "Effect PersonalSecurity"))
check("every span points inside the block",
      all(1 <= a <= b <= len(lines) for v in doc.spans.values() for a, b in v))
check("fields and spans use the same labels", {f[0] for f in doc.fields} <= set(doc.spans))
check("render goes through the save's own serialiser",
      codeview.render("ancillaries", base, {"type": "item"},
                      {"ancillary": "iron_guard"}).text
      == ancillaries.render_block(base, {"type": "item"}))
try:
    codeview.parse("ancillaries", base.replace("Ancillary iron_guard",
                                               "Ancillary steel_guard"),
                   {"ancillary": "iron_guard"})
    check("refused: renaming the ancillary in the text pane", False)
except codeview.CodeViewError as e:
    check(f"refused: renaming it in the text pane ({e.message[:30]}…)",
          "orphan" in e.message)

print("\nthe editor: overview, detail, and a save that goes to disk")
work = Path(tempfile.mkdtemp(prefix="tk-anc-")) / "TestMod"
(work / "data" / "text").mkdir(parents=True)
(work / "data" / "ui" / "ancillaries").mkdir(parents=True)
keyblock.write_text(work / "data" / "export_descr_ancillaries.txt", FILE,
                    ancillaries.ENCODING)
keyblock.write_text(work / "data" / "text" / "export_ancillaries.txt",
                    "﻿¬ test\r\n{iron_guard}Iron Guard\r\n"
                    "{iron_guard_desc}A watchful sort.\r\n", "utf-16")
(work / "data" / "ui" / "ancillaries" / "iron_guard.tga").write_bytes(b"\0" * 32)
mod = Mod(work)
eda = work / "data" / "export_descr_ancillaries.txt"

ov = ancillaries.overview(mod)
check("overview lists every ancillary",
      [r["name"] for r in ov["ancillaries"]] == ["iron_guard", "rohan_horn"])
check("the localised name leads, the code name follows",
      ov["ancillaries"][0]["label"] == "Iron Guard (iron_guard)")
check("a row says how many triggers grant it", ov["ancillaries"][0]["triggers"] == 1)
check("the types the mod uses are collected for the picker",
      ov["types"] == ["follower", "item"])
# A picture the mod does not ship means two different things, and the tool is
# only allowed to say the harsher one when it can see the game's own copies.
# Vanilla keeps them inside its .pack files, so on most machines it cannot —
# and asserting a blank slot anyway produced 56 false findings on Third Age
# Reforged and 2 on DaC. `vanilla_images` is the seam, so the test drives it.
_real_vanilla = ancillaries.vanilla_images
stock = work.parent / "unpacked_ui"
stock.mkdir(exist_ok=True)

ancillaries.vanilla_images = lambda: None
found = ancillaries.check_file(af, None, mod)
check("no vanilla copies to check against: reported, but not called missing",
      [f["kind"] for f in found if f["ancillary"] == "rohan_horn"] == ["unverified-image"])
check("...and it says how to get the check back",
      any("vanilla_ancillaries_dir" in f["message"] for f in found))

ancillaries.vanilla_images = lambda: stock
check("vanilla copies visible and it is in neither: a real missing picture",
      any(f["kind"] == "missing-image" and f["ancillary"] == "rohan_horn"
          for f in ancillaries.check_file(af, None, mod)))

(stock / "rohan_horn.tga").write_bytes(bytes(32))
check("vanilla ships it: no finding at all",
      not any(f["ancillary"] == "rohan_horn"
              for f in ancillaries.check_file(af, None, mod)
              if f["kind"] in ("missing-image", "unverified-image")))
check("...and the mod's own copy still wins for the one it does ship",
      ancillaries.image_path(mod, "iron_guard.tga")
      == work / "data" / "ui" / "ancillaries" / "iron_guard.tga")
ancillaries.vanilla_images = _real_vanilla

d = ancillaries.detail(mod, "iron_guard")
check("detail finds the picture that IS there", d["image_found"] is True)
check("…the triggers that grant it", [t["name"] for t in d["triggers"]] == ["gains_guard"])
check("…and which text keys are missing",
      d["missing_loc"] == ["iron_guard_effects_desc"])

p = ancillaries.plan(mod, {"ancillary": "test_ring", "action": "add", "edits": {
    "type": "ring", "transferable": "0", "unique": True,
    "excluded_ancillaries": ["test_ring"],
    "effects": [{"attribute": "Piety", "amount": "2"}]},
    "loc": {"test_ring": "Ring of Testing"}})
check("a create plans a block, its text keys and nothing else",
      p.payload()["ok"] and p.changes[0] == "+ Ancillary test_ring"
      and set(p.loc_writes) == {"test_ring", "test_ring_desc",
                                "test_ring_effects_desc"})
check("the new block is written in the engine's order",
      [ln.split()[0] for ln in p.block.split("\n") if ln.strip()]
      == ["Ancillary", "Type", "Transferable", "Image", "Unique",
          "ExcludedAncillaries", "Description", "EffectsDescription", "Effect"])
check("and it passes its own checks", ancillaries.check(
    ancillaries.parse_block(p.block), {"test_ring"}) == [])
ancillaries.apply(p)
after = ancillaries.parse_file(eda)
check("it is on disk, above the trigger section",
      after.get("test_ring") is not None
      and after.get("test_ring").start < after.trigger_start)
check("the wording reached export_ancillaries.txt",
      ancillaries.loc(Mod(work))["test_ring"] == "Ring of Testing")
check("…and the placeholder for the keys nobody typed",
      ancillaries.loc(Mod(work))["test_ring_desc"] == "test_ring_desc")

p = ancillaries.plan(mod, {"ancillary": "test_ring", "action": "edit",
                           "edits": {"transferable": "1", "type": "trinket"},
                           "loc": {"test_ring": "Ring of Proof"}})
check("an edit plans both files", "~ Trigger" not in " ".join(p.changes)
      and p.loc_writes == {"test_ring": "Ring of Proof"})
ancillaries.apply(p)
r = ancillaries.parse_file(eda).get("test_ring")
check("the edit landed on the right lines",
      r.get("Type") == "trinket" and r.transferable is True)
check("and the reworded text with it",
      ancillaries.loc(Mod(work))["test_ring"] == "Ring of Proof")

p = ancillaries.plan(mod, {"ancillary": "test_ring", "action": "add"})
check("adding a name the file already has is refused",
      not p.payload()["ok"] and "already an ancillary" in p.errors[0])

p = ancillaries.plan(mod, {"ancillary": "iron_guard", "action": "edit",
                           "triggers": {"adds": [{"trigger": {
                               "name": "guard_on_victory",
                               "when_to_test": "PostBattle",
                               "conditions": [{"term": "WonBattle", "args": []}],
                               "effects": [{"keyword": "AcquireAncillary",
                                            "args": ["iron_guard", "chance", "20"]}]}}]}})
ancillaries.apply(p)
made = triggers.parse_file(eda).get("guard_on_victory")
check("a trigger built in the GUI reaches disk in the language",
      made is not None and made.when_to_test == "PostBattle"
      and [c.term for c in made.conditions] == ["WonBattle"]
      and made.effects[0].keyword == "AcquireAncillary")

p = ancillaries.plan(mod, {"ancillary": "iron_guard", "action": "delete"})
check("deleting takes the triggers that only granted it",
      sum(1 for c in p.changes if c.startswith("- Trigger")) == 2)
ancillaries.apply(p)
gone = ancillaries.parse_file(eda)
check("it is gone and the file still parses", gone.get("iron_guard") is None)
check("no trigger is left granting it",
      not [f for f in ancillaries.check_file(gone, triggers.parse_file(eda))
           if f["kind"] == "unknown-acquire" and f["ancillary"] == "iron_guard"])

from unittransfer import transfer
rec = config.load_log()[-1]
transfer.undo(rec["id"])
check("and the log puts the whole job back",
      ancillaries.parse_file(eda).get("iron_guard") is not None
      and triggers.parse_file(eda).get("gains_guard") is not None)

print("\nthe real files")
root = config.get_med2_root()
mods = sorted((Path(root) / "mods").glob("*/data/export_descr_ancillaries.txt")) \
    if root else []
if not mods:
    print("  (no mods installed — the sweep that matters is skipped)")
else:
    total = 0
    for path in mods:
        text = keyblock.read_text(path, ancillaries.ENCODING)
        parsed = ancillaries.parse_text(text)
        m = Mod(path.parents[1])
        found = ancillaries.check_file(parsed, triggers.parse_text(text), m)
        total += len(parsed.ancillaries)
        name = path.parts[-3]
        check(f"{name}: {len(parsed.ancillaries)} ancillaries come back byte for byte",
              parsed.text() == text)
        check(f"{name}: every construct in it is named", parsed.warnings == [])
        check(f"{name}: every record re-renders to itself unchanged",
              all(ancillaries.render_block(parsed.block_text(a), {})
                  == parsed.block_text(a) for a in parsed.ancillaries))
        check(f"{name}: {len(found)} findings, and they are not a flood",
              len(found) < max(3, len(parsed.ancillaries) / 20))
    print(f"  swept {len(mods)} file(s), {total} ancillaries")

print(f"\n{sum(ok)}/{len(ok)} checks passed")
sys.exit(0 if all(ok) else 1)
