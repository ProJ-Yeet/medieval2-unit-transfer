"""Registry reloads a mod when its data files change on disk.

Reproduces the reported issue: editing the source bmdb/EDU didn't take effect in a
running server. The Registry re-parses when a mod's files change.

It checks the *cost* of that promise too. Re-stating it as of Phase 14a: a
resolved mod is trusted for :data:`server.REVALIDATE_SECONDS` before its files
are stat'ed again, because the check used to run on every single request —
scanning the mods folder and stat-ing twelve files, all of it inside one lock,
for each of the hundreds of unit-card requests one screen makes. Our own writes
call ``invalidate()`` and are therefore still immediate; somebody else's edit is
picked up a moment later instead of instantly, which is the trade this asserts.

    python -m tests.test_registry_reload
"""
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import config
from unittransfer.server import REVALIDATE_SECONDS, Registry

ok = []
def check(label, cond):
    ok.append(bool(cond)); print(f"  [{'OK ' if cond else 'FAIL'}] {label}")

EDU_ONE = "type Alpha\ndictionary Alpha\ncategory infantry\nsoldier alpha_model, 30, 0, 1\n"
EDU_TWO = EDU_ONE + "\ntype Beta\ndictionary Beta\ncategory infantry\nsoldier beta_model, 30, 0, 1\n"

root = Path(tempfile.mkdtemp(prefix="ut_root_"))
mod = root / "mods" / "TestMod"
data = mod / "data"
(data / "text").mkdir(parents=True)
edu_path = data / "export_descr_unit.txt"
edu_path.write_text(EDU_ONE, encoding="latin-1")
(data / "text" / "export_units.txt").write_bytes(
    "﻿".encode("utf-16-le"))          # minimal (empty) loc file with BOM

cfg = Path(tempfile.mkdtemp(prefix="ut_cfg_"))
config.CONFIG_DIR = cfg
config.SETTINGS_PATH = cfg / "settings.json"
config.save_settings(med2_root=str(root))

reg = Registry(cfg / "icons")
m1 = reg.get("TestMod")
check("initial parse sees 1 unit", len(m1.edu.units) == 1)

# unchanged -> same cached object
m1b = reg.get("TestMod")
check("unchanged mod returns the cached object", m1b is m1)

# edit the EDU on disk (bump mtime), then get() again
time.sleep(0.01)
edu_path.write_text(EDU_TWO, encoding="latin-1")
import os
# force a distinct mtime even on coarse clocks
os.utime(edu_path, (time.time() + 2, time.time() + 2))

# inside the revalidation window the cached parse is still served — deliberate
check("an edit within the window keeps the cached object", reg.get("TestMod") is m1)

# once the window is out, somebody else's edit is picked up
time.sleep(REVALIDATE_SECONDS + 0.05)
m2 = reg.get("TestMod")
check("edited mod is re-parsed (now 2 units)", len(m2.edu.units) == 2)
check("a fresh Mod object was created", m2 is not m1)
check("stable after reload (cached again)", reg.get("TestMod") is m2)

# our own writes never wait for the window at all
EDU_THREE = EDU_TWO + ("\ntype Gamma\ndictionary Gamma\ncategory infantry\n"
                       "soldier gamma_model, 30, 0, 1\n")
edu_path.write_text(EDU_THREE, encoding="latin-1")
reg.invalidate("TestMod")
check("invalidate() reparses immediately", len(reg.get("TestMod").edu.units) == 3)

import shutil
shutil.rmtree(root, ignore_errors=True)
shutil.rmtree(cfg, ignore_errors=True)
print("\n" + ("ALL PASSED" if all(ok) else "SOME FAILED"))
sys.exit(0 if all(ok) else 1)
