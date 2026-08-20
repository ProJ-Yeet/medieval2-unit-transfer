"""Replace any picture the toolkit shows, wherever that picture lives.

Every screen in the UI paints its art through one of two URLs — ``/icon`` for
unit cards, info cards, ancillary pictures, faction art and the loose files the
Minor Files editor lists, and ``/building_icon`` for building art. Both take a
*question* ("the card for `merc_spearmen` in this mod") and answer with PNG
bytes, and until now that was the end of it: the page never learned which file
on disk it had just been shown, so the only picture that could be replaced was
the one the unit editor had special-cased.

This module closes that. It takes the same URL the page already built for the
``<img>``, works out:

* **what is showing** — the actual file, its size in pixels, and whether it came
  out of the mod or was borrowed from the unpacked vanilla UI
* **where a replacement goes** — one or more paths under the mod's own
  ``data/``, because a unit card has to be written into every owning faction's
  folder and borrowed vanilla art has to be written into the mod for the first
  time

…and then writes it, with the same backup + log record every other job in the
toolkit uses, so Undo puts the old picture back.

Two rules the engine imposes, and this module enforces:

* **.tga or .dds, nothing else.** A ``.png`` copied in under the right name sits
  there and never renders. A picked ``.tga``/``.dds`` is copied byte for byte;
  anything else is re-encoded as a 32-bit TGA.
* **one file per name.** If a stem already exists as ``.dds`` and the
  replacement lands as ``.tga``, the old one is removed rather than left to win
  a lookup somewhere. It is backed up first, so Undo restores it.

Resolution is *reported, never enforced*. The game does not require a card to be
80x24, but every mod's art is that size for a reason, and a 512x512 card is a
mistake far more often than it is a choice — so a mismatch comes back as a
warning the dialog shows before the write, not as a refusal.
"""
from __future__ import annotations

import shutil
import time
import urllib.parse
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .logutil import file_op, log

#: What the engine reads. A picked file with one of these extensions is copied
#: verbatim; anything else is converted (see :func:`encode`).
NATIVE_EXTS = (".tga", ".dds")

#: What the browse dialog is allowed to import from. Deliberately the same set
#: the card preview accepts, so a file that previews can always be imported.
IMPORT_EXTS = (".tga", ".dds", ".png", ".jpg", ".jpeg", ".bmp", ".gif")

#: The filter string for the native file dialog, kept here so every caller in
#: the UI offers the same list.
IMPORT_FILTER = ("Images (*.tga;*.dds;*.png;*.jpg;*.jpeg;*.bmp)|"
                 "*.tga;*.dds;*.png;*.jpg;*.jpeg;*.bmp|All files (*.*)|*.*")

#: Bigger than any real piece of M2TW UI art by a wide margin; a guard against
#: pointing the importer at a 400 MB scan rather than a card.
MAX_IMPORT_BYTES = 64 * 1024 * 1024


# ---------------------------------------------------------------- probing ----
def probe(path: Optional[Path]) -> Dict:
    """What one image file *is*: size in pixels, format, bytes on disk.

    Never raises. A file that Pillow cannot open comes back with
    ``ok: False`` and a readable reason, because "your .dds is a format Pillow
    does not decode" is something the dialog should say rather than something
    that should 500 a request.
    """
    out: Dict = {"ok": False, "path": "", "name": "", "width": 0, "height": 0,
                 "format": "", "mode": "", "bytes": 0, "error": ""}
    if path is None:
        out["error"] = "there is no file here yet"
        return out
    p = Path(path)
    out["path"], out["name"] = str(p), p.name
    try:
        out["bytes"] = p.stat().st_size
    except OSError as exc:
        out["error"] = f"{p.name}: {exc.strerror or exc}"
        return out
    try:
        from PIL import Image
        with Image.open(p) as im:
            out["width"], out["height"] = im.size
            out["format"] = (im.format or "").upper()
            out["mode"] = im.mode
        out["ok"] = True
    except Exception as exc:                   # a corrupt or exotic file
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def encode(src: Path, ext: str) -> Optional[bytes]:
    """The bytes to write for ``src`` at a target extension, or ``None`` to copy.

    ``None`` means "the picked file is already in a format the engine reads and
    keeps its own extension" — copy it and keep its mtime, rather than paying a
    decode + re-encode that can only lose something (a .dds's mipmaps, a .tga's
    exact channel layout).
    """
    if ext.lower() in NATIVE_EXTS and src.suffix.lower() == ext.lower():
        return None
    from PIL import Image
    with Image.open(src) as im:
        buf = BytesIO()
        im.convert("RGBA").save(buf, format="TGA")
        return buf.getvalue()


# --------------------------------------------------------------- locating ----
def parse_url(url: str) -> Dict[str, str]:
    """Pull the query off one of the two image URLs the page builds.

    The page hands back the *same* string it put in the ``<img src>``, which is
    the only thing it reliably knows about a picture it did not resolve itself.
    Anything that is not one of the two known paths is refused here rather than
    being allowed to reach a file lookup.
    """
    u = urllib.parse.urlparse((url or "").strip())
    path = u.path or ""
    # `http://elsewhere/icon?…` parses with the right PATH, so the host has to be
    # checked as well: these URLs are same-origin by construction, and one that
    # is not did not come from a picture this tool painted.
    if u.scheme or u.netloc or path not in ("/icon", "/building_icon"):
        raise ValueError("that is not a picture this tool serves")
    q = urllib.parse.parse_qs(u.query)
    out = {k: (v[0] if v else "") for k, v in q.items()}
    out["_path"] = path
    return out


def _rel_under_data(mod, path: Optional[Path]) -> str:
    """``path`` as a mod-relative posix path, or ``""`` if it is outside data/."""
    if path is None:
        return ""
    try:
        return Path(path).resolve().relative_to(Path(mod.data).resolve()).as_posix()
    except (ValueError, OSError):
        return ""


def _safe_rel(mod, raw: str) -> str:
    """A caller-supplied rel, refused unless it stays inside the mod's data/."""
    rel = (raw or "").strip().replace("\\", "/").strip("/")
    if not rel or ".." in rel.split("/"):
        return ""
    try:
        target = (Path(mod.data) / rel).resolve()
        target.relative_to(Path(mod.data).resolve())
    except (ValueError, OSError):
        return ""
    return rel


def _swap_ext(rel: str, ext: str) -> str:
    return rel.rsplit(".", 1)[0] + ext if "." in rel.rsplit("/", 1)[-1] else rel + ext


def _unit_targets(mod, unit, kind: str) -> Tuple[List[str], str]:
    """Every faction folder that holds this unit's card, and a note about them.

    The game looks a card up under the *player's* faction folder, so one unit's
    card is routinely the same picture copied into ten of them. Replacing the
    one the preview happened to resolve would leave the other nine showing the
    old art to anyone playing those factions, which is exactly the bug the
    editor's card-variant list exists to make visible — so a replacement goes to
    all of them.
    """
    from .edit import _unit_icon_files
    on_disk = [rel for _abs, rel, k in _unit_icon_files(mod, unit.dictionary)
               if k == kind]
    if on_disk:
        note = (f"{len(on_disk)} faction folder(s) hold this {kind}; all of them "
                f"get the new picture") if len(on_disk) > 1 else ""
        return on_disk, note
    # Nothing on disk: fall back to where an import WOULD land, which is what the
    # unit editor computes from ownership. Same fan-out, same merc fallback.
    from .transfer import MERC_CARD_DIR, MERC_INFO_DIR
    base, merc, stem = (("ui/units", MERC_CARD_DIR, f"#{unit.dictionary}")
                        if kind == "card"
                        else ("ui/unit_info", MERC_INFO_DIR,
                              f"{unit.dictionary}_info"))
    own = [f for f in (x.lower() for x in unit.ownership) if f != "slave"] \
        or [x.lower() for x in unit.ownership]
    folders = list(dict.fromkeys(own + [merc]))
    if not folders:
        return [], ""
    return ([f"{base}/{f}/{stem}.tga" for f in folders],
            f"this unit has no {kind} on disk yet, so one is created in "
            f"{len(folders)} faction folder(s)")


def locate(mod, url: str, vanilla_root=None) -> Dict:
    """What picture a page URL is showing, and where a replacement would go.

    The answer is deliberately the same shape for all five kinds of picture, so
    the page has one dialog rather than five::

        kind      which sort of art this is
        label     what to call it in the dialog
        showing   the file the preview came from ("" if there is none)
        source    "mod" | "vanilla" | ""  — borrowed art is worth saying
        targets   the mod-relative path(s) a replacement is written to
        current   :func:`probe` of `showing`

    ``source: "vanilla"`` matters: the mod does not own that file, so replacing
    it *creates* the mod's own copy rather than overwriting anything. Undo then
    deletes the new file rather than restoring an old one, which is right.
    """
    from . import ancillaries, buildings, factions
    q = parse_url(url)
    out: Dict = {"ok": False, "kind": "", "label": "", "showing": "",
                 "source": "", "targets": [], "note": "", "error": "",
                 "current": probe(None)}

    if q["_path"] == "/building_icon":
        culture, level = q.get("culture", ""), q.get("level", "")
        size = q.get("kind", "small")
        if not culture or not level:
            out["error"] = "that building icon names no culture or level"
            return out
        src, source = buildings.find_icon(mod, culture, level, size, vanilla_root)
        stem = buildings.icon_stem(culture, level, size)
        out.update(kind="building", source=source,
                   label=f"the {'large' if size != 'small' else 'small'} icon for "
                         f"{level} ({culture})",
                   showing=str(src) if src else "",
                   targets=[f"ui/{culture}/buildings/{stem}.tga"])
        own = _rel_under_data(mod, src) if source == "mod" else ""
        if own:
            out["targets"] = [own]
        elif source:
            out["note"] = ("this mod has no icon of its own here — it is showing "
                           "the game's, and saving writes the mod's first copy")
        out["current"] = probe(src)
        out["ok"] = bool(out["targets"][0])
        return out

    kind = q.get("kind", "card")
    if kind == "ancillary":
        name = (q.get("image") or "").strip().replace("\\", "/").split("/")[-1]
        if not name:
            out["error"] = "that ancillary names no image"
            return out
        src = ancillaries.image_path(mod, name)
        inside = _rel_under_data(mod, src)
        out.update(kind="ancillary", label=f"the picture for {name}",
                   showing=str(src) if src else "",
                   source="mod" if inside else ("vanilla" if src else ""),
                   targets=[inside or f"{ancillaries.IMAGE_DIR}/{name}"],
                   current=probe(src))
        if src is not None and not inside:
            out["note"] = ("this picture comes from the game's own ancillary art — "
                           "saving writes the mod's first copy")
        out["ok"] = True
        return out

    if kind in ("faction", "modfile"):
        rel = _safe_rel(mod, q.get("rel", ""))
        if not rel:
            out["error"] = "that path is not inside the mod"
            return out
        src = Path(mod.data) / rel
        out.update(kind=kind, label=rel, targets=[rel],
                   showing=str(src) if src.is_file() else "",
                   source="mod" if src.is_file() else "",
                   current=probe(src if src.is_file() else None))
        out["ok"] = True
        return out

    # …which leaves the unit's own two cards
    kind = "info" if kind == "info" else "card"
    utype = q.get("type", "")
    unit = mod.edu.by_type().get(utype)
    if unit is None:
        out["error"] = f"no unit called {utype!r} in {mod.name}"
        return out
    src = mod.find_unit_info(unit) if kind == "info" else mod.find_unit_card(unit)
    targets, note = _unit_targets(mod, unit, kind)
    out.update(kind=kind, note=note, targets=targets,
               label=f"the {'info card' if kind == 'info' else 'unit card'} for "
                     f"{unit.dictionary}",
               showing=str(src) if src else "",
               source="mod" if src else "", current=probe(src))
    if not targets:
        out["error"] = (f"'{utype}' has no ownership, so there is no faction "
                        f"folder to put a {kind} in — set ownership first")
        return out
    out["ok"] = True
    return out


def reveal_target(mod, url: str, vanilla_root=None) -> Dict:
    """What "Open file location" should point the file manager at.

    Three answers, in the order they are worth having:

    * the file that is actually showing, wherever it lives — including the
      unpacked vanilla UI, because "which file am I looking at" is the question,
      and the answer being outside the mod is itself the interesting part
    * the folder a replacement would land in, when there is no file yet
    * an error, when even that folder does not exist

    The path is never taken from the caller: it comes back out of
    :func:`locate`, which resolves it the same way the picture was served. So
    this cannot be aimed at a file the tool would not already have shown.
    """
    where = locate(mod, url, vanilla_root)
    if not where["ok"] and not where["showing"]:
        return {"ok": False, "error": where["error"] or "there is no picture here"}
    if where["showing"] and Path(where["showing"]).is_file():
        return {"ok": True, "path": where["showing"],
                "outside": not bool(_rel_under_data(mod, Path(where["showing"]))),
                "source": where["source"]}
    folder = (Path(mod.data) / where["targets"][0]).parent if where["targets"] else None
    if folder is not None and folder.is_dir():
        return {"ok": True, "path": str(folder), "outside": False,
                "source": "", "folder_only": True}
    return {"ok": False,
            "error": "there is no file here yet, and no folder for one either — "
                     "import a picture and it is created"}


# ------------------------------------------------------------- the report ----
def plan(mod, url: str, src_path: str, vanilla_root=None) -> Dict:
    """Everything the confirm dialog needs: before, after, and what is off.

    Split from :func:`apply` so the user sees the warnings *before* the write
    rather than in a toast afterwards, and so the same numbers can be shown
    while the picked file is still only a preview.
    """
    out = locate(mod, url, vanilla_root)
    out["incoming"] = probe(None)
    out["warnings"] = []
    out["replaces"] = []
    if not out["ok"]:
        return out
    src = Path(src_path or "")
    if not src_path:
        return out
    if not src.is_file():
        out["ok"] = False
        out["error"] = f"there is no file at {src_path}"
        return out
    if src.suffix.lower() not in IMPORT_EXTS:
        out["ok"] = False
        out["error"] = (f"{src.suffix or 'that file'} is not an image this tool "
                        f"reads — pick a {', '.join(IMPORT_EXTS)}")
        return out
    try:
        if src.stat().st_size > MAX_IMPORT_BYTES:
            out["ok"] = False
            out["error"] = "that file is far too big to be a piece of UI art"
            return out
    except OSError as exc:
        out["ok"] = False
        out["error"] = str(exc)
        return out

    inc = probe(src)
    out["incoming"] = inc
    native = src.suffix.lower() in NATIVE_EXTS
    ext = src.suffix.lower() if native else ".tga"
    out["targets"] = [_swap_ext(rel, ext) for rel in out["targets"]]
    out["converted"] = not native
    if not native:
        out["warnings"].append(
            f"a {src.suffix} cannot be read by the game, so it is saved as a "
            f"32-bit .tga under the name the engine looks for")
    if not inc["ok"]:
        out["ok"] = False
        out["error"] = inc["error"] or "that image could not be read"
        return out

    # the resolution check the whole feature was asked for
    cur = out["current"]
    if cur["ok"] and (cur["width"], cur["height"]) != (inc["width"], inc["height"]):
        out["warnings"].append(
            f"the picture on disk is {cur['width']}x{cur['height']} and this one "
            f"is {inc['width']}x{inc['height']} — the game does not rescale UI "
            f"art, so it will be drawn stretched or cropped into the same box")
    elif not cur["ok"] and cur["error"] and out["showing"]:
        out["warnings"].append(
            f"the size of the picture already there could not be read "
            f"({cur['error']}), so this one could not be checked against it")

    # what actually happens on disk, path by path — including the siblings that
    # have to go so two files cannot answer to one name
    for rel in out["targets"]:
        target = Path(mod.data) / rel
        row = {"rel": rel, "exists": target.is_file(), "drops": []}
        for other in NATIVE_EXTS:
            if other == ext:
                continue
            sib = Path(mod.data) / _swap_ext(rel, other)
            if sib.is_file():
                row["drops"].append(_swap_ext(rel, other))
        out["replaces"].append(row)
    drops = [d for row in out["replaces"] for d in row["drops"]]
    if drops:
        out["warnings"].append(
            f"{len(drops)} file(s) with the same name but a {NATIVE_EXTS[0]}/"
            f"{NATIVE_EXTS[1]} swap are removed so only one answers to the name "
            f"(Undo puts them back)")
    return out


# -------------------------------------------------------------- the write ----
def apply(mod, url: str, src_path: str, vanilla_root=None) -> Dict:
    """Write the replacement, with the backups and log record Undo needs.

    Re-plans rather than trusting a plan handed back by the page: the file could
    have moved between the dialog opening and the button being clicked, and the
    page is not where a write should be authorised from anyway.
    """
    from . import config
    p = plan(mod, url, src_path, vanilla_root)
    if not p["ok"]:
        raise ValueError(p["error"] or "that picture cannot be replaced")
    if not src_path:
        raise ValueError("no image was picked")
    src = Path(src_path)
    ext = Path(p["targets"][0]).suffix.lower()
    data = encode(src, ext)

    tid = config.new_transfer_id()
    backup_root = config.backup_root_for(tid)
    manifest: Dict[str, List[str]] = {"backed_up": [], "created": []}

    def keep(rel: str) -> Path:
        target = Path(mod.data) / rel
        if target.exists():
            bpath = backup_root / "data" / rel
            bpath.parent.mkdir(parents=True, exist_ok=True)
            if not bpath.exists():
                shutil.copy2(target, bpath)
            manifest["backed_up"].append(rel)
            file_op("BACKUP", target, f"-> {bpath}")
        else:
            manifest["created"].append(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    written: List[str] = []
    dropped: List[str] = []
    for row in p["replaces"]:
        target = keep(row["rel"])
        if data is None:
            shutil.copy2(src, target)
            file_op("COPY", target, f"from {src}")
        else:
            target.write_bytes(data)
            file_op("CONVERT", target, f"{src.suffix} -> {ext} from {src}")
        written.append(row["rel"])
        for rel in row["drops"]:
            old = keep(rel)
            try:
                old.unlink()
                manifest.setdefault("deleted", []).append(rel)
                dropped.append(rel)
                file_op("DELETE", old, "same name, other extension — Undo puts it back")
            except OSError as exc:
                p["warnings"].append(f"could not remove data/{rel}: {exc}")

    summary = (f"{p['label']}: replaced with {src.name} in {len(written)} file(s)"
               + (f", {len(dropped)} removed" if dropped else ""))
    rec = {
        "id": tid,
        "when": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "image",
        "action": "replace",
        "source": mod.name, "source_root": str(mod.root),
        "dest": mod.name, "dest_root": str(mod.root),
        "unit_type": p["targets"][0], "resolved_type": p["targets"][0],
        "options": {}, "applied": True, "undone": False, "note": "",
        "summary": summary, "warnings": list(p["warnings"]),
        "manifest": manifest, "backup_root": str(backup_root),
    }
    config.append_log(rec)
    log.info("IMAGE  replace %s in %s — %d file(s), id=%s",
             p["targets"][0], mod.name, len(written), tid)
    return {"ok": True, "id": tid, "written": written, "dropped": dropped,
            "warnings": p["warnings"], "summary": summary, "record": rec,
            "converted": p.get("converted", False),
            "incoming": p["incoming"], "label": p["label"]}
