"""Read and write M2TW's compiled ``*.txt.strings.bin`` localisation archives.

The game reads the ``.bin``, never the ``.txt`` beside it, and only recompiles
one when it is missing. Until this module existed the whole of our answer to that
was :mod:`unittransfer.cleaner` — delete the ``.bin`` and let the next launch
rebuild it. That works, but it throws away a file we could simply have kept
correct, and it cannot show anyone what is inside one.

Format
------
Confirmed byte-for-byte against all 81 ``.strings.bin`` files shipped by the
three test mods (see ``tests/test_stringsbin.py``)::

    u16  style          1 = untagged, 2 = tagged
    u16  flavour        2048 in every file anyone has ever seen
    u32  count
    count × record      tagged:   <str tag> <str value>
                        untagged: <str value>
    u32  index_count    tagged files only
    index_count × <str>

    <str> = u16 length in UTF-16 code units, then that many LE code units

Two details the reference tool's codec gets wrong, and which cost real files:

* **``count`` is 32 bits, not 16.** Reading it as ``u16`` plus a padding word
  happens to agree while a file holds under 65 536 entries, and silently reads
  half a file when it doesn't — ``names.txt`` in Third Age already carries
  20 757, and a merged names file goes past the line.
* **There is a trailing index section**, not a single zero word. It is a list of
  tags in the order the source ``.txt`` had them (the entries themselves are
  sorted), and it can be far longer than the entry list — Third Age's
  ``export_buildings`` has 480 entries and 13 482 index strings, mostly stale
  vanilla tags. Writing a lone zero word there truncates the file.

The index is bookkeeping we cannot regenerate faithfully, and the game plainly
does not need it: many shipped files have an empty one. So it is carried through
an edit **verbatim** and left empty when we compile a ``.bin`` from scratch —
never invented.

Untagged files (``battle``, ``shared``, ``strat``, ``tooltips``) are the ones
alpaca's converter refused: their strings are addressed by position, so there is
nothing to name a row by. We still read and write them — a value can be edited in
place by index, which is all anyone could do with them anyway.

Text form
---------
:func:`to_txt` / :func:`from_txt` speak the ``{tag}value`` line format of the
``.txt`` files themselves, with an embedded newline written ``\\n`` exactly as
alpaca's converter wrote it. That escape is unambiguous here: across all 81 files
no value contains a backslash at all, while 16 723 contain a real newline.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

#: ``style`` word: entries are ``<tag> <value>`` pairs and can be looked up by name
TAGGED = 2
#: ``style`` word: entries are bare strings, addressed only by their position
UNTAGGED = 1
#: the second header word — constant in every file examined, but carried through
FLAVOUR = 2048

#: the ``.txt`` beside a ``.bin`` is UTF-16 with a BOM, and opens with a ¬ comment
TXT_ENCODING = "utf-16"
COMMENT = "\u00ac"


class StringsBinError(Exception):
    """The bytes are not a ``.strings.bin`` (with a byte offset, where known)."""

    def __init__(self, message: str, offset: int = -1):
        super().__init__(message)
        self.message = message
        self.offset = offset


@dataclass
class StringsBin:
    """One decoded archive: its header, its entries, and its index section.

    ``tags`` is empty for an untagged file; ``values`` always has one item per
    entry, so a row is ``(tags[i] if tagged else '', values[i])`` either way.
    """
    style: int = TAGGED
    flavour: int = FLAVOUR
    tags: List[str] = field(default_factory=list)
    values: List[str] = field(default_factory=list)
    #: the trailing tag index, kept exactly as read — see the module docstring
    index: List[str] = field(default_factory=list)

    @property
    def tagged(self) -> bool:
        return self.style == TAGGED

    def __len__(self) -> int:
        return len(self.values)

    def rows(self) -> List[Tuple[str, str]]:
        """``[(tag, value), …]`` — tag is ``''`` throughout an untagged file."""
        if not self.tagged:
            return [("", v) for v in self.values]
        return list(zip(self.tags, self.values))

    def pairs(self) -> Dict[str, str]:
        """``{tag: value}`` for a tagged file (last wins on a duplicate tag)."""
        return dict(self.rows()) if self.tagged else {}

    def index_of(self, tag: str) -> int:
        """Position of ``tag``, or -1. Case-sensitive: so is the game."""
        try:
            return self.tags.index(tag)
        except ValueError:
            return -1

    def get(self, tag: str) -> Optional[str]:
        i = self.index_of(tag)
        return self.values[i] if i >= 0 else None

    # ---- edits -----------------------------------------------------------
    def set_value(self, pos: int, value: str) -> None:
        """Replace the value at ``pos`` (the only edit an untagged file allows)."""
        if not 0 <= pos < len(self.values):
            raise StringsBinError(f"no entry at position {pos}")
        self.values[pos] = value

    def set(self, tag: str, value: str) -> int:
        """Set ``tag``'s value, adding the entry in sort position if it is new.

        Every tagged file ships with its tags in code-point order — all 69 of
        them — and the game binary-searches them, so a new tag goes where that
        order puts it rather than on the end.
        """
        if not self.tagged:
            raise StringsBinError("this file's entries have no tags — edit by position")
        i = self.index_of(tag)
        if i >= 0:
            self.values[i] = value
            return i
        i = _bisect(self.tags, tag)
        self.tags.insert(i, tag)
        self.values.insert(i, value)
        return i

    def remove(self, tag: str) -> bool:
        i = self.index_of(tag)
        if i < 0:
            return False
        del self.tags[i]
        del self.values[i]
        return True

    def sorted_ok(self) -> bool:
        """True when the tags are in the order the game expects to search."""
        return not self.tagged or self.tags == sorted(self.tags)


def _bisect(tags: List[str], tag: str) -> int:
    lo, hi = 0, len(tags)
    while lo < hi:
        mid = (lo + hi) // 2
        if tags[mid] < tag:
            lo = mid + 1
        else:
            hi = mid
    return lo


# ---------------------------------------------------------------------------
# the codec


def _read_str(data: bytes, pos: int) -> Tuple[str, int]:
    if pos + 2 > len(data):
        raise StringsBinError("file ends where a string length was expected", pos)
    (units,) = struct.unpack_from("<H", data, pos)
    pos += 2
    end = pos + units * 2
    if end > len(data):
        raise StringsBinError(
            f"a string says it is {units} characters long but only "
            f"{(len(data) - pos) // 2} are left in the file", pos - 2)
    # surrogate pairs are legal UTF-16; none of the shipped files use one, but
    # decoding leniently is better than refusing to open a file over one byte
    return data[pos:end].decode("utf-16-le", "replace"), end


def _write_str(out: bytearray, s: str) -> None:
    raw = s.encode("utf-16-le", "surrogatepass")
    units = len(raw) // 2
    if units > 0xFFFF:
        raise StringsBinError(
            f"a single string cannot exceed 65535 characters (this one is {units})")
    out += struct.pack("<H", units)
    out += raw


def decode(data: bytes) -> StringsBin:
    """Decode a ``.strings.bin``. Raises :class:`StringsBinError` if it isn't one."""
    if len(data) < 8:
        raise StringsBinError("too short to be a .strings.bin (needs an 8-byte header)", 0)
    style, flavour, count = struct.unpack_from("<HHI", data, 0)
    if style not in (TAGGED, UNTAGGED):
        raise StringsBinError(
            f"unknown .strings.bin style {style} (expected 1 = untagged or 2 = tagged)", 0)
    per = 2 if style == TAGGED else 1
    if 8 + count * per * 2 > len(data):
        raise StringsBinError(
            f"header claims {count} entries, which cannot fit in {len(data)} bytes", 4)
    sb = StringsBin(style=style, flavour=flavour)
    pos = 8
    for _ in range(count):
        if style == TAGGED:
            tag, pos = _read_str(data, pos)
            sb.tags.append(tag)
        value, pos = _read_str(data, pos)
        sb.values.append(value)
    if style == TAGGED:
        if pos + 4 > len(data):
            raise StringsBinError("file ends before its tag index", pos)
        (index_count,) = struct.unpack_from("<I", data, pos)
        pos += 4
        for _ in range(index_count):
            s, pos = _read_str(data, pos)
            sb.index.append(s)
    if pos != len(data):
        raise StringsBinError(
            f"{len(data) - pos} unexplained bytes after the last string", pos)
    return sb


def encode(sb: StringsBin) -> bytes:
    """Re-encode an archive. ``encode(decode(b)) == b`` for every shipped file."""
    if sb.tagged and len(sb.tags) != len(sb.values):
        raise StringsBinError(
            f"{len(sb.tags)} tags but {len(sb.values)} values — the two must match")
    out = bytearray(struct.pack("<HHI", sb.style, sb.flavour, len(sb.values)))
    for i, value in enumerate(sb.values):
        if sb.tagged:
            _write_str(out, sb.tags[i])
        _write_str(out, value)
    if sb.tagged:
        out += struct.pack("<I", len(sb.index))
        for s in sb.index:
            _write_str(out, s)
    return bytes(out)


def read(path: str | Path) -> StringsBin:
    return decode(Path(path).read_bytes())


def peek(path: str | Path) -> Dict:
    """``{style, flavour, count, tagged}`` from the 8-byte header alone.

    What a file listing needs. Decoding a whole folder of archives to count their
    entries costs half a second on Third Age — and the count is right there in the
    header, so nobody should pay that to draw a list.
    """
    with Path(path).open("rb") as fh:
        head = fh.read(8)
    if len(head) < 8:
        raise StringsBinError("too short to be a .strings.bin (needs an 8-byte header)", 0)
    style, flavour, count = struct.unpack("<HHI", head)
    if style not in (TAGGED, UNTAGGED):
        raise StringsBinError(
            f"unknown .strings.bin style {style} (expected 1 = untagged or 2 = tagged)", 0)
    return {"style": style, "flavour": flavour, "count": count,
            "tagged": style == TAGGED}


def write(path: str | Path, sb: StringsBin) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(encode(sb))


# ---------------------------------------------------------------------------
# the text form the .txt files themselves use


def escape(value: str) -> str:
    """Value -> one line of ``.txt``: a real newline becomes ``\\n``."""
    return value.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")


def unescape(text: str) -> str:
    """One line of ``.txt`` -> value. No file uses a backslash for anything else."""
    return text.replace("\\n", "\n")


def record_text(tag: str, value: str) -> str:
    """The one line a tagged entry occupies in the ``.txt`` — the code view's text."""
    return "{" + tag + "}" + escape(value)


def parse_record(text: str) -> Tuple[str, str]:
    """Read back one ``{tag}value`` line. Raises :class:`StringsBinError` if it isn't one."""
    s = text.strip("\ufeff").strip("\r\n")
    if "\n" in s:
        raise StringsBinError(
            "an entry is one line — write a line break as \\n rather than pressing Enter")
    s = s.strip()
    if not s.startswith("{"):
        raise StringsBinError("an entry starts with its tag in braces: {tag}text")
    close = s.find("}")
    if close < 0:
        raise StringsBinError("the tag's closing brace is missing")
    tag = s[1:close]
    if not tag.strip():
        raise StringsBinError("the tag is empty")
    return tag, unescape(s[close + 1:])


def to_txt(sb: StringsBin, newline: str = "\r\n") -> str:
    """The whole archive as its ``.txt`` counterpart (tagged files only)."""
    if not sb.tagged:
        raise StringsBinError(
            "this file's entries have no tags, so there is no .txt form of it")
    lines = [COMMENT] + [record_text(t, v) for t, v in sb.rows()]
    return newline.join(lines) + newline


#: what the game trims off a value when it compiles a ``.txt``: tabs and line
#: breaks, but NOT spaces — ``{AZTECS_WEAKNESS} `` compiles to a single space and
#: a trailing space survives too (measured, see :func:`from_txt`)
_EDGE = "\t\r\n"


def from_txt(text: str) -> List[Tuple[str, str]]:
    """Read a ``.txt`` localisation file into ``[(tag, value), …]``.

    This reproduces what the game's own compiler does, established by reading
    Third Age's ``export_units.txt`` and ``expanded.txt`` and comparing against
    the ``.bin`` files the game had written from them — 3393 of 3395 entries
    identical, the two exceptions being keys the mod edited after that ``.bin``
    was last built. The rules that came out of it:

    * comment lines (``¬``) and blanks are skipped;
    * a value continued on the lines below its key — which ``export_units.txt``
      does for every description — is folded back into one value with newlines,
      because that is how the compiled file stores it;
    * the result is trimmed of tabs and line breaks but **not** of spaces;
    * ``\\n`` in the text becomes a real newline.
    """
    lines = [ln[:-1] if ln.endswith("\r") else ln
             for ln in text.lstrip("\ufeff").split("\n")]
    out: List[Tuple[str, str]] = []
    i, n = 0, len(lines)
    while i < n:
        s = lines[i].strip("\ufeff")
        i += 1
        stripped = s.strip()
        if not stripped or stripped.startswith(COMMENT) or not stripped.startswith("{"):
            continue
        close = s.find("}")
        if close < 0:
            continue
        tag = s[s.find("{") + 1:close]
        value = s[close + 1:]
        cont: List[str] = []
        while i < n:
            nxt = lines[i].strip("\ufeff").strip()
            if nxt.startswith("{") or nxt.startswith(COMMENT):
                break
            cont.append(lines[i])
            i += 1
        while cont and not cont[-1].strip():
            cont.pop()
        if cont:
            value = (value + "\n" + "\n".join(cont)) if value.strip() else "\n".join(cont)
        out.append((tag, unescape(value.strip(_EDGE))))
    return out


def upsert_txt(body: str, writes: Dict[str, str]) -> str:
    """Set these tags in a ``.txt``, leaving every other line exactly alone.

    A tag already in the file has its line rewritten *and its continuation lines
    dropped* — a value may be written across the lines below its key (that is how
    the game's own compiler reads it, see :func:`from_txt`), so replacing only
    the ``{tag}`` line would leave the old wording behind as an orphan and the
    compiled result would still say it. A tag that is not there is appended.

    Used by the editors that own a record whose text keys live in one of these
    files — the traits editor's ``export_VnVs.txt`` and the ancillaries editor's
    ``export_ancillaries.txt``.
    """
    nl = "\r\n" if "\r\n" in body else "\n"
    lines = [ln[:-1] if ln.endswith("\r") else ln for ln in body.split("\n")]
    out: List[str] = []
    left = dict(writes)
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        stripped = line.lstrip("﻿").strip()
        tag = (stripped[1:stripped.find("}")]
               if stripped.startswith("{") and "}" in stripped else "")
        if tag and tag in left:
            out.append(f"{{{tag}}}{escape(left.pop(tag))}")
            i += 1
            while i < n:                    # its continuation lines go with it
                nxt = lines[i].lstrip("﻿").strip()
                if nxt.startswith("{") or nxt.startswith(COMMENT) or not nxt:
                    break
                i += 1
            continue
        out.append(line)
        i += 1
    while out and not out[-1].strip():
        out.pop()
    out.extend(f"{{{tag}}}{escape(value)}" for tag, value in left.items())
    return nl.join(out) + nl


def compile_txt(text: str, template: Optional[StringsBin] = None) -> StringsBin:
    """Build an archive from a ``.txt``, in the order the game searches.

    ``template`` lends its header words and its tag index — used when a ``.bin``
    already exists beside the ``.txt``, so recompiling changes only what the text
    changed. With no template the index is left empty, which is a state plenty of
    shipped files are already in.
    """
    rows = from_txt(text)
    seen: Dict[str, str] = {}
    for tag, value in rows:           # a repeated tag: the last one wins, as in game
        seen[tag] = value
    tags = sorted(seen)
    sb = StringsBin(style=TAGGED,
                    flavour=template.flavour if template else FLAVOUR,
                    tags=tags, values=[seen[t] for t in tags],
                    index=list(template.index) if template else [])
    return sb


# ---------------------------------------------------------------------------
# keeping a .bin in step with the .txt an edit just rewrote


def txt_path_for(bin_path: str | Path) -> Path:
    """``…/export_units.txt.strings.bin`` -> ``…/export_units.txt``."""
    p = Path(bin_path)
    return p.with_name(p.name[: -len(".strings.bin")]) if p.name.endswith(".strings.bin") else p


def bin_path_for(txt_path: str | Path) -> Path:
    p = Path(txt_path)
    return p.with_name(p.name + ".strings.bin")


def refresh_from_txt(txt_path: str | Path) -> Dict:
    """Recompile ``<txt>.strings.bin`` from the ``.txt`` we just wrote.

    The point of the whole module: the game shows the OLD text until its cache
    agrees with the file we edited, and this makes it agree instead of deleting
    it and making the next launch do the work. Returns a small record; never
    raises — a cache that could not be refreshed is the caller's cue to fall back
    to deleting it, not a reason to fail a finished edit.
    """
    txt = Path(txt_path)
    target = bin_path_for(txt)
    out: Dict = {"file": str(target), "rebuilt": False}
    if not txt.exists():
        return {**out, "error": f"no {txt.name} to compile from"}
    try:
        text = txt.read_text(encoding=TXT_ENCODING)
    except (OSError, UnicodeError) as e:
        return {**out, "error": f"could not read {txt.name}: {e}"}
    template = None
    if target.exists():
        try:
            template = read(target)
        except (OSError, StringsBinError):
            template = None          # unreadable cache: compile a fresh one over it
        else:
            if not template.tagged:
                return {**out, "error": f"{target.name} has no tags — refusing to rebuild it"}
    try:
        sb = compile_txt(text, template)
        write(target, sb)
    except (OSError, StringsBinError) as e:
        return {**out, "error": f"could not write {target.name}: {e}"}
    out["rebuilt"] = True
    out["entries"] = len(sb)
    return out


def load_pairs(path: str | Path) -> Dict[str, str]:
    """``{tag: value}`` from a ``.strings.bin`` — ``{}`` if it can't be read.

    The read-through other modules use when a mod ships the compiled file and
    not the ``.txt`` beside it, which is common once a mod has been released.
    """
    try:
        sb = read(path)
    except (OSError, StringsBinError):
        return {}
    return sb.pairs()
