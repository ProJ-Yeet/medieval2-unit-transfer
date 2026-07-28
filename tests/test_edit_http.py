"""Unit-editor mode over HTTP — exactly the calls the browser page makes.

Runs a real server against a throwaway MED2 root (one mini mod copied from
Third_Age_Reforged) and drives /api/edit/unit -> /api/edit/plan ->
/api/edit/apply -> /api/undo with the same JSON payloads the page sends, so a
mismatch between the UI's request shape and the engine is caught here.
"""
import json, shutil, sys, tempfile, threading, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import config
from unittransfer.server import Registry, Handler, _Server

MODS = Path(r"C:/Users/projy/Downloads/Games/Total War MEDIEVAL II Definitive Edition/mods")
TATR = MODS / "Third_Age_Reforged"
BASE = ""          # set once the server has bound (port 0 = let the OS pick a free
                   # one; a fixed port hits Windows' shifting reserved-port ranges)

ok = []
def check(label, cond):
    ok.append(bool(cond)); print(f"  [{'OK ' if cond else 'FAIL'}] {label}")


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))

def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode("utf-8"))


# ---- throwaway config + mod ----
cfg = Path(tempfile.mkdtemp(prefix="ut_cfg_"))
config.CONFIG_DIR = cfg; config.BACKUP_DIR = cfg / "backups"
config.SETTINGS_PATH = cfg / "settings.json"; config.LOG_PATH = cfg / "transfers.json"

med2 = Path(tempfile.mkdtemp(prefix="ut_med2_"))
mod_root = med2 / "mods" / "TestMod"
data = mod_root / "data"
(data / "text").mkdir(parents=True); (data / "unit_models").mkdir(parents=True)
for rel in ("export_descr_unit.txt", "text/export_units.txt",
            "unit_models/battle_models.modeldb"):
    shutil.copy2(TATR / "data" / rel, data / rel)
config.save_settings(med2_root=str(med2))

imports = Path(tempfile.mkdtemp(prefix="ut_import_"))
mesh_src = imports / "http_test.mesh"; mesh_src.write_bytes(b"MESH-HTTP")
tex_src = imports / "http_test.texture"; tex_src.write_bytes(b"TEX-HTTP")

before = {rel: (data / rel).read_bytes() for rel in
          ("export_descr_unit.txt", "text/export_units.txt",
           "unit_models/battle_models.modeldb")}

# ---- server ----
Handler.registry = Registry(cfg / "icons")
httpd = _Server(("127.0.0.1", 0), Handler)
BASE = f"http://127.0.0.1:{httpd.server_address[1]}"
threading.Thread(target=httpd.serve_forever, daemon=True).start()
print(f"serving {BASE}")

try:
    mods = get("/api/mods")
    check("mod discovered", any(m["name"] == "TestMod" for m in mods))
    units = get("/api/units?mod=TestMod")
    detail = None
    for u in units["units"]:
        d = get(f"/api/edit/unit?mod=TestMod&type={urllib.request.quote(u['type'])}")
        if d.get("models") and not d["models"][0].get("missing") and d["models"][0]["paths"]:
            detail = d; break
    check("edit detail served", detail is not None)
    UNIT = detail["type"]
    entry = detail["models"][0]["name"]
    print(f"  unit={UNIT!r} entry={entry!r} fields={len(detail['fields'])}")
    check("fields include type + soldier",
          any(f[0] == "type" for f in detail["fields"])
          and any(f[0] == "soldier" for f in detail["fields"]))
    check("path slots labelled",
          all("label" in p and "kind" in p for p in detail["models"][0]["paths"]))

    # ---- the bmdb tab's payload, exactly as edModelEdits() builds it ----
    # Faction checklist + default textures + a per-faction override + the folder
    # move + a rename, all in one request: the shape most likely to drift from
    # the engine. Runs first, against the untouched mod, and is undone again.
    md = detail["models"][0]
    check("detail carries the bmdb tab's inputs",
          all(k in md for k in ("textures", "texture_defaults", "folder",
                                "attach_factions", "has_attach"))
          and "all_factions" in detail)
    fold = post("/api/edit/model_folder", {"mod": "TestMod", "entry": entry})
    check("model_folder answers", not fold.get("error") and "moves" in fold)

    facs = md["factions"] + [f for f in detail["all_factions"]
                             if f not in md["factions"]][:1]
    unique = md["factions"][0]
    bmdb = {
        "mod": "TestMod", "unit": UNIT, "field_overrides": {}, "remove_fields": [],
        "loc": None, "new_models": [],
        "model_edits": [{
            "entry": entry, "new_name": "http_renamed_entry", "paths": {}, "copies": [],
            "imports": [],
            "defaults": dict(md["texture_defaults"], texture="unit_models/_http/def.texture"),
            "faction_paths": {unique: {"texture": "unit_models/_http/unique.texture"}},
            "factions": facs, "move_dir": "unit_models/_http_folder", "move_shared": True,
        }],
    }
    plan2 = post("/api/edit/plan", bmdb)
    check("bmdb-tab plan ok", not plan2.get("error") and not plan2["errors"])
    check("rename previewed", plan2["entry_renames"].get(entry) == "http_renamed_entry")
    res2 = post("/api/edit/apply", dict(bmdb, run_cleaner=False))
    check("bmdb-tab apply ok", not res2.get("error"))

    after2 = get(f"/api/edit/unit?mod=TestMod&type={urllib.request.quote(UNIT)}")
    m2 = next((m for m in after2["models"] if m["name"] == "http_renamed_entry"), None)
    check("entry renamed and the unit's EDU refs followed", m2 is not None)
    if m2:
        check("faction checklist applied", m2["factions"] == facs)
        check("the overridden faction kept its own texture",
              m2["textures"][unique]["texture"].endswith("/unique.texture"))
        check("every other faction took the default",
              all(v["texture"].endswith("/def.texture")
                  for f, v in m2["textures"].items() if f != unique))
        check("mesh + textures standardised into one folder",
              m2["folder"]["base"] == "unit_models/_http_folder")
    post("/api/undo", {"id": res2["record"]["id"]})
    check("bmdb-tab edit undone byte-exact",
          all((data / rel).read_bytes() == blob for rel, blob in before.items()))

    payload = {
        "mod": "TestMod", "unit": UNIT,
        "field_overrides": {"stat_health": "4, 0"},
        "remove_fields": [],
        "loc": {"name": "HTTP Test Name", "descr": "d", "descr_short": "s"},
        "model_edits": [],
        "new_models": [{
            "name": "http_test_entry", "clone_from": entry,
            "dest_dir": "unit_models/_http_test",
            "mesh_src": str(mesh_src), "texture_src": str(tex_src),
            "mesh_all_lods": True, "apply_to_attach": False, "assign_to": "soldier",
        }],
    }
    plan = post("/api/edit/plan", payload)
    check("plan ok", not plan.get("error") and not plan["errors"])
    check("plan lists the two file copies", len(plan["copies"]) == 2)
    check("plan writes all three text files", len(plan["files_written"]) == 3)
    check("nothing written yet by the plan",
          (data / "export_descr_unit.txt").read_bytes() == before["export_descr_unit.txt"])

    res = post("/api/edit/apply", dict(payload, run_cleaner=False))
    check("apply ok", not res.get("error") and res["record"]["applied"])
    tid = res["record"]["id"]

    after = get(f"/api/edit/unit?mod=TestMod&type={urllib.request.quote(UNIT)}")
    check("soldier repointed", any(m["name"] == "http_test_entry" for m in after["models"]))
    check("stat_health saved",
          dict(after["fields"]).get("stat_health") == "4, 0")
    check("name saved", after["loc"]["name"] == "HTTP Test Name")
    check("mesh copied in", (data / "unit_models/_http_test/http_test.mesh").read_bytes() == b"MESH-HTTP")
    check("texture copied in", (data / "unit_models/_http_test/http_test.texture").read_bytes() == b"TEX-HTTP")

    log = get("/api/log")
    check("log entry is an edit", log and log[-1]["mode"] == "edit" and log[-1]["id"] == tid)

    undone = post("/api/undo", {"id": tid})
    check("undo reported", undone.get("undone"))
    for rel, blob in before.items():
        check(f"{rel} restored byte-exact", (data / rel).read_bytes() == blob)
    check("imported files removed by undo",
          not (data / "unit_models/_http_test/http_test.mesh").exists())
    check("registry sees the reverted unit",
          get(f"/api/edit/unit?mod=TestMod&type={urllib.request.quote(UNIT)}")["loc"]["name"]
          != "HTTP Test Name")
finally:
    httpd.shutdown()

print(f"\n{sum(ok)}/{len(ok)} checks passed")
for p in (cfg, med2, imports):
    shutil.rmtree(p, ignore_errors=True)
sys.exit(0 if all(ok) else 1)
