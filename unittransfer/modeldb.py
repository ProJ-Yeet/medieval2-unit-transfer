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
    header_raw: str = ""                 # verbatim original header line (incl newline)

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
        count = len(self.entries) + 1  # +1 for the blank entry
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


def _read_entry(r: _Reader) -> ModelEntry:
    name = r.get_string().lower()
    scale = r.get_float()
    lod_count = r.get_int()
    lods = [(r.get_string(), r.get_int()) for _ in range(lod_count)]

    def read_textures() -> List[Texture]:
        cnt = r.get_int()
        out = []
        for _ in range(cnt):
            fac = r.get_string().lower()
            tex, nrm, spr = r.get_string(), r.get_string(), r.get_string()
            out.append(Texture(fac, tex, nrm, spr))
        return out

    main_tex = read_textures()
    attach_tex = read_textures()

    mount_n = r.get_int()
    anims: List[Animation] = []
    for _ in range(mount_n):
        mt = r.get_string().lower()
        pri = r.get_string()
        sec = r.get_string()
        priw = [r.get_string() for _ in range(r.get_int())]
        secw = [r.get_string() for _ in range(r.get_int())]
        anims.append(Animation(mt, pri, sec, priw, secw))

    torch_idx = r.get_int()
    torch = [r.get_float() for _ in range(6)]
    return ModelEntry(name, scale, lods, main_tex, attach_tex, anims,
                      torch_idx, torch)


def parse_text(text: str) -> ModelDb:
    r = _Reader(text)
    magic = r.get_string()
    if magic != ARCHIVE_MAGIC:
        raise ValueError(f"not a modeldb archive (magic={magic!r})")
    header_ints = [r.get_int() for _ in range(8)]
    count = header_ints[5]

    body_start = text.find("\n") + 1
    prev_end = body_start
    # Skip the reader up to body_start so the first string read is the blank name.
    r.i = body_start

    blank_raw = ""
    entries: List[ModelEntry] = []
    for n in range(count):
        if n == 0:
            name = r.get_string().lower()
            if name == "blank":
                for _ in range(39):
                    r.get_int()
                blank_raw = text[prev_end:r.i]
                prev_end = r.i
                continue
            # No blank entry: rewind and treat as a normal first entry.
            r.i = prev_end
        entry = _read_entry(r)
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


def entry_path_spans(raw: str) -> List[Tuple[int, int, str, str]]:
    """Locate every mesh/texture *file path* string inside one entry's raw text.

    Returns (start, end, value, kind) tuples where kind is
    ``mesh`` | ``texture`` | ``normal`` | ``sprite``. Faction names, skeletons and
    weapon names are deliberately excluded — they are not file paths.
    """
    r = _SpanReader(raw)
    out: List[Tuple[int, int, str, str]] = []

    r.get_string()                      # name
    r.get_float()                       # scale
    for _ in range(r.get_int()):        # LODs
        s, e, v = r.get_string_span()
        out.append((s, e, v, "mesh"))
        r.get_int()                     # distance

    def textures():
        for _ in range(r.get_int()):
            r.get_string()              # faction (not a path)
            for kind in ("texture", "normal", "sprite"):
                s, e, v = r.get_string_span()
                out.append((s, e, v, kind))

    textures()                          # main textures
    textures()                          # attach textures

    for _ in range(r.get_int()):        # animations
        r.get_string(); r.get_string(); r.get_string()   # mount type, pri/sec skeleton
        for _ in range(r.get_int()):
            r.get_string()              # primary weapons
        for _ in range(r.get_int()):
            r.get_string()              # secondary weapons

    r.get_int()                         # torch index
    for _ in range(6):
        r.get_float()
    return out


def rewrite_entry_paths(raw: str, path_map: Dict[str, str]) -> str:
    """Return ``raw`` with mesh/texture paths remapped via ``path_map``.

    Only the path strings are touched, and each replacement re-emits its own
    ``<len> <chars>`` prefix so the length numbering stays correct. Every other
    byte (floats, counts, whitespace) is preserved verbatim, which keeps entries
    that we did not reroute byte-identical.
    """
    if not path_map:
        return raw
    spans = entry_path_spans(raw)
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


def _texture_group_spans(raw: str) -> List[dict]:
    """Span info for an entry's two texture groups (main, then attach).

    Each group reports its count token span, every record's span, and where the
    group ends, so records can be appended and the count fixed in place.
    """
    r = _SpanReader(raw)
    r.get_string()                       # name
    r.get_float()                        # scale
    for _ in range(r.get_int()):         # LODs
        r.get_string_span()
        r.get_int()

    groups: List[dict] = []
    for _ in range(2):                   # main textures, then attach textures
        r._skip_ws()
        cnt_start = r.i
        count = int(r.token())
        cnt_end = r.i
        records = []
        for _ in range(count):
            f_start, f_end, fac = r.get_string_span()
            r.get_string_span()          # texture
            r.get_string_span()          # normal
            _, s_end, _ = r.get_string_span()   # sprite
            records.append({"fac": fac, "start": f_start, "fac_end": f_end, "end": s_end})
        groups.append({"cnt_start": cnt_start, "cnt_end": cnt_end, "count": count,
                       "records": records,
                       "group_end": records[-1]["end"] if records else cnt_end})
    return groups


def add_texture_factions(raw: str, factions, prefer: Optional[str] = None) -> str:
    """Ensure the entry has a texture record for every faction in ``factions``.

    A faction with no record has no skin, so the game fails to show the unit.
    Missing factions are given a clone of an existing record (same texture /
    normal / sprite paths), and each group's count token is bumped to match —
    this is what makes a transfer valid after a base unit changes ownership.
    """
    wanted = [f for f in dict.fromkeys(factions) if f]
    if not wanted:
        return raw
    groups = _texture_group_spans(raw)
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
