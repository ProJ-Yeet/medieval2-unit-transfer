/* strings.js — Strings mode: the compiled .txt.strings.bin files, read and written

   Part of the Medieval 2 GUI Toolkit UI. These files are plain
   <script> tags sharing ONE global scope, loaded in the order set in
   index.html — there is no build step and no module system. Two rules
   follow from that: a top-level name must be unique across all of
   them, and a file's top-level side effects may not depend on a file
   loaded after it. */
/* ======================= STRINGS MODE =======================
   Every piece of text the game shows lives in data/text as a pair: a .txt anyone
   can read, and a .strings.bin the game compiled from it. **The game reads the
   .bin.** Edit the .txt and nothing changes on screen until the .bin agrees —
   which is where "delete the .bin and let the game rebuild it" comes from, and
   why a mod can sit for years showing text its own .txt has not said in months.

   So this module works on the .bin directly. A row here is an entry in the
   compiled file: change it, save it, and the game says the new thing on the next
   launch with nothing deleted and nothing to rebuild. `⟳ Rebuild from .txt`
   recompiles the whole archive from the text file beside it, for when the .txt
   is the one that is right.

   Rows are filtered on the SERVER (see unittransfer/strings.py) — names.txt runs
   to 20 757 entries and shipping all of them so the browser can hide 20 000 is
   how a local tool starts feeling like a website.

   Four archives (battle, shared, strat, tooltips) store bare strings the engine
   addresses by position, with no tags at all. They are editable by row here, but
   they get no Code View: `{tag}text` is not a shape they have. */

const STR_PAGE = 400;

async function loadStrings(){
  const mod = state.src;
  main.innerHTML = '<div class="empty">Looking for ' + esc(mod) + '’s text files…</div>';
  let r;
  try{ r = await api.get('/api/strings?mod=' + enc(mod)); }
  catch(e){ if(stale('strings', mod)) return;
    main.innerHTML = `<div class="empty">Couldn't read the text folder.<br>
      <span class="count">${esc(''+e)}</span><br><br>
      <button class="primary" onclick="loadStrings()">Retry</button></div>`; return; }
  if(stale('strings', mod)) return;
  state.str = Object.assign({file:'', rows:null, edits:{}, busy:false}, r);
  undoReset();
  renderStrings();
}

function renderStrings(){
  const s = state.str;
  if(!s){ loadStrings(); return; }
  const strip = minorTabsHtml('', s.dir || 'data/text');
  if(!s.files.length){
    main.innerHTML = strip + `<div class="empty">${esc(s.mod)} has no .strings.bin files.<br>
      <span class="count">Looked in ${esc(s.dir)}</span></div>`;
    return;
  }
  count.textContent = `${s.files.length} file${s.files.length===1?'':'s'}`;
  main.innerHTML = strip + `<div class="strwrap">
    <div class="strlist">${s.files.map(strFileRow).join('')}</div>
    <div class="strmain" id="strMain">${strRowsHtml()}</div>
  </div>`;
}

function strFileRow(f){
  const on = state.str.file === f.rel;
  const state_ = f.error ? `<span class="w-bad">unreadable</span>`
    : f.stale ? `<span class="w-warn">${esc(f.txt)} is newer</span>`
    : f.txt ? `<span class="count">${esc(f.txt)}</span>`
    : `<span class="count">No .txt beside it</span>`;
  return `<button class="strfile${on?' on':''}" onclick="strOpen('${q1(esc(f.rel))}')">
    <div class="nm">${esc(f.label)}${f.tagged?'':' <span class="badge">by position</span>'}</div>
    <div class="sub">${f.error?'':`${f.entries} entries · `}${state_}</div>
  </button>`;
}

async function strOpen(rel){
  activity('opened strings file', `${rel} in ${state.src}`);
  const s = state.str;
  s.file = rel; s.rows = null; s.edits = {}; s.offset = 0;
  renderStrings();
  await strFetchRows();
}

async function strFetchRows(){
  const s = state.str, rel = s.file;
  if(!rel) return;
  const q = search.value.trim();
  let r;
  try{
    r = await api.get(`/api/strings/entries?mod=${enc(s.mod)}&file=${enc(rel)}`
      + `&q=${enc(q)}&limit=${STR_PAGE}&offset=${s.offset||0}`);
  }catch(e){ r = {error: '' + e}; }
  if(state.mode !== 'strings' || state.str !== s || s.file !== rel) return;
  s.rows = r;
  // A file is open now: this is Ctrl+Z's baseline. `undoBaseline` rather than
  // `undoReset` because this also runs for paging and searching within the same
  // file, and pending edits (and their history) outlive both.
  undoBaseline();
  const el = document.getElementById('strMain');
  if(el) el.innerHTML = strRowsHtml();
}

function strRowsHtml(){
  const s = state.str;
  if(!s.file) return '<div class="empty">Pick a file on the left.</div>';
  const r = s.rows;
  if(!r) return '<div class="empty">Reading the entries…</div>';
  if(r.error) return `<div class="empty"><span class="w-bad">✗ ${esc(r.error)}</span></div>`;
  const f = s.files.find(x => x.rel === s.file) || {};
  const pending = Object.keys(s.edits).length;
  const shown = r.rows.length, more = r.matched - (r.offset + shown);
  return `<div class="strbar">
      <div>
        <b>${esc(r.name)}</b>
        <span class="count">${r.matched === r.count ? `${r.count} entries`
          : `${r.matched} of ${r.count} entries match`}${
          r.tagged ? '' : ' · addressed by position'}</span>
      </div>
      <span class="sp"></span>
      ${f.txt && r.tagged ? `<button title="Compile ${esc(f.txt)} over this archive, so the game
reads what the text file says. Backed up first, and undoable from 🕑 Log."
        onclick="strRebuild()">⟳ Rebuild from ${esc(f.txt)}</button>` : ''}
      <button class="primary" ${pending?'':'disabled'} onclick="strSave()">
        Save ${pending} change${pending===1?'':'s'}</button>
    </div>
    ${f.stale && r.tagged ? `<div class="strnote w-warn">${esc(f.txt)} was edited after this
      archive was built, so the game is showing older text than the .txt says.
      ⟳ Rebuild puts that right.</div>` : ''}
    <table class="strtab">
      <tr><th>${r.tagged ? 'Tag' : 'Row'}</th><th>Text</th><th></th></tr>
      ${r.rows.map(strRowHtml).join('') || '<tr><td colspan="3" class="count">No entry matches.</td></tr>'}
    </table>
    ${more > 0 ? `<div class="strmore"><button onclick="strMore()">Show ${
      Math.min(more, STR_PAGE)} more</button>
      <span class="count">${more} not shown. Narrow the search above.</span></div>` : ''}`;
}

function strRowHtml(row){
  const s = state.str;
  const edited = s.edits[row.id] !== undefined;
  const value = edited ? s.edits[row.id] : row.value;
  return `<tr class="${edited?'edited':''}">
    <td class="k"><code>${esc(row.tag || ('#' + row.pos))}</code></td>
    <td><textarea rows="${Math.min(6, 1 + (value.match(/\n/g)||[]).length)}"
      data-row="${esc(row.id)}"
      oninput="strEdit('${q1(esc(row.id))}',this.value)">${esc(value)}</textarea></td>
    <td class="s">${edited
      ? `<button title="Put this entry back to what the archive says"
           onclick="strRevert('${q1(esc(row.id))}')">↺</button>` : ''}
      ${s.rows.tagged
      ? `<button title="Show this entry as the .txt writes it"
           onclick="strCode('${q1(esc(row.id))}')">&lt;/&gt;</button>` : ''}</td>
  </tr>`;
}

function strEdit(id, value){
  const s = state.str, row = (s.rows.rows || []).find(r => r.id === id);
  if(!row) return;
  if(value === row.value) delete s.edits[id]; else s.edits[id] = value;
  // The bar and this one row are repainted, never the table: redrawing it would
  // take the caret out of the box being typed in.
  const box = document.querySelector(`.strtab textarea[data-row="${cssq(id)}"]`);
  if(box) box.closest('tr').classList.toggle('edited', s.edits[id] !== undefined);
  strPaintBar();
}
function strRevert(id){
  delete state.str.edits[id];
  const el = document.getElementById('strMain');
  if(el) el.innerHTML = strRowsHtml();
}
function strPaintBar(){
  const n = Object.keys(state.str.edits).length;
  const b = document.querySelector('.strbar button.primary');
  if(b){ b.disabled = !n; b.textContent = `Save ${n} change${n===1?'':'s'}`; }
}
// One debounce for the header search, since every keystroke is a round trip
let strSearchT = null;
function strSearch(){
  if(!state.str || !state.str.file) return;
  clearTimeout(strSearchT);
  strSearchT = setTimeout(() => { state.str.offset = 0; strFetchRows(); }, 250);
}
function strMore(){
  const s = state.str;
  s.offset = (s.offset || 0) + STR_PAGE;
  strFetchRows();
}

/* ---- one entry as the .txt writes it ----
   The archive is binary, but an entry is exactly the `{tag}text` line of the
   .txt beside it, so that is what the Code View shows — the format modders
   already write, not a decoded stand-in. */
function strCode(id){
  const s = state.str;
  const row = (s.rows.rows || []).find(r => r.id === id);
  if(!row) return;
  const value = s.edits[id] !== undefined ? s.edits[id] : row.value;
  const cv = cvCreate({
    kind:'strings', mod:s.mod, id:`${s.file}|${row.id}`,
    where:s.rows.name,
    edits:() => ({tag: row.tag, value: strCvValue(cv)}),
    adopt:c => { if(c.detail) strCvSet(row, c.detail.value); },
  });
  cv._value = value;
  strCodeModal(cv, row);
}
const strCvValue = cv => cv._value;
function strCvSet(row, value){
  const s = state.str;
  if(value === row.value) delete s.edits[row.id]; else s.edits[row.id] = value;
  const box = document.getElementById('strCvBox');
  if(box && box.value !== value) box.value = value;
}

async function strCodeModal(cv, row){
  const m = document.getElementById('modal');
  m.className = 'modal wide';
  m.innerHTML = `<div class="ehead"><div>
      <div class="nm">${esc(row.tag)}</div>
      <div class="count">${esc(state.str.rows.name)}</div></div></div>
    <div style="padding:12px">
      <div class="lbl">Text</div>
      <textarea id="strCvBox" rows="5" style="width:100%"
        oninput="strCvType(cvOf('${cv.uid}'),this.value)">${esc(cv._value)}</textarea>
      <div id="strCvPane" style="margin-top:10px"></div>
    </div>
    <div style="padding:0 12px 12px;text-align:right">
      <button onclick="strCloseCode(cvOf('${cv.uid}'))">Close</button></div>`;
  overlay.classList.add('open');
  await cvLoad(cv);
  const pane = document.getElementById('strCvPane');
  if(pane){ pane.innerHTML = cvHtml(cv); cvWire(cv); }
  // cvLoad shows what is ON DISK. If this row already has an unsaved edit, the
  // pane would be showing a different string from the box right above it — so
  // re-render it from the pending value, through the same writer a save uses.
  if(cv.detail && cv._value !== cv.detail.value){ await cvRender(cv); cvRedrawLines(cv); }
}
function strCvType(cv, value){
  if(!cv) return;
  cv._value = value;
  const row = (state.str.rows.rows || []).find(r => `${state.str.file}|${r.id}` === cv.id);
  if(row) strCvSet(row, value);
  cvFromGui(cv);
}
function strCloseCode(cv){
  cvDrop(cv);
  closeModal();
  const el = document.getElementById('strMain');
  if(el) el.innerHTML = strRowsHtml();
}

/* ---- writing ---- */
async function strSave(){
  const s = state.str;
  const edits = Object.keys(s.edits).map(id => ({id, value: s.edits[id]}));
  if(!edits.length) return;
  await strApply({mod:s.mod, file:s.file, edits},
                 `${edits.length} entry(ies) in ${s.file.split('/').pop()}`);
}
async function strRebuild(){
  const s = state.str;
  const f = s.files.find(x => x.rel === s.file) || {};
  if(!confirm(`Compile ${f.txt} over ${f.name}?\n\nThe archive is backed up first `
    + `and 🕑 Log can undo it.`)) return;
  await strApply({mod:s.mod, file:s.file, action:'rebuild'}, `${f.name} from ${f.txt}`);
}

async function strApply(body, what){
  const s = state.str;
  s.busy = true;
  const plan = await api.post('/api/strings/plan', body);
  if(plan.error){ toast('✗ ' + plan.error, 5000); s.busy = false; return; }
  const p = plan.plan || {};
  const lines = (p.changes || []).slice(0, 12);
  if(!confirm(`Write ${what}?\n\n` + (lines.join('\n') || 'no visible change')
    + ((p.changes || []).length > 12 ? `\n…and ${p.changes.length - 12} more` : '')
    + `\n\n${p.before} entries -> ${p.after}`)) { s.busy = false; return; }
  const res = await api.post('/api/strings/apply', body);
  s.busy = false;
  if(res.error){ toast('✗ ' + res.error, 5000); return; }
  toast(`Saved. 🕑 Log can undo it.`);
  await loadStrings();
}
