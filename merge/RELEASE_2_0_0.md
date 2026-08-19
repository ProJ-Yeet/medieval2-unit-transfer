# Medieval 2 GUI Toolkit v2.0.0 — one tool for the whole mod, not just its units

**Unit Transfer is now the Medieval 2 GUI Toolkit.** 1.9.9 moved units between
mods. This moves, edits, checks and cleans up most of what a mod is made of —
six new editors, each one with a live view of the file it is writing.

The download and the launcher have new names
(`Launch-Medieval2-GUI-Toolkit.bat`); the old launcher still works and forwards
to it. Your settings, backups and transfer log carry over untouched.

---

## The short list

If you read one thing, read this.

- **Six new modules** — Home, Strings, Traits, Ancillaries, Minor Files and
  Factions — doubling the six you already had (Unit Transfer, Unit Editor,
  BMDB + Sprites, Sounds, Sprites and Buildings), plus building trees, unit
  tiers and an EDU cleanup inside the existing ones.
- **Code View everywhere.** Every editor shows the raw game file beside the
  form. Hover a box, its line lights up. Edit either side, the other follows.
- **`.strings.bin` is read and written natively**, so no more deleting the
  compiled file and hoping the game rebuilds it.
- **Nothing gets reformatted behind your back.** Every parser round-trips both
  test mods byte for byte, comments and all.
- **A cleanup pass for `export_descr_unit.txt`** — tidy, tier, group into
  sections and reorder the whole file, repeatably, with one Undo.
- **It is much faster.** Opening a big mod's units went from 4.2 seconds to
  under half a second, and the log opens in 51 ms instead of 571.
- **The tool stopped killing its own server.** Black unit cards, "Failed to
  fetch" and the grey screen on Transfer were all one bug. It is gone.

---

## Everything in this release

### The rebrand

The app, the launcher, the window title, the README and the release naming all
say **Medieval 2 GUI Toolkit**. The GitHub repo keeps its old name.
`Launch-Unit-Transfer.bat` is kept as a forwarder, so an existing shortcut
still works. Navigation moved into a burger menu with every module in one
registry, and there is a credits screen.

### New modules

**🏠 Home.** Launching lands here instead of asking you to pick a mode. Every
detected mod gets a card with a readiness matrix — which game files it has, per
module, with the campaign's real in-game name read out of the compiled text
("War of the Ring (Divide_and_Conquer_EUR)"). Each card carries its own mod, so
this is the one screen with no mod picker above it.

**📝 Strings.** Reads and writes `.strings.bin` directly. **All 81 archives
shipped by the installed mods decode and re-encode byte for byte**, which is
what established the format — and the format is not what the reference tool
believed: the entry count is a 32-bit number, not 16-bit (Third Age's
`names.txt` is already at 20 757 entries, where the old reading silently loses
half the file), and a trailing tag index follows the entries rather than a
single zero word (DaC's `export_buildings` has 480 entries and 13 482 index
strings — writing a zero there truncates two thirds of the file).

**🎭 Traits** and **🎖 Ancillaries.** Full editors for
`export_descr_character_traits.txt` and `export_descr_ancillaries.txt`, both
halves of each file: the definitions and the triggers hundreds of lines below
them, saved as one job. **All 1457 traits, 3021 levels and 1134 ancillaries in
the installed mods parse, round-trip byte for byte, and survive a full-form save
unchanged.** A level's key and the words the player reads are edited side by
side. Deleting a trait takes its triggers with it — and says which. Ancillary
pictures are shown.

**⚡ A trigger builder**, shared by both. One typed box per token, filled from
your own mod's traits, ancillaries, factions, cultures and buildings.
**All 4974 triggers and 20 013 conditions in the six installed trigger files
parse with zero unknown constructs.** Its vocabulary is generated from the
Docudemons reference plus a measurement pass over every trigger file on the
machine — 413 conditions and 217 events — which is also what makes it able to
warn that *a condition its event cannot supply data for will never fire*. That
found two real cases in the installed mods.

**📋 Minor Files.** One tabbed module for rebel factions, religions, cultures,
resources and character names. **All 15 real files round-trip byte for byte.**
Two tabs are edit-only and say why: the engine's resource list is closed, and a
culture is eleven settlement models, a fort, a port ladder, a watchtower and six
agents — not something a text editor conjures. A religion save writes four files
or none, because a religion that reaches three of them half exists.

**🏰 Factions.** All 90 factions across the installed mods, byte-exact, with map
colours shown as swatches and edited with a colour picker. Localised names
matter more here than anywhere: mods reuse vanilla slots wholesale, so DaC's
`sicily` is the Kingdom of Gondor and Third Age's `milan` is Rohan — a list of
slots is a list of the wrong countries.

**🏗 Building trees.** Create a whole new tree: the EDB block plus three text
keys per level, in one job with one backup, because a level short of any of them
crashes the game at the construction panel. The capability picker is grouped —
60 keywords in nine groups with the engine's accepted range beside each.

### Code View

A shared two-pane widget, built once and adopted by every editor: the GUI on one
side, the file's real text on the other, hover-to-highlight both ways, live
two-way edits, parsed on the server so there is no second parser anywhere.
Fourteen file shapes are registered — twelve of them editable from either
side, and two (voice entries, and the recruit-pool view below) read-only
because they are not single records. It opens tidied — the layout lined up — and
that counts as the *tool's* change, not yours, so merely looking at a record
does not mark it unsaved.

It can also **hide a record's comment-only lines** and put every one of them
back byte for byte, anchored to the keyword of the line it sat above. That
matters more than it sounds: 7203 lines in one mod's building file carry a
comment.

### The EDU cleanup and unit tiers

Tidy `export_descr_unit.txt` as a whole file rather than one unit at a time:
group the units into sections the way a well-kept EDU is organised, prefer the
order already in the file so a unit in a sensible place does not move, and place
exceptions by hand with a per-faction ordering GUI. Running it twice changes
nothing the second time.

**Unit tiers** are the tool's own metadata — there is no game file for them —
kept in a comment above the unit as `;@m2gt tier=3 variant=aor`. Invisible to
the engine, preserved byte for byte, and labelled in the editor as tool-only so
nobody expects the game to read it.

### The unit view, and city/castle twins

The screen that lists every building line training one unit can now do the
things you go there for. Requirements are editable from the unit's side. A
**Twin** column says whether the city or castle counterpart trains that unit
**at the facing tier** — not merely somewhere — with a button that copies the
pool across. Measured: **239 rows in DaC diverge and none in Third Age Reforged
do.** The three recruitment numbers are named at last: Immediate recruitment,
Replenish rate, Max pool.

### Speed and stability

The big one: **the tool was shutting its own server down while you were using
it.** Black unit cards, `TypeError: Failed to fetch`, the grey screen when you
pressed Transfer and the dead Settings button were all the same incident. The
icon cache sat next to the app, which for many people means inside OneDrive;
137 of 400 cached icons failed to read outright and the worst took 79 seconds.
Those stalls starved the page's heartbeat, and the dead-man watchdog concluded
the browser had gone away.

| | before | after |
|---|---|---|
| icon cache | inside the synced app folder | `%LOCALAPPDATA%` |
| an unreadable cache entry | served as a blank (a black card) | re-decoded from the mod |
| proof the page is alive | the heartbeat alone | any request at all |
| `/api/units` for a 916-unit mod | 4189 ms | **350–420 ms** |
| unit-card lookup | 224 712 file globs | one listing per folder |
| opening the log | 571 ms, 1.1 MB of JSON | **51 ms, 29 KB** |
| 427 unit cards, warm | 6.0 s, 137 unreadable | 3.3 s, 0 failures |

Switching mods mid-load no longer paints the mod you just left, every module has
a real loading bar, and a composer that fails says why instead of greying out.

### The log, and undo

The log is paged and filtered by mode, with counts. It now records **what you
did** beside what the tool did — a record of effects with no causes cannot be
read back. Ctrl+Z / Ctrl+Y were never wired for five editors (Traits,
Ancillaries, Factions, Minor Files, Strings); they are now.

### Under the hood

Twelve new Python modules and a UI split out of one 10 412-line HTML file into
23 JavaScript modules — still no build step. Shared engines were extracted as
the third and fourth caller appeared rather than up front: `keyblock` for
ordered `keyword value` blocks, `flatrecord` for run-of-records files.
**54 test modules run green**, and the parsers are checked against whatever mods
are actually installed rather than a hardcoded name.

Some of what that testing caught, all of it real and all of it ours:

- A byte-order mark cost the unit and faction parsers their **first record**,
  silently — DaC really was losing a faction.
- `config.settings.json` was written non-atomically, so any request landing in
  that gap concluded the machine had no Medieval II install and every mod
  vanished for an instant.
- Mixed line endings were being normalised; now a parser reads endings the way
  its writer writes them, and the two are stated together.
- 58 "missing ancillary picture" findings across two mods were the tool's fault,
  not the mods' — it was checking a blank slot against a store of building art
  that could never hold an ancillary picture.

### Things deliberately not done

No AI or autogenerate features. Reference implementations were audited, not
copied: their strings codec, their trigger vocabulary and four of their
minor-file parsers are **not ported**, because measuring them against real files
showed they were wrong about the format — two of those serialisers write files
the engine will not load. Art that lives inside the game's `.pack` archives is
never reported as missing, because the toolkit cannot see inside them and "not
shipped here" is not the same as "missing".

---

**Known gap:** `descr_sounds_*.txt` (32 files in DaC) is not covered. It is a
grammar of its own and gets its own phase later.

**Next:** a 3D model viewer, then the Campaign Map Editor — which is now what
3.0.0 means.
