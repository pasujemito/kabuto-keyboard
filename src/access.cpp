#include "access.h"
#include "access_logic.h"
#include <Preferences.h>
#include <mbedtls/md.h>

// Sessions are kept in flash (only their hashes, written at each login), so
// restarts and firmware updates keep you logged in. All callers run on the
// web server's task, so no lock is needed.

namespace {

const char* PREFS = "access";
SessionSlots<8> browsers_;   // phones and laptops; the one unused longest makes room
SessionSlots<2> scripts_;    // the PC screen reader (each run logs in afresh)
bool loaded_ = false;
uint32_t failures_ = 0, lockedUntil_ = 0;

std::string randomHex(size_t bytes) {
    static const char digits[] = "0123456789abcdef";
    std::string out;
    for (size_t i = 0; i < bytes; ++i) {
        uint8_t b = (uint8_t)esp_random();   // hardware RNG (radio on, so truly random)
        out += digits[b >> 4]; out += digits[b & 15];
    }
    return out;
}

std::string hashPin(const std::string& salt, const String& pin) {
    std::string input = salt + pin.c_str();
    uint8_t hash[32];
    mbedtls_md(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), (const uint8_t*)input.data(), input.size(), hash);
    static const char digits[] = "0123456789abcdef";
    std::string out;
    for (uint8_t b : hash) { out += digits[b >> 4]; out += digits[b & 15]; }
    return out;
}

std::string tokenHash(const std::string& token) { return hashPin("kabuto-session:", token.c_str()); }

void loadSessions() {
    if (loaded_) return;
    loaded_ = true;
    Preferences p; p.begin(PREFS, true);
    browsers_.load(p.getString("web", "").c_str());
    scripts_.load(p.getString("tools", "").c_str());
    p.end();
}

void saveSessions() {
    Preferences p; p.begin(PREFS, false);
    p.putString("web", browsers_.save().c_str());
    p.putString("tools", scripts_.save().c_str());
    p.end();
}

}  // namespace

bool accessPinSet() {
    Preferences p; p.begin(PREFS, true);
    bool set = p.getString("hash", "").length() > 0;
    p.end();
    return set;
}

bool accessSetPin(const String& pin) {
    if (!isValidPin(pin.c_str())) return false;
    std::string salt = randomHex(16);
    Preferences p; p.begin(PREFS, false);
    p.putString("salt", salt.c_str());
    p.putString("hash", hashPin(salt, pin).c_str());
    p.end();
    loaded_ = true;
    browsers_.clear(); scripts_.clear();
    saveSessions();   // a new PIN logs every browser out
    return true;
}

String accessLogin(const String& pin, String& err, bool script) {
    uint32_t now = millis();
    if (lockedUntil_ && (int32_t)(lockedUntil_ - now) > 0) {
        err = "Too many wrong PINs - try again in " + String((lockedUntil_ - now + 999) / 1000) + " s";
        return "";
    }
    Preferences p; p.begin(PREFS, true);
    std::string salt = p.getString("salt", "").c_str(), hash = p.getString("hash", "").c_str();
    p.end();
    if (hash.empty()) { err = "No PIN set yet - set one from the setup hotspot"; return ""; }
    if (!constantTimeEquals(hashPin(salt, pin), hash)) {
        uint32_t wait = loginLockoutMs(++failures_);
        lockedUntil_ = wait ? (now + wait) | 1 : 0;   // |1 keeps it non-zero (0 means unlocked)
        err = "Wrong PIN";
        return "";
    }
    failures_ = 0; lockedUntil_ = 0;
    std::string token = randomHex(16);
    loadSessions();
    if (script) scripts_.add(tokenHash(token)); else browsers_.add(tokenHash(token));
    saveSessions();
    return token.c_str();
}

bool accessSessionValid(const String& cookieHeader) {
    std::string token = cookieValue(cookieHeader.c_str(), ACCESS_COOKIE);
    if (token.empty()) return false;
    loadSessions();
    std::string h = tokenHash(token);
    return browsers_.touch(h) || scripts_.touch(h);
}
