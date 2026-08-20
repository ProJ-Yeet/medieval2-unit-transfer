"""What a ``requires`` clause in the EDB is allowed to name.

Every condition in ``export_descr_buildings.txt`` refers to something declared
somewhere else in the mod — a faction, a religion, an event counter, a hidden
resource — by its code name. Typing those by hand is how a building silently
stops being buildable: the game does not complain about
``requires event_counter anduin_citys 1``, it just never fires.

So this module reads each of those lists out of the mod and hands them to the
UI, which turns them into checklists showing the real in-game name with the code
name in brackets. Sources::

    factions      data/descr_sm_factions.txt  (+ display names from text/expanded.txt)
    cultures      data/descr_cultures.txt, and the cultures factions claim
    religions     data/descr_religions.txt  (its `religions { … }` list)
    hidden res.   the `hidden_resources` line at the top of the EDB itself
    resources     data/descr_sm_resources.txt
    buildings     the EDB's own lines and levels
    events        text/historic_events.txt, `set_event_counter` in the campaign
                  scripts, and whatever the EDB already names

Everything here is best-effort: a mod missing one of these files gets an empty
list for it, never an error, and the clause editor always keeps a raw-text
escape hatch for anything not on a list.

Three of the lists — cultures, religions and resources — are *not* parsed here.
They come from :mod:`unittransfer.minorfiles`, which is the module that edits
those files, so the names the clause editor offers and the names that module
writes can never drift apart. One engine, one parser per format.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Set

#: Plain 8-bit game data, same as the EDU/EDB.
ENCODING = "latin-1"

#: Where the campaign's own scripts live, relative to ``data/``. Event counters
#: are declared and set there, so this is the only place most of them exist.
SCRIPT_DIRS = ("world/maps/campaign", "scripts")

#: Cap on how much script text is scanned. A big mod's campaign_script.txt is
#: several MB and this runs on every mod load.
_MAX_SCRIPT_BYTES = 24 * 1024 * 1024

#: The wildcard a ``factions { … }`` list accepts instead of naming anyone.
ALL = "all"


def _read(path: Path, encodings=(ENCODING,)) -> str:
    for enc in encodings:
        try:
            return path.read_text(encoding=enc)
        except (OSError, UnicodeError):
            continue
    return ""


def _read_utf16(path: Path) -> str:
    """A ``data/text`` file: UTF-16 with a BOM, falling back to 8-bit."""
    return _read(path, ("utf-16", "latin-1"))


# Three of these lists come out of files the Minor Files module owns, and it owns
# them properly — the same parser that edits them, not a regex beside it. That is
# the whole point of the one-engine rule: `descr_cultures.txt` in particular has
# a `culture` keyword on its agent lines' neighbours and a tail outside the
# brace, and a regex for `^culture (\S+)` was only ever right by luck.


def religions(mod) -> List[str]:
    """Religion names — :func:`unittransfer.minorfiles.religion_names` is the source."""
    from . import minorfiles
    return minorfiles.religion_names(mod)


def cultures(mod) -> List[str]:
    """Culture names — from descr_cultures.txt, plus any a faction claims."""
    from . import minorfiles
    out = list(minorfiles.culture_names(mod))
    for c in mod.faction_cultures.values():
        if c not in out:
            out.append(c)
    return sorted(out)


def resources(mod) -> List[str]:
    """Trade resources — :func:`unittransfer.minorfiles.resource_names` is the source."""
    from . import minorfiles
    return sorted(set(minorfiles.resource_names(mod)))


#: Where the region list lives, relative to ``data/``.
REGIONS_REL = "world/maps/base/descr_regions.txt"
REGION_NAMES_REL = "text/imperial_campaign_regions_and_settlement_names.txt"


def regions(mod, hidden_names=()) -> List[dict]:
    """Every region, from ``data/world/maps/base/descr_regions.txt``.

    A positional record: the region name unindented, then an indented block whose
    lines are, in order::

        legion: <name>          (optional — the legion recruitment name)
        <settlement>
        <faction that owns it at the start>
        <rebel type that spawns there>
        <r> <g> <b>             (its colour on the map image)
        <resources, comma separated — trade AND hidden, mixed>
        <triumph value>
        <base farming level>
        religions { catholic 7 elven 5 … }

    The two bare numbers used to be written down here the other way round, and
    the file itself settles it: across vanilla's 112 regions the first is 5 on
    all but two records while the second runs 1–6 with a real spread, which is
    a fertility level and not a score. Both test mods write 5 and 1 for every
    region, so neither could have told them apart. Nothing reads either value
    yet — the region inspector of the campaign map editor is what will.

    The resource line is the interesting one, and it mixes the two kinds: a name
    declared on the EDB's ``hidden_resources`` line is a hidden resource, and
    anything else is a trade resource. Splitting them is what lets a
    ``requires hidden_resource X`` picker say *which places* X actually means.

    Display names for both the region and its settlement come from
    ``text/imperial_campaign_regions_and_settlement_names.txt``.
    """
    text = _read(mod.data / REGIONS_REL)
    if not text:
        return []
    names = {}
    loc = _read_utf16(mod.data / REGION_NAMES_REL)
    if loc:
        names = dict(re.findall(r"^\{([^}]+)\}(.*)$", loc, re.M))
    hidden_set = {h.lower() for h in hidden_names}

    out: List[dict] = []

    def flush(header: str, body: List[str]) -> None:
        rows, legion = [], ""
        for ln in body:
            s = ln.split(";", 1)[0].strip()
            if not s:
                continue
            if s.lower().startswith("legion:"):
                legion = s.split(":", 1)[1].strip()
                continue
            rows.append(s)
        if len(rows) < 5:
            return
        # the resource line is the first comma-separated one after the RGB triple
        res_at = next((i for i, r in enumerate(rows[4:], 4) if "," in r), None)
        resources_all = ([t.strip() for t in rows[res_at].split(",") if t.strip()]
                         if res_at is not None else [])
        rel = {}
        m = re.search(r"religions\s*\{([^}]*)\}", " ".join(rows))
        if m:
            toks = m.group(1).split()
            rel = {toks[i]: toks[i + 1] for i in range(0, len(toks) - 1, 2)}
        out.append({
            "region": header,
            "name": (names.get(header) or "").strip() or header,
            "settlement": rows[0],
            "settlement_name": (names.get(rows[0]) or "").strip() or rows[0],
            "faction": rows[1],
            "rebels": rows[2] if len(rows) > 2 else "",
            "legion": legion,
            "hidden_resources": [r for r in resources_all if r.lower() in hidden_set],
            "resources": [r for r in resources_all if r.lower() not in hidden_set],
            "religions": rel,
        })

    header, current = "", []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith(";"):
            continue
        # A region starts unindented — except that Third Age 6 writes its
        # `religions { … }` line flush left too, and treating that as a new
        # region would both lose the religions and invent a phantom record.
        starts_region = (line[:1] not in (" ", "\t")
                         and not line.lstrip().lower().startswith("religions"))
        if starts_region:
            if header:
                flush(header, current)
            header, current = line.strip(), []
        elif header:
            current.append(line)
    if header:
        flush(header, current)
    return out


def _script_files(mod) -> List[Path]:
    out: List[Path] = []
    for rel in SCRIPT_DIRS:
        base = mod.data / rel
        if not base.is_dir():
            continue
        try:
            out += [p for p in base.rglob("*.txt") if p.is_file()]
        except OSError:
            continue
    return out


def event_counters(mod) -> List[dict]:
    """Every event counter this mod knows about: ``{name, title, source}``.

    Three sources, and the same event usually appears in more than one under a
    different casing — DaC's EDB tests ``adunaim_gondor_allied`` while
    historic_events.txt calls it ``{ADUNAIM_GONDOR_ALLIED_TITLE}``. So they are
    merged case-insensitively, keeping the spelling that has to be *typed* and
    the title that can be *read*:

    ``text``    a ``{NAME_TITLE}`` in text/historic_events.txt — an event with
                written copy, which is what a modder thinks of as "an event"
    ``script``  a ``set_event_counter NAME`` in the campaign scripts — the thing
                that actually moves the counter the EDB tests
    ``edb``     already used by a ``requires event_counter`` in this EDB, so it
                is certainly spelled the way the game expects
    """
    #: lower name -> row. Later sources overwrite `name`/`source`, never `title`.
    rows: Dict[str, dict] = {}

    def note(name: str, source: str, title: str = "") -> None:
        row = rows.setdefault(name.lower(), {"name": name, "title": "", "source": source})
        row["name"] = name
        row["source"] = source
        if title and not row["title"]:
            row["title"] = title

    text = _read_utf16(mod.data / "text" / "historic_events.txt")
    for key, value in re.findall(r"^\{([A-Za-z0-9_]+)_TITLE\}(.*)$", text, re.M):
        note(key, "text", value.strip())

    budget = _MAX_SCRIPT_BYTES
    for p in _script_files(mod):
        try:
            size = p.stat().st_size
        except OSError:
            continue
        if size > budget:
            continue
        budget -= size
        for name in re.findall(r"^\s*(?:set_event_counter|declare_counter)\s+(\S+)",
                               _read(p), re.M | re.I):
            note(name, "script")
        if budget <= 0:
            break

    for name in re.findall(r"\bevent_counter\s+(\S+)", mod.edb.to_text()):
        note(name, "edb")

    # EDB-used first (certainly valid), then scripted, then merely written about
    order = {"edb": 0, "script": 1, "text": 2}
    return sorted(rows.values(), key=lambda r: (order.get(r["source"], 9),
                                                r["name"].lower()))


def build(mod) -> dict:
    """Everything a ``requires`` clause may name, in one payload for the UI."""
    edb = mod.edb
    fac_cultures = mod.faction_cultures
    names = mod.faction_names
    used_factions: Set[str] = set()
    for bl in edb.buildings:
        for blk in bl.blocks:
            used_factions |= set(_clause_factions(blk.requires))
            for cap in blk.capabilities + blk.faction_capabilities:
                used_factions |= set(_clause_factions(cap.requires))

    culture_list = cultures(mod)
    culture_set = set(culture_list)
    # `factions { … }` accepts factions, cultures, and the keyword `all`. They
    # are listed separately so the checklist can group them, and `all` is called
    # out because ticking it makes every other tick meaningless.
    faction_rows = []
    for code in sorted(set(fac_cultures) | (used_factions - culture_set)):
        if code in culture_set or code == ALL:
            continue
        faction_rows.append({"code": code, "name": names.get(code, ""),
                             "culture": fac_cultures.get(code, ""),
                             "used": code in used_factions})
    culture_rows = [{"code": c, "name": names.get(c, ""),
                     "used": c in used_factions} for c in culture_list]

    levels = []
    for bl in edb.buildings:
        levels.append({"line": bl.name,
                       "levels": [b.name for b in bl.blocks]})

    # A hidden resource is only meaningful as "the regions that carry it", so the
    # picker shows those rather than a bare code name. Declared at the top of the
    # EDB, handed out per region in descr_regions.txt.
    region_rows = regions(mod, edb.hidden_resources)
    carriers: Dict[str, List[str]] = {}
    trade: Dict[str, List[str]] = {}
    # "which regions" is the answer you can act on, but the SETTLEMENT is what you
    # recognise on the campaign map, so both are carried per resource.
    where: Dict[str, List[dict]] = {}
    where_trade: Dict[str, List[dict]] = {}
    for r in region_rows:
        spot = {"region": r["name"], "settlement": r["settlement_name"],
                "faction": r["faction"]}
        for hr in r["hidden_resources"]:
            carriers.setdefault(hr, []).append(r["name"])
            where.setdefault(hr, []).append(spot)
        for res in r["resources"]:
            trade.setdefault(res, []).append(r["name"])
            where_trade.setdefault(res, []).append(spot)
    hidden = [{"code": hr, "regions": carriers.get(hr, []),
               "count": len(carriers.get(hr, [])),
               "places": where.get(hr, [])}
              for hr in edb.hidden_resources]
    # a `resource` condition is the same shape of question, so answer it too
    res_rows = [{"code": r, "regions": trade.get(r, []), "count": len(trade.get(r, [])),
                 "places": where_trade.get(r, [])}
                for r in sorted(set(resources(mod)) | set(trade))]
    # how many regions already meet a `region_religion X n` clause, per religion
    rel_names = religions(mod)
    rel_rows = []
    for rel in rel_names:
        vals = sorted((int(r["religions"][rel]) for r in region_rows
                       if r["religions"].get(rel, "").isdigit()), reverse=True)
        rel_rows.append({"code": rel, "regions": len([v for v in vals if v]),
                         "max": vals[0] if vals else 0})

    return {
        "factions": faction_rows,
        "cultures": culture_rows,
        "all_keyword": ALL,
        "religions": rel_names,
        "religion_rows": rel_rows,
        "hidden_resources": hidden,
        "regions": region_rows,
        "resources": res_rows,
        "events": event_counters(mod),
        "building_levels": levels,
    }


def _clause_factions(clause: str) -> List[str]:
    from .buildings import clause_factions
    return clause_factions(clause)
