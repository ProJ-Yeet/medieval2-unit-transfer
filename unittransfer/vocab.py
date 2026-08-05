"""Value vocabularies for the guided EDU field editor.

The guided editor turns every EDU line into named boxes and drop-downs, and a
drop-down is only useful if it offers the values *this mod* actually accepts.
Two sources feed each list:

* the engine's own fixed sets (weapon type, damage type, formation, discipline,
  …) — these are hardcoded in the executable, so they are hardcoded here too;
* the mod's own files (``descr_projectile``, ``descr_mount``, ``descr_engines``,
  the modeldb, …) *plus* every value its EDU already uses.

The second half matters more than it sounds. Mods invent their own attributes
(``extreme_range``, ``garrison_unit``), banners (``crusade_cavalry``) and accents
(``Sindarin``), and a drop-down that only knew the vanilla set would quietly
invite the user to throw them away. So a harvested value is always offered, and
every list is advisory: the guided editor lets you type a value that is in no
list, exactly as the raw editor does.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

from . import edu as edu_mod

# ---------------------------------------------------------------------------
# fixed engine sets (from the executable's own tables + the EDU file header)
# ---------------------------------------------------------------------------
CATEGORY = ["infantry", "cavalry", "siege", "ship", "handler", "non_combatant"]
CLASS = ["light", "heavy", "missile", "spearmen", "skirmish"]
VOICE_TYPE = ["Heavy", "Light", "General"]
FORMATION_MAIN = ["square", "horde"]
FORMATION_SPECIAL = ["", "schiltrom", "shield_wall", "phalanx", "testudo", "wedge"]
DISCIPLINE = ["low", "normal", "disciplined", "impetuous"]
TRAINING = ["untrained", "trained", "highly_trained"]
WEAPON_TYPE = ["no", "melee", "thrown", "missile", "siege_missile"]
TECH_TYPE = ["melee_simple", "melee_blade", "missile_mechanical",
             "missile_gunpowder", "artillery_mechanical", "artillery_gunpowder"]
DAMAGE_TYPE = ["piercing", "blunt", "slashing", "fire"]
WEAPON_SOUND = ["none", "spear", "sword", "axe", "mace", "knife"]
ARMOUR_SOUND = ["flesh", "leather", "metal"]
MOUNT_CLASS = ["horse", "camel", "elephant"]

# stat_pri_attr / stat_sec_attr / stat_ter_attr
WEAPON_ATTR = [
    "ap", "bp", "spear", "light_spear", "long_pike", "short_pike",
    "spear_bonus_2", "spear_bonus_4", "spear_bonus_6", "spear_bonus_8",
    "spear_bonus_10", "spear_bonus_12", "thrown", "launching", "area", "prec",
]

# the `attributes` line. Ability/behaviour flags first, AI hints last — the
# guided editor groups them under those headings.
UNIT_ATTR = [
    "sea_faring", "can_swim", "can_horde", "can_withdraw", "can_run_amok",
    "can_feign_rout", "can_formed_charge", "can_sap", "cannot_skirmish",
    "start_not_skirmishing", "fire_by_rank", "hardy", "very_hardy",
    "hide_forest", "hide_improved_forest", "hide_long_grass", "hide_anywhere",
    "frighten_foot", "frighten_mounted", "power_charge", "knight",
    "general_unit", "general_unit_upgrade", "mercenary_unit", "free_upkeep_unit",
    "is_peasant", "no_custom", "gunpowder_unit", "gunpowder_artillery_unit",
    "stakes", "warcry", "screeching_women", "druid", "cantabrian_circle",
    "command", "has_eagles", "legionary_name", "may_charge_without_orders",
    "has_dogs", "has_pigs", "wagon_fort",
]
# AI usage hints — no effect on the unit itself, they tell the AI what it is
AI_ATTR = [
    "peasant", "pike", "crossbow", "gunmen", "guncavalry", "artillery",
    "cannon", "rocket", "mortar", "explode", "incendiary", "standard",
    "foot_archers", "horse_archers", "foot_javelinmen", "horse_javelinmen",
    "foot_slingers", "foot_pila", "foot_darts", "foot_francisca",
]

BANNER_FACTION = ["main_infantry", "main_cavalry", "main_missile", "main_spear"]
BANNER_HOLY = ["crusade", "jihad"]

# fixed sets keyed the way the page asks for them
STATIC: Dict[str, List[str]] = {
    "category": CATEGORY,
    "class": CLASS,
    "voice_type": VOICE_TYPE,
    "formation_main": FORMATION_MAIN,
    "formation_special": FORMATION_SPECIAL,
    "discipline": DISCIPLINE,
    "training": TRAINING,
    "weapon_type": WEAPON_TYPE,
    "tech_type": TECH_TYPE,
    "damage_type": DAMAGE_TYPE,
    "weapon_sound": WEAPON_SOUND,
    "armour_sound": ARMOUR_SOUND,
    "mount_class": MOUNT_CLASS,
    "weapon_attr": WEAPON_ATTR,
    "unit_attr": UNIT_ATTR,
    "ai_attr": AI_ATTR,
}


# ---------------------------------------------------------------------------
# reading the mod's own files
# ---------------------------------------------------------------------------
_TYPE_RE = re.compile(r"^\s*type\s+(.+?)\s*$", re.IGNORECASE)


def _type_names(path: Path) -> List[str]:
    """``type <name>`` lines of a simple descr_* file, in file order.

    Used for ``descr_ship.txt`` and ``descr_animals.txt``, which this tool has no
    reason to parse properly — the editor only needs the names.
    """
    try:
        text = path.read_text(encoding=edu_mod.ENCODING, errors="replace")
    except OSError:
        return []
    out: List[str] = []
    seen = set()
    for line in text.splitlines():
        s = line.split(";", 1)[0]
        m = _TYPE_RE.match(s)
        if not m:
            continue
        name = m.group(1).strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
    return out


def _merge(*lists) -> List[str]:
    """Concatenate, drop blanks and case-insensitive repeats, keep first order."""
    out: List[str] = []
    seen = set()
    for lst in lists:
        for v in lst or ():
            v = (v or "").strip()
            if not v or v.lower() in seen:
                continue
            seen.add(v.lower())
            out.append(v)
    return out


def _csv(value: str) -> List[str]:
    return [p.strip() for p in value.split(",") if p.strip()]


def _harvest(mod) -> Dict[str, List[str]]:
    """Every value the mod's own EDU already uses, per drop-down.

    One pass over the units: re-parsing 2000 blocks per drop-down would be silly,
    and the result is cached on the Mod anyway.
    """
    got: Dict[str, List[str]] = {k: [] for k in (
        "attributes", "weapon_attr", "accent", "banner_faction", "banner_holy",
        "banner_unit", "projectile", "mount", "engine", "mounted_engine",
        "ship", "animal", "model", "voice_type", "category", "class",
        "weapon_sound", "armour_sound", "tech_type", "damage_type",
        "weapon_type", "formation_special", "fire_effect")}
    for unit in mod.edu.units:
        for label, value in edu_mod.block_fields(unit.raw):
            key = label.split("#")[0]
            if key == "attributes":
                got["attributes"] += _csv(value)
            elif key in ("stat_pri_attr", "stat_sec_attr", "stat_ter_attr"):
                got["weapon_attr"] += [v for v in _csv(value) if v.lower() != "no"]
            elif key == "accent":
                got["accent"].append(value.strip())
            elif key == "banner faction":
                got["banner_faction"].append(value.strip())
            elif key == "banner holy":
                got["banner_holy"].append(value.strip())
            elif key == "banner unit":
                got["banner_unit"].append(value.strip())
            elif key in ("mount", "engine", "mounted_engine", "ship", "animal"):
                got[key].append(value.strip())
            elif key == "voice_type":
                got["voice_type"].append(value.strip())
            elif key in ("category", "class"):
                got[key].append(value.strip())
            elif key in ("soldier", "officer", "armour_ug_models"):
                got["model"] += _csv(value) if key != "soldier" else _csv(value)[:1]
            elif key == "formation":
                parts = _csv(value)
                if len(parts) >= 7:
                    got["formation_special"].append(parts[6])
            elif key in ("stat_pri", "stat_sec", "stat_ter"):
                parts = _csv(value)
                if len(parts) >= 9:
                    got["weapon_type"].append(parts[5])
                    got["tech_type"].append(parts[6])
                    got["damage_type"].append(parts[7])
                    got["weapon_sound"].append(parts[8])
                    if parts[2].lower() != "no":
                        got["projectile"].append(parts[2])
                # the optional "effect when the weapon fires" slot, present only
                # when the line carries 12 values instead of 11
                if len(parts) >= 12:
                    got["fire_effect"].append(parts[9])
            elif key in ("stat_pri_armour", "stat_sec_armour"):
                parts = _csv(value)
                if parts:
                    got["armour_sound"].append(parts[-1])
    return got


def build(mod) -> Dict[str, object]:
    """The whole vocabulary payload for one mod."""
    got = _harvest(mod)

    def defined(getter, fallback=()):
        try:
            return getter()
        except Exception:
            return list(fallback)

    projectiles = defined(lambda: sorted(mod.projectile_file.by_name()))
    mounts = defined(lambda: sorted(mod.mounts))
    engines = defined(lambda: sorted(mod.engine_file.by_type()))
    mounted = defined(lambda: sorted(mod.mounted_engine_file.by_type()))
    models = defined(lambda: sorted(e.name for e in mod.modeldb.entries))
    accents = defined(lambda: mod.sounds.accents())
    effects = defined(lambda: sorted(mod.effect_sets))
    ships = _type_names(mod.data / "descr_ship.txt")
    animals = _type_names(mod.data / "descr_animals.txt")

    out: Dict[str, object] = dict(STATIC)
    out.update({
        # engine sets first, then whatever else the mod turned out to use
        "category": _merge(CATEGORY, got["category"]),
        "class": _merge(CLASS, got["class"]),
        "voice_type": _merge(VOICE_TYPE, got["voice_type"]),
        "formation_special": _merge(FORMATION_SPECIAL, got["formation_special"]),
        "weapon_type": _merge(WEAPON_TYPE, got["weapon_type"]),
        "tech_type": _merge(TECH_TYPE, got["tech_type"]),
        "damage_type": _merge(DAMAGE_TYPE, got["damage_type"]),
        "weapon_sound": _merge(WEAPON_SOUND, got["weapon_sound"]),
        "armour_sound": _merge(ARMOUR_SOUND, got["armour_sound"]),
        "weapon_attr": _merge(WEAPON_ATTR, got["weapon_attr"]),
        "unit_attr": _merge(UNIT_ATTR, AI_ATTR, got["attributes"]),
        # mod files lead here: these ARE the mod's definitions, and a name the
        # EDU uses but no file defines is a broken reference the editor warns on
        "projectile": _merge(projectiles, got["projectile"]),
        "mount": _merge(mounts, got["mount"]),
        "mount_class": _merge(MOUNT_CLASS, mounts, got["mount"]),
        "engine": _merge(engines, got["engine"]),
        "mounted_engine": _merge(mounted, got["mounted_engine"]),
        "ship": _merge(ships, got["ship"]),
        "animal": _merge(animals, got["animal"]),
        "model": _merge(models, got["model"]),
        "accent": _merge(accents, got["accent"]),
        "banner_faction": _merge(BANNER_FACTION, got["banner_faction"]),
        "banner_holy": _merge(BANNER_HOLY, got["banner_holy"]),
        "banner_unit": _merge(got["banner_unit"]),
        "fire_effect": _merge(effects, got["fire_effect"]),
    })
    # which names are actually DEFINED by a file, so the editor can flag a
    # reference to something that does not exist rather than just offering a list
    out["defined"] = {
        "projectile": projectiles, "mount": mounts, "engine": engines,
        "mounted_engine": mounted, "ship": ships, "animal": animals,
        "model": models,
    }
    return out
