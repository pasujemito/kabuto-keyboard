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
#include <iostream>

uint32_t testClock = 0;
std::function<void()> testDelayHook;
HidKeyboard Keyboard;
std::vector<uint8_t> taps, held;
unsigned releases = 0;
void HidKeyboard::tap(uint8_t key, uint8_t, uint16_t) { taps.push_back(key); }
void HidKeyboard::pressKey(uint8_t key, uint8_t) { held.push_back(key); }
void HidKeyboard::releaseKey(uint8_t) {}
void HidKeyboard::releaseModifiers(uint8_t) {}
void HidKeyboard::releaseAll() { held.clear(); ++releases; }
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
    std::cout << "workflow engine tests passed\n";
}
