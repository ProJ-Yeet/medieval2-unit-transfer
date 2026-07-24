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

from PIL import Image

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
