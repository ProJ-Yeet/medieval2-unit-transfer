# Unit Transfer

Move units between **Medieval II: Total War** mods — and edit them once they're
there — without hand-editing text files.

Six modes, switched from the dropdown in the top-left corner:

- **⚔ Unit Transfer** — copy a unit from one mod into another
- **✎ Unit Editor** — change, clone or delete the units of a single mod
- **🗄 BMDB Editor** — edit *any* `battle_models.modeldb` entry, and clean the
  file of everything nothing uses
- **🔊 Unit Sounds** — decide which voice-bank entry each unit speaks with
- **🖼 Sprites** — generate and wire up the far-LOD unit sprites
- **🏰 Buildings** — browse and edit `export_descr_buildings.txt`: every
  building's stats, and which units it recruits

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
- Its **voice** — a copy of another unit's `Unit_Select` entry in the
  destination's voice bank, with the EDU's `accent` / `voice_type` pinned to match
  (see [Unit Sounds mode](#unit-sounds-mode))

Name collisions are detected and resolved (reuse identical content, rename on a
real conflict, or overwrite/skip — your choice), and every step is shown in a
preview before anything is written.

### What the transfer creates

The composer's first choice is what should exist in the destination when the
transfer is done. All three are restricted to the same **unit kind** — an
infantry unit only bases on (or replaces) an infantry unit, a lancer a lancer —
because stats and animations only make sense for the type they were written for.

- **A new unit** *(default)* — its own EDU entry, name, description and icons.
- **A new unit based on an existing one** — still a new entry, but combat stats,
  attributes, cost, formation, ownership and era are inherited from a
  destination unit you pick.
- **Replace an existing unit** — no new entry at all. The destination unit you
  pick is **rewritten in place**, in the file it already lives in and at the
  position it already sits: it keeps its type, dictionary, name, description,
  stats, ownership, era and cards, and gets the transferred unit's models. Use
  it to give a unit your mod already has a better-looking model without
  disturbing anything that refers to it (recruitment, scripts, the campaign map).

  In that mode:
  - **soldier, officers, armour upgrades and mount** come from the transferred
    unit by default. Each is a **Source / Keep** row under *Edit fields* — set
    one to *Keep* and that group stays exactly as the replaced unit had it.
  - **the unit card and the info card are kept**, each with its own tick box to
    import the source's instead. An imported card is written under the *replaced*
    unit's dictionary name and into its own faction folders, so the game still
    finds it.
  - **stats are the replaced unit's**, and each one can be imported on its own by
    clicking its `B` badge in the field editor (click again to put it back).
    `type` and `dictionary` are locked — changing those would rename the unit
    rather than replace it.
  - **the voice bank and `text/export_units.txt` are not touched**, so the unit
    keeps its barks, its name and its description.
  - the replaced unit's **old battle models stay in the modeldb** (other units
    may still use them) — the BMDB Editor's cleanup finds the ones that end up
    unused.

## Unit Editor mode

Switch the top-left dropdown to **✎ Unit Editor** and the tool works on one mod
instead of two. Click any unit to open its editor:

- **Identity & text** — rename the unit's `type`, rename its `dictionary` (the
  localisation record moves with it and the unit cards are copied to the new
  name), edit the displayed name, short description and info-card text, and flip
  the unit to a mercenary. Descriptions are stored on a single line, so a newline
  or tab you type becomes `\n` / `\t` when you click away
- **Unit card / info card** — **Browse…** picks a replacement image from
  anywhere on disk. On save it is renamed to the unit's dictionary name
  (`#<dict>.tga` / `<dict>_info.tga`) and copied into **every faction that owns
  the unit**, plus the `mercs`/`merc` fallback — the game looks a card up under
  the *player's* faction folder, so one copy in one folder is the usual reason a
  card doesn't show. Ownership changed in the same save decides the folders, and
  `slave` is dropped unless it is the only owner. A `.png`/`.jpg` is re-encoded
  to `.tga`, since the engine reads nothing else. Backed up and undoable like
  any other edit
- **EDU fields** — every field of the unit's block, edited in place, in one of
  two views (see [Guided vs raw fields](#guided-vs-raw-fields)). `✕` removes
  a line outright, which is not the same as blanking its value — the game still
  reads an empty field. Missing fields can be added and land in their canonical
  EDU position. The four fields whose *order* is data get chip lists you can drag
  to reorder:
  - `ownership` and `era 0/1/2` — a checklist of every faction the mod knows,
    with **All** / **None**, and per-era **Copy ownership** / **Copy 1st
    ownership** buttons that follow whichever faction you drag to the front
  - `armour_ug_models` — position N is upgrade level N. `✎` beside a tier jumps
    to that entry in the bmdb tab, and the `✕` above a tier drops it *with* its
    `armour_ug_levels` entry (removing one without the other slides every level
    above it onto the wrong model). `＋` opens four ways to add a tier:
    1. **Repeat the last tier** — names the same entry again, so the unit gains
       the armour upgrade in its stats while its model stays exactly as it was.
       No new modeldb entry is made; vanilla and DaC both do this
    2. **Take a unit's upgrades** — find any unit in the mod with the same search
       and faction / category / class / mercs filters as the **New unit** base
       picker, see its `armour_ug_models` with the level each sits at, and tick
       the ones to import
    3. **Pick an existing entry** — type-to-search every entry in the mod's
       `battle_models.modeldb` and point a tier straight at one
    4. **New entry from a tier** — choose which of the unit's entries to base it
       on, then the new-entry form opens with its own mesh/texture to fill in

    Only mode 4 creates a modeldb entry: `armour_ug_models` is a list of entry
    *names*, so a new one is worth making only when the tier will actually look
    different. Naming an entry the list already has is allowed everywhere — it is
    a normal pattern, not a mistake — and is labelled as a repeat.

    Every mode appends to `armour_ug_levels` in step, keeping it ascending: a
    donor's own level is kept when it is still above everything here, otherwise
    the tier lands one past the highest
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

## Guided vs raw fields

An EDU line is a comma-separated tuple whose meaning is entirely positional.
This is a real one:

```
stat_pri  14, 4, no, 0, 0, melee, melee_blade, piercing, spear, 25, 1
```

Eleven separate settings, and nothing on the line says which is which. Both the
transfer composer's **Edit fields** panel and the unit editor's **EDU fields**
tab show that line in one of two views, chosen with the **🧭 Guided / ⌗ Raw
lines** switch beside the filter box. The choice is remembered between runs and
applies to both places; **Guided is the default**, and **Raw lines** is exactly
the single-text-box-per-line view earlier versions had.

The guided view groups the unit's lines into **Basics · Men & mounts ·
Abilities · Weapons · Defence & morale · Recruitment · Cards & misc**, and gives
each line a card:

- **Every value gets its own labelled box** — `Attack`, `Charge bonus`,
  `Projectile`, `Range`, `Ammo`, `Weapon type`, … — so you never count commas
- **Every number has ▴▾ beside it**, with the right step size (whole florins for
  a cost, 0.1 for a mass or a formation spacing, 0.05 for a collision radius) and
  its own limits. Hold <kbd>Shift</kbd> for ×10, hold the button to repeat, or
  use <kbd>↑</kbd>/<kbd>↓</kbd> in the box. Only *stepping* clamps: attack stops
  at the engine's cap of 63, men at 1, a ground modifier goes negative freely —
  while **typing is never clamped**, so a value a mod already has is never
  rewritten just because you looked at it
- **Hover anything for the details** — the field name explains the whole line and
  shows its exact syntax; each value box explains that one slot, what the engine
  accepts in it and what its limits are. Written from the EDU's own header
  comments and the TWC field guide
- **Drop-downs wherever the engine only takes a fixed set of words** (weapon and
  damage type, discipline, training, formation, armour hit sound). Where the set
  comes from the mod instead — projectiles, mounts, engines, ships, animals,
  battle-model entries, accents, attributes, banners — the box offers what the
  mod actually defines *and* everything its EDU already uses, but still lets you
  type anything: a mod's own attribute is never a value you can only lose
- **`?` pins the explanation open** under the field name, for when a hover
  tooltip is the wrong shape for what you're doing
- **Checkboxes and pickers for the awkward bits** — `lock_morale` is a tick, not
  a fourth CSV value; `attributes` is a chip list with the abilities and the AI
  hints separated; `mount_effect` is up to three mount + number pairs;
  `stat_pri_attr` knows that "none" is spelled `no` and that only one
  `spear_bonus_N` can apply at a time
- **Optional slots are marked as such**, including the one most editors get
  wrong: the fire effect (`musket_shot_set`) that turns `stat_pri` from eleven
  values into twelve. Set it or clear it and the line grows or shrinks correctly
- **Live checks**, shown under the field they belong to and counted at the top:
  attack above the engine's cap of 63, a missile weapon with no ammunition or a
  projectile of `no`, a secondary missile weapon (the engine only fires the
  primary), a projectile / mount / engine / model name no file in the mod
  defines, a second formation that isn't paired with `square` or `horde`, a
  `phalanx` without `long_pike`, more armour upgrade models than levels, a unit
  with more than one of `ship` / `engine` / `mounted_engine` / `animal`, an
  `animal` line without `category handler`, empty ownership
- **`</>` on any card** shows that one line as raw text, edited either way and
  kept in step both directions — so the guided boxes are a lens on the file, not
  a layer over it

Anything the guided view does not recognise — a mod's own field, a repeated
line, a value count the engine doesn't use — is shown as a raw box for that one
field and said to be. It never guesses.

Everything else the two panels do is unchanged in either view: the composer's
`B` switches (take this field from the base unit, or the transferred unit's own)
and its 🔒 locks, the editor's `✕` delete and canonical-position add, and the
faction checklists and armour-tier `＋` menu described above.

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
   `descr_character.txt`, **no mention in any of the mod's `.lua` scripts**, and
   no mention anywhere in any `data/descr_*.txt`.
   Those last two are deliberately over-cautious: an entry merely *named* in one
   of those files is held back and listed separately, because a wrong "unused"
   silently breaks a mod while a wrong "still used" costs nothing.
   The Lua pass matters most — M2TWEOP scripts create units and swap battle
   models by *name*, and nothing in the mod's `.txt` files records that, so
   without it the cleanup would delete a model the campaign needs and you would
   only find out in game. Every `.lua` under the mod is read (including
   `eopData/`), and the dialog lists exactly what was protected and which
   script line named it. A name behind a `--` comment counts too: a Lua file is
   a program you are still working on, not data the game reads
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

## Unit Sounds mode

Switch the dropdown to **🔊 Unit Sounds** to work on the mod's voice bank,
`data/export_descr_sounds_units_voice.txt` — the file that decides which `.wav`
files a unit's soldiers shout when you select them.

A unit's voice needs **two things that have to agree**:

1. a `unit <type>` entry inside one `accent` / `class` block of the voice bank, and
2. the unit's EDU `accent` and `voice_type` fields pointing at *that same block*.

Get one without the other and the unit is silent — it falls back to the generic
barks its class uses. That is why every row here writes both halves, and why a
row's accent and class snap to whatever unit you copy from instead of being
editable on their own.

Three tabs:

- **No voice entry** — units the bank has never heard of. Pick the unit to copy
  the sounds from and the row is ready; its accent and class follow that unit.
  Rows whose EDU names an accent the bank has no block for are flagged in red
  (the single most common reason a transferred unit ends up mute)
- **Has a voice entry** — move a unit to another accent/class block, re-point it
  at a different unit's sounds, or drop its entry entirely. **only ones the EDU
  disagrees with** narrows the list to entries the game never reads, because the
  EDU sends it looking somewhere else
- **Entries with no unit** — entries naming a unit that no longer exists in the
  EDU. Dead weight, and the name is taken; tick one to delete it

**Set all shown to copy** applies one donor to every visible row at once, which
is the usual job here ("these forty new units should all sound like that one").
Everything is staged in memory — the row goes green — and written in a single
**Apply voice edits**, straight into the mod, with the same backups and
**🕑 Log → Undo** as a transfer.

### Voice on a transfer

The transfer composer has the same thing as a **Voice / sound** panel with three
options:

- **Use the base unit's sound** *(default)* — the unit you already picked as the
  base also supplies the voice. Its stats and its barks come from the same place,
  which is nearly always what you want. When you are *replacing* a unit this
  reads **Keep "X"'s own voice** and writes nothing: the unit already has its
  entry, and its `accent` / `voice_type` come across with its stats
- **Use another unit's sound** — base the unit on one destination unit but take
  the voice from a different one. The accent and class dropdowns filter the list
  of units that have their own barks
- **Don't import sound** — no entry is written and the EDU's `accent` /
  `voice_type` are left exactly as the source unit had them

With either of the first two, the accent and class **lock** once a donor is
resolved (with a tooltip saying why): the copied entry lives in that donor's
block, so pointing the EDU anywhere else would leave the unit reading a block its
entry is not in. The `accent` and `voice_type` rows in the field editor lock with
it, showing what will actually be written — including when the source unit had no
`accent` line at all and one is being added.

## Sprites mode

Switch the dropdown to **🖼 Sprites** to generate the far-LOD unit sprites — the
flat billboards the game swaps in for a unit's mesh once the camera is far
enough away. A unit with no sprite either pops to an invisible blob at distance
or takes the wrong unit's silhouette.

This mode merges the two published methods (Caliban/Gigantus'
[TWC thread 663024](https://www.twcenter.net/threads/creating-a-world-unit-sprite-generating.663024/)
and the M2TWEOP console route) and replaces everything both of them leave to a
GUI, to Python 2, or to hand-editing.

**Step 1 — Generate.** Only this step differs between the two methods, because
only the game can render a sprite:

- if the mod ships **M2TWEOP**, the mode writes you a
  `M2TWEOP.generateSprite("model")` snippet to paste into the console at the
  main menu — no CFG edit, no restart between batches
- otherwise it uses the **classic** route: `sprite_script.txt` written to the
  Medieval II Total War **root** (never into the mod — that is the single most
  common reason nothing happens) and `bypass_sprite_script = 1` added under
  `[misc]` of whichever CFG actually launches the mod, creating the section if
  it isn't there. **Turn the flag back off** is one click, because leaving it on
  makes the next normal launch re-render instead of starting the game, which
  reads as a crash

Mounts need their own sprites: pick the **mount's** model, not the rider's — the
game merges the two at render time.

**Step 2 — Convert.** The game writes raw TGA, which nothing downstream reads.
The published route pops a GUI you have to browse folders in, then runs a Python
**2** script. This mode does the whole chain itself: TGA → DXT5 DDS via the
bundled `nvcompress.exe` (`tools/nvtt/`, run headless), then DDS → `.texture`
via a Python 3 port of alpaca's container format — so **no Python 2 install and
no GUI**. Mipmaps are off by default; sprites almost certainly don't need them.

The engine emits one sprite per faction in the entry's ownership list, and those
copies are usually byte-identical. **Collapse identical faction copies** keeps
one and points the rest at it instead of shipping a dozen duplicate sheets.
Results are installed into `data/unit_sprites/` and the TGA/DDS intermediates
are cleaned up.

**Step 3 — Wire into the modeldb.** Both tutorials stop at "make sure your
modeldb tallies" and leave it to you. A sprite line has to read

```
unit_sprites/<faction>_<model>_sprite.spr
```

or it points at a file that will never exist. This mode audits every sprite line
in the modeldb against what is actually on disk and splits the result three ways:

- **misnamed** — the line resolves to nothing, but the file the generator
  produced *is* there. One click repoints them
- **missing** — nothing on disk either; generate those models in step 1
- **orphans** — sprite files no modeldb line names

The write goes through the same planner as BMDB mode, so it gets the same
backups and **🕑 Log → Undo**. Casing is preserved from the modeldb (real mods
carry `england_Mount_Pony_sprite.spr`), so repointing a line that was already
correct is a no-op rather than a diff.

## Buildings mode

Switch the dropdown to **🏰 Buildings** to work on `data/export_descr_buildings.txt`
— the settlement-building database. Buildings come in *lines*: a chain of levels
that upgrade into one another (Barracks → Militia Barracks → Army Barracks…),
declared like this:

```
building barracks
{
    convert_to castle_barracks
    levels town_watch city_barracks ...
    {
        town_watch city requires factions { england, }
        {
            capability
            {
                recruit_pool "Peasant Militia"  1  0.4  3  0  requires factions { england, }
                law_bonus bonus 1
            }
            material wooden
            construction 3
            cost 800
            settlement_min village
            upgrades { city_barracks }
        }
        ...
    }
    plugins { }
}
```

The grid lists the lines as pictures. Open one and you get a tab per level with:

- **Art** — the small browser icon and the big "constructed" picture
- **Name & description** — the three `text/export_buildings.txt` keys, which a
  building must have all of or the game crashes on load; renaming writes all
  three. A building can be called something different for **every culture**
  (`{stables}`, `{stables_crags}`, `{stables_northern_european}` …), so the
  section has a culture picker and edits exactly the key you choose, leaving the
  others alone — see below
- **Stats** — cost, turns to build, material, `settlement_min`/`_max`,
  `convert_to`, whether it is a city or castle building, and its requirements.
  Every number box has **▲▼** beside it
- **Upgrade path** — the whole line drawn as a graph, and what this level
  upgrades into (see below)
- **Recruitment** — every `recruit_pool` on the level, as a row *or* a card grid
  with the unit's picture and its pool stats underneath: starting points, points
  gained per turn, the cap, starting experience, and the conditions on that pool.
  Add units, remove them, retune the numbers, and filter the list down to what
  one faction can train. **Points per turn** carries a greyed reading of what the
  number actually means — `0.066667` is *"= 15 turns"* — and its ▲▼ move it by a
  whole turn at a time rather than by a fraction (▲ from 15 turns gives
  `0.071429`, i.e. 14)
- **Other capabilities** — `law_bonus`, `armour`, `wall_level`, `agent` and the
  rest, each with a note on what it does and what its number means

The **✎ Edit** button on any recruited unit switches to the Unit Editor for that
unit; the **← Back to <building>** button in the header brings you back to the
same level with everything you had typed still in place.

### Requirements, without typing code names

Every condition in a `requires` clause names something declared elsewhere in the
mod — a faction, an event counter, a hidden resource — and a typo is invisible:
the game doesn't complain about `requires event_counter anduin_citys 1`, the
building just never becomes available. So clauses are edited as a list of terms,
each picked from the mod's own lists and shown by its real name:

| Condition | Picked from | Shown as |
| --- | --- | --- |
| `factions { … }` | `descr_sm_factions.txt` + `text/expanded.txt` | a checklist of in-game names with the code in brackets — *Mordor (england)* — with cultures listed separately and `all` called out |
| `event_counter` | `text/historic_events.txt`, `set_event_counter` in the campaign scripts, and whatever the EDB already uses | the event's written title, plus where the name came from |
| `region_religion` | `descr_religions.txt` + `descr_regions.txt` | how many regions follow it and the highest percentage any of them reaches |
| `hidden_resource` | the EDB's own `hidden_resources` line + `descr_regions.txt` | the regions that carry it, by display name |
| `resource` | `descr_sm_resources.txt` + `descr_regions.txt` | same |
| `building_present_min_level` | the EDB itself | the line, then only its own levels |

Terms are joined with `and` / `or` in order, each can be negated, and the clause
it will write is shown underneath as you build it. M2TW evaluates these strictly
left to right with no brackets, which is why there is no tree to draw. Anything
the parser doesn't recognise stays as raw text rather than being dropped — a
couple of real mods have malformed clauses and they survive a round trip
untouched.

### "…but that faction doesn't own this unit"

A `recruit_pool` naming a faction is only half the job. The unit also has to list
that faction in its EDU `ownership`, or the building trains nothing for them, and
its battle model needs a texture record for it, or their soldiers turn up
untextured. Both fail silently in game.

So ticking a faction checks both straight away and says which is missing, and
saving fixes them: the `ownership` line is extended, and missing textures are
copied from a faction that already has them. Untick **Fix unit ownership** at the
bottom of the editor to leave them alone. Cultures are expanded to their factions
before checking, and `all` to every faction.

### Upgrade paths

A line is not always a straight chain. Some branch — `A → B → D` alongside
`A → C → E` — and at least one in Divide and Conquer is a single root with every
other level hanging directly off it. So the path is laid out by depth from
whichever levels nothing upgrades into, rather than assumed to be a ladder. Every
building in it is clickable and opens that level.

Underneath, the level's own `upgrades` list is editable: remove a branch, or add
one from a drop-down that only ever offers levels *later* in the line, because an
upgrade can never point backwards.

### Names are per culture too

`text/export_buildings.txt` names a level twice over: once for everybody
(`{stables}`) and once per culture (`{stables_crags}`, `{stables_gondor}` …),
each with its own `_desc` and `_desc_short`. The game shows a faction the key for
*its* culture and falls back to the shared one.

Mods that lean on this leave the shared key as a placeholder whose value is just
the key spelled out again — Divide and Conquer does exactly that, and marks them
`DO NOT TRANSLATE`. Reading only the shared key is why a browser can show a mod's
whole EDB as code names. So a name is resolved the way the game reads it, plus
one step: the culture on show wins, then the shared key, then whichever culture
*does* have text.

The culture picker in the sidebar therefore changes the **names** in the grid as
well as the art, and the picker in the level's **Name & description** section
chooses which key an edit lands on. The note under the boxes always says the key
being written (`{stables_crags}`), whether it is new, and — when you are editing
one culture while looking at another — where the name on show is coming from.

### Building icons

Building art is per **culture**, not per faction:
`data/ui/<culture>/buildings/#<culture>_<level>.tga` is the small icon and
`#<culture>_<level>_constructed.tga` the big one. The sidebar has a culture
picker for that reason.

Mods ship only the icons they changed and let the game fall back to the vanilla
ones, so a missing file is normal rather than a fault. The lookup goes:

1. the mod's own `data/ui/<culture>/buildings`
2. vanilla art — `vanilla_ui/` next to the app, or wherever the `vanilla_ui_root`
   setting points
3. if the mod has no art for this culture but does for another, that culture's
   art, badged with whose it is — otherwise most of the grid would be blank for
   buildings the mod *has* drawn
4. a drawn placeholder

Straight out of `packs/data_*.pack` that vanilla art is ~305 MB of uncompressed
TGA, and over half of it is the same picture saved under several names (eighteen
buildings share one harbour "constructed" image). `tools/pack_vanilla_ui.py`
turns such a folder into a manifest plus one lossless WebP per *distinct*
picture — about six times smaller with no duplicate bytes at all:

```bash
python tools/pack_vanilla_ui.py unpackaded_vanilla_ui vanilla_ui
```

That packed form is what the repo carries and what the tool reads by default; a
raw unpacked `<culture>/buildings/*.tga` folder still works unchanged, so nobody
has to run the packer to use their own copy. It is left out of the release zip
(it would treble the download) — `python build_release.py --with-vanilla-ui`
puts it in.

The badge in the corner of each picture says which of those you are looking at,
and the **Missing its own art** filter lists the buildings the mod ships nothing
for at all.

### Non-destructive by construction

The EDB is the biggest hand-maintained file in a mod (Divide and Conquer's is
17 500 lines) and it is full of things a re-emitting parser destroys: trailing
`;ok old_pool=2 new_pool=2` comments on individual recruit lines, indentation
that mixes tabs and spaces line by line, comma-separated `levels` lists. So the
file is kept as its verbatim lines and every edit is a splice of a known line
range — save a level and only the lines you changed change. Capabilities are
compared by meaning rather than by text, so re-sending `1 0.135 3 0` with
different spacing is not an edit and opening a building does not rewrite it.

Same backups and **🕑 Log → Undo** as everything else.

## M2TWEOP units

M2TWEOP lifts the game's 500-unit ceiling by loading extra unit definitions from
its own folder instead of `data/export_descr_unit.txt`. Those files are plain EDU
text — the same `type` / `soldier` / `stat_pri` block a normal unit has — they
just are not in the EDU.

The tool reads them as part of the mod's roster, so **every mode works on them
unchanged**: they show up in the unit picker (badged <kbd>EOP</kbd>), can be
transferred, edited, given a voice, and their battle models count as referenced
by the BMDB cleanup. The only thing that differs is where a change is written —
an EOP unit's edit goes back to *its own file* and leaves
`export_descr_unit.txt` byte-identical. Deleting one removes its file. Undo
restores either, byte-exact, like any other change.

**Setting the folder.** ⚙ **Root settings → M2TWEOP unit folders** picks a mod and
shows what it found. Left alone, a folder called `eopData` near the top of the mod
is auto-detected; **Add folder…** pins an explicit list instead if your mod keeps
them elsewhere (remove them all to go back to auto-detection). Only `.txt` files
that really contain unit blocks are read, so scripts, JSON and notes sitting in
the same folder are ignored.

**On a transfer**, the preview gains a *Which file this unit is written to* box:

- **Same as the source** (default) — an EOP unit stays an EOP unit, a normal unit
  stays a normal unit
- **M2TWEOP unit file** — write it to its own file, keeping it out of the
  500-unit cap. The unit-limit banner offers this for the whole batch in one click
- **export_descr_unit.txt** — force it into the EDU

If the destination has no EOP folder configured, the block goes into the EDU and
the preview says so — writing into a folder the extender is not set up to read
would make the unit vanish with no error anywhere.

The 500-unit warning counts only what is in `export_descr_unit.txt`. EOP units are
listed separately and never counted, because being outside that file is the whole
point of them.

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
- **Replace an existing unit** — instead of adding a unit, write the transferred
  one's models *into* a destination unit of the same type. No new EDU entry, no
  new dictionary, no new name: the unit keeps everything players know it by and
  just looks different. Officers and armour-upgrade models come across by
  default (each can be left alone), the unit card and info card are opt-in, and
  any single stat can be imported one at a time with the `B` buttons
- **Per-field editor** — override any single EDU field on the way in, in a
  **guided** view that gives every value in a line its own labelled box, a
  drop-down of what the mod actually accepts and a live check of what the engine
  will do with it, or in the **raw** one-box-per-line view — the switch sits
  beside the filter box in both the composer and the unit editor, and is
  remembered (see [Guided vs raw fields](#guided-vs-raw-fields))
- **Mercenary conversion** — flip a unit to a mercenary (attribute, texture
  skin, icon folders) as part of the transfer
- **Conflict resolution** — for every asset that would collide with an existing
  file: keep, overwrite, or relocate into its own folder
- **Voice bank editing** — give a unit another unit's selection barks, move it
  between accent/class blocks, or clear out entries whose unit is long gone; the
  file is edited by splicing, so every line you didn't touch stays byte-exact
- **Modeldb cleanup** — find the battle-model entries nothing references and the
  files under `unit_models` nothing mentions, and move them out of the mod into
  a folder laid out like the mod itself. Anything a `.lua` script names is
  protected and never offered
- **M2TWEOP units** — units defined in the extender's own folder instead of
  `export_descr_unit.txt` are read as part of the mod's roster, badged
  <kbd>EOP</kbd> everywhere, edited in place in their own file, and left out of
  the 500-unit cap. A transfer can keep a unit as an EOP unit, or turn a normal
  one into one to get it out from under the cap
- **Unit-text cache** — the game reads `data/text/export_units.txt.strings.bin`,
  the compiled form of `export_units.txt`, and only rebuilds it when it is
  missing, so until it is deleted a transferred or renamed unit keeps showing its
  *old* name and description. Every transfer, save, voice change and cleanup
  deletes it; the next launch writes a fresh one. Switch it off in ⚙ Settings, or
  from the box at the bottom of any Apply dialog — the two are the same setting.
  (This replaced running `Full Cleaner.bat`, which also deleted mod files the game
  never rebuilds — the campaign map's water art, some battle maps — with no way to
  undo it. The script still ships in the app folder to run by hand)
- **Ctrl+Z / Ctrl+Y while editing** — takes back **one value** rather than
  closing the dialog and losing everything. It works the same way in the unit
  editor, the bmdb editor, the buildings editor, the transfer composer and
  Unit Sounds; typing into one box is one step, and undo puts the caret back
  where it was. `Ctrl+Shift+Z` also redoes. This is the in-page working copy —
  nothing has been written to disk yet, and 🕑 Log → Undo is still what reverses
  a *save*
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
builds a smaller code-only zip for a machine that already has Python, and
`--version v1.4.0` names the zip for a release instead of stamping it with the
date.

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

`tests/test_guided_fields.py` also runs the page's own JavaScript under `node`
to prove the guided field editor's split-and-rejoin is lossless across every
unit of every installed mod — the one property that, if broken, would quietly
damage a file on save. It skips that half (rather than failing) when `node`
isn't on PATH; node is not a dependency of the tool itself.

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
  `descr_engines`/`descr_engine_skeleton`,
  `export_descr_sounds_units_voice`, `export_descr_buildings`), the
  dependency-resolution and transfer
  engine, the in-mod edit engine (`edit.py`), the voice-bank engine (`sounds.py`),
  the building database (`buildings.py`),
  the M2TWEOP unit-file layer (`eop.py`), the Lua reference scanner
  (`luascan.py`), the mod-wide modeldb audit and cleanup (`bmdb.py`), the sprite
  generation/conversion pipeline (`sprites.py`), the guided field editor's
  per-mod value lists (`vocab.py`), and the local HTTP server
- `web/` — the browser UI
- `tools/nvtt/` — NVIDIA Texture Tools 2.0 (`nvcompress.exe` + its DLLs, ~1 MB),
  driven headless by Sprites mode for TGA → DXT5
- `tests/` — one module per area, runnable individually
