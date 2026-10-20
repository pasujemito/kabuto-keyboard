#include "keymap.h"

bool asciiToKey(char c, uint8_t& modifiers, uint8_t& keycode) {
    modifiers = 0;
    keycode   = 0;

    if (c >= 'a' && c <= 'z') { keycode = KC_A + (c - 'a'); return true; }
    if (c >= 'A' && c <= 'Z') { modifiers = KM_LSHIFT; keycode = KC_A + (c - 'A'); return true; }
    if (c >= '1' && c <= '9') { keycode = KC_1 + (c - '1'); return true; }
    if (c == '0') { keycode = KC_0; return true; }

    switch (c) {
        case ' ':  keycode = KC_SPACE; return true;
        case '\n': keycode = KC_ENTER; return true;
        case '\t': keycode = KC_TAB;   return true;
        case '-':  keycode = KC_MINUS; return true;
        case '_':  modifiers = KM_LSHIFT; keycode = KC_MINUS; return true;
        case '=':  keycode = KC_EQUAL; return true;
        case '+':  modifiers = KM_LSHIFT; keycode = KC_EQUAL; return true;
        case '[':  keycode = KC_LBRACKET; return true;
        case '{':  modifiers = KM_LSHIFT; keycode = KC_LBRACKET; return true;
        case ']':  keycode = KC_RBRACKET; return true;
        case '}':  modifiers = KM_LSHIFT; keycode = KC_RBRACKET; return true;
        case '\\': keycode = KC_BACKSLASH; return true;
        case '|':  modifiers = KM_LSHIFT; keycode = KC_BACKSLASH; return true;
        case ';':  keycode = KC_SEMICOLON; return true;
        case ':':  modifiers = KM_LSHIFT; keycode = KC_SEMICOLON; return true;
        case '\'': keycode = KC_QUOTE; return true;
        case '"':  modifiers = KM_LSHIFT; keycode = KC_QUOTE; return true;
        case '`':  keycode = KC_GRAVE; return true;
        case '~':  modifiers = KM_LSHIFT; keycode = KC_GRAVE; return true;
        case ',':  keycode = KC_COMMA; return true;
        case '<':  modifiers = KM_LSHIFT; keycode = KC_COMMA; return true;
        case '.':  keycode = KC_DOT; return true;
        case '>':  modifiers = KM_LSHIFT; keycode = KC_DOT; return true;
        case '/':  keycode = KC_SLASH; return true;
        case '?':  modifiers = KM_LSHIFT; keycode = KC_SLASH; return true;
        case '!':  modifiers = KM_LSHIFT; keycode = KC_1; return true;
        case '@':  modifiers = KM_LSHIFT; keycode = KC_2; return true;
        case '#':  modifiers = KM_LSHIFT; keycode = KC_3; return true;
        case '$':  modifiers = KM_LSHIFT; keycode = KC_4; return true;
        case '%':  modifiers = KM_LSHIFT; keycode = KC_5; return true;
        case '^':  modifiers = KM_LSHIFT; keycode = KC_6; return true;
        case '&':  modifiers = KM_LSHIFT; keycode = KC_7; return true;
        case '*':  modifiers = KM_LSHIFT; keycode = KC_8; return true;
        case '(':  modifiers = KM_LSHIFT; keycode = KC_9; return true;
        case ')':  modifiers = KM_LSHIFT; keycode = KC_0; return true;
    }
    return false;
}

struct NamedKey { const char* name; uint8_t code; };
static const NamedKey kNamedKeys[] = {
    {"ENTER", KC_ENTER}, {"RETURN", KC_ENTER}, {"ESC", KC_ESC}, {"ESCAPE", KC_ESC},
    {"BACKSPACE", KC_BACKSPACE}, {"BKSP", KC_BACKSPACE}, {"TAB", KC_TAB},
    {"SPACE", KC_SPACE}, {"SPC", KC_SPACE}, {"CAPS", KC_CAPSLOCK},
    {"INSERT", KC_INSERT}, {"INS", KC_INSERT}, {"DELETE", KC_DELETE}, {"DEL", KC_DELETE},
    {"HOME", KC_HOME}, {"END", KC_END}, {"PAGEUP", KC_PAGEUP}, {"PGUP", KC_PAGEUP},
    {"PAGEDOWN", KC_PAGEDOWN}, {"PGDN", KC_PAGEDOWN},
    {"UP", KC_UP}, {"DOWN", KC_DOWN}, {"LEFT", KC_LEFT}, {"RIGHT", KC_RIGHT},
    {"PRINTSCREEN", KC_PRINTSCREEN}, {"PRTSC", KC_PRINTSCREEN},
    {"F1", KC_F1}, {"F2", KC_F2}, {"F3", KC_F3}, {"F4", KC_F4}, {"F5", KC_F5},
    {"F6", KC_F6}, {"F7", KC_F7}, {"F8", KC_F8}, {"F9", KC_F9}, {"F10", KC_F10},
    {"F11", KC_F11}, {"F12", KC_F12},
};

uint8_t keycodeFromName(const String& name) {
    String n = name; n.trim(); n.toUpperCase();
    if (n.length() == 1) {
        uint8_t m, k;
        if (asciiToKey(n[0], m, k)) return k;  // letters/digits
    }
    for (const auto& e : kNamedKeys) {
        if (n == e.name) return e.code;
    }
    return KC_NONE;
}

uint8_t modifierFromName(const String& name) {
    String n = name; n.trim(); n.toUpperCase();
    if (n == "CTRL" || n == "CONTROL" || n == "LCTRL") return KM_LCTRL;
    if (n == "RCTRL") return KM_RCTRL;
    if (n == "SHIFT" || n == "LSHIFT") return KM_LSHIFT;
    if (n == "RSHIFT") return KM_RSHIFT;
    if (n == "ALT" || n == "LALT") return KM_LALT;
    if (n == "RALT" || n == "ALTGR") return KM_RALT;
    if (n == "GUI" || n == "WIN" || n == "CMD" || n == "META" || n == "SUPER" || n == "LGUI") return KM_LGUI;
    if (n == "RGUI") return KM_RGUI;
    return 0;
}

String keyNameFromCode(uint8_t code) {
    if (code == KC_NONE) return "";
    if (code >= KC_A && code <= KC_Z) return String((char)('A' + (code - KC_A)));
    if (code >= KC_1 && code <= KC_9) return String((char)('1' + (code - KC_1)));
    if (code == KC_0) return "0";
    for (const auto& e : kNamedKeys) if (e.code == code) return String(e.name);
    return "";
}

String consumerNameFromUsage(uint16_t u) {
    switch (u) {
        case CC_PLAYPAUSE: return "PLAY";
        case CC_NEXT:      return "NEXT";
        case CC_PREV:      return "PREV";
        case CC_STOP:      return "STOP";
        case CC_MUTE:      return "MUTE";
        case CC_VOL_UP:    return "VOLUP";
        case CC_VOL_DOWN:  return "VOLDOWN";
    }
    return "";
}

uint16_t consumerFromName(const String& name) {
    String n = name; n.trim(); n.toUpperCase();
    if (n == "PLAY" || n == "PLAYPAUSE" || n == "PAUSE") return CC_PLAYPAUSE;
    if (n == "NEXT")   return CC_NEXT;
    if (n == "PREV" || n == "PREVIOUS") return CC_PREV;
    if (n == "STOP")   return CC_STOP;
    if (n == "MUTE")   return CC_MUTE;
    if (n == "VOLUP" || n == "VOLUMEUP")   return CC_VOL_UP;
    if (n == "VOLDOWN" || n == "VOLUMEDOWN") return CC_VOL_DOWN;
    return 0;
}
