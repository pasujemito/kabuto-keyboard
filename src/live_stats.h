#pragma once
#include <Arduino.h>
#include "stats_logic.h"

// The latest readings sent by tools/screen_stats.py (POST /api/stats).
// Written by the web server, read by the macro engine and the status API.
// Bars and minimap position are tenths of a percent; -1 means not read.
// All screen work happens on the PC: this is a few ints on the pad.

struct LiveStats {
    int hp = -1, mana = -1, xp = -1;
    uint8_t state = LIVE_OK;     // LiveState: dead/offline stop playback
    int x = -1, y = -1;          // your dot on the minimap
    int wx = LIVE_NO_POS, wy = LIVE_NO_POS;   // your place on the whole map (stats_logic.h)
    uint8_t mobs = 0;            // in reach: MOB_LEFT | MOB_RIGHT | MOB_RIGHT_NEARER | MOB_READ
    int ml = -1, mr = -1;        // mobs seen each side (-1: not read)
    int dl = -1, dr = -1;        // nearest each side, % of your reach (-1: none)
    char mob[LIVE_NAME_LEN] = {};   // the nearest mob's name ("" unknown)
    char map[LIVE_NAME_LEN] = {};   // the map's name ("-" not taught, "" no map library)
    uint32_t ageMs = 0;          // since the last reading
    bool fresh = false;          // a reading within LIVE_STATS_STALE_MS
    int32_t xpPerHour = -1;      // tenths of a percent of a level per hour
    int32_t minutesToLevel = -1;
    uint32_t levels = 0;         // level-ups seen since the last reset
};

// True when this reading turns the state from OK to a stop reason.
bool liveStatsUpdate(const StatsReading& r);
bool liveStatsUpdate(int hp, int mana, int xp, uint8_t state = LIVE_OK, int x = -1, int y = -1, uint8_t mobs = 0,
                     int wx = LIVE_NO_POS, int wy = LIVE_NO_POS);
LiveStats liveStatsSnapshot();
void liveStatsReset();   // start the XP rate afresh

// What a playing dynamic pattern is doing, for the dashboard. Written by the
// engine, read by the status API.
struct PatternView {
    bool active = false;         // a dynamic pattern is playing
    bool smart = false;
    uint8_t action = SMART_ATTACK;   // SmartAction
    bool facingLeft = false;
    bool haveHome = false;
    int home = 0;                // same units as the position it came from
    bool homeOnMap = false;      // home is a map position (wx), not the minimap dot
    uint16_t homeRange = 0;      // permille of the minimap; 0 = no home
    int peak = -1;               // auto-pause: most mobs seen lately (-1: off)
};
void patternViewSet(const PatternView& v);
PatternView patternViewSnapshot();
