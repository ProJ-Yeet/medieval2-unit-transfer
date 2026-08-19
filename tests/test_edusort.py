"""The EDU cleanup: the tier marker, and the whole-file sorter.

Phase 14e's two halves. The **marker** is the tool's own metadata — a tier
exists in no game file, so it is written as a comment above a unit's ``type``
line under one owned prefix. The **sorter** groups the roster the way a
hand-organised ``export_descr_unit.txt`` is grouped, and the whole of its
difficulty is doing that without moving units their author already placed.

What each part is here to catch:

  * **the marker travels with its own unit.** A comment above ``type`` belongs
    to the PREVIOUS block under the old boundary rule, which would have left the
    marker behind on every transfer, replace and sort. The block now starts at
    the marker, and the parse of a file that has none is unchanged — which is
    every real file, so the round-trip sweeps still mean what they meant.
  * **setting, changing and clearing a tier is lossless**, and clearing the last
    key deletes the line rather than leaving a bare prefix.
  * **the sorter only ever moves a block.** Same units, same fields, same
    comments — asserted here from outside, not by trusting the plan's own check.
  * **it is idempotent.** Running it twice must not differ from running it once,
    which is the exit criterion and the thing most easily broken: the first
    banner of a sorted file lands in the PREAMBLE when it is read back, and
    emitting it again grows the file a banner per run.
  * **an untiered unit does not acquire a tier** by being written under a
    banner and read back — that would move it on the second run.
  * **tiers are read from the file's own banners**, because 907 of DaC's 916
    units already sit under one and nobody should type them again.

Needs no game install for the marker half. When mods ARE installed it sorts each
one in a scratch copy, which is the check that actually matters.

    python -m tests.test_edusort
"""
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _realmod  # noqa: E402

from unittransfer import edu, edusort  # noqa: E402
from unittransfer.mod import Mod  # noqa: E402

ok = []


def check(label, cond):
    ok.append(bool(cond))
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}")


# A file with everything a real one has around a block boundary: a header, a
# banner introducing a unit, an inline comment, and a marker on the last unit.
FILE = (
    ";  the mod's own header\n"
    "\n"
    "type\t\t\tPeasant Archers\n"
    "dictionary\t\tPeasant_Archers\n"
    "category\t\tinfantry\n"
    "attributes\t\tsea_faring, hide_forest\n"
    "ownership\t\tsicily\n"
    "\n"
    ";---------------- GONDOR TIER 2 INFANTRY ----------------\n"
    ";@m2gt tier=2 variant=aor\n"
    "type\t\t\tGondor Pikemen\t\t;the good ones\n"
    "dictionary\t\tGondor_Pikemen\n"
    "category\t\tinfantry\n"
    "ownership\t\tsicily\n"
)

print("== the marker: a block boundary, and reading it ==")
f = edu.parse_text(FILE)
check("the file still round-trips byte for byte", f.to_text() == FILE)
check("two units", len(f.units) == 2)
check("the marker's unit reads its tier", f.units[1].tier == "2")
check("…and its variant", f.units[1].variant == "aor")
check("a unit with no marker has no tier", f.units[0].tier == "")
check("the marker is INSIDE its own unit's block",
      f.units[1].raw.startswith(";@m2gt"))
check("…and not in the block above it", ";@m2gt" not in f.units[0].raw)
check("the banner above it stays with the block above — it is that unit's filler",
      "GONDOR TIER 2" in f.units[0].raw)
check("the preamble is unchanged by the rule",
      f.preamble == ";  the mod's own header\n\n")

print("\n== writing a marker ==")
plain = "type\t\t\tFoo\ncategory\t\tinfantry\n"
one = edu.set_marker(plain, tier="3")
check("a marker is created above `type`", one.splitlines()[0] == ";@m2gt tier=3")
two = edu.set_marker(one, variant="aor")
check("a second key joins the same line",
      two.splitlines()[0] == ";@m2gt tier=3 variant=aor")
check("the line count grew by exactly one",
      len(two.splitlines()) == len(plain.splitlines()) + 1)
check("a changed value rewrites in place",
      edu.set_marker(two, tier="4").splitlines()[0] == ";@m2gt tier=4 variant=aor")
check("clearing one key keeps the other",
      edu.set_marker(two, variant="").splitlines()[0] == ";@m2gt tier=3")
check("clearing every key deletes the line, not leaving a bare prefix",
      edu.set_marker(edu.set_marker(two, variant=""), tier="") == plain)
check("asking to clear a marker that was never there changes nothing",
      edu.set_marker(plain, tier="") == plain)
check("the fields read back", edu.marker_fields(two) == {"tier": "3", "variant": "aor"})
check("a marker survives being parsed and re-emitted",
      edu.parse_text(two).units[0].raw == two)

print("\n== the marker travels with its unit ==")
blk = edu.parse_text(FILE).units[1].raw
check("a copied block keeps its marker",
      ";@m2gt" in edu.strip_trailing_filler(blk))
check("a renamed unit keeps its marker",
      ";@m2gt tier=2 variant=aor" in edu.rewrite_block(blk, type_new="Something Else"))

print("\n== reading tiers out of a file's own banners ==")
got = edusort.harvest(FILE)
check("the banner's tier is found", got.get("Gondor Pikemen", ("", ""))[1] == "2")
check("…and its section, in the author's own words",
      got.get("Gondor Pikemen", ("", ""))[0] == "GONDOR")
check("a `type` line's trailing comment is not read as part of the name",
      "Gondor Pikemen" in got)
check("a unit above every banner is not given one", "Peasant Archers" not in got)
check("a banner with no tier gives a group and no tier",
      edusort.harvest(";--- ROHAN CAVALRY ---\ntype\tX\n").get("X") == ("ROHAN", ""))
check("a comment that is not one of our banners is not read as one",
      edusort.BANNER_RE.match(";-- just something somebody wrote --") is None)
check("a hand-spelt CALVARY is still read (8 real ones in DaC)",
      edusort.BANNER_RE.match(";--- DUNLAND TIER 1 CALVARY ---") is not None)

print("\n== the banner a section is written under ==")
b = edusort.banner("GONDOR TIER 2 INFANTRY")
m = edusort.BANNER_RE.match(b)
check("what the sorter writes, the sorter can read back", m is not None)
check("…with the same section", m and m.group("name").strip() == "GONDOR")
check("…and the same tier", m and m.group("tier") == "2")
untiered = edusort.BANNER_RE.match(edusort.banner("GONDOR INFANTRY"))
check("an untiered banner round-trips WITHOUT inventing a tier",
      untiered is not None and not untiered.group("tier"))

print("\n== the sorter, on every installed mod ==")
mods = [m for m in _realmod.installed()
        if (m / "data" / "export_descr_unit.txt").is_file()]
if not mods:
    print("  (no installed mod with an EDU — the sweep is skipped)")
for src in mods:
    name = src.name
    work = Path(tempfile.mkdtemp()) / name
    (work / "data").mkdir(parents=True)
    for rel in ("export_descr_unit.txt", "descr_sm_factions.txt", "text/expanded.txt"):
        s = src / "data" / rel
        if s.is_file():
            (work / "data" / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s, work / "data" / rel)
    edu_path = work / "data" / "export_descr_unit.txt"
    before = edu_path.read_text(encoding=edu.ENCODING)

    p = edusort.plan(Mod(work))
    check(f"{name}: the plan is clean", p.errors == [])
    if p.errors or not p.text:
        continue

    a, b2 = edu.parse_text(before), edu.parse_text(p.text)
    fa = {u.type: edu.block_fields(u.raw) for u in a.main_units}
    fb = {u.type: edu.block_fields(u.raw) for u in b2.main_units}
    check(f"{name}: all {len(fa)} units are still there, and no others",
          set(fa) == set(fb))
    check(f"{name}: every unit's fields are untouched", fa == fb)

    def others(text):
        """Every comment line that is neither our banner nor our marker."""
        return Counter(l.strip() for l in text.splitlines()
                       if l.strip().startswith(";")
                       and not edusort.BANNER_RE.match(l) and not edu.is_marker(l))

    lost = others(before) - others(p.text)
    check(f"{name}: not one of the {sum(others(before).values())} comment lines "
          f"is lost", not lost)
    check(f"{name}: fewer units move than stay put "
          f"({len(p.moved)} of {len(fa)})", len(p.moved) < len(fa) / 2)

    edu_path.write_text(p.text, encoding=edu.ENCODING)
    p2 = edusort.plan(Mod(work))
    check(f"{name}: running it a second time changes nothing", not p2.text)

    # a tier set in the editor has to survive the cleanup that reads tiers itself
    f3 = edu.parse_text(edu_path.read_text(encoding=edu.ENCODING))
    victim = f3.main_units[len(f3.main_units) // 2]
    marked = edu.set_marker(victim.raw, tier="5", variant="quest")
    edu_path.write_text(
        f3.preamble + "".join(marked if u is victim else u.raw
                              for u in f3.main_units),
        encoding=edu.ENCODING)
    p3 = edusort.plan(Mod(work))
    if p3.text:
        edu_path.write_text(p3.text, encoding=edu.ENCODING)
    after = edu.parse_text(edu_path.read_text(encoding=edu.ENCODING)).by_type()
    kept = after.get(victim.type)
    check(f"{name}: a tier set by hand survives a cleanup",
          kept is not None and kept.tier == "5" and kept.variant == "quest")

    o = edusort.overview(Mod(work))
    check(f"{name}: the ordering screen lists every unit exactly once",
          sum(len(s["units"]) for s in o["sections"]) == len(fa))

    # a hand placement leads its section, over whatever the tier would have said
    sec = next(s for s in o["sections"] if len(s["units"]) > 3)
    last = sec["units"][-1]["type"]
    hp = edusort.plan(Mod(work), hand={sec["name"]: [last]})
    if hp.text:
        edu_path.write_text(hp.text, encoding=edu.ENCODING)
    lead = next(s for s in edusort.overview(Mod(work))["sections"]
                if s["name"] == sec["name"])["units"][0]["type"]
    check(f"{name}: a unit placed by hand leads its section", lead == last)
    # the point of recording it: the NEXT cleanup must not argue with the user
    p4 = edusort.plan(Mod(work))
    check(f"{name}: the cleanup after a hand placement leaves it alone", not p4.text)


print("\n== apply, and undo ==")
if mods:
    src = mods[0]
    work = Path(tempfile.mkdtemp()) / src.name
    (work / "data").mkdir(parents=True)
    for rel in ("export_descr_unit.txt", "descr_sm_factions.txt", "text/expanded.txt"):
        s = src / "data" / rel
        if s.is_file():
            (work / "data" / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s, work / "data" / rel)
    edu_path = work / "data" / "export_descr_unit.txt"
    original = edu_path.read_text(encoding=edu.ENCODING)

    from unittransfer import config, transfer  # noqa: E402

    res = edusort.apply(edusort.plan(Mod(work)))
    check("the cleanup reaches disk", edu_path.read_text(encoding=edu.ENCODING) != original)
    check("it is one job with one id", bool(res.get("id")))
    rec = config.load_log()[-1]
    check("the log records it as an EDU cleanup", rec["mode"] == "edu")
    check("one file backed up, none created",
          rec["manifest"]["backed_up"] == [edusort.REL]
          and rec["manifest"]["created"] == [])
    transfer.undo(rec["id"])
    check("undo puts the file back byte for byte",
          edu_path.read_text(encoding=edu.ENCODING) == original)

print(f"\n{sum(ok)}/{len(ok)} checks passed")
sys.exit(0 if all(ok) else 1)
