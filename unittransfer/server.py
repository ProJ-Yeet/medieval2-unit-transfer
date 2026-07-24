"""Local web server for the Unit Transfer UI (Stage 4).

Serves a single-page app to browse a source mod's units faction-wise (with icons),
pick a destination mod, and transfer units with options + conflict resolution.
Transfers apply in-place into the destination mod (backing up first) and every
transfer is logged with an undo.

API
  GET  /                         -> SPA
  GET  /api/settings             -> {med2_root, last_source, last_dest}
  POST /api/settings             -> set {med2_root,...} (persisted)
  GET  /api/mods                 -> [{name, root}]  (scanned under med2_root/mods)
  GET  /api/units?mod=NAME       -> {mod, factions, categories, classes, units}
  GET  /icon?mod=&type=&kind=    -> image/png
  POST /api/plan                 -> {source,dest,unit,options} -> plan preview
  POST /api/apply                -> {source,dest,unit,options} -> apply + record
  GET  /api/log                  -> transfer log
  POST /api/undo                 -> {id} -> undo a transfer
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

from . import cleaner, config
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
                  mod.descr_engine_skeleton_path, mod.expanded_path):
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
        # projectile(s) the unit fires (stat_pri/stat_sec slot 3); [] for melee.
        "projectiles": u.projectiles(),
        "has_card": m.find_unit_card(u) is not None,
    }


def build_units_response(m: Mod) -> dict:
    units = [_unit_payload(m, u) for u in m.edu.units]
    factions = sorted({f for u in m.edu.units for f in u.ownership})
    return {
        "mod": m.name,
        "factions": factions,
        "faction_names": {f: m.faction_names.get(f.lower(), "") for f in factions},
        # "categories" is the refined kind (cavalry split into Cavalry /
        # Cavalry_Lance / Cavalry_Archer) — it drives the filter and the base picker.
        "categories": sorted({u.kind() for u in m.edu.units if u.kind()}),
        "classes": sorted({u.class_type for u in m.edu.units if u.class_type}),
        "units": units,
    }


def _options_from(d: dict) -> TransferOptions:
    return TransferOptions(
        include_officers=bool(d.get("include_officers", True)),
        include_mount=bool(d.get("include_mount", True)),
        include_crew=bool(d.get("include_crew", True)),
        include_projectile=bool(d.get("include_projectile", True)),
        include_engine=bool(d.get("include_engine", True)),
        exclude_models=[str(m).lower() for m in (d.get("exclude_models") or [])],
        on_conflict=d.get("on_conflict", "rename"),
        new_type=d.get("new_type") or None,
        new_dictionary=d.get("new_dictionary") or None,
        base_type=d.get("base_type") or None,
        soldier_from=d.get("soldier_from", "source"),
        officer_from=d.get("officer_from", "source"),
        mount_from=d.get("mount_from", "source"),
        crew_from=d.get("crew_from", "source"),
        field_overrides=dict(d.get("field_overrides") or {}),
        asset_conflict=d.get("asset_conflict", "mod_folder"),
        asset_reroute_dir=d.get("asset_reroute_dir") or None,
        icon_conflict=d.get("icon_conflict", "use_existing"),
        engine_conflict=d.get("engine_conflict", "use_existing"),
        make_mercenary=bool(d.get("make_mercenary", False)),
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
        "dest_unit_count": len(plan.dest.edu.units),
        "dest_new_units": plan.dest_new_units,
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
                return self._json(config.load_settings())
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
            if u.path == "/api/log":
                return self._json(config.load_log())
            if u.path == "/icon":
                return self._icon(q)
            return self._err(404, "not found")
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
        # Clear the game's regenerated caches so the new unit actually shows up.
        # On by default; a batch only asks for it on its final unit.
        if (config.load_settings().get("run_full_cleaner", True)
                and body.get("run_cleaner", True) and not plan.skipped):
            res = cleaner.run_full_cleaner(dest.root)
            out["cleaner"] = res
            if res.get("ran"):
                log.info("CLEANER ran in %s (rc=%s%s)", dest.name,
                         res.get("returncode"), ", copied in" if res.get("copied") else "")
            else:
                log.warning("CLEANER did not run: %s", res.get("error"))
            config.update_log(rec.get("id", ""), cleaner=res)
        return out

    def _base_fields(self, q):
        """EDU fields of ``unit`` after applying ``base``'s stat template."""
        from . import edu as _edu
        sname = (q.get("source") or [None])[0]
        dname = (q.get("dest") or [None])[0]
        utype = (q.get("unit") or [None])[0]
        btype = (q.get("base") or [None])[0]
        names = self.registry.names()
        if not (sname in names and dname in names and utype and btype):
            return {"error": "bad params"}
        unit = self.registry.get(sname).edu.by_type().get(utype)
        base = self.registry.get(dname).edu.by_type().get(btype)
        if unit is None or base is None:
            return {"error": "unit or base not found"}
        if base.kind() != unit.kind():
            return {"error": f"base is {base.kind() or '?'}, unit is {unit.kind() or '?'}"}
        # mirror the real transfer exactly, including whole groups taken from the base
        opts = _options_from({k: (q.get(k) or ["source"])[0]
                              for k in ("soldier_from", "officer_from",
                                        "mount_from", "crew_from")})
        groups = base_field_groups_for(opts)
        composed = compose_with_base(unit.raw, base.raw, groups)
        return {"unit": utype, "base": btype,
                "fields": _edu.block_fields(composed),
                "inherited": list(_edu.BASE_COPY_KEYS) + groups,
                "base_field_groups": groups}

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
