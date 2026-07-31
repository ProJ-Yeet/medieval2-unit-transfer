"""BMDB mode over HTTP — exactly the calls the browser page makes.

Runs a real server against a throwaway MED2 root (one mini mod copied from
Third_Age_Reforged) and drives the two flows the page has:

  browse/edit   /api/bmdb/entries -> /api/bmdb/entry -> /api/bmdb/plan
                -> /api/bmdb/apply -> /api/undo
  clean up      /api/bmdb/audit -> /api/bmdb/cleanup_plan
                -> /api/bmdb/cleanup_apply -> /api/undo

so a mismatch between the UI's request shape and the engine is caught here.
"""
import json, shutil, sys, tempfile, threading, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import config, modeldb
from unittransfer.server import Registry, Handler, _Server

MODS = Path(r"C:/Users/projy/Downloads/Games/Total War MEDIEVAL II Definitive Edition/mods")
TATR = MODS / "Third_Age_Reforged"
BASE = ""          # set once the server has bound (port 0 = let the OS pick a free one;
                   # a fixed port hits Windows' shifting reserved-port ranges)

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


# ---- throwaway config + mod ----
cfg = Path(tempfile.mkdtemp(prefix="ut_cfg_"))
config.CONFIG_DIR = cfg; config.BACKUP_DIR = cfg / "backups"
config.SETTINGS_PATH = cfg / "settings.json"; config.LOG_PATH = cfg / "transfers.json"

med2 = Path(tempfile.mkdtemp(prefix="ut_med2_"))
mod_root = med2 / "mods" / "TestMod"
data = mod_root / "data"
(data / "text").mkdir(parents=True); (data / "unit_models").mkdir(parents=True)
for rel in ("export_descr_unit.txt", "text/export_units.txt",
            "unit_models/battle_models.modeldb", "descr_mount.txt",
            "descr_character.txt"):
    src = TATR / "data" / rel
    if src.exists():
        shutil.copy2(src, data / rel)
# a file under unit_models nothing in the modeldb mentions
(data / "unit_models" / "_Loose").mkdir()
junk = data / "unit_models" / "_Loose" / "left_behind.texture"
junk.write_bytes(b"J" * 2048)
config.save_settings(med2_root=str(med2), run_full_cleaner=False)

before = {rel: (data / rel).read_bytes() for rel in
          ("export_descr_unit.txt", "unit_models/battle_models.modeldb")}
target = Path(tempfile.mkdtemp(prefix="ut_target_")) / "TestMod_unused"

Handler.registry = Registry(cfg / "icons")
httpd = _Server(("127.0.0.1", 0), Handler)
BASE = f"http://127.0.0.1:{httpd.server_address[1]}"
threading.Thread(target=httpd.serve_forever, daemon=True).start()
print(f"serving {BASE}")

try:
    print("\n== browse ==")
    ov = get("/api/bmdb/entries?mod=TestMod")
    check(f"{ov['count']} entry blocks / {ov['names']} names listed",
          ov["count"] > 500 and len(ov["entries"]) == ov["names"])
    check("every row carries what the list renders",
          all({"name", "lods", "skins", "used_by", "unused", "copies"} <= set(r)
              for r in ov["entries"]))
    # one a UNIT references, so the rename below has to reach the EDU (a model
    # only a mount or descr_character names would not)
    used = next(r for r in ov["entries"]
                if {"soldier", "officer", "armour"} & set(r["kinds"]))
    det = get(f"/api/bmdb/entry?mod=TestMod&name={used['name']}")
    check("one entry comes back in the model-card shape",
          {"paths", "textures", "texture_defaults", "folder", "factions", "used_by"}
          <= set(det["model"]))
    check("with the faction list the skin checklist needs", bool(det["all_factions"]))
    check("an unknown entry is a 404, not a 500",
          get_status("/api/bmdb/entry?mod=TestMod&name=nope_nope") == 404)

    print("\n== edit an entry, no unit involved ==")
    body = {"mod": "TestMod",
            "model_edits": [{"entry": used["name"], "new_name": used["name"] + "_x",
                             "paths": {}, "copies": [], "imports": [],
                             "defaults": {}, "faction_paths": {}, "factions": None,
                             "move_dir": "", "move_shared": False}],
            "new_models": []}
    plan = post("/api/bmdb/plan", body)
    check("planned without errors", not plan["errors"])
    check("the rename is in the plan", plan["entry_renames"].get(used["name"]))
    check("the EDU is rewritten so its users follow",
          "export_descr_unit.txt" in plan["files_written"])
    res = post("/api/bmdb/apply", body)
    check("applied", bool(res.get("record", {}).get("id")))
    check("logged as a bmdb edit", res["record"]["mode"] == "bmdb")
    ov2 = get("/api/bmdb/entries?mod=TestMod")
    check("the list shows the new name",
          any(r["name"] == used["name"] + "_x" for r in ov2["entries"]))
    post("/api/undo", {"id": res["record"]["id"]})
    check("undo restores the modeldb byte-exact",
          (data / "unit_models/battle_models.modeldb").read_bytes()
          == before["unit_models/battle_models.modeldb"])

    print("\n== audit ==")
    # The audit is one long request, so the page polls /api/progress?job= beside
    # it — exactly what this does, on the same server, at the same time.
    seen, stop = [], threading.Event()
    def _poll():
        while not stop.is_set():
            try:
                seen.append(get("/api/progress?job=jtest"))
            except Exception:
                pass
            stop.wait(0.05)
    poller = threading.Thread(target=_poll, daemon=True); poller.start()
    a = get("/api/bmdb/audit?mod=TestMod&job=jtest")
    stop.set(); poller.join(2)
    reports = [s for s in seen if s]
    check(f"the job reported progress while it ran ({len(reports)} polls saw a step)",
          bool(reports) and all(isinstance(r["pct"], int) and r["label"] for r in reports))
    check("and finishes at 100%", get("/api/progress?job=jtest")["pct"] == 100)
    check("an unknown job id answers empty rather than erroring",
          get("/api/progress?job=never_ran") == {})
    check(f"{len(a['unused'])} unused entries", len(a["unused"]) > 0)
    check(f"{len(a['merges'])} soldier-only merge suggestions", len(a["merges"]) > 0)
    check("every suggestion offers alternative twins to pick from",
          all(m["options"] and m["into"] in m["options"] for m in a["merges"]))
    check("the planted loose file is listed as an orphan",
          any(o["rel"] == "unit_models/_Loose/left_behind.texture" for o in a["orphans"]))

    print("\n== cleanup ==")
    merge = a["merges"][0]
    payload = {"mod": "TestMod", "target": str(target),
               "entries": [u["entry"] for u in a["unused"][:15]],
               "merges": [{"entry": merge["entry"], "into": merge["into"]}],
               "orphans": ["unit_models/_Loose/left_behind.texture"]}
    cp = post("/api/bmdb/cleanup_plan", payload)
    check("planned without errors", not cp["errors"])
    check("16 entries queued (15 unused + the merged one)", len(cp["entry_deletes"]) == 16)
    check("the merge is carried in the plan", cp["merges"] == [merge_ := {
        "entry": merge["entry"], "into": merge["into"]}])
    check("the EDU is rewritten for it", cp["edu_rewritten"])
    check("the plan says where everything goes", cp["target"] == str(target))

    bad = post("/api/bmdb/cleanup_plan", dict(payload, target=""))
    check("no destination is an error, not a crash", bool(bad["errors"]))

    ca = post("/api/bmdb/cleanup_apply", payload)
    check("applied", bool(ca.get("record", {}).get("id")))
    ov3 = get("/api/bmdb/entries?mod=TestMod")
    check(f"the modeldb went {ov['names']} -> {ov3['names']} names",
          ov3["names"] == ov["names"] - 16)
    # a duplicated name owns more than one block, and all of its copies go
    gone_blocks = sum(r["copies"] for r in ov["entries"] if r["name"] in cp["entry_deletes"])
    check(f"and {ov['count']} -> {ov3['count']} entry blocks ({gone_blocks} removed)",
          ov3["count"] == ov["count"] - gone_blocks)
    check("the removed entries are gone",
          not (set(cp["entry_deletes"]) & {r["name"] for r in ov3["entries"]}))
    check("the standalone modeldb is next to the exported files",
          (target / "removed_battle_models.modeldb").is_file())
    check("it holds exactly the removed entries",
          sorted(modeldb.parse_file(target / "removed_battle_models.modeldb").by_name())
          == sorted(cp["entry_deletes"]))
    check("the loose file moved to unused_files, path mirrored",
          (target / "unused_files/data/unit_models/_Loose/left_behind.texture").is_file()
          and not junk.exists())
    check("a README explains how to put it back", (target / "README.txt").is_file())

    log = get("/api/log")
    rec = next(e for e in log if e["id"] == ca["record"]["id"])
    check("the log names it a cleanup", rec["mode"] == "bmdb" and rec["action"] == "cleanup")
    check("and remembers where the assets went", rec.get("export_root") == str(target))

    post("/api/undo", {"id": ca["record"]["id"]})
    check("undo restores the modeldb byte-exact",
          (data / "unit_models/battle_models.modeldb").read_bytes()
          == before["unit_models/battle_models.modeldb"])
    check("undo restores export_descr_unit.txt byte-exact",
          (data / "export_descr_unit.txt").read_bytes() == before["export_descr_unit.txt"])
    check("undo brings the loose file back", junk.is_file())
    check("the export folder is untouched by undo",
          (target / "removed_battle_models.modeldb").is_file())
finally:
    httpd.shutdown()

print(f"\n{sum(ok)}/{len(ok)} checks passed")
sys.exit(0 if all(ok) else 1)
