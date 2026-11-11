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
  const networkState={ssid:'HomeNet',stay:false,connected:false,ip:'',address:'http://kabuto.local',error:'',pinSet:false,viaHotspot:true,uptimeS:11100,heapFree:150000,heapLargest:70000};
  const networkRequests=[];let pinRequired=false,loggedIn=false;
  let liveState=null,patternState=null,noticeState=null,pinnedState=null;const statsRequests=[],noticeRequests=[],homeRequests=[];   // live bars, as the status poll reports them
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
   if(url.pathname==='/api/home/set'){homeRequests.push(url.pathname);pinnedState={home:liveState.wx??liveState.x,onMap:liveState.wx!==undefined,map:liveState.map};return route.fulfill({contentType:'application/json',body:'{"ok":true}'});}
   if(url.pathname==='/api/home/clear'){homeRequests.push(url.pathname);pinnedState=null;return route.fulfill({contentType:'application/json',body:'{"ok":true}'});}
   if(url.pathname==='/api/notices/clear'){noticeRequests.push(url.pathname);noticeState=null;return route.fulfill({contentType:'application/json',body:'{"ok":true}'});}
   if(url.pathname==='/api/status')return route.fulfill({contentType:'application/json',body:JSON.stringify({connected:false,bonds:0,lastKeyDown:-1,keyDownCount:0,keyMask:0,...(liveState?{live:liveState}:{}),...(patternState?{pattern:patternState}:{}),...(noticeState?{notices:noticeState}:{}),...(pinnedState?{pinnedHome:pinnedState}:{})})});
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
  assert.equal(await page.getByLabel('Face mobs',{exact:true}).count(),0);   // mobs in reach are always faced now: no switch
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
  assert.equal(await page.getByLabel('Walking: hop every (ms) minimum',{exact:true}).inputValue(),'600');
  await page.getByLabel('Auto-pause (%)',{exact:true}).fill('95');await page.getByRole('button',{name:'Apply pattern',exact:true}).click();
  assert.equal(await page.locator('#dynamicError').textContent(),'Auto-pause: enter a percentage from 0 to 90.');
  await page.getByLabel('Auto-pause (%)',{exact:true}).fill('25');
  await page.getByLabel('Walking: hop every (ms) minimum',{exact:true}).fill('20');await page.getByRole('button',{name:'Apply pattern',exact:true}).click();
  assert.equal(await page.locator('#dynamicError').textContent(),'Walking hops: enter an ordered range from 50 to 5000.');
  await page.getByLabel('Walking: hop every (ms) minimum',{exact:true}).fill('300');
  assert.equal(await page.locator('#dynamicSkills .dynamic-skill').count(),0);
  // Every setting explains itself in plain words, shows its default and goes back to it.
  assert.match(await page.locator('#dynamicHome').textContent(),/Distance boundary from home \(% of map width\).*Smart on or off\..*0%: disabled.*20%: narrow \(use on platforms\).*50%: wide \(use on flat ground\).*Default: 50%/s);
  assert.equal(await page.locator('#dynamicHome .setting-points li').count(),3);
  // Tap a value instead of typing: the bullet sets it, and is marked as the current one.
  await page.locator('#dynamicHome .setting-points li',{hasText:'20%: narrow'}).click();
  assert.equal(await page.getByLabel('Home range (%)',{exact:true}).inputValue(),'20');
  assert(await page.locator('#dynamicHome .setting-points li',{hasText:'20%: narrow'}).evaluate(e=>e.classList.contains('on')));
  assert.equal(await page.locator('#dynamicHome .setting-points li.on').count(),1);
  assert.equal(await page.locator('#dynamicHome input.slider').inputValue(),'20');   // the slider follows
  await page.locator('#dynamicHome input.slider').fill('35');
  assert.equal(await page.getByLabel('Home range (%)',{exact:true}).inputValue(),'35');
  assert.equal(await page.locator('#dynamicHome .setting-points li.on').count(),0);
  await page.locator('.setting[data-key="attacks_per_set"] .setting-points li',{hasText:'4–7'}).click();   // a range: both ends
  assert.equal(await page.getByLabel('Attacks per set minimum',{exact:true}).inputValue(),'4');assert.equal(await page.getByLabel('Attacks per set maximum',{exact:true}).inputValue(),'7');
  await page.locator('.setting[data-key="smart"] .setting-points li',{hasText:'off: attacks all the time'}).click();
  assert(!(await page.getByLabel('Smart mode',{exact:true}).isChecked()));
  await page.locator('.setting[data-key="smart"] .setting-points li',{hasText:'on: attacks only'}).click();
  assert(await page.getByLabel('Smart mode',{exact:true}).isChecked());
  // Fields are 16 px or more, so phones don't zoom in on them.
  assert(await page.locator('#dynamicDialog').evaluate(d=>[...d.querySelectorAll('input:not([type=checkbox]):not([type=range]),select')].every(e=>parseFloat(getComputedStyle(e).fontSize)>=16)));
  await page.getByLabel('Home range (%)',{exact:true}).fill('10');
  // Not driven right now (no screen reader readings here): greyed out, saying why.
  assert(await page.locator('#dynamicHome .setting[data-key="home_range"]').evaluate(e=>e.classList.contains('unused')));
  assert.match(await page.locator('#dynamicHome .unused-note').textContent(),/no readings from the PC screen reader/);
  assert.match(await page.locator('.setting[data-key="dir_hold"] .unused-note').textContent(),/turns happen in the air/);
  await page.getByLabel('Move while attacking (%)',{exact:true}).fill('0');
  assert.equal(await page.locator('.setting[data-key="dir_hold"] .unused-note').textContent(),'');   // tap turns are used again
  await page.getByRole('button',{name:'Default for Move while attacking',exact:true}).click();
  await page.getByLabel('Smart mode',{exact:true}).uncheck();
  assert.match(await page.locator('.setting[data-key="approach"] .unused-note').textContent(),/no readings|Smart is off/);
  assert.equal(await page.getByLabel('Home range (%)',{exact:true}).inputValue(),'10');
  await page.getByRole('button',{name:'Default for Home range',exact:true}).click();
  assert.equal(await page.getByLabel('Home range (%)',{exact:true}).inputValue(),'50');
  await page.getByRole('button',{name:'Default for Walking: hop every',exact:true}).click();
  assert.equal(await page.getByLabel('Walking: hop every (ms) minimum',{exact:true}).inputValue(),'600');
  await page.getByLabel('Smart mode',{exact:true}).uncheck();await page.getByRole('button',{name:'Default for Smart mode',exact:true}).click();
  assert(await page.getByLabel('Smart mode',{exact:true}).isChecked());
  assert.match(await page.locator('#dynamicMain').textContent(),/Move while attacking \(% of runs\).*0%: off: attacks on the spot.*100%: always on the move.*Default: 60%/s);
  assert.match(await page.locator('#dynamicMain').textContent(),/How often it flips direction \(%\).*0%: always faces the same way.*20%: occasionally flips sides/s);
  assert.match(await page.locator('#dynamicAware').textContent(),/10%: turns 10% from each edge: uses the middle 80% of the map/);
  // Attack off: support only. Everything about fighting greys out and says so; potions and skills don't.
  assert(await page.getByLabel('Attack',{exact:true}).isChecked());
  await page.getByLabel('Attack',{exact:true}).uncheck();
  assert.match(await page.locator('.setting[data-key="attacks_per_set"] .unused-note').textContent(),/Attack is off \(support only/);
  assert.match(await page.locator('.setting[data-key="smart"] .unused-note').textContent(),/Attack is off/);
  assert.equal(await page.locator('.setting[data-key="skill.chance"].unused').count(),0);
  assert.match(await page.locator('#dynamicMain').textContent(),/off: support only: never jumps, attacks or moves/);
  await page.getByRole('button',{name:'Default for Attack',exact:true}).click();
  assert(await page.getByLabel('Attack',{exact:true}).isChecked());
  assert.equal(await page.locator('.setting[data-key="attacks_per_set"] .unused-note').textContent(),'');
  assert.match(await page.locator('#dynamicPotions').textContent(),/HP drink below.*0%: ignores the bar.*Default: 50%/s);
  await page.getByLabel('Mana drink below (%)',{exact:true}).fill('70');await page.getByRole('button',{name:'Default for Mana drink below',exact:true}).click();
  assert.equal(await page.getByLabel('Mana drink below (%)',{exact:true}).inputValue(),'30');
  await page.getByLabel('Home range (%)',{exact:true}).fill('10');await page.getByLabel('Walking: hop every (ms) minimum',{exact:true}).fill('300');
  await page.getByLabel('Mana drink below (%)',{exact:true}).fill('25');
  await page.getByRole('button',{name:'Add skill',exact:true}).click();
  assert.equal(await page.getByLabel('Skill 1 key',{exact:true}).inputValue(),'A');   // first key nothing else uses
  await page.getByLabel('Skill 1 chance after each set (%)',{exact:true}).fill('80');
  await page.getByRole('button',{name:'Default for Skill 1 chance',exact:true}).click();
  assert.equal(await page.getByLabel('Skill 1 chance after each set (%)',{exact:true}).inputValue(),'10');
  if(process.env.SHOT)await page.locator('#dynamicDialog').screenshot({path:process.env.SHOT});
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
  // Backup potion keys: none by default; the same key twice is refused; one is kept.
  await page.locator('#dynamicPotions').evaluate(e=>e.closest('details').open=true);
  assert.equal(await page.getByLabel('HP backup key 1',{exact:true}).inputValue(),'');
  await page.getByLabel('HP backup key 1',{exact:true}).selectOption('D');await page.getByLabel('HP backup key 2',{exact:true}).selectOption('D');
  await page.getByRole('button',{name:'Apply pattern',exact:true}).click();
  assert.equal(await page.locator('#dynamicError').textContent(),'HP backup keys: each must be a different key.');
  await page.getByLabel('HP backup key 2',{exact:true}).selectOption('');
  await page.getByLabel('HP backup key 1 restored per tap',{exact:true}).fill('300');   // a weaker potion than the main one
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
  assert.equal(await page.getByLabel('HP backup key 1',{exact:true}).inputValue(),'D');assert.equal(await page.getByLabel('HP backup key 2',{exact:true}).inputValue(),'');
  assert.deepEqual(await page.evaluate(()=>cfg.workflows.find(w=>w.steps[0]?.type==='dynamic').steps[0].pattern.potions.map(x=>x.backup_keys)),[[{key:'D',per_tap:300}],[]]);
  assert.equal(await page.getByLabel('HP backup key 1 restored per tap',{exact:true}).inputValue(),'300');
  assert.equal(await page.getByLabel('Turn at map edges (%)',{exact:true}).inputValue(),'15');assert.equal(await page.getByLabel('Stuck after (seconds)',{exact:true}).inputValue(),'30');assert.equal(await page.getByLabel('Mana key',{exact:true}).inputValue(),'V');
  await page.locator('#dynamicClose').click();
  // Characters: keys, HP & Mana and skills set once and used by patterns.
  await page.locator('#tabRecordings').click();
  assert.match(await page.locator('#characters').textContent(),/set once per character/);
  await page.getByRole('button',{name:/^Make one from/}).click();
  assert.equal(await page.evaluate(()=>cfg.characters.length),1);
  assert.equal(await page.evaluate(()=>cfg.active_character===cfg.characters[0].id),true);
  assert.deepEqual(await page.evaluate(()=>{const p=dynamicPatterns()[0];return [p.char_keys,p.char_potions,p.char_skills];}),[true,true,true]);   // the same ones: used from now on
  assert.equal(await page.locator('#charactersSummary').textContent(),'Characters · Character 1');
  // Edit it: only Keys, HP & Mana and Skills show.
  await page.getByRole('button',{name:'Edit character Character 1',exact:true}).click();
  assert.equal(await page.locator('#dynamicTitle').textContent(),'Edit character');
  assert(await page.locator('#dynamicMain').isHidden());assert(await page.locator('#dynamicHome').isHidden());
  assert.equal(await page.getByRole('button',{name:'Save character',exact:true}).count(),1);
  await page.locator('#dynamicPotions').evaluate(e=>e.closest('details').open=true);
  await page.getByLabel('HP key',{exact:true}).selectOption('W');
  await page.getByLabel('Character name',{exact:true}).fill('Warrior');
  await page.getByRole('button',{name:'Save character',exact:true}).click();
  assert.equal(await page.locator('#dynamicDialog[open]').count(),0);
  assert.equal(await page.evaluate(()=>cfg.characters[0].name+' '+cfg.characters[0].potions.find(x=>x.id==='hp').key),'Warrior W');
  // The pattern uses it: its own HP & Mana are hidden, the character's are summarised.
  await page.locator('.recording-card').filter({hasText:'Dynamic ·'}).getByRole('button',{name:'Edit',exact:true}).click();
  assert(await page.getByLabel("Use the character's HP & Mana",{exact:true}).isChecked());
  assert(await page.locator('#dynamicPotions').isHidden());
  assert.match(await page.locator('.char-use[data-part="potions"]').textContent(),/Use Warrior's HP & Mana.*HP W/s);
  await page.getByLabel("Use the character's HP & Mana",{exact:true}).uncheck();
  assert(await page.locator('#dynamicPotions').isVisible());
  await page.getByLabel("Use the character's HP & Mana",{exact:true}).check();
  await page.getByRole('button',{name:'Apply pattern',exact:true}).click();
  assert.equal(await page.locator('#dynamicDialog[open]').count(),0);
  // A second character, made active; then deleted again.
  await page.locator('#tabRecordings').click();
  await page.getByRole('button',{name:'Add character',exact:true}).click();
  assert.equal(await page.locator('#dynamicTitle').textContent(),'New character');
  await page.getByLabel('Character name',{exact:true}).fill('Mage');
  await page.getByRole('button',{name:'Save character',exact:true}).click();
  assert.equal(await page.evaluate(()=>cfg.characters.map(c=>c.name).join()),'Warrior,Mage');
  await page.getByLabel('Active character: Mage',{exact:true}).check();
  assert.equal(await page.locator('#charactersSummary').textContent(),'Characters · Mage');
  page.once('dialog',d=>d.accept());
  await page.getByRole('button',{name:'Delete character Mage',exact:true}).click();
  assert.equal(await page.locator('#charactersSummary').textContent(),'Characters · Warrior');
  await page.locator('#tabKeys').click();
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
  // Check now: "Checking GitHub…" at once, even before the pad says it started, and the
  // result shows as soon as it's in (not at the next 30 s refresh).
  refuseInstall=false;
  await page.getByRole('button',{name:'Check now'}).click();
  assert.match(await page.locator('#updateStatus').textContent(),/Checking GitHub…/);
  assert(updateRequests.some(r=>r.path==='/api/update/check'));
  await page.waitForTimeout(1500);
  assert.match(await page.locator('#updateStatus').textContent(),/Checking GitHub…/);   // the pad hasn't picked it up yet: still following
  updateState.state='checking';await page.waitForTimeout(1700);
  updateState.state='ready';updateState.checkedAgoS=0;updateState.releases.unshift({version:'1.16.0',date:'2026-11-04',newer:true});
  await page.waitForFunction(()=>/Checked just now/.test(document.querySelector('#updateStatus').textContent),null,{timeout:4000});
  assert.equal(await page.locator('#updateSummary').textContent(),'Update available: v1.16.0');
  updateState.releases.shift();updateState.checkedAgoS=120;
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
  liveState={hp:723,mana:400,xp:632,x:420,y:700,wx:1420,mobs:10,ml:1,mr:3,ir:1,dl:192,dr:52,mob:'Blue_Snail',map:'Henesys',ageMs:300,fresh:true,xpPerHour:-1,minutesToLevel:-1,levels:0};
  patternState={smart:true,action:'attack',facing:'right',home:1300,homeOnMap:true,homeRange:100,peak:6};
  await page.waitForFunction(()=>document.querySelector('#liveStats .radar'));
  const dashText=await page.locator('#liveStats').textContent();
  assert.match(dashText,/⚔ In reach 1 \(4\)/);assert.match(dashText,/In reach 1 of 4/);   // in reach first, all seen in brackets
  assert.match(dashText,/⚔ Attacking/);assert.match(dashText,/Facing right ▶/);assert.match(dashText,/🗺 Henesys/);
  assert.match(dashText,/Target Blue Snail · right · 52% of reach \(in reach\)/);assert.match(dashText,/Seen 4 \(1 ◀ · ▶ 3\)/);assert.match(dashText,/Most lately 6/);
  assert.deepEqual(await page.locator('#liveStats .radar .mob').evaluateAll(ms=>ms.map(m=>[m.textContent,m.classList.contains('in')])),[['1',false],['3',true]]);
  assert.deepEqual(await page.locator('#liveStats .track .home').evaluate(e=>[e.style.left,e.style.width]),['20%','20%']);   // home 1300 on the map is 30% across the minimap, ±10%
  patternState={...patternState,action:'pause',facing:'left'};liveState={...liveState,mobs:8,ml:0,mr:1,dl:-1,dr:180,map:'-'};
  await page.waitForFunction(()=>/Auto-pause/.test(document.querySelector('#liveStats').textContent));
  const pauseText=await page.locator('#liveStats').textContent();
  assert.match(pauseText,/◀ Facing left/);assert.match(pauseText,/Map not taught/);assert.match(pauseText,/Nearest Blue Snail · right · 180% of reach/);
  // No mob readings (an untaught map): Smart stands still rather than attack blindly, and the dashboard says why.
  patternState={...patternState,action:'nodetector'};liveState={...liveState,mobs:0,ml:-1,mr:-1,dl:-1,dr:-1,mob:undefined,map:'-'};
  await page.waitForFunction(()=>/Mobs not counted/.test(document.querySelector('#liveStats').textContent));
  const blindText=await page.locator('#liveStats').textContent();
  assert.match(blindText,/⚠ No mob detection on this map: not attacking/);assert.doesNotMatch(blindText,/attacking anyway/);
  assert.match(blindText,/this map isn't taught\. On it, press Which map \(F9\)/);
  patternState={...patternState,action:'noreadings'};
  await page.waitForFunction(()=>/No readings from the PC: not attacking/.test(document.querySelector('#liveStats').textContent));
  patternState={...patternState,action:'attack'};
  assert.equal(await page.locator('#liveStats .radar').count(),0);
  liveState={...liveState,map:'Henesys'};
  await page.waitForFunction(()=>/no mob detection on this map/.test(document.querySelector('#liveStats').textContent));
  patternState={...patternState,smart:false};
  await page.waitForFunction(()=>/Smart off/.test(document.querySelector('#liveStats').textContent));
  assert.doesNotMatch(await page.locator('#liveStats').textContent(),/Can't see mobs/);
  // A home range but no Set home on this map: the dashboard says so.
  patternState={...patternState,home:undefined,noHome:true};
  await page.waitForFunction(()=>/No home on this map: press Set home/.test(document.querySelector('#liveStats').textContent));
  // Set home here: pins home where you stand; with nothing playing it shows as a mark
  // on its map, and Forget home clears it.
  patternState=null;liveState={...liveState,x:420,wx:1420,map:'Henesys',mobs:8,ml:0,mr:0,dl:-1,dr:-1};
  await page.waitForFunction(()=>/Idle|Playing/.test(document.querySelector('#liveStats').textContent));   // the pattern has stopped
  assert.equal(await page.locator('#liveStats .track .home').count(),0);
  assert.equal(await page.locator('#liveStats button',{hasText:'Forget this map'}).count(),0);
  await page.locator('#liveStats button',{hasText:'Set home here'}).click();
  await page.waitForFunction(()=>document.querySelector('#liveStats .track .home'));
  assert.deepEqual(homeRequests,['/api/home/set']);
  assert.deepEqual(await page.locator('#liveStats .track .home').evaluate(e=>[e.style.left,e.style.width,e.title]),['41.2%','1.6%','Home (from Set home)']);
  await page.locator('#liveStats button',{hasText:'Forget this map'}).click();
  await page.waitForFunction(()=>!document.querySelector('#liveStats .track .home'));
  assert.deepEqual(homeRequests,['/api/home/set','/api/home/clear']);
  patternState=null;
  // Notifications: the game's test popup (still on screen: highlighted, with a
  // toast) above an older death; Clear empties them on the pad.
  assert(await page.locator('#notices').isHidden());
  noticeState=[{id:1,kind:'dead',text:'you died',agoMs:185000},{id:2,kind:'test',text:'a test popup is on screen: answer it in the game',agoMs:4000}];
  liveState={hp:723,mana:400,xp:632,state:'test',stopped:'a test popup is on screen: answer it in the game',ageMs:300,fresh:true,xpPerHour:-1,minutesToLevel:-1,levels:0};
  await page.waitForFunction(()=>!document.querySelector('#notices').hidden);
  await page.locator('#toast.show.err').waitFor();assert.match(await page.locator('#toast').textContent(),/🧩 Test popup in the game/);
  assert.match(await page.locator('#notices').textContent(),/🔔 Notifications.*🧩Test popup in the game · on screen nowAnswer it yourself.*4 s ago💀You died.*3 min ago/s);
  assert(await page.locator('#notices').evaluate(e=>e.classList.contains('alert')));
  assert.deepEqual(await page.locator('#notices .notice').evaluateAll(ns=>ns.map(n=>n.classList.contains('now'))),[true,false]);
  assert.match(await page.locator('#liveStats').textContent(),/⛔ Stopped: a test popup is on screen/);
  await page.locator('#notices').screenshot({path:'/tmp/kabuto-notices.png'});
  liveState={...liveState,state:undefined,stopped:undefined};   // answered: kept in the list, no longer "now"
  await page.waitForFunction(()=>!document.querySelector('#notices').classList.contains('alert'));
  assert.doesNotMatch(await page.locator('#notices').textContent(),/on screen now/);
  await page.locator('#notices').getByRole('button',{name:'Clear'}).click();
  await page.waitForFunction(()=>document.querySelector('#notices').hidden);
  assert.deepEqual(noticeRequests,['/api/notices/clear']);
  // Only the newest 4 are listed.
  noticeState=[1,2,3,4,5,6].map(id=>({id,kind:id%2?'dead':'offline',text:'x',agoMs:(7-id)*60000}));
  await page.waitForFunction(()=>!document.querySelector('#notices').hidden);
  assert.equal(await page.locator('#notices .notice').count(),4);
  assert.match(await page.locator('#notices .notice').first().textContent(),/Game disconnected.*1 min ago/);
  noticeState=null;await page.waitForFunction(()=>document.querySelector('#notices').hidden);
  // The dashboard asks every 2 s, and not at all while the page is in the background.
  let statusCalls=0;const countStatus=r=>{if(new URL(r.url()).pathname==='/api/status')statusCalls++;};page.on('request',countStatus);
  await page.waitForTimeout(4200);assert(statusCalls>=2&&statusCalls<=3,'status asked '+statusCalls+' times in 4.2 s');
  const setHidden=h=>page.evaluate(h=>{Object.defineProperty(document,'hidden',{configurable:true,get:()=>h});document.dispatchEvent(new Event('visibilitychange'));},h);
  await setHidden(true);await page.waitForTimeout(2200);statusCalls=0;await page.waitForTimeout(4200);
  assert.equal(statusCalls,0);
  await setHidden(false);await page.waitForTimeout(400);assert.equal(statusCalls,1);   // shown again: asks at once, one loop only
  await page.waitForTimeout(2100);assert.equal(statusCalls,2);
  page.off('request',countStatus);
  liveState={hp:723,mana:-1,xp:-1,ageMs:12000,fresh:false,xpPerHour:-1,minutesToLevel:-1,levels:0};
  await page.waitForFunction(()=>document.querySelector('#liveStats').classList.contains('stale'));
  assert.match(await page.locator('#liveStats').textContent(),/stopped 12 s ago; potions use their timers/);
  assert.equal(await page.locator('#liveStats .live-row').count(),1);   // unread bars aren't shown
  liveState=null;await page.waitForFunction(()=>document.querySelector('#liveStats').hidden);
  await page.locator('#tabRecordings').click();
  // The screen reader's keys as pad buttons: one Setup layer with a way back,
  // and a free button on the current layer to get in.
  const layersBefore=await page.evaluate(()=>cfg.layers.length);
  await page.locator('#newSetupLayer').click();
  const layerKeys=i=>page.evaluate(i=>{const L=cfg.layers[i];return {name:L.name,keys:L.keys.map(k=>[k.name,cfg.workflows.find(w=>w.id===k.steps[0]?.workflow)?.steps[0]])};},i);
  assert.equal(await page.evaluate(()=>cfg.layers.length),layersBefore+1);
  assert.deepEqual(await layerKeys(layersBefore),{name:'MS🍁 Setup',keys:[['Mark (F8)',{type:'tool',key:'mark'}],['Skip (Esc)',{type:'tool',key:'skip'}],
    ['Which map (F9)',{type:'tool',key:'map'}],['Map area (F12)',{type:'tool',key:'area'}],['Outlines (F10)',{type:'tool',key:'outlines'}],['Back',{type:'layer',layer:0}]]});
  assert.deepEqual(await page.evaluate(n=>cfg.layers[0].keys.filter(k=>k.name==='🍁 Setup').map(k=>cfg.workflows.find(w=>w.id===k.steps[0].workflow).steps[0]),layersBefore),[{type:'layer',layer:layersBefore}]);
  assert.match(await page.locator('#recordings').textContent(),/Screen reader key · Mark \(F8\)/);
  assert.match(await page.locator('#recordings').textContent(),/Screen reader key · Map area \(F12\)/);
  const toolCount=await page.evaluate(()=>cfg.workflows.filter(w=>w.steps[0]?.type==='tool').length);
  assert.equal(toolCount,5);
  if(await page.evaluate(()=>cfg.layers.length+1<=meta.maxLayers)){
    await page.locator('#newSetupLayer').click();   // again: the same recordings are reused
    assert.equal(await page.evaluate(()=>cfg.workflows.filter(w=>w.steps[0]?.type==='tool').length),5);
  }
  // A Set home button: goes on the selected button when it's empty, its recording reused after.
  const emptyKey=await page.evaluate(()=>{selLayer=0;const i=cfg.layers[0].keys.findIndex(k=>!k.steps.length);selKey=i;return i;});
  if(emptyKey>=0){
    await page.locator('#newSetHome').click();
    assert.deepEqual(await page.evaluate(i=>{const k=cfg.layers[0].keys[i];return [k.name,cfg.workflows.find(w=>w.id===k.steps[0]?.workflow)?.steps];},emptyKey),['🏠 Set home',[{type:'tool',key:'home'}]]);
    assert.match(await page.locator('#recordings').textContent(),/Set home · home where you stand; never stops what's playing/);
    const homes=()=>page.evaluate(()=>cfg.workflows.filter(w=>w.steps[0]?.type==='tool'&&w.steps[0].key==='home').length);
    await page.locator('#newSetHome').click();assert.equal(await homes(),1);
  }
  // The scenarios (tests/scenarios.cpp) play the editor's default pattern from a fixture: keep them the same.
  {const fixture=JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures','default_pattern.json'),'utf8'));
   const current=await page.evaluate(()=>{const q=defaultDynamicPattern();q.id='default';q.char_keys=q.char_potions=q.char_skills=false;return q;});
   assert.deepEqual(current,fixture,'the editor\'s default pattern changed: update tests/fixtures/default_pattern.json (and check the scenarios)');}
  // Home Wi-Fi: typing survives a status refresh; a blank password keeps the saved one.
  await page.locator('#networkSummary').click();
  assert.match(await page.locator('#networkStatus').textContent(),/Saved: HomeNet\. Joined only to check for updates/);
  // The pad's health; memory too broken up for updates says so.
  assert.match(await page.locator('#padHealth').textContent(),/^Pad: up 3 h 5 min · memory 146 KB free, 68 KB in one piece$/);
  networkState.heapLargest=30000;await page.evaluate(()=>refreshNetwork());
  await page.waitForFunction(()=>document.querySelector('#padHealth').classList.contains('warn'));
  assert.match(await page.locator('#padHealth').textContent(),/29 KB in one piece\. Low: restart the pad/);
  networkState.heapLargest=70000;await page.evaluate(()=>refreshNetwork());
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
