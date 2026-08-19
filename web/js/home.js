/* home.js — Home mode: the mods this machine has, and what each one is ready for

   Part of the Medieval 2 GUI Toolkit UI. These files are plain
   <script> tags sharing ONE global scope, loaded in the order set in
   index.html — there is no build step and no module system. Two rules
   follow from that: a top-level name must be unique across all of
   them, and a file's top-level side effects may not depend on a file
   loaded after it. */
/* ======================= HOME =======================
   The toolkit used to open on whichever module you were last in, pointed at
   whichever mod you were last looking at, with no way to see either choice
   except by reading the two dropdowns in the header. Home is the landing page
   that answers both up front: here are your mods, here is what each one has on
   disk, here is what you can do with it.

   Each card asks the server (`/api/mod_files`) which of the files a module reads
   are actually there, so a module that cannot work on this mod says why on the
   card instead of being found out three clicks later. That report is read-only
   and shallow — file stats and an encoding sniff, never a parse — and it is
   cached per mod for the session, because it is a landing page and it has to
   feel like one.

   Nothing here is a second copy of the mod list: it is `state.mods`, the same
   one the header dropdown uses. */

// mod name -> its /api/mod_files report, or 'loading' / {error}
const HOME_REPORTS = {};

function renderHome(){
  const mods = state.mods || [];
  count.textContent = mods.length ? `${mods.length} mod${mods.length===1?'':'s'}` : '';
  if(!mods.length){
    main.innerHTML = `<div class="empty">No mods found.<br>
      <span class="count">Click ⚙ Settings and point the toolkit at your Medieval II folder.</span>
      <br><br><button class="primary" onclick="openSettings()">⚙ Settings</button></div>`;
    return;
  }
  main.innerHTML = `<div class="homewrap">
    ${homeRootHtml()}
    <div class="homestep">
      <span class="n">2</span>
      <span class="t"><b>Pick a mod, then a module.</b>
        <div class="p">Every write is backed up. 🕑 Log undoes any of them.</div></span>
    </div>
    ${homeResumeHtml()}
    <div class="homegrid">${mods.map(homeCardHtml).join('')}</div>
    ${homePrefsHtml()}
  </div>`;
  mods.forEach(m => homeLoadReport(m.name));
}

// Step 1 of using the toolkit at all: it has to know where Medieval II lives,
// because every mod it can see is a folder under that root.
//
// The buttons are the same two the settings dialog has, put here directly: a step
// that says "your mods live here" and then sends you to a dialog to change it is
// one hop longer than it needs to be, and the dialog is a worse place to do it
// from — this line is what you are looking at when you notice it is wrong.
function homeRootHtml(){
  const root = state.settings.med2_root || '';
  return `<div class="homestep">
    <span class="n">1</span>
    <span class="t">
      <b>Root mod folder.</b> The Medieval II folder your mods sit under.
      <div class="p">${root ? esc(root) : 'not set yet'}</div>
      <div class="count" id="homeRootStatus"></div>
    </span>
    <button onclick="homeAutoDetect()" title="Look the install path up from the registry">Auto-detect</button>
    <button class="${root ? '' : 'primary'}" onclick="homeBrowseRoot()">Browse…</button>
  </div>`;
}
// Both reuse the settings dialog's own actions, then re-read the mods and repaint
// Home — the point of doing it here is that the card grid below answers straight
// away whether the folder was the right one.
async function homeSetRoot(path){
  const st = document.getElementById('homeRootStatus');
  if(st) st.textContent = 'Reading ' + path + '…';
  const r = await api.post('/api/settings', {med2_root: path});
  state.settings = r;
  await refreshMods(state.src, state.dst);
  // the per-mod reports belong to the folder that has just been replaced
  for(const k of Object.keys(HOME_REPORTS)) delete HOME_REPORTS[k];
  render();
}
async function homeBrowseRoot(){
  const r = await api.post('/api/browse_folder', {title:'Pick your Medieval II folder (it contains "mods")'});
  if(!r.path) return;
  await homeSetRoot(r.path);
}
async function homeAutoDetect(){
  const st = document.getElementById('homeRootStatus');
  if(st) st.textContent = 'Looking for a Medieval II install…';
  const r = await api.get('/api/detect_med2_root');
  if(!r.path){
    if(st) st.innerHTML = '<span class="w-warn">No install found in the registry. Use Browse instead.</span>';
    return;
  }
  await homeSetRoot(r.path);
}

// Step 3: the settings that are worth having in front of you rather than behind a
// dialog. The dialog stays — it owns the awkward ones (the M2TWEOP folders, the
// unit-limit overrides) — but nothing here should need it.
function homePrefsHtml(){
  const s = state.settings || {};
  // One row per preference: the tick box and its label on the left, the hint
  // right-aligned, so the rows line up down the page.
  const chk = (id, on, label, hint) => `<div>
      <label class="chk"><input type="checkbox" id="${id}"
        ${on ? 'checked' : ''} onchange="homePref(this)"> ${label}</label>
      ${hint ? `<span class="count">${hint}</span>` : ''}</div>`;
  return `<div class="homestep">
    <span class="n">3</span>
    <span class="t">
      <b>Preferences.</b>
      <div class="homeprefs">
        ${chk('prefConsole', s.show_console, 'Keep the console window open',
              'from the next launch')}
        ${chk('prefSoldierBase', s.soldier_from_base, 'Start the Soldier row on <b>Base</b>',
              'in a transfer')}
        ${chk('prefClearBin', s.clear_strings_bin, 'Recompile <code>.strings.bin</code> after a text write',
              'the game reads the compiled copy')}
        ${chk('prefCodeView', s.code_view, 'Show Code View beside the guided editors',
              'the raw lines, live')}
        <div>
          <label class="chk" style="gap:6px">Faction names lead with
            <select id="prefFacSort" onchange="homePref(this)">
              <option value="name" ${s.faction_sort!=='code'?'selected':''}>the in-game name</option>
              <option value="code" ${s.faction_sort==='code'?'selected':''}>the EDU code</option>
            </select></label>
          <span class="count">the other one follows in brackets</span>
        </div>
      </div>
    </span>
    <button onclick="openSettings()" title="M2TWEOP folders, the 500-unit-limit overrides, the cache and Quit">⚙ All settings</button>
  </div>`;
}
// One handler for the lot: the id says which setting, so adding a row above needs
// nothing here.
const HOME_PREF_KEY = {prefConsole:'show_console', prefSoldierBase:'soldier_from_base',
  prefClearBin:'clear_strings_bin', prefCodeView:'code_view', prefFacSort:'faction_sort'};
async function homePref(el){
  const key = HOME_PREF_KEY[el.id]; if(!key) return;
  const value = el.tagName === 'SELECT' ? el.value : !!el.checked;
  state.settings[key] = value;
  await api.post('/api/settings', {[key]: value});
  if(key === 'faction_sort'){
    facSort.value = facBy();
    if(state.data) buildFilter('factionFilter', state.data.factions, 'faction', true);
  }
  toast('Saved.');
}

// The module you were last in, offered rather than jumped into: landing
// somewhere you did not ask for is exactly what Home exists to stop.
function homeResumeHtml(){
  const last = state.settings.mode;
  if(!last || last === 'home' || !MODES.some(m => m.id === last)) return '';
  const d = modeDef(last);
  const mod = state.src || '';
  return `<div class="homeresume">
    <span class="count">Last time you were in</span>
    <button class="primary" onclick="homeGo('${q1(esc(mod))}','${esc(d.id)}')">
      ${d.icon} ${esc(d.name)}${mod?` — ${esc(mod)}`:''} →</button>
  </div>`;
}

function homeCardHtml(m){
  const r = HOME_REPORTS[m.name];
  // The mod's FOLDER name, never its campaign title. The two disagree often
  // enough ("War of the Ring" is Divide_and_Conquer_EUR) that showing the title
  // means the card and every dropdown in the app name different things.
  return `<section class="homecard" id="hc-${esc(homeKey(m.name))}">
    <div class="hchead">
      <div>
        <div class="nm">${esc(m.name)}</div>
        <div class="sub" title="${esc(m.root)}">${esc(m.root)}</div>
      </div>
      ${m.pack?'<span class="badge">📦 mounted pack</span>':''}
    </div>
    <div class="hcmods">${homeModulesHtml(m, r)}</div>
    <div class="hcfiles">${homeFilesHtml(m, r)}</div>
  </section>`;
}
// ids have to survive a mod folder called anything at all
const homeKey = name => (''+name).replace(/[^A-Za-z0-9_-]/g,'_');

function homeModulesHtml(m, r){
  if(!r) return '<span class="count">Reading the mod’s files…</span>';
  if(r.error) return `<span class="w-bad">✗ ${esc(r.error)}</span>`;
  return MODES.filter(d => d.id !== 'home' && !d.sub).map(d => {
    const s = r.modules[d.id];
    if(!s) return '';
    const why = s.ready
      ? (s.partial.length ? `works, but this mod has no ${s.partial.join(', ')}` : d.hint)
      : `needs ${s.missing.join(', ')} — this mod has none`;
    return `<button class="hcmod${s.ready?'':' off'}" title="${esc(why)}"
      onclick="homeGo('${q1(esc(m.name))}','${esc(d.id)}')">
      <span class="ic">${d.icon}</span><span class="nm">${esc(d.name)}</span>
      ${s.ready?(s.partial.length?'<span class="dot warn">●</span>':'')
              :'<span class="dot bad">●</span>'}</button>`;
  }).join('');
}

function homeFilesHtml(m, r){
  if(!r || r.error) return '';
  const key = homeKey(m.name);
  const bad = r.files.filter(f => f.state === 'missing' || f.state === 'unreadable');
  const open = !!HOME_REPORTS['_open_' + m.name];
  return `<button class="hctoggle" onclick="homeToggleFiles('${q1(esc(m.name))}')">
      ${open?'▾':'▸'} ${r.files.length} known files${bad.length?` · ${bad.length} missing`:' · all present'}
    </button>
    ${open?`<table class="hctab">${r.files.map(homeFileRow).join('')}</table>`:''}`;
}
function homeFileRow(f){
  const mark = {present:'<span class="w-good">✓</span>',
                compiled:'<span class="w-good">✓</span>',
                empty:'<span class="w-warn">○</span>',
                missing:f.required?'<span class="w-bad">✗</span>':'<span class="count">—</span>',
                unreadable:'<span class="w-bad">!</span>'}[f.state] || '';
  const size = f.state === 'missing' ? ''
    : f.folder ? `${f.size} item${f.size===1?'':'s'}` : homeSize(f.size);
  return `<tr title="${esc(f.note || f.rel)}">
    <td class="s">${mark}</td>
    <td>${esc(f.label)}<div class="count">${esc(f.rel)}</div></td>
    <td class="count r">${esc(size)}</td>
    <td class="count">${esc(f.encoding || '')}</td></tr>`;
}
const homeSize = n => n >= 1048576 ? (n/1048576).toFixed(1)+' MB'
  : n >= 1024 ? Math.round(n/1024)+' KB' : n+' B';

function homeToggleFiles(name){
  HOME_REPORTS['_open_' + name] = !HOME_REPORTS['_open_' + name];
  renderHome();
}

async function homeLoadReport(name){
  if(HOME_REPORTS[name] || HOME_REPORTS['_busy_' + name]) return;
  HOME_REPORTS['_busy_' + name] = true;
  let r;
  try{ r = await api.get('/api/mod_files?mod=' + encodeURIComponent(name)); }
  catch(e){ r = {error: '' + e}; }
  HOME_REPORTS['_busy_' + name] = false;
  HOME_REPORTS[name] = r;
  if(state.mode !== 'home') return;           // they moved on while this loaded
  // repaint just this card, so a slow mod does not restart every other card's
  // load by redrawing the whole grid
  const el = document.getElementById('hc-' + homeKey(name));
  const m = (state.mods || []).find(x => x.name === name);
  if(el && m) el.outerHTML = homeCardHtml(m);
}

/* Open a module on a mod: the two choices the header dropdowns hold, made in one
   click. Both go through the same paths the dropdowns do, so nothing here is a
   second way of changing the mod. */
async function homeGo(name, mode){
  if(name && name !== state.src){
    srcSel.value = name;
    await srcSel.onchange({target: srcSel});
  }
  setAppMode(mode);
}
