#pragma once
#include <Arduino.h>
#include "stats_logic.h"

// The latest readings sent by tools/screen_stats.py (POST /api/stats).
// Written by the web server, read by the macro engine and the status API.
// Bars and minimap position are tenths of a percent; -1 means not read.
// All screen work happens on the PC: this is a few ints on the pad.

struct LiveStats {
    int hp = -1, mana = -1, xp = -1;
    uint8_t state = LIVE_OK;     // LiveState: dead/offline/map changed stop playback
    int x = -1, y = -1;          // your dot on the minimap
    int wx = LIVE_NO_POS, wy = LIVE_NO_POS;   // your place on the whole map (stats_logic.h)
    uint8_t mobs = 0;            // MOB_LEFT | MOB_RIGHT
    uint32_t ageMs = 0;          // since the last reading
    bool fresh = false;          // a reading within LIVE_STATS_STALE_MS
    int32_t xpPerHour = -1;      // tenths of a percent of a level per hour
    int32_t minutesToLevel = -1;
    uint32_t levels = 0;         // level-ups seen since the last reset
};

// True when this reading turns the state from OK to a stop reason.
bool liveStatsUpdate(int hp, int mana, int xp, uint8_t state = LIVE_OK, int x = -1, int y = -1, uint8_t mobs = 0,
                     int wx = LIVE_NO_POS, int wy = LIVE_NO_POS);
LiveStats liveStatsSnapshot();
void liveStatsReset();   // start the XP rate afresh
