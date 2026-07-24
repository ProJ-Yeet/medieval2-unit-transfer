# Unit Transfer — Handoff / Project Bible

> Tool to **seamlessly transfer Medieval II: Total War units between mods**, with a
> faction-wise UI (units grouped by ownership, shown with their in-game icons + filters).
> This file is the single source of truth. Update it at the end of every work session.

## Status board

| Stage | What | State |
|-------|------|-------|
| 0 | Explore parsers, verify formats, choose stack | ✅ done (this doc) |
| 1 | Core parsers: EDU, export_units, modeldb, factions | ✅ done + validated |
| 2 | UI: faction-wise unit browser + icons + filters | ✅ done + verified |
| 3 | Transfer engine + animation (modeldb) validation | ✅ done + validated |

_Last updated: 2026-07-24 (Stage 7: siege engines; Stage 8: startup + release zip)._

| 4 | Interactive UI transfer: root picker, src/dest, options, conflicts, log+undo | ✅ done + validated |

## Stage 4 — what exists now
- `unittransfer/config.py` — persistent settings (`config/settings.json`: med2_root, last_source, last_dest) +
  transfer log (`config/transfers.json`) + per-transfer backups (`config/backups/<id>/`).
- `unittransfer/transfer.py` (rewritten) — `TransferOptions` (include_officers/mount/crew, on_conflict
  overwrite|rename|skip, new_type/new_dictionary); `plan_transfer()` (conflict detect + **bmdb dedup/rename** +
  animation check + excluded-secondary warnings); `apply_transfer()` **applies in-place with per-file backups**
  and writes a log record with an undo manifest; `undo(id)` restores backups + deletes created files.
  - bmdb rule: same name + identical content (incl. filenames) → **reuse** & report; same name + different
    content → **rename** the incoming entry (`<name>_<srctag>`) and update EDU model refs via `edu.rewrite_block`.
  - Excluded secondaries keep their EDU name and raise a warning (must already exist in dest) — per decision.
- `unittransfer/edu.py` — `rewrite_block()` (rewrite type/dictionary + model refs in soldier/officer/armour lines).
- `unittransfer/localization.py` — `upsert_record()` (replace-or-append a loc record in the full UTF-16 text).
- `unittransfer/modeldb.py` — `content_equals()` (dedup compare incl. filenames) + `rename_entry_raw()`.
- `unittransfer/server.py` (rewritten) — mods discovered under `med2_root/mods`; endpoints `/api/settings`
  (GET/POST), `/api/mods`, `/api/units`, `/icon`, `/api/plan`, `/api/apply`, `/api/log`, `/api/undo`.
- `web/index.html` (rewritten) — ⚙ Root picker (persisted), **From/To** mod selectors, faction-wise browser,
  unit drawer with **Transfer to <dest>** → modal with include options + conflict radios (rename fields) +
  live **Preview** (colored plan) + **Apply**, and 🕑 **Log** panel with per-transfer **Undo**.
- `transfer_cli.py` — still works for headless use (note: now applies in-place + backup, not overlay).
- `tests/test_transfer_v2.py` — **ALL PASSED**: apply+undo byte-exact restore; exclude-officers; conflict
  skip/rename/overwrite; bmdb dedup (reuse identical); bmdb rename on collision + EDU ref update.
  Full HTTP stack (plan/apply/undo) also verified live against a temp mods root (real mods untouched; undo
  restored dest DB files to exact original md5s).

### IMPORTANT behaviour change from Stage 3
Transfers now **apply directly into the destination mod** (user decision), backing up each touched file under
`config/backups/<id>/` first; **Undo** restores them. This is NOT the old overlay approach. Real-mod safety comes
from the backup+undo, not from writing elsewhere.

| 5 | Faction names, deferred conflict, batch multi-select, use-as-base + field editor | ✅ done + verified |

## Stage 5 — what exists now
- **Real faction names** (5a): `mod.faction_names` parses `data/text/expanded.txt` (slot→display name);
  `mod.faction_label('poland')` → "Dol Guldur (poland)". Shown in faction group headers, filters, and unit drawer.
  Units API returns `faction_names`.
- **Deferred conflict** (5b): the transfer composer no longer shows overwrite/rename/skip up front. Preview runs a
  plan; the conflict resolver (rename fields / overwrite / skip) is injected into the preview **only if**
  `unit_conflict` is true. Verified: absent before preview, present after when a conflict exists.
- **Batch multi-select** (5c): header **☑ Select** toggles select-mode (checkbox ticks on cards); **Transfer
  selected (N)** opens a batch composer with a scrollable strip of chips (unit thumbnail + chosen base). Each unit
  has independent config; a dropdown/strip switches which unit you're editing. "Apply all" plans every unit,
  pausing on any conflict/base error, then applies each (in-place + backup, individually undoable).
- **Use-another-unit-as-base** (5d): composer has a base picker listing **destination** units of the **same
  category** (enforced; infantry can't base on cavalry) with **thumbnails**, plus the batch strip shows each unit's
  chosen base image so you can scan which uses which. Backend: `TransferOptions.base_type`; `plan_transfer`
  validates category (→ `base_error`) and composes the EDU via `edu.apply_base_template` — identity (type/dictionary),
  models, and icons stay from the transferred unit; stats/attributes/formation/cost/**ownership/era** come from the
  base; `card_pic_dir`/`info_pic_dir` are pinned so icons still resolve after ownership changes.
- **Field editor** (5d): `TransferOptions.field_overrides` ({key:value}) applied via `edu.set_field`. UI loads a
  unit's fields from `GET /api/unit_fields`, lets you pick a field, edit the value, and stack overrides.
- New/updated APIs: `/api/units` adds `faction_names`; `/api/unit_fields?mod=&type=`; `/api/plan`+`/api/apply`
  accept `base_type` + `field_overrides` and return `base_error`.
- Verified in-browser (no console errors): faction labels render; base picker shows 120 same-category candidates
  with icons; field override added; batch strip shows 3 units with independent per-unit bases; deferred conflict
  appears only after preview. Backend base templating unit-validated (mismatch blocked, stats from base, override
  applied, apply+undo clean).

| 6 | Cavalry sub-types (kind) + sprite-sheet completeness | ✅ done + validated |

## Stage 6 — what exists now
- **Unit "kind"** — `edu.Unit.kind()` refines `category` for cavalry using the 6th CSV slot of the stat lines
  (the weapon tech class: `melee` / `missile` / `thrown` / `no`):
  - `stat_pri` slot 6 == `missile` → **Cavalry_Archer**
  - else `stat_sec` slot 6 != `no` (a real secondary weapon) → **Cavalry_Lance**
  - else → **Cavalry**
  Non-cavalry categories are returned unchanged (`infantry`, `siege`, `ship`, `handler`).
  `Unit.stat_pri` / `Unit.stat_sec` are now parsed into value lists.
- **Base matching uses kind, not category**: `transfer.plan_transfer` (`base_error`) and `/api/base_fields` both
  compare `kind()`, so a lancer can only be based on a lancer, a horse archer only on a horse archer.
- UI: category filter / group-by / card badges / drawer / composer / base picker all show and filter on `kind`.
  `/api/units` returns `kind` per unit and `categories` = the refined kind list.
  Real counts — TATR: 59 Cavalry_Lance, 25 Cavalry_Archer, 18 Cavalry; DaC: 75 / 35 / 48.
- **Sprite sheets are now copied** (`transfer._sprite_sheets`): a `.spr` is binary and names no paths — the game
  finds its sheets by convention as `<spr basename>_000.texture`, `_001.texture`, … next to the `.spr`. The modeldb
  only names the `.spr`, so those sheets used to be left behind (far-LOD sprites invisible). Every sibling
  `_NNN.texture` is added to `asset_files`; if a `.spr` has none, a warning is raised. They live in
  `unit_sprites/`, outside `unit_models/`, so reroute/mod_folder leaves them in place (already counted in the
  "left where they are" warning).
- `tests/test_kinds_and_sprites.py` — **ALL PASSED** (20): all six classification rules incl. missile-beats-secondary
  and a cavalry block with no `stat_sec` line; both real mods split cleanly with no raw `cavalry` left and no
  mis-classification; plan for 'Numenor Axemen' copies the `.spr` **and** both of its sheet textures.
  Existing suites (parsers, base_ownership, reroute, revert, mount_transfer, transfer_v2) all still pass.

| 7 | Siege engines: descr_engines + engine skeletons + baked textures | ✅ done + validated |

## Stage 7 — what exists now (siege engines)
A unit's EDU `engine` / `mounted_engine` field names a block in **descr_engines.txt** /
**descr_mounted_engines.txt** — *not* a battle model. Transferring an artillery unit needs that block, the
files it names, the textures baked into its meshes, and each model group's **descr_engine_skeleton.txt**
entry with its `animations/engine/` files.

- **`unittransfer/engines.py`** (new) — parsers for all three files.
  - `parse_file()/parse_text()` → `EngineFile` (blocks start at `type`, kept verbatim, byte-exact round-trip).
    `Engine` exposes `groups` (`engine_model_group` → skeleton / bone_map / collision / mesh LODs),
    `reference_points`, `pathfinding_data`, `attack_stats`, `skeletons()`, `file_refs()`, `mesh_refs()`,
    `projectiles()` (attack_stat slot 3), `content_key()/content_equals()`.
  - `parse_skeleton_file()` → `EngineSkeletonFile`; `EngineSkeleton.anim_files()` returns the `.CAS` **and**
    `-evt:` paths (data-relative; engine anims are loose under `animations/engine/`, not in a unit anim pack).
  - `rewrite_engine_raw()` (type / engine_skeleton / attack_stat projectile / file paths),
    `rewrite_engine_skeleton_raw()`, `unique_engine_name()`.
  - **`mesh_textures(path)`** — reads the texture paths straight out of a `.mesh` binary (see FORMATS §5).
- **`mod.py`** — `engine_file` / `mounted_engine_file` / `engine_skeleton_file`, `engine_defs(name)`
  (a **list** — one engine type can span several culture/variant blocks), `mounted_engine_defs`,
  `engine_skeleton_def`.
- **`transfer.py`** — `_resolve_engines()` runs *before* projectiles so the engine's own `attack_stat`
  projectiles join the same resolution. Per engine: reuse (identical block set in dest) / rename on
  collision (+ EDU `engine` field repointed) / add. Then the skeletons, then every referenced file, then
  each mesh's baked textures.
  - New options `include_engine` (default on) and **`engine_conflict`** (default `use_existing`).
  - New plan fields: `engine_actions`, `engine_renames`, `engine_raws`, `mounted_engine_raws`,
    `engine_skeleton_raws/actions/renames`, `engine_assets`, `engine_vanilla_refs`,
    `engine_dest_overrides`, `engine_projectiles`.
- **Server/UI** — `/api/units` returns `engine`, `mounted_engine`, `engine_groups`; the plan payload returns
  the engine actions/assets/vanilla-refs/overrides; the composer has a **Siege engine** checkbox + fieldset,
  the drawer shows the engine, and the preview gets a **Siege-engine files** conflict resolver plus an
  **Engine override warning** panel. Registry live-reload watches the three engine files too.
- `tests/test_engines.py` — **ALL PASSED (67)**. Plus a live HTTP run (plan/apply/undo over the real
  endpoints against a temp mods root, 16/16) and an in-browser check of the composer/preview (no console
  errors) for a normal engine, an override case and a mounted engine.

### Stage 7 decisions (locked)
- **Engine files are never relocated.** `mod_folder`/`reroute` only move things under `unit_models/`;
  a siege mesh has its texture paths *baked into the binary*, so moving it would break them. Hence a
  separate `engine_conflict` whose default is **keep the destination's** — overwriting a shared file like
  `siege_engines/textures/mangonel.texture` would re-skin the destination's OWN engines. The imported engine
  may then wear the destination's skin; the preview lists every such file so the user can flip it.
- **Vanilla references are not copied.** A file the *source* doesn't contain is stock game data. Reported,
  not copied. If the *destination* overrides that same path, its version wins and may not match the engine —
  that is the `engine_dest_overrides` warning (the "keep an eye on overrides" case).
- **Not ported** (warned instead): the block's `fire_effect` / `shot_pfx_*` / `shot_sfx` / `area_effect`
  references and the crew-animation names in `crew_animations`; `ship` (descr_ship.txt) and `animal`
  (descr_animals.txt) entries.

### Stage 7 bug fixed
`_secondary_model_names` was feeding `ship` / `engine` / `mounted_engine` / `animal` to the **modeldb**
resolver as if they were battle-model names. None of them are (verified: 0/22 resolve in TATR), so every
siege unit's plan carried a bogus `missing_models` entry. They're removed from the model pass; engines are
resolved properly and ship/animal raise an explicit warning.

### Stage 6d — live reload, tab-close shutdown, infantry archer split
- **Source files reload on change**: `server.Registry` now stamps each cached Mod with a signature
  (size+mtime of edu/export_units/modeldb/descr_mount/descr_projectile/expanded) and re-parses when it
  changes. Editing the source bmdb/EDU takes effect on the next request — no restart, no "save & scan"
  needed. `tests/test_registry_reload.py`.
- **Server shuts down when the tab closes**: the page heartbeats `POST /api/heartbeat` every 4s and
  `navigator.sendBeacon('/api/bye')` on `pagehide`/`beforeunload`. A watchdog thread stops the server 8s
  after a `bye` with no further heartbeat (survives a refresh, which resumes beating), or after 150s with
  no heartbeat at all (backstop for a crashed tab / throttled background tab). So a windowless server no
  longer lingers holding the port. Verified: `bye` → "browser tab closed — shutting down".
- **Infantry + javelin split**: `edu.Unit.kind()` now splits BOTH infantry and cavalry by stat_pri slot 6
  (weapon tech class `missile`/`thrown`/`melee`): `missile` → `*_Archer`, `thrown` → `*_Javelin`, melee
  cavalry with a real secondary → `Cavalry_Lance`, else `Cavalry`/`Infantry`. So the full kind set is
  Cavalry / Cavalry_Archer / Cavalry_Javelin / Cavalry_Lance / Infantry / Infantry_Archer / Infantry_Javelin
  (+ siege/ship/handler unchanged). The thrown check sits before the lance check, fixing thrown cavalry that
  used to mis-label as Cavalry_Lance (they all carry a melee sidearm). The base picker matches on `kind`, so
  a javelin unit only bases on a javelin unit; `/api/base_fields` rejects cross-kind. Real counts — TATR: 71
  Infantry_Archer / 45 Infantry_Javelin / 235 Infantry / 15 Cavalry_Javelin; DaC: 175 / 59 / 475 / 14.
  `tests/test_kinds_and_sprites.py` extended (42 checks).

### Stage 6c — batch dedup, projectiles, per-model selection, soldier-from-base
- **Batch model dedup (bug fix)**: a model shared by several units in a batch used to be
  re-added as `name_thir`, `name_thir_2`, … The dedup now compares in a CANONICAL path space
  (`ModelEntry.content_key_mapped` + `transfer._canon_rel`) so an identical model already in the
  destination under ANY name is reused — critical because the default `mod_folder` mode relocates
  texture/mesh paths, which had silently broken *all* content comparison. `tests/test_batch_dedup.py`.
- **Projectiles** (`unittransfer/projectiles.py`, new): parses `data/descr_projectile.txt` (block =
  `projectile <name>`; keeps raw verbatim). A missile unit's projectile is its stat_pri/stat_sec slot-3
  token (`edu.Unit.projectiles()` / `.projectile`). On transfer (only when the unit keeps its own stats —
  a base supplies stats wholesale, so no port then), each projectile is reused / renamed-on-collision /
  added into `descr_projectile.txt`, one level of `flaming <proj>` dep is followed, and the projectile's
  `.cas` model files are copied. **Effects are NOT ported**: the 7 `effect`/`end_*` lines are checked
  against the destination's effect-set registry (`mod.effect_sets`, union of `effect_set` names across
  descr_effect_impacts / arrow-trail / artillery files) and any it lacks is rewritten to
  `invisible_placeholder_set` (`projectiles.rewrite_projectile_raw`). EDU stat lines are repointed on
  rename via `edu.rewrite_stat_projectile`. Warns loudly that effects must be re-added by hand.
  `TransferOptions.include_projectile`; UI has a Projectile checkbox alongside officers/mount/crew, a
  projectile line under the unit name, and a yellow warning box. `tests/test_projectiles.py`.
- **Per-model secondary selection** (`TransferOptions.exclude_models`): officers/crew can be picked
  individually (mini checkboxes) instead of all-or-none; an excluded model keeps its EDU name and must
  exist in the dest (same rule as an unticked group). Soldier/armour models can't be excluded.
  `tests/test_individual_models.py`.
- **"Use base's soldier by default"**: persisted setting `soldier_from_base` (⚙ settings). When on, a new
  composer cfg defaults `soldier_from` to `base`, so picking a base uses the base's soldier line+projectile.
- All 11 suites pass. Verified live: projectile line/warning/checkbox + collision rename in preview,
  individual officer exclusion, projectile toggle-off, and the soldier-from-base default.

### Stage 6b — mod-folder default, dual badges, mercenary flag
- **`mod_folder` is now the default asset mode** (`TransferOptions.asset_conflict`, the server default and the UI
  cfg all changed from `use_existing`). Every copied mesh/texture lands in `unit_models/<source mod>/` with the
  bmdb paths rewritten, so a transfer cannot collide with the destination's files. The radio list is reordered
  with mod_folder first, marked "(default)".
- **Unit cards show category AND class** — two badges (`infantry` + `missile`), class badge is `.badge.cls`
  (transparent background so the category reads first).
- **"Make this a mercenary unit" checkbox** (`TransferOptions.make_mercenary`, new Mercenary fieldset in the
  composer). Verified conventions first: all 129 DaC + 2 TATR merc units use `card_pic_dir mercs` +
  `info_pic_dir merc`, and the bmdb faction token is `merc` (2187 DaC entries carry it). The flag:
  1. appends `mercenary_unit` to the EDU `attributes` line (`edu.add_attribute`, applied **last** so a manual
     `attributes` override can't drop it),
  2. adds `merc` to `plan.texture_factions` → every copied bmdb entry gets a cloned `merc` texture record,
  3. retargets the copied icons to `ui/units/mercs/` + `ui/unit_info/merc/` and pins `card_pic_dir`/`info_pic_dir`.
  It also warns that recruitment still needs a pool entry in `descr_mercenaries.txt` (this tool does not write it).
  Note `icon_dir_overrides` are now applied for any transfer, not only base-templated ones.
- `tests/test_mercenary.py` — **ALL PASSED**: EDU attribute added once with the originals kept and both pic_dirs
  pinned; every added bmdb entry gains a `merc` record with a real texture path; modeldb round-trips byte-exact;
  card written into `ui/units/mercs/`; undo clean; flag OFF changes nothing; 5 `add_attribute` unit checks
  (append, no-op, create, comment preserved). Verified live in the composer for 'Bandits'.

| 8 | Startup: preflight logs, console lifecycle, icon progress, release zip | ✅ done + validated |

## Stage 8 — startup, console, and the shareable build

### The console now behaves
`Launch-Unit-Transfer.bat` **always** opens a console (no more `pythonw` silent launch), so a failed start is
readable. `app.py` then runs in one of two modes:
- **"Show console window" OFF (default)** — the launcher runs the preflight, starts the server as a **detached
  child** (`pythonw app.py --serve`), mirrors the child's log into the console until it prints
  `STARTUP-COMPLETE`, then exits, closing the window. The server outlives it; stop it with Quit in the UI.
- **ON** — the server runs in the foreground of that console: output keeps streaming and Ctrl+C stops it.
- **Any failure holds the window** (the `.bat` pauses on a non-zero exit) with the reason on screen.

**Why a detached child instead of hiding our own window** (this was tried first and does not work): on
Windows Terminal — the default console host on Win11 — `ShowWindow(GetConsoleWindow(), SW_HIDE)` is a no-op,
because the visible window belongs to `WindowsTerminal.exe`, not to us. Verified by window enumeration:
the console stayed on screen with class `CASCADIA_HOSTING_WINDOW_CLASS`. Ending the console *process* is the
only reliable way to close the window, so the server must be a separate process.

### Startup checks (`unittransfer/startup.py`, new)
`preflight()` returns a `Check` per item — Python version, Pillow (+version), `web/index.html`,
`config/` writable, MED2 root (+ the mods it found), and the port. `report()` logs each one and fails only on
a **fatal** miss:
- fatal: old Python, no Pillow, missing `web/`, unwritable `config/`, **port held by another program**
- warning: MED2 root unset or moved (the UI can fix it), **port held by our own server** (that path just
  reopens the running window instead of starting a second one)

`python app.py --check` runs only the checks — the thing to ask someone to run when a launch misbehaves.

### Icon conversion progress
`prewarm_icons()` decodes the remembered source/dest mods' unit **cards** at startup, logging
`icons: <mod> 320/916 (35%) — 300 converted, 20 already cached` at most twice a second. A cold cache is
~420 conversions in 3.6s for TATR and ~910 in 23s for DaC; warm is ~0.3s. `IconCache.is_cached()` tells
converted from cached without paying for a decode. The **browser tab opens first** and the grid fills in
behind it — waiting for a cold DaC prewarm before showing the UI was tried and is far too slow.
Info cards stay lazy (rarer per view, larger to decode). A shutdown cuts the pass short via `should_stop`.

### Which browser?
`webbrowser.open()` — the **system default** browser, whatever Windows has registered (Brave here). The tool
never picks a specific one. Console output now says so explicitly.

### Console encoding
`logutil` sets the console to UTF-8 (`SetConsoleOutputCP(65001)` + `stream.reconfigure`), because the legacy
codepage turned every `—`, `→` and `⚙` in a log line into `?`.

### `build_release.py` (new) — the shareable zip
`python build_release.py` produces `dist/UnitTransfer-<date>.zip` (**18.2 MB**), which someone can unzip and
run with **nothing installed**: it bundles Python's official *embeddable* distribution plus Pillow, a
`Unit Transfer.bat` that uses `runtime\python.exe`, and a plain-English `README.txt`.
- The embeddable build **replaces `sys.path`** with its `python312._pth`, so that file is written outright
  with `.`, `..` (the app folder — without it `import unittransfer` fails) and `Lib\site-packages`, plus
  `import site`. This was a real bug caught by testing the zip from a clean extract.
- `smoke_test()` runs the *staged* build's own `--check` before packaging, so a broken bundle fails the build
  rather than the recipient.
- `clean_stage()` + `assert_clean()` then strip and verify: **`config/` must never ship** (it holds the
  builder's mod paths, transfer log and backups) and neither may `__pycache__`, `.log` or `.pyc`. The smoke
  test itself creates `config/server.log`, and it did leak into the first build — hence the hard guard.
- `--no-runtime` builds a code-only zip for a PC that already has Python.
- Verified from a clean extract in a temp folder: bundled Python 3.12.10 + Pillow 12.3.0, first-run preflight
  correctly warns "MED2 root not set yet", the `.bat` launches, the console closes, the server serves the UI.

**Standing instruction: rebuild this zip at the end of every work session** so there is always a current one
to hand out.

- `tests/test_startup.py` — **ALL PASSED (26)**: every preflight outcome incl. fatal-vs-warning for each
  case, prewarm cold/warm/stop behaviour, and a real detached launch (launcher exits 0, server outlives it,
  log mirrored, `STARTUP-COMPLETE` seen, second launch reuses it, Quit stops it).

### Launcher: no more silent death (superseded by Stage 8 — kept for history)
The `.bat` launches windowless by default (`show_console: false`), so a failed start used to be a window that
flashes and vanishes with no feedback — the usual cause being an instance already holding port 8756.
- `GET /api/ping` → `{"app":"unit-transfer","pid":N}` identifies a running instance.
- `app.py` on bind failure now probes the port: **ours** → opens the browser at the existing server and exits 0;
  **something else** → a Windows message box (plus `config/server.log`). Verified both paths.
- To stop a windowless instance: the UI's Quit button, or `POST http://127.0.0.1:8756/api/quit`.

## Answered questions / decisions in Stage 5
- Base pool = destination mod units, same category only. Ownership/era inherited from the base. Base copies
  combat stats/attributes/cost/formation; the unit keeps identity, models, soldier line, and icons.

## Answered questions / decisions in Stage 4
- modeldb header entry-count IS bumped on inclusion (verified: 2193→2195 for +2 models; overlay/file re-parses clean).
- Apply mode = in-place + backup (undo restores). Placeholder policy = keep original secondary-model name + warn.

## Stage 3 — what exists now (transfer engine)
- `unittransfer/transfer.py` — `plan_transfer(source, unit_type, dest)` resolves the full dependency set
  (EDU block, localisation record, model entries incl. mount's model via `descr_mount`, mesh/texture/sprite files,
  card+info icons) and diagnoses missing models / **missing skeletons** / missing files / dest collisions.
  `apply_transfer(plan, out_dir)` writes a **patch/overlay** (decision: overlay only): EDU/export_units/modeldb
  written in FULL (dest + appended entries, modeldb header count bumped), plus copied assets; shared files already
  present in dest (same size) are skipped. Never touches source or dest.
- `unittransfer/mod.py` gained `mounts` / `mount_model()` (parses `data/descr_mount.txt`).
- `transfer_cli.py` — CLI: `--from --to --unit --out [--list] [--dry-run]`.
- `tests/test_transfer.py` — **ALL PASSED**: transferred 'Numenor Axemen' TATR→DaC overlay; overlay EDU/modeldb/
  localisation re-parse cleanly, entry counts correct, models + unit + loc present, assets written/skipped,
  originals untouched. Animation warning confirmed firing (e.g. 'Rhovanion Archers' → `MTW2_Non_Shield_nostun`
  absent from DaC → warns, proceeds).

### Transfer behaviour (locked decisions)
- Output = **patch/overlay folder** (only changed files; DBs in full so `data/` is drop-in mergeable over dest).
- Missing animation skeleton = **warn but proceed**.

## How to transfer (CLI)
```
python transfer_cli.py --from "<TATR path>" --to "<DaC path>" --unit "Rhovanion Archers" --out transfers/rhov
```
`--list` shows source unit types; `--dry-run` plans without writing. Merge = copy the overlay's `data/` over dest.

## Remaining / future polish (not blocking)
- Wire a "Transfer to <mod>…" button into the web UI (calls plan/apply; show the warning + file list). Server is
  read-only today; add a POST endpoint.
- ~~Sprite completeness~~ — done in Stage 6: the `.spr` **and** its `_NNN.texture` sheets are copied. Still worth an
  in-game check that far-LOD sprites render for a transferred unit.
- `descr_mount`-based mount models and ~~engine models~~ (done in Stage 7) are resolved. Still not carried:
  `ship` (descr_ship.txt) and `animal` (descr_animals.txt) entries — both warn loudly instead.
- Engine effect/particle/sound sets and `crew_animations` names are not ported (warned). Worth doing next if
  a transferred engine turns out to need them.
- Collision handling: if dest already has the unit type or a model name with *different* content, we currently
  duplicate/warn — consider a `--rename`/`--overwrite` option.

## How to run the UI
```
cd "C:\Users\projy\OneDrive\Coding\Unit Transfer"
python app.py
```
Or double-click `Launch-Unit-Transfer.bat`. Auto-discovers mods under the remembered MED2 root (set it in the
UI's ⚙); `--port N` to move off 8756, `--check` to run only the startup checks, `--serve` to stay in the
foreground. Opens http://127.0.0.1:8756/ in the **system default** browser. Needs **Pillow**.

## How to ship it to someone
```
python build_release.py
```
Writes `dist/UnitTransfer-<date>.zip` (~18 MB) with Python + Pillow bundled — the recipient unzips it and runs
`Unit Transfer.bat`, installing nothing. `--no-runtime` for a code-only zip. **Rebuild it at the end of every
work session.** The build refuses to package `config/`, logs or caches.

## Stage 2 — what exists now
- `unittransfer/icons.py` — `IconCache`: decode `.tga`/`.dds` → PNG (Pillow), disk-cached under `.cache/icons`,
  blank-PNG fallback (never raises). Both mods' cards are `.tga`, 48×64 RGBA — decode confirmed.
- `unittransfer/server.py` — stdlib `ThreadingHTTPServer`. API: `/api/mods`, `/api/units?mod=NAME`
  (units + factions + categories + classes), `/icon?mod=&type=&kind=card|info`. `build_units_response()` is unit-tested.
- `app.py` — entry point; discovers mods, opens browser, serves.
- `web/index.html` — SPA: mod selector; group-by faction/category/class/none; filters for faction, category,
  class, era, mercenary, hide-unrendered; text search; unit cards with in-game icons; detail drawer showing
  ownership/eras/models/attributes. Verified in browser: TATR 427 units grouped by 30 factions, icons served 200/PNG.
- Icon resolution honours `card_pic_dir`/`info_pic_dir` overrides and the `mercs`/`merc` fallback (confirmed:
  a `teutonic_order` unit correctly falls back to the `mercs` card folder).

## Stage 3 plan (next) — transfer engine + animation check
1. `transfer.py`: given (source Mod, unit type, dest Mod) resolve the full dependency set:
   - EDU block (verbatim `unit.raw`), the 3 localisation lines (`loc.record_text(dict)`),
   - model entries for every `unit.model_names()` (+ mount's model via descr_mount if `mount` set — NOT yet parsed;
     add a minimal descr_mount parser or resolve mount→model lazily),
   - physical files: LOD meshes + textures/normals/sprites from each model entry, icon `.tga`s (card+info across owner factions).
2. **Safety**: never write into a real mod. Operate on a COPY of the destination (copy dest mod dir, or a chosen
   output dir) — add a `--out` dir. Every writer backs up first (already the pattern). Round-trip writers exist and are byte-exact.
3. **Append/merge** into the destination copy: append EDU block, append loc record, append model entries to modeldb
   (bump header count), copy mesh/texture/icon files (skip if already present, warn on name collision with different content).
4. **Animation warning**: for each transferred model entry, `entry.skeletons()` vs `dest.modeldb.all_skeletons()`.
   Any skeleton not present in dest → warn "ensure animation <x> exists in your mod (anim pack / descr_skeleton)".
   NOTE dest skeletons come from OTHER models referencing them; a skeleton absent from every dest model = missing.
5. First test: TATR → copy-of-DaC, a small unit (e.g. a Hobbit unit). Validate the copied mod's files re-parse
   cleanly and the unit + models are present. Then optionally wire a "Transfer to…" button into the UI.

## Known edges / TODO
- `mount`→model resolution needs descr_mount (`data/descr_mount.txt`): map mount name → model entry. Not yet parsed.
- 2 DaC units had no localisation match (914/916) — handle missing loc gracefully on transfer.
- Info cards often absent (many units only have a card, not an info card) — that's normal; don't error.
- DDS decode path is implemented but untested (both test mods use TGA). If a mod uses `.dds`, verify Pillow support.

## Decisions (locked)
- **Stack**: Python core + local web UI (`python app.py`). Icons TGA/DDS → PNG for the browser.
- **First transfer test**: Third_Age_Reforged → a COPY of Divide_and_Conquer_EUR (small unit). Never touch originals.
- **Merge strategy**: transfers APPEND verbatim source entries (EDU block / loc record / modeldb entry) to the
  destination and bump the modeldb header count. Untouched destination entries are never reformatted.

## Stage 1 — what exists now (`unittransfer/` package)
- `modeldb.py` — `parse_file()/parse_text()` → `ModelDb` (entries w/ lods, textures, animations, skeletons, torch);
  keeps each entry's verbatim `raw`; `to_text()`/`write()` round-trip **byte-exact** (validated on TATR+DaC).
- `edu.py` — `parse_file()` → `EduFile` (units w/ verbatim `raw`, plus parsed type/dictionary/ownership/era/
  models/icons/attributes). `Unit.model_names()` and `Unit.icon_factions()` for dependency + icon resolution.
  Round-trip **byte-exact**.
- `localization.py` — `parse_file()` → `Localization` (dict → name/descr/descr_short); `record_text(dict)` builds a
  transfer record. UTF-16.
- `mod.py` — `Mod(root)`: canonical paths, cached `edu`/`loc`/`modeldb`, `icon_factions`, `ownership_factions`,
  `find_unit_card(unit)` / `find_unit_info(unit)` (with merc/mercs fallback).
- `tests/test_parsers.py` — non-destructive validation (`python -m tests.test_parsers`). **ALL PASSED**:
  TATR 427 units/1026 models, DaC 916 units/2192 models; byte-exact round-trips; 100% unit→model resolution;
  60/60 sampled unit cards found.

## Stage 2 plan (next)
- `icons.py`: decode `.tga`/`.dds` → PNG bytes (need Pillow; DDS may need `Pillow` + `pillow-dds`/manual). Cache PNGs.
- `server.py` + `app.py`: local HTTP server. Endpoints: list mods, list units for a mod (grouped by ownership
  faction, with icon URLs + filter metadata: category/class/era/attributes), serve icon PNGs, unit detail.
- Web page: faction-wise grid of unit cards; filters (faction, category, class, era, mercenary, text search).
- Keep it read-only in Stage 2; transfer wiring comes in Stage 3.

## Golden rules
- **Never read the big mod data files into context** (DaC modeldb is 21 MB). Parse them programmatically only.
- **Never mutate real mod files.** All testing works on copies in a scratch/output dir. Every writer backs up first.
- Reference implementation for all formats = the C# **ModdingTool** at
  `C:\Users\projy\OneDrive\ModdingTool-master\ModdingTool-master\Model\` (Parsers/, Databases/, DataTypes/).

## Environment
- Project root: `C:\Users\projy\OneDrive\Coding\Unit Transfer`
- Test mods root: `C:\Users\projy\Downloads\Games\Total War MEDIEVAL II Definitive Edition\mods`
  - `Divide_and_Conquer_EUR` — big (EDU 1.3MB, export_units 1.8MB, modeldb 21MB, 33 ui/units factions)
  - `Third_Age_Reforged` — smaller (EDU 559KB, export_units 692KB, modeldb 1.4MB, 30 ui/units factions)
- A per-mod data root is `<mod>\data\`.

---

## FILE FORMATS (verified against ModdingTool + real DaC files)

### 1. `data/export_descr_unit.txt`  (EDU)  — note filename is singular "unit"
- Plain text, Windows line endings. `;` begins a comment (whole-line or trailing). Blank lines ignored.
- A **unit block starts at a line whose first token is `type`** and runs until the next `type` (or EOF).
- Field = first token on the line; the rest are comma-separated values (some fields are space-then-comma).
- Special multi-word field keys: `banner faction`, `banner holy`, `era 0`, `era 1`, `era 2`.
- Fields we must understand for transfer (full list in `UnitDb.AssignFields`):
  - `type` — internal display name (may contain spaces), e.g. `Mirkwood Bodyguard`.
  - `dictionary` — localization + icon key, e.g. `Mirkwood_Bodyguard`.
  - `soldier <model>, <count>, <extras>, <mass>[, <radius>][, <height>]` — **first CSV token = battle model name**.
  - `officer <model>` — 0..3 lines, each a model name.
  - `mount <mountName>` — resolves to a model via descr_mount (mount's `model` → a modeldb entry).
  - `ship`, `engine`, `mounted_engine`, `animal` — other referenced types.
  - `armour_ug_models <m0>[, <m1>...]` — upgrade models (each a modeldb entry).
  - `ownership <faction>[, <faction>...]` — which factions own the unit (may include `slave`).
  - `era 0/1/2 <faction>...` — availability per era.
  - `info_pic_dir <dir>` / `card_pic_dir <dir>` — override folder for info/card icons (often `merc`/`mercs`).
  - stats: `stat_pri`, `stat_sec`, `stat_ter`, `stat_pri_armour`, ... — copy verbatim on transfer.
- Writer: emit fields in canonical order (see `Unit.WriteEntry` / `GetTypeTextField`), preserve comments.
- **DaC uses vanilla faction slot names** in ownership (e.g. `poland` = Angmar). TATR may use real names — don't assume.

### 2. `data/text/export_units.txt`  (localization)
- **UTF-16 LE** (BOM `ff fe`). Records separated by a line `¬-----`. `¬` also starts comment lines.
- Per unit, three lines keyed by the unit's `dictionary` value:
  - `{<dict>}<Localized Name>`
  - `{<dict>_descr}<long description>`
  - `{<dict>_descr_short}<short description>`
- Parser splits on `{` `}`. `_descr_short` matched before `_descr`.

### 3. `data/unit_models/battle_models.modeldb`  (BMDB)
- Length-prefixed token stream (see `FileStream.GetString/GetInt/GetFloat`, `BattleModelDb.ParseFile`).
  A string is stored as `<length> <that many chars>`. Numbers are bare tokens.
- Header: `22 serialization::archive 3 0 0 0 0 <N+1> 0 0` where `22` is the length of `serialization::archive`.
  Parser does `SetStringPos(35)` then reads `<N+1>` as entry count; first entry is `blank` (skipped, 39 ints).
  So real model count = header number − 1. (DaC header = 2193 → 2192 models.)
- Per entry (order):
  1. `Name` (string, lowercased on read)
  2. `Scale` (float), `LodCount` (int)
  3. LODs × LodCount: `Mesh` (string), `Distance` (int)  — mesh paths under data/unit_models
  4. `MainTexturesCount` (int); each: `faction`, `texturePath`, `normal`, `sprite` (4 strings). Only kept if faction ∈ factions or `merc`.
  5. `AttachTexturesCount` (int); each: same 4 strings.
  6. `MountTypeCount` (int) == number of **Animation** blocks; each:
     `mountType` (horse/none/elephant/camel), `primarySkeleton`, `secondarySkeleton`,
     `priWeaponCount` + that many weapon strings, `secWeaponCount` + that many strings.
  7. Torch: `TorchIndex` (int) + 6 floats (bone xyz, sprite xyz).
- The **first real entry in vanilla** has extra padding ints (`firstEntry` + `FirstEntryPad` = 2 ints) sprinkled between sections. Handle both padded and unpadded. (Safest: mirror the C# state machine exactly.)
- **Animations / skeletons** = the `primarySkeleton` / `secondarySkeleton` names across the entry's Animation blocks.
  For the transfer warning: collect the set of all skeleton names referenced anywhere in the DESTINATION modeldb;
  if a transferred entry references a skeleton not in that set, warn "animation <x> not present in destination — ensure it exists in your mod (anim pack / descr_skeleton)".

### 3b. `data/unit_sprites/*.spr` (far-LOD sprites)
- Binary, **contains no path strings** (verified: zero printable runs ≥5 chars in a real `.spr`).
- The modeldb texture record's 4th string names the `.spr`; the sprite **sheets** are found by naming convention:
  `<spr basename>_000.texture`, `_001.texture`, … in the same folder. Copy them alongside the `.spr` or the unit
  renders as nothing at distance.

### 3c. Unit "kind" (derived, not a file field)
- `stat_pri` / `stat_sec` CSV slot 6 = weapon tech class: `melee` | `missile` | `thrown` | `no`.
- `category cavalry` + `stat_pri` slot6 `missile` → Cavalry_Archer; else `stat_sec` slot6 ≠ `no` → Cavalry_Lance;
  else → Cavalry. Used for grouping and for restricting which units may serve as a stat base.

### 3d. `data/descr_engines.txt` + `descr_mounted_engines.txt` (siege engines)
- Plain text, `;` comments. A block starts at a line whose first token is `type` and runs to the next one.
- **One `type` can appear in SEVERAL blocks**, differing by `culture` and `variant` (`small`/`medium`/`large`)
  — e.g. the per-culture siege towers. A lookup must return them all or the engine half-exists.
- Structure: type-level fields (`culture`, `class`, `pathfinding_data`, `reference_points`, `area_effect`,
  `attack_stat`, the physics/obstacle/health block, `crew_animations … end`), then one or more
  `engine_model_group <normal|dying|dead>` sections, each with:
  - `engine_skeleton <name>` → an entry in `descr_engine_skeleton.txt` (the `dead` group usually has none)
  - `engine_bone_map <path.xml>`, `engine_collision <path.CAS>`
  - `engine_mesh <path.mesh>, <distance|max>` — one line per LOD
- **File-naming keys** = `reference_points`, `pathfinding_data`, `engine_bone_map`, `engine_collision`,
  `engine_mesh`. Values are already `data/`-relative; `none` means no file. `engine_mesh` is `path, distance`.
- `attack_stat`'s 3rd CSV slot is a **projectile name** (same as an EDU stat line); `no` = melee.
- `descr_mounted_engines.txt` is the same format, a subset (usually just `reference_points` + crew anims).
- Verified counts: TATR 86 blocks / DaC 105; both round-trip byte-exact.

### 3e. `data/descr_engine_skeleton.txt`
- Same block shape (`type <name>`), body is `anim <key> <path.CAS> [-if:N] [-fr:N] [-evt:<path.evt>]`.
- Animation paths are written **with** the `data/` prefix (`data/animations/engine/x.CAS`) — unlike the
  engine files. Engine animations live loose in `animations/engine/`, NOT inside a unit anim pack.
- Type names are unique here (TATR 54, DaC 60). A mod's file **replaces** the vanilla one rather than
  merging, so a name absent from it falls back to the base game's definition.

### 3f. `data/siege_engines/*.mesh` — textures are inside the binary
- A siege mesh is a `serialization::archive` stream: 4-byte little-endian length + that many bytes per
  string, numbers bare. **The texture paths it uses are stored as such strings and appear in NO text file**
  — descr_engines only names the `.mesh`.
- So scanning for length-prefixed printable-ASCII strings ending in `.texture`/`.dds`/`.tga` recovers the
  exact texture set (`engines.mesh_textures`). Verified: all 43 TATR engine meshes yield 3 paths each
  (diffuse, normal/bump, overlay), e.g. `erebor_ballista_lod0.mesh` →
  `siege_engines/textures/erebor_ballista.texture`, `…/template_att_norm.texture`, `OverlayTextures/dirt_02.texture`.
- This is what removes the guesswork the manual workflow needs (converting with IWTE / opening in Blender).
- Corollary: a mesh **cannot be relocated** without rewriting the binary, so engine assets keep their paths.

### 4. UI icons
- In-game **unit card** (the icon the UI must display): `data/ui/units/<faction>/#<dictionary>.tga`.
- **Info card**: `data/ui/unit_info/<faction>/<dictionary>_info.tga`.
- Search order for `<faction>`: the unit's `ownership` factions; if `MercenaryUnit`/merc, use `mercs` (card) and `merc` (info); `card_pic_dir`/`info_pic_dir` override the folder outright.
- If not found in the mod, ModdingTool falls back to the base-game copy. For our tool, also fall back to `mercs`/`merc` (the default folder) as the user noted.
- `.tga` files (some mods use `.dds`). UI needs TGA/DDS → PNG conversion to render in a browser/canvas.

---

## Resolving a unit's full dependency set (for transfer)
Given a unit block in EDU:
1. Models = { soldier model, officer models, armour_ug_models, mount's model, ship/engine/animal if any }.
2. For each model → its BMDB entry → LOD meshes, textures (per faction), skeletons.
3. Localization = the 3 `{dict...}` lines in export_units.txt.
4. Icons = card `#<dict>.tga` + info `<dict>_info.tga` across owner factions (+ merc fallback).
5. Physical files to copy: mesh files (LOD paths), texture/normal/sprite files, icon .tga/.dds files.
6. Animation check: skeletons referenced vs skeletons present in destination BMDB.
7. Siege engine (if `engine`/`mounted_engine` is set): the descr_engines block(s) for that type, each model
   group's descr_engine_skeleton entry + its `animations/engine/` `.CAS`/`.evt` files, every
   `reference_points`/`pathfinding_data`/`engine_bone_map`/`engine_collision`/`engine_mesh` file, the
   textures read out of each mesh binary, and the projectiles its `attack_stat` lines name.

## Open decisions (fill in once chosen)
- **Tech stack**: TBD (recommendation: Python core + local web UI). Record final choice here.
- Source/destination test pair for first transfer: TBD (suggest TATR → copy-of-DaC, a small unit).
- Output/scratch dir convention for safe testing: TBD.

## Next actions (Stage 1)
- Implement read-only parsers returning plain data structures: `parse_edu`, `parse_export_units`, `parse_modeldb`, and a faction list source. Round-trip writers that preserve untouched entries + comments.
- Add a golden test: parse then re-serialize TATR's files to a temp dir and diff against originals (should be byte-stable or explainably close).
