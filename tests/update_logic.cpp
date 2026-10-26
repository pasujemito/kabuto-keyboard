#include "../src/update_logic.h"
#include <cassert>
#include <iostream>
int main(){
    uint32_t v[3];
    assert(parseVersion("1.14.0",v)&&v[0]==1&&v[1]==14&&v[2]==0);
    for(const char* bad:{"v1.14.0","1.14","1.14.0-beta","1.14.0 ","","a.b.c"})assert(!parseVersion(bad,v));
    assert(isNewerVersion("1.14.0","1.13.9")&&isNewerVersion("2.0.0","1.99.99")&&isNewerVersion("1.13.10","1.13.9"));
    assert(!isNewerVersion("1.13.0","1.13.0")&&!isNewerVersion("1.12.5","1.13.0"));
    assert(!isNewerVersion("v9.0.0","1.0.0")&&!isNewerVersion("9.0.0","garbage"));
    assert(isSha256Hex(std::string(64,'a'))&&!isSha256Hex(std::string(64,'A'))&&!isSha256Hex(std::string(63,'a')));
    // Must match tools/release_index.py byte for byte (its self-test pins the same string).
    assert(manifestPayload("1.14.0",1234,std::string(64,'f'))=="1.14.0\n1234\n"+std::string(64,'f')+"\n");
    assert(wifiJoinProblem(201).find("2.4 GHz")!=std::string::npos&&wifiJoinProblem(15)=="the password looks wrong");
    assert(wifiJoinProblem(204)==wifiJoinProblem(202)&&wifiJoinProblem(0).find("in time")!=std::string::npos&&wifiJoinProblem(8)=="Wi-Fi error 8");
    assert(canInstallNow(false,false)&&!canInstallNow(true,false)&&!canInstallNow(false,true));
    assert(!shouldRollBack(false,99)&&!shouldRollBack(true,UPDATE_MAX_TRIAL_BOOTS)&&shouldRollBack(true,UPDATE_MAX_TRIAL_BOOTS+1));
    std::cout<<"update logic tests passed\n";
}
