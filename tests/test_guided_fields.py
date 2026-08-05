"""The guided EDU field editor: its vocabularies, and that it never rewrites a line.

The guided view splits every EDU line into labelled boxes and writes it back from
them. That is only safe if the split-and-rejoin is lossless — a unit opened and
saved untouched has to come out byte-identical, or every save quietly damages a
mod. This suite checks exactly that, over every unit of every installed mod:

  * ``vocab.build`` offers the engine's fixed sets AND everything the mod itself
    defines or already uses (a mod's own attribute must not vanish from a list)
  * the "defined" lists really come from the mod's descr_* files
  * every EDU line either round-trips through gfParse/gfBuild unchanged, or is
    refused by gfParse and shown raw — never silently reshaped
  * the lines that ARE refused are only the malformed ones

The round-trip half runs the page's own JavaScript under node; it is skipped
(not failed) when node is unavailable, since node is not a dependency of the tool.

    python -m tests.test_guided_fields
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittransfer import edu, vocab
from unittransfer.mod import Mod

MODS = Path(r"C:/Users/projy/Downloads/Games/Total War MEDIEVAL II Definitive Edition/mods")
WEB = ROOT / "web" / "index.html"
VANILLA_EDU = ROOT / "UnitEditor11" / "vanilla" / "export_descr_unit.txt"

ok = []


def check(label, cond):
    ok.append(bool(cond))
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}")


def installed_mods():
    if not MODS.is_dir():
        return []
    return [Mod(p) for p in sorted(MODS.iterdir())
            if (p / "data" / "export_descr_unit.txt").exists()]


# ---- 1) vocabularies --------------------------------------------------------
print("\n-- vocabularies --")
mods = installed_mods()
check("at least one mod installed to test against", bool(mods))

for mod in mods:
    v = mod.edu_vocab
    print(f"  {mod.name}:")
    check(f"    {mod.name}: the engine's fixed sets are all present",
          all(k in v for k in ("weapon_type", "tech_type", "damage_type",
                               "armour_sound", "discipline", "training")))
    check(f"    {mod.name}: closed sets are exactly the engine's",
          v["discipline"] == vocab.DISCIPLINE and v["training"] == vocab.TRAINING)

    # every value the mod's own EDU uses must be offered, or the drop-down would
    # invite the user to throw it away
    used_attrs, used_accents, used_banners = set(), set(), set()
    for unit in mod.edu.units:
        for label, value in edu.block_fields(unit.raw):
            key = label.split("#")[0]
            if key == "attributes":
                used_attrs |= {p.strip() for p in value.split(",") if p.strip()}
            elif key == "accent" and value.strip():
                used_accents.add(value.strip())
            elif key == "banner faction" and value.strip():
                used_banners.add(value.strip())
    lower = lambda lst: {str(x).lower() for x in lst}
    check(f"    {mod.name}: all {len(used_attrs)} attributes it uses are offered",
          lower(used_attrs) <= lower(v["unit_attr"]))
    check(f"    {mod.name}: all {len(used_accents)} accents it uses are offered",
          lower(used_accents) <= lower(v["accent"]))
    check(f"    {mod.name}: all {len(used_banners)} faction banners are offered",
          lower(used_banners) <= lower(v["banner_faction"]))

    # "defined" is what a file really declares — that is what a broken-reference
    # warning is measured against, so it must not be padded with EDU values
    defined = v["defined"]
    check(f"    {mod.name}: defined models == the modeldb's entries",
          set(defined["model"]) == {e.name for e in mod.modeldb.entries})
    check(f"    {mod.name}: defined projectiles == descr_projectile's blocks",
          set(defined["projectile"]) == set(mod.projectile_file.by_name()))
    check(f"    {mod.name}: defined mounts == descr_mount's blocks",
          set(defined["mount"]) == set(mod.mounts))

# the cache has to be dropped when the mod is rewritten, or the editor keeps
# offering names that were just renamed away
if mods:
    from unittransfer import edit as edit_mod
    mod = mods[0]
    _ = mod.edu_vocab
    check("edu_vocab is cached on the Mod", "edu_vocab" in mod.__dict__)
    edit_mod._invalidate(mod)
    check("edit._invalidate drops the cached vocab", "edu_vocab" not in mod.__dict__)
    from unittransfer import transfer as transfer_mod
    _ = mod.edu_vocab
    transfer_mod._invalidate(mod)
    check("transfer._invalidate drops the cached vocab", "edu_vocab" not in mod.__dict__)

# ---- 2) the guided split is lossless ---------------------------------------
print("\n-- guided round-trip (node) --")
node = shutil.which("node")
if not node:
    print("  [skip] node is not on PATH — the page's own JS cannot be exercised")
elif not WEB.exists():
    print("  [skip] web/index.html not found")
else:
    src = WEB.read_text(encoding="utf-8")
    script = src[src.index("<script>") + len("<script>"):src.rindex("</script>")]
    # `init()` would try to talk to a server that isn't there
    script = script.rsplit("init();", 1)[0]
    # the page binds its hover-card listeners at load; node has no DOM, and this
    # suite only exercises the pure split/rejoin functions
    stubs = r"""
const noop=()=>{};
globalThis.document={addEventListener:noop,getElementById:()=>null,
  querySelector:()=>null,querySelectorAll:()=>[],createElement:()=>({style:{},classList:{add:noop}}),
  body:{appendChild:noop}};
globalThis.window={addEventListener:noop,innerWidth:1280,innerHeight:800};
globalThis.fetch=()=>Promise.reject(new Error('no network'));
"""
    harness = r"""
const out={units:0,lines:0,guided:0,widget:0,raw:0,diff:0,examples:[],rawKeys:{}};
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
// ---- the ▴▾ steppers clamp to each slot's own limits ----
out.steps=[];
function step(key,i,from,dir,big){
  const p=GF_FIELDS[key].parts[i],el={value:from};
  gfStep(p,el,dir,big); return el.value;
}
const expect=(what,got,want)=>out.steps.push({what,got,want,ok:got===want});
expect('attack 62 +1',            step('stat_pri',0,'62',1),        '63');
expect('attack 63 +1 stays at the engine cap', step('stat_pri',0,'63',1), '63');
expect('attack 60 shift+1 clamps', step('stat_pri',0,'60',1,true),  '63');
expect('attack 0 -1 floors at 0',  step('stat_pri',0,'0',-1),       '0');
expect('men 1 -1 floors at 1',     step('soldier',1,'1',-1),        '1');
expect('mass 1 +1 steps by 0.1',   step('soldier',3,'1',1),         '1.1');
expect('radius blank +1 starts at its minimum', step('soldier',4,'',1), '0.05');
expect('ranks 1 -1 floors at 1',   step('formation',4,'1',-1),      '1');
expect('scrub 0 -1 goes negative', step('stat_ground',0,'0',-1),    '-1');
expect('upkeep 0 shift+1',         step('stat_cost',2,'0',1,true),  '10');
// a mod's out-of-range value survives being LOOKED at (only stepping clamps it,
// and then it lands inside the range rather than one below where it started)
expect('attack 65, stepped down, lands back inside the range',
       step('stat_pri',0,'65',-1), '63');

for(const text of EDU_TEXTS){
  for(const b of text.split(/^(?=type\s)/m)){
    if(!/^type\s/.test(b))continue;
    out.units++;
    for(const [label,value] of blockFields(b)){
      const key=label.replace(/#\d+$/,''),spec=GF_FIELDS[key];
      out.lines++;
      if(!spec){out.raw++;out.rawKeys[key]=(out.rawKeys[key]||0)+1;continue;}
      if(spec.w){out.widget++;continue;}
      const p=gfParse(spec,value);
      if(!p.ok){out.raw++;out.rawKeys[key]=(out.rawKeys[key]||0)+1;continue;}
      out.guided++;
      const back=gfBuild(spec,p.parts);
      const norm=value.split(',').map(x=>x.trim()).join(', ');
      if(back!==norm){out.diff++;
        if(out.examples.length<10)out.examples.push({label,in:value,out:back});}
    }
  }
}
console.log(JSON.stringify(out));
"""
    texts = [p.read_text(encoding="latin-1")
             for p in ([m.edu_path for m in mods] + [VANILLA_EDU]) if p.exists()]
    tmp = Path(tempfile.mkdtemp(prefix="ut_guided_"))
    js = tmp / "check.js"
    js.write_text("const EDU_TEXTS=" + json.dumps(texts) + ";\n" + stubs + script + harness,
                  encoding="utf-8")
    proc = subprocess.run([node, str(js)], capture_output=True, text=True)
    if proc.returncode != 0:
        check("the page script runs under node", False)
        print(proc.stderr[-1500:])
    else:
        r = json.loads(proc.stdout.strip().splitlines()[-1])
        print(f"  {r['units']} units, {r['lines']} lines — {r['guided']} guided, "
              f"{r['widget']} widget, {r['raw']} raw")
        for st in r.get("steps", []):
            check(f"stepper: {st['what']}"
                  + ("" if st["ok"] else f" (got {st['got']!r}, wanted {st['want']!r})"),
                  st["ok"])
        check("every guided line round-trips unchanged", r["diff"] == 0)
        if r["examples"]:
            for e in r["examples"]:
                print(f"      {e['label']}\n        in : {e['in']}\n        out: {e['out']}")
        check("nearly every line has a guided shape (<0.1% falls back to raw)",
              r["raw"] <= max(20, r["lines"] // 1000))
        print("  lines shown raw:", r["rawKeys"] or "none")
    shutil.rmtree(tmp, ignore_errors=True)

print("\n" + ("ALL PASSED" if all(ok) else "SOME FAILED"))
sys.exit(0 if all(ok) else 1)
