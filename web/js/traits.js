/* traits.js — Traits mode: export_descr_character_traits.txt, both halves of it

   Part of the Medieval 2 GUI Toolkit UI. These files are plain
   <script> tags sharing ONE global scope, loaded in the order set in
   index.html — there is no build step and no module system. Two rules
   follow from that: a top-level name must be unique across all of
   them, and a file's top-level side effects may not depend on a file
   loaded after it. */
/* ======================= TRAITS MODE =======================
   A trait is two things in two places. The top of the EDCT says what it IS — who
   can have it, which cultures cannot, and the ladder of levels with their
   effects. Hundreds of lines below, past `;== TRIGGER DATA ==`, the triggers say
   how anyone ever GETS it. Reading one without the other tells you nothing, so
   this screen shows them together: the levels above, and every trigger whose
   `Affects` names this trait below, in the shared builder from Phase 7.

   THE PAGE NEVER PARSES A GAME FILE. Everything here is /api/traits, /api/trait
   and /api/traits/plan|apply; the boxes are drawn from what the server read and
   a save posts back the same shape the server's own render_block takes.

   Three things the format imposes, all visible in this UI:

     * `Characters` accepts a comma list and the engine reads only the FIRST one,
       so this is a single picker with the bug spelled out, not a checklist that
       silently does nothing.
     * A level's five text fields are keys in data/text/export_VnVs.txt, and a
       character who reaches a level whose key is missing crashes the character
       screen. Missing keys are listed on the trait, and a save writes them.
     * Deleting a trait has to take its triggers with it — an `Affects` naming a
       trait that no longer exists is the "Trait not recognized" error. The
       confirmation says exactly which ones go. */

const TR_BLANK = {name:'', characters:['family'], hidden:false, exclude_cultures:[],
  no_going_back_level:'', anti_traits:[], levels:[]};

async function loadTraits(){
  const mod = state.src;
  main.innerHTML = '<div class="empty">Reading ' + esc(mod) + '’s traits…</div>';
  let r;
  try{ r = await api.get('/api/traits?mod=' + enc(mod)); }
  catch(e){ if(stale('traits', mod)) return;
    main.innerHTML = `<div class="empty">Couldn't read the traits file.<br>
      <span class="count">${esc(''+e)}</span><br><br>
      <button class="primary" onclick="loadTraits()">Retry</button></div>`; return; }
  if(stale('traits', mod)) return;
  state.tr = Object.assign({sel:'', d:null, busy:false, adding:false}, r);
  undoReset();
  renderTraits();
}

function renderTraits(){
  const t = state.tr;
  if(!t){ loadTraits(); return; }
  const strip = minorTabsHtml('', 'data/export_descr_character_traits.txt');
  if(t.error || !t.exists){
    main.innerHTML = strip + `<div class="empty">${esc(t.error || 'No traits file.')}<br>
      <span class="count">Traits live in data/export_descr_character_traits.txt</span></div>`;
    return;
  }
  const rows = trRows();
  count.textContent = `${rows.length}/${t.count}`;
  main.innerHTML = strip + `<div class="trwrap">
    <div class="trlist">
      <button class="trnew" onclick="trNew()">＋ New trait</button>
      ${findingsHtml('traits', t.finding_list, 'trOpen')}
      <div class="trrows">${rows.map(trRowHtml).join('')
        || '<div class="count" style="padding:8px">No trait matches.</div>'}</div>
    </div>
    <div class="trmain" id="trMain">${trDetailHtml()}</div>
  </div>`;
}

// The list is filtered in the page, not on the server: 800 rows is a list, and
// the whole file was parsed once to build it anyway (unlike names.txt's 20 757,
// which is why Strings pages server-side and this does not).
function trRows(){
  const q = search.value.trim().toLowerCase();
  const rows = state.tr.traits || [];
  if(!q) return rows;
  return rows.filter(r => r.name.toLowerCase().includes(q)
    || (r.label||'').toLowerCase().includes(q));
}

function trRowHtml(r){
  const on = state.tr.sel === r.name;
  return `<button class="trrow${on?' on':''}" onclick="trOpen('${q1(esc(r.name))}')">
    <div class="nm">${esc(r.label)}</div>
    <div class="sub">${r.levels} level${r.levels===1?'':'s'}${
      r.hidden?' · hidden':''}${
      r.triggers?` · ${r.triggers} trigger${r.triggers===1?'':'s'}`:' · <b>no trigger gives it</b>'}${
      r.findings?` <span class="w-warn">· ${r.findings}⚠</span>`:''}</div>
  </button>`;
}

async function trOpen(name){
  activity('opened trait', `${name} in ${state.src}`);
  const t = state.tr;
  t.sel = name; t.adding = false; t.d = null;
  renderTraits();
  let d;
  try{ d = await api.get(`/api/trait?mod=${enc(t.mod)}&name=${enc(name)}`); }
  catch(e){ d = {error:''+e}; }
  if(state.mode !== 'traits' || state.tr !== t || t.sel !== name) return;
  t.d = d.error ? d : trWorking(d);
  undoReset();          // the working copy exists now: this is Ctrl+Z's baseline
  trPaint();
  // the pane is remembered across records and modules; fetched after the first
  // paint so it never delays the form
  if(!d.error && state.settings.code_view) trCvToggle();
}

/* The working copy the boxes are bound to. Kept beside the payload the server
   sent so a save can post the whole form and the server can write only the lines
   that actually differ — which is what keeps a save from reformatting 20 lines
   the user never touched. */
function trWorking(d){
  d.w = JSON.parse(JSON.stringify(d.trait));
  d.trigs = (d.triggers || []).map(t => ({name:t.name, ui:null, dirty:false, src:t}));
  d.dirty = false;
  return d;
}

function trNew(){
  const t = state.tr;
  t.sel = ''; t.adding = true;
  t.d = {name:'', label:'(new trait)', trait:JSON.parse(JSON.stringify(TR_BLANK)),
    w:Object.assign(JSON.parse(JSON.stringify(TR_BLANK)),
      {levels:[trBlankLevel('')]}),
    trigs:[], findings:[], loc:{}, missing_loc:[], triggers:[], dirty:true,
    known:(t.traits||[]).map(r=>r.name),
    attributes:t.attributes||[], character_types:t.character_types||[]};
  renderTraits();
}

const trBlankLevel = name => ({name:name||'', description:'', effects_description:'',
  gain_message:'', lose_message:'', epithet:'', threshold:'1', effects:[]});

function trPaint(){
  const el = document.getElementById('trMain');
  if(el) el.innerHTML = trDetailHtml();
  const d = state.tr.d;
  if(d && d.cv){ cvWire(d.cv); cvBindHover(d.cv, document.getElementById('trGui')); }
  trWireTriggers();
}

// The form only — never the pane, which has the caret in it.
function trPaintForm(){
  const d = state.tr.d, el = document.getElementById('trGui');
  if(!d || !el) return;
  el.innerHTML = trFindingsHtml(d) + trHeaderHtml(d.w, d) + trLevelsHtml(d.w, d);
  if(d.cv) cvBindHover(d.cv, el);
}

/* ---- the detail pane ---- */
function trDetailHtml(){
  const t = state.tr, d = t.d;
  if(!t.sel && !t.adding) return `<div class="empty">Pick a trait on the left.<br>
    <span class="count">${t.count} trait${t.count===1?'':'s'}, ${t.triggers} trigger${
      t.triggers===1?'':'s'} in ${esc(t.file)}</span></div>`;
  if(!d) return '<div class="empty">Reading the trait…</div>';
  if(d.error) return `<div class="empty"><span class="w-bad">✗ ${esc(d.error)}</span></div>`;
  const w = d.w;
  return `<div class="trbar">
      <div><b>${esc(t.adding ? 'New trait' : d.label)}</b>
        <span class="count">${w.levels.length} level${w.levels.length===1?'':'s'}</span></div>
      <span class="sp"></span>
      ${t.adding ? '' : `<button class="${d.cv?'on':''}" title="Show this trait exactly as
export_descr_character_traits.txt stores it, beside the form. Hover a box to light
up its line; edit either side and the other follows."
        onclick="trCvToggle()">&lt;/&gt; Code view</button>
      <button class="danger" onclick="trDelete()">Delete</button>`}
      <button class="primary" onclick="trSave()">${t.adding?'Create trait':'Save'}</button>
    </div>
    <div id="trGui">
      ${trFindingsHtml(d)}
      ${trHeaderHtml(w, d)}
      ${trLevelsHtml(w, d)}
    </div>
    ${trCvHtml()}
    ${trTriggersHtml(d)}`;
}

function trFindingsHtml(d){
  const out = [];
  if((d.findings||[]).length) out.push(...d.findings.map(f =>
    `<div class="trfind w-warn">line ${f.line}: ${esc(f.message)}</div>`));
  if((d.missing_loc||[]).length) out.push(`<div class="trfind w-warn">${
    d.missing_loc.length} text key(s) are not in export_VnVs.txt (${
    d.missing_loc.slice(0,4).map(esc).join(', ')}${d.missing_loc.length>4?'…':''}).
    a character who reaches that level crashes the character screen. Type the words
    beside the key below, or save and they are created with the key as
    placeholder text.</div>`);
  return out.join('');
}

function trHeaderHtml(w, d){
  const types = d.character_types || ['family'];
  return `<section class="trsec">
    <div class="trsechead">Header <span class="count">The order of these lines is
      what the engine reads, and this editor keeps it</span></div>
    <div class="trgrid">
      <label class="lbl" data-label="name">Name</label>
      <input data-label="name" value="${esc(w.name)}" ${state.tr.adding?'':'disabled'}
        placeholder="TraitName" oninput="trSet('name',this.value)">
      <label class="lbl" data-label="characters">Characters</label>
      <div data-label="characters">
        <select onchange="trSet('characters',[this.value])">${
          types.map(c=>`<option ${c===(w.characters[0]||'family')?'selected':''}>${
            esc(c)}</option>`).join('')}</select>
        ${w.characters.length>1?`<div class="trhint w-warn">This trait lists ${
          esc(w.characters.join(', '))}, and the engine reads only the first. Use
          <code>all</code> with a condition in the trigger instead</div>`:''}
      </div>
      <label class="lbl" data-label="hidden">Hidden</label>
      <div data-label="hidden"><label class="chk"><input type="checkbox" ${w.hidden?'checked':''}
        onchange="trSet('hidden',this.checked)"> not shown on the character screen</label></div>
      <label class="lbl" data-label="exclude_cultures">ExcludeCultures</label>
      <input data-label="exclude_cultures" value="${esc(w.exclude_cultures.join(', '))}"
        placeholder="none"
        oninput="trSet('exclude_cultures',this.value.split(',').map(s=>s.trim()).filter(Boolean))">
      <label class="lbl" data-label="no_going_back_level">NoGoingBackLevel</label>
      <input data-label="no_going_back_level" value="${esc(w.no_going_back_level)}"
        placeholder="none" style="width:90px"
        oninput="trSet('no_going_back_level',this.value.trim())">
      <label class="lbl" data-label="anti_traits">AntiTraits</label>
      <div data-label="anti_traits">
        <input value="${esc(w.anti_traits.join(', '))}" placeholder="none" list="trAnti"
          oninput="trSet('anti_traits',this.value.split(',').map(s=>s.trim()).filter(Boolean))">
        <datalist id="trAnti">${(d.known||[]).map(n=>`<option value="${esc(n)}">`).join('')}</datalist>
      </div>
    </div>
  </section>`;
}

function trLevelsHtml(w, d){
  return `<section class="trsec">
    <div class="trsechead">Levels
      <span class="count">A character climbs these as points accumulate. The game
        shows the highest one whose threshold is met (9 is the engine's limit)</span></div>
    ${w.levels.map((lv,i)=>trLevelHtml(lv,i,d)).join('')
      || '<div class="count" style="padding:6px">No levels, so this trait can never be seen.</div>'}
    ${w.levels.length<9?`<button class="trgadd" onclick="trAddLevel()">＋ Add level</button>`:''}
  </section>`;
}

/* A level is a key on the left and the words the player reads on the right.
   The key is in the EDCT, the words are in data/text/export_VnVs.txt, and a key
   with no entry crashes the character screen — so both are edited here, in one
   row, and one save writes both files. */
function trLevelHtml(lv, i, d){
  const key = `level#${i+1}`;
  const txt = (k, label, hint) => {
    const tag = lv[k] || '';
    return `<label class="lbl" data-label="${key}.${k}">${label}</label>
    <div class="trkey">
      <input data-label="${key}.${k}" value="${esc(tag)}"
        placeholder="${esc(hint||'none')}"
        oninput="trSetLevel(${i},'${k}',this.value.trim())">
      ${tag ? `<input class="trtext" value="${esc(trLocText(d, tag))}"
        placeholder="${trHasKey(d, tag)?'':'Not in export_VnVs.txt yet. Type the words.'}"
        title="What the player reads. Saved into data/text/export_VnVs.txt."
        oninput="trSetLoc('${q1(esc(tag))}',this.value)">` : ''}
    </div>`;
  };
  return `<div class="trlevel" data-card="${key}">
    <div class="trlevhead">
      <span class="n">${i+1}</span>
      <input class="trlevname" data-label="${key}.name" value="${esc(lv.name)}"
        placeholder="LevelName" oninput="trSetLevel(${i},'name',this.value.trim())">
      <input class="trtext" value="${esc(trLocText(d, lv.name))}"
        placeholder="${trHasKey(d, lv.name)?'':'the name on the character screen'}"
        title="The level's name as the player sees it."
        oninput="trSetLoc('${q1(esc(lv.name))}',this.value)">
      <span class="lbl" data-label="${key}.threshold">Threshold</span>
      <input class="trnum" data-label="${key}.threshold" value="${esc(lv.threshold)}"
        oninput="trSetLevel(${i},'threshold',this.value.trim())">
      <button class="trgdel" title="Remove this level"
        onclick="trDelLevel(${i})">✕</button>
    </div>
    <div class="trgrid">
      ${txt('description','Description', lv.name?lv.name+'_desc':'')}
      ${txt('effects_description','EffectsDescription', lv.name?lv.name+'_effects_desc':'')}
      ${txt('gain_message','GainMessage')}
      ${txt('lose_message','LoseMessage')}
      ${txt('epithet','Epithet')}
    </div>
    <div class="treffects">
      ${(lv.effects||[]).map((e,k)=>trEffectHtml(e,i,k,d)).join('')}
      <button class="trgadd" onclick="trAddEffect(${i})">＋ Add effect</button>
    </div>
  </div>`;
}

// An attribute the engine does not have is marked but never refused: M2TWEOP
// adds some, and the generated list is what the mods and the Docudemons sheet
// between them know about — not a spec.
function trEffectHtml(e, i, k, d){
  const attrs = d.attributes || [];
  const known = !e.attribute || attrs.includes(e.attribute)
    || /^Combat_V_(Faction|Religion)_./.test(e.attribute);
  return `<div class="treff" data-label="level#${i+1}.effect#${k+1}">
    <input class="trattr${known?'':' bad'}" value="${esc(e.attribute)}" list="trAttrs"
      placeholder="attribute"
      oninput="trSetEffect(${i},${k},'attribute',this.value.trim())">
    <input class="trnum" value="${esc(e.amount)}"
      oninput="trSetEffect(${i},${k},'amount',this.value.trim())">
    ${known?'':'<span class="count w-warn">not a character attribute</span>'}
    <button class="trgdel" onclick="trDelEffect(${i},${k})">✕</button>
    <datalist id="trAttrs">${attrs.map(a=>`<option value="${esc(a)}">`).join('')}</datalist>
  </div>`;
}

/* ---- the triggers that feed this trait ----
   The other half of what a trait is. Each one is the shared builder from Phase 7
   (web/js/triggerui.js), which is why that file has waited for this screen. */
function trTriggersHtml(d){
  if(state.tr.adding) return `<section class="trsec">
    <div class="trsechead">Triggers</div>
    <div class="count" style="padding:6px">Create the trait first, then add the
      triggers that give it. A trigger cannot name a trait the file has not
      defined yet.</div></section>`;
  return `<section class="trsec">
    <div class="trsechead">Triggers <span class="count">${d.trigs.length
      ? 'what gives this trait its points' : 'nothing gives this trait any points'}</span></div>
    ${d.trigs.map((t,i)=>`<div class="trtrig">
      <div class="trtrighead">
        <b>${esc(t.name)}</b>
        <span class="sp"></span>
        <button class="trgdel" title="Remove this trigger"
          onclick="trDelTrigger(${i})">✕</button>
      </div>
      <div id="trtrg-${i}"></div>
    </div>`).join('')}
    <button class="trgadd" onclick="trAddTrigger()">＋ Add trigger</button>
  </section>`;
}

// The builder is created after the markup exists, because it paints itself into
// a slot by id and loads its vocabulary asynchronously.
async function trWireTriggers(){
  const d = state.tr.d;
  if(!d || !d.trigs) return;
  for(let i = 0; i < d.trigs.length; i++){
    const slot = document.getElementById('trtrg-' + i);
    if(!slot) continue;
    const row = d.trigs[i];
    if(!row.ui){
      row.ui = trgCreate({mod:state.tr.mod, trigger:row.src,
        onChange:() => { row.dirty = true; trDirty(); }});
      await trgLoad(row.ui);
    }
    const here = document.getElementById('trtrg-' + i);
    if(here) here.innerHTML = trgHtml(row.ui);
  }
}

/* ---- edits ----
   State first, paint second. A change that alters the SHAPE of the form
   repaints; typing in a box does not, or the caret jumps out from under the
   user on every keystroke. */
function trSet(key, value){
  const d = state.tr.d; if(!d) return;
  d.w[key] = value;
  trDirty(key === 'hidden' || key === 'characters');
}
function trSetLevel(i, key, value){
  const d = state.tr.d, lv = d && d.w.levels[i]; if(!lv) return;
  lv[key] = value;
  trDirty(false);
}
// What a key says on screen. `locEdits` is what has been retyped this session;
// `loc` is what the mod's text file says now.
const trHasKey = (d, tag) => tag && (d.loc||{})[tag] !== undefined;
function trLocText(d, tag){
  if(!tag) return '';
  const e = d.locEdits || {};
  return e[tag] !== undefined ? e[tag] : ((d.loc||{})[tag] || '');
}
function trSetLoc(tag, value){
  const d = state.tr.d; if(!d || !tag) return;
  (d.locEdits = d.locEdits || {})[tag] = value;
  trDirty(false);
}
function trSetEffect(i, k, key, value){
  const d = state.tr.d, lv = d && d.w.levels[i]; if(!lv || !lv.effects[k]) return;
  lv.effects[k][key] = value;
  trDirty(false);
}
function trAddLevel(){
  const d = state.tr.d; if(!d) return;
  const n = d.w.levels.length;
  const last = d.w.levels[n-1];
  const name = (d.w.name || 'Level') + (n + 1);
  d.w.levels.push(Object.assign(trBlankLevel(name),
    {threshold:String((+(last && last.threshold) || 0) + 1)}));
  trDirty(true);
}
function trDelLevel(i){
  const d = state.tr.d; if(!d) return;
  d.w.levels.splice(i, 1);
  trDirty(true);
}
function trAddEffect(i){
  const lv = state.tr.d.w.levels[i]; if(!lv) return;
  (lv.effects = lv.effects || []).push({attribute:'', amount:'1'});
  trDirty(true);
}
function trDelEffect(i, k){
  state.tr.d.w.levels[i].effects.splice(k, 1);
  trDirty(true);
}
function trAddTrigger(){
  const d = state.tr.d; if(!d) return;
  const n = (d.name || 'trait').toLowerCase() + '_' + (d.trigs.length + 1);
  d.trigs.push({name:n, ui:null, dirty:true, added:true,
    src:{name:n, when_to_test:'CharacterTurnEnd', conditions:[],
         effects:[{keyword:'Affects', args:[d.name, '1', 'Chance', '100']}]}});
  trDirty(true);
}
function trDelTrigger(i){
  const d = state.tr.d;
  const row = d.trigs[i];
  if(!row.added && !confirm(`Remove trigger ${row.name}?\n\n`
    + `It is written out of the file when you save.`)) return;
  if(row.ui) trgDrop(row.ui);
  d.trigs.splice(i, 1);
  d.removed = (d.removed || []).concat(row.added ? [] : [row.name]);
  trDirty(true);
}
function trDirty(repaint){
  const d = state.tr.d;
  d.dirty = true;
  if(repaint) trPaint();
  // the GUI→pane half of the Code View contract: change a box and the text pane
  // is re-serialised by the server, through the serialiser the save itself uses
  if(d.cv) cvFromGui(d.cv);
}

/* ---- one trait as the file writes it ----
   The same inline pane the unit and building editors use, remembered across
   records and modules by the one `code_view` setting. Text typed in the pane
   wins over the boxes when a save goes out (`raw_block`), because reordering,
   indenting and comments are edits no field map can express. */
function trCvHtml(){
  const d = state.tr.d;
  return d && d.cv ? `<div id="trCodeCol" style="padding-top:12px">${cvHtml(d.cv)}</div>` : '';
}

async function trCvToggle(){
  const d = state.tr.d; if(!d) return;
  if(d.cv){ cvDrop(d.cv); d.cv = null; state.settings.code_view = false;
    api.post('/api/settings', {code_view:false}); trPaint(); return; }
  state.settings.code_view = true; api.post('/api/settings', {code_view:true});
  d.cv = cvCreate(trCvHost());
  trPaint();
  await cvLoad(d.cv);
  if(state.tr.d !== d || !d.cv) return;
  trPaint();
}

function trCvHost(){
  return {kind:'traits', mod:state.tr.mod, id:state.tr.d.name,
    where:'data/' + state.tr.file,
    edits:() => trEdits(),
    // The pane's own text becomes the truth once it has been typed into: it can
    // say things the boxes cannot (a comment, a reordered level), so the form
    // follows it and the save carries it verbatim.
    adopt:cv => { const d = state.tr.d;
      if(!cv.detail) return;
      d.w = cv.detail;
      // `base`, never `text`: with comment hiding on, `text` is the view with the
      // comment-only lines cut out of it, and saving that would delete every one
      // of them. `base` is the record's real bytes.
      d.raw = cv.edited ? cv.base : ''; },
    refreshGui:() => { trPaintForm(); }};
}

/* ---- writing ---- */
function trEdits(){
  const w = state.tr.d.w;
  return {name:w.name, characters:w.characters, hidden:w.hidden,
    exclude_cultures:w.exclude_cultures, no_going_back_level:w.no_going_back_level,
    anti_traits:w.anti_traits,
    levels:w.levels.map(lv => ({name:lv.name, description:lv.description,
      effects_description:lv.effects_description, gain_message:lv.gain_message,
      lose_message:lv.lose_message, epithet:lv.epithet, threshold:lv.threshold,
      effects:(lv.effects||[]).filter(e => e.attribute && e.amount)}))};
}

function trBody(action){
  const t = state.tr, d = t.d;
  const body = {mod:t.mod, trait:action === 'add' ? d.w.name : d.name, action};
  if(action !== 'delete'){
    body.edits = trEdits();
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

async function trSave(){
  const t = state.tr, d = t.d;
  if(t.adding && !d.w.name.trim()){ toast('A new trait needs a name', 3500); return; }
  await trApply(trBody(t.adding ? 'add' : 'edit'),
                t.adding ? `create ${d.w.name}` : `save ${d.name}`);
}

async function trDelete(){
  const d = state.tr.d;
  await trApply(trBody('delete'), `delete ${d.name}`);
}

async function trApply(body, what){
  const t = state.tr;
  if(t.busy) return;
  t.busy = true;
  let plan;
  try{ plan = await api.post('/api/traits/plan', body); }
  finally{ t.busy = false; }
  if(plan.error){ toast('✗ ' + plan.error, 6000); return; }
  const p = plan.plan || {};
  const lines = (p.changes || []).slice(0, 14);
  const found = (p.findings || []).map(f => '⚠ ' + f.message);
  if(!confirm(`Write: ${what}?\n\n` + (lines.join('\n') || 'no visible change')
    + ((p.changes || []).length > 14 ? `\n…and ${p.changes.length - 14} more` : '')
    + (found.length ? '\n\n' + found.slice(0, 4).join('\n') : '')
    + `\n\nBacked up first, and 🕑 Log can undo it.`)) return;
  t.busy = true;
  let res;
  try{ res = await api.post('/api/traits/apply', body); }
  finally{ t.busy = false; }
  if(res.error){ toast('✗ ' + res.error, 6000); return; }
  toast('Saved. 🕑 Log can undo it.');
  const keep = body.action === 'delete' ? '' : body.trait;
  await loadTraits();
  if(keep) trOpen(keep);
}
