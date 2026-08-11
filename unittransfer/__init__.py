"""Unit Transfer — move Medieval II: Total War units between mods.

Package layout:
  modeldb.py       parse/write data/unit_models/battle_models.modeldb (length-prefixed archive)
  edu.py           parse/write data/export_descr_unit.txt (unit stat blocks)
  eop.py           M2TWEOP units: the same EDU blocks, kept in the extender's own
                   files — discovery, parsing, and routing writes back to them
  luascan.py       what the mod's .lua scripts name, so the modeldb cleanup never
                   removes a battle model an M2TWEOP script still uses
  localization.py  parse/write data/text/export_units.txt (UTF-16 name/descr records)
  cleaner.py       delete the compiled export_units.txt.strings.bin after a job, so
                   the game re-reads the text instead of its stale cache
  mod.py           Mod abstraction: paths, faction discovery, lazy DB access
  transfer.py      dependency resolution + cross-mod transfer (Stage 3)
  edit.py          unit EDITOR mode: change/create/delete units inside one mod
  bmdb.py          BMDB mode: the whole modeldb — browse/edit any entry, audit what
                   nothing references, and export the dead weight out of the mod
  pack.py          unit packs: units in a zip for someone else's machine. A pack
                   IS a mod, so importing one is an ordinary transfer out of it
  server.py        local web UI (Stage 2)

Design rule: transfers APPEND verbatim source entries to the destination rather than
re-serializing whole destination files, so untouched entries are never reformatted.

Second design rule: a mod's roster is ``mod.edu.units`` — EDU units and M2TWEOP
units together — so every feature is EOP-aware by default. Only the *write* side
distinguishes them, via :func:`unittransfer.eop.compose`.
"""

__version__ = "1.9.9"
