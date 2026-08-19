"""Unit packs: units in a zip you can hand to someone else.

The problem this solves is not "copy a unit" — :mod:`unittransfer.transfer`
already does that, and does it well: it resolves name collisions, follows armour
upgrades, brings the mount and its animation set, renames colliding projectiles,
fixes ownership and puts every touched file in the undo log. The problem is that
all of that only works when *both* mods are on the same machine.

So a pack is not a new format the importer has to understand. **A pack is a
mod.** The zip holds a real ``data/`` tree — an EDU with just those units, a
modeldb with just their entries, their meshes, textures, icons, voice lines and
whatever ``descr_*`` blocks they name — and importing one unzips it and hands it
to :func:`unittransfer.transfer.plan_transfer` as an ordinary source mod.

That is the whole design. Every check a normal transfer makes, a pack import
makes too, because it *is* a normal transfer; there is no second code path to
keep in step, and a pack built by an older version of the tool stays importable
for as long as the tool can read a mod at all.

What travels:

  ``unitpack.json``    which units, from which mod, when, by which version
  ``data/…``           the mini-mod, laid out exactly as a real one

What deliberately does not: anything the receiving mod already has to decide for
itself. A pack carries no ownership rewrites, no building recruit pools and no
opinion about which faction should field the unit — those are the importer's
options, and they are asked on the way in.
"""
from __future__ import annotations

import json
import shutil
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Set, Tuple

from . import bmdb, config, edu as edu_mod, localization, modeldb as modeldb_mod
from .logutil import log
from .mod import Mod

#: Bumped only when a pack stops being readable by the previous reader. The
#: layout is a mod, so in practice this stays at 1.
PACK_VERSION = 1
MANIFEST_NAME = "unitpack.json"

#: Files a pack may contain outside ``data/``. Anything else in the zip is
#: ignored on import — see :func:`_safe_members`.
_ALLOWED_TOP = {MANIFEST_NAME, "README.txt"}


class PackError(Exception):
    """Something the user can fix — surfaced in the UI, not a traceback."""


# ---------------------------------------------------------------------------
# what one unit drags along


def _model_names(mod: Mod, unit) -> List[str]:
    """Every modeldb entry a unit needs: its own models plus its mount's."""
    names = [n for n in unit.model_names() if n]
    if unit.mount:
        m = mod.mount_model(unit.mount)
        if m:
            names.append(m)
    seen: List[str] = []
    for n in names:
        if n.lower() not in {x.lower() for x in seen}:
            seen.append(n)
    return seen


def _entry_files(mod: Mod, names: Sequence[str]) -> List[Tuple[Path, str]]:
    """``(absolute source, path relative to data/)`` for every file those entries use.

    Missing files are skipped rather than raising: a mod that references vanilla
    art is normal, and the receiving end reports what it could not find with the
    same warning a same-machine transfer gives.
    """
    entries = mod.modeldb.by_name()
    out: List[Tuple[Path, str]] = []
    seen: Set[str] = set()
    for name in names:
        e = entries.get(name.lower())
        if e is None:
            continue
        for rel in list(e.mesh_files()) + list(e.texture_files()):
            rel = (rel or "").strip().replace("\\", "/")
            if not rel or rel == "0" or rel.lower() in seen:
                continue
            src = mod.data / rel
            if src.is_file():
                seen.add(rel.lower())
                out.append((src, rel))
    return out


def _icon_files(mod: Mod, unit) -> List[Tuple[Path, str]]:
    """The unit card and info card, where the mod actually has them."""
    out: List[Tuple[Path, str]] = []
    for p in (mod.find_unit_card(unit), mod.find_unit_info(unit)):
        if p and p.is_file():
            try:
                out.append((p, p.relative_to(mod.data).as_posix()))
            except ValueError:
                pass
    return out


# Voices deliberately do not travel. A unit's line in the voice bank is a name
# inside another faction's accent/class block, not a block of its own, so there
# is no honest way to lift one out — and the transfer already gives an imported
# unit a voice from the DESTINATION's bank, which is what you want anyway: a
# Mordor accent that does not exist in the receiving mod would be silence.


# ---------------------------------------------------------------------------
# plan


@dataclass
class PackPlan:
    mod: Mod
    units: List[object] = field(default_factory=list)      # edu.Unit
    missing: List[str] = field(default_factory=list)       # asked for, not in the mod
    models: List[str] = field(default_factory=list)
    assets: List[Tuple[Path, str]] = field(default_factory=list)
    icons: List[Tuple[Path, str]] = field(default_factory=list)
    mounts: List[str] = field(default_factory=list)
    projectiles: List[str] = field(default_factory=list)
    engines: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def bytes(self) -> int:
        total = 0
        for src, _ in self.assets + self.icons:
            try:
                total += src.stat().st_size
            except OSError:
                pass
        return total

    def summary(self) -> str:
        out = [f"pack {len(self.units)} unit(s) from {self.mod.name}",
               f"  {len(self.models)} battle-model entr(y/ies), "
               f"{len(self.assets)} asset file(s), {len(self.icons)} icon(s)"]
        for w in self.warnings:
            out.append("  ! " + w)
        return "\n".join(out)


def plan_pack(mod: Mod, unit_types: Sequence[str]) -> PackPlan:
    """Work out everything a pack would hold, without writing it."""
    plan = PackPlan(mod=mod)
    by_type = {u.type.lower(): u for u in mod.edu.units}
    for t in unit_types:
        u = by_type.get(str(t).strip().lower())
        if u is None:
            plan.missing.append(str(t))
        else:
            plan.units.append(u)
    if not plan.units:
        plan.warnings.append("none of those units are in this mod")
        return plan

    models: List[str] = []
    for u in plan.units:
        for n in _model_names(mod, u):
            if n.lower() not in {m.lower() for m in models}:
                models.append(n)
    plan.models = models

    known = mod.modeldb.by_name()
    for n in models:
        if n.lower() not in known:
            plan.warnings.append(
                f"'{n}' is not an entry in this mod's battle_models.modeldb — "
                "the pack cannot carry it")

    plan.assets = _entry_files(mod, models)
    for u in plan.units:
        plan.icons += _icon_files(mod, u)
        if not mod.find_unit_card(u):
            plan.warnings.append(f"{u.type} has no unit card in this mod — "
                                 "the import will have nothing to show on its row")
        if u.mount and mod.mount_def(u.mount) is None:
            plan.warnings.append(f"{u.type} rides '{u.mount}', which this mod's "
                                 "descr_mount.txt does not define")
    plan.mounts = sorted({u.mount for u in plan.units if u.mount})
    plan.projectiles = sorted({p for u in plan.units for p in u.projectiles()
                               if p and p.lower() != "no"})
    plan.engines = sorted({e for u in plan.units
                           for e in (u.engine, u.mounted_engine) if e})
    return plan


# ---------------------------------------------------------------------------
# write


def _blocks(names: Iterable[str], get) -> str:
    """Concatenate the verbatim ``descr_*`` blocks for ``names``."""
    out = []
    for n in names:
        for d in (get(n) or []):
            raw = getattr(d, "raw", "")
            if raw:
                out.append(raw if raw.endswith("\n") else raw + "\n")
    return "".join(out)


def _loc_text(mod: Mod, units: Sequence[object]) -> str:
    """A fresh export_units.txt holding only these units' three keys each."""
    text = ""
    for u in units:
        rec = mod.loc.get(u.dictionary)
        text = localization.upsert_record(
            text, u.dictionary,
            (rec.name if rec else "") or u.type,
            (rec.descr if rec else ""),
            (rec.descr_short if rec else ""))
    return text


def write_pack(plan: PackPlan, dest_zip: Path) -> dict:
    """Write the plan out as a zip. Returns a record for the caller to report."""
    if not plan.units:
        raise PackError(plan.warnings[0] if plan.warnings
                        else "nothing to pack")
    mod = plan.mod
    dest_zip = Path(dest_zip)
    dest_zip.parent.mkdir(parents=True, exist_ok=True)

    manifest = {
        "pack_version": PACK_VERSION,
        "tool": _tool_version(),
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source_mod": mod.name,
        "units": [{"type": u.type, "dictionary": u.dictionary,
                   "name": (mod.loc.get(u.dictionary).name
                            if mod.loc.get(u.dictionary) else "") or u.type,
                   "ownership": list(u.ownership),
                   "mount": u.mount, "eop": bool(getattr(u, "is_eop", False))}
                  for u in plan.units],
        "models": list(plan.models),
        "mounts": list(plan.mounts),
        "projectiles": list(plan.projectiles),
        "engines": list(plan.engines),
        "warnings": list(plan.warnings),
    }

    written = 0
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as z:
        def text(rel: str, body: str, encoding: str) -> None:
            nonlocal written
            if not body:
                return
            z.writestr(rel, body.encode(encoding))
            written += 1

        z.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2, ensure_ascii=False))
        z.writestr("README.txt", _README.format(
            mod=mod.name, when=manifest["created"],
            units="\n  ".join(f"{u['name']}  ({u['type']})" for u in manifest["units"])))

        # --- the mini-mod ---
        text("data/export_descr_unit.txt",
             mod.edu.preamble + "".join(u.raw for u in plan.units), edu_mod.ENCODING)
        text("data/text/export_units.txt", _loc_text(mod, plan.units),
             localization.ENCODING)
        text("data/unit_models/battle_models.modeldb",
             bmdb.export_modeldb_text(mod, plan.models), modeldb_mod.ENCODING)

        # descr_* blocks, verbatim and only the ones these units name. Each file
        # keeps its own preamble so the result parses like the real thing.
        mounts = _blocks(plan.mounts,
                         lambda n: [mod.mount_def(n)] if mod.mount_def(n) else [])
        if mounts:
            text("data/descr_mount.txt", mod.mount_file.preamble + mounts,
                 edu_mod.ENCODING)
        proj = _blocks(plan.projectiles,
                       lambda n: [mod.projectile_def(n)] if mod.projectile_def(n) else [])
        if proj:
            text("data/descr_projectile.txt", mod.projectile_file.preamble + proj,
                 edu_mod.ENCODING)
        eng = _blocks(plan.engines, mod.engine_defs)
        if eng:
            text("data/descr_engines.txt", mod.engine_file.preamble + eng,
                 edu_mod.ENCODING)
        meng = _blocks(plan.engines, mod.mounted_engine_defs)
        if meng:
            text("data/descr_mounted_engines.txt",
                 mod.mounted_engine_file.preamble + meng, edu_mod.ENCODING)
        # An engine names skeletons by string and the file is small, so it goes
        # whole rather than filtered — a missing skeleton is a broken engine.
        if (eng or meng) and mod.descr_engine_skeleton_path.is_file():
            try:
                z.write(mod.descr_engine_skeleton_path, "data/descr_engine_skeleton.txt")
                written += 1
            except OSError as e:
                log.warning("PACK  could not add descr_engine_skeleton.txt: %s", e)

        for src, rel in plan.assets + plan.icons:
            try:
                z.write(src, "data/" + rel)
                written += 1
            except OSError as e:
                log.warning("PACK  could not add %s: %s", src, e)

    size = dest_zip.stat().st_size
    log.info("PACK   %d unit(s) from %s -> %s (%d file(s), %.1f MB)",
             len(plan.units), mod.name, dest_zip, written, size / 1048576)
    return {"path": str(dest_zip), "files": written, "bytes": size,
            "units": [u.type for u in plan.units], "manifest": manifest,
            "warnings": list(plan.warnings)}


def _tool_version() -> str:
    try:
        from . import __version__
        return str(__version__)
    except Exception:
        return ""


_README = """\
Unit Transfer — unit pack
=========================

From: {mod}
When: {when}

Units in this pack:
  {units}

This zip is a miniature mod: everything under "data" is laid out exactly as a
real mod's data folder is. To use it, open Unit Transfer, pick the mod you want
the units in, and use "Import a unit pack" — the import runs the same checks,
conflict handling and options a normal transfer does, and lands in the same undo
log.

You do not have to use the tool. Unzipping this over a mod would technically put
the files in the right places, but the text files here hold ONLY these units, so
copying them over a real mod's export_descr_unit.txt or battle_models.modeldb
would wipe everything else in it. Use the importer.
"""


# ---------------------------------------------------------------------------
# read


def _safe_members(z: zipfile.ZipFile) -> List[zipfile.ZipInfo]:
    """Members that are safe to extract, i.e. plain files under data/ or the manifest.

    A zip can name ``../`` and absolute paths, and this one arrives from another
    person by design. Anything that does not resolve to a relative path inside
    ``data/`` (or one of the two files at the root) is dropped rather than
    sanitised — a pack should not contain one.
    """
    out: List[zipfile.ZipInfo] = []
    for info in z.infolist():
        if info.is_dir():
            continue
        name = info.filename.replace("\\", "/")
        if name.startswith("/") or ".." in name.split("/") or ":" in name:
            continue
        top = name.split("/", 1)[0]
        if top != "data" and name not in _ALLOWED_TOP:
            continue
        out.append(info)
    return out


def read_manifest(zip_path: Path) -> dict:
    """The pack's manifest, or a reconstructed one for a zip that has none."""
    zip_path = Path(zip_path)
    if not zip_path.is_file():
        raise PackError(f"{zip_path} does not exist")
    try:
        with zipfile.ZipFile(zip_path) as z:
            names = {i.filename.replace("\\", "/") for i in z.infolist()}
            if MANIFEST_NAME in names:
                return json.loads(z.read(MANIFEST_NAME).decode("utf-8"))
            if "data/export_descr_unit.txt" not in names:
                raise PackError(
                    "that zip is not a unit pack — it has no unitpack.json and no "
                    "data/export_descr_unit.txt")
    except zipfile.BadZipFile:
        raise PackError(f"{zip_path.name} is not a readable zip file")
    return {"pack_version": 0, "source_mod": "", "units": [], "created": ""}


def unpack(zip_path: Path, into: Path) -> Mod:
    """Extract a pack into ``into`` and return it as an ordinary :class:`Mod`.

    The caller owns ``into`` and is expected to delete it; :func:`import_source`
    wraps that up.
    """
    zip_path, into = Path(zip_path), Path(into)
    into.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path) as z:
            members = _safe_members(z)
            if not members:
                raise PackError(f"{zip_path.name} holds nothing a pack should hold")
            z.extractall(into, members=members)
    except zipfile.BadZipFile:
        raise PackError(f"{zip_path.name} is not a readable zip file")
    if not (into / "data").is_dir():
        raise PackError(f"{zip_path.name} has no data/ folder — it is not a unit pack")
    if not (into / "data" / "export_descr_unit.txt").is_file():
        raise PackError(f"{zip_path.name} carries no export_descr_unit.txt, so it "
                        "names no units")
    return Mod(into)


class import_source:
    """Context manager: a pack as a source :class:`Mod`, cleaned up afterwards.

    ::

        with pack.import_source(zip_path) as src:
            plan = transfer.plan_transfer(src, unit_type, dest, opts)

    The extracted folder lives under ``config/`` rather than the system temp dir,
    so a failed import leaves something the user can actually go and look at, and
    a stale one is obvious.
    """

    def __init__(self, zip_path: Path, keep: bool = False):
        self.zip_path = Path(zip_path)
        self.keep = keep
        self.root: Optional[Path] = None
        self.mod: Optional[Mod] = None

    def __enter__(self) -> Mod:
        stamp = time.strftime("%H%M%S")
        self.root = config.CONFIG_DIR / "packs" / f"_peek-{self.zip_path.stem}-{stamp}"
        shutil.rmtree(self.root, ignore_errors=True)
        self.mod = unpack(self.zip_path, self.root)
        return self.mod

    def __exit__(self, *exc):
        if self.root and not self.keep:
            shutil.rmtree(self.root, ignore_errors=True)
        return False


def pack_overview(zip_path: Path) -> dict:
    """What the import dialog shows before anything is unpacked for real."""
    manifest = read_manifest(zip_path)
    size = Path(zip_path).stat().st_size
    with import_source(zip_path) as src:
        units = []
        for u in src.edu.units:
            rec = src.loc.get(u.dictionary)
            units.append({
                "type": u.type,
                "dictionary": u.dictionary,
                "name": (rec.name.strip() if rec and rec.name else "") or u.type,
                "kind": u.kind(),
                "class": u.class_type,
                "category": u.category,
                "ownership": list(u.ownership),
                "mount": u.mount,
                "models": u.model_names(),
                "has_card": bool(src.find_unit_card(u)),
            })
        entries = [n for n in src.modeldb.by_name() if n]
    return {
        "path": str(zip_path),
        "bytes": size,
        "manifest": manifest,
        "units": units,
        "entries": entries,
        # a pack made by hand (or by an older build) has no manifest; it still
        # imports, because everything the importer needs is in the mod itself
        "has_manifest": bool(manifest.get("pack_version")),
    }
