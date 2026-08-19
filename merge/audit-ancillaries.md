# Ancillaries editor — what the reference tool has, and what we took

_Phase 9. Compared against `refs/upstream/editor/main` at the SHA in
`merge/SYNC_LOG.md`: `src/components/ancillaries/{AncillariesParser,
AncillaryEditor,AncillaryList,AncillariesContext,AncillariesFileLoader}.jsx` and
`src/pages/AncillariesEditor.jsx`._

**Verdict: field list matched, one good idea taken, and two hardcoded lists that
would quietly rewrite a mod's own data.** The file-handling verdict is the same
as `merge/audit-traits.md` — their serializer rewrites the whole file — because
it is the same serializer with one word changed.

## Field coverage

| Field | Theirs | Ours |
|---|---|---|
| `Ancillary <name>` | ✅ editable | ✅ editable (new ones only) |
| `Type` | ⚠ fixed 17-value dropdown | ✅ free text, this mod's own values offered |
| `Transferable` | ✅ 0/1 select | ✅ checkbox |
| `Image` | ✅ + preview | ✅ + preview, and says when the file is missing |
| `Unique` | ✅ | ✅, with the self-exclusion rule checked |
| `ExcludedAncillaries` | ✅ | ✅, with the limit of 3 enforced |
| `ExcludeCultures` | ⚠ fixed 6-culture list | ✅ free text |
| `Description` / `EffectsDescription` | ✅ key + text | ✅ key + text |
| `Effect <attribute> <n>` | ✅ add / delete | ✅ add / delete, attribute checked, limit of 8 |
| ancillary add / delete | ✅ | ✅, and the triggers that granted it go with it |

## What we took from them

**Show the picture.** Their editor decodes the `.tga` and puts it beside the
record, and it is obviously right — an ancillary IS its icon on the character
screen. Ours resolves `data/ui/ancillaries/<file>` and falls back to the vanilla
UI, decoding through the icon cache the unit grid already uses, so it costs
nothing new. It also gave us a finding they do not have: **DaC names two pictures
nobody shipped** (`heads_dwarven.tga`, `entertainment_bard.tga`), which is a
blank slot in game and nothing in any log.

**The displayed text beside its key**, same as the traits editor took from them —
here it matters more, because an ancillary's *own name* is a text key, so the box
beside the name is what the player reads.

## What we did not take, and why

**`ANCILLARY_TYPES` — a 17-value dropdown for a free-form field.** `Type` groups
ancillaries so a character holds one per type; it is whatever the mod says. The
three installed mods use **350 distinct values**, of which their list contains
**13**. Opening any of the other 337 in their editor shows a `<select>` with no
matching option and saving writes whichever value the select fell back to — a
silent regrouping of somebody's retinue. Ours is a text box whose datalist is
built from the types that mod already uses.

**`CULTURES` — the same mistake, smaller.** Six hardcoded vanilla cultures; the
installed mods also use `gondor`, `noldor` and `crags`. This is the Phase 13
ruling arriving early: adopt *fields*, derive *values* from the mod.

**Their serializer.** `serializeAncillariesFile` re-emits the file from the parsed
model, so every comment banner goes and the mod's own indentation with it. Two
data losses specific to this file:

* `transferable: parseInt(...)` — an ancillary with no `Transferable` line
  becomes `NaN` and is written as `Transferable  NaN`;
* `Effect` values go through `parseInt` too, so a malformed one is written `NaN`
  rather than left alone to be reported.

Ours splices: 1134 of 1134 real ancillaries re-render to themselves byte for
byte, and a full-form save (every box posted back unchanged) rewrites nothing.

**Their trigger half**, for the reason in `merge/audit-trigger-vocab.md`:
conditions are kept as raw strings, so there is no vocabulary, no operand pickers
and no never-fires check. Ours hosts the shared builder from Phase 7.

## What we have that they do not

* **The two silent hardcoded limits**, from TWCenter's *List of Hardcoded
  Limits*: more than 3 `ExcludedAncillaries` is an errorless crash, and more than
  8 `Effect` lines makes the ancillary impossible to gain from a trigger. Neither
  is in their editor and neither produces a message in game.
* **`Unique` without self-exclusion** — the guide's note, checked: a `Unique`
  ancillary not on its own `ExcludedAncillaries` line can still be acquired twice.
* **Cross-half checks**: an `AcquireAncillary` naming an ancillary the file does
  not define, an `ExcludedAncillaries` entry that does not exist, a duplicate name.
* **Line order**, which their serializer happens to get right by construction but
  never checks on input.
* **Code View**, and **backups + undo** covering the EDA, `export_ancillaries.txt`
  and its compiled archive as one job.
