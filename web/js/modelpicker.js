/* modelpicker.js — the soldier-model picker (it also picks the animation set)

   Part of the Medieval 2 GUI Toolkit UI. These files are plain
   <script> tags sharing ONE global scope, loaded in the order set in
   index.html — there is no build step and no module system. Two rules
   follow from that: a top-level name must be unique across all of
   them, and a file's top-level side effects may not depend on a file
   loaded after it. */
/* =========================================================================
   The soldier-model picker

   Swapping the model on a `soldier` line swaps the unit's animation set with it,
   because the skeleton lives on the modeldb entry. So the question is almost
   never "what is this entry called" — it is "which entries move the way I want",
   and a datalist of two thousand names cannot answer that. Three ways in:

     by skeleton  pick an animation set, get every entry that uses it
     by name      the plain search, with LOD/skin counts and how many units share it
     from a unit  take another unit's whole soldier line — men, mass and all

   Opens over the field editor and puts it straight back, the same stash/restore
   the building picker uses.
   ========================================================================= */
let mpBack=null;
async function mpOpen(label,part){
  const host=gfHost(); if(!host)return;
  const modal=document.getElementById('modal');
  mpBack={html:modal.innerHTML,cls:modal.className,label,part,scroll:stashPlace()};
  modal.innerHTML=`<h2>Pick a battle-model entry</h2>
    <div class="mbody"><div class="empty">Reading the modeldb…</div></div>
    <div class="foot"><button onclick="mpCancel()">Cancel</button></div>`;
  const mod=(state.ed&&state.ed.mod)||state.src;
  if(!state.mp||state.mp.mod!==mod){
    let r;
    try{ r=await api.get('/api/bmdb/skeletons?mod='+enc(mod)); }
    catch(e){ r={error:''+e}; }
    if(r.error){ modal.querySelector('.mbody').innerHTML=`<div class="w-bad">${esc(r.error)}</div>`; return; }
    state.mp={mod,skeletons:r.skeletons,entries:r.entries};
  }
  const cur=(gfParse(GF_FIELDS[gfKey(label)],host.get(label)).parts[part]||'').trim();
  state.mp.tab='skel'; state.mp.q=''; state.mp.skel=''; state.mp.uq='';
  state.mp.cur=cur;
  // open on the skeleton the current entry already uses — "something else that
  // moves like this" is the commonest reason to be here at all
  const now=state.mp.entries.find(e=>e.name.toLowerCase()===cur.toLowerCase());
  if(now&&now.skeletons.length)state.mp.skel=now.skeletons[0];
  else state.mp.tab='name';
  mpRender();
}
function mpCancel(){
  if(!mpBack)return closeModal();
  const modal=document.getElementById('modal');
  modal.className=mpBack.cls; modal.innerHTML=mpBack.html;
  usePlace(mpBack.scroll);
  mpBack=null;
  // restored markup is inert until its handlers are bound again, and the host's
  // own re-render is what knows how to do that for either dialog
  const host=gfHost();
  if(host&&host.rerender)host.rerender();
}
function mpSet(k,v){ state.mp[k]=v; mpRender(); }
function mpShown(){
  const s=state.mp,q=(s.q||'').trim().toLowerCase();
  return s.entries.filter(e=>
    (s.tab!=='skel'||!s.skel||e.skeletons.includes(s.skel))
    &&(!q||e.name.includes(q)||e.skeletons.some(k=>k.includes(q))));
}
function mpRender(){
  const s=state.mp;
  const tab=(k,t)=>`<button class="${s.tab===k?'on':''}" onclick="mpSet('tab','${k}')">${t}</button>`;
  const rows=s.tab==='unit'?[]:mpShown().slice(0,400);
  document.getElementById('modal').innerHTML=`<h2>Pick a battle-model entry
      ${s.cur?`<span class="pill">now: ${esc(s.cur)}</span>`:''}</h2>
    <div class="mbody">
      <div class="mptabs">${tab('skel','By skeleton')}${tab('name','By name')}
        ${tab('unit','From another unit')}</div>
      ${s.tab==='unit'?mpUnitBody():`
        <div class="basebar">
          ${s.tab==='skel'?`<select onchange="mpSet('skel',this.value)" style="max-width:280px">
            <option value="">Every skeleton</option>
            ${s.skeletons.map(k=>`<option value="${esc(k.name)}" ${k.name===s.skel?'selected':''}
              >${esc(k.name)}: ${k.entries} entr${k.entries===1?'y':'ies'}</option>`).join('')}
          </select>`:''}
          <input id="mpQ" placeholder="${s.tab==='skel'?'Narrow these…':'Search entries and skeletons…'}"
            value="${esc(s.q||'')}" oninput="mpSet('q',this.value)" style="flex:1">
          <span class="count">${mpShown().length} entr${mpShown().length===1?'y':'ies'}</span>
        </div>
        <div class="mplist" id="mpList">${rows.length?rows.map(e=>`
          <div class="mprow ${e.name===s.cur?'on':''}" onclick="mpPick('${q1(esc(e.name))}')">
            <span class="mn">${esc(e.name)}</span>
            <span class="msk">${esc(e.skeletons.join(' + ')||'no skeleton')}</span>
            <span class="count">${e.lods} LOD · ${e.skins} skin</span>
            <span class="mu">${e.used_by?`${e.used_by} user${e.used_by===1?'':'s'}`
              :'<span class="w-warn">unused</span>'}</span>
          </div>`).join(''):'<div class="caprow"><span class="count">Nothing matches.</span></div>'}</div>
        ${mpShown().length>400?`<div class="bnote">Showing the first 400. Narrow it down.</div>`:''}
        <div class="bnote">The skeleton is what decides how the man moves. An entry with a
          different one will animate differently even if the meshes look the same.</div>`}
    </div>
    <div class="foot"><button onclick="mpCancel()">Cancel</button></div>`;
}
function mpUnitBody(){
  const s=state.mp,q=(s.uq||'').trim().toLowerCase();
  const units=((state.data&&state.data.units)||[])
    .filter(u=>u.type!==(state.ed&&state.ed.unit)
      &&(!q||u.name.toLowerCase().includes(q)||u.type.toLowerCase().includes(q)))
    .slice(0,300);
  return `<div class="basebar"><input id="mpUQ" placeholder="Filter units…" value="${esc(s.uq||'')}"
      oninput="mpSet('uq',this.value)" style="flex:1"></div>
    <div class="baselist" style="max-height:300px">${units.map(u=>`
      <div class="baserow" onclick="mpTakeUnit('${q1(esc(u.type))}')">
        <img loading="lazy" onerror="iconRetry(this)" src="${iconUrl(state.ed?state.ed.mod:state.src,u.type)}">
        <div><div class="bn">${esc(u.name)}</div>
          <div class="bs">${esc(u.type)}${u.soldier_model?` · <code>${esc(u.soldier_model)}</code>`:''}</div></div>
      </div>`).join('')||'<div class="caprow"><span class="count">No units match.</span></div>'}</div>
    <div class="bnote">Takes that unit's whole <code>soldier</code> line (model, men, extras and mass)
      not just the entry name. The men count is usually what you want to check afterwards.</div>`;
}
// Write one part back through the same path the boxes use, then reopen the form.
function mpPick(name){
  const b=mpBack; if(!b)return;
  const host=gfHost(); if(!host)return mpCancel();
  const spec=GF_FIELDS[gfKey(b.label)];
  const p=gfParse(spec,host.get(b.label));
  if(p.ok){ p.parts[b.part]=name; host.set(b.label,gfBuild(spec,p.parts)); host.stale(); }
  mpCancel();
  toast(`Model set to ${name}.`);
}
async function mpTakeUnit(type){
  const b=mpBack; if(!b)return;
  const mod=(state.ed&&state.ed.mod)||state.src;
  let d;
  try{ d=await api.get(`/api/edit/unit?mod=${enc(mod)}&type=${enc(type)}`); }
  catch(e){ return toast('Could not read '+type+': '+e); }
  if(d.error)return toast(d.error);
  // fields come back as [label, value] pairs, in file order
  const line=(d.fields||[]).find(f=>f[0]===gfKey(b.label));
  if(!line||!line[1])return toast(`${type} has no ${gfKey(b.label)} line.`);
  const host=gfHost(); if(!host)return mpCancel();
  host.set(b.label,line[1]); host.stale();
  mpCancel();
  toast(`${gfKey(b.label)} line copied from ${type}: ${line[1]}`,4600);
}

/* ---- the widgets a plain box cannot do ---- */
function gfWidget(host,label,spec,cur){
  if(spec.w==='attrs')return gfAttrWidget(host,label,cur);
  if(spec.w==='wattr')return gfWeaponAttrWidget(host,label,cur);
  if(spec.w==='factions')return gfFactionWidget(host,label,cur);
  if(spec.w==='meffect')return gfMountEffectWidget(host,label,cur);
  if(spec.w==='ugmodels')return host.richArmour?`<div class="gfrow">${edArmourField(label,cur)}</div>`
    :gfListWidget(host,label,cur,'model');
  if(spec.w==='uglevels')return host.richArmour
    ?`<div class="gfrow"><div class="gfpart grow"><span class="pl">smith level per tier</span>
        <input data-gfraw="${esc(label)}" value="${esc(cur)}" spellcheck="false"></div></div>`
    :gfListWidget(host,label,cur,'');
  return '';
}
// A generic reorderable list of names (armour tiers in the composer).
function gfListWidget(host,label,cur,vocabName){
  const items=csv(cur);
  return `<div class="gfrow"><div style="flex:1;min-width:0">
    ${gfChips(host,label,items)}
    <div class="barrow">
      <input id="${gfAddId(label)}" placeholder="add…" style="width:190px;font-size:12px;padding:3px 7px"
        ${vocabName?`list="gfdl-${esc(vocabName)}"`:''}>
      <button onclick="gfListAdd('${q1(esc(label))}')">Add</button>
    </div></div></div>`;
}
function gfListAdd(label){
  const el=document.getElementById(gfAddId(label));
  const host=gfHost(); const v=(el&&el.value||'').trim(); if(!v)return;
  const list=csv(host.get(label)); list.push(v);
  host.set(label,list.join(', ')); host.stale(); gfRerenderBody();
}
/* What a list field said before you touched it. A plain "the field changed"
   flag is no use on a list of forty factions — you want to see WHICH ones are
   yours — so every list widget marks its own entries against this. Membership
   only: reordering `ownership` is a change to the field, not to any one entry. */
function gfListWas(host,label){
  return new Set(csv((host.orig?host.orig(label):'')||''));
}
// Drag-to-reorder chips, host-agnostic (the editor's own edChips is bound to
// state.ed, and the composer has no such state).
function gfChips(host,label,items){
  const was=gfListWas(host,label);
  const gone=[...was].filter(v=>items.indexOf(v)<0);
  return `<div class="chips">${items.map((v,i)=>`<span class="chipd${
      was.has(v)?'':' added'}" draggable="true"
      ondragstart="gfDragStart(event,'${q1(esc(label))}',${i})"
      ondragover="gfDragOver(event,'${q1(esc(label))}')" ondragleave="edDragLeave(event)"
      ondragend="edDragEnd(event)" ondrop="gfDrop(event,'${q1(esc(label))}',${i})"
      title="${was.has(v)?'drag to reorder':'Added by you · drag to reorder'}">
      <span class="g">⠿</span><span class="${i===0?'first':''}">${esc(v)}</span>
      <button class="x" title="Remove ${esc(v)}"
        onclick="gfListRemove('${q1(esc(label))}',${i})">✕</button></span>`).join('')
    ||'<span class="count">Empty</span>'}
    ${gone.map(v=>`<span class="chipd gone" title="Removed by you. Click to put it back."
      onclick="gfListRestore('${q1(esc(label))}','${q1(esc(v))}')">${esc(v)}</span>`).join('')}</div>`;
}
function gfListRestore(label,v){
  const host=gfHost(),list=csv(host.get(label));
  if(list.indexOf(v)<0)list.push(v);
  host.set(label,list.join(', ')); host.stale(); gfRerenderBody();
}
let gfDrag=null;
function gfDragStart(ev,label,i){gfDrag={label,i};ev.dataTransfer.effectAllowed='move';
  try{ev.dataTransfer.setData('text/plain',String(i));}catch(_){}
  ev.currentTarget.classList.add('drag');}
function gfDragOver(ev,label){if(!gfDrag||gfDrag.label!==label)return;
  ev.preventDefault();ev.currentTarget.classList.add('over');}
function gfDrop(ev,label,i){
  if(!gfDrag||gfDrag.label!==label)return; ev.preventDefault();
  const host=gfHost(),list=csv(host.get(label)),from=gfDrag.i; gfDrag=null;
  if(from===i){gfRerenderBody();return;}
  const [m]=list.splice(from,1); list.splice(i,0,m);
  host.set(label,list.join(', ')); host.stale(); gfRerenderBody();
}
function gfListRemove(label,i){
  const host=gfHost(),list=csv(host.get(label)); list.splice(i,1);
  host.set(label,list.join(', ')); host.stale(); gfRerenderBody();
}

/* attributes: tick boxes grouped into what the unit can DO and what the AI is
   told it is, plus a free box for a mod's own attribute. */
function gfAttrWidget(host,label,cur){
  const have=csv(cur),haveSet=new Set(have);
  const all=gfV(host,'unit_attr');
  const AI=['peasant','pike','crossbow','gunmen','guncavalry','artillery','cannon','rocket','mortar',
    'explode','incendiary','standard','foot_archers','horse_archers','foot_javelinmen','horse_javelinmen',
    'foot_slingers','foot_pila','foot_darts','foot_francisca','wagon_fort'];
  const isAI=a=>AI.indexOf(a)>=0;
  const known=new Set(all);
  const wasSet=gfListWas(host,label);
  const box=(a)=>facCheckRow(a,'',
    `gfListToggle('${q1(esc(label))}','${q1(esc(a))}',this.checked)`,
    haveSet.has(a),'',haveSet.has(a)!==wasSet.has(a));
  const abilities=all.filter(a=>!isAI(a)),hints=all.filter(isAI);
  const unknown=have.filter(a=>!known.has(a));
  return `<div class="gfrow"><div style="flex:1;min-width:0">
    ${gfChips(host,label,have)}
    <div class="barrow">
      <details class="drop"><summary>▾ Abilities: ${have.filter(a=>!isAI(a)).length} on</summary>
        <div class="dropbody"><div class="faclist" style="border:none;padding:0;max-height:none">
          ${abilities.map(box).join('')}</div></div></details>
      <details class="drop"><summary>▾ AI hints: ${have.filter(isAI).length} on</summary>
        <div class="dropbody"><div class="count" style="margin-bottom:6px">These change nothing about the
          unit itself; they tell the campaign AI what kind of unit it is looking at.</div>
          <div class="faclist" style="border:none;padding:0;max-height:none">${hints.map(box).join('')}</div>
        </div></details>
      <input id="${gfAddId(label)}" list="gfdl-unit_attr" placeholder="add your own…"
        style="width:170px;font-size:12px;padding:3px 7px">
      <button onclick="gfListAdd('${q1(esc(label))}')">Add</button>
    </div>
    ${unknown.length?`<div class="gfnote">Not in this mod’s usual set:
      <b>${unknown.map(esc).join(', ')}</b>, kept as typed.</div>`:''}
  </div></div>`;
}
// stat_pri_attr / stat_sec_attr / stat_ter_attr: same idea, but "empty" is the
// word `no`, and the spear bonuses are mutually exclusive.
function gfWeaponAttrWidget(host,label,cur){
  const have=csv(cur).filter(a=>a.toLowerCase()!=='no');
  const all=gfV(host,'weapon_attr');
  const haveSet=new Set(have);
  const wasSet=gfListWas(host,label);
  return `<div class="gfrow"><div style="flex:1;min-width:0">
    ${gfChips(host,label,have.length?have:[])}
    <div class="barrow">
      <details class="drop"><summary>▾ Choose attributes: ${have.length} on</summary>
        <div class="dropbody"><div class="faclist" style="border:none;padding:0;max-height:none">
          ${all.map(a=>facCheckRow(a,'',
            `gfWAttrToggle('${q1(esc(label))}','${q1(esc(a))}',this.checked)`,
            haveSet.has(a),'',haveSet.has(a)!==wasSet.has(a))).join('')}
        </div></div></details>
      <input id="${gfAddId(label)}" list="gfdl-weapon_attr" placeholder="add your own…"
        style="width:170px;font-size:12px;padding:3px 7px">
      <button onclick="gfListAdd('${q1(esc(label))}')">Add</button>
    </div>
    ${have.length?'':'<div class="gfnote">None, so the line is written as <code>no</code>.</div>'}
  </div></div>`;
}
function gfWAttrToggle(label,attr,on){
  const host=gfHost(),list=csv(host.get(label)).filter(a=>a.toLowerCase()!=='no');
  const i=list.indexOf(attr);
  // only one spear bonus can apply, so picking one drops the other
  if(on&&/^spear_bonus_/.test(attr))
    for(let j=list.length-1;j>=0;j--)if(/^spear_bonus_/.test(list[j]))list.splice(j,1);
  const at=list.indexOf(attr);
  if(on&&at<0)list.push(attr); else if(!on&&at>=0)list.splice(at,1);
  host.set(label,list.length?list.join(', '):'no'); host.stale(); gfRerenderBody();
}
function gfListToggle(label,v,on){
  const host=gfHost(),list=csv(host.get(label)),i=list.indexOf(v);
  if(on&&i<0)list.push(v); else if(!on&&i>=0)list.splice(i,1);
  host.set(label,list.join(', ')); host.stale(); gfRerenderBody();
}
// A host's facLabel runs both names together ("Mordor (england)"); a checklist
// wants them apart, so pull the display name back out of it.
function gfFacName(host,code){
  const both=host.facLabel(code);
  if(both===code)return '';
  const m=/^(.*)\s\((.*)\)$/.exec(both);
  if(!m)return both;
  return m[1]===code?m[2]:m[1];
}
/* ownership / era N: the editor already has a faction checklist bound to its own
   state; the composer gets the same shape driven by the host. */
function gfFactionWidget(host,label,cur){
  if(host.richArmour)return `<div class="gfrow">${edFactionField(label,cur)}</div>`;
  const list=csv(cur),chosen=new Set(list),all=host.factions();
  const isEra=label!=='ownership';
  const own=csv(host.get('ownership')||'');
  const wasSet=gfListWas(host,label);
  return `<div class="gfrow"><div style="flex:1;min-width:0">
    ${gfChips(host,label,list)}
    <div class="barrow">
      <details class="drop"><summary>▾ Choose factions: ${list.length} selected</summary>
        <div class="dropbody"><div class="faclist" style="border:none;padding:0;max-height:none">
          ${all.map(f=>facCheckRow(f,gfFacName(host,f),
              `gfListToggle('${q1(esc(label))}','${q1(esc(f))}',this.checked)`,
              chosen.has(f),'',chosen.has(f)!==wasSet.has(f))).join('')}
        </div></div></details>
      ${isEra&&own.length?`<button onclick="gfSetList('${q1(esc(label))}',${
        JSON.stringify(own).replace(/"/g,'&quot;')})" title="Replace this era with the ownership line"
        >Copy ownership (${own.length})</button>`:''}
      <button onclick="gfSetList('${q1(esc(label))}',[])">Clear</button>
    </div></div></div>`;
}
function gfSetList(label,items){const host=gfHost();
  host.set(label,items.join(', ')); host.stale(); gfRerenderBody();}

/* mount_effect: up to three "<mount> <±n>" pairs. The mount name may contain
   spaces ("mailed horse +2"), so the number is split off the end, not the start. */
function gfMountEffectWidget(host,label,cur){
  const pairs=csv(cur).map(s=>{const m=/^(.*?)\s*([+-]?\d+(?:\.\d+)?)$/.exec(s.trim());
    return m?{n:m[1].trim(),v:m[2]}:{n:s.trim(),v:''};});
  const rows=pairs.map((p,i)=>`<div class="gfoff">
      <span class="idx">${i+1}</span>
      <input data-gfme="${esc(label)}" data-i="${i}" data-part="n" list="gfdl-mount_class"
        value="${esc(p.n)}" style="width:180px;font-size:12.5px;padding:4px 7px">
      ${gfSpin(`data-gfme="${esc(label)}" data-i="${i}" data-part="v" aria-label="modifier"`,p.v)}
      <button class="rm" title="Remove" onclick="gfMeRemove('${q1(esc(label))}',${i})"
        style="background:none;border:1px solid transparent;color:var(--dim);padding:2px 6px">✕</button>
    </div>`).join('');
  return `<div class="gfgrid" style="flex-direction:column;align-items:flex-start">${rows}
    <div class="barrow">
      <button ${pairs.length>=3?'disabled title="The engine reads at most three"':''}
        onclick="gfMeAdd('${q1(esc(label))}')">＋ Add a mount effect</button>
      <span class="count">${pairs.length}/3 · a class (horse, camel, elephant) or one specific mount</span>
    </div></div>`;
}
function gfMeParts(host,label){
  return csv(host.get(label)).map(s=>{const m=/^(.*?)\s*([+-]?\d+(?:\.\d+)?)$/.exec(s.trim());
    return m?{n:m[1].trim(),v:m[2]}:{n:s.trim(),v:''};});
}
function gfMeWrite(host,label,pairs){
  host.set(label,pairs.filter(p=>p.n).map(p=>{
    const v=(p.v||'').trim(); const s=(/^[+-]/.test(v)||!v)?v:'+'+v;
    return (p.n+' '+s).trim();}).join(', '));
  host.stale();
}
function gfMeAdd(label){const host=gfHost();const p=gfMeParts(host,label);
  p.push({n:'horse',v:'+1'}); gfMeWrite(host,label,p); gfRerenderBody();}
function gfMeRemove(label,i){const host=gfHost();const p=gfMeParts(host,label);
  p.splice(i,1); gfMeWrite(host,label,p); gfRerenderBody();}

/* ---- adding a line the unit doesn't have ---- */
function gfAddHtml(host){
  const missing=host.missing();
  const gf=gfState(host);
  const offCount=host.fields().filter(([l])=>gfKey(l)==='officer').length;
  const sec=GF_SECTIONS.find(s=>s.id===gf.tab);
  const here=missing.filter(k=>sec&&sec.keys.indexOf(k)>=0);
  const list=here.length?here:missing;
  return `<div class="gfmissing">
    <span class="count">Add a line:</span>
    <select id="gfAddKey">${(list.length?list:missing).map(k=>{
      const sp=GF_FIELDS[k];
      return `<option value="${esc(k)}">${esc(k)}${sp?': '+esc(sp.t):''}</option>`;}).join('')
      ||'<option value="">The unit already has every known line</option>'}</select>
    <button onclick="gfAdd()">Add</button>
    ${offCount<3?`<button onclick="gfAddOfficer()" title="Officers are extra men on top of the unit; up to three"
      >＋ Officer (${offCount}/3)</button>`:''}
    ${here.length&&here.length!==missing.length?'<span class="count">Missing from this group</span>':''}
  </div>`;
}
function gfAdd(){
  const sel=document.getElementById('gfAddKey'),k=sel&&sel.value; if(!k)return;
  gfHost().add(k);
}
function gfAddOfficer(){
  const host=gfHost();
  const n=host.fields().filter(([l])=>gfKey(l)==='officer').length;
  if(n>=3)return;
  host.addLabel('officer',n?`officer#${n+1}`:'officer');
}

/* ---- wiring ------------------------------------------------------------- */
const gfHost=()=>((state.mode==='edit'&&state.ed)?gfHostEditor():gfHostComposer());
function gfHelp(label){const gf=state.gf;
  if(gf.help.has(label))gf.help.delete(label); else gf.help.add(label); gfRerenderBody();}
function gfRaw(label){const gf=state.gf;
  if(gf.raw.has(label))gf.raw.delete(label); else gf.raw.add(label); gfRerenderBody();}
function gfRemove(label){gfHost().toggleRemove(label);}

function gfWire(host){
  // one slot of a line: write the whole line back, but never re-render — that
  // would take the caret out of the box being typed into
  const write=(label,i,value)=>{
    const spec=GF_FIELDS[gfKey(label)];
    const p=gfParse(spec,host.get(label));
    if(!p.ok)return;
    p.parts[i]=value;
    host.set(label,gfBuild(spec,p.parts));
    host.stale(); gfAfterEdit(host,label);
  };
  document.querySelectorAll('#allFields [data-gfp]').forEach(el=>{
    const label=el.dataset.gfp,i=+el.dataset.i;
    if(el.type==='checkbox'){
      el.onchange=()=>{write(label,i,el.checked?(GF_FIELDS[gfKey(label)].parts[i].on||'1'):'');};
      return;
    }
    const fire=()=>write(label,i,el.value);
    el.oninput=fire; el.onchange=fire;
    if(!el.classList.contains('gfnum'))return;
    const spec=GF_FIELDS[gfKey(label)];
    gfWireNum(el,spec&&spec.parts&&spec.parts[i],fire);
  });
  // the whole line as text
  document.querySelectorAll('#allFields [data-gfraw]').forEach(el=>{
    const label=el.dataset.gfraw;
    el.oninput=()=>{host.set(label,el.value); host.stale(); gfAfterEdit(host,label,true);};
    el.onblur=()=>{const spec=GF_FIELDS[gfKey(label)];
      // a retyped raw line can change how many values it has, which changes the
      // boxes above it — redraw once the user has finished with it
      if(spec&&spec.parts)gfRerenderBody();};
  });
  // mount_effect's paired boxes
  document.querySelectorAll('#allFields [data-gfme]').forEach(el=>{
    const label=el.dataset.gfme,i=+el.dataset.i,part=el.dataset.part;
    const fire=()=>{const p=gfMeParts(host,label);
      if(!p[i])return; p[i][part]=el.value; gfMeWrite(host,label,p); gfAfterEdit(host,label);};
    el.oninput=fire;
    // a mount effect is a signed modifier, so it steps by 1 either way
    if(part==='v')gfWireNum(el,{min:-100,max:100},fire);
  });
  host.count();
}
// The ↑/↓ keys and the ▴▾ buttons of one number box. The buttons repeat while
// held — a cost field is a long way from 0 one click at a time.
function gfWireNum(el,p,fire){
  el.onkeydown=ev=>gfNumKey(ev,p,el,fire);
  const box=el.parentElement;
  (box?box.querySelectorAll('[data-spin]'):[]).forEach(b=>{
    const dir=+b.dataset.spin;
    b.onmousedown=ev=>{
      if(ev.button)return;
      ev.preventDefault();
      const once=()=>{gfStep(p,el,dir,ev.shiftKey);fire();};
      once();
      const start=setTimeout(()=>{b._rep=setInterval(once,60);},400);
      const stop=()=>{clearTimeout(start);clearInterval(b._rep);
        document.removeEventListener('mouseup',stop);};
      document.addEventListener('mouseup',stop);
    };
  });
}
/* Stepping a number box, from either the ▴▾ buttons or the ↑/↓ keys.
   `dir` is +1 / -1 and Shift multiplies by 10. The part's own min/max clamp the
   RESULT — and only the result: a value already outside the range (a mod's
   attack of 65, say) is left alone until you step it, and typing is never
   touched at all. An empty box starts from the minimum, or 0. */
function gfStep(p,el,dir,big){
  const step=(p&&p.step)||1;
  const dec=(p&&p.dec!=null)?p.dec
    :/\./.test(''+step)?(''+step).split('.')[1].length
    :/\./.test(el.value)?(el.value.split('.')[1]||'').length:0;
  const cur=parseFloat(el.value);
  let n=(isNaN(cur)?((p&&p.min!=null)?p.min:0):cur)+step*(big?10:1)*dir;
  if(p&&p.min!=null&&n<p.min)n=p.min;
  if(p&&p.max!=null&&n>p.max)n=p.max;
  el.value=dec?n.toFixed(dec):String(Math.round(n));
}
function gfNumKey(ev,p,el,fire){
  if(ev.key!=='ArrowUp'&&ev.key!=='ArrowDown')return;
  ev.preventDefault();
  gfStep(p,el,ev.key==='ArrowUp'?1:-1,ev.shiftKey);
  fire();
}
// After an edit that did NOT redraw: refresh the things that depend on the value
// (the changed marks, the warnings, the base-unit B, the raw box).
function gfAfterEdit(host,label,fromRaw){
  const cur=host.get(label),changed=host.changed(label);
  const card=document.querySelector(`#allFields .gfcard[data-card="${cssq(label)}"]`);
  if(card){
    card.classList.toggle('changed',changed);
    card.querySelectorAll('[data-gfraw]').forEach(r=>{
      if(r!==document.activeElement)r.value=cur;
      r.classList.toggle('changed',changed);});
    const spec=GF_FIELDS[gfKey(label)];
    const p=spec&&spec.parts?gfParse(spec,cur):null;
    if(fromRaw&&p&&p.ok){    // keep the guided boxes in step while the raw line is typed
      card.querySelectorAll('[data-gfp]').forEach(el=>{
        const v=p.parts[+el.dataset.i]==null?'':p.parts[+el.dataset.i];
        if(el.type==='checkbox')el.checked=!!v; else if(el.value!==v)el.value=v;});
    }
    // …and light up only the part that now differs from the file
    if(p){
      const pc=gfPartChanged(host,label,spec,p);
      card.querySelectorAll('[data-gfp]').forEach(el=>{
        const on=pc(+el.dataset.i);
        el.classList.toggle('changed',on);
        const cell=el.closest('.gfpart'); if(cell)cell.classList.toggle('changed',on);});
    }
    const b=card.querySelector('button[data-b]');
    if(b)b.outerHTML=host.badge(label,cur);
  }
  const w=gfWarnings(host);
  document.querySelectorAll('#allFields [data-warn]').forEach(el=>{
    const html=gfNotes(w[el.dataset.warn]);
    if(el.innerHTML!==html)el.innerHTML=html;});
  const sum=document.getElementById('gfSum'); if(sum)sum.innerHTML=gfSumHtml(host,w);
  host.count();
}
