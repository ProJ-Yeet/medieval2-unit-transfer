"""The model decoder — unittransfer/mesh.py.

The .mesh format was reverse-engineered from the bytes (nothing we hold
describes it), so the job of this suite is to make that decode falsifiable
rather than merely plausible. Three kinds of check:

  * the REFERENCE models in Reference/TWCenter/ — seven files that ship with
    this repo, so the core of the suite runs on a machine with no game on it;
  * INVARIANTS that a wrong stride would break: every index inside the vertex
    pool, UVs in [0, 1], normals of unit length, LODs that get simpler, and
    the parse reaching the bone table with only the LOD block left over;
  * a SWEEP over whatever mods are installed, which is the check that matters
    most — thousands of models by hundreds of hands, and a layout mistake shows
    up as a decode failure rather than as quiet rubbish.

The sweep reports what it measured and asserts only our behaviour, per the rule
that a test must never fail because a mod ships a broken file.
"""
import math
import os
import struct
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import mesh
from tests import _realmod

ok = []


def check(label, cond):
    ok.append(bool(cond))
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}")


REFERENCE = (ROOT / "Reference" / "TWCenter" / "--- TOOLS n RESOURCES ---" /
             "TEMPLATE - Barded-Mailed Horses" / "Barded-Mailed Horses")


def reference_models():
    return sorted(REFERENCE.glob("*.mesh")) if REFERENCE.is_dir() else []


# ---------------------------------------------------------------------------
print("\nReference models (in this repo, no game needed)")

models = reference_models()
check(f"the seven template meshes are present ({len(models)} found)", len(models) == 7)

decoded = {}
for path in models:
    try:
        decoded[path.name] = mesh.read_mesh(path)
    except mesh.MeshError as e:
        check(f"{path.name} decodes", False)
        print(f"          {e}")
check(f"every one of them decodes ({len(decoded)}/{len(models)})",
      len(decoded) == len(models) and models)

horse = decoded.get("mount_barded_horse_lod0.mesh")
if horse is not None:
    check("13 groups, the five body parts and their variants",
          len(horse.groups) == 13)
    check("group names are the parts a model is built from",
          {g.name for g in horse.groups} == {"Hands", "Body", "Head", "Arms", "Legs"})
    check("texture groups carry the artist's mesh names",
          {"saddle", "horse_body_01", "horse_body_02", "horse_body_03"}
          <= {g.texture_group for g in horse.groups})
    check("3435 vertices in one shared pool", horse.vertices == 3435)
    check("6114 triangles across the groups", horse.triangles == 6114)
    check("23 bones, named as a horse's skeleton",
          len(horse.bones) == 23 and horse.bones[0] == "bone_H_Saddle")
    check("the closing block names itself characterlod0",
          horse.lod_name == "characterlod0")
    check("nothing was read that the decoder could not place", not horse.notes)
    # the sheet a part's art lands on, per the doubled-u convention: the
    # saddle is painted on the main texture, the rear barding cloth on the
    # attachment sheet, and the horse body itself genuinely spans both
    sheets = {g.texture_group: g.sheets for g in horse.groups}
    check("the saddle's art is on the main sheet", sheets.get("saddle") == "main")
    check("the rear barding cloth is on the attachment sheet",
          sheets.get("body_cloth_back_01") == "attach")
    check("the horse body crosses from one sheet onto the other",
          sheets.get("horse_body_01") == "both")

# ---------------------------------------------------------------------------
print("\nInvariants a wrong stride would break")


def invariants(m, label):
    """Every check that must hold for any model, however it was made."""
    top = m.vertices
    bad_index = next((g.name for g in m.groups
                      if g.indices and max(g.indices) >= top), None)
    check(f"{label}: every index lands inside the {top}-vertex pool",
          bad_index is None)
    check(f"{label}: three indices per triangle",
          all(len(g.indices) % 3 == 0 for g in m.groups))
    if m.uvs:
        check(f"{label}: one texture coordinate pair per vertex",
              len(m.uvs) == top * 2)
        # [0, 2] and not [0, 1]: the file normalises u over the two-sheet
        # PAIR (main 0..0.5, attachment 0.5..1) and the reader doubles it
        # into the convention IWTE and the Blender addon use — main in the
        # first tile, attachment in the second (see mesh._classify_sheets).
        # These horses use both tiles nearly edge to edge, so a reader that
        # forgot to double, or doubled twice, fails here.
        us = m.uvs[0::2]
        check(f"{label}: texture coordinates sit in the two u tiles",
              all(-0.001 <= u <= 2.001 for u in us)
              and all(-0.001 <= v <= 1.001 for v in m.uvs[1::2]))
        check(f"{label}: the u tiles are both used (max u {max(us):.2f})",
              max(us) > 1.5)
    if m.normals:
        check(f"{label}: one normal per vertex", len(m.normals) == top * 3)
        lengths = [math.sqrt(m.normals[i] ** 2 + m.normals[i + 1] ** 2
                             + m.normals[i + 2] ** 2)
                   for i in range(0, min(len(m.normals), 3000), 3)]
        # packed to a biased byte, so a unit vector comes back within about
        # 0.005 of length one; the loose old bound (0.9..1.2) let a wrong
        # decode through — the signed-byte misread averaged 1.08 and passed
        check(f"{label}: normals are unit vectors (mean length "
              f"{sum(lengths) / len(lengths):.3f})",
              0.98 <= sum(lengths) / len(lengths) <= 1.02)
    lo, hi = m.bounds()
    check(f"{label}: the model has a real size, not a point",
          all(hi[i] > lo[i] for i in range(3)))


if horse is not None:
    invariants(horse, "horse lod0")
    lods = [decoded.get(f"mount_barded_horse_lod{i}.mesh") for i in range(3)]
    if all(lods):
        counts = [m.triangles for m in lods]
        check(f"each LOD is simpler than the one before it ({counts})",
              counts[0] > counts[1] > counts[2])
        check("and every LOD keeps the same 13 groups",
              all(len(m.groups) == 13 for m in lods))
    check(f"only the undecoded LOD block is left over ({horse.trailer} bytes)",
          horse.trailer == 519)

# ---------------------------------------------------------------------------
print("\nFiles that are not models fail with a sentence, not a hang")

tmp = Path(tempfile.mkdtemp(prefix="ut_mesh_"))


def refuses(label, data, name="thing.mesh"):
    p = tmp / name
    p.write_bytes(data)
    try:
        mesh.read_mesh(p)
    except mesh.MeshError as e:
        check(f"{label} — {str(e)[:60]}…", True)
        return
    except Exception as e:                       # anything else is a defect
        check(f"{label} (raised {type(e).__name__} instead of MeshError)", False)
        return
    check(f"{label} (decoded it anyway)", False)


refuses("a text file", b"soldier some_unit, 60, 0, 1.0\n" * 40, "notes.txt")
refuses("an empty file", b"")
refuses("a .cas strat model", mesh.CAS_SIGNATURE + bytes(4096), "model.cas")
if models:
    whole = models[0].read_bytes()
    refuses("a mesh cut off halfway", whole[:len(whole) // 2])
    # a plausible header with a nonsense count: the guard has to catch it
    # before anything tries to allocate on it
    broken = bytearray(whole)
    struct.pack_into("<I", broken, 0x49, 0x7FFFFFFF)
    refuses("a mesh whose group count is corrupt", bytes(broken))

check("probe names a .mesh without decoding it",
      models and mesh.probe(models[0]) == "mesh")
check("probe names a .cas too",
      mesh.probe_bytes(mesh.CAS_SIGNATURE + bytes(64)) == "cas")
check("probe says nothing about a file that is neither",
      mesh.probe_bytes(b"not a model at all") == "")

# ---------------------------------------------------------------------------
print("\nEvery model in an installed mod")

mod = _realmod.pick("Divide_and_Conquer_EUR", "Third_Age_Reforged")
models_dir = mod / "data" / "unit_models"
if not models_dir.is_dir():
    print(f"  [skip] {mod.name} has no unpacked data/unit_models")
else:
    found = []
    for dirpath, _, names in os.walk(models_dir):
        found += [Path(dirpath) / n for n in names if n.lower().endswith(".mesh")]
    found.sort()
    #: capped so the run stays a test rather than a batch job, and sorted first
    #: so the same files are measured every time
    LIMIT = 900
    sample = found[:LIMIT]

    failures, notes, groups, verts = [], 0, 0, 0
    for path in sample:
        try:
            m = mesh.read_mesh(path)
        except mesh.MeshError as e:
            failures.append((path.name, str(e)))
            continue
        notes += len(m.notes)
        groups += len(m.groups)
        verts += m.vertices
        if m.vertices and any(g.indices and max(g.indices) >= m.vertices
                              for g in m.groups):
            failures.append((path.name, "an index points outside the vertex pool"))

    print(f"  {mod.name}: {len(found):,} models found, {len(sample):,} read, "
          f"{groups:,} groups and {verts:,} vertices between them")
    check(f"every one of the {len(sample):,} decodes", not failures)
    for name, why in failures[:5]:
        print(f"          {name}: {why[:90]}")
    check("and none of them read anything the decoder could not place", notes == 0)

    # the settlement meshes are the same format with no skeleton — worth
    # measuring separately, because "0 bones" is a real answer there and a
    # symptom anywhere else
    blockset = mod / "data" / "blockset"
    if blockset.is_dir():
        built = []
        for dirpath, _, names in os.walk(blockset):
            built += [Path(dirpath) / n for n in names if n.lower().endswith(".mesh")]
        built.sort()
        bad = []
        for path in built[:120]:
            try:
                m = mesh.read_mesh(path)
                if m.bones:
                    bad.append(f"{path.name} has bones")
            except mesh.MeshError as e:
                bad.append(f"{path.name}: {e}")
        print(f"  {mod.name}: {len(built):,} settlement meshes, {min(len(built), 120)} read")
        check("settlement meshes decode too, and none of them is rigged", not bad)
        for line in bad[:5]:
            print(f"          {line[:90]}")

    # a siege engine is the OTHER vertex format: three-word header, normals as
    # floats rather than packed bytes. Same reader, and the only thing that
    # settles the difference is _resolve_stride, so it is worth its own check.
    engines = sorted((mod / "data" / "siege_engines").glob("*.mesh"))
    if engines:
        floats, bad = 0, []
        for path in engines:
            try:
                m = mesh.read_mesh(path)
            except mesh.MeshError as e:
                bad.append(f"{path.name}: {e}")
                continue
            if m.normals and m.vertices:
                lengths = [math.sqrt(m.normals[i] ** 2 + m.normals[i + 1] ** 2
                                     + m.normals[i + 2] ** 2)
                           for i in range(0, min(len(m.normals), 900), 3)]
                if 0.9 <= sum(lengths) / len(lengths) <= 1.2:
                    floats += 1
        print(f"  {mod.name}: {len(engines)} siege engines read")
        check("siege engines decode — the static vertex format, not the skinned one",
              not bad)
        check(f"and their float normals come out unit length ({floats}/{len(engines)})",
              floats == len(engines) - len(bad))
        for line in bad[:5]:
            print(f"          {line[:90]}")

    # A file can hold several models back to back — the sky domes are the only
    # ones in either test mod, and which of them do varies by mod. So the check
    # is not "these are refused" (that would pass vacuously where none are) but
    # "each one either decodes or is refused BY NAME": a vague error here would
    # mean the multi-model case is being mistaken for a corrupt file.
    domes = sorted((mod / "data" / "globallighting" / "meshes").glob("*.mesh"))
    if domes:
        read, named, vague = 0, 0, []
        for path in domes:
            try:
                mesh.read_mesh(path)
                read += 1
            except mesh.MeshError as e:
                if "more than one model" in str(e):
                    named += 1
                else:
                    vague.append(f"{path.name}: {e}")
        print(f"  {mod.name}: {len(domes)} sky domes — {read} decoded, "
              f"{named} refused as multi-model, {len(vague)} otherwise")
        check("every sky dome either decodes or is refused by name, never vaguely",
              not vague and read + named == len(domes))
        for line in vague[:3]:
            print(f"          {line[:90]}")

for p in tmp.glob("*"):
    p.unlink()
tmp.rmdir()

print(f"\n{sum(ok)}/{len(ok)} checks passed")
sys.exit(0 if all(ok) else 1)
