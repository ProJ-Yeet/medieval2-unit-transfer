"""Parser/writer for battle_models.modeldb (M2TW).

The file is a length-prefixed token stream ("serialization archive"):
  * a string is stored as ``<byte-length> <that many chars>``
  * numbers are bare whitespace-delimited tokens

Header:  ``<len> serialization::archive 3 0 0 0 0 <COUNT> 0 0``
where ``<len>`` is the length of the literal "serialization::archive" and
``<COUNT>`` = number-of-real-models + 1 (the extra one is the leading ``blank`` entry).

Verified end-to-end against Third_Age_Reforged (1026 models) and
Divide_and_Conquer_EUR (2192 models): both parse to a clean EOF and round-trip
byte-exact through :meth:`ModelDb.to_text`.

For every entry we keep the *raw source substring* that produced it, so a
transfer appends a source entry verbatim and only bumps the header count —
untouched entries are never re-serialized.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# modeldb is single-byte text (paths are ASCII). latin-1 round-trips every byte
# 1:1, which keeps raw spans exact.
ENCODING = "latin-1"
ARCHIVE_MAGIC = "serialization::archive"


@dataclass
class Animation:
    mount_type: str            # horse | none | elephant | camel
    primary_skeleton: str
    secondary_skeleton: str
    pri_weapons: List[str] = field(default_factory=list)
    sec_weapons: List[str] = field(default_factory=list)

    def skeletons(self) -> List[str]:
        return [s for s in (self.primary_skeleton, self.secondary_skeleton) if s]


@dataclass
class Texture:
    faction: str
    texture: str
    normal: str
    sprite: str


@dataclass
class ModelEntry:
    name: str
    scale: float
    lods: List[Tuple[str, int]]          # (mesh, distance)
    main_textures: List[Texture]
    attach_textures: List[Texture]
    animations: List[Animation]
    torch_index: int
    torch: List[float]                   # 6 floats
    raw: str = ""                        # verbatim source text for this entry
    first_entry_pad: bool = False        # see _read_entry's ``pad`` argument

    def skeletons(self) -> List[str]:
        out: List[str] = []
        for a in self.animations:
            out.extend(a.skeletons())
        return out

    def mesh_files(self) -> List[str]:
        return [mesh for mesh, _ in self.lods if mesh]

    def texture_files(self) -> List[str]:
        files: List[str] = []
        for t in list(self.main_textures) + list(self.attach_textures):
            for p in (t.texture, t.normal, t.sprite):
                if p and p != "0":
                    files.append(p)
        # de-dup, keep order
        seen, out = set(), []
        for f in files:
            if f not in seen:
                seen.add(f)
                out.append(f)
        return out

    def factions(self) -> List[str]:
        return sorted({t.faction for t in self.main_textures} |
                      {t.faction for t in self.attach_textures})

    def content_key_mapped(self, path_fn):
        """content_key with every file path passed through ``path_fn``.

        Lets callers compare two entries *modulo* a path rewrite (e.g. the
        reroute/mod_folder relocation), so a model copied into a mod-specific
        folder still counts as identical to its original for dedup purposes.
        """
        mp = path_fn
        return (
            round(self.scale, 4),
            tuple((mp(m), d) for m, d in self.lods),
            tuple((t.faction, mp(t.texture), mp(t.normal), mp(t.sprite))
                  for t in self.main_textures),
            tuple((t.faction, mp(t.texture), mp(t.normal), mp(t.sprite))
                  for t in self.attach_textures),
            tuple((a.mount_type, a.primary_skeleton, a.secondary_skeleton,
                   tuple(a.pri_weapons), tuple(a.sec_weapons)) for a in self.animations),
            self.torch_index,
            tuple(round(x, 4) for x in self.torch),
        )

    def content_key(self):
        """Everything that defines the entry EXCEPT its name (for dedup compare).

        Includes LOD mesh filenames + all texture paths, so 'identical' means
        truly identical (same content including file names), per spec.
        """
        return self.content_key_mapped(lambda p: p)

    def content_equals(self, other: "ModelEntry") -> bool:
        return self.content_key() == other.content_key()


class _Reader:
    """Length-prefixed token reader mirroring the ModdingTool FileStream."""

    def __init__(self, text: str):
        self.s = text
        self.i = 0
        self.n = len(text)

    def _skip_ws(self) -> None:
        while self.i < self.n and self.s[self.i].isspace():
            self.i += 1

    def token(self) -> str:
        self._skip_ws()
        start = self.i
        while self.i < self.n and not self.s[self.i].isspace():
            self.i += 1
        return self.s[start:self.i]

    def get_int(self) -> int:
        return int(self.token())

    def get_float(self) -> float:
        return float(self.token())

    def get_string(self) -> str:
        length = int(self.token())
        if length <= 0:
            return ""
        self._skip_ws()
        val = self.s[self.i:self.i + length]
        self.i += length
        return val


@dataclass
class ModelDb:
    header_ints: List[int]               # the 8 ints after the archive magic
    blank_raw: str                       # verbatim "blank" entry (leading padding entry)
    entries: List[ModelEntry]
    body_start: int = 0                  # offset in source where the body begins
    trailing: str = ""                   # bytes after the last entry (usually "\n")
    header_raw: str = ""                 # verbatim original header (incl trailing whitespace)

    def by_name(self) -> Dict[str, ModelEntry]:
        return {e.name: e for e in self.entries}

    def get(self, name: str) -> Optional[ModelEntry]:
        return self.by_name().get(name.lower())

    def all_skeletons(self) -> set:
        out: set = set()
        for e in self.entries:
            out.update(e.skeletons())
        out.discard("")
        return out

    def to_text(self) -> str:
        # +1 for the blank sentinel entry, but only if the source file had one
        # -- some mods (e.g. those lacking the vanilla "blank" padding entry)
        # count every entry as real.
        count = len(self.entries) + (1 if self.blank_raw else 0)
        if self.header_raw and count == self.header_ints[5]:
            # No entries added/removed: emit the original header byte-for-byte.
            header = self.header_raw
        else:
            ints = list(self.header_ints)
            ints[5] = count            # entry-count slot
            header = (f"{len(ARCHIVE_MAGIC)} {ARCHIVE_MAGIC} "
                      + " ".join(str(x) for x in ints) + "\n")
        body = self.blank_raw + "".join(e.raw for e in self.entries) + self.trailing
        return header + body

    def write(self, path: str | Path) -> None:
        Path(path).write_text(self.to_text(), encoding=ENCODING)


def _read_entry(r: _Reader, pad: bool = False) -> ModelEntry:
    """Read one entry. ``pad`` reproduces a vanilla M2TW quirk: when a
    modeldb has no leading ``blank`` sentinel entry, the game pads the very
    first real entry with 8 extra reserved int-pairs threaded through the
    body (confirmed against the reference C# ModdingTool's ``FirstEntryPad``
    calls). Every other entry, and every entry in a file that does have a
    ``blank`` sentinel, is unpadded.
    """
    def firstpad() -> None:
        if pad:
            r.get_int()
            r.get_int()

    name = r.get_string().lower()
    scale = r.get_float()
    firstpad()
    lod_count = r.get_int()
    firstpad()
    lods = [(r.get_string(), r.get_int()) for _ in range(lod_count)]
    firstpad()

    def read_textures(pad_after_count: bool) -> List[Texture]:
        cnt = r.get_int()
        if pad_after_count:
            firstpad()
        out = []
        for _ in range(cnt):
            fac = r.get_string().lower()
            tex, nrm, spr = r.get_string(), r.get_string(), r.get_string()
            out.append(Texture(fac, tex, nrm, spr))
        return out

    main_tex = read_textures(pad_after_count=True)
    attach_tex = read_textures(pad_after_count=False)   # no padding around this count
    firstpad()

    mount_n = r.get_int()
    firstpad()
    anims: List[Animation] = []
    for _ in range(mount_n):
        mt = r.get_string().lower()
        pri = r.get_string()
        sec = r.get_string()
        priw = [r.get_string() for _ in range(r.get_int())]
        secw = [r.get_string() for _ in range(r.get_int())]
        anims.append(Animation(mt, pri, sec, priw, secw))
    firstpad()

    torch_idx = r.get_int()
    torch = [r.get_float() for _ in range(6)]
    firstpad()
    return ModelEntry(name, scale, lods, main_tex, attach_tex, anims,
                      torch_idx, torch, first_entry_pad=pad)


def parse_text(text: str) -> ModelDb:
    r = _Reader(text)
    magic = r.get_string()
    if magic != ARCHIVE_MAGIC:
        raise ValueError(f"not a modeldb archive (magic={magic!r})")
    header_ints = [r.get_int() for _ in range(8)]
    count = header_ints[5]

    # The body starts at the first token AFTER the header ints. Locating it by
    # the first newline instead would assume the header is exactly one line —
    # true for most mods, but some wrap it (`...0 0 \n595 \n0 0 \n5 blank`),
    # and reading from mid-header makes the next int look like a string length
    # and swallows the first entry.
    r._skip_ws()
    body_start = r.i
    prev_end = body_start

    blank_raw = ""
    entries: List[ModelEntry] = []
    for n in range(count):
        pad = False
        if n == 0:
            name = r.get_string().lower()
            if name == "blank":
                for _ in range(39):
                    r.get_int()
                blank_raw = text[prev_end:r.i]
                prev_end = r.i
                continue
            # No blank entry: rewind and treat as a normal first entry.
            # Vanilla M2TW pads this specific entry with extra reserved
            # ints (see _read_entry's ``pad`` docstring).
            r.i = prev_end
            pad = True
        entry = _read_entry(r, pad=pad)
        entry.raw = text[prev_end:r.i]
        entries.append(entry)
        prev_end = r.i

    trailing = text[prev_end:]
    header_raw = text[:body_start]
    return ModelDb(header_ints, blank_raw, entries, body_start, trailing, header_raw)


def parse_file(path: str | Path) -> ModelDb:
    return parse_text(Path(path).read_text(encoding=ENCODING))


import re as _re

_NAME_PREFIX_RE = _re.compile(r"(\d+)\s+")


class _SpanReader(_Reader):
    """Reader that also reports the byte span of each length-prefixed string."""

    def get_string_span(self) -> Tuple[int, int, str]:
        """Return (start, end, value) covering the whole ``<len> <chars>`` token."""
        self._skip_ws()
        start = self.i
        length = int(self.token())
        if length <= 0:
            return (start, self.i, "")
        self._skip_ws()
        val = self.s[self.i:self.i + length]
        self.i += length
        return (start, self.i, val)


def entry_path_spans(raw: str, pad: bool = False) -> List[Tuple[int, int, str, str]]:
    """Locate every mesh/texture *file path* string inside one entry's raw text.

    Returns (start, end, value, kind) tuples where kind is
    ``mesh`` | ``texture`` | ``normal`` | ``sprite``. Faction names, skeletons and
    weapon names are deliberately excluded — they are not file paths.

    ``pad`` must be True when ``raw`` came from a :class:`ModelEntry` with
    ``first_entry_pad`` set (see ``_read_entry``) — otherwise this walk
    desyncs on the extra reserved ints and misidentifies path spans.
    """
    r = _SpanReader(raw)
    out: List[Tuple[int, int, str, str]] = []

    def firstpad() -> None:
        if pad:
            r.get_int()
            r.get_int()

    r.get_string()                      # name
    r.get_float()                       # scale
    firstpad()
    lod_n = r.get_int()
    firstpad()
    for _ in range(lod_n):              # LODs
        s, e, v = r.get_string_span()
        out.append((s, e, v, "mesh"))
        r.get_int()                     # distance
    firstpad()

    def textures(pad_after_count: bool):
        cnt = r.get_int()
        if pad_after_count:
            firstpad()
        for _ in range(cnt):
            r.get_string()              # faction (not a path)
            for kind in ("texture", "normal", "sprite"):
                s, e, v = r.get_string_span()
                out.append((s, e, v, kind))

    textures(pad_after_count=True)      # main textures
    textures(pad_after_count=False)     # attach textures (no padding around this count)
    firstpad()

    anim_n = r.get_int()
    firstpad()
    for _ in range(anim_n):             # animations
        r.get_string(); r.get_string(); r.get_string()   # mount type, pri/sec skeleton
        for _ in range(r.get_int()):
            r.get_string()              # primary weapons
        for _ in range(r.get_int()):
            r.get_string()              # secondary weapons
    firstpad()

    r.get_int()                         # torch index
    for _ in range(6):
        r.get_float()
    return out


def rewrite_entry_paths(raw: str, path_map: Dict[str, str], pad: bool = False) -> str:
    """Return ``raw`` with mesh/texture paths remapped via ``path_map``.

    Only the path strings are touched, and each replacement re-emits its own
    ``<len> <chars>`` prefix so the length numbering stays correct. Every other
    byte (floats, counts, whitespace) is preserved verbatim, which keeps entries
    that we did not reroute byte-identical. ``pad`` — see ``entry_path_spans``.
    """
    if not path_map:
        return raw
    spans = entry_path_spans(raw, pad=pad)
    out: List[str] = []
    pos = 0
    for start, end, val, _kind in spans:
        new = path_map.get(val)
        if not new or new == val:
            continue
        out.append(raw[pos:start])
        out.append(f"{len(new)} {new}")
        pos = end
    out.append(raw[pos:])
    return "".join(out)


def rewrite_paths_indexed(raw: str, index_map: Dict[int, str],
                          pad: bool = False) -> str:
    """Return ``raw`` with the path at each *span index* replaced.

    Indices are positions in :func:`entry_path_spans`' output. Unlike
    :func:`rewrite_entry_paths` (which maps by value) this addresses one slot at
    a time, so two LODs that happen to share a mesh file can be pointed at
    different files. Each replacement re-emits its own ``<len> <chars>`` prefix;
    every other byte is preserved. ``pad`` — see :func:`entry_path_spans`.
    """
    index_map = {int(k): v for k, v in (index_map or {}).items() if v is not None}
    if not index_map:
        return raw
    spans = entry_path_spans(raw, pad=pad)
    out: List[str] = []
    pos = 0
    for i, (start, end, val, _kind) in enumerate(spans):
        new = index_map.get(i)
        if new is None or new == val:
            continue
        out.append(raw[pos:start])
        out.append(f"{len(new)} {new}")
        pos = end
    out.append(raw[pos:])
    return "".join(out)


def animation_spans(raw: str, pad: bool = False) -> List[Dict[str, Tuple[int, int, str]]]:
    """Per animation record, the spans of its three name strings.

    ``[{"mount_type": (s, e, value), "primary": …, "secondary": …}, …]`` in file
    order. The weapon lists are deliberately not reported: they are the model's
    own weapons, and nothing here has any business rewriting them.
    ``pad`` — see :func:`entry_path_spans`.
    """
    r = _SpanReader(raw)

    def firstpad() -> None:
        if pad:
            r.get_int()
            r.get_int()

    r.get_string()                      # name
    r.get_float()                       # scale
    firstpad()
    lod_n = r.get_int()
    firstpad()
    for _ in range(lod_n):
        r.get_string()
        r.get_int()
    firstpad()

    def textures(pad_after_count: bool):
        cnt = r.get_int()
        if pad_after_count:
            firstpad()
        for _ in range(cnt):
            for _ in range(4):          # faction, texture, normal, sprite
                r.get_string()

    textures(pad_after_count=True)
    textures(pad_after_count=False)
    firstpad()

    out: List[Dict[str, Tuple[int, int, str]]] = []
    anim_n = r.get_int()
    firstpad()
    for _ in range(anim_n):
        out.append({"mount_type": r.get_string_span(),
                    "primary": r.get_string_span(),
                    "secondary": r.get_string_span()})
        for _ in range(r.get_int()):
            r.get_string()              # primary weapons
        for _ in range(r.get_int()):
            r.get_string()              # secondary weapons
    return out


def rewrite_animations(raw: str, anims: List["Animation"],
                       pad: bool = False) -> str:
    """Return ``raw`` with each animation record's mount type and two skeleton
    names replaced by ``anims``', matched up by position.

    Only those three strings move; the record count, the weapon lists and every
    other byte stay exactly as they were, so an entry keeps its own weapons while
    borrowing another entry's animation set. When ``raw`` has more records than
    ``anims``, the last of ``anims`` is reused for the rest — a mount with two
    records and a donor with one still ends up driven entirely by the donor.
    A name that only differs in case is left alone: the game does not care, and
    rewriting it would churn bytes for nothing (a parsed ``mount_type`` is
    lower-cased, so writing one back would otherwise never be a no-op).
    ``pad`` — see :func:`entry_path_spans`.
    """
    if not anims:
        return raw
    spans = animation_spans(raw, pad=pad)
    edits: List[Tuple[int, int, str]] = []
    for i, rec in enumerate(spans):
        a = anims[i] if i < len(anims) else anims[-1]
        for key, value in (("mount_type", a.mount_type),
                           ("primary", a.primary_skeleton),
                           ("secondary", a.secondary_skeleton)):
            start, end, old = rec[key]
            if (old or "").lower() == (value or "").lower():
                continue
            # an empty string is the bare "0" token — no trailing space, or the
            # next read would start one byte later than the writer meant
            edits.append((start, end, f"{len(value)} {value}" if value else "0"))
    if not edits:
        return raw
    out = raw
    for start, end, text in sorted(edits, key=lambda e: e[0], reverse=True):
        out = out[:start] + text + out[end:]
    return out


def merged_animations(entry_anims: List["Animation"],
                      donor_anims: List["Animation"]) -> List["Animation"]:
    """The parsed counterpart of :func:`rewrite_animations`: the entry's records
    with the donor's mount type and skeletons, keeping each record's weapons."""
    if not donor_anims:
        return list(entry_anims)
    out: List[Animation] = []
    for i, a in enumerate(entry_anims):
        d = donor_anims[i] if i < len(donor_anims) else donor_anims[-1]
        out.append(Animation(d.mount_type, d.primary_skeleton, d.secondary_skeleton,
                             list(a.pri_weapons), list(a.sec_weapons)))
    return out


def path_slots_raw(raw: str, pad: bool = False) -> List[dict]:
    """:func:`path_slots` straight off an entry's raw text.

    The editor rewrites an entry in stages (faction records added/removed, then
    per-faction texture paths set), and every stage shifts the span indices — so
    each stage has to re-derive the slots from the text it is about to edit
    rather than from the originally parsed :class:`ModelEntry`.
    """
    spans = entry_path_spans(raw, pad=pad)
    groups = _texture_group_spans(raw, pad=pad)
    records = [("main" if gi == 0 else "attach", rec["fac"])
               for gi, g in enumerate(groups) for rec in g["records"]]
    slots: List[dict] = []
    lod_i = rec_i = 0
    for i, (_s, _e, value, kind) in enumerate(spans):
        if kind == "mesh":
            slots.append({"i": i, "kind": "mesh", "value": value, "group": "lod",
                          "faction": "", "label": f"LOD {lod_i} mesh"})
            lod_i += 1
            continue
        group, faction = records[rec_i] if rec_i < len(records) else ("main", "")
        pretty = {"texture": "texture", "normal": "normal map", "sprite": "sprite"}[kind]
        slots.append({"i": i, "kind": kind, "value": value, "group": group,
                      "faction": faction,
                      "label": f"{faction} {pretty}"
                               + (" (attachment)" if group == "attach" else "")})
        if kind == "sprite":            # texture/normal/sprite = one faction record
            rec_i += 1
    return slots


def path_slots(entry: "ModelEntry") -> List[dict]:
    """Describe every editable path slot of an entry, in span-index order.

    Returns ``{"i", "kind", "value", "group", "faction", "label"}`` per slot —
    the shape the editor UI renders. The span order is fixed by the format:
    LOD meshes, then main-texture records (faction: texture/normal/sprite),
    then attachment-texture records.
    """
    slots = path_slots_raw(entry.raw, pad=entry.first_entry_pad)
    for lod_i, (_mesh, dist) in enumerate(entry.lods):     # label with the LOD distance
        if lod_i < len(slots) and slots[lod_i]["kind"] == "mesh":
            slots[lod_i]["label"] = f"LOD {lod_i} mesh (dist {dist})"
    return slots


def _texture_group_spans(raw: str, pad: bool = False) -> List[dict]:
    """Span info for an entry's two texture groups (main, then attach).

    Each group reports its count token span, every record's span, and where the
    group ends, so records can be appended and the count fixed in place.
    ``pad`` — see ``entry_path_spans``.
    """
    r = _SpanReader(raw)

    def firstpad() -> None:
        if pad:
            r.get_int()
            r.get_int()

    r.get_string()                       # name
    r.get_float()                        # scale
    firstpad()
    lod_n = r.get_int()
    firstpad()
    for _ in range(lod_n):               # LODs
        r.get_string_span()
        r.get_int()
    firstpad()

    groups: List[dict] = []
    for is_main in (True, False):        # main textures, then attach textures
        r._skip_ws()
        cnt_start = r.i
        count = int(r.token())
        cnt_end = r.i
        if is_main:
            firstpad()                   # no padding around the attach count
        records_start = r.i             # after any padding -- where a new record inserts
        records = []
        for _ in range(count):
            f_start, f_end, fac = r.get_string_span()
            r.get_string_span()          # texture
            r.get_string_span()          # normal
            _, s_end, _ = r.get_string_span()   # sprite
            records.append({"fac": fac, "start": f_start, "fac_end": f_end, "end": s_end})
        groups.append({"cnt_start": cnt_start, "cnt_end": cnt_end, "count": count,
                       "records": records, "records_start": records_start,
                       "group_end": records[-1]["end"] if records else records_start})
    return groups


def add_texture_factions(raw: str, factions, prefer: Optional[str] = None,
                          pad: bool = False) -> str:
    """Ensure the entry has a texture record for every faction in ``factions``.

    A faction with no record has no skin, so the game fails to show the unit.
    Missing factions are given a clone of an existing record (same texture /
    normal / sprite paths), and each group's count token is bumped to match —
    this is what makes a transfer valid after a base unit changes ownership.
    ``pad`` — see ``entry_path_spans``.
    """
    wanted = [f for f in dict.fromkeys(factions) if f]
    if not wanted:
        return raw
    groups = _texture_group_spans(raw, pad=pad)
    edits: List[Tuple[int, int, str]] = []          # (start, end, replacement)
    for g in groups:
        if not g["records"]:
            continue                                # nothing to clone from
        have = {rec["fac"] for rec in g["records"]}
        missing = [f for f in wanted if f not in have]
        if not missing:
            continue
        donor = None
        if prefer:
            donor = next((rec for rec in g["records"] if rec["fac"] == prefer), None)
        if donor is None:                           # 'slave' is the generic rebel skin
            donor = next((rec for rec in g["records"] if rec["fac"] != "slave"),
                         g["records"][0])
        # everything after the donor's faction string (its texture/normal/sprite,
        # with the file's own whitespace) is reused verbatim
        tail = raw[donor["fac_end"]:donor["end"]]
        added = "".join(f"\n{len(f)} {f}{tail}" for f in missing)
        edits.append((g["group_end"], g["group_end"], added))
        edits.append((g["cnt_start"], g["cnt_end"], str(g["count"] + len(missing))))
    if not edits:
        return raw
    # apply back-to-front so earlier offsets stay valid
    out = raw
    for start, end, text in sorted(edits, key=lambda e: e[0], reverse=True):
        out = out[:start] + text + out[end:]
    return out


def set_texture_factions(raw: str, factions, prefer: Optional[str] = None,
                         pad: bool = False) -> str:
    """Make each texture group hold *exactly* ``factions``, in that order.

    Unlike :func:`add_texture_factions` (which only ever adds) this is what the
    editor's faction checklist needs: ticking a faction clones an existing record
    for it, unticking one drops that record, and each group's count token is
    rewritten to match. A kept record is spliced back **verbatim**, so its own
    texture/normal/sprite paths survive the reshuffle. Refuses to empty a group —
    a texture group with zero records is not a model the game can draw.
    ``pad`` — see :func:`entry_path_spans`.
    """
    wanted = [f for f in dict.fromkeys((f or "").strip().lower() for f in factions) if f]
    if not wanted:
        return raw
    groups = _texture_group_spans(raw, pad=pad)
    edits: List[Tuple[int, int, str]] = []
    for g in groups:
        recs = g["records"]
        if not recs:
            continue                                # nothing to clone from
        if [r["fac"] for r in recs] == wanted:
            continue                                # already exactly right
        have = {r["fac"]: r for r in recs}
        donor = have.get(prefer or "")
        if donor is None:                           # 'slave' is the generic rebel skin
            donor = next((r for r in recs if r["fac"] != "slave"), recs[0])
        tail = raw[donor["fac_end"]:donor["end"]]
        # reuse whatever separated the count from the first record (usually "\n")
        lead = raw[g["records_start"]:recs[0]["start"]] or "\n"
        parts = [raw[have[f]["start"]:have[f]["end"]] if f in have
                 else f"{len(f)} {f}{tail}" for f in wanted]
        body = "".join((lead if i == 0 else "\n") + p for i, p in enumerate(parts))
        edits.append((g["records_start"], g["group_end"], body))
        edits.append((g["cnt_start"], g["cnt_end"], str(len(wanted))))
    if not edits:
        return raw
    out = raw
    for start, end, text in sorted(edits, key=lambda e: e[0], reverse=True):
        out = out[:start] + text + out[end:]
    return out


def rename_entry_raw(raw: str, new_name: str) -> str:
    """Return a copy of an entry's raw text with its (length-prefixed) name
    replaced by ``new_name``. The name is the first length-prefixed string in
    the entry body; everything after it is preserved verbatim.
    """
    lead_len = len(raw) - len(raw.lstrip())
    lead, rest = raw[:lead_len], raw[lead_len:]
    m = _NAME_PREFIX_RE.match(rest)
    if not m:
        return raw
    n = int(m.group(1))
    after = rest[m.end() + n:]
    return f"{lead}{len(new_name)} {new_name}{after}"
