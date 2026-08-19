"""What one mod actually has on disk, per module — the Home page's readiness matrix.

The reference tool opens with an upload box: you pick a ``data`` folder and it
tells you which files it found. We already know where every mod is, so the same
question is answered the other way round — for each mod the toolkit can see, say
which of the files each module needs are there, how big they are, and whether
they can be read at all.

The point is to answer "why is this greyed out" before it is asked. A mod with no
``export_descr_sounds_units_voice.txt`` is not broken and Unit Sounds is not
broken; there is simply nothing there, and saying so on the landing page is
cheaper than letting someone find out three clicks in.

Everything here is read-only and deliberately shallow: file paths come from
:class:`unittransfer.mod.Mod` (the one place that knows them) and a file is
opened only far enough to sniff its encoding, never parsed. A mod card must not
cost what opening the mod costs.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

#: module id -> the label the burger menu shows, so both agree without importing
#: anything from the page
MODULES: Dict[str, str] = {
    "transfer": "Unit Transfer",
    "edit": "Unit Editor",
    "bmdb": "BMDB + Sprites Editor",
    "sounds": "Unit Sounds",
    "sprites": "Sprites",
    "buildings": "Buildings",
    "traits": "Traits",
    "ancillaries": "Ancillaries",
    "minor": "Minor Files",
    "strings": "Strings",
}


@dataclass(frozen=True)
class Known:
    """One file (or folder) a module reads, and how much it matters to it."""
    rel: str                       # under the mod's data/
    label: str
    modules: tuple
    required: bool = True          # False = the module works without it, but poorer
    folder: bool = False


#: Every game file the toolkit reads today. Ordered as a person would look for
#: them: the roster first, then what a unit points at, then the rest.
KNOWN: List[Known] = [
    Known("export_descr_unit.txt", "Unit roster (EDU)", ("transfer", "edit", "sprites")),
    Known("text/export_units.txt", "Unit names and descriptions",
          ("transfer", "edit"), required=False),
    Known("unit_models/battle_models.modeldb", "Battle models (BMDB)",
          ("transfer", "edit", "bmdb", "sprites")),
    Known("descr_mount.txt", "Mounts", ("transfer", "edit"), required=False),
    Known("descr_projectile.txt", "Projectiles", ("transfer",), required=False),
    Known("descr_engines.txt", "Siege engines", ("transfer",), required=False),
    Known("descr_mounted_engines.txt", "Mounted engines", ("transfer",), required=False),
    Known("descr_engine_skeleton.txt", "Engine skeletons", ("transfer",), required=False),
    Known("export_descr_sounds_units_voice.txt", "Unit voice bank", ("sounds",)),
    Known("export_descr_buildings.txt", "Buildings (EDB)", ("buildings",)),
    Known("text/export_buildings.txt", "Building names and descriptions",
          ("buildings",), required=False),
    Known("descr_sm_factions.txt", "Factions and cultures",
          ("buildings", "minor"), required=False),
    Known("text/expanded.txt", "Faction names",
          ("transfer", "edit", "buildings"), required=False),
    Known("export_descr_character_traits.txt", "Character traits (EDCT)", ("traits",)),
    Known("text/export_VnVs.txt", "Trait names and descriptions",
          ("traits",), required=False),
    Known("export_descr_ancillaries.txt", "Ancillaries (EDA)", ("ancillaries",)),
    Known("text/export_ancillaries.txt", "Ancillary names and descriptions",
          ("ancillaries",), required=False),
    Known("ui/ancillaries", "Ancillary pictures", ("ancillaries",),
          required=False, folder=True),
    # The five small campaign files behind one module. All five are required
    # because each one IS a tab: a mod without descr_cultures.txt has no
    # settlements to draw, and saying so on the card is the point of the card.
    Known("descr_rebel_factions.txt", "Rebel factions", ("minor",)),
    Known("descr_religions.txt", "Religions", ("minor",)),
    Known("descr_religions_lookup.txt", "Religion lookup", ("minor",), required=False),
    Known("descr_sm_resources.txt", "Trade resources", ("minor",)),
    Known("descr_cultures.txt", "Cultures and settlements", ("minor",)),
    Known("descr_names.txt", "Character names", ("minor",)),
    Known("text", "Localisation folder", ("strings",), folder=True),
    Known("ui/units", "Unit cards", ("transfer", "edit"), required=False, folder=True),
    Known("ui/unit_info", "Unit info cards", ("transfer", "edit"),
          required=False, folder=True),
    Known("unit_models", "Model and texture files", ("bmdb", "sprites"), folder=True),
]


def _sniff(path: Path) -> str:
    """The file's text encoding, from its first bytes. Never parses."""
    try:
        with path.open("rb") as fh:
            head = fh.read(4)
    except OSError:
        return ""
    if head[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return "utf-16"
    if head[:3] == b"\xef\xbb\xbf":
        return "utf-8-sig"
    try:
        path.open("rb").read(4096).decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return "latin-1"
    return "utf-8"


def _entry(mod, k: Known) -> Dict:
    path = mod.data / k.rel
    row = {"rel": k.rel, "label": k.label, "modules": list(k.modules),
           "required": k.required, "folder": k.folder,
           "state": "missing", "size": 0, "encoding": "", "note": ""}
    try:
        st = path.stat()
    except OSError:
        # A missing file the module can live without is not worth a red mark, and
        # a compiled .strings.bin standing in for a missing .txt is not missing at
        # all — the game reads the compiled one.
        if not k.folder and (mod.data / (k.rel + ".strings.bin")).exists():
            row["state"] = "compiled"
            row["note"] = "only the compiled .strings.bin is here — the game reads that"
        return row
    if k.folder:
        if not path.is_dir():
            row["note"] = "expected a folder, found a file"
            row["state"] = "unreadable"
            return row
        try:
            row["size"] = sum(1 for _ in path.iterdir())
        except OSError as e:
            row["state"] = "unreadable"
            row["note"] = str(e)
            return row
        row["state"] = "present" if row["size"] else "empty"
        return row
    row["size"] = st.st_size
    row["encoding"] = _sniff(path)
    if not row["encoding"]:
        row["state"] = "unreadable"
        row["note"] = "the file is there but could not be opened"
    elif st.st_size == 0:
        row["state"] = "empty"
    else:
        row["state"] = "present"
    return row


def _module_rows(files: List[Dict]) -> Dict[str, Dict]:
    """Roll the file list up into one verdict per module."""
    out: Dict[str, Dict] = {}
    for mid, label in MODULES.items():
        mine = [f for f in files if mid in f["modules"]]
        bad = [f for f in mine if f["required"] and f["state"] in ("missing", "unreadable")]
        thin = [f for f in mine
                if not f["required"] and f["state"] in ("missing", "unreadable")]
        out[mid] = {
            "id": mid, "label": label,
            "ready": not bad,
            "missing": [f["label"] for f in bad],
            "partial": [f["label"] for f in thin],
            "files": len(mine),
        }
    return out


def campaign_title(mod) -> str:
    """The mod's campaign as it is named in game, or ``''``.

    Read through the compiled ``.strings.bin`` when the ``.txt`` is absent, which
    for a released mod is the normal case — see :mod:`unittransfer.stringsbin`.
    """
    from . import stringsbin
    for name, keys in (("menu_english.txt", ("UI_NEW_GAME_IMPERIAL_CAMPAIGN",)),
                       ("campaign_descriptions.txt", ("IMPERIAL_CAMPAIGN_TITLE",))):
        txt = mod.data / "text" / name
        pairs: Dict[str, str] = {}
        if txt.exists():
            try:
                pairs = dict(stringsbin.from_txt(
                    txt.read_text(encoding=stringsbin.TXT_ENCODING)))
            except (OSError, UnicodeError):
                pairs = {}
        if not pairs:
            pairs = stringsbin.load_pairs(stringsbin.bin_path_for(txt))
        for key in keys:
            value = (pairs.get(key) or "").strip()
            if value:
                return value
    return ""


def report(mod) -> Dict:
    """The whole readiness matrix for one mod."""
    files = [_entry(mod, k) for k in KNOWN]
    title = campaign_title(mod)
    return {
        "mod": mod.name,
        "root": str(mod.root),
        "title": title,
        # localised name first, code name in brackets — the rule the whole UI uses
        "label": f"{title} ({mod.name})" if title else mod.name,
        "files": files,
        "modules": _module_rows(files),
    }


def summary(mod) -> Dict:
    """The short form a mod card shows before anything is clicked."""
    r = report(mod)
    mods = r["modules"]
    return {"mod": r["mod"], "root": r["root"], "title": r["title"],
            "label": r["label"],
            "ready": [m for m in mods if mods[m]["ready"]],
            "blocked": [m for m in mods if not mods[m]["ready"]]}
