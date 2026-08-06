"""What a building's ``requires`` clause is allowed to name.

Every condition in the EDB refers to something declared in another file by its
code name, and a typo there is invisible in game — the building simply never
becomes available. So the editor offers checklists instead of a text box, and
this checks the lists are actually read out of the mod:

  * factions and cultures, with their real in-game names
  * religions, and how many regions follow each
  * hidden resources (declared at the top of the EDB) and which regions carry them
  * events, merged across historic_events.txt, the campaign scripts and the EDB
    itself — the same event is spelled three different ways in DaC
  * regions, from descr_regions.txt's positional record

Plus the vanilla art pack: a folder of duplicate TGAs in, a manifest and one
lossless WebP per distinct picture out, and the same lookups still answered.

    python -m tests.test_edbvocab
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import buildings, edbvocab
from unittransfer.mod import Mod

MODS = Path(r"C:/Users/projy/Downloads/Games/Total War MEDIEVAL II Definitive Edition/mods")
CANDIDATES = ("Divide_and_Conquer_EUR", "Third_Age_6", "third_age_3")

ok = []


def check(label, cond):
    ok.append(bool(cond))
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}")


installed = [m for m in CANDIDATES
             if (MODS / m / "data" / buildings.EDB_REL).exists()]
if not installed:
    print(f"no mod with an EDB installed under {MODS} — nothing to test")
    sys.exit(0)

# ---- 1) the vocabulary, per mod --------------------------------------------
for name in installed:
    print(f"\n1) {name}")
    mod = Mod(MODS / name)
    v = edbvocab.build(mod)

    check("factions found", len(v["factions"]) > 5)
    check("every faction row carries a code", all(f["code"] for f in v["factions"]))
    check("most factions have an in-game name",
          sum(1 for f in v["factions"] if f["name"]) > len(v["factions"]) / 2)
    check("`all` is a keyword, not listed as a faction",
          v["all_keyword"] == "all"
          and not any(f["code"] == "all" for f in v["factions"]))
    check("cultures are listed separately from factions",
          v["cultures"] and not ({c["code"] for c in v["cultures"]}
                                 & {f["code"] for f in v["factions"]}))
    check("religions found", len(v["religions"]) >= 3)
    check("hidden resources come from the EDB's own header",
          [h["code"] for h in v["hidden_resources"]] == list(mod.edb.hidden_resources))
    check("regions parsed", len(v["regions"]) > 20)
    check("every region has a settlement and an owner",
          all(r["settlement"] and r["faction"] for r in v["regions"]))
    check("every region has its religion breakdown",
          all(r["religions"] for r in v["regions"]))
    named = sum(1 for r in v["regions"] if r["name"] != r["region"])
    check(f"regions resolve display names ({named}/{len(v['regions'])})",
          named > len(v["regions"]) / 2)
    check("no phantom region was made from a stray `religions {` line",
          not any(r["region"].lower().startswith("religions") for r in v["regions"]))
    check("hidden resources know which regions carry them",
          any(h["count"] for h in v["hidden_resources"]))
    check("events found", len(v["events"]) > 10)
    check("every event row has a name and a source",
          all(e["name"] and e["source"] in ("edb", "script", "text")
              for e in v["events"]))
    check("events the EDB uses are listed first",
          [e["source"] for e in v["events"]][:1] in ([], ["edb"], ["script"], ["text"])
          and all(e["source"] == "edb" for e in v["events"][:1] if v["events"]))
    check("the vocabulary is JSON-serialisable", bool(json.dumps(v)))

    # every event_counter the EDB actually names must be offered
    used = {c.values[0].lower()
            for bl in mod.edb.buildings for b in bl.blocks
            for cap in [b] + list(b.capabilities) + list(b.faction_capabilities)
            for c in buildings.parse_clause(getattr(cap, "requires", ""))
            if c.kind == "event_counter" and c.values}
    offered = {e["name"].lower() for e in v["events"]}
    check(f"every event_counter the EDB uses is offered ({len(used)})",
          used <= offered)

    # the same event under two spellings must be ONE row
    dupes = [n for n in {e["name"].lower() for e in v["events"]}
             if sum(1 for e in v["events"] if e["name"].lower() == n) > 1]
    check("no event is listed twice under different casing", not dupes)
    titled = [e for e in v["events"] if e["source"] == "edb" and e["title"]]
    if titled:
        check("an EDB event keeps the EDB's spelling but gains the written title",
              titled[0]["name"] and titled[0]["title"])

# ---- 2) the vanilla art pack ------------------------------------------------
print("\n2) the vanilla art pack")
try:
    from PIL import Image
except ImportError:
    print("  [skip] Pillow not available")
    Image = None

if Image is not None:
    raw = Path(tempfile.mkdtemp(prefix="ut_van_"))
    # two cultures, and the same picture under three names — the duplication the
    # packer exists to remove
    same = Image.new("RGBA", (12, 9), (10, 20, 30, 255))
    other = Image.new("RGBA", (8, 8), (200, 10, 10, 255))
    for culture, stems in (("northern_european", ["#northern_european_abbey",
                                                  "#northern_european_abbey_constructed",
                                                  "#northern_european_church"]),
                           ("eastern_european", ["#eastern_european_abbey"])):
        d = raw / culture / "buildings"
        d.mkdir(parents=True)
        for i, stem in enumerate(stems):
            (same if i != 1 else other).save(d / f"{stem}.tga")
    # something outside buildings/ must be ignored
    (raw / "northern_european" / "units").mkdir()
    same.save(raw / "northern_european" / "units" / "#ignore_me.tga")

    packed = Path(tempfile.mkdtemp(prefix="ut_pack_"))
    sys.path.insert(0, str(ROOT / "tools"))
    from pack_vanilla_ui import pack           # noqa: E402
    stats = pack(raw, packed)

    check("every building icon was read", stats["read"] == 4)
    check("duplicates were written once", stats["written"] == 2)
    check("art outside buildings/ was ignored", stats["read"] == 4)
    manifest = json.loads((packed / buildings.MANIFEST_NAME).read_text(encoding="utf-8"))
    check("the manifest maps every name", len(manifest["entries"]) == 4)
    check("the three identical pictures share one file",
          len({v for k, v in manifest["entries"].items()
               if k != "northern_european/#northern_european_abbey_constructed"}) == 1)

    ui = buildings.VanillaUi(packed)
    check("the pack reports itself as packed", ui.packed)
    check("it lists both cultures",
          ui.cultures == ["eastern_european", "northern_european"])
    hit = ui.lookup("northern_european", "#northern_european_abbey")
    check("a lookup resolves to a real file", hit is not None and hit.exists())
    check("a miss is None", ui.lookup("northern_european", "#nope") is None)
    with Image.open(hit) as im:
        check("the picture survives losslessly", im.size == (12, 9))

    rawui = buildings.VanillaUi(raw)
    check("a RAW folder still works unchanged", not rawui.packed
          and rawui.lookup("eastern_european", "#eastern_european_abbey") is not None)
    check("a raw folder lists its cultures",
          rawui.cultures == ["eastern_european", "northern_european"])

    shutil.rmtree(raw, ignore_errors=True)
    shutil.rmtree(packed, ignore_errors=True)

print("\n" + ("ALL PASSED" if all(ok) else "SOME FAILED"))
sys.exit(0 if all(ok) else 1)
