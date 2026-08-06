"""Pack an unpacked vanilla UI folder into a small, committable art pack.

Buildings mode falls back to vanilla building art for the icons a mod doesn't
ship. Straight out of the game's .pack files that art is ~305 MB of uncompressed
TGA — too big to commit, and over half of it is the same picture saved under
several names (18 buildings share one "constructed" harbour picture, and so on).

This turns such a folder into::

    vanilla_ui/
      manifest.json        {"entries": {"<culture>/<stem>": "ab/abcd….webp", …}}
      art/ab/abcd….webp    one file per DISTINCT picture, lossless WebP

which is about 6x smaller and holds no duplicate bytes at all. Lossless, so the
art is bit-identical to the TGA once decoded — these are reference pictures, and
a lossy pass would be visible on the flat colour the icons are full of.

    python tools/pack_vanilla_ui.py unpackaded_vanilla_ui vanilla_ui

Reading the result is :class:`unittransfer.buildings.VanillaUi`, which also still
reads a raw unpacked folder — nobody has to run this to use their own copy.
"""
from __future__ import annotations

import hashlib
import io
import json
import shutil
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer.buildings import ICON_EXTS, MANIFEST_NAME, PACK_ART_DIR   # noqa: E402

#: Only building art is used by the tool, so only building art is packed.
WANTED_SUBDIR = "buildings"


#: WebP effort level. Measured on this art: 4 and 6 land within 0.5% of each
#: other on size, but 6 costs ~2s an image against ~0.16s — over an hour of extra
#: work across 1 200 pictures to save a couple of hundred KB. So: 4.
WEBP_METHOD = 4


def _webp(path: Path) -> bytes:
    with Image.open(path) as im:
        im.load()
        if im.mode != "RGBA":
            im = im.convert("RGBA")
        buf = io.BytesIO()
        im.save(buf, "WEBP", lossless=True, quality=100, method=WEBP_METHOD)
        return buf.getvalue()


def pack(src: Path, dest: Path) -> dict:
    art = dest / PACK_ART_DIR
    art.mkdir(parents=True, exist_ok=True)
    entries: dict[str, str] = {}
    seen: dict[str, str] = {}          # sha1 of the WebP -> its relative path
    stats = {"read": 0, "written": 0, "src_bytes": 0, "out_bytes": 0, "skipped": 0}

    sources = sorted(p for p in src.rglob("*")
                     if p.is_file() and p.suffix.lower() in ICON_EXTS
                     and p.parent.name.lower() == WANTED_SUBDIR)
    for i, p in enumerate(sources, 1):
        culture = p.parent.parent.name
        key = f"{culture}/{p.stem}"
        stats["read"] += 1
        stats["src_bytes"] += p.stat().st_size
        try:
            data = _webp(p)
        except Exception as exc:                      # a corrupt TGA is not fatal
            print(f"  ! skipped {p.name}: {exc}")
            stats["skipped"] += 1
            continue
        digest = hashlib.sha1(data).hexdigest()
        rel = seen.get(digest)
        if rel is None:
            rel = f"{digest[:2]}/{digest}.webp"
            target = art / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            seen[digest] = rel
            stats["written"] += 1
            stats["out_bytes"] += len(data)
        entries[key] = rel
        if i % 250 == 0:
            print(f"  {i}/{len(sources)}…")

    manifest = {"version": 1, "kind": "building-art", "entries": entries}
    (dest / MANIFEST_NAME).write_text(json.dumps(manifest, indent=0, sort_keys=True),
                                      encoding="utf-8")
    return stats


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    src, dest = Path(argv[0]), Path(argv[1])
    if not src.is_dir():
        print(f"no such folder: {src}")
        return 1
    if dest.exists() and any(dest.iterdir()):
        print(f"clearing {dest}")
        shutil.rmtree(dest / PACK_ART_DIR, ignore_errors=True)
    print(f"packing {src} -> {dest}")
    s = pack(src, dest)
    print(f"\n  read     {s['read']} files, {s['src_bytes'] / 1e6:.1f} MB")
    print(f"  written  {s['written']} distinct pictures, {s['out_bytes'] / 1e6:.1f} MB")
    print(f"  dropped  {s['read'] - s['written']} duplicates"
          + (f", {s['skipped']} unreadable" if s["skipped"] else ""))
    if s["src_bytes"]:
        print(f"  ratio    {s['out_bytes'] / s['src_bytes'] * 100:.1f}% of the original")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
