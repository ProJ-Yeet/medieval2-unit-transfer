/* sounds.js — Unit Sounds mode: which voice-bank entry a unit speaks with

   Part of the Medieval 2 GUI Toolkit UI. These files are plain
   <script> tags sharing ONE global scope, loaded in the order set in
   index.html — there is no build step and no module system. Two rules
   follow from that: a top-level name must be unique across all of
   them, and a file's top-level side effects may not depend on a file
   loaded after it. */
/* ======================= SOUNDS MODE =======================
   The unit VOICE BANK (data/export_descr_sounds_units_voice.txt): which .wav files
   a unit's soldiers shout when you select them.

   A unit's voice needs two things that have to agree: a `unit <type>` entry inside
   one accent/class block of the bank, and the EDU's `accent` + `voice_type` fields
   pointing at that same block. Get one without the other and the unit is silent —
   which is why every row here writes both, and why the accent/class of a row snap
   to whatever donor you pick instead of being editable independently.

   Everything is staged in memory and written in one apply, straight into the mod,
   through the same backups + 🕑 Log undo as a transfer. (The prototype this grew
   out of needed a .bat to generate reference files, a hand-run editor, exported
   patch CSVs, and a second .bat to fold them back in — none of that exists here.) */
async function loadSounds(){
  const mod=state.src;
  main.innerHTML='<div class="empty">Reading '+esc(mod)+'’s voice bank…</div>';
  let r;
  try{ r=await api.get('/api/sounds?mod='+enc(mod)); }
  catch(e){ if(stale('sounds',mod))return;
    main.innerHTML=`<div class="empty">Couldn't read the voice bank.<br>
    <span class="count">${esc(''+e)}</span><br><br>
    <button class="primary" onclick="loadSounds()">Retry</button></div>`; return; }
  if(stale('sounds',mod))return;        // moved on while this was in flight
  // `ops` is the staging area: unit type -> {accent, class, donor, remove}
  state.snd=Object.assign({tab:'missing',ops:{},fAccent:'',fClass:'',onlyBad:false,
                           bulkDonor:'',view:[],
                           // the read-only voice-bank pane, and which unit it shows
                           cv:null,cvUnit:''},r);
  undoReset();
  renderSounds();
}
// Donors that live in one accent/class block. A donor from another block is no use:
// copying its entry into this block would give the unit that block's neighbours,
// not the sounds you picked.
function sndDonors(accent,cls){
  if(!accent||!cls)return [];
  return state.snd.donors.filter(d=>d.accent===accent&&d['class']===cls);
}
function sndOp(type){const s=state.snd; return s.ops[type]||(s.ops[type]={});}
// The value a row currently shows: what's staged, else the bank's (existing units)
// or the EDU's if the bank has a block for it (missing units — a unit whose EDU
// already names a real accent is nearly always meant to stay there).
function sndVal(u,key){
  const op=state.snd.ops[u.type]||{};
  if(op[key]!==undefined)return op[key];
  if(key==='donor')return '';
  if(key==='accent')return u.accent!==undefined?u.accent:(u.accent_valid?u.edu_accent:'');
  return u['class']!==undefined?u['class']:(u.class_valid?u.edu_class:'');
}
// A row is only sent when it would actually do something. A new entry needs a donor
// to copy (there is nothing else to build one from); an existing one can also just
// move block, or be dropped.
function sndReady(u){
  const op=state.snd.ops[u.type]||{};
  if(op.remove)return true;
  const a=sndVal(u,'accent'),c=sndVal(u,'class');
  if(!a||!c)return false;
  if(u.accent===undefined)return !!op.donor;          // missing -> needs a donor
  return !!op.donor||a!==u.accent||c!==u['class'];
}
function sndOps(){
  const s=state.snd,out=[];
  for(const u of s.missing.concat(s.existing)){
    if(!sndReady(u))continue;
    const op=s.ops[u.type]||{};
    out.push({unit:u.type,accent:sndVal(u,'accent'),class:sndVal(u,'class'),
              donor:op.donor||'',remove:!!op.remove});
  }
  for(const o of s.orphans){const op=s.ops[o.type];
    if(op&&op.remove)out.push({unit:o.type,remove:true});}
  return out;
}
/* One place where every staged change is made, and the ONLY place the row is
   repainted from — state first, paint second. Doing it the other way round is what
   made the prototype need two clicks to take a unit: picking a donor rebuilt the
   dropdown from a `copyFrom` that had not been written yet, so the first pick was
   thrown away and only the second one stuck. */
function sndPick(i,key,value){
  const u=state.snd.view[i]; if(!u)return;
  const op=sndOp(u.type);
  op[key]=value;
  if(key==='donor'&&value){
    const d=state.snd.donors.find(x=>x.name===value);
    if(d){op.accent=d.accent; op['class']=d['class'];}   // the entry has to land in ITS block
  }
  // moving the row to another block orphans a donor from the old one
  if((key==='accent'||key==='class')&&op.donor){
    const d=state.snd.donors.find(x=>x.name===op.donor);
    if(!d||d.accent!==sndVal(u,'accent')||d['class']!==sndVal(u,'class'))op.donor='';
  }
  renderSounds();
}
function sndToggleRemove(i,on){
  const u=state.snd.view[i]; if(!u)return;
  sndOp(u.type).remove=on; renderSounds();
}
function sndTab(t){state.snd.tab=t; renderSounds();}
function sndFilter(key,v){state.snd[key]=v; renderSounds();}
function sndReset(){state.snd.ops={}; renderSounds(); toast('Staged voice changes cleared.');}
// Give every visible row the same donor in one go — the usual job here is "these
// forty new units should all sound like that one", and doing it row by row is the
// step this replaces.
function sndBulk(){
  const name=state.snd.bulkDonor; if(!name){toast('Pick a unit to copy from first.');return;}
  const d=state.snd.donors.find(x=>x.name===name); if(!d)return;
  let n=0;
  for(const u of state.snd.view){
    if(u.type===name)continue;                       // never make a unit copy itself
    const op=sndOp(u.type); op.donor=name; op.accent=d.accent; op['class']=d['class']; n++;
  }
  renderSounds();
  toast(`${n} row(s) set to copy “${name}” (${d.accent}/${d['class']}).`);
}
const SND_CAP=150;   // selects are expensive; the filters above are how you reach the rest
