#pragma once
#include <Arduino.h>
#include <vector>
#include <string>
#include "config.h"

// ---------------------------------------------------------------------------
// Macro data model + execution engine.
//
// A macro is an ordered list of Steps. Steps include key taps, key down/up,
// typed text, media keys, fixed delays, and loops (with a repeat count; 0 = run
// until the macro is stopped). Configured key-hold and delay durations receive
// a random +/-1000 ms variation each time their step runs.
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
};

struct Step {
    StepType    type   = StepType::DELAY;
    uint8_t     keycode   = 0;
    uint8_t     modifiers = 0;
    uint16_t    value   = 0;      // ms / repeat / usage / layer, per type
    std::string text;            // only for TEXT
    int         matchIndex = -1; // LOOP_START<->LOOP_END pairing (precomputed)
};

enum class TriggerMode : uint8_t { TAP, TOGGLE, HOLD };

struct KeyBinding {
    TriggerMode       trigger = TriggerMode::TAP;
    std::string       name;      // label shown in the UI
    std::vector<Step> steps;
    bool              empty() const { return steps.empty(); }
};

struct Layer {
    std::string name;
    KeyBinding  keys[KEY_COUNT];
};

struct Config {
    std::vector<Layer> layers;
    void ensureLayer(size_t n);
};

// Commands that other tasks (e.g. the web server) hand to the engine. They are
// queued and executed on the main loop task, so all config mutation and macro
// start/stop happens on one task - no races with the key scanner.
enum class EngineCmd : uint8_t {
    RELOAD, TEST, LAYER, STOP,
    // Live passthrough while recording: emit the key to the host in real time.
    // a = keycode / consumer usage, b = modifier mask (per command).
    LIVE_DOWN, LIVE_UP, LIVE_MEDIA, LIVE_MODDOWN, LIVE_MODUP, LIVE_RELEASEALL,
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
    bool    save();             // to flash

    // Stop whatever macro is running.
    void stopAll();
    bool isRunning() const { return running_; }
    int  runningKey() const { return runningKey_; }

private:
    static void taskTrampoline(void* arg);
    void runMacro(const KeyBinding& kb);
    void executeSteps(const std::vector<Step>& steps, volatile bool& stopFlag);
    void startMacroTask(int keyIndex, bool oneShot = false);

    static void validateLoops(KeyBinding& kb);

    Config cfg_;
    int    layer_      = 0;

    volatile bool running_    = false;
    volatile bool stopFlag_   = false;
    volatile bool oneShot_    = false;   // run a single pass regardless of trigger
    volatile int  runningKey_ = -1;
    TaskHandle_t  task_       = nullptr;
    QueueHandle_t cmdQueue_   = nullptr;

    // snapshot of the binding the task is executing
    KeyBinding    activeBinding_;
};

extern MacroEngine Macros;
