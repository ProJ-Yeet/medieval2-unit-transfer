"""Buildings mode over HTTP — exactly the calls the browser page makes.

Runs a real server against a throwaway MED2 root (one mini mod holding only the
EDB, its localisation and the unit files a recruit pool points at) and drives
/api/buildings -> /api/building -> /api/buildings/plan -> /api/buildings/apply
-> /api/undo with the same JSON the page sends, so a drift between the UI's
request shape and the engine is caught here rather than in the browser.

Also covers /building_icon, whose three fallback tiers (the mod's own art, the
unpacked vanilla UI, a drawn placeholder) are what the grid's badges read.

    python -m tests.test_buildings_http
"""
import json, shutil, sys, tempfile, threading, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import buildings, config
from unittransfer.server import Registry, Handler, _Server

MODS = Path(r"C:/Users/projy/Downloads/Games/Total War MEDIEVAL II Definitive Edition/mods")
SOURCE = next((MODS / m for m in ("Divide_and_Conquer_EUR", "third_age_3", "Third_Age_6")
               if (MODS / m / "data" / buildings.EDB_REL).exists()), None)
BASE = ""          # set once the server has bound (port 0 = let the OS pick a free one)

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

def head(path):
    req = urllib.request.Request(BASE + path, method="HEAD")
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, r.headers.get("X-Icon-Source")


if SOURCE is None:
    print(f"no mod with an EDB installed under {MODS} — nothing to test")
    sys.exit(0)
print(f"source mod: {SOURCE.name}")

# ---- throwaway config + mod ----
cfg = Path(tempfile.mkdtemp(prefix="ut_cfg_"))
config.CONFIG_DIR = cfg; config.BACKUP_DIR = cfg / "backups"
config.SETTINGS_PATH = cfg / "settings.json"; config.LOG_PATH = cfg / "transfers.json"

med2 = Path(tempfile.mkdtemp(prefix="ut_med2_"))
data = med2 / "mods" / "TestMod" / "data"
(data / "text").mkdir(parents=True)
for rel in (buildings.EDB_REL, buildings.LOC_REL, "export_descr_unit.txt",
            "text/export_units.txt", "descr_sm_factions.txt"):
    src = SOURCE / "data" / rel
    if src.exists():
        shutil.copy2(src, data / rel)
# one culture folder with one building icon, so the icon endpoint has a "mod" hit
edb_before = (data / buildings.EDB_REL).read_bytes()
config.save_settings(med2_root=str(med2))

# ---- server ----
Handler.registry = Registry(cfg / "icons")
httpd = _Server(("127.0.0.1", 0), Handler)
BASE = f"http://127.0.0.1:{httpd.server_address[1]}"
threading.Thread(target=httpd.serve_forever, daemon=True).start()
print(f"serving {BASE}")

try:
    check("mod discovered", any(m["name"] == "TestMod" for m in get("/api/mods")))

    # ---- 1) the grid's payload ----
    print("\n1) /api/buildings")
    ov = get("/api/buildings?mod=TestMod")
    check("has the EDB", ov["has_file"])
    check("lists building lines", len(ov["lines"]) > 0)
    check("carries the capability vocabulary", len(ov["capabilities"]) > 20)
    check("carries the settlement sizes", "huge_city" in ov["settlement_levels"])
    check("every line reports its art per culture",
          all("art" in l and "top_level" in l for l in ov["lines"]))
    check("art sources are only the three the UI knows",
          all(v in ("mod", "vanilla", "") for l in ov["lines"]
              for a in l["art"].values() for v in a.values()))

    # a line with recruit pools — the one the editor is actually for
    line = next(l for l in ov["lines"] if l["recruit_count"])
    print(f"  line={line['name']!r} ({line['level_count']} levels, "
          f"{line['recruit_count']} units)")

    # ---- 2) one line in full ----
    print("\n2) /api/building")
    d = get(f"/api/building?mod=TestMod&line={urllib.request.quote(line['name'])}")
    check("one entry per level", len(d["levels"]) == line["level_count"])
    check("units the pools name are resolved", len(d["units"]) > 0)
    lvl = next(l for l in d["levels"] if any(c.get("pool") for c in l["capabilities"]))
    pools = [c for c in lvl["capabilities"] if c.get("pool")]
    check("pool numbers are all present",
          all(all(p["pool"].get(k) not in (None, "") or k == "experience"
                  for k in ("unit", "initial", "per_turn", "maximum")) for p in pools))
    check("capabilities carry their original line number",
          all(isinstance(c["line"], int) for c in lvl["capabilities"]))
    try:
        get("/api/building?mod=TestMod&line=no_such_line")
        check("an unknown line is a 404", False)
    except urllib.error.HTTPError as e:
        check("an unknown line is a 404", e.code == 404)

    # ---- 3) the icon endpoint ----
    print("\n3) /building_icon")
    culture = (ov["cultures"] or [""])[0]
    status, src = head(f"/building_icon?mod=TestMod&culture={culture}"
                       f"&level={urllib.request.quote(lvl['name'])}&kind=small")
    check("HEAD is answered (not 501)", status == 200)
    check("a level this mod has no folder for falls through to a placeholder",
          head("/building_icon?mod=TestMod&culture=nowhere&level=nothing&kind=small")
          == (200, "placeholder"))
    with urllib.request.urlopen(
            BASE + "/building_icon?mod=TestMod&culture=nowhere&level=nothing&kind=large") as r:
        png = r.read()
    check("the placeholder is a real PNG", png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 100)
    check("a bad mod name still returns an image, not a 500",
          head("/building_icon?mod=nope&culture=x&level=y&kind=small") == (200, "placeholder"))

    # ---- 4) plan, exactly as the page builds it ----
    print("\n4) /api/buildings/plan")

    def payload(levels):
        return {"mod": "TestMod", "line": d["name"], "levels": levels}

    def level_body(lv, **over):
        # bldPayload(): every capability re-sent with its line number, pool args
        # rebuilt from the four numbers (so the spacing differs from the file)
        caps = []
        for c in lv["capabilities"]:
            p = c.get("pool")
            args = (f'"{p["unit"]}"  {p["initial"]}  {p["per_turn"]}  '
                    f'{p["maximum"]}  {p["experience"]}') if p else c["args"]
            caps.append({"line": c["line"], "keyword": c["keyword"], "args": args,
                         "requires": c["requires"], "delete": False})
        body = {"name": lv["name"], "settlement": lv["settlement"],
                "requires": lv["requires"], "scalars": dict(lv["scalars"]),
                "upgrades": list(lv["upgrades"]), "capabilities": caps}
        body.update(over)
        return body

    noop = post("/api/buildings/plan", payload([level_body(l) for l in d["levels"]]))
    check("re-sending every level unchanged is not a change", not noop["changes"])
    check("…and nothing would be written",
          not noop["edb_rewritten"] and not noop["loc_rewritten"])

    # now a real edit: a cost, a pool's refill rate, and a unit added
    first = pools[0]
    caps = level_body(lvl)["capabilities"]
    for c in caps:
        if c["line"] == first["line"]:
            c["args"] = (f'"{first["pool"]["unit"]}"  {first["pool"]["initial"]}  0.9  '
                         f'{first["pool"]["maximum"]}  {first["pool"]["experience"]}')
    added_unit = next(iter(d["units"].values()))["type"]
    caps.append({"line": None, "keyword": "recruit_pool",
                 "args": f'"{added_unit}"  1  0.5  2  0',
                 "requires": "factions { england, }", "delete": False})
    new_cost = str(int(lvl["scalars"].get("cost", "100")) + 77)
    edited = level_body(lvl, scalars={**lvl["scalars"], "cost": new_cost},
                        capabilities=caps)
    body = payload([edited if l["name"] == lvl["name"] else level_body(l)
                    for l in d["levels"]])

    plan = post("/api/buildings/plan", body)
    check("the plan is exactly the three intended changes", len(plan["changes"]) == 3)
    check("no errors", not plan["errors"])
    check("the EDB would be rewritten", plan["edb_rewritten"])
    check("nothing on disk changed from planning alone",
          (data / buildings.EDB_REL).read_bytes() == edb_before)

    # ---- 5) apply + undo ----
    print("\n5) /api/buildings/apply then /api/undo")
    res = post("/api/buildings/apply", dict(body, clear_strings_bin=False))
    check("apply returned a log record", bool(res.get("record", {}).get("id")))
    check("the record is a buildings edit", res["record"]["mode"] == "buildings")
    after = (data / buildings.EDB_REL).read_bytes()
    check("the EDB on disk changed", after != edb_before)
    check("only the edited lines moved",
          len(after.decode("latin-1").splitlines())
          == len(edb_before.decode("latin-1").splitlines()) + 1)

    reread = get(f"/api/building?mod=TestMod&line={urllib.request.quote(d['name'])}")
    rlvl = next(l for l in reread["levels"] if l["name"] == lvl["name"])
    check("the new cost is served back", rlvl["scalars"].get("cost") == new_cost)
    check("the added unit is served back",
          any(c.get("pool", {}).get("unit") == added_unit for c in rlvl["capabilities"]))
    check("the changed rate is served back",
          any(c.get("pool", {}).get("unit") == first["pool"]["unit"]
              and c["pool"]["per_turn"] == "0.9" for c in rlvl["capabilities"]))

    # What the page does after a save: re-read the line and rebuild the form from
    # it. Saving again from that must be a no-op — otherwise every visit to a
    # building would rewrite it. (Re-posting the OLD body would legitimately add
    # a second copy of the new pool: its `line: null` means "append one".)
    fresh = post("/api/buildings/apply",
                 {"mod": "TestMod", "line": reread["name"],
                  "levels": [level_body(l) for l in reread["levels"]],
                  "clear_strings_bin": False})
    check("saving again straight after a save is refused as a no-op",
          "nothing to change" in (fresh.get("error") or ""))

    post("/api/undo", {"id": res["record"]["id"]})
    check("undo restores the EDB byte-for-byte",
          (data / buildings.EDB_REL).read_bytes() == edb_before)
    check("the reverted file is served back",
          get(f"/api/building?mod=TestMod&line={urllib.request.quote(d['name'])}")
          ["levels"][0]["scalars"] == d["levels"][0]["scalars"])
finally:
    httpd.shutdown()
    shutil.rmtree(med2, ignore_errors=True)
    shutil.rmtree(cfg, ignore_errors=True)

print("\n" + ("ALL PASSED" if all(ok) else "SOME FAILED"))
sys.exit(0 if all(ok) else 1)
