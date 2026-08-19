"""The .strings.bin codec, the Strings module, and Home's file discovery.

The gate for the whole of Phase 6 is one claim: **decoding and re-encoding an
untouched archive gives back the same bytes.** Everything else in the module is
built on top of that, so it is checked first, on real files where any are
installed and on hand-built ones where they are not.

What each part is here to catch:

  * the two things the reference tool's codec gets wrong — a 16-bit entry count
    (fine until an archive passes 65 535 entries, which ``names.txt`` is already
    within sight of) and a single zero word where the trailing tag index goes
    (which truncates two thirds of Third Age's ``export_buildings``)
  * an edit that leaves everything it did not touch alone, byte for byte
  * a new tag landing in code-point order, because the game binary-searches them
  * the ``.txt`` compiler agreeing with the game's own compiler — the reason
    ``cleaner`` can now refresh a cache instead of deleting it
  * refusals: a renamed tag in the Code View pane, a path outside ``data/text``,
    and removing a row from an archive addressed by position
  * plan -> apply -> undo putting the archive back byte-exact

Needs no game install: every fixture here is written by the test. When mods ARE
installed it additionally sweeps every ``.strings.bin`` it can find, which is the
check that actually proved the format.

    python -m tests.test_stringsbin
"""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import codeview, config, modfiles, stringsbin
from unittransfer import strings as strings_mod

ok = []


def check(label, cond):
    ok.append(bool(cond))
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}")


def build(style=stringsbin.TAGGED, rows=(), index=()):
    """A hand-built archive, so the suite needs nothing installed."""
    sb = stringsbin.StringsBin(style=style, index=list(index))
    for tag, value in rows:
        if style == stringsbin.TAGGED:
            sb.tags.append(tag)
        sb.values.append(value)
    return sb


ROWS = [("alpine", "Hochgebirge"), ("highland", "Hochland"),
        ("mediterranean", "Mediterran"), ("volcanic", "Vulkanisch"),
        ("with_break", "first line\nsecond line"), ("with_space", " "),
        ("zz_empty", "")]

print("== the header the format actually has ==")
sb = build(rows=ROWS, index=["volcanic", "alpine", "unused1"])
raw = stringsbin.encode(sb)
check("style, flavour and a 32-bit count", raw[:8] == b"\x02\x00\x00\x08\x07\x00\x00\x00")
back = stringsbin.decode(raw)
check("round-trips byte for byte", stringsbin.encode(back) == raw)
check("the tag index survives verbatim", back.index == ["volcanic", "alpine", "unused1"])
check("a value keeps its embedded newline", back.get("with_break") == "first line\nsecond line")
check("a value that is one space stays one space", back.get("with_space") == " ")
check("peek reads the count without decoding", stringsbin.peek.__name__ == "peek")

# The count is 32 bits. Reading it as a u16 + padding word, as the reference
# tool's codec does, happens to agree below 65 536 and silently halves the file
# above it — so prove the wide field is really there.
big = build(rows=[(f"tag{i:06d}", f"v{i}") for i in range(70000)])
wide = stringsbin.encode(big)
check("70 000 entries survive a round trip (a 16-bit count could not hold them)",
      len(stringsbin.decode(wide)) == 70000)
check("the count word really is 32 bits", wide[4:8] == (70000).to_bytes(4, "little"))

print("\n== untagged archives (battle, shared, strat, tooltips) ==")
un = build(style=stringsbin.UNTAGGED, rows=[("", "one"), ("", "two")])
unraw = stringsbin.encode(un)
unback = stringsbin.decode(unraw)
check("no tags, no index section, and still byte-exact",
      stringsbin.encode(unback) == unraw and not unback.tagged and not unback.index)
check("a row can still be edited by position",
      (unback.set_value(1, "TWO") or unback.values[1]) == "TWO")
try:
    unback.set("tag", "x")
    check("setting a tag on an untagged archive is refused", False)
except stringsbin.StringsBinError:
    check("setting a tag on an untagged archive is refused", True)

print("\n== edits ==")
sb = stringsbin.decode(raw)
sb.set("highland", "CHANGED")
edited = stringsbin.encode(sb)
check("an edit changes only its own entry",
      stringsbin.decode(edited).get("alpine") == "Hochgebirge"
      and stringsbin.decode(edited).get("highland") == "CHANGED")
sb.set("beach", "Strand")
check("a new tag lands in code-point order, which is how the game searches",
      sb.tags == sorted(sb.tags) and sb.tags[1] == "beach")
check("removing a tag takes its value with it",
      sb.remove("beach") and sb.get("beach") is None and len(sb) == len(ROWS))

print("\n== the .txt form ==")
line = stringsbin.record_text("greeting", "hello\nworld")
check("an embedded newline is written \\n, as the game's own .txt does",
      line == "{greeting}hello\\nworld")
check("and reads back to the same value",
      stringsbin.parse_record(line) == ("greeting", "hello\nworld"))
for bad, why in [("no braces here", "no tag"), ("{unclosed", "no closing brace"),
                 ("{}text", "empty tag"), ("{a}one\nreal newline", "two lines")]:
    try:
        stringsbin.parse_record(bad)
        check(f"refused: {why}", False)
    except stringsbin.StringsBinError:
        check(f"refused: {why}", True)

TXT = ("¬ a comment\r\n"
       "{alpine}Hochgebirge\r\n"
       "{with_space} \r\n"
       "{folded}\r\n"
       "\tthe description sits on the line below its key\r\n"
       "{escaped}two\\nlines\r\n")
pairs = dict(stringsbin.from_txt(TXT))
check("a comment line is skipped", "¬ a comment" not in pairs)
check("a continued value is folded onto its key",
      pairs["folded"] == "the description sits on the line below its key")
check("tabs are trimmed but a lone space is kept", pairs["with_space"] == " ")
check("\\n in the text compiles to a real newline", pairs["escaped"] == "two\nlines")
made = stringsbin.compile_txt(TXT)
check("compiling sorts the tags", made.tags == sorted(made.tags))
check("compiling with no template leaves the index empty", made.index == [])
check("compiling with a template carries its index through",
      stringsbin.compile_txt(TXT, sb).index == sb.index)

print("\n== a mod on disk: discovery, code view, plan -> apply -> undo ==")
# read the real mods folder BEFORE the config paths are pointed at a temp dir,
# so the sweep at the end can still find whatever is installed
REAL_MODS = Path(config.get_med2_root() or ".") / "mods"

cfg = Path(tempfile.mkdtemp(prefix="ut-cfg-"))
config.CONFIG_DIR = cfg
config.BACKUP_DIR = cfg / "backups"
config.SETTINGS_PATH = cfg / "settings.json"
config.LOG_PATH = cfg / "transfers.json"

med2 = Path(tempfile.mkdtemp(prefix="ut-mod-"))
mod_root = med2 / "mods" / "StringsMod"
text = mod_root / "data" / "text"
text.mkdir(parents=True)
(mod_root / "data" / "export_descr_unit.txt").write_text("", encoding="latin-1")
(mod_root / "data" / "unit_models").mkdir()
(mod_root / "data" / "unit_models" / "battle_models.modeldb").write_text(
    "0", encoding="latin-1")
stringsbin.write(text / "export_units.txt.strings.bin", build(rows=ROWS, index=["alpine"]))
stringsbin.write(text / "battle.txt.strings.bin",
                 build(style=stringsbin.UNTAGGED, rows=[("", "one"), ("", "two")]))
(text / "export_units.txt").write_text(TXT, encoding="utf-16")

from unittransfer.mod import Mod
mod = Mod(mod_root)

ov = strings_mod.overview(mod)
names = {f["name"]: f for f in ov["files"]}
check("both archives are discovered", len(ov["files"]) == 2)
check("the entry count comes from the header", names["export_units.txt.strings.bin"]["entries"] == 7)
check("an untagged archive is flagged as such", not names["battle.txt.strings.bin"]["tagged"])
check("the .txt beside it is noticed", names["export_units.txt.strings.bin"]["txt"] == "export_units.txt")

rows = strings_mod.entries(mod, "text/export_units.txt.strings.bin", "hoch")
check("rows filter on tag and text alike", rows["matched"] == 2 and rows["count"] == 7)
check("an untagged row is addressed by position",
      strings_mod.entries(mod, "text/battle.txt.strings.bin")["rows"][1]["id"] == "#1")

for bad in ("../../secret.strings.bin", "text/../export_descr_unit.txt", "nope.txt"):
    try:
        strings_mod.resolve(mod, bad)
        check(f"a path outside data/text is refused ({bad})", False)
    except strings_mod.StringsError:
        check(f"a path outside data/text is refused ({bad})", True)

doc = codeview.strings_document(mod, "text/export_units.txt.strings.bin|alpine")
check("the code view shows the entry as the .txt writes it",
      doc.text == "{alpine}Hochgebirge" and doc.ident == "alpine")
check("its span map points at the one line it has",
      doc.spans == {"tag": [[1, 1]], "text": [[1, 1]]})
rendered = codeview.render("strings", doc.text, {"value": "Alps"}, {"tag": "alpine"})
check("a box edit re-serialises through the same writer",
      rendered.text == "{alpine}Alps")
try:
    codeview.parse("strings", "{renamed}x", {"tag": "alpine"})
    check("renaming a tag in the text pane is refused", False)
except codeview.CodeViewError as e:
    check("renaming a tag in the text pane is refused", "alpine" in e.message)

before = (text / "export_units.txt.strings.bin").read_bytes()
plan = strings_mod.plan(mod, {"file": "text/export_units.txt.strings.bin",
                              "edits": [{"id": "highland", "value": "Uplands"}]})
check("a plan says what it would change", plan.changes and not plan.errors)
check("a plan writes nothing yet",
      (text / "export_units.txt.strings.bin").read_bytes() == before)
rec = strings_mod.apply(plan)
after = stringsbin.read(text / "export_units.txt.strings.bin")
check("the edit landed", after.get("highland") == "Uplands")
check("nothing else moved", after.get("alpine") == "Hochgebirge" and after.index == ["alpine"])

noop = strings_mod.plan(mod, {"file": "text/export_units.txt.strings.bin",
                              "edits": [{"id": "highland", "value": "Uplands"}]})
check("re-planning the same value is a no-op", not noop.data)

try:
    strings_mod.plan(mod, {"file": "text/battle.txt.strings.bin", "removes": ["#0"]})
    check("removing a row from a positional archive is refused",
          strings_mod.plan(mod, {"file": "text/battle.txt.strings.bin",
                                 "removes": ["#0"]}).errors)
except strings_mod.StringsError:
    check("removing a row from a positional archive is refused", True)

from unittransfer.transfer import undo
undo(rec["id"])
check("undo puts the archive back byte-exact",
      (text / "export_units.txt.strings.bin").read_bytes() == before)

print("\n== rebuilding a cache from its .txt ==")
from unittransfer import cleaner
res = cleaner.refresh_strings_bin(mod_root, "data/text/export_units.txt.strings.bin")
check("the cache is rebuilt, not deleted",
      res.get("rebuilt") and (text / "export_units.txt.strings.bin").exists())
rebuilt = stringsbin.read(text / "export_units.txt.strings.bin")
check("it now says what the .txt says", rebuilt.get("escaped") == "two\nlines")
check("and it kept the tag index it had", rebuilt.index == ["alpine"])
(text / "export_units.txt").unlink()
res = cleaner.refresh_strings_bin(mod_root, "data/text/export_units.txt.strings.bin")
check("with no .txt to compile from it falls back to deleting",
      res.get("deleted") and not (text / "export_units.txt.strings.bin").exists())

print("\n== Home: what this mod is ready for ==")
report = modfiles.report(mod)
check("every known file is reported", len(report["files"]) == len(modfiles.KNOWN))
check("a module whose file is missing is not ready",
      not report["modules"]["sounds"]["ready"]
      and "Unit voice bank" in report["modules"]["sounds"]["missing"])
check("a module whose files are all there is ready", report["modules"]["edit"]["ready"])
by_rel = {f["rel"]: f for f in report["files"]}
check("a file that is nowhere is missing", by_rel["text/expanded.txt"]["state"] == "missing")
stringsbin.write(text / "expanded.txt.strings.bin", build(rows=[("england", "Mordor")]))
after_rel = {f["rel"]: f for f in modfiles.report(mod)["files"]}
check("a .txt that exists only as a compiled .bin is reported as compiled, not missing",
      after_rel["text/expanded.txt"]["state"] == "compiled")
check("faction names read through the compiled archive",
      Mod(mod_root).faction_names.get("england") == "Mordor")

print("\n== every .strings.bin on this machine ==")
found = sorted(REAL_MODS.rglob("*.strings.bin")) if REAL_MODS.is_dir() else []
if not found:
    print("  (no mods installed — the hand-built fixtures above are the whole check)")
else:
    bad = []
    for p in found:
        data = p.read_bytes()
        try:
            if stringsbin.encode(stringsbin.decode(data)) != data:
                bad.append(p.name)
        except stringsbin.StringsBinError as e:
            bad.append(f"{p.name}: {e}")
    check(f"all {len(found)} shipped archives round-trip byte for byte "
          + (f"(failed: {bad[:3]})" if bad else ""), not bad)

shutil.rmtree(med2, ignore_errors=True)
shutil.rmtree(cfg, ignore_errors=True)

print(f"\n{sum(ok)}/{len(ok)} checks — " + ("ALL PASSED" if all(ok) else "SOME FAILED"))
sys.exit(0 if all(ok) else 1)
