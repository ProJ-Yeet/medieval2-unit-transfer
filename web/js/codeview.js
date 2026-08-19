/* codeview.js — the shared two-pane widget: the boxes on one side, the file's
   own text on the other.

   Part of the Medieval 2 GUI Toolkit UI. These files are plain
   <script> tags sharing ONE global scope, loaded in the order set in
   index.html — there is no build step and no module system. Two rules
   follow from that: a top-level name must be unique across all of
   them, and a file's top-level side effects may not depend on a file
   loaded after it.

   ======================= CODE VIEW =======================
   Built once, adopted by every editor. A GUI hides the file, which is fine
   until the moment you need to know what the file actually says — then it is
   the whole problem. So each editor can show the record's real text beside its
   boxes, with the two kept in step:

     * hover a box, its line lights up (and the other way round);
     * edit a box, the text is re-serialised by the server and redrawn;
     * edit the text, the server re-reads it and the boxes follow;
     * text the parser rejects shows the reason on the offending line and
       changes nothing — the last good state is still there to save.

   THE PAGE NEVER PARSES A GAME FILE. Every arrow above goes through
   `unittransfer/codeview.py`, which uses the same parser and the same
   serialiser as the save path. That is what makes the text pane a promise
   rather than a guess: what it shows is the bytes a save would write.

   A host (the editor adopting the widget) supplies:
     kind      'edu' | 'edb' | 'bmdb' — the file shape, matching a KINDS entry
               on the server
     mod, id   which record to load
     edits()   the GUI's pending edits, in whatever shape that kind's save
               request already uses — the pane and the save then take the same
               road, which is what makes the pane a promise
     adopt(cv) the user typed in the text pane and it parsed: take cv.fields /
               cv.detail as the new truth
     refreshGui()  redraw the GUI side only (never the text pane — the caret is
               in it)
     label(el) which field the hovered element is, and find(label) the reverse.
               Optional: the default reads data-label / data-card, which is all
               an editor whose rows carry them needs.
     culture() for kinds whose record is rendered per culture (buildings).
   Everything but kind/mod/id is optional, so a read-only adopter costs nothing. */

/* One line's height in px. The textarea, the highlight overlay behind it and
   the line-number gutter beside it must agree to the pixel or the highlight
   drifts down the file, so all three take it from here and from --cvlh. */
const CV_LH = 17;
const CV_PAD = 6;                 // top padding, same three places
/* …except that raw-lines mode makes the pane's rows as tall as the boxes beside
   it, so the live value is read off the pane rather than assumed. --cvlh is
   still the one place it is set; this is how the maths gets at it. */
function cvLh(cv){
  const pane=document.getElementById('cvp-'+cv.uid);
  if(!pane)return CV_LH;
  const v=parseFloat(getComputedStyle(pane).getPropertyValue('--cvlh'));
  return v>0?v:CV_LH;
}
let CV_SEQ = 0;                   // unique DOM ids when two views are open at once
/* Live views by uid. An onclick attribute in the pane's own markup can only
   carry a string, and the pane must not assume it belongs to any one editor —
   so it looks itself up here rather than reaching into `state.ed` or `state.bld`. */
const CV_LIVE = {};
const cvOf = uid => CV_LIVE[uid];

function cvCreate(o){
  CV_SEQ += 1;
  const cv = {kind:o.kind||'edu', mod:o.mod, id:o.id, uid:'cv'+CV_SEQ, host:o,
    // `base` is the text a save would start from — the file's block until the
    // user hand-edits it, theirs afterwards. `text` is what the box holds right
    // now, which during typing is ahead of the last successful parse.
    // what the file is called, for the status line — the host knows (an EOP
    // unit's block is not in export_descr_unit.txt at all)
    where:o.where||'the file',
    // Some records are not editable AS TEXT — a voice entry only means anything
    // under the accent/class headers above it, which the block does not contain.
    // The pane still earns its place: it says what the file actually holds.
    readonly:!!o.readonly,
    // `text` is what the BOX shows; `base`/`pristine` are the record's REAL
    // bytes. They are the same thing until comment hiding is on, and keeping
    // them apart is what lets the view drop lines a save must still write.
    base:'', pristine:'', text:'', fields:[], spans:{}, partSpans:{}, note:'',
    detail:null,
    // the comment-only lines this view is not showing, and how to put them
    // back — opaque to the page, see codeview.py's hide_comments
    hidden:[], canHide:false, comments:0,
    // the layout was lined up when the record opened, and this is the text that
    // produced. A host tells "the tool did that" from "the user did that" by
    // comparing against it — see edCvUserEdited.
    auto:null,
    err:null, errLine:0, busy:false, edited:false, loaded:false, canRepair:false,
    canTidy:false, timer:null, seq:0, applying:false};
  CV_LIVE[cv.uid]=cv;
  return cv;
}

/* How a record OPENS, remembered like the rest of the view settings.

   Both are on by default, and both are why the pane is worth opening on a real
   mod's file: a hand-written EDU block is a ragged mix of tabs and spaces with
   the faction distinguishers written in among the fields, and reading down a
   value column is not possible in it. Neither changes a byte on its own — see
   cvAutoTidy for what "the tool lined it up" does and does not count as. */
const cvTidyOn=()=>((state.settings||{}).code_view_tidy!==false);
const cvHideOn=()=>((state.settings||{}).code_view_comments!=='show');

async function cvLoad(cv){
  cv.loaded=false; cv.err=null; cv.auto=null;
  const q=`mod=${encodeURIComponent(cv.mod)}&kind=${encodeURIComponent(cv.kind)}`
    +`&id=${encodeURIComponent(cv.id)}`
    +(cvHideOn()?'&hide=1':'')
    +(cv.host.culture?`&culture=${encodeURIComponent(cv.host.culture())}`:'');
  let r;
  try{ r=await api.get('/api/codeview?'+q); }
  catch(e){ r={error:''+e}; }
  cv.loaded=true;
  if(r.error){cv.err=r.error; return cv;}
  cvTakeView(cv,r);
  cv.base=cv.pristine=(r.full!=null?r.full:r.text);
  cv.note=r.note||''; cv.detail=r.detail||null;
  cv.canRepair=!!r.can_repair; cv.canTidy=!!r.can_tidy;
  cv.edited=false;
  await cvAutoTidy(cv);
  return cv;
}
// Everything an answer says about what the BOX should show. `full` is left to
// the caller: whether a new set of real bytes becomes the save's starting point
// depends on who typed them.
function cvTakeView(cv,r){
  cv.text=r.text; cv.fields=r.fields||[]; cv.spans=r.spans||{};
  cv.partSpans=r.part_spans||{}; cv.hidden=r.hidden||[];
  cv.canHide=!!r.can_hide; cv.comments=r.comments||0;
}
/* Line the record up the moment it opens.

   The button this grew out of was explicit on purpose — a layout the user wrote
   is theirs — and that rule survives in what this does NOT do. The fields are
   identical (only the gap between a keyword and its value moved), so the boxes
   are not rebuilt from it and nothing pending in them is thrown away; and the
   host is told the result is the TOOL's (`cv.auto`), so merely opening the pane
   does not make the dialog dirty. From the first real change on, the save writes
   this text — which is what keeps the pane a promise rather than a picture. */
async function cvAutoTidy(cv){
  if(!cv.loaded||cv.err||!cv.canTidy||cv.readonly||!cvTidyOn())return cv;
  let r;
  try{ r=await api.post('/api/codeview/tidy',Object.assign(cvWho(cv),{text:cv.text})); }
  catch(e){ return cv; }
  if(!r||!r.ok)return cv;              // an untidy block is still a readable one
  cvTakeView(cv,r);
  cv.base=cv.auto=(r.full!=null?r.full:r.text);
  cv.owns=true; cv.edited=false;
  return cv;
}
// Drop a view the page has finished with, so a long session's closed dialogs
// don't pile up in CV_LIVE.
function cvDrop(cv){ if(cv)delete CV_LIVE[cv.uid]; }

/* ---- markup ---- */
function cvHtml(cv){
  if(!cv.loaded)return `<div class="cvpane"><div class="cvbar"><span class="count">Loading the text…</span></div></div>`;
  const n=cvLines(cv.text).length;
  return `<div class="cvpane" id="cvp-${cv.uid}">
    <div class="cvbar">
      <span class="count" id="cvst-${cv.uid}">${cvStatus(cv)}</span>
      <span class="sp"></span>
      ${cv.canRepair?`<button title="Every string here is stored as its own length
followed by that many characters. Change a path and the number beside it has to
change too — this does that, and you can see it happen."
        onclick="cvRepair(cvOf('${cv.uid}'))">⟲ Fix lengths</button>`:''}
      ${cv.canTidy?`<button class="${cvTidyOn()?'on':''}" title="Line every value up in
one column, which is how this record now opens. Only the gap between a keyword
and its value changes: nothing is reordered, nothing is dropped, and comments
stay where they are. Turning it off reads the record back with the layout the
file itself has."
        onclick="cvTidyToggle(cvOf('${cv.uid}'))">⇥ Tidy layout</button>`:''}
      ${(cv.canHide&&cv.comments)?`<button class="${cvHideOn()?'on':''}" title="Leave the
lines that are nothing but a comment out of the box. Display only: every one of
them is still written back, byte for byte, where it sat."
        onclick="cvCommentsToggle(cvOf('${cv.uid}'))">; ${cv.comments} comment line${
          cv.comments===1?'':'s'}</button>`:''}
      <span class="count">${n} line${n===1?'':'s'}</span>
    </div>
    <div class="cvwrap">
      <div class="cvgutter"><div class="cvshift" id="cvgut-${cv.uid}">${cvGutter(cv)}</div></div>
      <div class="cvcode">
        <div class="cvhl"><div class="cvshift" id="cvhl-${cv.uid}">${cvOverlay(cv)}</div></div>
        <textarea class="cvta" id="cvta-${cv.uid}" spellcheck="false" wrap="off"
          ${cv.readonly?'readonly':''}
          aria-label="the record as the file stores it">${esc(cv.text)}</textarea>
      </div>
    </div>
    <div class="cverr" id="cverr-${cv.uid}">${cvErrHtml(cv)}</div></div>`;
}
// splitlines the way the server counts them: a trailing newline does not open a
// line the parser can see, but the box still shows a final empty row for it.
const cvLines=t=>(t==null?'':''+t).split('\n');
function cvGutter(cv){
  return cvLines(cv.text).map((_,i)=>`<div class="cvg" data-l="${i+1}">${i+1}</div>`).join('');
}
function cvOverlay(cv){
  // deliberately empty rows: the text itself is drawn by the textarea on top, so
  // there is only ever one copy of it and no font can make the two disagree
  return cvLines(cv.text).map((_,i)=>`<div class="cvl" data-l="${i+1}"></div>`).join('');
}
function cvStatus(cv){
  if(cv.err)return '<span class="w-bad">✗ this text can’t be read</span>';
  if(cv.readonly)return `what <code>${esc(cv.where)}</code> holds · read-only`;
  if(cv.busy)return 'checking…';
  if(cv.edited)return '<span class="w-good">✓ reads back — saved exactly as typed</span>';
  // the pane is a promise about the bytes a save writes, so it owns up to the
  // one thing it changed on its own
  if(cv.auto&&cv.auto!==cv.pristine)
    return 'lined up on opening · saved this way with your next change';
  return `the record as <code>${esc(cv.where)}</code> stores it`;
}
function cvErrHtml(cv){
  if(!cv.err)return cv.note?`<div class="count">${esc(cv.note)}</div>`:'';
  return `<div class="w-bad">✗ ${esc(cv.err)}${cv.errLine?` — line ${cv.errLine}`:''}
    <div class="count">Nothing is lost: fix the line, or undo your typing, and the
      boxes come straight back.</div></div>`;
}

/* ---- wiring ---- */
function cvWire(cv){
  const ta=document.getElementById('cvta-'+cv.uid); if(!ta)return;
  ta.value=cv.text;                              // survive an innerHTML redraw
  ta.onscroll=()=>cvScroll(cv);
  if(!cv.readonly)ta.oninput=()=>{
    cv.text=ta.value; cv.busy=true; cv.err=null;
    cvRedrawLines(cv); cvPaintStatus(cv);
    cvDebounce(cv,()=>cvParse(cv),250,'parse');
  };
  // the caret is a hover too: whichever line it sits on is the line the user
  // means, so the matching box lights up as they arrow through the text
  ta.onkeyup=ta.onclick=()=>cvLitGui(cv,cvLabelsAt(cv,cvCaretLine(cv,ta)));
  ta.onmousemove=ev=>cvLitGui(cv,cvLabelsAt(cv,cvLineAtY(cv,ta,ev.clientY)));
  ta.onmouseleave=()=>cvLitGui(cv,[]);
  cvScroll(cv); cvPaintSpans(cv,[]);
}
function cvScroll(cv){
  const ta=document.getElementById('cvta-'+cv.uid); if(!ta)return;
  const y=-ta.scrollTop;
  const hl=document.getElementById('cvhl-'+cv.uid);
  const g=document.getElementById('cvgut-'+cv.uid);
  // the overlay follows the text sideways too, or a value-level highlight sits
  // under the wrong characters the moment a long line is scrolled
  if(hl)hl.style.transform=`translate(${-ta.scrollLeft}px,${y}px)`;
  if(g)g.style.transform=`translateY(${y}px)`;   // the gutter never moves sideways
}
function cvRedrawLines(cv){
  const hl=document.getElementById('cvhl-'+cv.uid),g=document.getElementById('cvgut-'+cv.uid);
  if(hl)hl.innerHTML=cvOverlay(cv);
  if(g)g.innerHTML=cvGutter(cv);
  cvScroll(cv);
  // the block got longer or shorter, so whoever lines rows up against it gets
  // to do that again before the two disagree
  if(cv.host.relayout)cv.host.relayout(cv);
}
/* Grow the pane to hold the whole record, so it never scrolls.

   Raw-lines mode puts one box per EDU line beside the file's own lines and the
   promise is row for row. Two scrollers cannot keep that promise — the moment
   either moves, row n is no longer opposite line n — so both sides are fully
   expanded and the dialog is the only thing that scrolls. */
function cvExpand(cv,on){
  const pane=document.getElementById('cvp-'+cv.uid);
  const wrap=pane&&pane.querySelector('.cvwrap');
  if(!wrap)return 0;
  if(!on){wrap.style.height=''; return 0;}
  // …plus the wrap's own border, which is outside the box it holds: two pixels
  // short and the textarea grows a scrollbar and the promise is off again
  const edge=wrap.offsetHeight-wrap.clientHeight;
  const h=cvLines(cv.text).length*cvLh(cv)+CV_PAD*2+edge;
  wrap.style.height=h+'px';
  return h;
}
// Where line 1 of the text starts, measured from the top of `el`. The code pane
// carries a status bar the boxes have no equivalent of, so the two columns do
// not begin at the same y and rows placed from line numbers alone sit a bar's
// height too high.
function cvTextOrigin(cv,el){
  const ta=document.getElementById('cvta-'+cv.uid);
  if(!ta||!el)return CV_PAD;
  return ta.getBoundingClientRect().top-el.getBoundingClientRect().top
    +parseFloat(getComputedStyle(ta).paddingTop||0);
}
function cvPaintStatus(cv){
  const s=document.getElementById('cvst-'+cv.uid); if(s)s.innerHTML=cvStatus(cv);
  const e=document.getElementById('cverr-'+cv.uid); if(e)e.innerHTML=cvErrHtml(cv);
  const pane=document.getElementById('cvp-'+cv.uid);
  if(pane)pane.classList.toggle('bad',!!cv.err);
  cvPaintSpans(cv,[]);
}
function cvDebounce(cv,fn,ms,what){
  if(cv.timer)clearTimeout(cv.timer);
  cv.pending=what;
  cv.timer=setTimeout(()=>{cv.timer=null;cv.pending='';fn();},ms);
}
/* Anything about to ACT on the record — Preview, Save — must wait for the last
   keystroke to have been read. The debounce means `base` can be a quarter of a
   second behind what the box shows, and saving that would quietly drop the
   user's last word. A pending render is simply dropped instead: it only redraws
   the text pane, and the save reads the boxes it came from directly. */
async function cvSettle(cv){
  if(!cv||!cv.loaded||!cv.timer)return cv;
  const what=cv.pending;
  clearTimeout(cv.timer); cv.timer=null; cv.pending='';
  if(what==='parse')await cvParse(cv);
  return cv;
}

/* ---- the text pane was typed into ---- */
// which record this is, sent with every call so the server can build the kind's
// context (a modeldb entry's padding, a building's culture, the last good text)
// `hidden` rides along with `text` on every call: the box holds the view, and
// the server rebuilds the real bytes from the two of them before it parses.
const cvWho=cv=>({kind:cv.kind, mod:cv.mod, id:cv.id, culture:cv.host.culture
  ? cv.host.culture() : '', base:cv.base,
  hide:cvHideOn()?1:0, hidden:cv.hidden||[]});
async function cvParse(cv){
  const seq=++cv.seq, text=cv.text;
  const r=await api.post('/api/codeview/parse',Object.assign(cvWho(cv),{text}));
  if(seq!==cv.seq)return;                        // a later keystroke won the race
  cvTook(cv,r,text);
}
// Shared by parse and repair: both hand back a re-read of text the USER owns, so
// both make it the new base and let the boxes follow.
function cvTook(cv,r,text){
  cv.busy=false;
  if(!r.ok){cv.err=r.error||'this text can’t be read'; cv.errLine=r.line||0;
    cvPaintStatus(cv); cvPaintErrLine(cv); return false;}
  cv.err=null; cv.errLine=0; cv.note=r.note||'';
  cvTakeView(cv,r);
  // what the box shows is `text`; what a save writes is the same thing with the
  // hidden comment lines put back, which the server sent as `full`
  cv.base=(r.full!=null?r.full:text);
  cv.detail=r.detail||null;
  cv.edited=(cv.base!==cv.pristine);
  // From the first hand edit on, the pane owns the record's text: the boxes were
  // rebuilt from it and may hold positions that only make sense against it, so a
  // save has to keep going through the text even if it is typed back to the
  // file's own wording.
  cv.owns=true;
  cv.applying=true;
  try{ if(cv.host.adopt)cv.host.adopt(cv); if(cv.host.refreshGui)cv.host.refreshGui(); }
  finally{ cv.applying=false; }
  cvPaintStatus(cv);
  return true;
}
/* ---- put right what the format keeps in the text but nobody should type ----
   Only the modeldb has any: every string there is `<length> <text>`, so editing
   a path means editing a number nobody can be asked to count. The button is
   explicit and the corrected numbers appear on screen — nothing is fixed behind
   the user's back. */
async function cvRepair(cv){
  const text=cv.text;
  const r=await api.post('/api/codeview/repair',Object.assign(cvWho(cv),{text}));
  if(!r.ok){cv.err=r.error||'that could not be put right'; cv.errLine=r.line||0;
    cvPaintStatus(cv); cvPaintErrLine(cv); return;}
  cvTook(cv,r,r.text);
  const ta=document.getElementById('cvta-'+cv.uid);
  if(ta)ta.value=r.text;
  cvRedrawLines(cv);
  toast('Lengths put right');
}
/* Re-column the record so its values line up. Pressed by hand this is an edit
   like any other: it goes through cvTook, so the boxes are re-read from it and
   the dialog knows it has something to save. That is the whole difference
   between it and cvAutoTidy, which does the same rewriting when the record
   opens and is deliberately not the user's change. */
async function cvTidy(cv){
  const r=await api.post('/api/codeview/tidy',Object.assign(cvWho(cv),{text:cv.text}));
  if(!r.ok){cv.err=r.error||'that could not be tidied'; cv.errLine=r.line||0;
    cvPaintStatus(cv); cvPaintErrLine(cv); return;}
  cvTook(cv,r,r.text);
  const ta=document.getElementById('cvta-'+cv.uid);
  if(ta)ta.value=r.text;
  cvRedrawLines(cv);
  toast('Lined up — save to keep it');
}
/* ---- the two view settings, from the bar ----
   Turning tidying OFF cannot un-tidy text that has since been typed, so it does
   the only honest thing and reads the record back off disk. Anything typed into
   the pane goes with it, so it asks first. */
async function cvTidyToggle(cv){
  const on=cvTidyOn();
  if(on&&cv.base!==cv.pristine&&cv.base!==cv.auto
     &&!confirm('Reading the record back from the file drops what you typed in this pane. '
       +'The boxes keep their own changes. Go on?'))return;
  cvSetSetting('code_view_tidy',!on);
  if(!on)return cvTidy(cv);            // turning it on: line up what is here now
  await cvReload(cv);
}
// Hiding is a VIEW of the same bytes, so this never reloads and never costs an
// edit: the server is asked to re-cut the text the pane already owns.
async function cvCommentsToggle(cv){
  cvSetSetting('code_view_comments',cvHideOn()?'show':'hide');
  let r;
  try{ r=await api.post('/api/codeview/parse',
    Object.assign(cvWho(cv),{text:cv.base,hidden:[],hide:cvHideOn()?1:0})); }
  catch(e){ r=null; }
  if(!r||!r.ok){cvPaintStatus(cv); return;}
  cvTakeView(cv,r);
  cvRepaintAll(cv);
}
function cvSetSetting(k,v){
  state.settings[k]=v;
  const body={}; body[k]=v; api.post('/api/settings',body);
}
async function cvReload(cv){
  cv.owns=false;
  await cvLoad(cv);
  cvRepaintAll(cv);
}
// Redraw the whole pane in place: the bar's counts and the gutter both change
// when a view setting does, and only the pane's own column is replaced so the
// boxes beside it keep their scroll position and their focus.
function cvRepaintAll(cv){
  const pane=document.getElementById('cvp-'+cv.uid);
  const col=pane&&pane.parentElement;
  if(col){col.innerHTML=cvHtml(cv); cvWire(cv); cvBindHover(cv,cv.hostEl);}
  else{const ta=document.getElementById('cvta-'+cv.uid);
    if(ta)ta.value=cv.text; cvRedrawLines(cv); cvPaintStatus(cv);}
}
function cvPaintErrLine(cv){
  const hl=document.getElementById('cvhl-'+cv.uid); if(!hl)return;
  hl.querySelectorAll('.cvl.err').forEach(d=>d.classList.remove('err'));
  const d=cv.errLine&&hl.querySelector(`.cvl[data-l="${cv.errLine}"]`);
  if(d)d.classList.add('err');
}

/* ---- a box was typed into ----
   The text is re-serialised by the server rather than patched here: the boxes
   only know values, and the file also has an order, an indent and comments that
   only `apply_field_edits` knows how to keep. */
function cvFromGui(cv){
  if(!cv||!cv.loaded||cv.applying)return;
  cvDebounce(cv,()=>cvRender(cv),250,'render');
}
async function cvRender(cv){
  const ta=document.getElementById('cvta-'+cv.uid);
  if(ta&&document.activeElement===ta)return;     // they are typing in the text, not the boxes
  const seq=++cv.seq;
  const r=await api.post('/api/codeview/render',Object.assign(cvWho(cv),
    {edits:(cv.host.edits&&cv.host.edits())||{}}));
  if(seq!==cv.seq||!r.ok)return;
  cv.text=r.text; cv.spans=r.spans||{}; cv.partSpans=r.part_spans||{};
  cv.fields=r.fields||[]; cv.err=null; cv.busy=false;
  const box=document.getElementById('cvta-'+cv.uid);
  if(box&&document.activeElement!==box)box.value=cv.text;
  cvRedrawLines(cv); cvPaintStatus(cv);
}

/* ---- the two-way highlight ---- */
// line -> the labels whose span covers it (usually one; a wrapped field, none)
function cvLabelsAt(cv,line){
  if(!line)return [];
  const out=[];
  Object.keys(cv.spans||{}).forEach(l=>{
    (cv.spans[l]||[]).forEach(([a,b])=>{if(line>=a&&line<=b&&out.indexOf(l)<0)out.push(l);});
  });
  return out;
}
const cvCaretLine=(cv,ta)=>ta.value.slice(0,ta.selectionStart).split('\n').length;
function cvLineAtY(cv,ta,clientY){
  const r=ta.getBoundingClientRect();
  const n=Math.floor((clientY-r.top-CV_PAD+ta.scrollTop)/cvLh(cv))+1;
  return (n>=1&&n<=cvLines(cv.text).length)?n:0;
}
/* Light the file's line(s) for these labels — called when a box is hovered.

   `part` is the index of ONE value on the line, which is what the guided editor
   hovers: `stat_pri 14, 4, no, 0, 0, melee, …` is eleven settings, and lighting
   the whole line when the pointer is on the fourth of them says nothing. The
   column ranges come from the server (`part_spans`, tabs already expanded), so
   the page still never reads the text itself; a monospace `ch` is the unit both
   sides agree in. */
function cvPaintSpans(cv,labels,part){
  const hl=document.getElementById('cvhl-'+cv.uid); if(!hl)return;
  hl.querySelectorAll('.cvl.on').forEach(d=>d.classList.remove('on'));
  hl.querySelectorAll('.cvtok').forEach(d=>d.remove());
  const g=document.getElementById('cvgut-'+cv.uid);
  if(g)g.querySelectorAll('.cvg.on').forEach(d=>d.classList.remove('on'));
  let first=0;
  labels.forEach(l=>(cv.spans[l]||[]).forEach(([a,b])=>{
    for(let i=a;i<=b;i++){
      const d=hl.querySelector(`.cvl[data-l="${i}"]`); if(d)d.classList.add('on');
      const n=g&&g.querySelector(`.cvg[data-l="${i}"]`); if(n)n.classList.add('on');
      if(!first)first=i;
    }
  }));
  let tok=null;
  if(part!=null&&labels.length===1){
    tok=(cv.partSpans[labels[0]]||[])[part]||null;
    if(tok){
      const row=hl.querySelector(`.cvl[data-l="${tok[0]}"]`);
      if(row){const i=document.createElement('i'); i.className='cvtok';
        i.style.left=`calc(8px + ${tok[1]}ch)`;
        i.style.width=`${Math.max(1,tok[2]-tok[1])}ch`;
        row.appendChild(i);}
    }
  }
  // …and bring it into view. A 60-line record does not fit the pane, so a
  // highlight the user has to go and find is a highlight they never see.
  if(first)cvReveal(cv,tok?tok[0]:first,tok?tok[2]:0);
  return first;
}
// Scroll the text pane so line `n` (and, when given, column `col`) is visible.
// Only when it is not already: scrolling under a still pointer is worse than
// scrolling too little.
function cvReveal(cv,n,col){
  const ta=document.getElementById('cvta-'+cv.uid); if(!ta)return;
  const lh=cvLh(cv), top=(n-1)*lh, h=ta.clientHeight;
  if(ta.scrollHeight<=h+1)return;      // fully expanded: there is nothing to reveal
  if(top<ta.scrollTop||top>ta.scrollTop+h-lh*2){
    ta.scrollTop=Math.max(0,top-h/3);
  }
  if(col){
    const chw=cvCharWidth(ta), x=col*chw, w=ta.clientWidth;
    if(x<ta.scrollLeft||x>ta.scrollLeft+w-24)ta.scrollLeft=Math.max(0,x-w/2);
  }
  cvScroll(cv);
}
// One character's width in the pane's font, measured once per view.
function cvCharWidth(ta){
  if(ta._cvcw)return ta._cvcw;
  const s=document.createElement('span');
  s.style.cssText='position:absolute;visibility:hidden;white-space:pre';
  s.style.font=getComputedStyle(ta).font;
  s.textContent='0'.repeat(50);
  document.body.appendChild(s);
  const w=s.getBoundingClientRect().width/50;
  s.remove();
  return (ta._cvcw=w||7);
}
// …and the other way: light the box for the line under the pointer or caret.
// `find` is the mirror of `label` and belongs to the host for the same reason.
const cvDefaultFind=l=>document.querySelectorAll(
  `[data-label="${cssq(l)}"],[data-card="${cssq(l)}"]`);
function cvLitGui(cv,labels){
  document.querySelectorAll('.cvlit').forEach(el=>el.classList.remove('cvlit'));
  const find=cv.host.find||cvDefaultFind;
  labels.forEach(l=>(find(l)||[]).forEach(el=>el.classList.add('cvlit')));
}
/* The GUI side's hover, bound by delegation on whatever box holds the rows —
   they are rebuilt constantly (every keystroke in guided mode redraws a card),
   and a listener per row would be re-attached each time or, worse, forgotten.

   Which label a row means is the HOST's business: the unit editor tags its rows
   `data-label`/`data-card`, but the buildings editor's rows are `data-scalar`,
   `data-cap` and friends, and rewriting a 3000-line file to add a second set of
   attributes would be churn for nothing. So a host may pass `label(el)`. */
const cvDefaultLabel=el=>{
  const row=el.closest&&el.closest('[data-label],[data-card]');
  return row?(row.dataset.label||row.dataset.card):'';
};
// Which ONE value of a multi-value line this element edits, or null. The guided
// editor tags every box with the line it belongs to and its position on it.
const cvPartOf=el=>{
  const p=el.closest&&el.closest('[data-i]');
  return p?+p.dataset.i:null;
};
function cvBindHover(cv,hostEl){
  const el=hostEl||document.getElementById('edFieldsCol');
  if(!cv||!el||!cv.loaded)return;
  cv.hostEl=hostEl||null;              // so a repaint can rebind the same side
  // a resolver may name several spans at once: one box can stand for a value
  // every faction record repeats
  const label=el=>{const l=(cv.host.label||cvDefaultLabel)(el);
    return l?(Array.isArray(l)?l:[l]):[];};
  el.onmouseover=ev=>{
    const ls=(ev.target&&label(ev.target))||[];
    const part=ev.target?cvPartOf(ev.target):null;
    const key=ls.join('|')+'@'+part;
    if(key!==cv.hovLabel){cv.hovLabel=key; cvPaintSpans(cv,ls,part);}
  };
  el.onmouseleave=()=>{cv.hovLabel=''; cvPaintSpans(cv,[]);};
  // clicking a row's name scrolls the file to it — a 60-line record does not fit
  el.onclick=ev=>{
    const lab=ev.target.closest&&ev.target.closest('label,.gfhead .k,.k,h4');
    if(!lab)return;
    const ls=label(lab); if(ls.length)cvScrollTo(cv,ls[0]);
  };
}
const cvScrollTo=(cv,label)=>cvPaintSpans(cv,[label]);   // paint reveals it
