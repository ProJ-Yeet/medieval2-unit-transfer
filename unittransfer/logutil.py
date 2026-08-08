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

The file is the *diagnostic* copy and the console is the readable one. Everything
below DEBUG-level detail — the per-file trail, the mod fingerprints, the full
lists the console truncates — goes to the file only, because the whole point of
the file is that a user hits a problem, sends it, and it says what happened
without them having to reproduce anything. Helpers for writing that detail live
here so every mode records it the same way:

* :func:`banner` — one block per launch: version, Python, OS, where things are.
  Also the marker that separates one run from the previous one in an appended file.
* :func:`fingerprint` — what a mod looked like *before* it was touched: paths,
  sizes, mtimes, counts. Half of "what went wrong" is "which files were these".
* :func:`block` — a header plus an indented list, truncated on the console and
  written in full to the file.
* :func:`file_op` — one line per file written / backed up / copied / skipped.
  Called from every mode's write helper, so "what files got moved" is answerable
  from the log alone.

Because the file now carries real detail it is rotated rather than appended to
forever: a log a user cannot attach to a message is no better than no log.
"""
from __future__ import annotations

import logging
import os
import platform
import sys
import tempfile
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Iterable, Optional, Sequence

from . import config

LOGGER_NAME = "unittransfer"
log = logging.getLogger(LOGGER_NAME)

_CONSOLE_FMT = "%(asctime)s  %(levelname)-7s %(message)s"
_FILE_FMT = "%(asctime)s  %(levelname)-7s %(message)s"

#: Rotation. Four megabytes is many thousands of operations, and two backups mean
#: the run before last is still there when someone reports a problem a day late —
#: while the live file stays small enough to attach to a message.
MAX_BYTES = 4 * 1024 * 1024
BACKUP_COUNT = 2

#: How many items of a list the *console* shows before saying "… and N more".
#: The file always gets every one of them.
CONSOLE_LIST_LIMIT = 12

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
    # DEBUG always: the *handlers* decide what each destination sees, and the file
    # handler wants everything. Setting the logger itself to INFO would throw the
    # detail away before the file handler ever saw it.
    log.setLevel(logging.DEBUG)
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
            fh = RotatingFileHandler(d / "server.log", maxBytes=MAX_BYTES,
                                     backupCount=BACKUP_COUNT, encoding="utf-8")
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


# ---------------------------------------------------------------------------
# diagnostic detail
#
# Everything below exists for one reader: whoever is handed the log after
# something went wrong. It should be possible to say what the tool did, to which
# files, from the file alone.


def _fmt_size(n: int) -> str:
    """Byte counts a human can compare at a glance."""
    if n < 1024:
        return f"{n} B"
    for unit in ("KB", "MB", "GB"):
        n /= 1024.0
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}"
    return f"{n:.1f} GB"


def _stat_line(path: Path) -> str:
    """``"1.2 MB  2026-08-01 14:03"`` for a file, or why it isn't one.

    Size and mtime together are what identify a mod's file: two people running
    "the same mod" routinely have different EDUs, and that is exactly the kind of
    thing a bug report never mentions.
    """
    try:
        st = path.stat()
    except OSError as exc:
        return f"MISSING ({exc.__class__.__name__})"
    if not path.is_file():
        return "not a file"
    return (f"{_fmt_size(st.st_size)}  "
            f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(st.st_mtime))}")


def block(header: str, lines: Iterable[str], limit: int = CONSOLE_LIST_LIMIT,
          level: int = logging.INFO) -> None:
    """A header line, then ``lines`` indented under it.

    The console stops after ``limit`` items and says how many it swallowed; the
    file always gets the whole list. A long list is noise on screen and evidence
    in a log, so it goes to both at the level each one wants rather than being
    cut short for everybody.
    """
    items = [str(x) for x in lines]
    log.log(level, "%s", header)
    if not items:
        return
    for i, item in enumerate(items):
        # past the console's patience the line still has to reach the file, and
        # DEBUG is what the console filters and the file keeps
        log.log(level if i < limit else logging.DEBUG, "     %s", item)
    if len(items) > limit:
        log.log(level, "     … and %d more (all of them are in %s)",
                len(items) - limit, _log_path.name if _log_path else "the log file")


def banner(port: Optional[int] = None) -> None:
    """One block per launch: which build this is and where it is running.

    First thing in the file for a reason — an appended log needs a visible seam
    between runs, and every question about a bug report starts with "which
    version, on what". ``frozen`` matters because the packaged build and a source
    checkout resolve ``config/`` differently.
    """
    from . import __version__
    log.info("=" * 78)
    log.info("Unit Transfer %s — session started %s", __version__,
             time.strftime("%Y-%m-%d %H:%M:%S"))
    log.info("=" * 78)
    rows = [
        f"version      {__version__}",
        f"python       {platform.python_version()} ({platform.architecture()[0]}) "
        f"— {sys.executable}",
        f"os           {platform.platform()}",
        f"frozen       {'yes (packaged build)' if getattr(sys, 'frozen', False) else 'no (running from source)'}",
        f"app folder   {config.PROJECT_ROOT}",
        f"config       {config.CONFIG_DIR}",
        f"log file     {_log_path or '(none — not writable)'}",
        f"backups      {config.BACKUP_DIR}",
        f"med2 root    {config.get_med2_root() or '(not set)'}",
        f"cwd          {Path.cwd()}",
    ]
    if port is not None:
        rows.append(f"port         {port}")
    block("Environment:", rows)


def fingerprint(mod) -> None:
    """What a mod looked like before we touched it: paths, sizes, counts.

    Logged once per mod per session (the flag lives on the Mod, so a re-parse
    after a write logs it again — which is the point: the second fingerprint is
    the "after" picture).

    Nothing here is allowed to *do* work. ``Mod``'s interesting attributes are
    ``cached_property``, and ``lua_files`` in particular is a walk of the entire
    mod folder — reading it to write a log line would put a tree walk in front of
    every transfer. So the cached values are reported when some real job has
    already paid for them and skipped otherwise; the rest is file metadata, which
    is a handful of stats.
    """
    if getattr(mod, "_ut_fingerprinted", False):
        return
    try:
        mod._ut_fingerprinted = True
    except Exception:
        pass                                     # not our object — log it anyway

    def cached(attr: str):
        """The value only if it is already computed — never triggers the property."""
        return getattr(mod, "__dict__", {}).get(attr)

    try:
        rows = [
            f"root         {mod.root}",
            f"data         {mod.data}",
            f"EDU          {_stat_line(mod.edu_path)}",
            f"modeldb      {_stat_line(mod.modeldb_path)}",
            f"export_units {_stat_line(mod.export_units_path)}",
            f"descr_mount  {_stat_line(mod.descr_mount_path)}",
        ]
        eop_dirs = cached("eop_dirs")
        rows.append("EOP folders  " + (
            "(not looked up yet)" if eop_dirs is None
            else ", ".join(str(p) for p in eop_dirs) or "(none found)"))
        lua = cached("lua_files")
        rows.append("lua scripts  " + (
            "(not scanned yet — only the modeldb cleanup needs them)"
            if lua is None else str(len(lua))))
        edu = cached("edu")
        if edu is not None:
            rows.append(f"units        {len(edu.units)} "
                        f"({len(getattr(edu, 'eop_units', []) or [])} M2TWEOP)")
        db = cached("modeldb")
        if db is not None:
            rows.append(f"bmdb entries {len(db.entries)}")
        block(f"Mod '{mod.name}':", rows)
    except Exception:                            # a fingerprint must never break a job
        log.debug("could not fingerprint %r", getattr(mod, "name", mod), exc_info=True)


def file_op(verb: str, path, note: str = "", size: Optional[int] = None) -> None:
    """One line per file the tool touched. DEBUG: the file keeps it, the console doesn't.

    ``verb`` is a fixed-width tag so the trail can be read as a column and
    grepped: WRITE / BACKUP / COPY / DELETE / SAME / KEEP / EXPORT. This is the
    answer to "what files got moved", so it is emitted from inside the write
    helpers rather than alongside them — a path that never reaches a helper never
    reaches the disk either, and the two cannot drift apart.
    """
    p = Path(path)
    if size is None:
        try:
            size = p.stat().st_size if p.is_file() else None
        except OSError:
            size = None
    tail = f"  ({_fmt_size(size)})" if size is not None else ""
    log.debug("  %-6s %s%s%s", verb, p, tail, f"  — {note}" if note else "")


def counted(manifest: dict, extra: Sequence[str] = ()) -> None:
    """The per-file totals of a finished job, then the full lists in the file.

    The record in ``transfers.json`` already holds the manifest, but that file is
    machine-shaped and lives somewhere else; the point here is that the one file
    a user sends already answers what changed on disk.
    """
    order = ("created", "backed_up", "kept_existing", "deleted",
             "ext_created", "ext_backed_up")
    label = {"created": "created", "backed_up": "modified (backed up first)",
             "kept_existing": "left alone (destination's copy kept)",
             "deleted": "deleted (restorable with Undo)",
             "ext_created": "created outside data/ (M2TWEOP)",
             "ext_backed_up": "modified outside data/ (M2TWEOP)"}
    totals = []
    for key in order:
        items = manifest.get(key) or []
        if items:
            totals.append(f"{len(items)} {label[key]}")
    log.info("  files: %s", ", ".join(totals) if totals else "none changed")
    for line in extra:
        log.info("  %s", line)
    for key in order:
        items = manifest.get(key) or []
        if not items:
            continue
        log.debug("  %s:", label[key])
        for item in items:
            # ext_* entries are dicts holding the file and its backup
            if isinstance(item, dict):
                log.debug("     %s  (backup: %s)", item.get("path"), item.get("backup"))
            else:
                log.debug("     %s", item)


def tail(max_bytes: int = 512 * 1024) -> str:
    """The end of the log file, for the UI's "show me the log" button.

    Bounded because the whole point is to hand it to somebody: the last chunk
    holds the session that went wrong, and the rotated files are still on disk if
    more is needed.
    """
    if _log_path is None or not _log_path.is_file():
        return ""
    try:
        size = _log_path.stat().st_size
        with _log_path.open("rb") as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
                fh.readline()                    # drop the half line we landed in
            return fh.read().decode("utf-8", errors="replace")
    except OSError as exc:
        return f"(could not read {_log_path}: {exc})"
