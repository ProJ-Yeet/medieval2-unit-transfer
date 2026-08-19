"""The faction roster of ``descr_sm_factions.txt``.

The file that says what a faction *is*: its culture and religion, its two map
colours, the strat models it puts on the campaign map, whether it can sap a wall
or field a princess, and — for the handful that have one — its horde.

**It needed no new parser.** ``descr_sm_factions.txt`` is the fourth file to be a
run of ``<head> <name>`` records with ``keyword value`` lines under it, so it is
a :class:`unittransfer.flatrecord.Shape` and nothing else: all 90 factions in the
three installed mods parse byte-exact and re-render unchanged against
:data:`SHAPE` with no code of its own. What is in this module is what a *faction*
means, which is a different question from how its lines are laid out.

Measured over those 90 factions, and each one shaped something here:

* **The line order is canonical and nobody disagrees.** Thirteen distinct
  orderings appear, but they are thirteen *subsets* of one order — a topological
  sort over all 90 records finds **zero conflicts**. So :data:`ORDER` is derived,
  not guessed, and an inserted line goes to its place in it.
* **Sixteen keys are in 100% of factions and the rest are optional groups** —
  the four movies (63%), the eight horde keys (11%), ``can_build_siege_towers``
  (23%), and three that barely appear at all.
* **``horde_unit`` repeats**, up to 16 times in one faction, exactly as a rebel
  faction's ``unit`` does. It is the shape's ``repeat_kw``.
* **The head line can carry a modifier after a comma**: ``faction egypt,
  spawned_on_event``, and ``shadowing`` / ``shadowed_by`` naming another faction.
  Five real factions do this. The slot is the part before the comma — which is
  what everything else in the mod points at — and :func:`slot_of` is why nothing
  here ever compares a whole head line to a faction name.
* **``has_family_tree`` is not a boolean.** It is ``yes``, ``no`` or
  ``teutonic``, and 24 of the 90 say ``teutonic``. A checkbox would have written
  ``no`` over every one of them.

And two things this module deliberately does **not** do:

**It does not add or delete a faction.** A faction slot lives in eight or nine
files — ``descr_strat.txt``, ``expanded.txt``, the banners, ``descr_names.txt``,
the UI folders, the EDU's ownership lines, every ``requires factions { … }``
clause — and TWCenter has a step-by-step tutorial for it precisely because one
file is never the job. A faction that exists only here is a mod that will not
load, so the module edits and says why it will not create. Same ruling as the
cultures tab in :mod:`unittransfer.minorfiles`, for the same reason.

**It does not claim a missing picture is a fault.** ``symbol`` and
``rebel_symbol`` name ``.CAS`` *3D strat models*, not textures — those belong to
the model viewer, not here. ``loading_logo`` names a ``.tga`` that **none of the
90 real factions ships unpacked**: all 90 live in the game's ``.pack`` archives,
which the toolkit cannot read. So the paths are shown, resolved when they happen
to be on disk, and never marked missing when they are not — the ruling Phase 10a
already made about pips and settlement cards.

What IS visual and IS in this file is the two colours, and those are shown as
what they are: ``primary_colour red 55, green 75, blue 48`` is the colour the
faction paints the campaign map, and it gets a swatch and a picker.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import flatrecord as fr
from . import keyblock as kb
from . import minorfiles

ENCODING = fr.ENCODING

REL = "descr_sm_factions.txt"

#: The canonical line order, derived by topological sort over all 90 real
#: factions — thirteen observed orderings, zero conflicts between them.
ORDER: Tuple[str, ...] = (
    "culture", "religion", "special_faction_type", "symbol", "rebel_symbol",
    "primary_colour", "secondary_colour", "loading_logo", "standard_index",
    "logo_index", "small_logo_index", "triumph_value",
    "intro_movie", "victory_movie", "defeat_movie", "death_movie",
    "custom_battle_availability",
    "horde_min_units", "horde_max_units", "horde_max_units_reduction_every_horde",
    "horde_unit_per_settlement_population", "horde_min_named_characters",
    "horde_max_percent_army_stack", "horde_disband_percent_on_settlement_capture",
    "can_sap", "prefers_naval_invasions", "can_have_princess", "has_family_tree",
    "disband_to_pools", "can_build_siege_towers", "can_transmit_plague")

#: The sixteen keys every one of the 90 real factions has.
REQUIRED: Tuple[str, ...] = (
    "culture", "religion", "symbol", "rebel_symbol", "primary_colour",
    "secondary_colour", "loading_logo", "standard_index", "logo_index",
    "small_logo_index", "triumph_value", "custom_battle_availability",
    "can_sap", "prefers_naval_invasions", "can_have_princess", "has_family_tree")

SHAPE = fr.Shape(rel=REL, label="Factions", kw="faction", noun="faction",
                 order=ORDER, required=REQUIRED, repeat_kw="horde_unit")

#: the eight keys that only mean anything together — a horde is all of them or none
HORDE_KEYS: Tuple[str, ...] = tuple(k for k in ORDER if k.startswith("horde_"))

#: keys whose value is ``yes`` or ``no`` and nothing else (measured: no real
#: faction writes anything else in them). ``has_family_tree`` is NOT one of them.
YES_NO: Tuple[str, ...] = ("custom_battle_availability", "can_sap",
                           "prefers_naval_invasions", "can_have_princess",
                           "disband_to_pools", "can_build_siege_towers",
                           "can_transmit_plague")

#: ``has_family_tree`` has three values, and 24 of 90 real factions say the third
FAMILY_TREE: Tuple[str, ...] = ("yes", "no", "teutonic")

#: the two the engine knows, one faction each per campaign
SPECIAL_TYPES: Tuple[str, ...] = ("slave_faction", "papal_faction")

#: the modifiers a head line may carry after its comma
HEAD_MODIFIERS: Tuple[str, ...] = ("spawned_on_event", "shadowing", "shadowed_by")

#: keys whose value is a whole number
INT_KEYS: Tuple[str, ...] = ("standard_index", "triumph_value") + HORDE_KEYS

#: keys naming a file under ``data/``
ART_KEYS: Tuple[str, ...] = ("symbol", "rebel_symbol", "loading_logo")

#: M2TW's faction cap. Vanilla ships 31 slots; two of the three installed mods
#: sit at exactly 31 and none is above it. (TWCenter's *List of Hardcoded Limits*
#: says 21, but that entry is RTW's — the same guide is RTW-era throughout, as
#: the traits phase already found.)
FACTION_LIMIT = 31

#: where a faction's shown name lives, relative to ``data/``. The tag is the slot
#: in UPPER CASE — ``{SICILY}Kingdom of Gondor`` — which is worth knowing before
#: writing one: a lower-case tag creates a second entry the game never reads.
LOC_REL = "text/expanded.txt"

FactionError = fr.RecordError

_COLOUR_RE = re.compile(r"red\s+(\d+)\s*,\s*green\s+(\d+)\s*,\s*blue\s+(\d+)", re.I)


# ---------------------------------------------------------------------------
# the head line, which is a slot and possibly a modifier


def slot_of(name: str) -> str:
    """``"egypt, spawned_on_event"`` -> ``"egypt"``.

    The slot is what ``descr_strat``, the EDU's ownership lines, every
    ``requires factions { … }`` clause and ``expanded.txt`` all point at. The
    modifier is this file's own business.
    """
    return (name or "").partition(",")[0].strip()


def modifier_of(name: str) -> str:
    """``"spain, shadowed_by hrebels"`` -> ``"shadowed_by hrebels"``."""
    return (name or "").partition(",")[2].strip()


# ---------------------------------------------------------------------------
# colours, the one thing in this file that is genuinely visual


def parse_colour(value: str) -> Optional[Tuple[int, int, int]]:
    """``"red 55, green 75, blue 48"`` -> ``(55, 75, 48)``, or ``None``."""
    m = _COLOUR_RE.search(value or "")
    if not m:
        return None
    rgb = tuple(int(g) for g in m.groups())
    return rgb if all(0 <= c <= 255 for c in rgb) else None


def format_colour(rgb) -> str:
    """``(55, 75, 48)`` -> ``"red 55, green 75, blue 48"`` — the file's own words."""
    r, g, b = (max(0, min(255, int(c))) for c in rgb)
    return f"red {r}, green {g}, blue {b}"


def hex_colour(value: str) -> str:
    """``"red 55, …"`` -> ``"#374b30"``, so a browser colour input can show it."""
    rgb = parse_colour(value)
    return "#%02x%02x%02x" % rgb if rgb else ""


def from_hex(text: str) -> str:
    """``"#374b30"`` -> ``"red 55, green 75, blue 48"``."""
    s = (text or "").lstrip("#")
    if len(s) != 6:
        raise FactionError(f"`{text}` is not a #rrggbb colour")
    try:
        return format_colour(tuple(int(s[i:i + 2], 16) for i in (0, 2, 4)))
    except ValueError:
        raise FactionError(f"`{text}` is not a #rrggbb colour") from None


# ---------------------------------------------------------------------------
# reading the file


def parse_text(text: str) -> fr.RecordFile:
    return fr.parse_records(SHAPE, text)


def parse_file(path: str | Path) -> fr.RecordFile:
    return fr.parse_records(SHAPE, kb.read_text(Path(path), ENCODING))


def parse_block(text: str) -> fr.Record:
    return fr.parse_record_block(SHAPE, text)


def render_block(base: str, edits: Optional[Dict] = None) -> str:
    return fr.render_record(SHAPE, base, edits or {})


def block_spans(block: str) -> Dict[str, List[List[int]]]:
    return fr.record_spans(SHAPE, block)


def block_fields(block: str) -> List[Tuple[str, str]]:
    return fr.record_fields(SHAPE, block)


def path_for(mod) -> Path:
    return Path(mod.data) / REL


def faction_cultures(mod) -> Dict[str, str]:
    """slot -> culture, lower-cased. The single source of truth for that question.

    Building icons are picked by *culture* while a level's ``requires`` clause
    names *factions*, so the buildings browser has always needed this map — it
    just used to read the file with a regex of its own.
    """
    path = path_for(mod)
    if not path.is_file():
        return {}
    try:
        rf = parse_file(path)
    except (OSError, ValueError):
        return {}
    out: Dict[str, str] = {}
    for rec in rf.records:
        slot = slot_of(rec.name).lower()
        if slot:
            out.setdefault(slot, rec.get("culture").strip(",").lower())
    return out


def faction_slots(mod) -> List[str]:
    """Every faction slot this mod defines, in file order."""
    path = path_for(mod)
    if not path.is_file():
        return []
    return [s for s in (slot_of(r.name) for r in parse_file(path).records) if s]


# ---------------------------------------------------------------------------
# localisation and art


def loc(mod) -> Dict[str, str]:
    """``{TAG: text}`` from ``text/expanded.txt``, or its compiled archive."""
    return minorfiles._loc(mod, LOC_REL)


def loc_tag(name: str) -> str:
    """The ``expanded.txt`` key a faction's shown name is stored under.

    Upper case, because that is what all three mods write and what the compiled
    archive holds. :attr:`unittransfer.mod.Mod.faction_names` lower-cases on the
    way in, which is fine for reading and wrong for writing.
    """
    return slot_of(name).upper()


def label(name: str, names: Dict[str, str]) -> str:
    """``"Kingdom of Gondor (sicily)"`` — and here it earns its keep.

    Mods reuse vanilla slots wholesale: DaC's ``sicily`` is the Kingdom of
    Gondor and its ``turks`` are somebody else entirely. Without the real name
    first this screen would be a list of the wrong countries.
    """
    slot = slot_of(name)
    shown = (names.get(loc_tag(name)) or "").strip()
    return f"{shown} ({slot})" if shown and shown != slot else slot


#: Where a faction's pictures actually sit when a mod ships them unpacked, as
#: ``(label, path template)``. `{f}` is the faction slot. The roster itself names
#: none of these — see the module docstring — so they are found by convention,
#: which is exactly how the game finds them too.
PICTURE_DIRS: Tuple[Tuple[str, str], ...] = (
    ("Faction symbol", "ui/faction_symbols/{f}.tga"),
    ("Small symbol", "ui/faction_symbols_small/{f}.tga"),
    ("Menu icon", "ui/pips/faction_{f}.tga"),
    ("Loading screen", "ui/loading_screen/symbols/symbol128_{f}.tga"),
    ("Loading screen", "ui/loading_screen/symbols/symbol64_{f}.tga"),
    ("Banner", "banners/textures/{f}_main_ea.texture"),
)


def pictures(mod, slot: str) -> List[Dict]:
    """Every faction picture of ``slot`` this mod actually has on disk.

    An empty list is the normal answer for a mod that keeps its art in a
    ``.pack`` archive, and is never reported as a fault — the same ruling the
    settlement cards and religion pips got.
    """
    out: List[Dict] = []
    slot = (slot or "").strip().lower()
    if not slot:
        return out
    for label_, tmpl in PICTURE_DIRS:
        rel = tmpl.format(f=slot)
        try:
            if (Path(mod.data) / rel).is_file():
                out.append({"label": label_, "rel": rel})
        except OSError:
            pass
    return out


def picture_path(mod, rel: str) -> Optional[Path]:
    """Resolve one of :func:`pictures`' relative paths, refusing anything else."""
    rel = (rel or "").strip().replace("\\", "/")
    if not rel or ".." in rel.split("/"):
        return None
    try:
        p = (Path(mod.data) / rel).resolve()
        root = Path(mod.data).resolve()
        if root not in p.parents:
            return None
        return p if p.is_file() else None
    except OSError:
        return None


def art_path(mod, rel: str) -> Optional[Path]:
    """Where a ``symbol`` / ``loading_logo`` path actually is, or ``None``.

    ``None`` is the normal answer and is not a fault: every one of the 90 real
    ``loading_logo`` files lives in a ``.pack`` archive the toolkit cannot read.
    """
    rel = (rel or "").strip().replace("\\", "/")
    if not rel:
        return None
    try:
        p = Path(mod.data) / rel
        return p if p.is_file() else None
    except OSError:
        return None


# ---------------------------------------------------------------------------
# what is wrong with a faction that still parses


def check_file(rf: fr.RecordFile, mod=None) -> List[Dict]:
    """Findings for the whole roster.

    Deliberately silent about the art it names — see the module docstring.
    """
    out: List[Dict] = fr.check_records(SHAPE, rf)

    def add(kind: str, name: str, line: int, message: str) -> None:
        out.append({"kind": kind, "name": name, "line": line + 1, "message": message})

    cultures = religions = units = None
    if mod is not None:
        try:
            cultures = set(minorfiles.culture_names(mod)) or None
            religions = set(minorfiles.religion_names(mod)) or None
        except (OSError, AttributeError, ValueError):
            cultures = religions = None
        try:
            units = {u.type for u in mod.edu.units} or None
        except (OSError, AttributeError, ValueError):
            units = None

    slots = {slot_of(r.name) for r in rf.records}
    if len(rf.records) > FACTION_LIMIT:
        first = rf.records[FACTION_LIMIT]
        add("too-many-factions", first.name, first.start,
            f"{len(rf.records)} factions — the engine loads {FACTION_LIMIT} and this "
            "one is past the end")

    for rec in rf.records:
        mod_kw = modifier_of(rec.name).split()[0] if modifier_of(rec.name) else ""
        if mod_kw and mod_kw not in HEAD_MODIFIERS:
            add("unknown-modifier", rec.name, rec.start,
                f"`{mod_kw}` is not a head-line modifier — the engine knows "
                + kb.and_list(HEAD_MODIFIERS))
        if mod_kw in ("shadowing", "shadowed_by"):
            other = modifier_of(rec.name).split()[1:2]
            if other and other[0] not in slots:
                add("unknown-shadow", rec.name, rec.start,
                    f"`{other[0]}` is not a faction in this file")

        culture = rec.get("culture").strip(",")
        if cultures is not None and culture and culture not in cultures:
            add("unknown-culture", rec.name, rec.lines["culture"],
                f"`{culture}` is not a culture in descr_cultures.txt")
        religion = rec.get("religion").strip(",")
        if religions is not None and religion and religion not in religions:
            add("unknown-religion", rec.name, rec.lines["religion"],
                f"`{religion}` is not in the `religions` list of descr_religions.txt")

        for key in ("primary_colour", "secondary_colour"):
            if key in rec.lines and parse_colour(rec.get(key)) is None:
                add("bad-colour", rec.name, rec.lines[key],
                    f"`{rec.get(key)}` is not `red <0-255>, green <0-255>, "
                    "blue <0-255>`")
        for key in INT_KEYS:
            if key in rec.lines and not kb.is_int(rec.get(key)):
                add("bad-number", rec.name, rec.lines[key],
                    f"`{rec.get(key)}` is not a whole number")
        for key in YES_NO:
            value = rec.get(key)
            if key in rec.lines and value not in ("yes", "no"):
                add("bad-yes-no", rec.name, rec.lines[key],
                    f"`{value}` — `{key}` is yes or no")
        if "has_family_tree" in rec.lines and rec.get("has_family_tree") not in FAMILY_TREE:
            add("bad-family-tree", rec.name, rec.lines["has_family_tree"],
                f"`{rec.get('has_family_tree')}` — has_family_tree is "
                + kb.and_list(FAMILY_TREE))
        special = rec.get("special_faction_type")
        if special and special not in SPECIAL_TYPES:
            add("unknown-special-type", rec.name, rec.lines["special_faction_type"],
                f"`{special}` is not " + kb.and_list(SPECIAL_TYPES))

        have_horde = [k for k in HORDE_KEYS if k in rec.lines]
        if have_horde and rec.repeats and len(have_horde) < len(HORDE_KEYS):
            missing = [k for k in HORDE_KEYS if k not in rec.lines]
            add("part-horde", rec.name, rec.lines[have_horde[0]],
                "this faction has some horde lines and not others — no "
                + kb.and_list(missing))
        if have_horde and not rec.repeats:
            add("horde-no-units", rec.name, rec.lines[have_horde[0]],
                "horde settings but no `horde_unit` line — the horde has nothing "
                "to spawn")
        for rep in rec.repeats:
            if units is not None and rep.value not in units:
                add("unknown-horde-unit", rec.name, rep.line,
                    f"`{rep.value}` is not a unit in this mod's EDU")

    for kind, keyword in (("slave_faction", "slave_faction"),
                          ("papal_faction", "papal_faction")):
        holders = [r for r in rf.records if r.get("special_faction_type") == keyword]
        if len(holders) > 1:
            add("duplicate-special", holders[1].name, holders[1].start,
                f"{len(holders)} factions are `{keyword}` — the engine wants one")
    return out


# ---------------------------------------------------------------------------
# what the editor's list and its detail pane are made of


#: this module edits records; it does not create or destroy faction slots
ACTIONS: Tuple[str, ...] = ("edit",)

REFUSED = ("A faction slot lives in eight or nine files at once — descr_strat, "
           "expanded.txt, the banners, descr_names, the UI folders, every unit's "
           "ownership line and every `requires factions { … }` clause. A faction "
           "that exists only in this one is a mod that will not load, so this "
           "module changes factions and leaves creating and deleting them to the "
           "step-by-step job they are.")


def overview(mod) -> Dict:
    """Every faction in the mod, light enough to paint the whole roster."""
    path = path_for(mod)
    out: Dict = {"mod": getattr(mod, "name", ""), "file": REL,
                 "exists": path.is_file(), "factions": [], "findings": 0,
                 "count": 0, "actions": list(ACTIONS), "refused": REFUSED,
                 "limit": FACTION_LIMIT}
    if not path.is_file():
        out["error"] = f"{getattr(mod, 'name', '?')} has no {REL}"
        return out
    rf = parse_file(path)
    names = loc(mod)
    counted: Dict[str, int] = {}
    found = check_file(rf, mod)
    for finding in found:
        counted[finding["name"]] = counted.get(finding["name"], 0) + 1
    out["finding_list"] = [{"name": f.get("name", ""), "kind": f.get("kind", ""),
                            "message": f.get("message", "")} for f in found]
    for rec in rf.records:
        out["factions"].append({
            "name": rec.name, "slot": slot_of(rec.name),
            "modifier": modifier_of(rec.name),
            "label": label(rec.name, names),
            "culture": rec.get("culture"), "religion": rec.get("religion"),
            "primary": hex_colour(rec.get("primary_colour")),
            "secondary": hex_colour(rec.get("secondary_colour")),
            "horde": len(rec.repeats),
            "special": rec.get("special_faction_type"),
            "findings": counted.get(rec.name, 0), "line": rec.start + 1})
    out["count"] = len(rf.records)
    out["findings"] = sum(counted.values())
    out["loc"] = bool(names)
    out["warnings"] = rf.warnings[:20]
    out["cultures"] = minorfiles.culture_names(mod)
    out["religions"] = minorfiles.religion_names(mod)
    return out


def detail(mod, name: str) -> Dict:
    """One faction, everything the editor's pane draws."""
    rf = parse_file(path_for(mod))
    rec = rf.get(name) or next(
        (r for r in rf.records if slot_of(r.name) == slot_of(name)), None)
    if rec is None:
        raise KeyError(f"no faction {name!r} in {REL}")
    block = rf.block_text(rec)
    names = loc(mod)
    tag = loc_tag(rec.name)
    art = {k: bool(art_path(mod, rec.get(k))) for k in ART_KEYS}
    units = []
    try:
        for u in mod.edu.units:
            entry = mod.loc.get(u.dictionary)
            shown = (entry.name.strip() if entry and entry.name else "")
            units.append({"type": u.type,
                          "label": f"{shown} ({u.type})" if shown else u.type})
    except (OSError, AttributeError, ValueError):
        units = []
    return {
        "mod": getattr(mod, "name", ""), "file": REL, "name": rec.name,
        "slot": slot_of(rec.name), "modifier": modifier_of(rec.name),
        "label": label(rec.name, names),
        "faction": dict(rec.as_dict(SHAPE), horde_units=[r.value for r in rec.repeats]),
        "colours": {k: hex_colour(rec.get(k))
                    for k in ("primary_colour", "secondary_colour")},
        "text": block, "fields": [list(f) for f in block_fields(block)],
        "spans": block_spans(block),
        "findings": [f for f in check_file(rf, mod) if f["name"] == rec.name],
        "loc_tag": tag, "loc_file": LOC_REL, "loc_writable": True,
        "loc": {tag: names.get(tag, "")},
        "missing_loc": [tag] if names and tag not in names else [],
        "has_loc": bool(names),
        "art_found": art,
        # the pictures this mod really ships for the slot, found by convention
        # rather than named by the roster (which names none)
        "pictures": pictures(mod, slot_of(rec.name)),
        "actions": list(ACTIONS),
        "vocab": {
            "cultures": minorfiles.culture_names(mod),
            "religions": minorfiles.religion_names(mod),
            "yes_no": list(YES_NO), "family_tree": list(FAMILY_TREE),
            "special_types": list(SPECIAL_TYPES), "horde_keys": list(HORDE_KEYS),
            "order": list(ORDER), "required": list(REQUIRED),
            "int_keys": list(INT_KEYS), "art_keys": list(ART_KEYS),
            "units": units,
            "logo_indexes": sorted({r.get("logo_index") for r in rf.records
                                    if r.get("logo_index")}),
            "small_logo_indexes": sorted({r.get("small_logo_index")
                                          for r in rf.records
                                          if r.get("small_logo_index")}),
        },
    }


# ---------------------------------------------------------------------------
# plan -> apply


@dataclass
class FactionPlan:
    mod: object = None
    action: str = "edit"
    name: str = ""
    changes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    findings: List[Dict] = field(default_factory=list)
    text: str = ""
    block: str = ""
    loc_writes: Dict[str, str] = field(default_factory=dict)
    loc_new: List[str] = field(default_factory=list)

    def summary(self) -> str:
        head = (f"{self.action} faction {self.name} in "
                f"{getattr(self.mod, 'name', '?')} ({len(self.changes)} change(s))")
        return "\n".join([head] + [f"  {c}" for c in self.changes])

    def touched(self) -> bool:
        return bool(self.text or self.loc_writes)

    def payload(self) -> Dict:
        return {"action": self.action, "name": self.name,
                "changes": list(self.changes), "warnings": list(self.warnings),
                "errors": list(self.errors), "findings": list(self.findings),
                "block": self.block, "loc_writes": dict(self.loc_writes),
                "loc_new": list(self.loc_new), "loc_file": LOC_REL,
                "ok": not self.errors and self.touched()}


def plan(mod, body: dict) -> FactionPlan:
    """Work out the whole new roster for one save, without touching the disk.

    ``body`` is ``{mod, faction, action, edits, raw_block, loc, write_loc}`` —
    the ancillaries request shape again, because every editor in the toolkit
    sends the same thing.
    """
    p = FactionPlan(mod=mod, action=str(body.get("action") or "edit"),
                    name=str(body.get("faction") or "").strip())
    if p.action not in ACTIONS:
        p.errors.append(REFUSED)
        return p
    path = path_for(mod)
    if not path.is_file():
        p.errors.append(f"{getattr(mod, 'name', '?')} has no {REL}")
        return p
    original = kb.read_text(path, ENCODING)
    rf = parse_text(original)
    rec = rf.get(p.name) or next(
        (r for r in rf.records if slot_of(r.name) == slot_of(p.name)), None)
    if rec is None:
        p.errors.append(f"{p.name} is not a faction in this file")
        return p
    p.name = rec.name

    base = rf.block_text(rec)
    raw = body.get("raw_block")
    try:
        if raw is not None and str(raw).strip():
            block = str(raw).strip("\r\n")
            if slot_of(parse_block(block + "\n").name) != slot_of(p.name):
                raise FactionError(
                    f"this faction is `{slot_of(p.name)}` — renaming a slot here "
                    "would orphan descr_strat, every unit's ownership line, every "
                    "`requires factions { … }` clause and its own text entry")
        else:
            edits = dict(body.get("edits") or {})
            edits.pop("name", None)      # the slot is not editable — see above
            block = render_block(base, edits)
    except fr.RecordError as e:
        p.errors.append(e.message)
        return p

    text = original
    if block != base:
        p.changes.extend(kb.diff(base, block))
        text = rf.replace(rec.start, rec.end, block)
    p.text = "" if text == original else text

    after = parse_text(text)
    now = after.get(p.name)
    if now is not None:
        p.block = after.block_text(now)
        p.findings = [f for f in check_file(after, mod) if f["name"] == p.name]
        if body.get("write_loc", True):
            _plan_loc(p, mod, now, dict(body.get("loc") or {}))
    if not p.touched() and not p.errors:
        p.warnings.append("nothing to change")
    return p


def _plan_loc(p: FactionPlan, mod, rec, wanted: Dict) -> None:
    """What this save would write into ``text/expanded.txt``."""
    from . import stringsbin
    tag = loc_tag(rec.name)
    have = loc(mod)
    txt = Path(mod.data) / LOC_REL
    if not txt.exists() and not stringsbin.bin_path_for(txt).exists():
        p.warnings.append(f"this mod has no {Path(LOC_REL).name}, so this faction's "
                          "name could not be written — it will show its slot in game")
        return
    want = str(wanted.get(tag, "")).strip() if wanted else ""
    if tag not in have:
        p.loc_writes[tag] = want or slot_of(rec.name)
        p.loc_new.append(tag)
        p.changes.append(f"+ a new text key in {Path(LOC_REL).name}")
    elif want and want != have[tag]:
        p.loc_writes[tag] = want
        p.changes.append(f"~ the name in {Path(LOC_REL).name}")


def apply(p: FactionPlan) -> Dict:
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
    tid = config.new_transfer_id()
    backup_root = config.backup_root_for(tid)
    manifest: Dict[str, List[str]] = {"backed_up": [], "created": []}
    out: Dict = {"id": tid, "faction": p.name}

    def keep(rel: str) -> Path:
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
        target = keep(REL)
        kb.write_text(target, p.text, ENCODING)
        file_op("WRITE", target, f"{len(p.text)} bytes")
    if p.loc_writes:
        txt = Path(mod.data) / LOC_REL
        if txt.exists():
            target = keep(LOC_REL)
            keep(LOC_REL + ".strings.bin")
            kb.write_text(target,
                          stringsbin.upsert_txt(kb.read_text(target, "utf-16"),
                                                p.loc_writes),
                          "utf-16")
            file_op("WRITE", target, f"{len(p.loc_writes)} text key(s)")
            res = cleaner.refresh_strings_bin(mod.root,
                                              "data/" + LOC_REL + ".strings.bin")
            out["loc"] = {"file": LOC_REL, "written": len(p.loc_writes),
                          "new": len(p.loc_new), "strings_bin": res}
        else:
            rel = LOC_REL + ".strings.bin"
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
        "mode": "factions",
        "action": p.action,
        "source": mod.name, "source_root": str(mod.root),
        "dest": mod.name, "dest_root": str(mod.root),
        "unit_type": p.name, "resolved_type": p.name,
        "options": {}, "applied": True, "undone": False, "note": "",
        "summary": p.summary(), "warnings": list(p.warnings),
        "manifest": manifest, "backup_root": str(backup_root),
    }
    config.append_log(rec)
    log.info("FACTION %s %s in %s — %d change(s), id=%s",
             p.action, p.name, mod.name, len(p.changes), tid)
    out["record"] = rec
    return out
