/* minorfiles.js — Minor Files mode: the five small campaign files, one screen

   Part of the Medieval 2 GUI Toolkit UI. These files are plain
   <script> tags sharing ONE global scope, loaded in the order set in
   index.html — there is no build step and no module system. Two rules
   follow from that: a top-level name must be unique across all of
   them, and a file's top-level side effects may not depend on a file
   loaded after it. */
/* ======================= MINOR FILES MODE =======================
   Five files nobody would open a module for on their own, and one module
   because they are all read the same afternoon: a mod's rebels, its religions,
   what its provinces trade, what its settlements look like and what its people
   are called.

   They are three shapes, not five (see unittransfer/minorfiles.py), and that is
   what lets one list, one pane and one save serve all five tabs. What differs
   per tab is the form — and two tabs are deliberately edit-only:

     * RESOURCES — the engine's list of 28 is closed. A `type` it does not know
       is read and then ignored, so "create a resource" would be a button that
       writes a line nothing reads.
     * CULTURES — a culture is eleven settlement models and cards, a fort, a
       port ladder, a watchtower and six agents. Nothing a text editor creates.

   And one tab writes four files at once: adding a religion writes its block,
   joins it to the `religions { … }` list, appends it to
   descr_religions_lookup.txt and creates its name in text/religions.txt. A
   religion that reaches three of the four half exists, so they are one job with
   one backup set and one undo.

   THE PAGE NEVER PARSES A GAME FILE: /api/minor, /api/minor/record and
   /api/minor/plan|apply do all of it, and a save posts back the shape the
   server's own render_any takes. */

async function loadMinor(){
  const mod = state.src;
  const tab = minorWantTab || (state.mf && state.mf.tab) || 'rebels';
  minorWantTab = null;
  main.innerHTML = '<div class="empty">Reading ' + esc(mod) + '’s campaign files…</div>';
  let r;
  try{ r = await api.get(`/api/minor?mod=${enc(mod)}&tab=${enc(tab)}`); }
  catch(e){ if(stale('minor', mod)) return;
    main.innerHTML = `<div class="empty">Couldn't read the campaign files.<br>
      <span class="count">${esc(''+e)}</span><br><br>
      <button class="primary" onclick="loadMinor()">Retry</button></div>`; return; }
  if(stale('minor', mod)) return;
  state.mf = Object.assign({tab, sel:'', d:null, busy:false, adding:false}, r);
  undoReset();
  renderMinor();
}

function mfTab(id){
  const f = state.mf;
  if(!f || f.tab === id) return;
  f.tab = id; f.sel = ''; f.d = null; f.adding = false;
  loadMinor();
}

function renderMinor(){
  const f = state.mf;
  if(!f){ loadMinor(); return; }
  const rows = mfRows();
  count.textContent = f.exists ? `${rows.length}/${f.count}` : '—';
  main.innerHTML = mfTabsHtml() + (f.exists ? `<div class="trwrap">
    <div class="trlist">
      ${f.actions.includes('add')
        ? `<button class="trnew" onclick="mfNew()">＋ New ${esc(f.noun)}</button>` : ''}
      ${findingsHtml('minor:'+f.tab, f.finding_list, 'mfOpen')}
      <div class="trrows">${rows.map(mfRowHtml).join('')
        || `<div class="count" style="padding:8px">No ${esc(f.noun)} matches.</div>`}</div>
    </div>
    <div class="trmain" id="mfMain">${mfDetailHtml()}</div>
  </div>` : `<div class="empty">${esc(f.error || 'This mod has not got that file.')}<br>
      <span class="count">It would live in data/${esc(f.file)}</span></div>`);
}

const mfTabsHtml = () => minorTabsHtml(state.mf.tab, 'data/' + state.mf.file);

// Filtered in the page. The biggest list here is 28 factions of names or 68
// rebel factions — the file was parsed once to build it, and there is nothing
// left to page.
function mfRows(){
  const q = search.value.trim().toLowerCase();
  const rows = state.mf.records || [];
  if(!q) return rows;
  return rows.filter(r => r.name.toLowerCase().includes(q)
    || (r.label||'').toLowerCase().includes(q));
}

function mfRowHtml(r){
  const f = state.mf, on = f.sel === r.name;
  let sub = '';
  if(f.tab === 'rebels') sub = `${esc(r.category||'no category')} · chance ${
    esc(r.chance||'0')} · ${r.units} unit${r.units===1?'':'s'}`;
  else if(f.tab === 'resources') sub = `trade ${esc(r.trade_value||'0')}${
    r.has_mine?' · has a mine':''}${r.known?'':' · <b>not an engine resource</b>'}`;
  else if(f.tab === 'religions') sub = r.listed
    ? esc(r.pip_path||'no pip') : '<b>not in the religions list</b>';
  else if(f.tab === 'cultures') sub = `${r.levels} settlement level${
    r.levels===1?'':'s'} · ${r.agents}/6 agents`;
  else sub = Object.entries(r.sections||{}).map(([k,n]) => `${n} ${k}`).join(' · ')
    || '<b>no names at all</b>';
  return `<button class="trrow${on?' on':''}" onclick="mfOpen('${q1(esc(r.name))}')">
    <span class="nm">${esc(r.label)}</span><br>
    <span class="sub">${sub}${r.findings?` <span class="w-warn">· ${r.findings}⚠</span>`:''}</span>
  </button>`;
}

async function mfOpen(name){
  activity('opened record', `${name} (${state.mf.tab}) in ${state.src}`);
  const f = state.mf;
  f.sel = name; f.adding = false; f.d = null;
  renderMinor();
  let d;
  try{ d = await api.get(
    `/api/minor/record?mod=${enc(f.mod)}&tab=${enc(f.tab)}&name=${enc(name)}`); }
  catch(e){ d = {error:''+e}; }
  if(state.mode !== 'minor' || state.mf !== f || f.sel !== name) return;
  f.d = d.error ? d : mfWorking(d);
  undoReset();          // the working copy exists now: this is Ctrl+Z's baseline
  mfPaint();
  if(!d.error && state.settings.code_view) mfCvToggle();
}

function mfWorking(d){
  d.w = JSON.parse(JSON.stringify(d.record));
  d.locEdits = {};
  return d;
}

// A blank record per tab, in the shape that tab's `edits` takes — the same shape
// the server's own new_any() writes from, so a create and a save agree.
function mfBlank(tab){
  if(tab === 'rebels') return {name:'', category:'brigands', chance:'50',
    description:'', units:[]};
  if(tab === 'religions') return {name:'', pip_path:''};
  if(tab === 'names') return {name:'', sections:[{name:'characters', entries:[]}]};
  return {name:''};
}

function mfNew(){
  const f = state.mf;
  f.sel = ''; f.adding = true;
  const blank = mfBlank(f.tab);
  f.d = {name:'', label:`(new ${f.noun})`, tab:f.tab, file:f.file, noun:f.noun,
    record:blank, w:JSON.parse(JSON.stringify(blank)), findings:[], loc:{},
    locEdits:{}, missing_loc:[], loc_tag:'', loc_writable:true,
    known:(f.records||[]).map(r=>r.name), actions:f.actions,
    vocab:(f.d && f.d.vocab) || {}};
  renderMinor();
  mfLoadVocab();
}

// The pickers (this mod's unit list, its settlement levels) come with a record,
// and a brand-new one has no record to come with — so fetch them off any
// existing row rather than shipping a second endpoint for the same answer.
async function mfLoadVocab(){
  const f = state.mf;
  if(!f.adding || !f.records || !f.records.length) return;
  if(f.d.vocab && Object.keys(f.d.vocab).length) return;
  let d;
  try{ d = await api.get(`/api/minor/record?mod=${enc(f.mod)}&tab=${enc(f.tab)}`
    + `&name=${enc(f.records[0].name)}`); }
  catch(e){ return; }
  if(state.mode !== 'minor' || state.mf !== f || !f.adding) return;
  f.d.vocab = d.vocab || {};
  mfPaintForm();
}

function mfPaint(){
  const el = document.getElementById('mfMain');
  if(el) el.innerHTML = mfDetailHtml();
  const d = state.mf.d;
  if(d && d.cv){ cvWire(d.cv); cvBindHover(d.cv, document.getElementById('mfGui')); }
}

// The form only — never the pane, which has the caret in it.
function mfPaintForm(){
  const d = state.mf.d, el = document.getElementById('mfGui');
  if(!d || !el) return;
  el.innerHTML = mfFindingsHtml(d) + mfFormHtml(d);
  if(d.cv) cvBindHover(d.cv, el);
}

/* ---- the detail pane ---- */
function mfDetailHtml(){
  const f = state.mf, d = f.d;
  if(!f.sel && !f.adding) return `<div class="empty">Pick a ${esc(f.noun)} on the left.<br>
    <span class="count">${f.count} ${esc(f.noun)}${f.count===1?'':'s'} in data/${
      esc(f.file)}</span>${f.refused ? `<div class="trnote"
      style="max-width:560px;margin:14px auto;text-align:left">${esc(f.refused)}</div>`
      : ''}</div>`;
  if(!d) return `<div class="empty">Reading the ${esc(f.noun)}…</div>`;
  if(d.error) return `<div class="empty"><span class="w-bad">✗ ${esc(d.error)}</span></div>`;
  return `<div class="trbar">
      <div><b>${esc(f.adding ? 'New ' + f.noun : d.label)}</b>
        <span class="count">${esc(f.file)}</span></div>
      <span class="sp"></span>
      ${f.adding ? '' : `<button class="${d.cv?'on':''}" title="Show this ${esc(f.noun)}
exactly as ${esc(f.file)} stores it, beside the form."
        onclick="mfCvToggle()">&lt;/&gt; Code view</button>
      ${(d.actions||[]).includes('delete')
        ? '<button class="danger" onclick="mfDelete()">Delete</button>' : ''}`}
      <button class="primary" onclick="mfSave()">${f.adding?'Create':'Save'}</button>
    </div>
    <div id="mfGui">
      ${mfFindingsHtml(d)}
      ${mfFormHtml(d)}
    </div>
    ${d.cv ? `<div id="mfCodeCol" style="padding-top:12px">${cvHtml(d.cv)}</div>` : ''}`;
}

function mfFindingsHtml(d){
  const out = (d.findings||[]).map(f =>
    `<div class="trfind w-warn">line ${f.line}: ${esc(f.message)}</div>`);
  if((d.missing_loc||[]).length && d.loc_writable) out.push(`<div class="trfind w-warn">
    There is no <code>{${esc(d.loc_tag)}}</code> entry in ${esc(d.loc_file)} — this
    ${esc(d.noun)} shows its code name in game. Type the words beside the name below,
    or save and the key is created with the code name as placeholder text.</div>`);
  return out.join('');
}

/* ---- the forms, one per tab ---- */
function mfFormHtml(d){
  const f = state.mf;
  if(f.tab === 'rebels') return mfRebelForm(d);
  if(f.tab === 'resources') return mfResourceForm(d);
  if(f.tab === 'religions') return mfReligionForm(d);
  if(f.tab === 'cultures') return mfCultureForm(d);
  return mfNamesForm(d);
}

// The name box and, beside it, what the player actually reads. Same widget the
// traits and ancillaries editors use — except on the resources tab, where the
// text file behind it is read by position and only the Strings module can write
// it safely.
/* ---- the art these files point at ----
   A religion's pip, a resource's icon and a culture's settlement cards are all
   `.tga` paths under the mod's data/, and until now the editor showed them as
   text while the Buildings gallery showed its own art as pictures. Same server
   route as a faction symbol (`kind=modfile`), which is what keeps the path
   inside data/ — the page never gets to name an absolute file.

   A blank slot is NOT reported as a fault, and that is Phase 10a's ruling, not
   an oversight: every pip and settlement card in these files can legitimately
   live inside the game's own .pack archives, which the toolkit cannot read.
   Checking anyway produced 78 findings across three mods and 77 were noise. */
function mfArt(rel){
  // The two files disagree about the prefix and both are right: a resource icon
  // and a settlement card are written `data/ui/…` while a religion's pip is
  // written `ui/pips/…`. The server resolves everything under the mod's data/,
  // so the redundant half is dropped here rather than in one of the parsers —
  // neither file is wrong about its own format.
  const r=(rel||'').trim().replace(/\\/g,'/').replace(/^data\//i,'');
  if(!r)return '<span class="mfnoart" title="No path set">—</span>';
  return `<img class="mfpip" loading="lazy" src="/icon?mod=${enc(state.mf.mod)}&kind=modfile&rel=${enc(r)}"
    alt="" title="${esc(r)} — blank here means the file is not unpacked in this mod, which is normal: it may be inside a .pack archive"
    onerror="this.classList.add('gone')">`;
}
function mfNameRow(d, placeholder){
  const w = d.w, tag = d.loc_tag || '';
  const shown = tag ? (d.locEdits[tag] !== undefined ? d.locEdits[tag]
                       : ((d.loc||{})[tag] || '')) : '';
  return `<label class="lbl" data-label="name">Name</label>
    <div class="${tag?'trkey':''}">
      <input data-label="name" value="${esc(w.name)}"
        ${state.mf.adding?'':'disabled'} placeholder="${esc(placeholder||'')}"
        oninput="mfSet('name',this.value.trim())">
      ${tag ? `<input class="trtext" value="${esc(shown)}"
        ${d.loc_writable?'':'disabled'}
        placeholder="${esc(d.loc_writable
          ? (((d.loc||{})[tag] === undefined) ? 'not in ' + d.loc_file + ' yet'
             : 'what the player reads')
          : (shown || 'read by position — edit it in the Strings module'))}"
        title="${esc(d.loc_writable ? 'What the player reads. Saved into data/'
          + d.loc_file + '.' : d.loc_note || '')}"
        oninput="mfSetLoc('${q1(esc(tag))}',this.value)">` : ''}
    </div>
    ${tag && !d.loc_writable ? `<span></span><div class="trhint count">${
      esc(d.loc_note||'')}</div>` : ''}`;
}

function mfRebelForm(d){
  const w = d.w, v = d.vocab || {};
  return `<section class="trsec">
    <div class="trsechead">The rebel faction
      <span class="count">what spawns in a region whose descr_regions line names it</span></div>
    <div class="trgrid">
      ${mfNameRow(d, 'Evil_Rebels')}
      <label class="lbl" data-label="category">Category</label>
      <div>
        <select data-label="category" onchange="mfSet('category',this.value)">
          ${(v.categories||[]).map(c =>
            `<option value="${esc(c)}"${c===w.category?' selected':''}>${esc(c)}</option>`).join('')}
          ${(v.categories||[]).includes(w.category) ? ''
            : `<option value="${esc(w.category)}" selected>${esc(w.category)} (unknown)</option>`}
        </select>
        <div class="trhint count">the four the engine knows — anything else is
          read and ignored</div>
      </div>
      <label class="lbl" data-label="chance">Chance</label>
      <input data-label="chance" value="${esc(w.chance)}"
        oninput="mfSet('chance',this.value.trim())">
      <label class="lbl" data-label="description">Description key</label>
      <input data-label="description" value="${esc(w.description)}"
        placeholder="${esc(w.name||'')}"
        oninput="mfSet('description',this.value.trim())">
    </div>
    <div class="treffects">
      <div class="trsechead" style="margin:8px 0 0">Units
        <span class="count">${(w.units||[]).length} — a rebel faction with none
          cannot spawn. The whole rest of the line is the unit type, spaces and
          all.</span></div>
      ${(w.units||[]).map((u,k)=>`<div class="treff" data-label="unit#${k+1}">
        <input class="trattr" value="${esc(u)}" list="mfUnits"
          placeholder="unit type" oninput="mfSetUnit(${k},this.value)">
        <span class="count">${esc(mfUnitLabel(d, u))}</span>
        <button class="trgdel" onclick="mfDelUnit(${k})">✕</button>
      </div>`).join('')}
      <datalist id="mfUnits">${(v.units||[]).map(u =>
        `<option value="${esc(u.type)}">${esc(u.label)}</option>`).join('')}</datalist>
      <button class="trgadd" onclick="mfAddUnit()">＋ Add unit</button>
    </div>
  </section>`;
}

// The picker offers this mod's units under their in-game names; the line itself
// holds the EDU type, so the name is shown beside the box rather than in it.
function mfUnitLabel(d, type){
  if(!type) return '';
  const hit = ((d.vocab||{}).units||[]).find(u => u.type === type);
  return hit ? hit.label : '✗ not a unit in this mod';
}

function mfResourceForm(d){
  const w = d.w;
  return `<section class="trsec">
    <div class="trsechead">The resource
      <span class="count">placed on the campaign map by descr_regions.txt</span></div>
    <div class="trgrid">
      ${mfNameRow(d, 'timber')}
      <label class="lbl" data-label="trade_value">Trade value</label>
      <input data-label="trade_value" value="${esc(w.trade_value)}"
        oninput="mfSet('trade_value',this.value.trim())">
      <label class="lbl" data-label="item">Model (item)</label>
      <input data-label="item" value="${esc(w.item)}"
        placeholder="data/models_strat/resource_x.CAS"
        oninput="mfSet('item',this.value.trim())">
      <label class="lbl" data-label="icon">Icon</label>
      <div class="mfart">
        ${mfArt(w.icon)}
        <input data-label="icon" value="${esc(w.icon)}"
          placeholder="data/ui/resources/resource_x.tga"
          oninput="mfSet('icon',this.value.trim())">
      </div>
      <label class="lbl" data-label="has_mine">Has a mine</label>
      <div data-label="has_mine"><label class="chk"><input type="checkbox"
        ${w.has_mine?'checked':''} onchange="mfSet('has_mine',this.checked)">
        shows the mine model named at the top of this file</label></div>
    </div>
  </section>`;
}

function mfReligionForm(d){
  const w = d.w;
  return `<section class="trsec">
    <div class="trsechead">The religion
      <span class="count">a religion is written down three times — this file's
        list, this block, and descr_religions_lookup.txt. A save keeps all
        three in step.</span></div>
    <div class="trgrid">
      ${mfNameRow(d, 'catholic')}
      <label class="lbl" data-label="pip_path">Pip</label>
      <div>
        <div class="mfart">
          ${mfArt(w.pip_path)}
          <input data-label="pip_path" value="${esc(w.pip_path)}"
            placeholder="ui/pips/pip_catholic.tga"
            oninput="mfSet('pip_path',this.value.trim())">
        </div>
        <div class="trhint count">what the campaign map draws for it — the one
          line a religion block has</div>
      </div>
    </div>
    ${d.listed === false ? `<div class="trfind w-bad">This religion has a block but
      is not in the <code>religions { … }</code> list, and the engine reads the
      list — so as far as the game is concerned it does not exist.</div>` : ''}
  </section>`;
}

function mfCultureForm(d){
  const w = d.w, v = d.vocab || {};
  const box = (k, label) => w[k] === undefined || w[k] === '' ? '' :
    `<label class="lbl" data-label="${k}">${esc(label||k)}</label>
     <input data-label="${k}" value="${esc(w[k])}" oninput="mfSet('${k}',this.value.trim())">`;
  return `<section class="trsec">
    <div class="trsechead">The culture
      <span class="count">the record does not end at its closing brace — the fort,
        the ports, the watchtower and the six agents below belong to it too</span></div>
    <div class="trgrid">
      ${mfNameRow(d, 'southern_european')}
      ${(v.head||[]).map(k => box(k)).join('')}
      ${(v.tail||[]).map(k => box(k)).join('')}
    </div>
  </section>
  <section class="trsec">
    <div class="trsechead">Settlement ladder
      <span class="count">${(w.levels||[]).length} level(s) — each one a strat
        model, the settlement plan that goes with it, and the card</span></div>
    ${(w.levels||[]).map((l,k) => `<div class="mflvl" data-label="level.${esc(l.name)}">
      <div class="mflvlname">${esc(l.name)}</div>
      ${mfArt(l.card)}
      <div class="trgrid" style="flex:1">
        <label class="lbl" data-label="level.${esc(l.name)}.normal">Model</label>
        <input value="${esc(l.model)}" oninput="mfSetLevel(${k},'model',this.value.trim())">
        <label class="lbl">Settlement plan</label>
        <input value="${esc(l.plan)}" oninput="mfSetLevel(${k},'plan',this.value.trim())">
        <label class="lbl" data-label="level.${esc(l.name)}.card">Card</label>
        <input value="${esc(l.card)}" oninput="mfSetLevel(${k},'card',this.value.trim())">
      </div>
    </div>`).join('')}
    ${mfMissingLevels(w, v)}
  </section>
  <section class="trsec">
    <div class="trsechead">Agents
      <span class="count">card, info card, pip and cost. The two numbers after
        them are the same <code>1 1</code> in all 234 real agent lines, so they
        are carried by position and never rewritten.</span></div>
    ${Object.entries(w.agents||{}).map(([a,g]) => `<div class="treff" data-label="agent.${esc(a)}">
      <span class="mfag">${esc(a)}</span>
      ${mfArt(g.tokens[0])}
      ${[['card',0],['info_card',1],['pip',2],['cost',3]].map(([nm,i]) =>
        `<input class="${nm==='cost'?'trnum':''}" value="${esc(g.tokens[i]||'')}"
          title="${esc(nm)}" placeholder="${esc(nm)}"
          oninput="mfSetAgent('${q1(esc(a))}',${i},this.value.trim())">`).join('')}
    </div>`).join('')}
    ${(v.agents||[]).filter(a => !(w.agents||{})[a]).length
      ? `<div class="trfind w-warn">No ${(v.agents||[]).filter(a =>
          !(w.agents||{})[a]).map(esc).join(', ')} line — this culture cannot
          recruit one. Adding an agent line means saying where it goes, which
          this file's own order decides, so it is written in the code view.</div>`
      : ''}
    ${(w.ports||[]).length ? `<div class="trhint count" style="margin-top:8px">Ports:
      ${(w.ports||[]).map(p => esc(p.key)).join(', ')} — edited in the code view,
      because a port ladder is a pair of lines per level rather than a field.</div>` : ''}
  </section>`;
}

function mfMissingLevels(w, v){
  const have = new Set((w.levels||[]).map(l => l.name));
  const gone = (v.levels||[]).filter(l => !have.has(l));
  if(!gone.length) return '';
  return `<div class="trhint count" style="margin-top:8px">Not defined here:
    ${gone.map(esc).join(', ')}. That is only a fault when the OTHER cultures in
    this file define it — a mod that drops a level everywhere has removed it.</div>`;
}

// 800 names is a textarea, not 800 boxes. One name per line, which is exactly
// how the file itself holds them.
function mfNamesForm(d){
  const w = d.w, v = d.vocab || {};
  const has = new Set((w.sections||[]).map(s => s.name));
  return `<section class="trsec">
    <div class="trsechead">The faction's names
      <span class="count">one name per line, and a name is one word — the engine
        picks from these when it generates a family</span></div>
    <div class="trgrid">${mfNameRow(d, 'england')}</div>
    ${(w.sections||[]).map((s,k) => `<div style="margin-top:10px" data-label="${esc(s.name)}">
      <div class="trsechead" style="margin:0 0 4px">${esc(s.name)}
        <span class="count">${s.entries.length} name(s)</span></div>
      <textarea class="mfnames" rows="12"
        oninput="mfSetSection(${k},this.value)">${esc(s.entries.join('\n'))}</textarea>
    </div>`).join('')}
    ${(v.sections||[]).filter(s => !has.has(s)).length
      ? `<div class="trhint count" style="margin-top:8px">No ${
          (v.sections||[]).filter(s => !has.has(s)).map(esc).join(', ')} section.
          Adding one is a heading and its names together, so it is written in the
          code view.</div>` : ''}
  </section>`;
}

/* ---- edits ----
   Every one of these ends at `mfTouched`, which is the GUI→pane half of the
   Code View contract: change a box and the text pane is re-serialised by the
   server, through the same serialiser the save will use. */
function mfTouched(repaint){
  const d = state.mf.d; if(!d) return;
  if(repaint) mfPaintForm();
  if(d.cv) cvFromGui(d.cv);
}
function mfSet(key, value){
  const d = state.mf.d; if(!d) return;
  d.w[key] = value;
  // these change the shape of the form rather than one box's contents
  mfTouched(['name','has_mine'].includes(key));
}
function mfSetLoc(tag, value){
  const d = state.mf.d; if(!d || !tag) return;
  (d.locEdits = d.locEdits || {})[tag] = value;
}
function mfSetUnit(k, value){
  const d = state.mf.d; if(!d) return;
  d.w.units[k] = value.trim();
  mfTouched(true);
}
function mfAddUnit(){
  const w = state.mf.d.w;
  (w.units = w.units || []).push('');
  mfTouched(true);
}
function mfDelUnit(k){
  state.mf.d.w.units.splice(k, 1);
  mfTouched(true);
}
function mfSetLevel(k, key, value){
  const l = state.mf.d.w.levels[k]; if(!l) return;
  l[key] = value;
  mfTouched(false);
}
function mfSetAgent(name, i, value){
  const g = (state.mf.d.w.agents||{})[name]; if(!g) return;
  g.tokens[i] = value;
  mfTouched(false);
}
function mfSetSection(k, text){
  const s = state.mf.d.w.sections[k]; if(!s) return;
  s.entries = text.split('\n').map(v => v.trim()).filter(Boolean);
  mfTouched(false);
}

/* ---- the code view ---- */
async function mfCvToggle(){
  const f = state.mf, d = f.d; if(!d) return;
  if(d.cv){ cvDrop(d.cv); d.cv = null; state.settings.code_view = false;
    api.post('/api/settings', {code_view:false}); mfPaint(); return; }
  state.settings.code_view = true; api.post('/api/settings', {code_view:true});
  d.cv = cvCreate({kind:f.tab, mod:f.mod, id:d.name, where:'data/' + f.file,
    edits:() => mfEdits(),
    adopt:cv => { const s = state.mf.d;
      if(!cv.detail) return;
      s.w = cv.detail;
      // `base`, never `text`: with comment hiding on, `text` is the view with the
      // comment-only lines cut out of it, and saving that would delete every one
      // of them. `base` is the record's real bytes.
      s.raw = cv.edited ? cv.base : ''; },
    refreshGui:() => mfPaintForm()});
  mfPaint();
  await cvLoad(d.cv);
  if(state.mf.d !== d || !d.cv) return;
  mfPaint();
}

/* ---- writing ----
   `edits` is exactly what the server's render_any() for this tab takes, so the
   pane and the save cannot produce different bytes. */
function mfEdits(){
  const f = state.mf, w = f.d.w;
  if(f.tab === 'rebels') return {name:w.name, category:w.category, chance:w.chance,
    description:w.description, units:(w.units||[]).filter(Boolean)};
  if(f.tab === 'resources') return {name:w.name, trade_value:w.trade_value,
    item:w.item, icon:w.icon, has_mine:!!w.has_mine};
  if(f.tab === 'religions') return {name:w.name, pip_path:w.pip_path};
  if(f.tab === 'names') return {name:w.name,
    sections:Object.fromEntries((w.sections||[]).map(s => [s.name, s.entries]))};
  // cultures: only the keys this culture actually HAS a line for — the server
  // refuses to invent one, because where it would go is the file's own order
  const out = {name:w.name, levels:{}, agents:{}};
  const v = f.d.vocab || {};
  for(const k of (v.head||[]).concat(v.tail||[]))
    if(w[k]) out[k] = w[k];
  for(const l of (w.levels||[]))
    out.levels[l.name] = {model:l.model, plan:l.plan, card:l.card};
  for(const [a,g] of Object.entries(w.agents||{}))
    out.agents[a] = {card:g.tokens[0], info_card:g.tokens[1], pip:g.tokens[2],
      cost:g.tokens[3]};
  return out;
}

function mfBody(action){
  const f = state.mf, d = f.d;
  const body = {mod:f.mod, tab:f.tab, action,
    name:action === 'add' ? d.w.name : d.name};
  if(action !== 'delete'){
    body.edits = mfEdits();
    body.loc = d.locEdits || {};
    if(d.raw) body.raw_block = d.raw;
  }
  return body;
}

async function mfSave(){
  const f = state.mf, d = f.d;
  if(f.adding && !(d.w.name||'').trim()){
    toast(`A new ${f.noun} needs a name`, 3500); return; }
  await mfApply(mfBody(f.adding ? 'add' : 'edit'),
                f.adding ? `create ${d.w.name}` : `save ${d.name}`);
}
async function mfDelete(){
  await mfApply(mfBody('delete'), `delete ${state.mf.d.name}`);
}

async function mfApply(body, what){
  const f = state.mf;
  if(f.busy) return;
  f.busy = true;
  let plan;
  try{ plan = await api.post('/api/minor/plan', body); }
  finally{ f.busy = false; }
  if(plan.error){ toast('✗ ' + plan.error, 6000); return; }
  const p = plan.plan || {};
  const lines = (p.changes || []).slice(0, 14);
  const found = (p.findings || []).map(x => '⚠ ' + x.message);
  const also = (p.files || []).length
    ? `\n\nAlso rewritten: ${p.files.join(', ')}` : '';
  if(!confirm(`Write: ${what}?\n\n` + (lines.join('\n') || 'no visible change')
    + ((p.changes || []).length > 14 ? `\n…and ${p.changes.length - 14} more` : '')
    + also
    + (found.length ? '\n\n' + found.slice(0, 4).join('\n') : '')
    + '\n\nBacked up first, and 🕑 Log can undo it.')) return;
  f.busy = true;
  let res;
  try{ res = await api.post('/api/minor/apply', body); }
  finally{ f.busy = false; }
  if(res.error){ toast('✗ ' + res.error, 6000); return; }
  toast('Saved. 🕑 Log can undo it.');
  const keep = body.action === 'delete' ? '' : body.name;
  await loadMinor();
  if(keep) mfOpen(keep);
}
