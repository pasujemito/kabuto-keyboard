#include <algorithm>
#include "macro_engine.h"
#include "live_stats.h"
#include "hid_keyboard.h"
#include "keymap.h"
#include "storage.h"
#include "workflow_selection.h"
#include <cstdio>
#include <cstring>

MacroEngine Macros;

static constexpr size_t MACRO_LOG_CAPACITY = 96;
static MacroLogEntry macroLog[MACRO_LOG_CAPACITY];
static size_t macroLogCount = 0;
static size_t macroLogNext = 0;
static uint32_t macroLogNextId = 1;
static portMUX_TYPE macroLogMux = portMUX_INITIALIZER_UNLOCKED;

struct CmdMsg { EngineCmd cmd; int16_t a; int16_t b; char text[48] = {}; };

const KeyBinding* Config::findWorkflow(const std::string& id) const {
    for (const auto& workflow : workflows)
        if (workflow.id == id) return &workflow;
    return nullptr;
}

void Config::ensureLayer(size_t n) {
    while (layers.size() <= n) {
        Layer l;
        l.name = "Layer " + std::to_string(layers.size());
        layers.push_back(l);
    }
}

// --- interruptible delay ---------------------------------------------------
static void sleepMs(uint32_t ms, volatile bool& stop) {
    const uint32_t chunk = 5;
    uint32_t started = millis();
    while (true) {
        uint32_t elapsed = millis() - started;
        if (stop || elapsed >= ms) return;
        uint32_t remaining = ms - elapsed;
        uint32_t step = remaining < chunk ? remaining : chunk;
        TickType_t ticks = pdMS_TO_TICKS(step);
        vTaskDelay(ticks ? ticks : 1);
    }
}

static uint32_t randomizedDuration(uint32_t ms, bool enabled, bool keyTiming = false) {
    if (!enabled || ms == 0) return ms;
    int32_t jitter = keyTiming ? random(-6L, 7L) :
                     ms <= 5000 ? random(-15L, 16L) :
                     ms <= 40000 ? random(-200L, 201L) :
                                   random(-5000L, 5001L);
    int32_t duration = (int32_t)ms + jitter;
    return duration > 0 ? (uint32_t)duration : 1;
}

// Explicit timing ranges take precedence over global jitter.
static uint32_t stepDuration(const Step& step, bool jitter, bool keyTiming = false) {
    if (step.maxValue >= step.value && step.maxValue)
        return step.value + (uint32_t)random((long)(step.maxValue - step.value + 1));
    return randomizedDuration(step.value, jitter, keyTiming);
}

// Give the scheduler at least one tick. The macro task runs at a higher
// priority than the Arduino loop (which scans the keys) on the same core, so a
// macro with no delays in it would otherwise starve key scanning - and then the
// key that should stop it can never be read.
static inline void yieldTick() { vTaskDelay(1); }

void MacroEngine::begin() {
    cfg_.ensureLayer(0);
    if (!cmdQueue_) cmdQueue_ = xQueueCreate(32, sizeof(CmdMsg));
}

uint32_t MacroEngine::appendLog(const MacroLogEntry& entry) {
    portENTER_CRITICAL(&macroLogMux);
    MacroLogEntry& stored = macroLog[macroLogNext];
    stored = entry;
    stored.id = macroLogNextId++;
    macroLogNext = (macroLogNext + 1) % MACRO_LOG_CAPACITY;
    if (macroLogCount < MACRO_LOG_CAPACITY) macroLogCount++;
    uint32_t id = stored.id;
    portEXIT_CRITICAL(&macroLogMux);
    return id;
}

void MacroEngine::updateLogDuration(uint32_t id, uint32_t durationMs, bool complete) {
    if (!id) return;
    portENTER_CRITICAL(&macroLogMux);
    for (size_t offset = 0; offset < macroLogCount; offset++) {
        size_t slot = (macroLogNext + MACRO_LOG_CAPACITY - 1 - offset) % MACRO_LOG_CAPACITY;
        MacroLogEntry& entry = macroLog[slot];
        if (entry.id == id) {
            if (durationMs > entry.durationMs) entry.durationMs = durationMs;
            if (complete) entry.complete = true;
            break;
        }
    }
    portEXIT_CRITICAL(&macroLogMux);
}

size_t MacroEngine::copyLog(MacroLogEntry* entries, size_t capacity) const {
    if (!entries || !capacity) return 0;
    portENTER_CRITICAL(&macroLogMux);
    size_t copyCount = macroLogCount < capacity ? macroLogCount : capacity;
    size_t skipped = macroLogCount - copyCount;
    size_t slot = (macroLogNext + MACRO_LOG_CAPACITY - macroLogCount + skipped) % MACRO_LOG_CAPACITY;
    for (size_t index = 0; index < copyCount; index++) {
        entries[index] = macroLog[slot];
        slot = (slot + 1) % MACRO_LOG_CAPACITY;
    }
    portEXIT_CRITICAL(&macroLogMux);
    return copyCount;
}

void MacroEngine::clearLog() {
    portENTER_CRITICAL(&macroLogMux);
    macroLogCount = 0;
    macroLogNext = 0;
    portEXIT_CRITICAL(&macroLogMux);
}

// --- command queue ---------------------------------------------------------
bool MacroEngine::post(EngineCmd cmd, int a, int b) {
    if (!cmdQueue_) return false;
    CmdMsg m{};
    m.cmd = cmd;
    m.a = (int16_t)a;
    m.b = (int16_t)b;
    return xQueueSend(cmdQueue_, &m, 0) == pdTRUE;
}

bool MacroEngine::postText(const char* text) {
    if (!cmdQueue_ || !text || !text[0]) return false;
    CmdMsg m{};
    m.cmd = EngineCmd::LIVE_TEXT;
    std::strncpy(m.text, text, sizeof(m.text) - 1);
    return xQueueSend(cmdQueue_, &m, 0) == pdTRUE;
}

void MacroEngine::processCommands() {
    if (!cmdQueue_) return;
    CmdMsg m;
    while (xQueueReceive(cmdQueue_, &m, 0) == pdTRUE) {
        switch (m.cmd) {
            case EngineCmd::RELOAD: load();        break;
            case EngineCmd::LAYER:  setLayer(m.a); break;
            case EngineCmd::STOP:   stopAll();     break;
            case EngineCmd::TEST:
                setLayer(m.a);
                startMacroTask(m.b, /*oneShot=*/true);
                break;
            // --- live passthrough (only used while no macro is running) ---
            case EngineCmd::LIVE_DOWN:
                if (!running_) Keyboard.pressKey((uint8_t)m.a);
                break;
            case EngineCmd::LIVE_UP:
                if (!running_) Keyboard.releaseKey((uint8_t)m.a);
                break;
            case EngineCmd::LIVE_MEDIA:
                if (!running_) {
                    Keyboard.consumerPress((uint16_t)m.a);
                    vTaskDelay(pdMS_TO_TICKS(12));
                    Keyboard.consumerRelease();
                }
                break;
            case EngineCmd::LIVE_MODDOWN:
                if (!running_) Keyboard.pressKey(KC_NONE, (uint8_t)m.b);
                break;
            case EngineCmd::LIVE_MODUP:
                if (!running_) Keyboard.releaseModifiers((uint8_t)m.b);
                break;
            case EngineCmd::LIVE_RELEASEALL:
                if (!running_) Keyboard.releaseAll();
                break;
            case EngineCmd::LIVE_TEXT:
                if (!running_) Keyboard.typeString(String(m.text));
                break;
            // --- run-mode: emulate a real pad key press/release ---
            case EngineCmd::KEYDOWN:
                setLayer(m.b);
                onKeyDown(m.a);
                break;
            case EngineCmd::KEYUP:
                setLayer(m.b);
                onKeyUp(m.a);
                break;
        }
    }
}

// --- loop validation -------------------------------------------------------
void MacroEngine::validateLoops(KeyBinding& kb) {
    std::vector<int> stack;
    for (auto& s : kb.steps) s.matchIndex = -1;
    for (int i = 0; i < (int)kb.steps.size(); i++) {
        if (kb.steps[i].type == StepType::LOOP_START) {
            stack.push_back(i);
        } else if (kb.steps[i].type == StepType::LOOP_END) {
            if (!stack.empty()) {
                int start = stack.back(); stack.pop_back();
                kb.steps[start].matchIndex = i;
                kb.steps[i].matchIndex = start;
            }
            // unmatched LOOP_END is ignored at run time
        }
    }
    // unmatched LOOP_START (matchIndex == -1) will be skipped at run time
}

void MacroEngine::commit() {
    for (auto& workflow : cfg_.workflows) validateLoops(workflow);
    for (auto& layer : cfg_.layers)
        for (auto& kb : layer.keys)
            validateLoops(kb);
}

bool MacroEngine::load() {
    // Don't swap config out from under a running macro.
    stopAll();
    bool ok = loadConfig(cfg_);
    utilityClockStarted_ = false;
    utilityLastRun_.clear();
    dynamicSkillTimers_.clear();
    cfg_.ensureLayer(0);
    commit();
    if (layer_ >= (int)cfg_.layers.size()) layer_ = 0;
    return ok;
}

void MacroEngine::setLayer(int n) {
    if (n >= 0 && n < (int)cfg_.layers.size()) layer_ = n;
}

// --- step execution --------------------------------------------------------
void MacroEngine::executeSteps(const std::vector<Step>& steps, volatile bool& stop,
                               ExecutionState& state, uint8_t depth) {
    // Bound recursion and reject cycles, including legacy layer/key references.
    if (depth > 8 || std::find(callStack_.begin(), callStack_.end(), &steps) != callStack_.end()) return;
    callStack_.push_back(&steps);
    struct Frame { int startIdx; int endIdx; uint32_t remaining; bool infinite; uint32_t iteration; };
    std::vector<Frame> loops;

    // 'label' overrides the step's own text in the log (workflow names, skips).
    auto logStep = [&](const Step& step, int stepIndex, uint32_t startedAt,
                       uint32_t durationMs, bool complete,
                       const char* label = nullptr) -> uint32_t {
        MacroLogEntry entry{};
        entry.elapsedMs = startedAt - macroStartedAt_;
        entry.durationMs = durationMs;
        entry.run = macroRunId_;
        entry.pass = macroPass_;
        entry.step = stepIndex + 1;
        entry.type = step.type;
        entry.keycode = step.keycode;
        entry.modifiers = step.modifiers;
        entry.value = step.value;
        entry.complete = complete;
        const char* text = label ? label : step.text().c_str();
        std::strncpy(entry.text, text, sizeof(entry.text) - 1);
        size_t pathLength = 0;
        for (const Frame& frame : loops) {
            int written = std::snprintf(entry.loopPath + pathLength,
                                        sizeof(entry.loopPath) - pathLength,
                                        "%s%d#%lu", pathLength ? "/" : "",
                                        frame.startIdx + 1,
                                        (unsigned long)frame.iteration);
            if (written < 0 || (size_t)written >= sizeof(entry.loopPath) - pathLength) break;
            pathLength += (size_t)written;
        }
        return appendLog(entry);
    };

    auto isLogHeld = [&](uint32_t id) -> bool {
        for (int keycode = 0; keycode < 256; keycode++)
            if (state.heldKey[keycode] && state.heldKeyLogId[keycode] == id) return true;
        for (int bit = 0; bit < 8; bit++)
            if (state.heldMod[bit] && state.heldModLogId[bit] == id) return true;
        return false;
    };

    auto combatExpired = [&]() { return state.combat && (uint32_t)(millis() - state.combatStart) >= state.combatBudget; };
    auto wait = [&](uint32_t ms) {
        if (state.combat) {
            uint32_t elapsed = millis() - state.combatStart;
            ms = elapsed >= state.combatBudget ? 0 : std::min(ms, state.combatBudget - elapsed);
        }
        sleepMs(ms, stop);
    };
    auto hasHeldInput = [&]() {
        for (bool held : state.heldKey) if (held) return true;
        for (bool held : state.heldMod) if (held) return true;
        return false;
    };
    auto releaseTracked = [&]() {
        uint32_t ended = millis();
        for (int k = 0; k < 256; ++k) if (state.heldKey[k])
            updateLogDuration(state.heldKeyLogId[k], ended - state.heldKeyStartedAt[k], true);
        for (int k = 0; k < 8; ++k) if (state.heldMod[k])
            updateLogDuration(state.heldModLogId[k], ended - state.heldModStartedAt[k], true);
        Keyboard.releaseAll();
        state = ExecutionState{};
    };

    int pc = 0;
    const int n = (int)steps.size();
    while (pc < n) {
        if (stop || combatExpired()) break;
        Step guarded;
        const Step* current = &steps[pc];
        if (state.combat && current->type == StepType::KEY_UP && (current->modifiers & KM_LCTRL)) {
            guarded = *current; guarded.modifiers &= ~KM_LCTRL; current = &guarded;
        }
        const Step& s = *current;
        uint32_t stepStartedAt = millis();
        if (state.combat && (s.type == StepType::TEXT || s.type == StepType::CONSUMER)) {
            logStep(s,pc,stepStartedAt,0,true,"skipped: unsupported in combat");++pc;continue;
        }
        switch (s.type) {
            case StepType::KEY: {
                uint32_t holdMs = stepDuration(s, cfg_.randomizedDelay, true);
                uint32_t id = logStep(s, pc, stepStartedAt, holdMs, false);
                // Long taps and combat taps must remain interruptible. Retain
                // modifiers that were already held by the parent workflow.
                if (state.combat || holdMs > UINT16_MAX) {
                    uint8_t newMods = s.modifiers;
                    for (int bit=0; bit<8; ++bit) if(state.heldMod[bit]) newMods &= ~(1U<<bit);
                    Keyboard.pressKey(s.keycode, newMods);
                    wait(holdMs);
                    Keyboard.releaseKey(s.keycode);
                    Keyboard.releaseModifiers(newMods);
                } else Keyboard.tap(s.keycode, s.modifiers, (uint16_t)holdMs);
                updateLogDuration(id, millis() - stepStartedAt, true);
                break;
            }
            case StepType::KEY_DOWN: {
                uint32_t id = logStep(s, pc, stepStartedAt, 0, false);
                Keyboard.pressKey(s.keycode, s.modifiers);
                bool tracked = false;
                if (s.keycode != KC_NONE && !state.heldKey[s.keycode]) {
                    state.heldKey[s.keycode] = true;
                    state.heldKeyStartedAt[s.keycode] = stepStartedAt;
                    state.heldKeyLogId[s.keycode] = id;
                    tracked = true;
                }
                for (int bit = 0; bit < 8; bit++) {
                    if ((s.modifiers & (1U << bit)) && !state.heldMod[bit]) {
                        state.heldMod[bit] = true;
                        state.heldModStartedAt[bit] = stepStartedAt;
                        state.heldModLogId[bit] = id;
                        tracked = true;
                    }
                }
                if (!tracked) updateLogDuration(id, 0, true);
                break;
            }
            case StepType::KEY_UP: {
                uint32_t releaseIds[9] = {};
                size_t releaseCount = 0;
                auto addReleaseId = [&](uint32_t id) {
                    if (!id) return;
                    for (size_t index = 0; index < releaseCount; index++)
                        if (releaseIds[index] == id) return;
                    if (releaseCount < 9) releaseIds[releaseCount++] = id;
                };
                if (s.keycode != KC_NONE && state.heldKey[s.keycode]) {
                    uint32_t duration = millis() - state.heldKeyStartedAt[s.keycode];
                    updateLogDuration(state.heldKeyLogId[s.keycode], duration, false);
                    addReleaseId(state.heldKeyLogId[s.keycode]);
                    state.heldKey[s.keycode] = false;
                    state.heldKeyLogId[s.keycode] = 0;
                }
                for (int bit = 0; bit < 8; bit++) {
                    if ((s.modifiers & (1U << bit)) && state.heldMod[bit]) {
                        uint32_t duration = millis() - state.heldModStartedAt[bit];
                        updateLogDuration(state.heldModLogId[bit], duration, false);
                        addReleaseId(state.heldModLogId[bit]);
                        state.heldMod[bit] = false;
                        state.heldModLogId[bit] = 0;
                    }
                }
                logStep(s, pc, stepStartedAt, 0, true);
                if (s.keycode != KC_NONE) Keyboard.releaseKey(s.keycode);
                if (s.modifiers)          Keyboard.releaseModifiers(s.modifiers);
                for (size_t index = 0; index < releaseCount; index++)
                    if (!isLogHeld(releaseIds[index])) updateLogDuration(releaseIds[index], 0, true);
                break;
            }
            case StepType::TEXT: {
                uint32_t id = logStep(s, pc, stepStartedAt, 0, false);
                Keyboard.typeString(String(s.text().c_str()));
                updateLogDuration(id, millis() - stepStartedAt, true);
                break;
            }
            case StepType::CONSUMER: {
                uint32_t id = logStep(s, pc, stepStartedAt, 0, false);
                Keyboard.consumerPress(s.value);
                vTaskDelay(pdMS_TO_TICKS(20));
                Keyboard.consumerRelease();
                updateLogDuration(id, millis() - stepStartedAt, true);
                break;
            }
            case StepType::DELAY: {
                uint32_t duration = stepDuration(s, cfg_.randomizedDelay, hasHeldInput());
                uint32_t id = logStep(s, pc, stepStartedAt, duration, false);
                wait(duration);
                updateLogDuration(id, millis() - stepStartedAt, true);
                break;
            }
            case StepType::LAYER:
                setLayer(s.value);
                logStep(s, pc, stepStartedAt, 0, true);
                break;
            case StepType::DYNAMIC: {
                const DynamicPattern* pattern=s.pattern();
                if (!pattern || depth>=8 || hasHeldInput() || state.combat) {
                    logStep(s,pc,stepStartedAt,0,true,"skipped: dynamic needs neutral input");break;
                }
                // Don't start attacking a death or login screen.
                {LiveStats live=liveStatsSnapshot();const char* reason=live.fresh?liveStopReason(live.state):nullptr;
                 if(reason){char label[80];std::snprintf(label,sizeof(label),"skipped: %s",reason);logStep(s,pc,stepStartedAt,0,true,label);break;}}
                auto sample=[](DynamicRange range){return triangularSample(range,(uint32_t)random(1000001L));};
                auto delay=[](uint32_t ms){Step step;step.type=StepType::DELAY;step.value=ms;step.maxValue=ms;return step;};
                auto edge=[](bool down,uint8_t key,uint8_t mods){Step step;step.type=down?StepType::KEY_DOWN:StepType::KEY_UP;step.keycode=key;step.modifiers=mods;return step;};
                auto tap=[&](DynamicKey key,DynamicRange hold,DynamicRange after){
                    std::vector<Step> actions{edge(true,key.keycode,key.mods),delay(sample(hold)),edge(false,key.keycode,key.mods),delay(sample(after))};
                    executeSteps(actions,stop,state,depth+1);
                };
                const DynamicKey jump=pattern->jump,attack=pattern->attack;
                bool facingLeft=random(2L)==0;
                auto facing=[&]{return facingLeft?pattern->left:pattern->right;};
                uint32_t sets=sample(pattern->sets);
                const int32_t drift=pattern->tempoDriftPermille;
                int32_t tempo=drift?(int32_t)random(2L*drift+1)-drift:0;
                // Potions and skills share timers keyed by pattern; potions get a
                // prefix so a skill can't share an HP/Mana timer by its id.
                auto due=[&](const DynamicSkill& skill,const std::string& key){
                    auto timer=dynamicSkillTimers_.find(key);
                    return skill.enabled && (timer==dynamicSkillTimers_.end() || (uint32_t)(millis()-timer->second.lastRun)>=timer->second.wait) &&
                           random(1000L)<skill.chancePermille;
                };
                auto use=[&](const DynamicSkill& skill,const std::string& key,uint32_t taps=0){
                    Step skillEntry=s;skillEntry.keycode=skill.keycode;
                    uint32_t started=millis();
                    uint32_t id=logStep(skillEntry,pc,started,0,false,skill.id.c_str());
                    uint32_t repeats=taps?taps:sample(skill.repeats);
                    for(uint32_t repeat=0;repeat<repeats&&!stop;++repeat)tap(dynamicKeycode(skill.keycode),skill.hold,skill.after);
                    // Even an interrupted use starts its cooldown; each wait is drawn fresh.
                    dynamicSkillTimers_[key]={millis(),sample(skill.cooldown)};
                    updateLogDuration(id,millis()-started,true);
                };
                // A potion with a "drink below" threshold follows its bar while
                // tools/screen_stats.py sends fresh readings; otherwise its timer.
                auto potionKey=[&](const DynamicSkill& potion){return pattern->id+"/potion:"+potion.id;};
                auto potionLive=[&](const DynamicSkill& potion,int& value){
                    LiveStats live=liveStatsSnapshot();value=potion.id=="hp"?live.hp:live.mana;
                    return liveDecides(potion.belowPercent,live.fresh&&value>=0);
                };
                auto potionDue=[&](const DynamicSkill& potion){
                    int value;std::string key=potionKey(potion);
                    if(!potionLive(potion,value))return due(potion,key);
                    auto timer=dynamicSkillTimers_.find(key);bool drunk=timer!=dynamicSkillTimers_.end();
                    return potion.enabled&&liveWantsPotion(potion.belowPercent,value,drunk,drunk?(uint32_t)(millis()-timer->second.lastRun):0);
                };
                // With real amounts set, a live drink taps just enough to refill without waste.
                auto drink=[&](const DynamicSkill& potion){
                    int value;uint32_t taps=potionLive(potion,value)?livePotionTaps(value,potion.barMax,potion.perTap):0;
                    use(potion,potionKey(potion),taps);
                };
                // Between attacks: stop on a death or login screen,
                // turn for map edges and mobs, and turn (then stop) when stuck.
                StuckWatch stuck;
                auto screenCheck=[&]{
                    LiveStats live=liveStatsSnapshot();
                    if(!live.fresh)return false;
                    char label[80];
                    if(const char* reason=liveStopReason(live.state)){
                        std::snprintf(label,sizeof(label),"stopped: %s",reason);logStep(s,pc,millis(),0,true,label);
                        stop=true;return true;
                    }
                    int want=liveFacing(true,live.x,pattern->edgeMarginPermille,pattern->faceMobs,live.mobs);
                    if(want&&(want<0)!=facingLeft){facingLeft=want<0;tap(facing(),pattern->directionHold,pattern->directionAfter);}
                    if(pattern->stuckAfterMs){
                        // Map position when the script sends it (the dot can stay centred while you walk), else the dot.
                        bool map=live.wx!=LIVE_NO_POS&&live.wy!=LIVE_NO_POS;
                        uint8_t verdict=map?stuck.update(true,live.wx,live.wy,millis(),pattern->stuckAfterMs):stuck.update(live.x>=0&&live.y>=0,live.x,live.y,millis(),pattern->stuckAfterMs);
                        if(verdict==1){logStep(s,pc,millis(),0,true,"stuck: turning around");facingLeft=!facingLeft;tap(facing(),pattern->directionHold,pattern->directionAfter);}
                        if(verdict==2){logStep(s,pc,millis(),0,true,"stopped: still stuck");stop=true;return true;}
                    }
                    return false;
                };
                logStep(s,pc,stepStartedAt,0,true,"dynamic: starting");
                // Establish the actual initial facing before the first attack.
                tap(facing(),pattern->directionHold,pattern->directionAfter);
                for(uint32_t set=0;set<sets&&!stop;++set){
                    uint32_t count=sample(pattern->attacksPerSet),started=millis();
                    Step entry=s;entry.keycode=facing().keycode;entry.value=count;
                    char label[64];std::snprintf(label,sizeof(label),"set %lu/%lu: %lu attacks",(unsigned long)(set+1),(unsigned long)sets,(unsigned long)count);
                    uint32_t setLog=logStep(entry,pc,started,0,false,label);
                    for(uint32_t unit=0;unit<count&&!stop;++unit){
                        if(screenCheck())break;
                        // Live potions can't wait for the end of the set: drink between attacks.
                        int value;
                        for(const auto& potion:pattern->potions)if(!stop&&potionLive(potion,value)&&potionDue(potion))drink(potion);
                        if(drift)tempo=tempoDriftStep(tempo,drift,(int32_t)random(2L*(drift/2)+1)-drift/2);
                        uint32_t gap=(uint32_t)((uint64_t)sample(pattern->comboGap)*(uint32_t)(1000+tempo)/1000);
                        std::vector<Step> actions{
                            edge(true,jump.keycode,jump.mods),delay(sample(pattern->jumpToAttack)),
                            edge(true,attack.keycode,attack.mods),delay(sample(pattern->attackToJumpUp)),
                            edge(false,jump.keycode,jump.mods),delay(sample(pattern->jumpUpToAttackUp)),
                            edge(false,attack.keycode,attack.mods),delay(gap)};
                        executeSteps(actions,stop,state,depth+1);
                    }
                    updateLogDuration(setLog,millis()-started,true);
                    if(stop)break;
                    for(const auto& potion:pattern->potions)if(!stop&&potionDue(potion))drink(potion);
                    std::vector<size_t> skills;
                    for(size_t i=0;i<pattern->skills.size();++i)
                        if(due(pattern->skills[i],pattern->id+"/"+pattern->skills[i].id))skills.push_back(i);
                    if(pattern->shuffleSkills)for(size_t i=skills.size();i>1;--i)std::swap(skills[i-1],skills[random((long)i)]);
                    for(size_t index:skills){
                        if(stop)break;
                        use(pattern->skills[index],pattern->id+"/"+pattern->skills[index].id);
                    }
                    // No direction tap after the last set: it would only nudge the character.
                    if(stop||set+1==sets)break;
                    // Live facing (map edge, mobs) wins; otherwise the turn chance.
                    LiveStats live=liveStatsSnapshot();
                    int want=liveFacing(live.fresh,live.x,pattern->edgeMarginPermille,pattern->faceMobs,live.mobs);
                    if(want)facingLeft=want<0;
                    else if(random(1000L)<pattern->turnChancePermille)facingLeft=!facingLeft;
                    tap(facing(),pattern->directionHold,pattern->directionAfter);
                    if(!stop)yieldTick();
                }
                releaseTracked();
                logStep(s,pc,stepStartedAt,millis()-stepStartedAt,true,stop?"dynamic: stopped":"dynamic: finished");
                break;
            }
            case StepType::MOVE: {
                uint32_t duration = stepDuration(s, false);
                // Bound accumulated commanded movement, not merely press count.
                bool left = movementBalanceMs_ > 0 || (movementBalanceMs_ == 0 && random(2L) == 0);
                if (movementBalanceMs_ > -600 && movementBalanceMs_ < 600) {
                    bool proposedLeft = random(2L) == 0;
                    int32_t proposed = movementBalanceMs_ + (proposedLeft ? -(int32_t)duration : (int32_t)duration);
                    if (proposed >= -600 && proposed <= 600) left = proposedLeft;
                }
                uint8_t key = left ? KC_LEFT : KC_RIGHT;
                Step entry = s; entry.keycode = key;
                uint32_t id = logStep(entry, pc, stepStartedAt, duration, false);
                Keyboard.pressKey(key);
                wait(duration);
                Keyboard.releaseKey(key);
                uint32_t actual = millis() - stepStartedAt;
                movementBalanceMs_ += left ? -(int32_t)actual : (int32_t)actual;
                updateLogDuration(id, actual, true);
                break;
            }
            case StepType::UTILITIES: {
                bool neutral = !state.combat;
                for (bool held : state.heldKey) if (held) neutral = false;
                for (bool held : state.heldMod) if (held) neutral = false;
                if (!neutral) { logStep(s,pc,stepStartedAt,0,true,"skipped: keys held");break; }
                std::vector<const Workflow*> eligible;
                for (const auto& w : cfg_.workflows) {
                    auto last = utilityLastRun_.find(w.id);
                    uint32_t since = last == utilityLastRun_.end() ? utilityEpoch_ : last->second;
                    if (w.utilityEnabled && !w.empty() && (uint32_t)(millis()-since) >= w.cooldownMs &&
                        (uint32_t)random(1000L) < w.chancePermille) eligible.push_back(&w);
                }
                if (!eligible.empty() && depth < 8) {
                    const Workflow& w=*eligible[random((long)eligible.size())];
                    if (std::find(callStack_.begin(),callStack_.end(),&w.steps)!=callStack_.end()) break;
                    uint32_t id=logStep(s,pc,stepStartedAt,0,false,w.name.c_str());
                    executeSteps(w.steps,stop,state,depth+1);
                    releaseTracked();
                    utilityLastRun_[w.id]=millis();
                    updateLogDuration(id,millis()-stepStartedAt,true);
                } else { logStep(s,pc,stepStartedAt,0,true,"no utility due/selected"); }
                break;
            }
            case StepType::CALL:
            case StepType::RANDOM:
            case StepType::COMBAT: {
                bool combat = s.type == StepType::COMBAT;
                if (combat && state.combat) { logStep(s,pc,stepStartedAt,0,true,"skipped: nested combat");break; }
                uint32_t combatLog = 0;
                if (combat) {
                    releaseTracked();
                    state.combat=true;state.combatStart=millis();
                    state.combatBudget=std::min<uint32_t>(90000,stepDuration(s,false));
                    Step attack=s;attack.modifiers=KM_LCTRL;
                    combatLog=logStep(attack,pc,stepStartedAt,0,false);
                    Keyboard.pressKey(KC_NONE,KM_LCTRL);
                    state.heldMod[0]=true;state.heldModStartedAt[0]=millis();state.heldModLogId[0]=combatLog;
                }
                do {
                    if (stop || combatExpired()) break;
                    uint32_t choiceStartedAt = millis();
                    const KeyBinding* selected = nullptr;
                    if (s.type == StepType::CALL) {
                        selected = cfg_.findWorkflow(s.text());
                    } else {
                        std::vector<const KeyBinding*> candidates;
                        std::vector<uint16_t> weights;
                        for (const MacroRef& ref : s.choices()) {
                            const KeyBinding* candidate = nullptr;
                            if (!ref.workflow.empty()) candidate = cfg_.findWorkflow(ref.workflow);
                            else if (ref.layer < cfg_.layers.size() && ref.key < KEY_COUNT)
                                candidate = &cfg_.layers[ref.layer].keys[ref.key];
                            if (!candidate || candidate->empty() || !ref.weight ||
                                std::find(candidates.begin(), candidates.end(), candidate) != candidates.end()) continue;
                            candidates.push_back(candidate);
                            weights.push_back(ref.weight);
                        }
                        auto& history = choiceHistory_[&s];
                        std::vector<bool> eligible;
                        for (const auto* candidate : candidates) {
                            eligible.push_back(!workflowIsRecent(candidate, history, s.avoidRecent));
                        }
                        uint32_t total = workflowWeightTotal(weights, eligible);
                        int index = total ? selectWorkflow(weights, eligible, (uint32_t)random((long)total)) : -1;
                        if (index >= 0) {
                            selected = candidates[index];
                            rememberWorkflow(selected, history, s.avoidRecent);
                        }
                    }
                    const char* skipReason = nullptr;
                    if (!selected) skipReason = s.type == StepType::CALL ? "skipped: missing workflow" : "skipped: no eligible choices";
                    else if (depth >= 8) skipReason = "skipped: nesting limit";
                    else if (std::find(callStack_.begin(), callStack_.end(), &selected->steps) != callStack_.end())
                        skipReason = "skipped: recursive call";
                    const bool canCall = !skipReason;
                    const char* label = canCall ? (selected->name.empty() ? "unnamed workflow" : selected->name.c_str()) : skipReason;
                    uint32_t id = logStep(s, pc, choiceStartedAt, 0, !canCall, label);
                    if (canCall) {
                        executeSteps(selected->steps, stop, state, depth + 1);
                        updateLogDuration(id, millis() - choiceStartedAt, true);
                    }
                    if (!stop && !combatExpired()) yieldTick();
                } while (combat && !stop && !combatExpired());
                if (combat) {
                    releaseTracked();
                    updateLogDuration(combatLog,millis()-stepStartedAt,true);
                }
                break;
            }
            case StepType::LOOP_START:
                if (s.matchIndex < 0) {
                    logStep(s, pc, stepStartedAt, 0, true);
                    break;
                }
                loops.push_back({pc, s.matchIndex, s.value, s.value == 0, 1});
                logStep(s, pc, stepStartedAt, 0, true);
                break;
            case StepType::LOOP_END:
                logStep(s, pc, stepStartedAt, 0, true);
                if (!loops.empty()) {
                    Frame& f = loops.back();
                    if (f.infinite) {
                        yieldTick();          // bound the loop; let keys be scanned
                        f.iteration++;
                        pc = f.startIdx;      // -> ++pc lands at start+1
                    } else if (--f.remaining > 0) {
                        yieldTick();
                        f.iteration++;
                        pc = f.startIdx;
                    } else {
                        loops.pop_back();
                    }
                }
                break;
        }
        pc++;
    }
    callStack_.pop_back();
    if (depth == 0) {
        uint32_t endedAt = millis();
        for (int keycode = 0; keycode < 256; keycode++) {
            if (state.heldKey[keycode])
                updateLogDuration(state.heldKeyLogId[keycode], endedAt - state.heldKeyStartedAt[keycode], true);
        }
        for (int bit = 0; bit < 8; bit++) {
            if (state.heldMod[bit])
                updateLogDuration(state.heldModLogId[bit], endedAt - state.heldModStartedAt[bit], true);
        }
        Keyboard.releaseAll();   // leave keyboard clean when the macro ends/stops
    }
}

void MacroEngine::runMacro(const KeyBinding& kb) {
    choiceHistory_.clear();
    callStack_.clear();
    movementBalanceMs_ = 0;
    if (!utilityClockStarted_) {utilityEpoch_=millis();utilityClockStarted_=true;}
    if (oneShot_) {                       // Test / single pass
        macroPass_ = 1;
        ExecutionState state{};
        executeSteps(kb.steps, stopFlag_, state, 0);
        return;
    }
    switch (kb.trigger) {
        case TriggerMode::TAP:
            macroPass_ = 1;
            {
                ExecutionState state{};
                executeSteps(kb.steps, stopFlag_, state, 0);
            }
            break;
        case TriggerMode::HOLD:
        case TriggerMode::TOGGLE:
            // Repeat the whole macro until stopped (release / second press).
            while (!stopFlag_) {
                macroPass_++;
                ExecutionState state{};
                executeSteps(kb.steps, stopFlag_, state, 0);
                if (kb.steps.empty()) break;
                yieldTick();              // don't spin if the macro has no delays
            }
            break;
    }
}

void MacroEngine::taskTrampoline(void* arg) {
    MacroEngine* self = static_cast<MacroEngine*>(arg);
    self->running_ = true;
    self->runMacro(self->activeBinding_);
    self->running_ = false;
    self->runningKey_ = -1;
    TaskHandle_t t = self->task_;
    self->task_ = nullptr;
    vTaskDelete(t);
}

void MacroEngine::startMacroTask(int keyIndex, bool oneShot) {
    stopAll();  // only one macro at a time
    // If the previous task didn't actually wind down, refuse rather than
    // stack a second macro task (which would fight over the HID reports).
    if (running_ || task_) return;
    if (keyIndex < 0 || keyIndex >= KEY_COUNT) return;
    const KeyBinding& kb = cfg_.layers[layer_].keys[keyIndex];
    if (kb.empty()) return;
    activeBinding_ = kb;      // snapshot so edits mid-run are safe
    stopFlag_      = false;
    oneShot_       = oneShot;
    macroStartedAt_ = millis();
    macroRunId_++;
    macroPass_     = 0;
    runningKey_    = keyIndex;
    if (xTaskCreatePinnedToCore(taskTrampoline, "macro", 16384, this, 2, &task_, 1) != pdPASS) {
        task_ = nullptr;
        runningKey_ = -1;
    }
}

void MacroEngine::stopAll() {
    if (running_ && task_) {
        stopFlag_ = true;
        // wait for the task to wind down (it yields at least every ~5ms)
        for (int i = 0; i < 400 && running_; i++) vTaskDelay(pdMS_TO_TICKS(5));
    }
    Keyboard.releaseAll();
}

// --- trigger handling ------------------------------------------------------
void MacroEngine::onKeyDown(int keyIndex) {
    if (keyIndex < 0 || keyIndex >= KEY_COUNT) return;
    if (layer_ >= (int)cfg_.layers.size()) return;
    const KeyBinding& kb = cfg_.layers[layer_].keys[keyIndex];
    if (kb.empty()) return;

    if (kb.trigger == TriggerMode::TOGGLE) {
        // Press on the running key => stop it; otherwise start.
        if (running_ && runningKey_ == keyIndex) { stopAll(); return; }
        startMacroTask(keyIndex);
    } else {
        // TAP and HOLD both start on key-down.
        startMacroTask(keyIndex);
    }
}

void MacroEngine::onKeyUp(int keyIndex) {
    if (keyIndex < 0 || keyIndex >= KEY_COUNT) return;
    if (layer_ >= (int)cfg_.layers.size()) return;
    const KeyBinding& kb = cfg_.layers[layer_].keys[keyIndex];
    // HOLD stops on release; TAP finishes on its own; TOGGLE ignores release.
    if (kb.trigger == TriggerMode::HOLD && running_ && runningKey_ == keyIndex) {
        stopAll();
    }
}
