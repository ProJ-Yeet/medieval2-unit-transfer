"""Decode M2TW unit icons (.tga / .dds) to PNG bytes for the web UI.

Uses Pillow. Results are cached on disk under a scratch dir keyed by the source
path + mtime, so repeated requests are cheap. Falls back to a 1x1 transparent
PNG if a file can't be decoded (never raises into the request handler).
"""
from __future__ import annotations

import hashlib
import io
import os
import time
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw

from .logutil import log

#: Where a user-supplied placeholder is looked for (kept out of the mod folders,
#: like everything else this tool writes).
_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"

# 1x1 transparent PNG
_BLANK_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00"
    b"\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


class IconCache:
    def __init__(self, cache_dir: str | Path):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _key(self, src: Path, max_side: int = 0) -> Path:
        try:
            mtime = src.stat().st_mtime_ns
        except OSError:
            mtime = 0
        # `max_side` is part of the key: the same file served whole and served
        # shrunk are two different answers, and one must not be handed out for
        # the other.
        h = hashlib.sha1(f"{src}|{mtime}|{max_side}".encode("utf-8")).hexdigest()[:20]
        return self.cache_dir / f"{h}.png"

    def is_cached(self, src: Optional[Path]) -> bool:
        """True if this icon is already decoded on disk (no conversion needed).

        Lets the startup prewarm tell "converted" from "already cached" in its
        progress line without paying for a decode to find out.
        """
        if src is None:
            return False
        src = Path(src)
        return src.exists() and self._key(src).exists()

    def placeholder_png(self, width: int, height: int) -> bytes:
        """A neutral "no art here" tile, cached per size.

        Mods ship only the building icons they changed and let the game fall back
        to vanilla art, so a mod folder alone leaves most buildings with nothing
        to show. A drawn tile says that plainly; a blank PNG just looks broken.
        A ``config/placeholder_building.png`` next to the settings, if the user
        drops one there, is used instead at whatever size it already is.
        """
        custom = _CONFIG_DIR / "placeholder_building.png"
        if custom.exists():
            return self.png_bytes(custom)
        cached = self.cache_dir / f"placeholder-{width}x{height}.png"
        hit = _read_cached(cached)
        if hit is not None:
            return hit
        data = _draw_placeholder(width, height)
        try:
            cached.write_bytes(data)
        except OSError:
            pass
        return data

    def png_bytes(self, src: Optional[Path], max_side: int = 0) -> bytes:
        """This file as PNG bytes, cached on disk.

        ``max_side`` shrinks anything bigger than it, keeping the aspect ratio.
        Unit art is small and passes 0; a model's texture is up to 2048 square
        and the viewer draws it a few hundred pixels tall, so it asks for less.
        """
        if src is None or not Path(src).exists():
            # Not a fault: mods ship the art they changed and leave the rest to
            # the game's own files. The caller says which unit it was asking
            # about — this layer only ever sees a path, and "(no path)" tells
            # nobody anything.
            if src is not None:
                log.debug("ICON   listed but missing on disk: %s", src)
            return _BLANK_PNG
        src = Path(src)
        cached = self._key(src, max_side)
        hit = _read_cached(cached)
        if hit is not None:
            return hit
        started = time.perf_counter()
        data = _decode_to_png(src, max_side)
        log.debug("ICON   converted %s -> %d bytes of PNG in %.0f ms", src, len(data),
                  (time.perf_counter() - started) * 1000)
        # Write atomically: concurrent requests for the same uncached icon must
        # never leave a torn/partial file that a later reader would serve.
        try:
            tmp = cached.with_name(f"{cached.stem}.{os.getpid()}.{id(data) & 0xffffff:x}.tmp")
            tmp.write_bytes(data)
            os.replace(tmp, cached)
        except OSError:
            pass
        return data


#: First eight bytes of every PNG. A cache entry that doesn't start with them is
#: not a PNG we wrote, so it is a miss rather than something to serve.
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _read_cached(path: Path) -> Optional[bytes]:
    """Bytes of a cache entry, or None when it can't be used.

    Never raises, and never returns something that isn't a PNG. A cache lives on
    a real filesystem in normal use, but it can end up somewhere a read *fails*:
    a cloud-synced folder hands back ``OSError: [Errno 22]`` for a dehydrated
    placeholder, and a file that is still syncing can read short. Both used to
    surface as a black unit card — the icon handler catches the error and paints
    a blank, so the grid filled up with nothing and looked like a failed
    conversion. Treating it as a miss re-decodes from the mod's own TGA instead,
    which is the one copy that is always there.
    """
    try:
        if not path.exists():
            return None
        data = path.read_bytes()
    except OSError:
        return None
    return data if data[:8] == _PNG_MAGIC else None


def _draw_placeholder(width: int, height: int) -> bytes:
    """A dark slab with a dashed border and a centred ``?``, in the UI's palette."""
    width, height = max(8, min(width, 1024)), max(8, min(height, 1024))
    im = Image.new("RGBA", (width, height), (26, 30, 38, 255))
    d = ImageDraw.Draw(im)
    edge = (72, 82, 98, 255)
    step = max(4, width // 12)
    for x in range(0, width, step * 2):          # dashed top + bottom
        d.line([(x, 0), (min(x + step, width - 1), 0)], fill=edge)
        d.line([(x, height - 1), (min(x + step, width - 1), height - 1)], fill=edge)
    for y in range(0, height, step * 2):         # dashed left + right
        d.line([(0, y), (0, min(y + step, height - 1))], fill=edge)
        d.line([(width - 1, y), (width - 1, min(y + step, height - 1))], fill=edge)
    # A little roofed box rather than a "?": drawn from lines, so it stays crisp
    # at both the 78x62 browser icon and the 300x245 constructed picture, where a
    # bitmap-font glyph would be a speck.
    glyph = (150, 165, 190, 255)
    s = min(width, height) * 0.42
    cx, cy = width / 2, height / 2
    left, right = cx - s / 2, cx + s / 2
    eaves, base, apex = cy - s * 0.10, cy + s / 2, cy - s / 2
    d.line([(left, eaves), (left, base), (right, base), (right, eaves)],
           fill=glyph, width=max(1, int(s / 16)))
    d.line([(left - s * 0.12, eaves), (cx, apex), (right + s * 0.12, eaves)],
           fill=glyph, width=max(1, int(s / 16)))
    door = s * 0.16
    d.rectangle([cx - door, base - s * 0.34, cx + door, base], outline=glyph,
                width=max(1, int(s / 22)))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def _openable(src: Path):
    """What to hand Pillow for this file.

    A model's texture is a ``.texture``: the game's own 48-byte header with a
    plain DDS behind it, which Pillow cannot open by itself. ``sprites`` already
    owns that container both ways, so unwrapping is one call and every caller of
    this module can render one.
    """
    if src.suffix.lower() != ".texture":
        return src
    from . import sprites
    return io.BytesIO(sprites.texture_to_dds(src.read_bytes()))


def _decode_to_png(src: Path, max_side: int = 0) -> bytes:
    try:
        with Image.open(_openable(src)) as im:
            im.load()
            if im.mode != "RGBA":
                im = im.convert("RGBA")
            if max_side and max(im.size) > max_side:
                scale = max_side / max(im.size)
                im = im.resize((max(1, round(im.width * scale)),
                                max(1, round(im.height * scale))), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, "PNG")
            return buf.getvalue()
    except Exception:
        return _BLANK_PNG
