/* settings.js — the settings dialog, M2TWEOP folders, and the log/undo panel

   Part of the Medieval 2 GUI Toolkit UI. These files are plain
   <script> tags sharing ONE global scope, loaded in the order set in
   index.html — there is no build step and no module system. Two rules
   follow from that: a top-level name must be unique across all of
   them, and a file's top-level side effects may not depend on a file
   loaded after it. */
/* ---- new unit: reuses the transfer engine with source == destination ---- */
function openNewUnitPicker(){
  const modal=document.getElementById('modal');
  const d=state.data||{};
  modal.className='modal';
  modal.innerHTML=`<h2>New unit — pick the unit to build it from</h2>
    <div class="mbody">
      <div class="count" style="margin-bottom:8px">The new unit copies the one you pick — same models, icons
        and stats under a new <code>type</code> and <code>dictionary</code>. Nothing is duplicated on disk, and
        you can change any field in the next step.</div>
      <input id="nuSearch" placeholder="Filter units…" style="width:100%" oninput="renderNewUnitList()">
      <div class="barrow" style="margin-bottom:6px">
        <select id="nuFac" onchange="renderNewUnitList()">${
          opts('All factions',(d.factions||[]),facLabel)}</select>
        <select id="nuCat" onchange="renderNewUnitList()">${opts('All categories',d.categories||[])}</select>
        <select id="nuClass" onchange="renderNewUnitList()">${opts('All classes',d.classes||[])}</select>
        <label class="chk"><input type="checkbox" id="nuMerc" onchange="renderNewUnitList()"> mercs only</label>
        <span class="count" id="nuCount"></span>
      </div>
      <div class="baselist" id="nuList" style="max-height:420px"></div>
    </div>
    <div class="foot"><button onclick="closeModal()">Cancel</button></div>`;
  overlay.classList.add('open');
  renderNewUnitList();
}
// A labelled list (factions) is ordered by what it SHOWS, so a picker follows the
// same A→Z as the sidebar; a plain one keeps the order it came in.
// `sel` keeps a picker's choice through a re-render — the armour-tier menu redraws
// on every edit, unlike this dialog, which is built once.
const opts=(allLabel,values,label,sel)=>`<option value="">${allLabel}</option>`+
  (label?[...values].sort((a,b)=>label(a).localeCompare(label(b))):values)
    .map(v=>`<option value="${esc(v)}"${v===sel?' selected':''}>${esc(label?label(v):v)}</option>`).join('');
function renderNewUnitList(){
  const g=id=>(document.getElementById(id)||{}).value||'';
  const qq=g('nuSearch').trim().toLowerCase();
  const fac=g('nuFac'),cat=g('nuCat'),cls=g('nuClass');
  const merc=(document.getElementById('nuMerc')||{}).checked;
  const all=state.data?state.data.units:[];
  const units=all.filter(u=>
    (!qq||u.name.toLowerCase().includes(qq)||u.type.toLowerCase().includes(qq)
      ||u.dictionary.toLowerCase().includes(qq))
    &&(!fac||u.ownership.includes(fac))&&(!cat||u.kind===cat)&&(!cls||u.class===cls)
    &&(!merc||u.mercenary));
  const cnt=document.getElementById('nuCount');
  if(cnt)cnt.textContent=`${units.length}/${all.length}`;
  document.getElementById('nuList').innerHTML=units.slice(0,400).map(u=>`
    <div class="baserow" onclick="startNewUnit('${q1(esc(u.type))}')">
      <img onerror="iconRetry(this)" src="${iconUrl(state.src,u.type)}">
      <div><div>${esc(u.name)}</div><div class="count">${esc(u.type)} · ${esc(u.kind||u.category||'?')}${
        u.class?' / '+esc(u.class):''}${u.mercenary?' · merc':''}</div></div>
    </div>`).join('')||'<div class="count" style="padding:8px">No units match.</div>';
}
function startNewUnit(type){
  state.dst=state.src; state.destData=null;      // same-mod "transfer" = a new unit
  const u=(state.data.units.find(x=>x.type===type)||{});
  const c=cfgFor(type);
  c.on_conflict='rename';
  c.new_type=type+' (new)';
  c.new_dictionary=(u.dictionary||type)+'_new';
  // nothing needs relocating inside one mod: identical models/cards are reused
  c.asset_conflict='use_existing'; c.icon_conflict='use_existing'; c.engine_conflict='use_existing';
  c._resolved=true;
  openComposer([type]);
}

/* ---------- settings ---------- */
async function openSettings(){
  document.getElementById('modal').className='modal';
  const s=await api.get('/api/settings'); state.settings=s;
  const ign=s.unit_limit_ignored||[];
  const ignHtml=ign.length
    ? ign.map(m=>`<div class="ovr"><span><code>${esc(m)}</code></span><button onclick="reenableLimit('${q1(esc(m))}')">Re-enable warning</button></div>`).join('')
    : '<div class="count">None — the 500-unit-limit warning is active for every mod.</div>';
  document.getElementById('modal').innerHTML=`<h2>Settings</h2>
    <div class="mbody">
      <fieldset><legend>Medieval II root folder</legend>
        <div class="count" style="margin-bottom:8px">Point to your Medieval II install (contains <b>mods</b>) or a mods folder directly. Remembered next time.</div>
        <div style="display:flex;gap:6px">
          <input id="rootInput" style="width:100%" value="${esc(s.med2_root||'')}" placeholder="C:\\...\\Total War MEDIEVAL II Definitive Edition">
          <button onclick="autoDetectRoot()">Auto-detect</button>
          <button onclick="browseRoot()">Browse…</button>
        </div>
        <div id="rootStatus" class="count" style="margin-top:8px"></div>
      </fieldset>
      <fieldset><legend>Launcher</legend>
        <label class="chk"><input type="checkbox" id="consoleChk" ${s.show_console?'checked':''} onchange="saveConsole()">
          Keep the console window open <span class="count">(the tool reads this when it starts, so
          it applies from the next launch)</span></label>
        <div class="count" style="margin-top:6px">${docPoints(
          'The launcher always opens a console showing the startup checks and the unit-card conversions.',
          ['Off (default): it closes once that is done.',
           'On: it stays, showing every request.',
           'On any failure it comes back with the reason and stays put.',
           'Everything is logged to <code>config\\\\server.log</code> either way. Checks only: <code>py app.py --check</code>'])}</div>
        <div style="margin-top:8px"><button onclick="restartServer()">↻ Restart now to apply it</button>
          <span class="count">stops the tool and starts it again on the same address — this page comes back
          by itself</span></div>
        <div style="margin-top:8px"><button class="danger" onclick="quitServer()">⏻ Quit server</button>
          <span class="count">stops the tool (needed when running silently)</span></div>
      </fieldset>
      <fieldset><legend>Something went wrong?</legend>
        <div class="count" style="margin-bottom:8px">Everything the tool does is recorded, and the log is where
          both halves of that live: what was written (and the way back out of it), and the detailed diagnostic
          file to send along if the tool did something you didn't expect.</div>
        <div><button onclick="closeModal();openLog()">🕑 Open the log</button>
          <span class="count">the diagnostic download moved in there</span></div>
      </fieldset>
      <fieldset><legend>Transfer defaults</legend>
        <label class="chk"><input type="checkbox" id="soldierBaseChk" ${s.soldier_from_base?'checked':''} onchange="saveSoldierBase()">
          Use the base unit's <b>soldier</b> line by default</label>
        <div class="count" style="margin-top:6px">Start the <b>Soldier</b> row on <b>Base</b>, so the destination unit's model and projectile are used instead of the transferred unit's. Applies to both modes that have a base unit — building a new unit on one, and replacing one (there the base <i>is</i> the unit being replaced, so its own model and animations stay). Still switchable per unit.</div>
      </fieldset>
      <fieldset><legend>Unit-text cache</legend>
        <label class="chk"><input type="checkbox" id="clearBinChk" ${s.clear_strings_bin===false?'':'checked'} onchange="saveClearBin()">
          Clear <code>export_units.txt.strings.bin</code> after every transfer / edit / cleanup</label>
        <div class="count" style="margin-top:6px">The game reads that compiled cache instead of <code>export_units.txt</code>, and only rebuilds it when it's missing — so until it is deleted a new or renamed unit keeps showing its <b>old</b> text. Deleting costs nothing: the next launch writes a fresh one.</div>
        <div class="count" style="margin-top:6px">It is the only file this touches, and it is the same setting as the box at the bottom of every Apply dialog. (It replaced <code>Full Cleaner.bat</code>, which also deleted mod files the game never rebuilds — that script is still in the app folder if you want it.)</div>
      </fieldset>
      <fieldset><legend>Unit-limit warning (500 vanilla cap)</legend>
        <div class="count" style="margin-bottom:8px">Mods where the ${VANILLA_UNIT_LIMIT}-unit warning is suppressed (you confirmed M2TWEOP / EOP is in use):</div>
        ${ignHtml}
      </fieldset>
      <fieldset><legend>M2TWEOP unit folders</legend>
        <div class="count" style="margin-bottom:8px">M2TWEOP loads extra units from its own folder. Those units are
          badged <span class="badge eop">EOP</span> here, edited in place in their own file, and don't count against the
          ${VANILLA_UNIT_LIMIT}-unit cap.</div>
        <div class="count" style="margin-bottom:8px">Left blank, an <code>eopData</code> folder is auto-detected. Set it
          if your mod keeps them elsewhere.</div>
        <div style="display:flex;gap:6px;align-items:center;margin-bottom:8px">
          <select id="eopModSel" onchange="loadEopDirs()" style="max-width:260px">${
            (state.mods||[]).map(m=>`<option value="${esc(m.name)}"${m.name===(state.dst||state.src)?' selected':''}>${esc(m.name)}</option>`).join('')}</select>
          <button onclick="addEopDir()">Add folder…</button>
        </div>
        <div id="eopDirs" class="count">Loading…</div>
      </fieldset>
    </div>
    <div class="foot"><button onclick="closeModal()">Close</button><button class="primary" onclick="saveRoot()">Save & scan</button></div>`;
  overlay.classList.add('open');
  loadEopDirs();
}

/* ---------- M2TWEOP unit folders (per mod) ---------- */
const eopSelMod=()=>{const s=document.getElementById('eopModSel');return s?s.value:'';};
async function eopApi(body){
  const mod=eopSelMod(); if(!mod) return null;
  return api.post('/api/eop_dirs',Object.assign({mod},body||{}));
}
async function loadEopDirs(){
  const box=document.getElementById('eopDirs'); if(!box)return;
  box.textContent='Loading…';
  const r=await eopApi({});
  if(!r||r.error){box.innerHTML=`<span class="w-bad">${esc((r&&r.error)||'could not read')}</span>`;return;}
  const explicit=r.configured.length>0;
  const rows=(explicit?r.configured:r.detected).map(d=>`<div class="ovr"><span><code>${esc(d)}</code></span>${
    explicit?`<button onclick="removeEopDir('${q1(esc(d))}')">Remove</button>`:'<span class="count">auto-detected</span>'}</div>`).join('');
  box.innerHTML=(rows||'<div class="count">No EOP folder found or set — this mod\'s units all live in export_descr_unit.txt.</div>')
    +`<div class="count" style="margin-top:8px"><b>${r.eop_count}</b> M2TWEOP unit(s) in <b>${r.files.length}</b> file(s);
      <b>${r.edu_count}</b> unit(s) in export_descr_unit.txt.</div>`
    +(r.files.length?`<div class="flist" style="margin-top:6px">${r.files.slice(0,40).map(f=>`<div class="frow"><span class="fp">${esc(f)}</span></div>`).join('')}${
       r.files.length>40?`<div class="count">…and ${r.files.length-40} more</div>`:''}</div>`:'')
    +(explicit?'<div class="count" style="margin-top:6px">Remove them all to go back to auto-detection.</div>':'');
}
async function addEopDir(){
  const r=await api.post('/api/browse_folder',{title:'Select the mod’s M2TWEOP unit folder'});
  if(!r.path)return;
  const cur=await eopApi({});
  // an explicit list replaces detection outright, so seed it with what was
  // detected — otherwise adding one folder silently drops the others
  const dirs=(cur.configured.length?cur.configured:cur.detected).slice();
  if(!dirs.includes(r.path)) dirs.push(r.path);
  await eopApi({dirs});
  await refreshMods(state.src,state.dst);
  loadEopDirs();
  toast('EOP folder saved — the mod’s units were re-read.');
}
async function removeEopDir(dir){
  const cur=await eopApi({});
  await eopApi({dirs:(cur.configured||[]).filter(d=>d!==dir)});
  await refreshMods(state.src,state.dst);
  loadEopDirs();
}
async function saveRoot(){const root=document.getElementById('rootInput').value.trim();
  rootStatus.textContent='Scanning…'; await api.post('/api/settings',{med2_root:root});
  const mods=await api.get('/api/mods');
  rootStatus.innerHTML=mods.length?`Found ${mods.length}: ${mods.map(m=>esc(m.name)).join(', ')}`:'<span class="w-bad">No mods under that folder.</span>';
  if(mods.length){await refreshMods(state.src,state.dst);setTimeout(closeModal,700);}
}
async function autoDetectRoot(){
  rootStatus.textContent='Looking up the registry…';
  const r=await api.get('/api/detect_med2_root');
  if(!r.path){rootStatus.innerHTML='<span class="w-bad">Not found in the registry — install not detected. Type or paste the path instead.</span>';return;}
  document.getElementById('rootInput').value=r.path;
  await saveRoot();
}
async function browseRoot(){
  rootStatus.textContent='Opening folder browser…';
  const r=await api.post('/api/browse_folder',{title:'Select your Medieval II Total War folder'});
  if(!r.path){rootStatus.textContent='Cancelled.';return;}
  document.getElementById('rootInput').value=r.path;
  await saveRoot();
}

/* ---------- log ----------
   Everything the tool has done, and the way back out of any of it.

   It is PAGED. The whole log used to arrive in one piece and be turned into
   markup in one piece — 480 entries, 1.1 MB of JSON, 600 KB of HTML for a screen
   that shows about six of them — which is why opening it could take minutes.
   The server now answers with a page and the counts the filter needs. */
const LOG_MODES=[
  {id:'',           label:'Everything'},
  {id:'transfer',   label:'⚔ Transfers'},
  {id:'edit',       label:'✎ Unit edits'},
  {id:'bmdb',       label:'🗄 BMDB'},
  {id:'sounds',     label:'🔊 Sounds'},
  {id:'buildings',  label:'🏰 Buildings'},
  {id:'traits',     label:'🎖 Traits'},
  {id:'ancillaries',label:'🏅 Ancillaries'},
  {id:'factions',   label:'🛡 Factions'},
  {id:'minorfiles', label:'🗺 Minor files'},
  {id:'strings',    label:'🔤 Strings'},
];
// What the panel is showing right now: which mode, and how much of it.
state.logView={mode:'',shown:0,entries:[],total:0,counts:{},grand:0};
const LOG_PAGE=40;
async function openLog(mode){
  const v=state.logView;
  if(mode!==undefined&&mode!==v.mode){v.mode=mode;v.shown=0;v.entries=[];}
  document.getElementById('modal').className='modal';
  overlay.classList.add('open');
  if(!v.entries.length)document.getElementById('modal').innerHTML=
    '<h2>Log</h2><div class="mbody"><div class="count">Reading the log…</div></div>';
  const page=await api.get(`/api/log?mode=${encodeURIComponent(v.mode)}&offset=0`+
    `&limit=${Math.max(LOG_PAGE,v.shown||LOG_PAGE)}`,{label:'Reading the log…'});
  v.entries=page.entries; v.total=page.total; v.counts=page.counts;
  v.grand=page.grand_total; v.shown=v.entries.length;
  renderLog();
}
async function logMore(){
  const v=state.logView;
  const page=await api.get(`/api/log?mode=${encodeURIComponent(v.mode)}`+
    `&offset=${v.shown}&limit=${LOG_PAGE}`,{label:'Reading more of the log…'});
  v.entries=v.entries.concat(page.entries); v.shown=v.entries.length; v.total=page.total;
  renderLog();
}
function renderLog(){
  const v=state.logView;
  const tabs=LOG_MODES.map(m=>{
    const n=m.id?(v.counts[m.id]||0):v.grand;
    if(!n&&m.id)return '';                      // a mode nothing was ever done in
    return `<button class="mftab${v.mode===m.id?' on':''}" onclick="openLog('${m.id}')"
      >${esc(m.label)} <span class="count">${n}</span></button>`;
  }).join('');
  const items=v.entries.map(logItemHtml).join('')
    ||'<div class="empty">Nothing here yet.</div>';
  const left=v.total-v.shown;
  document.getElementById('modal').innerHTML=`<h2>Log</h2>
    <div class="mbody">
      <div class="mftabs">${tabs}</div>
      <div class="trnote">${docPoints('Every write is here, and every one of them can be taken back.',
        ['<b>Undo</b> reverts just that entry.',
         '<b>Revert to here</b> rolls that mod back to how it was at that point, undoing everything newer done to it.',
         'Backed-up files are restored byte for byte, and files that were moved in are removed again.'])}</div>
      ${items}
      ${left>0?`<div style="text-align:center;margin:10px 0">
        <button onclick="logMore()">Show ${Math.min(left,LOG_PAGE)} more</button>
        <span class="count"> ${v.shown} of ${v.total} shown</span></div>`
       :(v.total>LOG_PAGE?`<div class="count" style="text-align:center;margin:10px 0">
          All ${v.total} shown.</div>`:'')}
    </div>
    <div class="foot">
      <button onclick="downloadDiag()" title="The tool's own detailed log: which files it read and parsed, what it found, every file written, backed up, copied or deleted, and what you did along the way (mode opened, mod picked, record opened, field changed). Nothing personal is in it. It holds mod names, values from your mod files, and paths inside your Medieval II folder.">💾 Save diagnostic log</button>
      <span class="count">send it along if the tool did something you didn't expect</span>
      <button onclick="closeModal()">Close</button></div>`;
}
function logItemHtml(e){
  const id=q1(esc(e.id));
  const undoBtn=e.applied&&!e.undone?`<button class="danger" onclick="doUndo('${id}')">Undo</button>`:'';
  const revBtn=e.applied&&!e.undone&&e.newer_count
    ?`<button onclick="doRevert('${id}')" title="Restore “${esc(e.dest)}” to its state at this point (undo everything newer)">⟲ Revert to here (${e.newer_count})</button>`
    :'';
  return `<div class="log-item ${e.undone?'undone':''}">
    <div class="top"><div><b>${esc(e.resolved_type||e.unit_type||'')}</b> <span class="pill">${
      e.mode==='sounds'?`🔊 voice edits in ${esc(e.dest)}`
      :e.mode==='bmdb'?`${e.action==='cleanup'?'🧹 cleaned out of':'🗄 bmdb edit in'} ${esc(e.dest)}`
      :e.mode==='edit'?`${e.action==='delete'?'🗑 deleted in':'✎ edited in'} ${esc(e.dest)}`
      :e.mode&&e.mode!=='transfer'?`${esc(e.mode)} edit in ${esc(e.dest)}`
                     :`${esc(e.source)} → ${esc(e.dest)}`}</span></div>
      <div style="display:flex;gap:8px;align-items:center"><span class="when">${esc(e.when)}</span>
      ${undoBtn}${revBtn}
      ${e.undone?'<span class="pill">undone</span>':(!e.applied?'<span class="pill">not applied</span>':'')}</div></div>
    ${renderSummary(e.summary||'')}${e.summary_cut?`<div class="count">…and ${e.summary_cut}
      more characters, in the diagnostic log.</div>`:''}</div>`;
}
async function doUndo(id){const r=await api.post('/api/undo',{id});if(r.error){toast('Undo error: '+r.error);return;}
  toast('Undone ✓');state.destData=null;openLog();if(state.data)loadSource();}
async function doRevert(id){
  const e=(state.logView.entries||[]).find(x=>x.id===id); if(!e){toast('Log entry not found');return;}
  // counted by the server, which is the only place that has the whole log
  const newer=e.newer_count||0;
  if(!newer){toast('Already at this stage — nothing newer to undo.');return;}
  if(!confirm(`Revert “${e.dest}” to its state right after this transfer?\n\n`+
      `This undoes ${newer} newer transfer(s) to “${e.dest}” (newest first). `+
      `All backed-up files (EDU, localisation, modeldb, overwritten textures) are restored byte-exact and moved-in files are removed.`)) return;
  const r=await api.post('/api/revert',{id});
  if(r.error){toast('Revert error: '+r.error);return;}
  toast(`Reverted to this stage — undid ${r.count} transfer(s) ✓`);
  state.destData=null; openLog(); if(state.data)loadSource();}
