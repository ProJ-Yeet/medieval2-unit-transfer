"""Per-model secondary selection: exclude_models lets you pick officer/crew models
individually instead of the whole group.

    python -m tests.test_individual_models
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer.mod import Mod
from unittransfer.transfer import TransferOptions, plan_transfer

MODS = Path(r"C:/Users/projy/Downloads/Games/Total War MEDIEVAL II Definitive Edition/mods")
TATR, DAC = MODS / "Third_Age_Reforged", MODS / "Divide_and_Conquer_EUR"

ok = []
def check(label, cond):
    ok.append(bool(cond)); print(f"  [{'OK ' if cond else 'FAIL'}] {label}")

src, dest = Mod(TATR), Mod(DAC)

# a unit with >=2 distinct officer models, both resolvable in the source modeldb
UNIT = None
for u in src.edu.units:
    offs = [o.lower() for o in u.officers if src.modeldb.get(o)]
    if len(set(offs)) >= 2:
        UNIT, off_models = u.type, list(dict.fromkeys(offs))
        break
assert UNIT, "no unit with 2+ officer models found"
keep, drop = off_models[0], off_models[1]
print(f"unit={UNIT!r} officers={off_models}  keep={keep}  drop={drop}")

def acted(plan, name):
    return next((a for a in plan.model_actions if a.source_name == name), None)

# baseline: both officers included
p_all = plan_transfer(src, UNIT, dest, TransferOptions(include_officers=True))
check("baseline includes the kept officer", acted(p_all, keep) is not None)
check("baseline includes the dropped officer", acted(p_all, drop) is not None)

# exclude ONE officer model individually
p = plan_transfer(src, UNIT, dest,
                  TransferOptions(include_officers=True, exclude_models=[drop]))
check("excluded officer is NOT in model actions", acted(p, drop) is None)
check("excluded officer listed as excluded secondary", drop in p.excluded_secondaries)
check("kept officer still included", acted(p, keep) is not None)
check("kept officer NOT excluded", keep not in p.excluded_secondaries)

# group off overrides everything (both excluded)
p_off = plan_transfer(src, UNIT, dest, TransferOptions(include_officers=False))
check("group off excludes both officers",
      all(m in p_off.excluded_secondaries for m in off_models))

# soldier model is never excludable via exclude_models (it's primary)
p_sold = plan_transfer(src, UNIT, dest,
                       TransferOptions(exclude_models=[src.edu.by_type()[UNIT].soldier_model.lower()]))
check("soldier stays included even if named in exclude_models",
      acted(p_sold, src.edu.by_type()[UNIT].soldier_model.lower()) is not None)

print("\n" + ("ALL PASSED" if all(ok) else "SOME FAILED"))
sys.exit(0 if all(ok) else 1)
