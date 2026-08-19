"""Mod abstraction: locate the data files of one M2TW mod and lazily parse them.

A mod is a folder containing ``data/``. We resolve the canonical file paths,
discover faction folders (for icon lookup / UI grouping) and expose parsed
EDU / localisation / modeldb databases on demand.
"""
from __future__ import annotations

import os
from functools import cached_property
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import (buildings as buildings_mod, edu, engines as engines_mod,
               eop as eop_mod, localization, luascan, modeldb,
               mounts as mounts_mod, projectiles as projectiles_mod,
               sounds as sounds_mod)


class Mod:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.data = self.root / "data"
        if not self.data.is_dir():
            raise FileNotFoundError(f"no data/ folder under {self.root}")
        # folder -> (its mtime when listed, {lower-case filename: path}). See
        # :meth:`_dir_index`.
        self._icon_dirs: Dict[Path, Tuple[int, Dict[str, Path]]] = {}

    @property
    def name(self) -> str:
        return self.root.name

    # ---- canonical file paths ------------------------------------------
    @property
    def edu_path(self) -> Path:
        return self.data / "export_descr_unit.txt"

    @property
    def export_units_path(self) -> Path:
        return self.data / "text" / "export_units.txt"

    @property
    def modeldb_path(self) -> Path:
        return self.data / "unit_models" / "battle_models.modeldb"

    @property
    def ui_units_dir(self) -> Path:
        return self.data / "ui" / "units"

    @property
    def ui_unit_info_dir(self) -> Path:
        return self.data / "ui" / "unit_info"

    @property
    def unit_models_dir(self) -> Path:
        return self.data / "unit_models"

    @property
    def descr_mount_path(self) -> Path:
        return self.data / "descr_mount.txt"

    @property
    def descr_projectile_path(self) -> Path:
        return self.data / "descr_projectile.txt"

    @property
    def descr_engines_path(self) -> Path:
        return self.data / "descr_engines.txt"

    @property
    def descr_mounted_engines_path(self) -> Path:
        return self.data / "descr_mounted_engines.txt"

    @property
    def descr_engine_skeleton_path(self) -> Path:
        return self.data / "descr_engine_skeleton.txt"

    @property
    def expanded_path(self) -> Path:
        return self.data / "text" / "expanded.txt"

    @property
    def eds_path(self) -> Path:
        """The unit voice bank (``export_descr_sounds_units_voice.txt``)."""
        return self.data / sounds_mod.EDS_REL

    @property
    def edct_path(self) -> Path:
        """Character traits (``export_descr_character_traits.txt``)."""
        return self.data / "export_descr_character_traits.txt"

    @property
    def eda_path(self) -> Path:
        """Ancillaries (``export_descr_ancillaries.txt``)."""
        return self.data / "export_descr_ancillaries.txt"

    @property
    def edb_path(self) -> Path:
        """The settlement-building database (``export_descr_buildings.txt``)."""
        return self.data / buildings_mod.EDB_REL

    @property
    def building_loc_path(self) -> Path:
        return self.data / buildings_mod.LOC_REL

    def drop_caches(self) -> None:
        """Forget every cached read of this mod's files, after writing to them.

        Derived from the class's own ``cached_property`` set, never from a list
        of names. Two hand-written lists lived in ``edit`` and ``transfer`` and
        had drifted to 17 and 14 of the 23: ``ownership_factions`` is built from
        ``self.edu.units`` and was not among them while ``edu`` was, so after an
        edit it went on answering out of the EDU that had just been replaced.
        A property added later cannot be forgotten to be listed here.
        """
        for klass in type(self).__mro__:
            for name, attr in vars(klass).items():
                if isinstance(attr, cached_property):
                    self.__dict__.pop(name, None)

    # ---- parsed databases (cached) -------------------------------------
    @cached_property
    def edu(self) -> edu.EduFile:
        """Every unit the mod defines: the EDU *plus* its M2TWEOP unit files.

        Merged into one list on purpose — the unit picker, the transfer planner,
        the editor, the voice bank and the modeldb cleanup all want the mod's real
        roster, and an EOP unit that was invisible to the cleanup is exactly how a
        still-used battle model gets deleted. Each EOP unit keeps ``is_eop`` and
        the file it came from so writes go back to the right place.
        """
        parsed = edu.parse_file(self.edu_path)
        units, preambles = eop_mod.parse(self)
        parsed.units.extend(units)
        parsed.eop_preambles = preambles
        return parsed

    @cached_property
    def eop_dirs(self) -> List[Path]:
        """Folders this mod's M2TWEOP unit files are read from (may be empty)."""
        return eop_mod.eop_dirs(self)

    @cached_property
    def lua_files(self) -> List[Path]:
        """Every ``.lua`` script in the mod. Cached — finding them is a tree walk."""
        return luascan.lua_files(self)

    @cached_property
    def lua_tokens(self) -> Dict[str, "luascan.LuaHit"]:
        """Every identifier the mod's ``.lua`` scripts name -> where it was found.

        Cached on the mod because both the modeldb audit and the cleanup that
        follows it need the same answer, and re-walking a big mod's scripts for
        the second one is pure waste.
        """
        return luascan.scan(self)

    @cached_property
    def loc(self) -> localization.Localization:
        """Unit names and descriptions, read through the compiled cache if needed.

        The game reads ``export_units.txt.strings.bin``, not the ``.txt``, and a
        released mod can ship only the compiled one. Falling back to it means a
        mod like that shows real unit names here instead of bare dictionary keys.
        """
        if self.export_units_path.exists():
            return localization.parse_file(self.export_units_path)
        return self.loc_from_bin(self.export_units_path)

    @staticmethod
    def loc_from_bin(txt_path: Path, descr_suffix: str = "_descr"
                     ) -> localization.Localization:
        """A :class:`Localization` built from a ``.txt``'s compiled ``.strings.bin``.

        Empty when there is no readable archive — the callers all treat a missing
        localisation as "show the code name", which is the right answer anyway.
        """
        from . import stringsbin
        pairs = stringsbin.load_pairs(stringsbin.bin_path_for(txt_path))
        if not pairs:
            return localization.Localization()
        short = descr_suffix + "_short"
        entries: Dict[str, localization.LocEntry] = {}
        for key, value in pairs.items():
            if key.endswith(short):
                entries.setdefault(key[: -len(short)],
                                   localization.LocEntry()).descr_short = value
            elif key.endswith(descr_suffix):
                entries.setdefault(key[: -len(descr_suffix)],
                                   localization.LocEntry()).descr = value
            else:
                entries.setdefault(key, localization.LocEntry()).name = value
        return localization.Localization(entries=entries)

    @cached_property
    def modeldb(self) -> modeldb.ModelDb:
        return modeldb.parse_file(self.modeldb_path)

    @cached_property
    def mount_file(self) -> "mounts_mod.MountFile":
        """Parsed data/descr_mount.txt (blocks kept verbatim for transfers)."""
        return mounts_mod.parse_file(self.descr_mount_path)

    @cached_property
    def mounts(self) -> Dict[str, str]:
        """Map mount name -> battle-model name, from data/descr_mount.txt."""
        return {m.type: m.model.lower() for m in self.mount_file.mounts if m.model}

    def mount_model(self, mount_name: str) -> Optional[str]:
        m = self.mount_file.get(mount_name)
        return m.model.lower() if m and m.model else None

    def mount_def(self, mount_name: str):
        """The full mount definition block, or None."""
        return self.mount_file.get(mount_name)

    @cached_property
    def projectile_file(self) -> "projectiles_mod.ProjectileFile":
        """Parsed data/descr_projectile.txt (blocks kept verbatim for transfers)."""
        return projectiles_mod.parse_file(self.descr_projectile_path)

    def projectile_def(self, name: str):
        """The full projectile definition block, or None."""
        return self.projectile_file.get(name)

    @cached_property
    def engine_file(self) -> "engines_mod.EngineFile":
        """Parsed data/descr_engines.txt (blocks kept verbatim for transfers)."""
        return engines_mod.parse_file(self.descr_engines_path)

    @cached_property
    def mounted_engine_file(self) -> "engines_mod.EngineFile":
        """Parsed data/descr_mounted_engines.txt (same block format)."""
        return engines_mod.parse_file(self.descr_mounted_engines_path)

    @cached_property
    def engine_skeleton_file(self) -> "engines_mod.EngineSkeletonFile":
        """Parsed data/descr_engine_skeleton.txt."""
        return engines_mod.parse_skeleton_file(self.descr_engine_skeleton_path)

    def engine_defs(self, name: str):
        """Every descr_engines block for an engine type ([] when absent).

        One type can span several blocks (one per culture / variant), so a
        transfer must carry all of them.
        """
        return self.engine_file.get_all(name)

    def mounted_engine_defs(self, name: str):
        return self.mounted_engine_file.get_all(name)

    def engine_skeleton_def(self, name: str):
        """The descr_engine_skeleton block for a skeleton name, or None."""
        return self.engine_skeleton_file.get(name)

    @cached_property
    def sounds(self) -> "sounds_mod.SoundBank":
        """Parsed voice bank (lines kept verbatim so edits are splices)."""
        return sounds_mod.parse_file(self.eds_path)

    @cached_property
    def edb(self) -> "buildings_mod.EdbFile":
        """Parsed export_descr_buildings.txt (lines verbatim, edits are splices)."""
        return buildings_mod.parse_file(self.edb_path)

    @cached_property
    def building_loc(self) -> localization.Localization:
        """Building names/descriptions — same format as export_units.txt, but
        keyed with ``_desc`` / ``_desc_short`` instead of ``_descr``."""
        p = self.building_loc_path
        if not p.exists():
            return self.loc_from_bin(p, descr_suffix="_desc")
        try:
            return localization.parse_file(p, descr_suffix="_desc")
        except (OSError, UnicodeError):
            return localization.Localization()

    @cached_property
    def edb_vocab(self) -> Dict[str, object]:
        """What a building's ``requires`` clause may name (see :mod:`edbvocab`).

        Cached on the mod: building it walks the campaign scripts for event
        counters, which is seconds on a big mod, and the buildings browser asks
        for it on every load.
        """
        from . import edbvocab
        return edbvocab.build(self)

    @cached_property
    def cultures(self) -> List[str]:
        """Culture folders that hold building icons (``data/ui/<culture>/buildings``)."""
        return buildings_mod.cultures_of(self)

    @cached_property
    def faction_cultures(self) -> Dict[str, str]:
        """faction slot -> culture, from data/descr_sm_factions.txt."""
        return buildings_mod.faction_cultures(self)

    def find_building_icon(self, culture: str, level: str, kind: str = "small",
                           vanilla_root=None):
        """(path, source) for one building icon — see :func:`buildings.find_icon`."""
        return buildings_mod.find_icon(self, culture, level, kind, vanilla_root)

    @cached_property
    def effect_sets(self) -> set:
        """Effect-set names this mod defines (for the projectile effect check)."""
        return projectiles_mod.effect_sets(self.data)

    @cached_property
    def edu_vocab(self) -> Dict[str, object]:
        """Drop-down values for the guided EDU editor (see :mod:`vocab`).

        Cached because building it walks every unit in the EDU: the guided editor
        asks for it each time a unit is opened.
        """
        from . import vocab as vocab_mod
        return vocab_mod.build(self)

    @cached_property
    def faction_names(self) -> Dict[str, str]:
        """Map faction slot (code) -> localized display name, from text/expanded.txt.

        e.g. {'poland': 'Dol Guldur', 'england': 'Mordor'}. Empty if the file is absent.
        """
        import re
        out: Dict[str, str] = {}
        p = self.expanded_path
        if not p.exists():
            # same read-through as `loc`: a released mod may ship only the
            # compiled expanded.txt.strings.bin, and faction names are worth having
            from . import stringsbin
            return {k.lower(): v for k, v in
                    stringsbin.load_pairs(stringsbin.bin_path_for(p)).items()}
        try:
            txt = p.read_text(encoding="utf-16")
        except (OSError, UnicodeError):
            try:
                txt = p.read_text(encoding="latin-1")
            except OSError:
                return out
        for line in txt.splitlines():
            m = re.match(r"^\s*\{([^}]+)\}(.*)$", line.strip())
            if m:
                out[m.group(1).strip().lower()] = m.group(2).strip()
        return out

    def faction_label(self, slot: str) -> str:
        name = self.faction_names.get(slot.lower())
        return f"{name} ({slot})" if name else slot

    # ---- faction discovery ---------------------------------------------
    @cached_property
    def icon_factions(self) -> List[str]:
        """Faction folders present under data/ui/units."""
        if not self.ui_units_dir.is_dir():
            return []
        return sorted(p.name for p in self.ui_units_dir.iterdir() if p.is_dir())

    @cached_property
    def ownership_factions(self) -> List[str]:
        """Distinct ownership factions referenced by units (excludes 'slave')."""
        seen: Dict[str, int] = {}
        for u in self.edu.units:
            for f in u.ownership:
                if f == "slave":
                    continue
                seen[f] = seen.get(f, 0) + 1
        return sorted(seen, key=lambda f: (-seen[f], f))

    # ---- icon resolution -----------------------------------------------
    def find_unit_card(self, unit: "edu.Unit") -> Optional[Path]:
        """Locate the in-game unit card: data/ui/units/<faction>/#<dict>.tga."""
        return self._find_icon(self.ui_units_dir, unit.card_dirs(),
                               f"#{unit.dictionary}", (".tga", ".dds"))

    def find_unit_info(self, unit: "edu.Unit") -> Optional[Path]:
        """Locate the info card: data/ui/unit_info/<faction>/<dict>_info.tga.

        Uses ``info_pic_dir`` (falling back to ownership / mercenary status), NOT
        ``card_pic_dir`` — a unit can pin its card to ``mercs`` while its info
        card stays looked up under its ownership faction, and conflating the two
        made the info card silently unfindable for exactly that (common) case.
        """
        return self._find_icon(self.ui_unit_info_dir, unit.info_dirs(),
                               f"{unit.dictionary}_info", (".tga", ".dds"))

    def _dir_index(self, fdir: Path) -> Dict[str, Path]:
        """``lower-case filename -> path`` for one icon folder, listed once.

        The lookup below has to be case-insensitive (a card named ``#Foo.tga``
        for a dictionary of ``foo`` is common, and Linux would miss it), and it
        used to get that by globbing the whole faction folder per extension per
        candidate faction. Building the list of a mod's unit cards then cost
        **224,712 globs** and 4.8 of the 4.9 seconds it took to answer
        ``/api/units`` for Divide and Conquer — the visible half of "switching
        mods doesn't switch the units".

        One listing per folder replaces all of it. The folder's mtime is the
        key, so a card that appears while the tool is running is still picked up:
        adding or removing a file changes the folder's mtime, and the next
        lookup re-lists it.
        """
        try:
            stamp = fdir.stat().st_mtime_ns
        except OSError:
            return {}
        hit = self._icon_dirs.get(fdir)
        if hit is not None and hit[0] == stamp:
            return hit[1]
        index: Dict[str, Path] = {}
        try:
            with os.scandir(fdir) as it:
                for entry in it:
                    if entry.is_file():
                        index.setdefault(entry.name.lower(), Path(entry.path))
        except OSError:
            return {}
        self._icon_dirs[fdir] = (stamp, index)
        return index

    def _find_icon(self, base: Path, factions: List[str], stem: str,
                   exts: tuple) -> Optional[Path]:
        if not base.is_dir():
            return None
        stem_lower = stem.lower()
        for fac in factions:
            index = self._dir_index(base / fac)
            if not index:
                continue
            for ext in exts:
                hit = index.get(stem_lower + ext)
                if hit is not None:
                    return hit
        return None
