"""Parser for data/export_descr_unit.txt (M2TW EDU).

Each unit is a block that starts at a line whose first token is ``type`` and runs
until the next ``type`` (or EOF). We keep every block's *verbatim text* so a
transfer can append a source unit unchanged, and we parse the handful of fields
needed for dependency resolution, UI grouping and the animation check.

Field reference: ModdingTool ``UnitDb.AssignFields``. Comments start with ``;``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# EDU is plain 8-bit text; latin-1 round-trips every byte.
ENCODING = "latin-1"


def _split_fields(line: str) -> tuple[str, List[str]]:
    """Return (key, values) for one EDU line.

    Handles the multi-word keys (``banner faction``, ``banner holy``,
    ``era 0/1/2``) and comma-separated value lists.
    """
    # strip trailing comment
    if ";" in line:
        # keep ai_unit_value / value_per lines intact (they use ';' as data marker
        # in ModdingTool) — but for field parsing we only need the pre-';' part.
        line = line.split(";", 1)[0]
    line = line.rstrip()
    if not line.strip():
        return "", []
    stripped = line.strip()
    first = stripped.split(None, 1)
    key = first[0]
    remainder = first[1].strip() if len(first) > 1 else ""

    multiword = {"banner", "era"}
    if key in multiword and remainder:
        sub = remainder.split(None, 1)
        key = key + " " + sub[0]
        remainder = sub[1].strip() if len(sub) > 1 else ""

    values = [v.strip() for v in remainder.split(",")] if remainder else []
    return key, values


def _slot6(vals: List[str]) -> str:
    """6th CSV value of a stat_pri/stat_sec line, lowercased ('' if absent).

    That slot is the weapon tech class: ``melee`` / ``missile`` / ``thrown`` /
    ``no`` (``no`` = the unit has no such weapon).
    """
    return vals[5].strip().lower() if len(vals) > 5 else ""


@dataclass
class Unit:
    type: str = ""                       # display/internal name (may have spaces)
    dictionary: str = ""                 # localisation + icon key
    category: str = ""
    class_type: str = ""
    ownership: List[str] = field(default_factory=list)
    era0: List[str] = field(default_factory=list)
    era1: List[str] = field(default_factory=list)
    era2: List[str] = field(default_factory=list)
    soldier_model: str = ""              # first CSV token of `soldier`
    officers: List[str] = field(default_factory=list)
    mount: str = ""
    ship: str = ""
    engine: str = ""
    mounted_engine: str = ""
    animal: str = ""
    armour_ug_models: List[str] = field(default_factory=list)
    card_pic_dir: Optional[str] = None
    info_pic_dir: Optional[str] = None
    attributes: List[str] = field(default_factory=list)
    mercenary_unit: bool = False
    stat_pri: List[str] = field(default_factory=list)   # CSV values of stat_pri
    stat_sec: List[str] = field(default_factory=list)   # CSV values of stat_sec
    raw: str = ""                        # verbatim block text (incl. leading blank/comment lines)
    # M2TWEOP unit: this block lives in one of the extender's own files rather than
    # in data/export_descr_unit.txt. Everything else about it is a normal unit —
    # same fields, same models, same icons — so the flag exists purely to say where
    # an edit to it gets written back. See :mod:`unittransfer.eop`.
    is_eop: bool = False
    eop_file: str = ""                   # absolute path of that file ("" for EDU units)

    def kind(self) -> str:
        """Refined category used for grouping and base-unit matching.

        ``cavalry`` and ``infantry`` split by what the unit actually fights with —
        the 6th CSV slot of ``stat_pri``/``stat_sec`` (the weapon's tech type:
        ``missile`` / ``thrown`` / ``melee`` / ``no``):
          * cavalry, ``stat_pri`` slot 6 == ``missile``  -> ``Cavalry_Archer``
          * cavalry, ``stat_pri`` slot 6 == ``thrown``   -> ``Cavalry_Javelin``
          * cavalry, melee primary + a real ``stat_sec`` -> ``Cavalry_Lance``
            (lance primary, sidearm secondary)
          * cavalry, otherwise                           -> ``Cavalry``
          * infantry, ``stat_pri`` slot 6 == ``missile`` -> ``Infantry_Archer``
          * infantry, ``stat_pri`` slot 6 == ``thrown``  -> ``Infantry_Javelin``
          * infantry, otherwise                          -> ``Infantry``
        Every other category is returned unchanged. So a base unit is only offered
        for a same-fighting-style unit (a javelin unit only bases on a javelin unit).
        """
        cat = (self.category or "").lower()
        pri = _slot6(self.stat_pri)
        if cat == "cavalry":
            if pri == "missile":
                return "Cavalry_Archer"
            if pri == "thrown":
                return "Cavalry_Javelin"
            sec = _slot6(self.stat_sec)
            if sec and sec != "no":
                return "Cavalry_Lance"
            return "Cavalry"
        if cat == "infantry":
            if pri == "missile":
                return "Infantry_Archer"
            if pri == "thrown":
                return "Infantry_Javelin"
            return "Infantry"
        return self.category or ""

    def model_names(self) -> List[str]:
        """All battle-model names this unit references (lowercased, deduped)."""
        names: List[str] = []
        if self.soldier_model:
            names.append(self.soldier_model)
        names.extend(self.officers)
        names.extend(self.armour_ug_models)
        seen, out = set(), []
        for n in names:
            k = n.lower()
            if k and k not in seen:
                seen.add(k)
                out.append(k)
        return out

    def projectiles(self) -> List[str]:
        """Projectile names this unit fires (3rd CSV slot of stat_pri/stat_sec).

        A melee weapon has ``no`` in that slot; only real projectile names are
        returned, deduped and in pri-then-sec order.
        """
        out: List[str] = []
        for stat in (self.stat_pri, self.stat_sec):
            if len(stat) > 2:
                p = stat[2].strip()
                if p and p.lower() != "no":
                    out.append(p)
        seen, res = set(), []
        for p in out:
            if p.lower() not in seen:
                seen.add(p.lower()); res.append(p)
        return res

    @property
    def projectile(self) -> str:
        """Primary projectile name (stat_pri slot 3), or '' for a melee unit."""
        ps = self.projectiles()
        return ps[0] if ps else ""

    def _icon_dirs(self, pic_dir: Optional[str], merc_default: str,
                   other_merc: str) -> List[str]:
        """Faction folders to search for one icon kind, best-first.

        ``card_pic_dir`` and ``info_pic_dir`` are INDEPENDENT EDU fields — a unit
        can pin its card to ``mercs`` while leaving ``info_pic_dir`` unset (so the
        info card is looked up under its ownership faction instead). Each kind
        therefore needs its OWN pic_dir here, not the card's.
        """
        if pic_dir:
            base = [pic_dir]
        elif self.mercenary_unit:
            base = [merc_default]
        else:
            base = [f for f in self.ownership if f != "slave"] or list(self.ownership)
        # merc folders are the universal fallback (this kind's own merc folder first)
        for fb in (merc_default, other_merc):
            if fb not in base:
                base.append(fb)
        return base

    def card_dirs(self) -> List[str]:
        """Faction folders to search for the unit CARD, best-first."""
        return self._icon_dirs(self.card_pic_dir, "mercs", "merc")

    def info_dirs(self) -> List[str]:
        """Faction folders to search for the INFO card, best-first."""
        return self._icon_dirs(self.info_pic_dir, "merc", "mercs")


@dataclass
class EduFile:
    """The mod's units — ``export_descr_unit.txt`` plus any M2TWEOP unit files.

    ``units`` deliberately holds both kinds, because every feature in the tool
    wants the mod's full roster: a unit is a unit whether the engine read it from
    the EDU or from the extender's folder. What must NOT blur is where they are
    written back, so :meth:`to_text` — the "this is the EDU file" accessor — emits
    only the main file's units, and EOP blocks are routed by
    :func:`unittransfer.eop.compose`.
    """
    preamble: str                        # text before the first `type` (header comments)
    units: List[Unit]
    # ``{eop file path: its own preamble}``, so a rewrite of one EOP file keeps
    # whatever header comment it had instead of losing it.
    eop_preambles: Dict[str, str] = field(default_factory=dict)

    def by_type(self) -> Dict[str, Unit]:
        return {u.type: u for u in self.units}

    def by_dictionary(self) -> Dict[str, Unit]:
        return {u.dictionary: u for u in self.units if u.dictionary}

    @property
    def main_units(self) -> List[Unit]:
        """Units that live in data/export_descr_unit.txt."""
        return [u for u in self.units if not u.is_eop]

    @property
    def eop_units(self) -> List[Unit]:
        """Units that live in an M2TWEOP unit file."""
        return [u for u in self.units if u.is_eop]

    def to_text(self) -> str:
        """The text of ``export_descr_unit.txt`` — EOP units excluded on purpose."""
        return self.preamble + "".join(u.raw for u in self.main_units)

    def write(self, path: str | Path) -> None:
        Path(path).write_text(self.to_text(), encoding=ENCODING)


def _parse_block(raw: str) -> Unit:
    u = Unit(raw=raw)
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith(";"):
            continue
        key, vals = _split_fields(line)
        if not key:
            continue
        v0 = vals[0] if vals else ""
        if key == "type":
            u.type = v0
        elif key == "dictionary":
            u.dictionary = v0
        elif key == "category":
            u.category = v0
        elif key == "class":
            u.class_type = v0
        elif key == "soldier":
            u.soldier_model = v0
        elif key == "officer":
            if v0:
                u.officers.append(v0)
        elif key == "mount":
            u.mount = v0
        elif key == "ship":
            u.ship = v0
        elif key == "engine":
            u.engine = v0
        elif key == "mounted_engine":
            u.mounted_engine = v0
        elif key == "animal":
            u.animal = v0
        elif key == "armour_ug_models":
            u.armour_ug_models = [x for x in vals if x]
        elif key == "ownership":
            u.ownership = [x for x in vals if x]
        elif key == "era 0":
            u.era0 = [x for x in vals if x]
        elif key == "era 1":
            u.era1 = [x for x in vals if x]
        elif key == "era 2":
            u.era2 = [x for x in vals if x]
        elif key == "stat_pri":
            u.stat_pri = vals
        elif key == "stat_sec":
            u.stat_sec = vals
        elif key == "card_pic_dir":
            u.card_pic_dir = v0 or None
        elif key == "info_pic_dir":
            u.info_pic_dir = v0 or None
        elif key == "attributes":
            for a in vals:
                if not a:
                    continue
                u.attributes.append(a)
                if a == "mercenary_unit":
                    u.mercenary_unit = True
    return u


def parse_text(text: str) -> EduFile:
    lines = text.splitlines(keepends=True)
    # Find block boundaries: a line whose first non-space token is `type`.
    starts: List[int] = []
    for idx, line in enumerate(lines):
        s = line.lstrip()
        if s.startswith("type") and (len(s) == 4 or s[4].isspace()):
            # not a comment line
            if not line.lstrip().startswith(";"):
                starts.append(idx)
    if not starts:
        return EduFile(preamble=text, units=[])

    preamble = "".join(lines[:starts[0]])
    units: List[Unit] = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(lines)
        raw = "".join(lines[start:end])
        units.append(_parse_block(raw))
    return EduFile(preamble=preamble, units=units)


def parse_file(path: str | Path) -> EduFile:
    return parse_text(Path(path).read_text(encoding=ENCODING))


# --- block rewriting (for rename conflicts + model renames) --------------
import re as _re

_FIELD_RE = _re.compile(r"^([ \t]*(type|dictionary|soldier|officer|armour_ug_models)[ \t]+)(.*)$")


def _split_comment(value: str):
    if ";" in value:
        i = value.index(";")
        return value[:i].rstrip(), value[i:]
    return value.rstrip(), ""


def rewrite_block(raw: str, *, type_new: str | None = None,
                  dict_new: str | None = None,
                  model_map: dict | None = None) -> str:
    """Return a copy of a unit block with fields/model refs rewritten.

    ``model_map`` maps lowercased old model name -> new name; it rewrites the
    model token(s) in ``soldier`` (1st CSV field), ``officer`` (whole value) and
    ``armour_ug_models`` (each CSV field). Whitespace/comments are preserved.
    """
    model_map = {k.lower(): v for k, v in (model_map or {}).items()}
    out_lines = []
    for line in raw.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        eol = line[len(body):]
        m = _FIELD_RE.match(body)
        if not m:
            out_lines.append(line)
            continue
        prefix, field, value = m.group(1), m.group(2), m.group(3)
        val, comment = _split_comment(value)

        if field == "type" and type_new is not None:
            val = type_new
        elif field == "dictionary" and dict_new is not None:
            val = dict_new
        elif field == "soldier" and model_map:
            parts = val.split(",")
            tok = parts[0].strip()
            if tok.lower() in model_map:
                lead = parts[0][:len(parts[0]) - len(parts[0].lstrip())]
                parts[0] = lead + model_map[tok.lower()]
            val = ",".join(parts)
        elif field == "officer" and model_map:
            tok = val.strip()
            if tok.lower() in model_map:
                val = model_map[tok.lower()]
        elif field == "armour_ug_models" and model_map:
            parts = val.split(",")
            for i, p in enumerate(parts):
                t = p.strip()
                if t.lower() in model_map:
                    lead = p[:len(p) - len(p.lstrip())]
                    parts[i] = lead + model_map[t.lower()]
            val = ",".join(parts)

        rebuilt = prefix + val + ((" " + comment) if comment and not val.endswith(" ") else comment) + eol
        out_lines.append(rebuilt)
    return "".join(out_lines)


def block_fields(raw: str):
    """List (key, value) pairs for the editable field lines of a unit block.

    Repeated keys (e.g. multiple ``officer`` lines) are numbered key#2, key#3 so
    the field editor can address each. Comments/blank lines are skipped.
    """
    pairs = []
    counts: dict[str, int] = {}
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith(";"):
            continue
        k, vals = _split_fields(line)
        if not k:
            continue
        # recover the raw value text (after the key)
        stripped = line.strip()
        after = stripped[len(k):].lstrip() if stripped.lower().startswith(k.lower()) else ", ".join(vals)
        # strip trailing comment for display
        after, _ = _split_comment(after)
        counts[k] = counts.get(k, 0) + 1
        label = k if counts[k] == 1 else f"{k}#{counts[k]}"
        pairs.append((label, after))
    return pairs


def line_key(line: str) -> str:
    """Return the EDU field key of a line (handles 'banner faction', 'era 0', ...)."""
    s = line.strip()
    if not s or s.startswith(";"):
        return ""
    k, _ = _split_fields(line)
    return k


# Fields the base unit provides when using "use another unit as base".
# Everything else (identity + models + icons) stays from the transferred unit.
BASE_COPY_KEYS = [
    "category", "class", "voice_type", "banner faction", "banner holy", "accent",
    "formation", "move_speed_mod", "mount_effect",
    "stat_health", "stat_pri", "stat_pri_attr", "stat_sec", "stat_sec_attr",
    "stat_ter", "stat_ter_attr", "stat_pri_armour", "stat_sec_armour",
    "stat_heat", "stat_ground", "stat_mental", "stat_charge_dist",
    "stat_fire_delay", "stat_food", "stat_cost", "stat_stl",
    "recruit_priority_offset", "crusading_upkeep_modifier", "attributes",
    "ownership", "era 0", "era 1", "era 2",
]


def apply_base_template(unit_block: str, base_block: str,
                        copy_keys=BASE_COPY_KEYS) -> str:
    """Return the unit block with the given field lines taken from ``base_block``.

    Fields in ``copy_keys`` are replaced by the base's version (dropped if the base
    lacks them, appended if the base has them but the unit doesn't). All other lines
    (identity, models, icons, comments) are kept from ``unit_block``. Field order is
    not significant to the EDU parser except that ``type`` stays first.
    """
    keys = set(copy_keys)
    base_lines: dict[str, str] = {}
    for line in base_block.splitlines(keepends=True):
        k = line_key(line)
        if k in keys:
            base_lines[k] = line          # last occurrence wins
    out, inserted = [], set()
    for line in unit_block.splitlines(keepends=True):
        k = line_key(line)
        if k in keys:
            if k in base_lines and k not in inserted:
                out.append(base_lines[k]); inserted.add(k)
            # else: drop (base has no such field, or already inserted)
        else:
            out.append(line)
    # Base fields the unit didn't have must still be added — at the position the
    # BASE keeps them (accent after voice_type, era 2 after era 1, ...), not
    # dumped at the bottom of the block.
    base_order = _key_order(base_block)
    for key, line in base_lines.items():
        if key not in inserted:
            _insert_positioned(out, key, [line], base_order)
            inserted.add(key)
    return "".join(out)


def _key_order(block: str) -> List[str]:
    """Field keys in the order they first appear in a block."""
    order: List[str] = []
    for line in block.splitlines(keepends=True):
        k = line_key(line)
        if k and k not in order:
            order.append(k)
    return order


def _key_index(lines: List[str], key: str, last: bool = True) -> Optional[int]:
    idxs = [i for i, l in enumerate(lines) if line_key(l) == key]
    if not idxs:
        return None
    return idxs[-1] if last else idxs[0]


def _insert_positioned(out: List[str], key: str, new_lines: List[str],
                       ref_order: List[str]) -> None:
    """Insert ``new_lines`` for ``key`` into ``out`` using ``ref_order`` for placement.

    The slot is chosen by looking at what sits around ``key`` in the reference
    block: insert just after its nearest preceding neighbour that the target
    already has, else just before its nearest following one. Falls back to the
    end of the block (before trailing blank lines).
    """
    new_lines = [l if l.endswith("\n") else l + "\n" for l in new_lines]
    pos = None
    if key in ref_order:
        i = ref_order.index(key)
        for prev in reversed(ref_order[:i]):          # nearest preceding neighbour
            j = _key_index(out, prev, last=True)
            if j is not None:
                pos = j + 1
                break
        if pos is None:
            for nxt in ref_order[i + 1:]:             # else nearest following one
                j = _key_index(out, nxt, last=False)
                if j is not None:
                    pos = j
                    break
    if pos is None:                                   # append, before trailing blanks
        pos = len(out)
        while pos > 0 and not out[pos - 1].strip():
            pos -= 1
    if pos > 0 and out[pos - 1] and not out[pos - 1].endswith("\n"):
        out[pos - 1] += "\n"
    out[pos:pos] = new_lines


def copy_field_group(unit_block: str, base_block: str, key: str) -> str:
    """Replace EVERY ``key`` line in ``unit_block`` with every ``key`` line from
    ``base_block`` (dropping them all if the base has none).

    Unlike :func:`apply_base_template` this preserves repeated keys, so a base
    unit's full set of ``officer`` lines carries over rather than just the last.
    If the unit has no such field, the base's lines are inserted after the last
    real field line (never after the block's trailing blanks).
    """
    base_lines = [l if l.endswith("\n") else l + "\n"
                  for l in base_block.splitlines(keepends=True) if line_key(l) == key]
    out: List[str] = []
    found = inserted = False
    for line in unit_block.splitlines(keepends=True):
        if line_key(line) == key:
            found = True
            if not inserted:
                out.extend(base_lines)
                inserted = True
            continue                      # drop the unit's own line
        out.append(line)
    if not found and base_lines:
        # unit has no such field — place it where the base keeps it
        _insert_positioned(out, key, base_lines, _key_order(base_block))
    return "".join(out)


def add_attribute(block: str, attr: str) -> str:
    """Add ``attr`` to the block's ``attributes`` line (no-op if already listed).

    The rest of the line — order, spacing, trailing comment — is left alone; the
    attribute is appended to the end of the value list. If the unit has no
    ``attributes`` line at all, one is created.
    """
    out, done = [], False
    for line in block.splitlines(keepends=True):
        if not done and line_key(line) == "attributes":
            _, vals = _split_fields(line)
            if attr in vals:
                return block
            body = line.rstrip("\r\n")
            eol = line[len(body):] or "\n"
            head, comment = _split_comment(body)
            sep = ", " if head.split(None, 1)[1:] else "\t\t\t"
            out.append(f"{head}{sep}{attr}{(' ' + comment) if comment else ''}{eol}")
            done = True
        else:
            out.append(line)
    if not done:
        return set_field(block, "attributes", attr)
    return "".join(out)


def set_field(block: str, key: str, value: str) -> str:
    """Replace the value of field ``key`` in ``block`` (append the field if absent).

    ``value`` is the full text after the key (e.g. the whole CSV for stat_pri).
    Whitespace after the key is preserved when the field already exists.
    """
    out, done = [], False
    for line in block.splitlines(keepends=True):
        if not done and line_key(line) == key:
            body = line.rstrip("\r\n"); eol = line[len(body):] or "\n"
            # preserve leading indent + key + following whitespace
            stripped = body.lstrip()
            indent = body[:len(body) - len(stripped)]
            after_key = stripped[len(key):]
            ws = after_key[:len(after_key) - len(after_key.lstrip())] or "\t"
            out.append(f"{indent}{key}{ws}{value}{eol}")
            done = True
        else:
            out.append(line)
    if not done:
        body = "".join(out)
        if body and not body.endswith("\n"):
            body += "\n"
        out = [body, f"{key}\t\t\t{value}\n"]
    return "".join(out)


def strip_trailing_filler(block: str) -> str:
    """Drop trailing blank lines and comment-only lines from a unit block.

    A parsed block runs up to the next ``type`` line (see ``parse_text``), so it
    can end with blank lines and a decorative section-banner comment that
    actually introduces the NEXT unit in that file — noise that shouldn't be
    dragged along when this one unit is copied alone into a different file.
    """
    lines = block.splitlines(keepends=True)
    cut = 0
    for i in range(len(lines) - 1, -1, -1):
        s = lines[i].strip()
        if s and not s.startswith(";"):
            cut = i + 1
            break
    kept = "".join(lines[:cut])
    if kept and not kept.endswith("\n"):
        kept += "\n"
    return kept


def set_field_before(block: str, key: str, value: str, anchor_keys: tuple) -> str:
    """Like :func:`set_field`, but a NEWLY-added field is inserted right before
    the first line matching one of ``anchor_keys`` (falling back to right after
    the block's last real field line when none of them are present).

    Updating an already-present ``key`` behaves exactly like ``set_field`` —
    only the append path gets positioned.
    """
    if any(line_key(l) == key for l in block.splitlines(keepends=True)):
        return set_field(block, key, value)
    lines = block.splitlines(keepends=True)
    new_line = f"{key}\t\t\t{value}\n"
    for i, l in enumerate(lines):
        if line_key(l) in anchor_keys:
            if i > 0 and lines[i - 1] and not lines[i - 1].endswith("\n"):
                lines[i - 1] += "\n"
            lines.insert(i, new_line)
            return "".join(lines)
    # no anchor present — append right after the last real field line
    cut = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        s = lines[i].strip()
        if s and not s.startswith(";"):
            cut = i + 1
            break
    lines[cut:cut] = [new_line]
    return "".join(lines)


def rewrite_stat_projectile(block: str, name_map: dict) -> str:
    """Rewrite the projectile token (3rd CSV value) of stat_pri / stat_sec lines.

    ``name_map`` maps lowercased old projectile name -> new name. Only the 3rd
    comma-separated value is touched; all other spacing, values and the trailing
    comment are preserved byte-for-byte.
    """
    name_map = {k.lower(): v for k, v in name_map.items()}
    out: List[str] = []
    for line in block.splitlines(keepends=True):
        if line_key(line) not in ("stat_pri", "stat_sec"):
            out.append(line)
            continue
        body = line.rstrip("\r\n")
        eol = line[len(body):]
        # keep the "stat_pri<ws>" head intact, operate on the CSV remainder
        stripped = body.lstrip()
        indent = body[:len(body) - len(stripped)]
        key = stripped.split(None, 1)[0]
        after = stripped[len(key):]
        ws = after[:len(after) - len(after.lstrip())]
        csv = after[len(ws):]
        # split value from trailing ';' comment (the projectile slot is well before it)
        if ";" in csv:
            j = csv.index(";")
            values, comment = csv[:j], csv[j:]
        else:
            values, comment = csv, ""
        parts = values.split(",")
        if len(parts) > 2 and parts[2].strip().lower() in name_map:
            token = parts[2]
            lead = token[:len(token) - len(token.lstrip())]
            trail = token[len(token.rstrip()):]
            parts[2] = f"{lead}{name_map[token.strip().lower()]}{trail}"
            out.append(f"{indent}{key}{ws}{','.join(parts)}{comment}{eol}")
        else:
            out.append(line)
    return "".join(out)


# --- edit mode: in-place field editing -----------------------------------
# The order M2TW's own EDU files (and ModdingTool's UnitDb.AssignFields) keep
# fields in. Used to place a field the unit doesn't have yet in the slot a
# modder would expect, instead of dumping it at the bottom of the block.
CANONICAL_ORDER = [
    "type", "dictionary", "category", "class", "voice_type", "accent",
    "banner faction", "banner holy", "soldier", "officer", "ship", "engine",
    "mounted_engine", "animal", "mount", "mount_effect", "attributes",
    "move_speed_mod", "formation", "stat_health", "stat_pri", "stat_pri_ex",
    "stat_pri_attr", "stat_sec", "stat_sec_ex", "stat_sec_attr", "stat_ter",
    "stat_ter_ex", "stat_ter_attr", "stat_pri_armour", "stat_armour_ex",
    "stat_sec_armour", "stat_heat", "stat_ground", "stat_mental",
    "stat_charge_dist", "stat_fire_delay", "stat_food", "stat_cost", "stat_stl",
    "armour_ug_levels", "armour_ug_models", "ownership", "era 0", "era 1", "era 2",
    "recruit_priority_offset", "info_pic_dir", "card_pic_dir",
    "crusading_upkeep_modifier", "unit_info",
]


def split_label(label: str) -> tuple[str, int]:
    """``'officer#2'`` -> ``('officer', 2)``; a plain key -> ``(key, 1)``.

    ``block_fields`` numbers repeated keys this way, so the editor can address
    each individual ``officer`` / ``era`` line.
    """
    if "#" in label:
        head, _, tail = label.rpartition("#")
        if tail.isdigit():
            return head, int(tail)
    return label, 1


def _line_indices(block: str, key: str) -> List[int]:
    lines = block.splitlines(keepends=True)
    return [i for i, l in enumerate(lines) if line_key(l) == key]


def set_field_indexed(block: str, key: str, occurrence: int, value: str) -> str:
    """Replace the value of the ``occurrence``-th ``key`` line (1-based).

    Unlike :func:`set_field` this reaches repeated fields (``officer`` #2/#3).
    Indent, the whitespace after the key and any trailing comment are preserved;
    an absent field is added via :func:`add_field`.
    """
    lines = block.splitlines(keepends=True)
    idxs = _line_indices(block, key)
    if occurrence < 1 or occurrence > len(idxs):
        return add_field(block, key, value)
    i = idxs[occurrence - 1]
    body = lines[i].rstrip("\r\n")
    eol = lines[i][len(body):] or "\n"
    stripped = body.lstrip()
    indent = body[:len(body) - len(stripped)]
    after_key = stripped[len(key):]
    ws = after_key[:len(after_key) - len(after_key.lstrip())] or "\t"
    _, comment = _split_comment(after_key[len(ws):])
    lines[i] = f"{indent}{key}{ws}{value}{(' ' + comment) if comment else ''}{eol}"
    return "".join(lines)


def remove_field(block: str, key: str, occurrence: int = 1) -> str:
    """Delete the ``occurrence``-th ``key`` line outright (no-op if absent).

    Blanking a field's value is NOT the same as removing it — the game still
    parses the empty line — so the editor needs a real delete.
    """
    lines = block.splitlines(keepends=True)
    idxs = _line_indices(block, key)
    if occurrence < 1 or occurrence > len(idxs):
        return block
    del lines[idxs[occurrence - 1]]
    return "".join(lines)


def add_field(block: str, key: str, value: str) -> str:
    """Insert a field the block doesn't have, in its canonical EDU position."""
    out = block.splitlines(keepends=True)
    _insert_positioned(out, key, [f"{key}\t\t\t{value}"], CANONICAL_ORDER)
    return "".join(out)


def apply_field_edits(block: str, overrides: Dict[str, str],
                      removals=()) -> str:
    """Apply ``{label: value}`` edits and ``[label]`` deletions to one block.

    Labels are the ones :func:`block_fields` produces (``key`` / ``key#2``).
    Deletions are applied last and highest-occurrence-first, so removing
    ``officer#2`` can't shift the line ``officer#3`` refers to mid-flight.
    """
    out = block
    for label, value in (overrides or {}).items():
        key, occ = split_label(label)
        if not key:
            continue
        out = set_field_indexed(out, key, occ, value)
    for label in sorted(set(removals or ()),
                        key=lambda l: split_label(l)[1], reverse=True):
        key, occ = split_label(label)
        if key:
            out = remove_field(out, key, occ)
    return out


# Model slots an EDU block can point at a battle-models entry. ``soldier`` and
# ``armour_ug_models`` hold the model name inside a CSV list; ``officer`` lines
# hold it bare.
def set_model_slot(block: str, slot: str, name: str) -> str:
    """Point one model slot at ``name``.

    ``slot`` is ``soldier``, ``officer`` / ``officer#2``… or
    ``armour_ug_models#N`` (N = position in the CSV list; a position past the
    end appends). Everything else on the line is preserved.
    """
    key, occ = split_label(slot)
    if key == "officer":
        return set_field_indexed(block, "officer", occ, name)
    idxs = _line_indices(block, key)
    if not idxs:
        return add_field(block, key, name)
    lines = block.splitlines(keepends=True)
    i = idxs[0]
    body = lines[i].rstrip("\r\n")
    eol = lines[i][len(body):] or "\n"
    stripped = body.lstrip()
    indent = body[:len(body) - len(stripped)]
    after_key = stripped[len(key):]
    ws = after_key[:len(after_key) - len(after_key.lstrip())] or "\t"
    val, comment = _split_comment(after_key[len(ws):])
    parts = val.split(",")
    pos = 0 if key == "soldier" else occ - 1
    if pos < len(parts):
        lead = parts[pos][:len(parts[pos]) - len(parts[pos].lstrip())]
        parts[pos] = lead + name
    else:
        parts.append(" " + name)
    lines[i] = (f"{indent}{key}{ws}{','.join(parts)}"
                f"{(' ' + comment) if comment else ''}{eol}")
    return "".join(lines)
