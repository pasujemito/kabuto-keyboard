#include <Arduino.h>
#include <vector>
#include <map>
#include <string>
// Inspect interpreter state without adding a production test-only API.
#define private public
#include "../src/macro_engine.h"
#undef private
#include "../src/hid_keyboard.h"
#include "../src/live_stats.h"
#include <cassert>
#include <algorithm>
#include <iostream>

uint32_t testClock = 0;
std::function<void()> testDelayHook;
std::function<long(long)> testRandomHook;
HidKeyboard Keyboard;
std::vector<uint8_t> taps, held;
std::vector<uint16_t> tapHoldDurations;
unsigned releases = 0;
uint8_t heldMods=0;
uint32_t ctrlStarted=0;
std::vector<uint32_t> ctrlDurations;
struct HidEvent { uint32_t at; uint8_t key; uint8_t mods; bool down; };
std::vector<HidEvent> hidEvents;
std::vector<uint8_t> tapModifiers;

void HidKeyboard::tap(uint8_t key, uint8_t, uint16_t holdMs) { taps.push_back(key);tapHoldDurations.push_back(holdMs);tapModifiers.push_back(heldMods); }
void HidKeyboard::pressKey(uint8_t key, uint8_t mods) {
    if((mods&1)&&!(heldMods&1))ctrlStarted=millis();
    heldMods|=mods;
    if(key)held.push_back(key);
    hidEvents.push_back({millis(),key,heldMods,true});
}
void HidKeyboard::releaseKey(uint8_t key) {
    held.erase(std::remove(held.begin(),held.end(),key),held.end());
    hidEvents.push_back({millis(),key,heldMods,false});
}
void HidKeyboard::releaseModifiers(uint8_t mods) {
    if((mods&1)&&(heldMods&1))ctrlDurations.push_back(millis()-ctrlStarted);
    heldMods &= ~mods;
    hidEvents.push_back({millis(),0,heldMods,false});
}
void HidKeyboard::releaseAll() { releaseModifiers(255);held.clear(); ++releases; }
void HidKeyboard::typeString(const String&) {}
void HidKeyboard::consumerPress(uint16_t) {}
void HidKeyboard::consumerRelease() {}
bool loadConfig(Config&) { return false; }
bool saveConfig(const Config&) { return false; }

Step tap(uint8_t code) { Step s; s.type=StepType::KEY; s.keycode=code; return s; }
Step call(const char* id) { Step s; s.type=StepType::CALL; s.setText(id); return s; }
Workflow workflow(const char* id, std::vector<Step> steps) {
    Workflow w; w.id=id; w.name=id; w.steps=steps; return w;
}
void run(MacroEngine& engine, std::vector<Step> steps) {
    KeyBinding key; key.steps=steps;
    engine.oneShot_=true;
    engine.stopFlag_=false;
    taps.clear();
    engine.runMacro(key);
    assert(engine.callStack_.empty());
    assert(held.empty());
}
// Press Set home where the latest reading says you stand (the only way home is set).
void pinHere(){homePinsLoad(nullptr,0);bool ok=homePin();assert(ok);}
int main() {
    MacroEngine engine;
    engine.config().randomizedDelay=false;
    engine.config().workflows={workflow("walk", {tap(26)}), workflow("attack", {tap(4)}),
        workflow("approach", {call("walk"), call("attack")})};
    engine.commit();
    run(engine, {call("approach")});
    assert((taps==std::vector<uint8_t>{26,4}));
    assert(releases>0);
    Step choose; choose.type=StepType::RANDOM;choose.avoidRecent=1;
    MacroRef a; a.workflow="walk"; MacroRef b; b.workflow="attack";b.weight=5;
    choose.setChoices({a,b});
    Step loop; loop.type=StepType::LOOP_START;loop.value=4;loop.matchIndex=2;
    Step end;end.type=StepType::LOOP_END;end.matchIndex=0;
    run(engine,{loop,choose,end});
    assert((taps==std::vector<uint8_t>{26,4,26,4}));
    // Re-activating a key resets its history.
    run(engine,{choose});assert((taps==std::vector<uint8_t>{26}));
    // Toggle passes must retain history, even without an explicit loop step.
    KeyBinding toggle;toggle.trigger=TriggerMode::TOGGLE;toggle.steps={choose};
    engine.oneShot_=false;engine.stopFlag_=false;taps.clear();
    testDelayHook=[&] {if(taps.size()>=4)engine.stopFlag_=true;};
    engine.runMacro(toggle);testDelayHook={};
    assert((taps==std::vector<uint8_t>{26,4,26,4}));
    // An exhausted choice set skips instead of breaking the exclusion window.
    choose.avoidRecent=2;
    run(engine,{loop,choose,end});assert((taps==std::vector<uint8_t>{26,4}));
    // Missing and cyclic calls return safely and log the skip.
    engine.config().workflows.push_back(workflow("cycle",{call("cycle")}));
    run(engine,{call("missing"),call("cycle"),tap(9)});
    assert((taps==std::vector<uint8_t>{9}));
    MacroLogEntry entries[96];auto n=engine.copyLog(entries,96);bool skipped=false;
    for(size_t i=0;i<n;++i)if(std::string(entries[i].text).find("skipped:")==0)skipped=true;
    assert(skipped);
    // Exactly eight nested calls are supported; deeper calls skip safely.
    engine.config().workflows.clear();
    for(int i=0;i<9;++i) {
        std::string id="depth"+std::to_string(i);
        std::string next="depth"+std::to_string(i+1);
        engine.config().workflows.push_back(workflow(id.c_str(), i==8 ? std::vector<Step>{tap(31)} : std::vector<Step>{call(next.c_str()),tap(static_cast<uint8_t>(i+1))}));
    }
    run(engine,{call("depth0")});
    assert(taps.size()==8 && taps.front()==8 && taps.back()==1);
    // Legacy layer/key random references still run.
    engine.config().ensureLayer(0);engine.config().layers[0].keys[1].steps={tap(10)};
    MacroRef legacy;legacy.layer=0;legacy.key=1;choose.setChoices({legacy});
    choose.avoidRecent=0;run(engine,{choose});assert((taps==std::vector<uint8_t>{10}));
    // Stop during a nested held-key workflow releases all keys at the root.
    Step down;down.type=StepType::KEY_DOWN;down.keycode=26;
    Step delay;delay.type=StepType::DELAY;delay.value=100;
    engine.config().workflows.push_back(workflow("hold",{down,delay,tap(20)}));
    testDelayHook=[&] {engine.stopFlag_=true;};
    run(engine,{call("hold"),tap(21)});testDelayHook={};assert(taps.empty());
    // Attack envelopes retain Ctrl across movement and jumps, but respect
    // their deadline even when a child requests a 90-second wait.
    engine.config().workflows.clear();
    Step move;move.type=StepType::MOVE;move.value=200;move.maxValue=524;
    Step jumpDown; jumpDown.type=StepType::KEY_DOWN;jumpDown.modifiers=4;
    Step jumpUp; jumpUp.type=StepType::KEY_UP;jumpUp.modifiers=4;
    Step shortDelay;shortDelay.type=StepType::DELAY;shortDelay.value=121;shortDelay.maxValue=194;
    engine.config().workflows.push_back(workflow("combat-micro",{move,jumpDown,shortDelay,jumpUp}));
    MacroRef cr;cr.workflow="combat-micro";
    Step combat;combat.type=StepType::COMBAT;combat.value=90000;combat.maxValue=90000;combat.setChoices({cr});
    hidEvents.clear();ctrlDurations.clear();
    run(engine,{combat});
    assert(ctrlDurations.size()==1 && ctrlDurations[0]==90000);
    assert(!heldMods && held.empty());
    bool sawLeft=false,sawRight=false;
    for(auto e:hidEvents) if(e.key==80||e.key==79) {
        assert(e.mods&1); // arrows never release the attack modifier
        sawLeft|=e.key==80;sawRight|=e.key==79;
    }
    assert(sawLeft&&sawRight);
    assert(engine.movementBalanceMs_>=-600 && engine.movementBalanceMs_<=600);
    Step longDelay;longDelay.type=StepType::DELAY;longDelay.value=90000;
    engine.config().workflows[0].steps={jumpDown,longDelay,jumpUp};
    combat.value=1234;combat.maxValue=1234;ctrlDurations.clear();
    run(engine,{combat});assert(ctrlDurations.size()==1 && ctrlDurations[0]==1234);
    // Inclusive range endpoints are honored instead of applying global jitter.
    testRandomHook=[](long upper){return upper-1;};
    combat.value=1000;combat.maxValue=1234;ctrlDurations.clear();
    engine.config().randomizedDelay=true;
    run(engine,{combat});assert(ctrlDurations.size()==1&&ctrlDurations[0]==1234);
    testRandomHook={};engine.config().randomizedDelay=false;
    // Stop midway through held movement releases Ctrl, Alt and arrows.
    engine.config().workflows[0].steps={move,jumpDown,longDelay,jumpUp};
    uint32_t stopAt=millis()+73;
    testDelayHook=[&]{if(millis()>=stopAt)engine.stopFlag_=true;};
    run(engine,{combat});testDelayHook={};assert(held.empty()&&!heldMods);
    // Utility first-use/full cooldown, completion anchoring, and persistence
    // over starting another key. No Ctrl is held when the utility fires.
    Workflow utility=workflow("heal",{tap(11),shortDelay});utility.utilityEnabled=true;
    utility.cooldownMs=300000;utility.chancePermille=1000;
    engine.config().workflows={utility};engine.utilityClockStarted_=false;engine.utilityLastRun_.clear();
    Step utilities;utilities.type=StepType::UTILITIES;
    run(engine,{utilities});assert(taps.empty());
    uint32_t epoch=engine.utilityEpoch_;
    testClock=epoch+299999;run(engine,{utilities});assert(taps.empty());
    testClock=epoch+300000;tapModifiers.clear();run(engine,{utilities});
    assert((taps==std::vector<uint8_t>{11}) && tapModifiers.back()==0);
    uint32_t completed=millis();assert(engine.utilityLastRun_["heal"]==completed);
    testClock=completed+299999;run(engine,{utilities});assert(taps.empty());
    testClock=completed+300000;engine.config().workflows[0].chancePermille=0;
    run(engine,{utilities});assert(taps.empty());
    engine.config().workflows[0].chancePermille=1000;
    run(engine,{utilities});assert(taps.size()==1);
    // A utility check under Ctrl must not run or consume its cooldown.
    Step attackDown;attackDown.type=StepType::KEY_DOWN;attackDown.modifiers=1;
    testClock+=300000;run(engine,{attackDown,utilities});assert(taps.empty());
    engine.config().workflows[0].utilityEnabled=false;
    run(engine,{utilities});assert(taps.empty());
    // Unsigned elapsed-time arithmetic works across millis() wraparound.
    engine.utilityEpoch_=UINT32_MAX-100;engine.utilityLastRun_.clear();engine.config().workflows[0].utilityEnabled=true;
    engine.config().workflows[0].cooldownMs=200;testClock=50;
    run(engine,{utilities});assert(taps.empty());testClock=100;
    run(engine,{utilities});assert(taps.size()==1);
    // One visible recording can span internal parts without releasing Ctrl.
    // Captured fixed timings use the same jitter as other steps.
    Step ctrlUp;ctrlUp.type=StepType::KEY_UP;ctrlUp.modifiers=1;
    Step capturedDelay;capturedDelay.type=StepType::DELAY;capturedDelay.value=100;
    Workflow part1=workflow("rec-part1",{attackDown,capturedDelay});part1.recordingPartOf="recording";
    Workflow part2=workflow("rec-part2",{tap(11),ctrlUp});part2.recordingPartOf="recording";
    Workflow recording=workflow("recording",{call("rec-part1"),call("rec-part2")});recording.recording=true;
    engine.config().workflows={recording,part1,part2};engine.config().randomizedDelay=true;
    testRandomHook=[](long upper){return upper-1;};
    ctrlDurations.clear();tapModifiers.clear();run(engine,{call("recording")});
    assert(tapModifiers.back()==1);
    assert(ctrlDurations.size()==1&&ctrlDurations[0]==107); // 100ms + 6ms jitter + one scheduler yield
    assert(!heldMods&&held.empty());
    // Upper jitter endpoints at the 5-second and 40-second boundaries.
    const uint32_t bases[]={5000,5001,40000,40001};
    const uint32_t expected[]={5015,5201,40200,45001};
    for(size_t index=0;index<4;++index) {
        Step sampledDelay;sampledDelay.type=StepType::DELAY;sampledDelay.value=bases[index];
        uint32_t startedAt=millis();run(engine,{sampledDelay});
        assert(millis()-startedAt==expected[index]);
    }
    // Tap-style keystrokes receive +/-6 ms around their recorded hold time.
    Step jitteredTap=tap(26);jitteredTap.value=50;
    testRandomHook=[](long upper){return upper-1;};
    tapHoldDurations.clear();run(engine,{jitteredTap});
    assert(tapHoldDurations.size()==1&&tapHoldDurations[0]==56);
    testRandomHook=[](long){return 0;};
    tapHoldDurations.clear();run(engine,{jitteredTap});
    assert(tapHoldDurations.size()==1&&tapHoldDurations[0]==44);
    // Repeated loop iterations draw independent jitter for the same step.
    Step loopStart;loopStart.type=StepType::LOOP_START;loopStart.value=2;loopStart.matchIndex=4;
    Step loopEnd;loopEnd.type=StepType::LOOP_END;loopEnd.matchIndex=0;
    Step loopDelay;loopDelay.type=StepType::DELAY;loopDelay.value=5000;
    int randomCall=0;
    testRandomHook=[&randomCall](long upper){return randomCall++%2==0?0:upper-1;};
    ctrlDurations.clear();run(engine,{loopStart,attackDown,loopDelay,ctrlUp,loopEnd});
    assert((ctrlDurations==std::vector<uint32_t>{4994,5006}));
    testRandomHook={};engine.config().randomizedDelay=false;
    // Dynamic playback streams the preserved Alt/Ctrl overlap, with explicit
    // sampled timings taking precedence over the configured global jitter.
    DynamicPattern p;p.id="test-dynamic";p.sets={3,3};p.attacksPerSet={2,2};p.turnChancePermille=1000;
    Step dynamic;dynamic.type=StepType::DYNAMIC;dynamic.setPattern(p);
    engine.config().randomizedDelay=true;hidEvents.clear();ctrlDurations.clear();
    run(engine,{dynamic});
    std::vector<HidEvent> transitions;uint8_t previous=0;
    for(auto e:hidEvents)if(e.key==0&&e.mods!=previous){transitions.push_back(e);previous=e.mods;}
    assert(transitions.size()==3*2*4);
    for(size_t i=0;i<transitions.size();i+=4){
        assert(transitions[i].mods==4&&transitions[i+1].mods==5&&transitions[i+2].mods==1&&transitions[i+3].mods==0);
        assert(transitions[i+1].at-transitions[i].at==45);
        assert(transitions[i+2].at-transitions[i+1].at==30);
        assert(transitions[i+3].at-transitions[i+2].at==16);
    }
    std::vector<uint8_t> directions;
    for(auto e:hidEvents)if(e.down&&(e.key==80||e.key==79)){assert(!e.mods);directions.push_back(e.key);}
    // Initial facing plus one tap between sets; nothing after the last set.
    assert((directions==std::vector<uint8_t>{80,79,80}));
    assert(ctrlDurations.size()==6&&std::all_of(ctrlDurations.begin(),ctrlDurations.end(),[](uint32_t v){return v==46;}));
    p.turnChancePermille=0;dynamic.setPattern(p);hidEvents.clear();run(engine,{dynamic});
    for(auto e:hidEvents)if(e.down&&(e.key==80||e.key==79))assert(e.key==80);
    // Fresh counts each activation: minimum draws vs maximum draws.
    p.sets={2,4};p.attacksPerSet={1,3};dynamic.setPattern(p);
    ctrlDurations.clear();run(engine,{dynamic});assert(ctrlDurations.size()==2);
    testRandomHook=[](long upper){return upper-1;};ctrlDurations.clear();run(engine,{dynamic});
    assert(ctrlDurations.size()==12&&ctrlDurations[0]==200);testRandomHook={};
    // Custom movement keys (Space jumps, X attacks, A/D turn) keep the chord order.
    {
        DynamicPattern q=p;q.sets={2,2};q.attacksPerSet={1,1};q.turnChancePermille=1000;q.skills.clear();
        q.jump=dynamicKeycode(0x2C);q.attack=dynamicKeycode(0x1B);q.left=dynamicKeycode(0x04);q.right=dynamicKeycode(0x07);
        Step custom=dynamic;custom.setPattern(q);hidEvents.clear();run(engine,{custom});
        std::vector<std::pair<uint8_t,bool>> keys;
        for(auto e:hidEvents){assert(!e.mods);if(e.key)keys.push_back({e.key,e.down});}
        std::vector<std::pair<uint8_t,bool>> expected{{4,true},{4,false},{0x2C,true},{0x1B,true},{0x2C,false},{0x1B,false},
                                                       {7,true},{7,false},{0x2C,true},{0x1B,true},{0x2C,false},{0x1B,false}};
        assert(keys==expected);assert(held.empty()&&!heldMods);
    }
    // Tempo drift scales only the gap after each attack, within +/-drift.
    {
        DynamicPattern q=p;q.sets={1,1};q.attacksPerSet={3,3};q.tempoDriftPermille=150;q.skills.clear();
        Step drifting=dynamic;drifting.setPattern(q);
        for(bool high:{false,true}){
            if(high)testRandomHook=[](long upper){return upper-1;};else testRandomHook=[](long){return 0L;};
            hidEvents.clear();run(engine,{drifting});testRandomHook={};
            std::vector<uint32_t> ctrlUps,altDowns;uint8_t mods=0;
            for(auto e:hidEvents)if(e.key==0&&e.mods!=mods){if(e.mods==4&&!mods)altDowns.push_back(e.at);if(!e.mods&&mods==1)ctrlUps.push_back(e.at);mods=e.mods;}
            assert(ctrlUps.size()==3&&altDowns.size()==3);
            // Pinned at the edge: 760 ms max gap * 1.15, or 510 ms min gap * 0.85.
            for(size_t i=0;i+1<altDowns.size();++i)assert(altDowns[i+1]-ctrlUps[i]==(high?874U:433U));
        }
    }
    // Independent skills, repeat counts, and a cooldown retained over Stop/Start.
    p.sets={3,3};p.attacksPerSet={1,1};
    DynamicSkill c;c.id="skill-c";c.keycode=6;c.chancePermille=1000;c.cooldown={1000000,1000000};
    DynamicSkill h;h.id="skill-h";h.keycode=11;h.chancePermille=1000;h.repeats={1,1};
    p.skills={c,h};dynamic.setPattern(p);hidEvents.clear();run(engine,{dynamic});
    auto pressCount=[&](uint8_t key){return std::count_if(hidEvents.begin(),hidEvents.end(),[&](const HidEvent& e){return e.down&&e.key==key;});};
    assert(pressCount(6)==2&&pressCount(11)==3);
    for(auto e:hidEvents)if(e.key==6||e.key==11)assert(!e.mods);
    hidEvents.clear();run(engine,{dynamic});assert(pressCount(6)==0&&pressCount(11)==3);
    p.skills[0].chancePermille=0;p.skills[1].enabled=false;dynamic.setPattern(p);hidEvents.clear();
    engine.dynamicSkillTimers_.clear();run(engine,{dynamic});assert(pressCount(6)==0&&pressCount(11)==0);
    // A ranged "use again after" is drawn per use and gates later sets until it passes.
    {
        DynamicPattern q=p;DynamicSkill r;r.id="skill-r";r.keycode=21;r.chancePermille=1000;r.repeats={1,1};r.cooldown={2000,4000};
        q.skills={r};Step ranged=dynamic;ranged.setPattern(q);
        for(bool high:{false,true}){
            if(high)testRandomHook=[](long upper){return upper-1;};else testRandomHook=[](long){return 0L;};
            engine.dynamicSkillTimers_.clear();hidEvents.clear();run(engine,{ranged});testRandomHook={};
            assert(engine.dynamicSkillTimers_.at("test-dynamic/skill-r").wait==(high?4000U:2000U));
            assert(pressCount(21)==1); // 3 short sets fit inside even the 2000 ms wait
        }
        q.skills[0].cooldown={0,0};ranged.setPattern(q);engine.dynamicSkillTimers_.clear();hidEvents.clear();
        run(engine,{ranged});assert(pressCount(21)==3);
    }
    // HP/Mana potions fire on their own timers, before skills: quick taps in the gap
    // after an attack (jump and attack released), not adding to the gap.
    {
        DynamicPattern q=p;q.sets={3,3};q.attacksPerSet={1,1};
        DynamicSkill hp;hp.id="hp";hp.keycode=6;hp.chancePermille=1000;hp.repeats={1,1};hp.cooldown={1000000,1000000};
        DynamicSkill mana=hp;mana.id="mana";mana.keycode=0x19;mana.cooldown={0,0};
        DynamicSkill skill;skill.id="hp";skill.keycode=11;skill.chancePermille=1000;skill.repeats={1,1};   // a skill named like a potion keeps its own timer
        q.potions={hp,mana};q.skills={skill};Step drinking=dynamic;drinking.setPattern(q);
        engine.dynamicSkillTimers_.clear();hidEvents.clear();run(engine,{drinking});
        assert(pressCount(6)==1&&pressCount(0x19)==3&&pressCount(11)==3);
        std::vector<uint8_t> order;for(auto e:hidEvents)if(e.down&&(e.key==6||e.key==0x19||e.key==11))order.push_back(e.key);
        assert(order.size()==7&&order[0]==6&&order[1]==0x19&&order[2]==11);
        for(auto e:hidEvents)if(e.key==6||e.key==0x19)assert(e.mods==0);   // after the attack: jump (Alt) and attack (Ctrl) both up
        // Drinking adds no time: the attacks land exactly when they would without potions.
        uint32_t runStart=0;
        auto lastAttack=[&]{uint32_t at=0;for(auto e:hidEvents)if(e.down&&e.key==0&&e.mods==5)at=e.at-runStart;return at;};
        testRandomHook=[](long){return 0L;};
        engine.dynamicSkillTimers_.clear();hidEvents.clear();runStart=testClock;run(engine,{drinking});uint32_t with=lastAttack();
        DynamicPattern dry=q;dry.potions.clear();Step plain=dynamic;plain.setPattern(dry);
        engine.dynamicSkillTimers_.clear();hidEvents.clear();runStart=testClock;run(engine,{plain});testRandomHook={};
        assert(with&&with==lastAttack());
        q.potions[0].enabled=false;drinking.setPattern(q);engine.dynamicSkillTimers_.clear();hidEvents.clear();run(engine,{drinking});
        assert(pressCount(6)==0&&pressCount(0x19)==3);
    }
    // Live bars: with a "drink below" threshold, HP follows the screen reading
    // (between attacks, at most every LIVE_POTION_GAP_MS); stale or unread bars
    // fall back to the timer.
    {
        DynamicPattern q=p;q.sets={1,1};q.attacksPerSet={8,8};q.skills.clear();
        DynamicSkill hp;hp.id="hp";hp.keycode=6;hp.chancePermille=1000;hp.repeats={1,1};hp.cooldown={1000000,1000000};hp.belowPercent=50;
        DynamicSkill mana=hp;mana.id="mana";mana.keycode=0x19;mana.belowPercent=50;
        q.potions={hp,mana};Step live=dynamic;live.setPattern(q);
        auto drink=[&](int hpTenths,int manaTenths){engine.dynamicSkillTimers_.clear();hidEvents.clear();liveStatsUpdate(hpTenths,manaTenths,-1);run(engine,{live});};
        drink(300,-1);      // HP low: drinks at once and again after the gap (~0.6 s/attack); Mana unread: its timer, once
        assert(pressCount(6)>=2&&pressCount(0x19)==1);
        uint32_t firstHp=0,secondHp=0;for(auto e:hidEvents)if(e.down&&e.key==6){if(!firstHp)firstHp=e.at;else if(!secondHp)secondHp=e.at;}
        assert(secondHp-firstHp>=LIVE_POTION_GAP_MS);
        for(auto e:hidEvents)if(e.key==6)assert(e.mods==0);   // in the gap after an attack
        drink(800,900);     // both bars healthy: neither drinks, not even on the timer
        assert(pressCount(6)==0&&pressCount(0x19)==0);
        liveStatsUpdate(300,300,-1);testClock+=LIVE_STATS_STALE_MS;engine.dynamicSkillTimers_.clear();hidEvents.clear();run(engine,{live});
        assert(pressCount(6)==1&&pressCount(0x19)==1);   // stale reading: timers, once each
        // Real amounts: HP 5000 at 30% is 3500 short; 800 a tap = 4 taps (a 5th would waste).
        q.potions[0].barMax=5000;q.potions[0].perTap=800;q.attacksPerSet={1,1};live.setPattern(q);drink(300,-1);
        assert(pressCount(6)==4);
        // With attacks to follow, the 4 taps come together in the gap after an attack: as many as fit
        // (2+, quick, jump and attack both up), the rest after the next attack, never inside a jump.
        q.attacksPerSet={3,3};live.setPattern(q);testRandomHook=[](long){return 0L;};drink(300,-1);testRandomHook={};
        assert(pressCount(6)==4);   // 3 attacks: within the 3 s before it may drink again
        {int afterAttack=-1,inGap=0,firstGap=-1;uint8_t mods=0;
         for(auto e:hidEvents){
             if(e.key==0&&e.mods!=mods){if(!e.mods&&mods==1){afterAttack=0;}if(e.mods&4&&!(mods&4)){if(afterAttack>0&&firstGap<0)firstGap=inGap;afterAttack=-1;inGap=0;}mods=e.mods;}
             if(e.down&&e.key==6){assert(afterAttack>=0&&e.mods==0);++afterAttack;++inGap;}
         }
         assert(firstGap>=2);}
        q.attacksPerSet={1,1};live.setPattern(q);
        liveStatsUpdate(300,300,-1);testClock+=LIVE_STATS_STALE_MS;engine.dynamicSkillTimers_.clear();hidEvents.clear();run(engine,{live});
        assert(pressCount(6)==1);   // stale reading: its timer and taps range, not the amounts
        q.potions[0].barMax=q.potions[0].perTap=0;q.attacksPerSet={8,8};
        q.potions[0].belowPercent=0;live.setPattern(q);drink(100,-1);
        assert(pressCount(6)==1);   // no threshold: timer only, whatever the bar says
    }
    // Screen awareness: stop on death/login, face away from edges
    // and towards mobs, and turn then stop when the minimap dot is stuck.
    {
        DynamicPattern q=p;q.sets={2,2};q.attacksPerSet={6,6};q.skills.clear();q.potions.clear();q.turnChancePermille=0;
        Step aware=dynamic;
        const uint8_t L=80,R=79;   // arrow keycodes
        auto attacks=[&]{int n=0;for(auto e:hidEvents)if(e.down&&e.key==0&&e.mods==5)++n;return n;};   // Ctrl down while Alt held
        auto dirs=[&]{std::vector<uint8_t> d;for(auto e:hidEvents)if(e.down&&(e.key==L||e.key==R))d.push_back(e.key);return d;};
        // Like the PC script, send a reading before starting and keep sending while it plays.
        auto play=[&](std::function<void()> eachDelay){eachDelay();testRandomHook=[](long){return 0L;};testDelayHook=eachDelay;hidEvents.clear();run(engine,{aware});testDelayHook={};testRandomHook={};};
        // Dead before starting: nothing is pressed.
        aware.setPattern(q);liveStatsUpdate(500,500,-1,LIVE_DEAD);play([]{});
        assert(std::none_of(hidEvents.begin(),hidEvents.end(),[](const HidEvent& e){return e.down;}));
        // Dies mid-pattern: stops at once, nothing left held.
        liveStatsUpdate(500,500,-1,LIVE_OK);uint32_t dieAt=millis()+1500;
        play([&]{liveStatsUpdate(500,500,-1,millis()>=dieAt?LIVE_DEAD:LIVE_OK);});
        assert(attacks()>=1&&attacks()<4&&held.empty()&&!heldMods&&engine.stopFlag_);engine.stopFlag_=false;
        // The game's test popup shows mid-pattern: the same stop, and one notification for it.
        liveStatsUpdate(500,500,-1,LIVE_OK);noticesClear();uint32_t testAt=millis()+1500;
        play([&]{liveStatsUpdate(500,500,-1,millis()>=testAt?LIVE_TEST:LIVE_OK);});
        assert(attacks()>=1&&attacks()<4&&held.empty()&&!heldMods&&engine.stopFlag_);engine.stopFlag_=false;
        {Notices n=noticesSnapshot();assert(n.count==1&&n.kind[0]==LIVE_TEST);noticesClear();}
        // Near the left edge while facing left (the first random draw): turns right before attacking.
        q.edgeMarginPermille=120;aware.setPattern(q);
        play([&]{liveStatsUpdate(500,500,-1,LIVE_OK,50,500);});
        assert((dirs()==std::vector<uint8_t>{L,R,R}));   // between sets it taps the way it faces
        // A mob on the right only: face it, and keep facing it at the set boundary.
        q.edgeMarginPermille=0;q.faceMobs=true;aware.setPattern(q);
        play([&]{liveStatsUpdate(500,500,-1,LIVE_OK,500,500,MOB_RIGHT);});
        assert((dirs()==std::vector<uint8_t>{L,R,R}));
        // The same with an older pattern's face_mobs off: mobs in reach are always faced now.
        q.faceMobs=false;aware.setPattern(q);
        play([&]{liveStatsUpdate(500,500,-1,LIVE_OK,500,500,MOB_RIGHT);});
        assert((dirs()==std::vector<uint8_t>{L,R,R}));q.faceMobs=true;
        // Mobs on both sides: face the nearer one (left nearer: stays left; right nearer: turns right).
        play([&]{liveStatsUpdate(500,500,-1,LIVE_OK,500,500,MOB_LEFT|MOB_RIGHT);});
        assert((dirs()==std::vector<uint8_t>{L,L}));
        play([&]{liveStatsUpdate(500,500,-1,LIVE_OK,500,500,MOB_LEFT|MOB_RIGHT|MOB_RIGHT_NEARER);});
        assert((dirs()==std::vector<uint8_t>{L,R,R}));
        // Stuck on the same spot: turns around once, then stops.
        q.faceMobs=false;q.stuckAfterMs=1500;aware.setPattern(q);
        play([&]{liveStatsUpdate(500,500,-1,LIVE_OK,400,300);});
        // Start left, turn right when stuck, tap right between sets, stop early in set 2.
        assert((dirs()==std::vector<uint8_t>{L,R,R})&&attacks()==6);
        assert(engine.stopFlag_&&held.empty()&&!heldMods);engine.stopFlag_=false;
        // A sliding minimap: the dot stays centred but the map position moves, so it isn't stuck.
        play([&]{liveStatsUpdate(500,500,-1,LIVE_OK,500,500,0,(int)(millis()/10),500);});
        assert((dirs()==std::vector<uint8_t>{L,L})&&attacks()==12&&!engine.stopFlag_);
        // The map position standing still while the dot doesn't move either: stuck as before.
        play([&]{liveStatsUpdate(500,500,-1,LIVE_OK,500,500,0,-2400,500);});
        assert((dirs()==std::vector<uint8_t>{L,R,R})&&attacks()==6&&engine.stopFlag_);engine.stopFlag_=false;
        // Smart mode: no mobs in the hitbox -> no attacks until some appear, then face them.
        q.stuckAfterMs=0;q.smart=true;q.homeRangePermille=100;q.sets={1,1};q.attacksPerSet={3,3};aware.setPattern(q);
        auto firstAttack=[&]{for(auto e:hidEvents)if(e.down&&e.key==0&&e.mods==5)return e.at;return 0u;};
        uint32_t mobsAt=millis()+2000;
        play([&]{liveStatsUpdate(500,500,-1,LIVE_OK,500,500,millis()>=mobsAt?MOB_READ|MOB_RIGHT:MOB_READ);});
        assert(attacks()==3&&firstAttack()>=mobsAt&&dirs().back()==R&&!engine.stopFlag_);
        // Drifted from home with no mobs: walks back (holds left), then waits; mobs return once home.
        // (The first tap sets the facing; any left press after it is the walk.)
        bool walked=false;int calls=0;
        play([&]{if(++calls==1){liveStatsUpdate(500,500,-1,LIVE_OK,500,500,MOB_READ|MOB_LEFT,300,500);pinHere();return;}   // home: map x 300
                 auto d=dirs();walked=walked||(d.size()>=2&&d.back()==L);
                 liveStatsUpdate(500,500,-1,LIVE_OK,500,500,walked?MOB_READ|MOB_LEFT:MOB_READ,walked?320:450,500);});   // drifted to 450
        assert(walked&&attacks()==3);
        // Stop pressed while waiting for mobs: returns at once, nothing held.
        uint32_t stopAt=millis()+1500;
        play([&]{liveStatsUpdate(500,500,-1,LIVE_OK,500,500,MOB_READ);if(millis()>=stopAt)engine.stopFlag_=true;});
        assert(attacks()==0&&held.empty()&&!heldMods&&engine.stopFlag_);engine.stopFlag_=false;
        // Without a mob detector (no "mobs" in the readings) Smart can't see mobs: it
        // stands still rather than attack blindly, and the dashboard says why.
        {uint32_t stopNoDetector=millis()+3000;bool told=false;
         play([&]{liveStatsUpdate(500,500,-1,LIVE_OK,500,500,0);told=told||patternViewSnapshot().action==SMART_NO_DETECTOR;if(millis()>=stopNoDetector)engine.stopFlag_=true;});
         assert(attacks()==0&&told&&held.empty());engine.stopFlag_=false;}
        // No readings at all (the script not running, a charge-only cable): the same.
        {liveStatsUpdate(-1,-1,-1);testClock+=LIVE_STATS_STALE_MS;uint32_t stopNoReadings=millis()+3000;bool told=false;
         play([&]{told=told||patternViewSnapshot().action==SMART_NO_READINGS;if(millis()>=stopNoReadings)engine.stopFlag_=true;});
         assert(attacks()==0&&told&&held.empty());engine.stopFlag_=false;}
        // Readings with mobs in sight (counts, nearest distances) and the map's name.
        auto seen=[&](uint8_t mobs,int ml,int mr,int dl,int dr,int wx=LIVE_NO_POS,const char* map=""){
            StatsReading r;r.hp=r.mana=500;r.x=r.y=500;r.mobs=mobs;r.ml=ml;r.mr=mr;r.dl=dl;r.dr=dr;r.wx=wx;r.wy=wx==LIVE_NO_POS?LIVE_NO_POS:500;
            statsName(map,r.map);liveStatsUpdate(r);};
        auto holds=[&](uint8_t key,uint32_t ms){int n=0;uint32_t at=0;for(auto e:hidEvents)if(e.key==key){if(e.down)at=e.at;else if(e.at-at==ms)++n;}return n;};
        // Walking holds the arrow (presses at least ms long, or still down) and hops (Alt alone) while it's down.
        auto heldFor=[&](uint8_t key,uint32_t ms){int n=0;bool down=false;uint32_t at=0;
            for(auto e:hidEvents)if(e.key==key){if(e.down){down=true;at=e.at;}else if(down){if(e.at-at>=ms)++n;down=false;}}
            if(down&&millis()-at>=ms){++n;}
            return n;};
        auto hopsWhileHeld=[&](uint8_t key){int n=0;bool down=false;for(auto e:hidEvents){if(e.key==key)down=e.down;else if(down&&e.down&&e.key==0&&e.mods==4)++n;}return n;};
        // A broken change fails these rather than hanging: each run is stopped after 60 s.
        auto bounded=[&](std::function<void()> each){uint32_t giveUp=millis()+60000;play([&,each]{each();if(millis()>=giveUp)engine.stopFlag_=true;});};
        // Walking home holds the arrow the whole way, hopping every walk_hold
        // (the test's draws give its minimum), not separate taps; it's let go
        // before attacking.
        q.walkHold={400,900};aware.setPattern(q);walked=false;calls=0;
        bounded([&]{if(++calls==1){liveStatsUpdate(500,500,-1,LIVE_OK,500,500,MOB_READ|MOB_LEFT,300,500);pinHere();return;}
                 walked=walked||hopsWhileHeld(L)>=2;
                 liveStatsUpdate(500,500,-1,LIVE_OK,500,500,walked?MOB_READ|MOB_LEFT:MOB_READ,walked?320:450,500);});
        assert(walked&&heldFor(L,800)==1&&holds(L,250)==0&&attacks()==3&&held.empty());
        {bool down=false;for(auto e:hidEvents){if(e.key==L)down=e.down;if(e.down&&e.key==0&&e.mods==5)assert(!down);}}   // never attacks with the arrow held
        // Approach: mobs in sight on the right, none in reach: walks right
        // until they're in reach, then attacks. The dashboard sees it.
        q.walkHold={280,650};q.approach=true;aware.setPattern(q);
        bool viewed=false;
        bounded([&]{bool near=hopsWhileHeld(R)>=2;seen(near?MOB_READ|MOB_RIGHT:MOB_READ,0,2,-1,near?60:180);
                 PatternView v=patternViewSnapshot();viewed=viewed||(v.active&&v.smart&&v.action==SMART_APPROACH_RIGHT&&!v.facingLeft);});
        assert(hopsWhileHeld(R)>=2&&attacks()==3&&firstAttack()>0&&viewed&&!patternViewSnapshot().active);
        // Approach off: the same mobs out of reach are waited for, not walked to.
        q.approach=false;aware.setPattern(q);stopAt=millis()+3000;
        bounded([&]{seen(MOB_READ,0,2,-1,180);if(millis()>=stopAt)engine.stopFlag_=true;});
        assert(heldFor(R,250)==0&&attacks()==0&&engine.stopFlag_);engine.stopFlag_=false;
        // Auto-pause at 30%: 6 mobs, then 1 left, out of reach: no walking over to it, it
        // waits for the respawn and attacks again once they're back in reach.
        q.autoPausePermille=300;q.attacksPerSet={6,6};q.approach=true;aware.setPattern(q);
        auto attackTimes=[&]{std::vector<uint32_t> t;for(auto e:hidEvents)if(e.down&&e.key==0&&e.mods==5)t.push_back(e.at);return t;};
        uint32_t fewAt=millis()+1000,backAt=millis()+6000;
        bounded([&]{uint32_t now=millis();bool few=now>=fewAt&&now<backAt;seen(few?MOB_READ:MOB_READ|MOB_RIGHT,0,few?1:6,-1,few?180:50);});
        auto times=attackTimes();
        assert(times.size()==6&&times.front()<fewAt&&times.back()>=backAt&&hopsWhileHeld(R)==0);
        for(uint32_t t:times)assert(t<fewAt+700||t>=backAt);
        // The last one in reach: attacked straight away, auto-pause or not.
        fewAt=millis()+1000;
        bounded([&]{seen(MOB_READ|MOB_RIGHT,0,millis()>=fewAt?1:6,-1,50);});
        times=attackTimes();
        assert(times.size()==6);
        for(size_t i=1;i<times.size();++i)assert(times[i]-times[i-1]<2000);
        // The last few never respawn: after AUTO_PAUSE_MAX_MS it walks over to them after all.
        {fewAt=millis()+1000;uint32_t walkedAt=0;
         bounded([&]{uint32_t now=millis();seen(now>=fewAt?MOB_READ:MOB_READ|MOB_RIGHT,0,now>=fewAt?1:6,-1,now>=fewAt?180:50);
                  if(!walkedAt&&hopsWhileHeld(R)>=1){walkedAt=now;}
                  if(walkedAt&&now>walkedAt+500)engine.stopFlag_=true;});
         assert(walkedAt>=fewAt+AUTO_PAUSE_MAX_MS);engine.stopFlag_=false;}
        q.approach=false;
        // A new map: home moves to where you arrive, so it doesn't walk back to the old map's spot.
        q.autoPausePermille=0;q.attacksPerSet={3,3};aware.setPattern(q);calls=0;mobsAt=millis()+2500;
        bounded([&]{if(++calls==1){seen(MOB_READ|MOB_LEFT,1,0,40,-1,300,"Henesys");pinHere();return;}
                 seen(millis()>=mobsAt?MOB_READ|MOB_LEFT:MOB_READ,millis()>=mobsAt,0,millis()>=mobsAt?40:-1,-1,900,"Ellinia");});
        assert(heldFor(L,250)==0&&heldFor(R,250)==0&&attacks()==3&&firstAttack()>=mobsAt);
        // Same map, same drift: walks home.
        calls=0;walked=false;
        bounded([&]{if(++calls==1){seen(MOB_READ|MOB_LEFT,1,0,40,-1,300,"Henesys");pinHere();return;}
                 walked=walked||heldFor(L,250)>=1;seen(walked?MOB_READ|MOB_LEFT:MOB_READ,walked,0,walked?40:-1,-1,walked?320:900,"Henesys");});
        assert(walked&&attacks()==3);
        // Home is a zone (home ± range, here 30% ± 10%): a mob inside it is fought where
        // it is, and with none left it waits there (no walking home); outside the zone
        // it walks back in first, a mob in reach or not.
        auto at=[&](int x,uint8_t mobs){
            StatsReading r;r.hp=r.mana=500;r.x=x;r.y=500;r.mobs=mobs;r.ml=(mobs&MOB_LEFT)?1:0;r.mr=(mobs&MOB_RIGHT)?1:0;
            r.dl=(mobs&MOB_LEFT)?40:-1;r.dr=(mobs&MOB_RIGHT)?40:-1;liveStatsUpdate(r);};
        q.walkHold={280,650};aware.setPattern(q);calls=0;
        uint32_t homeShownAt=0,noneFrom=0,mobsBack=0;
        bounded([&]{if(++calls==1){at(300,MOB_READ|MOB_RIGHT);pinHere();return;}      // pressed here: home is 30%
                 PatternView v=patternViewSnapshot();if(v.haveHome&&v.home==300&&!v.homeOnMap)homeShownAt=millis();
                 if(attacks()<1){at(360,MOB_READ|MOB_RIGHT);return;}          // a mob 6% from home: fought where it is
                 if(!noneFrom){noneFrom=millis();mobsBack=noneFrom+2500;}
                 at(360,millis()>=mobsBack?MOB_READ|MOB_RIGHT:MOB_READ);});   // none for 2.5 s, then back
        assert(attacks()==3&&hopsWhileHeld(L)==0&&hopsWhileHeld(R)==0&&homeShownAt&&held.empty());   // waited where it was
        {uint32_t during=0;for(auto e:hidEvents)if(e.down&&e.key==0&&e.mods==5&&e.at>=noneFrom+300&&e.at<mobsBack)++during;assert(during==0);}
        // At the zone's edge (8% right of home, past 3/4 of 10%) with a mob in reach only
        // further out: it stands still, no attacking the air and no walking, until a mob
        // turns up on the inside.
        {calls=0;uint32_t insideAt=0;
         bounded([&]{if(++calls==1){at(300,MOB_READ|MOB_RIGHT);insideAt=millis()+2500;pinHere();return;}
                  at(380,millis()>=insideAt?MOB_READ|MOB_LEFT:MOB_READ|MOB_RIGHT);});   // a mob on the inside after 2.5 s
         assert(hopsWhileHeld(L)==0&&hopsWhileHeld(R)==0&&attacks()==3&&firstAttack()>=insideAt&&held.empty());}
        // Outside the zone (42%, 12% from home) with a mob in reach: no running back, it
        // fights its way back: jump-attacks with the homeward arrow held, sliding home
        // while the arrow is down, and stops holding it once just inside (39%).
        {calls=0;int x=420;uint32_t insideAt=0;
         bounded([&]{if(++calls==1){at(300,MOB_READ|MOB_LEFT);pinHere();return;}
                  bool l=std::find(held.begin(),held.end(),L)!=held.end();if(l&&x>350)--x;if(!insideAt&&x<=390)insideAt=millis();
                  at(x,MOB_READ|MOB_LEFT);});
         int whileReturning=0,afterwards=0;bool down=false;
         for(auto e:hidEvents){if(e.key==L)down=e.down;else if(e.down&&e.key==0&&e.mods==5){if(down)++whileReturning;else if(insideAt&&e.at>=insideAt)++afterwards;}}
         assert(whileReturning>=1&&attacks()==3&&held.empty()&&insideAt);}   // attacked on the way back
        // Fluid movement (glide). Is each attack made with `key` held?
        auto attacksHolding=[&](uint8_t key){int n=0;bool down=false;for(auto e:hidEvents){if(e.key==key)down=e.down;else if(down&&e.down&&e.key==0&&e.mods==5)++n;}return n;};
        auto playWith=[&](std::function<long(long)> draw,std::function<void()> each){uint32_t giveUp=millis()+60000;each();testRandomHook=draw;
            testDelayHook=[&,each]{each();if(millis()>=giveUp)engine.stopFlag_=true;};hidEvents.clear();run(engine,{aware});testDelayHook={};testRandomHook={};};
        // Every set on the move: the arrow goes down once and stays down through all
        // the jump-attacks of both sets (no taps on the ground), let go at the end.
        {DynamicPattern g=p;g.sets={2,2};g.attacksPerSet={3,3};g.skills.clear();g.potions.clear();g.turnChancePermille=0;g.glidePermille=1000;
         aware.setPattern(g);
         playWith([](long){return 0L;},[&]{liveStatsUpdate(500,500,-1,LIVE_OK,500,500);});
         assert((dirs()==std::vector<uint8_t>{L})&&attacks()==6&&attacksHolding(L)==6&&held.empty()&&!heldMods);
         // Standing sets (the draw says no move): a turn is made in the air, the arrow
         // pressed after take-off (Alt down) and let go once the attack is, never on the ground.
         g.glidePermille=500;g.edgeMarginPermille=120;aware.setPattern(g);
         playWith([](long upper){return upper==1000?999L:0L;},[&]{liveStatsUpdate(500,500,-1,LIVE_OK,50,500);});   // left edge: turn right
         assert((dirs()==std::vector<uint8_t>{R})&&attacks()==6&&attacksHolding(R)==1);
         for(size_t i=0;i<hidEvents.size();++i)if(hidEvents[i].key==R){
             if(hidEvents[i].down)assert(hidEvents[i].mods&4);   // in the air: Alt (jump) held
             else assert(i>0&&hidEvents[i-1].key==0&&!hidEvents[i-1].down);}   // let go right after the attack
         assert(held.empty()&&!heldMods);
         // Smart, gliding: walking home runs straight into attacking, the arrow never let go.
         g.edgeMarginPermille=0;g.smart=true;g.homeRangePermille=100;g.sets={1,1};g.glidePermille=1000;g.walkHold={280,650};aware.setPattern(g);
         walked=false;calls=0;int wx=450;uint32_t lastStep=0;
         playWith([](long){return 0L;},[&]{if(++calls==1){liveStatsUpdate(500,500,-1,LIVE_OK,500,500,MOB_READ|MOB_LEFT,300,500);pinHere();return;}
                  walked=walked||hopsWhileHeld(L)>=2;
                  if(std::find(held.begin(),held.end(),L)!=held.end()&&wx>320&&millis()-lastStep>=20){--wx;lastStep=millis();}   // walking: 5% a second
                  liveStatsUpdate(500,500,-1,LIVE_OK,500,500,walked?MOB_READ|MOB_LEFT:MOB_READ,wx,500);});
         assert(walked&&(dirs()==std::vector<uint8_t>{L})&&attacks()==3&&attacksHolding(L)==3&&held.empty());}
        // Home on its own: Smart off, a home range set, drifted past it: walks back
        // (arrow held, hopping), then attacks there; nothing is waited for.
        {DynamicPattern g=p;g.sets={1,1};g.attacksPerSet={3,3};g.skills.clear();g.potions.clear();g.smart=false;g.homeRangePermille=100;g.walkHold={280,650};
         aware.setPattern(g);walked=false;calls=0;
         playWith([](long){return 0L;},[&]{if(++calls==1){liveStatsUpdate(500,500,-1,LIVE_OK,500,500,MOB_READ,300,500);pinHere();return;}   // home: map x 300
                  walked=walked||hopsWhileHeld(L)>=1;
                  liveStatsUpdate(500,500,-1,LIVE_OK,500,500,MOB_READ,walked?320:450,500);});   // drifted to 450, no mobs
         assert(walked&&attacks()==3&&held.empty());
         // No home range: Smart off attacks where it is, whatever the drift.
         g.homeRangePermille=0;aware.setPattern(g);calls=0;
         playWith([](long){return 0L;},[&]{++calls;liveStatsUpdate(500,500,-1,LIVE_OK,500,500,MOB_READ,calls==1?300:450,500);});
         assert(hopsWhileHeld(L)==0&&attacks()==3);}
        // Home stays where Set home put it. A map name misread for a moment ("-", or another
        // name under 3 s) doesn't drop it; a new map that stays has its own Set home, or none.
        {DynamicPattern g=p;g.sets={1,1};g.attacksPerSet={6,6};g.skills.clear();g.potions.clear();g.smart=true;g.homeRangePermille=100;
         aware.setPattern(g);calls=0;bool moved=false;uint32_t t0=0;
         homePinsLoad(nullptr,0);seen(MOB_READ|MOB_LEFT,1,0,40,-1,300,"Henesys");assert(homePin());   // Set home in Henesys at 30%
         playWith([](long){return 0L;},[&]{if(++calls==1)t0=millis();uint32_t t=millis()-t0;
                  const char* map=t>1000&&t<1400?"-":t>2000&&t<3500?"Ellinia":"Henesys";   // flickers, and another name for 1.5 s
                  seen(MOB_READ|MOB_LEFT,1,0,40,-1,300,map);
                  PatternView v=patternViewSnapshot();if(v.active&&(!v.haveHome||v.home!=300))moved=true;});
         assert(!moved&&attacks()==6);
         g.attacksPerSet={10,10};aware.setPattern(g);calls=0;bool none=false;   // long enough to see the 3 s pass
         playWith([](long){return 0L;},[&]{if(++calls==1)t0=millis();uint32_t t=millis()-t0;
                  bool there=t>1000;seen(MOB_READ|MOB_LEFT,1,0,40,-1,there?900:300,there?"Ellinia":"Henesys");   // really moved to Ellinia
                  PatternView v=patternViewSnapshot();if(there&&t>5000&&v.active&&!v.haveHome)none=true;});
         assert(none&&attacks()==10);                                      // no Set home in Ellinia: no home
         seen(MOB_READ|MOB_LEFT,1,0,40,-1,900,"Ellinia");assert(homePin());   // Set home in Ellinia at 90%
         calls=0;bool rehomed=false;
         playWith([](long){return 0L;},[&]{if(++calls==1)t0=millis();uint32_t t=millis()-t0;
                  bool there=t>1000;seen(MOB_READ|MOB_LEFT,1,0,40,-1,there?900:300,there?"Ellinia":"Henesys");
                  PatternView v=patternViewSnapshot();if(v.active&&v.haveHome&&v.home==900)rehomed=true;});
         assert(rehomed&&attacks()==10);homePinsLoad(nullptr,0);}
        // Can't walk home within 10 s (a wall): home is kept, and walking back is tried again 20 s later.
        {DynamicPattern g=p;g.sets={1,1};g.attacksPerSet={3,3};g.skills.clear();g.potions.clear();g.smart=true;g.homeRangePermille=100;g.walkHold={280,650};
         aware.setPattern(g);calls=0;bool moved=false;uint32_t t0=0;
         playWith([](long){return 0L;},[&]{if(++calls==1){t0=millis();seen(MOB_READ,0,0,-1,-1,300,"Henesys");pinHere();return;}
                  seen(MOB_READ,0,0,-1,-1,450,"Henesys");   // drifted 15%, and walking never gets you closer
                  PatternView v=patternViewSnapshot();if(v.active&&v.haveHome&&v.home!=300)moved=true;
                  if(millis()-t0>45000)engine.stopFlag_=true;});   // walk 10 s, give up 20 s, walk 10 s again
         int walks=0;bool down=false;uint32_t at=0;
         for(auto e:hidEvents)if(e.key==L){if(e.down){down=true;at=e.at;}else if(down){if(e.at-at>=5000)++walks;down=false;}}
         assert(!moved&&walks==2&&attacks()==0&&held.empty());engine.stopFlag_=false;}
        // The map position dropping out and coming back keeps the same home (in the other units).
        {DynamicPattern g=p;g.sets={1,1};g.attacksPerSet={4,4};g.skills.clear();g.potions.clear();g.smart=false;g.homeRangePermille=100;
         aware.setPattern(g);calls=0;bool sameSpot=true;
         playWith([](long){return 0L;},[&]{++calls;bool mapPos=calls<3||calls>6;   // map position, then the dot only, then the map position again
                  liveStatsUpdate(500,500,-1,LIVE_OK,420,500,0,mapPos?1420:LIVE_NO_POS,500);if(calls==1)pinHere();
                  PatternView v=patternViewSnapshot();if(v.active&&v.haveHome&&v.home!=(v.homeOnMap?1420:420))sameSpot=false;});
         assert(sameSpot&&hopsWhileHeld(L)==0&&hopsWhileHeld(R)==0&&attacks()==4);}
        // Support only (attack off): never jumps, attacks or presses an arrow; drinks by the
        // bar, uses skills once their wait is over, until stopped; stops on death too.
        {DynamicPattern g=p;g.attacking=false;g.potions.clear();g.skills.clear();
         DynamicSkill hp;hp.id="hp";hp.keycode=6;hp.chancePermille=1000;hp.repeats={1,1};hp.cooldown={3000,3000};hp.belowPercent=50;hp.hold={50,50};hp.after={100,100};g.potions.push_back(hp);
         DynamicSkill buff;buff.id="buff";buff.keycode=20;buff.chancePermille=1000;buff.repeats={1,1};buff.cooldown={4000,4000};buff.hold={50,50};buff.after={500,500};g.skills.push_back(buff);
         aware.setPattern(g);engine.dynamicSkillTimers_.clear();uint32_t t0=0;calls=0;bool told=false;
         playWith([](long){return 0L;},[&]{if(++calls==1)t0=millis();liveStatsUpdate(300,800,-1,LIVE_OK,500,500,MOB_READ|MOB_LEFT);   // HP 30%: low
                  told=told||patternViewSnapshot().action==SMART_SUPPORT;if(millis()-t0>9500)engine.stopFlag_=true;});
         auto presses=[&](uint8_t key){int n=0;for(auto e:hidEvents)if(e.down&&e.key==key)++n;return n;};
         bool movement=false;for(auto e:hidEvents)if(e.down&&(e.mods||e.key==L||e.key==R))movement=true;
         assert(!movement&&attacks()==0&&told);
         assert(presses(6)>=3&&presses(6)<=4);    // HP every 3 s while low
         assert(presses(20)>=2&&presses(20)<=3);  // the buff every 4 s (plus its own time)
         assert(held.empty()&&!heldMods);engine.stopFlag_=false;
         // Backup keys: the bar never rises after two drinks with the main key: the backup is used.
         g.potions[0].backupKeys={5};g.skills.clear();aware.setPattern(g);engine.dynamicSkillTimers_.clear();calls=0;
         playWith([](long){return 0L;},[&]{if(++calls==1)t0=millis();liveStatsUpdate(300,800,-1,LIVE_OK,500,500,MOB_READ);   // HP stuck at 30%
                  if(millis()-t0>9500)engine.stopFlag_=true;});
         assert(presses(6)==2&&presses(5)==2&&held.empty());engine.stopFlag_=false;
         // Each key its own amount: HP 30% of 1000 (700 to refill); the main key restores 350 (2 taps),
         // the backup 100 (7 taps), so the backup is tapped more for the same gap.
         g.potions[0].barMax=1000;g.potions[0].perTap=350;g.potions[0].backupPerTap={100};aware.setPattern(g);engine.dynamicSkillTimers_.clear();calls=0;
         playWith([](long){return 0L;},[&]{if(++calls==1)t0=millis();liveStatsUpdate(300,800,-1,LIVE_OK,500,500,MOB_READ);
                  if(millis()-t0>9500)engine.stopFlag_=true;});
         assert(presses(6)==2*2&&presses(5)>=7&&presses(5)%7==0&&held.empty());engine.stopFlag_=false;   // 2 drinks of 2 taps, then 7 taps a drink
         // Death stops it.
         uint32_t dieAt=millis()+1500;calls=0;
         playWith([](long){return 0L;},[&]{liveStatsUpdate(800,800,-1,millis()>=dieAt?LIVE_DEAD:LIVE_OK);});
         assert(engine.stopFlag_&&held.empty());engine.stopFlag_=false;
         liveStatsUpdate(-1,-1,-1);testClock+=LIVE_STATS_STALE_MS;}
        // Home only comes from Set home: pressing the pattern's button never sets one. With no
        // Set home on the map there's no home, press after press (the dashboard says so); with
        // one, every press uses it, wherever you stand.
        {DynamicPattern g=p;g.sets={1,1};g.attacksPerSet={2,2};g.skills.clear();g.potions.clear();g.homeRangePermille=100;
         Step once=dynamic;once.setPattern(g);
         homePinsLoad(nullptr,0);
         auto press=[&](int x,bool& anyHome,int& seenHome,bool& noHome){anyHome=false;seenHome=-1;noHome=false;testRandomHook=[](long){return 0L;};
             testDelayHook=[&,x]{liveStatsUpdate(500,500,-1,LIVE_OK,x,500,MOB_READ|MOB_LEFT);
                 PatternView v=patternViewSnapshot();if(v.active&&v.haveHome){anyHome=true;seenHome=v.home;}if(v.active&&!v.haveHome&&v.homeRange)noHome=true;};
             liveStatsUpdate(500,500,-1,LIVE_OK,x,500,MOB_READ|MOB_LEFT);hidEvents.clear();
             KeyBinding key;key.steps={once};engine.oneShot_=true;engine.stopFlag_=false;engine.runMacro(key);testDelayHook={};testRandomHook={};};
         bool anyHome,noHome;int seenHome;
         for(int x: {300,360,420}){press(x,anyHome,seenHome,noHome);assert(!anyHome&&noHome&&attacks()==2);}
         liveStatsUpdate(500,500,-1,LIVE_OK,330,500,MOB_READ|MOB_LEFT);assert(homePin());   // Set home at 33%
         for(int x: {300,360,420}){press(x,anyHome,seenHome,noHome);assert(anyHome&&seenHome==330&&!noHome);}
         homePinsLoad(nullptr,0);}
        // Characters: a pattern using the active character's potions drinks with its key, and
        // two such patterns share the wait (switching patterns doesn't drink again); a pattern
        // with its own potions keeps its own.
        {Character war;war.id="war";war.name="Warrior";
         DynamicSkill hp;hp.id="hp";hp.keycode=7;hp.chancePermille=1000;hp.repeats={1,1};hp.cooldown={60000,60000};hp.hold={50,50};hp.after={100,100};war.potions.push_back(hp);
         engine.config().characters={war};engine.config().activeCharacter="war";
         DynamicPattern a=p;a.id="pa";a.attacking=false;a.potions.clear();a.skills.clear();a.charPotions=true;
         DynamicPattern b=a;b.id="pb";
         DynamicPattern own=a;own.id="po";own.charPotions=false;own.potions={hp};
         auto presses=[&](uint8_t key){int n=0;for(auto e:hidEvents)if(e.down&&e.key==key)++n;return n;};
         auto play2s=[&](const DynamicPattern& g){aware.setPattern(g);uint32_t t0=millis();
             playWith([](long){return 0L;},[&,t0]{liveStatsUpdate(800,800,-1,LIVE_OK,500,500,MOB_READ);if(millis()-t0>2000)engine.stopFlag_=true;});engine.stopFlag_=false;};
         engine.dynamicSkillTimers_.clear();
         play2s(a);assert(presses(7)==1);      // the character's key
         play2s(b);assert(presses(7)==0);      // another pattern, same character: its wait still runs
         play2s(own);assert(presses(7)==1);    // own potions: its own wait
         engine.config().characters.clear();engine.config().activeCharacter.clear();
         play2s(b);assert(presses(7)==0);}     // no character: the pattern's own (none here)
        // The zone's hard edge: moving while attacking towards mobs on the right, the
        // character slides 1 tenth of a % every few ms while an arrow is held. Home 30%,
        // boundary 10%: the arrow is let go of past 37.5%, so it never leaves 20-40%.
        {DynamicPattern g=p;g.sets={2,2};g.attacksPerSet={8,8};g.skills.clear();g.potions.clear();g.glidePermille=1000;g.smart=false;g.homeRangePermille=100;
         aware.setPattern(g);int x=300,maxX=300,minX=300;calls=0;
         liveStatsUpdate(500,500,-1,LIVE_OK,300,500,MOB_READ|MOB_RIGHT);pinHere();   // Set home at 30%
         playWith([](long){return 0L;},[&]{
             bool r=std::find(held.begin(),held.end(),R)!=held.end(),l=std::find(held.begin(),held.end(),L)!=held.end();
             if(++calls>1){x+=r?1:0;x-=l?1:0;}maxX=std::max(maxX,x);minX=std::min(minX,x);
             liveStatsUpdate(500,500,-1,LIVE_OK,x,500,MOB_READ|MOB_RIGHT);});
         assert(maxX<400&&minX>200&&attacks()==16&&held.empty());homePinsLoad(nullptr,0);}
        // With a jump's momentum: a jump carries on through the air at the speed it took off
        // with (600 ms), readings come 40 ms late and only every 0.5%, and turns are taps
        // (a small step). Whether moving while attacking or not, with mobs either side, the
        // character never crosses the zone's line (home 30%, 10% and a narrow 5%).
        auto physics=[&](DynamicPattern g,uint32_t ms,double speed){
            aware.setPattern(g);double x=300,vx=0;bool air=false,l=false,r=false;uint32_t land=0,last=millis(),next=0;size_t seenEv=0;int sent=300;double worst=0;
            std::vector<std::pair<uint32_t,int>> pipe;uint32_t t0=millis(),flip=0;int side=0;
            auto step=[&](uint32_t to){while(last<to){uint32_t d=std::min<uint32_t>(to-last,5);last+=d;if(air&&last>=land)air=false;if(!air)vx=((r?1:0)-(l?1:0))*speed;x+=vx*d;}};
            auto read=[&]{StatsReading rd;rd.hp=rd.mana=800;rd.x=sent;rd.y=500;rd.mobs=MOB_READ|(side?MOB_RIGHT:MOB_LEFT);rd.ml=side?0:2;rd.mr=side?2:0;rd.dl=side?-1:40;rd.dr=side?40:-1;rd.ir=1;liveStatsUpdate(rd);};
            read();pinHere();   // Set home at 30%
            playWith([](long upper){return upper>1?upper/2:0L;},[&]{
                uint32_t now=millis();
                for(;seenEv<hidEvents.size();++seenEv){const HidEvent& e=hidEvents[seenEv];step(e.at);
                    if(e.key==L)l=e.down;else if(e.key==R)r=e.down;
                    else if(e.key==0&&e.down&&(e.mods&4)&&!air){air=true;land=e.at+600;vx=((r?1:0)-(l?1:0))*speed;}}
                step(now);worst=std::max(worst,std::fabs(x-300)-g.homeRangePermille);
                if(now>=flip){flip=now+1500;side=!side;}
                if(now>=next){next=now+70;pipe.push_back({now+40,(int)std::lround(x)});}
                while(!pipe.empty()&&pipe.front().first<=now){if(std::abs(pipe.front().second-sent)>=5)sent=pipe.front().second;pipe.erase(pipe.begin());}
                read();if(now-t0>ms)engine.stopFlag_=true;});
            engine.stopFlag_=false;return worst;};
        {DynamicPattern g=p;g.sets={100,100};g.attacksPerSet={2,4};g.skills.clear();g.potions.clear();g.smart=false;g.homeRangePermille=100;g.turnChancePermille=500;
         for(uint16_t glide: {0,600,1000})for(uint16_t range: {100,50}){g.glidePermille=glide;g.homeRangePermille=range;
             double worst=physics(g,30000,0.1);assert(worst<=0);}
         assert(held.empty());homePinsLoad(nullptr,0);}
        // The map's edge the same way: "turn at map edges" 5%, moving while attacking towards
        // mobs on the left from 20%, sliding while an arrow is held: it stops near 5%, not 1%.
        {DynamicPattern g=p;g.sets={2,2};g.attacksPerSet={8,8};g.skills.clear();g.potions.clear();g.glidePermille=1000;g.smart=false;g.edgeMarginPermille=50;
         aware.setPattern(g);int x=200,minX=200;calls=0;
         playWith([](long){return 0L;},[&]{
             bool r=std::find(held.begin(),held.end(),R)!=held.end(),l=std::find(held.begin(),held.end(),L)!=held.end();
             if(++calls>1){x+=r?1:0;x-=l?1:0;}minX=std::min(minX,x);
             liveStatsUpdate(500,500,-1,LIVE_OK,x,500,MOB_READ|MOB_LEFT);});
         assert(minX>=40&&attacks()==16&&held.empty());}
        // A Set home made from the minimap dot is shown on the dashboard and the game layer
        // (every pattern, not only Smart), and kept as the same spot once map positions come.
        {DynamicPattern g=p;g.sets={1,1};g.attacksPerSet={4,4};g.skills.clear();g.potions.clear();aware.setPattern(g);
         int homeDot=-1,homeMap=-1;calls=0;
         liveStatsUpdate(500,500,-1,LIVE_OK,420,500,0,LIVE_NO_POS,500);pinHere();   // Set home from the dot at 42%
         playWith([](long){return 0L;},[&]{++calls;liveStatsUpdate(500,500,-1,LIVE_OK,420,500,0,calls>3?1500:LIVE_NO_POS,500);
                  PatternView v=patternViewSnapshot();if(v.haveHome&&!v.homeOnMap)homeDot=v.home;if(v.haveHome&&v.homeOnMap)homeMap=v.home;
                  char form[48];homeReply(form,sizeof(form));if(v.haveHome&&v.homeOnMap)assert(std::string(form)=="home=1500&hm=1&hr=0");});
         assert(homeDot==420&&homeMap==1500);
         char form[48];homeReply(form,sizeof(form));assert(!form[0]);homePinsLoad(nullptr,0);}   // nothing playing: no home to tell
        // Set home: one home per map, where you stood. On its map it's always home, whatever
        // spot a pattern starts from, press after press; pinned again while playing it's taken
        // up at once; another map's doesn't count (a map without one has no home), and
        // pinning there doesn't replace this one.
        {DynamicPattern g=p;g.sets={1,1};g.attacksPerSet={4,4};g.skills.clear();g.potions.clear();g.smart=false;g.homeRangePermille=0;aware.setPattern(g);
         homePinsLoad(nullptr,0);homePinsTakeDirty();
         seen(MOB_READ|MOB_LEFT,1,0,40,-1,600,"Henesys");assert(homePin()&&homePinsTakeDirty()&&!homePinsTakeDirty());   // saved once
         PinnedHome pin=homePinned("Henesys");assert(pin.set&&pin.home==600&&pin.onMap&&std::string(pin.map)=="Henesys");
         assert(!homePinned("Ellinia").set&&homePinnedHere().home==600);
         for(int start: {300,450,820}){   // new presses from anywhere: home stays put
             bool always=true;
             playWith([](long){return 0L;},[&,start]{seen(MOB_READ|MOB_LEFT,1,0,40,-1,start,"Henesys");
                      PatternView v=patternViewSnapshot();if(v.active&&(!v.haveHome||v.home!=600||!v.homePinned))always=false;});
             assert(always&&attacks()==4);}
         assert(homeUnpin()&&!homePinned("Henesys").set&&!homeUnpin());
         calls=0;int last=-1;bool pinnedLast=false;
         playWith([](long){return 0L;},[&]{++calls;int x=calls<4?300:500;seen(MOB_READ|MOB_LEFT,1,0,40,-1,x,"Henesys");
                  if(calls==4)assert(homePin());   // pressed mid-play, standing at 50%
                  PatternView v=patternViewSnapshot();if(v.active&&v.haveHome){last=v.home;pinnedLast=v.homePinned;}});
         assert(last==500&&pinnedLast&&attacks()==4);
         seen(MOB_READ|MOB_LEFT,1,0,40,-1,700,"Ellinia");assert(homePin());   // Ellinia's own
         assert(homePinned("Henesys").home==500&&homePinned("Ellinia").home==700);
         last=-1;
         playWith([](long){return 0L;},[&]{seen(MOB_READ|MOB_LEFT,1,0,40,-1,300,"Henesys");
                  PatternView v=patternViewSnapshot();if(v.active&&v.haveHome){last=v.home;pinnedLast=v.homePinned;}});
         assert(last==500&&pinnedLast);                                     // Henesys keeps 50%
         last=-1;
         playWith([](long){return 0L;},[&]{seen(MOB_READ|MOB_LEFT,1,0,40,-1,300,"Kerning_City");
                  PatternView v=patternViewSnapshot();if(v.active&&v.haveHome){last=v.home;pinnedLast=v.homePinned;}});
         assert(last==-1);                                                  // no Set home there: no home at all
         // Full: the one pinned longest ago makes room.
         for(int i=0;i<MAX_PINNED_HOMES;++i){char name[16];std::snprintf(name,sizeof(name),"Map_%d",i);seen(MOB_READ,0,0,-1,-1,100+i,name);assert(homePin());}
         assert(!homePinned("Henesys").set&&!homePinned("Ellinia").set&&homePinned("Map_0").home==100&&homePinned("Map_15").home==115);
         PinnedHome all[MAX_PINNED_HOMES];assert(homePinsCopy(all,MAX_PINNED_HOMES)==MAX_PINNED_HOMES);
         homePinsLoad(all,2);assert(homePinsCopy(all,MAX_PINNED_HOMES)==2&&homePinned(all[0].map).home==all[0].home);
         homePinsLoad(nullptr,0);homePinsTakeDirty();}
        // A Set home button (directly, or its one recording) pins home and never stops what's
        // playing; the "home" step inside a recording pins too, and isn't sent to the PC script.
        {Step tool;tool.type=StepType::TOOL;tool.value=TOOL_HOME;
         Workflow w;w.id="sethome";w.steps={tool};engine.cfg_.workflows.push_back(w);
         Step call;call.type=StepType::CALL;call.setText("sethome");
         if(engine.cfg_.layers.empty())engine.cfg_.layers.emplace_back();
         engine.layer_=0;
         engine.cfg_.layers[0].keys[0].steps={call};engine.cfg_.layers[0].keys[0].trigger=TriggerMode::TOGGLE;
         engine.cfg_.layers[0].keys[1].steps={tool};
         assert(engine.isSetHome(engine.cfg_.layers[0].keys[0])&&engine.isSetHome(engine.cfg_.layers[0].keys[1]));
         seen(MOB_READ,0,0,-1,-1,420,"Henesys");
         uint32_t before=homePinsVersion();
         engine.running_=true;engine.runningKey_=2;engine.stopFlag_=false;   // something playing on button 3
         engine.onKeyDown(0);assert(!engine.stopFlag_&&homePinsVersion()==before+1&&homePinned("Henesys").home==420);
         engine.onKeyDown(1);assert(!engine.stopFlag_&&homePinsVersion()==before+2);
         engine.running_=false;engine.runningKey_=-1;
         char keys[32];toolKeysTake(keys,sizeof(keys));
         run(engine,{tool});assert(homePinsVersion()==before+3);
         toolKeysTake(keys,sizeof(keys));assert(!keys[0]);
         engine.cfg_.layers[0].keys[0].steps.clear();engine.cfg_.layers[0].keys[1].steps.clear();engine.cfg_.workflows.pop_back();
         homePinsLoad(nullptr,0);homePinsTakeDirty();}
        liveStatsUpdate(-1,-1,-1);testClock+=LIVE_STATS_STALE_MS;   // leave no fresh data for later tests
    }
    // Cancellation at each hold phase leaves no Ctrl/Alt/arrow/skill input down.
    p.skills[0].chancePermille=1000;p.skills[0].cooldown={0,0};dynamic.setPattern(p);
    for(uint32_t offset: {1U,105U,150U,185U,210U,720U,800U,1700U}){
        uint32_t end=millis()+offset;testDelayHook=[&]{if(millis()>=end)engine.stopFlag_=true;};
        run(engine,{dynamic});testDelayHook={};assert(held.empty()&&!heldMods);
    }
    // Dynamic timing is refused inside a parent-held chord rather than
    // releasing/changing the parent's modifiers unexpectedly.
    ctrlDurations.clear();run(engine,{attackDown,dynamic,ctrlUp});assert(ctrlDurations.size()==1);
    // Screen reader keys on the pad: queued for the script, nothing typed.
    {
        char keys[64];toolKeysTake(keys,sizeof(keys));   // start empty
        Step mark;mark.type=StepType::TOOL;mark.value=TOOL_MARK;Step map=mark;map.value=TOOL_MAP;
        taps.clear();hidEvents.clear();run(engine,{mark,map,mark});
        assert(taps.empty()&&std::none_of(hidEvents.begin(),hidEvents.end(),[](const HidEvent& e){return e.down;}));   // no key went down
        toolKeysTake(keys,sizeof(keys));assert(std::string(keys)=="mark,map,mark");
        toolKeysTake(keys,sizeof(keys));assert(!keys[0]);   // taken once
        run(engine,{mark});testClock+=TOOL_KEY_MAX_AGE_MS+1;toolKeysTake(keys,sizeof(keys));assert(!keys[0]);   // stale: dropped
    }
    std::cout << "workflow engine tests passed\n";
}
