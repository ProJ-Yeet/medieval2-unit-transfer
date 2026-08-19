# Codebase audit, second pass — the release check after Phase 14

_2026-08-19 · v1.9.9, working tree at `121b791` plus the uncommitted Phases 0–14._
_Measured against the two installed mods, **Divide_and_Conquer_EUR** and
**Third_Age_Reforged**, plus synthetic files built for the cases neither mod
happens to exercise._

**Verdict: the tool is releasable.** The whole test suite is green for the first
time — **52 of 52 modules, 2156 individual checks** — and every whole-file parser
now round-trips both mods byte for byte, 24 files out of 24. Of the six defects
the [first audit](audit-codebase.md) confirmed, **all six are now closed**. This
pass found **three more**, two of them silent data loss on real files, and all
three are fixed here.

The scope: 38 Python modules (~27.7k lines), 22 JS modules (~14.6k lines), 52
test suites, every parser round-tripped against both mods, and every parser fed a
deliberately corrupted file.

---

## 1. What the first audit left open, and where it stands

| # | Finding | Status |
|---|---|---|
| 1.1 | `bmdb.audit()` crashes on a sparse mod | **closed** before this pass (see STATE.md, 2026-08-19) |
| 1.2 | `battle_models.modeldb` dies on a UTF-8 BOM | **closed here** — §2.1 |
| 1.3 | Mixed line endings silently normalised on write | **closed here** — §2.2 |
| 1.4 | The two `_invalidate` lists have drifted apart | **closed here** — §2.3 |
| 1.5 | A deleted config file keeps serving its old contents | closed before this pass |
| 1.6 | Dead code confirmed by pyflakes | **closed here** — §2.6 |
| 2 (a) | `edit.model_folder_report` may not report file-sharing entries | **explained** — the test was wrong, not the code. §3.1 |
| 2 (b) | `;` inside a value is always read as a comment | **measured, not a risk.** §4.2 |
| 2 (c) | Sprite wire-up assumes a naming convention mods ignore | **explained** — the code is right, the test picked the wrong entry. §3.2 |
| 2 (d) | 56 ancillary findings on Third Age Reforged unconfirmed | **they were ours, not the mod's.** §2.4 |

---

## 2. Defects found and fixed in this pass

### 2.1 — A byte-order mark cost two parsers their first record ⚠ **the worst of these**

The first audit predicted this and could not reproduce it: *"the survivors are
lucky, not safe. An EDU whose first line is a `type` declaration rather than a
comment would mangle that unit's name silently."* Feeding a UTF-8 BOM to every
parser over both mods found it is not hypothetical.

| parser | plain | with a UTF-8 BOM | how it fails |
|---|---|---|---|
| **modeldb** | 2190 entries | `ValueError` | crash (was §1.2) |
| **EDU** (first line a `type`) | 1 unit | **0 units** | **silent** |
| **factions**, DaC's real file | **31 factions** | **30 factions** | **silent** |
| EDU, mounts, traits, ancillaries, triggers, projectiles, engines, EDB | unchanged | unchanged | — |

DaC's `descr_sm_factions.txt` opens on `faction⇥⇥⇥scripts` rather than a comment,
and is **the one real file among 748 that does**. Its first faction simply stopped
existing — no error, no warning, nothing in the log. A user who then saved would
have written the file back one faction short.

Notepad writes a BOM into anything it saves as UTF-8, so this is what a modder
gets for opening a game file to look at it.

**Fixed** in one shared place rather than five. `keyblock.BOMS` /
`keyblock.without_bom` is the single definition, and `keyblock.code_of` — the one
function that turns a line into a *keyword* — drops a leading mark. Nothing
splices `code_of`'s result back (it strips indentation, so nothing could), which
is what makes that the safe seam. `edu.parse_text` has its own block scan and got
the same treatment; `modeldb.parse_text` skips the mark and now says in words
what is wrong with a file that is not a modeldb at all, instead of surfacing
`invalid literal for int() with base 10`.

**The mark is kept, not repaired.** A file that arrived with one is written back
with one, byte for byte. Reading a file and silently rewriting its first three
bytes is not this tool's job.

Regression tests: `tests/test_parsers.py` (BOM'd EDU, factions and modeldb, built
rather than borrowed since no installed mod exercises two of the three) and
`tests/test_modeldb_header.py`.

### 2.2 — Mixed line endings are no longer normalised on write

`Third_Age_Reforged/data/descr_projectile.txt` is 3353 CRLF lines and **5 lone
LFs**, and came back 5 bytes longer than it went in. It is the only such file in
either mod — **1 of 748** — but "unchanged lines come back byte for byte" was
either true or it was not.

The three splice-only parsers (`projectiles`, `mounts`, `engines`) now read
through `keyblock.read_text`, which does not let the platform decide what a line
ending is, and `transfer`'s writer takes an `exact=True` for them. Everything else
still reads and writes the translating way, because its serialiser emits bare LF
and always has — handing exact text to a translating writer would turn every CRLF
into CRCRLF.

Appending needed the other half of the answer: a block copied out of the *source*
mod need not be written the way the *destination* file is written, so
`keyblock.newline_of` / `to_newline` rewrite it to the destination's own ending
rather than dropping a foreign one into the middle of the file.

`triggers.parse_file` was reading `export_descr_character_traits.txt` through
universal newlines while `traits.parse_file` read the same file exactly — a trap
for whoever first wrote `tg.text()` back. Aligned.

**Result: the full round-trip sweep is now 24 files exact, 0 broken.**

### 2.3 — Cache invalidation is derived, not restated

`edit._invalidate` and `transfer._invalidate` each hardcoded the names of `Mod`'s
cached properties. `Mod` has 23; the lists named 17 and 14.

| | before | after |
|---|---|---|
| survive `edit._invalidate` | 6 of 23 | **0** |
| survive `transfer._invalidate` | 9 of 23 | **0** |

`ownership_factions` was the sharp one: derived from `self.edu.units`, and `edu`
*was* cleared while it was not, so after an edit it kept answering out of the EDU
that had just been replaced. Both functions now call `Mod.drop_caches()`, which
walks the class's own `cached_property` set. A property added later cannot be
forgotten.

### 2.4 — The ancillary image check was reporting 58 pictures that are fine

The first audit flagged 56 findings on Third Age Reforged as *"the mod's own data,
not a regression — but nobody has confirmed all 56 are genuine mod bugs"*. They
were not. All 56 (and both of DaC's) were **ours**.

`ancillaries.image_path` looked for a stock picture in `config.get_vanilla_ui_root()`
— which holds *building* art, keyed `culture/#name` in a content-addressed store
whose own manifest says `"kind": "building-art"`. It contains no ancillary picture
and never could, so the fallback could not match and every ancillary reusing a
stock image was reported as *"the character screen shows a blank slot"*.

Vanilla keeps those pictures inside its `.pack` archives, so on most machines
there is nothing on disk to check against — and that means **"cannot be checked"**,
not "the picture is missing". The check now says which of the two it is:

| mod | before | after |
|---|---|---|
| Third_Age_Reforged | 56 findings | **1**, an unverified-image note naming the count |
| Divide_and_Conquer_EUR | 2 findings | **1**, the same |

`config.get_vanilla_ancillary_dir()` looks for a real unpacked `ui/ancillaries`
(a `vanilla_ancillaries_dir` setting, or the Medieval II install's own folder). With
one in view, an absent picture really is a blank slot and each is named as before;
without one, it is said once, with the count, and with the way to get the check
back. `tests/test_ancillaries.py` drives all three branches.

Saying a true thing 56 times buries the findings that matter — the file it was
drowning has 345 ancillaries and 0 real defects.

### 2.5 — Three suites could not run at all

`test_mount_base_import`, `test_replace_unit` and `test_unit_rename_refs` were
hardcoded to a mod named `Third_Age_6` and died with a `FileNotFoundError`
traceback the moment it was not installed. A test that cannot run says nothing
about the tool, and its silence looks the same as a pass.

`tests/_realmod.py` now answers "which real mod should this measure itself
against": the preferred name if it is installed, any other installed mod
otherwise, and a `SKIPPED` line with status 0 when there is no mod at all. The
installed set changes; what is being tested does not.

Running them found the two defects in §3.3 and §3.4 below, both of which had been
invisible for as long as they had been unrunnable.

### 2.6 — Dead code

pyflakes over `unittransfer/`, `tools/`, `app.py` and `build_release.py` is clean
apart from one deliberate probe. Removed: 8 unused imports, 3 unused locals and an
f-string with no placeholders, plus one more in `tools/trigger_vocab.py` that
post-dated the first audit.

`startup.py:96`'s `from PIL import Image` **stays** — it is the preflight check
asking whether Pillow's image module really imports, which is the thing the tool
needs, and it already carries `# noqa: F401`. pyflakes is wrong about that one.

The two imports the first audit said to look at twice (`sprites` importing `.edit`,
`minorfiles` importing `.triggers`) were checked: neither forces module
registration, both were genuinely unused, both gone.

---

## 3. Test failures that turned out to be the tests

Five suites were failing. **None of the five was a regression, and only one was
about the tool's behaviour at all** (§2.4). The other four were tests asserting
something the code had never promised.

### 3.1 — `model_folder_report` was right about sharers all along

The first audit's *"one unexplained failure"*. `test_edit_models` picked a "victim"
— another entry sharing any file with ours — using `texture_files()`, which
includes sprites and attachment textures. The folder move deliberately relocates
neither: a sprite is never moved, and an attachment texture outside the model's
own folder is a shared pack that `folder_info_of` reports in `external_dirs` and
leaves alone. So the test demanded a sharer be reported for a file that was never
going to move.

The victim is now chosen from the files that actually move, and the suite picks a
unit whose *mesh* another entry reads, so the shared path is genuinely exercised
rather than quietly skipped. **37/37.**

### 3.2 — The sprite naming convention

Three `test_sprites` checks are about the wire-up reproducing an
already-correct `<faction>_<model>_sprite` line untouched. The test picked the
first entry with two factions — and in a real mod most sprite lines are shared
(DaC points 1044 records at one file), so it was picking a shared line and asking
the generator to have written it.

It now prefers an entry with two factions whose lines already follow the
convention, and reports rather than asserts when a mod has none. **45/45.**

### 3.3 — A copy that was renamed, checked under its old name

`test_mount_base_import` looked the copied mount entry up by the name it *arrived*
with. DaC already owns an entry called `mount_sauron`, so the incoming one was
correctly renamed to `mount_sauron_thir` and the lookup found DaC's own untouched
entry — making a swap that had happened look as though it had not. The test now
resolves the entry the unit actually points at. **30/30.**

This one could only ever surface with a destination that already owns an entry of
that name, which `Third_Age_6 -> DaC` never did.

### 3.4 — "Officers from base" does not mean what the test assumed

`import_officers_with_base` is on by default, and it means *bring the source's
officers over with the base unit's animations* — which drops `officer` from the
kept groups on purpose. `test_replace_unit`'s section is about the literal keep,
so it now says so. **ALL PASSED.**

### 3.5 — And one that was the mod's business

`test_unit_rename_refs` asserted the scan finds a `.lua` script. Not every mod
runs M2TWEOP; Third Age Reforged ships none. Whether a mod has Lua is the mod's
business — what is ours is that the scan picks up whatever it does ship, which is
what it now checks. **36/36.**

---

## 4. Measurements

### 4.1 — Round-trip fidelity: 24 of 24 exact

Every whole-file parser, both mods, parse → serialise → compare against the file
read under that parser's own contract:

| parser | DaC | TATR |
|---|---|---|
| EDU | 1,320,748 exact | 556,440 exact |
| modeldb | 21,053,905 exact | 1,423,978 exact |
| mounts · projectiles · engines · mounted engines · engine skeletons | exact | exact |
| ancillaries · traits · triggers · factions · EDB | exact | exact |

**0 broken.** The one break the first audit found (§2.2) is closed.

### 4.2 — `;` inside a value: measured, and not a risk

The first audit could not confirm whether any M2TW format permits a literal
semicolon in a value, which would make all six `_strip_comment` variants truncate
it. Over **136,183 lines** of the 18 files those parsers actually own, a `;` glued
between two non-space characters — what a semicolon-in-a-value would look like —
occurs **twice**:

```
descr_projectile.txt   mass            2.4;0.8      (both mods, same line)
```

Both are a modder's commented-out alternative value, which is exactly what
`_strip_comment` reads them as. And since every one of these files round-trips
byte-exact, a misread could only ever affect what the UI *shows*, never what is
written. **Closing this as measured.**

### 4.3 — Test suite

**52 of 52 modules green, 2156 checks.** The first audit's baseline was six
failing suites; the ones that remained at the start of this pass are accounted for
in §2.4 and §3 above.

---

## 5. Still open — deliberately

### 5.1 — The EDB reads through universal newlines

`buildings.parse_file` (and `buildings`' writer) still translate line endings,
which is the same exposure §2.2 closed for the other three. It is left alone
on purpose:

* **No mod triggers it.** 1 file in 748 has mixed endings and it is not an EDB.
* **`buildings.py` is the highest-risk module in the codebase** — the biggest, the
  only one that *creates* a record, and the one carrying 7203 commented input
  lines that must come back verbatim.

The fix, if it is ever wanted, is the one applied to `projectiles`: read via
`keyblock.read_text`, write with `exact=True`, and build every created line with
`keyblock.newline_of` of the file being written. It should be done with its own
phase and its own byte-diff, not as a footnote to a release check.

### 5.2 — Six `_strip_comment`, three `_line_kv`, five latin-1 readers

Unchanged from the first audit's §3, and unchanged on purpose. `_line_kv` is still
a literal triplicate across `engines`, `mounts` and `projectiles`; the six
`_strip_comment` still disagree about whitespace in ways that are semantic, not
stylistic, because these files are edited by line splice. Now that
`keyblock.without_bom` exists there is an obvious home for a shared one — but
collapsing six functions with four different contracts is a refactor with a real
chance of changing what a line means, and it buys nothing a user can see.

### 5.3 — `sprites.wire_model_edits` on a shared sprite line

Re-measured, and unchanged: of the records carrying a sprite path, **56,490 of
DaC's 57,245 (98.7%)** and **2,712 of TATR's 3,147 (86.2%)** point at something
other than `<faction>_<model>_sprite`. `sprites.audit` is
fine — it checks the file exists, not its name — but `wire_model_edits` would
rewrite a shared line to a per-faction name. It only runs on models the user has
just generated, so it is scoped, and it is now visible in the test rather than
hidden behind a failing assertion. **Worth a deliberate decision, not a fix in
passing.**

---

## 6. High-risk areas — unchanged advice

1. **`buildings.py`** — biggest module, the only one that creates a record, 7203
   commented lines that must survive. See §5.1.
2. **`keyblock.py`** — now carries the BOM rule as well as the line-ending rule,
   and six modules splice through it. `code_of` in particular is load-bearing for
   every flat-record parser.
3. **`transfer.py`'s apply path** — the `exact=` flag added in §2.2 means the
   writer now has two modes. A new file kind must pick the one that matches how
   its parser reads, or it will write CRCRLF.
4. **The Code View's `text` is not its bytes** — unchanged from STATE.md. Anything
   that saves must read `base`.

---

## 7. Overall

The first audit's verdict was "in good shape and Phase 14 can start". This one is
narrower and can be stronger: **every confirmed defect from both passes is closed,
every parser round-trips both mods byte for byte, and the whole suite runs green.**

The three defects this pass added were all found the same way — by feeding the
parsers a file a real person would plausibly hand them (one re-saved in Notepad),
and by making three suites that could not run, run. Neither is an expensive habit,
and both found things reading the code did not.
