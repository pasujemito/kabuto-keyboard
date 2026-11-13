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
    // A peak off the middle (2.0): the same ends, most draws near the peak, the mean pulled towards it
    // (a triangle's mean is (min + peak + max) / 3), a longer tail on the far side. 500 is the old sampler.
    assert(triangularSample({45,120},0,350)==45&&triangularSample({45,120},1000000,350)==120&&triangularSample({45,120},500000,500)==83);
    {double sum=0;unsigned low=0,n=0;
     for(uint32_t draw=0;draw<=1000000;draw+=10){auto v=triangularSample({0,100},draw,350);assert(v<=100);sum+=v;low+=v<50;++n;}
     assert(sum/n>44.5&&sum/n<45.5&&low>n*6/10);
     assert(triangularSample({0,100},350000,350)==35);   // the peak itself: 35% of draws fall below it
     assert(triangularSample({0,100},1000000,0)==100&&triangularSample({0,100},0,1000)==0&&triangularSample({0,100},1000000,1000)==100);}
    // Hesitation and per-play wobble.
    assert(hesitate(600,1500)==900&&hesitate(600,3000)==1800&&HESITATION.min==1300&&HESITATION.max==1900);
    {DynamicRange r=wobbleRange({510,760},-80);assert(r.min==469&&r.max==699);r=wobbleRange({510,760},0);assert(r.min==510&&r.max==760);
     r=wobbleRange({80000,90000},300);assert(r.min==90000&&r.max==90000);   // never past the longest hold
     DynamicPattern w;w.wobblePermille=0;wobblePattern(w,[](int32_t){return 0;});assert(w.comboGap.min==510);   // off: untouched
     w.wobblePermille=100;wobblePattern(w,[](int32_t n){return n-1;});assert(w.comboGap.min==561&&w.comboGap.max==836&&w.jumpToAttack.max==132);
     assert(w.attacksPerSet.min==2&&w.sets.max==12);}   // counts never wobble
    // Thresholds that aren't the same every time (2.1): from..to, or always `from` when `to` is 0 or lower.
    assert(drawBetween(50,62,[](int32_t){return 0;})==50&&drawBetween(50,62,[](int32_t n){return n-1;})==62);
    assert(drawBetween(50,0,[](int32_t n){return n-1;})==50&&drawBetween(120,100,[](int32_t n){return n-1;})==120&&drawBetween(7,7,[](int32_t){return 0;})==7);
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
