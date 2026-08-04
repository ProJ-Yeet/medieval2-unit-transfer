"""M2TWEOP + Lua over HTTP — the shapes the browser page actually reads.

Runs a real server against a throwaway MED2 root holding one mini mod with an
``eopData`` folder (one unit file, one Lua script), and checks every field the
page depends on is really there:

  /api/units            EOP badge per unit, plus the mod's EOP/EDU split that
                        drives the 500-unit banner
  /api/eop_dirs         read the detected folders, save an explicit list, clear it
  /api/edit/unit        the editor's "saves go to this file" line
  /api/plan             the destination's EOP state and the chosen target file
  /api/bmdb/audit       the Lua-protected list the cleanup dialog renders

A mismatch between the UI's field names and the server's is exactly what this
catches — the Python-level tests never go through JSON.
"""
import json, shutil, sys, tempfile, threading, urllib.error, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import config
from unittransfer import edu as edu_mod
from unittransfer.mod import Mod
from unittransfer.server import Handler, Registry, _Server

MODS = Path(r"C:/Users/projy/Downloads/Games/Total War MEDIEVAL II Definitive Edition/mods")
SRC = next((MODS / n for n in ("third_age_3", "Third_Age_6", "Divide_and_Conquer_EUR",
                               "Third_Age_Reforged")
            if (MODS / n / "data" / "export_descr_unit.txt").is_file()), None)
BASE = ""

ok = []
def check(label, cond):
    ok.append(bool(cond)); print(f"  [{'OK ' if cond else 'FAIL'}] {label}")

def get(path):
    with urllib.request.urlopen(BASE + path, timeout=300) as r:
        return json.loads(r.read().decode("utf-8"))

def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read().decode("utf-8"))


if SRC is None:
    print("No source mod available under", MODS); sys.exit(1)

cfg = Path(tempfile.mkdtemp(prefix="ut_cfg_"))
config.CONFIG_DIR = cfg; config.BACKUP_DIR = cfg / "backups"
config.SETTINGS_PATH = cfg / "settings.json"; config.LOG_PATH = cfg / "transfers.json"

med2 = Path(tempfile.mkdtemp(prefix="ut_med2_"))


def make_mod(name: str, with_eop: bool):
    root = med2 / "mods" / name
    data = root / "data"
    (data / "text").mkdir(parents=True); (data / "unit_models").mkdir(parents=True)
    for rel in ("export_descr_unit.txt", "text/export_units.txt",
                "unit_models/battle_models.modeldb", "descr_mount.txt"):
        src = SRC / "data" / rel
        if src.exists():
            shutil.copy2(src, data / rel)
    if with_eop:
        donor = next(u for u in Mod(root).edu.units if u.soldier_model)
        d = root / "eopData"; d.mkdir()
        (d / "eop_http_guard.txt").write_text(
            edu_mod.rewrite_block(edu_mod.strip_trailing_filler(donor.raw),
                                  type_new="eop_http_guard"),
            encoding=edu_mod.ENCODING)
    return root


src_root = make_mod("SourceMod", with_eop=True)
dst_root = make_mod("DestMod", with_eop=True)
# An entry the audit ITSELF calls removable before any Lua exists — so "protected
# after the script names it" is a real change of answer, not a coincidence.
import unittransfer.bmdb as _b
free = next(u["entry"] for u in _b.audit(Mod(src_root), scan_orphans=False)["unused"])
(src_root / "eopData" / "spawn.lua").write_text(
    f'-- spawner\nlocal m = "{free}"\nreturn m\n', encoding="utf-8")

config.save_settings(med2_root=str(med2), run_full_cleaner=False)
Handler.registry = Registry(cfg / "icons")
httpd = _Server(("127.0.0.1", 0), Handler)
BASE = f"http://127.0.0.1:{httpd.server_address[1]}"
threading.Thread(target=httpd.serve_forever, daemon=True).start()
print(f"serving {BASE}  (source mod: {SRC.name})")

try:
    print("\n== /api/units carries the EOP mark ==")
    u = get("/api/units?mod=SourceMod")
    check("the mod's EOP folders are reported", len(u.get("eop_dirs") or []) == 1)
    check("so is the EOP / EDU split",
          u.get("eop_count") == 1 and u.get("edu_count") == len(u["units"]) - 1)
    guard = next((x for x in u["units"] if x["type"] == "eop_http_guard"), None)
    check("the EOP unit is in the picker", guard is not None)
    check("it is flagged for the badge", guard and guard.get("eop") is True)
    check("and names its file for the tooltip",
          guard and guard.get("eop_file") == "eopData/eop_http_guard.txt")
    check("every other unit is explicitly not EOP",
          all(x.get("eop") is False for x in u["units"] if x["type"] != "eop_http_guard"))

    print("\n== /api/eop_dirs reads, saves and clears ==")
    r = post("/api/eop_dirs", {"mod": "SourceMod"})
    check("detection reports the folder", [Path(p).name for p in r["detected"]] == ["eopData"])
    check("nothing is configured yet", r["configured"] == [])
    check("the unit file is listed", r["files"] == ["eopData/eop_http_guard.txt"])
    check("counts come back", r["eop_count"] == 1 and r["edu_count"] > 100)

    custom = src_root / "OtherEop"; custom.mkdir()
    r = post("/api/eop_dirs", {"mod": "SourceMod", "dirs": [str(custom)]})
    check("an explicit folder is saved", r["configured"] == [str(custom)])
    check("and replaces detection outright", r["dirs"] == [str(custom)])
    check("so the units in the detected folder are dropped", r["eop_count"] == 0)
    check("the picker agrees", get("/api/units?mod=SourceMod")["eop_count"] == 0)
    r = post("/api/eop_dirs", {"mod": "SourceMod", "dirs": []})
    check("clearing it goes back to detection", r["eop_count"] == 1)
    check("an unknown mod is refused", "error" in post("/api/eop_dirs", {"mod": "Nope"}))

    print("\n== /api/edit/unit says where a save lands ==")
    d = get("/api/edit/unit?mod=SourceMod&type=eop_http_guard")
    check("the editor knows it is an EOP unit", d.get("eop") is True)
    check("and which file it will write", d.get("eop_file") == "eopData/eop_http_guard.txt")
    other = next(x["type"] for x in u["units"] if x["type"] != "eop_http_guard")
    d2 = get(f"/api/edit/unit?mod=SourceMod&type={urllib.parse.quote(other)}")
    check("a normal unit is not flagged", d2.get("eop") is False and d2.get("eop_file") == "")

    print("\n== /api/plan reports the transfer's EOP target ==")
    body = {"source": "SourceMod", "dest": "DestMod", "unit": "eop_http_guard",
            "options": {"eop_target": "auto", "on_conflict": "rename",
                        "new_type": "eop_http_copy", "new_dictionary": "eop_http_copy"}}
    p = post("/api/plan", body)
    check("the source unit is reported as EOP", p.get("source_is_eop") is True)
    check("the destination is reported as EOP-capable", p.get("dest_has_eop") is True)
    check("auto keeps it an EOP unit",
          (p.get("eop_file") or "").startswith("eopData/"))
    check("it adds nothing to the EDU count", p.get("dest_new_units") == 0)
    dd = get("/api/units?mod=DestMod")
    check("dest_unit_count excludes EOP units — that is what the banner counts",
          p.get("dest_unit_count") == len(dd["units"]) - 1)
    check("and dest_eop_count reports them separately", p.get("dest_eop_count") == 1)

    body["options"]["eop_target"] = "edu"
    p = post("/api/plan", body)
    check("forcing 'edu' clears the target file", p.get("eop_file") == "")
    check("and it counts against the cap again", p.get("dest_new_units") == 1)

    print("\n== /api/bmdb/audit reports what Lua protected ==")
    a = get("/api/bmdb/audit?mod=SourceMod")
    check("the scan counted the script", a.get("lua_files") == 1)
    kept = {m["entry"]: m for m in a.get("lua_kept") or []}
    check(f"'{free}' comes back protected", free in kept)
    check("the row names the script and line", "spawn.lua:2" in kept.get(free, {}).get("file", ""))
    check("it is not on the unused list", free not in {x["entry"] for x in a["unused"]})
    check("the audit also reports the mod's EOP state",
          a.get("eop_units") == 1 and len(a.get("eop_dirs") or []) == 1)

finally:
    httpd.shutdown()

print(f"\n{sum(ok)}/{len(ok)} checks — {'ALL PASSED' if all(ok) else 'SOME FAILED'}")
sys.exit(0 if all(ok) else 1)
