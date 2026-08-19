"""The trait definitions of ``export_descr_character_traits.txt``.

An EDCT is two files in one. The bottom half is the trigger language, which
:mod:`unittransfer.triggers` owns. The top half — this module — is the traits
themselves: what each one is called, who can get it, which cultures cannot, and
the ladder of levels a character climbs as points accumulate::

    Trait NaturalMilitarySkill
      Characters family
      Hidden
      ExcludeCultures southern_european, greek
      NoGoingBackLevel 2
      AntiTraits Coward

      Level GoodCommander
        Description GoodCommander_desc
        EffectsDescription GoodCommander_effects_desc
        GainMessage GoodCommander_gain_desc
        Epithet GoodCommander_epithet_desc
        Threshold 4

        Effect Command 1
        Effect TroopMorale 1

Both halves are held as the same list of lines: a trait's ``Affects`` line lives
in the trigger section and its levels live here, so the two parsers count lines
from the same place and a splice from either one lands where it was aimed.

Four things this format does that a naive reader gets wrong, all of them from
Squid's EDCT/EDA guide (``Reference/TWCenter/``) and confirmed against the 1457
traits in the three installed mods:

**The header's line order is load-bearing.** ``Characters`` must be the line
directly under ``Trait``, and the optional lines that follow have a fixed order
too. Get it wrong and the game does not report a bad trait — it stops
recognising every trait defined *after* it, and the crash surfaces hundreds of
lines away at the first condition that names one. So a header line this module
adds is inserted at its canonical position, never appended.

**A key can be absent, and absent is not empty.** ``Hidden`` is the whole line;
``GainMessage`` missing means no message; a level with no ``Effect`` lines is
normal. Editing an optional field to nothing therefore *deletes* its line rather
than writing a keyword with nothing after it.

**The required lines are required.** ``Characters`` on a trait and
``Description`` / ``EffectsDescription`` / ``Threshold`` on a level are CTDs when
missing, so blanking one is refused here rather than written and discovered in
game.

**Names here are keys somewhere else.** Level names and the four description
fields are tags in ``data/text/export_VnVs.txt``; the trait name is a key in the
trigger section's ``Affects`` lines, in ``AntiTraits`` lists, in EDA conditions
and in ``descr_strat``. :func:`check` is where that shows up: it reads both
halves of the file and says which of those references point at nothing.

As in :mod:`unittransfer.triggers`, **lines are kept verbatim and every edit is a
splice** — ``parse_text(t).text() == t`` for every file, always.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import keyblock as kb
from . import triggers

#: EDCT is plain 8-bit text; the game reads it as Latin-1 (same as the triggers)
ENCODING = triggers.ENCODING

TRAIT_KW = "Trait"
LEVEL_KW = "Level"

#: the optional header lines, **in the order the engine demands** — see the
#: module docstring. ``Characters`` is not in here because it is not optional.
HEADER_ORDER = ("Hidden", "ExcludeCultures", "NoGoingBackLevel", "AntiTraits")

#: a level's lines, in the order the guide's sample writes them. ``Effect`` lines
#: come after all of these, and there may be any number of them.
LEVEL_ORDER = ("Description", "EffectsDescription", "GainMessage", "LoseMessage",
               "Epithet", "Threshold")

#: keys whose value is a comma-separated list rather than one word
LIST_KEYS = ("ExcludeCultures", "AntiTraits", "Characters")

#: hardcoded engine limits (Squid's guide; the antitrait limit is 10 in RTW 1.2
#: and 20 from 1.5 on, and M2TW inherits the later one)
MAX_LEVELS = 9
MAX_ANTITRAITS = 20

#: the character types a trait can be given to
CHARACTER_TYPES = ("spy", "assassin", "diplomat", "admiral", "family", "priest",
                   "merchant", "princess", "heretic", "witch", "inquisitor", "all")

#: where the localised name of a trait level and its descriptions come from,
#: relative to ``data/`` — and the compiled cache beside it, which
#: :mod:`unittransfer.cleaner` addresses from the mod root instead
VNV_REL = "text/export_VnVs.txt"
VNV_BIN_REL = "data/" + VNV_REL + ".strings.bin"

#: field name in an edit request -> the keyword it writes
_TRAIT_FIELDS = {"characters": "Characters", "hidden": "Hidden",
                 "exclude_cultures": "ExcludeCultures",
                 "no_going_back_level": "NoGoingBackLevel",
                 "anti_traits": "AntiTraits"}
_LEVEL_FIELDS = {"description": "Description",
                 "effects_description": "EffectsDescription",
                 "gain_message": "GainMessage", "lose_message": "LoseMessage",
                 "epithet": "Epithet", "threshold": "Threshold"}
_KEY_FIELD = {v: k for k, v in _TRAIT_FIELDS.items()}
_KEY_FIELD.update({v: k for k, v in _LEVEL_FIELDS.items()})


class TraitError(kb.BlockError):
    """The text is not a trait block, or an edit would write a file the game rejects."""


# ---------------------------------------------------------------------------
# the parsed shapes


@dataclass
class Effect:
    """``Effect Command 1`` — one attribute this level changes."""
    attribute: str = ""
    amount: str = ""            # kept as written: "-1", "50", "+2" all occur
    line: int = 0

    def as_dict(self) -> Dict:
        return {"attribute": self.attribute, "amount": self.amount, "line": self.line}


@dataclass
class Level:
    """One rung of a trait: a threshold, some text keys and any effects."""
    name: str = ""
    values: Dict[str, str] = field(default_factory=dict)   # keyword -> value
    lines: Dict[str, int] = field(default_factory=dict)    # keyword -> 0-based line
    effects: List[Effect] = field(default_factory=list)
    start: int = 0              # 0-based line of the `Level` line
    end: int = 0                # 0-based line AFTER the level's last code line

    def get(self, key: str) -> str:
        return self.values.get(key, "")

    @property
    def threshold(self) -> str:
        return self.get("Threshold")

    def as_dict(self) -> Dict:
        d = {"name": self.name, "start": self.start, "end": self.end,
             "effects": [e.as_dict() for e in self.effects]}
        for key, fieldname in _LEVEL_FIELDS.items():
            d[key] = self.values.get(fieldname, "")
        return d


@dataclass
class Trait:
    """One ``Trait`` block: the header, then zero to nine levels."""
    name: str = ""
    values: Dict[str, str] = field(default_factory=dict)   # keyword -> value
    lines: Dict[str, int] = field(default_factory=dict)    # keyword -> 0-based line
    levels: List[Level] = field(default_factory=list)
    start: int = 0
    end: int = 0
    warnings: List[str] = field(default_factory=list)

    @property
    def hidden(self) -> bool:
        return "Hidden" in self.lines

    @property
    def characters(self) -> List[str]:
        return kb.split_list(self.values.get("Characters", ""))

    @property
    def exclude_cultures(self) -> List[str]:
        return kb.split_list(self.values.get("ExcludeCultures", ""))

    @property
    def anti_traits(self) -> List[str]:
        return kb.split_list(self.values.get("AntiTraits", ""))

    def as_dict(self) -> Dict:
        return {"name": self.name, "start": self.start, "end": self.end,
                "characters": self.characters, "hidden": self.hidden,
                "exclude_cultures": self.exclude_cultures,
                "no_going_back_level": self.values.get("NoGoingBackLevel", ""),
                "anti_traits": self.anti_traits,
                "levels": [lv.as_dict() for lv in self.levels],
                "warnings": list(self.warnings)}


@dataclass
class TraitFile:
    """A whole EDCT, held as its own lines with the traits indexed into it."""
    lines: List[str] = field(default_factory=list)
    newline: str = "\r\n"
    traits: List[Trait] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    trailing_newline: bool = True
    #: 0-based line of the first ``Trigger`` — where the other half starts, and
    #: the line a brand-new trait has to be inserted above
    trigger_start: int = -1

    def text(self) -> str:
        """The file exactly as it was read — the property everything else rests on."""
        out = self.newline.join(self.lines)
        return out + self.newline if self.trailing_newline and self.lines else out

    def get(self, name: str) -> Optional[Trait]:
        return next((t for t in self.traits if t.name == name), None)

    def by_name(self) -> Dict[str, Trait]:
        return {t.name: t for t in self.traits}

    def block_text(self, trait: Trait) -> str:
        return self.newline.join(self.lines[trait.start:trait.end])


# ---------------------------------------------------------------------------
# parsing


def _code(line: str) -> str:
    return line.split(";", 1)[0].strip()


def parse_text(text: str) -> TraitFile:
    """Read a whole EDCT. Never raises: anything odd becomes a warning.

    Only the *definition* half is interpreted. The trigger section below it is
    carried as lines and belongs to :mod:`unittransfer.triggers`, which reads the
    same file the other way round.
    """
    lines, newline, trailing = triggers.split_lines(text)
    tf = TraitFile(lines=lines, newline=newline, trailing_newline=trailing)

    cur: Optional[Trait] = None
    lvl: Optional[Level] = None
    for i, raw in enumerate(lines):
        code = kb.code_of(raw)
        if not code:
            continue
        words = code.split()
        head = words[0]
        value = code[len(head):].strip()

        if head == TRAIT_KW:
            cur = Trait(name=words[1] if len(words) > 1 else "", start=i, end=i + 1)
            lvl = None
            if not cur.name:
                cur.warnings.append(f"line {i + 1}: this Trait has no name")
            tf.traits.append(cur)
            continue
        if head == triggers.TRIGGER_KW:
            # the trigger section: this half of the file is over
            if tf.trigger_start < 0:
                tf.trigger_start = i
            cur, lvl = None, None
            continue
        if cur is None:
            continue

        if head == LEVEL_KW:
            if len(cur.levels) >= MAX_LEVELS:
                cur.warnings.append(
                    f"line {i + 1}: level {len(cur.levels) + 1} — a trait can have "
                    f"at most {MAX_LEVELS}")
            lvl = Level(name=words[1] if len(words) > 1 else "", start=i, end=i + 1)
            cur.levels.append(lvl)
            cur.end = i + 1
            continue
        if head == "Effect":
            if lvl is None:
                cur.warnings.append(f"line {i + 1}: an Effect outside any Level")
                continue
            lvl.effects.append(Effect(attribute=words[1] if len(words) > 1 else "",
                                      amount=words[2] if len(words) > 2 else "",
                                      line=i))
            lvl.end = cur.end = i + 1
            continue

        target = lvl if lvl is not None else cur
        known = LEVEL_ORDER if lvl is not None else ("Characters",) + HEADER_ORDER
        if head not in known:
            cur.warnings.append(
                f"line {i + 1}: `{head}` is not a "
                f"{'level' if lvl is not None else 'trait header'} line")
        if head in target.lines:
            cur.warnings.append(f"line {i + 1}: a second `{head}` line")
        target.values[head] = value
        target.lines[head] = i
        if lvl is not None:
            lvl.end = i + 1
        cur.end = i + 1

    for t in tf.traits:
        tf.warnings.extend(f"{t.name or '(unnamed)'}: {w}" for w in t.warnings)
    return tf


def parse_file(path: str | Path) -> TraitFile:
    return parse_text(kb.read_text(Path(path), ENCODING))


def parse_block(text: str) -> Trait:
    """Read ONE trait block, as the code view's pane holds it.

    Raises :class:`TraitError` rather than warning: a pane that edits one record
    must not quietly accept text holding two, or none.
    """
    tf = parse_text(text if text.endswith("\n") else text + "\n")
    if not tf.traits:
        raise TraitError("a trait block starts with a `Trait <name>` line — "
                         "this text has none", 1)
    if len(tf.traits) > 1:
        raise TraitError(
            f"this text holds {len(tf.traits)} trait blocks — one at a time",
            tf.traits[1].start + 1)
    if tf.trigger_start >= 0:
        raise TraitError("there is a `Trigger` block in this text — the trigger "
                         "section is edited on its own", tf.trigger_start + 1)
    return tf.traits[0]


# ---------------------------------------------------------------------------
# what is wrong with a trait that still parses


def check(trait: Trait, known: Optional[set] = None) -> List[Dict]:
    """Findings for one trait: what the engine will refuse, and what will not work.

    ``known`` is every trait name defined in the file, which is what makes an
    ``AntiTraits`` line checkable — the engine does not validate that list, so a
    misspelt antitrait loads happily and simply never cancels anything.
    """
    out: List[Dict] = []

    def add(kind: str, line: int, message: str) -> None:
        out.append({"kind": kind, "trait": trait.name, "line": line + 1,
                    "message": message})

    chars_line = trait.lines.get("Characters", -1)
    if chars_line < 0:
        add("no-characters", trait.start,
            "this trait has no `Characters` line — the game stops loading the file "
            "here with \"Unknown identifier ... when expecting characters\"")
    else:
        above = [k for k, ln in trait.lines.items() if ln < chars_line]
        if above:
            add("header-order", chars_line,
                f"`Characters` must be the line under `Trait`, but {kb.and_list(above)} "
                "sits above it — the engine then stops recognising every trait "
                "defined after this one, and crashes at whatever names one first")
        wrong = [c for c in trait.characters if c not in CHARACTER_TYPES]
        if wrong:
            add("unknown-character-type", chars_line,
                f"{kb.and_list(wrong)} is not a character type")
        if len(trait.characters) > 1:
            add("characters-list", chars_line,
                "the engine reads only the first type in a `Characters` list, so "
                f"only {trait.characters[0]} can ever get this trait — use `all` "
                "and a condition in the trigger, or one trait per type")

    order = [k for k in HEADER_ORDER if k in trait.lines]
    placed = sorted(order, key=lambda k: trait.lines[k])
    if order != placed:
        add("header-order", trait.lines[placed[0]],
            "the header lines are in the order " + ", ".join(placed) + " but the "
            "engine requires " + ", ".join(order))

    if len(trait.levels) > MAX_LEVELS:
        add("too-many-levels", trait.levels[MAX_LEVELS].start,
            f"level {MAX_LEVELS + 1} — a trait can have at most {MAX_LEVELS}")
    if not trait.levels and not trait.hidden:
        add("no-levels", trait.start,
            "a trait with no levels can never be seen or acquired; if that is "
            "deliberate (a counterweight for an antitrait) mark it `Hidden`")

    anti = trait.anti_traits
    if len(anti) > MAX_ANTITRAITS:
        add("too-many-antitraits", trait.lines["AntiTraits"],
            f"{len(anti)} antitraits — more than {MAX_ANTITRAITS} crashes the game")
    if known is not None:
        for name in anti:
            if name not in known:
                add("unknown-antitrait", trait.lines["AntiTraits"],
                    f"`{name}` is not a trait this file defines — the engine does "
                    "not check antitrait names, so this one simply never cancels "
                    "anything")
    if trait.name in anti:
        add("self-antitrait", trait.lines["AntiTraits"],
            "a trait cannot be its own antitrait")

    attrs = _attributes()
    seen_thresholds: List[int] = []
    for n, lv in enumerate(trait.levels, 1):
        if not lv.name:
            add("no-level-name", lv.start, f"level {n} has no name")
        for key in ("Description", "EffectsDescription", "Threshold"):
            if key not in lv.lines:
                add("missing-level-line", lv.start,
                    f"level {n} ({lv.name or '?'}) has no `{key}` line — a "
                    "character who reaches it crashes the character detail screen")
        t = lv.threshold
        if t:
            try:
                n_points = int(t)
            except ValueError:
                add("bad-threshold", lv.lines["Threshold"],
                    f"`{t}` is not a whole number of trait points")
            else:
                if n_points < 1:
                    add("bad-threshold", lv.lines["Threshold"],
                        f"a threshold of {n_points} — the hardcoded minimum is 1")
                elif seen_thresholds and n_points <= seen_thresholds[-1]:
                    add("unreachable-level", lv.lines["Threshold"],
                        f"level {n} needs {n_points} points, which level {n - 1} "
                        f"already reached at {seen_thresholds[-1]} — the game shows "
                        "the highest level whose threshold is met, so this one "
                        "never appears")
                seen_thresholds.append(n_points)
        for eff in lv.effects:
            if not _known_attribute(eff.attribute, attrs):
                add("unknown-attribute", eff.line,
                    f"`{eff.attribute}` is not a character attribute")
            elif not kb.is_int(eff.amount):
                add("bad-effect-amount", eff.line,
                    f"`{eff.amount}` is not a whole number of points")
    return out


def check_file(tf: TraitFile, trigger_file=None) -> List[Dict]:
    """Every finding in the file, including the ones only both halves can see.

    A trait name is a key the trigger section spends thousands of lines pointing
    at, and an ``Affects`` line naming a trait that does not exist is a CTD with
    a message about a line far from the mistake. Reading the definitions and the
    triggers together is the only way to catch that before the game does.
    """
    known = {t.name for t in tf.traits if t.name}
    out: List[Dict] = []

    seen: Dict[str, int] = {}
    for t in tf.traits:
        if t.name in seen:
            out.append({"kind": "duplicate-trait", "trait": t.name,
                        "line": t.start + 1,
                        "message": f"`{t.name}` is already defined on line "
                                   f"{seen[t.name] + 1} — trait names must be unique"})
        else:
            seen[t.name] = t.start
        out.extend(check(t, known))

    if trigger_file is None:
        return out
    for trig in trigger_file.triggers:
        for eff in trig.effects:
            if eff.keyword != "Affects" or not eff.args:
                continue
            if eff.args[0] not in known:
                out.append({"kind": "unknown-affects", "trait": eff.args[0],
                            "line": eff.line + 1,
                            "message": f"trigger `{trig.name}` affects `{eff.args[0]}`, "
                                       "which this file does not define — the points "
                                       "go nowhere, and the game reports \"Trait not "
                                       "recognized\""})
    return out


def _attributes() -> set:
    return set(triggers.vocab().get("attributes", []))


def _known_attribute(name: str, attrs: set) -> bool:
    """Is this a character attribute? The two parameterised families are prefixes.

    ``Combat_V_Faction_FactionName`` and ``Combat_V_Religion_ReligionName`` stand
    for one attribute per faction and per religion in the mod, which is why they
    cannot be matched literally.
    """
    if not attrs or name in attrs:
        return True
    for stem in ("Combat_V_Faction_", "Combat_V_Religion_"):
        if name.startswith(stem) and len(name) > len(stem):
            return True
    return False


# ---------------------------------------------------------------------------
# localisation: the level names and descriptions live in export_VnVs.txt


def loc(mod) -> Dict[str, str]:
    """``{tag: text}`` from the mod's ``export_VnVs.txt``, or its compiled archive.

    Every level name, description, effects description, gain and lose message and
    epithet in an EDCT is a tag in this one file, flat — no ``_descr`` pairing
    like the unit file has, so it is read as plain pairs rather than through
    :class:`~unittransfer.localization.Localization`. A mod that ships only the
    compiled ``.strings.bin`` still gets real names, through Phase 6's codec.
    """
    from . import stringsbin
    path = Path(getattr(mod, "data", "")) / VNV_REL
    try:
        if path.exists():
            return dict(stringsbin.from_txt(kb.read_text(path, "utf-16")))
    except (OSError, UnicodeError, ValueError):
        pass
    try:
        return stringsbin.load_pairs(stringsbin.bin_path_for(path))
    except (OSError, ValueError):
        return {}


def label(trait: Trait, names: Dict[str, str]) -> str:
    """``"Good Commander (NaturalMilitarySkill)"`` — the toolkit's naming rule.

    A trait has no name of its own: what the player reads is the name of whatever
    level they have reached, so the first level's name is the honest label.
    """
    tag = trait.levels[0].name if trait.levels else ""
    shown = (names.get(tag) or "").strip()
    # a text entry whose value is just its own key is a placeholder, not a name —
    # the same ruling the buildings editor makes about a shared key
    if not shown or shown == tag:
        return trait.name
    return f"{shown} ({trait.name})"


def text_tags(trait: Trait) -> List[str]:
    """Every ``export_VnVs.txt`` tag this trait's levels name, in order.

    All five level fields are keys in that file, and a character who reaches a
    level whose key is missing crashes the character detail screen — so this is
    the list a save has to make sure exists.
    """
    out: List[str] = []
    for lv in trait.levels:
        for tag in [lv.name] + [lv.values.get(k, "")
                                for k in ("Description", "EffectsDescription",
                                          "GainMessage", "LoseMessage", "Epithet")]:
            if tag and tag not in out:
                out.append(tag)
    return out


# ---------------------------------------------------------------------------
# what the editor's list and its detail pane are made of


def overview(mod) -> Dict:
    """Every trait in the mod, light enough to paint a list of 800 of them."""
    path = Path(mod.edct_path)
    out: Dict = {"mod": getattr(mod, "name", ""), "file": path.name,
                 "exists": path.exists(), "traits": [], "findings": 0}
    if not path.exists():
        out["error"] = f"{getattr(mod, 'name', '?')} has no {path.name}"
        return out
    tf = parse_file(path)
    tg = triggers.parse_file(path)
    names = loc(mod)
    out["vnv"] = bool(names)
    counted: Dict[str, int] = {}
    gives: Dict[str, int] = {}
    found = check_file(tf, tg)
    for finding in found:
        counted[finding["trait"]] = counted.get(finding["trait"], 0) + 1
    # The list's banner used to say "14 things to look at" and nothing else, so
    # the only way to find out WHAT was to open 1457 traits one at a time.
    out["finding_list"] = [{"name": f.get("trait", ""), "kind": f.get("kind", ""),
                            "message": f.get("message", "")} for f in found]
    for trig in tg.triggers:
        for eff in trig.effects:
            if eff.keyword == "Affects" and eff.args:
                gives[eff.args[0]] = gives.get(eff.args[0], 0) + 1
    for t in tf.traits:
        out["traits"].append({
            "name": t.name, "label": label(t, names),
            "characters": t.characters, "hidden": t.hidden,
            "levels": len(t.levels),
            "thresholds": [lv.threshold for lv in t.levels],
            "effects": sum(len(lv.effects) for lv in t.levels),
            "anti_traits": t.anti_traits,
            "triggers": gives.get(t.name, 0),
            "findings": counted.get(t.name, 0),
            "line": t.start + 1})
    out["count"] = len(tf.traits)
    out["findings"] = sum(counted.values())
    out["triggers"] = len(tg.triggers)
    return out


def detail(mod, name: str) -> Dict:
    """One trait, everything the editor's pane draws: fields, text, triggers, text keys.

    The triggers come with it because they are the half of a trait nobody can
    read off the definition: the block above says what the trait *is*, and the
    triggers hundreds of lines below say how anyone ever gets it.
    """
    tf = parse_file(mod.edct_path)
    trait = tf.get(name)
    if trait is None:
        raise KeyError(f"no trait {name!r} in {getattr(mod, 'name', '?')}")
    tg = triggers.parse_file(mod.edct_path)
    names = loc(mod)
    block = tf.block_text(trait)
    mine = [t for t in tg.triggers
            if any(e.keyword == "Affects" and e.args and e.args[0] == name
                   for e in t.effects)]
    return {
        "mod": getattr(mod, "name", ""), "name": trait.name,
        "label": label(trait, names), "trait": trait.as_dict(), "text": block,
        "fields": [list(f) for f in block_fields(block)], "spans": block_spans(block),
        "loc": {tag: names.get(tag, "") for tag in text_tags(trait)},
        "missing_loc": [tag for tag in text_tags(trait) if tag not in names],
        "has_vnv": bool(names),
        "findings": check(trait, set(tf.by_name())),
        "triggers": [dict(t.as_dict(), text=tg.block_text(t)) for t in mine],
        "known": sorted(tf.by_name()),
        "attributes": sorted(triggers.vocab().get("attributes", [])),
        "character_types": list(CHARACTER_TYPES),
    }


# ---------------------------------------------------------------------------
# editing: splices, so untouched lines stay untouched


def render_block(base: str, edits: Optional[Dict] = None) -> str:
    """Apply GUI edits to one trait block and give back its text.

    ``edits`` is the save request's own shape — ``{name, characters, hidden,
    exclude_cultures, no_going_back_level, anti_traits, levels: [{name,
    description, effects_description, gain_message, lose_message, epithet,
    threshold, effects: [{attribute, amount}]}]}`` — and every key is optional at
    every depth. What is not named is not touched, right down to the comment
    banner between two levels.

    An optional field set to nothing deletes its line. A required one set to
    nothing raises :class:`TraitError`, because the alternative is writing a file
    that stops the game loading.
    """
    try:
        return _render_block(base, edits or {})
    except TraitError:
        raise
    except kb.BlockError as e:
        # the shared splice speaks BlockError; this module's callers only ever
        # need to know about TraitError
        raise TraitError(e.message, e.line) from None


def _render_block(base: str, edits: Dict) -> str:
    trait = parse_block(base)
    lines, newline, _ = triggers.split_lines(base)
    sp = kb.Splice(lines)

    if "name" in edits:
        name = str(edits["name"] or "").strip()
        if not name:
            raise TraitError("a trait needs a name", trait.start + 1)
        if name != trait.name:
            sp.replace(trait.start, kb.sub_head(lines[trait.start], TRAIT_KW, name))

    kb.edit_keys(sp, lines, trait.lines, trait.values, edits, _KEY_FIELD,
                 order=("Characters",) + HEADER_ORDER, required=("Characters",),
                 flags=("Hidden",), list_keys=LIST_KEYS, anchor=trait.start,
                 indent=kb.body_indent(lines, trait.lines, trait.start), noun="trait")

    if "levels" in edits:
        _edit_levels(sp, lines, trait, list(edits["levels"] or []))
    return newline.join(sp.result())


def _edit_levels(sp: kb.Splice, lines: List[str], trait: Trait, wanted: List[Dict]) -> None:
    """Rewrite the levels in place; add or drop whole blocks only where needed."""
    old = trait.levels
    for i in range(min(len(old), len(wanted))):
        _edit_level(sp, lines, old[i], wanted[i] or {})

    if len(wanted) > len(old):
        last = old[-1] if old else None
        lvl_indent = kb.indent_of(lines[last.start]) if last else "  "
        body_indent = (kb.body_indent(lines, last.lines, last.start) if last
                       else lvl_indent + "  ")
        anchor = (last.end - 1) if last else max(
            [trait.start] + list(trait.lines.values()))
        block: List[str] = []
        for w in wanted[len(old):]:
            block.append("")
            block.extend(_new_level(w or {}, lvl_indent, body_indent))
        sp.after(anchor, block)
    elif len(wanted) < len(old):
        for lv in old[len(wanted):]:
            for i in range(lv.start, lv.end):
                sp.drop(i)


def _edit_level(sp: kb.Splice, lines: List[str], lv: Level, w: Dict) -> None:
    if "name" in w:
        name = str(w["name"] or "").strip()
        if not name:
            raise TraitError("a level needs a name", lv.start + 1)
        if name != lv.name:
            sp.replace(lv.start, kb.sub_head(lines[lv.start], LEVEL_KW, name))
    indent = kb.body_indent(lines, lv.lines, lv.start)
    kb.edit_keys(sp, lines, lv.lines, lv.values, w, _KEY_FIELD, order=LEVEL_ORDER,
                 required=("Description", "EffectsDescription", "Threshold"),
                 flags=(), list_keys=LIST_KEYS, anchor=lv.start, indent=indent,
                 noun="level")
    if "effects" in w:
        kb.edit_effects(sp, lines, lv.effects, list(w["effects"] or []), indent,
                        lv.end - 1)


def _new_level(w: Dict, lvl_indent: str, body_indent: str) -> List[str]:
    """A whole new ``Level`` block, written in the order the engine wants."""
    name = str(w.get("name") or "").strip()
    if not name:
        raise TraitError("a new level needs a name")
    out = [f"{lvl_indent}{LEVEL_KW} {name}"]
    values = dict(w)
    values.setdefault("description", f"{name}_desc")
    values.setdefault("effects_description", f"{name}_effects_desc")
    values.setdefault("threshold", "1")
    for key in LEVEL_ORDER:
        value = kb.value_text(values.get(_KEY_FIELD[key], ""), key in LIST_KEYS)
        if value:
            out.append(f"{body_indent}{key} {value}")
    for eff in (w.get("effects") or []):
        attribute = str((eff or {}).get("attribute") or "").strip()
        amount = str((eff or {}).get("amount") or "").strip()
        if attribute and amount:
            out.append(f"{body_indent}Effect {attribute} {amount}")
    return out


def replace_block(tf: TraitFile, trait: Trait, block: str) -> str:
    """The whole file with one trait's lines swapped for ``block``."""
    body, _, _ = triggers.split_lines(block)
    while body and not body[-1].strip():
        body.pop()
    lines = list(tf.lines)
    lines[trait.start:trait.end] = body
    out = tf.newline.join(lines)
    return out + tf.newline if tf.trailing_newline and lines else out


# ---------------------------------------------------------------------------
# spans, for the Code View widget


def block_spans(block: str) -> Dict[str, List[List[int]]]:
    """``{label: [[first, last]]}``, 1-based, for one trait block.

    A level owns two kinds of label: ``level#2`` is the whole block, so hovering
    a level card lights all of it, and ``level#2.threshold`` is one line inside
    it, so hovering one box lights only that.
    """
    trait = parse_block(block if block.endswith("\n") else block + "\n")
    spans: Dict[str, List[List[int]]] = {"name": [[trait.start + 1, trait.start + 1]]}
    for key, line in trait.lines.items():
        spans[_KEY_FIELD.get(key, key.lower())] = [[line + 1, line + 1]]
    for n, lv in enumerate(trait.levels, 1):
        spans[f"level#{n}"] = [[lv.start + 1, lv.end]]
        spans[f"level#{n}.name"] = [[lv.start + 1, lv.start + 1]]
        for key, line in lv.lines.items():
            spans[f"level#{n}.{_KEY_FIELD.get(key, key.lower())}"] = [[line + 1, line + 1]]
        for m, eff in enumerate(lv.effects, 1):
            spans[f"level#{n}.effect#{m}"] = [[eff.line + 1, eff.line + 1]]
    return spans


def block_fields(block: str) -> List[Tuple[str, str]]:
    """``[(label, value)]`` for one block, in the order the lines appear."""
    trait = parse_block(block if block.endswith("\n") else block + "\n")
    out = [("name", trait.name)]
    for key, _ in sorted(trait.lines.items(), key=lambda kv: kv[1]):
        out.append((_KEY_FIELD.get(key, key.lower()),
                    "yes" if key == "Hidden" else trait.values.get(key, "")))
    for n, lv in enumerate(trait.levels, 1):
        out.append((f"level#{n}.name", lv.name))
        for key, _ in sorted(lv.lines.items(), key=lambda kv: kv[1]):
            out.append((f"level#{n}.{_KEY_FIELD.get(key, key.lower())}",
                        lv.values.get(key, "")))
        for m, eff in enumerate(lv.effects, 1):
            out.append((f"level#{n}.effect#{m}", f"{eff.attribute} {eff.amount}"))
    return out


# ---------------------------------------------------------------------------
# plan -> apply
#
# One save can touch three things at once: the trait block, the triggers that
# feed it (which sit hundreds of lines below, in the same file) and the
# export_VnVs.txt keys its levels name. They belong in one job because they fail
# together — a trait whose text keys are missing crashes the character screen the
# first time anyone gets it, and a trigger left pointing at a deleted trait is
# the "Trait not recognized" the guide warns about.


@dataclass
class TraitPlan:
    mod: object = None
    action: str = "edit"                 # 'edit' | 'add' | 'delete'
    name: str = ""
    changes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    findings: List[Dict] = field(default_factory=list)
    #: the whole EDCT as it would be written — empty when nothing would change
    text: str = ""
    #: the new block, for the preview
    block: str = ""
    #: ``{tag: text}`` this save would write into export_VnVs — the keys the
    #: trait needs and does not have, plus any wording the user retyped
    loc_writes: Dict[str, str] = field(default_factory=dict)
    #: which of those are keys the file did not have at all
    loc_new: List[str] = field(default_factory=list)

    def summary(self) -> str:
        head = (f"{self.action} trait {self.name} in "
                f"{getattr(self.mod, 'name', '?')} ({len(self.changes)} change(s))")
        return "\n".join([head] + [f"  {c}" for c in self.changes])

    def payload(self) -> Dict:
        return {"action": self.action, "name": self.name,
                "changes": list(self.changes), "warnings": list(self.warnings),
                "errors": list(self.errors), "findings": list(self.findings),
                "block": self.block, "loc_writes": dict(self.loc_writes),
                "loc_new": list(self.loc_new),
                "ok": not self.errors and bool(self.text or self.loc_writes)}


def plan(mod, body: dict) -> TraitPlan:
    """Work out the whole new EDCT for one save, without touching the disk.

    ``body`` is ``{trait, action, edits, raw_block, triggers: {edits, adds,
    removes}, write_loc}``. ``edits`` is :func:`render_block`'s own shape, and
    ``raw_block`` is text the user hand-edited in the Code View — which wins over
    ``edits`` and reaches disk verbatim, the same ruling every other editor makes.
    """
    p = TraitPlan(mod=mod, action=str(body.get("action") or "edit"),
                  name=str(body.get("trait") or "").strip())
    path = Path(mod.edct_path)
    if not path.exists():
        p.errors.append(f"{getattr(mod, 'name', '?')} has no {path.name}")
        return p
    original = kb.read_text(path, ENCODING)
    try:
        text = _plan_trait(p, original, body)
        text = _plan_triggers(p, text, body)
    except (TraitError, triggers.TriggerError) as e:
        p.errors.append(e.message)
        return p
    if p.errors:
        return p

    tf = parse_text(text)
    trait = tf.get(p.name)
    if trait is not None:
        p.block = tf.block_text(trait)
        p.findings = check(trait, set(tf.by_name()))
        if body.get("write_loc", True):
            _plan_loc(p, mod, trait, dict(body.get("loc") or {}))
    p.text = "" if text == original else text
    if not p.text and not p.loc_writes and not p.errors:
        p.warnings.append("nothing to change")
    return p


def _plan_trait(p: TraitPlan, text: str, body: dict) -> str:
    """The EDCT with this one trait added, edited or removed."""
    tf = parse_text(text)
    if p.action == "add":
        if not p.name:
            raise TraitError("a new trait needs a name")
        if tf.get(p.name) is not None:
            p.errors.append(f"{p.name} is already a trait in this file")
            return text
        block = str(body.get("raw_block") or "").strip("\r\n") or new_block(
            dict(body.get("edits") or {}, name=p.name))
        parse_block(block + "\n")            # refuse a block that is not one
        p.changes.append(f"+ Trait {p.name}")
        return _insert_trait(tf, block)

    trait = tf.get(p.name)
    if trait is None:
        p.errors.append(f"{p.name} is not a trait in this file")
        return text

    if p.action == "delete":
        p.changes.append(f"- Trait {p.name} ({len(trait.levels)} level(s))")
        lines = list(tf.lines)
        del lines[trait.start:trait.end]
        out = tf.newline.join(lines)
        return out + tf.newline if tf.trailing_newline and lines else out

    base = tf.block_text(trait)
    raw = body.get("raw_block")
    if raw is not None and str(raw).strip():
        # hand-edited text goes to disk as written — reordering, indenting and
        # comments are edits no field map can express
        block = str(raw).strip("\r\n")
        if parse_block(block + "\n").name != p.name:
            raise TraitError(
                f"this trait is `{p.name}` — renaming it here would orphan every "
                "trigger, antitrait list and starting character that names it")
    else:
        block = render_block(base, dict(body.get("edits") or {}))
    if block == base:
        return text
    p.changes.extend(kb.diff(base, block))
    return replace_block(tf, trait, block)


def _insert_trait(tf: TraitFile, block: str) -> str:
    """A new trait goes under the last one, above the trigger section.

    Never at the end of the file: the definitions have to be read before the
    triggers that name them, and a ``Trait`` line below a ``Trigger`` is a trait
    the engine has already stopped looking for.
    """
    lines = list(tf.lines)
    at = (tf.traits[-1].end if tf.traits
          else (tf.trigger_start if tf.trigger_start >= 0 else len(lines)))
    body = [ln[:-1] if ln.endswith("\r") else ln for ln in block.split("\n")]
    lines[at:at] = [""] + body
    out = tf.newline.join(lines)
    return out + tf.newline if tf.trailing_newline and lines else out


def new_block(edits: Dict) -> str:
    """A whole trait block written from scratch, in the order the engine wants."""
    name = str(edits.get("name") or "").strip()
    if not name:
        raise TraitError("a new trait needs a name")
    chars = kb.value_text(edits.get("characters"), True) or "family"
    out = [f"{TRAIT_KW} {name}", f"    Characters {chars}"]
    for key in HEADER_ORDER:
        if key == "Hidden":
            if kb.truthy(edits.get("hidden")):
                out.append("    Hidden")
            continue
        value = kb.value_text(edits.get(_KEY_FIELD[key], ""), key in LIST_KEYS)
        if value:
            out.append(f"    {key} {value}")
    for lv in (list(edits.get("levels") or []) or [{"name": name}]):
        out.append("")
        out.extend(_new_level(lv or {}, "    ", "        "))
    return "\n".join(out)


def _plan_triggers(p: TraitPlan, text: str, body: dict) -> str:
    """The trigger half of a trait save, and the cleanup a delete owes it.

    The editing itself is :func:`triggers.edit_section`, shared with the
    ancillaries editor — both own the trigger section of their own file. What is
    specific here is that deleting a trait must not leave an `Affects` pointing
    at it, which is the guide's "Trait not recognized".
    """
    req = dict(body.get("triggers") or {})
    if p.action == "delete":
        req["removes"] = list(req.get("removes") or []) + triggers.orphaned_by(
            text, "Affects", p.name)
    text = triggers.edit_section(text, req, p.changes, p.warnings, p.errors)
    if p.action == "delete":
        text, dropped = triggers.strip_effect_lines(text, "Affects", p.name)
        if dropped:
            p.changes.append(f"- {dropped} `Affects {p.name}` line(s) from triggers "
                             "that feed other traits too")
    return text


def _plan_loc(p: TraitPlan, mod, trait: Trait, wanted: Dict) -> None:
    """What this save would write into ``export_VnVs.txt``.

    Two things at once, because they are the same write. **The keys the trait
    needs and the mod has not got** — a missing one is not cosmetic, it is the
    guide's CTD when a character reaches that level, so it is created with the
    tag itself as placeholder text: visible, obviously unfinished, not a crash.
    And **wording the user retyped**, since what a trait says on screen is as
    much a part of it as its threshold, and sending them to another module to
    write the words would be the tool getting in the way.
    """
    have = loc(mod)
    txt = Path(mod.data) / VNV_REL
    from . import stringsbin
    if not txt.exists() and not stringsbin.bin_path_for(txt).exists():
        p.warnings.append(f"this mod has no {txt.name}, so its text key(s) could "
                          "not be written — the trait will show its tags in game")
        return
    for tag in text_tags(trait):
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


def apply(p: TraitPlan) -> Dict:
    """Write a planned save, with the same backups and undo as any other job.

    The old files go to ``config/backups/<id>/data/…`` and the manifest goes in
    the transfer log, so 🕑 Log -> Undo puts both the EDCT and the text file back
    byte-exact.
    """
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
    out: Dict = {"id": tid, "trait": p.name}

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
        target = keep(Path(mod.edct_path).name)
        kb.write_text(target, p.text, ENCODING)
        file_op("WRITE", target, f"{len(p.text)} bytes")
    if p.loc_writes:
        out["loc"] = _write_loc(p, keep, stringsbin, cleaner, file_op)

    rec = {
        "id": tid,
        "when": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "traits",
        "action": p.action,
        "source": mod.name, "source_root": str(mod.root),
        "dest": mod.name, "dest_root": str(mod.root),
        "unit_type": p.name, "resolved_type": p.name,
        "options": {}, "applied": True, "undone": False, "note": "",
        "summary": p.summary(), "warnings": list(p.warnings),
        "manifest": manifest, "backup_root": str(backup_root),
    }
    config.append_log(rec)
    log.info("TRAIT  %s %s in %s — %d change(s), id=%s",
             p.action, p.name, mod.name, len(p.changes), tid)
    out["record"] = rec
    return out


def _write_loc(p: TraitPlan, keep, stringsbin, cleaner, file_op) -> Dict:
    """Add the missing text keys — to the ``.txt`` if there is one, the ``.bin`` if not.

    A mod that ships only the compiled archive is not a broken mod, it is most
    released ones, so the keys go straight into it through Phase 6's codec rather
    than the save refusing to finish.
    """
    txt = Path(p.mod.data) / VNV_REL
    if txt.exists():
        target = keep(VNV_REL)
        # the compiled cache is rewritten below, so it is backed up too — an undo
        # that restored the .txt and left the .bin would put the file back and
        # leave the game still reading the new text
        keep(VNV_REL + ".strings.bin")
        kb.write_text(target,
                      stringsbin.upsert_txt(kb.read_text(target, "utf-16"),
                                            p.loc_writes),
                      "utf-16")
        file_op("WRITE", target, f"{len(p.loc_writes)} text key(s)")
        res = cleaner.refresh_strings_bin(p.mod.root, VNV_BIN_REL)
        return {"file": VNV_REL, "written": len(p.loc_writes),
                "new": len(p.loc_new), "strings_bin": res}
    rel = VNV_REL + ".strings.bin"
    target = keep(rel)
    sb = stringsbin.read(target)
    for tag, value in p.loc_writes.items():
        sb.set(tag, value)
    stringsbin.write(target, sb)
    file_op("WRITE", target, f"{len(p.loc_writes)} text key(s)")
    return {"file": rel, "written": len(p.loc_writes), "new": len(p.loc_new),
            "compiled": True}
