"""Replacing any picture the toolkit shows — :mod:`unittransfer.images`.

Every screen paints its art through ``/icon`` or ``/building_icon``, and the URL
the page put in the ``<img>`` is the whole question. This module hands that URL
back and gets the file on disk, the path(s) a replacement is written to, and the
warnings that belong in the confirm dialog. What is pinned here:

  * a URL that is not one of the two image routes is refused outright, and a
    ``rel`` that walks out of ``data/`` with ``..`` is refused with it
  * ``locate`` finds a loose mod file, an ancillary picture, a faction picture
    and a building icon, and says which of them the mod actually owns
  * borrowed art (the mod ships none, the game's own is showing) plans a
    **created** file inside the mod rather than an overwrite of the game's
  * **a resolution mismatch is a warning**, both ways round, and matching sizes
    produce none — the point of the whole feature
  * a .png is re-encoded as a .tga, and the target's extension changes with it
  * a same-stem sibling in the other native extension is dropped, so two files
    cannot answer to one name
  * a unit card fans out to every faction folder that holds one, not just the
    one the preview happened to resolve
  * a plan writes nothing, an apply writes exactly the planned paths, and undo
    puts the mod back byte for byte

    python -m tests.test_images
"""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import config, images
from unittransfer.mod import Mod
from unittransfer.transfer import undo

MODS = Path(r"C:/Users/projy/Downloads/Games/Total War MEDIEVAL II Definitive Edition/mods")

ok = []


def check(label, cond):
    ok.append(bool(cond))
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}")


cfg = Path(tempfile.mkdtemp(prefix="ut_cfg_"))
config.CONFIG_DIR = cfg
config.BACKUP_DIR = cfg / "backups"
config.SETTINGS_PATH = cfg / "settings.json"
config.LOG_PATH = cfg / "transfers.json"


def paint(path: Path, w, h, colour=(200, 40, 40, 255), fmt=None):
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (w, h), colour).save(path, format=fmt)
    return path


# A mod is a folder with a data/ in it; nothing here needs an EDU, so the whole
# fixture is built rather than borrowed. (The unit-card section below does need
# one, and borrows there.)
root = Path(tempfile.mkdtemp(prefix="ut_img_"))
data = root / "data"
paint(data / "ui" / "pips" / "religion_catholic.tga", 32, 32)
paint(data / "ui" / "ancillaries" / "cool_hat.tga", 48, 48)
paint(data / "ui" / "england" / "symbols" / "symbol_england.tga", 84, 84)
paint(data / "ui" / "northern_european" / "buildings" / "#northern_european_town_hall.tga",
      78, 62)
# An empty EDU, because a real mod always has one and the server warms it when a
# mod is looked up. Nothing here needs a unit until the last section.
(data / "export_descr_unit.txt").write_text("", encoding="latin-1")
mod = Mod(root)

src = Path(tempfile.mkdtemp(prefix="ut_imgsrc_"))
same_tga = paint(src / "same_size.tga", 32, 32, (40, 200, 40, 255), "TGA")
big_tga = paint(src / "way_too_big.tga", 256, 256, (40, 40, 200, 255), "TGA")
a_png = paint(src / "from_photoshop.png", 32, 32, (200, 200, 40, 255))

PIP = f"/icon?mod={mod.name}&kind=modfile&rel=ui/pips/religion_catholic.tga"

print("== only the two image routes, and only inside the mod ==")
for bad in ("/api/settings?mod=X", "http://evil/icon?mod=X", "/web/js/core.js"):
    try:
        images.parse_url(bad)
        check(f"{bad} refused", False)
    except ValueError:
        check(f"{bad} refused", True)
check("a real /icon URL parses",
      images.parse_url(PIP).get("kind") == "modfile")
out = images.locate(mod, f"/icon?mod={mod.name}&kind=modfile&rel=../../../Windows/win.ini")
check("a rel that walks out of data/ is refused",
      not out["ok"] and "not inside the mod" in out["error"])

print("\n== what is showing, and where a replacement goes ==")
out = images.locate(mod, PIP)
check("a loose mod file is found", out["ok"] and out["source"] == "mod")
check("its size is read", (out["current"]["width"], out["current"]["height"]) == (32, 32))
check("the target is the file itself",
      out["targets"] == ["ui/pips/religion_catholic.tga"])

anc = images.locate(mod, f"/icon?mod={mod.name}&kind=ancillary&image=cool_hat.tga")
check("an ancillary picture is found in the mod",
      anc["ok"] and anc["source"] == "mod"
      and anc["targets"] == ["ui/ancillaries/cool_hat.tga"])
missing = images.locate(mod, f"/icon?mod={mod.name}&kind=ancillary&image=nothing_here.tga")
check("an ancillary with no picture still plans one",
      missing["ok"] and not missing["showing"]
      and missing["targets"] == ["ui/ancillaries/nothing_here.tga"])

fac = images.locate(mod, f"/icon?mod={mod.name}&kind=faction"
                         "&rel=ui/england/symbols/symbol_england.tga")
check("a faction picture is found", fac["ok"] and fac["current"]["width"] == 84)

bld = images.locate(mod, f"/building_icon?mod={mod.name}&culture=northern_european"
                         "&level=town_hall&kind=small")
check("a building icon the mod owns is found",
      bld["ok"] and bld["source"] == "mod" and bld["current"]["height"] == 62)
check("its target is the mod's own path",
      bld["targets"] == ["ui/northern_european/buildings/#northern_european_town_hall.tga"])
none = images.locate(mod, f"/building_icon?mod={mod.name}&culture=northern_european"
                          "&level=no_such_level&kind=small")
check("a building icon nothing ships still plans one in the mod",
      none["ok"] and not none["showing"]
      and none["targets"][0].endswith("#northern_european_no_such_level.tga"))

print("\n== the resolution check ==")
p = images.plan(mod, PIP, str(same_tga))
check("same size, no size warning",
      p["ok"] and not any("stretched" in w for w in p["warnings"]))
p = images.plan(mod, PIP, str(big_tga))
check("a bigger picture warns", any("stretched" in w for w in p["warnings"]))
check("and the warning names both sizes",
      any("32x32" in w and "256x256" in w for w in p["warnings"]))
p = images.plan(mod, f"/icon?mod={mod.name}&kind=faction"
                     "&rel=ui/england/symbols/symbol_england.tga", str(same_tga))
check("a smaller picture warns too", any("stretched" in w for w in p["warnings"]))
p = images.plan(mod, f"/icon?mod={mod.name}&kind=ancillary&image=nothing_here.tga",
                str(same_tga))
check("nothing on disk to compare against is not a warning",
      p["ok"] and not any("stretched" in w for w in p["warnings"]))

print("\n== formats ==")
p = images.plan(mod, PIP, str(a_png))
check("a .png is converted", p["converted"] and any(".tga" in w for w in p["warnings"]))
check("and the target keeps the .tga name the engine looks for",
      p["targets"] == ["ui/pips/religion_catholic.tga"])
p = images.plan(mod, PIP, str(src / "not_an_image.txt"))
check("a file that is not there is an error, not a traceback",
      not p["ok"] and "no file at" in p["error"])
(src / "notes.txt").write_text("hello")
p = images.plan(mod, PIP, str(src / "notes.txt"))
check("a .txt is refused by extension", not p["ok"] and "not an image" in p["error"])

dds_twin = data / "ui" / "pips" / "religion_orthodox.dds"
shutil.copy2(data / "ui" / "pips" / "religion_catholic.tga", dds_twin)
p = images.plan(mod, f"/icon?mod={mod.name}&kind=modfile&rel=ui/pips/religion_orthodox.dds",
                str(same_tga))
check("replacing a .dds with a .tga drops the .dds",
      p["replaces"][0]["drops"] == ["ui/pips/religion_orthodox.dds"]
      and p["targets"] == ["ui/pips/religion_orthodox.tga"])
check("and says so", any("answers to the name" in w for w in p["warnings"]))

print("\n== a plan writes nothing ==")
before = sorted(q.relative_to(data).as_posix() for q in data.rglob("*") if q.is_file())
images.plan(mod, PIP, str(big_tga))
after = sorted(q.relative_to(data).as_posix() for q in data.rglob("*") if q.is_file())
check("the mod is untouched by planning", before == after)

print("\n== the write, and undoing it ==")
pip_file = data / "ui/pips/religion_catholic.tga"
was = pip_file.read_bytes()
res = images.apply(mod, PIP, str(big_tga))
check("apply reports the file it wrote",
      res["ok"] and res["written"] == ["ui/pips/religion_catholic.tga"])
check("the picture on disk changed", pip_file.read_bytes() != was)
check("to the size that was picked", images.probe(pip_file)["width"] == 256)
undo(res["id"])
check("undo puts the old picture back", pip_file.read_bytes() == was)

created = images.apply(mod, f"/icon?mod={mod.name}&kind=ancillary&image=brand_new.tga",
                       str(a_png))
new_file = data / "ui/ancillaries/brand_new.tga"
check("a picture with nothing behind it is created", new_file.is_file())
check("a .png landed as a real .tga", images.probe(new_file)["format"] == "TGA")
undo(created["id"])
check("undo removes a created picture rather than leaving it", not new_file.exists())

res = images.apply(mod, f"/icon?mod={mod.name}&kind=modfile&rel=ui/pips/religion_orthodox.dds",
                   str(same_tga))
check("the .dds twin is gone", not dds_twin.exists())
check("and the .tga is there instead", (data / "ui/pips/religion_orthodox.tga").is_file())
undo(res["id"])
check("undo brings the .dds back", dds_twin.is_file())

print("\n== open file location ==")
spot = images.reveal_target(mod, PIP)
check("it points at the file that is showing",
      spot["ok"] and Path(spot["path"]) == pip_file and not spot["outside"])
spot = images.reveal_target(mod, f"/icon?mod={mod.name}&kind=ancillary&image=nowhere.tga")
check("with nothing there, it opens the folder one would go in",
      spot["ok"] and spot.get("folder_only") and Path(spot["path"]) == data / "ui/ancillaries")
spot = images.reveal_target(mod, f"/icon?mod={mod.name}&kind=modfile&rel=../boom")
check("and it refuses what locate refused", not spot["ok"])

print("\n== a unit card fans out to every faction folder ==")
donor = next((m for m in sorted(MODS.iterdir())
              if (m / "data/export_descr_unit.txt").is_file()),
             None) if MODS.is_dir() else None
if donor is None:
    print("  (no mod installed — skipped)")
else:
    real = Path(tempfile.mkdtemp(prefix="ut_imgu_"))
    (real / "data/text").mkdir(parents=True)
    for rel in ("export_descr_unit.txt", "text/export_units.txt"):
        if (donor / "data" / rel).is_file():
            shutil.copy2(donor / "data" / rel, real / "data" / rel)
    rmod = Mod(real)
    # Painted into the folders the GAME looks in (`card_dirs`, which honours
    # card_pic_dir), not into ownership — a merc's card lives under `mercs` and
    # the preview would find nothing in an ownership folder.
    unit = next((u for u in rmod.edu.units if len(u.card_dirs()) > 1), rmod.edu.units[0])
    for fac_ in unit.card_dirs():
        paint(real / "data/ui/units" / fac_ / f"#{unit.dictionary}.tga", 80, 24)
    url = f"/icon?mod={rmod.name}&type={unit.type}&kind=card"
    out = images.locate(rmod, url)
    check(f"every folder holding {unit.dictionary}'s card is a target "
          f"({len(out['targets'])} of them)",
          len(out["targets"]) == len(unit.card_dirs()))
    check("and the one the preview shows is one of them",
          out["showing"] and Path(out["showing"]).parent.name in unit.card_dirs())
    p = images.plan(rmod, url, str(big_tga))
    check("and the 80x24 card warns about a 256x256 replacement",
          any("stretched" in w for w in p["warnings"]))
    res = images.apply(rmod, url, str(same_tga))
    check("all of them are written",
          sorted(res["written"]) == sorted(out["targets"]))
    check("and every one really changed on disk",
          all(images.probe(real / "data" / r)["width"] == 32 for r in res["written"]))
    undo(res["id"])
    check("undo puts all of them back",
          all(images.probe(real / "data" / r)["width"] == 80 for r in res["written"]))
    shutil.rmtree(real, ignore_errors=True)

print("\n== over HTTP, the calls the page actually makes ==")
# A throwaway MED2 root holding a copy of the fixture, so this needs no install.
import json
import threading
import urllib.error
import urllib.request

from unittransfer.server import Handler, Registry, _Server

med2 = Path(tempfile.mkdtemp(prefix="ut_med2_"))
shutil.copytree(root, med2 / "mods" / "ArtMod")
config.save_settings(med2_root=str(med2))
Handler.registry = Registry(cfg / "icons")
httpd = _Server(("127.0.0.1", 0), Handler)
base = f"http://127.0.0.1:{httpd.server_address[1]}"
threading.Thread(target=httpd.serve_forever, daemon=True).start()


def post(path, body):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"http": exc.code, **json.loads(exc.read().decode("utf-8"))}


try:
    web_pip = "/icon?mod=ArtMod&kind=modfile&rel=ui/pips/religion_catholic.tga"
    r = post("/api/image/plan", {"mod": "ArtMod", "url": web_pip, "src": str(big_tga)})
    check("plan comes back over HTTP with the size warning",
          r.get("ok") and any("stretched" in w for w in r["warnings"]))
    check("and with the file it would write",
          r["replaces"] == [{"rel": "ui/pips/religion_catholic.tga",
                             "exists": True, "drops": []}])
    r = post("/api/image/plan", {"mod": "NoSuchMod", "url": web_pip, "src": ""})
    check("an unknown mod is a 404", r.get("http") == 404)
    r = post("/api/image/plan", {"mod": "ArtMod", "url": "/api/settings", "src": ""})
    check("a URL that is not a picture is refused, not a 500",
          r.get("ok") is False and "picture" in r.get("error", ""))
    r = post("/api/image/reveal", {"mod": "ArtMod", "url": "/icon?mod=ArtMod"
                                   "&kind=modfile&rel=../../../boom"})
    check("reveal refuses a path outside the mod without opening anything",
          r.get("ok") is False)

    live = med2 / "mods/ArtMod/data/ui/pips/religion_catholic.tga"
    live_was = live.read_bytes()
    r = post("/api/image/replace", {"mod": "ArtMod", "url": web_pip,
                                    "src": str(a_png)})
    check("replace writes through the server", r.get("ok"))
    check("the .png landed as a .tga, and the pip really changed",
          images.probe(live)["format"] == "TGA" and live.read_bytes() != live_was)
    post("/api/undo", {"id": r["id"]})
    check("and /api/undo puts it back byte for byte", live.read_bytes() == live_was)
finally:
    httpd.shutdown()
    shutil.rmtree(med2, ignore_errors=True)

shutil.rmtree(root, ignore_errors=True)
shutil.rmtree(src, ignore_errors=True)
shutil.rmtree(cfg, ignore_errors=True)

print(f"\n{sum(ok)}/{len(ok)} checks passed")
sys.exit(0 if all(ok) else 1)
