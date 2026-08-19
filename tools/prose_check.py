"""Find UI prose that breaks the toolkit's two writing rules.

The rules (ROADMAP, 2026-08-18): a note in the UI is a lead line plus points
through ``docPoints()``, never prose joined by em dashes; and every sentence
starts with a capital. Em dashes are fine in code comments and in short
appositives — this only flags the ones doing a full stop's job.

    python tools/prose_check.py            # a summary and the worst offenders
    python tools/prose_check.py --all      # every hit
    python tools/prose_check.py --file web/js/home.js

It is a heuristic, not a linter: it reads text out of string literals and cannot
know for certain where a sentence ends. Treat the output as a work list, and read
each hit in context before rewriting it.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: How long the text after a dash has to be before it stops being an appositive
#: and starts being a clause the dash is holding together.
CLAUSE_CHARS = 55

DASH = re.compile(r"\s[—–]\s")
#: A line of code rather than prose: no point flagging a dash inside a regex, a
#: path or an identifier.
CODE_ISH = re.compile(r"^(//|/\*|\*|rem\s|#)")


#: An inline style, not a sentence. ``'flex:0 0 88px'`` and
#: ``'margin-left:auto;display:flex'`` have spaces and letters like prose does,
#: and they were being stitched onto the title next to them and then reported
#: for opening in lower case — which they are supposed to do.
CSS_DECL = re.compile(r"^[a-z-]+\s*:\s*[^;]+(?:;\s*[a-z-]+\s*:\s*[^;]+)*;?$")

#: `+( … )+` — a value spliced into the middle of a sentence. See :func:`_fold`.
INTERP = re.compile(r"\+\s*\([^()]*\)\s*\+")


def _literals(line: str):
    """``[(text, glued)]`` for the quoted runs that look like visible text.

    ``glued`` says the literal continues the one before it: joined by ``+``, or
    by ``+ something +`` where the something is a value being interpolated into
    the middle of a sentence (``'on a '+esc(cat)+' unit the engine…'``). Both
    are halves of one sentence.

    Anything else between them — a ``?``, a ``:``, a comma, markup — means they
    are separate strings that only happen to share a line, and joining those
    invents sentences nobody wrote. The two branches of a ternary were being
    read as one, which is where "the replaced unit — pick one first the base
    unit — pick one" came from.
    """
    out = []
    end = 0
    # `(?:[^'\\\n]|\\.)` rather than `[^'\n]`: an apostrophe inside a
    # single-quoted string is written \' , and stopping at it chopped
    # "the source unit\'s own skeletons come across" into pieces that were then
    # reported for opening in lower case.
    for m in re.finditer(
            r"""(?:'((?:[^'\\\n]|\\.){12,})'"""
            r"""|"((?:[^"\\\n]|\\.){12,})\""""
            r"""|`((?:[^`\\\n]|\\.){12,})`)""", line):
        s = next(g for g in m.groups() if g is not None)
        sep, end = line[end:m.start()], m.end()
        # visible text has spaces and letters; skip selectors, urls, formats
        if " " not in s or not re.search(r"[A-Za-z]{3}", s):
            continue
        if s.startswith(("#", ".", "/", "http")) or "://" in s:
            continue
        if CSS_DECL.match(s.strip()):
            continue
        # joined by `+`; by `+ value +`; or by `+ (expression) +`, which is how a
        # choice is dropped into the middle of a sentence:
        #   '…animates like '+(rep?'the replaced unit':'the base unit')+' instead…'
        # The parentheses are what tell that apart from a bare ternary PICKING
        # between two whole strings, where the separator is just `:`.
        glued = re.fullmatch(r"[\s+]*|\+[^'\"`?:,]*\+|\+\s*\([^()]*\)\s*\+",
                             sep) is not None
        out.append((s, bool(out) and glued))
    return out


def _groups(line: str):
    """The logical strings on one line — ``+``-glued literals joined into one."""
    groups = []
    for s, glued in _literals(line):
        if glued and groups:
            groups[-1] += " " + s
        else:
            groups.append(s)
    return groups


def _fold(text: str):
    """``(first line number, source)`` with ``+`` continuations merged.

    The stitching this module's docstring promises only worked when the ``+``
    was left at the END of a line. This codebase overwhelmingly writes it at the
    START of the continuation instead::

        help:'The weapon’s attack factor — how much damage a blow does. '
          +'A higher number is stored but behaves as 63.'

    and every one of those continuations was being flushed as a string of its
    own and then reported for opening in lower case. 37 of guided.js's 37 hits
    were that, and nothing else. Folding the physical lines into logical ones
    before any literal is read fixes the measurement at the source, rather than
    asking 90 sentences to be rewritten around a quirk of the reader.
    """
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if out and (s.startswith("+") or out[-1][1].rstrip().endswith("+")):
            out[-1] = (out[-1][0], out[-1][1] + " " + s)
        else:
            out.append((i, line))
    # A choice dropped into the middle of a sentence is one value, not two
    # strings: in `'animates like '+(rep?'the replaced unit':'the base unit')+'
    # instead…'` the branches are words in a slot, and reading them as literals
    # of their own split the sentence around them into lower-case fragments.
    return [(i, INTERP.sub(" + ", line)) for i, line in out]


def ui_strings(text: str):
    """(line number, string) per LOGICAL string of visible text.

    A long note is written as several literals joined with ``+`` across several
    source lines, and each continuation naturally starts mid-sentence in lower
    case. Reading them line by line reported 589 "lower-case sentence starts",
    almost all of which were the second half of a sentence that began correctly
    on the line above. So the fragments of one expression are stitched back
    together before anything is measured — :func:`_fold` across lines, and
    :func:`_groups` within one — and nothing else is: two literals that merely
    share a line stay two strings.
    """
    for i, line in _fold(text):
        if CODE_ISH.match(line.strip()):
            continue
        for s in _groups(line):
            yield i, s


def clause_dashes(s: str):
    """Dashes with a long stretch of text after them — a full stop's work."""
    out = []
    for m in DASH.finditer(s):
        after = s[m.end():]
        # strip markup and template holes before measuring
        plain = re.sub(r"<[^>]*>", "", after)
        plain = re.sub(r"\$\{[^}]*\}", "", plain).strip()
        if len(plain) >= CLAUSE_CHARS:
            out.append(plain[:70])
    return out


def lower_starts(s: str):
    """SENTENCES that open in lower case, ignoring code and template holes.

    A label is not a sentence: "mercs only", "per turn" and "pool" are exactly
    right in lower case, and flagging them buries the real hits. A run of text
    counts as a sentence when it ends in a full stop or is long enough to be
    prose — which is the same line the eye draws.
    """
    plain = re.sub(r"<[^>]*>", " ", s)
    plain = re.sub(r"\$\{[^}]*\}", "", plain).strip()
    if not plain:
        return []
    sentence_ish = plain.endswith((".", "!", "?")) or len(plain) >= 60
    if not sentence_ish:
        return []
    # A LIST is not a sentence either, for the same reason a label is not: the
    # `syn:` lines name a record's value slots in the order the file writes them
    # ("attack, charge, projectile, range, ammo, …") and every one of those
    # words is an EDU term that is lower case by definition. Long enough to look
    # like prose, punctuated like an inventory.
    if plain.count(",") >= 2 and not re.search(r"[.!?]", plain):
        return []
    # The opening of the string, and only that. Scanning after every full stop was
    # tried and abandoned: a sentence may legitimately open with a code identifier
    # ("`no` means a melee weapon", "`spear` also carries a penalty"), an EDU
    # keyword is lower case by definition, and there is no way to tell those from
    # a real slip without reading the line — which is what the work list is for.
    if s.lstrip().startswith("<"):
        return []                      # opens inside markup: <code>keyword</code>
    # Opens on a value, not a word: "${n} pool(s) added…" reads "3 pool(s)
    # added…" on screen. Stripping the hole and then judging the first letter
    # asks a sentence that starts with a number to start with a capital.
    if s.lstrip().startswith("${"):
        return []
    if not re.match(r"[a-z]{3,}\b", plain) or plain.startswith(("px", "em", "rem")):
        return []
    return [plain[:60]]


def scan(paths):
    hits = []
    for p in paths:
        text = p.read_text(encoding="utf-8")
        for line, s in ui_strings(text):
            for bad in clause_dashes(s):
                hits.append(("dash", p, line, bad))
            for bad in lower_starts(s):
                hits.append(("case", p, line, bad))
    return hits


def main(argv):
    show_all = "--all" in argv
    if "--file" in argv:
        paths = [ROOT / argv[argv.index("--file") + 1]]
    else:
        paths = sorted((ROOT / "web" / "js").glob("*.js")) + [ROOT / "web" / "index.html"]

    hits = scan(paths)
    per_file = {}
    for kind, p, line, text in hits:
        per_file.setdefault(p.name, []).append((kind, line, text))

    dashes = sum(1 for h in hits if h[0] == "dash")
    cases = sum(1 for h in hits if h[0] == "case")
    print(f"{len(hits)} hits in {len(per_file)} files — "
          f"{dashes} clause-joining dashes, {cases} lower-case sentence starts\n")
    for name in sorted(per_file, key=lambda n: -len(per_file[n])):
        rows = per_file[name]
        print(f"  {len(rows):3}  {name}")
        if show_all:
            for kind, line, text in rows:
                print(f"        {kind} {name}:{line}  {text}")
    if not show_all:
        print("\n  --all to list every hit, --file <path> for one file")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
