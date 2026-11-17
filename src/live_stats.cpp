#include "live_stats.h"

namespace {
portMUX_TYPE mux_ = portMUX_INITIALIZER_UNLOCKED;   // a few ints: a spinlock is plenty
int hp_ = -1, mana_ = -1, xp_ = -1, x_ = -1, y_ = -1, wx_ = LIVE_NO_POS, wy_ = LIVE_NO_POS;
uint8_t state_ = LIVE_OK, mobs_ = 0;
int ml_ = -1, mr_ = -1, dl_ = -1, dr_ = -1, ir_ = -1;
char mob_[LIVE_NAME_LEN] = {}, map_[LIVE_NAME_LEN] = {};
PatternView view_;
ToolKeys toolKeys_;
PinnedHome pins_[MAX_PINNED_HOMES];
uint32_t pinsVersion_ = 0, pinStamp_ = 0;
bool pinsDirty_ = false;
// A map name as a key: "-" (a name it couldn't read) and "" are the same.
void mapKey(const char* map, char* out) { memset(out, 0, LIVE_NAME_LEN); if (map && strcmp(map, "-")) strncpy(out, map, LIVE_NAME_LEN - 1); }
int pinIndex(const char* key) { for (int i = 0; i < MAX_PINNED_HOMES; ++i) if (pins_[i].set && !strcmp(pins_[i].map, key)) return i; return -1; }
uint32_t at_ = 0;
bool any_ = false;
XpTracker xpTracker_;
Notices notices_;
}

bool liveStatsUpdate(const StatsReading& r) {
    uint32_t now = millis();
    portENTER_CRITICAL(&mux_);
    bool wasOk = state_ == LIVE_OK || !any_ || now - at_ >= LIVE_STATS_STALE_MS;
    notices_.note(r.state, wasOk ? (uint8_t)LIVE_OK : state_, now);
    hp_ = r.hp; mana_ = r.mana; xp_ = r.xp; state_ = r.state; x_ = r.x; y_ = r.y; mobs_ = r.mobs; wx_ = r.wx; wy_ = r.wy;
    ml_ = r.ml; mr_ = r.mr; dl_ = r.dl; dr_ = r.dr; ir_ = r.ir;
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
        s.ml = ml_; s.mr = mr_; s.dl = dl_; s.dr = dr_; s.ir = ir_;
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

Notices noticesSnapshot() {
    portENTER_CRITICAL(&mux_);
    Notices n = notices_;
    portEXIT_CRITICAL(&mux_);
    return n;
}

void noticesClear() {
    portENTER_CRITICAL(&mux_);
    notices_.clear();
    portEXIT_CRITICAL(&mux_);
}

void patternViewSet(const PatternView& v) {
    portENTER_CRITICAL(&mux_);
    view_ = v;
    portEXIT_CRITICAL(&mux_);
}

bool homePin() {
    LiveStats live = liveStatsSnapshot();
    bool onMap = live.wx != LIVE_NO_POS;
    if (!live.fresh || (!onMap && live.x < 0)) return false;
    char key[LIVE_NAME_LEN]; mapKey(live.map, key);
    portENTER_CRITICAL(&mux_);
    int at = pinIndex(key);
    if (at < 0) {   // a free place, else the one pinned longest ago
        at = 0;
        for (int i = 0; i < MAX_PINNED_HOMES; ++i) {
            if (!pins_[i].set) { at = i; break; }
            if (pins_[i].stamp < pins_[at].stamp) at = i;
        }
    }
    PinnedHome& p = pins_[at];
    p.set = true; p.home = onMap ? live.wx : live.x; p.onMap = onMap; memcpy(p.map, key, LIVE_NAME_LEN); p.stamp = ++pinStamp_;
    ++pinsVersion_; pinsDirty_ = true;
    portEXIT_CRITICAL(&mux_);
    return true;
}

bool homeUnpin() {
    LiveStats live = liveStatsSnapshot();
    char key[LIVE_NAME_LEN]; mapKey(live.map, key);
    portENTER_CRITICAL(&mux_);
    int at = pinIndex(key);
    if (at >= 0) { pins_[at] = PinnedHome(); ++pinsVersion_; pinsDirty_ = true; }
    portEXIT_CRITICAL(&mux_);
    return at >= 0;
}

PinnedHome homePinned(const char* map) {
    char key[LIVE_NAME_LEN]; mapKey(map, key);
    portENTER_CRITICAL(&mux_);
    int at = pinIndex(key);
    PinnedHome p = at >= 0 ? pins_[at] : PinnedHome();
    portEXIT_CRITICAL(&mux_);
    return p;
}

PinnedHome homePinnedHere() { return homePinned(liveStatsSnapshot().map); }

uint32_t homePinsVersion() {
    portENTER_CRITICAL(&mux_);
    uint32_t v = pinsVersion_;
    portEXIT_CRITICAL(&mux_);
    return v;
}

uint8_t homePinsCopy(PinnedHome* out, uint8_t cap) {
    uint8_t n = 0;
    portENTER_CRITICAL(&mux_);
    for (int i = 0; i < MAX_PINNED_HOMES && n < cap; ++i) if (pins_[i].set) out[n++] = pins_[i];
    portEXIT_CRITICAL(&mux_);
    return n;
}

void homePinsLoad(const PinnedHome* in, uint8_t count) {
    portENTER_CRITICAL(&mux_);
    for (int i = 0; i < MAX_PINNED_HOMES; ++i) pins_[i] = PinnedHome();
    for (uint8_t i = 0; i < count && i < MAX_PINNED_HOMES; ++i) {
        pins_[i] = in[i]; pins_[i].set = true; pins_[i].map[LIVE_NAME_LEN - 1] = 0;
        if (pins_[i].stamp > pinStamp_) pinStamp_ = pins_[i].stamp;
    }
    ++pinsVersion_;
    portEXIT_CRITICAL(&mux_);
}

bool homePinsTakeDirty() {
    portENTER_CRITICAL(&mux_);
    bool d = pinsDirty_; pinsDirty_ = false;
    portEXIT_CRITICAL(&mux_);
    return d;
}

void toolKeyPush(uint8_t key) {
    portENTER_CRITICAL(&mux_);
    toolKeys_.push(key, millis());
    portEXIT_CRITICAL(&mux_);
}

void toolKeysTake(char* out, size_t size) {
    portENTER_CRITICAL(&mux_);
    toolKeys_.take(millis(), out, size);
    portEXIT_CRITICAL(&mux_);
}

PatternView patternViewSnapshot() {
    portENTER_CRITICAL(&mux_);
    PatternView v = view_;
    portEXIT_CRITICAL(&mux_);
    return v;
}

void homeReply(char* out, size_t size) {
    PatternView v = patternViewSnapshot();
    if (v.active && v.haveHome) { homeReplyForm(out, size, true, true, v.home, v.homeOnMap, v.homeRange); return; }
    // Nothing playing (or a pattern with no zone): this map's Set home all the same, so the
    // PC's game layer shows where home is from the moment it's set, not only while playing.
    PinnedHome pin = homePinnedHere();
    homeReplyForm(out, size, pin.set, pin.set, pin.home, pin.onMap, 0);
}
