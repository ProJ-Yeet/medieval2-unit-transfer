"""Persistent settings + transfer log for the Unit Transfer tool.

Everything is stored under the project's ``config/`` dir so nothing leaks into the
game folders:
  config/settings.json   -> {"med2_root": "...", "last_source": "...", "last_dest": "..."}
  config/transfers.json  -> list of transfer records (for the log + undo)

Backups for in-place transfers live under ``config/backups/<transfer_id>/``.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
BACKUP_DIR = CONFIG_DIR / "backups"
SETTINGS_PATH = CONFIG_DIR / "settings.json"
LOG_PATH = CONFIG_DIR / "transfers.json"


#: One writer at a time within this process — two threads racing on the same temp
#: name would have each other's bytes, which is the bug this is here to stop.
_WRITE_LOCK = threading.Lock()

#: How many times to retry the rename when Windows says the file is in use.
_REPLACE_TRIES = 8


#: path -> ((size, mtime_ns), the file's TEXT). :func:`get_med2_root` is called
#: on every mod the server resolves — that was a disk read per icon request — and
#: every one of those reads is also a file handle open on the very file a settings
#: save is trying to rename over. The stat is what tells us we can skip both.
#:
#: The text is cached rather than the parsed object on purpose: callers do
#: ``s = load_settings(); s.update(...)``, and handing out the cached dict would
#: let one of them edit everybody else's copy.
_JSON_CACHE: Dict[str, Any] = {}


def _stamp(path: Path):
    try:
        st = path.stat()
        return (st.st_size, st.st_mtime_ns)
    except OSError:
        return None


def _read_json(path: Path, default):
    """Read a config file, remembering its text until it changes on disk.

    Keyed by path and re-read whenever size or mtime moves, so a test that swaps
    :data:`SETTINGS_PATH` and a person editing the file by hand both still work.
    """
    key = str(path)
    stamp = _stamp(path)
    hit = _JSON_CACHE.get(key)
    body = hit[1] if hit is not None else None
    # GONE is not the same as BUSY, and the fallback below is only for busy. A
    # file that no longer exists really has no contents, and remembering the last
    # ones made a deleted settings file invisible for the rest of the run — the
    # tool went on reporting a MED2 root that had been removed. `os.replace` never
    # leaves the destination missing, so nothing legitimate lands here.
    if stamp is None and not path.exists():
        _JSON_CACHE.pop(key, None)
        return default
    if hit is None or hit[0] != stamp:
        try:
            body = path.read_text(encoding="utf-8")
        except OSError:
            # Windows makes the destination briefly unopenable while a writer's
            # os.replace goes through, and answering "there are no settings" for
            # those few microseconds is exactly the bug this file is fixing. What
            # we read last is far closer to the truth than an empty default.
            if body is None:
                return default
        else:
            _JSON_CACHE[key] = (stamp, body)
    try:
        return json.loads(body)
    except ValueError:
        return default


def _write_json(path: Path, obj) -> None:
    """Write a config file so a concurrent reader never sees a half-written one.

    ``Path.write_text`` truncates and then writes, and the server is threaded:
    while the page's ``POST /api/settings`` was inside that gap, any other
    request resolving a mod called :func:`get_med2_root` -> :func:`load_settings`,
    read a truncated file, got ``{}`` back and concluded the machine had no
    Medieval II install — so every mod vanished for that instant and the request
    404'd. It was invisible because the page's GET helper retries; the retry
    always landed after the write finished. Measured as a real 404 on
    ``/api/codeview`` the moment an editor saved the ``code_view`` toggle and
    opened a record in the same breath.

    A temp file plus ``os.replace`` closes it: the rename is atomic on Windows
    and POSIX alike, so a reader sees either the old file or the new one. It also
    means a crash mid-write can no longer lose the settings outright.

    The retry is Windows', not paranoia: ``os.replace`` there fails with a sharing
    violation if any reader has the destination open at that instant, which under
    a burst of icon requests happens often enough to measure. Losing the write
    would put the same bug back the other way round, so it waits and tries again.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(obj, indent=2, ensure_ascii=False)
    with _WRITE_LOCK:
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        try:
            tmp.write_text(body, encoding="utf-8")
            for attempt in range(_REPLACE_TRIES):
                try:
                    os.replace(tmp, path)
                except PermissionError:
                    if attempt == _REPLACE_TRIES - 1:
                        raise
                    time.sleep(0.01 * (attempt + 1))
                    continue
                # our own write is authoritative straight away, whatever the
                # filesystem's mtime resolution has to say about it
                _JSON_CACHE[str(path)] = (_stamp(path), body)
                return
        finally:
            try:
                tmp.unlink()
            except OSError:
                pass                  # the replace consumed it, which is the norm


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


def get_vanilla_ancillary_dir() -> Optional[Path]:
    """Folder holding the GAME's own ``ui/ancillaries`` pictures — or None.

    Not the same thing as :func:`get_vanilla_ui_root`, which holds *building*
    art (its manifest says so) and no ancillary pictures at all. Reading one as
    the other is why every ancillary reusing a stock picture was reported as a
    blank slot: the fallback it was checked against could never contain it.

    Vanilla ships these inside its ``.pack`` archives, so there is usually
    nothing on disk to point at and this answers None — which means "cannot be
    checked", not "the picture is missing". A user who unpacks the UI can set
    ``vanilla_ancillaries_dir`` and get the check back.
    """
    saved = load_settings().get("vanilla_ancillaries_dir")
    cands = [Path(saved)] if saved else []
    root = get_med2_root()
    if root:
        cands.append(Path(root) / "data" / "ui" / "ancillaries")
    for cand in cands:
        try:
            if cand.is_dir() and any(cand.iterdir()):
                return cand
        except OSError:
            continue
    return None


# ---- derived data (caches) ----------------------------------------------
#: Cached so the probe below runs once per launch, not once per icon.
_cache_dir: Optional[Path] = None


def _cache_candidates():
    """Where the decoded-icon cache may live, best first.

    Deliberately NOT next to the app. Unzipping the toolkit inside OneDrive or
    Dropbox puts a *synced* folder in the middle of every icon read, and a synced
    file can be dehydrated into a cloud placeholder: reading it then blocks on a
    download that can take seconds, or fails outright with ``OSError: [Errno 22]``.
    Measured on this machine — 400 cached icons took over two minutes to read back
    out of a OneDrive folder, with the server's own liveness heartbeat queued
    behind them. ``config/`` stays where it is because it is the user's own data
    and it is small; a cache is recomputable and has no reason to be synced.

    Same folder as the log's fallback, so the tool leaves one stray directory
    rather than two.
    """
    local = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME")
    if local:
        yield Path(local) / "UnitTransfer" / "cache"
    home = Path.home()
    if str(home) != ".":
        yield home / ".cache" / "unit-transfer"
    yield Path(tempfile.gettempdir()) / "UnitTransfer" / "cache"
    yield PROJECT_ROOT / ".cache"          # last resort: better than no cache


def cache_dir(sub: str = "") -> Path:
    """A writable folder for derived data, created. Falls back until one works."""
    global _cache_dir
    if _cache_dir is None:
        for cand in _cache_candidates():
            try:
                cand.mkdir(parents=True, exist_ok=True)
                probe = cand / ".writable"
                probe.write_bytes(b"1")
                probe.unlink()
                _cache_dir = cand
                break
            except OSError:
                continue
        else:
            _cache_dir = Path(tempfile.gettempdir())
    out = _cache_dir / sub if sub else _cache_dir
    try:
        out.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return out


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
