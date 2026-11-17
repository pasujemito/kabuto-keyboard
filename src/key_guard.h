#pragma once
#include <cstdint>

// The last line of defence against a key left held on the PC (pure, host-tested).
// The main loop runs on its own task and checks this every scan, whatever the
// playing task is doing:
// - playing, but the playing task hasn't ticked for KEY_GUARD_STALL_MS (it hung,
//   or is stuck in a Bluetooth send): let go of everything and stop it;
// - nothing playing, yet a key has been held unchanged for KEY_GUARD_IDLE_HOLD_MS
//   (only the page's live keys hold keys outside a pattern, and they change far
//   more often than that): let go of everything.
// A playing pattern ticks every few ms (each wait is cut into 5 ms steps), so a
// long hold inside a pattern never trips it.
const uint32_t KEY_GUARD_STALL_MS = 3000;
const uint32_t KEY_GUARD_IDLE_HOLD_MS = 5000;
enum KeyGuardVerdict : uint8_t { KEY_GUARD_OK, KEY_GUARD_RELEASE, KEY_GUARD_STOP };
// "All keys up" is said more than once. The Bluetooth library can drop a report
// without telling the pad (no send buffer free for a moment), and a dropped
// release leaves the key down on the PC while the pad believes it's up. So once
// nothing is held, the empty report goes again ALL_UP_REPEAT_MS later, twice,
// and then the pad is silent until something changes, as a keyboard is: a lost
// release is mended within 160 ms. Windows only turns a report into a key event
// when a key changes, so a repeated empty report never reaches a program.
// `owed`: repeats still due; returns true when one is due now.
const uint32_t ALL_UP_REPEAT_MS = 80;
inline bool allUpDue(bool held, uint8_t owed, uint32_t sinceSendMs) {
    return !held && owed && sinceSendMs >= ALL_UP_REPEAT_MS;
}

inline uint8_t keyGuard(bool held, bool playing, uint32_t sinceChangeMs, uint32_t sinceTickMs) {
    if (!held) return KEY_GUARD_OK;
    if (playing) return sinceTickMs >= KEY_GUARD_STALL_MS ? KEY_GUARD_STOP : KEY_GUARD_OK;
    return sinceChangeMs >= KEY_GUARD_IDLE_HOLD_MS ? KEY_GUARD_RELEASE : KEY_GUARD_OK;
}
