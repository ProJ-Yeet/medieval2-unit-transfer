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
say **Medieval 2 GUI Toolkit**, and so does the GitHub repo (see the
correction pass below).
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

---

## The correction pass

Everything above shipped, was used, and came back with a list. This is that
list, folded into the same release rather than held over for a point version:
nothing here is a new direction, all of it is 2.0.0 finished properly.

### The repository is now `medieval2-gui-toolkit`

The one thing 2.0.0 deliberately left alone. The old address forwards, so an
existing clone, bookmark or release link still resolves.

### Undo, in the one place it never worked

**Ctrl+Z and Ctrl+Y now work inside the Code View.** They never did: the page
takes the keystroke away from the browser whenever an editor is open, and the
snapshots it restores are of the *boxes*, which is not where you typed. So the
browser's own undo was suppressed and the toolkit's had nothing to give back.

The pane keeps its own stack now, in the same shape as the rest: a run of typing
folds into one step once it stops, and an *empty* stack hands the keystroke back
to the editor around it. Undo therefore walks back through what you typed in the
text and then out into the boxes, in the order you made the changes.

### The left-hand filters fold

Every group in every sidebar — Group by, Faction, Category, Class, Era in the
unit modes, and Culture, Settlement, Shows, Religion, Faction in Buildings — is
now a heading you can click shut. On a mod with sixty factions the first heading
was the only one you could see without scrolling. A folded group that still has
something ticked says so with a count, so a filter can never hide rows out of
sight.

### The writing

A full pass over every string the UI shows. **Roughly 300 em dashes doing a full
stop's job are gone**, and every label, heading, button, option and note now
opens on a capital. The four dashes left are number ranges, which is what an en
dash is for.

---

### Unit Editor

- **"Open file location" opens the file's folder.** It was opening Documents.
  Windows wants `explorer /select,"<path>"` as one command string; passing it as
  an argument list quotes the whole switch the moment the path contains a space,
  Explorer fails to parse it, and falls back to the default folder. Every real
  mod path has a space in it, so it failed every time.
- **A ＋ beside Variant.** The variant list is built from what the mod's own
  units already use, so a mod that has never had one offered an empty drop-down
  and a note telling you to go and hand-edit the unit file — in the tool that
  exists to replace hand-editing it. Type the first one here; it joins the list
  for every other unit.
- **Abilities merged into Weapons.** The Abilities tab held two lines while
  Weapons beside it carried nine. What a unit can do and what it does it with is
  one question; the tab is now **Weapons & abilities**, with `attributes` and
  `mount_effect` leading it.

### Clean up the unit file

- **The comment breakers are yours.** The section banner is the only line the
  cleanup authors, so its width, its rule character, what it starts with and
  whether it is capitalised are now four boxes with a live sample above the
  preview. The defaults are byte for byte what 2.0.0 wrote.
- **The ordering screen is a list, not a row of chips.** Every unit gets a row
  with the three things the sorter actually reads beside it: **tier**,
  **variant** and **classification**, each a drop-down, each written onto the
  unit's own `;@m2gt` marker where the next run reads it back.
- **The classification arrives filled in.** Generals are detected from the
  unit's own `attributes`, and that reading is what the box shows, marked
  *detected* — so agreeing with the tool costs nothing and overruling it costs
  one click. A bodyguard or a hero that carries no such attribute is not
  detectable, which is exactly why the box is editable: `bodyguard`, `hero`,
  `unique`, `quest` and `none` all lead a faction's run the way a general does.
- Dragging a unit to place it by hand still works, and still outranks all of it.
- Setting a value repaints **one row**, not the roster. Divide and Conquer's 916
  units with three drop-downs each took the best part of a second to rebuild, so
  the box you had just used was replaced under the pointer.

### Buildings

- **City and castle, side by side.** A settlement building is two lines in the
  EDB with nothing tying them together, so they drift. The new **⇄ Compare city
  / castle** button at the top right of the building editor puts the two halves
  in one table, tier by tier, and marks every unit as trained by **both** halves
  or by one. **⇄ Mirror** closes a single gap; **⇄ Mirror all** closes every gap
  in the line. Nothing is written until you Save, and a row mirrored into the
  twin appears under *Also changing* first.
  A `requires` clause that differs is not counted as a divergence — a city
  clause names the city factions and a castle clause names the castle ones —
  and neither are different pool numbers, which are usually deliberate. Both are
  still shown.
- **The three recruitment numbers have one set of names everywhere**: **Initial
  Pool**, **Replenish Rate**, **Max Pool**. They were labelled by shape
  ("start / per turn / max"), and every screen spelt it differently.
- **The recruitment row is two lines.** The unit and its numbers on top, the
  `requires` clause underneath with the full width of the panel. The clause is
  the only thing on that row with no natural width, and it was being squeezed
  into whatever the fixed columns left over.
- **The comparison table's header lines up with its columns.** The header cells
  carried none of the classes that set the column widths.
- **Editing a field updates the Code View.** Every other editor tells the pane
  when a box changes; this one never did, so cost, culture, name, a clause and a
  pool's numbers all changed the working copy while the text beside it went on
  showing the file.
- **The faction sort is a toggle, not an entry in the list it sorts.** Choosing
  "sort by unit count" closed the drop-down, so the sorted list only appeared
  when you opened it again.
- **A repaint aimed at a form that is not on screen no longer throws.** Every
  panel that takes the dialog over leaves the building form out of the document,
  and the throw came out of an onclick — so it killed that click and everything
  after it, which from the outside is the tool freezing. The stale-state paths
  around the settlement filter and the level list are closed with it.

### Unit Sounds

Every row shows the **unit's card** beside its name. A voice bank is hundreds of
rows of type names, and a type name is the one thing about a unit nobody
recognises.

---

**Known gap:** `descr_sounds_*.txt` (32 files in DaC) is not covered. It is a
grammar of its own and gets its own phase later.

**Next:** a 3D model viewer, then the Campaign Map Editor — which is now what
3.0.0 means.
