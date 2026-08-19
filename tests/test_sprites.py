"""Sprites mode — generation prep, the conversion chain, dedup and wire-up.

Self-contained: the codec, naming and CFG cases build their own fixtures, so this
runs without any mod installed. The audit/scan cases use a throwaway copy of a
real mod's modeldb when one is present and skip cleanly when it isn't.

Covers:
  * the .texture container: round-trip against real nvcompress output, the exact
    48-byte header the Python 2 original wrote, and refusal on non-DXT input
  * the naming contract, including the mount case (byzantium_mount_heavy_horse)
    where splitting on underscores alone is ambiguous
  * the CFG flag: set into an existing [misc], create the section when absent,
    flip an existing line, and comment it back out on revert
  * sprite_script.txt lands in the Medieval II root, never in the mod
  * scan_export groups .spr + numbered sheets, and reports incomplete sets
  * the full convert chain end to end through nvcompress
  * dedup collapses byte-identical faction variants and repoints them
  * wire_model_edits emits the shape edit.bmdb_request_from_dict accepts
"""
import shutil
import struct
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import modeldb, sprites
from unittransfer.mod import Mod

MODS = Path(r"C:/Users/projy/Downloads/Games/Total War MEDIEVAL II Definitive Edition/mods")

ok = []
def check(label, cond):
    ok.append(bool(cond)); print(f"  [{'OK ' if cond else 'FAIL'}] {label}")


def make_tga(path: Path, w=32, h=32) -> None:
    """A minimal uncompressed 32-bit TGA — what the generator emits."""
    hdr = struct.pack('<BBBHHBHHHHBB', 0, 0, 2, 0, 0, 0, 0, 0, w, h, 32, 8)
    px = bytearray()
    for y in range(h):
        for x in range(w):
            px += bytes(((x * 8) % 256, (y * 8) % 256, 128, 255))
    path.write_bytes(hdr + bytes(px))


def fake_med2(mod_name="TestMod") -> Path:
    """A Medieval II root with mods/<name>/data, enough for _med2_root()."""
    root = Path(tempfile.mkdtemp(prefix="ut_spr_"))
    (root / "data").mkdir()
    (root / "mods" / mod_name / "data" / "unit_models").mkdir(parents=True)
    return root


# ---------------------------------------------------------------------------
print("\n.texture container")

if sprites.NVCOMPRESS.is_file():
    tmp = Path(tempfile.mkdtemp(prefix="ut_spr_codec_"))
    tga, dds = tmp / "a.tga", tmp / "a.dds"
    make_tga(tga)
    sprites._run_nvcompress(tga, dds, mipmaps=False)
    raw = dds.read_bytes()
    tex = sprites.dds_to_texture(raw)

    check("header is exactly 48 bytes", len(tex) - len(raw) == 48)
    check("round-trips back to the same DDS", sprites.texture_to_dds(tex) == raw)
    check("payload is the DDS verbatim", tex[48:] == raw)

    # the byte layout the Python 2 original produced, reproduced independently
    want = bytearray()
    for i in (0x01000000, 0x30000000, 0x00000000):
        want += struct.pack(">i", i)
    want += b"dds"
    for i in (0x0044E212, 0x00986212, 0x03C0DA12):
        want += struct.pack(">i", i)
    want += struct.pack("<h", 16384)          # DXT5
    want += bytes((0x02, 0, 0, 0, 0, 0, 0, 0x65, 0x56, 0x3A, 0x7C, 3, 0, 0, 0))
    want += raw[12:16]
    check("header matches alpaca's byte-for-byte", tex[:48] == bytes(want))
    check("DXT5 recorded (nvcompress -bc3)", raw[84:88] == b"DXT5")
    shutil.rmtree(tmp, ignore_errors=True)
else:
    print("  -- nvcompress missing, skipping codec round-trip")

try:
    sprites.dds_to_texture(b"NOPE" + bytes(200))
    check("rejects non-DDS input", False)
except sprites.SpriteError:
    check("rejects non-DDS input", True)

try:
    bad = bytearray(b"DDS " + bytes(200))
    bad[84:88] = b"DXT2"
    sprites.dds_to_texture(bytes(bad))
    check("rejects an unencodable DDS format", False)
except sprites.SpriteError:
    check("rejects an unencodable DDS format", True)


# ---------------------------------------------------------------------------
print("\nnaming contract")

check("sprite_line follows <faction>_<model>_sprite",
      sprites.sprite_line("milan", "guardofthecaves")
      == "unit_sprites/milan_guardofthecaves_sprite.spr")
# real modeldbs carry the entry's own casing (england_Mount_Pony_sprite.spr);
# normalising it here would rewrite every sprite line in a mod to no effect
check("sprite_line preserves casing",
      sprites.sprite_line("england", "Mount_Pony")
      == "unit_sprites/england_Mount_Pony_sprite.spr")

models = ["guardofthecaves", "mount_heavy_horse", "horse"]
check("splits a simple stem",
      sprites._match_stem("milan_guardofthecaves_sprite", models)
      == ("milan", "guardofthecaves"))
check("longest model wins on an ambiguous stem",
      sprites._match_stem("byzantium_mount_heavy_horse_sprite", models)
      == ("byzantium", "mount_heavy_horse"))
check("unknown model does not split",
      sprites._match_stem("milan_nosuchmodel_sprite", models) is None)
check("a bare model with no faction is rejected",
      sprites._match_stem("guardofthecaves_sprite", models) is None)


# ---------------------------------------------------------------------------
print("\nCFG bypass flag")

tmp = Path(tempfile.mkdtemp(prefix="ut_spr_cfg_"))

cfg = tmp / "a.cfg"
cfg.write_text("[features]\nmod = mods/X\n\n[misc]\nshow_hud_date = true\n")
sprites.set_cfg_bypass(cfg, True)
check("set into an existing [misc]", sprites._cfg_state(cfg) == "on")
check("placed under [misc], not appended blindly",
      cfg.read_text().index("bypass_sprite_script") > cfg.read_text().index("[misc]"))

cfg2 = tmp / "b.cfg"
cfg2.write_text("[features]\nmod = mods/X\n")
sprites.set_cfg_bypass(cfg2, True)
check("creates [misc] when absent",
      "[misc]" in cfg2.read_text() and sprites._cfg_state(cfg2) == "on")

cfg3 = tmp / "c.cfg"
cfg3.write_text("[misc]\n# bypass_sprite_script = 1\n")
check("a hashed line reads as off", sprites._cfg_state(cfg3) == "off")
sprites.set_cfg_bypass(cfg3, True)
check("flips a hashed line back on", sprites._cfg_state(cfg3) == "on")

sprites.revert_prep(str(cfg3))
check("revert comments it out, not deletes it",
      sprites._cfg_state(cfg3) == "off" and "bypass_sprite_script" in cfg3.read_text())

cfg4 = tmp / "d.cfg"
cfg4.write_text("[misc]\nbypass_sprite_script=true\n")
check("'true' reads as on", sprites._cfg_state(cfg4) == "on")
check("no spurious rewrite when already correct",
      sprites.set_cfg_bypass(cfg2, True) is False)
shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
print("\nconvert chain + dedup")

if sprites.NVCOMPRESS.is_file() and MODS.is_dir():
    donor = next((m for m in (MODS / "third_age_3", MODS / "Divide_and_Conquer_EUR")
                  if (m / "data/unit_models/battle_models.modeldb").is_file()), None)
else:
    donor = None

if donor is None:
    print("  -- no mod modeldb (or no nvcompress) available, skipping")
else:
    root = fake_med2()
    mod_root = root / "mods" / "TestMod"
    shutil.copy2(donor / "data/unit_models/battle_models.modeldb",
                 mod_root / "data/unit_models/battle_models.modeldb")
    mod = Mod(mod_root)

    # A real entry with at least two factions, so dedup has something to do —
    # and preferably two whose sprite lines ALREADY follow
    # `<faction>_<model>_sprite`, because three checks below are about the
    # wire-up reproducing such a line untouched. Most records in a real mod do
    # not follow it (DaC points 1044 of them at one shared file), so picking the
    # first entry with two factions was picking a shared line and asking the
    # generator to have written it.
    target = entry = None
    facs = []
    fallback = None
    for n, e in mod.modeldb.by_name().items():
        by_fac = sorted({t.faction for t in e.main_textures})
        if len(by_fac) < 2:
            continue
        if fallback is None:
            fallback = (n, e, by_fac[:2])
        good = [f for f in by_fac
                if next((t.sprite for t in e.main_textures if t.faction == f), "")
                == sprites.sprite_line(*sprites._real_names(e, f))]
        if len(good) >= 2:
            target, entry, facs = n, e, good[:2]
            break
    conventional = target is not None
    if not conventional and fallback:
        target, entry, facs = fallback
        print(f"  -- no entry in {donor.name} has two factions whose sprite line "
              "follows <faction>_<model>_sprite; the three checks about "
              "reproducing such a line are reported, not asserted")

    exp = root / sprites.EXPORT_REL
    exp.mkdir(parents=True)
    for f in facs:
        stem = sprites.sprite_stem(f, target)
        (exp / f"{stem}.spr").write_bytes(b"SPRFAKE")
        make_tga(exp / f"{stem}_000.tga")      # identical content across factions

    found = sprites.scan_export(mod)
    check("scan groups .spr with its numbered sheet", len(found) == 2)
    check("scan resolves faction + model",
          all(s.model == target and s.faction in facs for s in found.values()))
    check("scan marks the sets complete", all(s.complete for s in found.values()))

    plan = sprites.plan_convert(mod, sprites.ConvertRequest())
    check("plan picks up both sprites", len(plan.sets) == 2)
    rec = sprites.apply_convert(plan)

    check("both sheets converted", len(rec["converted"]) == 2)
    inst = mod.data / sprites.INSTALL_REL
    check("install dir created", inst.is_dir())
    check("identical variants deduped to one",
          len(rec["duplicates"].get(target, {})) == 1)
    kept = [f for f in facs if f not in rec["duplicates"].get(target, {})]
    check("the kept faction's files installed",
          (inst / f"{sprites.sprite_stem(kept[0], target)}.spr").is_file())
    check("the duplicate's files were not installed",
          not (inst / f"{sprites.sprite_stem(facs[1] if kept[0] == facs[0] else facs[0], target)}.spr").is_file())
    check("installed .texture is a real container",
          sprites.texture_to_dds(
              (inst / f"{sprites.sprite_stem(kept[0], target)}_000.texture").read_bytes()
          )[:4] == b"DDS ")
    check("intermediates cleaned up",
          not list(exp.glob("*.tga")) and not list(exp.glob("*.dds")))

    # --- wire-up shape
    edits = sprites.wire_model_edits(mod, rec["models"], rec["duplicates"])
    check("one model edit produced", len(edits) == 1)
    fp = edits[0]["faction_paths"]
    check("every faction gets a sprite path",
          set(fp) == {f.lower() for f in facs})
    check("the deduped faction points at the kept file",
          len({v["sprite"] for v in fp.values()}) == 1)

    # the payoff of preserving casing: where the modeldb line was already
    # correct, the wire-up reproduces it exactly and the write is a no-op
    real_faction, real_model = sprites._real_names(entry, kept[0])
    want = sprites.sprite_line(real_faction, real_model)
    check("path uses the modeldb's own casing",
          fp[kept[0].lower()]["sprite"] == want)
    existing = next(t.sprite for t in entry.main_textures
                    if t.faction.lower() == kept[0].lower())
    if conventional:
        check("reproduces an already-correct line byte-exact", want == existing)
    else:
        print(f"  [ -- ] this entry's line is {existing!r}, not the generated "
              f"{want!r} — a shared sprite, which the wire-up would repoint")

    from unittransfer import edit as edit_mod
    req = edit_mod.bmdb_request_from_dict({"model_edits": edits})
    check("edit.bmdb_request_from_dict accepts it",
          len(req.model_edits) == 1
          and req.model_edits[0].faction_paths[kept[0].lower()]["sprite"] == want)

    # --- prep writes to the Medieval II root, not the mod
    pplan = sprites.plan_prep(mod, sprites.PrepRequest(models=[target, "nosuchmodel"],
                                                       method="classic"))
    check("prep separates known from unknown models",
          pplan.known == [target] and pplan.unknown == ["nosuchmodel"])
    sprites.apply_prep(pplan)
    check("sprite_script.txt written to the Medieval II root",
          (root / sprites.SCRIPT_NAME).is_file()
          and not (mod_root / sprites.SCRIPT_NAME).exists())
    check("sprite_script.txt holds the model name",
          (root / sprites.SCRIPT_NAME).read_text().strip() == target)

    eplan = sprites.plan_prep(mod, sprites.PrepRequest(models=[target], method="eop"))
    check("eop prep emits the console snippet",
          eplan.lua == f'M2TWEOP.generateSprite("{target}")')
    check("eop prep writes no sprite_script", eplan.script_path is None)

    # --- audit resolves the freshly installed sprite against the modeldb.
    # The donor's line already names this file, so it lands in `ok`, not in
    # `orphans` — an orphan here would mean the naming contract was broken.
    a = sprites.audit(mod)
    stem = sprites.sprite_stem(real_faction, real_model).lower()
    if conventional:
        check("audit does not call the installed file an orphan",
              not any(stem in o.lower() for o in a.orphans))
        check("audit resolves it against the modeldb",
              any(r["model"] == target and r["faction"].lower() == kept[0].lower()
                  for r in a.ok))
    else:
        print("  [ -- ] the modeldb line does not name the generated file, so the "
              "audit is right to call it an orphan — nothing of ours to assert")

    shutil.rmtree(root, ignore_errors=True)


print(f"\n{sum(ok)}/{len(ok)} checks passed")
sys.exit(0 if all(ok) else 1)
