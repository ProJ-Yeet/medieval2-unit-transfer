"""Clearing the unit-text cache (`unittransfer.cleaner`) and when it runs.

The tool used to shell out to the mod's "Full Cleaner.bat", which deleted mod
files the game never rebuilds. It now deletes exactly one file — the compiled
`data/text/export_units.txt.strings.bin` — and does it for every job unless the
`clear_strings_bin` setting says otherwise.

Needs no game install: it works on temp folders and a temp settings file.

    python -m tests.test_cleaner
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import cleaner, config
from unittransfer.server import _strings_bin_wanted

ok = []


def check(label, cond):
    ok.append(bool(cond))
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}")


def make_mod(with_bin=True) -> Path:
    root = Path(tempfile.mkdtemp(prefix="ut_clean_"))
    text = root / "data" / "text"
    text.mkdir(parents=True)
    (root / "data" / "export_descr_unit.txt").write_text("type test\n", encoding="utf-8")
    if with_bin:
        (text / "export_units.txt.strings.bin").write_bytes(b"\xff\xfe compiled")
    return root


print("== clear_strings_bin ==")

mod = make_mod()
target = cleaner.strings_bin_path(mod)
check("the fixture really has a .strings.bin", target.exists())

res = cleaner.clear_strings_bin(mod)
check("reports it ran", res.get("ran") is True)
check("reports it deleted something", res.get("deleted") is True)
check("the file is gone", not target.exists())
check("nothing else was touched", (mod / "data" / "export_descr_unit.txt").exists())
check("the mod's data/text folder survives", (mod / "data" / "text").is_dir())

# ---- already clear: a no-op, not an error -------------------------------
res = cleaner.clear_strings_bin(mod)
check("second run still 'ran'", res.get("ran") is True)
check("second run deleted nothing", res.get("deleted") is False)
check("second run says the file was missing", res.get("missing") is True)

# ---- a mod folder that isn't there --------------------------------------
res = cleaner.clear_strings_bin(mod / "nope")
check("missing mod folder -> ran False", res.get("ran") is False)
check("missing mod folder -> an error string", bool(res.get("error")))

# ---- a locked file (the game is running) must not raise -----------------
mod2 = make_mod()
locked = cleaner.strings_bin_path(mod2)
with locked.open("rb"):
    # Windows refuses the unlink while the handle is open; POSIX allows it, so
    # only the "did not raise" half of this is asserted everywhere.
    res = cleaner.clear_strings_bin(mod2)
check("a held-open file never raises", isinstance(res, dict))
check("a held-open file either deletes or explains why not",
      res.get("deleted") is True or bool(res.get("error")))

print("\n== when it runs ==")

cfg = Path(tempfile.mkdtemp(prefix="ut_cfg_"))
real_cfg, real_settings = config.CONFIG_DIR, config.SETTINGS_PATH
config.CONFIG_DIR, config.SETTINGS_PATH = cfg, cfg / "settings.json"

check("no setting saved -> on by default", _strings_bin_wanted({}) is True)

config.save_settings(clear_strings_bin=False)
check("setting off -> a plain job does not clear", _strings_bin_wanted({}) is False)
check("setting off is overridable per job",
      _strings_bin_wanted({"clear_strings_bin": True}) is True)

config.save_settings(clear_strings_bin=True)
check("setting on -> a plain job clears", _strings_bin_wanted({}) is True)
check("setting on is overridable per job (batch: last unit only)",
      _strings_bin_wanted({"clear_strings_bin": False}) is False)

config.CONFIG_DIR, config.SETTINGS_PATH = real_cfg, real_settings

print(f"\n{sum(ok)}/{len(ok)} checks — " + ("ALL PASSED" if all(ok) else "SOME FAILED"))
sys.exit(0 if all(ok) else 1)
