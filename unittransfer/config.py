"""Persistent settings + transfer log for the Unit Transfer tool.

Everything is stored under the project's ``config/`` dir so nothing leaks into the
game folders:
  config/settings.json   -> {"med2_root": "...", "last_source": "...", "last_dest": "..."}
  config/transfers.json  -> list of transfer records (for the log + undo)

Backups for in-place transfers live under ``config/backups/<transfer_id>/``.
"""
from __future__ import annotations

import json
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


def get_med2_root() -> Optional[str]:
    return load_settings().get("med2_root")


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
