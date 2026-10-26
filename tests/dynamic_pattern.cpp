#include "../src/dynamic_pattern.h"
#include <cassert>
#include <iostream>
int main(){
    assert(triangularSample({45,120},0)==45);
    assert(triangularSample({45,120},1000000)==120);
    assert(triangularSample({45,120},500000)==83);
    assert(triangularSample({7,7},1234)==7);
    unsigned middle=0,edge=0;double total=0;
    for(uint32_t draw=0;draw<=1000000;draw+=10){
        auto v=triangularSample({0,100},draw);assert(v<=100);total+=v;
        if(v>=25&&v<=75)++middle;else ++edge;
    }
    assert(middle>edge*2);assert(total/100001>49.9&&total/100001<50.1);
    // Counts use the same sampler and never leave the configured integer range.
    for(uint32_t draw=0;draw<=1000000;draw+=97){auto n=triangularSample({2,10},draw);assert(n>=2&&n<=10);}
    // Tempo drift reverts toward 1.0x and never leaves +/-drift.
    assert(tempoDriftStep(100,150,0)==90&&tempoDriftStep(-100,150,0)==-90);
    assert(tempoDriftStep(150,150,75)==150&&tempoDriftStep(-150,150,-75)==-150);
    assert(tempoDriftStep(0,0,0)==0);
    // Movement keys default to the original Alt/Ctrl/arrows and must not clash.
    DynamicPattern p;assert(dynamicKeyProblem(p).empty());
    assert(p.jump.mods==0x04&&p.attack.mods==0x01&&p.left.keycode==0x50&&p.right.keycode==0x4F);
    DynamicPattern q=p;q.attack=q.jump;assert(dynamicKeyProblem(q)=="jump and attack need different keys");
    q=p;q.right=q.left;assert(!dynamicKeyProblem(q).empty());
    q=p;q.left=q.attack;assert(dynamicKeyProblem(q)=="turn keys must differ from jump and attack");
    q=p;q.jump=dynamicKeycode(0x2C);q.attack=dynamicKeycode(0x1B);assert(dynamicKeyProblem(q).empty());   // Space jumps, X attacks
    DynamicSkill s;s.keycode=0x1B;q.potions={s};assert(dynamicKeyProblem(q)=="skills and potions can't use a movement key");
    q.potions.clear();s.keycode=0x50;q.skills={s};assert(!dynamicKeyProblem(q).empty());   // a turn key
    q=p;q.left=DynamicKey();assert(dynamicKeyProblem(q)=="choose all four movement keys");
    std::cout<<"dynamic sampling tests passed\n";
}
