"""Phase 14b: the log is paged, and it records what the person did too.

Two halves of one complaint — "opening the log lags a lot, up to a few minutes"
and "the logs don't seem to be displaying everything honestly":

  * :func:`server.log_page` answers with a WINDOW of the log instead of all of
    it. The whole thing used to be sent and turned into markup in one go: 480
    entries, 1.1 MB of JSON, 600 KB of HTML for a panel that shows about six.
  * ``POST /api/activity`` lets the page write what the user did into the same
    log as what the tool did, so the record reads as a transcript rather than a
    list of effects with no causes.

    python -m tests.test_log_and_activity
"""
import json
import logging
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import config, server                              # noqa: E402

ok = []


def check(label, cond):
    ok.append(bool(cond))
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}")


# ---- a throwaway log to page through -----------------------------------
cfg = Path(tempfile.mkdtemp(prefix="ut_log_"))
config.CONFIG_DIR = cfg
config.LOG_PATH = cfg / "transfers.json"
config._JSON_CACHE.clear()

MODES = ["transfer", "edit", "traits", "edit", "bmdb"]
entries = []
for i in range(100):
    mode = MODES[i % len(MODES)]
    entries.append({
        "id": f"id-{i:03d}", "when": f"2026-08-18 10:{i % 60:02d}:00",
        "mode": mode, "unit_type": f"unit_{i}", "dest": "TestMod",
        "dest_root": "C:/mods/TestMod" if i % 2 == 0 else "C:/mods/Other",
        "applied": True, "undone": False,
        "summary": "line one\n" + ("x" * 9000 if i == 7 else "line two"),
        # the big one: undo's own bookkeeping, which the page never reads
        "manifest": {"backed_up": [f"data/file_{j}.txt" for j in range(200)]},
    })
config.save_log(entries)

whole = len(json.dumps(entries))
print(f"\n== a {len(entries)}-entry log ({whole:,} bytes on disk) ==")

page = server.log_page()
check("a page, not the whole log", len(page["entries"]) == server.LOG_PAGE)
check("but it says how much there is", page["total"] == 100 and page["grand_total"] == 100)
check("newest first", page["entries"][0]["id"] == "id-099")
size = len(json.dumps(page))
check(f"and it is far smaller ({size:,} vs {whole:,} bytes)", size < whole / 5)
check("undo's manifest is not in a listed entry",
      all("manifest" not in e for e in page["entries"]))
check("a huge summary is cut, and says so",
      any(e.get("summary_cut") for e in server.log_page(offset=90, limit=10)["entries"]))
check("…and cut to the documented cap",
      all(len(e.get("summary") or "") <= server.LOG_SUMMARY_CAP for e in
          server.log_page(offset=90, limit=10)["entries"]))

print("\n== paging ==")
p2 = server.log_page(offset=40)
check("the second page carries on where the first stopped", p2["entries"][0]["id"] == "id-059")
check("offset is reported back", p2["offset"] == 40)
seen = []
for off in range(0, 100, 40):
    seen += [e["id"] for e in server.log_page(offset=off)["entries"]]
check("paging right through sees every entry exactly once",
      len(seen) == 100 and len(set(seen)) == 100)
check("a silly offset is empty rather than an error", server.log_page(offset=500)["entries"] == [])
check("a negative offset is treated as the start", server.log_page(offset=-10)["offset"] == 0)

print("\n== the mode filter ==")
counts = server.log_page()["counts"]
check("counts are over the WHOLE log, not the page",
      counts["edit"] == 40 and counts["transfer"] == 20 and counts["bmdb"] == 20)
edits = server.log_page(mode="edit", limit=100)
check("filtering gives only that mode", edits["total"] == 40
      and all(e["mode"] == "edit" for e in edits["entries"]))
check("an unused mode filters to nothing", server.log_page(mode="sounds")["total"] == 0)

print("\n== 'revert to here' counts the newer writes to the SAME mod ==")
# every second entry went to a different mod, and each mod got 50
first = server.log_page(offset=99, limit=1)["entries"][0]
newest = server.log_page(limit=1)["entries"][0]
check("the newest entry has nothing newer than it", newest["newer_count"] == 0)
check("the oldest has every later write to its own mod behind it",
      first["newer_count"] == 49)
check("a mod's own count ignores the other mod's writes",
      server.log_page(offset=1, limit=1)["entries"][0]["newer_count"] == 0)

undone = [dict(e, undone=(e["id"] == "id-098")) for e in entries]
config.save_log(undone)
config._JSON_CACHE.clear()
check("an undone entry is not something to undo again",
      server.log_page(offset=99, limit=1)["entries"][0]["newer_count"] == 48)


# ---- the activity endpoint ---------------------------------------------
print("\n== what the person did goes into the same log ==")


class Grab(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


grab = Grab()
# `logutil.setup()` is what normally puts this logger at DEBUG (the file handler
# wants everything); nothing has called it here, so without this the activity
# lines are dropped before any handler sees them.
was_level = server.log.level
server.log.setLevel(logging.DEBUG)
server.log.addHandler(grab)
try:
    n = server.Handler._activity(server.Handler, {"events": [
        {"what": "opened", "detail": "Unit Editor (mod: TestMod)"},
        {"what": "changed", "detail": "stat_health: “1” -> “2”"},
    ]})
    check("both events were written", n == 2 and len(grab.lines) == 2)
    check("and they read as a transcript",
          "opened" in grab.lines[0] and "Unit Editor" in grab.lines[0]
          and "stat_health" in grab.lines[1])

    grab.lines.clear()
    check("junk is ignored, not crashed on",
          server.Handler._activity(server.Handler, {"events": "not a list"}) == 0
          and server.Handler._activity(server.Handler, {}) == 0
          and server.Handler._activity(server.Handler, {"events": [1, "two", None]}) == 0
          and server.Handler._activity(server.Handler, {"events": [{"detail": "no what"}]}) == 0)

    grab.lines.clear()
    flood = [{"what": "changed", "detail": f"field_{i}"} for i in range(500)]
    written = server.Handler._activity(server.Handler, {"events": flood})
    check("a flood is capped", written == server.Handler.ACTIVITY_MAX)
    check("…and the log says what it dropped",
          any("were dropped" in ln for ln in grab.lines))

    grab.lines.clear()
    server.Handler._activity(server.Handler, {"events": [
        {"what": "x" * 500, "detail": "y" * 5000}]})
    check("a long line is truncated, not written whole",
          len(grab.lines[0]) < 500)
    grab.lines.clear()
    server.Handler._activity(server.Handler, {"events": [
        {"what": "changed", "detail": "two\nlines\nhere"}]})
    check("an event cannot forge extra log lines with newlines",
          "\n" not in grab.lines[0])
finally:
    server.log.removeHandler(grab)
    server.log.setLevel(was_level)

import shutil                                                        # noqa: E402
shutil.rmtree(cfg, ignore_errors=True)
config._JSON_CACHE.clear()

print(f"\n{sum(ok)}/{len(ok)} checks — " + ("ALL PASSED" if all(ok) else "SOME FAILED"))
sys.exit(0 if all(ok) else 1)
