#pragma once
#include <Arduino.h>
#include "stats_logic.h"

// The latest HP/Mana/XP sent by tools/screen_stats.py (POST /api/stats).
// Written by the web server, read by the macro engine and the status API.
// Values are tenths of a percent; -1 means that bar isn't being read.

struct LiveStats {
    int hp = -1, mana = -1, xp = -1;
    uint32_t ageMs = 0;          // since the last reading
    bool fresh = false;          // a reading within LIVE_STATS_STALE_MS
    int32_t xpPerHour = -1;      // tenths of a percent of a level per hour
    int32_t minutesToLevel = -1;
    uint32_t levels = 0;         // level-ups seen since the last reset
};

void liveStatsUpdate(int hp, int mana, int xp);
LiveStats liveStatsSnapshot();
void liveStatsReset();   // start the XP rate afresh
