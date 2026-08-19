# Codebase audit — the baseline before Phase 14

> **Renumbered 2026-08-18:** "Phase 14" throughout this document means the 3D
> model viewer, which is now **Phase 15** — a bug-fix and polish pass was
> inserted ahead of it as Phase 14, and §1.1 / §1.4 / §1.5 / §2 / §6 below are
> carried by that phase. The body is left as it was written.

_2026-08-18 · v1.9.9, working tree at `121b791` plus the uncommitted Phases 0–13.
Measured against the two installed mods, **Divide_and_Conquer_EUR** and
**Third_Age_Reforged**, plus synthetic mods derived from them._

**Verdict: the tool is in good shape and Phase 14 can start.** Nothing found is
architectural, nothing requires a rewrite, and the parsers — the part with the
most to lose — are the strongest thing here. There are **six confirmed defects**,
of which **one is a hard crash on real data** and should be fixed before Phase 14
touches anything else. The rest are small and independent.

The scope of what was checked: 25 Python modules (~26k lines), 18 JS modules
(~11k lines), 50 test suites, and every parser round-tripped against real files.

---

## 1. Confirmed issues

### 1.1 — `bmdb.audit()` crashes on a sparse mod ⚠ **fix first**

`unittransfer/bmdb.py:365` passes the wrong map into the wrong function:

```python
"mentioned_in": mention_file(mentions, model) if entry is not None else "",
```

`mentions` here is the `Dict[str, str]` from `_mount_mentions` (line 339), but
`mention_file` (line 428) was written for the `Dict[str, dict]` that
`name_mentions` returns, and does `row["file"]`. When the lookup *hits*, that
indexes a string with a string:

```
TypeError: string indices must be integers, not 'str'
```

Reproduced deterministically. It needs a dead mount whose **model** name collides
with a **mentioned mount** name — so both full mods escape it by luck, but any mod
shipping a smaller set of `descr_*.txt` hits it:

| mod | full install | trimmed to `descr_mount` + `descr_character` |
|---|---|---|
| Divide_and_Conquer_EUR | audit OK | **CRASH** |
| Third_Age_Reforged | audit OK | audit OK |

This is what `tests/test_eop_and_lua.py` has been failing on — it builds exactly
that trimmed mod. The failure is **ours, not the test's**.

Three separate mistakes are tangled here, and all three want fixing together:

1. **A dead parameter.** `mount_audit(mod, users, mentions, report)` takes
   `mentions` and then overwrites it on line 339. The caller (line 676) computes
   and passes a value that has never been read.
2. **A namespace confusion.** `mentions` is keyed by *mount name*; `model` is a
   *model name*. Looking one up in the other is meaningless even when it doesn't
   crash.
3. **A casing mismatch.** `_mount_mentions` keys by the mount's original casing
   (`Boar` in DaC, `black_spidersA` in TATR). Line 361 tests `model not in
   mentions` with a lowercased name and line 431 lowercases again — so
   `frees_model` is computed against a lookup that nearly always misses.

Line 1176 already works around the casing by rebuilding the map
(`{k.lower(): v for k, v in _mount_mentions(mod).items()}`), which is the tell
that the contract was never settled.

**Fix:** drop the `mentions` parameter from `mount_audit`, have
`_mount_mentions` return lowercase keys (and fix the two call sites that
compensate), and drop the `mention_file` call — the mount rows want
`mentions.get(...)` directly, not the `name_mentions` accessor.

### 1.2 — `battle_models.modeldb` dies on a UTF-8 BOM

A modder who opens a modeldb in Notepad and saves it gets a BOM. The parser reads
latin-1, so the BOM survives as `ï»¿` glued to the first token — which is the
entry count:

```
ValueError: invalid literal for int() with base 10: 'ï»¿22'
```

Tested by prefixing a BOM to seven real files and re-parsing. Only the modeldb
breaks — every other parser survives because its first line is a comment or blank,
so the mangled token lands somewhere harmless:

| parser | plain | with UTF-8 BOM |
|---|---|---|
| EDU | 916 units | 916 units |
| **modeldb** | **2190 entries** | **`ValueError` (unhandled)** |
| mounts | 89 | 89 |
| traits | 799 | 799 |
| ancillaries | 703 | 703 |

Two things are wrong: the BOM isn't tolerated, and the error that reaches the user
is a raw `ValueError` naming an integer conversion, which tells them nothing about
what to fix. `luascan._read` and `modfiles` already strip BOMs — the handling
exists, it just isn't shared (see §3.1).

**Note the survivors are lucky, not safe.** An EDU whose first line is a `type`
declaration rather than a comment would mangle that unit's name silently. Neither
installed mod is written that way.

### 1.3 — Mixed line endings are silently normalised on write

`Third_Age_Reforged/data/descr_projectile.txt` carries 3353 CRLF line endings and
**5 lone LFs**. Parsers read with universal newlines, so both collapse to `\n`;
the writer emits `\r\n` throughout. The file comes back 5 bytes longer:

```
byte 12870 (line 430)   96,016 -> 96,021
  orig: b'effect_only\r\n\n;------'
  out : b'effect_only\r\n\r\n;-----'
```

This is the **only** fidelity break in the whole round-trip sweep (§4), and it
contradicts the byte-exactness the modules claim. Harmless to the engine, but it
means "unchanged lines come back byte for byte" is not quite true, and a diff
against the user's original will show noise they didn't cause.

### 1.4 — The two `_invalidate` lists have drifted apart

`edit._invalidate` (edit.py:1426) and `transfer._invalidate` (transfer.py:2306)
each hardcode the names of `Mod`'s cached properties. `Mod` has **23**; the lists
name 17 and 14. Measured by populating every cache and calling each:

| | caches populated | **survive invalidation** |
|---|---|---|
| `edit._invalidate` | 22 | **6** |
| `transfer._invalidate` | 22 | **9** |

Surviving both: `cultures`, `faction_cultures`, `faction_names`, `icon_factions`,
`lua_files`, `ownership_factions`. Surviving `transfer` only, and the clearest
sign the two have drifted: `edb`, `edb_vocab`, `building_loc`.

`ownership_factions` is the sharp one — it is derived from `self.edu.units`, and
`edu` *is* cleared. So after an edit it keeps answering from the EDU that was
replaced. Whether a user sees it depends on the `Mod` object being reused, which
`server.py:417` does cache.

**Fix:** derive the list from `Mod` rather than restating it —
`[n for n in dir(Mod) if isinstance(getattr(Mod, n, None), cached_property)]` —
and delete both hardcoded tuples. A new cached property then cannot be forgotten.

### 1.5 — A deleted config file keeps serving its old contents

`config._read_json` (config.py:55) treats "the file cannot be opened" as "a writer
is mid-`os.replace`" and answers from `_JSON_CACHE`. That is deliberate and the
comment explains why. But `_stamp` returns `None` for a **deleted** file too, so
the same branch runs: delete `settings.json` and the process keeps returning the
settings it had.

This is what `tests/test_startup.py` fails on ("unset root: reported, not fatal") —
again, the test is right. A user deleting `settings.json` to reset the tool sees
no effect until restart.

**Fix:** serve the cached body only when the file still exists (`stamp is not
None`), or bound the fallback to a few retries. The `os.replace` window is
microseconds; a deletion is permanent.

### 1.6 — Dead code confirmed by pyflakes

Small and unambiguous — 8 unused imports and 3 unused locals:

```
codeview.py:40   'typing.Callable' imported but unused
keyblock.py:41   'typing.Optional', 'typing.Tuple' imported but unused
minorfiles.py:73 '.triggers' imported but unused
modfiles.py:23   'typing.Optional' imported but unused
pack.py:38       'typing.Dict' imported but unused
sprites.py:49    '.edit' imported but unused
triggers.py:45   're' imported but unused
startup.py:96    'PIL.Image' imported but unused
factions.py:384  local variable 'slot' assigned but never used
server.py:944    local variable 'audit' assigned but never used
bmdb.py:731      f-string with no placeholders
```

`sprites.py:49` importing `.edit` and `minorfiles.py:73` importing `.triggers` are
worth a second look before deleting — an unused intra-package import sometimes
exists to force module registration. Neither appears to here, but check.

---

## 2. Potential issues — need verification

- **`edit.model_folder_report` may not report file-sharing entries.**
  `test_edit_models` fails two checks ("report names the sharers", "the sharing
  entry was repointed with it") on Third_Age_Reforged. The test *did* find a
  sharing entry, so the report should have named it. Either a real bug in the
  sharer walk or a test assumption about which entry gets picked. **Worth
  confirming before Phase 14** — it is the one unexplained failure.

- **`;` inside a value is always a comment.** All six `_strip_comment` variants
  split unconditionally on the first `;`. If any M2TW format permits a literal
  semicolon in a quoted value, that value is truncated silently. Neither installed
  mod exercises it; I could not confirm the formats forbid it.

- **Sprite wire-up assumes a naming convention the mods mostly ignore.** Measured
  over every faction record carrying a sprite path:

  | mod | records with a sprite | follow `<faction>_<model>_sprite` | do not |
  |---|---|---|---|
  | Divide_and_Conquer_EUR | 57,245 | 756 (1.3%) | **56,489** |
  | Third_Age_Reforged | 3,147 | 435 (13.8%) | **2,712** |

  Real mods share one sprite across many entries — DaC points 1044 records at
  `hre_snaga_skirmishers_sprite.spr`. `sprites.audit` is fine (it checks the file
  exists, not its name), but `_model_casing`'s casing recovery finds nothing to
  recover 98.7% of the time, and `wire_model_edits` would rewrite a shared line to
  a per-faction name. It only runs on models the user just generated, so this is
  scoped — but it is worth deciding deliberately rather than by default. This is
  also why three `test_sprites` checks fail: they assume the picked entry follows
  the convention, and DaC's `mount_naru_horse` points every faction at
  `unit_sprites/nazgul_sprite.spr`.

- **`ancillaries` reports 56 findings on Third_Age_Reforged** (`test_ancillaries`
  80/81). Per the 2026-08-18 decision this is the mod's own data, not a
  regression — but nobody has confirmed all 56 are genuine mod bugs.

---

## 3. Duplicate and overlapping functionality

First, the good news: most of what looks duplicated **is a deliberate protocol**.
`parse_file` / `parse_text` / `overview` / `plan` / `apply` / `render_block` /
`block_spans` appear in 5–12 modules each because every editor module implements
the same interface. That is the architecture working. Leave it alone.

The genuine duplication is smaller and mostly in helpers.

### 3.1 — Six `_strip_comment`, four different contracts

| module | implementation | contract |
|---|---|---|
| `buildings` | `find(";")`, returns `(code, comment)` | **tuple** — different signature |
| `engines` | `split(";",1)[0].rstrip()` | trailing strip |
| `mounts` | `split(";",1)[0].rstrip()` | *identical to engines* |
| `projectiles` | `split(";",1)[0].rstrip()` | *identical to engines* |
| `sounds` | `split(";",1)[0].strip()` | **strips both ends** — loses indent |
| `triggers` | `split(";",1)[0]` | **no strip at all** |

Three are byte-identical copies; the other three disagree about whitespace. Since
these files are edited by line splice, "does the code part keep its indentation"
is a real semantic difference, not a style one.

`_line_kv` is a **literal triplicate** across `engines`, `mounts` and
`projectiles` — same seven lines, same docstring.

### 3.2 — Five file readers, and only one strips a BOM

`bmdb._read_text`, `unitrefs._read`, `luascan._read`, `eop._read`,
`edbvocab._read` are all "read as latin-1, return `''` on `OSError`". Only
`luascan._read` drops a UTF-8 BOM. That inconsistency is the root of §1.2.

`keyblock.read_text` is **not** a duplicate — it preserves line endings on
purpose, and its docstring explains why. Keep it distinct.

### 3.3 — Two generations of shared record infrastructure

`keyblock` (the byte-exact splice engine) is well adopted: 6 modules.
`flatrecord` (the newer "declare a SHAPE" layer) is adopted by **2** —
`factions` and `minorfiles`. Where it is used it collapses a function to one line:

```python
def block_spans(block: str) -> Dict[str, List[List[int]]]:
    return fr.record_spans(SHAPE, block)
```

Meanwhile `ancillaries`, `traits` and `triggers` each hand-roll `parse_block`,
`block_spans` and `block_fields`. They predate `flatrecord` and were never
migrated.

**This is the one architectural observation in the audit — and it is not a
recommendation to migrate.** Those three have shapes `flatrecord` may not express
(traits have levels; triggers have conditions and effects). The honest summary is
that the layering is sound but its adoption is uneven, and STATE.md's "check
`flatrecord.py` before writing any parser" is the right instruction for Phase 14.
Migrating existing modules would be high-risk, low-reward churn.

---

## 4. Parsing and test results

### Round-trip fidelity — the headline result

Every whole-file parser was run over both mods: parse → `write()` → compare
**bytes** with the original.

| file | Divide_and_Conquer_EUR | Third_Age_Reforged |
|---|---|---|
| `export_descr_unit.txt` | byte-exact (1,356,325 B) | byte-exact (572,710 B) |
| `battle_models.modeldb` | byte-exact (21,520,695 B) | byte-exact (1,462,193 B) |
| `export_descr_buildings.txt` | byte-exact (1,600,517 B) | byte-exact (333,402 B) |
| `descr_projectile.txt` | byte-exact (103,767 B) | **+5 B** (§1.3) |
| `descr_mount.txt` | byte-exact (31,451 B) | byte-exact (21,499 B) |
| `export_descr_sounds_units_voice.txt` | byte-exact (1,320,721 B) | byte-exact (2,390,434 B) |

**11 of 12 byte-exact, including a 21 MB modeldb.** The one miss is 5 bytes of
line-ending normalisation. This is the strongest evidence in the audit that the
core is sound.

> An earlier pass comparing `to_text()` against raw bytes showed all 12
> "failing" — that was the harness, not the code. `to_text()` returns `\n` and
> the `write()` path restores `\r\n`, exactly as `keyblock.read_text` documents.
> The table above is the corrected comparison.

### Test suite baseline

All 50 suites, run as `python -m tests.<name>`. **42 passed.** (Note: `pytest`
is not installed and the suites do not use it — they are standalone scripts.)

| failure | cause | ours? |
|---|---|---|
| `test_eop_and_lua` | §1.1 crash | **yes — real defect** |
| `test_startup` | §1.5 deleted-file cache | **yes — real defect** |
| `test_edit_models` | 2 sharer checks | **unresolved — see §2** |
| `test_sprites` | 3 checks assume the sprite naming convention | no — mod data |
| `test_ancillaries` | TATR ships 56 EDA findings | no — mod data |
| `test_mount_base_import` | hardcoded `Third_Age_6`, not installed | no — test fixture |
| `test_replace_unit` | hardcoded `Third_Age_6`, not installed | no — test fixture |
| `test_unit_rename_refs` | hardcoded `Third_Age_6`, not installed | no — test fixture |

**Test-fixture debt worth fixing:** 3 suites hardcode `Third_Age_6` and simply
crash with `FileNotFoundError` when it is absent. Others already do the right
thing — `test_buildings.py` picks from a `CANDIDATES` tuple, `test_eop_and_lua`
uses a `next(...)` fallback chain. Applying that same pattern to the three would
take the suite from 42/50 to 45/50 without touching any product code, and would
stop the mod set changing under you from looking like a regression.

### Error handling

Checked deliberately, and it is **clean**: no bare `except:`, and **zero**
instances of `except ...: pass` or `except ...: continue` swallowing an error
across all 25 modules. Handlers name their exception types
(`OSError`, `UnicodeError`, `ValueError`). The broad `except Exception` uses are
confined to `logutil`, `startup` and `server` request handlers, which is where
they belong.

The error-handling weaknesses that do exist are about *message quality*, not
silence — §1.2's raw `ValueError` being the clearest example.

---

## 5. Recommended refactors

Ordered by value. The first two are the only ones I would do before Phase 14.

1. **Fix `mount_audit` (§1.1).** Drop the dead parameter, settle the key casing,
   drop the `mention_file` call. Removes a crash, a dead parameter and a
   meaningless lookup at once. ~10 lines.
2. **Derive the `_invalidate` list from `Mod` (§1.4).** Deletes two hardcoded
   tuples that have already drifted, and closes the class of bug permanently
   rather than re-listing the names correctly once. ~6 lines, replaces ~16.
3. **One shared `read_latin1(path)` helper** with the BOM strip, used by the five
   private readers (§3.2, §1.2). Keep `keyblock.read_text` separate.
4. **One shared `_strip_comment` and `_line_kv`** in a small `textutil` (§3.1).
   Do this *deliberately*: pick a whitespace contract, then check each of the six
   call sites against it rather than assuming. `buildings`' tuple-returning
   version should keep its own name — it is a different function.
5. **Give the modeldb parser a real error message** when the header is not a
   number, naming the file and what was expected.
6. Preserve per-line endings, or state plainly that files are normalised to the
   dominant ending (§1.3). Lowest priority — 5 bytes in one file.

---

## 6. Safe removals

Confirmed unreferenced across all Python, JS and HTML — every name checked for
bare references too, not just call syntax:

| name | module | note |
|---|---|---|
| `find_refs` | `unitrefs.py` | superseded by `rename_refs`; the "preview a rename" feature it was built for is not wired to the UI |
| `replace_culture` | `minorfiles.py` | one-line wrapper, no caller |
| `resource_loc` | `minorfiles.py` | one-line wrapper, no caller |
| `split_sprite_stem` | `sprites.py` | superseded by `_match_stem`; its own docstring points at the replacement |

Plus the pyflakes list in §1.6.

**A caution about method.** My first sweep flagged 10 functions; 6 were false
positives. `codeview.trait_document`, `ancillary_document` and `faction_document`
are dispatched from a dict in `server.py:895` and are fully live — they were
missed because they are referenced without parentheses.
`flatrecord.parse_record_file` and `replace_record` are re-exported as
`minorfiles` aliases. **Do not run a call-site regex and delete the output.** The
four above were each read individually.

Total safe removal is roughly 20 lines. This codebase is not carrying much dead
weight.

---

## 7. High-risk areas — change these carefully

1. **`buildings.py` (2965 lines).** STATE.md's warning is correct and this audit
   confirms it: 7203 input lines carry a comment, and it round-trips 1.6 MB
   byte-exact on both mods. Splice only. Never introduce a re-emitting
   serialiser.
2. **`modeldb.py` — the 21 MB round-trip.** Byte-exact on a 21,520,695-byte file
   with a positional binary-ish format where the header count must match the body.
   The BOM fix (§1.2) touches the header read; keep it to the read, and re-run the
   round-trip after.
3. **`_mount_mentions` / `name_mentions` / `mention_file` (§1.1).** Three
   overlapping "who names this token" maps with two different value shapes and
   an unsettled key casing. This is the least coherent corner found. Fix it in
   one deliberate pass with the trimmed-mod repro as the test — not incrementally.
4. **`config._read_json` (§1.5).** The staleness is load-bearing: it fixes a real
   threaded-server bug documented in the code. Narrow the condition; do not
   remove the fallback.
5. **`web/js/` — one global scope, no build step.** 18 files sharing a namespace
   with no module system. `test_web_modules` guards it (10/10) and is the only
   thing standing between you and a silent name collision. Keep it green.

---

## 8. Overall assessment

**Ready for Phase 14, after §1.1.**

What the evidence supports: the parsing layer — which is where a tool like this
actually lives or dies — is genuinely strong. 11 of 12 whole-file round-trips are
byte-exact across two structurally different mods, including a 21 MB modeldb and
a 1.6 MB EDB full of comments. Error handling is disciplined, with no silent
swallows anywhere. Dead code is roughly 20 lines. The module protocol
(`parse_file`/`overview`/`plan`/`apply`) is consistent enough that most apparent
duplication is the pattern working as intended.

What it does not support is treating the current test run as green. Two of the
eight failures are real defects the tests caught correctly and that have been
sitting behind "the mod set changed under us" — which was true for the other six
but not for these two.

Recommended before Phase 14:

- **Must:** fix §1.1. It is a hard crash reachable from real mod layouts, and
  Phase 14's mesh work will lean on `bmdb`.
- **Should:** fix §1.4 and §1.5 (both small, both close a class of bug), and
  resolve §2's `test_edit_models` question one way or the other — it is the only
  finding I could not classify.
- **Then:** unhardcode `Third_Age_6` in the three test fixtures, so the baseline
  reads 45/50 and future mod-set churn stops masking real regressions.

Everything else — the shared helpers, the `flatrecord` adoption gap, the sprite
naming question — is genuine but not blocking, and none of it gets harder if you
do Phase 14 first.
