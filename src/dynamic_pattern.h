#pragma once
#include <cstdint>
#include <cmath>
#include <string>
#include <vector>

struct DynamicRange { uint32_t min; uint32_t max; };
// A movement key: a modifier such as Alt (mods) or a normal key (keycode).
// Values are HID codes from keymap.h, kept numeric so host tests need no Arduino.
struct DynamicKey {
    uint8_t keycode = 0;
    uint8_t mods = 0;
    bool empty() const { return !keycode && !mods; }
    bool operator==(const DynamicKey& o) const { return keycode == o.keycode && mods == o.mods; }
    bool operator!=(const DynamicKey& o) const { return !(*this == o); }
};
inline DynamicKey dynamicModifier(uint8_t mods) { DynamicKey k; k.mods = mods; return k; }
inline DynamicKey dynamicKeycode(uint8_t keycode) { DynamicKey k; k.keycode = keycode; return k; }
// A skill, or an HP/Mana potion (always fires once its wait is over).
struct DynamicSkill {
    std::string id;
    uint8_t keycode = 0;
    bool enabled = true;
    uint16_t chancePermille = 100;
    DynamicRange repeats{2,2};
    DynamicRange hold{85,110};
    DynamicRange after{880,1130};
    DynamicRange cooldown{0,0}; // wait after each use; a fresh draw every time
    uint8_t belowPercent = 0;   // potions: with live bars, drink below this % (0 = timer only)
    uint8_t belowTo = 0;        // potions: ...or anywhere from belowPercent up to this %, drawn afresh after each drink (0 = always belowPercent)
    uint32_t barMax = 0, perTap = 0;   // potions: the bar's real total and what one tap restores (0 = taps range)
    std::vector<uint8_t> backupKeys;   // potions: more keys of the same kind, used in turn when one runs out (up to 3)
    std::vector<uint32_t> backupPerTap;   // what each backup restores per tap (0: the same as perTap)
};
struct DynamicPattern {
    std::string id;
    DynamicRange jumpToAttack{45,120};
    DynamicRange attackToJumpUp{30,120};
    DynamicRange jumpUpToAttackUp{16,80};
    DynamicRange comboGap{510,760};
    DynamicRange directionHold{85,180};
    DynamicRange directionAfter{16,330};
    DynamicRange attacksPerSet{2,10}; // jump-attacks while facing one way
    DynamicRange sets{8,12};          // sets per play; skills/turns happen between sets
    uint16_t turnChancePermille = 800;
    uint16_t tempoDriftPermille = 0;  // how far the gap after each attack may drift slower/faster
    bool shuffleSkills = true;
    // Screen awareness (needs tools/screen_stats.py); off in older patterns.
    uint16_t edgeMarginPermille = 0;  // turn back within this far of a minimap edge
    uint32_t stuckAfterMs = 0;        // minimap dot still this long: turn, then stop
    bool faceMobs = false;            // saved by older versions; mobs in reach are always faced now
    bool smart = false;               // no mobs: wait for them (and, with a home, hunt around it)
    uint16_t homeRangePermille = 0;   // how far from home you may drift, Smart or not (0 = no home)
    uint16_t autoPausePermille = 0;   // smart: most mobs in sight killed (below this share): wait for respawn (0 = off)
    bool approach = false;            // smart: walk to mobs you can see but not reach
    bool attacking = true;            // off: support only, no jump/attack/arrows, just potions and skills until stopped
    // From the active character (Config::characters) instead of the pattern's own:
    // its movement keys, its HP/Mana potions, its skills (with skill order).
    bool charKeys = false, charPotions = false, charSkills = false;
    DynamicRange walkHold{280,650};   // smart: walking (home or to mobs) holds the arrow, jumping after each of these
    uint16_t glidePermille = 0;       // share of sets moving while jump-attacking (arrow held); >0 also turns in the air
    // A rhythm that never settles (2.0; patterns saved before play exactly as they did).
    uint16_t peakPermille = 500;         // where in a timing range most draws land (500 = the middle; lower = quick, with a long tail)
    uint16_t hesitationPermille = 0;     // share of gaps after an attack stretched HESITATION times (a moment's hesitation)
    uint16_t wobblePermille = 0;         // each play shifts every timing range by up to this much, so no two plays share an average
    uint16_t breakChancePermille = 0;    // after a set: the chance of a short break of breakMs
    DynamicRange breakMs{700,2500};
    DynamicRange restEvery{0,0};         // a longer rest this often (ms; 0-0 = off), lasting restMs
    DynamicRange restMs{8000,30000};
    // Smarter with the screen reader (2.1; off in patterns saved before).
    bool mobSets = false;                // a set ends when its mobs are dead (no mob in reach), not only on its count
    DynamicRange reaction{0,0};          // after waiting, this long between seeing a mob in reach and attacking it
    uint16_t edgeMarginToPermille = 0;   // the edge margin is drawn from edgeMargin..this after each set (0 = always edgeMargin)
    DynamicRange session{0,0};           // stop by itself after playing this long without a real pause (ms; 0-0 = never)
    // Defaults match patterns saved before keys were configurable.
    DynamicKey jump = dynamicModifier(0x04);     // KM_LALT
    DynamicKey attack = dynamicModifier(0x01);   // KM_LCTRL
    DynamicKey left = dynamicKeycode(0x50);      // KC_LEFT
    DynamicKey right = dynamicKeycode(0x4F);     // KC_RIGHT
    std::vector<DynamicSkill> potions;           // "hp" and/or "mana", fired before skills
    std::vector<DynamicSkill> skills;
};

// A character: what belongs to whoever you play rather than to a pattern, set
// once and used by every pattern that picks it up (keys, potions, skills).
struct Character {
    std::string id, name;
    DynamicKey jump = dynamicModifier(0x04), attack = dynamicModifier(0x01), left = dynamicKeycode(0x50), right = dynamicKeycode(0x4F);
    std::vector<DynamicSkill> potions, skills;
    bool shuffleSkills = true;
};
// The pattern as it plays: the character's parts swapped in where it uses them.
inline DynamicPattern withCharacter(const DynamicPattern& p, const Character* c) {
    DynamicPattern out = p;
    if (!c) return out;
    if (p.charKeys) { out.jump = c->jump; out.attack = c->attack; out.left = c->left; out.right = c->right; }
    if (p.charPotions) out.potions = c->potions;
    if (p.charSkills) { out.skills = c->skills; out.shuffleSkills = c->shuffleSkills; }
    return out;
}

// Why a pattern's keys clash, or "" if they don't. Jump and attack overlap
// as a chord, turns are tapped between sets, and skills and potions must not
// press a movement key mid-pattern.
inline std::string dynamicKeyProblem(const DynamicPattern& p) {
    if (p.jump.empty() || p.attack.empty() || p.left.empty() || p.right.empty()) return "choose all four movement keys";
    if (p.jump == p.attack) return "jump and attack need different keys";
    if (p.left == p.right) return "turn left and turn right need different keys";
    for (DynamicKey turn : {p.left, p.right})
        if (turn == p.jump || turn == p.attack) return "turn keys must differ from jump and attack";
    for (const auto* list : {&p.potions, &p.skills})
        for (const auto& s : *list) {
            DynamicKey k = dynamicKeycode(s.keycode);
            if (k == p.jump || k == p.attack || k == p.left || k == p.right) return "skills and potions can't use a movement key";
            for (uint8_t b : s.backupKeys) {
                DynamicKey bk = dynamicKeycode(b);
                if (bk == p.jump || bk == p.attack || bk == p.left || bk == p.right) return "skills and potions can't use a movement key";
            }
        }
    return "";
}

// One step of the attack-tempo drift: a mean-reverting random walk in permille
// around 1.0x, kept within +/-drift. A recorded 57 s run drifted like 15% with
// noise of +/-drift/2 (lag-1 correlation ~0.33 of the gap after each attack).
inline int32_t tempoDriftStep(int32_t offset, uint16_t drift, int32_t noise) {
    offset = offset * 9 / 10 + noise;
    const int32_t limit = drift;
    return offset > limit ? limit : offset < -limit ? -limit : offset;
}

// Inverse CDF of a triangular distribution, quantized to integer
// milliseconds/counts. Draw is in [0, 1000000], including both endpoints.
// `peak` (permille of the range) is where most draws land: 500 is symmetric
// (counts, and patterns from before 2.0); lower leans quick with a longer tail
// on the slow side, as a person's timings do.
inline uint32_t triangularSample(DynamicRange range, uint32_t draw, uint16_t peak = 500) {
    if (range.min == range.max) return range.min;
    const double u = (draw > 1000000 ? 1000000 : draw) / 1000000.0;
    const double m = (peak > 1000 ? 1000 : peak) / 1000.0;
    const double span = range.max - range.min;
    const double value = u < m ? range.min + span * std::sqrt(u * m)
                               : range.max - span * std::sqrt((1.0-u) * (1.0-m));
    return static_cast<uint32_t>(std::lround(value));
}

// A threshold that isn't the same every time: from..to (to 0 or below from: always from).
// `draw(n)` returns a whole number in [0, n).
template <typename Draw> inline uint32_t drawBetween(uint32_t from, uint32_t to, Draw draw) {
    return to > from ? from + (uint32_t)draw((int32_t)(to - from + 1)) : from;
}

// A hesitation: the gap after an attack, this many times as long (permille). In the recorded
// playthrough 9% of the gaps were 1.4-1.9 times the usual one.
const DynamicRange HESITATION{1300,1900};
inline uint32_t hesitate(uint32_t gap, uint32_t timesPermille) { return (uint32_t)((uint64_t)gap * timesPermille / 1000); }

// Per-play wobble: a timing range moved as a whole by `offset` permille (within
// +/-wobble), so one play runs a little quicker or slower than the next. Never
// past 90 s (the longest hold), never out of order.
inline DynamicRange wobbleRange(DynamicRange range, int32_t offset) {
    auto scale = [offset](uint32_t v) {
        int64_t out = (int64_t)v * (1000 + offset) / 1000;
        return (uint32_t)(out < 0 ? 0 : out > 90000 && v <= 90000 ? 90000 : out);
    };
    DynamicRange out{scale(range.min), scale(range.max)};
    if (out.max < out.min) out.max = out.min;
    return out;
}
// The pattern as this play runs it: each timing range wobbled by its own draw.
// `draw(n)` returns a whole number in [0, n).
template <typename Draw> inline void wobblePattern(DynamicPattern& p, Draw draw) {
    if (!p.wobblePermille) return;
    const int32_t w = p.wobblePermille;
    for (DynamicRange* r : {&p.jumpToAttack, &p.attackToJumpUp, &p.jumpUpToAttackUp, &p.comboGap, &p.directionHold, &p.directionAfter, &p.walkHold})
        *r = wobbleRange(*r, (int32_t)draw(2 * w + 1) - w);
}
