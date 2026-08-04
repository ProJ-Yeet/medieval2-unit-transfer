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
    a standalone modeldb holding only the removed entries;
  * **drop dead mounts**: a ``descr_mount.txt`` definition no unit rides is a
    modeldb entry held alive by nothing, so removing the mount is usually what
    makes its model removable. Opt-in, and the removed blocks are exported too.

Why it matters: M2TW loads the entire modeldb into memory and big overhauls sit
near the engine's limits, so entries and meshes that nothing references cost real
budget. Nothing is deleted outright — everything moves to the export folder and
every touched file is backed up, so 🕑 Log → Undo restores the mod exactly.

What counts as "referenced":
  * ``export_descr_unit.txt`` — ``soldier`` / ``officer`` / ``armour_ug_models``
  * ``descr_mount.txt`` — a mount's model
  * ``descr_character.txt`` — ``battle_model`` (generals, agents)
  * every campaign's ``descr_strat.txt`` and ``campaign_script.txt`` —
    ``battle_model`` again, but written inline in a comma-separated character
    line rather than on its own, so those two files get a looser pattern
  * **every ``.lua`` script in the mod** — M2TWEOP mods create units, swap models
    and spawn characters from Lua, and none of that is written down in any
    ``.txt``. Any entry name a script mentions is off limits; see
    :mod:`unittransfer.luascan`.
  * anything else: any ``data/descr_*.txt`` that merely *mentions* the name is
    treated as a reference too, bar the two in :data:`DESCR_SKIP` that cannot
    name a battle model at all. That is deliberately over-cautious — a false
    "still used" costs nothing, a false "unused" silently breaks a mod.
"""
from __future__ import annotations

import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from . import config, edit, eop, luascan, modeldb
from . import edu as edu_mod
from . import mounts as mounts_mod
from .mod import Mod

# Slot kinds an entry can be referenced from. "soldier" is called out separately
# because it is the one the merge suggestions are about; OTHER_KINDS is "doing a
# real job somewhere a soldier merge cannot follow", which is every other kind —
# spelling it out that way means a new kind is covered everywhere by adding it here.
SLOT_KINDS = ("soldier", "officer", "armour", "mount", "character", "campaign")
OTHER_KINDS = tuple(k for k in SLOT_KINDS if k != "soldier")

# Name of the standalone modeldb written into the export folder. Deliberately NOT
# battle_models.modeldb: the export mirrors the mod's data/ tree so it can be
# copied back, and a file with that name would overwrite the real one.
EXPORT_DB_NAME = "removed_battle_models.modeldb"
EXPORT_MOUNTS_NAME = "removed_mounts.txt"   # the descr_mount.txt blocks, verbatim
UNUSED_SUBDIR = "unused_files"          # files no entry mentions at all
README_NAME = "README.txt"

# The campaign files that can name a battle model, relative to each campaign folder.
CAMPAIGN_FILES = ("descr_strat.txt", "campaign_script.txt")

# data/descr_*.txt files the over-cautious "somebody still mentions it" net skips.
# Everything else in that glob counts, so a file only belongs here when it CANNOT
# name a battle model or a mount — otherwise a false "unused" breaks a mod.
DESCR_SKIP = {
    # Where mounts are *defined*, not used: the only battle model a mount block
    # names is its `model` line, which `entry_users` already counts as a real
    # "mount" reference. Including it would make every mount's model look
    # "mentioned somewhere else" and the dead-mount pass could never free one.
    "descr_mount.txt",
    # Strat-map models only: its `model_flexi` / `texture` lines point at
    # data/models_strat, never at a unit_models battle model — so a name matching
    # in here is a coincidence, and one that pins a genuinely dead entry in place.
    "descr_model_strat.txt",
}

_TOKEN_RE = re.compile(r"[a-z0-9_.\-]+")
_COMMENT_RE = re.compile(r";[^\n]*")
# descr_character.txt puts `battle_model` on a line of its own...
_BATTLE_MODEL_RE = re.compile(r"^\s*battle_model\s+(\S+)", re.IGNORECASE | re.MULTILINE)
# ...but descr_strat.txt and campaign_script.txt write it inline, in the middle of
# a comma-separated character line ("character x, general, battle_model foo, ..."),
# so there it needs a comma to count as both a separator and a terminator.
_BATTLE_MODEL_INLINE_RE = re.compile(r"(?:^|[\s,])battle_model[\s,]+([^\s,]+)",
                                     re.IGNORECASE | re.MULTILINE)


# A scan / cleanup of a big mod is one multi-second call, so both take an optional
# ``(percent, label)`` sink the server exposes to the page — the bar then shows
# where the job really is instead of sitting at a made-up width.
Progress = Optional[Callable[[int, str], None]]


def _reporter(progress: Progress) -> Callable[[float, str], None]:
    """Wrap an optional sink so the callers below can report unconditionally.

    Reporting is never allowed to break the job it is describing, so a sink that
    raises (a poller's dict gone, anything) is swallowed.
    """
    def report(pct: float, label: str) -> None:
        if progress is None:
            return
        try:
            progress(max(0, min(100, int(pct))), label)
        except Exception:
            pass
    return report


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
    for name, where in _campaign_models(mod):
        add(name, "campaign", f"file:{where}")
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
        who = [short_referrer(w) for w in slots[kind]]
        if not who:
            continue
        shown = ", ".join(who[:3])
        if len(who) > 3:
            shown += f" and {len(who) - 3} more"
        parts.append(f"the {kind} model for {shown}")
    return "; ".join(parts)


def _kept_by_mention(name: str, row: dict, merge: bool = False) -> str:
    """The warning line for an entry a file or a script names by string.

    Worth spelling out rather than saying "still used": the reference is not in
    any unit's block, so the user looking at the mod would not find it — the point
    of the message is to name the file they should open.
    """
    what = "merge skipped" if merge else "kept"
    if row.get("lua"):
        why = ("a Lua script names it" if not row.get("in_comment")
               else "a Lua script names it (in a comment — left protected on purpose)")
        return (f"'{name}' — {what}: {why}, at {row['file']}. M2TWEOP scripts refer to "
                "battle models by name, so removing the entry would break that script "
                "the first time it runs.")
    return (f"'{name}' — {what}: {row['file']} names it. Nothing in the EDU points at "
            "it, but that file does, so it is left alone.")


def short_referrer(who: str) -> str:
    """``"mount:x"`` / ``"file:y"`` -> ``"x"`` / ``"y"``; a unit type is unchanged."""
    return who.split(":", 1)[1] if who.startswith(("mount:", "file:")) else who


def _character_models(mod: Mod) -> List[str]:
    """``battle_model`` names from descr_character.txt (generals and agents)."""
    path = mod.data / "descr_character.txt"
    if not path.is_file():
        return []
    return [m.group(1).lower() for m in _BATTLE_MODEL_RE.finditer(_read_text(path))]


def campaign_files(mod: Mod) -> List[Path]:
    """Every campaign's descr_strat.txt / campaign_script.txt.

    All campaign folders are walked, not just ``imperial_campaign`` — overhauls
    rename it, and a model kept alive only by an alternate campaign is exactly the
    kind of thing that must not be reported as dead.
    """
    base = mod.data / "world" / "maps" / "campaign"
    if not base.is_dir():
        return []
    out: List[Path] = []
    for folder in sorted(p for p in base.iterdir() if p.is_dir()):
        out += [folder / name for name in CAMPAIGN_FILES if (folder / name).is_file()]
    return out


def _campaign_models(mod: Mod) -> List[Tuple[str, str]]:
    """``(model name, "<campaign>/<file>")`` for every inline ``battle_model``.

    These name the model a *specific* character on the campaign map fights with —
    nothing in the EDU or descr_mount points at them, so without this pass they
    look completely unreferenced and the cleanup would happily delete them.
    Comments are stripped first: campaign_script.txt is mostly commented-out
    history in a mature mod, and a commented reference is not a reference.
    """
    out: List[Tuple[str, str]] = []
    for path in campaign_files(mod):
        text = _read_text(path)
        if not text:
            continue
        label = f"{path.parent.name}/{path.name}"
        for m in _BATTLE_MODEL_INLINE_RE.finditer(_COMMENT_RE.sub("", text)):
            out.append((m.group(1).strip().lower(), label))
    return out


def ridden_mounts(mod: Mod) -> set:
    """Lowercased mount names some unit's EDU ``mount`` line names."""
    return {u.mount.lower() for u in mod.edu.units if u.mount}


def _mount_mentions(mod: Mod,
                    report: Optional[Callable[[float, str], None]] = None) -> Dict[str, str]:
    """``mount name -> the file that mentions it``, for mounts.

    The same over-cautious net the entries get, but by whole name rather than by
    token: mount names contain spaces ("gondor horse"), so they cannot be looked
    up in :func:`_descr_tokens`. :data:`DESCR_SKIP` is left out for the reasons
    given there. The mod's Lua scripts are searched the same way — a mount a
    script hands to the engine is as ridden as one an EDU line names.

    Every name goes into ONE alternation so each file is scanned once. A regex per
    name per file is a hundred-odd passes over the same megabytes, and on a big
    mod that alone was most of the audit's running time.
    """
    names = [m.type for m in mod.mount_file.mounts if m.type]
    if not names:
        return {}

    # Whitespace in the name may be a tab in the file, and a name must not match as
    # a fragment of a longer one ("horse" inside "war horse"). `/ \ . -` are in the
    # boundary class as well so a name never matches a path segment — a mount called
    # "camel" is not a reference just because descr_skeleton.txt loads
    # animations/camel/Camel_Idle.CAS.
    def body(name: str) -> str:
        return r"\s+".join(re.escape(p) for p in name.lower().split())

    by_key = {" ".join(n.lower().split()): n for n in names}
    # longest alternative first, so at one position "war horse" beats "horse"
    alts = sorted((body(n) for n in names), key=len, reverse=True)
    rx = re.compile(r"(?<![a-z0-9_./\\-])(?:" + "|".join(alts) + r")(?![a-z0-9_./\\-])")

    paths = [p for p in sorted(mod.data.glob("descr_*.txt"))
             if p.name.lower() not in DESCR_SKIP]
    out: Dict[str, str] = {}
    for i, path in enumerate(paths):
        if report:
            report(i / (len(paths) or 1), path.name)
        text = _read_text(path).lower()
        if not text:
            continue
        for m in rx.finditer(text):
            name = by_key.get(" ".join(m.group(0).split()))
            if name is not None:
                out.setdefault(name, path.name)   # the first file that names it
    for name, hit in luascan.phrase_scan(mod, names).items():
        out.setdefault(name, hit.label())
    if report:
        report(1.0, "")
    return out


def mount_audit(mod: Mod, users: Dict[str, Dict[str, List[str]]],
                mentions: Dict[str, dict],
                report: Optional[Callable[[float, str], None]] = None
                ) -> Tuple[List[dict], List[dict]]:
    """``(mounts no unit rides, mounts held back because a descr_*.txt names one)``.

    ``frees_model`` on a row is the interesting part: it means removing that mount
    is the *only* thing keeping its modeldb entry alive, so ticking the mount lets
    the entry go with it. It is false when some other slot still names the model,
    when a second mount also names it and that one is staying, or when the entry is
    protected for any of the usual reasons.
    """
    if not mod.mount_file.mounts:
        return [], []
    ridden = ridden_mounts(mod)
    mentions = _mount_mentions(mod, report)
    entries = mod.modeldb.by_name()

    dead = [m for m in mod.mount_file.mounts
            if m.type and m.type.lower() not in ridden and m.type not in mentions]
    dead_low = {m.type.lower() for m in dead}

    rows: List[dict] = []
    for m in dead:
        model = (m.model or "").lower()
        slots = users.get(model) or {}
        others = [short_referrer(w) for k in SLOT_KINDS if k != "mount"
                  for w in slots.get(k, [])]
        # a model two mounts share only comes free when BOTH of them go
        other_mounts = [short_referrer(w) for w in slots.get("mount", [])
                        if short_referrer(w).lower() not in dead_low]
        entry = entries.get(model)
        frees = bool(model) and entry is not None and not others and not other_mounts \
            and not entry.first_entry_pad and model not in mentions
        rows.append({
            "mount": m.type,
            "class": m.mount_class,
            "model": m.model,
            "in_db": entry is not None,
            "frees_model": frees,
            "kept_by": (others + other_mounts)[:4],
            "mentioned_in": mention_file(mentions, model) if entry is not None else "",
        })
    rows.sort(key=lambda r: r["mount"].lower())
    held = [{"mount": name, "file": where} for name, where in sorted(mentions.items())]
    return rows, held


def _descr_tokens(mod: Mod) -> Dict[str, str]:
    """``token -> the descr_*.txt file it appeared in``, for the safety net.

    Every ``data/descr_*.txt`` is tokenised once (they are the only files that
    plausibly name a battle model outside the EDU), bar :data:`DESCR_SKIP`.
    Membership is then O(1) per entry instead of a scan per name, which matters on
    a 2000-entry modeldb.
    """
    out: Dict[str, str] = {}
    for path in sorted(mod.data.glob("descr_*.txt")):
        if path.name.lower() in DESCR_SKIP:
            continue
        text = _read_text(path).lower()
        if not text:
            continue
        for tok in set(_TOKEN_RE.findall(text)):
            out.setdefault(tok, path.name)
    return out


def name_mentions(mod: Mod,
                  report: Optional[Callable[[float, str], None]] = None
                  ) -> Dict[str, dict]:
    """``token -> {"file", "lua", "in_comment"}`` — the whole "somebody names it" net.

    Two sources, one lookup: the ``data/descr_*.txt`` token sweep
    (:func:`_descr_tokens`) and every ``.lua`` script in the mod
    (:func:`unittransfer.luascan.scan`). Membership in this dict is what keeps an
    entry off the unused list and what makes :func:`plan_cleanup` refuse to remove
    it, so a name a Lua script uses is protected by exactly the same machinery
    that already protects one a definition file uses — no separate code path to
    forget about.

    A definition file wins the label when both name a token: it is the more
    concrete answer to "why is this still here". The Lua hit is still recorded on
    the row, so the UI can show both.
    """
    # Prime ``Mod.lua_tokens`` by hand rather than just reading it: the first scan
    # is the slow one and it is the one that should drive the progress bar, but
    # every later caller (the cleanup that follows the audit) must get the cache.
    if "lua_tokens" not in mod.__dict__:
        mod.__dict__["lua_tokens"] = luascan.scan(mod, report)
    elif report:
        report(1.0, "")
    out: Dict[str, dict] = {}
    for tok, hit in mod.lua_tokens.items():
        out[tok] = {"file": hit.label(), "lua": True, "in_comment": hit.in_comment}
    for tok, where in _descr_tokens(mod).items():
        row = out.get(tok)
        if row is None:
            out[tok] = {"file": where, "lua": False, "in_comment": False}
        else:
            row["file"] = where            # the .txt is the better explanation
    return out


def mention_file(mentions: Dict[str, dict], name: str) -> str:
    """The "kept because …" label for a name, or ``""`` when nothing names it."""
    row = mentions.get((name or "").lower())
    return row["file"] if row else ""


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
                     unused: set, mentions: Optional[Dict[str, dict]] = None
                     ) -> List[dict]:
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

    A merge *deletes* its source entry, so anything ``mentions`` protects — a name
    some ``descr_*.txt`` or Lua script uses — is never offered as one. Repointing
    the EDU would not help there: the script still names the entry by string, and
    the entry would no longer be in the file to find.
    """
    entries = mod.modeldb.by_name()
    mentions = mentions or {}
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
        if any(slots[k] for k in OTHER_KINDS):
            continue                      # doing a real job somewhere else
        if name in mentions:
            continue                      # a script or a definition file names it
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
        options = options[:12]
        no_upgrades = [t for t in units
                       if not (by_type.get(t) and by_type[t].armour_ug_models)]
        out.append({
            "entry": name,
            "units": units,
            "into": preferred,
            "options": options,
            # per option, not just the default: the picker can be changed, and the
            # "already an armour tier" badge has to follow whatever is picked.
            "own_options": [n for n in options if n in own],
            "own_upgrade": preferred in own,
            "units_without_upgrades": no_upgrades,
            "files": _entry_files(entry),
            "lods": len(entry.lods),
            "skins": len(entry.main_textures),
        })
    return out


def orphan_files(mod: Mod, referenced: set,
                 report: Optional[Callable[[float, str], None]] = None) -> List[dict]:
    """Files under ``data/unit_models`` that no modeldb entry mentions at all.

    ``report`` is called with ``(fraction done, folder name)`` as the walk moves
    from one top-level folder to the next. That is why the tree is walked a folder
    at a time rather than with a single ``rglob``: this is the slowest part of the
    audit by far (tens of thousands of files on an overhaul), and one silent
    multi-second pause is exactly what the progress bar exists to avoid.
    """
    base = mod.unit_models_dir
    if not base.is_dir():
        return []
    try:
        tops = sorted(base.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        tops = []
    out: List[dict] = []
    total = len(tops) or 1
    for i, top in enumerate(tops):
        if report:
            report(i / total, top.name)
        for p in (top.rglob("*") if top.is_dir() else [top]):
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
    if report:
        report(1.0, "")
    out.sort(key=lambda x: x["rel"].lower())
    return out


def audit(mod: Mod, scan_orphans: bool = True, progress: Progress = None) -> dict:
    """Everything the cleanup dialog needs, in one pass over the mod.

    The percentages handed to ``progress`` are the shares each phase really takes
    on a big mod — parsing the modeldb and walking ``unit_models`` are most of the
    wait, and the walk reports its own way through as it goes.
    """
    say = _reporter(progress)
    say(3, "reading units, mounts, characters and campaign scripts")
    users = entry_users(mod)
    say(8, "reading data/descr_*.txt and the mod's .lua scripts")
    mentions = name_mentions(
        mod, lambda frac, where: say(8 + 12 * frac,
                                     f"reading .lua scripts{' — ' + where if where else ''}"))
    lua_count = len(mod.lua_files)
    say(20, "parsing battle_models.modeldb")
    entries = mod.modeldb.by_name()

    say(42, "listing the files every entry names")
    referenced_files = set()
    for e in mod.modeldb.entries:
        referenced_files.update(_norm(f) for f in _entry_files(e))

    say(48, f"checking {len(entries)} entries for references")
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
        row = mentions.get(e.name)
        if row:
            # named in a definition file we don't parse, in a comment in one we do,
            # or by a Lua script — keep it and say where, rather than guess it is
            # really dead
            mentioned.append({"entry": e.name, "file": row["file"],
                              "lua": row["lua"], "in_comment": row["in_comment"]})
            continue
        if e.first_entry_pad:
            mentioned.append({"entry": e.name, "file": "(padded first entry — never removed)",
                              "lua": False, "in_comment": False})
            continue
        unused_names.add(e.name)
        files = _entry_files(e)
        unused.append({"entry": e.name, "lods": len(e.lods),
                       "skins": len(e.main_textures), "files": files,
                       "copies": counts[e.name],
                       "on_disk": sum(1 for f in files if (mod.data / f).is_file())})

    say(56, "looking for entries with an identical twin")
    merges = merge_candidates(mod, users, unused_names, mentions)
    say(60, "walking data/unit_models")
    orphans = orphan_files(
        mod, referenced_files,
        lambda frac, where: say(60 + 25 * frac,
                                f"walking data/unit_models{'/' + where if where else ''}"),
    ) if scan_orphans else []
    say(85, "checking mounts no unit rides")
    dead_mounts, held_mounts = mount_audit(
        mod, users, mentions,
        lambda frac, where: say(85 + 14 * frac,
                                f"checking mounts no unit rides{' — ' + where if where else ''}"))
    say(100, "done")
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
        "unused_mounts": dead_mounts,
        "mentioned_mounts": held_mounts,
        "campaign_files": [f"{p.parent.name}/{p.name}" for p in campaign_files(mod)],
        # the Lua safety net, so the dialog can say what it protected and why
        "lua_files": lua_count,
        "lua_kept": [m for m in mentioned if m.get("lua")],
        "eop_units": len(mod.edu.eop_units),
        "eop_dirs": [str(p) for p in mod.eop_dirs],
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
    mentions = name_mentions(mod)
    counts = name_counts(mod)
    rows, seen = [], set()
    for e in mod.modeldb.entries:
        if e.name in seen:
            continue                       # one row per name, not per copy
        seen.add(e.name)
        slots = users.get(e.name) or {k: [] for k in SLOT_KINDS}
        refs = [w for k in SLOT_KINDS for w in slots[k]]
        # a name no slot uses but a descr_*.txt or a .lua still mentions is NOT
        # unused — say which file, so the row explains itself instead of looking blank
        row = mentions.get(e.name) if not refs else None
        mention = row["file"] if row else ""
        rows.append({
            "name": e.name,
            "lods": len(e.lods),
            "skins": len(e.main_textures),
            "used_by": refs[:12],
            "use_count": len(refs),
            "kinds": [k for k in SLOT_KINDS if slots[k]],
            "mentioned_in": mention,
            "mentioned_in_lua": bool(row and row["lua"]),
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
    labels = [f"{k}: {', '.join(short_referrer(w) for w in slots[k][:3])}"
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
    mounts: List[str] = field(default_factory=list)       # descr_mount.txt blocks to drop
    keep_shared_files: bool = True                # never move a file a kept entry uses


def cleanup_request_from_dict(d: dict) -> CleanupRequest:
    return CleanupRequest(
        target=(d.get("target") or "").strip(),
        entries=[str(x).lower() for x in (d.get("entries") or [])],
        merges=[{"entry": str(m.get("entry") or "").lower(),
                 "into": str(m.get("into") or "").lower()}
                for m in (d.get("merges") or []) if m.get("entry") and m.get("into")],
        orphans=[str(x).replace("\\", "/") for x in (d.get("orphans") or [])],
        mounts=[str(x) for x in (d.get("mounts") or []) if str(x).strip()],
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
    # M2TWEOP unit files a soldier merge repoints: {absolute path: new text}. An
    # EOP unit names battle models exactly like an EDU one, so a merge has to
    # follow it into its own file.
    eop_texts: Dict[str, str] = field(default_factory=dict)
    mount_text: str = ""                          # "" = descr_mount.txt is not rewritten
    mount_deletes: List[str] = field(default_factory=list)
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
    # The same re-check for the "somebody merely names it" net, Lua included. This
    # is the last line of defence rather than a duplicate of the audit: the audit
    # decides what to *offer*, this decides what may actually be written, and a
    # request can arrive from an older scan, a saved selection, or the CLI.
    mentions = name_mentions(mod)

    # ---- mounts nothing rides: dropped from descr_mount.txt FIRST, because that
    # is what takes the "mount" referrer off their model and lets the entry go.
    _plan_mounts(plan, users)

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
        held = mentions.get(name)
        if held:
            plan.warnings.append(_kept_by_mention(name, held))
            continue
        used = _describe_users(users, name)
        if used:
            # merges add their own entry to `doomed`, but only once the pairing
            # has passed every check below — being asked for is not enough.
            if name not in merging:
                slots = users.get(name) or {}
                only_mounts = bool(slots.get("mount")) and not any(
                    slots.get(k) for k in SLOT_KINDS if k != "mount")
                plan.warnings.append(
                    f"'{name}' is still {used} — kept, removing it would stop the game "
                    + ("loading. Tick that mount for removal too and the entry comes "
                       "free with it." if only_mounts else
                       "loading. Re-scan the mod to pick it up as a merge."))
            continue
        doomed.append(name)

    # ---- accepted soldier merges: repoint the EDU, then the entry joins the pile
    model_map: Dict[str, str] = {}
    for m in req.merges:
        name, into = m["entry"], m["into"]
        if name not in entries:
            plan.warnings.append(f"'{name}' is not in this mod's modeldb — merge skipped")
            continue
        if name in mentions:
            # A merge deletes `name`. Repointing the EDU does not help a script
            # that names it by string, so this pairing can never be safe.
            plan.warnings.append(_kept_by_mention(name, mentions[name], merge=True))
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
        blocks, touched = {}, []
        for u in mod.edu.units:
            if u.soldier_model and u.soldier_model.lower() in model_map:
                blocks[u.type] = edu_set_soldier(
                    u.raw, model_map[u.soldier_model.lower()])
                touched.append(u.type)
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
            # An M2TWEOP unit's soldier line is in that unit's own file, so the
            # repoint is split across the EDU and whichever EOP files are involved.
            split = eop.compose(mod, eop.edited(mod.edu.units, blocks))
            plan.edu_text = split.main
            plan.eop_texts = dict(split.files)
            for name, into in plan.merges:
                plan.changes.append(f"soldier model '{name}' -> '{into}'")
            plan.changes.append(
                f"{len(touched)} unit(s) rewritten: {', '.join(touched[:5])}"
                f"{'…' if len(touched) > 5 else ''}")
            for key in split.files:
                plan.changes.append(f"EOP unit file rewritten: {eop.rel_to_root(mod, key)}")

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

    if not (plan.entry_deletes or plan.exports or plan.mount_deletes):
        plan.changes.append("nothing to clean up")
    return plan


def _plan_mounts(plan: CleanupPlan, users: Dict[str, Dict[str, List[str]]]) -> None:
    """Work out the descr_mount.txt rewrite, and strip the referrers it removes.

    Mutates ``users`` in place: a mount that is going stops counting as a reason to
    keep its model, which is the whole point of offering the removal. Everything is
    re-checked against the mod — a unit that started riding the mount since the scan
    keeps it, because a dangling ``mount`` line stops the unit appearing at all, and
    so does a mount some ``descr_*.txt`` or Lua script names.

    The mention scan is only run when mounts were actually ticked: it reads every
    ``descr_*.txt`` and every script in the mod, and a cleanup that touches no
    mounts should not pay for that on each preview.
    """
    mod, req = plan.mod, plan.request
    if not req.mounts:
        return
    by_type = {m.type.lower(): m for m in mod.mount_file.mounts if m.type}
    ridden = ridden_mounts(mod)
    mentions = {k.lower(): v for k, v in _mount_mentions(mod).items()}
    keep: List[str] = []
    for want in dict.fromkeys(m.strip().lower() for m in req.mounts):
        mount = by_type.get(want)
        if mount is None:
            plan.warnings.append(f"mount '{want}' is not in this mod's descr_mount.txt — skipped")
            continue
        if want in mentions:
            plan.warnings.append(
                f"mount '{mount.type}' is named in {mentions[want]} — kept. Nothing in "
                "the EDU rides it, but that file does, so removing the block would "
                "break whatever reads it.")
            continue
        if want in ridden:
            riders = [u.type for u in mod.edu.units if u.mount.lower() == want]
            plan.warnings.append(
                f"mount '{mount.type}' is ridden by {', '.join(riders[:3])}"
                f"{'…' if len(riders) > 3 else ''} — kept, removing it would leave those "
                "units with a mount that does not exist")
            continue
        keep.append(mount.type)
    if not keep:
        return

    drop = {t.lower() for t in keep}
    plan.mount_deletes = keep
    plan.mount_text = mod.mount_file.preamble + "".join(
        m.raw for m in mod.mount_file.mounts if m.type.lower() not in drop)
    for slots in users.values():
        slots["mount"] = [w for w in slots["mount"]
                          if short_referrer(w).lower() not in drop]
    plan.changes.append(
        f"{len(keep)} mount{'' if len(keep) == 1 else 's'} removed from descr_mount.txt: "
        f"{', '.join(keep[:5])}{'…' if len(keep) > 5 else ''}")


def removed_mounts_text(mod: Mod, names: Sequence[str]) -> str:
    """The removed descr_mount.txt blocks, verbatim, for the export folder."""
    drop = {n.lower() for n in names}
    return "".join(m.raw for m in mod.mount_file.mounts if m.type.lower() in drop)


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

  {mounts}
      The {nm} descr_mount.txt block(s) that were removed, verbatim. No unit in the
      mod had a "mount" line naming them. Paste them back into data\\descr_mount.txt
      to restore them.

Undo: the removal itself is in the tool's log (the clock button) — "Undo" puts
every removed file and the original modeldb / export_descr_unit.txt back. This
folder is a copy and is never touched by Undo, so it is safe to keep or delete.
"""


# ---------------------------------------------------------------------------
# cleanup: apply


def apply_cleanup(plan: CleanupPlan, progress: Progress = None) -> Dict:
    """Write the cleanup: export first, then rewrite the mod (with backups)."""
    if plan.errors:
        raise ValueError("cannot apply: " + "; ".join(plan.errors))
    mod, target = plan.mod, plan.target
    if target is None:
        raise ValueError("cannot apply: no export folder")
    say = _reporter(progress)
    tid = config.new_transfer_id()
    backup_root = config.backup_root_for(tid)
    manifest: Dict[str, List[str]] = {"backed_up": [], "created": []}

    # 1) copy everything out BEFORE touching the mod, so a failure half-way
    #    leaves the mod intact rather than the assets gone and nowhere to be.
    target.mkdir(parents=True, exist_ok=True)
    n_exports = len(plan.exports)
    for i, (src, rel) in enumerate(plan.exports):
        # copying is most of the wall clock, and its total is known — so this is
        # the one part of the job whose bar is a straight count of real work.
        if i % 10 == 0:
            say(2 + 68 * i / n_exports, f"copying files out — {i}/{n_exports}")
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    say(70, "writing the export folder's modeldb")
    if plan.entry_deletes:
        (target / EXPORT_DB_NAME).write_text(
            export_modeldb_text(mod, plan.entry_deletes), encoding=modeldb.ENCODING)
    if plan.mount_deletes:
        (target / EXPORT_MOUNTS_NAME).write_text(
            removed_mounts_text(mod, plan.mount_deletes), encoding=mounts_mod.ENCODING)
    (target / README_NAME).write_text(
        _README.format(mod=mod.name, when=time.strftime("%Y-%m-%d %H:%M:%S"),
                       db=EXPORT_DB_NAME, n=len(plan.entry_deletes),
                       unused=UNUSED_SUBDIR, mounts=EXPORT_MOUNTS_NAME,
                       nm=len(plan.mount_deletes)),
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
        say(72, "rewriting export_descr_unit.txt")
        write_text("export_descr_unit.txt", plan.edu_text, edu_mod.ENCODING)
    if plan.eop_texts:
        say(73, "rewriting the M2TWEOP unit files")
        eop.write_split(mod, plan.eop_texts, (), backup_root, manifest)
    if plan.mount_text:
        say(74, "rewriting descr_mount.txt")
        write_text("descr_mount.txt", plan.mount_text, mounts_mod.ENCODING)
    if plan.modeldb_touched:
        say(76, "rewriting battle_models.modeldb")
        write_text("unit_models/battle_models.modeldb", _modeldb_without(plan),
                   modeldb.ENCODING)
    n_deletes = len(plan.deletes)
    for i, rel in enumerate(plan.deletes):
        if i % 10 == 0:
            say(84 + 15 * i / n_deletes, f"taking files out of the mod — {i}/{n_deletes}")
        t = mod.data / rel
        if t.exists():
            backup_and(rel)                     # backed up, then removed: Undo restores it
            try:
                t.unlink()
            except OSError as exc:
                plan.warnings.append(f"could not remove data/{rel}: {exc}")
    say(99, "writing the log entry")

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
        "resolved_type": ", ".join(
            [f"{n} {word}" for n, word in
             ((len(plan.entry_deletes),
               f"unused model entr{'y' if len(plan.entry_deletes) == 1 else 'ies'}"),
              (len(plan.mount_deletes),
               f"unused mount{'' if len(plan.mount_deletes) == 1 else 's'}"))
             if n]) or "nothing",
        "options": {"target": str(target), "merges": [list(m) for m in plan.merges],
                    "mounts": list(plan.mount_deletes)},
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
