# EDU + Sounds — what the reference tool has, and what we took

_Phase 13. Compared against `refs/upstream/editor/main` at the SHA in
`merge/SYNC_LOG.md`: `src/components/units/{EDUParser,UnitEditor,UnitList,
UnitStatRow,OwnershipTab,UnitDescriptionTab,UnitImagesTab,ModelDbPanel}.jsx`,
`src/pages/{UnitEditor,SoundEditor}.jsx` and `src/lib/modeldb{Codec,Store}.js`._

**Verdict: nothing adopted from their code, one idea adopted because looking for
one exposed a gap in ours, and two silent-rewrite defects of our own fixed on the
way.** Every claim below was measured against **1756 real units** — Kingdoms
vanilla (413, `Reference/UnitEditor11/vanilla/`), Divide and Conquer EUR (916)
and Third Age Reforged (427) — plus Divide and Conquer's **32**
`descr_sounds_*.txt` files and its `descr_banners_new.xml`. Where a list and the
files disagree, the count in brackets is what the files say.

This audit came out more lopsided than Phase 12's. The EDB one found four things
worth taking; here their unit vocabulary is **RTW-era or invented** in nine slots
out of eleven, and their sound editor is pointed at a different set of files
which it cannot read. So the useful half of this document is the measurement, and
the one change it produced is ours, not theirs.

---

## What we took

### 1. Banner names come from the mod's banners file, not from a hardcoded list

The only adoption, and it is an adoption of the *question* rather than of their
answer. Their `EDUParser.jsx` hardcodes `BANNER_FACTIONS` (4) and `BANNER_HOLY`
(`crusade`, `jihad`, `none`). Checking those against the files showed ours was
wrong in the same way:

| | theirs | ours (before) | what 1756 units use |
|---|---|---|---|
| `banner faction` | 4 fixed | 4 fixed | `main_infantry` (629), `main_cavalry` (381), `main_missile` (486), `main_spear` (230) |
| `banner holy` | `crusade`, `jihad`, `none` | `crusade`, `jihad` | `crusade` (1546), **`crusade_cavalry` (140)** — `jihad` and `none` appear **0** times |
| `banner unit` | not a field | harvest only | `dragon_standard`, `hospitaller`, `santiago`, `templars`, `teutonic` (vanilla, 6 lines) |

`crusade_cavalry` is used **119 times by vanilla itself**, so it is engine-era
vocabulary that both tools were simply missing; `jihad` is used by nothing and
declared by nothing.

The fix is not a longer list. **These names are declared by the mod, in
`data/descr_banners_new.xml`, in three sections that map exactly onto the three
EDU lines** — `<FactionBanners>` → `banner faction`, `<HolyBanners>` →
`banner holy`, `<UnitSpecificBanners>` → `banner unit`. That made banners the
last EDU vocabulary still hardcoded when the file that owns it was sitting on
disk, next to `descr_projectile.txt` and `descr_mount.txt`, which `vocab.py` has
always read.

So `vocab.banner_names()` reads the file, `build()` lets it lead exactly as the
projectile and mount files lead, and the three lists join `defined` — which means
the guided editor now flags a banner no file declares, the way it already flagged
a mount or a projectile. The fixed lists survive only as the fallback for a mod
with no banners file, and `BANNER_HOLY` lost `jihad` and gained `crusade_cavalry`.

Divide and Conquer declares 5 / 3 / 6; Third Age Reforged 5 / 3 / 6. **One real
finding**: Third Age Reforged's `Bomb Platforms` flies `banner faction
main_none`, which its own XML does not declare. `tests/test_guided_fields.py`
reports that as a finding about the mod and asserts only that the value is still
*offered* — the picker must never invite you to throw a mod's own value away.

### 2. Two silent rewrites of our own, found by widening the corpus

Their `serializeUnit` re-emits every unit from parsed values, which is the thing
this project refuses (below). Measuring that claim meant running our own guided
round-trip over all three EDUs, and vanilla had been missing from it — the test's
`VANILLA_EDU` path lacked its `Reference/` prefix and silently resolved to
nothing. With the corpus at 1756 units / 61 352 lines, two of our lines did not
come back byte for byte, both from Third Age Reforged, one line each:

* **`stat_mental 17, disciplined, highly_trained, locked`.** The fourth slot is a
  checkbox in the guided editor, and it re-emitted the literal `lock_morale`
  whatever the file said. `locked` is a typo that the engine ignores;
  `lock_morale` is a unit that **never routs**. Saving that unit untouched would
  have quietly changed how it behaves in battle. The fourth token now goes back
  exactly as written.
* **`formation 1.2, 1.2, 2.4, 2.4, 4, square,`.** A trailing comma is a seventh
  field, and an optional field the file left *empty* is not the same as one the
  file does not *have*. `gfParse` now records how many fields the source line
  carried, so `join` can tell the two apart.

Both fixes are in `web/js/guided.js`; the round-trip check now passes over all
1756 units.

---

## The field lists, side by side

Their parser handles 35 EDU keywords. Ours handles 43. Measured over the three
files, the keywords that actually occur are:

| keyword | vanilla | DaC | TAR | theirs | ours |
|---|---|---|---|---|---|
| `engine` | 48 | 42 | ✓ | — | ✓ |
| `mounted_engine` | 3 | 6 | ✓ | — | ✓ |
| `ship` | 20 | 8 | ✓ | — | ✓ |
| `animal` | — | — | ✓ | — | ✓ |
| `stat_ter` / `stat_ter_attr` | 5 | 14 | ✓ | — | ✓ |
| `stat_stl` | 3 | 3 | ✓ | — | ✓ |
| `recruit_priority_offset` | 0 | 912 | ✓ | — | ✓ |
| `crusading_upkeep_modifier` | — | — | — | — | ✓ |
| `unit_info` | documented in the file's own header | | | — | ✓ |
| `stat_pri_ex` / `stat_sec_ex` / `stat_armour_ex` | commented-out in vanilla | | | — | ✓ |
| `card_info_pic_dir` | **0** | **0** | **0** | ✓ | — |

`card_info_pic_dir` is the only field they have that we do not, and it is in no
real file and in no version of the EDU header. M2TW has `card_pic_dir` and
`info_pic_dir`; both tools have both. So **there is no field to adopt.**

---

## The value lists, measured

The EDU's own header comment (`Reference/UnitEditor11/vanilla/`) is the arbiter
here: it is written by the people who wrote the parser. Ours matches it in every
closed set. Theirs matches it in two.

| slot | what the files use | ours | theirs |
|---|---|---|---|
| `category` | `infantry`, `cavalry`, `siege`, `ship`, **`handler`** (TAR, 1) | **6, exactly the header's** | 4 — loses `handler` and `non_combatant` |
| `class` | `light`, `heavy`, `missile`, `spearmen`, `skirmish` (DaC, 1) | 5 | 4 |
| weapon type | `no`, `melee`, `thrown`, `missile`, `siege_missile` | **5, exact** | 2 (`melee`, `missile`) |
| tech type | `melee_simple`, `melee_blade`, `missile_mechanical`, `missile_gunpowder`, `artillery_mechanical`, `artillery_gunpowder` | **6, exact** | 8, of which **4 are used 0 times** (`melee_blade_slash`, `melee_blade_thrust`, `missile`, `siege_missile`) and **both `artillery_*` are missing** |
| stray values in the closed slots | a handful of mod typos: `no` and `piercing` in the tech slot, `no` and `spear` in the damage slot, `5` as a hit sound, `melee_blade` as a weapon type, `0` as a weapon attribute — none more than 5 uses, several on the same malformed lines | offered because they are harvested, and the guided editor warns; the two lines it cannot shape at all fall back to raw | a fixed drop-down shows nothing selected |
| damage type | `piercing`, `blunt`, `slashing`, `fire` | 4 | 4 ✓ |
| hit sound | `none`, `knife`, `mace`, `axe`, `sword`, `spear` | **6, exact** | 19, of which **13 are used 0 times** (`bow`, `crossbow`, `catapult_shot`, `trebuchet_shot`, …) |
| armour sound | `flesh`, `leather`, `metal` | **3, exact** | 4 — `plate` is used 0 times |
| discipline | `low`, `normal`, `disciplined`, `impetuous` | **4, exact** | `impetuous`, `normal`, `calm`, `steady` — `calm` and `steady` are used 0 times and `low`/`disciplined` are missing |
| training | `untrained`, `trained`, `highly_trained` | **3, exact** | 4 — adds `disciplined`, which is a *discipline* value in the wrong slot |
| formation | `square`, `horde`, `phalanx`, `schiltrom`, `shield_wall`, `wedge` (`testudo` 0) | 7, the header's | 9 — spells it **`schiltron`**, which matches nothing, and adds `column` and `line`, used 0 times |
| weapon attr | `ap`, `bp`, `spear`, `light_spear`, `long_pike`, `thrown`, `launching`, `area`, `spear_bonus_{4,6,8,10,12}` | **16, the header's whole set including the whole `spear_bonus_x` family** | not offered |
| `ownership`, `accent`, projectile, mount, engine, ship, animal, model | the mod's own files | **derived from those files, with a `defined` set behind the broken-reference warnings** | 24 hardcoded vanilla factions, 13 hardcoded accents, 10 hardcoded projectiles |

Two entries in that table are the whole argument. **`schiltron` vs `schiltrom`**
is a one-letter difference that would write a formation the engine does not know,
on purpose, from a drop-down. And the `ownership` row is Phase 10b's ruling again:
their `OwnershipTab` falls back to `OWNERSHIP_FACTIONS` — England, France, the
Papal States — for a mod whose factions are Gondor and Mordor.

### `attributes` — the one list worth counting carefully

The three files use **68 distinct** attributes between them. Ours offers 61 as a
fixed set and then merges in everything the open mod uses; theirs offers 31.

* **48 of the 68** are absent from their list, including `stakes`, `knight`,
  `command`, `cannot_skirmish`, `hide_long_grass`, `can_swim` and every AI hint.
* **11 of their 31** are used by nothing in 1756 units: `can_sap`, `drilled`,
  `ghost_unit`, `javelin`, `not_horde`, `rapid_reload`, `screeching_women`,
  `slave`, `spear`, `thrown`, `warcry`. Three of those (`can_sap`,
  `screeching_women`, `warcry`) are in the EDU header, so they are engine
  vocabulary nobody happens to use — the same case as Phase 12's eleven
  capability keywords, and ours already carries all three. The other eight are
  RTW.
* **25 of the 68 are absent from ours** and stay absent. **Nine** are the
  `area_effect_<radius>_<damage>` family (`_10_1`, `_25_2`, `_25_10`, `_50_2`,
  `_50_3`, `_100_5`, `_200_5`, plus two named `ae_holy` variants), which is a
  parameterised shape rather than a keyword. `barrowwights_unit`,
  `oathbreakers_unit`, `invasion_mercs`, `garrison_unit`, `bodyguard_unit`,
  `unique_unit`, `extreme_range`, `start_skirmishing`, `hide_everywhere`,
  `frighten_infantry`, `eagle` and `phalanx` are one mod's own or M2TWEOP's, and
  the harvest offers them whenever that mod is the one open — which is the rule,
  not an omission. Three are typos in the files themselves (`fright_mounted`,
  `very hardy` with a space, `very_hardyhardy`), and `lock_morale` appears once
  as an attribute, where it belongs on `stat_mental` and does nothing.

Nothing was adopted here, and unlike Phase 12 that is the correct outcome: a
capability keyword is a fixed engine table, and an attributes line is checked
against one — but their list is not that table, it is a smaller, older one.

---

## What we did not take, and why

### `EDUParser.jsx`'s `serializeUnit` — a re-emitting serialiser, again

The same disqualifying difference Phase 12 found in their EDB. `serializeUnit`
prints a fixed sequence of lines with fixed column padding from parsed values, so
a save loses every comment, every `stat_pri_ex` a mod has commented out, every
line the parser's `switch` has no `case` for — `engine`, `ship`, `stat_ter`,
`stat_stl`, `recruit_priority_offset` — and reorders what is left. It also
*writes* three commented-out lines of its own (`;stat_pri_ex`, `;stat_sec_ex`,
`;stat_armour_ex`) into every unit whether the unit had them or not, and falls
back to `armour_ug_models = soldier_model` when the line is absent, which is a
different unit.

Ours edits the EDU as verbatim lines with per-field overrides, and
`tests/test_guided_fields.py` asserts the split-and-rejoin over every line of
every installed EDU. That is the whole reason section 2 above exists: the
contract is strong enough that two one-line deviations in 61 352 lines showed up
as failures.

### `parseExportUnits` / `serializeExportUnits` — plain text, rebuilt from a map

Their unit names and descriptions come from a text `export_units.txt`, keyed into
an object and re-emitted in insertion order with a fixed blank-line pattern —
comments gone, order gone. Phase 6 owns this: `stringsbin.py` reads and writes
the real `.strings.bin`, byte-exact across all **81** real archives, and
`strings.py` edits a single entry in place. Their own button is labelled "Load
export_units.txt.strings.bin" while the parser behind it reads text.

### `SoundEditor.jsx` — a different set of files, and it cannot read them

Not a competitor to our voice-bank editor: theirs edits `descr_sounds_*.txt` (the
engine's sound *scripts*), ours edits `export_descr_sounds_units_voice.txt` (the
unit *voice bank*). Different files, no overlap. Two measurements settle whether
theirs is worth porting anyway:

* **Their `KNOWN_SOUND_FILES` names 14 files. Four exist.** Divide and Conquer
  ships **32** `descr_sounds_*.txt`, **28** of which their list has never heard
  of. The ten they name that do not exist (`descr_sounds_animals`, `_battles`,
  `_building_battle`, `_building_construction`, `_environment`, `_frontend`,
  `_missiles`, `_strat`, `_siege`, `_ui`) are RTW-era or invented; M2TW's are
  `_enviro`, `_engine`, `_structures`, `_stratmap`, `_interface` and so on.
* **Their parser destroys all 32.** It takes any line at column 0 with no space
  in it as a block label, which fits none of the real format —
  `DEFAULT:` / `BANK:` headers, `event … end` blocks, `folder` lines, indented
  sample names, `unit X:sec, Y:sec` selectors. Run over Divide and Conquer's 32
  files it round-trips **0 of 32** and loses **2975 lines**. In
  `descr_sounds_weapons.txt` — 3856 lines — the only "entry" it finds is the word
  `end`.

Their own empty state points the user at a third-party GitHub repo for the base
sound files, because M2TW ships these packed. That is a true and useful fact, and
the only thing here worth carrying forward.

**The coverage gap is real and is not closed by this phase.** Nothing in the
toolkit touches `descr_sounds_*.txt`. That is a file family of its own with a
real grammar, and it deserves the treatment Phase 7 gave triggers, not a raw-line
box — a phase, not a corner of this one. Recorded here, not scheduled.

### `ModelDbPanel.jsx`'s "duplicate faction texture"

The one feature in their unit screens that ours might have lacked: a popup that
copies a faction's texture paths onto another faction. We have it twice over, and
wired in rather than standalone — `modeldb.add_texture_factions` clones an
existing record for every missing faction and bumps each group's count token, and
`set_texture_factions` makes a group hold exactly the ticked factions, splicing a
kept record back **verbatim** so its own paths survive. Between them they are
reached from the unit editor's faction checklist, the transfer flow and the
building-ownership fix.

Their `OwnershipTab` also warns when an owning faction has no modeldb texture
entry, which ours does — and ours then offers to *fix* it on save (**Fix unit
ownership**, Phase 1.x), adding the missing EDU ownership and copying the
textures from a faction that has them.

### `UnitDescriptionTab.jsx` — card sizes that match nothing

It re-encodes an imported image to TGA at a fixed target size:
`card` 48×56, `info` 260×350, commented "approximate M2TW sizes". Measured over
Divide and Conquer's own art:

* **1440 of 1440 unit cards are 48×64.** Every card exported through their tool
  is squashed by eight pixels.
* **Info cards have no single size at all** — 432×172 (2531), 423×172 (1481),
  423×231 (128), 143×210 (81), 191×280 (18), 423×171 (11) across 4290 files.
  260×350 matches **none** of them.

Ours converts a `.png`/`.jpg` to `.tga` and leaves the dimensions alone, which is
the only defensible behaviour for a set that spread. Their per-faction variant
detection (`detectVariants`, guessing the faction from the second-to-last path
segment) is the same job our icon pipeline does from the unit's real `ownership`
list, which is where the answer actually is.

### `useEDUAutoSave` / `localStorage` throughout their unit screens

Five storage keys (`m2tw_edu_units`, `m2tw_units_file`, `m2tw_edu_file_name`,
`m2tw_export_units_file`, `m2tw_unit_images`) hold the whole EDU, the whole
strings file and every decoded card in the browser. Phase 12 refused the same
thing for the EDB and the reason has not changed: ours is a local server with the
mod on disk, every write is explicit, and every write has a backup and an undo
behind it.

---

## One thing the EDU header gets wrong, and one it gets right

The header comment in `export_descr_unit.txt` is the arbiter used above, and it
is worth writing down where it can and cannot be trusted, because it is RTW-era
in exactly one place:

* **Wrong.** "Tech type = simple, other, blade, archery or siege." None of those
  five strings appears in any of the 1756 units; the real values are the six
  `melee_*` / `missile_*` / `artillery_*` names. Their list is wrong in a
  different direction from the header's, so neither tool got this from the file.
* **Right, and worth keeping.** `stat_mental`'s "optional `lock_morale` stops
  unit from ever routing" — **51 real uses**, and the reason our fourth slot is a
  checkbox. `stat_pri_attr`'s "`spear_bonus_x` where x = 2, 4, 6, 8, 10 or 12" —
  the files use five of the six (everything but `spear_bonus_2`), and offering
  all six is right for the same reason Phase 12 adopted eleven unused capability
  keywords: the family is engine vocabulary, and a list built from three mods
  would keep every later mod to their habits.
