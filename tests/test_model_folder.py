"""“All this model's files in one folder”: what counts as ONE folder.

The editor's folder box was calling a perfectly tidy entry scattered, for two
reasons that have nothing to do with the mod being untidy:

  * the model folder and its ``textures/`` sub-folder were counted as two
    folders — but that IS the layout the editor standardises on;
  * the mesh path and the texture paths often spell the same folder with
    different capitalisation (the modeldb is hand-edited and Windows does not
    care), which read as two different folders.

And a third, which is untidiness but not this model's: an attachment set living
in a shared pack (``unit_models/AttachmentSets``) is no more this entry's file to
rehome than its sprite is.

Pure functions over hand-made path slots, plus one pass over a real mod's modeldb
to prove the rule holds against 2000 real entries.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import edit
from unittransfer.mod import Mod

MODS = Path(r"C:/Users/projy/Downloads/Games/Total War MEDIEVAL II Definitive Edition/mods")
REAL = MODS / "Divide_and_Conquer_EUR"

ok = []
def check(label, cond):
    ok.append(bool(cond)); print(f"  [{'OK ' if cond else 'FAIL'}] {label}")


def slots(meshes=(), textures=(), attach=()):
    """The shape :func:`edit.folder_info_of` reads, without a modeldb."""
    out = []
    i = 0
    for m in meshes:
        out.append({"i": i, "kind": "mesh", "value": m, "group": "lod",
                    "faction": "", "label": ""}); i += 1
    for group, paths in (("main", textures), ("attach", attach)):
        for p in paths:
            out.append({"i": i, "kind": "texture", "value": p, "group": group,
                        "faction": "x", "label": ""}); i += 1
    return out


BASE = "unit_models/_Units/anduin"

print("\n=== A: the folder and its textures/ are one folder ===")
info = edit.folder_info_of(slots([f"{BASE}/a.mesh"], [f"{BASE}/textures/a.texture"]))
check("standardised", info["standardized"])
check("base is the model folder", info["base"] == BASE)
check("one folder is listed, not two", info["folders"] == [BASE])

print("\n=== B: capitalisation is not a second folder ===")
info = edit.folder_info_of(slots(["unit_models/_units/anduin/a.mesh"],
                                 ["unit_models/_Units/Anduin/textures/a.texture"]))
check("still standardised", info["standardized"])
check("one folder listed", len(info["folders"]) == 1)
check("the base keeps the mesh's own spelling",
      info["base"] == "unit_models/_units/anduin")
info = edit.folder_info_of(slots(["unit_models/_units/anduin/a.mesh",
                                  "unit_models/_Units/ANDUIN/b.mesh"],
                                 [f"{BASE}/textures/a.texture"]))
check("two spellings of one mesh folder are one folder", info["standardized"])

print("\n=== C: a shared attachment set is not this model's mess ===")
info = edit.folder_info_of(slots([f"{BASE}/a.mesh"], [f"{BASE}/textures/a.texture"],
                                 ["unit_models/AttachmentSets/s.texture"]))
check("still one model folder", info["standardized"] and info["folders"] == [BASE])
check("the attachment folder is reported separately",
      info["external_dirs"] == ["unit_models/AttachmentSets"])
check("and its files are NOT queued to move",
      "unit_models/AttachmentSets/s.texture" not in info["texture_files"])
moves = edit.folder_moves_of(info, "unit_models/_Units/new")
check("standardising elsewhere leaves the shared set alone",
      not any("AttachmentSets" in p for p in moves))

print("\n=== C2: an attachment inside the model's own folder still moves ===")
info = edit.folder_info_of(slots([f"{BASE}/a.mesh"], [f"{BASE}/textures/a.texture"],
                                 [f"{BASE}/textures/att.texture"]))
check("it counts as the model's own", not info["external_dirs"])
moves = edit.folder_moves_of(info, "unit_models/_Units/new")
check("...and moves with it",
      moves.get(f"{BASE}/textures/att.texture")
      == "unit_models/_Units/new/textures/att.texture")

print("\n=== D: genuinely scattered files still warn ===")
info = edit.folder_info_of(slots(["unit_models/_Generals/flag/a.mesh"],
                                 [f"{BASE}/textures/a.texture"]))
check("not standardised", not info["standardized"])
check("both folders are listed", len(info["folders"]) == 2)
info = edit.folder_info_of(slots(["a/x.mesh", "b/y.mesh"], ["a/textures/t.texture"]))
check("meshes in two real folders is not standardised", not info["standardized"])

print("\n=== E: a case-only move is not a move ===")
info = edit.folder_info_of(slots(["unit_models/_units/anduin/a.mesh"],
                                 ["unit_models/_Units/Anduin/textures/a.texture"]))
check("moving to the same folder in another case moves nothing",
      not edit.folder_moves_of(info, "unit_models/_UNITS/ANDUIN"))
check("moving to a real other folder still moves everything",
      len(edit.folder_moves_of(info, "unit_models/elsewhere")) == 2)

print("\n=== F: over a real mod's whole modeldb ===")
mod = Mod(REAL)
entries = mod.modeldb.entries
infos = [edit.folder_info(e) for e in entries]
std = sum(1 for i in infos if i["standardized"])
ext = sum(1 for i in infos if i["external_dirs"])
print(f"  {len(entries)} entries: {std} standardised, {ext} with a shared attachment set")
check("the majority of a real mod's entries read as tidy", std > len(entries) // 2)
check("no entry lists a folder twice",
      all(len(i["folders"]) == len({f.lower() for f in i["folders"]}) for i in infos))
check("no standardised entry lists more than one folder",
      all(len(i["folders"]) <= 1 for i in infos if i["standardized"]))
check("a standardised entry never wants a move to its own base",
      all(not edit.folder_moves_of(i, i["base"]) for i in infos if i["standardized"]))
check("every entry's own files stay under the target when standardised",
      all(all(n.lower().startswith("zz/") for n in
              edit.folder_moves_of(i, "zz").values()) for i in infos[:400]))

print(f"\n{sum(ok)}/{len(ok)} checks passed")
sys.exit(0 if all(ok) else 1)
