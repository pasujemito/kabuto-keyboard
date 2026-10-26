#pragma once
#include <cstdint>
#include <cstdio>
#include <string>

// Pure decisions for automatic updates, kept free of Arduino so host tests
// can cover them. The networking and flashing live in updater.cpp.

// "1.14.0" -> {1,14,0}. Anything else (a "v" prefix, missing parts, trailing
// text) is rejected so a malformed release can never look newer.
inline bool parseVersion(const std::string& text, uint32_t out[3]) {
    unsigned a, b, c; char extra;
    if (std::sscanf(text.c_str(), "%u.%u.%u%c", &a, &b, &c, &extra) != 3) return false;
    out[0] = a; out[1] = b; out[2] = c;
    return true;
}

inline bool isNewerVersion(const std::string& candidate, const std::string& current) {
    uint32_t a[3], b[3];
    if (!parseVersion(candidate, a) || !parseVersion(current, b)) return false;
    for (int i = 0; i < 3; ++i) if (a[i] != b[i]) return a[i] > b[i];
    return false;
}

inline bool isSha256Hex(const std::string& text) {
    if (text.size() != 64) return false;
    for (char c : text) if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) return false;
    return true;
}

// The exact bytes the release workflow signs (tools/release_index.py):
// version, firmware size and SHA-256, one per line. Signing the version stops a
// replayed older release from posing as a newer one.
inline std::string manifestPayload(const std::string& version, uint32_t size, const std::string& sha256Hex) {
    return version + "\n" + std::to_string(size) + "\n" + sha256Hex + "\n";
}

// Installs only start when you confirm one, and never mid-playback or recording:
// the pad restarts at the end, which would cut a macro off.
inline bool canInstallNow(bool macroRunning, bool recording) {
    return !macroRunning && !recording;
}

// A freshly installed release is on trial until it has run for a minute. Each
// boot during the trial counts as an attempt; after this many it is rolled back.
const uint8_t UPDATE_MAX_TRIAL_BOOTS = 3;
const uint32_t UPDATE_HEALTHY_AFTER_MS = 60000;
inline bool shouldRollBack(bool onTrial, uint8_t attemptsIncludingThisBoot) {
    return onTrial && attemptsIncludingThisBoot > UPDATE_MAX_TRIAL_BOOTS;
}
