/* ---- Clean up the unit file -------------------------------------------
   The whole-file counterpart to the Unit Editor: it tidies, tiers, groups and
   reorders every block in export_descr_unit.txt at once.

   Two screens in one dialog. **Clean up** previews what would change and writes
   it; **Order** lists each section's units and lets one be dragged to where the
   sorter should have put it. Nothing is written until Apply, and the whole job
   is one backup and one Undo entry — see unittransfer/edusort.py.

   A hand placement is remembered per section and sent back with the next plan,
   so the sorter honours it rather than arguing with it. */

const eduTidy={mod:'',plan:null,view:'clean',sections:[],hand:{},busy:false,
               opts:{tidy:true,group:true,banners:true,tiers:true}};

async function openEduTidy(){
  eduTidy.mod=state.src; eduTidy.plan=null; eduTidy.view='clean';
  eduTidy.sections=[]; eduTidy.hand={};
  const modal=document.getElementById('modal');
  modal.className='modal wide';
  modal.innerHTML='<h2>Clean up the unit file…</h2>';
  overlay.classList.add('open');
  undoReset();
  renderEduTidy();
  eduTidyPlan();
}

function eduTidyRender(){renderEduTidy();}

function renderEduTidy(){
  const t=eduTidy,p=t.plan;
  const tab=(k,label)=>`<button class="${t.view===k?'on':''}"
    onclick="eduTidyView('${k}')">${label}</button>`;
  document.getElementById('modal').innerHTML=`
    <h2>Clean up the unit file <span class="pill">${esc(t.mod)}</span></h2>
    <div class="tabs">${tab('clean','Clean up')}${tab('order','Order')}</div>
    <div class="mbody" id="eduBody">${
      t.view==='clean'?eduTidyClean():eduTidyOrder()}</div>
    <div class="foot">
      <button onclick="closeModal()">Close</button>
      <button class="primary" ${(!p||!p.touched||p.errors.length||t.busy)?'disabled':''}
        onclick="eduTidyApply()">${t.busy?'Working…':'Apply'}</button>
    </div>`;
  if(t.view==='order')eduTidyWireOrder();
}

function eduTidyView(v){eduTidy.view=v; renderEduTidy();
  if(v==='order'&&!eduTidy.sections.length)eduTidyLoadOrder();}

const eduOpt=(k,label,hint)=>`<label class="chk" title="${esc(hint)}">
  <input type="checkbox" ${eduTidy.opts[k]?'checked':''}
    onchange="eduTidySet('${k}',this.checked)"> ${label}</label>`;

function eduTidySet(k,v){eduTidy.opts[k]=v; eduTidyPlan();}

function eduTidyClean(){
  const p=eduTidy.plan;
  const opts=`<fieldset><legend>What to do</legend>
    ${eduOpt('group','Group the units into sections',
             'Move each unit into its faction’s run, ordered by tier then by kind')}
    ${eduOpt('tiers','Read tiers from the file’s own banners',
             'A banner like ;--- GONDOR TIER 2 INFANTRY --- already says the tier')}
    ${eduOpt('banners','Write a banner above each section',
             'One comment line naming the section, tier and kind')}
    ${eduOpt('tidy','Line every unit’s values up in one column',
             'Rewrites only the gap between a keyword and its value')}
    <div class="count" style="margin-top:6px">${docPoints(
      'This rewrites the whole unit file in one go.',[
      'It only ever <b>moves</b> a block. No unit, field or comment of yours is changed or lost, '+
        'and the preview is refused outright if that is not true of the result.',
      'A tier read from a banner is written onto the unit as <code>;@m2gt tier=2</code>, so the '+
        'next run does not have to read it again.',
      'One backup, one entry in the log, one Undo.'])}</div>
  </fieldset>`;
  if(!p)return opts+'<div class="empty">Working out what would change…</div>';
  if(p.errors.length)
    return opts+`<div class="w-bad">${p.errors.map(esc).join('<br>')}</div>`;
  if(!p.touched)
    return opts+'<div class="empty">This file is already in shape — nothing to change.</div>';
  const secs=p.sections.map(s=>`<tr><td>${esc(s.name)}</td>
    <td class="num">${s.units}</td></tr>`).join('');
  return opts+`
    <div class="cards"><ul>${p.changes.map(c=>`<li>${esc(c)}</li>`).join('')}</ul></div>
    ${p.warnings.length?`<div class="w-warn">${p.warnings.map(esc).join('<br>')}</div>`:''}
    <div class="two">
      <div><h3>Sections (${p.sections.length})</h3>
        <div class="scroll" style="max-height:280px"><table class="grid">
          <thead><tr><th>Section</th><th class="num">Units</th></tr></thead>
          <tbody>${secs}</tbody></table></div></div>
      <div><h3>Units that move (${p.moved_count})</h3>
        <div class="scroll" style="max-height:280px" class="count">${
          p.moved.map(esc).join('<br>')||'— none —'}${
          p.moved_count>p.moved.length?`<br><span class="count">…and ${
            p.moved_count-p.moved.length} more</span>`:''}</div></div>
    </div>`;
}

/* ---- the per-section order screen ----
   Drag a unit onto another to place it there by hand. The placement is sent
   with the next plan as `hand`, and the sorter leads that section's run with it
   instead of working the position out from the tier. */
function eduTidyOrder(){
  const t=eduTidy;
  if(!t.sections.length)return '<div class="empty">Reading the unit file…</div>';
  const rows=s=>s.units.map((u,i)=>`<span class="chipd${
      (t.hand[s.name]||[]).indexOf(u.type)>=0?' added':''}" draggable="true"
      data-sec="${esc(s.name)}" data-i="${i}"
      title="${u.general?'General · ':''}${esc(u.category)}${
        u.tier?' · tier '+esc(u.tier):' · no tier'} — drag to place by hand">
      <span class="g">⠿</span><span>${esc(u.type)}</span>
      <span class="count">${u.general?'general':esc(u.tier||'—')}</span></span>`).join('');
  return `<div class="count">${docPoints(
      'Drag a unit onto another to say where it really belongs.',[
      'The sorter groups by tier and by kind, which is right for most units and wrong for the '+
        'ones a mod treats specially. A unit you place by hand leads its section instead.',
      'Placements apply on <b>Apply</b>, with everything else on the Clean up tab.'])}</div>
    ${t.sections.map(s=>`<fieldset style="margin-top:10px">
      <legend>${esc(s.name)} <span class="count">${s.units.length}</span></legend>
      <div class="chips">${rows(s)}</div></fieldset>`).join('')}`;
}

function eduTidyWireOrder(){
  let from=null;
  document.querySelectorAll('#eduBody [data-sec]').forEach(el=>{
    el.ondragstart=ev=>{from={sec:el.dataset.sec,i:+el.dataset.i};
      ev.dataTransfer.effectAllowed='move'; el.classList.add('drag');};
    el.ondragover=ev=>{if(from&&from.sec===el.dataset.sec){ev.preventDefault();
      el.classList.add('over');}};
    el.ondragleave=()=>el.classList.remove('over');
    el.ondragend=()=>{el.classList.remove('drag'); from=null;};
    el.ondrop=ev=>{
      if(!from||from.sec!==el.dataset.sec)return;
      ev.preventDefault();
      const s=eduTidy.sections.find(x=>x.name===el.dataset.sec),to=+el.dataset.i;
      if(from.i===to){from=null; return;}
      const [moved]=s.units.splice(from.i,1); s.units.splice(to,0,moved);
      eduTidy.hand[s.name]=s.units.map(u=>u.type);
      from=null; renderEduTidy(); eduTidyPlan();
    };
  });
}

async function eduTidyLoadOrder(){
  try{
    const r=await api.get(`/api/edu/order?mod=${enc(eduTidy.mod)}`);
    eduTidy.sections=r.sections||[];
  }catch(e){ toast(''+e,4000); }
  renderEduTidy();
}

async function eduTidyPlan(){
  const t=eduTidy;
  try{
    const r=await api.post('/api/edu/sort/plan',
      Object.assign({mod:t.mod,hand:t.hand},t.opts));
    t.plan=r.plan||{errors:[r.error||'no answer'],changes:[],warnings:[],
                    sections:[],moved:[],moved_count:0,touched:false};
  }catch(e){
    t.plan={errors:[''+e],changes:[],warnings:[],sections:[],moved:[],
            moved_count:0,touched:false};
  }
  renderEduTidy();
}

async function eduTidyApply(){
  const t=eduTidy;
  t.busy=true; renderEduTidy();
  try{
    const r=await api.post('/api/edu/sort/apply',
      Object.assign({mod:t.mod,hand:t.hand},t.opts));
    if(r.error){toast(r.error,5000); return;}
    activity('cleaned up the unit file',
             `${r.moved} unit(s) moved in ${t.mod}`);
    toast(`Unit file cleaned up — ${r.moved} unit(s) moved. 🕑 Log can undo it.`,5000);
    closeModal();
    loadSource();                // the roster on screen came from the file we just rewrote
  }catch(e){ toast(''+e,5000); }
  finally{ t.busy=false; }
}
