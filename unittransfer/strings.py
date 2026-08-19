"""Strings mode — browse and edit a mod's compiled ``data/text/*.strings.bin``.

The codec lives in :mod:`unittransfer.stringsbin`; this module is the part that
knows about a *mod*: which archives it has, what state each one is in relative to
the ``.txt`` beside it, and how an edit gets to disk with the same backups and
undo as every other job in the toolkit.

Two things worth knowing before reading on.

**The ``.txt`` is not the truth.** The game reads the ``.bin``. A mod folder can
easily hold a ``.txt`` edited last week and a ``.bin`` compiled last year, and
the game will show you last year's text — that is the bug the "delete the .bin"
folklore exists to work around. So every file row carries whether the two are in
step, and ``rebuild`` is offered as an explicit action.

**Untagged archives are editable, but only by position.** ``battle``, ``shared``,
``strat`` and ``tooltips`` store bare strings the engine addresses by index (see
:mod:`unittransfer.stringsbin`). Their rows are handled as ``#<position>`` and
they get no Code View, because ``{tag}text`` is not a shape they have.
"""
from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import config, stringsbin
from .logutil import file_op, log

#: where a mod keeps its localisation, relative to ``data/``
TEXT_REL = "text"

#: rows returned by :func:`entries` when the caller does not ask for more — a
#: 20 757-entry ``names.txt`` is not a list anyone scrolls, it is one they search
PAGE = 400


class StringsError(Exception):
    """The request names a file or a row this mod does not have."""


# ---------------------------------------------------------------------------
# discovery


def text_dir(mod) -> Path:
    return mod.data / TEXT_REL


def archives(mod) -> List[Path]:
    """Every ``*.strings.bin`` in the mod's ``data/text``, sorted by name."""
    d = text_dir(mod)
    if not d.is_dir():
        return []
    return sorted(d.glob("*.strings.bin"), key=lambda p: p.name.lower())


def rel_of(mod, path: Path) -> str:
    return path.relative_to(mod.data).as_posix()


def resolve(mod, rel: str) -> Path:
    """The archive named by a request, refusing anything outside ``data/text``.

    The name arrives from the page, so it is treated as untrusted: resolved
    against the mod's own text folder and rejected if it lands anywhere else.
    """
    name = (rel or "").replace("\\", "/").strip("/")
    name = name[len(TEXT_REL) + 1:] if name.startswith(TEXT_REL + "/") else name
    if not name or "/" in name or not name.endswith(".strings.bin"):
        raise StringsError(f"{rel!r} is not a .strings.bin in data/text")
    path = text_dir(mod) / name
    if not path.exists():
        raise StringsError(f"{mod.name} has no data/{TEXT_REL}/{name}")
    return path


def _state(bin_path: Path) -> Dict:
    """How the archive and its ``.txt`` stand relative to one another."""
    txt = stringsbin.txt_path_for(bin_path)
    out: Dict = {"txt": txt.name if txt.exists() else "", "stale": False}
    if not txt.exists():
        return out
    try:
        out["stale"] = txt.stat().st_mtime > bin_path.stat().st_mtime + 1
    except OSError:
        pass
    return out


def overview(mod) -> Dict:
    """Every archive in the mod, with its size, entry count and ``.txt`` state.

    Only each file's 8-byte header is read (:func:`stringsbin.peek`) — the entry
    count lives there, and decoding a whole folder to draw a list costs half a
    second on Third Age for a number we already have.
    """
    files = []
    for p in archives(mod):
        row = {"rel": rel_of(mod, p), "name": p.name,
               "label": p.name[: -len(".strings.bin")],
               "size": p.stat().st_size, "entries": 0, "tagged": True, "error": ""}
        row.update(_state(p))
        try:
            head = stringsbin.peek(p)
        except (OSError, stringsbin.StringsBinError) as e:
            row["error"] = str(e)
        else:
            row["entries"] = head["count"]
            row["tagged"] = head["tagged"]
        files.append(row)
    return {"mod": mod.name, "dir": str(text_dir(mod)), "files": files}


# ---------------------------------------------------------------------------
# rows


def handle(tag: str, pos: int, tagged: bool = True) -> str:
    """How one row is addressed from the page: its tag, or ``#<position>``."""
    return tag if (tagged and tag) else f"#{pos}"


def entries(mod, rel: str, query: str = "", limit: int = PAGE,
            offset: int = 0) -> Dict:
    """One archive's rows, filtered and paged.

    Filtering happens here rather than in the page because the biggest archives
    run to five figures: sending 20 000 rows so the browser can hide 19 900 of
    them is the kind of thing that makes a local tool feel like a website.
    """
    path = resolve(mod, rel)
    sb = stringsbin.read(path)
    q = (query or "").strip().lower()
    rows = []
    for pos, (tag, value) in enumerate(sb.rows()):
        if q and q not in tag.lower() and q not in value.lower():
            continue
        rows.append({"pos": pos, "tag": tag, "id": handle(tag, pos, sb.tagged),
                     "value": value})
    total = len(rows)
    limit = max(0, int(limit or 0)) or total
    page = rows[offset:offset + limit]
    return {"mod": mod.name, "rel": rel_of(mod, path), "name": path.name,
            "tagged": sb.tagged, "count": len(sb), "matched": total,
            "offset": offset, "rows": page,
            "sorted": sb.sorted_ok(), "index": len(sb.index),
            **_state(path)}


def _split_ident(ident: str) -> Tuple[str, str]:
    """``"text/foo.txt.strings.bin|some_tag"`` -> ``(rel, row handle)``."""
    rel, sep, row = (ident or "").partition("|")
    if not sep:
        raise StringsError(
            f"{ident!r} does not name a row — expected <file>|<tag>")
    return rel, row


def locate(mod, ident: str) -> Tuple[str, str, int, str]:
    """``(rel, tag, position, value)`` for one row named ``<file>|<tag-or-#pos>``."""
    rel, row = _split_ident(ident)
    path = resolve(mod, rel)
    sb = stringsbin.read(path)
    if row.startswith("#"):
        try:
            pos = int(row[1:])
        except ValueError:
            raise StringsError(f"{row!r} is not a row position") from None
    else:
        pos = sb.index_of(row)
        if pos < 0:
            raise StringsError(f"{path.name} has no entry tagged {row!r}")
    if not 0 <= pos < len(sb):
        raise StringsError(f"{path.name} has no entry at position {pos}")
    tag = sb.tags[pos] if sb.tagged else ""
    return rel_of(mod, path), tag, pos, sb.values[pos]


def record_line(tag: str, value: str, pos: int = -1) -> str:
    """The ``{tag}text`` line a Code View shows for one row.

    Untagged archives have no such line and never get one — see the module
    docstring.
    """
    if not tag:
        raise StringsError(
            "this archive's entries have no tags, so there is no {tag}text form "
            "of them — edit the value in the box instead")
    return stringsbin.record_text(tag, value)


# ---------------------------------------------------------------------------
# plan -> apply


@dataclass
class StringsPlan:
    mod: object = None
    rel: str = ""
    path: Optional[Path] = None
    action: str = "edit"                 # 'edit' | 'rebuild'
    changes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    #: the bytes that would be written — empty when nothing would change
    data: bytes = b""
    before: int = 0
    after: int = 0

    def summary(self) -> str:
        head = (f"{self.action} {self.rel} in {getattr(self.mod, 'name', '?')} "
                f"({len(self.changes)} change(s))")
        return "\n".join([head] + [f"  {c}" for c in self.changes])

    def payload(self) -> Dict:
        return {"rel": self.rel, "action": self.action,
                "changes": list(self.changes), "warnings": list(self.warnings),
                "errors": list(self.errors), "bytes": len(self.data),
                "before": self.before, "after": self.after,
                "ok": not self.errors and bool(self.data)}


def plan(mod, body: dict) -> StringsPlan:
    """Work out the new bytes for an edit without touching the disk.

    ``body`` is ``{file, edits: [{id|pos, value}], adds: [{tag, value}],
    removes: [id]}``, or ``{file, action: 'rebuild'}`` to recompile the archive
    from the ``.txt`` beside it.
    """
    p = StringsPlan(mod=mod, action=str(body.get("action") or "edit"))
    try:
        path = resolve(mod, body.get("file") or "")
    except StringsError as e:
        p.errors.append(str(e))
        return p
    p.path = path
    p.rel = rel_of(mod, path)
    try:
        sb = stringsbin.read(path)
    except (OSError, stringsbin.StringsBinError) as e:
        p.errors.append(f"could not read {path.name}: {e}")
        return p
    p.before = len(sb)
    original = stringsbin.encode(sb)

    if p.action == "rebuild":
        return _plan_rebuild(p, sb, original)

    def row_pos(ident) -> int:
        if isinstance(ident, int):
            return ident
        s = str(ident or "")
        if s.startswith("#"):
            return int(s[1:])
        return sb.index_of(s)

    for e in (body.get("edits") or []):
        ident = e.get("id", e.get("pos"))
        pos = row_pos(ident)
        if pos < 0 or pos >= len(sb):
            p.errors.append(f"{path.name} has no entry {ident!r}")
            continue
        value = str(e.get("value") or "")
        if value == sb.values[pos]:
            continue
        label = sb.tags[pos] if sb.tagged else f"#{pos}"
        sb.set_value(pos, value)
        p.changes.append(f"{label}: {_clip(sb.values[pos])}")
    for a in (body.get("adds") or []):
        tag = str(a.get("tag") or "").strip()
        if not sb.tagged:
            p.errors.append("this archive's entries have no tags — nothing to add")
            break
        if not tag:
            p.errors.append("a new entry needs a tag")
            continue
        if sb.index_of(tag) >= 0:
            p.errors.append(f"{path.name} already has an entry tagged {tag!r}")
            continue
        sb.set(tag, str(a.get("value") or ""))
        p.changes.append(f"+ {tag}: {_clip(str(a.get('value') or ''))}")
    for r in (body.get("removes") or []):
        ident = r.get("id") if isinstance(r, dict) else r
        if not sb.tagged:
            p.errors.append(
                "this archive's entries are addressed by position, so removing one "
                "would renumber every entry after it — edit the value instead")
            break
        pos = row_pos(ident)
        if pos < 0 or pos >= len(sb):
            p.errors.append(f"{path.name} has no entry {ident!r}")
            continue
        tag = sb.tags[pos]
        sb.remove(tag)
        p.changes.append(f"- {tag}")
    if p.errors:
        return p
    p.after = len(sb)
    if sb.index and (p.after != p.before):
        p.warnings.append(
            f"the trailing tag index ({len(sb.index)} names) is carried through "
            "unchanged — the game rebuilds it when it recompiles the .txt")
    new = stringsbin.encode(sb)
    p.data = b"" if new == original else new
    if not p.data and not p.errors:
        p.warnings.append("nothing to change")
    return p


def _plan_rebuild(p: StringsPlan, sb, original: bytes) -> StringsPlan:
    txt = stringsbin.txt_path_for(p.path)
    if not sb.tagged:
        p.errors.append(f"{p.path.name} has no tags, so it cannot be built from a .txt")
        return p
    if not txt.exists():
        p.errors.append(f"there is no {txt.name} beside it to build from")
        return p
    try:
        made = stringsbin.compile_txt(txt.read_text(encoding=stringsbin.TXT_ENCODING), sb)
    except (OSError, UnicodeError, stringsbin.StringsBinError) as e:
        p.errors.append(f"could not read {txt.name}: {e}")
        return p
    p.after = len(made)
    was, now = sb.pairs(), made.pairs()
    added = [t for t in now if t not in was]
    gone = [t for t in was if t not in now]
    changed = [t for t in now if t in was and now[t] != was[t]]
    for t in changed[:20]:
        p.changes.append(f"{t}: {_clip(now[t])}")
    if len(changed) > 20:
        p.changes.append(f"…and {len(changed) - 20} more changed")
    if added:
        p.changes.append(f"+ {len(added)} entry(ies) the .txt has and the cache did not")
    if gone:
        p.changes.append(f"- {len(gone)} entry(ies) the .txt no longer has")
    new = stringsbin.encode(made)
    p.data = b"" if new == original else new
    if not p.data:
        p.warnings.append(f"{p.path.name} already matches {txt.name}")
    return p


def _clip(s: str, n: int = 60) -> str:
    one = s.replace("\n", "\\n")
    return one if len(one) <= n else one[: n - 1] + "…"


def apply(p: StringsPlan) -> Dict:
    """Write a planned archive, with the same backups and undo as any other job.

    The old bytes go to ``config/backups/<id>/data/…`` and the manifest goes in
    the transfer log, so 🕑 Log -> Undo puts the archive back byte-exact.
    """
    if p.errors:
        raise ValueError("cannot apply: " + "; ".join(p.errors))
    if not p.data:
        raise ValueError("nothing to change")
    mod = p.mod
    tid = config.new_transfer_id()
    backup_root = config.backup_root_for(tid)
    manifest: Dict[str, List[str]] = {"backed_up": [], "created": []}

    target = mod.data / p.rel
    bpath = backup_root / "data" / p.rel
    bpath.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.copy2(target, bpath)
        manifest["backed_up"].append(p.rel)
        file_op("BACKUP", target, f"-> {bpath}")
    else:
        manifest["created"].append(p.rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(p.data)
    file_op("WRITE", target, f"{len(p.data)} bytes, {p.after} entries")

    rec = {
        "id": tid,
        "when": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "strings",
        "action": p.action,
        "source": mod.name,
        "source_root": str(mod.root),
        "dest": mod.name,
        "dest_root": str(mod.root),
        "unit_type": p.rel,
        "resolved_type": p.rel,
        "options": {},
        "applied": True,
        "undone": False,
        "note": "",
        "summary": p.summary(),
        "warnings": list(p.warnings),
        "manifest": manifest,
        "backup_root": str(backup_root),
    }
    config.append_log(rec)
    log.info("STRING %s %s in %s — %d change(s), id=%s",
             p.action, p.rel, mod.name, len(p.changes), tid)
    return rec
