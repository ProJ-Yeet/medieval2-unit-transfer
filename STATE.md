# STATE — Medieval 2 GUI Toolkit V2
_Updated: 2026-08-19 · v1.9.9 (unreleased changes) · after 14f_

## Next up
**PHASE 14 IS COMPLETE — 14a through 14g, all seven.** The suite is green:
**54 of 54 modules** (14f added `test_unit_view`, 25 checks over 8233 real pool
rows; 14e added `test_edusort`, 56).

**Everything from Phase 0 to Phase 14 is in the working tree and still
uncommitted and unreleased.** That is now the biggest thing outstanding, and it
is a lot of work to be sitting on one machine.

**The next phase is 15** (3D model viewer), and it **needs an upstream sync
first** — Phase 14 ported nothing, so it never needed one, but 15 does. See
Upstream below.

### What 14f did
The unit view was already the screen that gathered every building line training
one unit; what it could not do was any of the things you go there to do.
Requires is editable from the unit's side now, through the same dialog and into
the same save. A **Twin** column says whether the city/castle counterpart trains
the unit **at the facing tier**, with a `⇄` that stages the pool across —
**239 rows in DaC diverge and none in Reforged do**, which is what makes the
column worth its width. The panel got a **read-only Code View**, the three
recruitment numbers got **names** (Immediate recruitment, Replenish rate, Max
pool), the BMDB Editor became the **BMDB + Sprites Editor**, and Minor Files
finally shows the pips, icons and cards it had only ever shown as file paths.

Two bugs in shared machinery came out of it, both ours: `bldTouched()` re-drew a
form that was not on screen, and the clause dialog shared one stash slot with
the unit view that can open it — so a clause edit wiped the building editor
underneath. Both fixed; see ROADMAP.md's 14f outcome.

## Phase status
| Phase | Status | Note |
|---|---|---|
| 0–12 | done | see ROADMAP.md for each phase's exit criteria |
| UX correction pass | done | 17 of 18 items; the 18th (prose sweep) is now finished |
| Prose sweep | done | 19 note blocks in `buildings/transfer/editor/sprites.js` rewritten as lead + points via a shared `docPoints()` in core.js |
| 13 — EDU + Sounds audit | done | `merge/audit-edu-sounds.md`; measured over 1756 real units; **nothing adopted from their code**, banners rederived from the mod's own file, two silent rewrites of ours fixed |
| EDB corpus follow-up | done | `#` annotation lines no longer read as capabilities (3 parsers + regression case); the `plugins` and upgrade-clause sweeps no longer depend on which mods are installed; `merge/audit-edb.md` corrected |
| 14 — bug-fix and polish pass | **done** | all seven: 14a, 14b, 14c, 14d, 14e, 14f, 14g |
| 14f — EDB unit view, twin compare | done | Requires editable from the unit side, a per-TIER **Twin** column (239 divergences in DaC, 0 in Reforged) with `⇄` to close one, a read-only `pools` code view, the recruitment numbers named, BMDB → **BMDB + Sprites Editor**, Minor Files art. Two shared-machinery bugs fixed. `test_unit_view` 25/25 |
| 14g — the second prose sweep | done | 21 clause-joining dashes → **0**, four documented keeps. 6 of the old 115 hits' causes were defects in `tools/prose_check.py` itself, not in the writing |
| 14e — EDU cleanup and unit tiers | done | `unittransfer/edusort.py` + the `;@m2gt` marker in `edu.py`. Tiers are READ from the mod's own banners (907 of DaC's 916 sit under one). DaC: 15% of the roster moves, and a second run is byte-identical. `test_edusort` 56/56 |
| Release check (14h) | done | `merge/audit-codebase-2.md`. A BOM cost the EDU and factions parsers their first record SILENTLY (DaC really lost a faction); mixed line endings no longer normalised; cache invalidation derived from `Mod`; the 56 "missing ancillary picture" findings were ours, not the mod's; three suites that could not run, run. **52/52 green.** |
| 14a — loading, switching, Transfer | done | one bug, four masks: the watchdog was killing a live server. Cache out of OneDrive, any request counts as liveness, 224k globs and a per-request folder scan gone, abort + generation on every load, loading bar. `test_liveness_and_cache` 21/21 |
| 14c — launcher, Home, prose | done | launcher exit code 2 + no more guessing, restart-in-place for the console setting, `port_free` asks by binding, Home steps 1 and 3. Its prose item became **14g**, now finished. `test_startup` 48/48 |
| 14d — guided view + Code View | done | seven paired rows, tidy on open without making the dialog dirty, the sticky bug (it was `align-items:start`, not sticky), comment hiding as a hide/show PAIR so nothing is lost, raw lines side by side to 1 px, "Open file location", the dead click on the card, folding headings + an Era group-by. `test_codeview` 141/141 |
| 14b — log and undo/redo | done | log paging (571 ms → 51 ms, 1.1 MB → 29 KB), mode filter, diagnostic button moved in, Ctrl+Z/Ctrl+Y wired for the five editors that never had a scope, and the log now records what the user did beside what the tool did. `test_log_and_activity` 26/26 |

## In-progress detail
Clean. 14a, 14b, 14d and 14e are finished and verified in a running browser;
14c is part-done. Phases 0–13, both passes, 14a, 14b, 14d and 14e are in the
working tree, **not committed or released**.

**The EDU cleanup is the widest single write in the toolkit** — it rewrites
every block of a 35 000-line file — so `edusort.plan` refuses to hand over a
text that is not purely a reordering: same units, same fields, every comment
still present, checked before a byte reaches disk. Measured on both mods: DaC
916 units / 15% moved, Reforged 427 / 39%, both byte-identical on a second run,
no comment lost, and Undo restores the original exactly.

The icon cache lives at `%LOCALAPPDATA%\UnitTransfer\cache\icons` (14a). The old
`.cache/icons/` next to the app is dead weight and can be deleted whenever.

**The Code View's `text` is no longer its bytes.** With comment hiding on,
`cv.text` is the record MINUS its comment-only lines and `cv.base` is the real
thing. Anything that saves must read `base`; four adopters (`traits.js`,
`ancillaries.js`, `factions.js`, `minorfiles.js`) were saving `text` and would
have deleted every comment in the record. Check this on any new adopter.

**Green: 52 of 52 modules, 2156 checks.** The six that used to fail are closed —
one was a real defect of ours (the ancillary image check, see the audit) and the
rest were tests asserting something the code never promised. Detail per suite is
in `merge/audit-codebase-2.md` §3.

A test no longer hardcodes a mod NAME: `tests/_realmod.pick()` takes the
preferred mod if it is installed, any other installed mod otherwise, and prints
SKIPPED with status 0 when there is none. Three suites used to die on a
`FileNotFoundError` for `Third_Age_6` instead — and a suite that cannot run looks
exactly like one that passes. Still check the installed mod set before blaming a
failure on a regression (memory `unit-transfer-test-mods`).

`/api/log` answers with a page now, not an array: `test_edit_http` and
`test_bmdb_http` were updated for it.

## Read first
- ROADMAP.md — phases, exit criteria, locked decisions.
- `unittransfer/flatrecord.py` — **check here before writing any parser.** Phase 11
  needed no code at all, which is why it exists.
- `unittransfer/buildings.py` — the biggest module and the only one that CREATES a
  record. Everything else in it is a SPLICE of verbatim lines; 7203 of its real
  input lines carry a comment and a re-emitting serialiser loses all of them.
- `unittransfer/edusort.py` — the whole-file EDU cleanup, and the one module that
  decides where a unit BELONGS rather than what it says. Read its docstring
  before changing any grouping rule: every one of them is a measurement over the
  two installed mods, and the obvious rule was wrong in all four cases.
- `unittransfer/vocab.py` — what a drop-down may offer: engine sets hardcoded, and
  everything a mod DEFINES read from the file that defines it, with a `defined`
  map behind the broken-reference warnings. Phase 13 moved banners onto that rule.
- `web/js/core.js` — `MODES` in `wire()`, and `docPoints()`, which every note in
  the UI is written through. One global scope, no build step; adding a module means
  a new file + a `<script>` tag + a MODES entry, all three guarded by
  `tests/test_web_modules.py`.

## Upstream
reference tool reviewed SHA **b4768d5** (2026-08-14). Sync before Phase 15 —
Phase 14 ports nothing, so it needs no sync.
`merge/PORT_MANIFEST.json` is authoritative; all 12 phase-13 files now carry their
audit verdict in `notes`.

## Open questions for the user
- `OsmBackground.jsx` / `OsmRegionSearch.jsx` (phase 16) fetch OpenStreetMap tiles
  as a tracing backdrop. Reference layer, not generated mod data — but an external
  fetch. Port or drop?
- `descr_sounds_*.txt` (32 files in DaC) is a real coverage gap this audit
  measured and did not close — the engine's sound scripts, a grammar of its own.
  Its own phase later, or out of scope for V2?

## Decisions
- 2026-08-19: **A twin is compared per TIER, never per building.** A city/castle
  counterpart that trains the unit five levels up is not the same building, and
  a column that said "yes, somewhere" would be worse than none. `unit_instances`
  pairs the blocks once per line (`pair_levels`) rather than once per row.
- 2026-08-19: **A finding is only worth showing if it can come out zero.** The
  Twin column earns its width because DaC has 239 divergent rows and Third Age
  Reforged has none — the same check over both mods is what proves it is reading
  the file rather than describing its own assumptions.
- 2026-08-19: **The one code view that is not a record is read-only BY
  CONSTRUCTION.** `pools` gathers `recruit_pool` lines from a dozen building
  blocks, so no `parse`/`render` pair is registered for it at all — the pane
  cannot be saved from because the machinery to do so does not exist for that
  kind, not because a flag says no. Its `; building` headings are the module's
  own, so it is deliberately absent from `COMMENT_MARKS`.
- 2026-08-19: **One stash slot per LAYER.** The clause dialog used to borrow the
  slot the add-unit picker and the unit view also use, and the unit view can
  open the clause dialog on top of itself — so the two took turns clearing one
  slot and the building form underneath was lost. The dialog has its own now
  (`bldClauseStash`), and how deep the nesting goes stops mattering.
- 2026-08-19: **A redrawing helper checks that its target is on screen.**
  `bldTouched()` re-rendered the building body unconditionally, which is a null
  dereference the moment anything stages an edit from the unit view. Staging
  from another panel marks the working copy and lets that panel draw itself.
- 2026-08-19: **Two files may disagree about a path prefix and both be right.**
  A resource icon is written `data/ui/…` and a religion's pip `ui/pips/…`. The
  redundant half is dropped where the picture is requested, never in a parser —
  neither file is wrong about its own format, and a parser that "corrected" one
  of them would stop round-tripping.
- 2026-08-19: **A unit tier is `;@m2gt tier=3 variant=aor`, on the line above
  the unit's `type`** (user-confirmed). One owned prefix, invisible to the
  engine, skipped by every parser the way `#` is skipped in the EDB.
- 2026-08-19: **A `;@m2gt` line directly above a `type` line starts that unit's
  block.** Otherwise a comment above `type` belongs to the PREVIOUS unit, so the
  marker would describe one unit while living inside another and be left behind
  by every transfer, replace and sort. The change is safe precisely because the
  marker is ours — no real file contains one, so no existing byte-exact
  round-trip can be affected by it.
- 2026-08-19: **The mod's own EDU banners are read before the user is asked for
  anything.** A tier is in no game file, but a hand-organised EDU has already
  written one: **907 of DaC's 916 units sit under a `;--- X TIER N CAT ---`
  banner.** The tier is harvested from there and RECORDED on the unit, which is
  also what breaks a circle — the cleanup rewrites the banners, so a tier living
  only in a banner would be regenerated from itself.
- 2026-08-19: **A table of contents is not a layout.** DaC's TOC names a
  GENERALS section and MERCENARIES / SIEGE / SHIPS sections; the file has none
  of them. All 31 generals sit at the head of their own faction's run and the
  127 mercenaries are spread from unit 11 to unit 891. Faction first, kind
  second, and only the 13 units nobody owns fall through to a shared section.
- 2026-08-19: **A section is the author's own word for it, kept as text and
  never resolved to a faction slot.** Only 146 of DaC's 916 banner names match a
  localised faction name (a modder writes `CRAG`, `DORWINION`), and `ownership`
  cannot stand in because most units list a dozen factions and the line is a
  set, not a ranking. Section ORDER is likewise taken from where it is expressed
  — the median position of each section's units — not from
  `descr_sm_factions.txt`, which is a genuinely different order. Together these
  took DaC from 44% of the roster moving to 15%.
- 2026-08-19: **An untiered unit is never handed a tier by the banner written
  above it.** Its banner is written without a `TIER N`, because reading one back
  would move it out of the untiered group on the second run and cost the sorter
  its idempotence.
- 2026-08-19: **A hand placement is recorded, not just applied.** The ordering
  screen writes `order=N` onto the units it places so the NEXT cleanup honours
  them. A placement the following run silently undoes is a screen that wasted
  the user's time.
- 2026-08-19: **The tier is on the identity tab and deliberately NOT in the
  guided view.** The guided view is a view of real EDU field lines; a value the
  engine never reads does not belong among them, and putting it there would
  blur the distinction the "toolkit only" badge exists to make.
- 2026-08-19: **A byte-order mark is skipped for reading and KEPT for writing.**
  `keyblock.BOMS` / `without_bom` is the one definition, and `code_of` — the only
  function that turns a line into a keyword — drops it, which is safe precisely
  because nothing splices `code_of`'s result back. Stripping it on READ would
  have quietly rewritten the first three bytes of the user's file; this tool
  reads a file, it does not repair it behind their back.
- 2026-08-19: **"Not shipped here" is not the same as "missing".** A check may
  only assert the harsh reading when it can see the thing that would disprove it.
  The ancillary image check asserted a blank slot against a store of BUILDING art
  that could never hold an ancillary picture — 58 false findings across the two
  mods. When the evidence is not there the tool says so once, with the count and
  the way to get the check back, not 56 times.
- 2026-08-19: **A parser reads line endings the way its writer writes them, and
  the two are stated together.** `projectiles`, `mounts` and `engines` read exact
  (`keyblock.read_text`) and write exact (`write_text(..., exact=True)`); the rest
  read and write translating. Mixing the two turns every CRLF into CRCRLF. A block
  appended from a SOURCE mod is rewritten to the DESTINATION file's own ending
  (`keyblock.newline_of` / `to_newline`).
- 2026-08-19: **What must be forgotten is derived, never listed.**
  `Mod.drop_caches()` walks the class's own `cached_property` set. The two
  hand-written lists it replaces had drifted to 17 and 14 of 23, and
  `ownership_factions` was answering out of an EDU that had already been replaced.
- 2026-08-19: **A test names the mod it PREFERS, never the mod it requires**
  (`tests/_realmod.pick`). A suite that dies because a mod is not installed tells
  you nothing, and its silence is indistinguishable from a pass — three suites
  had been hiding two real defects that way.
- 2026-08-19: **The audit's two mention maps are not interchangeable, and no
  longer share a name.** `name_mentions` is keyed by modeldb ENTRY name with a
  row per name; `_mount_mentions` is keyed by MOUNT name with a bare filename.
  `mount_audit` took the first as a parameter and then shadowed it with the
  second, so its two model-keyed lookups read the mount map — wrong answers for
  `frees_model`, and a hard `TypeError` out of `mention_file` the moment a mount
  and an entry shared a name (four do in DaC, which is why `test_eop_and_lua`
  could not get past its first audit). The mount map is now `by_mount` and each
  lookup takes the map its key belongs to. `mention_file` reads either shape,
  because both maps are legitimately passed to it.
- 2026-08-19: **Hiding is a pair, not a filter.** The code view drops the
  comment-only lines from what it SHOWS, and the server rebuilds the real bytes
  from the view plus an opaque `hidden` list before anything parses or saves.
  The page still never learns what a comment looks like in a game file, and
  `buildings.py`'s rule — every one of the 7203 commented lines goes back byte
  for byte — is kept by construction rather than by care.
- 2026-08-19: **A hidden line is anchored to the KEYWORD of the line it sat
  above**, then to that line's exact text, then to its index. Anything else and
  typing a new value into the line below a comment moves the comment.
- 2026-08-19: **The tool's own layout pass is not the user's change.** The code
  view lines a record up as it opens; that is remembered separately (`cv.auto`)
  so the dialog is not "dirty" for having been looked at, while a save that
  happens for any other reason still writes the tidied block. A view that
  reports unsaved work you did not do is worse than a ragged file.
- 2026-08-19: **A paired row is written in the pair's order, not the file's.**
  `GF_PAIRS` decides which cards share a line; the group is emitted where its
  first member appears. It is the only place in the guided view where a card's
  position comes from anything but the file, so it is guarded by name.
- 2026-08-19: **Rows are placed from spans, never by counting.** Raw-lines mode
  lines each box up with the file line the SERVER says it came from. Counting
  rows drifts the moment a block has a `type` line, a hidden comment or a repeat
  — which every real block does.
- 2026-08-19: **A reveal is mod-relative.** `POST /api/reveal` takes a mod and a
  path under that mod's data folder and resolves it there; it never accepts an
  absolute path from the page.
- 2026-08-18: A startup check failing exits **2**, not 1, so the launcher points
  at the printed checks instead of guessing at a cause.
- 2026-08-18: "Could a server bind this port?" is asked by **binding** it. A
  connect cannot answer it: with a timeout set `connect_ex` returns the same code
  for a closed port and a wedged listener, and a closed loopback port can time out
  rather than refuse.
- 2026-08-18: A restart in place spawns the replacement FIRST (with `--wait-port`)
  and lets go of the port after. Stopping first ends the process before it can
  spawn anything.
- 2026-08-18: `config._read_json` tells **gone** from **busy**: the last-read
  fallback is for the moment `os.replace` makes a file unopenable, not for a file
  that has been deleted (audit §1.5).
- 2026-08-18: The log is **paged** — `/api/log` answers with a window plus the
  counts a filter needs, and computes `newer_count` itself, because "revert to
  here" was the only reason the page ever wanted the whole file.
- 2026-08-18: **The log records the user's actions too**, batched through
  `/api/activity` and written as untrusted text. A record of effects with no
  causes cannot be read back.
- 2026-08-18: An editor takes an undo baseline (`undoReset()`) at the point its
  working copy exists. Without one the first edit becomes the baseline, which is
  how five editors ended up looking as if Ctrl+Z was broken.
- 2026-08-18: **A cache never lives next to the app.** `config.cache_dir()` puts
  derived data in `%LOCALAPPDATA%`, because the app can be unzipped into OneDrive
  and a synced cache file can take 79 seconds to read or fail outright.
  `config/` stays put — it is the user's own data, not derived.
- 2026-08-18: **Traffic is liveness.** Any request keeps the server up; the
  heartbeat only still proves that a page really rendered. A heartbeat can be
  starved by the page's own requests, and the watchdog was killing live sessions.
- 2026-08-18: A resolved mod is trusted for one second before its files are
  re-checked (our own writes call `invalidate()`), and every load takes a
  generation and an abort signal — a superseded load is dropped, never painted.
- 2026-08-13: V2 architecture locked — vanilla-UI ports only; shared 2-way Code View widget built once (Phase 4); rebrand everywhere except GitHub repo name; version stays 1.x until Campaign Map lands (=2.0.0).
- 2026-08-13: Author permission obtained for reference-tool reuse; no licensing blocker.
- 2026-08-18: Every note in the UI is a lead line plus points (`docPoints()`), not prose joined by em dashes. Em dashes stay in code comments and in short appositives.
- 2026-08-19: **A measurement is fixed before the thing it measures.** 14g opened
  on "115 hits"; six of them were writing and the rest were
  `tools/prose_check.py` failing to stitch the `+` continuations its own
  docstring promised to stitch, reading `\'` as the end of a string, and taking
  inline CSS for prose. Rewriting 90 correct sentences to please a broken reader
  would have made the code worse and the next count meaningless.
- 2026-08-19: **A list is not a sentence, and neither is a fragment.** The `syn:`
  lines name a record's value slots in file order and every word in them is an
  EDU term that is lower case by definition; a string spliced into a sentence
  built at render time cannot be judged on its own first letter. Both are now
  rules in the checker, alongside the older "a label is not a sentence".
- 2026-08-18: A vocabulary the mod's own file declares is read from that file, never hardcoded — banners were the last EDU list breaking that rule.
- 2026-08-18: A test that measures a shipped mod reports the finding and asserts only OUR behaviour; it never fails because a mod has a bug.
- 2026-08-18: `#` at the start of an EDB line is a modder's annotation, not a keyword (the file's comment marker is `;`) — skipped by every parser in buildings.py, preserved verbatim on write.
- 2026-08-18: A count measured over installed mods is load-bearing only when the code leans on it. `plan_new_tree` writes an empty `plugins { }` because every real one is empty, NOT because every line has one — Third Age Reforged omits it on 45 of 112 and runs.
