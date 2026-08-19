/* undo.js — Ctrl+Z/Ctrl+Y across every editor, the "unsaved changes" guard,
   and the scroll/focus restoration that makes a redraw invisible

   Part of the Medieval 2 GUI Toolkit UI. These files are plain
   <script> tags sharing ONE global scope, loaded in the order set in
   index.html — there is no build step and no module system. Two rules
   follow from that: a top-level name must be unique across all of
   them, and a file's top-level side effects may not depend on a file
   loaded after it. */
/* =========================================================================
   Undo / redo — Ctrl+Z, Ctrl+Y (and Ctrl+Shift+Z)

   Every editor on this page keeps its pending changes in one plain-object
   working model and re-draws from it, so undo is a stack of SNAPSHOTS of that
   model rather than a log of commands: after any interaction the model is
   stringified and, if it differs from the top of the stack, pushed. Ctrl+Z
   restores the snapshot below and re-draws — which is why it takes back one
   value instead of closing the dialog and losing everything.

   Consecutive keystrokes in the same box collapse into one step (the box's
   identity is the coalesce key), so undo walks back value by value rather than
   letter by letter. Nothing is written to disk either way: this is the
   in-page working copy, and 🕑 Log → Undo is still what reverses a save.

   To make a new editor undoable: add a scope below. `id()` returns '' when the
   editor is not on screen and a stable string when it is (a change of string
   means "a different thing is being edited", and clears the stack); `get`/`set`
   move its working model in and out of a JSON-safe snapshot; `draw` re-renders.
   ========================================================================= */
const UNDO_SCOPES=[
  // the building editor: one working copy of every level in the line
  {id:()=>(modalOpen()&&state.bld&&state.bld.work)?'bld:'+state.bld.mod+':'+state.bld.line:'',
   get:()=>state.bld.work, set:v=>{state.bld.work=v;}, draw:()=>renderBuildingEditor()},
  // the unit editor and the bmdb editor share state.ed
  {id:()=>(modalOpen()&&state.ed)
      ?(state.ed.bmdb?'bmdb:':'ed:')+state.ed.mod+':'+(state.ed.unit||edBmdbName()):'',
   get:edSnap, set:edRestore,
   draw:()=>state.ed.bmdb?renderBmdbEditor():renderEditor()},
  // the transfer composer: one config per unit being sent across
  {id:()=>(modalOpen()&&!state.ed&&!(state.bld&&state.bld.work)&&state.editing&&composerList.length)
      ?'cfg:'+state.src+'>'+state.dst:'',
   get:cfgSnap, set:cfgRestore, draw:()=>renderComposer()},
  // sounds mode stages its changes on the page itself, with no dialog
  {id:()=>(!modalOpen()&&state.mode==='sounds'&&state.snd)?'snd:'+state.src:'',
   get:()=>state.snd.ops, set:v=>{state.snd.ops=v;}, draw:()=>renderSounds()},

  /* The editors built after this file. Every one of them was undoable in
     principle — they all keep a deep-cloned working copy at `state.<x>.d.w` and
     repaint their form from it, which is exactly the shape the snapshot stack
     wants — and none of them had a scope, so Ctrl+Z did nothing in any of them.
     That is the whole of the "Ctrl+Z is broken everywhere" report: it was never
     wired for Traits, Ancillaries, Factions, the five Minor Files tabs or
     Strings. They are all page editors rather than dialogs, hence `!modalOpen()`
     — a dialog on top of one owns the keystroke while it is open.

     A scope's `id` includes which record is open, so moving to another trait
     clears the stack instead of letting Ctrl+Z pour one record's values into
     another. */
  {id:()=>(!modalOpen()&&state.mode==='traits'&&state.tr&&state.tr.d&&state.tr.d.w)
      ?'tr:'+state.src+':'+(state.tr.sel||'(new)'):'',
   get:()=>state.tr.d.w, set:v=>{state.tr.d.w=v;}, draw:()=>trPaint()},
  {id:()=>(!modalOpen()&&state.mode==='ancillaries'&&state.an&&state.an.d&&state.an.d.w)
      ?'an:'+state.src+':'+(state.an.sel||'(new)'):'',
   get:()=>state.an.d.w, set:v=>{state.an.d.w=v;}, draw:()=>anPaint()},
  {id:()=>(!modalOpen()&&state.mode==='factions'&&state.fac&&state.fac.d&&state.fac.d.w)
      ?'fac:'+state.src+':'+(state.fac.sel||''):'',
   get:()=>state.fac.d.w, set:v=>{state.fac.d.w=v;}, draw:()=>facPaint()},
  {id:()=>(!modalOpen()&&state.mode==='minor'&&state.mf&&state.mf.d&&state.mf.d.w)
      ?'mf:'+state.src+':'+(state.mf.tab||'')+':'+(state.mf.sel||'(new)'):'',
   get:()=>state.mf.d.w, set:v=>{state.mf.d.w=v;}, draw:()=>mfPaint()},
  // Strings is the odd one out: its working copy is the map of pending edits,
  // keyed by row id, not a cloned record.
  {id:()=>(!modalOpen()&&state.mode==='strings'&&state.str&&state.str.rows)
      ?'str:'+state.src+':'+(state.str.file||''):'',
   get:()=>state.str.edits, set:v=>{state.str.edits=v;},
   draw:()=>{const el=document.getElementById('strMain');
     if(el)el.innerHTML=strRowsHtml(); strPaintBar();}},
];
const modalOpen=()=>document.getElementById('overlay').classList.contains('open');
const edBmdbName=()=>((state.ed.d.models[0]||{}).name||'');
// state.ed carries the read-only unit alongside the edits; only the edits go in
// a snapshot, and the two Sets have to survive the JSON round trip as arrays.
function edSnap(){
  const e=state.ed,c=e.cmp;
  // Only the compared unit's EDITS go in — not which unit it is, and not the
  // server payload it was loaded from. Undo takes back a typed number, and
  // "un-picking" a comparison would mean re-fetching a unit to put it back.
  return {ov:e.ov,rm:[...e.rm],added:[...(e.added||[])],loc:e.loc,newType:e.newType,
          newDict:e.newDict,mEdits:e.mEdits,newModels:e.newModels,
          cardSrc:e.cardSrc||'',infoSrc:e.infoSrc||'',removeOldIcons:!!e.removeOldIcons,
          cmpOv:c?c.ov:{},cmpRm:c?[...c.rm]:[],cmpAdded:c?[...c.added]:[]};
}
function edRestore(v){
  const e=state.ed;
  e.ov=v.ov; e.rm=new Set(v.rm); e.added=new Set(v.added); e.loc=v.loc;
  e.newType=v.newType; e.newDict=v.newDict; e.mEdits=v.mEdits; e.newModels=v.newModels;
  e.cardSrc=v.cardSrc; e.infoSrc=v.infoSrc; e.removeOldIcons=v.removeOldIcons;
  if(e.cmp){ e.cmp.ov=v.cmpOv||{}; e.cmp.rm=new Set(v.cmpRm||[]);
             e.cmp.added=new Set(v.cmpAdded||[]); }
}
// The underscore keys of a per-unit config are server answers cached on it
// (the field list, the conflict report) — big, and not something to undo.
function cfgSnap(){
  const out={};
  for(const t of Object.keys(state.cfg)){
    const c=state.cfg[t],o={};
    for(const k of Object.keys(c)) if(k[0]!=='_')o[k]=c[k];
    out[t]=o;
  }
  return out;
}
function cfgRestore(v){ for(const t of Object.keys(v)) Object.assign(cfgFor(t),v[t]); }

/* ---- "⚠ unsaved changes" ----
   Amber and badged, because it is a state you have to act on before closing the
   dialog — not another line of grey chrome to read past. One painter for every
   editor, driven off the same interactions the undo stack watches, so it can
   never fall out of step with what is actually pending. */
const dirtyChip=on=>on?'<span class="dirtychip">⚠ unsaved changes</span>':'';
function paintDirty(){
  const bld=document.getElementById('bldDirtyNote');
  if(bld)bld.innerHTML=dirtyChip(!!(state.bld&&state.bld.work&&bldDirty()));
  const ed=document.getElementById('edDirtyNote');
  if(ed)ed.innerHTML=dirtyChip(!!(state.ed&&(edDirty()||edCmpDirty())));
}

const undo={key:'',cur:null,ck:null,past:[],future:[]};
const UNDO_LIMIT=150;
function undoScope(){
  for(const s of UNDO_SCOPES){ const id=s.id(); if(id)return Object.assign({key:id},s); }
  return null;
}
// Called when an editor opens, so its first edit has a baseline to go back to.
function undoReset(){
  const s=undoScope();
  undo.key=s?s.key:''; undo.cur=s?JSON.stringify(s.get()):null;
  undo.ck=null; undo.past.length=0; undo.future.length=0;
}
// Take a baseline for what is open now, but only if the stack does not already
// belong to it. For a view that reloads without changing what is being edited —
// Strings paging through the same file, say — a full reset would throw away undo
// history for edits that are still pending.
function undoBaseline(){
  const s=undoScope();
  if(s&&s.key===undo.key)return;
  undoReset();
}
function undoCapture(ck){
  const s=undoScope(); if(!s)return;
  if(s.key!==undo.key){ undoReset(); return; }
  const snap=JSON.stringify(s.get());
  if(snap===undo.cur)return;
  // still typing into the same box: the step already on the stack covers it
  if(!(ck&&ck===undo.ck&&undo.past.length)){
    undo.past.push(undo.cur);
    if(undo.past.length>UNDO_LIMIT)undo.past.shift();
  }
  undo.cur=snap; undo.ck=ck||null; undo.future.length=0;
}
// Snapshots are taken one tick AFTER the event, because the page's own handler
// is what puts the typed value into the model.
let _undoPend=null;
function undoTick(ck){
  clearTimeout(_undoPend);
  _undoPend=setTimeout(()=>{undoCapture(ck);paintDirty();},0);
}
// Text boxes coalesce per element; a fresh element (after a re-draw) starts a
// new step. Tick boxes, dropdowns and buttons are each one step of their own.
let _undoSeq=0;
function undoKeyOf(el){
  if(!el||!el.tagName)return '';
  if(el.tagName!=='INPUT'&&el.tagName!=='TEXTAREA')return '';
  if(el.type==='checkbox'||el.type==='radio')return '';
  if(!el._ukey)el._ukey='k'+(++_undoSeq);
  return el._ukey;
}
// Where the caret was, so undo does not throw you out of the box you are in.
// A selector wins where the element carries an id or data-* of its own; failing
// that we fall back to where it sat in the tree, because a re-draw of the same
// view rebuilds the same structure and most boxes carry no identity at all.
function undoFocus(){
  const el=document.activeElement;
  if(!el||!/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName||''))return null;
  const sel=(()=>{
    if(el.id)return '[id="'+cssq(el.id)+'"]';
    const own=[...el.attributes].filter(a=>a.name.indexOf('data-')===0)
      .map(a=>`[${a.name}="${cssq(a.value)}"]`).join('');
    if(!own)return '';
    const row=el.closest('[data-cap]');
    return (row?`[data-cap="${cssq(row.dataset.cap)}"] `:'')+el.tagName.toLowerCase()+own;
  })();
  const path=[];
  for(let n=el;n&&n!==document.body;n=n.parentElement)
    path.unshift([...n.parentElement.children].indexOf(n));
  let caret=null;
  try{ caret=[el.selectionStart,el.selectionEnd]; }catch(e){}   // throws on some input types
  return {sel,path,tag:el.tagName,type:el.type||'',caret};
}
let _tipQuiet=false;    // read by the ?-card focusin handler further down
function undoRefocus(where){
  if(!where)return;
  // a string is the pre-existing selector-only form — still accepted
  if(typeof where==='string')where={sel:where,path:null,caret:null};
  let t=where.sel?document.querySelector(where.sel):null;
  if(!t&&where.path){
    let n=document.body;
    for(const i of where.path){ n=n&&n.children[i]; if(!n)break; }
    // only take it if the re-draw put the same kind of control back here
    if(n&&n.tagName===where.tag&&(n.type||'')===where.type)t=n;
  }
  if(!t)return;
  // putting the caret back is not the user reaching for help — see the focusin
  // handler, which would otherwise pop a ? card on every keystroke that redraws
  _tipQuiet=true;
  t.focus({preventScroll:true});
  setTimeout(()=>{_tipQuiet=false;},0);
  try{
    if(!t.setSelectionRange)return;
    const c=where.caret;
    t.setSelectionRange(c?c[0]:t.value.length,c?c[1]:t.value.length);
  }catch(e){}
}
/* Undo re-draws from the model, which replaces the dialog's innerHTML and so
   throws away where you were scrolled to — landing you at the top of a 300-pool
   building every time. The containers below are the ones that scroll; they are
   matched back up by position because a re-draw of the SAME editor rebuilds the
   same structure, and an id would only cover two of them. */
const UNDO_SCROLLERS='#modal,#bldBody,#edBody,.mbody,.poollist,.caplist,.faclist,'
  +'.lvstrip,.pathwrap,.upglist,.condlist,.ugrid,#main,#drawer,.baselist,.sprpick,'
  +'.allfields,.gfbody,.uglist,.cllist,.brlist,.movelist,.plist,.sndlist,.proglist,'
  +'.batchstrip,.filters,.tiplist,.usergrid,.cklist,.dblist,'
  // the Phase 8–12 screens: traits, ancillaries, minor files and factions all
  // share one list/detail shell, and Strings has its own
  +'.trrows,.trlist,.trmain,.strlist,.strmain,.mplist,.ntslots,.cvta,.findlist';
// Matched back up by where they sit in the tree rather than by position in the
// query result: a re-draw routinely changes how many of these exist (a filter
// narrows a list, a panel closes), and an index would then hand one container's
// offset to a different one.
function _domPath(el){
  const p=[];
  for(let n=el;n&&n!==document.body&&n.parentElement;n=n.parentElement)
    p.push([...n.parentElement.children].indexOf(n));
  return p.join('.');
}
function scrollSnapshot(){
  const out=[['',window.scrollY,window.scrollX]];
  document.querySelectorAll(UNDO_SCROLLERS).forEach(el=>{
    if(el.scrollTop||el.scrollLeft)out.push([_domPath(el),el.scrollTop,el.scrollLeft]);
  });
  return out;
}
function scrollRestore(snap){
  let by=null;
  for(const [key,top,left] of snap){
    if(!key){ window.scrollTo(left,top); continue; }
    if(!by){
      by=new Map();
      document.querySelectorAll(UNDO_SCROLLERS).forEach(el=>by.set(_domPath(el),el));
    }
    const el=by.get(key);
    if(el){ el.scrollTop=top; el.scrollLeft=left; }
  }
}

/* Every workspace re-draws by replacing innerHTML, so *any* button that changes
   the model — pick a soldier, tick a faction, add a pool row — used to drop you
   back at the top with the caret gone. Undo already had to solve this; the fix
   is the same one, applied to the re-draws themselves rather than to each of the
   couple of hundred buttons that call them. */
let _placeSkip=0;
// Entry points that OPEN something new opt out: restoring the previous view's
// scroll into a different unit/building is worse than starting at the top.
function resetPlace(){_placeSkip=1;}
/* A sub-dialog (edit a requires clause, pick factions, add units, compare a unit
   across trees) replaces the whole modal and puts the stashed markup back on the
   way out. By then the scroll it is "restoring" is already gone — assigning
   innerHTML zeroes it — so the re-draw that follows has nothing to put back and
   you land at the top of a three-hundred-row level. Stash the positions with the
   markup and the next re-draw uses those instead of what it can see. */
let _placePending=null;
// Held by the caller rather than parked in a global, because the dialog's OWN
// first draw goes through keepPlace too and would otherwise eat the snapshot
// before the way out ever sees it.
function stashPlace(){return scrollSnapshot();}
function usePlace(snap){_placePending=snap||null;}
function keepPlace(draw){
  if(_placeSkip){_placeSkip=0;_placePending=null;return draw();}
  const where=undoFocus();
  const scrolled=_placePending||scrollSnapshot();
  _placePending=null;
  const done=()=>{
    scrollRestore(scrolled); undoRefocus(where);
    // images and fonts can settle a frame later and shift the content under us
    requestAnimationFrame(()=>scrollRestore(scrolled));
  };
  const r=draw();
  // some of these re-draws are async and only paint after an await
  if(r&&typeof r.then==='function'){ r.then(done,done); return r; }
  done(); return r;
}
// Wrapped after every declaration has been hoisted — see the call at the end of
// this script. Nested re-draws are harmless: the outermost restore runs last.
const PLACE_KEPT=['renderComposer','renderAllFields','renderEditor','edRenderTab',
  'renderBuildingEditor','bldRenderBody','renderSprites','renderSounds','renderBmdb',
  'renderBmdbEditor','renderCleanup','gfRender','gfRerenderBody','renderFacPicker',
  'renderCondList','renderClauseDialog','bldPickRender','renderNewUnitList',
  'renderBaseList','renderSummary',
  'renderTraits','trPaint','trPaintForm','renderAncillaries','anPaint','anPaintForm',
  'renderMinor','mfPaint','mfPaintForm','renderFactions','facPaint','facPaintForm',
  'renderStrings','strPaintBar','renderHome','packExportRender','packImportRender',
  'trgRepaint','mpRender','cmpRepaint'];
function wireKeepPlace(){
  for(const n of PLACE_KEPT){
    const f=window[n];
    if(typeof f!=='function'||f._kept)continue;
    const g=function(...a){ return keepPlace(()=>f.apply(this,a)); };
    g._kept=true; window[n]=g;
  }
}
function undoStep(redo){
  const s=undoScope();
  if(!s||s.key!==undo.key)return false;
  const from=redo?undo.future:undo.past, to=redo?undo.past:undo.future;
  if(!from.length){ toast(redo?'Nothing to redo.':'Nothing to undo.',1400); return true; }
  clearTimeout(_undoPend);                 // don't let a pending capture re-push
  const where=undoFocus(),scrolled=scrollSnapshot();
  to.push(undo.cur);
  undo.cur=from.pop(); undo.ck=null;
  s.set(JSON.parse(undo.cur));
  s.draw();
  scrollRestore(scrolled);
  undoRefocus(where);
  paintDirty();
  // a re-draw that replaces images can settle a frame later and shift things
  requestAnimationFrame(()=>scrollRestore(scrolled));
  toast((redo?'↷ Redone':'↶ Undone')+` · ${undo.past.length} more to undo`,1400);
  return true;
}
document.addEventListener('input',e=>undoTick(undoKeyOf(e.target)));
document.addEventListener('change',e=>undoTick(undoKeyOf(e.target)));
document.addEventListener('click',e=>{
  if(e.target.closest&&e.target.closest('button,a,label,.opt,.facrow,.badge,.chk'))undoTick('');
});
document.addEventListener('keydown',e=>{
  if(!(e.ctrlKey||e.metaKey)||e.altKey)return;
  const k=(e.key||'').toLowerCase();
  const redo=(k==='y')||(k==='z'&&e.shiftKey);
  if(k!=='z'&&k!=='y')return;
  // nothing of ours to undo here — leave the browser's own undo alone
  if(undoStep(redo))e.preventDefault();
});
