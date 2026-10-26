// Optional Chromium layout/interaction smoke test; no real device required.
const {chromium}=require('playwright-core');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{
  const page=await browser.newPage({viewport:{width:1280,height:900}}),errors=[];let truncateConfig=true;
  page.on('pageerror',e=>errors.push(e.message));
  const html=fs.readFileSync(path.join(__dirname,'../data/index.html'),'utf8');
  const config=JSON.parse(fs.readFileSync(path.join(__dirname,'../data/macros.json'),'utf8'));
  await page.route('**/*',async route=>{
   const url=new URL(route.request().url());
   if(url.hostname!=='kabuto.test')return route.abort();
   if(url.pathname==='/')return route.fulfill({contentType:'text/html',body:html});
   if(url.pathname==='/api/config'&&truncateConfig)return route.fulfill({contentType:'application/json',body:JSON.stringify(config).slice(0,20000)});
   const data=url.pathname==='/api/meta'?{firmware:'test',cols:3,rows:2,keyCount:6,maxLayers:8,keys:['A','C','W','H','F1','LEFT','RIGHT','Z'],media:[]}:url.pathname==='/api/config'?config:url.pathname==='/api/log'?{events:[],elapsedMs:0,running:false}:url.pathname==='/api/storage'?{fsTotal:1441792,fsUsed:180224,configBytes:80719,maxConfig:262144,heapSize:327680,heapFree:122880,heapLargest:73728}:{connected:false,bonds:0,lastKeyDown:-1,keyDownCount:0,keyMask:0};
   return route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
  });
  // A truncated config (device low on memory) shows an error instead of an
  // empty editor, and recording reports why it can't start.
  await page.goto('http://kabuto.test');await page.locator('#loadError').waitFor();
  assert.match(await page.locator('#loadErrorText').textContent(),/incomplete data/);
  await page.getByRole('button',{name:'New recording',exact:true}).click();
  assert.equal(await page.locator('#sheet.show').count(),0);
  truncateConfig=false;await page.locator('#loadRetry').click();await page.locator('.recording-card').waitFor();
  assert(!(await page.locator('#loadError').isVisible()));
  assert.equal(await page.locator('#layerbar button b').first().textContent(),'0');
  const storage=await page.locator('#storage').textContent();
  assert.match(storage,/Recording slots6 of 64/);assert.match(storage,/Flash176 KB of 1\.4 MB/);assert.match(storage,/Device memory120 KB free/);
  assert.equal(await page.locator('.recording-card').count(),1);
  // The editor shows the whole recording across its hidden storage parts.
  const rows=page.locator('#stepList .step-row');
  // The shipped recording is on button 1, so it is locked until unlocked.
  assert(await page.locator('#recordings').getByRole('button',{name:'Edit',exact:true}).isDisabled());
  await page.locator('#recordings').getByRole('button',{name:'Unlock recording'}).click();
  await page.locator('#recordings').getByRole('button',{name:'Edit',exact:true}).click();await page.locator('#editDialog[open]').waitFor();
  assert.equal(await rows.count(),989);
  assert.match(await page.locator('#editSummary').textContent(),/^989 steps · 97\.9 s$/);
  assert.equal(await rows.nth(1).locator('.what').textContent(),'Press LEFT');
  await rows.first().click();
  await page.getByLabel('ms',{exact:true}).fill('1045');await page.getByLabel('ms',{exact:true}).press('Tab');
  assert.match(await page.locator('#editSummary').textContent(),/98\.9 s · unapplied changes/);
  assert.equal(await rows.nth(1).locator('.at').textContent(),'1.05s');
  await page.getByRole('button',{name:'+ Delay after',exact:true}).click();assert.equal(await rows.count(),990);
  assert(await rows.nth(1).evaluate(e=>e.classList.contains('sel')));
  await page.getByRole('button',{name:'Delete',exact:true}).last().click();assert.equal(await rows.count(),989);
  // Escape with unapplied changes asks first; dismissing keeps the editor open.
  await page.keyboard.press('Escape');assert(await page.locator('#editDialog[open]').isVisible());
  await page.getByRole('button',{name:'Apply changes',exact:true}).click();
  assert(!(await page.locator('#editDialog[open]').count()));
  assert.match(await page.locator('.recording-card .hint').textContent(),/989 steps · 98\.9 s/);
  assert.match(await page.locator('#storage').textContent(),/Recording slots6 of 64/);
  await page.locator('#recordings').getByRole('button',{name:'Edit',exact:true}).click();
  assert.equal(await rows.first().locator('.what').textContent(),'Wait 1045 ms');
  await page.locator('#editClose').click();assert(!(await page.locator('#editDialog[open]').count()));
  assert(await page.locator('#panelRecordings').isVisible());assert(await page.locator('#panelEdit').isVisible());
  await page.getByRole('button',{name:'Add to button',exact:true}).click();
  assert.equal(await page.locator('[aria-label="Playback mode"] [aria-checked="true"]').getAttribute('data-mode'),'sequence');
  await page.getByRole('radio',{name:'Random choice'}).click();
  // Repeated sequence entries become one unique random candidate.
  assert.equal(await page.locator('.assignment-list li').count(),1);
  await page.screenshot({path:'/tmp/kabuto-recordings-desktop.png'});
  await page.setViewportSize({width:390,height:844});
  // Phone pad: three evenly sized, roughly square buttons per row.
  await page.locator('#tabKeys').click();
  const caps=await page.locator('#grid .keycap').evaluateAll(cs=>cs.map(c=>c.getBoundingClientRect()).map(r=>({w:Math.round(r.width),h:Math.round(r.height),y:Math.round(r.y)})));
  assert.equal(caps.length,6);assert(caps.every(c=>c.w>=100&&Math.abs(c.w-caps[0].w)<=1&&Math.abs(c.h-c.w)<=1));
  assert.equal(new Set(caps.map(c=>c.y)).size,2);
  await page.screenshot({path:'/tmp/kabuto-pad-mobile.png'});
  await page.locator('#tabRecordings').click();assert(await page.locator('#panelRecordings').isVisible());assert(!(await page.locator('#panelEdit').isVisible()));
  await page.screenshot({path:'/tmp/kabuto-recordings-mobile.png'});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.locator('#recordings').getByRole('button',{name:'Edit',exact:true}).click();await page.locator('#editDialog[open]').waitFor();
  const dialog=await page.locator('#editDialog').boundingBox();assert(dialog.x>=0&&dialog.x+dialog.width<=390);
  await page.screenshot({path:'/tmp/kabuto-editor-mobile.png'});
  await page.locator('#editClose').click();
  await page.getByRole('button',{name:'New recording',exact:true}).click();await page.locator('#sheet.show').waitFor();
  assert.equal(await page.locator('#recUse').textContent(),'Save recording');
  await page.locator('.sheet-head .close').click();
  await page.locator('#tabEdit').click();assert(await page.getByRole('radiogroup',{name:'Playback mode'}).isVisible());
  const bounds=await page.locator('.tabbar').boundingBox();assert(bounds.y+bounds.height<=845);
  // The dynamic editor stays in the recording library and fits a phone.
  await page.locator('#tabRecordings').click();
  await page.getByRole('button',{name:'Dynamic pattern',exact:true}).click();
  await page.locator('#dynamicDialog[open]').waitFor();
  await page.getByLabel('Dynamic pattern name').fill('Jump combat varied');
  // New patterns start Natural; presets change movement/rhythm and keep skills.
  assert.equal(await page.getByLabel('Tempo drift (%)',{exact:true}).inputValue(),'15');
  await page.getByLabel('Skill 1 chance after each set (%)',{exact:true}).fill('35');
  await page.getByRole('button',{name:'Flip',exact:true}).click();
  assert.equal(await page.getByLabel('Attacks per set maximum',{exact:true}).inputValue(),'3');
  assert.equal(await page.getByLabel('Turn around after a set (%)',{exact:true}).inputValue(),'95');
  assert.match(await page.locator('#dynamicPresetHint').textContent(),/^Flip: Turns often/);
  assert.equal(await page.getByLabel('Skill 1 chance after each set (%)',{exact:true}).inputValue(),'35');
  await page.getByRole('button',{name:'Smooth',exact:true}).click();
  assert.equal(await page.getByLabel('Gap after attack (ms) minimum',{exact:true}).inputValue(),'580');
  await page.getByRole('button',{name:'Natural',exact:true}).click();
  assert.equal(await page.getByLabel('Attacks per set maximum',{exact:true}).inputValue(),'10');
  await page.getByLabel('Turn around after a set (%)',{exact:true}).fill('75');
  await page.getByLabel('Skill 1 chance after each set (%)',{exact:true}).fill('20');
  await page.getByRole('button',{name:'Add skill',exact:true}).click();
  await page.getByLabel('Skill 2 key',{exact:true}).selectOption('H');
  const dynamicBounds=await page.locator('#dynamicDialog').boundingBox();assert(dynamicBounds.x>=0&&dynamicBounds.x+dynamicBounds.width<=390);
  assert(await page.locator('#dynamicDialog').evaluate(d=>d.scrollWidth<=d.clientWidth));
  await page.screenshot({path:'/tmp/kabuto-dynamic-mobile.png'});
  await page.getByRole('button',{name:'Preview example JSON',exact:true}).click();
  await page.locator('#jsonDialog[open]').waitFor();
  const generated=JSON.parse(await page.locator('#jsonText').inputValue());assert(generated.steps.length>1&&generated.steps[0].key);
  await page.locator('#jsonClose').click();
  await page.getByRole('button',{name:'Apply pattern',exact:true}).click();
  assert.equal(await page.locator('#dynamicDialog[open]').count(),0);
  const dynamicCard=page.locator('.recording-card').filter({hasText:'Dynamic ·'});assert.equal(await dynamicCard.count(),1);
  await dynamicCard.getByRole('button',{name:'Edit',exact:true}).click();
  assert.equal(await page.getByLabel('Turn around after a set (%)',{exact:true}).inputValue(),'75');
  assert.equal(await page.getByLabel('Skill 1 chance after each set (%)',{exact:true}).inputValue(),'20');
  await page.locator('#dynamicClose').click();
  assert.deepEqual(errors,[]);console.log('desktop/mobile recordings browser tests passed');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
