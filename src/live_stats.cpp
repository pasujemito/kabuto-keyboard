#include "live_stats.h"

namespace {
portMUX_TYPE mux_ = portMUX_INITIALIZER_UNLOCKED;   // a few ints: a spinlock is plenty
int hp_ = -1, mana_ = -1, xp_ = -1;
uint32_t at_ = 0;
bool any_ = false;
XpTracker xpTracker_;
}

void liveStatsUpdate(int hp, int mana, int xp) {
    uint32_t now = millis();
    portENTER_CRITICAL(&mux_);
    hp_ = hp; mana_ = mana; xp_ = xp; at_ = now; any_ = true;
    xpTracker_.add(xp, now);
    portEXIT_CRITICAL(&mux_);
}

LiveStats liveStatsSnapshot() {
    LiveStats s;
    uint32_t now = millis();
    portENTER_CRITICAL(&mux_);
    if (any_) {
        s.hp = hp_; s.mana = mana_; s.xp = xp_;
        s.ageMs = now - at_;
        s.fresh = s.ageMs < LIVE_STATS_STALE_MS;
    }
    s.xpPerHour = xpTracker_.perHour();
    s.minutesToLevel = xpTracker_.minutesToLevel();
    s.levels = xpTracker_.levels;
    portEXIT_CRITICAL(&mux_);
    return s;
}

void liveStatsReset() {
    portENTER_CRITICAL(&mux_);
    xpTracker_ = XpTracker();
    portEXIT_CRITICAL(&mux_);
}
