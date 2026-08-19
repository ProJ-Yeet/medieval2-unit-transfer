"""The trigger grammar: round-trip fidelity, the vocabulary, and the builder.

The gate for Phase 7 is that this parser can read every trigger in every EDCT and
EDA on the machine, name every construct in them, and hand back the file byte for
byte. Nothing built on top of it — the traits editor, the ancillaries editor — is
worth anything if that is not true, because both of them save by splicing lines
back into a file the user has spent years hand-formatting.

What each part is here to catch:

  * ``parse_text(t).text() == t`` on hand-built files with every awkward thing
    real ones have: CRLF, tabs, comment banners, inline comments, blank lines
    inside a condition block, a trigger with no conditions
  * every construct classified — a term the vocabulary has never heard of is
    *reported*, not dropped, and still round-trips
  * ``render_block`` edits: an untouched clause keeps its exact line (indent and
    inline comment included), a changed one changes, and added/removed clauses
    move only themselves
  * the never-fires check: a condition whose required data type the event does
    not export, with the "or" alternatives read correctly (``Religion`` accepts
    any one of six, and reading that as one literal type would cry wolf on a
    hundred sound triggers)
  * the builder's own logic under ``node`` — the requirement/export test it draws
    its warnings from must agree with the Python one

Needs no game install for any of the above. When mods ARE installed it also
sweeps every real EDCT and EDA, which is the check that actually matters.

    python -m tests.test_triggers
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import config, triggers

ok = []


def check(label, cond):
    ok.append(bool(cond))
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}")


# Everything a real EDCT does that a naive parser gets wrong: a comment banner
# between triggers, an inline comment on a clause, tabs and spaces mixed, a blank
# line inside a condition block, a trigger with no conditions at all, and a term
# no vocabulary lists.
FILE = (
    ";------ banner ------\r\n"
    "Trait Brave\r\n"
    "  Characters family\r\n"
    "\r\n"
    "  Level Brave\r\n"
    "    Threshold 1\r\n"
    "\r\n"
    ";== TRIGGER DATA STARTS HERE ==\r\n"
    "\r\n"
    "Trigger battle_won\r\n"
    "  WhenToTest PostBattle\r\n"
    "  Condition IsGeneral\r\n"
    "\t\t and Trait Brave > 0\t; only the brave ones\r\n"
    "\r\n"
    "         and not WonBattle\r\n"
    "\r\n"
    "  Affects Brave 1 Chance 100\r\n"
    "\r\n"
    "Trigger always\r\n"
    "  WhenToTest CharacterTurnStart\r\n"
    "  Affects Brave -1 Chance 5\r\n"
    "\r\n"
    "Trigger invented\r\n"
    "  WhenToTest CharacterTurnEnd\r\n"
    "  Condition NotARealCondition foo > 3\r\n"
    "  Affects Brave 1 Chance 100\r\n"
)

print("== the file comes back exactly as it went in ==")
tf = triggers.parse_text(FILE)
check("byte-identical round trip", tf.text() == FILE)
check("three triggers found", len(tf.triggers) == 3)
check("the trait definition above them is not mistaken for one",
      [t.name for t in tf.triggers] == ["battle_won", "always", "invented"])
check("and its name is collected for the operand pickers",
      tf.definitions.get("Trait") == ["Brave"])

t0 = tf.triggers[0]
check("WhenToTest read", t0.when_to_test == "PostBattle")
check("three clauses, across blank lines and a comment", len(t0.conditions) == 3)
check("the first clause has no joiner", t0.conditions[0].joiner == "")
check("`and not X` parses as a negated clause",
      t0.conditions[2].joiner == "and" and t0.conditions[2].negated
      and t0.conditions[2].term == "WonBattle")
check("a clause's operands are kept in order",
      t0.conditions[1].args == ["Brave", ">", "0"])
check("its shape is measured from the operands",
      t0.conditions[1].shape == "name op num")
check("an inline comment stays on the clause's line", "; only the brave" in t0.conditions[1].raw)
check("the effect line is read", t0.effects[0].keyword == "Affects"
      and t0.effects[0].args == ["Brave", "1", "Chance", "100"])
check("a trigger with no conditions is fine", not tf.triggers[1].conditions)

print("\n== an unknown term is reported, never dropped ==")
unknown = triggers.unknown_terms(tf)
check("the invented condition is listed",
      len(unknown) == 1 and unknown[0]["term"] == "NotARealCondition")
check("…and it still parsed", tf.triggers[2].conditions[0].args == ["foo", ">", "3"])
check("…and the file still round-trips", tf.text() == FILE)

print("\n== a trigger that can never fire ==")
if triggers.vocab().get("missing"):
    print("  (no trigger_vocab.json — run tools/trigger_vocab.py)")
else:
    findings = triggers.check(tf.triggers[0])
    check("PostBattle + IsGeneral + Trait + WonBattle is sound", not findings)
    bad = triggers.parse_text(
        "Trigger t\r\n  WhenToTest CharacterComesOfAge\r\n"
        "  Condition SettlementBuildingExists >= market\r\n").triggers[0]
    f = triggers.check(bad)
    check("a condition needing `settlement` under an event that exports none is caught",
          len(f) == 1 and f[0]["kind"] == "missing-export" and "settlement" in f[0]["message"])
    # Religion's requirement is a disjunction — six alternatives, any one enough.
    rel = triggers.parse_text(
        "Trigger t\r\n  WhenToTest CharacterTurnEnd\r\n"
        "  Condition Religion catholic\r\n").triggers[0]
    check("an `or` requirement satisfied by one alternative is not flagged",
          not triggers.check(rel))
    check("satisfied() reads groups as (a and b) or c",
          triggers.satisfied([["a", "b"], ["c"]], {"c"})
          and triggers.satisfied([["a", "b"], ["c"]], {"a", "b"})
          and not triggers.satisfied([["a", "b"], ["c"]], {"a"})
          and triggers.satisfied([], set()))
    ghost = triggers.parse_text(
        "Trigger t\r\n  WhenToTest OnCharacterTurnStart\r\n").triggers[0]
    check("an event the engine does not have is caught (their list is full of these)",
          triggers.check(ghost)[0]["kind"] == "unknown-event")

print("\n== editing is a splice, not a re-emit ==")
block = tf.block_text(tf.triggers[0])
same = triggers.render_block(block, {})
check("rendering no edits changes nothing at all", same == block)
one = triggers.render_block(block, {"conditions": [
    {"term": "IsGeneral", "args": []},
    {"term": "Trait", "args": ["Brave", ">=", "2"]},
    {"term": "WonBattle", "args": [], "negated": True, "joiner": "and"}]})
lines_before, lines_after = block.split("\n"), one.split("\n")
check("only the changed clause's line changed",
      sum(1 for a, b in zip(lines_before, lines_after) if a != b) == 1)
check("the changed clause reads back", "Trait Brave >= 2" in one)
check("its inline comment survived the edit", "; only the brave" in one)
check("its tabs survived too", "\t\t and Trait" in one)
check("blank lines inside the block are untouched", one.count("\n\n") == block.count("\n\n"))

added = triggers.render_block(block, {"conditions": [
    {"term": "IsGeneral", "args": []},
    {"term": "Trait", "args": ["Brave", ">", "0"]},
    {"term": "WonBattle", "args": [], "negated": True, "joiner": "and"},
    {"term": "BattleOdds", "args": [">=", "1"], "joiner": "and"}]})
check("an added clause lands after the last one",
      "and BattleOdds >= 1" in added
      and added.index("BattleOdds") > added.index("WonBattle"))
check("…and copies the indent of the clauses it joins",
      re.search(r"\n( +)and BattleOdds", added).group(1) == "         ")
dropped = triggers.render_block(block, {"conditions": [
    {"term": "IsGeneral", "args": []}]})
check("removed clauses take only their own lines",
      "Trait Brave" not in dropped and "WonBattle" not in dropped
      and "Affects Brave 1 Chance 100" in dropped)
renamed = triggers.render_block(block, {"name": "renamed", "when_to_test": "PreBattle"})
check("the name and the event can be set",
      "Trigger renamed" in renamed and "WhenToTest PreBattle" in renamed)
check("a whole block can be spliced back into its file",
      triggers.replace_block(tf, tf.triggers[0], one).count("Trait Brave >= 2") == 1)

print("\n== one block on its own, as the code view holds it ==")
check("spans point at real lines",
      triggers.block_spans(block)["when_to_test"] == [[2, 2]])
check("fields list the clauses in order",
      [k for k, _ in triggers.block_fields(block)]
      == ["name", "when_to_test", "condition#1", "condition#2", "condition#3", "effect#1"])
for bad, why in [("nothing here", "no Trigger line"),
                 (block + "\nTrigger second\n  WhenToTest PostBattle\n", "two blocks")]:
    try:
        triggers.parse_block(bad)
        check(f"refused: {why}", False)
    except triggers.TriggerError:
        check(f"refused: {why}", True)

print("\n== the vocabulary is data, and it is served ==")
v = triggers.vocab()
if v.get("missing"):
    print("  (no trigger_vocab.json)")
else:
    check("it has the engine's conditions and events",
          len(v["conditions"]) > 300 and len(v["events"]) > 150)
    check("every entry carries a shape the GUI can draw",
          all(c["shapes"] for c in v["conditions"]))
    check("Trait's shape is `name op num`, measured from real files",
          triggers.term_def("Trait")["shapes"][0] == "name op num")
    check("an event carries what it exports",
          "character_record" in triggers.event_def("PostBattle")["exports"])
    check("the invented events from the reference tool are absent",
          triggers.event_def("OnCharacterTurnStart") is None
          and triggers.event_def("CharacterTurnStart") is not None)
    check("…and its invented conditions too",
          triggers.term_def("IsSpy") is None and triggers.term_def("IsGeneral") is not None)
    payload = triggers.vocab_payload(None)
    check("the API payload carries the operand sources the builder needs",
          payload["operand_sources"]["Trait"] == "traits"
          and payload["operands"]["attributes"])

print("\n== the builder agrees with the parser (node) ==")
node = shutil.which("node")
js = (ROOT / "web" / "js" / "triggerui.js")
if not node:
    print("  (node not on PATH — skipped; node is not a dependency of the tool)")
elif not js.exists():
    check("web/js/triggerui.js exists", False)
else:
    cases = [([["a", "b"], ["c"]], ["c"], True), ([["a", "b"], ["c"]], ["a", "b"], True),
             ([["a", "b"], ["c"]], ["a"], False), ([], [], True),
             ([["settlement"]], ["character_record"], False)]
    src = js.read_text(encoding="utf-8")
    harness = src + "\nconsole.log(JSON.stringify(" + json.dumps(
        [c[:2] for c in cases]) + ".map(a=>trgSatisfied(a[0],a[1]))));"
    tmp = Path(tempfile.mkdtemp(prefix="ut-trg-")) / "h.js"
    tmp.write_text(harness, encoding="utf-8")
    res = subprocess.run([node, str(tmp)], capture_output=True, text=True)
    shutil.rmtree(tmp.parent, ignore_errors=True)
    if res.returncode != 0:
        check(f"the builder loads under node ({res.stderr.strip()[:80]})", False)
    else:
        got = json.loads(res.stdout.strip().splitlines()[-1])
        want = [c[2] for c in cases]
        check("its requirement test matches Python's on every case", got == want)
        check("…including the Python side", [triggers.satisfied(a, set(b))
                                             for a, b, _ in cases] == want)

print("\n== every EDCT and EDA on this machine ==")
root = config.get_med2_root()
mods = Path(root) / "mods" if root else None
found = []
if mods and mods.is_dir():
    for mod in sorted(p for p in mods.iterdir() if p.is_dir()):
        for name in ("export_descr_character_traits.txt", "export_descr_ancillaries.txt"):
            p = mod / "data" / name
            if p.exists():
                found.append(p)
if not found:
    print("  (no mods installed — the hand-built file above is the whole check)")
else:
    bad, unknown_all, trig_n, cond_n = [], [], 0, 0
    for p in found:
        raw = p.read_text(encoding=triggers.ENCODING)
        parsed = triggers.parse_text(raw)
        if parsed.text() != raw:
            bad.append(p.name)
        trig_n += len(parsed.triggers)
        cond_n += sum(len(t.conditions) for t in parsed.triggers)
        unknown_all += triggers.unknown_terms(parsed)
    check(f"all {len(found)} files round-trip byte for byte "
          + (f"(failed: {bad})" if bad else ""), not bad)
    check(f"every construct in {trig_n} triggers / {cond_n} conditions is known "
          + (f"(unknown: {sorted({u['term'] for u in unknown_all})[:5]})"
             if unknown_all else ""), not unknown_all)
    # Every clause re-emits to the same TOKENS it was read from. Not the same
    # characters: real files put tabs between a term and its operand, and the
    # canonical form uses single spaces. That difference can never reach a file,
    # because an unedited clause is never re-emitted at all — which the next
    # check is what proves.
    off = []
    for p in found:
        for trig in triggers.parse_file(p).triggers:
            for c in trig.conditions:
                code = c.raw.split(";", 1)[0].split()
                head = [] if c.joiner else ["Condition"]
                if code != head + c.text().split():
                    off.append((p.name, trig.name, " ".join(code)))
    check(f"every clause re-emits to the tokens it was read from "
          + (f"(off: {off[:2]})" if off else ""), not off)

    # …and the reason that difference is harmless: re-rendering a real block with
    # its own parsed clauses gives the block back unchanged, tabs and all.
    churn = []
    for p in found:
        parsed = triggers.parse_file(p)
        for trig in parsed.triggers[:200]:
            blk = parsed.block_text(trig)
            same = triggers.render_block(blk, {"conditions": [
                {"term": c.term, "args": c.args, "joiner": c.joiner,
                 "negated": c.negated} for c in trig.conditions]})
            if same != blk:
                churn.append((p.name, trig.name))
    check(f"re-rendering a real block with its own clauses rewrites nothing "
          + (f"({len(churn)} churned, e.g. {churn[:2]})" if churn else ""), not churn)

print(f"\n{sum(ok)}/{len(ok)} checks — " + ("ALL PASSED" if all(ok) else "SOME FAILED"))
sys.exit(0 if all(ok) else 1)
