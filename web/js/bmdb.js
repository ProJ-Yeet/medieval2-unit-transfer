/* bmdb.js — BMDB + Sprites Editor mode: the whole battle_models.modeldb as a list

   Part of the Medieval 2 GUI Toolkit UI. These files are plain
   <script> tags sharing ONE global scope, loaded in the order set in
   index.html — there is no build step and no module system. Two rules
   follow from that: a top-level name must be unique across all of
   them, and a file's top-level side effects may not depend on a file
   loaded after it. */
/* =====================================================================
   BMDB MODE — the whole battle_models.modeldb, not one unit's slice of it.

   The list is every entry in the mod; opening one loads it in the SAME model
   card the unit editor uses (server-side it is literally the same payload and
   the same plan engine), so an entry can be edited without going through a unit
   that happens to reference it. Entries nothing references are flagged, and
   "Clean up" moves them — and the files under unit_models nothing mentions —
   out of the mod entirely. */
async function loadBmdb(){
  const mod=state.src;
  // A real mod's modeldb is 30 MB and several seconds to read, parse and
  // cross-reference. The bar is the server's own progress, not a guess — see
  // bmdb.overview's `progress` sink.
  const job=newJob();
  main.innerHTML=`<div class="empty" style="max-width:420px;margin:60px auto">
      <div class="progress-track"><div class="progress-fill" id="jobFill" style="width:0%"></div></div>
      <div class="count" style="margin-top:8px"><b id="jobPct">0%</b>
        <span id="jobStep">reading ${esc(mod)}’s battle_models.modeldb…</span></div>
    </div>`;
  state.bmdbJob=job;
  (async()=>{ while(state.bmdbJob===job){
    await new Promise(r=>setTimeout(r,300));
    if(state.bmdbJob!==job)break;
    // one try, no retries: a dropped poll just means the next one paints instead
    let p=null; try{p=await api.get('/api/progress?job='+enc(job),1);}catch(e){}
    if(state.bmdbJob===job&&p&&typeof p.pct==='number')jobPaint(p.pct,p.label||'');
  }})();
  try{ state.bmdb=await api.get(`/api/bmdb/entries?mod=${enc(mod)}&job=${enc(job)}`); }
  catch(e){ state.bmdbJob=null; if(stale('bmdb',mod))return;
    main.innerHTML=`<div class="empty">Couldn't read the modeldb.<br>
    <span class="count">${esc(''+e)}</span><br><br>
    <button class="primary" onclick="loadBmdb()">Retry</button></div>`; return; }
  finally{ state.bmdbJob=null; }
  if(stale('bmdb',mod))return;          // moved on while this was in flight
  renderBmdb();
}
function renderBmdb(){
  if(!state.bmdb||state.bmdb.mod!==state.src)return loadBmdb();
  const qq=search.value.trim().toLowerCase();
  const rows=state.bmdb.entries.filter(e=>
    (!qq||e.name.includes(qq)||(e.folder||'').toLowerCase().includes(qq)
      ||e.used_by.some(u=>u.toLowerCase().includes(qq)))
    &&(!unusedOnly.checked||e.unused));
  const nUnused=state.bmdb.entries.filter(e=>e.unused).length;
  const dupes=state.bmdb.count-state.bmdb.names;
  count.textContent=`${rows.length}/${state.bmdb.names}`;
  // 2000+ rows of HTML in one go is fine; it's the icons that are expensive and
  // there are none here.
  main.innerHTML=bmdbTabsHtml('data/unit_models/battle_models.modeldb')+`<div class="dbhead">
      <h2>${esc(state.src)} · ${state.bmdb.names} battle-model entries</h2>
      <span class="count">${nUnused} referenced by nothing${
        nUnused?' — <b class="w-warn">🧹 Clean up BMDB…</b> moves them out':''}${
        dupes?` · ${dupes} duplicate entry block${dupes===1?'':'s'} share a name with another`:''}</span>
    </div>
    ${rows.length?`<div class="dblist">${rows.map(bmdbRow).join('')}</div>`
                 :'<div class="empty">No entries match.</div>'}`;
  main.querySelectorAll('.dbrow').forEach(r=>r.onclick=()=>openBmdbEntry(r.dataset.name));
}
function bmdbRow(e){
  const use=e.unused?'<span class="w-warn">nothing references it</span>'
    :e.mentioned_in?`<span class="count">no unit uses it — ${e.mentioned_in_lua
        ?'named by a <b class="w-good">Lua script</b>':'only named in'} <code>${esc(e.mentioned_in)}</code></span>`
    :`${esc(e.used_by.slice(0,4).join(', '))}${e.use_count>4?` +${e.use_count-4} more`:''}`;
  return `<div class="dbrow ${e.unused?'unused':''}" data-name="${esc(e.name)}">
    <span class="en">${esc(e.name)}${e.copies>1?`<span class="badge w-warn" style="margin-left:5px"
      title="the modeldb holds this name ${e.copies} times">×${e.copies}</span>`:''}</span>
    <span class="use">${use}</span>
    <span class="nums">${e.lods} LOD${e.lods===1?'':'s'} · ${e.skins} skin${e.skins===1?'':'s'}</span>
  </div>`;
}
// Opening an entry builds exactly the state the unit editor's model tab runs on,
// with a one-entry `models` list and no unit — so edModels(), the faction
// checklist, the folder box and "＋ New entry from this" all work unchanged.
async function openBmdbEntry(name){
  const modal=document.getElementById('modal');
  modal.className='modal wide'; modal.innerHTML='<h2>Loading entry…</h2>';
  overlay.classList.add('open');
  let r;
  try{ r=await api.get(`/api/bmdb/entry?mod=${enc(state.src)}&name=${enc(name)}`); }
  catch(e){ r={error:''+e}; }
  if(r.error){ modal.innerHTML=`<h2>Battle model</h2><div class="mbody w-bad">${esc(r.error)}</div>
    <div class="foot"><button onclick="closeModal()">Close</button></div>`; return; }
  state.ed={bmdb:true,mod:state.src,unit:'',tab:'models',ov:{},rm:new Set(),added:new Set(),
    loc:{},newType:'',newDict:'',mEdits:{},newModels:[],open:{[r.model.name]:true},form:null,
    facOpen:{},folder:{},
    d:{type:'',dictionary:'',fields:[],loc:{},models:[r.model],model_names:r.model_names,
       all_factions:r.all_factions,faction_names:r.faction_names,
       unknown_factions:r.unknown_factions}};
  undoReset();
  resetPlace();
  renderBmdbEditor();
  if(state.settings.code_view){
    const e=state.ed;
    e.cv=cvCreate(bmCvHost());
    cvLoad(e.cv).then(()=>{if(state.ed===e&&e.cv)renderBmdbEditor();});
  }
}

/* ======================= CODE VIEW on the bmdb editor =====================
   The same widget again (web/js/codeview.js), pointed at the `bmdb` kind.

   This is the one record whose text carries bookkeeping nobody should be asked
   to type: a modeldb string is stored as `<length> <that many characters>`, so
   retyping a path leaves the number beside it wrong and desyncs the reader for
   everything after. The pane therefore refuses such text — naming the line and
   the number it should be — and offers ⟲ Fix lengths, which is the only kind
   with a repair. */
const bmCvEdited=()=>{const cv=state.ed&&state.ed.cv;
  return !!(cv&&cv.kind==='bmdb'&&cv.loaded&&cv.owns);};
function bmCvToggleHtml(){
  return `<button class="${state.ed.cv?'on':''}" title="Show this entry exactly as
battle_models.modeldb stores it, beside the boxes."
    onclick="bmCvToggle()">&lt;/&gt; Code view</button>`;
}
async function bmCvToggle(){
  const e=state.ed;
  if(e.cv){cvDrop(e.cv); e.cv=null; state.settings.code_view=false;
    api.post('/api/settings',{code_view:false}); renderBmdbEditor(); return;}
  state.settings.code_view=true; api.post('/api/settings',{code_view:true});
  e.cv=cvCreate(bmCvHost());
  renderBmdbEditor();
  await cvLoad(e.cv);
  if(state.ed===e&&e.cv)renderBmdbEditor();
}
/* `name` picks which of the open editor's models the pane shows. The BMDB mode
   has exactly one and leaves it out; the unit editor has several, and its Models
   tab points a pane at whichever card is open. Everything else is the same, and
   there is only one implementation of it. */
const bmModel=name=>(state.ed.d.models||[]).find(m=>m.name===name)||state.ed.d.models[0];
function bmCvHost(name,gui,redraw){
  const e=state.ed,m=bmModel(name);
  const guiId=gui||'bmGui', paint=redraw||renderBmdbEditor;
  return {kind:'bmdb', mod:e.mod, id:m.name,
    where:'data/unit_models/battle_models.modeldb',
    // the same ModelEdit the save sends, minus the parts that are not text in
    // this entry (imported files, folder moves) — the pane can only show text
    edits:()=>{const me=(state.ed.mEdits[m.name])||{};
      return {paths:me.paths||{}, new_name:me.new_name||''};},
    adopt:cv=>{
      // The whole card is rebuilt from the re-read text — typing can add or drop
      // a faction record, which patching slot by slot would not survive. What
      // the card knows and the entry does not (who else uses it, which EDU slot
      // points here) is carried across.
      if(!cv.detail)return;
      const s=state.ed,i=(s.d.models||[]).findIndex(x=>x.name===m.name);
      if(i<0)return;
      const was=s.d.models[i];
      s.d.models[i]=Object.assign(cv.detail,
        {slots:was.slots, used_by:was.used_by, shared:was.shared});
      // box edits are now folded into the text and must not be applied twice
      const me=s.mEdits[was.name];
      if(me){me.paths={}; me.defaults={}; me.faction_paths={}; me.factions=null;}},
    refreshGui:()=>{paint(); cvBindHover(bmCvOf(m.name),document.getElementById(guiId));},
    label:el=>bmCvLabel(el,m.name), find:l=>bmCvFind(l,guiId)};
}
// whichever live view is pointed at this entry — the BMDB dialog's or the unit
// editor's Models tab
const bmCvOf=name=>{const e=state.ed;
  return (e.mcv&&e.mcvName===name)?e.mcv:e.cv;};
// The boxes already carry what they edit: a LOD mesh its span index, a texture
// its faction and kind. Both are exactly how entry_spans labels its lines.
function bmCvLabel(el,name){
  if(!el||!el.closest)return '';
  const idx=el.closest('[data-i]');
  if(idx&&idx.dataset.entry)return 'path#'+idx.dataset.i;
  const fac=el.closest('[data-fac]');
  if(fac)return 'fac:'+fac.dataset.f+':'+fac.dataset.kind;
  // a default box stands for that kind in EVERY faction record
  const def=el.closest('[data-def]');
  if(def){
    const m=bmModel(name),k=def.dataset.kind;
    return (m.factions||[]).map(f=>'fac:'+f+':'+k);
  }
  const nm=el.closest('[data-rename]');
  return nm?'name':'';
}
function bmCvFind(label,guiId){
  const root='#'+(guiId||'bmGui');
  const m=/^path#(\d+)$/.exec(label);
  if(m)return [...document.querySelectorAll(`${root} [data-i="${m[1]}"]`)];
  const f=/^fac:([^:]*):(.+)$/.exec(label);
  if(f)return [...document.querySelectorAll(
    `${root} [data-f="${cssq(f[1])}"][data-kind="${cssq(f[2])}"]`)];
  if(label==='name')return [...document.querySelectorAll(`${root} [data-rename]`)];
  return [];
}

function renderBmdbEditor(){
  const e=state.ed,m=e.d.models[0];
  document.getElementById('modal').innerHTML=`
    <h2>Battle model <span class="pill">${esc(e.mod)}</span></h2>
    <div class="ehead">
      <div><div class="nm" style="font-family:ui-monospace,Consolas,monospace">${esc(m.name)}</div>
        <div class="count">${m.lods.length} LOD${m.lods.length===1?'':'s'} ·
          ${m.factions.length} faction skin${m.factions.length===1?'':'s'} ·
          ${m.used_by.length?`used by ${m.used_by.length}`:'<span class="w-warn">referenced by nothing</span>'}</div></div>
    </div>
    <div class="cvsplit${e.cv?'':' off'}" style="padding:0 14px">
      <div id="bmGui"><div class="mbody" id="edBody" style="padding:0"></div></div>
      ${e.cv?`<div id="bmCodeCol" style="padding-top:12px">${cvHtml(e.cv)}</div>`:''}
    </div>
    <div class="foot">
      <span id="edDirtyNote"></span>
      ${bmCvToggleHtml()}
      <span class="count" title="Takes back one value at a time, without closing this dialog">
        ⌨ Ctrl+Z undo · Ctrl+Y redo</span>
      ${cleanerBoxHtml()}
      <button onclick="closeModal()">Close</button>
      <button onclick="edPreview()">Preview</button>
      <button class="primary" onclick="edSave()">Save changes</button>
    </div>`;
  edRenderTab();
  if(e.cv){cvWire(e.cv); cvBindHover(e.cv,document.getElementById('bmGui'));}
}

/* ---- who uses this entry ----
   Closed by default and only counted in the header: an entry a hundred units
   share would otherwise push the thing you came to edit off the screen. Opened,
   every user is a card with its own icon, and clicking one opens that unit in a
   new browser tab — so following "this model is also used by X" never costs you
   the edits in the tab you are in. */
function edUsersOpen(){ return !!(state.ed&&state.ed.usersOpen); }
function edToggleUsers(){ state.ed.usersOpen=!edUsersOpen(); edRenderTab(); }
function edUsersFilter(v){ state.ed.usersQ=v; edRenderTab(); }
function edEntryUsers(m){
  if(!m)return '';
  const all=m.used_by||[];
  const q=((state.ed.usersQ)||'').trim().toLowerCase();
  const index=Object.fromEntries(((state.data&&state.data.units)||[]).map(u=>[u.type.toLowerCase(),u]));
  const rows=all.filter(w=>!q||w.toLowerCase().includes(q));
  return `<div class="bsec edusers"><h4>
      <button class="usertog" onclick="edToggleUsers()">${edUsersOpen()?'▾':'▸'}
        Used by <span class="n">${all.length}</span></button>
      ${all.length?'<span class="count">every unit, mount and file that names this entry</span>'
                  :'<span class="count w-warn">nothing in the mod references it</span>'}
      ${edUsersOpen()&&all.length>8?`<input class="mini" style="margin-left:auto;max-width:200px"
        placeholder="Filter…" value="${esc(state.ed.usersQ||'')}"
        oninput="edUsersFilter(this.value)">`:''}</h4>
    ${edUsersOpen()&&all.length?`<div class="usergrid">${rows.map(w=>{
      const other=/^(mount|file):/.test(w);
      const u=index[w.toLowerCase()];
      return `<div class="ucell ${other?'plain':''}"
        ${other?'':`onclick="openUnitTab('${q1(esc(w))}')" title="Open ${esc(w)} in a new tab"`}>
        ${other?'<div class="ic none">—</div>'
               :`<img loading="lazy" onerror="iconRetry(this)" src="${iconUrl(state.ed.mod,w)}" alt="">`}
        <div class="un">${esc(u?u.name:short(w))}</div>
        <div class="ut">${esc(other?w.split(':')[0]:(u?(u.kind||u.category||w):w))}</div>
      </div>`;}).join('')||'<span class="count">Nothing matches.</span>'}</div>`:''}
  </div>`;
}
const short=w=>w.replace(/^(mount|file):/,'');
