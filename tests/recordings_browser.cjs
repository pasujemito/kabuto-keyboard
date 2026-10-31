// Optional Chromium layout/interaction smoke test; no real device required.
const {chromium}=require('playwright-core');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{
  const page=await browser.newPage({viewport:{width:1280,height:900}}),errors=[];let truncateConfig=true;
  // Update API mock: one newer and one older signed release on the device's list.
  const updateState={current:'1.14.0',repo:'owner/kabuto',enabled:true,wifi:'HomeNet',state:'ready',error:'',progress:0,installing:'',checkedAgoS:120,rolledBack:'',
    releases:[{version:'1.15.0',date:'2026-11-02',newer:true},{version:'1.14.0',date:'2026-10-27',newer:false},{version:'1.13.0',date:'2026-10-20',newer:false}]};
  const updateRequests=[];let refuseInstall=false;
  // Home Wi-Fi and PIN mocks; pinRequired acts like a page opened over the home network.
  const networkState={ssid:'HomeNet',stay:false,connected:false,ip:'',address:'http://kabuto.local',error:'',pinSet:false,viaHotspot:true};
  const networkRequests=[];let pinRequired=false,loggedIn=false;
  let liveState=null,patternState=null;const statsRequests=[];   // live bars, as the status poll reports them
  page.on('pageerror',e=>errors.push(e.message));
  const html=fs.readFileSync(path.join(__dirname,'../web/index.html'),'utf8');
  const config=JSON.parse(fs.readFileSync(path.join(__dirname,'../data/macros.json'),'utf8'));
  const handler=async route=>{
   const url=new URL(route.request().url());
   if(url.hostname!=='kabuto.test')return route.abort();
   if(url.pathname==='/')return route.fulfill({contentType:'text/html',body:html});
   if(url.pathname==='/api/login'){
    loggedIn=route.request().postData()==='pin=246810';
    return route.fulfill({status:loggedIn?200:401,contentType:'application/json',body:JSON.stringify(loggedIn?{ok:true}:{ok:false,error:'Wrong PIN'})});
   }
   if(url.pathname.startsWith('/api/')&&pinRequired&&!loggedIn)return route.fulfill({status:401,contentType:'application/json',body:'{"ok":false,"error":"PIN required"}'});
   if(url.pathname==='/api/network'&&route.request().method()==='POST'){networkRequests.push(route.request().postData());return route.fulfill({contentType:'application/json',body:'{"ok":true}'});}
   if(url.pathname==='/api/stats/reset'){statsRequests.push(url.pathname);return route.fulfill({contentType:'application/json',body:'{"ok":true}'});}
   if(url.pathname==='/api/status')return route.fulfill({contentType:'application/json',body:JSON.stringify({connected:false,bonds:0,lastKeyDown:-1,keyDownCount:0,keyMask:0,...(liveState?{live:liveState}:{}),...(patternState?{pattern:patternState}:{})})});
   if(url.pathname==='/api/network')return route.fulfill({contentType:'application/json',body:JSON.stringify(networkState)});
   if(url.pathname.startsWith('/api/update/')){
    updateRequests.push({path:url.pathname,version:url.searchParams.get('version'),body:route.request().postData()});
    if(url.pathname==='/api/update/install'&&refuseInstall)return route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({ok:false,error:'Stop playback or recording first'})});
    return route.fulfill({contentType:'application/json',body:'{"ok":true}'});
   }
   if(url.pathname==='/api/update')return route.fulfill({contentType:'application/json',body:JSON.stringify(updateState)});
   if(url.pathname==='/api/config'&&truncateConfig)return route.fulfill({contentType:'application/json',body:JSON.stringify(config).slice(0,20000)});
   const data=url.pathname==='/api/meta'?{firmware:'test',cols:3,rows:2,keyCount:6,maxLayers:8,keys:['A','C','W','H','F1','LEFT','RIGHT','Z','V','X','SPACE','D'],media:[]}:url.pathname==='/api/config'?config:url.pathname==='/api/log'?{events:[],elapsedMs:0,running:false}:url.pathname==='/api/storage'?{fsTotal:1441792,fsUsed:180224,configBytes:80719,maxConfig:262144,heapSize:327680,heapFree:122880,heapLargest:73728}:{connected:false,bonds:0,lastKeyDown:-1,keyDownCount:0,keyMask:0};
   return route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
  };
  await page.route('**/*',handler);
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
  // New patterns start Natural with HP on C and Mana on V, and no skill yet.
  assert.equal(await page.getByLabel('Tempo drift (%)',{exact:true}).inputValue(),'15');
  assert(await page.getByLabel('Enable HP',{exact:true}).isChecked());
  assert.equal(await page.getByLabel('HP key',{exact:true}).inputValue(),'C');assert.equal(await page.getByLabel('Mana key',{exact:true}).inputValue(),'V');
  assert.equal(await page.getByLabel('HP every (seconds) minimum',{exact:true}).inputValue(),'40');
  assert.equal(await page.getByLabel('HP drink below (%)',{exact:true}).inputValue(),'50');assert.equal(await page.getByLabel('Mana drink below (%)',{exact:true}).inputValue(),'30');
  await page.getByLabel('Mana drink below (%)',{exact:true}).fill('101');await page.getByRole('button',{name:'Apply pattern',exact:true}).click();
  assert.equal(await page.locator('#dynamicError').textContent(),'Mana drink below: enter a percentage from 0 to 100.');
  await page.getByLabel('Mana drink below (%)',{exact:true}).fill('25');
  // Real amounts: both or neither, per tap no more than the total.
  assert.equal(await page.getByLabel('HP bar total',{exact:true}).inputValue(),'0');
  await page.getByLabel('HP bar total',{exact:true}).fill('5000');await page.getByRole('button',{name:'Apply pattern',exact:true}).click();
  assert.equal(await page.locator('#dynamicError').textContent(),'HP amounts: set both the bar total and per tap (no more than the total), or both 0.');
  await page.getByLabel('HP per tap',{exact:true}).fill('800');
  // Screen awareness: on for new patterns; out-of-range values are refused.
  await page.locator('summary',{hasText:'Screen awareness'}).click();
  assert.equal(await page.getByLabel('Turn at map edges (%)',{exact:true}).inputValue(),'12');
  assert.equal(await page.getByLabel('Stuck after (seconds)',{exact:true}).inputValue(),'20');
  assert(await page.getByLabel('Face mobs',{exact:true}).isChecked());
  await page.getByLabel('Turn at map edges (%)',{exact:true}).fill('50');await page.getByRole('button',{name:'Apply pattern',exact:true}).click();
  assert.equal(await page.locator('#dynamicError').textContent(),'Turn at map edges: enter a percentage from 0 to 40.');
  await page.getByLabel('Turn at map edges (%)',{exact:true}).fill('15');
  await page.getByLabel('Stuck after (seconds)',{exact:true}).fill('2');await page.getByRole('button',{name:'Apply pattern',exact:true}).click();
  assert.equal(await page.locator('#dynamicError').textContent(),'Stuck after: enter 0 (off) or 3 to 600 seconds.');
  await page.getByLabel('Stuck after (seconds)',{exact:true}).fill('30');
  // Smart mode: on with a 50% home range, 30% auto-pause, walking to mobs and
  // 280-650 ms strides for new patterns; out-of-range values are refused.
  assert(await page.getByLabel('Smart mode',{exact:true}).isChecked());
  assert.equal(await page.getByLabel('Home range (%)',{exact:true}).inputValue(),'50');
  await page.getByLabel('Home range (%)',{exact:true}).fill('60');await page.getByRole('button',{name:'Apply pattern',exact:true}).click();
  assert.equal(await page.locator('#dynamicError').textContent(),'Home range: enter a percentage from 0 to 50.');
  await page.getByLabel('Home range (%)',{exact:true}).fill('10');
  assert.equal(await page.getByLabel('Auto-pause (%)',{exact:true}).inputValue(),'30');
  assert(await page.getByLabel('Walk to mobs',{exact:true}).isChecked());
  assert.equal(await page.getByLabel('Walking strides (ms) minimum',{exact:true}).inputValue(),'280');
  await page.getByLabel('Auto-pause (%)',{exact:true}).fill('95');await page.getByRole('button',{name:'Apply pattern',exact:true}).click();
  assert.equal(await page.locator('#dynamicError').textContent(),'Auto-pause: enter a percentage from 0 to 90.');
  await page.getByLabel('Auto-pause (%)',{exact:true}).fill('25');
  await page.getByLabel('Walking strides (ms) minimum',{exact:true}).fill('20');await page.getByRole('button',{name:'Apply pattern',exact:true}).click();
  assert.equal(await page.locator('#dynamicError').textContent(),'Walking strides: enter an ordered range from 50 to 5000.');
  await page.getByLabel('Walking strides (ms) minimum',{exact:true}).fill('300');
  assert.equal(await page.locator('#dynamicSkills .dynamic-skill').count(),0);
  await page.getByRole('button',{name:'Add skill',exact:true}).click();
  assert.equal(await page.getByLabel('Skill 1 key',{exact:true}).inputValue(),'A');   // first key nothing else uses
  // Presets change movement/rhythm and keep skills.
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
  // Movement keys: Space jumps, X attacks; clashes are refused, and skills can't pick them.
  await page.locator('#dynamicKeysSummary').click();
  await page.getByLabel('Jump key',{exact:true}).selectOption('SPACE');await page.getByLabel('Attack key',{exact:true}).selectOption('SPACE');
  await page.getByRole('button',{name:'Apply pattern',exact:true}).click();
  assert.equal(await page.locator('#dynamicError').textContent(),'Jump and attack need different keys.');
  await page.getByLabel('Attack key',{exact:true}).selectOption('X');
  assert.equal(await page.locator('#dynamicKeysSummary').textContent(),'Keys · jump SPACE, attack X, turn LEFT/RIGHT');
  assert.equal(await page.getByLabel('Skill 1 key',{exact:true}).locator('option[value="SPACE"]').count(),0);
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
  assert(generated.steps.some(s=>s.key==='SPACE')&&generated.steps.some(s=>s.key==='X')&&!generated.steps.some(s=>s.mods?.length));
  assert(generated.steps.some(s=>s.type==='down'&&s.key==='C')&&generated.steps.some(s=>s.type==='down'&&s.key==='V'));   // HP and Mana fire
  await page.locator('#jsonClose').click();
  await page.getByRole('button',{name:'Apply pattern',exact:true}).click();
  assert.equal(await page.locator('#dynamicDialog[open]').count(),0);
  const dynamicCard=page.locator('.recording-card').filter({hasText:'Dynamic ·'});assert.equal(await dynamicCard.count(),1);
  await dynamicCard.getByRole('button',{name:'Edit',exact:true}).click();
  assert.equal(await page.getByLabel('Turn around after a set (%)',{exact:true}).inputValue(),'75');
  assert.equal(await page.getByLabel('Skill 1 chance after each set (%)',{exact:true}).inputValue(),'20');
  assert.equal(await page.getByLabel('Jump key',{exact:true}).inputValue(),'SPACE');
  assert.equal(await page.getByLabel('Turn at map edges (%)',{exact:true}).inputValue(),'15');assert.equal(await page.getByLabel('Stuck after (seconds)',{exact:true}).inputValue(),'30');assert.equal(await page.getByLabel('Mana key',{exact:true}).inputValue(),'V');
  await page.locator('#dynamicClose').click();
  // Updates: a newer release is announced; installing needs a confirmation.
  await page.locator('#tabRecordings').click();
  assert.equal(await page.locator('#updateSummary').textContent(),'Update available: v1.15.0');
  await page.locator('#updateSummary').click();
  assert.equal(await page.getByRole('button',{name:'Install v1.14.0'}).count(),0); // installed one has no button
  let dialogText='';page.once('dialog',d=>{dialogText=d.message();d.dismiss();});
  await page.getByRole('button',{name:'Install v1.15.0'}).click();
  assert.match(dialogText,/^Install v1\.15\.0\?/);assert(!updateRequests.some(r=>r.path==='/api/update/install'));
  page.once('dialog',d=>{dialogText=d.message();d.accept();});
  await page.getByRole('button',{name:'Install v1.13.0'}).click();
  await page.waitForFunction(()=>true);await page.waitForTimeout(100);
  assert.match(dialogText,/older than v1\.14\.0/);
  assert.deepEqual(updateRequests.filter(r=>r.path==='/api/update/install').map(r=>r.version),['1.13.0']);
  refuseInstall=true;page.once('dialog',d=>d.accept());
  await page.getByRole('button',{name:'Install v1.15.0'}).click();
  await page.locator('#toast.show.err').waitFor();assert.match(await page.locator('#toast').textContent(),/Stop playback/);
  // Live bars from the PC screen reader appear on the pad screen with XP rates.
  await page.locator('#tabKeys').click();
  assert.equal(await page.locator('#gridMode button.on').getAttribute('data-g'),'run');   // buttons play when tapped, until Edit
  assert(await page.locator('#liveStats').isHidden());
  liveState={hp:723,mana:400,xp:632,ageMs:500,fresh:true,xpPerHour:53,minutesToLevel:416,levels:1};
  await page.waitForFunction(()=>!document.querySelector('#liveStats').hidden);
  const liveText=await page.locator('#liveStats').textContent();
  assert.match(liveText,/HP72\.3%/);assert.match(liveText,/MP40%/);assert.match(liveText,/XP63\.2%/);
  assert.match(liveText,/\+5\.3%\/h · 0\.09%\/min · level in 6 h 56 min · 1 level up/);
  assert.equal(await page.locator('#liveStats .meter i').first().evaluate(e=>e.style.width),'72.3%');
  await page.getByRole('button',{name:'Reset XP rate'}).click();await page.waitForTimeout(100);assert.deepEqual(statsRequests,['/api/stats/reset']);
  // Death stops the pad: a red banner, plus your minimap position and a mob on the left.
  liveState={hp:0,mana:400,xp:632,x:420,y:700,mobs:1,stopped:'you died',ageMs:400,fresh:true,xpPerHour:-1,minutesToLevel:-1,levels:0};
  await page.waitForFunction(()=>document.querySelector('#liveStats .live-stop'));
  const deadText=await page.locator('#liveStats').textContent();
  assert.match(deadText,/⛔ Stopped: you died/);assert.match(deadText,/Map◀ 42%/);
  assert.equal(await page.locator('#liveStats .track i').evaluate(e=>e.style.left),'42%');
  // The dashboard while a smart pattern plays: what it's doing and facing, the
  // map, the mobs it sees (the nearest right one in reach, named) and home.
  liveState={hp:723,mana:400,xp:632,x:420,y:700,wx:1420,mobs:10,ml:1,mr:3,dl:192,dr:52,mob:'Blue_Snail',map:'Henesys',ageMs:300,fresh:true,xpPerHour:-1,minutesToLevel:-1,levels:0};
  patternState={smart:true,action:'attack',facing:'right',home:1300,homeOnMap:true,homeRange:100,peak:6};
  await page.waitForFunction(()=>document.querySelector('#liveStats .radar'));
  const dashText=await page.locator('#liveStats').textContent();
  assert.match(dashText,/⚔ Attacking/);assert.match(dashText,/Facing right ▶/);assert.match(dashText,/🗺 Henesys/);
  assert.match(dashText,/Target Blue Snail · right · 52% of reach \(in reach\)/);assert.match(dashText,/Seen 4 \(1 ◀ · ▶ 3\)/);assert.match(dashText,/Most lately 6/);
  assert.deepEqual(await page.locator('#liveStats .radar .mob').evaluateAll(ms=>ms.map(m=>[m.textContent,m.classList.contains('in')])),[['1',false],['3',true]]);
  assert.deepEqual(await page.locator('#liveStats .track .home').evaluate(e=>[e.style.left,e.style.width]),['20%','20%']);   // home 1300 on the map is 30% across the minimap, ±10%
  patternState={...patternState,action:'pause',facing:'left'};liveState={...liveState,mobs:8,ml:0,mr:1,dl:-1,dr:180,map:'-'};
  await page.waitForFunction(()=>/Auto-pause/.test(document.querySelector('#liveStats').textContent));
  const pauseText=await page.locator('#liveStats').textContent();
  assert.match(pauseText,/◀ Facing left/);assert.match(pauseText,/Map not taught/);assert.match(pauseText,/Nearest Blue Snail · right · 180% of reach/);
  // No mob readings (an untaught map): smart can't stop for mobs, and the dashboard says why.
  patternState={...patternState,action:'attack'};liveState={...liveState,mobs:0,ml:-1,mr:-1,dl:-1,dr:-1,mob:undefined,map:'-'};
  await page.waitForFunction(()=>/Mobs not counted/.test(document.querySelector('#liveStats').textContent));
  const blindText=await page.locator('#liveStats').textContent();
  assert.match(blindText,/⚠ Can't see mobs: attacking anyway/);assert.match(blindText,/this map isn't taught\. On it, press Which map \(F9\)/);
  assert.equal(await page.locator('#liveStats .radar').count(),0);
  liveState={...liveState,map:'Henesys'};
  await page.waitForFunction(()=>/no mob detection on this map/.test(document.querySelector('#liveStats').textContent));
  patternState={...patternState,smart:false};
  await page.waitForFunction(()=>/Smart off/.test(document.querySelector('#liveStats').textContent));
  assert.doesNotMatch(await page.locator('#liveStats').textContent(),/Can't see mobs/);
  patternState=null;
  liveState={hp:723,mana:-1,xp:-1,ageMs:12000,fresh:false,xpPerHour:-1,minutesToLevel:-1,levels:0};
  await page.waitForFunction(()=>document.querySelector('#liveStats').classList.contains('stale'));
  assert.match(await page.locator('#liveStats').textContent(),/stopped 12 s ago; potions use their timers/);
  assert.equal(await page.locator('#liveStats .live-row').count(),1);   // unread bars aren't shown
  liveState=null;await page.waitForFunction(()=>document.querySelector('#liveStats').hidden);
  await page.locator('#tabRecordings').click();
  // The screen reader's keys as pad buttons: a Setup and a Tune layer, ways
  // between them and back, and a free button on the current layer to get in.
  const layersBefore=await page.evaluate(()=>cfg.layers.length);
  await page.locator('#newSetupLayer').click();
  const layerKeys=i=>page.evaluate(i=>{const L=cfg.layers[i];return {name:L.name,keys:L.keys.map(k=>[k.name,cfg.workflows.find(w=>w.id===k.steps[0]?.workflow)?.steps[0]])};},i);
  assert.equal(await page.evaluate(()=>cfg.layers.length),layersBefore+2);
  assert.deepEqual(await layerKeys(layersBefore),{name:'MS🍁 Setup',keys:[['Mark (F8)',{type:'tool',key:'mark'}],['Skip (Esc)',{type:'tool',key:'skip'}],
    ['Which map (F9)',{type:'tool',key:'map'}],['Outlines (F10)',{type:'tool',key:'outlines'}],['Tune ▸',{type:'layer',layer:layersBefore+1}],['Back',{type:'layer',layer:0}]]});
  assert.deepEqual(await layerKeys(layersBefore+1),{name:'MS🍁 Tune',keys:[['Looser (F6)',{type:'tool',key:'looser'}],['Stricter (F7)',{type:'tool',key:'stricter'}],
    ['Outlines (F10)',{type:'tool',key:'outlines'}],['Hide layer (F11)',{type:'tool',key:'hide'}],['◂ Setup',{type:'layer',layer:layersBefore}],['Back',{type:'layer',layer:0}]]});
  assert.deepEqual(await page.evaluate(n=>cfg.layers[0].keys.filter(k=>k.name==='🍁 Setup').map(k=>cfg.workflows.find(w=>w.id===k.steps[0].workflow).steps[0]),layersBefore),[{type:'layer',layer:layersBefore}]);
  assert.match(await page.locator('#recordings').textContent(),/Screen reader key · Mark \(F8\)/);
  assert.match(await page.locator('#recordings').textContent(),/Screen reader key · Looser \(F6\)/);
  const toolCount=await page.evaluate(()=>cfg.workflows.filter(w=>w.steps[0]?.type==='tool').length);
  assert.equal(toolCount,7);
  if(await page.evaluate(()=>cfg.layers.length+2<=meta.maxLayers)){
    await page.locator('#newSetupLayer').click();   // again: the same recordings are reused
    assert.equal(await page.evaluate(()=>cfg.workflows.filter(w=>w.steps[0]?.type==='tool').length),7);
  }
  // Home Wi-Fi: typing survives a status refresh; a blank password keeps the saved one.
  await page.locator('#networkSummary').click();
  assert.match(await page.locator('#networkStatus').textContent(),/Saved: HomeNet\. Joined only to check for updates/);
  await page.getByLabel('Home Wi-Fi name').fill('OtherNet');
  await page.evaluate(()=>refreshNetwork());await page.waitForTimeout(100);
  assert.equal(await page.getByLabel('Home Wi-Fi name').inputValue(),'OtherNet');
  await page.getByRole('button',{name:'Save Wi-Fi'}).click();await page.waitForTimeout(100);
  assert.deepEqual(networkRequests,['ssid=OtherNet&stay=0']);
  // Staying connected needs a PIN; it's sent with the settings, never shown again.
  await page.getByLabel(/Stay connected/).check();
  await page.getByRole('button',{name:'Save Wi-Fi'}).click();
  await page.waitForFunction(()=>/Set a PIN to stay connected/.test(document.querySelector('#toast').textContent));
  await page.getByLabel('Access PIN',{exact:true}).fill('2468');await page.getByRole('button',{name:'Save Wi-Fi'}).click();
  await page.waitForFunction(()=>/at least 6 characters/.test(document.querySelector('#toast').textContent));
  assert.equal(networkRequests.length,1);
  await page.getByLabel('Access PIN',{exact:true}).fill('246810');await page.getByRole('button',{name:'Save Wi-Fi'}).click();await page.waitForTimeout(100);
  assert.equal(networkRequests[1],'ssid=OtherNet&stay=1&pin=246810');assert.equal(await page.getByLabel('Access PIN',{exact:true}).inputValue(),'');
  Object.assign(networkState,{ssid:'OtherNet',stay:true,connected:true,ip:'192.168.1.42',pinSet:true});
  await page.evaluate(()=>refreshNetwork());await page.waitForTimeout(100);
  assert.match(await page.locator('#networkStatus').textContent(),/Connected to OtherNet as 192\.168\.1\.42\. Open kabuto\.local/);
  assert.equal(await page.locator('#networkSummary').textContent(),'Home Wi-Fi · kabuto.local');
  // Over the home network the editor asks for the PIN, then loads.
  pinRequired=true;loggedIn=false;
  const remote=await browser.newPage({viewport:{width:390,height:844}});remote.on('pageerror',e=>errors.push(e.message));
  await remote.route('**/*',handler);await remote.goto('http://kabuto.test');
  await remote.locator('#pinDialog[open]').waitFor();
  await remote.keyboard.press('Escape');assert.equal(await remote.locator('#pinDialog[open]').count(),1);   // can't skip it
  await remote.getByLabel('Enter access PIN').fill('000000');await remote.getByRole('button',{name:'Unlock'}).click();
  await remote.waitForFunction(()=>document.querySelector('#pinError').textContent==='Wrong PIN');
  await remote.getByLabel('Enter access PIN').fill('246810');await remote.getByRole('button',{name:'Unlock'}).click();
  await remote.locator('#pinDialog[open]').waitFor({state:'detached'});
  await remote.locator('#tabRecordings').click();await remote.locator('.recording-card').first().waitFor();
  assert.equal(await remote.locator('#pinDialog[open]').count(),0);
  assert.deepEqual(errors,[]);console.log('desktop/mobile recordings browser tests passed');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
