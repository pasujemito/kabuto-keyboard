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
