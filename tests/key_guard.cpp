#include "../src/key_guard.h"
#include <cassert>
#include <iostream>
int main(){
    // Nothing held: nothing to do, whatever else.
    assert(keyGuard(false,true,999999,999999)==KEY_GUARD_OK&&keyGuard(false,false,999999,999999)==KEY_GUARD_OK);
    // Playing and ticking: a key may stay down as long as the pattern wants (an arrow through a glide).
    assert(keyGuard(true,true,600000,4)==KEY_GUARD_OK&&keyGuard(true,true,600000,KEY_GUARD_STALL_MS-1)==KEY_GUARD_OK);
    // Playing but the playing task stopped ticking: let go and stop it.
    assert(keyGuard(true,true,0,KEY_GUARD_STALL_MS)==KEY_GUARD_STOP);
    // Nothing playing (a crash ended it, or the page's live keys): a key held unchanged too long is let go of.
    assert(keyGuard(true,false,KEY_GUARD_IDLE_HOLD_MS-1,999999)==KEY_GUARD_OK&&keyGuard(true,false,KEY_GUARD_IDLE_HOLD_MS,0)==KEY_GUARD_RELEASE);
    // "All keys up" again: soon after a release (twice), then every second while nothing is held; never while a key is.
    assert(!allUpDue(false,2,ALL_UP_REPEAT_MS-1)&&allUpDue(false,2,ALL_UP_REPEAT_MS)&&allUpDue(false,1,ALL_UP_REPEAT_MS));
    assert(!allUpDue(false,0,ALL_UP_REFRESH_MS-1)&&allUpDue(false,0,ALL_UP_REFRESH_MS));
    assert(!allUpDue(true,2,999999)&&!allUpDue(true,0,999999));
    std::cout<<"key guard tests passed\n";
}
