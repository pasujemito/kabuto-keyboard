#pragma once
// ---------------------------------------------------------------------------
// Hardware & build configuration
// ---------------------------------------------------------------------------
// Adjust these to match your wiring. The defaults assume a simple matrix of
// physical keys plus one "config mode" button.

#define DEVICE_NAME        "Kabuto"
#define FIRMWARE_VERSION   "1.10.1"

// --- Key matrix -----------------------------------------------------------
// A matrix of ROWS x COLS mechanical keys. Each intersection is one
// physical key whose index is (row * MATRIX_COLS + col).
#define MATRIX_ROWS        2
#define MATRIX_COLS        3
#define KEY_COUNT          (MATRIX_ROWS * MATRIX_COLS)

// GPIOs driven LOW one at a time (outputs).
static const int ROW_PINS[MATRIX_ROWS] = {4, 5};
// GPIOs read with internal pull-ups (inputs). A pressed key reads LOW.
static const int COL_PINS[MATRIX_COLS] = {6, 7, 15};

// --- Config-mode button ---------------------------------------------------
// Hold this at boot (or press any time) to start the Wi-Fi config portal.
#define CONFIG_BTN_PIN     0            // BOOT button on most dev kits
#define CONFIG_BTN_ACTIVE_LOW 1

// --- Status LED -----------------------------------------------------------
#define STATUS_LED_PIN     48           // on-board RGB on many S3 kits (set -1 to disable)

// --- Behaviour ------------------------------------------------------------
#define DEBOUNCE_MS        8            // key debounce window
#define MATRIX_SCAN_HZ     1000         // matrix poll rate
#define MATRIX_SETTLE_US   40           // column settle time after driving a row LOW
                                        // (raise to ~60-80 if keys are still flaky
                                        //  with long wires; lower only if all solid)
#define MAX_LAYERS         8
#define MAX_MACRO_STEPS    256          // per macro
#define MACRO_FILE         "/macros.json"
#define MACRO_TMP_FILE     "/macros.tmp"  // uploads land here, then replace MACRO_FILE
#define MAX_CONFIG_BYTES   (256 * 1024)   // reject larger config uploads

// --- Config portal --------------------------------------------------------
#define AP_SSID            "Kabuto-Setup"
#define AP_PASSWORD        "macropad123"   // >= 8 chars; change before real use
#define AP_CHANNEL         6
