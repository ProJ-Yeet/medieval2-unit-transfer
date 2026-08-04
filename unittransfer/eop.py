"""EOP units: EDU blocks that live *outside* export_descr_unit.txt.

M2TWEOP (the engine extender) lifts the game's 500-unit ceiling by loading extra
unit definitions from its own folder instead of from ``data/export_descr_unit.txt``.
Each of those files is plain EDU text — the same ``type`` / ``soldier`` /
``stat_pri`` block a normal unit has — it just is not in the EDU. That is the
whole difference, and it is why the rest of this tool can treat an EOP unit like
any other once it has been read: same parser, same model references, same icons,
same voice bank, same battle_models.modeldb entries.

What EOP units do *not* share is where they are written back. So the contract is:

  * :func:`parse` reads them and tags each one ``is_eop`` with the file it came
    from, and :class:`unittransfer.mod.Mod` merges them into ``mod.edu.units`` —
    which is what makes every feature EOP-aware without knowing it;
  * :meth:`unittransfer.edu.EduFile.to_text` emits only the *main* file's units,
    so nothing can accidentally paste an EOP unit into export_descr_unit.txt;
  * :func:`compose` is the one place that turns an edited unit list back into
    files: the main EDU plus one text per EOP file that actually changed.

Where the files are is a per-mod setting, exactly as ModdingTool models it (a list
of "EOP directories" saved against the mod). :func:`detect_dirs` guesses the usual
M2TWEOP layout so most mods need no setting up, and every ``.txt`` found is
checked with :func:`looks_like_units` before it is parsed — an EOP folder holds
scripts, JSON and notes as well as unit files, and misreading one of those as a
unit list would invent units that do not exist.
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field, replace as _replace
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from . import config
from . import edu as edu_mod

# Folder names M2TWEOP installs use, checked case-insensitively against every
# directory near the top of the mod. Detection is a convenience only — a mod that
# keeps its unit files somewhere else is handled by adding the folder in settings.
EOP_DIR_NAMES = ("eopdata", "eop_data", "eopdata_units", "eop")

# How deep below the mod root detection looks. M2TWEOP's folder sits beside
# ``data/``; three levels covers the "mods/<mod>/eopData/units" shapes as well
# without turning startup into a full tree walk of a 40 GB install.
DETECT_DEPTH = 3

# Directories never worth walking when looking for EOP unit files.
SKIP_DIRS = {".git", ".svn", "__pycache__", "node_modules", "backups"}

# A file only counts as a unit file when it has a `type` line AND one of the
# fields every real unit block carries. A lone `type` shows up in plenty of
# unrelated config text; the pair does not.
_TYPE_RE = re.compile(r"^[ \t]*type[ \t]+\S", re.MULTILINE | re.IGNORECASE)
_UNITISH_RE = re.compile(r"^[ \t]*(soldier|dictionary|stat_pri|category)[ \t]+\S",
                         re.MULTILINE | re.IGNORECASE)


# ---------------------------------------------------------------------------
# where the files are


def _key(root: Path) -> str:
    """The settings key for one mod — its resolved root, case-folded.

    Windows paths differ only in case all the time (the folder picker and a saved
    path rarely agree), and a settings entry that silently fails to match would
    look exactly like "EOP support is broken".
    """
    try:
        return str(root.resolve()).replace("\\", "/").casefold()
    except OSError:
        return str(root).replace("\\", "/").casefold()


def configured_dirs(mod) -> List[Path]:
    """EOP folders the user set for this mod, in the order they set them."""
    saved = (config.load_settings().get("eop_dirs") or {}).get(_key(Path(mod.root)))
    if not saved:
        return []
    out: List[Path] = []
    for raw in saved:
        try:
            p = Path(raw).expanduser()
        except (OSError, ValueError):
            continue
        if p not in out:
            out.append(p)
    return out


def set_configured_dirs(mod, dirs: Sequence[str]) -> List[str]:
    """Save this mod's EOP folders; an empty list falls back to detection."""
    settings = config.load_settings()
    table = dict(settings.get("eop_dirs") or {})
    cleaned = [str(Path(d).expanduser()) for d in dirs if str(d).strip()]
    if cleaned:
        table[_key(Path(mod.root))] = cleaned
    else:
        table.pop(_key(Path(mod.root)), None)
    config.save_settings(eop_dirs=table)
    return cleaned


def detect_dirs(mod) -> List[Path]:
    """EOP folders found by name under the mod root, shallowest first.

    ``data/`` is skipped: a folder in there called "eop" would be game data the
    engine reads itself, not the extender's own store, and walking it is the
    expensive part of the tree.
    """
    root = Path(mod.root)
    if not root.is_dir():
        return []
    found: List[Path] = []
    frontier = [(root, 0)]
    while frontier:
        cur, depth = frontier.pop(0)
        if depth >= DETECT_DEPTH:
            continue
        try:
            children = sorted((p for p in cur.iterdir() if p.is_dir()),
                              key=lambda p: p.name.lower())
        except OSError:
            continue
        for p in children:
            low = p.name.lower()
            if low in SKIP_DIRS or (depth == 0 and low == "data"):
                continue
            if low in EOP_DIR_NAMES:
                if p not in found:
                    found.append(p)
                continue              # its unit files are found by walking it later
            frontier.append((p, depth + 1))
    return found


def eop_dirs(mod) -> List[Path]:
    """The folders this mod's EOP units are read from and written back to.

    A saved setting wins outright — if the user named the folders, guessing more
    of them would write a transferred unit somewhere they did not ask for.
    """
    return configured_dirs(mod) or detect_dirs(mod)


def looks_like_units(text: str) -> bool:
    """True when a file's text is EDU unit blocks rather than something else."""
    return bool(_TYPE_RE.search(text)) and bool(_UNITISH_RE.search(text))


def _dirs_for(mod) -> List[Path]:
    """This mod's EOP folders, via ``Mod.eop_dirs`` when the caller passed a Mod.

    Detection is a bounded tree walk, and ``Mod.edu`` reaches this on every parse,
    so the cached property is used whenever there is one.
    """
    cached = mod.__dict__.get("eop_dirs") if hasattr(mod, "__dict__") else None
    return list(cached) if isinstance(cached, list) else eop_dirs(mod)


def unit_files(mod) -> List[Path]:
    """Every ``.txt`` under this mod's EOP folders that really holds unit blocks."""
    out: List[Path] = []
    seen: set = set()
    for base in _dirs_for(mod):
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.txt"), key=lambda p: str(p).lower()):
            if not p.is_file():
                continue
            if any(part.lower() in SKIP_DIRS for part in p.parts):
                continue
            try:
                key = str(p.resolve()).casefold()
            except OSError:
                key = str(p).casefold()
            if key in seen:
                continue
            seen.add(key)
            if looks_like_units(_read(p)):
                out.append(p)
    return out


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding=edu_mod.ENCODING)
    except OSError:
        return ""


def rel_to_root(mod, path) -> str:
    """A path shown to the user: relative to the mod root when it is inside it."""
    p = Path(path)
    root = Path(mod.root)
    try:
        return p.relative_to(root).as_posix()
    except ValueError:
        return p.as_posix()


# ---------------------------------------------------------------------------
# reading


@dataclass
class EopFile:
    """One parsed EOP unit file."""
    path: Path
    preamble: str                                    # text before the first `type`
    units: List["edu_mod.Unit"] = field(default_factory=list)


def parse(mod) -> Tuple[List["edu_mod.Unit"], Dict[str, str]]:
    """``(units, {file: preamble})`` for every EOP unit this mod defines.

    Each unit is tagged ``is_eop`` and carries the file it came from, so an edit
    to it can be written back to that same file rather than to the EDU. Order is
    file order within file-name order, which keeps the unit list stable between
    runs (the UI sorts it anyway, but a stable list makes diffs readable).
    """
    units: List["edu_mod.Unit"] = []
    preambles: Dict[str, str] = {}
    for path in unit_files(mod):
        text = _read(path)
        if not text:
            continue
        parsed = edu_mod.parse_text(text)
        key = str(path)
        preambles[key] = parsed.preamble
        for u in parsed.units:
            u.is_eop = True
            u.eop_file = key
            units.append(u)
    return units, preambles


# ---------------------------------------------------------------------------
# writing


@dataclass
class Split:
    """What a rewrite of the unit list means on disk.

    ``main`` and ``files`` hold only what actually *changed*, because every plan
    in this tool uses "" / empty to mean "leave that file alone" — a compose that
    always returned text would make every edit look like it rewrote the EDU.
    """
    main: str = ""                                   # "" = export_descr_unit.txt unchanged
    files: Dict[str, str] = field(default_factory=dict)   # abs path -> new text
    removed: List[str] = field(default_factory=list)      # abs paths with no units left

    def __bool__(self) -> bool:
        return bool(self.main or self.files or self.removed)


def compose(mod, units: Sequence["edu_mod.Unit"], *,
            main_preamble: Optional[str] = None) -> Split:
    """Turn an edited unit list back into the files it came from.

    ``units`` is the mod's WHOLE unit list after the edit — every block, EOP and
    main-file alike, in the order they should be written. Each unit goes back to
    the file it came from; a unit with no ``eop_file`` goes to the EDU.

    A file whose units are all gone is reported in ``removed`` rather than written
    empty: EOP unit files are one-unit-per-file in practice, so deleting the last
    unit means deleting the file, and leaving a stray header behind would keep the
    extender loading a file with nothing in it.
    """
    main_preamble = mod.edu.preamble if main_preamble is None else main_preamble
    preambles = getattr(mod.edu, "eop_preambles", {}) or {}

    main_blocks: List[str] = []
    by_file: Dict[str, List[str]] = {key: [] for key in preambles}
    for u in units:
        if u.is_eop and u.eop_file:
            by_file.setdefault(u.eop_file, []).append(u.raw)
        else:
            main_blocks.append(u.raw)

    split = Split()
    main_text = main_preamble + "".join(main_blocks)
    if main_text != mod.edu.to_text():
        split.main = main_text
    for key, blocks in by_file.items():
        path = Path(key)
        old = _read(path)
        if not blocks:
            if old:
                split.removed.append(key)
            continue
        text = preambles.get(key, "") + "".join(blocks)
        if text != old:
            split.files[key] = text
    return split


def write_split(mod, texts: Dict[str, str], removes: Sequence[str],
                backup_root: Path, manifest: dict) -> List[str]:
    """Write the EOP side of a plan, backing every touched file up first.

    EOP files sit *outside* ``data/``, and often outside the mod root altogether
    when the user pointed the setting at a shared folder — so the usual
    ``manifest["backed_up"]`` list, whose entries are resolved against
    ``<mod>/data/``, cannot describe them. They get their own manifest keys
    holding absolute paths plus the absolute path of each backup, which is all
    :func:`unittransfer.transfer.undo` needs to put them back.

    A removal is backed up and *then* unlinked, exactly like a deleted texture, so
    Undo restores a deleted unit's file rather than losing it.

    Returns the labels to show the user (mod-relative where possible).
    """
    backed = manifest.setdefault("ext_backed_up", [])
    created = manifest.setdefault("ext_created", [])
    written: List[str] = []

    def back_up(path: Path) -> None:
        n = len(backed) + len(created)
        bpath = backup_root / "eop" / f"{n:03d}_{path.name}"
        bpath.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, bpath)
        backed.append({"path": str(path), "backup": str(bpath)})

    for key, text in texts.items():
        path = Path(key)
        if path.exists():
            back_up(path)
        else:
            created.append(str(path))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding=edu_mod.ENCODING)
        written.append(rel_to_root(mod, path))
    for key in removes:
        path = Path(key)
        if not path.exists():
            continue
        back_up(path)
        try:
            path.unlink()
        except OSError:
            continue
        written.append(rel_to_root(mod, path) + " (removed)")
    return written


def restore_split(manifest: dict) -> None:
    """Undo counterpart of :func:`write_split`: put the EOP files back.

    Restoring a backup covers both an overwrite and a removal — the file is
    written back either way — and a file this plan created is deleted, the same
    shape :func:`unittransfer.transfer.undo` uses for everything under ``data/``.
    """
    for rec in manifest.get("ext_backed_up") or []:
        src, dst = Path(rec.get("backup", "")), Path(rec.get("path", ""))
        if not src.is_file() or not str(dst):
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        except OSError:
            pass
    for raw in manifest.get("ext_created") or []:
        try:
            p = Path(raw)
            if p.is_file():
                p.unlink()
        except OSError:
            pass


def edited(units: Iterable["edu_mod.Unit"], blocks: Dict[str, str],
           drop: Iterable[str] = ()) -> List["edu_mod.Unit"]:
    """The unit list with some blocks swapped and some units dropped, by ``type``.

    A convenience so every rewrite site can hand :func:`compose` a full unit list
    without hand-rolling the "keep everything, change these" loop — and, more to
    the point, without dropping the ``is_eop`` / ``eop_file`` tags that decide
    where each block gets written. Copies are made rather than mutating the cached
    parse, which must stay pristine for the next plan.
    """
    gone = {t for t in drop}
    out: List["edu_mod.Unit"] = []
    for u in units:
        if u.type in gone:
            continue
        raw = blocks.get(u.type)
        out.append(u if raw is None or raw == u.raw else _replace(u, raw=raw))
    return out


def rewrite_all(units: Iterable["edu_mod.Unit"], fn) -> List["edu_mod.Unit"]:
    """Every unit with ``fn(unit.raw)`` applied, tags kept (see :func:`edited`)."""
    out: List["edu_mod.Unit"] = []
    for u in units:
        raw = fn(u.raw)
        out.append(u if raw == u.raw else _replace(u, raw=raw))
    return out


def new_unit_file(mod, unit_type: str, target_dir=None) -> Optional[Path]:
    """Where a newly transferred EOP unit's own file should go, or None.

    One file per unit, named after the unit — that is what M2TWEOP installs look
    like and what makes an EOP unit findable by hand later. Returns None when the
    mod has no EOP folder at all, which is the caller's cue to fall back to the
    EDU rather than invent a folder the extender is not configured to read.
    """
    base = Path(target_dir) if target_dir else next(iter(_dirs_for(mod)), None)
    if base is None:
        return None
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", (unit_type or "unit").strip()) or "unit"
    cand = base / f"{stem}.txt"
    n = 2
    while cand.exists():
        cand = base / f"{stem}_{n}.txt"
        n += 1
    return cand


def unit_file_text(preamble: str, block: str) -> str:
    """The full text of a single-unit EOP file."""
    head = preamble if (not preamble or preamble.endswith("\n")) else preamble + "\n"
    body = block if block.endswith("\n") else block + "\n"
    return head + body
