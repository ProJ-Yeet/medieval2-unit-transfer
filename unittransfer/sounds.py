"""Parser + surgical editor for ``data/export_descr_sounds_units_voice.txt``.

That file is the unit **voice bank**: which .wav files a unit's soldiers shout.
It is a plain indented tree::

    BANK: unit_voice
        accent Arabic
            class Heavy
                vocal Unit_Select
                    engine heliopolis, middle_tower
                        event
                            folder data/sounds/Voice/...
                            Arabic_General_Generic_Tower_1.wav
                        end
                    unit Black Snake Guard
                        event
                            folder data/sounds/Voice/...
                            4a_Harad_Bodyguard_1.wav
                        end
                vocal Attack
                    event
                        ...
                    end

Only ``vocal Unit_Select`` carries per-unit entries (``unit <name>``); every other
vocal belongs to the whole ``accent``/``class`` pair. So a unit's voice is decided
by three things: its EDU ``accent`` and ``voice_type`` fields, which pick the block,
and a ``unit <type>`` entry inside that block's ``Unit_Select``, which gives it its
own selection barks.

Non-destructive by construction
-------------------------------
The bundled "Sounds Parser" prototype round-tripped this file through a CSV and
re-emitted it from scratch. That loses anything the CSV has no column for —
comments, blank lines, the exact indent of every line, repeated ``accent`` blocks
(Divide and Conquer has ``accent English`` four separate times) and the file's
line endings. Here the file is kept as its **verbatim lines** and every edit is a
splice: a unit entry is a contiguous line range that can be copied, renamed,
removed or re-inserted. Nothing outside the spliced range is ever rewritten.

The prototype's EDU side (``edu_parser.py``: EDU -> JSON -> EDU) is dropped
entirely — it drops unknown fields and re-indents every line. :mod:`unittransfer.edu`
already keeps each unit block verbatim, so the EDU half of a voice edit goes
through :func:`set_voice_fields` instead.
"""
from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import config, edu as edu_mod, eop

# Same reasoning as the EDU: 8-bit text, and latin-1 round-trips every byte.
ENCODING = "latin-1"

#: Path of the voice bank relative to a mod's ``data/`` folder.
EDS_REL = "export_descr_sounds_units_voice.txt"

#: The vocal that owns per-unit entries. Every other vocal is class-wide.
UNIT_SELECT = "Unit_Select"

#: Structural keywords, i.e. the lines that are NOT sound-file paths. Recognised
#: only outside an open ``event`` block — inside one, every line is a path and a
#: file could legitimately be called ``unit_something.wav``.
_STRUCT = ("accent", "class", "vocal", "unit", "engine")


@dataclass
class VoiceEntry:
    """One ``unit <name>`` / ``engine <name>`` sub-entry of a vocal.

    ``start``/``end`` are line indices into :attr:`SoundBank.lines` covering the
    keyword line and every event block under it (``end`` is exclusive).
    """
    accent: str
    voice_class: str
    vocal: str
    kind: str                     # "unit" | "engine"
    names: List[str]              # the comma-separated names on the keyword line
    start: int
    end: int

    @property
    def name(self) -> str:
        return self.names[0] if self.names else ""


@dataclass
class VocalBlock:
    """A ``vocal <name>`` region inside one accent/class block."""
    accent: str
    voice_class: str
    vocal: str
    start: int                    # index of the `vocal ...` line
    end: int                      # exclusive
    entries: List[VoiceEntry] = field(default_factory=list)


@dataclass
class SoundBank:
    lines: List[str]                                  # verbatim, keepends
    vocals: List[VocalBlock] = field(default_factory=list)
    entries: List[VoiceEntry] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_text(self) -> str:
        return "".join(self.lines)

    # ---- lookups -------------------------------------------------------
    def accents(self) -> List[str]:
        """Distinct accent names, in file order (an accent may appear twice)."""
        return list(dict.fromkeys(v.accent for v in self.vocals if v.accent))

    def classes(self) -> List[str]:
        return list(dict.fromkeys(v.voice_class for v in self.vocals if v.voice_class))

    def unit_entries(self) -> List[VoiceEntry]:
        """Every per-unit ``Unit_Select`` entry."""
        return [e for e in self.entries
                if e.kind == "unit" and e.vocal == UNIT_SELECT]

    def by_unit(self) -> Dict[str, VoiceEntry]:
        """Map unit name -> its entry (first wins; a duplicate is a warning)."""
        out: Dict[str, VoiceEntry] = {}
        for e in self.unit_entries():
            for n in e.names:
                out.setdefault(n, e)
        return out

    def get(self, unit_name: str) -> Optional[VoiceEntry]:
        return self.by_unit().get(unit_name)

    def unit_select(self, accent: str, voice_class: str) -> Optional[VocalBlock]:
        """The first ``Unit_Select`` block of an accent/class pair.

        "First" matters: an accent name can head several blocks in one file, and
        the game reads them in order, so a new entry belongs in the first one.
        """
        for v in self.vocals:
            if (v.vocal == UNIT_SELECT and v.accent == accent
                    and v.voice_class == voice_class):
                return v
        return None

    def class_pairs(self) -> List[Tuple[str, str]]:
        """(accent, class) pairs that have a ``Unit_Select`` block, in file order."""
        return list(dict.fromkeys((v.accent, v.voice_class) for v in self.vocals
                                  if v.vocal == UNIT_SELECT))


# ---------------------------------------------------------------------------
# parsing


def _keyword(stripped: str) -> Tuple[str, str]:
    """``('unit', 'Black Snake Guard')`` for a structural line, else ``('', '')``."""
    head = stripped.split(None, 1)
    key = head[0].lower()
    if key in _STRUCT:
        return key, (head[1].strip() if len(head) > 1 else "")
    return "", ""


def _names(value: str) -> List[str]:
    """Split a keyword line's value on commas (``engine a, b, c``)."""
    return [n.strip() for n in value.split(",") if n.strip()]


def parse_text(text: str) -> SoundBank:
    lines = text.splitlines(keepends=True)
    bank = SoundBank(lines=lines)

    accent = voice_class = vocal = ""
    inside_event = False
    open_vocal: Optional[VocalBlock] = None
    open_entry: Optional[VoiceEntry] = None

    def close_entry(at: int) -> None:
        """End the open entry, not counting blank/comment lines that trail it.

        A block runs up to the NEXT keyword line, so it would otherwise swallow
        the blank line or section comment that really introduces what follows —
        and copying an entry would drag that along, while deleting one would take
        it away.
        """
        nonlocal open_entry
        if open_entry is None:
            return
        cut = at
        while cut > open_entry.start + 1:
            s = lines[cut - 1].strip()
            if s and not s.startswith(";"):
                break
            cut -= 1
        open_entry.end = cut
        open_entry = None

    def close_vocal(at: int) -> None:
        nonlocal open_vocal
        close_entry(at)
        if open_vocal is not None:
            open_vocal.end = at
            open_vocal = None

    for i, raw in enumerate(lines):
        s = raw.strip()
        if not s or s.startswith(";"):
            continue

        # Inside an open event every line is a sound path until `end` — this test
        # MUST come first, or a file named `engine_fire.wav` would be read as a
        # sub-entry. (The prototype tolerated `endd`-style typos; so do we.)
        if inside_event:
            low = s.lower()
            if low == "end" or (low.startswith("end") and low.rstrip("d") == "en"):
                inside_event = False
                if low != "end":
                    bank.warnings.append(f"line {i + 1}: read {s!r} as 'end'")
            continue

        key, value = _keyword(s)
        if key == "accent":
            close_vocal(i)
            accent, voice_class, vocal = value, "", ""
        elif key == "class":
            close_vocal(i)
            voice_class, vocal = value, ""
        elif key == "vocal":
            close_vocal(i)
            vocal = value.split()[0] if value else ""
            open_vocal = VocalBlock(accent=accent, voice_class=voice_class,
                                    vocal=vocal, start=i, end=len(lines))
            bank.vocals.append(open_vocal)
        elif key in ("unit", "engine"):
            close_entry(i)
            open_entry = VoiceEntry(accent=accent, voice_class=voice_class,
                                    vocal=vocal, kind=key, names=_names(value),
                                    start=i, end=len(lines))
            bank.entries.append(open_entry)
            if open_vocal is not None:
                open_vocal.entries.append(open_entry)
        elif s.split(None, 1)[0].lower() == "event":
            inside_event = True
        elif s.lower() == "end":
            bank.warnings.append(f"line {i + 1}: 'end' with no open 'event'")
        # anything else outside an event is unrecognised; left alone verbatim

    close_vocal(len(lines))
    return bank


def parse_file(path: str | Path) -> SoundBank:
    p = Path(path)
    if not p.exists():
        return SoundBank(lines=[])
    return parse_text(p.read_text(encoding=ENCODING))


# ---------------------------------------------------------------------------
# splicing


def _indent_of(line: str) -> str:
    return line[:len(line) - len(line.lstrip())]


def _reindent(block: List[str], old: str, new: str) -> List[str]:
    """Shift a copied block from one indent level to another.

    Every level of this file sits at a fixed depth, so a donor entry from another
    accent normally needs no shift at all — but a hand-edited file can mix tabs
    and spaces, and pasting a block at the wrong depth is how you get a voice bank
    the game silently ignores.
    """
    if old == new:
        return list(block)
    out = []
    for l in block:
        out.append(new + l[len(old):] if l.startswith(old) else l)
    return out


def _rename_keyword_line(line: str, new_name: str) -> str:
    """``'\\t\\t\\t\\tunit Old Name\\n'`` -> the same line naming ``new_name``."""
    body = line.rstrip("\r\n")
    eol = line[len(body):] or "\n"
    indent = _indent_of(body)
    key = body.strip().split(None, 1)[0]
    return f"{indent}{key} {new_name}{eol}"


def _insert_at(block: VocalBlock, donor: Optional[VoiceEntry]) -> int:
    """Where a new entry goes inside a ``Unit_Select`` block.

    Right after the donor when the donor lives in this very block (copies stay
    next to what they were copied from, which is how the bank reads); otherwise
    after the last ``unit`` entry, else after the last ``engine`` entry, else
    immediately after the ``vocal Unit_Select`` line itself.
    """
    if donor is not None and block.start <= donor.start < block.end:
        return donor.end
    units = [e for e in block.entries if e.kind == "unit"]
    if units:
        return units[-1].end
    if block.entries:
        return block.entries[-1].end
    return block.start + 1


def entry_indent(block: VocalBlock, bank: SoundBank) -> str:
    """The indent a sub-entry keyword line uses inside this block."""
    if block.entries:
        return _indent_of(bank.lines[block.entries[0].start])
    return _indent_of(bank.lines[block.start]) + "\t"


def add_unit(bank: SoundBank, unit_name: str, donor: VoiceEntry,
             accent: str, voice_class: str) -> str:
    """Return the file text with ``unit_name`` added, copying ``donor``'s sounds.

    Raises ``ValueError`` when the accent/class pair has no ``Unit_Select`` block
    to add to — inventing a whole accent bank would be a guess, and a silently
    misplaced entry is worse than a refusal the user can act on.
    """
    block = bank.unit_select(accent, voice_class)
    if block is None:
        raise ValueError(f"no '{accent}' / '{voice_class}' Unit_Select block in the voice bank")
    src = bank.lines[donor.start:donor.end]
    if not src:
        raise ValueError(f"voice entry for {donor.name!r} is empty")
    copied = _reindent(src, _indent_of(src[0]), entry_indent(block, bank))
    copied[0] = _rename_keyword_line(copied[0], unit_name)
    at = _insert_at(block, donor)
    out = list(bank.lines)
    out[at:at] = copied
    return "".join(out)


def remove_unit(bank: SoundBank, unit_name: str) -> str:
    """Return the file text with ``unit_name``'s entry deleted (no-op if absent)."""
    e = bank.get(unit_name)
    if e is None:
        return bank.to_text()
    if len(e.names) > 1:
        # the line names several units — drop just this one rather than the block
        keep = [n for n in e.names if n != unit_name]
        out = list(bank.lines)
        out[e.start] = _rename_keyword_line(out[e.start], ", ".join(keep))
        return "".join(out)
    out = list(bank.lines)
    del out[e.start:e.end]
    return "".join(out)


def move_unit(bank: SoundBank, unit_name: str, accent: str, voice_class: str,
              donor: Optional[VoiceEntry] = None) -> str:
    """Move an existing entry to another accent/class, optionally re-copying sounds.

    ``donor`` replaces the entry's sound paths; ``None`` keeps its own. The move
    is a delete + insert, so the file is re-parsed in between — line numbers shift
    the moment anything is spliced out.
    """
    e = bank.get(unit_name)
    if e is None:
        raise ValueError(f"{unit_name!r} has no voice entry to move")
    source = donor if donor is not None else e
    # copy the block we are about to re-insert BEFORE removing anything
    src = bank.lines[source.start:source.end]
    text = remove_unit(bank, unit_name)
    after = parse_text(text)
    block = after.unit_select(accent, voice_class)
    if block is None:
        raise ValueError(f"no '{accent}' / '{voice_class}' Unit_Select block in the voice bank")
    copied = _reindent(src, _indent_of(src[0]), entry_indent(block, after))
    copied[0] = _rename_keyword_line(copied[0], unit_name)
    # the donor's own entry may have shifted with the removal — re-find it
    ref = after.get(donor.name) if donor is not None else None
    at = _insert_at(block, ref)
    out = list(after.lines)
    out[at:at] = copied
    return "".join(out)


# ---------------------------------------------------------------------------
# the EDU half of a voice edit


def set_voice_fields(block: str, accent: str, voice_class: str) -> str:
    """Point a unit's EDU block at an accent/class pair.

    ``accent`` and ``voice_type`` are what the game uses to find the voice bank
    block; the ``unit`` entry inside it is useless without them. Existing lines
    are edited in place (indent, spacing and trailing comment kept); a missing one
    is inserted at its canonical position, right after ``class`` / ``voice_type``.
    """
    out = block
    if voice_class:
        out = (edu_mod.set_field(out, "voice_type", voice_class)
               if _has_field(out, "voice_type")
               else edu_mod.add_field(out, "voice_type", voice_class))
    if accent:
        out = (edu_mod.set_field(out, "accent", accent)
               if _has_field(out, "accent")
               else edu_mod.add_field(out, "accent", accent))
    return out


def _has_field(block: str, key: str) -> bool:
    return any(edu_mod.line_key(l) == key for l in block.splitlines())


def unit_voice_fields(unit) -> Tuple[str, str]:
    """``(accent, voice_type)`` as written in a parsed EDU unit's block ('' if absent)."""
    found = {"accent": "", "voice_type": ""}
    for line in unit.raw.splitlines():
        k = edu_mod.line_key(line)
        if k in found and not found[k]:
            parts = line.strip().split(None, 1)
            found[k] = _strip_comment(parts[1]) if len(parts) > 1 else ""
    return found["accent"], found["voice_type"]


def _strip_comment(v: str) -> str:
    return v.split(";", 1)[0].strip()


# ---------------------------------------------------------------------------
# plan / apply for Sounds mode (batch edits inside ONE mod)


@dataclass
class SoundOp:
    """One unit's voice change, as the UI stages it."""
    unit: str                     # EDU unit type
    accent: str = ""
    voice_class: str = ""
    donor: str = ""               # unit whose sounds to copy ("" = keep its own)
    remove: bool = False          # drop the voice entry entirely


@dataclass
class SoundPlan:
    mod: object
    ops: List[SoundOp] = field(default_factory=list)
    eds_text: str = ""            # "" = voice bank unchanged
    edu_text: str = ""            # "" = EDU unchanged
    # accent / voice_type on an M2TWEOP unit lives in that unit's own file, not in
    # the EDU: {absolute path: new text}. See :mod:`unittransfer.eop`.
    eop_texts: Dict[str, str] = field(default_factory=dict)
    changes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [f"voice edits in {self.mod.name} ({len(self.ops)} unit(s))"]
        lines += ["  " + c for c in self.changes]
        lines += ["  ! " + w for w in self.warnings]
        lines += ["  ERROR: " + e for e in self.errors]
        return "\n".join(lines)


def ops_from_dicts(raw) -> List[SoundOp]:
    return [SoundOp(unit=str(d.get("unit") or ""),
                    accent=str(d.get("accent") or ""),
                    voice_class=str(d.get("class") or d.get("voice_class") or ""),
                    donor=str(d.get("donor") or ""),
                    remove=bool(d.get("remove")))
            for d in (raw or []) if (d.get("unit") or "").strip()]


def plan_sounds(mod, ops: List[SoundOp]) -> SoundPlan:
    """Work out the whole new voice-bank + EDU text for a batch of voice edits.

    Every op is applied to the *running* text and the result re-parsed, because a
    splice moves every line after it — planning them all against the original file
    would put the second edit in the wrong place.
    """
    plan = SoundPlan(mod=mod, ops=list(ops))
    if not ops:
        return plan
    if not mod.eds_path.exists():
        plan.errors.append(f"{mod.name} has no data/{mod.eds_path.name}")
        return plan

    text = mod.sounds.to_text()
    by_type = mod.edu.by_type()
    edu_edits: Dict[str, Tuple[str, str]] = {}      # unit type -> (accent, class)

    for op in ops:
        bank = parse_text(text)
        existing = bank.get(op.unit)

        if op.remove:
            if existing is None:
                plan.warnings.append(f"{op.unit}: no voice entry to remove")
                continue
            text = remove_unit(bank, op.unit)
            plan.changes.append(f"{op.unit}: voice entry removed "
                                f"({existing.accent}/{existing.voice_class})")
            continue

        if not op.accent or not op.voice_class:
            plan.errors.append(f"{op.unit}: pick an accent and a class")
            continue
        if bank.unit_select(op.accent, op.voice_class) is None:
            plan.errors.append(f"{op.unit}: {mod.name}'s voice bank has no "
                               f"{op.accent} / {op.voice_class} Unit_Select block")
            continue

        donor = bank.get(op.donor) if op.donor else None
        if op.donor and donor is None:
            plan.errors.append(f"{op.unit}: no voice entry named {op.donor!r} to copy from")
            continue

        try:
            if existing is None:
                if donor is None:
                    plan.errors.append(f"{op.unit}: pick a unit to copy the sounds from")
                    continue
                text = add_unit(bank, op.unit, donor, op.accent, op.voice_class)
                plan.changes.append(
                    f"{op.unit}: voice entry added in {op.accent}/{op.voice_class}, "
                    f"sounds copied from {donor.name}")
            else:
                moved = (existing.accent != op.accent
                         or existing.voice_class != op.voice_class)
                if not moved and donor is None:
                    plan.warnings.append(f"{op.unit}: nothing to change")
                    continue
                text = move_unit(bank, op.unit, op.accent, op.voice_class, donor)
                what = []
                if moved:
                    what.append(f"moved {existing.accent}/{existing.voice_class} "
                                f"-> {op.accent}/{op.voice_class}")
                if donor is not None:
                    what.append(f"sounds copied from {donor.name}")
                plan.changes.append(f"{op.unit}: " + ", ".join(what))
        except ValueError as exc:
            plan.errors.append(f"{op.unit}: {exc}")
            continue

        if op.unit in by_type:
            edu_edits[op.unit] = (op.accent, op.voice_class)
        else:
            plan.warnings.append(
                f"{op.unit}: no such unit in {mod.name}'s EDU — the voice entry is "
                f"written but nothing points at it")

    if plan.errors:
        return plan
    if text != mod.sounds.to_text():
        plan.eds_text = text
    if edu_edits:
        split = _edu_with_voice(mod, edu_edits)
        plan.edu_text = split.main
        plan.eop_texts = dict(split.files)
        for utype, (accent, cls) in edu_edits.items():
            plan.changes.append(f"{utype}: EDU accent={accent}, voice_type={cls}")
        for key in split.files:
            plan.changes.append(
                f"EOP unit file rewritten: {eop.rel_to_root(mod, key)}")
    return plan


def _edu_with_voice(mod, edits: Dict[str, Tuple[str, str]]) -> "eop.Split":
    """The mod's unit files with only the named units' voice fields changed.

    An M2TWEOP unit's ``accent`` / ``voice_type`` are in its own file, so this
    returns a split rather than one blob — writing the change into
    export_descr_unit.txt would both miss the unit and corrupt the EDU.
    """
    blocks = {u.type: set_voice_fields(u.raw, *edits[u.type])
              for u in mod.edu.units if u.type in edits}
    return eop.compose(mod, eop.edited(mod.edu.units, blocks))


def apply_sounds(plan: SoundPlan) -> Dict:
    """Write the plan into the mod, with per-file backups and a log record.

    Same machinery as a transfer or a unit edit: every touched file is copied into
    ``config/backups/<id>/`` first and the manifest goes in the transfer log, so
    🕑 Log -> Undo restores the voice bank byte-exact.
    """
    if plan.errors:
        raise ValueError("cannot apply: " + "; ".join(plan.errors))
    mod = plan.mod
    tid = config.new_transfer_id()
    backup_root = config.backup_root_for(tid)
    manifest: Dict[str, List[str]] = {"backed_up": [], "created": []}

    def write_text(rel: str, text: str, encoding: str) -> None:
        target = mod.data / rel
        if target.exists():
            bpath = backup_root / "data" / rel
            bpath.parent.mkdir(parents=True, exist_ok=True)
            if not bpath.exists():
                shutil.copy2(target, bpath)
            manifest["backed_up"].append(rel)
        else:
            manifest["created"].append(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding=encoding)

    if plan.eds_text:
        write_text(EDS_REL, plan.eds_text, ENCODING)
    if plan.edu_text:
        write_text("export_descr_unit.txt", plan.edu_text, edu_mod.ENCODING)
    if plan.eop_texts:
        eop.write_split(mod, plan.eop_texts, (), backup_root, manifest)

    units = [op.unit for op in plan.ops]
    rec = {
        "id": tid,
        "when": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "sounds",
        "action": "voice",
        "source": mod.name,
        "source_root": str(mod.root),
        "dest": mod.name,
        "dest_root": str(mod.root),
        "unit_type": units[0] if len(units) == 1 else f"{len(units)} units",
        "resolved_type": units[0] if len(units) == 1 else f"{len(units)} units",
        "options": {},
        "applied": True,
        "undone": False,
        "note": "",
        "summary": plan.summary(),
        "warnings": list(plan.warnings),
        "manifest": manifest,
        "backup_root": str(backup_root),
    }
    config.append_log(rec)
    mod.__dict__.pop("sounds", None)
    mod.__dict__.pop("edu", None)
    mod.__dict__.pop("edu_vocab", None)
    return rec


# ---------------------------------------------------------------------------
# payload for the Sounds-mode UI


def overview(mod) -> dict:
    """Everything Sounds mode needs for one mod, in one request.

    Units are split into those the voice bank already has an entry for and those
    it doesn't — the same two lists the prototype's HTML editor showed, except the
    accents/classes and donors come from the mod being edited rather than from
    files a .bat had to generate first.
    """
    bank = mod.sounds
    by_unit = bank.by_unit()
    pairs = bank.class_pairs()
    accents = list(dict.fromkeys(a for a, _c in pairs))
    classes = list(dict.fromkeys(c for _a, c in pairs))

    donors = [{"name": e.name, "accent": e.accent, "class": e.voice_class}
              for e in bank.unit_entries()]

    missing, existing = [], []
    for u in mod.edu.units:
        accent, cls = unit_voice_fields(u)
        loc = mod.loc.get(u.dictionary)
        row = {
            "type": u.type,
            "name": (loc.name.strip() if loc and loc.name else "") or u.type,
            "edu_accent": accent,
            "edu_class": cls,
            # an EDU accent/class the bank has no block for is the single most
            # common reason a transferred unit ends up mute
            "accent_valid": accent in accents if accent else False,
            "class_valid": cls in classes if cls else False,
        }
        e = by_unit.get(u.type)
        if e is None:
            missing.append(row)
        else:
            row["accent"] = e.accent
            row["class"] = e.voice_class
            # the EDU says one block, the bank puts the unit in another: the game
            # follows the EDU, so the entry is dead until one of the two moves
            row["accent_conflict"] = bool(accent) and accent.lower() != e.accent.lower()
            row["class_conflict"] = bool(cls) and cls.lower() != e.voice_class.lower()
            existing.append(row)

    # entries whose unit no longer exists in the EDU: dead weight, and a name a
    # new unit could collide with
    types = {u.type for u in mod.edu.units}
    orphans = [{"type": e.name, "name": e.name,
                "accent": e.accent, "class": e.voice_class}
               for e in bank.unit_entries() if e.name not in types]

    return {
        "mod": mod.name,
        "has_file": mod.eds_path.exists(),
        "accents": accents,
        "classes": classes,
        "pairs": [{"accent": a, "class": c} for a, c in pairs],
        "donors": donors,
        "missing": missing,
        "existing": existing,
        "orphans": orphans,
        "warnings": bank.warnings[:20],
    }
