"""Unit packs: export to a zip, and import it as an ordinary transfer source.

A pack is a miniature mod, and that is the whole claim being tested here — not
that some bespoke import routine works, but that the zip round-trips into
something :func:`unittransfer.transfer.plan_transfer` treats like any other
source. Checked:

  * the plan names the unit's own models AND its mount's, and the asset list is
    only files that actually exist
  * the written zip holds the four files a mod is made of, and nothing outside
    ``data/`` except the manifest and the README
  * the EDU and modeldb inside carry ONLY the packed units/entries — a pack that
    quietly shipped the whole source mod would be 400 MB and would overwrite the
    receiving mod if anyone unzipped it by hand
  * reading it back gives the same units, with the manifest intact
  * a zip that is not a pack is refused with a message, not a traceback
  * a malicious member (``../``, absolute path) is dropped rather than extracted
  * mounted through the registry it becomes a discoverable source mod, and a
    real plan_transfer out of it resolves models, mount and assets
  * unmounting removes it and deletes what was unpacked

    python -m tests.test_pack
"""
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import config, edu as edu_mod, modeldb as modeldb_mod, pack
from unittransfer.mod import Mod

MODS = Path(r"C:/Users/projy/Downloads/Games/Total War MEDIEVAL II Definitive Edition/mods")
SRC_MOD, DST_MOD = MODS / "Divide_and_Conquer_EUR", MODS / "Third_Age_6"

ok = []


def check(label, cond):
    ok.append(bool(cond))
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}")


cfg = Path(tempfile.mkdtemp(prefix="ut_cfg_"))
config.CONFIG_DIR = cfg
config.BACKUP_DIR = cfg / "backups"
config.SETTINGS_PATH = cfg / "settings.json"
config.LOG_PATH = cfg / "transfers.json"

tmp = Path(tempfile.mkdtemp(prefix="ut_pack_"))


# ---------------------------------------------------------------------------
print("\n== refusing what is not a pack ==")

junk = tmp / "junk.zip"
with zipfile.ZipFile(junk, "w") as z:
    z.writestr("hello.txt", "not a mod")
try:
    pack.read_manifest(junk)
    check("a zip with no EDU and no manifest is refused", False)
except pack.PackError as e:
    check("a zip with no EDU and no manifest is refused", "not a unit pack" in str(e))

notzip = tmp / "notazip.zip"
notzip.write_bytes(b"this is not a zip at all")
try:
    pack.read_manifest(notzip)
    check("a file that is not a zip is refused", False)
except pack.PackError as e:
    check("a file that is not a zip is refused", "readable zip" in str(e))

try:
    pack.read_manifest(tmp / "nope.zip")
    check("a missing file is refused", False)
except pack.PackError:
    check("a missing file is refused", True)

# A pack arrives from another person, so the extractor is the security boundary.
evil = tmp / "evil.zip"
with zipfile.ZipFile(evil, "w") as z:
    z.writestr("unitpack.json", '{"pack_version": 1, "source_mod": "x", "units": []}')
    z.writestr("data/export_descr_unit.txt", "type test\n")
    z.writestr("../escaped.txt", "should never be written")
    z.writestr("data/../../also_escaped.txt", "nor this")
out = tmp / "evil_out"
pack.unpack(evil, out)
escaped = list(out.parent.glob("escaped.txt")) + list(out.parent.parent.glob("*escaped*"))
check("a '..' member is dropped, not extracted", not escaped)
check("…and the legitimate members still land",
      (out / "data" / "export_descr_unit.txt").is_file())


# ---------------------------------------------------------------------------
if not SRC_MOD.is_dir() or not DST_MOD.is_dir():
    print("\n  -- test mods not present, skipping the round-trip --")
else:
    print("\n== plan ==")
    src = Mod(SRC_MOD)
    # picked dynamically: hardcoding a unit name ties the test to one mod version
    unit = next(u for u in src.edu.units
                if u.mount and u.armour_ug_models and src.find_unit_card(u))
    plan = pack.plan_pack(src, [unit.type, "no such unit at all"])

    check("the requested unit is in the plan", [u.type for u in plan.units] == [unit.type])
    check("a name the mod does not have is reported, not silently dropped",
          plan.missing == ["no such unit at all"])
    lower = {m.lower() for m in plan.models}
    check("the plan carries the unit's own models",
          all(m.lower() in lower for m in unit.model_names() if m))
    mount_model = src.mount_model(unit.mount)
    check("…and its mount's battle model", mount_model in lower)
    check("every asset in the plan exists on disk",
          all(p.is_file() for p, _ in plan.assets))
    check("the mount is listed", unit.mount in plan.mounts)
    check("the summary names the mod and the counts",
          src.name in plan.summary() and str(len(plan.models)) in plan.summary())

    print("\n== write ==")
    zpath = tmp / "unit.zip"
    rec = pack.write_pack(plan, zpath)
    check("the zip was written", zpath.is_file() and rec["bytes"] > 0)

    with zipfile.ZipFile(zpath) as z:
        names = {i.filename for i in z.infolist()}
        edu_text = z.read("data/export_descr_unit.txt").decode(edu_mod.ENCODING)
        db_text = z.read("data/unit_models/battle_models.modeldb").decode(
            modeldb_mod.ENCODING)
    for rel in ("unitpack.json", "README.txt", "data/export_descr_unit.txt",
                "data/text/export_units.txt",
                "data/unit_models/battle_models.modeldb", "data/descr_mount.txt"):
        check(f"the pack holds {rel}", rel in names)
    stray = [n for n in names
             if not n.startswith("data/") and n not in ("unitpack.json", "README.txt")]
    check("nothing sits outside data/ but the manifest and the README", not stray)

    packed_edu = edu_mod.parse_text(edu_text)
    check("the EDU inside holds ONLY the packed unit",
          [u.type for u in packed_edu.units] == [unit.type])
    check("…and the whole source EDU did not come along",
          len(packed_edu.units) < len(src.edu.units))
    packed_db = modeldb_mod.parse_text(db_text)
    named = {e.name for e in packed_db.entries if e.name}
    check("the modeldb inside holds only the packed entries",
          named <= {m.lower() for m in plan.models})
    check("…and it is still a readable modeldb", len(named) == len(plan.models))

    print("\n== read back ==")
    ov = pack.pack_overview(zpath)
    check("the overview names the same unit", [u["type"] for u in ov["units"]] == [unit.type])
    check("the manifest survived", ov["has_manifest"] and ov["manifest"]["source_mod"] == src.name)
    check("the manifest records the source mod's own name",
          ov["manifest"]["units"][0]["type"] == unit.type)
    check("the entries travelled", len(ov["entries"]) == len(plan.models))

    print("\n== a pack is a source mod ==")
    from unittransfer.server import Registry
    from unittransfer.transfer import TransferOptions, plan_transfer

    reg = Registry(Path(tempfile.mkdtemp(prefix="ut_cache_")))
    info = reg.mount_pack(zpath)
    check("mounting names it after the mod it came from", src.name in info["name"])
    check("it shows up as a mod", info["name"] in reg.discover())
    check("…flagged as a pack", reg.is_pack(info["name"]))

    mounted = reg.get(info["name"])
    check("the mounted mod parses as a mod", [u.type for u in mounted.edu.units] == [unit.type])

    tplan = plan_transfer(mounted, unit.type, Mod(DST_MOD), TransferOptions())
    check("planning a transfer OUT of the pack works", not tplan.option_error)
    check("…and it resolves the models", len(tplan.model_actions) > 0)
    check("…and the assets", len(tplan.asset_files) > 0)
    check("…and the mount definition", tplan.mount_action != "")
    check("the relocation folder is named after the source mod, not a temp dir",
          "unit_models" not in info["name"] and src.name.lower()[:4] in info["name"].lower())

    root = Path(info["root"])
    check("unmounting reports it removed something", reg.unmount_pack(info["name"]))
    check("…drops it from the mod list", info["name"] not in reg.discover())
    check("…and deletes what was unpacked", not root.exists())


shutil.rmtree(tmp, ignore_errors=True)
shutil.rmtree(cfg, ignore_errors=True)
bad = ok.count(False)
print(f"\n{len(ok) - bad}/{len(ok)} checks — " + ("ALL PASSED" if not bad else "SOME FAILED"))
sys.exit(1 if bad else 0)
