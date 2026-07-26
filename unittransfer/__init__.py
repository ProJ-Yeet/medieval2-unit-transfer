"""Unit Transfer — move Medieval II: Total War units between mods.

Package layout:
  modeldb.py       parse/write data/unit_models/battle_models.modeldb (length-prefixed archive)
  edu.py           parse/write data/export_descr_unit.txt (unit stat blocks)
  localization.py  parse/write data/text/export_units.txt (UTF-16 name/descr records)
  mod.py           Mod abstraction: paths, faction discovery, lazy DB access
  transfer.py      dependency resolution + cross-mod transfer (Stage 3)
  server.py        local web UI (Stage 2)

Design rule: transfers APPEND verbatim source entries to the destination rather than
re-serializing whole destination files, so untouched entries are never reformatted.
"""

__version__ = "1.0.5"
