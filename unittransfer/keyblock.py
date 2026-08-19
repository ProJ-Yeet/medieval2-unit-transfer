"""Blocks of ``Keyword value`` lines whose order the engine cares about.

Traits and ancillaries are the same language written twice. Squid's guide
documents them in one document for that reason, :mod:`unittransfer.triggers`
already serves the bottom half of both files, and this module is the top half:
a record is a name line, then a fixed sequence of optional and required
``Keyword value`` lines, then any number of ``Effect Attribute Points``::

    Ancillary iron_guard          Trait NaturalMilitarySkill
      Type follower                 Characters family
      Transferable 0                Hidden
      Image iron_guard.tga          ExcludeCultures greek
      Description iron_desc         …
      Effect Command 1              Effect Command 1

Both formats punish the same two mistakes, so the handling is here once rather
than in each of them:

**Line order is load-bearing.** An EDCT header in the wrong order does not
report a bad trait — it stops the engine recognising every trait defined after
it. So :func:`edit_keys` inserts a line at its place in the format's own order,
never appends, and works that place out from the lines that are already there.

**Absent is not empty.** ``Hidden`` and ``Unique`` are whole lines with no
value; an optional key that is missing means "no", not "blank". Editing one to
nothing deletes its line, and a required one blanked is refused rather than
written as a bare keyword the game will not load.

And one thing neither format survives without: **an edit is a splice.** These
files are hand-written and full of comment banners, mixed tabs and blank lines
inside a record. A form posts every box on save, so a value that has not changed
must not rewrite its line — see :func:`same_value`, which compares a list as a
list because 128 real traits write ``greek,  noldor`` with two spaces.
"""
from __future__ import annotations

import difflib
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Sequence


class BlockError(Exception):
    """The text is not this kind of block, or an edit would write a bad file."""

    def __init__(self, message: str, line: int = 0):
        super().__init__(message)
        self.message = message
        self.line = line


# ---------------------------------------------------------------------------
# reading and writing, with the line endings left alone


def read_text(path: Path, encoding: str) -> str:
    """Read a file with its line endings exactly as they are.

    ``Path.read_text`` turns every ``\\r\\n`` into ``\\n`` on the way in and
    ``Path.write_text`` turns every ``\\n`` back into ``\\r\\n`` on the way out —
    fine for the editors whose serialisers emit ``\\n`` and let Windows put the
    ``\\r`` back, but not for these, whose whole claim is that the bytes come
    back as they went in. So they do their own I/O and never let the platform
    decide what a line ending is.
    """
    with open(path, "r", encoding=encoding, newline="") as fh:
        return fh.read()


def write_text(path: Path, text: str, encoding: str) -> None:
    """Write text exactly as given — see :func:`read_text`."""
    with open(path, "w", encoding=encoding, newline="") as fh:
        fh.write(text)


# ---------------------------------------------------------------------------
# reading the shapes


def newline_of(text: str) -> str:
    """The line ending this text mostly uses — ``\\r\\n`` unless ``\\n`` is commoner.

    Asked before appending to a file that already exists, so a block added to
    it is written the way the rest of it is written. Third Age Reforged's
    ``descr_projectile.txt`` is 3353 CRLF lines and 5 lone LFs; a file is not
    obliged to be consistent, so the question is which ending is the norm here,
    not which one the file uses.
    """
    crlf = text.count(chr(13) + chr(10))
    lf = text.count(chr(10)) - crlf
    return chr(10) if lf > crlf else chr(13) + chr(10)


def to_newline(text: str, newline: str) -> str:
    """Rewrite every line ending in ``text`` as ``newline``."""
    body = text.replace(chr(13) + chr(10), chr(10)).replace(chr(13), chr(10))
    return body.replace(chr(10), newline) if newline != chr(10) else body


#: A UTF-8 byte-order mark as a latin-1 read sees it, plus the decoded form.
#: Notepad writes one into anything it saves as UTF-8, and a game file whose
#: FIRST line is a record head (DaC's descr_sm_factions.txt opens on
#: `faction`, not a comment) then has that head glued to the mark: the line
#: stops being recognised and the record vanishes with no error anywhere.
BOMS = ("\xef\xbb\xbf", "\ufeff")


def without_bom(text: str) -> str:
    """``text`` with a leading byte-order mark removed, if it has one."""
    for mark in BOMS:
        if text.startswith(mark):
            return text[len(mark):]
    return text


def code_of(line: str) -> str:
    """The code part of a line. ``;`` starts a comment anywhere it appears.

    A leading byte-order mark is dropped here rather than on read, because the
    mark is part of the file and has to be written back: this is the one place
    that turns a line into a KEYWORD, and nothing splices its result back (it
    strips the indentation, so nothing could).
    """
    return without_bom(line.split(";", 1)[0].strip())


def split_list(value: str) -> List[str]:
    """``"admiral,  family"`` -> ``["admiral", "family"]``. Spacing is not data."""
    return [p.strip() for p in value.split(",") if p.strip()]


def indent_of(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def body_indent(lines: List[str], present: Dict[str, int], start: int) -> str:
    """The indent a new line in this block should copy.

    These files are lined up by eye — some with two spaces, some with tabs — and
    a new line landing in a different column is the first thing anyone notices.
    """
    if present:
        return indent_of(lines[min(present.values())])
    return indent_of(lines[start]) + "  "


def is_int(s: str) -> bool:
    try:
        int(s)
        return True
    except ValueError:
        return False


def and_list(items) -> str:
    """``[a, b, c]`` as ``"`a`, `b` and `c`"`` — for a finding's message."""
    items = list(items)
    if len(items) < 2:
        return "".join(f"`{i}`" for i in items)
    return ", ".join(f"`{i}`" for i in items[:-1]) + f" and `{items[-1]}`"


# ---------------------------------------------------------------------------
# writing a line back


def keep_comment(line: str, new_code: str) -> str:
    """``new_code`` plus whatever comment the old line carried."""
    code, sep, comment = line.partition(";")
    if not sep:
        return new_code
    # keep the spacing that sat before the ';' so a column of comments stays one
    pad = code[len(code.rstrip()):]
    return new_code + pad + ";" + comment


def sub_head(line: str, keyword: str, value: str) -> str:
    """Replace a ``<keyword> <value>`` line's value, keeping indent and comment."""
    return keep_comment(line, indent_of(line) + keyword + (f" {value}" if value else ""))


def head_prefix(line: str, keyword: str) -> str:
    """``"\\tcategory\\t\\t\\t"`` — a line's indent, keyword and the gap after it.

    The campaign files the minor-files module reads are laid out in tab columns
    rather than by one space, and a rewritten value that lands in a different
    column is the first thing anyone notices about a save. So the gap a line
    already has is data, and it is copied rather than normalised — both when a
    value is replaced and when a new line joins a run of them.
    """
    code = line.partition(";")[0]
    indent = indent_of(code)
    after = code[len(indent) + len(keyword):]
    return indent + keyword + (after[: len(after) - len(after.lstrip())] or " ")


def sub_value(line: str, keyword: str, value: str) -> str:
    """Replace the value on a ``<keyword><gap><value>`` line, keeping the gap."""
    if not value:
        return keep_comment(line, indent_of(line) + keyword)
    return keep_comment(line, head_prefix(line, keyword) + value)


#: What a tab is worth in these files. Measured: at 4, **1731 of the ~1800
#: value-bearing lines in the three installed ``descr_sm_factions.txt`` start in
#: column 28** — one dominant column, which is what "laid out in tab columns"
#: actually means. At 8 the same lines scatter across 40, 48 and 32.
TAB_WIDTH = 4


def _advance(text: str, tab: int = TAB_WIDTH) -> int:
    """Which column ``text`` ends in, counting a tab as a jump to the next stop."""
    col = 0
    for ch in text:
        col = (col // tab + 1) * tab if ch == "\t" else col + 1
    return col


def value_column(line: str, keyword: str, tab: int = TAB_WIDTH) -> int:
    """The column a ``keyword<gap>value`` line's value starts in."""
    return _advance(head_prefix(line, keyword), tab)


def pad_to_column(keyword: str, indent: str, column: int,
                  tab: int = TAB_WIDTH) -> str:
    """``indent + keyword`` plus the tabs that put a value in ``column``.

    The gap between keyword and value is data in these files, and it is a
    *column*, not a string. Copying the gap of the line above — which is what
    this used to do — only lands right when the two keywords are the same
    length: inserting ``can_build_siege_towers`` with ``culture``'s four tabs
    pushed its value five columns past everything else in the record.

    A keyword already at or past the column gets a single tab, which is what the
    real files do with the long ones (``horde_disband_percent_on_settlement_capture``
    cannot reach column 28 and does not try).
    """
    out = indent + keyword
    col = _advance(out, tab)
    if col >= column:
        return out + "\t"
    while col < column:
        out += "\t"
        col = (col // tab + 1) * tab
    return out


def sub_tokens(line: str, keyword: str, tokens: Sequence[str]) -> str:
    """Rewrite every token of a many-valued line, keeping the gaps between them.

    ``spy  spy.tga  spy_info.tga  spy.tga  350  1  1`` is seven columns lined up
    by eye. Only the tokens the caller changed differ; the whitespace is the
    file's own.
    """
    code = line.partition(";")[0]
    indent = indent_of(code)
    rest = code[len(indent) + len(keyword):]
    out = indent + keyword
    parts = re.findall(r"(\s+)(\S+)", rest)
    for i, (gap, old) in enumerate(parts):
        out += gap + (str(tokens[i]) if i < len(tokens) else old)
    for extra in tokens[len(parts):]:
        out += " " + str(extra)
    return keep_comment(line, out)


def value_text(value, listy: bool = False) -> str:
    """The text after the keyword, for whatever shape the request sent."""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v).strip() for v in value if str(v).strip())
    return str(value if value is not None else "").strip()


def truthy(value) -> bool:
    """Whether a flag key (``Hidden``, ``Unique``) should have its line at all."""
    return value not in (False, None, "", 0, "false", "False", [], ())


def same_value(a: str, b: str, listy: bool = False) -> bool:
    """Would writing ``a`` where ``b`` is change anything the game reads?"""
    return split_list(a) == split_list(b) if listy else a == b


def diff(before: str, after: str, limit: int = 20) -> List[str]:
    """The changed lines, as a confirmation dialog shows them.

    A real line diff rather than a set difference: a trait with five levels
    usually has the same ``Threshold 2`` somewhere else, and comparing sets would
    report the old line as removed and never mention what replaced it.
    """
    out = []
    for line in difflib.unified_diff(before.split("\n"), after.split("\n"),
                                     n=0, lineterm=""):
        if line[:3] in ("+++", "---") or line.startswith("@@"):
            continue
        if line[:1] in "+-" and line[1:].strip():
            out.append(("  " if line[0] == "+" else "- ") + line[1:].strip())
    return out[:limit]


# ---------------------------------------------------------------------------
# the splice


class Splice:
    """Line edits collected against the original numbering, applied once.

    Every anchor a caller gives is a line number in the text as parsed, so the
    edits can be worked out in reading order and still land correctly when some
    of them insert and some delete.
    """

    def __init__(self, lines: List[str]):
        self.lines = list(lines)
        self._set: Dict[int, str] = {}
        self._drop: set = set()
        self._after: Dict[int, List[str]] = defaultdict(list)

    def replace(self, i: int, text: str) -> None:
        self._set[i] = text

    def drop(self, i: int) -> None:
        self._drop.add(i)

    def after(self, i: int, texts: List[str]) -> None:
        self._after[i].extend(texts)

    def result(self) -> List[str]:
        out: List[str] = []
        for i, line in enumerate(self.lines):
            if i not in self._drop:
                out.append(self._set.get(i, line))
            out.extend(self._after.get(i, ()))
        return out


def edit_keys(sp: Splice, lines: List[str], present: Dict[str, int],
              values: Dict[str, str], edits: Dict, key_field: Dict[str, str],
              order: Sequence[str], required: Sequence[str], flags: Sequence[str],
              list_keys: Sequence[str], anchor: int, indent: str,
              noun: str = "record", align: bool = False) -> None:
    """Rewrite, delete or insert the ``keyword value`` lines of one block.

    An inserted line goes at its place in ``order`` — under the last of its
    predecessors that exists, or under the block's own first line when none do.
    That is the whole reason this is not an append: see the module docstring.

    ``present`` is keyword -> line, ``values`` keyword -> what it says now, and
    ``edits`` is the request's field names, mapped back by ``key_field``.

    ``align`` keeps the whitespace between keyword and value instead of writing
    one space — see :func:`head_prefix`. The EDCT and EDA indent their values by
    a single space; the campaign files line them up in tab columns.
    """
    write = sub_value if align else sub_head
    gap = " "
    #: the column this record puts its values in — the commonest one among the
    #: lines it already has, so an inserted line joins the column rather than
    #: copying one keyword's tab count (see :func:`pad_to_column`)
    column = 0
    if align and present:
        counts: Dict[int, int] = {}
        for key0, i in present.items():
            col = value_column(lines[i], key0)
            counts[col] = counts.get(col, 0) + 1
        column = max(counts, key=lambda c: (counts[c], -c))
    #: keyword -> the line it sits on, or the line it was just inserted under.
    #: Two lines inserted under the same anchor keep the order they were asked
    #: for, which is why an inserted key can serve as a later key's predecessor.
    at = dict(present)
    order = list(order)
    for key in order:
        fieldname = key_field.get(key, "")
        if fieldname not in edits:
            continue
        listy = key in list_keys
        value = "" if key in flags else value_text(edits[fieldname], listy)
        line = present.get(key, -1)
        if key in flags:
            if truthy(edits[fieldname]):
                if line >= 0:
                    continue                      # already there, nothing to write
            else:
                if line >= 0:
                    sp.drop(line)
                    at.pop(key, None)
                continue
        elif not value:
            if key in required:
                raise BlockError(f"a {noun} needs its `{key}` line", (line + 1) or 1)
            if line >= 0:
                sp.drop(line)
                at.pop(key, None)
            continue
        elif line >= 0:
            # A form sends every box, so most keys arrive unchanged; rewriting
            # them anyway would normalise spacing their author chose.
            if not same_value(value, values.get(key, ""), listy):
                sp.replace(line, write(lines[line], key, value))
            continue
        prior = [at[k] for k in order[:order.index(key)] if k in at]
        where = max(prior) if prior else anchor
        if column and value:
            row = pad_to_column(key, indent, column) + value
        else:
            row = indent + key + (gap + value if value else "")
        sp.after(where, [row])
        at[key] = where


def edit_effects(sp: Splice, lines: List[str], effects, wanted: List[Dict],
                 indent: str, last_line: int) -> None:
    """Rewrite the ``Effect Attribute Points`` lines; add or drop only what moved.

    Index-aligned with what is there, like every other list in these files: an
    untouched effect keeps its exact line, and a new one copies the indent of the
    effect above it.
    """
    old = list(effects)
    for i in range(min(len(old), len(wanted))):
        eff, w = old[i], wanted[i] or {}
        attribute = str(w.get("attribute", eff.attribute) or "").strip()
        amount = str(w.get("amount", eff.amount) or "").strip()
        if (attribute, amount) == (eff.attribute, eff.amount):
            continue
        if not attribute or not amount:
            raise BlockError("an Effect line is `Effect <attribute> <points>` — "
                             "both are needed", eff.line + 1)
        sp.replace(eff.line,
                   keep_comment(lines[eff.line],
                                f"{indent_of(lines[eff.line])}Effect "
                                f"{attribute} {amount}"))
    if len(wanted) > len(old):
        eff_indent = indent_of(lines[old[-1].line]) if old else indent
        rows = []
        for w in wanted[len(old):]:
            attribute = str((w or {}).get("attribute") or "").strip()
            amount = str((w or {}).get("amount") or "").strip()
            if attribute and amount:
                rows.append(f"{eff_indent}Effect {attribute} {amount}")
        sp.after(old[-1].line if old else last_line, rows)
    elif len(wanted) < len(old):
        for eff in old[len(wanted):]:
            sp.drop(eff.line)


def new_lines(edits: Dict, key_field: Dict[str, str], order: Sequence[str],
              flags: Sequence[str], list_keys: Sequence[str],
              indent: str) -> List[str]:
    """The ``keyword value`` lines of a brand-new block, in the engine's order."""
    out = []
    for key in order:
        if key in flags:
            if truthy(edits.get(key_field.get(key, ""))):
                out.append(indent + key)
            continue
        value = value_text(edits.get(key_field.get(key, ""), ""), key in list_keys)
        if value:
            out.append(f"{indent}{key} {value}")
    for eff in (edits.get("effects") or []):
        attribute = str((eff or {}).get("attribute") or "").strip()
        amount = str((eff or {}).get("amount") or "").strip()
        if attribute and amount:
            out.append(f"{indent}Effect {attribute} {amount}")
    return out
