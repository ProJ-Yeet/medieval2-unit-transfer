"""Local web server for the Unit Transfer UI (Stage 4).

Serves a single-page app to browse a source mod's units faction-wise (with icons),
pick a destination mod, and transfer units with options + conflict resolution.
Transfers apply in-place into the destination mod (backing up first) and every
transfer is logged with an undo.

API
  GET  /                         -> SPA
  GET  /api/settings             -> {med2_root, last_source, last_dest}
  POST /api/settings             -> set {med2_root,...} (persisted)
  GET  /api/detect_med2_root     -> {path}  (registry lookup, not persisted)
  POST /api/browse_folder        -> {title} -> {path}  (native OS folder dialog)
  POST /api/reveal               -> {mod, rel} -> show that file in the OS file
                                    manager. Mod-relative only.
  GET  /api/mods                 -> [{name, root, pack}]  (scanned under
                                    med2_root/mods, plus any mounted unit pack)

Unit packs (see :mod:`unittransfer.pack`)
  POST /api/pack/plan            -> what a pack of these units would hold
  POST /api/pack/write           -> write it to {path}
  POST /api/pack/open            -> read someone else's pack: manifest + units
  POST /api/pack/mount           -> register it as a source mod for this session;
                                    importing is then an ordinary transfer out of
                                    it, with every check that implies
  POST /api/pack/unmount         -> drop it again and delete what was unpacked
  GET  /api/units?mod=NAME       -> {mod, factions, categories, classes, units}
  GET  /icon?mod=&type=&kind=    -> image/png
  POST /api/plan                 -> {source,dest,unit,options} -> plan preview
  POST /api/apply                -> {source,dest,unit,options} -> apply + record
  GET  /api/log[?mode=&limit=&offset=]  -> a PAGE of the log, newest first
  POST /api/undo                 -> {id} -> undo a transfer

Unit-editor mode (edits inside ONE mod, see :mod:`unittransfer.edit`)
  GET  /api/edit/unit?mod=&type= -> fields + localisation + modeldb entries
  POST /api/edit/model_folder    -> {mod,entry,target} -> where an entry's files
                                    live + what moving them would touch
  POST /api/edit/plan            -> preview an edit / delete
  POST /api/edit/apply           -> apply it (same backups + undo as a transfer)
  POST /api/browse_file          -> native file dialog (mesh/texture import)
  POST /api/browse_save          -> native Save-As dialog (unit pack export)

BMDB mode (the whole battle_models.modeldb, see :mod:`unittransfer.bmdb`)
  GET  /api/bmdb/entries?mod=    -> every entry, light (the browser list)
  GET  /api/bmdb/skeletons?mod=  -> every entry keyed by the animation skeleton(s)
                                    it uses, plus a tally per skeleton — what the
                                    soldier-model picker searches
  GET  /api/bmdb/entry?mod=&name= -> one entry, in the editor's model-card shape
  POST /api/bmdb/plan | /apply   -> edit entries that belong to no single unit
  GET  /api/bmdb/audit?mod=      -> unused entries, soldier-merge twins, orphan files
  POST /api/bmdb/cleanup_plan    -> what a cleanup would move/remove
  POST /api/bmdb/cleanup_apply   -> do it (backups + undo, assets exported first)
  GET  /api/progress?job=ID      -> where a long job (audit / cleanup) has got to

Sprites mode (far-LOD unit sprites, see :mod:`unittransfer.sprites`)
  GET  /api/sprites?mod=         -> models, CFG state, what's waiting in export/,
                                    and an audit of the modeldb's sprite lines
  POST /api/sprites/prep_plan    -> what prepping generation would touch
  POST /api/sprites/prep_apply   -> write sprite_script.txt / CFG flag (or the
                                    M2TWEOP console snippet, which writes nothing)
  POST /api/sprites/revert_cfg   -> comment the bypass flag back out
  POST /api/sprites/mark         -> mark models as sprited by hand (or unmark)
  POST /api/sprites/convert_plan -> what the TGA -> .texture run would do
  POST /api/sprites/convert_apply-> run it, dedup, install into the mod
  POST /api/sprites/wire         -> point the modeldb's sprite lines at the
                                    result (backups + undo, via bmdb mode)

Home (see :mod:`unittransfer.modfiles`)
  GET  /api/mod_files?mod=       -> which of the files each module reads this mod
                                    actually has, with size + encoding, plus the
                                    campaign's in-game name

Triggers (the shared builder's vocabulary, see :mod:`unittransfer.triggers`)
  GET  /api/triggers/vocab?mod=  -> every engine condition and event, with what
                                    each condition REQUIRES and each event
                                    EXPORTS, plus this mod's own trait /
                                    ancillary / faction / culture / building
                                    names for the operand pickers

Traits mode (export_descr_character_traits.txt, see :mod:`unittransfer.traits`)
  GET  /api/traits?mod=          -> every trait, light: levels, thresholds, how
                                    many triggers feed it, how many findings
  GET  /api/trait?mod=&name=     -> one trait in full: header, levels, effects,
                                    its text keys, and the triggers that give it
  POST /api/traits/plan|/apply   -> add, edit or delete a trait and the triggers
                                    that feed it, adding any missing
                                    export_VnVs.txt keys (backups + undo)

Ancillaries mode (export_descr_ancillaries.txt, see :mod:`unittransfer.ancillaries`)
  GET  /api/ancillaries?mod=     -> every ancillary, light: type, effects, how
                                    many triggers grant it, how many findings
  GET  /api/ancillary?mod=&name= -> one in full: its lines, effects, text keys,
                                    picture and the triggers that grant it
  POST /api/ancillaries/plan|/apply
                                 -> add, edit or delete an ancillary and the
                                    triggers that grant it, adding any missing
                                    export_ancillaries.txt keys (backups + undo)
  GET  /icon?mod=&kind=ancillary&image=
                                 -> that ancillary's picture as a PNG

Factions mode (descr_sm_factions.txt, see :mod:`unittransfer.factions`)
  GET  /api/factions?mod=        -> every faction, light: culture, religion, its
                                    two map colours, horde size, findings
  GET  /api/faction?mod=&name=   -> one in full: every line, the pickers its
                                    boxes need, and its expanded.txt name
  POST /api/factions/plan|/apply -> edit one faction and its shown name together
                                    (backups + undo). Editing only: a faction
                                    slot lives in eight or nine files at once

EDU cleanup (export_descr_unit.txt as a whole, see :mod:`unittransfer.edusort`)
  GET  /api/edu/order?mod=       -> every section and the units in it, in the
                                    order a cleanup would leave them
  POST /api/edu/sort/plan|/apply -> tidy, tier, group and reorder the whole unit
                                    file. `marks` sets a unit's tier, variant or
                                    classification; `style` is how the section
                                    banners are drawn
                                    file (one backup + undo). `plan` never
                                    returns the new text, only what would change

Minor Files mode (the five small campaign files, see :mod:`unittransfer.minorfiles`)
  GET  /api/minor?mod=&tab=      -> one tab's whole list (rebels / religions /
                                    resources / cultures / names), with the
                                    findings counted per record
  GET  /api/minor/record?mod=&tab=&name=
                                 -> one record in full: its fields, spans, the
                                    pickers its boxes need and its text key
  POST /api/minor/plan|/apply    -> add, edit or delete one record. A religion's
                                    save is four files at once — its block, the
                                    `religions` list, descr_religions_lookup.txt
                                    and text/religions.txt (backups + undo)

Strings mode (compiled data/text/*.strings.bin, see :mod:`unittransfer.strings`)
  GET  /api/strings?mod=         -> every archive: entry count, .txt state, size
  GET  /api/strings/entries?mod=&file=&q=&limit=&offset=
                                 -> that archive's rows, filtered and paged here
                                    rather than in the page (names.txt is 20 757)
  POST /api/strings/plan|/apply  -> edit entries, or `action: 'rebuild'` to
                                    recompile the archive from the .txt beside it
                                    (backups + undo, same as a transfer)

Sounds mode (the unit voice bank, see :mod:`unittransfer.sounds`)
  GET  /api/sounds?mod=          -> accents/classes, donors, and every unit split
                                    into "has a voice entry" / "doesn't"
  POST /api/sounds/plan | /apply -> stage voice edits, then write them (backups +
                                    undo, same as a transfer)

Buildings mode (export_descr_buildings.txt, see :mod:`unittransfer.buildings`)
  GET  /api/buildings?mod=&culture=
                                 -> every building line, light (the browser grid);
                                    `culture` picks which per-culture name shows
  GET  /api/buildings/variants?mod=&line=&culture=
                                 -> one building line beside its city/castle
                                    twin, tier by tier, with every unit marked
                                    as trained on both sides or on one
  GET  /api/building?mod=&line=&culture=
                                 -> one line in full: levels, stats, capabilities,
                                    recruit pools, which cultures have art and
                                    every culture's name / description
  GET  /api/buildings/checks?mod=&line=
                                 -> recruitment checks: units that stop being
                                    recruitable further up a chain, units one
                                    settlement type has and its city/castle twin
                                    does not, and units listed twice in a level.
                                    No `line` = every line with a finding
  GET  /api/buildings/unit?mod=&type=&culture=
                                 -> every recruit pool in the mod that trains one
                                    unit, so its numbers can be compared (and
                                    edited) across all the trees at once
  GET  /building_icon?mod=&culture=&level=&kind=
                                 -> the small / constructed icon, falling back to
                                    unpacked vanilla art, then to a placeholder
  POST /api/buildings/plan|/apply-> preview then write EDB + building-name edits
                                    (backups + undo, same as a transfer). `also`
                                    carries edits to further building lines, saved
                                    in the same pass — mirroring into the castle
                                    variant and cross-tree pool edits both use it
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import urllib.parse
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Optional

from . import bmdb, buildings, cleaner, codeview, config, edit, modfiles, sounds
from . import ancillaries, edusort, factions, minorfiles, sprites, strings, traits, triggers
from . import eop as _eop
from . import logutil
from .logutil import log, setup as setup_logging
from .icons import IconCache
from .mod import Mod
from .transfer import (TransferOptions, plan_transfer, apply_transfer, undo, revert_to,
                       base_field_groups_for, compose_with_base, mount_base_import,
                       officer_base_import)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

# Liveness: the page sends /api/heartbeat every few seconds and /api/bye when its
# tab closes, so the (often windowless) server shuts down instead of lingering and
# holding the port. A watchdog thread does the actual shutdown.
#: ``last_beat`` is the page's own heartbeat and is what proves a browser really
#: rendered the UI; ``last_seen`` is any other request from it. The watchdog
#: takes the later of the two, so a page that is busy fetching cannot be
#: mistaken for a page that has gone away.
_LIVENESS: Dict[str, Optional[float]] = {"last_beat": None, "pending_close": None,
                                         "last_seen": None}


def page_ever_loaded() -> bool:
    """True once a browser has actually rendered the UI and started heartbeating.

    The one trustworthy "did a browser really open?" signal. ``webbrowser.open()``
    returns True on Windows even when nothing opens (no default browser, a broken
    file association, a blocked handler), so the launcher can't rely on it — but a
    heartbeat can only come from a real page that really loaded.
    """
    return _LIVENESS["last_beat"] is not None
_BYE_GRACE = 8.0          # seconds after a tab-close beacon before we stop (survives a refresh)
#: Seconds of total silence before we stop. Generous on purpose: the cost of
#: waiting too long is a server holding a port nobody wanted; the cost of firing
#: too early is killing the tool under someone who is still using it.
_DEAD_MAN = 300.0

#: Paths that must NOT count as a sign of life. ``/api/ping`` is how a second
#: launch asks "are you already running", and answering it is not evidence that
#: anyone still has the page open.
_NOT_ALIVE = ("/api/ping", "/api/bye")


def note_request(path: str) -> None:
    """Any request from the page is proof the page is alive — not just heartbeats.

    The heartbeat used to be the only thing keeping the server up, and it is a
    ``setInterval`` in the tab: the browser throttles those in a background tab,
    and it shares the origin's ~6 connections with every unit-card request the
    grid is making. Both happened at once here — hundreds of slow icon reads out
    of a cloud-synced cache filled the connection pool, no heartbeat got through
    for two and a half minutes, and the watchdog shut down a server that was busy
    serving that very page. From the browser: black unit cards, "TypeError:
    Failed to fetch", a grey composer and a dead Settings button, all at once.

    Traffic *is* liveness, so every request now says so. The heartbeat stays as
    the proof of life for a page that is merely sitting there being read.
    """
    if path in _NOT_ALIVE:
        return
    _LIVENESS["last_seen"] = time.time()


def _restart_into(httpd, console: bool) -> None:
    """Hand this port to a fresh server, then get out of the way.

    Order matters and there is only one that works: the replacement cannot bind
    the port while we still hold it, and we cannot answer the request after we
    have stopped. So the reply goes out first, then this thread stops serving,
    closes the socket, spawns the replacement and ends the process. The page
    waits for the new server on the same address and reloads itself.
    """
    from . import startup
    app = Path(__file__).resolve().parent.parent / "app.py"
    port = httpd.server_address[1]
    # Spawn BEFORE stopping. Stopping first ends serve_forever, which unwinds
    # main() and takes the whole process with it — including this thread, before
    # it ever got to the spawn. The child is told to wait for the port instead.
    try:
        startup.spawn_server(app, ["--port", str(port), "--wait-port"],
                             console=console)
        log.info("RESTART replacement server starting%s — handing over port %d",
                 " with a console" if console else "", port)
    except Exception:
        log.error("restart: could not start the replacement — staying up",
                  exc_info=True)
        return
    try:
        httpd.shutdown()                     # stop serving (blocks until it has)
        httpd.server_close()                 # …and let go of the port
    except Exception:
        log.warning("restart: could not stop cleanly", exc_info=True)
    # This process must actually end: two servers on one port is the one outcome
    # worse than none.
    os._exit(0)


def should_stop(now: float, liveness: Optional[dict] = None) -> str:
    """'' to keep serving, otherwise why we are stopping. Pure, so it is testable.

    Two ways a server outlives its page: the tab was closed (it said so), or the
    tab went away without saying so (a crash, a killed browser). The second is a
    guess, and it used to be a bad one — see :func:`note_request`.
    """
    lv = _LIVENESS if liveness is None else liveness
    lb, pc, ls = lv["last_beat"], lv["pending_close"], lv.get("last_seen")
    alive = max(x for x in (lb, ls, 0.0) if x is not None)
    if pc is not None and now - pc > _BYE_GRACE and alive < pc:
        return "tab closed"
    if lb is not None and now - alive > _DEAD_MAN:
        return f"idle >{int(_DEAD_MAN)}s"
    return ""


def _liveness_watchdog(httpd) -> None:
    while True:
        time.sleep(2)
        why = should_stop(time.time())
        if why:
            log.info("browser %s — shutting down", why)
            threading.Thread(target=httpd.shutdown, daemon=True).start()
            return


# ---------------------------------------------------------------------------
# progress for the long jobs (the BMDB audit and the cleanup)
#
# Both are a single request that can run for many seconds, and a bar parked at a
# made-up width tells the user nothing. The page makes up a job id, passes it with
# the request and polls /api/progress?job=ID beside it; the job writes where it is
# under that id from its own thread (ThreadingHTTPServer serves the poll meanwhile).
_PROGRESS: Dict[str, dict] = {}
_PROGRESS_LOCK = threading.Lock()
_PROGRESS_TTL = 300.0        # seconds a finished job's last report is kept


def _progress_sink(job: str):
    """A ``(percent, label)`` callback the poller can read back, or ``None``."""
    job = (job or "").strip()
    if not job:
        return None

    def report(pct: int, label: str) -> None:
        now = time.time()
        with _PROGRESS_LOCK:
            for k, v in list(_PROGRESS.items()):
                if now - v["when"] > _PROGRESS_TTL:
                    _PROGRESS.pop(k, None)      # a page that never polled again
            _PROGRESS[job] = {"pct": pct, "label": label, "when": now}
    return report


def _progress_read(job: str) -> dict:
    with _PROGRESS_LOCK:
        rec = _PROGRESS.get((job or "").strip())
        return {"pct": rec["pct"], "label": rec["label"]} if rec else {}


def _strings_bin_wanted(body: dict) -> bool:
    """Whether to clear ``export_units.txt.strings.bin`` after this job.

    One setting, ``clear_strings_bin`` (on by default), decides it for every
    transfer / edit / voice change / cleanup — the game keeps showing the OLD
    unit text until that cache is gone, and it writes a fresh one on the next
    launch, so there is nothing to lose by clearing it every time.

    A job body may still say ``clear_strings_bin`` explicitly to override the
    setting for that one call (a batch transfer asks for it on its last unit
    only, and the tests switch it off).
    """
    if body.get("clear_strings_bin") is not None:
        return bool(body.get("clear_strings_bin"))
    return config.load_settings().get("clear_strings_bin", True)


def _clear_cache(mod_root, out: dict, rec: dict, mod_name: str,
                 rel: str = cleaner.STRINGS_BIN_REL) -> None:
    """Refresh the compiled cache for a finished job and record what it did.

    Recompiles it from the ``.txt`` the job just wrote where it can, and falls
    back to the old delete-and-let-the-game-rebuild where it cannot — see
    :func:`cleaner.refresh_strings_bin`.
    """
    res = cleaner.refresh_strings_bin(mod_root, rel)
    out["strings_bin"] = res
    if res.get("rebuilt"):
        log.info("CACHE  rebuilt %s in %s (%d entries)", rel, mod_name,
                 res.get("entries", 0))
    elif res.get("deleted"):
        log.info("CACHE  cleared %s in %s", rel, mod_name)
    elif res.get("missing"):
        log.info("CACHE  %s not present in %s — nothing to clear", rel, mod_name)
    else:
        log.warning("CACHE  not cleared: %s", res.get("error"))
    config.update_log(rec.get("id", ""), strings_bin=res)


def _safe_stem(name: str) -> str:
    """A mod name reduced to something safe to use as a folder name."""
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", (name or "pack").strip()).strip("._") or "pack"


#: How long a resolved mod is trusted before its files are stat'ed again. Short
#: enough that editing a mod's file in another program still shows up on the next
#: click; long enough that a page full of unit cards resolves the mod once
#: instead of once per card.
REVALIDATE_SECONDS = 1.0


class Registry:
    def __init__(self, cache_dir: Path):
        self.icons = IconCache(cache_dir)
        self._mods: Dict[str, Mod] = {}
        self._sigs: Dict[str, tuple] = {}      # name -> on-disk signature when cached
        # name -> extracted root, for unit packs mounted this session
        self._packs: Dict[str, Path] = {}
        # ThreadingHTTPServer serves the ~dozens of icon requests of one page
        # concurrently; Mod's cached_property parsers and this dict are not
        # thread-safe, so serialise mod resolution + first-parse behind a lock.
        self._lock = threading.RLock()
        # name -> when this mod was last checked against the disk. Every request
        # used to re-scan the mods folder and stat twelve files before it could
        # be answered, all of it inside the lock above: a screen of unit cards is
        # hundreds of requests, so they queued behind each other for no reason.
        # An on-disk edit still shows up without a restart, just up to a second
        # later — and our own writes call invalidate(), so they are immediate.
        self._checked: Dict[str, float] = {}

    @staticmethod
    def _signature(mod: Mod) -> tuple:
        """(size, mtime) of a mod's key data files, so an edit on disk is noticed.

        Lets a running server pick up a changed source bmdb / EDU / projectile file
        without a restart — every request rebuilds the Mod when the files move.
        """
        sig = []
        for p in (mod.edu_path, mod.export_units_path, mod.modeldb_path,
                  mod.descr_mount_path, mod.descr_projectile_path,
                  mod.descr_engines_path, mod.descr_mounted_engines_path,
                  mod.descr_engine_skeleton_path, mod.expanded_path,
                  mod.eds_path, mod.edb_path, mod.building_loc_path):
            try:
                st = p.stat()
                sig.append((p.name, st.st_size, int(st.st_mtime_ns)))
            except OSError:
                sig.append((p.name, -1, -1))
        return tuple(sig)

    # ---- mod discovery from the MED2 root ----
    def mods_root(self) -> Optional[Path]:
        root = config.get_med2_root()
        if not root:
            return None
        p = Path(root)
        # accept either the install root (has a 'mods' subfolder) or a mods folder itself
        if (p / "mods").is_dir():
            return p / "mods"
        return p

    def discover(self) -> Dict[str, Path]:
        mr = self.mods_root()
        out: Dict[str, Path] = {}
        if mr and mr.is_dir():
            for child in sorted(mr.iterdir()):
                if child.is_dir() and (child / "data").is_dir():
                    out[child.name] = child
        # A mounted unit pack is a mod like any other from here on — that is the
        # whole point of the format (see :mod:`unittransfer.pack`). Registering it
        # here means the composer, the base picker, the conflict handling, the
        # preview and the undo log all work on it with no import-specific code.
        for name, root in self._packs.items():
            if (root / "data").is_dir():
                out[name] = root
        return out

    # ---- unit packs mounted as read-only source mods ----
    def mount_pack(self, zip_path) -> dict:
        """Unpack a zip and register it as a source mod for this session."""
        from . import pack as pack_mod
        manifest = pack_mod.read_manifest(Path(zip_path))
        # named after the mod it CAME from, not the zip: the transfer engine puts
        # relocated assets in a folder named after the source, and
        # "unit_models/p-20260811-155044/" tells nobody anything
        # …and the source's name comes FIRST, because transfer._tag builds rename
        # suffixes from a mod's leading letters: "pack_Divide…" would tag every
        # renamed entry "_pack", which says nothing about where it came from.
        stem = _safe_stem(manifest.get("source_mod") or Path(zip_path).stem)
        with self._lock:
            name = f"{stem}_pack"
            n = 2
            while name in self._packs:
                name = f"{stem}_pack{n}"
                n += 1
            root = config.CONFIG_DIR / "packs" / name
            shutil.rmtree(root, ignore_errors=True)
            pack_mod.unpack(Path(zip_path), root)
            self._packs[name] = root
        log.info("PACK   mounted %s as %s", zip_path, name)
        return {"name": name, "root": str(root), "manifest": manifest}

    def unmount_pack(self, name: str) -> bool:
        with self._lock:
            root = self._packs.pop(name, None)
            self._mods.pop(name, None)
            self._sigs.pop(name, None)
        if root is None:
            return False
        shutil.rmtree(root, ignore_errors=True)
        log.info("PACK   unmounted %s", name)
        return True

    def is_pack(self, name: str) -> bool:
        return name in self._packs

    def names(self) -> List[str]:
        return list(self.discover())

    def get(self, name: str) -> Mod:
        with self._lock:
            fresh = self._checked.get(name)
            cached = self._mods.get(name)
            if (cached is not None and fresh is not None
                    and time.monotonic() - fresh < REVALIDATE_SECONDS):
                return cached
            paths = self.discover()
            if name not in paths:
                raise KeyError(name)
            # cache by resolved path; drop cache if the path changed OR any of the
            # mod's data files changed on disk (so edits to the source bmdb/EDU show
            # up without restarting the tool).
            key = str(paths[name])
            cached = self._mods.get(name)
            if cached is not None and str(cached.root) == key:
                if self._signature(cached) != self._sigs.get(name):
                    cached = None                # a data file changed -> reparse
            elif cached is not None:
                cached = None                    # mod path changed
            cold = cached is None
            if cold:
                # The log has to say what the tool was doing while the screen was
                # still empty, and this is it: the first request for a mod reads
                # its files, everything after that is served from memory.
                log.info("PARSE  %s: reading its files (%s)", name, paths[name])
                started = time.perf_counter()
                cached = Mod(paths[name])
                self._mods[name] = cached
                self._sigs[name] = self._signature(cached)
            # Warm the light parsed DBs *inside the lock* so concurrent icon /
            # units requests never trigger a cached_property parse race (which
            # would surface as sporadic 500s -> broken card images). The heavy
            # modeldb is left lazy; it's only needed by the serialised plan/apply.
            _ = cached.edu, cached.loc, cached.faction_names, cached.mounts
            if cold:
                # `faction_names` is the mod's whole name lookup, not its factions
                # (which /api/units counts) — say which, or the number reads as a
                # mod with 1941 factions in it.
                log.info("PARSE  %s: %d units, %d mounts, %d localised names in %.2fs",
                         name, len(cached.edu.units), len(cached.mounts),
                         len(cached.faction_names), time.perf_counter() - started)
            self._checked[name] = time.monotonic()
            return cached

    def invalidate(self, name: str):
        with self._lock:
            self._mods.pop(name, None)
            self._sigs.pop(name, None)
            self._checked.pop(name, None)


def _engine_groups(m: Mod, u) -> list:
    """Model-group names of the unit's siege engine, for the composer's summary.

    ['normal', 'dying', 'dead'] for a typical engine, [] when the unit has none or
    the engine isn't defined in this mod (a mounted engine has no model groups).
    """
    for name, defs in ((u.engine, m.engine_defs), (u.mounted_engine, m.mounted_engine_defs)):
        if not name:
            continue
        groups = [g.name for b in defs(name) for g in b.groups]
        return list(dict.fromkeys(groups))
    return []


def _mounted_engine_class(m: Mod, u) -> str:
    """The ``descr_engine_skeleton.txt`` entry a mounted engine's ``class`` names.

    A mounted engine has no model groups (the model is the mount's), so ``class``
    is the only thing pointing at an animation set — usually ``serpentine``,
    ``rocket_launcher`` or ``ballista``. '' when the unit has no mounted engine or
    this mod doesn't define it.
    """
    if not u.mounted_engine:
        return ""
    for b in m.mounted_engine_defs(u.mounted_engine):
        if b.engine_class:
            return b.engine_class
    return ""


def _unit_payload(m: Mod, u) -> dict:
    loc = m.loc.get(u.dictionary)
    disp = (loc.name.strip() if loc and loc.name else "") or u.type
    return {
        "type": u.type, "dictionary": u.dictionary, "name": disp,
        "category": u.category, "kind": u.kind(),
        "class": u.class_type, "ownership": u.ownership,
        "eras": {"0": u.era0, "1": u.era1, "2": u.era2},
        "attributes": u.attributes, "mercenary": u.mercenary_unit,
        "models": u.model_names(),
        # the soldier line's model and the armour-upgrade list separately: when the
        # upgrade list is nothing but the soldier model, "armour upgrades from the
        # source" names no model of its own and the composer ties the two rows
        # together (see transfer._follow_soldier_upgrades)
        "soldier_model": u.soldier_model, "armour_ug_models": u.armour_ug_models,
        "officers": u.officers, "mount": u.mount,
        # crew = ship / engine / mounted_engine / animal (drives the "Crew"
        # transfer option, greyed out when the unit has none). These name entries
        # in descr_ship / descr_engines / descr_mounted_engines / descr_animals,
        # NOT battle models — the siege engine is resolved separately below.
        "crew": [x for x in (u.ship, u.engine, u.mounted_engine, u.animal) if x],
        # siege engine: the descr_engines.txt / descr_mounted_engines.txt entry
        # this unit drives, and how many blocks + model groups it spans.
        "engine": u.engine, "mounted_engine": u.mounted_engine,
        "engine_groups": _engine_groups(m, u),
        # a mounted engine has no model groups: its `class` is the skeleton name
        "engine_class": _mounted_engine_class(m, u),
        # projectile(s) the unit fires (stat_pri/stat_sec slot 3); [] for melee.
        "projectiles": u.projectiles(),
        "has_card": m.find_unit_card(u) is not None,
        "has_info": m.find_unit_info(u) is not None,
        # M2TWEOP unit: defined in one of the extender's own files rather than in
        # data/export_descr_unit.txt. The UI badges these, and the 500-unit cap
        # does not apply to them.
        "eop": u.is_eop,
        "eop_file": _eop.rel_to_root(m, u.eop_file) if u.is_eop else "",
    }


#: How many log entries one page carries.
LOG_PAGE = 40
#: A summary longer than this is cut for the LIST. Nothing is lost — the whole
#: record is still in `config/transfers.json`, and the diagnostic log has the
#: detail — but one 310 KB entry (a mod-wide cleanup's file-by-file account) must
#: not decide how long the log takes to open.
LOG_SUMMARY_CAP = 4000
#: Dropped from a listed entry. `manifest` is the backup bookkeeping undo reads
#: server-side; the page has never used it, and it is most of the file's weight.
LOG_LIST_DROP = ("manifest",)


def log_page(mode: str = "", offset: int = 0, limit: int = LOG_PAGE) -> dict:
    """One page of the transfer log, newest first, plus what the filter needs.

    The log used to be sent whole, and the panel built HTML for every entry in
    it: 480 entries, 1.1 MB of JSON and 600 KB of markup for a screen that shows
    about six. It also has to be read off disk first, which on a machine where
    `config/` is inside OneDrive is where the "opening the log takes minutes"
    report comes from.

    `counts` is over the WHOLE log (a filter has to say what it would show), and
    `newer_count` is computed here because it needs the whole log too — it is
    what "Revert to here" reverts, and the page must not have to hold 480 entries
    to work out one number.
    """
    entries = config.load_log()
    counts: Dict[str, int] = {}
    for e in entries:
        counts[e.get("mode") or "transfer"] = counts.get(e.get("mode") or "transfer", 0) + 1

    # "how many applied, not-yet-undone writes to this same mod came after it"
    newer: Dict[str, int] = {}
    seen: Dict[str, int] = {}
    for e in reversed(entries):                       # newest first
        key = e.get("dest_root") or ""
        newer[e.get("id") or ""] = seen.get(key, 0)
        if e.get("applied") and not e.get("undone"):
            seen[key] = seen.get(key, 0) + 1

    picked = [e for e in reversed(entries)
              if not mode or (e.get("mode") or "transfer") == mode]
    total = len(picked)
    offset = max(0, offset)
    page = picked[offset:offset + max(1, limit)]

    out = []
    for e in page:
        item = {k: v for k, v in e.items() if k not in LOG_LIST_DROP}
        summary = item.get("summary") or ""
        if len(summary) > LOG_SUMMARY_CAP:
            item["summary"] = summary[:LOG_SUMMARY_CAP]
            item["summary_cut"] = len(summary) - LOG_SUMMARY_CAP
        item["newer_count"] = newer.get(e.get("id") or "", 0)
        out.append(item)
    return {"entries": out, "total": total, "offset": offset, "limit": limit,
            "counts": counts, "grand_total": len(entries), "mode": mode}


def build_units_response(m: Mod) -> dict:
    started = time.perf_counter()
    units = [_unit_payload(m, u) for u in m.edu.units]
    factions = sorted({f for u in m.edu.units for f in u.ownership})
    # Which units have no card is worth saying plainly: a blank card in the grid
    # is either "this mod ships no art for it" or "the conversion failed", and
    # those look identical on screen.
    cardless = [u.type for u in m.edu.units if not m.find_unit_card(u)]
    log.info("UNITS  %s: %d units, %d with a card, %d factions in %.2fs",
             m.name, len(units), len(units) - len(cardless), len(factions),
             time.perf_counter() - started)
    if cardless:
        log.debug("UNITS  %s: %d units ship no unit card: %s", m.name, len(cardless),
                  ", ".join(cardless)[:800])
    return {
        "mod": m.name,
        "factions": factions,
        # M2TWEOP state, so the picker can show the badge legend and the settings
        # panel can say whether the folders were configured or auto-detected
        "eop_dirs": [str(p) for p in m.eop_dirs],
        "eop_configured": [str(p) for p in _eop.configured_dirs(m)],
        "eop_count": len(m.edu.eop_units),
        "edu_count": len(m.edu.main_units),
        "faction_names": {f: m.faction_names.get(f.lower(), "") for f in factions},
        # "categories" is the refined kind (cavalry split into Cavalry /
        # Cavalry_Lance / Cavalry_Archer) — it drives the filter and the base picker.
        "categories": sorted({u.kind() for u in m.edu.units if u.kind()}),
        "classes": sorted({u.class_type for u in m.edu.units if u.class_type}),
        "units": units,
    }


def _edit_payload(plan) -> dict:
    """Preview shape of an edit plan (never the whole rewritten files —
    the modeldb alone is 20+ MB on a big mod)."""
    return {
        "mod": plan.mod.name,
        "unit_type": plan.unit_type,
        "resolved_type": plan.resolved_type,
        "resolved_dict": plan.resolved_dict,
        "action": "delete" if plan.request.delete else "edit",
        "changes": plan.changes,
        "warnings": plan.warnings,
        "errors": plan.errors,
        "files_written": ([f for f, on in (("export_descr_unit.txt", plan.edu_text),
                                           ("text/export_units.txt", plan.loc_text),
                                           ("unit_models/battle_models.modeldb",
                                            plan.modeldb_touched)) if on]),
        # every other file a `type` rename reaches, with how many lines in each
        "ref_counts": [{"file": f, "hits": n} for f, n in plan.ref_counts],
        "copies": [rel for _src, rel in plan.copies],
        "icon_copies": [rel for _src, rel in plan.icon_copies]
                       + [rel for _src, rel in plan.icon_converts],
        "deletes": list(plan.deletes),
        "new_entries": [n for n, _r, _p in plan.new_entries],
        "entry_updates": sorted(plan.entry_updates.keys()),
        "entry_renames": plan.entry_renames,
        "entry_deletes": list(plan.entry_deletes),
        "summary": plan.summary(),
    }


def _cleanup_payload(plan) -> dict:
    """Preview shape of a cleanup plan (file lists capped — a big mod exports
    thousands of files and the browser only needs enough to show the user)."""
    return {
        "mod": plan.mod.name,
        "target": str(plan.target or ""),
        "entry_deletes": list(plan.entry_deletes),
        "merges": [{"entry": a, "into": b} for a, b in plan.merges],
        "mount_deletes": list(plan.mount_deletes),
        "edu_rewritten": bool(plan.edu_text),
        "mounts_rewritten": bool(plan.mount_text),
        "export_count": len(plan.exports),
        "exports": [rel for _src, rel in plan.exports[:300]],
        "kept_files": plan.kept_files[:60],
        "kept_count": len(plan.kept_files),
        "orphan_count": plan.orphan_count,
        "orphan_bytes": plan.orphan_bytes,
        "changes": plan.changes,
        "warnings": plan.warnings,
        "errors": plan.errors,
        "summary": plan.summary(),
    }


def _sound_payload(plan) -> dict:
    """Preview shape of a voice-edit plan (never the whole rewritten voice bank —
    it is a megabyte of text the browser has no use for)."""
    return {
        "mod": plan.mod.name,
        "count": len(plan.ops),
        "eds_rewritten": bool(plan.eds_text),
        "edu_rewritten": bool(plan.edu_text),
        "changes": plan.changes,
        "warnings": plan.warnings,
        "errors": plan.errors,
        "summary": plan.summary(),
    }


def _building_payload(plan) -> dict:
    """Preview shape of a building-edit plan.

    Like the voice-edit preview, the rewritten file itself is deliberately left
    out — the EDB is 17k lines and the page only needs the change list."""
    return {
        "mod": plan.mod.name,
        "line": plan.line,
        "edb_rewritten": bool(plan.edb_text),
        "loc_rewritten": bool(plan.loc_text),
        "edu_rewritten": bool(plan.edu_text or plan.eop_texts),
        "modeldb_rewritten": bool(plan.modeldb_text),
        "changes": plan.changes,
        "warnings": plan.warnings,
        "errors": plan.errors,
        "summary": plan.summary(),
        # only a new tree carries these: it is the one building edit that has
        # something to say about art, and it says it rather than writing it
        "created": plan.created,
        "slots": plan.slots,
    }


def _sprite_prep_payload(plan) -> dict:
    return {
        "mod": plan.mod.name,
        "method": plan.request.method,
        "known": plan.known,
        "unknown": plan.unknown,
        "mounts": plan.mounts,
        "script_path": str(plan.script_path) if plan.script_path else "",
        "export_dir": str(plan.export_dir) if plan.export_dir else "",
        "cfg_edit": plan.cfg_edit,
        "lua": plan.lua,
        "warnings": plan.warnings,
        "summary": plan.summary(),
    }


def _sprite_convert_payload(plan) -> dict:
    return {
        "mod": plan.mod.name,
        "sets": [{"stem": s.stem, "model": s.model, "faction": s.faction,
                  "sheets": len(s.sheets)} for s in plan.sets],
        "install_dir": str(plan.install_dir) if plan.install_dir else "",
        "incomplete": plan.incomplete,
        "warnings": plan.warnings,
        "summary": plan.summary(),
    }


def _options_from(d: dict) -> TransferOptions:
    return TransferOptions(
        include_officers=bool(d.get("include_officers", True)),
        include_mount=bool(d.get("include_mount", True)),
        include_crew=bool(d.get("include_crew", True)),
        include_projectile=bool(d.get("include_projectile", True)),
        include_engine=bool(d.get("include_engine", True)),
        exclude_models=[str(m).lower() for m in (d.get("exclude_models") or [])],
        eop_target=d.get("eop_target", "auto"),
        on_conflict=d.get("on_conflict", "rename"),
        new_type=d.get("new_type") or None,
        new_dictionary=d.get("new_dictionary") or None,
        base_type=d.get("base_type") or None,
        mode=d.get("mode", "new"),
        replace_type=d.get("replace_type") or None,
        import_card=bool(d.get("import_card", False)),
        import_info_card=bool(d.get("import_info_card", False)),
        soldier_from=d.get("soldier_from", "source"),
        officer_from=d.get("officer_from", "source"),
        mount_from=d.get("mount_from", "source"),
        crew_from=d.get("crew_from", "source"),
        upgrade_from=d.get("upgrade_from", "source"),
        import_mount_with_base=bool(d.get("import_mount_with_base", True)),
        import_officers_with_base=bool(d.get("import_officers_with_base", True)),
        field_overrides=dict(d.get("field_overrides") or {}),
        asset_conflict=d.get("asset_conflict", "mod_folder"),
        asset_reroute_dir=d.get("asset_reroute_dir") or None,
        icon_conflict=d.get("icon_conflict", "use_existing"),
        engine_conflict=d.get("engine_conflict", "use_existing"),
        make_mercenary=bool(d.get("make_mercenary", False)),
        merc_icons=bool(d.get("merc_icons", False)),
        sound_mode=d.get("sound_mode", "base"),
        sound_donor=d.get("sound_donor") or None,
    )


def _plan_payload(plan) -> dict:
    return {
        "unit_type": plan.unit_type,
        "resolved_type": plan.resolved_type,
        "resolved_dict": plan.resolved_dict,
        "unit_conflict": plan.unit_conflict,
        "skipped": plan.skipped,
        "on_conflict": plan.options.on_conflict,
        "base_type": plan.options.base_type or "",
        # "replace an existing unit": the destination unit rewritten in place
        # ("" in the normal mode). The composer uses it to say what happened and
        # to keep the 500-unit banner honest — a replacement adds no unit.
        "mode": plan.options.mode,
        "replace_type": plan.replace_type,
        "import_card": plan.options.import_card,
        "import_info_card": plan.options.import_info_card,
        "soldier_from": plan.options.soldier_from,
        "base_field_groups": list(dict.fromkeys(plan.base_field_groups)),
        "base_error": plan.base_error,
        "option_error": plan.option_error,
        "model_actions": [asdict(a) for a in plan.model_actions],
        "add_count": len(plan.add_entries),
        "asset_count": len(plan.asset_files),
        "icon_count": len(plan.icon_files),
        "asset_conflicts": [asdict(c) for c in plan.asset_conflicts],
        "asset_conflict": plan.options.asset_conflict,
        "icon_conflict": plan.options.icon_conflict,
        "mercenary": plan.mercenary,
        "sound_mode": plan.options.sound_mode,
        "sound_action": plan.sound_action,
        "sound_donor": plan.sound_donor,
        "sound_accent": plan.sound_accent,
        "sound_class": plan.sound_class,
        "sound_detail": plan.sound_detail,
        "mount_action": plan.mount_action,
        "mount_name": plan.mount_name,
        "mount_from_base_import": plan.mount_from_base_import,
        "mount_anim_donor": plan.mount_anim_donor,
        "mount_skeletons_swapped": plan.mount_skeletons_swapped,
        "officer_from_base_import": plan.officer_from_base_import,
        "officer_anim_donor": plan.officer_anim_donor,
        "officer_skeletons_swapped": plan.officer_skeletons_swapped,
        "projectile_actions": [{"name": n, "action": a, "detail": d}
                               for n, a, d in plan.projectile_actions],
        "projectile_effects_blanked": plan.projectile_effects_blanked,
        "engine_conflict": plan.options.engine_conflict,
        "engine_actions": [{"name": n, "action": a, "detail": d}
                           for n, a, d in plan.engine_actions],
        "engine_skeleton_actions": [{"name": n, "action": a, "detail": d}
                                    for n, a, d in plan.engine_skeleton_actions],
        "engine_assets": plan.engine_assets,
        "engine_vanilla_refs": plan.engine_vanilla_refs,
        "engine_dest_overrides": plan.engine_dest_overrides,
        "reroute_dir": plan.reroute_dir,
        "relocated_count": len(plan.path_map),
        # Only EDU units count against the vanilla 500 cap — M2TWEOP units are
        # loaded from the extender's own files, which is the point of them.
        "dest_unit_count": len(plan.dest.edu.main_units),
        "dest_eop_count": len(plan.dest.edu.eop_units),
        "dest_new_units": plan.dest_new_units,
        # M2TWEOP: where this unit's block will be written ("" = the EDU)
        "eop_target": plan.options.eop_target,
        "eop_file": _eop.rel_to_root(plan.dest, plan.eop_file) if plan.eop_file else "",
        "dest_has_eop": bool(plan.dest.eop_dirs),
        "source_is_eop": bool(getattr(
            plan.source.edu.by_type().get(plan.unit_type), "is_eop", False)),
        "excluded_secondaries": plan.excluded_secondaries,
        "missing_models": plan.missing_models,
        "missing_skeletons": plan.missing_skeletons,
        # which copied model asks for each missing skeleton, and the subset the
        # Soldier row owns — the composer warns beside that row, not in general
        "skeleton_models": plan.skeleton_models,
        "soldier_model_name": plan.soldier_model_name,
        "soldier_skeletons_missing": plan.soldier_skeletons_missing(),
        # graded the same way: a missing skeleton is blamed on the slot whose fix
        # is real, and an armour-upgrade one is cosmetic rather than a crash
        "mount_skeletons_missing": plan.mount_skeletons_missing(),
        "officer_skeletons_missing": plan.officer_skeletons_missing(),
        "cosmetic_skeletons_missing": plan.cosmetic_skeletons_missing(),
        "base_soldier_model": plan.base_soldier_model,
        "soldier_anim_changed": list(plan.soldier_anim_changed),
        "missing_assets": plan.missing_assets[:20],
        "warnings": plan.warnings,
        "summary": plan.summary(),
    }


class Handler(BaseHTTPRequestHandler):
    registry: Registry = None
    # HTTP/1.0 (connection-per-request): ThreadingHTTPServer keep-alive plays
    # badly with the browser's pooled connections (sporadic "Failed to fetch").
    # The lock + atomic-cache + always-return-a-PNG fixes are what actually cure
    # the broken card icons, not connection reuse.

    def log_message(self, fmt, *args):
        # http.server's per-request line. Icons are dozens per page view, so keep
        # the request log at debug level; real actions are logged explicitly below.
        try:
            log.debug("HTTP %s", fmt % args)
        except Exception:
            pass

    # ---- io helpers ----
    def _send(self, code, body: bytes, ctype: str, headers: Optional[dict] = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json")

    def _err(self, code, msg):
        self._json({"error": msg}, code)

    #: One batch of UI events may not turn into a thousand log lines.
    ACTIVITY_MAX = 60
    #: How much of one event's text is kept. A field's new value can be a whole
    #: EDU line; the record of the save has the rest.
    ACTIVITY_CHARS = 300

    def _activity(self, body: dict) -> int:
        """Write what the person did into the same log as what the tool did.

        Half of "what happened" was missing: the log recorded every file the tool
        wrote and nothing at all about the clicks that led there, so reading it
        back meant inferring intent from effects. The page reports its own actions
        here — mode opened, mod picked, record opened, field changed from X to Y,
        dialog closed with edits still pending — batched, so a burst of typing is
        one request rather than one per keystroke.

        Never trusted, only recorded: each line is truncated, the whole batch is
        capped, and it is written as text at DEBUG (the file's level) rather than
        interpreted. The UI cannot make the server do anything through here.
        """
        events = body.get("events")
        if not isinstance(events, list):
            return 0
        written = 0
        for ev in events[:self.ACTIVITY_MAX]:
            if not isinstance(ev, dict):
                continue
            what = str(ev.get("what") or "")[:60].replace("\n", " ")
            detail = str(ev.get("detail") or "")[:self.ACTIVITY_CHARS].replace("\n", " ")
            if not what:
                continue
            log.debug("UI     %-16s %s", what, detail)
            written += 1
        if len(events) > self.ACTIVITY_MAX:
            log.debug("UI     (%d more events in that batch were dropped)",
                      len(events) - self.ACTIVITY_MAX)
        return written

    def _diag(self):
        """The diagnostic log as a download.

        Served rather than merely pointed at, because "send me your log file"
        fails at the first step for most people: ``config/`` is next to the app,
        the app was unzipped somewhere they don't remember, and the log may not
        even be there (see :func:`unittransfer.logutil.setup`). A button that
        hands them the file removes every one of those steps.
        """
        # Flush first — a diagnostic download that stops one line short of the
        # thing that went wrong is worse than useless.
        for h in log.handlers:
            try:
                h.flush()
            except Exception:
                pass
        text = logutil.tail()
        path = logutil.log_path()
        if not text:
            text = (f"(no log file — logutil found nowhere writable)\n"
                    f"Expected location: {path or config.CONFIG_DIR / 'server.log'}\n")
        name = f"unit-transfer-log-{time.strftime('%Y%m%d-%H%M%S')}.txt"
        log.info("DIAG   log downloaded from the UI (%d bytes from %s)", len(text), path)
        return self._send(200, text.encode("utf-8", errors="replace"),
                          "text/plain; charset=utf-8",
                          {"Content-Disposition": f'attachment; filename="{name}"'})

    def _read_body(self) -> dict:
        n = int(self.headers.get("Content-Length", 0))
        if not n:
            return {}
        return json.loads(self.rfile.read(n).decode("utf-8"))

    def _drain_body(self) -> None:
        """Consume and discard any request body (for beacons we don't parse)."""
        try:
            n = int(self.headers.get("Content-Length", 0))
            if n:
                self.rfile.read(n)
        except (ValueError, OSError):
            pass

    # ---- GET ----
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        note_request(u.path)
        try:
            if u.path in ("/", "/index.html"):
                return self._file(WEB_DIR / "index.html", "text/html; charset=utf-8")
            if u.path.startswith("/js/"):
                return self._web_asset(u.path)
            if u.path == "/api/ping":
                # identifies an already-running instance to a second launch
                import os as _os
                from . import __version__ as _ver
                return self._json({"app": "unit-transfer", "pid": _os.getpid(),
                                   "version": _ver})
            if u.path == "/api/settings":
                s = config.load_settings()
                # unsaved yet -> offer the registry-detected install as a prefill
                s["med2_root"] = s.get("med2_root") or config.detect_med2_root()
                return self._json(s)
            if u.path == "/api/detect_med2_root":
                # explicit re-lookup for the Settings "Auto-detect" button, on
                # demand rather than only as an initial prefill.
                return self._json({"path": config.detect_med2_root()})
            if u.path == "/api/mods":
                return self._json([{"name": n, "root": str(p),
                                    "pack": self.registry.is_pack(n)}
                                   for n, p in self.registry.discover().items()])
            if u.path == "/api/units":
                name = (q.get("mod") or [None])[0]
                if not name or name not in self.registry.names():
                    return self._err(404, "unknown mod")
                return self._json(build_units_response(self.registry.get(name)))
            if u.path == "/api/unit_fields":
                name = (q.get("mod") or [None])[0]
                utype = (q.get("type") or [None])[0]
                if not name or name not in self.registry.names() or not utype:
                    return self._err(404, "unknown mod/unit")
                m = self.registry.get(name)
                unit = m.edu.by_type().get(utype)
                if unit is None:
                    return self._err(404, "unit not found")
                from . import edu as _edu
                return self._json({"type": utype, "fields": _edu.block_fields(unit.raw)})
            if u.path == "/api/codeview":
                # the raw text of one record plus its field->line map, for the
                # side-by-side code view. `kind` names the file shape so the
                # same endpoint serves every editor that adopts the widget.
                name = (q.get("mod") or [None])[0]
                kind = (q.get("kind") or ["edu"])[0]
                ident = (q.get("id") or [None])[0]
                if not name or name not in self.registry.names() or not ident:
                    return self._err(404, "unknown mod/record")
                mod = self.registry.get(name)
                loaders = {"edu": codeview.unit_document,
                           "bmdb": codeview.entry_document,
                           "strings": codeview.strings_document,
                           "traits": codeview.trait_document,
                           "ancillaries": codeview.ancillary_document,
                           "factions": codeview.faction_document,
                           "sounds": codeview.sounds_document,
                           "pools": codeview.pools_document,
                           "edb": lambda m, i: codeview.building_document(
                               m, i, (q.get("culture") or [""])[0])}
                # the five minor files: the kind IS the tab, one name for one
                # file shape, so a tab cannot end up pointed at another's parser
                for t in minorfiles.TABS:
                    loaders[t.id] = (lambda tab_id: lambda m, i:
                                     codeview.minor_document(m, tab_id, i))(t.id)
                if kind not in loaders:
                    return self._err(400, f"no code view for '{kind}'")
                doc = loaders[kind](mod, ident)
                # `hide=1` asks for the comment-only lines to be left out of the
                # text the pane draws; `full` in the answer is still the record's
                # real bytes, and `hidden` is how they go back.
                out = codeview.view_payload(doc, (q.get("hide") or ["0"])[0] == "1")
                out["can_repair"] = codeview.can_repair(kind)
                out["can_tidy"] = codeview.can_tidy(kind)
                return self._json(out)
            if u.path == "/api/edu_vocab":
                # what the guided field editor puts in its drop-downs: the
                # engine's fixed sets plus everything THIS mod defines or uses
                name = (q.get("mod") or [None])[0]
                if not name or name not in self.registry.names():
                    return self._err(404, "unknown mod")
                return self._json(self.registry.get(name).edu_vocab)
            if u.path == "/api/base_fields":
                # Fields the unit would have AFTER inheriting from a destination
                # base unit — so the editor shows what will actually be written.
                return self._json(self._base_fields(q))
            if u.path == "/api/dirs":
                return self._json(self._dirs(q))
            if u.path == "/api/edit/unit":
                # everything the unit editor needs for one unit: EDU fields,
                # localisation, and each battle-model entry it points at
                name = (q.get("mod") or [None])[0]
                utype = (q.get("type") or [None])[0]
                if not name or name not in self.registry.names() or not utype:
                    return self._err(404, "unknown mod/unit")
                return self._json(edit.unit_detail(self.registry.get(name), utype))
            if u.path == "/api/progress":
                return self._json(_progress_read((q.get("job") or [""])[0]))
            if u.path in ("/api/bmdb/entries", "/api/bmdb/entry", "/api/bmdb/audit",
                          "/api/bmdb/skeletons"):
                name = (q.get("mod") or [None])[0]
                if not name or name not in self.registry.names():
                    return self._err(404, "unknown mod")
                # reported before the mod is resolved: parsing its EDU is already
                # a second or two, and the page is showing a bar by then
                job = (q.get("job") or [""])[0]
                sink = _progress_sink(job) if job else None
                if sink:
                    sink(1, f"reading {name}'s files")
                mod = self.registry.get(name)
                if u.path == "/api/bmdb/entries":
                    return self._json(bmdb.overview(mod, progress=sink))
                if u.path == "/api/bmdb/entry":
                    return self._json(bmdb.entry_detail(mod, (q.get("name") or [""])[0]))
                if u.path == "/api/bmdb/skeletons":
                    return self._json(bmdb.skeleton_index(mod))
                log.info("BMDB   audit of %s", name)
                return self._json(bmdb.audit(mod, progress=sink))
            if u.path == "/api/sounds":
                name = (q.get("mod") or [None])[0]
                if not name or name not in self.registry.names():
                    return self._err(404, "unknown mod")
                return self._json(sounds.overview(self.registry.get(name)))
            if u.path in ("/api/strings", "/api/strings/entries"):
                name = (q.get("mod") or [None])[0]
                if not name or name not in self.registry.names():
                    return self._err(404, "unknown mod")
                mod = self.registry.get(name)
                if u.path == "/api/strings":
                    return self._json(strings.overview(mod))
                # rows are filtered and paged here, not in the page: the biggest
                # archives run to five figures (see :func:`strings.entries`)
                return self._json(strings.entries(
                    mod, (q.get("file") or [""])[0], (q.get("q") or [""])[0],
                    int((q.get("limit") or [strings.PAGE])[0] or 0),
                    int((q.get("offset") or ["0"])[0] or 0)))
            if u.path in ("/api/ancillaries", "/api/ancillary"):
                name = (q.get("mod") or [None])[0]
                if not name or name not in self.registry.names():
                    return self._err(404, "unknown mod")
                mod = self.registry.get(name)
                if u.path == "/api/ancillaries":
                    return self._json(ancillaries.overview(mod))
                try:
                    return self._json(
                        ancillaries.detail(mod, (q.get("name") or [""])[0]))
                except KeyError as e:
                    return self._err(404, str(e))
            if u.path in ("/api/factions", "/api/faction"):
                name = (q.get("mod") or [None])[0]
                if not name or name not in self.registry.names():
                    return self._err(404, "unknown mod")
                mod = self.registry.get(name)
                if u.path == "/api/factions":
                    return self._json(factions.overview(mod))
                try:
                    return self._json(factions.detail(mod, (q.get("name") or [""])[0]))
                except KeyError as e:
                    return self._err(404, str(e))
            if u.path == "/api/edu/order":
                name = (q.get("mod") or [None])[0]
                if not name or name not in self.registry.names():
                    return self._err(404, "unknown mod")
                return self._json(edusort.overview(self.registry.get(name)))
            if u.path in ("/api/minor", "/api/minor/record"):
                name = (q.get("mod") or [None])[0]
                if not name or name not in self.registry.names():
                    return self._err(404, "unknown mod")
                mod = self.registry.get(name)
                which = (q.get("tab") or ["rebels"])[0]
                try:
                    if u.path == "/api/minor":
                        return self._json(minorfiles.overview(mod, which))
                    return self._json(minorfiles.detail(
                        mod, which, (q.get("name") or [""])[0]))
                except KeyError as e:
                    return self._err(404, str(e))
            if u.path in ("/api/traits", "/api/trait"):
                name = (q.get("mod") or [None])[0]
                if not name or name not in self.registry.names():
                    return self._err(404, "unknown mod")
                mod = self.registry.get(name)
                if u.path == "/api/traits":
                    return self._json(traits.overview(mod))
                try:
                    return self._json(traits.detail(mod, (q.get("name") or [""])[0]))
                except KeyError as e:
                    return self._err(404, str(e))
            if u.path == "/api/triggers/vocab":
                # the condition/event vocabulary the trigger builder draws its
                # pickers from. Generated data (tools/trigger_vocab.py), not code,
                # and the same for every mod — so `mod` only adds that mod's own
                # trait / ancillary / faction names as operand suggestions.
                name = (q.get("mod") or [""])[0]
                mod = (self.registry.get(name)
                       if name and name in self.registry.names() else None)
                return self._json(triggers.vocab_payload(mod))
            if u.path == "/api/mod_files":
                name = (q.get("mod") or [None])[0]
                if not name or name not in self.registry.names():
                    return self._err(404, "unknown mod")
                return self._json(modfiles.report(self.registry.get(name)))
            if u.path in ("/api/buildings", "/api/building",
                          "/api/buildings/checks", "/api/buildings/unit",
                          "/api/buildings/variants"):
                name = (q.get("mod") or [None])[0]
                if not name or name not in self.registry.names():
                    return self._err(404, "unknown mod")
                mod = self.registry.get(name)
                # which culture's building names to resolve — see buildings.loc_key
                culture = (q.get("culture") or [""])[0]
                if u.path == "/api/buildings":
                    return self._json(buildings.overview(mod, culture))
                if u.path == "/api/buildings/checks":
                    try:
                        return self._json(buildings.checks(mod, (q.get("line") or [""])[0]))
                    except KeyError as e:
                        return self._err(404, f"no building line {e}")
                if u.path == "/api/buildings/unit":
                    return self._json(buildings.unit_instances(
                        mod, (q.get("type") or [""])[0], culture))
                if u.path == "/api/buildings/variants":
                    # one line beside its city/castle twin, tier by tier
                    try:
                        return self._json(buildings.variant_compare(
                            mod, (q.get("line") or [""])[0], culture))
                    except KeyError as e:
                        return self._err(404, f"no building line {e}")
                return self._json(buildings.detail(mod, (q.get("line") or [""])[0],
                                                   culture))
            if u.path == "/building_icon":
                return self._building_icon(q)
            if u.path == "/preview_image":
                # Preview of a file the user just picked in the native browse
                # dialog — it lives outside the mod, so /icon (mod + unit) can't
                # reach it. Decoded to PNG rather than served raw, and only for
                # image extensions, so this can't be used to read arbitrary files.
                return self._preview_image((q.get("path") or [""])[0])
            if u.path == "/api/sprites":
                name = (q.get("mod") or [None])[0]
                if not name or name not in self.registry.names():
                    return self._err(404, "unknown mod")
                return self._json(sprites.overview(self.registry.get(name)))
            if u.path == "/api/log":
                return self._json(log_page(
                    mode=(q.get("mode") or [""])[0],
                    offset=int((q.get("offset") or ["0"])[0] or 0),
                    limit=int((q.get("limit") or [str(LOG_PAGE)])[0] or LOG_PAGE)))
            if u.path == "/api/diag":
                return self._diag()
            if u.path == "/icon":
                return self._icon(q)
            return self._err(404, "not found")
        except KeyError as e:
            # an unknown mod / unit / model entry is a 404, not a server fault
            log.warning("GET %s: not found: %s", u.path, e)
            return self._err(404, str(e))
        except Exception as e:
            log.exception("GET %s failed: %s", u.path, e)
            return self._err(500, f"{type(e).__name__}: {e}")

    # `_send` already withholds the body for HEAD, so the same routing serves both
    # — without this, BaseHTTPRequestHandler answers every HEAD with a 501.
    do_HEAD = do_GET

    # ---- POST ----
    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        note_request(u.path)
        # liveness signals: no body needed, kept out of the body-parsing path so a
        # sendBeacon (empty/other content-type) can't 500.
        if u.path == "/api/heartbeat":
            _LIVENESS["last_beat"] = time.time()
            _LIVENESS["pending_close"] = None
            self._drain_body()
            return self._json({"ok": True})
        if u.path == "/api/bye":
            _LIVENESS["pending_close"] = time.time()
            self._drain_body()
            return self._json({"ok": True})
        try:
            body = self._read_body()
            if u.path == "/api/activity":
                return self._json({"ok": self._activity(body)})
            if u.path == "/api/settings":
                s = config.save_settings(**body)
                return self._json(s)
            if u.path == "/api/browse_folder":
                # a browser page can't hand back a real filesystem path from its
                # own file input, so pop the OS's native folder dialog instead —
                # the server IS this machine, unlike a normal web app.
                from .folder_dialog import browse_for_folder
                path = browse_for_folder(body.get("title") or "Select a folder")
                return self._json({"path": path})
            if u.path == "/api/reveal":
                # "Open file location". The page sends the mod and a path
                # RELATIVE to that mod's data folder, never an absolute one, so
                # a reveal cannot be aimed at anything the mod does not own.
                name = body.get("mod") or ""
                if name not in self.registry.names():
                    return self._err(404, "unknown mod")
                mod = self.registry.get(name)
                root = mod.data.resolve()
                try:
                    target = (mod.data / str(body.get("rel") or "")).resolve()
                    target.relative_to(root)
                except (ValueError, OSError):
                    return self._json({"ok": False,
                                       "error": "that path is not inside the mod"})
                if not target.exists():
                    return self._json({"ok": False,
                                       "error": "that file is not there any more"})
                from .folder_dialog import reveal
                return self._json({"ok": reveal(str(target)),
                                   "path": str(target)})
            if u.path == "/api/eop_dirs":
                return self._json(self._eop_dirs(body))
            if u.path == "/api/browse_file":
                # same reason as browse_folder: the editor needs a real path to
                # the .mesh/.texture being imported, which a file input can't give.
                from .folder_dialog import browse_for_file
                path = browse_for_file(body.get("title") or "Select a file",
                                       body.get("filter") or "",
                                       body.get("dir") or "")
                return self._json({"path": path})
            if u.path == "/api/browse_save":
                # …and the other direction, for writing a unit pack out
                from .folder_dialog import browse_for_save
                path = browse_for_save(body.get("title") or "Save as",
                                       body.get("filter") or "",
                                       body.get("dir") or "",
                                       body.get("name") or "",
                                       body.get("ext") or "")
                return self._json({"path": path})
            if u.path == "/api/edit/model_folder":
                # "do all this entry's files live in one folder, and who else
                # would a move affect" — answered before the user commits to it.
                mod = self.registry.get(body.get("mod") or "")
                return self._json(edit.model_folder_report(
                    mod, body.get("entry") or "", body.get("target") or ""))
            if u.path in ("/api/codeview/parse", "/api/codeview/render",
                          "/api/codeview/repair", "/api/codeview/tidy"):
                return self._json(self._codeview(u.path.rsplit("/", 1)[-1], body))
            if u.path == "/api/edit/plan":
                return self._json(self._edit_plan(body))
            if u.path == "/api/edit/apply":
                return self._json(self._edit_apply(body))
            if u.path == "/api/bmdb/plan":
                mod = self.registry.get(body["mod"])
                return self._json(_edit_payload(
                    edit.plan_bmdb(mod, edit.bmdb_request_from_dict(body))))
            if u.path == "/api/bmdb/apply":
                return self._json(self._bmdb_apply(body))
            if u.path == "/api/bmdb/cleanup_plan":
                mod = self.registry.get(body["mod"])
                return self._json(_cleanup_payload(bmdb.plan_cleanup(
                    mod, bmdb.cleanup_request_from_dict(body))))
            if u.path == "/api/bmdb/cleanup_apply":
                return self._json(self._bmdb_cleanup(body))
            if u.path in ("/api/strings/plan", "/api/strings/apply"):
                return self._json(self._strings(u.path.rsplit("/", 1)[-1], body))
            if u.path in ("/api/traits/plan", "/api/traits/apply"):
                return self._json(self._traits(u.path.rsplit("/", 1)[-1], body))
            if u.path in ("/api/ancillaries/plan", "/api/ancillaries/apply"):
                return self._json(self._ancillaries(u.path.rsplit("/", 1)[-1], body))
            if u.path in ("/api/factions/plan", "/api/factions/apply"):
                return self._json(self._factions(u.path.rsplit("/", 1)[-1], body))
            if u.path in ("/api/minor/plan", "/api/minor/apply"):
                return self._json(self._minor(u.path.rsplit("/", 1)[-1], body))
            if u.path in ("/api/edu/sort/plan", "/api/edu/sort/apply"):
                return self._json(self._edu_sort(u.path.rsplit("/", 1)[-1], body))
            if u.path == "/api/sounds/plan":
                mod = self.registry.get(body["mod"])
                return self._json(_sound_payload(
                    sounds.plan_sounds(mod, sounds.ops_from_dicts(body.get("ops")))))
            if u.path == "/api/sounds/apply":
                return self._json(self._sounds_apply(body))
            if u.path.startswith("/api/pack/"):
                return self._json(self._pack(u.path.rsplit("/", 1)[-1], body))
            if u.path == "/api/buildings/plan":
                mod = self.registry.get(body["mod"])
                return self._json(_building_payload(buildings.plan_edit(mod, body)))
            if u.path == "/api/buildings/apply":
                return self._json(self._buildings_apply(body))
            if u.path == "/api/buildings/ownership":
                # asked on demand rather than baked into /api/building: it needs
                # the heavy modeldb parse, and only the clause editor wants it
                mod = self.registry.get(body["mod"])
                return self._json({"rows": buildings.ownership_report(
                    mod, body.get("checks"))})
            if u.path.startswith("/api/sprites/"):
                return self._json(self._sprites(u.path.rsplit("/", 1)[-1], body))
            if u.path == "/api/plan":
                return self._json(self._plan(body))
            if u.path == "/api/apply":
                return self._json(self._apply(body))
            if u.path == "/api/undo":
                log.info("UNDO   id=%s", body.get("id"))
                rec = undo(body["id"])
                if rec.get("dest"):
                    self.registry.invalidate(rec["dest"])   # dest files changed on disk
                log.info("UNDO   restored %r in %s", rec.get("resolved_type"), rec.get("dest"))
                return self._json(rec)
            if u.path == "/api/restart":
                # "Keep the console window open" is read once, at launch, so a
                # session that is already running cannot grow a console — which
                # is why ticking the box looked like it did nothing. This puts the
                # setting into effect now: reply first, then let go of the port
                # and start a replacement, with or without a console as asked.
                want_console = bool(body.get("console"))
                log.info("RESTART requested from the UI (console=%s)", want_console)
                self._json({"ok": True, "console": want_console})
                threading.Thread(target=_restart_into, args=(self.server, want_console),
                                 daemon=True).start()
                return None
            if u.path == "/api/quit":
                log.info("QUIT requested from the UI — shutting down")
                # Silent mode has no console to Ctrl+C, so the UI can stop us.
                # shutdown() blocks until serve_forever returns, so it must not
                # run on this handler's thread.
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return self._json({"ok": True, "message": "server stopping"})
            if u.path == "/api/revert":
                log.info("REVERT to id=%s", body.get("id"))
                res = revert_to(body["id"])
                if res.get("dest"):
                    self.registry.invalidate(res["dest"])
                log.info("REVERT %s: undid %d newer transfer(s)",
                         res.get("dest"), res.get("count", 0))
                return self._json(res)
            return self._err(404, "not found")
        except KeyError as e:
            log.warning("POST %s: not found: %s", u.path, e)
            return self._err(404, str(e))
        except Exception as e:
            log.exception("POST %s failed: %s", u.path, e)
            return self._err(500, f"{type(e).__name__}: {e}")

    def _plan(self, body):
        src = self.registry.get(body["source"])
        dest = self.registry.get(body["dest"])
        plan = plan_transfer(src, body["unit"], dest, _options_from(body.get("options", {})))
        return _plan_payload(plan)

    def _apply(self, body):
        src = self.registry.get(body["source"])
        dest = self.registry.get(body["dest"])
        plan = plan_transfer(src, body["unit"], dest, _options_from(body.get("options", {})))
        log.info("APPLY  %r  %s -> %s%s", body["unit"], body["source"], body["dest"],
                 f" (base={plan.options.base_type})" if plan.options.base_type else "")
        rec = apply_transfer(plan)
        self.registry.invalidate(body["dest"])   # dest files changed on disk
        for line in plan.summary().splitlines()[1:]:
            if line.strip():
                log.info("   %s", line.strip())
        log.info("APPLY  done id=%s  (%s)", rec.get("id"),
                 "skipped" if plan.skipped else f"type={plan.resolved_type!r}")
        out = {"record": rec, "plan": _plan_payload(plan)}
        # Clear the localisation cache so the new unit's text actually shows up.
        # A batch asks for it on its final unit and no earlier.
        if _strings_bin_wanted(body) and not plan.skipped:
            _clear_cache(dest.root, out, rec, dest.name)
        return out

    # ---- code view ----
    def _codeview(self, what, body):
        """Re-read hand-edited text, re-serialise GUI edits, or repair text.

        Every answer carries the same shape as ``GET /api/codeview`` so the
        widget has one code path, and a text the parser rejects comes back as
        ``{ok: false, error, line}`` rather than an HTTP error: the page shows it
        beside the offending line and keeps the state it already had.

        The per-kind context (which mod, which entry's padding, the text last
        known good) is assembled by :func:`codeview.context` — the endpoints
        deliberately don't know what each kind needs, so a new kind adds nothing
        here. ``base`` from the request wins over the on-disk text, because after
        a hand edit the pane's own last-good text is what a repair must diff
        against.
        """
        kind = body.get("kind") or "edu"
        mod_name = body.get("mod") or ""
        # The pane may be hiding this record's comment-only lines, in which case
        # `text` is the view and `hidden` holds the rest. Everything below works
        # on the REAL text: the comments go back before a parser or a serialiser
        # ever sees it, and the answer hides them again.
        hide = bool(body.get("hide"))
        text = codeview.show_comments(kind, body.get("text") or "",
                                      body.get("hidden") or [])
        try:
            ctx = (codeview.context(kind, self.registry.get(mod_name),
                                    body.get("id") or "", body.get("culture") or "")
                   if mod_name in self.registry.names() else {})
            if body.get("base"):
                ctx = dict(ctx, base=body["base"])
            if what == "parse":
                doc = codeview.parse(kind, text, ctx)
            elif what == "repair":
                doc = codeview.repair(kind, text, ctx)
            elif what == "tidy":
                doc = codeview.tidy(kind, text, ctx)
            else:
                doc = codeview.render(kind, body.get("base") or "",
                                      body.get("edits") or {}, ctx)
        except codeview.CodeViewError as e:
            # the line the parser objected to counts the comments the pane is
            # not showing, so it is moved onto the view's numbering — pointing
            # at the wrong line is worse than pointing at none
            line = e.line
            if hide and line and what != "render":
                line = codeview.line_map(kind, text).get(line, 0) or line
            return {"ok": False, "error": e.message, "line": line}
        out = codeview.view_payload(doc, hide)
        out["ok"] = True
        return out

    # ---- edit mode ----
    def _edit_plan(self, body):
        mod = self.registry.get(body["mod"])
        plan = edit.plan_edit(mod, edit.request_from_dict(body))
        return _edit_payload(plan)

    def _edit_apply(self, body):
        mod = self.registry.get(body["mod"])
        plan = edit.plan_edit(mod, edit.request_from_dict(body))
        log.info("EDIT   %r in %s (%s)", plan.unit_type, mod.name,
                 "delete" if plan.request.delete else "edit")
        rec = edit.apply_edit(plan)
        self.registry.invalidate(body["mod"])       # files changed on disk
        for line in plan.summary().splitlines()[1:]:
            if line.strip():
                log.info("   %s", line.strip())
        log.info("EDIT   done id=%s", rec.get("id"))
        out = {"record": rec, "plan": _edit_payload(plan)}
        if _strings_bin_wanted(body):
            _clear_cache(mod.root, out, rec, mod.name)
        return out

    # ---- sounds mode ----
    def _sounds_apply(self, body):
        mod = self.registry.get(body["mod"])
        plan = sounds.plan_sounds(mod, sounds.ops_from_dicts(body.get("ops")))
        if plan.errors:
            return {"error": "; ".join(plan.errors), "plan": _sound_payload(plan)}
        log.info("VOICE  %d edit(s) in %s", len(plan.ops), mod.name)
        rec = sounds.apply_sounds(plan)
        self.registry.invalidate(body["mod"])       # files changed on disk
        for line in plan.summary().splitlines()[1:]:
            if line.strip():
                log.info("   %s", line.strip())
        log.info("VOICE  done id=%s", rec.get("id"))
        out = {"record": rec, "plan": _sound_payload(plan)}
        # a voice change can move the `accent` / `voice_type` lines in the EDU,
        # so clear the unit-text cache here too
        if _strings_bin_wanted(body):
            _clear_cache(mod.root, out, rec, mod.name)
        return out

    # ---- buildings mode ----
    def _buildings_apply(self, body):
        mod = self.registry.get(body["mod"])
        plan = buildings.plan_edit(mod, body)
        if plan.errors:
            return {"error": "; ".join(plan.errors), "plan": _building_payload(plan)}
        if not (plan.edb_text or plan.loc_text or plan.edu_text or plan.eop_texts
                or plan.modeldb_text):
            return {"error": "nothing to change", "plan": _building_payload(plan)}
        log.info("BUILD  %r in %s (%d change(s))", plan.line, mod.name, len(plan.changes))
        rec = buildings.apply_edit(plan)
        self.registry.invalidate(body["mod"])       # files changed on disk
        for line in plan.summary().splitlines()[1:]:
            if line.strip():
                log.info("   %s", line.strip())
        log.info("BUILD  done id=%s", rec.get("id"))
        out = {"record": rec, "plan": _building_payload(plan)}
        # a renamed building writes text/export_buildings.txt, whose compiled
        # .strings.bin would otherwise keep showing the old name in game
        if plan.loc_text and _strings_bin_wanted(body):
            _clear_cache(mod.root, out, rec, mod.name,
                         cleaner.BUILDINGS_STRINGS_BIN_REL)
        return out

    # ---- strings archives ----
    def _strings(self, action, body):
        """Preview or write one ``*.strings.bin``.

        Same plan-then-apply shape as every other editor, so the page can show
        exactly what a save would do before it does it. A file or row this mod
        does not have comes back as ``{error}`` rather than an HTTP failure —
        the browser is showing a list that may be a moment out of date.
        """
        try:
            mod = self.registry.get(body["mod"])
            plan = strings.plan(mod, body)
        except strings.StringsError as e:
            return {"error": str(e)}
        out = {"plan": plan.payload()}
        if action == "plan" or plan.errors:
            if plan.errors:
                out["error"] = "; ".join(plan.errors)
            return out
        if not plan.data:
            out["error"] = "nothing to change"
            return out
        out["record"] = strings.apply(plan)
        self.registry.invalidate(body["mod"])       # the file changed on disk
        return out

    # ---- traits ----
    def _traits(self, action, body):
        """Preview or write one trait, its triggers and its text keys together.

        Same plan-then-apply shape as every other editor. A save here can touch
        the EDCT twice over (the trait block and the triggers hundreds of lines
        below it) and ``export_VnVs.txt`` as well — one job, one backup set, one
        undo, because half of it landing is a mod that crashes.
        """
        try:
            mod = self.registry.get(body["mod"])
            plan = traits.plan(mod, body)
        except (KeyError, OSError) as e:
            return {"error": str(e)}
        out = {"plan": plan.payload()}
        if action == "plan" or plan.errors:
            if plan.errors:
                out["error"] = "; ".join(plan.errors)
            return out
        if not plan.text and not plan.loc_adds:
            out["error"] = "nothing to change"
            return out
        out.update(traits.apply(plan))
        self.registry.invalidate(body["mod"])       # the file changed on disk
        return out

    # ---- ancillaries ----
    def _ancillaries(self, action, body):
        """Preview or write one ancillary, its triggers and its text keys together.

        The traits handler with one word changed — the two editors share their
        request shape because they share their file format.
        """
        try:
            mod = self.registry.get(body["mod"])
            plan = ancillaries.plan(mod, body)
        except (KeyError, OSError) as e:
            return {"error": str(e)}
        out = {"plan": plan.payload()}
        if action == "plan" or plan.errors:
            if plan.errors:
                out["error"] = "; ".join(plan.errors)
            return out
        if not plan.text and not plan.loc_writes:
            out["error"] = "nothing to change"
            return out
        out.update(ancillaries.apply(plan))
        self.registry.invalidate(body["mod"])       # the file changed on disk
        return out

    # ---- factions ----
    def _factions(self, action, body):
        """Preview or write one faction and its shown name together.

        Editing only, and the refusal is the format's: a faction slot lives in
        eight or nine files at once, so one that exists only in this file is a
        mod that will not load — see :data:`factions.REFUSED`.
        """
        try:
            mod = self.registry.get(body["mod"])
            plan = factions.plan(mod, body)
        except (KeyError, OSError) as e:
            return {"error": str(e)}
        out = {"plan": plan.payload()}
        if action == "plan" or plan.errors:
            if plan.errors:
                out["error"] = "; ".join(plan.errors)
            return out
        if not plan.touched():
            out["error"] = "nothing to change"
            return out
        out.update(factions.apply(plan))
        self.registry.invalidate(body["mod"])       # the file changed on disk
        return out

    # ---- the EDU cleanup ----
    def _edu_sort(self, action, body):
        """Preview or write a whole-file cleanup of ``export_descr_unit.txt``.

        One file, so one backup and one undo entry — but the widest single write
        in the toolkit, which is why :func:`edusort.plan` refuses to hand over a
        text that is not purely a reordering of the one it read.
        """
        try:
            mod = self.registry.get(body["mod"])
            plan = edusort.plan(
                mod,
                banners=body.get("banners", True), tidy=body.get("tidy", True),
                group=body.get("group", True), tiers=body.get("tiers", True),
                hand=body.get("hand"),
                # the ordering screen's per-unit tier / variant / classification
                marks=body.get("marks"),
                # and how the section banners it writes are drawn
                style=body.get("style"))
        except (KeyError, OSError) as e:
            return {"error": str(e)}
        out = {"plan": plan.payload()}
        if action == "plan" or plan.errors:
            if plan.errors:
                out["error"] = "; ".join(plan.errors)
            return out
        if not plan.touched():
            out["error"] = "nothing to change"
            return out
        out.update(edusort.apply(plan))
        self.registry.invalidate(body["mod"])       # the file changed on disk
        return out

    # ---- minor files ----
    def _minor(self, action, body):
        """Preview or write one record of one of the five small campaign files.

        The ancillaries handler with a tab on it. What is different is on the
        other side: a religion's save writes four files, so ``plan`` is what says
        which — and all four ride one backup set, because a religion that reaches
        three of them is a religion that half exists.
        """
        try:
            mod = self.registry.get(body["mod"])
            plan = minorfiles.plan(mod, body)
        except (KeyError, OSError) as e:
            return {"error": str(e)}
        out = {"plan": plan.payload()}
        if action == "plan" or plan.errors:
            if plan.errors:
                out["error"] = "; ".join(plan.errors)
            return out
        if not plan.touched():
            out["error"] = "nothing to change"
            return out
        out.update(minorfiles.apply(plan))
        self.registry.invalidate(body["mod"])       # the file changed on disk
        return out

    # ---- unit packs ----
    def _pack(self, action, body):
        """Export units to a zip, or mount someone else's zip as a source mod.

        There is no "import" action: mounting is the import. Once a pack is a
        registered mod, the ordinary transfer endpoints move units out of it with
        every check, option and undo step they always had.
        """
        from . import pack as pack_mod
        try:
            if action in ("plan", "write"):
                mod = self.registry.get(body["mod"])
                units = [str(t) for t in (body.get("units") or []) if str(t).strip()]
                plan = pack_mod.plan_pack(mod, units)
                out = {"units": [u.type for u in plan.units],
                       "missing": plan.missing, "models": plan.models,
                       "assets": len(plan.assets), "icons": len(plan.icons),
                       "mounts": plan.mounts, "projectiles": plan.projectiles,
                       "engines": plan.engines, "bytes": plan.bytes,
                       "warnings": plan.warnings, "summary": plan.summary()}
                if action == "plan":
                    return out
                dest = (body.get("path") or "").strip()
                if not dest:
                    return {"error": "no destination file chosen"}
                out["record"] = pack_mod.write_pack(plan, Path(dest))
                return out
            if action == "open":                 # what the import dialog previews
                return pack_mod.pack_overview(Path(body.get("path") or ""))
            if action == "mount":                # …and what makes it importable
                return self.registry.mount_pack(Path(body.get("path") or ""))
            if action == "unmount":
                return {"unmounted": self.registry.unmount_pack(body.get("name") or "")}
        except pack_mod.PackError as e:
            return {"error": str(e)}
        except (OSError, ValueError) as e:
            return {"error": f"{type(e).__name__}: {e}"}
        return {"error": f"unknown pack action {action!r}"}

    # ---- sprites mode ----
    def _sprites(self, action, body):
        """Dispatch one sprite action. Split out because the five endpoints share
        a mod lookup and the same "SpriteError means the user can fix it" rule."""
        try:
            if action == "revert_cfg":              # no mod needed, just the CFG
                return sprites.revert_prep(body.get("cfg") or "")

            mod = self.registry.get(body["mod"])

            if action in ("prep_plan", "prep_apply"):
                req = sprites.PrepRequest(
                    models=[str(m) for m in (body.get("models") or [])],
                    method=(body.get("method") or "eop").lower(),
                    cfg_path=body.get("cfg_path") or "")
                plan = sprites.plan_prep(mod, req)
                out = _sprite_prep_payload(plan)
                if action == "prep_apply":
                    out["record"] = sprites.apply_prep(plan)
                return out

            if action in ("convert_plan", "convert_apply"):
                req = sprites.ConvertRequest(
                    stems=[str(s) for s in (body.get("stems") or [])],
                    mipmaps=bool(body.get("mipmaps", False)),
                    dedup=bool(body.get("dedup", True)),
                    install=bool(body.get("install", True)),
                    cleanup=bool(body.get("cleanup", True)))
                plan = sprites.plan_convert(mod, req)
                out = _sprite_convert_payload(plan)
                if action == "convert_apply":
                    sink = _progress_sink(body.get("job") or "")
                    log.info("SPRITE convert %d set(s) in %s", len(plan.sets), mod.name)
                    out["record"] = sprites.apply_convert(plan, progress=sink)
                    self.registry.invalidate(body["mod"])   # data/ changed on disk
                return out

            if action == "mark":
                # a toggle, not a replace: the page sends the models whose mark
                # changed, so two tabs can't wipe each other's marks
                cur = set(sprites.marked_done(mod))
                names = {str(n).strip().lower()
                         for n in (body.get("models") or []) if str(n).strip()}
                cur |= names if body.get("done") else set()
                cur -= set() if body.get("done") else names
                return {"marked": sprites.set_marked_done(mod, cur)}

            if action == "wire":
                # reuse bmdb mode's planner so the modeldb write inherits its
                # backups + undo rather than us hand-rolling a second writer
                edits = sprites.wire_model_edits(
                    mod, {str(k): [str(f) for f in v]
                          for k, v in (body.get("models") or {}).items()},
                    body.get("duplicates") or {})
                if not edits:
                    return {"error": "nothing to wire up"}
                return self._bmdb_apply({"mod": body["mod"], "model_edits": edits})
        except sprites.SpriteError as e:
            return {"error": str(e)}
        return {"error": f"unknown sprite action {action!r}"}

    # ---- bmdb mode ----
    def _bmdb_apply(self, body):
        mod = self.registry.get(body["mod"])
        plan = edit.plan_bmdb(mod, edit.bmdb_request_from_dict(body))
        log.info("BMDB   edit %s in %s",
                 ", ".join(sorted(plan.entry_updates) + [n for n, _r, _p in plan.new_entries])
                 or "(nothing)", mod.name)
        rec = edit.apply_edit(plan)
        self.registry.invalidate(body["mod"])
        log.info("BMDB   done id=%s", rec.get("id"))
        return {"record": rec, "plan": _edit_payload(plan)}

    def _bmdb_cleanup(self, body):
        sink = _progress_sink(body.get("job") or "")
        if sink:
            sink(1, "working out what moves")
        mod = self.registry.get(body["mod"])
        plan = bmdb.plan_cleanup(mod, bmdb.cleanup_request_from_dict(body))
        log.info("BMDB   cleanup %s -> %s (%d entries, %d mounts, %d files)", mod.name,
                 plan.target, len(plan.entry_deletes), len(plan.mount_deletes),
                 len(plan.exports))
        rec = bmdb.apply_cleanup(plan, progress=sink)
        self.registry.invalidate(body["mod"])
        for line in plan.summary().splitlines()[1:]:
            if line.strip():
                log.info("   %s", line.strip())
        out = {"record": rec, "plan": _cleanup_payload(plan)}
        if _strings_bin_wanted(body):
            if sink:
                sink(99, "clearing the unit-text cache")
            _clear_cache(mod.root, out, rec, mod.name)
        return out

    def _base_fields(self, q):
        """EDU fields of ``unit`` after applying ``base``'s stat template.

        Also serves replace mode (``mode=replace``), where the "base" is the unit
        being replaced: the same composition, plus the icon-folder pins, so the
        editor's rows are exactly the block that will be written and each B button
        switches a field the transfer engine will actually honour.
        """
        from . import edu as _edu
        sname = (q.get("source") or [None])[0]
        dname = (q.get("dest") or [None])[0]
        utype = (q.get("unit") or [None])[0]
        btype = (q.get("base") or [None])[0]
        replacing = (q.get("mode") or [""])[0] == "replace"
        what = "unit to replace" if replacing else "base"
        names = self.registry.names()
        if not (sname in names and dname in names and utype and btype):
            return {"error": "bad params"}
        unit = self.registry.get(sname).edu.by_type().get(utype)
        base = self.registry.get(dname).edu.by_type().get(btype)
        if unit is None or base is None:
            return {"error": f"unit or {what} not found"}
        if base.kind() != unit.kind():
            return {"error": f"{what} is {base.kind() or '?'}, unit is {unit.kind() or '?'}"}
        # mirror the real transfer exactly, including whole groups taken from the base
        body = {k: (q.get(k) or ["source"])[0]
                for k in ("soldier_from", "officer_from", "mount_from",
                          "crew_from", "upgrade_from")}
        for k in ("import_mount_with_base", "import_officers_with_base"):
            body[k] = (q.get(k) or ["1"])[0] not in ("0", "false", "")
        opts = _options_from(body)
        keys = _edu.REPLACE_COPY_KEYS if replacing else _edu.BASE_COPY_KEYS
        groups = base_field_groups_for(opts)
        # a group goes back to the source when its models are being imported over
        # the base's (only their animations are borrowed) — the composed preview
        # has to show the same block the transfer will actually write
        if mount_base_import(base, self.registry.get(dname), unit, opts)[0]:
            groups = [g for g in groups if g != "mount"]
        if officer_base_import(base, self.registry.get(dname), unit, opts)[0]:
            groups = [g for g in groups if g != "officer"]
        composed = compose_with_base(unit.raw, base.raw, groups, copy_keys=keys)
        return {"unit": utype, "base": btype,
                "fields": _edu.block_fields(composed),
                "inherited": list(keys) + groups,
                "base_field_groups": groups}

    def _eop_dirs(self, body):
        """Read or set one mod's M2TWEOP unit folders.

        A POST with no ``dirs`` key only reads (so the settings panel can show the
        auto-detected folders without saving them as an explicit choice); a POST
        that carries ``dirs`` saves it, and an empty list clears the setting and
        goes back to detection.
        """
        name = body.get("mod") or ""
        if name not in self.registry.names():
            return {"error": f"unknown mod {name!r}"}
        mod = self.registry.get(name)
        if "dirs" in body:
            _eop.set_configured_dirs(mod, [str(d) for d in (body.get("dirs") or [])])
            edit._invalidate(mod)             # units move between files as this changes
        return {
            "mod": mod.name,
            "configured": [str(p) for p in _eop.configured_dirs(mod)],
            "detected": [str(p) for p in _eop.detect_dirs(mod)],
            "dirs": [str(p) for p in mod.eop_dirs],
            "files": [_eop.rel_to_root(mod, p) for p in _eop.unit_files(mod)],
            "eop_count": len(mod.edu.eop_units),
            "edu_count": len(mod.edu.main_units),
        }

    def _dirs(self, q):
        """List sub-folders under a mod's data/ dir, for the reroute browser.

        Always resolves inside data/ (never escapes it) and defaults to unit_models.
        """
        name = (q.get("mod") or [None])[0]
        rel = (q.get("path") or ["unit_models"])[0] or "unit_models"
        if not name or name not in self.registry.names():
            return {"error": "unknown mod"}
        data = self.registry.get(name).data.resolve()
        rel = rel.replace("\\", "/").strip("/")
        target = (data / rel).resolve()
        try:                                   # refuse anything outside data/
            target.relative_to(data)
        except ValueError:
            target, rel = data / "unit_models", "unit_models"
        if not target.is_dir():
            target, rel = data / "unit_models", "unit_models"
        dirs = sorted((p.name for p in target.iterdir() if p.is_dir()),
                      key=str.lower) if target.is_dir() else []
        parent = "/".join(rel.split("/")[:-1]) if "/" in rel else ""
        return {"path": rel, "parent": parent, "dirs": dirs,
                "can_up": rel.lower() != "unit_models" and bool(rel)}

    def _file(self, p: Path, ctype: str):
        if not p.exists():
            return self._err(404, f"missing {p.name}")
        self._send(200, p.read_bytes(), ctype)

    #: What a URL path under web/ is allowed to be. The UI is the only thing
    #: served from disk, so this stays deliberately short.
    WEB_TYPES = {".js": "application/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8",
                 ".svg": "image/svg+xml", ".png": "image/png"}

    def _web_asset(self, url_path: str):
        """Serve a file from web/ — the UI's own scripts, nothing else.

        The path is resolved and then checked to be *inside* web/, so `..` or an
        absolute path cannot walk out of it and turn the tool into a file reader
        for whatever the browser asks for.
        """
        rel = urllib.parse.unquote(url_path.lstrip("/"))
        p = (WEB_DIR / rel).resolve()
        try:
            p.relative_to(WEB_DIR.resolve())
        except ValueError:
            return self._err(403, "outside web/")
        ctype = self.WEB_TYPES.get(p.suffix.lower())
        if not ctype or not p.is_file():
            return self._err(404, f"no such asset: {rel}")
        self._send(200, p.read_bytes(), ctype)

    #: what the browse dialog is allowed to preview — the formats a card can be
    #: imported from, and nothing that would turn this into a file reader
    PREVIEW_EXTS = {".tga", ".dds", ".png", ".jpg", ".jpeg", ".bmp", ".gif"}

    def _preview_image(self, path: str):
        """Decode an off-mod image to PNG for the editor's card preview.

        Same never-500 rule as :meth:`_icon`: a failure paints a blank, because a
        broken-image glyph in the editor reads as "your file is corrupt".
        """
        try:
            p = Path(path)
            if (path and p.is_file()
                    and p.suffix.lower() in self.PREVIEW_EXTS
                    and p.stat().st_size <= 64 * 1024 * 1024):
                return self._send(200, self.registry.icons.png_bytes(p), "image/png")
        except Exception:
            pass
        try:
            self._send(200, self.registry.icons.png_bytes(None), "image/png")
        except Exception:
            pass

    #: Native sizes of M2TW building art — the small browser icon and the big
    #: "constructed" picture. Used only for the placeholder, so a missing icon
    #: occupies exactly the space the real one would.
    BUILDING_ICON_SIZE = {"small": (78, 62), "large": (300, 245)}

    def _building_icon(self, q):
        """Serve one building icon as PNG, or a placeholder if there is none.

        Never 500s, for the same reason as :meth:`_icon`: a failed response
        paints a broken-image glyph across the grid. The ``X-Icon-Source``
        header says where the art came from (``mod`` / ``vanilla`` /
        ``placeholder``) so the UI can badge borrowed art.
        """
        kind = (q.get("kind") or ["small"])[0]
        source = "placeholder"
        data = None
        try:
            name = (q.get("mod") or [None])[0]
            culture = (q.get("culture") or [""])[0]
            level = (q.get("level") or [""])[0]
            if name and culture and level and name in self.registry.names():
                mod = self.registry.get(name)
                src, source = mod.find_building_icon(
                    culture, level, kind, config.get_vanilla_ui_root())
                if src is not None:
                    data = self.registry.icons.png_bytes(src)
                else:
                    source = "placeholder"
        except Exception:
            log.debug("building icon failed", exc_info=True)
            data = None
        try:
            if data is None:
                w, h = self.BUILDING_ICON_SIZE.get(kind, self.BUILDING_ICON_SIZE["small"])
                data = self.registry.icons.placeholder_png(w, h)
            self._send(200, data, "image/png", {"X-Icon-Source": source})
        except Exception:
            pass

    def _icon(self, q):
        # Icons must NEVER 500: a failed response paints a broken-image glyph in
        # the grid. On any trouble, fall back to a blank PNG with 200 instead.
        try:
            name = (q.get("mod") or [None])[0]
            utype = (q.get("type") or [None])[0]
            kind = (q.get("kind") or ["card"])[0]
            src = None
            if kind == "ancillary" and name and name in self.registry.names():
                # An ancillary names a file under data/ui/ancillaries rather than
                # a unit, so it is looked up by image name; a mod that keeps a
                # stock picture without shipping it falls through to vanilla's.
                src = ancillaries.image_path(self.registry.get(name),
                                             (q.get("image") or [""])[0])
                self._send(200, self.registry.icons.png_bytes(src), "image/png")
                return
            if kind in ("faction", "modfile") and name and name in self.registry.names():
                # A picture the page already knows the path of: a faction symbol
                # (named by convention, not by any field) or one of a unit's card
                # variants. `picture_path` is what keeps `rel` inside data/.
                src = factions.picture_path(self.registry.get(name),
                                            (q.get("rel") or [""])[0])
                self._send(200, self.registry.icons.png_bytes(src), "image/png")
                return
            if name and utype and name in self.registry.names():
                m = self.registry.get(name)
                unit = m.edu.by_type().get(utype)
                if unit is not None:
                    src = m.find_unit_info(unit) if kind == "info" else m.find_unit_card(unit)
                    if src is None:
                        # Said here rather than in the icon cache, which only ever
                        # sees a path: a blank card is normal (the mod ships no art
                        # and the game falls back to its own), and the log has to
                        # tell that apart from a conversion that failed.
                        log.debug("ICON   %s has no %s art in %s", utype, kind, name)
            self._send(200, self.registry.icons.png_bytes(src), "image/png")
        except Exception:
            try:
                self._send(200, self.registry.icons.png_bytes(None), "image/png")
            except Exception:
                pass


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    # A freshly rendered page fires dozens of icon requests at once; a bigger
    # listen backlog stops the OS from dropping bursts (which the browser would
    # surface as broken images).
    request_queue_size = 128
    # HTTPServer defaults this to 1, but on Windows SO_REUSEADDR lets a SECOND
    # instance bind a port that is already serving — the two then fight over
    # requests. Off on Windows so a duplicate launch fails loudly instead.
    allow_reuse_address = (os.name != "nt")


def serve(cache_dir: Path, host="127.0.0.1", port=8756, on_ready=None, verbose=False):
    setup_logging(verbose)
    logutil.banner(port)
    Handler.registry = Registry(cache_dir)
    httpd = _Server((host, port), Handler)     # socket is bound + listening here
    log.info("Unit Transfer UI  ->  http://%s:%d/", host, port)
    log.info("MED2 root: %s", config.get_med2_root() or "(not set — choose it in the UI)")
    log.info("Mods found: %s", ", ".join(Handler.registry.names()) or "(none yet)")
    log.info("Ctrl+C to stop (or use Quit in the UI's settings, or close the browser tab).")
    threading.Thread(target=_liveness_watchdog, args=(httpd,), daemon=True).start()
    if on_ready:                               # e.g. open the browser now that we're up
        try:
            on_ready()
        except Exception:
            log.debug("on_ready failed", exc_info=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log.info("interrupted — stopping")
        httpd.shutdown()
    log.info("server stopped")
    return httpd
