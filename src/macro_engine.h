#pragma once
#include <Arduino.h>
#include <vector>
#include <string>
#include <map>
#include <memory>
#include "config.h"

// ---------------------------------------------------------------------------
// Macro data model + execution engine.
//
// A macro is an ordered list of Steps. Steps include key taps, key down/up,
// typed text, media keys, delays, workflow calls, random choices and loops
// (repeat count 0 = until stopped). Optional timing variation is +/-6 ms for
// key holds, +/-15 ms up to 5 seconds, +/-200 ms up to 40 seconds and +/-5000
// ms beyond that.
//
// Each physical key, on each layer, has a trigger mode:
//   TAP    - run the macro once per key press
//   TOGGLE - press once to start, press again to stop (good for loops)
//   HOLD   - run while the key is held, stop on release
// ---------------------------------------------------------------------------

enum class StepType : uint8_t {
    KEY,        // tap keycode+mods, hold = value ms
    KEY_DOWN,   // press and hold keycode+mods
    KEY_UP,     // release keycode (and clear mods in 'modifiers')
    TEXT,       // type the UTF-8/ASCII string in 'text'
    CONSUMER,   // media key: usage in 'value'
    DELAY,      // wait 'value' ms
    LOOP_START, // begin loop; 'value' = repeat count (0 = until stopped)
    LOOP_END,   // end of innermost loop
    LAYER,      // switch active layer to 'value'
    MOVE,       // short balanced left/right pulse
    COMBAT,     // hold Ctrl while choosing bounded micro workflows
    UTILITIES,  // occasionally invoke eligible cooldown workflows
    CALL,       // execute a named workflow once
    RANDOM,     // run one randomly selected macro from 'choices'
};

struct MacroRef {
    std::string workflow; // empty selects the legacy layer/key binding
    uint16_t weight = 1;
    uint8_t layer = 0;
    uint8_t key = 0;
};

// Payload that only TEXT, CALL, RANDOM and COMBAT steps carry. Kept out of
// Step so the common key/delay steps of long recordings stay small.
struct StepExtra {
    std::string           text;    // TEXT: string to type, CALL: workflow id
    std::vector<MacroRef> choices; // RANDOM / COMBAT
};

struct Step {
    StepType    type   = StepType::DELAY;
    uint8_t     keycode   = 0;
    uint8_t     modifiers = 0;
    uint8_t     avoidRecent = 0; // exclude up to 16 recent choices; skip if exhausted
    uint32_t    value   = 0;      // ms / repeat / usage / layer, per type
    uint32_t    maxValue = 0;     // inclusive upper timing bound, 0 = fixed
    int16_t     matchIndex = -1;  // LOOP_START<->LOOP_END pairing (precomputed)
    std::shared_ptr<const StepExtra> extra; // shared: copies stay cheap

    const std::string& text() const { static const std::string none; return extra ? extra->text : none; }
    const std::vector<MacroRef>& choices() const { static const std::vector<MacroRef> none; return extra ? extra->choices : none; }
    void setText(std::string value) { auto e = mutableExtra(); e->text = std::move(value); extra = std::move(e); }
    void setChoices(std::vector<MacroRef> value) { auto e = mutableExtra(); e->choices = std::move(value); extra = std::move(e); }

private:
    std::shared_ptr<StepExtra> mutableExtra() const {
        return extra ? std::make_shared<StepExtra>(*extra) : std::make_shared<StepExtra>();
    }
};

struct MacroLogEntry {
    uint32_t id = 0;
    uint32_t elapsedMs = 0;
    uint32_t durationMs = 0;
    uint32_t run = 0;
    uint32_t pass = 0;
    uint16_t step = 0;
    StepType type = StepType::DELAY;
    uint8_t keycode = 0;
    uint8_t modifiers = 0;
    uint32_t value = 0;
    bool complete = true;
    char text[40] = {};
    char loopPath[32] = {};
};

enum class TriggerMode : uint8_t { TAP, TOGGLE, HOLD };

struct KeyBinding {
    TriggerMode       trigger = TriggerMode::TAP;
    std::string       name;      // label shown in the UI
    std::string       playbackMode; // simple UI: single / sequence / random
    bool              recording = false; // workflow timings originated in a recording
    std::vector<Step> steps;
    bool              empty() const { return steps.empty(); }
};

struct Layer {
    std::string name;
    KeyBinding  keys[KEY_COUNT];
};

struct Workflow : KeyBinding {
    std::string id;
    std::string kind = "nano"; // retained for compatibility, hidden by the UI
    std::string recordingPartOf;
    bool utilityEnabled = false;
    uint32_t cooldownMs = 0;
    uint16_t chancePermille = 100;
};

struct Config {
    std::vector<Workflow> workflows;
    const KeyBinding* findWorkflow(const std::string& id) const;
    std::vector<Layer> layers;
    bool randomizedDelay = true;
    void ensureLayer(size_t n);
};

// Commands that other tasks (e.g. the web server) hand to the engine. They are
// queued and executed on the main loop task, so all config mutation and macro
// start/stop happens on one task - no races with the key scanner.
enum class EngineCmd : uint8_t {
    RELOAD, TEST, LAYER, STOP,
    // Live passthrough while recording: emit the key to the host in real time.
    // a = keycode / consumer usage, b = modifier mask (per command).
    LIVE_DOWN, LIVE_UP, LIVE_MEDIA, LIVE_MODDOWN, LIVE_MODUP, LIVE_RELEASEALL, LIVE_TEXT,
    // Run-mode: drive a pad key from the UI with full trigger semantics.
    // a = key index, b = layer.
    KEYDOWN, KEYUP,
};

// ---------------------------------------------------------------------------
class MacroEngine {
public:
    void begin();

    // Thread-safe: queue a command from any task. Returns false if the queue
    // is full. a/b are command arguments (TEST: layer,key; LAYER: n).
    bool post(EngineCmd cmd, int a = 0, int b = 0);
    bool postText(const char* text);
    // Drain queued commands. Call from the main loop task only.
    void processCommands();

    // Called by the matrix scanner on key edges.
    void onKeyDown(int keyIndex);
    void onKeyUp(int keyIndex);

    // Active layer control.
    int  activeLayer() const { return layer_; }
    void setLayer(int n);

    // Access to config (the web server edits this, then calls commit()).
    Config& config() { return cfg_; }
    void    commit();           // re-validate loop pairing after edits
    bool    load();             // from flash

    // Stop whatever macro is running.
    void stopAll();
    bool isRunning() const { return running_; }
    int  runningKey() const { return runningKey_; }
    uint32_t elapsedMs() const { return running_ ? millis() - macroStartedAt_ : 0; }
    size_t copyLog(MacroLogEntry* entries, size_t capacity) const;
    void clearLog();

private:
    struct ExecutionState {
        uint32_t heldKeyStartedAt[256] = {};
        uint32_t heldKeyLogId[256] = {};
        bool heldKey[256] = {};
        uint32_t heldModStartedAt[8] = {};
        uint32_t heldModLogId[8] = {};
        bool heldMod[8] = {};
        bool combat = false;
        uint32_t combatStart = 0;
        uint32_t combatBudget = 0;
    };

    static void taskTrampoline(void* arg);
    void runMacro(const KeyBinding& kb);
    void executeSteps(const std::vector<Step>& steps, volatile bool& stopFlag,
                      ExecutionState& state, uint8_t depth = 0);
    void startMacroTask(int keyIndex, bool oneShot = false);
    uint32_t appendLog(const MacroLogEntry& entry);
    void updateLogDuration(uint32_t id, uint32_t durationMs, bool complete);

    static void validateLoops(KeyBinding& kb);

    // History lasts for one key activation, including all toggle/hold passes.
    std::map<const Step*, std::vector<const KeyBinding*>> choiceHistory_;
    std::vector<const std::vector<Step>*> callStack_;
    int32_t movementBalanceMs_ = 0;
    bool utilityClockStarted_ = false;
    uint32_t utilityEpoch_ = 0;
    std::map<std::string, uint32_t> utilityLastRun_;
    Config cfg_;
    int    layer_      = 0;

    volatile bool running_    = false;
    volatile bool stopFlag_   = false;
    volatile bool oneShot_    = false;   // run a single pass regardless of trigger
    volatile int  runningKey_ = -1;
    uint32_t macroStartedAt_ = 0;
    uint32_t macroRunId_     = 0;
    uint32_t macroPass_      = 0;
    TaskHandle_t  task_       = nullptr;
    QueueHandle_t cmdQueue_   = nullptr;

    // snapshot of the binding the task is executing
    KeyBinding    activeBinding_;
};

extern MacroEngine Macros;
