"""Phase 14a: the server must not shut down under a page that is still using it,
and a cache entry it cannot read must not turn into a black unit card.

Both were one incident. Reading the icon cache out of a OneDrive-synced folder
took seconds per file and sometimes failed outright (``OSError: [Errno 22]``),
which filled the browser's handful of connections with slow icon requests; the
page's heartbeat — a ``setInterval`` sharing those same connections — never got
through; and after 150 seconds the liveness watchdog concluded the tab was gone
and stopped a server that was busy serving it. What the user saw was black unit
cards, "TypeError: Failed to fetch", a grey transfer dialog and a dead Settings
button, none of which looks like "the server exited".

    python -m tests.test_liveness_and_cache
"""
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import config, icons, server                       # noqa: E402
from unittransfer.mod import Mod                                     # noqa: E402

ok = []


def check(label, cond):
    ok.append(bool(cond))
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}")


# ---- liveness -----------------------------------------------------------
print("\n== the watchdog counts traffic, not just heartbeats ==")
NOW = 10_000.0


def live(beat=None, seen=None, close=None):
    return {"last_beat": beat, "pending_close": close, "last_seen": seen}


check("a page that beat a moment ago is alive",
      not server.should_stop(NOW, live(beat=NOW - 3)))
check("no heartbeat and no traffic for the dead-man window stops the server",
      server.should_stop(NOW, live(beat=NOW - server._DEAD_MAN - 1)))
check("THE BUG: a page whose heartbeat is starved but whose requests still "
      "arrive is alive",
      not server.should_stop(NOW, live(beat=NOW - server._DEAD_MAN - 1,
                                       seen=NOW - 2)))
check("a tab that said goodbye and went quiet stops the server",
      server.should_stop(NOW, live(beat=NOW - 20, close=NOW - server._BYE_GRACE - 1)))
check("a refresh (goodbye, then traffic again) does not stop the server",
      not server.should_stop(NOW, live(beat=NOW - 20, seen=NOW - 1,
                                       close=NOW - server._BYE_GRACE - 1)))
check("nothing has ever loaded the page -> not our business to stop",
      not server.should_stop(NOW, live()))

before = dict(server._LIVENESS)
try:
    server._LIVENESS.update(live())
    server.note_request("/api/units")
    check("an ordinary request is a sign of life", server._LIVENESS["last_seen"])
    check("…but it is not mistaken for the page having rendered",
          server._LIVENESS["last_beat"] is None)
    server._LIVENESS.update(live())
    server.note_request("/api/ping")
    check("a second launch asking 'are you there' is not a sign of life",
          server._LIVENESS["last_seen"] is None)
finally:
    server._LIVENESS.update(before)


# ---- the icon cache -----------------------------------------------------
print("\n== an unreadable cache entry is a miss, never a black card ==")
tmp = Path(tempfile.mkdtemp(prefix="ut_icons_"))
cache = icons.IconCache(tmp / "cache")

# a real source image to decode
from PIL import Image                                                # noqa: E402
src = tmp / "card.tga"
Image.new("RGBA", (48, 64), (200, 30, 30, 255)).save(src)

good = cache.png_bytes(src)
check("a real card decodes to a real PNG", len(good) > 100 and good[:8] == icons._PNG_MAGIC)
check("and it is cached", cache.is_cached(src))

entry = cache._key(src)
entry.write_bytes(b"not a png at all")
served = cache.png_bytes(src)
check("a corrupt cache entry is re-decoded, not served",
      served[:8] == icons._PNG_MAGIC and len(served) > 100)

entry.write_bytes(b"")
check("an empty cache entry is re-decoded too",
      cache.png_bytes(src)[:8] == icons._PNG_MAGIC)

check("_read_cached never raises on a missing file",
      icons._read_cached(tmp / "nope.png") is None)
check("_read_cached never raises on a directory",
      icons._read_cached(tmp) is None)

# ---- where the cache lives ---------------------------------------------
print("\n== a cache does not belong in a synced folder ==")
d = config.cache_dir("icons")
check("cache_dir is writable and exists", d.is_dir() and os.access(d, os.W_OK))
check("cache_dir is NOT inside the app folder (OneDrive/Dropbox put the app "
      "wherever they like)", ROOT not in d.parents and d != ROOT)
check("a sub-folder is created on request", config.cache_dir("probe_sub").is_dir())
try:
    (config.cache_dir("probe_sub")).rmdir()
except OSError:
    pass


# ---- icon lookup --------------------------------------------------------
print("\n== unit-card lookup lists a folder once instead of globbing it ==")
mroot = tmp / "TestMod"
(mroot / "data" / "ui" / "units" / "england").mkdir(parents=True)
(mroot / "data" / "text").mkdir(parents=True)
(mroot / "data" / "export_descr_unit.txt").write_text(
    "type Alpha\ndictionary Alpha\ncategory infantry\nsoldier a, 30, 0, 1\n"
    "ownership england\n", encoding="latin-1")
(mroot / "data" / "text" / "export_units.txt").write_bytes("﻿".encode("utf-16-le"))
m = Mod(mroot)
unit = m.edu.units[0]

card = mroot / "data" / "ui" / "units" / "england" / "#Alpha.tga"
Image.new("RGBA", (48, 64), (10, 10, 10, 255)).save(card)
found = m.find_unit_card(unit)
check("a card whose case differs from the dictionary is still found",
      found is not None and found.name == "#Alpha.tga")

# the folder is remembered, and a card added afterwards still turns up: the
# index is keyed on the folder's mtime, not on the life of the Mod object
other = mroot / "data" / "ui" / "units" / "england" / "#Alpha.dds"
time.sleep(0.01)
os.utime(card.parent, None)
check("the second lookup is served from the index",
      m.find_unit_card(unit) == found)
card.unlink()
Image.new("RGBA", (48, 64), (10, 10, 10, 255)).save(other.with_suffix(".tga").with_name("#alpha.tga"))
check("a card that appears while the tool is running is picked up",
      (m.find_unit_card(unit) or Path("")).name == "#alpha.tga")

import shutil                                                        # noqa: E402
shutil.rmtree(tmp, ignore_errors=True)

print(f"\n{sum(ok)}/{len(ok)} checks — " + ("ALL PASSED" if all(ok) else "SOME FAILED"))
sys.exit(0 if all(ok) else 1)
