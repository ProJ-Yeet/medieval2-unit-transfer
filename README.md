# Unit Transfer

Move units between **Medieval II: Total War** mods without hand-editing text files.

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

## Features

- **Faction-wise browser** — units grouped by owning faction, with real faction
  names, filters (category, class, era, mercenary), and search
- **Batch transfer** — select several units and transfer them in one pass, each
  with its own options
- **Use another unit as a stat base** — port a unit's identity/models but
  inherit combat stats, cost, and ownership from an existing unit in the
  destination mod
- **Per-field editor** — override any single EDU field on the way in
- **Mercenary conversion** — flip a unit to a mercenary (attribute, texture
  skin, icon folders) as part of the transfer
- **Conflict resolution** — for every asset that would collide with an existing
  file: keep, overwrite, or relocate into its own folder
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
  transfer engine, and the local HTTP server
- `web/` — the browser UI
- `tests/` — one module per area, runnable individually
