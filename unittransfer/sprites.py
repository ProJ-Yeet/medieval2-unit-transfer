"""Unit sprite generation: prep the game, convert what it spat out, wire it in.

Sprites are the flat 2D billboards M2TW swaps in for a unit's mesh at the far
LOD. The engine can render them for you, but only as a side effect of booting
the game with a magic CFG flag, and what lands on disk is raw TGA that nothing
downstream can read. This module owns everything either published method leaves
manual or leaves to a GUI.

Two generation methods exist and this module supports both, because they differ
*only* in how the TGAs get produced:

classic (Caliban/Gigantus, TWC thread 663024)
    ``sprite_script.txt`` in the Medieval II Total War **root** (not the mod —
    that is the single most common failure in the thread), one modeldb model
    name per line, ``bypass_sprite_script = 1`` under ``[misc]`` in whichever
    CFG actually launches the mod, then run the mod once. Works everywhere.

eop (M2TWEOP console)
    ``M2TWEOP.generateSprite("model")`` from the main menu. No CFG edit, no
    restart per batch — strictly nicer when the mod runs EOP, so it is the
    default when we can see an EOP install.

Everything after generation is ours:

* **Convert.** The published route is a GUI (``_1 Convert TGA to DDS.exe``) then
  a Python **2** script. We drive the GUI's own engine, ``nvcompress.exe``,
  headless from ``tools/nvtt/`` and re-implement the ``.texture`` container in
  Python 3 — see :func:`dds_to_texture`. That removes the Python 2.6 install the
  tutorial demands and the manual folder-browsing step.
* **Dedup.** The engine emits one sprite set per faction in the entry's
  ownership list. Identical sets are the norm, so we keep one and repoint the
  rest rather than shipping a dozen byte-identical sheets.
* **Wire-up.** Both methods stop at "make sure your modeldb tallies", by hand.
  We build the sprite lines and hand them to :mod:`unittransfer.edit`, which
  already gives us backups + undo.
"""
from __future__ import annotations

import hashlib
import os
import re
import struct
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from . import config, edit, modeldb
from .logutil import log
from .mod import Mod

# Where the game always writes sprites, relative to the Medieval II Total War
# root. Not configurable — the engine hard-codes it, which is why the tutorial
# insists the folder must exist at the root and not under the mod.
EXPORT_REL = Path("export") / "unit_sprites"

# Where they have to end up to be loadable, relative to a mod's data/.
INSTALL_REL = Path("unit_sprites")

SCRIPT_NAME = "sprite_script.txt"

# Most misnamed rows the page will ever act on in one go; the rest come back on
# the next pass, which is cheaper than shipping an unbounded list to a browser.
AUDIT_CAP = 500

# The bundled NVIDIA Texture Tools compressor. Vendored (996K) so the workspace
# works out of the box; ``bin/settings.xml`` from the published setup is what
# fixes the flags below — DXT5, clamped.
NVTT_DIR = config.PROJECT_ROOT / "tools" / "nvtt"
NVCOMPRESS = NVTT_DIR / "nvcompress.exe"


# ---------------------------------------------------------------------------
# .texture container
#
# A M2TW .texture is a 48-byte header followed by a verbatim DDS file. Ported
# from alpaca's texture_converter.py 0.1 (2006), which is Python 2 only; the
# byte layout below is that script's, preserved exactly.

_INIT = (0x01000000, 0x30000000, 0x00000000)
_NORM_HEADER = (0x0044E212, 0x00986212, 0x03C0DA12)
_FILL = bytes((0x02, 0, 0, 0, 0, 0, 0, 0x65, 0x56, 0x3A, 0x7C, 3, 0, 0, 0))

# DDS fourCC (at offset 84) -> the constant the container records for it.
_DXT_CODE = {b"DXT5": 16384, b"DXT1": 4096}

TEXTURE_HEADER_LEN = 48


class SpriteError(Exception):
    """Something the user can fix — surfaced in the UI, not a traceback."""


def dds_to_texture(dds: bytes) -> bytes:
    """Wrap raw DDS bytes in the 48-byte .texture header the engine expects.

    Only DXT1/DXT5 are encodable: the header records a size constant per format
    and there is no value for anything else, which is why the original script
    bails with "could not be converted" instead of guessing.
    """
    if dds[:4] != b"DDS ":
        raise SpriteError("not a DDS file (bad magic)")
    code = _DXT_CODE.get(bytes(dds[84:88]))
    if code is None:
        got = bytes(dds[84:88]).decode("ascii", "replace")
        raise SpriteError(f"unsupported DDS format {got!r} — need DXT5 or DXT1")
    out = bytearray()
    for i in _INIT:
        out += struct.pack(">i", i)
    out += b"dds"
    for i in _NORM_HEADER:
        out += struct.pack(">i", i)
    # native short in the original (x86 little-endian); pinned explicitly here so
    # the output can't drift with the interpreter's platform
    out += struct.pack("<h", code)
    out += _FILL
    out += dds[12:16]          # DDS dwHeight, copied raw
    out += dds
    assert len(out) - len(dds) == TEXTURE_HEADER_LEN
    return bytes(out)


def texture_to_dds(tex: bytes) -> bytes:
    """Unwrap a .texture back to DDS — the inverse of :func:`dds_to_texture`."""
    if len(tex) <= TEXTURE_HEADER_LEN:
        raise SpriteError("truncated .texture file")
    return tex[TEXTURE_HEADER_LEN:]


# ---------------------------------------------------------------------------
# naming contract

_SPRITE_RE = re.compile(r"^(?P<faction>[a-z0-9_]+?)_(?P<model>[a-z0-9_]+)_sprite$", re.I)


def sprite_stem(faction: str, model: str) -> str:
    """``<faction>_<model>_sprite`` — the name the engine derives, not a choice.

    The generator names its output from the modeldb entry's faction record, so a
    modeldb sprite line that says anything else points at a file that will never
    exist. Both tutorials call this out; neither checks it.

    Casing is preserved, not normalised: the generator copies the entry's own
    casing (real mods carry ``england_Mount_Pony_sprite.spr``), and lowercasing
    here would rewrite every sprite line in a mod's modeldb to no effect —
    Windows resolves either spelling to the same file.
    """
    return f"{faction.strip()}_{model.strip()}_sprite"


def sprite_line(faction: str, model: str) -> str:
    """The modeldb sprite path for a faction record."""
    return f"{INSTALL_REL.as_posix()}/{sprite_stem(faction, model)}.spr"


def _model_casing(entry: "modeldb.ModelEntry") -> str:
    """How the modeldb spells this entry's name *inside its sprite paths*.

    ``ModelEntry.name`` is lowercased by the parser, but the paths are not — real
    mods carry ``aztecs_Mount_Pony_sprite.spr`` for an entry keyed
    ``mount_pony``, and the generator copies that casing onto the files it
    writes. Recovering it from an existing line is what makes a wire-up a no-op
    where the modeldb was already correct.
    """
    want = entry.name.lower()
    prefix = INSTALL_REL.as_posix() + "/"
    for t in entry.main_textures:
        rel = (t.sprite or "").strip().replace("\\", "/")
        if not rel or rel == "0":
            continue
        stem = rel[len(prefix):] if rel.lower().startswith(prefix) else rel
        stem = Path(stem).stem
        if not stem.lower().endswith("_sprite"):
            continue
        core = stem[: -len("_sprite")]
        # strip the faction prefix; what remains must be this entry's name
        if core.lower().endswith("_" + want):
            return core[len(core) - len(want):]
    return entry.name


def _real_names(entry: "modeldb.ModelEntry", faction: str) -> Tuple[str, str]:
    """The faction's and model's casing as the modeldb actually spells them."""
    model = _model_casing(entry)
    for t in entry.main_textures:
        if t.faction.lower() == faction.lower():
            return t.faction, model
    return faction, model


def split_sprite_stem(stem: str) -> Optional[Tuple[str, str]]:
    """``milan_guardofthecaves_sprite`` -> ``("milan", "guardofthecaves")``.

    Ambiguous by construction (both halves may contain underscores), so the
    caller is expected to disambiguate against real model names — see
    :func:`_match_stem`.
    """
    m = _SPRITE_RE.match(stem)
    return (m.group("faction"), m.group("model")) if m else None


def _match_stem(stem: str, models: Iterable[str]) -> Optional[Tuple[str, str]]:
    """Split a sprite stem using the mod's actual model names as the oracle.

    ``byzantium_mount_heavy_horse_sprite`` splits four different ways on
    underscores alone; only one of them names a model that exists. Longest
    model match wins, so ``x_heavy_horse`` beats ``x_horse`` when both exist.
    """
    if not stem.lower().endswith("_sprite"):
        return None
    core = stem[: -len("_sprite")].lower()
    best: Optional[Tuple[str, str]] = None
    for m in models:
        m = m.lower()
        suffix = "_" + m
        if core.endswith(suffix) and len(core) > len(suffix):
            faction = core[: -len(suffix)]
            if best is None or len(m) > len(best[1]):
                best = (faction, m)
    return best


# ---------------------------------------------------------------------------
# prep


@dataclass
class PrepRequest:
    models: List[str] = field(default_factory=list)
    method: str = "eop"                 # "eop" | "classic"
    cfg_path: str = ""                  # classic only; the CFG that launches the mod


@dataclass
class PrepPlan:
    mod: Mod
    med2_root: Path
    request: PrepRequest
    known: List[str] = field(default_factory=list)      # models present in the modeldb
    unknown: List[str] = field(default_factory=list)    # typo'd / not in the modeldb
    mounts: List[str] = field(default_factory=list)     # models that are mount entries
    script_path: Optional[Path] = None
    export_dir: Optional[Path] = None
    cfg_edit: Optional[dict] = None     # {"path", "action", "line"}
    lua: str = ""                       # EOP console snippet
    warnings: List[str] = field(default_factory=list)

    def summary(self) -> str:
        out = [f"prep {len(self.known)} model(s) for sprite generation "
               f"({self.request.method})"]
        if self.script_path:
            out.append(f"  write {self.script_path}")
        if self.export_dir:
            out.append(f"  ensure {self.export_dir}")
        if self.cfg_edit:
            out.append(f"  {self.cfg_edit['action']} {self.cfg_edit['line']!r} "
                       f"in {self.cfg_edit['path']}")
        for u in self.unknown:
            out.append(f"  ! {u} is not a modeldb entry")
        return "\n".join(out)


def _med2_root(mod: Mod) -> Path:
    """The Medieval II Total War root, i.e. the folder holding ``mods/``.

    Derived from the mod rather than settings so it stays correct for a mod
    opened from somewhere unusual; falls back to the configured root.
    """
    for parent in mod.root.parents:
        if (parent / "mods").is_dir() and (parent / "data").is_dir():
            return parent
    root = config.get_med2_root()
    if not root:
        raise SpriteError(
            "can't locate the Medieval II Total War root — set it in Settings")
    return Path(root)


def find_cfgs(mod: Mod) -> List[str]:
    """CFG files that plausibly launch this mod, best guess first.

    The flag has to go in the CFG the *launcher* uses, which is why the thread is
    full of "nothing happened" — a mod commonly ships several.
    """
    root = _med2_root(mod)
    seen: List[Path] = []
    for base in (mod.root, root):
        try:
            for p in sorted(base.glob("*.cfg")):
                if p not in seen:
                    seen.append(p)
        except OSError:
            pass

    def rank(p: Path) -> tuple:
        stem = p.stem.lower()
        # a CFG named after the mod, or sitting in it, is the usual launcher
        return (0 if stem == mod.name.lower() else 1,
                0 if p.parent == mod.root else 1,
                stem)

    return [str(p) for p in sorted(seen, key=rank)]


def plan_prep(mod: Mod, req: PrepRequest) -> PrepPlan:
    """Work out what prepping generation would touch, without touching it."""
    root = _med2_root(mod)
    plan = PrepPlan(mod=mod, med2_root=root, request=req)

    entries = mod.modeldb.by_name()
    mount_models = {m.lower() for m in mod.mounts.values() if m}
    for name in req.models:
        n = name.strip().lower()
        if not n:
            continue
        if n in entries:
            plan.known.append(n)
            if n in mount_models:
                plan.mounts.append(n)
        else:
            plan.unknown.append(n)

    if not plan.known:
        plan.warnings.append("no valid model names — nothing would be generated")

    plan.export_dir = root / EXPORT_REL

    if req.method == "eop":
        plan.lua = "\n".join(f'M2TWEOP.generateSprite("{m}")' for m in plan.known)
        return plan

    # --- classic ---
    plan.script_path = root / SCRIPT_NAME
    cfg = Path(req.cfg_path) if req.cfg_path else None
    if not cfg:
        cands = find_cfgs(mod)
        cfg = Path(cands[0]) if cands else None
    if cfg is None:
        plan.warnings.append(
            "no CFG found — add 'bypass_sprite_script = 1' under [misc] by hand")
    elif not cfg.is_file():
        plan.warnings.append(f"{cfg} does not exist")
    else:
        state = _cfg_state(cfg)
        plan.cfg_edit = {"path": str(cfg),
                         "action": "already set" if state == "on" else "set",
                         "line": "bypass_sprite_script = 1"}
    return plan


_BYPASS_RE = re.compile(r"^(?P<hash>[#;]*\s*)bypass_sprite_script\s*=\s*(?P<val>\S+)",
                        re.I)


def _cfg_state(cfg: Path) -> str:
    """``on`` | ``off`` | ``absent`` for the bypass flag in a CFG."""
    try:
        for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
            m = _BYPASS_RE.match(line.strip())
            if m:
                if m.group("hash").strip():
                    return "off"
                return "on" if m.group("val").lower() in ("1", "true", "yes") else "off"
    except OSError:
        pass
    return "absent"


def set_cfg_bypass(cfg: Path, on: bool) -> bool:
    """Turn ``bypass_sprite_script`` on or off, creating ``[misc]`` if needed.

    Off means commented out rather than deleted, matching the tutorial's advice
    to hash the line so it is there for the next batch. Returns whether the file
    changed.
    """
    text = cfg.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    want = "bypass_sprite_script = 1"

    for i, line in enumerate(lines):
        m = _BYPASS_RE.match(line.strip())
        if not m:
            continue
        new = want if on else f"# {want}"
        if lines[i].strip() == new:
            return False
        lines[i] = new
        cfg.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return True

    if not on:
        return False    # nothing to turn off

    # no existing entry: append under [misc], creating the section if absent
    idx = next((i for i, l in enumerate(lines)
                if l.strip().lower() == "[misc]"), None)
    if idx is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines += ["[misc]", want]
    else:
        lines.insert(idx + 1, want)
    cfg.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


def apply_prep(plan: PrepPlan) -> dict:
    """Write the script / folder / CFG flag. EOP needs none of it."""
    rec: dict = {"method": plan.request.method, "models": list(plan.known),
                 "wrote": [], "lua": plan.lua}
    if plan.export_dir:
        plan.export_dir.mkdir(parents=True, exist_ok=True)
        rec["wrote"].append(str(plan.export_dir))
    if plan.script_path:
        plan.script_path.write_text("\n".join(plan.known) + "\n", encoding="utf-8")
        rec["wrote"].append(str(plan.script_path))
    if plan.cfg_edit:
        cfg = Path(plan.cfg_edit["path"])
        if set_cfg_bypass(cfg, True):
            rec["wrote"].append(str(cfg))
        rec["cfg"] = str(cfg)
    log.info("SPRITE prep %s: %d model(s)", plan.request.method, len(plan.known))
    return rec


def revert_prep(cfg_path: str) -> dict:
    """Comment the bypass flag back out — the step everyone forgets.

    Leaving it on means the next normal launch re-renders sprites instead of
    starting the game, which reads as a crash.
    """
    cfg = Path(cfg_path)
    if not cfg.is_file():
        raise SpriteError(f"{cfg} does not exist")
    changed = set_cfg_bypass(cfg, False)
    log.info("SPRITE revert cfg %s (%s)", cfg, "changed" if changed else "already off")
    return {"cfg": str(cfg), "changed": changed, "state": _cfg_state(cfg)}


# ---------------------------------------------------------------------------
# convert


@dataclass
class SpriteSet:
    """One generated sprite: the .spr descriptor plus its sheet(s)."""
    stem: str                       # <faction>_<model>_sprite
    faction: str
    model: str
    spr: Optional[Path] = None
    sheets: List[Path] = field(default_factory=list)   # .tga awaiting conversion
    done: List[Path] = field(default_factory=list)     # .texture already converted

    @property
    def complete(self) -> bool:
        return self.spr is not None and bool(self.sheets or self.done)


def scan_export(mod: Mod) -> Dict[str, SpriteSet]:
    """Group whatever the generator left in ``export/unit_sprites`` by sprite.

    A sprite is a ``.spr`` descriptor plus one or more sheets; the engine numbers
    the sheets (``..._sprite_000.tga``), so they group by the ``_sprite`` stem.
    """
    root = _med2_root(mod)
    src = root / EXPORT_REL
    models = list(mod.modeldb.by_name().keys())
    out: Dict[str, SpriteSet] = {}
    if not src.is_dir():
        return out

    def bucket(stem: str) -> Optional[SpriteSet]:
        # sheets carry a _000 suffix the .spr does not
        base = re.sub(r"_\d+$", "", stem)
        got = _match_stem(base, models)
        if not got:
            return None
        faction, model = got
        return out.setdefault(base, SpriteSet(stem=base, faction=faction, model=model))

    for p in sorted(src.iterdir()):
        if not p.is_file():
            continue
        ext = p.suffix.lower()
        if ext not in (".spr", ".tga", ".texture"):
            continue
        s = bucket(p.stem)
        if s is None:
            continue
        if ext == ".spr":
            s.spr = p
        elif ext == ".tga":
            s.sheets.append(p)
        else:
            s.done.append(p)
    return out


@dataclass
class ConvertRequest:
    stems: List[str] = field(default_factory=list)   # empty = everything found
    mipmaps: bool = False           # Gigantus (post 3): almost certainly unwanted
    dedup: bool = True              # collapse byte-identical faction variants
    install: bool = True            # move results into the mod's data/unit_sprites
    cleanup: bool = True            # delete the TGA/DDS intermediates afterwards


@dataclass
class ConvertPlan:
    mod: Mod
    request: ConvertRequest
    sets: List[SpriteSet] = field(default_factory=list)
    install_dir: Optional[Path] = None
    incomplete: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def summary(self) -> str:
        n = sum(len(s.sheets) for s in self.sets)
        out = [f"convert {n} sheet(s) across {len(self.sets)} sprite(s)"]
        if self.install_dir:
            out.append(f"  install into {self.install_dir}")
        for s in self.incomplete:
            out.append(f"  ! {s} is missing its .spr or its sheets")
        return "\n".join(out)


def plan_convert(mod: Mod, req: ConvertRequest) -> ConvertPlan:
    plan = ConvertPlan(mod=mod, request=req)
    if not NVCOMPRESS.is_file():
        plan.warnings.append(f"nvcompress.exe missing from {NVTT_DIR}")
    found = scan_export(mod)
    want = {s.lower() for s in req.stems}
    for stem, s in sorted(found.items()):
        if want and stem.lower() not in want:
            continue
        if not s.complete:
            plan.incomplete.append(stem)
            continue
        plan.sets.append(s)
    if req.install:
        plan.install_dir = mod.data / INSTALL_REL
    if not plan.sets:
        plan.warnings.append(
            f"nothing to convert in {_med2_root(mod) / EXPORT_REL} — "
            "has the generator run yet?")
    return plan


def _run_nvcompress(tga: Path, dds: Path, mipmaps: bool) -> None:
    """TGA -> DXT5 DDS, headless.

    The published route pops a GUI and makes you browse to the folder every time;
    this is that GUI's own engine with the settings its ``settings.xml`` preset
    (DXT5, clamp) passed on the command line.
    """
    cmd = [str(NVCOMPRESS), "-bc3", "-clamp", "-nocuda"]
    if not mipmaps:
        cmd.append("-nomips")
    cmd += [str(tga), str(dds)]
    kw = {}
    if sys.platform == "win32":
        # keep the tool's console window from flashing up per sheet
        kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(NVTT_DIR), **kw)
    if res.returncode != 0 or not dds.is_file():
        tail = (res.stderr or res.stdout or "").strip().splitlines()
        raise SpriteError(f"nvcompress failed on {tga.name}: "
                          f"{tail[-1] if tail else f'exit {res.returncode}'}")


def _digest(p: Path) -> str:
    return hashlib.sha1(p.read_bytes()).hexdigest()


def apply_convert(plan: ConvertPlan, progress=None) -> dict:
    """TGA -> DDS -> .texture, then dedup, install and clean up.

    Returns a record naming every file produced plus the faction records the
    dedup pass wants repointed, which is what the wire-up step consumes.
    """
    if plan.warnings and not plan.sets:
        raise SpriteError(plan.warnings[0])

    rec: dict = {"converted": [], "installed": [], "removed": [],
                 "duplicates": {}, "models": {}}
    total = sum(len(s.sheets) for s in plan.sets) or 1
    done = 0
    intermediates: List[Path] = []

    for s in plan.sets:
        for tga in s.sheets:
            dds = tga.with_suffix(".dds")
            tex = tga.with_suffix(".texture")
            _run_nvcompress(tga, dds, plan.request.mipmaps)
            tex.write_bytes(dds_to_texture(dds.read_bytes()))
            s.done.append(tex)
            intermediates += [tga, dds]
            rec["converted"].append(str(tex))
            done += 1
            if progress:
                progress(int(done * 90 / total), f"converted {tex.name}")

    # --- dedup: identical sheets across factions are the norm, not the exception
    if plan.request.dedup:
        by_model: Dict[str, List[SpriteSet]] = {}
        for s in plan.sets:
            by_model.setdefault(s.model, []).append(s)
        for model, group in by_model.items():
            keep: Dict[str, str] = {}        # content digest -> canonical faction
            for s in sorted(group, key=lambda x: x.faction):
                key = "|".join(sorted(_digest(p) for p in s.done))
                canon = keep.get(key)
                if canon is None:
                    keep[key] = s.faction
                elif canon != s.faction:
                    rec["duplicates"].setdefault(model, {})[s.faction] = canon
            rec["models"][model] = sorted({s.faction for s in group})

    # --- install
    if plan.install_dir:
        plan.install_dir.mkdir(parents=True, exist_ok=True)
        dupes = rec["duplicates"]
        for s in plan.sets:
            if dupes.get(s.model, {}).get(s.faction):
                continue        # a duplicate: repointed in the modeldb instead
            for p in [s.spr] + s.done:
                if p is None:
                    continue
                dest = plan.install_dir / p.name
                dest.write_bytes(p.read_bytes())
                rec["installed"].append(str(dest))
                intermediates.append(p)

    # --- cleanup
    if plan.request.cleanup:
        for p in intermediates:
            try:
                if p.is_file():
                    p.unlink()
                    rec["removed"].append(str(p))
            except OSError as e:
                log.warning("SPRITE could not remove %s: %s", p, e)

    if progress:
        progress(100, "done")
    log.info("SPRITE convert: %d texture(s), %d installed, %d duplicate record(s)",
             len(rec["converted"]), len(rec["installed"]),
             sum(len(v) for v in rec["duplicates"].values()))
    return rec


# ---------------------------------------------------------------------------
# wire-up + audit


def wire_model_edits(mod: Mod, models: Dict[str, List[str]],
                     duplicates: Optional[Dict[str, Dict[str, str]]] = None) -> List[dict]:
    """Build the modeldb edits that point each faction record at its sprite.

    ``models`` maps model name -> factions that got a sprite. ``duplicates`` maps
    model -> {faction: canonical faction}; a deduped faction points at the
    canonical faction's file rather than one of its own.

    Returned in :func:`unittransfer.edit.bmdb_request_from_dict` shape, so the
    write goes through the existing planner and inherits its backups and undo
    instead of us hand-rolling a modeldb writer.
    """
    dupes = duplicates or {}
    entries = mod.modeldb.by_name()
    out: List[dict] = []
    for model, factions in sorted(models.items()):
        entry = entries.get(model.lower())
        if entry is None:
            continue
        fp: Dict[str, dict] = {}
        for faction in factions:
            canon = dupes.get(model, {}).get(faction, faction)
            real_faction, real_model = _real_names(entry, canon)
            fp[faction] = {"sprite": sprite_line(real_faction, real_model)}
        if fp:
            out.append({"entry": model.lower(), "faction_paths": fp})
    return out


@dataclass
class SpriteAudit:
    ok: List[dict] = field(default_factory=list)
    missing: List[dict] = field(default_factory=list)     # line points at no file
    misnamed: List[dict] = field(default_factory=list)    # file exists, wrong name
    unset: List[dict] = field(default_factory=list)       # no sprite line at all
    orphans: List[str] = field(default_factory=list)      # files nothing references


def audit(mod: Mod) -> SpriteAudit:
    """Cross-check every modeldb sprite line against the files on disk.

    This is the check both tutorials describe in prose ("make sure sprite entries
    tally") and neither performs. ``misnamed`` is the interesting bucket: the
    line resolves to nothing, but the file the *generator* would have produced
    for that faction and model does exist, so it is a one-click fix.
    """
    res = SpriteAudit()
    data = mod.data
    install = data / INSTALL_REL
    referenced: set = set()

    # A real mod has tens of thousands of faction records, and stat()ing each
    # one's sprite took ~20s on Divide and Conquer. They nearly all live in the
    # same handful of folders, so list each folder once and test membership.
    listing: Dict[str, set] = {}

    def exists(rel: str) -> bool:
        p = data / rel
        key = str(p.parent).lower()
        names = listing.get(key)
        if names is None:
            try:
                names = {n.lower() for n in os.listdir(p.parent)}
            except OSError:
                names = set()
            listing[key] = names
        return p.name.lower() in names

    for name, entry in sorted(mod.modeldb.by_name().items()):
        if not name:                    # the padded first entry, not a model
            continue
        for t in entry.main_textures:
            rel = (t.sprite or "").strip().replace("\\", "/")
            row = {"model": name, "faction": t.faction, "path": rel}
            if not rel or rel == "0":
                res.unset.append(row)
                continue
            referenced.add(rel.lower())
            if exists(rel):
                res.ok.append(row)
                continue
            expect = sprite_line(t.faction, entry.name)
            row["expected"] = expect
            if exists(expect):
                res.misnamed.append(row)
            else:
                res.missing.append(row)

    if install.is_dir():
        for p in sorted(install.glob("*.spr")):
            rel = (INSTALL_REL / p.name).as_posix()
            if rel.lower() not in referenced:
                res.orphans.append(rel)
    return res


def overview(mod: Mod) -> dict:
    """Everything the Sprites workspace needs to render its first screen."""
    a = audit(mod)
    entries = mod.modeldb.by_name()
    mount_models = {m.lower() for m in mod.mounts.values() if m}
    pending = scan_export(mod)
    try:
        root = str(_med2_root(mod))
    except SpriteError:
        root = ""
    return {
        "mod": mod.name,
        "med2_root": root,
        "export_dir": str(Path(root) / EXPORT_REL) if root else "",
        "install_dir": str(mod.data / INSTALL_REL),
        "have_nvcompress": NVCOMPRESS.is_file(),
        # EOP generation needs no CFG edit and no restart per batch, so the UI
        # leads with it wherever the mod actually ships EOP
        "has_eop": bool(mod.eop_dirs),
        "cfgs": find_cfgs(mod) if root else [],
        "cfg_state": {c: _cfg_state(Path(c)) for c in (find_cfgs(mod) if root else [])},
        # a sentinel-less modeldb carries a padded first entry with no name at
        # all (see modeldb._read_entry) — it is not a model and can't be generated
        "models": [{"name": n,
                    "factions": sorted({t.faction for t in e.main_textures}),
                    "is_mount": n in mount_models}
                   for n, e in sorted(entries.items()) if n],
        "pending": [{"stem": s.stem, "model": s.model, "faction": s.faction,
                     "sheets": len(s.sheets), "textures": len(s.done),
                     "complete": s.complete}
                    for s in sorted(pending.values(), key=lambda x: x.stem)],
        # A real mod produces thousands of `missing` rows (units that simply have
        # no sprite yet) and the page only counts them, so only the rows it
        # actually renders — and the misnamed ones it can act on — travel.
        "audit": {"ok": len(a.ok),
                  "missing": len(a.missing),
                  "misnamed": a.misnamed[:AUDIT_CAP],
                  "misnamed_total": len(a.misnamed),
                  "unset": len(a.unset),
                  "orphans": len(a.orphans),
                  "orphan_sample": a.orphans[:50]},
    }
