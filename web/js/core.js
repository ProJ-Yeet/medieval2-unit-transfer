/* core.js — shared state, the API client, the module registry and the burger
   menu, mod loading, filters, and the card grid every mode paints into

   Part of the Medieval 2 GUI Toolkit UI. These files are plain
   <script> tags sharing ONE global scope, loaded in the order set in
   index.html — there is no build step and no module system. Two rules
   follow from that: a top-level name must be unique across all of
   them, and a file's top-level side effects may not depend on a file
   loaded after it. */
// `dst` is the mod being written to right now, which a single-mod mode mirrors
// onto the source. `xferDst` is the destination the user actually PICKED, kept
// apart so that entering Edit/Buildings doesn't quietly overwrite it — see
// applyMode.
const state={mods:[],src:null,dst:null,xferDst:null,data:null,destData:null,factionNames:{},
  sel:{faction:new Set(),category:new Set(),class:new Set(),era:new Set()},
  selMode:false, selected:new Set(), cfg:{}, editing:null, settings:{},
  // group headings the user has folded shut, `groupBy:heading` (see toggleGroup)
  folded:new Set(),
  // 'transfer' = move units between mods; 'edit' = edit the units of ONE mod;
  // 'bmdb' = edit / clean up that mod's whole battle_models.modeldb;
  // 'sounds' = which voice-bank entry each unit uses;
  // 'buildings' = that mod's export_descr_buildings.txt
  // 'traits' = its export_descr_character_traits.txt, both halves;
  // 'ancillaries' = its export_descr_ancillaries.txt, likewise;
  // 'minor' = the five small campaign files (rebels, religions, resources,
  //           cultures, character names) behind one tab strip
  mode:'home', ed:null, bmdb:null, clean:null, snd:null, destSnd:null, str:null,
  tr:null, an:null, mf:null, fac:null,
  // bld survives a hop into the unit editor and back — see openUnitFromBuilding
  bld:null, bldReturn:null};

const VANILLA_UNIT_LIMIT=500;   // M2TW vanilla EDU cap; M2TWEOP/EOP raise it.

/* ---------- the API client ----------
   Two things every request in this app needs, so they live here rather than in
   twenty modules: it can be ABANDONED (picking another mod half way through a
   load must not paint the mod you just left), and it is what the loading bar
   watches. A module gets both by doing nothing at all — see `loadbar` below. */

// Thrown by a request that was abandoned. Callers check for it and return
// quietly: nothing went wrong, the answer simply stopped being wanted.
const ABORTED='__aborted__';
const isAborted=e=>e===ABORTED||(e&&e.name==='AbortError');
// Bumped by every new load. A response carrying an older number is dropped
// instead of painted — the reason a fast switch back and forth can't leave the
// screen showing the other mod.
let _loadGen=0,_loadAbort=null;
function newLoad(){
  _loadGen++;
  if(_loadAbort)_loadAbort.abort();      // the requests of the load being replaced
  _loadAbort=new AbortController();
  return {gen:_loadGen,signal:_loadAbort.signal};
}
const loadStale=gen=>gen!==_loadGen;

// GET with a few automatic retries — a page's request can be dropped transiently
// (e.g. during an icon burst, or if the tab was open across a server restart),
// and we must never hang forever on such a blip. An abandoned request is never
// retried: nobody is waiting for it.
const api={
  get:async(u,opts)=>{
    const o=(typeof opts==='number')?{tries:opts}:(opts||{});
    const tries=o.tries||4; let err;
    loadbar.opened(u,o.label);
    try{
      for(let i=0;i<tries;i++){
        try{const r=await fetch(u,{cache:'no-store',signal:o.signal});
          if(!r.ok) throw new Error('HTTP '+r.status);
          return await r.json();}
        catch(e){
          if(isAborted(e)||(o.signal&&o.signal.aborted))throw ABORTED;
          err=e; if(i<tries-1) await new Promise(res=>setTimeout(res,200*(i+1)));}
      }
      throw err;
    }finally{loadbar.closed(u);}},
  post:async(u,b,opts)=>{
    const o=opts||{};
    loadbar.opened(u,o.label);
    try{
      return await (await fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify(b||{}),signal:o.signal})).json();
    }catch(e){ if(isAborted(e))throw ABORTED; throw e; }
    finally{loadbar.closed(u);}}};

/* ---------- the loading bar ----------
   "The menu is open but nothing is on it yet" used to look identical to "this is
   broken": the biggest mod takes a moment to read, and a blank panel says
   nothing about which of the two you are looking at.

   It counts REQUESTS rather than asking each module to report progress, which is
   why every module has one without a line of its own code: opened/closed are
   called by the API client above, the bar appears once a burst has lasted long
   enough to be worth mentioning, and the fraction is "answered / asked for so
   far". Traffic that isn't a load — the heartbeat, a progress poll, a settings
   save — is ignored, or the bar would blink every four seconds forever. */
const LOADBAR_IGNORE=[/\/api\/heartbeat/,/\/api\/bye/,/\/api\/progress/,/\/api\/settings$/];
const LOADBAR_DELAY=180;     // ms a burst must last before the bar is worth showing
const loadbar={
  open:0,done:0,label:'',timer:null,shown:false,
  ignored(u){return LOADBAR_IGNORE.some(re=>re.test(u));},
  opened(u,label){
    if(this.ignored(u))return;
    if(!this.open)this.done=0;                 // a new burst
    this.open++;
    if(label)this.label=label;
    if(!this.shown&&!this.timer)this.timer=setTimeout(()=>this.show(),LOADBAR_DELAY);
    this.paint();
  },
  closed(u){
    if(this.ignored(u))return;
    this.open=Math.max(0,this.open-1); this.done++;
    if(!this.open)this.hide(); else this.paint();
  },
  // What the bar SAYS. A module that knows better than "Loading…" passes a label
  // with its request; anything else keeps the last one until the burst ends.
  say(label){this.label=label;this.paint();},
  show(){this.timer=null;this.shown=true;
    const el=document.getElementById('loadbar'); if(el)el.classList.add('on');
    this.paint();},
  hide(){clearTimeout(this.timer);this.timer=null;this.shown=false;this.label='';
    const el=document.getElementById('loadbar'); if(el)el.classList.remove('on');},
  paint(){
    if(!this.shown)return;
    const el=document.getElementById('loadbar'); if(!el)return;
    const total=this.done+this.open;
    const pct=total?Math.round(100*this.done/total):0;
    // nothing to divide by yet -> sweep rather than sit at a made-up number
    el.classList.toggle('busy',total<2);
    if(total>=2)el.querySelector('.lbfill').style.width=Math.max(4,pct)+'%';
    el.querySelector('.lbtext').textContent=this.label||'Loading…';
    el.querySelector('.lbnum').textContent=total>1?`${this.done}/${total}`:'';
  }};
/* ---------- activity ----------
   What the PERSON did, into the same log as what the tool did.

   The log used to record every file written and nothing about the clicks that
   led there, so reading it back meant inferring intent from effects. These lines
   close that half: mode opened, mod picked, record opened, field changed from
   this to that, dialog closed with edits still pending.

   Batched, because a burst of clicking must not become a burst of requests: a
   flush goes out about once a second, and the queue is drained on the way out of
   the page too. */
const ACTIVITY_FLUSH=1200, ACTIVITY_MAX=60;
let _acts=[],_actT=null;
function activity(what,detail){
  _acts.push({what:what,detail:detail==null?'':''+detail});
  if(_acts.length>ACTIVITY_MAX)_acts.shift();
  if(!_actT)_actT=setTimeout(flushActivity,ACTIVITY_FLUSH);
}
function flushActivity(){
  clearTimeout(_actT); _actT=null;
  if(!_acts.length)return;
  const events=_acts; _acts=[];
  // fire and forget: the log is a record, never something the UI waits on
  try{fetch('/api/activity',{method:'POST',keepalive:true,
    headers:{'Content-Type':'application/json'},body:JSON.stringify({events})});}catch(e){}
}
// A field's OLD value is only knowable before it changes, so it is remembered on
// the way in. `change` rather than `input`: one line per value the user settled
// on, not one per keystroke.
const _actWas=new WeakMap();
document.addEventListener('focusin',e=>{
  const el=e.target;
  if(el&&/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName||''))_actWas.set(el,el.value);
},true);
// Controls that already write a better line of their own, so the generic one
// would only repeat them (and worse: a picker changed by code never saw the
// focusin, so its "was" would be blank).
const ACTIVITY_SKIP=['srcSel','dstSel','search'];
document.addEventListener('change',e=>{
  const el=e.target; if(!el||!el.tagName)return;
  if(ACTIVITY_SKIP.includes(el.id))return;
  const name=el.id||el.getAttribute('data-label')||el.getAttribute('data-row')
    ||el.getAttribute('data-bp')||el.name||el.className||el.tagName.toLowerCase();
  if(el.type==='checkbox'||el.type==='radio')
    return activity('ticked',`${name} -> ${el.checked?'on':'off'}`);
  const was=_actWas.get(el);
  if(was===el.value)return;
  // No focusin means nothing typed in this box — a picker set by code, or a
  // control drawn and changed in one go. Saying so beats printing an empty "was".
  activity('changed',was==null?`${name} -> “${(el.value||'').slice(0,120)}” (was not read)`
    :`${name}: “${was.slice(0,120)}” -> “${(el.value||'').slice(0,120)}”`);
  _actWas.set(el,el.value);
},true);
window.addEventListener('pagehide',flushActivity);

const esc=s=>(s==null?'':''+s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const q1=v=>v.replace(/'/g,"\\'");
// A note is a short lead line and then points. Prose that runs for six lines is
// unreadable in an 11.5px grey box, so anything carrying more than one fact is
// written this way. .count, .bnote, .sprnote and .gfdoc all style the list.
const docPoints=(lead,points)=>{const ps=points.filter(Boolean);
  return ps.length?lead+'<ul>'+ps.map(p=>'<li>'+p+'</li>').join('')+'</ul>':lead;};
function toast(m,ms=2800){const t=document.getElementById('toast');t.textContent=m;t.classList.add('show');clearTimeout(t._t);t._t=setTimeout(()=>t.classList.remove('show'),ms);}
// A faction has two names — the EDU's code ("teutonic_order") and the in-game one
// ("Clans of Enedwaith") — and which one you look for depends on what you are
// doing. Whichever is picked leads and sorts; the other rides along in brackets so
// the row is still readable either way.
const facBy=()=>(state.settings.faction_sort==='code'?'code':'name');
const facTwoNames=(code,name)=>!name?code
  :facBy()==='code'?`${code} (${name})`:`${name} (${code})`;
const facLabel=f=>facTwoNames(f,state.factionNames[f]);
// In a CHECKLIST the two names are split rather than run together: the one you
// are reading down the list for leads, and the other appears over the row on
// hover (.facrow .fc), so a long name is never cut short to make room for a code
// you only need to glance at once. Which one leads is the ⚙ faction_sort setting.
const facLead=(code,name)=>!name?code:(facBy()==='code'?code:name);
const facBehind=(code,name)=>!name?'':(facBy()==='code'?name:code);
// One checklist row: tick box, the leading name, and the hover-only detail.
function facCheckRow(code,name,onchange,checked,note,edited){
  const behind=[facBehind(code,name),note].filter(Boolean).join(' · ');
  return `<div class="facrow${edited?' edited':''}">
    <label class="chk"><input type="checkbox" ${checked?'checked':''} onchange="${onchange}">
      <span class="fn">${esc(facLead(code,name))}</span></label>
    ${behind||edited?`<span class="fc">${esc(behind)}${
      edited?(behind?' · ':'')+(checked?'added by you':'removed by you'):''}</span>`:''}</div>`;
}
const iconUrl=(mod,type,kind)=>`/icon?mod=${encodeURIComponent(mod)}&type=${encodeURIComponent(type)}&kind=${kind||'card'}`;
// Icon requests can be dropped when a page fires dozens at once (connection
// bursts). A missing icon returns a valid blank PNG (onload), so onerror only
// fires on a genuine connection failure — retry it a few times with backoff.
function iconRetry(img){
  const n=(+img.dataset.try||0)+1; img.dataset.try=n;
  if(n>4) return;                       // give up quietly after 4 tries
  const base=img.src.split('#')[0];
  setTimeout(()=>{img.src=base+'#r'+n;}, 120*n*n);
}

// Keep the server alive while this tab is open; tell it to stop when the tab closes
// (so a windowless server doesn't linger holding the port). A refresh sends 'bye'
// too, but the reloaded page resumes heartbeats within the server's grace window.
let _hbStarted=false;
function startHeartbeat(){
  if(_hbStarted)return; _hbStarted=true;
  const beat=()=>{try{fetch('/api/heartbeat',{method:'POST',keepalive:true});}catch(e){}};
  beat(); setInterval(beat,4000);
  const bye=()=>{try{navigator.sendBeacon('/api/bye');}catch(e){}};
  window.addEventListener('pagehide',bye);
  window.addEventListener('beforeunload',bye);
}
async function init(){
  try{
    startHeartbeat();
    const s=await api.get('/api/settings');state.settings=s;
    facSort.value=facBy();                 // remembered across runs like the rest
    restoreFilters();                      // …and so are the filters themselves
    // ?mod=&edit= — how "open this unit in a new tab" arrives. It picks the mod
    // and opens the editor for this tab only; the remembered mod is not changed.
    const qs=new URLSearchParams(location.search);
    const qMod=qs.get('mod'),qEdit=qs.get('edit');
    // A launch lands on Home, whatever module you were in last time — that is
    // the point of having one. The remembered mode is not forgotten: Home offers
    // it as "last time you were in …", so it is a click rather than an ambush.
    state.mode=qEdit?'edit':'home';
    await refreshMods(qMod||s.last_source,qMod||s.last_dest);
    wire(); applyMode(false);
    if(qEdit){
      if(state.data&&state.data.units.some(u=>u.type===qEdit))openEditor(qEdit);
      else toast(`“${qEdit}” is not a unit in ${state.src}`,4000);
    }
  }catch(e){
    main.innerHTML=`<div class="empty">Couldn't reach the Medieval 2 GUI Toolkit server.<br>
      <span class="count">Is <code>Launch-Medieval2-GUI-Toolkit.bat</code> (python app.py) still running?</span><br><br>
      <button class="primary" onclick="init()">Retry</button></div>`;
  }
}

const realMods=()=>state.mods.filter(m=>!m.pack);
async function refreshMods(pSrc,pDst){
  state.mods=await api.get('/api/mods');
  const opt=m=>`<option value="${esc(m.name)}">${esc(m.pack?'📦 '+m.name:m.name)}</option>`;
  srcSel.innerHTML=state.mods.map(opt).join('');
  // A mounted unit pack can only ever be a SOURCE: it holds a handful of units
  // and nothing else, and writing into it would go nowhere — it is deleted when
  // the pack is unmounted.
  dstSel.innerHTML=realMods().map(opt).join('');
  if(!state.mods.length){main.innerHTML='<div class="empty">No mods found. Click ⚙ Settings to point at your Medieval II folder.</div>';return;}
  const real=realMods().length?realMods():state.mods;
  state.src=pSrc&&state.mods.some(m=>m.name===pSrc)?pSrc:real[0].name;
  state.dst=pDst&&real.some(m=>m.name===pDst)?pDst:(real[1]?.name||real[0].name);
  // Older builds persisted a single-mod mode's mirrored destination as
  // last_dest, so a remembered pair can arrive as A -> A. Starting Transfer
  // pointed at the source mod reads as "copy this onto itself" — pick a real
  // second mod instead, exactly as a first run would.
  if(state.mode==='transfer'&&state.dst===state.src&&real.length>1)
    state.dst=real.find(m=>m.name!==state.src).name;
  state.xferDst=state.dst;
  srcSel.value=state.src; dstSel.value=state.dst;
  state.destData=null;
  await loadSource();
}
// The unit list is what Transfer and Edit show; the other modes have their own
// workspace, so this must not paint over one of those just because the units
// finished loading underneath it.
const unitListMode=()=>state.mode==='transfer'||state.mode==='edit';
async function loadSource(){
  const mod=state.src;
  // Every load ABANDONS the one before it. Without this, picking a second mod
  // while the first was still being read left both requests running: the older
  // one held one of the browser's handful of connections to the end, and if it
  // was the one that finished last, its units were the ones you were left
  // looking at. Switching mods is the commonest thing anyone does here.
  const {gen,signal}=newLoad();
  activity('reading mod',mod);
  if(unitListMode())main.innerHTML='<div class="empty">Loading '+esc(mod)+'…</div>';
  let r;
  try{
    r=await api.get('/api/units?mod='+encodeURIComponent(mod),
                    {signal,label:`Reading ${mod}’s units…`});
  }catch(e){
    if(isAborted(e)||loadStale(gen)||mod!==state.src)return;   // a later load owns the screen
    if(unitListMode())main.innerHTML=`<div class="empty">Couldn't load “${esc(mod)}”.<br>
      <span class="count">${esc(''+e)}</span><br><br>
      <button class="primary" onclick="loadSource()">Retry</button></div>`;
    return;
  }
  if(loadStale(gen)||mod!==state.src)return;   // a later load owns the screen now
  state.data=r;
  state.factionNames=state.data.faction_names||{};
  // Keep whatever is ticked. Saving a unit or finishing a transfer reloads this
  // list, and re-ticking the same filters every time was maddening. Only values
  // this mod doesn't have are dropped — a filter that can never match would hide
  // everything with no visible reason why.
  let dropped=false;
  const prune=(key,values)=>{const ok=new Set(values||[]);
    for(const v of [...state.sel[key]])if(!ok.has(v)){state.sel[key].delete(v);dropped=true;}};
  prune('faction',state.data.factions);
  prune('category',state.data.categories);
  prune('class',state.data.classes);
  if(dropped)saveFilters();   // don't let the next run resurrect what was dropped
  // same for a pending multi-selection: a unit that was just deleted (or that
  // this mod never had) can't be transferred, so it can't stay ticked
  const types=new Set(state.data.units.map(u=>u.type));
  for(const t of [...state.selected])if(!types.has(t))state.selected.delete(t);
  updateBatchBtn();
  buildFilter('factionFilter',state.data.factions,'faction',true);
  buildFilter('categoryFilter',state.data.categories,'category');
  buildFilter('classFilter',state.data.classes,'class');
  syncEraBoxes();
  render();
}
/* ---------- filters remembered ----------
   The filter panel is "where I was looking", the same kind of state as the mod
   pair and the faction sort, so it is persisted the same way and restored on
   the next run instead of only surviving until the next reload. */
function restoreFilters(){
  const f=state.settings.filters||{};
  state.sel={faction:new Set(f.faction||[]),category:new Set(f.category||[]),
             class:new Set(f.class||[]),era:new Set(f.era||[])};
  if(f.group_by)groupBy.value=f.group_by;
  mercOnly.checked=!!f.merc_only;
  state.folded=new Set(state.settings.folded_groups||[]);
  syncEraBoxes();
}
function syncEraBoxes(){document.querySelectorAll('.era').forEach(cb=>cb.checked=state.sel.era.has(cb.value));}
let _saveFiltersT=null;
function saveFilters(){                       // debounced: ticking is a burst
  clearTimeout(_saveFiltersT);
  _saveFiltersT=setTimeout(()=>{
    state.settings.filters={faction:[...state.sel.faction],category:[...state.sel.category],
      class:[...state.sel.class],era:[...state.sel.era],
      group_by:groupBy.value,merc_only:mercOnly.checked};
    api.post('/api/settings',{filters:state.settings.filters});
  },400);
}
function filtersChanged(){saveFilters();render();}
async function ensureDest(){ if(!state.destData||state.destData.mod!==state.dst){state.destData=await api.get('/api/units?mod='+encodeURIComponent(state.dst));} return state.destData; }

function buildFilter(id,values,key,useLabel){
  const box=document.getElementById(id);
  // factions are listed under whichever name is leading, so the A→Z the user
  // picked is the A→Z they see here as well as in the group headers
  const list=useLabel?[...(values||[])].sort((a,b)=>facLabel(a).localeCompare(facLabel(b)))
                     :(values||[]);
  box.innerHTML=list.map(v=>`<label class="opt"><input type="checkbox" value="${esc(v)}" ${
    state.sel[key].has(v)?'checked':''}>${esc(useLabel?facLabel(v):v)}</label>`).join('')
    ||'<span class="count">—</span>';
  box.querySelectorAll('input').forEach(cb=>cb.onchange=()=>{const s=state.sel[key];cb.checked?s.add(cb.value):s.delete(cb.value);filtersChanged();});
}
/* ---------- burger menu ----------
   The single registry of modules. Everything the menu shows — and the header
   label, and the per-mode document title — comes from here, so a new module is
   one entry in this array plus its render function. */
// `sub:true` = still a real mode, but reached through a tab strip inside its
// host rather than from this menu (Sprites lives in the BMDB editor; Traits,
// Ancillaries, Factions and Strings live in Minor Files).
const MODES=[
  {id:'home',     icon:'⌂', name:'Home',          hint:'your mods, and what each one is ready for'},
  {id:'edit',     icon:'✎', name:'Unit Editor',   hint:'change, clone or delete one mod’s units'},
  {id:'transfer', icon:'⚔', name:'Unit Transfer', hint:'copy a unit from one mod into another'},
  {id:'buildings',icon:'🏰', name:'Buildings',     hint:'browse and edit export_descr_buildings'},
  {id:'bmdb',     icon:'🗄', name:'BMDB + Sprites Editor', hint:'battle_models.modeldb, and the sprites it points at'},
  {id:'sounds',   icon:'🔊', name:'Unit Sounds',   hint:'pick which voice entry each unit speaks with'},
  {id:'minor',    icon:'🗺', name:'Minor Files',   hint:'rebels, religions, cultures, traits, factions and text'},
  {id:'sprites',  icon:'🖼', name:'Sprites',       sub:true, hint:'generate and wire the far-LOD unit sprites'},
  {id:'traits',   icon:'🎖', name:'Traits',        sub:true, hint:'character traits, their levels and the triggers that give them'},
  {id:'ancillaries',icon:'🏅', name:'Ancillaries',  sub:true, hint:'the items and followers a character picks up'},
  {id:'factions', icon:'🛡', name:'Factions',      sub:true, hint:'each faction’s culture, religion, colours and horde'},
  {id:'strings',  icon:'🔤', name:'Strings',       sub:true, hint:'the compiled text files the game actually reads'},
];
const modeDef=id=>MODES.find(m=>m.id===id)||MODES[0];

/* ---------- the Minor Files tab strip ----------
   Nine campaign files behind one strip. Five are shapes of one parser and are
   tabs of the `minor` mode; the other four are big enough to have their own
   mode, so their tab switches mode rather than tab. Everything the strip needs
   is here because five different files draw it. */
const MINOR_TABS=[
  {id:'rebels',      label:'Rebel factions'},
  {id:'religions',   label:'Religions'},
  {id:'resources',   label:'Resources'},
  {id:'cultures',    label:'Cultures'},
  {id:'names',       label:'Character names'},
  {mode:'traits',      label:'Traits'},
  {mode:'ancillaries', label:'Ancillaries'},
  {mode:'factions',    label:'Factions'},
  {mode:'strings',     label:'Strings'},
];
let minorWantTab=null;
function minorTabsHtml(active,note){
  return `<div class="mftabs">${MINOR_TABS.map(t=>{
    const on=t.mode?state.mode===t.mode:(state.mode==='minor'&&active===t.id);
    const go=t.mode?`minorGo(null,'${t.mode}')`:`minorGo('${t.id}')`;
    return `<button class="mftab${on?' on':''}" onclick="${go}">${esc(t.label)}</button>`;
  }).join('')}${note?`<span class="count" style="margin-left:auto">${esc(note)}</span>`:''}</div>`;
}
function minorGo(tab,mode){
  if(mode)return setAppMode(mode);
  if(state.mode==='minor')return mfTab(tab);
  minorWantTab=tab; state.mf=null; setAppMode('minor');
}

/* ---------- the findings banner ----------
   "14 things to look at — the marked rows below" was the whole message, so the
   only way to learn WHAT was to open every marked row. It now opens: one line
   per finding, each a link to the record it is about. Shared by Traits,
   Ancillaries, Factions and Minor Files, which all produce the same shape.

   `open` is remembered per screen in `state.findOpen`, so opening it does not
   close again on the next repaint. */
state.findOpen={};
function findingsHtml(key,list,onopen){
  const n=(list||[]).length;
  if(!n)return '';
  const open=!!state.findOpen[key];
  const rows=(list||[]).map(f=>`<div class="findrow">
      ${f.name?`<a class="ulink" onclick="${onopen}('${q1(esc(f.name))}')"
        >${esc(f.name)}</a> `:''}<span>${esc(f.message||f.kind||'')}</span>
    </div>`).join('');
  return `<div class="trnote w-warn">
    <button class="findtog" onclick="findingsToggle('${q1(esc(key))}')">
      ${open?'▾':'▸'} ${n} thing${n===1?'':'s'} to look at</button>
    ${open?`<div class="findlist">${rows}</div>`
          :'<div class="count">the marked rows below, or open this to read them</div>'}
  </div>`;
}
function findingsToggle(key){state.findOpen[key]=!state.findOpen[key]; render();}

/* ---------- the BMDB tab strip ----------
   Sprites are the far-LOD half of a modeldb entry, so they are a tab of the
   BMDB editor rather than a module of their own. */
const BMDB_TABS=[{mode:'bmdb',label:'Model entries'},{mode:'sprites',label:'Sprites'}];
const bmdbTabsHtml=note=>`<div class="mftabs">${BMDB_TABS.map(t=>
  `<button class="mftab${state.mode===t.mode?' on':''}" onclick="setAppMode('${t.mode}')"
    >${esc(t.label)}</button>`).join('')}${
  note?`<span class="count" style="margin-left:auto">${esc(note)}</span>`:''}</div>`;
function navOpen(open){
  navMenu.classList.toggle('open',open);
  navBack.classList.toggle('open',open);
  navMenu.setAttribute('aria-hidden',open?'false':'true');
}
// NB: not "setMode" — the composer already owns that name (its new/base/replace
// switch), and function declarations hoist, so the later one would silently win.
function setAppMode(id){
  navOpen(false);
  if(id===state.mode)return;
  activity('opened',`${modeDef(id).name} (mod: ${state.src||'none'})`);
  state.mode=id;applyMode(true);
}
// keeps the header label and the menu's highlighted row honest — called from
// applyMode so every way of switching (menu, pack mount, building hop) lands here
// A sub-mode has no row of its own in the menu, so its HOST row lights up.
const MODE_HOST={sprites:'bmdb',traits:'minor',ancillaries:'minor',
  factions:'minor',strings:'minor'};
function syncNav(){
  const d=modeDef(state.mode), host=MODE_HOST[state.mode]||state.mode;
  navCur.textContent=d.icon+' '+d.name;
  document.querySelectorAll('#navModes .navitem').forEach(b=>
    b.classList.toggle('on',b.dataset.mode===host));
}
function wire(){
  navModes.innerHTML=MODES.filter(m=>!m.sub).map(m=>`<button class="navitem" data-mode="${m.id}">
      <span class="ic">${m.icon}</span>
      <span><span class="nm">${esc(m.name)}</span><span class="hint">${esc(m.hint)}</span></span>
    </button>`).join('');
  navModes.querySelectorAll('.navitem').forEach(b=>b.onclick=()=>setAppMode(b.dataset.mode));
  navBtn.onclick=()=>navOpen(!navMenu.classList.contains('open'));
  navBack.onclick=()=>navOpen(false);
  creditsBtn.onclick=()=>{navOpen(false);openCredits();};
  document.addEventListener('keydown',e=>{
    if(e.key==='Escape'&&navMenu.classList.contains('open'))navOpen(false);});
  newUnitBtn.onclick=openNewUnitPicker;
  tidyEduBtn.onclick=openEduTidy;
  // Picking the mod that's already on the other side swaps the pair rather than
  // leaving a pointless A -> A: with A -> B, choosing A as the dest gives B -> A.
  srcSel.onchange=async e=>{
    const v=e.target.value;
    if(v!==state.src)
      activity('picked mod',`${state.mode==='transfer'?'source: ':''}${v} (was ${state.src})`);
    // A ticked pile belongs to the mod it was ticked in — carrying it to another
    // mod would transfer whatever happens to share a type name over there.
    if(v!==state.src)clearSelection();
    // Edit / bmdb mode works on a single mod, so both sides follow the picker.
    if(state.mode!=='transfer'){state.src=state.dst=v;dstSel.value=v;state.destData=null;
      state.cfg={};state.bmdb=null;state.snd=null;state.destSnd=null;state.str=null;
      state.tr=null;state.an=null;state.mf=null;state.fac=null;
      state.bld=null;state.bldReturn=null;
      // the mirrored destination is not the user's transfer pick — don't save it
      await api.post('/api/settings',{last_source:v,last_dest:state.xferDst||v});return loadSource();}
    if(v===state.dst){state.dst=state.xferDst=state.src;dstSel.value=state.dst;state.destData=null;}
    state.src=v;srcSel.value=v;state.cfg={};
    await api.post('/api/settings',{last_source:state.src,last_dest:state.dst});
    loadSource();};
  dstSel.onchange=async e=>{
    const v=e.target.value;
    if(v!==state.dst)activity('picked mod',`destination: ${v} (was ${state.dst})`);
    const srcChanged=(v===state.src);
    if(srcChanged){state.src=state.dst;srcSel.value=state.src;clearSelection();}
    state.dst=state.xferDst=v;dstSel.value=v;state.destData=null;state.destSnd=null;state.cfg={};
    await api.post('/api/settings',{last_source:state.src,last_dest:state.dst});
    if(srcChanged)loadSource();};
  // Strings filters on the SERVER (its biggest archive is 20 757 rows), so its
  // search is a debounced fetch rather than a repaint of what is already here.
  search.oninput=()=>{
    if(state.mode==='strings')return strSearch();
    render();};
  mercOnly.onchange=filtersChanged; groupBy.onchange=filtersChanged;
  // rebuilds the faction list (its A→Z changes) but keeps whatever is ticked
  facSort.onchange=()=>{state.settings.faction_sort=facSort.value;
    api.post('/api/settings',{faction_sort:facSort.value});
    if(state.data)buildFilter('factionFilter',state.data.factions,'faction',true);
    render();};
  document.querySelectorAll('.era').forEach(cb=>cb.onchange=()=>{cb.checked?state.sel.era.add(cb.value):state.sel.era.delete(cb.value);filtersChanged();});
  settingsBtn.onclick=openSettings; logBtn.onclick=openLog;
  selBtn.onclick=toggleSelMode; batchBtn.onclick=openBatch; clearSelBtn.onclick=clearSelection;
  packBtn.onclick=()=>packExport([...state.selected]); importPackBtn.onclick=packImport;
  cleanBtn.onclick=openCleanup; unusedOnly.onchange=render; sndBtn.onclick=sndApply;
  backBldBtn.onclick=backToBuilding;
  overlay.onclick=e=>{if(e.target.id==='overlay')closeModal();};
}
/* ---------- mode switching ---------- */
// Edit and bmdb modes work on ONE mod in place, so the destination always mirrors
// the source: that also lets the "new unit" flow reuse the transfer engine with
// source == dest.
function applyMode(persist){
  syncNav();
  const one=state.mode!=='transfer', edit=state.mode==='edit', bm=state.mode==='bmdb',
        snd=state.mode==='sounds', spr=state.mode==='sprites', bld=state.mode==='buildings',
        str=state.mode==='strings', trt=state.mode==='traits',
        anc=state.mode==='ancillaries', mnr=state.mode==='minor',
        fac=state.mode==='factions',
        home=state.mode==='home';
  // Home is the one screen that is ABOUT the mods, so it does not sit under a
  // mod picker: every card carries its own.
  document.getElementById('srcLbl').style.display=home?'none':'';
  srcSel.style.display=home?'none':'';
  document.getElementById('srcLbl').textContent=one?'Mod':'From';
  document.getElementById('dstWrap').style.display=(one||home)?'none':'';
  search.style.display=home?'none':'';
  selBtn.style.display=one?'none':'';
  batchBtn.style.display=(!one&&state.selMode)?'inline-block':'none';
  clearSelBtn.style.display=(!one&&state.selMode&&state.selected.size)?'inline-block':'none';
  // A pack is made from the SOURCE mod and imported into the destination, so
  // both live in transfer mode — which is also the only mode where "the other
  // mod" is a thing at all.
  packBtn.style.display=(!one&&state.selMode&&state.selected.size)?'inline-block':'none';
  importPackBtn.style.display=one?'none':'inline-block';
  newUnitBtn.style.display=edit?'inline-block':'none';
  tidyEduBtn.style.display=edit?'inline-block':'none';
  cleanBtn.style.display=bm?'inline-block':'none';
  sndBtn.style.display=snd?'inline-block':'none';
  unusedWrap.style.display=bm?'inline-flex':'none';
  mercOnly.parentElement.style.display=(bm||snd||spr||bld||str||trt||anc||mnr||fac||home)?'none':'inline-flex';
  // these bring their own filters — the sidebar's faction/era ones say nothing
  // about a voice entry, and nothing at all about a modeldb record or a sprite
  document.getElementById('unitFilters').style.display=
    (bm||snd||spr||bld||str||trt||anc||mnr||fac||home)?'none':'';
  document.getElementById('bldFilters').style.display=bld?'':'none';
  // Only offered while the unit editor is what you'd be going back FROM: in
  // buildings mode the building is already on screen.
  backBldBtn.style.display=(edit&&state.bldReturn)?'inline-block':'none';
  if(state.bldReturn)backBldBtn.textContent=`← Back to ${state.bldReturn.label}`;
  search.placeholder=bm?'Search entries…':snd?'Search units…':spr?'Search models…'
                    :bld?'Search buildings…':str?'Search tags and text…'
                    :trt?'Search traits…'
                    :anc?'Search ancillaries and types…'
                    :mnr?'Search this file…'
                    :fac?'Search factions…':'Search…';
  document.title=modeDef(state.mode).name+' — Medieval 2 GUI Toolkit';
  if(one&&state.selMode)toggleSelMode();
  // A single-mod mode mirrors the destination onto the source, but the pick the
  // user made in Transfer is remembered rather than overwritten — both in
  // `xferDst` and in the persisted setting, so neither this switch nor the next
  // run turns the transfer pair into A -> A. Transfer never shows A -> A anyway
  // (that is what Edit's "new unit from this one" is for), so coming back to it
  // with nothing to restore falls through to any other mod, same as a first run.
  if(one){
    if(state.dst!==state.src){state.xferDst=state.dst;
      state.dst=state.src;dstSel.value=state.src;state.destData=null;}
  }else if(state.dst===state.src&&state.mods.length>1){
    const want=state.xferDst&&state.xferDst!==state.src
      &&state.mods.some(m=>m.name===state.xferDst)
        ? state.xferDst : state.mods.find(m=>m.name!==state.src).name;
    state.dst=state.xferDst=want;dstSel.value=want;state.destData=null;state.destSnd=null;
  }
  if(persist)api.post('/api/settings',
    {mode:state.mode,last_dest:one?(state.xferDst||state.dst):state.dst});
  render();
}

// Leaving select mode keeps WHAT was ticked — you step out to look at a unit in
// the drawer, or to change a filter, and coming back to an empty pile after
// ticking twenty units was the worst way to lose work here. Only the highlight
// goes (a ticked card outside select mode just looks broken); ✕ Clear, switching
// source mod, and a finished transfer are what actually empty it.
function toggleSelMode(){state.selMode=!state.selMode;document.body.classList.toggle('selmode',state.selMode);
  selBtn.classList.toggle('on',state.selMode);
  paintSelection();
  batchBtn.style.display=state.selMode?'inline-block':'none';
  updateBatchBtn();}
function clearSelection(){state.selected.clear();paintSelection();updateBatchBtn();}
// every card of every selected unit, since one unit can render under several groups
function paintSelection(){main.querySelectorAll('.card').forEach(c=>
  c.classList.toggle('sel',state.selMode&&state.selected.has(c.dataset.type)));}
function updateBatchBtn(){batchBtn.textContent=`Transfer selected (${state.selected.size})`;batchBtn.disabled=state.selected.size===0;
  const on=state.selMode&&state.selected.size?'inline-block':'none';
  clearSelBtn.style.display=on;
  packBtn.style.display=state.mode==='transfer'?on:'none';
  packBtn.textContent=`📦 Export pack (${state.selected.size})`;}

function unitMatches(u){
  const qq=search.value.trim().toLowerCase();
  if(qq&&!(u.name.toLowerCase().includes(qq)||u.type.toLowerCase().includes(qq)||u.dictionary.toLowerCase().includes(qq)))return false;
  if(mercOnly.checked&&!u.mercenary)return false;
  const S=state.sel;
  if(S.faction.size&&!u.ownership.some(f=>S.faction.has(f)))return false;
  if(S.category.size&&!S.category.has(u.kind))return false;
  if(S.class.size&&!S.class.has(u.class))return false;
  if(S.era.size&&![...S.era].some(e=>(u.eras[e]||[]).length>0))return false;
  return true;
}
/* Every workspace is loaded asynchronously and the mode picker does not wait for
   it, so a read that takes a while — a 6000-entry modeldb, a whole voice bank,
   the first units load of a big mod — can come back after you have already moved
   on. Whoever started a load has to check it is still the one on screen before
   painting, or the new mode ends up wearing the old workspace's content (the
   toolbar and title switch, the body does not). `renderBuildings` has always
   done this; `stale()` is that same check for the rest. */
function stale(mode,mod){return state.mode!==mode||(mod!==undefined&&mod!==state.src);}
function render(){
  if(state.mode==='home')return renderHome();
  if(state.mode==='bmdb')return renderBmdb();
  if(state.mode==='sounds')return renderSounds();
  if(state.mode==='sprites')return renderSprites();
  if(state.mode==='buildings')return renderBuildings();
  if(state.mode==='strings')return state.str?renderStrings():loadStrings();
  if(state.mode==='traits')return state.tr?renderTraits():loadTraits();
  if(state.mode==='ancillaries')return state.an?renderAncillaries():loadAncillaries();
  if(state.mode==='minor')return state.mf?renderMinor():loadMinor();
  if(state.mode==='factions')return state.fac?renderFactions():loadFactions();
  // the unit list is still loading (or its load failed) — say so rather than
  // leaving whatever the mode before this one had drawn
  if(!state.data){main.innerHTML='<div class="empty">Loading '+esc(state.src)+'…</div>';return;}
  const units=state.data.units.filter(unitMatches);
  count.textContent=`${units.length}/${state.data.units.length}`;
  const gb=groupBy.value;
  if(!units.length){main.innerHTML='<div class="empty">No units match.</div>';return;}
  // Ticking a filter says "this is what I'm here for", so its group leads —
  // otherwise picking one faction buries it under every OTHER faction its units
  // are also owned by (a unit renders once per faction it belongs to). Alphabetical
  // within the picked ones, then alphabetical for the rest.
  const picked=state.sel[{faction:'faction',kind:'category',class:'class',era:'era'}[gb]]||new Set();
  const byPicked=(ka,kb,la,lb)=>(picked.has(kb)-picked.has(ka))||la.localeCompare(lb);
  let groups;
  if(gb==='none')groups=[['All units',units]];
  else if(gb==='faction'){const map=new Map();for(const u of units){for(const f of (u.ownership.length?u.ownership:['(none)']))(map.get(f)||map.set(f,[]).get(f)).push(u);}
    groups=[...map.entries()].sort((a,b)=>byPicked(a[0],b[0],facLabel(a[0]),facLabel(b[0]))).map(([f,us])=>[facLabel(f),us]);}
  // An era is a list of factions per era slot, so a unit lands in every era it
  // is fielded in — the same one-card-per-group rule faction grouping follows.
  else if(gb==='era'){const map=new Map();
    for(const u of units){const in_=ERA_KEYS.filter(e=>(u.eras[e]||[]).length);
      for(const e of (in_.length?in_:['-']))(map.get(e)||map.set(e,[]).get(e)).push(u);}
    groups=ERA_KEYS.concat('-').filter(e=>map.has(e)).map(e=>[ERA_LABEL[e],map.get(e)]);}
  else{const map=new Map();for(const u of units){const k=u[gb]||'(none)';(map.get(k)||map.set(k,[]).get(k)).push(u);}
    groups=[...map.entries()].sort((a,b)=>byPicked(a[0],b[0],a[0],b[0]));}
  main.innerHTML=groups.map(([g,us])=>{
    const key=gb+':'+g,off=state.folded.has(key);
    return `<section class="faction-group${off?' folded':''}">
    <div class="faction-head" onclick="toggleGroup('${q1(esc(key))}')"
      title="${off?'Show these units again':'Fold this group away'}">
      <span class="fold">${off?'▸':'▾'}</span>
      <h2>${esc(g)}</h2><span class="n">${us.length} units</span></div>
    ${off?'':`<div class="grid">${us.map(cardHtml).join('')}</div>`}</section>`;}).join('');
  main.querySelectorAll('.card').forEach(c=>c.onclick=()=>onCard(c.dataset.type));
}
// Custom-battle era slots, in the order the EDU writes them.
const ERA_KEYS=['0','1','2'];
const ERA_LABEL={'0':'Early','1':'High','2':'Late','-':'No era (campaign only)'};
/* Which group headings are folded shut. Keyed by group-by AND heading, so
   folding half the factions away does not also fold something in the category
   view, and remembered on the user's settings so it survives a reload the way
   the rest of the filter panel does. */
function toggleGroup(key){
  if(state.folded.has(key))state.folded.delete(key); else state.folded.add(key);
  state.settings.folded_groups=[...state.folded];
  api.post('/api/settings',{folded_groups:state.settings.folded_groups});
  render();
}
function cardHtml(u){
  const s=(state.selMode&&state.selected.has(u.type))?'sel':'';
  return `<div class="card ${s}" data-type="${esc(u.type)}">
    <div class="tick">✓</div>
    <img loading="lazy" onerror="iconRetry(this)" src="${iconUrl(state.src,u.type)}" alt="">
    <div class="meta"><div class="nm">${esc(u.name)}</div><div class="sub">${esc(u.type)}</div>
    <div>${u.eop?`<span class="badge eop" title="M2TWEOP unit — defined in ${esc(u.eop_file||'an EOP unit file')}, not in export_descr_unit.txt">EOP</span>`:''}${u.mercenary?'<span class="badge merc">merc</span>':''}<span class="badge">${esc(u.kind||u.category||'?')}</span>${u.class?`<span class="badge cls">${esc(u.class)}</span>`:''}</div></div></div>`;
}
function onCard(type){
  if(state.selMode){ if(state.selected.has(type))state.selected.delete(type); else state.selected.add(type);
    updateBatchBtn(); markCardSel(type); return; }
  if(state.mode==='edit') return openEditor(type);
  openDrawer(type);
}
// A unit owned by several factions renders one card per faction group (and the
// same goes for the other group-by modes), so EVERY copy has to reflect the
// selection — querySelector would only ever find the first, making a selected
// unit look unselected under its other factions.
function markCardSel(type){const on=state.selMode&&state.selected.has(type);
  main.querySelectorAll(`.card[data-type="${cssq(type)}"]`).forEach(c=>c.classList.toggle('sel',on));}
const cssq=s=>s.replace(/"/g,'\\"');

function openDrawer(type){
  const u=state.data.units.find(x=>x.type===type); if(!u)return;
  const d=document.getElementById('drawer');
  const eras=['0','1','2'].filter(e=>(u.eras[e]||[]).length).map(e=>({0:'Early',1:'High',2:'Late'}[e])).join(', ')||'—';
  d.innerHTML=`<button class="close" onclick="drawer.classList.remove('open')">×</button>
    <div class="dh"><img onerror="iconRetry(this)" src="${iconUrl(state.src,u.type)}"><div><h2>${esc(u.name)}</h2><div class="sub">${esc(u.type)}</div></div></div>
    ${u.has_info?`<div class="infowrap"><div class="k">Info card</div><img onerror="this.parentElement.style.display='none'" src="${iconUrl(state.src,u.type,'info')}"></div>`:''}
    <div class="body">
      ${row('Dictionary',esc(u.dictionary))}
      ${row('Ownership',u.ownership.map(f=>`<span class="chip">${esc(facLabel(f))}</span>`).join('')||'—')}
      ${row('Category / Class',esc(u.kind||u.category||'—')+' / '+esc(u.class||'—'))}
      ${row('Eras',eras)}
      ${row('Battle models',u.models.map(m=>`<span class="chip">${esc(m)}</span>`).join('')||'—')}
      ${row('Officers / Mount',(u.officers.map(o=>`<span class="chip">${esc(o)}</span>`).join('')||'—')+(u.mount?`  mount: <span class="chip">${esc(u.mount)}</span>`:''))}
      ${(u.engine||u.mounted_engine)?row('Siege engine',`<span class="chip">${esc(u.engine||u.mounted_engine)}</span>${u.mounted_engine&&!u.engine?' <span class="count">(mounted)</span>':''}${(u.engine_groups||[]).length?`<span class="count"> · groups: ${(u.engine_groups||[]).map(esc).join(', ')}</span>`:''}`):''}
      <button class="primary" style="width:100%;margin-top:6px" onclick="drawer.classList.remove('open');openComposer(['${q1(esc(u.type))}'])">Transfer to “${esc(state.dst)}” →</button>
    </div>`;
  d.classList.add('open');
}
const row=(k,v)=>`<div class="row"><div class="k">${k}</div><div class="v">${v}</div></div>`;

/* ---------- credits ---------- */
async function openCredits(){
  let ver='';
  try{const p=await api.get('/api/ping');if(p.version)ver='v'+p.version;}catch(e){}
  const m=document.getElementById('modal');
  m.className='modal';
  m.innerHTML=`
    <div class="ehead"><div>
      <div class="nm" style="font-size:17px;color:var(--accent)">Medieval 2 GUI Toolkit</div>
      <div class="count">${esc(ver)}</div>
    </div></div>
    <div style="padding:16px;line-height:1.7">
      <div style="margin-bottom:14px">
        <div class="lbl" style="margin-bottom:4px">Built on the work of</div>
        <b>Mylae</b> — the
        <a href="https://github.com/Machiavello-1441/m2tw-editor" target="_blank"
           style="color:var(--accent2)">M2TW Editor</a>, whose modules this toolkit adapts and builds on.
      </div>
      <div style="margin-bottom:14px">
        <div class="lbl" style="margin-bottom:4px">Special thanks</div>
        <b>Gigantus</b> and the <b>TWCenter</b> community — for the guides that
        taught everyone, this tool included, how these files actually work.
      </div>
      <div style="margin-bottom:14px">
        <div class="lbl" style="margin-bottom:4px">Thanks</div>
        <a href="https://www.twcenter.net/ubs/medieval-2-total-war-modding-tool.26/" target="_blank"
           style="color:var(--accent2)">Fynn’s Medieval II Total War Modding Tool</a> — for the motivation.
      </div>
      <div>
        <div class="lbl" style="margin-bottom:4px">Testing</div>
        <b>Jayzinski</b> and <b>TheHolyPilgrim</b>
      </div>
    </div>
    <div style="padding:0 16px 16px;text-align:right">
      <button class="primary" onclick="closeModal()">Close</button>
    </div>`;
  overlay.classList.add('open');
}
function closeModal(){
  // "…and did they save it?" is half of what makes a log readable
  if(overlay.classList.contains('open')&&undo.past.length)
    activity('closed dialog',`with ${undo.past.length} unsaved change(s)`);
  overlay.classList.remove('open');
  // Closing out of a sub-dialog abandons its stashed scroll: leaving it pending
  // would hand a dead snapshot to whatever re-draws next.
  usePlace(null);
  // the unit editor widens the modal — put it back for the next dialog
  document.getElementById('modal').className='modal';}
