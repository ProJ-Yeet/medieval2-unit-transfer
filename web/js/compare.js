/* compare.js — the compare tab — the same unit table twice, side by side

   Part of the Medieval 2 GUI Toolkit UI. These files are plain
   <script> tags sharing ONE global scope, loaded in the order set in
   index.html — there is no build step and no module system. Two rules
   follow from that: a top-level name must be unique across all of
   them, and a file's top-level side effects may not depend on a file
   loaded after it. */
// key|part label -> +1 when bigger is better, -1 when smaller is. A slot that
// is not in here has no better side and is only ever marked "different".
const CMP_MERIT=(()=>{
  const m={},set=(key,pairs)=>Object.keys(pairs).forEach(p=>{m[key+'|'+p]=pairs[p];});
  ['stat_pri','stat_sec','stat_ter'].forEach(k=>set(k,
    {'Attack':1,'Charge bonus':1,'Range':1,'Ammo':1,'Delay':-1}));
  ['stat_pri_ex','stat_sec_ex','stat_ter_ex'].forEach(k=>set(k,
    {'Attack vs mounted':1,'Defence vs mounted':1,'Armour penetration':1}));
  set('stat_pri_armour',{'Armour':1,'Defence skill':1,'Shield':1});
  set('stat_armour_ex',{'Armour 0':1,'Armour 1':1,'Armour 2':1,'Armour 3':1,
    'Defence skill':1,'Shield melee':1,'Shield missile':1});
  set('stat_sec_armour',{'Armour':1,'Defence skill':1});
  set('stat_mental',{'Morale':1});
  set('stat_health',{'Man':1,'Mount / animal':1});
  set('stat_ground',{'Scrub':1,'Sand':1,'Forest':1,'Snow':1});
  set('soldier',{'Men':1});
  set('unit_info',{'Melee attack':1,'Missile attack':1,'Defence':1});
  set('move_speed_mod',{'×':1});
  set('stat_heat',{'Heat':-1});
  set('stat_fire_delay',{'Delay':-1});
  set('stat_stl',{'Men':-1});               // men it may lose before it counts as dead
  set('crusading_upkeep_modifier',{'×':-1});
  set('stat_cost',{'Turns':-1,'Recruit':-1,'Upkeep':-1,'Weapon ug.':-1,'Armour ug.':-1,
    'Custom battle':-1,'Price rise':-1});
  return m;
})();
// The two dropdowns that are really a ladder. `impetuous` is deliberately absent
// from the discipline list: it is a different behaviour, not a better one.
const CMP_ORDER={
  'stat_mental|Training':['untrained','trained','highly_trained'],
  'stat_mental|Discipline':['low','normal','disciplined'],
};
const cmpNum=v=>{const n=parseFloat(String(v==null?'':v).trim());return isFinite(n)?n:null;};
const cmpFmt=n=>String(Math.round(n*1000)/1000);
function cmpVerdict(key,part,va,vb,absent){
  const a=(va==null?'':''+va).trim(),b=(vb==null?'':''+vb).trim();
  if(a===b)return {same:true};
  if(absent)return {diff:true,absent};
  const id=key+'|'+((part&&part.pl)||'');
  const merit=CMP_MERIT[id];
  if(merit){
    const na=cmpNum(a),nb=cmpNum(b);
    if(na!=null&&nb!=null&&na!==nb)
      return {win:((na>nb)===(merit>0))?'a':'b',gap:cmpFmt(Math.abs(na-nb))};
  }
  const order=CMP_ORDER[id];
  if(order){
    const ia=order.indexOf(a.toLowerCase()),ib=order.indexOf(b.toLowerCase());
    if(ia>=0&&ib>=0&&ia!==ib)return {win:ia>ib?'a':'b',gap:''};
  }
  return {diff:true};
}
// The two lines that are the unit's IDENTITY rather than a stat. They differ
// between any two units by definition, so they would head the table with a
// difference nobody came to look at — and `type` in particular is renamed
// through its own machinery on the Identity tab, not by writing the field.
const CMP_SKIP=new Set(['type','dictionary']);
function cmpBuild(A,B,labels){
  const secs={},tally={a:0,b:0,neu:0,same:0};
  labels.forEach(label=>{
    const key=gfKey(label),spec=GF_FIELDS[key];
    if(CMP_SKIP.has(key))return;
    const hasA=A.has(label),hasB=B.has(label);
    if(!hasA&&!hasB)return;
    const absent=!hasA?'a':(!hasB?'b':'');
    const parted=spec&&spec.parts&&spec.parts.length;
    const pa=parted?gfParse(spec,A.val(label)):null;
    const pb=parted?gfParse(spec,B.val(label)):null;
    let rows;
    if(pa&&pb&&pa.ok&&pb.ok){
      rows=spec.parts.map((part,i)=>{
        const va=pa.parts[i]==null?'':pa.parts[i],vb=pb.parts[i]==null?'':pb.parts[i];
        return {label,key,pi:i,part,name:part.pl,va,vb,v:cmpVerdict(key,part,va,vb,absent)};
      });
    }else{
      // a list line (ownership, attributes) or one the parser refused: the whole
      // value is the slot, and it is compared as text
      const va=A.val(label),vb=B.val(label);
      rows=[{label,key,pi:-1,part:null,name:(spec&&spec.t)||label,va,vb,
             v:cmpVerdict(key,null,va,vb,absent)}];
    }
    rows.forEach(r=>{ if(r.v.same)tally.same++; else if(r.v.win)tally[r.v.win]++; else tally.neu++; });
    const sid=GF_SECTION_OF[key]||'other';
    const sec=secs[sid]||(secs[sid]={id:sid,
      t:(GF_SECTIONS.find(s=>s.id===sid)||{}).t||'Other lines',fields:[]});
    sec.fields.push({label,key,title:(spec&&spec.t)||label,rows,absent});
  });
  return {sections:GF_SECTIONS.map(s=>secs[s.id]).filter(Boolean),tally};
}

const cmpSide=w=>w==='b'?state.ed.cmp:state.ed;
function cmpVal(w,label){
  const s=cmpSide(w); if(!s||!s.d)return '';
  if(label in s.ov)return s.ov[label];
  const f=s.d.fields.find(x=>x[0]===label); return f?f[1]:'';
}
function cmpHas(w,label){
  const s=cmpSide(w); if(!s||!s.d)return false;
  return !!s.d.fields.find(x=>x[0]===label)&&!(s.rm&&s.rm.has(label));
}
const cmpEdited=(w,label)=>!!(cmpSide(w)&&(label in (cmpSide(w).ov||{})));
function cmpSet(w,label,val){
  if(w==='a')return edSetField(label,val);
  const c=state.ed.cmp,f=c.d.fields.find(x=>x[0]===label);
  if(!f){ c.d.fields=c.d.fields.concat([[label,'']]); c.added.add(label); }
  if(val===((f||['',''])[1])&&!c.added.has(label))delete c.ov[label]; else c.ov[label]=val;
  c.rm.delete(label); edStale();
}
function cmpPart(w,label,pi){
  const key=gfKey(label),spec=GF_FIELDS[key],raw=cmpVal(w,label);
  if(pi<0||!spec||!spec.parts||!spec.parts.length)return raw;
  const p=gfParse(spec,raw);
  return p.ok?(p.parts[pi]==null?'':p.parts[pi]):raw;
}
// Typing into one box rewrites the whole line it belongs to, exactly as the
// guided editor does — a slot has no existence of its own in the EDU.
function cmpWrite(w,label,pi,val){
  const key=gfKey(label),spec=GF_FIELDS[key];
  if(pi<0||!spec||!spec.parts||!spec.parts.length)return cmpSet(w,label,val);
  const p=gfParse(spec,cmpVal(w,label));
  if(!p.ok)return cmpSet(w,label,val);
  const parts=p.parts.slice(); parts[pi]=val;
  cmpSet(w,label,gfBuild(spec,parts));
}
function cmpLabels(){
  const e=state.ed,out=[],seen=new Set();
  const push=l=>{ if(!seen.has(l)){seen.add(l);out.push(l);} };
  (e.d.fields||[]).forEach(([l])=>push(l));
  (e.cmp&&e.cmp.d?e.cmp.d.fields:[]).forEach(([l])=>push(l));
  return out;
}
const edCmpModel=()=>cmpBuild({val:l=>cmpVal('a',l),has:l=>cmpHas('a',l)},
                              {val:l=>cmpVal('b',l),has:l=>cmpHas('b',l)},cmpLabels());
const edCmpDirty=()=>{
  const c=state.ed&&state.ed.cmp;
  return !!(c&&c.d&&(Object.keys(c.ov).length||c.rm.size));
};

/* ---- picking the other unit ---- */
function edCmpUnits(){
  const e=state.ed;
  if(state.data&&state.data.mod===e.mod)return state.data.units||[];
  if(e.cmpUnitsFor===e.mod)return e.cmpUnits||[];
  if(!e._cmpLoading){
    e._cmpLoading=true;
    api.get('/api/units?mod='+enc(e.mod)).then(d=>{
      e._cmpLoading=false; e.cmpUnits=d.units||[]; e.cmpUnitsFor=e.mod;
      if(state.ed===e&&e.tab==='compare')edRenderTab();
    }).catch(()=>{e._cmpLoading=false;});
  }
  return [];
}
async function edCmpPick(type){
  const e=state.ed;
  e.cmp={unit:type,d:null,ov:{},rm:new Set(),added:new Set(),loading:true};
  edRenderTab();
  let d;
  try{ d=await api.get(`/api/edit/unit?mod=${enc(e.mod)}&type=${enc(type)}`); }
  catch(err){ d={error:''+err}; }
  if(state.ed!==e||!e.cmp||e.cmp.unit!==type)return;   // moved on while loading
  if(d.error){ e.cmp={unit:type,d:null,ov:{},rm:new Set(),added:new Set(),error:d.error};
    edRenderTab(); return; }
  e.cmp={unit:type,d,ov:{},rm:new Set(),added:new Set()};
  e.cmpQ=''; edRenderTab();
}
function edCmpClear(){
  const e=state.ed;
  if(edCmpDirty()&&!confirm(`Discard the unsaved changes to ${e.cmp.unit}?`))return;
  e.cmp=null; edRenderTab();
}
function edCmpSetQ(v){ state.ed.cmpQ=v; }
function edCmpToggleSame(on){ state.ed.cmpSame=on; edRenderTab(); }

function edCmpHead(m){
  const e=state.ed,t=m.tally;
  const nameOf=(mod,type,fallback)=>{
    const u=edCmpUnits().find(x=>x.type===type);
    return (u&&u.name)||fallback||type;
  };
  const side=(w,type,name,extra)=>`<div class="cu ${w}">
      <img onerror="iconRetry(this)" src="${iconUrl(e.mod,type)}" alt="">
      <div style="min-width:0"><div class="nm">${esc(name)}</div>
        <div class="ty">${esc(type)}</div>${extra||''}</div></div>`;
  return `<div class="cmphead">
    ${side('a',e.unit,e.loc.name||e.d.type,
      `<div class="ty"><b class="w">${t.a}</b> better here</div>`)}
    <div class="tally">
      <div><b>${t.a+t.b+t.neu}</b> differ${t.neu?` · ${t.neu} no better side`:''}</div>
      <div class="count">${t.same} identical</div>
      <div style="margin-top:4px"><button onclick="edCmpClear()">⇄ Change</button>
        <button onclick="openUnitTab('${q1(esc(e.cmp.unit))}')"
          title="Open the compared unit in its own editor tab">↗ Open</button></div>
    </div>
    ${side('b',e.cmp.unit,nameOf(e.mod,e.cmp.unit,e.cmp.d.type),
      `<div class="ty"><b class="w">${t.b}</b> better here</div>`)}
  </div>`;
}
function edCmpSection(sec){
  return `<div class="cmpsec"><h5>${esc(sec.t)}</h5>
    <div class="cmplist">${sec.fields.map(edCmpField).join('')}</div></div>`;
}
function edCmpField(f){
  const e=state.ed;
  const missing=f.absent==='a'?`<span class="w-warn"> ${esc(e.unit)} has no such line.</span>`
    :f.absent==='b'?`<span class="w-warn"> ${esc(e.cmp.unit)} has no such line.</span>`:'';
  return `<div class="cmpfield">${esc(f.title)}
      <span class="count">${esc(f.label)}</span>${missing}</div>
    ${f.rows.map(edCmpRow).join('')}`;
}
function edCmpRow(r){
  const v=r.v;
  const cell=w=>`<span class="cv ${w} ${v.same?'':v.win?(v.win===w?'win':'lose'):'diff'} ${
      cmpEdited(w,r.label)?'edited':''}">${cmpWidget(w,r)}</span>`;
  return `<div class="cmprow ${v.same?'same':''}">
    <span class="cl" title="${esc(r.name)}">${esc(r.name)}</span>
    ${cell('a')}
    <span class="cd ${v.same?'':v.win?'win':'neu'}">${cmpDelta(v)}</span>
    ${cell('b')}</div>`;
}
// ◀ points at the unit that wins the slot, with the size of the gap. A slot with
// no better side just says the two are not equal.
function cmpDelta(v){
  if(v.same)return '=';
  if(v.win==='a')return `◀ ${esc(v.gap||'')}`;
  if(v.win==='b')return `${esc(v.gap||'')} ▶`;
  return v.absent?'·':'≠';
}
let _cmpLists=null;
function cmpVocabList(name){
  const v=gfVocabFor(state.ed.mod)[name];
  return Array.isArray(v)?v:[];
}
function cmpDatalists(){
  const out=[...(_cmpLists||[])].map(n=>`<datalist id="cmpdl-${esc(n)}">${
    cmpVocabList(n).map(x=>`<option value="${esc(x)}">`).join('')}</datalist>`).join('');
  _cmpLists=null;
  return out;
}
function cmpWidget(w,r){
  const val=cmpPart(w,r.label,r.pi);
  const p=r.part,at=`data-cmp="${w}" data-cl="${esc(r.label)}" data-ci="${r.pi}"`;
  if(p&&p.type==='sel'){
    const list=cmpVocabList(p.v);
    if(list.length)return `<select ${at}>${p.optional?'<option value=""></option>':''}${
      list.map(x=>`<option value="${esc(x)}" ${x===val?'selected':''}>${esc(x)}</option>`).join('')}${
      val&&!list.includes(val)?`<option value="${esc(val)}" selected>${esc(val)}</option>`:''}</select>`;
  }
  if(p&&p.type==='combo'&&p.v&&cmpVocabList(p.v).length){
    (_cmpLists=_cmpLists||new Set()).add(p.v);
    return `<input ${at} list="cmpdl-${esc(p.v)}" value="${esc(val)}">`;
  }
  return `<input ${at} value="${esc(val)}"${
    p&&p.type==='num'?' inputmode="decimal"':''}>`;
}
function edCmpPicker(){
  const e=state.ed;
  const q=(e.cmpQ||'').trim().toLowerCase();
  const units=edCmpUnits().filter(u=>u.type!==e.unit
    &&(!q||u.name.toLowerCase().includes(q)||u.type.toLowerCase().includes(q))).slice(0,300);
  return `<div class="frm">
    <fieldset><legend>Compare with another unit</legend>
      <div class="count">Pick a unit from <b>${esc(e.mod)}</b>. Its stats are shown beside
        ${esc(e.loc.name||e.d.type)}’s, slot by slot, with the better side in green and the
        worse in red. Both columns stay editable, so a gap can be closed from either
        end. <b>Save changes</b> then writes both units.</div>
      <input class="q" id="cmpQ" style="margin-top:8px;width:100%"
        placeholder="Filter ${esc(e.mod)}’s units…" value="${esc(e.cmpQ||'')}">
      <div class="baselist" style="max-height:340px;margin-top:6px">${units.map(u=>`
        <div class="baserow" onclick="edCmpPick('${q1(esc(u.type))}')">
          <img loading="lazy" onerror="iconRetry(this)" src="${iconUrl(e.mod,u.type)}">
          <div><div class="bn">${esc(u.name)}</div>
            <div class="bs">${esc(u.type)} · ${esc(u.kind||u.category||'')}</div></div>
        </div>`).join('')||`<div class="caprow"><span class="count">${
          edCmpUnits().length?'No units match.':'Loading this mod’s units…'}</span></div>`}</div>
    </fieldset></div>`;
}
function cmpRepaint(el){
  const row=el.closest('.cmprow'); if(!row)return;
  const label=el.dataset.cl,pi=+el.dataset.ci;
  const key=gfKey(label),spec=GF_FIELDS[key];
  const part=(pi>=0&&spec&&spec.parts)?spec.parts[pi]:null;
  const absent=!cmpHas('a',label)?'a':(!cmpHas('b',label)?'b':'');
  const v=cmpVerdict(key,part,cmpPart('a',label,pi),cmpPart('b',label,pi),absent);
  row.className='cmprow'+(v.same?' same':'');
  ['a','b'].forEach(w=>{
    const cell=row.querySelector('.cv.'+w); if(!cell)return;
    cell.className='cv '+w+' '+(v.same?'':v.win?(v.win===w?'win':'lose'):'diff')
      +(cmpEdited(w,label)?' edited':'');
  });
  const cd=row.querySelector('.cd');
  if(cd){ cd.className='cd '+(v.same?'':v.win?'win':'neu'); cd.innerHTML=cmpDelta(v); }
  const head=document.querySelector('#edBody .cmphead');
  if(head)head.outerHTML=edCmpHead(edCmpModel());
  paintDirty();
}

// The compared unit is a second, ordinary unit edit — same endpoint, its own
// request. Nothing but the field overrides can be changed from the Compare tab,
// so the rest of the payload is the neutral form.
function edCmpPayload(extra){
  const e=state.ed,c=e.cmp;
  return Object.assign({mod:e.mod,unit:c.unit,new_type:'',new_dictionary:'',
    field_overrides:c.ov,remove_fields:[...c.rm],loc:null,
    model_edits:[],new_models:[],card_src:'',info_src:'',
    remove_old_icons:false},extra||{});
}
