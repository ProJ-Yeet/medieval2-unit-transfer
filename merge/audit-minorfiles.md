# Minor files — what the reference tool has, and what we took

_Phase 10a. Compared against `refs/upstream/editor/main` at the SHA in
`merge/SYNC_LOG.md`: `src/pages/MinorFiles.jsx`, `src/pages/CulturesEditor.jsx`,
`src/pages/CharactersEditor.jsx`, `src/components/minorfiles/{RebelFactionsTab,
RebelFactionRow,RebelUnitPicker,ReligionsTab,ResourcesTab,CharacterNamesTab}.jsx`
and `src/components/cultures/culturesParser.jsx`._

**Verdict: the tab layout taken, all five parsers rejected.** This is the first
audit where the reference implementation is not merely lossy but *wrong about the
format* — three of its four small-file parsers cannot read a single real file
correctly, and two of its serialisers write files the engine will not load. Every
claim below was checked against all 15 of these files in the three installed
mods (Divide_and_Conquer_EUR, third_age_3, Third_Age_6).

## What we took

**One module, several tabs.** Their `MinorFiles.jsx` puts rebels, religions,
resources and names behind one tab bar, and that is obviously right: these are
four files nobody opens on their own. We add cultures as a fifth tab rather than
the separate page they give it, because `descr_cultures.txt` is the same size of
job. `minorfiles.TABS` is that list.

**The file each tab needs, named on the tab.** Their tab descriptions spell out
the `.txt` *and* the `.strings.bin` beside it. Ours does the same through the
Home module's readiness matrix, which already knows how to say "this file is not
here".

**A unit picker for rebel `unit` lines** (`RebelUnitPicker.jsx`) — a rebel
faction names EDU unit types, and typing them by hand is how you get a rebel
faction that spawns nothing. Ours reads the mod's own EDU, which is the same
idea; theirs reads whatever EDU was uploaded.

## What we did not take, and why

### `ReligionsTab.jsx` — reads no religion and writes an unloadable file

Its parser looks for `icon`, `pip` or `anti_pip`. The real key is **`pip_path`**,
and it sits inside a brace block:

```
religions
{
	catholic
	islam
}

religion catholic
{
	pip_path	ui/pips/pip_evil.tga
}
```

Measured across all three mods: 25 religion blocks, 25 `pip_path` lines, zero
`icon`, zero `pip`, zero `anti_pip`. So their editor lists the names and shows
every pip as blank. Worse, `serializeReligions` emits

```
religion catholic
	icon	ui/pips/pip_evil.tga
```

— no braces, no `religions { … }` list, and a key the engine has never had. The
`religions` list is the part the engine actually reads as the set of religions;
a file without it is not a descr_religions at all.

It also has no idea `descr_religions_lookup.txt` must agree (it offers an
"export lookup" button that regenerates it from the block order, which is a
reasonable instinct pointed at the wrong list). Ours checks all four places a
religion is written down — the list, its block, the lookup and
`text/religions.txt` — because geeko's *How to add a religion* says all four, and
because **Third Age 3 disagrees with itself on three of them**: `heretic` has two
blocks, the `religions` list is one short of the blocks, and the lookup still
carries `rohirrim`, `wicked` and `uruk`, which the file no longer defines.

### `ResourcesTab.jsx` — the model line is `item`, not `model`

Same shape of failure, one word: every one of the 84 real resource records writes
`item data/models_strat/resource_x.CAS` and none writes `model`. Their parser
therefore reads no model and their serialiser writes a key the engine ignores,
so every resource on the campaign map loses its 3D object.

It gets `has_mine` right. It has no notion of the file-level `mine <path>` line
that says *which* model a mined resource shows, so that line is dropped on
export.

Their `RESOURCE` handling is otherwise open-ended, which we tightened rather than
loosened: the engine's resource list is **closed**. All three mods ship the same
28 names in three different orders and none has ever added one, so
`minorfiles.KNOWN_RESOURCES` reports an invented `type` as a line that is read
and then ignored.

### `RebelFactionsTab.jsx` — invents a syntax for the `unit` line

Its parser splits `unit` on commas into `unitName, minExp, maxCount`, and its
serialiser always writes all three back:

```js
lines.push(`\tunit\t\t\t\t${padded}${u.minExp}, ${u.maxCount}`);
```

**Not one of the 215 real `unit` lines in the three mods has a comma.** The rest
of the line is the unit type and nothing else — and the types have spaces in
them (`unit Mordor Orcs Invasion`, `unit Cave Trolls2`), which is exactly what a
comma-splitting parser is least able to see. Round-tripping DaC through their
editor rewrites all 151 of its unit lines.

The parser also accepts `rebel_faction` and `faction` as alternative head
keywords "(legacy/alternate)". Neither appears in any real file; the head keyword
is `rebel_type`.

Their `CATEGORIES` list of four is right, and we kept it — measured, all 68 real
records use one of exactly those four.

### `culturesParser.jsx` — right about the shape, wrong about where a record ends

The best of the four. It reads the nested settlement braces correctly, and its
`parsePath` split on the comma is the right idea. Two things stop it being
portable:

* **it splits the file on `;;;;` banner lines** to find cultures. That works on
  the files that have them and merges two cultures into one on the files that do
  not. Ours ends a culture at the next `culture` line, which is what the engine
  does.
* **its `offmapSettlement` / `offmapPort` defaults are invented data.** They are
  initialised to specific vanilla `.cas` paths and never parsed from the file, so
  a save writes six settlement models and four port models that the mod never
  said. None of the three installed mods has an `offmap` line at all.

We took its `SETTLEMENT_TYPES` and `AGENT_TYPES` lists (both measured correct)
and its reading of the agent line as seven columns. What the last two numbers on
an agent line mean is not in any document on this machine and all 234 real agent
lines write `1 1`, so ours carries them by position and never rewrites them.

### `CharacterNamesTab.jsx` — no findings, and no way to have any

`descr_names.txt` is 25 903 names in Third Age 6 and their tab is a flat list.
Ours reads sections per faction (`characters`, `women`, and `settlements` from
the file's own header comment, which none of the three mods uses) and reports
duplicates — 97 real ones across the three mods, each of which is a name the
engine will simply never pick twice as often as intended.

## The general point

Their four small-file parsers are the same code four times: strip comments,
regex the keys someone remembered, re-emit the whole file from the model. Ours
are three shapes and one splice, so a save touches the lines it changed and
nothing else — and the tab columns these files are laid up in survive it, which
is what `keyblock.head_prefix` / `sub_value` / `sub_tokens` were added for.

`unittransfer/minorfiles.py` and `tests/test_minorfiles.py` are the record: 15
real files, byte-exact round trip, zero unknown constructs, and every record
re-rendering to itself under a full-form save.
