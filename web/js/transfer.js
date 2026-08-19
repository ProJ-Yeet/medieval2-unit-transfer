/* transfer.js — Unit Transfer mode: the composer, base/replace, conflict
   resolution, the asset and icon resolvers, and batch transfers

   Part of the Medieval 2 GUI Toolkit UI. These files are plain
   <script> tags sharing ONE global scope, loaded in the order set in
   index.html — there is no build step and no module system. Two rules
   follow from that: a top-level name must be unique across all of
   them, and a file's top-level side effects may not depend on a file
   loaded after it. */
/* ---------- per-unit config ---------- */
function cfgFor(type){
  if(!state.cfg[type]) state.cfg[type]={include_officers:true,include_mount:true,include_crew:true,include_projectile:true,include_engine:true,engine_conflict:'use_existing',
    // How the unit lands in the destination — see setMode(). 'base_type' is the
    // destination unit the 'base' and 'replace' modes both lean on (the stat
    // donor / the unit being rewritten); '' while the mode is 'new'.
    mode:'new',import_card:false,import_info_card:false,
    base_type:'',soldier_from:(state.settings&&state.settings.soldier_from_base)?'base':'source',
    officer_from:'source',mount_from:'source',crew_from:'source',upgrade_from:'source',
    // "Port + base animations" for the mount / officers: bring the source's own
    // models across and take only their animations from the base's (fromBasePanel)
    import_mount_with_base:true,import_officers_with_base:true,
    field_overrides:{},on_conflict:'rename',new_type:'',new_dictionary:'',make_mercenary:false,merc_icons:false,exclude_models:[],
    asset_conflict:'mod_folder',asset_reroute_dir:'',icon_conflict:'use_existing',
    // voice: 'base' (copy the base unit's barks — the default), 'unit' (copy some
    // other destination unit's), 'none'. snd_accent/snd_class only filter the
    // donor list; the accent/class actually written are always the donor's.
    sound_mode:'base',sound_donor:'',snd_accent:'',snd_class:'',
    // where the unit's block is written: 'auto' mirrors the source unit (an EOP
    // unit stays one), 'eop' forces an M2TWEOP unit file, 'edu' forces the EDU
    eop_target:'auto',
    base_fac:'',_conflict:null,_fields:null,_orig:null,_fieldsKey:null,_inherited:null};
  return state.cfg[type];
}
/* ---- transfer mode ----------------------------------------------------------
   'new'     the unit arrives as its own EDU entry, with its own name and icons.
   'base'    same, but the stats/attributes/ownership/era are inherited from a
             destination unit — a new unit built on an existing one.
   'replace' the picked destination unit IS what gets written: its block is
             rewritten with this unit's models and nothing is added to the mod.
             It keeps its type, name, description, stats and cards; each stat can
             still be switched over one at a time with the B buttons below, and
             the cards have their own tick boxes.
   The last two share one picker (`base_type`) because they ask the same question
   — which destination unit — and both are restricted to the SAME unit kind: a
   cavalry model in an infantry entry has neither the right stats nor the right
   animations. */
const modeOf=c=>c.mode||'new';
const isReplace=c=>modeOf(c)==='replace'&&!!c.base_type;
// what the picked unit is called in prose, per mode
const donorRole=c=>modeOf(c)==='replace'?'replaced unit':'base unit';
// The destination's voice bank, fetched once per destination mod. Needed to know
// whether a base unit HAS barks to copy, and to list the units that do.
async function ensureDestSnd(){
  if(!state.destSnd||state.destSnd.mod!==state.dst){
    try{ state.destSnd=await api.get('/api/sounds?mod='+enc(state.dst)); }
    catch(e){ state.destSnd={mod:state.dst,has_file:false,donors:[],accents:[],classes:[]}; }
  }
  return state.destSnd;
}

/* ---------- composer (single or batch) ---------- */
let composerList=[];
async function openComposer(types){
  composerList=types.slice(); state.editing=types[0];
  state.ed=null;                // the composer, not a unit editor, owns this dialog
  const m=document.getElementById('modal');
  m.className='modal';
  m.innerHTML='<h2>Opening…</h2><div class="mbody"><div class="count">Reading '+
    esc(state.dst)+'…</div></div>';
  overlay.classList.add('open');
  // The overlay goes up first, so anything that throws between here and the
  // finished dialog used to leave a dimmed screen with nothing on it and no way
  // to tell whether the tool was working or dead. It says which, now.
  try{
    await ensureDest();         // needed for the unit-limit projection + base picker
    await ensureDestSnd();      // …and to know which destination units have barks
  }catch(e){
    if(isAborted(e)){closeModal();return;}
    m.innerHTML=`<h2>Couldn't open the transfer</h2>
      <div class="mbody"><div class="trnote w-warn">${docPoints(
        `Reading “${esc(state.dst)}” failed, so there is nothing to build the transfer against.`,
        [`<code>${esc(''+(e&&e.message||e))}</code>`,
         'Nothing has been written yet. This is the step before any file is touched.',
         'If the tool is no longer running, start it again and retry.'])}</div></div>
      <div class="foot"><button onclick="closeModal()">Close</button>
        <button class="primary" onclick="openComposer(${JSON.stringify(types)})">Retry</button></div>`;
    return;
  }
  undoReset();
  resetPlace();
  renderComposer();
}
async function renderComposer(){
  const batch=composerList.length>1;
  const type=state.editing; const u=state.data.units.find(x=>x.type===type);
  const c=cfgFor(type);
  const m=document.getElementById('modal');
  const strip = batch ? `<div class="batchstrip">${composerList.map(t=>{const cc=cfgFor(t);
      const bimg=cc.base_type?`<img onerror="iconRetry(this)" src="${iconUrl(state.dst,cc.base_type)}">`:'';
      return `<div class="bchip ${t===type?'sel':''}" onclick="switchUnit('${q1(esc(t))}')">
        <img onerror="iconRetry(this)" src="${iconUrl(state.src,t)}"><div class="t">${esc(t)}</div>
        <div class="base">${!cc.base_type?'new unit'
          :(isReplace(cc)?'replaces: ':'base: ')+esc(cc.base_type)}</div></div>`;}).join('')}</div>` : '';
  const hasOff=u.officers.length>0, hasMount=!!u.mount, hasCrew=!!(u.crew&&u.crew.length);
  const proj=u.projectiles||[]; const hasProj=proj.length>0;
  // siege engine: descr_engines.txt entry + its skeletons/meshes/baked textures
  const eng=u.engine||u.mounted_engine||''; const hasEng=!!eng;
  const engMounted=!u.engine&&!!u.mounted_engine;
  const engGroups=u.engine_groups||[];
  // a mounted engine has no model groups — its `class` names the descr_engine_skeleton entry
  const engClass=engMounted?(u.engine_class||''):'';
  // a group supplied by the base — or kept by the unit being replaced — makes its
  // "include the source's" box moot
  const rep=isReplace(c);
  const kw=rep?'(kept)':'(from base)';           // why a group's box is greyed out
  const insteadMsg=n=>rep?`→ keeping ${esc(n)}’s own`:`→ using ${esc(n)}’s instead`;
  const crwBase=c.crew_from==='base'&&!!c.base_type;
  /* "Port + base animations" is `<group>_from = base` plus the import flag: the
     source's own models come across (own modeldb entry, own descr_mount.txt
     block) and only their animation records are the base's, which is the one
     part of them the destination can be missing. So that case is NOT a group
     taken from the base, and its include box stays live. */
  const bU=baseUnitOf(c);
  const mntChoice=c.mount_from==='base'&&!!c.base_type&&hasMount&&!!(bU&&bU.mount);
  const mntImport=mntChoice&&c.import_mount_with_base!==false;
  const mntBase=c.mount_from==='base'&&!!c.base_type&&!mntImport;
  const offChoice=c.officer_from==='base'&&!!c.base_type&&hasOff&&!!(bU&&bU.officers.length);
  const offImport=offChoice&&c.import_officers_with_base!==false;
  const offBase=c.officer_from==='base'&&!!c.base_type&&!offImport;
  // projectile physics live in stat_pri/stat_sec, which the base supplies wholesale,
  // so with a base the projectile is the base's (already in dest) and porting is moot
  const projBase=!!c.base_type;
  const offOn=hasOff&&!offBase, mntOn=hasMount&&!mntBase, crwOn=hasCrew&&!crwBase;
  const projOn=hasProj&&!projBase;
  // the engine is named by the `engine` field, which the base supplies when the
  // crew group is taken from it
  const engBase=crwBase; const engOn=hasEng&&!engBase;
  const sameMod=state.src===state.dst;      // edit mode's "new unit from this one"
  // the guided field editor lays its boxes out in rows — give it the same room
  // the unit editor gets, instead of the default 640px dialog
  m.className=gfMode()==='guided'?'modal wide':'modal';
  m.innerHTML=`<h2>${batch?`Batch transfer: ${composerList.length} units`
      :sameMod?`New unit from “${esc(u.name)}”`
      :rep?`Replace “${esc(c.base_type)}” with “${esc(u.name)}”`
      :`Transfer “${esc(u.name)}”`} <span class="pill">${
      sameMod?'in '+esc(state.src):esc(state.src)+' → '+esc(state.dst)}</span></h2>
   <div class="mbody">
     ${unitLimitBanner()}
     ${strip}
     <div style="display:flex;gap:12px;align-items:center;margin-bottom:10px">
       <img class="baseimg" src="${iconUrl(state.src,type)}">
       <div><b>${esc(u.name)}</b><div class="count">${esc(type)} · ${esc(u.kind||u.category||'?')}/${esc(u.class||'?')}</div>
         ${hasProj?`<div class="projline">🏹 projectile: ${proj.map(p=>`<span class="chip">${esc(p)}</span>`).join('')}</div>`:''}
         ${hasEng?`<div class="projline">🏰 siege engine: <span class="chip">${esc(eng)}</span>${engMounted?'<span class="count"> (mounted)</span>':''}${engGroups.length?`<span class="count"> · ${engGroups.map(esc).join(' / ')}</span>`:''}${engClass?`<span class="count"> · class: ${esc(engClass)}</span>`:''}</div>`:''}</div>
     </div>
     ${sameMod?'':`${projOn?`<div class="warnbox">⚠ <b>Projectile effects aren't imported.</b> The definition
       (damage, velocity, angles) comes across; effect lines fall back to <code>invisible_placeholder_set</code>
       where ${esc(state.dst)} lacks them. Re-add them in <code>descr_effect_impacts.txt</code>.</div>`:''}
     <fieldset><legend>Include secondary models</legend>
       <label class="chk${offOn?'':' off'}"><input type="checkbox" id="optOff" ${offOn&&c.include_officers?'checked':''} ${offOn?'':'disabled'}> Officers ${!hasOff?'(none)':offBase?kw:`(${u.officers.length})`}</label>
       <label class="chk${mntOn?'':' off'}" style="margin-left:12px"><input type="checkbox" id="optMount" ${mntOn&&c.include_mount?'checked':''} ${mntOn?'':'disabled'}> Mount${!hasMount?' (none)':mntBase?' '+kw:` (${esc(u.mount)})`}</label>
       <label class="chk${crwOn?'':' off'}" style="margin-left:12px"><input type="checkbox" id="optCrew" ${crwOn&&c.include_crew?'checked':''} ${crwOn?'':'disabled'}> Crew${!hasCrew?' (none)':crwBase?' '+kw:` (${u.crew.length})`}</label>
       <label class="chk${projOn?'':' off'}" style="margin-left:12px"><input type="checkbox" id="optProj" ${projOn&&c.include_projectile?'checked':''} ${projOn?'':'disabled'}> Projectile${!hasProj?' (none)':projBase?' '+kw:` (${proj.map(esc).join(', ')})`}</label>
       <label class="chk${engOn?'':' off'}" style="margin-left:12px"><input type="checkbox" id="optEngine" ${engOn&&c.include_engine!==false?'checked':''} ${engOn?'':'disabled'}> Siege engine${!hasEng?' (none)':engBase?' '+kw:` (${esc(eng)})`}</label>
       ${hasOff?`<div class="optnames"><span class="k">Officers</span>${offBase?`<span class="frombase">${insteadMsg(c.base_type)}</span>`:modelChecks(u.officers,offOn,c)}${
         offImport?`<span class="frombase">→ brought across; animated like
           <b>${esc(bU.officers[0])}</b> where ${esc(state.dst)} lacks their animations</span>`:''}</div>`:''}
       ${hasMount?`<div class="optnames"><span class="k">Mount</span><span class="chip">${esc(u.mount)}</span>${
         mntBase?`<span class="frombase">${insteadMsg(c.base_type)}</span>`
         :mntImport?`<span class="frombase">→ brought across; animated like
           <b>${esc(bU.mount)}</b> where ${esc(state.dst)} lacks its animations</span>`:''}</div>`:''}
       ${mntImport?`<div class="count" style="margin-left:22px">
           <code>${esc(u.mount)}</code> is added to ${esc(state.dst)}'s descr_mount.txt with its
           own model. Only its animation set is taken from <code>${esc(bU.mount)}</code>, and only
           where the skeletons it asks for are missing here.</div>`:''}
       ${hasCrew?`<div class="optnames"><span class="k">Crew</span>${crwBase?`<span class="frombase">${insteadMsg(c.base_type)}</span>`:modelChecks(u.crew,crwOn,c)}</div>`:''}
       ${hasProj?`<div class="optnames"><span class="k">Projectile</span>${proj.map(o=>`<span class="chip">${esc(o)}</span>`).join('')}${projBase?`<span class="frombase">${insteadMsg(c.base_type)} stats (its projectile)</span>`:'→ added to descr_projectile.txt, effects blanked'}</div>`:''}
       ${hasEng?`<div class="optnames"><span class="k">Siege engine</span><span class="chip">${esc(eng)}</span>${engBase?`<span class="frombase">${insteadMsg(c.base_type)}</span>`:engMounted?`→ added to descr_mounted_engines.txt with its reference points${engClass?`; its <code>class ${esc(engClass)}</code> descr_engine_skeleton.txt entry is added only if ${esc(state.dst)} lacks it`:''}`:`→ added to descr_engines.txt + descr_engine_skeleton.txt, with its meshes/bone maps/collision/reference points, the textures baked into those meshes, and its engine animations`}</div>`:''}
       <div class="count" style="margin-top:5px">An unticked group keeps its source name, which must already exist in ${esc(state.dst)}. Or take it from ${rep?`“${esc(c.base_type)}”`:'the base'} above.</div>
     </fieldset>
     ${engOn&&c.include_engine!==false?`<fieldset><legend>Siege engine: <code>${esc(eng)}</code></legend>
       <div class="count">Copied: the <code>${engMounted?'descr_mounted_engines.txt':'descr_engines.txt'}</code> block${engGroups.length?` (${engGroups.length} model group${engGroups.length>1?'s':''}: ${engGroups.map(esc).join(', ')})`:''}
         ${engMounted?`and the <code>reference_points</code> file it names.`
         :`, ${engGroups.length?`each group's animation entry, `:''}every mesh / bone map / collision /
         reference-points file it names${engGroups.length?', and the textures baked into those meshes':''}.`}</div>
       ${engMounted?`<div class="count" style="margin-top:5px">${docPoints('<b>Mounted engine.</b>',[
         `The gun is part of the <b>mount's</b> model, so only the <code>reference_points</code> file
          comes across.`,
         engClass?`Its animation set <code>${esc(engClass)}</code> is added only if ${esc(state.dst)}
           lacks it. An existing one is kept as-is, which normally works fine.`
         :`It has no <code>class</code> line, so no animation entry comes with it. Check it by hand.`
         ])}</div>`:''}
       ${engMounted?'':`<div class="count" style="margin-top:5px">${docPoints(
         `<b>Engine files can't be relocated</b>, because each mesh has its texture paths baked in.`,[
         `Overwriting a shared one also re-skins ${esc(state.dst)}'s own engines.`,
         `So the default keeps the destination's file, and the imported engine may then wear its skin.`,
         'Preview lists them and lets you flip that.'])}</div>`}
       <div class="count" style="margin-top:5px">Vanilla files the engine uses aren't copied. If ${esc(state.dst)} overrides
         one, its version wins and may not match. The preview flags those.</div>
       <div class="count" style="margin-top:5px">Not ported: effect / particle / sound references and
         <code>crew_animations</code> names, so check those exist in ${esc(state.dst)}.</div>
     </fieldset>`:''}
     <fieldset><legend>What this transfer creates in ${esc(state.dst)}</legend>
       <div class="radio-row">
         <label><input type="radio" name="tmode" value="new" ${modeOf(c)==='new'?'checked':''}>
           <b>A new unit</b>: its own entry, name and icons</label>
         <label><input type="radio" name="tmode" value="base" ${modeOf(c)==='base'?'checked':''}>
           <b>A new unit based on an existing one</b>: a new entry that inherits a destination
           unit's stats, cost, ownership and era</label>
         <label><input type="radio" name="tmode" value="replace" ${modeOf(c)==='replace'?'checked':''}>
           <b>Replace an existing unit</b>: no new entry, so a destination unit keeps its name and
           stats, and gets “${esc(u.name)}”’s models</label>
       </div>
       <div id="baseArea" style="margin-top:8px;${modeOf(c)==='new'?'display:none':''}">
         <div class="count" style="margin-bottom:6px">${modeOf(c)==='replace'
           ? docPoints(`Pick the <b>${esc(state.dst)}</b> unit to rewrite.`,[
               'It keeps everything except its models.',
               'Change what comes across with the <b>Take from</b> rows, the '
                 +'<span class="ibadge">B</span> buttons and the card boxes below.',
               `Only ${esc(u.kind||u.category||'')} units are listed: it has to be the same unit type.`])
           : docPoints(`Pick the <b>${esc(state.dst)}</b> unit to inherit the numbers from.`,[
               `Only ${esc(u.kind||u.category||'')} units are listed: it has to be the same unit type.`])
         }</div>
         <div class="basepick">
           <img class="baseimg" id="baseImg" src="${c.base_type?iconUrl(state.dst,c.base_type):''}" style="${c.base_type?'':'visibility:hidden'}">
           <div style="flex:1">
             <div class="basebar">
               <input id="baseSearch" value="${esc(c.base_q||'')}" placeholder="Filter ${esc(u.kind||u.category||'')} units in ${esc(state.dst)}…" oninput="renderBaseList()">
               <select id="baseFac" onchange="renderBaseList()"><option value="">All factions</option></select>
             </div>
             <div class="baselist" id="baseList"></div>
           </div>
         </div>
         ${modeOf(c)==='replace'&&!c.base_type?`<div class="count w-warn" style="margin-top:6px">
           Pick a unit to replace before applying.</div>`:''}
       </div>
     </fieldset>
     ${rep?`<fieldset><legend>Import from “${esc(u.name)}”</legend>
       <div class="count">“${esc(c.base_type)}” keeps its own cards unless you tick these. An imported
         card replaces its file, under its own name and faction folders.</div>
       <label class="chk" style="margin-top:6px"><input type="checkbox" id="optImpCard" ${c.import_card?'checked':''}>
         Unit card ${u.has_card?'':'<span class="count">(the source has none)</span>'}</label>
       <label class="chk" style="margin-left:12px"><input type="checkbox" id="optImpInfo" ${c.import_info_card?'checked':''}>
         Unit info card ${u.has_info?'':'<span class="count">(the source has none)</span>'}</label>
       <div class="count" style="margin-top:6px">Stats are imported one at a time with the
         <span class="ibadge">B</span> buttons in <b>Edit fields</b>.</div>
     </fieldset>`:''}`}
     ${soundFieldset(c,u)}
     <fieldset><legend>Mercenary attribute</legend>
       <label class="chk"><input type="checkbox" id="optMerc" ${c.make_mercenary?'checked':''}> Make this a mercenary unit</label>
       <div class="count" style="margin-top:5px">Adds the <code>mercenary_unit</code> attribute and a
         <code>merc</code> texture record.
         ${u.mercenary?'<b class="w-good">Already a mercenary in the source.</b>':''}
         <br>To actually recruit it, add a pool entry in <code>descr_mercenaries.txt</code> yourself.</div>
     </fieldset>
     <fieldset><legend>Mercenary icons</legend>
       <label class="chk"><input type="checkbox" id="optMercIcons" ${c.merc_icons?'checked':''}> Put the unit card and info card in the merc folders ONLY</label>
       <div class="count" style="margin-top:5px">${docPoints('What the tick box changes.',[
         '<b>On:</b> cards go to the merc folders only, pinned with <code>card_pic_dir</code> / '
           +'<code>info_pic_dir</code>.',
         '<b>Off (default):</b> a copy in every faction folder the unit is owned by, plus the merc '
           +'folders as a fallback. No pinning needed.'])}</div>
     </fieldset>
     <fieldset><legend>Edit fields: every EDU field, edited as overrides</legend>
       ${sameMod?'':fromBasePanel(c,u)}
       <div class="fieldbar">
         <input id="fieldFilter" placeholder="Filter fields…" oninput="filterFields()">
         ${gfToggleHtml()}
         <span class="count" id="fieldChanged"></span>
       </div>
       <div class="allfields" id="allFields"><div class="count" style="padding:6px">Loading fields…</div></div>
       ${sameMod?'':rep?`<div class="count" style="margin-top:6px">${docPoints(
         `<span class="ibadge">B</span> marks a field <b>${esc(c.base_type)}</b> keeps.`,[
         `Click one to import that field from “${esc(u.type)}”; click again to put it back.`,
         `Greyed out <span class="ibadge off" style="background:transparent;color:var(--dim);border-color:var(--edge)">B</span> = imported.`,
         '<code>type</code> and <code>dictionary</code> are locked: changing them would rename the '
           +'unit instead of replacing it.'])}</div>`
        :`<div class="count" style="margin-top:6px"><span class="ibadge">B</span>
         marks a field taken from the base${c.base_type?` <b>${esc(c.base_type)}</b>`:''}. Click one to keep
         <b>${esc(u.type)}</b>'s own value instead; click again to go back. Greyed out <span class="ibadge off"
         style="background:transparent;color:var(--dim);border-color:var(--edge)">B</span> = the source's
         value. Fields the source unit doesn't have can't be switched.</div>`}
     </fieldset>
     <div id="previewBox"></div>
   </div>
   <div class="foot">
     ${cleanerBoxHtml()}
     <button onclick="closeModal()">Cancel</button>
     <button onclick="doPreview()">Preview${batch?' this unit':''}</button>
     <button class="primary" onclick="doApply()">${batch?'Apply all':'Apply'}</button>
   </div>`;
  // wire per-unit option persistence (disabled inputs — absent models — never fire)
  // with a base, toggling an include box changes which unit supplies that group
  // group toggles re-render so the per-model checkboxes enable/disable in step
  // the secondary-model / base fieldsets are absent when creating a new unit
  // inside one mod (nothing to bring across, and the base IS the source unit)
  if(window.optOff)optOff.onchange=()=>{c.include_officers=optOff.checked; renderComposer();};
  if(window.optMount)optMount.onchange=()=>{c.include_mount=optMount.checked; doPreview();};
  // this one changes which models are copied at all, so the whole composer is redrawn
  if(window.optCrew)optCrew.onchange=()=>{c.include_crew=optCrew.checked; renderComposer();};
  if(window.optProj)optProj.onchange=()=>{c.include_projectile=optProj.checked; doPreview();};
  // re-render: the engine fieldset appears/disappears with the checkbox
  if(window.optEngine)optEngine.onchange=()=>{c.include_engine=optEngine.checked; renderComposer();};
  // re-render: the whole voice panel (locks, donor list, notes) changes with the mode
  document.querySelectorAll('input[name=sndmode]').forEach(r=>r.onchange=()=>{
    c.sound_mode=r.value; renderComposer();});
  optMerc.onchange=()=>{c.make_mercenary=optMerc.checked; doPreview();};
  optMercIcons.onchange=()=>{c.merc_icons=optMercIcons.checked; doPreview();};
  // new unit / based on one / replace one — a whole different composer each time
  document.querySelectorAll('input[name=tmode]').forEach(r=>r.onchange=()=>setMode(r.value));
  if(window.optImpCard)optImpCard.onchange=()=>{c.import_card=optImpCard.checked; importedIcons(c); doPreview();};
  if(window.optImpInfo)optImpInfo.onchange=()=>{c.import_info_card=optImpInfo.checked; importedIcons(c); doPreview();};
  // per-group source/base toggles — re-render so the include boxes grey out.
  // officer_from / mount_from are the three-way rows and wire themselves through
  // grp3Set, because each of their values sets TWO options.
  ['soldier_from','crew_from','upgrade_from'].forEach(k=>
    document.querySelectorAll(`input[name=${k}]`).forEach(r=>r.onchange=()=>{
      c[k]=r.value; renderComposer();}));
  loadFields(type); if(modeOf(c)!=='new')renderBaseList();
  doPreview();   // auto-plan so limit / asset-conflict warnings surface immediately
}
/* Switching mode rebuilds the composer: the picker, the per-group rows, the field
   editor's baseline and the voice panel all mean something different in each one.
   Going back to a plain new unit drops the pick — nothing else uses it — but the
   pick SURVIVES a base<->replace switch, since it answers the same question. */
/* Importing a card over a unit that already has one only does something if the
   existing file is replaced: the replaced unit's card sits at the very path the
   import writes to (ui/units/<faction>/#<its dict>.tga), and the default "use
   existing" would keep it — the tick box would appear to do nothing. So asking
   for a card sets the icon rule to overwrite; clearing both puts it back. The
   radios in the preview still win if you change them afterwards. */
function importedIcons(c){
  c.icon_conflict=(c.import_card||c.import_info_card)?'overwrite':'use_existing';
}
function setMode(v){
  const c=cfgFor(state.editing);
  const prev=modeOf(c);
  c.mode=v;
  if(v==='new')c.base_type='';
  // "Soldier from the base" (⚙ setting) is the default for BOTH modes that have a
  // base unit: "base" means the same thing in each — the destination unit supplies
  // the soldier line — so a user who set that default meant it when replacing too.
  // Entering base/replace re-applies it; a per-unit pick still wins afterwards.
  if(v!==prev&&v!=='new')
    c.soldier_from=(state.settings&&state.settings.soldier_from_base)?'base':'source';
  // the composed baseline (and which fields are inherited) changes with the mode
  c._fields=null; c._fieldsKey=null;
  renderComposer();
}
// The destination unit currently chosen as base (has its officers/mount/crew).
function baseUnitOf(c){
  return (c.base_type&&state.destData)
    ? state.destData.units.find(x=>x.type===c.base_type) : null;}
// "Take from base" toggles — one row per group, shown only when the BASE has it.
// Replacing reads the same rows the other way round: "Source" ports the
// transferred unit's models over the replaced unit's, "Base" leaves that group
// exactly as the replaced unit has it. Both send the same `<group>_from=base`,
// because in both modes "base" means "the destination unit supplies this group"
// — which is why the label is "Base" either way.
/* The three-way rows (Officers, Mount) encode two server options at once. Their
   models are entries of their own and carry their own animation set, so there
   are three different answers and not two:
     port      = the source's entry, its own skeletons. Crashes if this mod
                 has not got them.
     portanim  = the source's entry with the base unit's animation records
                 written over its skeleton lines. Safe to load, may move oddly.
     base      = the base unit's own model. Nothing copied at all. */
const GRP3=[['port','Port as is'],['portanim','Port + base animations'],['base','Use base’s']];
function grp3Value(c,key){
  if(c[key]!=='base')return 'port';
  return c[key==='mount_from'?'import_mount_with_base':'import_officers_with_base']===false
    ? 'base' : 'portanim';
}
function grp3Set(key,v){
  const c=cfgFor(state.editing);
  const imp=key==='mount_from'?'import_mount_with_base':'import_officers_with_base';
  c[key]=v==='port'?'source':'base';
  c[imp]=(v==='portanim');
  renderComposer();
}
function fromBasePanel(c,u){
  const b=baseUnitOf(c), on=!!c.base_type, rep=isReplace(c);
  const row=(key,label,detail,tip)=>`<div class="sbrow"><span class="k">${
      tip?qm(tip,label):''}${label}</span>
    <label><input type="radio" name="${key}" value="source" ${c[key]!=='base'?'checked':''} ${on?'':'disabled'}> Source</label>
    <label><input type="radio" name="${key}" value="base" ${c[key]==='base'?'checked':''} ${on?'':'disabled'}> Base</label>
    <span class="count">${detail}</span></div>`;
  const row3=(key,label,detail,tip)=>{const cur=grp3Value(c,key);
    return `<div class="sbrow"><span class="k">${tip?qm(tip,label):''}${label}</span>
      ${GRP3.map(([v,t])=>`<label><input type="radio" name="${key}" value="${v}"
        ${cur===v?'checked':''} ${on?'':'disabled'}
        onchange="grp3Set('${key}','${v}')"> ${t}</label>`).join('')}
      <span class="count">${detail}</span></div>`;};
  const has=n=>rep?`${esc(c.base_type)} has ${n}`:`base has ${n}`;
  // The soldier line is not just "the body model": its modeldb entry carries the
  // skeletons, so whichever unit supplies it decides how the unit animates. That
  // is the one thing about this row nobody guesses, hence the ?.
  let rows=row('soldier_from','Animations (Soldier entry)', on?'the soldier line only':'',
    'The soldier line names the battle model the unit fights with, and that '
    +'modeldb entry is what carries its animations. It is the ONLY entry the '
    +'engine animates the unit from. An armour-upgrade entry is a visual swap '
    +'at that armour level and its own skeleton line is never played. '
    +'Source: the source unit\'s own skeletons come across, and this mod must '
    +'already have them or the game crashes on load. '
    +(rep?'Base':'Base')+': the unit animates like '
    +(rep?'the replaced unit':'the base unit')+' instead, which always loads but '
    +'may fight unexpectedly.');
  // Filled in by paintSoldierAnim() from the plan — a missing-animation warning
  // only belongs here when the SOLDIER model is the one asking for it, since
  // flipping this row is the fix. See TransferPlan.soldier_skeletons_missing.
  rows+=`<div class="sbanim" id="soldierAnim" hidden></div>`;
  if(b&&b.officers.length) rows+=row3('officer_from','Officers',
    has(`${b.officers.length}: ${esc(b.officers.join(', '))}`),
    'An officer is a modeldb entry of its own, so it carries its own animation '
    +'set. Port as is: the source\'s officers, their own skeletons, and this mod '
    +'must have them or the game crashes on load. Port + base animations: the '
    +'same models with the base unit\'s officer\'s animation records written '
    +'over their skeleton lines, so it always loads, and they may move oddly. '
    +'Use base\'s: the '+(rep?'replaced':'base')+' unit\'s officers, nothing copied.');
  if(b&&b.mount)           rows+=row3('mount_from','Mount',
    has(esc(b.mount)),
    'A mount is three things: the descr_mount.txt block, its battle model, and '
    +'that model\'s animations. Port as is: the source\'s mount and its own '
    +'skeletons, which this mod must have or the game crashes on load. Port + '
    +'base animations: the same mount with the base mount\'s animation records, '
    +'so it always loads and may move oddly. Use base\'s: ride the '
    +(rep?'replaced':'base')+' unit\'s mount instead, nothing copied.');
  if(b&&b.crew&&b.crew.length) rows+=row('crew_from','Crew',has(`${b.crew.length}: ${esc(b.crew.join(', '))}`));
  // The armour-upgrade models are only a choice when replacing: a base template
  // leaves them with the transferred unit, since the new unit IS that unit.
  if(rep) rows+=row('upgrade_from','Armour upgrades',
    `<code>armour_ug_models</code>: the models it wears once its armour is upgraded`,
    'Independent of the Soldier row. The game renders the upgrade entry for the '
    +'unit\'s armour level, so leaving this on Source while the soldier line comes '
    +'from the base puts the source\'s model back on screen at that level. It does '
    +'not change how the unit animates: only the soldier entry does that.');
  return `<div class="basefrom${on?'':' off'}">
    <div class="bftitle">Take from ${on?`<b>${esc(c.base_type)}</b>`
      :(rep?'the replaced unit. Pick one first.':'the base unit. Pick one first.')}</div>
    ${rows}</div>`;
}
/* ---------- voice / sound ----------
   A unit's barks are not in its EDU block: they are a `unit <type>` entry inside one
   accent/class block of the destination's voice bank, and the EDU's `accent` +
   `voice_type` are what point the game at that block. Copying a voice therefore
   pins those two fields to the donor's — an entry the EDU doesn't point at is never
   read — which is exactly why the accent and class controls here lock as soon as a
   donor is in play, rather than letting you set a combination that can't work. */
// The donor a config resolves to, plus why it can or can't be used.
function soundDonor(c){
  const ds=state.destSnd;
  if(!ds||!ds.has_file)return {mode:c.sound_mode,blocked:'nobank'};
  if(c.sound_mode==='none')return {mode:'none'};
  // Replacing: "the base's voice" would be the replaced unit's own entry, copied
  // onto itself. It already has it, and its accent/voice_type come across with
  // its stats — so the default means "leave the voice alone", and nothing is
  // locked. Picking another unit still copies that unit's barks as usual.
  if(c.sound_mode==='base'&&isReplace(c))return {mode:'keep',name:c.base_type};
  const name=c.sound_mode==='base'?(c.base_type||''):(c.sound_donor||'');
  if(!name)return {mode:c.sound_mode,blocked:c.sound_mode==='base'?'nobase':'nopick'};
  const d=(ds.donors||[]).find(x=>x.name===name);
  return d?{mode:c.sound_mode,name,accent:d.accent,cls:d['class']}
          :{mode:c.sound_mode,name,blocked:'silent'};
}
function soundFieldset(c,u){
  const ds=state.destSnd||{},d=soundDonor(c);
  const locked=!!d.accent;
  const radio=(v,label,note,off)=>`<label class="chk${off?' off':''}">
    <input type="radio" name="sndmode" value="${v}" ${c.sound_mode===v?'checked':''} ${off?'disabled':''}>
    ${label}${note?` <span class="count">${note}</span>`:''}</label>`;
  if(!ds.has_file)return `<fieldset><legend>Voice / sound</legend>
    <div class="count">“${esc(state.dst)}” has no voice bank
      (<code>export_descr_sounds_units_voice.txt</code>), so there is nothing to copy into.
      The unit uses the game's own sounds.</div></fieldset>`;
  // why the accent/class pair is not yours to choose while a donor is set
  const why=locked
    ? `Locked. The copied entry goes into ${d.accent} / ${d.cls}, the block “${d.name}” sits in, and `
      +`accent / voice_type are written to match. Point them elsewhere and the unit falls back to `
      +`generic barks. `
      +(c.sound_mode==='base'?`Switch to “another unit” for a different voice.`
                             :`Clear the unit below to filter by accent and class again.`)
    : '';
  const donors=(ds.donors||[]).filter(x=>(!c.snd_accent||x.accent===c.snd_accent)
                                       &&(!c.snd_class||x['class']===c.snd_class));
  const acc=locked?d.accent:c.snd_accent, cls=locked?d.cls:c.snd_class;
  const pick=(key,cur,vals,blank)=>`<select ${locked?`disabled title="${esc(why)}"`
      :`onchange="cmpSndPick('${key}',this.value)"`}>
    <option value="">${blank}</option>
    ${vals.map(v=>`<option value="${esc(v)}" ${v===cur?'selected':''}>${esc(v)}</option>`).join('')}
    ${locked&&!vals.includes(cur)?`<option value="${esc(cur)}" selected>${esc(cur)}</option>`:''}</select>`;
  let body='';
  if(d.mode==='keep')
    body=`<div class="count" style="margin-top:6px">“${esc(d.name)}” keeps the barks it already has,
      the voice bank isn't touched. Pick “another unit” to give it a different voice.</div>`;
  else if(c.sound_mode==='none')
    body=`<div class="count" style="margin-top:6px">No entry is written and
      <code>accent</code> / <code>voice_type</code> stay as the source unit had them. The unit still
      speaks. It just uses its class's generic barks.</div>`;
  else if(d.blocked==='nobase')
    body=`<div class="count w-warn" style="margin-top:6px">No base unit picked yet, so there is no
      voice to copy. Pick one above, or switch to “another unit”.</div>`;
  else if(d.blocked==='silent')
    body=`<div class="count w-warn" style="margin-top:6px">“${esc(d.name)}” has no barks of its own
      in ${esc(state.dst)}, so there is nothing to copy. Pick another unit${
      c.sound_mode==='base'?' for the voice':''}.</div>`;
  else body=`<div class="sndpick">
      <span class="count">Accent</span>${pick('snd_accent',acc,ds.accents||[],'Any')}
      <span class="count">Class</span>${pick('snd_class',cls,ds.classes||[],'Any')}
      ${locked?`<span class="lockicon" title="${esc(why)}">🔒 locked</span>`:
        `<span class="count">These two just filter the list below</span>`}
    </div>
    ${c.sound_mode==='unit'?`<div class="sndpick">
      <span class="count">Sound from</span>
      <select onchange="cmpSndPick('sound_donor',this.value)" style="flex:1;max-width:340px">
        <option value="">Pick a unit (${donors.length} with their own barks)</option>
        ${donors.map(x=>`<option value="${esc(x.name)}" ${x.name===c.sound_donor?'selected':''}>${esc(x.name)} (${esc(x.accent)}/${esc(x['class'])})</option>`).join('')}
      </select>
      ${c.sound_donor?`<button onclick="cmpSndPick('sound_donor','')" title="Unlock the accent and class filters.">✕</button>`:''}
    </div>`:''}
    ${locked?`<div class="sndlocked count">🔒 <b>${esc(d.name)}</b>’s sounds are copied to
      <b>${esc(c.new_type||u.type)}</b> in <b>${esc(d.accent)} / ${esc(d.cls)}</b>, with
      <code>accent</code> and <code>voice_type</code> set to match. ${esc(why)}</div>`:''}`;
  return `<fieldset><legend>Voice / sound</legend>
    <div class="sndopt">
      ${isReplace(c)
        ? radio('base',`Keep “${esc(c.base_type)}”’s own voice`,'the voice bank isn’t touched')
        : radio('base','Use the base unit’s sound',
              c.base_type?`copies “${esc(c.base_type)}”’s barks`:'no base unit picked yet')}
      ${radio('unit','Use another unit’s sound',
              isReplace(c)?'copy another unit’s barks over it'
                          :'take the voice from a different unit')}
      ${radio('none','Don’t import sound',isReplace(c)
              ?'same as keeping it'
              :'use the class’s generic barks')}
    </div>${body}</fieldset>`;
}
function cmpSndPick(key,value){
  const c=cfgFor(state.editing);
  c[key]=value;
  // a donor from another block would drag that block's sounds along, so a changed
  // filter drops a pick it no longer matches
  if(key!=='sound_donor'&&c.sound_donor){
    const d=(state.destSnd.donors||[]).find(x=>x.name===c.sound_donor);
    if(!d||(c.snd_accent&&d.accent!==c.snd_accent)||(c.snd_class&&d['class']!==c.snd_class))
      c.sound_donor='';
  }
  renderComposer();
}
function switchUnit(t){state.editing=t;renderComposer();}
// faction label using the DESTINATION mod's names (base units live in the dest)
const destFacLabel=f=>facTwoNames(f,(state.destData?.faction_names||{})[f]);
function renderBaseList(){
  const u=state.data.units.find(x=>x.type===state.editing); const c=cfgFor(state.editing);
  const dd=state.destData; if(!dd){baseList.innerHTML='<div class="count" style="padding:8px">Loading destination…</div>';return;}
  const rawQ=document.getElementById('baseSearch')?.value||'';
  c.base_q=rawQ;                       // survive composer re-renders
  const qq=rawQ.toLowerCase();
  const facSel=document.getElementById('baseFac');
  // same *kind*: cavalry only bases on cavalry of the same weapon layout
  // (Cavalry / Cavalry_Lance / Cavalry_Archer)
  const sameCat=dd.units.filter(x=>x.kind===u.kind);
  // populate the faction filter with the factions that actually own a candidate
  if(facSel&&facSel.options.length<=1){
    const facs=[...new Set(sameCat.flatMap(x=>x.ownership))].sort((a,b)=>destFacLabel(a).localeCompare(destFacLabel(b)));
    facSel.innerHTML='<option value="">All factions</option>'+
      facs.map(f=>`<option value="${esc(f)}">${esc(destFacLabel(f))}</option>`).join('');
    if(c.base_fac)facSel.value=c.base_fac;
  }
  const fac=facSel?facSel.value:''; c.base_fac=fac;
  const cands=sameCat.filter(x=>(!fac||x.ownership.includes(fac))
    && (!qq||x.name.toLowerCase().includes(qq)||x.type.toLowerCase().includes(qq))).slice(0,120);
  baseList.innerHTML=cands.map(x=>`<div class="baserow ${x.type===c.base_type?'sel':''}" onclick="pickBase('${q1(esc(x.type))}')">
    <img loading="lazy" onerror="iconRetry(this)" src="${iconUrl(state.dst,x.type)}"><div><div class="bn">${esc(x.name)}</div><div class="bs">${esc(x.type)}</div></div></div>`).join('')
    ||`<div class="count" style="padding:8px">No ${esc(u.kind||u.category||'')} units in destination match. The ${esc(donorRole(c))} must be the same unit type.</div>`;
}
function pickBase(t){const c=cfgFor(state.editing);c.base_type=t;
  // full re-render: the soldier toggle and the "using base's" hints only become
  // live once a base exists (search text + faction filter are kept in cfg)
  renderComposer();}
async function loadFields(type){
  const c=cfgFor(type);
  // The baseline depends on whether a base unit is inherited from: with a base,
  // show the fields the unit will ACTUALLY have after inheriting its stats.
  // the composed result depends on the base AND on which groups come from it
  const froms=['soldier_from','officer_from','mount_from','crew_from','upgrade_from'];
  // whether the source's mount is imported changes whose `mount` line the composed
  // block ends up with, so it is part of both the URL and the cache key
  const impMount=c.import_mount_with_base!==false;
  const impOff=c.import_officers_with_base!==false;
  const key=c.base_type
    ?[modeOf(c),c.base_type,...froms.map(k=>c[k]||'source'),impMount,impOff].join('|'):'';
  if(!c._fields || c._fieldsKey!==key){
    const url=c.base_type
      ? `/api/base_fields?source=${encodeURIComponent(state.src)}&unit=${encodeURIComponent(type)}`
        +`&dest=${encodeURIComponent(state.dst)}&base=${encodeURIComponent(c.base_type)}`
        +`&mode=${encodeURIComponent(modeOf(c))}`
        +froms.map(k=>`&${k}=${encodeURIComponent(c[k]||'source')}`).join('')
        +`&import_mount_with_base=${impMount?1:0}`
        +`&import_officers_with_base=${impOff?1:0}`
      : `/api/unit_fields?mod=${encodeURIComponent(state.src)}&type=${encodeURIComponent(type)}`;
    let r;
    try{ r=await api.get(url); }catch(e){ r={error:''+e}; }
    if(r.error){ if(state.editing===type){const b=document.getElementById('allFields');
        if(b)b.innerHTML=`<div class="count w-bad" style="padding:6px">${esc(r.error)}</div>`;} return; }
    c._fields=r.fields||[]; c._inherited=r.inherited||[];
    c._orig={}; for(const [label,val] of c._fields) c._orig[label]=val;   // baseline for diffing
    c._fieldsKey=key;
    // With a base, the SOURCE unit's own values are what a B can be switched back
    // to, so they are fetched alongside (once per unit — they never change).
    if(c.base_type&&!c._srcFields){
      try{
        const s=await api.get(`/api/unit_fields?mod=${encodeURIComponent(state.src)}`
                              +`&type=${encodeURIComponent(type)}`);
        c._srcFields=Object.fromEntries(s.fields||[]);
      }catch(e){ c._srcFields={}; }
    }
    // an override that now matches the new baseline is no longer an override
    for(const k of Object.keys(c.field_overrides))
      if(c.field_overrides[k]===c._orig[k]) delete c.field_overrides[k];
  }
  if(state.editing!==type)return;
  renderAllFields(type);
}
// Show EVERY EDU field of the unit at once (like ModdingTool's unit edit screen).
// Any value changed from its original becomes a field override.
function renderAllFields(type){
  const c=cfgFor(type); const box=document.getElementById('allFields'); if(!box)return;
  if(!c._fields.length){box.innerHTML='<div class="count" style="padding:6px">No editable fields.</div>';updateFieldChanged();return;}
  if(gfMode()==='guided'){
    const host=gfHostComposer();
    box.classList.add('guided'); box.innerHTML=gfRender(host); gfWire(host);
    updateFieldChanged(); return;
  }
  box.classList.remove('guided');
  const inh=new Set(c.base_type?(c._inherited||[]):[]);
  // A copied voice OWNS accent + voice_type: the entry is written into the donor's
  // block, and these two are what send the game there. Editing one here would
  // silently point the unit at a block its entry is not in, so they are shown as
  // the donor's and locked, with the same explanation as the voice panel's 🔒.
  const snd=soundDonor(c), sndLock=snd.accent
    ? {vals:{accent:snd.accent,voice_type:snd.cls},
       why:`Locked by the voice panel. “${snd.name}”’s sounds are copied into `
          +`${snd.accent} / ${snd.cls}, and these two fields are what point the game at `
          +`that block. Choose “Don’t import sound” to edit them yourself.`}
    : null;
  // A unit that has no `accent` line at all still GETS one when a voice is copied
  // (the game can't find the block without it), so show that row rather than
  // writing a field the panel never mentioned. It goes where the EDU keeps it —
  // right after voice_type / class.
  // Replacing a unit does not rename it: `type` and `dictionary` ARE the unit
  // being rewritten. They stay the destination's and are shown as such — editing
  // one here would rename the unit and orphan its localisation entry and icons,
  // which is the one thing this mode exists to avoid.
  const rb=baseUnitOf(c);
  const idLock=(isReplace(c)&&rb)
    ? {vals:{type:rb.type,dictionary:rb.dictionary},
       why:`Locked. This transfer rewrites “${rb.type}” in place, so it keeps its own `
          +`type and dictionary. Those two are what tie it to its name, description `
          +`and icons; change them and you have renamed the unit instead of replacing it.`}
    : null;
  // both locks in one lookup, most specific first
  const lockFor=key=>(idLock&&(key in idLock.vals))?{val:idLock.vals[key],why:idLock.why}
                    :(sndLock&&(key in sndLock.vals))?{val:sndLock.vals[key],why:sndLock.why}
                    :null;
  let fields=c._fields;
  if(sndLock){
    fields=c._fields.slice();
    for(const k of ['voice_type','accent']){
      if(fields.some(([l])=>l===k))continue;
      const after=fields.findIndex(([l])=>l==='voice_type'||l==='class');
      fields.splice(after<0?0:after+1,0,[k,sndLock.vals[k]]);
    }
  }
  box.innerHTML=fields.map(([label,val])=>{
    const dup=/#\d+$/.test(label);
    const key=label.replace(/#\d+$/,'');
    const lk=dup?null:lockFor(key);
    const cur=lk?lk.val
      :(label in c.field_overrides)?c.field_overrides[label]:val;
    const changed=!lk&&(label in c.field_overrides)&&c.field_overrides[label]!==c._orig[label];
    const isInh=inh.has(key);
    const why=lk?lk.why
      :isInh?`${isReplace(c)?'Kept from':'Inherited from the base unit'} ${c.base_type}.`
      :dup?'This field appears more than once in the unit. Edit this one in the EDU directly.'
      :(GF_FIELDS[key]&&GF_FIELDS[key].t?GF_FIELDS[key].t+'. '+gfPlainDoc(key):'');
    return `<div class="afrow${dup?' dup':''}" data-label="${esc(label)}">
      <label>${qm(why,label)}${esc(label)}${
        lk?'<span class="ibadge">🔒</span>':isInh?baseBadge(c,label,cur):''}</label>
      <input data-k="${esc(label)}" value="${esc(cur)}" class="${changed?'changed':''}"
        ${lk||dup?'disabled':''}></div>`;
  }).join('');
  box.querySelectorAll('input[data-k]').forEach(inp=>{
    inp.oninput=()=>{const k=inp.dataset.k, v=inp.value;
      if(v!==c._orig[k]) c.field_overrides[k]=v; else delete c.field_overrides[k];
      inp.classList.toggle('changed', v!==c._orig[k]);
      // a typed value is no longer the base's, so the B has to stop claiming it is
      const b=box.querySelector(`button[data-b="${cssq(k)}"]`);
      if(b)b.outerHTML=baseBadge(c,k,v);
      updateFieldChanged();};
  });
  updateFieldChanged(); filterFields();
}
/* The B beside an inherited field is a switch, not a label: ON the field carries
   the base unit's value, OFF it carries the source unit's own. Nothing new is
   stored for it — "off" is just a field override holding the source's value, which
   is what the transfer engine already knows how to write. It follows that typing
   your own value turns the B off too: the field is no longer the base's. */
const baseSrcVal=(c,label)=>(c._srcFields||{})[label];
function baseBadge(c,label,cur){
  const src=baseSrcVal(c,label);
  const rep=isReplace(c);
  const same=src===undefined||src===c._orig[label];
  if(same){
    // Nothing to switch TO, so this is a marker rather than a button. It looks
    // different (hollow, dashed) and says why on the line: a B that simply does
    // nothing when clicked reads as a broken button.
    const why=src===undefined
      ? `only ${esc(c.base_type)} has this line`
      : `both units have the same value`;
    return `<span class="ibadge fixed" title="${rep?'Kept from':'From'} ${esc(c.base_type)}.
Not switchable: ${why}.">B</span><span class="bwhy">${why}</span>`;
  }
  const on=cur===c._orig[label];
  return `<button type="button" class="ibadge${on?'':' off'}" data-b="${esc(label)}"
    onclick="toggleBaseField('${q1(esc(label))}')"
    title="${on?`${rep?'Keeping':'Using'} ${esc(c.base_type)}'s value. Click to ${rep?'import':'keep'} ${esc(state.editing)}'s own (${esc(src)}).`
              :`${rep?'Imported from':'Using'} ${esc(state.editing)}${rep?'':"'s own value"}. Click to go back to ${esc(c.base_type)}'s (${esc(c._orig[label])}).`}">B</button>`;
}
function toggleBaseField(label){
  const c=cfgFor(state.editing);
  const src=baseSrcVal(c,label); if(src===undefined)return;
  // guided mode has no single box holding the line — the value lives in the
  // override map and the boxes are drawn from it, so flip it there and redraw
  if(document.querySelector('#allFields .gfwrap')){
    const cur=(label in c.field_overrides)?c.field_overrides[label]:c._orig[label];
    const next=(cur===c._orig[label])?src:c._orig[label];
    if(next!==c._orig[label]) c.field_overrides[label]=next; else delete c.field_overrides[label];
    gfRerenderBody(); updateFieldChanged(); return;
  }
  const inp=document.querySelector(`#allFields input[data-k="${cssq(label)}"]`); if(!inp)return;
  const usingBase=inp.value===c._orig[label];
  const next=usingBase?src:c._orig[label];
  if(next!==c._orig[label]) c.field_overrides[label]=next; else delete c.field_overrides[label];
  inp.value=next;
  inp.classList.toggle('changed', next!==c._orig[label]);
  const b=document.querySelector(`#allFields button[data-b="${cssq(label)}"]`);
  if(b)b.outerHTML=baseBadge(c,label,next);
  updateFieldChanged();
}
function updateFieldChanged(){const c=cfgFor(state.editing);const n=Object.keys(c.field_overrides).length;
  const el=document.getElementById('fieldChanged'); if(el)el.textContent=n?`${n} changed`:'';}
function filterFields(){const qq=(document.getElementById('fieldFilter')?.value||'').toLowerCase();
  // the guided view searches across every section (a field's friendly name and
  // its explanation count too), so it redraws rather than hiding rows
  if(document.querySelector('#allFields .gfwrap')){
    const gf=state.gf; if(!gf)return;
    if((gf.q||'')===qq)return;
    gf.q=qq; gfRerenderBody(); return;
  }
  document.querySelectorAll('#allFields .afrow').forEach(r=>{
    const l=(r.dataset.label||'').toLowerCase(); r.style.display=(!qq||l.includes(qq))?'':'none';});}
/* ---- clearing data/text/export_units.txt.strings.bin ----------------------
   The game reads that compiled cache, not export_units.txt, and only rebuilds
   it when it is missing — so until it is deleted a transferred or renamed unit
   keeps showing the OLD name and description. Deleting it costs nothing: the
   next launch writes a fresh one.

   Unlike the Full Cleaner.bat this replaced, it removes exactly that one file
   and nothing the mod ships, so it is a setting rather than a per-job risk to
   weigh up: `clear_strings_bin` in settings.json, on by default, applying to
   every transfer / save / voice change / cleanup. The box under each Apply is
   the same setting, put where you would look for it. */
const clearBinOn=()=>(state.settings||{}).clear_strings_bin!==false;
// `what` names the text file whose cache this job would clear — export_units.txt
// for anything unit-shaped, export_buildings.txt for a building rename.
function cleanerBoxHtml(what){
  const kind=what||'unit';
  return `<label class="chk cleanerbox" style="margin-right:auto" title="Deletes data/text/export_${kind}s.txt.strings.bin in the mod being written to. That is the compiled copy of export_${kind}s.txt; until it is gone the game keeps showing the OLD ${kind} text. It is rebuilt on the next launch. This is a setting, so it applies to every transfer, save, voice change and cleanup.">
    <input type="checkbox" ${clearBinOn()?'checked':''} onchange="setClearBin(this.checked)">
    Clear the <b>${kind}-text cache</b> afterwards
    <span class="count">A setting, so it applies to every job</span></label>`;
}
async function setClearBin(on){
  state.settings=await api.post('/api/settings',{clear_strings_bin:on});
  toast(on?'Unit-text cache will be cleared after every job.'
          :'Unit-text cache left alone, so new unit text may not show in game.');
}
// what a job's response says about the clear, appended to its toast
function binMsg(r){
  const b=r&&r.strings_bin; if(!b)return '';
  if(b.deleted)return '  · unit-text cache cleared';
  if(b.missing)return '';           // nothing was there, so not worth a mention
  return `  · cache not cleared: ${b.error||'?'}`;
}

// per-model checkboxes for a secondary group (officers / crew), so models can be
// picked individually rather than all-or-none. Disabled when the group is off.
function modelChecks(models,groupOn,c){
  const ex=new Set((c.exclude_models||[]).map(s=>s.toLowerCase()));
  return models.map(m=>{
    const on=groupOn&&!ex.has(m.toLowerCase());
    return `<label class="chk mini${groupOn?'':' off'}"><input type="checkbox" ${on?'checked':''} ${groupOn?'':'disabled'} onchange="toggleModel('${q1(esc(m))}',this.checked)"> ${esc(m)}</label>`;
  }).join('');
}
function toggleModel(name,on){
  const c=cfgFor(state.editing);
  const ex=new Set((c.exclude_models||[]).map(s=>s.toLowerCase()));
  if(on)ex.delete(name.toLowerCase()); else ex.add(name.toLowerCase());
  c.exclude_models=[...ex]; doPreview();
}
function optsPayload(type){const c=cfgFor(type);
  // The engine applies field overrides AFTER pinning accent/voice_type to the voice
  // donor's block, so an override left over from before the lock would quietly undo
  // it — drop those two while a donor is in play.
  let fo=c.field_overrides;
  if(soundDonor(c).accent&&('accent' in fo||'voice_type' in fo)){
    fo=Object.assign({},fo); delete fo.accent; delete fo.voice_type;
  }
  const rep=isReplace(c);
  // the replaced unit's identity is not editable — the engine ignores these two
  // when replacing, and sending them would only make the preview lie
  if(rep&&('type' in fo||'dictionary' in fo)){
    fo=Object.assign({},fo); delete fo.type; delete fo.dictionary;
  }
  return {include_officers:c.include_officers,include_mount:c.include_mount,include_crew:c.include_crew,
    include_projectile:c.include_projectile!==false,include_engine:c.include_engine!==false,
    exclude_models:c.exclude_models||[],
    // one picker, two meanings: a stat template, or the unit being rewritten
    mode:rep?'replace':'new',
    base_type:rep?null:(c.base_type||null),
    replace_type:rep?c.base_type:null,
    import_card:!!c.import_card,import_info_card:!!c.import_info_card,
    field_overrides:fo,
    soldier_from:c.soldier_from||'source',officer_from:c.officer_from||'source',
    mount_from:c.mount_from||'source',crew_from:c.crew_from||'source',
    upgrade_from:c.upgrade_from||'source',
    import_mount_with_base:c.import_mount_with_base!==false,
    import_officers_with_base:c.import_officers_with_base!==false,
    on_conflict:c.on_conflict,new_type:c.new_type||null,new_dictionary:c.new_dictionary||null,
    eop_target:c.eop_target||'auto',
    asset_conflict:c.asset_conflict||'mod_folder',
    asset_reroute_dir:c.asset_reroute_dir||null,
    icon_conflict:c.icon_conflict||'use_existing',
    engine_conflict:c.engine_conflict||'use_existing',
    make_mercenary:!!c.make_mercenary,merc_icons:!!c.merc_icons,
    sound_mode:c.sound_mode||'base',sound_donor:c.sound_donor||null};}
// Render the plan summary as indented rows. Each row's text sits in its own
// column, so a long path wraps under itself and the structure stays readable.
function renderSummary(t){
  const rows=(t||'').split('\n').map((raw,i)=>{
    const m=raw.match(/^(\s*)(.*?)\s*$/); const indent=m[1].length; let body=m[2];
    if(!body)return '';
    const lvl=indent>=6?3:(indent>=2?2:1);
    let sev='';
    if(/ERROR/.test(body))sev='bad';
    else if(/^!/.test(body)||/WARNING|EXCLUDED|NOT found|SKIPPED|differ\b/.test(body))sev='warn';
    else if(/RELOCATED|OVERWRITE|RENAMED|REPLACING|renamed bmdb|reuse existing|base template|byte-identical|supplies them/.test(body))sev='good';
    let icon='';
    if(/^!/.test(body))icon='⚠';
    else if(/^-/.test(body))icon='·';
    body=body.replace(/^[!\-]\s*/,'');
    // highlight counts and file paths inside the line
    let html=esc(body)
      .replace(/(^|\s)(\d+)(?=\s|$|\))/g,'$1<span class="num">$2</span>')
      .replace(/([\w./\\-]+\.(?:mesh|texture|tga|dds|spr|txt|modeldb))/g,'<span class="path">$1</span>');
    return `<div class="srow lvl${lvl}${sev?' '+sev:''}${i===0?' shead':''}">`
      +`<span class="sicon">${icon}</span><span class="stext">${html}</span></div>`;
  }).join('');
  return `<div class="sum">${rows}</div>`;
}

/* ---------- 500 vanilla unit-limit warning ---------- */
function projectedDestCount(){
  const dd=state.destData; if(!dd) return null;
  const have=new Set(dd.units.map(u=>u.type));
  // The cap is a property of export_descr_unit.txt, so M2TWEOP units are not
  // counted — being outside that file is exactly what they are for.
  const current=(dd.edu_count!=null)?dd.edu_count:dd.units.length;
  let add=0, eopAdd=0;
  for(const t of composerList){ const c=cfgFor(t);
    const toEop=eopBound(t);
    if(isReplace(c)) continue;               // rewrites a unit that already exists
    if(have.has(t) && c.on_conflict!=='rename') continue;  // overwrite/skip: no net type
    if(toEop) eopAdd++; else add++;
  }
  return {current, add, eopAdd, projected:current+add, eop:dd.eop_count||0};
}
/* Will this unit's block be written to an M2TWEOP unit file rather than the EDU?
   Mirrors transfer._resolve_eop_target so the banner agrees with what apply does. */
function eopBound(type){
  const dd=state.destData, sd=state.srcData; if(!dd) return false;
  const want=(cfgFor(type).eop_target)||'auto';
  if(!(dd.eop_dirs||[]).length) return false;   // nowhere to write one
  if(want==='eop') return true;
  if(want==='edu') return false;
  const u=(sd&&sd.units||[]).find(x=>x.type===type);
  return !!(u&&u.eop);
}
const limitIgnored=mod=>(state.settings.unit_limit_ignored||[]).includes(mod);
function unitLimitBanner(){
  const p=projectedDestCount(); if(!p) return '';
  if(Math.max(p.current,p.projected)<=VANILLA_UNIT_LIMIT || limitIgnored(state.dst)) return '';
  const now=p.current>VANILLA_UNIT_LIMIT;
  const dd=state.destData||{};
  const hasEop=((dd.eop_dirs||[]).length>0);
  return `<div class="limitwarn">
    <b>⚠ Vanilla unit limit exceeded.</b>
    “${esc(state.dst)}” ${now?`already has ${p.current}`:`will have ${p.projected}`} units in
    export_descr_unit.txt
    (vanilla M2TW caps at ${VANILLA_UNIT_LIMIT}${p.add?`; this transfer adds ${p.add}`:''}).
    ${p.eop?`<div class="sub">Its ${p.eop} M2TWEOP unit${p.eop===1?'':'s'} don't count, because they load from the extender.${p.eopAdd?` This transfer adds ${p.eopAdd} more.`:''}</div>`:''}
    <div class="sub">Past ${VANILLA_UNIT_LIMIT}, unmodified M2TW crashes. With M2TWEOP / EOP it's fine.</div>
    <div class="acts">
      ${hasEop?`<button onclick="allToEop()">Write these as M2TWEOP units instead</button>`:''}
      <button onclick="ignoreLimit()">Ignore for “${esc(state.dst)}” (using m2ex/eop)</button>
      <span class="count">${hasEop?'':'Set the mod’s EOP folder in ⚙ Settings to use the first option. '}Re-enable in ⚙ Settings.</span>
    </div></div>`;
}
/* Flip every unit in the composer to "write as an M2TWEOP unit" — the one-click
   answer to the limit banner, which is the moment the user is actually thinking
   about where these units land. */
function allToEop(){
  for(const t of composerList) cfgFor(t).eop_target='eop';
  renderComposer();
  toast(`${composerList.length} unit(s) will be written as M2TWEOP unit files.`);
}
async function ignoreLimit(){
  const cur=(state.settings.unit_limit_ignored||[]).slice();
  if(!cur.includes(state.dst)) cur.push(state.dst);
  state.settings=await api.post('/api/settings',{unit_limit_ignored:cur});
  renderComposer();
  toast(`Unit-limit warning ignored for “${state.dst}”.`);
}
async function saveConsole(){
  const on=document.getElementById('consoleChk').checked;
  state.settings=await api.post('/api/settings',{show_console:on});
  toast(on?'Console will show on the next launch.':'Console hidden from the next launch.');}
async function quitServer(){
  if(!confirm('Stop the Medieval 2 GUI Toolkit server?\n\nThe page will stop working until you launch it again.'))return;
  try{await api.post('/api/quit',{});}catch(e){}
  document.body.innerHTML='<div class="empty" style="padding:60px">Medieval 2 GUI Toolkit server stopped.<br>'
    +'<span class="count">Run Launch-Medieval2-GUI-Toolkit.bat to start it again.</span></div>';}
/* Restart the tool in place, so a setting the server only reads at startup
   ("Keep the console window open") can be applied without going back to the
   launcher. The server answers, lets go of the port, starts a replacement on the
   same address and ends itself; this page waits for the new one and reloads. */
async function restartServer(){
  const want=!!(document.getElementById('consoleChk')||{}).checked;
  if(!confirm(`Restart the toolkit now?\n\nIt comes back on the same address, `+
    `${want?'with':'without'} a console window. Anything you have open but unsaved is lost.`))return;
  const m=document.getElementById('modal');
  m.className='modal';
  m.innerHTML=`<h2>Restarting…</h2><div class="mbody"><div class="count">
    Waiting for the toolkit to come back on this address. This page reloads by itself.</div></div>`;
  overlay.classList.add('open');
  try{await api.post('/api/restart',{console:want});}catch(e){}
  // The old server stops answering the moment it hands the port over, so this
  // polls rather than waiting on the response.
  const t0=Date.now();
  const tick=async()=>{
    try{
      const p=await fetch('/api/ping',{cache:'no-store'});
      if(p.ok){location.reload();return;}
    }catch(e){}
    if(Date.now()-t0>45000){
      m.innerHTML=`<h2>It has not come back</h2><div class="mbody"><div class="trnote w-warn">${docPoints(
        'The replacement server has not answered in 45 seconds.',
        ['If a console window opened, the reason will be in it.',
         'Otherwise start the tool again with Launch-Medieval2-GUI-Toolkit.bat.',
         'Nothing was written to your mods. A restart only touches this tool.'])}</div></div>
        <div class="foot"><button class="primary" onclick="location.reload()">Try this page again</button></div>`;
      return;
    }
    setTimeout(tick,700);
  };
  setTimeout(tick,1200);
}
/* Hand the user the diagnostic log as a file. A link rather than fetch+Blob so
   the browser's own download UI names it and drops it in Downloads — the point
   is that they can attach it to a message without ever finding config/. */
function downloadDiag(){
  const a=document.createElement('a');
  a.href='/api/diag'; a.download='';
  document.body.appendChild(a); a.click(); a.remove();
  toast('Diagnostic log saved to your Downloads folder.');}
async function saveClearBin(){
  await setClearBin(document.getElementById('clearBinChk').checked);}
async function saveSoldierBase(){
  const on=document.getElementById('soldierBaseChk').checked;
  state.settings=await api.post('/api/settings',{soldier_from_base:on});
  toast(on?'New base picks will default the soldier to the base.':'Soldier defaults to the source unit.');}
async function reenableLimit(mod){
  const cur=(state.settings.unit_limit_ignored||[]).filter(m=>m!==mod);
  state.settings=await api.post('/api/settings',{unit_limit_ignored:cur});
  toast(`Unit-limit warning re-enabled for “${mod}”.`); openSettings();
}

/* ---------- asset (texture/mesh) conflict resolver ---------- */
const modFolderName=()=>'unit_models/'+(state.src||'').replace(/[^A-Za-z0-9._-]+/g,'_').replace(/^_+|_+$/g,'');
function assetConflictUI(type,r){
  const c=cfgFor(type);
  const list=r.asset_conflicts||[];
  // three buckets, each with its own resolution mode: battle-model assets (which
  // can be relocated), icons (located by name, can't be) and siege-engine files
  // (can't be either — their textures are baked into the mesh binaries).
  const aConf=list.filter(x=>x.kind!=='icon'&&x.kind!=='engine');
  const iConf=list.filter(x=>x.kind==='icon');
  const eConf=list.filter(x=>x.kind==='engine');
  const aDiff=aConf.filter(x=>!x.identical), aIdent=aConf.filter(x=>x.identical);
  const iDiff=iConf.filter(x=>!x.identical);
  const eDiff=eConf.filter(x=>!x.identical);
  const reloc=(c.asset_conflict==='reroute'||c.asset_conflict==='mod_folder');
  let html='';
  // --- meshes / textures: keep, overwrite, or relocate (which avoids conflicts entirely)
  if(aConf.length||reloc){
    const warn=aDiff.length&&!reloc;
    html+=`<fieldset class="assetconf" ${warn?'':'style="border-color:var(--edge)"'}>
      <legend class="${warn?'w-warn':''}">Textures / meshes</legend>
      <div class="count">${docPoints(
        `${aConf.length} file(s) already exist at the same path.`,[
        `<b class="w-good">${aIdent.length}</b> identical, so they are reused.`,
        `<b class="${aDiff.length?'w-warn':''}">${aDiff.length}</b> differ.`,
        r.reroute_dir?`<span class="w-good">Relocating ${r.relocated_count} file(s) →
          <code>${esc(r.reroute_dir)}/</code>, so those have no conflict.</span>`:''])}</div>
      <div class="radio-row" style="margin-top:6px">
        <label><input type="radio" name="ac" value="mod_folder" ${c.asset_conflict==='mod_folder'?'checked':''}> Own folder: <code>${esc(modFolderName())}/</code> <b class="w-good">(default)</b></label>
        <label><input type="radio" name="ac" value="reroute" ${c.asset_conflict==='reroute'?'checked':''}> Reroute: choose a folder under <code>unit_models/</code></label>
        <label><input type="radio" name="ac" value="use_existing" ${c.asset_conflict==='use_existing'?'checked':''}> Keep the destination’s files</label>
        <label><input type="radio" name="ac" value="overwrite" ${c.asset_conflict==='overwrite'?'checked':''}> Overwrite with the source’s (backed up, undoable)</label>
      </div>
      <div id="rerouteBox" style="${c.asset_conflict==='reroute'?'':'display:none'};margin-top:8px">
        <div class="brbar">
          <input id="rrPath" value="${esc(c.asset_reroute_dir||'')}" placeholder="unit_models/MyFolder">
          <button onclick="brToggle()">Browse…</button>
        </div>
        <div id="brBox" style="${state.brOpen?'':'display:none'}">
          <div class="brbar" style="margin-top:6px">
            <button onclick="brUp()">↑ Up</button><span class="count" id="brNow"></span>
          </div>
          <div class="brlist" id="brList"></div>
          <div class="brbar" style="margin-top:6px">
            <input id="brNew" placeholder="new sub-folder name">
            <button onclick="brMakeSub()">Use new sub-folder</button>
          </div>
        </div>
      </div>
      ${reloc?`<div class="count" style="margin-top:6px">Files keep their folder structure, and the new modeldb entries point at the new paths.</div>`:''}
      ${aDiff.length&&!reloc?`<div class="flist">${aDiff.map(x=>`<div class="frow"><span class="fp">${esc(x.rel)}</span><span class="fs">src ${x.src_size}B vs dest ${x.dst_size}B${x.src_size===x.dst_size?' (same size, different bytes)':''}</span></div>`).join('')}</div>`:''}
    </fieldset>`;
  }
  // --- icons: located by faction folder + dictionary, so they can't be relocated
  if(iConf.length){
    html+=`<fieldset class="assetconf" ${iDiff.length?'':'style="border-color:var(--edge)"'}>
      <legend class="${iDiff.length?'w-warn':''}">Unit card / info icons</legend>
      <div class="count">${docPoints(`${iConf.length} icon(s) already exist.`,[
        `<b class="w-good">${iConf.length-iDiff.length}</b> identical,
         <b class="${iDiff.length?'w-warn':''}">${iDiff.length}</b> differ.`,
        `Icons are found by faction folder + name, so they can't be rerouted.`,
        r.replace_type?`To import a card over <b>${esc(r.replace_type)}</b>'s, pick overwrite.`:''
        ])}</div>
      ${iDiff.length?`<div class="radio-row" style="margin-top:6px">
        <label><input type="radio" name="ic" value="use_existing" ${c.icon_conflict!=='overwrite'?'checked':''}> Keep the existing icon</label>
        <label><input type="radio" name="ic" value="overwrite" ${c.icon_conflict==='overwrite'?'checked':''}> Overwrite with the source’s</label>
      </div>
      <div class="flist">${iDiff.map(x=>`<div class="frow"><span class="fp">${esc(x.rel)}</span><span class="fs">src ${x.src_size}B vs dest ${x.dst_size}B</span></div>`).join('')}</div>`:''}
    </fieldset>`;
  }
  // --- siege-engine files: texture paths are baked into each mesh, so no relocation
  if(eConf.length){
    html+=`<fieldset class="assetconf" ${eDiff.length?'':'style="border-color:var(--edge)"'}>
      <legend class="${eDiff.length?'w-warn':''}">Siege-engine files</legend>
      <div class="count">${docPoints(`${eConf.length} engine file(s) already exist.`,[
        `<b class="w-good">${eConf.length-eDiff.length}</b> identical,
         <b class="${eDiff.length?'w-warn':''}">${eDiff.length}</b> differ.`,
        `Each mesh has its texture paths baked in, so they can't be relocated.`])}</div>
      ${eDiff.length?`<div class="radio-row" style="margin-top:6px">
        <label><input type="radio" name="ec" value="use_existing" ${c.engine_conflict!=='overwrite'?'checked':''}> Keep the destination’s <b class="w-good">(default)</b>. The imported engine may wear its skin.</label>
        <label><input type="radio" name="ec" value="overwrite" ${c.engine_conflict==='overwrite'?'checked':''}> Overwrite, which also re-skins ${esc(state.dst)}’s own engines</label>
      </div>
      <div class="flist">${eDiff.map(x=>`<div class="frow"><span class="fp">${esc(x.rel)}</span><span class="fs">src ${x.src_size}B vs dest ${x.dst_size}B</span></div>`).join('')}</div>`:''}
    </fieldset>`;
  }
  // --- vanilla files the engine needs that the DESTINATION overrides
  const ovr=r.engine_dest_overrides||[];
  if(ovr.length){
    html+=`<fieldset class="assetconf"><legend class="w-warn">Engine override warning</legend>
      <div class="count">${docPoints(`${ovr.length} vanilla file(s) the engine uses are overridden
        by ${esc(state.dst)} but not by ${esc(state.src)}.`,[
        `Nothing is copied: ${esc(state.dst)}’s version wins and may not match.`,
        'Check these by hand:'])}</div>
      <div class="flist">${ovr.map(p=>`<div class="frow"><span class="fp">${esc(p)}</span></div>`).join('')}</div>
    </fieldset>`;
  }
  // --- descr_engine_skeleton.txt entries (a mounted engine's `class` lands here)
  const skel=r.engine_skeleton_actions||[];
  if(skel.length){
    const kept=skel.filter(x=>x.action==='reuse');
    html+=`<fieldset class="assetconf" ${kept.length?'':'style="border-color:var(--edge)"'}>
      <legend class="${skel.some(x=>x.action==='vanilla')?'w-warn':''}">Engine skeletons (<code>descr_engine_skeleton.txt</code>)</legend>
      <div class="count">An entry ${esc(state.dst)} already has is reused as-is, never overwritten.</div>
      <div class="flist">${skel.map(x=>`<div class="frow"><span class="fp">${esc(x.name)}</span><span class="fs ${
        x.action==='vanilla'?'w-warn':x.action==='add'?'w-good':''}">${esc(x.action)}: ${esc(x.detail)}</span></div>`).join('')}</div>
    </fieldset>`;
  }
  return html;
}
function wireAssetConflict(type){const c=cfgFor(type);
  document.querySelectorAll('input[name=ac]').forEach(r=>r.onchange=()=>{c.asset_conflict=r.value;doPreview();});
  document.querySelectorAll('input[name=ic]').forEach(r=>r.onchange=()=>{c.icon_conflict=r.value;doPreview();});
  document.querySelectorAll('input[name=ec]').forEach(r=>r.onchange=()=>{c.engine_conflict=r.value;doPreview();});
  const rr=document.getElementById('rrPath');
  if(rr){rr.oninput=()=>{c.asset_reroute_dir=rr.value;};
         rr.onchange=()=>{c.asset_reroute_dir=rr.value;doPreview();};}
  if(state.brOpen&&c.asset_conflict==='reroute')brLoad(state.brPath||'unit_models');}

/* ---------- destination folder browser (for Reroute) ---------- */
function brToggle(){state.brOpen=!state.brOpen;
  const b=document.getElementById('brBox'); if(b)b.style.display=state.brOpen?'':'none';
  if(state.brOpen)brLoad(state.brPath||'unit_models');}
async function brLoad(path){
  let r; try{r=await api.get(`/api/dirs?mod=${encodeURIComponent(state.dst)}&path=${encodeURIComponent(path)}`);}
  catch(e){return;}
  if(r.error)return;
  state.brPath=r.path;
  const now=document.getElementById('brNow'); if(now)now.textContent=r.path+'/';
  const list=document.getElementById('brList'); if(!list)return;
  list.innerHTML=(r.dirs||[]).map(d=>`<div class="brrow" onclick="brEnter('${q1(esc(d))}')">📁 ${esc(d)}</div>`).join('')
    ||'<div class="count" style="padding:6px">(no sub-folders here)</div>';
  brSetPath(r.path);
}
function brSetPath(p){const rr=document.getElementById('rrPath');
  cfgFor(state.editing).asset_reroute_dir=p; if(rr)rr.value=p;}
function brEnter(name){brLoad((state.brPath||'unit_models')+'/'+name);}
function brUp(){const p=(state.brPath||'unit_models').split('/'); if(p.length>1){p.pop();brLoad(p.join('/'));}}
function brMakeSub(){const n=(document.getElementById('brNew')?.value||'').trim();
  if(!n){toast('Type a folder name first');return;}
  brSetPath((state.brPath||'unit_models')+'/'+n.replace(/[\\/]+/g,'_'));
  doPreview();}

async function doPreview(){
  const type=state.editing; const box=document.getElementById('previewBox'); if(!box)return null;
  box.innerHTML='<div class="preview">Planning…</div>';
  const r=await api.post('/api/plan',{source:state.src,dest:state.dst,unit:type,options:optsPayload(type)});
  if(state.editing!==type) return r;          // user switched units mid-plan
  if(r.error){box.innerHTML=`<div class="preview w-bad">${esc(r.error)}</div>`;
              paintSoldierAnim(null);return null;}
  paintSoldierAnim(r);
  // the "(soldier line)" animation line is shown beside the Soldier row instead
  let html=renderSummary((r.summary||'').split('\n')
    .filter(l=>!/ANIMATION WARNING \(soldier line\)/.test(l)).join('\n'));
  cfgFor(type)._conflict=r.unit_conflict;
  // Having rendered the conflict fieldset (with its pre-filled rename defaults, editable
  // right here) IS the review step — don't also force a redundant "Apply again" pause in
  // doApply() for a unit whose resolution the user already saw and could adjust.
  if(r.unit_conflict) cfgFor(type)._resolved=true;
  if(r.unit_conflict) html+=conflictUI(type);
  html+=eopUI(type,r);
  html+=assetConflictUI(type,r);
  box.innerHTML=html; wireConflict(type); wireEop(type); wireAssetConflict(type);
  return r;
}
/* Missing animations, shown against the row that can fix them.
   A skeleton is an animation pack the destination either has or hasn't — copying a
   battle model does not bring one along, and M2TW does not shrug it off: a model
   asking for an animation set the mod doesn't have takes the game down on load.
   The plan reports every missing skeleton in the summary, but this warning belongs
   beside the SOLDIER row and only when the soldier line's own model is the one
   asking, because switching that row to the base / replaced unit is the fix. An
   officer's or a mount's missing skeleton is not this row's to answer for.
   Filled in from the plan rather than at render time: renderComposer() is what
   builds the row, and it is renderComposer() that kicks off the plan. */
function paintSoldierAnim(r){
  const el=document.getElementById('soldierAnim'); if(!el)return;
  const c=cfgFor(state.editing), rep=isReplace(c);
  const who=rep?`“${esc(c.base_type||'the replaced unit')}”`:'the base unit';
  const list=a=>(a||[]).map(s=>`<code>${esc(s)}</code>`).join(', ');
  const out=[];
  const miss=(r&&r.soldier_skeletons_missing)||[];
  if(miss.length){
    const mdl=(r.soldier_model_name||'').trim();
    out.push(`<b>⚠ Missing animation${miss.length===1?'':'s'}</b>
      <ul>
        <li>${esc(state.dst)} has no ${list(miss)}${
          mdl?`, which the soldier model <code>${esc(mdl)}</code> asks for`:''}.</li>
        <li>A soldier entry whose animation set is not in the mod <b>crashes the game
          on load</b>.</li>
        <li>Fix: set this row to <b>Base</b> and the unit keeps ${who}’s model and
          animations.</li>
        <li>Or import the animation set into this mod first (anim pack +
          <code>descr_skeleton.txt</code>). Only do that if you already know how.</li>
      </ul>`);
  }
  // Taking the base's soldier entry always loads, but it also swaps the animation
  // set — a pikeman animated as a swordsman fights wrong and nothing says why.
  const chg=(r&&r.soldier_anim_changed)||[];
  if(chg[0]&&chg[1]&&chg[0]!==chg[1]){
    out.push(`<b>⚠ Different animation set</b>
      <ul>
        <li>This unit was animated as ${list(chg[0].split(', '))}.</li>
        <li>Taking the soldier line from ${who} animates it as ${list(chg[1].split(', '))}.</li>
        <li>It will load, but attack timing and reach come from the animation, so it
          may perform unexpectedly in battle.</li>
      </ul>`);
  }
  // An armour-upgrade entry is a visual swap; the engine never plays its skeleton.
  const cos=(r&&r.cosmetic_skeletons_missing)||[];
  if(cos.length){
    out.push(`<b>Armour-upgrade animations</b>
      <ul>
        <li>${esc(state.dst)} has no ${list(cos)}, named by an armour-upgrade model.</li>
        <li>Not a crash: the engine animates the unit from its <b>soldier</b> entry.</li>
      </ul>`);
  }
  el.innerHTML=out.join('');
  el.hidden=!out.length;
}
/* Where the unit's EDU block gets written. Shown whenever the destination has an
   M2TWEOP folder OR the source unit is an EOP unit — the second case matters even
   with no folder, because that is the transfer that silently demotes a unit into
   the EDU and pushes the mod towards the 500 cap. */
function eopUI(type,r){
  const c=cfgFor(type);
  // Replacing has nothing to choose: the rewritten block stays in whichever file
  // the replaced unit already lives in, EDU or M2TWEOP.
  if(r.replace_type) return `<fieldset class="assetconf" style="margin-top:10px;border-color:var(--edge)">
    <legend>Which file this unit is written to</legend>
    <div class="count">It replaces <b>${esc(r.replace_type)}</b> where it already is${
      r.eop_file?` in <span class="path">${esc(r.eop_file)}</span>`:' in <code>export_descr_unit.txt</code>'}.
      Nothing moves, and the ${VANILLA_UNIT_LIMIT}-unit cap is untouched.</div></fieldset>`;
  if(!r.dest_has_eop && !r.source_is_eop) return '';
  const auto=r.source_is_eop?'M2TWEOP unit file (the source unit is one)':'export_descr_unit.txt';
  return `<fieldset class="assetconf" style="margin-top:10px${r.source_is_eop&&!r.dest_has_eop?';border-color:var(--warn)':''}">
    <legend${r.source_is_eop?' class="w-warn"':''}>Which file this unit is written to</legend>
    <div class="count">${docPoints(
      r.source_is_eop?`“${esc(type)}” is an <b>M2TWEOP unit</b> in the source mod.`
                     :`Where this unit lands in ${esc(state.dst)}:`,[
      r.dest_has_eop?`“${esc(state.dst)}” has an EOP folder, so it can hold M2TWEOP units.`
                    :`“${esc(state.dst)}” has <b>no EOP folder set</b>, so this goes into
                      export_descr_unit.txt. Set one in ⚙ Settings to keep it out.`,
      r.dest_has_eop?`M2TWEOP units don't count against the ${VANILLA_UNIT_LIMIT}-unit cap.`
                    :`It therefore <b>does</b> count against the ${VANILLA_UNIT_LIMIT}-unit cap.`])}
    </div>
    ${r.dest_has_eop?`<div class="radio-row" style="margin-top:6px">
      <label><input type="radio" name="eopt" value="auto" ${(c.eop_target||'auto')==='auto'?'checked':''}> Same as the source (${esc(auto)})</label>
      <label><input type="radio" name="eopt" value="eop" ${c.eop_target==='eop'?'checked':''}> M2TWEOP unit file</label>
      <label><input type="radio" name="eopt" value="edu" ${c.eop_target==='edu'?'checked':''}> export_descr_unit.txt</label>
    </div>`:''}
    ${r.eop_file?`<div class="count" style="margin-top:6px">Will be written to <span class="path">${esc(r.eop_file)}</span>.</div>`:''}
  </fieldset>`;
}
function wireEop(type){const c=cfgFor(type);
  document.querySelectorAll('input[name=eopt]').forEach(x=>x.onchange=()=>{c.eop_target=x.value;doPreview();});
}
function conflictUI(type){const c=cfgFor(type);const u=state.data.units.find(x=>x.type===type);
  if(!c.new_type)c.new_type=type+' (copy)'; if(!c.new_dictionary)c.new_dictionary=u.dictionary+'_copy';
  // Same mod = the "new unit" flow: the clash with the original is the whole point,
  // so ask for the new unit's names instead of warning about a conflict.
  const sameMod=state.src===state.dst;
  if(sameMod) return `<fieldset style="margin-top:10px"><legend>Name for the new unit</legend>
    <div class="rename-fields" id="rf" style="padding-left:0">
      <label>New type<input id="nt" value="${esc(c.new_type)}"></label>
      <label>New dictionary<input id="nd" value="${esc(c.new_dictionary)}"></label>
    </div>
    <div class="count">The original “${esc(type)}” stays as it is.</div></fieldset>`;
  return `<fieldset style="margin-top:10px;border-color:var(--warn)"><legend class="w-warn">Unit already exists in destination</legend>
    <div class="radio-row">
      <label><input type="radio" name="cf" value="rename" ${c.on_conflict==='rename'?'checked':''}> Rename</label>
      <label><input type="radio" name="cf" value="overwrite" ${c.on_conflict==='overwrite'?'checked':''}> Overwrite existing</label>
      <label><input type="radio" name="cf" value="skip" ${c.on_conflict==='skip'?'checked':''}> Skip</label>
    </div>
    <div class="rename-fields" id="rf">
      <label>New type<input id="nt" value="${esc(c.new_type)}"></label>
      <label>New dictionary<input id="nd" value="${esc(c.new_dictionary)}"></label>
    </div></fieldset>`;
}
function wireConflict(type){const c=cfgFor(type);
  document.querySelectorAll('input[name=cf]').forEach(r=>r.onchange=()=>{c.on_conflict=r.value;document.getElementById('rf').style.display=r.value==='rename'?'':'none';});
  const nt=document.getElementById('nt'),nd=document.getElementById('nd');
  if(nt)nt.oninput=()=>c.new_type=nt.value; if(nd)nd.oninput=()=>c.new_dictionary=nd.value;
  const rf=document.getElementById('rf');
  if(rf&&state.src!==state.dst)rf.style.display=c.on_conflict==='rename'?'':'none';
}

const PROG_ICON={pending:'·',current:'⟳',done:'✓',error:'✗',skipped:'~'};
const PROG_CLS={current:'w-warn',done:'w-good',error:'w-bad',skipped:''};
function renderProgress(types,status){
  const done=status.filter(s=>s==='done'||s==='error'||s==='skipped').length;
  const curIdx=status.indexOf('current');
  const pct=types.length?Math.round((done/types.length)*100):0;
  const rows=types.map((t,i)=>{
    const st=status[i];
    return `<div class="proglist-row ${PROG_CLS[st]||''}"><span class="pi">${PROG_ICON[st]}</span> ${esc(t)}</div>`;
  }).join('');
  document.getElementById('modal').innerHTML=`<h2>Transferring…</h2>
    <div class="mbody">
      <div class="progress-track"><div class="progress-fill" style="width:${pct}%"></div></div>
      <div class="count" style="margin:8px 0 12px">${done} of ${types.length} done
        ${curIdx>=0?`: <b>${esc(types[curIdx])}</b>`:''}</div>
      <div class="proglist">${rows}</div>
    </div>`;
}

/* Real progress for the long BMDB jobs (the scan and the cleanup). Each is ONE
   request that runs for seconds, so the server reports where it is under a job id
   and this polls that id alongside the request — a bar parked at a made-up width
   is exactly what this replaces. Polling stops the moment the request settles. */
const newJob=()=>'j'+Date.now().toString(36)+Math.random().toString(36).slice(2,7);
function jobBox(title,note){
  document.getElementById('modal').innerHTML=`<h2>${esc(title)}</h2>
    <div class="mbody">
      <div class="progress-track"><div class="progress-fill" id="jobFill" style="width:0%"></div></div>
      <div class="count" style="margin-top:8px"><b id="jobPct">0%</b>
        <span id="jobStep">starting…</span></div>
      <div class="count" style="margin-top:10px">${note}</div>
    </div>`;
}
// Only touches the bar if it is still on screen — the job's own result replaces
// the modal, and a late poll must not paint over it.
function jobPaint(pct,label){
  const f=document.getElementById('jobFill'); if(!f)return;
  f.style.width=Math.max(0,Math.min(100,pct))+'%';
  document.getElementById('jobPct').textContent=pct+'%';
  document.getElementById('jobStep').textContent=label||'';
}
async function runJob(job,title,note,run){
  let done=false;
  jobBox(title,note);
  (async()=>{while(!done){
    await new Promise(r=>setTimeout(r,300));
    if(done)break;
    // one try, no retries: a dropped poll just means the next one paints instead
    let p=null; try{p=await api.get('/api/progress?job='+enc(job),1);}catch(e){}
    if(!done&&p&&typeof p.pct==='number')jobPaint(p.pct,p.label||'');
  }})();
  try{ return await run(); } finally{ done=true; }
}
async function doApply(){
  const types=composerList.length?composerList:[state.editing];
  // ensure conflicts are resolved: preview each; if conflict and not yet resolved, focus it
  for(const t of types){
    const r=await api.post('/api/plan',{source:state.src,dest:state.dst,unit:t,options:optsPayload(t)});
    if(r.error){toast(`${t}: ${r.error}`);state.editing=t;renderComposer();await doPreview();return;}
    if(r.base_error){toast(`${t}: ${r.base_error}`);state.editing=t;renderComposer();return;}
    if(r.option_error){toast(`${t}: ${r.option_error}`);state.editing=t;renderComposer();return;}
    if(r.unit_conflict && !cfgFor(t)._resolved){ state.editing=t;renderComposer();await doPreview();
      toast(`“${t}” already exists in the destination. Choose rename, overwrite or skip, then Apply again.`);
      cfgFor(t)._resolved=true; return; }
  }
  let ok=0,skip=0,last=null;
  const status=types.map(()=>'pending');
  for(let i=0;i<types.length;i++){
    const t=types[i];
    status[i]='current'; renderProgress(types,status);
    const res=await api.post('/api/apply',{source:state.src,dest:state.dst,unit:t,
      options:optsPayload(t),
      // once per batch, after the last unit — clearing it earlier just lets the
      // game recompile the cache before the batch has finished writing
      clear_strings_bin:clearBinOn()&&i===types.length-1});
    if(res.error){status[i]='error';renderProgress(types,status);toast(`${t}: ${res.error}`);return;}
    if(res.strings_bin)last=res;
    if(res.plan&&res.plan.skipped){skip++;status[i]='skipped';} else {ok++;status[i]='done';}
    renderProgress(types,status);
  }
  closeModal();
  const repl=types.filter(t=>isReplace(cfgFor(t))).length;
  toast(`${state.src===state.dst?'Created':repl===ok?'Replaced':'Transferred'} ${ok} unit(s)${
    repl&&repl!==ok?` (${repl} replaced)`:''}${skip?`, skipped ${skip}`:''} ✓${binMsg(last)}  (undo in 🕑 Log)`,4200);
  // these ones are done — leaving them ticked invites transferring them twice
  clearSelection();
  state.cfg={};
  if(state.dst===state.src)loadSource();
}

/* ---------- batch open ---------- */
function openBatch(){ if(!state.selected.size)return; openComposer([...state.selected]); }
