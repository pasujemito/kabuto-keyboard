#include <Arduino.h>
#include <LittleFS.h>
#include "../src/storage.h"
#include <fstream>
#include <iterator>
#include <cassert>
#include <iostream>
TestLittleFS LittleFS;
void Config::ensureLayer(size_t n){while(layers.size()<=n)layers.push_back(Layer{});}
// Test helpers: write a JSON string the way an upload does, and read it back.
static bool saveRawJson(const String& json,String& err){
    {File f=LittleFS.open(MACRO_TMP_FILE,"w");f.write((const uint8_t*)json.c_str(),json.length());}
    return commitConfigFile(MACRO_TMP_FILE,err);
}
static String readRawJson(){File f=LittleFS.open(MACRO_FILE,"r");return f?f.readString():String();}
int main(){
    std::ifstream file("examples/combat-layer-one.json");assert(file);
    String json(std::string((std::istreambuf_iterator<char>(file)),std::istreambuf_iterator<char>()));
    String err;assert(saveRawJson(json,err));Config cfg;assert(loadConfig(cfg));
    assert(cfg.layers.size()==2&&cfg.layers[0].keys[0].steps[0].type==StepType::COMBAT);
    const Step& combat=cfg.layers[0].keys[0].steps[0];assert(combat.value==25000&&combat.maxValue==85000);
    assert(combat.choices().size()==6&&combat.avoidRecent==1);
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
    for(auto raw:bad){assert(!saveRawJson(String(raw),err));assert(readRawJson()==previous);assert(!LittleFS.exists(MACRO_TMP_FILE));}
    // Uploads are committed from a temp file, which is removed afterwards.
    {File upload=LittleFS.open(MACRO_TMP_FILE,"w");const char* half=R"({"layers":[{"keys":[)";upload.write((const uint8_t*)half,strlen(half));}
    assert(!commitConfigFile(MACRO_TMP_FILE,err));assert(readRawJson()==previous);assert(!LittleFS.exists(MACRO_TMP_FILE));
    assert(storageInfo().configBytes==previous.size());
    // Long taps retain 32-bit values rather than wrapping at 65.535 seconds.
    assert(saveRawJson(String(R"({"layers":[{"keys":[{"steps":[{"type":"key","key":"A","hold":90000}]}]}]})"),err));
    assert(loadConfig(cfg));assert(cfg.layers[0].keys[0].steps[0].value==90000);
    // UI-only fields such as a button colour are accepted and kept in the file.
    assert(saveRawJson(String(R"({"layers":[{"keys":[{"color":"teal","steps":[{"type":"key","key":"A"}]}]}]})"),err));
    assert(loadConfig(cfg));assert(readRawJson().find("\"teal\"")!=std::string::npos);
    // The simplified shipped recording survives save/load, including hidden
    // storage parts and an empty sequence/random preference on a button.
    std::ifstream preset("data/macros.json");assert(preset);
    String simple(std::string((std::istreambuf_iterator<char>(preset)),std::istreambuf_iterator<char>()));
    assert(saveRawJson(simple,err));assert(loadConfig(cfg));
    assert(cfg.workflows[0].recording&&cfg.workflows[0].id=="sample-recording");
    assert(cfg.workflows[1].recordingPartOf=="sample-recording");
    assert(cfg.layers[0].keys[0].playbackMode=="single");
    cfg.layers[0].keys[1].playbackMode="random";
    assert(saveConfig(cfg));assert(loadConfig(roundtrip));
    assert(roundtrip.workflows[0].recording);
    assert(roundtrip.workflows[1].recordingPartOf=="sample-recording");
    assert(roundtrip.layers[0].keys[1].playbackMode=="random");
    size_t recordedSteps=0;
    for(const auto& part:roundtrip.workflows)if(part.recordingPartOf=="sample-recording")recordedSteps+=part.steps.size();
    assert(recordedSteps==989);
    std::cout<<"workflow storage tests passed\n";
}
