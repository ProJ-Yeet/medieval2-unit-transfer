"""Sprites mode over HTTP — exactly the calls the browser page makes.

Runs a real server against a throwaway MED2 root so a mismatch between the UI's
request shape and the engine is caught here:

  overview      /api/sprites
  prep          /api/sprites/prep_plan -> prep_apply -> revert_cfg
  convert       /api/sprites/convert_plan -> convert_apply (with progress)
  wire          /api/sprites/wire -> /api/undo

Skips cleanly when no donor mod or no nvcompress is available.
"""
import json, shutil, struct, sys, tempfile, threading, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import config, sprites
from unittransfer.server import Registry, Handler, _Server

MODS = Path(r"C:/Users/projy/Downloads/Games/Total War MEDIEVAL II Definitive Edition/mods")
BASE = ""

ok = []
def check(label, cond):
    ok.append(bool(cond)); print(f"  [{'OK ' if cond else 'FAIL'}] {label}")


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))

def get_status(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=120) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code

def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read().decode("utf-8"))


def make_tga(path, w=32, h=32):
    hdr = struct.pack('<BBBHHBHHHHBB', 0, 0, 2, 0, 0, 0, 0, 0, w, h, 32, 8)
    px = bytearray()
    for y in range(h):
        for x in range(w):
            px += bytes(((x * 8) % 256, (y * 8) % 256, 128, 255))
    path.write_bytes(hdr + bytes(px))


donor = None
if MODS.is_dir():
    donor = next((m for m in (MODS / "third_age_3", MODS / "Divide_and_Conquer_EUR")
                  if (m / "data/unit_models/battle_models.modeldb").is_file()), None)
if donor is None or not sprites.NVCOMPRESS.is_file():
    print("no donor mod or no nvcompress — skipping")
    sys.exit(0)

# ---- throwaway config + mod ----
cfg = Path(tempfile.mkdtemp(prefix="ut_cfg_"))
config.CONFIG_DIR = cfg; config.BACKUP_DIR = cfg / "backups"
config.SETTINGS_PATH = cfg / "settings.json"; config.LOG_PATH = cfg / "transfers.json"

med2 = Path(tempfile.mkdtemp(prefix="ut_med2_"))
(med2 / "data").mkdir()
mod_root = med2 / "mods" / "TestMod"
data = mod_root / "data"
(data / "text").mkdir(parents=True); (data / "unit_models").mkdir(parents=True)
for rel in ("export_descr_unit.txt", "text/export_units.txt",
            "unit_models/battle_models.modeldb", "descr_mount.txt"):
    src = donor / "data" / rel
    if src.exists():
        shutil.copy2(src, data / rel)
# the CFG that launches the mod, with no [misc] section at all
launch_cfg = mod_root / "TestMod.cfg"
launch_cfg.write_text("[features]\nmod = mods/TestMod\n")
config.save_settings(med2_root=str(med2), run_full_cleaner=False)

modeldb_before = (data / "unit_models/battle_models.modeldb").read_bytes()

Handler.registry = Registry(cfg / "icons")
httpd = _Server(("127.0.0.1", 0), Handler)
BASE = f"http://127.0.0.1:{httpd.server_address[1]}"
threading.Thread(target=httpd.serve_forever, daemon=True).start()
print(f"serving {BASE}")

try:
    print("\n== overview ==")
    ov = get("/api/sprites?mod=TestMod")
    check("the shape the page renders",
          {"models", "pending", "audit", "cfgs", "cfg_state", "have_nvcompress",
           "export_dir", "install_dir", "has_eop"} <= set(ov))
    check("models carry their faction list",
          ov["models"] and all({"name", "factions", "is_mount"} <= set(m)
                               for m in ov["models"]))
    check("the mod's launch CFG is offered",
          any(c.endswith("TestMod.cfg") for c in ov["cfgs"]))
    check("nvcompress reported present", ov["have_nvcompress"] is True)
    check("nothing waiting yet", ov["pending"] == [])
    # a sentinel-less modeldb has a padded first entry with no name; offering it
    # would put M2TWEOP.generateSprite("") in front of the user
    check("the nameless padded entry is not offered as a model",
          all(m["name"] for m in ov["models"]))
    check("nor does it show up in the audit",
          all(r["model"] for r in ov["audit"]["misnamed"]))
    check("an unknown mod is a 404, not a 500",
          get_status("/api/sprites?mod=NoSuchMod") == 404)

    target = next(m["name"] for m in ov["models"] if len(m["factions"]) >= 2)
    facs = sorted(next(m["factions"] for m in ov["models"] if m["name"] == target))[:2]

    print("\n== prep ==")
    body = {"mod": "TestMod", "models": [target, "nosuchmodel"], "method": "classic",
            "cfg_path": str(launch_cfg)}
    plan = post("/api/sprites/prep_plan", body)
    check("known/unknown split", plan["known"] == [target] and plan["unknown"] == ["nosuchmodel"])
    check("script path is the Medieval II root", plan["script_path"] == str(med2 / "sprite_script.txt"))
    check("a CFG edit is planned", plan["cfg_edit"]["action"] == "set")
    check("nothing written by a plan", not (med2 / "sprite_script.txt").exists())

    rec = post("/api/sprites/prep_apply", body)["record"]
    check("sprite_script.txt written to the root", (med2 / "sprite_script.txt").is_file())
    check("never into the mod", not (mod_root / "sprite_script.txt").exists())
    check("export/unit_sprites created", (med2 / "export" / "unit_sprites").is_dir())
    check("the bypass flag is on now",
          get("/api/sprites?mod=TestMod")["cfg_state"][str(launch_cfg)] == "on")
    check("[misc] was created for it", "[misc]" in launch_cfg.read_text())

    eop = post("/api/sprites/prep_plan",
               {"mod": "TestMod", "models": [target], "method": "eop"})
    check("eop emits the console snippet",
          eop["lua"] == f'M2TWEOP.generateSprite("{target}")')
    check("eop writes no sprite_script", eop["script_path"] == "")

    r = post("/api/sprites/revert_cfg", {"cfg": str(launch_cfg)})
    check("revert turns it back off", r["state"] == "off" and r["changed"] is True)
    check("but leaves the line behind", "bypass_sprite_script" in launch_cfg.read_text())

    print("\n== convert ==")
    exp = med2 / "export" / "unit_sprites"
    for f in facs:
        stem = sprites.sprite_stem(f, target)
        (exp / f"{stem}.spr").write_bytes(b"SPRFAKE")
        make_tga(exp / f"{stem}_000.tga")          # identical across factions
    # one incomplete set: a sheet with no .spr beside it
    make_tga(exp / f"{sprites.sprite_stem('zzz', target)}_000.tga")

    ov2 = get("/api/sprites?mod=TestMod")
    check("the generated sets show up as waiting", len(ov2["pending"]) == 3)
    check("the incomplete one is flagged",
          sum(1 for p in ov2["pending"] if not p["complete"]) == 1)

    cplan = post("/api/sprites/convert_plan", {"mod": "TestMod"})
    check("only the complete sets are planned", len(cplan["sets"]) == 2)
    check("the incomplete one is reported, not converted", len(cplan["incomplete"]) == 1)

    res = post("/api/sprites/convert_apply", {"mod": "TestMod", "job": "t1"})
    crec = res["record"]
    check("both sheets converted", len(crec["converted"]) == 2)
    check("identical faction copies collapsed",
          len(crec["duplicates"].get(target, {})) == 1)
    inst = data / "unit_sprites"
    check("installed into the mod", inst.is_dir() and list(inst.glob("*.spr")))
    check("only the kept copy installed", len(list(inst.glob("*.spr"))) == 1)
    check("intermediates cleaned up", not list(exp.glob("*.dds")))
    check("the incomplete set's TGA was left alone",
          (exp / f"{sprites.sprite_stem('zzz', target)}_000.tga").is_file())
    tex = next(inst.glob("*.texture"))
    check("the .texture unwraps to a real DDS",
          sprites.texture_to_dds(tex.read_bytes())[:4] == b"DDS ")

    print("\n== wire ==")
    check("modeldb untouched so far",
          (data / "unit_models/battle_models.modeldb").read_bytes() == modeldb_before)
    w = post("/api/sprites/wire", {"mod": "TestMod", "models": crec["models"],
                                   "duplicates": crec["duplicates"]})
    check("the write went through bmdb mode's planner", "record" in w and "plan" in w)
    check("it is undoable", bool(w["record"].get("id")))
    after = get("/api/sprites?mod=TestMod")
    check("neither faction is left misnamed",
          not any(r["model"] == target and r["faction"].lower() in
                  [f.lower() for f in facs] for r in after["audit"]["misnamed"]))
    check("the audit payload sends counts, not thousands of rows",
          isinstance(after["audit"]["missing"], int)
          and isinstance(after["audit"]["orphans"], int))
    check("the installed sprite is no longer an orphan",
          not any(target.lower() in o.lower()
                  for o in after["audit"]["orphan_sample"]))

    post("/api/undo", {"id": w["record"]["id"]})
    check("undo restores the modeldb byte-exact",
          (data / "unit_models/battle_models.modeldb").read_bytes() == modeldb_before)

    print("\n== errors ==")
    check("an unknown action is an error, not a 500",
          "error" in post("/api/sprites/nonsense", {"mod": "TestMod"}))
    check("a bad CFG path is an error, not a 500",
          "error" in post("/api/sprites/revert_cfg", {"cfg": str(med2 / "nope.cfg")}))
    check("wiring nothing is an error",
          "error" in post("/api/sprites/wire", {"mod": "TestMod", "models": {}}))
finally:
    httpd.shutdown()
    for p in (cfg, med2):
        shutil.rmtree(p, ignore_errors=True)

print(f"\n{sum(ok)}/{len(ok)} checks passed")
sys.exit(0 if all(ok) else 1)
