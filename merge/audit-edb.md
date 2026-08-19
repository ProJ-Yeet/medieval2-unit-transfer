# EDB — what the reference tool has, and what we took

_Phase 12. Compared against `refs/upstream/editor/main` at the SHA in
`merge/SYNC_LOG.md`: `src/pages/EDBEditor.jsx` and
`src/components/edb/{BuildingTree,EDBContext,EDBParser,LevelEditor,
CapabilityEditor,CapabilityLibrary,RequirementBuilder,UpgradesEditor,
HiddenResourceEditor,LevelCultureEditor,GuildEditor,ValidationPanel,
EDBValidator,BuildingTextEditor,AutoSavePanel,ImageCropModal}.jsx`._

**Verdict: four ideas taken, six refused, and one of the refusals is the reason
this audit exists.** Every claim below was measured against the three mods
installed in August 2026 — **277 building lines, 1099 levels, 771 upgrade
entries** — rather than taken from either tool's source. Where our list and
theirs disagree, the count in brackets is what the real files say.

> **Corpus note, 2026-08-18.** That set is gone: Third Age 3 and 6 are no longer
> installed and Third Age Reforged has taken their place, so the corpus is now
> **248 lines, 856 levels, 601 upgrade entries**. The counts below stand as what
> was measured, and `tests/test_edb_tree.py` re-measures the same facts against
> whatever is installed today. Two of them did **not** survive the new mod and
> are corrected in place, marked ⚠ — both in the direction of *strengthening* the
> case against their serialiser, not weakening it. A count is only load-bearing
> here when the scaffold leans on it; where it does, the check now asserts our
> own behaviour and merely reports the mods'.

Our Buildings module already had the things the roadmap thought it might be
missing: a per-level form, a `requires` clause builder over the mod's own
vocabulary, recruit-pool editing with cross-tree mirroring, Code View (Phase 4b),
plan → preview → apply with backup and undo. So this audit is narrower than the
earlier ones — it is about *layout* and about the one operation we did not have.

---

## What we took

### 1. The collapsible tree, as an alternative and not a replacement

`BuildingTree.jsx` lists every line with its levels folded underneath. That is
the right shape for the question "what is in this mod": DaC's 136 lines and 499
levels fit in two screens as rows, and in about fifteen as cards.

It is a **second** view rather than a replacement, because the gallery answers a
different question — a building card is how anyone recognises a building they
have seen in game, and their editor has no art at all. `▦ Gallery / ▤ Tree`
sits in the list header and the choice is remembered (`bld_browse`).

Not taken from it: the **drag handle** that reorders building lines. Their
`reorderBuildings` moves a line in the array and re-serialises the file. Ours
never re-emits the EDB — every edit is a splice of known line indices, which is
what keeps DaC's hand-written `;ok old_pool=2 new_pool=2` comments and its
line-by-line mix of tabs and spaces intact. Reordering is also not an edit
anybody needs: nothing in the file or in `descr_strat.txt` reads the order.

### 2. "Add a new building tree"

The one operation the screen did not have. Theirs is `createDefaultBuilding` — a
name, one level, a `happiness_bonus` and a hardcoded
`requires factions { northern_european, southern_european, }`. Ours
(`buildings.plan_new_tree`) keeps the shape and changes every value:

* **the clause is this mod's own cultures**, the ones a faction actually belongs
  to. Their two would be two of Divide and Conquer's nine and two of Third Age
  6's twelve — a new building most of the mod cannot build. (Third Age 6's own
  `descr_cultures.txt` declares 22, ten of which have no faction and no art at
  all, so "every declared culture" is not the right list either.)
* **the levels chain forward.** Each level's `upgrades` block names the next.
  All **771** upgrade entries measured point at a level listed *after* them on
  the `levels` line — none backwards, none at itself, none at a level its line
  does not have — which is what TWCenter's *List of Hardcoded Limits* says the
  engine requires.
* **three text keys per level, in the same job.** `{x}`, `{x_desc}`,
  `{x_desc_short}`; a level short of one crashes the game at the construction
  panel, and all **1099** real levels have all three. Their editor keeps text in
  browser state and asks you to export a second file afterwards; a mod with no
  `data/text/export_buildings.txt` is refused here rather than half served.
* **an empty `plugins { }` block**, which theirs never writes. ⚠ Not because the
  engine demands one — Third Age Reforged omits it on **45 of its 112** lines and
  runs, so it is optional. It is written because it is the shape 203 of the 248
  current lines take and an empty one can lose nothing (below).
* **the indent is the file's own**, read off its existing `levels` lines. These
  files are hand-maintained and no two of the three agree.

### 3. The capability library, grouped, with ranges

`CapabilityLibrary.jsx` carries 59 capabilities from a spreadsheet with a
type/subtype tree, the argument shape, the accepted range and a description.
Our `CAP_HELP` had 49 with a one-line hint and no grouping, and the picker was
one flat alphabetical `<select>` — a list you read rather than one you choose
from, because `construction_cost_bonus_stone` and `weapon_melee_blade` are not
neighbours in anybody's head.

Taken: the **grouping** (`CAP_META` / `CAP_GROUPS`, nine groups, shown as
`<optgroup>`), the **ranges** (beside the keyword and in its hint), and the
**eleven keywords we did not have**: `construction_cost_bonus_defensive`,
`_military`, `_other`, `_religious`, `construction_time_bonus_military`,
`_stone`, `_wooden`, `fire_risk`, `gate_defences`, `upgrade_bodyguard`,
`weapon_melee_simple`.

Adopting hardcoded *values* is the thing this project keeps refusing — an
ancillary's `Type` in Phase 9, a religion list in Phase 10b. It is right here
and wrong there for one reason: **a capability keyword is engine vocabulary, not
a fact about a mod.** Not one of the eleven is used by any of the three
installed mods, and that is exactly why a list built only from those three would
have been wrong — it would have kept every mod to their habits. (The check runs
the other way too: all **48** keywords the real files use were already in our
list, so nothing was missing.) Four of the eleven are documented in their own
source as having no effect; those say so in the hint, because a keyword that
silently does nothing is worse than a missing one.

### 4. A clause on each upgrade

`UpgradesEditor.jsx` lets an upgrade entry carry its own requirements. It is
right that it can: **41 of the 771** real entries were
`wooden_wall requires factions { … }`, and ours showed the clause as a
read-only `<code>` chip. (None of the 601 current entries carries one — how many
mods happen to use the feature says nothing about whether the editor should
support it, so `test_edb_tree` now reports that count and asserts
`upgrade_name()` against every real entry instead.) Now the row has the same ✎ picker every other clause in
the module has, over the same vocabulary, writing back into the same string —
`detail()` gained `upgrade_paths` (the entry taken apart) beside the strings a
save still sends, so nothing else changed shape.

Not taken from it: **which levels it offers.** Theirs offers every level in the
line except the one you are on, so it will happily write an upgrade that points
backwards — a thing zero of the 771 real entries do. Ours has always offered
only the levels after this one, and now says why.

---

## What we did not take, and why

### `HiddenResourceEditor.jsx` — a delete with nothing behind it

Add and remove names on the `hidden_resources` line, with no check either way. A
hidden resource is named by `descr_regions.txt` (which region has it) and by
`requires hidden_resource X` clauses throughout the EDB itself, and removing one
breaks both silently — the building simply never becomes available, which is the
hardest kind of EDB bug to see.

Two facts make the feature worth having *later* rather than now: TWCenter's
hardcoded-limits note puts the ceiling at 63 or 64 and says extras CTD, and
**Divide and Conquer ships 74** — so the limit as written is not the limit, and
we would be warning about something three of three mods disprove. Deferred with
its checks, not adopted with theirs. (The list is already shown, read-only, in
the clause picker's vocabulary.)

### `GuildEditor.jsx` / `GuildsParser.jsx` — a second file, out of this phase

`export_descr_guilds.txt` is its own format (`Guild <name>` / `building
guild_<x>` / `levels <a> <b> <c>` plus trigger blocks). The pairing is exact and
worth knowing — **all 19** `guild_` lines in the installed mods are named there,
no orphans in either direction, and nothing that is not a `guild_` line appears
in that file — so the new-tree flow *says* a `guild_` line needs an entry. It
does not write one. That file is a phase of its own, not a corner of this one.

### `EDBParser.jsx` / `EDBExporter.jsx` — a re-emitting serialiser

The disqualifying difference, and the reason our whole module is built the way it
is. Theirs parses the EDB into objects and writes it back out from them, so a
save re-emits all 17 500 lines of DaC's file from scratch, opening with
`;This file is generated by …` and four blank lines.

**7203 of the 32 987 lines in the three installed EDBs carry a comment**, and
none of them survives that: the `;ok old_pool=2 new_pool=2 (Orc infantry T4 @
T5)` notes DaC's authors wrote on their `recruit_pool` lines, the `;####` banners
the file is organised by, the per-line mix of tabs and spaces, the blank lines.
Ours keeps the file as its verbatim lines and splices known ranges; nothing
outside an edited range is ever rewritten, and `tests/test_buildings.py` asserts
the byte-exact round trip on every installed mod.

Checked while here: their level serialiser knows four scalars (`material`,
`construction`, `cost`, `settlement_min`), and it always emits an empty
`plugins { }`.

* The empty `plugins { }` loses nothing, and that is still true: **every** real
  plugins block, in both the old corpus and the new one, is empty. This is the
  one plugins fact the scaffold leans on, so it is the one `test_edb_tree`
  asserts; whether a line carries the block at all is reported, not required.
* ⚠ Four scalars is **not** enough, which the old corpus hid. A level body may
  also carry `convert_to <n>` — distinct from the line-level `convert_to <name>`
  — and **121 of the 856** current levels do (Divide and Conquer 37, Third Age
  Reforged 84). Their serialiser drops it from every one of them. Ours keeps
  every scalar it finds, because it splices and never re-emits.

### The four prefix hints in their new-building dialog

`BuildingTree.jsx` offers `core_`, `hinterland_`, `temple_` and `guild_` as
prefixes with a one-line hint each. The prefixes are worth offering — ours does —
but two of the hints are claims about the engine that the files do not support,
and one of the four is not a modder's to choose:

| Their hint | What 277 real lines say |
|---|---|
| `core_` — "Upgrades settlement to next level" | It is the settlement's own chain, and **every mod defines exactly two**: `core_building` and `core_castle_building`. Both already exist in any mod you would open. A third does not appear anywhere. Ours offers it with that said. |
| `hinterland_` — "Cannot be demolished for cash" | Nothing restricts it. **75 lines, 66 distinct names**, including a mod's info-panel dummies, unique province features and a second copy of a guild. Vanilla's province-wide lines carry it; that is all our hint claims. |
| `temple_` — "Only one temple_ building per settlement" | Not measurable from these files, so not repeated. What is measurable: **all 32** `temple_` lines also carry a `religion` line, so ours says to pick one. |
| `guild_` — "needs entry in export_descr_guilds.txt (max 3 levels)" | Both halves survive contact: **19 of 19** guild lines are named in that file, and **19 of 19** have exactly three levels. Only the first is kept as a hint, because "every real one has three" and "the engine refuses a fourth" are different claims and only the first is measured. |

### `AutoSavePanel.jsx` / `useEDBAutoSave.jsx` — autosave into browser storage

Their editor holds the EDB in `localStorage` and writes it back periodically.
Ours is a local server with the mod on disk: nothing is held anywhere, every
write is explicit, and every write has a backup and an undo behind it. There is
nothing to port.

### `ImageCropModal.jsx` — crops building cards in the browser

Building art is a `.tga` under `data/ui/<culture>/buildings/`, and the toolkit
has an icon pipeline of its own already (Phase 1.x, `/icon` and the import
flow). Cropping is not the missing piece; drawing is. The new-tree preview lists
the card paths a new line will want and calls a blank one a blank — Phase 10a's
ruling that art references are shown and never called faults.

---

## Two things the limits document gets wrong for M2TW

TWCenter's *List of Hardcoded Limits* is the arbiter for most of this file, and
it is an RTW-era document in two places that matter to a new-tree flow. Both were
caught by measuring instead of quoting:

* **"Overall building tree number: max 64. Extras CTD."** Third Age 3 has **117**
  and Divide and Conquer **136**, and both run. So creating a tree number 65
  produces no warning here.
* **"Levels per building tree: max 9. Extras CTD."** True of vanilla; M2TWEOP
  raises it and mods lean on that. The deepest real tree measured is Third Age
  6's `core_building` at **51 levels**. So passing nine is *said* — with the
  number and the reason — and not refused. Their tree shows the same warning at
  level 9, which is the one place their editor and the document agree with each
  other and with us.

The third limit in that entry — "levels can only be upgraded to levels listed
after them on the `levels` line" — holds in all 771 real entries, and is the one
the scaffold is built on.
