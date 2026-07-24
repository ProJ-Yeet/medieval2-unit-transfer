"""Mod abstraction: locate the data files of one M2TW mod and lazily parse them.

A mod is a folder containing ``data/``. We resolve the canonical file paths,
discover faction folders (for icon lookup / UI grouping) and expose parsed
EDU / localisation / modeldb databases on demand.
"""
from __future__ import annotations

from functools import cached_property
from pathlib import Path
from typing import Dict, List, Optional

from . import (edu, engines as engines_mod, localization, modeldb,
               mounts as mounts_mod, projectiles as projectiles_mod)


class Mod:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.data = self.root / "data"
        if not self.data.is_dir():
            raise FileNotFoundError(f"no data/ folder under {self.root}")

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

    # ---- parsed databases (cached) -------------------------------------
    @cached_property
    def edu(self) -> edu.EduFile:
        return edu.parse_file(self.edu_path)

    @cached_property
    def loc(self) -> localization.Localization:
        return localization.parse_file(self.export_units_path)

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
    def effect_sets(self) -> set:
        """Effect-set names this mod defines (for the projectile effect check)."""
        return projectiles_mod.effect_sets(self.data)

    @cached_property
    def faction_names(self) -> Dict[str, str]:
        """Map faction slot (code) -> localized display name, from text/expanded.txt.

        e.g. {'poland': 'Dol Guldur', 'england': 'Mordor'}. Empty if the file is absent.
        """
        import re
        out: Dict[str, str] = {}
        p = self.expanded_path
        if not p.exists():
            return out
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
        return self._find_icon(self.ui_units_dir, unit.icon_factions(),
                               f"#{unit.dictionary}", (".tga", ".dds"))

    def find_unit_info(self, unit: "edu.Unit") -> Optional[Path]:
        """Locate the info card: data/ui/unit_info/<faction>/<dict>_info.tga."""
        # info cards prefer the 'merc' folder as universal fallback (not 'mercs')
        facs = unit.icon_factions()
        return self._find_icon(self.ui_unit_info_dir, facs,
                               f"{unit.dictionary}_info", (".tga", ".dds"))

    def _find_icon(self, base: Path, factions: List[str], stem: str,
                   exts: tuple) -> Optional[Path]:
        if not base.is_dir():
            return None
        stem_lower = stem.lower()
        for fac in factions:
            fdir = base / fac
            if not fdir.is_dir():
                continue
            for ext in exts:
                cand = fdir / (stem + ext)
                if cand.exists():
                    return cand
                # case-insensitive fallback (Windows is usually fine, be safe)
                for p in fdir.glob("*" + ext):
                    if p.stem.lower() == stem_lower:
                        return p
        return None
