"""Voice bank (export_descr_sounds_units_voice.txt): parse, splice, plan, apply, undo.

The whole point of the parser is that it never rewrites a line it wasn't asked to
touch, so most of these checks are byte-for-byte comparisons against the original
file — including "add then remove gives you exactly what you started with".

Uses a TEMP mod (the voice bank + the 3 DB files copied from DaC) and a TEMP config
dir, so neither the real mods nor the project config are touched.

Run:  python -m tests.test_sounds
"""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from unittransfer import config, sounds as S  # noqa: E402
from unittransfer.mod import Mod  # noqa: E402
from unittransfer.transfer import (TransferOptions, plan_transfer,  # noqa: E402
                                   apply_transfer, undo)

MODS = Path(r"C:/Users/projy/Downloads/Games/Total War MEDIEVAL II Definitive Edition/mods")
TATR = MODS / "Third_Age_Reforged"
DAC = MODS / "Divide_and_Conquer_EUR"

results = []


def check(label, cond):
    results.append(bool(cond))
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}")
    return cond


def make_temp_mod(src_mod: Path) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="ut_snd_"))
    data = tmp / "data"
    (data / "text").mkdir(parents=True)
    (data / "unit_models").mkdir(parents=True)
    for rel in ("export_descr_unit.txt", S.EDS_REL):
        shutil.copy2(src_mod / "data" / rel, data / rel)
    shutil.copy2(src_mod / "data" / "text" / "export_units.txt", data / "text" / "export_units.txt")
    shutil.copy2(src_mod / "data" / "unit_models" / "battle_models.modeldb",
                 data / "unit_models" / "battle_models.modeldb")
    return tmp


def use_temp_config():
    tmp = Path(tempfile.mkdtemp(prefix="ut_cfg_"))
    config.CONFIG_DIR = tmp
    config.BACKUP_DIR = tmp / "backups"
    config.SETTINGS_PATH = tmp / "settings.json"
    config.LOG_PATH = tmp / "transfers.json"
    return tmp


def main():
    use_temp_config()

    # ---------- A: parse is lossless ----------
    print("\n=== A: parse round-trip ===")
    dac = Mod(DAC)
    bank = dac.sounds
    original = dac.eds_path.read_text(encoding=S.ENCODING)
    check("to_text() is byte-identical to the file", bank.to_text() == original)
    check("found Unit_Select entries", len(bank.unit_entries()) > 100)
    check("found accents and classes", bank.accents() and bank.classes())
    check("no parse warnings", not bank.warnings)
    # an accent heads several separate blocks in DaC — the parser must not merge them
    heads = [v.accent for v in bank.vocals if v.vocal == S.UNIT_SELECT]
    check("repeated accent blocks kept separate", len(heads) > len(set(heads)))

    donor = bank.unit_entries()[0]
    other = next(e for e in bank.unit_entries()
                 if e.name != donor.name and (e.accent, e.voice_class)
                 != (donor.accent, donor.voice_class))

    # ---------- B: add / remove is exactly reversible ----------
    print("\n=== B: add then remove restores the file ===")
    added = S.add_unit(bank, "UT Test Unit", donor, donor.accent, donor.voice_class)
    b2 = S.parse_text(added)
    e = b2.get("UT Test Unit")
    check("the new entry exists", e is not None)
    check("it landed in the donor's block",
          e and (e.accent, e.voice_class) == (donor.accent, donor.voice_class))
    check("its sounds are the donor's",
          "".join(b2.lines[e.start + 1:e.end])
          == "".join(bank.lines[donor.start + 1:donor.end]))
    check("only the new lines were added",
          len(b2.lines) - len(bank.lines) == donor.end - donor.start)
    check("remove gives back the original file", S.remove_unit(b2, "UT Test Unit") == original)

    # ---------- C: move ----------
    print("\n=== C: move to another accent/class ===")
    moved = S.move_unit(b2, "UT Test Unit", other.accent, other.voice_class, None)
    b3 = S.parse_text(moved)
    e3 = b3.get("UT Test Unit")
    check("moved to the target block",
          e3 and (e3.accent, e3.voice_class) == (other.accent, other.voice_class))
    check("exactly one entry left (not copied twice)",
          [x.name for x in b3.unit_entries()].count("UT Test Unit") == 1)
    check("line count unchanged by the move", len(b3.lines) == len(b2.lines))
    check("remove after the move restores the original",
          S.remove_unit(b3, "UT Test Unit") == original)

    print("\n=== C2: move an existing unit and re-copy its sounds ===")
    swapped = S.move_unit(bank, donor.name, other.accent, other.voice_class, other)
    b4 = S.parse_text(swapped)
    e4 = b4.get(donor.name)
    check("donor moved to the other block",
          e4 and (e4.accent, e4.voice_class) == (other.accent, other.voice_class))
    check("it now carries the other unit's sounds",
          "".join(b4.lines[e4.start + 1:e4.end])
          == "".join(bank.lines[other.start + 1:other.end]))
    check("no entry gained or lost", len(b4.unit_entries()) == len(bank.unit_entries()))

    # ---------- D: EDU side ----------
    print("\n=== D: EDU accent / voice_type ===")
    block = "type\t\t\tX\nclass\t\t\theavy\nsoldier\t\t\tfoo, 60, 0, 1.0\n"
    out = S.set_voice_fields(block, "German", "Heavy")
    check("accent added", "accent" in out and "German" in out)
    check("voice_type added", "voice_type" in out and "Heavy" in out)
    check("voice fields sit before soldier",       # canonical EDU order
          out.index("accent") < out.index("soldier"))
    check("nothing else was touched", "soldier\t\t\tfoo, 60, 0, 1.0" in out)
    again = S.set_voice_fields(out, "Arabic", "Light")
    check("an existing accent is replaced, not duplicated", again.count("accent") == 1)
    check("an existing voice_type is replaced", again.count("voice_type") == 1)

    # ---------- E: plan + apply + undo in Sounds mode ----------
    print("\n=== E: Sounds mode plan / apply / undo ===")
    mod_root = make_temp_mod(DAC)
    mod = Mod(mod_root)
    eds_before = mod.eds_path.read_bytes()
    edu_before = mod.edu_path.read_bytes()

    d = mod.sounds.unit_entries()[0]
    mute = next(u.type for u in mod.edu.units if mod.sounds.get(u.type) is None)
    plan = S.plan_sounds(mod, S.ops_from_dicts(
        [{"unit": mute, "accent": d.accent, "class": d.voice_class, "donor": d.name}]))
    check("plan has no errors", not plan.errors)
    check("plan rewrites both files", bool(plan.eds_text) and bool(plan.edu_text))
    rec = S.apply_sounds(plan)
    after = Mod(mod_root)
    check("the unit now has a voice entry", after.sounds.get(mute) is not None)
    accent, cls = S.unit_voice_fields(after.edu.by_type()[mute])
    check("its EDU accent/voice_type match the entry", (accent, cls) == (d.accent, d.voice_class))
    check("the backup manifest lists both files",
          sorted(rec["manifest"]["backed_up"]) == sorted([S.EDS_REL, "export_descr_unit.txt"]))
    undo(rec["id"])
    check("undo restores the voice bank byte-exact",
          (mod_root / "data" / S.EDS_REL).read_bytes() == eds_before)
    check("undo restores the EDU byte-exact",
          (mod_root / "data" / "export_descr_unit.txt").read_bytes() == edu_before)

    print("\n=== E1b: the file on disk only gains the lines it should ===")
    # The one thing that would ruin a real mod without ever raising: the voice bank
    # is CRLF, and the write path reads/writes through Python's universal newlines.
    # Diff the actual bytes rather than trust that round-trip.
    import difflib
    mod2 = Mod(make_temp_mod(DAC))
    raw_before = mod2.eds_path.read_bytes()
    crlf_before = raw_before.count(b"\r\n")
    check("the source voice bank is CRLF with no bare LF",
          crlf_before and raw_before.count(b"\n") == crlf_before)
    d2 = mod2.sounds.unit_entries()[0]
    mute2 = next(u.type for u in mod2.edu.units if mod2.sounds.get(u.type) is None)
    S.apply_sounds(S.plan_sounds(mod2, S.ops_from_dicts(
        [{"unit": mute2, "accent": d2.accent, "class": d2.voice_class, "donor": d2.name}])))
    raw_after = mod2.eds_path.read_bytes()
    check("no bare LF was introduced",
          raw_after.count(b"\n") == raw_after.count(b"\r\n"))
    added = d2.end - d2.start
    check("exactly the copied block's worth of new lines",
          raw_after.count(b"\r\n") == crlf_before + added)
    delta = [l for l in difflib.unified_diff(raw_before.decode(S.ENCODING).splitlines(True),
                                             raw_after.decode(S.ENCODING).splitlines(True), n=0)
             if l[0] in "+-" and not l.startswith(("---", "+++"))]
    check("every changed line is an addition — nothing was rewritten",
          len(delta) == added and all(l.startswith("+") for l in delta))

    print("\n=== E2: a plan that can't work reports it instead of guessing ===")
    bad = S.plan_sounds(mod, S.ops_from_dicts(
        [{"unit": mute, "accent": "NoSuchAccent", "class": "Heavy", "donor": d.name}]))
    check("unknown accent/class is an error", bool(bad.errors))
    check("nothing is written for a failed plan", not bad.eds_text and not bad.edu_text)
    nodonor = S.plan_sounds(mod, S.ops_from_dicts(
        [{"unit": mute, "accent": d.accent, "class": d.voice_class}]))
    check("adding with no donor is an error", bool(nodonor.errors))

    # ---------- F: sound options on a transfer ----------
    print("\n=== F: transfer sound modes ===")
    src = Mod(TATR)
    dest = Mod(make_temp_mod(DAC))
    base = next(u.type for u in dest.edu.units
                if u.kind() == "Infantry" and dest.sounds.get(u.type))
    unit = next(u.type for u in src.edu.units
                if u.kind() == "Infantry" and u.type not in dest.edu.by_type())
    bentry = dest.sounds.get(base)

    p = plan_transfer(src, unit, dest, TransferOptions(base_type=base, sound_mode="base"))
    check("base mode copies the base's voice", p.sound_action == "copy")
    check("it uses the base as donor", p.sound_donor == base)
    check("accent/class come from the base's entry",
          (p.sound_accent, p.sound_class) == (bentry.accent, bentry.voice_class))

    p_none = plan_transfer(src, unit, dest, TransferOptions(sound_mode="none"))
    check("none mode writes nothing", p_none.sound_action == "none" and not p_none.sound_text)

    p_nobase = plan_transfer(src, unit, dest, TransferOptions(sound_mode="base"))
    check("base mode with no base is reported, not silent",
          p_nobase.sound_action == "no_base" and not p_nobase.sound_text)

    p_unit = plan_transfer(src, unit, dest,
                           TransferOptions(sound_mode="unit", sound_donor=base))
    check("unit mode copies the named donor", p_unit.sound_action == "copy")
    check("a different base than the voice donor is allowed",
          plan_transfer(src, unit, dest,
                        TransferOptions(base_type=base, sound_mode="unit",
                                        sound_donor=bentry.name)).sound_donor == bentry.name)

    p_missing = plan_transfer(src, unit, dest,
                              TransferOptions(sound_mode="unit", sound_donor="No Such Unit"))
    check("an unknown donor warns instead of failing the transfer",
          p_missing.sound_action == "missing" and not p_missing.sound_text)

    print("\n=== F2: apply + undo a transfer that carries a voice ===")
    eds_before = dest.eds_path.read_bytes()
    plan = plan_transfer(src, unit, dest, TransferOptions(base_type=base, sound_mode="base"))
    rec = apply_transfer(plan)
    live = Mod(dest.root)
    entry = live.sounds.get(plan.resolved_type)
    check("the transferred unit has a voice entry", entry is not None)
    check("in the base's block",
          entry and (entry.accent, entry.voice_class) == (bentry.accent, bentry.voice_class))
    accent, cls = S.unit_voice_fields(live.edu.by_type()[plan.resolved_type])
    check("its EDU accent/voice_type were pinned to match",
          (accent, cls) == (bentry.accent, bentry.voice_class))
    check("the voice bank was backed up", S.EDS_REL in rec["manifest"]["backed_up"])
    undo(rec["id"])
    check("undo restores the voice bank byte-exact",
          (dest.root / "data" / S.EDS_REL).read_bytes() == eds_before)

    ok = all(results)
    print(f"\n{'ALL PASS' if ok else 'FAILURES'}  ({sum(results)}/{len(results)})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
