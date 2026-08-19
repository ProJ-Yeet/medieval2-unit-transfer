"""Index the TWCenter tutorial archive so a format question has one place to look.

    python tools/twc_index.py              # rebuild the index
    python tools/twc_index.py --check      # report what would change, write nothing

`Reference/TWCenter/` is 3.4 GB of saved tutorials, guides and tool dumps — the
accumulated knowledge of how Medieval II's files actually work, in 300-odd
documents whose only organising principle is the filename someone saved them
under. This walks it once and writes two files next to it:

  INDEX.json  every document as a record — path, title, tags, the game files it
              mentions (with how often), a one-line summary, and which roadmap
              phases it bears on
  INDEX.md    the same thing as a table you can read or grep

Both are committed (the archive itself is not — see .gitignore); regenerate
after adding tutorials.

Finding the tutorial for a format is then a grep:

    grep -i "descr_mount" Reference/TWCenter/INDEX.md
    grep -i "phase:6" Reference/TWCenter/INDEX.md

Extraction is best-effort by design. A scanned PDF with no text layer yields
nothing to search, so it is tagged `needs-manual-read` and listed in its own
section rather than being silently indexed as empty — the archive holds a few,
and a phase that needs one has to open it by hand.

Dev-only. Nothing here ships in a release; the PDF readers are not runtime
dependencies of the toolkit.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import unicodedata
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARCHIVE = ROOT / "Reference" / "TWCenter"
OUT_JSON = ARCHIVE / "INDEX.json"
OUT_MD = ARCHIVE / "INDEX.md"

#: Extensions worth reading. Everything else in the archive (textures, meshes,
#: .exe tools, video) is an asset, not a document — it is counted per folder as
#: context but never given an entry of its own.
DOC_EXTS = {".pdf", ".txt", ".docx", ".md", ".htm", ".html", ".xlsx"}

#: A saved web page drags its whole asset folder along. The page itself is the
#: document; the scripts and images beside it are not.
SKIP_DIR_MARKERS = ("_files",)

#: Below this many characters of extracted text, a document is assumed to be a
#: scan or an extraction failure rather than a short tutorial.
MIN_TEXT = 200

#: How much text to read per document. Tags and game-file mentions saturate long
#: before this; reading whole 200-page PDFs would only cost time.
MAX_TEXT = 60_000


# ---------------------------------------------------------------------------
# text extraction
# ---------------------------------------------------------------------------
def _pdf_text(path: Path) -> str:
    """Text of a PDF, via PyMuPDF if present (faster, better) else pypdf."""
    try:
        import fitz                                    # PyMuPDF
        out = []
        with fitz.open(path) as doc:
            for page in doc:
                out.append(page.get_text())
                if sum(len(s) for s in out) > MAX_TEXT:
                    break
        return "".join(out)
    except ImportError:
        pass
    except Exception:
        return ""
    try:
        from pypdf import PdfReader
        out = []
        reader = PdfReader(str(path))
        for page in reader.pages:
            out.append(page.extract_text() or "")
            if sum(len(s) for s in out) > MAX_TEXT:
                break
        return "".join(out)
    except Exception:
        return ""


def _docx_text(path: Path) -> str:
    """Body text of a .docx without python-docx: it is XML inside a zip."""
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8", "replace")
    except Exception:
        return ""
    xml = re.sub(r"</w:p>", "\n", xml)
    return _strip_tags(xml)


def _xlsx_text(path: Path) -> str:
    """Cell values of a spreadsheet — the Docudemons field references are xlsx."""
    try:
        import openpyxl
    except ImportError:
        return ""
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception:
        return ""
    out = []
    try:
        for ws in wb.worksheets:
            out.append(f"[sheet] {ws.title}")
            for row in ws.iter_rows(values_only=True):
                cells = [str(c) for c in row if c is not None]
                if cells:
                    out.append(" ".join(cells))
                if sum(len(s) for s in out) > MAX_TEXT:
                    return "\n".join(out)
    finally:
        wb.close()
    return "\n".join(out)


def _strip_tags(markup: str) -> str:
    markup = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", markup)
    markup = re.sub(r"(?s)<[^>]+>", " ", markup)
    return html.unescape(markup)


def _html_text(path: Path) -> str:
    raw = path.read_bytes()[: MAX_TEXT * 6]
    return _strip_tags(raw.decode("utf-8", "replace"))


def _plain_text(path: Path) -> str:
    """A .txt that may be UTF-16 — M2TW's own text files usually are."""
    raw = path.read_bytes()[: MAX_TEXT * 2]
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", "replace")
    return raw.decode("utf-8", "replace")


def extract(path: Path) -> str:
    ext = path.suffix.lower()
    try:
        if ext == ".pdf":
            return _pdf_text(path)
        if ext == ".docx":
            return _docx_text(path)
        if ext == ".xlsx":
            return _xlsx_text(path)
        if ext in (".htm", ".html"):
            return _html_text(path)
        return _plain_text(path)
    except Exception:
        return ""


def clean(text: str) -> str:
    """Collapse whitespace and drop the control characters PDFs leak."""
    text = unicodedata.normalize("NFKC", text)
    text = "".join(c if c.isprintable() or c in "\n\t" else " " for c in text)
    return re.sub(r"[ \t]+", " ", text)


# ---------------------------------------------------------------------------
# what game files a document is about
# ---------------------------------------------------------------------------
#: Matched against the text AND the filename. Patterns rather than a fixed list:
#: mods invent files (descr_mercenaries, export_descr_sounds_units_voice) and a
#: hardcoded roster would miss exactly the unusual ones a tutorial exists for.
FILE_PATTERNS = (
    r"\bexport_descr_[a-z0-9_]+\.txt\b",
    r"\bexport_[a-z0-9_]+\.txt\b",
    r"\bdescr_[a-z0-9_]+\.(?:txt|xml)\b",
    r"\b[a-z0-9_]*battle_models\.modeldb\b",
    r"\bcampaign_script\.txt\b",
    r"\bmap_[a-z0-9_]+\.tga\b",
    r"\b(?:water_surface|ground_types|climates|features|heights|roughness)\.tga\b",
    r"\b[a-z0-9_.]+\.strings\.bin\b",
    r"\b[a-z0-9_]+\.(?:cas|mesh|sd|worldpkgdesc)\b",
    r"\bmedieval2\.preference\.cfg\b",
    r"\b[a-z0-9_]+\.cfg\b",
)
FILE_RE = re.compile("|".join(FILE_PATTERNS), re.I)

#: Mentions that are noise: generic names any document picks up in passing.
FILE_NOISE = {"descr_.txt", "export_descr_.txt", "config.cfg", "settings.cfg"}


def game_files(text: str, name: str) -> list[dict]:
    counts: Counter[str] = Counter()
    for hay, weight in ((name, 5), (text, 1)):        # a filename hit means more
        for m in FILE_RE.finditer(hay):
            f = m.group(0).lower()
            if f in FILE_NOISE or len(f) < 6:
                continue
            counts[f] += weight
    return [{"file": f, "hits": n} for f, n in counts.most_common(25)]


# ---------------------------------------------------------------------------
# topics
# ---------------------------------------------------------------------------
#: tag -> (regexes searched in the text, regexes searched in the filename).
#: Filename matches are worth more: whoever saved the file named it for its
#: subject, while a passing mention of "sprite" proves nothing.
TAGS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "units": ((r"export_descr_unit", r"\bEDU\b", r"unit stat", r"soldier\b"),
              (r"\bunit", r"\bEDU\b", r"cavalry", r"infantry", r"berserker")),
    "buildings": ((r"export_descr_buildings", r"\bEDB\b", r"building tree",
                   r"recruit_pool", r"capability"),
                  (r"building", r"\bEDB\b", r"guild", r"fort")),
    "traits": ((r"export_descr_character_traits", r"\bEDCT\b", r"\bTrigger\b.*\bAffects\b",
                r"antitrait"), (r"trait", r"\bEDCT\b")),
    "ancillaries": ((r"export_descr_ancillaries", r"\bEDA\b", r"ancillary"),
                    (r"ancillar", r"\bEDA\b", r"retinue")),
    "campaign-map": ((r"descr_strat", r"map_regions", r"map_heights", r"campaign map",
                      r"descr_regions"),
                     (r"\bmap\b", r"campaign", r"region", r"coastline", r"river",
                      r"climate", r"geomod", r"worldwind", r"3dem")),
    "factions": ((r"descr_sm_factions", r"faction symbol", r"new faction",
                  r"faction_standing"),
                 (r"faction", r"banner", r"symbol", r"emergent")),
    "strings": ((r"\.strings\.bin", r"BinEditor", r"expanded\.txt"),
                (r"bineditor", r"strings", r"name converter", r"unique names")),
    "sounds": ((r"descr_sounds", r"export_descr_sounds", r"\bvoice\b", r"\bidx\b.*\bdat\b",
                r"accent"),
               (r"sound", r"music", r"voice", r"accent", r"audio")),
    "models-3d": ((r"battle_models\.modeldb", r"\.cas\b", r"\.mesh\b", r"milkshape",
                   r"\bLOD\b"),
                  (r"model", r"\bcas\b", r"\bbmdb\b", r"blender", r"strat model",
                   r"retextur", r"\bUV\b", r"mesh")),
    "sprites": ((r"\bsprite\b", r"\.spr\b", r"sprite sheet"),
                (r"sprite",)),
    "textures": ((r"\.dds\b", r"\.texture\b", r"normal map", r"alpha channel"),
                 (r"textur", r"\bDDS\b", r"\bGIMP\b", r"portrait", r"2d building art")),
    "animation": ((r"descr_skeleton", r"animation", r"\bpose\b"),
                  (r"animation", r"skeleton", r"anim\b")),
    "scripting": ((r"campaign_script", r"\bmonitor_event\b", r"\bI_\w+", r"console_command",
                   r"\bwhile\b.*\bend_while\b"),
                  (r"script", r"event", r"trigger", r"marian", r"invasion", r"garrison",
                   r"reform")),
    "projectiles": ((r"descr_projectile", r"projectile", r"\bprec\b"),
                    (r"projectile", r"arrow", r"greekfire", r"javelin")),
    "mounts": ((r"descr_mount", r"mount_effect"), (r"mount", r"horse", r"cavalry", r"animal")),
    "religion": ((r"descr_religions", r"religion"), (r"religio", r"piety", r"inquisitor")),
    "culture": ((r"descr_cultures", r"\bculture\b"), (r"culture",)),
    "characters": ((r"descr_character", r"family tree", r"portrait", r"\bnames\.txt\b"),
                   (r"character", r"family", r"portrait", r"general", r"captain", r"hero",
                    r"adoption", r"legion-names")),
    "resources": ((r"descr_sm_resources", r"hidden_resource", r"\bresource\b"),
                  (r"resource", r"\bAOR\b", r"mine")),
    "settlements": ((r"settlement_mechanics", r"descr_settlement", r"\bwalls\b"),
                    (r"settlement", r"siege", r"garrison", r"city", r"castle")),
    "mercenaries": ((r"descr_mercenaries", r"mercenar"), (r"mercenar",)),
    "installation": ((r"\bunpack", r"steam", r"registry", r"\bmod folder\b"),
                     (r"install", r"steam", r"unpack", r"launcher", r"registry", r"4gb")),
    "troubleshooting": ((r"crash to desktop", r"\bCTD\b", r"error log", r"hardcoded limit"),
                        (r"crash", r"\bfix\b", r"glitch", r"problem", r"limit", r"error")),
    "tools": ((r"\.exe\b", r"download the tool"),
              (r"tool", r"editor", r"converter", r"generator", r"utility", r"patch")),
}

#: Which roadmap phase each tag informs. A phase can pull its own reading list
#: with one grep; tags with no phase (installation, troubleshooting) are still
#: indexed, they just answer no phase's questions.
TAG_PHASES: dict[str, tuple[str, ...]] = {
    "units": ("13",), "buildings": ("12",), "traits": ("8",), "ancillaries": ("9",),
    "campaign-map": ("15",), "factions": ("11",), "strings": ("6",),
    "sounds": ("13",), "models-3d": ("14",), "sprites": ("14",), "textures": ("14",),
    "animation": ("14",), "scripting": ("7",), "projectiles": ("13",),
    "mounts": ("13",), "religion": ("10",), "culture": ("10",),
    "characters": ("10", "15"), "resources": ("10", "15"),
    "settlements": ("12", "15"), "mercenaries": ("15",),
}


def topics(text: str, name: str) -> list[str]:
    found = []
    for tag, (body_pats, name_pats) in TAGS.items():
        score = 0
        for p in name_pats:
            if re.search(p, name, re.I):
                score += 3
        for p in body_pats:
            if re.search(p, text, re.I):
                score += 1
        if score >= 2:
            found.append((score, tag))
    found.sort(reverse=True)
    return [t for _, t in found]


def phases_for(tags: list[str]) -> list[str]:
    out: set[str] = set()
    for t in tags:
        out.update(TAG_PHASES.get(t, ()))
    return sorted(out, key=int)


# ---------------------------------------------------------------------------
# per-document record
# ---------------------------------------------------------------------------
#: Forum furniture. Every page saved from TWCenter opens with the same
#: not-logged-in banner, and it is not what any of these guides is about.
BOILERPLATE = (
    "if this is your first visit", "check out the faq", "register before you can post",
    "click the register link", "to start viewing messages", "select the forum that you want",
    "all times are gmt", "powered by vbulletin", "printable version", "join date",
    "last edited by", "originally posted by", "results 1 to", "share this post",
    "cookies", "privacy policy", "terms of service", "javascript",
    # A rendered forum page puts its footer and nav in the text layer before the
    # post body, so without these the "summary" of half the archive is a
    # copyright notice.
    "vbulletin", "jelsoft", "dragonbyte", "optimisation provided", "contact us",
    "privacy statement", "quick navigation", "posting permissions", "similar threads",
    "forgot password", "remember me", "advanced search", "bookmarks",
    "original thread:", "thread:", "user name", "you may not post",
)


def summarize(text: str, title: str) -> str:
    """The first line that reads like prose about the subject.

    Tutorials open with navigation chrome, forum breadcrumbs and the author's
    signature block; the first *sentence-shaped* line past that is almost always
    the real opening of the guide.
    """
    for raw in text.split("\n"):
        line = raw.strip()
        if len(line) < 40 or len(line) > 400:
            continue
        low = line.lower()
        if low.startswith(("http", "www.", "posted by", "quote:", "originally posted")):
            continue
        if any(b in low for b in BOILERPLATE):
            continue
        if line.count("|") > 2 or line.count("•") > 2:
            continue
        if not re.search(r"[a-z]{3}\s+[a-z]{3}", line, re.I):   # needs real words
            continue
        # Skip the document's own heading however it is punctuated: the saved
        # page repeats the thread title, sometimes with the "[Modding]" prefix
        # the filename dropped, sometimes with a colon or a ".txt" the filename
        # couldn't carry. Substring matching misses those, so compare by words.
        if _is_heading(line, title):
            continue
        return re.sub(r"\s+", " ", line)[:300]
    return ""


def _squash(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _is_heading(line: str, title: str) -> bool:
    """True when `line` is just the title again. Four fifths of the title's
    words being present is the threshold: enough to catch a re-punctuated
    heading, not so loose that a first sentence reusing the subject is lost."""
    a, b = _squash(line), _squash(title)
    if a and b and (a in b or b in a):
        return True
    words = {w for w in re.findall(r"[a-z0-9]+", title.lower()) if len(w) > 2}
    if not words:
        return False
    have = {w for w in re.findall(r"[a-z0-9]+", line.lower()) if len(w) > 2}
    return len(words & have) / len(words) >= 0.8 and len(have) <= len(words) + 4


def title_for(path: Path) -> str:
    """The filename, tidied. Whoever saved these named them well; PDF metadata
    titles are mostly the printing browser's idea of the page and are worse."""
    stem = path.stem
    stem = re.sub(r"^\[(?:Modding|Tutorial|Resource|TW Guide|FIX|M2TW modding tutorial)\]\s*",
                  "", stem, flags=re.I)
    stem = re.sub(r"\s+", " ", stem.replace("_", " ")).strip(" -–—")
    return stem or path.stem


def is_doc(path: Path) -> bool:
    if path.suffix.lower() not in DOC_EXTS:
        return False
    # The index writes itself into the archive it walks. Left in, each run would
    # index the previous run's output — the tags of every topic at once — and the
    # file would never settle.
    if path.name in (OUT_JSON.name, OUT_MD.name):
        return False
    return not any(marker in part for part in path.parts for marker in SKIP_DIR_MARKERS)


#: Formats a tutorial is written in. A .txt sitting beside one of these is the
#: script it tells you to paste, not a second tutorial.
PROSE_EXTS = (".pdf", ".htm", ".html", ".docx")


def _primary(paths: list[Path], folder: Path) -> Path:
    """Which file in a folder *is* the tutorial.

    Prefer a prose document named after its folder, then any prose document,
    then the biggest file. `Mongol invasion script/` holds the PDF of the guide
    and the .txt of the script it hands you — the PDF is the document, the .txt
    is its attachment.
    """
    prose = [p for p in paths if p.suffix.lower() in PROSE_EXTS]
    want = folder.name.lower()
    for p in prose:
        if p.stem.lower() == want or want in p.stem.lower() or p.stem.lower() in want:
            return p
    if prose:
        return max(prose, key=lambda p: p.stat().st_size)
    return max(paths, key=lambda p: p.stat().st_size)


def build(archive: Path) -> dict:
    paths = sorted((p for p in archive.rglob("*") if p.is_file() and is_doc(p)),
                   key=lambda p: str(p).lower())

    # A folder in this archive is one piece of knowledge: a tutorial plus the
    # scripts, data files and converted text it ships with. Indexing every one
    # of those as its own document buried the 300 real guides under a folder of
    # 35 one-line script fragments. Files at the archive root are each their own
    # document — nothing groups them.
    groups: dict[Path, list[Path]] = {}
    for p in paths:
        groups.setdefault(p.parent, []).append(p)

    units: list[tuple[Path, list[Path]]] = []
    for folder, members in groups.items():
        if folder == archive or len(members) == 1:
            units += [(m, []) for m in members]
        else:
            main = _primary(members, folder)
            units.append((main, [m for m in members if m != main]))
    units.sort(key=lambda u: str(u[0]).lower())

    docs, unreadable = [], []
    for i, (path, extra) in enumerate(units, 1):
        rel = path.relative_to(archive).as_posix()
        print(f"  [{i:>3}/{len(units)}] {rel[:78]}", flush=True)
        text = clean(extract(path))[:MAX_TEXT]
        name = title_for(path)
        # The folder name carries subject too — "Mongol invasion script/x.pdf"
        # is about scripting even when the file inside is called "x".
        parent = path.parent.name if path.parent != archive else ""
        name_hay = f"{name} {parent} {' '.join(p.stem for p in extra[:40])}"
        # Game-file detection reads the RAW names — `title_for` turns underscores
        # into spaces for readability, which stops `export_descr_unit.txt` from
        # matching itself. That matters most for the archive's copies of the game
        # files themselves, which are the format examples worth finding.
        raw_hay = f"{path.name} {parent} {' '.join(p.name for p in extra[:40])}"
        # Attachments are read too: the script a tutorial hands you names the
        # events and files the prose only gestures at.
        for p in extra[:40]:
            if p.suffix.lower() in (".txt", ".md"):
                text += "\n" + clean(extract(p))[:4000]
        rec = {
            "path": rel,
            "title": name,
            "ext": path.suffix.lower().lstrip("."),
            "kb": round(path.stat().st_size / 1024),
            "tags": topics(text, name_hay),
            "game_files": game_files(text, raw_hay),
            "summary": summarize(text, name),
            "chars": len(text),
            "attachments": [p.relative_to(archive).as_posix() for p in extra],
        }
        rec["phases"] = phases_for(rec["tags"])
        if len(text) < MIN_TEXT:
            rec["tags"] = rec["tags"] + ["needs-manual-read"]
            unreadable.append(rel)
        docs.append(rec)
    return {"archive": archive.name, "documents": docs, "unreadable": unreadable,
            "files_indexed": len(paths)}


# ---------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------
def render_md(index: dict) -> str:
    docs = index["documents"]
    by_tag: dict[str, list[dict]] = {}
    for d in docs:
        for t in d["tags"]:
            if t != "needs-manual-read":
                by_tag.setdefault(t, []).append(d)
    untagged = [d for d in docs if not [t for t in d["tags"] if t != "needs-manual-read"]]

    # The coverage table is about FORMATS, so a tutorial's own asset ("grape.cas",
    # "symbol_rebels.cas") is dropped here — it stays on the document's own row,
    # where naming one specific model is the useful thing.
    format_re = re.compile(r"^(?:export_|descr_|campaign_script|map_[a-z_]+\.tga$"
                           r"|battle_models\.modeldb$)|\.(?:sd|strings\.bin|cfg)$", re.I)
    files = Counter()
    for d in docs:
        for gf in d["game_files"]:
            if format_re.search(gf["file"]):
                files[gf["file"]] += 1

    out = [
        "# TWCenter archive — index",
        "",
        f"{len(docs)} documents covering {index['files_indexed']} files, generated by "
        "`tools/twc_index.py`. Rebuild after adding tutorials: "
        "`python tools/twc_index.py`.",
        "",
        "A **document** is a piece of knowledge, not a file: a tutorial's own "
        "scripts and data files are attachments of it (`+N` on its row, listed "
        "in `INDEX.json`), because a folder of 35 one-line script fragments is "
        "one guide, not 35. Attachment text is searched too, so a tutorial is "
        "tagged for what its scripts do as well as what its prose says.",
        "",
        "This is the ground truth for how Medieval II's files behave. When a "
        "format or a field's meaning is unclear, grep here first:",
        "",
        "```bash",
        'grep -i "descr_mount" Reference/TWCenter/INDEX.md   # who documents this file',
        'grep -i "phase:8" Reference/TWCenter/INDEX.md       # reading list for a phase',
        "```",
        "",
        "Paths are relative to `Reference/TWCenter/`. `needs-manual-read` means "
        "no text layer (a scan or an image-only export) — open it by hand.",
        "",
        "## Game files by coverage",
        "",
        "How many documents mention each file. A file with no entry here is one "
        "nothing in the archive explains — worth knowing before a phase starts.",
        "",
        "| Game file | Documents |",
        "|---|---|",
    ]
    for f, n in files.most_common(60):
        out.append(f"| `{f}` | {n} |")

    # Reading list per roadmap phase. The topic sections below are organised for
    # browsing; this is organised for the question an actual session asks —
    # "I am starting phase 8, what in here explains the file I am about to parse?"
    out += ["", "## Reading list by roadmap phase", "",
            "See `ROADMAP.md` for what each phase builds. Ranked by how much of "
            "the document is about that phase's subject.", ""]
    by_phase: dict[str, list[dict]] = {}
    for d in docs:
        for p in d["phases"]:
            by_phase.setdefault(p, []).append(d)
    for phase in sorted(by_phase, key=int):
        # Rank by how central this phase's subject is to the document, not by how
        # many files it name-drops — "Crashes and how to fix them" mentions half
        # the game and is nobody's first read. `tags` is already strongest-first,
        # so the position of the phase's own tag is the measure.
        def centrality(d, _p=phase):
            spots = [i for i, t in enumerate(d["tags"]) if _p in TAG_PHASES.get(t, ())]
            return min(spots) if spots else 99
        entries = sorted(by_phase[phase], key=lambda d: (centrality(d), -d["chars"]))
        out += [f"**phase:{phase}** — {len(entries)} documents", ""]
        for d in entries[:10]:
            gf = ", ".join(f"`{g['file']}`" for g in d["game_files"][:3]) or "—"
            flag = " ⚠" if "needs-manual-read" in d["tags"] else ""
            out.append(f"- [{_text(d['title'])}]({_link(d['path'])}){flag} — {gf}")
        if len(entries) > 10:
            out.append(f"- …{len(entries) - 10} more under the topic sections below")
        out.append("")

    out += ["", "## Documents by topic", ""]
    for tag in sorted(by_tag, key=lambda t: (-len(by_tag[t]), t)):
        entries = sorted(by_tag[tag], key=lambda d: d["title"].lower())
        ph = TAG_PHASES.get(tag)
        head = f"### {tag}" + (f"  ·  phase:{' phase:'.join(ph)}" if ph else "")
        out += [head, "", f"{len(entries)} documents.", "",
                "| Document | Game files | Summary |", "|---|---|---|"]
        for d in entries:
            gf = ", ".join(f"`{g['file']}`" for g in d["game_files"][:4]) or "—"
            summary = (d["summary"] or "").replace("|", "\\|")[:160]
            flag = " ⚠" if "needs-manual-read" in d["tags"] else ""
            att = f" +{len(d['attachments'])}" if d["attachments"] else ""
            out.append(f"| [{_text(d['title'])}]({_link(d['path'])}){flag}{att} "
                       f"| {gf} | {summary} |")
        out.append("")

    if untagged:
        out += ["## Untagged", "",
                "Nothing matched — usually a tool's own readme or a data dump.", "",
                "| Document | Game files |", "|---|---|"]
        for d in sorted(untagged, key=lambda d: d["title"].lower()):
            gf = ", ".join(f"`{g['file']}`" for g in d["game_files"][:4]) or "—"
            out.append(f"| [{_text(d['title'])}]({_link(d['path'])}) | {gf} |")
        out.append("")

    if index["unreadable"]:
        out += ["## needs-manual-read", "",
                f"{len(index['unreadable'])} documents yielded no usable text "
                "(scanned pages, image-only exports, or an empty file). They are "
                "indexed by name only.", ""]
        out += [f"- `{p}`" for p in index["unreadable"]]
        out.append("")
    return "\n".join(out)


def _link(rel: str) -> str:
    """Markdown link target for a path with spaces and brackets in it."""
    return "<" + rel + ">"


def _text(s: str) -> str:
    """Link text. Half these titles start with `[Tutorial]`, which without
    escaping closes the link before it opens."""
    return s.replace("[", "\\[").replace("]", "\\]")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="report what would change without writing")
    ap.add_argument("--archive", default=str(ARCHIVE), help="archive folder to index")
    args = ap.parse_args(argv)

    archive = Path(args.archive)
    if not archive.is_dir():
        print(f"no archive at {archive}", file=sys.stderr)
        return 2

    print(f"indexing {archive}")
    index = build(archive)
    md = render_md(index)
    js = json.dumps(index, indent=1, ensure_ascii=False)

    docs = index["documents"]
    tagged = sum(1 for d in docs if [t for t in d["tags"] if t != "needs-manual-read"])
    print(f"\n{len(docs)} documents · {tagged} tagged · "
          f"{len(index['unreadable'])} need a manual read")

    if args.check:
        for path, new in ((OUT_JSON, js), (OUT_MD, md)):
            old = path.read_text(encoding="utf-8") if path.exists() else ""
            print(f"  {path.name}: {'unchanged' if old == new else 'WOULD CHANGE'}")
        return 0

    OUT_JSON.write_text(js, encoding="utf-8")
    OUT_MD.write_text(md, encoding="utf-8")
    print(f"  wrote {OUT_MD.relative_to(ROOT)}\n  wrote {OUT_JSON.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
