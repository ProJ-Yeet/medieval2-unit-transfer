"""Keep the localisation cache M2TW reads in step, after a job has edited a mod.

``data/text/export_units.txt.strings.bin`` is the compiled form of
``export_units.txt``. The game reads the .bin, not the .txt, and only recompiles
it when the .bin is missing — so until it is deleted a newly transferred or
renamed unit keeps showing the OLD name and description (or none at all).

Deleting it was the whole of the fix for a long time, and it is safe: the game
writes it back on the next launch. Since :mod:`unittransfer.stringsbin` can write
the format, :func:`refresh_strings_bin` does better — it recompiles the cache
from the ``.txt`` the job just wrote, so nothing is thrown away and the game has
nothing to rebuild. Deleting stays as the fallback for when there is no ``.txt``
to compile from. This is the batch line the original replaced::

    if exist data\\text\\export_units.txt.strings.bin del /F/s/q data\\text\\export_units.txt.strings.bin

This used to run the mod's "Full Cleaner.bat" instead. That script deletes far
more than caches — the whole of ``data/terrain/aerial_map/sea`` (the campaign
map's water art, i.e. its rivers), several historical battle maps and
``data/scripts/show_me`` — none of which the game regenerates and none of which
was in a backup manifest, so Undo could not bring it back. The one file above is
the only one a unit edit actually needs gone. "Full Cleaner.bat" still ships in
the app folder for anyone who wants to run it by hand.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict

#: relative to the mod root — the only file this module ever removes
STRINGS_BIN_REL = "data/text/export_units.txt.strings.bin"

#: same story for building names, which live in their own text file and so have
#: their own compiled cache — a renamed building keeps its old name until it goes
BUILDINGS_STRINGS_BIN_REL = "data/text/export_buildings.txt.strings.bin"


def strings_bin_path(mod_root: str | Path,
                     rel: str = STRINGS_BIN_REL) -> Path:
    return Path(mod_root) / rel


def refresh_strings_bin(mod_root: str | Path,
                        rel: str = STRINGS_BIN_REL) -> Dict:
    """Bring one compiled cache back in step with the ``.txt`` we just wrote.

    Preferred over :func:`clear_strings_bin` now that
    :mod:`unittransfer.stringsbin` can write the format: recompiling keeps the
    file the game actually reads, so an edit shows up in game without the mod
    losing a cache the next launch then has to rebuild — a visible pause on a big
    mod, and an outright loss on one whose ``.txt`` has since gone missing.

    Falls back to deleting when there is nothing to compile from, or when the
    compile fails: a lost cache is recoverable, a wrong one is not.
    """
    from . import stringsbin
    root = Path(mod_root)
    if not root.is_dir():
        return {"ran": False, "file": rel, "deleted": False, "rebuilt": False,
                "error": f"mod folder not found: {root}"}
    target = strings_bin_path(root, rel)
    txt = stringsbin.txt_path_for(target)
    if txt.exists():
        res = stringsbin.refresh_from_txt(txt)
        if res.get("rebuilt"):
            return {"ran": True, "file": rel, "path": str(target), "deleted": False,
                    "rebuilt": True, "entries": res.get("entries", 0)}
        why = res.get("error", "")
    else:
        why = f"no {txt.name} to compile from"
    out = clear_strings_bin(root, rel)
    out["rebuilt"] = False
    out["rebuild_error"] = why
    return out


def clear_strings_bin(mod_root: str | Path, rel: str = STRINGS_BIN_REL) -> Dict:
    """Delete one compiled ``*.txt.strings.bin``, if it is there.

    Returns a small record describing what happened; never raises — a failure to
    clear a cache must not turn a completed transfer into an error.
    """
    result: Dict = {"ran": True, "file": rel, "deleted": False}
    root = Path(mod_root)
    if not root.is_dir():
        return {**result, "ran": False, "error": f"mod folder not found: {root}"}

    target = strings_bin_path(root, rel)
    result["path"] = str(target)
    if not target.exists():
        # nothing to do: the game has not compiled one since the last clear
        result["missing"] = True
        return result

    try:
        target.unlink()
        result["deleted"] = True
    except OSError as e:
        # most often the game is running and holding the file open
        result["ran"] = False
        result["error"] = f"could not delete {rel}: {e}"
    return result
