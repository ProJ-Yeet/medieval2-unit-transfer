"""Batch model dedup: a model shared by several transferred units must produce a
SINGLE destination entry, not name, name_tag, name_tag_2, ...

Reproduces the reported bug: transferring many units that share an officer used to
append a fresh renamed copy of that officer for every unit, because dedup only
compared against a same-NAMED dest entry. Now identical content is recognised
under any name.

    python -m tests.test_batch_dedup
"""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import config, modeldb
from unittransfer.mod import Mod
from unittransfer.transfer import (TransferOptions, _canon_rel, _folder_tag,
                                   apply_transfer, plan_transfer)

# canonicalise a relocated path (mod_folder default) back for comparison
_TARGET = f"unit_models/{_folder_tag('Third_Age_Reforged')}"
def _canon(p):
    return _canon_rel(p, _TARGET)

MODS = Path(r"C:/Users/projy/Downloads/Games/Total War MEDIEVAL II Definitive Edition/mods")
TATR, DAC = MODS / "Third_Age_Reforged", MODS / "Divide_and_Conquer_EUR"

ok = []


def check(label, cond):
    ok.append(bool(cond))
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}")


cfg = Path(tempfile.mkdtemp(prefix="ut_cfg_"))
config.CONFIG_DIR = cfg
config.BACKUP_DIR = cfg / "backups"
config.SETTINGS_PATH = cfg / "settings.json"
config.LOG_PATH = cfg / "transfers.json"

dest_root = Path(tempfile.mkdtemp(prefix="ut_dest_"))
data = dest_root / "data"
(data / "text").mkdir(parents=True)
(data / "unit_models").mkdir(parents=True)
for rel in ("export_descr_unit.txt", "text/export_units.txt",
            "unit_models/battle_models.modeldb"):
    shutil.copy2(DAC / "data" / rel, data / rel)

src = Mod(TATR)

# Pick a unit whose officer model resolves in the source modeldb (so it's actually
# copied). We transfer it repeatedly under new names to stand in for several units
# that share the same officer.
UNIT = None
for u in src.edu.units:
    if u.officers and src.modeldb.get(u.officers[0]) and src.modeldb.get(u.soldier_model):
        UNIT = u.type
        officer = u.officers[0].lower()
        break
assert UNIT, "no suitable unit found"
print(f"unit={UNIT!r}  shared officer model={officer!r}")


def entries_named_like(db, stem):
    return sorted(n for n in db.by_name() if n == stem or n.startswith(stem + "_"))


N = 4
resolved_types = []
for i in range(N):
    dest = Mod(dest_root)
    # unique target type each time so all N land as separate units
    opts = TransferOptions(include_officers=True, on_conflict="rename",
                           new_type=f"{UNIT} B{i}", new_dictionary=f"nax_b{i}")
    plan = plan_transfer(src, UNIT, dest, opts)
    resolved_types.append(plan.resolved_type)
    act = next((a for a in plan.model_actions if a.source_name == officer), None)
    print(f"  transfer {i} ({plan.resolved_type!r}): officer action = "
          f"{act.action if act else None} -> {act.final_name if act else None}")
    if i == 0:
        check("transfer 0: officer added", act is not None and act.action == "add")
    else:
        check(f"transfer {i}: shared officer is REUSED, not re-added",
              act is not None and act.action == "reuse_identical")
    apply_transfer(plan)

# after N transfers, the officer's content must exist exactly once in the modeldb.
# On disk the paths are relocated (mod_folder default), so compare in canonical space.
db = modeldb.parse_file(data / "unit_models/battle_models.modeldb")
src_entry = src.modeldb.get(officer)
src_key = src_entry.content_key()          # source paths are canonical
same = [n for n, e in db.by_name().items()
        if e.content_key_mapped(lambda p: _canon(p)) == src_key]
print(f"  dest entries with the officer's content: {same}")
check("exactly one dest entry carries the shared officer's content", len(same) == 1)

copies = entries_named_like(db, officer)
print(f"  entries named like {officer!r}: {copies}")
check("no _2/_3 duplicate suffixes for the shared officer",
      not any(c[-1].isdigit() and "_" in c for c in copies if c != officer))

check("modeldb round-trips byte-exact",
      db.to_text() == (data / "unit_models/battle_models.modeldb").read_text(
          encoding=modeldb.ENCODING))

# every appended EDU unit must point its officer line at the single shared entry
from unittransfer import edu as _edu
parsed = _edu.parse_text((data / "export_descr_unit.txt").read_text(encoding=_edu.ENCODING))
appended = [u for u in parsed.units if u.type in set(resolved_types)]
check(f"all {N} copies appended", len(appended) == N)
refs = {u.officers[0].lower() for u in appended if u.officers}
print(f"  officer refs across the copies: {refs}")
check("every copy references the same single officer entry", len(refs) == 1)
check("that ref is the shared dest entry", not same or refs == {same[0]})

shutil.rmtree(dest_root, ignore_errors=True)
shutil.rmtree(cfg, ignore_errors=True)
print("\n" + ("ALL PASSED" if all(ok) else "SOME FAILED"))
sys.exit(0 if all(ok) else 1)
