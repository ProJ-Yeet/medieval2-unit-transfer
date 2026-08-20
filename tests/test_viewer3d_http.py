"""The 3D viewer over HTTP — the three calls the page makes.

    /api/model             which LODs and skins the entry has, and which of
                           them this mod actually ships
    /api/model/geometry    one decoded LOD as the binary payload
    /model_texture         one skin as a PNG

Run against a throwaway mod built from whichever mod is installed, with **this
repo's own reference horse planted at the path the entry names**. That is what
makes the geometry assertions exact rather than approximate: the suite knows
how many vertices and triangles should come back, because it put the file there.

The refusals matter as much as the successes. A viewer is opened from a list of
model entries, and plenty of those name files the mod does not ship — the
answer has to be a sentence saying so, with the right status code, not a 500 and
not an empty canvas.
"""
import json
import shutil
import struct
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import config, mesh, modeldb
from unittransfer.server import Registry, Handler, _Server
from tests import _realmod

REFERENCE = (ROOT / "Reference" / "TWCenter" / "--- TOOLS n RESOURCES ---" /
             "TEMPLATE - Barded-Mailed Horses" / "Barded-Mailed Horses" /
             "mount_barded_horse_lod0.mesh")

ok = []


def check(label, cond):
    ok.append(bool(cond))
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}")


BASE = ""


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=300) as r:
        return json.loads(r.read().decode("utf-8"))


def raw(path):
    with urllib.request.urlopen(BASE + path, timeout=300) as r:
        return r.read()


def status(path):
    """``(code, error text)`` — a refusal is a result here, not an exception."""
    try:
        with urllib.request.urlopen(BASE + path, timeout=300) as r:
            return r.status, ""
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8")).get("error", "")
        except Exception:
            return e.code, ""


def enc(s):
    return urllib.parse.quote(str(s))


if not REFERENCE.is_file():
    print(f"SKIPPED — the reference model is not readable at {REFERENCE}")
    sys.exit(0)

mod_src = _realmod.pick("Divide_and_Conquer_EUR", "Third_Age_Reforged",
                        need="unit_models/battle_models.modeldb")

# ---- a throwaway MED2 root with one mod in it ----
cfg = Path(tempfile.mkdtemp(prefix="ut_cfg_"))
config.CONFIG_DIR = cfg
config.BACKUP_DIR = cfg / "backups"
config.SETTINGS_PATH = cfg / "settings.json"
config.LOG_PATH = cfg / "transfers.json"

med2 = Path(tempfile.mkdtemp(prefix="ut_med2_"))
data = med2 / "mods" / "ViewerMod" / "data"
(data / "text").mkdir(parents=True)
(data / "unit_models").mkdir(parents=True)
for rel in ("export_descr_unit.txt", "text/export_units.txt",
            "unit_models/battle_models.modeldb", "descr_mount.txt"):
    src = mod_src / "data" / rel
    if src.exists():
        shutil.copy2(src, data / rel)
config.save_settings(med2_root=str(med2), run_full_cleaner=False)

db = modeldb.parse_text((data / "unit_models" / "battle_models.modeldb")
                        .read_bytes().decode(modeldb.ENCODING))
# an entry with somewhere to put a mesh and somewhere to put a skin
entry = next((e for e in db.entries
              if e.mesh_files() and [t for t in e.main_textures
                                     if t.texture and t.texture != "0"]), None)
if entry is None:
    print("SKIPPED — no modeldb entry with both a mesh and a texture path")
    sys.exit(0)

lod_rel = entry.mesh_files()[0].replace("\\", "/")
tex_rel = next(t.texture for t in entry.main_textures
               if t.texture and t.texture != "0").replace("\\", "/")
tex_faction = next(t.faction for t in entry.main_textures
                   if t.texture and t.texture != "0")

# the reference horse, planted where this entry says its first LOD lives
planted = data / lod_rel
planted.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(REFERENCE, planted)
horse = mesh.read_mesh(REFERENCE)

# a real .texture from the mod, if it has one loose on disk, at the skin's path
real_tex = next((p for p in (mod_src / "data" / "unit_models").rglob("*.texture")
                 if "normal" not in p.name.lower()), None)
if real_tex is not None:
    (data / tex_rel).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(real_tex, data / tex_rel)

# a second entry's LOD, planted as a file that is NOT a model, for the 400 case
broken_entry = next((e for e in db.entries
                     if e.mesh_files() and e.name != entry.name), None)
if broken_entry is not None:
    broken = data / broken_entry.mesh_files()[0].replace("\\", "/")
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_bytes(REFERENCE.read_bytes()[:4096])   # a mesh cut off short

Handler.registry = Registry(cfg / "icons")
httpd = _Server(("127.0.0.1", 0), Handler)
BASE = f"http://127.0.0.1:{httpd.server_address[1]}"
threading.Thread(target=httpd.serve_forever, daemon=True).start()
print(f"serving {BASE} · mod {mod_src.name} · entry {entry.name}")

try:
    # ---------------------------------------------------------------
    print("\n== /api/model — what the picker opens on ==")
    info = get(f"/api/model?mod=ViewerMod&entry={enc(entry.name)}")
    check("the entry comes back named, with its LODs and skins",
          info["name"] == entry.name and info["lods"] and "skins" in info)
    check("every LOD row says whether the mod actually ships it",
          all({"index", "rel", "distance", "exists"} <= set(l) for l in info["lods"]))
    first = info["lods"][0]
    check(f"the LOD we planted a file at reads as present ({first['rel'][-40:]})",
          first["exists"] is True)
    missing = [l for l in info["lods"][1:] if not l["exists"]]
    check(f"and the ones we did not, do not ({len(missing)} of "
          f"{len(info['lods'])-1} other LODs)",
          len(info["lods"]) == 1 or bool(missing))
    check("a skin is a PAIR — the main sheet and the attachment sheet a faction "
          "wears together — deduplicated on the pair",
          len({(s["rel"], s["attach"]) for s in info["skins"]}) == len(info["skins"])
          and all({"rel", "exists", "attach", "attach_exists", "factions"} <= set(s)
                  for s in info["skins"]))
    shared = max((len(s["factions"]) for s in info["skins"]), default=0)
    paired = sum(1 for s in info["skins"] if s["attach"])
    print(f"          {len(info['skins'])} distinct skin(s), {paired} with an "
          f"attachment sheet; the most shared is used by {shared} factions")
    check("every faction the entry lists is accounted for in some skin row",
          {t.faction for t in entry.main_textures if t.texture and t.texture != "0"}
          <= {f for s in info["skins"] for f in s["factions"]})

    # ---------------------------------------------------------------
    print("\n== /api/model/geometry — the binary payload ==")
    blob = raw(f"/api/model/geometry?mod=ViewerMod&entry={enc(entry.name)}&lod=0")
    check("it opens with the payload magic", blob[:4] == mesh.PAYLOAD_MAGIC)
    hlen = struct.unpack_from("<I", blob, 4)[0]
    head = json.loads(blob[8:8 + hlen])
    check(f"the counts are the model we planted, not something else "
          f"({head['vertices']} vertices, {head['triangles']} triangles)",
          head["vertices"] == horse.vertices and head["triangles"] == horse.triangles)
    check(f"every group came across ({len(head['groups'])})",
          len(head["groups"]) == len(horse.groups)
          and [g["name"] for g in head["groups"]] == [g.name for g in horse.groups])
    # the page samples the two sheets glued into one image and lets the UVs
    # choose, so `sheets` is a LABEL for the part list — but it still has to
    # agree with the decoder, and it has to admit a group that straddles both
    check("each group says which sheet its art lands on, and whether the game "
          "treats it as optional",
          all({"sheets", "optional"} <= set(g) for g in head["groups"])
          and all(g["sheets"] in ("main", "attach", "both") for g in head["groups"])
          and [g["sheets"] for g in head["groups"]] == [g.sheets for g in horse.groups])
    check("the groups' index ranges run end to end with no gap",
          all(head["groups"][i]["start"] + head["groups"][i]["count"]
              == head["groups"][i + 1]["start"] for i in range(len(head["groups"]) - 1)))
    check(f"the bones came across ({len(head['bones'])})",
          head["bones"] == horse.bones)
    # the page rejects a payload whose length disagrees with its header, so the
    # server had better not send one — this is that same arithmetic
    n = head["vertices"]
    want = (8 + hlen + n * 12 + (n * 12 if head["has_normals"] else 0)
            + (n * 8 if head["has_uvs"] else 0)
            + sum(g["count"] for g in head["groups"]) * 2)
    check(f"the payload is exactly as long as its header describes ({len(blob):,} bytes)",
          want == len(blob))
    check("the float arrays start 4-byte aligned, so the page can view them in place",
          (8 + hlen) % 4 == 0)

    # ---------------------------------------------------------------
    print("\n== /model_texture — a skin as a PNG ==")
    if real_tex is None:
        print("  [skip] no loose .texture in this mod to plant")
    else:
        png = raw(f"/model_texture?mod=ViewerMod&rel={enc(tex_rel)}")
        check(f"a .texture comes back as a PNG ({len(png):,} bytes)",
              png[:8] == b"\x89PNG\r\n\x1a\n")
        import io
        from PIL import Image
        im = Image.open(io.BytesIO(png))
        check(f"and no bigger than the viewer asks for ({im.width}x{im.height})",
              max(im.size) <= Handler.MODEL_TEXTURE_MAX)
        check("the skin the entry names reads as present in this mod",
              any(s["rel"] == tex_rel and s["exists"] for s in info["skins"]))

    # ---------------------------------------------------------------
    print("\n== what happens when it cannot be drawn ==")
    code, why = status("/api/model?mod=NoSuchMod&entry=whatever")
    check(f"an unknown mod is a 404 ({code})", code == 404)
    code, why = status("/api/model?mod=ViewerMod&entry=no_such_entry_at_all")
    check(f"an unknown entry is a 404 that names it ({code})",
          code == 404 and "no_such_entry_at_all" in why)
    code, why = status(f"/api/model/geometry?mod=ViewerMod&entry={enc(entry.name)}&lod=99")
    check(f"a LOD the entry does not have is a 404 ({code})", code == 404)

    gone = next((l for l in info["lods"] if not l["exists"]), None)
    if gone is not None:
        code, why = status(f"/api/model/geometry?mod=ViewerMod"
                           f"&entry={enc(entry.name)}&lod={gone['index']}")
        check(f"a LOD the mod does not ship is a 404 saying so ({code})",
              code == 404 and "does not ship" in why)
    else:
        print("  [skip] this entry has only the one LOD")

    if broken_entry is not None:
        code, why = status(f"/api/model/geometry?mod=ViewerMod"
                           f"&entry={enc(broken_entry.name)}&lod=0")
        check(f"a file that will not decode is a 400 carrying the decoder's own "
              f"sentence ({code})", code == 400 and len(why) > 20)
        print(f"          it said: {why[:90]}")

    # a texture path that tries to climb out of the mod is refused by the same
    # rule every other art route uses, and answers a blank rather than a file
    png = raw("/model_texture?mod=ViewerMod&rel=../../../../windows/win.ini")
    check("a skin path pointing outside the mod gets a blank, never the file",
          png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) < 200)

finally:
    httpd.shutdown()

shutil.rmtree(med2, ignore_errors=True)
shutil.rmtree(cfg, ignore_errors=True)

print(f"\n{sum(ok)}/{len(ok)} checks passed")
sys.exit(0 if all(ok) else 1)
