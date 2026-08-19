"""Which real mod a test should measure itself against.

Three suites were written against ``Third_Age_6`` by name and died with a
``FileNotFoundError`` traceback the moment it was not installed — which says
nothing about the tool and hides whatever the run was meant to prove. The
installed set changes; the thing being tested does not. So a test names the mod
it *prefers* and takes whatever real mod is there instead, and when there is no
mod at all it says so and exits 0 rather than pretending to have failed.
"""
import sys
from pathlib import Path

MODS = Path(r"C:/Users/projy/Downloads/Games/Total War MEDIEVAL II Definitive Edition/mods")


def installed(exclude=()) -> list:
    """Every mod folder under :data:`MODS` that really has a ``data/`` in it."""
    drop = {str(e).lower() for e in exclude}
    if not MODS.is_dir():
        return []
    return sorted((p for p in MODS.iterdir()
                   if p.is_dir() and (p / "data").is_dir() and p.name.lower() not in drop),
                  key=lambda p: p.name.lower())


def pick(*prefer, exclude=(), need="") -> Path:
    """The first preferred mod that is installed, else any other installed one.

    ``need`` is a path under the mod's ``data/`` the test cannot do without
    (``unit_models/battle_models.modeldb``, say); mods missing it are passed
    over. Exits the process with a SKIPPED line — and status 0 — when nothing
    qualifies, because "no mod to measure" is not a defect in the tool.
    """
    drop = {str(e).lower() for e in exclude} | {
        Path(str(e)).name.lower() for e in exclude}
    order = [MODS / p for p in prefer] + installed(exclude=drop)
    seen = set()
    for m in order:
        key = m.name.lower()
        if key in seen or key in drop:
            continue
        seen.add(key)
        if (m / "data").is_dir() and (not need or (m / "data" / need).exists()):
            return m
    want = " or ".join(prefer) or "any mod"
    print(f"SKIPPED — no installed mod to test against (wanted {want}"
          + (f" with data/{need}" if need else "") + f") under {MODS}")
    sys.exit(0)
