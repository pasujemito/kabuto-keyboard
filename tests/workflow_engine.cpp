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
    // HP/Mana potions fire on their own timers, before skills, never inside a chord.
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
        for(auto e:hidEvents)if(e.key==6||e.key==0x19)assert(!e.mods);
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
        for(auto e:hidEvents)if(e.key==6)assert(!e.mods);   // never inside the jump/attack chord
        drink(800,900);     // both bars healthy: neither drinks, not even on the timer
        assert(pressCount(6)==0&&pressCount(0x19)==0);
        liveStatsUpdate(300,300,-1);testClock+=LIVE_STATS_STALE_MS;engine.dynamicSkillTimers_.clear();hidEvents.clear();run(engine,{live});
        assert(pressCount(6)==1&&pressCount(0x19)==1);   // stale reading: timers, once each
        // Real amounts: HP 5000 at 30% is 3500 short; 800 a tap = 4 taps (a 5th would waste).
        q.potions[0].barMax=5000;q.potions[0].perTap=800;q.attacksPerSet={1,1};live.setPattern(q);drink(300,-1);
        assert(pressCount(6)==4);
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
        // Near the left edge while facing left (the first random draw): turns right before attacking.
        q.edgeMarginPermille=120;aware.setPattern(q);
        play([&]{liveStatsUpdate(500,500,-1,LIVE_OK,50,500);});
        assert((dirs()==std::vector<uint8_t>{L,R,R}));   // between sets it taps the way it faces
        // A mob on the right only: face it, and keep facing it at the set boundary.
        q.edgeMarginPermille=0;q.faceMobs=true;aware.setPattern(q);
        play([&]{liveStatsUpdate(500,500,-1,LIVE_OK,500,500,MOB_RIGHT);});
        assert((dirs()==std::vector<uint8_t>{L,R,R}));
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
        play([&]{if(++calls==1){liveStatsUpdate(500,500,-1,LIVE_OK,500,500,MOB_READ|MOB_LEFT,300,500);return;}   // home: map x 300
                 auto d=dirs();walked=walked||(d.size()>=2&&d.back()==L);
                 liveStatsUpdate(500,500,-1,LIVE_OK,500,500,walked?MOB_READ|MOB_LEFT:MOB_READ,walked?320:450,500);});   // drifted to 450
        assert(walked&&attacks()==3);
        // Stop pressed while waiting for mobs: returns at once, nothing held.
        uint32_t stopAt=millis()+1500;
        play([&]{liveStatsUpdate(500,500,-1,LIVE_OK,500,500,MOB_READ);if(millis()>=stopAt)engine.stopFlag_=true;});
        assert(attacks()==0&&held.empty()&&!heldMods&&engine.stopFlag_);engine.stopFlag_=false;
        // Without a mob detector (no "mobs" in the readings) smart mode just attacks.
        play([&]{liveStatsUpdate(500,500,-1,LIVE_OK,500,500,0);});
        assert(attacks()==3);
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
    std::cout << "workflow engine tests passed\n";
}
