/* sprites.js — Sprites mode: generating and wiring the far-LOD unit sprites

   Part of the Medieval 2 GUI Toolkit UI. These files are plain
   <script> tags sharing ONE global scope, loaded in the order set in
   index.html — there is no build step and no module system. Two rules
   follow from that: a top-level name must be unique across all of
   them, and a file's top-level side effects may not depend on a file
   loaded after it. */
/* ---------- sprites mode ----------
   Sprites are the flat billboards the game swaps in at the far LOD. The engine
   renders them, but only as a side effect of booting with a magic flag, and what
   lands on disk is raw TGA. This workspace does the prep, then owns everything
   after generation: convert, dedup, install and point the modeldb at the result.
   The two published methods differ only in step 1, so that is the only step that
   branches. */
async function loadSprites(){
  const mod=state.src;
  main.innerHTML='<div class="empty">Reading '+esc(mod)+'’s models…</div>';
  let r;
  try{ r=await api.get('/api/sprites?mod='+enc(mod)); }
  catch(e){ if(stale('sprites',mod))return;
    main.innerHTML=`<div class="empty">Couldn't read the modeldb.<br>
    <span class="count">${esc(''+e)}</span><br><br>
    <button class="primary" onclick="loadSprites()">Retry</button></div>`; return; }
  if(stale('sprites',mod))return;       // moved on while this was in flight
  state.spr=Object.assign({
    picked:new Set(),
    // EOP is strictly nicer where it exists (no CFG edit, no restart per batch),
    // so it leads unless the mod shows no sign of it
    method:r.has_eop?'eop':'classic',
    cfg:r.cfgs[0]||'', mipmaps:false, dedup:true, mounts:false, last:null,
    // a real mod lists 2000+ models of which a couple of hundred need anything,
    // so the list opens on the work rather than on the whole modeldb
    todo:true
  },r);
  renderSprites();
}
function sprSet(k,v){state.spr[k]=v;renderSprites();}
function sprPick(name,on){const s=state.spr;on?s.picked.add(name):s.picked.delete(name);renderSprites();}
function sprPickShown(on){const s=state.spr;sprShown().forEach(m=>on?s.picked.add(m.name):s.picked.delete(m.name));renderSprites();}
// The models a unit visibly *switches to* — its armour-upgrade levels. An entry
// that is only ever somebody's soldier, officer or general model is skipped:
// picking those alongside is what makes a batch balloon from thirty models to
// two thousand, and they are covered by their own unit's row anyway.
function sprPickUpgrades(){
  const s=state.spr, hits=sprShown().filter(m=>(m.roles||[]).includes('armour'));
  if(!hits.length)return toast('No armour-upgrade models among the models shown.');
  hits.forEach(m=>s.picked.add(m.name));
  renderSprites(); toast(`Picked ${hits.length} armour-upgrade model(s).`);
}
function sprQuery(){
  // the sidebar box and the picker's own box are the same filter, so either works
  return ((state.spr&&state.spr.q)||search.value||'').trim().toLowerCase();
}
function sprShown(){
  const s=state.spr,qq=sprQuery();
  // "needs sprites" hides anything whose every faction record already resolves,
  // plus anything marked done by hand. A search overrides it, so a model you
  // deliberately look up never silently fails to appear.
  return s.models.filter(m=>(!qq||m.name.includes(qq))&&(s.mounts||!m.is_mount||qq)
    &&(!s.todo||qq||(m.state!=='ok'&&!m.done)));
}
const SPR_STATE={ok:'has sprites',partial:'partly done',none:'no sprites'};
// What a model is used AS. Worth showing per row: it is the difference between
// "this needs a sprite of its own" and "this is already covered elsewhere".
const SPR_ROLE={soldier:'soldier',armour:'armour ug',officer:'officer',mount:'mount'};
function sprFlags(m){
  const out=(m.roles||[]).map(r=>`<span class="sprtag">${esc(SPR_ROLE[r]||r)}</span>`);
  if(m.is_mount&&!(m.roles||[]).includes('mount'))out.unshift('<span class="sprtag">mount</span>');
  if(m.done)out.push('<span class="sprtag on">done</span>');
  // state 'none' used to render nothing at all, so the rows that most need
  // flagging were the only ones with no flag
  out.push(m.state==='none'
    ?'<span class="sprtag warn">not in unit_sprites/</span>'
    :`<span class="sprtag ${m.state==='ok'?'on':''}">${SPR_STATE[m.state]}</span>`);
  return out.join(' ');
}
async function sprMark(on){
  const s=state.spr,names=[...s.picked];
  if(!names.length)return toast('Pick some models first.');
  const r=await api.post('/api/sprites/mark',{mod:state.src,models:names,done:on});
  if(r.error)return toast(r.error);
  s.picked.clear();
  toast(`${names.length} model(s) ${on?'marked done':'unmarked'}.`);
  await loadSprites();
}
function renderSprites(){
  if(!state.spr||state.spr.mod!==state.src)return loadSprites();
  const s=state.spr, a=s.audit, picked=[...s.picked];
  const shown=sprShown();
  count.textContent=`${picked.length} picked`;
  const pending=s.pending.filter(p=>p.complete);
  const cfgState=s.cfg?(s.cfg_state[s.cfg]||'absent'):'absent';

  main.innerHTML=bmdbTabsHtml('data/unit_sprites')+`<div class="sprhead">
      <h2>${esc(state.src)} · unit sprites</h2>
      <span class="count">Generate the far-LOD billboards, convert them and point the
        modeldb at them. ${a.missing||a.misnamed_total
        ?`<b class="w-warn">${a.missing+a.misnamed_total}</b> of
          ${a.ok+a.missing+a.misnamed_total} sprite line(s) resolve to no file.`
        :`All ${a.ok} sprite line(s) resolve.`}</span>
    </div>

    <div class="sprstep"><h3><span class="n">1</span> Generate
      <span class="grow"></span>
      <span class="count">${s.method==='eop'?'via the M2TWEOP console':'via sprite_script + CFG'}</span>
      </h3>
      <div class="sprbody">
        <div class="sprnote">${s.has_eop
          ?docPoints('This mod ships M2TWEOP, so generation goes through its console.',[
            'No CFG to edit.',
            'No restart between batches.',
            s.method==='classic'
              ?`<a href="#" onclick="sprSet('method','eop');return false">Use it instead</a>`
              :`<a href="#" onclick="sprSet('method','classic');return false">Use the classic route instead</a>`])
          :docPoints('This mod has no M2TWEOP install, so generation uses the classic route.',[
            'The game renders the sprites on the next launch.',
            'Everything after that is the same either way.'])}</div>
        <div class="sprrow">
          <input id="sprQ" type="search" placeholder="Search models…" value="${esc(s.q||'')}"
            oninput="sprSet('q',this.value)" style="min-width:200px">
          <span class="count">${shown.length} of ${s.models.length} model(s)</span>
          <button onclick="sprPickShown(true)">Pick all shown</button>
          <button onclick="sprPickUpgrades()" title="Armour-upgrade models only. Skips entries that are just somebody's soldier, officer or general model">Pick armour upgrades</button>
          <button onclick="sprPickShown(false)">Clear</button>
          <label class="chk"><input type="checkbox" ${s.todo?'checked':''}
            onchange="sprSet('todo',this.checked)"> needs sprites only</label>
          <label class="chk"><input type="checkbox" ${s.mounts?'checked':''}
            onchange="sprSet('mounts',this.checked)"> show mounts</label>
          <span class="grow"></span>
        </div>
        <div class="sprrow">
          <button ${picked.length?'':'disabled'} onclick="sprMark(true)">
            Mark ${picked.length} done by hand</button>
          <button ${picked.length?'':'disabled'} onclick="sprMark(false)">Unmark</button>
          <span class="count">${s.done_total} marked done${s.todo
            ?', hidden along with models whose lines all resolve':''}</span>
        </div>
        <div class="sprnote">Mounts need their own sprites, so pick the <b>mount's</b> model,
          not the rider's; the game merges the two.</div>
        <div class="sprpick">${shown.length?shown.map(m=>`
          <label><input type="checkbox" ${s.picked.has(m.name)?'checked':''}
            onchange="sprPick('${q1(m.name)}',this.checked)">
            <span>${esc(m.name)}</span> ${sprFlags(m)}
            <span class="fac">${m.factions.length} faction(s)</span></label>`).join('')
          :`<div class="empty" style="padding:14px">${s.todo
            ?'Nothing left to generate. Every model\\u2019s sprite lines resolve or is marked done.'
            :'No models match.'}</div>`}</div>
        ${s.method==='eop'?`
          <div class="sprnote">Load to the main menu and run this in the EOP console.
            Nothing is written to disk for this method.</div>
          <textarea class="sprlua" readonly onclick="this.select()">${
            picked.length?picked.map(m=>`M2TWEOP.generateSprite("${m}")`).join('\n')
            :'Pick one or more models above.'}</textarea>
          <div class="sprrow"><button ${picked.length?'':'disabled'}
            onclick="sprCopyLua()">Copy to clipboard</button>
            <span class="count">Sprites land in ${sprExportDirs(s)}</span></div>`
        :`
          <div class="sprrow">
            <span class="count">CFG that launches the mod</span>
            <select onchange="sprSet('cfg',this.value)" style="max-width:340px">
              ${s.cfgs.length?s.cfgs.map(c=>`<option value="${esc(c)}" ${c===s.cfg?'selected':''}>${esc(c)}</option>`).join('')
                :'<option value="">None found</option>'}
            </select>
            <span class="sprtag ${cfgState==='on'?'on':'off'}">bypass ${esc(cfgState)}</span>
          </div>
          <div class="sprnote">${docPoints('Two things catch people out on this route.',[
            '<code>sprite_script.txt</code> goes in the Medieval II Total War <b>root</b>, never in '
              +'the mod. That is the single most common reason nothing happens.',
            'The bypass flag makes the next normal launch re-render instead of starting, which reads '
              +'as a crash. Turn it back off when you are done.'])}</div>
          <div class="sprrow">
            <button class="primary" ${picked.length?'':'disabled'} onclick="sprPrep()">
              Write sprite_script + set flag (${picked.length})</button>
            <button ${cfgState==='on'?'':'disabled'} onclick="sprRevert()">Turn the flag back off</button>
          </div>`}
      </div></div>

    <div class="sprstep"><h3><span class="n">2</span> Convert
      <span class="grow"></span>
      <span class="count">${pending.length} waiting</span></h3>
      <div class="sprbody">
        ${s.have_nvcompress?'':`<div class="sprnote w-warn">nvcompress.exe is missing from
          tools/nvtt, so conversion can't run.</div>`}
        <div class="sprnote">${docPoints('Conversion runs here, start to finish.',[
          'TGA → DXT5 DDS → <code>.texture</code>.',
          `Installed into <code>${esc(s.install_dir)}</code>.`,
          'The published route needs a GUI and Python 2. Neither is required here.'])}</div>
        ${pending.length?`<div class="sprlist">
          <div class="r hrow"><span>Sprite</span><span>Model</span><span>Sheets</span></div>
          ${pending.map(p=>`<div class="r"><span>${esc(p.stem)}</span>
            <span class="count">${esc(p.model)}</span>
            <span class="count">${p.sheets||p.textures}</span></div>`).join('')}</div>`
        :`<div class="sprnote">Nothing waiting in ${sprExportDirs(s)}.
           Run step 1 first, then come back and hit Rescan.</div>`}
        ${s.pending.length>pending.length?`<div class="sprnote w-warn">
          ${s.pending.length-pending.length} incomplete set(s) ignored, because they are missing their
          <code>.spr</code> or their sheets.</div>`:''}
        <div class="sprrow">
          <button class="primary" ${pending.length&&s.have_nvcompress?'':'disabled'}
            onclick="sprConvert()">Convert ${pending.length} sprite(s)</button>
          <button onclick="loadSprites()">Rescan</button>
          <label class="chk"><input type="checkbox" ${s.dedup?'checked':''}
            onchange="sprSet('dedup',this.checked)"> collapse identical faction copies</label>
          <label class="chk"><input type="checkbox" ${s.mipmaps?'checked':''}
            onchange="sprSet('mipmaps',this.checked)"> mipmaps</label>
        </div>
        <div class="sprnote">The engine writes one sprite per faction in the entry's ownership
          list; identical copies are the norm. Collapsing keeps one and points the rest at it.
          Mipmaps are off because sprites almost certainly don't need them.</div>
        ${s.last?sprResultHtml(s.last):''}
      </div></div>

    <div class="sprstep"><h3><span class="n">3</span> Wire into the modeldb</h3>
      <div class="sprbody">
        <div class="sprnote">Both published methods stop here and tell you to check the sprite
          lines by hand. A line must read
          <code>unit_sprites/&lt;faction&gt;_&lt;model&gt;_sprite.spr</code> or it points at a file
          that will never exist.</div>
        ${a.misnamed.length?`
          <div class="sprnote"><b class="w-warn">${a.misnamed_total}</b> line(s) point at nothing
            while the file the generator produced <i>is</i> on disk. It is a one-click fix.</div>
          <div class="sprlist">
            <div class="r hrow"><span>Points at</span><span>Model</span><span>Faction</span></div>
            ${a.misnamed.slice(0,50).map(r=>`<div class="r"><span>${esc(r.path)}</span>
              <span class="count">${esc(r.model)}</span>
              <span class="count">${esc(r.faction)}</span></div>`).join('')}</div>
          <div class="sprrow"><button class="primary" onclick="sprFixNames()">
            Repoint ${a.misnamed.length} line(s)</button>
            ${a.misnamed_total>a.misnamed.length?`<span class="count">of ${a.misnamed_total}
              Run it again for the rest.</span>`:''}</div>`
        :'<div class="sprnote">No misnamed sprite lines.</div>'}
        ${a.missing?`<div class="sprnote w-warn">${a.missing} line(s) name a sprite
          that isn't on disk at all. Generate those models in step 1.</div>`:''}
        ${a.orphans?`<div class="sprnote">${a.orphans} sprite file(s) in
          <code>unit_sprites/</code> that no modeldb line names.</div>`:''}
      </div></div>`;
}
// Two folders when the mod lives outside the install that launches it — both are
// scanned, and naming both is what makes "nothing found" diagnosable.
function sprExportDirs(s){
  const d=(s.export_dirs&&s.export_dirs.length)?s.export_dirs
         :[s.export_dir||'export/unit_sprites'];
  return d.map(p=>`<code>${esc(p)}</code>`).join(' or ');
}
function sprResultHtml(r){
  const dupes=Object.values(r.duplicates||{}).reduce((n,v)=>n+Object.keys(v).length,0);
  const models=Object.keys(r.models||{}).length;
  return `<div class="sprnote" style="border-top:1px solid var(--edge);padding-top:9px">
    <b class="w-good">Converted ${r.converted.length} sheet(s)</b> across ${models} model(s);
    ${r.installed.length} file(s) installed${dupes?`, ${dupes} duplicate faction copy(s) collapsed`:''}.
    </div>
    <div class="sprrow"><button class="primary" onclick="sprWire()">
      Point the modeldb at these (${models} model(s))</button></div>`;
}
async function sprCopyLua(){
  const t=[...state.spr.picked].map(m=>`M2TWEOP.generateSprite("${m}")`).join('\n');
  try{ await navigator.clipboard.writeText(t); toast('Copied. Paste it into the EOP console.'); }
  catch(e){ toast('Could not reach the clipboard. Select the box and copy manually.'); }
}
async function sprPrep(){
  const s=state.spr;
  const r=await api.post('/api/sprites/prep_apply',{mod:state.src,models:[...s.picked],
    method:'classic',cfg_path:s.cfg});
  if(r.error)return toast(r.error);
  if(r.unknown?.length)toast(`${r.unknown.length} name(s) are not modeldb entries, so they were skipped.`);
  else toast(`Ready. Run the mod, then come back to step 2.`);
  await loadSprites();
}
async function sprRevert(){
  const r=await api.post('/api/sprites/revert_cfg',{cfg:state.spr.cfg});
  toast(r.error?r.error:r.changed?'Flag turned off.':'Flag was already off.');
  await loadSprites();
}
async function sprConvert(){
  const s=state.spr,job=newJob();
  overlay.classList.add('open');
  const r=await runJob(job,'Converting sprites',
    `TGA → DXT5 DDS → <code>.texture</code>, then installing into
     ${esc(s.install_dir)}. The originals in export/ are removed as they convert.`,
    ()=>api.post('/api/sprites/convert_apply',{mod:state.src,job,mipmaps:s.mipmaps,
      dedup:s.dedup,install:true,cleanup:true}));
  closeModal();
  if(r.error)return toast('Convert failed: '+r.error);
  const last=r.record;
  await loadSprites();           // re-reads the mod: export/ and data/ both changed
  state.spr.last=last; renderSprites();
  toast(`Converted ${last.converted.length} sheet(s) ✓`);
}
async function sprWire(){
  const last=state.spr.last; if(!last)return;
  const r=await api.post('/api/sprites/wire',{mod:state.src,models:last.models,
    duplicates:last.duplicates});
  if(r.error)return toast(r.error);
  toast('Modeldb updated. Undo is in the log.');
  await loadSprites();
}
async function sprFixNames(){
  // rebuild the sprite line for every faction record the audit flagged; the
  // server derives the correct casing from the modeldb itself
  const models={};
  for(const r of state.spr.audit.misnamed)(models[r.model]||(models[r.model]=[])).push(r.faction);
  const res=await api.post('/api/sprites/wire',{mod:state.src,models});
  if(res.error)return toast(res.error);
  toast('Sprite lines repointed. Undo is in the log.');
  await loadSprites();
}

function renderSounds(){
  if(!state.snd||state.snd.mod!==state.src)return loadSounds();
  const s=state.snd;
  if(!s.has_file){
    main.innerHTML=`<div class="empty">“${esc(state.src)}” has no
      <code>data/export_descr_sounds_units_voice.txt</code>.<br>
      <span class="count">Without that file there is no voice bank to edit, so units fall back
      to the game's own.</span></div>`;
    sndBtn.textContent='Apply voice edits (0)'; sndBtn.disabled=true; return;
  }
  const qq=search.value.trim().toLowerCase();
  const list=s.tab==='missing'?s.missing:s.tab==='existing'?s.existing:s.orphans;
  const all=list.filter(u=>{
    if(qq&&!(u.type.toLowerCase().includes(qq)||(u.name||'').toLowerCase().includes(qq)))return false;
    const a=sndVal(u,'accent'),c=sndVal(u,'class');
    if(s.fAccent&&a!==s.fAccent)return false;
    if(s.fClass&&c!==s.fClass)return false;
    if(s.onlyBad&&s.tab==='existing'&&!(u.accent_conflict||u.class_conflict))return false;
    if(s.onlyBad&&s.tab==='missing'&&u.accent_valid)return false;
    return true;
  });
  s.view=all.slice(0,SND_CAP);
  const staged=sndOps().length;
  sndBtn.textContent=`Apply voice edits (${staged})`; sndBtn.disabled=!staged;
  count.textContent=`${all.length}/${list.length}`;
  const nConf=s.existing.filter(u=>u.accent_conflict||u.class_conflict).length;
  const tab=(k,label,n)=>`<button class="${s.tab===k?'on':''}" onclick="sndTab('${k}')">${label} <span class="badge">${n}</span></button>`;
  const opt=(v,cur)=>`<option value="${esc(v)}" ${v===cur?'selected':''}>${esc(v)}</option>`;
  main.innerHTML=`<div class="sndhead">
      <h2>${esc(state.src)} · unit voices</h2>
      <div class="count">${docPoints(`${s.donors.length} units have their own selection barks
        across ${s.pairs.length} accent/class blocks.`,[
        nConf?`<b class="w-warn">${nConf}</b> unit(s) sit in a block their EDU doesn't point at. The
          game follows the EDU, so those entries are dead.`:''])}</div>
      <div class="sndtabs">
        ${tab('missing','No voice entry',s.missing.length)}
        ${tab('existing','Has a voice entry',s.existing.length)}
        ${tab('orphans','Entries with no unit',s.orphans.length)}
      </div>
    </div>
    ${s.tab==='orphans'?`<div class="count" style="margin-top:10px">${docPoints(
       'These entries name units that no longer exist.',[
       'They do nothing on their own.',
       'The name stays taken: a new unit called the same thing would inherit them.',
       'Tick one to delete it.'])}</div>`:''}
    <div class="sndbar">
      <span class="count">Filter</span>
      <select onchange="sndFilter('fAccent',this.value)">
        <option value="">All accents</option>${s.accents.map(a=>opt(a,s.fAccent)).join('')}</select>
      <select onchange="sndFilter('fClass',this.value)">
        <option value="">All classes</option>${s.classes.map(c=>opt(c,s.fClass)).join('')}</select>
      ${s.tab==='orphans'?'':`<label class="chk"><input type="checkbox" ${s.onlyBad?'checked':''}
        onchange="sndFilter('onlyBad',this.checked)"> ${s.tab==='existing'?'only ones the EDU disagrees with':'only ones with no usable accent'}</label>`}
      <span class="grow"></span>
      ${s.tab==='orphans'?'':`<span class="count">Set all ${s.view.length} shown to copy</span>
      <select onchange="sndFilter('bulkDonor',this.value)" style="max-width:230px">
        <option value="">Pick a unit</option>
        ${s.donors.map(d=>`<option value="${esc(d.name)}" ${d.name===s.bulkDonor?'selected':''}>${esc(d.name)} (${esc(d.accent)}/${esc(d['class'])})</option>`).join('')}
      </select>
      <button onclick="sndBulk()">Apply to shown</button>`}
      ${staged?`<button class="danger" onclick="sndReset()">✕ Clear ${staged} staged</button>`:''}
      <button class="${s.cv?'on':''}" title="Show a unit's block exactly as
export_descr_sounds_units_voice.txt stores it. Click a unit's name to look at it."
        onclick="sndCvToggle()">&lt;/&gt; Code view</button>
    </div>
    <div class="cvsplit${s.cv?'':' off'}">
    <div id="sndGui">
    ${all.length?`<div class="sndlist">
      <div class="sndrow hrow"><span>Unit</span><span>In game now</span><span>Accent</span>
        <span>Class</span><span>Copy sounds from</span><span>Drop</span></div>
      <!-- the unit card sits beside the name, the same picture the unit editor
           and the recruitment lists show: a voice bank is 900 rows of type names,
           and a type name is the one thing about a unit nobody recognises -->
      ${s.view.map(sndRowHtml).join('')}</div>`
     :'<div class="empty">No units match.</div>'}
    </div>
    ${s.cv?`<div id="sndCodeCol">${cvHtml(s.cv)}</div>`:''}
    </div>
    ${all.length>SND_CAP?`<div class="count" style="margin:10px 0">Showing the first
      ${SND_CAP} of ${all.length}. Narrow it down with the filters or the search box.</div>`:''}`;
  if(s.cv&&s.cv.loaded)cvWire(s.cv);
}
function sndRowHtml(u,i){
  const s=state.snd,op=s.ops[u.type]||{};
  const a=sndVal(u,'accent'),c=sndVal(u,'class');
  const isOrphan=s.tab==='orphans', has=u.accent!==undefined;
  const ready=sndReady(u), dropping=!!op.remove;
  // what the game does with this unit right now, before anything staged
  let now;
  if(isOrphan) now=`<span class="w-warn">no such unit</span>`;
  else if(!has) now=u.edu_accent
    ? (u.accent_valid?`<span class="count">${esc(u.edu_accent)}, generic</span>`
                     :`<span class="w-bad" title="The EDU names an accent this mod's voice bank has no block for.">${esc(u.edu_accent)} ✗</span>`)
    : `<span class="w-warn" title="No accent line in the EDU at all.">No accent</span>`;
  else now=(u.accent_conflict||u.class_conflict)
    ? `<span class="w-bad" title="EDU says ${esc(u.edu_accent||'none')}/${esc(u.edu_class||'none')}, the bank has it in ${esc(u.accent)}/${esc(u['class'])} . The game follows the EDU, so these sounds never play">${esc(u.accent)}/${esc(u['class'])} ✗</span>`
    : `<span class="count">${esc(u.accent)}/${esc(u['class'])}</span>`;
  if(isOrphan) return `<div class="sndrow ${dropping?'dropping':''}">
    <div class="un"><span class="uc empty" title="No unit by this name exists, so it has no card."></span>
      <span class="un2"><span class="nm">${esc(u.name)}</span>
        <span class="ty">Voice entry only</span></span></div>
    <span class="now">${now}</span>
    <span class="count">${esc(u.accent)}</span><span class="count">${esc(u['class'])}</span>
    <span class="count">None</span>
    <span class="rm"><input type="checkbox" ${dropping?'checked':''} title="Delete this entry from the voice bank."
      onchange="sndToggleRemove(${i},this.checked)"></span></div>`;
  const donors=sndDonors(a,c);
  const sel=(cur,vals,key,blank)=>`<select onchange="sndPick(${i},'${key}',this.value)" ${dropping?'disabled':''}>
    <option value="">${blank}</option>
    ${vals.map(v=>`<option value="${esc(v)}" ${v===cur?'selected':''}>${esc(v)}</option>`).join('')}</select>`;
  return `<div class="sndrow ${dropping?'dropping':ready?'staged':''}"
    data-label="unit" data-snd="${esc(u.type)}">
    <div class="un" onclick="sndCvShow('${q1(esc(u.type))}')"
      title="Show this unit's block in the code view">
      <img class="uc" loading="lazy" onerror="iconRetry(this)"
        src="${iconUrl(state.src,u.type)}" alt="">
      <span class="un2"><span class="nm">${esc(u.name||u.type)}</span>
        <span class="ty">${esc(u.type)}</span></span></div>
    <span class="now">${now}</span>
    ${sel(a,s.accents,'accent','Pick an accent')}
    ${sel(c,s.classes,'class','Pick a class')}
    <select onchange="sndPick(${i},'donor',this.value)" ${dropping?'disabled':''}
      title="${a&&c?`units with their own barks in ${esc(a)}/${esc(c)}`:'pick an accent and a class first'}">
      <option value="">${a&&c?(has?'Keep its own sounds':`Pick a unit (${donors.length})`):'Pick an accent and a class first'}</option>
      ${donors.map(d=>`<option value="${esc(d.name)}" ${d.name===(op.donor||'')?'selected':''}>${esc(d.name)}</option>`).join('')}
    </select>
    <span class="rm">${has?`<input type="checkbox" ${dropping?'checked':''}
      title="Remove this unit's voice entry from the bank." onchange="sndToggleRemove(${i},this.checked)">`:''}</span>
  </div>`;
}
/* ---- code view on the sounds screen ----
   READ-ONLY (see codeview.sounds_document): a voice entry only means anything
   under the accent/class headers above it, and moving it between those is the
   staged edits' whole job. The pane answers "what does the file actually say
   about this unit", which is what the screen had no way to show. */
async function sndCvToggle(){
  const s=state.snd;
  if(s.cv){cvDrop(s.cv); s.cv=null; renderSounds(); return;}
  s.cv=cvCreate({kind:'sounds', mod:state.src, id:s.cvUnit||'', readonly:true,
    where:'data/export_descr_sounds_units_voice.txt'});
  renderSounds();
  if(s.cvUnit)await sndCvShow(s.cvUnit); else {s.cv.loaded=true; renderSounds();}
}
async function sndCvShow(type){
  const s=state.snd; if(!s.cv)return;
  s.cvUnit=type;
  const cv=s.cv; cv.id=type;
  // A unit on the "no voice entry" tab has no block to show, and asking the
  // server for one comes back as a bare 404. Say what is actually true instead.
  const row=(s.existing||[]).concat(s.missing||[],s.orphans||[])
    .find(u=>u.type===type||u.name===type);
  if(row&&row.accent===undefined){
    cv.loaded=true; cv.text=''; cv.spans={}; cv.partSpans={}; cv.err=null;
    cv.base=''; cv.pristine=''; cv.hidden=[]; cv.comments=0; cv.auto=null;
    cv.note=`“${type}” has no entry in the voice bank yet. Stage one on its row `
      +`and apply, and it will have a block here.`;
    renderSounds(); return;
  }
  cv.loaded=false;
  renderSounds();
  await cvLoad(cv);
  if(state.snd===s&&s.cv===cv)renderSounds();
}
async function sndApply(){
  const ops=sndOps(); if(!ops.length)return;
  const modal=document.getElementById('modal');
  modal.className='modal'; modal.innerHTML='<h2>Planning voice edits…</h2>';
  overlay.classList.add('open');
  let r;
  try{ r=await api.post('/api/sounds/plan',{mod:state.src,ops}); }
  catch(e){ r={error:''+e}; }
  if(r.error&&!r.errors){ modal.innerHTML=`<h2>Voice edits</h2><div class="mbody w-bad">${esc(r.error)}</div>
    <div class="foot"><button onclick="closeModal()">Close</button></div>`; return; }
  const bad=(r.errors||[]).length;
  modal.innerHTML=`<h2>Voice edits <span class="pill">${esc(state.src)}</span></h2>
    <div class="mbody">
      ${bad?`<div class="warnbox">⚠ <b>${bad} row(s) can't be written.</b> Nothing is applied
        until they are fixed or removed from the selection.<br>
        ${r.errors.map(e=>esc(e)).join('<br>')}</div>`:''}
      <div class="count" style="margin-bottom:8px">${docPoints(
        'Writes the voice bank'+(r.edu_rewritten
          ?' and <code>export_descr_unit.txt</code> (the matching <code>accent</code> / <code>voice_type</code> lines)'
          :'')+'.',[
        'Backed up first: 🕑 Log → Undo restores them exactly.'])}</div>
      ${renderSummary(r.summary)}
    </div>
    <div class="foot">${cleanerBoxHtml()}<button onclick="closeModal()">Cancel</button>
      <button class="primary" ${bad?'disabled':''} onclick="sndDoApply()">Apply ${ops.length} change(s)</button></div>`;
}
async function sndDoApply(){
  const ops=sndOps();
  document.getElementById('modal').innerHTML=`<h2>Writing voice edits…</h2>
    <div class="mbody"><div class="progress-track"><div class="progress-fill" style="width:60%"></div></div>
      <div class="count" style="margin-top:8px">${ops.length} unit(s)</div></div>`;
  let r;
  try{ r=await api.post('/api/sounds/apply',{mod:state.src,ops,clear_strings_bin:clearBinOn()}); }
  catch(e){ r={error:''+e}; }
  if(r.error){ toast('Voice edits failed: '+r.error,4500); closeModal(); return; }
  closeModal();
  toast(`${ops.length} voice change(s) written ✓${binMsg(r)}  (undo in 🕑 Log)`,4200);
  state.snd=null; state.destSnd=null; loadSounds();
}
