# Medieval 2 GUI Toolkit v2.0.1 — every picture in the tool can be replaced

2.0.0 could swap exactly one picture: a unit's card, through the unit editor's
own import. Everything else the tool draws — info cards, building art, ancillary
pictures, faction symbols, religion pips, settlement cards — was something you
could look at and nothing else, even though the tool knew perfectly well which
file it had just decoded.

Now every one of them can be replaced in place, and every one of them can tell
you where it lives on disk. A subrelease: nothing else changed.

---

## The short list

- **Replace any picture, anywhere.** Right-click any image in the tool for
  **Replace image…** and **Open file location**. The screens where a picture is
  the thing you came to edit also get a ✎ on the picture and a pair of buttons
  under it.
- **A resolution warning before the write.** The game does not rescale UI art,
  so a 512x512 file dropped in for an 80x24 card is drawn stretched into the
  same box. The confirm dialog shows both pictures side by side, at the size
  each really is, and says what is about to happen. It is a warning, never a
  refusal — it is your mod's art.
- **A unit card fans out to every faction folder that holds one.** The game
  looks a card up under the *player's* faction folder, so one card is routinely
  the same picture copied into ten of them. Replacing only the one the preview
  happened to find would leave the other nine stale.
- **Art the mod is borrowing from the game is said so, and creating.** Most mods
  ship only the building icons they changed. Replacing one of the borrowed ones
  writes the mod's **first** copy at the path the game looks for, rather than
  pretending to overwrite a file the mod does not own.
- **`.png` and `.jpg` are converted to `.tga` on the way in**, because the
  engine reads nothing else — a `.png` copied in under the right name sits there
  and never renders.
- **One Undo, like everything else.** Every file is backed up before it is
  written, and a created file is deleted rather than restored when you undo.

---

## Everything in this release

### Replacing a picture

Every image in the UI is painted through one of two server routes, and that URL
is a complete description of the picture. So the page hands the URL back and the
server re-resolves it into the file that is showing plus the path(s) a
replacement is written to. One dialog serves all of them.

Two ways in, because the pictures fall into two groups:

- **Right-click**, on any picture on any screen — including the thumbnails in
  lists and grids that have no room for a button.
- **A ✎ on the picture, and Open file location / Replace image… under it**, on
  the screens where the picture is the subject: the unit editor's card variants,
  the ancillary editor, the faction editor's art, the building editor's small
  and large icons, and the pips and cards in Minor Files (where the pip itself
  is the button — those tables have no room for two more).

### What the confirm dialog says

- both pictures side by side, at the size each really is, with their dimensions
  and their file sizes
- **the resolution warning**, naming both sizes, whichever way round they differ
- the conversion note when the picked file is not already a `.tga`/`.dds`
- the exact list of paths under the mod's `data/` that will be written, each one
  marked **overwritten** or **created**
- and any same-name file in the other native extension that has to go, so two
  files cannot answer to one name. It is backed up first, so Undo brings it back.

### Open file location

Points the file manager at the file that is actually showing, wherever it lives
— including the unpacked vanilla UI, because "which file am I looking at" is the
question and the answer being outside your mod is the interesting part. With
nothing there yet, it opens the folder one would be created in.

### Under the hood

New `unittransfer/images.py` and `web/js/images.js`; three routes
(`/api/image/plan`, `/api/image/replace`, `/api/image/reveal`). A plan writes
nothing. An apply goes through the same backup + log record as every other job,
so it appears in the log and undoes like a transfer.

**Tests:** `tests/test_images.py`, 53 checks — the route and path refusals, all
five kinds of picture located, the resolution warning both ways round and its
absence when the sizes match, the `.png` conversion, the extension-swap
cleanup, the unit-card fan-out against a real mod's EDU, a plan writing nothing,
and an apply undone byte for byte. The last section drives the real server over
HTTP with the exact JSON the page sends.

---

**Next:** a 3D model viewer, then the Campaign Map Editor, which is 3.0.0.
