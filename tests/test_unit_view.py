"""Phase 14f — the EDB unit view: twin awareness and its read-only code view.

Two things this phase added on the Python side, both measured against whatever
mods are installed rather than a fixture:

* ``buildings.unit_instances`` now answers "does the settlement's OTHER half
  train this unit at the facing tier?" per row, which is what makes the city /
  castle divergence visible from the unit's side.
* ``codeview.pools_document`` — the one code view in the toolkit that is not a
  record. It gathers ``recruit_pool`` lines from however many building blocks
  they come from, so it is read-only by construction.

    python -m tests.test_unit_view
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _realmod
from unittransfer import buildings, codeview
from unittransfer.mod import Mod

ok = fail = 0


def check(cond, label, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  [OK ] {label}")
    else:
        fail += 1
        print(f"  [BAD] {label}" + (f" — {detail}" if detail else ""))


def note(text):
    print(f"  ---- {text}")


def pick_unit(mod, want_twin_gap=False):
    """A unit with recruit pools; optionally one whose twin tier lacks it."""
    for u in mod.edu.units:
        rows = buildings.unit_instances(mod, u.type)["instances"]
        if not rows:
            continue
        if not want_twin_gap:
            return u.type, rows
        if any(r["twin"] and r["twin_level"] and not r["twin_has"] for r in rows):
            return u.type, rows
    return "", []


def run(mod):
    print(f"\n== {mod.name} ==")

    # ---- the twin columns exist and are self-consistent ----
    unit, rows = pick_unit(mod)
    if not rows:
        note("no unit in this mod is trained by any building — nothing to check")
        return

    keys = ("twin", "twin_level", "twin_level_label", "twin_has")
    check(all(k in r for r in rows for k in keys),
          f"every row carries the twin columns ({unit}, {len(rows)} pool(s))")

    # A row with no twin BUILDING cannot have a twin tier, and a row with no
    # twin tier cannot claim the twin trains anything.
    bad_level = [r for r in rows if not r["twin"] and r["twin_level"]]
    check(not bad_level, "no twin building means no twin tier", str(bad_level[:1]))

    # measured over the whole mod, because one unit proves very little
    tally = {"no twin": 0, "no facing tier": 0, "twin trains it": 0, "twin does not": 0}
    checked = 0
    for u in mod.edu.units:
        for r in buildings.unit_instances(mod, u.type)["instances"]:
            checked += 1
            if not r["twin"]:
                tally["no twin"] += 1
            elif not r["twin_level"]:
                tally["no facing tier"] += 1
            elif r["twin_has"]:
                tally["twin trains it"] += 1
            else:
                tally["twin does not"] += 1
    note(f"{checked} pool row(s): " + ", ".join(f"{v} {k}" for k, v in tally.items()))
    check(sum(tally.values()) == checked, "every row falls in exactly one bucket")

    # `twin_has` must agree with the file: if it says the twin trains the unit,
    # the twin's own rows must include one at that level.
    unit, rows = pick_unit(mod)
    disagreed = []
    for r in rows:
        if not (r["twin"] and r["twin_level"]):
            continue
        twin_rows = [x for x in buildings.unit_instances(mod, unit)["instances"]
                     if x["line"] == r["twin"] and x["level"] == r["twin_level"]]
        if bool(twin_rows) != bool(r["twin_has"]):
            disagreed.append((r["line"], r["level"], r["twin_has"], len(twin_rows)))
    check(not disagreed, f"twin_has agrees with the twin's own pools ({unit})",
          str(disagreed[:2]))

    # ---- the read-only code view ----
    doc = codeview.pools_document(mod, unit)
    lines = doc.text.split("\n")
    check(doc.kind == "pools", "the document names its own kind")
    check(len(doc.spans) == len(rows),
          f"one span per pool row ({len(doc.spans)} spans, {len(rows)} rows)")

    # every span points at a line that really is that pool's line
    off = []
    for r in rows:
        span = doc.spans.get(f"pool:{r['cap_line']}")
        if not span:
            off.append((r["cap_line"], "no span"))
            continue
        i = span[0][0] - 1
        if not (0 <= i < len(lines)) or "recruit_pool" not in lines[i]:
            off.append((r["cap_line"], lines[i] if 0 <= i < len(lines) else "out of range"))
    check(not off, "every span lands on a recruit_pool line", str(off[:2]))

    # the pane shows the FILE's bytes, not a re-rendering of them
    src = (Path(mod.data) / buildings.EDB_REL).read_text(
        encoding=buildings.ENCODING).split("\n")
    verbatim = []
    for r in rows:
        i = doc.spans[f"pool:{r['cap_line']}"][0][0] - 1
        shown = lines[i].split("    ; line ")[0]
        real = src[r["cap_line"]].rstrip("\r\n")
        if shown != real:
            verbatim.append((r["cap_line"], shown[:60], real[:60]))
    check(not verbatim, "each pool line is the file's own bytes", str(verbatim[:1]))

    # a building heading for each distinct line, so the list is readable
    heads = [l for l in lines if l.startswith("; ")]
    check(len(heads) == len({r["line"] for r in rows}),
          f"one heading per building line ({len(heads)})")

    # ---- it is read-only, and the registry says so ----
    check("pools" not in codeview.KINDS,
          "no parse/render pair is registered — the pane cannot be saved from")
    check(not codeview.comment_marks("pools"),
          "comment hiding is off: the headings are ours, not the file's")

    # ---- a unit nothing trains is an error, not an empty pane ----
    orphan = next((u.type for u in mod.edu.units
                   if not buildings.unit_instances(mod, u.type)["instances"]), "")
    if orphan:
        try:
            codeview.pools_document(mod, orphan)
            check(False, "a unit no building trains is refused", f"{orphan} returned a doc")
        except KeyError:
            check(True, f"a unit no building trains is refused ({orphan})")
    else:
        note("every unit in this mod is trained somewhere — refusal path not exercised")

    # ---- the twin gap the panel exists to show ----
    gap_unit, gap_rows = pick_unit(mod, want_twin_gap=True)
    if gap_unit:
        g = next(r for r in gap_rows
                 if r["twin"] and r["twin_level"] and not r["twin_has"])
        note(f"a real divergence: {gap_unit} is in {g['line']} · {g['level']} "
             f"but not in {g['twin']} · {g['twin_level']}")
        check(True, "the panel has a real city/castle gap to show")
    else:
        note("this mod's city/castle pairs are perfectly in step — nothing to mirror")


def main():
    # Every installed mod, because the interesting case is a DISAGREEMENT
    # between two of them: DaC's city/castle pairs have drifted apart in 239
    # places and Reforged's have not drifted at all, and a check that only ever
    # saw one of those would look like it was measuring the wrong thing.
    mods = _realmod.installed()
    if not mods:
        print(f"SKIPPED — no installed mod to test against under {_realmod.MODS}")
        return 0
    for path in mods:
        run(Mod(path))
    print(f"\n{ok} passed, {fail} failed")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
