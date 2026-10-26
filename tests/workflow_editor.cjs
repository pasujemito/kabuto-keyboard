// Install jsdom outside the checkout; see tests/README.md.
const {JSDOM}=require('jsdom');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../data/index.html'),'utf8');
const dom=new JSDOM(html,{runScripts:'outside-only',url:'http://kabuto.test'}),w=dom.window;
const requests=[];let saved;
w.confirm=()=>true;
w.fetch=async(url,options)=>{requests.push(url);if(url==='/api/config')saved=JSON.parse(options.body);return {ok:true,json:async()=>({})};};
w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
w.HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new w.Event('close'));};
w.eval(html.split('<script>')[1].split('</script>')[0].replace(/loadAll\(\)\.catch\([^\n]+/,'')+'\nwindow.testEval=code=>eval(code);');
const evaluate=code=>w.testEval(code);
const snapshot=()=>JSON.parse(evaluate('JSON.stringify(cfg)'));
const selectMode=value=>{const option=w.document.querySelector(`[aria-label="Playback mode"] [data-mode="${value}"]`);assert(option);option.click();};
evaluate(`meta={keyCount:6,maxLayers:8,keys:['A','W','H','LEFT','RIGHT','Z'],media:[]};cfg={version:1,layers:[{name:'Base',keys:[]}]};normalize();savedSnapshot=JSON.stringify(cfg);renderLayers();renderGrid();renderEditor();renderRecordings();`);
async function main(){
  assert(!w.document.querySelector('#editor').textContent.match(/nano|micro|cooldown|‰/));
  const first=evaluate(`importRecordingObject({name:'Walk',steps:[{type:'down',key:'W'},{type:'delay',ms:300},{type:'up',key:'W'}]}).id`);
  const second=evaluate(`importRecordingObject({name:'Attack',steps:[{type:'down',mods:['ctrl']},{type:'delay',ms:150},{type:'up',mods:['ctrl']}]}).id`);
  assert.equal(w.document.querySelectorAll('.recording-card').length,2);
  evaluate(`addRecordingToButton(${JSON.stringify(first)});addRecordingToButton(${JSON.stringify(second)});`);
  let key=snapshot().layers[0].keys[0];assert.equal(key.playbackMode,'sequence');assert.deepEqual(key.steps.map(s=>s.workflow),[first,second]);
  w.document.querySelector('[aria-label="Move recording up"]').click();key=snapshot().layers[0].keys[0];assert.deepEqual(key.steps.map(s=>s.workflow),[first,second]); // first up is disabled
  w.document.querySelector('[aria-label="Move recording down"]').click();
  assert.deepEqual(snapshot().layers[0].keys[0].steps.map(s=>s.workflow),[second,first]);
  selectMode('random');key=snapshot().layers[0].keys[0];assert.equal(key.steps[0].type,'random');assert.equal(key.steps[0].choices.length,2);
  const repeat=w.document.querySelector('#editor input[type="checkbox"]');repeat.click();assert.equal(snapshot().layers[0].keys[0].steps[0].avoidRecent,1);
  selectMode('sequence');assert.deepEqual(snapshot().layers[0].keys[0].steps.map(s=>s.workflow),[second,first]);
  w.confirm=()=>false;selectMode('single');assert.equal(snapshot().layers[0].keys[0].steps.length,2);
  w.confirm=()=>true;selectMode('single');assert.equal(snapshot().layers[0].keys[0].steps[0].workflow,second);
  await evaluate('save()');assert.equal(saved.layers[0].keys[0].playbackMode,'single');
  // Button colours are stored on the button and drawn on its keycap.
  w.document.querySelector('[aria-label="Button colour"] [aria-label="teal"]').click();
  assert.equal(snapshot().layers[0].keys[0].color,'teal');
  assert.match(w.document.querySelector('#grid .keycap').style.background,/gradient/);
  w.document.querySelector('[aria-label="Button colour"] [aria-label="none"]').click();
  assert.equal(snapshot().layers[0].keys[0].color,undefined);
  // Assigned recordings are grouped, badged, and locked until unlocked.
  const cardFor=name=>[...w.document.querySelectorAll('.recording-card')].find(c=>c.querySelector('input').value===name);
  assert(cardFor('Attack').classList.contains('locked'));assert(!cardFor('Walk').classList.contains('locked'));
  assert.equal(cardFor('Walk').querySelector('.badge.new').textContent,'New');
  assert.equal(cardFor('Attack').querySelector('button.badge').textContent,'#1');
  assert(cardFor('Attack').querySelector('[aria-label="Edit"]').disabled);assert(cardFor('Attack').querySelector('input').readOnly);
  cardFor('Attack').querySelector('[aria-label="Unlock recording"]').click();
  assert(!cardFor('Attack').querySelector('[aria-label="Edit"]').disabled);
  cardFor('Attack').querySelector('[aria-label="Lock recording"]').click();assert(cardFor('Attack').classList.contains('locked'));
  // Assigned recordings cannot be deleted.
  evaluate(`deleteRecording(${JSON.stringify(second)});`);assert(snapshot().workflows.some(r=>r.id===second));
  assert.match(w.document.querySelector('#toast').textContent,/Remove this recording/);
  // Existing direct button macros are preserved when adding another recording.
  evaluate(`selKey=1;cfg.layers[0].keys[1].steps=[{type:'key',key:'H',hold:30}];renderEditor();`);
  assert.match(w.document.querySelector('#editor').textContent,/existing custom macro/);
  evaluate(`addRecordingToButton(${JSON.stringify(first)});`);
  key=snapshot().layers[0].keys[1];assert.equal(key.steps.length,2);
  const preserved=snapshot().workflows.find(r=>r.id===key.steps[0].workflow);assert.equal(preserved.steps[0].key,'H');
  // Long recordings remain one visible item and export all captured steps.
  const long=evaluate(`importRecordingObject({name:'Long',steps:Array.from({length:330},()=>[{type:'down',mods:['ctrl']},{type:'delay',ms:100},{type:'up',mods:['ctrl']}]).flat()}).id`);
  const longItem=snapshot().workflows.find(r=>r.id===long);assert.equal(longItem.steps.length,5);
  assert(snapshot().workflows.filter(r=>r.recordingPartOf===long).every(r=>r.steps.length<=240));
  assert.equal(evaluate(`recordingList().filter(r=>r.id===${JSON.stringify(long)}).length`),1);
  evaluate(`selectedWorkflow=${JSON.stringify(long)};openJsonPreview('selected');`);
  let jsonText=w.document.querySelector('#jsonText');assert.equal(JSON.parse(jsonText.value).steps.length,990);
  assert(!JSON.parse(jsonText.value).steps.some(s=>s.type==='call'));
  const before=snapshot(),beforeRequests=requests.length;
  let copied;w.navigator.clipboard={writeText:async text=>{copied=text;}};await evaluate('copyJson()');assert.equal(copied,jsonText.value);
  w.navigator.clipboard={writeText:async()=>{throw new Error('denied');}};await evaluate('copyJson()');assert.equal(jsonText.selectionEnd,jsonText.value.length);
  let downloadedBlob,downloadedName;
  w.URL.createObjectURL=blob=>{downloadedBlob=blob;return 'blob:test';};w.URL.revokeObjectURL=()=>{};
  w.HTMLAnchorElement.prototype.click=function(){downloadedName=this.download;};
  evaluate('downloadJson()');assert.equal(downloadedName,'Long.json');
  const downloaded=await new Promise((resolve,reject)=>{const r=new w.FileReader();r.onload=()=>resolve(r.result);r.onerror=reject;r.readAsText(downloadedBlob);});
  assert.equal(JSON.parse(downloaded).steps.length,990);assert.deepEqual(snapshot(),before);assert.equal(requests.length,beforeRequests);
  evaluate('closeJsonPreview()');
  // Re-recording replaces old internal parts and retains all button references.
  evaluate(`openRecorder(${JSON.stringify(long)});rec.steps=[{type:'key',key:'A',hold:20}];useSteps();`);
  assert.equal(snapshot().workflows.find(r=>r.id===long).steps[0].key,'A');
  assert(!snapshot().workflows.some(r=>r.recordingPartOf===long));
  // Empty/stopped recordings and preview availability.
  evaluate(`openRecorder(${JSON.stringify(long)});rec.on=true;rec.events=[[0,'down','key','W'],[750,'up','key','W']];refreshRec();`);
  assert(w.document.querySelector('#recJson').disabled);evaluate('stopRec()');assert(!w.document.querySelector('#recJson').disabled);
  w.document.querySelector('#recJson').click();const recording=JSON.parse(jsonText.value);assert.equal(recording.randomizedDelay,false);assert.equal(recording.layers[0].keys[0].steps[1].ms,750);evaluate('closeJsonPreview()');
  w.document.querySelector('#recJson').click();
  assert.match(w.document.querySelector('#jsonTimingRanges').textContent,/layers\[0\]\.keys\[0\]\.steps\[1\]\.ms/);
  assert.match(w.document.querySelector('#jsonTimingRanges').textContent,/±6 ms · 744–756 ms/);
  evaluate('closeJsonPreview()');
  w.document.querySelector('#recClear').click();assert(w.document.querySelector('#recJson').disabled);
  evaluate('closeRecorder()');
  // Failed imports/storage capacity leave data intact.
  const beforeBad=snapshot();assert.throws(()=>evaluate(`importRecordingObject({steps:[{type:'delay',ms:-1}]})`));assert.deepEqual(snapshot(),beforeBad);
  evaluate(`while(cfg.workflows.length<64)cfg.workflows.push({id:'filler-'+cfg.workflows.length,name:'filler',kind:'nano',steps:[]});`);
  const full=snapshot();assert.throws(()=>evaluate(`storeRecording(cfg.workflows.find(r=>r.id===${JSON.stringify(long)}),Array.from({length:500},()=>({type:'delay',ms:1})))`));assert.deepEqual(snapshot(),full);
  // Shipped preset shows one recording, not its five storage parts.
  const preset=JSON.parse(fs.readFileSync(path.join(__dirname,'../data/macros.json'),'utf8'));
  evaluate(`cfg=${JSON.stringify(preset)};selectedWorkflow=null;selLayer=0;selKey=0;normalize();renderLayers();renderGrid();renderEditor();renderRecordings();`);
  assert.equal(w.document.querySelectorAll('.recording-card').length,1);
  assert.equal(w.document.querySelector('[aria-label="Playback mode"] [aria-checked="true"]').dataset.mode,'single');
  assert(!w.document.querySelector('#editor').textContent.match(/nano|micro|cooldown|‰/));
  assert.equal(evaluate('recordingSteps(recordingList()[0]).length'),989);
  // Existing execution log exports remain available.
  evaluate(`renderMacroLog({events:[{id:1,run:1,pass:1,step:1,type:'move',key:'LEFT',elapsedMs:0,durationMs:200,complete:true}],elapsedMs:200,running:false});`);
  w.document.querySelector('#exportLog').click();assert.equal(JSON.parse(jsonText.value).events[0].key,'LEFT');evaluate('closeJsonPreview()');
  // Layers can be deleted unless another button switches to them; later references shift down.
  evaluate(`cfg.layers.push({name:'Two',keys:[]},{name:'Three',keys:[]});normalize();cfg.layers[0].keys[5].steps=[{type:'layer',layer:2}];selLayer=1;renderLayers();`);
  w.document.querySelector('#layerDelete').click();
  assert.deepEqual(snapshot().layers.map(l=>l.name),[snapshot().layers[0].name,'Three']);
  assert.equal(snapshot().layers[0].keys[5].steps[0].layer,1);
  evaluate(`selLayer=1;renderLayers();`);w.document.querySelector('#layerDelete').click();
  assert.equal(snapshot().layers.length,2);assert.match(w.document.querySelector('#toast').textContent,/switches to or plays from this layer/);
  evaluate(`showTab('recordings')`);assert(w.document.querySelector('#panelRecordings').classList.contains('show'));
  // Dynamic presets use a settings dialog, not a low-level step editor.
  evaluate(`meta.keys.push('C','F1');`);
  w.document.querySelector('#newDynamic').click();assert(w.document.querySelector('#dynamicDialog').open);
  assert.equal(w.document.querySelector('#dynamicName').value,'Dynamic jump-attack');
  const chance=w.document.querySelector('[aria-label="Skill 1 chance after each set (%)"]');chance.value='35';chance.oninput();
  w.document.querySelector('#dynamicAddSkill').click();
  const h=w.document.querySelector('[aria-label="Skill 2 key"]');h.value='H';h.onchange();
  const hEnabled=w.document.querySelector('[aria-label="Enable skill 2"]');hEnabled.click();
  const cooldown=w.document.querySelector('[aria-label="Skill 2 minimum interval (minutes)"]');cooldown.value='5';cooldown.oninput();
  // Invalid fields leave the configuration unchanged and keep the draft open.
  const originalConfig=snapshot();
  const max=w.document.querySelector('[aria-label="Attacks per set maximum"]');max.value='1';max.oninput();
  w.document.querySelector('#dynamicApply').click();assert.match(w.document.querySelector('#dynamicError').textContent,/ordered range/);assert.deepEqual(snapshot(),originalConfig);
  max.value='10';max.oninput();w.document.querySelector('#dynamicApply').click();assert(!w.document.querySelector('#dynamicDialog').open);
  let dynamic=snapshot().workflows.find(r=>r.steps.length===1&&r.steps[0].type==='dynamic');assert(dynamic);
  assert.equal(dynamic.steps[0].pattern.skills.length,2);assert.equal(dynamic.steps[0].pattern.skills[0].chance,.35);
  assert.equal(dynamic.steps[0].pattern.skills[1].cooldown_ms,300000);
  assert.match(evaluate(`recordingSummary(cfg.workflows.find(r=>r.id===${JSON.stringify(dynamic.id)}))`),/Dynamic/);
  evaluate(`openStepEditor(${JSON.stringify(dynamic.id)});`);assert(w.document.querySelector('#dynamicDialog').open);assert(!w.document.querySelector('#editDialog').open);
  // One generated example preserves overlap order and establishes facing first.
  const example=JSON.parse(evaluate(`JSON.stringify((()=>{const p=JSON.parse(JSON.stringify(dynamicDraft));p.sets=[2,2];p.attacks_per_set=[2,2];p.turn_chance=1;p.skills[0].chance=1;p.skills[1].chance=0;return generateDynamicSample(p,()=>0);})())`));
  assert.equal(example.steps[0].key,'LEFT');
  const dirs=example.steps.filter(s=>s.type==='down'&&['LEFT','RIGHT'].includes(s.key)).map(s=>s.key);assert.deepEqual(dirs,['LEFT','RIGHT']); // no direction tap after the last set
  const edges=example.steps.filter(s=>s.mods?.length).map(s=>s.type+':'+s.mods[0]);
  assert.deepEqual(edges,Array.from({length:4},()=>['down:alt','down:ctrl','up:alt','up:ctrl']).flat());
  assert.equal(example.steps.filter(s=>s.type==='down'&&s.key==='C').length,4);
  assert(!example.steps.some(s=>s.key==='H'));
  w.document.querySelector('#dynamicPreview').click();assert(w.document.querySelector('#jsonDialog').open);
  assert.equal(w.document.querySelector('#jsonScope').value,'generated');assert(JSON.parse(jsonText.value).steps.length>1);
  evaluate('closeJsonPreview();closeDynamicEditor();');
  // Preview does not replace the live definition. Export/import retains it
  // while assigning fresh timer identities to an independent copy.
  assert.equal(snapshot().workflows.find(r=>r.id===dynamic.id).steps[0].type,'dynamic');
  evaluate(`selectedWorkflow=${JSON.stringify(dynamic.id)};openJsonPreview('selected');`);
  const live=JSON.parse(jsonText.value);assert.equal(live.steps[0].type,'dynamic');
  const importedId=evaluate(`importRecordingObject(${JSON.stringify(live)}).id`);
  assert.notEqual(snapshot().workflows.find(r=>r.id===importedId).steps[0].pattern.id,live.steps[0].pattern.id);
  // Presets exported before the batch -> set rename still import, under the new keys.
  const legacy=JSON.parse(JSON.stringify(live)),old=legacy.steps[0].pattern;
  old.combos_per_side=old.attacks_per_set;old.sides=old.sets;delete old.attacks_per_set;delete old.sets;
  const legacyId=evaluate(`importRecordingObject(${JSON.stringify(legacy)}).id`);
  const upgraded=snapshot().workflows.find(r=>r.id===legacyId).steps[0].pattern;
  assert.deepEqual(upgraded.sets,old.sides);assert.deepEqual(upgraded.attacks_per_set,old.combos_per_side);assert.equal(upgraded.sides,undefined);
  evaluate('closeJsonPreview();');
  // Pattern cancel/discard has the same protection as the recording editor.
  evaluate(`openDynamicEditor(${JSON.stringify(dynamic.id)});`);
  const name=w.document.querySelector('#dynamicName');name.value='Changed';name.oninput();w.confirm=()=>false;
  w.document.querySelector('#dynamicClose').click();assert(w.document.querySelector('#dynamicDialog').open);
  w.confirm=()=>true;w.document.querySelector('#dynamicClose').click();assert(!w.document.querySelector('#dynamicDialog').open);
  dom.window.close();console.log('recordings and button assignment tests passed');
}
main().catch(e=>{dom.window.close();console.error(e);process.exitCode=1;});
