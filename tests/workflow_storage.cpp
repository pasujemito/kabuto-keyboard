#include <Arduino.h>
#include <LittleFS.h>
#include "../src/storage.h"
#include <fstream>
#include <iterator>
#include <cassert>
#include <iostream>
TestLittleFS LittleFS;
void Config::ensureLayer(size_t n){while(layers.size()<=n)layers.push_back(Layer{});}
int main(){
    std::ifstream file("data/macros.json");assert(file);
    String json(std::string((std::istreambuf_iterator<char>(file)),std::istreambuf_iterator<char>()));
    String err;assert(saveRawJson(json,err));Config cfg;assert(loadConfig(cfg));
    assert(cfg.layers.size()==2&&cfg.layers[0].keys[0].steps[0].type==StepType::COMBAT);
    const Step& combat=cfg.layers[0].keys[0].steps[0];assert(combat.value==25000&&combat.maxValue==85000);
    assert(combat.choices.size()==6&&combat.avoidRecent==1);
    assert(cfg.workflows[0].steps[0].type==StepType::MOVE&&cfg.workflows[0].steps[0].maxValue==524);
    bool found=false;for(const auto& w:cfg.workflows)if(w.id=="pet-food"){
        found=true;assert(w.cooldownMs==1800000&&!w.utilityEnabled&&w.chancePermille==50);
    }assert(found);
    assert(saveConfig(cfg));Config roundtrip;assert(loadConfig(roundtrip));
    assert(roundtrip.layers[0].keys[0].steps[0].maxValue==85000);
    assert(roundtrip.workflows[0].steps[0].maxValue==524);
    // Invalid ranges, overflowing movement, and unassigned enabled utilities
    // must fail before overwriting the saved configuration.
    auto previous=readRawJson();
    const char* bad[]={
        R"({"layers":[{"keys":[{"steps":[{"type":"combat","ms":90001,"choices":[{"layer":0,"key":1}]}]}]}]})",
        R"({"layers":[{"keys":[{"steps":[{"type":"delay","ms":100,"maxMs":50}]}]}]})",
        R"({"layers":[{"keys":[{"steps":[{"type":"move","ms":601}]}]}]})",
        R"({"layers":[],"workflows":[{"id":"x","steps":[],"utilityEnabled":true,"cooldownMs":300000}]})"
    };
    for(auto raw:bad){assert(!saveRawJson(String(raw),err));assert(readRawJson()==previous);}
    // Long taps retain 32-bit values rather than wrapping at 65.535 seconds.
    assert(saveRawJson(String(R"({"layers":[{"keys":[{"steps":[{"type":"key","key":"A","hold":90000}]}]}]})"),err));
    assert(loadConfig(cfg));assert(cfg.layers[0].keys[0].steps[0].value==90000);
    std::cout<<"workflow storage tests passed\n";
}
