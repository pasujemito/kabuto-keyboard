#include "live_stats.h"

namespace {
portMUX_TYPE mux_ = portMUX_INITIALIZER_UNLOCKED;   // a few ints: a spinlock is plenty
int hp_ = -1, mana_ = -1, xp_ = -1, x_ = -1, y_ = -1, wx_ = LIVE_NO_POS, wy_ = LIVE_NO_POS;
uint8_t state_ = LIVE_OK, mobs_ = 0;
int ml_ = -1, mr_ = -1, dl_ = -1, dr_ = -1;
char mob_[LIVE_NAME_LEN] = {}, map_[LIVE_NAME_LEN] = {};
PatternView view_;
uint32_t at_ = 0;
bool any_ = false;
XpTracker xpTracker_;
}

bool liveStatsUpdate(const StatsReading& r) {
    uint32_t now = millis();
    portENTER_CRITICAL(&mux_);
    bool wasOk = state_ == LIVE_OK || !any_ || now - at_ >= LIVE_STATS_STALE_MS;
    hp_ = r.hp; mana_ = r.mana; xp_ = r.xp; state_ = r.state; x_ = r.x; y_ = r.y; mobs_ = r.mobs; wx_ = r.wx; wy_ = r.wy;
    ml_ = r.ml; mr_ = r.mr; dl_ = r.dl; dr_ = r.dr;
    memcpy(mob_, r.mob, LIVE_NAME_LEN); memcpy(map_, r.map, LIVE_NAME_LEN);
    at_ = now; any_ = true;
    if (r.state == LIVE_OK) xpTracker_.add(r.xp, now);   // a death or login screen isn't XP news
    portEXIT_CRITICAL(&mux_);
    return wasOk && r.state != LIVE_OK;
}

bool liveStatsUpdate(int hp, int mana, int xp, uint8_t state, int x, int y, uint8_t mobs, int wx, int wy) {
    StatsReading r;
    r.hp = hp; r.mana = mana; r.xp = xp; r.state = state; r.x = x; r.y = y; r.mobs = mobs; r.wx = wx; r.wy = wy;
    return liveStatsUpdate(r);
}

LiveStats liveStatsSnapshot() {
    LiveStats s;
    uint32_t now = millis();
    portENTER_CRITICAL(&mux_);
    if (any_) {
        s.hp = hp_; s.mana = mana_; s.xp = xp_;
        s.state = state_; s.x = x_; s.y = y_; s.mobs = mobs_; s.wx = wx_; s.wy = wy_;
        s.ml = ml_; s.mr = mr_; s.dl = dl_; s.dr = dr_;
        memcpy(s.mob, mob_, LIVE_NAME_LEN); memcpy(s.map, map_, LIVE_NAME_LEN);
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

void patternViewSet(const PatternView& v) {
    portENTER_CRITICAL(&mux_);
    view_ = v;
    portEXIT_CRITICAL(&mux_);
}

PatternView patternViewSnapshot() {
    portENTER_CRITICAL(&mux_);
    PatternView v = view_;
    portEXIT_CRITICAL(&mux_);
    return v;
}
