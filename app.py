"""Medieval 2 GUI Toolkit — launch the local web UI.

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
import time
import traceback
import webbrowser
from pathlib import Path

from unittransfer import config, startup
from unittransfer.logutil import setup as setup_logging
from unittransfer.server import WEB_DIR, Handler, serve

APP_PATH = Path(__file__).resolve()

# ---- what our exit codes mean, for Launch-Medieval2-GUI-Toolkit.bat ----
#: A startup check failed. The console already carries the reason, check by check.
EXIT_PREFLIGHT = 2
#: The server IS running, but no browser opened by itself — so the launcher keeps
#: its window, because the address in it is the user's only way in.
EXIT_NO_BROWSER = 3
#: Decoded icons. Not next to the app — see :func:`config.cache_dir` for why a
#: cache must not sit in a folder OneDrive or Dropbox is syncing.
CACHE_DIR = config.cache_dir("icons")


def _parse(argv):
    port, root, verbose, mode = 8756, None, False, "launch"
    wait_port = False
    passthrough = []
    it = iter(argv)
    for a in it:
        if a == "--wait-port":
            # Set by a restart-in-place: the server that asked for us is still
            # holding the port for another moment. Only ever passed by us.
            wait_port = True
        elif a in ("--port", "-p"):
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
    return port, root, verbose, mode, passthrough, wait_port


def main(argv):
    port, root, verbose, mode, passthrough, wait_port = _parse(argv)

    if root:
        config.save_settings(med2_root=str(Path(root)))

    # Logs go to the console (when there is one) and always to config/server.log,
    # so the detached server still leaves a full trail.
    log = setup_logging(verbose)
    log.info("Medieval 2 GUI Toolkit %s — %s", mode, APP_PATH.parent)

    # A restart-in-place starts us while the server being replaced still holds the
    # port: it cannot answer the request that asked for the restart *after* it has
    # stopped, so it replies, spawns us, and only then lets go. Waiting here — and
    # before the preflight port check — is what makes that order work.
    if wait_port and not startup.wait_for_port(port):
        log.error("Port %d never came free — the server being replaced is still "
                  "holding it. Nothing was started.", port)
        return EXIT_PREFLIGHT

    # ---- preflight: say WHY a launch fails instead of dying silently ----
    checks = startup.preflight(port, WEB_DIR)
    if not startup.report(checks):
        if mode == "serve":
            # detached: no console of ours to read, so put it on screen
            _alert("Medieval 2 GUI Toolkit could not start.\n\n"
                   + "\n".join(f"• {c.name}: {c.detail}" for c in checks if c.blocking)
                   + f"\n\nDetails: {startup.server_log_path()}")
        # EXIT_PREFLIGHT, not 1: report() has just printed which check failed and
        # why, so the launcher must point at that instead of listing guesses. It
        # used to say "Pillow is missing -> pip install pillow" on every failure,
        # Pillow installed or not, which is how a wrong reason ends up on screen
        # directly underneath the right one.
        return EXIT_PREFLIGHT
    if mode == "check":
        log.info("Startup checks passed (--check: not starting the server).")
        return 0

    # Already running on this port? Just show that window — don't start a second
    # server only to have it fail to bind.
    if mode != "serve" and _already_ours(port):
        log.info("The Medieval 2 GUI Toolkit is already running on port %d — opening that "
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
    ok, reason, browser_ok = startup.follow_until_ready(proc, offset)
    if not ok:
        log.error("STARTUP FAILED — %s", reason)
        log.error("Full log: %s", startup.server_log_path())
        return 1
    log.info("Server is up: http://127.0.0.1:%d/", port)
    log.info("Stop the tool with Quit in the UI. Log: %s", startup.server_log_path())
    if not browser_ok:
        log.error("No browser opened — leaving this window up so the address "
                  "above stays readable.")
        return EXIT_NO_BROWSER
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
            _watch_for_page(log, port, stopping)
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
            log.info("The Medieval 2 GUI Toolkit is already running on port %d — "
                     "opening that window instead.", port)
            open_browser()
            log.info("%s — reused the running instance.", startup.READY_MARKER)
            return 0
        _alert(f"Medieval 2 GUI Toolkit could not start on port {port}.\n\n{e}\n\n"
               f"Something else is using that port. Launch with --port 8757 "
               f"to pick another one.\n\nDetails: {startup.server_log_path()}")
        return 1
    except Exception:
        log.error("Medieval 2 GUI Toolkit crashed:\n%s", traceback.format_exc())
        _alert(f"Medieval 2 GUI Toolkit crashed.\n\nSee {startup.server_log_path()} "
               "for the traceback.")
        return 1
    return 0


def _watch_for_page(log, port: int, stopping: threading.Event,
                    wait: float = 8.0) -> None:
    """Give the browser a moment to actually load, and shout if it never does.

    The UI heartbeats within a few seconds of loading. If none arrives, no page
    is on screen — almost always a browser that didn't open — so we emit the
    marker that tells the launcher to KEEP its window (the address there is then
    the user's only way in). Emitted BEFORE the ready marker so the launcher sees
    it in the same batch.
    """
    from unittransfer.server import page_ever_loaded
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if stopping.is_set() or page_ever_loaded():
            return
        time.sleep(0.25)
    if page_ever_loaded() or stopping.is_set():
        return
    url = f"http://127.0.0.1:{port}/"
    log.error("%s — no browser has loaded the tool. It IS running; open this "
              "address yourself: %s", startup.BROWSER_FAILED_MARKER, url)


def _open_browser(log, port: int) -> None:
    """Open the UI in the system DEFAULT browser.

    ``webbrowser.open()`` hands the URL to whatever Windows has registered
    (Brave, Edge, Firefox...). The tool never picks a specific browser.

    Its return value is NOT trustworthy on Windows — it reports success even when
    no browser appears — so whether a page really loaded is confirmed separately
    by waiting for the UI's heartbeat (see ``_watch_for_page``).
    """
    url = f"http://127.0.0.1:{port}/"
    log.info("Opening %s in your default browser…", url)
    try:
        webbrowser.open(url)
    except Exception:
        log.debug("webbrowser.open raised", exc_info=True)


def _already_ours(port: int) -> bool:
    """True if an existing toolkit server is answering on ``port``."""
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
        ctypes.windll.user32.MessageBoxW(0, msg, "Medieval 2 GUI Toolkit", 0x10)
    except Exception:
        pass


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
