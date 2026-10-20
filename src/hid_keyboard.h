#pragma once
#include <Arduino.h>
#include <NimBLEDevice.h>
#include <NimBLEHIDDevice.h>

// ---------------------------------------------------------------------------
// BLE HID keyboard (boot keyboard + consumer/media control).
//
// Acts as a standard Bluetooth keyboard. Bonds are stored by NimBLE, so the
// device can be paired with several hosts; selecting which host to connect to
// is done the usual BLE way (connect from whichever host is in range, or
// clear bonds to re-pair).
// ---------------------------------------------------------------------------

class HidKeyboard {
public:
    void begin(const char* deviceName);
    bool isConnected();

    // Low-level key report: up to 6 simultaneous keycodes + modifier bitmask.
    void pressKey(uint8_t keycode, uint8_t modifiers = 0);
    void releaseKey(uint8_t keycode);
    void releaseModifiers(uint8_t mask);   // release held modifier bits
    void releaseAll();

    // Convenience: press then release with an optional hold time.
    void tap(uint8_t keycode, uint8_t modifiers = 0, uint16_t holdMs = 0);

    // Type an ASCII character / string using the US layout mapping.
    void typeChar(char c);
    void typeString(const String& s);

    // Consumer control (media keys): usage codes from the Consumer page.
    void consumerPress(uint16_t usage);
    void consumerRelease();

    // Forget all bonded hosts (next connection will re-pair).
    void clearBonds();

    // Number of currently bonded hosts.
    int bondCount();

private:
    void sendKeyReport();

    NimBLEHIDDevice*     hid_        = nullptr;
    NimBLECharacteristic* inputKbd_  = nullptr;
    NimBLECharacteristic* inputCons_ = nullptr;
    bool                 connected_  = false;

    uint8_t modifiers_ = 0;
    uint8_t keys_[6]   = {0, 0, 0, 0, 0, 0};

    friend class HidServerCallbacks;
};

extern HidKeyboard Keyboard;
