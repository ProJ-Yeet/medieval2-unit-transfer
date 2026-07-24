"""Registry reloads a mod when its data files change on disk.

Reproduces the reported issue: editing the source bmdb/EDU didn't take effect in a
running server. The Registry now re-parses when a mod's files change.

    python -m tests.test_registry_reload
"""
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import config
from unittransfer.server import Registry

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

m2 = reg.get("TestMod")
check("edited mod is re-parsed (now 2 units)", len(m2.edu.units) == 2)
check("a fresh Mod object was created", m2 is not m1)

# and stable again afterwards
m2b = reg.get("TestMod")
check("stable after reload (cached again)", m2b is m2)

import shutil
shutil.rmtree(root, ignore_errors=True)
shutil.rmtree(cfg, ignore_errors=True)
print("\n" + ("ALL PASSED" if all(ok) else "SOME FAILED"))
sys.exit(0 if all(ok) else 1)
