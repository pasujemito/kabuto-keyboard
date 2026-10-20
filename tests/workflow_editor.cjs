// Install jsdom outside the checkout; see tests/README.md.
const {JSDOM} = require('jsdom');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../data/index.html'), 'utf8');
const dom = new JSDOM(html, {runScripts: 'outside-only', url: 'http://kabuto.test'});
const w = dom.window;
let saved;
const requests=[];
w.confirm = () => true;
w.prompt = () => 'Walk forward';
w.fetch = async (url, options) => {
  requests.push(url);
  if(url === '/api/config') saved = JSON.parse(options.body);
  return {ok: true, json: async () => ({})};
};
const source = html.split('<script>')[1].split('</script>')[0];
w.eval(source.replace(/loadAll\(\)\.catch\([^\n]+/, '')+'\nwindow.testEval = code => eval(code);');
w.testEval(`meta={keyCount:6,maxLayers:8,keys:['A','W','H'],media:[]};
 cfg={version:1,layers:[{name:'Base',keys:[]}]};normalize();
 savedSnapshot=JSON.stringify(cfg);renderLayers();renderGrid();renderEditor();`);
const click = text => {
  const b = [...w.document.querySelectorAll('#editor button')].find(b => b.textContent === text);
  assert(b, `button ${text} exists`);b.click();
};
const edit = id => {
  const select = w.document.querySelector('[aria-label="Edit key or workflow"]');
  select.value = id;select.onchange();
};
const snapshot = () => JSON.parse(w.testEval('JSON.stringify(cfg)'));
async function main() {
  click('+ nano');
  click('+ Tap key');
  let cfg = snapshot();
  const nano = cfg.workflows[0].id;
  assert.equal(cfg.workflows[0].kind, 'nano');
  assert.equal(cfg.workflows[0].steps[0].type, 'key');
  w.prompt = () => 'Approach and attack';
  click('+ micro');
  click('+ Call workflow');
  const micro = snapshot().workflows[1].id;
  const call = w.document.querySelector('[aria-label="Workflow to call"]');
  call.value = nano;call.onchange();
  assert.equal(snapshot().workflows[1].steps[0].workflow, nano);
  edit('');
  click('+ Random workflow');
  let inputs = [...w.document.querySelectorAll('#editor input[type="checkbox"]')];
  // Default choices contain both workflows. Switch one off and on to exercise
  // identity preservation and rebuilding weight controls.
  const nanoCheckbox = inputs.find(i => i.parentNode.textContent.includes('nano · Walk forward'));
  assert(nanoCheckbox);nanoCheckbox.click();
  const unchecked = [...w.document.querySelectorAll('#editor input[type="checkbox"]')]
    .find(i => i.parentNode.textContent.includes('nano · Walk forward'));
  unchecked.click();
  const weight = [...w.document.querySelectorAll('#editor input[type="number"]')]
    .find(i => i.parentNode.textContent === 'weight');
  assert(weight);weight.value='7';weight.oninput();
  await w.testEval('save()');
  assert.equal(saved.layers[0].keys[0].steps[0].avoidRecent, 1);
  assert(saved.layers[0].keys[0].steps[0].choices.some(c => c.weight === 7));
  assert.equal(saved.workflows[1].steps[0].workflow, nano);
  assert.equal(saved.version, 2);
  // Deletion cannot strand workflow calls or random references.
  edit(nano);click('Delete workflow');
  assert.equal(snapshot().workflows.length, 2);
  assert.match(w.document.querySelector('#toast').textContent, /Remove calls/);
  // Recorder writes to the selected workflow, not the physical key.
  w.testEval(`rec.steps=[{type:'key',key:'H',hold:20}];useSteps();`);
  assert.equal(snapshot().workflows[0].steps[0].key, 'H');
  assert.equal(snapshot().layers[0].keys[0].steps[0].type, 'random');
  // Physical key selection switches back from the workflow editor.
  w.document.querySelectorAll('#grid .keycap')[1].click();
  assert.equal(w.document.querySelector('[aria-label="Edit key or workflow"]').value, '');
  // Existing JSON keeps the legacy layer/key choices through normalization.
  w.testEval(`cfg.layers[0].keys[1].steps=[{type:'random',choices:[{layer:0,key:0}]}];normalize();`);
  assert.deepEqual(snapshot().layers[0].keys[1].steps[0].choices, [{layer:0,key:0}]);
  // Preview/export never saves or changes the source configuration.
  w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
  w.HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new w.Event('close'));};
  edit(micro);
  const beforeExport=snapshot();
  const beforeRequests=requests.length;
  click('JSON / Export');
  assert(w.document.querySelector('#jsonDialog').open);
  const jsonText=w.document.querySelector('#jsonText');
  assert(jsonText.readOnly);
  assert.equal(JSON.parse(jsonText.value).steps[0].workflow,nano);
  assert.match(w.document.querySelector('#jsonHint').textContent,/references/);
  const scope=w.document.querySelector('#jsonScope');scope.value='config';scope.onchange();
  assert.deepEqual(JSON.parse(jsonText.value),beforeExport);
  let copied;
  w.navigator.clipboard={writeText:async value=>{copied=value;}};
  await w.testEval('copyJson()');
  assert.equal(copied,jsonText.value);
  // HTTP device pages may lack clipboard access: retain manual copy support.
  w.navigator.clipboard={writeText:async()=>{throw new Error('denied');}};
  await w.testEval('copyJson()');
  assert.equal(jsonText.selectionEnd,jsonText.value.length);
  assert.match(w.document.querySelector('#toast').textContent,/Copy command/);
  w.testEval('closeJsonPreview()');
  // Stop finalizes recorded transitions before enabling JSON export.
  w.testEval(`rec.on=true;rec.events=[[0,'down','key','W'],[750,'up','key','W']];refreshRec();`);
  assert(w.document.querySelector('#recJson').disabled);
  w.testEval('stopRec()');
  assert(!w.document.querySelector('#recJson').disabled);
  w.document.querySelector('#recJson').click();
  const recording=JSON.parse(jsonText.value);
  assert.equal(recording.randomizedDelay,false);
  assert.deepEqual(recording.layers[0].keys[0].steps,[{type:'down',key:'W'},{type:'delay',ms:750},{type:'up',key:'W'}]);
  let downloadedBlob,downloadedName;
  w.URL.createObjectURL=blob=>{downloadedBlob=blob;return 'blob:kabuto-test';};
  w.URL.revokeObjectURL=()=>{};
  w.HTMLAnchorElement.prototype.click=function(){downloadedName=this.download;};
  w.document.querySelector('#jsonDownload').click();
  assert.equal(downloadedName,'kabuto-recording.json');
  assert.equal(downloadedBlob.type,'application/json;charset=utf-8');
  const downloaded=await new Promise((resolve,reject)=>{const reader=new w.FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsText(downloadedBlob);});
  assert.deepEqual(JSON.parse(downloaded),recording);
  assert.deepEqual(snapshot(),beforeExport);
  // Only stopping recording sends a recording-status request; JSON actions do not.
  assert.deepEqual(requests.slice(beforeRequests),['/api/recording?active=0']);
  w.testEval('closeJsonPreview()');
  w.document.querySelector('#recClear').click();
  assert(w.document.querySelector('#recJson').disabled);
  dom.window.close();
  console.log('workflow editor tests passed');
}
main().catch(e => {dom.window.close();console.error(e);process.exitCode=1;});
