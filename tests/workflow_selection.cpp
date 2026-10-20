#include "../src/workflow_selection.h"
#include <cassert>
#include <iostream>

int main() {
    const std::vector<uint16_t> weights{1, 3, 2};
    std::vector<bool> eligible{true, true, true};
    assert(workflowWeightTotal(weights, eligible) == 6);
    const int expected[]{0, 1, 1, 1, 2, 2};
    for (uint32_t draw = 0; draw < 6; ++draw)
        assert(selectWorkflow(weights, eligible, draw) == expected[draw]);
    assert(selectWorkflow(weights, eligible, 6) == -1);
    eligible[1] = false;
    assert(workflowWeightTotal(weights, eligible) == 3);
    assert(selectWorkflow(weights, eligible, 0) == 0);
    assert(selectWorkflow(weights, eligible, 1) == 2);
    assert(selectWorkflow(weights, eligible, 2) == 2);
    assert(selectWorkflow({0, 0}, {true, true}, 0) == -1);
    assert(selectWorkflow({}, {}, 0) == -1);
    assert(selectWorkflow(weights, {false, false, false}, 0) == -1);
    // Repeated selections use actual firmware history and selection helpers.
    // Excluding two with three choices guarantees no repeats within that window.
    std::vector<int> history;
    for (unsigned iteration = 0; iteration < 1000; ++iteration) {
        for (int i = 0; i < 3; ++i) eligible[i] = !workflowIsRecent(i, history, 2);
        uint32_t total = workflowWeightTotal(weights, eligible);
        assert(total > 0);
        int selected = selectWorkflow(weights, eligible, iteration % total);
        assert(!workflowIsRecent(selected, history, 2));
        rememberWorkflow(selected, history, 2);
        assert(history.size() <= 2);
    }
    // Exhaustion skips: it must not silently re-enable excluded choices.
    history = {0, 1, 2};
    for (int i = 0; i < 3; ++i) eligible[i] = !workflowIsRecent(i, history, 3);
    assert(selectWorkflow(weights, eligible, 0) == -1);
    assert(!workflowIsRecent(2, history, 0));
    // Retention and 32-bit totals for the supported maximum weights/counts.
    history.clear();
    for (int i = 0; i < 100; ++i) rememberWorkflow(i, history, 16);
    assert(history.size() == 16 && history.front() == 84 && history.back() == 99);
    assert(workflowWeightTotal(std::vector<uint16_t>(112, 1000), std::vector<bool>(112, true)) == 112000);
    std::cout << "workflow selection tests passed\n";
}
