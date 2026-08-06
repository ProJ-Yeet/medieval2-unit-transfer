"""Clear the localisation cache M2TW rebuilds, after a job has edited a mod.

``data/text/export_units.txt.strings.bin`` is the compiled form of
``export_units.txt``. The game reads the .bin, not the .txt, and only recompiles
it when the .bin is missing — so until it is deleted a newly transferred or
renamed unit keeps showing the OLD name and description (or none at all).

Deleting it is the whole of the fix, and it is safe: the game writes it back on
the next launch. This is the batch line it replaces::

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
