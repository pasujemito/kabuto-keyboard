#pragma once
#include <cstdint>
#include <cstdlib>
#include <cstring>

// Live HP/Mana/XP, read off the game screen by tools/screen_stats.py as bar
// fill percentages (pure, host-tested). Kept in tenths of a percent (0-1000).

const uint32_t LIVE_STATS_STALE_MS = 5000;   // older readings fall back to potion timers
const uint32_t LIVE_POTION_GAP_MS = 3000;    // let a potion land before drinking again
const uint32_t XP_RATE_MIN_MS = 60000;       // a minute of readings before showing a rate

// XP gained from the XP bar, counting through level-ups (the bar wraps from
// near full to near empty). Smaller drops (death penalty, a misread) are
// ignored rather than subtracted.
struct XpTracker {
    uint32_t startMs = 0, lastMs = 0, levels = 0;
    uint64_t gained = 0;   // tenths of a percent of a level
    int lastXp = -1;

    void add(int xp, uint32_t nowMs) {
        if (xp < 0 || xp > 1000) return;
        if (lastXp < 0) { lastXp = xp; startMs = lastMs = nowMs; return; }
        int delta = xp - lastXp;
        if (delta < -500) { delta += 1000; ++levels; }
        else if (delta < 0) delta = 0;
        gained += (uint64_t)delta; lastXp = xp; lastMs = nowMs;
    }
    // Tenths of a percent of a level per hour, or -1 until there's a minute of data.
    int32_t perHour() const {
        uint32_t ms = lastMs - startMs;
        return lastXp < 0 || ms < XP_RATE_MIN_MS ? -1 : (int32_t)(gained * 3600000ULL / ms);
    }
    // Minutes until the next level at the current rate, or -1 if unknown.
    int32_t minutesToLevel() const {
        int32_t rate = perHour();
        return rate <= 0 ? -1 : (int32_t)((1000 - lastXp) * 60LL / rate);
    }
};

// With a fresh reading and a threshold set, a potion drinks when its bar is
// under the threshold, at most every LIVE_POTION_GAP_MS. Returns false when
// the timer should decide instead (no threshold, or that bar isn't being read).
inline bool liveDecides(uint8_t belowPercent, bool freshReadingOfThisBar) { return belowPercent && freshReadingOfThisBar; }
// With the bar's real total and what one tap restores: how many taps fill the
// gap without wasting any (rounded down), at least 1, at most
// LIVE_POTION_MAX_TAPS. 0 = amounts not set (use the potion's taps range).
const uint32_t LIVE_POTION_MAX_TAPS = 10;
inline uint32_t livePotionTaps(int valueTenths, uint32_t barMax, uint32_t perTap) {
    if (!barMax || !perTap || valueTenths < 0 || valueTenths > 1000) return 0;
    uint64_t taps = (uint64_t)barMax * (uint32_t)(1000 - valueTenths) / 1000 / perTap;
    return taps < 1 ? 1 : taps > LIVE_POTION_MAX_TAPS ? LIVE_POTION_MAX_TAPS : (uint32_t)taps;
}
inline bool liveWantsPotion(uint8_t belowPercent, int valueTenths, bool drunkBefore, uint32_t msSinceDrink) {
    return valueTenths >= 0 && valueTenths < belowPercent * 10 && (!drunkBefore || msSinceDrink >= LIVE_POTION_GAP_MS);
}

// Game state reported by the screen reader. Anything but OK stops playback.
enum LiveState : uint8_t { LIVE_OK = 0, LIVE_DEAD = 1, LIVE_OFFLINE = 2 };
inline const char* liveStopReason(uint8_t state) {
    switch (state) {
        case LIVE_DEAD: return "you died";
        case LIVE_OFFLINE: return "the game is disconnected or at the login screen";
        default: return nullptr;
    }
}

// Mob sides from the screen reader: bit 0 = left of you, bit 1 = right,
// bit 2 = with both, the right one is nearer (sent as "RL"; "LR" = left
// nearer), bit 3 = the mob detector is set up (the reading has "mobs"), so
// no side bits really means no mobs rather than "not looking".
const uint8_t MOB_LEFT = 1, MOB_RIGHT = 2, MOB_RIGHT_NEARER = 4, MOB_READ = 8;

// Which way to face from live data: -1 left, +1 right, 0 no opinion (the
// pattern's own turn chance decides). Keeping off a map edge comes first;
// then facing the mob: the only side with mobs, or the nearer one when both
// sides have some. x is the minimap position in
// tenths of a percent (-1: not read).
// Smart mode, before each attack: attack, wait for mobs, or walk back home.
// Home is your position when the pattern started; you may drift `range`
// either way (same units as the position: tenths of a minimap width; 0 = no
// home). Out of range with no mobs, or twice out of range whatever's around,
// it walks back, and once walking keeps on until within half the range.
// No fresh reading or no mob detector: just attack, as without smart mode.
enum SmartAction : uint8_t { SMART_ATTACK, SMART_WAIT, SMART_WALK_LEFT, SMART_WALK_RIGHT };
inline uint8_t smartAction(bool fresh, uint8_t mobs, bool havePos, int pos, bool haveHome, int home, uint16_t range, bool homing) {
    if (!fresh) return SMART_ATTACK;
    bool any = mobs & (MOB_LEFT | MOB_RIGHT);
    if (havePos && haveHome && range) {
        int off = pos - home, dist = off < 0 ? -off : off;
        if (dist > (homing ? range / 2 : range) && (!any || dist > 2 * range)) return off > 0 ? SMART_WALK_LEFT : SMART_WALK_RIGHT;
    }
    return (mobs & MOB_READ) && !any ? SMART_WAIT : SMART_ATTACK;
}

inline int liveFacing(bool fresh, int x, uint16_t edgeMarginTenths, bool faceMobs, uint8_t mobSides) {
    if (!fresh) return 0;
    if (edgeMarginTenths && x >= 0) {
        if (x < edgeMarginTenths) return +1;
        if (x > 1000 - edgeMarginTenths) return -1;
    }
    if (!faceMobs) return 0;
    bool left = mobSides & MOB_LEFT, right = mobSides & MOB_RIGHT;
    if (left && right) return mobSides & MOB_RIGHT_NEARER ? +1 : -1;
    return left ? -1 : right ? +1 : 0;
}

// Map position (wx/wy): where you are on the whole map, in tenths of a
// minimap width/height, counting how far a sliding minimap has moved. Your dot
// can sit in the middle while you walk, so this is what tells you're moving.
// It can go below 0 or past 1000; LIVE_NO_POS = not read.
const int LIVE_NO_POS = -1000000;

// Stuck = your position stays within `radius` for `afterMs`. The first time
// returns 1 (try turning around); still stuck a window later returns 2 (stop).
// `seen` false (no position) starts over.
struct StuckWatch {
    bool has = false;
    int x = 0, y = 0;
    uint32_t since = 0;
    uint8_t strikes = 0;
    uint8_t update(bool seen, int nx, int ny, uint32_t now, uint32_t afterMs, int radius = 15) {
        if (!seen) { has = false; return 0; }
        if (!has || nx - x > radius || x - nx > radius || ny - y > radius || y - ny > radius) {
            has = true; x = nx; y = ny; since = now; strikes = 0; return 0;
        }
        if (now - since < afterMs) return 0;
        since = now;
        return ++strikes >= 2 ? 2 : 1;
    }
};

// ---- readings from tools/screen_stats.py -----------------------------------
// The same form ("hp=72.5&mana=40&xp=63.2&x=41.5&y=70&wx=1415&wy=700&state=ok&mobs=L") comes
// over Wi-Fi (POST /api/stats) or the USB cable ("KABUTO stats <form>").

// "72.5" -> 725 tenths. Empty, not a number or outside 0-100 -> -1 (not read):
// a blank must never look like an empty HP bar, which would trigger a potion.
inline int statsTenths(const char* text) {
    if (!text || !*text) return -1;
    char* end;
    double v = strtod(text, &end);
    if (end == text || *end || !(v >= 0 && v <= 100)) return -1;
    return (int)(v * 10 + 0.5);
}
// Map position: a whole number within +-100000, else LIVE_NO_POS.
inline int statsPos(const char* text) {
    if (!text || !*text) return LIVE_NO_POS;
    char* end;
    long v = strtol(text, &end, 10);
    if (end == text || *end || v < -100000 || v > 100000) return LIVE_NO_POS;
    return (int)v;
}
inline uint8_t statsState(const char* text) {
    if (!text) return LIVE_OK;
    if (!strcmp(text, "dead")) return LIVE_DEAD;
    if (!strcmp(text, "offline")) return LIVE_OFFLINE;
    return LIVE_OK;
}
inline uint8_t statsMobs(const char* text) {
    if (!text) return 0;   // no "mobs" in the reading: no detector
    uint8_t sides = (strchr(text, 'L') ? MOB_LEFT : 0) | (strchr(text, 'R') ? MOB_RIGHT : 0);
    return MOB_READ | (sides == (MOB_LEFT | MOB_RIGHT) && text[0] == 'R' ? sides | MOB_RIGHT_NEARER : sides);
}

struct StatsReading {
    int hp = -1, mana = -1, xp = -1, x = -1, y = -1, wx = LIVE_NO_POS, wy = LIVE_NO_POS;
    uint8_t state = LIVE_OK, mobs = 0;
};

// Parses the form without allocating. Unknown keys are ignored; values the
// script sends never need escaping (numbers, ok/dead/offline, L/R).
inline StatsReading parseStatsForm(const char* form) {
    StatsReading r;
    while (form && *form) {
        const char* amp = strchr(form, '&');
        size_t len = amp ? (size_t)(amp - form) : strlen(form);
        const char* eq = (const char*)memchr(form, '=', len);
        if (eq) {
            char key[8] = {}, value[16] = {};
            size_t kl = (size_t)(eq - form), vl = len - kl - 1;
            if (kl < sizeof(key) && vl < sizeof(value)) {
                memcpy(key, form, kl); memcpy(value, eq + 1, vl);
                if (!strcmp(key, "hp")) r.hp = statsTenths(value);
                else if (!strcmp(key, "mana")) r.mana = statsTenths(value);
                else if (!strcmp(key, "xp")) r.xp = statsTenths(value);
                else if (!strcmp(key, "x")) r.x = statsTenths(value);
                else if (!strcmp(key, "y")) r.y = statsTenths(value);
                else if (!strcmp(key, "wx")) r.wx = statsPos(value);
                else if (!strcmp(key, "wy")) r.wy = statsPos(value);
                else if (!strcmp(key, "state")) r.state = statsState(value);
                else if (!strcmp(key, "mobs")) r.mobs = statsMobs(value);
            }
        }
        form = amp ? amp + 1 : nullptr;
    }
    return r;
}
