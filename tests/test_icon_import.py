"""Importing a replacement unit card / info card in the unit editor.

The game looks a card up in ``ui/units/<the player's faction>/`` under the unit's
*dictionary* name — not wherever the file came from — so one import has to fan
out to a copy per owning faction, renamed. Covers:

  * a .tga import lands in every owning faction folder + the mercs/merc fallback
  * the file is renamed to #<dict>.tga / <dict>_info.tga, whatever it was called
  * ownership changed in the SAME save decides the folders, not the old ownership
  * `slave` alone still gets a folder; slave alongside real factions does not
  * a .png is re-encoded to .tga (a copied .png would never render)
  * one decode per source however many folders it lands in
  * a missing source file is an error, not a traceback
  * a rename + import writes under the new dictionary and warns about the old
  * nothing is written by a plan, and undo restores the mod exactly
"""
import shutil, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import config, edit
from unittransfer.mod import Mod
from unittransfer.transfer import undo

MODS = Path(r"C:/Users/projy/Downloads/Games/Total War MEDIEVAL II Definitive Edition/mods")

ok = []
def check(label, cond):
    ok.append(bool(cond)); print(f"  [{'OK ' if cond else 'FAIL'}] {label}")


donor = next((m for m in (MODS / "third_age_3", MODS / "Divide_and_Conquer_EUR")
              if (m / "data/export_descr_unit.txt").is_file()), None) if MODS.is_dir() else None
if donor is None:
    print("no donor mod available — skipping")
    sys.exit(0)

cfg = Path(tempfile.mkdtemp(prefix="ut_cfg_"))
config.CONFIG_DIR = cfg; config.BACKUP_DIR = cfg / "backups"
config.SETTINGS_PATH = cfg / "settings.json"; config.LOG_PATH = cfg / "transfers.json"


def fresh_mod():
    root = Path(tempfile.mkdtemp(prefix="ut_ico_"))
    data = root / "data"
    (data / "text").mkdir(parents=True)
    (data / "unit_models").mkdir(parents=True)
    for rel in ("export_descr_unit.txt", "text/export_units.txt",
                "unit_models/battle_models.modeldb", "descr_mount.txt"):
        src = donor / "data" / rel
        if src.exists():
            shutil.copy2(src, data / rel)
    return root


def make_png(path, w=32, h=48):
    from PIL import Image
    Image.new("RGBA", (w, h), (200, 40, 40, 255)).save(path)

def make_tga(path, w=32, h=48):
    from PIL import Image
    Image.new("RGBA", (w, h), (40, 200, 40, 255)).save(path, format="TGA")


src_dir = Path(tempfile.mkdtemp(prefix="ut_src_"))
tga_src = src_dir / "MyCoolCard.tga";   make_tga(tga_src)
png_src = src_dir / "from_photoshop.png"; make_png(png_src)
info_src = src_dir / "big_info.tga";    make_tga(info_src, 200, 100)

root = fresh_mod()
mod = Mod(root)
# a unit several factions own, so the fan-out has something to fan out to
unit = next((u for u in mod.edu.units
             if len([f for f in u.ownership if f != "slave"]) >= 2 and u.dictionary), None)
facs = [f.lower() for f in unit.ownership if f != "slave"]
print(f"using {unit.type!r} (dict {unit.dictionary!r}) owned by {len(facs)} faction(s)")

print("\n== a .tga import fans out ==")
req = edit.request_from_dict({"unit": unit.type, "card_src": str(tga_src),
                              "info_src": str(info_src)})
plan = edit.plan_edit(mod, req)
rels = [rel for _s, rel in plan.icon_copies]
check("no errors", not plan.errors)
check("nothing needed converting", not plan.icon_converts)
check("one card per owning faction + the mercs fallback",
      sum(1 for r in rels if r.startswith("ui/units/")) == len(facs) + 1)
check("one info card per owning faction + the merc fallback",
      sum(1 for r in rels if r.startswith("ui/unit_info/")) == len(facs) + 1)
check("renamed to the dictionary, not the source filename",
      all(r.endswith(f"/#{unit.dictionary}.tga") for r in rels if r.startswith("ui/units/"))
      and "MyCoolCard" not in " ".join(rels))
check("every owning faction is covered",
      all(f"ui/units/{f}/#{unit.dictionary}.tga" in rels for f in facs))
check("the mercs/merc fallback folders are included",
      f"ui/units/mercs/#{unit.dictionary}.tga" in rels
      and f"ui/unit_info/merc/{unit.dictionary}_info.tga" in rels)
check("a plan writes nothing", not (root / "data/ui").exists())

print("\n== apply, then undo ==")
before = (root / "data/export_descr_unit.txt").read_bytes()
rec = edit.apply_edit(plan)
check("every planned file exists on disk", all((root / "data" / r).is_file() for r in rels))
check("the copies are the source bytes",
      (root / "data" / f"ui/units/{facs[0]}/#{unit.dictionary}.tga").read_bytes()
      == tga_src.read_bytes())
check("the info card is its own image, not the card",
      (root / "data" / f"ui/unit_info/{facs[0]}/{unit.dictionary}_info.tga").read_bytes()
      == info_src.read_bytes())
undo(rec["id"])
check("undo removes the imported icons",
      not any((root / "data" / r).is_file() for r in rels))
check("undo leaves the EDU untouched",
      (root / "data/export_descr_unit.txt").read_bytes() == before)

print("\n== a .png is converted, not copied ==")
mod = Mod(root)
plan = edit.plan_edit(mod, edit.request_from_dict(
    {"unit": unit.type, "card_src": str(png_src)}))
check("routed to the convert list", plan.icon_converts and not plan.icon_copies)
conv = [rel for _s, rel in plan.icon_converts]
check("written as .tga despite the .png source",
      all(r.endswith(f"/#{unit.dictionary}.tga") for r in conv))
check("the change line says it converted",
      any("converted from .png" in c for c in plan.changes))
rec = edit.apply_edit(plan)
out = root / "data" / conv[0]
check("the result is a real TGA, not a renamed PNG", out.read_bytes()[:2] != b"\x89P")
from PIL import Image
with Image.open(out) as im:
    check("it decodes as TGA at the source's size",
          im.format == "TGA" and im.size == (32, 48))
check("identical bytes in every folder (decoded once)",
      len({(root / 'data' / r).read_bytes() for r in conv}) == 1)
undo(rec["id"])

print("\n== ownership changed in the same save decides the folders ==")
mod = Mod(root)
plan = edit.plan_edit(mod, edit.request_from_dict(
    {"unit": unit.type, "card_src": str(tga_src),
     "field_overrides": {"ownership": "milan, venice"}}))
rels = [rel for _s, rel in plan.icon_copies]
check("uses the NEW ownership",
      f"ui/units/milan/#{unit.dictionary}.tga" in rels
      and f"ui/units/venice/#{unit.dictionary}.tga" in rels)
check("not the old ownership",
      not any(f"ui/units/{f}/" in r for r in rels for f in facs if f not in ("milan", "venice")))

print("\n== slave handling ==")
mod = Mod(root)
plan = edit.plan_edit(mod, edit.request_from_dict(
    {"unit": unit.type, "card_src": str(tga_src),
     "field_overrides": {"ownership": "slave"}}))
rels = [rel for _s, rel in plan.icon_copies]
check("slave alone still gets its folder",
      f"ui/units/slave/#{unit.dictionary}.tga" in rels)
plan = edit.plan_edit(mod, edit.request_from_dict(
    {"unit": unit.type, "card_src": str(tga_src),
     "field_overrides": {"ownership": "milan, slave"}}))
rels = [rel for _s, rel in plan.icon_copies]
check("slave alongside a real faction is dropped",
      f"ui/units/milan/#{unit.dictionary}.tga" in rels
      and f"ui/units/slave/#{unit.dictionary}.tga" not in rels)

print("\n== rename + import ==")
mod = Mod(root)
plan = edit.plan_edit(mod, edit.request_from_dict(
    {"unit": unit.type, "new_dictionary": "renamed_thing", "card_src": str(tga_src)}))
rels = [rel for _s, rel in plan.icon_copies]
check("the import lands under the NEW dictionary",
      any(r.endswith("/#renamed_thing.tga") for r in rels))
check("and none under the old one",
      not any(r.endswith(f"/#{unit.dictionary}.tga") for r in rels))
check("it warns that the old icons still win the lookup",
      any("remove the old icons" in w for w in plan.warnings))

print("\n== errors ==")
mod = Mod(root)
plan = edit.plan_edit(mod, edit.request_from_dict(
    {"unit": unit.type, "card_src": str(src_dir / "does_not_exist.tga")}))
check("a missing source is an error, not a traceback",
      any("not found" in e for e in plan.errors))
plan = edit.plan_edit(mod, edit.request_from_dict({"unit": unit.type}))
check("no import requested changes nothing",
      not plan.icon_copies and not plan.icon_converts)

shutil.rmtree(root, ignore_errors=True)
shutil.rmtree(src_dir, ignore_errors=True)
shutil.rmtree(cfg, ignore_errors=True)

print(f"\n{sum(ok)}/{len(ok)} checks passed")
sys.exit(0 if all(ok) else 1)
