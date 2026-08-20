/* images.js — replace any picture the toolkit shows, from wherever it shows it

   Part of the Medieval 2 GUI Toolkit UI. These files are plain
   <script> tags sharing ONE global scope, loaded in the order set in
   index.html — there is no build step and no module system. Two rules
   follow from that: a top-level name must be unique across all of
   them, and a file's top-level side effects may not depend on a file
   loaded after it. */
/* =========================================================================
   Replacing a picture, anywhere

   Until this file, exactly one picture in the whole toolkit could be swapped:
   the unit card, through the editor's own staged import. Every other image —
   info cards, the building browser's art, ancillary pictures, faction symbols,
   the religion pips and settlement cards in Minor Files — was something you
   could look at and nothing else, even though the tool knew perfectly well
   which file it had just decoded.

   The way in is the `<img>`'s own `src`. Every picture on every screen is
   painted through `/icon` or `/building_icon`, and that URL is a complete
   description of the question the server answered. So the page hands the URL
   straight back, and `unittransfer/images.py` re-resolves it into the file that
   is showing plus the path(s) a replacement is written to.

   Two ways to reach it, because the pictures fall into two groups:

     right-click     works on ANY picture on ANY screen, including the ones in
                     lists and grids that have no room for a button
     ✎ + a button    on the screens where a picture is the thing being edited,
                     so it is discoverable without knowing to right-click

   Both end in the same confirm dialog, which is where the resolution check
   lives: the game does not rescale UI art, so a 512x512 file dropped in for an
   80x24 card is drawn stretched into the same box. That is a warning and never
   a refusal — a mod is free to change what size its own art is, as long as it
   is told what it is doing.
   ========================================================================= */

//: The two routes that serve a picture whose file this tool can locate.
const IMG_ROUTES = ['/icon?', '/building_icon?'];

/* The `src` with the noise taken off. `iconRetry` appends `#r2` and a refresh
   after a save appends `&_ib=<time>`, and neither is part of the question the
   URL asks — sending them back would still work (the server ignores what it
   does not read) but the dialog's own previews would inherit a stale buster. */
function imgUrlOf(el){
  const raw = (el && el.getAttribute && el.getAttribute('src')) || '';
  return raw.split('#')[0].replace(/[?&]_ib=\d+/, '');
}
const imgReplaceable = url => !!url && IMG_ROUTES.some(p => url.startsWith(p));
const imgModOf = url => {
  const qs = url.split('?')[1] || '';
  return new URLSearchParams(qs).get('mod') || '';
};

/* ---------- the right-click menu ----------
   Delegated at the document, so it covers pictures that were rendered before
   this file ran and pictures that have not been rendered yet. Anything that is
   not one of ours keeps the browser's own menu. */
let imgMenuEl = null;
document.addEventListener('contextmenu', ev => {
  const el = ev.target && ev.target.closest ? ev.target.closest('img') : null;
  const url = imgUrlOf(el);
  if(!imgReplaceable(url) || !imgModOf(url)) return;
  ev.preventDefault();
  imgMenu(ev.clientX, ev.clientY, url);
});
function imgMenu(x, y, url){
  imgMenuClose();
  const m = imgMenuEl = document.createElement('div');
  m.className = 'imgmenu';
  m.innerHTML = `
    <button onclick="imgMenuClose();imgPick('${q1(esc(url))}')">Replace image…</button>
    <button onclick="imgMenuClose();imgWhere('${q1(esc(url))}')">Open file location</button>`;
  document.body.appendChild(m);
  // keep it on screen when the click was near the right or bottom edge
  const r = m.getBoundingClientRect();
  m.style.left = Math.min(x, window.innerWidth - r.width - 8) + 'px';
  m.style.top  = Math.min(y, window.innerHeight - r.height - 8) + 'px';
}
function imgMenuClose(){ if(imgMenuEl){ imgMenuEl.remove(); imgMenuEl = null; } }
document.addEventListener('click', imgMenuClose, true);
document.addEventListener('scroll', imgMenuClose, true);
document.addEventListener('keydown', e => { if(e.key === 'Escape') imgMenuClose(); });

/* ---------- the buttons the panels embed ----------
   `after` is the NAME of a re-render function, not the function itself: these
   are inline onclick strings, the same way the rest of the UI is written. It is
   called once the write lands, because a panel that lists what is on disk (the
   editor's card variants, Minor Files' pip table) is out of date the moment a
   file is created or an extension changes. */
const imgEditBtn = (url, after) =>
  `<button class="icoedit" title="Replace this picture"
    onclick="imgPick('${q1(esc(url))}'${after?`,'${after}'`:''})">✎</button>`;
const imgWhereBtn = (url, label) =>
  `<button title="Show the file this picture comes from in the file manager."
    onclick="imgWhere('${q1(esc(url))}')">${label || 'Open file location'}</button>`;
const imgRow = (url, after) =>
  `<div class="sprrow">${imgWhereBtn(url)}
    <button onclick="imgPick('${q1(esc(url))}'${after?`,'${after}'`:''})">Replace image…</button>
  </div>`;

/* Call a re-render by name.
   `window[name]` is not enough: a top-level `const` in a classic script lands in
   the global LEXICAL scope, not on `window`, so half the page's functions are
   invisible to a property lookup (`bldRenderBodyNow` is one). A `Function` body
   runs in global scope, which can see both. */
function imgCall(name){
  if(!name) return;
  try{
    const fn = Function(`return typeof ${name}==='function'?${name}:null`)();
    if(fn) fn();
  }catch(e){ /* a panel that has since closed is not an error */ }
}

/* ---------- open file location ---------- */
async function imgWhere(url){
  let r;
  try{ r = await api.post('/api/image/reveal', {mod: imgModOf(url), url}); }
  catch(e){ r = {ok:false, error:''+e}; }
  if(!r || !r.ok) return toast((r && r.error) || 'that folder could not be opened');
  if(r.outside) toast('that picture is the game’s own, not this mod’s');
  else if(r.folder_only) toast('nothing there yet — opened the folder it would go in');
}

/* ---------- pick, confirm, write ---------- */
let imgBack = null;                    // the dialog we opened over, to put back
async function imgPick(url, after){
  const mod = imgModOf(url);
  let p;
  try{ p = await api.post('/api/image/plan', {mod, url, src:''}); }
  catch(e){ return toast(''+e); }
  if(!p.ok) return toast(p.error || 'that picture cannot be replaced');
  const f = await api.post('/api/browse_file',
    {title: 'Pick the picture to use for ' + p.label,
     filter: 'Images (*.tga;*.dds;*.png;*.jpg;*.jpeg;*.bmp)|'
           + '*.tga;*.dds;*.png;*.jpg;*.jpeg;*.bmp|All files (*.*)|*.*'});
  if(!f.path) return;
  let q;
  try{ q = await api.post('/api/image/plan', {mod, url, src:f.path}); }
  catch(e){ return toast(''+e); }
  imgDialog(url, mod, f.path, q, after || '');
}

function imgDialog(url, mod, src, p, after){
  const modal = document.getElementById('modal');
  const overlay = document.getElementById('overlay');
  const wasOpen = overlay.classList.contains('open');
  imgBack = wasOpen ? {html: modal.innerHTML, cls: modal.className,
                       scroll: stashPlace(), after} : {after};
  const cur = p.current || {}, inc = p.incoming || {};
  const dim = d => (d && d.ok) ? `${d.width}x${d.height}`
                               : `<span class="w-warn">size unknown</span>`;
  const kb = d => (d && d.bytes) ? ` · ${Math.round(d.bytes/1024)} KB` : '';
  const ok = p.ok !== false;
  modal.innerHTML = `<h2>Replace ${esc(p.label || 'this picture')}</h2>
    <div class="mbody">
      ${ok ? '' : `<div class="w-bad" style="margin-bottom:10px">${esc(p.error||'')}</div>`}
      <div class="imgcmp">
        <figure>
          <img src="${esc(url)}&_ib=${Date.now()}" onerror="iconRetry(this)" alt="">
          <figcaption><b>On disk now</b><br>${p.showing
            ? `${dim(cur)}${kb(cur)}<br><span class="count">${esc(p.showing)}</span>`
            : '<span class="count">nothing here yet</span>'}</figcaption>
        </figure>
        <div class="imgarrow">→</div>
        <figure>
          <img src="/preview_image?path=${encodeURIComponent(src)}" alt="">
          <figcaption><b>The new one</b><br>${dim(inc)}${kb(inc)}<br>
            <span class="count">${esc(src)}</span></figcaption>
        </figure>
      </div>
      ${p.note ? `<div class="count" style="margin-top:10px">${esc(p.note)}</div>` : ''}
      ${(p.warnings||[]).map(w =>
        `<div class="w-warn" style="margin-top:8px">⚠ ${esc(w)}</div>`).join('')}
      ${(p.replaces||[]).length ? `<div class="count" style="margin-top:10px">${
        docPoints(`This writes ${p.replaces.length} file${
          p.replaces.length===1?'':'s'} under the mod's own data folder:`,
          p.replaces.map(r => `<code>${esc(r.rel)}</code> — ${
            r.exists ? 'overwritten' : '<b>created</b>'}${
            r.drops.length ? `, and <code>${r.drops.map(esc).join('</code> <code>')
              }</code> removed` : ''}`))
        }<br>Every one of them is backed up first, so this is one Undo away.</div>` : ''}
    </div>
    <div class="foot">
      <button onclick="imgCancel()">Cancel</button>
      <button class="primary" ${ok?'':'disabled'}
        onclick="imgApply('${q1(esc(url))}','${q1(esc(mod))}','${q1(esc(src))}')">
        Replace</button>
    </div>`;
  modal.className = 'modal';
  overlay.classList.add('open');
}

function imgCancel(){
  const modal = document.getElementById('modal');
  if(imgBack && imgBack.html !== undefined){
    modal.className = imgBack.cls; modal.innerHTML = imgBack.html;
    usePlace(imgBack.scroll);
    // restored markup is inert until its handlers are bound again, and only the
    // panel's own re-render knows how to do that
    const after = imgBack.after; imgBack = null;
    imgCall(after);
    return;
  }
  imgBack = null;
  closeModal();
}

async function imgApply(url, mod, src){
  let r;
  try{ r = await api.post('/api/image/replace', {mod, url, src}); }
  catch(e){ return toast(''+e); }
  if(!r || !r.ok) return toast((r && r.error) || 'the picture could not be replaced');
  activity('replaced a picture', r.summary || url);
  imgCancel();                          // puts the panel underneath back
  imgBust();
  toast(r.summary || 'picture replaced');
}

/* Every picture on the page, re-fetched.
   The server sends `Cache-Control: no-cache`, but a replacement can touch ten
   faction folders at once and the page has no idea which of its thumbnails came
   out of which of them — so the cheap, correct answer is to re-ask for all of
   them rather than to guess. */
function imgBust(){
  const stamp = Date.now();
  document.querySelectorAll('img').forEach(el => {
    const url = imgUrlOf(el);
    if(imgReplaceable(url)) el.src = url + '&_ib=' + stamp;
  });
}
