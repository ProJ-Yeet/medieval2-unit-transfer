"""Files that are a run of ``<head> <name>`` records with ``keyword value`` lines.

Four of the game's campaign files are the same file with different words in it::

    rebel_type   Evil_Rebels      type    timber        faction   sicily
      category   peasant_revolt     trade_value  5        culture   gondor
      chance     0                  item    …/x.CAS       religion  islam
      unit       Cave Trolls2       icon    …/x.tga       symbol    …/x.CAS
      unit       Mordor Orcs        has_mine              horde_unit  Miners

A head line names the record, the lines under it are ``keyword value``, one
keyword may repeat (a rebel faction's ``unit``, a horde's ``horde_unit``), and
the whole thing is laid out in tab columns that a save must not disturb. That is
all :class:`Shape` says, and it is enough for a parser, a serialiser, a span map
and a field list to be written once.

This module was extracted from :mod:`unittransfer.minorfiles` when
``descr_sm_factions.txt`` turned out to need exactly it and nothing else: all 90
factions in the three installed mods parse byte-exact and re-render unchanged
against a :class:`Shape` and no new code at all. A fourth caller is the point at
which "the shape the minor files share" stops being a fact about the minor files.

The layer below is :mod:`unittransfer.keyblock`, which owns one record's lines —
the splice, the insert-at-its-place rule and the column-preserving rewrite. This
layer owns the *file*: where the records are, and how one of them is swapped out
without touching a byte of the rest.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import keyblock as kb
from . import triggers

#: these are plain 8-bit text like every other campaign file, and Latin-1 is the
#: codec that promises the bytes come back as they went in
ENCODING = "latin-1"

#: how they are split into lines — the EDCT's splitter, so a line number means
#: the same thing in every editor
split_lines = triggers.split_lines


class RecordError(kb.BlockError):
    """The text is not this kind of record, or an edit would write a bad file."""


# ---------------------------------------------------------------------------
# a file held as its own lines



@dataclass
class LineFile:
    """Any of these files, kept verbatim with records indexed into it."""
    lines: List[str] = field(default_factory=list)
    newline: str = "\r\n"
    trailing_newline: bool = True
    warnings: List[str] = field(default_factory=list)

    @property
    def items(self) -> List:
        """Every record in this file — one name for five different lists.

        The editor is one module over five files, so it has to be able to say
        "the records of this file" without knowing which file it is holding.
        """
        return []

    def text(self) -> str:
        """The file exactly as it was read — what every round-trip test asserts."""
        out = self.newline.join(self.lines)
        return out + self.newline if self.trailing_newline and self.lines else out

    def _rebuilt(self, lines: List[str]) -> str:
        out = self.newline.join(lines)
        return out + self.newline if self.trailing_newline and lines else out

    def replace(self, start: int, end: int, block: str) -> str:
        """The whole file with lines ``[start:end)`` swapped for ``block``.

        One function for all five files: a save is always "this record's lines,
        and only this record's lines, become that text".
        """
        body, _, _ = split_lines(block)
        while body and not body[-1].strip():
            body.pop()
        lines = list(self.lines)
        lines[start:end] = body
        return self._rebuilt(lines)


def head_of(code: str) -> Tuple[str, str]:
    """``"category  peasant_revolt"`` -> ``("category", "peasant_revolt")``."""
    words = code.split()
    if not words:
        return "", ""
    return words[0], code[len(words[0]):].strip()


# ---------------------------------------------------------------------------
# one flat-record format, described rather than coded twice


@dataclass(frozen=True)
class Shape:
    """One flat-record format, described rather than coded twice."""
    rel: str                          # under the mod's data/
    label: str
    kw: str                           # the head keyword: `rebel_type`, `type`
    noun: str                         # what one record is called in a message
    order: Tuple[str, ...]            # body keys, in the order real files write them
    required: Tuple[str, ...]
    flags: Tuple[str, ...] = ()
    list_keys: Tuple[str, ...] = ()
    repeat_kw: str = ""               # a key that may appear many times (`unit`)
    #: file-level lines above the first record (`mine <path>` in the resources file)
    preamble_keys: Tuple[str, ...] = ()

    @property
    def fields(self) -> Dict[str, str]:
        """request field name -> keyword. The keywords are already snake_case."""
        return {k: k for k in self.order}


#: ``descr_rebel_factions.txt`` — all 68 records in the three installed mods write

@dataclass
class Repeat:
    """One line of a key that may appear many times (a rebel's ``unit``)."""
    value: str = ""
    line: int = 0

    def as_dict(self) -> Dict:
        return {"value": self.value, "line": self.line}


@dataclass
class Record:
    """One flat record: a name, its ``keyword value`` lines, and its repeats."""
    name: str = ""
    values: Dict[str, str] = field(default_factory=dict)
    lines: Dict[str, int] = field(default_factory=dict)
    repeats: List[Repeat] = field(default_factory=list)
    start: int = 0
    end: int = 0
    warnings: List[str] = field(default_factory=list)

    def get(self, key: str) -> str:
        return self.values.get(key, "")

    def flag(self, key: str) -> bool:
        return key in self.lines

    def as_dict(self, shape: Shape) -> Dict:
        d: Dict = {"name": self.name, "start": self.start, "end": self.end,
                   "units": [r.value for r in self.repeats]}
        for key in shape.order:
            d[key] = self.flag(key) if key in shape.flags else self.get(key)
        return d


@dataclass
class RecordFile(LineFile):
    """A whole flat-record file."""
    shape: Optional[Shape] = None
    records: List[Record] = field(default_factory=list)
    #: the file-level lines above the first record: keyword -> (value, line)
    preamble: Dict[str, Tuple[str, int]] = field(default_factory=dict)

    @property
    def items(self) -> List[Record]:
        return self.records

    def get(self, name: str) -> Optional[Record]:
        return next((r for r in self.records if r.name == name), None)

    def by_name(self) -> Dict[str, Record]:
        return {r.name: r for r in self.records}

    def block_text(self, rec: Record) -> str:
        return self.newline.join(self.lines[rec.start:rec.end])


def parse_records(shape: Shape, text: str) -> RecordFile:
    """Read a whole flat-record file. Never raises: anything odd is a warning."""
    lines, newline, trailing = split_lines(text)
    rf = RecordFile(lines=lines, newline=newline, trailing_newline=trailing,
                    shape=shape)
    cur: Optional[Record] = None
    for i, raw in enumerate(lines):
        code = kb.code_of(raw)
        if not code:
            continue
        key, value = head_of(code)
        if key == shape.kw:
            cur = Record(name=value, start=i, end=i + 1)
            if not value:
                cur.warnings.append(f"line {i + 1}: this {shape.noun} has no name")
            rf.records.append(cur)
            continue
        if cur is None:
            if key in shape.preamble_keys:
                rf.preamble[key] = (value, i)
            else:
                rf.warnings.append(
                    f"line {i + 1}: `{key}` before the first `{shape.kw}` line")
            continue
        if shape.repeat_kw and key == shape.repeat_kw:
            # the whole rest of the line: unit types have spaces in them
            cur.repeats.append(Repeat(value=value, line=i))
            cur.end = i + 1
            continue
        if key not in shape.order:
            cur.warnings.append(f"line {i + 1}: `{key}` is not a {shape.noun} line")
        elif key in cur.lines:
            cur.warnings.append(f"line {i + 1}: a second `{key}` line")
        cur.values[key] = value
        cur.lines[key] = i
        cur.end = i + 1

    for rec in rf.records:
        rf.warnings.extend(f"{rec.name or '(unnamed)'}: {w}" for w in rec.warnings)
    return rf


def parse_record_file(shape: Shape, path: str | Path) -> RecordFile:
    return parse_records(shape, kb.read_text(Path(path), ENCODING))


def parse_record_block(shape: Shape, text: str) -> Record:
    """Read ONE record, as a code view pane holds it."""
    rf = parse_records(shape, text if text.endswith("\n") else text + "\n")
    if not rf.records:
        raise RecordError(f"a {shape.noun} starts with a `{shape.kw} <name>` line — "
                         "this text has none", 1)
    if len(rf.records) > 1:
        raise RecordError(
            f"this text holds {len(rf.records)} {shape.noun}s — one at a time",
            rf.records[1].start + 1)
    return rf.records[0]


def render_record(shape: Shape, base: str, edits: Optional[Dict] = None) -> str:
    """Apply GUI edits to one record and give back its text.

    ``edits`` is the save request's own shape — the body keywords by name, plus
    ``name`` and (for rebels) ``units: [str]`` — and every key is optional. What
    is not named is not touched, so a form that posts every box does not
    reformat the lines nobody edited.
    """
    edits = edits or {}
    rec = parse_record_block(shape, base)
    lines, newline, _ = split_lines(base)
    sp = kb.Splice(lines)

    if "name" in edits:
        name = str(edits["name"] or "").strip()
        if not name:
            raise RecordError(f"a {shape.noun} needs a name", rec.start + 1)
        if name != rec.name:
            sp.replace(rec.start, kb.sub_value(lines[rec.start], shape.kw, name))

    indent = kb.body_indent(lines, rec.lines, rec.start)
    try:
        kb.edit_keys(sp, lines, rec.lines, rec.values, edits, shape.fields,
                     order=shape.order, required=shape.required, flags=shape.flags,
                     list_keys=shape.list_keys, anchor=rec.start, indent=indent,
                     noun=shape.noun, align=True)
    except kb.BlockError as e:
        raise RecordError(e.message, e.line) from None
    if shape.repeat_kw and "units" in edits:
        edit_repeats(sp, lines, rec.repeats, list(edits["units"] or []),
                     shape.repeat_kw, indent, rec.end - 1)
    return newline.join(sp.result())


def edit_repeats(sp: kb.Splice, lines: List[str], olds: List[Repeat],
                 wanted: List[str], keyword: str, indent: str,
                 last_line: int) -> None:
    """Rewrite a repeated single-value key; add or drop only what moved.

    Index-aligned with what is there, like the ``Effect`` lines of a trait: an
    untouched entry keeps its exact line, tab stops and all, and a new one copies
    the indent of the entry above it.
    """
    for i in range(min(len(olds), len(wanted))):
        value = str(wanted[i] or "").strip()
        if value == olds[i].value:
            continue
        if not value:
            raise RecordError(f"a `{keyword}` line needs a value", olds[i].line + 1)
        sp.replace(olds[i].line, kb.sub_value(lines[olds[i].line], keyword, value))
    if len(wanted) > len(olds):
        prefix = (kb.head_prefix(lines[olds[-1].line], keyword) if olds
                  else indent + keyword + " ")
        rows = [prefix + str(v).strip()
                for v in wanted[len(olds):] if str(v).strip()]
        sp.after(olds[-1].line if olds else last_line, rows)
    elif len(wanted) < len(olds):
        for old in olds[len(wanted):]:
            sp.drop(old.line)


def new_record(shape: Shape, edits: Dict) -> str:
    """A whole record written from scratch, in the order the real files write it."""
    name = str(edits.get("name") or "").strip()
    if not name:
        raise RecordError(f"a new {shape.noun} needs a name")
    out = [f"{shape.kw}\t\t\t{name}"]
    out += ["\t" + ln.strip() for ln in
            kb.new_lines(edits, shape.fields, shape.order, shape.flags,
                         shape.list_keys, "")]
    for value in (edits.get("units") or []):
        if str(value).strip():
            out.append(f"\t{shape.repeat_kw}\t\t\t{str(value).strip()}")
    return "\n".join(out)


def replace_record(rf: RecordFile, rec: Record, block: str) -> str:
    """The whole file with one record's lines swapped for ``block``."""
    return rf.replace(rec.start, rec.end, block)


def record_spans(shape: Shape, block: str) -> Dict[str, List[List[int]]]:
    """``{label: [[first, last]]}``, 1-based, for one record."""
    rec = parse_record_block(shape, block)
    spans: Dict[str, List[List[int]]] = {"name": [[rec.start + 1, rec.start + 1]]}
    for key, line in rec.lines.items():
        spans[key] = [[line + 1, line + 1]]
    for n, rep in enumerate(rec.repeats, 1):
        spans[f"{shape.repeat_kw}#{n}"] = [[rep.line + 1, rep.line + 1]]
    return spans


def record_fields(shape: Shape, block: str) -> List[Tuple[str, str]]:
    """``[(label, value)]`` for one record, in the order its lines appear."""
    rec = parse_record_block(shape, block)
    out = [("name", rec.name)]
    for key, _ in sorted(rec.lines.items(), key=lambda kv: kv[1]):
        out.append((key, "yes" if key in shape.flags else rec.values.get(key, "")))
    for n, rep in enumerate(rec.repeats, 1):
        out.append((f"{shape.repeat_kw}#{n}", rep.value))
    return out


def check_records(shape: Shape, rf: RecordFile) -> List[Dict]:
    """The findings any flat-record file can have, whatever it holds.

    Three, and each is a file the game will not load or will silently misread:
    a name used twice, a required line missing, and lines out of the order every
    real record writes them in. What a *particular* file means by its values —
    that ``brigands`` is one of four rebel categories, that a faction's culture
    must be one this mod defines — belongs to that file's own module.
    """
    out: List[Dict] = []
    seen: Dict[str, int] = {}

    def add(kind: str, name: str, line: int, message: str) -> None:
        out.append({"kind": kind, "name": name, "line": line + 1, "message": message})

    for rec in rf.records:
        if rec.name in seen:
            add("duplicate", rec.name, rec.start,
                f"`{rec.name}` is already defined on line {seen[rec.name] + 1} — "
                "names must be unique")
        else:
            seen[rec.name] = rec.start
        for key in shape.required:
            if key not in rec.lines:
                add("missing-line", rec.name, rec.start,
                    f"no `{key}` line — the game will not load this {shape.noun}")
        order = [k for k in shape.order if k in rec.lines]
        placed = sorted(order, key=lambda k: rec.lines[k])
        if order != placed:
            add("line-order", rec.name, rec.lines[placed[0]],
                "the lines are in the order " + ", ".join(placed) + " but every "
                f"real {shape.noun} writes them " + ", ".join(order))
    return out
