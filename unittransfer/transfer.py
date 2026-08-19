"""Cross-mod unit transfer (Stage 4): interactive, in-place, undoable.

Pipeline:
  plan_transfer(source, unit_type, dest, options) -> TransferPlan
      resolves the dependency set, decides bmdb dedup/rename per model, detects the
      unit-name conflict, and collects warnings (excluded secondaries, missing
      skeletons, missing files).
  apply_transfer(plan) -> record dict
      writes changes DIRECTLY into the destination mod, backing up every touched
      file first, and appends a log record containing the undo manifest.
  undo(transfer_id) -> restores backups / deletes created files.

Options let the user include or exclude officer / crew / mount models; excluded
secondaries keep their original EDU name and raise a warning (they must already
exist in the destination). bmdb rule: same name + identical content -> reuse;
same name + different content -> the incoming entry is renamed and every EDU
model reference is updated to match.
"""
from __future__ import annotations

import filecmp
import logging
import shutil
from dataclasses import dataclass, field, asdict, replace as dc_replace
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import (config, edu as edu_mod, engines as engines_mod, eop, localization,
               modeldb, mounts, projectiles as projectiles_mod, sounds)
from . import keyblock as kb
from .logutil import block, counted, file_op, fingerprint, log
from .mod import Mod


# Human-readable names of the EDU field groups a base / replaced unit can supply,
# keyed by the group key used in `base_field_groups`.
_MODEL_GROUP_NAMES = {
    "soldier": "soldier line",
    "officer": "officers",
    "mount": "mount",
    "armour_ug_models": "armour upgrade models",
    "ship": "crew",
}


# --------------------------------------------------------------------------
@dataclass
class TransferOptions:
    include_officers: bool = True
    include_mount: bool = True
    include_crew: bool = True          # ship / engine / mounted_engine / animal group
    include_projectile: bool = True    # copy the projectile def(s) into descr_projectile.txt
    # copy the siege-engine definition: the descr_engines.txt block(s), their
    # descr_engine_skeleton.txt entries, every mesh/bonemap/collision/reference-
    # points file they name, the textures baked into those meshes, and the engine
    # animations under animations/engine/.
    include_engine: bool = True
    # individual secondary MODEL names (officer/mount/crew) to force-exclude even
    # when their group is included — lets the user pick models one by one instead of
    # all-or-none. Lowercased model names. Excluded models keep their EDU name and
    # must already exist in the destination (same rule as an unticked group).
    exclude_models: List[str] = field(default_factory=list)
    # Where the transferred unit's EDU block is written in the destination:
    #   "auto"  mirror the source unit — an M2TWEOP unit stays an M2TWEOP unit
    #           when the destination has an EOP folder, otherwise it lands in the
    #           EDU (the destination is not running the extender, so a file in a
    #           folder nothing reads would just make the unit vanish)
    #   "eop"   force its own M2TWEOP unit file, which keeps it off the 500-unit
    #           vanilla cap — the reason to want this for a normal unit
    #   "edu"   force data/export_descr_unit.txt
    # See :mod:`unittransfer.eop`.
    eop_target: str = "auto"
    # What the transfer produces in the destination:
    #   "new"     the unit arrives as its OWN entry — a new unit type, a new
    #             dictionary entry, its own icons (the default)
    #   "replace" the unit is written INTO an existing destination unit named by
    #             `replace_type`: no new EDU entry, no new dictionary, no new
    #             localisation. The destination unit keeps its type, name,
    #             description, stats, ownership and era, and only its MODELS are
    #             swapped for the transferred unit's — one field at a time can be
    #             switched over via `field_overrides` (the composer's B buttons),
    #             and the card / info card only come across when asked for.
    # The replaced unit must be the same `kind()` as the transferred one, exactly
    # as a base unit must: swapping a cavalry model into an infantry entry gives a
    # unit whose animations and stats don't match its models.
    mode: str = "new"
    replace_type: Optional[str] = None
    # replace mode only: bring the source's unit card / info card across as the
    # replaced unit's (renamed to ITS dictionary, written into ITS faction
    # folders). Off by default — the replaced unit keeps the card it already has,
    # which is usually what "just give it better models" means.
    import_card: bool = False
    import_info_card: bool = False
    # unit-name conflict: "overwrite" | "rename" | "skip"
    on_conflict: str = "rename"
    new_type: Optional[str] = None     # required when on_conflict == "rename"
    new_dictionary: Optional[str] = None
    # "use another unit as base": a destination unit type whose stats/attrs are inherited
    base_type: Optional[str] = None
    # Which unit supplies each field group: "source" (default) or "base".
    # All need a base unit; each is offered only when the base actually has it.
    #   soldier_from -> the `soldier` line ONLY (model + count/mass/radius);
    #                   `armour_ug_models` always stays from the transferred unit
    #   officer_from -> every `officer` line
    #   mount_from   -> the `mount` line
    #   crew_from    -> `ship` / `engine` / `mounted_engine` / `animal`
    #   upgrade_from -> `armour_ug_models` (the armour-upgrade model list). Only
    #                   offered in replace mode; a base template leaves the
    #                   upgrade models with the transferred unit, as it always has.
    # A group taken from the base needs nothing copied — those models are already
    # in the destination.
    soldier_from: str = "source"
    officer_from: str = "source"
    mount_from: str = "source"
    crew_from: str = "source"
    upgrade_from: str = "source"
    # `mount_from == "base"` used to mean "ride the base unit's mount" — the
    # source's horse was left behind entirely. That is almost never what someone
    # picking a base wants: they pick one because the destination has the ANIMATIONS
    # for it, not because they wanted a different horse. So with this on (the
    # default) the source's mount comes across as its own descr_mount.txt block and
    # its own modeldb entry, and only its *animation set* is taken from the base's
    # mount — and only where the source's skeletons are missing from the
    # destination's modeldb, which is the case that would otherwise leave the mount
    # unanimated. Off = the old behaviour, the base's mount as-is.
    import_mount_with_base: bool = True
    # The officer version of the same three-way choice. Officers have their own
    # modeldb entries and so their own animation sets, so "port as is" (crash if
    # the destination lacks the skeleton), "port with the base's animations" and
    # "use the base's officers" are three different answers.
    import_officers_with_base: bool = True
    # manual per-field EDU overrides: {field_key: full value string}
    field_overrides: Dict[str, str] = field(default_factory=dict)
    # what to do about copied mesh/texture files:
    #   "mod_folder"   copy everything into unit_models/<source mod name> (default)
    #   "reroute"      copy everything into ``asset_reroute_dir`` instead
    #   "use_existing" keep the destination's differing files
    #   "overwrite"    replace them with the source's
    # The two relocating modes rewrite the bmdb entry paths to match, so nothing
    # can collide — hence mod_folder is the default. Byte-identical files are
    # always reused in the non-relocating modes.
    asset_conflict: str = "mod_folder"
    # data-relative target folder for "reroute" (e.g. "unit_models/MyFolder")
    asset_reroute_dir: Optional[str] = None
    # Icons (ui/units, ui/unit_info) are looked up by faction folder + dictionary
    # name, so they CANNOT be relocated — only keep or replace.
    icon_conflict: str = "use_existing"
    # Siege-engine files (siege_engines/, animations/engine/) can't be relocated
    # either: descr_engines paths could be rewritten, but each mesh has its texture
    # paths baked into the binary. Overwriting a shared file (e.g. a stock
    # siege_engines/textures/mangonel.texture) would re-skin the DESTINATION's own
    # engines, so "use_existing" is the default — keep the destination's version
    # and report the difference.  "overwrite" | "use_existing"
    engine_conflict: str = "use_existing"
    # Mercenary attribute: adds the `mercenary_unit` attribute to the EDU block
    # and gives the copied bmdb entries a `merc` texture record.
    make_mercenary: bool = False
    # Mercenary icon folders: puts the unit card / info card in the mercs/merc
    # folders (pinned via card_pic_dir/info_pic_dir), independent of the flag above.
    merc_icons: bool = False
    # Voice: where the transferred unit's selection barks come from.
    #   "base" copy the BASE unit's voice entry (the default — a unit built on
    #          another one should sound like it, and its accent/voice_type already
    #          come from the base, so the entry lands in a block that exists)
    #   "unit" copy some OTHER destination unit's entry, named by `sound_donor`
    #          (base one unit for stats, another for the voice)
    #   "none" write no voice entry at all
    # A copied voice also PINS the EDU's `accent` / `voice_type` to the donor's:
    # the entry is dead weight unless those two fields point at the same block.
    sound_mode: str = "base"
    sound_donor: Optional[str] = None


@dataclass
class AssetConflict:
    rel: str                 # path relative to data/ (same name + path in both mods)
    identical: bool          # True -> byte-for-byte equal (will be reused, no copy)
    src_size: int
    dst_size: int
    kind: str = "texture"    # "texture" | "mesh" | "icon"


@dataclass
class ModelAction:
    source_name: str
    action: str                        # "add" | "reuse_identical" | "rename"
    final_name: str                    # name used in destination
    reason: str = ""


@dataclass
class TransferPlan:
    unit_type: str
    dictionary: str
    source: Mod
    dest: Mod
    options: TransferOptions
    # unit conflict
    unit_conflict: bool = False
    resolved_type: str = ""            # type written into dest
    resolved_dict: str = ""            # dictionary written into dest
    skipped: bool = False
    # base templating
    base_unit: object = None                       # edu.Unit used as stat template (or None)
    base_error: str = ""                           # non-empty -> base invalid, block apply
    # "replace an existing unit": the destination unit whose block is rewritten in
    # place. "" in the normal (new unit) mode. When set, `base_unit` IS that unit —
    # replacing is a base template that also takes over the base's identity — and
    # `resolved_type` / `resolved_dict` are its own.
    replace_type: str = ""
    option_error: str = ""                         # non-empty -> options invalid, block apply
    icon_dir_overrides: Dict[str, str] = field(default_factory=dict)  # card/info_pic_dir fixes
    # EDU field groups taken wholesale from the base unit (officer / mount /
    # crew when their include box is off, and soldier when so chosen)
    base_field_groups: List[str] = field(default_factory=list)
    # models
    model_actions: List[ModelAction] = field(default_factory=list)
    model_renames: Dict[str, str] = field(default_factory=dict)   # old->new (for EDU rewrite)
    add_entries: List[Tuple[str, modeldb.ModelEntry]] = field(default_factory=list)  # (final_name, entry)
    # assets / icons
    asset_files: List[Tuple[Path, str]] = field(default_factory=list)   # (src_abs, rel_to_data)
    icon_files: List[Tuple[Path, str]] = field(default_factory=list)
    # files whose name+path already exist in the destination (byte-compared)
    asset_conflicts: List[AssetConflict] = field(default_factory=list)
    # mount definition (descr_mount.txt). Without this the EDU's `mount` field
    # points at nothing in the destination and the unit never appears in game.
    mount_action: str = ""           # "" | "add" | "reuse" | "rename" | "missing"
    mount_name: str = ""             # name written into the EDU
    mount_raw: str = ""              # block to append to the destination file
    mount_rename: Optional[Tuple[str, str]] = None   # (old, new)
    # "mount from base" + `import_mount_with_base`: the source's mount was brought
    # across anyway. `mount_anim_donor` is the base unit's mount modeldb entry
    # whose animation set the copied mount entry was given, and
    # `mount_skeletons_swapped` the source skeletons that were missing here and so
    # were replaced. Both empty when the source's own animations were kept.
    mount_from_base_import: bool = False
    mount_anim_donor: str = ""
    mount_skeletons_swapped: List[str] = field(default_factory=list)
    # The same three for the officers, which have their own modeldb entries and so
    # their own animation sets — see `officer_base_import`.
    officer_from_base_import: bool = False
    officer_anim_donor: str = ""
    officer_skeletons_swapped: List[str] = field(default_factory=list)
    # projectiles (descr_projectile.txt). rename map: old proj name -> resolved name
    # (only entries that were renamed on collision); raws to append; effect stats.
    projectile_renames: Dict[str, str] = field(default_factory=dict)
    projectile_raws: List[str] = field(default_factory=list)   # blocks to append
    projectile_actions: List[Tuple[str, str, str]] = field(default_factory=list)  # (name,action,detail)
    projectile_effects_blanked: int = 0    # effect lines rewritten to placeholder
    # siege engines (descr_engines.txt / descr_mounted_engines.txt /
    # descr_engine_skeleton.txt). See `_resolve_engines`.
    engine_actions: List[Tuple[str, str, str]] = field(default_factory=list)  # (name,action,detail)
    engine_renames: Dict[str, str] = field(default_factory=dict)   # EDU field key -> new engine name
    engine_raws: List[str] = field(default_factory=list)           # -> descr_engines.txt
    mounted_engine_raws: List[str] = field(default_factory=list)   # -> descr_mounted_engines.txt
    engine_skeleton_raws: List[str] = field(default_factory=list)  # -> descr_engine_skeleton.txt
    engine_skeleton_actions: List[Tuple[str, str, str]] = field(default_factory=list)
    engine_skeleton_renames: Dict[str, str] = field(default_factory=dict)
    # data-relative paths in asset_files that belong to an engine (they follow
    # `engine_conflict`, not `asset_conflict`, and are never relocated)
    engine_assets: List[str] = field(default_factory=list)
    # files an engine references that the SOURCE mod does not contain -> they come
    # from the vanilla game and are not ours to copy
    engine_vanilla_refs: List[str] = field(default_factory=list)
    # ...of those, the ones the DESTINATION *does* contain: the destination's own
    # override will be used instead of vanilla, which may not match the engine
    engine_dest_overrides: List[str] = field(default_factory=list)
    # projectiles an engine's `attack_stat` lines fire (merged into the unit's)
    engine_projectiles: List[str] = field(default_factory=list)
    # relocation (reroute / mod_folder): old data-rel path -> new data-rel path.
    # Applied to the copied files AND to the added bmdb entries' path strings.
    path_map: Dict[str, str] = field(default_factory=dict)
    reroute_dir: str = ""            # data-relative folder the assets were moved to
    # factions the copied bmdb entries must carry a texture for (set when a base
    # unit or an override changes ownership); empty means "leave textures alone"
    texture_factions: List[str] = field(default_factory=list)
    texture_donor: str = ""          # faction whose skin the new records clone
    mercenary: bool = False          # unit is being turned into a mercenary
    merc_icons: bool = False         # card/info card pinned to the mercs/merc folders
    # voice bank (export_descr_sounds_units_voice.txt). See `_resolve_sound`.
    sound_action: str = ""           # "" | "copy" | "none" | "missing" | "no_base"
    sound_donor: str = ""            # destination unit whose entry is copied
    sound_accent: str = ""           # accent/class the copy lands in — also forced
    sound_class: str = ""            # onto the EDU block's accent / voice_type
    sound_text: str = ""             # whole new voice-bank file ("" = unchanged)
    sound_detail: str = ""           # human-readable note for the summary
    # 1 if this transfer adds a NEW unit type to the destination EDU, else 0
    # (overwrite/skip add none) — drives the 500 vanilla unit-limit warning. A
    # unit written as an M2TWEOP unit adds none either: the cap is a property of
    # export_descr_unit.txt, and staying out of it is the whole point of EOP.
    dest_new_units: int = 1
    # M2TWEOP: absolute path of the unit file this transfer writes ("" = the unit
    # goes into data/export_descr_unit.txt like any other).
    eop_file: str = ""
    # An existing EOP unit this transfer overwrites, so its old file is rewritten
    # (or removed) instead of the EDU. "" when no such conflict.
    eop_replaced: str = ""
    # diagnostics
    excluded_secondaries: List[str] = field(default_factory=list)
    missing_models: List[str] = field(default_factory=list)
    missing_skeletons: List[str] = field(default_factory=list)
    # A missing skeleton is only actionable if you know WHICH copied model asks for
    # it: the soldier line's is fixed by taking the soldier from the base/replaced
    # unit, an officer's or a mount's is not. `skeleton_models` maps each missing
    # skeleton to the source model names that reference it; `soldier_model_name` is
    # the soldier-line model this transfer actually copies ("" when the soldier
    # comes from the base, so no soldier skeleton can be missing).
    skeleton_models: Dict[str, List[str]] = field(default_factory=dict)
    soldier_model_name: str = ""
    #: copied model name (lowercased) -> the slot it fills for THIS unit, one of
    #: :data:`SLOT_ORDER`. What the fix for a missing animation is depends
    #: entirely on which slot asked for it, and that is not recoverable from the
    #: modeldb entry alone.
    model_slots: Dict[str, str] = field(default_factory=dict)
    #: the base / replaced unit's soldier model, when the soldier line comes from
    #: it — used to say the unit will now animate like that unit instead
    base_soldier_model: str = ""
    #: the two skeleton sets differ, so the unit moves differently after this
    soldier_anim_changed: Tuple[str, str] = ("", "")
    missing_assets: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def _missing_for(self, slot: str) -> List[str]:
        """Missing skeletons whose most important asker fills ``slot``."""
        out = []
        for s in self.missing_skeletons:
            roles = {self.model_slots.get(o.lower(), "armour")
                     for o in self.skeleton_models.get(s, [])}
            best = next((r for r in SLOT_ORDER if r in roles), "armour")
            if best == slot:
                out.append(s)
        return out

    def soldier_skeletons_missing(self) -> List[str]:
        """The missing skeletons the soldier-line model is the one asking for.

        These are the ones the Soldier row can fix: hand that group to the base /
        replaced unit and the entry is not copied at all, so nothing asks the
        destination for an animation set it does not have.
        """
        if not self.soldier_model_name:
            return []
        return self._missing_for("soldier")

    def mount_skeletons_missing(self) -> List[str]:
        return self._missing_for("mount")

    def officer_skeletons_missing(self) -> List[str]:
        return self._missing_for("officer")

    def cosmetic_skeletons_missing(self) -> List[str]:
        """Missing skeletons only an armour-upgrade entry asks for.

        Not a crash. The engine takes the unit's animation from the SOLDIER
        entry; an armour-upgrade entry is a visual swap at that armour level, so
        its own skeleton line is never the one played.
        """
        return self._missing_for("armour")

    def summary(self) -> str:
        L = [f"Transfer '{self.unit_type}'  {self.source.name} -> {self.dest.name}"]
        if self.base_error:
            L.append("  ! BASE ERROR: " + self.base_error)
            return "\n".join(L)
        if self.option_error:
            L.append("  ! OPTION ERROR: " + self.option_error)
            return "\n".join(L)
        if self.replace_type:
            L.append(f"  REPLACING '{self.replace_type}' in {self.dest.name}: its EDU block is "
                     "rewritten in place — no new unit type, no new dictionary entry")
            # only the model groups the transferred unit actually has are a choice
            src_unit = self.source.edu.by_type().get(self.unit_type)
            has = {"soldier": bool(getattr(src_unit, "soldier_model", "")),
                   "officer": bool(getattr(src_unit, "officers", None)),
                   "armour_ug_models": bool(getattr(src_unit, "armour_ug_models", None)),
                   "mount": bool(getattr(src_unit, "mount", ""))}
            groups = [g for g in ("soldier", "officer", "armour_ug_models", "mount")
                      if has.get(g)]
            taken = [g for g in groups if g not in self.base_field_groups]
            kept = [g for g in groups if g in self.base_field_groups]
            L.append("      models taken from '" + self.unit_type + "': "
                     + (", ".join(_MODEL_GROUP_NAMES[g] for g in taken) or "none")
                     + (f" (kept from '{self.replace_type}': "
                        + ", ".join(_MODEL_GROUP_NAMES[g] for g in kept) + ")" if kept else ""))
            L.append(f"      stats/attributes/ownership/era stay '{self.replace_type}'s"
                     + (f", overridden field(s): {', '.join(sorted(self.options.field_overrides))}"
                        if self.options.field_overrides else ""))
            L.append("      unit card: " + ("IMPORTED from the source"
                                            if self.options.import_card else "kept"))
            L.append("      info card: " + ("IMPORTED from the source"
                                            if self.options.import_info_card else "kept"))
            L.append(f"      localisation untouched — '{self.replace_type}' keeps its name "
                     "and description")
        elif self.base_unit is not None:
            L.append(f"  base template: '{self.options.base_type}' (stats/attrs/ownership/era inherited)")
        if self.mercenary:
            L.append(f"  MERCENARY ATTRIBUTE: +{MERC_ATTR} attribute, +'{MERC_TEX_FACTION}' bmdb skin")
        if self.merc_icons:
            L.append(f"  MERCENARY ICONS: -> {MERC_CARD_DIR}/ + {MERC_INFO_DIR}/")
        if self.sound_action == "copy":
            L.append(f"  voice: copied {self.sound_donor}'s Unit_Select entry into "
                     f"{self.sound_accent}/{self.sound_class} "
                     f"(EDU accent + voice_type pinned to match)")
        elif self.sound_action in ("missing", "no_base"):
            L.append("  ! voice: " + self.sound_detail)
        elif self.sound_action == "none" and self.sound_detail:
            L.append("  voice: " + self.sound_detail)
        if self.options.field_overrides:
            L.append("  field overrides: " + ", ".join(sorted(self.options.field_overrides)))
        if self.skipped:
            L.append("  SKIPPED (unit already exists and conflict=skip)")
            return "\n".join(L)
        if self.unit_conflict:
            mode = self.options.on_conflict
            if mode == "rename":
                L.append(f"  unit exists -> RENAMED to '{self.resolved_type}' (dict '{self.resolved_dict}')")
            elif mode == "overwrite":
                L.append("  unit exists -> OVERWRITE")
        if self.eop_file:
            L.append(f"  M2TWEOP UNIT: written to {eop.rel_to_root(self.dest, self.eop_file)} "
                     "(outside export_descr_unit.txt, so outside the 500-unit cap)")
        adds = [a for a in self.model_actions if a.action == "add"]
        reuse = [a for a in self.model_actions if a.action == "reuse_identical"]
        ren = [a for a in self.model_actions if a.action == "rename"]
        L.append(f"  models: {len(adds)} add, {len(reuse)} reuse-identical, {len(ren)} renamed")
        for a in ren:
            L.append(f"      renamed bmdb '{a.source_name}' -> '{a.final_name}' ({a.reason})")
        for a in reuse:
            L.append(f"      reuse existing bmdb '{a.final_name}' (identical incl. filenames)")
        if self.mount_action == "add":
            L.append(f"  mount '{self.mount_name}' -> ADDED to descr_mount.txt")
        elif self.mount_action == "rename":
            L.append(f"  mount exists with different stats -> RENAMED to "
                     f"'{self.mount_name}' in descr_mount.txt (EDU updated)")
        elif self.mount_action == "reuse":
            L.append(f"  mount '{self.mount_name}' already in destination descr_mount.txt (reused)")
        elif self.mount_action == "missing":
            L.append("  ! mount NOT found in source descr_mount.txt")
        if self.mount_from_base_import:
            L.append("  mount taken from the transferred unit even though the base "
                     "supplies the mount group (its model and definition come across)")
        if self.mount_anim_donor:
            L.append(f"      its animations come from '{self.mount_anim_donor}' (the base "
                     f"unit's mount) — {', '.join(self.mount_skeletons_swapped)} "
                     f"{'is' if len(self.mount_skeletons_swapped) == 1 else 'are'} "
                     "not in the destination's modeldb")
        for name, action, detail in self.projectile_actions:
            verb = {"add": "ADDED to", "rename": "RENAMED in", "reuse": "reused in",
                    "missing": "MISSING from"}.get(action, action)
            L.append(f"  projectile '{name}' -> {verb} descr_projectile.txt ({detail})")
        if self.projectile_effects_blanked:
            L.append(f"      {self.projectile_effects_blanked} effect line(s) -> "
                     "'invisible_placeholder_set' (effects not ported — re-add by hand)")
        for name, action, detail in self.engine_actions:
            # `detail` opens with the file the action applies to — descr_engines.txt
            # for a ground engine, descr_mounted_engines.txt for a mounted one
            verb = {"add": "ADDED to", "rename": "RENAMED in", "reuse": "reused in",
                    "missing": "MISSING from"}.get(action, action)
            L.append(f"  siege engine '{name}' -> {verb} {detail}")
        for name, action, detail in self.engine_skeleton_actions:
            verb = {"add": "ADDED to", "rename": "RENAMED in", "reuse": "reused in",
                    "vanilla": "left to VANILLA in"}.get(action, action)
            L.append(f"      engine skeleton '{name}' -> {verb} "
                     f"descr_engine_skeleton.txt ({detail})")
        if self.engine_assets:
            L.append(f"      engine files copied: {len(self.engine_assets)} "
                     "(meshes, bone maps, collision, reference points, baked textures, "
                     "engine animations)")
        if self.engine_vanilla_refs:
            L.append(f"      {len(self.engine_vanilla_refs)} referenced file(s) are "
                     "VANILLA (not overridden by the source) — not copied:")
            for r in self.engine_vanilla_refs:
                L.append(f"          - {r}")
        if self.engine_dest_overrides:
            L.append("      ! DESTINATION OVERRIDES a vanilla file the engine needs "
                     "(its version wins — verify it matches):")
            for r in self.engine_dest_overrides:
                L.append(f"          - {r}")
        L.append(f"  asset files: {len(self.asset_files)}   icon files: {len(self.icon_files)}")
        if self.reroute_dir:
            L.append(f"  RELOCATED assets -> {self.reroute_dir}/  "
                     f"({len(self.path_map)} file(s), bmdb paths rewritten)")
        if self.asset_conflicts:
            ident = [c for c in self.asset_conflicts if c.identical]
            diff = [c for c in self.asset_conflicts if not c.identical]
            L.append(f"  asset name/path conflicts: {len(self.asset_conflicts)} "
                     f"({len(ident)} byte-identical -> reuse, {len(diff)} differ)")
            for c in diff:
                mode_key = (self.options.icon_conflict if c.kind == "icon"
                            else self.options.engine_conflict if c.kind == "engine"
                            else self.options.asset_conflict)
                mode = ("OVERWRITE destination" if mode_key == "overwrite"
                        else "keep existing (use destination's)")
                L.append(f"      - [{c.kind}] {c.rel}  (src {c.src_size}B vs "
                         f"dest {c.dst_size}B) -> {mode}")
        if self.excluded_secondaries:
            L.append("  ! EXCLUDED secondary models (kept name, must exist in destination):")
            for s in self.excluded_secondaries:
                L.append(f"      - {s}")
        if self.missing_models:
            L.append("  ! model entries NOT found in source modeldb: " + ", ".join(self.missing_models))
        # The soldier line's missing animations get their own ONE-LINE entry, tagged
        # "(soldier line)": the composer shows that case beside the Soldier row (the
        # row that fixes it) and drops this line to avoid saying it twice. Keeping it
        # here regardless is deliberate — the diagnostic log must still record it.
        soldier = self.soldier_skeletons_missing()
        if soldier:
            L.append("  ! ANIMATION WARNING (soldier line) - "
                     + ", ".join(soldier)
                     + f" absent from {self.dest.name}'s modeldb, asked for by the "
                     f"soldier model '{self.soldier_model_name}'. The game CRASHES on "
                     "load. Set Soldier to the base / replaced unit, or import the "
                     "animation set yourself first (anim pack / descr_skeleton) — only "
                     "do that if you already know how.")
        for slot, label, fix in (
                ("mount", "mount", "Pick “port with the base's animations” for the "
                                   "mount, or import the animation set yourself."),
                ("officer", "officer", "Pick “port with the base's animations” for the "
                                       "officers, or import the animation set yourself.")):
            miss = self._missing_for(slot)
            if miss:
                who = ", ".join(sorted({m for s in miss
                                        for m in self.skeleton_models.get(s, [])}))
                L.append(f"  ! ANIMATION WARNING ({label}) - " + ", ".join(miss)
                         + f" absent from {self.dest.name}'s modeldb, asked for by "
                         f"'{who}'. The game CRASHES on load. " + fix)
        cosmetic = self.cosmetic_skeletons_missing()
        if cosmetic:
            L.append("  - armour-upgrade models name animation(s) this mod has not got ("
                     + ", ".join(cosmetic) + "). Not a crash: the engine animates the "
                     "unit from its SOLDIER entry and an upgrade level is a visual swap.")
        if self.missing_assets:
            L.append(f"  ! {len(self.missing_assets)} referenced files not found on disk (skipped)")
        for w in self.warnings:
            L.append("  - " + w)
        return "\n".join(L)


# --------------------------------------------------------------------------
#: Model slots, most animation-significant first. A missing skeleton is blamed on
#: the highest slot that asks for it, because that is the one whose fix is real:
#:
#:   soldier — the entry the engine takes the unit's animation from. Missing = crash.
#:   mount / officer — their own entries, each with its own animation set. Missing =
#:     crash, fixable by borrowing the base unit's equivalent entry's animations.
#:   armour — an armour-upgrade level. A visual swap only; the soldier entry still
#:     drives the animation, so a missing skeleton here is cosmetic.
SLOT_ORDER = ("soldier", "mount", "officer", "armour")


def model_slots_for(source: Mod, unit, base_groups=()) -> Dict[str, str]:
    """``model name (lower) -> slot``, first slot in :data:`SLOT_ORDER` wins."""
    slots: Dict[str, str] = {}

    def put(name, slot: str) -> None:
        n = (name or "").strip().lower()
        if n:
            slots.setdefault(n, slot)

    base_groups = set(base_groups)
    if "soldier" not in base_groups:
        put(getattr(unit, "soldier_model", ""), "soldier")
    if "mount" not in base_groups and getattr(unit, "mount", ""):
        put(source.mount_model(unit.mount), "mount")
    if "officer" not in base_groups:
        for o in unit.officers:
            put(o, "officer")
    if "armour_ug_models" not in base_groups:
        for m in unit.armour_ug_models:
            put(m, "armour")
    return slots


def _secondary_model_names(source: Mod, unit, opts: TransferOptions,
                           base_groups=()):
    """Return (included_models, excluded_models).

    A group listed in ``base_groups`` comes from the base unit, so the source's
    models for it are neither copied nor "excluded" — nothing references them.
    Otherwise officers/mount/crew follow the include options. armour_ug_models
    stay from the transferred unit unless that group too was handed to the base
    (only replace mode offers that), so their models are normally always copied.
    """
    base_groups = set(base_groups)
    excl = {m.lower() for m in opts.exclude_models}   # individually-unticked models
    included: List[str] = []
    excluded: List[str] = []

    def route(name: str, group_on: bool):
        """Include a secondary model unless its group is off or it's individually
        unticked; excluded models keep their EDU name (must exist in the dest)."""
        n = name.lower()
        (included if (group_on and n not in excl) else excluded).append(n)

    if unit.soldier_model and "soldier" not in base_groups:
        included.append(unit.soldier_model.lower())
    if "armour_ug_models" not in base_groups:
        for m in unit.armour_ug_models:
            included.append(m.lower())

    if "officer" not in base_groups:
        for off in unit.officers:
            route(off, opts.include_officers)

    if unit.mount and "mount" not in base_groups:
        mm = source.mount_model(unit.mount)
        if mm:
            route(mm, opts.include_mount)

    # NOTE `ship` / `engine` / `mounted_engine` / `animal` are NOT battle-model
    # names — they name entries in descr_ship.txt / descr_engines.txt /
    # descr_mounted_engines.txt / descr_animals.txt. Feeding them to the modeldb
    # resolver only ever produced bogus "model not found" diagnostics. Engines are
    # resolved properly by `_resolve_engines`; ship/animal are warned about there.

    # de-dup preserving order
    def dedup(xs):
        seen, out = set(), []
        for x in xs:
            if x and x not in seen:
                seen.add(x); out.append(x)
        return out
    return dedup(included), dedup(excluded)


def mount_base_import(base_unit, dest: Mod, unit, opts: "TransferOptions"):
    """``(bring the source's mount across?, the base's mount entry to copy its
    animations from)`` for a transfer whose mount group comes from the base.

    Both are ``False``/``None`` unless every part of the case is present: the
    option is on, the mount really is set to come from the base, and BOTH units
    actually have a mount. A base with no mount still means "this unit loses its
    mount" — there would be nothing to inherit an animation set from, and quietly
    porting the mount instead would change what the toggle does.

    The entry can come back ``None`` while the import still goes ahead: that only
    means the base's mount names no modeldb entry we can read, so there is no
    animation set to borrow and the mount keeps its own (reported by the caller).
    """
    if not (opts.import_mount_with_base and opts.mount_from == "base"):
        return False, None
    base_mount = getattr(base_unit, "mount", "") if base_unit else ""
    if not base_mount or not getattr(unit, "mount", ""):
        return False, None
    model = dest.mount_model(base_mount)
    return True, (dest.modeldb.get(model) if model else None)


def officer_base_import(base_unit, dest: Mod, unit, opts: "TransferOptions"):
    """The officer version of :func:`mount_base_import`.

    An officer is a modeldb entry like any other and carries its own animation
    set, so the same two-step is available: bring the source's officers across
    but give them the base unit's officer's animations, which is the one set this
    mod is already known to have.
    """
    if not (opts.import_officers_with_base and opts.officer_from == "base"):
        return False, None
    base_officers = list(getattr(base_unit, "officers", []) or []) if base_unit else []
    if not base_officers or not unit.officers:
        return False, None
    return True, dest.modeldb.get(base_officers[0])


def _swap_entry_animations(plan: "TransferPlan", dest: Mod, model_name: str,
                           donor, what: str, undo_hint: str):
    """Give one copied modeldb entry ``donor``'s animation set.

    A skeleton is an ``animations/*.cas`` pack the destination either has or
    hasn't — copying the entry does not bring one along — so an entry whose
    skeletons are missing here is a model that does not animate, and the engine
    takes the whole game down on load rather than shrugging. The donor is by
    definition already working in this mod, so its records are the one animation
    set we know is safe. Everything else stays the copied entry's; only the
    skeleton names change.

    Returns ``(donor name, swapped skeletons)`` or ``("", [])``.
    """
    model_name = (model_name or "").lower()
    if not model_name:
        return "", []
    for i, (final_name, entry) in enumerate(plan.add_entries):
        if entry.name.lower() != model_name:
            continue
        missing = [s for s in dict.fromkeys(entry.skeletons())
                   if s and s not in dest.modeldb.all_skeletons()]
        if not missing:
            return "", []                # its own animations work here — keep them
        if donor is None or not donor.animations:
            plan.warnings.append(
                f"{what} model '{entry.name}' needs animation(s) "
                f"{', '.join(missing)}, which {dest.name} does not have, and the "
                f"base unit's {what} has no readable modeldb entry to borrow an "
                "animation set from. Copy the .cas files over by hand, or the game "
                "will crash on load.")
            return "", []
        raw = modeldb.rewrite_animations(entry.raw, donor.animations,
                                         pad=entry.first_entry_pad)
        plan.add_entries[i] = (final_name, modeldb.ModelEntry(
            name=entry.name, scale=entry.scale, lods=entry.lods,
            main_textures=entry.main_textures, attach_textures=entry.attach_textures,
            animations=modeldb.merged_animations(entry.animations, donor.animations),
            torch_index=entry.torch_index, torch=entry.torch, raw=raw,
            first_entry_pad=entry.first_entry_pad))
        # This entry no longer asks for them — but another copied model might, and
        # dropping a skeleton this transfer still needs would hide a real problem.
        still_wanted = {s for n, e in plan.add_entries if n != final_name
                        for s in e.skeletons()}
        plan.missing_skeletons = [s for s in plan.missing_skeletons
                                  if s not in missing or s in still_wanted]
        plan.warnings.append(
            f"the {what}'s model '{entry.name}' uses animation(s) "
            f"{', '.join(missing)}, which {dest.name} does not have. It was given "
            f"'{donor.name}'s instead (the base unit's {what}), so it animates like "
            f"the base's — it may move unexpectedly in battle. {undo_hint}")
        return donor.name, missing
    return "", []


def _apply_mount_anim_donor(plan: "TransferPlan", source: Mod, dest: Mod,
                            unit, donor) -> None:
    name, missing = _swap_entry_animations(
        plan, dest, source.mount_model(unit.mount), donor, "mount",
        "Pick “port as is” for the mount to keep the original skeletons and copy "
        "them over yourself.")
    plan.mount_anim_donor, plan.mount_skeletons_swapped = name, missing


def _apply_officer_anim_donor(plan: "TransferPlan", source: Mod, dest: Mod,
                              unit, donor) -> None:
    for off in unit.officers:
        name, missing = _swap_entry_animations(
            plan, dest, off, donor, "officer",
            "Pick “port as is” for the officers to keep the original skeletons and "
            "copy them over yourself.")
        if name:
            plan.officer_anim_donor = name
            plan.officer_skeletons_swapped += [s for s in missing
                                               if s not in plan.officer_skeletons_swapped]


def _resolve_projectiles(plan: "TransferPlan", source: Mod, dest: Mod,
                         names: List[str], opts: "TransferOptions") -> None:
    """Plan the projectile blocks ``names`` needs in descr_projectile.txt.

    ``names`` are the projectiles a unit's stat lines and/or its siege engine's
    ``attack_stat`` lines fire; any ``flaming`` variant they reference is followed
    too. Each is reused when the destination already has an identical block, renamed
    on a name collision with different content, or added. Effect-set references the
    destination doesn't define are rewritten to the placeholder (effects are never
    ported). EDU stat lines are repointed at apply time via
    ``plan.projectile_renames``.
    """
    wanted: List[str] = []
    for name in names:
        if name and not any(name.lower() == w.lower() for w in wanted):
            wanted.append(name)
    if not wanted:
        return
    # follow one level of `flaming <proj>` so a fiery variant doesn't dangle
    seed = list(wanted)
    for name in seed:
        sp = source.projectile_def(name)
        if sp and sp.flaming and sp.flaming not in wanted:
            wanted.append(sp.flaming)

    valid_effects = dest.effect_sets            # names the destination already defines
    dest_projs = dest.projectile_file
    taken = set(dest_projs.by_name().keys())
    resolved: Dict[str, str] = {}               # source name -> final dest name

    # First pass: decide the final name for every wanted projectile (needed so the
    # `flaming` cross-refs can be rewritten consistently).
    to_emit: List[projectiles_mod.Projectile] = []
    for name in wanted:
        sp = source.projectile_def(name)
        if sp is None:
            plan.projectile_actions.append((name, "missing",
                                            "not found in source descr_projectile.txt"))
            plan.warnings.append(
                f"projectile '{name}' has no entry in the source descr_projectile.txt")
            continue
        dp = dest_projs.get(name)
        if dp is not None and dp.content_equals(sp):
            resolved[name.lower()] = dp.name
            plan.projectile_actions.append((name, "reuse", "identical in destination"))
        elif dp is not None:
            new_name = projectiles_mod.unique_projectile_name(name, taken, _tag(source))
            taken.add(new_name)
            resolved[name.lower()] = new_name
            plan.projectile_renames[name.lower()] = new_name
            plan.projectile_actions.append((name, "rename",
                                            f"name collision -> '{new_name}'"))
            to_emit.append(sp)
        else:
            taken.add(name)
            resolved[name.lower()] = name
            plan.projectile_actions.append((name, "add", "new projectile"))
            to_emit.append(sp)

    # flaming rename map: how to rewrite `flaming <x>` inside emitted blocks
    # (only projectiles that actually got a new name)
    flaming_map = {old: new for old, new in resolved.items()
                   if new and new.lower() != old}

    # Second pass: build the raw blocks with names/flaming/effects rewritten, and
    # copy each projectile's .cas model files (outside unit_models/, so they're
    # never relocated — they keep their data/models_missile paths).
    valid_lower = {e.lower() for e in valid_effects}
    seen_pmodels = {rel for _, rel in plan.asset_files}
    for sp in to_emit:
        name_new = resolved.get(sp.name.lower())
        name_new = name_new if name_new and name_new != sp.name else None
        blanked = sum(1 for v in sp.effects.values()
                      if v and v.lower() not in valid_lower)
        plan.projectile_effects_blanked += blanked
        raw = projectiles_mod.rewrite_projectile_raw(
            sp.raw, name_new=name_new, flaming_map=flaming_map,
            valid_effects=valid_effects)
        plan.projectile_raws.append(raw)
        for rel in sp.models:
            if rel in seen_pmodels:
                continue
            seen_pmodels.add(rel)
            src_abs = source.data / rel
            if src_abs.exists():
                plan.asset_files.append((src_abs, rel))
            else:
                plan.missing_assets.append(rel)

    added = [a for a in plan.projectile_actions if a[1] in ("add", "rename")]
    if added:
        plan.warnings.append(
            "PROJECTILE IMPORT: special effects are NOT imported — the projectile's "
            "effect/impact lines were pointed at 'invisible_placeholder_set' where the "
            "destination lacks them. Re-add the real effects manually in "
            "descr_effect_impacts.txt / the arrow-trail files.")
        if any(source.projectile_def(a[0]) and source.projectile_def(a[0]).models
               for a in added):
            plan.warnings.append(
                "projectile model (.cas) files were copied, but their textures under "
                "data/models_missile/textures/ are not chased — verify the missile model "
                "renders and copy its texture if it's missing in the destination.")


# --------------------------------------------------------------------------
# Siege engines
#
# A unit's EDU `engine` / `mounted_engine` field names a block in
# descr_engines.txt / descr_mounted_engines.txt — NOT a battle model. Carrying an
# artillery unit across needs that block, the files it names, the textures baked
# into its meshes, and each model group's descr_engine_skeleton.txt entry with the
# animation .CAS/.evt files under animations/engine/.
ENGINE_FIELDS = (("engine", "descr_engines.txt"),
                 ("mounted_engine", "descr_mounted_engines.txt"))


def _engine_asset(plan: "TransferPlan", source: Mod, dest: Mod, rel: str,
                  seen: set, why: str) -> None:
    """Queue one engine file for copying, or classify it as a vanilla reference.

    A file the SOURCE mod doesn't contain is a stock game file the mod never
    overrode — not ours to copy. If the DESTINATION *does* have that path, its own
    override wins over vanilla and may not be what the engine expects, so that case
    is flagged (this is the "keep an eye on overrides" case).
    """
    key = rel.lower()
    if key in seen or rel in seen:
        return
    seen.add(key)
    seen.add(rel)              # the model pass compares case-sensitively
    src_abs = source.data / rel
    if src_abs.exists():
        plan.asset_files.append((src_abs, rel))
        plan.engine_assets.append(rel)
        return
    plan.engine_vanilla_refs.append(f"{rel}  ({why})")
    if (dest.data / rel).exists():
        plan.engine_dest_overrides.append(rel)


def _resolve_engine_skeletons(plan: "TransferPlan", source: Mod, dest: Mod,
                              names: List[str], seen_assets: set,
                              allow_rename: bool = True) -> Dict[str, str]:
    """Plan the descr_engine_skeleton.txt entries an engine's model groups need.

    Returns the rename map (lowercased old name -> new) so the engine block's
    ``engine_skeleton`` lines can be repointed. Engine animations are stored loose
    under ``animations/engine/`` rather than in a unit anim pack, so the ``.CAS``
    and ``-evt:`` files are copied alongside.

    ``allow_rename=False`` for a MOUNTED engine: it names its skeleton through the
    block's ``class`` line, and those are the shared stock classes (serpentine /
    rocket_launcher / ballista) the destination almost always already defines. A
    rename there would fork an animation set for no gain, so an entry that already
    exists is kept as-is and merely flagged.
    """
    taken = set(dest.engine_skeleton_file.by_type().keys())
    renames: Dict[str, str] = {}
    for name in names:
        if name.lower() in plan.engine_skeleton_renames or any(
                a[0].lower() == name.lower() for a in plan.engine_skeleton_actions):
            continue
        src_s = source.engine_skeleton_def(name)
        if src_s is None:
            # not in the mod's file -> it inherits the vanilla definition. Fine when
            # the destination has it too (or it's a stock name); a problem when
            # neither mod defines it, which means the engine has no animation there.
            in_dest = dest.engine_skeleton_def(name) is not None
            plan.engine_skeleton_actions.append(
                (name, "vanilla",
                 "not in the source descr_engine_skeleton.txt (inherited from the "
                 "base game)" + ("" if in_dest else " — and ABSENT from the destination's")))
            if not in_dest:
                plan.warnings.append(
                    f"engine skeleton '{name}' is defined in NEITHER mod's "
                    "descr_engine_skeleton.txt — it must exist in the base game or that "
                    "model group will have no animation. Add the entry by hand if not.")
            continue
        dst_s = dest.engine_skeleton_def(name)
        if dst_s is not None and dst_s.content_equals(src_s):
            plan.engine_skeleton_actions.append((name, "reuse", "identical in destination"))
            continue
        if dst_s is not None and not allow_rename:
            plan.engine_skeleton_actions.append(
                (name, "reuse", "already in the destination descr_engine_skeleton.txt "
                                "with different animations — KEPT, not overwritten"))
            plan.warnings.append(
                f"engine skeleton '{name}' (the mounted engine's `class`) already exists "
                "in the destination descr_engine_skeleton.txt with different animations. "
                "The destination's entry is kept — the mounted engine will use it, which "
                "normally works fine. Compare the two by hand if the firing animation "
                "looks wrong.")
            continue
        if dst_s is not None:
            new_name = engines_mod.unique_engine_name(name, taken, _tag(source))
            taken.add(new_name.lower())
            renames[name.lower()] = new_name
            plan.engine_skeleton_renames[name.lower()] = new_name
            plan.engine_skeleton_actions.append(
                (name, "rename", f"name collision -> '{new_name}'"))
            raw = engines_mod.rewrite_engine_skeleton_raw(src_s.raw, type_new=new_name)
        else:
            taken.add(name.lower())
            plan.engine_skeleton_actions.append((name, "add", "new engine skeleton"))
            raw = src_s.raw
        plan.engine_skeleton_raws.append(raw)
        for rel in src_s.anim_files():
            _engine_asset(plan, source, dest, rel, seen_assets,
                          f"animation for engine skeleton '{name}'")
    return renames


def _resolve_engines(plan: "TransferPlan", source: Mod, dest: Mod, unit,
                     opts: "TransferOptions", seen_assets: set) -> None:
    """Plan everything a unit's siege engine needs in the destination."""
    for field_key, filename in ENGINE_FIELDS:
        name = getattr(unit, field_key, "")
        if not name or field_key in plan.base_field_groups:
            continue
        mounted = field_key == "mounted_engine"
        src_blocks = (source.mounted_engine_defs(name) if mounted
                      else source.engine_defs(name))
        if not src_blocks:
            plan.engine_actions.append(
                (name, "missing", f"{filename} — no entry in the source"))
            plan.warnings.append(
                f"siege engine '{name}' ({field_key}) has no entry in the source "
                f"{filename} — the destination will have a dangling engine reference.")
            continue
        dst_blocks = (dest.mounted_engine_defs(name) if mounted
                      else dest.engine_defs(name))
        # one type can span several blocks (per culture / variant): compare and
        # carry the whole set, or the engine only half-exists in the destination
        same = (len(dst_blocks) == len(src_blocks)
                and all(d.content_equals(s) for d, s in zip(dst_blocks, src_blocks)))
        nblocks = (f"{len(src_blocks)} block"
                   f"{'s' if len(src_blocks) > 1 else ''}")
        if dst_blocks and same:
            plan.engine_actions.append(
                (name, "reuse", f"{filename} — identical in destination ({nblocks})"))
            continue

        final_name = name
        if dst_blocks:
            all_types = set((dest.mounted_engine_file if mounted
                             else dest.engine_file).by_type().keys())
            final_name = engines_mod.unique_engine_name(name, all_types, _tag(source))
            plan.engine_renames[field_key] = final_name
            plan.engine_actions.append(
                (name, "rename", f"{filename} — name collision -> '{final_name}'"))
        else:
            plan.engine_actions.append(
                (name, "add", f"{filename} — new engine ({nblocks})"))

        # skeletons first: their rename map has to be applied to the engine blocks.
        # A mounted engine has no model groups — its `class` line is the skeleton
        # name (see Engine.mounted_skeletons), and it is never renamed.
        skel_names: List[str] = []
        for b in src_blocks:
            for s in (b.mounted_skeletons() if mounted else b.skeletons()):
                if not any(s.lower() == x.lower() for x in skel_names):
                    skel_names.append(s)
        skel_map = _resolve_engine_skeletons(plan, source, dest, skel_names,
                                             seen_assets, allow_rename=not mounted)

        for b in src_blocks:
            raw = engines_mod.rewrite_engine_raw(
                b.raw, type_new=(final_name if final_name != name else None),
                skeleton_map=skel_map)
            (plan.mounted_engine_raws if mounted else plan.engine_raws).append(raw)
            for p in b.projectiles():
                if not any(p.lower() == x.lower() for x in plan.engine_projectiles):
                    plan.engine_projectiles.append(p)
            # the files the block names...
            for rel in b.file_refs():
                _engine_asset(plan, source, dest, rel, seen_assets,
                              f"referenced by engine '{name}'")
            # ...and the textures baked into each mesh binary. Nothing in the text
            # files names these, so without reading the mesh the engine transfers
            # untextured (or silently wearing the destination's skins).
            for rel in b.mesh_refs():
                mesh_abs = source.data / rel
                if not mesh_abs.exists():
                    continue
                texs = engines_mod.mesh_textures(mesh_abs)
                if not texs:
                    plan.warnings.append(
                        f"no texture paths could be read out of '{rel}' — check the "
                        "engine's textures manually (convert it with IWTE / open it "
                        "in Blender or Milkshape).")
                for t in texs:
                    _engine_asset(plan, source, dest, t, seen_assets,
                                  f"texture baked into '{rel}'")

    if plan.engine_dest_overrides:
        plan.warnings.append(
            "ENGINE OVERRIDE WARNING: the engine references "
            f"{len(plan.engine_dest_overrides)} vanilla file(s) the SOURCE mod does "
            "not override but the DESTINATION does — the destination's version will "
            "be used and may not match: "
            + ", ".join(plan.engine_dest_overrides[:6])
            + (" …" if len(plan.engine_dest_overrides) > 6 else ""))
    if plan.engine_raws or plan.mounted_engine_raws:
        plan.warnings.append(
            "ENGINE IMPORT: effect/particle/sound references in the engine block "
            "(fire_effect, shot_pfx_*, shot_sfx, area_effect) and the crew animation "
            "names in its `crew_animations` block are NOT ported — verify they exist "
            "in the destination.")

    # ship / animal name entries in descr_ship.txt / descr_animals.txt, which this
    # tool does not carry across. Say so rather than silently dropping them.
    for field_key, filename in (("ship", "descr_ship.txt"),
                                ("animal", "descr_animals.txt")):
        val = getattr(unit, field_key, "")
        if val and field_key not in plan.base_field_groups:
            plan.warnings.append(
                f"unit has `{field_key} {val}`, which names an entry in {filename} — "
                "that file is NOT transferred; add the entry by hand if the "
                "destination lacks it.")


def _resolve_sound(plan: "TransferPlan", dest: Mod) -> None:
    """Decide the transferred unit's voice entry and compose the new voice bank.

    The unit's barks are NOT part of its EDU block: they live in the destination's
    ``export_descr_sounds_units_voice.txt`` as a ``unit <type>`` entry inside one
    accent/class block, and the EDU's ``accent`` / ``voice_type`` are what send the
    game looking in that block. So copying a voice means both halves — an entry
    spliced into the bank, and those two EDU fields pinned to the donor's — which is
    why the composer locks them while a donor is in play.

    Nothing here can fail the transfer: a missing bank or a mute donor downgrades to
    a warning, because a unit with no voice entry still works (it just falls back to
    its class's generic barks).
    """
    opts = plan.options
    mode = (opts.sound_mode or "base").lower()
    # Replacing a unit: "the base's voice" would mean copying the replaced unit's
    # own entry onto itself. It already has it, and its accent/voice_type come
    # across with the rest of its stats, so the sane reading of the default is
    # "leave the voice alone" — picking another unit still works as it does for a
    # base template.
    if plan.replace_type and mode == "base":
        plan.sound_action = "none"
        plan.sound_detail = (f"'{plan.replace_type}' keeps its own voice entry "
                             "(accent and voice_type come across with its stats)")
        return
    if mode == "none":
        plan.sound_action = "none"
        return
    if not dest.eds_path.exists():
        plan.sound_action = "missing"
        plan.sound_detail = (f"{dest.name} has no data/{sounds.EDS_REL} — no voice "
                             "entry written")
        plan.warnings.append(plan.sound_detail)
        return

    if mode == "base":
        donor_name = opts.base_type or ""
        if not donor_name:
            plan.sound_action = "no_base"
            plan.sound_detail = ("no base unit chosen, so there is no base voice to "
                                 "copy — pick a base unit, choose another unit for the "
                                 "voice, or turn the voice off")
            plan.warnings.append(plan.sound_detail)
            return
    else:
        donor_name = opts.sound_donor or ""
        if not donor_name:
            plan.sound_action = "no_base"
            plan.sound_detail = "no unit chosen to copy the voice from"
            plan.warnings.append(plan.sound_detail)
            return

    bank = dest.sounds
    donor = bank.get(donor_name)
    if donor is None:
        plan.sound_action = "missing"
        plan.sound_detail = (f"'{donor_name}' has no Unit_Select entry in {dest.name}'s "
                             "voice bank, so there is nothing to copy (it uses its "
                             "class's generic barks)")
        plan.warnings.append(plan.sound_detail)
        return

    plan.sound_donor = donor_name
    plan.sound_accent = donor.accent
    plan.sound_class = donor.voice_class
    # Overwriting a unit that already has an entry must MOVE it, not add a second
    # one — two `unit X` lines in the bank and the game reads only the first.
    existing = bank.get(plan.resolved_type)
    try:
        if existing is not None:
            plan.sound_text = sounds.move_unit(bank, plan.resolved_type,
                                               donor.accent, donor.voice_class, donor)
        else:
            plan.sound_text = sounds.add_unit(bank, plan.resolved_type, donor,
                                              donor.accent, donor.voice_class)
    except ValueError as exc:
        plan.sound_action = "missing"
        plan.sound_detail = f"voice entry not written: {exc}"
        plan.warnings.append(plan.sound_detail)
        return
    plan.sound_action = "copy"
    plan.warnings.append(
        f"voice: '{plan.resolved_type}' copies {donor_name}'s Unit_Select sounds and "
        f"its EDU accent/voice_type are pinned to {donor.accent}/{donor.voice_class} "
        "(the entry only works if both point at the same block).")


def _override_projectiles(opts: TransferOptions) -> List[str]:
    """Projectiles named by a hand-set ``stat_pri`` / ``stat_sec`` override.

    With a base unit (or a replaced one) the stats — and therefore the projectile —
    normally come from the destination, so nothing has to be ported. Switching one
    of those two fields back to the transferred unit's value (the composer's B
    button, which is exactly how "import the individual stats" works when
    replacing a unit) puts a SOURCE projectile name in the block, and that name
    means nothing in the destination unless its definition comes along too.
    """
    out: List[str] = []
    for key in ("stat_pri", "stat_sec"):
        val = opts.field_overrides.get(key)
        if not val:
            continue
        parts = [p.strip() for p in val.split(",")]
        # slot 3 of the CSV is the projectile ("no" for a melee weapon)
        if len(parts) > 2 and parts[2] and parts[2].lower() != "no":
            out.append(parts[2])
    return out


def _follow_soldier_upgrades(plan: "TransferPlan", unit) -> None:
    """Report — never override — an armour-upgrade list that shadows the soldier line.

    An armour-upgrade entry is the model the unit actually wears at that armour
    level, so one naming the source's soldier model puts that model back on
    screen whatever the ``soldier`` line says. The two rows are an independent
    choice and stay one: this only says what the combination will look like.
    """
    if "soldier" not in plan.base_field_groups:
        return
    if "armour_ug_models" in plan.base_field_groups:
        return
    soldier = (unit.soldier_model or "").lower()
    ug = [m.lower() for m in unit.armour_ug_models]
    if not soldier or soldier not in ug:
        return
    who = plan.replace_type or plan.options.base_type
    only = set(ug) == {soldier}
    plan.warnings.append(
        f"the soldier line comes from '{who}', but the armour upgrade models "
        + (f"are only '{soldier}' — the source's soldier model."
           if only else
           f"still list '{soldier}', the source's soldier model.")
        + " The game renders the upgrade entry for the unit's armour level, so at "
        f"that level the unit still looks like '{soldier}'. Set Armour upgrades to "
        f"'{who}' as well if that is not what you want.")


def _check_base_soldier_animations(plan: "TransferPlan", source: Mod, dest: Mod,
                                   unit) -> None:
    """Say so when taking the soldier line from the base CHANGES the animation.

    Taking the base's soldier entry is the safe answer to a missing animation,
    but it is not free: the entry carries the skeletons, so the unit now moves
    the way the base unit moves. A pikeman animated as a swordsman does not
    crash, it just fights wrong, and nothing on screen says why.
    """
    if "soldier" not in plan.base_field_groups or plan.base_unit is None:
        return
    base_model = (getattr(plan.base_unit, "soldier_model", "") or "").strip()
    plan.base_soldier_model = base_model
    src_entry = source.modeldb.get(unit.soldier_model) if unit.soldier_model else None
    dst_entry = dest.modeldb.get(base_model) if base_model else None
    if src_entry is None or dst_entry is None:
        return
    was = [s for s in dict.fromkeys(src_entry.skeletons()) if s]
    now = [s for s in dict.fromkeys(dst_entry.skeletons()) if s]
    if not was or not now or set(was) == set(now):
        return
    plan.soldier_anim_changed = (", ".join(was), ", ".join(now))
    who = plan.replace_type or plan.options.base_type
    plan.warnings.append(
        f"the soldier line comes from '{who}', so the unit animates as "
        f"{plan.soldier_anim_changed[1]} instead of {plan.soldier_anim_changed[0]}. "
        "It will not crash, but it may move and fight unexpectedly in battle — a "
        "different animation set means different attack timings and reach.")


def base_field_groups_for(opts: TransferOptions) -> List[str]:
    """EDU field groups a base unit supplies, given the include/soldier options.

    Each ``*_from == "base"`` toggle hands that whole group to the base unit.
    ``soldier_from`` covers the soldier line ONLY — ``armour_ug_models`` always
    stays from the transferred unit.
    """
    groups: List[str] = []
    if opts.soldier_from == "base":
        groups.append("soldier")
    if opts.officer_from == "base":
        groups.append("officer")
    if opts.mount_from == "base":
        groups.append("mount")
    if opts.crew_from == "base":
        groups += ["ship", "engine", "mounted_engine", "animal"]
    if opts.upgrade_from == "base":
        groups.append("armour_ug_models")
    return groups


def compose_with_base(unit_raw: str, base_raw: str, groups: List[str],
                      copy_keys=None) -> str:
    """Unit block after inheriting the base's stats plus whole field groups.

    ``copy_keys`` names the stat fields taken from the base — the default set for
    a base template, :data:`edu.REPLACE_COPY_KEYS` when replacing a unit (which
    also hands over the icon-folder pins along with the identity).
    """
    block = edu_mod.apply_base_template(unit_raw, base_raw,
                                        copy_keys or edu_mod.BASE_COPY_KEYS)
    for key in dict.fromkeys(groups):
        block = edu_mod.copy_field_group(block, base_raw, key)
    return block


UNIT_MODELS = "unit_models"

# Mercenary conventions, verified against DaC (129 merc units) and TATR (2):
# every one of them uses card_pic_dir=mercs + info_pic_dir=merc, and the bmdb
# faction token for a mercenary skin is `merc`.
MERC_ATTR = "mercenary_unit"
MERC_TEX_FACTION = "merc"
MERC_CARD_DIR = "mercs"          # data/ui/units/<dir>
MERC_INFO_DIR = "merc"           # data/ui/unit_info/<dir>


def _folder_tag(mod_name: str) -> str:
    """Filesystem-safe folder name derived from a mod name (for mod_folder mode)."""
    import re
    tag = re.sub(r"[^A-Za-z0-9._-]+", "_", mod_name).strip("_")
    return tag or "transferred"


def _reloc_target(opts: "TransferOptions", source: Mod) -> str:
    """The folder assets get relocated into, or '' when not relocating."""
    if opts.asset_conflict == "mod_folder":
        return f"{UNIT_MODELS}/{_folder_tag(source.name)}"
    if opts.asset_conflict == "reroute":
        return _normalize_reroute_dir(opts.asset_reroute_dir)
    return ""


def _canon_rel(rel: str, target: str) -> str:
    """Strip our relocation ``target`` prefix so a relocated path compares equal to
    its pre-relocation form. Paths not under ``target`` are returned unchanged."""
    if target:
        p = target + "/"
        if rel.startswith(p):
            return UNIT_MODELS + "/" + rel[len(p):]
    return rel


def _normalize_reroute_dir(raw: Optional[str]) -> str:
    """Normalise a user-supplied reroute folder to a clean data-relative path.

    Accepts ``unit_models/Foo``, ``Foo``, backslashes, or a stray ``data/`` prefix,
    and always returns a path under ``unit_models/`` (never escaping it).
    """
    if not raw:
        return ""
    p = str(raw).replace("\\", "/").strip().strip("/")
    if p.lower().startswith("data/"):
        p = p[5:]
    # drop any ".." segments so the target can't escape the mod's data dir
    parts = [seg for seg in p.split("/") if seg and seg != "." and seg != ".."]
    if not parts:
        return ""
    if parts[0].lower() != UNIT_MODELS:
        parts.insert(0, UNIT_MODELS)
    if len(parts) == 1:                      # bare "unit_models" is not a target
        return ""
    return "/".join(parts)


def _sprite_sheets(source: Mod, rel: str) -> List[Tuple[Path, str]]:
    """Sheet textures belonging to a ``.spr`` file, as (abs, data-relative) pairs.

    A ``.spr`` is binary and carries no path strings: the game finds its sheets by
    name, ``<spr basename>_000.texture``, ``_001.texture``, ... next to the ``.spr``.
    The modeldb only names the ``.spr``, so without this the unit transfers with
    invisible far-LOD sprites.
    """
    p = Path(rel.replace("\\", "/"))
    folder = source.data / p.parent
    if not folder.is_dir():
        return []
    prefix = (p.stem + "_").lower()
    out: List[Tuple[Path, str]] = []
    for f in sorted(folder.iterdir()):
        n = f.name.lower()
        if not (n.startswith(prefix) and n.endswith(".texture")):
            continue
        if not n[len(prefix):-len(".texture")].isdigit():
            continue
        out.append((f, (p.parent / f.name).as_posix()))
    return out


def _unique_name(base: str, taken: set) -> str:
    if base not in taken:
        return base
    i = 2
    while f"{base}_{i}" in taken:
        i += 1
    return f"{base}_{i}"


def _resolve_eop_target(plan: TransferPlan, unit) -> None:
    """Decide whether the transferred unit becomes an M2TWEOP unit, and where.

    Three things get settled here, and they interact:

    * **Which file the new block goes in.** "auto" mirrors the source unit,
      because an overhaul's EOP unit is EOP for a reason and quietly demoting it
      into the EDU is how a destination silently blows past the 500-unit cap. The
      mirror only holds when the destination actually has an EOP folder — writing
      into a folder the extender is not configured to read makes the unit vanish
      with no error anywhere, which is far worse than landing in the EDU.
    * **What is being replaced.** Overwriting a destination unit that is itself an
      EOP unit rewrites *that unit's* file, not the EDU.
    * **The unit-limit count.** A unit that lands outside export_descr_unit.txt
      does not count against the vanilla cap at all.
    """
    dest, opts = plan.dest, plan.options
    # Replacing has no choice to make: the rewritten block belongs to the replaced
    # unit, so it stays in whichever file that unit already lives in. Moving it
    # would mean deleting a unit from one file and adding it to another — not a
    # replacement, and a silent way to lose an M2TWEOP unit's slot.
    if plan.replace_type:
        replaced = dest.edu.by_type().get(plan.replace_type)
        if replaced is not None and replaced.is_eop:
            plan.eop_replaced = replaced.eop_file
            plan.eop_file = replaced.eop_file
        plan.dest_new_units = 0
        return

    existing = dest.edu.by_type().get(plan.unit_type)
    if plan.unit_conflict and opts.on_conflict == "overwrite" and existing is not None \
            and existing.is_eop:
        plan.eop_replaced = existing.eop_file

    want = (opts.eop_target or "auto").lower()
    if want == "auto":
        want = "eop" if unit.is_eop else "edu"
    if want != "eop":
        return

    if not dest.eop_dirs:
        # Only worth saying out loud when the unit came in as an EOP unit or the
        # user asked for one — otherwise "auto" simply resolved to the EDU.
        plan.warnings.append(
            f"'{dest.name}' has no M2TWEOP unit folder configured, so "
            f"'{plan.resolved_type}' goes into export_descr_unit.txt instead. Set the "
            "mod's EOP folder in Settings to keep it out of the 500-unit cap.")
        return

    # Overwriting an existing EOP unit reuses its file — a rewrite in place, so
    # the modder's own layout survives the transfer.
    if plan.eop_replaced:
        plan.eop_file = plan.eop_replaced
    else:
        target = eop.new_unit_file(dest, plan.resolved_type)
        if target is None:
            return
        plan.eop_file = str(target)
    plan.dest_new_units = 0                # outside the EDU -> outside the cap


def plan_transfer(source: Mod, unit_type: str, dest: Mod,
                  options: Optional[TransferOptions] = None) -> TransferPlan:
    opts = options or TransferOptions()
    unit = source.edu.by_type().get(unit_type)
    if unit is None:
        raise KeyError(f"unit {unit_type!r} not found in {source.name}")

    plan = TransferPlan(unit_type=unit_type, dictionary=unit.dictionary,
                        source=source, dest=dest, options=opts)

    # ---- base templating / replacing an existing unit ----
    # Both work the same way — a destination unit supplies the stat fields — and
    # differ in what happens to the identity: a base template writes a NEW unit
    # that inherits the base's numbers, while a replacement takes the destination
    # unit's type, dictionary and icons over as well, so nothing is added at all.
    replacing = (opts.mode or "new").lower() == "replace"
    donor_type = (opts.replace_type if replacing else opts.base_type) or ""
    what = "unit to replace" if replacing else "base unit"
    if donor_type:
        base_unit = dest.edu.by_type().get(donor_type)
        if base_unit is None:
            plan.base_error = f"{what} '{donor_type}' not found in destination"
        elif base_unit.kind() != unit.kind():
            plan.base_error = (f"type mismatch: '{unit_type}' is {unit.kind() or '?'}, "
                               f"{what} '{donor_type}' is {base_unit.kind() or '?'} "
                               f"(the {what} must be the same unit type)")
        else:
            plan.base_unit = base_unit
            if replacing:
                plan.replace_type = base_unit.type
                plan.warnings.append(
                    f"replacing '{base_unit.type}': its EDU block is rewritten in place, so "
                    "no unit type and no dictionary entry are added. It keeps its name, "
                    "description, stats, ownership and era — only the models change.")
                plan.warnings.append(
                    f"'{base_unit.type}'s previous battle models are left in "
                    "battle_models.modeldb (other units may still use them). Use the BMDB "
                    "Editor's cleanup afterwards if nothing else does.")
            else:
                plan.warnings.append(
                    f"using '{donor_type}' as stat base: combat stats, attributes, cost, "
                    "formation, ownership & era come from it; models/name/icons stay from the transferred unit.")
    elif replacing:
        plan.base_error = "no destination unit chosen to replace"

    # ---- ownership change -> bmdb texture factions ----
    # A base unit (or an explicit override) rewrites `ownership`. The copied bmdb
    # entries only carry textures for the SOURCE unit's factions, so any new
    # faction would have no skin and the unit fails to show up in game. Record
    # the final faction list so apply can add the missing texture records.
    final_own: List[str] = []
    if plan.base_unit is not None:
        final_own = list(plan.base_unit.ownership)
    ov = opts.field_overrides.get("ownership")
    if ov:
        final_own = [x.strip() for x in ov.split(",") if x.strip()]
    # A mercenary is recruited outside the ownership list, so its bmdb entries
    # need a `merc` skin on top of whatever factions it already covers.
    want_tex = list(final_own)
    if opts.make_mercenary and MERC_TEX_FACTION not in want_tex:
        want_tex.append(MERC_TEX_FACTION)
    if want_tex:
        have = {t.faction for e in (source.modeldb.get(m) for m in unit.model_names())
                if e for t in e.main_textures}
        plan.texture_factions = want_tex
        plan.texture_donor = next((f for f in unit.ownership if f != "slave" and f in have), "")
        missing = [f for f in want_tex if f not in have]
        if missing:
            plan.warnings.append(
                "adding bmdb texture entries for "
                + ", ".join(missing) + " (cloned from "
                + (plan.texture_donor or "the model's existing skin") + ")")

    # ---- unit-name conflict ----
    # Replacing settles this by definition: the block written IS the replaced
    # unit's, under its own type and dictionary, so there is nothing to rename,
    # overwrite or skip and nothing is added to the destination's unit count.
    plan.resolved_type = unit_type
    plan.resolved_dict = unit.dictionary
    if plan.replace_type:
        plan.resolved_type = plan.base_unit.type
        plan.resolved_dict = plan.base_unit.dictionary
        plan.unit_conflict = False
        plan.dest_new_units = 0
    else:
        plan.unit_conflict = unit_type in dest.edu.by_type()
        if plan.unit_conflict:
            if opts.on_conflict == "skip":
                plan.skipped = True
                plan.dest_new_units = 0
                return plan
            if opts.on_conflict == "overwrite":
                plan.dest_new_units = 0    # replaces an existing type, no net add
            if opts.on_conflict == "rename":
                plan.resolved_type = opts.new_type or (unit_type + " (copy)")
                plan.resolved_dict = opts.new_dictionary or (unit.dictionary + "_copy")

    # ---- M2TWEOP: which file the block lands in ----
    _resolve_eop_target(plan, unit)

    # ---- models: dedup / rename / add ----
    # With a base unit, an unticked officers/mount/crew box means "use the base's"
    # — those models are already in the destination, so nothing has to be copied
    # and nothing can dangle. Without a base we fall back to keeping the source's
    # names (which must then already exist in the destination).
    if plan.base_unit is not None:
        plan.base_field_groups = base_field_groups_for(opts)

    # "mount from base", but bring the source's mount anyway: the mount stops
    # being a base group altogether (its model, its EDU line and its
    # descr_mount.txt block all come from the source, exactly as if the box said
    # "source"), and the base's mount is kept only as the animation donor below.
    import_mount, anim_donor = mount_base_import(plan.base_unit, dest, unit, opts)
    if import_mount:
        plan.base_field_groups = [g for g in plan.base_field_groups if g != "mount"]
        plan.mount_from_base_import = True
    # …and the same for the officers
    import_off, off_donor = officer_base_import(plan.base_unit, dest, unit, opts)
    if import_off:
        plan.base_field_groups = [g for g in plan.base_field_groups if g != "officer"]
        plan.officer_from_base_import = True

    # `armour_ug_models` shadows the soldier line: the game renders the entry for
    # the unit's armour level, so an upgrade list still naming the SOURCE's soldier
    # model puts that model (and its animations) back into the unit — the Soldier
    # row would have changed nothing at all. Two thirds of the time the list is
    # nothing but the soldier model repeated, and then "from the source" names no
    # model of its own to keep: hand it over with the soldier line. A genuinely
    # different list is the user's to decide, so that one is only reported.
    _follow_soldier_upgrades(plan, unit)

    included, excluded = _secondary_model_names(source, unit, opts,
                                                plan.base_field_groups)
    plan.excluded_secondaries = excluded
    # Which of the copied models IS the soldier line — the one group whose missing
    # animations the Soldier row can make go away (see soldier_skeletons_missing).
    if unit.soldier_model and "soldier" not in plan.base_field_groups:
        plan.soldier_model_name = unit.soldier_model.lower()
    plan.model_slots = model_slots_for(source, unit, plan.base_field_groups)
    _check_base_soldier_animations(plan, source, dest, unit)
    if excluded:
        plan.warnings.append(
            f"{len(excluded)} secondary model(s) excluded; their EDU names are kept and "
            "must already exist in the destination.")
    if plan.base_field_groups:
        taken = [_MODEL_GROUP_NAMES[g] for g in plan.base_field_groups
                 if g in _MODEL_GROUP_NAMES]
        plan.warnings.append(
            (f"kept from '{plan.replace_type}'" if plan.replace_type
             else f"taken from base '{opts.base_type}'")
            + f": {', '.join(taken)} — those models "
            "already exist in the destination, so nothing is copied for them.")

    dest_models = dest.modeldb.by_name()
    dest_skeletons = dest.modeldb.all_skeletons()
    taken_names = set(dest_models.keys())
    seen_assets: set = set()
    # Content dedup is done in a CANONICAL path space: the default mod_folder /
    # reroute modes relocate texture+mesh paths, so an entry we already copied has
    # rewritten paths and would otherwise never compare equal to the source (or to
    # the same model brought in by another unit in a batch). Canonicalising strips
    # our relocation prefix so identical models match regardless of where they landed.
    reloc_target = _reloc_target(opts, source)
    canon = lambda p: _canon_rel(p, reloc_target)

    def ckey(entry):
        return entry.content_key_mapped(canon)

    # canonical content_key -> the dest name already carrying that content. Recognises
    # an identical model under ANY name — e.g. a shared officer added (and renamed) by
    # an earlier unit in a batch; without this each unit re-adds name_tag, name_tag_2…
    dest_by_content: Dict = {}
    for nm, e in dest_models.items():
        dest_by_content.setdefault(ckey(e), nm)

    for name in included:
        entry = source.modeldb.get(name)
        if entry is None:
            plan.missing_models.append(name)
            continue

        key = ckey(entry)
        alt = dest_by_content.get(key)
        if alt is not None:
            # identical content already in the destination (same OR different name) —
            # point the EDU/mount refs at it and copy nothing.
            if alt != name:
                plan.model_renames[name] = alt
                plan.model_actions.append(ModelAction(name, "reuse_identical", alt,
                                          f"identical content already present as '{alt}'"))
            else:
                plan.model_actions.append(ModelAction(name, "reuse_identical", name,
                                                      "identical incl. filenames"))
            continue
        if name in dest_models:                  # same name, DIFFERENT content
            new_name = _unique_name(name + "_" + _tag(source), taken_names)
            taken_names.add(new_name)
            plan.model_renames[name] = new_name
            plan.add_entries.append((new_name, entry))
            plan.model_actions.append(ModelAction(name, "rename", new_name,
                                                  "name collision, different content"))
            dest_by_content.setdefault(key, new_name)
        else:
            taken_names.add(name)
            plan.add_entries.append((name, entry))
            plan.model_actions.append(ModelAction(name, "add", name))
            dest_by_content.setdefault(key, name)

        # animation check (for entries we actually add)
        for skel in entry.skeletons():
            if skel and skel not in dest_skeletons:
                if skel not in plan.missing_skeletons:
                    plan.missing_skeletons.append(skel)
                owners = plan.skeleton_models.setdefault(skel, [])
                if name not in owners:
                    owners.append(name)

        # assets for this model
        for rel in entry.mesh_files() + entry.texture_files():
            if rel in seen_assets:
                continue
            seen_assets.add(rel)
            src_abs = source.data / rel
            if src_abs.exists():
                plan.asset_files.append((src_abs, rel))
                # a .spr also needs its sheet textures, which nothing references
                if rel.lower().endswith(".spr"):
                    sheets = _sprite_sheets(source, rel)
                    for sheet_abs, sheet_rel in sheets:
                        if sheet_rel in seen_assets:
                            continue
                        seen_assets.add(sheet_rel)
                        plan.asset_files.append((sheet_abs, sheet_rel))
                    if not sheets:
                        plan.warnings.append(
                            f"no sheet textures (<name>_000.texture) found next to "
                            f"'{rel}' — far-away sprites may not render.")
            else:
                plan.missing_assets.append(rel)

    # the mount was brought across on a base unit's ticket — its animations are
    # the one thing the destination may not have, so they come from the base's
    if plan.mount_from_base_import:
        _apply_mount_anim_donor(plan, source, dest, unit, anim_donor)
    if plan.officer_from_base_import:
        _apply_officer_anim_donor(plan, source, dest, unit, off_donor)

    # ---- mount definition (descr_mount.txt) ----
    # The EDU's `mount` field names a block here, and that block's `model` field
    # names the modeldb entry (copied above). Without the block the destination
    # has a dangling mount reference and the unit never shows up in game.
    if unit.mount and "mount" not in plan.base_field_groups:
        src_m = source.mount_def(unit.mount)
        if src_m is None:
            plan.mount_action = "missing"
            plan.warnings.append(
                f"mount '{unit.mount}' has no entry in the source descr_mount.txt")
        else:
            dst_m = dest.mount_def(unit.mount)
            if dst_m is not None and dst_m.content_equals(src_m):
                plan.mount_action = "reuse"
                plan.mount_name = dst_m.type
            elif dst_m is not None:
                new_name = mounts.unique_mount_name(
                    unit.mount, dest.mount_file.by_type(), _tag(source))
                plan.mount_action = "rename"
                plan.mount_name = new_name
                plan.mount_rename = (unit.mount, new_name)
                plan.mount_raw = mounts.rewrite_mount_raw(
                    src_m.raw, type_new=new_name, model_map=plan.model_renames)
            else:
                plan.mount_action = "add"
                plan.mount_name = unit.mount
                plan.mount_raw = mounts.rewrite_mount_raw(
                    src_m.raw, model_map=plan.model_renames)
            if plan.mount_raw and not opts.include_mount:
                plan.warnings.append(
                    f"mount definition '{plan.mount_name}' is being added but its model "
                    f"'{src_m.model}' was excluded — that model must already exist in "
                    "the destination.")

    # ---- siege engine (descr_engines.txt + descr_engine_skeleton.txt) ----
    # Resolved BEFORE projectiles so the engine's own `attack_stat` projectiles are
    # part of the same resolution (and share its rename decisions).
    if opts.include_engine:
        _resolve_engines(plan, source, dest, unit, opts, seen_assets)

    # ---- projectile definitions (descr_projectile.txt) ----
    # A missile unit's stat_pri/stat_sec name a projectile defined in
    # descr_projectile.txt. When a base unit supplies the stats, the projectile is
    # the base's (already in the destination), so we only port projectiles when the
    # unit keeps its own stats. An engine's projectiles come along regardless: the
    # engine block is copied verbatim and would otherwise dangle. Effects are NOT
    # ported: any effect-set the destination lacks becomes a harmless placeholder.
    if opts.include_projectile:
        wanted_projectiles = (list(unit.projectiles()) if plan.base_unit is None
                              else _override_projectiles(opts))
        wanted_projectiles += plan.engine_projectiles
        _resolve_projectiles(plan, source, dest, wanted_projectiles, opts)

    # a projectile was renamed on collision -> repoint the engine's attack_stat lines
    if plan.projectile_renames:
        for bucket in (plan.engine_raws, plan.mounted_engine_raws):
            for i, raw in enumerate(bucket):
                bucket[i] = engines_mod.rewrite_engine_raw(
                    raw, projectile_map=plan.projectile_renames)

    # ---- relocation: reroute / mod_folder ----
    # Move every copied mesh/texture under a target folder (keeping its structure
    # below unit_models/), so nothing can collide with the destination's files.
    # The bmdb path strings are rewritten to match at apply time via path_map.
    if opts.asset_conflict in ("reroute", "mod_folder"):
        target = reloc_target
        if not target:
            plan.option_error = ("no reroute folder chosen — pick or type a folder "
                                 "under unit_models/ (e.g. unit_models/MyFolder)")
        else:
            plan.reroute_dir = target
            prefix = UNIT_MODELS + "/"
            remapped: List[Tuple[Path, str]] = []
            skipped_outside = 0
            for src_abs, rel in plan.asset_files:
                if rel.startswith(prefix) and not rel.startswith(target + "/"):
                    new_rel = f"{target}/{rel[len(prefix):]}"
                    plan.path_map[rel] = new_rel
                    remapped.append((src_abs, new_rel))
                else:
                    # outside unit_models/ (e.g. sprites) — cannot be relocated safely
                    if not rel.startswith(prefix):
                        skipped_outside += 1
                    remapped.append((src_abs, rel))
            plan.asset_files = remapped
            plan.warnings.append(
                f"assets relocated to '{target}/' ({len(plan.path_map)} file(s)); "
                "the added battle_models.modeldb entries point at the new paths.")
            if skipped_outside:
                plan.warnings.append(
                    f"{skipped_outside} file(s) outside {UNIT_MODELS}/ were left "
                    "where they are (only unit_models paths can be relocated).")

    # ---- icons ----
    # Without merc_icons, every faction the unit ends up owned by needs its OWN
    # copy of the card/info file (the game looks in ui/units/<player's faction>/,
    # not just wherever the source happened to keep it) — this is what a unit
    # shared between several factions (e.g. two factions both fielding the same
    # mercenary-flavoured troop) needs, and it's also what makes an ownership
    # change (base template / `ownership` override) land the icon where the
    # destination faction will actually look, instead of pinning *_pic_dir back
    # at the source's folder. The mercs/merc fallback folder is always included
    # too, since a unit with `mercenary_unit` set (already, or via make_mercenary)
    # falls back to it whenever *_pic_dir isn't pinned.
    # Replacing an existing unit leaves its cards alone unless asked: the point of
    # the mode is usually "give this unit better models", and the unit already has
    # a card that matches its name. Each is opted into on its own, because a new
    # model often wants a new unit card while the info card still reads correctly.
    final_ownership = ([f for f in final_own if f != "slave"] or final_own
                       or [f for f in unit.ownership if f != "slave"] or list(unit.ownership))
    want_card = opts.import_card if plan.replace_type else True
    want_info = opts.import_info_card if plan.replace_type else True
    card = source.find_unit_card(unit) if want_card else None
    info = source.find_unit_info(unit) if want_info else None
    # A rename conflict points the EDU/loc entry at `resolved_dict`, and the game
    # looks up the card/info card BY THAT DICTIONARY NAME (`#<dict>.tga` /
    # `<dict>_info.tga`) — so a renamed unit's icons must land under the NEW name,
    # not the source's filename, or they'd silently fail to show in-game (and a
    # stale conflict would be reported against the old unit's icon instead).
    dict_renamed = plan.resolved_dict != unit.dictionary
    for kind, icon, pic_dir_key, merc_folder, base_dir, stem_fmt in (
            ("card", card, "card_pic_dir", MERC_CARD_DIR, "ui/units", "#{}"),
            ("info", info, "info_pic_dir", MERC_INFO_DIR, "ui/unit_info", "{}_info")):
        if icon is None:
            continue
        fname = (stem_fmt.format(plan.resolved_dict) + icon.suffix) if dict_renamed else icon.name
        if opts.merc_icons:
            # a mercenary's icons live in the merc folders only, pinned with *_pic_dir
            plan.icon_dir_overrides[pic_dir_key] = merc_folder
            plan.icon_files.append((icon, f"{base_dir}/{merc_folder}/{fname}"))
        else:
            # one copy per owning faction, plus the mercs/merc fallback — no
            # *_pic_dir pin needed since every faction finds its own copy
            for folder in dict.fromkeys(final_ownership + [merc_folder]):
                plan.icon_files.append((icon, f"{base_dir}/{folder}/{fname}"))
    if card is None and want_card:
        plan.warnings.append("no unit card icon found in source")
    if info is None and want_info:
        plan.warnings.append("no unit info icon found in source")
    if plan.replace_type and not (want_card and want_info):
        kept = ("its unit card and info card" if not (want_card or want_info)
                else "its info card" if want_card else "its unit card")
        plan.warnings.append(f"'{plan.replace_type}' keeps {kept} — the source's "
                             "is not copied over it.")

    # ---- mercenary ----
    if opts.make_mercenary:
        plan.mercenary = True
        plan.warnings.append(
            f"mercenary attribute: '{MERC_ATTR}' attribute added, bmdb entries "
            f"get a '{MERC_TEX_FACTION}' skin.")
        plan.warnings.append(
            "mercenary: to actually recruit it, add a pool entry in "
            "data/world/maps/campaign/imperial_campaign/descr_mercenaries.txt — "
            "this tool does not write that file.")
    if opts.merc_icons:
        plan.merc_icons = True
        plan.warnings.append(
            f"mercenary icons: card/info card go to ui/units/{MERC_CARD_DIR}/ + "
            f"ui/unit_info/{MERC_INFO_DIR}/ (pinned via card_pic_dir/info_pic_dir).")

    # ---- voice bank ----
    _resolve_sound(plan, dest)

    # ---- asset name/path conflicts (byte comparison) ----
    # For every file we'd copy, if the destination already has a file with the
    # same name AND path, byte-compare them so the user can choose whether a
    # differing file should be overwritten or the destination's kept.
    def scan_conflict(src_abs: Path, rel: str, kind: str):
        dst_abs = dest.data / rel
        if not dst_abs.exists():
            return
        try:
            s_size = src_abs.stat().st_size
            d_size = dst_abs.stat().st_size
        except OSError:
            return
        # cheap check first: differing sizes can't be identical
        identical = s_size == d_size and filecmp.cmp(src_abs, dst_abs, shallow=False)
        plan.asset_conflicts.append(
            AssetConflict(rel=rel, identical=identical, src_size=s_size,
                          dst_size=d_size, kind=kind))

    engine_rels = {r.lower() for r in plan.engine_assets}
    for src_abs, rel in plan.asset_files:
        kind = ("engine" if rel.lower() in engine_rels
                else "mesh" if rel.lower().endswith(".mesh") else "texture")
        scan_conflict(src_abs, rel, kind)
    for src_abs, rel in plan.icon_files:
        scan_conflict(src_abs, rel, "icon")

    # An imported card lands on the replaced unit's OWN card — same folder, same
    # `#<dict>.tga` name — so keeping the destination's file means the import
    # writes nothing at all. Say so rather than reporting a copy that won't happen.
    if plan.replace_type and plan.icon_files and opts.icon_conflict != "overwrite":
        if any(c.kind == "icon" and not c.identical for c in plan.asset_conflicts):
            plan.warnings.append(
                f"the imported card(s) would replace '{plan.replace_type}'s own files, but "
                "the icon rule is set to keep the destination's — nothing would be written. "
                "Choose 'overwrite' under Unit card / info icons.")

    diff_conflicts = [c for c in plan.asset_conflicts if not c.identical]
    if diff_conflicts:
        plan.warnings.append(
            f"{len(diff_conflicts)} asset file(s) already exist in the destination with "
            "DIFFERENT content — choose overwrite or keep-existing before applying.")
    diff_engine = [c for c in diff_conflicts if c.kind == "engine"]
    if diff_engine:
        keeping = opts.engine_conflict != "overwrite"
        plan.warnings.append(
            f"{len(diff_engine)} SIEGE-ENGINE file(s) exist in the destination with "
            "different content: " + ", ".join(c.rel for c in diff_engine[:6])
            + (" …" if len(diff_engine) > 6 else "")
            + (". Keeping the destination's versions (the engine may render with the "
               "destination's skin) — engine files cannot be relocated because each "
               "mesh has its texture paths baked into the binary."
               if keeping else
               ". OVERWRITING them, which also re-skins the destination's OWN engines "
               "that share these files."))

    return plan


def _tag(mod: Mod) -> str:
    """Short lowercase tag from a mod name for rename suffixes."""
    import re
    letters = re.sub(r"[^a-z0-9]", "", mod.name.lower())
    return letters[:4] or "src"


# --------------------------------------------------------------------------
def _build_unit_block(plan: TransferPlan, unit) -> str:
    """Compose the EDU block to write: base template + rename/model rewrites + overrides."""
    # A parsed block runs up to the next `type` line in the SOURCE file, so it can
    # drag along blank lines and a decorative section-banner comment that actually
    # introduces the NEXT source unit — meaningless (and confusing) once copied
    # alone into the destination file.
    block = edu_mod.strip_trailing_filler(unit.raw)
    # 1) inherit stats/attrs/ownership/era from the base unit, if any. Replacing
    #    inherits the icon-folder pins too — the block keeps the replaced unit's
    #    identity, so its cards must stay findable where they already are.
    if plan.base_unit is not None:
        block = compose_with_base(
            block, plan.base_unit.raw, plan.base_field_groups,
            copy_keys=edu_mod.REPLACE_COPY_KEYS if plan.replace_type else None)
    # pin the icon folders (base ownership change, or the merc folders) — placed
    # right before recruit_priority_offset, matching where mods conventionally
    # keep these fields, instead of always trailing at the very end of the block.
    # Reversed so each insert lands right before the anchor: dict order is
    # card_pic_dir then info_pic_dir, and inserting info_pic_dir FIRST (right
    # before recruit_priority_offset) then card_pic_dir (also right before it,
    # pushing info_pic_dir down) yields the conventional info/card/recruit order.
    for key, folder in reversed(list(plan.icon_dir_overrides.items())):
        block = edu_mod.set_field_before(block, key, folder,
                                         anchor_keys=("recruit_priority_offset",))
    # 2) apply conflict rename + bmdb model-ref renames
    type_new = plan.resolved_type if plan.resolved_type != plan.unit_type else None
    dict_new = plan.resolved_dict if plan.resolved_dict != unit.dictionary else None
    if type_new or dict_new or plan.model_renames:
        block = edu_mod.rewrite_block(block, type_new=type_new, dict_new=dict_new,
                                      model_map=plan.model_renames)
    # the mount definition was renamed to dodge a clash -> point the EDU at it
    if plan.mount_rename:
        block = edu_mod.set_field(block, "mount", plan.mount_rename[1])
    # a projectile was renamed on collision -> repoint the stat_pri/stat_sec token
    if plan.projectile_renames:
        block = edu_mod.rewrite_stat_projectile(block, plan.projectile_renames)
    # a siege engine was renamed to dodge a clash -> point the EDU at the new name
    for field_key, new_name in plan.engine_renames.items():
        block = edu_mod.set_field(block, field_key, new_name)
    # 3) pin accent / voice_type at the block the copied voice entry lives in —
    #    before the manual overrides, so typing your own accent still wins (the
    #    composer locks those two fields, but a saved batch config could carry one)
    if plan.sound_action == "copy":
        block = sounds.set_voice_fields(block, plan.sound_accent, plan.sound_class)
    # 4) manual per-field overrides. `type` and `dictionary` are not editable when
    #    replacing: they ARE the unit being replaced, and rewriting one here would
    #    rename that unit (and orphan its localisation entry and icons) rather
    #    than swap its models.
    locked = ("type", "dictionary") if plan.replace_type else ()
    for k, v in plan.options.field_overrides.items():
        if k in locked:
            continue
        block = edu_mod.set_field(block, k, v)
    # 5) mercenary flag last, so a manual `attributes` override can't drop it
    if plan.mercenary:
        block = edu_mod.add_attribute(block, MERC_ATTR)
    return block


def apply_transfer(plan: TransferPlan) -> Dict:
    """Apply the plan in-place into the destination mod, with backups + a log record."""
    if plan.base_error:
        raise ValueError("cannot apply: " + plan.base_error)
    if plan.option_error:
        raise ValueError("cannot apply: " + plan.option_error)
    if plan.skipped:
        log.info("APPLY  %r skipped — it already exists in %s and the conflict "
                 "option is 'skip'; nothing was written", plan.unit_type, plan.dest.name)
        rec = _base_record(plan, applied=False, note="skipped (unit exists, conflict=skip)")
        config.append_log(rec)
        return rec

    dest = plan.dest
    source = plan.source
    unit = source.edu.by_type()[plan.unit_type]
    tid = config.new_transfer_id()
    backup_root = config.backup_root_for(tid)

    # Both mods, as they are on disk *before* anything is written. When a transfer
    # produces a broken destination the first question is which files these were.
    fingerprint(source)
    fingerprint(dest)
    log.info("APPLY  id=%s  %r  %s -> %s", tid, plan.unit_type, source.name, dest.name)
    log.info("  backups -> %s", backup_root)
    _log_plan(plan)

    manifest = {"backed_up": [], "created": []}

    def backup_and(rel: str) -> Path:
        """Ensure a backup of dest/data/<rel> exists (if the file exists) and return the target path."""
        target = dest.data / rel
        if target.exists():
            bpath = backup_root / "data" / rel
            bpath.parent.mkdir(parents=True, exist_ok=True)
            if not bpath.exists():
                shutil.copy2(target, bpath)
            manifest["backed_up"].append(rel)
            file_op("BACKUP", target, f"-> {bpath}")
        else:
            manifest["created"].append(rel)
        return target

    def write_text(rel: str, text: str, encoding: str, exact: bool = False):
        """Write one of the destination's text files.

        ``exact`` writes the string's line endings through untouched, for the
        parsers that now READ them untouched (projectiles, mounts, engines).
        Everything else still lets the platform put the CR back, because its
        serialiser emits bare LF and always has. Handing exact text to the
        translating writer would turn every CRLF into CRCRLF.
        """
        target = backup_and(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        if exact:
            kb.write_text(target, text, encoding)
        else:
            target.write_text(text, encoding=encoding)
        file_op("WRITE", target, f"{encoding}, {len(text)} chars")

    conflicts = {c.rel: c for c in plan.asset_conflicts}
    # Relocating modes write into a folder of our own, so replacing anything that
    # happens to sit there is the right call.
    asset_mode = ("overwrite"
                  if plan.options.asset_conflict in ("overwrite", "reroute", "mod_folder")
                  else "use_existing")
    icon_mode = "overwrite" if plan.options.icon_conflict == "overwrite" else "use_existing"
    # Engine files sit outside unit_models/ and are never relocated (their textures
    # are baked into the mesh binaries), so a relocating asset mode must NOT drag
    # them along into overwriting the destination's shared siege-engine files.
    engine_mode = ("overwrite" if plan.options.engine_conflict == "overwrite"
                   else "use_existing")

    def copy_asset(src_abs: Path, rel: str, mode: str):
        target = dest.data / rel
        if target.exists():
            c = conflicts.get(rel)
            identical = c.identical if c is not None else (
                target.stat().st_size == src_abs.stat().st_size
                and filecmp.cmp(src_abs, target, shallow=False))
            if identical:
                file_op("SAME", target, "byte-identical in both mods — not copied")
                return                       # byte-identical -> reuse existing
            if mode != "overwrite":
                # differing file, user chose to keep the destination's version
                manifest.setdefault("kept_existing", []).append(rel)
                file_op("KEEP", target, f"differs from the source's copy, mode={mode}")
                return
            backup_and(rel)                  # overwriting a differing file: back up first
        else:
            manifest["created"].append(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_abs, target)
        file_op("COPY", target, f"from {src_abs}")

    # ---- 1) EDU (and/or the M2TWEOP unit files) ----
    edu_text, eop_texts, eop_removes = _compose_edu(plan, unit)
    if edu_text:
        write_text("export_descr_unit.txt", edu_text, edu_mod.ENCODING)
    if eop_texts or eop_removes:
        eop.write_split(dest, eop_texts, eop_removes, backup_root, manifest)

    # ---- 2) localisation ----
    # A replaced unit keeps its own name and description: the entry belongs to the
    # destination unit, which still exists and is still called what it was called.
    # Overwriting it would rename a unit the player already knows, which is not
    # what "swap this unit's models" asks for.
    loc_entry = None if plan.replace_type else source.loc.get(unit.dictionary)
    if loc_entry is not None:
        loc_text = dest.export_units_path.read_text(encoding=localization.ENCODING)
        loc_text = localization.upsert_record(
            loc_text, plan.resolved_dict,
            loc_entry.name or "", loc_entry.descr or "", loc_entry.descr_short or "")
        write_text("text/export_units.txt", loc_text, localization.ENCODING)
    elif not plan.replace_type:
        plan.warnings.append("source localisation missing; none written")

    # ---- 3) modeldb ----
    if plan.add_entries:
        db = dest.modeldb
        base = len(db.entries)
        appended = []
        for final_name, entry in plan.add_entries:
            raw = (modeldb.rename_entry_raw(entry.raw, final_name)
                   if final_name != entry.name else entry.raw)
            # point the entry at the relocated files (re-emits correct length
            # prefixes); a no-op when nothing was rerouted
            raw = modeldb.rewrite_entry_paths(raw, plan.path_map, pad=entry.first_entry_pad)
            # give every faction the unit now belongs to a texture record
            if plan.texture_factions:
                raw = modeldb.add_texture_factions(
                    raw, plan.texture_factions, prefer=plan.texture_donor or None,
                    pad=entry.first_entry_pad)
            new_entry = modeldb.ModelEntry(
                name=final_name, scale=entry.scale, lods=entry.lods,
                main_textures=entry.main_textures, attach_textures=entry.attach_textures,
                animations=entry.animations, torch_index=entry.torch_index,
                torch=entry.torch, raw=raw)
            appended.append(new_entry)
        db.entries.extend(appended)
        text = db.to_text()
        del db.entries[base:]          # keep cached db pristine
        write_text("unit_models/battle_models.modeldb", text, modeldb.ENCODING)

    # ---- 3b) mount definition (descr_mount.txt) ----
    if plan.mount_raw:
        mtext = dest.mount_file.to_text()
        if mtext.strip():
            mtext = mtext.rstrip("\r\n") + "\n\n" + plan.mount_raw
        else:                       # destination had no descr_mount.txt at all
            mtext = plan.mount_raw
        nl = kb.newline_of(mtext)
        mtext = kb.to_newline(mtext, nl)
        if not mtext.endswith(nl):
            mtext += nl
        write_text("descr_mount.txt", mtext, mounts.ENCODING, exact=True)

    # ---- 3c) projectile definitions (descr_projectile.txt) ----
    if plan.projectile_raws:
        ptext = dest.projectile_file.to_text()
        # The block comes out of the SOURCE mod and need not be written the way
        # this file is written, so it is rewritten to the destination's ending
        # rather than dropped into the middle of it as it stands.
        nl = kb.newline_of(ptext)
        block = (nl + nl).join(r.strip("\r\n") for r in plan.projectile_raws)
        if ptext.strip():
            ptext = ptext.rstrip("\r\n") + nl + nl + block
        else:                       # destination had no descr_projectile.txt at all
            ptext = block
        ptext = kb.to_newline(ptext, nl)
        if not ptext.endswith(nl):
            ptext += nl
        write_text("descr_projectile.txt", ptext, projectiles_mod.ENCODING, exact=True)

    # ---- 3d) siege engines ----
    for rel, raws, current in (
            ("descr_engines.txt", plan.engine_raws,
             lambda: dest.engine_file.to_text()),
            ("descr_mounted_engines.txt", plan.mounted_engine_raws,
             lambda: dest.mounted_engine_file.to_text()),
            ("descr_engine_skeleton.txt", plan.engine_skeleton_raws,
             lambda: dest.engine_skeleton_file.to_text())):
        if not raws:
            continue
        text = current()
        nl = kb.newline_of(text)          # same rule as the projectiles above
        block = (nl + nl).join(r.strip("\r\n") for r in raws)
        text = (text.rstrip("\r\n") + nl + nl + block) if text.strip() else block
        text = kb.to_newline(text, nl)
        if not text.endswith(nl):
            text += nl
        write_text(rel, text, engines_mod.ENCODING, exact=True)

    # ---- 3e) voice bank ----
    if plan.sound_text:
        write_text(sounds.EDS_REL, plan.sound_text, sounds.ENCODING)

    # ---- 4) assets + icons ----
    engine_rels = {r.lower() for r in plan.engine_assets}
    for src_abs, rel in plan.asset_files:
        copy_asset(src_abs, rel,
                   engine_mode if rel.lower() in engine_rels else asset_mode)
    for src_abs, rel in plan.icon_files:
        copy_asset(src_abs, rel, icon_mode)

    rec = _base_record(plan, applied=True, transfer_id=tid)
    rec["manifest"] = manifest
    rec["backup_root"] = str(backup_root)
    config.append_log(rec)

    counted(manifest, [f"written as {plan.resolved_type!r}"
                       + (f" into the M2TWEOP file {plan.eop_file}" if plan.eop_file
                          else " in export_descr_unit.txt")])
    log.info("APPLY  done id=%s", tid)

    # invalidate dest caches so a subsequent plan sees the new state
    _invalidate(dest)
    return rec


def _log_plan(plan: TransferPlan) -> None:
    """Everything the planner decided, before any of it is written.

    The human summary in :meth:`TransferPlan.summary` is what the UI shows and it
    is already logged; this is the part that summary deliberately leaves out —
    every model, every renamed name, every file, every path rewrite. It only
    exists to be read after the fact, so it goes to the file at DEBUG and the
    console never sees it.
    """
    opts = plan.options
    block("  options:", [
        f"mode             {opts.mode}"
        + (f"   [replacing {plan.replace_type!r}]" if plan.replace_type else ""),
        f"base unit        {opts.base_type or '(none)'}",
        f"on_conflict      {opts.on_conflict}"
        + ("   (the destination already has this type)" if plan.unit_conflict else ""),
        f"asset_conflict   {opts.asset_conflict}",
        f"icon_conflict    {opts.icon_conflict}",
        f"engine_conflict  {opts.engine_conflict}",
        f"eop_target       {opts.eop_target}"
        + (f"   -> {plan.eop_file}" if plan.eop_file else "   -> export_descr_unit.txt"),
        f"reroute dir      {plan.reroute_dir or '(assets stay where they are)'}",
        "field groups     " + ", ".join(
            f"{g}={getattr(opts, g)}" for g in
            ("soldier_from", "officer_from", "mount_from", "crew_from", "upgrade_from")),
        "include          " + ", ".join(
            g for g in ("include_officers", "include_mount", "include_crew",
                        "include_projectile", "include_engine")
            if getattr(opts, g)),
        f"taken from base  {', '.join(plan.base_field_groups) or '(none)'}",
        f"mercenary        attribute={plan.mercenary}, icons={plan.merc_icons}",
        f"sound            mode={opts.sound_mode}, donor={opts.sound_donor or '(none)'}"
        f" -> action={plan.sound_action or '(none)'}",
        f"field overrides  {', '.join(sorted(opts.field_overrides)) or '(none)'}",
        f"excluded models  {', '.join(opts.exclude_models) or '(none)'}",
    ], level=logging.DEBUG)

    block("  battle model entries:",
          [f"{a.source_name} -> {a.final_name}  [{a.action}]"
           + (f"  — {a.reason}" if a.reason else "")
           for a in plan.model_actions] or ["(none)"], level=logging.DEBUG)
    if plan.path_map:
        block("  asset paths rewritten in the copied bmdb entries:",
              [f"{old} -> {new}" for old, new in sorted(plan.path_map.items())],
              level=logging.DEBUG)
    block(f"  asset files to copy ({len(plan.asset_files)}):",
          [rel for _src, rel in plan.asset_files] or ["(none)"], level=logging.DEBUG)
    block(f"  icon files to copy ({len(plan.icon_files)}):",
          [rel for _src, rel in plan.icon_files] or ["(none)"], level=logging.DEBUG)
    if plan.asset_conflicts:
        block(f"  files that already exist in the destination ({len(plan.asset_conflicts)}):",
              [f"{c.rel}  [{c.kind}]  "
               + ("identical" if c.identical
                  else f"DIFFERENT — source {c.src_size} B, destination {c.dst_size} B")
               for c in plan.asset_conflicts], level=logging.DEBUG)
    # name the model behind each missing skeleton: "EUR_Troll_Mace_XL" alone doesn't
    # say whether the soldier line, an officer or the mount dragged it in.
    soldier_skels = set(plan.soldier_skeletons_missing())
    for label, names in (("missing models", plan.missing_models),
                         ("missing skeletons",
                          [s + "   <- " + (", ".join(plan.skeleton_models.get(s, []))
                                           or "?")
                           + ("  [SOLDIER line]" if s in soldier_skels else "")
                           for s in plan.missing_skeletons]),
                         ("missing assets", plan.missing_assets),
                         ("excluded secondaries", plan.excluded_secondaries)):
        if names:
            block(f"  {label} ({len(names)}):", names, level=logging.DEBUG)
    # Warnings are the one part of the plan that is genuinely worth a console
    # line: they are what the user was told, and a report that disagrees with
    # them is a report about something else.
    if plan.warnings:
        block(f"  warnings ({len(plan.warnings)}):", plan.warnings)


def _compose_edu(plan: TransferPlan, unit) -> Tuple[str, Dict[str, str], List[str]]:
    """The destination's unit files after applying the conflict resolution.

    Returns ``(EDU text or "", {M2TWEOP file: text}, [EOP files to remove])``. The
    EDU text is "" only when nothing about that file changes — which happens when
    the unit is written as an M2TWEOP unit and did not replace an EDU unit.

    Overwriting is the case that needs care: the unit being replaced can live in
    the EDU while the replacement is going to an EOP file (or the other way
    round), so the old block has to be taken out of *its* file rather than out of
    whichever file the new one lands in.
    """
    dest = plan.dest
    block = _build_unit_block(plan, unit)

    # Replacing rewrites one unit IN PLACE: the new block goes exactly where the
    # old one was, in the file it was already in, keeping the blank lines and
    # section banner that followed it. Nothing is appended and nothing moves, so
    # a modder's own EDU layout survives the swap.
    if plan.replace_type:
        replaced = dest.edu.by_type().get(plan.replace_type)
        stand_in = dc_replace(replaced,
                              raw=block + edu_mod.trailing_filler(replaced.raw))
        units = [stand_in if u.type == plan.replace_type else u for u in dest.edu.units]
        split = eop.compose(dest, units)
        return split.main, dict(split.files), list(split.removed)

    overwriting = plan.unit_conflict and plan.options.on_conflict == "overwrite"
    kept = [u for u in dest.edu.units if u.type != plan.unit_type] if overwriting \
        else list(dest.edu.units)
    split = eop.compose(dest, kept)
    edu_text, eop_texts = split.main, dict(split.files)
    removes = list(split.removed)

    if plan.eop_file:
        # its own file: the removal of an emptied file it is about to rewrite is
        # not a removal at all, so take it back off that list
        removes = [r for r in removes if r != plan.eop_file]
        preamble = (dest.edu.eop_preambles.get(plan.eop_file, "")
                    if plan.eop_file in dest.edu.eop_preambles else "")
        base = eop_texts.get(plan.eop_file)
        if base is None and plan.eop_file != plan.eop_replaced:
            eop_texts[plan.eop_file] = eop.unit_file_text(preamble, block)
        else:
            body = (base if base is not None
                    else eop.unit_file_text(preamble, "")).rstrip("\r\n")
            eop_texts[plan.eop_file] = (body + "\n\n\n" if body else "") + block
        return edu_text, eop_texts, removes

    # the EDU: append after exactly two blank lines, regardless of how the
    # existing file happened to end
    text = (edu_text or dest.edu.to_text()).rstrip("\r\n") + "\n" + "\n\n"
    return text + block, eop_texts, removes


def _base_record(plan: TransferPlan, applied: bool, transfer_id: str = "",
                 note: str = "") -> Dict:
    return {
        "id": transfer_id or config.new_transfer_id(),
        "when": __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
        "source": plan.source.name,
        "source_root": str(plan.source.root),
        "dest": plan.dest.name,
        "dest_root": str(plan.dest.root),
        "unit_type": plan.unit_type,
        "resolved_type": plan.resolved_type,
        "options": asdict(plan.options),
        "applied": applied,
        "undone": False,
        "note": note,
        "summary": plan.summary(),
        "warnings": list(plan.warnings) + [f"animation missing: {s}" for s in plan.missing_skeletons],
    }


def _invalidate(mod: Mod):
    """Every cached read of this mod is now stale — see :meth:`Mod.drop_caches`."""
    mod.drop_caches()


# --------------------------------------------------------------------------
def undo(transfer_id: str) -> Dict:
    """Revert an applied transfer using its backup manifest."""
    entries = config.load_log()
    rec = next((e for e in entries if e.get("id") == transfer_id), None)
    if rec is None:
        raise KeyError(f"no transfer with id {transfer_id}")
    if not rec.get("applied") or rec.get("undone"):
        return rec
    dest_root = Path(rec["dest_root"])
    data = dest_root / "data"
    backup_root = Path(rec.get("backup_root", ""))
    manifest = rec.get("manifest", {})

    # restore overwritten files
    for rel in manifest.get("backed_up", []):
        bpath = backup_root / "data" / rel
        if bpath.exists():
            target = data / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(bpath, target)
    # delete created files
    for rel in manifest.get("created", []):
        target = data / rel
        try:
            if target.exists():
                target.unlink()
        except OSError:
            pass
    # M2TWEOP unit files: these are absolute paths outside data/ (often outside
    # the mod), so they carry their own backup location rather than being resolved
    # against `data` like everything above.
    eop.restore_split(manifest)

    config.update_log(transfer_id, undone=True)
    rec["undone"] = True
    return rec


def revert_to(transfer_id: str) -> Dict:
    """Roll the destination mod back to its state right AFTER ``transfer_id``.

    Every newer applied-and-not-yet-undone transfer to the *same destination* is
    undone, newest first (so overlapping per-file backups restore in the right
    order). The target transfer and everything before it are left in place — the
    mod ends up exactly as it was when this log entry finished.

    Each intermediate undo restores that transfer's byte-exact backups (EDU /
    localisation / modeldb / overwritten textures) and deletes the files it
    created (moved-in textures), so the whole chain reverts cleanly.
    """
    entries = config.load_log()
    idx = next((i for i, e in enumerate(entries) if e.get("id") == transfer_id), None)
    if idx is None:
        raise KeyError(f"no transfer with id {transfer_id}")
    target = entries[idx]
    dest_root = target.get("dest_root")
    dest_name = target.get("dest")

    # newer transfers to the SAME destination that are still in effect
    newer = [e for e in entries[idx + 1:]
             if e.get("dest_root") == dest_root
             and e.get("applied") and not e.get("undone")]

    undone_ids: List[str] = []
    for e in reversed(newer):          # newest first
        undo(e["id"])
        undone_ids.append(e["id"])

    return {
        "reverted_to": transfer_id,
        "dest": dest_name,
        "undone_ids": undone_ids,
        "count": len(undone_ids),
    }
