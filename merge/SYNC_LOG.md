# Upstream sync log

Every review of Mylae's `main`, newest first. Written by
`tools/upstream_sync.py sync --accept`. His commit messages all say
"File changes", so these entries are the only record of what actually moved.

## 2026-08-20 — b4768d5..e6e6982

19 commits, 18 files changed.

### port-concept (6)
- `M` `src/components/map/CharactersTab.jsx` — phase 16  <-- FORMAT KNOWLEDGE MAY HAVE CHANGED
- `M` `src/components/map/MapCanvas.jsx` — phase 16  <-- FORMAT KNOWLEDGE MAY HAVE CHANGED
- `M` `src/components/map/RegionEditorPanel.jsx` — phase 16  <-- FORMAT KNOWLEDGE MAY HAVE CHANGED
- `M` `src/components/map/StratPanel.jsx` — phase 16  <-- FORMAT KNOWLEDGE MAY HAVE CHANGED
- `M` `src/components/map/stratParser.jsx` — phase 16  <-- FORMAT KNOWLEDGE MAY HAVE CHANGED
- `M` `src/pages/CampaignMap.jsx` — phase 16  <-- FORMAT KNOWLEDGE MAY HAVE CHANGED

### out-of-scope (10)

Counted only.

### skip (2)

Counted only.

### What actually moved

Every one of the 19 commits lands in the campaign map editor or the New Map
Editor. Nothing touches a file behind a module V2 has shipped, so nothing here
had to be implemented to keep 2.0.0 correct. His messages are real sentences
again for the newest eight commits, which is new; the older eleven are still
"File changes", so this was still read as a diff.

### The one correction we took

`RegionEditorPanel.jsx` swapped the labels on the two bare numbers at the foot
of a `descr_regions.txt` record: the first is the **triumph value**, the second
the **base farming level**. He had them the other way round and so did we, in
`unittransfer/edbvocab.py`'s `regions()` docstring ("farming level" then
"unknown/level").

His word was not what settled it. Vanilla's own 112 regions were measured: the
first number is 5 on 110 of them and 4 on the other two, while the second runs
1 to 6 with a real spread, which is a fertility level and not a score. Both
test mods write 5 and 1 for every single region, so a measurement over the
installed mods alone could never have told the two apart. The docstring is
corrected and carries the measurement. Nothing reads either value yet; phase
16c's region inspector is what will, and it already lists "triumph value" in
its exit criteria.

### Three facts banked for phase 16

Recorded in the `notes` field of the file each came from.

- A fort's comment in `descr_strat.txt` has moved out of the fort line
  (inline `;;;;; text`) and onto its own `;;; text` line above it. He parses
  both, so 16a must read the inline form as legacy input and write the new one.
- A new character is inserted after the last existing character **of the same
  faction**, not at the head of the list, because in `descr_strat` a character
  belongs to the faction block it sits inside. List order is file order, and
  16a's writer has the same constraint.
- An M2TW heightmap carries elevation in R and G and sea/water level in B
  (`HeightmapAdjustPanel.jsx`, out of scope itself). Check the TWCenter index
  before leaning on it.

His painting rewrite in `CampaignMap.jsx` is a React fix to a real problem 16b
will meet: copying a multi-megabyte pixel buffer and calling
`createImageBitmap` once per frame is what froze his canvas. He mutates in
place and rebuilds the bitmap on a 120 ms debounce.

### Two new files, both filed out-of-scope

`src/lib/osmTiles.js` is Overpass bbox-splitting arithmetic whose only two
importers are `newmap/OsmTagOverlayEditor.jsx` and `pages/NewMapEditor.jsx`;
the auto-rule had guessed `audit` because it sits under `src/lib/`.
`newmap/HeightmapAdjustPanel.jsx` is New Map Editor UI. Neither is M2TW format
knowledge. The `OsmBackground.jsx` / `OsmRegionSearch.jsx` question is
untouched by this sync and still open.

### Phase numbers corrected in the manifest and the rules

The manifest and `upstream_sync.py`'s RULES table still used the numbering from
before ROADMAP.md renumbered on 2026-08-18: old 14 was the 3D/texture phase and
old 15 the campaign map. 46 map files moved 15 to **16** and 10 model/texture
files moved 14 to **15**; the banner and spritesheet files keep 14, because
that work really did ship in 14f. A number printed beside every changed file is
worse than no number when it names the wrong phase, and this sync would have
read as "phase 15, the phase STATE.md says is next".

## 2026-08-14 — 7cab442..b4768d5

7 commits, 1 files changed.

### port-concept (1)
- `M` `src/components/map/stratParser.jsx` — phase 15  <-- FORMAT KNOWLEDGE MAY HAVE CHANGED

## 2026-08-13 — baseline at 7cab442

Phase 2. Nothing to diff against: this is where tracking starts.

His full history (1947 commits) is mirrored into this repo under
`refs/upstream/editor/*` — it now survives a force-push or the repo being
deleted, and no branch of ours can be confused with one of his. All 298 files at
`7cab442` (2026-08-12) are triaged in `PORT_MANIFEST.json`:

| Disposition | Files |
|---|---|
| port-concept | 124 |
| skip | 86 |
| out-of-scope | 68 |
| audit | 20 |

Nothing is left untriaged.

**Where his effort is going.** Replaying the last 80 commits through the tool
(as a test of it) showed the changes land almost entirely in
`src/components/map/` and `src/pages/CampaignMap.jsx` — phase 16, the flagship,
and the last phase we build. Expect this file set to be substantially different
by the time we get there; re-sync before 16a and before every sub-phase after it
(the map editor was renumbered 15 → 16 on 2026-08-18).

**Decisions recorded during triage** (see the `notes` field on each file):

- `src/lib/autoGroundTypes.js` is excluded as a generator, but it holds the
  canonical M2TW ground-type RGB table, which phase 15 needs in order to *read*
  `map_ground_types.tga`. Take the constants, never the generator.
- `CampaignEventsTab.jsx` / `campaignEventsParser.jsx` are kept in phase 15.
  They edit `descr_events.txt`; the thing ruled out of V2 was the script editor
  (`ScriptEditor.jsx`, `ScriptingPanel.jsx`), which is a different feature.
- `OsmBackground.jsx` and `OsmRegionSearch.jsx` are flagged **decision needed**:
  they fetch OpenStreetMap tiles as a backdrop to trace over. That is a
  reference layer rather than generated mod data, but it is still an external
  fetch, so confirm before porting.
- Only two files in his entire tree call an LLM (`LuaAiAssistant.jsx`,
  `ScriptAIAssistant.jsx`); both are `out-of-scope`, as are all six
  generator/fetcher components under `newmap/` and `SymbolGenerator.jsx`.
