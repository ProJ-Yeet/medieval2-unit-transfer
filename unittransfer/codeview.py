"""Code View — the server half of "the GUI and the raw file, side by side".

Every editor in the toolkit shows a mod file as labelled boxes. Code View adds
the other view of the same bytes: the text as the game reads it, with a map
saying which line each box came from. Hover a stat, its line lights up; type in
the text, the boxes follow.

The rule this module exists to enforce is that **the browser never parses a game
file**. The page owns pixels; ``unittransfer`` owns formats. So the widget asks
here for three things and nothing else:

  * :func:`document` — text + fields + spans for something already on disk
  * :func:`parse` — the user typed in the text pane: re-read it, or say why not
  * :func:`render` — the user typed in a box: re-serialise, through the very
    serialiser the save path uses, so the text pane can never promise a byte the
    save would not write
  * :func:`repair` — optional, for a format whose text carries bookkeeping a
    person cannot be expected to maintain by hand (the modeldb's length
    prefixes). Never automatic: the page offers it as a button.

A *kind* is one file shape (``edu``, ``edb``, ``bmdb``, ``strings``, ``traits``,
``ancillaries`` today; the minor files join later). Each kind supplies a parse
function and a render function and gets the whole widget for free — that is the
point of building it once.

``render``'s ``edits`` argument is kind-shaped, and deliberately so: it is
whatever that editor's save request already sends (``{overrides, removals}`` for
a unit's EDU block, the level-edit body for a building line, the path map for a
modeldb entry). The pane and the save then take the same road, which is the only
way the pane can promise what the save will write.

Spans are ``{label: [[first_line, last_line], ...]}``, 1-based and inclusive,
counted from the first line of the text being shown. A label may own more than
one span, and a repeated key is numbered ``key#2`` exactly as the field lists
already number it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import edu as edu_mod


class CodeViewError(Exception):
    """The raw text the user typed is not this kind of file (with a line, if known)."""

    def __init__(self, message: str, line: int = 0):
        super().__init__(message)
        self.message = message
        self.line = line


@dataclass
class Doc:
    """One document as both panes see it."""
    kind: str
    text: str
    fields: List[Tuple[str, str]] = field(default_factory=list)
    spans: Dict[str, List[List[int]]] = field(default_factory=dict)
    ident: str = ""                      # the record's own name (EDU: its `type`)
    note: str = ""                       # something true but not fatal
    #: Kind-shaped extra the GUI needs to redraw itself from re-read text. The
    #: EDU's field list is enough on its own; a building line is a tree, so its
    #: kind puts a whole `buildings.detail` payload here.
    detail: Optional[dict] = None

    def payload(self) -> dict:
        return {"kind": self.kind, "text": self.text,
                "fields": [list(f) for f in self.fields],
                "spans": self.spans,
                "part_spans": part_spans(self.text, self.spans),
                "id": self.ident,
                "lines": len(self.text.splitlines()),
                "note": self.note, "detail": self.detail}


#: Tab stop the code view lays its text out on. The pane sets `tab-size` to the
#: same number, which is what lets a column computed here land on the right pixel
#: in the browser.
TAB = 4


def _visual_col(line: str, index: int) -> int:
    """Column ``index`` of ``line`` lands in, with tabs expanded at :data:`TAB`."""
    col = 0
    for ch in line[:index]:
        col = (col // TAB + 1) * TAB if ch == "\t" else col + 1
    return col


def part_spans(text: str, spans: Dict[str, List[List[int]]]
               ) -> Dict[str, List[List[int]]]:
    """``label -> [[line, col, col_end], …]``, one entry per comma-separated value.

    A guided box edits ONE value of a line that holds eleven of them, so hovering
    it should light that value up and not the whole line. Every format here spells
    a multi-value line the same way — ``keyword`` then a comma-separated list — so
    this is derived from the text and the line spans rather than being a third
    thing each kind has to produce. Columns are visual (tabs expanded), because
    that is what the pane can position a box at.

    Single-value lines get one entry, which is still useful: it lights the value
    rather than the keyword and the indent in front of it.
    """
    lines = text.split("\n")
    out: Dict[str, List[List[int]]] = {}
    for label, ranges in (spans or {}).items():
        if not ranges or len(ranges) != 1:
            continue                      # multi-line fields have no value list
        a, b = ranges[0]
        if a != b or a < 1 or a > len(lines):
            continue
        raw = lines[a - 1]
        key = label.split("#")[0]
        body = raw.split(";", 1)[0]       # never point inside a trailing comment
        stripped = body.lstrip()
        indent = len(body) - len(stripped)
        if stripped.lower().startswith(key.lower()):
            start = indent + len(key)
        else:                             # not a `keyword value` line — first gap
            gap = len(stripped) - len(stripped.lstrip(" \t"))
            first = stripped.find(" ")
            tab = stripped.find("\t")
            cut = min(x for x in (first, tab) if x >= 0) if (first >= 0 or tab >= 0) else -1
            if cut < 0:
                continue
            start = indent + gap + cut
        while start < len(body) and body[start] in " \t":
            start += 1
        if start >= len(body):
            continue
        parts: List[List[int]] = []
        pos = start
        for piece in body[start:].split(","):
            lead = len(piece) - len(piece.lstrip())
            value = piece.strip()
            c0 = pos + lead
            c1 = c0 + len(value)
            parts.append([a, _visual_col(raw, c0), _visual_col(raw, c1)])
            pos += len(piece) + 1         # + the comma
        if parts:
            out[label] = parts
    return out


# ---------------------------------------------------------------------------
# the EDU kind

def _edu_parse(text: str, ctx: dict) -> Doc:
    """One unit block of ``export_descr_unit.txt``.

    A code view edits one record, so text holding two units is refused rather
    than half-applied: the save path replaces a single block, and the second
    unit would be swallowed into the first one's slot.
    """
    parsed = edu_mod.parse_text(text)
    if not parsed.units:
        raise CodeViewError(
            "a unit block needs a `type` line — this text has none", 1)
    if len(parsed.units) > 1:
        # the line the second block starts on, so the editor can point at it
        first = parsed.units[0].raw.count("\n")
        pre = parsed.preamble.count("\n")
        raise CodeViewError(
            f"this text holds {len(parsed.units)} unit blocks — a code view edits "
            "one unit at a time, so the extra `type` line(s) must go",
            pre + first + 1)
    unit = parsed.units[0]
    note = ""
    if parsed.preamble.strip():
        note = "the lines above the `type` line are kept with this unit"
    return Doc(kind="edu", text=text, fields=edu_mod.block_fields(unit.raw),
               spans=_shift(edu_mod.block_spans(unit.raw),
                            parsed.preamble.count("\n")),
               ident=unit.type, note=note)


def _edu_render(base: str, edits: dict, ctx: dict) -> str:
    return edu_mod.apply_field_edits(base, edits.get("overrides") or {},
                                     list(edits.get("removals") or []))


#: Column an EDU block's values line up in, at :data:`TAB`-wide tab stops. 24 is
#: what vanilla uses and what the longest common keyword (`crusading_upkeep_
#: modifier` aside) clears comfortably; a keyword too long for it takes one tab,
#: which is what the real long ones do.
EDU_VALUE_COL = 24


def _edu_tidy(text: str, ctx: dict) -> str:
    """Line every keyword's value up in one column, comments and all kept.

    A hand-written EDU block is a ragged mix of tabs and spaces, and reading a
    unit means reading down the value column. This only ever rewrites the gap
    BETWEEN a keyword and its value: nothing is reordered, nothing is dropped,
    and a comment or a blank line is passed through untouched. It is a button,
    never automatic — see the `owns` rule in web/js/codeview.js.
    """
    out = []
    for raw in text.split("\n"):
        body, sep, comment = raw.partition(";")
        stripped = body.lstrip()
        if not stripped:
            out.append(raw)
            continue
        cut = min((i for i, ch in enumerate(stripped) if ch in " \t"), default=-1)
        if cut < 0:
            out.append(raw)
            continue
        key = stripped[:cut]
        # `banner faction` / `banner holy` / `era 0` are two-word keywords
        rest = stripped[cut:].lstrip()
        if key in ("banner", "era") and rest:
            second = rest.split(None, 1)
            key = key + " " + second[0]
            rest = second[1].lstrip() if len(second) > 1 else ""
        if not rest:
            out.append(raw)
            continue
        pad = EDU_VALUE_COL - len(key)
        gap = "\t" * max(1, -(-pad // TAB)) if pad > 0 else "\t"
        out.append(key + gap + rest + sep + comment)
    return "\n".join(out)


# ---------------------------------------------------------------------------
# hiding the comment lines — DISPLAY ONLY
#
# A unit block in a real mod carries the faction distinguishers and whatever the
# last person to touch it wrote down, and none of it is a field. Reading around
# them is half the reason the guided view exists, so the pane hides them.
#
# What it must not do is lose them. `buildings.py`'s rule holds for every splice
# parser here: 7203 real input lines carry a comment and the write path has to
# put every one back byte for byte. So the hiding is a PAIR of functions, not a
# filter: the page is handed the text without the comment lines plus an opaque
# `hidden` list, sends both back, and the server rebuilds the real text before
# anything parses or saves. The page never learns what a comment looks like in
# this format, which is the rule the rest of the module already follows.

#: What opens a comment in each kind's file. A kind that is absent cannot hide
#: anything — the modeldb stores lengths rather than text a person comments, and
#: the strings archives have a convention this has not measured. `#` is on the
#: EDB because Phase 13 ruled it a modder's annotation there, and every parser in
#: buildings.py already skips it.
COMMENT_MARKS: Dict[str, Tuple[str, ...]] = {
    # `pools` is absent on purpose: its comment lines are the building headings
    # this module writes itself, so hiding them would leave a list of pool lines
    # with nothing saying which building each came from.
    "edu": (";",), "edb": (";", "#"), "traits": (";",), "ancillaries": (";",),
    "factions": (";",), "sounds": (";",), "rebels": (";",), "resources": (";",),
    "religions": (";",), "cultures": (";",), "names": (";",),
}


def comment_marks(kind: str) -> Tuple[str, ...]:
    return COMMENT_MARKS.get(kind, ())


def _is_comment(line: str, marks: Tuple[str, ...]) -> bool:
    """A line that is NOTHING but a comment.

    A trailing comment stays where it is: it belongs to the field in front of
    it, and hiding it would take a value off the screen with it.
    """
    s = line.strip()
    return bool(s) and bool(marks) and s.startswith(marks)


def line_map(kind: str, text: str) -> Dict[int, int]:
    """1-based full line -> its 1-based line in the hidden view, or 0 if hidden."""
    marks = comment_marks(kind)
    out: Dict[int, int] = {}
    seen = 0
    for i, raw in enumerate(text.split("\n"), 1):
        if _is_comment(raw, marks):
            out[i] = 0
        else:
            seen += 1
            out[i] = seen
    return out


def hide_comments(kind: str, text: str) -> Tuple[str, List[dict]]:
    """``(view, hidden)`` — the text without its comment-only lines, and how to
    put them back.

    Each hidden line remembers three things about where it was: how many view
    lines stood in front of it, the text of the line it sat above, and that
    line's keyword. They are tried in the opposite order to how much they can
    tell you: the exact line first, then the keyword — every format here is
    keyword-first, so typing a new VALUE does not move it — and the count last,
    for when the line it sat above is gone altogether.
    """
    marks = comment_marks(kind)
    if not marks:
        return text, []
    view: List[str] = []
    hidden: List[dict] = []
    for raw in text.split("\n"):
        if _is_comment(raw, marks):
            hidden.append({"at": len(view), "text": raw})
        else:
            view.append(raw)
    if not hidden:
        return text, []
    for h in hidden:
        at = h["at"]
        line = view[at] if at < len(view) else None
        h["before"] = line
        h["key"] = line.split()[0] if line and line.split() else None
    return "\n".join(view), hidden


def _first(line: str) -> Optional[str]:
    parts = line.split()
    return parts[0] if parts else None


def _anchor(lines: List[str], h: dict) -> int:
    """Which view line a hidden line goes back above."""
    at = max(0, min(int(h.get("at") or 0), len(lines)))
    if h.get("before") is None:
        return len(lines)             # it was at the end and it stays at the end
    for hits in ([i for i, line in enumerate(lines) if line == h["before"]],
                 [i for i, line in enumerate(lines)
                  if h.get("key") and _first(line) == h["key"]]):
        if hits:
            return min(hits, key=lambda i: (abs(i - at), i))
    return at


def show_comments(kind: str, view_text: str, hidden: Optional[List[dict]]) -> str:
    """Put the hidden comment lines back.

    The exact inverse of :func:`hide_comments` on text nobody has touched, and
    never a loss on text somebody has: a comment whose anchor line has gone
    falls back to the position it was counted from.
    """
    if not hidden:
        return view_text
    lines = view_text.split("\n")
    slots: Dict[int, List[str]] = {}
    for h in hidden:
        slots.setdefault(_anchor(lines, h), []).append(str(h.get("text") or ""))
    out: List[str] = []
    for i, line in enumerate(lines):
        out.extend(slots.get(i, ()))
        out.append(line)
    out.extend(slots.get(len(lines), ()))
    return "\n".join(out)


def _hidden_spans(kind: str, text: str, spans: Dict[str, List[List[int]]]
                  ) -> Dict[str, List[List[int]]]:
    """Span line numbers moved onto the hidden view's numbering."""
    m = line_map(kind, text)
    out: Dict[str, List[List[int]]] = {}
    for label, ranges in (spans or {}).items():
        moved = []
        for a, b in ranges:
            live = [n for n in (m.get(i, 0) for i in range(a, b + 1)) if n]
            if live:
                moved.append([min(live), max(live)])
        if moved:
            out[label] = moved
    return out


def view_payload(doc: Doc, hide: bool = False) -> dict:
    """:meth:`Doc.payload` as the pane should draw it.

    ``full`` is always the record's real text — the bytes a save writes. With
    hiding on, ``text``, ``spans``, ``part_spans`` and ``lines`` all describe the
    view WITHOUT its comment-only lines, and ``hidden`` says how to rebuild the
    rest. The pane holds both: it shows ``text`` and it saves ``full``.
    """
    out = doc.payload()
    marks = comment_marks(doc.kind)
    out["full"] = doc.text
    out["hidden"] = []
    out["can_hide"] = bool(marks)
    # how many there are, whether or not they are being hidden — the pane's
    # button says what it would hide before anyone has pressed it
    out["comments"] = sum(1 for line in doc.text.split("\n")
                          if _is_comment(line, marks))
    if not hide or not marks:
        return out
    view, hidden = hide_comments(doc.kind, doc.text)
    if not hidden:
        return out
    out["text"] = view
    out["hidden"] = hidden
    out["spans"] = _hidden_spans(doc.kind, doc.text, doc.spans)
    out["part_spans"] = part_spans(view, out["spans"])
    out["lines"] = len(view.splitlines())
    return out


def _shift(spans: Dict[str, List[List[int]]], by: int) -> Dict[str, List[List[int]]]:
    """Move every span down ``by`` lines (the block does not start at line 1)."""
    if not by:
        return spans
    return {k: [[a + by, b + by] for a, b in v] for k, v in spans.items()}


# ---------------------------------------------------------------------------
# the EDB kind — one `building … { … }` line of export_descr_buildings.txt

def _edb_parse(text: str, ctx: dict) -> Doc:
    from . import buildings as bld
    sub = bld.parse_text(text)
    if not sub.buildings:
        raise CodeViewError(
            "a building line starts with `building <name> {` — this text has none", 1)
    if len(sub.buildings) > 1:
        raise CodeViewError(
            f"this text holds {len(sub.buildings)} building lines — a code view "
            "edits one line at a time",
            sub.buildings[1].start + 1)
    bl = sub.buildings[0]
    if bl.end < len(sub.lines) and "".join(sub.lines[bl.end:]).strip():
        raise CodeViewError("there is text after the line's closing brace", bl.end + 1)
    note = "; ".join(sub.warnings) if sub.warnings else ""
    mod = ctx.get("mod")
    # The boxes are a tree, not a field list, so they are redrawn from a full
    # detail payload rather than from `fields` — built off the block just read,
    # with art and localisation still coming from the mod (they are not in it).
    detail = (bld.detail(mod, bl.name, ctx.get("culture") or "", bl=bl)
              if mod is not None else None)
    return Doc(kind="edb", text=text, fields=bld.block_fields(sub, bl),
               spans=_shift(bld.block_spans(sub, bl), bl.start),
               ident=bl.name, note=note, detail=detail)


def _edb_render(base: str, edits: dict, ctx: dict) -> str:
    from . import buildings as bld
    return bld.render_block(base, edits or {})


# ---------------------------------------------------------------------------
# the BMDB kind — one entry of unit_models/battle_models.modeldb
#
# The only kind whose text carries bookkeeping the person editing it cannot
# reasonably maintain: every string is written `<length> <that many chars>`, so
# retyping a texture path and leaving the number alone desyncs the reader. Hence
# this kind is also the only one with a `repair`.

def _bmdb_parse(text: str, ctx: dict) -> Doc:
    from . import modeldb as mdb
    pad = bool(ctx.get("pad"))
    try:
        entry = mdb.parse_entry_text(text, pad=pad)
    except (ValueError, IndexError) as e:
        base = ctx.get("base") or ""
        bad = mdb.prefix_problems(base, text, pad=pad) if base else []
        if bad:
            first = bad[0]
            raise CodeViewError(
                f"line {first['line']}'s length says {first['said']} but the text "
                f"beside it is {first['should']} characters"
                + (f" (and {len(bad) - 1} more like it)" if len(bad) > 1 else "")
                + " — every modeldb string is written `<length> <text>`",
                first["line"]) from None
        raise CodeViewError(f"this text isn't a modeldb entry: {e}", 0) from None
    # the whole card, not a slot list: hand-edited text can add or drop a faction
    # record, and then a card patched slot-by-slot would be quietly out of step
    from .edit import model_payload
    return Doc(kind="bmdb", text=text,
               fields=[(s["label"], s["value"]) for s in mdb.path_slots_raw(text, pad=pad)],
               spans=mdb.entry_spans(text, pad=pad), ident=entry.name,
               detail=model_payload(entry))


def _bmdb_render(base: str, edits: dict, ctx: dict) -> str:
    from . import modeldb as mdb
    pad = bool(ctx.get("pad"))
    text = base
    name = (edits.get("new_name") or "").strip()
    if name:
        text = mdb.rename_entry_raw(text, name.lower())
    paths = {int(k): str(v) for k, v in (edits.get("paths") or {}).items()}
    if paths:
        text = mdb.rewrite_paths_indexed(text, paths, pad=pad)
    return text


def _bmdb_repair(text: str, ctx: dict) -> str:
    from . import modeldb as mdb
    return mdb.repair_prefixes(ctx.get("base") or "", text, pad=bool(ctx.get("pad")))


# ---------------------------------------------------------------------------
# the strings kind — one entry of a compiled *.txt.strings.bin
#
# The archive is binary, but its entries are exactly the `{tag}text` lines of the
# .txt beside it, so that is what the pane shows: the format modders already
# write, not a decoded surrogate. One entry is one line — a real line break in a
# value is written `\n`, which is what the game's own compiler reads.

def _strings_parse(text: str, ctx: dict) -> Doc:
    from . import stringsbin as sbin
    try:
        tag, value = sbin.parse_record(text)
    except sbin.StringsBinError as e:
        raise CodeViewError(str(e), 1) from None
    locked = ctx.get("tag")
    if locked and tag != locked:
        # A tag is the key the game looks the string up by; renaming it here
        # would silently orphan whatever names it. Same ruling as a building
        # line and a modeldb entry, and for the same reason.
        raise CodeViewError(
            f"this entry's tag is `{locked}` — renaming a tag in the text pane "
            "would orphan everything that looks the string up by it", 1)
    return Doc(kind="strings", text=text,
               fields=[("tag", tag), ("text", value)],
               spans={"tag": [[1, 1]], "text": [[1, 1]]},
               ident=tag,
               detail={"tag": tag, "value": value,
                       "pos": ctx.get("pos", -1), "file": ctx.get("file", "")})


def _strings_render(base: str, edits: dict, ctx: dict) -> str:
    from . import stringsbin as sbin
    tag = str(edits.get("tag") or ctx.get("tag") or "")
    if not tag:
        tag = sbin.parse_record(base)[0] if base.strip() else ""
    return sbin.record_text(tag, str(edits.get("value") or ""))


# ---------------------------------------------------------------------------
# the traits kind — one `Trait … Level …` block of export_descr_character_traits
#
# The block below the header is a ladder, not a field list, so the boxes are
# redrawn from a whole trait payload rather than from `fields` — the same ruling
# the buildings kind needed for its capability tree.

def _traits_parse(text: str, ctx: dict) -> Doc:
    from . import traits as traits_mod
    try:
        trait = traits_mod.parse_block(text)
    except traits_mod.TraitError as e:
        raise CodeViewError(e.message, e.line) from None
    locked = ctx.get("trait")
    if locked and trait.name != locked:
        # The trait name is the key its own triggers' `Affects` lines, other
        # traits' `AntiTraits` lists, the EDA's conditions and descr_strat all
        # point at. Same ruling as a building line, and for the same reason.
        raise CodeViewError(
            f"this trait is `{locked}` — renaming it in the text pane would "
            "orphan every trigger, antitrait list and starting character that "
            "names it", 1)
    known = set(ctx.get("known") or ())
    findings = traits_mod.check(trait, known or None)
    return Doc(kind="traits", text=text, fields=traits_mod.block_fields(text),
               spans=traits_mod.block_spans(text), ident=trait.name,
               note="; ".join(f["message"] for f in findings[:2]),
               detail=trait.as_dict())


def _traits_render(base: str, edits: dict, ctx: dict) -> str:
    from . import traits as traits_mod
    try:
        return traits_mod.render_block(base, edits or {})
    except traits_mod.TraitError as e:
        raise CodeViewError(e.message, e.line) from None


# ---------------------------------------------------------------------------
# the ancillaries kind — one `Ancillary … Effect …` block of the EDA
#
# EDCT's smaller sibling: a flat record rather than a ladder, so its boxes are a
# field list and a `detail` payload both, exactly as the traits kind is.

def _anc_parse(text: str, ctx: dict) -> Doc:
    from . import ancillaries as anc_mod
    try:
        anc = anc_mod.parse_block(text)
    except anc_mod.AncillaryError as e:
        raise CodeViewError(e.message, e.line) from None
    locked = ctx.get("ancillary")
    if locked and anc.name != locked:
        # An ancillary's name is its `AcquireAncillary` key, other ancillaries'
        # `ExcludedAncillaries` entries, a condition operand, a descr_strat entry
        # AND its own text key. Same ruling as a trait, for four more reasons.
        raise CodeViewError(
            f"this ancillary is `{locked}` — renaming it in the text pane would "
            "orphan every trigger, exclusion list, starting character and text "
            "entry that names it", 1)
    known = set(ctx.get("known") or ())
    findings = anc_mod.check(anc, known or None)
    return Doc(kind="ancillaries", text=text, fields=anc_mod.block_fields(text),
               spans=anc_mod.block_spans(text), ident=anc.name,
               note="; ".join(f["message"] for f in findings[:2]),
               detail=anc.as_dict())


def _anc_render(base: str, edits: dict, ctx: dict) -> str:
    from . import ancillaries as anc_mod
    try:
        return anc_mod.render_block(base, edits or {})
    except anc_mod.AncillaryError as e:
        raise CodeViewError(e.message, e.line) from None


# ---------------------------------------------------------------------------
# the minor-file kinds — one record of each of the five small campaign files
#
# All five names are keys another file points at: `descr_regions.txt` names a
# region's rebel type and lists its religions by name, `descr_sm_factions.txt`
# names each faction's culture and religion, and a faction's names are looked up
# by the faction's own slot. So all five refuse a rename in the text pane, the
# same ruling a building line and a trait already make.

def _minor_locked(kind: str, ident: str, found: str, points_at: str) -> None:
    if ident and found != ident:
        raise CodeViewError(
            f"this {kind} is `{ident}` — renaming it in the text pane would orphan "
            f"{points_at}", 1)


def _record_kind(tab: str, shape_name: str, points_at: str):
    """A parse/render pair for one of the two flat-record files."""
    def parse_one(text: str, ctx: dict) -> Doc:
        from . import minorfiles as mf
        shape = getattr(mf, shape_name)
        try:
            rec = mf.parse_record_block(shape, text)
        except mf.MinorError as e:
            raise CodeViewError(e.message, e.line) from None
        _minor_locked(shape.noun, ctx.get("ident") or "", rec.name, points_at)
        findings = [f for f in mf.check_records(shape, mf.parse_records(shape, text))]
        return Doc(kind=tab, text=text, fields=mf.record_fields(shape, text),
                   spans=mf.record_spans(shape, text), ident=rec.name,
                   note="; ".join(f["message"] for f in findings[:2]),
                   detail=rec.as_dict(shape))

    def render_one(base: str, edits: dict, ctx: dict) -> str:
        from . import minorfiles as mf
        try:
            return mf.render_record(getattr(mf, shape_name), base, edits or {})
        except mf.MinorError as e:
            raise CodeViewError(e.message, e.line) from None

    return {"parse": parse_one, "render": render_one}


def _religions_parse(text: str, ctx: dict) -> Doc:
    from . import minorfiles as mf
    try:
        rel = mf.parse_religion_block(text)
    except mf.MinorError as e:
        raise CodeViewError(e.message, e.line) from None
    _minor_locked("religion", ctx.get("ident") or "", rel.name,
                  "every region's religion percentages, every faction's `religion` "
                  "line and the lookup file")
    return Doc(kind="religions", text=text, fields=mf.religion_fields(text),
               spans=mf.religion_spans(text), ident=rel.name,
               detail=rel.as_dict())


def _religions_render(base: str, edits: dict, ctx: dict) -> str:
    from . import minorfiles as mf
    try:
        return mf.render_religion(base, edits or {})
    except mf.MinorError as e:
        raise CodeViewError(e.message, e.line) from None


def _cultures_parse(text: str, ctx: dict) -> Doc:
    from . import minorfiles as mf
    try:
        cul = mf.parse_culture_block(text)
    except mf.MinorError as e:
        raise CodeViewError(e.message, e.line) from None
    _minor_locked("culture", ctx.get("ident") or "", cul.name,
                  "every faction's `culture` line and every building that requires "
                  "one")
    return Doc(kind="cultures", text=text, fields=mf.culture_fields(text),
               spans=mf.culture_spans(text), ident=cul.name,
               note="; ".join(w for w in cul.warnings[:2]),
               detail=cul.as_dict())


def _cultures_render(base: str, edits: dict, ctx: dict) -> str:
    from . import minorfiles as mf
    try:
        return mf.render_culture(base, edits or {})
    except mf.MinorError as e:
        raise CodeViewError(e.message, e.line) from None


def _names_parse(text: str, ctx: dict) -> Doc:
    from . import minorfiles as mf
    try:
        fac = mf.parse_names_block(text)
    except mf.MinorError as e:
        raise CodeViewError(e.message, e.line) from None
    _minor_locked("faction", ctx.get("ident") or "", fac.name,
                  "the names this faction's characters and settlements draw from")
    return Doc(kind="names", text=text, fields=mf.names_fields(text),
               spans=mf.names_spans(text), ident=fac.name,
               detail=fac.as_dict())


def _names_render(base: str, edits: dict, ctx: dict) -> str:
    from . import minorfiles as mf
    try:
        return mf.render_names(base, edits or {})
    except mf.MinorError as e:
        raise CodeViewError(e.message, e.line) from None


# ---------------------------------------------------------------------------
# the factions kind — one record of descr_sm_factions.txt
#
# The fourth flat-record file, and the one whose name is load-bearing in the most
# places: descr_strat, every unit's ownership line, every `requires factions { … }`
# clause, descr_names and its own expanded.txt entry all point at the slot. The
# head line may carry a modifier after a comma (`faction egypt, spawned_on_event`),
# so what is locked is the SLOT, not the whole line.

def _factions_parse(text: str, ctx: dict) -> Doc:
    from . import factions as fac
    try:
        rec = fac.parse_block(text)
    except fac.FactionError as e:
        raise CodeViewError(e.message, e.line) from None
    locked = ctx.get("faction") or ""
    if locked and fac.slot_of(rec.name) != fac.slot_of(locked):
        raise CodeViewError(
            f"this faction is `{fac.slot_of(locked)}` — renaming a slot in the text "
            "pane would orphan descr_strat, every unit's ownership line, every "
            "`requires factions { … }` clause and its own text entry", 1)
    findings = fac.check_file(fac.parse_text(text if text.endswith("\n") else text + "\n"))
    return Doc(kind="factions", text=text, fields=fac.block_fields(text),
               spans=fac.block_spans(text), ident=rec.name,
               note="; ".join(f["message"] for f in findings[:2]),
               detail=dict(rec.as_dict(fac.SHAPE),
                           horde_units=[r.value for r in rec.repeats]))


def _factions_render(base: str, edits: dict, ctx: dict) -> str:
    from . import factions as fac
    try:
        return fac.render_block(base, edits or {})
    except fac.FactionError as e:
        raise CodeViewError(e.message, e.line) from None


#: kind -> {parse, render, repair?}. One entry per file shape; adding a kind is
#: what makes a new editor code-viewable, and nothing else has to change.
KINDS: Dict[str, dict] = {
    "edu": {"parse": _edu_parse, "render": _edu_render, "tidy": _edu_tidy},
    "edb": {"parse": _edb_parse, "render": _edb_render},
    "bmdb": {"parse": _bmdb_parse, "render": _bmdb_render, "repair": _bmdb_repair},
    "strings": {"parse": _strings_parse, "render": _strings_render},
    "traits": {"parse": _traits_parse, "render": _traits_render},
    "ancillaries": {"parse": _anc_parse, "render": _anc_render},
    "rebels": _record_kind("rebels", "REBELS",
                           "every region that spawns it in descr_regions.txt"),
    "resources": _record_kind("resources", "RESOURCES",
                              "every resource placed on the campaign map"),
    "religions": {"parse": _religions_parse, "render": _religions_render},
    "cultures": {"parse": _cultures_parse, "render": _cultures_render},
    "names": {"parse": _names_parse, "render": _names_render},
    "factions": {"parse": _factions_parse, "render": _factions_render},
}


def _kind(kind: str) -> dict:
    try:
        return KINDS[kind]
    except KeyError:
        raise CodeViewError(f"no code view for '{kind}'") from None


def parse(kind: str, text: str, ctx: Optional[dict] = None) -> Doc:
    """Re-read hand-edited text. Raises :class:`CodeViewError` if it isn't valid."""
    return _kind(kind)["parse"](text, ctx or {})


def render(kind: str, base: str, edits: Optional[dict] = None,
           ctx: Optional[dict] = None) -> Doc:
    """Apply GUI edits to ``base`` and re-read the result.

    Goes through the same serialiser the save path uses, so what the text pane
    shows is what a save would write — including the whitespace and comments the
    serialiser preserves. ``edits`` is kind-shaped: see the module docstring.
    """
    ctx = ctx or {}
    text = _kind(kind)["render"](base, edits or {}, ctx)
    return parse(kind, text, ctx)


def can_repair(kind: str) -> bool:
    return "repair" in KINDS.get(kind, {})


def can_tidy(kind: str) -> bool:
    return "tidy" in KINDS.get(kind, {})


def tidy(kind: str, text: str, ctx: Optional[dict] = None) -> Doc:
    """Re-column the record's layout, then re-read it. Asked for, never automatic."""
    ctx = ctx or {}
    fn = _kind(kind).get("tidy")
    if fn is None:
        raise CodeViewError(f"'{kind}' has no layout to tidy")
    return parse(kind, fn(text, ctx), ctx)


def repair(kind: str, text: str, ctx: Optional[dict] = None) -> Doc:
    """Put right the derived bookkeeping in hand-edited text, then re-read it.

    Only kinds that HAVE derived bookkeeping offer this, and only ever because
    the user asked: the corrected text goes straight back on screen.
    """
    ctx = ctx or {}
    fn = _kind(kind).get("repair")
    if fn is None:
        raise CodeViewError(f"'{kind}' has nothing to repair")
    return parse(kind, fn(text, ctx), ctx)


def unit_document(mod, unit_type: str) -> Doc:
    """The code view of one unit as it currently sits in the mod's files."""
    unit = mod.edu.by_type().get(unit_type)
    if unit is None:
        raise KeyError(f"unit {unit_type!r} not found in {mod.name}")
    return parse("edu", unit.raw)


def building_document(mod, name: str, culture: str = "") -> Doc:
    """The code view of one building line as it currently sits in the mod."""
    from . import buildings as bld
    bl = mod.edb.get(name)
    if bl is None:
        raise KeyError(f"no building line {name!r} in {mod.name}")
    return parse("edb", bld.block_text(mod.edb, bl),
                 {"mod": mod, "culture": culture})


def entry_document(mod, name: str) -> Doc:
    """The code view of one battle-model entry as it currently sits in the mod."""
    entry = mod.modeldb.by_name().get((name or "").lower())
    if entry is None:
        raise KeyError(f"no model entry {name!r} in {mod.name}")
    doc = parse("bmdb", entry.raw, {"pad": entry.first_entry_pad, "base": entry.raw})
    doc.note = ("every string here is written `<length> <text>` — edit a path and "
                "the length beside it needs to follow, which the ⟲ button does")
    return doc


def strings_document(mod, ident: str) -> Doc:
    """The code view of one ``.strings.bin`` entry, addressed ``<rel>|<tag>``.

    An untagged archive has no names to address a row by, so its rows are
    ``<rel>|#<position>`` instead — the same handle the editor lists them under.
    """
    from . import strings as strings_mod
    rel, tag, pos, value = strings_mod.locate(mod, ident)
    return parse("strings", strings_mod.record_line(tag, value, pos),
                 {"tag": tag, "pos": pos, "file": rel})


def trait_document(mod, name: str) -> Doc:
    """The code view of one trait as it currently sits in the mod's EDCT."""
    from . import traits as traits_mod
    tf = traits_mod.parse_file(mod.edct_path)
    trait = tf.get(name)
    if trait is None:
        raise KeyError(f"no trait {name!r} in {mod.name}")
    return parse("traits", tf.block_text(trait),
                 {"trait": name, "known": set(tf.by_name())})


def ancillary_document(mod, name: str) -> Doc:
    """The code view of one ancillary as it currently sits in the mod's EDA."""
    from . import ancillaries as anc_mod
    af = anc_mod.parse_file(mod.eda_path)
    anc = af.get(name)
    if anc is None:
        raise KeyError(f"no ancillary {name!r} in {mod.name}")
    return parse("ancillaries", af.block_text(anc),
                 {"ancillary": name, "known": set(af.by_name())})


def sounds_document(mod, unit_name: str) -> Doc:
    """One unit's block of ``export_descr_sounds_units_voice.txt``.

    READ-ONLY, and deliberately so. A voice entry is not a standalone record: it
    only means anything inside the ``accent`` / ``class`` / ``vocal`` headers
    above it, and the Sounds module's whole job is moving an entry BETWEEN those
    headers. Text pasted here would have to be re-attached to a block the text
    does not contain. So this shows what the file says — which is what the
    module was missing — and the staged edits stay the way to change it.
    """
    from pathlib import Path
    from . import sounds as snd
    path = Path(mod.data) / snd.EDS_REL
    if not path.is_file():
        raise KeyError(f"{getattr(mod, 'name', '?')} has no voice bank")
    bank = snd.parse_file(path)
    entry = bank.get(unit_name)
    if entry is None:
        raise KeyError(f"no voice entry for {unit_name!r}")
    lines = bank.lines[entry.start:entry.end]
    text = "".join(lines).rstrip("\r\n")
    spans: Dict[str, List[List[int]]] = {"unit": [[1, 1]]}
    for i, raw in enumerate(lines, 1):
        head = raw.strip().split(None, 1)
        if head and head[0].lower() in ("event", "folder", "vocal"):
            spans.setdefault(head[0].lower(), []).append([i, i])
    return Doc(kind="sounds", text=text, ident=unit_name, spans=spans,
               fields=[("accent", entry.accent), ("class", entry.voice_class),
                       ("vocal", entry.vocal), ("unit", entry.name)],
               note=f"in accent {entry.accent} / class {entry.voice_class} "
                    f"— read-only here; use the rows above to move or copy it")


def pools_document(mod, unit: str) -> Doc:
    """Every ``recruit_pool`` line in the mod that trains one unit.

    READ-ONLY, and for the same reason :func:`sounds_document` is. Every other
    kind here is ONE record: a block with a beginning and an end that a
    serialiser can write back. This is the opposite shape — the unit view
    gathers lines from a dozen building blocks scattered through
    ``export_descr_buildings.txt``, and text pasted here would have to be taken
    apart and posted back to blocks the text does not contain.

    What it is for is the question the unit view cannot otherwise answer: *what
    do these rows actually say in the file?* The numbers are in boxes and the
    clause is summarised, and neither shows the line. So each pool is printed
    under its building, with its real line number, exactly as the file has it.
    """
    from pathlib import Path
    from . import buildings as b
    from . import keyblock as kb

    rows = b.unit_instances(mod, unit)["instances"]
    if not rows:
        raise KeyError(f"no building trains {unit!r}")
    src = kb.read_text(Path(mod.data) / b.EDB_REL, b.ENCODING).split("\n")

    out: List[str] = []
    spans: Dict[str, List[List[int]]] = {}
    fields: List[Tuple[str, str]] = []
    line_of = None
    for r in rows:
        if r["line"] != line_of:
            line_of = r["line"]
            if out:
                out.append("")
            out.append(f"; {line_of}"
                       + (f"   ({r['settlement']})" if r.get("settlement") else ""))
        i = r["cap_line"]
        #: the file's own bytes for this pool, not a re-rendering of it
        text = src[i].rstrip("\r\n") if 0 <= i < len(src) else ""
        out.append(f"{text}    ; line {i + 1} · {r['level']}")
        spans[f"pool:{i}"] = [[len(out), len(out)]]
        fields.append((f"pool:{i}", text.strip()))

    return Doc(kind="pools", text="\n".join(out), ident=unit,
               spans=spans, fields=fields,
               note=f"{len(rows)} recruit pool(s) across "
                    f"{len({r['line'] for r in rows})} building line(s) — read-only "
                    "here; the boxes beside it are how they change")


def faction_document(mod, name: str) -> Doc:
    """The code view of one faction as it currently sits in the mod's roster."""
    from . import factions as fac
    rf = fac.parse_file(fac.path_for(mod))
    rec = rf.get(name) or next(
        (r for r in rf.records if fac.slot_of(r.name) == fac.slot_of(name)), None)
    if rec is None:
        raise KeyError(f"no faction {name!r} in {fac.REL}")
    return parse("factions", rf.block_text(rec), {"faction": rec.name})


def minor_document(mod, tab_id: str, name: str) -> Doc:
    """The code view of one record of a minor file, as it sits in the mod.

    One function for all five, because the only thing that differs between them
    is which parser reads the file — the reason they share a module at all.
    """
    from . import keyblock as kb
    from . import minorfiles as mf
    meta = mf.tab(tab_id)
    path = mf.path_for(mod, tab_id)
    if not path.is_file():
        raise KeyError(f"{getattr(mod, 'name', '?')} has no {meta.rel}")
    text = kb.read_text(path, mf.ENCODING)
    if tab_id in ("rebels", "resources"):
        shape = mf.REBELS if tab_id == "rebels" else mf.RESOURCES
        parsed = mf.parse_records(shape, text)
    elif tab_id == "religions":
        parsed = mf.parse_religions(text)
    elif tab_id == "cultures":
        parsed = mf.parse_cultures(text)
    else:
        parsed = mf.parse_names(text)
    rec = parsed.get(name)
    if rec is None:
        raise KeyError(f"no {meta.noun} {name!r} in {meta.rel}")
    return parse(meta.id, parsed.block_text(rec), {"ident": name})


def context(kind: str, mod, ident: str, culture: str = "") -> dict:
    """The per-record context a kind's parse/render/repair needs.

    Kept in one place so the server does not have to know what each kind wants,
    and so a new kind can need something new without touching the endpoints.
    """
    if kind == "bmdb":
        entry = mod.modeldb.by_name().get((ident or "").lower())
        return {"pad": bool(entry and entry.first_entry_pad),
                "base": entry.raw if entry else ""}
    if kind == "edb":
        return {"mod": mod, "culture": culture}
    if kind == "strings":
        from . import strings as strings_mod
        rel, tag, pos, _ = strings_mod.locate(mod, ident)
        return {"tag": tag, "pos": pos, "file": rel}
    if kind == "traits":
        from . import traits as traits_mod
        return {"trait": ident,
                "known": set(traits_mod.parse_file(mod.edct_path).by_name())}
    if kind == "ancillaries":
        from . import ancillaries as anc_mod
        return {"ancillary": ident,
                "known": set(anc_mod.parse_file(mod.eda_path).by_name())}
    if kind in ("rebels", "resources", "religions", "cultures", "names"):
        # all five lock their record's name for the same reason, so all five want
        # the same one thing: what that name is
        return {"ident": ident}
    if kind == "factions":
        return {"faction": ident}
    return {}
