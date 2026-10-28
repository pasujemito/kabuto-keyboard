#include "live_stats.h"

namespace {
portMUX_TYPE mux_ = portMUX_INITIALIZER_UNLOCKED;   // a few ints: a spinlock is plenty
int hp_ = -1, mana_ = -1, xp_ = -1, x_ = -1, y_ = -1;
uint8_t state_ = LIVE_OK, mobs_ = 0;
uint32_t at_ = 0;
bool any_ = false;
XpTracker xpTracker_;
}

bool liveStatsUpdate(int hp, int mana, int xp, uint8_t state, int x, int y, uint8_t mobs) {
    uint32_t now = millis();
    portENTER_CRITICAL(&mux_);
    bool wasOk = state_ == LIVE_OK || !any_ || now - at_ >= LIVE_STATS_STALE_MS;
    hp_ = hp; mana_ = mana; xp_ = xp; state_ = state; x_ = x; y_ = y; mobs_ = mobs;
    at_ = now; any_ = true;
    if (state == LIVE_OK) xpTracker_.add(xp, now);   // a death or login screen isn't XP news
    portEXIT_CRITICAL(&mux_);
    return wasOk && state != LIVE_OK;
}

LiveStats liveStatsSnapshot() {
    LiveStats s;
    uint32_t now = millis();
    portENTER_CRITICAL(&mux_);
    if (any_) {
        s.hp = hp_; s.mana = mana_; s.xp = xp_;
        s.state = state_; s.x = x_; s.y = y_; s.mobs = mobs_;
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
