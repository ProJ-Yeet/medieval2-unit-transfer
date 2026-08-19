/* guided.js — the guided field editor: an EDU line's positional slots, named

   Part of the Medieval 2 GUI Toolkit UI. These files are plain
   <script> tags sharing ONE global scope, loaded in the order set in
   index.html — there is no build step and no module system. Two rules
   follow from that: a top-level name must be unique across all of
   them, and a file's top-level side effects may not depend on a file
   loaded after it. */
/* ======================================================================
   GUIDED FIELD EDITOR
   ----------------------------------------------------------------------
   An EDU line is a comma-separated tuple whose meaning is entirely positional:
   `stat_pri 14, 4, no, 0, 0, melee, melee_blade, piercing, spear, 25, 1` is
   eleven different settings and nothing on the line says which is which. The raw
   view (what this tool showed before, and what every other EDU editor shows) asks
   you to know that by heart.

   The guided view gives each slot its own labelled box, a drop-down wherever the
   engine only accepts a fixed set of words, a one-line explanation, and a warning
   when a value would not work — while writing back the very same line, so a unit
   edited here is byte-identical to one edited by hand. Anything it does not
   recognise (a mod's own field, a repeated line, a value count the engine does
   not use) falls back to the raw box for that one field rather than guessing.

   The same code drives both places EDU fields are edited — the transfer composer
   and the unit editor — through a small host object; see gfHostComposer /
   gfHostEditor for what each supplies.
   ====================================================================== */

// Which view the two field editors open in. Guided is the default; the setting is
// remembered like the rest of them.
const gfMode=()=>((state.settings||{}).field_editor_mode==='raw'?'raw':'guided');
function gfSetMode(m){
  state.settings.field_editor_mode=m;
  api.post('/api/settings',{field_editor_mode:m});
  if(state.mode==='edit'&&state.ed)edRenderTab(); else if(state.editing)renderComposer();
}
function gfToggleHtml(){
  const g=gfMode()==='guided';
  return `<div class="gfmode" title="Guided: every value in its own labelled box, with drop-downs and checks.
Raw lines: one text box per EDU line, exactly as the file stores it.">
    <button class="${g?'on':''}" onclick="gfSetMode('guided')">🧭 Guided</button>
    <button class="${g?'':'on'}" onclick="gfSetMode('raw')">⌗ Raw lines</button></div>`;
}

/* ---- vocabularies -------------------------------------------------------
   Fetched per mod (/api/edu_vocab): the engine's fixed sets plus everything the
   mod itself defines or already uses, so a drop-down never invites you to throw
   away a mod's own attribute or accent. The page keeps a minimal copy of the
   fixed sets so it is usable before the answer arrives. */
const GF_STATIC={
  category:['infantry','cavalry','siege','ship','handler','non_combatant'],
  'class':['light','heavy','missile','spearmen','skirmish'],
  voice_type:['Heavy','Light','General'],
  formation_main:['square','horde'],
  formation_special:['','schiltrom','shield_wall','phalanx','testudo','wedge'],
  discipline:['low','normal','disciplined','impetuous'],
  training:['untrained','trained','highly_trained'],
  weapon_type:['no','melee','thrown','missile','siege_missile'],
  tech_type:['melee_simple','melee_blade','missile_mechanical','missile_gunpowder',
             'artillery_mechanical','artillery_gunpowder'],
  damage_type:['piercing','blunt','slashing','fire'],
  weapon_sound:['none','spear','sword','axe','mace','knife'],
  armour_sound:['flesh','leather','metal'],
  mount_class:['horse','camel','elephant'],
  weapon_attr:['ap','bp','spear','light_spear','long_pike','short_pike','spear_bonus_2',
    'spear_bonus_4','spear_bonus_6','spear_bonus_8','spear_bonus_10','spear_bonus_12',
    'thrown','launching','area','prec'],
  unit_attr:['sea_faring','can_swim','can_withdraw','can_run_amok','can_formed_charge',
    'cannot_skirmish','start_not_skirmishing','fire_by_rank','hardy','very_hardy',
    'hide_forest','hide_improved_forest','hide_long_grass','hide_anywhere','frighten_foot',
    'frighten_mounted','power_charge','knight','general_unit','mercenary_unit',
    'free_upkeep_unit','is_peasant','no_custom','gunpowder_unit','stakes','druid',
    'cantabrian_circle','command','legionary_name'],
  banner_faction:['main_infantry','main_cavalry','main_missile','main_spear'],
  banner_holy:['crusade','jihad'],
  projectile:[],mount:[],engine:[],mounted_engine:[],ship:[],animal:[],model:[],
  accent:[],banner_unit:[],fire_effect:[],defined:{}};
state.vocab={};
function gfVocabFor(mod){
  if(!mod)return GF_STATIC;
  if(state.vocab[mod])return state.vocab[mod];
  if(state.vocab['?'+mod])return GF_STATIC;      // already in flight
  state.vocab['?'+mod]=true;
  api.get('/api/edu_vocab?mod='+enc(mod)).then(v=>{
    state.vocab[mod]=Object.assign({},GF_STATIC,v||{});
    // the boxes that were drawn from the static fallback now have real lists
    if(state.mode==='edit'&&state.ed)edRenderTab(); else if(state.editing)renderAllFields(state.editing);
  }).catch(()=>{});
  return GF_STATIC;
}
const gfV=(host,name)=>((host.vocab||GF_STATIC)[name])||[];
// Names a mod file actually defines, for "this points at nothing" warnings. An
// empty list means the file is missing or unparsed — then we say nothing.
const gfDefined=(host,name)=>((host.vocab||{}).defined||{})[name]||[];
const gfHas=(list,v)=>{const t=(v||'').trim().toLowerCase();
  return !t||list.some(x=>(''+x).toLowerCase()===t);};

/* ---- the field table ----------------------------------------------------
   `parts` is the line, slot by slot. `arity` lists the value counts the engine
   accepts (absent = exactly one per part); a line with any other count is shown
   raw, because guessing which slot is missing is how an editor eats a unit.
   `pad` normalises an accepted short form up to the full part list, `join`
   writes it back in whichever form is still correct. */
const gfP=(pl,type,o)=>Object.assign({pl,type},o||{});
// one DOM id per list box, derived the same way wherever it is needed
const gfAddId=label=>'gfadd-'+label.replace(/\W/g,'_');
/* A number box carries its own limits: `min`/`max` are what the ▴▾ steppers and
   the ↑/↓ keys clamp to, `step` is how far one press moves it and `dec` how many
   decimals to keep. Only ONE of these limits is a real engine cap (attack, 63);
   the rest sit above the highest value found across vanilla, Third Age and DaC,
   so a stepper cannot run away while nothing a real mod does is out of reach.
   Typing is never clamped — an existing value the engine dislikes is reported by
   the checks, not silently rewritten under the cursor. */
const gfN=(pl,o)=>gfP(pl,'num',o);                       // number box
const gfS=(pl,v,o)=>gfP(pl,'sel',Object.assign({v},o));  // closed drop-down
const gfC=(pl,v,o)=>gfP(pl,'combo',Object.assign({v},o));// drop-down you can type into
const gfT=(pl,o)=>gfP(pl,'text',o);

// stat_pri / stat_sec / stat_ter share one shape: 11 values, or 12 when the
// optional "effect played when the weapon fires" (musket_shot_set) is present
// between the hit sound and the delay.
const gfWeaponParts=()=>[
  gfN('Attack',{min:0,max:63,
    help:'The weapon’s attack factor: how much damage a connecting blow does. <b>The engine caps this at 63</b>. '
      +'A higher number is stored but behaves as 63, so it is the one number here with a hard ceiling.'}),
  gfN('Charge bonus',{min:0,max:63,
    help:'Extra attack added while the charge is running. It decays as the charge is absorbed, so it rewards '
      +'hitting a unit that is not braced rather than a long melee.'}),
  gfC('Projectile','projectile',{w:3,
    help:'The ammunition this weapon fires: an entry in <code>descr_projectile.txt</code>, which is where its '
      +'speed, arc, damage model and impact effect live. <code>no</code> means a melee weapon.'}),
  gfN('Range',{min:0,max:2000,
    help:'How far the missile can be fired, in metres. 0 for a melee weapon. Vanilla bows sit near 120–180 and '
      +'artillery near 250–450.'}),
  gfN('Ammo',{min:0,max:999,
    help:'Shots carried <b>per man</b>, not per unit. 0 for a melee weapon.'}),
  gfS('Weapon type','weapon_type',{w:2,
    help:'How the weapon is used: <code>melee</code>, <code>thrown</code>, <code>missile</code> or '
      +'<code>siege_missile</code>. <b>A missile weapon has to be the primary one</b>: the engine will not fire a '
      +'secondary bow. The exception is artillery, where the crew’s own weapon is primary.'}),
  gfS('Tech type','tech_type',{w:3,
    help:'Which weapon-upgrade line a smith improves for this unit: <code>melee_simple</code>, '
      +'<code>melee_blade</code>, <code>missile_mechanical</code>, <code>missile_gunpowder</code>, '
      +'<code>artillery_mechanical</code> or <code>artillery_gunpowder</code>.'}),
  gfS('Damage type','damage_type',{w:2,
    help:'<code>piercing</code>, <code>blunt</code> or <code>slashing</code>. The EDU’s own header notes this may '
      +'no longer be read by the engine; it is still set on every unit.'}),
  gfS('Hit sound','weapon_sound',{w:2,
    help:'The sound played when the weapon connects: <code>none</code>, <code>knife</code>, <code>mace</code>, '
      +'<code>axe</code>, <code>sword</code> or <code>spear</code>. Cosmetic only.'}),
  gfC('Fire effect','fire_effect',{w:3,optional:1,
    help:'Optional. The effect played when the weapon <i>fires</i>: <code>musket_shot_set</code> for gunpowder '
      +'units, and essentially nothing else. Setting it is what turns this line from 11 values into 12; clearing '
      +'it turns it back.'}),
  gfN('Delay',{min:0,max:9999,
    help:'Minimum delay between attacks, in tenths of a second, on top of whatever the animation takes. Lower is '
      +'faster. 25 is the value nearly every unit in the game uses.'}),
  gfN('Skel. factor',{min:0,max:100,step:0.1,dec:1,
    help:'Skeleton compensation factor in melee. The EDU header says it should be 1; a few mods use it to tune '
      +'how a mismatched animation lands.'}),
];
// A doc is a short lead line and then points. Prose that runs for six lines is
// what this editor exists to replace, so it does not get to live in the help.
// The shape is shared with every other note in the UI - see docPoints() in core.js.
const gfDoc=docPoints;

const gfWeaponSpec=(title,doc)=>({t:title,doc,parts:gfWeaponParts(),arity:[11,12],
  syn:'attack, charge, projectile, range, ammo, weapon type, tech type, damage type, hit sound, [fire effect,] delay, skeleton factor',
  // 11 values -> no fire effect: open slot 9 so every box keeps its meaning
  pad:p=>p.length>=12?p:p.slice(0,9).concat([''],p.slice(9)),
  join:p=>{const fx=(p[9]||'').trim();
    return p.slice(0,9).concat(fx?[fx]:[],p.slice(10)).map(x=>(''+(x==null?'':x)).trim()).join(', ');}});
const gfExSpec=which=>({t:which+' weapon bonuses',opt:1,
  syn:'attack bonus vs mounted, defence bonus vs mounted, armour penetration',
  doc:gfDoc('Optional. Three factors that apply only against mounted enemies.',[
    'The engine does read the line.',
    'Most mods leave it out and use <code>mount_effect</code> plus the '
      +'<code>spear_bonus_N</code> attributes instead.',
    'Vanilla ships it commented out on every unit.']),
  parts:[gfN('Attack vs mounted',{min:-100,max:100,help:'Added to the attack factor when the target is mounted.'}),
    gfN('Defence vs mounted',{min:-100,max:100,help:'Added to defence when the attacker is mounted.'}),
    gfN('Armour penetration',{min:-100,max:100,help:'How much of a mounted target’s armour this weapon ignores.'})]});
const gfAttrSpec=which=>({t:which+' weapon attributes',w:'wattr',
  doc:gfDoc('What the weapon does beyond its numbers.',[
    '<code>ap</code>: halves the target’s armour.',
    '<code>bp</code>: a missile passes through a man and hits the one behind.',
    '<code>spear</code> / <code>light_spear</code>: brace against a cavalry charge '
      +'from the front. <code>spear</code> also carries a penalty against infantry.',
    '<code>long_pike</code>: required by phalanx units.',
    '<code>spear_bonus_N</code>: a flat attack bonus against cavalry. Only one applies.',
    '<code>thrown</code> / <code>launching</code> / <code>area</code>: change how the hit resolves.',
    '<code>prec</code>: a missile unit throws one volley, then charges.',
    'None of them is written <code>no</code>, which is how "none" is spelled here.'])});

const GF_FIELDS={
  'type':{t:'Internal name',syn:'<name>',
    doc:gfDoc('The name every <b>other</b> file uses for this unit.',[
      'Read by <code>descr_strat.txt</code>, <code>export_descr_buildings.txt</code>, '
        +'<code>descr_mercenaries.txt</code>, <code>descr_rebel_factions.txt</code> and campaign scripts.',
      'Spaces are allowed.',
      'Rule of thumb: any file that names units without underscores wants this name.']),
    parts:[gfT('type',{grow:1,help:'Renaming it here does not update the other files that recruit the unit.'})]},
  'dictionary':{t:'Dictionary key',syn:'<key>  ; <comment>',
    doc:gfDoc('The unit’s <i>other</i> name.',[
      'The key its on-screen text is looked up under in <code>data/text/export_units.txt</code>.',
      'Also the filename of its unit card and info card (<code>#&lt;key&gt;.tga</code>).',
      'Usually the type with underscores instead of spaces.',
      'Anything after a <code>;</code> is a comment. Vanilla uses it to spell the real name out.']),
    parts:[gfT('dictionary',{grow:1})]},
  'category':{t:'Category',syn:'infantry | cavalry | siege | ship | handler',
    doc:gfDoc('The broad troop type. Sets defaults and where the unit stands in an army’s formation.',[
      'Wagons like the Great Cross count as <code>siege</code>.',
      '<code>handler</code> is for a unit whose animals do the fighting.',
      '<code>non_combatant</code> is in the file header but is a Rome leftover.']),
    parts:[gfS('category','category',{w:2})]},
  'class':{t:'Class',syn:'light | heavy | missile | spearmen',
    doc:gfDoc('What the unit is within its category.',[
      '<code>light</code> / <code>heavy</code>: infantry, cavalry and ships.',
      '<code>missile</code>: infantry, cavalry and siege.',
      '<code>spearmen</code>: infantry only.',
      'A wagon is the odd one out: <code>siege</code> category, <code>light</code> class.']),
    parts:[gfS('class','class',{w:2})]},
  'voice_type':{t:'Voice type',syn:'Heavy | Light | General',
    doc:gfDoc('Which set of battlefield barks the unit uses.',[
      '<code>Light</code>: ships and weak-sounding troops.',
      '<code>Heavy</code>: regulars.',
      '<code>General</code>: a general’s bodyguard.',
      'With <code>accent</code>, this is what points the game at a block in '
        +'<code>export_descr_sounds_units_voice.txt</code>.']),
    parts:[gfS('voice_type','voice_type',{w:2})]},
  'accent':{t:'Accent',opt:1,syn:'<accent>',
    doc:gfDoc('Optional. Forces one accent on the unit whoever owns it.',[
      'Without the line it speaks with the owning faction’s accent, so English-owned '
        +'Swiss Pikemen sound English.',
      'Accents are declared in <code>descr_sounds_accents.txt</code>.',
      'Vanilla has English, Scottish, French, German, Mediterranean, East_European, '
        +'Arabic and Mongolian. Mods add their own.']),
    parts:[gfC('accent','accent',{w:3})]},
  'banner faction':{t:'Faction banner',syn:'<banner>',
    doc:gfDoc('The unit’s big battlefield banner, from <code>descr_banners_new.xml</code>.',[
      'It also decides the mini-banners for experience and weapon/armour upgrades.',
      'The list is the <code>&lt;FactionBanners&gt;</code> section of that file, so it is this '
        +'mod’s own. Vanilla declares four, all named <code>main_…</code>.',
      'Ships have no line: they never appear on the battlefield.']),
    parts:[gfC('banner','banner_faction',{w:3})]},
  'banner holy':{t:'Holy-war banner',opt:1,syn:'<banner>',
    doc:gfDoc('Optional. The second banner the unit carries while on a crusade.',[
      'The list is the <code>&lt;HolyBanners&gt;</code> section of '
        +'<code>descr_banners_new.xml</code>. Vanilla declares <code>crusade</code> and '
        +'<code>crusade_cavalry</code>, and a mod may declare its own.',
      'Leave the line out and the unit carries none.']),
    parts:[gfC('banner','banner_holy',{w:3})]},
  'banner unit':{t:'Unit banner',opt:1,syn:'<banner>',
    doc:gfDoc('Optional and rare. A per-unit banner override.',[
      'The list is the <code>&lt;UnitSpecificBanners&gt;</code> section of '
        +'<code>descr_banners_new.xml</code>. The crusading orders live here.',
      'Leave the line out and the unit flies its faction banner.']),
    parts:[gfC('banner','banner_unit',{w:3})]},

  'soldier':{t:'Soldiers',syn:'model, men, extras, mass[, radius[, height]]',
    doc:gfDoc('Who the unit is made of.',[
      'The model name is an entry in <code>battle_models.modeldb</code>.',
      'That entry decides how the man looks <b>and</b> how he moves.',
      'Swapping it swaps the animation set with it.']),
    parts:[gfC('Model','model',{w:3,
        help:'A <code>battle_models.modeldb</code> entry. It carries the meshes, the per-faction textures and the '
          +'animation skeleton, so changing it changes how the man looks <i>and</i> how he fights.'}),
      gfN('Men',{min:1,max:500,
        help:'Men in the unit at the largest unit-size setting; the smaller settings scale down from it. The guide '
          +'gives 4–100 as the range, though shipped mods field 2-man scout and monster units quite happily.'}),
      gfN('Extras',{min:0,max:99,
        help:'Attached siege engines or animals: 2 on a two-trebuchet unit, and 0 for ordinary troops. What the '
          +'extras <i>are</i> comes from the <code>engine</code> / <code>animal</code> / <code>mounted_engine</code> line.'}),
      gfN('Mass',{min:0,max:200,step:0.1,dec:1,
        help:'Collision mass of one man; 1 is normal. A heavier man shoves people aside on the charge. Ignored for '
          +'cavalry, because a mounted unit takes its mass from the mount in <code>descr_mount.txt</code>.'}),
      gfN('Radius',{optional:1,min:0,max:10,step:0.05,dec:2,
        help:'Optional. Collision radius of one man in metres. Leave it empty unless the mod already sets it. '
          +'Adding it lengthens the line, and the height slot is only read when a radius is present.'}),
      gfN('Height',{optional:1,min:0,max:10,step:0.1,dec:1,
        help:'Optional. Collision height of one man in metres. Only read when a radius is given.'})],
    arity:[4,5,6],
    join:p=>{const q=p.map(x=>(''+(x==null?'':x)).trim());
      while(q.length>4&&!q[q.length-1])q.pop(); return q.join(', ');}},
  'officer':{t:'Officer',opt:1,syn:'<model>',
    doc:gfDoc('Optional. An extra man riding along with the unit.',[
      'Taken from <code>battle_models.modeldb</code>, like the soldier model.',
      'Decoration only: losing him costs the unit nothing.',
      'Up to three <code>officer</code> lines, directly after <code>soldier</code>.']),
    parts:[gfC('Model','model',{w:3})]},
  'mount':{t:'Mount',opt:1,syn:'<mount>',
    doc:gfDoc('What the unit rides, named in <code>descr_mount.txt</code>.',[
      'That block holds the animal’s mass, its model and its own stats.',
      'This line only points at it.',
      'A ridden horse or camel has no separate hit points. An elephant does.']),
    parts:[gfC('Mount','mount',{w:3})]},
  'ship':{t:'Ship',opt:1,syn:'<ship type>',
    doc:gfDoc('Ships only, from <code>descr_ship.txt</code>.',[
      '<code>heavy warship</code> is the type that can cross deep ocean tiles.',
      'The line goes directly after <code>soldier</code>.']),
    parts:[gfC('Ship','ship',{w:3})]},
  'engine':{t:'Siege engine',opt:1,syn:'<engine>',
    doc:gfDoc('The siege engine this crew operates, from <code>descr_engines.txt</code>.',[
      'Catapult, trebuchet, bombard, ram, ladder, siege tower and so on.',
      'How many the unit fields comes from the <i>extras</i> slot of the '
        +'<code>soldier</code> line.']),
    parts:[gfC('Engine','engine',{w:3})]},
  'mounted_engine':{t:'Mounted engine',opt:1,syn:'<engine>',
    doc:gfDoc('A gun carried by the unit’s mount, from <code>descr_mounted_engines.txt</code>.',[
      'Elephant serpentine, elephant rocket launcher, camel gun.',
      'Unlike a ground engine it has no model of its own: it rides the mount’s.']),
    parts:[gfC('Engine','mounted_engine',{w:3})]},
  'animal':{t:'Animals',opt:1,syn:'<animal>',
    doc:gfDoc('Non-ridden animals that fight while the men handle them, from '
      +'<code>descr_animals.txt</code>.',[
      'War dogs, pigs.',
      'Needs <code>category handler</code> or the animals never appear.',
      'How many comes from the <i>extras</i> slot of the <code>soldier</code> line.']),
    parts:[gfC('Animal','animal',{w:3})]},
  'mount_effect':{t:'Bonus vs mounts',opt:1,w:'meffect',
    syn:'<mount> ±N, <mount> ±N, <mount> ±N',
    doc:gfDoc('Attack modifiers that apply only against enemies riding a particular mount.',[
      'Each entry is a name and a signed number.',
      'The name is a mount <i>class</i> (<code>horse</code>, <code>camel</code>, '
        +'<code>elephant</code>) or one specific mount from <code>descr_mount.txt</code>.',
      '<b>The engine reads at most three.</b>',
      'This is where "camels frighten horses" and "everything hates elephants" live.'])},
  'attributes':{t:'Attributes',w:'attrs',syn:'attr, attr, attr, …',
    doc:gfDoc('Everything about the unit that is not a number. Two different kinds share the line.',[
      '<b>Abilities</b>: where it can hide, whether it can board ships or swim, whether '
        +'it can withdraw, its stamina, whether it is a mercenary, whether it can lay '
        +'stakes or form a Cantabrian circle.',
      'A unit may only carry <b>one</b> special ability.',
      '<b>AI labels</b> (<code>pike</code>, <code>crossbow</code>, <code>artillery</code>, '
        +'<code>gunmen</code>) change nothing about the unit.',
      'They only tell the campaign AI what kind of unit it is looking at.'])},
  'move_speed_mod':{t:'Movement modifier',opt:1,syn:'<multiplier>',
    doc:gfDoc('Kingdoms only. Multiplies the speed the unit’s animation skeleton gives it.',[
      'Above 1 is faster, below is slower.',
      'Without the line the skeleton alone decides.']),
    parts:[gfN('×',{min:0,max:5,step:0.01,dec:2,help:'1 leaves the skeleton’s own speed alone.'})]},

  'formation':{t:'Formation',syn:'close ↔, close ↕, loose ↔, loose ↕, ranks, formation[, second formation]',
    doc:gfDoc('How tightly the men stand, and which formations the unit may adopt.',[
      'The first four numbers are spacing in metres.',
      'Side-to-side then front-to-back, in close order then in loose order.']),
    parts:[gfN('Close ↔',{min:0,max:200,step:0.1,dec:1,help:'Side-to-side spacing between men in metres, close order.'}),
      gfN('Close ↕',{min:0,max:200,step:0.1,dec:1,help:'Front-to-back spacing between ranks in metres, close order.'}),
      gfN('Loose ↔',{min:0,max:200,step:0.1,dec:1,help:'Side-to-side spacing in loose order. It is always wider than close order.'}),
      gfN('Loose ↕',{min:0,max:200,step:0.1,dec:1,help:'Front-to-back spacing in loose order.'}),
      gfN('Ranks',{min:1,max:50,help:'How many ranks deep the unit forms up by default. Pikes use 8; most infantry 3–4.'}),
      gfS('Formation','formation_main',{w:2,
        help:'The formation the unit starts in. With a second formation set, this one <b>must</b> be '
          +'<code>square</code> or <code>horde</code> (a circle).'}),
      gfS('Can switch to','formation_special',{w:2,optional:1,
        help:'Optional. The formation the unit can toggle into: <code>phalanx</code> (a spear wall, which needs '
          +'<code>long_pike</code> on the primary weapon), <code>schiltrom</code>, <code>shield_wall</code>, '
          +'<code>testudo</code> or <code>wedge</code>.'})],
    arity:[6,7],
    join:p=>{const q=p.map(x=>(''+(x==null?'':x)).trim());
      // drop the empty 7th slot unless the file's own line carried it as a
      // trailing comma, which one real unit in Third Age Reforged does
      if(!q[6]&&p.gfSrcLen!==7)q.length=6; return q.join(', ');}},
  'stat_health':{t:'Hit points',syn:'man, mount/animal',
    doc:gfDoc('How many killing blows it takes to put one man down.',[
      'Almost every unit in the game uses 1. More than that is effectively a monster.',
      'Ridden horses and camels have <b>no</b> separate hit points.',
      'The second box is for elephants and attached animals.']),
    parts:[gfN('Man',{min:0,max:999,help:'Killing blows one man absorbs. 1 is normal.'}),
      gfN('Mount / animal',{min:0,max:999,
        help:'Hit points of the mount or attached animal, where it has its own. Horses and camels do not.'})]},
  'stat_stl':{t:'Soldiers to stay alive',opt:1,syn:'<men>',
    doc:gfDoc('Optional. How many men the unit must keep for the game to still count it alive.',[
      'Only a handful of units in any mod set it.']),
    parts:[gfN('Men',{min:0,max:999})]},

  'stat_pri':gfWeaponSpec('Primary weapon',
    gfDoc('The weapon the unit leads with.',[
      '<b>A missile weapon has to be this one.</b> The engine will not fire a secondary bow.',
      'Artillery is the exception: the crew’s own hand weapon goes here and the engine’s '
        +'shot is the secondary line.'])),
  'stat_pri_ex':gfExSpec('Primary'),
  'stat_pri_attr':gfAttrSpec('Primary'),
  'stat_sec':gfWeaponSpec('Secondary weapon',
    gfDoc('The sidearm.',[
      'On a mounted, vehicle or artillery unit this is the mount’s or engine’s own attack.',
      'A missile unit’s melee weapon belongs here.',
      '"No sidearm" is one exact line: <code>0, 0, no, 0, 0, no, melee_simple, blunt, '
        +'none, 25, 1</code>. The button in this card’s header writes it.'])),
  'stat_sec_ex':gfExSpec('Secondary'),
  'stat_sec_attr':gfAttrSpec('Secondary'),
  'stat_ter':gfWeaponSpec('Third weapon',
    gfDoc('Optional third weapon, read exactly like the other two.',[
      'Vanilla uses it once: the trebuchet’s rotten cow carcass.',
      'Either all of the ternary lines are present or none of them is.'])),
  'stat_ter_ex':gfExSpec('Third'),
  'stat_ter_attr':gfAttrSpec('Third'),

  'stat_pri_armour':{t:'Defence',syn:'armour, defence skill, shield, hit sound',
    doc:gfDoc('What protects the man, split three ways because they work differently.',[
      '<b>Armour</b> counts against everything.',
      '<b>Defence skill</b> is his parrying, and is <b>not</b> used when he is shot at.',
      '<b>Shield</b> only counts against attacks from the front or the left.']),
    parts:[gfN('Armour',{min:0,max:255,help:'Armour factor. Counts against every kind of attack. Halved by an <code>ap</code> weapon.'}),
      gfN('Defence skill',{min:0,max:255,help:'Parrying skill. It is ignored when the man is shot at: armour and shield are all that protect him then.'}),
      gfN('Shield',{min:0,max:255,help:'Shield factor. Only applies to attacks from the front or the left, which is why flanking works.'}),
      gfS('Hit sound','armour_sound',{w:2,help:'What it sounds like when the man is hit: <code>flesh</code>, <code>leather</code> or <code>metal</code>. Cosmetic.'})]},
  'stat_armour_ex':{t:'Defence (extended)',opt:1,
    syn:'armour 0, armour 1, armour 2, armour 3, defence skill, shield melee, shield missile, hit sound',
    doc:gfDoc('Optional long form of the line above.',[
      'Gives armour its own value at the base level and at each of the three upgrade '
        +'levels, instead of letting the engine derive them.',
      'Splits the shield into one value against melee and another against missile fire.',
      'Vanilla ships it commented out.']),
    parts:[gfN('Armour 0',{min:0,max:255,help:'Armour with no smith upgrade.'}),
      gfN('Armour 1',{min:0,max:255,help:'Armour at the first upgrade level.'}),
      gfN('Armour 2',{min:0,max:255,help:'Armour at the second upgrade level.'}),
      gfN('Armour 3',{min:0,max:255,help:'Armour at the third upgrade level.'}),
      gfN('Defence skill',{min:0,max:255,help:'As in the normal line. It is not used against missiles.'}),
      gfN('Shield melee',{min:0,max:255,help:'Shield factor against melee attacks from the front or left.'}),
      gfN('Shield missile',{min:0,max:255,help:'Shield factor against missile fire. This is the split the longer line exists for.'}),
      gfS('Hit sound','armour_sound',{w:2})]},
  'stat_sec_armour':{t:'Vehicle / animal defence',syn:'armour, defence skill, hit sound',
    doc:gfDoc('The defence of the attached artillery piece, wagon or animal.',[
      'There is no shield slot here.',
      'A ridden horse has no separate defence, so ordinary cavalry leaves this at '
        +'<code>0, 0, flesh</code>.']),
    parts:[gfN('Armour',{min:0,max:255,help:'Armour of the vehicle or animal.'}),
      gfN('Defence skill',{min:0,max:255,help:'Defence skill of the vehicle or animal.'}),
      gfS('Hit sound','armour_sound',{w:2})]},
  'stat_mental':{t:'Morale',syn:'morale, discipline, training[, lock_morale]',
    doc:gfDoc('The unit’s state of mind.',[
      '<b>Morale</b>: how much punishment it takes before routing.',
      '<b>Discipline</b>: how well it answers a sudden shock, like a charge in the rear '
        +'or the general dying.',
      '<b>Training</b>: how tidily it holds its formation.']),
    parts:[gfN('Morale',{min:0,max:100,help:'Base morale. Higher units stand longer before routing.'}),
      gfS('Discipline','discipline',{w:2,
        help:'<code>low</code>, <code>normal</code>, <code>disciplined</code> or <code>impetuous</code>. '
          +'Impetuous units may charge without being told to.'}),
      gfS('Training','training',{w:2,
        help:'<code>untrained</code>, <code>trained</code> or <code>highly_trained</code>: how neatly the unit '
          +'keeps its formation while it moves.'}),
      gfP('Never routs','flag',{on:'lock_morale',
        help:'Adds <code>lock_morale</code>, an optional fourth value: the unit will not rout, whatever happens to it.'})],
    arity:[3,4],
    join:p=>{const q=p.slice(0,3).map(x=>(''+(x==null?'':x)).trim());
      // the 4th token goes back exactly as the file wrote it: Third Age Reforged
      // spells one `locked`, which does nothing, and turning that into
      // `lock_morale` on save would quietly make the unit unroutable
      const f=(''+(p[3]==null?'':p[3])).trim();
      if(f)q.push(f==='1'?'lock_morale':f); return q.join(', ');}},
  'stat_heat':{t:'Heat fatigue',syn:'<extra fatigue>',
    doc:gfDoc('Extra fatigue in hot climates, on top of the normal rate.',[
      'Higher tires sooner in the desert.',
      'Heavily armoured units carry the most.']),
    parts:[gfN('Heat',{min:-100,max:100})]},
  'stat_ground':{t:'Ground modifiers',syn:'scrub, sand, forest, snow',
    doc:gfDoc('Combat modifiers per ground type, wherever the unit is fighting.',[
      'Negative is a penalty.',
      'A desert unit has a positive sand value and a negative snow one.']),
    parts:[gfN('Scrub',{min:-100,max:100,help:'Modifier while fighting on scrub.'}),
      gfN('Sand',{min:-100,max:100,help:'Modifier on sand. Positive for desert troops.'}),
      gfN('Forest',{min:-100,max:100,help:'Modifier in forest. Positive for woodsmen, negative for close formations.'}),
      gfN('Snow',{min:-100,max:100,help:'Modifier in snow. Positive for northern troops.'})]},
  'stat_charge_dist':{t:'Charge distance',syn:'<metres>',
    doc:gfDoc('How far out from the enemy the unit breaks into its charge.',[
      'Bigger means it starts running sooner.',
      'That builds more charge, but also tires it more.']),
    parts:[gfN('Metres',{min:0,max:999})]},
  'stat_fire_delay':{t:'Fire delay',opt:1,syn:'<delay>',
    doc:gfDoc('Extra delay between volleys, on top of what the reload animation costs.',[
      'Modders report it has no effect in Kingdoms.',
      'Nearly every unit carries 0.']),
    parts:[gfN('Delay',{min:0,max:999})]},
  'stat_food':{t:'Food',opt:1,syn:'<a>, <b>',
    doc:gfDoc('No longer used by the engine.',[
      'Every unit in the game carries <code>60, 300</code> out of habit.',
      'No reason to change it, no reason to remove it.']),
    parts:[gfN('Value 1',{min:0,max:9999}),gfN('Value 2',{min:0,max:9999})]},
  'stat_cost':{t:'Cost',syn:'turns, recruit, upkeep, weapon ug, armour ug, custom battle, free picks, price rise',
    doc:gfDoc('Everything the unit costs.',[
      'The first box is turns.',
      'Every other box is florins.']),
    parts:[gfN('Turns',{min:0,max:99,help:'Turns the unit takes to recruit.'}),
      gfN('Recruit',{min:0,max:999999,help:'Florins to recruit it in the campaign. This does <i>not</i> set the price of hiring it as a mercenary.'}),
      gfN('Upkeep',{min:0,max:999999,help:'Florins per turn to keep it in the field.'}),
      gfN('Weapon ug.',{min:0,max:999999,help:'Florins the smith charges to upgrade its weapons.'}),
      gfN('Armour ug.',{min:0,max:999999,help:'Florins the smith charges to upgrade its armour.'}),
      gfN('Custom battle',{min:0,max:999999,help:'What it costs in a custom battle, independent of the campaign price.'}),
      gfN('Free picks',{min:0,max:99,help:'How many you may buy in a custom battle before the price starts climbing.'}),
      gfN('Price rise',{min:0,max:999999,help:'How much the custom-battle price goes up by after that.'})]},
  'recruit_priority_offset':{t:'AI recruit priority',opt:1,syn:'<offset>',
    doc:gfDoc('Kingdoms only. How badly the AI wants this unit.',[
      'Higher means it recruits it more often.',
      'Negative pushes it down the list.',
      'It goes at the end of the unit’s block.']),
    parts:[gfN('Offset',{min:-1000,max:1000})]},
  'crusading_upkeep_modifier':{t:'Crusade upkeep',opt:1,syn:'<multiplier>',
    doc:gfDoc('Multiplies the unit’s upkeep while it is on a crusade or jihad.',[
      'Vanilla uses 0.5 (half price) on the units it wants you to take along.']),
    parts:[gfN('×',{min:0,max:10,step:0.1,dec:2})]},
  'armour_ug_levels':{t:'Armour upgrade levels',w:'uglevels',syn:'level, level, level, …',
    doc:gfDoc('The smith level each armour tier needs, read position by position against '
      +'the models below.',[
      'The first value is the unit’s normal level. The rest are the upgrades.',
      'The list has to stay ascending.',
      'More levels than models is normal: the last model carries the levels above it.'])},
  'armour_ug_models':{t:'Armour upgrade models',w:'ugmodels',syn:'model, model, model, …',
    doc:gfDoc('One <code>battle_models.modeldb</code> entry per armour tier.',[
      'Position 0 is the unit’s normal look, position 1 the first upgrade, and so on.',
      'Naming the same entry twice is a real pattern, not a mistake: it gains the '
        +'armour upgrade in its stats without changing how it looks.',
      'These entries do <b>not</b> decide how the unit animates. The '
        +'<code>soldier</code> line does.'])},
  'ownership':{t:'Ownership',w:'factions',syn:'faction, faction, culture, …',
    doc:gfDoc('The factions and cultures allowed to have this unit.',[
      'Not optional book-keeping: <b>a faction that can build the unit still cannot '
        +'recruit it unless it is listed here</b>.',
      'It also decides which faction folders the unit’s card is looked up in.'])},
  'era 0':{t:'Custom battle: Early',w:'factions',opt:1,syn:'faction, faction, …',
    doc:gfDoc('Optional. Which factions may pick this unit in an <b>Early</b>-era custom battle.',[
      'Nothing to do with the campaign.',
      'The campaign is <code>ownership</code> plus the building that recruits it.'])},
  'era 1':{t:'Custom battle: High',w:'factions',opt:1,syn:'faction, faction, …',
    doc:'Optional. Which factions may pick this unit in a <b>High</b>-era custom battle.'},
  'era 2':{t:'Custom battle: Late',w:'factions',opt:1,syn:'faction, faction, …',
    doc:'Optional. Which factions may pick this unit in a <b>Late</b>-era custom battle.'},
  'card_pic_dir':{t:'Unit card folder',opt:1,syn:'<folder>',
    doc:gfDoc('Optional. Pins the unit card to one folder under <code>data/ui/units/</code>.',[
      'Without it the game looks the card up in the <i>player’s</i> faction folder.',
      'Useful for a mercenary or a shared unit.',
      'A trap otherwise: it overrides every per-faction card.']),
    parts:[gfT('Folder',{grow:1,mono:1})]},
  'info_pic_dir':{t:'Info card folder',opt:1,syn:'<folder>',
    doc:'Optional. The same thing for the big info card, under <code>data/ui/unit_info/</code>.',
    parts:[gfT('Folder',{grow:1,mono:1})]},
  'unit_info':{t:'Info panel numbers',opt:1,syn:'melee attack, missile attack, defence',
    doc:gfDoc('Optional. The three summary numbers the unit-info panel shows the player.',[
      'Vanilla keeps this line commented out on every unit.',
      'Left out, the engine works them out from the real stats.']),
    parts:[gfN('Melee attack',{min:0,max:999}),gfN('Missile attack',{min:0,max:999}),gfN('Defence',{min:0,max:999})]},
};

const GF_SECTIONS=[
  {id:'basics',t:'Basics',keys:['type','dictionary','category','class','voice_type','accent',
    'banner faction','banner holy','banner unit']},
  {id:'men',t:'Men & mounts',keys:['soldier','officer','mount','ship','engine','mounted_engine',
    'animal','stat_health','stat_stl','move_speed_mod','armour_ug_levels','armour_ug_models']},
  /* Abilities used to be a group of its own, holding two lines: `attributes` and
     `mount_effect`. Two cards is not a tab — it sat there half empty while the
     Weapons tab beside it carried nine — and the two are read together anyway,
     because what a unit can DO and what it does it WITH are the same question.
     They lead the group: `attributes` is the widest-reaching line on the unit
     and belongs at the top of whatever tab it is on. */
  {id:'weapons',t:'Weapons & abilities',
   keys:['attributes','mount_effect','stat_pri','stat_pri_attr','stat_pri_ex',
    'stat_sec','stat_sec_attr','stat_sec_ex','stat_ter','stat_ter_attr','stat_ter_ex']},
  {id:'defence',t:'Defence & morale',keys:['stat_pri_armour','stat_armour_ex','stat_sec_armour',
    'stat_mental','formation','stat_charge_dist','stat_fire_delay','stat_heat','stat_ground']},
  {id:'cost',t:'Recruitment',keys:['stat_cost','recruit_priority_offset','crusading_upkeep_modifier',
    'ownership','era 0','era 1','era 2']},
  {id:'ui',t:'Cards & misc',keys:['card_pic_dir','info_pic_dir','unit_info','stat_food']},
  {id:'other',t:'Other lines',keys:[]},
];
const GF_SECTION_OF=(()=>{const m={};GF_SECTIONS.forEach(s=>s.keys.forEach(k=>m[k]=s.id));return m;})();
const gfKey=label=>label.replace(/#\d+$/,'');

/* ---- lines that read as one thought share a row --------------------------
   A card per EDU line is right for `stat_pri`, which is eleven settings. It is
   wrong for `banner faction`, which is one drop-down: a full-width card for it
   pushes the next one off the screen, and a guided unit is forty cards long.

   These groups sit side by side instead. A group is emitted where its FIRST
   member appears, in the group's own order rather than the file's — the pairs
   below are next to each other in a normal EDU, but a mod that has moved a line
   should not lose the pairing over it. Repeats come along: `officer`,
   `officer#2` and `officer#3` are one key and land on one row. */
const GF_PAIRS=[
  ['type','dictionary'],
  ['category','class','voice_type','accent'],
  ['banner faction','banner holy'],
  ['officer'],
  ['move_speed_mod','stat_health'],
  ['stat_heat','stat_ground'],
  ['stat_charge_dist','stat_fire_delay'],
];
const GF_PAIR_OF=(()=>{const m={};
  GF_PAIRS.forEach((g,i)=>g.forEach(k=>m[k]=i));return m;})();
// The cards of one section, with the paired ones wrapped in a row of their own.
function gfRows(host,shown,warns){
  const used=new Set(),out=[];
  shown.forEach(l=>{
    if(used.has(l))return;
    const g=GF_PAIR_OF[gfKey(l)];
    if(g==null){out.push(gfCard(host,l,warns)); return;}
    const run=[];
    GF_PAIRS[g].forEach(k=>shown.forEach(x=>{
      if(gfKey(x)===k&&!used.has(x)){run.push(x); used.add(x);}}));
    out.push(run.length>1
      ? `<div class="gfpair" style="--gfn:${run.length}">${
          run.map(x=>gfCard(host,x,warns)).join('')}</div>`
      : gfCard(host,run[0],warns));
  });
  return out.join('');
}

/* ---- splitting a line into its slots, and putting it back together ---- */
function gfParse(spec,val){
  const raw=(val==null?'':''+val);
  const n=(spec.parts||[]).length;
  if(!n)return {parts:[],ok:true};
  if(!raw.trim())return {parts:new Array(n).fill(''),ok:true,empty:true};
  let p=raw.split(',').map(s=>s.trim());
  const allow=spec.arity||[n];
  if(allow.indexOf(p.length)<0)return {parts:p,ok:false};
  const srcLen=p.length;   // BEFORE pad: how many fields the file's own line had
  if(spec.pad)p=spec.pad(p);
  while(p.length<n)p.push('');
  // A trailing comma is a field, and an optional field the file left empty is
  // NOT the same as a field the file does not have. `join` needs to tell them
  // apart to give the line back byte for byte; a named property on the array
  // rides along through every caller (they all mutate p.parts in place) and is
  // invisible to map/join/JSON. Absent = built fresh from the GUI, so normalise.
  p.gfSrcLen=srcLen;
  return {parts:p,ok:true};
}
function gfBuild(spec,parts){
  if(spec.join)return spec.join(parts);
  return parts.map(x=>(''+(x==null?'':x)).trim()).join(', ');
}

/* ---- host adapters ------------------------------------------------------
   The unit editor and the transfer composer keep their edits in different
   places (`state.ed.ov` + a removal set vs a per-unit `field_overrides`), have
   different extras (a real delete vs the base-unit B switches) and read
   different mods. Everything the renderer needs comes through here. */
function gfHostEditor(){
  const e=state.ed;
  return {
    id:'ed', key:'ed:'+e.mod+':'+e.unit, mod:e.mod,
    vocab:gfVocabFor(e.mod),
    fields:()=>e.d.fields,
    known:new Set(e.d.known_fields||[]),
    get:edFieldVal,
    orig:l=>{const f=e.d.fields.find(x=>x[0]===l);return f?f[1]:'';},
    set:(l,v)=>edSetField(l,v),
    changed:l=>(l in e.ov)&&e.ov[l]!==((e.d.fields.find(x=>x[0]===l)||['',''])[1]),
    removed:l=>e.rm.has(l),
    canRemove:true,
    protectedKeys:new Set(['type','dictionary','soldier']),
    toggleRemove:l=>{if(e.rm.has(l))e.rm.delete(l);else{e.rm.add(l);delete e.ov[l];}edRenderTab();},
    badge:()=>'',
    lock:()=>null,
    factions:()=>edFactionList(),
    facLabel:edFacLabel,
    missing:()=>{const present=new Set(e.d.fields.map(([l])=>gfKey(l)));
      return (e.d.known_fields||[]).filter(k=>!present.has(k));},
    add:k=>{e.d.fields=e.d.fields.concat([[k,'']]);e.added.add(k);e.ov[k]='';edRenderTab();},
    addLabel:(k,l)=>{e.d.fields=e.d.fields.concat([[l,'']]);e.added.add(l);e.ov[l]='';edRenderTab();},
    richArmour:true,          // the editor's ＋ tier menu and ✎ jump-to-model
    creates:()=>[],           // editing in place creates no modeldb entry
    rerender:()=>edRenderTab(),
    count:()=>edCount(),
    stale:()=>edStale(),
  };
}
function gfHostComposer(){
  const c=cfgFor(state.editing);
  const inh=new Set(c.base_type?(c._inherited||[]):[]);
  const lockFor=gfComposerLock(c);
  return {
    id:'cm', key:'cm:'+state.dst+':'+state.editing, mod:state.dst,
    vocab:gfVocabFor(state.dst),
    fields:()=>gfComposerFields(c),
    known:new Set(Object.keys(GF_FIELDS)),
    get:l=>{const lk=lockFor(gfKey(l)); if(lk)return lk.val;
      return (l in c.field_overrides)?c.field_overrides[l]:c._orig[l];},
    orig:l=>c._orig[l],
    set:(l,v)=>{if(v!==c._orig[l])c.field_overrides[l]=v; else delete c.field_overrides[l];},
    changed:l=>(l in c.field_overrides)&&c.field_overrides[l]!==c._orig[l],
    removed:()=>false,
    canRemove:false,
    protectedKeys:new Set(),
    toggleRemove:()=>{},
    badge:(l,cur)=>inh.has(gfKey(l))&&!/#\d+$/.test(l)?baseBadge(c,l,cur):'',
    lock:l=>/#\d+$/.test(l)?null:lockFor(gfKey(l)),
    factions:()=>gfComposerFactions(c),
    facLabel:facLabel,
    missing:()=>{const present=new Set(gfComposerFields(c).map(([l])=>gfKey(l)));
      return (state.ed&&state.ed.d.known_fields||Object.keys(GF_FIELDS)).filter(k=>!present.has(k));},
    add:k=>{c._fields=c._fields.concat([[k,'']]);c.field_overrides[k]='';renderAllFields(state.editing);},
    addLabel:(k,l)=>{c._fields=c._fields.concat([[l,'']]);c.field_overrides[l]='';renderAllFields(state.editing);},
    richArmour:false,
    creates:()=>gfComposerCreates(),
    rerender:()=>renderAllFields(state.editing),
    count:()=>updateFieldChanged(),
    stale:()=>{},
  };
}
// Same two locks the raw view applies: a copied voice owns accent + voice_type,
// and replacing a unit keeps the replaced unit's type + dictionary.
function gfComposerLock(c){
  const snd=soundDonor(c);
  const sndLock=snd.accent?{vals:{accent:snd.accent,voice_type:snd.cls},
    why:`Locked by the voice panel. “${snd.name}”’s sounds are copied into ${snd.accent} / ${snd.cls}, `
       +`and these two fields are what point the game at that block. Choose “Don’t import sound” to edit them yourself.`}:null;
  const rb=baseUnitOf(c);
  const idLock=(isReplace(c)&&rb)?{vals:{type:rb.type,dictionary:rb.dictionary},
    why:`Locked. This transfer rewrites “${rb.type}” in place, so it keeps its own type and dictionary.`}:null;
  return key=>(idLock&&(key in idLock.vals))?{val:idLock.vals[key],why:idLock.why}
             :(sndLock&&(key in sndLock.vals))?{val:sndLock.vals[key],why:sndLock.why}:null;
}
function gfComposerFields(c){
  const snd=soundDonor(c);
  let fields=c._fields||[];
  if(snd.accent){        // a copied voice ADDS these two lines if the unit lacks them
    fields=fields.slice();
    for(const k of ['voice_type','accent']){
      if(fields.some(([l])=>l===k))continue;
      const after=fields.findIndex(([l])=>l==='voice_type'||l==='class');
      fields.splice(after<0?0:after+1,0,[k,k==='accent'?snd.accent:snd.cls]);
    }
  }
  return fields;
}
/* The modeldb entries this transfer is about to CREATE in the destination.
   `/api/edu_vocab` lists what the destination has today, so without this every
   new unit's own soldier and armour-upgrade models were flagged "not an entry in
   this mod's battle_models.modeldb" — true of the mod as it stands, false of the
   mod the moment the transfer lands, and it is the same job that writes both. */
function gfComposerCreates(){
  const u=(state.data&&state.data.units||[]).find(x=>x.type===state.editing);
  if(!u)return [];
  // model_names() already covers soldier + officers + armour_ug_models
  return (u.models||[]).concat(u.mount?[u.mount]:[]).filter(Boolean);
}
// The composer has no per-unit faction list of its own: use the destination mod's,
// widened by whatever the unit's own ownership/era lines already name.
function gfComposerFactions(c){
  const all=Object.keys(state.factionNames||{}).slice();
  (state.destData&&state.destData.factions||[]).forEach(f=>all.push(f.name||f));
  ['ownership','era 0','era 1','era 2'].forEach(l=>{
    const v=(l in c.field_overrides)?c.field_overrides[l]:c._orig[l];
    csv(v||'').forEach(f=>all.push(f));
  });
  const seen=new Set();
  return all.filter(f=>f&&!seen.has(f)&&seen.add(f)).sort((a,b)=>facLabel(a).localeCompare(facLabel(b)));
}

/* ---- per-dialog view state (which section, the search box, which cards have
        their raw line or help opened) ---- */
function gfState(host){
  if(!state.gf||state.gf.key!==host.key)
    state.gf={key:host.key,tab:'basics',q:'',raw:new Set(),help:new Set()};
  return state.gf;
}

/* ---- warnings ------------------------------------------------------------
   Things the engine will not do, or will do differently from what the numbers
   suggest. They never block a save — a mod may know better — but the point of a
   guided editor is that you find out here rather than at the loading screen. */
function gfWarnings(host){
  const out={},add=(l,h,k)=>{(out[l]||(out[l]=[])).push({h,k:k||'warn'});};
  const val=l=>host.get(l)||'';
  const has=l=>host.fields().some(([x])=>x===l)&&!host.removed(l);
  const parts=l=>val(l).split(',').map(s=>s.trim());
  const num=x=>{const n=parseFloat(x);return isNaN(n)?null:n;};

  const cat=(val('category')||'').toLowerCase();
  const cls=(val('class')||'').toLowerCase();
  if(has('class')&&cat==='infantry'&&cls==='spearmen'){/* fine */}
  if(has('class')&&cat!=='infantry'&&cls==='spearmen')
    add('class','<b>spearmen</b> is an infantry class, so on a '+esc(cat)+' unit the engine falls back to a default.');
  if(has('animal')&&cat!=='handler')
    add('animal','An <code>animal</code> line needs <code>category handler</code>, otherwise the animals never appear.');
  // a unit carries ONE kind of attachment; the engine reads whichever it finds
  // first and the others are dead weight
  const extras=['ship','engine','mounted_engine','animal'].filter(has);
  if(extras.length>1)extras.forEach(k=>add(k,
    'A unit can only use one of <code>ship</code>, <code>engine</code>, <code>mounted_engine</code> and '
    +'<code>animal</code>. This one has <b>'+extras.join('</b>, <b>')+'</b>.','bad'));

  ['stat_pri','stat_sec','stat_ter'].forEach(k=>{
    if(!has(k))return;
    const p=parts(k); if(p.length<11)return;
    const atk=num(p[0]),proj=(p[2]||'').toLowerCase(),rng=num(p[3]),ammo=num(p[4]),wt=(p[5]||'').toLowerCase();
    if(atk!==null&&atk>63)add(k,'Attack <b>'+esc(p[0])+'</b> is above the engine’s cap of 63, so it will behave as 63.');
    const missile=(wt==='missile'||wt==='thrown'||wt==='siege_missile');
    if(missile&&proj==='no')add(k,'Weapon type is <b>'+esc(wt)+'</b> but the projectile is <code>no</code>, so it will never fire.');
    if(!missile&&proj!=='no'&&proj)add(k,'A projectile is set but the weapon type is <b>'+esc(wt||'none')+'</b>. Only missile, thrown and siege_missile weapons fire.');
    if(missile&&!rng)add(k,'Missile weapon with range 0, so it cannot reach anything.');
    if(missile&&!ammo)add(k,'Missile weapon with 0 ammunition, so it fires nothing.');
    if(proj&&proj!=='no'&&!gfHas(gfDefined(host,'projectile'),p[2])&&gfDefined(host,'projectile').length)
      add(k,'Projectile <code>'+esc(p[2])+'</code> is not defined in this mod’s <code>descr_projectile.txt</code>.','bad');
    if(p.length>=12&&(p[9]||'').trim()&&!/^[A-Za-z_][\w]*$/.test(p[9].trim()))
      add(k,'The 12-value form puts the fire effect in slot 10, and <code>'+esc(p[9])+'</code> does not look like an effect name.');
  });
  if(has('stat_pri')&&has('stat_sec')){
    const w=x=>((parts(x)[5])||'').toLowerCase();
    const missileSec=['missile','thrown'].indexOf(w('stat_sec'))>=0;
    if(missileSec&&['missile','thrown','siege_missile'].indexOf(w('stat_pri'))<0)
      add('stat_sec','A missile weapon has to be the <b>primary</b> one. The engine ignores a secondary bow.');
  }
  if(has('stat_ter')!==has('stat_ter_attr'))
    add(has('stat_ter')?'stat_ter':'stat_ter_attr','A third weapon needs <b>all</b> of stat_ter and stat_ter_attr, or the engine drops it.');

  if(has('formation')){
    const p=parts('formation');
    if(p.length>=7){
      const a=(p[5]||'').toLowerCase(),b=(p[6]||'').toLowerCase();
      if(b&&['square','horde'].indexOf(a)<0)
        add('formation','With two formations the first must be <b>square</b> or <b>horde</b>.');
      if(b&&['schiltrom','shield_wall','phalanx','testudo','wedge'].indexOf(b)<0)
        add('formation','<b>'+esc(b)+'</b> is not one of the switchable formations (schiltrom, shield_wall, phalanx, testudo, wedge).');
      if(b==='phalanx'&&csv(val('stat_pri_attr')).indexOf('long_pike')<0)
        add('formation','A <b>phalanx</b> unit normally needs <code>long_pike</code> in its primary weapon attributes.');
    }
  }
  const lv=csv(val('armour_ug_levels')),md=csv(val('armour_ug_models'));
  if(has('armour_ug_models')&&lv.length&&md.length&&md.length>lv.length)
    add('armour_ug_models',`<b>${md.length}</b> upgrade model(s) but only <b>${lv.length}</b> level(s). `
      +'The tiers past the last level have nothing to trigger them.');
  else if(has('armour_ug_models')&&lv.length&&md.length&&lv.length>md.length)
    add('armour_ug_models',`<b>${lv.length}</b> armour levels share <b>${md.length}</b> model(s), so the last `
      +'model carries the levels above it. Common and fine; add models only if the tiers should look different.','info');
  const defModels=gfDefined(host,'model');
  // plus whatever this job is about to write into the modeldb — see host.creates
  const coming=new Set((host.creates?host.creates():[]).map(x=>(''+x).trim().toLowerCase()));
  const knownModel=m=>gfHas(defModels,m)||coming.has((m||'').trim().toLowerCase());
  if(defModels.length){
    md.forEach(m=>{if(!knownModel(m))add('armour_ug_models','<code>'+esc(m)+'</code> is not an entry in this mod’s battle_models.modeldb.','bad');});
    const sm=(parts('soldier')[0]||'');
    if(has('soldier')&&sm&&!knownModel(sm))
      add('soldier','<code>'+esc(sm)+'</code> is not an entry in this mod’s battle_models.modeldb.','bad');
  }
  [['mount','mount'],['engine','engine'],['mounted_engine','mounted_engine'],
   ['ship','ship'],['animal','animal']].forEach(([k,v])=>{
    const list=gfDefined(host,v);
    if(has(k)&&list.length&&!gfHas(list,val(k))&&!coming.has((val(k)||'').trim().toLowerCase()))
      add(k,'<code>'+esc(val(k))+'</code> is not defined in this mod’s <code>descr_'+
        (k==='mounted_engine'?'mounted_engines':k==='engine'?'engines':k==='animal'?'animals':k)+'.txt</code>.','bad');
  });
  // The three banner lines name banners declared by descr_banners_new.xml, one
  // XML section per line. `defined` only carries them when the mod HAS that file.
  [['banner faction','banner_faction','FactionBanners'],
   ['banner holy','banner_holy','HolyBanners'],
   ['banner unit','banner_unit','UnitSpecificBanners']].forEach(([k,v,section])=>{
    const list=gfDefined(host,v);
    if(has(k)&&list.length&&!gfHas(list,val(k)))
      add(k,'<code>'+esc(val(k))+'</code> is not declared in this mod’s '
        +'<code>descr_banners_new.xml</code> (<code>&lt;'+section+'&gt;</code>).','bad');
  });
  if(has('soldier')){
    // NB: not "fewer than 4". The guide gives 4 as the minimum, but shipped mods
    // field 2-man scout and monster units that work perfectly well — only a unit
    // with no men at all is definitely wrong.
    const men=num(parts('soldier')[1]);
    if(men!==null&&men<1)add('soldier','A unit with no men, so nothing will be recruited.','bad');
  }
  if(has('ownership')&&!csv(val('ownership')).length)
    add('ownership','No owner. No faction can recruit this unit, and its unit card has no faction folder to live in.','bad');
  const attrs=csv(val('attributes'));
  if(attrs.indexOf('mercenary_unit')>=0&&!has('card_pic_dir'))
    add('attributes','<code>mercenary_unit</code>: the unit card is looked up under <code>ui/units/mercs/</code> unless <code>card_pic_dir</code> says otherwise.','info');
  if(attrs.indexOf('can_run_amok')>=0&&!has('mount'))
    add('attributes','<code>can_run_amok</code> only does anything on a mounted unit.');
  if(has('stat_mental')){
    const p=parts('stat_mental');
    if(p.length>3&&(p[3]||'').toLowerCase()!=='lock_morale')
      add('stat_mental','The optional fourth value can only be <code>lock_morale</code>.','bad');
  }
  return out;
}

/* ---- rendering ---------------------------------------------------------- */
function gfRender(host){
  const gf=gfState(host);
  const warns=gfWarnings(host);
  const groups={};GF_SECTIONS.forEach(s=>groups[s.id]=[]);
  host.fields().forEach(([label])=>{
    const k=gfKey(label);
    let sec=GF_SECTION_OF[k];
    // a repeated line only has a guided shape when the field itself is repeatable
    if(sec&&/#\d+$/.test(label)&&k!=='officer')sec=null;
    (groups[sec||'other']).push(label);
  });
  const q=(gf.q||'').trim().toLowerCase();
  let shown,heading='';
  if(q){
    shown=host.fields().map(([l])=>l).filter(l=>{
      const sp=GF_FIELDS[gfKey(l)]||{};
      return (l+' '+(sp.t||'')+' '+(sp.doc||'')).toLowerCase().indexOf(q)>=0;});
    heading=`<div class="gfintro">${shown.length} field(s) matching “${esc(gf.q)}”.</div>`;
  }else{
    if(!groups[gf.tab]||(!groups[gf.tab].length&&gf.tab!=='other'))
      gf.tab=(GF_SECTIONS.find(s=>groups[s.id].length)||GF_SECTIONS[0]).id;
    shown=groups[gf.tab];
  }
  const nWarn=Object.keys(warns).length;
  const nav=GF_SECTIONS.map(s=>{
    const n=groups[s.id].length;
    if(!n&&s.id==='other')return '';
    const hits=groups[s.id].filter(l=>gfReal(warns[l]).length);
    // the badge names the fields, not just how many — a bare "3 things to look
    // at" makes you open all three sections to find out which
    const why=hits.length?hits.join(', ')+'. Hover or click the section to read them.':'';
    return `<button class="${!q&&gf.tab===s.id?'on':''}" onclick="gfTab('${s.id}')">${esc(s.t)}
      <span class="n">${n}</span>${hits.length?`<span class="bad" title="${esc(why)}">▲ ${hits.length}</span>`:''}</button>`;
  }).join('');
  return `<div class="gfwrap">
    <div class="gfnav" id="gfNav">${nav}</div>
    <div class="gfbody" id="gfBody">
      <div class="gfsum" id="gfSum">${gfSumHtml(host,warns)}</div>
      ${heading}
      ${shown.length?gfRows(host,shown,warns)
        :'<div class="gfempty">Nothing in this group. The unit has no such lines, so add one below.</div>'}
      ${gfAddHtml(host)}
    </div>
    ${gfDatalists(host)}</div>`;
}
function gfTab(id){const gf=state.gf; if(!gf)return; gf.tab=id; gf.q='';
  const f=document.getElementById('fieldFilter'); if(f)f.value='';
  gfRerenderBody();}
// Re-draw just the guided body, so switching a section or opening a raw line
// does not throw away the rest of the dialog (or its scroll position).
function gfRerenderBody(){
  const box=document.getElementById('allFields'); if(!box)return;
  if(!((state.mode==='edit'&&state.ed)||state.editing))return;
  const host=gfHost();
  const b=document.getElementById('gfBody'),was=b?b.scrollTop:0;
  box.innerHTML=gfRender(host); gfWire(host);
  const now=document.getElementById('gfBody'); if(now&&was)now.scrollTop=was;
}
const gfReal=list=>(list||[]).filter(x=>x.k!=='info');
function gfSumHtml(host,warns){
  const n=Object.values(warns).reduce((a,b)=>a+gfReal(b).length,0);
  const bad=Object.values(warns).reduce((a,b)=>a+b.filter(x=>x.k==='bad').length,0);
  return `<span class="count">${host.fields().length} line(s) in this unit.</span>`
    +(n?`<span class="pill warn" onclick="gfShowWarnings()" title="Jump to the first one">
        ${bad?'✖ '+bad+' broken':''}${bad&&n-bad?' · ':''}${n-bad?'▲ '+(n-bad)+' to check':''}</span>`
      :`<span class="pill" style="border-color:var(--good);color:var(--good)">✓ nothing looks wrong</span>`);
}
function gfShowWarnings(){
  const el=document.querySelector('#gfBody .gfnote.bad,#gfBody .gfnote.warn');
  if(el){el.scrollIntoView({block:'center'});return;}
  // the first problem is in another section — find it and switch there
  const w=gfWarnings(gfHost()),first=Object.keys(w).find(k=>gfReal(w[k]).length); if(!first)return;
  gfTab(GF_SECTION_OF[gfKey(first)]||'other');
  setTimeout(()=>{const e2=document.querySelector('#gfBody .gfnote.bad,#gfBody .gfnote.warn');
    if(e2)e2.scrollIntoView({block:'center'});},0);
}

// One <datalist> per open drop-down, emitted once for the whole body.
function gfDatalists(host){
  const want=new Set();
  Object.values(GF_FIELDS).forEach(sp=>(sp.parts||[]).forEach(p=>{if(p.type==='combo')want.add(p.v);}));
  return [...want].map(v=>`<datalist id="gfdl-${esc(v)}">${
    gfV(host,v).map(x=>`<option value="${esc(x)}">`).join('')}</datalist>`).join('');
}

function gfCard(host,label,warns){
  const key=gfKey(label);
  const spec=GF_FIELDS[key];
  const gone=host.removed(label);
  const lk=host.lock(label);
  const cur=host.get(label);
  const changed=host.changed(label);
  const gf=gfState(host);
  const rawOpen=gf.raw.has(label)||!spec;
  const parsed=spec&&spec.parts?gfParse(spec,cur):null;
  const title=spec?spec.t:label;
  const canRm=host.canRemove&&!host.protectedKeys.has(key);
  const head=`<div class="gfhead">
    ${spec?qmSpec(key,null):''}
    <span class="t">${esc(title)}</span>
    <span class="k">${esc(label)}</span>
    ${spec&&spec.opt?'<span class="count" title="The engine works without this line">Optional</span>':''}
    ${lk?`<span class="ibadge" title="${esc(lk.why)}">🔒</span>`:host.badge(label,cur)}
    <span class="sp"></span>
    ${(!gone&&!lk&&GF_ACTIONS[key])?GF_ACTIONS[key](label,cur):''}
    ${spec?`<button class="${gf.help.has(label)?'on':''}" title="What this line does"
        onclick="gfHelp('${q1(esc(label))}')">?</button>`:''}
    ${lk?'':`<button class="${rawOpen?'on':''}" title="Show the line exactly as the file stores it"
        onclick="gfRaw('${q1(esc(label))}')">&lt;/&gt;</button>`}
    ${canRm?`<button class="rm" title="${gone?'Keep this line':'Delete this line from the unit'}"
        onclick="gfRemove('${q1(esc(label))}')">${gone?'↺':'✕'}</button>`:''}
  </div>`;
  let body='';
  if(gone)body='<div class="gfnote">This line will be removed from the unit.</div>';
  else if(lk)body=`<div class="gfrow"><div class="gfpart grow"><span class="pl">value</span>
      <input value="${esc(lk.val)}" disabled title="${esc(lk.why)}"></div></div>
    <div class="gfnote">${esc(lk.why)}</div>`;
  else if(spec&&spec.w)body=gfWidget(host,label,spec,cur);
  else if(spec&&parsed&&parsed.ok)body=gfParts(host,label,spec,parsed);
  else if(spec)body=`<div class="gfnote warn">This line has ${parsed.parts.length} value(s); the engine
      reads ${(spec.arity||[spec.parts.length]).join(' or ')} here, so it is shown as raw text.</div>`;
  const raw=(rawOpen&&!gone&&!lk)?`<div class="gfraw">
      <span class="pl">${esc(key)}</span>
      <input data-gfraw="${esc(label)}" value="${esc(cur)}" spellcheck="false"
        class="${changed?'changed':''}"></div>`:'';
  const doc=(spec&&gf.help.has(label))?`<div class="gfdoc">${spec.doc||''}</div>`:'';
  const empty=(parsed&&parsed.empty&&!gone)?'<div class="gfnote">This line is empty. Fill it in and it gets written.</div>':'';
  return `<div class="gfcard${changed?' changed':''}${gone?' gone':''}" data-card="${esc(label)}">
    ${head}${doc}${body}${empty}${raw}
    <div data-warn="${esc(label)}">${gfNotes(warns[label])}</div></div>`;
}
/* Quick actions in a card's header. "No secondary weapon" is not a cosmetic
   shortcut: the engine recognises one exact line as "this unit has no sidearm"
   (`0, 0, no, 0, 0, no, melee_simple, blunt, none, 25, 1`), and typing eleven
   values by hand to say nothing is how the reference editor makes people do it. */
const GF_NO_WEAPON='0, 0, no, 0, 0, no, melee_simple, blunt, none, 25, 1';
const gfIsNoWeapon=v=>{const p=(v||'').split(',').map(x=>x.trim());
  return p.length>=9&&p[0]==='0'&&p[2]==='no'&&(p[5]==='no'||p[5]==='');};
const GF_ACTIONS={
  stat_sec:(label,cur)=>gfIsNoWeapon(cur)?'':`<button title="Write the line the engine reads as
'this unit has no sidearm', and clear its attributes"
    onclick="gfNoWeapon('${q1(esc(label))}')">no secondary weapon</button>`,
  stat_ter:(label,cur)=>gfIsNoWeapon(cur)?'':`<button title="Write the empty-weapon line and clear its attributes"
    onclick="gfNoWeapon('${q1(esc(label))}')">no third weapon</button>`,
};
function gfNoWeapon(label){
  const host=gfHost();
  host.set(label,GF_NO_WEAPON);
  const attr=label+'_attr';
  if(host.fields().some(([l])=>l===attr))host.set(attr,'no');
  host.stale(); gfRerenderBody();
}
const gfNotes=list=>(list||[]).map(m=>`<div class="gfnote ${m.k||'warn'}">${m.h}</div>`).join('');

// Which PART of a multi-value line differs from what the file said. A whole-line
// "changed" flag is no help on `stat_pri 7, 3, no, 0, 0, melee, …`: you want the
// one number you touched lit up, not all thirteen.
function gfPartChanged(host,label,spec,parsed){
  const was=gfParse(spec,(host.orig?host.orig(label):'')||'');
  const whole=host.changed(label);
  const norm=v=>(v==null?'':''+v).trim();
  return i=>{
    if(!was||!was.ok||!parsed.ok)return whole;   // can't line them up, so mark the lot
    return norm(parsed.parts[i])!==norm(was.parts[i]);
  };
}
function gfParts(host,label,spec,parsed){
  const key=gfKey(label);
  const partChanged=gfPartChanged(host,label,spec,parsed);
  const cells=spec.parts.map((p,i)=>{
    const v=parsed.parts[i]==null?'':parsed.parts[i];
    const ch=partChanged(i);
    const cls='gfpart'+(p.grow?' grow':p.w===3?' w3':p.w===2?' w2':'')+(ch?' changed':'');
    const attr=`data-gfp="${esc(label)}" data-i="${i}"`;
    const chc=ch?' changed':'';                  // the amber "you changed this"
    // the explanation hangs off the ? beside the part's name; the control keeps
    // an accessible name of its own, since the label is not a <label for=…>
    const aria=` aria-label="${esc(p.pl)}"`;
    let ctl;
    if(p.type==='flag'){
      ctl=`<label class="chk" style="height:26px"><input type="checkbox" ${attr}${aria}
        class="${chc.trim()}" ${v?'checked':''}> ${esc(p.on||'on')}</label>`;
    }else if(p.type==='sel'){
      const opts=gfV(host,p.v);
      const list=opts.indexOf(v)<0?[v].concat(opts):opts;
      ctl=`<select ${attr}${aria} class="${chc.trim()}">${list.map(o=>`<option value="${esc(o)}"${
        o===v?' selected':''}>${o===''?(p.optional?'None':'(unset)'):esc(o)}</option>`).join('')}</select>`;
    }else if(p.type==='combo'){
      // A model name is the one combo where the datalist is not enough: it is
      // 2000-odd entries and the thing you actually know is how the man should
      // MOVE, which lives in the entry's skeleton. ⌕ opens the picker.
      const box=`<input ${attr}${aria} class="${chc.trim()}" list="gfdl-${esc(p.v)}"
        value="${esc(v)}" spellcheck="false">`;
      ctl=p.v!=='model'?box:`<span class="gfcombo">${box}<button type="button" class="gfbrowse"
        tabindex="-1" title="Find an entry by skeleton, by name, or copy another unit's whole soldier line"
        onclick="mpOpen('${q1(esc(label))}',${i})">⌕</button></span>`;
    }else if(p.type==='num'){
      ctl=gfSpin(attr+aria,v,chc);
    }else{
      ctl=`<input ${attr}${aria} class="${chc.trim()}" value="${esc(v)}" spellcheck="false"
        ${p.mono?' style="font-family:ui-monospace,Consolas,monospace"':''}>`;
    }
    // the wrapper carries the part index too (but NOT data-gfp, which is the
    // "this is an editable control" marker) so hovering the part's NAME lights
    // the same one value in the code view — see cvPartOf
    return `<div class="${cls}" data-i="${i}"><span class="pl">${qmSpec(key,i)}${esc(p.pl)}${
      p.optional?' <span style="opacity:.6">(opt)</span>':''}</span>${ctl}</div>`;
  }).join('');
  return `<div class="gfgrid">${cells}</div>`;
}
/* A number box with its own ▴▾. The browser's own <input type=number> is not
   used on purpose: EDU values are decimals, negatives and occasionally blanks,
   and a number input quietly refuses or reformats those. This keeps a plain text
   box — so any value in the file survives being looked at — and puts the
   stepping in buttons and the ↑/↓ keys, which are the only things that clamp. */
const gfSpin=(attr,v,cls)=>`<span class="gfspin"><input ${attr} class="gfnum${cls||''}" value="${esc(v)}"
    spellcheck="false" inputmode="decimal"><span class="gfsp">
    <button type="button" tabindex="-1" data-spin="1" aria-label="increase">▴</button>
    <button type="button" tabindex="-1" data-spin="-1" aria-label="decrease">▾</button>
  </span></span>`;

/* ---- the ? marker -------------------------------------------------------
   Explanations are ASKED FOR, not sprung: a field's help hangs off a small ?
   at its top-left rather than off the field itself, so moving the pointer
   across a form does not set off a trail of cards, and a box you are trying to
   read is never covered by a tip about the box next to it.

   `qm(text)` is the plain form. `qmSpec(key, i)` is the one the guided editor
   uses, which pulls a full card out of GF_FIELDS instead of a line of text.
   Both are read by the same delegated handler below. */
// The markers are deliberately NOT tab stops: there is one per field, and a
// guided unit has four hundred of them — putting each in the tab order would
// double the keystrokes to cross a form. Keyboard users get the same card when
// they focus the field itself (see the focusin handler), and the marker keeps a
// plain `title` so it still has an accessible name of its own.
const qm=(text,title)=>!text?'':`<span class="qm" tabindex="-1"
  title="${esc(text)}"${title?` data-tiptitle="${esc(title)}"`:''}
  data-tiptext="${esc(text)}">?</span>`;
const qmSpec=(key,i)=>`<span class="qm" tabindex="-1" title="What is this?"
  data-tip="${esc(key)}"${i==null?'':` data-tipi="${i}"`}>?</span>`;
// A field's documentation as plain text, for the raw view — GF_FIELDS writes its
// `doc` as HTML, and a ? marker carries text.
function gfPlainDoc(key){
  const spec=GF_FIELDS[key];
  if(!spec||!spec.doc)return '';
  return spec.doc.replace(/<[^>]*>/g,'').replace(/\s+/g,' ').trim();
}

/* ---- the hover card -----------------------------------------------------
   One floating element driven by delegation, so it survives the guided body
   being redrawn (which happens on nearly every edit) without rebinding
   anything. */
function gfTipHtml(key,i){
  const spec=GF_FIELDS[key]; if(!spec)return '';
  if(i==null||i===''){
    return `<div class="tt">${esc(spec.t)}</div>
      <div class="tk">${esc(key)}${spec.syn?'  '+esc(spec.syn):''}</div>
      <div class="tb">${spec.doc||''}</div>
      ${spec.opt?'<div class="tf">Optional. The engine works without this line.</div>':''}`;
  }
  const p=(spec.parts||[])[+i]; if(!p)return '';
  const range=[];
  if(p.type==='num'){
    if(p.min!=null&&p.max!=null)range.push(`${p.min} to ${p.max}`);
    else if(p.min!=null)range.push(`${p.min} or more`);
    else if(p.max!=null)range.push(`up to ${p.max}`);
    if(p.step&&p.step!==1)range.push(`steps of ${p.step}`);
  }
  return `<div class="tt">${esc(p.pl)}${p.optional?' <span class="topt">optional</span>':''}</div>
    <div class="tk">${esc(key)}, value ${(+i)+1} of ${spec.parts.length}</div>
    <div class="tb">${p.help||spec.doc||''}</div>
    ${range.length?`<div class="tf">▴▾ and the ↑/↓ keys step within ${range.join(', ')}.
      Hold Shift for ×10, or hold the button down to repeat. Typing is never clamped.</div>`:''}`;
}
let gfTipEl=null;
function gfTipShow(el){
  let html;
  if(el.dataset.tiptext!==undefined){
    // a plain explanation moved off a field's own title attribute
    html=(el.dataset.tiptitle?`<div class="tt">${esc(el.dataset.tiptitle)}</div>`:'')
        +`<div class="tb">${esc(el.dataset.tiptext)}</div>`;
  }else{
    const key=el.dataset.tip,i=el.dataset.tipi;
    html=gfTipHtml(key,i===undefined?null:i);
  }
  if(!html)return;
  if(!gfTipEl){gfTipEl=document.createElement('div');gfTipEl.className='gftip';document.body.appendChild(gfTipEl);}
  gfTipEl.innerHTML=html; gfTipEl.style.display='block';
  gfTipEl.style.left='0px'; gfTipEl.style.top='0px';         // measure unconstrained
  const r=el.getBoundingClientRect(),t=gfTipEl.getBoundingClientRect();
  let x=r.left, y=r.bottom+7;
  if(x+t.width>window.innerWidth-10)x=Math.max(10,window.innerWidth-10-t.width);
  if(y+t.height>window.innerHeight-10)y=Math.max(10,r.top-7-t.height);
  gfTipEl.style.left=x+'px'; gfTipEl.style.top=y+'px';
}
function gfTipHide(){if(gfTipEl)gfTipEl.style.display='none';}
// bound once, on the document — the guided body is replaced wholesale on edits
const TIP_SEL='[data-tip],[data-tiptext]';
document.addEventListener('mouseover',ev=>{
  const el=ev.target&&ev.target.closest&&ev.target.closest(TIP_SEL);
  if(!el){gfTipHide();return;}
  if(el===gfTipEl)return;
  gfTipShow(el);
});
document.addEventListener('mouseleave',gfTipHide,true);
window.addEventListener('scroll',gfTipHide,true);
/* Focusing a field shows its ? card, so the help is reachable without a mouse
   even though the markers themselves are out of the tab order — but only when
   the focus came from the KEYBOARD. Clicking into a box to type in it was
   dropping a help card over the row you were about to edit, which reads as the ?
   button opening itself. `:focus-visible` can't tell these apart: browsers match
   it on text inputs however they were focused. */
let _tipByPointer=false;
document.addEventListener('pointerdown',()=>{_tipByPointer=true;},true);
document.addEventListener('keydown',()=>{_tipByPointer=false;},true);
document.addEventListener('focusin',ev=>{
  const byPointer=_tipByPointer; _tipByPointer=false;
  if(_tipQuiet)return;                     // a re-draw putting the caret back
  const t=ev.target;
  if(!t||!t.closest){gfTipHide();return;}
  let el=t.closest(TIP_SEL);
  if(!el&&/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName||'')){
    if(byPointer){gfTipHide();return;}     // clicked into, not tabbed into
    const cell=t.closest('.gfpart,.afrow,.brow,.condrow,.gfcard');
    el=cell?cell.querySelector('.qm'):null;
  }
  if(el)gfTipShow(el); else gfTipHide();
});
document.addEventListener('keydown',ev=>{if(ev.key==='Escape')gfTipHide();});
