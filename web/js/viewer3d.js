/* viewer3d.js — the 3D model viewer

   Part of the Medieval 2 GUI Toolkit UI. These files are plain
   <script> tags sharing ONE global scope, loaded in the order set in
   index.html — there is no build step and no module system. Two rules
   follow from that: a top-level name must be unique across all of
   them, and a file's top-level side effects may not depend on a file
   loaded after it. */
/* =========================================================================
   THE MODEL VIEWER — a battle model, drawn, from the entry that names it.

   Plain WebGL, no library. A static textured model needs one shader, one
   orbit camera and a texture bind, and the alternative was vendoring 600 KB
   of three.js into a project whose whole point is that it has no build step.

   The geometry arrives from /api/model/geometry as ONE binary payload, not
   as JSON: a soldier is a few thousand vertices and spelling those floats
   out as text costs about six times the bytes and a parse on top. The header
   is JSON, the arrays are raw, and each one goes straight into a buffer.

   Four things about the format drive the whole UI here (see mesh.py):

     * indices are GLOBAL into one shared vertex pool, so a group is a face
       range rather than a mesh of its own — one buffer, one draw call per
       visible group, no per-group vertex data;
     * a group is named `type` + `mesh name` — the two halves of the Blender
       addon's `objectname__comment` — and carries a required/optional flag,
       its `__opt`. Groups sharing a TYPE are variants of one part and the game
       picks one per soldier. Drawing them all at once puts three heads on one
       man, so the viewer picks one per part and offers the others, which is
       also how you look at what a mod actually shipped;
     * a model is painted from the main and attachment textures GLUED into
       one image, main in u 0..1 and attachment in u 1..2, tiling in both
       axes outside that. The UVs address the pair, so they go to the
       shader untouched and no code chooses a sheet for a part;
     * the models are LEFT-handed (Direct3D). Handed straight to a right-handed
       viewer they come out mirrored — shield on the wrong arm — so the model
       matrix negates X.
   ========================================================================= */

/* --- small matrix helpers -------------------------------------------------
   Only the four operations a fixed-function camera needs. Column-major, the
   order WebGL wants, so they go to uniformMatrix4fv untransposed. */
function v3Perspective(fovY, aspect, near, far){
  const f = 1 / Math.tan(fovY / 2), d = near - far;
  return [f/aspect,0,0,0, 0,f,0,0, 0,0,(far+near)/d,-1, 0,0,2*far*near/d,0];
}
function v3LookAt(eye, at, up){
  const z = v3Norm([eye[0]-at[0], eye[1]-at[1], eye[2]-at[2]]);
  const x = v3Norm(v3Cross(up, z));
  const y = v3Cross(z, x);
  return [x[0],y[0],z[0],0, x[1],y[1],z[1],0, x[2],y[2],z[2],0,
          -v3Dot(x,eye), -v3Dot(y,eye), -v3Dot(z,eye), 1];
}
function v3Cross(a,b){ return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]; }
function v3Dot(a,b){ return a[0]*b[0]+a[1]*b[1]+a[2]*b[2]; }
function v3Norm(a){
  const L = Math.hypot(a[0],a[1],a[2]) || 1;
  return [a[0]/L, a[1]/L, a[2]/L];
}

/* --- the environment ------------------------------------------------------
   A procedural stand-in for the studio HDRI Blender lights its viewport with.
   Shipping a real .hdr would mean a megabyte of asset and a decoder for it, and
   for an inspection viewer the part of an HDRI that matters is the part this
   reproduces: sky above, ground below, a bright band at the horizon, and light
   arriving from every direction rather than from one lamp. The SAME function
   paints the backdrop and lights the model, which is what makes a model look
   like it is standing in the scene instead of floating on a flat colour.

   It is also why the background is no longer near-black: a dark unit on a dark
   field is unreadable, and armour has nothing to reflect. */
const V3_ENV = `
vec3 v3Env(vec3 d){
  vec3 sky     = vec3(0.36, 0.45, 0.62);
  vec3 horizon = vec3(0.78, 0.79, 0.80);
  vec3 ground  = vec3(0.24, 0.22, 0.20);
  float t = clamp(d.y, -1.0, 1.0);
  return t > 0.0 ? mix(horizon, sky, pow(t, 0.55))
                 : mix(horizon, ground, pow(-t, 0.40));
}`;

const V3_VERT = `
attribute vec3 aPos; attribute vec3 aNormal; attribute vec2 aUv;
uniform mat4 uProj, uView; uniform mat4 uModel;
varying vec3 vNormal; varying vec2 vUv;
void main(){
  // uModel mirrors X (see v3Draw), and for a mirror the inverse-transpose that
  // normals want is the matrix itself — so mat3(uModel) is right here.
  vNormal = mat3(uModel) * aNormal;
  vUv = aUv;
  gl_Position = uProj * uView * uModel * vec4(aPos, 1.0);
}`;

/* ONE texture, and it is the two sheets side by side.

   This is how the game does it and it is not the same thing as picking a sheet
   per part. A model's modeldb entry names a main texture and an attachment
   texture; the game lays them out as one image twice as wide, main on the left
   and attachment on the right, and the mesh's single UV set addresses THAT.
   So u 0..1 lands on the main sheet, u 1..2 lands on the attachment sheet, and
   anything outside repeats — the whole pair tiles, infinitely, in both axes.

   Which is why the shader does nothing clever: the UVs go in as the modeller
   authored them and only the halving that turns "two sheets wide" into "one
   texture wide" is applied. That halving is NOT redundant with anything the
   decoder does, and removing it is the bug to not reintroduce: the FILE stores
   u normalised over the pair (main 0..0.5), mesh.py doubles it on read into
   the space above — the space IWTE and the Blender addon use — and this halves
   it again to land in the atlas. Take either step out and every model samples a
   squeezed stripe of one sheet. Nothing is wrapped, folded or normalised into
   0..1, and no branch decides a part's sheet — the coordinate already says.
   The 112 groups with u < 0 and the 268 with v outside 0..1 in one mod alone
   are the proof that the tiling is real and must not be clamped away. */
const V3_FRAG = `
precision mediump float;
varying vec3 vNormal; varying vec2 vUv;
uniform sampler2D uTex;
uniform float uHasTex, uFlat;
uniform vec3 uKey, uEye;
${V3_ENV}
void main(){
  vec4 base = uHasTex > 0.5
    ? texture2D(uTex, vec2(vUv.x * 0.5, vUv.y))
    : vec4(0.72, 0.66, 0.56, 1.0);
  if(base.a < 0.35) discard;          // the alpha channel is a cut-out mask
  if(uFlat > 0.5){ gl_FragColor = vec4(0.92, 0.94, 0.98, 1.0); return; }

  vec3 n = normalize(vNormal);
  // ambient straight out of the environment, so a surface facing the sky picks
  // up the sky and one facing the floor goes warm and dark
  vec3 light = v3Env(n) * 0.62;
  light += vec3(1.00, 0.96, 0.90) * 0.50 * max(dot(n, normalize(uKey)), 0.0);
  light += vec3(0.62, 0.70, 0.85) * 0.20 * max(dot(n, normalize(vec3(-0.6, 0.2, -0.7))), 0.0);
  light += vec3(1.0) * 0.18 * max(dot(n, normalize(uEye)), 0.0);   // fill from the camera
  // Unit art is sRGB and this multiply is linear, so a light of 0.5 lands far
  // darker than half-lit looks — which is how a viewer of dark armour and dark
  // cloth ends up a viewer of silhouettes. The curve lifts the mid-tones back
  // without touching what is already fully lit. An inspection tool, not a
  // render: you have to be able to SEE the thing.
  gl_FragColor = vec4(pow(clamp(base.rgb * light, 0.0, 1.0), vec3(0.78)), 1.0);
}`;

/* The backdrop: one full-screen triangle, each pixel asking the environment
   what lies along its own view ray — so the horizon sits still while the model
   turns, and pitching the camera up shows sky and down shows ground. */
const V3_BG_VERT = `
attribute vec2 aQuad;
uniform vec3 uRight, uUp, uFwd; uniform vec2 uScale;
varying vec3 vDir;
void main(){
  vDir = normalize(uFwd + uRight * aQuad.x * uScale.x + uUp * aQuad.y * uScale.y);
  gl_Position = vec4(aQuad, 0.999, 1.0);
}`;

const V3_BG_FRAG = `
precision mediump float;
varying vec3 vDir;
${V3_ENV}
void main(){
  // a touch darker than the light it casts, so the model reads against it
  gl_FragColor = vec4(v3Env(normalize(vDir)) * 0.55, 1.0);
}`;

let v3 = null;          // the live viewer, or null when the dialog is closed
let v3Back = null;      // the dialog we opened over, to put back on close

/* --- opening -------------------------------------------------------------- */

async function v3Open(mod, entry){
  const modal = document.getElementById('modal');
  const overlay = document.getElementById('overlay');
  const wasOpen = overlay.classList.contains('open');
  v3Back = wasOpen ? {html: modal.innerHTML, cls: modal.className, scroll: stashPlace()} : {};
  modal.className = 'modal wide';
  modal.innerHTML = `<h2>Model — ${esc(entry)}</h2>
    <div class="mbody"><div class="empty">Reading ${esc(entry)}…</div></div>
    <div class="foot"><button onclick="v3Close()">Close</button></div>`;
  overlay.classList.add('open');

  let info;
  try{ info = await api.get(`/api/model?mod=${enc(mod)}&entry=${enc(entry)}`); }
  catch(e){ return v3Fail(''+e); }
  if(info.error) return v3Fail(info.error);

  // `skin` indexes info.skins, because a skin is a PAIR of files now — the
  // main sheet and the attachment sheet a faction uses together — and a pair
  // has no one path to name it by
  v3 = {mod, entry, info, lod: 0, skin: 0,
        geo: null, tex: null, texAtt: null, hidden: {}, variant: {},
        wire: false, spin: false,
        yaw: 0.6, pitch: 0.25, dist: 3, centre: [0,0,0], gl: null, err: ''};
  // open on the first LOD the mod actually ships — an entry whose lod0 lives in
  // a .pack still has lod1 and lod2 on disk more often than not
  const there = info.lods.find(l => l.exists);
  v3.lod = there ? there.index : 0;
  v3Render();
  await v3Load();
}

/* What to call a skin in the picker: the faction that uses it, and how many
   others share it. A skin used by everyone is named for the file instead —
   there is no one faction it belongs to. */
function v3SkinLabel(s){
  const n = (s.factions||[]).length;
  if(n === 0) return (s.rel || 'no texture').split('/').pop();
  if(n === 1) return facLabel(s.factions[0]);
  return `${facLabel(s.factions[0])} +${n-1} more`;
}

/* The skin the viewer is on, and its two sheets. */
function v3Skin(){ return (v3.info.skins || [])[v3.skin] || null; }

function v3Fail(msg){
  const b = document.querySelector('#modal .mbody');
  if(b) b.innerHTML = `<div class="w-bad">${esc(msg)}</div>`;
}

function v3Close(){
  v3Stop();
  const modal = document.getElementById('modal');
  if(v3Back && v3Back.html !== undefined){
    modal.className = v3Back.cls; modal.innerHTML = v3Back.html;
    usePlace(v3Back.scroll);
    // the restored markup is inert until its own module rebinds it, and only
    // the model card ever opens this — so it is the one that gets asked
    if(typeof edRenderTab === 'function' && state.ed) edRenderTab();
  }else{
    document.getElementById('overlay').classList.remove('open');
    modal.className = 'modal'; modal.innerHTML = '';
  }
  v3Back = null; v3 = null;
}

function v3Stop(){
  if(v3 && v3.raf) cancelAnimationFrame(v3.raf);
  if(v3 && v3.gl){
    const gl = v3.gl;
    [v3.bPos, v3.bNormal, v3.bUv, v3.bIdx, v3.bLines, v3.bQuad]
      .forEach(b => b && gl.deleteBuffer(b));
    if(v3.texture) gl.deleteTexture(v3.texture);
    [v3.prog, v3.bg].forEach(p => p && gl.deleteProgram(p));
  }
  if(v3) v3.gl = null;
}

/* --- the dialog ----------------------------------------------------------- */

function v3Render(){
  if(!v3) return;
  const i = v3.info;
  const lods = i.lods.map(l =>
    `<option value="${l.index}" ${l.index===v3.lod?'selected':''} ${l.exists?'':'disabled'}>
       LOD ${l.index}${l.distance?` · from ${l.distance}m`:''}${l.exists?'':' — not in this mod'}
     </option>`).join('');
  // one option per PAIR of files: an entry that lists 29 factions against the
  // same main and attachment textures has one skin, and saying so is more use
  // than 29 identical rows
  const skins = i.skins.length
    ? i.skins.map((s, n) => `<option value="${n}" ${n===v3.skin?'selected':''}
        ${s.exists?'':'disabled'}>${esc(v3SkinLabel(s))}${s.exists?'':' — not in this mod'}</option>`).join('')
    : '<option>no skins on this entry</option>';

  document.querySelector('#modal .mbody').innerHTML = `
    <div class="v3wrap">
      <div class="v3stage">
        <canvas id="v3canvas"></canvas>
        <div class="v3hint">drag to turn · wheel to zoom · right-drag to pan</div>
        <div class="v3msg" id="v3msg"></div>
      </div>
      <aside class="v3side">
        <button class="v3roll" onclick="v3Randomize()" title="Pick a variant for every part the way the game does, one soldier at a time">🎲 Randomize variations</button>
        <label class="v3f"><span>Level of detail</span>
          <select onchange="v3SetLod(this.value)">${lods}</select></label>
        <label class="v3f"><span>Skin</span>
          <select onchange="v3SetSkin(this.value)" ${i.skins.length?'':'disabled'}>${skins}</select></label>
        <div class="v3btns">
          <button id="v3spin" class="${v3.spin?'on':''}" onclick="v3Toggle('spin')">Rotate</button>
          <button id="v3wire" class="${v3.wire?'on':''}" onclick="v3Toggle('wire')">Wireframe</button>
          <button onclick="v3Frame()">Recentre</button>
        </div>
        <div class="v3parts" id="v3parts"></div>
        <div class="v3facts" id="v3facts"></div>
      </aside>
    </div>`;
  v3Parts();
  v3Facts();
  const c = document.getElementById('v3canvas');
  if(c && v3.geo) v3Start(c);
}

/* --- parts ----------------------------------------------------------------
   A group's first string is its TYPE: the slot the game fills. Most are the
   modeller's own words for a body part (Body, Head, hair, bracers), but the
   equipment slots are a fixed vocabulary the engine knows — the same list the
   Blender addon offers under "Apply Prefix" (panels/qol_panel.PART_PREFIXES).
   Spelling them out beats showing "shieldpassive0" and leaving you to work out
   which shield that is. */
const V3_SLOTS = {
  weapon0: 'Weapon', weapon1: 'Weapon 2',
  primaryactive0: 'Primary weapon — drawn', primaryactive1: 'Primary weapon 2 — drawn',
  primarypassive0: 'Primary weapon — stowed', primarypassive1: 'Primary weapon 2 — stowed',
  secondaryactive0: 'Secondary weapon — drawn', secondaryactive1: 'Secondary weapon 2 — drawn',
  secondarypassive0: 'Secondary weapon — stowed', secondarypassive1: 'Secondary weapon 2 — stowed',
  shield0: 'Shield', shield1: 'Shield 2',
  shieldactive0: 'Shield — carried', shieldactive1: 'Shield 2 — carried',
  shieldpassive0: 'Shield — slung', shieldpassive1: 'Shield 2 — slung',
  ramrod0: 'Ramrod', 'cannon ball0': 'Cannon ball', 'ballista arrow0': 'Ballista bolt'
};

/* Which slots start hidden. A model ships both stances of the same kit — the
   shield on the arm AND the shield on the back, the drawn sword AND the
   sheathed one — and showing every one of them at once hangs three swords off
   one soldier. The addon's importer makes the same call in hideVariations: it
   hides `shieldpassive` and `secondaryactive` and leaves the primary stance
   showing. Tick them back on to see the rest. */
function v3SlotHidden(key){
  return key.indexOf('shieldpassive') === 0 || key.indexOf('secondaryactive') === 0;
}

/* The model's groups folded into parts: one entry per group TYPE, holding its
   variants. Case-folded, because the same part is spelled `Arms` in one mod's
   mesh and `arms` in another's — and, in nineteen files across both installed
   mods, both ways inside ONE mesh, where they are plainly the same arms. */
function v3PartMap(){
  const parts = new Map();
  if(!v3 || !v3.geo) return parts;
  v3.geo.groups.forEach((g, idx) => {
    const key = (g.name || '(unnamed)').toLowerCase();
    if(!parts.has(key))
      parts.set(key, {key, label: V3_SLOTS[key] || g.name || '(unnamed)', list: []});
    parts.get(key).list.push({g, idx});
  });
  // a part every one of whose variants is flagged optional is one the game
  // only puts on some soldiers — the addon's __opt marker
  parts.forEach(p => { p.optional = p.list.every(v => v.g.optional); });
  return parts;
}

function v3Chosen(part){
  return v3.variant[part.key] !== undefined ? v3.variant[part.key] : part.list[0].idx;
}

/* One row per part: a checkbox to drop it, and a picker when it has variants,
   because showing two heads at once is the wrong answer to "what does this
   model look like". */
function v3Parts(){
  const host = document.getElementById('v3parts');
  if(!host || !v3 || !v3.geo) return;
  const parts = v3PartMap();
  const att = [...parts.values()].filter(p => p.list.some(v => v.g.sheets !== 'main')).length;
  host.innerHTML = `<div class="k">Parts <span class="count">${parts.size} slots`
    + (att ? ` · ${att} reaching the attachment sheet` : '') + `</span></div>`
    + [...parts.values()].map(p => {
    const box = `<input type="checkbox" ${v3.hidden[p.key]?'':'checked'}
        onchange="v3TogglePart('${q1(esc(p.key))}')">`;
    // which sheet the art is ON, said rather than acted on — the UVs do the
    // choosing themselves, and a part can genuinely straddle the two
    const sheet = p.list.some(v => v.g.sheets === 'both') ? 'both sheets'
                : p.list.every(v => v.g.sheets === 'attach') ? 'attach sheet'
                : p.list.some(v => v.g.sheets !== 'main') ? 'both sheets' : '';
    const tags = (p.optional ? '<span class="v3tag">optional</span>' : '')
               + (sheet ? `<span class="v3tag">${sheet}</span>` : '');
    if(p.list.length === 1){
      const {g} = p.list[0];
      return `<label class="v3part">${box}
        <span class="v3nm">${esc(p.label)}</span>${tags}
        <span class="count">${esc(g.texture_group||'')} · ${g.count/3} tris</span></label>`;
    }
    const chosen = v3Chosen(p);
    return `<div class="v3part v3var"><label class="v3nm">${box} ${esc(p.label)} ${tags}</label>
      <select onchange="v3SetVariant('${q1(esc(p.key))}', this.value)">
        ${p.list.map(({g, idx}) => `<option value="${idx}" ${idx===chosen?'selected':''}
          >${esc(g.texture_group || ('variant ' + (idx+1)))} · ${g.count/3} tris</option>`).join('')}
      </select>
      <span class="count">${p.list.length} variants — the game picks one per soldier</span></div>`;
  }).join('');
}

/* One soldier's worth of choices: a variant per part, and a coin toss on the
   parts the mesh flags optional — which is what the game itself does as it
   fills a unit out of one model. */
function v3Randomize(){
  if(!v3 || !v3.geo) return;
  v3PartMap().forEach(p => {
    v3.variant[p.key] = p.list[Math.floor(Math.random() * p.list.length)].idx;
    v3.hidden[p.key] = v3SlotHidden(p.key) || (p.optional && Math.random() < 0.5);
  });
  v3Parts();
}

function v3Facts(){
  const host = document.getElementById('v3facts');
  if(!host || !v3) return;
  const g = v3.geo;
  if(!g) return host.innerHTML = '';
  const size = [0,1,2].map(k => (g.max[k]-g.min[k]).toFixed(2));
  const skin = v3Skin();
  const onAtt = g.groups.filter(x => x.sheets !== 'main').length;
  host.innerHTML = docPoints('This model:', [
    `<b>${g.vertices.toLocaleString()}</b> vertices, <b>${g.triangles.toLocaleString()}</b> triangles`,
    `${g.groups.length} group${g.groups.length===1?'':'s'} over one shared vertex pool`,
    `${size[0]} × ${size[1]} × ${size[2]} in game units`,
    g.bones.length ? `rigged to ${g.bones.length} bones` : 'no skeleton — a static model',
    skin && skin.rel ? `main texture <code>${esc(skin.rel)}</code>${skin.exists?'':' — <b>not in this mod</b>'}`
                     : 'no texture listed on this entry',
    skin && skin.attach
      ? `attachment texture <code>${esc(skin.attach)}</code>${skin.attach_exists?'':' — <b>not in this mod</b>'}`
      : '',
    // the honest answer to "why does this look right in the game and not here":
    // an entry can name an attachment sheet that no group's UVs ever reach
    onAtt ? `${onAtt} group${onAtt===1?'':'s'} reach into the attachment sheet — their UVs pass u 1`
          : 'every group stays in the main sheet, u 0 to 1',
    v3.info.skins.length === 1 && (v3.info.skins[0].factions||[]).length > 1
      ? `every one of its ${v3.info.skins[0].factions.length} factions uses that same pair`
      : `${v3.info.skins.length} distinct skin${v3.info.skins.length===1?'':'s'} across its factions`,
    g.lod_name ? `the file calls itself <code>${esc(g.lod_name)}</code>` : ''
  ]) + (g.notes||[]).map(n => `<div class="w-warn" style="margin-top:6px">${esc(n)}</div>`).join('');
}

/* --- loading -------------------------------------------------------------- */

async function v3Load(){
  if(!v3) return;
  const want = ++v3Gen;
  v3Note('Reading the model…');
  let buf;
  try{
    const r = await fetch(`/api/model/geometry?mod=${enc(v3.mod)}&entry=${enc(v3.entry)}&lod=${v3.lod}`);
    if(!r.ok){
      // the decoder's own sentence is the useful part, so it is shown as-is
      let msg = `the server answered ${r.status}`;
      try{ msg = (await r.json()).error || msg; }catch(e){}
      throw new Error(msg);
    }
    buf = await r.arrayBuffer();
  }catch(e){ if(want===v3Gen) v3Note(''+(e.message||e), true); return; }
  if(want !== v3Gen || !v3) return;

  try{ v3.geo = v3Parse(buf); }
  catch(e){ return v3Note(''+(e.message||e), true); }
  v3.variant = {};
  // the stances a model ships but does not wear at once start off
  v3.hidden = {};
  v3PartMap().forEach(p => { if(v3SlotHidden(p.key)) v3.hidden[p.key] = true; });
  v3Note('');
  v3Render();
  await v3LoadSkin(want);
}

let v3Gen = 0;          // so a slow LOD cannot land after a newer one

/* One image per sheet. They land independently and either may be missing — a
   mod that references vanilla art ships neither — so each one applies as it
   arrives rather than waiting for the pair. */
function v3Fetch(rel, want, into){
  if(!rel){ v3[into] = null; v3Apply(); return; }
  const img = new Image();
  img.onload = () => { if(want===v3Gen && v3){ v3[into] = img; v3Apply(); } };
  img.onerror = () => { if(want===v3Gen && v3){ v3[into] = null; v3Apply(); } };
  img.src = `/model_texture?mod=${enc(v3.mod)}&rel=${enc(rel)}`;
}

async function v3LoadSkin(want){
  if(!v3) return;
  const skin = v3Skin();
  v3.tex = null; v3.texAtt = null;
  v3Fetch(skin && skin.exists ? skin.rel : '', want, 'tex');
  v3Fetch(skin && skin.attach_exists ? skin.attach : '', want, 'texAtt');
}

function v3Note(msg, bad){
  const el = document.getElementById('v3msg');
  if(el) el.innerHTML = msg ? `<span class="${bad?'w-bad':'count'}">${esc(msg)}</span>` : '';
}

/* The payload mesh.py builds: "M2GT", a JSON header, then the arrays raw. */
function v3Parse(buf){
  const view = new DataView(buf);
  const magic = String.fromCharCode(view.getUint8(0), view.getUint8(1),
                                    view.getUint8(2), view.getUint8(3));
  if(magic !== 'M2GT') throw new Error('that response is not model geometry');
  const hlen = view.getUint32(4, true);
  const head = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 8, hlen)));
  let at = 8 + hlen;
  const n = head.vertices;
  head.positions = new Float32Array(buf, at, n*3); at += n*12;
  if(head.has_normals){ head.normals = new Float32Array(buf, at, n*3); at += n*12; }
  if(head.has_uvs){ head.uvs = new Float32Array(buf, at, n*2); at += n*8; }
  const total = head.groups.reduce((s,g) => s + g.count, 0);
  head.indices = new Uint16Array(buf, at, total); at += total*2;
  if(at !== buf.byteLength)
    throw new Error(`the geometry is ${buf.byteLength-at} bytes longer than its header describes`);
  return head;
}

/* --- controls ------------------------------------------------------------- */

function v3SetLod(v){ if(!v3) return; v3.lod = +v; v3Stop(); v3.geo = null; v3Load(); }
function v3SetSkin(v){ if(!v3) return; v3.skin = +v; v3LoadSkin(v3Gen); v3Facts(); }
function v3SetVariant(part, idx){ if(!v3) return; v3.variant[part] = +idx; }
function v3TogglePart(key){ if(!v3) return; v3.hidden[key] = !v3.hidden[key]; }
function v3Toggle(what){
  if(!v3) return;
  v3[what] = !v3[what];
  const b = document.getElementById('v3' + what);
  if(b) b.classList.toggle('on', v3[what]);
}
function v3Frame(){
  if(!v3 || !v3.geo) return;
  const g = v3.geo;
  v3.centre = [0,1,2].map(k => (g.min[k]+g.max[k])/2);
  // to fit a sphere of radius r at this field of view the camera wants
  // r / sin(fov/2) — about 1.15 spans — and a little margin on top of it
  const span = Math.max(...[0,1,2].map(k => g.max[k]-g.min[k])) || 1;
  v3.dist = span * 1.35;
  v3.yaw = 0.6; v3.pitch = 0.25;
}

/* Which group indices to draw: one variant per part, minus the parts that are
   switched off. */
function v3Visible(){
  const out = [];
  v3PartMap().forEach(p => { if(!v3.hidden[p.key]) out.push(v3Chosen(p)); });
  return out;
}

/* --- WebGL ---------------------------------------------------------------- */

function v3Start(canvas){
  const gl = canvas.getContext('webgl', {antialias:true, alpha:false})
          || canvas.getContext('experimental-webgl');
  if(!gl) return v3Note('this browser has no WebGL, so the model cannot be drawn', true);
  v3.gl = gl;
  const prog = v3Program(gl, V3_VERT, V3_FRAG);
  if(!prog) return v3Note('the viewer’s shaders would not compile here', true);
  v3.prog = prog;
  v3.loc = {
    aPos: gl.getAttribLocation(prog,'aPos'),
    aNormal: gl.getAttribLocation(prog,'aNormal'),
    aUv: gl.getAttribLocation(prog,'aUv'),
    uProj: gl.getUniformLocation(prog,'uProj'),
    uView: gl.getUniformLocation(prog,'uView'),
    uModel: gl.getUniformLocation(prog,'uModel'),
    uTex: gl.getUniformLocation(prog,'uTex'),
    uHasTex: gl.getUniformLocation(prog,'uHasTex'),
    uKey: gl.getUniformLocation(prog,'uKey'),
    uEye: gl.getUniformLocation(prog,'uEye'),
    uFlat: gl.getUniformLocation(prog,'uFlat')
  };
  // the backdrop: its own tiny program over one full-screen quad
  v3.bg = v3Program(gl, V3_BG_VERT, V3_BG_FRAG);
  if(v3.bg) v3.bgLoc = {
    aQuad: gl.getAttribLocation(v3.bg,'aQuad'),
    uRight: gl.getUniformLocation(v3.bg,'uRight'),
    uUp: gl.getUniformLocation(v3.bg,'uUp'),
    uFwd: gl.getUniformLocation(v3.bg,'uFwd'),
    uScale: gl.getUniformLocation(v3.bg,'uScale')
  };
  v3.bQuad = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, v3.bQuad);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1, 3,-1, -1,3]), gl.STATIC_DRAW);
  v3Buffers(gl);
  v3Apply();
  v3Frame();
  v3Wire(canvas);
  gl.enable(gl.DEPTH_TEST);
  const tick = () => {
    if(!v3 || !v3.gl) return;
    if(v3.spin && !v3.drag) v3.yaw += 0.006;
    v3Draw();
    v3.raf = requestAnimationFrame(tick);
  };
  v3.raf = requestAnimationFrame(tick);
}

function v3Program(gl, vs, fs){
  const build = (type, src) => {
    const s = gl.createShader(type);
    gl.shaderSource(s, src); gl.compileShader(s);
    if(!gl.getShaderParameter(s, gl.COMPILE_STATUS)){
      console.error('viewer3d shader:', gl.getShaderInfoLog(s)); return null;
    }
    return s;
  };
  const v = build(gl.VERTEX_SHADER, vs), f = build(gl.FRAGMENT_SHADER, fs);
  if(!v || !f) return null;
  const p = gl.createProgram();
  gl.attachShader(p, v); gl.attachShader(p, f); gl.linkProgram(p);
  gl.deleteShader(v); gl.deleteShader(f);
  return gl.getProgramParameter(p, gl.LINK_STATUS) ? p : null;
}

function v3Buffers(gl){
  const g = v3.geo;
  const buf = (data, target) => {
    const b = gl.createBuffer();
    gl.bindBuffer(target, b); gl.bufferData(target, data, gl.STATIC_DRAW);
    return b;
  };
  v3.bPos = buf(g.positions, gl.ARRAY_BUFFER);
  // a model with no normal stream still has to shade: face the camera flat
  v3.bNormal = buf(g.normals || new Float32Array(g.vertices*3).fill(0.577), gl.ARRAY_BUFFER);
  v3.bUv = buf(g.uvs || new Float32Array(g.vertices*2), gl.ARRAY_BUFFER);
  v3.bIdx = buf(g.indices, gl.ELEMENT_ARRAY_BUFFER);
  // one line-index buffer for the wireframe, built once from the triangles
  const lines = new Uint16Array(g.indices.length * 2);
  for(let t = 0, o = 0; t < g.indices.length; t += 3){
    const [a,b2,c] = [g.indices[t], g.indices[t+1], g.indices[t+2]];
    lines[o++]=a; lines[o++]=b2; lines[o++]=b2; lines[o++]=c; lines[o++]=c; lines[o++]=a;
  }
  v3.bLines = buf(lines, gl.ELEMENT_ARRAY_BUFFER);
}

/* The two sheets glued into the one image the UVs are addressing: main in the
   left half, attachment in the right, each exactly one unit of u wide however
   big the source files are. An entry with no attachment sheet of its own — or
   one the mod does not ship — gets the main sheet in both halves, which is
   what the addon's exporter does with an empty attach slot (`attach_name =
   plan['attach'][1] or main_name`) and keeps the tiling continuous.

   Gluing beats binding two textures and choosing per part, which is what this
   did before and what got it wrong: the choice is not the viewer's to make.
   A group whose UVs run 0.41 to 1.38 is one piece of art crossing from one
   sheet onto the other, and any per-part rule has to put the whole of it on
   one sheet or the other and be wrong about half of it. */
function v3Atlas(main, att){
  const w = main.width, h = main.height;
  const c = document.createElement('canvas');
  c.width = w * 2; c.height = h;
  const x = c.getContext('2d');
  x.drawImage(main, 0, 0, w, h);
  // scaled into its half, so u 1..2 is the whole attachment sheet whatever
  // size it came in at
  x.drawImage(att || main, w, 0, w, h);
  return c;
}

function v3Apply(){
  if(!v3 || !v3.gl) return;
  const gl = v3.gl;
  if(v3.texture){ gl.deleteTexture(v3.texture); v3.texture = null; }
  if(!v3.tex) return;
  const atlas = v3Atlas(v3.tex, v3.texAtt);
  const t = gl.createTexture();
  gl.activeTexture(gl.TEXTURE0);
  gl.bindTexture(gl.TEXTURE_2D, t);
  // NOT flipped. WebGL's own habit is to flip, because OpenGL puts v=0 at the
  // bottom — M2TW is a Direct3D game and puts it at the top, so flipping sends
  // every UV to the mirrored half of the sheet. Checked against the art rather
  // than assumed: on a Lossarnach noble the head groups' UVs (v 0.00..0.10)
  // land exactly on the faces painted along the TOP edge of its texture, and
  // the same for every body and skirt group on that sheet.
  gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, atlas);
  // REPEAT is the whole point — the pair tiles, and UVs really do run past the
  // two tiles and below zero. A skin is served square and no bigger than 1024,
  // so the atlas is 2048 wide at most and a power of two in both axes, which
  // is what WebGL 1 demands before it will repeat anything at all.
  const pot = n => n > 0 && (n & (n-1)) === 0;
  if(pot(atlas.width) && pot(atlas.height)){
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.REPEAT);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.REPEAT);
    gl.generateMipmap(gl.TEXTURE_2D);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
  }else{
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    v3Note('this skin is not a power of two, so the tiled parts of it cannot '
         + 'repeat here', true);
  }
  v3.texture = t;
}

function v3Draw(){
  const gl = v3.gl, c = gl.canvas, g = v3.geo;
  const w = c.clientWidth || 640, h = c.clientHeight || 420;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  if(c.width !== Math.round(w*dpr) || c.height !== Math.round(h*dpr)){
    c.width = Math.round(w*dpr); c.height = Math.round(h*dpr);
  }
  gl.viewport(0, 0, c.width, c.height);
  gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);

  // M2TW models stand up the Y axis. Measured, not assumed: across six DaC
  // soldiers the Head group's centroid sits 1.4 above the Legs group's in Y
  // and level with it in X and Z. Orbit the wrong axis and every man in the
  // game lies on his side.
  const cp = Math.cos(v3.pitch), sp = Math.sin(v3.pitch);
  const eye = [v3.centre[0] + v3.dist*cp*Math.sin(v3.yaw),
               v3.centre[1] + v3.dist*sp,
               v3.centre[2] + v3.dist*cp*Math.cos(v3.yaw)];
  const fovY = 0.9, aspect = (c.width/c.height)||1;
  const back = v3Norm([eye[0]-v3.centre[0], eye[1]-v3.centre[1], eye[2]-v3.centre[2]]);
  const right = v3Norm(v3Cross([0,1,0], back));
  const up = v3Cross(back, right);

  // the environment behind the model, before anything else and behind
  // everything else: depth writes off, so the model still sorts normally
  if(v3.bg){
    gl.useProgram(v3.bg);
    gl.bindBuffer(gl.ARRAY_BUFFER, v3.bQuad);
    gl.enableVertexAttribArray(v3.bgLoc.aQuad);
    gl.vertexAttribPointer(v3.bgLoc.aQuad, 2, gl.FLOAT, false, 0, 0);
    gl.uniform3fv(v3.bgLoc.uRight, right);
    gl.uniform3fv(v3.bgLoc.uUp, up);
    gl.uniform3fv(v3.bgLoc.uFwd, [-back[0], -back[1], -back[2]]);
    const t = Math.tan(fovY/2);
    gl.uniform2f(v3.bgLoc.uScale, t*aspect, t);
    gl.depthMask(false);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    gl.depthMask(true);
    gl.disableVertexAttribArray(v3.bgLoc.aQuad);
  }

  gl.useProgram(v3.prog);
  gl.uniformMatrix4fv(v3.loc.uProj, false,
    v3Perspective(fovY, aspect, Math.max(0.01, v3.dist/100), v3.dist*10));
  gl.uniformMatrix4fv(v3.loc.uView, false, v3LookAt(eye, v3.centre, [0,1,0]));
  // X negated: M2TW models are LEFT-handed (right +X, up +Y, forward +Z, the
  // Direct3D convention) and this camera is right-handed. Handed over as they
  // are, every soldier came out mirrored — shield arm and sword arm swapped.
  // Measured from the models themselves: shield0 sits at -X and primaryactive0
  // at +X, which is shield in the left hand and weapon in the right.
  gl.uniformMatrix4fv(v3.loc.uModel, false,
    [-1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]);
  gl.uniform3fv(v3.loc.uKey, v3Norm([0.45, 0.85, 0.7]));   // above, front, left
  gl.uniform3fv(v3.loc.uEye, back);

  const bind = (buf, loc, size) => {
    if(loc < 0) return;
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, size, gl.FLOAT, false, 0, 0);
  };
  bind(v3.bPos, v3.loc.aPos, 3);
  bind(v3.bNormal, v3.loc.aNormal, 3);
  bind(v3.bUv, v3.loc.aUv, 2);

  // One texture for the whole model — the glued pair — so every group is the
  // same bind and the UVs alone decide which sheet a triangle lands on.
  const textured = !!(v3.texture && g.has_uvs);
  if(textured){
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, v3.texture);
    gl.uniform1i(v3.loc.uTex, 0);
  }
  gl.uniform1f(v3.loc.uHasTex, textured ? 1 : 0);

  const visible = v3Visible();
  gl.uniform1f(v3.loc.uFlat, 0);
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, v3.bIdx);
  for(const idx of visible){
    const grp = g.groups[idx];
    gl.drawElements(gl.TRIANGLES, grp.count, gl.UNSIGNED_SHORT, grp.start*2);
  }
  if(v3.wire){
    gl.uniform1f(v3.loc.uFlat, 1);
    gl.uniform1f(v3.loc.uHasTex, 0);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, v3.bLines);
    for(const idx of visible){
      const grp = g.groups[idx];
      gl.drawElements(gl.LINES, grp.count*2, gl.UNSIGNED_SHORT, grp.start*4);
    }
  }
}

/* --- orbit ---------------------------------------------------------------- */

function v3Wire(canvas){
  let last = null, pan = false;
  canvas.addEventListener('contextmenu', e => e.preventDefault());
  canvas.addEventListener('pointerdown', e => {
    last = [e.clientX, e.clientY]; pan = (e.button === 2 || e.shiftKey);
    if(v3) v3.drag = true;
    canvas.setPointerCapture(e.pointerId);
  });
  canvas.addEventListener('pointerup', e => {
    last = null; if(v3) v3.drag = false;
    try{ canvas.releasePointerCapture(e.pointerId); }catch(err){}
  });
  canvas.addEventListener('pointermove', e => {
    if(!last || !v3) return;
    const dx = e.clientX - last[0], dy = e.clientY - last[1];
    last = [e.clientX, e.clientY];
    if(pan){
      // pan across the screen plane, scaled so the model keeps up with the cursor
      const k = v3.dist / 500;
      v3.centre[0] -= dx * k * Math.cos(v3.yaw);
      v3.centre[2] += dx * k * Math.sin(v3.yaw);
      v3.centre[1] += dy * k;
    }else{
      v3.yaw -= dx * 0.01;
      v3.pitch = Math.max(-1.5, Math.min(1.5, v3.pitch + dy * 0.01));
    }
  });
  canvas.addEventListener('wheel', e => {
    if(!v3) return;
    e.preventDefault();
    v3.dist = Math.max(0.05, v3.dist * (e.deltaY > 0 ? 1.12 : 0.89));
  }, {passive:false});
}
