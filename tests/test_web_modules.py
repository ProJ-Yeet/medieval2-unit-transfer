"""The UI's split JavaScript: one global scope, so nothing may collide.

`web/index.html` loads `web/js/*.js` as plain <script> tags — no build step, no
module system. Everything therefore shares ONE global scope, which makes two
mistakes silent and expensive:

  * **a duplicate top-level name.** Whichever declaration loads last wins, and
    function declarations hoist, so the loser's callers quietly call the winner.
    This already happened once: the composer's `setMode` swallowed the burger
    menu's until it was renamed `setAppMode`.
  * **a file that stops being loaded.** Deleting a <script> tag, or adding a
    module file and forgetting the tag, leaves the page half-wired at runtime
    rather than failing at build time — there is no build.

So this test reads the script tags out of index.html and holds them against the
files on disk, then scans every top-level declaration for collisions. It needs
no game install and no browser. Node, if present, also syntax-checks each file.

    python -m tests.test_web_modules
"""
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

WEB = ROOT / "web"
JS = WEB / "js"

ok = []


def check(label, cond):
    ok.append(bool(cond))
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}")


#: A top-level declaration starts at column 0 — everything nested is indented.
#: That is the file's own convention and the split preserved it.
DECL = re.compile(
    r"^(?:async\s+function|function)\s+([A-Za-z_$][\w$]*)"
    r"|^(?:const|let|var)\s+([A-Za-z_$][\w$]*)"
    r"|^class\s+([A-Za-z_$][\w$]*)")


def declarations(path: Path) -> list[str]:
    names = []
    for line in path.read_text(encoding="utf-8").split("\n"):
        if not line or line[0].isspace():
            continue
        m = DECL.match(line)
        if m:
            names.append(next(g for g in m.groups() if g))
    return names


print("== index.html and web/js agree ==")
html = (WEB / "index.html").read_text(encoding="utf-8")
tags = re.findall(r'<script src="js/([A-Za-z0-9_.-]+\.js)"></script>', html)
on_disk = sorted(p.name for p in JS.glob("*.js"))

check("index.html has script tags", bool(tags))
check("no file is loaded twice", len(tags) == len(set(tags)))
check(f"every tag exists on disk ({len(tags)} tags)",
      all((JS / t).is_file() for t in tags))
missing = sorted(set(on_disk) - set(tags))
check(f"every file on disk is loaded{': ' + ', '.join(missing) if missing else ''}",
      not missing)
check("core.js is loaded first — it declares the state everything reads",
      tags and tags[0] == "core.js")
check("boot.js is loaded last — it calls init()", tags and tags[-1] == "boot.js")
check("no inline <script> block is left in index.html",
      not re.search(r"<script>\s*\n", html))

print("\n== one global scope: no duplicate top-level names ==")
where = defaultdict(list)
for name in tags:
    for decl in declarations(JS / name):
        where[decl].append(name)
dupes = {n: f for n, f in where.items() if len(f) > 1}
for n, files in sorted(dupes.items()):
    print(f"       {n} declared in {', '.join(files)}")
check(f"{len(where)} top-level names, none declared twice", not dupes)

print("\n== the modules are syntactically valid ==")
node = shutil.which("node")
if not node:
    print("  [skip] node not on PATH — syntax check needs it")
else:
    bad = []
    for name in tags:
        r = subprocess.run([node, "--check", str(JS / name)],
                           capture_output=True, text=True)
        if r.returncode:
            bad.append(f"{name}: {r.stderr.strip().splitlines()[0] if r.stderr else '?'}")
    for b in bad:
        print(f"       {b}")
    check(f"all {len(tags)} module files parse", not bad)

    # Loaded together they must also be one valid program — a stray brace in one
    # file can parse alone and still break the page.
    joined = "\n".join((JS / n).read_text(encoding="utf-8") for n in tags)
    # encoding= is not optional: the UI is full of emoji and the Windows default
    # for a pipe is cp1252, which cannot carry them.
    r = subprocess.run(
        [node, "-e", "new (require('vm').Script)(require('fs').readFileSync(0,'utf8'))"],
        input=joined, capture_output=True, text=True, encoding="utf-8")
    check("concatenated in load order, they parse as one program", r.returncode == 0)

print(f"\n{sum(ok)}/{len(ok)} checks — " + ("ALL PASSED" if all(ok) else "SOME FAILED"))
sys.exit(0 if all(ok) else 1)
