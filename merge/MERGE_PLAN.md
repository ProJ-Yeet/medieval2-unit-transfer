 > **Superseded as a plan by [ROADMAP.md](../ROADMAP.md) (2026-08-13).** The
> analysis below (their LOC map, overlap table, architecture notes) is still
> valid reference; the phase pipeline and licensing section are not — the
> author granted permission, and the V2 direction is vanilla-UI ports, not a
> React fork.

# Merging `m2tw-editor` into Unit Transfer

**Upstream:** https://github.com/Machiavello-1441/m2tw-editor (`main`, no releases, no tags, no license)
**Analysed at:** commit `7cab442` (2026-08-12), 1947 commits, 298 files
**Our side:** Unit Transfer v1.9.9 — 16.8k LOC Python, 8.2k LOC tests, 10.3k LOC vanilla web UI

This document is the durable plan. It survives across sessions: state lives in
`merge/STATE.json` and `merge/PORT_MANIFEST.json`, decisions in `merge/decisions/`.
Start any session by reading `merge/STATE.json`.

---

## 1. What their tool actually is

A **Base44-generated React 18 + Vite SPA** (~59.6k LOC in `src/`, of which ~4k is
shadcn/ui boilerplate). It is a *browser* application:

| Aspect | Reality |
|---|---|
| File input | `<input webkitdirectory>` — user picks `data/`, files are read into memory. **No File System Access API anywhere** (one `indexedDB` use, for EDB autosave). |
| File output | JSZip → `a.download` of a `<mod>_data.zip`. It never writes back to the mod. |
| State | 241 `localStorage` call sites + React contexts (`EDBContext`, `RefDataContext`, `TraitsContext`, `AncillariesContext`, `ModDataContext`). |
| Cloud coupling | Base44 SDK in **12 files only**: auth (`AuthContext`), entities (`Region`, `Character`, `ScriptTemplate`, `CampaignData`…), `InvokeLLM` for two AI assistants, one `uploadToDrive` function. Stripe deps are present but unused in app code. |
| Safety | No backups, no undo, no plan/preview→apply. Edit-in-memory, export-and-hope. |
| Correctness posture | Vanilla vocabularies **hardcoded** (e.g. `EDUParser.jsx` ships literal lists of attributes, formations, the 24 vanilla factions). Mod-specific vocab is not derived from the mod. |
| Release discipline | Commits are auto-pushed from the Base44 builder, ~all titled "File changes". Direct-to-`main`, no branches, no tags. |

Activity: 1454 commits in 2026-03, then 226 / 11 / 160 / 67 / 29 through 2026-08.
Recent work is almost entirely `src/components/map/` (strat map, resources, characters).

### Their feature surface (by LOC)

```
map/            12,835   campaign map: TGA layers, region paint, coastline trace,
newmap/          6,483   OSM/Köppen/land-cover import, bbox+feature layer gen,
                         descr_strat parse, family tree, disasters, events, scripting
edb/             5,261   export_descr_buildings: tree, levels, capabilities, guilds,
                         requirement builder, validator, autosave, icon cropping
ui/              4,002   shadcn component library (boilerplate)
units/           1,875   EDU parse/edit, modeldb panel, ownership, descriptions, cards
minorfiles/      1,633   rebel factions, religions, resources, character names
factions/        1,570   descr_sm_factions, banners, symbols, strings
shared/          1,526   trigger/condition editors, effects builder, TGA decode
traits/          1,335   export_descr_character_traits
stratmap/        1,198   descr_strat character models + preview
ancillaries/     1,137   export_descr_ancillaries
lua/             1,016   M2TWEOP Lua editor, ImGui editor, API reference, AI assistant
assets/          1,670   3D model/texture viewer, pose editor
export/            978   mod validator, trigger validation, package picker
spritesheet/       788   sd XML sprite sheet editor + canvas
banners/           686   banner textures
animation+anim/    877   CAS animation inspector, bone table, skeleton viewer, scaling
cultures/          217
lib/             3,010   ★ codecs: casCodec, casAnimCodec, ms3dCodec, modeldbCodec,
                         textureCodec, tgaEncoder, stringsBinStore, skeletonPoser,
                         slerpUtils, worldCover, mapLayerStore
pages/          10,511   23 page shells incl. UnitCardGenerator (775), GoatTools (503)
```

---

## 2. Head-to-head

### Overlap (both tools do it — redundancy to resolve)

| Domain | Ours | Theirs | Verdict |
|---|---|---|---|
| EDU parse/edit | `edu.py` 849 + `vocab.py` (vocab derived from the mod), `edit.py` 2k | `EDUParser.jsx` 262, hardcoded vanilla vocab | **Ours wins.** Theirs is a subset with wrong assumptions for mods. |
| `battle_models.modeldb` | `modeldb.py` 729 + `bmdb.py` 1449 (audit, cleanup, orphan detection) | `modeldbCodec.js` 300 + `ModelDbPanel.jsx` 522 | **Ours wins** on logic; their panel is a UI to reuse. |
| export_descr_buildings | `buildings.py` 2290 (stats, recruitment, ownership, checks) | `edb/` 5261 (guild editor, capability library, requirement builder, level images, validator) | **Split.** Ours owns the file; **their UI + capability/requirement vocabulary is a real gain**. |
| Sounds | `sounds.py` 716 (voice bank surgery, EDU accent pinning) | `SoundEditor.jsx` 380 | **Ours wins.** |
| Sprites | `sprites.py` 979 (generate + wire far-LOD) | `spritesheet/` 788 (sd XML editor, canvas) | **Complementary** — we generate, they edit/inspect. |
| Unit cards / icons | `icons.py`, `edit.py` icon import | `UnitCardGenerator.jsx` 775 | **Theirs adds** a generator we don't have. |
| Lua / M2TWEOP | `eop.py` 433, `luascan.py` 243 | `lua/` 1016 (editor, ImGui, API reference) | **Complementary.** |

### Only ours

Cross-mod **transfer engine** (`transfer.py`, 119 KB) with dependency resolution,
collision handling, kind-restricted base/replace modes, mount-animation logic;
**backup + undo**; **plan→preview→apply**; unit **packs**; siege `descr_engines`
+ binary texture extraction; projectiles; mounts; localisation; the mod registry;
`.pack` vanilla-UI fallback; a Windows portable release with bundled Python;
**41 test files / 8.2k LOC of tests**.

### Only theirs

Campaign map editing (the single biggest asset, ~19k LOC), region/geo import,
`descr_strat`, traits, ancillaries, factions/cultures/religions/resources/rebels,
character names, family tree, campaign scripting with templates + validation,
**`.strings.bin` codec**, **CAS / .mesh / MS3D binary codecs**, **DDS/TGA
decode+encode**, 3D viewer, skeleton pose editor + animation inspector, unit card
generator, mod-wide validation dashboard.

### The architectural mismatch (this is the whole problem)

Ours is **filesystem-authoritative**: a local Python server reads and writes the
real mod, backs up everything it touches, and can undo. Theirs is
**memory-authoritative**: files are copied into the browser, edited, and dropped
back as a zip the user has to unpack over their mod by hand.

Their parsers are therefore written as React modules coupled to contexts and
`localStorage`, not as reusable libraries. **Nothing of theirs can be "imported"
as-is.** Every port is either a rewrite of the *format knowledge* in Python, or a
rewire of a *UI component* onto our API.

---

## 3. Blocker to clear first: licensing

**The repo has no LICENSE file.** By default that means all rights reserved — we
have no permission to copy, adapt, or redistribute any of it, and our release zip
is public. Before any of their code (or a line-by-line translation of it) ships
in Unit Transfer:

1. Ask the author to add a permissive licence (MIT/Apache-2.0), **or** get
   written permission to relicense their contributions under ours.
2. Record the outcome in `merge/decisions/0001-licensing.md`.
3. Until then, Phase 2 may proceed **only** for formats where we write our own
   implementation from the public format spec (their file headers cite public
   sources: the MS3D spec, BinEditor v3.0), documenting the source we used — not
   from their code.

Also worth agreeing up front: whether this is a **merge** (he joins, we become
one project) or an **absorb** (we track his repo as an upstream we harvest from).
The pipeline below works for both, but the answer changes how much we invest in
adapting his UI versus replacing it.

---

## 4. Recommended course of action

> **One engine, two front-ends.**
> Our Python package stays the single source of truth for every byte on disk.
> Their React app is forked into `studio/`, stripped of Base44, and rewired so
> its editors talk to our HTTP API instead of browser memory.

```
                    ┌──────────────────────────────────────┐
   web/index.html   │  unittransfer/  (Python, sole owner  │   studio/  (React,
   vanilla UI,   ──▶│  of parsing, disk I/O, backup/undo,  │◀── forked from
   zero-build       │  plan→apply, packs, transfer engine) │    m2tw-editor)
                    └──────────────────────────────────────┘
                          ▲ HTTP /api/*  (47 endpoints today)
```

**Why this and not the alternatives**

- *Port their React app wholesale into our repo and drop our UI* — throws away a
  vanilla UI that works with zero build step, and imports 241 `localStorage`
  couplings and cloud auth into a tool whose selling point is "unzip and run".
- *Rewrite their 19k-LOC map editor in vanilla JS* — not worth it. That code is
  canvas/3D-heavy and genuinely good; it should be reused, not retyped.
- *Push our transfer engine into their Base44 app* — impossible. Cross-mod
  transfer needs real filesystem access, backups and undo. A browser tab can't do
  it, and Base44 hosting makes it worse.
- *Keep two separate tools and just share formats* — leaves the user with two
  installs and two conflicting ideas of what the mod currently contains.

**Non-destructive by construction**

- Nothing in `unittransfer/` is deleted or rewritten to accommodate them.
- `web/index.html` stays the default UI and keeps working standalone. Studio is
  an *optional* second front-end (`Unit Transfer.bat --studio`), shipped
  prebuilt so end users never see npm.
- Their code lives in `studio/` with a pinned upstream SHA; their history is
  fetched into our repo so it survives even if they delete the repo.
- Every phase lands as its own commit behind passing tests; any phase can be
  reverted without touching the ones before it.

**No redundancies — the single-source-of-truth doctrine**

For each M2TW file format, exactly one implementation is authoritative, and it is
in Python. Every one of their JSX parsers gets exactly one disposition:

| Disposition | Meaning | Example |
|---|---|---|
| `reject` | We already own this format. Their parser is deleted from the fork; their UI calls our API. | `EDUParser.jsx`, `modeldbCodec.js` |
| `port` | They own format knowledge we lack. Reimplement in Python + tests; delete the JS parser from the fork. | `stringsBinCodec`, `sdXmlParser`, EDB capability vocabulary |
| `adapt` | UI component worth keeping; rewire its data source to our API. | `BuildingTree.jsx`, `ModelDbPanel.jsx` |
| `vendor` | Pure browser-side rendering with no file semantics. Keep near-verbatim; sync from upstream automatically. | `MapCanvas.jsx`, `SkeletonViewer.jsx`, `ui/*` |
| `defer` | Out of scope for now, revisit later. | Stripe, `GoatTools` until reviewed |

Rule: **a format may never be parsed on both sides.** If a codec exists in
`unittransfer/`, the fork must not contain a second implementation of it — the
sync tool (Phase 0) fails the build if one reappears upstream and gets pulled in.

---

## 5. Upstream tracking (he works on `main`, no releases)

Set up once, in Phase 0:

1. `git remote add upstream-editor https://github.com/Machiavello-1441/m2tw-editor.git`
   and fetch into a namespace that never pollutes our branches:
   `git fetch upstream-editor '+refs/heads/*:refs/upstream/editor/*'`.
   Their full history now lives in our repo — immune to force-pushes and repo deletion.
2. `merge/STATE.json` records `upstream.reviewed_sha` — the last commit we have
   triaged (not merged; *triaged*).
3. `merge/PORT_MANIFEST.json` holds one row per upstream file:
   `{path, sha_at_review, disposition, target, status, notes, tests}`.
4. `tools/upstream_sync.py` — the workhorse:
   - fetches, diffs `reviewed_sha..upstream/editor/main`
   - buckets every changed file by its manifest disposition
   - `vendor` files: shows the diff, offers to apply into `studio/`
   - `adapt` files: flags for manual review, prints the diff and our local delta
   - `port` files: flags **"format knowledge may have changed"** → check whether
     the Python implementation needs updating, and whether a test must change
   - `reject` files: silently ignored, but counted
   - **new files** upstream: appended to the manifest as `status: untriaged`
   - writes a dated entry to `merge/SYNC_LOG.md` and bumps `reviewed_sha`
5. Cadence: run it weekly, and always before starting a new phase. Because his
   commit messages are all "File changes", the diff is the only signal — the tool
   reads diffs, never messages.

---

## 6. Phased pipeline

Every phase: has an entry gate, produces artefacts, ends with `pytest` green and
one commit. `merge/STATE.json` names the current phase and the next pending item,
so any session resumes by reading it. No phase depends on a later one.

| # | Phase | Output | Gate to start |
|---|---|---|---|
| **0** | **Tracking + legal infra** | upstream remote fetched, `merge/STATE.json`, empty manifest, `tools/upstream_sync.py`, licence question sent | — |
| **1** | **Triage all 298 files** | `PORT_MANIFEST.json` fully populated: every file has a disposition + target + rationale | Phase 0 |
| **2** | **Format harvest (Python)** | New `unittransfer/` modules + tests, no UI: `stringsbin.py`, `spritesheet.py` (sd XML), `casmodel.py` (.mesh/.cas/MS3D), `texture.py` (DDS/TGA encode), `traits.py`, `ancillaries.py`, `factions.py`, `cultures.py` | Phase 1; licence cleared (or spec-only reimplementation) |
| **3** | **API parity for new domains** | `/api/traits/*`, `/api/ancillaries/*`, `/api/factions/*`, `/api/strings/*`, `/api/campaign/*` — each with plan→apply, backup and undo, matching our existing endpoint contract | Phase 2 per-domain (can run domain-by-domain) |
| **4** | **Fork bootstrap** | `studio/` vendored at a pinned SHA; Base44 auth/entities/Stripe/LLM stripped; builds offline; `npm run build` produces static assets | Phase 1 |
| **5** | **Wire Studio to the engine** | `studio/src/api/engine.js` replaces `base44Client.js`; mod selection via `/api/mods`; file loading via API, not `webkitdirectory`; `localStorage` demoted to a cache | Phase 4 |
| **6** | **Redundancy kill, domain by domain** | For units → modeldb → EDB → sounds → sprites: their editor UI on our engine, their parser deleted, manifest rows flipped to `done` | Phase 5 + the matching Phase 3 domain |
| **7** | **Browser-only features get real I/O** | Campaign map, 3D viewer, animation editor read and write through the API with backup/undo | Phase 5 |
| **8** | **Packaging** | `build_release.py --with-studio` bundles prebuilt Studio assets; `Unit Transfer.bat` gains a Studio toggle; release zip size budget checked | Phase 6 |
| **9** | **Steady state** | Weekly `upstream_sync.py`; new upstream features triaged into the manifest, not merged blind | Phase 8 |

**Sequencing note.** Phase 2 is deliberately first-and-independent: it is pure
gain (our tool gets `.strings.bin`, sprite-sheet and CAS support) and it is
useful even if the merge is later abandoned or the licence answer is "no" for
their code specifically. Phases 4–7 are where the cost is.

**Rough weight.** Phase 2 ≈ 8 Python modules with tests. Phase 3 ≈ 5 domains ×
(model + endpoints + backup/undo + tests). Phases 4–7 ≈ the bulk: ~50k LOC of
React to fork, strip, and rewire, of which realistically ~15k needs hands-on
adaptation and the rest is vendored or dropped.

---

## 7. Risks

| Risk | Mitigation |
|---|---|
| **No licence** → we can't ship any of it | Phase 0 blocker; spec-only reimplementation as the fallback path |
| Upstream churns fast on `main` and breaks our fork | Vendored fork pinned to a SHA; we pull deliberately, never track `main` live |
| Their hardcoded vanilla vocab leaks into our mod-aware engine | Doctrine: their vocab lists are *fallbacks only*; our `vocab.py`/`edbvocab.py` derivation wins |
| Release zip bloats past what users tolerate | Studio ships as prebuilt static assets, gzipped, behind a flag; measure at Phase 8 against the current ~53 MB |
| React front-end raises the bar for contributing | The vanilla UI stays fully functional and is the default |
| Merge stalls half-done | Every phase is independently valuable and independently revertible; `STATE.json` makes a cold restart cheap |

---

## 8. Immediate next actions

1. Decide **merge vs absorb** and ask the author about licensing.
2. Approve this plan (or amend it), then run Phase 0.
3. Phase 1 triage of 298 files — mechanical, and it's what makes everything after
   it resumable.
