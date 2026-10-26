#pragma once
#include <cstddef>
#include <cstdint>
#include <string>

// PIN rules, login throttling and cookie parsing for the editor on your home
// network (pure, host-tested). The setup hotspot needs no PIN: it has its own
// Wi-Fi password. See access.cpp.

const size_t PIN_MIN_LENGTH = 6, PIN_MAX_LENGTH = 32;
inline bool isValidPin(const std::string& pin) {
    if (pin.size() < PIN_MIN_LENGTH || pin.size() > PIN_MAX_LENGTH) return false;
    for (char c : pin) if (c < 0x20 || c > 0x7e) return false;   // printable ASCII
    return true;
}

// Wait before the next login after `failures` wrong PINs in a row: none for
// the first 4, then 30 s doubling up to 15 min, so guessing a PIN takes years.
inline uint32_t loginLockoutMs(uint32_t failures) {
    if (failures < 5) return 0;
    uint32_t ms = 30000;
    for (uint32_t i = 5; i < failures && ms < 900000; ++i) ms *= 2;
    return ms > 900000 ? 900000 : ms;
}

// The value of `name` in a Cookie header ("a=1; kabuto_session=abc"), or "".
inline std::string cookieValue(const std::string& header, const std::string& name) {
    const std::string key = name + "=";
    for (size_t pos = 0; pos < header.size();) {
        size_t end = header.find(';', pos);
        if (end == std::string::npos) end = header.size();
        size_t start = header.find_first_not_of(' ', pos);
        if (start < end && header.compare(start, key.size(), key) == 0)
            return header.substr(start + key.size(), end - start - key.size());
        pos = end + 1;
    }
    return "";
}

// Compares without stopping at the first difference, so response timing
// doesn't reveal how much of a secret matched.
inline bool constantTimeEquals(const std::string& a, const std::string& b) {
    if (a.size() != b.size()) return false;
    unsigned char diff = 0;
    for (size_t i = 0; i < a.size(); ++i) diff |= (unsigned char)(a[i] ^ b[i]);
    return diff == 0;
}
