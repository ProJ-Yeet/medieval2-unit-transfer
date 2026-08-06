"""Decode M2TW unit icons (.tga / .dds) to PNG bytes for the web UI.

Uses Pillow. Results are cached on disk under a scratch dir keyed by the source
path + mtime, so repeated requests are cheap. Falls back to a 1x1 transparent
PNG if a file can't be decoded (never raises into the request handler).
"""
from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw

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

    def _key(self, src: Path) -> Path:
        try:
            mtime = src.stat().st_mtime_ns
        except OSError:
            mtime = 0
        h = hashlib.sha1(f"{src}|{mtime}".encode("utf-8")).hexdigest()[:20]
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
        if cached.exists():
            return cached.read_bytes()
        data = _draw_placeholder(width, height)
        try:
            cached.write_bytes(data)
        except OSError:
            pass
        return data

    def png_bytes(self, src: Optional[Path]) -> bytes:
        if src is None or not Path(src).exists():
            return _BLANK_PNG
        src = Path(src)
        cached = self._key(src)
        if cached.exists():
            return cached.read_bytes()
        data = _decode_to_png(src)
        # Write atomically: concurrent requests for the same uncached icon must
        # never leave a torn/partial file that a later reader would serve.
        try:
            tmp = cached.with_name(f"{cached.stem}.{os.getpid()}.{id(data) & 0xffffff:x}.tmp")
            tmp.write_bytes(data)
            os.replace(tmp, cached)
        except OSError:
            pass
        return data


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


def _decode_to_png(src: Path) -> bytes:
    try:
        with Image.open(src) as im:
            im.load()
            if im.mode != "RGBA":
                im = im.convert("RGBA")
            buf = io.BytesIO()
            im.save(buf, "PNG")
            return buf.getvalue()
    except Exception:
        return _BLANK_PNG
