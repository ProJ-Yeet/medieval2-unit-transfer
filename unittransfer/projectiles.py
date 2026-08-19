"""Parser/writer for data/descr_projectile.txt (M2TW projectile definitions).

A missile unit's ``stat_pri`` (or ``stat_sec``) names a projectile in its 3rd CSV
slot, e.g. ``stat_pri  11, 3, elite_arrow, 220, 20, missile, ...`` -> ``elite_arrow``.
That projectile is defined here:

    projectile elf_midtier_arrow

    effect                     arrows_new_set
    end_effect                 arrow_impact_ground_set
    ...
    damage      0
    velocity    30 50
    ...

So transferring a missile unit needs the projectile block too, or the game has a
dangling projectile reference. Blocks start at a line whose first token is
``projectile`` and run until the next one (or EOF). Each block's verbatim text is
kept so a transfer can append it (with only the effect lines rewritten).

Effects are NOT ported: the 7 ``effect``/``end_*`` lines reference effect-sets
defined in the source mod's descr_effect_impacts / arrow-trail files, which we do
not copy. Any effect-set the destination doesn't already define is rewritten to a
harmless placeholder so the projectile stays valid; the user re-adds real effects
by hand. ``;`` starts a comment.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from . import keyblock as kb

ENCODING = "latin-1"

# The projectile fields that reference an effect-set (and thus get the placeholder
# treatment when the destination doesn't define them).
EFFECT_KEYS = (
    "effect", "end_effect", "end_man_effect", "end_package_effect",
    "end_shatter_effect", "end_shatter_man_effect", "end_shatter_package_effect",
)
PLACEHOLDER = "invisible_placeholder_set"


def _strip_comment(s: str) -> str:
    return s.split(";", 1)[0].rstrip()


def _line_kv(line: str):
    """(key, value) for one line; ('', '') for blanks/comments."""
    body = _strip_comment(line).strip()
    if not body:
        return "", ""
    parts = body.split(None, 1)
    return parts[0], (parts[1].strip() if len(parts) > 1 else "")


@dataclass
class Projectile:
    name: str = ""
    flaming: str = ""                 # -> another projectile used as the fiery variant
    effects: Dict[str, str] = field(default_factory=dict)   # key -> effect-set name
    models: List[str] = field(default_factory=list)   # data-relative .cas model paths
    raw: str = ""                    # verbatim block text

    def content_key(self):
        """Everything defining the projectile EXCEPT its name (for dedup compare).

        Effect-set names are included: two projectiles with the same physics but
        different effects are genuinely different. The ``flaming`` reference is
        included too.
        """
        out = []
        for line in self.raw.splitlines():
            k, v = _line_kv(line)
            if k and k != "projectile":
                out.append((k.lower(), v.lower()))
        return tuple(out)

    def content_equals(self, other: "Projectile") -> bool:
        return self.content_key() == other.content_key()


@dataclass
class ProjectileFile:
    preamble: str = ""
    projectiles: List[Projectile] = field(default_factory=list)

    def by_name(self) -> Dict[str, Projectile]:
        return {p.name: p for p in self.projectiles}

    def get(self, name: str) -> Optional[Projectile]:
        if not name:
            return None
        exact = self.by_name().get(name)
        if exact is not None:
            return exact
        low = name.lower()                      # projectile names are case-insensitive
        for p in self.projectiles:
            if p.name.lower() == low:
                return p
        return None

    def to_text(self) -> str:
        return self.preamble + "".join(p.raw for p in self.projectiles)


def _parse_block(raw: str) -> Projectile:
    p = Projectile(raw=raw)
    for line in raw.splitlines():
        k, v = _line_kv(line)
        if k == "projectile" and not p.name:
            p.name = v
        elif k == "flaming" and not p.flaming:
            p.flaming = v
        elif k in EFFECT_KEYS and k not in p.effects:
            p.effects[k] = v
        elif k == "model" and v:
            # "model  data/models_missile/x.cas, 40" -> the .cas path (data-relative)
            path = v.split(",", 1)[0].strip().replace("\\", "/")
            if path.lower().startswith("data/"):
                path = path[5:]
            if path:
                p.models.append(path)
    return p


def parse_text(text: str) -> ProjectileFile:
    lines = text.splitlines(keepends=True)
    starts: List[int] = []
    for i, line in enumerate(lines):
        s = line.lstrip()
        if s.startswith(";"):
            continue
        if s.startswith("projectile") and (len(s) == 10 or s[10].isspace()):
            starts.append(i)
    if not starts:
        return ProjectileFile(preamble=text, projectiles=[])
    out = ProjectileFile(preamble="".join(lines[:starts[0]]))
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        out.projectiles.append(_parse_block("".join(lines[start:end])))
    return out


def parse_file(path: str | Path) -> ProjectileFile:
    p = Path(path)
    if not p.exists():
        return ProjectileFile()
    # Read WITHOUT letting the platform decide what a line ending is: `to_text`
    # is a pure splice of these raws, so whatever comes in goes back out. With
    # universal newlines a file mixing CRLF and lone LF (Third Age Reforged
    # ships one) came back longer than it went in, which is the one thing these
    # modules promise not to do.
    return parse_text(kb.read_text(p, ENCODING))


def unique_projectile_name(base: str, taken, tag: str = "") -> str:
    """A projectile name not already used in the destination."""
    existing = {t.lower() for t in taken}
    if base.lower() not in existing:
        return base
    cand = f"{base}_{tag}" if tag else f"{base}_copy"
    i = 2
    while cand.lower() in existing:
        cand = f"{base}_{tag}_{i}" if tag else f"{base}_copy_{i}"
        i += 1
    return cand


def rewrite_projectile_raw(raw: str, *, name_new: Optional[str] = None,
                           flaming_map: Optional[Dict[str, str]] = None,
                           valid_effects=None) -> str:
    """Return a copy of a block with the projectile renamed, ``flaming`` retargeted,
    and every effect-set the destination lacks replaced by the placeholder.

    ``valid_effects`` is a set of effect-set names present in the DESTINATION (lower
    case). When given, any of the 7 effect lines whose value isn't in it is rewritten
    to ``invisible_placeholder_set``. When ``None``, effects are left untouched.
    Indentation and trailing ``;`` comments are preserved.
    """
    flaming_map = {k.lower(): v for k, v in (flaming_map or {}).items()}
    valid = None if valid_effects is None else {e.lower() for e in valid_effects}
    out: List[str] = []
    done_name = False
    for line in raw.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        eol = line[len(body):]
        stripped = body.lstrip()
        indent = body[:len(body) - len(stripped)]
        # split trailing comment off the whole line body
        if ";" in stripped:
            i = stripped.index(";")
            content, comment = stripped[:i], stripped[i:]
        else:
            content, comment = stripped, ""
        ws_before_comment = content[len(content.rstrip()):]
        content = content.rstrip()
        parts = content.split(None, 1)
        key = parts[0] if parts else ""
        val = parts[1].strip() if len(parts) > 1 else ""

        new_val = None
        if key == "projectile" and name_new is not None and not done_name:
            new_val, done_name = name_new, True
        elif key == "flaming" and val.lower() in flaming_map:
            new_val = flaming_map[val.lower()]
        elif key in EFFECT_KEYS and valid is not None and val.lower() not in valid:
            new_val = PLACEHOLDER

        if new_val is None:
            out.append(line)
        else:
            sep = content[len(key):len(content) - len(content[len(key):].lstrip())]
            out.append(f"{indent}{key}{sep}{new_val}{ws_before_comment}{comment}{eol}")
    return "".join(out)


# --- destination effect-set registry -------------------------------------
_EFFECT_SET_RE = re.compile(r"^\s*effect_set\s+(\S+)", re.IGNORECASE)
# files that declare `effect_set <name>` entries a projectile may reference
_EFFECT_FILES = (
    "descr_effect_impacts.txt",
    "descr_arrow_trail_effects.txt",
    "descr_arrow_trail_custom_effects.txt",
    "descr_artillery_effects.txt",
)


def effect_sets(data_dir: Path) -> set:
    """Every ``effect_set`` name defined across a mod's effect files (lowercased)."""
    names: set = set()
    for fn in _EFFECT_FILES:
        p = data_dir / fn
        if not p.exists():
            continue
        try:
            for line in p.read_text(encoding=ENCODING).splitlines():
                m = _EFFECT_SET_RE.match(line)
                if m:
                    names.add(m.group(1).lower())
        except OSError:
            continue
    return names
