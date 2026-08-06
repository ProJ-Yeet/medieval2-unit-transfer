"""Persistent settings + transfer log for the Unit Transfer tool.

Everything is stored under the project's ``config/`` dir so nothing leaks into the
game folders:
  config/settings.json   -> {"med2_root": "...", "last_source": "...", "last_dest": "..."}
  config/transfers.json  -> list of transfer records (for the log + undo)

Backups for in-place transfers live under ``config/backups/<transfer_id>/``.
"""
from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
BACKUP_DIR = CONFIG_DIR / "backups"
SETTINGS_PATH = CONFIG_DIR / "settings.json"
LOG_PATH = CONFIG_DIR / "transfers.json"


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


# ---- settings -----------------------------------------------------------
def load_settings() -> Dict[str, Any]:
    return _read_json(SETTINGS_PATH, {})


def save_settings(**kw) -> Dict[str, Any]:
    s = load_settings()
    s.update({k: v for k, v in kw.items() if v is not None})
    _write_json(SETTINGS_PATH, s)
    return s


def detect_med2_root() -> Optional[str]:
    """Look up the install path from the registry, same key + value the game's own
    installers write (`med2_mod_installer.iss` reads it as ``AppPath`` under
    ``SOFTWARE\\SEGA\\Medieval II Total War``). A 32-bit installer's writes land in
    the WOW6432Node view on 64-bit Windows, so both views are tried explicitly
    rather than relying on this process's own bitness.
    """
    if sys.platform != "win32":
        return None
    import winreg
    key_path = r"SOFTWARE\SEGA\Medieval II Total War"
    for flags in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY, 0):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path, 0,
                                 winreg.KEY_READ | flags) as key:
                value, _ = winreg.QueryValueEx(key, "AppPath")
        except OSError:
            continue
        if value and Path(value).is_dir():
            return value
    return None


def get_med2_root() -> Optional[str]:
    """The saved root, falling back to a registry-detected install when unset."""
    return load_settings().get("med2_root") or detect_med2_root()


#: Where vanilla building art is looked for when the user hasn't pointed
#: elsewhere, best first: the packed form this repo ships (~45 MB of deduplicated
#: lossless WebP, see ``tools/pack_vanilla_ui.py``), then a raw folder someone
#: unpacked themselves (~305 MB of TGA, never committed).
VANILLA_UI_DIRS = (PROJECT_ROOT / "vanilla_ui", PROJECT_ROOT / "unpackaded_vanilla_ui")


def get_vanilla_ui_root() -> Optional[Path]:
    """Folder holding vanilla building art, packed or raw — or None.

    Mods ship only the building icons they changed and let the game fall back to
    the vanilla ones, so without this the browser would show a placeholder for
    most of a mod's buildings. Optional: absent just means more placeholders.
    """
    saved = load_settings().get("vanilla_ui_root")
    cands = ((Path(saved),) if saved else ()) + VANILLA_UI_DIRS
    for cand in cands:
        if cand.is_dir():
            return cand
    return None


# ---- transfer log -------------------------------------------------------
def load_log() -> List[Dict[str, Any]]:
    return _read_json(LOG_PATH, [])


def save_log(entries: List[Dict[str, Any]]) -> None:
    _write_json(LOG_PATH, entries)


def append_log(record: Dict[str, Any]) -> None:
    entries = load_log()
    entries.append(record)
    save_log(entries)


def update_log(transfer_id: str, **changes) -> None:
    entries = load_log()
    for e in entries:
        if e.get("id") == transfer_id:
            e.update(changes)
            break
    save_log(entries)


def new_transfer_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


def backup_root_for(transfer_id: str) -> Path:
    return BACKUP_DIR / transfer_id
