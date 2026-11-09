// Scenario tests: the real dynamic-pattern engine playing in a small simulated
// game world, with the pattern the editor makes by default (fixtures/
// default_pattern.json, loaded through the pad's own config loader) plus the
// settings each scenario changes.
//
// The world: a map of platforms (walking off one, or landing past its end, is
// a fall), jumps that keep their take-off speed through the air for 600 ms,
// mobs that wander, take hits, die and respawn, and a screen reader that sends
// what tools/screen_stats.py sends, 40 ms late, the position only every 0.5%.
//
// Every scenario checks the same rules (see check()); each adds its own
// expectations. The report says, in plain words, what each one expects and
// what happened. When a change makes one fail, say what the new behaviour is
// and why, before changing the expectation.
#include <Arduino.h>
#include <LittleFS.h>
#include <ArduinoJson.h>
#define private public
#include "../src/macro_engine.h"
#undef private
#include "../src/hid_keyboard.h"
#include "../src/live_stats.h"
#include "../src/storage.h"
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstdarg>
#include <fstream>
#include <iterator>
#include <algorithm>

uint32_t testClock = 0;
std::function<void()> testDelayHook;
std::function<long(long)> testRandomHook;
HidKeyboard Keyboard;
TestLittleFS LittleFS;
struct HidEvent { uint32_t at; uint8_t key; uint8_t mods; bool down; };
std::vector<HidEvent> hidEvents;
std::vector<uint8_t> held;
uint8_t heldMods = 0;
void HidKeyboard::tap(uint8_t key, uint8_t mods, uint16_t) { hidEvents.push_back({millis(), key, (uint8_t)(heldMods | mods), true}); hidEvents.push_back({millis(), key, heldMods, false}); }
void HidKeyboard::pressKey(uint8_t key, uint8_t mods) { heldMods |= mods; if (key) held.push_back(key); hidEvents.push_back({millis(), key, heldMods, true}); }
void HidKeyboard::releaseKey(uint8_t key) { held.erase(std::remove(held.begin(), held.end(), key), held.end()); hidEvents.push_back({millis(), key, heldMods, false}); }
void HidKeyboard::releaseModifiers(uint8_t mods) { heldMods &= ~mods; hidEvents.push_back({millis(), 0, heldMods, false}); }
void HidKeyboard::releaseAll() { releaseModifiers(255); held.clear(); }
void HidKeyboard::typeString(const String&) {}
void HidKeyboard::consumerPress(uint16_t) {}
void HidKeyboard::consumerRelease() {}

const uint8_t KEY_LEFT = 80, KEY_RIGHT = 79, MOD_CTRL = 1, MOD_ALT = 4;

std::string fmt(const char* f, ...) { char b[400]; va_list a; va_start(a, f); vsnprintf(b, sizeof(b), f, a); va_end(a); return b; }

// ---- the world ----------------------------------------------------------------
struct Platform { double x0, x1; int y; };   // y: height in px (0: the floor)
struct Mob { int platform; double x, vx = 0; int hp = 3; bool alive = true, still = false; uint32_t respawnAt = 0, wanderAt = 0; };
struct World {
    double width = 2000;              // map width in px
    std::vector<Platform> platforms{{0, 2000, 0}};
    std::vector<Mob> mobs;
    double speed = 0.125;             // px per ms: 125 px/s, 100% speed
    double reach = 150;               // attack reach, px in front
    double sight = 600;               // the screen, px either side
    bool knockback = false;           // mobs touching you push you 40 px away
    std::string map = "Scenario";
};

struct Run {   // what happened
    int attacks = 0, hits = 0, kills = 0, wasted = 0;   // wasted: no mob in reach when attacking
    bool fell = false;
    double furthestPast = -1e9;       // px past the home zone's line (negative: inside)
    double minX = 1e9, maxX = -1e9;
    uint32_t longestIdleWithMob = 0;  // ms in a row with a mob in reach and no attack
    uint32_t idleFrom = 0, idleTo = 0;
    std::vector<std::pair<uint32_t,std::string>> timed;
    uint32_t endedAt = 0, startedAt = 0;
    bool keysLeft = false, walkedHome = false;
    int attacksOutside = 0; uint32_t outsideSince = 0, longestOutside = 0;
    std::vector<std::string> log;
};

struct Sim {
    World w;
    int platform = 0; double x = 0, vx = 0; bool air = false; uint32_t landAt = 0;
    bool left = false, right = false; int facing = 1; uint8_t mods = 0;
    uint32_t last = 0, nextFrame = 0, lastTouch = 0, idleSince = 0, nextTrace = 0; size_t seen = 0;
    int sentX = -9999; std::vector<std::pair<uint32_t, StatsReading>> pipe;
    uint8_t state = LIVE_OK;
    double homeX = 0, rangePx = 0; bool zone = false, hitOut = false;
    Run run;

    bool sameLevel(int a, int b) const { return w.platforms[a].y == w.platforms[b].y; }
    bool inReach(const Mob& m) const { return m.alive && sameLevel(m.platform, platform) && std::fabs(m.x - x) <= w.reach; }
    bool mobInReach() const { for (auto& m : w.mobs) if (inReach(m)) return true; return false; }
    // One it should be attacking: in reach and, with a home zone, inside it (the pad's rule:
    // the zone first; at its edge, mobs outside are left alone).
    // In the zone's safety band (about 0.4 s of walking from the line) it faces inwards and
    // only mobs on the inside count, as the pad does.
    bool targetInReach() const {
        double band = std::min(rangePx / 2, w.speed * 400 * 1.5), off = x - homeX;   // the pad measures the speed: allow it 50% over
        bool inBand = zone && std::fabs(off) > rangePx - band;
        for (auto& m : w.mobs) {
            if (!inReach(m) || (zone && std::fabs(m.x - homeX) > rangePx)) continue;
            if (inBand && (m.x - x) * off > 0) continue;   // on the outer side, from the band
            return true;
        }
        return false;
    }
    void land() {   // where you come down: this platform if you're over it, else the one below
        const Platform& p = w.platforms[platform];
        if (x >= p.x0 && x <= p.x1) return;
        run.fell = true;
        int best = -1;
        for (size_t i = 0; i < w.platforms.size(); ++i) {
            const Platform& q = w.platforms[i];
            if (q.y < p.y && x >= q.x0 && x <= q.x1 && (best < 0 || q.y > w.platforms[best].y)) best = (int)i;
        }
        if (best >= 0) platform = best;
    }
    void step(uint32_t to) {
        while (last < to) {
            uint32_t d = std::min<uint32_t>(to - last, 5); last += d;
            if (air && last >= landAt) { air = false; land(); }
            if (!air) vx = ((right ? 1 : 0) - (left ? 1 : 0)) * w.speed;
            x = std::max(0.0, std::min(w.width, x + vx * d));
            if (!air) land();   // walked off the end
            for (auto& m : w.mobs) {
                if (!m.alive) { if (last >= m.respawnAt) { const Platform& p = w.platforms[m.platform]; m.alive = true; m.hp = 3; m.x = p.x0 + 20 + std::rand() % std::max(1, (int)(p.x1 - p.x0 - 40)); } continue; }
                if (!m.still && last >= m.wanderAt) { m.wanderAt = last + 2000 + std::rand() % 2000; m.vx = (std::rand() % 3 - 1) * 0.03; }
                const Platform& p = w.platforms[m.platform];
                m.x = std::max(p.x0 + 5, std::min(p.x1 - 5, m.x + m.vx * d));
                if (w.knockback && !air && sameLevel(m.platform, platform) && std::fabs(m.x - x) < 25 && last - lastTouch > 3000) {
                    lastTouch = last; x += (x < m.x ? -40 : 40); x = std::max(0.0, std::min(w.width, x)); land();
                }
            }
        }
    }
    void attack(uint32_t at) {
        ++run.attacks; idleSince = 0;
        if (zone && std::fabs(x - homeX) > rangePx) ++run.attacksOutside;
        if (!mobInReach() && !(zone && std::fabs(x - homeX) > rangePx)) {
            ++run.wasted;
            double near = 1e9; for (auto& m : w.mobs) if (m.alive && sameLevel(m.platform, platform) && std::fabs(m.x - x) < std::fabs(near)) near = m.x - x;
            run.timed.push_back({at, fmt("ATTACK WITH NO MOB IN REACH: x=%.0f face=%d air=%d L=%d R=%d nearest %+.0f px", x, facing, air, left, right, near)});
        }   // outside the zone it fights its way back on purpose
        int hit = 0;
        for (auto& m : w.mobs) {
            double dx = (m.x - x) * facing;
            if (hit < 3 && m.alive && sameLevel(m.platform, platform) && dx >= -20 && dx <= w.reach) {
                ++hit; if (--m.hp <= 0) { m.alive = false; m.respawnAt = at + 7000; ++run.kills; }
            }
        }
        run.hits += hit > 0;
    }
    void apply(const HidEvent& e) {
        step(e.at);
        if (e.key == KEY_LEFT) { left = e.down; if (e.down) facing = -1; }
        else if (e.key == KEY_RIGHT) { right = e.down; if (e.down) facing = 1; }
        if (air && e.down && (e.key == KEY_LEFT || e.key == KEY_RIGHT) && vx == 0) vx = (e.key == KEY_RIGHT ? 1 : -1) * w.speed * 0.3;   // a little air control
        uint8_t now = e.mods;
        if ((now & MOD_ALT) && !(mods & MOD_ALT) && !air) { air = true; landAt = e.at + 600; vx = ((right ? 1 : 0) - (left ? 1 : 0)) * w.speed; }
        if ((now & MOD_CTRL) && !(mods & MOD_CTRL)) attack(e.at);
        mods = now;
    }
    StatsReading read() const {   // what the screen reader sees now
        StatsReading r; r.hp = r.mana = 800; r.state = state; r.y = 500;
        int px = (int)std::lround(x / w.width * 1000); r.x = px;
        r.mobs = MOB_READ; r.ml = r.mr = 0; r.dl = r.dr = -1; r.ir = 0;
        for (auto& m : w.mobs) {
            if (!m.alive) continue;
            double dx = m.x - x; int dy = std::abs(w.platforms[m.platform].y - w.platforms[platform].y);
            if (std::fabs(dx) > w.sight || dy > 300) continue;
            int pct = (int)std::lround(std::fabs(dx) / w.reach * 100);
            if (dx < 0) { ++r.ml; if (r.dl < 0 || pct < r.dl) r.dl = pct; } else { ++r.mr; if (r.dr < 0 || pct < r.dr) r.dr = pct; }
            if (inReach(m)) { ++r.ir; r.mobs |= dx < 0 ? MOB_LEFT : MOB_RIGHT; }
        }
        if (r.dl >= 0 && r.dr >= 0 && r.dr < r.dl) r.mobs |= MOB_RIGHT_NEARER;
        statsName(w.map.c_str(), r.map);
        return r;
    }
    void tick() {
        uint32_t now = millis();
        for (; seen < hidEvents.size(); ++seen) apply(hidEvents[seen]);
        step(now);
        run.minX = std::min(run.minX, x); run.maxX = std::max(run.maxX, x);
        if (zone) run.furthestPast = std::max(run.furthestPast, std::fabs(x - homeX) - rangePx);
        if (zone && std::fabs(x - homeX) > rangePx) { if (!run.outsideSince) run.outsideSince = now; run.longestOutside = std::max(run.longestOutside, now - run.outsideSince); }
        else run.outsideSince = 0;
        if (targetInReach() && state == LIVE_OK) { if (!idleSince) idleSince = now; if (now - idleSince > run.longestIdleWithMob) { run.longestIdleWithMob = now - idleSince; run.idleFrom = idleSince; run.idleTo = now; } }
        else idleSince = 0;
        if (now >= nextTrace) {
            nextTrace = now + 1000;
            StatsReading r = read(); PatternView v = patternViewSnapshot();
            double near = 1e9; for (auto& m : w.mobs) if (m.alive && sameLevel(m.platform, platform) && std::fabs(m.x - x) < std::fabs(near)) near = m.x - x;
            run.timed.push_back({now, fmt("x=%.0f face=%d air=%d L=%d R=%d | read mobs=%d ir=%d ml=%d mr=%d dl=%d dr=%d | nearest mob %+.0f px | pad: action=%d home=%d", x, facing, air, left, right, r.mobs, r.ir, r.ml, r.mr, r.dl, r.dr, near, v.action, v.haveHome ? v.home : -1)});
        }
        if (now >= nextFrame) {
            nextFrame = now + 70;
            StatsReading r = read();
            if (sentX != -9999 && std::abs(r.x - sentX) < 5) r.x = sentX; else sentX = r.x;   // only 0.5% moves
            pipe.push_back({now + 40, r});
        }
        while (!pipe.empty() && pipe.front().first <= now) { liveStatsUpdate(pipe.front().second); pipe.erase(pipe.begin()); }
    }
};

// ---- the pattern: the editor's default, changed per scenario -----------------------
std::string defaultPatternJson;
DynamicPattern loadPattern(std::function<void(JsonObject)> change) {
    JsonDocument doc;
    assert(!deserializeJson(doc, defaultPatternJson));
    change(doc.as<JsonObject>());
    JsonDocument cfg;
    cfg["version"] = 2;
    JsonObject layer = cfg["layers"].to<JsonArray>().add<JsonObject>();
    layer["name"] = "Main";
    JsonObject w = cfg["workflows"].to<JsonArray>().add<JsonObject>();
    w["id"] = "scenario"; w["name"] = "Scenario"; w["kind"] = "nano"; w["recording"] = true;
    JsonObject step = w["steps"].to<JsonArray>().add<JsonObject>();
    step["type"] = "dynamic"; step["pattern"] = doc;
    std::string json; serializeJson(cfg, json);
    {File f = LittleFS.open(MACRO_TMP_FILE, "w"); f.write((const uint8_t*)json.c_str(), json.length());}
    String err; bool ok = commitConfigFile(MACRO_TMP_FILE, err);
    if (!ok) { std::printf("pattern rejected: %s\n", err.c_str()); assert(ok); }
    Config c; assert(loadConfig(c));
    return *c.workflows[0].steps[0].pattern();
}

// ---- running one ----------------------------------------------------------------------
MacroEngine engine;
struct Setup {
    World world;
    int startPlatform = 0; double startX = 1000;
    uint32_t maxMs = 120000;
    std::function<void(Sim&, uint32_t)> during;   // called every tick (ms since start)
};
Run play(const Setup& setup, const DynamicPattern& p, unsigned seed) {
    std::srand(seed);
    testRandomHook = [](long upper) { return upper > 0 ? (long)(std::rand() % upper) : 0L; };
    Sim sim; sim.w = setup.world; sim.platform = setup.startPlatform; sim.x = setup.startX;
    sim.last = millis(); sim.nextFrame = millis();
    for (auto& m : sim.w.mobs) m.wanderAt = millis();
    sim.zone = p.homeRangePermille > 0; sim.homeX = setup.startX; sim.rangePx = p.homeRangePermille / 1000.0 * sim.w.width;
    homePinsLoad(nullptr, 0); engine.keptHomes_.clear(); engine.driftSpeeds_.clear();
    liveStatsUpdate(sim.read()); sim.sentX = sim.read().x;
    hidEvents.clear(); held.clear(); heldMods = 0;
    uint32_t t0 = millis(), end = t0 + setup.maxMs; sim.run.startedAt = t0;
    testDelayHook = [&] {
        sim.tick();
        if (setup.during) setup.during(sim, millis() - t0);
        if (millis() >= end) engine.stopFlag_ = true;
    };
    Step s; s.type = StepType::DYNAMIC; s.setPattern(p);
    KeyBinding key; key.steps = {s};
    engine.oneShot_ = true; engine.stopFlag_ = false;
    engine.runMacro(key);
    testDelayHook = {}; testRandomHook = {};
    sim.run.endedAt = millis();
    sim.run.keysLeft = !held.empty() || heldMods;
    static MacroLogEntry entries[512]; size_t n = engine.copyLog(entries, 512);
    for (size_t i = 0; i < n; ++i) if (entries[i].text[0]) {
        sim.run.log.push_back(entries[i].text); sim.run.timed.push_back({t0 + entries[i].elapsedMs, entries[i].text});
        if (std::string(entries[i].text).find("back into the home zone") != std::string::npos) sim.run.walkedHome = true;
    }
    engine.clearLog();
    liveStatsUpdate(-1, -1, -1); testClock += LIVE_STATS_STALE_MS;   // no fresh readings left for the next one
    return sim.run;
}

struct Run;
extern Run lastRun;
// ---- the report ---------------------------------------------------------------------------
int failures = 0;
struct Expect { std::string text; bool ok; };
void report(const char* name, const char* expected, const std::vector<Expect>& checks, const std::string& measured) {
    bool ok = true; for (auto& c : checks) ok = ok && c.ok;
    std::printf("%s  %s\n      expects: %s\n      saw:     %s\n", ok ? "PASS" : "FAIL", name, expected, measured.c_str());
    for (auto& c : checks) if (!c.ok) std::printf("      ✗ %s\n", c.text.c_str());
    if (!ok) ++failures;
    const char* trace = getenv("SCENARIO_TRACE");
    if (trace && std::string(name).find(trace) != std::string::npos) for (auto& l : lastRun.log) std::printf("        pad: %s\n", l.c_str());
    if (trace && std::string(name).find(trace) != std::string::npos) for (auto& t : lastRun.timed) std::printf("        %6u %s\n", t.first - lastRun.startedAt, t.second.c_str());
}
bool debug = getenv("SCENARIO_DEBUG") != nullptr;
void dumpIdle(const Run& r) {
    if (!debug) return;
    std::printf("      longest idle %u–%u ms (run %u–%u):\n", r.idleFrom - r.startedAt, r.idleTo - r.startedAt, 0u, r.endedAt - r.startedAt);
    for (auto& t : r.timed) if (t.first + 3000 >= r.idleFrom && t.first <= r.idleTo + 1000) std::printf("        %6u %s\n", t.first - r.startedAt, t.second.c_str());
}

// The rules every scenario keeps, over several seeds; the worst of them is reported.
struct Many { std::vector<Run> runs; };
Run lastRun;

Many repeat(const Setup& s, const DynamicPattern& p, int seeds = 4) { Many m; for (int i = 1; i <= seeds; ++i) m.runs.push_back(play(s, p, 1000 + i * 7919)); lastRun = m.runs[0]; for (auto& r : m.runs) if (r.wasted > lastRun.wasted || r.maxX > lastRun.maxX) lastRun = r; return m; }
template <class F> double worst(const Many& m, F f) { double v = -1e18; for (auto& r : m.runs) v = std::max(v, (double)f(r)); return v; }
template <class F> double least(const Many& m, F f) { double v = 1e18; for (auto& r : m.runs) v = std::min(v, (double)f(r)); return v; }
double perMin(const Run& r, int n) { return n * 60000.0 / std::max<uint32_t>(1, r.endedAt - r.startedAt); }
double idle(const Many& m) { const Run* w = &m.runs[0]; for (auto& r : m.runs) if (r.longestIdleWithMob > w->longestIdleWithMob) w = &r; dumpIdle(*w); return w->longestIdleWithMob / 1000.0; }
std::vector<Expect> rules(const Many& m, bool smart) {
    std::vector<Expect> e;
    e.push_back({"no key is left held down", worst(m, [](const Run& r) { return r.keysLeft; }) == 0});
    if (smart) e.push_back({"with Smart on, (almost) no attack without a mob in reach (at most 5% or 2 attacks: a mob can step out of reach mid-swing; fighting its way back in from outside the zone excepted)",
        worst(m, [](const Run& r) { return r.wasted <= 2 ? 0.0 : 100.0 * r.wasted / r.attacks; }) <= 5});
    return e;
}

std::vector<Mob> spread(int platform, double x0, double x1, int n) {
    std::vector<Mob> v; for (int i = 0; i < n; ++i) { Mob m; m.platform = platform; m.x = x0 + (x1 - x0) * (i + 0.5) / n; v.push_back(m); } return v;
}

int main() {
    {std::ifstream f("tests/fixtures/default_pattern.json"); assert(f);
     defaultPatternJson.assign(std::istreambuf_iterator<char>(f), std::istreambuf_iterator<char>());}
    std::printf("Scenarios: the default pattern (as the editor makes it) in a simulated map.\n\n");
    auto with = [](std::function<void(JsonObject)> f) { return loadPattern(f); };

    // 1. Attacking: the defaults, a flat 2000 px map with mobs all along it.
    {Setup s; s.world.mobs = spread(0, 100, 1900, 10);
     auto m = repeat(s, with([](JsonObject) {}));
     auto e = rules(m, true);
     double rate = least(m, [](const Run& r) { return perMin(r, r.attacks); }), kills = least(m, [](const Run& r) { return r.kills; });
     e.push_back({"keeps attacking: never more than 4 s with a mob in reach and no attack", idle(m) <= 4});
     e.push_back({"kills mobs", kills >= 3});
     e.push_back({"never inside the map-edge margin (12%; give or take the screen reader's 0.5% and one turn step to face a mob)", least(m, [](const Run& r) { return r.minX; }) >= 215 && worst(m, [](const Run& r) { return r.maxX; }) <= 1785});
     report("Attacking (defaults)", "keeps attacking and killing mobs, stays out of the map-edge margin, no key left held",
            e, fmt("%.0f attacks/min, longest idle by a mob %.1f s, %.0f kills, x %.0f–%.0f px", rate, idle(m), kills, least(m, [](const Run& r) { return r.minX; }), worst(m, [](const Run& r) { return r.maxX; })));}

    // 2. Reach: one mob in sight but out of reach, Walk to mobs off: no attacking the air until it's in reach.
    {Setup s; Mob mob; mob.platform = 0; mob.x = 1300; s.world.mobs = {mob}; s.maxMs = 30000;   // 300 px away: twice the reach
     s.during = [](Sim& sim, uint32_t t) {   // after 15 s it walks up to 80 px away and stays
         Mob& m = sim.w.mobs[0]; if (t < 15000 || !m.alive) return;
         m.wanderAt = millis() + 100000; m.vx = m.x > 1080 ? -0.05 : 0; };
     auto m = repeat(s, with([](JsonObject p) { p["approach"] = false; }));
     auto e = rules(m, true);
     e.push_back({"attacks once the mob is in reach", least(m, [](const Run& r) { return r.hits; }) >= 1});
     report("Attacking within reach", "with a mob out of reach it waits (no attacks), then attacks once the mob walks into reach",
            e, fmt("attacks without a mob in reach: %.0f, hits: %.0f", worst(m, [](const Run& r) { return r.wasted; }), least(m, [](const Run& r) { return r.hits; })));}

    // 3. Sight: mobs in sight, none in reach, Walk to mobs on: walks over and attacks.
    {Setup s; s.world.mobs = spread(0, 1350, 1450, 2); s.maxMs = 30000;
     auto m = repeat(s, with([](JsonObject p) { p["home_range"] = 0; }));
     auto e = rules(m, true);
     e.push_back({"walks to the mobs and kills them", least(m, [](const Run& r) { return r.kills; }) >= 1});
     report("Attacking with sight (walk to mobs)", "walks to mobs it can see but not reach, then attacks them",
            e, fmt("kills: %.0f, furthest right %.0f px", least(m, [](const Run& r) { return r.kills; }), least(m, [](const Run& r) { return r.maxX; })));}

    // 4. Home 0: no home, wanders freely; still never into the map-edge margin.
    {Setup s; s.world.mobs = spread(0, 100, 1900, 8);
     auto m = repeat(s, with([](JsonObject p) { p["home_range"] = 0; }));
     auto e = rules(m, true);
     e.push_back({"never walks back to a home", worst(m, [](const Run& r) { return r.walkedHome; }) == 0});
     e.push_back({"keeps attacking: never more than 4 s with a mob in reach and no attack", idle(m) <= 4});
     e.push_back({"never inside the map-edge margin (give or take 0.5% and one turn step)", least(m, [](const Run& r) { return r.minX; }) >= 215 && worst(m, [](const Run& r) { return r.maxX; }) <= 1785});
     report("Home at 0%", "no home: it goes where the mobs are, never walks back to a spot, stays out of the map-edge margin",
            e, fmt("x %.0f–%.0f px, %.0f attacks/min, longest idle by a mob %.1f s", least(m, [](const Run& r) { return r.minX; }), worst(m, [](const Run& r) { return r.maxX; }), least(m, [](const Run& r) { return perMin(r, r.attacks); }), idle(m)));}

    // 5. A narrow zone on flat ground, mobs everywhere: never past the line, keeps attacking.
    for (double glide : {0.0, 0.6, 1.0}) {
        Setup s; s.world.mobs = spread(0, 100, 1900, 14);
        auto m = repeat(s, with([glide](JsonObject p) { p["home_range"] = 0.1; p["glide"] = glide; }));
        auto e = rules(m, true);
        double past = worst(m, [](const Run& r) { return r.furthestPast; });
        e.push_back({"never past the zone's line", past <= 0});
        e.push_back({"keeps attacking: never more than 4 s with a mob in reach and no attack", idle(m) <= 4});
        report(fmt("Narrow zone, 10%% (moves while attacking %.0f%%)", glide * 100).c_str(), "stays within home ± 10% of the map, attacking the mobs inside it",
               e, fmt("furthest %+.0f px from the line, %.0f attacks/min, longest idle by a mob %.1f s", past, least(m, [](const Run& r) { return perMin(r, r.attacks); }), idle(m)));
    }

    // 6. A narrow zone on a platform (the zone inside the platform): never falls, keeps attacking.
    for (double glide : {0.0, 0.6, 1.0}) {
        Setup s; s.world.platforms = {{0, 2000, 0}, {700, 1300, 200}}; s.startPlatform = 1; s.startX = 1000;
        s.world.mobs = spread(1, 720, 1280, 4); auto below = spread(0, 100, 1900, 6); s.world.mobs.insert(s.world.mobs.end(), below.begin(), below.end());
        auto m = repeat(s, with([glide](JsonObject p) { p["home_range"] = 0.12; p["glide"] = glide; }));   // ±240 px on a 600 px platform
        auto e = rules(m, true);
        e.push_back({"never falls off the platform", worst(m, [](const Run& r) { return r.fell; }) == 0});
        e.push_back({"keeps attacking: never more than 4 s with a mob in reach and no attack", idle(m) <= 4});
        e.push_back({"never past the zone's line", worst(m, [](const Run& r) { return r.furthestPast; }) <= 0});
        report(fmt("Platform, zone inside it (moves while attacking %.0f%%)", glide * 100).c_str(), "on a 600 px platform with home ± 240 px it never falls, and keeps attacking",
               e, fmt("fell: %s, x %.0f–%.0f px (platform 700–1300), %.0f attacks/min, longest idle by a mob %.1f s", worst(m, [](const Run& r) { return r.fell; }) ? "yes" : "no",
                      least(m, [](const Run& r) { return r.minX; }), worst(m, [](const Run& r) { return r.maxX; }), least(m, [](const Run& r) { return perMin(r, r.attacks); }), idle(m)));
    }

    // 7. Two platforms on the same level with a gap; zone inside the first; mobs on both.
    {Setup s; s.world.platforms = {{0, 2000, 0}, {600, 1100, 200}, {1250, 1700, 200}}; s.startPlatform = 1; s.startX = 850;
     s.world.mobs = spread(1, 620, 1080, 3); auto other = spread(2, 1270, 1680, 4); s.world.mobs.insert(s.world.mobs.end(), other.begin(), other.end());
     auto m = repeat(s, with([](JsonObject p) { p["home_range"] = 0.1; }));   // ±200 px: 650–1050 on a 600–1100 platform
     auto e = rules(m, true);
     e.push_back({"never falls into the gap", worst(m, [](const Run& r) { return r.fell; }) == 0});
     e.push_back({"keeps attacking: never more than 4 s with a mob in reach and no attack", idle(m) <= 4});
     report("Platform with another across a gap", "with mobs on the next platform too, it never walks or jumps into the gap",
            e, fmt("fell: %s, furthest right %.0f px (gap from 1100), %.0f attacks/min, longest idle by a mob %.1f s", worst(m, [](const Run& r) { return r.fell; }) ? "yes" : "no",
                   worst(m, [](const Run& r) { return r.maxX; }), least(m, [](const Run& r) { return perMin(r, r.attacks); }), idle(m)));}

    // 8. The zone overlapping the map's edge: the map-edge margin and the zone both hold.
    {Setup s; s.startX = 300; s.world.mobs = spread(0, 30, 800, 9);
     auto m = repeat(s, with([](JsonObject p) { p["home_range"] = 0.1; }));   // home 15%, zone 100–500 px, margin 240 px
     auto e = rules(m, true);
     e.push_back({"never inside the map-edge margin (240 px, give or take 0.5%)", least(m, [](const Run& r) { return r.minX; }) >= 230});
     e.push_back({"never past the zone's far line (500 px)", worst(m, [](const Run& r) { return r.maxX; }) <= 500});
     report("Zone overlapping the map edge", "home near the map's edge: the map-edge margin wins on that side, the zone on the other",
            e, fmt("x %.0f–%.0f px (margin to 240, zone to 500)", least(m, [](const Run& r) { return r.minX; }), worst(m, [](const Run& r) { return r.maxX; })));}

    // 9. Knocked out of the zone with mobs about: fights its way back, attacking.
    {Setup s; s.world.mobs = spread(0, 700, 1400, 6); s.maxMs = 60000;
     s.during = [](Sim& sim, uint32_t t) { if (t > 8000 && !sim.hitOut && !sim.air) { sim.hitOut = true; sim.x = 1300; } };   // a big hit: 300 px out
     auto m = repeat(s, with([](JsonObject p) { p["home_range"] = 0.1; }));
     auto e = rules(m, true);
     double outside = least(m, [](const Run& r) { return r.attacksOutside; }), back = worst(m, [](const Run& r) { return r.longestOutside / 1000.0; });
     e.push_back({"attacks on the way back (not just running)", outside >= 1});
     e.push_back({"back inside the zone within 5 s", back <= 5});
     report("Knocked out of the zone", "pushed 300 px out with mobs about, it keeps attacking while it drifts back in",
            e, fmt("%.0f attacks while outside, back inside after %.1f s", outside, back));}

    // 10. Set home while playing: the pattern carries on, around the new home.
    {Setup s; s.world.mobs = spread(0, 100, 1900, 14); s.maxMs = 60000;
     s.during = [](Sim& sim, uint32_t t) {
         if (t > 20000 && !sim.hitOut && !sim.air) { sim.hitOut = true; sim.x = 1500; sim.homeX = 1500; liveStatsUpdate(sim.read()); homePin(); }   // walked over and pressed Set home
     };
     auto m = repeat(s, with([](JsonObject p) { p["home_range"] = 0.1; }));
     auto e = rules(m, true);
     e.push_back({"keeps attacking after Set home: never more than 4 s with a mob in reach and no attack", idle(m) <= 4});
     e.push_back({"never past the new zone's line", worst(m, [](const Run& r) { return r.furthestPast; }) <= 0});
     report("Set home while playing", "home moves to where you stand (75%) and the pattern carries on around it, without stopping",
            e, fmt("furthest %+.0f px from the line, %.0f attacks/min, longest idle by a mob %.1f s", worst(m, [](const Run& r) { return r.furthestPast; }), least(m, [](const Run& r) { return perMin(r, r.attacks); }), idle(m)));}

    // 12. The zone's safety band is measured in your own movement (about 0.4 s of walking: one
    // knockback), not in % of the minimap: the same real room on a small map and a big one.
    // With mobs knocking you back, it stays inside the line on both maps.
    for (double width : {1000.0, 6000.0}) {
        Setup s; s.world.width = width; s.world.platforms = {{0, width, 0}}; s.startX = width / 2; s.world.knockback = true;
        s.world.mobs = spread(0, width * 0.05, width * 0.95, (int)(width / 140));
        auto m = repeat(s, with([](JsonObject p) { p["home_range"] = 0.1; }));
        auto e = rules(m, true);
        double past = worst(m, [](const Run& r) { return r.furthestPast; });
        e.push_back({"knocked back near the edge, still never past the line", past <= 0});
        report(fmt("Knockback near the zone's edge, %.0f px map", width).c_str(), "the safety band is about one knockback in real distance whatever the map's size: never past the line",
               e, fmt("furthest %+.0f px from the line", past));
    }
    // 13. ...and on a big map the band doesn't waste the zone: mobs just inside the line (90% of
    // the way out, 540 px from home on a 6000 px map with a 10% zone) are walked to and killed.
    // A band of a quarter of the zone (150 px) plus a jump's drift stopped it 200 px short.
    {Setup s; s.world.width = 6000; s.world.platforms = {{0, 6000, 0}}; s.startX = 3000; s.maxMs = 60000;
     Mob a; a.platform = 0; a.x = 3540; a.still = true; Mob b = a; b.x = 3545; s.world.mobs = {a, b};   // standing still
     auto m = repeat(s, with([](JsonObject p) { p["home_range"] = 0.1; p["auto_pause"] = 0; }));
     auto e = rules(m, true);
     double kills = least(m, [](const Run& r) { return r.kills; }), reached = least(m, [](const Run& r) { return r.maxX - 3000; });
     e.push_back({"walks out and kills mobs at 90% of the zone", kills >= 1});
     e.push_back({"never past the line", worst(m, [](const Run& r) { return r.furthestPast; }) <= 0});
     report("Big map: mobs near the zone's line", "the safety band is real distance, so on a big map it walks out to mobs near the line and kills them",
            e, fmt("kills: %.0f, reached %.0f of 600 px from home", kills, reached));}

    // 11. Death: it stops, nothing left held.
    {Setup s; s.world.mobs = spread(0, 100, 1900, 10); s.maxMs = 60000;
     s.during = [](Sim& sim, uint32_t t) { if (t > 10000) sim.state = LIVE_DEAD; };
     auto m = repeat(s, with([](JsonObject) {}), 2);
     auto e = rules(m, true);
     double stoppedAfter = worst(m, [](const Run& r) { return (double)(r.endedAt - r.startedAt); });
     e.push_back({"stops within 2 s of dying", stoppedAfter <= 12000});
     report("Death", "stops playing as soon as you die, nothing left held", e, fmt("stopped %.1f s in (died at 10 s)", stoppedAfter / 1000));}

    std::printf("\n%s: %d scenario(s) failed\n", failures ? "FAILED" : "scenarios passed", failures);
    return failures ? 1 : 0;
}
