"""Run the mod's "Full Cleaner.bat" inside a destination mod after a transfer.

M2TW caches several of the files a transfer edits — most importantly
``data/text/export_units.txt.strings.bin``, the compiled form of the localisation
file. Until that cache is deleted the game keeps showing the OLD text, so a newly
transferred unit shows no name/description. The cleaner script removes those
regenerated files (it recreates them on next launch).

The script uses ``pushd "%~dp0"`` and relative ``data\\...`` paths, so it has to
live in — and run from — the mod's own root folder. We copy it there on demand.

NOTE: the script ends with ``pause``; it is run with stdin at EOF so that returns
immediately instead of hanging forever.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLEANER_NAME = "Full Cleaner.bat"
TIMEOUT_S = 300


def cleaner_source() -> Path:
    return PROJECT_ROOT / CLEANER_NAME


def run_full_cleaner(mod_root: str | Path) -> Dict:
    """Copy the cleaner into ``mod_root`` (if absent) and run it there.

    Returns a small record describing what happened; never raises.
    """
    result: Dict = {"ran": False, "copied": False, "cleaner": CLEANER_NAME}
    src = cleaner_source()
    if not src.exists():
        result["error"] = f"{CLEANER_NAME} not found in {PROJECT_ROOT}"
        return result

    root = Path(mod_root)
    if not root.is_dir():
        result["error"] = f"mod folder not found: {root}"
        return result

    target = root / CLEANER_NAME
    try:
        if not target.exists():
            shutil.copy2(src, target)
            result["copied"] = True
    except OSError as e:
        result["error"] = f"could not copy cleaner: {e}"
        return result
    result["path"] = str(target)

    if os.name != "nt":
        result["error"] = "not Windows — cleaner not executed"
        return result

    try:
        proc = subprocess.run(
            ["cmd", "/c", str(target)],
            cwd=str(root),
            stdin=subprocess.DEVNULL,      # so the script's trailing `pause` returns
            capture_output=True, text=True, timeout=TIMEOUT_S,
        )
        result["ran"] = True
        result["returncode"] = proc.returncode
        out = (proc.stdout or "") + (proc.stderr or "")
        result["output"] = out.strip()[-1500:]
    except subprocess.TimeoutExpired:
        result["error"] = f"cleaner timed out after {TIMEOUT_S}s"
    except Exception as e:                  # never let this break a transfer
        result["error"] = f"{type(e).__name__}: {e}"
    return result
