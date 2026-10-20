#include "macro_engine.h"
#include "hid_keyboard.h"
#include "keymap.h"
#include "storage.h"

MacroEngine Macros;

struct CmdMsg { EngineCmd cmd; int16_t a; int16_t b; };

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

static uint32_t randomizedDuration(uint16_t ms) {
    int32_t duration = (int32_t)ms + random(-1000L, 1001L);
    return duration > 0 ? (uint32_t)duration : 0;
}

// Give the scheduler at least one tick. The macro task runs at a higher
// priority than the Arduino loop (which scans the keys) on the same core, so a
// macro with no delays in it would otherwise starve key scanning - and then the
// key that should stop it can never be read.
static inline void yieldTick() { vTaskDelay(1); }

void MacroEngine::begin() {
    cfg_.ensureLayer(0);
    if (!cmdQueue_) cmdQueue_ = xQueueCreate(8, sizeof(CmdMsg));
}

// --- command queue ---------------------------------------------------------
bool MacroEngine::post(EngineCmd cmd, int a, int b) {
    if (!cmdQueue_) return false;
    CmdMsg m{cmd, (int16_t)a, (int16_t)b};
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
void MacroEngine::executeSteps(const std::vector<Step>& steps, volatile bool& stop) {
    struct Frame { int startIdx; int endIdx; uint32_t remaining; bool infinite; };
    std::vector<Frame> loops;

    int pc = 0;
    const int n = (int)steps.size();
    while (pc < n) {
        if (stop) break;
        const Step& s = steps[pc];
        switch (s.type) {
            case StepType::KEY: {
                uint32_t holdMs = randomizedDuration(s.value);
                Keyboard.tap(s.keycode, s.modifiers,
                             holdMs > UINT16_MAX ? UINT16_MAX : (uint16_t)holdMs);
                break;
            }
            case StepType::KEY_DOWN:
                Keyboard.pressKey(s.keycode, s.modifiers);
                break;
            case StepType::KEY_UP:
                if (s.keycode != KC_NONE) Keyboard.releaseKey(s.keycode);
                if (s.modifiers)          Keyboard.releaseModifiers(s.modifiers);
                break;
            case StepType::TEXT:
                Keyboard.typeString(String(s.text.c_str()));
                break;
            case StepType::CONSUMER:
                Keyboard.consumerPress(s.value);
                vTaskDelay(pdMS_TO_TICKS(20));
                Keyboard.consumerRelease();
                break;
            case StepType::DELAY:
                sleepMs(randomizedDuration(s.value), stop);
                break;
            case StepType::LAYER:
                setLayer(s.value);
                break;
            case StepType::LOOP_START:
                if (s.matchIndex < 0) break;             // unmatched -> skip
                loops.push_back({pc, s.matchIndex, s.value, s.value == 0});
                break;
            case StepType::LOOP_END:
                if (!loops.empty()) {
                    Frame& f = loops.back();
                    if (f.infinite) {
                        yieldTick();          // bound the loop; let keys be scanned
                        pc = f.startIdx;      // -> ++pc lands at start+1
                    } else if (--f.remaining > 0) {
                        yieldTick();
                        pc = f.startIdx;
                    } else {
                        loops.pop_back();
                    }
                }
                break;
        }
        pc++;
    }
    Keyboard.releaseAll();   // leave keyboard clean when the macro ends/stops
}

void MacroEngine::runMacro(const KeyBinding& kb) {
    if (oneShot_) {                       // Test / single pass
        executeSteps(kb.steps, stopFlag_);
        return;
    }
    switch (kb.trigger) {
        case TriggerMode::TAP:
            executeSteps(kb.steps, stopFlag_);
            break;
        case TriggerMode::HOLD:
        case TriggerMode::TOGGLE:
            // Repeat the whole macro until stopped (release / second press).
            while (!stopFlag_) {
                executeSteps(kb.steps, stopFlag_);
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
