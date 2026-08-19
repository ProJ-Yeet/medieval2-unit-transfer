"""The small campaign files: rebel factions, religions, resources, cultures, names.

Five files nobody would build a module for on their own, and one module because
they are all read the same afternoon: a mod's rebels, its religions, what its
provinces trade, what its settlements look like and what its people are called.

They are three shapes, not five, which is why they are here together:

**Flat records** — ``descr_rebel_factions.txt`` and ``descr_sm_resources.txt``.
A head line names the record and ``keyword value`` lines follow, exactly the
shape :mod:`unittransfer.keyblock` was written for by the traits editor::

    rebel_type          Evil_Rebels        type            timber
      category          peasant_revolt       trade_value   5
      chance            0                    item          data/…/resource_timber.CAS
      description       Evil_Rebels          icon          data/ui/…/resource_timber.tga
      unit              Cave Trolls2         has_mine
      unit              Mordor Orcs Invasion

**Brace blocks** — ``descr_religions.txt`` and ``descr_cultures.txt``. A name
line, then a ``{ … }`` body; cultures nest one level further for the settlement
ladder and then carry a *tail* of flat lines after the closing brace.

**Indented sections** — ``descr_names.txt``. ``faction: x``, then ``characters``
and ``women`` sections holding one bare name per line, 25 903 of them in Third
Age 6.

Everything is a line splice against the file as read, as in every editor since
Phase 8: these files are hand-aligned with tab stops and comment banners, and
``parse_text(t).text() == t`` for all 15 real files is the gate.

What measurement corrected in the reference tool's own parsers (all three break
files that load today — see ``merge/audit-minorfiles.md``):

* **a religion's key is ``pip_path`` inside a brace block.** Their parser looks
  for ``icon`` / ``pip`` / ``anti_pip``, finds none of them in any real file, and
  its serialiser writes a brace-less file the engine cannot read at all.
* **a resource's model line is ``item``, not ``model``.** Same failure: every
  real resource has ``item`` and none has ``model``.
* **a rebel ``unit`` line is a unit type and nothing else.** Their serialiser
  appends ``, 1, 1`` to each one; not one of the 215 real ``unit`` lines in the
  three installed mods has a comma, and the names have spaces in them
  (``unit Mordor Orcs Invasion``), so the rest of the line IS the name.

And two things the files themselves say:

* **a religion is written down three times** — the ``religions { … }`` list, its
  own ``religion x { … }`` block, and ``descr_religions_lookup.txt`` — plus a
  name in ``text/religions.txt`` (geeko's *How to add a religion*). Third Age 3
  disagrees with itself on all three counts: ``heretic`` has two blocks, the list
  is missing one name, and the lookup carries three religions that no longer
  exist. :func:`check_religions` is mostly there to say so.
* **the engine's resource list is closed.** All three installed mods ship the
  same 28 resource names in three different orders, and none has ever added one.

And one thing the checks here deliberately do **not** do: complain about a
``.tga`` the mod does not ship. Every pip and every settlement card in these
files can legitimately live in the game's own ``.pack`` archives, which the
toolkit cannot read, so "not on disk here" is not "missing". Measured: checking
them anyway produced 78 findings across the three mods and 77 of them were Third
Age 3's ``southern_european`` pointing at stock cards it does not need to ship.
Phase 10b shows the picture when it can find one; it does not call the other case
a fault.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from . import flatrecord as fr
from . import keyblock as kb

#: these are plain 8-bit text like every other campaign file, and Latin-1 is the
#: codec that promises the bytes come back as they went in
ENCODING = fr.ENCODING

#: how they are split into lines — the EDCT's splitter, so a line number means
#: the same thing in every editor
split_lines = fr.split_lines

#: The flat-record half of this module lives in :mod:`unittransfer.flatrecord`
#: now — ``descr_sm_factions.txt`` needed exactly it and nothing else, and a
#: fourth caller is where "the shape the minor files share" stops being a fact
#: about the minor files. These names are re-exported because they are this
#: module's published API and its tests, its Code View kinds and the server all
#: use them from here.
RecordError = fr.RecordError
#: the name this module has raised since Phase 10a, kept as an alias of the one
#: class so ``except MinorError`` still catches everything it ever caught
MinorError = fr.RecordError
LineFile = fr.LineFile
Shape = fr.Shape
Repeat = fr.Repeat
Record = fr.Record
RecordFile = fr.RecordFile
parse_records = fr.parse_records
parse_record_file = fr.parse_record_file
parse_record_block = fr.parse_record_block
render_record = fr.render_record
edit_repeats = fr.edit_repeats
new_record = fr.new_record
replace_record = fr.replace_record
record_spans = fr.record_spans
record_fields = fr.record_fields
_head = fr.head_of



def _closing(lines: Sequence[str], start: int) -> int:
    """The line of the ``}`` matching the first ``{`` at or after ``start``.

    ``-1`` when the file runs out first, which is a warning rather than a raise:
    these files are hand-written and a truncated block must still round-trip.
    """
    depth = 0
    opened = False
    for i in range(start, len(lines)):
        code = kb.code_of(lines[i])
        if not code:
            continue
        for ch in code:
            if ch == "{":
                depth += 1
                opened = True
            elif ch == "}":
                depth -= 1
                if opened and depth == 0:
                    return i
    return -1


def split_pair(value: str) -> Tuple[str, str]:
    """``"path/x.CAS,   plan_name"`` -> ``("path/x.CAS", "plan_name")``.

    Half the lines in ``descr_cultures.txt`` are a file and the settlement plan
    that goes with it, comma-separated and lined up with tabs. ``port_sea`` lines
    write the comma and stop, so the second half is legitimately empty.
    """
    path, sep, rest = value.partition(",")
    return path.strip(), (rest.strip() if sep else "")


# ---------------------------------------------------------------------------
# shape one: flat `keyword value` records


REBELS = Shape(
    rel="descr_rebel_factions.txt", label="Rebel factions", kw="rebel_type",
    noun="rebel faction",
    order=("category", "chance", "description"),
    required=("category", "chance", "description"),
    repeat_kw="unit")

#: the four categories the engine knows (measured: 68 real records use only these)
REBEL_CATEGORIES = ("gladiator_revolt", "brigands", "pirates", "peasant_revolt")

#: ``descr_sm_resources.txt``. ``mine`` is a file-level line naming the model a
#: mined resource shows, not a per-resource key — ``has_mine`` is the per-resource
#: flag that opts into it.
RESOURCES = Shape(
    rel="descr_sm_resources.txt", label="Resources", kw="type", noun="resource",
    order=("trade_value", "item", "icon", "has_mine"),
    required=("trade_value", "item", "icon"),
    flags=("has_mine",),
    preamble_keys=("mine",))

#: the 28 resource names all three installed mods ship — in three different
#: orders, and with no additions. The engine's list is closed: a `type` it does
#: not know is read and ignored.
KNOWN_RESOURCES = (
    "amber", "camels", "chocolate", "coal", "cotton", "dogs", "dyes", "elephants",
    "fish", "furs", "generic", "gold", "grain", "iron", "ivory", "marble",
    "silk", "silver", "slaves", "spices", "sugar", "sulfur", "textiles",
    "timber", "tin", "tobacco", "wine", "wool")



def check_records(shape: Shape, rf: RecordFile, mod=None) -> List[Dict]:
    """Findings for a whole flat-record file.

    The three any such file can have — a duplicate name, a missing required line,
    lines out of order — come from :func:`unittransfer.flatrecord.check_records`.
    What is left here is what these two files MEAN by their values.
    """
    out: List[Dict] = fr.check_records(shape, rf)

    def add(kind: str, name: str, line: int, message: str) -> None:
        out.append({"kind": kind, "name": name, "line": line + 1, "message": message})

    units = None
    if mod is not None and shape is REBELS:
        try:
            units = {u.type for u in mod.edu.units}
        except (OSError, AttributeError, ValueError):
            units = None

    for rec in rf.records:
        if shape is REBELS:
            category = rec.get("category")
            if category and category not in REBEL_CATEGORIES:
                add("unknown-category", rec.name, rec.lines["category"],
                    f"`{category}` is not one of the four categories the engine "
                    "knows: " + kb.and_list(REBEL_CATEGORIES))
            chance = rec.get("chance")
            if chance and not kb.is_int(chance):
                add("bad-chance", rec.name, rec.lines["chance"],
                    f"`{chance}` is not a whole number")
            if not rec.repeats:
                add("no-units", rec.name, rec.start,
                    "no `unit` line — a rebel faction with no units cannot spawn")
            for rep in rec.repeats:
                if units is not None and rep.value not in units:
                    add("unknown-unit", rec.name, rep.line,
                        f"`{rep.value}` is not a unit in this mod's EDU")

        if shape is RESOURCES:
            value = rec.get("trade_value")
            if value and not kb.is_int(value):
                add("bad-trade-value", rec.name, rec.lines["trade_value"],
                    f"`{value}` is not a whole number")
            if rec.name and rec.name not in KNOWN_RESOURCES:
                add("unknown-resource", rec.name, rec.start,
                    f"`{rec.name}` is not one of the 28 resources the engine knows "
                    "— the line is read and then ignored")
    return out


# ---- the two flat files by name, so callers do not pass shapes around -------

def parse_rebels(text: str) -> RecordFile:
    return parse_records(REBELS, text)


def parse_resources(text: str) -> RecordFile:
    return parse_records(RESOURCES, text)


#: where a rebel faction's shown name lives, relative to ``data/``. Tagged by the
#: record's ``description`` value, which every one of the 68 real records sets to
#: its own name.
REBELS_LOC_REL = "text/rebel_faction_descr.txt"

#: …and a resource's, which is a different kind of file — see :data:`LOC_FILES`.
RESOURCES_LOC_REL = "text/strat.txt"


def rebel_loc(mod) -> Dict[str, str]:
    """``{tag: text}`` from ``text/rebel_faction_descr.txt`` — a rebel's shown name."""
    return _loc(mod, REBELS_LOC_REL)


def resource_loc(mod) -> Dict[str, str]:
    """``{tag: text}`` from ``text/strat.txt``, where resource names live."""
    return _loc(mod, RESOURCES_LOC_REL)


def resource_tag(name: str) -> str:
    """``timber`` -> ``SMT_RESOURCE_TIMBER``, the tag ``strat.txt`` writes."""
    return "SMT_RESOURCE_" + (name or "").strip().upper()


# ---------------------------------------------------------------------------
# shape two, first file: descr_religions.txt
#
# A religion is written down three times and the three can disagree — see the
# module docstring. The `religions { … }` list is what the engine reads as the
# set; the `religion x { … }` block is where its pip comes from.


RELIGIONS_REL = "descr_religions.txt"
RELIGIONS_LOOKUP_REL = "descr_religions_lookup.txt"
RELIGIONS_LOC_REL = "text/religions.txt"

#: the only key any of the 25 real religion blocks carries
RELIGION_KEYS = ("pip_path",)


@dataclass
class Religion:
    """One ``religion <name> { pip_path … }`` block."""
    name: str = ""
    values: Dict[str, str] = field(default_factory=dict)
    lines: Dict[str, int] = field(default_factory=dict)
    start: int = 0                    # the `religion <name>` line
    end: int = 0                      # one past the closing brace
    warnings: List[str] = field(default_factory=list)

    @property
    def pip_path(self) -> str:
        return self.values.get("pip_path", "")

    def as_dict(self) -> Dict:
        return {"name": self.name, "pip_path": self.pip_path,
                "start": self.start, "end": self.end}


@dataclass
class ReligionFile(LineFile):
    """A whole ``descr_religions.txt``: the list block and the religion blocks."""
    religions: List[Religion] = field(default_factory=list)
    #: the names inside `religions { … }`, in file order, and the line each is on
    listed: List[str] = field(default_factory=list)
    listed_lines: Dict[str, int] = field(default_factory=dict)
    list_start: int = -1              # the `religions` line
    list_end: int = -1                # its closing brace

    @property
    def items(self) -> List[Religion]:
        return self.religions

    def get(self, name: str) -> Optional[Religion]:
        return next((r for r in self.religions if r.name == name), None)

    def by_name(self) -> Dict[str, Religion]:
        return {r.name: r for r in self.religions}

    def block_text(self, rel: Religion) -> str:
        return self.newline.join(self.lines[rel.start:rel.end])


def parse_religions(text: str) -> ReligionFile:
    """Read a whole ``descr_religions.txt``. Never raises."""
    lines, newline, trailing = split_lines(text)
    rf = ReligionFile(lines=lines, newline=newline, trailing_newline=trailing)
    i = 0
    while i < len(lines):
        code = kb.code_of(lines[i])
        if not code:
            i += 1
            continue
        key, value = _head(code)
        if key == "religions" and not value:
            end = _closing(lines, i)
            if end < 0:
                rf.warnings.append(f"line {i + 1}: `religions` has no closing brace")
                i += 1
                continue
            rf.list_start, rf.list_end = i, end
            for j in range(i + 1, end):
                name = kb.code_of(lines[j])
                if not name or name in "{}":
                    continue
                if name in rf.listed_lines:
                    rf.warnings.append(f"line {j + 1}: `{name}` is listed twice")
                rf.listed.append(name)
                rf.listed_lines.setdefault(name, j)
            i = end + 1
            continue
        if key == "religion":
            end = _closing(lines, i)
            rel = Religion(name=value, start=i,
                           end=(end + 1) if end >= 0 else i + 1)
            if not value:
                rel.warnings.append(f"line {i + 1}: this religion has no name")
            if end < 0:
                rel.warnings.append(f"line {i + 1}: `religion {value}` has no "
                                    "closing brace")
            for j in range(i + 1, rel.end):
                body = kb.code_of(lines[j])
                if not body or body in "{}":
                    continue
                bkey, bvalue = _head(body)
                if bkey not in RELIGION_KEYS:
                    rel.warnings.append(f"line {j + 1}: `{bkey}` is not a religion line")
                rel.values[bkey] = bvalue
                rel.lines[bkey] = j
            rf.religions.append(rel)
            i = rel.end
            continue
        rf.warnings.append(f"line {i + 1}: `{key}` is not a descr_religions line")
        i += 1

    for rel in rf.religions:
        rf.warnings.extend(f"{rel.name or '(unnamed)'}: {w}" for w in rel.warnings)
    return rf


def parse_religion_block(text: str) -> Religion:
    """Read ONE ``religion … { … }`` block, as a code view pane holds it."""
    rf = parse_religions(text if text.endswith("\n") else text + "\n")
    if not rf.religions:
        raise MinorError("a religion starts with a `religion <name>` line followed "
                         "by `{` — this text has none", 1)
    if len(rf.religions) > 1:
        raise MinorError(f"this text holds {len(rf.religions)} religions — "
                         "one at a time", rf.religions[1].start + 1)
    return rf.religions[0]


def render_religion(base: str, edits: Optional[Dict] = None) -> str:
    """Apply GUI edits to one religion block. ``edits`` is ``{name, pip_path}``."""
    edits = edits or {}
    rel = parse_religion_block(base)
    lines, newline, _ = split_lines(base)
    sp = kb.Splice(lines)
    if "name" in edits:
        name = str(edits["name"] or "").strip()
        if not name:
            raise MinorError("a religion needs a name", rel.start + 1)
        if name != rel.name:
            sp.replace(rel.start, kb.sub_value(lines[rel.start], "religion", name))
    if "pip_path" in edits:
        value = str(edits["pip_path"] or "").strip()
        line = rel.lines.get("pip_path", -1)
        if not value:
            raise MinorError("a religion needs its `pip_path` line — the pip is what "
                             "the campaign map draws for it",
                             (line + 1) or (rel.start + 1))
        if line >= 0:
            if value != rel.values.get("pip_path", ""):
                sp.replace(line, kb.sub_value(lines[line], "pip_path", value))
        else:
            # under the opening brace, indented like the block it joins
            brace = next((i for i in range(rel.start, rel.end)
                          if kb.code_of(lines[i]) == "{"), rel.start)
            sp.after(brace, [kb.indent_of(lines[rel.start]) + "\t" +
                             f"pip_path\t{value}"])
    return newline.join(sp.result())


def new_religion(edits: Dict) -> str:
    """A whole religion block written from scratch."""
    name = str(edits.get("name") or "").strip()
    if not name:
        raise MinorError("a new religion needs a name")
    pip = str(edits.get("pip_path") or f"ui/pips/pip_{name}.tga").strip()
    return f"religion {name}\n{{\n\tpip_path\t{pip}\n}}"


def edit_religions_file(text: str, add: str = "", remove: str = "",
                        block: str = "") -> str:
    """The whole ``descr_religions.txt`` with one religion joined or dropped.

    A religion is written down twice inside this one file — once in the
    ``religions { … }`` list the engine reads as the set, and once as its own
    ``religion x { … }`` block, which is where its pip comes from. Adding one
    that lands in only the list has no pip; adding one that lands in only the
    block does not exist. So both go in one splice, and a delete takes both.
    """
    rf = parse_religions(text)
    sp = kb.Splice(rf.lines)
    if add:
        if rf.get(add) is not None or add in rf.listed_lines:
            raise MinorError(f"`{add}` is already a religion in this file")
        if rf.list_start < 0:
            raise MinorError("this file has no `religions { … }` list to join — the "
                             "engine reads that list, so a religion outside it does "
                             "not exist")
        last = max(rf.listed_lines.values()) if rf.listed_lines else rf.list_start
        pad = (kb.indent_of(rf.lines[last]) if rf.listed_lines
               else kb.indent_of(rf.lines[rf.list_start]) + "\t")
        sp.after(last, [pad + add])
        body, _, _ = split_lines(block or new_religion({"name": add}))
        while body and not body[-1].strip():
            body.pop()
        at = rf.religions[-1].end - 1 if rf.religions else rf.list_end
        sp.after(at, [""] + body)
    if remove:
        rel = rf.get(remove)
        if rel is None and remove not in rf.listed_lines:
            raise MinorError(f"`{remove}` is not a religion in this file")
        if remove in rf.listed_lines:
            sp.drop(rf.listed_lines[remove])
        if rel is not None:
            for i in range(rel.start, rel.end):
                sp.drop(i)
    lines = sp.result()
    out = rf.newline.join(lines)
    return out + rf.newline if rf.trailing_newline and lines else out


def edit_lookup(text: str, add: str = "", remove: str = "") -> str:
    """``descr_religions_lookup.txt`` with one name appended or dropped.

    Measured rather than assumed: the three installed mods disagree about this
    file's *order* (Third Age 3 has islam and orthodox the other way round from
    its own ``religions`` list) and about its *contents* (Third Age 6 lists a
    ``wicked`` that no longer exists), and all three run. So a save keeps it in
    step by name only — appending or dropping a line, never reordering one.
    """
    lines, newline, trailing = split_lines(text)
    sp = kb.Splice(lines)
    have = [kb.code_of(ln) for ln in lines]
    if add and add not in have:
        last = max((i for i, c in enumerate(have) if c), default=len(lines) - 1)
        sp.after(last, [kb.indent_of(lines[last]) + add if last >= 0 else add])
    if remove:
        for i, code in enumerate(have):
            if code == remove:
                sp.drop(i)
    out = newline.join(sp.result())
    return out + newline if trailing and lines else out


def religion_spans(block: str) -> Dict[str, List[List[int]]]:
    rel = parse_religion_block(block)
    spans = {"name": [[rel.start + 1, rel.start + 1]]}
    for key, line in rel.lines.items():
        spans[key] = [[line + 1, line + 1]]
    return spans


def religion_fields(block: str) -> List[Tuple[str, str]]:
    rel = parse_religion_block(block)
    out = [("name", rel.name)]
    for key, _ in sorted(rel.lines.items(), key=lambda kv: kv[1]):
        out.append((key, rel.values.get(key, "")))
    return out


def parse_lookup(text: str) -> List[str]:
    """``descr_religions_lookup.txt`` — one religion per line, in index order."""
    return [kb.code_of(ln) for ln in text.replace("\r\n", "\n").split("\n")
            if kb.code_of(ln)]


def religion_loc(mod) -> Dict[str, str]:
    """``{tag: text}`` from ``text/religions.txt`` — the name shown in game."""
    return _loc(mod, RELIGIONS_LOC_REL)


def check_religions(rf: ReligionFile, lookup: Optional[List[str]] = None,
                    names: Optional[Dict[str, str]] = None) -> List[Dict]:
    """Findings for the religion set — mostly, the three lists disagreeing.

    A religion has to be in the ``religions { … }`` list, have its own block, be
    in ``descr_religions_lookup.txt`` and have a name in ``text/religions.txt``
    (geeko's tutorial, and confirmed by all three installed mods keeping all four
    in step for the religions they actually use).
    """
    out: List[Dict] = []

    def add(kind: str, name: str, line: int, message: str) -> None:
        out.append({"kind": kind, "name": name, "line": line + 1, "message": message})

    seen: Dict[str, int] = {}
    for rel in rf.religions:
        if rel.name in seen:
            add("duplicate-block", rel.name, rel.start,
                f"`{rel.name}` already has a block on line {seen[rel.name] + 1} — "
                "the second one is dead text")
        else:
            seen[rel.name] = rel.start
        if "pip_path" not in rel.lines:
            add("missing-pip", rel.name, rel.start,
                "no `pip_path` line — the campaign map has no pip to draw")

    for name in rf.listed:
        if name not in seen:
            add("listed-without-block", name, rf.listed_lines.get(name, rf.list_start),
                f"`{name}` is in the `religions` list but has no `religion {name}` "
                "block, so it has no pip")
    for rel in rf.religions:
        if rel.name and rel.name not in rf.listed_lines:
            add("block-without-listing", rel.name, rel.start,
                f"`{rel.name}` has a block but is not in the `religions` list — the "
                "engine reads the list, so this religion does not exist")

    if lookup is not None:
        for name in rf.listed:
            if name not in lookup:
                add("missing-from-lookup", name,
                    rf.listed_lines.get(name, rf.list_start),
                    f"`{name}` is not in {RELIGIONS_LOOKUP_REL}")
        for name in lookup:
            if name not in rf.listed_lines:
                add("stale-in-lookup", name, rf.list_start,
                    f"{RELIGIONS_LOOKUP_REL} still lists `{name}`, which this file "
                    "no longer defines")
    if names is not None and names:
        for name in rf.listed:
            if name not in names:
                add("missing-name", name, rf.listed_lines.get(name, rf.list_start),
                    f"no `{{{name}}}` entry in {RELIGIONS_LOC_REL} — the religion "
                    "shows its code name in game")
    return out


# ---------------------------------------------------------------------------
# shape two, second file: descr_cultures.txt
#
# The one file here with two levels of braces. A culture is a head line, a
# `{ … }` holding the settlement ladder, and then a TAIL of flat lines — forts,
# ports, watchtowers and the six agents — that belong to the culture even though
# they sit outside its brace. That shape is why the record ends at the next
# `culture` line rather than at a closing brace.


CULTURES_REL = "descr_cultures.txt"

#: file-level lines above the first culture
CULTURE_PREAMBLE = ("symbol", "siege", "blockade")

#: the head lines, between `culture <name>` and the settlement brace
CULTURE_HEAD = ("portrait_mapping", "rebel_standard_index")

#: single-valued tail keys, in the order all 39 real cultures write them
CULTURE_TAIL = ("fort", "fort_cost", "fort_wall", "fishing_village",
                "watchtower", "watchtower_cost")

#: the tail keys that repeat — a port level is a `port_land` / `port_sea` pair
CULTURE_PORT_KEYS = ("port_land", "port_sea")

#: one line each, seven tokens: keyword, three .tga names, a cost, and two more
#: numbers that no document on this machine explains — all 234 real agent lines
#: write `1 1` for them, so they are carried by position and never rewritten
CULTURE_AGENTS = ("spy", "assassin", "diplomat", "admiral", "merchant", "priest")

#: the settlement levels a culture draws, in the order the real files write them
CULTURE_LEVELS = ("village", "moot_and_bailey", "town", "wooden_castle",
                  "large_town", "castle", "city", "fortress", "large_city",
                  "citadel", "huge_city")

#: what a level block holds: the strat model (plus its settlement plan) and the
#: settlement card
CULTURE_LEVEL_KEYS = ("normal", "card")


@dataclass
class CultureLevel:
    """One settlement level inside a culture's brace."""
    name: str = ""
    values: Dict[str, str] = field(default_factory=dict)
    lines: Dict[str, int] = field(default_factory=dict)
    start: int = 0
    end: int = 0

    @property
    def model(self) -> str:
        return split_pair(self.values.get("normal", ""))[0]

    @property
    def plan(self) -> str:
        return split_pair(self.values.get("normal", ""))[1]

    def as_dict(self) -> Dict:
        return {"name": self.name, "model": self.model, "plan": self.plan,
                "card": self.values.get("card", ""),
                "start": self.start, "end": self.end}


@dataclass
class Culture:
    """One culture: head lines, the settlement ladder, and the tail."""
    name: str = ""
    values: Dict[str, str] = field(default_factory=dict)
    lines: Dict[str, int] = field(default_factory=dict)
    levels: List[CultureLevel] = field(default_factory=list)
    #: ``[(keyword, value, line)]`` for the port ladder, in file order
    ports: List[Tuple[str, str, int]] = field(default_factory=list)
    #: agent -> (tokens after the keyword, line)
    agents: Dict[str, Tuple[List[str], int]] = field(default_factory=dict)
    start: int = 0
    end: int = 0
    brace_start: int = -1
    brace_end: int = -1
    warnings: List[str] = field(default_factory=list)

    def get(self, key: str) -> str:
        return self.values.get(key, "")

    def level(self, name: str) -> Optional[CultureLevel]:
        return next((l for l in self.levels if l.name == name), None)

    def as_dict(self) -> Dict:
        d: Dict = {"name": self.name, "start": self.start, "end": self.end,
                   "levels": [l.as_dict() for l in self.levels],
                   "ports": [{"key": k, "value": v, "line": i}
                             for k, v, i in self.ports],
                   "agents": {a: {"tokens": list(t), "line": i}
                              for a, (t, i) in self.agents.items()}}
        for key in CULTURE_HEAD + CULTURE_TAIL:
            d[key] = self.get(key)
        return d


@dataclass
class CultureFile(LineFile):
    cultures: List[Culture] = field(default_factory=list)
    preamble: Dict[str, Tuple[str, int]] = field(default_factory=dict)

    @property
    def items(self) -> List[Culture]:
        return self.cultures

    def get(self, name: str) -> Optional[Culture]:
        return next((c for c in self.cultures if c.name == name), None)

    def by_name(self) -> Dict[str, Culture]:
        return {c.name: c for c in self.cultures}

    def block_text(self, cul: Culture) -> str:
        return self.newline.join(self.lines[cul.start:cul.end])


def parse_cultures(text: str) -> CultureFile:
    """Read a whole ``descr_cultures.txt``. Never raises."""
    lines, newline, trailing = split_lines(text)
    cf = CultureFile(lines=lines, newline=newline, trailing_newline=trailing)
    cur: Optional[Culture] = None
    i = 0
    while i < len(lines):
        code = kb.code_of(lines[i])
        if not code:
            i += 1
            continue
        key, value = _head(code)
        if key == "culture":
            cur = Culture(name=value, start=i, end=i + 1)
            if not value:
                cur.warnings.append(f"line {i + 1}: this culture has no name")
            cf.cultures.append(cur)
            i += 1
            continue
        if cur is None:
            if key in CULTURE_PREAMBLE:
                cf.preamble[key] = (value, i)
            else:
                cf.warnings.append(
                    f"line {i + 1}: `{key}` before the first `culture` line")
            i += 1
            continue
        if code == "{" and cur.brace_start < 0:
            end = _closing(lines, i)
            if end < 0:
                cur.warnings.append(f"line {i + 1}: the settlement block never closes")
                i += 1
                continue
            cur.brace_start, cur.brace_end = i, end
            _parse_levels(cur, lines, i, end)
            cur.end = end + 1
            i = end + 1
            continue
        if key in CULTURE_PORT_KEYS:
            cur.ports.append((key, value, i))
        elif key in CULTURE_AGENTS:
            tokens = code.split()[1:]
            if len(tokens) != 6:
                cur.warnings.append(
                    f"line {i + 1}: `{key}` has {len(tokens)} values, and every real "
                    "agent line has 6")
            cur.agents[key] = (tokens, i)
        elif key in CULTURE_HEAD + CULTURE_TAIL:
            if key in cur.lines:
                cur.warnings.append(f"line {i + 1}: a second `{key}` line")
            cur.values[key] = value
            cur.lines[key] = i
        else:
            cur.warnings.append(f"line {i + 1}: `{key}` is not a culture line")
        cur.end = i + 1
        i += 1

    for cul in cf.cultures:
        cf.warnings.extend(f"{cul.name or '(unnamed)'}: {w}" for w in cul.warnings)
    return cf


def _parse_levels(cul: Culture, lines: List[str], start: int, end: int) -> None:
    """The settlement ladder inside a culture's brace."""
    i = start + 1
    while i < end:
        code = kb.code_of(lines[i])
        if not code or code in "{}":
            i += 1
            continue
        name = code.split()[0]
        close = _closing(lines, i)
        if close < 0 or close > end:
            cul.warnings.append(f"line {i + 1}: `{name}` has no closing brace")
            i += 1
            continue
        lvl = CultureLevel(name=name, start=i, end=close + 1)
        if name not in CULTURE_LEVELS:
            cul.warnings.append(f"line {i + 1}: `{name}` is not a settlement level")
        for j in range(i + 1, close):
            body = kb.code_of(lines[j])
            if not body or body in "{}":
                continue
            bkey, bvalue = _head(body)
            if bkey not in CULTURE_LEVEL_KEYS:
                cul.warnings.append(
                    f"line {j + 1}: `{bkey}` is not a settlement-level line")
            lvl.values[bkey] = bvalue
            lvl.lines[bkey] = j
        cul.levels.append(lvl)
        i = close + 1


def parse_culture_block(text: str) -> Culture:
    """Read ONE culture record, as a code view pane holds it."""
    cf = parse_cultures(text if text.endswith("\n") else text + "\n")
    if not cf.cultures:
        raise MinorError("a culture starts with a `culture <name>` line — this text "
                         "has none", 1)
    if len(cf.cultures) > 1:
        raise MinorError(f"this text holds {len(cf.cultures)} cultures — one at a "
                         "time", cf.cultures[1].start + 1)
    return cf.cultures[0]


def render_culture(base: str, edits: Optional[Dict] = None) -> str:
    """Apply GUI edits to one culture record.

    ``edits`` is ``{name, portrait_mapping, rebel_standard_index, fort, …,
    levels: {village: {model, plan, card}, …}, agents: {spy: {cost}, …}}`` and
    every key is optional. A level's ``normal`` line is rewritten from its model
    and plan together, because that is one line in the file.
    """
    edits = edits or {}
    cul = parse_culture_block(base)
    lines, newline, _ = split_lines(base)
    sp = kb.Splice(lines)

    if "name" in edits:
        name = str(edits["name"] or "").strip()
        if not name:
            raise MinorError("a culture needs a name", cul.start + 1)
        if name != cul.name:
            sp.replace(cul.start, kb.sub_value(lines[cul.start], "culture", name))

    for key in CULTURE_HEAD + CULTURE_TAIL:
        if key not in edits:
            continue
        value = str(edits[key] or "").strip()
        line = cul.lines.get(key, -1)
        if line < 0:
            raise MinorError(f"this culture has no `{key}` line to edit — adding one "
                             "means saying where it goes, which the file's own order "
                             "decides", cul.start + 1)
        if not value:
            raise MinorError(f"a culture needs its `{key}` line", line + 1)
        if value != cul.values.get(key, ""):
            sp.replace(line, kb.sub_value(lines[line], key, value))

    for name, want in (edits.get("levels") or {}).items():
        lvl = cul.level(name)
        if lvl is None:
            raise MinorError(f"this culture has no `{name}` settlement level",
                             cul.start + 1)
        _edit_level(sp, lines, lvl, dict(want or {}))

    for agent, want in (edits.get("agents") or {}).items():
        held = cul.agents.get(agent)
        if held is None:
            raise MinorError(f"this culture has no `{agent}` line", cul.start + 1)
        tokens, line = held
        new = list(tokens)
        for pos, name in ((0, "card"), (1, "info_card"), (2, "pip"), (3, "cost")):
            if name in (want or {}) and pos < len(new):
                value = str(want[name] or "").strip()
                if not value:
                    raise MinorError(f"an agent's `{name}` cannot be empty", line + 1)
                new[pos] = value
        if new != tokens:
            sp.replace(line, kb.sub_tokens(lines[line], agent, new))
    return newline.join(sp.result())


def _edit_level(sp: kb.Splice, lines: List[str], lvl: CultureLevel,
                want: Dict) -> None:
    """One settlement level's two lines. ``normal`` is model and plan together."""
    if "model" in want or "plan" in want:
        line = lvl.lines.get("normal", -1)
        if line < 0:
            raise MinorError(f"`{lvl.name}` has no `normal` line", lvl.start + 1)
        model = str(want.get("model", lvl.model) or "").strip()
        plan = str(want.get("plan", lvl.plan) or "").strip()
        if not model:
            raise MinorError(f"`{lvl.name}` needs a strat model", line + 1)
        old = lvl.values.get("normal", "")
        # the gap after the comma is this file's own column, like every other gap
        rest = old.partition(",")[2]
        gap = rest[: len(rest) - len(rest.lstrip())] or "\t\t"
        value = f"{model},{gap}{plan}" if plan else f"{model},"
        if split_pair(value) != split_pair(old):
            sp.replace(line, kb.sub_value(lines[line], "normal", value))
    if "card" in want:
        line = lvl.lines.get("card", -1)
        card = str(want["card"] or "").strip()
        if line < 0:
            raise MinorError(f"`{lvl.name}` has no `card` line", lvl.start + 1)
        if not card:
            raise MinorError(f"`{lvl.name}` needs a settlement card", line + 1)
        if card != lvl.values.get("card", ""):
            sp.replace(line, kb.sub_value(lines[line], "card", card))


def replace_culture(cf: CultureFile, cul: Culture, block: str) -> str:
    """The whole file with one culture's lines — brace, tail and all — swapped."""
    return cf.replace(cul.start, cul.end, block)


def culture_spans(block: str) -> Dict[str, List[List[int]]]:
    cul = parse_culture_block(block)
    spans: Dict[str, List[List[int]]] = {"name": [[cul.start + 1, cul.start + 1]]}
    for key, line in cul.lines.items():
        spans[key] = [[line + 1, line + 1]]
    for lvl in cul.levels:
        spans[f"level.{lvl.name}"] = [[lvl.start + 1, lvl.end]]
        for key, line in lvl.lines.items():
            spans[f"level.{lvl.name}.{key}"] = [[line + 1, line + 1]]
    nth: Dict[str, int] = {}
    for key, _, line in cul.ports:
        nth[key] = nth.get(key, 0) + 1
        spans[f"{key}#{nth[key]}"] = [[line + 1, line + 1]]
    for agent, (_, line) in cul.agents.items():
        spans[f"agent.{agent}"] = [[line + 1, line + 1]]
    return spans


def culture_fields(block: str) -> List[Tuple[str, str]]:
    cul = parse_culture_block(block)
    out = [("name", cul.name)]
    for key, _ in sorted(cul.lines.items(), key=lambda kv: kv[1]):
        out.append((key, cul.values.get(key, "")))
    for lvl in cul.levels:
        out.append((f"level.{lvl.name}.normal", lvl.values.get("normal", "")))
        out.append((f"level.{lvl.name}.card", lvl.values.get("card", "")))
    nth: Dict[str, int] = {}
    for key, value, _ in cul.ports:
        nth[key] = nth.get(key, 0) + 1
        out.append((f"{key}#{nth[key]}", value))
    for agent, (tokens, _) in cul.agents.items():
        out.append((f"agent.{agent}", " ".join(tokens)))
    return out


def check_cultures(cf: CultureFile) -> List[Dict]:
    """Findings for the culture file: a missing level, a missing agent, a duplicate.

    Deliberately says nothing about the ``.tga`` files it names — see the module
    docstring on why art references are not checked here.
    """
    out: List[Dict] = []

    def add(kind: str, name: str, line: int, message: str) -> None:
        out.append({"kind": kind, "name": name, "line": line + 1, "message": message})

    # A settlement level is only missing if the file itself thinks it exists. A
    # mod that drops `moot_and_bailey` from every culture has removed the level
    # (all 10 of DaC's cultures do); one culture out of ten missing it is the
    # crash, and the difference is not something a fixed list of eleven can see.
    used = {l.name for cul in cf.cultures for l in cul.levels}

    seen: Dict[str, int] = {}
    for cul in cf.cultures:
        if cul.name in seen:
            add("duplicate", cul.name, cul.start,
                f"`{cul.name}` is already defined on line {seen[cul.name] + 1}")
        else:
            seen[cul.name] = cul.start
        have = {l.name for l in cul.levels}
        for key in CULTURE_HEAD:
            if key not in cul.lines:
                add("missing-line", cul.name, cul.start,
                    f"no `{key}` line — the game will not load this culture")
        missing = [l for l in CULTURE_LEVELS if l in used and l not in have]
        if missing:
            add("missing-levels", cul.name, cul.brace_start if cul.brace_start >= 0
                else cul.start,
                f"no {kb.and_list(missing)} block, which the other cultures here "
                "have — a settlement at that level has no model to draw")
        for agent in CULTURE_AGENTS:
            if agent not in cul.agents:
                add("missing-agent", cul.name, cul.start,
                    f"no `{agent}` line — this culture cannot recruit one")
    return out


def culture_names(mod) -> List[str]:
    """Every culture this mod defines, in file order. The single source of truth.

    :attr:`unittransfer.mod.Mod.cultures` answers a different question — which
    culture folders hold building icons — and a mod can perfectly well define a
    culture with no icon folder of its own.
    """
    path = Path(mod.data) / CULTURES_REL
    if not path.is_file():
        return []
    return [c.name for c in parse_cultures(kb.read_text(path, ENCODING)).cultures
            if c.name]


def religion_names(mod) -> List[str]:
    """Every religion this mod defines, in the order the `religions` list gives.

    The list block is the answer because the list is what the engine reads as the
    set — a religion with a block and no listing does not exist. A file with no
    list block at all falls back to its blocks, because that is a file we have no
    better reading of, not because the two are the same thing.
    """
    path = Path(mod.data) / RELIGIONS_REL
    if not path.is_file():
        return []
    rf = parse_religions(kb.read_text(path, ENCODING))
    if rf.listed:
        return list(rf.listed)
    return sorted({r.name for r in rf.religions if r.name})


def resource_names(mod) -> List[str]:
    """Every trade resource this mod defines, in file order."""
    path = Path(mod.data) / RESOURCES.rel
    if not path.is_file():
        return []
    return [r.name for r in parse_records(RESOURCES,
                                          kb.read_text(path, ENCODING)).records
            if r.name]


# ---------------------------------------------------------------------------
# shape three: descr_names.txt
#
# No braces and no keywords — a faction, then sections of bare names, one per
# line. A section header and a name are both a single word, so they are told
# apart the way the engine tells them apart: by the three names a section can
# have. Indentation agrees with that on 43 158 of 43 161 real lines, which is
# exactly why it is not the test.


NAMES_REL = "descr_names.txt"

#: the sections a faction can hold. `settlements` is in the file's own header
#: comment; none of the three installed mods uses it, and all three use `women`.
NAME_SECTIONS = ("settlements", "characters", "women")


@dataclass
class NameSection:
    """One ``characters`` / ``women`` / ``settlements`` list."""
    name: str = ""
    entries: List[Repeat] = field(default_factory=list)
    start: int = 0
    end: int = 0

    def as_dict(self) -> Dict:
        return {"name": self.name, "start": self.start, "end": self.end,
                "entries": [e.value for e in self.entries]}


@dataclass
class NameFaction:
    """One ``faction: <name>`` record and its sections."""
    name: str = ""
    sections: List[NameSection] = field(default_factory=list)
    start: int = 0
    end: int = 0
    warnings: List[str] = field(default_factory=list)

    def section(self, name: str) -> Optional[NameSection]:
        return next((s for s in self.sections if s.name == name), None)

    def as_dict(self) -> Dict:
        return {"name": self.name, "start": self.start, "end": self.end,
                "sections": [s.as_dict() for s in self.sections]}


@dataclass
class NameFile(LineFile):
    factions: List[NameFaction] = field(default_factory=list)

    @property
    def items(self) -> List[NameFaction]:
        return self.factions

    def get(self, name: str) -> Optional[NameFaction]:
        return next((f for f in self.factions if f.name == name), None)

    def by_name(self) -> Dict[str, NameFaction]:
        return {f.name: f for f in self.factions}

    def block_text(self, fac: NameFaction) -> str:
        return self.newline.join(self.lines[fac.start:fac.end])


def parse_names(text: str) -> NameFile:
    """Read a whole ``descr_names.txt``. Never raises."""
    lines, newline, trailing = split_lines(text)
    nf = NameFile(lines=lines, newline=newline, trailing_newline=trailing)
    fac: Optional[NameFaction] = None
    sec: Optional[NameSection] = None
    for i, raw in enumerate(lines):
        code = kb.code_of(raw)
        if not code:
            continue
        low = code.lower()
        if low.startswith("faction:"):
            fac = NameFaction(name=code.split(":", 1)[1].strip(), start=i, end=i + 1)
            sec = None
            if not fac.name:
                fac.warnings.append(f"line {i + 1}: this faction has no name")
            nf.factions.append(fac)
            continue
        if fac is None:
            nf.warnings.append(f"line {i + 1}: `{code}` before the first faction")
            continue
        if low in NAME_SECTIONS:
            sec = NameSection(name=low, start=i, end=i + 1)
            fac.sections.append(sec)
            fac.end = i + 1
            continue
        if sec is None:
            fac.warnings.append(
                f"line {i + 1}: `{code}` is not under a "
                f"{kb.and_list(NAME_SECTIONS)} heading")
            fac.end = i + 1
            continue
        if len(code.split()) > 1:
            fac.warnings.append(f"line {i + 1}: `{code}` has a space in it — a name "
                                "is one word")
        sec.entries.append(Repeat(value=code, line=i))
        sec.end = fac.end = i + 1

    for f in nf.factions:
        nf.warnings.extend(f"{f.name or '(unnamed)'}: {w}" for w in f.warnings)
    return nf


def parse_names_block(text: str) -> NameFaction:
    """Read ONE faction's names, as a code view pane holds it."""
    nf = parse_names(text if text.endswith("\n") else text + "\n")
    if not nf.factions:
        raise MinorError("this text has no `faction: <name>` line", 1)
    if len(nf.factions) > 1:
        raise MinorError(f"this text holds {len(nf.factions)} factions — "
                         "one at a time", nf.factions[1].start + 1)
    return nf.factions[0]


def render_names(base: str, edits: Optional[Dict] = None) -> str:
    """Apply GUI edits to one faction's names.

    ``edits`` is ``{name, sections: {characters: [str], women: [str]}}``. A list
    is index-aligned with what is there, so renaming the fourth character
    rewrites one line and leaves 800 others exactly as they were.
    """
    edits = edits or {}
    fac = parse_names_block(base)
    lines, newline, _ = split_lines(base)
    sp = kb.Splice(lines)
    if "name" in edits:
        name = str(edits["name"] or "").strip()
        if not name:
            raise MinorError("a faction needs a name", fac.start + 1)
        if name != fac.name:
            sp.replace(fac.start, kb.keep_comment(
                lines[fac.start], kb.indent_of(lines[fac.start]) + f"faction: {name}"))
    for which, wanted in (edits.get("sections") or {}).items():
        sec = fac.section(str(which).lower())
        if sec is None:
            raise MinorError(f"this faction has no `{which}` section", fac.start + 1)
        rows = [str(v).strip() for v in (wanted or [])]
        for value in rows:
            if len(value.split()) > 1:
                raise MinorError(f"`{value}` has a space in it — a name is one word",
                                 sec.start + 1)
        _edit_entries(sp, lines, sec, rows)
    return newline.join(sp.result())


def _edit_entries(sp: kb.Splice, lines: List[str], sec: NameSection,
                  wanted: List[str]) -> None:
    """A section's name list, index-aligned with the lines already there."""
    olds = sec.entries
    for i in range(min(len(olds), len(wanted))):
        if wanted[i] and wanted[i] != olds[i].value:
            sp.replace(olds[i].line,
                       kb.keep_comment(lines[olds[i].line],
                                       kb.indent_of(lines[olds[i].line]) + wanted[i]))
        elif not wanted[i]:
            raise MinorError("a name cannot be blank", olds[i].line + 1)
    if len(wanted) > len(olds):
        pad = (kb.indent_of(lines[olds[-1].line]) if olds
               else kb.indent_of(lines[sec.start]) + "\t")
        sp.after(olds[-1].line if olds else sec.start,
                 [pad + v for v in wanted[len(olds):] if v])
    elif len(wanted) < len(olds):
        for old in olds[len(wanted):]:
            sp.drop(old.line)


def new_names(edits: Dict) -> str:
    """A whole ``faction: x`` record written from scratch.

    Always with a ``characters`` heading, even when nobody typed a name under it
    yet: a faction with no ``characters`` section cannot generate a family, and a
    heading with nothing under it is at least a hole this module's own check can
    see. Indented the way all three real files indent theirs.
    """
    name = str(edits.get("name") or "").strip()
    if not name:
        raise MinorError("a new faction needs a name")
    out = [f"faction: {name}", ""]
    sections = dict(edits.get("sections") or {})
    for which in ("characters", "women"):
        rows = [str(v).strip() for v in (sections.get(which) or []) if str(v).strip()]
        if which != "characters" and not rows:
            continue
        for value in rows:
            if len(value.split()) > 1:
                raise MinorError(f"`{value}` has a space in it — a name is one word")
        out += ["\t" + which] + ["\t\t" + v for v in rows] + [""]
    while out and not out[-1]:
        out.pop()
    return "\n".join(out)


def names_spans(block: str) -> Dict[str, List[List[int]]]:
    fac = parse_names_block(block)
    spans: Dict[str, List[List[int]]] = {"name": [[fac.start + 1, fac.start + 1]]}
    for sec in fac.sections:
        spans[sec.name] = [[sec.start + 1, sec.end]]
        for n, entry in enumerate(sec.entries, 1):
            spans[f"{sec.name}#{n}"] = [[entry.line + 1, entry.line + 1]]
    return spans


def names_fields(block: str) -> List[Tuple[str, str]]:
    """One row per section rather than per name: a faction can have 800 of them."""
    fac = parse_names_block(block)
    out = [("name", fac.name)]
    for sec in fac.sections:
        out.append((sec.name, f"{len(sec.entries)} name(s)"))
    return out


def check_names(nf: NameFile, mod=None) -> List[Dict]:
    """Findings for the names file: duplicates, empty sections, unknown factions."""
    out: List[Dict] = []

    def add(kind: str, name: str, line: int, message: str) -> None:
        out.append({"kind": kind, "name": name, "line": line + 1, "message": message})

    known = None
    if mod is not None:
        try:
            known = set(mod.faction_cultures) or None
        except (OSError, AttributeError, ValueError):
            known = None

    seen: Dict[str, int] = {}
    for fac in nf.factions:
        if fac.name in seen:
            add("duplicate", fac.name, fac.start,
                f"`{fac.name}` already has a block on line {seen[fac.name] + 1} — the "
                "engine reads the first and ignores this one")
        else:
            seen[fac.name] = fac.start
        if known is not None and fac.name not in known:
            add("unknown-faction", fac.name, fac.start,
                f"`{fac.name}` is not a faction in descr_sm_factions.txt")
        if not fac.sections:
            add("no-sections", fac.name, fac.start,
                "no `characters` section — a faction with no names cannot generate "
                "a family")
        for sec in fac.sections:
            if not sec.entries:
                add("empty-section", fac.name, sec.start,
                    f"the `{sec.name}` section is empty")
            here: Dict[str, int] = {}
            for entry in sec.entries:
                if entry.value in here:
                    add("duplicate-name", fac.name, entry.line,
                        f"`{entry.value}` is already in this `{sec.name}` list on "
                        f"line {here[entry.value] + 1}")
                else:
                    here[entry.value] = entry.line
    return out


# ---------------------------------------------------------------------------
# localisation, shared by the files that have any


def _loc(mod, rel: str) -> Dict[str, str]:
    """``{tag: text}`` from a ``{tag}text`` file, or its compiled archive.

    The same read the traits and ancillaries editors make, through Phase 6's
    codec when a mod ships only the ``.strings.bin`` — which for a released mod
    is the normal case.
    """
    from . import stringsbin
    path = Path(getattr(mod, "data", "")) / rel
    try:
        if path.exists():
            return dict(stringsbin.from_txt(kb.read_text(path, "utf-16")))
    except (OSError, UnicodeError, ValueError):
        pass
    try:
        return stringsbin.load_pairs(stringsbin.bin_path_for(path))
    except (OSError, ValueError):
        return {}


def label(name: str, names: Dict[str, str], tag: str = "") -> str:
    """``"Timber (timber)"`` — the toolkit's naming rule, localised name first.

    A text entry whose value is just its own key is a placeholder rather than a
    name, and shows as the code name alone — the same ruling the buildings and
    ancillaries editors make.
    """
    shown = (names.get(tag or name) or "").strip()
    if not shown or shown == name or shown == (tag or name):
        return name
    return f"{shown} ({name})"


# ---------------------------------------------------------------------------
# the registry the Minor Files module is built from
#
# One row per file: what it is called, where it lives, and the code view kind
# that edits one of its records. Phase 10b's tabs are this list.


@dataclass(frozen=True)
class MinorKind:
    #: the tab id, which is also its :mod:`unittransfer.codeview` kind — one name
    #: for one file shape, so a tab cannot end up pointed at another tab's parser
    id: str
    label: str
    rel: str
    noun: str


TABS: Tuple[MinorKind, ...] = (
    MinorKind("rebels", "Rebel factions", REBELS.rel, "rebel faction"),
    MinorKind("religions", "Religions", RELIGIONS_REL, "religion"),
    MinorKind("resources", "Resources", RESOURCES.rel, "resource"),
    MinorKind("cultures", "Cultures", CULTURES_REL, "culture"),
    MinorKind("names", "Character names", NAMES_REL, "faction"),
)


def tab(tab_id: str) -> MinorKind:
    for t in TABS:
        if t.id == tab_id:
            return t
    raise KeyError(f"no minor-files tab {tab_id!r}")


def path_for(mod, tab_id: str) -> Path:
    return Path(mod.data) / tab(tab_id).rel


#: tab -> the actions it offers. Two of the five are edit-only, and both
#: refusals are the format talking rather than the session running out:
#:
#: * **resources** — the engine's list is closed. All three installed mods ship
#:   the same 28 names in three different orders and none has ever added one; a
#:   ``type`` the engine does not know is read and then ignored, so "create a
#:   resource" is a button that writes a line nothing reads. Deleting one is
#:   worse: ``descr_regions.txt`` places resources by name, and the map would
#:   keep placing a resource this file no longer defines.
#: * **cultures** — a culture is eleven settlement models, eleven settlement
#:   cards, a fort, a port ladder, a watchtower and six agents, none of which a
#:   text editor can conjure. Deleting one orphans every faction whose
#:   ``culture`` line names it and every building that requires one.
ACTIONS: Dict[str, Tuple[str, ...]] = {
    "rebels": ("edit", "add", "delete"),
    "resources": ("edit",),
    "religions": ("edit", "add", "delete"),
    "cultures": ("edit",),
    "names": ("edit", "add", "delete"),
}

#: why an edit-only tab is edit-only, shown where its buttons would be
REFUSED: Dict[str, str] = {
    "resources": "The engine's resource list is closed — all three mods measured "
                 "ship the same 28 names and a `type` it does not know is read and "
                 "ignored, so a resource can be changed but not created. Deleting "
                 "one leaves descr_regions.txt placing a resource nothing defines.",
    "cultures": "A culture is eleven settlement models and cards, a fort, a port "
                "ladder, a watchtower and six agents — nothing a text editor can "
                "create from nothing. Deleting one orphans every faction whose "
                "`culture` line names it.",
}

#: tab -> (the ``data/text`` file its names live in, whether a save may write it).
#:
#: ``strat.txt`` is the odd one and the reason this is a pair rather than a path.
#: Its compiled archive is **style 1 — 1307 bare strings with no tags at all**,
#: read by position, and identical in length across all three installed mods. Our
#: own :func:`unittransfer.stringsbin.refresh_from_txt` already refuses to rebuild
#: an untagged archive, and appending a line to the ``.txt`` would shift every
#: index after it. So the resources tab *shows* the name and sends anyone who
#: wants to change it to the Strings module, which edits that file by position —
#: the one place that can do it safely.
LOC_FILES: Dict[str, Tuple[str, bool]] = {
    "rebels": (REBELS_LOC_REL, True),
    "resources": (RESOURCES_LOC_REL, False),
    "religions": (RELIGIONS_LOC_REL, True),
}


def shape_of(tab_id: str) -> Shape:
    """The flat-record shape behind ``rebels`` / ``resources``."""
    if tab_id == "rebels":
        return REBELS
    if tab_id == "resources":
        return RESOURCES
    raise KeyError(f"{tab_id!r} is not a flat-record tab")


def parse_any(tab_id: str, text: str) -> LineFile:
    """Read a whole file of whichever of the five shapes this tab is."""
    if tab_id in ("rebels", "resources"):
        return parse_records(shape_of(tab_id), text)
    if tab_id == "religions":
        return parse_religions(text)
    if tab_id == "cultures":
        return parse_cultures(text)
    if tab_id == "names":
        return parse_names(text)
    raise KeyError(f"no minor-files tab {tab_id!r}")


def read_any(mod, tab_id: str) -> Tuple[LineFile, str]:
    """``(parsed, text)`` for one tab of one mod. Raises ``KeyError`` if absent."""
    meta = tab(tab_id)
    path = path_for(mod, tab_id)
    if not path.is_file():
        raise KeyError(f"{getattr(mod, 'name', '?')} has no {meta.rel}")
    text = kb.read_text(path, ENCODING)
    return parse_any(tab_id, text), text


def render_any(tab_id: str, base: str, edits: Optional[Dict] = None) -> str:
    """Apply GUI edits to one record, whichever shape it is."""
    if tab_id in ("rebels", "resources"):
        return render_record(shape_of(tab_id), base, edits or {})
    if tab_id == "religions":
        return render_religion(base, edits or {})
    if tab_id == "cultures":
        return render_culture(base, edits or {})
    if tab_id == "names":
        return render_names(base, edits or {})
    raise KeyError(f"no minor-files tab {tab_id!r}")


def new_any(tab_id: str, edits: Dict) -> str:
    """A whole record written from scratch — only for the tabs that allow it."""
    if tab_id in ("rebels", "resources"):
        return new_record(shape_of(tab_id), edits)
    if tab_id == "religions":
        return new_religion(edits)
    if tab_id == "names":
        return new_names(edits)
    raise MinorError(REFUSED.get(tab_id, f"{tab_id} records cannot be created here"))


def parse_block_any(tab_id: str, text: str):
    """Read ONE record of whichever shape this tab is — the code view's parse."""
    if tab_id in ("rebels", "resources"):
        return parse_record_block(shape_of(tab_id), text)
    if tab_id == "religions":
        return parse_religion_block(text)
    if tab_id == "cultures":
        return parse_culture_block(text)
    if tab_id == "names":
        return parse_names_block(text)
    raise KeyError(f"no minor-files tab {tab_id!r}")


def check_any(mod, tab_id: str, parsed: LineFile) -> List[Dict]:
    """Every finding in one whole file, with the companion files it needs.

    The religions tab is the one that reads more than its own file, because a
    religion is written down three times and the point of the check is that the
    three can disagree.
    """
    if tab_id in ("rebels", "resources"):
        return check_records(shape_of(tab_id), parsed, mod)
    if tab_id == "religions":
        lookup_path = Path(getattr(mod, "data", "")) / RELIGIONS_LOOKUP_REL
        lookup = None
        if lookup_path.is_file():
            try:
                lookup = parse_lookup(kb.read_text(lookup_path, ENCODING))
            except OSError:
                lookup = None
        return check_religions(parsed, lookup, religion_loc(mod))
    if tab_id == "cultures":
        return check_cultures(parsed)
    return check_names(parsed, mod)


def loc_names(mod, tab_id: str) -> Dict[str, str]:
    """``{tag: text}`` for the tab's own localisation file — ``{}`` when it has none."""
    rel = LOC_FILES.get(tab_id, ("", False))[0]
    return _loc(mod, rel) if rel else {}


def loc_tag(tab_id: str, rec) -> str:
    """The text key one record's shown name is stored under, or ``""``.

    Three different answers, and each one is the file's own: a rebel faction is
    keyed by its ``description`` value, a resource by ``SMT_RESOURCE_<NAME>``, and
    a religion by its own name.
    """
    if tab_id == "rebels":
        return rec.get("description") or rec.name
    if tab_id == "resources":
        return resource_tag(rec.name)
    if tab_id == "religions":
        return rec.name
    return ""


def record_label(mod, tab_id: str, rec, names: Dict[str, str]) -> str:
    """``"Brigands (brigands)"`` — the toolkit's naming rule for one record."""
    if tab_id == "names":
        shown = (getattr(mod, "faction_names", {}) or {}).get(rec.name.lower(), "")
        return f"{shown} ({rec.name})" if shown and shown != rec.name else rec.name
    tag = loc_tag(tab_id, rec)
    return label(rec.name, names, tag) if tag else rec.name


# ---------------------------------------------------------------------------
# what the module's list shows and what its pane shows


def _row(mod, tab_id: str, rec, parsed: LineFile, names: Dict[str, str],
         counted: Dict[str, int]) -> Dict:
    """One row of a tab's list — light enough to paint 200 factions of names."""
    row: Dict = {"name": rec.name, "label": record_label(mod, tab_id, rec, names),
                 "line": rec.start + 1, "findings": counted.get(rec.name, 0)}
    if tab_id == "rebels":
        row.update(category=rec.get("category"), chance=rec.get("chance"),
                   units=len(rec.repeats))
    elif tab_id == "resources":
        row.update(trade_value=rec.get("trade_value"), icon=rec.get("icon"),
                   has_mine=rec.flag("has_mine"),
                   known=rec.name in KNOWN_RESOURCES)
    elif tab_id == "religions":
        row.update(pip_path=rec.pip_path, listed=rec.name in parsed.listed_lines)
    elif tab_id == "cultures":
        row.update(levels=len(rec.levels), agents=len(rec.agents),
                   portrait_mapping=rec.get("portrait_mapping"))
    else:
        row.update(sections={s.name: len(s.entries) for s in rec.sections},
                   total=sum(len(s.entries) for s in rec.sections))
    return row


def overview(mod, tab_id: str) -> Dict:
    """One tab's whole list, plus what the module needs to draw around it."""
    meta = tab(tab_id)
    path = path_for(mod, tab_id)
    out: Dict = {"mod": getattr(mod, "name", ""), "tab": tab_id, "label": meta.label,
                 "file": meta.rel, "noun": meta.noun, "exists": path.is_file(),
                 "records": [], "findings": 0, "count": 0,
                 "actions": list(ACTIONS.get(tab_id, ("edit",))),
                 "refused": REFUSED.get(tab_id, ""),
                 "tabs": [{"id": t.id, "label": t.label, "rel": t.rel} for t in TABS]}
    if not path.is_file():
        out["error"] = f"{getattr(mod, 'name', '?')} has no {meta.rel}"
        return out
    parsed, _ = read_any(mod, tab_id)
    names = loc_names(mod, tab_id)
    found = check_any(mod, tab_id, parsed)
    counted: Dict[str, int] = {}
    for finding in found:
        counted[finding["name"]] = counted.get(finding["name"], 0) + 1
    out["records"] = [_row(mod, tab_id, r, parsed, names, counted)
                      for r in parsed.items]
    out["count"] = len(parsed.items)
    out["findings"] = len(found)
    out["finding_list"] = [{"name": f.get("name", ""), "kind": f.get("kind", ""),
                            "message": f.get("message", "")} for f in found]
    out["loc"] = bool(names)
    out["warnings"] = parsed.warnings[:20]
    if tab_id == "religions":
        # the list the engine actually reads, beside the blocks that give pips
        out["listed"] = list(parsed.listed)
        lookup_path = Path(mod.data) / RELIGIONS_LOOKUP_REL
        out["lookup"] = (parse_lookup(kb.read_text(lookup_path, ENCODING))
                         if lookup_path.is_file() else [])
        out["lookup_file"] = RELIGIONS_LOOKUP_REL
    return out


def vocab(mod, tab_id: str, parsed: LineFile) -> Dict:
    """What this tab's pickers offer — always the mod's own values, never a list.

    A rebel faction's ``unit`` lines are the reason this exists: they name EDU
    types with spaces in them, and typing one by hand is how a rebel faction
    stops spawning. So the picker offers this mod's units under their in-game
    names, resolved the way every other unit picker in the toolkit resolves them.
    """
    out: Dict = {}
    if tab_id == "rebels":
        out["categories"] = list(REBEL_CATEGORIES)
        units = []
        try:
            for u in mod.edu.units:
                entry = mod.loc.get(u.dictionary)
                shown = (entry.name.strip() if entry and entry.name else "")
                units.append({"type": u.type,
                              "label": f"{shown} ({u.type})" if shown else u.type})
        except (OSError, AttributeError, ValueError):
            units = []
        out["units"] = units
    elif tab_id == "resources":
        out["known"] = list(KNOWN_RESOURCES)
    elif tab_id == "religions":
        out["listed"] = list(getattr(parsed, "listed", []))
    elif tab_id == "cultures":
        out["levels"] = list(CULTURE_LEVELS)
        out["agents"] = list(CULTURE_AGENTS)
        out["tail"] = list(CULTURE_TAIL)
        out["head"] = list(CULTURE_HEAD)
    else:
        out["sections"] = list(NAME_SECTIONS)
    return out


def detail(mod, tab_id: str, name: str) -> Dict:
    """One record, everything the module's pane draws."""
    meta = tab(tab_id)
    parsed, _ = read_any(mod, tab_id)
    rec = parsed.get(name)
    if rec is None:
        raise KeyError(f"no {meta.noun} {name!r} in {meta.rel}")
    block = parsed.block_text(rec)
    names = loc_names(mod, tab_id)
    tag = loc_tag(tab_id, rec)
    rel, writable = LOC_FILES.get(tab_id, ("", False))
    fields = (record_fields(shape_of(tab_id), block)
              if tab_id in ("rebels", "resources") else
              religion_fields(block) if tab_id == "religions" else
              culture_fields(block) if tab_id == "cultures" else names_fields(block))
    spans = (record_spans(shape_of(tab_id), block)
             if tab_id in ("rebels", "resources") else
             religion_spans(block) if tab_id == "religions" else
             culture_spans(block) if tab_id == "cultures" else names_spans(block))
    out: Dict = {
        "mod": getattr(mod, "name", ""), "tab": tab_id, "file": meta.rel,
        "noun": meta.noun, "name": rec.name,
        "label": record_label(mod, tab_id, rec, names),
        "record": rec.as_dict(shape_of(tab_id)) if tab_id in ("rebels", "resources")
                  else rec.as_dict(),
        "text": block, "fields": [list(f) for f in fields], "spans": spans,
        "findings": [f for f in check_any(mod, tab_id, parsed) if f["name"] == name],
        "loc_tag": tag, "loc_file": rel, "loc_writable": writable,
        "loc": {tag: names.get(tag, "")} if tag else {},
        "missing_loc": [tag] if tag and names and tag not in names else [],
        "has_loc": bool(names),
        "known": [r.name for r in parsed.items],
        "actions": list(ACTIONS.get(tab_id, ("edit",))),
        "vocab": vocab(mod, tab_id, parsed),
    }
    if tab_id == "resources":
        out["loc_note"] = ("This name lives in text/strat.txt, whose compiled "
                           "archive holds 1307 bare strings read by position, not "
                           "by tag — so it is the Strings module that edits it "
                           "safely, not this one.")
    if tab_id == "religions":
        out["listed"] = rec.name in parsed.listed_lines
    return out


# ---------------------------------------------------------------------------
# plan -> apply
#
# The ancillaries editor's save with one difference: a record here can live in
# more than one file at once. Adding a religion writes its block, joins it to the
# `religions { … }` list, appends it to descr_religions_lookup.txt and creates its
# name in text/religions.txt — four writes that are worthless one at a time, so
# they are one job with one backup set and one undo.


@dataclass
class MinorPlan:
    mod: object = None
    tab: str = "rebels"
    action: str = "edit"                 # 'edit' | 'add' | 'delete'
    name: str = ""
    changes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    findings: List[Dict] = field(default_factory=list)
    #: the tab's own file as it would be written — empty when nothing would change
    text: str = ""
    block: str = ""
    #: the OTHER campaign files this save rewrites: relative path -> whole text
    extra: Dict[str, str] = field(default_factory=dict)
    #: ``{tag: text}`` this save would write into the tab's localisation file
    loc_writes: Dict[str, str] = field(default_factory=dict)
    loc_new: List[str] = field(default_factory=list)
    loc_rel: str = ""

    def summary(self) -> str:
        head = (f"{self.action} {tab(self.tab).noun} {self.name} in "
                f"{getattr(self.mod, 'name', '?')} ({len(self.changes)} change(s))")
        return "\n".join([head] + [f"  {c}" for c in self.changes])

    def touched(self) -> bool:
        return bool(self.text or self.extra or self.loc_writes)

    def payload(self) -> Dict:
        return {"tab": self.tab, "action": self.action, "name": self.name,
                "changes": list(self.changes), "warnings": list(self.warnings),
                "errors": list(self.errors), "findings": list(self.findings),
                "block": self.block, "files": sorted(self.extra),
                "loc_writes": dict(self.loc_writes), "loc_new": list(self.loc_new),
                "loc_file": self.loc_rel,
                "ok": not self.errors and self.touched()}


def plan(mod, body: dict) -> MinorPlan:
    """Work out every file one save would write, without touching the disk.

    ``body`` is ``{mod, tab, name, action, edits, raw_block, loc, write_loc}`` —
    the ancillaries request shape with ``tab`` added, because five files behind
    one module is exactly one more thing than that editor had to say.
    """
    p = MinorPlan(mod=mod, tab=str(body.get("tab") or "rebels"),
                  action=str(body.get("action") or "edit"),
                  name=str(body.get("name") or "").strip())
    try:
        meta = tab(p.tab)
    except KeyError as e:
        p.errors.append(str(e))
        return p
    if p.action not in ACTIONS.get(p.tab, ()):
        p.errors.append(REFUSED.get(p.tab)
                        or f"a {meta.noun} cannot be {p.action}ed here")
        return p
    path = path_for(mod, p.tab)
    if not path.is_file():
        p.errors.append(f"{getattr(mod, 'name', '?')} has no {meta.rel}")
        return p
    original = kb.read_text(path, ENCODING)
    try:
        text = _plan_record(p, original, body)
    except MinorError as e:
        p.errors.append(e.message)
        return p
    if p.errors:
        return p

    if p.tab == "religions" and p.action in ("add", "delete"):
        _plan_lookup(p, mod)

    parsed = parse_any(p.tab, text)
    rec = parsed.get(p.name)
    if rec is not None:
        p.block = parsed.block_text(rec)
        p.findings = [f for f in check_any(mod, p.tab, parsed) if f["name"] == p.name]
        if body.get("write_loc", True):
            _plan_loc(p, mod, rec, dict(body.get("loc") or {}))
    p.text = "" if text == original else text
    _drop_settled(p)
    if not p.touched() and not p.errors:
        p.warnings.append("nothing to change")
    return p


def _drop_settled(p: MinorPlan) -> None:
    """Take out the findings this very save is about to fix.

    The checks read the *file* the save would write and the *companion files* as
    they still are on disk, so a new religion always came back "not in
    descr_religions_lookup.txt" and "no name in text/religions.txt" — in the same
    preview whose change list says it is writing both. A warning about the thing
    you are already doing is a warning nobody can act on.
    """
    fixed = set()
    if RELIGIONS_LOOKUP_REL in p.extra:
        fixed.add("missing-from-lookup")
    if p.loc_writes:
        fixed.add("missing-name")
    if fixed:
        p.findings = [f for f in p.findings
                      if f["kind"] not in fixed or f["name"] != p.name]


def _plan_record(p: MinorPlan, text: str, body: dict) -> str:
    """The tab's own file with this one record added, edited or removed."""
    parsed = parse_any(p.tab, text)
    noun = tab(p.tab).noun

    if p.action == "add":
        if not p.name:
            raise MinorError(f"a new {noun} needs a name")
        if parsed.get(p.name) is not None:
            p.errors.append(f"{p.name} is already a {noun} in this file")
            return text
        block = str(body.get("raw_block") or "").strip("\r\n") or new_any(
            p.tab, dict(body.get("edits") or {}, name=p.name))
        if parse_block_any(p.tab, block + "\n").name != p.name:
            raise MinorError(f"this text does not define `{p.name}`")
        p.changes.append(f"+ {noun} {p.name}")
        if p.tab == "religions":
            p.changes.append(f"+ `{p.name}` in the `religions` list")
            return edit_religions_file(text, add=p.name, block=block)
        body_lines = [ln[:-1] if ln.endswith("\r") else ln for ln in block.split("\n")]
        lines = list(parsed.lines)
        at = parsed.items[-1].end if parsed.items else len(lines)
        lines[at:at] = [""] + body_lines
        return parsed._rebuilt(lines)

    rec = parsed.get(p.name)
    if rec is None:
        p.errors.append(f"{p.name} is not a {noun} in this file")
        return text

    if p.action == "delete":
        p.changes.append(f"- {noun} {p.name}")
        if p.tab == "religions":
            p.changes.append(f"- `{p.name}` from the `religions` list")
            return edit_religions_file(text, remove=p.name)
        lines = list(parsed.lines)
        del lines[rec.start:rec.end]
        return parsed._rebuilt(lines)

    base = parsed.block_text(rec)
    raw = body.get("raw_block")
    if raw is not None and str(raw).strip():
        block = str(raw).strip("\r\n")
        if parse_block_any(p.tab, block + "\n").name != p.name:
            raise MinorError(
                f"this {noun} is `{p.name}` — renaming it here would orphan every "
                "campaign file that names it")
    else:
        block = render_any(p.tab, base, dict(body.get("edits") or {}))
    if block == base:
        return text
    p.changes.extend(kb.diff(base, block))
    return parsed.replace(rec.start, rec.end, block)


def _plan_lookup(p: MinorPlan, mod) -> None:
    """Keep ``descr_religions_lookup.txt`` in step with a religion coming or going.

    The third of the three places a religion is written down. A mod that has not
    got the file at all is left alone rather than given one: two of the three
    installed mods carry stale entries in theirs and still run, so inventing one
    would be guessing at a file the mod has chosen to do without.
    """
    path = Path(getattr(mod, "data", "")) / RELIGIONS_LOOKUP_REL
    if not path.is_file():
        p.warnings.append(f"this mod has no {RELIGIONS_LOOKUP_REL}, so there was "
                          "nothing to keep in step with it")
        return
    before = kb.read_text(path, ENCODING)
    after = edit_lookup(before, add=p.name if p.action == "add" else "",
                        remove=p.name if p.action == "delete" else "")
    if after == before:
        return
    p.extra[RELIGIONS_LOOKUP_REL] = after
    p.changes.append(("+ " if p.action == "add" else "- ")
                     + f"`{p.name}` in {RELIGIONS_LOOKUP_REL}")


def _plan_loc(p: MinorPlan, mod, rec, wanted: Dict) -> None:
    """What this save would write into the tab's ``data/text`` file.

    Only for the two tabs whose file the toolkit may write — see
    :data:`LOC_FILES` on why ``text/strat.txt`` is not one of them.
    """
    from . import stringsbin
    rel, writable = LOC_FILES.get(p.tab, ("", False))
    tag = loc_tag(p.tab, rec)
    if not rel or not tag:
        return
    p.loc_rel = rel
    if not writable:
        if wanted.get(tag):
            p.warnings.append(f"{rel} is read by position, not by tag — change this "
                              "name in the Strings module, which can do it safely")
        return
    have = loc_names(mod, p.tab)
    txt = Path(mod.data) / rel
    if not txt.exists() and not stringsbin.bin_path_for(txt).exists():
        p.warnings.append(f"this mod has no {Path(rel).name}, so this {tab(p.tab).noun}"
                          "'s name could not be written — it will show its tag in game")
        return
    want = str(wanted.get(tag, "")).strip() if wanted else ""
    if tag not in have:
        p.loc_writes[tag] = want or tag
        p.loc_new.append(tag)
        p.changes.append(f"+ a new text key in {Path(rel).name}")
    elif want and want != have[tag]:
        p.loc_writes[tag] = want
        p.changes.append(f"~ the name in {Path(rel).name}")


def apply(p: MinorPlan) -> Dict:
    """Write a planned save, with the same backups and undo as any other job."""
    import shutil
    import time

    from . import cleaner, config, stringsbin
    from .logutil import file_op, log

    if p.errors:
        raise ValueError("cannot apply: " + "; ".join(p.errors))
    if not p.touched():
        raise ValueError("nothing to change")
    mod = p.mod
    meta = tab(p.tab)
    tid = config.new_transfer_id()
    backup_root = config.backup_root_for(tid)
    manifest: Dict[str, List[str]] = {"backed_up": [], "created": []}
    out: Dict = {"id": tid, "tab": p.tab, "name": p.name}

    def keep(rel: str) -> Path:
        """Back a file up into this job's folder and hand back where it lives."""
        target = Path(mod.data) / rel
        bpath = backup_root / "data" / rel
        bpath.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            shutil.copy2(target, bpath)
            manifest["backed_up"].append(rel)
            file_op("BACKUP", target, f"-> {bpath}")
        else:
            manifest["created"].append(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    if p.text:
        target = keep(meta.rel)
        kb.write_text(target, p.text, ENCODING)
        file_op("WRITE", target, f"{len(p.text)} bytes")
    for rel, text in sorted(p.extra.items()):
        target = keep(rel)
        kb.write_text(target, text, ENCODING)
        file_op("WRITE", target, f"{len(text)} bytes")
    if p.loc_writes and p.loc_rel:
        txt = Path(mod.data) / p.loc_rel
        if txt.exists():
            target = keep(p.loc_rel)
            # the compiled cache is rewritten below, so it is backed up too — an
            # undo that put the .txt back and left the .bin would leave the game
            # still reading the new text
            keep(p.loc_rel + ".strings.bin")
            kb.write_text(target,
                          stringsbin.upsert_txt(kb.read_text(target, "utf-16"),
                                                p.loc_writes),
                          "utf-16")
            file_op("WRITE", target, f"{len(p.loc_writes)} text key(s)")
            res = cleaner.refresh_strings_bin(mod.root,
                                              "data/" + p.loc_rel + ".strings.bin")
            out["loc"] = {"file": p.loc_rel, "written": len(p.loc_writes),
                          "new": len(p.loc_new), "strings_bin": res}
        else:
            rel = p.loc_rel + ".strings.bin"
            target = keep(rel)
            sb = stringsbin.read(target)
            for tag, value in p.loc_writes.items():
                sb.set(tag, value)
            stringsbin.write(target, sb)
            file_op("WRITE", target, f"{len(p.loc_writes)} text key(s)")
            out["loc"] = {"file": rel, "written": len(p.loc_writes),
                          "new": len(p.loc_new), "compiled": True}

    rec = {
        "id": tid,
        "when": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "minorfiles",
        "action": p.action,
        "source": mod.name, "source_root": str(mod.root),
        "dest": mod.name, "dest_root": str(mod.root),
        "unit_type": p.name, "resolved_type": p.name,
        "options": {"tab": p.tab}, "applied": True, "undone": False, "note": "",
        "summary": p.summary(), "warnings": list(p.warnings),
        "manifest": manifest, "backup_root": str(backup_root),
    }
    config.append_log(rec)
    log.info("MINOR  %s %s %s in %s — %d change(s), id=%s",
             p.action, p.tab, p.name, mod.name, len(p.changes), tid)
    out["record"] = rec
    return out
