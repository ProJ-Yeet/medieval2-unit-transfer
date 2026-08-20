# Medieval 2 GUI Toolkit v2.1.0

2.0.1 could tell you everything about a battle model except what it looks like.
The entry named a mesh, three LODs and a texture per faction, and every one of
those was a path — a string you could read, copy and check for typos, and
nothing else. To see the thing, you exported it through IWTE, imported it into
Blender and assigned the materials by hand.

Now the tool draws it. **View model**, on any model card, reads the `.mesh`
itself and paints it with the faction's skin, in the browser, with no export
step and nothing installed.

---

## The short list

- **A 3D model viewer, on the card you were already looking at.** Drag to turn,
  wheel to zoom, right-drag to pan. It is on the model card in both the Unit
  Editor and BMDB mode, because it is the same card.
- **The parts a model is really made of**, listed with their triangle counts and
  a checkbox each. Parts the game only puts on some soldiers are marked
  *optional*, and a part whose art lives on the attachment texture says so.
- **The variants, one at a time.** A model usually carries several heads, several
  helmets and several shields and the game picks one per soldier — drawing them
  all at once puts nine helmets on one orc. The viewer picks one and offers the
  rest in a drop-down. **Randomize variations** rolls the lot the way the game
  fills a unit out of the one model.
- **Skins deduplicated to the ones that differ.** An entry commonly lists
  twenty-nine factions against one pair of textures. Four rows means four skins,
  not twenty-nine of the same one.
- **Both textures at once, the way the game paints them** — main and attachment
  glued side by side, with the model's UVs running across the pair. A scabbard or
  a cape comes out in its own colours instead of wearing whatever happened to sit
  at those coordinates on the main sheet.
- **A LOD the mod does not actually ship is greyed out and says so**, which makes
  the viewer a quick way to find an entry pointing at a file that is not there. A
  file that cannot be read puts the reason on the canvas in words.

---

## Everything in this release

### Reading a `.mesh`

Nothing we hold documents the format. The Blender addon in `Reference/` never
parses a model — it writes an IWTE task file and shells out to `IWTE.exe` — and
the other reference tool's decoder describes a layout that matches no real file.
So `unittransfer/mesh.py` was written from the bytes.

A `.mesh` is a **boost::serialization binary archive**, which is why a
fixed-stride reader cannot work: boost writes a class descriptor the first time
it meets a type and only the class id afterwards, so the same record is two bytes
longer the first time it appears. On top of that sits a group table, one shared
vertex pool the groups index into, a bone table, and a per-LOD block that is
measured rather than decoded because nothing drawn is inside it.

The decode is falsifiable rather than plausible: reaching the bone table at all
proves every stride before it was right, because one wrong stride anywhere puts
the table outside the window it is looked for in. **4,700 of the 4,702 `.mesh`
files in Divide and Conquer and Third Age Reforged decode** — every unit model,
mount, settlement piece and siege engine in both. The two that do not are sky
domes holding several models in one file, and they are refused by name rather
than half-read.

### What the viewer is

Plain WebGL, no library. A static textured model needs one shader, an orbit
camera and a texture bind, and vendoring 600 KB of three.js into a project whose
whole point is that it has no build step was the wrong trade.

The geometry crosses as **one binary payload**, not JSON: a JSON header for the
structure and then the arrays raw, 4-byte aligned, so the page views each one in
place with no copy and no parse. A soldier is a few thousand vertices, and
spelling those floats out as text is about six times the bytes and a parse on top.

The model stands in a simple environment — sky above, ground below, a bright band
at the horizon — and the same function paints the backdrop and lights the model.
Game armour is dark, and a dark model on a dark field is a silhouette.

### The two textures, and why no code picks one

A modeldb entry names a main texture and an attachment texture per faction, and
**the game lays them out as one image twice as wide** — main on the left,
attachment on the right — which is what the mesh's single UV set addresses, and
the pair tiles infinitely in both axes outside that.

So the viewer glues the two into one texture, samples at `u * 0.5` with REPEAT
wrapping, and the coordinate does the rest. **No code chooses a sheet for a part
and nothing is normalised into 0..1.** Both of the obvious shortcuts are wrong,
and both were tried:

- **Choosing a sheet per group** looks right, because the Blender addon splits
  its materials into `__main` and `__attach`. But one group's art can cross the
  boundary — 124 groups in Third Age Reforged do — and any per-group rule has to
  put the whole of it on one sheet and be wrong about the rest.
- **Shifting an attachment group's `u` by -1** fails for the same reason, and
  throws the tiling away besides: in that mod alone 112 groups have `u` below
  zero and 268 have `v` outside 0..1, on purpose.

**How `u` is stored, which is where the last bug was.** The file normalises `u`
over the *pair* — main is 0..0.5 and attachment 0.5..1, tiling with period 1 —
while everyone downstream of IWTE speaks the doubled version, main in 0..1 and
attachment in 1..2. That is the convention the Blender addon enforces in
`export_checks.checkUVSpace`. The decoder now doubles `u` on read, so everything
this tool hands out is in the addon's space and the atlas lands on the art.
Before that, the halved coordinate met the shader's own halving and every model
sampled a squeezed stripe of one sheet, with the sword, the cape and the shield
all painted out of the wrong half. Settled by measurement rather than by eye:
across 900 models, 1,092 of the 1,179 weapon and shield groups — the art an
attachment sheet exists for — sit in the second half.

### Normals, and the dark patches

The packed normal stream is a `D3DCOLOR`-style vector: unsigned bytes biased
around 127.5, stored **z-y-x** with a pad byte. Read the obvious way instead —
signed bytes in x-y-z order — the vectors come back with lengths from 0.74 to
1.43 and *half of them point away from their own faces*, which on screen is a
model covered in dark blotches with hard seams between them. Decoded properly
they are unit length to within 0.004 and agree with the faces computed from the
positions. The suite now pins the length to 0.98..1.02; the old 0.9..1.2 bound
was loose enough to let the broken decode pass.

### Everything else the format turned out to say

- **What the group name strings are.** One mod ships a mesh whose group type is
  IWTE's own unanswered prompt, saved verbatim into the file — _"enter a group
  type: cloak"_ — which settles that the first string is the group TYPE, the
  second is the artist's MESH NAME, and the trailing flag is required/optional.
  That is exactly the addon's `objectname__comment__opt`. So the parts panel
  folds by type, spells the engine's fixed equipment vocabulary out in words
  ("Secondary weapon — drawn", not `secondaryactive0`), and starts with the
  stowed shield and the sheathed sword switched off — the same call the addon's
  importer makes.
- **Models are Y-up and left-handed.** Neither is written in the file. Orbiting
  the wrong axis lays every man in the game on his side; handing left-handed
  coordinates to a right-handed camera swaps the shield arm and the sword arm.
  Both measured from the models themselves and written into the decoder's
  docstring so nobody has to derive them again.
- **`v = 0` is the top**, because M2TW is a Direct3D game. WebGL's habit of
  flipping an uploaded image sends most of a model's vertices onto empty black.

### Also in this release

- **`tools/meshdump.py`**, the tool the format was reverse-engineered with, kept
  because it is also the answer to "the viewer will not open this file, why". It
  prints a model's groups, vertex pool and bones; `--raw` walks the bytes for a
  file that will not decode at all, and `--sweep` runs a whole mod through in one
  go.
- **`.texture` files unwrap for any screen**, not just the viewer, and images are
  shrunk on the way out — a 2048 skin served at 1024 is 4 MB instead of 16.

---

## Tests

`test_mesh` holds the decoder to the seven template meshes that ship in this
repo — so its core runs on a machine with no game installed — and then sweeps
whatever mod is present, which is the check that matters: a wrong stride looks
fine on one file and falls over on the thousandth. It reads outside
`unit_models` deliberately, because settlement pieces (no skeleton) and siege
engines (a second vertex format) are where the format's variations live.

`test_viewer3d_http` drives the viewer's three routes over a real server, with
this repo's own reference model planted at the path the entry names, so the
expected vertex and triangle counts are known exactly. Half of it is the
refusals: an entry that is not there, a LOD the mod does not ship, a texture
outside the mod's folder.
