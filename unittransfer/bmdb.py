"""Mod-wide battle_models.modeldb tools — the third mode of the app.

:mod:`unittransfer.edit` edits the modeldb entries *one unit* points at. This
module works on the file as a whole:

  * **browse / edit every entry**, not just a unit's — the payload it hands the
    UI is exactly the one the unit editor's model card renders
    (:func:`unittransfer.edit.model_payload`), and edits are planned by
    :func:`unittransfer.edit.plan_bmdb`, so both modes share one engine;
  * **audit** the file: which entries nothing references any more, which entries
    exist only because a unit's ``soldier`` line names them (and could be pointed
    at an existing twin instead), and which files under ``data/unit_models`` no
    entry mentions at all;
  * **clean up**: drop those entries from the mod's modeldb and *move* their
    files out into a folder of the user's choosing, mirroring the mod's own
    layout so the whole thing can be dropped back in later. That folder also gets
    a standalone modeldb holding only the removed entries.

Why it matters: M2TW loads the entire modeldb into memory and big overhauls sit
near the engine's limits, so entries and meshes that nothing references cost real
budget. Nothing is deleted outright — everything moves to the export folder and
every touched file is backed up, so 🕑 Log → Undo restores the mod exactly.

What counts as "referenced":
  * ``export_descr_unit.txt`` — ``soldier`` / ``officer`` / ``armour_ug_models``
  * ``descr_mount.txt`` — a mount's model
  * ``descr_character.txt`` — ``battle_model`` (generals, agents)
  * anything else: any ``data/descr_*.txt`` that merely *mentions* the name is
    treated as a reference too. That is deliberately over-cautious — a false
    "still used" costs nothing, a false "unused" silently breaks a mod.
"""
from __future__ import annotations

import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from . import config, edit, modeldb
from . import edu as edu_mod
from .mod import Mod

# Slot kinds an entry can be referenced from. "soldier" is called out separately
# because it is the one the merge suggestions are about.
SLOT_KINDS = ("soldier", "officer", "armour", "mount", "character")

# Name of the standalone modeldb written into the export folder. Deliberately NOT
# battle_models.modeldb: the export mirrors the mod's data/ tree so it can be
# copied back, and a file with that name would overwrite the real one.
EXPORT_DB_NAME = "removed_battle_models.modeldb"
UNUSED_SUBDIR = "unused_files"          # files no entry mentions at all
README_NAME = "README.txt"

_TOKEN_RE = re.compile(r"[a-z0-9_.\-]+")
_BATTLE_MODEL_RE = re.compile(r"^\s*battle_model\s+(\S+)", re.IGNORECASE | re.MULTILINE)


# ---------------------------------------------------------------------------
# who references what


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="latin-1")
    except OSError:
        return ""


def entry_users(mod: Mod) -> Dict[str, Dict[str, List[str]]]:
    """``entry name -> {slot kind: [referrers]}`` across every file that names one.

    A referrer is a unit type, a ``mount:<name>`` or a ``character:<type>`` — the
    thing the UI shows so "unused" can be checked by eye before anything moves.
    """
    users: Dict[str, Dict[str, List[str]]] = {}

    def add(name: str, kind: str, who: str) -> None:
        if not name:
            return
        slot = users.setdefault(name.lower(), {k: [] for k in SLOT_KINDS})
        if who not in slot[kind]:
            slot[kind].append(who)

    for u in mod.edu.units:
        add(u.soldier_model, "soldier", u.type)
        for o in u.officers:
            add(o, "officer", u.type)
        for a in u.armour_ug_models:
            add(a, "armour", u.type)
    for mount_name, model in (mod.mounts or {}).items():
        add(model, "mount", f"mount:{mount_name}")
    for name in _character_models(mod):
        add(name, "character", "file:descr_character.txt")
    return users


def _describe_users(users: Dict[str, Dict[str, List[str]]], name: str) -> str:
    """``"the soldier model for Gondor Infantry, …"``, or ``""`` if nothing names it.

    Phrased for a warning line, so the slot is named as well as the referrer: the
    whole point of the message is that the entry is not the dead weight the list
    it came from said it was.
    """
    slots = users.get(name)
    if not slots:
        return ""
    parts = []
    for kind in SLOT_KINDS:
        who = slots[kind]
        if not who:
            continue
        shown = ", ".join(who[:3])
        if len(who) > 3:
            shown += f" and {len(who) - 3} more"
        parts.append(f"the {kind} model for {shown}")
    return "; ".join(parts)


def _character_models(mod: Mod) -> List[str]:
    """``battle_model`` names from descr_character.txt (generals and agents)."""
    path = mod.data / "descr_character.txt"
    if not path.is_file():
        return []
    return [m.group(1).lower() for m in _BATTLE_MODEL_RE.finditer(_read_text(path))]


def _descr_tokens(mod: Mod) -> Dict[str, str]:
    """``token -> the descr_*.txt file it appeared in``, for the safety net.

    Every ``data/descr_*.txt`` is tokenised once (they are the only files that
    plausibly name a battle model outside the EDU). Membership is then O(1) per
    entry instead of a scan per name, which matters on a 2000-entry modeldb.
    """
    out: Dict[str, str] = {}
    for path in sorted(mod.data.glob("descr_*.txt")):
        text = _read_text(path).lower()
        if not text:
            continue
        for tok in set(_TOKEN_RE.findall(text)):
            out.setdefault(tok, path.name)
    return out


# ---------------------------------------------------------------------------
# the "footer": what makes two entries interchangeable as a soldier model


def footer_key(e: "modeldb.ModelEntry") -> tuple:
    """Everything after an entry's meshes and skins: animations and the torch.

    Two entries with the same footer are driven by the same skeletons and hold
    the same weapons, which is what has to match before one can stand in for the
    other. Meshes/textures are excluded on purpose — that is exactly the part the
    merge is meant to be free of.
    """
    return (tuple((a.mount_type, a.primary_skeleton, a.secondary_skeleton,
                   tuple(a.pri_weapons), tuple(a.sec_weapons)) for a in e.animations),
            e.torch_index, tuple(round(x, 4) for x in e.torch))


def _entry_files(e: "modeldb.ModelEntry") -> List[str]:
    return list(dict.fromkeys(e.mesh_files() + e.texture_files()))


def _norm(rel: str) -> str:
    return (rel or "").replace("\\", "/").strip().lower()


# ---------------------------------------------------------------------------
# audit


def _unit_index(mod: Mod) -> Dict[str, "object"]:
    return mod.edu.by_type()


def merge_candidates(mod: Mod, users: Dict[str, Dict[str, List[str]]],
                     unused: set) -> List[dict]:
    """Entries only a ``soldier`` line names, paired with an identical-footer twin.

    A unit that also lists ``armour_ug_models`` draws those models, so its
    ``soldier`` entry mostly exists to be named — pointing that line at an entry
    the mod already has frees a whole modeldb slot. Every pairing is a
    *suggestion*: it changes which model the line names, so the UI ticks them one
    by one (that is what the manual checkbox is for).

    A soldier line moved onto an entry the same cleanup then deletes is the one
    outcome M2TW will not start on, so only entries that are *referenced* are
    ever offered to move onto. Being referenced is what keeps an entry off the
    unused list and what makes ``plan_cleanup`` refuse to remove it, so a target
    picked here cannot go anywhere. Twins suggest each other, though, and a merge
    is the single way a referenced entry may still be dropped — so the pairings
    are worked out per footer group rather than one entry at a time. When a group
    has somewhere safe to land the whole group can go; when it does not, one
    member is held back to be the entry the others point at.
    """
    entries = mod.modeldb.by_name()
    by_type = _unit_index(mod)
    # Entries worth pointing at, grouped by footer: the ones something in the mod
    # still names. An entry nothing references is a removal away from not being
    # there -- including the ones held back merely because a descr_*.txt mentions
    # them, which never reach the `unused` list but are deletable all the same.
    twins: Dict[tuple, List[str]] = {}
    for e in mod.modeldb.entries:
        slots = users.get(e.name)
        if not (slots and any(slots[k] for k in SLOT_KINDS)):
            continue
        twins.setdefault(footer_key(e), []).append(e.name)

    # Who could be merged at all, before any of them is paired up.
    eligible: List[tuple] = []
    for name, slots in sorted(users.items()):
        if name in unused or not slots["soldier"]:
            continue
        if any(slots[k] for k in ("officer", "armour", "mount", "character")):
            continue                      # doing a real job somewhere else
        entry = entries.get(name)
        if entry is None:
            continue
        eligible.append((name, slots, entry, footer_key(entry)))

    # Per footer group: if some survivor is not itself eligible, everything in
    # the group can point at it. If they are all eligible the group would empty
    # itself out, so the last one keeps its slot and takes the others.
    grouped: Dict[tuple, List[str]] = {}
    for name, _slots, _entry, foot in eligible:
        grouped.setdefault(foot, []).append(name)
    sources: set = set()
    for foot, names in grouped.items():
        anchored = any(n not in names for n in twins.get(foot, []))
        sources.update(names if anchored else names[:-1])

    out: List[dict] = []
    for name, slots, entry, foot in eligible:
        if name not in sources:
            continue
        options = [n for n in dict.fromkeys(twins.get(foot, []))
                   if n != name and n not in sources]
        if not options:
            continue
        units = slots["soldier"]
        # Best twin: one the same unit already lists as an armour upgrade — the
        # unit is already drawing it, so the swap changes nothing on screen.
        own: List[str] = []
        for t in units:
            u = by_type.get(t)
            if u:
                own += [a.lower() for a in u.armour_ug_models]
        preferred = next((n for n in options if n in own), options[0])
        # the picker is capped, so the default has to be inside what it shows
        options = [preferred] + [n for n in options if n != preferred]
        no_upgrades = [t for t in units
                       if not (by_type.get(t) and by_type[t].armour_ug_models)]
        out.append({
            "entry": name,
            "units": units,
            "into": preferred,
            "options": options[:12],
            "own_upgrade": preferred in own,
            "units_without_upgrades": no_upgrades,
            "files": _entry_files(entry),
            "lods": len(entry.lods),
            "skins": len(entry.main_textures),
        })
    return out


def orphan_files(mod: Mod, referenced: set) -> List[dict]:
    """Files under ``data/unit_models`` that no modeldb entry mentions at all."""
    base = mod.unit_models_dir
    if not base.is_dir():
        return []
    out: List[dict] = []
    for p in base.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(mod.data).as_posix()
        # never offer a modeldb (the real one, or somebody's .modeldb backup) —
        # the whole audit is derived from it
        if ".modeldb" in p.name.lower() or _norm(rel) in referenced:
            continue
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        out.append({"rel": rel, "size": size})
    out.sort(key=lambda x: x["rel"].lower())
    return out


def audit(mod: Mod, scan_orphans: bool = True) -> dict:
    """Everything the cleanup dialog needs, in one pass over the mod."""
    users = entry_users(mod)
    tokens = _descr_tokens(mod)
    entries = mod.modeldb.by_name()

    referenced_files = set()
    for e in mod.modeldb.entries:
        referenced_files.update(_norm(f) for f in _entry_files(e))

    counts = name_counts(mod)
    unused: List[dict] = []
    unused_names: set = set()
    mentioned: List[dict] = []
    seen: set = set()
    for e in mod.modeldb.entries:
        if e.name in seen:
            continue                    # duplicate names are one piece of work
        seen.add(e.name)
        slots = users.get(e.name)
        if slots and any(slots[k] for k in SLOT_KINDS):
            continue
        where = tokens.get(e.name)
        if where:
            # named in a definition file we don't parse (or in a comment in one we
            # do) — keep it and say where, rather than guess it is really dead
            mentioned.append({"entry": e.name, "file": where})
            continue
        if e.first_entry_pad:
            mentioned.append({"entry": e.name, "file": "(padded first entry — never removed)"})
            continue
        unused_names.add(e.name)
        files = _entry_files(e)
        unused.append({"entry": e.name, "lods": len(e.lods),
                       "skins": len(e.main_textures), "files": files,
                       "copies": counts[e.name],
                       "on_disk": sum(1 for f in files if (mod.data / f).is_file())})

    merges = merge_candidates(mod, users, unused_names)
    orphans = orphan_files(mod, referenced_files) if scan_orphans else []
    return {
        "mod": mod.name,
        "root": str(mod.root),
        "entry_count": len(mod.modeldb.entries),
        "unused": unused,
        "mentioned": mentioned,
        "merges": merges,
        "orphans": orphans,
        "orphan_bytes": sum(o["size"] for o in orphans),
        "referenced_files": len(referenced_files),
    }


# ---------------------------------------------------------------------------
# entry browsing (bmdb mode's list + one entry's editor payload)


def name_counts(mod: Mod) -> Dict[str, int]:
    """How many entry blocks each name owns.

    Real mods do ship a modeldb with the same name twice (an entry pasted in
    again over the years). Nothing can tell the copies apart — a unit names a
    model by string — so every part of this module works per *name* and reports
    the copy count, rather than pretending they are separate models.
    """
    out: Dict[str, int] = {}
    for e in mod.modeldb.entries:
        out[e.name] = out.get(e.name, 0) + 1
    return out


def overview(mod: Mod) -> dict:
    """Every entry in the mod, light enough to render a few thousand rows."""
    users = entry_users(mod)
    tokens = _descr_tokens(mod)
    counts = name_counts(mod)
    rows, seen = [], set()
    for e in mod.modeldb.entries:
        if e.name in seen:
            continue                       # one row per name, not per copy
        seen.add(e.name)
        slots = users.get(e.name) or {k: [] for k in SLOT_KINDS}
        refs = [w for k in SLOT_KINDS for w in slots[k]]
        # a name no slot uses but a descr_*.txt still mentions is NOT unused —
        # say which file, so the row explains itself instead of looking blank
        mention = "" if refs else (tokens.get(e.name) or "")
        rows.append({
            "name": e.name,
            "lods": len(e.lods),
            "skins": len(e.main_textures),
            "used_by": refs[:12],
            "use_count": len(refs),
            "kinds": [k for k in SLOT_KINDS if slots[k]],
            "mentioned_in": mention,
            "copies": counts[e.name],
            "unused": not refs and not mention and not e.first_entry_pad,
            "folder": edit.folder_info(e)["base"],
        })
    return {"mod": mod.name, "count": len(mod.modeldb.entries), "names": len(rows),
            "entries": rows, "all_factions": edit.all_mod_factions(mod)}


def entry_detail(mod: Mod, name: str) -> dict:
    """One entry in the shape the editor's model card renders."""
    entry = mod.modeldb.by_name().get((name or "").lower())
    if entry is None:
        raise KeyError(f"model entry {name!r} not found in {mod.name}")
    slots = entry_users(mod).get(entry.name) or {k: [] for k in SLOT_KINDS}
    refs = [w for k in SLOT_KINDS for w in slots[k]]
    short = lambda w: w.split(":", 1)[1] if w.startswith(("mount:", "file:")) else w
    labels = [f"{k}: {', '.join(short(w) for w in slots[k][:3])}"
              f"{'…' if len(slots[k]) > 3 else ''}"
              for k in SLOT_KINDS if slots[k]]
    payload = edit.model_payload(entry, labels, refs)
    all_factions = edit.all_mod_factions(mod)
    return {
        "mod": mod.name,
        "model": payload,
        "model_names": sorted(mod.modeldb.by_name().keys()),
        "all_factions": all_factions,
        "faction_names": {f: mod.faction_names.get(f.lower(), "") for f in all_factions},
        "entry_count": len(mod.modeldb.entries),
    }


# ---------------------------------------------------------------------------
# cleanup: plan


@dataclass
class CleanupRequest:
    target: str                                   # absolute folder the assets move to
    entries: List[str] = field(default_factory=list)      # unused entries to remove
    merges: List[dict] = field(default_factory=list)      # [{"entry", "into"}] accepted
    orphans: List[str] = field(default_factory=list)      # data-relative files to move out
    keep_shared_files: bool = True                # never move a file a kept entry uses


def cleanup_request_from_dict(d: dict) -> CleanupRequest:
    return CleanupRequest(
        target=(d.get("target") or "").strip(),
        entries=[str(x).lower() for x in (d.get("entries") or [])],
        merges=[{"entry": str(m.get("entry") or "").lower(),
                 "into": str(m.get("into") or "").lower()}
                for m in (d.get("merges") or []) if m.get("entry") and m.get("into")],
        orphans=[str(x).replace("\\", "/") for x in (d.get("orphans") or [])],
        keep_shared_files=bool(d.get("keep_shared_files", True)),
    )


@dataclass
class CleanupPlan:
    mod: Mod
    request: CleanupRequest
    target: Optional[Path] = None
    entry_deletes: List[str] = field(default_factory=list)
    merges: List[Tuple[str, str]] = field(default_factory=list)   # (entry, into)
    edu_text: str = ""                            # "" = the EDU is not rewritten
    exports: List[Tuple[Path, str]] = field(default_factory=list)  # (src abs, rel in export)
    deletes: List[str] = field(default_factory=list)               # rel under data/
    kept_files: List[str] = field(default_factory=list)            # shared, left in place
    orphan_count: int = 0
    orphan_bytes: int = 0
    changes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def modeldb_touched(self) -> bool:
        return bool(self.entry_deletes)

    def summary(self) -> str:
        lines = [f"clean up {self.mod.name}'s battle_models.modeldb"]
        lines += ["  " + c for c in self.changes]
        lines += ["  ! " + w for w in self.warnings]
        return "\n".join(lines)


def _resolve_target(mod: Mod, raw: str) -> Tuple[Optional[Path], str]:
    """The export folder as an absolute path, refusing anywhere inside the mod.

    Exporting into the mod would move files from one part of it to another and
    then hand back a folder that is itself part of the mod — the opposite of
    taking the weight off it.
    """
    if not raw:
        return None, "choose a folder to move the unused assets into"
    try:
        target = Path(raw).expanduser().resolve()
    except OSError as exc:
        return None, f"bad destination: {exc}"
    if target == mod.root.resolve() or mod.root.resolve() in target.parents:
        return None, (f"'{target}' is inside {mod.name} — pick a folder outside the mod, "
                      "otherwise the files never actually leave it")
    if target.exists() and not target.is_dir():
        return None, f"'{target}' is a file, not a folder"
    return target, ""


def plan_cleanup(mod: Mod, req: CleanupRequest) -> CleanupPlan:
    """Work out exactly what a cleanup would remove, move and rewrite."""
    plan = CleanupPlan(mod=mod, request=req)
    target, err = _resolve_target(mod, req.target)
    plan.target = target
    if err:
        plan.errors.append(err)

    entries = mod.modeldb.by_name()
    # Removing an entry something still names breaks the game on load, so the
    # request is re-checked against the mod rather than trusted: a scan can be
    # older than the mod it describes. A `soldier` reference counts like any
    # other — the merge pass below is the only way a referenced entry may go, and
    # only because it repoints that soldier line first.
    users = entry_users(mod)
    merging = {m["entry"] for m in req.merges}
    doomed: List[str] = []
    for name in dict.fromkeys(req.entries):
        e = entries.get(name)
        if e is None:
            plan.warnings.append(f"'{name}' is not in this mod's modeldb — skipped")
            continue
        if e.first_entry_pad:
            plan.warnings.append(edit.PAD_ENTRY_KEPT.format(name=name))
            continue
        used = _describe_users(users, name)
        if used:
            # merges add their own entry to `doomed`, but only once the pairing
            # has passed every check below — being asked for is not enough.
            if name not in merging:
                plan.warnings.append(
                    f"'{name}' is still {used} — kept, removing it would stop the "
                    "game loading. Re-scan the mod to pick it up as a merge.")
            continue
        doomed.append(name)

    # ---- accepted soldier merges: repoint the EDU, then the entry joins the pile
    model_map: Dict[str, str] = {}
    for m in req.merges:
        name, into = m["entry"], m["into"]
        if name not in entries:
            plan.warnings.append(f"'{name}' is not in this mod's modeldb — merge skipped")
            continue
        if into not in entries:
            plan.errors.append(f"'{into}' is not in this mod's modeldb")
            continue
        if entries[name].first_entry_pad:
            plan.warnings.append(edit.PAD_ENTRY_KEPT.format(name=name))
            continue
        if into == name or into in merging or into in doomed:
            # Repointing a soldier line at something this same cleanup deletes
            # leaves it naming a model that is not in the file — exactly the
            # error the game refuses to start on. Footer twins suggest each
            # other, so a mutual pair is the way this happens.
            plan.errors.append(
                f"'{name}' would be pointed at '{into}', which this cleanup also "
                "removes — untick one of the two, they are twins of each other")
            continue
        if footer_key(entries[name]) != footer_key(entries[into]):
            plan.errors.append(
                f"'{name}' and '{into}' no longer have the same animations/torch "
                "footer — re-run the scan")
            continue
        model_map[name] = into
        plan.merges.append((name, into))
        if name not in doomed:
            doomed.append(name)

    if model_map:
        blocks, touched = [], []
        for u in mod.edu.units:
            hit = [s for s in ([u.soldier_model] if u.soldier_model else [])
                   if s.lower() in model_map]
            if hit:
                blocks.append(edu_set_soldier(u.raw, model_map[u.soldier_model.lower()]))
                touched.append(u.type)
            else:
                blocks.append(u.raw)
            # An entry only reachable through `soldier` cannot appear in another
            # slot — but a *different* unit could still name it, so anything left
            # pointing at a merged entry is a hard error rather than a silent break.
            leftovers = [m for m in u.model_names()
                         if m in model_map and m != (u.soldier_model or "").lower()]
            if leftovers:
                plan.errors.append(
                    f"'{u.type}' still names {', '.join(sorted(set(leftovers)))} outside "
                    "its soldier line — that entry cannot be merged away")
        if touched:
            plan.edu_text = mod.edu.preamble + "".join(blocks)
            for name, into in plan.merges:
                plan.changes.append(f"soldier model '{name}' -> '{into}'")
            plan.changes.append(
                f"{len(touched)} unit(s) rewritten: {', '.join(touched[:5])}"
                f"{'…' if len(touched) > 5 else ''}")

    plan.entry_deletes = doomed
    if doomed:
        # a name can own more than one block in the file; removing the name
        # removes every copy of it, so say what the file will really lose
        counts = name_counts(mod)
        blocks = sum(counts.get(n, 0) for n in doomed)
        total = len(mod.modeldb.entries)
        plan.changes.append(f"{len(doomed)} entr{'y' if len(doomed) == 1 else 'ies'} "
                            f"removed from battle_models.modeldb "
                            f"({total} -> {total - blocks})")
        extra = blocks - len(doomed)
        if extra:
            plan.changes.append(
                f"{extra} of those {'is a duplicate copy' if extra == 1 else 'are duplicate copies'}"
                " of a name already on the list — nothing can tell the copies apart, so all go")

    # ---- files: only the ones no surviving entry still uses
    drop = set(doomed)
    kept_files = set()
    for e in mod.modeldb.entries:
        if e.name not in drop:
            kept_files.update(_norm(f) for f in _entry_files(e))

    seen: set = set()
    for name in doomed:
        for rel in _entry_files(entries[name]):
            key = _norm(rel)
            if key in seen:
                continue
            seen.add(key)
            if key in kept_files:
                plan.kept_files.append(rel)
                continue
            src = mod.data / rel
            if not src.is_file():
                continue
            plan.exports.append((src, f"data/{rel}"))
            plan.deletes.append(rel)
    if plan.exports:
        plan.changes.append(f"{len(plan.exports)} asset file(s) moved to the export folder")
    if plan.kept_files:
        plan.changes.append(f"{len(plan.kept_files)} file(s) left in the mod — "
                            "entries that stay still use them")
    if any(f.lower().endswith(".spr") for _s, f in plan.exports):
        plan.warnings.append(
            "sprite (.spr) files were exported — their companion sprite sheet is "
            "not named in the modeldb, so check data/unit_sprites before deleting "
            "anything from the export folder by hand.")

    # ---- files nothing in the modeldb mentions
    for rel in dict.fromkeys(req.orphans):
        src = mod.data / rel
        if not src.is_file():
            plan.warnings.append(f"data/{rel} is not on disk — skipped")
            continue
        try:
            plan.orphan_bytes += src.stat().st_size
        except OSError:
            pass
        plan.exports.append((src, f"{UNUSED_SUBDIR}/data/{rel}"))
        plan.deletes.append(rel)
        plan.orphan_count += 1
    if plan.orphan_count:
        plan.changes.append(
            f"{plan.orphan_count} file(s) no entry mentions moved to "
            f"{UNUSED_SUBDIR}/ ({plan.orphan_bytes / 1048576:.1f} MB)")

    if not (plan.entry_deletes or plan.exports):
        plan.changes.append("nothing to clean up")
    return plan


def edu_set_soldier(block: str, name: str) -> str:
    """Point a unit block's ``soldier`` line at ``name`` (rest of the line kept)."""
    return edu_mod.set_model_slot(block, "soldier", name)


# ---------------------------------------------------------------------------
# cleanup: the standalone modeldb written next to the exported files


def export_modeldb_text(mod: Mod, names: Sequence[str]) -> str:
    """A loadable modeldb holding only ``names``, in their original file order.

    Reuses each entry's verbatim source text, so the export is byte-identical to
    what was cut out of the mod — that is what makes copying it back safe.
    """
    drop = {n.lower() for n in names}
    kept = [e for e in mod.modeldb.entries if e.name in drop]
    src = mod.modeldb
    blank = src.blank_raw
    if not blank and not (kept and kept[0].first_entry_pad):
        # This mod's file has no `blank` sentinel, so its own first entry carries
        # the reserved padding. Whatever we exported does not, so give the export
        # a sentinel of its own instead — otherwise nothing could read it back.
        blank = "5 blank" + " 0" * 39 + "\n"
    db = modeldb.ModelDb(header_ints=list(src.header_ints), blank_raw=blank,
                         entries=kept, trailing=src.trailing, header_raw="")
    return db.to_text()


_README = """\
Unit Transfer — battle-model cleanup export
===========================================

Moved out of: {mod}
When:         {when}

  {db}
      A standalone battle_models.modeldb holding ONLY the {n} entries that were
      removed. Not called battle_models.modeldb on purpose, so it can never
      overwrite a real one by accident.

  data\\...
      The mesh / texture / sprite files those entries used, in the same layout
      they had inside the mod. To put them back, copy this "data" folder over
      the mod's own data folder and paste the entries from {db} back into the
      mod's battle_models.modeldb (and fix the entry count in its header line).

  {unused}\\data\\...
      Files that were sitting under data\\unit_models but were not named by ANY
      entry in the modeldb, removed or kept. Nothing referenced them.

Undo: the removal itself is in the tool's log (the clock button) — "Undo" puts
every removed file and the original modeldb / export_descr_unit.txt back. This
folder is a copy and is never touched by Undo, so it is safe to keep or delete.
"""


# ---------------------------------------------------------------------------
# cleanup: apply


def apply_cleanup(plan: CleanupPlan) -> Dict:
    """Write the cleanup: export first, then rewrite the mod (with backups)."""
    if plan.errors:
        raise ValueError("cannot apply: " + "; ".join(plan.errors))
    mod, target = plan.mod, plan.target
    if target is None:
        raise ValueError("cannot apply: no export folder")
    tid = config.new_transfer_id()
    backup_root = config.backup_root_for(tid)
    manifest: Dict[str, List[str]] = {"backed_up": [], "created": []}

    # 1) copy everything out BEFORE touching the mod, so a failure half-way
    #    leaves the mod intact rather than the assets gone and nowhere to be.
    target.mkdir(parents=True, exist_ok=True)
    for src, rel in plan.exports:
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    if plan.entry_deletes:
        (target / EXPORT_DB_NAME).write_text(
            export_modeldb_text(mod, plan.entry_deletes), encoding=modeldb.ENCODING)
    (target / README_NAME).write_text(
        _README.format(mod=mod.name, when=time.strftime("%Y-%m-%d %H:%M:%S"),
                       db=EXPORT_DB_NAME, n=len(plan.entry_deletes),
                       unused=UNUSED_SUBDIR),
        encoding="utf-8")

    # 2) now rewrite the mod, backing up every file first
    def backup_and(rel: str) -> Path:
        t = mod.data / rel
        if t.exists():
            bpath = backup_root / "data" / rel
            bpath.parent.mkdir(parents=True, exist_ok=True)
            if not bpath.exists():
                shutil.copy2(t, bpath)
            manifest["backed_up"].append(rel)
        else:
            manifest["created"].append(rel)
        return t

    def write_text(rel: str, text: str, encoding: str) -> None:
        t = backup_and(rel)
        t.parent.mkdir(parents=True, exist_ok=True)
        t.write_text(text, encoding=encoding)

    if plan.edu_text:
        write_text("export_descr_unit.txt", plan.edu_text, edu_mod.ENCODING)
    if plan.modeldb_touched:
        write_text("unit_models/battle_models.modeldb", _modeldb_without(plan),
                   modeldb.ENCODING)
    for rel in plan.deletes:
        t = mod.data / rel
        if t.exists():
            backup_and(rel)                     # backed up, then removed: Undo restores it
            try:
                t.unlink()
            except OSError as exc:
                plan.warnings.append(f"could not remove data/{rel}: {exc}")

    rec = {
        "id": tid,
        "when": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "bmdb",
        "action": "cleanup",
        "source": mod.name,
        "source_root": str(mod.root),
        "dest": mod.name,
        "dest_root": str(mod.root),
        "unit_type": "",
        "resolved_type": f"{len(plan.entry_deletes)} unused model entr"
                         f"{'y' if len(plan.entry_deletes) == 1 else 'ies'}",
        "options": {"target": str(target), "merges": [list(m) for m in plan.merges]},
        "applied": True,
        "undone": False,
        "note": "",
        "summary": plan.summary(),
        "warnings": list(plan.warnings),
        "manifest": manifest,
        "backup_root": str(backup_root),
        "export_root": str(target),
    }
    config.append_log(rec)
    edit._invalidate(mod)
    return rec


def _modeldb_without(plan: CleanupPlan) -> str:
    """The mod's modeldb with the removed entries gone (header count follows)."""
    db = plan.mod.modeldb
    drop = set(plan.entry_deletes)
    original = list(db.entries)
    try:
        db.entries = [e for e in original if e.name not in drop]
        return db.to_text()
    finally:
        db.entries = original              # keep the cached parse pristine
