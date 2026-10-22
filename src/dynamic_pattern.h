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
    uint32_t cooldownMs = 0;
};
struct DynamicPattern {
    std::string id;
    DynamicRange jumpToAttack{45,120};
    DynamicRange attackToJumpUp{30,120};
    DynamicRange jumpUpToAttackUp{16,80};
    DynamicRange comboGap{510,760};
    DynamicRange directionHold{85,180};
    DynamicRange directionAfter{16,330};
    DynamicRange combosPerBatch{2,10};
    DynamicRange batches{8,12};
    uint16_t turnChancePermille = 800;
    bool shuffleSkills = true;
    std::vector<DynamicSkill> skills;
};

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
