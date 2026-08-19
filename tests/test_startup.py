"""Startup: preflight checks, icon prewarm progress, and the two-process launch.

Covers:
  * every preflight check passes on a healthy install
  * each failure is reported, and only the ones that really block are fatal:
      - Pillow / web/index.html / unwritable config / old Python  -> fatal
      - MED2 root unset or moved                                  -> warning
      - port held by ANOTHER program -> fatal; held by OUR server -> warning
  * `report()` returns False only when something fatal failed
  * `prewarm_icons` converts on a cold cache, reuses on a warm one, tells the two
    apart in its progress, and stops when asked
  * a real detached launch: the launcher exits, the server outlives it, the log
    is mirrored, and STARTUP-COMPLETE is reached
  * a second launch reuses the running server instead of starting another
  * the log falls back out of an unwritable config/ instead of vanishing
  * "did a browser really load?" is answered by the page heartbeat, not by
    webbrowser.open()'s unreliable Windows return value

    python -m tests.test_startup
"""
import json
import shutil
import socket
import subprocess
import sys
import threading
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import config, server, startup
from unittransfer.logutil import setup as setup_logging

ok = []


def check(label, cond):
    ok.append(bool(cond))
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def by_name(checks, prefix):
    return next(c for c in checks if c.name.startswith(prefix))


setup_logging()
real_cfg = config.CONFIG_DIR
cfg = Path(tempfile.mkdtemp(prefix="ut_cfg_"))
config.CONFIG_DIR = cfg
config.SETTINGS_PATH = cfg / "settings.json"
config.LOG_PATH = cfg / "transfers.json"
config.BACKUP_DIR = cfg / "backups"

# ---- healthy install ----------------------------------------------------
print("== preflight: healthy install ==")
port = free_port()
config.save_settings(med2_root=str(
    Path(r"C:/Users/projy/Downloads/Games/Total War MEDIEVAL II Definitive Edition")))
checks = startup.preflight(port, ROOT / "web")
for c in checks:
    print("   ", c.line())
check("nothing fatal failed", startup.report(checks))
check("MED2 root check lists both mods",
      "Divide_and_Conquer_EUR" in by_name(checks, "MED2 root").detail
      and "Third_Age_Reforged" in by_name(checks, "MED2 root").detail)
check("free port reported free", by_name(checks, f"port {port}").ok)

# ---- MED2 root problems are warnings, not fatal -------------------------
print("\n== preflight: MED2 root problems are non-fatal ==")
config.SETTINGS_PATH.unlink(missing_ok=True)
c = by_name(startup.preflight(port, ROOT / "web"), "MED2 root")
check("unset root: reported, not fatal", not c.ok and not c.fatal and "not set" in c.detail)
config.save_settings(med2_root=r"C:\nope\definitely\gone")
c = by_name(startup.preflight(port, ROOT / "web"), "MED2 root")
check("missing root: reported, not fatal", not c.ok and not c.fatal and "no longer exists" in c.detail)
check("a non-fatal failure still lets startup proceed",
      startup.report(startup.preflight(port, ROOT / "web")))

# ---- fatal checks -------------------------------------------------------
print("\n== preflight: fatal checks ==")
c = by_name(startup.preflight(port, ROOT / "no_such_web"), "web/index.html")
check("missing web/index.html is fatal", c.blocking)
check("report() fails when something fatal fails",
      not startup.report(startup.preflight(port, ROOT / "no_such_web")))

bad_cfg = Path(tempfile.mkdtemp(prefix="ut_ro_")) / "a_file_not_a_dir"
bad_cfg.write_text("x")
config.CONFIG_DIR = bad_cfg / "config"      # can't mkdir under a file
c = by_name(startup.preflight(port, ROOT / "web"), "config/ writable")
check("unwritable config/ is fatal", c.blocking)
config.CONFIG_DIR = cfg

# ---- port: ours vs someone else's --------------------------------------
print("\n== preflight: port in use ==")
squatter = socket.socket()
squatter.bind(("127.0.0.1", 0))
squatter.listen(1)
sq_port = squatter.getsockname()[1]
c = by_name(startup.preflight(sq_port, ROOT / "web"), f"port {sq_port}")
check("port held by another program is FATAL",
      c.blocking and "another program" in c.detail)
squatter.close()

# ---- icon prewarm -------------------------------------------------------
print("\n== icon prewarm ==")
icon_cache = Path(tempfile.mkdtemp(prefix="ut_icons_"))
config.save_settings(med2_root=str(
    Path(r"C:/Users/projy/Downloads/Games/Total War MEDIEVAL II Definitive Edition")))
reg = server.Registry(icon_cache)
t0 = time.monotonic()
cold = startup.prewarm_icons(reg, ["Third_Age_Reforged"])
cold_s = time.monotonic() - t0
check(f"cold cache converted {cold} cards in {cold_s:.1f}s", cold > 300)
check("PNGs actually written", len(list(icon_cache.glob("*.png"))) >= cold)
t0 = time.monotonic()
warm = startup.prewarm_icons(reg, ["Third_Age_Reforged"])
warm_s = time.monotonic() - t0
check(f"warm cache converted nothing ({warm_s:.2f}s)", warm == 0)
check("warm pass is much faster than cold", warm_s < cold_s / 3)
check("unknown mod is skipped, not raised",
      startup.prewarm_icons(reg, ["No_Such_Mod"]) == 0)
shutil.rmtree(icon_cache, ignore_errors=True)

stop = {"v": False}
icon_cache2 = Path(tempfile.mkdtemp(prefix="ut_icons2_"))
reg2 = server.Registry(icon_cache2)


def stopper():
    # stop almost immediately: the pass must bail out, not run to completion
    stop["v"] = True
    return True


check("should_stop cuts the prewarm short",
      startup.prewarm_icons(reg2, ["Third_Age_Reforged"], should_stop=stopper) == 0)
shutil.rmtree(icon_cache2, ignore_errors=True)

# ---- log always lands somewhere, even when config/ is unwritable --------
print("\n== log location fallback ==")
from unittransfer import logutil

blocker = Path(tempfile.mkdtemp(prefix="ut_ro_")) / "not_a_dir"
blocker.write_text("x")
saved_cfg = config.CONFIG_DIR
config.CONFIG_DIR = blocker / "config"          # cannot mkdir under a file
# reset the one-shot logging setup so it re-resolves a location
for h in list(logutil.log.handlers):
    logutil.log.removeHandler(h)
logutil.log._ut_configured = False
logutil._log_path = None
logutil.setup()
logutil.log.info("fallback probe line")
lp = logutil.log_path()
check("a log file is created even when config/ is unwritable",
      lp is not None and lp.exists())
check("the fallback is NOT under the unwritable config/",
      lp is not None and lp.parent != config.CONFIG_DIR)
check("startup.server_log_path() points at the real location", startup.server_log_path() == lp)
# clean up the fallback we just created, and restore normal logging
if lp is not None and "UnitTransfer" in str(lp):
    try:
        lp.unlink()
        lp.parent.rmdir()
    except OSError:
        pass
config.CONFIG_DIR = saved_cfg
for h in list(logutil.log.handlers):
    logutil.log.removeHandler(h)
logutil.log._ut_configured = False
logutil._log_path = None
setup_logging()

# ---- browser-loaded detection uses the heartbeat, not webbrowser's lie ---
print("\n== browser-loaded detection ==")
server._LIVENESS["last_beat"] = None
check("page_ever_loaded() is False before any heartbeat", not server.page_ever_loaded())
server._LIVENESS["last_beat"] = time.time()
check("page_ever_loaded() is True once a heartbeat arrives", server.page_ever_loaded())
server._LIVENESS["last_beat"] = None
check("BROWSER_FAILED_MARKER is defined for the launcher to key on",
      bool(getattr(startup, "BROWSER_FAILED_MARKER", "")))

# ---- the real two-process launch ---------------------------------------
# Uses the project's own config dir (the launcher child reads it), so restore it.
config.CONFIG_DIR = real_cfg
config.SETTINGS_PATH = real_cfg / "settings.json"
config.LOG_PATH = real_cfg / "transfers.json"
config.BACKUP_DIR = real_cfg / "backups"
saved = config.load_settings().get("show_console")
config.save_settings(show_console=False)

print("\n== detached launch ==")
lport = free_port()


def run_launcher():
    return subprocess.run([sys.executable, str(ROOT / "app.py"), "--port", str(lport)],
                          cwd=str(ROOT), capture_output=True, text=True, timeout=300)


def ping(p):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{p}/api/ping", timeout=2) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


r1 = run_launcher()
out1 = r1.stdout + r1.stderr
check("launcher exited 0", r1.returncode == 0)
check("launcher returned instead of blocking on the server", True)
check("console mirrored the server's startup checks", "Startup checks:" in out1)
check("console mirrored the TGA->PNG icon progress",
      "icons: converting unit cards" in out1)
check("console saw STARTUP-COMPLETE", startup.READY_MARKER in out1)
info = ping(lport)
check(f"server outlived the launcher (pid {info and info.get('pid')})",
      info is not None and info.get("app") == "unit-transfer")

r2 = run_launcher()
out2 = r2.stdout + r2.stderr
check("second launch exits 0", r2.returncode == 0)
check("second launch reuses the running server",
      "already running" in out2 and "opening that window" in out2)
check("second launch did NOT start another server",
      ping(lport) and ping(lport)["pid"] == info["pid"])

try:
    urllib.request.urlopen(urllib.request.Request(
        f"http://127.0.0.1:{lport}/api/quit", data=b"{}",
        headers={"Content-Type": "application/json"}), timeout=5).read()
except Exception:
    pass
time.sleep(2)
check("Quit stopped the detached server", ping(lport) is None)

# ---- restart in place (Phase 14c) ---------------------------------------
print("\n== handing the port over to a replacement server ==")
# "Keep the console window open" is read once, at launch, so a running session
# could never grow a console — which read as the setting being broken. A restart
# in place applies it, and it turns on this handover: the replacement starts
# first and waits, because the server it replaces cannot stop before it has
# answered the request that asked it to.
spare = free_port()
check("a port nothing holds is free at once", startup.port_free(spare))
check("…and wait_for_port says so immediately",
      startup.wait_for_port(spare, timeout=1.0))

held = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
held.bind(("127.0.0.1", 0))
held.listen(8)
held_port = held.getsockname()[1]
check("a port with a listener on it is NOT free", not startup.port_free(held_port))

# The question is "could a server bind this?", and only binding answers it: with a
# timeout set, connect_ex returns WSAEWOULDBLOCK for a closed port AND for a
# listener whose accept queue is full, and this machine times out on a closed
# loopback port rather than refusing. Both of those used to read as "free".
stuck = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
stuck.bind(("127.0.0.1", 0))
stuck.listen(1)
stuck_port = stuck.getsockname()[1]
for _ in range(4):
    try:
        socket.create_connection(("127.0.0.1", stuck_port), timeout=0.2)
    except OSError:
        pass
check("a listener that has stopped answering is still NOT free",
      not startup.port_free(stuck_port))
stuck.close()

t0 = time.time()
check("waiting on a held port gives up rather than handing it over",
      not startup.wait_for_port(held_port, timeout=1.0) and time.time() - t0 >= 0.9)

threading.Thread(target=lambda: (time.sleep(1.0), held.close()), daemon=True).start()
t0 = time.time()
check("and it returns as soon as the port is let go",
      startup.wait_for_port(held_port, timeout=10.0) and time.time() - t0 < 5)

# a console child must run on the console interpreter, or its output has nowhere
# to go — pythonw.exe would swallow the very thing the setting asks to see
if sys.platform == "win32":
    import subprocess as _sp
    seen = {}

    def _fake_popen(cmd, **kw):
        seen.update(cmd=cmd, flags=kw.get("creationflags"), out=kw.get("stdout"))
        raise OSError("not really starting anything")

    real_popen = _sp.Popen
    _sp.Popen = _fake_popen
    try:
        for want_console in (True, False):
            try:
                startup.spawn_server(ROOT / "app.py", ["--port", "1", "--wait-port"],
                                     console=want_console)
            except OSError:
                pass
            if want_console:
                check("a console restart runs python.exe, not pythonw.exe",
                      "pythonw" not in seen["cmd"][0].lower())
                check("…with a console of its own, inheriting its handles",
                      bool(seen["flags"] & _sp.CREATE_NEW_CONSOLE) and seen["out"] is None)
            else:
                check("a windowless restart is detached and silenced",
                      bool(seen["flags"] & _sp.DETACHED_PROCESS)
                      and seen["out"] == _sp.DEVNULL)
            check(f"either way it passes --wait-port (console={want_console})",
                  "--wait-port" in seen["cmd"])
    finally:
        _sp.Popen = real_popen


# ---- the exit code the launcher reads (Phase 14c) -----------------------
print("\n== a failed check exits with its own code, so the .bat can say so ==")
import app as app_mod                                                # noqa: E402

_real_preflight = startup.preflight
startup.preflight = lambda port, web: [
    startup.Check("pretend check", False, "failed on purpose", fatal=True)]
try:
    rc_fail = app_mod.main(["--check"])
finally:
    startup.preflight = _real_preflight
check("a failed startup check exits EXIT_PREFLIGHT (2), not 1",
      rc_fail == app_mod.EXIT_PREFLIGHT == 2)
check("a passing run still exits 0", app_mod.main(["--check"]) == 0)
# The launcher branches on that number: it used to print "Pillow is missing" for
# every non-zero code, right underneath the real reason.
bat = (ROOT / "Launch-Medieval2-GUI-Toolkit.bat").read_text(encoding="utf-8",
                                                            errors="replace")
check("the launcher has a branch for code 2", '"%RC%"=="2"' in bat)
check("…and no longer guesses at the cause",
      "Common causes" not in bat and "Pillow is missing      -" not in bat)
check("it points at the printed checks instead",
      "marked FAIL" in bat and "config\\server.log" in bat)

if saved is not None:
    config.save_settings(show_console=saved)
shutil.rmtree(cfg, ignore_errors=True)
print(f"\n{sum(ok)}/{len(ok)} checks — " + ("ALL PASSED" if all(ok) else "SOME FAILED"))
sys.exit(0 if all(ok) else 1)
