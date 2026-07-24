"""Unit Transfer — launch the local web UI.

Usage:
  python app.py                 # use the remembered MED2 root (choose it in the UI if unset)
  python app.py <med2_root>     # set/point to the Medieval II install root (has a 'mods' folder)
  python app.py --port 9000
  python app.py --check         # run the startup checks and exit (no server)
  python app.py --serve         # run the server in THIS process (no launcher wrapper)

Startup, as the launcher does it:

  1. A console always opens, so a failed start is readable instead of a window
     that flashes and vanishes.
  2. The preflight checks run and print — Python, Pillow, web/, config/, the MED2
     root, the port. Anything fatal stops here with the reason on screen, and the
     launcher holds the window open.
  3. "Show console window" ON  -> the server runs right here: output keeps
     streaming and Ctrl+C stops it.
     "Show console window" OFF -> the server is started as a DETACHED child and
     this console mirrors its log (port, browser, TGA→PNG icon progress) until it
     reports ready, then exits and the window closes. The server keeps running;
     stop it with Quit in the UI.

The browser tab opens in the system DEFAULT browser — whatever Windows has
registered. The tool never picks a specific one.
"""
from __future__ import annotations

import sys
import threading
import traceback
import webbrowser
from pathlib import Path

from unittransfer import config, startup
from unittransfer.logutil import setup as setup_logging
from unittransfer.server import WEB_DIR, Handler, serve

APP_PATH = Path(__file__).resolve()
CACHE_DIR = APP_PATH.parent / ".cache" / "icons"


def _parse(argv):
    port, root, verbose, mode = 8756, None, False, "launch"
    passthrough = []
    it = iter(argv)
    for a in it:
        if a in ("--port", "-p"):
            port = int(next(it))
            passthrough += ["--port", str(port)]
        elif a in ("--verbose", "-v"):
            verbose = True          # also log every HTTP request
            passthrough.append(a)
        elif a in ("--check", "--startup-check"):
            mode = "check"
        elif a == "--serve":
            mode = "serve"          # internal: the detached child, or a manual run
        else:
            root = a
            passthrough.append(a)
    return port, root, verbose, mode, passthrough


def main(argv):
    port, root, verbose, mode, passthrough = _parse(argv)

    if root:
        config.save_settings(med2_root=str(Path(root)))

    # Logs go to the console (when there is one) and always to config/server.log,
    # so the detached server still leaves a full trail.
    log = setup_logging(verbose)
    log.info("Unit Transfer %s — %s", mode, APP_PATH.parent)

    # ---- preflight: say WHY a launch fails instead of dying silently ----
    checks = startup.preflight(port, WEB_DIR)
    if not startup.report(checks):
        if mode == "serve":
            # detached: no console of ours to read, so put it on screen
            _alert("Unit Transfer could not start.\n\n"
                   + "\n".join(f"• {c.name}: {c.detail}" for c in checks if c.blocking)
                   + f"\n\nDetails: {startup.server_log_path()}")
        return 1
    if mode == "check":
        log.info("Startup checks passed (--check: not starting the server).")
        return 0

    # Already running on this port? Just show that window — don't start a second
    # server only to have it fail to bind.
    if mode != "serve" and _already_ours(port):
        log.info("Unit Transfer is already running on port %d — opening that "
                 "window instead of starting a second one.", port)
        _open_browser(log, port)
        return 0

    keep_console = bool(config.load_settings().get("show_console", False))
    if mode == "launch" and not keep_console:
        return _launch_detached(log, port, passthrough)
    return _run_server(log, port, verbose, keep_console)


def _launch_detached(log, port: int, passthrough) -> int:
    """Start the server as a child, mirror its startup, then close this console."""
    log.info("Starting the server (detached) — this window closes once it's up.")
    log.info("Turn on Settings → Show console window to keep it open instead.")
    # Take the offset AFTER our own lines are written: launcher and server share
    # server.log, and mirroring from an earlier point would echo them back.
    try:
        offset = startup.server_log_path().stat().st_size
    except OSError:
        offset = 0
    try:
        proc = startup.spawn_server(APP_PATH, passthrough)
    except OSError as exc:
        log.error("Could not start the server process: %s", exc)
        return 1
    ok, reason = startup.follow_until_ready(proc, offset)
    if not ok:
        log.error("STARTUP FAILED — %s", reason)
        log.error("Full log: %s", startup.server_log_path())
        return 1
    log.info("Server is up on port %d. Stop it with Quit in the UI.", port)
    return 0


def _run_server(log, port: int, verbose: bool, keep_console: bool) -> int:
    """Actually serve. Used by the detached child and by --serve / show-console."""
    settings = config.load_settings()
    stopping = threading.Event()

    def open_browser():
        _open_browser(log, port)

    def on_ready():
        """Listening: open the tab now, then warm the icons behind it.

        The tab comes first so the UI is usable immediately — a cold cache for a
        big mod is ~30s of conversions and the grid fills in as they land. The
        console mirrors that progress; only when it finishes do we declare
        startup complete (which is what lets the launcher window close).
        """
        open_browser()

        def work():
            try:
                names = [n for n in (settings.get("last_source"),
                                     settings.get("last_dest")) if n]
                if names:
                    startup.prewarm_icons(Handler.registry, names,
                                          should_stop=stopping.is_set)
                else:
                    log.info("icons: no remembered mods yet — they'll convert as you "
                             "pick a source and destination.")
            except Exception:
                log.warning("icon prewarm failed (continuing)", exc_info=True)
            if stopping.is_set():
                return
            log.info("%s — server ready on port %d.%s", startup.READY_MARKER, port,
                     "  Ctrl+C here, or Quit in the UI, to stop."
                     if keep_console else "  Stop it with Quit in the UI.")
        threading.Thread(target=work, name="icon-prewarm", daemon=True).start()

    try:
        try:
            serve(CACHE_DIR, port=port, on_ready=on_ready, verbose=verbose)
        finally:
            stopping.set()          # stop the prewarm logging past shutdown
    except OSError as e:
        # Almost always "address already in use" (the preflight usually catches it
        # first, but a race is possible). If the port is OUR server, just show it.
        log.error("Could not start on port %d: %s", port, e)
        if _already_ours(port):
            log.info("Unit Transfer is already running on port %d — "
                     "opening that window instead.", port)
            open_browser()
            log.info("%s — reused the running instance.", startup.READY_MARKER)
            return 0
        _alert(f"Unit Transfer could not start on port {port}.\n\n{e}\n\n"
               f"Something else is using that port. Launch with --port 8757 "
               f"to pick another one.\n\nDetails: {startup.server_log_path()}")
        return 1
    except Exception:
        log.error("Unit Transfer crashed:\n%s", traceback.format_exc())
        _alert(f"Unit Transfer crashed.\n\nSee {startup.server_log_path()} "
               "for the traceback.")
        return 1
    return 0


def _open_browser(log, port: int) -> None:
    """Open the UI in the system DEFAULT browser.

    ``webbrowser.open()`` hands the URL to whatever Windows has registered
    (Brave, Edge, Firefox...). The tool never picks a specific browser.
    """
    url = f"http://127.0.0.1:{port}/"
    log.info("Opening %s in your default browser…", url)
    try:
        if not webbrowser.open(url):
            log.warning("Could not launch a browser — open %s yourself.", url)
    except Exception:
        log.warning("Could not launch a browser — open %s yourself.", url, exc_info=True)


def _already_ours(port: int) -> bool:
    """True if an existing Unit Transfer server is answering on ``port``."""
    import json
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping",
                                    timeout=2) as r:
            return json.loads(r.read().decode("utf-8")).get("app") == "unit-transfer"
    except Exception:
        return False


def _alert(msg: str) -> None:
    """Message box — the only feedback the DETACHED server can give (it has no
    console). The launcher prints to its own console instead."""
    print(msg)
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, msg, "Unit Transfer", 0x10)
    except Exception:
        pass


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
