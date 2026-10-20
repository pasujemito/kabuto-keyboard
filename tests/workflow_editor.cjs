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
const click=(selector,text)=>{const b=[...w.document.querySelectorAll(selector+' button')].find(b=>b.textContent===text);assert(b,`button ${text} exists`);b.click();};
const selectMode=value=>{const select=w.document.querySelector('[aria-label="Playback mode"]');assert(select);select.value=value;select.onchange();};
evaluate(`meta={keyCount:6,maxLayers:8,keys:['A','W','H','LEFT','RIGHT','Z'],media:[]};cfg={version:1,layers:[{name:'Base',keys:[]}]};normalize();savedSnapshot=JSON.stringify(cfg);renderLayers();renderGrid();renderEditor();renderRecordings();`);
async function main(){
  assert(!w.document.querySelector('#editor').textContent.match(/nano|micro|cooldown|‰/));
  const first=evaluate(`importRecordingObject({name:'Walk',steps:[{type:'down',key:'W'},{type:'delay',ms:300},{type:'up',key:'W'}]}).id`);
  const second=evaluate(`importRecordingObject({name:'Attack',steps:[{type:'down',mods:['ctrl']},{type:'delay',ms:150},{type:'up',mods:['ctrl']}]}).id`);
  assert.equal(w.document.querySelectorAll('.recording-card').length,2);
  evaluate(`addRecordingToButton(${JSON.stringify(first)});addRecordingToButton(${JSON.stringify(second)});`);
  let key=snapshot().layers[0].keys[0];assert.equal(key.playbackMode,'sequence');assert.deepEqual(key.steps.map(s=>s.workflow),[first,second]);
  click('#editor','↑');key=snapshot().layers[0].keys[0];assert.deepEqual(key.steps.map(s=>s.workflow),[first,second]); // first up is disabled
  w.document.querySelector('[aria-label="Move recording down"]').click();
  assert.deepEqual(snapshot().layers[0].keys[0].steps.map(s=>s.workflow),[second,first]);
  selectMode('random');key=snapshot().layers[0].keys[0];assert.equal(key.steps[0].type,'random');assert.equal(key.steps[0].choices.length,2);
  const repeat=w.document.querySelector('#editor input[type="checkbox"]');repeat.click();assert.equal(snapshot().layers[0].keys[0].steps[0].avoidRecent,1);
  selectMode('sequence');assert.deepEqual(snapshot().layers[0].keys[0].steps.map(s=>s.workflow),[second,first]);
  w.confirm=()=>false;selectMode('single');assert.equal(snapshot().layers[0].keys[0].steps.length,2);
  w.confirm=()=>true;selectMode('single');assert.equal(snapshot().layers[0].keys[0].steps[0].workflow,second);
  await evaluate('save()');assert.equal(saved.layers[0].keys[0].playbackMode,'single');
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
  assert.equal(w.document.querySelector('[aria-label="Playback mode"]').value,'single');
  assert(!w.document.querySelector('#editor').textContent.match(/nano|micro|cooldown|‰/));
  assert.equal(evaluate('recordingSteps(recordingList()[0]).length'),989);
  // Existing execution log exports remain available.
  evaluate(`renderMacroLog({events:[{id:1,run:1,pass:1,step:1,type:'move',key:'LEFT',elapsedMs:0,durationMs:200,complete:true}],elapsedMs:200,running:false});`);
  w.document.querySelector('#exportLog').click();assert.equal(JSON.parse(jsonText.value).events[0].key,'LEFT');evaluate('closeJsonPreview()');
  evaluate(`showTab('recordings')`);assert(w.document.querySelector('#panelRecordings').classList.contains('show'));
  dom.window.close();console.log('recordings and button assignment tests passed');
}
main().catch(e=>{dom.window.close();console.error(e);process.exitCode=1;});
