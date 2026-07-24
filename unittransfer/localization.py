"""Parser for data/text/export_units.txt (M2TW unit localisation).

UTF-16 LE (BOM ff fe). Records are separated by a line ``¬-----`` (the ``¬``
character, U+00AC, also begins comment lines). Each unit contributes three keys:

    {<dict>}<Localized Name>
    {<dict>_descr}
    <long description — on the FOLLOWING line(s)>
    {<dict>_descr_short}
    <short description — on the FOLLOWING line(s)>

IMPORTANT: a key's value is whatever follows on the same line PLUS every
subsequent line up to the next ``{key}`` or ``¬`` line. In practice the name sits
on the key line while the descriptions sit on the lines after it, so reading only
the key line yields an empty description.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

ENCODING = "utf-16"          # Python picks LE/BE from the BOM on read
SEPARATOR = "¬-----"    # ¬-----
NOT = "¬"               # ¬

_ENTRY_RE = re.compile(r"^\{([^}]*)\}(.*)$")


@dataclass
class LocEntry:
    name: str = ""
    descr: Optional[str] = None
    descr_short: Optional[str] = None


@dataclass
class Localization:
    entries: Dict[str, LocEntry] = field(default_factory=dict)
    _lines: List[str] = field(default_factory=list)   # original lines (no line endings)
    _newline: str = "\r\n"

    def get(self, dictionary: str) -> Optional[LocEntry]:
        return self.entries.get(dictionary)

    def record_text(self, dictionary: str) -> str:
        """Build a fresh 3-line record block for a dictionary key."""
        e = self.entries.get(dictionary)
        if e is None:
            return ""
        nl = self._newline
        out = SEPARATOR + nl
        out += "{" + dictionary + "}" + (e.name or "") + nl
        out += "{" + dictionary + "_descr}" + (e.descr or "") + nl
        out += "{" + dictionary + "_descr_short}" + (e.descr_short or "") + nl
        return out


def parse_text(text: str) -> Localization:
    # normalise: detect newline style, split on \n keeping content
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.split("\n")
    lines = [ln[:-1] if ln.endswith("\r") else ln for ln in lines]

    entries: Dict[str, LocEntry] = {}
    i, n = 0, len(lines)
    while i < n:
        line = lines[i].strip("﻿").strip()
        if not line or line.startswith(NOT):
            i += 1
            continue
        m = _ENTRY_RE.match(line)
        if not m:
            i += 1
            continue
        key, value = m.group(1), m.group(2)
        # gather continuation lines: everything until the next key or ¬ line
        j = i + 1
        cont: List[str] = []
        while j < n:
            s = lines[j].strip("﻿").strip()
            if s.startswith("{") or s.startswith(NOT):
                break
            cont.append(lines[j])
            j += 1
        while cont and not cont[-1].strip():        # drop trailing blank lines
            cont.pop()
        full = value + ("\n" + "\n".join(cont) if cont else "")
        full = full.strip() if not value.strip() else full

        if key.endswith("_descr_short"):
            entries.setdefault(key[: -len("_descr_short")], LocEntry()).descr_short = full
        elif key.endswith("_descr"):
            entries.setdefault(key[: -len("_descr")], LocEntry()).descr = full
        else:
            entries.setdefault(key, LocEntry()).name = full
        i = j
    return Localization(entries=entries, _lines=lines, _newline=newline)


def parse_file(path: str | Path) -> Localization:
    return parse_text(Path(path).read_text(encoding=ENCODING))


def upsert_record(text: str, key: str, name: str, descr: str = "",
                  descr_short: str = "") -> str:
    """Replace the {key}/{key_descr}/{key_descr_short} lines in ``text`` in place,
    or append a fresh record block if the key is not present.
    """
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.split("\n")
    trimmed = [ln[:-1] if ln.endswith("\r") else ln for ln in lines]

    # Replace each key's FULL span (its line + continuation lines); replacing only
    # the key line would strand the previous description underneath it.
    blocks = [("{" + key + "}", _emit(key, name, inline=True)),
              ("{" + key + "_descr}", _emit(key + "_descr", descr)),
              ("{" + key + "_descr_short}", _emit(key + "_descr_short", descr_short))]
    found = False
    for marker, new_lines in blocks:
        span = _key_span(trimmed, marker)
        if span is None:
            continue
        start, end = span
        trimmed[start:end] = new_lines
        found = True
    if found:
        return nl.join(trimmed)

    # append a fresh record
    if not text.endswith("\n"):
        text += nl
    out = [SEPARATOR]
    for marker, new_lines in blocks:
        out.extend(new_lines)
    return text + nl.join(out) + nl


def _emit(key: str, value: Optional[str], inline: bool = False) -> List[str]:
    """Lines for one keyed entry.

    The name goes on the key line; descriptions go on the following line(s),
    matching how M2TW's own export_units.txt is laid out.
    """
    val = (value or "").strip("\r\n")
    if inline:
        return ["{" + key + "}" + val.replace("\n", " ")]
    if not val:
        return ["{" + key + "}"]
    return ["{" + key + "}"] + val.split("\n")


def _key_span(lines: List[str], marker: str):
    """(start, end) covering ``marker``'s line and its continuation lines."""
    for i, ln in enumerate(lines):
        if ln.strip("﻿").strip().startswith(marker):
            j = i + 1
            while j < len(lines):
                s = lines[j].strip("﻿").strip()
                if s.startswith("{") or s.startswith(NOT):
                    break
                j += 1
            return i, j
    return None
