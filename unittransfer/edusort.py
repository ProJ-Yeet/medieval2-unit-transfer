"""Whole-file cleanup of ``data/export_descr_unit.txt``.

The EDU is one block per unit and nothing tells the engine what order they come
in, so a file worked on for years ends up with units wherever there was room.
Divide and Conquer's is the counter-example, and its shape is deliberate:
generals first, then one contiguous run per faction sub-sectioned by banner
comments reading ``;--- GONDOR TIER 1 INFANTRY ---``, then the sections that
belong to no faction — rebels, mercenaries, siege, ships.

This module puts any mod's EDU into that shape. Three rules run through it:

* **It splices, it never re-emits.** A unit's block is moved as the verbatim
  lines it already was. The only bytes this module authors are the section
  banners; everything else is carried, so a comment nobody has a rule for
  survives whatever happens around it.
* **It prefers the order already in the file.** The grouping is a *stable* sort
  on ``(section, tier, category)``, so units that already agree about where they
  belong keep the order they are in, and a file already in shape comes back
  byte for byte. That is also what makes a second run a no-op.
* **A tier is read before it is asked for.** The tier a unit sorts by is the
  tool's own metadata (:data:`unittransfer.edu.MARKER`) and no game file has it
  — but a mod that has organised its EDU by hand has already *written* it, in
  the banners. 907 of DaC's 916 units sit under one. So :func:`harvest_tiers`
  reads the file's own banners rather than asking anyone to type 916 numbers,
  which is the same rule the rest of the toolkit follows for vocabularies: what
  the mod's file declares is read from the file that declares it.

The preamble — everything above the first unit, which in DaC is a hand-written
table of contents — is never touched. It names factions in words this module
cannot re-derive, and rewriting it would mean guessing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from . import edu as edu_mod

REL = "export_descr_unit.txt"
ENCODING = edu_mod.ENCODING

#: A section banner: ``;---- GONDOR TIER 1 INFANTRY ----``. 319 of DaC's 320
#: banners match this, which is what makes it safe both to read tiers out of and
#: to recognise as the tool's own furniture on write. The faction name is not
#: captured for sorting — a unit's own ``ownership`` says which faction it is
#: in, and the banner text is display.
#: The sub-group words a banner may end on. Reading is lenient because real
#: files are spelt by hand — DaC writes ``CALVARY`` 8 times and ``HORSE ARCHER``
#: once — while writing is always the canonical spelling. A banner ending on a
#: word that is NOT in this list is not ours: it is left alone and carried
#: through as an ordinary comment rather than consumed and rewritten.
CAT_WORDS = ("INFANTRY", "ARCHERS", "ARCHER", "HORSE ARCHERS", "HORSE ARCHER",
             "CAVALRY", "CALVARY", "GENERALS", "GENERAL", "OTHER")

#: The characters a banner's rule may be drawn with. The reader accepts every
#: one of them because the WRITER can now be told to use any of them
#: (:data:`BANNER_STYLE`), and a banner this tool writes but cannot read back is
#: worse than no banner at all: the next run would carry it as an ordinary
#: comment AND write a fresh one, so a file would gain a banner on every pass.
#: Broadening it also picks up the `;====== GONDOR INFANTRY ======` a mod wrote
#: by hand, which is our furniture by any reasonable reading — and the trailing
#: :data:`CAT_WORDS` still has to match, so an ordinary rule of equals signs
#: over a paragraph of notes is not mistaken for one.
BANNER_FILL = "-=*~#_+."

BANNER_RE = re.compile(
    r"^\s*;[;" + re.escape(BANNER_FILL) + r"]{2,}\s*(?P<name>.*?)"
    r"\s*(?:TIER\s+(?P<tier>\d+)\s+)?"
    r"(?P<cat>" + "|".join(sorted(CAT_WORDS, key=len, reverse=True)) + r")"
    r"\s*[" + re.escape(BANNER_FILL) + r"]{2,}\s*$", re.IGNORECASE)

#: How wide a banner is, counted honestly: the line :func:`banner` returns is
#: exactly this many characters. It reads 95 rather than a round 96 because 95
#: is what this module has always written, and the default has to stay byte for
#: byte what it was or a file already cleaned up would show a change on a run
#: that was asked to change nothing.
BANNER_WIDTH = 95

#: Sub-groups within a faction, in the order DaC writes them. The key is what
#: :meth:`unittransfer.edu.Unit.kind` returns; the value is the banner word.
#: ``CALVARY`` appears 8 times in DaC and ``HORSE ARCHER`` once — real files are
#: spelt by hand, so reading is lenient (see :data:`BANNER_RE`) while writing is
#: consistent.
CATEGORIES: Tuple[Tuple[str, ...], ...] = (
    ("INFANTRY", "Infantry", "Infantry_Javelin"),
    ("ARCHERS", "Infantry_Archer"),
    ("CAVALRY", "Cavalry", "Cavalry_Lance", "Cavalry_Javelin"),
    ("HORSE ARCHERS", "Cavalry_Archer"),
)
_CAT_RANK: Dict[str, int] = {k: i for i, g in enumerate(CATEGORIES) for k in g[1:]}
_CAT_NAME: Dict[int, str] = {i: g[0] for i, g in enumerate(CATEGORIES)}

#: Sections that are not one faction's roster, in the order DaC's own table of
#: contents lists them — after every faction, never before.
REBELS, MERCS, SIEGE, SHIPS = "rebels", "mercs", "siege", "ships"
TAIL: Tuple[str, ...] = (REBELS, MERCS, SIEGE, SHIPS)

SECTION_TITLES = {
    REBELS: "REBELS", MERCS: "MERCENARIES",
    SIEGE: "SIEGE UNITS", SHIPS: "SHIPS",
}

#: A general leads its faction's run, so it sorts in front of tier 0 — and a
#: unit somebody placed by hand leads even that, because it is the one position
#: in the file a person actually chose.
GENERAL_TIER = -1
HAND_TIER = -2

#: What ``special=`` on a unit's marker may say, and where it sorts.
#:
#: The sorter DETECTS a general from ``attributes``, and that is right for the
#: 31 units in Divide and Conquer that carry ``general_unit``. It is silent
#: about everything else a mod treats as out of the ordinary: a bodyguard that
#: is not flagged as a general, a hero, a one-off quest unit. Those units are
#: exactly the ones a hand-organised EDU keeps at the head of a faction's run,
#: and the sorter used to bury them among the tier 1 spearmen.
#:
#: So the classification is editable, per unit, from the ordering screen — with
#: whatever was detected filled in, so agreeing with the tool costs nothing.
#: ``none`` is a real value and not a blank: it means "I looked, and this unit
#: is ordinary", which is how you overrule a detection you disagree with.
SPECIAL_RANK: Dict[str, int] = {
    "general": -1,
    "bodyguard": -1,
    "hero": 0,
    "unique": 0,
    "quest": 0,
}
SPECIAL_VALUES: Tuple[str, ...] = ("general", "bodyguard", "hero", "unique",
                                   "quest", "none")

#: A unit with no tier sorts after the tiered ones in its category rather than
#: in front of them: an untiered unit is one nobody has classified yet, and
#: burying the classified ones under it would undo the work.
UNTIERED = 99


# ---------------------------------------------------------------------------
# reading tiers out of the file's own banners


def harvest(text: str) -> Dict[str, Tuple[str, str]]:
    """``{unit type: (group, tier)}`` read from the banner each unit sits under.

    A banner applies to every unit below it until the next one. It carries both
    halves of where a unit belongs, and both are worth more than anything this
    module could derive:

    * the **tier**, which exists in no game file at all;
    * the **group** — the author's own word for the section, like ``GONDOR`` or
      ``NORTHERN DUNEDAIN``. It is deliberately kept as *text* and never
      resolved to a faction slot. Measured, only 146 of DaC's 916 banner names
      match a localised faction name, because a modder writes ``CRAG`` and
      ``DORWINION`` rather than whatever ``descr_sm_factions.txt`` calls them —
      and a unit's own ``ownership`` cannot stand in either, since most units
      list a dozen factions and the line is a set, not a ranking.

    So the file's own sectioning is authoritative wherever it exists, and this
    module only invents a section where there is none.
    """
    out: Dict[str, Tuple[str, str]] = {}
    group, tier = "", ""
    for line in text.splitlines():
        m = BANNER_RE.match(line)
        if m:
            group = m.group("name").strip().upper()
            tier = str(int(m.group("tier"))) if m.group("tier") else ""
            continue
        if edu_mod.line_key(line) == "type":
            # through the parser's own splitter: a `type` line can carry a
            # trailing comment, and 17 of DaC's do.
            vals = edu_mod._split_fields(line)[1]
            name = vals[0] if vals else ""
            if group and name and name not in out:
                out[name] = (group, tier)
    return out


def harvest_tiers(text: str) -> Dict[str, str]:
    """``{unit type: tier}`` — the tier half of :func:`harvest`."""
    return {t: tier for t, (_, tier) in harvest(text).items() if tier}


def apply_tiers(text: str, tiers: Dict[str, str]) -> str:
    """Write ``{unit type: tier}`` onto each unit's marker line."""
    if not tiers:
        return text
    f = edu_mod.parse_text(text)
    out = [f.preamble]
    for u in f.units:
        want = tiers.get(u.type, "")
        out.append(edu_mod.set_marker(u.raw, tier=want) if want else u.raw)
    return "".join(out)


# ---------------------------------------------------------------------------
# which section a unit belongs to


def section_of(u: edu_mod.Unit) -> Tuple[str, str]:
    """``(section, faction slot)`` for one unit — the slot is ``""`` off-roster.

    **Faction first, kind second**, and that is a measurement rather than a
    preference. The obvious reading of DaC's table of contents — a global
    GENERALS block at the top and MERCENARIES, SIEGE and SHIPS blocks at the
    bottom — is not how the file is actually laid out: all 31 of its generals
    sit at the head of their own faction's run, and its 127 mercenaries are
    spread from unit 11 to unit 891 because most of them are somebody's
    area-of-recruitment troops. Hoisting either into a section of its own moves
    ~140 units their author deliberately placed.

    So a unit that any faction can field belongs to that faction, and only the
    handful nobody owns — 13 units in DaC, 3 in Third Age Reforged — fall
    through to the shared sections at the end. Generals still come first, but
    first *within their faction* (see :func:`tier_rank`).
    """
    owners = [o for o in u.ownership if o.lower() != "slave"]
    if owners:
        return "faction", owners[0].lower()
    cat = (u.category or "").lower()
    if cat == "ship":
        return SHIPS, ""
    if cat == "siege":
        return SIEGE, ""
    if "mercenary_unit" in set(u.attributes):
        return MERCS, ""
    return REBELS, ""


def detected_special(u: edu_mod.Unit) -> str:
    """What the unit's own lines say it is, before anyone edits the marker.

    Only ``general`` is derivable: ``general_unit`` is a real EDU attribute the
    engine reads. Everything else in :data:`SPECIAL_VALUES` is a judgement about
    a roster that no game file records, which is why it is offered rather than
    guessed.
    """
    if {"general_unit", "general_unit_upgrade"} & set(u.attributes):
        return "general"
    return ""


def special_of(u: edu_mod.Unit) -> str:
    """The unit's classification: its marker if it has one, else what was detected."""
    want = (u.special or "").strip().lower()
    if want in SPECIAL_VALUES:
        return want
    return detected_special(u)


def is_general(u: edu_mod.Unit) -> bool:
    return special_of(u) in ("general", "bodyguard")


def category_rank(u: edu_mod.Unit) -> int:
    """Which sub-group of its faction a unit sits in (see :data:`CATEGORIES`)."""
    return _CAT_RANK.get(u.kind(), len(CATEGORIES))


def tier_rank(u: edu_mod.Unit) -> int:
    """Which tier band a unit sorts in.

    Generals lead their faction's run; anything else marked special follows them
    and still comes in front of tier 1. A unit marked ``none`` sorts on its tier
    alone, whatever its attributes say.
    """
    rank = SPECIAL_RANK.get(special_of(u))
    if rank is not None:
        return rank
    return int(u.tier) if u.tier.isdigit() else UNTIERED


# ---------------------------------------------------------------------------
# the blocks


@dataclass
class Block:
    """One unit's lines, split into what moves and what separates."""
    unit: edu_mod.Unit
    body: str                 # the unit's own lines — marker, type, fields, notes
    kept: List[str]           # trailing comment lines that are not our banners
    index: int                # where it was, which is the tie-break for a stable sort
    section: str = ""
    slot: str = ""
    group: str = ""           # the section it is in, in the author's own words
    owners: List[str] = field(default_factory=list)   # every faction that can field it

    @property
    def type(self) -> str:
        return self.unit.type


def _split_blocks(f: edu_mod.EduFile, groups: Dict[str, Tuple[str, str]],
                  names: Dict[str, str]) -> List[Block]:
    """Each unit as body + the trailing filler worth keeping, in its section.

    A recognised banner is dropped here and regenerated on write: it is the
    tool's own furniture, and carrying a stale one alongside a fresh one is how
    a file ends up with two. Every other comment line is kept and stays with the
    unit it followed — this module deletes nobody's writing.
    """
    out: List[Block] = []
    for i, u in enumerate(f.main_units):
        body = edu_mod.strip_trailing_filler(u.raw)
        kept = [l for l in edu_mod.trailing_filler(u.raw).splitlines()
                if l.strip() and not BANNER_RE.match(l)]
        sec, slot = section_of(u)
        out.append(Block(unit=u, body=body, kept=kept, index=i, section=sec,
                         slot=slot, group=groups.get(u.type, ("", ""))[0],
                         owners=[o.lower() for o in u.ownership if o.lower() != "slave"]))
    _name_the_rest(out, names)
    return out


def _name_the_rest(blocks: List[Block], names: Dict[str, str]) -> None:
    """Give a section to every unit no banner covered.

    A faction whose roster sits under banners usually has a few units that do
    not — DaC's bodyguards live above the first banner in the file. Calling
    those by the localised faction name would file them apart from their own
    faction, because the author's banner word is rarely the localised name
    (``MORIA`` against ``GOBLINS OF MORIA``). So a faction that already has a
    banner word lends it to its own strays, and only a faction with no banner
    anywhere falls back to what the game calls it.
    """
    import collections

    votes: Dict[str, collections.Counter] = {}
    for b in blocks:
        if b.section == "faction" and b.group:
            votes.setdefault(b.slot, collections.Counter())[b.group] += 1
    for b in blocks:
        if b.group:
            continue
        if b.section != "faction":
            b.group = SECTION_TITLES[b.section]
        elif b.slot in votes:
            b.group = votes[b.slot].most_common(1)[0][0]
        else:
            b.group = (names.get(b.slot) or b.slot).upper()


# ---------------------------------------------------------------------------
# the order


def _moved(ordered: List[Block]) -> List[str]:
    """Which units genuinely had to move, not which ones changed index.

    One unit sent from the top of the file to the bottom shifts the index of
    every unit behind it, so counting ``index != position`` reports almost the
    whole roster and tells the user nothing. The units that stayed put are the
    longest run still in their original relative order; everything else is what
    moved. That is the smallest honest answer, and it is the number "prefer the
    order already in the file" has to be judged on.
    """
    import bisect

    tails: List[int] = []          # tails[k] = smallest end of a run of length k+1
    where: List[int] = []          # for each block, the run length it ends
    for b in ordered:
        k = bisect.bisect_left(tails, b.index)
        if k == len(tails):
            tails.append(b.index)
        else:
            tails[k] = b.index
        where.append(k)
    stayed, want = set(), len(tails) - 1
    for i in range(len(ordered) - 1, -1, -1):
        if where[i] == want:
            stayed.add(i)
            want -= 1
    return [b.type for i, b in enumerate(ordered) if i not in stayed]


def group_order(blocks: List[Block]) -> List[str]:
    """Which section comes first — taken from the file's own layout.

    ``descr_sm_factions.txt`` also puts the factions in an order, and it is
    tempting to use that. Measured, it is not the same order: DaC's roster file
    opens on ``scripts, sicily, turks, russia, teutonic_order`` while its EDU is
    laid out ``sicily, turks, russia, milan, normans``. Sorting by the wrong one
    moves hundreds of units that were already where their author put them.

    So the order is read from where it is actually expressed — the median
    position of each section's units right now. The median rather than the
    first, so one stray early unit cannot drag a whole section to the top. The
    shared sections at the end keep :data:`TAIL` order.
    """
    import statistics

    seen: Dict[str, List[int]] = {}
    for b in blocks:
        if b.section == "faction":
            seen.setdefault(b.group, []).append(b.index)
    return sorted(seen, key=lambda g: statistics.median(seen[g]))


def _section_rank(order: Sequence[str]) -> Dict[str, int]:
    rank = {g: i for i, g in enumerate(order)}
    for j, name in enumerate(TAIL):
        rank[SECTION_TITLES[name]] = len(order) + j
    return rank


def _key(b: Block, rank: Dict[str, int]):
    #: a section nothing has an opinion about still has to land somewhere;
    #: after everything that does, in a stable order.
    sec = rank.get(b.group, len(rank) + 1)
    if b.unit.order.isdigit():
        return (sec, HAND_TIER, 0, int(b.unit.order), b.index)
    return (sec, tier_rank(b.unit), category_rank(b.unit), 0, b.index)


def order_blocks(blocks: List[Block], order: Sequence[str]) -> List[Block]:
    """The blocks in the order the file should keep them.

    A **stable** sort, which is the whole of "prefer the order already in the
    file": two units with nothing to choose between them stay as they are, so a
    file already in shape is returned untouched and a second run cannot differ
    from the first.

    A unit placed by hand leads its section, in the order it was given — and
    that placement is read from the unit's own marker rather than passed in
    beside it, so every later run honours it too (see :func:`apply_hand`).
    """
    rank = _section_rank(order)
    return sorted(blocks, key=lambda b: _key(b, rank))


def apply_hand(text: str, hand: Optional[Dict[str, List[str]]]) -> str:
    """Record a hand placement on the units it names.

    The sorter is right about most units and wrong about the ones a mod treats
    specially, which is the whole reason the ordering screen exists. A placement
    made there has to OUTLIVE the cleanup that follows it — otherwise the next
    run puts the unit back where its tier said and the screen was a waste of
    everyone's time. So it is written onto the unit the way its tier is, and
    read back the same way. Nothing else in an EDU records position: in this
    file, position IS the record.
    """
    want: Dict[str, str] = {}
    for types in (hand or {}).values():
        for i, t in enumerate(types):
            want[t] = str(i)
    if not want:
        return text
    f = edu_mod.parse_text(text)
    return f.preamble + "".join(
        edu_mod.set_marker(u.raw, order=want[u.type]) if u.type in want else u.raw
        for u in f.main_units)


#: The marker keys the ordering screen may set on a unit.
MARK_KEYS: Tuple[str, ...] = ("tier", "variant", "special")


def apply_marks(text: str, marks: Optional[Dict[str, Dict[str, str]]]) -> Tuple[str, List[str]]:
    """Write ``{unit type: {tier, variant, special}}`` onto the units named.

    The three things the ordering screen edits, written the way every other
    piece of this tool's metadata is: onto the unit's own ``;@m2gt`` line, above
    its ``type``, where the engine skips it and the next run reads it back.

    A key set to ``""`` is REMOVED rather than written blank — that is how you
    take a classification off a unit again — and :func:`unittransfer.edu.set_marker`
    deletes a marker that has nothing left on it, so a unit cleared of all three
    comes out with no marker line at all rather than a bare prefix.

    Returns the new text and which units were actually changed, so the plan can
    say so rather than reporting a silent write.
    """
    want = {k: v for k, v in (marks or {}).items() if v}
    if not want:
        return text, []
    f = edu_mod.parse_text(text)
    out = [f.preamble]
    touched: List[str] = []
    for u in f.units:
        m = want.get(u.type)
        if not m:
            out.append(u.raw)
            continue
        fields = {k: str(m.get(k, "") or "") for k in MARK_KEYS if k in m}
        if not fields:
            out.append(u.raw)
            continue
        raw = edu_mod.set_marker(u.raw, **fields)
        if raw != u.raw:
            touched.append(u.type)
        out.append(raw)
    return "".join(out), touched


# ---------------------------------------------------------------------------
# writing it back


#: How a section banner is drawn. The defaults are what the real files use — a
#: 96-column rule of hyphens with the section name centred in it — and every one
#: of them is a matter of taste rather than of format, so all four are the user's.
#: :data:`BANNER_RE` still has to read the result back, which is the one
#: constraint: the line starts ``;``, the fill repeats at least twice, and the
#: title sits between the two runs. Anything a mod already writes by hand is
#: therefore still recognised, and a banner this tool writes is still a banner
#: the next run will read.
#: ``upper`` is OFF by default so the default output is byte for byte what this
#: module wrote before the style existed. A section name comes out of the file's
#: own banners, so forcing case would rewrite the author's spelling on a run
#: nobody asked to change anything.
BANNER_STYLE = {"width": BANNER_WIDTH, "fill": "-", "prefix": ";", "upper": False}


def banner_style(style: Optional[Dict] = None) -> Dict:
    """A complete style, with anything the caller left out filled in.

    A fill that is not a single safe character falls back to a hyphen rather
    than being rejected: this is a display choice arriving from a text box, and
    a bad one must not be able to stop a cleanup.
    """
    out = dict(BANNER_STYLE)
    for k, v in (style or {}).items():
        if k in out and v is not None:
            out[k] = v
    try:
        out["width"] = max(20, min(200, int(out["width"])))
    except (TypeError, ValueError):
        out["width"] = BANNER_WIDTH
    fill = str(out["fill"] or "-")[:1]
    out["fill"] = fill if fill in BANNER_FILL else "-"
    prefix = str(out["prefix"] or ";")
    out["prefix"] = (prefix if prefix[:1] == ";" and set(prefix) <= set(";" + BANNER_FILL)
                     else ";")
    out["upper"] = bool(out["upper"])
    return out


def banner(title: str, style: Optional[Dict] = None) -> str:
    """One section banner, in the shape the real files use."""
    s = banner_style(style)
    text = title.upper() if s["upper"] else title
    # the two spaces around the title are part of the width, and so is the prefix
    pad = max(4, s["width"] - len(text) - len(s["prefix"]) - 2)
    left = pad // 2
    return (s["prefix"] + s["fill"] * left + " " + text + " "
            + s["fill"] * (pad - left))


def _title(b: Block) -> str:
    """The banner a block sits under — its section, then its sub-group.

    Written so :data:`BANNER_RE` reads it straight back: the section survives a
    round trip through the file itself, which is what lets the next run see the
    same grouping without any of it being stored anywhere else.
    """
    if is_general(b.unit):
        return f"{b.group} GENERALS"
    cat = _CAT_NAME.get(category_rank(b.unit), "OTHER")
    tier = tier_rank(b.unit)
    # An untiered unit gets a banner with no tier in it, so reading the file
    # back does not hand it a tier nobody chose — that would move it out of the
    # untiered group on the second run and cost the sorter its idempotence.
    return f"{b.group} TIER {tier} {cat}" if tier != UNTIERED else f"{b.group} {cat}"


def render(f: edu_mod.EduFile, blocks: List[Block],
           *, banners: bool = True, tidy: bool = True,
           style: Optional[Dict] = None) -> str:
    """The whole file: its own preamble, then the blocks in the given order."""
    from .codeview import _edu_tidy

    # The first banner of a sorted file sits above the first unit, which makes
    # it part of the PREAMBLE when that file is read back. Re-emitting the
    # preamble whole would then print it a second time, and the file would grow
    # a banner on every run. Ours are dropped here for the same reason they are
    # dropped from a block's filler: they are furniture, and they are rewritten
    # below. Everything else in the preamble — DaC's hand-written table of
    # contents included — is passed through untouched.
    out: List[str] = ["".join(l for l in f.preamble.splitlines(keepends=True)
                              if not BANNER_RE.match(l))]
    last = None
    for b in blocks:
        title = _title(b)
        if banners and title != last:
            out.append(banner(title, style) + "\n")
        last = title
        body = _edu_tidy(b.body, {}) if tidy else b.body
        out.append(body if body.endswith("\n") else body + "\n")
        for line in b.kept:
            out.append(line + "\n")
        out.append("\n")
    return "".join(out)


# ---------------------------------------------------------------------------
# plan / apply


@dataclass
class SortPlan:
    mod: object
    text: str = ""                       # what would be written ("" = nothing to do)
    moved: List[str] = field(default_factory=list)
    changes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    untiered: List[str] = field(default_factory=list)
    read_tiers: List[str] = field(default_factory=list)
    placed: List[str] = field(default_factory=list)
    marked: List[str] = field(default_factory=list)
    sections: List[Tuple[str, int]] = field(default_factory=list)

    def touched(self) -> bool:
        return bool(self.text)

    def summary(self) -> str:
        return "; ".join(self.changes) or "nothing to change"

    def payload(self) -> Dict:
        """What the page is shown — never the whole new file, which is 1.2 MB."""
        return {
            "changes": self.changes, "warnings": self.warnings,
            "errors": self.errors, "summary": self.summary(),
            "moved": self.moved[:200], "moved_count": len(self.moved),
            "untiered": self.untiered[:200], "untiered_count": len(self.untiered),
            "read_tiers": len(self.read_tiers), "placed": len(self.placed),
            "marked": len(self.marked),
            "sections": [{"name": n, "units": c} for n, c in self.sections],
            "touched": self.touched(),
        }


def path_for(mod) -> Path:
    return Path(mod.data) / REL


def overview(mod) -> Dict:
    """Every section and the units in it, in the order a cleanup would leave them.

    What the ordering screen draws. It is the plan's own grouping rather than a
    second opinion about it, so what the user drags is what the sorter would
    write.
    """
    path = path_for(mod)
    if not path.is_file():
        return {"sections": [], "error": f"this mod has no {REL}"}
    text = path.read_text(encoding=ENCODING)
    f = edu_mod.parse_text(text)
    names = {k.lower(): v for k, v in (mod.faction_names or {}).items()}
    blocks = _split_blocks(f, harvest(text), names)
    ordered = order_blocks(blocks, group_order(blocks))
    # the localised name, so the list reads as units rather than as type strings
    names_of: Dict[str, str] = {}
    try:
        loc = mod.loc
    except Exception:
        loc = None
    if loc is not None:
        for u in f.main_units:
            entry = loc.get(u.dictionary or u.type)
            if entry is not None and getattr(entry, "name", ""):
                names_of[u.type] = entry.name

    out: List[Dict] = []
    for b in ordered:
        if not out or out[-1]["name"] != b.group:
            out.append({"name": b.group, "units": []})
        out[-1]["units"].append({
            "type": b.type,
            "name": names_of.get(b.type, ""),
            "tier": b.unit.tier,
            "variant": b.unit.variant,
            # what the marker says, and — separately — what the unit's own lines
            # say. The screen fills the drop-down in from the second when the
            # first is empty, so agreeing with the tool costs no clicks and
            # disagreeing with it is still one.
            "special": b.unit.special,
            "detected_special": detected_special(b.unit),
            "general": is_general(b.unit),
            "category": _CAT_NAME.get(category_rank(b.unit), "OTHER"),
            "kind": b.unit.kind(),
        })
    # What the drop-downs may offer: the standard set first, then whatever this
    # mod's own units have added to it. The same rule as everywhere else in the
    # toolkit — a value a mod uses is a value the mod may be offered — and it
    # matters most on a mod that has never been cleaned up, where the units carry
    # no markers at all and a list built only from them would be empty.
    from .vocab import TIER, TIER_VARIANT

    def _merged(base, seen):
        out = list(base)
        for v in sorted(seen):
            if v and v not in out:
                out.append(v)
        return out

    return {"sections": out,
            "tiers": _merged(TIER, {u.tier for u in f.main_units if u.tier}),
            "variants": _merged(TIER_VARIANT,
                                {u.variant for u in f.main_units if u.variant}),
            "specials": list(SPECIAL_VALUES),
            "banner_style": banner_style(None)}


def plan(mod, *, banners: bool = True, tidy: bool = True, group: bool = True,
         tiers: bool = True, hand: Optional[Dict[str, List[str]]] = None,
         marks: Optional[Dict[str, Dict[str, str]]] = None,
         style: Optional[Dict] = None) -> SortPlan:
    """What a cleanup would do to this mod's EDU, without doing any of it."""
    from . import factions

    p = SortPlan(mod=mod)
    path = path_for(mod)
    if not path.is_file():
        p.errors.append(f"this mod has no {REL}")
        return p

    original = path.read_text(encoding=ENCODING)
    f = edu_mod.parse_text(original)
    if not f.main_units:
        p.errors.append(f"no units found in {REL} — refusing to rewrite it")
        return p

    # The tier a banner already states is written onto the unit's own marker
    # before anything is sorted. It has to be: this pass REWRITES the banners,
    # so a tier that lived only in one would be regenerated from itself. Reading
    # it once and recording it is what breaks the circle — and it is reading the
    # mod's own file, not inventing a value. A unit that already has a marker
    # keeps it; the marker is the answer, the banner is only where it was found.
    found = harvest(original)
    staged = original
    if tiers:
        have = {u.type for u in f.main_units if u.tier}
        read = {t: v for t, (_, v) in found.items() if v and t not in have}
        if read:
            p.read_tiers = sorted(read)
            staged = apply_tiers(staged, read)
    # The tier, variant and classification edited on the ordering screen. They go
    # on BEFORE the sort, because they are what the sort reads: setting a unit's
    # tier and having it move in the same pass is the whole point of editing it
    # there rather than opening the unit editor for one drop-down.
    if marks:
        staged, p.marked = apply_marks(staged, marks)
    if hand:
        staged = apply_hand(staged, hand)
        p.placed = sorted({t for types in hand.values() for t in types})
    if staged is not original:
        f = edu_mod.parse_text(staged)

    names = {k.lower(): v for k, v in (mod.faction_names or {}).items()}
    blocks = _split_blocks(f, found, names)
    ordered = order_blocks(blocks, group_order(blocks)) if group else blocks

    text = render(f, ordered, banners=banners, tidy=tidy, style=style)
    if text == original:
        return p

    p.text = text
    p.moved = _moved(ordered)
    p.untiered = [b.type for b in ordered
                  if b.section == "faction" and tier_rank(b.unit) == UNTIERED]

    seen: List[Tuple[str, int]] = []
    for b in ordered:
        if seen and seen[-1][0] == b.group:
            seen[-1] = (b.group, seen[-1][1] + 1)
        else:
            seen.append((b.group, 1))
    p.sections = seen

    if p.read_tiers:
        p.changes.append(f"+ {len(p.read_tiers)} tier(s) read from the file's own banners")
    if p.marked:
        p.changes.append(f"+ {len(p.marked)} unit(s) given a tier, variant or "
                         "classification from the ordering screen")
    if p.placed:
        p.changes.append(f"+ {len(p.placed)} unit(s) placed by hand, recorded so the "
                         "next cleanup keeps them there")
    if group and p.moved:
        p.changes.append(f"~ {len(p.moved)} unit(s) moved into {len(seen)} section(s)")
    if tidy:
        p.changes.append("~ every unit's values lined up in one column")
    if banners:
        p.changes.append(f"~ {len(seen)} section banner(s) written")
    if p.untiered:
        p.warnings.append(
            f"{len(p.untiered)} unit(s) have no tier yet, so they sort after the "
            "tiered ones in their group — read the file's own banners in to give "
            "them one")
    _verify(p, original, text)
    return p


def _verify(p: SortPlan, before: str, after: str) -> None:
    """Refuse anything that is not purely a reordering.

    Position is the only thing this module is allowed to change, so the check is
    a multiset comparison: the same units, each with the same field lines, and
    no comment line of anybody's lost. It is cheap next to what it prevents —
    silently rewriting a 35 000-line roster.
    """
    import collections

    a, b = edu_mod.parse_text(before), edu_mod.parse_text(after)
    lost = {u.type for u in a.main_units} - {u.type for u in b.main_units}
    gained = {u.type for u in b.main_units} - {u.type for u in a.main_units}
    if lost:
        p.errors.append(f"{len(lost)} unit(s) would be lost: "
                        + ", ".join(sorted(lost)[:5]))
    if gained:
        p.errors.append(f"{len(gained)} unit(s) would appear from nowhere: "
                        + ", ".join(sorted(gained)[:5]))

    fields_a = {u.type: edu_mod.block_fields(u.raw) for u in a.main_units}
    changed = [u.type for u in b.main_units
               if u.type in fields_a and edu_mod.block_fields(u.raw) != fields_a[u.type]]
    if changed:
        p.errors.append(f"{len(changed)} unit(s) would have fields changed: "
                        + ", ".join(sorted(changed)[:5]))

    def comments(text: str) -> collections.Counter:
        return collections.Counter(
            l.strip() for l in text.splitlines()
            if l.strip().startswith(";") and not BANNER_RE.match(l))

    dropped = comments(before) - comments(after)
    if dropped:
        p.errors.append(f"{sum(dropped.values())} comment line(s) would be lost: "
                        + "; ".join(list(dropped)[:3]))


def apply(p: SortPlan) -> Dict:
    """Write a planned cleanup, with the same backup and undo as any other job."""
    import shutil
    import time

    from . import config
    from .logutil import file_op, log

    if p.errors:
        raise ValueError("cannot apply: " + "; ".join(p.errors))
    if not p.touched():
        raise ValueError("nothing to change")

    mod = p.mod
    tid = config.new_transfer_id()
    backup_root = config.backup_root_for(tid)
    manifest: Dict[str, List[str]] = {"backed_up": [], "created": []}

    target = path_for(mod)
    bpath = backup_root / "data" / REL
    bpath.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, bpath)
    manifest["backed_up"].append(REL)
    file_op("BACKUP", target, f"-> {bpath}")

    target.write_text(p.text, encoding=ENCODING)
    file_op("WRITE", target, f"{len(p.text)} bytes")

    rec = {
        "id": tid,
        "when": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "edu",
        "action": "clean up the unit file",
        "source": mod.name, "source_root": str(mod.root),
        "dest": mod.name, "dest_root": str(mod.root),
        "unit_type": "", "resolved_type": "",
        "options": {}, "applied": True, "undone": False, "note": "",
        "summary": p.summary(), "warnings": list(p.warnings),
        "manifest": manifest, "backup_root": str(backup_root),
    }
    config.append_log(rec)
    log.info("EDU cleanup in %s — %d unit(s) moved, id=%s",
             mod.name, len(p.moved), tid)
    return {"id": tid, "moved": len(p.moved), "record": rec}
