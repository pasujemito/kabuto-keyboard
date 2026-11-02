#pragma once
#include <cstddef>
#include <cstdint>
#include <cstdlib>
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

// Logged-in browsers (and, kept apart, the PC script): each slot holds a
// token's hash and when it was last used (a counter, not a clock). A login
// takes an empty slot or the one unused the longest, so the phone you use
// stays logged in however often something else logs in. access.cpp keeps
// them across restarts; a new PIN empties them all.
inline bool constantTimeEquals(const std::string& a, const std::string& b);
template <size_t N> struct SessionSlots {
    std::string hash[N];
    uint32_t used[N] = {};
    uint32_t clock = 0;
    size_t add(const std::string& h) {
        size_t at = 0;
        for (size_t i = 0; i < N; ++i) {
            if (hash[i].empty()) { at = i; break; }
            if (used[i] < used[at]) at = i;
        }
        hash[at] = h; used[at] = ++clock;
        return at;
    }
    bool touch(const std::string& h) {   // a request with this session: still in use
        if (h.empty()) return false;
        for (size_t i = 0; i < N; ++i)
            if (!hash[i].empty() && constantTimeEquals(hash[i], h)) { used[i] = ++clock; return true; }
        return false;
    }
    void clear() { for (size_t i = 0; i < N; ++i) { hash[i].clear(); used[i] = 0; } }
    // Kept as "hash:used,hash:used"; a damaged entry is skipped.
    std::string save() const {
        std::string out;
        for (size_t i = 0; i < N; ++i)
            if (!hash[i].empty()) out += (out.empty() ? "" : ",") + hash[i] + ":" + std::to_string(used[i]);
        return out;
    }
    void load(const std::string& text) {
        clear();
        size_t i = 0;
        for (size_t pos = 0; pos < text.size() && i < N;) {
            size_t end = text.find(',', pos);
            if (end == std::string::npos) end = text.size();
            size_t colon = text.find(':', pos);
            if (colon != std::string::npos && colon > pos && colon < end) {
                hash[i] = text.substr(pos, colon - pos);
                used[i] = (uint32_t)strtoul(text.substr(colon + 1, end - colon - 1).c_str(), nullptr, 10);
                if (used[i] > clock) clock = used[i];
                ++i;
            }
            pos = end + 1;
        }
    }
};

// Compares without stopping at the first difference, so response timing
// doesn't reveal how much of a secret matched.
inline bool constantTimeEquals(const std::string& a, const std::string& b) {
    if (a.size() != b.size()) return false;
    unsigned char diff = 0;
    for (size_t i = 0; i < a.size(); ++i) diff |= (unsigned char)(a[i] ^ b[i]);
    return diff == 0;
}
