"""Decode M2TW battle models (``.mesh``) to plain geometry the web UI can draw.

The format had to be read out of the bytes rather than out of a spec. Neither
reference we hold describes it:

* the Blender addon in ``Reference/Medieval-2-Toolkit/`` never parses a model —
  it writes an IWTE task file and shells out to ``IWTE.exe`` (``tasks/iwte_run``);
* the reference tool's ``src/lib/casCodec.js`` documents ``.mesh`` as "uint32
  version, uint32 submesh count, 32-byte vertices", which matches no real file.
  Its own comment ("attempting to parse anyway") is the tell.

What a ``.mesh`` really is
--------------------------
A **boost::serialization binary archive** — every file opens with
``16 00 00 00 "serialization::archive"``. Which means the byte layout is not a
flat struct: boost writes a class descriptor the FIRST time it meets a type
(class id, tracking flag, version) and only the class id on every later mention,
so the same record is two bytes longer the first time it appears. That is the
whole reason a fixed-stride reader cannot work, and it is what :class:`_Archive`
below exists to model.

The record layout on top of it::

    header, then a group count, then one record per group:
        string  group type        "Body"  "Head"  "primaryactive0"  "shield0"
        string  mesh name         "horse_body_01"  "saddle"
        uint32  triangle count
        uint16  index triples
        uint32  flag              0 required, 1 optional
    then the vertex pool the groups all index into:
        uint32  vertex count, then a stream per attribute:
        uint32  stream type, uint32 count, count * stride bytes
    then a bounding sphere and a bone table:
        uint32  bone count, then (uint32 name length, chars, uint32 index)
    then a per-LOD block, named but not decoded — see below.

**Indices are global.** Every group indexes one shared vertex pool, so a group
is a face range, not a mesh of its own. The variants a unit shows at random
(``horse_body_01`` / ``_02`` / ``_03``) are separate groups over that same pool.

**A model is painted from TWO textures GLUED SIDE BY SIDE, and its UVs address
the pair.** Its modeldb entry names a main texture and an attachment texture
per faction, and the game treats them as one image twice as wide: main on the
left, attachment on the right. **In the file, u is normalised over that PAIR**:
u 0..0.5 is the main sheet, u 0.5..1 the attachment sheet, and the pair tiles
with period 1. Measured, not assumed: across 900 models in one mod, 1,092 of
the 1,179 weapon and shield groups — the art an attachment sheet exists for —
sit in u 0.5..1, with bodies, heads and beards packed into 0..0.5.

Everyone downstream of IWTE speaks the DOUBLED version of that coordinate —
the Blender addon keeps main-texture objects in u 0..1 and attach objects in
u 1..2 (``export_checks.checkUVSpace``), because IWTE doubles u when it turns
a .mesh into a scene — so :func:`_read_streams` doubles u the same way and
everything this module hands out uses the community convention: main 0..1,
attachment 1..2, tiling with period 2. Nobody has to know the file stores it
halved except this docstring.

A renderer therefore does not choose a sheet, and must not: it glues the two
into one texture, samples at ``u/2`` with REPEAT wrapping, and the coordinate
does the rest. Choosing per group is wrong for the groups whose art crosses
the boundary (a barded horse's Body group spans both sheets), and normalising
a coordinate into 0..1 throws the tiling away. :func:`_classify_sheets`
records which sheet a group's art lands on for the sake of SAYING so; it is a
label, not an instruction.

**The models are left-handed.** Right is +X, up is +Y and forward is +Z, which
is the Direct3D convention and the opposite of OpenGL's. Measured, not assumed:
a horse's head sits at +Z and its tail at -Z, and on a soldier the ``shield0``
group sits at -X with ``primaryactive0`` at +X — shield in the left hand,
weapon in the right. Anything drawing these coordinates in a right-handed
viewer has to negate one axis or every model comes out mirrored.

**Models stand up the Y axis**, and nothing in the file says so. Measured rather
than assumed: across six Divide and Conquer soldiers the ``Head`` group's
centroid sits about 1.4 above the ``Legs`` group's in Y and level with it in X
and Z, and plotting a horse with Z across and Y up draws a horse. A viewer that
orbits the wrong axis lays every man in the game on his side, so it is worth
knowing before drawing anything.

Stream types, worked out by stride and by what the numbers turn out to be:

======  =======  =========================================================
type    stride   meaning
======  =======  =========================================================
0       12       position, 3 floats
1        8       bone weights, 2 floats (they sum to 1)
2        4       bone indices, 4 bytes
3        4 / 12  normal, either packed or three floats — see below
4        8       texture coordinates, 2 floats; u stored halved — see above
8, 9     4       colour and lighting channels, settlement meshes only
10      4 / 12   tangent, written like the normal
11      4 / 12   binormal, written like the normal
13, 14   4       two more settlement-only channels
======  =======  =========================================================

**There are two vertex formats sharing these type numbers.** A skinned model —
soldiers, mounts, settlements — packs the normal, tangent and binormal
D3DCOLOR-style: unsigned bytes biased around 127.5, z-y-x order, pad byte last
(see :func:`_unpack_normals` for how that was established). A static one —
siege engines, sky domes — writes the same three as three floats each. Nothing in a stream header
says which, so :func:`_resolve_stride` settles it by trying both and keeping the
one the rest of the file can be read from. The same split shows up in the
archive header, which is four words long for a skinned model and three for a
static one (:func:`_read_header`).

Skinning is out of scope for V2 — a static pose is enough for the viewer — so
the weight and bone-index streams are read for the byte count and then dropped.
Bone NAMES are kept: they cost nothing and they say what a model is rigged to.
A settlement mesh under ``blockset`` is the same format with no bones at all; a
siege engine has a handful (``bone_Lwheel``, ``bone_Rwheel``).

How far the decode goes, and how we know it is right
----------------------------------------------------
Everything from the first byte to the end of the bone table is read as a
grammar: no searching, no strides taken on faith. Reaching the bone table at
all is the proof, because a single wrong stride anywhere before it — one index
block, one vertex stream — puts the table outside the short window it is looked
for in, and the count read there lands on nonsense instead of a bone.

What is NOT decoded is the block that closes the file: a per-LOD record of
material and attachment settings, 519 bytes in every unit model measured. Its
name is read (``characterlod0``) and its length recorded on
:attr:`MeshFile.trailer`; nothing the viewer draws is inside it, so decoding it
was not worth another round of archaeology. A trailer larger than
:data:`MAX_TRAILER` is treated as a decode that stopped early, not as a big
block.

The one place the reader searches rather than parses is the gap between vertex
streams, where boost's bookkeeping changes length depending on which classes
the archive has already introduced — see :func:`_find_stream`, which explains
what constrains the search.

``tests/test_mesh.py`` holds this to the reference models in ``Reference/`` and
to every model in whatever mods are installed. **4,700 of the 4,702 .mesh files
in Divide and Conquer and Third Age Reforged decode** with every invariant
holding — every unit model, mount, settlement piece and siege engine in both.

The two that do not are sky domes under ``globallighting``, and they are
refused rather than half-read: a file can hold SEVERAL models one after another,
and this reader takes a single-model file. The tell is the closing block — a
model that ends names it (``characterlod0``), and one followed by another model
has no name to give, which is how :func:`_finish` tells the two apart and says
which it found.

What a ``.cas`` is, and why there is no reader for one here
-----------------------------------------------------------
:func:`probe` tells a strat-map ``.cas`` from a battle ``.mesh``, and
:func:`read_mesh` refuses one by name rather than by crashing — but the
geometry is not decoded, because a ``.cas`` is not a variation on this format,
it is a different one. It opens with the float ``3.2``, and what follows is a
whole 3ds-max scene export: a frame rate and a table of key times, a node
hierarchy (``Scene Root``, then the bones), animation tracks over those nodes,
then the mesh, then the material and its texture — ``textures\\Daritai.tga`` sits
in the last 60 bytes of the file. Reverse-engineering it is a second job of the
size this one was, and it belongs to the campaign map's strat preview, which is
where the roadmap always had it. Recorded here so that phase starts from what is
known rather than from nothing.
"""
from __future__ import annotations

import json
import struct
from array import array
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

#: The signature every M2TW .mesh opens with.
BOOST_SIGNATURE = b"serialization::archive"

#: Version float a strat .cas opens with (3.2, as little-endian float bytes).
CAS_SIGNATURE = b"\xcd\xccL@"

#: Bytes per vertex in each vertex stream, by the stream's type number, as the
#: lengths that type is ever written at. Types 8, 9, 13 and 14 only turn up in
#: the settlement meshes under ``blockset`` — colour and lighting channels a
#: building has and a soldier does not.
#:
#: Types 3, 10 and 11 have two lengths because two vertex formats share these
#: numbers: a skinned model packs the normal, tangent and binormal into three
#: biased bytes and a pad (see :func:`_unpack_normals`), a static one writes
#: three floats. See :func:`_resolve_stride` for how a file's is settled.
STREAM_STRIDE: Dict[int, Tuple[int, ...]] = {
    0: (12,), 1: (8,), 2: (4,), 4: (8,),
    3: (4, 12), 10: (4, 12), 11: (4, 12),
    8: (4,), 9: (4,), 13: (4,), 14: (4,),
}

POSITION_STREAM = 0
NORMAL_STREAM = 3
UV_STREAM = 4

#: A sanity ceiling on any count read out of the file, so a corrupt uint32
#: cannot make us try to allocate gigabytes before we notice it is nonsense.
MAX_COUNT = 4_000_000


class MeshError(Exception):
    """A model file could not be read. Carries a sentence, not a traceback."""


# ---------------------------------------------------------------------------
# result types


@dataclass
class MeshGroup:
    """One named part of a model: a face range over the file's vertex pool.

    The three fields the file gives a group are exactly the three IWTE asks a
    modder for, which is how we know what they are rather than guessing. One
    mod ships a mesh whose group type is IWTE's own unanswered prompt, saved
    verbatim into the file::

        'For the mesh named: cloak_1, enter a group type: cloak'
        'For the mesh named: cloak_1, enter a group flag (0 for required,
         1 for optional.): 0'

    So: :attr:`name` is the group TYPE, :attr:`texture_group` is the MESH NAME,
    and :attr:`flag` is required/optional. Which is also where the Blender
    addon's ``objectname__comment__opt`` convention comes from — IWTE joins the
    type and the mesh name with ``__`` and appends ``__opt`` when the flag is 1.
    """

    #: group TYPE — the slot the game fills: Body, Head, Legs, primaryactive0,
    #: shield0, Attachments1. Several groups sharing a type are variants and
    #: the game picks one per soldier.
    name: str
    #: the artist's MESH NAME within that type: horse_body_01, head_cloth_02.
    texture_group: str
    indices: array                 # 'H', 3 per triangle, into the vertex pool
    #: 0 = required, 1 = optional. An optional part is shown on some soldiers
    #: and not others; it is the ``__opt`` marker in the addon's object names.
    flag: int = 0
    #: Which of the entry's two textures this group's art lands on:
    #: ``"main"``, ``"attach"``, or ``"both"`` for one piece of art that
    #: crosses from one onto the other. Not a field in the file and NOT a
    #: rendering instruction — the UVs already address both sheets as one
    #: image, and a renderer picking a sheet per group would have to be wrong
    #: about every ``"both"``. This is for saying what a part uses, nothing
    #: more. See :func:`_classify_sheets`.
    sheets: str = "main"

    @property
    def triangles(self) -> int:
        return len(self.indices) // 3

    @property
    def optional(self) -> bool:
        return self.flag == 1


@dataclass
class MeshFile:
    """A decoded model. One vertex pool, groups indexing into it."""

    source: str
    format: str                                  # "mesh" or "cas"
    positions: array = field(default_factory=lambda: array("f"))
    normals: array = field(default_factory=lambda: array("f"))
    uvs: array = field(default_factory=lambda: array("f"))
    groups: List[MeshGroup] = field(default_factory=list)
    bones: List[str] = field(default_factory=list)
    #: the closing block's name: characterlod0, buildingalphaskinnedlod0, …
    lod_name: str = ""
    #: bytes after the bone table — the LOD/attachment block, see the module
    #: docstring. Measured, deliberately not decoded.
    trailer: int = 0
    #: anything read but not understood, said out loud rather than swallowed
    notes: List[str] = field(default_factory=list)

    @property
    def vertices(self) -> int:
        return len(self.positions) // 3

    @property
    def triangles(self) -> int:
        return sum(g.triangles for g in self.groups)

    def bounds(self) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
        """``(min, max)`` corners of the model's box, ``((0,0,0),(0,0,0))`` if empty."""
        p = self.positions
        if not p:
            return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
        return (
            (min(p[0::3]), min(p[1::3]), min(p[2::3])),
            (max(p[0::3]), max(p[1::3]), max(p[2::3])),
        )

    def summary(self) -> str:
        lo, hi = self.bounds()
        size = tuple(round(hi[i] - lo[i], 3) for i in range(3))
        return (f"{Path(self.source).name}: {len(self.groups)} groups, "
                f"{self.vertices} vertices, {self.triangles} triangles, "
                f"{len(self.bones)} bones, size {size[0]}x{size[1]}x{size[2]}")


# ---------------------------------------------------------------------------
# the archive reader


class _Archive:
    """A cursor over a boost binary archive, with its class bookkeeping.

    The only subtlety worth stating: :meth:`obj` is how a pointer to a tracked
    object reads, and it is two bytes longer the first time a class id turns up
    (the tracking flag and the class version follow it). Miss that and every
    offset after the first record is wrong — which is exactly the shape of bug
    that leaves a parser producing plausible-looking rubbish.
    """

    def __init__(self, data: bytes, source: str):
        self.d = data
        self.p = 0
        self.source = source
        self.seen: set = set()

    # -- primitives ---------------------------------------------------------

    def _need(self, n: int) -> None:
        if self.p + n > len(self.d):
            raise MeshError(
                f"{Path(self.source).name} ends early: wanted {n} more bytes at "
                f"offset {self.p} of {len(self.d)}")

    def u8(self) -> int:
        self._need(1)
        v = self.d[self.p]
        self.p += 1
        return v

    def u16(self) -> int:
        self._need(2)
        v = struct.unpack_from("<H", self.d, self.p)[0]
        self.p += 2
        return v

    def u32(self) -> int:
        self._need(4)
        v = struct.unpack_from("<I", self.d, self.p)[0]
        self.p += 4
        return v

    def f32(self) -> float:
        self._need(4)
        v = struct.unpack_from("<f", self.d, self.p)[0]
        self.p += 4
        return v

    def peek16(self) -> int:
        return struct.unpack_from("<H", self.d, self.p)[0] if self.p + 2 <= len(self.d) else -1

    def count(self, what: str) -> int:
        """A uint32 that is about to be used as a length. Guarded."""
        n = self.u32()
        if n > MAX_COUNT:
            raise MeshError(
                f"{Path(self.source).name} asks for {n:,} {what} at offset "
                f"{self.p - 4} — not a model file this tool understands")
        return n

    def text(self) -> str:
        n = self.count("characters")
        self._need(n)
        s = self.d[self.p:self.p + n].decode("latin-1")
        self.p += n
        return s

    def blob(self, n: int) -> bytes:
        self._need(n)
        b = self.d[self.p:self.p + n]
        self.p += n
        return b

    # -- boost object bookkeeping ------------------------------------------

    def obj(self) -> int:
        """Read a pointer to a tracked object; return its class id.

        A run of zero words can precede the class id (boost's optional-class-id
        slots, plus the odd empty field that lands in the same place). No real
        class id is zero, so consuming them until a non-zero word appears is
        unambiguous — and the byte-exhaustion check at the end of the parse is
        what proves we never ate a byte that meant something.
        """
        while self.peek16() == 0:
            self.u16()
        cid = self.u16()
        if cid not in self.seen:
            self.seen.add(cid)
            self.u8()          # tracking level
            self.u8()          # class version
        self.u32()             # object id
        return cid

    def ref(self) -> int:
        """A pointer to a class the archive has already introduced.

        Used only after the vertex streams. :func:`_find_stream` jumps over the
        bookkeeping between streams rather than reading it, so from there on
        :attr:`seen` no longer knows which classes have been declared — and the
        classes the tail names are exactly the ones those skipped preambles
        introduced. Reading them as plain references is right for every model
        measured, and wrong loudly rather than quietly if it ever is not: the
        bone count that follows lands on nonsense and :meth:`count` says so.
        """
        while self.peek16() == 0:
            self.u16()
        cid = self.u16()
        self.u32()
        return cid

    def at_end(self) -> bool:
        return self.p >= len(self.d)


# ---------------------------------------------------------------------------
# .mesh


def _looks_like_descriptor(a: _Archive) -> bool:
    """True if the cursor is on ``u16 0`` and then a boost class descriptor."""
    if a.p + 8 > len(a.d):
        return False
    zero, cid, tracking, version = struct.unpack_from("<HHBB", a.d, a.p)
    return zero == 0 and 0 < cid <= 64 and tracking <= 1 and version <= 8


def _read_header(a: _Archive) -> None:
    """The archive signature and the handful of words before the first class.

    There are four of those words in a skinned model and three in a static one
    (siege engines, the skydome, anything with no skeleton). Rather than guess
    from the file's folder, take the length that leaves the cursor on a class
    descriptor — a wrong choice puts it on a length or a flag instead, which
    :func:`_looks_like_descriptor` can see.
    """
    sig = a.text()
    if sig.encode("latin-1") != BOOST_SIGNATURE:
        raise MeshError(f"{Path(a.source).name} is not a .mesh "
                        f"(expected a boost archive, found {sig[:32]!r})")
    a.blob(5)                  # library version + the archive's type sizes
    mark = a.p
    for words in (4, 3):
        a.p = mark
        for _ in range(words):
            a.u32()
        if _looks_like_descriptor(a):
            return
    raise MeshError(f"{Path(a.source).name}: the archive header is not a shape "
                    f"this tool knows ({a.d[mark:mark + 20].hex(' ')})")


def _read_groups(a: _Archive) -> List[MeshGroup]:
    a.u16()
    a.obj()
    a.u16()
    a.obj()
    a.u16()
    n = a.count("groups")
    groups: List[MeshGroup] = []
    for i in range(n):
        a.obj()
        name = a.text()
        texture_group = a.text()
        if i == 0:
            a.u16()            # the index container's descriptor, written once
        tris = a.count("triangles")
        idx = array("H")
        idx.frombytes(a.blob(tris * 6))
        flag = a.u32()
        groups.append(MeshGroup(name, texture_group, idx, flag))
        a.u8()
        a.obj()                # the group's two child objects; no geometry in
        a.obj()                # them, but they have to be stepped over exactly
    return groups


#: How far ahead of a finished stream the next one's header may sit. The gap is
#: boost's own bookkeeping — object ids and class descriptors — and the longest
#: measured across every model in two mods and the reference set is 40 bytes.
STREAM_GAP = 96


def _find_stream(a: _Archive, verts: int,
                 got: Sequence[int]) -> Optional[Tuple[int, int]]:
    """``(type, offset of the data)`` for the next stream, or ``None``.

    The bytes between two streams are boost's class bookkeeping, and their
    length depends on which classes the archive has already introduced — the
    first stream sits 40 bytes past the previous block, a later one 26. Rather
    than model class definitions we do not have, look ahead for the header
    itself: a known stream type, this file's exact vertex count, and room for
    the data. A count sometimes follows its type across a two-byte class
    descriptor, so both spacings are allowed.

    Three things keep the search honest: the window is small, a type already
    read is not matched twice, and every stream after this one has to be found
    from wherever this one ends — so a coincidence does not survive the chain.
    """
    limit = min(a.p + STREAM_GAP, len(a.d) - 8)
    for off in range(a.p, limit + 1, 2):
        stype = struct.unpack_from("<I", a.d, off)[0]
        if stype not in STREAM_STRIDE or stype in got:
            continue
        for skip in (4, 6):    # count straight after the type, or past a marker
            if struct.unpack_from("<I", a.d, off + skip)[0] != verts:
                continue
            start = off + skip + 4
            if start + verts * min(STREAM_STRIDE[stype]) <= len(a.d):
                return stype, start
    return None


def _resolve_stride(a: _Archive, stype: int, start: int, verts: int,
                    got: Sequence[int]) -> Optional[int]:
    """Which of a type's possible strides this file uses.

    A skinned model packs its normal, tangent and binormal into three signed
    bytes and a pad; a static one — a siege engine, the skydome — writes the
    same three attributes as three floats. Same type number, four bytes per
    vertex against twelve. Nothing in the stream header says which, so try
    them and keep the one that leaves the cursor somewhere the rest of the
    file can be read from: another stream header inside the window, or the
    bounding sphere and bone table that close the model.
    """
    options = STREAM_STRIDE[stype]
    if len(options) == 1:
        return options[0]
    for stride in options:
        end = start + verts * stride
        if end > len(a.d):
            continue
        probe = _Archive(a.d, a.source)
        probe.p = end
        if _find_stream(probe, verts, got) is not None:
            return stride
        probe.p = end
        try:
            _read_bones(probe, MeshFile(source=a.source, format="mesh"))
        except MeshError:
            continue
        if 0 <= len(a.d) - probe.p <= MAX_TRAILER:
            return stride
    return None


def _read_streams(a: _Archive, out: MeshFile) -> None:
    """The vertex pool: a count, then one stream per vertex attribute."""
    a.obj()
    a.obj()
    verts = a.count("vertices")
    a.u16()
    a.u32()                    # weights per vertex (2 in every file measured)

    packed: Dict[int, bytes] = {}
    while True:
        found = _find_stream(a, verts, tuple(packed))
        if found is None:
            break
        stype, start = found
        stride = _resolve_stride(a, stype, start, verts, tuple(packed) + (stype,))
        if stride is None:
            out.notes.append(f"vertex stream type {stype} has a length this "
                             f"tool could not settle; it was left out")
            break
        a.p = start
        packed[stype] = a.blob(verts * stride)

    if POSITION_STREAM not in packed:
        raise MeshError(f"{Path(a.source).name} has no vertex positions — "
                        f"found streams {sorted(packed) or 'none'}")
    out.positions = array("f")
    out.positions.frombytes(packed[POSITION_STREAM])
    if UV_STREAM in packed:
        out.uvs = array("f")
        out.uvs.frombytes(packed[UV_STREAM])
        # The file normalises u over the two-sheet PAIR: main is 0..0.5 and
        # the attachment sheet 0.5..1. Doubling here is what puts every UV
        # this module hands out into the convention IWTE and the Blender
        # addon speak — main in u 0..1, attachment in u 1..2 — see the
        # module docstring. v is per sheet already and stays as written.
        for i in range(0, len(out.uvs), 2):
            out.uvs[i] *= 2.0
    if NORMAL_STREAM in packed:
        out.normals = _unpack_normals(packed[NORMAL_STREAM], verts)
    elif packed:
        out.notes.append("no normal stream; the viewer will have to derive them")


def _unpack_normals(raw: bytes, verts: int) -> array:
    """The normal stream as floats, whichever of its two forms it is in.

    Twelve bytes a vertex are already three floats. Four are a D3DCOLOR-style
    packed vector: unsigned bytes biased around 127.5 (``b / 255 * 2 - 1``),
    laid out BGRA-fashion — **x in the third byte, y in the second, z in the
    first**, and the fourth a pad that is always zero. Settled by measurement,
    not guesswork: decoded this way the vectors come back unit length to
    within 0.004 and agree with the face normals computed from the positions
    (mean dot +0.9, 4 of 6,783 opposed on the model measured); read as signed
    bytes in x-y-z order — the first guess — their lengths ranged 0.74..1.43
    and half of them pointed against their own faces, which on screen was a
    model covered in dark patches with hard seams between them.
    """
    if verts and len(raw) // verts == 12:
        out = array("f")
        out.frombytes(raw)
        return out
    out = array("f", bytes(verts * 12))
    for v in range(verts):
        for c in range(3):
            out[v * 3 + c] = raw[v * 4 + (2 - c)] / 255.0 * 2.0 - 1.0
    return out


def _read_bones(a: _Archive, out: MeshFile) -> None:
    """The bounding sphere and bone table that follow the vertex streams.

    A settlement mesh under ``blockset`` has no skeleton and writes a count of
    zero here — same grammar, empty table, and no class descriptor because
    there are no entries to describe.
    """
    a.ref()
    a.ref()
    a.blob(10)
    for _ in range(4):
        a.f32()                # bounding sphere: centre and radius
    a.u32()
    n = a.count("bones")
    if n:
        a.u16()                # the table's class descriptor, once
    for _ in range(n):
        out.bones.append(a.text())
        a.u32()                # the bone's index, which is its position anyway


def read_mesh(path) -> MeshFile:
    """Decode a battle model. Raises :class:`MeshError` on anything else."""
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError as e:
        raise MeshError(f"could not read {path.name}: {e}") from e
    if not data.startswith(struct.pack("<I", len(BOOST_SIGNATURE)) + BOOST_SIGNATURE):
        raise MeshError(_wrong_format(path, data, "mesh"))

    a = _Archive(data, str(path))
    out = MeshFile(source=str(path), format="mesh")
    _read_header(a)
    out.groups = _read_groups(a)
    _read_streams(a, out)
    _read_bones(a, out)
    out.lod_name = _read_lod_name(a)
    _finish(a, out)
    _classify_sheets(out)
    return out


#: A texel's worth of slack at a sheet boundary, for LABELLING only — never
#: for sampling. It is the addon's own UV-space tolerance, and it is about one
#: texel of a 1024 sheet, which is the point.
TILE_EPS = 0.001


def _classify_sheets(m: MeshFile) -> None:
    """Say which of the entry's two textures each group's art lands on.

    A modeldb entry names two textures per faction, a main one and an
    attachment one, and **the game lays them out as ONE image twice as wide** —
    main on the left, attachment on the right — which is what the mesh's single
    UV set addresses. In the coordinates this module hands out (u doubled by
    :func:`_read_streams` from the file's pair-normalised form), u 0..1 is the
    main sheet, u 1..2 is the attachment sheet, and the pair repeats in both
    axes outside that. The Blender addon
    works in the same space: ``export_checks.checkUVSpace`` keeps main-texture
    objects in the first tile and attach-texture objects "in the tile one unit
    to the right", and its importer splits the imported materials into
    ``__main`` and ``__attach`` on the same line.

    Nothing here is a rendering instruction. A renderer samples the glued pair
    at ``u/2`` and the coordinate picks the sheet by itself; it must NOT choose
    per group, because a group's art can cross the boundary — 124 of this mod's
    groups do — and picking one sheet for such a group is wrong about half of
    it. Nor may it wrap a coordinate into 0..1: 112 groups have u below zero
    and 268 have v outside 0..1, and those tile on purpose.

    What this is for is the answer to "what does this part use", which the
    viewer's part list shows. It is worked out the way the shader samples — the
    half of the glued pair a coordinate lands in is ``u mod 2``, below 1 for
    main and at or above 1 for attachment — so the label cannot disagree with
    the picture about anything you could see.

    The range is pulled in by :data:`TILE_EPS` first, and that is not a fudge.
    Meshes routinely have an edge vertex a fraction over a boundary — the
    ``avari_horselords`` body runs to u = -0.004 — and the render does sample
    the far sheet's last texel column there, exactly as the game does. But it
    is one column under one vertex, and calling the whole body "both sheets"
    over it tells the reader something false about the part.
    """
    if not m.uvs:
        return
    uvs = m.uvs
    half = lambda u: 1 if u % 2.0 >= 1.0 else 0
    for g in m.groups:
        if not g.indices:
            continue
        lo = hi = uvs[g.indices[0] * 2]
        for v in g.indices:
            u = uvs[v * 2]
            if u < lo:
                lo = u
            elif u > hi:
                hi = u
        # a group flatter than the slack itself (helmet_backface is a single
        # point in UV space) would come out inside out, so it is judged on its
        # midpoint instead of on a range it does not have
        if hi - lo <= 2 * TILE_EPS:
            a = b = half((lo + hi) / 2)
        else:
            a, b = half(lo + TILE_EPS), half(hi - TILE_EPS)
        g.sheets = "both" if a != b else ("attach" if a else "main")


def _read_lod_name(a: _Archive) -> str:
    """The name of the block that closes the file — ``characterlod0`` and the
    like. Read for the name alone: the rest of the block is per-LOD material
    and attachment settings, and nothing the viewer draws is in it."""
    mark = a.p
    try:
        a.ref()
        a.ref()
        a.u32()
        a.u32()
        a.u16()
        a.ref()
        name = a.text()
    except MeshError:
        a.p = mark
        return ""
    if not name or not all(32 <= ord(c) < 127 for c in name):
        a.p = mark
        return ""
    a.p = mark
    return name


# ---------------------------------------------------------------------------
# shared tail checks


#: The LOD/attachment block after the bone table. Roomy, because the point of
#: the ceiling is to catch a decode that stopped early, not to police the block.
MAX_TRAILER = 64 * 1024


def _finish(a: _Archive, out: MeshFile) -> None:
    """The proof: everything up to the bone table has to be accounted for.

    Reaching the bone table at all means every index block and every vertex
    stream before it was exactly the size the reader believed, because a single
    wrong stride anywhere would put the table out of the window it is looked
    for in. What follows the table is the per-LOD attachment block; nothing the
    viewer draws is in it, so it is measured rather than decoded, and an
    implausibly large one is treated as a decode that stopped early.
    """
    out.trailer = len(a.d) - a.p
    if out.trailer > MAX_TRAILER:
        # A model that ends here names its closing block. One that does not is
        # a file holding SEVERAL models back to back — the sky domes under
        # globallighting do this — and the geometry read so far is only the
        # first of them. Saying which of the two it is beats one vague message
        # for both.
        if not out.lod_name:
            raise MeshError(
                f"{Path(a.source).name} holds more than one model, one after "
                f"another; this tool reads a single-model file. The first has "
                f"{out.vertices:,} vertices and {out.triangles:,} triangles, "
                f"and {out.trailer:,} bytes follow it")
        raise MeshError(
            f"{Path(a.source).name}: {out.trailer:,} of {len(a.d):,} bytes left "
            f"after the bone table — the layout does not match, so the geometry "
            f"cannot be trusted")
    top = len(out.positions) // 3
    for g in out.groups:
        if g.indices and max(g.indices) >= top:
            raise MeshError(
                f"{Path(a.source).name}: group {g.name!r}/{g.texture_group!r} "
                f"indexes vertex {max(g.indices)} of {top}")


def _wrong_format(path: Path, data: bytes, wanted: str) -> str:
    found = probe_bytes(data)
    if found == wanted:
        return f"{path.name} is a {wanted} file but its header is damaged"
    if found == "cas":
        return (f"{path.name} is a .cas strat-map model, not a battle .mesh — "
                f"this tool does not read .cas geometry yet")
    return (f"{path.name} is not a Medieval II model file "
            f"(first bytes: {data[:8].hex(' ') or 'empty'})")


def probe_bytes(data: bytes) -> str:
    """``"mesh"``, ``"cas"`` or ``""`` from a file's opening bytes."""
    if data.startswith(struct.pack("<I", len(BOOST_SIGNATURE)) + BOOST_SIGNATURE):
        return "mesh"
    if data[:4] == CAS_SIGNATURE:
        return "cas"
    return ""


def probe(path) -> str:
    """What kind of model a file is, without decoding it."""
    try:
        with open(path, "rb") as fh:
            return probe_bytes(fh.read(32))
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# what the viewer asks for


#: Magic the geometry payload opens with, so a truncated or mis-routed response
#: is caught in the page rather than drawn as noise.
PAYLOAD_MAGIC = b"M2GT"


def entry_view(entry, data_dir: Path) -> dict:
    """A modeldb entry as the viewer's picker needs it: LODs and skins.

    Cheap on purpose — it stats files and decodes nothing, because this is what
    the dialog opens on and the geometry is a second request. ``exists`` is the
    interesting column: a mod that references vanilla art is normal, and the
    viewer has to say "not in this mod" rather than draw nothing and look broken.
    """
    lods = []
    for i, (rel, distance) in enumerate(entry.lods):
        rel = (rel or "").strip().replace("\\", "/")
        path = data_dir / rel if rel else None
        lods.append({
            "index": i,
            "rel": rel,
            "distance": distance,
            "exists": bool(rel) and path.is_file(),
        })
    # A skin is a PAIR of files, not one file. Every faction on the entry gets
    # a main texture and an attachment texture, and a model draws from BOTH at
    # once — the groups whose UVs sit in the second tile take the attachment
    # sheet (see _classify_attachments). Offering the two files as separate
    # choices, which is what listing them one row per file did, means whichever
    # one you pick paints the whole model and half of it comes out wrong.
    #
    # Still deduplicated, because an entry commonly lists twenty-nine factions
    # against one pair and a picker with twenty-nine identical rows tells you
    # nothing. The key is the pair, so two factions that share a main texture
    # but differ in their attachment stay two rows.
    def by_faction(group):
        out = {}
        for t in group:
            rel = (t.texture or "").strip().replace("\\", "/")
            if rel and rel != "0":
                out.setdefault(t.faction, rel)
        return out

    main_of, attach_of = by_faction(entry.main_textures), by_faction(entry.attach_textures)
    skins: List[dict] = []
    by_pair: Dict[tuple, dict] = {}
    for faction in list(main_of) + [f for f in attach_of if f not in main_of]:
        main = main_of.get(faction, "")
        attach = attach_of.get(faction, "")
        row = by_pair.get((main.lower(), attach.lower()))
        if row is None:
            row = {
                # `rel`/`exists` are the MAIN texture: it is what names the
                # skin and what the model is mostly painted in
                "rel": main, "exists": bool(main) and (data_dir / main).is_file(),
                "attach": attach,
                "attach_exists": bool(attach) and (data_dir / attach).is_file(),
                "factions": [],
            }
            by_pair[(main.lower(), attach.lower())] = row
            skins.append(row)
        if faction not in row["factions"]:
            row["factions"].append(faction)
    return {"name": entry.name, "scale": entry.scale, "lods": lods,
            "skins": skins, "skeletons": entry.skeletons()}


def geometry_payload(m: MeshFile) -> bytes:
    """A decoded model as one binary response the page can use directly.

    JSON would be the obvious thing and is the wrong thing here: a soldier is a
    few thousand vertices, and spelling those floats out as text is roughly six
    times the bytes and a parse on top. This is a JSON header for the parts that
    are structure, then the arrays raw, so the page hands each one straight to a
    typed array with no copying.

    Layout, little-endian throughout::

        "M2GT"  uint32 header length (the header is padded to a multiple of 4)
        header  JSON: counts, groups with their index ranges, bones, bounds
        float32 positions, 3 per vertex
        float32 normals,   3 per vertex   (omitted if the model has none)
        float32 uvs,       2 per vertex   (omitted if the model has none)
        uint16  indices, every group's in the order the header lists them
    """
    offset, groups = 0, []
    for g in m.groups:
        groups.append({"name": g.name, "texture_group": g.texture_group,
                       "flag": g.flag, "optional": g.optional, "sheets": g.sheets,
                       "start": offset, "count": len(g.indices)})
        offset += len(g.indices)
    lo, hi = m.bounds()
    header = {
        "vertices": m.vertices,
        "triangles": m.triangles,
        "groups": groups,
        "bones": m.bones,
        "lod_name": m.lod_name,
        "has_normals": bool(m.normals),
        "has_uvs": bool(m.uvs),
        "min": list(lo),
        "max": list(hi),
        "notes": m.notes,
        "source": Path(m.source).name,
    }
    raw = json.dumps(header).encode("utf-8")
    raw += b" " * (-len(raw) % 4)        # keep the float arrays 4-byte aligned
    out = [PAYLOAD_MAGIC, struct.pack("<I", len(raw)), raw,
           m.positions.tobytes()]
    if m.normals:
        out.append(m.normals.tobytes())
    if m.uvs:
        out.append(m.uvs.tobytes())
    for g in m.groups:
        out.append(g.indices.tobytes())
    return b"".join(out)
