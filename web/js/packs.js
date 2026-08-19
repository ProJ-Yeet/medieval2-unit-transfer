/* packs.js — unit packs — units in a zip you can send someone

   Part of the Medieval 2 GUI Toolkit UI. These files are plain
   <script> tags sharing ONE global scope, loaded in the order set in
   index.html — there is no build step and no module system. Two rules
   follow from that: a top-level name must be unique across all of
   them, and a file's top-level side effects may not depend on a file
   loaded after it. */
/* =========================================================================
   Unit packs — units in a zip you can send someone

   Export builds a miniature mod: the units' EDU blocks, their modeldb entries,
   the meshes, textures and icons those name, and whatever descr_* blocks they
   reach for. Import mounts that zip as an ordinary source mod and then gets out
   of the way: the source dropdown switches to it and every existing screen —
   the composer, the base picker, conflicts, preview, Save, the undo log — works
   on it unchanged. There is no separate "import" screen to keep in step with
   the transfer one, because the import IS a transfer.
   ========================================================================= */
const MBs=n=>(n/1048576).toFixed(1)+' MB';
async function packExport(types){
  if(!types.length)return toast('Tick some units first.');
  const modal=document.getElementById('modal');
  modal.className='modal';
  overlay.classList.add('open');
  modal.innerHTML=`<h2>Export ${types.length} unit${types.length===1?'':'s'} as a pack</h2>
    <div class="mbody"><div class="empty">Working out what has to travel…</div></div>
    <div class="foot"><button onclick="closeModal()">Cancel</button></div>`;
  let r;
  try{ r=await api.post('/api/pack/plan',{mod:state.src,units:types}); }
  catch(e){ r={error:''+e}; }
  if(r.error){ modal.querySelector('.mbody').innerHTML=`<div class="w-bad">${esc(r.error)}</div>`; return; }
  state.pack={mod:state.src,types,plan:r};
  packExportRender();
}
function packExportRender(){
  const p=state.pack.plan;
  document.getElementById('modal').innerHTML=`<h2>Export ${p.units.length} unit${
      p.units.length===1?'':'s'} as a pack <span class="pill">${esc(state.pack.mod)}</span></h2>
    <div class="mbody">
      <div class="sum">
        <div class="srow"><span class="sicon">•</span><span class="stext">
          ${p.units.map(t=>`<code>${esc(t)}</code>`).join(', ')}</span></div>
        <div class="srow"><span class="sicon">•</span><span class="stext">
          ${p.models.length} battle-model entr${p.models.length===1?'y':'ies'},
          ${p.assets} mesh/texture file${p.assets===1?'':'s'}, ${p.icons} icon${p.icons===1?'':'s'}</span></div>
        ${p.mounts.length?`<div class="srow"><span class="sicon">•</span><span class="stext">
          mount${p.mounts.length===1?'':'s'}: ${p.mounts.map(m=>`<code>${esc(m)}</code>`).join(', ')}</span></div>`:''}
        ${p.projectiles.length?`<div class="srow"><span class="sicon">•</span><span class="stext">
          projectile${p.projectiles.length===1?'':'s'}: ${p.projectiles.map(m=>`<code>${esc(m)}</code>`).join(', ')}</span></div>`:''}
        ${p.engines.length?`<div class="srow"><span class="sicon">•</span><span class="stext">
          engine${p.engines.length===1?'':'s'}: ${p.engines.map(m=>`<code>${esc(m)}</code>`).join(', ')}</span></div>`:''}
        <div class="srow"><span class="sicon">→</span><span class="stext">
          about ${MBs(p.bytes)} of art before compression</span></div>
        ${(p.missing||[]).map(t=>`<div class="srow bad"><span class="sicon">✕</span>
          <span class="stext">${esc(t)} is not in this mod</span></div>`).join('')}
        ${(p.warnings||[]).map(w=>`<div class="srow warn"><span class="sicon">!</span>
          <span class="stext">${esc(w)}</span></div>`).join('')}
      </div>
      <div class="bnote">The zip is a miniature mod. Whoever you send it to opens the toolkit,
        picks the mod they want the units in and hits <b>📦 Import pack…</b> — the import runs the
        same checks, renames and options a normal transfer does. Voices are not carried: an
        imported unit is given a voice from the receiving mod, which is the only kind that will
        actually play there.</div>
      <div id="packResult"></div>
    </div>
    <div class="foot">
      <button onclick="closeModal()">Cancel</button>
      <button class="primary" ${p.units.length?'':'disabled'} onclick="packWrite()">
        Choose where to save…</button></div>`;
}
async function packWrite(){
  const p=state.pack;
  const name=(p.plan.units.length===1?p.plan.units[0]:`${p.mod}-${p.plan.units.length}-units`)
    .replace(/[^A-Za-z0-9_.-]+/g,'_')+'.zip';
  const pick=await api.post('/api/browse_save',
    {title:'Save the unit pack',filter:'Unit pack (*.zip)|*.zip|All files (*.*)|*.*',
     name,ext:'zip'});
  if(!pick.path)return;                       // cancelled
  const box=document.getElementById('packResult');
  box.innerHTML='<div class="count" style="padding:8px">Writing the pack…</div>';
  let r;
  try{ r=await api.post('/api/pack/write',{mod:p.mod,units:p.types,path:pick.path}); }
  catch(e){ r={error:''+e}; }
  if(r.error){ box.innerHTML=`<div class="mbody w-bad">${esc(r.error)}</div>`; return; }
  const rec=r.record;
  box.innerHTML=`<div class="sum" style="margin-top:10px">
    <div class="srow good"><span class="sicon">✓</span><span class="stext">
      Wrote <code>${esc(rec.path)}</code> — ${rec.files} file(s), ${MBs(rec.bytes)}</span></div></div>`;
  toast(`Pack written: ${rec.path}`,5000);
}

async function packImport(){
  const pick=await api.post('/api/browse_file',
    {title:'Open a unit pack',filter:'Unit pack (*.zip)|*.zip|All files (*.*)|*.*'});
  if(!pick.path)return;
  const modal=document.getElementById('modal');
  modal.className='modal';
  overlay.classList.add('open');
  modal.innerHTML=`<h2>Import a unit pack</h2>
    <div class="mbody"><div class="empty">Opening the pack…</div></div>
    <div class="foot"><button onclick="closeModal()">Cancel</button></div>`;
  let r;
  try{ r=await api.post('/api/pack/open',{path:pick.path}); }
  catch(e){ r={error:''+e}; }
  if(r.error){ modal.querySelector('.mbody').innerHTML=`<div class="w-bad">${esc(r.error)}</div>`; return; }
  state.packIn=r;
  packImportRender();
}
function packImportRender(){
  const r=state.packIn,m=r.manifest||{};
  document.getElementById('modal').innerHTML=`<h2>Import a unit pack</h2>
    <div class="mbody">
      <div class="count" style="margin-bottom:8px">
        <code>${esc(r.path)}</code> · ${MBs(r.bytes)}${
        m.source_mod?` · made from <b>${esc(m.source_mod)}</b>`:''}${
        m.created?` on ${esc(m.created)}`:''}</div>
      ${r.has_manifest?'':`<div class="warnbox">This zip carries no <code>unitpack.json</code>.
        It still looks like a mod, so it can still be imported — just be sure you know where
        it came from.</div>`}
      <div class="baselist" style="max-height:280px">${r.units.map(u=>`
        <div class="baserow">
          <div><div class="bn">${esc(u.name)}${u.has_card?'':' <span class="badge">no card</span>'}</div>
            <div class="bs">${esc(u.type)} · ${esc([u.kind,u.class].filter(Boolean).join(' · '))}${
              u.mount?` · rides <code>${esc(u.mount)}</code>`:''}</div></div>
        </div>`).join('')||'<div class="caprow"><span class="count">This pack names no units.</span></div>'}</div>
      <div class="bnote">${r.entries.length} battle-model entr${r.entries.length===1?'y':'ies'} travel with them.
        Importing mounts the pack as a source mod and drops you in the normal transfer screen, so
        name clashes, the base unit, ownership and every other option are asked there — nothing is
        written until you press Transfer.</div>
    </div>
    <div class="foot">
      <button onclick="closeModal()">Cancel</button>
      <button class="primary" ${r.units.length?'':'disabled'} onclick="packMount()">
        Open ${r.units.length} unit${r.units.length===1?'':'s'} for transfer</button></div>`;
}
async function packMount(){
  const r=state.packIn;
  let info;
  try{ info=await api.post('/api/pack/mount',{path:r.path}); }
  catch(e){ info={error:''+e}; }
  if(info.error)return toast(info.error,5000);
  closeModal();
  // From here it is an ordinary transfer: the pack is just another source mod.
  state.mode='transfer';
  await refreshMods(info.name,state.dst===info.name?null:state.dst);
  state.src=info.name; srcSel.value=info.name;
  applyMode(true);
  await loadSource();
  toast(`Pack opened as “${info.name}”. Pick the units and transfer them into ${state.dst} `
       +'exactly as you would from any other mod.',6000);
}

/* ---- clean-up: what nothing uses, and where to put it ---- */
async function openCleanup(){
  const modal=document.getElementById('modal');
  modal.className='modal wide';
  overlay.classList.add('open');
  const job=newJob();
  let a;
  try{ a=await runJob(job,`Clean up ${esc(state.src)}’s BMDB`,
        `Scanning every entry, every unit that names one, and every file under
         <code>data/unit_models</code>… (a big mod takes a few seconds)`,
        ()=>api.get(`/api/bmdb/audit?mod=${enc(state.src)}&job=${enc(job)}`)); }
  catch(e){ a={error:''+e}; }
  if(a.error){ modal.innerHTML=`<h2>Clean up</h2><div class="mbody w-bad">${esc(a.error)}</div>
    <div class="foot"><button onclick="closeModal()">Close</button></div>`; return; }
  state.clean={a,target:state.settings.last_cleanup_target||'',
    entries:new Set(a.unused.map(u=>u.entry)),     // unused: pre-ticked, they are dead by definition
    merges:new Set(),                              // suggestions: never pre-ticked, they change a model
    into:Object.fromEntries(a.merges.map(m=>[m.entry,m.into])),
    orphans:new Set(a.orphans.map(o=>o.rel)),
    mounts:new Set(),                              // rewrites descr_mount.txt: opt in by hand
    open:{unused:true,merges:true,mounts:false,orphans:false},plan:null};
  resetPlace();
  renderCleanup();
}
const MB=n=>(n/1048576).toFixed(1)+' MB';
function renderCleanup(){
  const c=state.clean,a=c.a;
  // The counts get their own node: ticking a row must not re-render the lists
  // (a big mod has 3000+ file rows and rebuilding them per click is unusable).
  const sec=(k,title,body)=>`<div class="clsec">
      <div class="h" onclick="clToggle('${k}')"><span>${c.open[k]?'▾':'▸'}</span>
        <b>${title}</b><span class="count" id="clc_${k}">${clCountText(k)}</span></div>
      ${c.open[k]?`<div class="b">${body()}</div>`:''}</div>`;
  document.getElementById('modal').innerHTML=`
    <h2>Clean up ${esc(a.mod)}’s battle_models.modeldb</h2>
    <div class="mbody">
      <div class="count" style="margin-bottom:10px">${a.entry_count} entries scanned. Nothing is deleted —
        everything ticked is <b>moved</b> into the folder below, in the mod's own layout, so it can be
        pasted straight back. Undoable from 🕑 Log.</div>

      <fieldset><legend>Where the removed assets go</legend>
        <div class="cltarget">
          <input id="clTarget" value="${esc(c.target)}" placeholder="e.g. D:\\M2TW backups\\${esc(a.mod)}_unused"
            oninput="state.clean.target=this.value;clStale()">
          <button onclick="clPickTarget()">Browse…</button>
        </div>
        <div class="treebox">${esc(a.mod)}_unused\\
  removed_battle_models.modeldb   <span style="color:var(--dim)">— only the entries that were removed</span>
  removed_mounts.txt              <span style="color:var(--dim)">— the descr_mount.txt blocks that were removed</span>
  data\\unit_models\\…              <span style="color:var(--dim)">— their meshes/textures, same paths as in the mod</span>
  unused_files\\data\\unit_models\\… <span style="color:var(--dim)">— files no entry mentions at all</span></div>
        <div class="count" style="margin-top:6px">Must be outside the mod, or the files never really leave it.</div>
      </fieldset>

      ${sec('unused','Entries nothing references',()=>clUnusedBody())}
      ${sec('merges','Soldier-only entries with an identical twin',()=>clMergeBody())}
      ${sec('mounts','Mounts no unit rides',()=>clMountBody())}
      ${sec('orphans','Files under unit_models no entry mentions',()=>clOrphanBody())}

      ${clLuaBox(a)}
      ${a.mentioned.length?`<div class="count">${a.mentioned.length} more entr${
        a.mentioned.length===1?'y is':'ies are'} used by no unit but named in another file
        (<code>${[...new Set(a.mentioned.map(m=>m.file))].slice(0,4).map(esc).join('</code>, <code>')}</code>)
        — left alone.</div>`:''}
      ${a.mentioned_mounts.length?`<div class="count">${a.mentioned_mounts.length} mount${
        a.mentioned_mounts.length===1?' is':'s are'} ridden by no unit but still named in a
        <code>descr_*.txt</code> — not offered above.</div>`:''}
      ${a.campaign_files.length?`<div class="count">Campaign files also read for
        <code>battle_model</code> references:
        <code>${a.campaign_files.map(esc).join('</code>, <code>')}</code>.</div>`:''}
      <div id="clPreview"></div>
    </div>
    <div class="foot">
      ${cleanerBoxHtml()}
      <button onclick="closeModal()">Close</button>
      <button onclick="clPreview()">Preview</button>
      <button class="primary" onclick="clApply()">Move them out</button>
    </div>`;
}
function clToggle(k){state.clean.open[k]=!state.clean.open[k];renderCleanup();}
function clStale(){const b=document.getElementById('clPreview');
  if(b&&state.clean.plan){state.clean.plan=null;b.innerHTML='';}}
async function clPickTarget(){
  const r=await api.post('/api/browse_folder',{title:'Folder to move the unused assets into'});
  if(!r.path)return;
  state.clean.target=r.path; clStale(); renderCleanup();
  state.settings.last_cleanup_target=r.path;      // so reopening the dialog offers it again
  api.post('/api/settings',{last_cleanup_target:r.path});
}
/* What the Lua pass protected. Its own box rather than a line in the "named in
   another file" note, because this is the safety net people do not know exists:
   an M2TWEOP script names battle models by string and nothing in the mod's .txt
   files records that, so without it the cleanup would delete a model the campaign
   uses and the break would only show up in game. */
function clLuaBox(a){
  const kept=a.lua_kept||[];
  const scanned=a.lua_files||0;
  if(!scanned) return '';
  if(!kept.length) return `<div class="count">Read <b>${scanned}</b> <code>.lua</code> script${
    scanned===1?'':'s'} in the mod — none of them names a battle-model entry, so nothing was held back for that.</div>`;
  const rows=kept.slice(0,60).map(m=>`<div class="frow"><span class="fp">${esc(m.entry)}</span><span class="fs">${
    esc(m.file)}${m.in_comment?' — in a comment, still protected':''}</span></div>`).join('');
  return `<fieldset class="assetconf" style="margin-top:10px;border-color:var(--good)">
    <legend class="w-good">Protected by the mod's Lua scripts</legend>
    <div class="count"><b>${kept.length}</b> entr${kept.length===1?'y is':'ies are'} named by one of this mod's
      <b>${scanned}</b> <code>.lua</code> script${scanned===1?'':'s'} and nothing else. Deleting
      ${kept.length===1?'it':'them'} would break that script, so ${kept.length===1?'it is':'they are'} not
      offered for removal.</div>
    <div class="flist" style="margin-top:6px">${rows}${
      kept.length>60?`<div class="count">…and ${kept.length-60} more</div>`:''}</div>
  </fieldset>`;
}
function clUnusedBody(){
  const c=state.clean,rows=c.a.unused;
  if(!rows.length)return '<div class="count" style="margin-top:8px">Nothing — every entry is referenced. 🎉</div>';
  return `<div class="count" style="margin-top:7px">No unit, mount or character in this mod names these.
      Their files move out too, unless an entry that stays also uses them.</div>
    <div class="clbar">
      <button onclick="clAll('entries',true)">Select all</button>
      <button onclick="clAll('entries',false)">None</button></div>
    <div class="cllist">${rows.map(u=>`<div class="clrow">
      <input type="checkbox" ${c.entries.has(u.entry)?'checked':''}
        onchange="clPick('entries','${q1(esc(u.entry))}',this.checked)">
      <div class="grow"><span class="nm">${esc(u.entry)}</span>${u.copies>1?`
        <span class="badge w-warn">×${u.copies} copies of this name — all go</span>`:''}
        <div class="sub">${u.lods} LOD${u.lods===1?'':'s'} · ${u.skins} skin${u.skins===1?'':'s'} ·
          ${u.files.length} file${u.files.length===1?'':'s'} named, ${u.on_disk} on disk</div></div>
    </div>`).join('')}</div>`;
}
/* Suggestions, never decisions: the twin has the same animations, skeletons and
   torch block, but its meshes and textures are its own — so every row is ticked
   by hand (or with "Agree to all" once you have read them). */
function clMergeBody(){
  const c=state.clean,rows=c.a.merges;
  if(!rows.length)return '<div class="count" style="margin-top:8px">None found.</div>';
  return `<div class="count" style="margin-top:7px">
      Each of these is used only by a unit's <code>soldier</code> line and has a twin with the same
      footer (animations, skeletons, torch), so the line can point at the twin instead.
      <b>Check each pair first</b> — the twin's meshes and textures are its own.</div>
    <div class="clbar">
      <button onclick="clAll('merges',true)">Agree to all</button>
      <button onclick="clAll('merges',false)">None</button></div>
    <div class="cllist">${rows.map(m=>{
      const risky=m.units_without_upgrades.length;
      return `<div class="clrow ${risky?'risky':''}">
      <input type="checkbox" ${c.merges.has(m.entry)?'checked':''}
        onchange="clPick('merges','${q1(esc(m.entry))}',this.checked)">
      <div class="grow">
        <span class="nm">${esc(m.entry)}</span> →
        <select onchange="clInto('${q1(esc(m.entry))}',this.value)">
          ${m.options.map(o=>`<option value="${esc(o)}" ${c.into[m.entry]===o?'selected':''}>${esc(o)}</option>`).join('')}
        </select>
        <span class="badge" id="clOwn_${esc(m.entry)}" style="color:var(--good);border-color:var(--good)${
          clIsOwn(m,c.into[m.entry])?'':';display:none'}">already an armour tier of the same unit</span>
        <div class="sub">soldier of ${m.units.map(u=>userLink(u)).join(', ')}
          · ${m.lods} LOD${m.lods===1?'':'s'}, ${m.files.length} file${m.files.length===1?'':'s'}</div>
        ${risky?`<div class="sub w-warn">⚠ ${esc(m.units_without_upgrades.join(', '))}
          list no armour_ug_models, so this entry IS what you see on the field — swapping it
          changes how the unit looks.</div>`:''}
      </div></div>`;}).join('')}</div>`;
}
/* "already an armour tier of the same unit" is a fact about the PICKED twin, not
   about the row — the picker offers up to 12, and only some of them are models the
   unit already draws. So the badge is re-evaluated on every change instead of being
   frozen at whatever the server suggested. */
const clIsOwn=(m,into)=>(m.own_options||[]).includes(into);
function clInto(entry,into){
  const c=state.clean;
  c.into[entry]=into;
  const row=c.a.merges.find(m=>m.entry===entry),b=document.getElementById('clOwn_'+entry);
  if(row&&b)b.style.display=clIsOwn(row,into)?'':'none';
  clStale();
}
/* A mount nothing rides is dead weight in descr_mount.txt, and its model entry is
   usually alive for that reason alone — so ticking one here is what lets the entry
   go too (that is what "frees ..." means on the row). Not pre-ticked: this is the
   one part of the cleanup that rewrites descr_mount.txt. */
function clMountBody(){
  const c=state.clean,rows=c.a.unused_mounts;
  if(!rows.length)return '<div class="count" style="margin-top:8px">None — every mount is ridden by a unit.</div>';
  return `<div class="count" style="margin-top:7px">No unit rides these, so their
      <code>descr_mount.txt</code> blocks do nothing. Ticking one removes the block and frees its
      modeldb entry if nothing else uses the model. Removed blocks are saved to
      <code>removed_mounts.txt</code>.</div>
    <div class="clbar">
      <button onclick="clAll('mounts',true)">Select all</button>
      <button onclick="clAll('mounts',false)">None</button></div>
    <div class="cllist">${rows.map(m=>`<div class="clrow">
      <input type="checkbox" ${c.mounts.has(m.mount)?'checked':''}
        onchange="clPick('mounts','${q1(esc(m.mount))}',this.checked)">
      <div class="grow"><span class="nm">${esc(m.mount)}</span>
        ${m.class?`<span class="badge">${esc(m.class)}</span>`:''}
        ${m.frees_model?`<span class="badge" style="color:var(--good);border-color:var(--good)">frees ${esc(m.model)}</span>`:''}
        <div class="sub">model <code>${esc(m.model||'(none)')}</code>${
          m.in_db?'':' <span class="w-warn">— not in the modeldb</span>'}</div>
        ${!m.frees_model&&m.kept_by.length?`<div class="sub">its model stays: still used by
          ${esc(m.kept_by.join(', '))}</div>`:''}
        ${!m.frees_model&&!m.kept_by.length&&m.mentioned_in?`<div class="sub">its model stays:
          named in <code>${esc(m.mentioned_in)}</code></div>`:''}
      </div></div>`).join('')}</div>`;
}
function clOrphanBody(){
  const c=state.clean,rows=c.a.orphans;
  if(!rows.length)return '<div class="count" style="margin-top:8px">None — every file under unit_models is named by an entry.</div>';
  return `<div class="count" style="margin-top:7px">Files sitting in <code>data/unit_models</code> that
      <b>no</b> modeldb entry names — removed ones or not. They go to
      <code>unused_files\\</code> in the destination, paths mirrored.</div>
    <div class="clbar">
      <button onclick="clAll('orphans',true)">Select all</button>
      <button onclick="clAll('orphans',false)">None</button></div>
    <div class="cllist">${rows.map(o=>`<div class="clrow">
      <input type="checkbox" ${c.orphans.has(o.rel)?'checked':''}
        onchange="clPick('orphans','${q1(esc(o.rel))}',this.checked)">
      <div class="grow"><span class="sub" style="margin:0">${esc(o.rel)}</span></div>
      <span class="count">${MB(o.size)}</span></div>`).join('')}</div>`;
}
function clCountText(k){
  const c=state.clean,a=c.a;
  if(k==='unused')return `${c.entries.size}/${a.unused.length} ticked`;
  if(k==='merges')return `${c.merges.size}/${a.merges.length} ticked · needs your eye`;
  if(k==='mounts'){
    const frees=a.unused_mounts.filter(m=>c.mounts.has(m.mount)&&m.frees_model).length;
    return `${c.mounts.size}/${a.unused_mounts.length} ticked${frees?` · frees ${frees} entr${frees===1?'y':'ies'}`:''}`;
  }
  const bytes=a.orphans.reduce((n,o)=>n+(c.orphans.has(o.rel)?o.size:0),0);
  return `${c.orphans.size}/${a.orphans.length} ticked · ${MB(bytes)}`;
}
function clCounts(){['unused','merges','mounts','orphans'].forEach(k=>{
  const el=document.getElementById('clc_'+k); if(el)el.textContent=clCountText(k);});}
// The checkbox already shows its own new state, so only the header count needs
// touching — that keeps ticking one of 3000 rows instant.
function clPick(key,id,on){const s=state.clean[key]; on?s.add(id):s.delete(id);
  clStale(); clCounts();}
function clAll(key,on){
  const c=state.clean;
  const all=key==='entries'?c.a.unused.map(u=>u.entry)
           :key==='merges'?c.a.merges.map(m=>m.entry)
           :key==='mounts'?c.a.unused_mounts.map(m=>m.mount)
           :c.a.orphans.map(o=>o.rel);
  c[key]=new Set(on?all:[]);
  const head=document.getElementById('clc_'+(key==='entries'?'unused':key));
  if(head)head.closest('.clsec').querySelectorAll('.cllist input[type=checkbox]')
    .forEach(cb=>{cb.checked=on;});
  clStale(); clCounts();
}
function clPayload(){
  const c=state.clean;
  // A ticked mount carries its model with it, so the freed entries ride along in
  // `entries` — they are never in the unused list (the mount was referencing them).
  const freed=c.a.unused_mounts.filter(m=>c.mounts.has(m.mount)&&m.frees_model).map(m=>m.model);
  return {mod:c.a.mod,target:c.target,
    entries:[...new Set([...c.entries,...freed])],
    merges:[...c.merges].map(e=>({entry:e,into:c.into[e]})),
    mounts:[...c.mounts],
    orphans:[...c.orphans]};
}
async function clPreview(){
  const box=document.getElementById('clPreview'); if(!box)return null;
  box.innerHTML='<div class="preview">Planning…</div>';
  const r=await api.post('/api/bmdb/cleanup_plan',clPayload());
  if(r.error){box.innerHTML=`<div class="preview w-bad">${esc(r.error)}</div>`;return null;}
  state.clean.plan=r;
  box.innerHTML=clPlanHtml(r); return r;
}
function clPlanHtml(r){
  const li=(cls,items)=>items.map(x=>`<div class="srow ${cls}"><span class="sicon">${
      cls==='bad'?'✗':cls==='warn'?'!':'·'}</span><span class="stext">${esc(x)}</span></div>`).join('');
  const sample=r.exports.slice(0,12);
  return `<div class="sum" style="margin-top:10px">
    <div class="srow shead"><span class="sicon">🧹</span><span class="stext">What this moves</span></div>
    ${li('',r.changes)}
    ${r.target?`<div class="srow"><span class="sicon">📁</span><span class="stext">into <span class="path">${esc(r.target)}</span></span></div>`:''}
    ${sample.length?`<div class="srow"><span class="sicon">·</span><span class="stext">
      ${sample.map(x=>`<span class="path">${esc(x)}</span>`).join('<br>')}
      ${r.export_count>sample.length?`<br><i>…and ${r.export_count-sample.length} more</i>`:''}</span></div>`:''}
    ${li('warn',r.warnings)}${li('bad',r.errors)}</div>`;
}
async function clApply(){
  const c=state.clean;
  if(!c.target){toast('Choose where the removed assets should go first');return;}
  const r=state.clean.plan||await clPreview();
  if(!r)return;
  if(r.errors&&r.errors.length){toast(r.errors[0]);return;}
  if(!r.entry_deletes.length&&!r.export_count&&!r.mount_deletes.length){toast('Nothing is ticked');return;}
  if(!confirm(`Move ${r.entry_deletes.length} modeldb entr${r.entry_deletes.length===1?'y':'ies'} `+
      `and ${r.export_count} file(s) out of “${c.a.mod}”?\n\nThey are copied to:\n${r.target}\n\n`+
      `${r.merges.length?`${r.merges.length} unit soldier line(s) are repointed at their twin.\n\n`:''}`+
      `${r.mount_deletes.length?`${r.mount_deletes.length} mount(s) are removed from descr_mount.txt.\n\n`:''}`+
      `Everything touched is backed up first — 🕑 Log → Undo puts it all back.`))return;
  const job=newJob();
  const res=await runJob(job,'Cleaning up…',
    `Copying ${r.export_count} file(s) out, then rewriting ${esc(c.a.mod)}’s modeldb.
     Everything is backed up as it goes — 🕑 Log → Undo puts it all back.`,
    ()=>api.post('/api/bmdb/cleanup_apply',{...clPayload(),job,clear_strings_bin:clearBinOn()}));
  if(res.error){toast('Cleanup failed: '+res.error);renderCleanup();return;}
  closeModal();
  toast(`Removed ${res.plan.entry_deletes.length} entr${res.plan.entry_deletes.length===1?'y':'ies'} `+
        `and ${res.plan.export_count} file(s) ✓${binMsg(res)}  (undo in 🕑 Log)`,5200);
  state.bmdb=null; state.destData=null; loadSource();
}

function edDeleteDialog(){
  const e=state.ed;
  document.getElementById('modal').innerHTML=`<h2 class="w-bad">Delete “${esc(e.d.type)}”</h2>
    <div class="mbody">
      <div class="warnbox">This removes the unit's block from <code>export_descr_unit.txt</code>.
        Anything that still recruits it (<code>export_descr_buildings.txt</code>,
        <code>descr_strat.txt</code>, scripts) must be cleaned up by hand or the game will error.</div>
      <fieldset><legend>Also remove</legend>
        <label class="chk"><input type="checkbox" id="dOptLoc" checked> its text entry
          (<code>${esc(e.d.dictionary)}</code>) from export_units.txt</label><br>
        <label class="chk"><input type="checkbox" id="dOptModels"> its battle-model entries —
          only ones no other unit or mount uses</label><br>
        <label class="chk"><input type="checkbox" id="dOptAssets"> the mesh/texture files of those
          entries (only if nothing else references them)</label><br>
        <label class="chk"><input type="checkbox" id="dOptIcons"> its unit card and info card</label>
      </fieldset>
      <div class="count">Everything removed is backed up first — 🕑 Log → Undo restores it byte-exact.</div>
      <div id="edPreview"></div>
    </div>
    <div class="foot"><button onclick="renderEditor()">Cancel</button>
      <button onclick="edDeletePreview()">Preview</button>
      <button class="danger" onclick="edDoDelete()">Delete unit</button></div>`;
  edDeletePreview();
}
function edDeleteOpts(){
  const g=id=>{const el=document.getElementById(id);return !!(el&&el.checked);};
  return {delete:true,delete_options:{remove_loc:g('dOptLoc'),remove_models:g('dOptModels'),
    remove_assets:g('dOptAssets'),remove_icons:g('dOptIcons')}};
}
async function edDeletePreview(){
  const box=document.getElementById('edPreview'); if(!box)return;
  box.innerHTML='<div class="preview">Planning…</div>';
  const r=await api.post('/api/edit/plan',edPayload(edDeleteOpts()));
  box.innerHTML=r.error?`<div class="preview w-bad">${esc(r.error)}</div>`:edPlanHtml(r);
}
async function edDoDelete(){
  const e=state.ed;
  if(!confirm(`Delete “${e.d.type}” from ${e.mod}?\n\nIt is backed up first, so you can undo it from the 🕑 Log.`))return;
  const res=await api.post('/api/edit/apply',edPayload(edDeleteOpts()));
  if(res.error){toast('Delete failed: '+res.error);return;}
  closeModal(); toast(`Deleted “${e.d.type}” ✓  (undo in 🕑 Log)`,4200);
  state.destData=null; loadSource();
}
