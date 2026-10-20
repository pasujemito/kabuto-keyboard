#pragma once
#include <cstdint>
#include <cstddef>
#include <vector>

// Pick from half-open weighted intervals. The caller supplies a uniform draw
// in [0, total), allowing deterministic tests without a hardware RNG.
inline uint32_t workflowWeightTotal(const std::vector<uint16_t>& weights,
                                    const std::vector<bool>& eligible) {
    uint32_t total = 0;
    for (std::size_t i = 0; i < weights.size() && i < eligible.size(); ++i)
        if (eligible[i]) total += weights[i];
    return total;
}
inline int selectWorkflow(const std::vector<uint16_t>& weights,
                          const std::vector<bool>& eligible, uint32_t draw) {
    if (draw >= workflowWeightTotal(weights, eligible)) return -1;
    for (std::size_t i = 0; i < weights.size() && i < eligible.size(); ++i) {
        if (!eligible[i]) continue;
        if (draw < weights[i]) return static_cast<int>(i);
        draw -= weights[i];
    }
    return -1;
}

// The same helper is used by firmware and host tests. History is ordered from
// oldest to newest, and tracks identities rather than positions in the list.
template <typename T>
inline bool workflowIsRecent(const T& candidate, const std::vector<T>& history, unsigned count) {
    const std::size_t start = history.size() > count ? history.size() - count : 0;
    for (std::size_t i = start; i < history.size(); ++i)
        if (history[i] == candidate) return true;
    return false;
}
template <typename T>
inline void rememberWorkflow(const T& candidate, std::vector<T>& history, unsigned limit) {
    if (!limit) return;
    history.push_back(candidate);
    while (history.size() > limit) history.erase(history.begin());
}
