/* buildings.js — Buildings mode: export_descr_buildings.txt — levels, recruit
   pools, requires clauses, upgrades and cross-tree editing

   Part of the Medieval 2 GUI Toolkit UI. These files are plain
   <script> tags sharing ONE global scope, loaded in the order set in
   index.html — there is no build step and no module system. Two rules
   follow from that: a top-level name must be unique across all of
   them, and a file's top-level side effects may not depend on a file
   loaded after it. */
/* =========================================================================
   Buildings mode — data/export_descr_buildings.txt

   A building "line" is an upgrade chain (Barracks -> Militia Barracks -> …).
   The grid lists lines; opening one gives a tab per level with its stats, its
   capabilities and, the point of the whole screen, its recruit pools: which
   units it trains, at what rate, for whom.

   Building art is per CULTURE, not per faction — data/ui/<culture>/buildings/
   #<culture>_<level>.tga is the small icon and #<culture>_<level>_constructed.tga
   the big one. A mod ships only what it changed, so anything it doesn't have
   falls back to unpacked vanilla art and then to a drawn placeholder; the badge
   on the picture says which you're looking at.
   ========================================================================= */

const BLD_SETTLE_LABEL={city:'City',castle:'Castle',both:'City + castle'};

//: The four numbers of a `recruit_pool` line, explained on their ? markers.
const POOL_HELP={
  initial:'Points the pool holds the moment the building finishes. One point is '
    +'one unit ready to hire, so 1 means the first one can be recruited straight away.',
  per_turn:'Points the pool gains each turn; one point is one unit. The ▲▼ move '
    +'it by a whole turn at a time, and the grey reading beside it says how long '
    +'one unit actually takes.',
  maximum:'The most points the pool can hold. It stops filling here, so this is '
    +'how many of the unit can be waiting to hire at once.',
  experience:'Experience the unit is recruited with, 0 to 9. Each point is a '
    +'chevron; 9 is three gold ones.',
};

/* ---- number boxes ----
   A number box is an ordinary input with ▲▼ beside it; the arrows only set
   .value and fire `input`, so the field's own handler stores the change exactly
   as typing would (and so undo records it as one step).

   `step` is how far one click moves the value, with one special case: 'turns'
   moves a recruit rate by one whole TURN rather than by a fraction. A rate of
   0.066667 is "a unit every 15 turns", and nobody thinks in the fraction — ▲
   there gives 1/14 = 0.071429, still "the number goes up". */
const numFmt=n=>String(+(+n).toFixed(6));
function numBox(attrs,value,step,after){
  return `<span class="numwrap"><input ${attrs} data-step="${esc(step)}"
      value="${esc(value)}" inputmode="decimal">
    <span class="spin"><button type="button" tabindex="-1" data-bump="1" title="Increase">▲</button
      ><button type="button" tabindex="-1" data-bump="-1" title="Decrease">▼</button></span>
    ${after||''}</span>`;
}
// Turns per unit, for a recruit pool's points-per-turn. 0 or nonsense = never.
function poolTurns(v){
  const n=parseFloat(v);
  if(!isFinite(n)||n<=0)return 'never';
  const t=1/n;
  if(t<=1.02)return 'every turn';
  return (t<10?numFmt(t.toFixed(1)):Math.round(t))+' turns';
}
/* A pool count of 1 and a pool count of 0 are different buildings, and the
   useful value between them is 0.99: the pool fills but never reaches a whole
   point, so the unit shows without ever becoming recruitable. Stepping straight
   from 1 to 0 meant typing it by hand every time. */
const POOL_EDGE=0.99;
function numBump(inp,dir){
  const step=inp.dataset.step||'1';
  const cur=parseFloat(inp.value);
  let next;
  if(step==='turns'){
    const turns=(isFinite(cur)&&cur>0)?Math.max(1,Math.round(1/cur)):1;
    next=1/Math.max(1,turns-dir);       // ▲ = one turn sooner = a bigger rate
  }else if(step==='pool'){
    const v=isFinite(cur)?cur:0;
    next=dir<0 ? (v>1?v-1:(v>POOL_EDGE?POOL_EDGE:0))
               : (v<POOL_EDGE?POOL_EDGE:(v<1?1:v+1));
  }else{
    next=(isFinite(cur)?cur:0)+dir*(parseFloat(step)||1);
    if(next<0)next=0;                   // no negative costs, pools or build times
  }
  inp.value=numFmt(next);
  inp.dispatchEvent(new Event('input',{bubbles:true}));
}
// Wire every ▲▼ under `root`, and keep any "= 15 turns" readout beside a rate
// box in step with what is typed into it.
function wireNumBoxes(root){
  root.querySelectorAll('.numwrap').forEach(w=>{
    const inp=w.querySelector('input'); if(!inp)return;
    const turns=w.querySelector('.turns');
    w.querySelectorAll('[data-bump]').forEach(btn=>{
      btn.onclick=e=>{e.preventDefault();numBump(inp,+btn.dataset.bump);};
    });
    // ↑/↓ in the box do what the arrows beside it do — including the 1 → 0.99 → 0
    // step on a pool count, which is the whole reason to reach for the key
    inp.addEventListener('keydown',e=>{
      const dir=e.key==='ArrowUp'?1:e.key==='ArrowDown'?-1:0;
      if(!dir)return;
      e.preventDefault(); numBump(inp,dir);
    });
    if(turns)inp.addEventListener('input',()=>{turns.textContent='= '+poolTurns(inp.value);});
  });
}

function bldIcon(level,kind,culture){
  return `/building_icon?mod=${enc(state.src)}&culture=${enc(culture||bldCultureNow())}`
       + `&level=${enc(level)}&kind=${kind||'small'}`;
}
function bldCultureNow(){
  const b=state.bld; return (b&&b.culture)||'';
}
// One in-flight request per mod, shared by every caller. render() fires again on
// each keystroke and filter tick, and switching mod nulls state.bld mid-await —
// without this the second caller could resume before the first had assigned.
//
// The overview is also per CULTURE, because a building's name is: DaC names
// every one of its buildings per culture and leaves the shared key a
// placeholder, so the grid has to ask for the names of the culture on show.
let _bldLoading=null;
async function loadBuildings(force){
  const want=state.settings.bld_culture||'';
  if(state.bld&&state.bld.mod===state.src&&!force)return state.bld;
  if(_bldLoading&&_bldLoading.mod===state.src&&!force)return _bldLoading.p;
  main.innerHTML='<div class="empty">Reading '+esc(state.src)+'’s buildings…</div>';
  const mod=state.src;
  const p=(async()=>{
    let ov=await api.get('/api/buildings?mod='+enc(mod)+'&culture='+enc(want));
    // Which culture's art and names lead: whatever was picked last if this mod
    // has it, else the first culture folder that holds building art.
    const culture=(ov.cultures||[]).includes(want)?want:(ov.cultures||[])[0]||'';
    // the remembered culture is not one this mod has, so the names that came
    // back are the wrong culture's — ask again for the one actually on show
    if(culture!==want)ov=await api.get('/api/buildings?mod='+enc(mod)+'&culture='+enc(culture));
    const b={mod,ov,culture,line:null,d:null,work:null,lvl:0,plan:null,own:{},
             view:state.settings.bld_view==='grid'?'grid':'rows',
             poolFac:new Set(),fixOwnership:true,
             sel:{settlement:new Set(),religion:new Set(),faction:new Set()}};
    // the mod may have been switched away from while this was in flight
    if(state.src===mod)state.bld=b;
    return b;
  })();
  _bldLoading={mod,p};
  try{ return await p; }
  finally{ if(_bldLoading&&_bldLoading.p===p)_bldLoading=null; }
}
async function renderBuildings(){
  let b;
  try{ b=await loadBuildings(); }
  catch(e){ main.innerHTML=`<div class="empty">Couldn't read the buildings of “${esc(state.src)}”.<br>
    <span class="count">${esc(''+e)}</span><br><br>
    <button class="primary" onclick="render()">Retry</button></div>`; return; }
  // the picker moved on while we were loading — whoever it moved to will render
  if(!b||b.mod!==state.src||state.mode!=='buildings')return;
  const ov=b.ov;
  if(!ov.has_file){
    main.innerHTML=`<div class="empty">“${esc(state.src)}” has no
      <code>data/export_descr_buildings.txt</code>.</div>`;
    count.textContent=''; return;
  }
  bldBuildFilters();
  const lines=ov.lines.filter(bldMatches);
  count.textContent=`${lines.length}/${ov.lines.length}`;
  const head=`<div class="faction-head">
      <h2>${esc(state.src)}: buildings</h2>
      <span class="n">${lines.length} line${lines.length===1?'':'s'}, ${
        lines.reduce((n,l)=>n+l.level_count,0)} levels</span>
      ${ov.vanilla_ui?'':'<span class="n w-warn">No unpacked vanilla UI, so missing art shows a placeholder</span>'}
      ${ov.religions_are_vanilla?`<span class="n w-warn"
        title="This mod has no data/descr_religions.txt, so the religion pickers
offer the base game's five. If it defines its own, add that file.">using vanilla’s
        five religions</span>`:''}
      <span style="margin-left:auto;display:flex;gap:6px;align-items:center">
        <span class="viewtoggle">
          <button class="${bldBrowse()==='gallery'?'on':''}" onclick="bldSetBrowse('gallery')"
            title="Cards with each line's finished art">▦ Gallery</button>
          <button class="${bldBrowse()==='tree'?'on':''}" onclick="bldSetBrowse('tree')"
            title="One row per line, its levels folded underneath">▤ Tree</button>
        </span>
        ${(ov.actions||{}).create?`<button class="primary" onclick="bldNewTree()"
          title="Add a whole new building line to this mod">＋ New building tree</button>`:''}
      </span>
    </div>`;
  if(!lines.length){
    main.innerHTML=`<section class="faction-group">${head}
      <div class="empty">No buildings match.</div></section>`;
    return;
  }
  main.innerHTML=`<section class="faction-group">${head}${
    bldBrowse()==='tree'
      ? `<div class="btree">${lines.map(bldTreeRowHtml).join('')}</div>`
      : `<div class="bgrid">${lines.map(bldCardHtml).join('')}</div>`}</section>`;
  main.querySelectorAll('.bcard').forEach(c=>c.onclick=()=>openBuilding(c.dataset.line));
}
/* ---- gallery ⇄ tree ----
   Two ways of reading the same list, and which one is useful depends on what you
   came for. The gallery shows every line's finished picture, which is how you
   recognise a building you have seen in game; the tree shows the whole EDB at
   once — DaC's 136 lines and 499 levels fit on two screens — which is how you
   find the level a unit is trained from. The choice is remembered, because
   nobody wants to re-pick it every launch. */
const bldBrowse=()=>(state.settings.bld_browse==='tree'?'tree':'gallery');
function bldSetBrowse(v){
  state.settings.bld_browse=v; api.post('/api/settings',{bld_browse:v});
  render();
}
// which lines are unfolded, kept on the mod's state so it survives a re-render
// but not a mod switch
const bldOpenTrees=()=>{
  const b=state.bld; if(!b.open)b.open=new Set(); return b.open;
};
function bldTreeToggle(name){
  const open=bldOpenTrees();
  open.has(name)?open.delete(name):open.add(name);
  render();
}
function bldTreeRowHtml(l){
  const open=bldOpenTrees().has(l.name);
  const a=bldCardArt(l),top=l.top_level||l.levels[l.levels.length-1]||'';
  const bits=[BLD_SETTLE_LABEL[l.settlement]||l.settlement,
    `${l.level_count} level${l.level_count===1?'':'s'}`];
  if(l.recruit_count)bits.push(`${l.recruit_count} unit${l.recruit_count===1?'':'s'}`);
  if(l.religion)bits.push(esc(l.religion));
  if(l.convert_to)bits.push('↔ '+esc(l.convert_to));
  const warn=l.missing_units.length
    ? ` <span class="w-bad" title="Named in a recruit pool but not in this mod's EDU: ${
        esc(l.missing_units.join(', '))}">· ${l.missing_units.length} unknown</span>`:'';
  return `<div class="btrow${open?' open':''}" onclick="bldTreeToggle('${q1(esc(l.name))}')">
      <button class="btwist" tabindex="-1">${open?'▾':'▸'}</button>
      <img loading="lazy" onerror="iconRetry(this)" alt="" src="${bldIcon(top,'small',a.culture)}">
      <span class="antxt"><span class="nm">${esc(l.label)}</span>
        <span class="sub">${l.label===l.name?'':esc(l.name)+' · '}${
          bits.join(' · ')}${warn}</span></span>
      <button onclick="event.stopPropagation();openBuilding('${q1(esc(l.name))}')"
        title="Open this line in the editor">Open</button>
    </div>
    ${open?`<div class="btlevels">${l.levels.map((n,i)=>`
      <button class="btlv" onclick="openBuilding('${q1(esc(l.name))}',false,${i})"
        title="Open ${esc(n)}">
        <img loading="lazy" onerror="iconRetry(this)" alt="" src="${bldIcon(n,'small',a.culture)}">
        <span class="t">${esc((l.level_labels||[])[i]||n)}</span>
        <span class="n">${esc(n)}</span></button>`).join('')}</div>`:''}`;
}
function bldCardHtml(l){
  // the last level is the finished building, so its constructed art is the one
  // that says what the line IS at a glance
  const top=l.top_level||l.levels[l.levels.length-1]||'';
  const a=bldCardArt(l);
  const tags=[`<span class="badge">${esc(BLD_SETTLE_LABEL[l.settlement]||l.settlement)}</span>`,
    `<span class="badge">${l.level_count} level${l.level_count===1?'':'s'}</span>`];
  if(l.recruit_count)tags.push(`<span class="badge cls">${l.recruit_count} unit${l.recruit_count===1?'':'s'}</span>`);
  if(l.religion)tags.push(`<span class="badge merc">${esc(l.religion)}</span>`);
  if(l.missing_units.length)tags.push(`<span class="badge" style="color:var(--bad);border-color:var(--bad)"
      title="Named in a recruit pool but not in this mod's EDU: ${esc(l.missing_units.join(', '))}"
      >${l.missing_units.length} unknown</span>`);
  return `<div class="bcard" data-line="${esc(l.name)}">
    <div class="art"><img loading="lazy" onerror="iconRetry(this)" alt=""
        src="${bldIcon(top,'large',a.culture)}">
      ${bldArtBadge(a)}</div>
    <div class="bmeta"><div class="nm">${esc(l.label)}</div>
      <div class="sub">${esc(l.name)}</div>
      <div class="tags">${tags.join('')}</div></div></div>`;
}
// Where the card's picture comes from in the culture being shown: 'mod',
// 'vanilla' or '' for nothing at all. The overview says so per line, so the grid
// never has to ask the server about art it is already displaying.
function bldArtSource(l,culture){
  const a=(l.art||{})[culture||state.bld.culture]||{};
  return a.large||a.small||'';
}
// Most building lines are culture-specific, so with one culture picked the
// majority of the grid would be placeholders for buildings the mod HAS drawn —
// just for someone else. So a line with nothing in the chosen culture borrows
// the art of a culture that does have it, and the badge says whose.
function bldCardArt(l){
  const want=state.bld.culture;
  const own=bldArtSource(l,want);
  if(own)return {culture:want,source:own,borrowed:false};
  for(const c of Object.keys(l.art||{})){
    const s=bldArtSource(l,c);
    if(s)return {culture:c,source:s,borrowed:true};
  }
  return {culture:want,source:'',borrowed:false};
}
/* Whose art the pane is actually showing, said in words rather than as the bare
   token the server sends. "vanilla" on its own reads as a label, not as "this
   mod ships none and the game will fall back". */
function bldArtWhose(src){
  if(src==='mod')return '<span class="w-good">✓ this mod’s own art</span>';
  if(src==='vanilla')return `<span class="w-warn" title="This mod ships no file at
this path, so the game uses the base game's picture. Drop a .tga in to override it."
    >falling back to the vanilla building art</span>`;
  if(src==='vanilla*')return `<span class="w-warn" title="No vanilla art for this
culture either, so another vanilla culture's picture is standing in.">falling back to
    vanilla art from another culture</span>`;
  return '<span class="w-warn">No art anywhere. Showing a placeholder.</span>';
}
function bldArtBadge(a){
  if(a.borrowed)return `<span class="src vanilla"
    title="This mod has no ${esc(state.bld.culture)} art for this building, so its ${esc(a.culture)} art is shown instead."
    >${esc(a.culture)}</span>`;
  if(a.source==='vanilla')return `<span class="src vanilla"
    title="Borrowed from the unpacked vanilla UI. This mod ships no art for it.">vanilla</span>`;
  if(!a.source)return `<span class="src placeholder"
    title="Neither this mod nor the unpacked vanilla UI has art for this building">no art</span>`;
  return '';
}
function bldMatches(l){
  const b=state.bld; if(!b)return true;
  const S=b.sel,qq=search.value.trim().toLowerCase();
  if(qq&&!(l.label.toLowerCase().includes(qq)||l.name.toLowerCase().includes(qq)
      ||l.levels.some(x=>x.toLowerCase().includes(qq))
      ||(l.level_labels||[]).some(x=>x.toLowerCase().includes(qq))))return false;
  if(S.settlement.size&&!S.settlement.has(l.settlement))return false;
  if(S.religion.size&&!S.religion.has(l.religion||'(none)'))return false;
  if(S.faction.size&&!l.factions.some(f=>S.faction.has(f)))return false;
  if(bldRecruitOnly.checked&&!l.recruit_count)return false;
  // "missing its own art" = the mod ships nothing for it in ANY culture
  if(bldMissingArt.checked&&Object.values(l.art||{}).some(a=>a.small==='mod'||a.large==='mod'))
    return false;
  return true;
}
let _bldFiltersFor='';
function bldBuildFilters(){
  const b=state.bld,ov=b.ov,key=b.mod+'|'+b.culture;
  if(_bldFiltersFor===key)return;                 // only rebuild when the mod changes
  _bldFiltersFor=key;
  bldCulture.innerHTML=(ov.cultures||[]).map(c=>
    `<option value="${esc(c)}" ${c===b.culture?'selected':''}>${esc(c)}</option>`).join('')
    ||'<option value="">(no culture folders)</option>';
  bldCulture.onchange=()=>{bldSetCulture(bldCulture.value);};
  const religions=[...new Set(ov.lines.map(l=>l.religion||'(none)'))].sort();
  bldReligionFilter.innerHTML=religions.map(r=>
    `<label class="opt"><input type="checkbox" value="${esc(r)}">${esc(r)}</label>`).join('');
  const factions=[...new Set(ov.lines.flatMap(l=>l.factions))]
    .sort((a,b2)=>bldFacLabel(a).localeCompare(bldFacLabel(b2)));
  bldFactionFilter.innerHTML=factions.map(f=>
    `<label class="opt"><input type="checkbox" value="${esc(f)}">${esc(bldFacLabel(f))}</label>`).join('')
    ||'<span class="count">None</span>';
  const wire=(box,key2)=>box.querySelectorAll('input').forEach(cb=>cb.onchange=()=>{
    cb.checked?b.sel[key2].add(cb.value):b.sel[key2].delete(cb.value); render();});
  wire(bldReligionFilter,'religion'); wire(bldFactionFilter,'faction');
  document.querySelectorAll('.bldset').forEach(cb=>cb.onchange=()=>{
    const b2=state.bld; if(!b2)return;
    cb.checked?b2.sel.settlement.add(cb.value):b2.sel.settlement.delete(cb.value);
    render();});
  bldRecruitOnly.onchange=render;
  bldMissingArt.onchange=render;
  paintFilterFolds();
}
// A `requires factions { … }` clause names factions AND cultures; only the
// factions have an in-game name to show alongside the code.
function bldFacLabel(f){
  return state.factionNames[f]?facTwoNames(f,state.factionNames[f]):f;
}
/* ---------- the building editor ----------
   `atLevel` opens straight at one level rather than at the first: the tree list
   lists the levels, so clicking one has to land on it. `keepLevel` is the
   re-read after a Save, which stays where it was. */
async function openBuilding(name,keepLevel,atLevel){
  activity('opened building',`${name} in ${state.src}`);
  const modal=document.getElementById('modal');
  modal.className='modal wide'; modal.innerHTML='<h2>Loading building…</h2>';
  overlay.classList.add('open');
  let d;
  // the overview holds the culture list and the capability vocabulary the editor
  // needs; a save or a mod switch can leave it not yet loaded
  try{ await loadBuildings(); }
  catch(e){ modal.innerHTML=`<h2>Building</h2><div class="mbody w-bad">${esc(''+e)}</div>
    <div class="foot"><button onclick="closeModal()">Close</button></div>`; return; }
  try{ d=await api.get(`/api/building?mod=${enc(state.src)}&line=${enc(name)}`
                       +`&culture=${enc((state.bld&&state.bld.culture)||'')}`); }
  catch(e){ modal.innerHTML=`<h2>Building</h2><div class="mbody w-bad">${esc(''+e)}</div>
    <div class="foot"><button onclick="closeModal()">Close</button></div>`; return; }
  const b=state.bld;
  b.line=name; b.d=d; b.plan=null; b.locSel=null;
  if(typeof atLevel==='number')b.lvl=Math.max(0,Math.min(atLevel,d.levels.length-1));
  else if(!keepLevel)b.lvl=0;
  // a different line (or a re-read after saving) means a different block of text
  cvDrop(b.cv); b.cv=null;
  // The working copy the form edits. Everything is sent on save and the server
  // skips whatever still matches the file, so the page never has to diff.
  // `locAll` is every culture's name/description keyed by culture ('' = the
  // shared key), so the culture picker never has to go back to the server.
  b.work=bldWorkFrom(d);
  b.orig=JSON.stringify(b.work);
  b.checks=null;
  bldLoadChecks();
  b.own=b.own||{};                        // unit type -> ownership check result
  undoReset();
  // a re-read after Save keeps the level, so it keeps where you were scrolled
  // too; opening a different building starts at the top
  if(!keepLevel)resetPlace();
  renderBuildingEditor();
  // the code pane is remembered across records and modules; fetched after the
  // first paint so it never delays the dialog
  if(state.settings.code_view){
    b.cv=cvCreate(bldCvHost());
    cvLoad(b.cv).then(()=>{
      if(state.bld!==b||!b.cv)return;
      bldCvAdoptLoad(b.cv);
      renderBuildingEditor();
    });
  }
}
/* ---- which of a level's per-culture names is the one on show ----
   The same fallback the server uses (buildings._best_loc), redone here so the
   editor stays live when the culture picker moves: the culture's own key wins,
   then the shared key, then whichever culture DOES have text — a shared key
   whose value is just the key itself is a placeholder, not a name. */
function bldLocPlaceholder(rec){
  const n=((rec&&rec.name)||'').trim();
  return !n||n===(rec&&rec.key);
}
function bldLocCulture(lv,culture){
  const all=lv.locAll||{};
  const order=[culture,''].filter(c=>c in all)
    .concat(Object.keys(all).filter(c=>c&&c!==culture));
  for(const c of order) if(!bldLocPlaceholder(all[c]))return c;
  return culture in all?culture:'';
}
function bldLevelLabel(i){
  const b=state.bld, lv=b.work&&b.work.levels[i];
  if(!lv)return (b.d.levels[i]||{}).label||'';
  const rec=(lv.locAll||{})[bldLocCulture(lv,b.culture)]||{};
  return ((rec.name||'').trim())||lv.name;
}
// `conds` is the structured form of `requires`; `condEdited` says whether it has
// been touched. Only a touched clause is sent back as structure — an untouched
// one goes back as its original text, so the server never re-emits (and quietly
// tidies) a clause nobody edited.
/* The working copy the form edits, built from a /api/building detail payload.
   Everything is sent on save and the server skips whatever still matches the
   file, so the page never has to diff. `locAll` is every culture's
   name/description keyed by culture ('' = the shared key), so the culture picker
   never has to go back to the server.

   Its own function because Code View rebuilds it too: re-reading hand-edited
   text hands back a detail payload of exactly this shape, and the boxes have to
   come from that rather than from the file. */
function bldWorkFrom(d){
  const work={levels:d.levels.map(lv=>({
      name:lv.name, settlement:lv.settlement, requires:lv.requires,
      conds:JSON.parse(JSON.stringify(lv.conditions||[])), condEdited:false,
      scalars:Object.assign({},lv.scalars), upgrades:lv.upgrades.slice(),
      // the same list as name + conditions, so an upgrade's own clause can be
      // edited with the same picker as everything else. The strings above stay
      // the thing a save sends; these write back into them.
      upgConds:(lv.upgrade_paths||[]).map(u=>JSON.parse(JSON.stringify(u.conditions||[]))),
      locAll:JSON.parse(JSON.stringify(lv.loc_all||{'':Object.assign({present:true},lv.loc)})),
      caps:lv.capabilities.map(c=>bldCapCopy(c,false)),
      fcaps:lv.faction_capabilities.map(c=>bldCapCopy(c,true))}))};
  // Edits staged against OTHER building lines — the castle twin of this one, or
  // every tree that trains some unit. Kept inside `work` so dirty-tracking, undo
  // and Save pick them up with no special case: {line: {level: [rows]}}.
  work.also={};
  return work;
}
function bldCapCopy(c,faction){
  return {line:c.line,keyword:c.keyword,args:c.args,requires:c.requires,
          conds:JSON.parse(JSON.stringify(c.conditions||[])),condEdited:false,
          bonus:c.bonus,value:c.value,pool:c.pool?Object.assign({},c.pool):null,
          comment:c.comment,faction:faction,del:false};
}
function bldDirty(){
  const b=state.bld;
  return !!(b&&b.work&&(JSON.stringify(b.work)!==b.orig||bldCvEdited()));
}

/* ======================= CODE VIEW on the building editor =================
   The same widget the unit editor uses (web/js/codeview.js), pointed at the
   `edb` kind: the whole `building … { … }` block beside the form, hover-linked
   both ways, and hand-editable.

   A building line is a tree, not a field list, so re-reading hand-edited text
   hands back a whole detail payload and the form is rebuilt from it. And once
   the pane has done that, the save must go through the text FOREVER after —
   `bldCvOwns` — because the capability rows now carry line numbers relative to
   the pane's text rather than to the file, and planning those against the whole
   EDB would edit the wrong lines. */
const bldCvEdited=()=>{const cv=state.bld&&state.bld.cv;
  return !!(cv&&cv.loaded&&cv.base!==cv.pristine);};
const bldCvOwns=()=>{const cv=state.bld&&state.bld.cv; return !!(cv&&cv.owns);};
function bldCvBlocked(){
  const cv=state.bld&&state.bld.cv;
  if(!cv||!cv.err)return '';
  return 'The code view can’t be read: '+cv.err+
    ' Fix it, or undo your typing, before saving.';
}
function bldCvToggleHtml(){
  return `<button class="${state.bld.cv?'on':''}" title="Show this building line exactly as
export_descr_buildings.txt stores it, beside the form. Hover a box to light up its
line; edit either side and the other follows."
    onclick="bldCvToggle()">&lt;/&gt; Code view</button>`;
}
async function bldCvToggle(){
  const b=state.bld;
  if(b.cv){cvDrop(b.cv); b.cv=null; state.settings.code_view=false;
    api.post('/api/settings',{code_view:false}); renderBuildingEditor(); return;}
  state.settings.code_view=true; api.post('/api/settings',{code_view:true});
  b.cv=cvCreate(bldCvHost());
  renderBuildingEditor();
  await cvLoad(b.cv);
  if(state.bld!==b||!b.cv)return;
  bldCvAdoptLoad(b.cv);
  renderBuildingEditor();
}
function bldCvHost(){
  const b=state.bld;
  return {kind:'edb', mod:b.mod, id:b.line,
    where:'data/export_descr_buildings.txt',
    culture:()=>state.bld.culture||'',
    edits:()=>bldPayload(),
    adopt:cv=>{const s=state.bld;
      if(!cv.detail)return;
      s.d=cv.detail;
      // the level on screen may have been renamed or removed by the typing
      s.work=bldWorkFrom(cv.detail);
      s.lvl=Math.min(s.lvl,Math.max(0,s.work.levels.length-1));
      s.orig=JSON.stringify(s.work);},
    refreshGui:()=>bldCvRefresh(),
    label:bldCvLabel, find:bldCvFind};
}
/* The form is rebuilt from the pane the moment the pane arrives, before anything
   has been typed. That is not busywork: a capability row carries the LINE it sits
   on, and /api/building counts those from the top of the 30 000-line EDB while the
   pane counts them from the top of the block. Two conventions on one screen is a
   bug waiting for the first capability edit, so the pane's parse becomes the only
   one — and from then on the save goes through the pane's text (`owns`), which is
   the only text those numbers mean anything against.

   Box edits made while the pane was still loading are left alone; the pane simply
   doesn't take over in that case. */
function bldCvAdoptLoad(cv){
  const b=state.bld;
  if(!b||!cv||!cv.detail||cv.err)return;
  if(JSON.stringify(b.work)!==b.orig)return;
  b.d=cv.detail;
  b.work=bldWorkFrom(cv.detail);
  b.lvl=Math.min(b.lvl,Math.max(0,b.work.levels.length-1));
  b.orig=JSON.stringify(b.work);
  cv.owns=true;
}
// A redraw of the form only — never of the pane, which has the caret in it.
function bldCvRefresh(){
  const b=state.bld;
  if(!b||!b.work)return;
  const lv=b.work.levels[b.lvl],orig=b.d.levels[b.lvl];
  if(!lv||!orig)return;
  bldRenderBody(lv,orig);
  cvBindHover(b.cv,document.getElementById('bldGui'));
  paintDirty();
}
/* Which span the hovered element belongs to. The form's rows are `data-scalar`,
   `data-settlement` and `data-cap` — adding a second set of attributes to a
   three-thousand-line file would be churn, so the mapping lives here instead
   (codeview.js takes `label`/`find` from the host for exactly this). */
function bldCvLabel(el){
  const b=state.bld;
  if(!b||!b.work||!el||!el.closest)return '';
  const lv=b.work.levels[b.lvl]; if(!lv)return '';
  const key='level:'+lv.name;
  const cap=el.closest('[data-cap]');
  if(cap){
    const row=bldCapList()[+cap.dataset.cap];
    return (row&&row.line!=null)?'capline#'+row.line:key;
  }
  let f=el.closest('[data-scalar],[data-settlement]');
  // hovering the words beside a box counts as hovering the box
  if(!f&&el.nextElementSibling&&el.nextElementSibling.matches
     &&el.nextElementSibling.matches('[data-scalar],[data-settlement]'))
    f=el.nextElementSibling;
  if(f)return f.hasAttribute('data-settlement')?key+':header'
       :key+':'+(f.dataset.scalar||'');
  if(el.closest('.clausebar'))return key+':header';
  if(el.closest('#bldUpg'))return key+':upgrades';
  // anywhere else in the form: light the level this form IS
  return el.closest('#bldBody')?key:'';
}
function bldCvFind(label){
  const b=state.bld;
  if(!b||!b.work)return [];
  const lv=b.work.levels[b.lvl]; if(!lv)return [];
  const m=/^capline#(\d+)$/.exec(label);
  if(m){
    const i=bldCapList().findIndex(c=>String(c.line)===m[1]);
    const el=i<0?null:document.querySelector(`#bldBody [data-cap="${i}"]`);
    return el?[el]:[];
  }
  const pre='level:'+lv.name;
  if(label===pre+':header')
    return [...document.querySelectorAll('#bldBody [data-settlement],#bldBody .clausebar')];
  if(label===pre+':upgrades'){const u=document.getElementById('bldUpg');return u?[u]:[];}
  if(label.startsWith(pre+':')){
    const el=document.querySelector(
      `#bldBody [data-scalar="${cssq(label.slice(pre.length+1))}"]`);
    return el?[el]:[];
  }
  return [];
}
function bldLevelDirty(i){
  const b=state.bld;
  if(!b||!b.orig)return false;
  return JSON.stringify(b.work.levels[i])!==JSON.stringify(JSON.parse(b.orig).levels[i]);
}
function renderBuildingEditor(){
  const b=state.bld,d=b.d;
  const lv=b.work.levels[b.lvl],orig=d.levels[b.lvl];
  document.getElementById('modal').innerHTML=`
    <h2>Building line <span class="pill">${esc(b.mod)}</span></h2>
    <div class="ehead">
      <img style="width:74px;height:60px" onerror="iconRetry(this)"
        src="${bldIcon(d.levels[d.levels.length-1].name,'small')}">
      <div><div class="nm">${esc(d.label)}</div>
        <div class="count"><code>${esc(d.name)}</code> · ${esc(BLD_SETTLE_LABEL[d.settlement]||d.settlement)}
          · ${d.levels.length} level${d.levels.length===1?'':'s'}${
          d.convert_to?` · converts to <code>${esc(d.convert_to)}</code>`:''}${
          d.religion?` · religion <b>${esc(d.religion)}</b>`:''}</div>
        <div class="count">Defined in <code>data/export_descr_buildings.txt</code>${
          d.plugins.length?` · ${d.plugins.length} plugin(s): ${esc(d.plugins.map(p=>p.name).join(', '))}`:''}</div></div>
      <span id="bldVarBtn">${bldVarBtnHtml()}</span>
    </div>
    <div class="lvstrip">${d.levels.map((l,i)=>`
      <div class="lvchip ${i===b.lvl?'on':''} ${bldLevelDirty(i)?'dirty':''}" onclick="bldPickLevel(${i})">
        <img loading="lazy" onerror="iconRetry(this)" src="${bldIcon(l.name,'small')}" alt="">
        <div class="t" title="${esc(bldLevelLabel(i))} (${esc(l.name)})">${esc(bldLevelLabel(i))}</div>
        <div class="n">${l.capabilities.filter(c=>c.pool).length} units</div>
      </div>`).join('')}</div>
    <div class="cvsplit${b.cv?'':' off'}" style="padding:0 14px">
      <div id="bldGui"><div class="mbody" id="bldBody" style="padding:0"></div></div>
      ${b.cv?`<div id="bldCodeCol" style="padding-top:12px">${cvHtml(b.cv)}</div>`:''}
    </div>
    <div class="foot">
      <span class="count" id="bldDirtyNote"></span>
      ${bldCvToggleHtml()}
      <span class="count" title="Takes back one value at a time, without closing this dialog">
        ⌨ Ctrl+Z undo · Ctrl+Y redo</span>
      <label class="chk" style="margin-right:auto" title="A recruit pool can name a faction the unit itself doesn't belong to, and the building then trains nothing for them, silently. With this on, saving adds the missing EDU ownership and copies the missing battle-model textures from a faction that has them.">
        <input type="checkbox" id="bldFixOwn" ${b.fixOwnership!==false?'checked':''}
          onchange="state.bld.fixOwnership=this.checked;bldDirtyNote()">
        Fix unit <b>ownership</b> to match</label>
      ${cleanerBoxHtml('building')}
      <button onclick="bldClose()">Close</button>
      <button onclick="bldPreview()">Preview</button>
      <button class="primary" onclick="bldSave()">Save changes</button>
    </div>`;
  bldRenderBody(lv,orig);
  if(b.cv){cvWire(b.cv); cvBindHover(b.cv,document.getElementById('bldGui'));}
}
/* The way into the city/castle comparison, big and top right where the thing
   it compares is named. The twin is worked out server-side and arrives with the
   checks, so the button knows whether there is anything on the other side before
   it is pressed: a line buildable in both settlement types has no other half,
   and the button says so instead of opening an empty panel. */
function bldVarBtnHtml(){
  const b=state.bld,twin=bldTwin();
  if(!twin)
    return `<button class="vcbtn" disabled title="A city/castle pair is matched by name
(barracks against castle_barracks, stables against c_stables). This line has no
counterpart the tool can match \u2014 usually because it is buildable in both
settlement types already.">\u21c4 No city/castle twin</button>`;
  const ck=b.checks||{};
  const gaps=(ck.mirror||[]).reduce((n,m)=>n+m.only_here.length+m.only_there.length,0);
  return `<button class="vcbtn primary" onclick="bldCompareVariants()"
    title="Put this building beside its ${esc(b.d.settlement==='city'?'castle':'city')} half,
tier by tier, and close any unit one of them trains and the other does not.">
    \u21c4 Compare city / castle${gaps?` <span class="badge warn">${gaps}</span>`:''}</button>`;
}
function bldPickLevel(i){
  const b=state.bld; b.lvl=i; b.plan=null;
  // the ticks belong to the level they were made on — every row here is a
  // different object, and carrying a stale selection across only confuses
  if(b.bulk)b.bulk.sel.clear();
  renderBuildingEditor();
}
function bldClose(){
  if(bldDirty()&&!confirm('Close without saving your building changes?'))return;
  cvDrop(state.bld.cv); state.bld.cv=null;
  state.bld.line=null; state.bld.d=null; state.bld.work=null;
  closeModal();
}
function bldRenderBody(lv,orig){
  const b=state.bld,ov=b.ov;
  const body=document.getElementById('bldBody');
  /* The form is not always the thing in the dialog. Every panel that takes the
     modal over — Add units, the per-unit comparison, the city/castle comparison
     — leaves `#bldBody` out of the document, and a repaint aimed at it then
     threw on a null. That throw came out of an onclick, so it killed the click
     that caused it and everything after it: the page stopped responding, which
     is what "the tool crashed" looks like from the outside.

     Every caller is a change to the working copy, and the working copy is what
     the form is rebuilt from when the panel closes. So there is nothing to do
     here, and doing nothing is correct rather than merely safe. */
  if(!body)return;
  const scroll=body.scrollTop;
  // The pool and capability lists are scrollers of their OWN inside the body, so
  // putting the body back where it was is not enough: ticking a unit two hundred
  // rows down redrew the list and threw you back to the top of it.
  const scrollOf=id=>{const el=document.getElementById(id);return el?el.scrollTop:0;};
  const inner=[['bldPools',scrollOf('bldPools')],['bldCaps',scrollOf('bldCaps')]];
  const art=orig.art[b.culture]||{};
  const sel=(key,list,cur,blank)=>`<select data-scalar="${key}">
      ${blank?`<option value="">${esc(blank)}</option>`:''}
      ${list.map(v=>`<option value="${esc(v)}" ${v===cur?'selected':''}>${esc(v)}</option>`).join('')}
      ${cur&&!list.includes(cur)?`<option value="${esc(cur)}" selected>${esc(cur)} (custom)</option>`:''}
    </select>`;
  const pools=[...lv.caps,...lv.fcaps].filter(c=>c.pool);
  const plain=[...lv.caps,...lv.fcaps].filter(c=>!c.pool);
  const shown=pools.filter(bldPoolMatches);
  body.innerHTML=`
    <div class="bsec"><h4>Art <span class="count">Culture: ${esc(b.culture||'none')}</span></h4>
      <div class="bart">
        <figure class="small"><img onerror="iconRetry(this)" src="${bldIcon(orig.name,'small')}">
          <figcaption>#${esc(b.culture)}_${esc(orig.name)}.tga<br>
            ${bldArtWhose(art.small)}</figcaption></figure>
        <figure class="large"><img onerror="iconRetry(this)" src="${bldIcon(orig.name,'large')}">
          <figcaption>#${esc(b.culture)}_${esc(orig.name)}_constructed.tga<br>
            ${bldArtWhose(art.large)}</figcaption></figure>
        <div style="flex:1;min-width:180px">
          <div class="bnote">Cultures with art for this level:</div>
          <div class="tags" style="margin-top:5px">${Object.keys(orig.art).length
            ? Object.keys(orig.art).map(c=>`<span class="badge ${c===b.culture?'cls':''}"
                style="cursor:pointer" onclick="bldSetCulture('${q1(esc(c))}')">${esc(c)}</span>`).join('')
            : '<span class="count">None. Every culture falls back to the placeholder.</span>'}</div>
        </div>
      </div></div>

    ${bldLocSection(lv,orig)}

    <div class="bsec"><h4>Stats</h4>
      <div class="brow"><span class="k">${qm('What the settlement pays to put this level up, in florins. Written as the level\'s `cost` line.','Cost')}Cost</span>
        ${numBox('data-scalar="cost"',lv.scalars.cost||'','100')}
        <span class="k" style="flex:0 0 88px">${qm('How many turns construction takes once it is queued. The level\'s `construction` line.','Turns to build')}Turns to build</span>
        ${numBox('data-scalar="construction"',lv.scalars.construction||'','1')}</div>
      <div class="brow"><span class="k">${qm('Which building model the settlement shows on the battle map: wooden or stone. Purely visual, but a stone building in a wooden settlement looks wrong.','Material')}Material</span>${sel('material',ov.materials,lv.scalars.material||'','(unset)')}
        <span class="k" style="flex:0 0 88px">${qm('Index (0-based) of the level in the opposite city/castle line that this one becomes when the settlement is converted.','Convert to')}Convert to</span>
        ${numBox('data-scalar="convert_to"',lv.scalars.convert_to||'','1')}</div>
      <div class="brow"><span class="k">${qm('The smallest settlement size that may build this level. Below it the building is not offered at all.','Settlement min')}Settlement min</span>${sel('settlement_min',ov.settlement_levels,lv.scalars.settlement_min||'','(unset)')}
        <span class="k" style="flex:0 0 88px">${qm('The largest settlement size that may build this level. Leave it unset for no ceiling.','Settlement max')}max</span>${sel('settlement_max',ov.settlement_levels,lv.scalars.settlement_max||'','(none)')}</div>
      <div class="brow"><span class="k">${qm('Whether this level belongs to cities, to castles, or to both. It pins the level to one settlement type; leaving it open means either can build it.','Buildable in')}Buildable in</span>
        <select data-settlement>
          <option value="" ${lv.settlement===''?'selected':''}>City and castle</option>
          <option value="city" ${lv.settlement==='city'?'selected':''}>City only</option>
          <option value="castle" ${lv.settlement==='castle'?'selected':''}>Castle only</option>
        </select></div>
      <div class="brow"><span class="k">${qm('Everything that has to be true before this level can be built: which factions, which events, which resources. Every term names something declared elsewhere in the mod, and a typo is silent: the building simply never becomes available.','Requires')}Requires</span>
        <div class="clausebar">
          <div class="sum">${bldClauseSummary(lv.conds)}</div>
          <button class="reqbtn" onclick="bldEditClause('level')">✎ Edit requirements</button>
        </div></div>
      ${bldRequiresHelp()}</div>

    ${bldUpgradesSection(lv,orig)}

    <div class="bsec"><h4>Recruitment <span class="n">${shown.length}</span>
        <span class="count">of ${pools.filter(p=>!p.del).length}</span>
        ${bldPoolFilterHtml(pools)}
        <div class="viewtoggle" style="margin-left:auto">
          <button class="${b.view!=='grid'?'on':''}" onclick="bldSetView('rows')">▤ Rows</button>
          <button class="${b.view==='grid'?'on':''}" onclick="bldSetView('grid')">▦ Grid</button>
        </div>
        <button style="margin-left:0" class="${bldBulkOn()?'on':''}" onclick="bldBulkToggle()"
          title="Tick several units and give them all the same requirements, numbers or removal at once"
          >☑ Bulk edit</button>
        <button class="primary" onclick="bldAddPoolDialog()">＋ Add unit</button></h4>
      ${bldBulkBar(shown)}
      ${bldPressureHtml(lv)}
      ${b.view==='grid'
        ? `<div class="ugrid" id="bldPools">${shown.length?shown.map(bldPoolCard).join('')
            :'<span class="count">Nothing matches.</span>'}</div>`
        : `<div class="poollist" id="bldPools">${shown.length?shown.map(bldPoolRow).join('')
            :'<div class="poolrow"><span class="count">'
             +(pools.length?'Nothing matches this filter.':'This level trains nothing.')
             +'</span></div>'}</div>`}</div>

    <div class="bsec"><h4>Other capabilities <span class="n">${plain.filter(c=>!c.del).length}</span>
        <button onclick="bldAddCap()">＋ Add capability</button></h4>
      <div class="caplist" id="bldCaps">${plain.length?plain.map(bldCapRow).join('')
        :'<div class="caprow"><span class="count">None.</span></div>'}</div>
      ${lv.fcaps.length?'<div class="bnote">Rows marked <b>faction</b> live in this level’s '
        +'<code>faction_capability</code> block, so they apply to the whole faction, not just the settlement.</div>':''}</div>

    ${bldChecksHtml()}
    ${bldAlsoHtml()}

    <div id="bldPlan"></div>`;
  if(b.plan)document.getElementById('bldPlan').innerHTML=bldPlanHtml(b.plan,b.planStale);
  bldWire();
  if(body&&scroll)body.scrollTop=scroll;
  inner.forEach(([id,top])=>{
    const el=document.getElementById(id); if(el&&top)el.scrollTop=top;});
  paintDirty();
}
/* ---- name & description, per culture ----
   One level can be called something different for every culture — Warg Breeder
   for the orcs, Stables for everyone else — and DaC does exactly that for its
   whole EDB, leaving the shared key a "DO NOT TRANSLATE" placeholder. So the
   editor picks a culture the way the game does, and writing to one culture
   leaves the others alone. */
function bldLocSel(){
  const b=state.bld,lv=b.work.levels[b.lvl];
  const s=b.locSel;
  return (s!=null&&s in (lv.locAll||{}))?s:bldLocCulture(lv,b.culture);
}
function bldLocRec(){
  const lv=state.bld.work.levels[state.bld.lvl];
  const c=bldLocSel();
  return (lv.locAll||{})[c]||(lv.locAll[c]={key:c?lv.name+'_'+c:lv.name,present:false,
                                            name:'',descr:'',descr_short:''});
}
function bldLocPick(c){ state.bld.locSel=c; bldTouched(); }
function bldLocSection(lv,orig){
  const b=state.bld,cur=bldLocSel(),rec=bldLocRec();
  const all=lv.locAll||{};
  const named=c=>{
    const r=all[c]||{};
    const tag=c===''?'shared (every culture)':c;
    return `${tag}${bldLocPlaceholder(r)?' (no text)':''}`;
  };
  const owner=bldLocCulture(lv,b.culture);
  return `<div class="bsec"><h4>Name &amp; description
      <span class="count">text/export_buildings.txt</span>
      <span style="margin-left:auto;display:flex;align-items:center;flex:0 0 auto">
      ${qm('Which key in export_buildings.txt these three boxes edit. A level can be named once for everyone and again for each culture; the game shows a faction the key for ITS culture and falls back to the shared one. Editing one culture leaves the others exactly as they were.','Culture')}
      <select class="mini" style="flex:0 0 auto;max-width:250px"
        onchange="bldLocPick(this.value)">
        ${Object.keys(all).map(c=>`<option value="${esc(c)}" ${c===cur?'selected':''}
          >${esc(named(c))}</option>`).join('')}
      </select></span></h4>
      <div class="brow"><span class="k">${qm('The name shown on the building browser and the construction panel. Written as {'+rec.key+'}.','Name')}Name</span>
        <input data-loc="name" value="${esc(rec.name)}" placeholder="${esc(orig.name)}"></div>
      <div class="brow"><span class="k">${qm('The one-line summary under the building in the construction panel. Written as {'+rec.key+'_desc_short}.','Short description')}Short description</span>
        <input data-loc="descr_short" value="${esc(rec.descr_short)}"></div>
      <div class="brow"><span class="k">${qm('The full text on the building\'s info scroll. Written as {'+rec.key+'_desc}. A building needs all three keys or the game crashes on load, so saving a name writes all three.','Description')}Description</span>
        <textarea data-loc="descr" style="flex:1;min-height:56px;padding:4px 7px;font-size:12.5px"
          >${esc(rec.descr)}</textarea></div>
      <div class="bnote">Editing <code>{${esc(rec.key)}}</code>${rec.present?''
        :'. <b>New</b>: this key is not in the file yet'}. ${
        cur===b.culture?`This is the culture the browser is showing.`
        :cur===''?`Shown to any culture that has no key of its own.`
        :`The browser is showing <b>${esc(b.culture||'the shared key')}</b>, which reads its name from
          <code>{${esc((all[owner]||{}).key||lv.name)}}</code>.`}</div></div>
`;
}
/* ---- can this building offer one faction too many units? ----
   M2TW's recruitment panel holds a limited number of units per building; past it
   the panel overflows and the game can crash on opening the settlement. That is
   a failure you only meet on the one save where enough conditions have lined up
   at once, so it is worth being told about while editing.

   The JS twin of buildings.recruitment_pressure, recomputed from the working
   copy so the count tracks pools as they are added, removed and re-gated.

   Two numbers, because they answer different questions. `always` is pools the
   faction gets with NO further condition — if that is over the limit the
   building is already broken. `most` assumes every event counter, hidden
   resource and settlement size holds at the same time; it is an upper bound on
   purpose, since which of a mod's conditions can truly coincide is not
   answerable from the EDB alone. */
function bldRecruitPressure(lv){
  const ov=state.bld.ov,fc=ov.faction_cultures||{},limit=ov.recruit_limit||32;
  const every=Object.keys(fc);
  const cultures=new Set(Object.values(fc));
  const ALL=(bldVocab().all_keyword||'all').toLowerCase();
  const most={},always={};
  [...lv.caps,...lv.fcaps].forEach(c=>{
    if(c.del||!c.pool)return;
    const conds=c.conds||[];
    const facs=conds.filter(x=>x.kind==='factions'&&!x.negate).flatMap(x=>x.values||[]);
    const gated=conds.some(x=>x.kind!=='factions');
    let who;
    if(!facs.length||facs.some(f=>(f||'').toLowerCase()===ALL))who=every;
    else{
      const s=new Set();
      facs.forEach(f=>{
        if(cultures.has(f))every.forEach(k=>{if(fc[k]===f)s.add(k);});
        else s.add(f);
      });
      who=[...s];
    }
    who.forEach(f=>{most[f]=(most[f]||0)+1; if(!gated)always[f]=(always[f]||0)+1;});
  });
  const rows=Object.keys(most)
    .filter(f=>most[f]>limit||(always[f]||0)>limit)
    .map(f=>({faction:f,most:most[f],always:always[f]||0}));
  rows.sort((a,b)=>b.always-a.always||b.most-a.most||a.faction.localeCompare(b.faction));
  return {limit,rows};
}
function bldPressureHtml(lv){
  const p=bldRecruitPressure(lv);
  if(!p.rows.length)return '';
  const hard=p.rows.filter(r=>r.always>p.limit);
  const rows=p.rows.slice(0,10).map(r=>`<div class="prow2 ${r.always>p.limit?'bad':''}">
      <span class="pf">${esc(bldFacLabel(r.faction))}</span>
      <span class="pn">${r.most}</span>
      <span class="pd">${r.always>p.limit
        ? `<b>${r.always}</b> of them with no condition at all`
        : `${r.always} unconditional · the rest need every gate to line up`}</span>
    </div>`).join('');
  return `<div class="ownwarn ${hard.length?'bad':''}" style="margin:0 0 8px">
    <b>${hard.length?'Over the recruitment limit.':'Could go over the recruitment limit.'}</b>
    M2TW shows at most <b>${p.limit}</b> units per building in a settlement's
    recruitment panel; past that the panel overflows and the game can crash on
    opening it.
    ${hard.length?'':`These counts assume every event counter, hidden resource and
      settlement condition holds <i>at the same time</i>. It is an upper bound, so it may
      never actually happen. The unconditional count is the one that always does.`}
    <div class="plist">${rows}</div>
    ${p.rows.length>10?`<div class="count">…and ${p.rows.length-10} more faction(s).</div>`:''}
  </div>`;
}
function bldRequiresHelp(){
  const lv=state.bld.work.levels[state.bld.lvl];
  const txt=bldClauseText(lv.conds);
  return `<div class="bnote">${txt
    ? `Written into the EDB as <code>requires ${esc(txt)}</code>`
    : 'No conditions. Anyone can build this, at any time.'}</div>`;
}
// Switching culture changes both the art and the NAMES, and the names come from
// the server — so the grid is re-fetched. The open editor is not: it already
// holds every culture's text (`loc_all`), and re-fetching would throw away
// whatever has been typed into it.
async function bldSetCulture(c){
  const b=state.bld;
  b.culture=c; state.settings.bld_culture=c;
  api.post('/api/settings',{bld_culture:c});
  bldCulture.value=c; _bldFiltersFor='';
  if(b.d){ b.locSel=null; renderBuildingEditor(); }
  try{
    const ov=await api.get('/api/buildings?mod='+enc(b.mod)+'&culture='+enc(c));
    if(state.bld===b&&b.culture===c)b.ov=ov;    // keep any open editor's working copy
  }catch(e){}
  render();
}
// index into the level's combined cap list, so one data attribute addresses both
// the capability and the faction_capability arrays
function bldCapList(){
  const b=state.bld;
  const lv=b&&b.work&&b.work.levels[b.lvl];
  return lv?[...lv.caps,...lv.fcaps]:[];
}
/* ---- which recruit pools are shown ----
   A big level trains hundreds of units, almost all of them gated to one faction,
   so "who can train what here" is the question you actually arrive with. */
function bldPoolMatches(c){
  const sel=state.bld.poolFac;
  if(!sel||!sel.size)return true;
  const facs=(c.conds||[]).filter(x=>x.kind==='factions'&&!x.negate)
    .flatMap(x=>x.values||[]);
  if(!facs.length)return sel.has('(any)');      // no clause = anyone can train it
  const all=(bldVocab().all_keyword)||'all';
  if(facs.includes(all))return true;
  return facs.some(f=>sel.has(f));
}
function bldPoolFilterHtml(pools){
  const sel=state.bld.poolFac||new Set();
  const counts=new Map();
  let open=0;
  const all=(bldVocab().all_keyword)||'all';
  pools.forEach(c=>{
    const facs=(c.conds||[]).filter(x=>x.kind==='factions'&&!x.negate)
      .flatMap(x=>x.values||[]);
    if(!facs.length){open++;return;}
    new Set(facs).forEach(f=>counts.set(f,(counts.get(f)||0)+1));
  });
  // By unit count first, because "who trains the most here" is the question the
  // list is usually scanned for. A long roster is easier to FIND a name in
  // alphabetically, so the order is a remembered choice rather than a ruling.
  //
  // That choice used to be an entry in this very drop-down, which made it a
  // filter you had to pick to un-pick: choosing it closed the list, and the
  // sorted list only appeared when you opened it again. It is a button beside
  // the list now, so the order changes with the list still in front of you.
  const az=bldFacSort()==='az';
  const rows=[...counts.entries()].sort(az
    ? (a,b)=>bldFacName(a[0]).localeCompare(bldFacName(b[0]))
    : (a,b)=>b[1]-a[1]||a[0].localeCompare(b[0]));
  if(!rows.length&&!open)return '';
  const picked=sel.size
    ? [...sel].map(f=>f==='(any)'?'anyone':bldFacName(f)).join(', ').slice(0,40)
    : 'any';
  return qm('Narrow the list below to the units one faction can actually train here. '
      +'A big level trains hundreds, almost all of them gated to one faction, so '
      +'"who can train what" is usually the question you arrive with.','Faction filter')
    +`<select class="mini" onchange="bldPoolFacPick(this.value);this.value=''"
      style="flex:0 0 auto;max-width:230px">
      <option value="">Faction: ${esc(picked)}…</option>
      ${sel.size?'<option value="(clear)">Show everything</option>':''}
      ${open?`<option value="(any)">No faction clause (${open})</option>`:''}
      ${rows.map(([f,n])=>`<option value="${esc(f)}">${esc(bldFacName(f))} (${n})</option>`).join('')}
    </select>
    <span class="viewtoggle" title="Which order the faction list above is in.">
      <button class="${az?'on':''}" ${az?'disabled':''}
        onclick="bldFacSortToggle()">A to Z</button>
      <button class="${az?'':'on'}" ${az?'':'disabled'}
        onclick="bldFacSortToggle()">Unit count</button>
    </span>`;
}
const bldFacSort=()=>((state.settings||{}).bld_facsort==='az'?'az':'count');
function bldFacSortToggle(){
  const v=bldFacSort()==='az'?'count':'az';
  state.settings.bld_facsort=v; api.post('/api/settings',{bld_facsort:v});
  bldRedrawLevel();
}
function bldPoolFacPick(v){
  const b=state.bld; if(!b)return;
  b.poolFac=b.poolFac||new Set();
  if(!v)return;
  if(v==='(clear)')b.poolFac.clear();
  else if(b.poolFac.has(v))b.poolFac.delete(v); else b.poolFac.add(v);
  bldRedrawLevel();
}
function bldSetView(v){
  const b=state.bld; if(!b)return;
  b.view=v;
  state.settings.bld_view=v; api.post('/api/settings',{bld_view:v});
  bldRedrawLevel();
}
/* Repaint the level the editor is on, or do nothing at all.
   Everything that changes how the recruitment list LOOKS lands here rather than
   reaching into `state.bld.work` itself: a mod switch nulls `state.bld` and a
   closed dialog leaves `work` null, and a control that survives either — the
   sidebar, a remembered setting, a keystroke — would otherwise throw on a stale
   object and take the whole page down with it. */
function bldRedrawLevel(){
  const b=state.bld;
  if(!b||!b.work||!b.d||!b.work.levels[b.lvl]||!b.d.levels[b.lvl])return;
  bldRenderBody(b.work.levels[b.lvl],b.d.levels[b.lvl]);
}
// The cached ownership answer for a pool, if one has been fetched — drawn as a
// small flag on the row rather than fetched eagerly for hundreds of units.
function bldPoolOwnFlag(c){
  const b=state.bld;
  const facs=(c.conds||[]).filter(x=>x.kind==='factions'&&!x.negate).flatMap(x=>x.values||[]);
  if(!facs.length)return '';
  const row=b.own[c.pool.unit+'|'+[...facs].sort().join(',')];
  if(!row||(!row.missing_ownership.length&&!row.missing_textures.length))return '';
  const bits=[];
  if(row.missing_ownership.length)bits.push('not owned by '+row.missing_ownership.join(', '));
  if(row.missing_textures.length)bits.push('no texture for '+row.missing_textures.join(', '));
  return `<span class="ownflag" title="${esc(bits.join('; '))}. Saving fixes this.">⚠</span>`;
}
function bldPoolRow(c){
  const b=state.bld,i=bldCapList().indexOf(c);
  const info=b.d.units[(c.pool.unit||'').toLowerCase()];
  const missing=!info||info.missing;
  /* Two lines, not one. The row used to put the unit, four number boxes, the
     whole `requires` clause and five buttons side by side, and the clause is the
     only one of those with no natural width: a real one names half a dozen
     factions and a settlement level, so it was squeezed into whatever the fixed
     columns left over and read as an ellipsis. The numbers keep the top line,
     which is what the eye scans down; the clause gets a line to itself and the
     full width of the panel. */
  return `<div class="poolrow ${c.del?'gone':''} ${missing?'missing':''} ${
      bldBulkHas(c)?'picked':''}" data-cap="${i}">
    <div class="prtop">
      ${bldPickBox(c,i)}
      <img loading="lazy" onerror="iconRetry(this)" src="${iconUrl(state.src,c.pool.unit)}" alt="">
      <div class="who"><div class="un" title="${esc(c.pool.unit)}">${esc(info&&!missing?info.name:c.pool.unit)}</div>
        <div class="ut">${missing?'<span class="w-bad">Not in this mod’s EDU</span>':esc(c.pool.unit)}</div></div>
      <div class="nums">
        <label>${qm(POOL_HELP.initial,POOL_LABEL.initial)}${POOL_LABEL.initial}${
          numBox('data-pool="initial"',c.pool.initial,'pool')}</label>
        <label>${qm(POOL_HELP.per_turn,POOL_LABEL.per_turn)}${POOL_LABEL.per_turn}${
          numBox('data-pool="per_turn"',c.pool.per_turn,'turns',
          `<span class="turns">= ${esc(poolTurns(c.pool.per_turn))}</span>`)}</label>
        <label>${qm(POOL_HELP.maximum,POOL_LABEL.maximum)}${POOL_LABEL.maximum}${
          numBox('data-pool="maximum"',c.pool.maximum,'pool')}</label>
        <label>${qm(POOL_HELP.experience,POOL_LABEL.experience)}${POOL_SHORT.experience}${
          numBox('data-pool="experience"',c.pool.experience,'1')}</label>
      </div>
      <div class="acts">
        ${bldPoolActs(c,i)}
        ${missing?'':`<button title="Open this unit in the Unit Editor"
          onclick="openUnitFromBuilding('${q1(esc(c.pool.unit))}')">✎ Edit</button>`}
        <button class="${c.del?'':'danger'}" onclick="bldToggleDel(${i})"
          title="${c.del?'Keep this recruit pool':'Remove this recruit pool'}">${c.del?'↺':'🗑'}</button>
      </div>
      ${c.faction?'<span class="badge">faction</span>':''}
    </div>
    <div class="prbot">
      <span class="prk">Requires</span>
      <div class="clausebar">
        <div class="sum">${bldClauseSummary(c.conds)}</div>
        ${bldPoolOwnFlag(c)}
        <button class="reqbtn" onclick="bldEditClause('cap',${i})">✎</button>
        ${bldCopyBtn(i)}
      </div>
    </div></div>`;
}
function bldPoolCard(c){
  const b=state.bld,i=bldCapList().indexOf(c);
  const info=b.d.units[(c.pool.unit||'').toLowerCase()];
  const missing=!info||info.missing;
  return `<div class="ucard ${c.del?'gone':''} ${bldBulkHas(c)?'picked':''}" data-cap="${i}">
    <div class="top">
      ${bldPickBox(c,i)}
      <img loading="lazy" onerror="iconRetry(this)" src="${iconUrl(state.src,c.pool.unit)}" alt="">
      <div style="min-width:0">
        <div class="nm">${esc(info&&!missing?info.name:c.pool.unit)}</div>
        <div class="ty">${missing?'<span class="w-bad">not in this mod’s EDU</span>'
          :esc([info.kind,info.class].filter(Boolean).join(' · ')||c.pool.unit)}</div>
      </div>
      ${bldPoolOwnFlag(c)}
    </div>
    <div class="stats">
      <label>${qm(POOL_HELP.initial,POOL_LABEL.initial)}${POOL_LABEL.initial}${
        numBox('data-pool="initial"',c.pool.initial,'pool')}</label>
      <label>${qm(POOL_HELP.per_turn,POOL_LABEL.per_turn)}${POOL_LABEL.per_turn}${
        numBox('data-pool="per_turn"',c.pool.per_turn,'turns')}</label>
      <label>${qm(POOL_HELP.maximum,POOL_LABEL.maximum)}${POOL_LABEL.maximum}${
        numBox('data-pool="maximum"',c.pool.maximum,'pool')}</label>
      <label>${qm(POOL_HELP.experience,POOL_LABEL.experience)}${POOL_SHORT.experience}${
        numBox('data-pool="experience"',c.pool.experience,'1')}</label>
    </div>
    <div class="turns" data-turns style="text-align:center">a unit ${esc(poolTurns(c.pool.per_turn))}</div>
    <div class="clausebar"><div class="sum">${bldClauseSummary(c.conds)}</div>${bldCopyBtn(i)}</div>
    <div class="acts">
      <button onclick="bldEditClause('cap',${i})">✎ Requires</button>
      ${bldPoolActs(c,i)}
      ${missing?'':`<button onclick="openUnitFromBuilding('${q1(esc(c.pool.unit))}')">✎ Unit</button>`}
      <button class="${c.del?'':'danger'}" onclick="bldToggleDel(${i})">${c.del?'↺':'🗑'}</button>
    </div></div>`;
}
/* The three things you reach for while looking at one recruit pool: put it in
   the settlement type's other half, push it up the rest of the chain, and see
   what every OTHER building gives the same unit. */
function bldPoolActs(c,i){
  const b=state.bld,twin=bldTwin(),above=b.work.levels.length-1-b.lvl;
  const unit=q1(esc(c.pool.unit));
  return `${twin&&bldTwinLevel()?`<button title="Copy this pool into ${esc(twin)}, the ${
      esc(b.d.settlement==='city'?'castle':'city')} half of this building"
    onclick="bldMirrorRowNow(${i})">⇄</button>`:''}
    ${above>0?`<button title="Add this unit to the ${above} tier(s) above, with slightly better numbers"
      onclick="bldTiersRowNow(${i})">⇅</button>`:''}
    <button title="Compare this unit's pool, replenishment and experience across every building line that trains it"
      onclick="bldShowUnit('${unit}')">≡</button>`;
}

/* =========================================================================
   Bulk edit over recruit pools

   Nothing here is a new kind of edit — every one of these actions is something
   the single-row buttons already do. What it changes is the arithmetic: giving
   twenty freshly added units the same `requires factions { … }` was twenty trips
   through the clause dialog, and the twentieth was where the typo went in.

   The selection holds the capability OBJECTS, not their indices. Indices into
   bldCapList() shift the moment a row is added or a new row is dropped, and a
   selection that silently slides onto its neighbours is worse than none.
   ========================================================================= */
const bldBulk=()=>(state.bld.bulk||(state.bld.bulk={on:false,sel:new Set()}));
const bldBulkOn=()=>!!(state.bld&&state.bld.bulk&&state.bld.bulk.on);
const bldBulkHas=c=>bldBulkOn()&&bldBulk().sel.has(c);
// Only rows still in the level count — a new row that was dropped again is gone
// from lv.caps but may still be sitting in the Set.
function bldBulkSel(){
  const sel=bldBulk().sel;
  return bldCapList().filter(c=>c.pool&&sel.has(c));
}
function bldBulkToggle(){
  const bu=bldBulk(); bu.on=!bu.on;
  if(!bu.on)bu.sel.clear();
  bldRenderBodyNow();
}
function bldPickBox(c,i){
  if(!bldBulkOn())return '';
  return `<label class="pick" title="Tick this pool for the bulk actions above"><input type="checkbox"
    ${bldBulkHas(c)?'checked':''} onchange="bldBulkPick(${i},this.checked)"></label>`;
}
function bldBulkPick(i,on){
  const c=bldCapList()[i]; if(!c)return;
  on?bldBulk().sel.add(c):bldBulk().sel.delete(c);
  bldRenderBodyNow();
}
function bldBulkAll(on){
  const bu=bldBulk(),lv=state.bld.work.levels[state.bld.lvl];
  // "all" means all the filter is showing, not all three hundred the level has
  const shown=[...lv.caps,...lv.fcaps].filter(c=>c.pool&&bldPoolMatches(c));
  shown.forEach(c=>on?bu.sel.add(c):bu.sel.delete(c));
  if(!on)bu.sel.clear();
  bldRenderBodyNow();
}
const bldRenderBodyNow=()=>bldRenderBody(state.bld.work.levels[state.bld.lvl],
                                         state.bld.d.levels[state.bld.lvl]);
/* ---- carrying one row's clause to the others ----
   The clipboard lives on `state`, not on the building, so a clause copied out of
   the town watch can be pasted into the barracks — which is most of why anyone
   would copy one at all. It holds a deep copy: pasting must not hand every row a
   reference to the same terms, or editing one afterwards edits all of them. */
function bldCopyBtn(i){
  return `<button class="reqbtn" onclick="bldCopyCond(${i})"
    title="Copy these requirements. Tick other units under ☑ Bulk edit and paste them on.">⧉</button>`;
}
function bldCopyCond(i){
  const c=bldCapList()[+i]; if(!c)return;
  const name=(c.pool&&c.pool.unit)||c.keyword||'that row';
  state.condClip={unit:name,conds:JSON.parse(JSON.stringify(c.conds||[])),
                  text:bldClauseText(c.conds)};
  // so the bar's "copy from" box keeps showing whoever it was last taken from,
  // whether that was picked in the box or by ⧉ on a row
  state.bld.copyFrom=(c.pool&&c.pool.unit)||'';
  const bu=bldBulk();
  if(!bu.on){bu.on=true;}                     // there is nowhere to paste it otherwise
  bldRenderBodyNow();
  toast(`Copied ${name}’s requirements${state.condClip.text?': '+state.condClip.text:' (none, so always)'
    }. Tick the units to paste onto.`,4200);
}
/* Put a clause onto one row. `replace` swaps it outright; `add` joins the new
   terms onto what is already there. M2TW evaluates a clause left to right with
   no brackets, so "add" really is a concatenation — the incoming terms are
   ANDed onto the end, and a term the row already carries is skipped rather than
   written twice. */
function bldCondsOnto(host,conds,mode){
  const incoming=JSON.parse(JSON.stringify(conds||[]));
  const base=mode==='add'?JSON.parse(JSON.stringify(host.conds||[])):[];
  const seen=new Set(base.map(c=>bldCondText(c)));
  const keep=incoming.filter(c=>{
    const t=bldCondText(c);
    if(mode==='add'&&seen.has(t))return false;
    seen.add(t); return true;
  });
  keep.forEach(c=>{ if(!c.join)c.join='and'; });
  const out=base.concat(keep);
  if(out.length)out[0].join='';
  host.conds=out; host.condEdited=true; host.requires=bldClauseText(out);
  return out;
}
function bldBulkPaste(){
  const sel=bldBulkSel(),clip=state.condClip;
  if(!clip||!sel.length)return;
  const mode=bldPasteMode();
  sel.forEach(h=>bldCondsOnto(h,clip.conds,mode));
  bldTouched();
  toast(`${clip.unit}’s requirements ${mode==='add'?'added to':'copied onto'} ${
    sel.length} unit${sel.length===1?'':'s'}.`);
}
const bldPasteMode=()=>(state.bld.pasteMode==='add'?'add':'replace');
function bldSetPasteMode(v){ state.bld.pasteMode=v; }
function bldBulkDelete(){
  const b=state.bld,sel=bldBulkSel(); if(!sel.length)return;
  const lv=b.work.levels[b.lvl];
  sel.forEach(c=>{
    c.del=true;
    // a row that was only ever added by this dialog just goes away
    if(c.line==null){ const from=c.faction?lv.fcaps:lv.caps;
      const i=from.indexOf(c); if(i>=0)from.splice(i,1); }
    bldBulk().sel.delete(c);
  });
  bldTouched();
  toast(`${sel.length} recruit pool${sel.length===1?'':'s'} marked for removal.`);
}
// Only the boxes you actually filled in are written — a blank one leaves that
// number alone, so "give these twelve units max 4" doesn't also zero their
// starting points.
function bldBulkNums(){
  const b=state.bld,sel=bldBulkSel(),n=b.bulkNums||{};
  const keys=['initial','per_turn','maximum','experience'].filter(k=>(n[k]||'').trim()!=='');
  if(!sel.length)return;
  if(!keys.length){toast('Fill in at least one of the four numbers first.');return;}
  sel.forEach(c=>keys.forEach(k=>{c.pool[k]=n[k].trim();}));
  bldTouched();
  toast(`${keys.map(k=>POOL_LABEL[k]||k).join(', ')} set on ${sel.length} pool${
    sel.length===1?'':'s'}.`);
}
/* What the three recruitment numbers are CALLED, in one place.

   They used to be labelled by shape rather than by job: "start / per turn / max"
   describes the arithmetic and says nothing about what the number does to the
   game, and each screen had spelt it differently anyway. These are the names
   every screen in the toolkit now uses, so the number you set on a row is the
   number you recognise in the comparison panel and in the bulk editor. */
const POOL_LABEL={initial:'Initial Pool',per_turn:'Replenish Rate',
                  maximum:'Max Pool',experience:'Experience'};
//: The same names where a row has no width to spare for the long one.
const POOL_SHORT={initial:'Initial Pool',per_turn:'Replenish Rate',
                  maximum:'Max Pool',experience:'XP'};
/* Which unit a clause is taken FROM is its own choice, not "whichever you ticked
   first": the unit you want to copy is usually one you have NOT ticked, because
   the ticks are the units you are about to paste onto. So it is a box over every
   pool on the level — ticked ones marked — rather than a button. */
function bldCopySelect(sel){
  const b=state.bld,list=bldCapList();
  const pools=list.map((c,i)=>({c,i})).filter(x=>x.c.pool&&!x.c.del);
  if(!pools.length)return '';
  const name=c=>{
    const info=b.d.units[(c.pool.unit||'').toLowerCase()];
    return (info&&!info.missing?info.name:c.pool.unit)||c.pool.unit;
  };
  const byUnit=pools.find(x=>x.c.pool.unit===b.copyFrom);
  const cur=byUnit?byUnit.i:(sel.length?list.indexOf(sel[0]):-1);
  return `<span class="lbl2">⧉ Copy from</span>
    <select onchange="bldCopyCond(this.value)" style="max-width:220px"
      title="Take this unit's requirements onto the clipboard, ready to paste onto the ticked ones">
      ${pools.map(x=>`<option value="${x.i}" ${x.i===cur?'selected':''}
        >${bldBulkHas(x.c)?'✓ ':''}${esc(name(x.c))}</option>`).join('')}
    </select>`;
}
function bldBulkBar(shown){
  if(!bldBulkOn())return '';
  const b=state.bld,sel=bldBulkSel(),n=sel.length,clip=state.condClip;
  const bn=b.bulkNums||(b.bulkNums={initial:'',per_turn:'',maximum:'',experience:''});
  const num=k=>`<label>${POOL_LABEL[k]}<input data-bulknum="${k}" value="${esc(bn[k])}"
    placeholder="0" inputmode="decimal"></label>`;
  return `<div class="bulkbar">
    <span class="n">${n} selected</span>
    <button onclick="bldBulkAll(true)">Tick all ${shown.length} shown</button>
    <button onclick="bldBulkAll(false)" ${n?'':'disabled'}>Clear</button>
    <button class="primary" ${n?'':'disabled'} onclick="bldBulkClause()"
      title="Edit one requires clause and put it on every ticked unit">✎ Requirements for ${n}…</button>
    ${bldCopySelect(sel)}
    <button ${clip&&n?'':'disabled'} onclick="bldBulkPaste()"
      title="${clip?esc('Paste '+clip.unit+'’s requirements: '+(clip.text||'(none, so always)'))
                  :'Copy a unit’s requirements first'}">📌 Paste${
        clip?` ${esc(clip.unit)}’s`:''}</button>
    <select onchange="bldSetPasteMode(this.value)" title="What pasting does to what the row already says">
      <option value="replace" ${bldPasteMode()==='replace'?'selected':''}>Replace theirs</option>
      <option value="add" ${bldPasteMode()==='add'?'selected':''}>Add to theirs</option>
    </select>
    <button class="danger" ${n?'':'disabled'} onclick="bldBulkDelete()">🗑 Remove ${n}</button>
    <div class="bnote" style="flex:1 1 100%;margin:0">${clip
      ? `Clipboard: <b>${esc(clip.unit)}</b>, <code>${esc(clip.text||'always')}</code>`
      : 'Copy a clause off one unit with ⧉ on its row, then paste it onto the ticked ones.'}</div>
    <div class="bnums">${['initial','per_turn','maximum','experience'].map(num).join('')}
      <button ${n?'':'disabled'} onclick="bldBulkNums()">Apply numbers to ${n}</button>
      <span class="hint">Blank boxes are left alone.</span></div>
  </div>`;
}
/* One clause dialog over many rows. It opens on what they already say when they
   all say the same thing — the common case straight after adding a batch, where
   every one of them carries its own ownership and you are about to narrow that
   to one faction. When they disagree it opens empty rather than picking a winner
   arbitrarily. */
function bldBulkClause(){
  const b=state.bld,hosts=bldBulkSel();
  if(!hosts.length)return;
  const first=bldClauseText(hosts[0].conds);
  const same=hosts.every(h=>bldClauseText(h.conds)===first);
  const seed=same?JSON.parse(JSON.stringify(hosts[0].conds||[])):[];
  b.clause={hosts,kind:'bulk',index:-1,
            conds:seed,was:JSON.parse(JSON.stringify(seed)),
            units:hosts.map(h=>h.pool&&h.pool.unit).filter(Boolean),
            unit:'',mode:same?'replace':'add',same,pick:null};
  b.stashScroll=stashPlace();   // come back to the row you opened, not the top
  b.stash=document.getElementById('modal').innerHTML;
  renderClauseDialog();
  bldClauseOwnership();
}
function bldClauseMode(v){ state.bld.clause.mode=v; renderClauseDialog(); }

/* ---- the upgrade graph ----
   A line is not always a straight chain. Some branch (A -> B -> D and A -> C -> E),
   and at least one in DaC is a single root with every other level hanging off it
   (A -> B, C, D, E). So rather than assume a ladder, the levels are laid out by
   depth from whichever ones nothing upgrades into. */
function bldUpgradeGraph(){
  const b=state.bld,levels=b.work.levels;
  const idx=new Map(levels.map((lv,i)=>[lv.name,i]));
  const into=new Map(levels.map(lv=>[lv.name,[]]));
  levels.forEach(lv=>lv.upgrades.forEach(u=>{
    const name=u.split(/\s+/)[0];
    if(into.has(name))into.get(name).push(lv.name);
  }));
  const roots=levels.filter(lv=>!into.get(lv.name).length).map(lv=>lv.name);
  const depth=new Map();
  const walk=(name,d,seen)=>{
    if(seen.has(name))return;                 // a cycle in a hand-edited EDB
    seen.add(name);
    depth.set(name,Math.max(depth.get(name)||0,d));
    const lv=levels[idx.get(name)];
    (lv?lv.upgrades:[]).forEach(u=>{
      const n=u.split(/\s+/)[0];
      if(idx.has(n))walk(n,d+1,seen);
    });
    seen.delete(name);
  };
  (roots.length?roots:[levels[0]&&levels[0].name]).forEach(r=>r&&walk(r,0,new Set()));
  levels.forEach(lv=>{if(!depth.has(lv.name))depth.set(lv.name,0);});
  const tiers=[];
  depth.forEach((d,name)=>{(tiers[d]=tiers[d]||[]).push(name);});
  return {tiers,idx,into,depth};
}
function bldUpgradesSection(lv,orig){
  const b=state.bld,g=bldUpgradeGraph();
  const idx=g.idx;
  const node=name=>{
    const i=idx.get(name);
    const t=i==null?name:bldLevelLabel(i);
    return `<div class="pnode ${i===b.lvl?'on':''}" onclick="bldPickLevel(${i})"
      title="Open ${esc(t)}">
      <img loading="lazy" onerror="iconRetry(this)" src="${bldIcon(name,'small')}" alt="">
      <div><div class="t">${esc(t)}</div><div class="n">${esc(name)}</div></div></div>`;
  };
  // what THIS level upgrades into, editable; only ever levels further along the
  // line's own `levels` order, because M2TW upgrades never go backwards
  const here=lv.upgrades.map(bldUpgName);
  const forward=b.d.levels.map((l,i)=>l.name)
    .filter((n,i)=>i>b.lvl&&!here.includes(n));
  return `<div class="bsec"><h4>Upgrade path
      <span class="count">${g.tiers.length>1?g.tiers.length+' tiers':'one tier'}</span></h4>
    <div class="pathwrap">${g.tiers.map((names,d)=>`
      <div class="prow">${d?'<span class="parrow">↳</span>':''}
        ${names.map(node).join(d?'<span class="pbranch">or</span>':'<span class="parrow">·</span>')}
      </div>`).join('')}</div>
    <div class="bnote">Click any building to open it. Levels on the same row are
      alternatives at the same depth.</div>
    <h4 style="margin-top:12px">${esc(bldLevelLabel(b.lvl))} upgrades into
      <span class="n">${here.length}</span></h4>
    <div class="upglist" id="bldUpg">${here.length?lv.upgrades.map((u,i)=>{
        const name=bldUpgName(u);
        const j=idx.get(name);
        const conds=(lv.upgConds&&lv.upgConds[i])||[];
        return `<div class="upgrow">
          <span class="un">${j!=null?`<a class="ulink" onclick="bldPickLevel(${j})">${esc(name)}</a>`
            :`<span class="w-bad" title="No level of this line is called that">${esc(name)}</span>`}</span>
          <div class="clausebar" style="flex:1;min-width:110px">
            <div class="sum">${bldClauseSummary(conds)}</div>
            <button class="reqbtn" onclick="bldEditClause('upgrade',${i})"
              title="Who takes this branch. An upgrade may carry its own requires clause: 41 of the 771 in the installed mods do.">✎</button>
          </div>
          <button class="x danger" onclick="bldUpgRemove(${i})"
            title="Stop upgrading into this">🗑</button></div>`;
      }).join(''):'<div class="upgrow"><span class="count">Nothing. This is the end of its branch.</span></div>'}
    </div>
    ${forward.length?`<div class="brow" style="margin-top:6px">
      <select class="mini" id="upgAdd" style="flex:0 0 260px">
        <option value="">＋ Also upgrade into…</option>
        ${forward.map(n=>`<option value="${esc(n)}">${esc(n)}</option>`).join('')}
      </select><span class="count">Only levels later in the line are offered:
        an upgrade can never point backwards.</span></div>`
      :'<div class="bnote">This is the last level in the line, so it has nothing to upgrade into.</div>'}
  </div>`;
}
/* An `upgrades` entry is a level name and, sometimes, a clause of its own:
   `ce_wooden_wall requires event_counter cex_avail_wooden_wall_erebor 1`. The
   level is the first word — the server's `buildings.upgrade_name` says the same
   thing, and both are wanted, because the page draws the row and the file
   writes it. */
const bldUpgName=u=>String(u||'').split(/\s+/)[0]||'';
function bldUpgRemove(i){
  const lv=state.bld.work.levels[state.bld.lvl];
  lv.upgrades.splice(i,1);
  if(lv.upgConds)lv.upgConds.splice(i,1);
  bldTouched();
}
function bldUpgAdd(name){
  if(!name)return;
  const lv=state.bld.work.levels[state.bld.lvl];
  lv.upgrades.push(name);
  (lv.upgConds=lv.upgConds||[]).push([]);
  bldTouched();
}
/* The keyword picker, in groups. There are 60 of them and they were one flat
   alphabetical list, which is a list you read rather than choose from —
   `construction_cost_bonus_stone` and `weapon_melee_blade` are not neighbours in
   anybody's head. The grouping is the one thing worth taking from the reference
   tool's EDB half; the hint carries the range the engine accepts beside it. */
function bldCapOptions(current){
  const b=state.bld,caps=b.ov.capabilities||[];
  const groups=b.ov.capability_groups||['Other'];
  const known=caps.map(x=>x.keyword);
  const out=groups.map(g=>{
    const rows=caps.filter(x=>(x.group||'Other')===g);
    if(!rows.length)return '';
    return `<optgroup label="${esc(g)}">${rows.map(x=>
      `<option value="${esc(x.keyword)}" ${x.keyword===current?'selected':''}
        title="${esc(x.help||'')}">${esc(x.keyword)}${
        x.range?` (${esc(x.range)})`:''}</option>`).join('')}</optgroup>`;
  }).join('');
  // a keyword this mod uses that our list has never heard of stays selectable
  return out+(known.includes(current)?''
    :`<optgroup label="In this file"><option value="${esc(current)}" selected
        >${esc(current)}</option></optgroup>`);
}
function bldCapRow(c){
  const b=state.bld,i=bldCapList().indexOf(c);
  const meta=b.ov.capabilities.find(x=>x.keyword===c.keyword)||{};
  const help=(meta.help||'')+(meta.range?`  (${meta.range})`:'');
  return `<div class="caprow ${c.del?'gone':''}" data-cap="${i}">
    ${qm(help.trim()||'A capability this level gives the settlement. Pick the keyword to see what it does.',c.keyword)}
    <select class="kw" data-kw>${bldCapOptions(c.keyword)}</select>
    ${qm('Write the value as "bonus N" rather than a bare number. Most modifiers are declared that way, and the engine ignores the ones that are not.','bonus')}
    <label class="chk"><input type="checkbox" data-bonus ${c.bonus?'checked':''}> bonus</label>
    ${numBox('class="val" data-val',c.value,'1')}
    <div class="clausebar" style="flex:1;min-width:110px">
      <div class="sum">${bldClauseSummary(c.conds)}</div>
      <button class="reqbtn" onclick="bldEditClause('cap',${i})">✎</button>
    </div>
    ${c.faction?'<span class="badge">faction</span>':''}
    <button class="x ${c.del?'':'danger'}" onclick="bldToggleDel(${i})">${c.del?'↺':'🗑'}</button>
    </div>`;
}
function bldToggleDel(i){
  const c=bldCapList()[i]; c.del=!c.del;
  // a row that was only ever added by this dialog just goes away
  if(c.del&&c.line==null){
    const lv=state.bld.work.levels[state.bld.lvl];
    const from=c.faction?lv.fcaps:lv.caps;
    from.splice(from.indexOf(c),1);
  }
  bldTouched();
}
function bldTouched(){
  state.bld.planStale=!!state.bld.plan;
  const b=state.bld;
  // The building form is not on screen while another panel has the modal, and
  // its body element does not exist. Staging from over there redraws its own
  // panel, and the form is rebuilt from the same working copy on the way back.
  // `stash` is what every such panel sets, so this covers the ones written after
  // it as well as the two that were named here.
  if(b.cmp||b.vc||b.stash)return;
  bldRenderBody(b.work.levels[b.lvl],b.d.levels[b.lvl]);
  bldCvFollow();
}
/* The working copy as it was when the building opened, so every widget can say
   which of its values is yours. b.orig is the JSON of that moment; it is parsed
   once and cached, not per keystroke. */
function bldBaseLevel(){
  const b=state.bld;
  if(b._baseFor!==b.orig){ b._base=JSON.parse(b.orig); b._baseFor=b.orig; }
  const lv=b._base.levels[b.lvl]||{caps:[],fcaps:[]};
  return [...lv.caps,...lv.fcaps];
}
function bldWire(){
  const b=state.bld,lv=b.work.levels[b.lvl],list=bldCapList();
  const body=document.getElementById('bldBody');
  const mark=(el,changed)=>el.classList.toggle('changed',!!changed);
  const orig=b.d.levels[b.lvl];
  body.querySelectorAll('[data-scalar]').forEach(el=>{
    const key=el.dataset.scalar;
    mark(el,(el.value||'')!==(orig.scalars[key]||''));
    el.oninput=el.onchange=()=>{
      const v=el.value.trim();
      if(v)lv.scalars[key]=v; else delete lv.scalars[key];
      mark(el,v!==(orig.scalars[key]||'')); bldDirtyNote();};
  });
  const st=body.querySelector('[data-settlement]');
  mark(st,st.value!==orig.settlement);
  st.onchange=()=>{lv.settlement=st.value;mark(st,st.value!==orig.settlement);bldDirtyNote();};
  const upAdd=document.getElementById('upgAdd');
  if(upAdd)upAdd.onchange=()=>{bldUpgAdd(upAdd.value);};
  // The bulk bar's four numbers are staged on the building, not on any row, so
  // ticking another unit (which redraws the bar) doesn't wipe what was typed.
  body.querySelectorAll('[data-bulknum]').forEach(el=>{
    el.oninput=()=>{(b.bulkNums||(b.bulkNums={}))[el.dataset.bulknum]=el.value;};
  });
  const locC=bldLocSel(),locWas=((orig.loc_all||{})[locC])||{};
  body.querySelectorAll('[data-loc]').forEach(el=>{
    const key=el.dataset.loc;
    mark(el,el.value!==(locWas[key]||''));
    el.oninput=()=>{bldLocRec()[key]=el.value;
      mark(el,el.value!==(locWas[key]||''));bldDirtyNote();};
  });
  // A capability is matched to its baseline by the EDB LINE it came from, not by
  // its position: adding a pool pushes onto lv.caps, which shifts every
  // faction_capability's index in the combined list and would mis-pair them.
  const baseCaps=new Map();
  bldBaseLevel().forEach(c=>{ if(c.line!=null)baseCaps.set(c.line,c); });
  body.querySelectorAll('[data-cap]').forEach(row=>{
    const c=list[+row.dataset.cap]; if(!c)return;
    const was=c.line==null?null:baseCaps.get(c.line);   // null = a row you added
    const rowMark=()=>row.classList.toggle('changed',
      !!row.querySelector('.changed')||c.line==null||c.del);
    row.querySelectorAll('[data-pool]').forEach(el=>{
      const k=el.dataset.pool;
      const orig=()=>String((was&&was.pool&&was.pool[k])!=null?was.pool[k]:'');
      const diff=()=>!was||el.value.trim()!==orig();
      mark(el,diff());
      el.oninput=()=>{c.pool[k]=el.value.trim();
        // the grid card keeps its "a unit every N turns" line under the boxes
        if(k==='per_turn')row.querySelectorAll('[data-turns]')
          .forEach(t=>{t.textContent='a unit '+poolTurns(el.value);});
        mark(el,diff()); rowMark(); bldDirtyNote();};});
    const kw=row.querySelector('[data-kw]');
    if(kw){ mark(kw,!was||kw.value!==was.keyword);
      kw.onchange=()=>{c.keyword=kw.value;bldTouched();}; }
    const bo=row.querySelector('[data-bonus]');
    if(bo){ mark(bo,!was||bo.checked!==!!was.bonus);
      bo.onchange=()=>{c.bonus=bo.checked;mark(bo,!was||bo.checked!==!!was.bonus);
        rowMark();bldDirtyNote();}; }
    const val=row.querySelector('[data-val]');
    if(val){ const diff=()=>!was||val.value.trim()!==String(was.value==null?'':was.value);
      mark(val,diff());
      val.oninput=()=>{c.value=val.value.trim();mark(val,diff());rowMark();bldDirtyNote();}; }
    rowMark();
  });
  wireNumBoxes(body);
}
function bldDirtyNote(){
  paintDirty();
  const b=state.bld; if(!b)return;
  b.planStale=!!b.plan;
  const chip=document.querySelectorAll('.lvchip')[b.lvl];
  if(chip)chip.classList.toggle('dirty',bldLevelDirty(b.lvl));
  bldCvFollow();
}
/* Keep the text pane in step with the boxes.

   Every other editor that adopted the pane calls `cvFromGui` the moment one of
   its boxes changes, which is what makes the pane a promise about the bytes a
   save would write rather than a picture of the record as it opened. This one
   never did: cost, culture, name, a `requires` term, a recruit pool's numbers —
   all of it changed the working copy, none of it reached the pane, and the text
   beside the form went on showing the file. It is called from the two places
   every change in this editor already goes through, so a new control gets it
   without knowing the pane exists.

   `cvFromGui` is itself debounced and does nothing while the caret is IN the
   pane, so this is safe to call on every keystroke. */
function bldCvFollow(){
  const b=state.bld;
  if(b&&b.cv&&!b.cmp)cvFromGui(b.cv);
}
function bldAddCap(){
  const lv=state.bld.work.levels[state.bld.lvl];
  lv.caps.push({line:null,keyword:'law_bonus',args:'',requires:'',bonus:true,value:'1',
                pool:null,comment:'',faction:false,del:false});
  bldTouched();
}

/* =========================================================================
   `requires` clauses, as structure

   A clause is a flat list of terms joined left-to-right by and/or — M2TW has no
   precedence, so there is no tree to draw. Each term names something declared
   elsewhere in the mod (a faction, an event counter, a hidden resource) by its
   CODE name, and a typo there is invisible: the game doesn't complain, the
   building simply never becomes available. So every term is edited by picking
   from the mod's own lists, shown by real name with the code in brackets.

   Anything the parser didn't recognise stays as raw text rather than being
   dropped — a couple of real mods have malformed clauses and they must survive
   a round trip untouched.
   ========================================================================= */

const COND_LABEL={factions:'Factions',hidden_resource:'Hidden resource',
  resource:'Trade resource',event_counter:'Event',region_religion:'Region religion',
  building_present_min_level:'Building present (min level)',
  building_present:'Building present',settlement_min:'Settlement size',
  market_level:'Market level',raw:'Custom text'};

const bldVocab=()=>((state.bld&&state.bld.ov&&state.bld.ov.vocab)||{});
// A `factions { }` entry may be a faction, a whole culture, or the keyword
// `all`; the label says which, since a culture quietly covers several factions.
function bldFacName(code){
  const v=bldVocab();
  if(code===(v.all_keyword||'all'))return 'All factions';
  const f=(v.factions||[]).find(x=>x.code===code);
  if(f)return f.name?`${f.name} (${f.code})`:f.code;
  const c=(v.cultures||[]).find(x=>x.code===code);
  if(c)return `${c.name?c.name+' ':''}(${c.code}) · culture`;
  return code;
}
function bldEventName(name){
  const e=(bldVocab().events||[]).find(x=>x.name===name);
  return e&&e.title?`${e.title} (${e.name})`:name;
}
// The JS side of Condition.text() in unittransfer/buildings.py. Kept in step
// with it because the page previews a clause before the server ever emits one;
// the server's version is what actually gets written.
function bldCondText(c){
  if(c.kind==='raw')return c.raw||'';
  const body=c.kind==='factions'
    ? 'factions {'+(c.values||[]).map(v=>' '+v+',').join('')+' }'
    : [c.kind].concat((c.values||[]).filter(v=>v!=='')).join(' ');
  return (c.negate?'not ':'')+body;
}
function bldClauseText(conds){
  return (conds||[]).map((c,i)=>(i?` ${c.join||'and'} `:'')+bldCondText(c)).join('').trim();
}
// One readable line for a row that has no room for the full editor.
function bldClauseSummary(conds){
  if(!conds||!conds.length)return '<span class="count">Always</span>';
  return conds.map((c,i)=>{
    const j=i?`<span class="cj">${esc(c.join||'and')}</span> `:'';
    return j+`<span class="cterm${c.negate?' neg':''}">${esc(bldCondSummary(c))}</span>`;
  }).join(' ');
}
function bldCondSummary(c){
  const v=c.values||[],n=c.negate?'not ':'';
  switch(c.kind){
    case 'factions':{
      const names=v.map(x=>{const f=(bldVocab().factions||[]).find(y=>y.code===x);
        return f&&f.name?f.name:x;});
      return n+(names.length>3?`${names.slice(0,3).join(', ')} +${names.length-3}`
                              :names.join(', ')||'nobody');}
    case 'event_counter':{
      const e=(bldVocab().events||[]).find(x=>x.name===v[0]);
      const nm=e&&e.title?e.title:v[0];
      return (v[1]==='0'?'before ':'after ')+(c.negate?'NOT ':'')+nm;}
    case 'region_religion': return `${n}region ≥${v[1]}% ${v[0]}`;
    case 'hidden_resource': return `${n}hidden: ${v[0]}`;
    case 'resource': return `${n}resource: ${v[0]}`;
    case 'building_present_min_level': return `${n}has ${v[0]} ≥ ${v[1]}`;
    case 'building_present': return `${n}has ${v[0]}`;
    default: return n+bldCondText(Object.assign({},c,{negate:false}));
  }
}
/* ---- the clause dialog ----
   Opened from a level or from one recruit pool. `ctx.conds` is edited in place
   and `ctx.done()` is called on close, so the caller doesn't have to thread the
   value back. The building editor's markup is stashed and restored, the same
   trick the unit picker uses. */
function bldEditClause(kind,index){
  const b=state.bld,lv=b.work.levels[b.lvl];
  // An upgrade row has no host object of its own — the entry is a string in
  // `lv.upgrades`. So it gets a stand-in whose conds the dialog edits, and
  // bldClauseApply writes the two back into the string as one.
  const host=kind==='level'?lv
    :kind==='upgrade'?{conds:(lv.upgConds&&lv.upgConds[index])||[],requires:'',
                       upgIndex:index}
    :bldCapList()[index];
  if(!host)return;
  const unit=(host.pool&&host.pool.unit)||'';
  b.clause={host,kind,index,conds:JSON.parse(JSON.stringify(host.conds||[])),
            // what the clause said on the way in, so every widget in here can
            // show which of its values YOU changed
            was:JSON.parse(JSON.stringify(host.conds||[])),
            unit,units:unit?[unit]:[],pick:null};
  bldClauseStash();
  renderClauseDialog();
  bldClauseOwnership();
}
/* The clause dialog keeps its OWN snapshot of what it covered up.
   It used to borrow `b.stash`, which the add-unit picker and the unit view also
   use — and the unit view can open this dialog on top of itself, so the two
   took turns clearing one slot and the building form underneath was lost. One
   slot per layer, and the nesting stops mattering. */
function bldClauseStash(){
  const b=state.bld;
  b.cstashScroll=stashPlace();   // come back to the row you opened, not the top
  b.cstash=document.getElementById('modal').innerHTML;
}
function bldClauseUnstash(){
  const b=state.bld;
  document.getElementById('modal').innerHTML=b.cstash; b.cstash=null;
  usePlace(b.cstashScroll); b.cstashScroll=null;
}
function bldClauseCancel(){
  const b=state.bld,unit=b.clause&&b.clause.kind==='unit';
  bldClauseUnstash(); b.clause=null;
  // The stash is markup, not a live panel: whichever screen we came from has to
  // be drawn again or its inputs come back unwired.
  if(unit)bldUnitRender(); else bldRenderBody(b.work.levels[b.lvl],b.d.levels[b.lvl]);
}
function bldClauseApply(){
  const b=state.bld,c=b.clause;
  if(c.kind==='bulk'){
    const n=(c.hosts||[]).length;
    (c.hosts||[]).forEach(h=>bldCondsOnto(h,c.conds,c.mode));
    toast(`${c.mode==='add'?'Added to':'Set on'} ${n} unit${n===1?'':'s'}: ${
      bldClauseText(c.conds)||'no requirements'}`,4200);
  }else if(c.kind==='upgrade'){
    const lv=b.work.levels[b.lvl],i=c.host.upgIndex;
    const clause=bldClauseText(c.conds);
    (lv.upgConds=lv.upgConds||[])[i]=c.conds;
    // two spaces before `requires`, the way the real entries are written
    lv.upgrades[i]=bldUpgName(lv.upgrades[i])+(clause?'  requires '+clause:'');
  }else{
    c.host.conds=c.conds; c.host.condEdited=true;
    c.host.requires=bldClauseText(c.conds);
  }
  const unit=c.kind==='unit';
  bldClauseUnstash(); b.clause=null;
  if(unit){ bldUnitRender(); return; }   // its own screen, and not a building edit yet
  bldTouched();
}
function renderClauseDialog(){
  const b=state.bld,c=b.clause;
  const bulk=c.kind==='bulk',n=bulk?c.hosts.length:0;
  const what=bulk
    ? `who can recruit these <b>${n} unit${n===1?'':'s'}</b> here`
    : c.kind==='level'
    ? `who can build <b>${esc(b.d.levels[b.lvl].label)}</b>`
    : c.kind==='upgrade'
    ? `who upgrades into <b>${esc(bldUpgName(
        b.work.levels[b.lvl].upgrades[c.host.upgIndex]))}</b>`
    : (c.unit?`who can recruit <b>${esc(c.unit)}</b> here`
             :`when <b>${esc(c.host.keyword)}</b> applies`);
  document.getElementById('modal').innerHTML=`
    <h2>Requirements: ${what}</h2>
    <div class="mbody">
      ${bulk?bldBulkClauseHead(c):''}
      <div class="condlist" id="condList"></div>
      <div class="brow" style="margin-top:8px">
        <select id="condAdd" style="flex:0 0 260px">
          <option value="">＋ Add a requirement…</option>
          ${Object.keys(COND_LABEL).map(k=>`<option value="${k}">${esc(COND_LABEL[k])}</option>`).join('')}
        </select>
        <span class="count">Terms are evaluated left to right. M2TW has no brackets.</span>
      </div>
      <div id="condOwn"></div>
      <div class="bsec" style="margin-top:12px"><h4>Written as</h4>
        <div class="preview" id="condText"></div></div>
    </div>
    <div class="foot">
      <button onclick="bldClauseCancel()">Cancel</button>
      <button class="primary" onclick="bldClauseApply()">${bulk
        ? `Use on ${n} unit${n===1?'':'s'}` : 'Use these requirements'}</button>
    </div>`;
  document.getElementById('condAdd').onchange=e=>{
    if(!e.target.value)return;
    bldCondAdd(e.target.value); e.target.value='';
  };
  renderCondList();
}
/* The head of the bulk clause dialog: who it will land on, and whether it
   replaces what they say or is added to it. Replace is the default when they all
   already agree — you are narrowing one shared clause. When they disagree the
   dialog opens empty and defaults to ADD, because replacing a clause you were
   never shown is how a level quietly stops training half its units. */
function bldBulkClauseHead(c){
  const names=c.units.slice(0,14).map(esc);
  return `<div class="ownwarn" style="margin:0 0 10px">
    <b>${c.hosts.length} recruit pool${c.hosts.length===1?'':'s'}</b>:
    <code>${names.join('</code> <code>')}</code>${
      c.units.length>names.length?` <span class="count">+${c.units.length-names.length} more</span>`:''}
    <div class="brow" style="margin:7px 0 0">
      <label class="chk"><input type="radio" name="bulkmode" value="replace"
        ${c.mode!=='add'?'checked':''} onchange="bldClauseMode('replace')">
        Replace what each of them requires</label>
      <label class="chk"><input type="radio" name="bulkmode" value="add"
        ${c.mode==='add'?'checked':''} onchange="bldClauseMode('add')">
        Add these terms to what they already require</label>
    </div>
    <div class="count" style="margin-top:4px">${c.same
      ? 'They all require the same thing today, shown below. '
      : '<b class="w-warn">They do not all require the same thing</b>, so this opened empty. '}${
      c.mode==='add'
      ? 'Each term below is ANDed onto that unit’s own clause; a term it already carries is not '
        +'written twice.'
      : 'Replacing throws away whatever each of them requires now.'}</div>
  </div>`;
}
function bldCondAdd(kind){
  const c=state.bld.clause;
  const blank={factions:[],hidden_resource:[''],resource:[''],event_counter:['','1'],
    region_religion:['',''],building_present_min_level:['',''],building_present:[''],
    settlement_min:[''],market_level:['1'],raw:[]};
  c.conds.push({join:c.conds.length?'and':'',negate:false,kind,
                values:(blank[kind]||[]).slice(),raw:''});
  renderCondList();
}
function renderCondList(){
  const c=state.bld.clause;
  const box=document.getElementById('condList');
  box.innerHTML=c.conds.length?c.conds.map(condRowHtml).join('')
    :'<div class="condrow"><span class="count">No requirements. Anyone, always.</span></div>';
  document.getElementById('condText').textContent=bldClauseText(c.conds)||'(no requires clause)';
  wireCondRows();
  bldClauseOwnership();
}
function condRowHtml(cond,i){
  const v=cond.values||[];
  let body='';
  switch(cond.kind){
    case 'factions': body=condFactionsHtml(cond,i); break;
    case 'event_counter': body=
      condPick(i,0,'event',v[0])+
      `<select data-cv="${i}:1" style="flex:0 0 150px">
        <option value="1" ${v[1]!=='0'?'selected':''}>Has happened (1)</option>
        <option value="0" ${v[1]==='0'?'selected':''}>Has not happened (0)</option></select>`;
      break;
    case 'region_religion': body=
      condPick(i,0,'religion',v[0])
      +qm('Minimum percentage of the region that has to follow that religion for this term to hold.','Minimum %')
      +`<input data-cv="${i}:1" value="${esc(v[1]||'')}" inputmode="numeric"
        style="flex:0 0 90px" placeholder="%">`;
      break;
    case 'hidden_resource':
      body=condPick(i,0,'hidden_resource',v[0])+condWhereHtml('hidden_resource',v[0]); break;
    case 'resource':
      body=condPick(i,0,'resource',v[0])+condWhereHtml('resource',v[0]); break;
    case 'building_present': body=condPick(i,0,'building',v[0]); break;
    case 'building_present_min_level':
      body=condPick(i,0,'building',v[0])+condPick(i,1,'level',v[1],v[0]); break;
    case 'settlement_min': body=condPick(i,0,'settlement',v[0]); break;
    case 'raw': body=`<input data-craw="${i}" value="${esc(cond.raw||'')}"
      style="flex:1" placeholder="written into the clause exactly as typed">`; break;
    default: body=`<input data-cv="${i}:0" value="${esc(v[0]||'')}" style="flex:1">`;
  }
  return `<div class="condrow" data-cond="${i}">
    ${i?`<select data-cjoin="${i}" class="cjoin">
        <option value="and" ${cond.join!=='or'?'selected':''}>and</option>
        <option value="or" ${cond.join==='or'?'selected':''}>or</option></select>`
      :'<span class="cjoin lead">if</span>'}
    <label class="chk">${qm('Invert this term. It holds when the condition is NOT met.','not')}<input
      type="checkbox" data-cneg="${i}" ${cond.negate?'checked':''}> not</label>
    <span class="ckind">${qm(bldCondKindHelp(cond.kind)||'A term of the requires clause.',
      COND_LABEL[cond.kind]||cond.kind)}${esc(COND_LABEL[cond.kind]||cond.kind)}</span>
    ${body}
    <button class="x danger" onclick="bldCondRemove(${i})" title="Remove this requirement">🗑</button>
  </div>`;
}
function bldCondKindHelp(kind){
  const k=((state.bld.ov.condition_kinds)||[]).find(x=>x.kind===kind);
  return k&&k.help?k.help:'';
}
// A single-select over one of the mod's own lists. Rendered as a datalist-backed
// input rather than a <select> because some of these lists run to two thousand
// entries (DaC declares 1 700 event counters) and a plain dropdown is unusable
// at that size.
function condPick(i,slot,list,value,dep){
  const id=`cl${i}_${slot}`;
  return `<input data-cv="${i}:${slot}" list="${id}" value="${esc(value||'')}"
      style="flex:1;min-width:110px" placeholder="${esc(list.replace('_',' '))}…">
    <datalist id="${id}">${condOptions(list,dep).map(o=>
      `<option value="${esc(o.value)}">${esc(o.label)}</option>`).join('')}</datalist>`;
}
function condOptions(list,dep){
  const v=bldVocab();
  switch(list){
    case 'event': return (v.events||[]).map(e=>({value:e.name,
      label:(e.title?e.title+'. ':'')+(e.source==='edb'?'Used in this EDB'
        :e.source==='script'?'set by a script':'from historic_events.txt')}));
    // Each of these means "the regions where it holds", so descr_regions.txt is
    // what the picker shows — a bare code name says nothing about where it bites.
    case 'religion': return (v.religion_rows||(v.religions||[]).map(r=>({code:r})))
      .map(r=>({value:r.code,label:r.regions
        ? `${r.regions} region${r.regions===1?'':'s'} follow it, up to ${r.max}%`
        : 'no region follows this'}));
    case 'hidden_resource': return (v.hidden_resources||[]).map(r=>({value:r.code,
      label:r.count?`${r.count} region${r.count===1?'':'s'}: ${r.regions.slice(0,4).join(', ')}${
        r.regions.length>4?'…':''}`:'no region carries this'}));
    case 'resource': return (v.resources||[]).map(r=>({value:r.code||r,
      label:r.count?`${r.count} region${r.count===1?'':'s'}: ${r.regions.slice(0,4).join(', ')}${
        r.regions.length>4?'…':''}`:'not placed in any region'}));
    case 'settlement': return (state.bld.ov.settlement_levels||[]).map(s=>({value:s,label:s}));
    case 'building': return (v.building_levels||[]).map(b=>({value:b.line,
      label:`${b.levels.length} level${b.levels.length===1?'':'s'}`}));
    case 'level':{
      const line=(v.building_levels||[]).find(b=>b.line===dep);
      return (line?line.levels:[]).map(l=>({value:l,label:l}));}
  }
  return [];
}
/* ---- where a resource actually is ----
   `requires hidden_resource Arthedain` says nothing about where it bites: the
   name is invented by the mod and only means the handful of regions that carry
   it, out of descr_regions.txt. So the picker gets a marker that names the
   SETTLEMENTS on hover — the thing you recognise on the campaign map — with the
   region and its starting owner beside each. */
function condPlaces(kind,code){
  const v=bldVocab();
  const rows=(kind==='hidden_resource'?v.hidden_resources:v.resources)||[];
  const r=rows.find(x=>(x.code||x)===code);
  return (r&&r.places)||[];
}
// The owner's in-game name if the mod gave it one, else its code.
function condOwnerName(code){
  const f=(bldVocab().factions||[]).find(x=>x.code===code);
  return (f&&f.name)||code;
}
function condWhereHtml(kind,code){
  if(!code)return '';
  const places=condPlaces(kind,code);
  if(!places.length)return `<span class="where none" data-where="${esc(kind)}"
    title="No region in descr_regions.txt carries this, so nothing that requires it can ever be built"
    >∅ nowhere</span>`;
  const rows=places.map(p=>`<div class="wrow"><b>${esc(p.settlement)}</b>
      <span>${esc(p.region)}</span>
      ${p.faction?`<i>${esc(condOwnerName(p.faction))}</i>`:''}</div>`).join('');
  return `<span class="where" data-where="${esc(kind)}">📍 ${places.length} settlement${
      places.length===1?'':'s'}
    <span class="wpop"><div class="whead">${esc(code)}, from
      <code>world/maps/base/descr_regions.txt</code></div>${rows}</span></span>`;
}
function condFactionsHtml(cond,i){
  const chosen=cond.values||[];
  const label=chosen.length?chosen.map(bldFacName).join(', '):'nobody, so this can never be built';
  return `<button class="facbtn" onclick="bldFacPicker(${i})"
      title="Pick the factions and cultures this applies to">
      ${chosen.length?esc(label):'<span class="w-bad">'+esc(label)+'</span>'}</button>`;
}
function wireCondRows(){
  const c=state.bld.clause;
  document.querySelectorAll('[data-cjoin]').forEach(el=>el.onchange=()=>{
    c.conds[+el.dataset.cjoin].join=el.value; condChanged();});
  document.querySelectorAll('[data-cneg]').forEach(el=>el.onchange=()=>{
    c.conds[+el.dataset.cneg].negate=el.checked; condChanged();});
  document.querySelectorAll('[data-craw]').forEach(el=>el.oninput=()=>{
    c.conds[+el.dataset.craw].raw=el.value; condChanged();});
  document.querySelectorAll('[data-cv]').forEach(el=>{
    const [i,slot]=el.dataset.cv.split(':').map(Number);
    const set=()=>{const cond=c.conds[i];
      while(cond.values.length<=slot)cond.values.push('');
      cond.values[slot]=el.value.trim();
      // the level list depends on which building line is picked
      if(cond.kind==='building_present_min_level'&&slot===0)renderCondList();
      else condChanged();};
    el.onchange=set; el.oninput=()=>{const cond=c.conds[i];
      while(cond.values.length<=slot)cond.values.push('');
      cond.values[slot]=el.value.trim();
      // keep "📍 8 settlements" in step with the resource being typed
      if(slot===0&&(cond.kind==='hidden_resource'||cond.kind==='resource')){
        const row=el.closest('.condrow'),old=row&&row.querySelector('[data-where]');
        const html=condWhereHtml(cond.kind,cond.values[0]);
        if(old)old.outerHTML=html; else if(row&&html)el.insertAdjacentHTML('afterend',html);
      }
      condChanged();};
  });
}
function condChanged(){
  const c=state.bld.clause;
  document.getElementById('condText').textContent=bldClauseText(c.conds)||'(no requires clause)';
  bldClauseOwnership();
}
function bldCondRemove(i){
  const c=state.bld.clause;
  c.conds.splice(i,1);
  if(c.conds.length)c.conds[0].join='';
  renderCondList();
}

/* ---- the faction checklist ---- */
function bldFacPicker(i){
  const b=state.bld,c=b.clause;
  c.pick={i,q:''};
  b.stashScroll2=stashPlace();
  b.stash2=document.getElementById('modal').innerHTML;
  renderFacPicker();
}
function renderFacPicker(){
  const c=state.bld.clause,v=bldVocab();
  const cond=c.conds[c.pick.i],chosen=new Set(cond.values||[]);
  // what this condition named when the dialog opened, so a row you have since
  // ticked or unticked is marked as yours
  const was=new Set((((c.was||[])[c.pick.i])||{}).values||[]);
  const edited=code=>chosen.has(code)!==was.has(code);
  const ALL=v.all_keyword||'all';
  const q=(c.pick.q||'').toLowerCase();
  const match=r=>!q||r.code.toLowerCase().includes(q)||(r.name||'').toLowerCase().includes(q);
  const row=(r,isCulture)=>`<label class="facrow${chosen.has(r.code)?' on':''}${
        edited(r.code)?' edited':''}">
      <input type="checkbox" data-fac="${esc(r.code)}" ${chosen.has(r.code)?'checked':''}>
      <span class="fn">${esc(r.name||r.code)}</span>
      <span class="fc">${esc(r.code)}${isCulture?' · culture':r.culture?' · '+esc(r.culture):''}${
        edited(r.code)?(chosen.has(r.code)?' · added by you':' · removed by you'):''}</span>
    </label>`;
  document.getElementById('modal').innerHTML=`
    <h2>Which factions?</h2>
    <div class="mbody">
      <div class="brow"><input id="facQ" placeholder="Filter by name or code…" style="flex:1"
        value="${esc(c.pick.q||'')}">
        <button onclick="bldFacAll(true)">Tick all shown</button>
        <button onclick="bldFacAll(false)">Untick all shown</button></div>
      <label class="facrow allrow${chosen.has(ALL)?' on':''}${edited(ALL)?' edited':''}">
        <input type="checkbox" data-fac="${esc(ALL)}" ${chosen.has(ALL)?'checked':''}>
        <span class="fn">All factions</span>
        <span class="fc">${esc(ALL)}: the wildcard. Ticking it makes the rest moot.</span></label>
      <h4 class="fgh">Factions</h4>
      <div class="faclist">${(v.factions||[]).filter(match).map(r=>row(r,false)).join('')
        ||'<span class="count">None match</span>'}</div>
      <h4 class="fgh">Cultures <span class="count">Covers every faction of that culture</span></h4>
      <div class="faclist">${(v.cultures||[]).filter(match).map(r=>row(r,true)).join('')
        ||'<span class="count">None match</span>'}</div>
      <div id="facOwn"></div>
    </div>
    <div class="foot">
      <span class="count" id="facCount"></span>
      <button class="primary" onclick="bldFacDone()">Done</button>
    </div>`;
  const qbox=document.getElementById('facQ');
  qbox.oninput=()=>{c.pick.q=qbox.value;renderFacPicker();
    const n=document.getElementById('facQ');n.focus();n.setSelectionRange(n.value.length,n.value.length);};
  document.querySelectorAll('[data-fac]').forEach(cb=>cb.onchange=()=>{
    const set=new Set(cond.values||[]);
    cb.checked?set.add(cb.dataset.fac):set.delete(cb.dataset.fac);
    cond.values=[...set];
    renderFacPicker();});
  document.getElementById('facCount').textContent=
    `${(cond.values||[]).length} selected`;
  bldFacOwnership(cond.values||[]);
}
function bldFacAll(on){
  const c=state.bld.clause,cond=c.conds[c.pick.i];
  const set=new Set(cond.values||[]);
  document.querySelectorAll('[data-fac]').forEach(cb=>{
    if(cb.closest('.allrow'))return;         // never bulk-tick the wildcard
    on?set.add(cb.dataset.fac):set.delete(cb.dataset.fac);});
  cond.values=[...set];
  renderFacPicker();
}
function bldFacDone(){
  const b=state.bld;
  document.getElementById('modal').innerHTML=b.stash2; b.stash2=null;
  b.clause.pick=null;
  usePlace(b.stashScroll2); b.stashScroll2=null;
  renderClauseDialog();
}

/* ---- "…but this unit doesn't belong to them" ----
   A recruit_pool naming a faction is only half of it: the unit must also list
   that faction in its EDU `ownership`, and its battle model needs a texture for
   it, or the building trains nothing / trains something untextured. Both fail
   silently in game, so they are checked as soon as a faction is ticked. */
async function bldOwnCheck(unit,factions){
  return (await bldOwnChecks([unit],factions))[0]||null;
}
// The same question for a whole bulk selection, asked in ONE request: the
// endpoint already takes a list of checks, and a hundred round trips for a
// hundred ticked units is a hundred round trips.
async function bldOwnChecks(units,factions){
  const b=state.bld,facs=[...factions].sort();
  const key=u=>u+'|'+facs.join(',');
  const want=[...new Set(units)].filter(u=>u&&!(key(u) in b.own));
  if(want.length){
    try{
      const r=await api.post('/api/buildings/ownership',
        {mod:b.mod,checks:want.map(u=>({unit:u,factions:facs}))});
      const rows=r.rows||[];
      want.forEach((u,i)=>{ b.own[key(u)]=rows[i]||null; });
    }catch(e){ want.forEach(u=>{ b.own[key(u)]=null; }); }
  }
  return [...new Set(units)].map(u=>b.own[key(u)]).filter(Boolean);
}
function bldOwnHtml(row){
  if(!row)return '';
  if(!row.known)return `<div class="ownwarn bad">“${esc(row.unit)}” is not a unit in
    this mod’s EDU, so nothing will ever be recruited from this pool.</div>`;
  const bits=[],fixes=[];
  if(row.missing_ownership.length){
    bits.push(`<b>${row.missing_ownership.map(bldFacName).map(esc).join(', ')}</b> ${
      row.missing_ownership.length===1?'is':'are'} not in
      <code>${esc(row.unit)}</code>’s EDU <code>ownership</code>, so the building
      would train nothing for ${row.missing_ownership.length===1?'them':'those'}`);
    fixes.push('the ownership line is extended');
  }
  if(row.missing_textures.length){
    bits.push(`its battle model has no texture for
      <b>${row.missing_textures.map(esc).join(', ')}</b>, so their soldiers would
      turn up untextured`);
    fixes.push('the missing textures are copied from a faction that has them');
  }
  if(!bits.length)return `<div class="ownwarn ok">Every faction here can already
    field <code>${esc(row.unit)}</code>.</div>`;
  return `<div class="ownwarn">${bits.join('; and ')}. Saving fixes
    ${bits.length===1?'that':'both'}: ${fixes.join(', and ')}. Untick
    <b>Fix unit ownership</b> at the bottom of the editor to leave it alone.</div>`;
}
// Over many units the individual warnings would be a wall of text, so they are
// rolled into one line per problem naming the units — the answer you want is
// "which of these twelve can't the Danes actually field", not twelve paragraphs.
function bldOwnManyHtml(rows){
  const bad=rows.filter(r=>r&&(!r.known||r.missing_ownership.length||r.missing_textures.length));
  if(!rows.length)return '';
  if(!bad.length)return `<div class="ownwarn ok">Every faction here can already field
    all ${rows.length} of these units.</div>`;
  if(bad.length===1&&rows.length===1)return bldOwnHtml(bad[0]);
  const unknown=bad.filter(r=>!r.known).map(r=>r.unit);
  const noOwn=bad.filter(r=>r.known&&r.missing_ownership.length);
  const noTex=bad.filter(r=>r.known&&r.missing_textures.length);
  const list=us=>`<code>${us.slice(0,12).map(esc).join('</code> <code>')}</code>${
    us.length>12?` <span class="count">+${us.length-12} more</span>`:''}`;
  const bits=[];
  if(unknown.length)bits.push(`<div><b class="w-bad">${unknown.length}</b> not in this mod’s
    EDU at all, so nothing will ever be recruited from ${unknown.length===1?'that pool':'those pools'}:
    ${list(unknown)}</div>`);
  if(noOwn.length)bits.push(`<div><b>${noOwn.length}</b> ${noOwn.length===1?'does':'do'} not list
    every one of those factions in <code>ownership</code>, so the building would train nothing for
    them: ${list(noOwn.map(r=>r.unit))}</div>`);
  if(noTex.length)bits.push(`<div><b>${noTex.length}</b> ${noTex.length===1?'has':'have'} no battle-model
    texture for some of them, so their soldiers would turn up untextured:
    ${list(noTex.map(r=>r.unit))}</div>`);
  return `<div class="ownwarn ${unknown.length?'bad':''}">${bits.join('')}
    <div class="count" style="margin-top:5px">${docPoints(
      'Saving fixes the ownership and copies the missing textures.',[
      'Untick <b>Fix unit ownership</b> at the bottom of the editor to leave them alone.',
      'A unit the EDU doesn’t have cannot be fixed from here.'])}</div></div>`;
}
async function bldOwnBox(id,facs){
  const c=state.bld.clause;
  const units=(c&&(c.units&&c.units.length?c.units:(c.unit?[c.unit]:[])))||[];
  if(!units.length)return;
  const box=document.getElementById(id);
  if(!box)return;
  if(!facs.length){box.innerHTML='';return;}
  const rows=await bldOwnChecks(units,facs);
  // the dialog may have moved on while the request was out
  if(state.bld.clause!==c)return;
  box.innerHTML=units.length===1?bldOwnHtml(rows[0]):bldOwnManyHtml(rows);
}
async function bldClauseOwnership(){
  const c=state.bld.clause; if(!c)return;
  const facs=[].concat(...c.conds.filter(x=>x.kind==='factions'&&!x.negate)
    .map(x=>x.values||[]));
  return bldOwnBox('condOwn',facs);
}
async function bldFacOwnership(facs){ return bldOwnBox('facOwn',facs); }

/* ---- add units to this level's recruitment ----
   A level is filled out a dozen units at a time, not one, so the picker TICKS
   rather than adds: a row you tick stays ticked while you keep filtering, and
   one button adds the lot. The count in the button is the whole selection, not
   just what the current filter shows. */
function bldAddPoolDialog(){
  const b=state.bld,lv=b.work.levels[b.lvl];
  const already=new Set([...lv.caps,...lv.fcaps].filter(c=>c.pool&&!c.del)
    .map(c=>c.pool.unit.toLowerCase()));
  const above=b.work.levels.length-1-b.lvl, twin=bldTwin(), twinLv=bldTwinLevel();
  // The numbers used to be fixed and invisible, so every added unit had to be
  // corrected row by row afterwards. They are the dialog's own fields now, and
  // they carry over to the tiers above with a per-tier step.
  b.pick={q:'',faction:'',already,picked:new Set(),
          nums:{initial:'1',per_turn:'0.5',maximum:'2',experience:'0'},
          tiers:false,bump:Object.assign({},BLD_TIER_BUMP),mirror:false};
  const modal=document.getElementById('modal');
  b.stashScroll=stashPlace();
  b.stash=modal.innerHTML;                     // put the editor back on cancel
  modal.innerHTML=`<h2>Add units to ${esc(b.d.levels[b.lvl].label)}</h2>
    <div class="mbody">
      <div class="basebar"><input id="bpQ" placeholder="Filter ${esc(state.src)}’s units…"
          oninput="bldPickFilter()"><select id="bpFac" onchange="bldPickFilter()">
          <option value="">All factions</option>${
            (state.data.factions||[]).slice().sort((a,c)=>facLabel(a).localeCompare(facLabel(c)))
              .map(f=>`<option value="${esc(f)}">${esc(facLabel(f))}</option>`).join('')}
        </select>
        <button onclick="bldPickAll(true)">Tick all shown</button>
        <button onclick="bldPickAll(false)">Untick all</button></div>
      <div class="baselist" style="max-height:260px" id="bpList"></div>

      <div class="bsec" style="margin-top:10px"><h4>Numbers each new pool starts with</h4>
        <div class="brow bpnums">
          <label>${qm(POOL_HELP.initial,POOL_LABEL.initial)}${POOL_LABEL.initial}${
            numBox('data-bp="initial"',b.pick.nums.initial,'pool')}</label>
          <label>${qm(POOL_HELP.per_turn,POOL_LABEL.per_turn)}${POOL_LABEL.per_turn}${
            numBox('data-bp="per_turn"',b.pick.nums.per_turn,'turns',
              `<span class="turns">= ${esc(poolTurns(b.pick.nums.per_turn))}</span>`)}</label>
          <label>${qm(POOL_HELP.maximum,POOL_LABEL.maximum)}${POOL_LABEL.maximum}${
            numBox('data-bp="maximum"',b.pick.nums.maximum,'pool')}</label>
          <label>${qm(POOL_HELP.experience,POOL_LABEL.experience)}${POOL_SHORT.experience}${
            numBox('data-bp="experience"',b.pick.nums.experience,'1')}</label>
        </div>

        ${above>0?`<label class="chk" title="${esc(bldTiersAboveNames())}">
          <input type="checkbox" id="bpTiers" onchange="bldPickOpt('tiers',this.checked)">
          Add to the <b>${above}</b> tier(s) above this one as well
          <span class="count">${esc(bldTiersAboveNames())}</span></label>
        <div class="brow bpnums" id="bpBump" style="display:none">
          <span class="k">Each tier up by</span>
          <label>${POOL_LABEL.initial}${numBox('data-bpb="initial"',b.pick.bump.initial,'1')}</label>
          <label>${POOL_LABEL.per_turn}${numBox('data-bpb="per_turn"',b.pick.bump.per_turn,'0.05')}</label>
          <label>${POOL_LABEL.maximum}${numBox('data-bpb="maximum"',b.pick.bump.maximum,'1')}</label>
          <label>${POOL_SHORT.experience}${numBox('data-bpb="experience"',b.pick.bump.experience,'1')}</label>
        </div>`
        :'<div class="bnote">This is the top tier, so there is nothing above to copy into.</div>'}

        ${twin&&twinLv?`<label class="chk"><input type="checkbox" id="bpMirror"
            onchange="bldPickOpt('mirror',this.checked)">
          Mirror into <code>${esc(twin)}</code> · <code>${esc(twinLv)}</code>
          (the ${esc(b.d.settlement==='city'?'castle':'city')} half of this building)</label>`
        :`<div class="bnote">No city/castle twin the tool can match for this line, so there is
          nothing to mirror into.</div>`}
      </div>

      <div class="bnote">${docPoints('Each new pool is gated to that unit’s own '
        +'<code>ownership</code>, so only the factions that can field it are offered it here.',[
        'Open <b>Requirements</b> on the row to widen or narrow that.',
        'Or tick several rows and use <b>Bulk edit</b>.'])}</div>
    </div>
    <div class="foot"><span class="count" id="bpCount"></span>
      <button onclick="bldPickCancel()">Cancel</button>
      <button class="primary" id="bpAdd" onclick="bldAddPicked()">Add</button></div>`;
  wireNumBoxes(modal);
  modal.querySelectorAll('[data-bp],[data-bpb]').forEach(inp=>{
    const bump=inp.dataset.bpb!==undefined;
    inp.addEventListener('input',()=>{
      (bump?b.pick.bump:b.pick.nums)[bump?inp.dataset.bpb:inp.dataset.bp]=inp.value;
    });
  });
  bldPickRender();
}
function bldPickOpt(key,on){
  state.bld.pick[key]=on;
  const box=document.getElementById('bpBump');
  if(box&&key==='tiers')box.style.display=on?'':'none';
  bldPickRender();
}
// Shared by the add-unit picker and the cross-tree compare panel: both stash the
// editor's markup on the way in and hand it back here.
function bldPickCancel(){
  const modal=document.getElementById('modal');
  modal.innerHTML=state.bld.stash; state.bld.stash=null; state.bld.cmp=null;
  state.bld.vc=null;
  usePlace(state.bld.stashScroll); state.bld.stashScroll=null;
  bldRedrawLevel();
}
// The rows the filter boxes are letting through right now.
function bldPickShown(){
  const p=state.bld.pick;
  return (state.data.units||[]).filter(u=>
    (!p.q||u.name.toLowerCase().includes(p.q)||u.type.toLowerCase().includes(p.q))
    &&(!p.faction||u.ownership.includes(p.faction))).slice(0,300);
}
function bldPickFilter(){
  const p=state.bld.pick;
  p.q=(document.getElementById('bpQ').value||'').trim().toLowerCase();
  p.faction=document.getElementById('bpFac').value;
  bldPickRender();
}
function bldPickToggle(type){
  const p=state.bld.pick;
  p.picked.has(type)?p.picked.delete(type):p.picked.add(type);
  bldPickRender();
}
function bldPickAll(on){
  const p=state.bld.pick;
  bldPickShown().forEach(u=>on?p.picked.add(u.type):p.picked.delete(u.type));
  bldPickRender();
}
function bldPickRender(){
  const p=state.bld.pick,already=p.already;
  const units=bldPickShown();
  document.getElementById('bpList').innerHTML=units.map(u=>`
    <div class="baserow ${p.picked.has(u.type)?'on':''}" onclick="bldPickToggle('${q1(esc(u.type))}')">
      <label class="pick" onclick="event.preventDefault()"><input type="checkbox"
        ${p.picked.has(u.type)?'checked':''}></label>
      <img loading="lazy" onerror="iconRetry(this)" src="${iconUrl(state.src,u.type)}">
      <div><div class="bn">${esc(u.name)}${already.has(u.type.toLowerCase())
        ?' <span class="badge">already here</span>':''}</div>
        <div class="bs">${esc(u.type)} · ${esc(u.kind||u.category||'')}</div></div>
    </div>`).join('')||'<div class="caprow"><span class="count">No units match.</span></div>';
  const n=p.picked.size;
  const cnt=document.getElementById('bpCount');
  if(cnt)cnt.textContent=n?`${n} ticked${units.length<n?', some of them outside the filter':''}`
                          :'Tick the units to add.';
  const add=document.getElementById('bpAdd');
  if(add){add.textContent=n?`Add ${n} unit${n===1?'':'s'}`:'Add';add.disabled=!n;}
}
/* A pool with no clause is trained by EVERY faction that can build the level,
   which is almost never what adding one unit means — and for the factions that
   don't own the unit the building silently trains nothing. So a new pool starts
   gated to the unit's own EDU `ownership`: the set that can actually field it.
   It is a starting point, not a rule — the row's Requirements button opens the
   clause like any other. A unit with no ownership gets no clause, because an
   empty `factions { }` would train nothing for anyone; the editor's existing
   "no ownership" warning is the thing to fix there. */
const bldPickedUnit=type=>(state.data.units||[]).find(x=>x.type===type);
function bldPoolOwnership(type){
  const u=bldPickedUnit(type);
  const own=[...new Set((u&&u.ownership)||[])];
  return own.length?[{join:'',negate:false,kind:'factions',values:own,raw:''}]:[];
}
// One new pool row, appended to the level. Returns it, so the caller can say
// what it did — nothing here touches the DOM, because adding twenty units must
// redraw once rather than twenty times.
function bldAddPoolRow(type,lvIndex,nums,conds){
  const b=state.bld,lv=b.work.levels[lvIndex==null?b.lvl:lvIndex];
  if(!lv)return null;
  // A copy of an existing pool brings that pool's own clause; a unit added from
  // the picker gets its EDU ownership instead (see bldPoolOwnership).
  const raw=(nums&&nums.requires!==undefined)?String(nums.requires||''):null;
  conds=conds||(raw===null?bldPoolOwnership(type):[]);
  // `d.units` only indexes the units this line ALREADY trains — the server sends
  // it once per line rather than the mod's whole EDU. A unit added here is by
  // definition not in it yet, so the row would call itself missing from the EDU
  // until the next save. It came out of the picker, which reads that same EDU.
  const u=bldPickedUnit(type);
  if(u&&b.d&&b.d.units&&!b.d.units[type.toLowerCase()])
    b.d.units[type.toLowerCase()]={type:u.type,name:u.name||u.type,kind:u.kind,
      class:u.class,category:u.category,ownership:[...(u.ownership||[])],
      mercenary:!!u.mercenary,eop:!!u.eop,missing:false};
  // A clause copied verbatim from another row goes back as its ORIGINAL text:
  // re-emitting it from structure would quietly re-tidy a clause nobody edited.
  const edited=raw===null||!!(conds&&conds.length);
  const row={line:null,keyword:'recruit_pool',args:'',
    requires:edited?bldClauseText(conds):raw,conds:conds||[],condEdited:edited,
    bonus:false,value:'',
    pool:Object.assign({unit:type,initial:'1',per_turn:'0.5',maximum:'2',experience:'0'},
                       nums?{initial:nums.initial,per_turn:nums.per_turn,
                             maximum:nums.maximum,experience:nums.experience}:{},
                       {unit:type}),
    comment:'',faction:false,del:false};
  lv.caps.push(row);
  return row;
}
function bldAddPool(type){ bldAddPicked([type]); }
/* Commit the picker's ticks. The rows land ticked in bulk edit as well, because
   the thing you do straight after adding twelve units is give all twelve the
   same requires clause — and hunting them back down in a list of three hundred
   is exactly the work this is meant to save. */
function bldAddPicked(types){
  const b=state.bld;
  const list=types||[...((b.pick&&b.pick.picked)||[])];
  if(!list.length)return;
  const p=b.pick||{};
  const nums=p.nums||{initial:'1',per_turn:'0.5',maximum:'2',experience:'0'};
  const rows=list.map(t=>bldAddPoolRow(t,b.lvl,nums));
  // …and the same units into the tiers above and the twin building, on the same
  // clause each row just got, so one trip through the picker fills the chain
  let up=0,mirrored=0;
  if(p.tiers){
    for(let j=b.lvl+1;j<b.work.levels.length;j++){
      rows.forEach(r=>{
        if(bldHasUnit(j,r.pool.unit))return;
        bldAddPoolRow(r.pool.unit,j,bldBumped(r.pool,j-b.lvl,p.bump),
                      JSON.parse(JSON.stringify(r.conds||[])));
        up++;
      });
    }
  }
  if(p.mirror){
    const twin=bldTwin();
    for(let j=b.lvl;j<b.work.levels.length;j++){
      const tl=bldTwinLevel(j);
      if(!twin||!tl||(j>b.lvl&&!p.tiers))break;
      rows.forEach(r=>{
        const pool=j===b.lvl?r.pool:bldBumped(r.pool,j-b.lvl,p.bump);
        if(bldStagePool(twin,tl,Object.assign({},pool,{unit:r.pool.unit}),r.conds))mirrored++;
      });
    }
  }
  // A gated pool can fall outside the faction filter that is narrowing the list,
  // and a unit that vanishes the moment you add it looks like the add failed.
  if(rows.some(r=>!bldPoolMatches(r))&&b.poolFac)b.poolFac.clear();
  b.bulk=b.bulk||{sel:new Set()};
  b.bulk.on=true; b.bulk.sel=new Set(rows);
  // the picker replaced the editor's markup — rebuild it, then show the new rows
  const modal=document.getElementById('modal');
  if(b.stash){ modal.innerHTML=b.stash; b.stash=null; }
  usePlace(b.stashScroll); b.stashScroll=null;
  renderBuildingEditor();
  const label=b.d.levels[b.lvl].label;
  const gated=rows.filter(r=>r.conds.length).length;
  const extra=(up?` +${up} on the tier(s) above`:'')
             +(mirrored?` +${mirrored} staged in ${bldTwin()}`:'');
  toast(rows.length===1
    ? `${list[0]} added to ${label}${rows[0].conds.length
        ? `, restricted to its ${rows[0].conds[0].values.length} owning faction(s)`
        : ', and it has no ownership, so anyone here can train it'}${extra}`
    : `${rows.length} units added to ${label}. ${gated} gated to their own ownership${
        gated<rows.length?`, ${rows.length-gated} with no ownership to gate to`:''
      }.${extra} They are ticked for bulk edit.`,4600);
}

/* =========================================================================
   Recruitment checks, mirroring and cross-tree editing

   Three things are invisible one level at a time and obvious across a whole
   line, and all three are mistakes a mod actually ships:

     * a unit recruitable at tier 2 that silently stops being recruitable when
       the player upgrades to tier 3 — the building "loses" units as it grows;
     * a unit the city half trains and the castle half does not, when the two are
       meant to be the same building;
     * the same unit listed twice in one level, which the game reads as two pools
       feeding one recruitment slot.

   The server works them out (buildings.line_checks); everything here is the
   panel that shows them and the one-click fixes. A fix never writes: it stages
   rows into the working copy exactly as adding a unit by hand does, so Preview,
   Save, Ctrl+Z and the log all behave the same.
   ========================================================================= */
async function bldLoadChecks(force){
  const b=state.bld,line=b&&b.line; if(!line)return;
  if(b.checks&&b.checks.line===line&&!force)return;
  try{
    const r=await api.get(`/api/buildings/checks?mod=${enc(b.mod)}&line=${enc(line)}`);
    if(state.bld!==b||b.line!==line)return;          // moved on while in flight
    b.checks=(r.lines||[])[0]||{line,gaps:[],dupes:[],mirror:[],level_pairs:{}};
  }catch(e){ if(state.bld!==b||b.line!==line)return; b.checks={line,error:''+e}; }
  // The whole body, not just the panel: knowing the twin is what puts the ⇄
  // button on every pool row, and the answer only lands after the first draw.
  if(document.getElementById('bldChecks'))bldRenderBodyNow();
  // …and the header's "Compare city / castle" button, which cannot know whether
  // there IS a twin until this answer arrives.
  const btn=document.getElementById('bldVarBtn');
  if(btn)btn.innerHTML=bldVarBtnHtml();
}
// The twin line's name, and the level in it that mirrors the one on screen.
function bldTwin(){ return ((state.bld||{}).checks||{}).twin||''; }
function bldTwinLevel(i){
  const b=state.bld,ck=b.checks||{};
  const lv=b.work.levels[i==null?b.lvl:i];
  return lv?((ck.level_pairs||{})[lv.name]||''):'';
}
function bldChecksHtml(){
  return `<div class="bsec" id="bldChecks">${bldChecksInner()}</div>`;
}
/* Edits staged against other building lines are invisible in this form — they
   belong to buildings that are not on screen — so they get a panel of their own.
   Without it, Save would write changes the page never showed. */
function bldAlsoHtml(){
  const also=(state.bld.work||{}).also||{};
  const lines=Object.keys(also).filter(l=>
    Object.values(also[l]).some(rows=>rows.length));
  if(!lines.length)return '';
  return `<div class="bsec"><h4>Also changing <span class="n">${bldAlsoCount()}</span>
      <span class="count">in ${lines.length} other building line(s)</span>
      <button style="margin-left:auto" onclick="bldAlsoClear()">Drop these</button></h4>
    ${lines.map(l=>`<div class="ckgroup"><div class="ckhead"><code>${esc(l)}</code></div>
      <div class="cklist">${Object.entries(also[l]).filter(([,r])=>r.length).map(([lvl,rows])=>`
        <div class="ckrow"><div class="ckwho"><div class="un">${esc(lvl)}</div>
          <div class="ut">${rows.map(r=>`${esc(r.pool.unit)} <span class="count">${
            r.line==null?'new':'edited'}</span>`).join(' · ')}</div></div>
          <button onclick="bldAlsoDrop('${q1(esc(l))}','${q1(esc(lvl))}')">Drop</button></div>`
        ).join('')}</div></div>`).join('')}
    <div class="bnote">These are written in the same pass as this building, so Preview shows them
      and one Undo takes the lot back.</div></div>`;
}
function bldAlsoDrop(line,level){
  const also=(state.bld.work||{}).also||{};
  if(also[line])delete also[line][level];
  if(also[line]&&!Object.keys(also[line]).length)delete also[line];
  bldTouched(); renderBuildingEditor();
}
function bldAlsoClear(){
  state.bld.work.also={};
  bldTouched(); renderBuildingEditor();
}
function bldChecksInner(){
  const b=state.bld,ck=b.checks;
  if(!ck)return `<h4>Checks</h4><div class="bnote">Looking over the whole line…</div>`;
  if(ck.error)return `<h4>Checks</h4><div class="bnote w-bad">${esc(ck.error)}</div>`;
  const lvl=b.lvl, lv=b.work.levels[lvl];
  const gaps=(ck.gaps||[]).filter(g=>g.missing.includes(lvl)||g.first===lvl);
  const mir=(ck.mirror||[]).find(m=>m.level_index===lvl);
  const dupes=(ck.dupes||[]).filter(d=>d.level_index===lvl);
  const total=(ck.gaps||[]).length+(ck.dupes||[]).length+(ck.mirror||[]).length;
  if(!total)return `<h4>Checks <span class="badge good">clean</span></h4>
    <div class="bnote">Every unit this line trains is still trained at every tier above the one
      it starts at${ck.twin?`, and it matches <code>${esc(ck.twin)}</code>`:''}, with nothing listed twice.</div>`;
  const rows=[];

  if(gaps.length)rows.push(`<div class="ckgroup"><div class="ckhead">
      <b class="w-warn">${gaps.length}</b> unit(s) stop being recruitable further up this line
      <button onclick="bldFillGaps()">Fill every gap</button></div>
    <div class="cklist">${gaps.map(g=>`<div class="ckrow">
      <img loading="lazy" onerror="iconRetry(this)" src="${iconUrl(state.src,g.pool.unit)}" alt="">
      <div class="ckwho"><div class="un">${esc(g.unit)}</div>
        <div class="ut">trained at ${g.present.map(bldLevelLabel).map(esc).join(', ')}
          Missing from <b>${g.missing_levels.map((n,i)=>esc(bldLevelLabel(g.missing[i]))).join(', ')}</b>.</div></div>
      <button onclick="bldFillGap('${q1(esc(g.unit))}')">Add to the missing tier(s)</button>
    </div>`).join('')}</div></div>`);

  if(mir)rows.push(`<div class="ckgroup"><div class="ckhead">
      This tier differs from <code>${esc(ck.twin)}</code> · <code>${esc(mir.twin)}</code>
      <span class="count">${mir.only_here.length} only here, ${mir.only_there.length} only there</span></div>
    <div class="cklist">
      ${mir.only_here.map(p=>bldMirrorRow(p,'push')).join('')}
      ${mir.only_there.map(p=>bldMirrorRow(p,'pull')).join('')}
    </div>
    <div class="brow" style="margin-top:6px">
      <button onclick="bldMirrorAll('push')">Copy all ${mir.only_here.length} into ${esc(ck.twin)}</button>
      <button onclick="bldMirrorAll('pull')">Bring all ${mir.only_there.length} over here</button>
    </div></div>`);

  if(dupes.length)rows.push(`<div class="ckgroup"><div class="ckhead">
      <b class="w-warn">${dupes.length}</b> unit(s) listed more than once in this tier</div>
    <div class="cklist">${dupes.map(d=>`<div class="ckrow">
      <img loading="lazy" onerror="iconRetry(this)" src="${iconUrl(state.src,d.unit)}" alt="">
      <div class="ckwho"><div class="un">${esc(d.unit)} <span class="badge">×${d.count}</span></div>
        <div class="ut">${d.same_requires
          ? '<span class="w-warn">Every copy has the same requirements, so one of them does nothing.</span>'
          : 'The copies have different requirements, so this is probably deliberate (one per faction).'}</div></div>
      <button onclick="bldJumpPool('${q1(esc(d.unit))}')">Show the rows</button>
    </div>`).join('')}</div></div>`);

  const elsewhere=total-(gaps.length+dupes.length+(mir?1:0));
  return `<h4>Checks <span class="n">${total}</span>
      <span class="count">across the whole line</span>
      <button style="margin-left:auto" onclick="bldLoadChecks(true)">Re-check</button></h4>
    ${rows.join('')||'<div class="bnote">Nothing to flag on this tier.</div>'}
    ${elsewhere>0?`<div class="bnote">${elsewhere} more finding(s) on other tiers of this line.
      Switch tier above to see them.</div>`:''}`;
}
// Scroll the recruitment list to a unit and flash its rows — the useful answer
// to "this unit is listed twice" is being shown both of them.
function bldJumpPool(unit){
  const key=unit.toLowerCase();
  const idx=bldCapList().map((c,i)=>[c,i])
    .filter(([c])=>c.pool&&c.pool.unit.toLowerCase()===key).map(([,i])=>i);
  if(!idx.length)return toast('Those rows are hidden by the faction filter.');
  const host=document.getElementById('bldPools'); if(!host)return;
  let first=null;
  idx.forEach(i=>{
    const el=host.querySelector(`[data-cap="${i}"]`); if(!el)return;
    first=first||el;
    el.classList.add('flash');
    setTimeout(()=>el.classList.remove('flash'),1600);
  });
  if(first)first.scrollIntoView({block:'center'});
  else toast('Those rows are hidden by the faction filter.');
}
function bldMirrorRow(p,dir){
  return `<div class="ckrow">
    <img loading="lazy" onerror="iconRetry(this)" src="${iconUrl(state.src,p.unit)}" alt="">
    <div class="ckwho"><div class="un">${esc(p.unit)}</div>
      <div class="ut">${dir==='push'?'only in this settlement type':'only in the twin'}
        · ${POOL_LABEL.initial} ${esc(p.initial)}, ${POOL_LABEL.per_turn} ${esc(p.per_turn)},
        ${POOL_LABEL.maximum} ${esc(p.maximum)}, ${POOL_SHORT.experience} ${esc(p.experience)}</div></div>
    <button onclick="bldMirrorOne('${q1(esc(p.unit))}','${dir}')">${
      dir==='push'?'Copy to the twin':'Add here'}</button></div>`;
}

/* ---- staging a pool into ANOTHER building line ----
   Rows go into work.also keyed by line then level. `line:null` marks a brand-new
   capability, exactly as a row added by hand in this editor does, so the server
   plans it through the same path. */
function bldAlso(line,level){
  const also=state.bld.work.also||(state.bld.work.also={});
  const byLevel=also[line]||(also[line]={});
  return byLevel[level]||(byLevel[level]=[]);
}
function bldAlsoCount(){
  const also=(state.bld.work||{}).also||{};
  return Object.values(also).reduce((n,byLevel)=>
    n+Object.values(byLevel).reduce((m,rows)=>m+rows.length,0),0);
}
function bldAlsoLines(){ return Object.keys((state.bld.work||{}).also||{}); }
// Whether the twin building already trains a unit at one of its levels — a
// mirror that duplicates what is there is exactly the "same unit twice" mistake
// the checks panel above flags.
function bldTwinHas(level,unit){
  const t=((state.bld.checks||{}).twin_units||{})[level]||[];
  return t.includes(unit.toLowerCase());
}
function bldStagePool(line,level,pool,conds){
  if(line===bldTwin()&&bldTwinHas(level,pool.unit))return false;
  const rows=bldAlso(line,level);
  if(rows.some(r=>r.pool.unit.toLowerCase()===pool.unit.toLowerCase()))return false;
  rows.push({line:null,keyword:'recruit_pool',args:'',
    requires:conds?bldClauseText(conds):(pool.requires||''),
    conds:conds||[],condEdited:!!conds,bonus:false,value:'',
    pool:{unit:pool.unit,initial:pool.initial,per_turn:pool.per_turn,
          maximum:pool.maximum,experience:pool.experience},
    comment:'',faction:false,del:false});
  return true;
}
// A pool already in THIS line's working copy, by unit and level. Used to avoid
// adding a second copy of something the level already trains.
function bldHasUnit(lvIndex,unit){
  const lv=state.bld.work.levels[lvIndex]; if(!lv)return false;
  const key=unit.toLowerCase();
  return [...lv.caps,...lv.fcaps].some(c=>c.pool&&!c.del&&c.pool.unit.toLowerCase()===key);
}

// "the tiers above" is only meaningful if it says WHICH — a barracks line can
// be five levels deep and the names are what the modder knows them by.
function bldTiersAboveNames(){
  const b=state.bld;
  return (b.d.levels||[]).slice(b.lvl+1).map((l,i)=>bldLevelLabel(b.lvl+1+i)).join(', ');
}
/* ---- fill the tiers above ---- */
// The numbers a mod gives a unit climb with the building, so a propagated copy
// climbs too rather than repeating tier 1's figures all the way up.
const BLD_TIER_BUMP={initial:0,per_turn:0,maximum:1,experience:0};
function bldBumped(pool,steps,bump){
  const num=(v,d)=>{const n=parseFloat(v);return isFinite(n)?n:d;};
  const b=bump||BLD_TIER_BUMP;
  return {unit:pool.unit,
    initial:numFmt(Math.max(0,num(pool.initial,1)+steps*num(b.initial,0))),
    per_turn:numFmt(Math.max(0,num(pool.per_turn,0.5)+steps*num(b.per_turn,0))),
    maximum:numFmt(Math.max(0,num(pool.maximum,2)+steps*num(b.maximum,0))),
    experience:numFmt(Math.max(0,Math.min(9,num(pool.experience,0)+steps*num(b.experience,0)))),
    requires:pool.requires};
}
function bldFillGap(unit){
  const b=state.bld,ck=b.checks||{};
  const g=(ck.gaps||[]).find(x=>x.unit===unit); if(!g)return;
  const n=bldFillGapRows(g);
  bldTouched(); renderBuildingEditor();
  toast(n?`${unit} added to ${n} tier(s).`:`${unit} is already on every tier.`);
}
function bldFillGaps(){
  const b=state.bld,ck=b.checks||{};
  let n=0;
  (ck.gaps||[]).forEach(g=>{n+=bldFillGapRows(g);});
  bldTouched(); renderBuildingEditor();
  toast(n?`${n} pool(s) added so nothing drops out as the building upgrades.`
         :'Nothing to fill.');
}
function bldFillGapRows(g){
  const b=state.bld;
  let n=0;
  for(const i of g.missing){
    if(i>=b.work.levels.length||bldHasUnit(i,g.unit))continue;
    bldAddPoolRow(g.unit,i,bldBumped(g.pool,i-g.pool.level_index),null);
    n++;
  }
  return n;
}

/* ---- mirror into the city/castle twin ---- */
function bldMirrorOne(unit,dir){
  const b=state.bld,ck=b.checks||{};
  const m=(ck.mirror||[]).find(x=>x.level_index===b.lvl); if(!m)return;
  const list=dir==='push'?m.only_here:m.only_there;
  const p=list.find(x=>x.unit===unit); if(!p)return;
  if(!bldMirrorApply(p,dir,m))return toast(`${unit} is already there.`);
  bldTouched(); renderBuildingEditor();
  toast(dir==='push'
    ? `${unit} staged into ${ck.twin} · ${m.twin}. It is saved with the rest.`
    : `${unit} added to this tier.`);
}
function bldMirrorAll(dir){
  const b=state.bld,ck=b.checks||{};
  const m=(ck.mirror||[]).find(x=>x.level_index===b.lvl); if(!m)return;
  const list=dir==='push'?m.only_here:m.only_there;
  let n=0; list.forEach(p=>{ if(bldMirrorApply(p,dir,m))n++; });
  if(!n)return toast('Nothing left to copy.');
  bldTouched(); renderBuildingEditor();
  toast(dir==='push'?`${n} unit(s) staged into ${ck.twin}.`:`${n} unit(s) added to this tier.`);
}
function bldMirrorApply(p,dir,m){
  const b=state.bld,ck=b.checks||{};
  if(dir==='push')return bldStagePool(ck.twin,m.twin,p,null);
  if(bldHasUnit(b.lvl,p.unit))return false;
  bldAddPoolRow(p.unit,b.lvl,p,null);
  return true;
}
// The ⇄ button on a pool row: put THIS row into the twin building at the tier
// that faces the one on screen.
function bldMirrorRowNow(i){
  const b=state.bld,c=bldCapList()[i]; if(!c||!c.pool)return;
  const twin=bldTwin(),level=bldTwinLevel();
  if(!twin||!level)return toast('This line has no city/castle twin the tool can match.');
  const ok=bldStagePool(twin,level,Object.assign({},c.pool,{requires:c.requires}),
                        c.condEdited?c.conds:null);
  if(!ok)return toast(bldTwinHas(level,c.pool.unit)
    ? `${twin} · ${level} already trains ${c.pool.unit}.`
    : `${c.pool.unit} is already staged for ${twin}.`);
  bldTouched(); renderBuildingEditor();
  toast(`${c.pool.unit} staged into ${twin} · ${level}. It is saved with the rest.`,4000);
}
// …and the same row pushed up every tier above this one.
function bldTiersRowNow(i){
  const b=state.bld,c=bldCapList()[i]; if(!c||!c.pool)return;
  let n=0;
  for(let j=b.lvl+1;j<b.work.levels.length;j++){
    if(bldHasUnit(j,c.pool.unit))continue;
    bldAddPoolRow(c.pool.unit,j,bldBumped(Object.assign({},c.pool,{requires:c.requires}),j-b.lvl),
                  c.condEdited?c.conds:null);
    n++;
  }
  if(!n)return toast(`${c.pool.unit} is already trained at every tier above this one.`);
  bldTouched(); renderBuildingEditor();
  toast(`${c.pool.unit} added to ${n} higher tier(s).`);
}

/* =========================================================================
   The city half and the castle half, side by side

   A settlement building is written as TWO lines in the EDB with nothing tying
   them together — `barracks` and `castle_barracks` are as unrelated to the file
   as any two buildings in it — so over years of edits they drift. A unit gets
   added to the city chain and forgotten in the castle one, and the only way to
   find that was to open both lines and read them against each other by eye.

   This panel is that reading, done for you. Tier by tier, every unit either half
   trains, and what each half gives it. `⇄ Mirror` closes one gap; `⇄ Mirror all`
   closes every gap on the tier or in the whole line.

   Nothing here writes to disk. A unit copied INTO this line goes into its
   working copy exactly as one added by hand does; a unit copied into the twin is
   staged in `work.also` and appears in the editor's "Also changing" panel. Both
   are written by the same Save, with the same backup and the same Undo — the
   same road every other edit in this editor takes.
   ========================================================================= */
async function bldCompareVariants(){
  const b=state.bld; if(!b||!b.line)return;
  const modal=document.getElementById('modal');
  if(!b.stash){b.stashScroll=stashPlace(); b.stash=modal.innerHTML;}
  modal.innerHTML=`<h2>City and castle, side by side</h2>
    <div class="mbody"><div class="empty">Reading both halves of this building…</div></div>
    <div class="foot"><button onclick="bldPickCancel()">Back</button></div>`;
  let r;
  try{ r=await api.get(`/api/buildings/variants?mod=${enc(b.mod)}&line=${enc(b.line)}`
                       +`&culture=${enc(b.culture||'')}`); }
  catch(e){ r={error:''+e}; }
  if(!r||r.error){
    modal.querySelector('.mbody').innerHTML=`<div class="w-bad">${esc((r&&r.error)||'no answer')}</div>`;
    return;
  }
  activity('compared city/castle',`${b.line} against ${r.twin||'nothing'} in ${b.mod}`);
  b.vc={r,only:'gaps'};
  bldVarRender();
}
// Which rows the panel shows. Both halves of a real building agree about most of
// their roster, so "everything" is a thousand rows of nothing to do — the gaps
// are what the panel is opened for, and they lead.
function bldVarFilter(v){ if(state.bld.vc){state.bld.vc.only=v; bldVarRender();} }
function bldVarRows(lv){
  const only=(state.bld.vc||{}).only;
  if(only==='all')return lv.units;
  if(only==='numbers')return lv.units.filter(u=>u.where!=='both'||u.numbers_differ);
  return lv.units.filter(u=>u.where!=='both');
}
// Which side of the panel is which settlement type, in the reader's words.
const bldVarSide=(r,side)=>side==='a'
  ? (r.settlement||'this half') : (r.twin_settlement||'the other half');
function bldVarRender(){
  const b=state.bld,vc=b.vc; if(!vc)return;
  const r=vc.r;
  const modal=document.getElementById('modal');
  if(!r.twin){
    modal.innerHTML=`<h2>City and castle, side by side</h2>
      <div class="mbody"><div class="bnote">${esc(r.reason||'')}${docPoints('',[
        'A pair is matched by name: <code>barracks</code> against '
          +'<code>castle_barracks</code>, <code>stables</code> against <code>c_stables</code>.',
        'A line buildable in <b>both</b> settlement types has no second half to '
          +'compare, because it already is both.'])}</div></div>
      <div class="foot"><button onclick="bldPickCancel()">Back</button></div>`;
    return;
  }
  const gaps=r.only_a+r.only_b;
  const tab=(k,label,n)=>`<button class="${vc.only===k?'on':''}"
    onclick="bldVarFilter('${k}')">${label}${n==null?'':` <span class="badge">${n}</span>`}</button>`;
  modal.innerHTML=`<h2>${esc(r.line_label||r.line)}
      <span class="pill">city and castle, side by side</span></h2>
    <div class="mbody">
      <div class="vchead">
        <div class="vcside"><span class="badge">${esc(r.settlement)}</span>
          <b>${esc(r.line_label||r.line)}</b><code>${esc(r.line)}</code></div>
        <div class="vcvs">⇄</div>
        <div class="vcside"><span class="badge cls">${esc(r.twin_settlement)}</span>
          <b>${esc(r.twin_label||r.twin)}</b><code>${esc(r.twin)}</code></div>
      </div>
      <div class="count">${docPoints(gaps
        ? `<b class="w-warn">${gaps}</b> unit(s) are trained by one half and not the other.`
        : 'Both halves train the same units at every tier.',[
        r.differs?`<b>${r.differs}</b> unit(s) are trained by both, with different `
          +'numbers. That is often deliberate, so it is not counted as a gap.':'',
        'A <code>requires</code> clause that differs is not counted either: a city '
          +'clause names the city factions and a castle clause names the castle ones.',
        'Nothing is written until you Save the building, and a mirror into the '
          +'other half is listed under <b>Also changing</b> first.'])}</div>
      <div class="sndtabs" style="margin:8px 0">
        ${tab('gaps','Only on one side',gaps)}
        ${tab('numbers','Gaps and different numbers',gaps+r.differs)}
        ${tab('all','Every unit',r.levels.reduce((n,l)=>n+l.units.length,0))}
        ${gaps?`<button class="primary" style="margin-left:auto"
          onclick="bldVarMirrorAll()">⇄ Mirror every gap (${gaps})</button>`:''}
      </div>
      ${r.levels.map(bldVarLevelHtml).join('')}
    </div>
    <div class="foot">
      <span class="count">${bldAlsoCount()?`${bldAlsoCount()} row(s) staged for other lines`:''}</span>
      <button onclick="bldPickCancel()">Back to the building</button>
    </div>`;
}
function bldVarLevelHtml(lv,i){
  const r=state.bld.vc.r;
  const rows=bldVarRows(lv);
  const gaps=lv.only_a+lv.only_b;
  if(!lv.twin_level)
    return `<fieldset class="vclv"><legend>${esc(lv.level_label||lv.level)}</legend>
      <div class="bnote">This tier has no facing tier in <code>${esc(r.twin)}</code>,
        so there is nothing to compare it with.</div></fieldset>`;
  return `<fieldset class="vclv"><legend>${esc(lv.level_label||lv.level)}
      <span class="count">tier ${i+1}</span> ⇄ ${esc(lv.twin_level_label||lv.twin_level)}</legend>
    <div class="vcbar">
      <span class="count">${lv.units.length} unit(s) across both halves${
        gaps?` · <b class="w-warn">${gaps}</b> on one side only`:' · none missing'}${
        lv.differs?` · ${lv.differs} with different numbers`:''}</span>
      ${gaps?`<button style="margin-left:auto" onclick="bldVarMirrorLevel(${i})"
        title="Copy every unit this tier is missing into whichever half is missing it">
        ⇄ Mirror this tier (${gaps})</button>`:''}
    </div>
    ${rows.length?`<div class="vclist">
      <div class="vcrow vchd"><span class="vcu">Unit</span><span class="vcw">Trained by</span>
        <span class="vcn">${esc(r.settlement)}</span>
        <span class="vcn">${esc(r.twin_settlement)}</span>
        <span class="vca"></span></div>
      ${rows.map(u=>bldVarRowHtml(u,i)).join('')}</div>`
     :'<div class="bnote">Nothing to show here with the current filter.</div>'}
  </fieldset>`;
}
// The four numbers of one side, or a plain "not trained here".
function bldVarNums(p){
  if(!p)return '<span class="w-warn">not trained</span>';
  return `<span title="${esc(POOL_LABEL.initial)}">${esc(p.initial)}</span>
    <span title="${esc(POOL_LABEL.per_turn)}">${esc(p.per_turn)}</span>
    <span title="${esc(POOL_LABEL.maximum)}">${esc(p.maximum)}</span>
    <span title="${esc(POOL_SHORT.experience)}">${esc(p.experience)}</span>`;
}
function bldVarRowHtml(u,li){
  const r=state.bld.vc.r;
  const where=u.where==='both'
    ? `<span class="badge good" title="Both halves of this building train it at this tier.">both</span>`
    : u.where==='a'
      ? `<span class="badge" title="Only the ${esc(r.settlement)} half trains it here.">${esc(r.settlement)} only</span>`
      : `<span class="badge cls" title="Only the ${esc(r.twin_settlement)} half trains it here.">${esc(r.twin_settlement)} only</span>`;
  const act=u.where==='both'
    ? (u.numbers_differ
        ? `<span class="count" title="${esc(u.diff.join(', '))}">Different ${
             esc(u.diff.filter(f=>f!=='requires').join(', '))}</span>`
        : '<span class="count">In step</span>')
    : `<button onclick="bldVarMirrorOne(${li},'${q1(esc(u.unit))}')"
        title="Copy this unit into the half that is missing it. Nothing is written until you Save.">⇄ Mirror</button>`;
  return `<div class="vcrow ${u.where==='both'?'':'gap'}">
    <span class="vcu">
      <img loading="lazy" onerror="iconRetry(this)" src="${iconUrl(state.src,u.unit)}" alt="">
      <span class="vcnm"><span class="nm">${esc(u.name||u.unit)}</span>
        <span class="ty">${u.missing?'<span class="w-bad">Not in this mod’s EDU</span>'
                                     :esc(u.unit)}</span></span></span>
    <span class="vcw">${where}</span>
    <span class="vcn ${u.where==='b'?'off':''}">${bldVarNums(u.a)}</span>
    <span class="vcn ${u.where==='a'?'off':''}">${bldVarNums(u.b)}</span>
    <span class="vca">${act}</span></div>`;
}
/* Copy one unit into the half that does not train it.

   Into THIS line it is an ordinary added row in the working copy; into the twin
   it is an `also` row, staged against that line's own level. Both go through the
   calls the single-row ⇄ on a pool row already uses, so a mirror from here and a
   mirror from there stage identically. */
function bldVarMirrorApply(lv,u){
  const r=state.bld.vc.r;
  if(u.where==='a'){                          // this half has it, the twin does not
    return bldStagePool(r.twin,lv.twin_level,u.a,null);
  }
  if(bldHasUnit(lv.level_index,u.unit))return false;
  bldAddPoolRow(u.unit,lv.level_index,u.b,null);
  return true;
}
// The panel's own copy of the answer is what it draws from, so a mirrored row
// has to be marked there too or it would offer the same button again.
function bldVarTake(lv,u){
  if(u.where==='a'){u.b=Object.assign({},u.a);}
  else{u.a=Object.assign({},u.b);}
  u.where='both'; u.same=true; u.diff=[]; u.numbers_differ=false; u.staged=true;
  lv.only_a=lv.units.filter(x=>x.where==='a').length;
  lv.only_b=lv.units.filter(x=>x.where==='b').length;
  const r=state.bld.vc.r;
  r.only_a=r.levels.reduce((n,l)=>n+l.only_a,0);
  r.only_b=r.levels.reduce((n,l)=>n+l.only_b,0);
}
function bldVarMirrorOne(li,unit){
  const vc=state.bld.vc; if(!vc)return;
  const lv=vc.r.levels[li]; if(!lv)return;
  const u=lv.units.find(x=>x.unit===unit); if(!u||u.where==='both')return;
  const into=u.where==='a'?vc.r.twin_settlement:vc.r.settlement;
  if(!bldVarMirrorApply(lv,u))return toast(`${unit} is already staged there.`);
  bldVarTake(lv,u);
  bldTouched(); bldVarRender();
  toast(`${unit} staged into the ${into} half. Save the building to write it.`,4000);
}
function bldVarMirrorLevel(li){
  const vc=state.bld.vc; if(!vc)return;
  const lv=vc.r.levels[li]; if(!lv)return;
  let n=0;
  lv.units.filter(u=>u.where!=='both').forEach(u=>{
    if(bldVarMirrorApply(lv,u)){bldVarTake(lv,u); n++;}
  });
  if(!n)return toast('Nothing left to copy on this tier.');
  bldTouched(); bldVarRender();
  toast(`${n} unit(s) staged. Save the building to write them.`,4000);
}
function bldVarMirrorAll(){
  const vc=state.bld.vc; if(!vc)return;
  let n=0;
  vc.r.levels.forEach(lv=>{
    if(!lv.twin_level)return;
    lv.units.filter(u=>u.where!=='both').forEach(u=>{
      if(bldVarMirrorApply(lv,u)){bldVarTake(lv,u); n++;}
    });
  });
  if(!n)return toast('Nothing left to copy.');
  bldTouched(); bldVarRender();
  toast(`${n} unit(s) staged across every tier. Save the building to write them.`,5000);
}

/* ---- the same unit, everywhere it is recruited ----
   A unit is typically trained from four or five buildings whose numbers drifted
   apart over years of edits, and no view in the mod puts them side by side. This
   one does, and edits them in place: rows in the building on screen go into its
   working copy, rows in other lines are staged as `also` edits keyed by the EDB
   line they already occupy. */
async function bldShowUnit(unit){
  const b=state.bld;
  const modal=document.getElementById('modal');
  if(!b.stash){b.stashScroll=stashPlace();b.stash=modal.innerHTML;}
  modal.innerHTML=`<h2>${esc(unit)}: everywhere it is recruited</h2>
    <div class="mbody"><div class="empty">Reading every building line…</div></div>
    <div class="foot"><button onclick="bldPickCancel()">Back</button></div>`;
  let r;
  try{ r=await api.get(`/api/buildings/unit?mod=${enc(b.mod)}&type=${enc(unit)}`
                       +`&culture=${enc(b.culture||'')}`); }
  catch(e){ r={error:''+e}; }
  if(r.error){ modal.querySelector('.mbody').innerHTML=`<div class="w-bad">${esc(r.error)}</div>`; return; }
  b.cmp={unit,r,edits:{}};
  bldUnitRender();
}
function bldUnitRows(){
  const c=state.bld.cmp; return c?c.r.instances:[];
}
// One number, as the panel currently has it (edited value wins).
function bldUnitVal(row,key){
  const e=state.bld.cmp.edits[row.cap_line];
  return (e&&e[key]!==undefined)?e[key]:row[key];
}
function bldUnitSet(cap,key,val){
  const e=state.bld.cmp.edits, cur=e[cap]||(e[cap]={});
  cur[key]=val;
  bldUnitPaintDirty();
}
function bldUnitDirtyRows(){
  const c=state.bld.cmp;
  return bldUnitRows().filter(r=>{
    const e=c.edits[r.cap_line]; if(!e)return false;
    if(e.condEdited)return true;
    return ['initial','per_turn','maximum','experience']
      .some(k=>e[k]!==undefined&&String(e[k]).trim()!==String(r[k]).trim());
  });
}
/* ---- the unit view's own Code View ----
   Read-only, because this screen is the one shape in the toolkit that is not a
   record: its rows come from a dozen building blocks scattered through the EDB,
   so there is nothing for a serialiser to write back to. What it answers is the
   question the boxes cannot — what do these pools actually SAY in the file —
   and hovering a row lights its line. See codeview.pools_document. */
function bldUnitCvHost(){
  const c=state.bld.cmp;
  return {kind:'pools', mod:state.bld.mod, id:c.unit, readonly:true,
          where:'data/export_descr_buildings.txt',
          rerender:()=>bldUnitRender()};
}
async function bldUnitCvToggle(){
  const b=state.bld,c=b.cmp;
  if(c.cv){cvDrop(c.cv); c.cv=null; bldUnitRender(); return;}
  c.cv=cvCreate(bldUnitCvHost());
  bldUnitRender();                       // draw the empty pane, then fill it
  await cvLoad(c.cv);
  if(state.bld.cmp===c)bldUnitRender();
}
// The requires clause as this panel currently has it (an edit wins over the file).
function bldUnitReq(row){
  const e=state.bld.cmp.edits[row.cap_line];
  return (e&&e.condEdited)?(e.requires||''):(row.requires||'');
}
/* Editing a requires clause from the UNIT side.
   The same dialog the building editor uses, given a host of our own: these rows
   come from building lines that are mostly not loaded into `b.work`, so there
   is no capability object to hand it. The edit is kept in `cmp.edits` beside
   the numbers and staged by the same Apply, which is what makes a requirement
   edited here save exactly like one edited from the building view. */
function bldUnitEditReq(i){
  const b=state.bld,r=bldUnitRows()[i]; if(!r)return;
  const e=b.cmp.edits[r.cap_line]||(b.cmp.edits[r.cap_line]={});
  const conds=e.condEdited?e.conds:(r.conditions||[]);
  b.clause={host:e,kind:'unit',index:i,unit:b.cmp.unit,units:[b.cmp.unit],pick:null,
            conds:JSON.parse(JSON.stringify(conds||[])),
            was:JSON.parse(JSON.stringify(conds||[]))};
  bldClauseStash();
  renderClauseDialog();
  bldClauseOwnership();
}
function bldUnitPaintDirty(){
  const n=bldUnitDirtyRows().length;
  const el=document.getElementById('bcCount');
  if(el)el.textContent=n?`${n} row(s) changed`:'Nothing changed yet.';
  const btn=document.getElementById('bcApply');
  if(btn){btn.disabled=!n;btn.textContent=n?`Stage ${n} change(s)`:'Stage changes';}
}
function bldUnitRender(){
  const b=state.bld,c=b.cmp,rows=bldUnitRows();
  //: The EDU/EDB keyword on the left, what the column is CALLED on the right.
  //: "start / per turn / max" said what the numbers were shaped like and not
  //: what they do; these are the names the same three fields now carry
  //: everywhere the toolkit shows them.
  const KEYS=[['initial',POOL_LABEL.initial],['per_turn',POOL_LABEL.per_turn],
              ['maximum',POOL_LABEL.maximum],['experience',POOL_SHORT.experience]];
  // A value that is not the one most of the rows use is what you came here to
  // find, so it is marked rather than left to be spotted.
  const common=KEYS.map(([k])=>{
    const tally={};
    rows.forEach(r=>{const v=String(bldUnitVal(r,k)).trim();tally[v]=(tally[v]||0)+1;});
    return Object.entries(tally).sort((x,y)=>y[1]-x[1])[0]||['',0];
  });
  document.getElementById('modal').innerHTML=`<h2>${esc(c.r.info.name||c.unit)}
      <span class="pill">${esc(rows.length)} recruit pool(s)</span></h2>
    <div class="mbody">
      <div class="ehead">
        <img style="width:60px;height:48px" onerror="iconRetry(this)" src="${iconUrl(state.src,c.unit)}">
        <div><div class="nm">${esc(c.r.info.name||c.unit)}</div>
          <div class="count"><code>${esc(c.unit)}</code>${c.r.info.missing
            ?' · <span class="w-bad">not in this mod’s EDU</span>':''}</div>
          <div class="count">Every building line that trains it. Change a number here and it is
            staged like any other edit. Preview and Save write the lot in one pass.</div></div>
      </div>
      <div class="cvsplit${c.cv?'':' off'}">
        <div id="bcGui">${rows.length?`<div class="poollist" id="bcList">
          <div class="bcrow bchead"><span class="bcb">Building</span>
            <span class="count">Tier</span>
            <span class="bctw" title="Whether the city/castle counterpart trains this unit at the tier facing this one">Twin</span>
            ${KEYS.map(([k,l])=>`<span class="bcn" title="${esc(POOL_HELP[k]||'')}">${esc(l)}</span>`).join('')}
            <span class="bcreq">Requires</span></div>
          ${rows.map((r,i)=>bldUnitRow(r,i,KEYS,common)).join('')}
        </div>`:'<div class="bnote">No building line trains this unit.</div>'}</div>
        ${c.cv?`<div style="padding-top:4px">${cvHtml(c.cv)}</div>`:''}
      </div>
      <div class="bnote">A tier is shown as its position in its own line, so tier 2 of a
        three-level barracks and tier 2 of a five-level one are both “2”. The
        <b>odd</b> mark is a value that disagrees with what most of the other pools use.</div>
    </div>
    <div class="foot"><span class="count" id="bcCount"></span>
      <button class="${c.cv?'on':''}" title="Show the recruit_pool lines these rows come from, exactly as
export_descr_buildings.txt holds them. Read-only: they live in a dozen
building blocks, so there is no one record to write back."
        onclick="bldUnitCvToggle()">&lt;/&gt; Code view</button>
      <button onclick="bldPickCancel()">Back</button>
      <button class="primary" id="bcApply" onclick="bldUnitApply()">Stage changes</button></div>`;
  wireNumBoxes(document.getElementById('modal'));
  document.getElementById('modal').querySelectorAll('[data-bc]').forEach(inp=>{
    inp.addEventListener('input',()=>bldUnitSet(+inp.dataset.bcline,inp.dataset.bc,inp.value));
  });
  if(c.cv){cvWire(c.cv); cvBindHover(c.cv,document.getElementById('bcGui'));}
  bldUnitPaintDirty();
}
function bldUnitRow(r,i,KEYS,modal){
  const here=r.line===state.bld.line;
  const req=bldUnitReq(r), reqEdited=req!==(r.requires||'');
  return `<div class="bcrow ${here?'here':''}" data-label="pool:${r.cap_line}">
    <span class="bcb" title="${esc(r.line)}">${esc(r.line_label||r.line)}
      <span class="badge ${r.settlement==='castle'?'cls':''}">${esc(r.settlement||'both')}</span>
      ${here?`<span class="badge good" title="This is the building line you have open behind this panel. Editing this row edits the form you came from.">open</span>`:''}</span>
    <span class="count" title="${esc(r.level)}">${esc(r.level_label||r.level)}
      <span class="count">(${r.level_index+1}/${r.level_count})</span></span>
    ${bldUnitTwinCell(r)}
    ${KEYS.map(([k],j)=>{
      const v=bldUnitVal(r,k);
      const odd=String(v).trim()!==modal[j][0];
      return `<span class="bcn ${odd?'odd':''}" title="${odd?'differs from what most pools use ('+esc(modal[j][0])+')':''}">
        ${numBox(`data-bc="${k}" data-bcline="${r.cap_line}"`,v,k==='per_turn'?'turns':(k==='experience'?'1':'pool'))}</span>`;
    }).join('')}
    <span class="count bcreq ${reqEdited?'changed':''}" title="${esc(req||'no conditions')}"><span>${
      esc(req||'None')}</span>
      <button class="reqbtn" title="Edit who can recruit it from this building"
        onclick="bldUnitEditReq(${i})">✎</button></span></div>`;
}
/* Does the settlement's other half train this unit at the facing tier?
   A city/castle pair drifting apart is what this panel is opened to find, and
   the answer is per TIER: a twin that trains the unit five levels up is not the
   same building. `⇄ Mirror` puts the row into the twin, staged like every other
   edit — the same call the building editor's own mirror uses. */
function bldUnitTwinCell(r){
  if(!r.twin)
    return `<span class="count bctw" title="This building line has no city/castle counterpart.">None</span>`;
  if(!r.twin_level)
    return `<span class="count bctw" title="${esc(r.twin)} has no tier facing this one.">no tier</span>`;
  const where=`${r.twin} · ${r.twin_level_label||r.twin_level}`;
  if(r.twin_has)
    return `<span class="count bctw" title="${esc(where)} trains it too."><span class="badge good">✓</span></span>`;
  return `<span class="count bctw"><span class="w-warn" title="${esc(where)} does not train this unit.">✗</span>
    <button class="reqbtn" title="Copy this pool into ${esc(where)}, staged with the rest"
      onclick="bldUnitMirror(${r.level_index},'${q1(esc(r.line))}')">⇄</button></span>`;
}
// ⇄ from the unit view: stage this pool into the twin building's facing tier.
// It goes through bldStagePool like every other mirror, so it lands in the same
// `also` bucket, refuses a duplicate the same way, and rides the same Save.
function bldUnitMirror(levelIndex,line){
  const b=state.bld,c=b.cmp;
  const r=bldUnitRows().find(x=>x.line===line&&x.level_index===levelIndex);
  if(!r||!r.twin_level)return;
  const pool={unit:c.unit,
    initial:bldUnitVal(r,'initial'),per_turn:bldUnitVal(r,'per_turn'),
    maximum:bldUnitVal(r,'maximum'),experience:bldUnitVal(r,'experience')};
  if(!bldStagePool(r.twin,r.twin_level,pool,null))
    return toast(`${c.unit} is already in ${r.twin} · ${r.twin_level_label||r.twin_level}.`);
  r.twin_has=true;                    // the panel is looking at staged state now
  bldTouched(); bldUnitRender();
  toast(`${c.unit} staged into ${r.twin} · ${r.twin_level_label||r.twin_level}. Saved with the rest.`,4200);
}
function bldUnitApply(){
  const b=state.bld,c=b.cmp;
  const dirty=bldUnitDirtyRows();
  if(!dirty.length)return;
  let here=0,elsewhere=0;
  for(const r of dirty){
    const e=c.edits[r.cap_line];
    const pool={unit:r.unit||c.unit,
      initial:e.initial!==undefined?e.initial:r.initial,
      per_turn:e.per_turn!==undefined?e.per_turn:r.per_turn,
      maximum:e.maximum!==undefined?e.maximum:r.maximum,
      experience:e.experience!==undefined?e.experience:r.experience};
    if(r.line===b.line){
      // the building on screen already has this row in its working copy, found
      // by the EDB line it came from — edit it there so the form stays truthful
      const row=[...b.work.levels[r.level_index].caps,...b.work.levels[r.level_index].fcaps]
        .find(x=>x.line===r.cap_line);
      if(row&&row.pool){
        Object.assign(row.pool,pool);
        if(e.condEdited){row.conds=e.conds;row.condEdited=true;row.requires=e.requires;}
        here++; continue;
      }
    }
    // a row in another line: staged by the EDB line index it already occupies,
    // which is what the server's capability planner keys an in-place rewrite on
    const rows=bldAlso(r.line,r.level);
    const prev=rows.find(x=>x.line===r.cap_line);
    if(prev){
      Object.assign(prev.pool,pool);
      if(e.condEdited){prev.conds=e.conds;prev.condEdited=true;prev.requires=e.requires;}
    }
    else rows.push({line:r.cap_line,keyword:'recruit_pool',args:'',
      requires:e.condEdited?e.requires:(r.requires||''),
      conds:e.condEdited?e.conds:[],condEdited:!!e.condEdited,bonus:false,value:'',
      pool:Object.assign({},pool),comment:'',faction:!!r.faction,del:false});
    elsewhere++;
  }
  c.edits={};
  bldPickCancel();                   // back to the building editor
  bldTouched(); renderBuildingEditor();
  toast(`${here+elsewhere} pool(s) staged${elsewhere?`, ${elsewhere} of them in other building line(s)`:''}.`,4200);
}

/* ---- hop to the Unit Editor and back ----
   The building editor's whole state (which line, which level, every unsaved
   edit) lives in state.bld, which nothing here clears — so coming back is just
   re-rendering it. bldReturn only records what the Back button should say and
   which level to land on. */
function openUnitFromBuilding(type){
  const b=state.bld;
  if(bldDirty()&&!confirm(
      'You have unsaved building changes. They are kept while you edit the unit, and '
      +'switch to the Unit Editor now?'))return;
  state.bldReturn={line:b.line,lvl:b.lvl,label:b.d.label};
  closeModal();
  state.mode='edit';
  applyMode(true);
  openEditor(type);
}
async function backToBuilding(){
  const r=state.bldReturn,b=state.bld; if(!r||!b)return;
  if(state.ed&&(edDirty()||edCmpDirty())
     &&!confirm('Discard the unsaved unit changes and go back to the building?'))return;
  state.ed=null; closeModal();
  state.bldReturn=null;
  state.mode='buildings';
  applyMode(true);
  // The working copy is NOT rebuilt: everything typed into the building before
  // the hop is still in b.work, and throwing it away is exactly what makes
  // switching back and forth useless. Only the read-only half is re-read, so a
  // unit renamed or deleted in the meantime shows up as such in the pool rows.
  // Capability line numbers index the EDB, which a unit edit never touches, so
  // the working copy stays valid against it.
  if(b.work&&b.line===r.line){
    b.lvl=r.lvl;
    try{
      const fresh=await api.get(`/api/building?mod=${enc(b.mod)}&line=${enc(r.line)}`);
      if(fresh.levels.length===b.work.levels.length)b.d=fresh;
    }catch(e){}
    b.planStale=!!b.plan;
    document.getElementById('modal').className='modal wide';
    overlay.classList.add('open');
    renderBuildingEditor();
    return;
  }
  b.lvl=r.lvl;
  await openBuilding(r.line,true);
}

/* ---- preview / save ---- */
function bldPayload(){
  const b=state.bld;
  const origLevels=JSON.parse(b.orig).levels;
  return {mod:b.mod,line:b.line,fix_ownership:b.fixOwnership!==false,
    // A line hand-edited as text replaces its whole block, and the boxes then
    // apply on top of it. Sent from the first hand edit onwards even if the text
    // has since been typed back to what the file says: the capability rows now
    // count lines from the pane's text, and only the raw path plans against it.
    raw_block:bldCvOwns()?b.cv.base:'',
    levels:b.work.levels.map((lv,i)=>{
    const o=origLevels[i],out={name:lv.name,settlement:lv.settlement,requires:lv.requires,
      scalars:lv.scalars,upgrades:lv.upgrades,
      capabilities:[...lv.caps].map(bldCapOp),
      faction_capabilities:[...lv.fcaps].map(bldCapOp)};
    if(lv.condEdited)out.conditions=lv.conds;
    // Only send the localisation records whose text actually changed: their
    // presence is what makes the server rewrite text/export_buildings.txt at
    // all. `loc` is the shared key, `loc_cultures` the per-culture ones.
    const was=o.locAll||{},cultures={};
    for(const c of Object.keys(lv.locAll||{})){
      const rec=lv.locAll[c],old=was[c]||{};
      if(rec.name===(old.name||'')&&rec.descr===(old.descr||'')
         &&rec.descr_short===(old.descr_short||''))continue;
      const send={name:rec.name||'',descr:rec.descr||'',descr_short:rec.descr_short||''};
      if(c)cultures[c]=send; else out.loc=send;
    }
    if(Object.keys(cultures).length)out.loc_cultures=cultures;
    return out;}),
    // Rows staged against other building lines — the castle twin, or every tree
    // that trains one unit. Planned against the same parse and spliced in the
    // same pass, so this stays one edit and one undo step.
    also:Object.entries((b.work.also)||{}).map(([line,byLevel])=>({
      line,
      levels:Object.entries(byLevel).filter(([,rows])=>rows.length)
        .map(([name,rows])=>({name,capabilities:rows.map(bldCapOp)}))
    })).filter(x=>x.levels.length)};
}
function bldCapOp(c){
  const args=c.pool
    ? `"${c.pool.unit}"  ${c.pool.initial}  ${c.pool.per_turn}  ${c.pool.maximum}  ${c.pool.experience}`
    : ((c.bonus?'bonus ':'')+(c.value||'')).trim();
  const op={line:c.line,keyword:c.keyword,args,requires:c.requires,delete:!!c.del};
  // Structure only where the clause was actually built here. A row copied from
  // somewhere else is new but its clause is not: it carries the original text,
  // and re-emitting that from structure would quietly re-tidy — or, for a row
  // with no parsed conditions, silently drop — a clause nobody edited.
  if(c.condEdited)op.conditions=c.conds||[];
  return op;
}
async function bldPreview(){
  const b=state.bld;
  const box=document.getElementById('bldPlan');
  await cvSettle(b.cv);                 // read the last keystroke before planning
  const blocked=bldCvBlocked();
  if(blocked){box.innerHTML=`<div class="mbody w-bad">${esc(blocked)}</div>`; return;}
  box.innerHTML='<div class="count" style="padding:8px">Working out what would change…</div>';
  try{
    b.plan=await api.post('/api/buildings/plan',bldPayload());
    b.planStale=false;
    box.innerHTML=bldPlanHtml(b.plan,false);
  }catch(e){ box.innerHTML=`<div class="mbody w-bad">${esc(''+e)}</div>`; }
}
function bldPlanHtml(p,stale){
  if(p.error)return `<div class="sum"><div class="srow bad"><span class="sicon">✕</span>
    <span class="stext">${esc(p.error)}</span></div></div>`;
  const rows=[];
  (p.changes||[]).forEach(c=>rows.push(`<div class="srow"><span class="sicon">•</span>
    <span class="stext">${esc(c)}</span></div>`));
  (p.warnings||[]).forEach(c=>rows.push(`<div class="srow warn"><span class="sicon">!</span>
    <span class="stext">${esc(c)}</span></div>`));
  (p.errors||[]).forEach(c=>rows.push(`<div class="srow bad"><span class="sicon">✕</span>
    <span class="stext">${esc(c)}</span></div>`));
  if(!rows.length)rows.push(`<div class="srow"><span class="sicon">·</span>
    <span class="stext">Nothing would change.</span></div>`);
  const files=[p.edb_rewritten?'export_descr_buildings.txt':'',
               p.loc_rewritten?'text/export_buildings.txt':'',
               p.edu_rewritten?'export_descr_unit.txt':'',
               p.modeldb_rewritten?'unit_models/battle_models.modeldb':''].filter(Boolean);
  return `<div class="bsec" style="margin-top:14px"><h4>Preview${
      stale?' <span class="w-warn">(out of date: edited since)</span>':''}</h4>
    <div class="sum">${rows.join('')}
      ${files.length?`<div class="srow shead" style="margin-top:6px"><span class="sicon">→</span>
        <span class="stext">writes ${files.map(f=>`<code>${esc(f)}</code>`)
          .join(files.length>2?', ':' and ')}</span></div>`:''}
    </div></div>`;
}
async function bldSave(){
  const b=state.bld;
  await cvSettle(b.cv);                 // the last keystroke counts
  const blocked=bldCvBlocked();
  if(blocked){toast(blocked,6000); return;}
  if(!bldDirty()){toast('Nothing to save.');return;}
  const btn=event&&event.target; if(btn)btn.disabled=true;
  try{
    const res=await api.post('/api/buildings/apply',
      Object.assign(bldPayload(),{clear_strings_bin:clearBinOn()}));
    if(res.error){ toast(res.error,5000);
      document.getElementById('bldPlan').innerHTML=bldPlanHtml(res.plan||{error:res.error},false);
      return; }
    toast(`Saved. ${(res.plan.changes||[]).length} change(s) written to ${b.mod}.`);
    state.bld.ov=await api.get('/api/buildings?mod='+enc(state.src));
    _bldFiltersFor='';
    await openBuilding(b.line,true);           // re-read from disk, keep the level
    render();
  }catch(e){ toast('Save failed: '+e,5000); }
  finally{ if(btn)btn.disabled=false; }
}

/* ========================= a new building tree =========================
   The one thing the Buildings screen could not do: every other operation here
   edits a line that is already in the file. A tree is three things at once —
   the EDB block, three text keys per level, and the per-culture cards — and the
   first two have to land together, because a level with no `{name}` key crashes
   the game at the construction panel (all 1099 levels in the three installed
   mods have all three of theirs). The cards are art and stay yours to draw; the
   dialog lists the paths and calls a blank one a blank, not a fault.

   Same plan → preview → apply road as every other save here, through the same
   two endpoints: the server owns the block's text, so what the preview counts
   and what Create writes cannot be two different things.

   THE LEVELS CHAIN FORWARD. Each one's `upgrades` block names the next and never
   the other way about — all 771 upgrade entries measured across the three mods
   point at a level listed later on the `levels` line, which is what TWCenter's
   hardcoded-limits note says the engine requires. */

const NT_MAX_ROWS=20;
const bldNt=()=>state.bld&&state.bld.nt;
const bldNtName=()=>{const n=bldNt(); return (n.prefix||'')+(n.stem||'').trim();};
const bldNtDefaultLabel=name=>(name||'').replace(/_/g,' ')
  .replace(/\b\w/g,c=>c.toUpperCase());

function bldNewTree(){
  const b=state.bld;
  b.nt={prefix:'',stem:'',label:'',settlement:'city',religion:'',convert_to:'',
        levels:[{name:'',label:'',auto:true},{name:'',label:'',auto:true},
                {name:'',label:'',auto:true}],
        plan:null,busy:false};
  bldNtRenumber();
  overlay.classList.add('open');
  document.getElementById('modal').className='modal wide';
  bldNtPaint();
}
/* A level whose name you have not touched follows the line's — type `forge` and
   the three rows become forge_1, forge_2, forge_3. Touch one and it stops
   following, because renaming it back under you is the worse failure. */
function bldNtRenumber(){
  const n=bldNt(),base=bldNtName();
  n.levels.forEach((lv,i)=>{ if(lv.auto)lv.name=base?base+'_'+(i+1):''; });
}
function bldNtSet(key,value){
  const n=bldNt();
  bldNtRead();
  n[key]=value;
  if(key==='prefix'||key==='stem')bldNtRenumber();
  n.plan=null;
  bldNtPaint();
}
// A keystroke drops the stale preview but does NOT repaint: rebuilding the form
// under the caret would lose the cursor position on every character typed.
function bldNtTouch(i,key,value){
  const n=bldNt();
  if(i>=0){
    const lv=n.levels[i]; if(!lv)return;
    lv[key]=value;
    if(key==='name')lv.auto=false;
  }else{
    n[key]=value;
    if(key==='stem'){
      bldNtRenumber();
      n.levels.forEach((lv,j)=>{
        if(!lv.auto)return;
        const box=document.getElementById('ntN'+j); if(box)box.value=lv.name;
        const lab=document.getElementById('ntL'+j);
        if(lab)lab.placeholder=bldNtDefaultLabel(lv.name);
      });
    }
  }
  n.plan=null;
  document.getElementById('ntPlan').innerHTML=bldNtHint();
}
function bldNtAddLevel(){
  const n=bldNt();
  if(n.levels.length>=NT_MAX_ROWS)return;
  bldNtRead();
  n.levels.push({name:'',label:'',auto:true});
  bldNtRenumber(); n.plan=null; bldNtPaint();
}
function bldNtDropLevel(i){
  const n=bldNt();
  if(n.levels.length<=1)return;
  bldNtRead();
  n.levels.splice(i,1);
  bldNtRenumber(); n.plan=null; bldNtPaint();
}
// Pull every box back into the form state before a repaint or a request.
function bldNtRead(){
  const n=bldNt(); if(!n)return;
  const get=id=>{const el=document.getElementById(id); return el?el.value:undefined;};
  const stem=get('ntStem'); if(stem!==undefined)n.stem=stem;
  const label=get('ntLabel'); if(label!==undefined)n.label=label;
  n.levels.forEach((lv,i)=>{
    const nm=get('ntN'+i); if(nm!==undefined&&nm!==lv.name){lv.name=nm; lv.auto=false;}
    const lb=get('ntL'+i); if(lb!==undefined)lv.label=lb;
  });
}
function bldNtSpec(){
  const n=bldNt();
  return {name:bldNtName(),label:(n.label||'').trim(),
          settlement:n.settlement,religion:n.religion,convert_to:n.convert_to,
          levels:n.levels.map(lv=>({name:(lv.name||'').trim(),
                                    label:(lv.label||'').trim()}))};
}
function bldNtHint(){
  const n=bldNt(),name=bldNtName();
  if(!name)return '<div class="bnote">Give the line a name to see what would be written.</div>';
  const kept=n.levels.map(x=>(x.name||'').trim()).filter(Boolean);
  return `<div class="bnote">${docPoints('What Create would write:',[
    `<code>building ${esc(name)}</code> with ${kept.length} level${kept.length===1?'':'s'} at the
     end of the EDB.`,
    `${kept.length*3} text key${kept.length*3===1?'':'s'} in <code>text/export_buildings.txt</code>.`,
    'Preview first: nothing is written until you press Create.'])}</div>`;
}
function bldNtPaint(){
  const b=state.bld,ov=b.ov,n=b.nt;
  const prefixes=ov.prefixes||[{prefix:'',label:'(no prefix)',hint:''}];
  const chosen=prefixes.find(p=>p.prefix===n.prefix)||prefixes[0];
  document.getElementById('modal').innerHTML=`<h2>New building tree in ${esc(b.mod)}</h2>
    <div class="mbody">
      <div class="brow">
        <label style="flex:0 0 180px">Prefix
          <select onchange="bldNtSet('prefix',this.value)">
            ${prefixes.map(p=>`<option value="${esc(p.prefix)}" ${
              p.prefix===n.prefix?'selected':''}>${esc(p.label)}</option>`).join('')}
          </select></label>
        <label style="flex:1 1 200px">Line name (the code name)
          <input id="ntStem" value="${esc(n.stem)}" placeholder="forge"
            oninput="bldNtTouch(-1,'stem',this.value)"></label>
        <label style="flex:1 1 200px">Shown as
          <input id="ntLabel" value="${esc(n.label)}" placeholder="Forge"
            oninput="bldNtTouch(-1,'label',this.value)"></label>
      </div>
      ${chosen&&chosen.hint?`<div class="bnote">${esc(chosen.hint)}</div>`:''}
      <div class="brow">
        <label style="flex:0 0 180px">Settlement
          <select onchange="bldNtSet('settlement',this.value)">
            <option value="city" ${n.settlement==='city'?'selected':''}>City</option>
            <option value="castle" ${n.settlement==='castle'?'selected':''}>Castle</option>
            <option value="" ${n.settlement===''?'selected':''}>Both (no word on the line)</option>
          </select></label>
        <label style="flex:0 0 180px">Religion
          <select onchange="bldNtSet('religion',this.value)">
            <option value="">(none)</option>
            ${(ov.religions||[]).map(r=>`<option value="${esc(r)}" ${
              r===n.religion?'selected':''}>${esc(r)}</option>`).join('')}
          </select></label>
        <label style="flex:1 1 220px">Converts to (the twin line)
          <select onchange="bldNtSet('convert_to',this.value)">
            <option value="">(none)</option>
            ${(ov.lines||[]).map(l=>`<option value="${esc(l.name)}" ${
              l.name===n.convert_to?'selected':''}>${esc(l.name)}</option>`).join('')}
          </select></label>
      </div>

      <div class="bsec"><h4>Levels <span class="n">${n.levels.length}</span>
          <span class="count">Each one upgrades into the next</span>
          <button style="margin-left:auto" onclick="bldNtAddLevel()"
            ${n.levels.length>=NT_MAX_ROWS?'disabled':''}>＋ Add level</button></h4>
        <div class="ntlv"><span class="i"></span><span class="count">Code name</span>
          <span class="count">Shown as</span><span></span></div>
        ${n.levels.map((lv,i)=>`<div class="ntlv">
          <span class="i">${i+1}</span>
          <input id="ntN${i}" value="${esc(lv.name)}" placeholder="code name"
            oninput="bldNtTouch(${i},'name',this.value)">
          <input id="ntL${i}" value="${esc(lv.label)}"
            placeholder="${esc(bldNtDefaultLabel(lv.name))}"
            oninput="bldNtTouch(${i},'label',this.value)">
          <button class="x danger" title="Remove this level"
            ${n.levels.length<=1?'disabled':''} onclick="bldNtDropLevel(${i})">🗑</button>
        </div>`).join('')}
        <div class="bnote">${docPoints('Every level starts from the same defaults.',[
          'An empty <code>capability</code> block and <code>material wooden</code>.',
          'A build time and a cost that climb with the tier.',
          'A <code>requires factions { … }</code> naming every culture a faction in this mod '
            +'belongs to, so the line starts buildable by everyone and you narrow it in the editor.',
          'Units come after: open the line and use ＋ Add unit.'])}</div>
      </div>

      <div id="ntPlan">${bldNtHint()}</div>
    </div>
    <div class="foot">
      <button onclick="bldNtCancel()">Cancel</button>
      <button onclick="bldNtPreview()">Preview</button>
      <button class="primary" onclick="bldNtCreate()">Create</button>
    </div>`;
  if(n.plan)document.getElementById('ntPlan').innerHTML=bldNtPlanHtml(n.plan);
}
function bldNtCancel(){ state.bld.nt=null; closeModal(); }

function bldNtPlanHtml(p){
  const slots=(p.slots||[]).filter(s=>!s.found);
  if(!slots.length)return bldPlanHtml(p,false);
  return bldPlanHtml(p,false)+`<div class="bsec"><h4>Building cards to draw
      <span class="n">${slots.length}</span></h4>
    <div class="ntslots">${slots.map(s=>`<div><code>${esc(s.small)}</code>${
      s.large_found?'':` · <code>${esc(s.large)}</code>`}</div>`).join('')}</div>
    <div class="bnote">${docPoints('A list to draw against, not a list of faults.',[
      '78×62 TGA for the button, 300×245 TGA for the constructed picture.',
      'A level with no card is not a crash; it shows a blank one.'])}</div></div>`;
}
async function bldNtPreview(){
  const n=bldNt(); if(!n)return;
  bldNtRead();
  const box=document.getElementById('ntPlan');
  box.innerHTML='<div class="count" style="padding:8px">Working out what would be written…</div>';
  try{
    n.plan=await api.post('/api/buildings/plan',{mod:state.src,create:bldNtSpec()});
    box.innerHTML=bldNtPlanHtml(n.plan);
  }catch(e){ box.innerHTML=`<div class="mbody w-bad">${esc(''+e)}</div>`; }
}
async function bldNtCreate(){
  const n=bldNt(); if(!n||n.busy)return;
  bldNtRead();
  const name=bldNtName();
  const btn=event&&event.target; if(btn)btn.disabled=true;
  n.busy=true;
  try{
    const res=await api.post('/api/buildings/apply',
      {mod:state.src,create:bldNtSpec(),clear_strings_bin:clearBinOn()});
    if(res.error){
      n.plan=res.plan||{error:res.error};
      document.getElementById('ntPlan').innerHTML=bldNtPlanHtml(n.plan);
      toast(res.error,6000);
      return;
    }
    toast(`Created ${name}. ${(res.plan.changes||[]).length} change(s) written to ${state.src}.`);
    state.bld.nt=null;
    // the EDB is a different file now, so the overview is re-read rather than patched
    await loadBuildings(true);
    bldOpenTrees().add(name);
    _bldFiltersFor='';
    render();                       // the list behind the dialog gained a row
    await openBuilding(name);       // …and the new line opens on top of it
  }catch(e){ toast('Create failed: '+e,6000); }
  finally{ if(btn)btn.disabled=false; if(bldNt())bldNt().busy=false; }
}
