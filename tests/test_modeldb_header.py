"""modeldb header layout: the body must be located by token position, not by
the first newline.

Most mods write the header as a single line (`...0 0 \\n5 blank`), but some wrap
it mid-header (`...0 0 \\n595 \\n0 0 \\n5 blank`). Reading the body from
`text.find("\\n")+1` then starts mid-header, where the entry COUNT gets read as
a string length and swallows the first entry whole -- which surfaced as
`could not convert string to float: 'nit_models/...'` (note the eaten `u`).

    python -m tests.test_modeldb_header
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import modeldb

ok = []


def check(label, cond):
    ok.append(bool(cond))
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}")


def one_entry(name, tex):
    """A minimal but complete entry: 1 LOD, 1 main texture, 0 attach, 1 anim."""
    return (
        f"\n{len(name)} {name} \n1.0 \n1 "
        f"\n{len('m/' + name + '.mesh')} m/{name}.mesh 121 "
        f"\n1 \n4 ever \n{len(tex)} {tex} \n{len(tex)} {tex} \n0 "
        f"\n0 "
        f"\n1 \n5 horse \n3 pri \n3 sec \n0 \n0 "
        f"\n-1 0.0 0.0 0.0 0.0 0.0 0.0 "
    )


BLANK = "\n5 blank " + " ".join(["0"] * 39) + " "
BODY = BLANK + one_entry("mount_pony", "unit_models/mounts/pony.texture") \
             + one_entry("mount_cob", "unit_models/mounts/cob.texture")

# 3 entries counted in the header = blank + 2 real ones
SINGLE_LINE = "22 serialization::archive 3 0 0 0 0 3 0 0" + BODY
# the same file with the header wrapped -- the layout that used to break
WRAPPED = "22 serialization::archive 3 0 0 0 0 \n3 \n0 0" + BODY

print("== header layouts ==")
for label, text in (("single-line header", SINGLE_LINE), ("wrapped header", WRAPPED)):
    db = modeldb.parse_text(text)
    check(f"{label}: 2 entries parsed", len(db.entries) == 2)
    check(f"{label}: names intact",
          [e.name for e in db.entries] == ["mount_pony", "mount_cob"])
    check(f"{label}: first entry's paths are not truncated",
          db.entries[0].texture_files() == ["unit_models/mounts/pony.texture"])
    check(f"{label}: round-trips byte-exact", db.to_text() == text)
    check(f"{label}: header count read from the right slot", db.header_ints[5] == 3)

print("\n== both layouts describe the same models ==")
a = modeldb.parse_text(SINGLE_LINE)
b = modeldb.parse_text(WRAPPED)
check("entry content is identical across layouts",
      [e.content_key() for e in a.entries] == [e.content_key() for e in b.entries])

print("\n== a real wrapped-header file, if present ==")
sample = Path(r"C:\Users\projy\Downloads\battle_models.modeldb")
if sample.is_file():
    text = sample.read_text(encoding=modeldb.ENCODING)
    db = modeldb.parse_text(text)
    check(f"parses ({len(db.entries)} entries)", len(db.entries) > 0)
    check("entry count matches the header's count-1",
          len(db.entries) + 1 == db.header_ints[5])
    check("round-trips byte-exact", db.to_text() == text)
    check("no entry name looks like a swallowed path",
          not any("/" in e.name for e in db.entries))
else:
    print("  (skipped -- sample file not on this machine)")

print(f"\n{sum(ok)}/{len(ok)} checks — " + ("ALL PASSED" if all(ok) else "SOME FAILED"))
sys.exit(0 if all(ok) else 1)
