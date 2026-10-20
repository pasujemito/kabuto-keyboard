#include <Arduino.h>
#include "config.h"
#include "hid_keyboard.h"
#include "macro_engine.h"
#include "storage.h"
#include "web_server.h"

// ---------------------------------------------------------------------------
// Matrix scanning with per-key debounce.
// Rows are driven LOW one at a time; columns read with pull-ups (pressed=LOW).
// ---------------------------------------------------------------------------
static bool     keyState[KEY_COUNT];     // debounced state (true = pressed)
static bool     rawPrev[KEY_COUNT];      // last raw sample
static uint32_t lastChange[KEY_COUNT];   // ms of last raw change

// Live debounced key state, readable by the web server's key tester.
volatile bool     g_keyLive[KEY_COUNT];
// Diagnostics for the web UI live monitor.
volatile uint32_t g_keyMask      = 0;   // bit i set = key i currently down
volatile int      g_lastKeyDown  = -1;  // last key index that went down
volatile uint32_t g_keyDownCount = 0;   // total key-down edges since boot
static bool g_startupWarning = false;
static uint8_t slowPulse(uint32_t now, uint32_t periodMs, uint8_t minimum, uint8_t maximum) {
    uint32_t halfPeriod = periodMs / 2;
    uint32_t phase = now % periodMs;
    uint32_t progress = phase < halfPeriod ? phase : periodMs - phase;
    return minimum + (progress * (maximum - minimum)) / halfPeriod;
}

static void setStatusLed(uint8_t red, uint8_t green, uint8_t blue) {
#if STATUS_LED_PIN >= 0
    static uint8_t lastRed = 255, lastGreen = 255, lastBlue = 255;
    if (red == lastRed && green == lastGreen && blue == lastBlue) return;
    neopixelWrite(STATUS_LED_PIN, red, green, blue);
    lastRed = red;
    lastGreen = green;
    lastBlue = blue;
#endif
}

static void statusLedInit() {
    setStatusLed(0, 0, 0);
}

static void statusLedUpdate() {
#if STATUS_LED_PIN >= 0
    uint32_t now = millis();
    bool running = Macros.isRunning();
    bool connected = Keyboard.isConnected();

    if (g_startupWarning || !connected) {
        uint32_t phase = now % 1400;
        bool flash = phase < 100 || (phase >= 200 && phase < 300) ||
                     (phase >= 400 && phase < 500);
        setStatusLed(flash ? 56 : 0, 0, 0);
    } else if (running) {
        setStatusLed(0, 0, slowPulse(now, 3600, 4, 64));
    } else if (webServerRecorderActive()) {
        uint8_t level = slowPulse(now, 3600, 4, 64);
        setStatusLed(level, level * 3 / 5, 0);
    } else {
        setStatusLed(0, 36, 0);
    }
#endif
}

static void matrixInit() {
    for (int r = 0; r < MATRIX_ROWS; r++) { pinMode(ROW_PINS[r], OUTPUT); digitalWrite(ROW_PINS[r], HIGH); }
    for (int c = 0; c < MATRIX_COLS; c++) pinMode(COL_PINS[c], INPUT_PULLUP);
    for (int i = 0; i < KEY_COUNT; i++) { keyState[i] = rawPrev[i] = false; lastChange[i] = 0; g_keyLive[i] = false; }
}

static void matrixScan() {
    uint32_t now = millis();
    for (int r = 0; r < MATRIX_ROWS; r++) {
        digitalWrite(ROW_PINS[r], LOW);
        // Let the column lines settle. ESP32 internal pull-ups are weak
        // (~45k), so the line needs tens of microseconds to recover to HIGH
        // after the previous row; too short a wait causes flaky/phantom reads.
        delayMicroseconds(MATRIX_SETTLE_US);
        for (int c = 0; c < MATRIX_COLS; c++) {
            int idx = r * MATRIX_COLS + c;
            bool raw = (digitalRead(COL_PINS[c]) == LOW);
            if (raw != rawPrev[idx]) { rawPrev[idx] = raw; lastChange[idx] = now; }
            if ((now - lastChange[idx]) >= DEBOUNCE_MS && raw != keyState[idx]) {
                keyState[idx] = raw;
                g_keyLive[idx] = raw;
                if (raw) {
                    g_keyMask |= (1UL << idx);
                    g_lastKeyDown = idx;
                    g_keyDownCount++;
                    Macros.onKeyDown(idx);
                } else {
                    g_keyMask &= ~(1UL << idx);
                    Macros.onKeyUp(idx);
                }
            }
        }
        digitalWrite(ROW_PINS[r], HIGH);
    }
}

// ---------------------------------------------------------------------------
// Config button: long-press clears BLE pairings (handy if a host is stuck).
// ---------------------------------------------------------------------------
static void configButtonInit() {
#if CONFIG_BTN_PIN >= 0
    pinMode(CONFIG_BTN_PIN, CONFIG_BTN_ACTIVE_LOW ? INPUT_PULLUP : INPUT);
#endif
}

static void configButtonPoll() {
#if CONFIG_BTN_PIN >= 0
    static uint32_t downSince = 0;
    static bool handled = false;
    bool pressed = (digitalRead(CONFIG_BTN_PIN) == (CONFIG_BTN_ACTIVE_LOW ? LOW : HIGH));
    uint32_t now = millis();
    if (pressed) {
        if (downSince == 0) { downSince = now; handled = false; }
        if (!handled && (now - downSince) > 3000) {
            Keyboard.clearBonds();
            Serial.println("[btn] BLE pairings cleared");
            handled = true;
        }
    } else {
        downSince = 0;
    }
#endif
}

void setup() {
    Serial.begin(115200);
    delay(300);
    statusLedInit();
    Serial.println();
    Serial.printf("Kabuto %s booting\n", FIRMWARE_VERSION);

    if (!storageBegin()) {
        Serial.println("[fs] LittleFS mount failed");
        g_startupWarning = true;
    }
    ensureDefaultConfig();

    Macros.begin();
    if (!Macros.load()) {
        Serial.println("[cfg] no valid config, starting empty");
        g_startupWarning = true;
    }

    Keyboard.begin(DEVICE_NAME);
    Serial.printf("[ble] advertising as '%s' (%d bonds)\n", DEVICE_NAME, Keyboard.bondCount());

    webServerBegin();
    Serial.printf("[web] config portal: connect to Wi-Fi '%s' then open http://192.168.4.1\n", AP_SSID);

    matrixInit();
    configButtonInit();
    Serial.println("[ok] ready");
}

void loop() {
    Macros.processCommands();   // apply queued web actions on this (engine) task
    matrixScan();
    configButtonPoll();
    statusLedUpdate();
    delay(1000 / MATRIX_SCAN_HZ);
}
