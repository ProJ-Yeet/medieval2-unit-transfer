/* editor.js — Unit Editor mode: EDU fields, identity, model entries, textures

   Part of the Medieval 2 GUI Toolkit UI. These files are plain
   <script> tags sharing ONE global scope, loaded in the order set in
   index.html — there is no build step and no module system. Two rules
   follow from that: a top-level name must be unique across all of
   them, and a file's top-level side effects may not depend on a file
   loaded after it. */
/* ======================= UNIT EDITOR (edit mode) =======================
   Edits one mod in place: EDU fields, the localised name/description, the
   battle_models.modeldb entries the unit uses (including creating a new entry
   from an existing one), and deleting the unit. Every apply goes through the
   same backup + log as a transfer, so 🕑 Log → Undo reverts it. */
const enc=encodeURIComponent;
const modRoot=n=>(state.mods.find(m=>m.name===n)||{}).root||'';
// A native dialog hands back an absolute path; show it as the mod-relative one
// the game actually uses (the server accepts either).
function relInMod(p){
  const root=modRoot(state.src); if(!p||!root)return p||'';
  const norm=s=>s.replace(/\\/g,'/').replace(/\/+$/,'');
  const r=norm(root)+'/data/', s=norm(p);
  return s.toLowerCase().startsWith(r.toLowerCase())?s.slice(r.length):s;
}

async function openEditor(type){
  activity('opened unit',`${type} in ${state.src}`);
  const modal=document.getElementById('modal');
  modal.className='modal wide'; modal.innerHTML='<h2>Loading unit…</h2>';
  overlay.classList.add('open');
  let d;
  try{ d=await api.get(`/api/edit/unit?mod=${enc(state.src)}&type=${enc(type)}`); }
  catch(e){ modal.innerHTML=`<h2>Unit editor</h2><div class="mbody w-bad">${esc(''+e)}</div>
    <div class="foot"><button onclick="closeModal()">Close</button></div>`; return; }
  if(d.error){ modal.innerHTML=`<h2>Unit editor</h2><div class="mbody w-bad">${esc(d.error)}</div>
    <div class="foot"><button onclick="closeModal()">Close</button></div>`; return; }
  state.ed={mod:state.src,unit:type,d,tab:'identity',ov:{},rm:new Set(),
            loc:Object.assign({},d.loc),newType:'',newDict:'',
            mEdits:{},newModels:[],open:{},form:null,removeOldIcons:false,added:new Set(),
            // replacement card / info card picked off disk, applied on save
            cardSrc:'',infoSrc:'',
            // per-entry UI state: which faction has its "unique textures" panel
            // open, and the last /api/edit/model_folder answer for its folder box
            facOpen:{},folder:{},
            // the Code View pane on the EDU fields tab (null until it's opened),
            // and the modeldb one on the Models tab — one card at a time
            cv:null,mcv:null,mcvName:'',
            // the Compare tab: a SECOND unit loaded beside this one, with edits
            // of its own that Save writes as a second, independent unit save
            cmp:null,cmpQ:'',cmpSame:false,
            ug:null};      // the armour-tier ＋ menu, closed
  undoReset();
  resetPlace();            // a different unit starts at the top, not where the last one sat
  renderEditor();
  // the code pane is remembered: whoever works with it wants it on every unit,
  // and it is fetched after the first paint so it never delays the dialog
  if(state.settings.code_view){
    const e=state.ed;
    e.cv=cvCreate(edCvHost());
    cvLoad(e.cv).then(()=>{if(state.ed===e&&e.tab==='fields')edRenderTab();});
  }
}
// Every unit opens in its own browser tab, so you can follow "this model is also
// used by X" without losing the edits in the tab you came from.
function openUnitTab(type){
  window.open(`/?mod=${enc(state.ed?state.ed.mod:state.src)}&edit=${enc(type)}`,'_blank');
}
// A model's users are unit types, plus "mount:<name>" / "file:<name>" referrers
// which are not units and so have no editor to open.
function userLink(name){
  return /^(mount|file):/.test(name) ? `<span class="count">${esc(name)}</span>`
    : `<a class="ulink" onclick="openUnitTab('${q1(esc(name))}')">${esc(name)}</a>`;
}
function edDirty(){
  const e=state.ed; if(!e)return false;
  return !!(Object.keys(e.ov).length||e.rm.size||e.newModels.length||
            edModelEdits().length||e.newType||e.newDict||edCvUserEdited()||
            (e.tierEdit&&Object.keys(e.tierEdit).length)||
            JSON.stringify(e.loc)!==JSON.stringify(e.d.loc));
}
// Has the unit's block been hand-edited in Code View? `base` is what the text
// pane last parsed cleanly, `pristine` what the file said when it opened. Note
// this stays true while the pane shows an error: the last GOOD text is still
// the one a save would write, and dropping it silently back to the file's
// version would throw away work the user can still see on screen. What an error
// does stop is the save itself — see edCvBlocked().
// Keyed on the kind because bmdb mode shares `state.ed`: its pane holds a
// modeldb entry, which goes to the save as `raw_entry` on the model edit, never
// as the unit block's `raw_block`.
function edCvEdited(){
  const cv=state.ed&&state.ed.cv;
  return !!(cv&&cv.kind==='edu'&&cv.loaded&&cv.base!==cv.pristine);
}
/* …and the narrower question the DIALOG asks: is there anything to save.

   The pane lines the block up the moment it opens (cvAutoTidy), so opening it
   already makes `edCvEdited` true — and a view toggle that says "unsaved
   changes" and offers to throw work away on close is a lie about what the user
   did. The tool's own layout pass is remembered as `cv.auto`, so this can tell
   the two apart: it is not a reason to save on its own, and the moment there IS
   one the tidied text is what gets written. */
function edCvUserEdited(){
  const cv=state.ed&&state.ed.cv;
  if(!cv||cv.kind!=='edu'||!cv.loaded)return false;
  return cv.base!==cv.pristine&&cv.base!==cv.auto;
}
// The text pane can't be read, so neither Preview nor Save may run: they would
// act on the last good text while the screen shows something else.
function edCvBlocked(){
  const cv=state.ed&&state.ed.cv;
  if(!cv||!cv.err)return '';
  return 'The code view can’t be read: '+cv.err+
    ' Fix the line, or undo your typing, before saving.';
}
/* ---- what each touched bmdb entry sends ----
   Texture paths go by faction + kind, never by span index: ticking a faction on
   or off renumbers every texture slot in the entry, so an index captured by the
   page would land on the wrong one. Meshes keep using indices — those are stable. */
function edModelEdits(){
  const e=state.ed;
  // an entry hand-edited in Code View is a change even if no box was touched
  const cvName=(e.cv&&e.cv.kind==='bmdb'&&e.cv.owns)?e.cv.id:'';
  const names=Object.keys(e.mEdits);
  if(cvName&&!names.includes(cvName))names.push(cvName);
  return names.map(name=>{
    const me=e.mEdits[name]||{};
    if(!me._touched&&name!==cvName)return null;
    const m=e.d.models.find(x=>x.name===name); if(!m)return null;
    const v=edTexView(m), kinds=edKinds(m), faction_paths={};
    edFacs(m).forEach(f=>{
      const o={},cur=v.facs[f]||{};
      kinds.forEach(k=>{ if(cur[k]&&cur[k]!==v.defs[k])o[k]=cur[k]; });
      if(Object.keys(o).length)faction_paths[f]=o;
    });
    return {entry:name,new_name:me.new_name||'',paths:me.paths||{},copies:me.copies||[],
      // the entry as hand-edited in Code View; everything above applies on top
      raw_entry:name===cvName?e.cv.base:'',
      imports:(me.imports||[]).map(x=>({src:x.src,dest_dir:x.dest_dir})),
      defaults:v.defs,faction_paths,factions:me.factions||null,
      move_dir:me.move_dir||'',move_shared:!!me.move_shared};
  }).filter(Boolean);
}
function edPayload(extra){
  const e=state.ed;
  const locChanged=JSON.stringify(e.loc)!==JSON.stringify(e.d.loc);
  return Object.assign({mod:e.mod,unit:e.unit,new_type:e.newType,new_dictionary:e.newDict,
    // a block edited as text replaces the file's; the boxes still apply on top
    raw_block:edCvEdited()?e.cv.base:'',
    field_overrides:e.ov,remove_fields:[...e.rm],loc:locChanged?e.loc:null,
    model_edits:edModelEdits(),new_models:e.newModels,
    card_src:e.cardSrc||'',info_src:e.infoSrc||'',
    // absent (not "") unless the user touched it — clearing a tier and never
    // setting one are different requests, and the server tells them apart
    tier:(e.tierEdit&&'tier' in e.tierEdit)?e.tierEdit.tier:null,
    tier_variant:(e.tierEdit&&'tier_variant' in e.tierEdit)?e.tierEdit.tier_variant:null,
    remove_old_icons:!!e.removeOldIcons},extra||{});
}
function renderEditor(){
  const e=state.ed,d=e.d;
  const tab=(k,label)=>`<button class="${e.tab===k?'on':''}" onclick="edTab('${k}')">${label}</button>`;
  document.getElementById('modal').innerHTML=`
    <h2>Edit unit <span class="pill">${esc(e.mod)}</span></h2>
    <div class="ehead">
      <img onerror="iconRetry(this)" src="${iconUrl(e.mod,e.unit)}">
      <div><div class="nm">${esc(e.loc.name||d.type)}${
        d.eop?'<span class="badge eop" style="margin-left:6px;vertical-align:middle">EOP</span>':''}</div>
        <div class="count">${esc(d.type)} · dictionary <code>${esc(d.dictionary)}</code>
          · ${d.models.length} model entr${d.models.length===1?'y':'ies'}</div>
        <div class="count">${d.eop
          ? `M2TWEOP unit. Saves are written to <code>${esc(d.eop_file)}</code>, not to export_descr_unit.txt.`
          : 'Defined in <code>data/export_descr_unit.txt</code>.'}</div></div>
    </div>
    <div class="tabs">${tab('identity','Identity & text')}${tab('fields','EDU fields')}
      ${tab('models','Battle models (bmdb)')}${tab('compare','⇄ Compare')}</div>
    <div class="mbody" id="edBody"></div>
    <div class="foot">
      <button class="danger" onclick="edDeleteDialog()">🗑 Delete unit…</button>
      <span id="edDirtyNote"></span>
      <span class="count" title="Takes back one value at a time, without closing this dialog">
        ⌨ Ctrl+Z undo · Ctrl+Y redo</span>
      ${state.bldReturn?`<button onclick="backToBuilding()"
        title="Return to the building editor exactly as you left it">← ${esc(state.bldReturn.label)}</button>`:''}
      ${cleanerBoxHtml()}
      <button onclick="closeModal()">Close</button>
      <button onclick="edPreview()">Preview</button>
      <button class="primary" onclick="edSave()">Save changes</button>
    </div>`;
  edRenderTab();
}
function edTab(t){state.ed.tab=t;renderEditor();}
function edRenderTab(){
  const e=state.ed,b=document.getElementById('edBody');
  // Editing anything re-renders the whole tab, and replacing innerHTML throws
  // every scroll position back to the top — both the dialog's and the EDU field
  // list's own box. Ticking a faction 40 rows down must leave you looking at it,
  // not at the top of the unit, so both are put back afterwards.
  const modal=document.getElementById('modal');
  const wasModal=modal?modal.scrollTop:0;
  const fields=document.getElementById('allFields');
  const wasFields=fields?fields.scrollTop:0;
  const gbody=document.getElementById('gfBody');
  const wasG=gbody?gbody.scrollTop:0;
  b.innerHTML=(e.tab==='identity'?edIdentity():e.tab==='fields'?edFields()
              :e.tab==='compare'?edCompare():edModels())
    // bmdb mode edits an entry with no unit around it, so "who uses this?" has
    // nowhere else to live — it goes at the bottom of the entry itself
    +(e.bmdb?edEntryUsers(e.d.models[0]):'')
    +'<div id="edPreview"></div>';
  // keep the last preview visible across cosmetic re-renders (tab switch, expanding
  // an entry) — flagged as stale once anything has been edited since it was made
  if(e.plan)document.getElementById('edPreview').innerHTML=edPlanHtml(e.plan,e.planStale);
  if(e.tab==='fields')edWireFields();
  if(e.tab==='identity')edWireIdentity();
  if(e.tab==='models')edWireModels();
  if(e.tab==='compare')edWireCompare();
  const nowFields=document.getElementById('allFields');
  if(nowFields&&wasFields)nowFields.scrollTop=wasFields;
  const nowG=document.getElementById('gfBody');
  if(nowG&&wasG)nowG.scrollTop=wasG;
  if(modal&&wasModal)modal.scrollTop=wasModal;
  paintDirty();
}
function edWireModels(){
  document.querySelectorAll('#edBody input[data-entry]').forEach(inp=>{
    inp.oninput=()=>{const name=inp.dataset.entry,i=+inp.dataset.i;
      const m=state.ed.d.models.find(x=>x.name===name);
      const orig=(m.paths.find(p=>p.i===i)||{}).value;
      const me=edTouch(name);
      if(inp.value!==orig)me.paths[i]=inp.value; else delete me.paths[i];
      inp.classList.toggle('changed',inp.value!==orig);};
  });
  document.querySelectorAll('#edBody input[data-def]').forEach(inp=>{
    inp.oninput=()=>{const name=inp.dataset.def,k=inp.dataset.kind;
      const m=state.ed.d.models.find(x=>x.name===name),me=edTouch(name),v=inp.value.trim();
      if(v&&v!==m.texture_defaults[k])me.defaults[k]=v; else delete me.defaults[k];
      inp.classList.toggle('changed',k in me.defaults);};
  });
  document.querySelectorAll('#edBody input[data-fac]').forEach(inp=>{
    inp.oninput=()=>{const name=inp.dataset.fac,f=inp.dataset.f,k=inp.dataset.kind;
      const me=edTouch(name),v=inp.value.trim();
      const fp=me.faction_paths[f]||(me.faction_paths[f]={});
      if(v)fp[k]=v; else delete fp[k];
      if(!Object.keys(fp).length)delete me.faction_paths[f];
      inp.classList.toggle('changed',!!v);};
  });
  // …and the modeldb pane, when a model card has one open
  const e=state.ed;
  if(e.mcv&&e.mcv.loaded){
    cvWire(e.mcv);
    const idx=(e.d.models||[]).findIndex(m=>m.name===e.mcvName);
    cvBindHover(e.mcv,document.getElementById('edmGui'+idx));
  }
  // any box on this tab moves the pane's text with it
  document.querySelectorAll('#edBody input[data-entry],#edBody input[data-def],'
    +'#edBody input[data-fac]').forEach(inp=>{
      const prev=inp.oninput;
      inp.oninput=ev=>{if(prev)prev.call(inp,ev); cvFromGui(state.ed.mcv);};
    });
}
// Where an imported texture should land: alongside the one it replaces, else in
// the model folder's textures/ (sprites live in their own shared folder).
function edImportDir(m,kind){
  const cur=edTexView(m).defs[kind]||'';
  if(cur.includes('/'))return cur.slice(0,cur.lastIndexOf('/'));
  const me=state.ed.mEdits[m.name]||{};
  const base=me.move_dir||m.folder.base||m.folder.suggestion;
  return kind==='sprite'?'unit_sprites':base+'/textures';
}
const TEX_FILTER='Textures (*.texture)|*.texture|All files (*.*)|*.*';
const SPR_FILTER='Sprites (*.spr)|*.spr|All files (*.*)|*.*';
async function edImportInto(name,kind,set){
  const m=state.ed.d.models.find(x=>x.name===name);
  const r=await api.post('/api/browse_file',
    {title:'Select a file to import',filter:kind==='sprite'?SPR_FILTER:TEX_FILTER});
  if(!r.path)return;
  const dir=edImportDir(m,kind),rel=dir+'/'+r.path.split(/[\\\/]/).pop();
  const me=edTouch(name);
  me.imports=(me.imports||[]).filter(x=>x.rel!==rel).concat([{src:r.path,dest_dir:dir,rel}]);
  set(me,rel); edRenderTab(); edPreview();
}
const edImportDefault=(name,kind)=>edImportInto(name,kind,(me,rel)=>{me.defaults[kind]=rel;});
const edImportFac=(name,fac,kind)=>edImportInto(name,kind,(me,rel)=>{
  (me.faction_paths[fac]||(me.faction_paths[fac]={}))[kind]=rel;});

/* ---- EDU field access shared by every tab ----
   `e.ov` holds overrides keyed by the label block_fields() produced; `e.added`
   remembers fields this session created, so an override that happens to equal
   the (empty) starting value still gets written. */
const csv=s=>(s||'').split(',').map(x=>x.trim()).filter(Boolean);
function edFieldVal(label){const e=state.ed;
  if(label in e.ov)return e.ov[label];
  const f=e.d.fields.find(x=>x[0]===label); return f?f[1]:'';}
function edSetField(label,val){
  const e=state.ed,f=e.d.fields.find(x=>x[0]===label);
  if(!f){e.d.fields=e.d.fields.concat([[label,'']]); e.added.add(label);}
  if(val===((f||['',''])[1])&&!e.added.has(label)) delete e.ov[label]; else e.ov[label]=val;
  e.rm.delete(label); edStale();
}
// Put a field back exactly as it was — including "it wasn't there at all", which
// setting it to "" would not do (an empty EDU line is still a line).
function edRestoreField(label,val){
  const e=state.ed;
  if(val===''&&e.added.has(label)){
    e.added.delete(label); delete e.ov[label];
    e.d.fields=e.d.fields.filter(f=>f[0]!==label); edStale(); return;
  }
  edSetField(label,val);
}

/* ---- identity + localisation ---- */
// export_units.txt keeps a description on ONE line, so a real newline or tab
// typed into the box would split the record. They are written as the literal
// two-character escapes the game reads instead, the moment the box loses focus.
const escLines=s=>(s==null?'':''+s).replace(/\r\n?|\n/g,'\\n').replace(/\t/g,'\\t');
function edIsMerc(){return csv(edFieldVal('attributes')).includes('mercenary_unit');}
function edIdentity(){
  const e=state.ed,d=e.d,merc=edIsMerc();
  return `<div class="frm">
    <div class="two">
      <div><label>Unit type (EDU <code>type</code>, the internal name)
        <input id="edType" value="${esc(e.newType||d.type)}"></label>
        <div class="count" style="margin-top:4px">${docPoints(
          'Renaming it follows the unit through the whole mod.',[
          "Rewritten: <code>export_descr_buildings.txt</code>, every campaign's "
            +'<code>descr_strat.txt</code> and <code>campaign_script.txt</code>, the voice bank, '
            +"<code>descr_mercenaries.txt</code> and the mod's <code>.lua</code> scripts.",
          'Preview lists every file and how many lines in each. Undo puts them all back.',
          'Spellings that differ only in capitalisation are reported, not rewritten. Other '
            +'things share these files.'])}</div></div>
      <div><label>Dictionary (localisation + unit-card key)
        <input id="edDict" value="${esc(e.newDict||d.dictionary)}"></label>
        <div class="count" style="margin-top:4px">Renaming it moves the text entry and copies the
          unit cards to the new name (${d.icons.length} icon file${d.icons.length===1?'':'s'} found).
          <label class="chk" style="margin-top:4px"><input type="checkbox" id="edRmIcons"
            ${e.removeOldIcons?'checked':''}> delete the old icon files</label></div></div>
    </div>
    <label>Displayed name<input id="edName" value="${esc(e.loc.name)}"></label>
    <label>Short description (unit card tooltip)<textarea id="edShort">${esc(e.loc.descr_short)}</textarea></label>
    <label>Description (info card)<textarea id="edDescr" style="min-height:150px">${esc(e.loc.descr)}</textarea></label>
    <div class="count" style="margin-top:4px">The description is stored on a single line, so any
      new line or tab you type becomes <code>\\n</code> / <code>\\t</code> when you click away.</div>
    ${edTierBox()}
    <fieldset style="margin-top:12px"><legend>Mercenary</legend>
      <button class="${merc?'on':''}" onclick="edToggleMerc(${merc?'false':'true'})">${
        merc?'✓ Mercenary unit':'Make this a mercenary unit'}</button>
      <div class="count" style="margin-top:6px">${merc
        ?'This unit has the <code>mercenary_unit</code> attribute; the button removes it.'
        :'Adds the <code>mercenary_unit</code> attribute.'}
        To recruit it, add a pool entry in <code>descr_mercenaries.txt</code> yourself. A merc's card is
        looked up under <code>ui/units/mercs/</code> unless <code>card_pic_dir</code> says otherwise.</div>
    </fieldset>
    <fieldset style="margin-top:12px"><legend>Unit card / info card</legend>
      <div class="count">${docPoints('Import a replacement from anywhere on disk.',[
        `On save it takes the unit's dictionary name and is copied into <b>every faction that owns
         the unit</b> (plus the <code>mercs</code>/<code>merc</code> fallback), because the game
         looks it up under the <i>player's</i> faction folder.`,
        edOwnFolders().length
          ?`Right now that is <b>${edOwnFolders().length}</b> folder(s):
             <code>${edOwnFolders().map(esc).join('</code> <code>')}</code>.`
          :`<b class="w-warn">This unit has no ownership</b>, so there is no faction folder to
             copy into. Set <code>ownership</code> first.`,
        'A <code>.png</code>/<code>.jpg</code> is converted to <code>.tga</code>; the engine reads '
          +'nothing else.'])}</div>
      <div class="icoprev">
        <div class="icoslot">
          <div class="icowrap">
            <img class="card" onerror="this.style.display='none'"
              title="Replace the unit card" onclick="edPickIcon('cardSrc')"
              src="${e.cardSrc?'/preview_image?path='+enc(e.cardSrc):iconUrl(e.mod,e.unit)}">
            <button class="icoedit" title="Replace the unit card"
              onclick="edPickIcon('cardSrc')">✎</button>
          </div>
          <div class="k">Unit card</div>
          <div class="fn">${e.cardSrc?esc(e.cardSrc.split(/[\\/]/).pop()):'current'}</div>
          <div class="sprrow">
            ${edRevealBtn('card')}
            ${e.cardSrc?`<button class="danger" onclick="edClearIcon('cardSrc')">✕</button>`:''}
          </div>
        </div>
        <div class="icoslot">
          <div class="icowrap">
            <img class="info" onerror="this.style.display='none'"
              title="Replace the info card" onclick="edPickIcon('infoSrc')"
              src="${e.infoSrc?'/preview_image?path='+enc(e.infoSrc):iconUrl(e.mod,e.unit,'info')}">
            <button class="icoedit" title="Replace the info card"
              onclick="edPickIcon('infoSrc')">✎</button>
          </div>
          <div class="k">Info card</div>
          <div class="fn">${e.infoSrc?esc(e.infoSrc.split(/[\\/]/).pop()):'current'}</div>
          <div class="sprrow">
            ${edRevealBtn('info')}
            ${e.infoSrc?`<button class="danger" onclick="edClearIcon('infoSrc')">✕</button>`:''}
          </div>
        </div>
      </div>
      ${edCardVariants('card','Unit cards on disk')}
      ${edCardVariants('info','Info cards on disk')}
      ${(e.cardSrc||e.infoSrc)?`<div class="count w-good" style="margin-top:8px">
        Staged. Nothing is written until you hit Save.</div>`:''}
    </fieldset>
  </div>`;
}
/* Every DISTINCT card on disk, and which factions share it. The game looks a
   card up under the PLAYER's faction folder, so a mod may ship one picture for
   ten factions or ten different ones — and the preview above can only ever show
   whichever folder was found first. Grouped by file content on the server
   (edit.icon_variants), so ten identical copies are one row. */
function edCardVariants(kind,title){
  const e=state.ed;
  const rows=((e.d.icon_variants||{})[kind])||[];
  if(rows.length<2)return '';           // one picture for everyone: nothing to say
  return `<div class="cardvars">
    <div class="k">${esc(title)} <span class="count">${rows.length} different
      picture${rows.length===1?'':'s'} across ${rows.reduce((n,r)=>n+r.factions.length,0)}
      faction folder${rows.reduce((n,r)=>n+r.factions.length,0)===1?'':'s'}</span></div>
    <div class="cardvarlist">${rows.map(r=>`<figure>
      <img loading="lazy" onerror="iconRetry(this)"
        src="/icon?mod=${enc(e.mod)}&kind=modfile&rel=${enc(r.rel)}" alt="">
      <figcaption>
        <span class="count">${esc(r.rel)}</span>
        <span class="tags">${r.factions.map(f=>`<span class="badge">${esc(f)}</span>`).join('')}</span>
      </figcaption></figure>`).join('')}</div></div>`;
}

// The faction folders an imported card would land in: this save's ownership if it
// is being changed, otherwise the unit's current one. Mirrors _plan_icon_import.
function edOwnFolders(){
  const own=(edFieldVal('ownership')||'')
    .split(/[,\s]+/).map(s=>s.trim().toLowerCase()).filter(Boolean);
  const real=own.filter(f=>f!=='slave');   // slave alone still needs a folder
  return real.length?real:own;
}
/* ---- where the picture actually lives ----
   The preview comes through /icon, which resolves the faction folders for us,
   so the page never knew the path it was showing. `d.icons` lists them in the
   order that resolution walks, so its first entry of a kind IS the picture
   above the button. The path goes back to the server as `rel` and is resolved
   under the mod's own data folder there. */
const edIconRel=kind=>{
  const f=(state.ed.d.icons||[]).find(x=>x.kind===kind);
  return f?f.rel:'';
};
function edRevealBtn(kind){
  const rel=edIconRel(kind),what=kind==='card'?'unit':'info';
  if(!rel)return `<button disabled title="This unit has no ${what} card on disk yet.
Import one and save, and this opens the folder it lands in.">Open file location</button>`;
  const many=((state.ed.d.icon_variants||{})[kind]||[]).length>1;
  return `<button title="Show ${esc(rel)} in the file manager.
${many?'This unit has more than one distinct picture. The list below has the rest.'
      :'Every faction folder that has one shares this picture.'}"
    onclick="edReveal('${q1(esc(rel))}')">Open file location</button>`;
}
async function edReveal(rel){
  const r=await api.post('/api/reveal',{mod:state.ed.mod,rel});
  if(!r||!r.ok)toast((r&&r.error)||'that folder could not be opened');
}
async function edPickIcon(key){
  const r=await api.post('/api/browse_file',
    {title:'Select the image to use as the unit card',
     filter:'Images (*.tga;*.dds;*.png;*.jpg;*.jpeg;*.bmp)|*.tga;*.dds;*.png;*.jpg;*.jpeg;*.bmp|All files (*.*)|*.*'});
  if(r.path){state.ed[key]=r.path; edRenderTab();}
}
/* ---- the tier: the toolkit's own note about a unit, not a game field ----
   Every other box on this screen writes a line the engine reads. This one does
   not, and the badge says so where it cannot be missed: a tier lives in a
   comment above the unit's `type` line, and it exists so the EDU cleanup has
   something to group by. `edTierVal` reads the pending edit before the saved
   value, the same way `edFieldVal` does for a real field. */
const edTierVal=k=>{const e=state.ed;
  return (e.tierEdit&&k in e.tierEdit)?e.tierEdit[k]:(e.d[k]||'');};
function edSetTier(k,v){const e=state.ed;
  e.tierEdit=e.tierEdit||{};
  if(v===(e.d[k]||''))delete e.tierEdit[k]; else e.tierEdit[k]=v;
  edStale(); edRenderTab();
}
function edTierBox(){
  const e=state.ed;
  const tier=edTierVal('tier'),variant=edTierVal('tier_variant');
  // A value typed through ＋ is not in the mod's list until the mod is read
  // again, so it is added to the list here. Without this the drop-down came back
  // with nothing selected and the new variant looked like it had been thrown
  // away — it was still staged, which is worse than losing it outright.
  const opts=(list,cur)=>{
    const all=(list||[]).slice();
    if(cur&&all.indexOf(cur)<0)all.push(cur);
    return ['<option value=""></option>'].concat(
      all.map(v=>`<option value="${esc(v)}"${v===cur?' selected':''}>${esc(v)}${
        (list||[]).indexOf(v)<0?' (new)':''}</option>`)).join('');
  };
  const v=gfVocabFor(e.mod)||{};
  /* The variant list is the mod's OWN vocabulary — every value any of its units
     already uses, read back out of the markers the tool wrote (vocab.py's
     `_marker_values`). So a mod that has never had a variant offers an empty
     drop-down, and the note underneath used to answer that with "type one in the
     unit file", which means leaving the toolkit to hand-edit the file it exists
     to replace. ＋ is that first value, typed here: it goes onto this unit, and
     from the next read of the mod it is in the list for every other one. */
  const adding=!!e.tierNewVar;
  return `<fieldset style="margin-top:12px"><legend>Tier <span class="pill">toolkit only</span></legend>
    <div class="two">
      <div><label>Tier<select id="edTier">${opts(v.tier,tier)}</select></label></div>
      <div><label>Variant<span class="tiervar">${adding
        ? `<input id="edTierVarNew" placeholder="A name for the new variant"
             value="${esc(variant)}" autofocus>
           <button title="Keep this variant" onclick="edTierVarAdd(false)">✓</button>`
        : `<select id="edTierVar">${opts(v.tier_variant,variant)}</select>
           <button title="Add a variant this mod has never used before.
It goes onto this unit, and joins the list for every other one."
             onclick="edTierVarAdd(true)">＋</button>`}</span></label></div>
    </div>
    <div class="count" style="margin-top:6px">${docPoints(
      'The game never reads this. It is the toolkit’s own note about the unit.',[
      'It is stored as a comment above the unit’s <code>type</code> line '+
        '(<code>;@m2gt tier=3 variant=aor</code>), so the engine skips it and no mod file changes shape.',
      'It exists so <b>Clean up the unit file</b> can group the roster by tier the way a '+
        'hand-organised <code>export_descr_unit.txt</code> is.',
      'The list holds every variant this mod already uses. <b>＋</b> adds one it does not.'])}</div>
  </fieldset>`;
}
// ＋ opens the box; ✓ closes it again. The value is written on every keystroke,
// so a variant typed and never confirmed is still the unit's.
function edTierVarAdd(on){
  state.ed.tierNewVar=!!on;
  edRenderTab();
  const el=document.getElementById('edTierVarNew');
  if(el){el.focus(); el.select();}
}
function edClearIcon(key){state.ed[key]=''; edRenderTab();}
function edToggleMerc(on){
  const attrs=csv(edFieldVal('attributes'));
  const i=attrs.indexOf('mercenary_unit');
  if(on&&i<0)attrs.push('mercenary_unit');
  if(!on&&i>=0)attrs.splice(i,1);
  edSetField('attributes',attrs.join(', ')); edRenderTab();
}
function edWireIdentity(){
  const e=state.ed,d=e.d;
  const bind=(id,fn)=>{const el=document.getElementById(id);
    if(el)el.oninput=()=>{fn(el.value);edStale();};};
  bind('edType',v=>{e.newType=(v.trim()===d.type)?'':v.trim();});
  bind('edDict',v=>{e.newDict=(v.trim()===d.dictionary)?'':v.trim();});
  bind('edName',v=>{e.loc.name=v;});
  bind('edShort',v=>{e.loc.descr_short=v;});
  bind('edDescr',v=>{e.loc.descr=v;});
  ['edShort','edDescr'].forEach(id=>{const el=document.getElementById(id); if(!el)return;
    el.onblur=()=>{const v=escLines(el.value);
      if(v!==el.value){el.value=v; if(id==='edShort')e.loc.descr_short=v; else e.loc.descr=v; edStale();}};});
  const rm=document.getElementById('edRmIcons'); if(rm)rm.onchange=()=>e.removeOldIcons=rm.checked;
  const t=document.getElementById('edTier');
  if(t)t.onchange=()=>edSetTier('tier',t.value);
  const tv=document.getElementById('edTierVar');
  if(tv)tv.onchange=()=>edSetTier('tier_variant',tv.value);
  // the typed-in variant writes as it is typed, and must not redraw the box it
  // is being typed into — so it sets the value directly rather than via edSetTier
  const tn=document.getElementById('edTierVarNew');
  if(tn)tn.oninput=()=>{
    const w=state.ed; w.tierEdit=w.tierEdit||{};
    const v=tn.value.trim().replace(/\s+/g,'_');
    if(v===(w.d.tier_variant||''))delete w.tierEdit.tier_variant;
    else w.tierEdit.tier_variant=v;
    edStale();
  };
}

/* ---- every EDU field, editable, with a real delete ----
   Four of them are comma-separated lists whose ORDER is meaningful, so they get
   drag-to-reorder chips instead of a text box: `ownership` / `era 0..2` (the
   factions that may field the unit) and `armour_ug_models` (position N = armour
   upgrade level N). */
const LIST_FIELDS=new Set(['ownership','era 0','era 1','era 2']);
function edFields(){
  const cv=state.ed.cv;
  return `<fieldset><legend>EDU fields, edited in place</legend>
    <div class="fieldbar">
      <input id="fieldFilter" placeholder="Filter fields…" oninput="filterFields()">
      ${gfToggleHtml()}${edCvToggleHtml()}
      <span class="count" id="fieldChanged"></span>
    </div>
    <div class="cvsplit${cv?'':' off'}${(cv&&gfMode()==='raw')?' rawpair':''}">
      <div class="cvgui" id="edFieldsCol">${edFieldsCol()}</div>
      ${cv?`<div id="edCodeCol">${cvHtml(cv)}</div>`:''}
    </div></fieldset>`;
}
// Just the boxes — redrawn on its own when the text pane re-reads the block,
// because redrawing the whole tab would take the caret out of the text.
function edFieldsCol(){
  return gfMode()==='guided'
    ? `<div class="allfields guided" id="allFields">${gfRender(gfHostEditor())}</div>`
    : edRawFields();
}
function edFieldsRefresh(){
  const col=document.getElementById('edFieldsCol'); if(!col){edRenderTab(); return;}
  const box=document.getElementById('allFields'),was=box?box.scrollTop:0;
  const g=document.getElementById('gfBody'),wasG=g?g.scrollTop:0;
  col.innerHTML=edFieldsCol();
  if(gfMode()==='guided')gfWire(gfHostEditor()); else edWireRawRows();
  const now=document.getElementById('allFields'); if(now&&was)now.scrollTop=was;
  const nowG=document.getElementById('gfBody'); if(nowG&&wasG)nowG.scrollTop=wasG;
  edCount(); cvBindHover(state.ed.cv); edRawAlign(); paintDirty();
}

/* ---- Code View on this tab ----
   Off by default and remembered per user: most edits never need the file, and
   the pane costs half the dialog's width. */
function edCvToggleHtml(){
  const on=!!state.ed.cv;
  return `<button class="${on?'on':''}" title="Show this unit's block exactly as
export_descr_unit.txt stores it, beside the boxes. Hover a box to light up its
line; edit either side and the other follows."
    onclick="edCvToggle()">&lt;/&gt; Code view</button>`;
}
async function edCvToggle(){
  const e=state.ed;
  if(e.cv){e.cv=null; api.post('/api/settings',{code_view:false});
    state.settings.code_view=false; edRenderTab(); return;}
  state.settings.code_view=true; api.post('/api/settings',{code_view:true});
  e.cv=cvCreate(edCvHost());
  edRenderTab();                       // shows "Loading the text…" beside the boxes
  await cvLoad(e.cv);
  if(state.ed===e&&e.cv)edRenderTab();
}
function edCvHost(){
  const e=state.ed;
  return {kind:'edu', mod:e.mod, id:e.unit,
    where:e.d.eop?e.d.eop_file:'data/export_descr_unit.txt',
    edits:()=>({overrides:state.ed.ov, removals:[...state.ed.rm]}),
    // the text pane re-read the block: it is the new starting point, so the
    // box-level overrides that produced it are folded in and cleared
    adopt:cv=>{const s=state.ed;
      s.d.fields=(cv.fields||[]).map(f=>[f[0],f[1]]);
      s.ov={}; s.rm=new Set(); s.added=new Set(); edStale();},
    refreshGui:()=>edFieldsRefresh(),
    // the block's line count changed, so the raw rows have to be re-placed
    relayout:()=>edRawAlign()};
}
function edRawFields(){
  const e=state.ed,d=e.d;
  const present=new Set(d.fields.map(([l])=>l.replace(/#\d+$/,'')));
  const missing=(d.known_fields||[]).filter(k=>!present.has(k));
  // type/dictionary/soldier define the block — the engine refuses to drop them
  const PROTECTED=new Set(['type','dictionary','soldier']);
  const rmBtn=(label,gone)=>PROTECTED.has(label.replace(/#\d+$/,''))
    ? '<span class="rm" title="This field defines the unit and can\'t be removed"> </span>'
    : `<button class="rm" data-rm="${esc(label)}" title="${
        gone?'Keep this field':'Remove this line from the unit'}">${gone?'↺':'✕'}</button>`;
  const rows=d.fields.map(([label,val])=>{
    const cur=(label in e.ov)?e.ov[label]:val;
    const gone=e.rm.has(label);
    const key=label.replace(/#\d+$/,'');
    // what this line is, moved onto the ? beside its name
    const why=GF_FIELDS[key]&&GF_FIELDS[key].t
      ? GF_FIELDS[key].t+'. '+gfPlainDoc(key) : '';
    const head=`<div class="afrow wide${gone?' gone':''}" data-label="${esc(label)}">
      <label>${qm(why,label)}${esc(label)}</label>`;
    if(LIST_FIELDS.has(label)&&!gone)
      return head+edFactionField(label,cur)+rmBtn(label,gone)+'</div>';
    if(label==='armour_ug_models'&&!gone)
      return head+edArmourField(label,cur)+rmBtn(label,gone)+'</div>';
    return `<div class="afrow${gone?' gone':''}" data-label="${esc(label)}">
      <label>${qm(why,label)}${esc(label)}</label>
      <input data-k="${esc(label)}" value="${esc(cur)}" ${gone?'disabled':''}
        class="${(label in e.ov)&&e.ov[label]!==val?'changed':''}">
      ${rmBtn(label,gone)}</div>`;
  }).join('');
  return `<div class="allfields" id="allFields">${rows}</div>
    <div class="count" style="margin-top:6px">✕ removes the whole line. Clearing a value
      leaves an empty field, which the game still reads.</div>
    <div class="prow" style="margin-top:8px;grid-template-columns:var(--plw) 1fr auto">
      <span class="pl">${qm('Fields the EDU understands that this unit has no line for. Adding one writes a fresh line with an empty value.','Add a missing field')}Add a missing field</span>
      <select id="edAddKey">${missing.map(k=>`<option>${esc(k)}</option>`).join('')||'<option value="">Nothing missing</option>'}</select>
      <button onclick="edAddField()">Add</button>
    </div>`;
}
function edWireFields(){
  if(gfMode()==='guided')gfWire(gfHostEditor()); else edWireRawRows();
  edCount();
  if(state.ed.cv){cvWire(state.ed.cv); cvBindHover(state.ed.cv);}
  edRawAlign();
}
/* ---- raw lines, line for line ----
   With Code View open, the raw view is one box per EDU line beside the file's
   own lines, and it is only worth having if row n really is line n. Counting
   will not give that: the block also has its `type` line, whatever comment
   lines the pane is hiding, and a repeated field is two rows for one key. The
   server already says where every field's line is — that is what the hover
   highlight runs on — so the rows are PLACED from those spans and the two sides
   agree whatever the block looks like. A row the spans do not cover (a field
   just added, which is not in the file yet) is stacked below the block. */
function edRawAlign(){
  const cv=state.ed&&state.ed.cv;
  const box=document.getElementById('allFields');
  if(!box)return;
  const on=!!(cv&&cv.loaded&&!cv.err&&gfMode()==='raw');
  const rows=[...box.querySelectorAll('.afrow')];
  box.classList.toggle('aligned',on);
  if(!on){rows.forEach(r=>{r.style.top='';}); box.style.height='';
    if(cv)cvExpand(cv,false); return;}
  const lh=cvLh(cv);
  cvExpand(cv,true);                   // grow the pane before measuring against it
  const top0=cvTextOrigin(cv,box);     // where the pane's line 1 is, from here
  let last=cvLines(cv.text).length;
  rows.forEach(r=>{
    const sp=(cv.spans[r.dataset.label]||[])[0];
    const line=sp?sp[0]:(last+=1);
    r.classList.toggle('unplaced',!sp);
    r.style.top=Math.round((line-1)*lh+top0)+'px';
  });
  box.style.height=Math.round(last*lh+top0+lh)+'px';
}
function edWireRawRows(){
  const e=state.ed;
  document.querySelectorAll('#allFields input[data-k]').forEach(inp=>{
    inp.oninput=()=>{const k=inp.dataset.k,orig=(e.d.fields.find(f=>f[0]===k)||['',''])[1];
      if(inp.value!==orig)e.ov[k]=inp.value; else delete e.ov[k];
      inp.classList.toggle('changed',inp.value!==orig); edCount(); edStale();};
  });
  document.querySelectorAll('#allFields .rm').forEach(b=>{
    b.onclick=()=>{const k=b.dataset.rm;
      if(e.rm.has(k)){e.rm.delete(k);} else {e.rm.add(k); delete e.ov[k];}
      edRenderTab();};
  });
}
function edCount(){
  const e=state.ed,el=document.getElementById('fieldChanged'); if(!el)return;
  const n=Object.keys(e.ov).length,r=e.rm.size;
  el.textContent=[n?`${n} changed`:'',r?`${r} removed`:''].filter(Boolean).join(' · ');
}
function edAddField(){
  const e=state.ed,sel=document.getElementById('edAddKey'); const k=sel&&sel.value; if(!k)return;
  e.d.fields=e.d.fields.concat([[k,'']]);      // shows up as a new (empty) row
  e.added.add(k); e.ov[k]=''; edRenderTab();
  const inp=document.querySelector(`#allFields input[data-k="${cssq(k)}"]`);
  if(inp){inp.focus();}
}

/* =========================================================================
   COMPARE — the same unit table twice, side by side

   "Is my new spearman better than the one it replaces, and by how much" is a
   question the EDU answers only if you hold two blocks of eleven-value lines in
   your head at once. So the second unit is loaded beside the first and the lines
   are split into their named slots — attack against attack, morale against
   morale — with the better side green and the worse red.

   Which side is "better" is only claimed where it is genuinely a merit: attack
   and armour go up, cost and heat fatigue go down, and everything else (a hit
   sound, a formation width, the skeleton factor) is simply marked as different.
   Guessing a winner for a setting that has none would be worse than saying
   nothing, because it reads as advice.

   Both columns are live boxes and both are written by Save — the whole point is
   to close a gap you can see, in whichever of the two units is wrong. */

/* One slot's verdict. `absent` names a side that has no such LINE at all, which
   makes its zeroes meaningless — a unit with no `stat_armour_ex` does not have
   0 armour, it has the ordinary line instead — so nothing wins those. */
/* The whole table as data, from two field lookups. Pure — it never touches the
   page — so the same call builds the view and answers "how many differences are
   there" for the header, and the test suite can drive it under node. */
/* ---- the two sides ----
   'a' is the unit the editor opened on and writes through the ordinary edit
   path; 'b' is the compared unit, which carries its own override map and is
   saved by a second request. Neither knows about the other. */
/* ---- the tab ---- */
function edCompare(){
  const e=state.ed;
  if(!e.cmp)return edCmpPicker();
  if(e.cmp.loading)return `<div class="frm"><div class="count">Loading
    ${esc(e.cmp.unit)}…</div></div>`;
  if(e.cmp.error)return `<div class="frm"><div class="w-bad">Couldn’t open
    ${esc(e.cmp.unit)}: ${esc(e.cmp.error)}</div>
    <button style="margin-top:8px" onclick="state.ed.cmp=null;edRenderTab()">Pick another unit</button></div>`;
  const m=edCmpModel();
  const q=(e.cmpQ||'').trim().toLowerCase();
  const fields=[];
  m.sections.forEach(sec=>{
    const keep=sec.fields.map(f=>{
      const hit=!q||f.key.toLowerCase().includes(q)||f.title.toLowerCase().includes(q)
        ||f.rows.some(r=>(r.name||'').toLowerCase().includes(q));
      if(!hit)return null;
      const rows=e.cmpSame?f.rows:f.rows.filter(r=>!r.v.same);
      return rows.length?Object.assign({},f,{rows}):null;
    }).filter(Boolean);
    if(keep.length)fields.push(Object.assign({},sec,{fields:keep}));
  });
  return `<div class="frm">
    ${edCmpHead(m)}
    <div class="cmpbar">
      <input class="q" id="cmpQ" placeholder="Filter by stat: attack, morale, cost…"
        value="${esc(e.cmpQ||'')}">
      <label class="chk"><input type="checkbox" id="cmpSame" ${e.cmpSame?'checked':''}>
        show the stats they share</label>
      <span class="count">Both columns are editable. <b>Save changes</b> writes both units.</span>
    </div>
    ${fields.length?fields.map(edCmpSection).join('')
      :`<div class="count">${q?'Nothing matches that filter.'
        :'These two units are identical on every line. Tick “show the stats they share” to see them.'}</div>`}
    ${cmpDatalists()}</div>`;
}
/* Which vocabularies the table needs a datalist for, emitted once at the bottom
   rather than once per box — a `soldier` model list is two thousand entries and
   the table has forty of them. */
function edWireCompare(){
  const e=state.ed;
  const q=document.getElementById('cmpQ');
  if(q)q.oninput=()=>{ e.cmpQ=q.value;
    // in the picker the list itself is the thing being filtered; in the table
    // only the rows are, and both want the caret left where it is
    edRenderTab();
    const n=document.getElementById('cmpQ');
    if(n){n.focus();n.setSelectionRange(n.value.length,n.value.length);}
  };
  const same=document.getElementById('cmpSame');
  if(same)same.onchange=()=>edCmpToggleSame(same.checked);
  document.querySelectorAll('#edBody [data-cmp]').forEach(el=>{
    const w=el.dataset.cmp,label=el.dataset.cl,pi=+el.dataset.ci;
    const write=()=>{ cmpWrite(w,label,pi,el.value); cmpRepaint(el); };
    el.oninput=write; el.onchange=write;
  });
}
/* Recolour one row in place. A full re-render on every keystroke would throw the
   caret out of the box being typed into, which is exactly the box whose colour
   has to keep up. */
/* ---- drag-to-reorder chip lists ---------------------------------------
   The order of these lists is data, not decoration: armour_ug_models[N] is the
   model shown at armour upgrade level N, and era lines are conventionally led by
   the faction the unit belongs to. Dropping a chip rewrites the whole line. */
let edDrag=null;
function edDragStart(ev,label,i){
  edDrag={label,i}; ev.dataTransfer.effectAllowed='move';
  try{ev.dataTransfer.setData('text/plain',String(i));}catch(_){}
  ev.currentTarget.classList.add('drag');
}
function edDragOver(ev,label){
  if(!edDrag||edDrag.label!==label)return;
  ev.preventDefault(); ev.currentTarget.classList.add('over');
}
function edDragLeave(ev){ev.currentTarget.classList.remove('over');}
function edDragEnd(ev){ev.currentTarget.classList.remove('drag'); edDrag=null;}
function edDrop(ev,label,i){
  if(!edDrag||edDrag.label!==label)return;
  ev.preventDefault();
  const list=csv(edFieldVal(label)),from=edDrag.i;
  if(from===i){edDrag=null; edRenderTab(); return;}
  const [moved]=list.splice(from,1); list.splice(i,0,moved);
  edDrag=null; edSetField(label,list.join(', ')); edRenderTab();
}
// `opt.cls` styles the list (armour tiers use it to lift their ✕ above the chip)
// and `opt.rm` swaps in a different remove call — an armour tier has to drop its
// armour_ug_levels entry with it, which the plain list remove knows nothing about.
function edChips(label,items,extra,opt){
  const o=opt||{},cls=o.cls?' '+o.cls:'';
  // entries you added stand out from the ones the file already had, and the
  // ones you took out stay as ghosts you can click to put back
  // …except for armour tiers, where a slot is positional: putting one back is
  // not just re-adding a name, so no ghost is offered there
  const was=new Set(csv((state.ed.d.fields.find(x=>x[0]===label)||['',''])[1]));
  const gone=o.cls==='ug'?[]:[...was].filter(v=>items.indexOf(v)<0);
  return `<div class="chips${cls}">${items.map((v,i)=>`<span class="chipd${cls}${
      was.has(v)?'':' added'}" draggable="true"
      ondragstart="edDragStart(event,'${q1(esc(label))}',${i})"
      ondragover="edDragOver(event,'${q1(esc(label))}')" ondragleave="edDragLeave(event)"
      ondragend="edDragEnd(event)" ondrop="edDrop(event,'${q1(esc(label))}',${i})"
      title="${was.has(v)?'drag to reorder':'Added by you · drag to reorder'}">
      <span class="g">⠿</span><span class="${i===0?'first':''}">${esc(v)}</span>
      ${(extra||(()=>''))(v,i)}
      <button class="${o.cls==='ug'?'xup':'x'}" title="Remove ${esc(v)}"
        onclick="${o.rm?o.rm(i,v):`edListRemove('${q1(esc(label))}',${i})`}">✕</button>
    </span>`).join('')||'<span class="count">Empty</span>'}
    ${gone.map(v=>`<span class="chipd gone" title="Removed by you. Click to put it back."
      onclick="edListRestore('${q1(esc(label))}','${q1(esc(v))}')">${esc(v)}</span>`).join('')}</div>`;
}
function edListRestore(label,v){
  const list=csv(edFieldVal(label));
  if(list.indexOf(v)<0)list.push(v);
  edSetField(label,list.join(', ')); edRenderTab();
}
function edListRemove(label,i){
  const list=csv(edFieldVal(label)); list.splice(i,1);
  edSetField(label,list.join(', ')); edRenderTab();
}
function edListSet(label,items){edSetField(label,items.join(', ')); edRenderTab();}
function edListToggle(label,fac,on){
  const list=csv(edFieldVal(label)),i=list.indexOf(fac);
  if(on&&i<0)list.push(fac); else if(!on&&i>=0)list.splice(i,1);
  edListSet(label,list);
}

/* ---- ownership / era 0..2: a faction checklist over a chip list ---- */
function edFactionList(){
  const d=state.ed.d,seen=new Set();
  const all=(d.all_factions||[]).slice();
  ['ownership','era 0','era 1','era 2'].forEach(l=>csv(edFieldVal(l)).forEach(f=>all.push(f)));
  return all.filter(f=>!seen.has(f)&&seen.add(f))
            .sort((a,b)=>edFacLabel(a).localeCompare(edFacLabel(b)));
}
const edFacLabel=f=>facTwoNames(f,(state.ed.d.faction_names||{})[f]);
function edFactionField(label,cur){
  const list=csv(cur),chosen=new Set(list);
  const isEra=label!=='ownership';
  const own=csv(edFieldVal('ownership'));
  // which factions this line named before you touched it, so the ones you
  // added or removed stand out from the ones that were already there
  const was=new Set(csv((state.ed.d.fields.find(x=>x[0]===label)||['',''])[1]));
  const boxes=edFactionList().map(f=>facCheckRow(
      f,(state.ed.d.faction_names||{})[f],
      `edListToggle('${q1(esc(label))}','${q1(esc(f))}',this.checked)`,
      chosen.has(f),'',chosen.has(f)!==was.has(f))).join('');
  return `<div style="flex:1;min-width:0">
    ${edChips(label,list)}
    <div class="barrow">
      <details class="drop"><summary>▾ Choose factions: ${list.length} selected</summary>
        <div class="dropbody"><div class="barrow" style="margin:0 0 6px">
          <button onclick="edListSet('${q1(esc(label))}',${JSON.stringify(edFactionList()).replace(/"/g,'&quot;')})">All</button>
          <button onclick="edListSet('${q1(esc(label))}',[])">None</button>
        </div><div class="faclist" style="border:none;padding:0;max-height:none">${boxes}</div></div>
      </details>
      ${isEra?`<button ${own.length?'':'disabled'}
          onclick="edListSet('${q1(esc(label))}',${JSON.stringify(own).replace(/"/g,'&quot;')})"
          title="Replace this era with the ownership line">Copy ownership (${own.length})</button>
        <button ${own.length?'':'disabled'}
          onclick="edListSet('${q1(esc(label))}',['${q1(esc(own[0]||''))}'])"
          title="Replace this era with just the first faction of ownership">Copy 1st ownership${
            own.length?` (${esc(own[0])})`:''}</button>`:''}
    </div></div>`;
}

/* ---- armour_ug_models: reorder tiers, jump to an entry, add the next one ----
   Each tier carries a ✕ above its chip, because dropping one is not just a list
   remove: armour_ug_levels is positional too and has to lose the same slot.
   The ＋ opens a four-mode panel — see edUgPanel. */
function edArmourField(label,cur){
  const models=csv(cur),levels=csv(edFieldVal('armour_ug_levels'));
  const jump=(v)=>`<button title="Edit ${esc(v)} in the Battle models tab"
      onclick="edJumpModel('${q1(esc(v))}')">✎</button>`;
  const open=!!state.ed.ug;
  return `<div style="flex:1;min-width:0">
    ${edChips(label,models,jump,{cls:'ug',rm:i=>`edUgRemove(${i})`})}
    <div class="barrow">
      <button class="ugadd${open?' on':''}" onclick="edUgOpen()"
        title="Add an armour upgrade tier">${open?'−':'＋'}</button>
      <span class="count">Position = upgrade level${levels.length?` · armour_ug_levels: ${esc(levels.join(', '))}`:''}${
        levels.length&&levels.length!==models.length
          ? ` <span class="w-warn">${levels.length} level(s) for ${models.length} model(s)</span>`:''}</span>
    </div>
    ${edUgPanel()}</div>`;
}

/* ---- the ＋ menu: four ways to add an armour tier -------------------------
   1 repeat the last tier — the SAME entry again, so the armour upgrade is a
                            stat change with no model change
   2 take a unit's ugs    — read another unit's armour_ug_models, tick what to import
   3 pick an existing entry — search the whole modeldb and point a tier at one
   4 new entry from a tier — clone a chosen entry and give it its own mesh/texture
   Only mode 4 creates a modeldb entry. 1-3 just name entries that already exist:
   armour_ug_models is a list of bmdb entry names, and a new entry is only worth
   making when the tier is actually going to look different. */
function edUgOpen(){const e=state.ed; e.ug=e.ug?null:{mode:''}; edRenderTab();}
function edUgMode(m){
  const e=state.ed,u=e.ug||(e.ug={});
  if(m==='clone'){edUgCloneLast(); return;}          // nothing to configure
  u.mode=m; u.filter='';
  if(m==='unit'){u.unit='';u.donor=null;u.pick={};u.error='';u.loading=false;}
  if(m==='new'){
    const tiers=csv(edFieldVal('armour_ug_models'));
    const own=(e.d.models||[]).filter(x=>!x.missing).map(x=>x.name);
    u.from=own.slice().reverse().find(n=>tiers.includes(n))||own[own.length-1]||'';
  }
  edRenderTab();
}
function edUgPanel(){
  const u=state.ed.ug; if(!u)return '';
  const btn=(k,label,tip)=>`<button class="${u.mode===k?'on':''}" title="${esc(tip)}"
    onclick="edUgMode('${k}')">${label}</button>`;
  return `<div class="ugpanel">
    <div class="ugmodes">
      ${btn('clone','1 · Repeat the last tier',
        'Name the last entry again as the next tier. The unit gains the armour upgrade in its stats while its model stays exactly as it was. No new modeldb entry is made.')}
      ${btn('unit','2 · Take a unit’s upgrades',
        'Read another unit’s armour_ug_models and import the tiers you tick.')}
      ${btn('browse','3 · Pick an existing entry',
        'Search every entry in this mod’s battle_models.modeldb and add one as a tier.')}
      ${btn('new','4 · New entry from a tier',
        'Create a new modeldb entry based on one this unit already uses, with its own mesh and texture.')}
    </div>
    ${u.mode?`<div class="ugbody">${u.mode==='unit'?edUgUnitBody()
        :u.mode==='browse'?edUgBrowseBody():edUgNewBody()}</div>`
      :'<div class="count" style="margin-top:9px">Choose how the new tier should be made.</div>'}
  </div>`;
}

/* -- shared: append tiers, keeping armour_ug_levels in step -- */
const edUgSnapshot=()=>({models:edFieldVal('armour_ug_models'),
                         levels:edFieldVal('armour_ug_levels')});
// `opt.repeat` allows a name the list already has. Naming the same entry twice is
// a real M2TW pattern, not a mistake — it is how a unit gets the armour upgrade
// without a different model — so only the accidental case is guarded against.
function edUgAppend(names,donorLevels,opt){
  const models=csv(edFieldVal('armour_ug_models')),levels=csv(edFieldVal('armour_ug_levels'));
  const added=[];
  (names||[]).forEach((raw,i)=>{
    const name=(raw||'').trim().toLowerCase();
    if(!name||(models.includes(name)&&!(opt||{}).repeat))return;
    models.push(name); added.push(name);
    // armour_ug_levels has to stay ascending — the game reads it as "this model
    // from this armour level up". So a donor's own level is kept only when it is
    // still above everything here; otherwise the tier goes one past the highest.
    const nums=levels.map(x=>parseInt(x,10)).filter(x=>!isNaN(x));
    const max=nums.length?Math.max(...nums):0;
    const want=parseInt(((donorLevels||[])[i]||'').trim(),10);
    levels.push(String(!isNaN(want)&&want>max ? want
                       : nums.length?max+1:models.length));
  });
  if(!added.length)return added;
  edSetField('armour_ug_models',models.join(', '));
  edSetField('armour_ug_levels',levels.join(', '));
  return added;
}
// ✕ above a tier: drop the model AND its level, or every level above it slides
// down onto the wrong model.
function edUgRemove(i){
  const e=state.ed;
  const models=csv(edFieldVal('armour_ug_models')),levels=csv(edFieldVal('armour_ug_levels'));
  const hadLevels=!!edFieldVal('armour_ug_levels');
  const gone=models[i]; if(gone===undefined)return;
  models.splice(i,1);
  if(i<levels.length)levels.splice(i,1);
  edSetField('armour_ug_models',models.join(', '));
  if(hadLevels)edSetField('armour_ug_levels',levels.join(', '));
  // a pending entry that exists only to be this tier has nothing left to be —
  // unless the tier was repeated and another slot still names it
  const at=e.newModels.findIndex(n=>n._tier&&n.name===gone);
  if(at>=0&&!models.includes(gone))e.newModels.splice(at,1);
  edRenderTab(); edPreview();
}

/* -- mode 1: repeat the last tier -- */
// The SAME entry name again, not a copy of it. armour_ug_models is a list of
// bmdb entry names, so repeating one gives the unit the armour upgrade in its
// stats while the model on the field stays exactly as it was — vanilla and DaC
// both do it (isengard_bodyguard twice, at levels 3 and 6). Cloning the entry
// instead would put a second copy of the same meshes and textures in the modeldb
// for no visible difference.
function edUgCloneLast(){
  const e=state.ed,models=csv(edFieldVal('armour_ug_models'));
  // with no tiers yet, the first one repeats the body model
  const last=(models[models.length-1]||edFieldVal('soldier').split(',')[0]||'').trim().toLowerCase();
  if(!last){toast('This unit has no model entry to repeat');return;}
  if(!edUgAppend([last],null,{repeat:true}).length)return;
  e.ug=null; edRenderTab(); edPreview();
  const lv=csv(edFieldVal('armour_ug_levels')).slice(-1)[0];
  toast(`“${last}” repeated as the next tier${lv?` (armour level ${lv})`:''} `
       +`It upgrades the stats and keeps the same model.`,4200);
}
// Where a cloned tier comes from and what it gets called: `<stem>_ug<n>`, with n
// walked up until nothing in the mod (or pending) has that name.
function edUgNewSpec(srcName){
  const e=state.ed,d=e.d,models=csv(edFieldVal('armour_ug_models'));
  const src=(srcName||models[models.length-1]||edFieldVal('soldier').split(',')[0]||'')
            .trim().toLowerCase();
  if(!src||!d.models.some(m=>m.name===src)){
    toast('No existing model entry to clone this tier from'); return null;}
  // strip an existing tier suffix so tiers stay <stem>_ug1.._ugN rather than
  // growing one per clone — mods write both `_ug3` and `_upg3`
  const stem=src.replace(/_u(p)?g\d+$/i,'');
  let n=models.length+1,name=`${stem}_ug${n}`;
  while(d.model_names.includes(name)||e.newModels.some(x=>x.name===name)||models.includes(name))
    name=`${stem}_ug${++n}`;
  const from=d.models.find(m=>m.name===src)||{};
  return {src,name,
          dest_dir:(from.folder&&(from.folder.base||from.folder.suggestion))||'unit_models'};
}

/* -- mode 2: import another unit's armour upgrades --
   The donor is picked with the same search + faction / category / class / mercs
   filters as "＋ New unit"'s base picker, off the same state.data.units the
   browser is showing, so finding a unit works the way it does everywhere else.
   The filters live in `u.f` rather than in the DOM, because every edit
   re-renders the whole tab and would otherwise reset them. */
function edUgUnitBody(){
  const e=state.ed,u=e.ug,d=e.d,dd=state.data||{};
  const f=u.f||(u.f={q:'',fac:'',cat:'',cls:'',merc:false});
  const have=new Set(csv(edFieldVal('armour_ug_models')));
  const donor=u.loading?'<div class="count" style="margin-top:9px">Reading the unit…</div>'
    :u.error?`<div class="count w-bad" style="margin-top:9px">${esc(u.error)}</div>`
    :!u.donor?''
    :!u.donor.models.length
      ?`<div class="count w-warn" style="margin-top:9px"><b>${esc(u.unit)}</b> has no
        <code>armour_ug_models</code>${u.donor.soldier?`. Its body model is
        <code>${esc(u.donor.soldier)}</code>, which mode 3 can add`:''}.</div>`
    :`<div class="count" style="margin-top:9px">Tiers of <b>${esc(u.unit)}</b> to import:</div>
      <div class="uglist">${u.donor.models.map((m,i)=>{
        const dup=have.has(m),known=(d.model_names||[]).includes(m);
        return `<label class="ugrow">
          <input type="checkbox" ${u.pick[i]?'checked':''}
            onchange="state.ed.ug.pick[${i}]=this.checked">
          <span class="nm">${esc(m)}</span>
          <span class="count">level ${esc(u.donor.levels[i]||'none')}${
            dup?' · already a tier, so it imports as a repeat'
              :known?'':' · <span class="w-warn">not in this mod’s modeldb</span>'}</span>
        </label>`;}).join('')}</div>
      <div class="barrow">
        <button class="primary" onclick="edUgTakeUnit()">Add ticked tier(s)</button>
        <span class="count">Appended after the tiers this unit already has</span>
      </div>`;
  const rows=edUgUnitRows();          // sets u._n, so the count renders first time
  return `<input id="ugSearch" style="width:100%" placeholder="Filter units…"
      value="${esc(f.q)}" oninput="edUgFilterUnits('q',this.value)">
    <div class="barrow" style="margin:6px 0 0">
      <select onchange="edUgFilterUnits('fac',this.value)">${
        opts('All factions',dd.factions||[],facLabel,f.fac)}</select>
      <select onchange="edUgFilterUnits('cat',this.value)">${
        opts('All categories',dd.categories||[],null,f.cat)}</select>
      <select onchange="edUgFilterUnits('cls',this.value)">${
        opts('All classes',dd.classes||[],null,f.cls)}</select>
      <label class="chk"><input type="checkbox" ${f.merc?'checked':''}
        onchange="edUgFilterUnits('merc',this.checked)"> mercs only</label>
      <span class="count" id="ugCount">${u._n?`${u._n[0]}/${u._n[1]}`:''}</span>
    </div>
    <div class="baselist" id="ugUnitList">${rows}</div>
    ${donor}`;
}
// Rows only — the filter handler rewrites just this, so typing never loses the
// caret and the donor's tick list below is left as it is.
function edUgUnitRows(){
  const e=state.ed,u=e.ug,f=u.f,all=(state.data&&state.data.units)||[];
  const qq=(f.q||'').trim().toLowerCase();
  const units=all.filter(x=>x.type!==e.d.type
    &&(!qq||(x.name||'').toLowerCase().includes(qq)||x.type.toLowerCase().includes(qq)
        ||(x.dictionary||'').toLowerCase().includes(qq))
    &&(!f.fac||(x.ownership||[]).includes(f.fac))&&(!f.cat||x.kind===f.cat)
    &&(!f.cls||x.class===f.cls)&&(!f.merc||x.mercenary));
  u._n=[units.length,all.length];
  return units.slice(0,400).map(x=>`
    <div class="baserow${u.unit===x.type?' sel':''}" onclick="edUgPickUnit('${q1(esc(x.type))}')">
      <img onerror="iconRetry(this)" src="${iconUrl(e.mod,x.type)}">
      <div><div class="bn">${esc(x.name||x.type)}</div>
        <div class="bs">${esc(x.type)} · ${esc(x.kind||'?')}${x.class?' / '+esc(x.class):''}${
          x.mercenary?' · merc':''}</div></div>
    </div>`).join('')||'<div class="count" style="padding:8px">No units match.</div>';
}
function edUgFilterUnits(k,v){
  const u=state.ed.ug; if(!u||!u.f)return;
  u.f[k]=v;
  const box=document.getElementById('ugUnitList');
  if(!box){edRenderTab();return;}
  box.innerHTML=edUgUnitRows();
  const c=document.getElementById('ugCount');
  if(c&&u._n)c.textContent=`${u._n[0]}/${u._n[1]}`;
}
async function edUgPickUnit(type){
  const e=state.ed,u=e.ug; if(!u)return;
  u.unit=(type||'').trim(); u.donor=null; u.pick={}; u.error='';
  if(!u.unit){edRenderTab();return;}
  u.loading=true; edRenderTab();
  let r;
  try{ r=await api.get(`/api/unit_fields?mod=${enc(e.mod)}&type=${enc(u.unit)}`); }
  catch(err){ r={error:''+err}; }
  if(state.ed!==e||e.ug!==u||u.unit!==(type||'').trim())return;   // moved on meanwhile
  u.loading=false;
  if(r.error){u.error=r.error; edRenderTab(); return;}
  const get=k=>(((r.fields||[]).find(([l])=>l===k))||['',''])[1];
  u.donor={models:csv(get('armour_ug_models')),levels:csv(get('armour_ug_levels')),
           soldier:(get('soldier').split(',')[0]||'').trim()};
  // a tier this unit already has is offered but not pre-ticked — importing it
  // would be a deliberate repeat, not something to do by default
  const have=new Set(csv(edFieldVal('armour_ug_models')));
  u.donor.models.forEach((m,i)=>{u.pick[i]=!have.has(m);});
  edRenderTab();
}
function edUgTakeUnit(){
  const e=state.ed,u=e.ug; if(!u||!u.donor)return;
  const names=[],levels=[];
  u.donor.models.forEach((m,i)=>{
    if(u.pick[i]){names.push(m); levels.push(u.donor.levels[i]||'');}});
  if(!names.length){toast('Nothing ticked to import');return;}
  const added=edUgAppend(names,levels,{repeat:true}),from=u.unit;
  e.ug=null; edRenderTab(); edPreview();
  toast(`${added.length} tier${added.length===1?'':'s'} taken from ${from} ✓`);
}

/* -- mode 3: search the whole modeldb -- */
function edUgBrowseBody(){
  const u=state.ed.ug;
  return `<div class="prow" style="grid-template-columns:var(--plw) 1fr">
      <span class="pl">Find an entry</span>
      <input id="ugFind" value="${esc(u.filter||'')}" placeholder="type part of an entry name…"
        oninput="edUgFilter(this.value)"></div>
    <div id="ugHits">${edUgBrowseHits()}</div>`;
}
const UG_HITS_MAX=200;
function edUgBrowseHits(){
  const e=state.ed,qq=(e.ug.filter||'').trim().toLowerCase();
  const have=new Set(csv(edFieldVal('armour_ug_models')));
  const all=(e.d.model_names||[]).concat(e.newModels.map(n=>n.name));
  const hits=all.filter(n=>!qq||n.includes(qq)),shown=hits.slice(0,UG_HITS_MAX);
  // an entry already on the unit is still offered: naming it again is how a tier
  // upgrades the stats without changing the model
  return `<div class="uglist">${shown.map(n=>{
      const dup=have.has(n);
      return `<div class="ugrow" onclick="edUgAddOne('${q1(esc(n))}')">
        <span class="nm">${esc(n)}</span>
        <span class="count">${dup?'Already a tier. Click to repeat it.'
                                 :'click to add as the next tier'}</span>
      </div>`;}).join('')
      ||'<div class="ugrow have"><span class="count">No entry matches</span></div>'}</div>
    <div class="count" style="margin-top:6px">${hits.length} of ${all.length} entr${
      all.length===1?'y':'ies'}${hits.length>shown.length
        ? ` · showing the first ${shown.length}, keep typing`:''}</div>`;
}
// Only the results are redrawn — re-rendering the tab would take the focus out
// of the box on every keystroke.
function edUgFilter(v){
  const e=state.ed; if(!e.ug)return;
  e.ug.filter=v;
  const box=document.getElementById('ugHits');
  if(box)box.innerHTML=edUgBrowseHits(); else edRenderTab();
}
function edUgAddOne(name){
  const e=state.ed,again=csv(edFieldVal('armour_ug_models')).includes(name);
  if(!edUgAppend([name],null,{repeat:true}).length)return;
  e.ug=null; edRenderTab(); edPreview();
  toast(`“${name}” added as ${again?'a repeated':'an'} armour tier ✓`);
}

/* -- mode 4: a new entry based on one of this unit's -- */
function edUgNewBody(){
  const e=state.ed,u=e.ug;
  const own=(e.d.models||[]).filter(m=>!m.missing).map(m=>m.name);
  if(!own.length)return `<div class="count w-warn">This unit has no readable modeldb entry
    to base a new one on.</div>`;
  return `<div class="prow" style="grid-template-columns:var(--plw) 1fr auto">
      <span class="pl">Base it on</span>
      <select onchange="state.ed.ug.from=this.value">${own.map(n=>
        `<option value="${esc(n)}" ${u.from===n?'selected':''}>${esc(n)}</option>`).join('')}</select>
      <button class="primary" onclick="edUgNewFromTier()">Set it up…</button></div>
    <div class="count" style="margin-top:7px">Adds the tier and opens the new-entry form on the
      <b>Battle models</b> tab: name it, pick its folder, and point it at its own mesh and texture.
      Everything else is copied from the entry you based it on.</div>`;
}
function edUgNewFromTier(){const u=state.ed.ug; edAddArmourTier(u&&u.from);}
// Jump straight to a model's entry in the bmdb tab (the ✎ beside an armour tier
// and the model links elsewhere both land here).
function edJumpModel(name){
  const e=state.ed,key=(name||'').toLowerCase();
  if(!e.d.models.some(m=>m.name===key)){
    if(e.newModels.some(n=>n.name===key)){e.tab='models'; renderEditor(); return;}
    toast(`“${name}” is not one of this unit's model entries`); return;
  }
  e.tab='models'; e.open[key]=true; renderEditor();
  const el=document.querySelector(`#edBody .mentry[data-entry="${cssq(key)}"]`);
  if(el)el.scrollIntoView({block:'center'});
}
// Mode 4 of the ＋ menu: clone `src` (the last tier when unset) into a brand-new
// entry, add it as the next tier, bump armour_ug_levels, and open the form to
// give it its own mesh/texture — an upgrade tier pointing at the same files as
// the tier below it is not an upgrade.
function edAddArmourTier(src){
  const e=state.ed,spec=edUgNewSpec(src);
  if(!spec)return;
  // the tier list and levels are set now so the chips show it straight away;
  // dropping the pending entry puts both back
  const tier=edUgSnapshot();
  if(!edUgAppend([spec.name]).length)return;
  e.form={clone_from:spec.src,name:spec.name,dest_dir:spec.dest_dir,
          mesh_src:'',texture_src:'',normal_src:'',sprite_src:'',
          mesh_all_lods:true,apply_to_attach:false,assign_to:'',_tier:tier};
  e.ug=null; e.tab='models'; renderEditor();
}

/* ---- battle model entries ----
   One entry per card: its name, who else uses it, its meshes, ONE set of default
   textures that every faction inherits, the faction checklist (with a per-faction
   override panel where a faction needs its own skin), and the folder its files
   live in. */
const TEX_KINDS=['texture','normal','sprite','attach_texture','attach_normal'];
// the sub-folder the standard layout keeps a model's textures in — mirrors
// edit.TEXTURE_SUBDIR, and the two have to agree or the preview lies
const TEX_SUBDIR='textures';
const KIND_LABEL={texture:'Texture',normal:'Normal map',sprite:'Sprite (.spr)',
  attach_texture:'Attachment texture',attach_normal:'Attachment normal map'};
// An attachment has no sprite — the format stores an empty string there — so
// that slot is never offered.
const edKinds=m=>['texture','normal','sprite'].concat(
  m.has_attach?['attach_texture','attach_normal']:[]);
const edFacs=m=>((state.ed.mEdits[m.name]||{}).factions)||m.factions;
// What each faction's slots read right now: the entry's own values, with the
// edits made in this session on top. Anything equal to the default is *not* sent
// as an override, so changing a default really does reach every faction that
// shares it — and only those.
// With a folder move pending, every path shown (and sent) is the one it will
// have AFTER the move — otherwise the boxes would still read the old folder and
// send it straight back.
function edRebase(name,val,kind){
  const me=state.ed.mEdits[name]||{};
  if(!me.move_dir||!val||kind==='sprite')return val;
  const base=me.move_dir.replace(/\/+$/,''),file=val.split('/').pop();
  return (kind==='mesh'?base:base+'/'+TEX_SUBDIR)+'/'+file;
}
function edTexView(m){
  const me=state.ed.mEdits[m.name]||{};
  const defs={},facs={};
  const merged=Object.assign({},m.texture_defaults,me.defaults||{});
  Object.keys(merged).forEach(k=>{defs[k]=edRebase(m.name,merged[k],k);});
  edFacs(m).forEach(f=>{
    const src=Object.assign({},m.textures[f]||{},(me.faction_paths||{})[f]||{}),out={};
    Object.keys(src).forEach(k=>{out[k]=edRebase(m.name,src[k],k);});
    facs[f]=out;});
  return {defs,facs};
}
function edModels(){
  const e=state.ed,d=e.d;
  const pending=e.newModels.map((n,i)=>`<div class="pending">
      <button class="x" onclick="edDropNew(${i})" title="Discard">✕</button>
      <b>${esc(n.name)}</b>: new entry cloned from
      <a class="ulink" onclick="edJumpModel('${q1(esc(n.clone_from))}')">${esc(n.clone_from)}</a>
      ${n.assign_to?` → <code>${esc(n.assign_to)}</code>`:''}
      ${n._tier?' <span class="count">· next armour tier</span>':''}
      <div class="count">${esc(n.dest_dir||'(no folder)')} · ${n.mesh_src?esc(n.mesh_src.split(/[\\\/]/).pop()):'(clone mesh)'}
        · ${n.texture_src?esc(n.texture_src.split(/[\\\/]/).pop()):'(clone texture)'}
        <button style="padding:1px 7px;font-size:11px;margin-left:6px" onclick="edEditNew(${i})">Edit…</button></div></div>`).join('');
  const entries=d.models.map((m,i)=>edModelCard(m,i)).join('');
  return `${pending}${e.form?edNewModelForm():''}
    <div class="count" style="margin-bottom:8px">Paths are relative to the mod's <code>data/</code> folder.
      “Import…” copies a file from anywhere on disk into the mod and points the slot at it.</div>
    ${entries}`;
}
function edModelCard(m,idx){
  const e=state.ed;
  if(m.missing) return `<div class="mentry"><div class="mhead">
      <span class="mn w-bad">${esc(m.name)}</span>
      <span class="count">Missing from this mod's modeldb${m.slots.length?` · ${m.slots.map(esc).join(', ')}`:''}</span>
    </div></div>`;
  const open=!!e.open[m.name];
  const me=e.mEdits[m.name]||{};
  const facs=edFacs(m);
  const meshes=m.paths.filter(p=>p.group==='lod').map(p=>{
    const cur=edRebase(m.name,(me.paths&&p.i in me.paths)?me.paths[p.i]:p.value,'mesh');
    return `<div class="prow">
      <span class="pl" title="${esc(p.label)}">${esc(p.label)}</span>
      <input data-entry="${esc(m.name)}" data-i="${p.i}" value="${esc(cur)}"
        title="${esc(cur)}" class="${cur!==p.value?'changed':''}">
      <button onclick="edImportPath('${q1(esc(m.name))}',${p.i},'mesh')">Import…</button>
      <button onclick="edResetPath('${q1(esc(m.name))}',${p.i})" title="Undo this change">↺</button></div>`;
  }).join('');
  const cvOn=!!(e.mcv&&e.mcvName===m.name);
  return `<div class="mentry" data-entry="${esc(m.name)}">
    <div class="mhead" onclick="edToggle('${q1(esc(m.name))}')">
      <span>${open?'▾':'▸'}</span><span class="mn">${esc(m.name)}</span>
      <span class="grow count">${m.slots.map(esc).join(', ')
        ||(e.bmdb?'<span class="w-warn">nothing references it</span>':'referenced by this unit')}
        · ${m.lods.length} LOD${m.lods.length===1?'':'s'} · ${facs.length} skin${facs.length===1?'':'s'}</span>
      ${open&&!e.bmdb?`<button class="${cvOn?'on':''}" title="Show this entry exactly as
battle_models.modeldb stores it, beside the boxes."
        onclick="event.stopPropagation();edModelCv('${q1(esc(m.name))}')">&lt;/&gt;</button>`:''}
      ${edSharedDrop(m)}
    </div>
    ${open?`<div class="cvsplit${cvOn?'':' off'}">
      <div class="mbody2" id="edmGui${idx}">
      <div class="prow" style="grid-template-columns:var(--plw) 1fr auto">
        <span class="pl">Entry name</span>
        <input id="edmn${idx}" value="${esc(me.new_name||m.name)}"
          oninput="edRename('${q1(esc(m.name))}',${idx},this.value)"
          class="${me.new_name?'changed':''}">
        <button onclick="edNewFrom('${q1(esc(m.name))}')">＋ New entry from this</button>
      </div>
      <div class="prow" style="grid-template-columns:var(--plw) 1fr"><span class="pl"></span>
        <span id="edmns${idx}" class="count">${edNameHint(m,me.new_name||m.name)}</span></div>
      <div class="count" style="margin-top:5px">Skeletons: ${m.skeletons.map(esc).join(', ')||'none'}</div>
      ${edFolderBox(m)}
      <div class="psec">Meshes (LODs)</div>${meshes||'<div class="count">none</div>'}
      ${edDefaultTextures(m)}
      ${edFactionSkins(m)}
      </div>
      ${cvOn?`<div id="edmCode${idx}">${cvHtml(e.mcv)}</div>`:''}
      </div>`:''}</div>`;
}
/* The modeldb pane on the unit editor's Models tab. The BMDB mode has had one
   since Phase 4b; this is the same widget on the same kind, pointed at whichever
   model card is open — one at a time, because two panes of the same file side by
   side is two answers to the same question. */
async function edModelCv(name){
  const e=state.ed;
  if(e.mcv&&e.mcvName===name){cvDrop(e.mcv); e.mcv=null; e.mcvName=''; edRenderTab(); return;}
  if(e.mcv)cvDrop(e.mcv);
  const idx=(e.d.models||[]).findIndex(m=>m.name===name);
  e.mcvName=name;
  e.mcv=cvCreate(bmCvHost(name,'edmGui'+idx,edRenderTab));
  edRenderTab();
  await cvLoad(e.mcv);
  if(state.ed===e&&e.mcv&&e.mcvName===name)edRenderTab();
}
/* "shared with" — every unit that references this entry, each a link that opens
   that unit in its own tab. */
function edSharedDrop(m){
  const users=m.used_by||[],bm=!!state.ed.bmdb;
  if(!users.length)return `<span class="count">${bm?'used by nothing':'only this unit'}</span>`;
  return `<details class="drop" onclick="event.stopPropagation()">
    <summary class="${bm?'':'w-warn'}">${bm?`used by ${users.length}`
      :`⚠ shared with ${users.length} other${users.length===1?'':'s'}`} ▾</summary>
    <div class="dropbody" style="position:absolute;z-index:5;min-width:230px">
      <div class="count" style="margin-bottom:5px">Editing this entry changes ${bm?'every one of them'
        :'them too. Use “＋ New entry from this” to affect only this unit'}.</div>
      ${users.map(u=>`<div class="urow">${userLink(u)}</div>`).join('')}
    </div></details>`;
}
function edNameHint(m,val){
  const e=state.ed,v=(val||'').trim().toLowerCase();
  if(!v)return '<span class="w-bad">the entry needs a name</span>';
  if(v===m.name)return 'unchanged';
  if(/\s/.test(v))return '<span class="w-bad">✗ entry names cannot contain spaces</span>';
  if(e.d.model_names.includes(v)||e.newModels.some(n=>n.name===v))
    return '<span class="w-bad">✗ Taken. Another entry in this mod already has that name.</span>';
  const n=(m.used_by||[]).length+1;
  return `<span class="w-good">✓ Available.</span> ${n} unit reference${n===1?'':'s'} will be
    rewritten to match across the whole EDU`;
}

/* ---- the default texture set every faction inherits ---- */
function edDefaultTextures(m){
  const v=edTexView(m);
  const rows=edKinds(m).map(k=>`<div class="prow" style="grid-template-columns:var(--plw) 1fr auto">
      <span class="pl">${KIND_LABEL[k]}</span>
      <input data-def="${esc(m.name)}" data-kind="${k}" value="${esc(v.defs[k]||'')}"
        title="${esc(v.defs[k]||'')}"
        class="${(state.ed.mEdits[m.name]||{}).defaults&&k in state.ed.mEdits[m.name].defaults?'changed':''}">
      <button onclick="edImportDefault('${q1(esc(m.name))}','${k}')">Import…</button></div>`).join('');
  return `<div class="psec">Default textures and sprites</div>
    <div class="count">Used by every faction below unless that faction is given its own.</div>
    ${rows}`;
}
/* ---- the faction checklist, with a per-faction override panel ---- */
function edFactionSkins(m){
  const e=state.ed,chosen=edFacs(m),set=new Set(chosen);
  const all=(e.d.all_factions||[]).slice();
  chosen.forEach(f=>{if(!all.includes(f))all.push(f);});
  all.sort((a,b)=>edFacLabel(a).localeCompare(edFacLabel(b)));
  const v=edTexView(m),kinds=edKinds(m);
  // Tokens descr_sm_factions.txt does not define. They stay in the list (they
  // are in the file, and unticking one would drop a skin) but they are marked,
  // because a checklist that quietly offers `ents` alongside `timurids` reads as
  // the tool having found a faction the mod does not have.
  const odd=new Set(e.d.unknown_factions||[]);
  const rows=all.map(f=>{
    const on=set.has(f),key=m.name+'|'+f,open=!!e.facOpen[key];
    const uniq=on&&kinds.some(k=>(v.facs[f]||{})[k]&&v.facs[f][k]!==v.defs[k]);
    const bad=odd.has(f.toLowerCase());
    return `<div class="facrow">
        <label class="chk"><input type="checkbox" ${on?'checked':''}
          onchange="edFacToggle('${q1(esc(m.name))}','${q1(esc(f))}',this.checked)">
          ${esc(edFacLabel(f))}</label>
        ${bad?`<span class="fc w-warn" title="No faction with this name in this mod’s
descr_sm_factions.txt. The modeldb still names it, so the record is kept.">not a faction here</span>`:''}
        ${on?`<button class="uq ${uniq||open?'on':''}" title="Give ${esc(f)} its own textures"
          onclick="edFacUnique('${q1(esc(m.name))}','${q1(esc(f))}')">${uniq?'✎ unique':'✎'}</button>`:''}
      </div>${on&&open?edFacUniquePanel(m,f,v,kinds):''}`;
  }).join('');
  return `<div class="psec">Factions (which factions this model has a skin for)</div>
    <div class="barrow" style="margin-top:4px">
      <button onclick="edFacAll('${q1(esc(m.name))}',true)">All</button>
      <button onclick="edFacAll('${q1(esc(m.name))}',false)">None</button>
      <span class="count">${chosen.length} selected${
        chosen.length?` · first = <b>${esc(chosen[0])}</b> (the record new skins are cloned from)`:''}</span>
    </div>
    <div class="faclist">${rows}</div>`;
}
function edFacUniquePanel(m,f,v,kinds){
  const cur=v.facs[f]||{};
  return `<div class="facuniq">
    <div class="count" style="margin-bottom:4px"><b>${esc(edFacLabel(f))}</b>. Leave a box empty
      to fall back to the default above.</div>
    ${kinds.map(k=>{const own=cur[k]&&cur[k]!==v.defs[k];
      return `<div class="prow" style="grid-template-columns:calc(var(--plw) - 10px) 1fr auto">
        <span class="pl">${KIND_LABEL[k]}</span>
        <input data-fac="${esc(m.name)}" data-f="${esc(f)}" data-kind="${k}"
          value="${esc(own?cur[k]:'')}" placeholder="${esc(v.defs[k]||'(default)')}"
          title="${esc(own?cur[k]:v.defs[k]||'')}" class="${own?'changed':''}">
        <button onclick="edImportFac('${q1(esc(m.name))}','${q1(esc(f))}','${k}')">Import…</button>
      </div>`;}).join('')}</div>`;
}
function edFacToggle(name,fac,on){
  const m=state.ed.d.models.find(x=>x.name===name);
  const me=edTouch(name),list=(me.factions||m.factions).slice(),i=list.indexOf(fac);
  if(on&&i<0)list.push(fac); else if(!on&&i>=0)list.splice(i,1);
  me.factions=list; edRenderTab();
}
function edFacAll(name,on){
  const e=state.ed,m=e.d.models.find(x=>x.name===name),me=edTouch(name);
  if(!on&&m.factions.length){
    // one record has to survive: an entry with no faction skin can't be drawn
    me.factions=[ (me.factions||m.factions)[0] ];
    toast('Kept one faction. A battle model needs at least one skin.');
  } else if(on){
    const all=(e.d.all_factions||[]).slice();
    (me.factions||m.factions).forEach(f=>{if(!all.includes(f))all.push(f);});
    me.factions=all;
  }
  edRenderTab();
}
function edFacUnique(name,fac){
  const e=state.ed,k=name+'|'+fac; e.facOpen[k]=!e.facOpen[k]; edRenderTab();
}

/* ---- "all this model's files in one folder" ---- */
function edFolderBox(m){
  const e=state.ed,me=e.mEdits[m.name]||{},f=m.folder,chk=e.folder[m.name];
  const target=me.move_dir||(chk&&chk.target)||f.base||f.suggestion;
  if(me.move_dir) return `<div class="folderbox">
    <b class="w-good">✓ Files will move into <span class="fpath">data/${esc(me.move_dir)}</span></b>
    <div class="count" style="margin-top:4px">Meshes there, textures in <code>textures/</code>, sprites
      left alone.
      ${me.move_shared?'<b class="w-warn">Other entries using these files are repointed too.</b>'
                      :'Other entries keep their paths.'}</div>
    <div class="barrow"><button onclick="edFolderCancel('${q1(esc(m.name))}')">Undo this move</button></div>
  </div>`;
  // `folders` is already collapsed server-side: a model folder and its
  // textures/ sub-folder are ONE folder (that is the layout), and two spellings
  // of the same folder are one folder too. Attachment sets live in `external`
  // and are never counted — they are shared packs, like sprites.
  const folders=f.folders||[...new Set((f.mesh_dirs||[]).concat(f.texture_dirs||[]))];
  const ext=f.external_dirs||[];
  const extNote=ext.length?`<div class="count" style="margin-top:4px">Attachment textures live
    in ${ext.map(d=>`<span class="fpath">data/${esc(d)}</span>`).join(', ')}: a shared set,
    so it is left where it is.</div>`:'';
  const head=f.standardized
    ? `<b>Model folder</b> <span class="fpath">data/${esc(f.base)}</span>
       <div class="count" style="margin-top:3px">Meshes here, textures in its
         <code>${TEX_SUBDIR}/</code>, one folder.</div>${extNote}`
    : `<b class="w-warn">⚠ No single model folder</b>
       <div class="count" style="margin-top:3px">This entry's files are spread across
         ${folders.length} folder(s):
         ${folders.map(d=>`<div class="fpath">data/${esc(d||'(data root)')}</div>`).join('')}
         Standardise them into one folder?</div>${extNote}`;
  return `<div class="folderbox${f.standardized?'':' bad'}">
    ${head}
    <div class="frow2">
      <input id="edfd_${esc(m.name)}" value="${esc(target)}" placeholder="unit_models/_Units/my_model">
      <button onclick="edFolderPick('${q1(esc(m.name))}')">Browse…</button>
      <button class="${f.standardized?'':'primary'}" onclick="edFolderCheck('${q1(esc(m.name))}')">${
        f.standardized?'Change folder…':'Standardise…'}</button>
    </div>
    ${chk?edFolderCheckHtml(m,chk):''}</div>`;
}
function edFolderCheckHtml(m,chk){
  if(chk.error)return `<div class="count w-bad" style="margin-top:6px">${esc(chk.error)}</div>`;
  if(!chk.moves.length)return `<div class="count w-good" style="margin-top:6px">Nothing to move.
    every file is already where <span class="fpath">data/${esc(chk.target_rel)}</span> wants it.</div>`;
  const missing=chk.moves.filter(x=>x.missing);
  const shared=chk.shared_entries||[];
  return `<div style="margin-top:8px;border-top:1px solid var(--edge);padding-top:7px">
    <div class="count">${chk.moves.length} file(s) would move:</div>
    <div class="movelist">${chk.moves.map(x=>`<div>${esc(x.old)} → <b>${esc(x.new)}</b>${
      x.missing?' <span class="w-warn">(not on disk)</span>':''}</div>`).join('')}</div>
    ${missing.length?`<div class="count w-warn" style="margin-top:5px">${missing.length} of them
      aren't on disk. Those entries are repointed anyway; put the files there yourself.</div>`:''}
    ${shared.length?`<div class="count w-warn" style="margin-top:6px">⚠ <b>${shared.length} other
      model entr${shared.length===1?'y also uses':'ies also use'} these files:</b>
      ${shared.map(n=>`<code>${esc(n)}</code>`).join(', ')}.<br>
      Moving without updating them leaves those entries pointing at the old files.</div>
      <div class="barrow">
        <button class="primary" onclick="edFolderApply('${q1(esc(m.name))}',true)">Edit and move anyway, updating all ${shared.length}</button>
        <button onclick="edFolderApply('${q1(esc(m.name))}',false)">Move only this entry</button>
      </div>`
    :`<div class="barrow"><button class="primary" onclick="edFolderApply('${q1(esc(m.name))}',false)">Move the files</button></div>`}
  </div>`;
}
function edFolderTarget(name){
  const el=document.getElementById('edfd_'+name); return el?el.value.trim():'';
}
async function edFolderCheck(name){
  const e=state.ed,target=edFolderTarget(name);
  if(!target){toast('Give the folder a path first');return;}
  const r=await api.post('/api/edit/model_folder',{mod:e.mod,entry:name,target});
  e.folder[name]=r; edRenderTab();
}
async function edFolderPick(name){
  const r=await api.post('/api/browse_folder',{title:'Folder inside the mod’s data\\ for this model'});
  if(!r.path)return;
  const el=document.getElementById('edfd_'+name); if(el)el.value=relInMod(r.path);
  edFolderCheck(name);
}
function edFolderApply(name,shared){
  const chk=state.ed.folder[name]||{},me=edTouch(name);
  me.move_dir=chk.target_rel||edFolderTarget(name); me.move_shared=!!shared;
  delete state.ed.folder[name]; edRenderTab(); edPreview();
}
function edFolderCancel(name){
  const me=edTouch(name); me.move_dir=''; me.move_shared=false;
  edRenderTab(); edPreview();
}

function edToggle(name){const e=state.ed;e.open[name]=!e.open[name];edRenderTab();}
function edME(name){const e=state.ed;
  if(!e.mEdits[name])e.mEdits[name]={new_name:'',paths:{},copies:[],defaults:{},
    faction_paths:{},factions:null,move_dir:'',move_shared:false,_touched:false};
  return e.mEdits[name];}
// Only a *touched* entry is sent to the server — opening a card must never
// rewrite paths that merely happened to be displayed.
function edTouch(name){const me=edME(name); me._touched=true; edStale(); return me;}
function edRename(name,idx,v){
  const me=edTouch(name);
  me.new_name=(v.trim().toLowerCase()===name)?'':v.trim().toLowerCase();
  const m=state.ed.d.models.find(x=>x.name===name);
  const hint=document.getElementById('edmns'+idx);
  if(hint)hint.innerHTML=edNameHint(m,v);
}
function edSetPath(name,i,v){const me=edTouch(name);me.paths[i]=v;}
function edResetPath(name,i){const me=edTouch(name);delete me.paths[i];
  me.copies=(me.copies||[]).filter(c=>c.i!==i); edRenderTab();}
async function edImportPath(name,i,kind){
  const filt=kind==='mesh'?'Meshes (*.mesh)|*.mesh|All files (*.*)|*.*'
            :kind==='sprite'?'Sprites (*.spr)|*.spr|All files (*.*)|*.*'
            :'Textures (*.texture)|*.texture|All files (*.*)|*.*';
  const r=await api.post('/api/browse_file',{title:'Select a file to import',filter:filt});
  if(!r.path)return;
  const m=state.ed.d.models.find(x=>x.name===name);
  const slot=m.paths.find(p=>p.i===i);
  const me=edME(name);
  const cur=(i in me.paths)?me.paths[i]:slot.value;
  const dir=cur.includes('/')?cur.slice(0,cur.lastIndexOf('/')):'unit_models';
  const file=r.path.split(/[\\\/]/).pop();
  me.paths[i]=dir+'/'+file;
  me.copies=(me.copies||[]).filter(c=>c.i!==i).concat([{i,src:r.path,dest_dir:dir}]);
  edRenderTab(); edPreview();
}

/* ---- new bmdb entry cloned from an existing one ---- */
function edNewFrom(name){
  const e=state.ed,m=e.d.models.find(x=>x.name===name)||{};
  e.form={clone_from:name,name:(e.newType||e.d.type).toLowerCase().replace(/[^a-z0-9_]+/g,'_'),
          dest_dir:(m.folder&&(m.folder.base||m.folder.suggestion))
                   ||('unit_models/'+(e.mod||'').replace(/[^A-Za-z0-9._-]+/g,'_')),
          mesh_src:'',texture_src:'',normal_src:'',sprite_src:'',
          mesh_all_lods:true,apply_to_attach:false,
          assign_to:(m.slots||[])[0]||'soldier'};
  e.open[name]=true; edRenderTab();
}
function edEditNew(i){
  const e=state.ed; e.form=Object.assign({_editing:i},e.newModels[i]); edRenderTab();
}
function edNewModelForm(){
  const e=state.ed,f=e.form;
  const slots=['','soldier'];
  e.d.fields.forEach(([l])=>{const k=l.replace(/#\d+$/,'');
    if(k==='officer')slots.push(l==='officer'?'officer#1':l);});
  const arm=(e.d.fields.find(([l])=>l==='armour_ug_models')||[])[1];
  if(arm)arm.split(',').forEach((_x,i)=>slots.push('armour_ug_models#'+(i+1)));
  const file=(v)=>v?esc(v):'<span class="count">Not set, so the clone’s file is kept.</span>';
  return `<div class="newmodel">
    <b>New model entry cloned from <code>${esc(f.clone_from)}</code></b>
    <div class="count" style="margin-top:3px">Sprites, the faction (ownership) texture records and the
      footer (animations, skeletons and torch) are copied from that entry, so the new model stays valid.</div>
    <div class="fbrow"><span class="k">Entry name</span>
      <input value="${esc(f.name)}" oninput="edForm('name',this.value)"><span></span></div>
    <div class="fbrow"><span class="k">Copy files into</span>
      <input value="${esc(f.dest_dir)}" oninput="edForm('dest_dir',this.value)"
        placeholder="unit_models/my_folder">
      <button onclick="edPickDir()">Browse…</button></div>
    <div class="fbrow"><span class="k">Mesh (.mesh)</span><div>${file(f.mesh_src)}</div>
      <button onclick="edPickFile('mesh_src','Meshes (*.mesh)|*.mesh|All files (*.*)|*.*')">Choose…</button></div>
    <div class="fbrow"><span class="k">Texture</span><div>${file(f.texture_src)}</div>
      <button onclick="edPickFile('texture_src','Textures (*.texture)|*.texture|All files (*.*)|*.*')">Choose…</button></div>
    <div class="fbrow"><span class="k">Normal map</span><div>${file(f.normal_src)}</div>
      <button onclick="edPickFile('normal_src','Textures (*.texture)|*.texture|All files (*.*)|*.*')">Choose…</button></div>
    <div class="fbrow"><span class="k">Sprite (.spr)</span><div>${file(f.sprite_src)}</div>
      <button onclick="edPickFile('sprite_src','Sprites (*.spr)|*.spr|All files (*.*)|*.*')">Choose…</button></div>
    <div style="margin-top:8px">
      <label class="chk"><input type="checkbox" ${f.mesh_all_lods?'checked':''}
        onchange="edForm('mesh_all_lods',this.checked)"> use the mesh for every LOD</label>
      <label class="chk" style="margin-left:14px"><input type="checkbox" ${f.apply_to_attach?'checked':''}
        onchange="edForm('apply_to_attach',this.checked)"> also repoint attachment textures</label>
    </div>
    <div class="fbrow"><span class="k">Point EDU slot at it</span>
      <select onchange="edForm('assign_to',this.value)">
        ${slots.map(s=>`<option value="${esc(s)}" ${f.assign_to===s?'selected':''}>${s?esc(s):'Don’t change the unit'}</option>`).join('')}
      </select><button class="primary" onclick="edAddNewModel()">${
        f._editing===undefined?'Add entry':'Save entry'}</button></div>
  </div>`;
}
function edForm(k,v){state.ed.form[k]=v; if(k==='mesh_all_lods'||k==='apply_to_attach')return; }
async function edPickFile(key,filter){
  const r=await api.post('/api/browse_file',{title:'Select a file to import',filter});
  if(r.path){state.ed.form[key]=r.path; edRenderTab();}
}
async function edPickDir(){
  const r=await api.post('/api/browse_folder',{title:'Folder inside the mod’s data\\ to copy the files into'});
  if(r.path){state.ed.form.dest_dir=relInMod(r.path); edRenderTab();}
}
function edAddNewModel(){
  const e=state.ed,f=e.form;
  if(!f.name.trim()){toast('The new entry needs a name');return;}
  const entry=Object.assign({},f,{name:f.name.trim().toLowerCase()});
  const at=entry._editing; delete entry._editing;
  if(at===undefined)e.newModels.push(entry); else e.newModels[at]=entry;
  e.form=null; edRenderTab(); edPreview();
}
// Discarding a pending entry has to undo what adding it changed — an armour tier
// also wrote armour_ug_models / armour_ug_levels.
function edDropNew(i){
  const e=state.ed,[gone]=e.newModels.splice(i,1);
  if(gone&&gone._tier){
    edRestoreField('armour_ug_models',gone._tier.models);
    edRestoreField('armour_ug_levels',gone._tier.levels);
  }
  edRenderTab(); edPreview();
}

/* ---- preview / save / delete ---- */
// bmdb mode posts the very same body to the very same planner, minus the unit —
// see unittransfer.edit.plan_bmdb.
const edApi=p=>(state.ed&&state.ed.bmdb?'/api/bmdb/':'/api/edit/')+p;
async function edPreview(){
  const box=document.getElementById('edPreview'); if(!box)return null;
  await cvSettle(state.ed.cv);          // read the last keystroke before planning
  const blocked=edCvBlocked();
  if(blocked){box.innerHTML=`<div class="preview w-bad">${esc(blocked)}</div>`; return null;}
  box.innerHTML='<div class="preview">Planning…</div>';
  const r=await api.post(edApi('plan'),edPayload());
  if(r.error){box.innerHTML=`<div class="preview w-bad">${esc(r.error)}</div>`;return null;}
  state.ed.plan=r; state.ed.planStale=false;
  box.innerHTML=edPlanHtml(r);
  // the unit being compared against is a save of its own, so it gets its own
  // plan under the first one rather than being silently left out of it
  if(edCmpDirty()){
    const cr=await api.post('/api/edit/plan',edCmpPayload());
    box.insertAdjacentHTML('beforeend',cr.error
      ? `<div class="preview w-bad">${esc(state.ed.cmp.unit)}: ${esc(cr.error)}</div>`
      : `<div class="count" style="margin-top:8px">…and for
          <b>${esc(state.ed.cmp.unit)}</b>:</div>`+edPlanHtml(cr));
  }
  return r;
}
function edStale(){const e=state.ed;
  // every path that changes a field ends here, so this is where the text pane
  // finds out it has to be re-serialised
  if(e&&e.cv)cvFromGui(e.cv);
  if(e&&e.plan&&!e.planStale){e.planStale=true;
  const b=document.getElementById('edPreview'); if(b)b.innerHTML=edPlanHtml(e.plan,true);}}
function edPlanHtml(r,stale){
  const li=(cls,items)=>items.map(x=>`<div class="srow ${cls}"><span class="sicon">${
      cls==='bad'?'✗':cls==='warn'?'!':'·'}</span><span class="stext">${esc(x)}</span></div>`).join('');
  return `<div class="sum" style="margin-top:10px">
    <div class="srow shead"><span class="sicon">✎</span><span class="stext">Pending changes${
      stale?' <span class="w-warn">Edited since this preview. Press Preview again.</span>':''}</span></div>
    ${li('',r.changes.length?r.changes:['no changes'])}
    ${r.files_written.length?`<div class="srow"><span class="sicon">💾</span><span class="stext">writes ${
      r.files_written.map(f=>`<span class="path">${esc(f)}</span>`).join(', ')}</span></div>`:''}
    ${(r.ref_counts||[]).length?`<div class="srow"><span class="sicon">🔗</span><span class="stext">the
      renamed unit is followed into ${r.ref_counts.length} more file(s): ${
      r.ref_counts.map(x=>`<span class="path">${esc(x.file)}</span> <b>×${x.hits}</b>`).join(', ')
      }</span></div>`:''}
    ${li('warn',r.warnings)}${li('bad',r.errors)}</div>`;
}
async function edSave(){
  const e=state.ed,bm=!!e.bmdb;
  await cvSettle(e.cv);                 // the last keystroke counts
  const blocked=edCvBlocked();
  if(blocked){toast(blocked); return;}
  const one=edDirty(),two=edCmpDirty();
  if(!one&&!two){toast('Nothing to save');return;}
  // Both units are planned BEFORE either is written, so a problem with the
  // second one is found while nothing has been touched — half a save is worse
  // than none when the two were being balanced against each other.
  let r=null,cr=null;
  if(one){
    r=await api.post(edApi('plan'),edPayload());
    if(r.error){toast('Error: '+r.error);return;}
    if(r.errors&&r.errors.length){
      document.getElementById('edPreview').innerHTML=edPlanHtml(r);
      toast(r.errors[0]);return;}
  }
  if(two){
    cr=await api.post('/api/edit/plan',edCmpPayload());
    if(cr.error){toast(`Error in ${e.cmp.unit}: ${cr.error}`);return;}
    if(cr.errors&&cr.errors.length){toast(`${e.cmp.unit}: ${cr.errors[0]}`);return;}
  }
  const what=bm?e.d.models[0].name:e.unit;
  const writing=[one?what:null,two?e.cmp.unit:null].filter(Boolean).join(' and ');
  document.getElementById('modal').innerHTML=`<h2>Saving…</h2>
    <div class="mbody"><div class="progress-track"><div class="progress-fill" style="width:60%"></div></div>
    <div class="count" style="margin-top:8px">Writing ${esc(writing)} into ${esc(e.mod)}…</div></div>`;
  let res=null;
  if(one){
    res=await api.post(edApi('apply'),edPayload({clear_strings_bin:clearBinOn()}));
    if(res.error){toast('Save failed: '+res.error);bm?renderBmdbEditor():renderEditor();return;}
  }
  if(two){
    const res2=await api.post('/api/edit/apply',edCmpPayload({clear_strings_bin:clearBinOn()}));
    if(res2.error){
      toast(`${one?'Saved '+what+', but ':''}saving ${e.cmp.unit} failed: ${res2.error}`,5000);
      renderEditor(); return;}
    if(!res)res=res2;
    e.cmp.ov={}; e.cmp.rm=new Set(); e.cmp.added=new Set();
  }
  closeModal();
  const saved=[one?(bm?what:res.plan.resolved_type):null,two?e.cmp.unit:null].filter(Boolean);
  toast(`Saved ${saved.map(s=>'“'+s+'”').join(' and ')} ✓${binMsg(res)}  (undo in 🕑 Log)`,4200);
  state.destData=null; state.bmdb=null; loadSource();
}
