#include "hid_keyboard.h"
#include "keymap.h"

HidKeyboard Keyboard;

// Report IDs
#define RID_KEYBOARD 1
#define RID_CONSUMER 2

// HID report map: a boot-style keyboard (report 1) + consumer control (report 2)
static const uint8_t HID_REPORT_MAP[] = {
    // ----- Keyboard (Report ID 1) -----
    0x05, 0x01,        // Usage Page (Generic Desktop)
    0x09, 0x06,        // Usage (Keyboard)
    0xA1, 0x01,        // Collection (Application)
    0x85, RID_KEYBOARD,//   Report ID (1)
    0x05, 0x07,        //   Usage Page (Keyboard/Keypad)
    0x19, 0xE0,        //   Usage Minimum (Left Control)
    0x29, 0xE7,        //   Usage Maximum (Right GUI)
    0x15, 0x00,        //   Logical Minimum (0)
    0x25, 0x01,        //   Logical Maximum (1)
    0x75, 0x01,        //   Report Size (1)
    0x95, 0x08,        //   Report Count (8)
    0x81, 0x02,        //   Input (Data,Var,Abs) ; modifier byte
    0x95, 0x01,        //   Report Count (1)
    0x75, 0x08,        //   Report Size (8)
    0x81, 0x03,        //   Input (Const) ; reserved byte
    0x95, 0x06,        //   Report Count (6)
    0x75, 0x08,        //   Report Size (8)
    0x15, 0x00,        //   Logical Minimum (0)
    0x25, 0xFF,        //   Logical Maximum (255)
    0x05, 0x07,        //   Usage Page (Keyboard/Keypad)
    0x19, 0x00,        //   Usage Minimum (0)
    0x29, 0xFF,        //   Usage Maximum (255)
    0x81, 0x00,        //   Input (Data,Array) ; 6 key slots
    0xC0,              // End Collection

    // ----- Consumer Control (Report ID 2) -----
    0x05, 0x0C,        // Usage Page (Consumer)
    0x09, 0x01,        // Usage (Consumer Control)
    0xA1, 0x01,        // Collection (Application)
    0x85, RID_CONSUMER,//   Report ID (2)
    0x15, 0x00,        //   Logical Minimum (0)
    0x26, 0xFF, 0x03,  //   Logical Maximum (0x3FF)
    0x19, 0x00,        //   Usage Minimum (0)
    0x2A, 0xFF, 0x03,  //   Usage Maximum (0x3FF)
    0x75, 0x10,        //   Report Size (16)
    0x95, 0x01,        //   Report Count (1)
    0x81, 0x00,        //   Input (Data,Array)
    0xC0               // End Collection
};

// ---- Connection callbacks -------------------------------------------------
class HidServerCallbacks : public NimBLEServerCallbacks {
public:
    void onConnect(NimBLEServer* s, ble_gap_conn_desc* desc) override {
        Keyboard.connected_ = true;
        // Keep advertising off while connected; request a secure link.
        NimBLEDevice::startSecurity(desc->conn_handle);
    }
    void onDisconnect(NimBLEServer* s) override {
        Keyboard.connected_ = false;
        Keyboard.releaseAll();
        NimBLEDevice::startAdvertising();  // allow another host to connect
    }
};

void HidKeyboard::begin(const char* deviceName) {
    NimBLEDevice::init(deviceName);
    NimBLEDevice::setPower(ESP_PWR_LVL_P9);

    // Bonding + MITM protection, display-only-ish; "just works" if no IO.
    NimBLEDevice::setSecurityAuth(true, false, true);  // bond, no MITM, SC

    NimBLEServer* server = NimBLEDevice::createServer();
    server->setCallbacks(new HidServerCallbacks());

    hid_ = new NimBLEHIDDevice(server);
    inputKbd_  = hid_->inputReport(RID_KEYBOARD);
    inputCons_ = hid_->inputReport(RID_CONSUMER);

    hid_->manufacturer()->setValue("Kabuto");
    hid_->pnp(0x02, 0xE502, 0xA111, 0x0210);
    hid_->hidInfo(0x00, 0x01);
    hid_->reportMap((uint8_t*)HID_REPORT_MAP, sizeof(HID_REPORT_MAP));
    hid_->startServices();

    NimBLEAdvertising* adv = NimBLEDevice::getAdvertising();
    adv->setAppearance(0x03C1);  // HID Keyboard
    adv->addServiceUUID(hid_->hidService()->getUUID());
    adv->setScanResponse(true);
    adv->start();
}

bool HidKeyboard::isConnected() { return connected_; }

void HidKeyboard::sendKeyReport() {
    if (!connected_ || !inputKbd_) return;
    uint8_t report[8] = {
        modifiers_, 0x00,
        keys_[0], keys_[1], keys_[2], keys_[3], keys_[4], keys_[5]
    };
    inputKbd_->setValue(report, sizeof(report));
    inputKbd_->notify();
}

void HidKeyboard::pressKey(uint8_t keycode, uint8_t modifiers) {
    modifiers_ |= modifiers;
    if (keycode != KC_NONE) {
        for (int i = 0; i < 6; i++) if (keys_[i] == keycode) { sendKeyReport(); return; }
        for (int i = 0; i < 6; i++) if (keys_[i] == 0) { keys_[i] = keycode; break; }
    }
    sendKeyReport();
}

void HidKeyboard::releaseKey(uint8_t keycode) {
    for (int i = 0; i < 6; i++) if (keys_[i] == keycode) keys_[i] = 0;
    sendKeyReport();
}

void HidKeyboard::releaseModifiers(uint8_t mask) {
    modifiers_ &= ~mask;
    sendKeyReport();
}

void HidKeyboard::releaseAll() {
    modifiers_ = 0;
    for (int i = 0; i < 6; i++) keys_[i] = 0;
    sendKeyReport();
}

void HidKeyboard::tap(uint8_t keycode, uint8_t modifiers, uint16_t holdMs) {
    pressKey(keycode, modifiers);
    if (holdMs) delay(holdMs);
    // Release just this key + its modifiers, leave any other held keys intact.
    for (int i = 0; i < 6; i++) if (keys_[i] == keycode) keys_[i] = 0;
    modifiers_ &= ~modifiers;
    sendKeyReport();
}

void HidKeyboard::typeChar(char c) {
    uint8_t m, k;
    if (!asciiToKey(c, m, k)) return;
    tap(k, m, 2);
    delay(2);
}

void HidKeyboard::typeString(const String& s) {
    for (size_t i = 0; i < s.length(); i++) typeChar(s[i]);
}

void HidKeyboard::consumerPress(uint16_t usage) {
    if (!connected_ || !inputCons_) return;
    uint8_t report[2] = { (uint8_t)(usage & 0xFF), (uint8_t)((usage >> 8) & 0xFF) };
    inputCons_->setValue(report, sizeof(report));
    inputCons_->notify();
}

void HidKeyboard::consumerRelease() {
    if (!connected_ || !inputCons_) return;
    uint8_t report[2] = {0, 0};
    inputCons_->setValue(report, sizeof(report));
    inputCons_->notify();
}

void HidKeyboard::clearBonds() { NimBLEDevice::deleteAllBonds(); }

int HidKeyboard::bondCount() { return NimBLEDevice::getNumBonds(); }
