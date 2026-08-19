# Upstream sync log

Every review of Mylae's `main`, newest first. Written by
`tools/upstream_sync.py sync --accept`. His commit messages all say
"File changes", so these entries are the only record of what actually moved.

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
