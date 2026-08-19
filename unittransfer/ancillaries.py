"""The ancillary definitions of ``export_descr_ancillaries.txt``.

EDA is EDCT's smaller sibling: same two halves, same trigger language below, and
a definition above that is one flat record instead of a ladder of levels::

    Ancillary iron_guard
        Type follower
        Transferable 0
        Image iron_guard.tga
        Unique
        ExcludedAncillaries iron_guard
        ExcludeCultures greek, noldor
        Description iron_guard_desc
        EffectsDescription iron_guard_effects_desc
        Effect Command 1
        Effect PersonalSecurity 2

The block machinery is :mod:`unittransfer.keyblock` and the trigger half is
:mod:`unittransfer.triggers`, both already written — the two formats are one
language and Squid's guide documents them in one document for that reason. What
is left here is what EDA does *differently*, and there are four things:

**``Type`` and ``Transferable`` are not in the guide.** That guide is RTW's; both
lines are M2TW additions and both are present in all 1134 ancillaries the three
installed mods define, always as lines two and three. ``Type`` is a free-form
grouping name — a character holds one ancillary per type — and ``Transferable``
is ``0`` or ``1``: whether it can be handed to another character.

**The trigger half grants rather than adds.** EDCT triggers say ``Affects <trait>
<points> Chance <n>``; EDA's say ``AcquireAncillary <name> chance <n>``, and the
``chance`` keyword is written both ways in the wild (609 lower-case against 710
capitalised across the same six files), so it is left exactly as found.

**Two hardcoded limits, and both are silent.** At most 3 ``ExcludedAncillaries``
(more is an errorless CTD) and at most 8 ``Effect`` lines (more makes the
ancillary impossible to gain from a trigger, and misbehaves when one is
transferred). Both are from TWCenter's *List of Hardcoded Limits*; no installed
mod is over either, so :func:`check` reporting one means something.

**An ancillary has a picture.** ``Image`` names a file under
``data/ui/ancillaries``, which the mods here ship unpacked — so it can be shown
beside the record the way a unit card is.

Text keys live in ``data/text/export_ancillaries.txt`` rather than
``export_VnVs.txt``, and a missing one is an errorless CTD the moment anybody
acquires the ancillary or opens the character screen holding it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import keyblock as kb
from . import traits as traits_mod
from . import triggers

#: EDA is plain 8-bit text, like the EDCT beside it
ENCODING = triggers.ENCODING

ANC_KW = "Ancillary"

#: every line of a record, **in the order all 1134 real ancillaries write them**.
#: ``Effect`` lines follow, and there may be up to :data:`MAX_EFFECTS` of them.
BODY_ORDER = ("Type", "Transferable", "Image", "Unique", "ExcludedAncillaries",
              "ExcludeCultures", "Description", "EffectsDescription")

#: the lines the engine will not do without
REQUIRED = ("Type", "Transferable", "Image", "Description", "EffectsDescription")

#: lines that are the whole line — present or absent, never a value
FLAGS = ("Unique",)

#: keys whose value is a comma-separated list
LIST_KEYS = ("ExcludedAncillaries", "ExcludeCultures")

#: hardcoded engine limits (TWCenter, *List of Hardcoded Limits*)
MAX_EXCLUDED = 3
MAX_EFFECTS = 8

#: where an ancillary's displayed name and descriptions come from, relative to
#: ``data/`` — and its compiled cache, which :mod:`unittransfer.cleaner`
#: addresses from the mod root instead
LOC_REL = "text/export_ancillaries.txt"
LOC_BIN_REL = "data/" + LOC_REL + ".strings.bin"

#: where ``Image`` names are resolved, relative to ``data/``
IMAGE_DIR = "ui/ancillaries"

#: field name in an edit request -> the keyword it writes
_FIELDS = {"type": "Type", "transferable": "Transferable", "image": "Image",
           "unique": "Unique", "excluded_ancillaries": "ExcludedAncillaries",
           "exclude_cultures": "ExcludeCultures", "description": "Description",
           "effects_description": "EffectsDescription"}
_KEY_FIELD = {v: k for k, v in _FIELDS.items()}

#: the ``Effect`` line is the same construct in both files, so it is the same class
Effect = traits_mod.Effect


class AncillaryError(kb.BlockError):
    """The text is not an ancillary block, or an edit would write a bad file."""


# ---------------------------------------------------------------------------
# the parsed shapes


@dataclass
class Ancillary:
    """One ``Ancillary`` block: a name, its lines, and any effects."""
    name: str = ""
    values: Dict[str, str] = field(default_factory=dict)   # keyword -> value
    lines: Dict[str, int] = field(default_factory=dict)    # keyword -> 0-based line
    effects: List[Effect] = field(default_factory=list)
    start: int = 0
    end: int = 0
    warnings: List[str] = field(default_factory=list)

    def get(self, key: str) -> str:
        return self.values.get(key, "")

    @property
    def unique(self) -> bool:
        return "Unique" in self.lines

    @property
    def transferable(self) -> bool:
        return self.get("Transferable").strip() != "0"

    @property
    def excluded_ancillaries(self) -> List[str]:
        return kb.split_list(self.get("ExcludedAncillaries"))

    @property
    def exclude_cultures(self) -> List[str]:
        return kb.split_list(self.get("ExcludeCultures"))

    def as_dict(self) -> Dict:
        d = {"name": self.name, "start": self.start, "end": self.end,
             "unique": self.unique,
             "excluded_ancillaries": self.excluded_ancillaries,
             "exclude_cultures": self.exclude_cultures,
             "effects": [e.as_dict() for e in self.effects]}
        for key, fieldname in _FIELDS.items():
            if key not in ("unique", "excluded_ancillaries", "exclude_cultures"):
                d[key] = self.values.get(fieldname, "")
        return d


@dataclass
class AncillaryFile:
    """A whole EDA, held as its own lines with the ancillaries indexed into it."""
    lines: List[str] = field(default_factory=list)
    newline: str = "\r\n"
    ancillaries: List[Ancillary] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    trailing_newline: bool = True
    #: 0-based line of the first ``Trigger`` — where the other half starts
    trigger_start: int = -1

    def text(self) -> str:
        """The file exactly as it was read — the property everything else rests on."""
        out = self.newline.join(self.lines)
        return out + self.newline if self.trailing_newline and self.lines else out

    def get(self, name: str) -> Optional[Ancillary]:
        return next((a for a in self.ancillaries if a.name == name), None)

    def by_name(self) -> Dict[str, Ancillary]:
        return {a.name: a for a in self.ancillaries}

    def block_text(self, anc: Ancillary) -> str:
        return self.newline.join(self.lines[anc.start:anc.end])


# ---------------------------------------------------------------------------
# parsing


def parse_text(text: str) -> AncillaryFile:
    """Read a whole EDA. Never raises: anything odd becomes a warning.

    Only the *definition* half is interpreted; the trigger section below it is
    carried as lines and belongs to :mod:`unittransfer.triggers`, which reads the
    same file the other way round.
    """
    lines, newline, trailing = triggers.split_lines(text)
    af = AncillaryFile(lines=lines, newline=newline, trailing_newline=trailing)

    cur: Optional[Ancillary] = None
    for i, raw in enumerate(lines):
        code = kb.code_of(raw)
        if not code:
            continue
        words = code.split()
        head = words[0]
        value = code[len(head):].strip()

        if head == ANC_KW:
            cur = Ancillary(name=words[1] if len(words) > 1 else "", start=i, end=i + 1)
            if not cur.name:
                cur.warnings.append(f"line {i + 1}: this Ancillary has no name")
            af.ancillaries.append(cur)
            continue
        if head == triggers.TRIGGER_KW:
            if af.trigger_start < 0:
                af.trigger_start = i
            cur = None
            continue
        if cur is None:
            continue

        if head == "Effect":
            cur.effects.append(Effect(attribute=words[1] if len(words) > 1 else "",
                                      amount=words[2] if len(words) > 2 else "",
                                      line=i))
            cur.end = i + 1
            continue
        if head not in BODY_ORDER:
            cur.warnings.append(f"line {i + 1}: `{head}` is not an ancillary line")
        elif head in cur.lines:
            cur.warnings.append(f"line {i + 1}: a second `{head}` line")
        cur.values[head] = value
        cur.lines[head] = i
        cur.end = i + 1

    for a in af.ancillaries:
        af.warnings.extend(f"{a.name or '(unnamed)'}: {w}" for w in a.warnings)
    return af


def parse_file(path: str | Path) -> AncillaryFile:
    return parse_text(kb.read_text(Path(path), ENCODING))


def parse_block(text: str) -> Ancillary:
    """Read ONE ancillary block, as the code view's pane holds it.

    Raises :class:`AncillaryError` rather than warning: a pane that edits one
    record must not quietly accept text holding two, or none.
    """
    af = parse_text(text if text.endswith("\n") else text + "\n")
    if not af.ancillaries:
        raise AncillaryError("an ancillary block starts with an `Ancillary <name>` "
                             "line — this text has none", 1)
    if len(af.ancillaries) > 1:
        raise AncillaryError(
            f"this text holds {len(af.ancillaries)} ancillary blocks — one at a time",
            af.ancillaries[1].start + 1)
    if af.trigger_start >= 0:
        raise AncillaryError("there is a `Trigger` block in this text — the trigger "
                             "section is edited on its own", af.trigger_start + 1)
    return af.ancillaries[0]


# ---------------------------------------------------------------------------
# what is wrong with an ancillary that still parses


def check(anc: Ancillary, known: Optional[set] = None) -> List[Dict]:
    """Findings for one ancillary: what the engine refuses, and what will not work."""
    out: List[Dict] = []

    def add(kind: str, line: int, message: str) -> None:
        out.append({"kind": kind, "ancillary": anc.name, "line": line + 1,
                    "message": message})

    for key in REQUIRED:
        if key not in anc.lines:
            add("missing-line", anc.start,
                f"no `{key}` line — the game will not load this ancillary")

    order = [k for k in BODY_ORDER if k in anc.lines]
    placed = sorted(order, key=lambda k: anc.lines[k])
    if order != placed:
        add("line-order", anc.lines[placed[0]],
            "the lines are in the order " + ", ".join(placed) + " but every real "
            "ancillary writes them " + ", ".join(order))

    transferable = anc.get("Transferable").strip()
    if "Transferable" in anc.lines and transferable not in ("0", "1"):
        add("bad-transferable", anc.lines["Transferable"],
            f"`{transferable}` — Transferable is 0 or 1")

    excluded = anc.excluded_ancillaries
    if len(excluded) > MAX_EXCLUDED:
        add("too-many-excluded", anc.lines["ExcludedAncillaries"],
            f"{len(excluded)} excluded ancillaries — more than {MAX_EXCLUDED} is an "
            "errorless crash")
    if known is not None:
        for name in excluded:
            if name not in known:
                add("unknown-excluded", anc.lines["ExcludedAncillaries"],
                    f"`{name}` is not an ancillary this file defines")
    # The guide's note, and it holds in the real files: a Unique ancillary that is
    # not on its own excluded list can be acquired a second time.
    if anc.unique and anc.name and anc.name not in excluded:
        add("unique-not-excluded", anc.lines["Unique"],
            "a `Unique` ancillary needs its own name on its `ExcludedAncillaries` "
            "line, or it can still be acquired twice")

    if len(anc.effects) > MAX_EFFECTS:
        add("too-many-effects", anc.effects[MAX_EFFECTS].line,
            f"{len(anc.effects)} effects — more than {MAX_EFFECTS} makes this "
            "ancillary impossible to gain from a trigger")
    attrs = set(triggers.vocab().get("attributes", []))
    for eff in anc.effects:
        if not traits_mod._known_attribute(eff.attribute, attrs):
            add("unknown-attribute", eff.line,
                f"`{eff.attribute}` is not a character attribute")
        elif not kb.is_int(eff.amount):
            add("bad-effect-amount", eff.line,
                f"`{eff.amount}` is not a whole number of points")
    return out


def check_file(af: AncillaryFile, trigger_file=None, mod=None) -> List[Dict]:
    """Every finding in the file, including the ones only both halves can see.

    An ``AcquireAncillary`` naming an ancillary this file does not define is the
    guide's errorless CTD, and no amount of reading the definition half shows it.
    ``mod`` adds the findings that need the folder rather than the file — an
    ``Image`` line naming a picture nobody shipped.
    """
    known = {a.name for a in af.ancillaries if a.name}
    out: List[Dict] = []
    # Pictures the mod does not ship. Whether that is a defect depends on
    # something outside this file, so they are collected and judged once below
    # instead of each becoming a finding on the way past.
    checkable = vanilla_images() is not None
    unshipped: List = []

    seen: Dict[str, int] = {}
    for a in af.ancillaries:
        if a.name in seen:
            out.append({"kind": "duplicate-ancillary", "ancillary": a.name,
                        "line": a.start + 1,
                        "message": f"`{a.name}` is already defined on line "
                                   f"{seen[a.name] + 1} — names must be unique"})
        else:
            seen[a.name] = a.start
        out.extend(check(a, known))
        if mod is not None and a.get("Image") and image_path(mod, a.get("Image")) is None:
            unshipped.append(a)

    # With the game's own pictures in view, an absent one really is a blank slot
    # and each is worth naming. Without them, "not shipped here" is all anyone
    # can say, and saying it 56 times buries the findings that are real — so it
    # is said once, against the first one, with the count.
    if checkable:
        out.extend(_image_finding(a, a.get("Image"), True) for a in unshipped)
    elif unshipped:
        first = _image_finding(unshipped[0], unshipped[0].get("Image"), False)
        if len(unshipped) > 1:
            first["message"] += (f" (and {len(unshipped) - 1} other "
                                 f"ancillar{'y' if len(unshipped) == 2 else 'ies'})")
        first["ancillaries"] = [a.name for a in unshipped]
        out.append(first)

    if trigger_file is None:
        return out
    for trig in trigger_file.triggers:
        for eff in trig.effects:
            if eff.keyword != "AcquireAncillary" or not eff.args:
                continue
            if eff.args[0] not in known:
                out.append({"kind": "unknown-acquire", "ancillary": eff.args[0],
                            "line": eff.line + 1,
                            "message": f"trigger `{trig.name}` grants "
                                       f"`{eff.args[0]}`, which this file does not "
                                       "define — an errorless crash when it fires"})
    return out


# ---------------------------------------------------------------------------
# localisation and art


def loc(mod) -> Dict[str, str]:
    """``{tag: text}`` from the mod's ``export_ancillaries.txt``, or its archive.

    Same flat ``{tag}text`` shape as the trait file, read through Phase 6's codec
    when a mod ships only the compiled ``.strings.bin``.
    """
    from . import stringsbin
    path = Path(getattr(mod, "data", "")) / LOC_REL
    try:
        if path.exists():
            return dict(stringsbin.from_txt(kb.read_text(path, "utf-16")))
    except (OSError, UnicodeError, ValueError):
        pass
    try:
        return stringsbin.load_pairs(stringsbin.bin_path_for(path))
    except (OSError, ValueError):
        return {}


def label(anc: Ancillary, names: Dict[str, str]) -> str:
    """``"Iron Guard (iron_guard)"`` — the toolkit's naming rule.

    Unlike a trait, an ancillary's own name IS a text key, so there is no level to
    borrow one from. A text entry whose value is just its own key is a
    placeholder, not a name — the same ruling the buildings editor makes.
    """
    shown = (names.get(anc.name) or "").strip()
    if not shown or shown == anc.name:
        return anc.name
    return f"{shown} ({anc.name})"


def text_tags(anc: Ancillary) -> List[str]:
    """Every ``export_ancillaries.txt`` tag this ancillary names, in order."""
    out: List[str] = []
    for tag in [anc.name, anc.get("Description"), anc.get("EffectsDescription")]:
        if tag and tag not in out:
            out.append(tag)
    return out


def image_path(mod, image: str) -> Optional[Path]:
    """Where an ``Image`` line's file actually is, or ``None``.

    The mod's own folder first, then the game's own ``ui/ancillaries`` if it has
    been unpacked — an ancillary that keeps a stock picture names it without
    shipping it.

    It used to look in ``config.get_vanilla_ui_root()``, which holds *building*
    art and no ancillary picture at all, so the second candidate could never
    match: every stock-picture ancillary came back missing. 56 of Third Age
    Reforged's 345 and 2 of DaC's, all of them fine in game.
    """
    name = (image or "").strip().replace("\\", "/").split("/")[-1]
    if not name:
        return None
    candidates = [Path(mod.data) / IMAGE_DIR / name]
    vanilla = vanilla_images()
    if vanilla is not None:
        candidates.append(vanilla / name)
    for path in candidates:
        try:
            if path.is_file():
                return path
        except OSError:
            continue
    return None


def vanilla_images() -> Optional[Path]:
    """The game's unpacked ``ui/ancillaries``, or ``None`` when there is none.

    ``None`` is the normal answer — vanilla keeps these inside its ``.pack``
    archives — and it means *cannot be checked*, never *the picture is missing*.
    Every caller below branches on it rather than assuming absence is proof.
    """
    try:
        from . import config
        return config.get_vanilla_ancillary_dir()
    except (OSError, ValueError):
        return None


#: What a missing picture means depends on whether vanilla's own copies are
#: visible, so both messages live here rather than being written out twice.
def _image_finding(anc, image: str, checkable: bool) -> Dict:
    return {"kind": "missing-image" if checkable else "unverified-image",
            "ancillary": anc.name,
            "line": anc.lines.get("Image", anc.start) + 1,
            "message": (f"`{image}` is not in {IMAGE_DIR} here or in the game's "
                        "own copies — the character screen shows a blank slot")
            if checkable else
            (f"`{image}` is not in {IMAGE_DIR} here. It is fine if it is one of "
             "the game's own pictures, which stay inside its .pack files — "
             "unpack them and set `vanilla_ancillaries_dir` to have this checked")}


# ---------------------------------------------------------------------------
# what the editor's list and its detail pane are made of


def overview(mod) -> Dict:
    """Every ancillary in the mod, light enough to paint a list of 700 of them."""
    path = Path(mod.eda_path)
    out: Dict = {"mod": getattr(mod, "name", ""), "file": path.name,
                 "exists": path.exists(), "ancillaries": [], "findings": 0}
    if not path.exists():
        out["error"] = f"{getattr(mod, 'name', '?')} has no {path.name}"
        return out
    af = parse_file(path)
    tg = triggers.parse_file(path)
    names = loc(mod)
    out["loc"] = bool(names)
    counted: Dict[str, int] = {}
    grants: Dict[str, int] = {}
    found = check_file(af, tg, mod)
    for finding in found:
        counted[finding["ancillary"]] = counted.get(finding["ancillary"], 0) + 1
    # what the list's banner lists, so "N things to look at" says which N
    out["finding_list"] = [{"name": f.get("ancillary", ""), "kind": f.get("kind", ""),
                            "message": f.get("message", "")} for f in found]
    for trig in tg.triggers:
        for eff in trig.effects:
            if eff.keyword == "AcquireAncillary" and eff.args:
                grants[eff.args[0]] = grants.get(eff.args[0], 0) + 1
    for a in af.ancillaries:
        out["ancillaries"].append({
            "name": a.name, "label": label(a, names), "type": a.get("Type"),
            "image": a.get("Image"), "unique": a.unique,
            "transferable": a.transferable,
            "excluded_ancillaries": a.excluded_ancillaries,
            "effects": len(a.effects),
            "triggers": grants.get(a.name, 0),
            "findings": counted.get(a.name, 0),
            "line": a.start + 1})
    out["count"] = len(af.ancillaries)
    out["findings"] = sum(counted.values())
    out["triggers"] = len(tg.triggers)
    out["types"] = sorted({a.get("Type") for a in af.ancillaries if a.get("Type")})
    return out


def detail(mod, name: str) -> Dict:
    """One ancillary, everything the editor's pane draws."""
    af = parse_file(mod.eda_path)
    anc = af.get(name)
    if anc is None:
        raise KeyError(f"no ancillary {name!r} in {getattr(mod, 'name', '?')}")
    tg = triggers.parse_file(mod.eda_path)
    names = loc(mod)
    block = af.block_text(anc)
    mine = [t for t in tg.triggers
            if any(e.keyword == "AcquireAncillary" and e.args and e.args[0] == name
                   for e in t.effects)]
    art = image_path(mod, anc.get("Image"))
    return {
        "mod": getattr(mod, "name", ""), "name": anc.name,
        "label": label(anc, names), "ancillary": anc.as_dict(), "text": block,
        "fields": [list(f) for f in block_fields(block)], "spans": block_spans(block),
        "loc": {tag: names.get(tag, "") for tag in text_tags(anc)},
        "missing_loc": [tag for tag in text_tags(anc) if tag not in names],
        "has_loc": bool(names),
        "image_found": art is not None,
        "findings": check(anc, set(af.by_name())) + (
            [] if art is not None or not anc.get("Image") else
            [_image_finding(anc, anc.get("Image"), vanilla_images() is not None)]),
        "triggers": [dict(t.as_dict(), text=tg.block_text(t)) for t in mine],
        "known": sorted(af.by_name()),
        "types": sorted({a.get("Type") for a in af.ancillaries if a.get("Type")}),
        "attributes": sorted(triggers.vocab().get("attributes", [])),
    }


# ---------------------------------------------------------------------------
# editing: splices, so untouched lines stay untouched


def render_block(base: str, edits: Optional[Dict] = None) -> str:
    """Apply GUI edits to one ancillary block and give back its text.

    ``edits`` is the save request's own shape — ``{name, type, transferable,
    image, unique, excluded_ancillaries, exclude_cultures, description,
    effects_description, effects: [{attribute, amount}]}`` — and every key is
    optional. What is not named is not touched.
    """
    try:
        return _render_block(base, edits or {})
    except AncillaryError:
        raise
    except kb.BlockError as e:
        raise AncillaryError(e.message, e.line) from None


def _render_block(base: str, edits: Dict) -> str:
    anc = parse_block(base)
    lines, newline, _ = triggers.split_lines(base)
    sp = kb.Splice(lines)

    if "name" in edits:
        name = str(edits["name"] or "").strip()
        if not name:
            raise AncillaryError("an ancillary needs a name", anc.start + 1)
        if name != anc.name:
            sp.replace(anc.start, kb.sub_head(lines[anc.start], ANC_KW, name))

    indent = kb.body_indent(lines, anc.lines, anc.start)
    kb.edit_keys(sp, lines, anc.lines, anc.values, edits, _KEY_FIELD,
                 order=BODY_ORDER, required=REQUIRED, flags=FLAGS,
                 list_keys=LIST_KEYS, anchor=anc.start, indent=indent,
                 noun="ancillary")
    if "effects" in edits:
        kb.edit_effects(sp, lines, anc.effects, list(edits["effects"] or []),
                        indent, anc.end - 1)
    return newline.join(sp.result())


def new_block(edits: Dict) -> str:
    """A whole ancillary block written from scratch, in the order the engine wants."""
    name = str(edits.get("name") or "").strip()
    if not name:
        raise AncillaryError("a new ancillary needs a name")
    values = dict(edits)
    values.setdefault("type", "item")
    values.setdefault("transferable", "1")
    values.setdefault("image", f"{name}.tga")
    values.setdefault("description", f"{name}_desc")
    values.setdefault("effects_description", f"{name}_effects_desc")
    return "\n".join(
        [f"{ANC_KW} {name}"]
        + kb.new_lines(values, _KEY_FIELD, BODY_ORDER, FLAGS, LIST_KEYS, "    "))


def replace_block(af: AncillaryFile, anc: Ancillary, block: str) -> str:
    """The whole file with one ancillary's lines swapped for ``block``."""
    body, _, _ = triggers.split_lines(block)
    while body and not body[-1].strip():
        body.pop()
    lines = list(af.lines)
    lines[anc.start:anc.end] = body
    out = af.newline.join(lines)
    return out + af.newline if af.trailing_newline and lines else out


# ---------------------------------------------------------------------------
# spans, for the Code View widget


def block_spans(block: str) -> Dict[str, List[List[int]]]:
    """``{label: [[first, last]]}``, 1-based, for one ancillary block."""
    anc = parse_block(block if block.endswith("\n") else block + "\n")
    spans: Dict[str, List[List[int]]] = {"name": [[anc.start + 1, anc.start + 1]]}
    for key, line in anc.lines.items():
        spans[_KEY_FIELD.get(key, key.lower())] = [[line + 1, line + 1]]
    for n, eff in enumerate(anc.effects, 1):
        spans[f"effect#{n}"] = [[eff.line + 1, eff.line + 1]]
    return spans


def block_fields(block: str) -> List[Tuple[str, str]]:
    """``[(label, value)]`` for one block, in the order the lines appear."""
    anc = parse_block(block if block.endswith("\n") else block + "\n")
    out = [("name", anc.name)]
    for key, _ in sorted(anc.lines.items(), key=lambda kv: kv[1]):
        out.append((_KEY_FIELD.get(key, key.lower()),
                    "yes" if key in FLAGS else anc.values.get(key, "")))
    for n, eff in enumerate(anc.effects, 1):
        out.append((f"effect#{n}", f"{eff.attribute} {eff.amount}"))
    return out


# ---------------------------------------------------------------------------
# plan -> apply
#
# The same three-things-at-once save the traits editor makes, for the same
# reason: the ancillary block, the triggers that grant it (below it in the same
# file) and the export_ancillaries.txt keys it names all fail together.


@dataclass
class AncillaryPlan:
    mod: object = None
    action: str = "edit"                 # 'edit' | 'add' | 'delete'
    name: str = ""
    changes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    findings: List[Dict] = field(default_factory=list)
    #: the whole EDA as it would be written — empty when nothing would change
    text: str = ""
    block: str = ""
    #: ``{tag: text}`` this save would write into export_ancillaries.txt
    loc_writes: Dict[str, str] = field(default_factory=dict)
    loc_new: List[str] = field(default_factory=list)

    def summary(self) -> str:
        head = (f"{self.action} ancillary {self.name} in "
                f"{getattr(self.mod, 'name', '?')} ({len(self.changes)} change(s))")
        return "\n".join([head] + [f"  {c}" for c in self.changes])

    def payload(self) -> Dict:
        return {"action": self.action, "name": self.name,
                "changes": list(self.changes), "warnings": list(self.warnings),
                "errors": list(self.errors), "findings": list(self.findings),
                "block": self.block, "loc_writes": dict(self.loc_writes),
                "loc_new": list(self.loc_new),
                "ok": not self.errors and bool(self.text or self.loc_writes)}


def plan(mod, body: dict) -> AncillaryPlan:
    """Work out the whole new EDA for one save, without touching the disk.

    ``body`` is ``{ancillary, action, edits, raw_block, loc, triggers: {edits,
    adds, removes}, write_loc}`` — the traits editor's request shape with one
    word changed, because the two editors are the same editor.
    """
    p = AncillaryPlan(mod=mod, action=str(body.get("action") or "edit"),
                      name=str(body.get("ancillary") or "").strip())
    path = Path(mod.eda_path)
    if not path.exists():
        p.errors.append(f"{getattr(mod, 'name', '?')} has no {path.name}")
        return p
    original = kb.read_text(path, ENCODING)
    try:
        text = _plan_block(p, original, body)
        text = _plan_triggers(p, text, body)
    except (AncillaryError, triggers.TriggerError) as e:
        p.errors.append(e.message)
        return p
    if p.errors:
        return p

    af = parse_text(text)
    anc = af.get(p.name)
    if anc is not None:
        p.block = af.block_text(anc)
        p.findings = check(anc, set(af.by_name()))
        if body.get("write_loc", True):
            _plan_loc(p, mod, anc, dict(body.get("loc") or {}))
    p.text = "" if text == original else text
    if not p.text and not p.loc_writes and not p.errors:
        p.warnings.append("nothing to change")
    return p


def _plan_block(p: AncillaryPlan, text: str, body: dict) -> str:
    """The EDA with this one ancillary added, edited or removed."""
    af = parse_text(text)
    if p.action == "add":
        if not p.name:
            raise AncillaryError("a new ancillary needs a name")
        if af.get(p.name) is not None:
            p.errors.append(f"{p.name} is already an ancillary in this file")
            return text
        block = str(body.get("raw_block") or "").strip("\r\n") or new_block(
            dict(body.get("edits") or {}, name=p.name))
        parse_block(block + "\n")            # refuse a block that is not one
        p.changes.append(f"+ Ancillary {p.name}")
        lines = list(af.lines)
        at = (af.ancillaries[-1].end if af.ancillaries
              else (af.trigger_start if af.trigger_start >= 0 else len(lines)))
        body_lines = [ln[:-1] if ln.endswith("\r") else ln for ln in block.split("\n")]
        lines[at:at] = [""] + body_lines
        out = af.newline.join(lines)
        return out + af.newline if af.trailing_newline and lines else out

    anc = af.get(p.name)
    if anc is None:
        p.errors.append(f"{p.name} is not an ancillary in this file")
        return text

    if p.action == "delete":
        p.changes.append(f"- Ancillary {p.name}")
        lines = list(af.lines)
        del lines[anc.start:anc.end]
        out = af.newline.join(lines)
        return out + af.newline if af.trailing_newline and lines else out

    base = af.block_text(anc)
    raw = body.get("raw_block")
    if raw is not None and str(raw).strip():
        block = str(raw).strip("\r\n")
        if parse_block(block + "\n").name != p.name:
            raise AncillaryError(
                f"this ancillary is `{p.name}` — renaming it here would orphan "
                "every trigger, exclusion list, starting character and text entry "
                "that names it")
    else:
        block = render_block(base, dict(body.get("edits") or {}))
    if block == base:
        return text
    p.changes.extend(kb.diff(base, block))
    return replace_block(af, anc, block)


def _plan_triggers(p: AncillaryPlan, text: str, body: dict) -> str:
    """The trigger half of an ancillary save, and the cleanup a delete owes it.

    ``AcquireAncillary`` is EDA's ``Affects``: a trigger left granting an
    ancillary this file no longer defines is an errorless crash when it fires.
    """
    req = dict(body.get("triggers") or {})
    if p.action == "delete":
        req["removes"] = list(req.get("removes") or []) + triggers.orphaned_by(
            text, "AcquireAncillary", p.name)
    text = triggers.edit_section(text, req, p.changes, p.warnings, p.errors)
    if p.action == "delete":
        text, dropped = triggers.strip_effect_lines(text, "AcquireAncillary", p.name)
        if dropped:
            p.changes.append(f"- {dropped} `AcquireAncillary {p.name}` line(s) from "
                             "triggers that grant other ancillaries too")
    return text


def _plan_loc(p: AncillaryPlan, mod, anc: Ancillary, wanted: Dict) -> None:
    """What this save would write into ``export_ancillaries.txt``.

    The keys the ancillary needs and the mod has not got — missing one is the
    guide's errorless CTD the moment anybody acquires it — plus any wording the
    user retyped, since what an ancillary says on screen is part of it.
    """
    from . import stringsbin
    have = loc(mod)
    txt = Path(mod.data) / LOC_REL
    if not txt.exists() and not stringsbin.bin_path_for(txt).exists():
        p.warnings.append(f"this mod has no {txt.name}, so its text key(s) could "
                          "not be written — it will show its tags in game")
        return
    for tag in text_tags(anc):
        want = str(wanted.get(tag, "")).strip() if wanted else ""
        if tag not in have:
            p.loc_writes[tag] = want or tag
            p.loc_new.append(tag)
        elif want and want != have[tag]:
            p.loc_writes[tag] = want
    if p.loc_new:
        p.changes.append(f"+ {len(p.loc_new)} new text key(s) in {txt.name}")
    reworded = len(p.loc_writes) - len(p.loc_new)
    if reworded:
        p.changes.append(f"~ {reworded} text(s) rewritten in {txt.name}")


def apply(p: AncillaryPlan) -> Dict:
    """Write a planned save, with the same backups and undo as any other job."""
    import shutil
    import time

    from . import cleaner, config, stringsbin
    from .logutil import file_op, log

    if p.errors:
        raise ValueError("cannot apply: " + "; ".join(p.errors))
    if not p.text and not p.loc_writes:
        raise ValueError("nothing to change")
    mod = p.mod
    tid = config.new_transfer_id()
    backup_root = config.backup_root_for(tid)
    manifest: Dict[str, List[str]] = {"backed_up": [], "created": []}
    out: Dict = {"id": tid, "ancillary": p.name}

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
        target = keep(Path(mod.eda_path).name)
        kb.write_text(target, p.text, ENCODING)
        file_op("WRITE", target, f"{len(p.text)} bytes")
    if p.loc_writes:
        txt = Path(mod.data) / LOC_REL
        if txt.exists():
            target = keep(LOC_REL)
            # the compiled cache is rewritten below, so it is backed up too — an
            # undo that restored the .txt and left the .bin would put the file
            # back and leave the game still reading the new text
            keep(LOC_REL + ".strings.bin")
            kb.write_text(target,
                          stringsbin.upsert_txt(kb.read_text(target, "utf-16"),
                                                p.loc_writes),
                          "utf-16")
            file_op("WRITE", target, f"{len(p.loc_writes)} text key(s)")
            res = cleaner.refresh_strings_bin(mod.root, LOC_BIN_REL)
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
        "mode": "ancillaries",
        "action": p.action,
        "source": mod.name, "source_root": str(mod.root),
        "dest": mod.name, "dest_root": str(mod.root),
        "unit_type": p.name, "resolved_type": p.name,
        "options": {}, "applied": True, "undone": False, "note": "",
        "summary": p.summary(), "warnings": list(p.warnings),
        "manifest": manifest, "backup_root": str(backup_root),
    }
    config.append_log(rec)
    log.info("ANC    %s %s in %s — %d change(s), id=%s",
             p.action, p.name, mod.name, len(p.changes), tid)
    out["record"] = rec
    return out
