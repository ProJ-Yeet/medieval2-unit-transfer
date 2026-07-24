"""Parsers for the siege-engine files: ``descr_engines.txt``,
``descr_mounted_engines.txt`` and ``descr_engine_skeleton.txt``.

A siege unit's EDU ``engine`` (or ``mounted_engine``) field names an engine
defined in ``descr_engines.txt``::

    type                Dol_Guldur_Tower
    culture             all
    class               holy_cart
    pathfinding_data    none
    reference_points    siege_engines/great_bell_tower_standard_milan.modelReferencePoints

    engine_model_group  normal
    engine_skeleton     Great_bell_tower_standard
    engine_bone_map     siege_engines/BoneMaps/Great_Bell_Tower_standard.xml
    engine_collision    siege_engines/collision_models/belltower_collide.CAS
    engine_mesh         siege_engines/Dol_Guldur_Tower_lod0.mesh, 40.0
    ...

So an engine transfer needs FOUR things in the destination:
  1. the ``descr_engines.txt`` block(s),
  2. every file named on a ``reference_points`` / ``pathfinding_data`` /
     ``engine_bone_map`` / ``engine_collision`` / ``engine_mesh`` line,
  3. the **textures** those meshes use — which are *baked into the .mesh binary*,
     not named in any text file (see :func:`mesh_textures`),
  4. each model group's ``engine_skeleton`` entry from
     ``descr_engine_skeleton.txt``, plus the ``.CAS``/``.evt`` animation files it
     names (engine animations live loose under ``animations/engine/``, not in a
     unit anim pack).

Blocks start at a line whose first token is ``type`` and run until the next one.
Verbatim block text is kept so a transfer can append it unchanged. Note a single
engine ``type`` may appear in SEVERAL blocks (one per ``culture`` / ``variant``,
e.g. the per-culture siege towers) — lookups therefore return a list.
``;`` starts a comment.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ENCODING = "latin-1"

#: Engine keys whose value names a file, relative to the mod's ``data/`` folder.
#: ``engine_mesh`` is ``"<path>, <distance>"``; the rest are a bare path.
FILE_KEYS = ("reference_points", "pathfinding_data", "engine_bone_map",
             "engine_collision", "engine_mesh")
#: values that mean "no file here"
NO_FILE = {"", "none", "no"}


def _strip_comment(s: str) -> str:
    return s.split(";", 1)[0].rstrip()


def _line_kv(line: str) -> Tuple[str, str]:
    """(key, value) for one line; ('', '') for blanks/comments."""
    body = _strip_comment(line).strip()
    if not body:
        return "", ""
    parts = body.split(None, 1)
    return parts[0], (parts[1].strip() if len(parts) > 1 else "")


def data_rel(path: str) -> str:
    """Normalise a path as written in an engine file to a ``data/``-relative one.

    Engine files write mesh/bonemap paths already relative to ``data/``
    (``siege_engines/x.mesh``) but animation paths WITH the prefix
    (``data/animations/engine/x.CAS``). Backslashes are normalised too.
    """
    p = str(path).replace("\\", "/").strip().strip('"').lstrip("/")
    if p.lower().startswith("data/"):
        p = p[5:]
    return p


def _file_value(key: str, value: str) -> str:
    """The file path a ``key value`` line names, or '' if it names none."""
    if key not in FILE_KEYS:
        return ""
    val = value.split(",", 1)[0].strip() if key == "engine_mesh" else value.strip()
    if val.lower() in NO_FILE:
        return ""
    return data_rel(val)


# --------------------------------------------------------------------------
@dataclass
class ModelGroup:
    """One ``engine_model_group`` (normal / dying / dead) of an engine."""
    name: str = ""
    skeleton: str = ""
    bone_map: str = ""
    collision: str = ""
    meshes: List[str] = field(default_factory=list)   # data-relative, LOD order


@dataclass
class Engine:
    type: str = ""
    culture: str = ""
    variant: str = ""
    engine_class: str = ""
    reference_points: str = ""
    pathfinding_data: str = ""
    groups: List[ModelGroup] = field(default_factory=list)
    attack_stats: List[List[str]] = field(default_factory=list)  # CSV values per line
    raw: str = ""                                    # verbatim block text

    # ---- what this engine depends on -----------------------------------
    def skeletons(self) -> List[str]:
        """``engine_skeleton`` names across the model groups (deduped, in order)."""
        out: List[str] = []
        seen = set()
        for g in self.groups:
            if g.skeleton and g.skeleton.lower() not in seen:
                seen.add(g.skeleton.lower())
                out.append(g.skeleton)
        return out

    def file_refs(self) -> List[str]:
        """Every data-relative file the block names, deduped, in file order."""
        out: List[str] = []
        seen = set()
        for line in self.raw.splitlines():
            k, v = _line_kv(line)
            rel = _file_value(k, v)
            if rel and rel.lower() not in seen:
                seen.add(rel.lower())
                out.append(rel)
        return out

    def mesh_refs(self) -> List[str]:
        """Just the ``engine_mesh`` paths (the ones carrying baked textures)."""
        return [r for r in self.file_refs() if r.lower().endswith(".mesh")]

    def projectiles(self) -> List[str]:
        """Projectile names fired by this engine (3rd CSV slot of ``attack_stat``)."""
        out: List[str] = []
        seen = set()
        for vals in self.attack_stats:
            if len(vals) > 2:
                p = vals[2].strip()
                if p and p.lower() not in NO_FILE and p.lower() not in seen:
                    seen.add(p.lower())
                    out.append(p)
        return out

    # ---- dedup ----------------------------------------------------------
    def content_key(self):
        """Everything defining the engine EXCEPT its name (for dedup compare)."""
        out = []
        for line in self.raw.splitlines():
            k, v = _line_kv(line)
            if k and k != "type":
                out.append((k.lower(), v.lower()))
        return tuple(out)

    def content_equals(self, other: "Engine") -> bool:
        return self.content_key() == other.content_key()


@dataclass
class EngineFile:
    preamble: str = ""
    engines: List[Engine] = field(default_factory=list)

    def by_type(self) -> Dict[str, List[Engine]]:
        """Lowercased engine type -> every block declaring it (culture/variant)."""
        out: Dict[str, List[Engine]] = {}
        for e in self.engines:
            out.setdefault(e.type.lower(), []).append(e)
        return out

    def get_all(self, name: str) -> List[Engine]:
        """Every block for an engine type ([] when absent). Case-insensitive."""
        if not name:
            return []
        return self.by_type().get(name.lower(), [])

    def get(self, name: str) -> Optional[Engine]:
        blocks = self.get_all(name)
        return blocks[0] if blocks else None

    def to_text(self) -> str:
        return self.preamble + "".join(e.raw for e in self.engines)


def _parse_engine_block(raw: str) -> Engine:
    e = Engine(raw=raw)
    group: Optional[ModelGroup] = None
    for line in raw.splitlines():
        k, v = _line_kv(line)
        if not k:
            continue
        if k == "type" and not e.type:
            e.type = v
        elif k == "culture" and not e.culture:
            e.culture = v
        elif k == "class" and not e.engine_class:
            e.engine_class = v
        elif k == "variant" and not e.variant:
            e.variant = v
        elif k == "reference_points" and not e.reference_points:
            e.reference_points = _file_value(k, v)
        elif k == "pathfinding_data" and not e.pathfinding_data:
            e.pathfinding_data = _file_value(k, v)
        elif k == "engine_model_group":
            group = ModelGroup(name=v)
            e.groups.append(group)
        elif k == "attack_stat":
            e.attack_stats.append([x.strip() for x in v.split(",")])
        elif group is not None:
            if k == "engine_skeleton" and not group.skeleton:
                group.skeleton = v
            elif k == "engine_bone_map" and not group.bone_map:
                group.bone_map = _file_value(k, v)
            elif k == "engine_collision" and not group.collision:
                group.collision = _file_value(k, v)
            elif k == "engine_mesh":
                rel = _file_value(k, v)
                if rel:
                    group.meshes.append(rel)
    return e


def _block_starts(lines: List[str]) -> List[int]:
    """Indices of lines that open a block (first token ``type``, not a comment)."""
    starts: List[int] = []
    for i, line in enumerate(lines):
        s = line.lstrip()
        if s.startswith(";"):
            continue
        if s.startswith("type") and (len(s) == 4 or s[4].isspace()):
            starts.append(i)
    return starts


def parse_text(text: str) -> EngineFile:
    lines = text.splitlines(keepends=True)
    starts = _block_starts(lines)
    if not starts:
        return EngineFile(preamble=text, engines=[])
    out = EngineFile(preamble="".join(lines[:starts[0]]))
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        out.engines.append(_parse_engine_block("".join(lines[start:end])))
    return out


def parse_file(path: str | Path) -> EngineFile:
    p = Path(path)
    if not p.exists():
        return EngineFile()
    return parse_text(p.read_text(encoding=ENCODING))


# --------------------------------------------------------------------------
@dataclass
class EngineSkeleton:
    """One ``type`` block of ``descr_engine_skeleton.txt``.

    Each ``anim`` line is ``anim <key> <path.CAS> [-if:N] [-fr:N] [-evt:<path>]``.
    """
    type: str = ""
    anims: List[Tuple[str, str]] = field(default_factory=list)   # (key, cas path)
    raw: str = ""

    def anim_files(self) -> List[str]:
        """Every ``.CAS`` and ``-evt:`` file the block names (data-relative)."""
        out: List[str] = []
        seen = set()
        for line in self.raw.splitlines():
            k, v = _line_kv(line)
            if k != "anim" or not v:
                continue
            for tok in v.split():
                rel = ""
                if tok.lower().startswith("-evt:"):
                    rel = data_rel(tok[5:].rstrip(","))
                elif "/" in tok or "\\" in tok:
                    rel = data_rel(tok.rstrip(","))
                if rel and rel.lower() not in seen:
                    seen.add(rel.lower())
                    out.append(rel)
        return out

    def content_key(self):
        out = []
        for line in self.raw.splitlines():
            k, v = _line_kv(line)
            if k and k != "type":
                # collapse the wild whitespace these files use so two identical
                # entries formatted differently still compare equal
                out.append((k.lower(), " ".join(v.lower().split())))
        return tuple(out)

    def content_equals(self, other: "EngineSkeleton") -> bool:
        return self.content_key() == other.content_key()


@dataclass
class EngineSkeletonFile:
    preamble: str = ""
    skeletons: List[EngineSkeleton] = field(default_factory=list)

    def by_type(self) -> Dict[str, EngineSkeleton]:
        return {s.type.lower(): s for s in self.skeletons}

    def get(self, name: str) -> Optional[EngineSkeleton]:
        if not name:
            return None
        return self.by_type().get(name.lower())

    def to_text(self) -> str:
        return self.preamble + "".join(s.raw for s in self.skeletons)


def _parse_skeleton_block(raw: str) -> EngineSkeleton:
    s = EngineSkeleton(raw=raw)
    for line in raw.splitlines():
        k, v = _line_kv(line)
        if k == "type" and not s.type:
            s.type = v
        elif k == "anim" and v:
            parts = v.split(None, 1)
            key = parts[0]
            path = ""
            if len(parts) > 1:
                for tok in parts[1].split():
                    if "/" in tok or "\\" in tok:
                        path = data_rel(tok.rstrip(","))
                        break
            s.anims.append((key, path))
    return s


def parse_skeleton_text(text: str) -> EngineSkeletonFile:
    lines = text.splitlines(keepends=True)
    starts = _block_starts(lines)
    if not starts:
        return EngineSkeletonFile(preamble=text, skeletons=[])
    out = EngineSkeletonFile(preamble="".join(lines[:starts[0]]))
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        out.skeletons.append(_parse_skeleton_block("".join(lines[start:end])))
    return out


def parse_skeleton_file(path: str | Path) -> EngineSkeletonFile:
    p = Path(path)
    if not p.exists():
        return EngineSkeletonFile()
    return parse_skeleton_text(p.read_text(encoding=ENCODING))


# --------------------------------------------------------------------------
def _rewrite_lines(raw: str, decide) -> str:
    """Rewrite block lines, preserving indentation, spacing and ``;`` comments.

    ``decide(key, value, state)`` returns a replacement value or None. ``state``
    is a mutable dict the caller can use to fire a rule only once.
    """
    state: Dict[str, object] = {}
    out: List[str] = []
    for line in raw.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        eol = line[len(body):]
        stripped = body.lstrip()
        indent = body[:len(body) - len(stripped)]
        if ";" in stripped:
            i = stripped.index(";")
            content, comment = stripped[:i], stripped[i:]
        else:
            content, comment = stripped, ""
        ws_before_comment = content[len(content.rstrip()):]
        content = content.rstrip()
        parts = content.split(None, 1)
        key = parts[0] if parts else ""
        val = parts[1].strip() if len(parts) > 1 else ""

        new_val = decide(key, val, state) if key else None
        if new_val is None:
            out.append(line)
        else:
            after = content[len(key):]
            sep = after[:len(after) - len(after.lstrip())] or "\t\t\t"
            out.append(f"{indent}{key}{sep}{new_val}{ws_before_comment}{comment}{eol}")
    return "".join(out)


def rewrite_engine_raw(raw: str, *, type_new: Optional[str] = None,
                       skeleton_map: Optional[Dict[str, str]] = None,
                       projectile_map: Optional[Dict[str, str]] = None,
                       path_map: Optional[Dict[str, str]] = None) -> str:
    """Copy of an engine block with names/paths retargeted.

    ``skeleton_map`` / ``projectile_map`` / ``path_map`` are keyed by the
    lowercased original name (``path_map`` by data-relative path).
    """
    skeleton_map = {k.lower(): v for k, v in (skeleton_map or {}).items()}
    projectile_map = {k.lower(): v for k, v in (projectile_map or {}).items()}
    path_map = {k.lower(): v for k, v in (path_map or {}).items()}

    def decide(key, val, state):
        if key == "type" and type_new is not None and not state.get("type"):
            state["type"] = True
            return type_new
        if key == "engine_skeleton" and val.lower() in skeleton_map:
            return skeleton_map[val.lower()]
        if key == "attack_stat" and projectile_map:
            parts = val.split(",")
            if len(parts) > 2 and parts[2].strip().lower() in projectile_map:
                token = parts[2]
                lead = token[:len(token) - len(token.lstrip())]
                trail = token[len(token.rstrip()):]
                parts[2] = lead + projectile_map[parts[2].strip().lower()] + trail
                return ",".join(parts)
            return None
        if key in FILE_KEYS and path_map:
            rel = _file_value(key, val)
            new = path_map.get(rel.lower()) if rel else None
            if new:
                if key == "engine_mesh" and "," in val:
                    return new + "," + val.split(",", 1)[1]
                return new
        return None

    return _rewrite_lines(raw, decide)


def rewrite_engine_skeleton_raw(raw: str, *,
                                type_new: Optional[str] = None) -> str:
    """Copy of a ``descr_engine_skeleton.txt`` block with its ``type`` renamed."""
    def decide(key, val, state):
        if key == "type" and type_new is not None and not state.get("type"):
            state["type"] = True
            return type_new
        return None
    return _rewrite_lines(raw, decide)


def unique_engine_name(base: str, taken, tag: str = "") -> str:
    """An engine (or engine-skeleton) name not already used in the destination."""
    existing = {t.lower() for t in taken}
    if base.lower() not in existing:
        return base
    cand = f"{base}_{tag}" if tag else f"{base}_copy"
    i = 2
    while cand.lower() in existing:
        cand = f"{base}_{tag}_{i}" if tag else f"{base}_copy_{i}"
        i += 1
    return cand


# --------------------------------------------------------------------------
# Texture extraction from a .mesh binary
#
# A siege-engine mesh is a `serialization::archive` stream of length-prefixed
# strings (4-byte little-endian length + that many bytes) and raw numbers. The
# texture paths a mesh uses are stored as such strings near the end of the file
# and appear NOWHERE in the text files — descr_engines only names the .mesh. So
# copying an engine without reading its mesh means guessing which textures it
# needs; this reads them exactly.
TEXTURE_EXTS = (".texture", ".dds", ".tga")
_MAX_STR = 260                          # a path longer than MAX_PATH isn't one


def mesh_textures(path: str | Path) -> List[str]:
    """Data-relative texture paths baked into a siege-engine ``.mesh`` file.

    Returns [] for a missing/unreadable file. Deduped, in file order.
    """
    p = Path(path)
    try:
        blob = p.read_bytes()
    except OSError:
        return []
    return textures_in_blob(blob)


def textures_in_blob(blob: bytes) -> List[str]:
    """The texture paths inside a mesh byte-string (see :func:`mesh_textures`)."""
    out: List[str] = []
    seen = set()
    i, end = 0, len(blob) - 4
    while i < end:
        n = struct.unpack_from("<I", blob, i)[0]
        if 5 <= n <= _MAX_STR and i + 4 + n <= len(blob):
            chunk = blob[i + 4:i + 4 + n]
            if all(32 <= c < 127 for c in chunk):
                s = chunk.decode("latin-1")
                if s.lower().endswith(TEXTURE_EXTS) and ("/" in s or "\\" in s):
                    rel = data_rel(s)
                    if rel.lower() not in seen:
                        seen.add(rel.lower())
                        out.append(rel)
                i += 4 + n
                continue
        i += 1
    return out
