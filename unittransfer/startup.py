"""Startup preflight, icon prewarming, and the two-process launch.

The launcher always gives the tool a real console so a failed start is *readable*
instead of a window that flashes and vanishes. This module provides the pieces
that behaviour needs:

  * :func:`preflight` — check everything that can stop the tool booting and report
    each result as a line, so the console says *why* it failed.
  * :func:`prewarm_icons` — decode a mod's unit cards up front with a progress
    line, because a cold cache means hundreds of TGA→PNG conversions and the grid
    otherwise sits there looking broken.
  * :func:`spawn_server` / :func:`follow_until_ready` — run the server as a
    detached child and mirror its log into the console until it reports ready, so
    the console can simply *exit* once startup is done.

Why a detached child rather than hiding our own window: on Windows Terminal (the
default console host since Win11) ``ShowWindow(GetConsoleWindow(), SW_HIDE)`` is a
no-op — the visible window belongs to WindowsTerminal.exe, not to us. Ending the
console *process* is the only thing that reliably closes the window, so the
server has to be a separate process that outlives it.

With "Show console window" ON the server instead runs in the foreground of that
console, so its output keeps streaming and Ctrl+C still stops it.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from . import config
from .logutil import log

MIN_PYTHON = (3, 9)

#: logged by the server once it is listening, the tab is open and the icons are
#: warm — the launcher waits for this line, then closes the console.
READY_MARKER = "STARTUP-COMPLETE"
#: logged when the server came up fine but no browser could be opened. The
#: launcher must then KEEP its window, because auto-closing it would leave the
#: user with no window and no tab — indistinguishable from "nothing happened".
BROWSER_FAILED_MARKER = "BROWSER-NOT-OPENED"


# --------------------------------------------------------------------------
class Check:
    """One preflight result. ``fatal`` means the tool cannot run."""

    def __init__(self, name: str, ok: bool, detail: str = "", fatal: bool = False):
        self.name, self.ok, self.detail, self.fatal = name, ok, detail, fatal

    @property
    def blocking(self) -> bool:
        return self.fatal and not self.ok

    def line(self) -> str:
        mark = "ok  " if self.ok else ("FAIL" if self.fatal else "warn")
        return f"  [{mark}] {self.name}" + (f" — {self.detail}" if self.detail else "")


def _port_state(port: int, host: str = "127.0.0.1") -> Tuple[bool, str]:
    """(free, detail). A port held by OUR server is reported as such."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        if s.connect_ex((host, port)) != 0:
            return True, "free"
    # something is listening — is it us?
    import json
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/ping", timeout=2) as r:
            info = json.loads(r.read().decode("utf-8"))
        if info.get("app") == "unit-transfer":
            return False, f"already running (pid {info.get('pid')}) — its window will be reopened"
    except Exception:
        pass
    return False, "in use by another program — relaunch with --port 8757"


def preflight(port: int, web_dir: Path) -> List[Check]:
    """Everything that can stop the tool booting, each as a reportable line."""
    checks: List[Check] = []

    v = sys.version_info
    checks.append(Check(
        f"Python {v.major}.{v.minor}.{v.micro}", v[:2] >= MIN_PYTHON,
        "" if v[:2] >= MIN_PYTHON else f"need {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer",
        fatal=True))

    try:
        import PIL                                        # noqa: F401
        from PIL import Image                             # noqa: F401
        checks.append(Check("Pillow (unit icons)", True, f"version {PIL.__version__}"))
    except Exception as exc:                              # noqa: BLE001
        checks.append(Check("Pillow (unit icons)", False,
                            f"not importable ({exc}) — run: pip install pillow", fatal=True))

    idx = web_dir / "index.html"
    checks.append(Check("web/index.html", idx.is_file(),
                        str(idx) if not idx.is_file() else "", fatal=True))

    try:
        config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        probe = config.CONFIG_DIR / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        checks.append(Check("config/ writable", True, str(config.CONFIG_DIR)))
    except OSError as exc:
        checks.append(Check("config/ writable", False,
                            f"{config.CONFIG_DIR}: {exc}", fatal=True))

    root = config.get_med2_root()
    if not root:
        checks.append(Check("MED2 root", False, "not set yet — choose it in the UI (⚙)"))
    else:
        rp = Path(root)
        mods = rp / "mods" if (rp / "mods").is_dir() else rp
        if not rp.exists():
            checks.append(Check("MED2 root", False, f"{rp} no longer exists — reset it in the UI (⚙)"))
        else:
            found = sorted(c.name for c in mods.iterdir()
                           if c.is_dir() and (c / "data").is_dir()) if mods.is_dir() else []
            checks.append(Check(
                "MED2 root", bool(found),
                f"{mods} — {len(found)} mod(s): {', '.join(found)}" if found
                else f"{mods} has no folders with a data/ subfolder"))

    free, detail = _port_state(port)
    # A port held by ANOTHER program is fatal — nothing downstream can recover.
    # A port held by our own server is not: that path reopens the running window.
    ours = "already running" in detail
    checks.append(Check(f"port {port}", free, detail, fatal=not ours))
    return checks


def report(checks: List[Check]) -> bool:
    """Log every check; return True when nothing fatal failed."""
    log.info("Startup checks:")
    for c in checks:
        (log.info if c.ok else (log.error if c.fatal else log.warning))("%s", c.line())
    bad = [c for c in checks if c.blocking]
    if bad:
        log.error("")
        log.error("STARTUP FAILED — %d check(s) did not pass:", len(bad))
        for c in bad:
            log.error("   * %s%s", c.name, f": {c.detail}" if c.detail else "")
        log.error("Full log: %s", config.CONFIG_DIR / "server.log")
        return False
    return True


# --------------------------------------------------------------------------
def prewarm_icons(registry, mod_names: List[str], every: float = 0.5,
                  should_stop: Optional[Callable[[], bool]] = None) -> int:
    """Decode the unit CARDS of ``mod_names`` to PNG, logging progress.

    A cold icon cache means one TGA→PNG conversion per unit (hundreds per mod),
    which is the slowest part of a first run. Doing it up front — with a progress
    line at most every ``every`` seconds — means the console reports what the tool
    is busy with while the grid fills in. Cached icons are near-free, so a warm
    start passes through in a moment.

    Only the grid's card icons are warmed; the larger info cards are rare enough
    per view that converting them lazily is cheaper than doubling this pass.
    ``should_stop`` lets a shutdown cut the work short. Returns the number
    actually converted.
    """
    converted = 0
    for name in mod_names:
        if not name or (should_stop and should_stop()):
            continue
        try:
            mod = registry.get(name)
        except Exception as exc:                          # noqa: BLE001
            log.warning("icons: skipping %r (%s)", name, exc)
            continue
        units = mod.edu.units
        total = len(units)
        log.info("icons: converting unit cards for %s (%d units)…", name, total)
        hits = misses = 0
        last = time.monotonic()
        started = last
        for i, u in enumerate(units, 1):
            if should_stop and should_stop():
                log.info("icons: %s stopped at %d/%d (shutting down)", name, i, total)
                return converted
            src = mod.find_unit_card(u)
            if src is not None:
                # a cached icon is a file-exists check; a new one is a decode
                if registry.icons.is_cached(src):
                    hits += 1
                else:
                    registry.icons.png_bytes(src)
                    misses += 1
                    converted += 1
            now = time.monotonic()
            if now - last >= every or i == total:
                last = now
                log.info("icons: %s  %d/%d (%d%%) — %d converted, %d already cached",
                         name, i, total, i * 100 // max(total, 1), misses, hits)
        log.info("icons: %s done — %d converted, %d cached, %.1fs",
                 name, misses, hits, time.monotonic() - started)
    return converted


# --------------------------------------------------------------------------
def server_log_path() -> Path:
    """Where the log is actually being written (may not be config/ — see logutil)."""
    from .logutil import log_path
    return log_path() or (config.CONFIG_DIR / "server.log")


def _pythonw() -> str:
    """The windowless interpreter, so the detached server has no console at all.

    Falls back to the current interpreter when ``pythonw.exe`` isn't beside it
    (the server then keeps an invisible console of its own, which is harmless).
    """
    exe = Path(sys.executable)
    if os.name == "nt":
        cand = exe.with_name(exe.name.replace("python", "pythonw"))
        if cand.name != exe.name and cand.exists():
            return str(cand)
    return str(exe)


def spawn_server(app_path: Path, args: List[str]) -> subprocess.Popen:
    """Start the server as a DETACHED child that outlives this console."""
    flags = 0
    if os.name == "nt":
        flags = (getattr(subprocess, "DETACHED_PROCESS", 0)
                 | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    return subprocess.Popen(
        [_pythonw(), str(app_path), "--serve", *args],
        cwd=str(app_path.parent), creationflags=flags, close_fds=True,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def follow_until_ready(proc: subprocess.Popen, offset: int,
                       timeout: float = 300.0) -> Tuple[bool, str, bool]:
    """Mirror the server's log to this console until it reports ready.

    ``offset`` is the size of ``server.log`` at spawn time, so only the child's
    lines are echoed (not the launcher's own preflight, already on screen).

    Returns (ok, reason, browser_ok). ok=False means the child died or timed out.
    browser_ok=False means the server is fine but nothing opened on screen, which
    the caller must treat as "keep this window" — otherwise the user is left with
    no console and no tab and no idea the tool is running.
    """
    path = server_log_path()
    deadline = time.monotonic() + timeout
    pos = offset
    pending = ""
    browser_ok = True

    def emit(line: str) -> None:
        nonlocal browser_ok
        if line.strip():
            print(line, flush=True)
        if BROWSER_FAILED_MARKER in line:
            browser_ok = False

    while True:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                fh.seek(pos)
                chunk = fh.read()
                pos = fh.tell()
        except OSError:
            chunk = ""
        if chunk:
            pending += chunk
            *lines, pending = pending.split("\n")
            for line in lines:
                emit(line)
                if READY_MARKER in line:
                    return True, "ready", browser_ok
        rc = proc.poll()
        if rc is not None:
            time.sleep(0.3)                    # let the last lines land
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    fh.seek(pos)
                    for line in fh.read().splitlines():
                        emit(line)
            except OSError:
                pass
            return (rc == 0), f"server exited with code {rc}", browser_ok
        if time.monotonic() > deadline:
            return False, f"server did not report ready within {timeout:.0f}s", browser_ok
        time.sleep(0.15)
