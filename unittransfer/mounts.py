"""Parser/writer for data/descr_mount.txt (M2TW mount definitions).

A unit's EDU ``mount`` field names a mount defined here, and that definition's
``model`` field names the battle_models.modeldb entry to use:

    type                gondor horse        ;;;;;  Gondor Cavalry
    class               horse
    model               mount_gondor_horse
    radius              1.2
    ...

So transferring a mounted unit needs THREE things in the destination: the EDU
block, this mount definition, and the mount's modeldb entry. Missing the mount
definition leaves a dangling ``mount`` reference and the unit never shows up.

Blocks start at a line whose first token is ``type`` (same shape as the EDU) and
run until the next one. Each block's verbatim text is kept so a transfer can
append it unchanged. ``;`` starts a comment.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

ENCODING = "latin-1"


def _strip_comment(s: str) -> str:
    return s.split(";", 1)[0].rstrip()


def _line_kv(line: str):
    """(key, value) for one descr_mount line; ('', '') for blanks/comments."""
    body = _strip_comment(line).strip()
    if not body:
        return "", ""
    parts = body.split(None, 1)
    return parts[0], (parts[1].strip() if len(parts) > 1 else "")


@dataclass
class Mount:
    type: str = ""
    mount_class: str = ""
    model: str = ""                  # -> battle_models.modeldb entry name
    raw: str = ""                    # verbatim block text

    def content_key(self):
        """Everything defining the mount EXCEPT its name (for dedup compare)."""
        out = []
        for line in self.raw.splitlines():
            k, v = _line_kv(line)
            if k and k != "type":
                out.append((k.lower(), v.lower()))
        return tuple(out)

    def content_equals(self, other: "Mount") -> bool:
        return self.content_key() == other.content_key()


@dataclass
class MountFile:
    preamble: str = ""
    mounts: List[Mount] = field(default_factory=list)

    def by_type(self) -> Dict[str, Mount]:
        return {m.type: m for m in self.mounts}

    def get(self, name: str) -> Optional[Mount]:
        if not name:
            return None
        exact = self.by_type().get(name)
        if exact is not None:
            return exact
        low = name.lower()                      # mount names are case-insensitive
        for m in self.mounts:
            if m.type.lower() == low:
                return m
        return None

    def to_text(self) -> str:
        return self.preamble + "".join(m.raw for m in self.mounts)


def _parse_block(raw: str) -> Mount:
    m = Mount(raw=raw)
    for line in raw.splitlines():
        k, v = _line_kv(line)
        if k == "type" and not m.type:
            m.type = v
        elif k == "class" and not m.mount_class:
            m.mount_class = v
        elif k == "model" and not m.model:
            m.model = v
    return m


def parse_text(text: str) -> MountFile:
    lines = text.splitlines(keepends=True)
    starts: List[int] = []
    for i, line in enumerate(lines):
        s = line.lstrip()
        if s.startswith(";"):
            continue
        if s.startswith("type") and (len(s) == 4 or s[4].isspace()):
            starts.append(i)
    if not starts:
        return MountFile(preamble=text, mounts=[])
    out = MountFile(preamble="".join(lines[:starts[0]]))
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        out.mounts.append(_parse_block("".join(lines[start:end])))
    return out


def parse_file(path: str | Path) -> MountFile:
    p = Path(path)
    if not p.exists():
        return MountFile()
    return parse_text(p.read_text(encoding=ENCODING))


def rewrite_mount_raw(raw: str, *, type_new: Optional[str] = None,
                      model_map: Optional[Dict[str, str]] = None) -> str:
    """Copy of a block with its ``type`` and/or ``model`` value rewritten.

    Indentation and trailing ``;`` comments are preserved; ``model_map`` is keyed
    by lowercased model name (modeldb entries are stored lowercased).
    """
    model_map = {k.lower(): v for k, v in (model_map or {}).items()}
    out: List[str] = []
    done_type = False
    for line in raw.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        eol = line[len(body):]
        stripped = body.lstrip()
        indent = body[:len(body) - len(stripped)]
        parts = stripped.split(None, 1)
        key = parts[0] if parts else ""
        rest = parts[1] if len(parts) > 1 else ""
        # split value from its trailing comment
        if ";" in rest:
            i = rest.index(";")
            value, comment = rest[:i], rest[i:]
        else:
            value, comment = rest, ""
        ws = value[len(value.rstrip()):]        # spacing before the comment
        val = value.rstrip()

        new_val = None
        if key == "type" and type_new is not None and not done_type:
            new_val, done_type = type_new, True
        elif key == "model" and val.lower() in model_map:
            new_val = model_map[val.lower()]

        if new_val is None:
            out.append(line)
        else:
            sep = stripped[len(key):len(stripped) - len(stripped[len(key):].lstrip())]
            out.append(f"{indent}{key}{sep}{new_val}{ws}{comment}{eol}")
    return "".join(out)


def unique_mount_name(base: str, taken, tag: str = "") -> str:
    """A mount name not already used in the destination."""
    existing = {t.lower() for t in taken}
    if base.lower() not in existing:
        return base
    cand = f"{base}_{tag}" if tag else f"{base}_copy"
    i = 2
    while cand.lower() in existing:
        cand = f"{base}_{tag}_{i}" if tag else f"{base}_copy_{i}"
        i += 1
    return cand
