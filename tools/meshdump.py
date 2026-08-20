"""Print what a Medieval II model file contains.

This is the tool the ``.mesh`` format was reverse-engineered with, kept because
it is also the answer to "the viewer will not open this file, why". It reads a
model and prints its groups, its vertex pool and its bones — and with ``--raw``
it walks the bytes instead, which is what you want when a file will NOT decode.

    python tools/meshdump.py <file.mesh> [more files...]
    python tools/meshdump.py --raw <file.mesh>       # byte-level walk
    python tools/meshdump.py --sweep <folder>        # decode every .mesh under it

The sweep is how a change to unittransfer/mesh.py gets checked against a whole
mod in one go: it reports how many files decoded, and the first failure of each
distinct kind rather than thousands of near-identical lines.
"""
import collections
import os
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from unittransfer import mesh


def show(path: str) -> int:
    try:
        m = mesh.read_mesh(path)
    except mesh.MeshError as e:
        print(f"{Path(path).name}: {e}")
        return 1
    lo, hi = m.bounds()
    print(f"\n{Path(path).name}  ({os.path.getsize(path):,} bytes)")
    print(f"  {m.vertices:,} vertices, {m.triangles:,} triangles, "
          f"{len(m.groups)} groups, {len(m.bones)} bones")
    print(f"  box   {tuple(round(v, 3) for v in lo)} .. {tuple(round(v, 3) for v in hi)}")
    print(f"  lod   {m.lod_name or '(unnamed)'}   trailer {m.trailer} bytes not decoded")
    print(f"  has   positions{'  normals' if m.normals else ''}"
          f"{'  uvs' if m.uvs else ''}")
    width = max((len(g.name) for g in m.groups), default=4)
    for i, g in enumerate(m.groups):
        print(f"    {i:3d}  {g.name:<{width}}  {g.texture_group:<26}  "
              f"{g.triangles:6,} tris  flag {g.flag}")
    if m.bones:
        print("  bones " + ", ".join(m.bones))
    for note in m.notes:
        print(f"  note  {note}")
    return 0


def raw(path: str) -> int:
    """Walk the bytes without trusting the parser — for a file that will not open."""
    d = Path(path).read_bytes()
    print(f"{Path(path).name}  {len(d):,} bytes   kind={mesh.probe_bytes(d) or 'unknown'}")
    print("  head " + d[:48].hex(" "))
    names = [(m.start(), m.group()) for m in re.finditer(rb"[ -~]{4,}", d)]
    print(f"  {len(names)} printable runs; first 20:")
    for off, s in names[:20]:
        print(f"    {off:#08x}  {s[:60]!r}")
    print("  uint32 words that could be counts, with what follows:")
    for off in range(0, min(len(d) - 8, 4096), 2):
        n = struct.unpack_from("<I", d, off)[0]
        if 8 <= n <= 100000 and off + 4 + n * 6 <= len(d):
            print(f"    {off:#08x}  {n:,}  -> {d[off + 4:off + 16].hex(' ')}")
    return 0


def sweep(folder: str) -> int:
    files = []
    for dirpath, _, names in os.walk(folder):
        files += [os.path.join(dirpath, n) for n in names if n.lower().endswith(".mesh")]
    files.sort()
    if not files:
        print(f"no .mesh files under {folder}")
        return 1
    ok = 0
    fails = collections.Counter()
    first = {}
    for f in files:
        try:
            mesh.read_mesh(f)
            ok += 1
        except mesh.MeshError as e:
            key = re.sub(r"\d+", "N", str(e).split(": ", 1)[-1])[:70]
            fails[key] += 1
            first.setdefault(key, f)
        except Exception as e:                       # a crash is worth seeing whole
            key = f"{type(e).__name__}: {e}"[:70]
            fails[key] += 1
            first.setdefault(key, f)
    print(f"{folder}\n  {len(files):,} files, {ok:,} decoded, {sum(fails.values()):,} failed")
    for key, n in fails.most_common():
        print(f"    {n:5,}  {key}\n           first: {first[key]}")
    return 1 if fails else 0


def main(argv) -> int:
    if not argv:
        print(__doc__)
        return 2
    if argv[0] == "--raw":
        return max((raw(f) for f in argv[1:]), default=2)
    if argv[0] == "--sweep":
        return max((sweep(f) for f in argv[1:]), default=2)
    return max((show(f) for f in argv), default=2)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
