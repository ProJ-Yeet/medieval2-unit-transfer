"""Unit *editing* engine — the second mode of the tool (Stage 13).

Where :mod:`unittransfer.transfer` moves a unit from one mod into another, this
module changes a unit **inside a single mod**:

  * edit any EDU field of an existing unit (including deleting a field outright —
    blanking a value is not the same thing to the game);
  * rename its ``type`` / ``dictionary`` (the dictionary rename carries the
    localisation record and the unit-card files with it, otherwise the unit
    silently loses its name and icons);
  * edit its localised name / description / short description;
  * edit the battle_models.modeldb entries it uses — every mesh / texture /
    normal-map / sprite path, and the entry name (EDU refs follow the rename);
  * create a NEW modeldb entry cloned from one the unit already uses: you point
    at a mesh and a texture on disk and say which folder inside ``data/`` they
    should land in, and the files are copied there and the entry rewritten to
    reference them. Sprites, the faction (ownership) texture records and the
    footer — animations/skeletons and the torch block — come from the cloned
    entry, so the new model stays valid;
  * delete a unit, optionally taking its localisation record, its now-unused
    modeldb entries and its icons with it.

Creating a *new unit from an existing one* is not implemented here: that is
exactly a transfer whose source and destination are the same mod, so the UI
reuses :func:`unittransfer.transfer.plan_transfer` for it and gets dedup,
conflict resolution, the base-unit templating and the field editor for free.

Every write goes through the same backup + log record as a transfer, so the
existing Undo / "Revert to here" buttons work on edits too.
"""
from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import config
from . import edu as edu_mod
from . import localization, modeldb
from .mod import Mod

# ---------------------------------------------------------------------------
# request objects (built from the JSON body by ``from_dict``)


# A unit block *is* its `type` line (that's where parsing starts), the game finds
# its name/icons through `dictionary`, and it needs a body model — removing any of
# these doesn't edit the unit, it corrupts the file.
PROTECTED_FIELDS = {"type", "dictionary", "soldier"}

# In a modeldb with no leading `blank` sentinel the FIRST entry carries the extra
# reserved int-pairs the game expects there (see modeldb._read_entry's ``pad``).
# Deleting it would leave an unpadded entry in that position and the file would no
# longer parse, so it is always kept.
PAD_ENTRY_KEPT = ("'{name}' is the modeldb's padded first entry — removing it would "
                  "corrupt the file (this mod has no 'blank' sentinel entry), so it "
                  "is kept.")


@dataclass
class ModelEdit:
    """Changes to an existing modeldb entry.

    ``paths`` addresses individual slots by span index (that's how meshes are
    edited). Textures go through ``defaults`` / ``faction_paths`` instead, keyed
    by faction + kind, because ticking a faction on or off in ``factions``
    renumbers every texture span — an index captured by the browser before that
    would land on the wrong slot.
    """
    entry: str                                   # entry name as it is today
    new_name: str = ""                           # rename (EDU refs follow)
    paths: Dict[int, str] = field(default_factory=dict)   # span index -> new path
    copies: List[dict] = field(default_factory=list)      # [{"i", "src"}] files to bring in
    # files copied into the mod without owning a slot — a texture imported for
    # the default/per-faction boxes is named by ``defaults``/``faction_paths``,
    # not by span index, so the copy has to be requested separately
    imports: List[dict] = field(default_factory=list)     # [{"src", "dest_dir"}]
    # texture kinds: texture | normal | sprite | attach_texture | attach_normal
    defaults: Dict[str, str] = field(default_factory=dict)          # applied to every faction
    faction_paths: Dict[str, Dict[str, str]] = field(default_factory=dict)  # per-faction override
    factions: Optional[List[str]] = None         # None = leave the records alone
    move_dir: str = ""                           # relocate mesh/textures under data/<move_dir>
    move_shared: bool = False                    # repoint other entries using those files too


@dataclass
class NewModel:
    """A new modeldb entry cloned from an existing one."""
    name: str
    clone_from: str
    dest_dir: str = ""                # folder under data/ the files are copied to
    mesh_src: str = ""                # absolute path of the .mesh to import
    mesh_all_lods: bool = True        # point every LOD at it (else only LOD 0)
    texture_src: str = ""             # absolute path of the .texture to import
    normal_src: str = ""
    sprite_src: str = ""              # blank -> keep the clone's sprites
    apply_to_attach: bool = False     # also repoint the attachment textures
    assign_to: str = ""               # EDU slot to point at the new entry


@dataclass
class DeleteOptions:
    remove_loc: bool = True
    remove_models: bool = False       # only entries no other unit/mount uses
    remove_assets: bool = False       # mesh/texture files of those entries
    remove_icons: bool = False


@dataclass
class EditRequest:
    unit: str
    new_type: str = ""
    new_dictionary: str = ""
    field_overrides: Dict[str, str] = field(default_factory=dict)
    remove_fields: List[str] = field(default_factory=list)
    loc: Optional[dict] = None                   # {name, descr, descr_short}
    model_edits: List[ModelEdit] = field(default_factory=list)
    new_models: List[NewModel] = field(default_factory=list)
    remove_old_icons: bool = False               # after a dictionary rename
    delete: bool = False
    delete_options: DeleteOptions = field(default_factory=DeleteOptions)


# Texture slots a faction record exposes to the editor. The attachment *sprite*
# is deliberately absent: the engine has no attachment sprites, so that slot is
# always the literal "0" and showing it only invites breaking it.
TEXTURE_KINDS = {("main", "texture"): "texture",
                 ("main", "normal"): "normal",
                 ("main", "sprite"): "sprite",
                 ("attach", "texture"): "attach_texture",
                 ("attach", "normal"): "attach_normal"}


def _clean_paths(d) -> Dict[str, str]:
    """Keep only the texture kinds we know, with a non-blank value.

    A blank field in the editor means "fall back to the default", never "write an
    empty path" — an entry with an empty texture string is one the game can't load.
    """
    known = set(TEXTURE_KINDS.values())
    return {str(k): str(v).replace("\\", "/").strip()
            for k, v in (d or {}).items()
            if str(k) in known and str(v).strip()}


def request_from_dict(d: dict) -> EditRequest:
    dops = d.get("delete_options") or {}
    return EditRequest(
        unit=d.get("unit") or "",
        new_type=(d.get("new_type") or "").strip(),
        new_dictionary=(d.get("new_dictionary") or "").strip(),
        field_overrides={str(k): str(v) for k, v in (d.get("field_overrides") or {}).items()},
        remove_fields=[str(x) for x in (d.get("remove_fields") or [])],
        loc=d.get("loc"),
        model_edits=[ModelEdit(entry=str(m.get("entry") or "").lower(),
                               new_name=(m.get("new_name") or "").strip(),
                               paths={int(k): str(v) for k, v in (m.get("paths") or {}).items()},
                               copies=list(m.get("copies") or []),
                               imports=list(m.get("imports") or []),
                               defaults=_clean_paths(m.get("defaults")),
                               faction_paths={str(f).lower(): _clean_paths(v)
                                              for f, v in (m.get("faction_paths") or {}).items()},
                               factions=([str(f).strip().lower()
                                          for f in m.get("factions") if str(f).strip()]
                                         if m.get("factions") is not None else None),
                               move_dir=(m.get("move_dir") or "").strip(),
                               move_shared=bool(m.get("move_shared", False)))
                     for m in (d.get("model_edits") or [])],
        new_models=[NewModel(name=(n.get("name") or "").strip().lower(),
                             clone_from=(n.get("clone_from") or "").strip().lower(),
                             dest_dir=(n.get("dest_dir") or "").strip(),
                             mesh_src=(n.get("mesh_src") or "").strip(),
                             mesh_all_lods=bool(n.get("mesh_all_lods", True)),
                             texture_src=(n.get("texture_src") or "").strip(),
                             normal_src=(n.get("normal_src") or "").strip(),
                             sprite_src=(n.get("sprite_src") or "").strip(),
                             apply_to_attach=bool(n.get("apply_to_attach", False)),
                             assign_to=(n.get("assign_to") or "").strip())
                    for n in (d.get("new_models") or [])],
        remove_old_icons=bool(d.get("remove_old_icons", False)),
        delete=bool(d.get("delete", False)),
        delete_options=DeleteOptions(
            remove_loc=bool(dops.get("remove_loc", True)),
            remove_models=bool(dops.get("remove_models", False)),
            remove_assets=bool(dops.get("remove_assets", False)),
            remove_icons=bool(dops.get("remove_icons", False))),
    )


# ---------------------------------------------------------------------------
# plan


@dataclass
class EditPlan:
    mod: Mod
    unit_type: str
    request: EditRequest
    label: str = ""                              # summary heading when no single unit owns the plan
    resolved_type: str = ""
    resolved_dict: str = ""
    edu_block: str = ""                          # the unit's block after editing
    edu_text: str = ""                           # whole file after editing ("" = unchanged)
    loc_text: str = ""                           # whole file after editing ("" = unchanged)
    entry_updates: Dict[str, str] = field(default_factory=dict)   # name -> new raw
    entry_renames: Dict[str, str] = field(default_factory=dict)   # old -> new
    new_entries: List[Tuple[str, str, bool]] = field(default_factory=list)  # (name, raw, pad)
    entry_deletes: List[str] = field(default_factory=list)
    copies: List[Tuple[Path, str]] = field(default_factory=list)  # (src abs, rel under data/)
    icon_copies: List[Tuple[Path, str]] = field(default_factory=list)
    deletes: List[str] = field(default_factory=list)              # rel paths to remove
    changes: List[str] = field(default_factory=list)              # human-readable preview
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def modeldb_touched(self) -> bool:
        return bool(self.entry_updates or self.new_entries or self.entry_deletes
                    or self.entry_renames)

    def summary(self) -> str:
        head = self.label or (
            f"delete '{self.unit_type}'" if self.request.delete
            else f"edit '{self.unit_type}'"
            + (f" -> '{self.resolved_type}'" if self.resolved_type != self.unit_type else ""))
        lines = [f"{head} in {self.mod.name}"]
        lines += ["  " + c for c in self.changes]
        lines += ["  ! " + w for w in self.warnings]
        return "\n".join(lines)


def _rel_under_data(mod: Mod, raw: str) -> Optional[str]:
    """Normalise a user-supplied destination to a path relative to ``data/``.

    Accepts ``data/unit_models/x``, ``unit_models/x`` or an absolute path inside
    the mod. Returns None when it would land outside ``data/`` — the game can't
    load those, and we must never write outside the mod.
    """
    s = (raw or "").replace("\\", "/").strip().strip("/")
    if not s:
        return None
    p = Path(s)
    if p.is_absolute():
        try:
            s = p.resolve().relative_to(mod.data.resolve()).as_posix()
        except ValueError:
            return None
    elif s.lower().startswith("data/"):
        s = s[5:]
    target = (mod.data / s).resolve()
    try:
        target.relative_to(mod.data.resolve())
    except ValueError:
        return None
    return s.strip("/")


def _model_users(mod: Mod, skip_unit: str = "") -> Dict[str, List[str]]:
    """model entry name (lower) -> the unit types / mounts that reference it."""
    users: Dict[str, List[str]] = {}
    for u in mod.edu.units:
        if u.type == skip_unit:
            continue
        for m in u.model_names():
            users.setdefault(m.lower(), []).append(u.type)
    for mount_name, model in (mod.mounts or {}).items():
        if model:
            users.setdefault(model.lower(), []).append(f"mount:{mount_name}")
    return users


def _unit_icon_files(mod: Mod, dictionary: str) -> List[Tuple[Path, str, str]]:
    """Every card/info file on disk for a dictionary: (abs, rel, new-name stem).

    Icons are found by faction folder + dictionary, so a rename has to touch all
    of them — not just the one the browser happens to show.
    """
    out: List[Tuple[Path, str, str]] = []
    for base, pattern, kind in ((mod.ui_units_dir, f"*/#{dictionary}.tga", "card"),
                                (mod.ui_unit_info_dir, f"*/{dictionary}_info.tga", "info")):
        if not base.is_dir():
            continue
        for p in sorted(base.glob(pattern)):
            out.append((p, p.relative_to(mod.data).as_posix(), kind))
    return out


def plan_edit(mod: Mod, req: EditRequest) -> EditPlan:
    unit = mod.edu.by_type().get(req.unit)
    if unit is None:
        raise KeyError(f"unit {req.unit!r} not found in {mod.name}")
    plan = EditPlan(mod=mod, unit_type=req.unit, request=req,
                    resolved_type=req.new_type or req.unit,
                    resolved_dict=req.new_dictionary or unit.dictionary)
    if req.delete:
        return _plan_delete(plan, unit)

    by_type = mod.edu.by_type()
    if req.new_type and req.new_type != unit.type and req.new_type in by_type:
        plan.errors.append(f"a unit called '{req.new_type}' already exists in {mod.name}")

    block = unit.raw
    db = mod.modeldb
    entries = db.by_name()

    # ---- 1) new modeldb entries (cloned from one the unit already uses) ----
    taken = set(entries.keys()) | {n.lower() for n, _, _ in plan.new_entries}
    for nm in req.new_models:
        _plan_new_model(plan, mod, nm, entries, taken)

    # ---- 2) edits to existing entries ----
    for me in req.model_edits:
        _plan_model_edit(plan, mod, me, entries, taken)

    # EDU refs must follow a renamed entry, or the unit points at nothing
    if plan.entry_renames:
        block = edu_mod.rewrite_block(block, model_map=plan.entry_renames)

    # ---- 3) EDU fields ----
    for label in req.remove_fields:
        key = edu_mod.split_label(label)[0]
        if key in PROTECTED_FIELDS:
            plan.errors.append(
                f"'{key}' cannot be removed — a unit block is defined by it "
                "(rename or edit it instead)")
        elif key in ("category", "class"):
            plan.warnings.append(f"removing '{key}' — the game needs it on every unit")
    if req.field_overrides or req.remove_fields:
        before = block
        block = edu_mod.apply_field_edits(block, req.field_overrides, req.remove_fields)
        if block != before:
            for label, val in sorted(req.field_overrides.items()):
                plan.changes.append(f"{label} = {val}")
            for label in req.remove_fields:
                plan.changes.append(f"removed field '{label}'")

    # ---- 4) point EDU slots at the new entries (only ones that really planned) ----
    planned = {n for n, _raw, _pad in plan.new_entries}
    for nm in req.new_models:
        if nm.assign_to and nm.name in planned:
            block = edu_mod.set_model_slot(block, nm.assign_to, nm.name)
            plan.changes.append(f"{nm.assign_to} -> {nm.name}")

    # ---- 5) type / dictionary rename ----
    if req.new_type and req.new_type != unit.type:
        block = edu_mod.rewrite_block(block, type_new=req.new_type)
        plan.changes.append(f"type '{unit.type}' -> '{req.new_type}'")
        plan.warnings.append(
            "renaming `type` does not touch other files — recruitment "
            "(export_descr_buildings.txt), descr_strat.txt and any scripts that "
            "name this unit must be updated by hand.")
    if req.new_dictionary and req.new_dictionary != unit.dictionary:
        block = edu_mod.rewrite_block(block, dict_new=req.new_dictionary)
        plan.changes.append(f"dictionary '{unit.dictionary}' -> '{req.new_dictionary}'")

    plan.edu_block = block
    # A renamed entry has to be chased through the WHOLE file: any other unit
    # still naming the old entry would point at nothing once it's gone.
    if plan.entry_renames:
        others = sorted({u.type for u in mod.edu.units if u.type != unit.type
                         and any(m in plan.entry_renames for m in u.model_names())})
        if others:
            plan.changes.append(
                f"{len(others)} other unit(s) repointed at the renamed entry: "
                f"{', '.join(others[:4])}{'…' if len(others) > 4 else ''}")
        mounted = sorted({n for n, m in (mod.mounts or {}).items()
                          if m in plan.entry_renames})
        if mounted:
            plan.warnings.append(
                f"mount(s) {', '.join(mounted)} name the renamed entry in "
                "descr_mount.txt — that file is not rewritten, fix it by hand.")
    if block != unit.raw or plan.entry_renames:
        plan.edu_text = _replace_block(mod, unit, block, model_map=plan.entry_renames)

    # ---- 6) localisation ----
    old_entry = mod.loc.get(unit.dictionary)
    loc = req.loc if req.loc is not None else None
    dict_changed = plan.resolved_dict != unit.dictionary
    if loc is not None or dict_changed:
        name = (loc or {}).get("name", (old_entry.name if old_entry else "") or "")
        descr = (loc or {}).get("descr", (old_entry.descr if old_entry else "") or "")
        short = (loc or {}).get("descr_short",
                                (old_entry.descr_short if old_entry else "") or "")
        text = mod.export_units_path.read_text(encoding=localization.ENCODING)
        text = localization.upsert_record(text, plan.resolved_dict, name, descr, short)
        if dict_changed:
            others = [u.type for u in mod.edu.units
                      if u.type != unit.type and u.dictionary == unit.dictionary]
            if others:
                plan.warnings.append(
                    f"'{unit.dictionary}' is also used by {', '.join(others[:3])}"
                    f"{'…' if len(others) > 3 else ''} — its old text entry is kept.")
            else:
                text = localization.remove_record(text, unit.dictionary)
                plan.changes.append(f"text entry '{unit.dictionary}' removed")
            plan.changes.append(f"text entry '{plan.resolved_dict}' written")
        elif loc is not None:
            plan.changes.append("name / description updated")
        plan.loc_text = text

    # ---- 7) icons follow a dictionary rename ----
    if dict_changed:
        icons = _unit_icon_files(mod, unit.dictionary)
        for abs_p, rel, kind in icons:
            new_name = (f"#{plan.resolved_dict}.tga" if kind == "card"
                        else f"{plan.resolved_dict}_info.tga")
            new_rel = abs_p.parent.relative_to(mod.data).as_posix() + "/" + new_name
            plan.icon_copies.append((abs_p, new_rel))
            plan.changes.append(f"icon copied to {new_rel}")
            if req.remove_old_icons:
                plan.deletes.append(rel)
        if not icons:
            plan.warnings.append(
                f"no unit card found for '{unit.dictionary}' — the renamed unit "
                f"will need data/ui/units/<faction>/#{plan.resolved_dict}.tga.")

    if not (plan.edu_text or plan.loc_text or plan.modeldb_touched
            or plan.copies or plan.icon_copies or plan.deletes):
        plan.changes.append("no changes")
    return plan


def bmdb_request_from_dict(d: dict) -> EditRequest:
    """Parse a *mod-wide* modeldb edit — the same body as an edit request minus
    the unit, so the browser can post the exact payload the unit editor builds."""
    return request_from_dict({"model_edits": d.get("model_edits"),
                              "new_models": d.get("new_models"), "unit": ""})


def plan_bmdb(mod: Mod, req: EditRequest) -> EditPlan:
    """Plan modeldb edits that belong to no particular unit (bmdb mode).

    Same engine as :func:`plan_edit` — the entry editor, the new-entry cloner and
    the folder standardiser are shared verbatim — but nothing here reads or writes
    a unit block *except* to chase a renamed entry through the whole EDU, which is
    mandatory: units name their models by string, so a rename that stopped at the
    modeldb would leave every user of the entry pointing at nothing.
    """
    names = [me.entry for me in req.model_edits] + [nm.name for nm in req.new_models]
    plan = EditPlan(mod=mod, unit_type="", request=req,
                    label=f"edit {len(names)} battle-model "
                          f"entr{'y' if len(names) == 1 else 'ies'}",
                    resolved_type=", ".join(names[:3]) + ("…" if len(names) > 3 else ""))
    entries = mod.modeldb.by_name()
    taken = set(entries.keys())
    for nm in req.new_models:
        _plan_new_model(plan, mod, nm, entries, taken)
        if nm.assign_to:
            plan.warnings.append(
                f"'{nm.name}': bmdb mode edits no unit, so nothing was pointed at "
                f"the new entry — set '{nm.assign_to}' in the unit editor.")
    for me in req.model_edits:
        _plan_model_edit(plan, mod, me, entries, taken)

    if plan.entry_renames:
        plan.edu_text = mod.edu.preamble + "".join(
            edu_mod.rewrite_block(u.raw, model_map=plan.entry_renames)
            for u in mod.edu.units)
        users = sorted({u.type for u in mod.edu.units
                        if any(m in plan.entry_renames for m in u.model_names())})
        if users:
            plan.changes.append(
                f"{len(users)} unit(s) repointed at the renamed entr"
                f"{'y' if len(plan.entry_renames) == 1 else 'ies'}: "
                f"{', '.join(users[:4])}{'…' if len(users) > 4 else ''}")
        else:
            plan.edu_text = ""              # nothing referenced it — leave the EDU alone
        mounted = sorted({n for n, m in (mod.mounts or {}).items()
                          if m in plan.entry_renames})
        if mounted:
            plan.warnings.append(
                f"mount(s) {', '.join(mounted)} name the renamed entry in "
                "descr_mount.txt — that file is not rewritten, fix it by hand.")
    if not (plan.edu_text or plan.modeldb_touched or plan.copies or plan.deletes):
        plan.changes.append("no changes")
    return plan


def me_dest_dir(me: ModelEdit, idx: int) -> str:
    """Fallback destination folder for a file dropped onto an existing slot:
    the folder the slot's current path lives in."""
    cur = me.paths.get(idx, "")
    return cur.rsplit("/", 1)[0] if "/" in cur else "unit_models"


def _plan_file_copy(plan: EditPlan, mod: Mod, src: Path, dest_dir: str) -> Optional[str]:
    """Queue a copy of ``src`` into ``data/<dest_dir>/`` and return its rel path."""
    rel_dir = _rel_under_data(mod, dest_dir)
    if rel_dir is None:
        plan.errors.append(f"destination '{dest_dir}' is outside the mod's data folder")
        return None
    if not src or not str(src).strip():
        plan.errors.append("no source file given for a copy")
        return None
    if not src.is_file():
        plan.errors.append(f"source file not found: {src}")
        return None
    rel = f"{rel_dir}/{src.name}" if rel_dir else src.name
    target = mod.data / rel
    if target.exists() and target.resolve() == src.resolve():
        return rel                                   # already the file in place
    plan.copies.append((src, rel))
    plan.changes.append(f"copy {src.name} -> data/{rel}")
    if target.exists():
        plan.warnings.append(f"data/{rel} already exists and will be overwritten "
                             "(backed up first, so Undo restores it).")
    return rel


# ---------------------------------------------------------------------------
# battle-model entry edits: faction records, per-faction textures, and the
# "one folder per model" layout


# The layout the editor standardises on: meshes sit directly in the model's
# folder, every texture/normal in a `textures` sub-folder of it. Sprites are
# left where they are — they are usually shared pack files far away from the
# model, and rehoming them would break every other entry that reads them.
TEXTURE_SUBDIR = "textures"


def _dirname(rel: str) -> str:
    rel = (rel or "").replace("\\", "/")
    return rel.rsplit("/", 1)[0] if "/" in rel else ""


def _basename(rel: str) -> str:
    return (rel or "").replace("\\", "/").rsplit("/", 1)[-1]


def _real(paths) -> List[str]:
    """De-duplicated, actually-set file paths ("0" is the format's 'none')."""
    return [p for p in dict.fromkeys(paths) if p and p != "0"]


def folder_info_of(slots: List[dict], name: str = "") -> dict:
    """Where a set of path slots' mesh/texture files live, and whether that is
    one folder.

    ``base`` is non-empty only when they already follow the standard layout —
    every mesh in one folder, every texture in that folder or its ``textures/``
    sub-folder. Otherwise the files are scattered and the editor offers to
    standardise them.
    """
    meshes = _real(s["value"] for s in slots if s["kind"] == "mesh")
    textures = _real(s["value"] for s in slots if s["kind"] in ("texture", "normal"))
    mesh_dirs = sorted({_dirname(p) for p in meshes})
    tex_dirs = sorted({_dirname(p) for p in textures})

    base = ""
    if len(mesh_dirs) == 1 and mesh_dirs[0]:
        m = mesh_dirs[0]
        if all(d == m or d == f"{m}/{TEXTURE_SUBDIR}" for d in tex_dirs):
            base = m
    elif not meshes and len(tex_dirs) == 1 and tex_dirs[0].endswith("/" + TEXTURE_SUBDIR):
        base = tex_dirs[0][: -len("/" + TEXTURE_SUBDIR)]

    suggestion = base or next((d for d in mesh_dirs if d),
                              next((d for d in tex_dirs if d), "unit_models/" + name))
    if not base and suggestion.endswith("/" + TEXTURE_SUBDIR):
        suggestion = suggestion[: -len("/" + TEXTURE_SUBDIR)]
    return {"base": base, "standardized": bool(base), "suggestion": suggestion,
            "mesh_dirs": mesh_dirs, "texture_dirs": tex_dirs,
            "mesh_files": meshes, "texture_files": textures}


def folder_info(entry: "modeldb.ModelEntry") -> dict:
    return folder_info_of(modeldb.path_slots(entry), entry.name)


def folder_moves_of(info: dict, target: str) -> Dict[str, str]:
    """``old rel -> new rel`` for every mesh/texture that isn't already in place."""
    target = (target or "").replace("\\", "/").strip().strip("/")
    if not target:
        return {}
    if info["standardized"] and info["base"] == target:
        return {}                      # already the layout asked for — touch nothing
    moves: Dict[str, str] = {}
    for p in info["mesh_files"]:
        new = f"{target}/{_basename(p)}"
        if new != p:
            moves[p] = new
    for p in info["texture_files"]:
        new = f"{target}/{TEXTURE_SUBDIR}/{_basename(p)}"
        if new != p:
            moves[p] = new
    return moves


def folder_moves(entry: "modeldb.ModelEntry", target: str) -> Dict[str, str]:
    return folder_moves_of(folder_info(entry), target)


def entries_using(mod: Mod, rels, skip=()) -> Dict[str, List[str]]:
    """``file rel -> other modeldb entries that reference it``."""
    wanted = set(rels)
    drop = {s.lower() for s in skip}
    out: Dict[str, List[str]] = {}
    for e in mod.modeldb.entries:
        if e.name.lower() in drop:
            continue
        for rel in wanted.intersection(set(e.mesh_files()) | set(e.texture_files())):
            out.setdefault(rel, []).append(e.name)
    return out


def model_folder_report(mod: Mod, entry_name: str, target: str = "") -> dict:
    """What moving an entry's files into ``target`` would do — the payload the
    editor's folder box needs *before* the user commits to it.
    """
    entry = mod.modeldb.by_name().get((entry_name or "").lower())
    if entry is None:
        return {"error": f"model entry '{entry_name}' not found in {mod.name}"}
    info = folder_info(entry)
    tgt = (target or "").strip() or info["suggestion"]
    rel_target = _rel_under_data(mod, tgt)
    out = dict(info, entry=entry.name, target=tgt,
               target_rel=rel_target or "", moves=[], shared=[], shared_entries=[],
               error="" if rel_target is not None else
                     f"'{tgt}' is outside the mod's data folder")
    if rel_target is None:
        return out
    moves = folder_moves(entry, rel_target)
    shared = entries_using(mod, moves.keys(), skip=[entry.name])
    out["moves"] = [{"old": o, "new": n, "missing": not (mod.data / o).is_file()}
                    for o, n in sorted(moves.items())]
    out["shared"] = [{"rel": rel, "entries": sorted(names)}
                     for rel, names in sorted(shared.items())]
    out["shared_entries"] = sorted({n for names in shared.values() for n in names})
    return out


def _plan_folder_move(plan: EditPlan, mod: Mod, entry: "modeldb.ModelEntry",
                      raw: str, me: ModelEdit) -> str:
    """Relocate the entry's mesh/texture files under ``me.move_dir`` and repoint
    the entry (and, with ``move_shared``, every other entry using those files).

    Reads the paths off ``raw`` rather than the entry as parsed from disk, and
    runs *after* the texture edits, so a file imported or repointed in the same
    save lands in the chosen folder too instead of escaping the move.
    """
    target = _rel_under_data(mod, me.move_dir)
    if target is None:
        plan.errors.append(f"'{me.move_dir}' is outside the mod's data folder")
        return raw
    slots = modeldb.path_slots_raw(raw, pad=entry.first_entry_pad)
    moves = folder_moves_of(folder_info_of(slots, entry.name), target)
    if not moves:
        return raw

    clashes = {}
    for old, new in moves.items():
        clashes.setdefault(new, []).append(old)
    for new, olds in clashes.items():
        if len(olds) > 1:
            plan.errors.append(
                f"{entry.name}: {len(olds)} different files would both become "
                f"data/{new} ({', '.join(sorted(olds))}) — rename one first")
    if plan.errors:
        return raw

    shared = entries_using(mod, moves.keys(), skip=[entry.name])
    users = sorted({n for names in shared.values() for n in names})
    if users and not me.move_shared:
        plan.warnings.append(
            f"{len(users)} other model entr{'y' if len(users) == 1 else 'ies'} "
            f"({', '.join(users[:4])}{'…' if len(users) > 4 else ''}) also use these "
            "files — they keep pointing at the old location, so the old files are "
            "copied, not moved.")

    raw = modeldb.rewrite_entry_paths(raw, moves, pad=entry.first_entry_pad)
    for old, new in sorted(moves.items()):
        src = mod.data / old
        if not src.is_file():
            plan.warnings.append(
                f"data/{old} is not on disk — '{entry.name}' now points at "
                f"data/{new}, put the file there yourself.")
            continue
        if (mod.data / new).exists() and (mod.data / new).resolve() != src.resolve():
            plan.warnings.append(f"data/{new} already exists and will be overwritten "
                                 "(backed up first, so Undo restores it).")
        plan.copies.append((src, new))
        if me.move_shared or old not in shared:
            plan.deletes.append(old)          # nothing references the old path any more
            plan.changes.append(f"move data/{old} -> data/{new}")
        else:
            plan.changes.append(f"copy data/{old} -> data/{new}")

    if me.move_shared and users:
        entries_by_name = mod.modeldb.by_name()
        for name in users:
            other = entries_by_name.get(name.lower())
            if other is None:
                continue
            base_raw = plan.entry_updates.get(other.name, other.raw)
            plan.entry_updates[other.name] = modeldb.rewrite_entry_paths(
                base_raw, moves, pad=other.first_entry_pad)
        plan.changes.append(
            f"{len(users)} other entr{'y' if len(users) == 1 else 'ies'} repointed "
            f"at data/{target}: {', '.join(users[:4])}{'…' if len(users) > 4 else ''}")
    plan.changes.append(f"{entry.name}: mesh + textures standardised under data/{target}")
    return raw


def _texture_index_map(raw: str, pad: bool, defaults: Dict[str, str],
                       faction_paths: Dict[str, Dict[str, str]]) -> Dict[int, str]:
    """Span index -> new path for the default/per-faction texture values.

    Addressed by faction + kind and resolved against the raw text *as it is now*,
    so this stays correct after faction records have been added or removed.
    """
    out: Dict[int, str] = {}
    for slot in modeldb.path_slots_raw(raw, pad=pad):
        key = TEXTURE_KINDS.get((slot["group"], slot["kind"]))
        if not key:
            continue
        value = (faction_paths.get(slot["faction"]) or {}).get(key, defaults.get(key))
        if value and value != slot["value"]:
            out[slot["i"]] = value
    return out


def _plan_model_edit(plan: EditPlan, mod: Mod, me: ModelEdit,
                     entries: Dict[str, "modeldb.ModelEntry"], taken: set) -> None:
    """Apply one entry's edits, in the only order that keeps them all meaningful.

    Indexed paths first (they were captured against the entry as it is on disk),
    then the faction records — which renumber every texture span — then the
    by-faction texture values, re-derived from the text at that point. The folder
    move comes last and re-reads every path again, so it owns the final layout
    instead of being undone by a path the browser captured before it.
    """
    entry = entries.get(me.entry)
    if entry is None:
        plan.errors.append(f"model entry '{me.entry}' not found in this mod's modeldb")
        return
    pad = entry.first_entry_pad
    raw = entry.raw

    # ---- indexed slots (LOD meshes) + any file imported onto one of them ----
    paths = dict(me.paths)
    for cp in me.copies:
        src = Path(str(cp.get("src") or ""))
        idx = int(cp.get("i", -1))
        rel = _plan_file_copy(plan, mod, src, cp.get("dest_dir") or me_dest_dir(me, idx))
        if rel:
            paths[idx] = rel
    if paths:
        raw = modeldb.rewrite_paths_indexed(raw, paths, pad=pad)
        for i, v in sorted(paths.items()):
            plan.changes.append(f"{entry.name}: path #{i} -> {v}")
    # files brought in for the default / per-faction texture boxes: copied here,
    # pointed at by the path values below
    for imp in me.imports:
        _plan_file_copy(plan, mod, Path(str(imp.get("src") or "")),
                        str(imp.get("dest_dir") or ""))

    # ---- faction (ownership) texture records ----
    if me.factions is not None:
        wanted = [f for f in dict.fromkeys(me.factions) if f]
        current = [t.faction for t in entry.main_textures]
        if not wanted:
            plan.errors.append(
                f"{entry.name}: a battle model needs at least one faction texture "
                "record — the game can't draw a unit with none.")
        elif wanted != current:
            raw = modeldb.set_texture_factions(raw, wanted, pad=pad)
            added = [f for f in wanted if f not in current]
            dropped = [f for f in current if f not in wanted]
            if added:
                plan.changes.append(
                    f"{entry.name}: faction skin(s) added: {', '.join(added)} "
                    "(cloned from an existing record)")
            if dropped:
                plan.changes.append(f"{entry.name}: faction skin(s) removed: "
                                    f"{', '.join(dropped)}")
                using = [u.type for u in mod.edu.units
                         if entry.name in u.model_names()
                         and set(u.ownership) & set(dropped)]
                if using:
                    plan.warnings.append(
                        f"{entry.name}: {', '.join(dropped[:4])} still own "
                        f"{', '.join(using[:3])}{'…' if len(using) > 3 else ''} — those "
                        "units lose their skin unless you change their ownership too.")
            if not added and not dropped:
                plan.changes.append(f"{entry.name}: faction skins reordered")

    # ---- default + per-faction texture paths ----
    if me.defaults or me.faction_paths:
        index_map = _texture_index_map(raw, pad, me.defaults, me.faction_paths)
        if index_map:
            # report the factions/kinds that really move, not everything the
            # browser sent — most of what it sends is the entry's own values
            slots = {s["i"]: s for s in modeldb.path_slots_raw(raw, pad=pad)}
            touched: Dict[str, set] = {}
            for i in index_map:
                s = slots.get(i)
                if s:
                    touched.setdefault(s["faction"], set()).add(
                        TEXTURE_KINDS[(s["group"], s["kind"])])
            raw = modeldb.rewrite_paths_indexed(raw, index_map, pad=pad)
            for fac in sorted(touched):
                plan.changes.append(
                    f"{entry.name}: {fac} {', '.join(sorted(touched[fac]))} repointed")

    # ---- one folder for the mesh + textures (last: it owns every path) ----
    if me.move_dir:
        raw = _plan_folder_move(plan, mod, entry, raw, me)

    # ---- rename (EDU refs follow, mod-wide) ----
    new_name = me.new_name.strip().lower()
    if new_name and new_name != entry.name:
        if " " in new_name:
            plan.errors.append(f"'{new_name}': model entry names cannot contain spaces")
        elif new_name in entries or new_name in taken:
            plan.errors.append(f"a model entry called '{new_name}' already exists")
        else:
            raw = modeldb.rename_entry_raw(raw, new_name)
            plan.entry_renames[entry.name] = new_name
            taken.add(new_name)
            plan.changes.append(f"model entry '{entry.name}' renamed to '{new_name}'")

    if raw != entry.raw:
        plan.entry_updates[entry.name] = raw


def _plan_new_model(plan: EditPlan, mod: Mod, nm: NewModel,
                    entries: Dict[str, "modeldb.ModelEntry"], taken: set) -> None:
    """Clone an existing entry into a new one pointing at imported files."""
    if not nm.name:
        plan.errors.append("the new model entry needs a name")
        return
    if " " in nm.name:
        plan.errors.append(f"'{nm.name}': model entry names cannot contain spaces")
        return
    if nm.name in entries or nm.name in taken:
        plan.errors.append(f"'{nm.name}': a model entry with that name already exists")
        return
    clone = entries.get(nm.clone_from)
    if clone is None:
        plan.errors.append(f"'{nm.name}': entry to clone from "
                           f"('{nm.clone_from}') not found")
        return

    slots = modeldb.path_slots(clone)
    index_map: Dict[int, str] = {}

    mesh_rel = _plan_file_copy(plan, mod, Path(nm.mesh_src), nm.dest_dir) if nm.mesh_src else None
    tex_rel = _plan_file_copy(plan, mod, Path(nm.texture_src), nm.dest_dir) if nm.texture_src else None
    norm_rel = _plan_file_copy(plan, mod, Path(nm.normal_src), nm.dest_dir) if nm.normal_src else None
    spr_rel = _plan_file_copy(plan, mod, Path(nm.sprite_src), nm.dest_dir) if nm.sprite_src else None

    if mesh_rel:
        meshes = [s for s in slots if s["kind"] == "mesh"]
        for k, s in enumerate(meshes):
            if k == 0 or nm.mesh_all_lods:
                index_map[s["i"]] = mesh_rel
    for s in slots:
        if s["group"] == "attach" and not nm.apply_to_attach:
            continue                       # attachments keep the clone's files
        if s["kind"] == "texture" and tex_rel:
            index_map[s["i"]] = tex_rel
        elif s["kind"] == "normal" and norm_rel:
            index_map[s["i"]] = norm_rel
        elif s["kind"] == "sprite" and spr_rel:
            index_map[s["i"]] = spr_rel

    raw = modeldb.rename_entry_raw(clone.raw, nm.name)
    raw = modeldb.rewrite_paths_indexed(raw, index_map, pad=clone.first_entry_pad)
    plan.new_entries.append((nm.name, raw, clone.first_entry_pad))
    taken.add(nm.name)
    facs = clone.factions()
    plan.changes.append(
        f"new model entry '{nm.name}' cloned from '{clone.name}' "
        f"({len(clone.lods)} LOD(s), {len(facs)} faction skin(s): {', '.join(facs[:6])}"
        f"{'…' if len(facs) > 6 else ''}; sprites, ownership and animations kept)")
    if not mesh_rel and not tex_rel:
        plan.warnings.append(
            f"'{nm.name}' points at exactly the same files as '{clone.name}' — "
            "give it a mesh and/or a texture to make it a different model.")
    for skel in dict.fromkeys(clone.skeletons()):
        if skel and skel not in mod.modeldb.all_skeletons():
            plan.warnings.append(f"animation '{skel}' is not in this mod's modeldb")


def _plan_delete(plan: EditPlan, unit) -> EditPlan:
    mod, opts = plan.mod, plan.request.delete_options
    kept = [u for u in mod.edu.units if u.type != unit.type]
    plan.edu_text = mod.edu.preamble + "".join(u.raw for u in kept)
    plan.changes.append(f"unit '{unit.type}' removed from export_descr_unit.txt")

    others_same_dict = [u.type for u in kept if u.dictionary == unit.dictionary]
    if opts.remove_loc:
        if others_same_dict:
            plan.warnings.append(
                f"text entry '{unit.dictionary}' kept — still used by "
                f"{', '.join(others_same_dict[:3])}")
        else:
            text = mod.export_units_path.read_text(encoding=localization.ENCODING)
            plan.loc_text = localization.remove_record(text, unit.dictionary)
            plan.changes.append(f"text entry '{unit.dictionary}' removed")

    users = _model_users(mod, skip_unit=unit.type)
    entries = mod.modeldb.by_name()
    orphans = [m.lower() for m in unit.model_names() if m.lower() not in users]
    shared = [m for m in unit.model_names() if m.lower() in users]
    if opts.remove_models:
        for name in orphans:
            entry = entries.get(name)
            if entry is None:
                continue
            if entry.first_entry_pad:
                plan.warnings.append(PAD_ENTRY_KEPT.format(name=name))
                continue
            plan.entry_deletes.append(name)
            plan.changes.append(f"model entry '{name}' removed (no other unit uses it)")
            if opts.remove_assets:
                for rel in entry.mesh_files() + entry.texture_files():
                    if (mod.data / rel).exists() and not _asset_shared(mod, rel, orphans):
                        plan.deletes.append(rel)
                        plan.changes.append(f"deleted data/{rel}")
    elif orphans:
        plan.warnings.append(
            f"{len(orphans)} model entry/entries are now unused: {', '.join(orphans[:4])}"
            f"{'…' if len(orphans) > 4 else ''}")
    if shared:
        plan.warnings.append(
            f"kept model(s) still used elsewhere: {', '.join(sorted(set(shared))[:4])}")

    if opts.remove_icons:
        for _abs, rel, _kind in _unit_icon_files(mod, unit.dictionary):
            if others_same_dict:
                break
            plan.deletes.append(rel)
            plan.changes.append(f"deleted data/{rel}")
    return plan


def _asset_shared(mod: Mod, rel: str, ignoring: List[str]) -> bool:
    """True when a mesh/texture is referenced by a modeldb entry we are keeping."""
    drop = {n.lower() for n in ignoring}
    for e in mod.modeldb.entries:
        if e.name.lower() in drop:
            continue
        if rel in e.mesh_files() or rel in e.texture_files():
            return True
    return False


def _replace_block(mod: Mod, unit, new_block: str,
                   model_map: Optional[Dict[str, str]] = None) -> str:
    """Whole EDU text with this unit's block swapped in place.

    In place, not appended: an edit must leave every other byte of the file
    (including the unit's position in it) untouched. ``model_map`` (a modeldb
    entry rename) is additionally applied to every *other* unit's block — a
    rename that only fixed the edited unit would leave every other unit of that
    model pointing at a name the modeldb no longer has.
    """
    out = [mod.edu.preamble]
    for u in mod.edu.units:
        if u.type == unit.type:
            out.append(new_block)
        elif model_map:
            out.append(edu_mod.rewrite_block(u.raw, model_map=model_map))
        else:
            out.append(u.raw)
    return "".join(out)


# ---------------------------------------------------------------------------
# apply


def _modeldb_text(plan: EditPlan) -> str:
    """Rebuild battle_models.modeldb with the plan's entry edits applied."""
    db = plan.mod.modeldb
    drop = {n.lower() for n in plan.entry_deletes}
    original = list(db.entries)
    rebuilt: List[modeldb.ModelEntry] = []
    for e in original:
        if e.name.lower() in drop:
            continue
        raw = plan.entry_updates.get(e.name)
        if raw is None:
            rebuilt.append(e)
            continue
        new_name = plan.entry_renames.get(e.name, e.name)
        rebuilt.append(modeldb.ModelEntry(
            name=new_name, scale=e.scale, lods=e.lods, main_textures=e.main_textures,
            attach_textures=e.attach_textures, animations=e.animations,
            torch_index=e.torch_index, torch=e.torch, raw=raw,
            first_entry_pad=e.first_entry_pad))
    for name, raw, pad in plan.new_entries:
        rebuilt.append(modeldb.ModelEntry(
            name=name, scale=1.0, lods=[], main_textures=[], attach_textures=[],
            animations=[], torch_index=0, torch=[], raw=raw, first_entry_pad=pad))
    try:
        db.entries = rebuilt
        return db.to_text()
    finally:
        db.entries = original          # keep the cached parse pristine


def apply_edit(plan: EditPlan) -> Dict:
    """Write the plan into the mod, with per-file backups and a log record."""
    if plan.errors:
        raise ValueError("cannot apply: " + "; ".join(plan.errors))
    mod = plan.mod
    tid = config.new_transfer_id()
    backup_root = config.backup_root_for(tid)
    manifest: Dict[str, List[str]] = {"backed_up": [], "created": []}

    def backup_and(rel: str) -> Path:
        target = mod.data / rel
        if target.exists():
            bpath = backup_root / "data" / rel
            bpath.parent.mkdir(parents=True, exist_ok=True)
            if not bpath.exists():
                shutil.copy2(target, bpath)
            manifest["backed_up"].append(rel)
        else:
            manifest["created"].append(rel)
        return target

    def write_text(rel: str, text: str, encoding: str) -> None:
        target = backup_and(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding=encoding)

    def copy_file(src: Path, rel: str) -> None:
        target = backup_and(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)

    if plan.edu_text:
        write_text("export_descr_unit.txt", plan.edu_text, edu_mod.ENCODING)
    if plan.loc_text:
        write_text("text/export_units.txt", plan.loc_text, localization.ENCODING)
    if plan.modeldb_touched:
        write_text("unit_models/battle_models.modeldb", _modeldb_text(plan),
                   modeldb.ENCODING)
    for src, rel in plan.copies + plan.icon_copies:
        copy_file(src, rel)
    for rel in plan.deletes:
        target = mod.data / rel
        if target.exists():
            backup_and(rel)                    # back up, then remove: Undo restores it
            try:
                target.unlink()
            except OSError as exc:
                plan.warnings.append(f"could not delete data/{rel}: {exc}")

    rec = {
        "id": tid,
        "when": time.strftime("%Y-%m-%d %H:%M:%S"),
        # no unit owns the plan -> it came from bmdb mode (plan_bmdb)
        "mode": "edit" if plan.unit_type else "bmdb",
        "action": "delete" if plan.request.delete else "edit",
        "source": mod.name,
        "source_root": str(mod.root),
        "dest": mod.name,
        "dest_root": str(mod.root),
        "unit_type": plan.unit_type,
        "resolved_type": plan.resolved_type,
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
    _invalidate(mod)
    return rec


def _invalidate(mod: Mod) -> None:
    for attr in ("edu", "loc", "modeldb", "mount_file", "mounts",
                 "projectile_file", "effect_sets", "engine_file",
                 "mounted_engine_file", "engine_skeleton_file"):
        mod.__dict__.pop(attr, None)


# ---------------------------------------------------------------------------
# detail payload for the editor UI


def unit_detail(mod: Mod, unit_type: str) -> dict:
    """Everything the unit editor needs for one unit."""
    unit = mod.edu.by_type().get(unit_type)
    if unit is None:
        raise KeyError(f"unit {unit_type!r} not found in {mod.name}")
    loc = mod.loc.get(unit.dictionary)
    users = _model_users(mod, skip_unit=unit_type)
    entries = mod.modeldb.by_name()

    models = []
    slots_for: Dict[str, List[str]] = {}
    if unit.soldier_model:
        slots_for.setdefault(unit.soldier_model.lower(), []).append("soldier")
    for i, o in enumerate(unit.officers, 1):
        slots_for.setdefault(o.lower(), []).append(f"officer#{i}")
    for i, a in enumerate(unit.armour_ug_models, 1):
        slots_for.setdefault(a.lower(), []).append(f"armour_ug_models#{i}")
    mount_model = mod.mount_model(unit.mount) if unit.mount else None
    if mount_model:
        slots_for.setdefault(mount_model.lower(), []).append(f"mount ({unit.mount})")

    for name in list(dict.fromkeys(list(unit.model_names())
                                   + ([mount_model] if mount_model else []))):
        e = entries.get(name.lower())
        if e is None:
            models.append({"name": name, "missing": True,
                           "slots": slots_for.get(name.lower(), [])})
            continue
        models.append(model_payload(e, slots_for.get(e.name, []),
                                    sorted(set(users.get(e.name, [])))))

    all_factions = all_mod_factions(mod)
    return {
        "mod": mod.name,
        "type": unit.type,
        "dictionary": unit.dictionary,
        "fields": edu_mod.block_fields(unit.raw),
        "loc": {"name": (loc.name if loc else "") or "",
                "descr": (loc.descr if loc else "") or "",
                "descr_short": (loc.descr_short if loc else "") or ""},
        "models": models,
        "model_names": sorted(entries.keys()),
        "icons": [{"rel": rel, "kind": kind}
                  for _abs, rel, kind in _unit_icon_files(mod, unit.dictionary)],
        "known_fields": edu_mod.CANONICAL_ORDER,
        "unit_count": len(mod.edu.units),
        # the faction checklists (EDU ownership/eras, and a model's skins) offer
        # every faction the mod knows about, not just the ones this unit has
        "all_factions": all_factions,
        "faction_names": {f: mod.faction_names.get(f.lower(), "") for f in all_factions},
        "unit_types": sorted(u.type for u in mod.edu.units),
    }


def model_payload(e: "modeldb.ModelEntry", slots=(), used_by=()) -> dict:
    """One modeldb entry as the editor's model card reads it.

    Shared by the unit editor (the entries one unit points at) and bmdb mode
    (any entry in the mod), so both render and edit an entry identically.
    """
    slot_paths = modeldb.path_slots(e)
    used = list(used_by)
    return {
        "name": e.name,
        "missing": False,
        "slots": list(slots),
        "scale": e.scale,
        "lods": [{"mesh": m, "distance": d} for m, d in e.lods],
        "paths": slot_paths,
        "factions": [t.faction for t in e.main_textures],   # file order, not sorted
        "attach_factions": [t.faction for t in e.attach_textures],
        "has_attach": bool(e.attach_textures),
        "textures": _texture_table(slot_paths),
        "texture_defaults": _texture_defaults(slot_paths),
        "folder": folder_info(e),
        "skeletons": sorted(set(s for s in e.skeletons() if s)),
        # the whole list, not a sample: it backs the "shared with" dropdown
        "used_by": used,
        "shared": bool(used),
    }


def all_mod_factions(mod: Mod) -> List[str]:
    """Every faction slot the mod knows about, for the skin checklists."""
    return sorted({f for u in mod.edu.units for f in u.ownership}
                  | {t.faction for e in mod.modeldb.entries for t in e.main_textures}
                  | set(mod.icon_factions))


def _texture_table(slots: List[dict]) -> Dict[str, Dict[str, str]]:
    """``faction -> {texture, normal, sprite, attach_texture, attach_normal}``."""
    out: Dict[str, Dict[str, str]] = {}
    for s in slots:
        key = TEXTURE_KINDS.get((s["group"], s["kind"]))
        if key:
            out.setdefault(s["faction"], {})[key] = s["value"]
    return out


def _texture_defaults(slots: List[dict]) -> Dict[str, str]:
    """The value each texture kind most factions already share.

    That is what "default textures — used by every faction unless it has its own"
    is seeded with, so opening an entry and saving it changes nothing.
    """
    buckets: Dict[str, List[str]] = {}
    for s in slots:
        key = TEXTURE_KINDS.get((s["group"], s["kind"]))
        if key and s["value"]:
            buckets.setdefault(key, []).append(s["value"])
    return {k: max(set(v), key=v.count) for k, v in buckets.items()}
