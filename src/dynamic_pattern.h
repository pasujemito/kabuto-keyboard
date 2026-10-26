#pragma once
#include <cstdint>
#include <cmath>
#include <string>
#include <vector>

struct DynamicRange { uint32_t min; uint32_t max; };
struct DynamicSkill {
    std::string id;
    uint8_t keycode = 0;
    bool enabled = true;
    uint16_t chancePermille = 100;
    DynamicRange repeats{2,2};
    DynamicRange hold{85,110};
    DynamicRange after{880,1130};
    DynamicRange cooldown{0,0}; // wait after each use; a fresh draw every time
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
    std::vector<DynamicSkill> skills;
};

// One step of the attack-tempo drift: a mean-reverting random walk in permille
// around 1.0x, kept within +/-drift. A recorded 57 s run drifted like 15% with
// noise of +/-drift/2 (lag-1 correlation ~0.33 of the gap after each attack).
inline int32_t tempoDriftStep(int32_t offset, uint16_t drift, int32_t noise) {
    offset = offset * 9 / 10 + noise;
    const int32_t limit = drift;
    return offset > limit ? limit : offset < -limit ? -limit : offset;
}

// Inverse CDF of a symmetric triangular distribution, quantized to integer
// milliseconds/counts. Draw is in [0, 1000000], including both endpoints.
inline uint32_t triangularSample(DynamicRange range, uint32_t draw) {
    if (range.min == range.max) return range.min;
    const double u = (draw > 1000000 ? 1000000 : draw) / 1000000.0;
    const double span = range.max - range.min;
    const double value = u < .5 ? range.min + span * std::sqrt(u / 2.0)
                                : range.max - span * std::sqrt((1.0-u) / 2.0);
    return static_cast<uint32_t>(std::lround(value));
}
