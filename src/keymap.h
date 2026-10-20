#pragma once
#include <Arduino.h>

// ---------------------------------------------------------------------------
// USB HID usage keycodes (Keyboard/Keypad page, 0x07) plus modifier bitmasks.
// These are the standard values a HID keyboard reports.
// ---------------------------------------------------------------------------

// Modifier bitmask (byte 0 of the keyboard report)
enum : uint8_t {
    KM_LCTRL  = 0x01,
    KM_LSHIFT = 0x02,
    KM_LALT   = 0x04,
    KM_LGUI   = 0x08,
    KM_RCTRL  = 0x10,
    KM_RSHIFT = 0x20,
    KM_RALT   = 0x40,
    KM_RGUI   = 0x80,
};

// Common keycodes (not exhaustive; extend as needed)
enum : uint8_t {
    KC_NONE = 0x00,
    KC_A = 0x04, KC_B, KC_C, KC_D, KC_E, KC_F, KC_G, KC_H, KC_I, KC_J,
    KC_K, KC_L, KC_M, KC_N, KC_O, KC_P, KC_Q, KC_R, KC_S, KC_T,
    KC_U, KC_V, KC_W, KC_X, KC_Y, KC_Z,
    KC_1 = 0x1E, KC_2, KC_3, KC_4, KC_5, KC_6, KC_7, KC_8, KC_9, KC_0,
    KC_ENTER = 0x28, KC_ESC, KC_BACKSPACE, KC_TAB, KC_SPACE,
    KC_MINUS, KC_EQUAL, KC_LBRACKET, KC_RBRACKET, KC_BACKSLASH,
    KC_NONUS_HASH, KC_SEMICOLON, KC_QUOTE, KC_GRAVE, KC_COMMA, KC_DOT, KC_SLASH,
    KC_CAPSLOCK,
    KC_F1, KC_F2, KC_F3, KC_F4, KC_F5, KC_F6, KC_F7, KC_F8, KC_F9, KC_F10,
    KC_F11, KC_F12,
    KC_PRINTSCREEN, KC_SCROLLLOCK, KC_PAUSE, KC_INSERT, KC_HOME, KC_PAGEUP,
    KC_DELETE, KC_END, KC_PAGEDOWN, KC_RIGHT, KC_LEFT, KC_DOWN, KC_UP,
};

// Consumer-control (media) usage codes, Consumer page 0x0C
enum : uint16_t {
    CC_PLAYPAUSE = 0x00CD,
    CC_NEXT      = 0x00B5,
    CC_PREV      = 0x00B6,
    CC_STOP      = 0x00B7,
    CC_MUTE      = 0x00E2,
    CC_VOL_UP    = 0x00E9,
    CC_VOL_DOWN  = 0x00EA,
};

// Map an ASCII char to a (modifier, keycode) pair on the US layout.
// Returns true if the character is typable.
bool asciiToKey(char c, uint8_t& modifiers, uint8_t& keycode);

// Resolve a human-readable key name ("ENTER", "A", "F5", "CTRL+C" tokens are
// handled by the macro parser; this resolves single names) to a keycode.
uint8_t keycodeFromName(const String& name);

// Resolve a modifier name ("CTRL","SHIFT","ALT","GUI"/"WIN"/"CMD") to a mask.
uint8_t modifierFromName(const String& name);

// Resolve a media key name ("PLAY","NEXT","VOLUP"...) to a consumer usage, 0 if none.
uint16_t consumerFromName(const String& name);

// Reverse lookups (for serializing a config back to JSON).
String keyNameFromCode(uint8_t code);     // "A", "ENTER", "F5", "" if unknown
String consumerNameFromUsage(uint16_t u); // "VOLUP", ... "" if unknown
