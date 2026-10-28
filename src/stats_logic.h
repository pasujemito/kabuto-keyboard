#pragma once
#include <cstdint>

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
inline bool liveWantsPotion(uint8_t belowPercent, int valueTenths, bool drunkBefore, uint32_t msSinceDrink) {
    return valueTenths >= 0 && valueTenths < belowPercent * 10 && (!drunkBefore || msSinceDrink >= LIVE_POTION_GAP_MS);
}

// Game state reported by the screen reader. Anything but OK stops playback.
enum LiveState : uint8_t { LIVE_OK = 0, LIVE_DEAD = 1, LIVE_OFFLINE = 2, LIVE_MAP_CHANGED = 3 };
inline const char* liveStopReason(uint8_t state) {
    switch (state) {
        case LIVE_DEAD: return "you died";
        case LIVE_OFFLINE: return "the game is disconnected or at the login screen";
        case LIVE_MAP_CHANGED: return "the map changed";
        default: return nullptr;
    }
}

// Mob sides from the screen reader: bit 0 = left of you, bit 1 = right.
const uint8_t MOB_LEFT = 1, MOB_RIGHT = 2;

// Which way to face from live data: -1 left, +1 right, 0 no opinion (the
// pattern's own turn chance decides). Keeping off a map edge comes first;
// then facing mobs that are on one side only. x is the minimap position in
// tenths of a percent (-1: not read).
inline int liveFacing(bool fresh, int x, uint16_t edgeMarginTenths, bool faceMobs, uint8_t mobSides) {
    if (!fresh) return 0;
    if (edgeMarginTenths && x >= 0) {
        if (x < edgeMarginTenths) return +1;
        if (x > 1000 - edgeMarginTenths) return -1;
    }
    if (faceMobs && mobSides == MOB_LEFT) return -1;
    if (faceMobs && mobSides == MOB_RIGHT) return +1;
    return 0;
}

// Stuck = the minimap dot stays within `radius` for `afterMs`. The first time
// returns 1 (try turning around); still stuck a window later returns 2 (stop).
struct StuckWatch {
    int x = -1, y = -1;
    uint32_t since = 0;
    uint8_t strikes = 0;
    uint8_t update(int nx, int ny, uint32_t now, uint32_t afterMs, int radius = 15) {
        if (nx < 0 || ny < 0) { x = -1; return 0; }
        if (x < 0 || nx - x > radius || x - nx > radius || ny - y > radius || y - ny > radius) {
            x = nx; y = ny; since = now; strikes = 0; return 0;
        }
        if (now - since < afterMs) return 0;
        since = now;
        return ++strikes >= 2 ? 2 : 1;
    }
};
