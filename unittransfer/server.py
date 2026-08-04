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
  GET  /api/mods                 -> [{name, root}]  (scanned under med2_root/mods)
  GET  /api/units?mod=NAME       -> {mod, factions, categories, classes, units}
  GET  /icon?mod=&type=&kind=    -> image/png
  POST /api/plan                 -> {source,dest,unit,options} -> plan preview
  POST /api/apply                -> {source,dest,unit,options} -> apply + record
  GET  /api/log                  -> transfer log
  POST /api/undo                 -> {id} -> undo a transfer

Unit-editor mode (edits inside ONE mod, see :mod:`unittransfer.edit`)
  GET  /api/edit/unit?mod=&type= -> fields + localisation + modeldb entries
  POST /api/edit/model_folder    -> {mod,entry,target} -> where an entry's files
                                    live + what moving them would touch
  POST /api/edit/plan            -> preview an edit / delete
  POST /api/edit/apply           -> apply it (same backups + undo as a transfer)
  POST /api/browse_file          -> native file dialog (mesh/texture import)

BMDB mode (the whole battle_models.modeldb, see :mod:`unittransfer.bmdb`)
  GET  /api/bmdb/entries?mod=    -> every entry, light (the browser list)
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
  POST /api/sprites/convert_plan -> what the TGA -> .texture run would do
  POST /api/sprites/convert_apply-> run it, dedup, install into the mod
  POST /api/sprites/wire         -> point the modeldb's sprite lines at the
                                    result (backups + undo, via bmdb mode)

Sounds mode (the unit voice bank, see :mod:`unittransfer.sounds`)
  GET  /api/sounds?mod=          -> accents/classes, donors, and every unit split
                                    into "has a voice entry" / "doesn't"
  POST /api/sounds/plan | /apply -> stage voice edits, then write them (backups +
                                    undo, same as a transfer)
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.parse
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Optional

from . import bmdb, cleaner, config, edit, sounds, sprites
from . import eop as _eop
from .logutil import log, setup as setup_logging
from .icons import IconCache
from .mod import Mod
from .transfer import (TransferOptions, plan_transfer, apply_transfer, undo, revert_to,
                       base_field_groups_for, compose_with_base)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

# Liveness: the page sends /api/heartbeat every few seconds and /api/bye when its
# tab closes, so the (often windowless) server shuts down instead of lingering and
# holding the port. A watchdog thread does the actual shutdown.
_LIVENESS: Dict[str, Optional[float]] = {"last_beat": None, "pending_close": None}


def page_ever_loaded() -> bool:
    """True once a browser has actually rendered the UI and started heartbeating.

    The one trustworthy "did a browser really open?" signal. ``webbrowser.open()``
    returns True on Windows even when nothing opens (no default browser, a broken
    file association, a blocked handler), so the launcher can't rely on it — but a
    heartbeat can only come from a real page that really loaded.
    """
    return _LIVENESS["last_beat"] is not None
_BYE_GRACE = 8.0          # seconds after a tab-close beacon before we stop (survives a refresh)
_DEAD_MAN = 150.0         # seconds without any heartbeat before we stop (backgrounded tabs throttle)


def _liveness_watchdog(httpd) -> None:
    while True:
        time.sleep(2)
        now = time.time()
        lb, pc = _LIVENESS["last_beat"], _LIVENESS["pending_close"]
        closed = pc is not None and now - pc > _BYE_GRACE and (lb is None or lb < pc)
        dead = lb is not None and now - lb > _DEAD_MAN
        if closed or dead:
            log.info("browser %s — shutting down",
                     "tab closed" if closed else f"idle >{int(_DEAD_MAN)}s")
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


def _clear_cache(mod_root, out: dict, rec: dict, mod_name: str) -> None:
    """Run the cache clear for a finished job and record what it did."""
    res = cleaner.clear_strings_bin(mod_root)
    out["strings_bin"] = res
    if res.get("deleted"):
        log.info("CACHE  cleared %s in %s", cleaner.STRINGS_BIN_REL, mod_name)
    elif res.get("missing"):
        log.info("CACHE  %s not present in %s — nothing to clear",
                 cleaner.STRINGS_BIN_REL, mod_name)
    else:
        log.warning("CACHE  not cleared: %s", res.get("error"))
    config.update_log(rec.get("id", ""), strings_bin=res)


class Registry:
    def __init__(self, cache_dir: Path):
        self.icons = IconCache(cache_dir)
        self._mods: Dict[str, Mod] = {}
        self._sigs: Dict[str, tuple] = {}      # name -> on-disk signature when cached
        # ThreadingHTTPServer serves the ~dozens of icon requests of one page
        # concurrently; Mod's cached_property parsers and this dict are not
        # thread-safe, so serialise mod resolution + first-parse behind a lock.
        self._lock = threading.RLock()

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
                  mod.eds_path):
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
        return out

    def names(self) -> List[str]:
        return list(self.discover())

    def get(self, name: str) -> Mod:
        with self._lock:
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
            if cached is None:
                cached = Mod(paths[name])
                self._mods[name] = cached
                self._sigs[name] = self._signature(cached)
            # Warm the light parsed DBs *inside the lock* so concurrent icon /
            # units requests never trigger a cached_property parse race (which
            # would surface as sporadic 500s -> broken card images). The heavy
            # modeldb is left lazy; it's only needed by the serialised plan/apply.
            _ = cached.edu, cached.loc, cached.faction_names, cached.mounts
            return cached

    def invalidate(self, name: str):
        with self._lock:
            self._mods.pop(name, None)
            self._sigs.pop(name, None)


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


def build_units_response(m: Mod) -> dict:
    units = [_unit_payload(m, u) for u in m.edu.units]
    factions = sorted({f for u in m.edu.units for f in u.ownership})
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
    def _send(self, code, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json")

    def _err(self, code, msg):
        self._json({"error": msg}, code)

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
        try:
            if u.path in ("/", "/index.html"):
                return self._file(WEB_DIR / "index.html", "text/html; charset=utf-8")
            if u.path == "/api/ping":
                # identifies an already-running instance to a second launch
                import os as _os
                return self._json({"app": "unit-transfer", "pid": _os.getpid()})
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
                return self._json([{"name": n, "root": str(p)}
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
            if u.path in ("/api/bmdb/entries", "/api/bmdb/entry", "/api/bmdb/audit"):
                name = (q.get("mod") or [None])[0]
                if not name or name not in self.registry.names():
                    return self._err(404, "unknown mod")
                audit = u.path == "/api/bmdb/audit"
                # reported before the mod is resolved: parsing its EDU is already
                # a second or two, and the page is showing a bar by then
                sink = _progress_sink((q.get("job") or [""])[0]) if audit else None
                if sink:
                    sink(1, f"reading {name}'s files")
                mod = self.registry.get(name)
                if u.path == "/api/bmdb/entries":
                    return self._json(bmdb.overview(mod))
                if u.path == "/api/bmdb/entry":
                    return self._json(bmdb.entry_detail(mod, (q.get("name") or [""])[0]))
                log.info("BMDB   audit of %s", name)
                return self._json(bmdb.audit(mod, progress=sink))
            if u.path == "/api/sounds":
                name = (q.get("mod") or [None])[0]
                if not name or name not in self.registry.names():
                    return self._err(404, "unknown mod")
                return self._json(sounds.overview(self.registry.get(name)))
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
                return self._json(config.load_log())
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

    # ---- POST ----
    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
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
            if u.path == "/api/edit/model_folder":
                # "do all this entry's files live in one folder, and who else
                # would a move affect" — answered before the user commits to it.
                mod = self.registry.get(body.get("mod") or "")
                return self._json(edit.model_folder_report(
                    mod, body.get("entry") or "", body.get("target") or ""))
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
            if u.path == "/api/sounds/plan":
                mod = self.registry.get(body["mod"])
                return self._json(_sound_payload(
                    sounds.plan_sounds(mod, sounds.ops_from_dicts(body.get("ops")))))
            if u.path == "/api/sounds/apply":
                return self._json(self._sounds_apply(body))
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
        opts = _options_from({k: (q.get(k) or ["source"])[0]
                              for k in ("soldier_from", "officer_from", "mount_from",
                                        "crew_from", "upgrade_from")})
        keys = _edu.REPLACE_COPY_KEYS if replacing else _edu.BASE_COPY_KEYS
        groups = base_field_groups_for(opts)
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

    def _icon(self, q):
        # Icons must NEVER 500: a failed response paints a broken-image glyph in
        # the grid. On any trouble, fall back to a blank PNG with 200 instead.
        try:
            name = (q.get("mod") or [None])[0]
            utype = (q.get("type") or [None])[0]
            kind = (q.get("kind") or ["card"])[0]
            src = None
            if name and utype and name in self.registry.names():
                m = self.registry.get(name)
                unit = m.edu.by_type().get(utype)
                if unit is not None:
                    src = m.find_unit_info(unit) if kind == "info" else m.find_unit_card(unit)
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
