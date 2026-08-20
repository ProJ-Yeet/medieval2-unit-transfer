/* ancillaries.js — Ancillaries mode: export_descr_ancillaries.txt, both halves

   Part of the Medieval 2 GUI Toolkit UI. These files are plain
   <script> tags sharing ONE global scope, loaded in the order set in
   index.html — there is no build step and no module system. Two rules
   follow from that: a top-level name must be unique across all of
   them, and a file's top-level side effects may not depend on a file
   loaded after it. */
/* ======================= ANCILLARIES MODE =======================
   The retinue: the items and followers a character picks up. EDA is EDCT's
   smaller sibling — same file shape, same trigger language below — so this
   screen is the traits screen with the level ladder taken out and a picture put
   in. What differs is worth knowing:

     * `Type` groups ancillaries: a character holds one per type, so it is the
       field that decides what a new one replaces. Free-form, so the picker
       offers the ones this mod already uses rather than a fixed list.
     * `Transferable` is whether it can be handed to another character.
     * Two limits are silent and hardcoded: more than 3 ExcludedAncillaries is an
       errorless crash, more than 8 effects makes the ancillary impossible to
       gain from a trigger. Both are checked before a save, not after.
     * Its name is its own text key — unlike a trait, which borrows its first
       level's — so the box beside the name IS what the player reads.

   THE PAGE NEVER PARSES A GAME FILE: /api/ancillaries, /api/ancillary and
   /api/ancillaries/plan|apply do all of it, and a save posts back the shape the
   server's own render_block takes. */

const AN_BLANK = {name:'', type:'item', transferable:'1', image:'', unique:false,
  excluded_ancillaries:[], exclude_cultures:[], description:'',
  effects_description:'', effects:[]};

async function loadAncillaries(){
  const mod = state.src;
  main.innerHTML = '<div class="empty">Reading ' + esc(mod) + '’s ancillaries…</div>';
  let r;
  try{ r = await api.get('/api/ancillaries?mod=' + enc(mod)); }
  catch(e){ if(stale('ancillaries', mod)) return;
    main.innerHTML = `<div class="empty">Couldn't read the ancillaries file.<br>
      <span class="count">${esc(''+e)}</span><br><br>
      <button class="primary" onclick="loadAncillaries()">Retry</button></div>`; return; }
  if(stale('ancillaries', mod)) return;
  state.an = Object.assign({sel:'', d:null, busy:false, adding:false}, r);
  undoReset();
  renderAncillaries();
}

function renderAncillaries(){
  const a = state.an;
  if(!a){ loadAncillaries(); return; }
  const strip = minorTabsHtml('', 'data/export_descr_ancillaries.txt');
  if(a.error || !a.exists){
    main.innerHTML = strip + `<div class="empty">${esc(a.error || 'No ancillaries file.')}<br>
      <span class="count">They live in data/export_descr_ancillaries.txt</span></div>`;
    return;
  }
  const rows = anRows();
  count.textContent = `${rows.length}/${a.count}`;
  main.innerHTML = strip + `<div class="trwrap">
    <div class="trlist">
      <button class="trnew" onclick="anNew()">＋ New ancillary</button>
      ${findingsHtml('ancillaries', a.finding_list, 'anOpen')}
      <div class="trrows">${rows.map(anRowHtml).join('')
        || '<div class="count" style="padding:8px">No ancillary matches.</div>'}</div>
    </div>
    <div class="trmain" id="anMain">${anDetailHtml()}</div>
  </div>`;
}

// Filtered in the page: 700 rows is a list, and the file was parsed once to
// build it anyway. The type is searchable too — it is how a modder groups them.
function anRows(){
  const q = search.value.trim().toLowerCase();
  const rows = state.an.ancillaries || [];
  if(!q) return rows;
  return rows.filter(r => r.name.toLowerCase().includes(q)
    || (r.label||'').toLowerCase().includes(q)
    || (r.type||'').toLowerCase().includes(q));
}

function anRowHtml(r){
  const on = state.an.sel === r.name;
  return `<button class="trrow anrow${on?' on':''}" onclick="anOpen('${q1(esc(r.name))}')">
    <img class="anpic" src="${anImgUrl(r.image)}" alt="" loading="lazy"
      onerror="iconRetry(this)">
    <span class="antxt">
      <span class="nm">${esc(r.label)}</span>
      <span class="sub">${esc(r.type||'no type')}${r.unique?' · unique':''}${
        r.effects?` · ${r.effects} effect${r.effects===1?'':'s'}`:''}${
        r.triggers?` · ${r.triggers} trigger${r.triggers===1?'':'s'}`
                  :' · <b>nothing grants it</b>'}${
        r.findings?` <span class="w-warn">· ${r.findings}⚠</span>`:''}</span>
    </span>
  </button>`;
}

const anImgUrl = image => `/icon?mod=${enc(state.an.mod)}&kind=ancillary`
  + `&image=${enc(image||'')}`;

async function anOpen(name){
  activity('opened ancillary', `${name} in ${state.src}`);
  const a = state.an;
  a.sel = name; a.adding = false; a.d = null;
  renderAncillaries();
  let d;
  try{ d = await api.get(`/api/ancillary?mod=${enc(a.mod)}&name=${enc(name)}`); }
  catch(e){ d = {error:''+e}; }
  if(state.mode !== 'ancillaries' || state.an !== a || a.sel !== name) return;
  a.d = d.error ? d : anWorking(d);
  undoReset();          // the working copy exists now: this is Ctrl+Z's baseline
  anPaint();
  if(!d.error && state.settings.code_view) anCvToggle();
}

function anWorking(d){
  d.w = JSON.parse(JSON.stringify(d.ancillary));
  d.trigs = (d.triggers || []).map(t => ({name:t.name, ui:null, dirty:false, src:t}));
  d.locEdits = {};
  return d;
}

function anNew(){
  const a = state.an;
  a.sel = ''; a.adding = true;
  a.d = {name:'', label:'(new ancillary)',
    ancillary:JSON.parse(JSON.stringify(AN_BLANK)),
    w:JSON.parse(JSON.stringify(AN_BLANK)),
    trigs:[], findings:[], loc:{}, locEdits:{}, missing_loc:[], triggers:[],
    known:(a.ancillaries||[]).map(r=>r.name), types:a.types||[],
    attributes:a.attributes||[]};
  renderAncillaries();
}

function anPaint(){
  const el = document.getElementById('anMain');
  if(el) el.innerHTML = anDetailHtml();
  const d = state.an.d;
  if(d && d.cv){ cvWire(d.cv); cvBindHover(d.cv, document.getElementById('anGui')); }
  anWireTriggers();
}

// The form only — never the pane, which has the caret in it.
function anPaintForm(){
  const d = state.an.d, el = document.getElementById('anGui');
  if(!d || !el) return;
  el.innerHTML = anFindingsHtml(d) + anFormHtml(d.w, d);
  if(d.cv) cvBindHover(d.cv, el);
}

/* ---- the detail pane ---- */
function anDetailHtml(){
  const a = state.an, d = a.d;
  if(!a.sel && !a.adding) return `<div class="empty">Pick an ancillary on the left.<br>
    <span class="count">${a.count} ancillar${a.count===1?'y':'ies'}, ${a.triggers}
      trigger${a.triggers===1?'':'s'} in ${esc(a.file)}</span></div>`;
  if(!d) return '<div class="empty">Reading the ancillary…</div>';
  if(d.error) return `<div class="empty"><span class="w-bad">✗ ${esc(d.error)}</span></div>`;
  return `<div class="trbar">
      <div><b>${esc(a.adding ? 'New ancillary' : d.label)}</b>
        <span class="count">${esc(d.w.type || 'no type')}</span></div>
      <span class="sp"></span>
      ${a.adding ? '' : `<button class="${d.cv?'on':''}" title="Show this ancillary exactly
as export_descr_ancillaries.txt stores it, beside the form."
        onclick="anCvToggle()">&lt;/&gt; Code view</button>
      <button class="danger" onclick="anDelete()">Delete</button>`}
      <button class="primary" onclick="anSave()">${a.adding?'Create':'Save'}</button>
    </div>
    <div id="anGui">
      ${anFindingsHtml(d)}
      ${anFormHtml(d.w, d)}
    </div>
    ${d.cv ? `<div id="anCodeCol" style="padding-top:12px">${cvHtml(d.cv)}</div>` : ''}
    ${anTriggersHtml(d)}`;
}

function anFindingsHtml(d){
  const out = (d.findings||[]).map(f =>
    `<div class="trfind w-warn">line ${f.line}: ${esc(f.message)}</div>`);
  if((d.missing_loc||[]).length) out.push(`<div class="trfind w-warn">${
    d.missing_loc.length} text key(s) are not in export_ancillaries.txt (${
    d.missing_loc.map(esc).join(', ')}). Acquiring this ancillary, or opening the
    character screen holding it, crashes the game with no error. Type the words
    beside the key below, or save and they are created with the key as
    placeholder text.</div>`);
  return out.join('');
}

function anFormHtml(w, d){
  const key = (k, label, hint) => {
    const tag = w[k] || '';
    return `<label class="lbl" data-label="${k}">${label}</label>
      <div class="trkey">
        <input data-label="${k}" value="${esc(tag)}" placeholder="${esc(hint||'')}"
          oninput="anSet('${k}',this.value.trim())">
        ${tag ? `<input class="trtext" value="${esc(anLocText(d, tag))}"
          placeholder="${anHasKey(d, tag)?'':'not in export_ancillaries.txt yet'}"
          title="What the player reads. Saved into data/text/export_ancillaries.txt."
          oninput="anSetLoc('${q1(esc(tag))}',this.value)">` : ''}
      </div>`;
  };
  return `<section class="trsec">
    <div class="trsechead">The ancillary
      <span class="count">The order of these lines is what every real EDA writes, and
        this editor keeps it</span></div>
    <div class="anhead">
      <div class="anpicbox">
        <div class="icowrap">
          <img class="anbig" src="${anImgUrl(w.image)}" alt="" onerror="iconRetry(this)"
            title="Replace this picture"
            onclick="imgPick('${q1(esc(anImgUrl(w.image)))}','anPaint')">
          ${imgEditBtn(anImgUrl(w.image),'anPaint')}
        </div>
        ${imgWhereBtn(anImgUrl(w.image),'Where is it?')}
      </div>
      <div class="trgrid" style="flex:1">
        <label class="lbl" data-label="name">Name</label>
        <div class="trkey">
          <input data-label="name" value="${esc(w.name)}"
            ${state.an.adding?'':'disabled'} placeholder="ancillary_name"
            oninput="anSet('name',this.value.trim())">
          <input class="trtext" value="${esc(anLocText(d, w.name))}"
            placeholder="${anHasKey(d, w.name)?'':'the name on the character screen'}"
            title="The ancillary's name as the player sees it."
            oninput="anSetLoc('${q1(esc(w.name))}',this.value)">
        </div>
        <label class="lbl" data-label="type">Type</label>
        <div>
          <input data-label="type" value="${esc(w.type)}" list="anTypes"
            placeholder="item" oninput="anSet('type',this.value.trim())">
          <datalist id="anTypes">${(d.types||[]).map(t =>
            `<option value="${esc(t)}">`).join('')}</datalist>
          <div class="trhint count">A character holds one ancillary per type, so this
            is what a new one replaces</div>
        </div>
        <label class="lbl" data-label="image">Image</label>
        <div>
          <input data-label="image" value="${esc(w.image)}" placeholder="name.tga"
            oninput="anSet('image',this.value.trim())">
          ${d.image_found === false ? `<div class="trhint w-warn">Not found in
            data/ui/ancillaries or the vanilla UI</div>` : ''}
        </div>
        <label class="lbl" data-label="transferable">Transferable</label>
        <div data-label="transferable"><label class="chk"><input type="checkbox"
          ${w.transferable !== '0' ? 'checked' : ''}
          onchange="anSet('transferable',this.checked?'1':'0')">
          can be handed to another character</label></div>
        <label class="lbl" data-label="unique">Unique</label>
        <div data-label="unique"><label class="chk"><input type="checkbox"
          ${w.unique?'checked':''} onchange="anSet('unique',this.checked)">
          can only ever be acquired once</label></div>
      </div>
    </div>
    <div class="trgrid" style="margin-top:8px">
      <label class="lbl" data-label="excluded_ancillaries">ExcludedAncillaries</label>
      <div>
        <input data-label="excluded_ancillaries"
          value="${esc((w.excluded_ancillaries||[]).join(', '))}" list="anNames"
          placeholder="none"
          oninput="anSet('excluded_ancillaries',this.value.split(',').map(s=>s.trim()).filter(Boolean))">
        <datalist id="anNames">${(d.known||[]).map(n =>
          `<option value="${esc(n)}">`).join('')}</datalist>
        ${(w.excluded_ancillaries||[]).length > 3
          ? '<div class="trhint w-bad">More than 3 is an errorless crash.</div>'
          : (w.unique && !(w.excluded_ancillaries||[]).includes(w.name)
             ? `<div class="trhint w-warn">A Unique ancillary needs its own name here,
                or it can still be acquired twice</div>` : '')}
      </div>
      <label class="lbl" data-label="exclude_cultures">ExcludeCultures</label>
      <input data-label="exclude_cultures"
        value="${esc((w.exclude_cultures||[]).join(', '))}" placeholder="none"
        oninput="anSet('exclude_cultures',this.value.split(',').map(s=>s.trim()).filter(Boolean))">
      ${key('description','Description', w.name?w.name+'_desc':'')}
      ${key('effects_description','EffectsDescription',
            w.name?w.name+'_effects_desc':'')}
    </div>
    <div class="treffects">
      <div class="trsechead" style="margin:8px 0 0">Effects
        <span class="count">${(w.effects||[]).length}/8. More than 8 makes this
          ancillary impossible to gain from a trigger</span></div>
      ${(w.effects||[]).map((e,k)=>anEffectHtml(e,k,d)).join('')}
      ${(w.effects||[]).length < 8
        ? '<button class="trgadd" onclick="anAddEffect()">＋ Add effect</button>' : ''}
    </div>
  </section>`;
}

function anEffectHtml(e, k, d){
  const attrs = d.attributes || [];
  const known = !e.attribute || attrs.includes(e.attribute)
    || /^Combat_V_(Faction|Religion)_./.test(e.attribute);
  return `<div class="treff" data-label="effect#${k+1}">
    <input class="trattr${known?'':' bad'}" value="${esc(e.attribute)}" list="anAttrs"
      placeholder="attribute" oninput="anSetEffect(${k},'attribute',this.value.trim())">
    <input class="trnum" value="${esc(e.amount)}"
      oninput="anSetEffect(${k},'amount',this.value.trim())">
    ${known?'':'<span class="count w-warn">not a character attribute</span>'}
    <button class="trgdel" onclick="anDelEffect(${k})">✕</button>
    <datalist id="anAttrs">${attrs.map(x=>`<option value="${esc(x)}">`).join('')}</datalist>
  </div>`;
}

/* ---- the triggers that grant it ----
   `AcquireAncillary` is EDA's `Affects`, and the builder is the same one the
   traits editor hosts (web/js/triggerui.js). */
function anTriggersHtml(d){
  if(state.an.adding) return `<section class="trsec">
    <div class="trsechead">Triggers</div>
    <div class="count" style="padding:6px">Create the ancillary first. A trigger
      cannot grant one the file has not defined yet.</div></section>`;
  return `<section class="trsec">
    <div class="trsechead">Triggers <span class="count">${d.trigs.length
      ? 'what grants this ancillary' : 'nothing grants this ancillary'}</span></div>
    ${d.trigs.map((t,i)=>`<div class="trtrig">
      <div class="trtrighead"><b>${esc(t.name)}</b><span class="sp"></span>
        <button class="trgdel" title="Remove this trigger"
          onclick="anDelTrigger(${i})">✕</button></div>
      <div id="antrg-${i}"></div>
    </div>`).join('')}
    <button class="trgadd" onclick="anAddTrigger()">＋ Add trigger</button>
  </section>`;
}

async function anWireTriggers(){
  const d = state.an.d;
  if(!d || !d.trigs) return;
  for(let i = 0; i < d.trigs.length; i++){
    if(!document.getElementById('antrg-' + i)) continue;
    const row = d.trigs[i];
    if(!row.ui){
      row.ui = trgCreate({mod:state.an.mod, trigger:row.src,
        onChange:() => { row.dirty = true; }});
      await trgLoad(row.ui);
    }
    const here = document.getElementById('antrg-' + i);
    if(here) here.innerHTML = trgHtml(row.ui);
  }
}

/* ---- edits ---- */
function anSet(key, value){
  const d = state.an.d; if(!d) return;
  d.w[key] = value;
  // these change the shape of the form (a warning appears, a picture changes)
  anRepaintIf(['unique','image','excluded_ancillaries','transferable','type']
    .includes(key));
}
function anSetEffect(k, key, value){
  const e = state.an.d.w.effects[k]; if(!e) return;
  e[key] = value;
  anRepaintIf(false);
}
function anAddEffect(){
  const w = state.an.d.w;
  (w.effects = w.effects || []).push({attribute:'', amount:'1'});
  anRepaintIf(true);
}
function anDelEffect(k){
  state.an.d.w.effects.splice(k, 1);
  anRepaintIf(true);
}
const anHasKey = (d, tag) => tag && (d.loc||{})[tag] !== undefined;
function anLocText(d, tag){
  if(!tag) return '';
  const e = d.locEdits || {};
  return e[tag] !== undefined ? e[tag] : ((d.loc||{})[tag] || '');
}
function anSetLoc(tag, value){
  const d = state.an.d; if(!d || !tag) return;
  (d.locEdits = d.locEdits || {})[tag] = value;
}
// The GUI→pane half of the Code View contract: change a box and the text pane
// is re-serialised by the server, through the serialiser the save itself uses.
function anRepaintIf(yes){
  const d = state.an.d; if(!d) return;
  if(yes) anPaintForm();
  if(d.cv) cvFromGui(d.cv);
}

function anAddTrigger(){
  const d = state.an.d; if(!d) return;
  const n = (d.name || 'anc').toLowerCase() + '_' + (d.trigs.length + 1);
  d.trigs.push({name:n, ui:null, dirty:true, added:true,
    src:{name:n, when_to_test:'CharacterTurnEnd', conditions:[],
         effects:[{keyword:'AcquireAncillary', args:[d.name, 'chance', '5']}]}});
  anPaint();
}
function anDelTrigger(i){
  const d = state.an.d, row = d.trigs[i];
  if(!row.added && !confirm(`Remove trigger ${row.name}?\n\n`
    + 'It is written out of the file when you save.')) return;
  if(row.ui) trgDrop(row.ui);
  d.trigs.splice(i, 1);
  d.removed = (d.removed || []).concat(row.added ? [] : [row.name]);
  anPaint();
}

/* ---- the code view ---- */
async function anCvToggle(){
  const d = state.an.d; if(!d) return;
  if(d.cv){ cvDrop(d.cv); d.cv = null; state.settings.code_view = false;
    api.post('/api/settings', {code_view:false}); anPaint(); return; }
  state.settings.code_view = true; api.post('/api/settings', {code_view:true});
  d.cv = cvCreate({kind:'ancillaries', mod:state.an.mod, id:d.name,
    where:'data/' + state.an.file,
    edits:() => anEdits(),
    adopt:cv => { const s = state.an.d;
      if(!cv.detail) return;
      s.w = cv.detail;
      // `base`, never `text`: with comment hiding on, `text` is the view with the
      // comment-only lines cut out of it, and saving that would delete every one
      // of them. `base` is the record's real bytes.
      s.raw = cv.edited ? cv.base : ''; },
    refreshGui:() => anPaintForm()});
  anPaint();
  await cvLoad(d.cv);
  if(state.an.d !== d || !d.cv) return;
  anPaint();
}

/* ---- writing ---- */
function anEdits(){
  const w = state.an.d.w;
  return {name:w.name, type:w.type, transferable:w.transferable, image:w.image,
    unique:w.unique, excluded_ancillaries:w.excluded_ancillaries,
    exclude_cultures:w.exclude_cultures, description:w.description,
    effects_description:w.effects_description,
    effects:(w.effects||[]).filter(e => e.attribute && e.amount)};
}

function anBody(action){
  const a = state.an, d = a.d;
  const body = {mod:a.mod, ancillary:action === 'add' ? d.w.name : d.name, action};
  if(action !== 'delete'){
    body.edits = anEdits();
    body.loc = d.locEdits || {};
    if(d.raw) body.raw_block = d.raw;
    const adds = [], edits = [];
    for(const row of (d.trigs || [])){
      if(!row.ui || !row.dirty) continue;
      (row.added ? adds : edits).push({name:row.name, trigger:trgValue(row.ui)});
    }
    body.triggers = {adds, edits, removes:d.removed || []};
  }
  return body;
}

async function anSave(){
  const a = state.an, d = a.d;
  if(a.adding && !d.w.name.trim()){ toast('A new ancillary needs a name', 3500); return; }
  await anApply(anBody(a.adding ? 'add' : 'edit'),
                a.adding ? `create ${d.w.name}` : `save ${d.name}`);
}
async function anDelete(){
  await anApply(anBody('delete'), `delete ${state.an.d.name}`);
}

async function anApply(body, what){
  const a = state.an;
  if(a.busy) return;
  a.busy = true;
  let plan;
  try{ plan = await api.post('/api/ancillaries/plan', body); }
  finally{ a.busy = false; }
  if(plan.error){ toast('✗ ' + plan.error, 6000); return; }
  const p = plan.plan || {};
  const lines = (p.changes || []).slice(0, 14);
  const found = (p.findings || []).map(f => '⚠ ' + f.message);
  if(!confirm(`Write: ${what}?\n\n` + (lines.join('\n') || 'no visible change')
    + ((p.changes || []).length > 14 ? `\n…and ${p.changes.length - 14} more` : '')
    + (found.length ? '\n\n' + found.slice(0, 4).join('\n') : '')
    + '\n\nBacked up first, and 🕑 Log can undo it.')) return;
  a.busy = true;
  let res;
  try{ res = await api.post('/api/ancillaries/apply', body); }
  finally{ a.busy = false; }
  if(res.error){ toast('✗ ' + res.error, 6000); return; }
  toast('Saved. 🕑 Log can undo it.');
  const keep = body.action === 'delete' ? '' : body.ancillary;
  await loadAncillaries();
  if(keep) anOpen(keep);
}
