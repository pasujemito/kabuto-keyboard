#include <algorithm>
#include "macro_engine.h"
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
    uint32_t elapsed = 0;
    while (elapsed < ms) {
        if (stop) return;
        uint32_t step = (ms - elapsed) < chunk ? (ms - elapsed) : chunk;
        TickType_t ticks = pdMS_TO_TICKS(step);
        vTaskDelay(ticks ? ticks : 1);
        elapsed += step;
    }
}

static uint32_t randomizedDuration(uint16_t ms, bool enabled) {
    if (!enabled || ms == 0) return ms;
    int32_t jitter = ms < 2000 ? random(-10L, 11L) : random(-1000L, 1001L);
    int32_t duration = (int32_t)ms + jitter;
    return duration > 0 ? (uint32_t)duration : 1;
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
    cfg_.ensureLayer(0);
    commit();
    if (layer_ >= (int)cfg_.layers.size()) layer_ = 0;
    return ok;
}

bool MacroEngine::save() { return saveConfig(cfg_); }

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

    auto logStep = [&](const Step& step, int stepIndex, uint32_t startedAt,
                       uint32_t durationMs, bool complete) -> uint32_t {
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
        if (step.type == StepType::TEXT || step.type == StepType::RANDOM || step.type == StepType::CALL)
            std::strncpy(entry.text, step.text.c_str(), sizeof(entry.text) - 1);
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

    int pc = 0;
    const int n = (int)steps.size();
    while (pc < n) {
        if (stop) break;
        const Step& s = steps[pc];
        uint32_t stepStartedAt = millis();
        switch (s.type) {
            case StepType::KEY: {
                uint32_t holdMs = randomizedDuration(s.value, cfg_.randomizedDelay);
                if (holdMs > UINT16_MAX) holdMs = UINT16_MAX;
                uint32_t id = logStep(s, pc, stepStartedAt, holdMs, false);
                Keyboard.tap(s.keycode, s.modifiers, (uint16_t)holdMs);
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
                Keyboard.typeString(String(s.text.c_str()));
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
                uint32_t duration = randomizedDuration(s.value, cfg_.randomizedDelay);
                uint32_t id = logStep(s, pc, stepStartedAt, duration, false);
                sleepMs(duration, stop);
                updateLogDuration(id, millis() - stepStartedAt, true);
                break;
            }
            case StepType::LAYER:
                setLayer(s.value);
                logStep(s, pc, stepStartedAt, 0, true);
                break;
            case StepType::CALL:
            case StepType::RANDOM: {
                const KeyBinding* selected = nullptr;
                if (s.type == StepType::CALL) {
                    selected = cfg_.findWorkflow(s.text);
                } else {
                    std::vector<const KeyBinding*> candidates;
                    std::vector<uint16_t> weights;
                    for (const MacroRef& ref : s.choices) {
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
                Step entryStep = s;
                const char* skipReason = nullptr;
                if (!selected) skipReason = s.type == StepType::CALL ? "skipped: missing workflow" : "skipped: no eligible choices";
                else if (depth >= 8) skipReason = "skipped: nesting limit";
                else if (std::find(callStack_.begin(), callStack_.end(), &selected->steps) != callStack_.end())
                    skipReason = "skipped: recursive call";
                const bool canCall = !skipReason;
                entryStep.text = canCall ? (selected->name.empty() ? "unnamed workflow" : selected->name) : skipReason;
                uint32_t id = logStep(entryStep, pc, stepStartedAt, 0, !canCall);
                if (canCall) {
                    executeSteps(selected->steps, stop, state, depth + 1);
                    updateLogDuration(id, millis() - stepStartedAt, true);
                }
                yieldTick();
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
    if (oneShot_) {                       // Test / single pass
        macroPass_ = 1;
        ExecutionState state{};
        executeSteps(kb.steps, stopFlag_, state);
        return;
    }
    switch (kb.trigger) {
        case TriggerMode::TAP:
            macroPass_ = 1;
            {
                ExecutionState state{};
                executeSteps(kb.steps, stopFlag_, state);
            }
            break;
        case TriggerMode::HOLD:
        case TriggerMode::TOGGLE:
            // Repeat the whole macro until stopped (release / second press).
            while (!stopFlag_) {
                macroPass_++;
                ExecutionState state{};
                executeSteps(kb.steps, stopFlag_, state);
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
    if (xTaskCreatePinnedToCore(taskTrampoline, "macro", 8192, this, 2, &task_, 1) != pdPASS) {
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
