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
// Smart mode, before each attack: attack, wait, or walk (home or to mobs).
// Home is your position when the pattern started (or you reached a new map);
// you may drift `range` either way (same units as the position: tenths of a
// minimap width; 0 = no home). Out of range with no mobs in reach, or twice
// out of range whatever's around, it walks back, and once walking keeps on
// until within half the range. Then: auto-pause (`paused`, see AutoPause)
// waits; mobs in reach are attacked; with `approach`, mobs you can see but
// not reach are walked to (the nearer side), but not past 3/4 of the home
// range. No fresh reading or no mob detector: just attack.
enum SmartAction : uint8_t { SMART_ATTACK, SMART_WAIT, SMART_WALK_LEFT, SMART_WALK_RIGHT, SMART_PAUSE, SMART_APPROACH_LEFT, SMART_APPROACH_RIGHT };
struct SmartInput {
    bool fresh = false;
    uint8_t mobs = 0;              // in reach: MOB_LEFT | MOB_RIGHT | MOB_READ ...
    int seenLeft = -1, seenRight = -1;   // mobs you can see each side (-1: not read)
    int nearLeft = -1, nearRight = -1;   // the nearest each side, % of reach (-1: none)
    bool havePos = false, haveHome = false, homing = false, approach = false, paused = false;
    int pos = 0, home = 0;
    uint16_t range = 0;
};
inline uint8_t smartDecide(const SmartInput& in) {
    if (!in.fresh) return SMART_ATTACK;
    bool any = in.mobs & (MOB_LEFT | MOB_RIGHT), homed = in.havePos && in.haveHome && in.range;
    int off = homed ? in.pos - in.home : 0;
    if (homed) {
        int dist = off < 0 ? -off : off;
        if (dist > (in.homing ? in.range / 2 : in.range) && (!any || dist > 2 * in.range)) return off > 0 ? SMART_WALK_LEFT : SMART_WALK_RIGHT;
    }
    if (in.paused) return SMART_PAUSE;
    if (any) return SMART_ATTACK;
    bool left = in.seenLeft > 0, right = in.seenRight > 0;
    if (in.approach && (left || right)) {
        bool goLeft = left && (!right || (in.nearLeft >= 0 && (in.nearRight < 0 || in.nearLeft <= in.nearRight)));
        int limit = in.range * 3 / 4;
        if (!homed || (goLeft ? off > -limit : off < limit)) return goLeft ? SMART_APPROACH_LEFT : SMART_APPROACH_RIGHT;
    }
    return (in.mobs & MOB_READ) ? SMART_WAIT : SMART_ATTACK;
}
// The decision with mobs in reach only (no counts, approach or auto-pause).
inline uint8_t smartAction(bool fresh, uint8_t mobs, bool havePos, int pos, bool haveHome, int home, uint16_t range, bool homing) {
    SmartInput in;
    in.fresh = fresh; in.mobs = mobs; in.havePos = havePos; in.pos = pos; in.haveHome = haveHome; in.home = home; in.range = range; in.homing = homing;
    return smartDecide(in);
}

// Auto-pause: with most of the mobs you could see killed, wait for them to
// respawn rather than chase the last few. The most seen lately is the bar
// (it drops by one every MOB_PEAK_DECAY_MS it isn't reached, so one crowded
// moment doesn't hold it up for good). Fewer than `share` of it (permille)
// pauses; back to twice that share resumes. A pause lasts at most
// AUTO_PAUSE_MAX_MS: then the stragglers are fair game until the mobs are back.
const uint32_t MOB_PEAK_DECAY_MS = 30000;
const uint32_t AUTO_PAUSE_MAX_MS = 20000;
struct AutoPause {
    int peak = 0;
    uint32_t peakAt = 0, since = 0;
    bool paused = false, spent = false;
    // `seen`: mobs you can see now (-1: not read). True = hold off attacking.
    bool update(int seen, uint16_t share, uint32_t now) {
        if (seen < 0 || !share) { paused = spent = false; return false; }
        if (seen >= peak) { peak = seen; peakAt = now; }
        else if (now - peakAt >= MOB_PEAK_DECAY_MS) { --peak; peakAt = now; }
        uint32_t resume = share * 2 > 1000 ? 1000 : share * 2;
        if ((uint32_t)seen * 1000 >= (uint32_t)peak * resume) { paused = spent = false; return false; }
        if (paused && now - since >= AUTO_PAUSE_MAX_MS) { paused = false; spent = true; }
        if (!paused && !spent && seen > 0 && (uint32_t)seen * 1000 < (uint32_t)peak * share) { paused = true; since = now; }
        return paused;
    }
};

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

// ---- the screen reader's keys, pressed on the pad ---------------------------
// "tool" steps press tools/screen_stats.py's keys from the pad: mark (its F8),
// skip (Esc), map (F9), outlines (F10) and hide (F11), so setup and the game
// layer need no keyboard and work whatever has focus. They wait here until the
// script asks (USB "KABUTO keys", Wi-Fi POST /api/tool/keys); ones older than
// TOOL_KEY_MAX_AGE_MS are dropped, so presses with no script running don't
// fire later.
enum ToolKey : uint8_t { TOOL_NONE, TOOL_MARK, TOOL_SKIP, TOOL_MAP, TOOL_OUTLINES, TOOL_HIDE };
const uint32_t TOOL_KEY_MAX_AGE_MS = 3000;
inline const char* toolKeyName(uint8_t key) {
    static const char* const names[] = {"", "mark", "skip", "map", "outlines", "hide"};
    return key <= TOOL_HIDE ? names[key] : "";
}
inline uint8_t toolKeyFromName(const char* name) {
    for (uint8_t k = TOOL_MARK; name && k <= TOOL_HIDE; ++k)
        if (!strcmp(name, toolKeyName(k))) return k;
    return TOOL_NONE;
}
struct ToolKeys {
    static const uint8_t CAP = 8;
    uint8_t keys[CAP] = {};
    uint32_t at[CAP] = {};
    uint8_t count = 0;
    void push(uint8_t key, uint32_t now) {
        if (count == CAP) { memmove(keys, keys + 1, CAP - 1); memmove(at, at + 1, (CAP - 1) * sizeof(uint32_t)); --count; }   // the oldest goes
        keys[count] = key; at[count++] = now;
    }
    // The fresh keys, oldest first, comma separated into `out` ("" for none);
    // the queue is emptied.
    void take(uint32_t now, char* out, size_t size) {
        size_t n = 0;
        out[0] = 0;
        for (uint8_t i = 0; i < count; ++i) {
            if (now - at[i] > TOOL_KEY_MAX_AGE_MS) continue;
            const char* name = toolKeyName(keys[i]);
            size_t len = strlen(name);
            if (n + len + 2 > size) break;
            if (n) out[n++] = ',';
            memcpy(out + n, name, len); n += len; out[n] = 0;
        }
        count = 0;
    }
};

// ---- readings from tools/screen_stats.py -----------------------------------
// The same form ("hp=72.5&mana=40&xp=63.2&x=41.5&y=70&wx=1415&wy=700&state=ok&mobs=L
// &ml=1&mr=3&dl=192&dr=52&mn=Slime&map=Henesys") comes over Wi-Fi (POST
// /api/stats) or the USB cable ("KABUTO stats <form>"). ml/mr: mobs seen each
// side; dl/dr: the nearest each side in % of your reach; mn: its name; map:
// the map's name ("-" for one the script wasn't taught).

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
// A count or distance: a whole number 0-9999, else -1 (not read).
inline int statsCount(const char* text) {
    if (!text || !*text) return -1;
    char* end;
    long v = strtol(text, &end, 10);
    if (end == text || *end || v < 0 || v > 9999) return -1;
    return (int)v;
}
// A map or mob name: letters, digits, - and _ kept (others dropped), at most
// LIVE_NAME_LEN - 1 characters.
const size_t LIVE_NAME_LEN = 24;
inline void statsName(const char* text, char* out) {
    size_t n = 0;
    for (; text && *text && n < LIVE_NAME_LEN - 1; ++text) {
        char c = *text;
        if ((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '-' || c == '_') out[n++] = c;
    }
    out[n] = 0;
}
inline uint8_t statsMobs(const char* text) {
    if (!text) return 0;   // no "mobs" in the reading: no detector
    uint8_t sides = (strchr(text, 'L') ? MOB_LEFT : 0) | (strchr(text, 'R') ? MOB_RIGHT : 0);
    return MOB_READ | (sides == (MOB_LEFT | MOB_RIGHT) && text[0] == 'R' ? sides | MOB_RIGHT_NEARER : sides);
}

struct StatsReading {
    int hp = -1, mana = -1, xp = -1, x = -1, y = -1, wx = LIVE_NO_POS, wy = LIVE_NO_POS;
    uint8_t state = LIVE_OK, mobs = 0;   // no "mobs" field: 0, no detector
    int ml = -1, mr = -1, dl = -1, dr = -1;
    char map[LIVE_NAME_LEN] = {}, mob[LIVE_NAME_LEN] = {};   // "": not sent
};

// One field of a reading; unknown keys are ignored.
inline void statsField(StatsReading& r, const char* key, const char* value) {
    if (!strcmp(key, "hp")) r.hp = statsTenths(value);
    else if (!strcmp(key, "mana")) r.mana = statsTenths(value);
    else if (!strcmp(key, "xp")) r.xp = statsTenths(value);
    else if (!strcmp(key, "x")) r.x = statsTenths(value);
    else if (!strcmp(key, "y")) r.y = statsTenths(value);
    else if (!strcmp(key, "wx")) r.wx = statsPos(value);
    else if (!strcmp(key, "wy")) r.wy = statsPos(value);
    else if (!strcmp(key, "state")) r.state = statsState(value);
    else if (!strcmp(key, "mobs")) r.mobs = statsMobs(value);
    else if (!strcmp(key, "ml")) r.ml = statsCount(value);
    else if (!strcmp(key, "mr")) r.mr = statsCount(value);
    else if (!strcmp(key, "dl")) r.dl = statsCount(value);
    else if (!strcmp(key, "dr")) r.dr = statsCount(value);
    else if (!strcmp(key, "mn")) statsName(value, r.mob);
    else if (!strcmp(key, "map")) statsName(value, r.map);
}

// Parses the form without allocating. Values the script sends never need
// escaping (numbers, ok/dead/offline, L/R, names of letters, digits, - and _).
inline StatsReading parseStatsForm(const char* form) {
    StatsReading r;
    while (form && *form) {
        const char* amp = strchr(form, '&');
        size_t len = amp ? (size_t)(amp - form) : strlen(form);
        const char* eq = (const char*)memchr(form, '=', len);
        if (eq) {
            char key[8] = {}, value[32] = {};
            size_t kl = (size_t)(eq - form), vl = len - kl - 1;
            if (kl < sizeof(key) && vl < sizeof(value)) {
                memcpy(key, form, kl); memcpy(value, eq + 1, vl);
                statsField(r, key, value);
            }
        }
        form = amp ? amp + 1 : nullptr;
    }
    return r;
}
