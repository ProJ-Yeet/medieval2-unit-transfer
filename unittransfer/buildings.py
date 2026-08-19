"""Parser + surgical editor for ``data/export_descr_buildings.txt`` (the EDB).

The EDB is the settlement-building database. It is a brace-nested tree of
*building lines* — a group of buildings that upgrade into one another::

    building cannon
    {
        convert_to castle_cannon
        levels gunsmith cannon_maker cannon_foundry royal_arsenal
        {
            gunsmith city requires factions { northern_european, } and event_counter gunpowder_discovered 1
            {
                convert_to 0
                capability
                {
                    recruit_pool "NE Bombard"  1  0.4  3  0  requires factions { england, }
                    armour 1
                }
                material wooden
                construction 3
                cost 800
                settlement_min city
                upgrades
                {
                    cannon_maker
                }
            }
            ...
        }
        plugins
        {
        }
    }

So the nesting is::

    building <line>            -> BuildingLine
      levels <a> <b> <c>       -> the upgrade order
      { <level> ... }          -> LevelBlock, one per name in `levels`
          capability { ... }   -> Capability lines (recruit_pool, armour, …)
          faction_capability { ... }
          upgrades { ... }     -> which level(s) this one upgrades into
      plugins <names> { ... }  -> Plugin (a legacy sub-building, no capabilities)

Non-destructive by construction
-------------------------------
Same rule as :mod:`unittransfer.sounds`: the file is kept as its **verbatim
lines** and every edit is a splice of a known line range. That matters more here
than anywhere else in the tool — Divide and Conquer's EDB is 17.5k lines whose
``recruit_pool`` lines carry hand-written trailing comments
(``;ok old_pool=2 new_pool=2 (Orc infantry T4 @ T5)``), the indentation mixes
tabs and spaces line by line, and a re-emitted file would lose all of it. Nothing
outside the spliced range is ever rewritten.

Localisation lives in ``data/text/export_buildings.txt``, which is the same
UTF-16 keyed format as ``export_units.txt`` but with ``_desc`` / ``_desc_short``
suffixes instead of ``_descr`` / ``_descr_short``.
"""
from __future__ import annotations

import json
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import (config, edbvocab, edu as edu_mod, eop, localization,
               minorfiles, modeldb as modeldb_mod, stringsbin)
from .logutil import counted, file_op, fingerprint, log

#: EDB is plain 8-bit text, like the EDU — latin-1 round-trips every byte.
ENCODING = "latin-1"

#: Path of the EDB relative to a mod's ``data/`` folder.
EDB_REL = "export_descr_buildings.txt"

#: Path of the building localisation relative to ``data/``.
LOC_REL = "text/export_buildings.txt"

#: The settlement types a level line may be pinned to. Omitted = both.
SETTLEMENT_TYPES = ("city", "castle")

#: Settlement sizes, smallest first — what ``settlement_min`` names.
SETTLEMENT_LEVELS = ("village", "town", "large_town", "city", "large_city", "huge_city")

#: Scalar keys inside a level block (everything that is not a nested block).
LEVEL_SCALARS = ("convert_to", "material", "construction", "cost",
                 "settlement_min", "settlement_max", "year_available")

#: Nested blocks inside a level block.
LEVEL_BLOCKS = ("capability", "faction_capability", "upgrades")

#: Capability keywords that take a ``bonus <n>`` argument rather than a bare
#: number. Kept so the editor can offer the right widget (and so a value typed
#: into the number box is written back in the shape the game expects).
BONUS_CAPS = frozenset({
    "free_upkeep", "happiness_bonus", "law_bonus", "trade_base_income_bonus",
    "recruitment_cost_bonus_naval", "population_health_bonus",
    "population_growth_bonus", "population_loyalty_bonus", "retrain_cost_bonus",
    "religion_level", "heavy_cavalry_bonus", "construction_cost_bonus_stone",
    "construction_cost_bonus_wooden", "construction_time_bonus_defensive",
    "construction_time_bonus_other", "construction_time_bonus_religious",
    "income_bonus", "taxable_income_bonus", "trade_level_bonus",
    "recruits_exp_bonus", "recruits_morale_bonus",
    # from the reference tool's capability sheet — see merge/audit-edb.md
    "construction_cost_bonus_defensive", "construction_cost_bonus_military",
    "construction_cost_bonus_other", "construction_cost_bonus_religious",
    "construction_time_bonus_military", "construction_time_bonus_stone",
    "construction_time_bonus_wooden",
})

#: What each capability keyword does, for the editor's tooltips. From the TWC
#: guide "A Guide to the export_descr_buildings.txt file" (Dol Guldur) plus the
#: keywords the installed mods actually use.
CAP_HELP: Dict[str, str] = {
    "recruit_pool": "Lets this building train a unit. Values: starting points, points gained per turn, maximum points, starting experience (0-9).",
    "wall_level": "Settlement walls. 0 wooden palisade, 1 wooden wall, 2 stone, 3 large stone, 4 huge stone.",
    "tower_level": "Settlement towers. 1 arrow, 2 ballista, 3 cannon.",
    "gate_strength": "Gate strength. 1 reinforced, 2 iron.",
    "free_upkeep": "Supports this many militia units free of charge.",
    "happiness_bonus": "Public order through happiness, 5% per point.",
    "law_bonus": "Public order through law, 5% per point.",
    "population_loyalty_bonus": "Population loyalty, 5% per point.",
    "recruitment_slots": "Extra recruitment slots in the settlement.",
    "stage_races": "Allows horse races (ceremonial sacrifices in the Americas campaign).",
    "stage_games": "Allows ceremonial dances (Americas campaign).",
    "armour": "Upgrades armour like a blacksmith. 1 padded/leather, 2 light mail, 3 heavy mail, 4 partial plate, 5 full plate, 6 advanced plate.",
    "trade_base_income_bonus": "Bonus on tradeable goods.",
    "trade_level_bonus": "Raises the settlement's trade level.",
    "trade_fleet": "Adds this many trade fleets.",
    "recruitment_cost_bonus_naval": "Ships cost 10% less per point.",
    "navy_bonus": "Experience bonus for cannon-armed ships trained here.",
    "agent": "Lets the building train an agent: agent <type> <level>. Types: spy, assassin, diplomat, admiral, princess, merchant, priest, heretic, witch, inquisitor.",
    "agent_limit": "Raises the cap for an agent type: agent_limit <type> <n>.",
    "road_level": "Road level in the province. 0 dirt, 1 paved, 2 highways.",
    "farming_level": "Raises farm level in the province.",
    "mine_resource": "Mining income. Vanilla mines are 4, mining networks 7.",
    "population_health_bonus": "Settlement health, 5% per point.",
    "population_growth_bonus": "Population growth, 0.5% per point.",
    "retrain_cost_bonus": "Retraining costs 10% less per point.",
    "weapon_missile_gunpowder": "Upgrades the weapons of gun-armed troops.",
    "weapon_artillery_gunpowder": "Upgrades gunpowder artillery.",
    "weapon_missile_mechanical": "Upgrades bows and crossbows.",
    "weapon_artillery_mechanical": "Upgrades mechanical artillery.",
    "weapon_naval_gunpowder": "Upgrades naval guns.",
    "weapon_projectile": "Upgrades gun-armed troops and gunpowder artillery.",
    "weapon_melee_blade": "Upgrades the weapons of melee troops.",
    "religion_level": "Conversion bonus for this building's religion, 5% per point.",
    "amplify_religion_level": "Multiplies the effect of religious buildings.",
    "pope_approval": "Sends a message about the Pope's approval when built.",
    "pope_disapproval": "Makes the Pope unhappy with your faction.",
    "heavy_cavalry_bonus": "Experience bonus for knights trained here.",
    "cavalry_bonus": "Experience bonus for all cavalry trained here.",
    "archer_bonus": "Experience bonus for all archers trained here.",
    "gun_bonus": "Experience bonus for gunpowder-armed troops.",
    "recruits_exp_bonus": "Experience bonus for every unit trained here.",
    "recruits_morale_bonus": "Morale bonus for every unit trained here.",
    "income_bonus": "Flat income bonus for the settlement.",
    "taxable_income_bonus": "Raises the settlement's taxable income.",
    "construction_cost_bonus_stone": "Stone buildings cost 1% less per point.",
    "construction_cost_bonus_wooden": "Wooden buildings cost 1% less per point.",
    "construction_time_bonus_defensive": "Defensive buildings are built faster.",
    "construction_time_bonus_other": "Other buildings are built faster.",
    "construction_time_bonus_religious": "Religious buildings are built faster.",
    # ---- taken from the reference tool's capability sheet (Phase 12) ----
    # Eleven keywords the engine reads that no installed mod happens to use.
    # Adopted as FIELDS, which is the rule: a keyword is engine vocabulary, and a
    # list built only from three mods' habits would keep every mod to those
    # habits. The four whose own source says they do nothing say so here, because
    # a keyword that silently does nothing is worse than a missing one.
    "construction_cost_bonus_defensive": "Core (settlement) buildings cost 1% less per point.",
    "construction_cost_bonus_other": "Buildings that are neither core nor temple_ cost 1% less per point.",
    "construction_cost_bonus_religious": "temple_ buildings cost 1% less per point.",
    "construction_cost_bonus_military": "No effect — the engine reads it and does nothing with it.",
    "construction_time_bonus_stone": "Stone buildings are built 1% faster per point.",
    "construction_time_bonus_wooden": "Wooden buildings are built 1% faster per point.",
    "construction_time_bonus_military": "No effect — the engine reads it and does nothing with it.",
    "gate_defences": "Boiling oil over the gate. 0 none, 1 oil.",
    "upgrade_bodyguard": "Lets generals' bodyguards be upgraded after the Marian reforms event.",
    "weapon_melee_simple": "Upgrades the weapons of melee troops that use blunt weapons.",
    "fire_risk": "No effect — the fire disaster was cut before Rome shipped.",
}

#: ``keyword -> (group, argument range)`` for the capability picker: what to
#: file it under and what the engine will accept. Groups come from the reference
#: tool's spreadsheet, which is the one thing in its EDB half that our own list
#: had nothing like — a flat alphabetical list of 60 keywords is a list you scan,
#: not one you choose from. A keyword absent here falls under "Other".
CAP_META: Dict[str, Tuple[str, str]] = {
    "recruit_pool": ("Recruitment", ""),
    "agent": ("Agents", "level 0-2"),
    "agent_limit": ("Agents", "1+"),
    "wall_level": ("Defence", "0-4"),
    "tower_level": ("Defence", "1-3"),
    "gate_strength": ("Defence", "0-2"),
    "gate_defences": ("Defence", "0-1"),
    "free_upkeep": ("Recruitment", "1+"),
    "recruitment_slots": ("Recruitment", "1+"),
    "recruitment_cost_bonus_naval": ("Recruitment", "1-2"),
    "recruits_exp_bonus": ("Recruitment", "1-5"),
    "recruits_morale_bonus": ("Recruitment", "1+"),
    "retrain_cost_bonus": ("Recruitment", "0-1"),
    "upgrade_bodyguard": ("Recruitment", "1+"),
    "happiness_bonus": ("Population", "1-25"),
    "law_bonus": ("Population", "1-25"),
    "population_health_bonus": ("Population", "1-25"),
    "population_growth_bonus": ("Population", "1-25"),
    "population_loyalty_bonus": ("Population", "1-25"),
    "stage_games": ("Population", "1-3"),
    "stage_races": ("Population", "1-2"),
    "fire_risk": ("Population", ""),
    "income_bonus": ("Economy", "1+"),
    "taxable_income_bonus": ("Economy", "1+"),
    "trade_base_income_bonus": ("Economy", "1+"),
    "trade_level_bonus": ("Economy", "1+"),
    "trade_fleet": ("Economy", "1+"),
    "farming_level": ("Economy", "1-3"),
    "mine_resource": ("Economy", "1+"),
    "road_level": ("Economy", "0-3"),
    "religion_level": ("Religion", "1+"),
    "amplify_religion_level": ("Religion", "1+"),
    "pope_approval": ("Religion", "1+"),
    "pope_disapproval": ("Religion", "1+"),
    "construction_cost_bonus_stone": ("Construction", "1-100"),
    "construction_cost_bonus_wooden": ("Construction", "1-100"),
    "construction_cost_bonus_defensive": ("Construction", "1-100"),
    "construction_cost_bonus_other": ("Construction", "1-100"),
    "construction_cost_bonus_religious": ("Construction", "1-100"),
    "construction_cost_bonus_military": ("Construction", "1-100"),
    "construction_time_bonus_defensive": ("Construction", "1-100"),
    "construction_time_bonus_other": ("Construction", "1-100"),
    "construction_time_bonus_religious": ("Construction", "1-100"),
    "construction_time_bonus_stone": ("Construction", "1-100"),
    "construction_time_bonus_wooden": ("Construction", "1-100"),
    "construction_time_bonus_military": ("Construction", "1-100"),
    "armour": ("Unit upgrades", "1-6"),
    "navy_bonus": ("Unit upgrades", "0-9"),
    "archer_bonus": ("Unit upgrades", "0-9"),
    "cavalry_bonus": ("Unit upgrades", "0-9"),
    "heavy_cavalry_bonus": ("Unit upgrades", "0-9"),
    "gun_bonus": ("Unit upgrades", "0-9"),
    "weapon_melee_blade": ("Weapons", "0-9"),
    "weapon_melee_simple": ("Weapons", "0-9"),
    "weapon_missile_gunpowder": ("Weapons", "0-9"),
    "weapon_missile_mechanical": ("Weapons", "0-9"),
    "weapon_artillery_gunpowder": ("Weapons", "0-9"),
    "weapon_artillery_mechanical": ("Weapons", "0-9"),
    "weapon_naval_gunpowder": ("Weapons", "0-9"),
    "weapon_projectile": ("Weapons", "0-9"),
}

#: The order the picker shows the groups in, coarsest first.
CAP_GROUPS = ("Recruitment", "Unit upgrades", "Weapons", "Defence", "Agents",
              "Population", "Economy", "Religion", "Construction", "Other")

#: Vanilla's five religions — a last resort only. A building line's `religion`
#: names whatever ``descr_religions.txt`` defines, and a mod routinely replaces
#: the lot (DaC has ten, none of them `pagan`), so the real list comes from
#: :func:`unittransfer.minorfiles.religion_names` via the mod's own vocab.
VANILLA_RELIGIONS = ("catholic", "orthodox", "islam", "pagan", "heretic")

#: Materials a level may be built from.
MATERIALS = ("wooden", "stone")

_WS = re.compile(r"^(\s*)")


def _strip_comment(line: str) -> Tuple[str, str]:
    """Split an EDB line into (code, comment) — the comment keeps its ``;``."""
    i = line.find(";")
    if i < 0:
        return line, ""
    return line[:i], line[i:]


def _code(line: str) -> str:
    """The runnable part of a line, trimmed."""
    return _strip_comment(line)[0].strip()


def _indent(line: str) -> str:
    return _WS.match(line).group(1)


def _is_annotation(code: str) -> bool:
    """Is this line a modder's ``#`` note rather than something the engine reads?

    The EDB's comment marker is ``;``, so a line starting with ``#`` is not a
    comment as far as the format is concerned — but it is not a keyword either,
    and the engine evidently ignores it: Divide and Conquer ships **109** of
    them, all inside one capability block, grouping its ``recruit_pool`` lines by
    faction (``# GONDOR``, ``# ERIADOR``, …), and the mod runs.

    Reading one as a capability put ``#`` in the capability picker as if it were
    engine vocabulary. Nothing is skipped on *write*: this module splices known
    line ranges and never re-emits a block, so a line no parser claims survives
    a save untouched.
    """
    return code.startswith("#")


def _split_requires(text: str) -> Tuple[str, str]:
    """Split ``<args> requires <clause>`` into (args, clause).

    ``requires`` only ever appears as its own word, so a unit called
    "Requires Guard" in a quoted recruit_pool name can't be mistaken for it.
    """
    m = re.search(r"(?<![\w\"])requires\b", text)
    if not m:
        return text.strip(), ""
    return text[:m.start()].strip(), text[m.end():].strip()


# ---------------------------------------------------------------------------
# data model


@dataclass
class Capability:
    """One line inside a ``capability`` / ``faction_capability`` block."""
    keyword: str = ""
    args: str = ""                # everything between the keyword and `requires`
    requires: str = ""            # the clause after `requires` ('' = always)
    line: int = 0                 # index into EdbFile.lines
    indent: str = "\t\t\t\t"
    comment: str = ""             # trailing `;…` kept verbatim

    # ---- recruit_pool view ----
    @property
    def is_recruit(self) -> bool:
        return self.keyword == "recruit_pool"

    def pool(self) -> Optional["RecruitPool"]:
        return RecruitPool.parse(self) if self.is_recruit else None

    def text(self) -> str:
        """Re-emit this capability as a full line (with its line ending)."""
        body = self.keyword
        if self.args:
            body += " " + self.args
        if self.requires:
            body += "  requires " + self.requires
        tail = ("\t\t" + self.comment) if self.comment else ""
        return f"{self.indent}{body}{tail}\n"


@dataclass
class RecruitPool:
    """The parsed shape of a ``recruit_pool`` capability.

    ``recruit_pool "Unit Type"  <initial>  <per turn>  <max>  <exp>  [requires …]``
    """
    unit: str = ""
    initial: str = "1"
    per_turn: str = "0.5"
    maximum: str = "1"
    experience: str = "0"
    requires: str = ""
    quoted: bool = True

    @classmethod
    def parse(cls, cap: Capability) -> Optional["RecruitPool"]:
        args = cap.args.strip()
        if args.startswith('"'):
            end = args.find('"', 1)
            if end < 0:
                return None
            unit, rest, quoted = args[1:end], args[end + 1:], True
        else:                                   # unquoted single-word unit type
            parts = args.split(None, 1)
            if not parts:
                return None
            unit, rest, quoted = parts[0], (parts[1] if len(parts) > 1 else ""), False
        nums = rest.split()
        while len(nums) < 4:
            nums.append("0")
        return cls(unit=unit, initial=nums[0], per_turn=nums[1], maximum=nums[2],
                   experience=nums[3], requires=cap.requires, quoted=quoted)

    def to_args(self) -> str:
        name = f'"{self.unit}"' if (self.quoted or " " in self.unit) else self.unit
        return f"{name}  {self.initial}  {self.per_turn}  {self.maximum}  {self.experience}"


@dataclass
class LevelBlock:
    """One building inside a line — a ``gunsmith``, a ``stone_wall``…"""
    name: str = ""
    settlement: str = ""          # 'city' | 'castle' | '' (both)
    requires: str = ""
    header: int = 0               # index of the `<name> city requires …` line
    start: int = 0                # index of the opening `{`
    end: int = 0                  # index just past the closing `}`
    scalars: Dict[str, str] = field(default_factory=dict)      # key -> value
    scalar_lines: Dict[str, int] = field(default_factory=dict)  # key -> line index
    upgrades: List[str] = field(default_factory=list)
    upgrades_span: Tuple[int, int] = (0, 0)      # (open brace, close brace)
    capabilities: List[Capability] = field(default_factory=list)
    cap_span: Tuple[int, int] = (0, 0)
    faction_capabilities: List[Capability] = field(default_factory=list)
    fcap_span: Tuple[int, int] = (0, 0)

    @property
    def recruits(self) -> List[RecruitPool]:
        return [p for c in self.capabilities + self.faction_capabilities
                if (p := c.pool()) is not None]


@dataclass
class Plugin:
    """A ``plugins`` sub-building. No capability block; carries ``building_min``."""
    name: str = ""
    levels: List[str] = field(default_factory=list)
    start: int = 0
    end: int = 0


@dataclass
class BuildingLine:
    """A ``building <name> { … }`` block: one upgrade chain."""
    name: str = ""
    convert_to: str = ""
    religion: str = ""
    #: Other line-level keys some EDBs carry (``classification``, ``factions``).
    #: Kept so nothing is silently dropped from the view; not editable.
    extras: Dict[str, str] = field(default_factory=dict)
    levels: List[str] = field(default_factory=list)
    levels_line: int = 0
    start: int = 0                # index of the `building <name>` line
    end: int = 0                  # index just past the line's closing `}`
    blocks: List[LevelBlock] = field(default_factory=list)
    plugins: List[Plugin] = field(default_factory=list)
    plugins_span: Tuple[int, int] = (0, 0)

    def level(self, name: str) -> Optional[LevelBlock]:
        for b in self.blocks:
            if b.name == name:
                return b
        return None

    @property
    def settlement(self) -> str:
        """'city', 'castle' or 'both' — what kind of settlement this line is for."""
        kinds = {b.settlement for b in self.blocks}
        kinds.discard("")
        if kinds == {"city"}:
            return "city"
        if kinds == {"castle"}:
            return "castle"
        return "both"


@dataclass
class EdbFile:
    lines: List[str] = field(default_factory=list)          # verbatim, keepends
    hidden_resources: List[str] = field(default_factory=list)
    hidden_resources_line: int = -1
    buildings: List[BuildingLine] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_text(self) -> str:
        return "".join(self.lines)

    def get(self, name: str) -> Optional[BuildingLine]:
        for b in self.buildings:
            if b.name == name:
                return b
        return None

    def by_level(self) -> Dict[str, Tuple[BuildingLine, LevelBlock]]:
        """level name -> (its line, its block). Level names are unique in a valid EDB."""
        out: Dict[str, Tuple[BuildingLine, LevelBlock]] = {}
        for line in self.buildings:
            for blk in line.blocks:
                out.setdefault(blk.name, (line, blk))
        return out


# ---------------------------------------------------------------------------
# parsing


def parse_text(text: str) -> EdbFile:
    """Parse the EDB, keeping every line verbatim.

    A hand-rolled brace walker rather than a tokeniser: braces can share a line
    with code (``upgrades { }``), a level header can carry a ``requires`` clause
    with its own braces (``factions { england, }``) and comments can appear
    anywhere. Only *structural* braces — the ones that open a block on their own
    line, or trail a block keyword — change the nesting.
    """
    lines = text.splitlines(keepends=True)
    edb = EdbFile(lines=lines)

    i, n = 0, len(lines)
    while i < n:
        code = _code(lines[i])
        if not code:
            i += 1
            continue
        head = code.split(None, 1)
        kw = head[0]
        if kw == "hidden_resources":
            edb.hidden_resources = (head[1].split() if len(head) > 1 else [])
            edb.hidden_resources_line = i
            i += 1
            continue
        if kw == "building" and len(head) > 1:
            bl, i = _parse_building(edb, lines, i)
            if bl is not None:
                edb.buildings.append(bl)
            continue
        i += 1
    return edb


def parse_file(path: str | Path) -> EdbFile:
    p = Path(path)
    if not p.exists():
        return EdbFile()
    return parse_text(p.read_text(encoding=ENCODING))


def _open_brace(lines: List[str], i: int, n: int) -> int:
    """Index of the ``{`` that opens the block starting at/after line ``i``.

    Returns -1 if the next non-blank code line isn't a brace. Braces normally sit
    on their own line in the EDB but are tolerated trailing the keyword.
    """
    while i < n:
        code = _code(lines[i])
        if code:
            return i if code.startswith("{") or code.endswith("{") else -1
        i += 1
    return -1


def _matching_close(lines: List[str], open_idx: int, n: int) -> int:
    """Index of the ``}`` closing the block whose ``{`` is at ``open_idx``.

    Braces inside a ``requires factions { … }`` clause are skipped: such a clause
    always opens and closes on the same line, so a line whose braces balance can
    never change the depth.
    """
    depth = 0
    i = open_idx
    while i < n:
        code = _code(lines[i])
        if code:
            opens, closes = code.count("{"), code.count("}")
            if opens and opens == closes and i != open_idx:
                pass                      # inline `factions { … }` — no net change
            depth += opens - closes
            if depth <= 0 and i > open_idx:
                return i
            if depth <= 0 and i == open_idx and opens and closes:
                return i                  # `{ }` on one line
        i += 1
    return n - 1


def _parse_building(edb: EdbFile, lines: List[str], i: int) -> Tuple[Optional[BuildingLine], int]:
    n = len(lines)
    bl = BuildingLine(name=_code(lines[i]).split(None, 1)[1].strip(), start=i)
    open_idx = _open_brace(lines, i + 1, n)
    if open_idx < 0:
        edb.warnings.append(f"line {i + 1}: `building {bl.name}` has no opening brace")
        return None, i + 1
    close_idx = _matching_close(lines, open_idx, n)
    bl.end = close_idx + 1

    j = open_idx + 1
    while j < close_idx:
        code = _code(lines[j])
        if not code:
            j += 1
            continue
        parts = code.split(None, 1)
        kw, rest = parts[0], (parts[1].strip() if len(parts) > 1 else "")
        if kw == "convert_to":
            bl.convert_to = rest
        elif kw == "religion":
            bl.religion = rest
        elif kw in ("classification", "factions"):
            bl.extras[kw] = rest
        elif kw == "levels":
            # Divide and Conquer writes `levels gundabad, lorien, fennas, …` on at
            # least one line, so commas are separators here as well as spaces.
            bl.levels = [t for t in rest.replace(",", " ").split() if t]
            bl.levels_line = j
            lv_open = _open_brace(lines, j + 1, n)
            if lv_open >= 0:
                lv_close = _matching_close(lines, lv_open, n)
                _parse_levels(edb, lines, lv_open, lv_close, bl)
                j = lv_close + 1
                continue
        elif kw == "plugins":
            pg_open = _open_brace(lines, j + 1, n)
            if pg_open >= 0:
                pg_close = _matching_close(lines, pg_open, n)
                bl.plugins_span = (pg_open, pg_close)
                bl.plugins = _parse_plugins(lines, pg_open, pg_close)
                j = pg_close + 1
                continue
        j += 1
    return bl, close_idx + 1


def _parse_levels(edb: EdbFile, lines: List[str], open_idx: int, close_idx: int,
                  bl: BuildingLine) -> None:
    n = len(lines)
    j = open_idx + 1
    while j < close_idx:
        code = _code(lines[j])
        if not code or code in ("{", "}"):
            j += 1
            continue
        blk = _parse_level_header(code, j)
        lv_open = _open_brace(lines, j + 1, n)
        if lv_open < 0:
            edb.warnings.append(f"line {j + 1}: level `{blk.name}` has no opening brace")
            j += 1
            continue
        lv_close = _matching_close(lines, lv_open, n)
        blk.start, blk.end = lv_open, lv_close + 1
        _parse_level_body(lines, lv_open, lv_close, blk)
        bl.blocks.append(blk)
        j = lv_close + 1


def _parse_level_header(code: str, idx: int) -> LevelBlock:
    """``<name> [city|castle] [requires <clause>]``."""
    args, requires = _split_requires(code)
    toks = args.split()
    name = toks[0] if toks else ""
    settlement = ""
    if len(toks) > 1 and toks[1] in SETTLEMENT_TYPES:
        settlement = toks[1]
    return LevelBlock(name=name, settlement=settlement, requires=requires, header=idx)


def _parse_level_body(lines: List[str], open_idx: int, close_idx: int,
                      blk: LevelBlock) -> None:
    n = len(lines)
    j = open_idx + 1
    while j < close_idx:
        code = _code(lines[j])
        if not code or code in ("{", "}") or _is_annotation(code):
            j += 1
            continue
        parts = code.split(None, 1)
        kw, rest = parts[0], (parts[1].strip() if len(parts) > 1 else "")
        if kw in LEVEL_BLOCKS:
            sub_open = _open_brace(lines, j + 1, n)
            if sub_open < 0:
                j += 1
                continue
            sub_close = _matching_close(lines, sub_open, n)
            if kw == "upgrades":
                blk.upgrades_span = (sub_open, sub_close)
                blk.upgrades = [c for k in range(sub_open + 1, sub_close)
                                if (c := _code(lines[k])) and c not in ("{", "}")
                                and not _is_annotation(c)]
            else:
                caps = _parse_capabilities(lines, sub_open, sub_close)
                if kw == "capability":
                    blk.cap_span, blk.capabilities = (sub_open, sub_close), caps
                else:
                    blk.fcap_span, blk.faction_capabilities = (sub_open, sub_close), caps
            j = sub_close + 1
            continue
        blk.scalars[kw] = rest
        blk.scalar_lines[kw] = j
        j += 1


def _parse_capabilities(lines: List[str], open_idx: int, close_idx: int) -> List[Capability]:
    caps: List[Capability] = []
    for j in range(open_idx + 1, close_idx):
        raw = lines[j]
        code, comment = _strip_comment(raw)
        stripped = code.strip()
        if not stripped or stripped in ("{", "}") or _is_annotation(stripped):
            continue
        parts = stripped.split(None, 1)
        args, requires = _split_requires(parts[1] if len(parts) > 1 else "")
        caps.append(Capability(keyword=parts[0], args=args, requires=requires,
                               line=j, indent=_indent(raw), comment=comment.strip()))
    return caps


def _parse_plugins(lines: List[str], open_idx: int, close_idx: int) -> List[Plugin]:
    """Plugins are shaped like building lines but have no capability block.

    Only the outline is parsed — the tool doesn't edit plugins, it just shows a
    line that has them so nothing looks missing.
    """
    out: List[Plugin] = []
    n = len(lines)
    j = open_idx + 1
    while j < close_idx:
        code = _code(lines[j])
        if not code or code in ("{", "}"):
            j += 1
            continue
        name = code.split()[0]
        p_open = _open_brace(lines, j + 1, n)
        if p_open < 0:
            j += 1
            continue
        p_close = _matching_close(lines, p_open, n)
        levels: List[str] = []
        for k in range(p_open + 1, p_close):
            c = _code(lines[k])
            if c.startswith("levels "):
                levels = c.split()[1:]
                break
        out.append(Plugin(name=name, levels=levels, start=j, end=p_close + 1))
        j = p_close + 1
    return out


# ---------------------------------------------------------------------------
# icons + cultures


#: Building icons live per culture: ``data/ui/<culture>/buildings/#<culture>_<level>.tga``
#: is the small (build-browser) icon and ``…_constructed.tga`` the big one shown
#: once it stands. ``.dds`` is accepted too — some mods ship that instead, and
#: ``.webp`` is what the packed vanilla fallback stores.
ICON_EXTS = (".tga", ".dds", ".png", ".webp")

#: Names inside a packed vanilla art folder — see ``tools/pack_vanilla_ui.py``.
MANIFEST_NAME = "manifest.json"
PACK_ART_DIR = "art"


def icon_stem(culture: str, level: str, kind: str = "small") -> str:
    """``#<culture>_<level>`` (+ ``_constructed`` for the big icon)."""
    suffix = "_constructed" if kind in ("large", "big", "constructed") else ""
    return f"#{culture}_{level}{suffix}"


#: folder -> (mtime, {lower-case stem: path}). Building art folders hold 300-700
#: files and every level asks about every culture, so a per-request `iterdir()`
#: per miss turned one detail view into tens of thousands of directory reads.
_DIR_INDEX: Dict[str, Tuple[int, Dict[str, Path]]] = {}


def _index(folder: Path) -> Dict[str, Path]:
    key = str(folder)
    try:
        mtime = folder.stat().st_mtime_ns
    except OSError:
        _DIR_INDEX.pop(key, None)
        return {}
    cached = _DIR_INDEX.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    out: Dict[str, Path] = {}
    try:
        for p in folder.iterdir():
            if p.suffix.lower() in ICON_EXTS:
                out.setdefault(p.stem.lower(), p)
    except OSError:
        return {}
    _DIR_INDEX[key] = (mtime, out)
    return out


def _lookup(folder: Path, stem: str) -> Optional[Path]:
    """Find ``<stem>.<tga|dds|png>`` in ``folder``, case-insensitively."""
    return _index(folder).get(stem.lower())


class VanillaUi:
    """The vanilla building art a mod's missing icons fall back to.

    Two shapes are accepted, because one of them is what anyone gets by
    unpacking the game themselves:

    ``packed``  a folder holding ``manifest.json`` + ``art/`` — deduplicated
                lossless WebP, ~6x smaller, what this repo ships
    ``raw``     ``<culture>/buildings/#<culture>_<level>.tga``, i.e. the .pack
                files' own layout, straight out of any unpacker

    Both answer the same question: given a culture and a file stem, where is the
    picture? Instances are cached per path+mtime by :func:`vanilla_ui`.
    """

    def __init__(self, root: Path):
        self.root = Path(root)
        self.manifest: Dict[str, str] = {}
        self.packed = False
        mf = self.root / MANIFEST_NAME
        if mf.is_file():
            try:
                self.manifest = json.loads(mf.read_text(encoding="utf-8")).get("entries", {})
                self.packed = True
            except (OSError, ValueError):
                self.manifest = {}
        self._cultures: Optional[List[str]] = None

    @property
    def cultures(self) -> List[str]:
        # Memoised: the buildings overview asks which cultures exist thousands of
        # times (once per line per culture per icon size) and a directory walk
        # each time was most of the request.
        if self._cultures is None:
            if self.packed:
                self._cultures = sorted({k.split("/", 1)[0] for k in self.manifest})
            else:
                try:
                    self._cultures = sorted(p.name for p in self.root.iterdir()
                                            if p.is_dir() and (p / "buildings").is_dir())
                except OSError:
                    self._cultures = []
        return self._cultures

    def lookup(self, culture: str, stem: str) -> Optional[Path]:
        if self.packed:
            rel = self.manifest.get(f"{culture}/{stem}")
            if rel is None:                       # manifests are written lower-case-safe
                rel = self.manifest.get(f"{culture}/{stem}".lower())
            if rel is None:
                return None
            p = self.root / PACK_ART_DIR / rel
            return p if p.exists() else None
        return _lookup(self.root / culture / "buildings", stem)


_VANILLA_CACHE: Dict[str, Optional["VanillaUi"]] = {}


def vanilla_ui(root) -> Optional["VanillaUi"]:
    """A cached :class:`VanillaUi` for ``root``, or None when there isn't one.

    Cached by path for the life of the process. This art is a static download,
    not something a mod edits under us — and it is asked about thousands of times
    per page, so re-stat'ing it each time showed up as most of a request.
    """
    if not root:
        return None
    key = str(root)
    if key in _VANILLA_CACHE:
        return _VANILLA_CACHE[key]
    p = Path(root)
    ui = VanillaUi(p) if p.is_dir() else None
    _VANILLA_CACHE[key] = ui
    return ui


def find_icon(mod, culture: str, level: str, kind: str = "small",
              vanilla_root: Optional[Path] = None) -> Tuple[Optional[Path], str]:
    """Locate a building icon, falling back to unpacked vanilla art.

    Mods routinely ship only the icons they changed and let the game fall back to
    the vanilla ones for everything else, so a missing file in the mod is normal
    rather than a fault. Search order, and the ``source`` returned with the hit:

    ``mod``      the mod's own ``data/ui/<culture>/buildings``
    ``vanilla``  the same culture in the unpacked vanilla UI
    ``vanilla*`` any vanilla culture (a mod culture like ``gondor`` has no vanilla
                 namesake, so this is the only way it can borrow one)
    ``""``       nothing found — the caller paints the placeholder
    """
    stem = icon_stem(culture, level, kind)
    hit = _lookup(mod.data / "ui" / culture / "buildings", stem)
    if hit is not None:
        return hit, "mod"
    van = vanilla_ui(vanilla_root)
    if van is None:
        return None, ""
    hit = van.lookup(culture, stem)
    if hit is not None:
        return hit, "vanilla"
    for other in van.cultures:
        if other == culture:
            continue
        hit = van.lookup(other, icon_stem(other, level, kind))
        if hit is not None:
            return hit, "vanilla"
    return None, ""


def cultures_of(mod) -> List[str]:
    """Culture folders under ``data/ui`` that actually hold building icons."""
    ui = mod.data / "ui"
    if not ui.is_dir():
        return []
    return sorted(p.name for p in ui.iterdir()
                  if p.is_dir() and (p / "buildings").is_dir())


def faction_cultures(mod) -> Dict[str, str]:
    """faction slot -> culture — :mod:`unittransfer.factions` is the source.

    Building icons are picked by *culture*, but a level's ``requires`` clause
    names *factions*, so this is what lets the browser show the right art for
    "the buildings England can build". It used to read the file with a regex of
    its own, which got the head line's comma modifier right by accident
    (``faction egypt, spawned_on_event``) and would have been the fifth parser of
    a file the toolkit now edits.
    """
    from . import factions as fac
    return fac.faction_cultures(mod)


_FACTIONS_CLAUSE = re.compile(r"factions\s*\{([^}]*)\}", re.I)


def clause_factions(clause: str) -> List[str]:
    """Every faction/culture named in a ``requires`` clause's ``factions { … }``."""
    out: List[str] = []
    for m in _FACTIONS_CLAUSE.finditer(clause or ""):
        for tok in m.group(1).split(","):
            tok = tok.strip()
            if tok:
                out.append(tok)
    return list(dict.fromkeys(out))


# ---------------------------------------------------------------------------
# how many units one building can offer one faction

#: Most units M2TW will show in a settlement's recruitment panel for one
#: building. Past this the panel overflows and the game can crash on opening it,
#: which is the sort of failure that only shows up on the one save where enough
#: conditions have lined up at once — hence the check.
RECRUIT_LIMIT = 32


def _pool_factions(requires: str, faction_cultures: Dict[str, str]) -> set:
    """Which factions a pool's clause admits, cultures and ``all`` expanded.

    A pool with no ``factions { }`` at all is open to everyone, which is the
    case that quietly makes a building the same size for every faction.
    """
    every = set(faction_cultures)
    named = clause_factions(requires)
    if not named:
        return set(every)
    cultures = set(faction_cultures.values())
    out: set = set()
    for tok in named:
        low = tok.lower()
        if low == "all":
            return set(every)
        if low in cultures:
            out |= {f for f, c in faction_cultures.items() if c == low}
        else:
            out.add(tok)
    return out


def _is_gated(requires: str) -> bool:
    """True when a clause says anything beyond which factions it applies to."""
    return any(c.kind != "factions" for c in parse_clause(requires or ""))


def recruitment_pressure(blk: "LevelBlock", faction_cultures: Dict[str, str],
                         limit: int = RECRUIT_LIMIT) -> List[dict]:
    """How many units one level could offer each faction, worst case first.

    Two numbers per faction, because they answer different questions:

    ``always``
        pools this faction gets with no further condition at all. If this is
        over the limit the building is already broken, on every save.
    ``most``
        every pool whose ``factions { }`` admits it, taking every other
        condition — event counters, hidden resources, settlement size — as
        satisfied at the same time. This is an upper bound, and deliberately so:
        working out which of a mod's conditions can truly hold at once is not
        decidable from the EDB alone, and a warning that under-counts is worse
        than one that occasionally over-counts.

    Only factions at or over ``limit`` are returned.
    """
    pools = [c for c in blk.capabilities + blk.faction_capabilities
             if c.keyword == "recruit_pool"]
    most: Dict[str, int] = {}
    always: Dict[str, int] = {}
    for cap in pools:
        gated = _is_gated(cap.requires)
        for f in _pool_factions(cap.requires, faction_cultures):
            most[f] = most.get(f, 0) + 1
            if not gated:
                always[f] = always.get(f, 0) + 1
    rows = [{"faction": f, "most": n, "always": always.get(f, 0), "limit": limit}
            for f, n in most.items() if n > limit or always.get(f, 0) > limit]
    rows.sort(key=lambda r: (-r["always"], -r["most"], r["faction"]))
    return rows


# ---------------------------------------------------------------------------
# `requires` clauses, as structure


#: How many arguments each condition takes after its keyword, and what they mean.
#: Anything not here is kept as raw text — the EDB has a few malformed clauses in
#: the wild (``requires woe_unlock_siege.``) and a typo must not become a crash.
CONDITION_ARGS: Dict[str, Tuple[str, ...]] = {
    "factions": ("factions",),                       # a { a, b, } list
    "hidden_resource": ("hidden_resource",),
    "resource": ("resource",),
    "event_counter": ("event", "value"),
    "region_religion": ("religion", "percent"),
    "building_present_min_level": ("building", "level"),
    "building_present": ("building",),
    "settlement_min": ("settlement",),
    "is_players_turn": (),
    "market_level": ("value",),
}

#: What each condition means, for the editor's tooltips.
CONDITION_HELP = {
    "factions": "Only these factions (or whole cultures) can build it. `all` means everyone.",
    "hidden_resource": "The region must carry this hidden resource — the list at the top of the EDB.",
    "resource": "The region must produce this trade resource.",
    "event_counter": "An event counter must have this value. 1 = after the event, 0 = before.",
    "region_religion": "At least this percentage of the region must follow the religion.",
    "building_present_min_level": "Another building line must be present, at this level or better.",
    "building_present": "Another building line must be present at any level.",
    "settlement_min": "The settlement must be at least this size.",
}

_JOIN_SPLIT = re.compile(r"\s+(and|or)\s+", re.I)


@dataclass
class Condition:
    """One term of a ``requires`` clause.

    ``join`` is the word that attached it to the term before it ('' for the
    first). M2TW evaluates a clause strictly left to right with no precedence, so
    keeping the terms in order with their own joiner is the whole of the grammar.
    """
    join: str = ""                # 'and' | 'or' | ''
    negate: bool = False
    kind: str = "raw"
    values: List[str] = field(default_factory=list)
    raw: str = ""                 # the term verbatim, for anything unparsed

    def text(self) -> str:
        """This term on its own, without its joiner."""
        body = self.raw if self.kind == "raw" else self._body()
        return ("not " + body) if self.negate else body

    def _body(self) -> str:
        if self.kind == "factions":
            inner = "".join(f" {v}," for v in self.values)
            return "factions {" + inner + " }"
        return " ".join([self.kind] + [v for v in self.values if v != ""])


def parse_clause(clause: str) -> List[Condition]:
    """Split a ``requires`` clause into its terms.

    Braces only ever appear inside a ``factions { … }`` list, and such a list is
    always on one line, so the split can simply ignore any ``and``/``or`` that
    falls between braces.
    """
    clause = (clause or "").strip()
    if not clause:
        return []
    # mask the brace contents so a faction called `and` couldn't split the clause
    masked = []
    depth = 0
    for ch in clause:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
        masked.append("\x00" if (depth and ch not in "{}") else ch)
    masked = "".join(masked)

    # Spans on the masked copy index the real string exactly (masking is 1:1), so
    # the terms are sliced out rather than reassembled — the joiners are padded
    # with runs of whitespace in the wild and any length arithmetic gets it wrong.
    out: List[Condition] = []
    pos, join = 0, ""
    for m in _JOIN_SPLIT.finditer(masked):
        term = clause[pos:m.start()].strip()
        if term:
            out.append(_parse_term(term, join if out else ""))
        join = m.group(1).lower()
        pos = m.end()
    term = clause[pos:].strip()
    if term:
        out.append(_parse_term(term, join if out else ""))
    return out


def _parse_term(term: str, join: str) -> Condition:
    negate = False
    body = term
    m = re.match(r"(?i)^not\s+(.*)$", body)
    if m:
        negate, body = True, m.group(1).strip()
    head = body.split(None, 1)[0].lower() if body.split() else ""
    if head == "factions":
        return Condition(join=join, negate=negate, kind="factions",
                         values=clause_factions(body), raw=term)
    spec = CONDITION_ARGS.get(head)
    if spec is None:
        return Condition(join=join, negate=negate, kind="raw", raw=body)
    rest = body.split()[1:]
    if len(rest) != len(spec):
        # right keyword, wrong number of arguments — keep it verbatim rather than
        # silently dropping or inventing one
        return Condition(join=join, negate=negate, kind="raw", raw=body)
    return Condition(join=join, negate=negate, kind=head, values=rest, raw=term)


def clause_text(conditions: List[Condition]) -> str:
    """Re-emit a whole clause from its terms."""
    out = ""
    for i, c in enumerate(conditions):
        if i:
            out += f" {c.join or 'and'} "
        out += c.text()
    return out.strip()


def conditions_from_dicts(raw) -> List[Condition]:
    """The UI's JSON shape -> :class:`Condition` objects."""
    out: List[Condition] = []
    for d in (raw or []):
        kind = str(d.get("kind") or "raw")
        out.append(Condition(join=str(d.get("join") or ""),
                             negate=bool(d.get("negate")),
                             kind=kind,
                             values=[str(v) for v in (d.get("values") or [])],
                             raw=str(d.get("raw") or "")))
    return out


def condition_payload(c: Condition) -> dict:
    return {"join": c.join, "negate": c.negate, "kind": c.kind,
            "values": list(c.values), "raw": c.raw, "text": c.text()}


def clause_payload(clause: str) -> List[dict]:
    return [condition_payload(c) for c in parse_clause(clause)]


# ---------------------------------------------------------------------------
# editing — every operation is a splice of known line indices


@dataclass
class LineEdit:
    """A pending change to one contiguous run of lines.

    ``start``/``end`` are indices into the *original* file (``end`` exclusive);
    ``text`` replaces them. Deletions carry an empty ``text``. All edits for one
    apply are collected, sorted and spliced back-to-front, so no index shifts.
    """
    start: int
    end: int
    text: str = ""
    note: str = ""


def splice(lines: List[str], edits: List[LineEdit]) -> str:
    """Apply every edit to ``lines`` and return the new file text."""
    out = list(lines)
    for e in sorted(edits, key=lambda x: x.start, reverse=True):
        out[e.start:e.end] = ([e.text] if e.text else [])
    return "".join(out)


def _insert_before(lines: List[str], idx: int, text: str) -> LineEdit:
    """An edit that puts ``text`` immediately above line ``idx``.

    Written as a *replacement* of line ``idx`` with ``text + that line`` rather
    than a zero-width insert, so two edits that both target ``idx`` can't be
    applied twice over — the splice is index-stable either way, and a pure insert
    that also re-emitted the anchor line silently duplicated it.
    """
    return LineEdit(idx, idx + 1, text + lines[idx])


def _rewrite_header(blk: LevelBlock, lines: List[str], settlement: str,
                    requires: str) -> str:
    raw = lines[blk.header]
    _, comment = _strip_comment(raw)
    body = blk.name
    if settlement:
        body += " " + settlement
    if requires:
        body += " requires " + requires
    tail = ("\t\t" + comment.strip()) if comment.strip() else ""
    return f"{_indent(raw)}{body}{tail}\n"


def _scalar_line(indent: str, key: str, value: str, comment: str = "") -> str:
    tail = ("\t\t" + comment) if comment else ""
    return f"{indent}{key} {value}{tail}\n"


def _norm(text: str) -> str:
    """Collapse runs of whitespace — for comparing two capabilities by meaning."""
    return " ".join((text or "").split())


def _same_capability(old: Capability, new: Capability) -> bool:
    """True when ``new`` says exactly what ``old`` already says.

    Compared field by field rather than as text: the EDB lines up its
    ``recruit_pool`` numbers with runs of spaces and tabs, and an editor that
    re-emits ``1 0.135 3 0`` with a different gap has changed nothing. Without
    this, opening a level and saving would rewrite — and re-space — every one of
    its several hundred pool lines.
    """
    return (old.keyword == new.keyword
            and _norm(old.args) == _norm(new.args)
            and _norm(old.requires) == _norm(new.requires))


def _cap_indent(blk: LevelBlock, lines: List[str], span: Tuple[int, int]) -> str:
    """The indent to give a freshly added capability line."""
    caps = blk.capabilities if span == blk.cap_span else blk.faction_capabilities
    if caps:
        return caps[0].indent
    return _indent(lines[span[0]]) + "\t"


def plan_level_edit(edb: EdbFile, bl: BuildingLine, blk: LevelBlock,
                    changes: dict) -> Tuple[List[LineEdit], List[str], List[str]]:
    """Turn one level's edit payload into splices.

    ``changes`` mirrors what the UI sends::

        {"settlement": "city", "requires": "factions { england, }",
         "scalars": {"cost": "800", "construction": "3", …},
         "upgrades": ["cannon_maker"],
         "capabilities": [{"keyword": …, "args": …, "requires": …,
                           "line": <original index or null for a new one>,
                           "delete": false}, …]}

    Returns (edits, changed descriptions, warnings).
    """
    lines = edb.lines
    edits: List[LineEdit] = []
    notes: List[str] = []
    warn: List[str] = []

    # ---- header: settlement type + requires clause ----
    if "settlement" in changes or "requires" in changes or "conditions" in changes:
        settlement = str(changes.get("settlement", blk.settlement) or "").strip()
        if "conditions" in changes:
            requires = clause_text(conditions_from_dicts(changes["conditions"]))
        else:
            requires = str(changes.get("requires", blk.requires) or "").strip()
        if settlement and settlement not in SETTLEMENT_TYPES:
            warn.append(f"{blk.name}: '{settlement}' is not a settlement type — ignored")
            settlement = blk.settlement
        # whitespace-only differences are not edits: the clause editor re-emits
        # with one space where the file often has two or three
        if settlement != blk.settlement or _norm(requires) != _norm(blk.requires):
            edits.append(LineEdit(blk.header, blk.header + 1,
                                  _rewrite_header(blk, lines, settlement, requires)))
            if settlement != blk.settlement:
                notes.append(f"{blk.name}: settlement {blk.settlement or 'both'} -> "
                             f"{settlement or 'both'}")
            if _norm(requires) != _norm(blk.requires):
                notes.append(f"{blk.name}: requires -> {requires or '(none)'}")

    # ---- scalars: cost / construction / material / settlement_min / convert_to ----
    for key, value in (changes.get("scalars") or {}).items():
        value = str(value).strip()
        old = blk.scalars.get(key, "")
        if value == old:
            continue
        idx = blk.scalar_lines.get(key)
        if idx is None:
            if not value:
                continue
            # Insert a missing scalar just before the closing brace, at the same
            # indent as the level's other scalars.
            anchor = min(blk.scalar_lines.values()) if blk.scalar_lines else blk.end - 1
            edits.append(_insert_before(lines, blk.end - 1,
                                        _scalar_line(_indent(lines[anchor]), key, value)))
            notes.append(f"{blk.name}: {key} added = {value}")
            continue
        if not value:
            edits.append(LineEdit(idx, idx + 1, ""))
            notes.append(f"{blk.name}: {key} removed (was {old})")
            continue
        _, comment = _strip_comment(lines[idx])
        edits.append(LineEdit(idx, idx + 1,
                              _scalar_line(_indent(lines[idx]), key, value,
                                           comment.strip())))
        notes.append(f"{blk.name}: {key} {old or '(unset)'} -> {value}")

    # ---- upgrades list ----
    if "upgrades" in changes:
        want = [u.strip() for u in (changes.get("upgrades") or []) if str(u).strip()]
        if want != blk.upgrades and blk.upgrades_span != (0, 0):
            o, c = blk.upgrades_span
            indent = (_indent(lines[o + 1]) if c > o + 1 else _indent(lines[o]) + "\t")
            body = "".join(f"{indent}{u}\n" for u in want)
            edits.append(LineEdit(o + 1, c, body))
            notes.append(f"{blk.name}: upgrades {', '.join(blk.upgrades) or '(none)'} "
                         f"-> {', '.join(want) or '(none)'}")

    # ---- capability lines ----
    cap_ops = changes.get("capabilities")
    if cap_ops is not None:
        edits += _plan_capabilities(edb, blk, cap_ops, notes, warn, faction=False)
    fcap_ops = changes.get("faction_capabilities")
    if fcap_ops is not None:
        edits += _plan_capabilities(edb, blk, fcap_ops, notes, warn, faction=True)
    return edits, notes, warn


def _plan_capabilities(edb: EdbFile, blk: LevelBlock, ops: List[dict],
                       notes: List[str], warn: List[str],
                       faction: bool) -> List[LineEdit]:
    """Rewrite / delete / append capability lines, one splice each.

    Existing lines are edited *in place* so their neighbours — including the
    hand-written trailing comments DaC's EDB is full of — stay byte-exact. New
    lines are appended just above the block's closing brace.
    """
    lines = edb.lines
    span = blk.fcap_span if faction else blk.cap_span
    existing = {c.line: c for c in
                (blk.faction_capabilities if faction else blk.capabilities)}
    label = "faction_capability" if faction else "capability"
    edits: List[LineEdit] = []
    additions: List[str] = []

    if span == (0, 0):
        if any(not o.get("delete") for o in ops):
            warn.append(f"{blk.name}: no {label} block to write into")
        return edits

    for op in ops:
        idx = op.get("line")
        keyword = str(op.get("keyword") or "").strip()
        args = str(op.get("args") or "").strip()
        # a row whose clause was edited structurally sends `conditions`; one that
        # was left alone sends its original `requires` text, so an untouched
        # clause is never re-emitted (and never quietly tidied)
        requires = (clause_text(conditions_from_dicts(op["conditions"]))
                    if "conditions" in op else str(op.get("requires") or "").strip())
        if idx is None:                                   # a new capability
            if op.get("delete") or not keyword:
                continue
            cap = Capability(keyword=keyword, args=args, requires=requires,
                             indent=_cap_indent(blk, lines, span))
            additions.append(cap.text())
            notes.append(f"{blk.name}: + {keyword} {args}".rstrip())
            continue
        cap = existing.get(int(idx))
        if cap is None:
            warn.append(f"{blk.name}: capability line {idx} is no longer there — skipped")
            continue
        if op.get("delete"):
            edits.append(LineEdit(cap.line, cap.line + 1, ""))
            notes.append(f"{blk.name}: - {cap.keyword} {cap.args}".rstrip())
            continue
        new = Capability(keyword=keyword or cap.keyword, args=args,
                         requires=requires, indent=cap.indent, comment=cap.comment)
        if _same_capability(cap, new):
            continue
        edits.append(LineEdit(cap.line, cap.line + 1, new.text()))
        # Report whichever half actually moved: rewriting only a pool's `requires`
        # is the commonest edit here, and a note that repeated the unchanged
        # numbers on both sides read as "nothing happened".
        if _norm(cap.args) == _norm(new.args) and cap.keyword == new.keyword:
            notes.append(f"{blk.name}: {cap.keyword} {cap.args} — requires "
                         f"{cap.requires or '(none)'} -> {new.requires or '(none)'}")
        else:
            what = f"{cap.keyword} {cap.args} -> {new.keyword} {new.args}".rstrip()
            if _norm(cap.requires) != _norm(new.requires):
                what += f" (requires -> {new.requires or 'none'})"
            notes.append(f"{blk.name}: {what}")

    if additions:
        edits.append(_insert_before(lines, span[1], "".join(additions)))
    return edits


# ---------------------------------------------------------------------------
# "can this faction actually field this unit?"


def _expand_factions(mod, names) -> List[str]:
    """Turn a ``factions { … }`` list into the real factions it covers.

    The list accepts three things and only one of them is a faction: ``all``
    means every faction, a culture name means every faction of that culture, and
    anything else is a faction. Ownership is per faction, so a culture has to be
    expanded before it can be checked.
    """
    fac_cultures = mod.faction_cultures
    everyone = [f for f in fac_cultures if f != "slave"]
    out: List[str] = []
    for name in names or []:
        low = (name or "").strip().lower()
        if not low:
            continue
        if low == edbvocab.ALL:
            return list(dict.fromkeys(everyone))
        members = [f for f, c in fac_cultures.items() if c == low and f != "slave"]
        out += members or [low]
    return list(dict.fromkeys(out))


def ownership_report(mod, checks) -> List[dict]:
    """For each ``{unit, factions}``, who can't actually field it and why.

    A ``recruit_pool`` naming a faction is not enough on its own. The unit also
    has to list that faction in its EDU ``ownership`` — otherwise the building
    trains nothing for them — and its battle model needs a texture record for
    the faction, or the soldiers turn up untextured. Both are quiet failures in
    game, so they are worth saying out loud here.
    """
    by_type = {u.type.lower(): u for u in mod.edu.units}
    out: List[dict] = []
    for chk in (checks or []):
        name = str(chk.get("unit") or "")
        unit = by_type.get(name.lower())
        wanted = _expand_factions(mod, chk.get("factions"))
        row = {"unit": name, "factions": wanted, "missing_ownership": [],
               "missing_textures": [], "entries": [], "known": unit is not None}
        if unit is None or not wanted:
            out.append(row)
            continue
        owned = {f.lower() for f in unit.ownership}
        row["ownership"] = list(unit.ownership)
        row["missing_ownership"] = [f for f in wanted if f.lower() not in owned]

        # the battle model's per-faction textures: `slave` is the catch-all a
        # faction with no record of its own falls back to, so an entry that has
        # it can never be untextured
        for entry_name in _unit_entries(unit):
            entry = mod.modeldb.get(entry_name)
            if entry is None:
                continue
            have = {f.lower() for f in entry.factions()}
            row["entries"].append(entry_name)
            if "slave" in have:
                continue
            row["missing_textures"] += [f for f in wanted if f.lower() not in have]
        row["missing_textures"] = list(dict.fromkeys(row["missing_textures"]))
        out.append(row)
    return out


def _unit_entries(unit) -> List[str]:
    """The battle-model entries a unit's own soldiers use (not mount or crew)."""
    names = [unit.soldier_model] + list(unit.armour_ug_models)
    return [n for n in dict.fromkeys(names) if n]


def _plan_ownership(mod, plan: "BuildingPlan", checks) -> None:
    """Stage the EDU / modeldb writes that make those factions able to field it."""
    report = ownership_report(mod, checks)
    edu_blocks: Dict[str, str] = {}
    entry_facs: Dict[str, List[str]] = {}
    for row in report:
        if not row["known"]:
            plan.warnings.append(
                f"{row['unit']}: named by a recruit pool but not a unit in {mod.name} "
                f"— ownership not changed")
            continue
        unit = next(u for u in mod.edu.units if u.type.lower() == row["unit"].lower())
        if row["missing_ownership"]:
            merged = list(dict.fromkeys(list(unit.ownership) + row["missing_ownership"]))
            edu_blocks[unit.type] = edu_mod.set_field(
                edu_blocks.get(unit.type, unit.raw), "ownership", ", ".join(merged))
            plan.changes.append(
                f"{unit.type}: ownership += {', '.join(row['missing_ownership'])}")
        for entry_name in row["entries"]:
            if row["missing_textures"]:
                entry_facs.setdefault(entry_name, [])
                entry_facs[entry_name] += row["missing_textures"]

    if edu_blocks:
        split = eop.compose(mod, eop.edited(mod.edu.units, edu_blocks))
        plan.edu_text = split.main
        plan.eop_texts = dict(split.files)
        for key in split.files:
            plan.changes.append(f"EOP unit file rewritten: {eop.rel_to_root(mod, key)}")

    if entry_facs:
        text = mod.modeldb.to_text()
        for entry_name, facs in entry_facs.items():
            entry = mod.modeldb.get(entry_name)
            if entry is None:
                continue
            wanted = list(dict.fromkeys(f.lower() for f in facs))
            new_raw = modeldb_mod.add_texture_factions(entry.raw, wanted)
            if new_raw != entry.raw:
                text = text.replace(entry.raw, new_raw, 1)
                plan.changes.append(
                    f"{entry_name}: battle-model textures += {', '.join(wanted)} "
                    f"(copied from an existing faction's)")
        if text != mod.modeldb.to_text():
            plan.modeldb_text = text


# ---------------------------------------------------------------------------
# plan / apply


@dataclass
class BuildingPlan:
    mod: object
    line: str = ""                 # the building line being edited
    edb_text: str = ""             # '' = EDB unchanged
    loc_text: str = ""             # '' = export_buildings.txt unchanged
    # Written only when the edit asked for the ownership fix: a recruit pool can
    # name a faction the unit itself doesn't belong to, and putting that right
    # means the EDU (and, for an M2TWEOP unit, its own file) and the modeldb.
    edu_text: str = ""
    eop_texts: Dict[str, str] = field(default_factory=dict)
    modeldb_text: str = ""
    changes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    #: True when this plan CREATES the line rather than editing one.
    created: bool = False
    #: For a create: the building-card files the new levels will want. Reported,
    #: never written — see :func:`icon_slots`.
    slots: List[dict] = field(default_factory=list)

    def summary(self) -> str:
        if self.created:
            out = [f"new building line {self.line!r} in {self.mod.name}"]
            out += ["  " + c for c in self.changes]
            out += ["  ! " + w for w in self.warnings]
            out += ["  ERROR: " + e for e in self.errors]
            return "\n".join(out)
        out = [f"building edits in {self.mod.name} ({self.line or 'multiple lines'})"]
        out += ["  " + c for c in self.changes]
        out += ["  ! " + w for w in self.warnings]
        out += ["  ERROR: " + e for e in self.errors]
        return "\n".join(out)


def _all_line_bodies(body: dict) -> List[dict]:
    """The building lines this request touches: the main one, then any extras.

    ``also`` carries ``[{"line": …, "levels": [...]}]`` — mirroring a pool into
    the castle variant, or pushing one unit's numbers across every tree that
    trains it, both land here. They are planned against the same parse and
    spliced in the same pass as the main line, so one Save is one edit and one
    undo step rather than one per building.
    """
    out = [body]
    for extra in (body.get("also") or []):
        if isinstance(extra, dict) and extra.get("line"):
            out.append(extra)
    return out


def plan_edit(mod, body: dict) -> BuildingPlan:
    """Plan every level edit in one request.

    All edits are planned against the *original* line indices and spliced
    back-to-front in one pass, so several levels — and, via ``also``, several
    building lines — can be saved together without any of them moving the others.
    """
    # a new tree is its own job: there is no line to splice into yet, and the
    # two files it writes have to fail together
    if body.get("create"):
        return plan_new_tree(mod, body["create"])

    plan = BuildingPlan(mod=mod, line=str(body.get("line") or ""))
    edb = mod.edb
    if not mod.edb_path.exists():
        plan.errors.append(f"{mod.name} has no data/{EDB_REL}")
        return plan

    edits: List[LineEdit] = []
    bl = None
    for part in _all_line_bodies(body):
        name = str(part.get("line") or "")
        cur = edb.get(name)
        if cur is None:
            plan.errors.append(f"{mod.name} has no building line named {name!r}")
            return plan
        if bl is None:
            bl = cur
        # A line hand-edited in Code View replaces its whole block, and the box
        # edits then apply on top of THAT text — line order, indenting and the
        # EDB's many hand-written comments are edits no level payload can carry,
        # so re-deriving them from the boxes would throw them away.
        raw = str(part.get("raw_block") or "")
        if raw:
            edits.append(_raw_line_edit(plan, cur, part, raw))
            continue
        for lv in (part.get("levels") or []):
            blk = cur.level(str(lv.get("name") or ""))
            if blk is None:
                plan.warnings.append(f"{name} has no level {lv.get('name')!r}")
                continue
            e, notes, warn = plan_level_edit(edb, cur, blk, lv)
            edits += e
            # a note from another line has to say which line, or the preview reads
            # as if the building on screen grew rows it never had
            tag = "" if cur is bl else f"{name} · "
            plan.changes += [tag + n for n in notes]
            plan.warnings += [tag + w for w in warn]

    # the line's own header fields
    if "convert_to" in body or "religion" in body:
        edits += _plan_line_fields(edb, bl, body, plan)

    if plan.errors:
        return plan
    if edits:
        text = splice(edb.lines, edits)
        if text != edb.to_text():
            plan.edb_text = text
            reparsed = parse_text(text)
            if reparsed.warnings or not reparsed.get(plan.line):
                plan.errors.append(
                    "the edit would produce an EDB this tool can no longer read — "
                    "refusing to write it")
                return plan

    for part in _all_line_bodies(body):
        _check_recruit_limit(mod, edb.get(str(part.get("line") or "")), part, plan,
                             merge_existing=part is not body)

    loc = _plan_localisation(mod, body, plan)
    if loc:
        plan.loc_text = loc

    # Every faction each recruit pool names, so the fix covers what the edit
    # leaves behind as well as what it adds.
    if body.get("fix_ownership"):
        checks: Dict[str, List[str]] = {}
        for part in _all_line_bodies(body):
            for lv in (part.get("levels") or []):
                for op in ((lv.get("capabilities") or [])
                           + (lv.get("faction_capabilities") or [])):
                    if op.get("delete") or op.get("keyword") != "recruit_pool":
                        continue
                    pool = RecruitPool.parse(Capability(keyword="recruit_pool",
                                                        args=str(op.get("args") or "")))
                    if pool is None:
                        continue
                    requires = (clause_text(conditions_from_dicts(op["conditions"]))
                                if "conditions" in op else str(op.get("requires") or ""))
                    checks.setdefault(pool.unit, [])
                    checks[pool.unit] += clause_factions(requires)
        wanted = [{"unit": u, "factions": f} for u, f in checks.items() if f]
        if wanted:
            _plan_ownership(mod, plan, wanted)
    return plan


def _check_recruit_limit(mod, bl: Optional[BuildingLine], body: dict,
                         plan: BuildingPlan, merge_existing: bool = False) -> None:
    """Warn when a level being saved could offer one faction too many units.

    Counted from the payload rather than the file, so the warning is about what
    you are about to write. A level the edit does not mention is skipped: it is
    not changing, and nagging about a mod's pre-existing shape on every unrelated
    save is how a warning gets ignored.

    ``merge_existing`` is for the lines reached through ``also``: those payloads
    carry only the rows being added, so the level's untouched pools have to come
    from the file or every mirrored add would look free.
    """
    cultures = mod.faction_cultures
    if not cultures:
        return
    for lv in (body.get("levels") or []):
        ops = (lv.get("capabilities") or []) + (lv.get("faction_capabilities") or [])
        if not ops:
            continue
        name = str(lv.get("name") or "")
        if merge_existing and bl is not None:
            blk = bl.level(name)
            if blk is not None:
                touched = {op.get("line") for op in ops if op.get("line") is not None}
                ops = ops + [{"keyword": c.keyword, "args": c.args,
                              "requires": c.requires, "line": c.line}
                             for c in blk.capabilities + blk.faction_capabilities
                             if c.line not in touched]
        most: Dict[str, int] = {}
        always: Dict[str, int] = {}
        for op in ops:
            if op.get("delete") or op.get("keyword") != "recruit_pool":
                continue
            requires = (clause_text(conditions_from_dicts(op["conditions"]))
                        if "conditions" in op else str(op.get("requires") or ""))
            gated = _is_gated(requires)
            for f in _pool_factions(requires, cultures):
                most[f] = most.get(f, 0) + 1
                if not gated:
                    always[f] = always.get(f, 0) + 1
        over = [(f, n) for f, n in most.items()
                if n > RECRUIT_LIMIT or always.get(f, 0) > RECRUIT_LIMIT]
        if not over:
            continue
        over.sort(key=lambda r: (-always.get(r[0], 0), -r[1], r[0]))
        for f, n in over[:6]:
            a = always.get(f, 0)
            label = mod.faction_label(f) if hasattr(mod, "faction_label") else f
            if a > RECRUIT_LIMIT:
                plan.warnings.append(
                    f"{name}: {label} can already train {a} units here with no "
                    f"conditions attached — over the {RECRUIT_LIMIT} the "
                    f"recruitment panel holds")
            else:
                plan.warnings.append(
                    f"{name}: {label} could reach {n} units here if every event, "
                    f"resource and settlement condition lined up at once "
                    f"(limit {RECRUIT_LIMIT}; {a} apply unconditionally)")
        if len(over) > 6:
            plan.warnings.append(f"{name}: …and {len(over) - 6} more faction(s) over "
                                 f"the {RECRUIT_LIMIT}-unit limit")


def _raw_line_edit(plan: BuildingPlan, bl: BuildingLine, part: dict,
                   raw: str) -> LineEdit:
    """One splice replacing a whole building line with hand-edited text.

    The text is checked before it is trusted with the file: it has to still be
    exactly one building line, and still be *this* one. Renaming a line in the
    text would leave every `levels` list, plugin and settlement plan that names
    it pointing at nothing, and unlike a unit's `type` there is no rename flow
    to hand that to — so it is refused rather than warned about.
    """
    from . import codeview
    try:
        doc = codeview.parse("edb", raw)
    except codeview.CodeViewError as e:
        plan.errors.append(f"{bl.name}: the edited text isn't a valid building line: "
                           f"{e.message}")
        return LineEdit(bl.start, bl.start, "")
    if doc.ident != bl.name:
        plan.errors.append(
            f"the text renames the line to '{doc.ident}' — a building line's name is "
            f"used by its levels list and by the settlement plans, so '{bl.name}' "
            "has to stay. Rename it everywhere by hand, or not at all.")
        return LineEdit(bl.start, bl.start, "")
    # box edits made after the text edit still land, on top of the typed text
    text = render_block(raw, part)
    if text != block_text_of(plan, bl):
        plan.changes.append(f"{bl.name}: building line edited as text")
    return LineEdit(bl.start, bl.end, text)


def block_text_of(plan: BuildingPlan, bl: BuildingLine) -> str:
    """The line's current on-disk text (the plan knows the mod it came from)."""
    return block_text(plan.mod.edb, bl) if plan.mod is not None else ""


def _plan_line_fields(edb: EdbFile, bl: BuildingLine, body: dict,
                      plan: BuildingPlan) -> List[LineEdit]:
    """``convert_to`` / ``religion`` on the building line itself."""
    lines = edb.lines
    edits: List[LineEdit] = []
    for key, old in (("convert_to", bl.convert_to), ("religion", bl.religion)):
        if key not in body:
            continue
        new = str(body.get(key) or "").strip()
        if new == old:
            continue
        idx = next((j for j in range(bl.start + 1, bl.end)
                    if _code(lines[j]).split(None, 1)[:1] == [key]), None)
        if idx is None:
            if not new:
                continue
            anchor = bl.levels_line or bl.start + 1
            edits.append(_insert_before(lines, anchor,
                                        _scalar_line(_indent(lines[anchor]), key, new)))
        elif new:
            edits.append(LineEdit(idx, idx + 1,
                                  _scalar_line(_indent(lines[idx]), key, new)))
        else:
            edits.append(LineEdit(idx, idx + 1, ""))
        plan.changes.append(f"{bl.name}: {key} {old or '(unset)'} -> {new or '(none)'}")
    return edits


# ---------------------------------------------------------------------------
# creating a building tree
#
# The one thing this module could not do before: every other operation edits a
# line that is already there. A new tree is three files at once — the EDB block,
# three text keys per level in export_buildings.txt (a level short of any one of
# them is a CTD, and all 1099 real levels measured have all three), and the
# per-culture icons, which are art and stay the modder's to draw.


def upgrade_name(entry: str) -> str:
    """The level an ``upgrades`` entry points at.

    An entry may carry its own clause — ``ce_wooden_wall requires event_counter
    cex_avail_wooden_wall_erebor 1`` — so the level is the first word and the
    rest is a condition on taking that branch. 41 of the 771 upgrade entries in
    the three installed mods are of that shape.
    """
    parts = (entry or "").split(None, 1)
    return parts[0] if parts else ""


#: Vanilla's ceiling on levels in one tree (TWCenter, *List of Hardcoded
#: Limits*). M2TWEOP raises it and mods lean on that — Third Age 6's
#: ``core_building`` is 51 levels deep — so passing it is said, not refused.
VANILLA_MAX_LEVELS = 9

#: Upgrades one level may offer (same source). The deepest real level offers 6.
MAX_UPGRADES = 8

#: Prefixes the game reads on a building line's name, with what each one costs
#: you. Written from a sweep of the 277 real building lines in the three
#: installed mods, not from the reference tool's four one-line hints — two of
#: which are claims about the engine that the real files do not support (see
#: ``merge/audit-edb.md``).
TREE_PREFIXES: List[Dict[str, str]] = [
    {"prefix": "", "label": "(no prefix)",
     "hint": "An ordinary settlement building — what 145 of the 277 real lines are."},
    {"prefix": "hinterland_", "label": "hinterland_",
     "hint": "Vanilla's province-wide lines (roads, farms, mines, ports) carry it. "
             "Nothing restricts it: the mods use it for 66 different things, "
             "75 lines in all."},
    {"prefix": "temple_", "label": "temple_",
     "hint": "The religious lines. All 32 real ones also carry a `religion` line, "
             "so pick a religion below if you take this."},
    {"prefix": "guild_", "label": "guild_",
     "hint": "Needs a matching entry in data/export_descr_guilds.txt. All 19 real "
             "guild_ lines have one, and nothing else in that file does — a "
             "guild the file does not name is never offered."},
    {"prefix": "core_", "label": "core_",
     "hint": "The settlement's own chain. Every mod measured defines exactly two — "
             "core_building and core_castle_building — and both already exist, so "
             "a third is not a thing any real mod does."},
]

#: What this module will and will not do to a whole tree, and why. Same
#: ``ACTIONS``/``REFUSED`` pair the minor-file tabs and the faction roster use,
#: so the screen can show the reason where the button would be.
TREE_ACTIONS = {"create": True, "delete": False, "rename": False}

TREE_REFUSED = {
    "delete": "A building line is named from outside the EDB — every settlement in "
              "descr_strat.txt that has one built, the twin line's `convert_to`, "
              "export_descr_guilds.txt for a guild, and the campaign script. "
              "Deleting the block here would leave a save game and a campaign start "
              "pointing at a building that no longer exists, and this tool cannot "
              "see most of those files. Take the levels out of the settlements "
              "first, by hand.",
    "rename": "The name is the key its levels list, its twin's `convert_to`, the "
              "settlement plans and every script line that builds it all point at "
              "— the same ruling the text pane already makes.",
}

_NAME_OK = re.compile(r"^[A-Za-z0-9_]+$")


def _tree_indent(edb: EdbFile) -> str:
    """One level of indentation, taken from the file being written into.

    The EDB is hand-maintained and the three installed mods are not consistent
    with each other (or, in Third Age 6's case, with themselves), so a new block
    copies whatever the file's own `levels` lines use rather than imposing tabs
    on a file written with spaces.
    """
    for bl in edb.buildings:
        if bl.levels_line:
            ind = _indent(edb.lines[bl.levels_line])
            if ind:
                return ind
    return "\t"


def new_tree_text(spec: dict, indent: str = "\t") -> str:
    """Render a whole ``building … { … }`` block from the new-tree form.

    Every level is chained into the next through its ``upgrades`` block, because
    that is the only thing that makes a tree a tree — and the direction is
    forced: all 771 upgrade entries in the three installed mods point at a level
    listed *after* them on the `levels` line, which is what TWCenter's hardcoded
    limits say the engine requires.
    """
    i1, i2, i3, i4 = indent, indent * 2, indent * 3, indent * 4
    name = str(spec.get("name") or "").strip()
    levels = list(spec.get("levels") or [])
    names = [str(lv.get("name") or "").strip() for lv in levels]

    out = [f"building {name}\n", "{\n"]
    if str(spec.get("convert_to") or "").strip():
        out.append(f"{i1}convert_to {str(spec['convert_to']).strip()}\n")
    if str(spec.get("religion") or "").strip():
        out.append(f"{i1}religion {str(spec['religion']).strip()}\n")
    out.append(f"{i1}levels {' '.join(names)}\n")
    out.append(f"{i1}{{\n")
    for pos, lv in enumerate(levels):
        settlement = str(lv.get("settlement") or "").strip()
        requires = str(lv.get("requires") or "").strip()
        head = names[pos]
        if settlement:
            head += " " + settlement
        if requires:
            head += " requires " + requires
        out.append(f"{i2}{head}\n{i2}{{\n")
        out.append(f"{i3}capability\n{i3}{{\n{i3}}}\n")
        for key in ("material", "construction", "cost", "settlement_min"):
            val = str(lv.get(key, "")).strip()
            if val:
                out.append(f"{i3}{key} {val}\n")
        out.append(f"{i3}upgrades\n{i3}{{\n")
        if pos + 1 < len(names):
            out.append(f"{i4}{names[pos + 1]}\n")
        out.append(f"{i3}}}\n{i2}}}\n")
    out.append(f"{i1}}}\n")
    # every one of the 277 real building lines has one, empty or not
    out.append(f"{i1}plugins\n{i1}{{\n{i1}}}\n")
    out.append("}\n")
    return "".join(out)


def _default_requires(mod) -> str:
    """``factions { … }`` naming every culture the mod has.

    A new tree nobody can build is the easiest thing in the world to write here
    — Third Age 6 ships four levels whose clause is a literal `factions { }` —
    so the default is "everyone", spelled with this mod's own names rather than
    with vanilla's. The reference tool's new-building default is a hardcoded
    ``northern_european, southern_european``, which in Divide and Conquer means
    two of its nine cultures.

    "Everyone" is the cultures a faction in this mod actually belongs to, not
    every culture the file declares: Third Age 6's ``descr_cultures.txt`` lists
    22, of which ten have no faction and no building art at all (``dummy``,
    ``avari``, ``warg_riders`` …), and naming those in the clause would say
    nothing while making it three times as long to read.
    """
    used = sorted(set(faction_cultures(mod).values()))
    names = used or minorfiles.culture_names(mod) or cultures_of(mod)
    if not names:
        return ""
    return "factions { " + "".join(f"{c}, " for c in names) + "}"


def new_tree_spec(mod, spec: dict) -> dict:
    """Fill a half-written new-tree form in, so the preview shows real text.

    The form may send nothing but a name and a level count; everything else has
    a default taken from the mod rather than from vanilla.
    """
    out = dict(spec)
    out["name"] = str(spec.get("name") or "").strip()
    settlement = str(spec.get("settlement") or "").strip()
    requires = str(spec.get("requires") or "").strip() or _default_requires(mod)
    levels = []
    for pos, lv in enumerate(spec.get("levels") or []):
        lv = dict(lv)
        lv["name"] = str(lv.get("name") or "").strip()
        lv.setdefault("settlement", settlement)
        lv["requires"] = str(lv.get("requires") or "").strip() or requires
        lv.setdefault("material", "wooden")
        lv.setdefault("construction", "2")
        lv.setdefault("cost", str(600 * (pos + 1)))
        lv.setdefault("settlement_min", SETTLEMENT_LEVELS[min(pos, len(SETTLEMENT_LEVELS) - 1)])
        # An empty box is absent, not blank: the form sends "" for a level whose
        # shown name you left alone, and a level whose `{name}` key is empty is
        # a blank entry in the construction panel.
        lv["label"] = (str(lv.get("label") or "").strip()
                       or lv["name"].replace("_", " ").title())
        lv["descr"] = str(lv.get("descr") or "")
        lv["descr_short"] = str(lv.get("descr_short") or "")
        levels.append(lv)
    out["levels"] = levels
    return out


def icon_slots(mod, spec: dict) -> List[dict]:
    """The building-card files a new tree will want, and which already exist.

    Written down rather than written: these are TGA art, and the toolkit has
    nothing to put in them. A level with no card is not a crash — the same
    ruling Phase 10a made about pips and settlement cards — so this is a list to
    draw against, not a list of faults.

    One row per level and culture, carrying both files: they are drawn as a pair
    (the button and the constructed picture) and nobody makes one without the
    other. Only the cultures with a ``data/ui/<culture>/buildings`` folder are
    listed — a culture the mod has no art folder for has no slot to fill.
    """
    vanilla = config.get_vanilla_ui_root()
    out: List[dict] = []
    for lv in (spec.get("levels") or []):
        level = str(lv.get("name") or "")
        for culture in (cultures_of(mod) or list(mod.cultures)):
            row = {"level": level, "culture": culture, "found": True}
            for kind in ("small", "large"):
                found, source = find_icon(mod, culture, level, kind, vanilla)
                row[kind] = f"data/ui/{culture}/buildings/{icon_stem(culture, level, kind)}.tga"
                row[kind + "_found"] = bool(found)
                row[kind + "_source"] = source
                row["found"] = row["found"] and bool(found)
            out.append(row)
    return out


def plan_new_tree(mod, spec: dict) -> BuildingPlan:
    """Plan the whole of a new building tree: EDB block, then its text keys.

    Refuses rather than half-writes. A name already in the file, a level name
    already used *anywhere* in the EDB (level names are the EDB's one global
    namespace — ``EdbFile.by_level`` and every text key rely on it) or a name the
    game cannot read all stop the plan, because the second half of this job
    writes into a different file and there is no such thing as a tree that
    reached one of them.
    """
    spec = new_tree_spec(mod, spec)
    plan = BuildingPlan(mod=mod, line=spec["name"], created=True)
    edb = mod.edb
    if not mod.edb_path.exists():
        plan.errors.append(f"{mod.name} has no data/{EDB_REL}")
        return plan

    name = spec["name"]
    levels = spec["levels"]
    if not name:
        plan.errors.append("the new building line needs a name")
    elif not _NAME_OK.match(name):
        plan.errors.append(f"{name!r} is not a name the EDB can carry — letters, "
                           "digits and underscores only, and no spaces")
    elif edb.get(name) is not None:
        plan.errors.append(f"{mod.name} already has a building line called {name!r}")
    if not levels:
        plan.errors.append("a building line needs at least one level")

    taken = edb.by_level()
    seen: set = set()
    for lv in levels:
        lname = lv["name"]
        if not lname:
            plan.errors.append("every level needs a name")
        elif not _NAME_OK.match(lname):
            plan.errors.append(f"level {lname!r}: letters, digits and underscores only")
        elif lname in taken:
            owner = taken[lname][0].name
            plan.errors.append(
                f"{mod.name} already has a level called {lname!r}, in the {owner!r} "
                "line — a level name is the key its text, its icons and every "
                "settlement plan use, so two of them cannot share one")
        elif lname in seen:
            plan.errors.append(f"level {lname!r} is in the new line twice")
        seen.add(lname)
    if name and name in taken:
        plan.errors.append(f"{name!r} is already the name of a level in the "
                           f"{taken[name][0].name!r} line")
    if plan.errors:
        return plan

    if len(levels) > VANILLA_MAX_LEVELS:
        plan.warnings.append(
            f"{len(levels)} levels — vanilla stops at {VANILLA_MAX_LEVELS} per tree "
            "and crashes past it. M2TWEOP raises the ceiling and mods use that "
            "(Third Age 6's core_building is 51 deep), so this only works with EOP.")
    for prefix, why in (("guild_", "needs a matching entry in "
                                   "data/export_descr_guilds.txt — all 19 real "
                                   "guild_ lines have one, and a guild that file "
                                   "does not name is never offered"),
                        ("core_", "is the settlement's own chain; every mod "
                                  "measured defines exactly core_building and "
                                  "core_castle_building, and nothing suggests a "
                                  "third one does anything")):
        if name.startswith(prefix):
            plan.warnings.append(f"a {prefix} line {why}.")
    if name.startswith("temple_") and not str(spec.get("religion") or "").strip():
        plan.warnings.append("every one of the 32 real temple_ lines also carries a "
                             "`religion` line; this one has none.")
    convert = str(spec.get("convert_to") or "").strip()
    if convert and edb.get(convert) is None:
        plan.warnings.append(f"convert_to names {convert!r}, which this EDB has no "
                             "building line for")

    block = new_tree_text(spec, _tree_indent(edb))
    text = edb.to_text()
    if text and not text.endswith("\n"):
        text += "\n"
    text += "\n" + block
    reparsed = parse_text(text)
    new = reparsed.get(name)
    if reparsed.warnings or new is None or len(new.blocks) != len(levels):
        plan.errors.append("the new line would produce an EDB this tool can no "
                           "longer read — refusing to write it")
        return plan
    plan.edb_text = text
    plan.changes.append(f"{name}: new building line, {len(levels)} level"
                        f"{'' if len(levels) == 1 else 's'} "
                        f"({', '.join(lv['name'] for lv in levels)})")

    plan.loc_text = _plan_new_localisation(mod, spec, plan)
    plan.slots = icon_slots(mod, spec)
    missing = [s for s in plan.slots if not s["found"]]
    if missing:
        plan.warnings.append(
            f"{len(missing)} of {len(plan.slots)} building cards have no picture "
            "yet — those levels show a blank card until you draw them. The paths "
            "are listed below; this is art, not a fault.")
    return plan


def _plan_new_localisation(mod, spec: dict, plan: BuildingPlan) -> str:
    """The text keys a new tree needs in ``data/text/export_buildings.txt``.

    Three per level — ``{x}``, ``{x_desc}``, ``{x_desc_short}`` — because all
    1099 levels in the three installed mods have all three and a level short of
    one crashes the game at the construction panel. The tree's own
    ``{<line>_name}`` is written too when the form gave it a name: it is the
    heading the browser groups the levels under, and 227 of the 277 real lines
    have one.
    """
    path = mod.data / LOC_REL
    if not path.exists():
        plan.errors.append(
            f"{mod.name} has no data/{LOC_REL}, so the new levels would have no "
            "names — and a level with no text key crashes the game. Nothing written.")
        return ""
    text = path.read_text(encoding=localization.ENCODING)
    for lv in (spec.get("levels") or []):
        key = lv["name"]
        text = localization.upsert_record(text, key, str(lv.get("label") or key),
                                          str(lv.get("descr") or ""),
                                          str(lv.get("descr_short") or ""),
                                          descr_suffix="_desc")
        plan.changes.append(f"{key}: text keys written ({{{key}}}, {{{key}_desc}}, "
                            f"{{{key}_desc_short}})")
    label = str(spec.get("label") or "").strip()
    if label:
        # ONE key, not a three-key record: no real line has a `<line>_name_desc`
        text = stringsbin.upsert_txt(text, {spec["name"] + "_name": label})
        plan.changes.append(f"{spec['name']}_name: tree shown as {label!r}")
    return text


# ---------------------------------------------------------------------------
# Code View: one building line as text, and which line each box came from


def block_text(edb: EdbFile, bl: BuildingLine) -> str:
    """The verbatim text of one ``building … { … }`` block."""
    return "".join(edb.lines[bl.start:bl.end])


def block_spans(edb: EdbFile, bl: BuildingLine) -> Dict[str, List[List[int]]]:
    """Map each editable thing in a building line to the lines it occupies.

    Lines are 1-based and inclusive, counted from the first line of the BLOCK
    (not of the file), because that is what the code view is showing. Labels are
    the ones :func:`unittransfer.codeview` hands the page, and they are
    hierarchical so a hover can be as coarse or as fine as the box that raised
    it: hovering a level's card lights the whole level, hovering its cost line
    lights one line.

        building                  the `building <name>` line
        convert_to / religion / classification / factions
        levels                    the `levels a, b, c` line
        level:<name>              the whole level block, brace to brace
        level:<name>:header       its `<name> city requires …` line
        level:<name>:<scalar>     cost, construction, material, …
        level:<name>:upgrades     the whole upgrades block
        level:<name>:cap#<i>      the i-th capability line (1-based)
        level:<name>:fcap#<i>     the i-th faction_capability line
    """
    spans: Dict[str, List[List[int]]] = {}
    base = bl.start

    def put(label: str, first: int, last: int = None) -> None:
        if first < base or first >= bl.end:
            return
        last = first if last is None else min(last, bl.end - 1)
        spans.setdefault(label, []).append([first - base + 1, last - base + 1])

    put("building", bl.start)
    # convert_to / religion / the extras are found the way _plan_line_fields
    # finds them to edit them — same scan, so the two can never disagree
    for j in range(bl.start + 1, bl.end):
        head = _code(edb.lines[j]).split(None, 1)[:1]
        if head and head[0] in ("convert_to", "religion", "classification", "factions"):
            put(head[0], j)
    if bl.levels_line:
        put("levels", bl.levels_line)
    for p in bl.plugins:
        put(f"plugin:{p.name}", p.start, p.end - 1)

    for blk in bl.blocks:
        key = f"level:{blk.name}"
        put(key, blk.header, blk.end - 1)
        put(key + ":header", blk.header)
        for name, idx in blk.scalar_lines.items():
            put(f"{key}:{name}", idx)
        if blk.upgrades_span != (0, 0):
            o, c = blk.upgrades_span
            # the brace usually sits on its own line under the keyword; the
            # highlight should cover the keyword the user is looking at, not
            # start one line below it
            head = o - 1 if (o - 1 > blk.header
                             and _code(edb.lines[o - 1]) == "upgrades") else o
            put(key + ":upgrades", head, c)
        for i, c in enumerate(blk.capabilities, 1):
            put(f"{key}:cap#{i}", c.line)
            # the editor's rows carry a capability's LINE, not its position, so
            # the same span is addressable that way too — that is what survives
            # rows being filtered, reordered or hidden in the list
            put(f"capline#{c.line}", c.line)
        for i, c in enumerate(blk.faction_capabilities, 1):
            put(f"{key}:fcap#{i}", c.line)
            put(f"capline#{c.line}", c.line)
    return spans


def block_fields(edb: EdbFile, bl: BuildingLine) -> List[Tuple[str, str]]:
    """``(label, value)`` for every span :func:`block_spans` reports.

    A flat list of what the block says, in the same vocabulary as the spans —
    enough for the page to show a value beside a highlight without walking the
    tree itself.
    """
    out: List[Tuple[str, str]] = [("building", bl.name)]
    for key, val in (("convert_to", bl.convert_to), ("religion", bl.religion)):
        if val:
            out.append((key, val))
    for key, val in bl.extras.items():
        out.append((key, val))
    if bl.levels:
        out.append(("levels", ", ".join(bl.levels)))
    for blk in bl.blocks:
        key = f"level:{blk.name}"
        out.append((key + ":header",
                    " ".join(x for x in (blk.settlement,
                                         ("requires " + blk.requires) if blk.requires else "")
                             if x)))
        for name in blk.scalar_lines:
            out.append((f"{key}:{name}", blk.scalars.get(name, "")))
        if blk.upgrades_span != (0, 0):
            out.append((key + ":upgrades", ", ".join(blk.upgrades)))
        for i, c in enumerate(blk.capabilities, 1):
            out.append((f"{key}:cap#{i}", _code(c.text())))
        for i, c in enumerate(blk.faction_capabilities, 1):
            out.append((f"{key}:fcap#{i}", _code(c.text())))
    return out


def render_block(base: str, body: dict) -> str:
    """Apply the editor's level-edit payload to ONE building line's text.

    The same :func:`plan_level_edit` and :func:`splice` the save runs, just
    pointed at the block on its own instead of at the whole 30 000-line EDB — so
    the code view shows exactly the bytes a save would put in the file, and
    there is no second serialiser to drift from the first.
    """
    sub = parse_text(base)
    if not sub.buildings:
        return base
    bl = sub.buildings[0]
    plan = BuildingPlan(mod=None, line=bl.name)
    edits: List[LineEdit] = []
    for lv in (body.get("levels") or []):
        blk = bl.level(str(lv.get("name") or ""))
        if blk is None:
            continue
        e, _notes, _warn = plan_level_edit(sub, bl, blk, lv)
        edits += e
    if "convert_to" in body or "religion" in body:
        edits += _plan_line_fields(sub, bl, body, plan)
    return splice(sub.lines, edits) if edits else base


def _plan_localisation(mod, body: dict, plan: BuildingPlan) -> str:
    """Rewrite ``text/export_buildings.txt`` for any renamed level.

    Every level needs three keys (``{x}``, ``{x_desc}``, ``{x_desc_short}``) or
    the game CTDs, so a name edit always writes all three.

    A level may be named once for everyone (the base key) and again for each
    culture (``{x_<culture>}``). ``loc`` on a level payload is the base record;
    ``loc_cultures`` maps culture -> record for the rest. Only the ones that
    actually differ from the file are written.
    """
    edits = [lv for lv in (body.get("levels") or [])
             if "loc" in lv or "loc_cultures" in lv]
    if not edits:
        return ""
    path = mod.data / LOC_REL
    if not path.exists():
        plan.warnings.append(f"{mod.name} has no data/{LOC_REL} — names not written")
        return ""
    text = path.read_text(encoding=localization.ENCODING)
    changed = False
    for lv in edits:
        name = str(lv.get("name") or "")
        targets = []
        if "loc" in lv:
            targets.append(("", lv.get("loc") or {}))
        for culture, rec in (lv.get("loc_cultures") or {}).items():
            targets.append((str(culture), rec or {}))
        for culture, loc in targets:
            key = loc_key(name, culture)
            cur = mod.building_loc.get(key)
            new_name = str(loc.get("name", cur.name if cur else "") or "")
            new_desc = str(loc.get("descr", cur.descr if cur else "") or "")
            new_short = str(loc.get("descr_short", cur.descr_short if cur else "") or "")
            if cur and (new_name, new_desc, new_short) == (cur.name or "", cur.descr or "",
                                                           cur.descr_short or ""):
                continue
            if not cur and not (new_name or new_desc or new_short):
                continue          # an untouched culture the file never had
            text = localization.upsert_record(text, key, new_name, new_desc, new_short,
                                              descr_suffix="_desc")
            plan.changes.append(f"{key}: name -> {new_name!r}")
            changed = True
    return text if changed else ""


def apply_edit(plan: BuildingPlan) -> Dict:
    """Write the plan into the mod, with per-file backups and a log record.

    Same machinery as a transfer, a unit edit or a voice edit: every touched file
    is copied into ``config/backups/<id>/`` first and the manifest goes in the
    transfer log, so 🕑 Log -> Undo restores the EDB byte-exact.
    """
    if plan.errors:
        raise ValueError("cannot apply: " + "; ".join(plan.errors))
    mod = plan.mod
    tid = config.new_transfer_id()
    backup_root = config.backup_root_for(tid)
    manifest: Dict[str, List[str]] = {"backed_up": [], "created": []}

    fingerprint(mod)
    log.info("BUILD  id=%s in %s — %r (%d change(s))", tid, mod.name, plan.line,
             len(plan.changes))
    log.info("  backups -> %s", backup_root)

    def write_text(rel: str, text: str, encoding: str) -> None:
        target = mod.data / rel
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
        target.write_text(text, encoding=encoding)
        file_op("WRITE", target, f"{encoding}, {len(text)} chars")

    if plan.edb_text:
        write_text(EDB_REL, plan.edb_text, ENCODING)
    if plan.loc_text:
        write_text(LOC_REL, plan.loc_text, localization.ENCODING)
    if plan.edu_text:
        write_text("export_descr_unit.txt", plan.edu_text, edu_mod.ENCODING)
    if plan.eop_texts:
        eop.write_split(mod, plan.eop_texts, (), backup_root, manifest)
    if plan.modeldb_text:
        write_text("unit_models/battle_models.modeldb", plan.modeldb_text,
                   modeldb_mod.ENCODING)

    rec = {
        "id": tid,
        "when": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "buildings",
        "action": "building-new" if plan.created else "building",
        "source": mod.name,
        "source_root": str(mod.root),
        "dest": mod.name,
        "dest_root": str(mod.root),
        "unit_type": plan.line,
        "resolved_type": plan.line,
        "options": {},
        "applied": True,
        "undone": False,
        "note": "",
        "summary": plan.summary(),
        "warnings": list(plan.warnings),
        "manifest": manifest,
        "backup_root": str(backup_root),
    }
    config.append_log(rec)
    counted(manifest)
    log.info("BUILD  done id=%s", tid)
    for cached in ("edb", "building_loc", "edb_vocab", "edu", "edu_vocab", "modeldb"):
        mod.__dict__.pop(cached, None)
    return rec


# ---------------------------------------------------------------------------
# payloads for the Buildings-mode UI


def loc_key(level: str, culture: str = "") -> str:
    """The export_buildings.txt key holding one level's text for one culture.

    A level has a base key (``{stables}``) and one key per culture
    (``{stables_northern_european}``). The game shows the culture's key to a
    faction of that culture and the base key to everyone else.
    """
    return f"{level}_{culture}" if culture else level


def _placeholder(key: str, name: str) -> bool:
    """True when a key's value is not a real name.

    Divide and Conquer writes the key's own text back as its value for ~3000
    base keys — ``{stables}stables``, described as "DO NOT TRANSLATE" — because
    every one of its buildings is named per culture instead. Treating that as a
    name is what made the browser show code names for the whole mod.
    """
    n = (name or "").strip()
    return not n or n == key


def _loc_of(mod, key: str) -> dict:
    e = mod.building_loc.get(key)
    return {"name": (e.name or "") if e else "",
            "descr": (e.descr or "") if e else "",
            "descr_short": (e.descr_short or "") if e else ""}


def _loc_all(mod, level: str) -> Dict[str, dict]:
    """Every record export_buildings.txt holds for one level.

    Keyed by culture, with ``''`` for the base key. Cultures the file says
    nothing about are still listed (``present: False``) so the editor can offer
    to write them.
    """
    out: Dict[str, dict] = {}
    for culture in [""] + list(mod.cultures):
        key = loc_key(level, culture)
        e = mod.building_loc.get(key)
        out[culture] = {"key": key, "present": e is not None,
                        "name": (e.name or "") if e else "",
                        "descr": (e.descr or "") if e else "",
                        "descr_short": (e.descr_short or "") if e else ""}
    return out


def _best_loc(mod, level: str, culture: str = "") -> dict:
    """The record a level actually shows, for the culture being looked at.

    Same order the game reads them in — the culture's own key first, then the
    base key — with one addition: a base key that is only a placeholder falls
    through to whichever culture DOES have text, so a mod that names everything
    per culture still reads as names rather than as code.
    """
    recs = _loc_all(mod, level)
    order = ([culture] if culture in recs and culture else []) + [""]
    order += [c for c in recs if c and c != culture]
    for c in order:
        r = recs[c]
        if not _placeholder(r["key"], r["name"]):
            return dict(r, culture=c)
    return dict(recs.get(culture) or recs[""], culture=culture if culture in recs else "")


def _label(mod, key: str, fallback: str = "", culture: str = "") -> str:
    """A level's or line's display name, falling back to its code name."""
    name = (_best_loc(mod, key, culture)["name"] or "").strip()
    return name if name else (fallback or key)


def _cap_payload(cap: Capability) -> dict:
    """One capability line, split into the pieces the editor's widgets need."""
    args = cap.args
    bonus = args.split(None, 1)[0] == "bonus" if args else False
    out = {
        "line": cap.line,
        "keyword": cap.keyword,
        "args": args,
        "requires": cap.requires,
        "conditions": clause_payload(cap.requires),
        "comment": cap.comment,
        "bonus": bonus,
        "value": (args.split(None, 1)[1].strip() if bonus and " " in args else
                  ("" if bonus else args)),
        "help": CAP_HELP.get(cap.keyword, ""),
    }
    pool = cap.pool()
    if pool is not None:
        out["pool"] = {"unit": pool.unit, "initial": pool.initial,
                       "per_turn": pool.per_turn, "maximum": pool.maximum,
                       "experience": pool.experience}
    return out


def _units_index(mod) -> Dict[str, dict]:
    """Lower-cased EDU type -> the bits the recruitment list shows for a unit."""
    out: Dict[str, dict] = {}
    for u in mod.edu.units:
        loc = mod.loc.get(u.dictionary)
        out[u.type.lower()] = {
            "type": u.type,
            "name": (loc.name.strip() if loc and loc.name else "") or u.type,
            "kind": u.kind(),
            "class": u.class_type,
            "category": u.category,
            "ownership": list(u.ownership),
            "mercenary": u.mercenary_unit,
            "eop": u.is_eop,
        }
    return out


# ---------------------------------------------------------------------------
# city / castle variants
#
# Nearly every recruitment building in a real mod exists twice — once for cities
# and once for castles — and the two are expected to stay in step. Nothing in the
# EDB says which two lines are a pair, though: the file just has two independent
# `building` blocks whose names differ by a marker the mod picked. Divide and
# Conquer alone ships all four spellings below, sometimes in the same file.

#: Name fragments that mean "this is the castle (or city) half", not part of the
#: building's identity. `c` is the short form both DaC and vanilla use.
_VARIANT_BITS = frozenset(("castle", "city", "c"))


def variant_key(name: str) -> str:
    """A building or level name with its city/castle marker taken out.

    ``castle_barracks``, ``c_barracks``, ``barracks_castle`` and
    ``temple_c_academic`` all key as their marker-free form, so the two halves of
    a pair meet in the middle. Nothing else is normalised — two names that differ
    by anything but a marker are different buildings.

    A name that is *only* a marker (the ``castle`` level of a core castle line)
    keeps itself rather than collapsing to nothing.
    """
    parts = [p for p in name.strip().lower().split("_") if p]
    kept = [p for p in parts if p not in _VARIANT_BITS]
    return "_".join(kept or parts)


def variant_pairs(edb: EdbFile) -> Dict[str, str]:
    """``line name -> the opposite settlement's line``, both ways round.

    Only unambiguous pairs are reported: exactly one city line and exactly one
    castle line sharing a key. Two candidates on a side means the mod is using
    the marker for something else, and guessing there would mirror an edit into
    the wrong building.
    """
    sides: Dict[str, Dict[str, List[str]]] = {}
    for bl in edb.buildings:
        kind = bl.settlement
        if kind not in ("city", "castle"):
            continue
        sides.setdefault(variant_key(bl.name), {}).setdefault(kind, []).append(bl.name)
    out: Dict[str, str] = {}
    for by_kind in sides.values():
        city, castle = by_kind.get("city") or [], by_kind.get("castle") or []
        if len(city) == 1 and len(castle) == 1:
            out[city[0]] = castle[0]
            out[castle[0]] = city[0]
    return out


def pair_levels(a: BuildingLine, b: BuildingLine) -> Dict[str, str]:
    """``level of a -> the level of b that mirrors it``.

    Marker-free names first (``stables`` -> ``c_stables``), then position in the
    chain for whatever is left: a mod that renamed its castle tiers outright
    still has tier 1 facing tier 1, and that is the pairing a human would make.
    """
    by_key: Dict[str, List[str]] = {}
    for blk in b.blocks:
        by_key.setdefault(variant_key(blk.name), []).append(blk.name)
    out: Dict[str, str] = {}
    used: set = set()
    for blk in a.blocks:
        for cand in by_key.get(variant_key(blk.name), []):
            if cand not in used:
                out[blk.name] = cand
                used.add(cand)
                break
    for i, blk in enumerate(a.blocks):
        if blk.name in out:
            continue
        if i < len(b.blocks) and b.blocks[i].name not in used:
            out[blk.name] = b.blocks[i].name
            used.add(b.blocks[i].name)
    return out


# ---------------------------------------------------------------------------
# recruitment checks
#
# Three mistakes that are invisible one level at a time and obvious across a
# whole line: a unit that stops being recruitable when the building is upgraded,
# a unit one settlement type has and the other does not, and the same unit listed
# twice in one level.


def _pool_rows(bl: BuildingLine) -> List[dict]:
    """Every recruit pool in a line, tagged with where it lives."""
    rows: List[dict] = []
    for i, blk in enumerate(bl.blocks):
        for faction, caps in ((False, blk.capabilities), (True, blk.faction_capabilities)):
            for cap in caps:
                pool = cap.pool()
                if pool is None:
                    continue
                rows.append({"line": bl.name, "level": blk.name, "level_index": i,
                             "faction": faction, "cap_line": cap.line,
                             "unit": pool.unit, "unit_key": pool.unit.lower(),
                             "initial": pool.initial, "per_turn": pool.per_turn,
                             "maximum": pool.maximum, "experience": pool.experience,
                             "requires": cap.requires})
    return rows


def _pool_brief(r: dict) -> dict:
    """Just enough of a pool row to recreate it somewhere else."""
    return {k: r[k] for k in
            ("unit", "initial", "per_turn", "maximum", "experience", "requires")}


def line_checks(edb: EdbFile, bl: BuildingLine,
                pairs: Optional[Dict[str, str]] = None) -> dict:
    """Continuity, mirror and duplicate findings for one building line."""
    rows = _pool_rows(bl)
    levels = [b.name for b in bl.blocks]

    # ---- a unit that stops being recruitable further up the chain ----
    at: Dict[str, set] = {}
    names: Dict[str, str] = {}
    best: Dict[str, dict] = {}
    for r in rows:
        at.setdefault(r["unit_key"], set()).add(r["level_index"])
        names.setdefault(r["unit_key"], r["unit"])
        # the highest tier that does train it — what a filled-in gap should copy,
        # since the numbers a mod gives a unit tend to climb with the building
        cur = best.get(r["unit_key"])
        if cur is None or r["level_index"] > cur["level_index"]:
            best[r["unit_key"]] = dict(_pool_brief(r), level_index=r["level_index"])
    gaps = []
    for key, seen in sorted(at.items()):
        first = min(seen)
        missing = [i for i in range(first, len(levels)) if i not in seen]
        if missing:
            gaps.append({"unit": names[key], "first": first,
                         "present": sorted(seen), "missing": missing,
                         "missing_levels": [levels[i] for i in missing],
                         "pool": best[key]})

    # ---- the same unit twice in one level ----
    dupes = []
    per_level: Dict[Tuple[int, str], List[dict]] = {}
    for r in rows:
        per_level.setdefault((r["level_index"], r["unit_key"]), []).append(r)
    for (idx, key), group in sorted(per_level.items()):
        if len(group) > 1:
            dupes.append({"unit": group[0]["unit"], "level": levels[idx],
                          "level_index": idx, "count": len(group),
                          "cap_lines": [g["cap_line"] for g in group],
                          # two rows with different clauses are usually deliberate
                          # (one per faction); identical ones never are
                          "same_requires": len({_norm(g["requires"]) for g in group}) == 1})

    # ---- what the other settlement type has and this one does not ----
    pairs = variant_pairs(edb) if pairs is None else pairs
    other_name = pairs.get(bl.name, "")
    other = edb.get(other_name) if other_name else None
    mirror: List[dict] = []
    forward: Dict[str, str] = {}
    twin_units: Dict[str, List[str]] = {}
    if other is not None:
        forward = pair_levels(bl, other)
        mine: Dict[str, Dict[str, dict]] = {}
        for r in rows:
            mine.setdefault(r["level"], {}).setdefault(r["unit_key"], r)
        theirs: Dict[str, Dict[str, dict]] = {}
        for r in _pool_rows(other):
            theirs.setdefault(r["level"], {}).setdefault(r["unit_key"], r)
        # everything the twin trains, not only what differs: mirroring a row
        # across has to know whether it is already there
        twin_units = {lvl: sorted(by_unit) for lvl, by_unit in theirs.items()}
        for i, blk in enumerate(bl.blocks):
            twin = forward.get(blk.name)
            if not twin:
                continue
            here, there = mine.get(blk.name, {}), theirs.get(twin, {})
            only_here = [_pool_brief(here[k]) for k in sorted(here) if k not in there]
            only_there = [_pool_brief(there[k]) for k in sorted(there) if k not in here]
            if not only_here and not only_there:
                continue
            # the numbers travel with the names: copying a unit across is the
            # point of the finding, and it should land on the twin's own figures
            # rather than on a default nobody chose
            mirror.append({
                "level": blk.name, "level_index": i, "twin": twin,
                "only_here": only_here, "only_there": only_there,
            })
    return {
        "line": bl.name,
        "settlement": bl.settlement,
        "levels": levels,
        "twin": other_name,
        # this line's level -> the twin's level, for every tier and not only the
        # ones that differ: mirroring a pool needs the target level name even
        # where the two halves currently agree
        "level_pairs": forward,
        # lower-cased unit types the twin already trains, per twin level
        "twin_units": twin_units,
        "gaps": gaps,
        "dupes": dupes,
        "mirror": mirror,
    }


def checks(mod, line: str = "") -> dict:
    """Recruitment checks for one line, or a per-line rollup for the whole mod."""
    edb = mod.edb
    pairs = variant_pairs(edb)
    if line:
        bl = edb.get(line)
        if bl is None:
            raise KeyError(line)
        return {"mod": mod.name, "pairs": pairs, "lines": [line_checks(edb, bl, pairs)]}
    rollup = []
    for bl in edb.buildings:
        res = line_checks(edb, bl, pairs)
        if res["gaps"] or res["dupes"] or res["mirror"]:
            rollup.append({k: res[k] for k in
                           ("line", "settlement", "twin", "gaps", "dupes", "mirror")})
    return {"mod": mod.name, "pairs": pairs, "lines": rollup}


def unit_instances(mod, unit: str, culture: str = "") -> dict:
    """Every recruit pool in the mod that trains ``unit``, across all lines.

    What the building browser's "compare this unit everywhere" panel is built
    from: the same unit is usually recruited from four or five buildings with
    numbers that drifted apart, and seeing them in one table is the only way to
    tell which one is the odd one out.
    """
    edb = mod.edb
    key = unit.strip().lower()
    pairs = variant_pairs(edb)
    #: line -> {its level name: the facing level in its city/castle twin}, and
    #: line -> {level name: units it trains there}. Worked out once per line
    #: rather than per row, because a unit with five pools in one building would
    #: otherwise pair the same two blocks five times.
    twin_levels: Dict[str, Dict[str, str]] = {}
    twin_trains: Dict[str, Dict[str, set]] = {}

    def _twin_of(bl):
        """``(level pairing, what the twin trains per level)`` for one line."""
        if bl.name not in twin_levels:
            other = edb.get(pairs.get(bl.name, "")) if pairs.get(bl.name) else None
            trains: Dict[str, set] = {}
            if other is not None:
                for r in _pool_rows(other):
                    trains.setdefault(r["level"], set()).add(r["unit_key"])
            twin_levels[bl.name] = pair_levels(bl, other) if other is not None else {}
            twin_trains[bl.name] = trains
        return twin_levels[bl.name], twin_trains[bl.name]

    rows = []
    for bl in edb.buildings:
        for r in _pool_rows(bl):
            if r["unit_key"] != key:
                continue
            blk = bl.blocks[r["level_index"]]
            # Does the settlement's other half train this unit at the facing
            # tier? A city/castle pair that has drifted apart is the thing this
            # panel is read to find, and the answer is per TIER: a twin that
            # trains the unit five levels up is not the same building.
            levels, trains = _twin_of(bl)
            tw_level = levels.get(blk.name, "")
            rows.append({
                "line": bl.name,
                "line_label": _label(mod, bl.name + "_name", bl.name, culture),
                "settlement": blk.settlement or bl.settlement,
                "twin": pairs.get(bl.name, ""),
                "twin_level": tw_level,
                "twin_level_label": (_label(mod, tw_level, tw_level, culture)
                                     if tw_level else ""),
                "twin_has": bool(tw_level and key in trains.get(tw_level, ())),
                "level": blk.name,
                "level_label": _label(mod, blk.name, blk.name, culture),
                "level_index": r["level_index"],
                "level_count": len(bl.blocks),
                "faction": r["faction"],
                "cap_line": r["cap_line"],
                "initial": r["initial"], "per_turn": r["per_turn"],
                "maximum": r["maximum"], "experience": r["experience"],
                "requires": r["requires"],
                "conditions": clause_payload(r["requires"]),
            })
    info = _units_index(mod).get(key)
    return {"mod": mod.name, "unit": unit,
            "info": info or {"type": unit, "name": unit, "missing": True},
            "instances": rows}


def _art_sources(mod, level: str, vanilla) -> Dict[str, Dict[str, str]]:
    """``{culture: {'small': src, 'large': src}}`` for one level, '' where absent.

    Answered here rather than left to the icon endpoint so the grid can badge
    borrowed art and filter on "this mod has none of its own" without firing a
    request per card. Cheap: :func:`find_icon` reads a cached directory index.
    """
    out: Dict[str, Dict[str, str]] = {}
    for culture in mod.cultures:
        small = find_icon(mod, culture, level, "small", vanilla)[1]
        large = find_icon(mod, culture, level, "large", vanilla)[1]
        out[culture] = {"small": small, "large": large}
    return out


def overview(mod, culture: str = "") -> dict:
    """Every building line in one mod, light enough for the browser grid.

    ``culture`` picks which of a level's per-culture names is shown; sending the
    lot would mean nine names per level over several thousand levels, so the
    browser re-asks when the culture picker moves.
    """
    edb = mod.edb
    units = _units_index(mod)
    vanilla = config.get_vanilla_ui_root()
    lines = []
    for bl in edb.buildings:
        recruits: List[str] = []
        factions: List[str] = []
        for blk in bl.blocks:
            factions += clause_factions(blk.requires)
            for pool in blk.recruits:
                recruits.append(pool.unit)
                factions += clause_factions(pool.requires)
        uniq = list(dict.fromkeys(recruits))
        # the last level is the finished building, and its art is what the card shows
        top = bl.blocks[-1].name if bl.blocks else ""
        lines.append({
            "name": bl.name,
            "top_level": top,
            "art": _art_sources(mod, top, vanilla) if top else {},
            "label": _label(mod, bl.name + "_name", bl.name, culture),
            "convert_to": bl.convert_to,
            "religion": bl.religion,
            "extras": dict(bl.extras),
            "settlement": bl.settlement,
            "levels": [b.name for b in bl.blocks],
            "level_labels": [_label(mod, b.name, "", culture) for b in bl.blocks],
            "level_count": len(bl.blocks),
            "recruit_count": len(uniq),
            "missing_units": [u for u in uniq if u.lower() not in units],
            "factions": list(dict.fromkeys(factions)),
            "plugin_count": len(bl.plugins),
        })
    return {
        "mod": mod.name,
        "has_file": mod.edb_path.exists(),
        "has_loc": mod.building_loc_path.exists(),
        "lines": lines,
        "culture": culture,
        "cultures": mod.cultures,
        "faction_cultures": mod.faction_cultures,
        "faction_names": mod.faction_names,
        "hidden_resources": edb.hidden_resources,
        # this mod's own religions, falling back to vanilla's five only when it
        # has no descr_religions.txt to read them out of
        "religions": (minorfiles.religion_names(mod) or list(VANILLA_RELIGIONS)),
        # …and say so, or the picker silently offers `pagan` to a mod that has
        # ten religions and none of them is pagan
        "religions_are_vanilla": not minorfiles.religion_names(mod),
        "materials": list(MATERIALS),
        "settlement_levels": list(SETTLEMENT_LEVELS),
        "recruit_limit": RECRUIT_LIMIT,
        "capabilities": [{"keyword": k, "help": v, "bonus": k in BONUS_CAPS,
                          "group": CAP_META.get(k, ("Other", ""))[0],
                          "range": CAP_META.get(k, ("Other", ""))[1]}
                         for k, v in sorted(CAP_HELP.items())],
        "capability_groups": list(CAP_GROUPS),
        # what a `requires` clause may name, so the editor can offer checklists
        # of real names instead of a free-text box — see :mod:`edbvocab`
        "vocab": mod.edb_vocab,
        "condition_kinds": [{"kind": k, "args": list(a),
                             "help": CONDITION_HELP.get(k, "")}
                            for k, a in CONDITION_ARGS.items()],
        "vanilla_ui": bool(config.get_vanilla_ui_root()),
        "warnings": edb.warnings[:20],
        # the new-tree form: what a name may start with, what the tool will and
        # will not do to a whole tree, and the two limits it warns about
        "prefixes": [dict(p) for p in TREE_PREFIXES],
        "actions": dict(TREE_ACTIONS),
        "refused": dict(TREE_REFUSED),
        "max_levels": VANILLA_MAX_LEVELS,
        "max_upgrades": MAX_UPGRADES,
        "default_requires": _default_requires(mod),
    }


def detail(mod, name: str, culture: str = "", bl: "BuildingLine" = None) -> dict:
    """One building line in full — every level, capability and recruit pool.

    Unlike the browser grid this carries every culture's name and description
    (``loc_all``), because the editor has to be able to show and write any of
    them without going back to the server.

    ``bl`` overrides the mod's own parse of the line. Code View passes the line
    it just re-read out of hand-edited text, so the boxes can be redrawn from
    text that is not on disk yet, while art, localisation and the unit index —
    none of which live in the block — still come from the mod.
    """
    bl = bl if bl is not None else mod.edb.get(name)
    if bl is None:
        raise KeyError(name)
    units = _units_index(mod)
    vanilla = config.get_vanilla_ui_root()
    #: Only the units this line can actually train, keyed by lower-cased type.
    #: Sent once for the whole line rather than inlined per pool — a big barracks
    #: has hundreds of pools and most of them name the same handful of units.
    referenced: Dict[str, dict] = {}
    levels = []
    for blk in bl.blocks:
        caps = [_cap_payload(c) for c in blk.capabilities]
        fcaps = [_cap_payload(c) for c in blk.faction_capabilities]
        for c in caps + fcaps:
            pool = c.get("pool")
            if pool:
                key = pool["unit"].lower()
                info = units.get(key)
                referenced[key] = info or {"type": pool["unit"], "name": pool["unit"],
                                           "missing": True}
        # which cultures actually have art for this level, so the UI can offer a
        # culture switcher that only lists the ones that will show something
        art = {}
        for c in mod.cultures:
            small, s_src = find_icon(mod, c, blk.name, "small", vanilla)
            large, l_src = find_icon(mod, c, blk.name, "large", vanilla)
            if small or large:
                art[c] = {"small": s_src, "large": l_src}
        best = _best_loc(mod, blk.name, culture)
        levels.append({
            "name": blk.name,
            "label": _label(mod, blk.name, "", culture),
            "loc": _loc_of(mod, blk.name),
            "loc_all": _loc_all(mod, blk.name),
            # which culture's record the label above came from, so the editor
            # opens on the text you are actually looking at
            "loc_culture": best["culture"],
            "settlement": blk.settlement,
            "requires": blk.requires,
            "conditions": clause_payload(blk.requires),
            "factions": clause_factions(blk.requires),
            "scalars": dict(blk.scalars),
            "upgrades": list(blk.upgrades),
            # the same list taken apart: an upgrade entry may carry its own
            # clause (`wooden_wall requires factions { … }` — 41 of the 771 in
            # the installed mods), and the editor needs it as conditions to put
            # a picker on it rather than a read-only chip. The strings above are
            # still what a save sends, so nothing else has to change shape.
            "upgrade_paths": [
                {"name": upgrade_name(u),
                 "requires": _split_requires(u)[1],
                 "conditions": clause_payload(_split_requires(u)[1])}
                for u in blk.upgrades],
            "capabilities": caps,
            "faction_capabilities": fcaps,
            "has_faction_capability": blk.fcap_span != (0, 0),
            "art": art,
            # factions this level could offer too many units at once — see
            # recruitment_pressure. The page recomputes it as pools are edited;
            # this is what it starts from.
            "recruit_pressure": recruitment_pressure(blk, mod.faction_cultures),
        })
    return {
        "mod": mod.name,
        "units": referenced,
        "name": bl.name,
        "culture": culture,
        "cultures": list(mod.cultures),
        "label": _label(mod, bl.name + "_name", bl.name, culture),
        "convert_to": bl.convert_to,
        "religion": bl.religion,
        "extras": dict(bl.extras),
        "settlement": bl.settlement,
        "levels_order": list(bl.levels),
        "levels": levels,
        "plugins": [{"name": p.name, "levels": p.levels} for p in bl.plugins],
    }
