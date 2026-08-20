# Medieval 2 GUI Toolkit — V2 Roadmap

**Reference tool:** [Mylae's M2TW Editor](https://github.com/Machiavello-1441/m2tw-editor)
(React/Base44, ~59.6k LOC, works directly on `main`, no releases — used with the
author's permission). We port **behaviour and format knowledge**, never JSX.

**Ground truth when a format is unclear:** the TWCenter tutorial archive in
`Reference/TWCenter/` (indexed in Phase 1), then the Blender M2TW addon in
`Reference/Medieval-2-Toolkit/` for 3D formats.

Every phase is session-sized or explicitly split. A session doing roadmap work
**must** end by updating `STATE.md` (contract at the bottom of this file),
running the test suite, and running `graphify update .`.

## Locked decisions

- **One engine.** `unittransfer/` (Python) is the sole owner of parsing and
  disk I/O. No second parser for the same format anywhere, ever.
- **Vanilla UI only.** Reference modules are rewritten in our stack (plain JS
  served by the Python server, zero build step). No React, no npm.
- **Code View everywhere, built once.** A shared two-pane widget (GUI ⇄ raw
  code, hover-highlight, two-way live edits, server-side parsing with a
  field→line span map). Built in Phase 4, adopted by every editor after it.
- **No AI / autogenerate features. Hard no.** Excludes porting their
  `LuaAiAssistant`, `ScriptAIAssistant`, symbol generator, OSM/Köppen/land-cover
  fetchers.
- **Localised names first** everywhere in the UI, code name in brackets —
  `Town Hall (core_building)`.
- **Self-hosted local app.** Never a hosted browser app; file access stays
  server-side with backup/undo on every write.
- **Don't vendor their `dist/`** or any bulk assets from the reference repo.
- **Versioning:** **2.0.0 shipped at the end of Phase 14** (2026-08-19), with
  every V2 editor module complete. Release titles are "Medieval 2 GUI Toolkit
  vX.Y.Z — …".
  *This supersedes the original rule, which was "stay on 1.x until the Campaign
  Map Editor lands".* The reason it changed: 1.9.9 shipped a unit-transfer tool,
  and what is in 2.0.0 is a different program — a rebrand, six new editor
  modules, a shared Code View, and a whole polish pass over them. Holding the
  major number back for one unbuilt feature would have meant shipping all of
  that as a point release. **The Campaign Map Editor is now 3.0.0** (Phase 16).

## Phase index

| # | Phase | Effort | Sessions |
|---|---|---|---|
| 0 | V2 kickoff (nav, rebrand, roadmap) | S | ✅ done |
| 1 | TWCenter tutorial index | M | ✅ done |
| 2 | Reference-tool tracking infra | S–M | ✅ done |
| 3 | Split the UI monolith | M | ✅ done |
| 4 | Code View widget + line-map API | L | ✅ done |
| 5 | Home module (file discovery, no upload) | M | ✅ done |
| 6 | Strings editor (.strings.bin) | M | ✅ done |
| 7 | Trigger/condition core | S–M | ✅ done |
| 8 | Traits editor | L | ✅ done |
| 9 | Ancillaries editor | M | ✅ done |
| 10 | Minor Files module | L | ✅ done |
| 11 | Factions editor | M–L | ✅ done |
| 12 | EDB upgrades | M | ✅ done |
| 13 | EDU + Sounds audit | S | ✅ done |
| 14 | Bug-fix and polish pass | XL | ✅ done (14a–14g) |
| 14j | Replace any picture (v2.0.1) | S | ✅ done |
| 15 | 3D model viewer | L | 2 (15a, 15b) |
| 16 | Campaign Map Editor — flagship, LAST | XL | 5+ (16a–16e) |

Dependency shape: 1 and 2 are independent; 3 gates 4; 4 gates every editor
phase (5–12, 15, 16 UIs); 7 gates 8/9; 6 is reused by 11.
Phases 5–13 are mutually independent once their gates are met — sessions can
reorder them. 14 is a pass over what 0–13 built, so it comes before 15 and 16
but gates neither of them.

`unittransfer/flatrecord.py` (extracted in Phase 11) is the shared engine for
every file that is a run of `<head> <name>` records with `keyword value` lines —
rebel factions, resources and factions today. Check for it before writing a
parser: Phase 11 needed none at all.

---

## Phase 0 — V2 kickoff ✅ (done 2026-08-13)

Burger-menu navigation (module registry in one `MODES` array), full rebrand to
Medieval 2 GUI Toolkit (UI, titles, README, launcher bats with an old-name
forwarder, release naming in `build_release.py`), credits screen, this roadmap,
`STATE.md`.

## Phase 1 — TWCenter tutorial index ✅ (done 2026-08-13)

`tools/twc_index.py` → `Reference/TWCenter/INDEX.md` + `INDEX.json`: 206
documents covering all 321 files, 25 tagged `needs-manual-read` (no text layer),
per-phase reading lists, idempotent (`--check`). Both INDEX files are committed
even though `Reference/` is ignored.

<details><summary>original plan</summary>

- **Goal:** Turn `Reference/TWCenter/` into a searchable index so any later
  phase can find the authoritative tutorial for a file format in seconds.
- **Preconditions:** none.
- **Files:** new `tools/twc_index.py`; generated `Reference/TWCenter/INDEX.md`
  + `INDEX.json` (file → title, topic tags, game files covered, 1-line summary).
- **Effort:** M — one session. PDF text extraction (dev-only dependency, e.g.
  pypdf; not shipped in releases).
- **Exit criteria:** every file in the archive has an entry; entries are
  greppable by game filename (`descr_strat`, `export_descr_ancillaries`, …);
  5 spot-checked entries accurately reflect their PDF.
- **Risks:** scanned/image-only PDFs may defeat text extraction — tag those
  `needs-manual-read` rather than guessing.

</details>

## Phase 2 — Reference-tool tracking infra ✅ (done 2026-08-13)

1947 commits mirrored to `refs/upstream/editor/*`; all 298 files triaged in
`merge/PORT_MANIFEST.json` (124 port-concept, 86 skip, 68 out-of-scope, 20
audit, 0 untriaged); `tools/upstream_sync.py status|triage|sync` verified against
replayed history; baseline in `merge/SYNC_LOG.md`.

<details><summary>original plan</summary>

- **Goal:** Make Mylae's release-less `main` branch safely consumable: full
  history mirrored in our repo, every file triaged, and a diff-driven sync tool
  for his future changes.
- **Preconditions:** none.
- **Files:** git remote + `refs/upstream/editor/*` fetch; `merge/PORT_MANIFEST.json`
  (per-file: disposition `port-concept | audit | skip | out-of-scope`, target
  phase, reviewed SHA); `tools/upstream_sync.py`; `merge/SYNC_LOG.md`.
- **Effort:** S–M — one session (triage at directory granularity, file-level
  only for directories feeding V2 phases).
- **Exit criteria:** sync tool fetches, diffs `reviewed_sha..upstream/main`,
  buckets changes by disposition, flags "format knowledge may have changed" for
  `port-concept` files, appends to SYNC_LOG, bumps the SHA; manifest covers all
  ~298 files; run it clean once.
- **Risks:** his commit messages are all "File changes" — the tool must key on
  diffs only. Run the sync at the start of any phase that ports from a
  directory he's recently touched (he is actively rewriting `map/` right now).

</details>

## Phase 3 — Split the UI monolith ✅ (done 2026-08-13)

`web/index.html` 10 412 → 1 077 lines (shell + CSS + 14 `<script>` tags);
`web/js/*.js` holds the code, split by module, sharing one global scope with no
build step. Server gained `_web_asset` (path-contained) for `/js/*`. Guarded by
`tests/test_web_modules.py`: load order, every file loaded, no duplicate
top-level name (680 checked), each file parses, concatenation parses.

<details><summary>original plan</summary>

- **Goal:** Break `web/index.html` (10.4k lines) into per-module files served
  plainly by the Python server, so each later phase touches one file.
- **Preconditions:** none (do before Phase 4 lands its widget).
- **Files:** `web/index.html` (shell + shared CSS), new `web/js/core.js`
  (state, api, nav/MODES, modal, toast, filters), `web/js/<module>.js` × 6;
  `unittransfer/server.py` static serving (exists); `build_release.py` include
  list check.
- **Effort:** M — one session; purely mechanical, no behaviour change.
- **Exit criteria:** all six modules smoke-tested working (transfer plan,
  editor open/save, BMDB audit, sounds stage, sprites list, building open);
  no build step; release build still packages the whole `web/`.
- **Risks:** script-order and shared-global coupling (the `setMode` hoisting
  collision found in Phase 0 is the warning). Keep load order explicit in the
  shell; grep for duplicate top-level names before landing.

</details>

## Phase 4 — Code View widget + line-map API ✅ (done 2026-08-13)

**4b ✅.** Two more kinds in the same registry — `edb` (one `building … { … }`
line) and `bmdb` (one modeldb entry) — and both editors adopted the widget with
no second parser anywhere. `buildings.block_spans/block_fields/render_block`,
`buildings.detail(…, bl=)` so the form can be rebuilt from text that isn't on
disk yet, `modeldb.parse_entry_text/entry_spans`, and hand-edited text reaching
disk verbatim via `part["raw_block"]` (EDB) and `ModelEdit.raw_entry` (BMDB).
`render`'s edits argument is now kind-shaped — whatever that editor's save
request already sends — which is what keeps pane and save on one road.

Two things the shape of these formats forced:
* **The buildings pane owns the parse from the moment it loads.** A capability
  row carries the line it sits on, and `/api/building` counts from the top of
  the EDB while the pane counts from the top of the block. One convention, or
  the first capability edit lands on the wrong line.
* **`repair` (`⟲ Fix lengths`), only on `bmdb`.** Every modeldb string is stored
  `<length> <text>`, so a retyped path desyncs the reader. The pane refuses such
  text, naming the line and the number it should be, and the button puts it
  right — explicitly, with the numbers changing on screen.

**4a ✅.** `unittransfer/codeview.py` (kind registry, `parse` /
`render` / `unit_document`, `CodeViewError`), `edu.block_spans`, three endpoints
(`GET /api/codeview`, `POST /api/codeview/parse|render`), `web/js/codeview.js`,
piloted on the Unit Editor's EDU tab behind a remembered `</> Code view` toggle.
`EditRequest.raw_block` carries a hand-edited block to disk verbatim, with field
overrides applying on top of it. Guarded by `tests/test_codeview.py` (59 checks,
no game install needed). Measured on a 1701-unit EDU: parse 3.7 ms, render
4.5 ms, initial load 6.7 ms — the 50 ms budget holds, so 4b can adopt freely.

<details><summary>original plan</summary>

- **Goal:** One reusable component giving every editor a side-by-side GUI ⇄ raw
  code view: hover a field → its line(s) highlight; edit either side → the
  other updates live.
- **Preconditions:** Phase 3.
- **Files:** `web/js/codeview.js`; `unittransfer/server.py` endpoints
  (`GET /api/codeview` → `{text, spans: field→[line ranges]}`,
  `POST /api/codeview/parse` → re-parsed fields for edited raw text);
  span-map support in `unittransfer/edu.py` first; tests
  `tests/test_codeview.py`.
- **Effort:** L — split: **4a** widget + API + pilot on the Unit Editor's EDU
  entry; **4b** adopt in Buildings and BMDB editors.
- **Exit criteria (4a):** in the Unit Editor, hovering any stat highlights its
  EDU line; typing in the raw pane updates the GUI fields within ~500 ms
  (debounced, server-parsed); GUI edits rewrite the raw pane; a raw edit that
  doesn't parse shows the error inline and never corrupts state; span maps
  round-trip in tests. **(4b):** same behaviour in Buildings + BMDB; no
  client-side parser exists.
- **Risks:** span maps must survive our serializers exactly (comment and
  whitespace preservation); parsing on every debounce means endpoints must stay
  <50 ms on DaC-sized files — measure in 4a before adopting widely.
- **Open question:** for binary-backed editors (BMDB is a text archive — fine;
  strings.bin decodes to text) the "raw" pane shows our canonical decoded text.
  *Answered in 4b:* the BMDB pane shows the archive's own bytes, and the length
  prefixes — the one part of that text nobody can maintain by hand — get an
  explicit repair button rather than a decoded surrogate format.

</details>

## Phase 5 — Home module ✅ (done 2026-08-13)

`unittransfer/modfiles.py` (17 known files → per-module verdict, encoding sniff,
campaign title read through the strings codec), `GET /api/mod_files?mod=`,
`web/js/home.js`, `MODES` entry. A launch lands on Home whatever module you were
in last; the remembered mode is offered as "last time you were in …" rather than
jumped into. Each card carries its own mod, so Home is the one screen with no mod
picker above it. Guarded by `tests/test_stringsbin.py`.

<details><summary>original plan</summary>

- **Goal:** Replace "pick a mode first" with a landing page: detected mods,
  module launcher, and a per-mod file-discovery report — the reference tool's
  upload flow, inverted onto our server-side registry.
- **Preconditions:** Phase 3 (module file layout); their `DataFolderPicker` /
  `Home.jsx` file lists consulted via Phase 2 manifest.
- **Files:** `web/js/home.js`, `MODES` entry, `unittransfer/server.py`
  (`/api/mod_files?mod=` — which known game files exist, size, encoding),
  `unittransfer/mod.py`.
- **Effort:** M — one session.
- **Exit criteria:** launching lands on Home; each mod shows a readiness matrix
  (file present / missing / unreadable per module, localised mod title); every
  module reachable from a mod card; burger menu unchanged.
- **Risks:** none serious; keep discovery read-only and cached.
  *Landed as:* a shallow report (stat + 4-byte encoding sniff, never a parse),
  cached per mod for the session and repainted card by card so one slow mod does
  not restart the others. "Localised mod title" has no real source in M2TW — the
  closest honest one is the campaign's own in-game name
  (`UI_NEW_GAME_IMPERIAL_CAMPAIGN`, then `IMPERIAL_CAMPAIGN_TITLE`), which reads
  through Phase 6's codec: "War of the Ring (Divide_and_Conquer_EUR)".

</details>

## Phase 6 — Strings editor ✅ (done 2026-08-13)

`unittransfer/stringsbin.py` (codec), `unittransfer/strings.py` (the mod-facing
module), `codeview` kind `strings`, `/api/strings` + `/api/strings/entries` +
`/api/strings/plan|apply`, `web/js/strings.js`. **All 81 `.strings.bin` files
shipped by the three installed mods decode and re-encode byte for byte**, which
is what established the format; `tests/test_stringsbin.py` is 58 checks and runs
that sweep whenever mods are present.

The format is NOT what the reference tool's `stringsBinCodec.jsx` says, and both
of its errors destroy files:
* **the entry count is `u32`, not `u16` + padding.** Agrees below 65 536 entries
  and silently reads half a file above it — Third Age's `names.txt` is already at
  20 757.
* **a trailing *tag index* follows the entries, not a single zero word.** It is
  the tags in the source `.txt`'s original order and can dwarf the entry list
  (DaC's `export_buildings`: 480 entries, 13 482 index strings, mostly stale
  vanilla tags). Writing a zero word there truncates two thirds of the file. It
  is carried through an edit verbatim and left empty when compiling from scratch
  — a state plenty of shipped files are already in.

Also confirmed by measurement rather than folklore: the four untagged archives
(`battle`, `shared`, `strat`, `tooltips` — style word 1) hold bare strings with
no index section at all; tags are code-point sorted in all 69 tagged files, so a
new tag is inserted in that order; and the game's own compiler folds continuation
lines, trims tabs and line breaks but **not** spaces, and reads `\n` as a line
break (3393 of 3395 entries reproduced against a `.bin` the game itself wrote).

`cleaner.refresh_strings_bin` now recompiles a cache from the `.txt` a job just
wrote instead of deleting it, falling back to deletion when there is nothing to
compile from. `Mod.loc` / `building_loc` / `faction_names` read through the codec
when the `.txt` is absent, so a mod that ships only compiled text still shows
real names.

<details><summary>original plan</summary>

- **Goal:** Read and write `.txt.strings.bin` natively (keys + UTF-16 values),
  ending the "delete the .bin and let the game rebuild it" workaround.
- **Preconditions:** Phases 3, 4 (ships with Code View from day one).
- **Files:** new `unittransfer/stringsbin.py` (codec, from the BinEditor v3.0
  format their `stringsBinCodec.jsx` cites; verify against TWCenter index),
  `tests/test_stringsbin.py`, `/api/strings/*` (list/entry/plan/apply with
  backup+undo), `web/js/strings.js`.
- **Effort:** M — one session.
- **Exit criteria:** decode→encode of untouched files is byte-identical for
  every `.strings.bin` in the test mods; edit/save/undo works; existing
  `cleaner.py` .bin-deletion path becomes unnecessary for edited files;
  localised-name lookups elsewhere can read through this codec.
- **Risks:** encoding corner cases (odd counts, empty values) — the
  byte-identical round-trip test is the gate.
  *Landed as:* the gate held. The ground truth was alpaca's converter
  (`Reference/TWCenter/--- TOOLS n RESOURCES ---/strings_bin_converter_0_7_2/`),
  which has the 32-bit count the JSX lacks, plus a sweep over the real files for
  everything alpaca's script also stops short of.
- **Open question, answered:** the "raw" pane for a binary-backed editor. A
  strings entry IS one `{tag}text` line of the `.txt` beside it, so the pane
  shows that — the format modders already write, not a decoded stand-in. Untagged
  archives get no pane, because that shape does not exist for them.

</details>

## Phase 7 — Trigger/condition core ✅ (done 2026-08-13)

`unittransfer/triggers.py` (grammar, splice editor, spans),
`tools/trigger_vocab.py` → `unittransfer/data/trigger_vocab.json` (413
conditions, 217 events), `GET /api/triggers/vocab?mod=`, `web/js/triggerui.js`,
`tests/test_triggers.py` (49 checks). **All 4974 triggers / 20 013 conditions in
the six installed EDCT and EDA files parse with zero unknown constructs and the
files come back byte for byte.**

The vocabulary is generated, never written by hand, from the Docudemons
spreadsheet (`Reference/TWCenter/M2TW_Ultimate_Docudemons_5.3.xlsx`) plus a
measurement pass over every trigger file on the machine. The spreadsheet supplies
each condition's description and — the part that pays for itself — which data
types it **requires** and which each event **exports**; the mods supply the
argument *shape* of each term (`Trait` is `name op num`), because the spreadsheet
describes parameters in prose and 20 000 real clauses do not.

That pairing gives `triggers.check`: a condition whose required data type its
event does not export can never be true, and the trigger silently never fires —
invisible when reading the file. It found **2 real cases** in the installed mods
(`SettlementBuildingExists` under `PostBattle` and under `CharacterComesOfAge`).
Getting there needed two corrections to the source data: requirements can be
disjunctive (`Religion` accepts any one of six types) and the spreadsheet spells
two types more than one way — without both, the check cried wolf 104 times.

**Their `conditionDefs.jsx` is not ported** — see `merge/audit-trigger-vocab.md`.
Of its 78 conditions, 20 exist; of its 82 `WhenToTest` events, 41 exist, and the
misses are not typos but a whole invented `On` prefix (`OnCharacterTurnStart` for
the engine's `CharacterTurnStart`) plus plausible-sounding conditions the engine
has never had (`IsSpy`, `IsHeir`, `SettlementLevel`). A picker built from it
writes triggers that never fire.

`web/js/triggerui.js` is a component with a host contract, not a mode: its hosts
are Phase 8b and Phase 9, exactly as the dependency shape says. It draws one
typed box per token of a term's measured shape, fills `name` boxes from that
mod's own traits / ancillaries / factions / cultures / buildings, and shows the
never-fires warning live as the event changes. Its requirement test is checked
against the Python one under `node`.

<details><summary>original plan</summary>

- **Goal:** One Python grammar + one GUI builder for the `Trigger / WhenToTest /
  Condition / Affects` language shared by traits, ancillaries and (later) the
  script editor.
- **Preconditions:** Phase 3; their `shared/conditionDefs.jsx`,
  `TriggerEditor.jsx`, `WhenToTestSelect.jsx` as the vocabulary reference,
  TWCenter docs as ground truth.
- **Files:** new `unittransfer/triggers.py` + `tests/test_triggers.py`;
  `web/js/triggerui.js` (builder component: event picker, condition rows with
  typed operands, localised labels).
- **Effort:** S–M — one session.
- **Exit criteria:** parses every trigger in both test mods' EDCT + EDA files
  with zero unknown-construct warnings (unknowns are listed, not dropped);
  serializes back byte-identical; vocab served via API.
- **Risks:** condition vocabulary is huge and partly version-specific — store
  it as data (JSON) derived from their defs + TWCenter, not as code.
  *Landed as:* data, but derived from TWCenter and from the mods — their defs
  turned out to be too wrong to derive anything from. "Localised labels" has
  nothing to localise: condition and event names are engine identifiers with no
  text entry anywhere, so the labels are the identifiers, with the Docudemons
  description as the hint and this mod's own usage count beside each one.

</details>

## Phase 8 — Traits editor ✅ (done 2026-08-13)

**8b ✅.** `web/js/traits.js` + `MODES` entry, `GET /api/traits` + `/api/trait`,
`POST /api/traits/plan|apply`, and the traits half of `unittransfer/traits.py`
(`overview`, `detail`, `plan`, `apply`). **`web/js/triggerui.js` has its first
host**: the triggers whose `Affects` names the open trait are listed under it,
each one in the shared builder, and their edits ride in the same save.

A save can touch three things and does them as one job, because they fail
together: the trait block, the triggers hundreds of lines below it in the same
file, and the `export_VnVs.txt` keys its levels name. Backups and undo cover all
of them — `tests/test_traits.py` creates a trait, edits it, builds a trigger for
it in the GUI's shape, deletes it and undoes the lot against a scratch mod.

Four rulings the format forced on the UI:

* **A level is a key and the words the player reads, side by side.** Taken from
  their editor (`merge/audit-traits.md`) — the key is in the EDCT and the wording
  is in `export_VnVs.txt`, and sending someone to another module to write the
  words would be the tool getting in the way. A key the file has not got is
  created; one whose wording was retyped is rewritten in place, continuation
  lines and all, and the compiled archive is rebuilt in the same save.
* **Deleting a trait takes its triggers with it.** A trigger left `Affects`-ing a
  trait that no longer exists is the guide's "Trait not recognized". A trigger
  that fed *only* this trait is removed whole; one that also feeds others loses
  just that line, so their points survive. The preview says which.
* **Renaming a trait is refused everywhere except at creation** — the name is the
  key its own triggers, other traits' `AntiTraits`, the EDA and `descr_strat` all
  point at. Same ruling as a building line.
* **The form sends every box on save, so an unchanged value must not rewrite its
  line.** A list is compared as a list: `greek,  noldor` and `greek, noldor` are
  the same value, and 128 real traits are written the first way. All 1457 survive
  a full-form save unchanged.

**8a ✅.** `unittransfer/traits.py` — the definition half of
the EDCT, sitting on `triggers.split_lines` so both halves of the file count
lines from the same place. **All 1457 traits / 3021 levels in the three installed
EDCTs parse with zero unknown constructs and the files come back byte for byte**;
`tests/test_traits.py` is 88 checks. Code View kind `traits` registered (spans
per header line, per level, per level field and per `Effect`), with
`codeview.trait_document` and a rename refusal — the trait name is the key its
own triggers' `Affects` lines, other traits' `AntiTraits`, the EDA and
`descr_strat` all point at.

Three things the format forced, all from Squid's EDCT/EDA guide
(`Reference/TWCenter/[Modding] RTW  Guide for Traits and Ancillaries.pdf`) and
confirmed against the real files:

* **The header's line order is load-bearing.** `Characters` must be the line
  under `Trait`, and the optional lines after it have a fixed order. Get it wrong
  and the engine does not report a bad trait — it stops recognising every trait
  defined *after* it and crashes hundreds of lines away. So an added header line
  is inserted at its canonical position, never appended, and `check` reports a
  file that already has it wrong.
* **Absent is not empty.** `Hidden` is a whole line; an optional field edited to
  nothing deletes its line rather than writing a bare keyword. The four required
  lines (`Characters`; `Description` / `EffectsDescription` / `Threshold`) are
  refused when blanked, because the alternative is writing a file that stops the
  game loading.
* **`check` reads both halves at once.** A trait name is what thousands of
  trigger lines point at, so `check_file(tf, trigger_file)` catches an `Affects`
  naming a trait that does not exist. On the installed mods it found **14 real
  findings in 1457 traits**: DaC's `HeroAbility_GALADRIEL` is missing its `Trait`
  line and has been absorbed as a second level of `HeroAbilitySilvanElf` at the
  same threshold, so it can never appear; two DaC triggers write
  `Affects Trait SuppliedBySea …` and the points go nowhere; and 11 traits use a
  comma-separated `Characters` list, where only the first type ever works.

Localised names come from `data/text/export_VnVs.txt` (flat `{tag}text`, read
through Phase 6's codec when a mod ships only the compiled archive) — a trait has
no name of its own, so `traits.label` shows its first level's:
"Race: Decayed Man (Nazgul)".

- **Goal:** Full `export_descr_character_traits.txt` editor — traits, levels,
  effects, triggers — with localised names and Code View.
- **Preconditions:** Phases 4, 7 (and 6 for localised trait names).
- **Files:** **8a:** `unittransfer/traits.py` + tests (parse/serialize, spans).
  **8b:** `web/js/traits.js` + `MODES` entry + `/api/traits/*` plan/apply.
- **Effort:** L — parser and UI are a session each.
- **Exit criteria (8a):** ✅ round-trip byte-identical on both test mods; span
  maps for Code View. **(8b):** ✅ create/edit/delete a trait end-to-end with
  backup+undo; anti-traits and thresholds editable via GUI; their editor's
  field coverage matched or exceeded (`merge/audit-traits.md` — matched on
  fields, exceeded on checks, Code View, undo and the trigger half);
  `web/js/triggerui.js` gets its first host.
- **Risks:** EDCT files in big mods are enormous — list virtualisation matters
  (we already do this for 1700-entry dropdowns).

## Phase 9 — Ancillaries editor ✅ (done 2026-08-13)

`unittransfer/ancillaries.py`, `web/js/ancillaries.js`, `GET /api/ancillaries` +
`/api/ancillary`, `POST /api/ancillaries/plan|apply`, code view kind
`ancillaries`, and `/icon?kind=ancillary&image=` for the pictures. **All 1134
ancillaries in the three installed EDAs parse with zero unknown constructs, come
back byte for byte, and re-render to themselves under a full-form save**;
`tests/test_ancillaries.py` is 85 checks.

Because EDA and EDCT are one language, the second editor was mostly extraction
rather than new code — and that is the shape the next few phases should keep:

* **`unittransfer/keyblock.py`** now owns "a block of `Keyword value` lines whose
  order the engine cares about, edited by splices": the splice, the
  insert-at-its-place rule, the flag keys, the required-key refusal, the
  list-compared-as-a-list rule and the line-ending-preserving I/O. Traits was
  rewired onto it first, and its 117 checks are what proved the extraction.
* **`triggers.edit_section` / `orphaned_by` / `strip_effect_lines` / `new_block` /
  `append_block`** now own the trigger half of a save, so both editors delete
  their own record's triggers the same way. `Affects` and `AcquireAncillary` are
  the same problem with a different keyword.
* **`stringsbin.upsert_txt`** owns writing `{tag}text` back into a localisation
  file, continuation lines and all — `export_VnVs.txt` for traits,
  `export_ancillaries.txt` for ancillaries.

Four things EDA does that EDCT does not:

* **`Type` and `Transferable` are not in the guide at all** — that guide is RTW's,
  both lines are M2TW's, and both are present in all 1134 real ancillaries as
  lines two and three. `Type` groups them (a character holds one per type) and is
  free-form: the mods use **350 distinct values**, which is why the reference
  tool's 17-value dropdown is not ported (`merge/audit-ancillaries.md`).
* **Two hardcoded limits, both silent**: more than 3 `ExcludedAncillaries` is an
  errorless crash, more than 8 `Effect` lines makes the ancillary impossible to
  gain from a trigger (TWCenter, *List of Hardcoded Limits*).
* **An ancillary has a picture**, resolved from `data/ui/ancillaries` then the
  vanilla UI and decoded through the existing icon cache. **DaC names two that
  nobody shipped** — a blank slot in game and nothing in any log.
* **Its own name is a text key**, unlike a trait's, so the box beside the name is
  what the player reads.

- **Exit criteria:** ✅ round-trip byte-identical; ✅ edit end-to-end with undo;
  ✅ image references resolved and previewed like unit cards.

## Phase 10 — Minor Files module ✅ (two sessions, done 2026-08-14)

**10b ✅ (done 2026-08-14).** `web/js/minorfiles.js` + a `MODES` entry, `GET
/api/minor` + `/api/minor/record`, `POST /api/minor/plan|apply`, the five code
view kinds wired into `/api/codeview`, and the editor half of
`unittransfer/minorfiles.py` (`overview`, `detail`, `vocab`, `plan`, `apply`).
One tab strip over five files, because the parse layer already made them three
shapes. `tests/test_minorfiles.py` is 160 checks and drives create / edit /
delete / undo against a scratch mod.

Three rulings the files forced, and all three are refusals:

* **Two of the five tabs are edit-only, and the format says so.** The engine's
  resource list is closed — all three installed mods ship the same 28 names and
  a `type` it does not know is read and ignored — so "create a resource" would be
  a button that writes a line nothing reads, and deleting one leaves
  `descr_regions.txt` placing a resource nothing defines. A culture is eleven
  settlement models and cards, a fort, a port ladder, a watchtower and six
  agents; nothing a text editor conjures, and deleting one orphans every faction
  whose `culture` line names it. Both refusals are shown where their buttons
  would be, with the reason.
* **The resources tab shows its name and refuses to write it.** `text/strat.txt`
  compiles to a **style-1 archive: 1307 bare strings with no tags at all**, read
  by position, and identical in length across all three mods. Appending a line
  shifts every index after it. Our own `stringsbin.refresh_from_txt` already
  refuses to rebuild an untagged archive, so the tab points at the Strings
  module, which edits that file by position. The other two localised tabs
  (`rebel_faction_descr.txt`, `religions.txt`) are style 2 and written normally.
* **A religion save is four files or it is nothing.** The block, the
  `religions { … }` list, `descr_religions_lookup.txt` and `text/religions.txt` —
  one job, one backup set, one undo, because a religion that reaches three of
  them half exists. Measured on the lookup: the three mods disagree about its
  *order* (Third Age 3 has islam and orthodox the other way round from its own
  list) and its *contents* (Third Age 6 lists a `wicked` that no longer exists)
  and all three run, so a save keeps it in step **by name only** — appending or
  dropping a line, never reordering one.

Two things fixed on the way, both outside this phase's own code and both real:

* **The Code View widget's GUI→pane arrow was never wired in Traits or
  Ancillaries.** Its own header comment promises "edit a box, the text is
  re-serialised by the server and redrawn", and `cvFromGui` was called only by
  the unit and strings editors. Measured live: typing in an ancillary's Type box
  left the pane showing the old text. All three editors now call it.
* **`config._write_json` was not atomic, and it cost real 404s.**
  `Path.write_text` truncates then writes; the server is threaded; any request
  resolving a mod inside that gap read a truncated `settings.json`, got `{}`, and
  concluded the machine had no Medieval II install — so every mod vanished for
  that instant. Invisible because the page's GET helper retries. Caught as a 404
  on `/api/codeview` the moment an editor saved the `code_view` toggle and opened
  a record in the same breath. Now a temp file plus `os.replace` (with a retry,
  because Windows refuses the rename while a reader has the file open) and an
  mtime-gated read cache, so `get_med2_root` stops opening the file on every mod
  resolution. Stress-tested: 24 000 concurrent reads against 1000 writes, zero
  torn reads and zero failed writes; it was 23 torn reads with the rename alone.

Single source of truth landed as the exit criteria asked: `edbvocab.religions` /
`cultures` / `resources` were three regexes beside the module that edits those
files, and now call `minorfiles.religion_names` / `culture_names` /
`resource_names`. `buildings.RELIGIONS` — a hardcoded vanilla five, and DaC has
ten of which none is `pagan` — is now `VANILLA_RELIGIONS`, used only as the
fallback when a mod has no `descr_religions.txt`. Home's readiness matrix gained
the Minor Files module and, while there, the Traits and Ancillaries rows that
phases 8b and 9 never added.

**10a ✅ (done 2026-08-14).** `unittransfer/minorfiles.py` — five files, and
they turned out to be **three shapes, not five**, which is why they are one
module: flat `keyword value` records on `keyblock` (rebel factions, resources),
brace blocks (religions, cultures), and indented sections of bare words
(`descr_names.txt`). **All 15 real files in the three installed mods parse with
zero unknown constructs, come back byte for byte, and every record re-renders to
itself under a full-form save**; `tests/test_minorfiles.py` is 133 checks. Five
new Code View kinds (`rebels`, `resources`, `religions`, `cultures`, `names`),
all five refusing a rename in the text pane — every one of these names is a key
`descr_regions.txt` or `descr_sm_factions.txt` points at.

Three things the formats forced:

* **A campaign file's gap between keyword and value is data.** These files are
  laid out in tab columns, so `keyblock` gained `head_prefix` / `sub_value` /
  `sub_tokens` and `edit_keys(align=True)`: a rewritten value keeps its column,
  and a new line copies the gap of the line above it. The EDCT/EDA path is
  untouched — those files really do use one space.
* **A culture record does not end at its closing brace.** The forts, ports,
  watchtowers and six agent lines come after it and belong to it, so a record
  ends at the next `culture` line.
* **Art references are not checked.** A pip or a settlement card can live in the
  game's `.pack` archives, which the toolkit cannot read. Checking anyway gave 78
  findings across three mods, 77 of them noise.

**Their four minor-file parsers are not ported** — see
`merge/audit-minorfiles.md`. This is the first audit where the reference
implementation is not merely lossy but wrong about the format: a religion's key
is `pip_path` inside a brace block, not their `icon` / `pip` / `anti_pip`; a
resource's model line is `item`, not their `model`; and their rebel serialiser
appends `, <exp>, <count>` to every `unit` line, when not one of the 215 real
`unit` lines has a comma and the unit types have spaces in them. Two of their
serialisers write files the engine will not load at all.

What the checks found in real mods: **Third Age 3 disagrees with itself about its
own religions** three ways (a duplicate `heretic` block, a name missing from the
`religions` list, three stale entries in `descr_religions_lookup.txt`); DaC drops
`moot_and_bailey` from 7 of its 10 cultures and `fortress` from one; and there
are 97 duplicate character names across the three `descr_names.txt` files.

- **Goal:** One tabbed module for the small campaign files: rebel factions,
  religions, cultures, resources, character names.
- **Preconditions:** Phase 4; Phase 6 for localised names.
- **Files:** **10a:** ✅ `unittransfer/minorfiles.py` + `tests/test_minorfiles.py`
  + the five Code View kinds. **10b:** `web/js/minorfiles.js` + `MODES` entry +
  `/api/minor/*` + `plan`/`apply` (the backup+undo save, still to write — copy
  `ancillaries.plan/apply`).
- **Effort:** L in total; each session M.
- **Exit criteria:** ✅ every tab round-trips byte-identical; ✅ rebel-faction unit
  pickers use localised unit names (453 of them on Third Age 3, resolved the way
  every other unit picker resolves them); ✅ religions/cultures referenced by
  Buildings mode resolve from here instead of ad-hoc parsing (single source of
  truth — `minorfiles.culture_names` / `religion_names` / `resource_names` are
  that source, and `edbvocab` now calls them).
- **Risks:** `descr_names.txt` is huge and encoding-sensitive; treat as its own
  tab with lazy load. *Landed as:* 25 903 names in Third Age 6, read as sections
  per faction so a pane loads one faction rather than the file. Encoding is
  Latin-1 like every other campaign file, which is what makes the byte-exact
  round trip a promise rather than a hope.

## Phase 11 — Factions editor ✅ (done 2026-08-14)

`unittransfer/factions.py`, `web/js/factions.js` + a `MODES` entry,
`GET /api/factions` + `/api/faction`, `POST /api/factions/plan|apply`, Code View
kind `factions`. **All 90 factions in the three installed mods parse byte-exact,
re-render unchanged under a full-form save, and produce zero findings**;
`tests/test_factions.py` is 83 checks.

**It needed no parser.** `descr_sm_factions.txt` is the fourth file to be a run
of `<head> <name>` records with `keyword value` lines under it, so it is a
`Shape` and nothing else — which is what STATE.md predicted and what made the
first hour of this phase a measurement rather than a parser. That made the
extraction worth doing: the flat-record engine moved out of `minorfiles.py` into
**`unittransfer/flatrecord.py`**, with `minorfiles` re-exporting every name it
published so its 160 checks were untouched. A fourth caller is the point at
which "the shape the minor files share" stops being a fact about the minor files.

What 90 real factions decided:

* **The line order is canonical and nobody disagrees.** Ten distinct orderings
  appear across the three mods, and a topological sort over all of them finds
  **zero conflicts** — so `ORDER` is derived, not guessed, and every observed
  ordering is a subset of it (a test asserts exactly that).
* **`has_family_tree` is not a boolean.** `yes`, `no` or `teutonic`, and **24 of
  the 90 say `teutonic`**. A checkbox — the obvious GUI — would have written
  `no` over every one of them, so it is a three-way picker with the count in the
  hint.
* **The head line can carry a modifier**: `faction egypt, spawned_on_event`, and
  `shadowing` / `shadowed_by` naming another faction (five real cases). The slot
  is the part before the comma, and `slot_of` is why nothing here ever compares
  a whole head line to a faction name.
* **The localised name matters more here than anywhere else in the toolkit.**
  Mods reuse vanilla slots wholesale — DaC's `sicily` is the Kingdom of Gondor,
  Third Age 6's `milan` is Rohan — so a list of slots is a list of the wrong
  countries. Names are written back to `text/expanded.txt`, whose tag is the
  slot in **UPPER CASE** (`{SICILY}`); `Mod.faction_names` lower-cases on read,
  which is right for reading and would have created a dead second entry on write.
* **No create, no delete.** A faction slot lives in eight or nine files at once
  and TWCenter has a step-by-step tutorial for adding one precisely because one
  file is never the job. Same ruling as the cultures tab in Phase 10b.

**The "banner/symbol textures displayed" exit criterion was written on a wrong
premise and is replaced.** This file names no faction texture at all: `symbol`
and `rebel_symbol` are `.CAS` **3D strat models** (Phase 14's business, not an
image), and `loading_logo` names a `.tga` that **not one of the 90 real factions
ships unpacked** — all 90 are inside the game's `.pack` archives, which the
toolkit cannot read. `standard_index` and `logo_index` are indices into banner
and UI sprite sheets, and neither appears in any `data/text/*.txt`. So the paths
are shown, a found one is marked (symbols often are: 59/90), and an unfound one
is never called missing — Phase 10a's ruling about pips and settlement cards.
What IS visual and IS in this file is the two map colours, and those got what
they deserved: a swatch on every row and a colour picker in the form.

One bug found on the way, in the shared machinery rather than here:
**`keyblock.edit_keys(align=True)` put an inserted line in the wrong column.**
It copied the *gap string* of the record's first line, which only lands right
when the two keywords are the same length — inserting `can_build_siege_towers`
with `culture`'s four tabs pushed its value five columns past everything else.
Measured: at a 4-space tab, **1731 of the ~1800 value-bearing lines in the three
real rosters start in column 28**, so the gap is a *column*, not a string. Now
`pad_to_column` tabs to the column the record itself uses, and a keyword too
long to reach it takes a single tab, which is what the real long ones do.

Single source of truth again: `buildings.faction_cultures` was a fifth ad-hoc
reader of this file (it got the head-line comma right by accident) and now calls
`factions.faction_cultures`.

- **Exit criteria:** ✅ faction records fully editable with round-trip fidelity;
  ✅ colours shown and edited, art paths resolved-when-findable and never
  falsely reported missing (replaces "banner/symbol textures displayed", which
  the format does not support — see above); ✅ name edits flow through Phase 6's
  codec into `expanded.txt`.
- **Risks:** faction records cross-reference many files (strat, win conditions)
  — *landed as:* out-of-scope references are shown read-only, and the ones this
  module CAN check (culture, religion, horde units) are checked against the
  mod's own `descr_cultures` / `descr_religions` / EDU.

## Phase 12 — EDB upgrades ✅ (done 2026-08-14)

`buildings.plan_new_tree` / `new_tree_text` / `icon_slots` / `upgrade_name`,
`TREE_PREFIXES` + the `TREE_ACTIONS`/`TREE_REFUSED` pair, a `create` key on
`/api/buildings/plan|apply` (no new endpoint — a create is a building save),
`web/js/buildings.js` gaining the tree list, the new-tree dialog and a grouped
capability picker, and `merge/audit-edb.md`. `tests/test_edb_tree.py` is 79
checks over **277 real building lines / 1099 levels / 771 upgrade entries**.

Four things the measurement decided:

* **A tree is two files or it is nothing.** The EDB block and three text keys per
  level go in one job with one backup set — a level short of `{x}`, `{x_desc}` or
  `{x_desc_short}` crashes the game at the construction panel, and all 1099 real
  levels have all three. A mod with no `text/export_buildings.txt` is refused
  rather than half served. The cards are the third thing and they are **art**:
  listed with their paths, never written, and a blank one is never called a fault
  (Phase 10a's ruling).
* **The levels chain forward, and that is not a style choice.** All 771 upgrade
  entries in the three mods point at a level listed *after* them on the `levels`
  line — none backwards, none at itself, none at a level its line has not got.
  The reference tool's upgrades picker offers every level except the current one,
  so it will happily write the one shape no real file has.
* **A level name is the EDB's one global namespace.** Two lines cannot share one:
  the text keys, the icon stems and every settlement plan are keyed on it, so a
  new tree reusing one is refused before either file is touched. Same for a line
  named after an existing level.
* **The two limits in TWCenter's hardcoded-limits note are RTW-era.** "Max 64
  building trees" — Third Age 3 has 117 and DaC 136, both running, so no warning.
  "Max 9 levels per tree" — true of vanilla, and Third Age 6's `core_building` is
  **51** deep on M2TWEOP, so passing nine is *said*, with the number, not refused.

Also landed: **an upgrade's own clause is editable.** 41 of the 771 entries are
`wooden_wall requires factions { … }` and ours showed that as a read-only chip;
the row now has the same ✎ picker every other clause has, writing back into the
same string (`detail()` gained `upgrade_paths` beside the strings a save sends,
so nothing else changed shape). And the capability picker is grouped: 60 keywords
in nine `<optgroup>`s with the engine's accepted range beside each, up from 49 in
one flat alphabetical list. Eleven keywords came from the reference tool's
capability sheet and **none of them is used by any installed mod** — which is the
point: a capability keyword is engine vocabulary, not a fact about a mod, so this
is the one place where adopting their hardcoded list is right (the check runs the
other way too — all 48 keywords the real files use were already ours).

<details><summary>original plan</summary>

- **Goal:** Fold the reference tool's good EDB ideas into our Buildings module:
  collapsible building-tree list as an alternative to the gallery, an
  "add new building tree" flow, and any field-layout wins from their editor.
- **Preconditions:** Phase 4 (Buildings already has Code View via 4b).
- **Files:** `web/js/buildings.js`, `unittransfer/buildings.py` (new-tree
  scaffolding: EDB block + levels + `export_buildings.txt` strings + icon
  slots), tests.
- **Effort:** M — one session.
- **Exit criteria:** ✅ list/gallery toggle persisted (`bld_browse`; the gallery
  stays, because a building card is how anyone recognises a building they have
  seen in game and their editor has no art at all); ✅ creating a new tree
  produces a mod that loads — `line_checks` on the created line is clean and a
  whole-mod check run is no worse than before it; ✅ `merge/audit-edb.md`.
- **Risks:** new-tree creation touches EDB + strings + icons at once — reuse
  the transfer engine's plan→preview→apply pattern. *Landed as:* exactly that,
  and through the existing `/api/buildings/plan|apply` rather than a new pair —
  a create is a building save whose line does not exist yet, so it gets the
  backup, the undo and the `.strings.bin` recompile for free.

</details>

## Phase 13 — EDU + Sounds audit ✅ (done 2026-08-18)

- **Goal:** Systematically compare their EDU fields/dropdowns and SoundEditor
  against ours, adopt the small wins, and write down the verdict.
- **Preconditions:** Phase 2 (manifest points at the files).
- **Files:** `merge/audit-edu-sounds.md`; small diffs to `unittransfer/vocab.py`
  / `edu.py` / `sounds.py` and editor JS where adopted.
- **Effort:** S — one session.
- **Exit criteria:** the audit document lists every field/dropdown they have,
  ours beside it, verdict (have-better / adopted / rejected-why); adopted items
  landed with tests.
- **Risks:** their vocab lists are hardcoded vanilla — adopt *fields*, derive
  *values* from the mod as we already do.
- **Outcome:** `merge/audit-edu-sounds.md`, measured over **1756 real units**
  (Kingdoms vanilla + Divide and Conquer EUR + Third Age Reforged). Nothing was
  adopted from their code: they have no field we lack (`card_info_pic_dir` is in
  no real file), and their value lists are RTW-era or invented in nine closed
  slots out of eleven. What the audit *did* produce is ours — banner names now
  come from the mod's own `descr_banners_new.xml` (`vocab.banner_names`, three XML
  sections onto the three EDU lines, and into `defined` so an undeclared banner is
  flagged), and two silent rewrites in the guided editor were fixed
  (`stat_mental`'s fourth token, `formation`'s trailing comma). Their SoundEditor
  is a different file family which its own parser destroys — 0 of 32 round-trip —
  so the `descr_sounds_*.txt` **coverage gap is recorded, not closed**.

## Phase 14 — Bug-fix and polish pass (nine sessions)

One batch of defects and small features from real use of the finished modules,
plus the leftovers `merge/audit-codebase.md` recorded and did not fix. Nothing
here is new ground: it is the pass that makes Phases 0–13 feel finished before
the two big ones. Reported items are grouped by **where the fix lives**, not by
where they were noticed, and every one is written down — a session may re-scope
an item or find it already fixed, but may not drop one silently.

- **Preconditions:** none beyond the modules themselves. Independent of 15 and 16.
- **Effort:** XL overall; each sub-phase below is one session with its own exit.
- **Ordering:** 14a first — it is the only sub-phase holding a broken core flow.
  The rest can be reordered freely. (14g was 14c's last item until it was measured
  at 115 hits and given a session of its own. 14i came after the release, from
  using it.)

### 14a — Loading, mod switching, and the two Transfer failures ✅ (done 2026-08-18)

- **Goal:** A mod switch is instant and safe, and Unit Transfer works on Third
  Age Reforged.
- **Items:**
  - **Switching mods mid-load does not interrupt the load.** `api.get`
    (`core.js:34`) has no `AbortController` and retries four times with backoff,
    so picking another mod leaves the first mod's requests in flight and the
    screen ends on `TypeError: Failed to fetch`. Give the loader a request
    generation: a response from a superseded generation is dropped rather than
    painted, and the requests behind it are aborted.
  - **DaC to Reforged and back does not switch the units** — the grid keeps the
    old mod's, and Settings cannot be clicked while it is happening. Same area;
    confirm whether it is one bug or two.
  - **Reforged unit cards fail to convert and show black**, and pressing Transfer
    unit greys the screen instead of opening the composer. Find out where:
    `icons._decode_to_png` (`icons.py:127`) swallows a decode failure and returns
    a placeholder, so a card format Pillow reads differently would look exactly
    like this. The grey screen is a second symptom — an exception thrown while
    building the composer leaves the overlay up with no dialog inside it, which
    should never be a reachable end state.
  - **A loading bar at the bottom of every menu** while the module is still
    fetching, showing real progress rather than a spinner. One shared widget in
    `core.js`, driven by the loads the modules already await.
- **Files:** `web/js/core.js`, `web/js/transfer.js`, `unittransfer/icons.py`,
  `web/index.html` (bar styling), tests.
- **Exit criteria:** switching mods during a load never shows a fetch error and
  never paints stale data; every Reforged unit card decodes, as a measured count
  in the test; the composer either opens or says why, never greys out; the bar
  appears in every mode whose load runs longer than about 200 ms.

**Outcome — it was one bug wearing four masks.** Black unit cards, "TypeError:
Failed to fetch", the grey composer and the dead Settings button were all the
same incident: **the server was shutting itself down while it was being used.**

The chain, measured on this machine:

* The icon cache lived in `.cache/icons` **next to the app** — which here means
  inside OneDrive. Reading 400 cached icons back out of it: **137 of them failed
  outright** with `OSError: [Errno 22]` (a dehydrated cloud placeholder), and of
  those that did read, the median was 12.6 ms and **the worst was 79 seconds**.
* An unreadable entry surfaced as a blank PNG, because `_icon` catches everything
  and paints a blank rather than 500ing. A screen of those is a grid of **black
  cards** — indistinguishable from "the conversion failed".
* The slow ones filled the browser's ~6 connections to one origin. The page's
  heartbeat is a `setInterval` sharing those connections, so it stopped getting
  through: the server's own log shows heartbeats every 4 s, then nothing for 150
  seconds, then `browser idle >150s — shutting down`. **The dead-man watchdog
  killed a live session.** Everything after that is what a dead server looks
  like from a page that is still open.

Fixed at each link, with `tests/test_liveness_and_cache.py` (21 checks) on the
two that are ours to promise:

| | before | after |
|---|---|---|
| icon cache | inside the synced app folder | `config.cache_dir()` → `%LOCALAPPDATA%` |
| unreadable cache entry | served as a blank (black card) | treated as a miss, re-decoded from the mod's own TGA |
| proof of life | the heartbeat alone | **any** request (`note_request`), heartbeat still proves the page rendered |
| dead-man window | 150 s | 300 s |
| `Registry.get()` per request | ~4 ms (folder scan + 12 stats, under one lock) | **0.7 µs** on the hot path, disk re-checked at most once a second |
| unit-card lookup | **224,712 globs** to answer one `/api/units` | one listing per folder, keyed on its mtime |
| `/api/units` for DaC (916 units) | 4189 ms | **350–420 ms** |
| 427 Reforged cards, warm | 6.0 s, 137/400 unreadable | 3.3 s, 0 failures |

The client half: `api.get`/`api.post` take an abort signal, every load takes a
generation (`newLoad()` / `loadStale()`), and a response from a superseded load
is dropped instead of painted — a fast DaC→Reforged→DaC now ends on DaC's 916
units every time. `openComposer` no longer raises the overlay before it has
anything to put in it, so a failure there says what failed and offers a retry
instead of greying the screen. And the **loading bar** is driven by the API
client itself (`loadbar` in core.js), so every module has one without a line of
its own code: it appears after 180 ms, names what it is reading, sweeps while a
single request is out and becomes a real fraction once there is more than one.

Also swept up here because it is the message this fix changes: the five places
still naming `Launch-Unit-Transfer.bat` (14c's third item) now name the real
file.


### 14b — The log, and undo/redo ✅ (done 2026-08-18)

**Outcome.** All five items landed, with `tests/test_log_and_activity.py` (26
checks) over the two halves that are ours to promise.

* **The log opens in 51 ms instead of 571** (and instead of minutes on a cold
  `config/`): `/api/log` is now `log_page(mode, offset, limit)`, newest first,
  40 to a page. 1.1 MB of JSON became 29 KB and 600 KB of markup became 40 KB.
  `manifest` is dropped from a listed entry — it is undo's own bookkeeping and
  the page never used it — and a summary over 4000 characters is cut with a note
  saying where the rest is (one real entry is **310 KB** on its own).
  `newer_count` is computed server-side, because "Revert to here (N)" was the
  only reason the page ever needed the whole log.
* **A mode filter**, as tabs with counts over the whole log, showing only the
  modes that have entries: here that is Everything 480, Traits 205, Minor files
  120, Ancillaries 81, Transfers 37, Factions 30, BMDB 6, Buildings 1.
* **"Save diagnostic log" moved into the log panel's footer**; Settings now
  points at the log instead of carrying its own copy of the button.
* **Ctrl+Z / Ctrl+Y were never wired for five of the editors.** The handler was
  live the whole time — `undo.js` had scopes for the building editor, the unit
  and BMDB editors, the transfer composer and Sounds, and nothing for **Traits,
  Ancillaries, Factions, Minor Files or Strings**, all of which were built after
  it. They all keep a deep-cloned working copy at `state.<x>.d.w` and repaint
  from it, which is exactly the shape the snapshot stack wants, so each needed a
  scope and a baseline: `undoReset()` at the point the working copy appears
  (without it the *first* edit becomes the baseline and Ctrl+Z has nothing to go
  back to), plus `undoBaseline()` for Strings, which reloads rows for paging and
  searching without changing what is being edited. Verified one field at a time
  in all five: undo restores the old value, redo puts the new one back.

* **The log records what the person did, next to what the tool did.** Half of
  "what happened" was missing: every file written was in there and not one of the
  clicks that led to it, so reading it back meant inferring intent from effects.
  `POST /api/activity` takes batched UI events — capped at 60 an event, truncated
  to 300 characters, newlines stripped, written as text at DEBUG, never
  interpreted — and `activity()` reports mode opened, mod picked, record opened,
  field changed from X to Y (on `change`, so one line per value settled on rather
  than one per keystroke), and a dialog closed with edits still pending. The old
  value comes from a `focusin` capture, because it is only knowable before it
  changes. A real session now reads:

```
UI  opened           Minor Files (mod: Third_Age_Reforged)
UI  opened record    gladiator_uprising (rebels) in Third_Age_Reforged
UI  changed          chance: “100” -> “42”
UI  picked mod       Third_Age_Reforged (was Divide_and_Conquer_EUR)
UI  reading mod      Third_Age_Reforged
```

* **And the tool narrates its own background work**, which is the other half of
  the same complaint. `PARSE` says which mod is being read and what came out of it
  (`916 units, 89 mounts, 1941 localised names in 0.55s`) — that is what the
  screen is waiting for on a cold mod, and it was previously silent. `UNITS` says
  how long the payload took and **how many units ship no card**, naming them at
  DEBUG: a blank card in the grid is either "this mod has no art for it" or "the
  conversion failed", and those look identical on screen. `ICON` says which file
  was converted and how long it took, and names the unit when there is nothing to
  convert (`Stone Giants has no card art in Third_Age_Reforged`) — the icon cache
  only ever sees a path, so that line had to be written where the unit is known.

Two tests had to change with the endpoint: `test_edit_http` and `test_bmdb_http`
read `/api/log` as a bare array, and now read `["entries"]` (newest first). Both
pass, and `test_edit_http` gained a check that the page reports its own totals.

- **Goal:** The log section is where you go to find out what the tool did, and it
  opens instantly.
- **Items:**
  - **Opening the log takes up to minutes.** `/api/log` returns
    `config/transfers.json` whole — **1,086,991 bytes here** — and `openLog`
    builds HTML for every entry in it. Page it server-side and paint a window of
    it, so open time stops depending on how long the tool has been in use.
  - **Move "Save diagnostic log" out of Settings** (`settings.js`, the "Something
    went wrong?" fieldset) **into the log section**, with the rest of the log.
  - **Filter the log by mode** — transfer, edit, bmdb, sounds, buildings and the
    rest — so "what did I do in the Unit Editor" is one click.
  - **The log does not record enough.** It should read as a transcript: what the
    user did (entered this mode, opened this unit, changed this field from this
    to that, saved it or left it), and what the tool did in the background with
    the same weight (parsing this file, fetching unit data, fetching the unit's
    UI art, this card was not found so it is being converted). `logutil.py`
    already has `block`, `file_op` and `fingerprint` for exactly this shape — the
    gap is the calls, not the plumbing. UI actions have no path to the log at
    all today, so that needs a small endpoint, batched.
  - **Ctrl+Z and Ctrl+Y are broken everywhere.** The handler is live
    (`undo.js:303`) but every scope's `id()` opens with `modalOpen()`, so outside
    a dialog there is nothing to undo and the key silently does nothing. Decide
    per scope what is meant to happen, then fix it — "nothing of ours to undo"
    and "the browser's own undo" must not be confusable.
- **Files:** `web/js/settings.js`, `web/js/undo.js`, `unittransfer/server.py`,
  `unittransfer/config.py`, `unittransfer/logutil.py`, tests.
- **Exit criteria:** the log opens in under a second on a log this size; the mode
  filter and the save button are both in it; a scripted session (open a mod, edit
  a field, save, switch mode) reads end to end in `server.log` with nothing
  important missing; Ctrl+Z and Ctrl+Y take back and restore a value in every
  editor that claims to support them.

### 14c — Launcher, Home, and the prose sweep ⏳ (four of five done 2026-08-18)

- **Goal:** Nothing on the way into or out of the tool tells the user something
  untrue.
- **Items:**
  - **"Pillow is missing" is printed on every failed start**
    (`Launch-Medieval2-GUI-Toolkit.bat:98`), one of three guesses, while
    `startup.preflight` has already worked out the real reason. Print the
    preflight result instead of the guess list.
  - **"Keep the console window open" does nothing for the current session** —
    `app.py:97` reads `show_console` once, at launch. Either apply it live or say
    "from the next launch" at the tick box, not three lines below it.
  - ~~**The old launcher name is still in five places.**~~ ✅ done in 14a, which
    rewrote one of those messages anyway.
  - **Home step 1 gets its own Browse and Auto-detect buttons** instead of a
    Change button that opens Settings (`home.js:61`); both actions already exist
    as `browseRoot()` and `autoDetectRoot()`.
  - **Home gains a step 3, Preferences**, carrying the settings options (console,
    transfer defaults, unit-text cache, ignored limits) so Settings is not the
    only way to reach them.
  - ~~**A second prose sweep.**~~ Split out as **14g** — measured at 115 hits
    across 12 files, which is not a tail-end item.
- **Files:** `Launch-Medieval2-GUI-Toolkit.bat`, `Install-Dependencies.bat`,
  `app.py`, `unittransfer/startup.py`, `web/js/home.js`, `web/js/settings.js`,
  UI strings across `web/js/`, `README.md`.
- **Exit criteria:** forcing each preflight check to fail prints that check's own
  reason and no other; no file in the repo names the old launcher; Home does the
  root folder and the preferences without opening Settings; the UI strings carry
  no clause-joining em dash and no uncapitalised sentence.

**Outcome.** Four items done and verified; the prose sweep is measured and split
out as **14g** below, because it is a session's work of its own.

* **The launcher no longer guesses.** A failed startup check now exits **2**
  (`app.EXIT_PREFLIGHT`), so the .bat can say "the reason is in the list above,
  look for the lines marked FAIL" instead of printing three guesses under it —
  the first of which was "Pillow is missing → pip install pillow", Pillow
  installed or not. A non-zero code that is *not* 2 gets its own message: the
  checks passed, so it is not a missing library or a taken port, and the log has
  the traceback.
* **"Keep the console window open" can be applied now.** It is read once, at
  launch, which is why ticking it appeared to do nothing; the tick box now says
  so where the tick is, and **↻ Restart now to apply it** hands the port to a
  replacement server. The order is the whole trick: the outgoing server cannot
  stop before it has answered the request telling it to stop, so it replies,
  spawns the replacement with `--wait-port`, and only then lets go. Measured
  end to end: pid 22044 → 19632 on the same port in 6.1 s, and the page waits for
  `/api/ping` and reloads itself. A console child runs on `python.exe`, not
  `pythonw.exe`, or its output would have nowhere to go.
* **`startup.port_free` asks by binding, not by connecting.** The first version
  connected, and on this machine that cannot answer the question: with a timeout
  set, `connect_ex` returns `WSAEWOULDBLOCK` both for a closed port and for a
  listener whose accept queue is full, and a *closed* loopback port here times
  out rather than refusing. Binding is exactly the question a starting server
  asks. Four cases now behave: live server held, non-answering listener held,
  closed port free, and free within 1.0 s of a release.
* **Home step 1 has its own Browse and Auto-detect buttons**, and picking a
  folder re-reads the mods and repaints the cards, so the grid below answers
  straight away whether it was the right folder. Auto-detect reports "no install
  found in the registry" here, which is correct: this install has no registry key
  (the success path cannot be exercised on this machine).
* **Home step 3 is Preferences** — console, soldier-from-base, `.strings.bin`
  recompile, Code View and which faction name leads — one row per line, each
  saving on change. Settings keeps the awkward ones (M2TWEOP folders, the
  unit-limit overrides, the cache, Quit) and step 3 links to it.

**Carried in and fixed here:** audit §1.5. `config._read_json` fell back to the
last text it had read whenever a read failed, which is right for the microsecond
a Windows `os.replace` makes a file unopenable and wrong for a file that is
*gone* — a deleted `settings.json` stayed visible for the rest of the run, and
the tool went on reporting a MED2 root that had been removed. Gone and busy are
now told apart. That was also the `test_startup` flake: 48/48, three runs
running, where it was 31/32 with the failing check moving between runs.


### 14d — Unit Editor: a compact guided view, and a Code View that follows — DONE

- **Goal:** The guided editor fits on a screen, and Code View sits beside the
  field you are actually looking at.
- **Items, and what each turned out to be:**
  - **Pair the rows that belong together.** `GF_PAIRS` in `guided.js`, drawn by
    `gfRows`: Internal name | Dictionary · Category | Class | Voice type |
    Accent · Faction banner | Holy-war banner · the three officer entries ·
    Movement modifier | HP · Heat fatigue | Ground modifiers · Charge distance |
    Fire delay. A group is emitted where its first member appears, in the
    **group's** order rather than the file's, so a mod that has moved a line
    does not lose the pairing over it. Both guided hosts get it — the composer
    as well as the editor.
  - **Tidy layout on by default.** `cvAutoTidy` lines the block up as the record
    opens, and the honesty of the pane is kept by what it does NOT do: the
    fields are identical, so the boxes are not rebuilt and nothing pending in
    them is lost, and the result is remembered as `cv.auto` so `edCvUserEdited`
    can tell "the tool did that" from "the user did that". Opening the pane
    therefore does not make the dialog dirty; the moment there IS something to
    save, the tidied text is what gets written. Off is a remembered setting
    (`code_view_tidy`) and turning it off re-reads the record from the file.
  - **Code View sticks now.** The cause was not `position:sticky` at all: every
    adopter wraps `cvHtml()` in a column div, so the pane is a CHILD of the grid
    item, and `.cvsplit`'s `align-items:start` shrink-wrapped that item to the
    pane's own height — a sticky box with nowhere to travel. `stretch` gives it
    the row's height back. Measured: pinned at the modal's top through the whole
    scroll, and a field at the very bottom of the dialog has its line in view.
  - **The comment lines are hidden, and the hiding is a PAIR of functions.**
    `codeview.hide_comments` / `show_comments`: the page is handed the text
    without the comment-only lines plus an opaque `hidden` list, sends both
    back, and the server rebuilds the real bytes before anything parses or
    saves. The page never learns what a comment looks like in this format, which
    is the module's existing rule. A trailing comment stays on its line — it
    belongs to the field in front of it. Each hidden line remembers its index,
    the line it sat above and that line's keyword, tried in that order, so
    typing a new **value** does not move it. `COMMENT_MARKS` carries `#` for the
    EDB, per Phase 13's ruling.
  - **Raw-lines mode is line for line.** Neither pane scrolls: `cvExpand` grows
    the pane to the whole record and `edRawAlign` places each box from the
    **span** the server already sends, not by counting rows — a block has a
    `type` line, hidden comments and repeats, so counting would drift. Measured
    at 1 px over a 38-line block.
  - **"Open file location"** replaces the Browse button under both cards, over a
    new `POST /api/reveal` that takes the mod and a path RELATIVE to that mod's
    data folder, never an absolute one.
  - **The unit card image was clickable and did nothing** — it picked up
    `.card`'s pointer cursor and hover border from the browse grid. It now does
    what the ✎ on it does.
  - **The group-by headings fold**, remembered per group-by on the user's
    settings, and **Era (custom battle)** joins Faction / Category / Class as a
    group-by so all four of the named ones exist to fold.
- **Files:** `web/js/guided.js`, `web/js/editor.js`, `web/js/codeview.js`,
  `web/js/core.js`, `unittransfer/codeview.py`, `unittransfer/server.py`,
  `unittransfer/folder_dialog.py`, `web/index.html`, and the four other Code View
  adopters (`traits.js`, `ancillaries.js`, `factions.js`, `minorfiles.js`), which
  saved `cv.text` and now save `cv.base` — `text` is the view, and saving it
  would have deleted every comment line.
- **Exit criteria — all met:** each paired row lands on one line at the default
  window width (measured: identical `top` for every card of all seven rows);
  Code View's highlighted line is in view at any scroll position; a round-trip
  through the comment-hiding view is byte-exact (`test_codeview`, and end to end
  in a running browser on a DaC trait and a TATR unit); raw-lines mode lines up
  row for row; group headings fold and the state survives a repaint.

### 14e — EDU cleanup, and unit tiers ✅ (done 2026-08-19)

`unittransfer/edusort.py`, the tier marker in `unittransfer/edu.py`, tier and
variant vocabularies in `vocab.py`, `GET /api/edu/order` +
`POST /api/edu/sort/plan|apply`, `web/js/edusort.js` and a tier box on the Unit
Editor's identity tab. `tests/test_edusort.py` is 56 checks over both installed
mods. **The marker is `;@m2gt tier=3 variant=aor`, as proposed and confirmed.**

Four things the measurement decided, and all four went against the plan:

* **A `;@m2gt` line directly above `type` starts that unit's block.** Under the
  old boundary a comment above `type` belongs to the PREVIOUS unit, so the
  marker would have described one unit while living inside another and been
  left behind by every transfer, replace and sort. Safe to change precisely
  because the marker is ours: no real file has one, so every byte-exact
  round-trip is untouched by construction.
* **The file's own banners are read before anything is asked of the user.**
  A tier is in no game file — but a mod that organised its EDU by hand has
  already written one, and **907 of DaC's 916 units sit under a
  `;--- GONDOR TIER 1 INFANTRY ---` banner**. The tier is harvested from there
  and recorded on the unit, which also breaks a circle: this pass rewrites the
  banners, so a tier living only in one would be regenerated from itself.
* **Faction first, kind second — the table of contents is not the layout.**
  DaC's TOC promises a GENERALS block and MERCENARIES / SIEGE / SHIPS blocks,
  and the file does not have them: all 31 generals sit at the head of their own
  faction's run and the 127 mercenaries are spread from unit 11 to unit 891.
  Hoisting either moves ~140 units their author placed. Only the 13 units
  nobody owns fall through to a shared section.
* **A section is the author's own word for it, kept as text.** Only 146 of 916
  banner names match a localised faction name — a modder writes `CRAG` and
  `DORWINION` — and `ownership` cannot stand in, since most units list a dozen
  factions and the line is a set, not a ranking. Resolving banners to faction
  slots, or ordering sections by `descr_sm_factions.txt`, each moved hundreds of
  units for nothing; taking the order from where it is actually expressed (the
  median position of each section's units) took DaC from 44% of the roster
  moving to **15%**.

Also landed: **a hand placement is recorded, not just applied.** The ordering
screen writes `order=N` onto the units it places, so the next cleanup honours
them — a placement the following run undoes is a screen that wasted the user's
time. And the plan **refuses** any text that is not purely a reordering: same
units, same fields, every comment still there, checked before a byte is written.

<details><summary>original plan</summary>

### 14e — EDU cleanup, and unit tiers

- **Goal:** Turn a sprawling `export_descr_unit.txt` into the shape DaC's is in,
  without the tool ever deciding something it cannot justify from the file.
- **Items:**
  - **Tidy the whole file**, not one unit at a time — the layout `cvTidy` already
    applies to a single block.
  - **Group the units into sections.** Work out how DaC's EDU is actually
    organised (generals at the top, then by faction, then by unit type) and
    reproduce that grouping. **Prefer the order already in the file:** a unit
    already in a sensible place does not move.
  - **A per-faction GUI for the order**, so exceptions can be placed by hand
    rather than argued with.
  - **Unit tiers.** A tier is in no game file — it is the tool's own metadata,
    kept in a comment above the unit, and it exists so this sorter has something
    to sort by. Tier 0–5 by default plus special variants of each (AoR, unique
    general, quest unit and so on), and a way to add more. Editable in the Unit
    Editor, labelled there as tool-only so nobody expects the game to read it.
  - **Open question for the user:** the exact comment marker. Proposal —
    `;@m2gt tier=3 variant=aor` on the line above the unit's `type`, one owned
    prefix, invisible to the engine, skipped by our parsers the way Phase 13's
    ruling skips `#` in the EDB. *Confirmed as proposed, 2026-08-19.*
- **Files:** a new sorter module in `unittransfer/` (splice-based: it moves whole
  line blocks and never re-emits a record), `unittransfer/edu.py`,
  `web/js/editor.js`, `web/js/guided.js`, tests over both installed mods.
- **Exit criteria:** ✅ cleaning up either installed mod's EDU produces a file the
  game loads, with the same units, the same fields and every comment still
  present; ✅ running it twice changes nothing the second time; ✅ a tier written in
  the editor survives a cleanup and a save; ✅ the per-faction ordering GUI can
  place a unit the sorter got wrong.
  *Landed as:* the ordering GUI is a tab of the cleanup dialog rather than a
  screen of its own, and it is per **section** rather than per faction, because
  a section turned out to be the author's own banner word and not a faction slot
  (see above). **`web/js/guided.js` is untouched on purpose:** the guided view is
  a view of real EDU field lines, and putting a value the engine never reads
  among them would blur the exact distinction the "toolkit only" badge exists to
  make. The tier lives on the identity tab, where a unit's identity already does.

</details>

### 14f — EDB unit view, twin compare, and the rest ✅ (done 2026-08-19)

**Outcome.** All ten items landed, with `tests/test_unit_view.py` (25 checks)
over the two halves that are ours to promise, measured across **8233 real pool
rows** in the two installed mods.

The unit view was already the screen that gathered every building line training
one unit; what it could not do was any of the things you go there to do. It can
now:

* **The Requires clause is editable from the unit's side**, through the same
  dialog the building editor uses. These rows come from lines that are mostly
  not loaded, so the clause dialog was given a host of its own and the edit is
  kept in `cmp.edits` beside the numbers — which is what makes a requirement
  edited here produce the same plan entry as one edited from the building view.
* **A Twin column**, per TIER rather than per building: a twin that trains the
  unit five levels up is not the same building. **DaC has 239 rows whose facing
  tier does not train the unit and Third Age Reforged has none** — the second
  number is why this is worth showing, because a check that can only ever say
  "diverged" is not measuring anything. Each gap gets a `⇄` that stages the pool
  into the twin through `bldStagePool`, so it refuses a duplicate and rides the
  same Save as everything else.
* **A read-only Code View** (`codeview.pools_document`, kind `pools`). It is the
  one code view in the toolkit that is **not a record** — it gathers
  `recruit_pool` lines from a dozen blocks, so there is nothing for a serialiser
  to write back to, and it is read-only by construction rather than by policy
  (no `parse`/`render` pair is registered at all). Hovering a row lights its
  line; each line is the file's own bytes with its real line number beside it.
* **The three recruitment numbers are named** — Immediate recruitment, Replenish
  rate, Max pool — in the unit view and in the add-units dialog both. "start /
  per turn / max" said what the numbers looked like, not what they do.
* **The `open` badge says what it means**, "add to the tiers above" **names the
  tiers**, and the recruitment faction dropdown **remembers whether it is sorted
  by unit count or A to Z** (`bld_facsort`; count stays the default, because
  "who trains the most here" is the question the list is usually scanned for).
* **The BMDB Editor is the BMDB + Sprites Editor**, in `MODES`, in
  `modfiles.py`'s readiness matrix and in the README.
* **Minor Files shows its art.** A religion's pip, a resource's icon, a
  settlement card and an agent card are all TGAs under the mod's `data/`, and
  the editor showed them as text while the Buildings gallery showed pictures.
  Same server route as a faction symbol (`kind=modfile`, which keeps the path
  inside `data/`). The two files disagree about the prefix and **both are
  right** — a resource icon is written `data/ui/…` and a religion's pip
  `ui/pips/…` — so the redundant half is dropped at the call site rather than in
  either parser. A blank slot is still never called a fault: Phase 10a measured
  that check at 78 findings across three mods, 77 of them noise.

Two bugs found on the way, both ours and both in shared machinery:

* **`bldTouched()` re-rendered a form that was not on screen.** Staging anything
  from the unit view threw `Cannot set properties of null` out of
  `bldRenderBody`, because the building body element does not exist while the
  unit modal is up. It now returns early when the unit view owns the modal, and
  the form is rebuilt from the same working copy on the way back.
* **The clause dialog and the unit view shared one stash slot.** Both saved the
  markup they covered into `b.stash`, and the unit view can open the clause
  dialog *on top of itself* — so the two took turns clearing one slot and the
  building form underneath was lost, wiping the editor on the way back. The
  clause dialog now has its own (`bldClauseStash`/`bldClauseUnstash`) and the
  nesting stops mattering.

**One item resolved as a no-op, and it is recorded rather than quietly
dropped:** "gallery view is already the default, find what set `bld_browse` to
`tree` before changing it." Nothing does. The only writer in the codebase is
`bldSetBrowse`, which is the user's own click on the view toggle, and the saved
setting on this machine reads `gallery`. There was nothing to fix.

<details><summary>original plan</summary>


- **Goal:** Recruitment is editable from the unit's side, and a city/castle pair
  can be brought into line in one click.
- **Items:**
  - **The unit view already exists** (`bldUnitRow`, `buildings.js:2673`) and
    lists every line that trains the unit. Two gaps: **the Requires column is
    read-only** there while the same clause is editable elsewhere, and **the
    `open` badge is unexplained** — it means "the building line you have open"
    and needs a tooltip saying so.
  - **"Mention if the unit is in the TWIN building."** *(Answered 2026-08-19.)*
    The first reading — *is it in this mod's EDU* — was wrong, and checking
    settled it: that is already built and has been since Phase 12
    (`buildings.js:2650` shows a red "not in this mod's EDU" beside the name).
    What was meant is the city/castle counterpart: for each row in the unit
    view, say whether the twin line trains this unit too. It is the same
    question `bldTwin()` already answers for a whole building, asked per unit,
    and it is what makes the **Mirror** item below actionable from this side.
  - **Recruitment numbers in two rows:** the top row renamed to **Immediate
    recruitment** (start), **Replenish rate** (per turn) and **Max pool**
    (maximum); the bottom row the unit's requirements.
  - **Compare the city and castle variants of one building side by side**,
    units included, with a **Mirror** button that resolves one unit or all of
    them. Half of this is built: `bldTwin()` and `bldTwinLevel()` find the twin,
    the add-units dialog can already mirror into it, and the recruitment checks
    already produce `mirror` findings — this is the view that makes them
    actionable.
  - **Sort the recruitment faction dropdown** by A to Z or by unit count.
  - **"Make the code view reach the UNIT VIEW too."** *(Answered 2026-08-19.)*
    The first reading — *Buildings gets Code View like every other module* — was
    also wrong: the building editor has had it since Phase 4b
    (`bldCvToggleHtml` at `buildings.js:488`, `bldCvHost` at `506`). The dialog
    with no pane is the per-unit recruit-pool view, which is what the rest of
    this sub-phase is about. It should show the `recruit_pool` lines it is
    editing, from however many building blocks they come from.
  - **Hovering "add to the tiers above" should name the tiers** it means
    (`buildings.js:2092`).
  - **Gallery view is already the default** (`buildings.js:204`), so the report
    means a remembered `bld_browse` of `tree`. Find what set it before changing
    the default.
  - **Rename the BMDB Editor to "BMDB + Sprites Editor"** — the `MODES` entry at
    `core.js:241` and every label that follows from it.
  - **Minor Files has art it does not show.** Many of those menus have TGAs
    behind them; show them the way the Buildings gallery shows a building.
- **Files:** `web/js/buildings.js`, `unittransfer/buildings.py`,
  `web/js/minorfiles.js`, `web/js/bmdb.js`, `web/js/core.js`, tests.
- **Exit criteria:** ✅ a requirement edited from the unit view saves the same as
  one edited from the building view (verified in a running browser: the plan
  reads `wooden_castle: … requires factions { portugal, } and region_religion
  catholic 15 -> factions { poland, }`); ✅ the twin compare shows both halves of
  a real DaC pair and Mirror closes an inconsistency the checks flagged
  (`core_castle_building · motte_and_bailey` → `core_building ·
  wooden_pallisade`, staged and previewed); ✅ the renamed recruitment fields are
  the ones a save writes; ✅ Minor Files shows art for every menu that has any.

</details>

### 14g — The second prose sweep ✅ (done 2026-08-19)

**Zero clause-joining dashes, down from 21.** Rewritten across `guided.js`,
`transfer.js`, `buildings.js`, `sprites.js`, `editor.js` and `factions.js`: a
dash doing a full stop's work became a full stop, a colon or a conjunction,
whichever the sentence actually wanted.

**Most of the 115 was the measurement, not the writing.** `tools/prose_check.py`
promised in its own docstring to stitch a note's fragments back together before
judging them, and did not — so a continuation was read as a sentence of its own
and reported for starting in lower case, which is what a continuation does. Six
reader defects, each fixed at the source rather than by rewriting 90 sentences
around a quirk of the reader:

| | what it did | hits |
|---|---|---|
| leading `+` | the codebase writes `\n +'…'`; only a TRAILING `+` was stitched | 47 |
| escaped quotes | `\'` ended the literal early, chopping sentences mid-word | 5 |
| `+ (a?'x':'y') +` | a choice spliced into a sentence read as two strings | 10 |
| ternary branches | two literals sharing a line were joined into one sentence nobody wrote | 9 |
| inline CSS | `'flex:0 0 88px'` has spaces and letters, so it read as prose | 5 |
| `${n} unit(s) …` | a sentence opening on a value was judged on the letter after it | 12 |

Two rules were also added to what is *not* a sentence, alongside the existing
"a label is not a sentence": **a list is not** (the `syn:` lines name a record's
value slots — "attack, charge, projectile, range, ammo, …" — every word an EDU
term that is lower case by definition), and **a sentence that opens on an
interpolated value is not judged on the letter after the hole.**

**Four deliberate keeps**, all one class and one reason: a fragment spliced into
a sentence that is assembled at render time, so the reader never sees the whole
of it and the lower-case start is correct on screen.

* `buildings.js:1990` — a `fixes` entry, rendered as "Saving fixes both: the
  ownership line is extended, and the missing textures are copied…".
* `editor.js:1361` — a ternary branch continuing "Editing this entry changes …".
* `sprites.js:482` — an optional clause inside "Writes the voice bank … .".
* `transfer.js:183` — a template branch continuing "Copied: the … block …".

<details><summary>original plan</summary>

### 14g — The second prose sweep

- **Goal:** Finish the writing rules across the whole UI, with a number to hit
  rather than an impression to chase.
- **The work list is measured.** `tools/prose_check.py` (written in 14c) reads
  the visible strings out of `web/js/*.js` and `web/index.html` and applies the
  two rules: **115 hits in 12 files — 21 clause-joining dashes and 94 lower-case
  sentence openings.** Worst first: `guided.js` 37, `transfer.js` 29,
  `buildings.js` 27, `sprites.js` 9, `editor.js` 5.
- **It is a work list, not a linter.** Three heuristics were tried and thrown
  away before the count meant anything: reading line by line reported 589
  lower-case starts, almost all of them the second half of a sentence that began
  correctly on the line above (a long note is several literals joined with `+`);
  scanning after every full stop flagged sentences that legitimately open with a
  code identifier (`no` means a melee weapon); and short labels are not
  sentences — "mercs only" and "per turn" are right as they are. The tool now
  stitches fragments back together and only flags a whole string. **Read every
  hit in context before rewriting it.**
- **Files:** UI strings across `web/js/`, `web/index.html`.
- **Effort:** M — one session.
- **Exit criteria:** ✅ `python tools/prose_check.py` reports zero, or every
  remaining hit is listed in this phase as a deliberate keep with its reason.
  *Landed as:* zero dashes, and the four remaining case hits listed above.

</details>

### Carried in from `merge/audit-codebase.md`

That audit's own list belongs to this phase rather than to the viewer, and none
of it is done. **Must:** §1.1 — `bmdb.mount_audit` crashes with `TypeError:
string indices must be integers` on a mod shipping only some `descr_*.txt`; a
dead parameter, a namespace confusion and a casing mismatch, fixed in one pass
with the trimmed-mod repro as the test. **Should:** §1.4 (derive `_invalidate`
from `Mod`), §1.5 (narrow `config._read_json`'s staleness window without removing
the fallback) and settling §2's `test_edit_models` question. **Then:** unhardcode
`Third_Age_6` in the three fixtures, so the baseline stops hiding regressions
behind mod-set churn, and take the ~20 lines of §6 safe removals.

- **Risks:** a long list of small changes across every module is exactly the
  shape that breaks something quietly. Two guards: the splice rule — 14d's
  comment hiding and 14e's sorter both touch files that must round-trip
  byte-exact, so assert the round-trip and not just the feature — and
  `test_web_modules`, which is the only thing between a new shared widget and a
  silent name collision in the one global scope.

### 14i — The post-release correction pass ✅ (done 2026-08-20)

The list that came back from actually using v2.0.0. Ten items, no new direction,
**folded into the 2.0.0 release notes rather than given a version of its own** —
the user asked for it that way, so the tag, `__version__` and the release page
all stay 2.0.0 and `merge/RELEASE_2_0_0.md` gained a "The correction pass"
section. A future round asked for as its own version is 2.0.1.

- **Goal:** finish 2.0.0 properly. Two real defects, one freeze, seven pieces of
  polish, a repo rename and a writing sweep.

**Outcome.**

*The repo.* `ProJ-Yeet/medieval2-unit-transfer` → `ProJ-Yeet/medieval2-gui-toolkit`,
description rewritten, `origin` re-pointed. GitHub forwards the old address, so
nothing published breaks. The only in-tree references were STATE.md and
HANDOFF.md; the app itself never linked to its own repo.

*Two defects, one cause each.*

- **"Open file location" opened Documents.** `folder_dialog.reveal` passed
  `["explorer", "/select,<path>"]` as a LIST, and `subprocess.list2cmdline`
  wraps the whole `/select,C:\Some Folder\x.tga` token in quotes as soon as the
  path holds a space. Explorer cannot parse the switch then and falls back to
  the default folder. Every real mod path has a space in it, so it failed 100%
  of the time and looked like "the button does nothing useful". It is one
  command STRING now with the path quoted inside the switch, plus `normpath`
  because Explorer will not follow forward slashes. Verified against a real DaC
  card path: Explorer lands on `…/Divide_and_Conquer_EUR/data/ui`.
- **Ctrl+Z did nothing in the Code View.** undo.js listens on the document and,
  whenever an editor is open, calls `preventDefault` and restores a snapshot of
  that editor's BOXES. Typing in the pane is in no such snapshot, so the
  browser's own textarea undo was suppressed and ours had nothing to give back.
  The pane keeps its own stack now (`cvUndoInit` / `cvUndoNote` / `cvUndoStep`),
  same shape as undo.js's: snapshots, a run of typing coalescing into one step
  after 450 ms of quiet. Two rules keep the stacks from fighting — a text change
  nobody typed re-baselines the pane's stack, and an EMPTY stack means "not
  mine", so the handler returns without touching the event and undo.js runs
  next. Undo therefore walks back through the typing and then out into the form,
  in the order the edits were made. codeview.js loads before undo.js, which is
  what makes the ordering work.

*The freeze.* `bldRenderBody` threw `Cannot set properties of null` whenever a
panel that takes the modal over (Add units, the per-unit comparison, the new
city/castle comparison) was on screen and something changed the working copy.
The throw came out of an onclick, so it killed that click and everything after
it — from the outside, the tool stops responding. `bldTouched` now returns early
for `cmp`, `vc` or any `stash`; `bldRenderBody` returns early with no `#bldBody`
at all. The stale-`state.bld` paths went with it: the settlement filter's
handler reads the live object rather than the one captured when it was wired,
and `bldSetView` / `bldFacSortToggle` / `bldPoolFacPick` / `bldCapList` go
through a guarded `bldRedrawLevel()`.

*Everything else.*

| item | where |
|---|---|
| Folding sidebar groups, persisted, with a ticked-count badge | `core.js` `wireFilterFolds`, read off the markup so a new `<h3>` folds without being wrapped by hand |
| ＋ beside the tier Variant | `editor.js` `edTierVarAdd`; the typed value is kept in the list as `(new)` or the drop-down comes back empty and the staged value looks lost |
| Abilities merged into **Weapons & abilities** | `guided.js` `GF_SECTIONS`; two cards was never a tab |
| Editable comment breakers | `edusort.banner_style` / `banner(title, style)`; width, fill, prefix, capitals, live sample in the dialog. `upper` defaults OFF so the default output is byte for byte what 2.0.0 wrote |
| The ordering screen as a unit LIST with tier / variant / **classification** | `edusort.js` rewritten; `apply_marks` writes them onto `;@m2gt`; `overview` sends `detected_special` so the box arrives filled in |
| **⇄ Compare city / castle** | `buildings.variant_compare` + `GET /api/buildings/variants`; the panel, per-unit ⇄ Mirror and ⇄ Mirror all in `buildings.js` |
| One set of names for the three pool numbers | `POOL_LABEL` / `POOL_SHORT` in `buildings.js`, used by every screen that shows them |
| Two-line recruitment rows | `.poolrow .prtop` / `.prbot`; the `requires` clause is the only thing on that row with no natural width |
| The comparison header lines up | the header cells carried none of the classes that set the column widths |
| The building Code View follows field edits | `bldCvFollow()` from `bldDirtyNote` and `bldTouched`; this editor was the only adopter that never called `cvFromGui` |
| Faction sort as a toggle | it was an entry in the drop-down it sorts, so choosing it closed the list |
| Unit cards on the voice rows | `sprites.js` `sndRowHtml` |
| ~300 clause-joining em dashes → 0 | every `web/js` module and `index.html`; four number ranges kept, and the lower-case keeps are file names, `and`/`or` clause tokens and inline fragments |

**New surface.** `GET /api/buildings/variants?mod=&line=&culture=`;
`marks` and `style` on `POST /api/edu/sort/plan|apply`; the `special=` marker key
on `;@m2gt`, read through `edusort.special_of` and detected by
`edusort.detected_special`.

**Measured.** DaC `barracks` against `castle_barracks`: 3 units on one side only,
411 with different pool numbers across 414 shared units — which is why "differs"
is reported per FIELD and a `requires` mismatch is not counted as a divergence.
A city clause names the city factions and a castle clause names the castle ones,
so a single yes/no would have flagged the whole roster and meant nothing.

**Risk that bit.** The ordering screen repaints ONE row on a drop-down change,
not the roster: 916 units × 3 drop-downs took ~690 ms to rebuild, so the box you
had just used was replaced under the pointer. 11 ms after.

**Two defects the new suite found in the new work**, both in the banner style
and both the same shape — a writer that can draw something its reader cannot
read. `BANNER_RE` only ever matched a rule of HYPHENS, so a banner drawn with
`=` or `#`, or with a prefix of `;;`, was unreadable to the next run: it would
be carried as an ordinary comment AND a fresh one written above it, and the file
would gain a banner every pass. The reader takes the whole `BANNER_FILL` set
now, which also picks up the `;===== GONDOR INFANTRY =====` a mod wrote by hand.
And `width` was off by one against the line it produced (96 in, 95 out) —
inherited from the constant it replaced. `BANNER_WIDTH` is 95 now and the
arithmetic is exact, so the default output is byte for byte what it always was
*and* the number means what it says.

`tests/test_variants_and_marks.py`, 82 checks: the comparison from both sides on
every installed pair, every banner style round-tripping through `BANNER_RE`,
seven nonsense styles falling back rather than raising, and a marked cleanup
reaching disk on both real mods with no unit gaining or losing a field.

### 14j — Replace any picture ✅ (done 2026-08-20, released as v2.0.1)

- **Goal:** every picture the tool draws can be replaced in place and can say
  where it lives, the way the unit card already could — with a warning when the
  resolutions do not match.

**The way in is the `<img>`'s own `src`.** Every picture on every screen is
painted through `/icon` or `/building_icon`, and that URL is a complete
description of the question the server answered. So the page hands the URL
straight back and `unittransfer/images.py` re-resolves it. That is what made
this small: one dialog and one engine cover unit cards, info cards, ancillary
pictures, faction art, the Minor Files pips and settlement cards, and building
icons, instead of five per-screen imports.

**Outcome.**

- New `unittransfer/images.py` (`locate` / `plan` / `apply` / `reveal_target`)
  and `web/js/images.js`; routes `POST /api/image/plan|replace|reveal`. The
  write goes through the same backup + log record as every other job, so it is
  in the log and undoes like a transfer.
- **Two ways in.** A delegated right-click menu on any `<img>` whose src is one
  of the two routes — which is what covers the thumbnails in lists and grids —
  and a ✎ plus a button pair on the screens where the picture is the subject
  (card variants, ancillary, faction art, the building editor's Art pane, and
  the Minor Files pips, where the pip itself is the button).
- **The resolution check**, which is what was actually asked for: the confirm
  dialog puts both pictures side by side at the size each really is and names
  both sizes when they differ. A warning and never a refusal — a mod is free to
  change what size its own art is.
- **A unit card fans out to every faction folder that holds one**, reusing
  `edit._unit_icon_files`, falling back to the ownership fan-out `_plan_icon_import`
  computes when the unit has no card yet. Replacing only the folder the preview
  resolved would leave the rest stale — which is the same fact the card-variant
  list exists to make visible.
- **Borrowed art creates rather than overwrites.** A building icon or ancillary
  picture the mod does not own is served out of the vanilla UI; a replacement
  writes the mod's *first* copy at the path the game looks for, and the dialog
  says so. That is the "drop a .tga in to override it" the building browser had
  been telling people to do by hand.
- **`.png`/`.jpg` → 32-bit `.tga`**, and a same-stem sibling in the other native
  extension is removed so two files cannot answer to one name. Backed up first.
- **`Function(...)` rather than `window[name]`** for the panel re-render hook: a
  top-level `const` in a classic script lands in the global lexical scope, not
  on `window`, so `bldRenderBodyNow` was invisible to a property lookup.
- A bare `addEventListener` at the top level of a module file breaks the two
  node-driven tests, which stub `document`/`window` but not the global. It is
  `document.addEventListener` now.

`tests/test_images.py`, 53 checks — it builds its own folder of pictures rather
than borrowing a mod's, so everything but the unit-card fan-out runs with no
game installed. The last section drives the real server over HTTP with the exact
JSON the page sends.

## Phase 15 — 3D model viewer (two sessions)

- **Goal:** A working in-browser viewer for unit `.mesh` models (their
  ModelViewer is broken; fix the approach or reimplement from the Blender
  addon's loader).
- **Preconditions:** Phase 3; Blender addon in `Reference/Medieval-2-Toolkit/`
  as format ground truth; Phase 2 manifest for their `ms3dCodec`/`casCodec`
  findings.
- **Files:** **15a:** `unittransfer/mesh.py` (decode .mesh → JSON/typed-array
  geometry + texture refs, from the addon's reader) + tests against real mod
  meshes. **15b:** `web/js/viewer3d.js` + vendored `three.min.js` (~600 KB,
  ours to vendor — the "no dist/" rule is about *their* repo) + API endpoint;
  entry points from BMDB and Unit Editor ("view model").
- **Effort:** L.
- **Exit criteria:** any soldier/mount model in the test mods renders with
  diffuse texture, correct origin and orbit controls; wrong-format files fail
  with a message, not a hang; decode covered by tests.
- **Risks:** their JS mesh parser guesses ("attempting to parse anyway") — the
  Blender addon is the trustworthy reference; skinning/skeleton display is out
  of scope (static pose is enough for V2).

## Phase 16 — Campaign Map Editor — flagship, LAST (5+ sessions)

- **Goal:** Complete and surpass their half-finished map editor: fast accurate
  canvas rendering, layer legend, region inspector, query/highlight, correct
  sidebar enumeration, working 3D strat preview.
- **Preconditions:** Phases 4, 5, 10 (regions/religions/resources vocab), 15
  (viewer for strat models); **run the upstream sync first** — `map/` is where
  he is actively working.
- **Sub-phases, each one session with its own exit:**
  - **16a — Python foundations:** `unittransfer/stratmap.py`: `descr_strat`,
    `descr_regions`, `map_regions.tga` + companion TGAs decode (Pillow),
    settlement/character/resource models. Exit: parse both test mods with full
    round-trip; every faction and settlement enumerated correctly (their
    sidebar bug fixed at the data layer).
  - **16b — Renderer core:** single canvas with layered offscreen buffers,
    device-pixel exact picking (their one-frame icon lag and off-pixel
    placement are the anti-goals), sensible default zoom fitted to the map.
    Exit: 60 fps pan/zoom on DaC's map; dragged icons stay under the cursor on
    the exact pixel.
  - **16c — Layers + inspector:** checkbox legend (settlements on, all else
    off by default); click region → editable side panel (owner, religion,
    resources, triumph value…) with plan→apply writes. Exit: edit a region
    end-to-end with undo; legend state persisted.
  - **16d — Query/highlight:** pick a hidden resource (or any attribute) →
    all matching regions highlight; localised names throughout. Exit: resource,
    religion-majority and owner queries work on both test mods.
  - **16e — 3D strat preview:** fix navigation/origin using Phase 15's viewer.
    Exit: settlement/character strat models render and orbit correctly.
- **Future expansion (V2.1+, not V2):** mercenary-pool view/edit by region and
  faction (data layer lands in 16a; UI deferred).
- **Risks:** biggest phase, and upstream is churning here — re-triage before
  every sub-phase. TGA layer semantics are subtle (TWCenter index is the
  arbiter). This phase alone gates **3.0.0** (it gated 2.0.0 until Phase 14
  shipped as 2.0.0 without it — see Locked decisions).

---

## Explicitly out of scope for V2 (future expansion only)

Script editor (eventual Scratch-style block UI for faction events), Animations,
Unit Card Generator, Goat Tools, LUA Scripts, New Map Editor, Export/validation
dashboard. Tracked in `merge/PORT_MANIFEST.json` as `out-of-scope`; nothing in
V2 may depend on them.

---

## STATE.md contract

`STATE.md` (repo root) is the first thing a fresh session reads and the last
thing a working session writes. Format — exactly these sections, in order,
total length under ~60 lines:

```markdown
# STATE — Medieval 2 GUI Toolkit V2
_Updated: YYYY-MM-DD · vX.Y.Z · after <what this session did>_

## Next up
One imperative sentence: the exact next action (phase + step).

## Phase status
| Phase | Status | Note |
|---|---|---|
Only phases that are done / in-progress / blocked. Status ∈ {done,
in-progress, blocked}. One row per phase, one short note.

## In-progress detail
Exact stopping point when a phase is mid-flight: files half-edited, failing
tests, the next concrete step. "Clean." when nothing is mid-flight.

## Read first
2–5 paths a fresh session must read before acting (ROADMAP.md is implied).

## Upstream
reference-tool reviewed SHA + date; "sync overdue" flag if >2 weeks old.

## Decisions
Append-only, dated, one line each. Prune into ROADMAP's Locked decisions
when a decision graduates.
```

Rules: update it even for partial sessions (that's its whole point); never let
it exceed a screen — detail goes in `merge/` notes or the roadmap, not here;
phase exit criteria live in ROADMAP.md only, STATE.md just points at them.
