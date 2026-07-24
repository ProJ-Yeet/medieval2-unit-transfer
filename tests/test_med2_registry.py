"""Registry lookup for the MED2 install root (`config.detect_med2_root`).

Mirrors the key + value `med2_mod_installer.iss` reads (`AppPath` under
`SOFTWARE\\SEGA\\Medieval II Total War`), so a friend who installed via Steam/disk
doesn't have to hunt for the folder themselves. `winreg` is faked in `sys.modules`
so this runs without touching the real registry or requiring the game installed.

    python -m tests.test_med2_registry
"""
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import config

ok = []


def check(label, cond):
    ok.append(bool(cond))
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}")


class FakeKey:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def install_fake_winreg(found_at_flags=None, value=None):
    """found_at_flags: the flags value OpenKey should succeed for (others raise)."""
    fake = types.ModuleType("winreg")
    fake.HKEY_LOCAL_MACHINE = object()
    fake.KEY_READ = 0x20019
    fake.KEY_WOW64_32KEY = 0x0200
    fake.KEY_WOW64_64KEY = 0x0100

    def OpenKey(hive, path, res, access):
        if found_at_flags is None or (access & 0x0300) != found_at_flags:
            raise OSError("not found")
        return FakeKey(value)

    def QueryValueEx(key, name):
        assert name == "AppPath"
        return key.value, 1

    fake.OpenKey = OpenKey
    fake.QueryValueEx = QueryValueEx
    sys.modules["winreg"] = fake
    return fake


real_winreg = sys.modules.get("winreg")
real_platform = sys.platform

print("== detect_med2_root ==")

# ---- key absent under every view -> None --------------------------------
install_fake_winreg(found_at_flags=None)
check("key missing everywhere -> None", config.detect_med2_root() is None)

# ---- key present under the 32-bit (WOW6432Node) view, real folder -------
real_dir = tempfile.mkdtemp(prefix="ut_med2_")
install_fake_winreg(found_at_flags=0x0200, value=real_dir)
check("found under WOW64_32KEY -> that path", config.detect_med2_root() == real_dir)

# ---- key present under the native 64-bit view ---------------------------
install_fake_winreg(found_at_flags=0x0100, value=real_dir)
check("found under WOW64_64KEY -> that path", config.detect_med2_root() == real_dir)

# ---- key present but points at a folder that no longer exists ----------
install_fake_winreg(found_at_flags=0x0200, value=r"C:\definitely\not\a\real\folder")
check("stale registry value (folder gone) -> None", config.detect_med2_root() is None)

# ---- non-Windows short-circuits before touching winreg at all ----------
sys.platform = "linux"
check("non-win32 -> None without consulting winreg", config.detect_med2_root() is None)
sys.platform = real_platform

print("\n== get_med2_root falls back only when unset ==")
cfg = Path(tempfile.mkdtemp(prefix="ut_cfg_"))
real_cfg, real_settings = config.CONFIG_DIR, config.SETTINGS_PATH
config.CONFIG_DIR, config.SETTINGS_PATH = cfg, cfg / "settings.json"

install_fake_winreg(found_at_flags=0x0200, value=real_dir)
check("nothing saved -> registry value used", config.get_med2_root() == real_dir)

explicit = tempfile.mkdtemp(prefix="ut_explicit_")
config.save_settings(med2_root=explicit)
check("explicit setting wins over registry", config.get_med2_root() == explicit)

config.CONFIG_DIR, config.SETTINGS_PATH = real_cfg, real_settings

if real_winreg is not None:
    sys.modules["winreg"] = real_winreg
else:
    sys.modules.pop("winreg", None)

print(f"\n{sum(ok)}/{len(ok)} checks — " + ("ALL PASSED" if all(ok) else "SOME FAILED"))
sys.exit(0 if all(ok) else 1)
