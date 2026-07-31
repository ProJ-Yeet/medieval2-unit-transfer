# Unit Transfer

Move units between **Medieval II: Total War** mods — and edit them once they're
there — without hand-editing text files.

Three modes, switched from the dropdown in the top-left corner:

- **⚔ Unit Transfer** — copy a unit from one mod into another
- **✎ Unit Editor** — change, clone or delete the units of a single mod
- **🗄 BMDB Editor** — edit *any* `battle_models.modeldb` entry, and clean the
  file of everything nothing uses

Point it at two mods, pick a unit from one, and transfer it into the other. It
figures out and carries across everything the unit actually depends on — battle
models, mounts, projectiles, siege engines, icons, textures, sprites — resolves
name collisions, and warns you about anything it can't safely port (missing
animations, effects, vanilla file overrides). Every transfer backs up what it
touches and can be undone.

Runs as a small local web server with a UI in your browser; no game files are
ever touched except the destination mod you point it at, and even that's
protected by the backup/undo system.

## Download

Grab the latest build from **[Releases](../../releases/latest)** — unzip it and
run `Unit Transfer.bat`. Nothing else to install: Python and the image library
it needs are bundled inside.

## What it transfers

- The unit's **EDU** entry (stats, attributes, ownership, era, cost, formation)
- Its **localised name and descriptions**
- Every **battle model** it uses (soldier, officers, mount, crew) — meshes,
  textures, normal maps, and far-LOD sprite sheets
- Its **mount** definition, if mounted
- Its **projectile** definition, if it's a missile unit
- For artillery: the full **siege engine** — the `descr_engines.txt` block(s),
  each model group's animation skeleton, every referenced mesh/bone-map/
  collision/reference-points file, and the textures baked into those meshes
  (read straight out of the binary — no text file names them)
- Its **unit card and info card** icons

Name collisions are detected and resolved (reuse identical content, rename on a
real conflict, or overwrite/skip — your choice), and every step is shown in a
preview before anything is written.

## Unit Editor mode

Switch the top-left dropdown to **✎ Unit Editor** and the tool works on one mod
instead of two. Click any unit to open its editor:

- **Identity & text** — rename the unit's `type`, rename its `dictionary` (the
  localisation record moves with it and the unit cards are copied to the new
  name), edit the displayed name, short description and info-card text, and flip
  the unit to a mercenary. Descriptions are stored on a single line, so a newline
  or tab you type becomes `\n` / `\t` when you click away
- **EDU fields** — every field of the unit's block, edited in place. `✕` removes
  a line outright, which is not the same as blanking its value — the game still
  reads an empty field. Missing fields can be added and land in their canonical
  EDU position. The four fields whose *order* is data get chip lists you can drag
  to reorder:
  - `ownership` and `era 0/1/2` — a checklist of every faction the mod knows,
    with **All** / **None**, and per-era **Copy ownership** / **Copy 1st
    ownership** buttons that follow whichever faction you drag to the front
  - `armour_ug_models` — position N is upgrade level N. `✎` beside a tier jumps
    to that entry in the bmdb tab; **＋ Add armour tier** clones the tier below
    into a brand-new entry, appends it, and bumps `armour_ug_levels` with it
- **Battle models (bmdb)** — one card per `battle_models.modeldb` entry the unit
  points at:
  - **Entry name** — renaming it tells you straight away whether the name is free,
    and rewrites every unit in the EDU that referenced the old one, not just this
    one
  - **Shared with** — a dropdown of every unit using this entry; clicking a name
    opens that unit in its own browser tab
  - **Default textures and sprites** — one texture / normal map / sprite set that
    every faction inherits (attachments have no sprite, so that slot isn't shown)
  - **Factions** — a checklist of every faction, **All** / **None**, and a `✎`
    beside each to give just that faction its own textures; the rest keep the
    defaults. Ticking a faction clones an existing skin record for it
  - **Model folder** — if the meshes and textures all live under one folder it is
    shown and can be changed; if they are scattered you are told so and offered to
    standardise them (meshes in `<folder>/`, textures in `<folder>/textures/`,
    sprites left alone). Either way, any *other* entry using the same files is
    listed first, with **Edit and move anyway** to repoint those entries too
- **New model entry** — clone the entry the unit already uses, point it at a new
  mesh and texture, and say which folder under `data/` they should be copied to.
  The sprites, the per-faction (ownership) texture records and the footer —
  animations/skeletons and the torch block — are kept from the cloned entry, so
  the new model is valid; optionally the unit's `soldier`/`officer`/armour slot
  is pointed at it in the same step
- **＋ New unit** — build a new unit from an existing one, picked with the same
  faction / category / class / mercenary filters as the browser. This runs the
  same engine as a transfer, with source and destination being the same mod, so
  you get dedup (identical models and cards are reused, nothing is duplicated on
  disk) and the full field editor
- **🗑 Delete unit** — removes the EDU block and, if you ask for them, its text
  entry, its now-unused model entries, their mesh/texture files and its icons

Every save is previewed first and backed up, so **🕑 Log → Undo** reverts an edit
or a deletion byte-exact, exactly like a transfer.

## BMDB Editor mode

Switch the dropdown to **🗄 BMDB Editor** to work on the mod's whole
`battle_models.modeldb` instead of one unit's slice of it. The list is every
entry in the file — what references it, how many LODs and faction skins it has,
and a warning colour when nothing references it at all. Search filters by entry
name, folder or referring unit; **unused only** narrows it to the dead ones.

Clicking an entry opens the *same* model card the Unit Editor uses — entry name,
meshes, default and per-faction textures, the faction checklist, the model-folder
standardiser and "＋ New entry from this" — except it reaches entries no unit
points at (mounts, generals from `descr_character.txt`, leftovers). Renaming
still rewrites every unit in the EDU that named the old entry.

### 🧹 Clean up BMDB

M2TW loads the whole modeldb into memory, so entries and meshes nothing uses
cost real budget. The cleanup scans the mod and offers three lists, each with
per-row checkboxes and **Select all** / **None**:

1. **Entries nothing references** — no unit's `soldier` / `officer` /
   `armour_ug_models`, no mount in `descr_mount.txt`, no `battle_model` in
   `descr_character.txt`, and no mention anywhere in any `data/descr_*.txt`.
   That last check is deliberately over-cautious: an entry merely *named* in one
   of those files is held back and listed separately, because a wrong "unused"
   silently breaks a mod while a wrong "still used" costs nothing
2. **Soldier-only entries with an identical twin** — an entry named *only* by a
   unit's `soldier` line (never as an armour upgrade tier, an officer, a mount or
   a character model) where another entry has the **exact same footer**:
   animations, skeletons and the torch block. The soldier line can be pointed at
   the twin and the entry freed. These are suggestions, never automatic — every
   row is ticked by hand, or all at once with **Agree to all**. A unit that lists
   no `armour_ug_models` is flagged in amber, because there its soldier model is
   what you actually see on the field
3. **Files under `unit_models` no entry mentions** — every file in that tree that
   no modeldb entry names, removed or kept

Nothing is deleted. You choose a destination folder (outside the mod) and
everything ticked is **moved** there, laid out like the mod itself:

```
<destination>\
  removed_battle_models.modeldb   a loadable modeldb of just the removed entries
  README.txt                      what this is and how to put it back
  data\unit_models\…              their meshes/textures, same paths as in the mod
  unused_files\data\unit_models\… the files no entry mentioned at all
```

Because `data\` mirrors the mod, copying it back over the mod's own `data\`
restores the files, and the entries can be pasted back out of
`removed_battle_models.modeldb`. A file that an entry you *kept* still uses is
never moved. The removal itself is backed up like any other change, so
**🕑 Log → Undo** restores the mod byte-exact (the destination folder is a copy
and is left alone).

## Features

- **Faction-wise browser** — units grouped by owning faction, with real faction
  names, filters (category, class, era, mercenary), and search
- **Filters stay put** — what you tick survives editing or transferring a unit,
  and is still there the next time you open the tool
- **Batch transfer** — select several units and transfer them in one pass, each
  with its own options; leaving ☑ Select keeps the selection (**✕ Clear** empties
  it, as does finishing the transfer or changing the source mod)
- **Use another unit as a stat base** — port a unit's identity/models but
  inherit combat stats, cost, and ownership from an existing unit in the
  destination mod
- **Per-field editor** — override any single EDU field on the way in
- **Mercenary conversion** — flip a unit to a mercenary (attribute, texture
  skin, icon folders) as part of the transfer
- **Conflict resolution** — for every asset that would collide with an existing
  file: keep, overwrite, or relocate into its own folder
- **Modeldb cleanup** — find the battle-model entries nothing references and the
  files under `unit_models` nothing mentions, and move them out of the mod into
  a folder laid out like the mod itself
- **Undo** — every applied transfer is logged with a full backup; revert it
  from the log with one click
- **Live reload** — edits to the source mod's files are picked up on the next
  request, no restart needed

## Running from source

Needs Python 3.9+ and Pillow.

```bash
pip install pillow
python app.py
```

Or double-click `Launch-Unit-Transfer.bat` — it checks for Python and Pillow
first and, if Pillow is missing, installs it automatically (`pip install
pillow`) before starting. If that install fails (no internet, broken pip), run
`Install-Dependencies.bat` for a clearer standalone diagnostic, or install
Pillow yourself and try again. First run: click the gear icon and point it at
your Medieval II install folder (the one containing a `mods` folder). The
browser opens automatically.

If you don't want to deal with Python at all, grab the portable build from
[Releases](../../releases/latest) instead — it bundles its own Python and
Pillow, so there's nothing to install.

```bash
python app.py --check     # run the startup checks only, no server
python app.py --port 9000 # use a different port
```

## Building the portable release

```bash
python build_release.py
```

Produces `dist/UnitTransfer-<date>.zip`: the tool plus a bundled Python runtime
and Pillow, so it runs on a machine with nothing installed. `--no-runtime`
builds a smaller code-only zip for a machine that already has Python.

## Command-line transfer

For headless/scripted use:

```bash
python transfer_cli.py --from "<source mod path>" --to "<dest mod path>" --unit "Unit Name" --out transfers/out
```

`--list` shows the source mod's unit types; `--dry-run` plans without writing.

## Tests

```bash
python -m tests.test_parsers
python -m tests.test_transfer_v2
# ...one module per tests/test_*.py
```

Each suite is self-contained and safe to run against real mod installs — all
writes happen in temp directories or through the backup/undo path.

## Logs & troubleshooting

Every run is logged to `config/server.log` (and, if that folder isn't writable,
to `%LOCALAPPDATA%\UnitTransfer\server.log`). The portable build also tees the
launcher window to `launcher-output.txt` and ships a **Troubleshoot.bat** that
collects a diagnostic without closing on its own.

`server.log.sample` in this repo shows what a normal session looks like — startup
checks, icon conversion progress, and a unit transfer with undo.

If the launcher window opens and closes with nothing visible, the tool usually
started fine but your browser didn't open on its own — go to
`http://127.0.0.1:8756/` manually. Newer builds detect this, keep the window
open, and print the address.

## Project layout

- `unittransfer/` — parsers and writers for each file format (EDU, localisation,
  `battle_models.modeldb`, `descr_mount`, `descr_projectile`,
  `descr_engines`/`descr_engine_skeleton`), the dependency-resolution and
  transfer engine, the in-mod edit engine (`edit.py`), the mod-wide modeldb audit
  and cleanup (`bmdb.py`), and the local HTTP server
- `web/` — the browser UI
- `tests/` — one module per area, runnable individually
