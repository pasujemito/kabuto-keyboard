#pragma once
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <cstdio>

// Live HP/Mana/XP, read off the game screen by tools/screen_stats.py as bar
// fill percentages (pure, host-tested). Kept in tenths of a percent (0-1000).

const uint32_t LIVE_STATS_STALE_MS = 5000;   // older readings fall back to potion timers
const uint32_t LIVE_POTION_GAP_MS = 3000;    // let a potion land before drinking again
const uint32_t XP_RATE_MIN_MS = 60000;       // a minute of readings before showing a rate

// XP gained from the XP bar. A rise of up to XP_STEP_MAX at once counts
// straight away. Anything else (a drop, a bigger rise) only counts once the
// bar has stayed there (within XP_HOLD_SLACK) for XP_HOLD_MS: changing maps
// fades the screen, and a bar misread low then read right again must not
// look like a level-up followed by a huge gain. Once it holds: a drop of
// over half the bar is a level-up (counted in `levels`; the rate starts
// afresh for the new level, whose % are of a bigger level), a drop of up to
// XP_DROP_MAX (the death penalty) is just where the bar is now, a bigger rise
// (a quest) is gained. A drop in between can't happen in the game: only if it
// stays XP_RESET_MS (another character?) does the rate start afresh there.
const int XP_STEP_MAX = 100;          // tenths: 10% of a level in one reading
const int XP_DROP_MAX = 150;          // tenths: 15%
const uint32_t XP_HOLD_MS = 10000;
const uint32_t XP_RESET_MS = 60000;
const int XP_HOLD_SLACK = 20;         // tenths: 2%
struct XpTracker {
    uint32_t startMs = 0, lastMs = 0, levels = 0;
    uint64_t gained = 0;   // tenths of a percent of a level
    int lastXp = -1;
    int heldXp = -1;       // a change waiting to hold (-1: none)
    uint32_t heldMs = 0;

    void add(int xp, uint32_t nowMs) {
        if (xp < 0 || xp > 1000) return;
        if (lastXp < 0) { lastXp = xp; startMs = lastMs = nowMs; return; }
        lastMs = nowMs;
        int delta = xp - lastXp;
        if (delta >= 0 && delta <= XP_STEP_MAX) { gained += (uint64_t)delta; lastXp = xp; heldXp = -1; return; }
        if (heldXp < 0 || xp - heldXp > XP_HOLD_SLACK || heldXp - xp > XP_HOLD_SLACK) { heldXp = xp; heldMs = nowMs; return; }
        if (nowMs - heldMs < XP_HOLD_MS) return;
        int to = heldXp, drop = lastXp - to;   // it held: the bar went there, and has moved on to xp since
        if (drop > XP_DROP_MAX && drop <= 500 && nowMs - heldMs < XP_RESET_MS) return;   // can't be: wait
        heldXp = -1;
        if (drop > XP_DROP_MAX) { levels += drop > 500; gained = 0; startMs = nowMs; }   // level up (or a reset): afresh
        else if (to > lastXp) gained += (uint64_t)(to - lastXp);
        lastXp = to;
        if (xp > lastXp) { gained += (uint64_t)(xp - lastXp); lastXp = xp; }
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
// TEST: the game's test popup is on screen (a quiz only you can answer).
enum LiveState : uint8_t { LIVE_OK = 0, LIVE_DEAD = 1, LIVE_OFFLINE = 2, LIVE_TEST = 3 };
inline const char* liveStopReason(uint8_t state) {
    switch (state) {
        case LIVE_DEAD: return "you died";
        case LIVE_OFFLINE: return "the game is disconnected or at the login screen";
        case LIVE_TEST: return "a test popup is on screen: answer it in the game";
        default: return nullptr;
    }
}
// The state as the screen reader spells it ("ok", "dead", "offline", "test").
inline const char* liveStateName(uint8_t state) {
    static const char* const names[] = {"ok", "dead", "offline", "test"};
    return state <= LIVE_TEST ? names[state] : "ok";
}

// ---- notifications ------------------------------------------------------------
// What the pad's page lists under Notifications: each time the game turns to
// a stop state it wasn't in (a test popup, death, a disconnect), with when.
// The newest CAP are kept (the oldest goes); ids count up from 1 and survive
// clear(), so the page can tell a new one (buzz the phone) from one it showed.
struct Notices {
    static const uint8_t CAP = 8;
    uint8_t kind[CAP] = {};     // LiveState
    uint32_t at[CAP] = {};
    uint8_t count = 0;
    uint32_t last = 0;          // the newest one's id (0: none yet)
    // A reading's state, after `before` (LIVE_OK when there was no fresh one).
    // True when it was noted.
    bool note(uint8_t state, uint8_t before, uint32_t now) {
        if (state == LIVE_OK || state == before || !liveStopReason(state)) return false;
        if (count == CAP) { memmove(kind, kind + 1, CAP - 1); memmove(at, at + 1, (CAP - 1) * sizeof(uint32_t)); --count; }
        kind[count] = state; at[count++] = now; ++last;
        return true;
    }
    uint32_t id(uint8_t i) const { return last - (count - 1 - i); }   // i: 0 = the oldest kept
    void clear() { count = 0; }
};

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
// range. Then, with a home and the mob detector, nothing to fight nearby
// means back home: walk until within HOME_SETTLE / 2 of it whenever farther
// than HOME_SETTLE, so you hunt around home rather than wherever the last
// mob led you (auto-pause waits there too). No fresh reading, or no mob
// detector on this map: Smart can't tell where mobs are, so it stands still
// (SMART_NO_READINGS / SMART_NO_DETECTOR) rather than attack blindly.
const int HOME_SETTLE = 60;   // tenths of a minimap width: "at home" within this (3% once walking)
const uint32_t MAP_CHANGE_MS = 3000;   // another map's name must hold this long before home moves there
const uint32_t HOME_RETRY_MS = 20000;  // couldn't walk home in 10 s: home is kept, walking back tried again after this
enum SmartAction : uint8_t { SMART_ATTACK, SMART_WAIT, SMART_WALK_LEFT, SMART_WALK_RIGHT, SMART_PAUSE, SMART_APPROACH_LEFT, SMART_APPROACH_RIGHT,
                             SMART_NO_READINGS, SMART_NO_DETECTOR, SMART_SUPPORT };
const uint32_t SUPPORT_CHECK_MS = 1000;   // support only (attack off): potions and skills are looked at this often
struct SmartInput {
    bool fresh = false;
    uint8_t mobs = 0;              // in reach: MOB_LEFT | MOB_RIGHT | MOB_READ ...
    int seenLeft = -1, seenRight = -1;   // mobs you can see each side (-1: not read)
    int nearLeft = -1, nearRight = -1;   // the nearest each side, % of reach (-1: none)
    bool havePos = false, haveHome = false, homing = false, approach = false, paused = false;
    int pos = 0, home = 0;
    uint16_t range = 0;
};
// Home on its own (any pattern with a home range, Smart or not): drifted past
// the range with no mobs in reach, or twice the range whatever's around, walk
// back until within half of it; otherwise attack.
inline uint8_t homeDecide(const SmartInput& in) {
    if (!in.fresh || !in.havePos || !in.haveHome || !in.range) return SMART_ATTACK;
    bool any = in.mobs & (MOB_LEFT | MOB_RIGHT);
    int off = in.pos - in.home, dist = off < 0 ? -off : off;
    if (dist > (in.homing ? in.range / 2 : in.range) && (!any || dist > 2 * in.range)) return off > 0 ? SMART_WALK_LEFT : SMART_WALK_RIGHT;
    return SMART_ATTACK;
}
inline uint8_t smartDecide(const SmartInput& in) {
    if (!in.fresh) return SMART_NO_READINGS;
    bool any = in.mobs & (MOB_LEFT | MOB_RIGHT), homed = in.havePos && in.haveHome && in.range;
    int off = homed ? in.pos - in.home : 0;
    uint8_t back = homeDecide(in);
    if (back != SMART_ATTACK) return back;
    bool away = homed && (in.mobs & MOB_READ) && (off < 0 ? -off : off) > (in.homing ? HOME_SETTLE / 2 : HOME_SETTLE);
    if (in.paused) return away ? (off > 0 ? SMART_WALK_LEFT : SMART_WALK_RIGHT) : SMART_PAUSE;
    if (any) return SMART_ATTACK;
    bool left = in.seenLeft > 0, right = in.seenRight > 0;
    if (in.approach && (left || right)) {
        bool goLeft = left && (!right || (in.nearLeft >= 0 && (in.nearRight < 0 || in.nearLeft <= in.nearRight)));
        int limit = in.range * 3 / 4;
        if (!homed || (goLeft ? off > -limit : off < limit)) return goLeft ? SMART_APPROACH_LEFT : SMART_APPROACH_RIGHT;
    }
    if (away) return off > 0 ? SMART_WALK_LEFT : SMART_WALK_RIGHT;   // nothing to fight here: back home
    return (in.mobs & MOB_READ) ? SMART_WAIT : SMART_NO_DETECTOR;
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

// ---- backup potion keys ---------------------------------------------------------
// A potion with backup keys (more of the same kind) watches its bar: a drink is
// checked POTION_CHECK_MS later, and POTION_MISSES drinks in a row that didn't
// raise the bar by POTION_RISE (tenths of a %) mean that key ran out: the next
// key is used, round to the first again after the last. Without fresh readings
// nothing is judged.
const uint32_t POTION_CHECK_MS = 2000;
const int POTION_RISE = 5;
const uint8_t POTION_MISSES = 2;
struct PotionKeys {
    uint8_t active = 0, count = 1, misses = 0;   // the key in use (0 = the main one) of `count`
    bool armed = false; int before = 0; uint32_t at = 0;
    void drank(bool fresh, int value, uint32_t now) {
        if (count < 2 || !fresh || value < 0) return;
        armed = true; before = value; at = now + POTION_CHECK_MS;
    }
    // True when it moved on to the next key.
    bool check(bool fresh, int value, uint32_t now) {
        if (!armed || (int32_t)(now - at) < 0) return false;
        armed = false;
        if (!fresh || value < 0) return false;
        if (value >= before + POTION_RISE) { misses = 0; return false; }
        if (++misses < POTION_MISSES) return false;
        misses = 0; active = (uint8_t)((active + 1) % count);
        return true;
    }
};

// ---- home, told back to the screen reader ------------------------------------
// The answer to each reading carries the playing pattern's home, so the PC's
// game layer can mark it on the minimap: "home=1415&hm=1&hr=500" (home in the
// position's own units, hm=1 when it's a map position wx rather than the dot's
// x, hr the home range in tenths of a percent of the minimap, 0 = none). Empty
// with no pattern playing or no home yet.
inline void homeReplyForm(char* out, size_t size, bool active, bool haveHome, int home, bool onMap, uint16_t range) {
    if (!size) return;
    out[0] = 0;
    if (active && haveHome) snprintf(out, size, "home=%d&hm=%d&hr=%u", home, onMap ? 1 : 0, (unsigned)range);
}

// ---- the screen reader's keys, pressed on the pad ---------------------------
// "tool" steps press tools/screen_stats.py's keys from the pad: mark (its F8),
// skip (Esc), map (F9), outlines (F10), hide (F11), looser (F6) and stricter
// (F7) mob colours, home (1.18.6's F12, no longer used: kept so saved buttons load), area (F12:
// mark this map's minimap and name by hand, over the automatic ones), so setup, tuning and the game layer need no keyboard and
// work whatever has focus. They wait here until the
// script asks (USB "KABUTO keys", Wi-Fi POST /api/tool/keys); ones older than
// TOOL_KEY_MAX_AGE_MS are dropped, so presses with no script running don't
// fire later.
enum ToolKey : uint8_t { TOOL_NONE, TOOL_MARK, TOOL_SKIP, TOOL_MAP, TOOL_OUTLINES, TOOL_HIDE, TOOL_LOOSER, TOOL_STRICTER, TOOL_HOME, TOOL_AREA };
const uint32_t TOOL_KEY_MAX_AGE_MS = 3000;
inline const char* toolKeyName(uint8_t key) {
    static const char* const names[] = {"", "mark", "skip", "map", "outlines", "hide", "looser", "stricter", "home", "area"};
    return key <= TOOL_AREA ? names[key] : "";
}
inline uint8_t toolKeyFromName(const char* name) {
    for (uint8_t k = TOOL_MARK; name && k <= TOOL_AREA; ++k)
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
// the map's name ("-" for one the script wasn't taught). state: ok, dead,
// offline or test (the game's test popup).

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
    if (!strcmp(text, "test")) return LIVE_TEST;
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
