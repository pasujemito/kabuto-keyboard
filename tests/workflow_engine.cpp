#include <Arduino.h>
#include <vector>
#include <map>
#include <string>
// Inspect interpreter state without adding a production test-only API.
#define private public
#include "../src/macro_engine.h"
#undef private
#include "../src/hid_keyboard.h"
#include <cassert>
#include <algorithm>
#include <iostream>

uint32_t testClock = 0;
std::function<void()> testDelayHook;
std::function<long(long)> testRandomHook;
HidKeyboard Keyboard;
std::vector<uint8_t> taps, held;
unsigned releases = 0;
uint8_t heldMods=0;
uint32_t ctrlStarted=0;
std::vector<uint32_t> ctrlDurations;
struct HidEvent { uint32_t at; uint8_t key; uint8_t mods; bool down; };
std::vector<HidEvent> hidEvents;
std::vector<uint8_t> tapModifiers;

void HidKeyboard::tap(uint8_t key, uint8_t, uint16_t) { taps.push_back(key);tapModifiers.push_back(heldMods); }
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
}
void HidKeyboard::releaseAll() { releaseModifiers(255);held.clear(); ++releases; }
void HidKeyboard::typeString(const String&) {}
void HidKeyboard::consumerPress(uint16_t) {}
void HidKeyboard::consumerRelease() {}
bool loadConfig(Config&) { return false; }
bool saveConfig(const Config&) { return false; }

Step tap(uint8_t code) { Step s; s.type=StepType::KEY; s.keycode=code; return s; }
Step call(const char* id) { Step s; s.type=StepType::CALL; s.text=id; return s; }
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
    choose.choices={a,b};
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
    choose.choices.clear();MacroRef legacy;legacy.layer=0;legacy.key=1;choose.choices.push_back(legacy);
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
    Step combat;combat.type=StepType::COMBAT;combat.value=90000;combat.maxValue=90000;combat.choices={cr};
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
    std::cout << "workflow engine tests passed\n";
}
