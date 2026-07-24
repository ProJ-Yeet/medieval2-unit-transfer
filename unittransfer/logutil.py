"""Logging for the Unit Transfer server.

Writes to the console (when there is one) and always to ``config/server.log``,
so a windowless launch still leaves a trail. Import ``log`` and use it directly.

Under ``pythonw`` there is no stdout at all, so the stream handler is only
attached when one actually exists — otherwise logging would raise.
"""
from __future__ import annotations

import logging
import sys

from . import config

LOGGER_NAME = "unittransfer"
log = logging.getLogger(LOGGER_NAME)

_CONSOLE_FMT = "%(asctime)s  %(levelname)-7s %(message)s"
_FILE_FMT = "%(asctime)s  %(levelname)-7s %(message)s"


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

    try:
        config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(config.CONFIG_DIR / "server.log", encoding="utf-8")
        fh.setLevel(logging.DEBUG)               # the file keeps everything
        fh.setFormatter(logging.Formatter(_FILE_FMT, datefmt="%Y-%m-%d %H:%M:%S"))
        log.addHandler(fh)
    except OSError:
        pass

    log._ut_configured = True                    # type: ignore[attr-defined]
    return log
