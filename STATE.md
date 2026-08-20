# STATE — Medieval 2 GUI Toolkit V2
_Updated: 2026-08-20 · **v2.1.0 released** · after 15d_

## Next up
**PHASE 15 IS COMPLETE — 15a, 15b, 15c and 15d — and v2.1.0 IS PUBLISHED.**
The 3D model viewer works end to end, is committed, pushed, tagged `v2.1.0` and
released with the portable zip. Notes: `merge/RELEASE_2_1_0.md`.

**Phase 16 is the Campaign Map Editor**, the flagship, and it gates 3.0.0. Run
the upstream sync before 16a — `map/` is where he is actively working.

**PHASE 14 IS COMPLETE — 14a through 14j — and v2.0.1 IS PUBLISHED.**
The suite is green: **58 of 58 modules** (15b added `test_viewer3d_http`,
22 checks after 15c; 15a added `test_mesh`, 38 checks after 15d;
14j added `test_images`, 53 checks; 14i added `test_variants_and_marks`, 82;
14f added `test_unit_view`, 25 over 8233 real pool rows; 14e added `test_edusort`,
56).

Phases 0–14 are committed, pushed, tagged `v2.0.1` and released with the
portable zip:
<https://github.com/ProJ-Yeet/medieval2-gui-toolkit/releases/tag/v2.0.1>

**14j is a SUBRELEASE of its own** (`v2.0.1`, `merge/RELEASE_2_0_1.md`), unlike
14i which was folded into 2.0.0. The user asked for it as one: it is a feature,
not a correction. Read memory `release-numbering` before picking the next number.

**The repo is `medieval2-gui-toolkit` now** (14i). GitHub forwards the old
address, so an existing clone or release link still resolves, but write the new
one down anywhere it is typed fresh.

**14i is a CORRECTION PASS folded into 2.0.0, not a point release.** The user
asked for it that way: the tag, the version string and the release page all stay
2.0.0, and `merge/RELEASE_2_0_0.md` carries the new work as a "The correction
pass" section rather than a changelog of its own. If a future round is asked for
as a version of its own, that is 2.0.1 — read memory `release-numbering` first.

**The 2.0.0 numbering overrode a locked decision, on purpose.** The old rule
reserved 2.0.0 for the Campaign Map Editor; the user was shown the conflict and
chose to override, because 1.9.9 shipped a unit-transfer tool and 2.0.0 is a
different program. **The Campaign Map Editor is now 3.0.0.** ROADMAP.md's Locked
decisions section carries the reasoning; don't re-propose the old rule.

**Phase 15's upstream sync is done** (2026-08-20, reviewed SHA `e6e6982`): all
19 of his new commits are campaign-map and New Map Editor work, none of it in
Phase 15's file set. One `descr_regions` correction came out of the sync and is
applied. See Upstream below.

### What 15c did — the viewer against the addon
15b's viewer drew models, and drew several of them wrong. Every fault here was
settled against `Reference/Medieval-2-Toolkit/` (Mylae's Blender addon) and
against the mods' own bytes, not by eye.

**A model is painted from the two textures GLUED SIDE BY SIDE, and the UVs
address the pair.** A modeldb entry names a main texture and an attachment
texture per faction, and the game treats them as **one image twice as wide** —
main on the left, attachment on the right — which is what the mesh's single UV
set is written against. u 0..1 is the main sheet, u 1..2 is the attachment
sheet, and the pair **tiles infinitely** outside that.

**15c got the SPACE right and the STORAGE wrong — see 15d.** The file does not
store `u` in that range: it normalises over the pair (main 0..0.5, attachment
0.5..1) and IWTE doubles it on the way into Blender. 15c passed the file's own
`u` through to a shader that halves it again, so every model sampled a squeezed
stripe of one sheet. `_read_streams` doubles `u` on read now.

So the viewer glues the two into one texture (`v3Atlas`, a 2048x1024 canvas for
the usual 1024 skins, power-of-two so WebGL will repeat it), samples at
`u * 0.5` with REPEAT on both axes, and that is the whole of it. **No code
chooses a sheet for a part and nothing is normalised into 0..1.**

This corrects a wrong first attempt in this same session, and the corrections
are worth keeping because both mistakes are easy to make again:

- **Choosing a sheet per group is wrong**, even though the addon's material
  split (`__main` / `__attach`) makes it look right. One group's art can CROSS
  the boundary — 124 groups in TATR do, e.g. `mount_eastern_armoured_horse`'s
  `Body` at u 0.41..1.38 — and any per-group rule has to put the whole of it
  on one sheet and be wrong about the rest.
- **Shifting an attachment group's u by -1 to sample a separate texture is
  also wrong**, for the same reason and because it throws the tiling away.
  UVs really do run outside the two tiles: in TATR alone **112 groups have
  u below zero and 268 have v outside 0..1**. The atlas handles all of it for
  free; a per-group shift cannot.

An entry with no attachment sheet, or one the mod does not ship, gets the main
sheet in both halves — the same fallback the addon's exporter uses for an empty
attach slot (`attach_name = plan['attach'][1] or main_name`).

`mesh._classify_sheets` still records `"main"` / `"attach"` / `"both"` per
group, but it is a LABEL for the part list, not a rendering instruction, and it
is computed the way the shader samples (`u mod 2`) so it cannot disagree with
the picture. Verified by drawing a model's UV mesh onto the glued pair at
`u * 0.5`: every triangle lands on its own art, face on face in the left half
and shoulder cape on cape cloth in the right.

**Models were mirrored — shield arm and sword arm swapped.** M2TW is
**left-handed** (right +X, up +Y, forward +Z; Direct3D), and 15b handed those
coordinates straight to a right-handed camera. Measured from the models: a
horse's head sits at +Z and its tail at -Z, and on a soldier `shield0` sits at
-X with `primaryactive0` at +X — shield in the left hand, weapon in the right,
so the model's own right is +X and a figure facing the camera was showing its
right side on the viewer's right. `uModel` negates X. For a mirror the
inverse-transpose normals want is the matrix itself, so `mat3(uModel)` stays.

**What the two group name strings ARE, settled rather than guessed.** One TATR
mesh has a group type that is IWTE's own unanswered prompt, saved verbatim into
the file: _"enter a group type: cloak"_ / _"enter a group flag (0 for required,
1 for optional.)"_. So the first string is the group TYPE, the second is the
MESH NAME, and the uint32 15b called a variant marker is **required/optional**.
That is exactly the addon's `objectname__comment__opt` — IWTE joins the two
with `__` and appends `__opt` when the flag is 1. The parts panel now folds by
type (case-folded: nineteen meshes across the two mods spell the same part
`Arms` and `arms` in ONE file), spells the engine's fixed equipment vocabulary
out from the addon's `PART_PREFIXES` ("Secondary weapon — drawn", not
`secondaryactive0`), tags parts the mesh flags optional, and starts with
`shieldpassive*` and `secondaryactive*` switched off — the same call the
addon's importer makes in `hideVariations`.

**Randomize variations**, a button at the top of the panel: a variant per part
and a coin toss on the optional ones, which is what the game does filling a
unit out of one model.

**The V axis was NOT wrong** — 15b had it right, and this was checked properly
this time rather than by a luminance heuristic: drawing the head groups' UV
boxes on a Lossarnach noble's sheet puts them exactly on the faces painted
along the sheet's TOP edge (v 0.00..0.10), and the same for every body and
skirt group. `v=0` is the top. Flipped, the model renders as garbage.

**The backdrop is an environment, not a flat near-black.** One `v3Env()`
function — sky above, warm ground below, a bright band at the horizon — paints
the background AND lights the model, which is the part of an HDRI that matters
for an inspection viewer without shipping a megabyte of `.hdr` and a decoder.
Plus a mid-tone curve, because unit art is sRGB and a linear multiply of 0.5
lands far darker than half-lit looks: dark armour on a dark field was a viewer
of silhouettes. **Turntable is now "Rotate" and starts OFF.**

`test_viewer3d_http` is 22/22 (the payload now has to say which sheet each
group draws from and whether it is optional); `test_mesh` was 34/34 here, with
its UV assertion widened from `[0,1]` to the two u tiles — which passed
vacuously, because nothing was reaching the second tile yet. 15d is what made
that assertion bite.

### What 15d did — two decode bugs the user caught in Blender
Both were found the same way and it is the way to find the next one: the user
opened the same models in Blender through Mylae's addon and put its picture
beside the viewer's. Neither bug was visible as "broken" — both looked like a
viewer that sort of worked.

**The UVs were squeezed into one sheet, and every part wore the wrong art.**
The file normalises `u` over the two-sheet PAIR: main is 0..0.5, attachment is
0.5..1, tiling with period 1. Everyone downstream of IWTE speaks the DOUBLED
version of that (main 0..1, attachment 1..2), which is the space the addon
enforces in `export_checks.checkUVSpace` and the space 15c wrote the viewer
against — so the file's own `u` met the shader's `u * 0.5` and halved twice.
`mesh._read_streams` doubles `u` on read, so everything this tool hands out is
in the addon's space and nothing else had to change. Measured before believing
it: across 900 TATR models, **1,092 of the 1,179 weapon and shield groups sit
in u 0.5..1** — the half an attachment sheet exists for — with bodies, heads
and beards packed into 0..0.5. Verified by drawing each group's triangles onto
the glued pair: face on face, scabbard on scabbard.

Side effect worth knowing: `_classify_sheets` was labelling **every** group
`"main"` before this, because nothing ever passed u 1. The part list's "attach
sheet" / "both sheets" tags only started telling the truth here.

**The packed normals are `D3DCOLOR`, not signed bytes.** Unsigned, biased around
127.5 (`b / 255 * 2 - 1`), stored **z-y-x** with a pad byte last. Read as signed
bytes over 127 in x-y-z order — 15a's guess, and the obvious one — the vectors
come back 0.74..1.43 long with **half of them pointing away from their own
faces** (mean dot -0.11). That is what the dark blotches and hard seams were.
Decoded properly: unit length to within 0.004, mean dot **+0.897** against the
face normals computed from the positions, 4 of 6,783 opposed.

`test_mesh`'s normal-length bound was **0.9..1.2, which the broken decode passed
at 1.08** — it is 0.98..1.02 now. Also added: the reference horse must use both
u tiles (catches forgetting to double, and doubling twice), and its saddle must
classify `main`, its rear barding cloth `attach`, its body `both`.

**The lesson for the next format bug:** a plausible decode that renders
something is the dangerous case. Both of these were settled by measuring the
decode against a second source — the face normals the positions imply, and the
addon's own UV convention — not by looking at the canvas.

### What 15b did
**`web/js/viewer3d.js` draws the model, in plain WebGL, with no library.** The
user chose that over vendoring three.js: a static textured model needs one
shader, an orbit camera and a texture bind, and 600 KB of someone else's dist/
in a project whose whole point is that it has no build step is a bad trade.
About 400 lines, and the only maths in it is perspective and look-at.

**Three routes, all in `server._model_route`:** `/api/model` (the picker — LODs
and skins, and which of them the mod actually ships), `/api/model/geometry`
(one LOD as a binary payload) and `/model_texture` (one skin as a PNG).

**The geometry goes over as ONE binary blob, not JSON.** `mesh.geometry_payload`
writes `"M2GT"`, a JSON header for the structure, then the arrays raw, padded so
the floats stay 4-byte aligned — the page views each one in place with no copy
and no parse. JSON would have been about six times the bytes.

**Two real bugs were found by looking at pixels rather than at the screen**, and
both would have shipped as "the viewer sort of works":

- **The V axis was upside down.** WebGL's habit is to flip an uploaded image
  because OpenGL puts v=0 at the bottom; M2TW is a Direct3D game and puts it at
  the top. Flipping sent 62% of a real horse's vertices onto empty black space.
  Measured by sampling the texture at the mesh's own UVs: mean luminance 48
  against 16, pure black 2% against 62%.
- **The camera orbited the wrong axis.** I had assumed Z-up. **Models are
  Y-up** — across six DaC soldiers the `Head` group's centroid sits ~1.4 above
  the `Legs` group's in Y and level in X and Z. Orbiting Z lays every man in
  the game on his side. Now written into `mesh.py`'s docstring so nobody
  re-derives it.

**The variant problem is the thing that makes this UI worth having.** A model
carries several heads, helmets and shields and the game picks one per soldier;
drawing them all puts nine helmets on one orc. `gundabad_pale_uruk_new2` has 27
groups and the viewer draws **12** — one per part, the rest offered in
drop-downs. Verified in the browser against the real DOM.

**Skins are deduplicated rather than listed per faction** (`mesh.entry_view`).
Entries routinely list 29 factions against one texture; 29 identical rows told
you nothing. One row per distinct skin, labelled "portugal (Remnants of Angmar)
+28 more". _15c changed what a "skin" is — see below._

**`icons.py` grew two things** both of which everything else can now use:
`.texture` files unwrap to DDS through `sprites.texture_to_dds` before Pillow
sees them, and `png_bytes(src, max_side)` shrinks on the way out (a 2048 skin
served at 1024 is 4 MB instead of 16, and `max_side` is part of the cache key).

Verified in the real app, not just in tests: the button on a real DaC model
card, the viewer opening from it, 4 distinct skins each loading a different
1024² texture, wireframe drawing with no GL error, and the model card restored
on close.

### What 15a did
**`unittransfer/mesh.py` reads a battle model, and the read is falsifiable.**
`read_mesh(path)` returns a `MeshFile`: one shared vertex pool (positions,
normals, UVs), the groups that index into it, the bone names, and the LOD block's
name. `probe(path)` tells a `.mesh` from a `.cas` without decoding either.

**Two things ROADMAP.md said about this phase were wrong, and the plan followed
the files instead.** There is no loader to port: the Blender addon in
`Reference/Medieval-2-Toolkit/` never parses a model, it writes an IWTE task
file and shells out to `IWTE.exe` (`tasks/iwte_run.py`). And upstream's
`src/lib/casCodec.js` — the "port-concept" entry in the manifest — documents
`.mesh` as "uint32 version, uint32 submesh count, 32-byte vertices", which
matches no real file and cannot parse one. **A `.mesh` is a
boost::serialization binary archive**, which is why: boost writes a class
descriptor the first time it meets a type and only the class id afterwards, so
the same record is two bytes longer on its first appearance and no fixed-stride
reader can work. The format is written up in full at the top of `mesh.py` —
group table, the eleven vertex stream types with their strides, the bone table —
and that docstring is the spec now, because nothing else is.

**What proves it: reaching the bone table.** One wrong stride anywhere before it
puts the table outside the short window it is looked for in, and the count read
there lands on nonsense. **4,700 of the 4,702 `.mesh` files in the two test mods
decode** — every unit model, mount, settlement piece and siege engine in Divide
and Conquer (3,500 of 3,500) and Third Age Reforged (1,200 of 1,202) — plus the
seven reference templates. The two exceptions are sky domes that hold SEVERAL
models one after another; they are refused by name rather than half-read.

**There are two vertex formats, and finding the second one cost the most time.**
A skinned model (soldiers, mounts, settlements) packs normal, tangent and
binormal into three signed bytes and a pad; a static one (siege engines, sky
domes) writes them as three floats — same stream type numbers, four bytes a
vertex against twelve. The archive header is four words in the first and three
in the second. Neither is announced anywhere, so `_read_header` and
`_resolve_stride` both try the alternatives and keep whichever leaves the rest
of the file readable. **A sweep of one folder will not find this**: everything
under `unit_models` is the skinned form, and `data/siege_engines` is the only
place in either mod that is not.

**What is NOT decoded** is the block that closes the file: a per-LOD material and
attachment record, 519 bytes in every unit model. Its name is read
(`characterlod0`), its length is on `MeshFile.trailer`, and nothing the viewer
draws is inside it.

**`.cas` was asked for and did not land, and that was the agreed fallback.**
`probe` identifies one and `read_mesh` refuses it by name, but there is no `.cas`
geometry reader. It is not a variant of `.mesh` — it opens with the float `3.2`
and is a whole 3ds-max scene export: frame rate, key times, a node hierarchy
(`Scene Root`, then bones), animation tracks, then the mesh, then the material,
with `textures\…\.tga` in the last 60 bytes. That is a second job the size this
one was, and it belongs to **16e**, where the roadmap always had the strat
preview. The reconnaissance is written down at the bottom of `mesh.py` so 16e
starts from something.

**For 15b:** the geometry is renderer-ready as it stands. Indices are GLOBAL
into one pool, so a group is a face range, not a mesh of its own — draw the pool
once and issue one index range per group. Several groups share a group TYPE
(`Body`/`horse_body_01`, `_02`, `_03`) and are variants of one part, and drawing
all of them at once stacks three heads on one soldier: pick one variant per part.
`MeshGroup.flag` is not that — 15c showed it is required/optional — and
`MeshGroup.sheets` LABELS which of the entry's two textures a group's art
lands on, without being a rendering instruction: the two are glued into one
image and the UVs pick by themselves.
Textures need no new code — `sprites.texture_to_dds()` then Pillow reads DXT1,
DXT3 and DXT5 out of a real `.texture` at 1024² and 2048², which is the whole
texture path. `tools/meshdump.py` is the debugging tool: `--sweep <folder>` over
a mod, `--raw <file>` on one that will not open.

### What 14i did
The list that came back from actually using 2.0.0. Ten items, no new direction.

**Two of them were real defects with a single cause each.** "Open file location"
opened Documents, every time, for everyone: `explorer /select,<path>` was passed
as an argument LIST, and `subprocess.list2cmdline` quotes the whole
`/select,C:\…` token the moment the path has a space in it — Explorer then fails
to parse the switch and falls back to the default folder. Every real mod path has
a space in it. It is one command STRING now, with the path quoted inside the
switch. And Ctrl+Z did nothing in the Code View, because undo.js takes the
keystroke whenever an editor is open and restores a snapshot of the BOXES; the
pane keeps its own stack now, and an empty stack hands the keystroke back to the
editor so undo walks out of the text and into the form.

**The freeze report was `bldRenderBody` throwing on a null.** Every panel that
takes the dialog over leaves `#bldBody` out of the document, and the throw came
out of an onclick — so it killed that click and everything after it. `bldTouched`
now returns early for any stashed panel, `bldRenderBody` returns early with no
body at all, and the stale-`state.bld` paths around the settlement filter, the
level list and the faction picker are closed with it.

The rest: the sidebars fold (every `<h3>` in every `aside.filters`, wrapped by
reading the markup rather than by hand), a ＋ on the tier Variant, Abilities
merged into **Weapons & abilities**, the cleanup dialog's banner format made
editable with a live sample, the ordering screen rebuilt as a list of units with
tier / variant / **classification** drop-downs filled in from what was detected,
**⇄ Compare city / castle** on the building editor with per-unit and whole-line
mirroring, one set of names for the three recruitment numbers (**Initial Pool /
Replenish Rate / Max Pool**), the recruitment row split over two lines so the
`requires` clause has room, the building Code View following field edits at last,
the faction sort lifted out of the drop-down it sorts, unit cards on the voice
rows, and a prose sweep that took ~300 clause-joining em dashes to zero.

New server surface: `GET /api/buildings/variants` (one line beside its twin,
tier by tier) and `marks` / `style` on `/api/edu/sort/plan|apply`. New marker
key `special=` on `;@m2gt`, read by `edusort.special_of`.

### What 14j did
**Every picture the tool draws can be replaced in place, and every picture can
say where it lives on disk.** Before this, one picture in the whole toolkit
could be swapped: the unit card, through the editor's own staged import.

**What made it small is that the page hands back the `<img>`'s own `src`.**
Every picture on every screen is painted through `/icon` or `/building_icon`,
and that URL is a complete description of the question the server answered — so
one engine (`unittransfer/images.py`) and one dialog (`web/js/images.js`) cover
unit cards, info cards, ancillary pictures, faction art, the Minor Files pips
and settlement cards, and building icons.

Two ways in: a delegated **right-click** menu on any `<img>` served by those two
routes (which is what reaches the thumbnails in lists and grids), and a **✎ plus
a button pair** on the screens where the picture is the subject.

The **resolution warning** is the thing that was asked for: the confirm dialog
puts both pictures side by side at the size each really is and names both sizes
when they differ. A warning, never a refusal. Three more rules fall out of the
formats: a `.png`/`.jpg` is re-encoded as a 32-bit `.tga`; a same-stem sibling
in the other native extension is removed so two files cannot answer to one name;
and **a unit card fans out to every faction folder that holds one**, because the
game looks it up under the *player's* faction folder.

**Borrowed art creates rather than overwrites.** A building icon or ancillary
picture the mod does not own is served out of the vanilla UI, so a replacement
writes the mod's *first* copy at the path the game looks for — which is the
"drop a .tga in to override it" the building browser had only ever said in a
tooltip.

New server surface: `POST /api/image/plan | /replace | /reveal`. The write goes
through the same backup + log record as every other job, so it is in the log and
undoes like a transfer. `tests/test_images.py`, 53 checks, builds its own folder
of pictures — only the fan-out section needs a mod installed.

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
| 15a — the model decoder | **done** | `unittransfer/mesh.py` + `tools/meshdump.py`. A `.mesh` is a **boost::serialization archive**, reverse-engineered from the files: neither the Blender addon (it shells out to IWTE) nor upstream's `casCodec.js` (its spec matches no real file) could be ported. **4,700 of 4,702 models decode** (the 2 are multi-model sky domes, refused by name), proven by reaching the bone table. Two vertex formats: skinned packs normals to bytes, static writes floats. `.cas` NOT decoded — a whole 3ds-max scene format, handed to 16e. `test_mesh` 34/34 |
| 15b — the viewer | **done** | `web/js/viewer3d.js`, hand-rolled WebGL (no three.js, user's call). `/api/model`, `/api/model/geometry` (binary payload, not JSON), `/model_texture`. **View model** on the shared model card. Parts, variant pickers, skins, LODs. Models are **Y-up**, not Z-up — caught by measuring group centroids. `test_viewer3d_http` 21/21 |
| 15c — the viewer against the addon | **done** | Four faults, all settled against Mylae's Blender addon and the mods' bytes. The main and attachment textures are **glued side by side into one image** and the UVs address the pair — sample at `u * 0.5` with REPEAT, never choose a sheet per group (124 groups straddle the boundary) and never normalise into 0..1 (112 groups have u < 0, 268 have v outside 0..1). Models were **mirrored** — M2TW is left-handed, so `uModel` negates X. The two group strings are **type** and **mesh name** and the uint32 is **required/optional**, proven by an IWTE prompt left in a TATR mesh; parts fold by type with the addon's equipment vocabulary. Procedural-HDRI backdrop and lighting, **Randomize variations**, Turntable renamed **Rotate** and off by default. The V axis was already right. `test_viewer3d_http` 22/22 |
| 14 — bug-fix and polish pass | **done** | 14a–14j |
| 14j — replace any picture | done | **v2.0.1.** `unittransfer/images.py` + `web/js/images.js`; `POST /api/image/plan\|replace\|reveal`. Right-click any image anywhere, or the ✎ where a picture is the subject. Resolution mismatch warned (never refused), `.png` → `.tga`, unit cards fanned out to every faction folder, borrowed vanilla art creating the mod's first copy. `test_images` 53/53 |
| 14i — the post-release correction pass | done | repo renamed to `medieval2-gui-toolkit`; Code View Ctrl+Z/Y; folding sidebars; "Open file location" fixed (Explorer arg quoting); ＋ on tier Variant; Abilities folded into **Weapons & abilities**; editable banner format + the ordering screen as a unit list with tier/variant/**classification**; **⇄ Compare city / castle** (`/api/buildings/variants`); **Initial Pool / Replenish Rate / Max Pool** everywhere; two-line recruit rows; building Code View follows field edits; faction sort as a toggle; unit cards on voice rows; ~300 em dashes → 0. Folded into the 2.0.0 release notes, not a new version |
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
reference tool reviewed SHA **e6e6982** (2026-08-20). **The Phase 15 sync is
done** — the write-up is the newest entry in `merge/SYNC_LOG.md`.

All 19 of his commits since b4768d5 land in the campaign map editor or the New
Map Editor, so **nothing had to be ported to keep 2.0.0 correct**, and Phase 15
(the 3D model viewer) can start without waiting on anything of his. One
correction came out of it and is applied: `descr_regions`' two bare numbers are
**triumph value then base farming level**, not farming level then unknown —
measured over vanilla's 112 regions, not taken on his word, because both test
mods write 5 and 1 everywhere and cannot tell the two apart. Three facts for
Phase 16 are banked in the manifest's `notes`.

**Phase numbers in the manifest were off by one and are fixed.** It was written
before the 2026-08-18 renumber, so 46 map files said 15 (they are 16) and 10
model/texture files said 14 (they are 15). `upstream_sync.py`'s RULES table is
corrected too, so new files land on the right number.

`merge/PORT_MANIFEST.json` is authoritative; all 12 phase-13 files carry their
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
