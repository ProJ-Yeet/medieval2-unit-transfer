"""Logging for the Unit Transfer server.

Writes to the console (when there is one) and always to a ``server.log``, so a
windowless launch still leaves a trail. Import ``log`` and use it directly.

Under ``pythonw`` there is no stdout at all, so the stream handler is only
attached when one actually exists — otherwise logging would raise.

The log normally lives in ``config/server.log`` next to the app. If that folder
can't be written — the app was unzipped somewhere read-only like Program Files,
or a synced/locked folder — it falls back to ``%LOCALAPPDATA%``. Silently having
no log at all is the worst possible outcome when someone reports "it just opens
and closes", so there is always somewhere to look; :func:`log_path` says where.
"""
from __future__ import annotations

import logging
import os
import sys
import tempfile
from pathlib import Path

from . import config

LOGGER_NAME = "unittransfer"
log = logging.getLogger(LOGGER_NAME)

_CONSOLE_FMT = "%(asctime)s  %(levelname)-7s %(message)s"
_FILE_FMT = "%(asctime)s  %(levelname)-7s %(message)s"

#: where the log actually ended up (set by setup(); None if even the fallbacks failed)
_log_path: Path | None = None


def log_path() -> Path | None:
    """The file the log is actually being written to, or None if none could be."""
    return _log_path


def _candidate_dirs():
    """Where to try putting the log, best first."""
    yield config.CONFIG_DIR
    local = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if local:
        yield Path(local) / "UnitTransfer"
    yield Path(tempfile.gettempdir()) / "UnitTransfer"


def setup(verbose: bool = False) -> logging.Logger:
    """Attach console + file handlers once. Safe to call repeatedly."""
    if getattr(log, "_ut_configured", False):
        return log
    log.setLevel(logging.DEBUG if verbose else logging.INFO)
    log.propagate = False

    stream = sys.stdout
    if stream is not None:                       # None under pythonw
        # The Windows console defaults to a legacy codepage, which turns every
        # non-ASCII character in a log line (paths, em-dashes, arrows) into "?".
        # Switch the console AND the stream to UTF-8; `errors="replace"` keeps a
        # stubborn terminal from raising mid-log.
        try:
            if sys.platform == "win32":
                import ctypes
                ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        except Exception:
            pass
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
        try:
            sh = logging.StreamHandler(stream)
            sh.setLevel(logging.DEBUG if verbose else logging.INFO)
            sh.setFormatter(logging.Formatter(_CONSOLE_FMT, datefmt="%H:%M:%S"))
            log.addHandler(sh)
        except Exception:
            pass

    global _log_path
    for d in _candidate_dirs():
        try:
            d.mkdir(parents=True, exist_ok=True)
            fh = logging.FileHandler(d / "server.log", encoding="utf-8")
            fh.setLevel(logging.DEBUG)           # the file keeps everything
            fh.setFormatter(logging.Formatter(_FILE_FMT, datefmt="%Y-%m-%d %H:%M:%S"))
            log.addHandler(fh)
            _log_path = d / "server.log"
            break
        except OSError:
            continue                             # try the next location
    if _log_path is None:
        log.warning("No writable location for server.log — this session is not "
                    "being logged to a file.")
    elif _log_path.parent != config.CONFIG_DIR:
        log.warning("config/ is not writable; logging to %s instead", _log_path)

    log._ut_configured = True                    # type: ignore[attr-defined]
    return log
