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
    std::cout<<"dynamic sampling tests passed\n";
}
