"""The unit comparison table, and bulk requires-clause edits over recruit pools.

Both features are pure JavaScript in ``web/index.html`` — no server call decides
which unit "wins" a stat, and no server call merges one recruit pool's clause
onto twenty others. So this suite runs the page's own functions under node,
against real mod data, and checks the parts that are easy to get quietly wrong:

  * every stat named in ``CMP_MERIT`` / ``CMP_ORDER`` still exists as a slot of
    the field it claims to belong to. These are string keys — ``stat_pri|Attack``
    — so renaming a part label in ``GF_FIELDS`` would silently stop colouring the
    slot rather than fail, and the table would just look duller.
  * ``cmpVerdict`` calls a winner only where there is one: bigger wins for
    attack, smaller wins for upkeep, the training ladder is ordered, and a line
    one of the two units does not HAVE never loses on its zeroes.
  * ``cmpBuild`` over two real units accounts for every slot exactly once and
    keeps identity lines (``type``, ``dictionary``) out of a stat comparison.
  * ``bldCondsOnto`` — replace swaps the clause, add concatenates, a term the
    row already carries is not written twice, and applying the same paste again
    changes nothing. That last one matters: pasting is a button you press when
    you are not sure whether it took.

Run it with:

    python -m tests.test_compare_and_bulk
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

from unittransfer.mod import Mod

MODS = Path(r"C:/Users/projy/Downloads/Games/Total War MEDIEVAL II Definitive Edition/mods")
WEB = ROOT / "web" / "index.html"

ok = []


def check(label, cond):
    ok.append(bool(cond))
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}")


def installed_mods():
    if not MODS.is_dir():
        return []
    return [Mod(p) for p in sorted(MODS.iterdir())
            if (p / "data" / "export_descr_unit.txt").exists()]


STUBS = r"""
const noop=()=>{};
globalThis.document={addEventListener:noop,getElementById:()=>null,
  querySelector:()=>null,querySelectorAll:()=>[],createElement:()=>({style:{},classList:{add:noop}}),
  body:{appendChild:noop}};
globalThis.window={addEventListener:noop,innerWidth:1280,innerHeight:800};
globalThis.fetch=()=>Promise.reject(new Error('no network'));
"""

HARNESS = r"""
const out={merit:[],order:[],verdict:[],build:null,conds:[]};

// ---- 1) every coloured slot still exists ----------------------------------
for(const id of Object.keys(CMP_MERIT).concat(Object.keys(CMP_ORDER))){
  const i=id.indexOf('|'), key=id.slice(0,i), pl=id.slice(i+1);
  const spec=GF_FIELDS[key];
  const found=!!(spec&&spec.parts&&spec.parts.some(p=>p.pl===pl));
  (CMP_MERIT[id]!==undefined?out.merit:out.order).push({id,found});
}

// ---- 2) the verdict itself -------------------------------------------------
const pl=(key,name)=>GF_FIELDS[key].parts.find(p=>p.pl===name);
const V=(what,key,name,a,b,absent)=>{
  const v=cmpVerdict(key,name?pl(key,name):null,a,b,absent||'');
  out.verdict.push({what,win:v.win||'',gap:v.gap||'',same:!!v.same,diff:!!v.diff});
};
V('attack 12 vs 8 — bigger wins',      'stat_pri','Attack','12','8');
V('attack 8 vs 12 — the other side',   'stat_pri','Attack','8','12');
V('attack 10 vs 10 — identical',       'stat_pri','Attack','10','10');
V('weapon delay 20 vs 25 — faster wins','stat_pri','Delay','20','25');
V('upkeep 120 vs 300 — cheaper wins',  'stat_cost','Upkeep','120','300');
V('recruit turns 1 vs 2 — fewer wins', 'stat_cost','Turns','1','2');
V('free picks is a setting, not a merit','stat_cost','Free picks','2','5');
V('skeleton factor has no better side','stat_pri','Skel. factor','1','1.1');
V('training ladder is ordered',        'stat_mental','Training','highly_trained','trained');
V('impetuous is different, not better','stat_mental','Discipline','impetuous','disciplined');
V('a hit sound is just different',     'stat_pri','Hit sound','axe','sword');
V('morale 18 vs 19',                   'stat_mental','Morale','18','19');
V('armour 8 vs 7',                     'stat_pri_armour','Armour','8','7');
V('heat fatigue 4 vs 1 — less is better','stat_heat','Heat','4','1');
V('nothing wins a line one of them lacks','stat_armour_ex','Armour 0','0','12','a');
V('a non-numeric value never wins',    'stat_pri','Attack','lots','8');

// ---- 3) the table over two real units --------------------------------------
function blockFields(raw){
  const res=[],counts={};
  for(const line of raw.split(/\r?\n/)){
    const s=line.trim(); if(!s||s.startsWith(';'))continue;
    let m=/^(banner\s+\w+|era\s+\d+)\s*(.*)$/i.exec(s),key,rest;
    if(m){key=m[1].replace(/\s+/g,' ');rest=m[2];}
    else{m=/^(\S+)\s*(.*)$/.exec(s); if(!m)continue; key=m[1]; rest=m[2];}
    rest=rest.split(';')[0].trim();
    counts[key]=(counts[key]||0)+1;
    res.push([counts[key]===1?key:key+'#'+counts[key],rest]);
  }
  return res;
}
const blocks=EDU_TEXT.split(/^(?=type\s)/m).filter(b=>/^type\s/.test(b)).map(blockFields);
const side=f=>{const m=new Map(f);return {val:l=>m.has(l)?m.get(l):'',has:l=>m.has(l)};};
const labelsOf=(a,b)=>{const s=[],seen=new Set();
  a.concat(b).forEach(([l])=>{if(!seen.has(l)){seen.add(l);s.push(l);}}); return s;};
{
  const a=blocks[0],b=blocks[1];
  const labels=labelsOf(a,b);
  const m=cmpBuild(side(a),side(b),labels);
  const rows=[].concat(...m.sections.map(s=>[].concat(...s.fields.map(f=>f.rows))));
  const t=m.tally;
  out.build={
    units:blocks.length,
    sections:m.sections.map(s=>s.id),
    rows:rows.length,
    tallied:t.a+t.b+t.neu+t.same,
    // identity lines must not be in a stat table
    identity:rows.some(r=>r.key==='type'||r.key==='dictionary'),
    // a slot the two agree on is "same" and never also a win
    contradiction:rows.some(r=>r.v.same&&r.v.win),
    // stat_pri is eleven values, so it must produce eleven rows, not one
    priRows:rows.filter(r=>r.key==='stat_pri').length,
    priParts:GF_FIELDS['stat_pri'].parts.length,
    // a unit compared with ITSELF has no differences at all
    selfDiff:(()=>{const s=cmpBuild(side(a),side(a),labelsOf(a,a)).tally;
                   return s.a+s.b+s.neu;})(),
  };
}

// ---- 4) putting one clause onto another row --------------------------------
const C=(kind,values,join)=>({join:join||'',negate:false,kind,values,raw:''});
const mkrow=conds=>({conds:JSON.parse(JSON.stringify(conds)),requires:'',condEdited:false});
const say=(what,got,want)=>out.conds.push({what,got,want,ok:got===want});
{
  const src=[C('factions',['gondor','rohan'])];
  const r=mkrow([C('hidden_resource',['Arthedain'])]);
  bldCondsOnto(r,src,'replace');
  say('replace swaps the clause outright',
      bldClauseText(r.conds),'factions { gondor, rohan, }');
  say('replace writes the row’s requires text too',
      r.requires,'factions { gondor, rohan, }');
  say('replace marks the row as edited', r.condEdited?'yes':'no','yes');
}
{
  const r=mkrow([C('hidden_resource',['Arthedain'])]);
  bldCondsOnto(r,[C('factions',['gondor'])],'add');
  say('add concatenates onto what is there',
      bldClauseText(r.conds),'hidden_resource Arthedain and factions { gondor, }');
  bldCondsOnto(r,[C('factions',['gondor'])],'add');
  say('add is idempotent — the same term is not written twice',
      bldClauseText(r.conds),'hidden_resource Arthedain and factions { gondor, }');
  bldCondsOnto(r,[C('event_counter',['x','1'])],'add');
  say('add still appends a term that IS new',
      bldClauseText(r.conds),
      'hidden_resource Arthedain and factions { gondor, } and event_counter x 1');
}
{
  const r=mkrow([]);
  bldCondsOnto(r,[C('factions',['gondor']),C('hidden_resource',['R'],'or')],'add');
  say('adding onto an empty clause leaves no dangling join',
      bldClauseText(r.conds),'factions { gondor, } or hidden_resource R');
  say('the first term never carries a join', r.conds[0].join,'');
}
{
  const r=mkrow([C('factions',['gondor'])]);
  bldCondsOnto(r,[],'replace');
  say('replacing with nothing clears the clause', bldClauseText(r.conds),'');
}
{
  // the paste must be a COPY: editing one row afterwards must not touch another
  const src=[C('factions',['gondor'])];
  const a=mkrow([]),b=mkrow([]);
  bldCondsOnto(a,src,'replace'); bldCondsOnto(b,src,'replace');
  a.conds[0].values.push('rohan');
  say('each row gets its own copy of the terms',
      bldClauseText(b.conds),'factions { gondor, }');
  say('…and the clipboard itself is untouched',
      bldClauseText(src),'factions { gondor, }');
}

console.log(JSON.stringify(out));
"""


print("\n-- compare & bulk (node) --")
node = shutil.which("node")
mods = installed_mods()
if not node:
    print("  [skip] node is not on PATH — the page's own JS cannot be exercised")
elif not WEB.exists():
    print("  [skip] web/index.html not found")
elif not mods:
    print("  [skip] no mod installed to compare units from")
else:
    # Since the Phase 3 split the page's code is web/js/*.js, loaded as plain
    # <script src> tags — one global scope, so concatenating them in tag order IS
    # the page's program. (Scraping an inline <script> block, as this used to,
    # now finds the HTML comment that explains the split and reads the comment.)
    src = WEB.read_text(encoding="utf-8")
    tags = re.findall(r'<script src="js/([A-Za-z0-9_.-]+\.js)"></script>', src)
    script = "\n".join((WEB.parent / "js" / t).read_text(encoding="utf-8") for t in tags)
    script = script.rsplit("init();", 1)[0]      # would talk to a server that isn't there
    edu = mods[0].edu_path.read_text(encoding="latin-1")
    print(f"  comparing the first two units of {mods[0].name}")
    tmp = Path(tempfile.mkdtemp(prefix="ut_cmp_"))
    js = tmp / "check.js"
    js.write_text("const EDU_TEXT=" + json.dumps(edu) + ";\n" + STUBS + script + HARNESS,
                  encoding="utf-8")
    # node writes UTF-8; Windows would otherwise decode it as cp1252 and every
    # em dash in a check's label would come back as a different string
    proc = subprocess.run([node, str(js)], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        check("the page script runs under node", False)
        print(proc.stderr[-1500:])
    else:
        r = json.loads(proc.stdout.strip().splitlines()[-1])

        print("\n  -- every coloured slot names a real part --")
        bad = [x["id"] for x in r["merit"] + r["order"] if not x["found"]]
        check(f"all {len(r['merit'])} CMP_MERIT and {len(r['order'])} CMP_ORDER slots exist"
              + (f" (missing: {bad})" if bad else ""), not bad)

        print("\n  -- who wins a slot --")
        want = {
            'attack 12 vs 8 — bigger wins': ('a', '4'),
            'attack 8 vs 12 — the other side': ('b', '4'),
            'attack 10 vs 10 — identical': ('=', ''),
            'weapon delay 20 vs 25 — faster wins': ('a', '5'),
            'upkeep 120 vs 300 — cheaper wins': ('a', '180'),
            'recruit turns 1 vs 2 — fewer wins': ('a', '1'),
            'free picks is a setting, not a merit': ('~', ''),
            'skeleton factor has no better side': ('~', ''),
            'training ladder is ordered': ('a', ''),
            'impetuous is different, not better': ('~', ''),
            'a hit sound is just different': ('~', ''),
            'morale 18 vs 19': ('b', '1'),
            'armour 8 vs 7': ('a', '1'),
            'heat fatigue 4 vs 1 — less is better': ('b', '3'),
            'nothing wins a line one of them lacks': ('~', ''),
            'a non-numeric value never wins': ('~', ''),
        }
        for v in r["verdict"]:
            got = ('=' if v["same"] else (v["win"] or '~'), v["gap"])
            exp = want[v["what"]]
            check(v["what"] + ("" if got == exp else f" (got {got}, wanted {exp})"), got == exp)

        print("\n  -- the table over two real units --")
        b = r["build"]
        print(f"  {b['rows']} slots, sections {b['sections']}")
        check("every slot is counted exactly once", b["rows"] == b["tallied"])
        check("type / dictionary are kept out of a stat table", not b["identity"])
        check("no slot is both identical and a win", not b["contradiction"])
        check(f"stat_pri is split into all {b['priParts']} of its values",
              b["priRows"] == b["priParts"])
        check("a unit compared with itself has no differences", b["selfDiff"] == 0)

        print("\n  -- putting one clause onto another row --")
        for c in r["conds"]:
            check(c["what"] + ("" if c["ok"] else f" (got {c['got']!r}, wanted {c['want']!r})"),
                  c["ok"])
    shutil.rmtree(tmp, ignore_errors=True)

print(f"\n{sum(ok)}/{len(ok)} checks passed")
sys.exit(0 if all(ok) else 1)
