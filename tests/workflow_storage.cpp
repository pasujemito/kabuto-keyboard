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
    // Dynamic definitions remain compact and retain every parameter on disk.
    std::ifstream dynamicFile("examples/jump-combat-dynamic.json");assert(dynamicFile);
    std::string fragment((std::istreambuf_iterator<char>(dynamicFile)),std::istreambuf_iterator<char>());
    String dynamicJson(std::string("{\"layers\":[{\"keys\":[")+fragment+"]}]}");
    assert(saveRawJson(dynamicJson,err));assert(loadConfig(cfg));
    const auto* pattern=cfg.layers[0].keys[0].steps[0].pattern();assert(pattern);
    assert(pattern->jumpToAttack.min==45&&pattern->jumpToAttack.max==120);
    assert(pattern->attacksPerSet.min==2&&pattern->sets.max==12&&pattern->turnChancePermille==800);
    assert(pattern->skills.empty()&&pattern->potions.size()==2&&pattern->potions[0].id=="hp"&&pattern->potions[0].keycode==6);
    assert(pattern->potions[0].chancePermille==1000&&pattern->potions[0].cooldown.min==40000&&pattern->potions[1].keycode==0x19);
    assert(pattern->jump.mods==0x04&&pattern->attack.mods==0x01&&pattern->left.keycode==0x50);
    assert(saveConfig(cfg));assert(loadConfig(roundtrip));
    pattern=roundtrip.layers[0].keys[0].steps[0].pattern();
    assert(pattern&&pattern->potions[1].cooldown.max==45000&&pattern->potions[0].after.max==700&&pattern->shuffleSkills);
    // Custom movement keys survive a round trip; potions and skills keep separate shapes.
    String customKeys(R"({"layers":[{"keys":[{"steps":[{"type":"dynamic","pattern":{"id":"k","keys":{"jump":"SPACE","attack":"X","left":"A","right":"D"},)"
                      R"("potions":[{"id":"mana","key":"V","every_ms":[1000,2000]}],"skills":[{"id":"s","key":"Q","chance":0.5,"cooldown_ms":3000}]}}]}]}]})");
    assert(saveRawJson(customKeys,err));assert(loadConfig(cfg));assert(saveConfig(cfg));assert(loadConfig(roundtrip));
    pattern=roundtrip.layers[0].keys[0].steps[0].pattern();
    assert(pattern->jump.keycode==0x2C&&!pattern->jump.mods&&pattern->attack.keycode==0x1B&&pattern->left.keycode==0x04&&pattern->right.keycode==0x07);
    assert(pattern->potions.size()==1&&pattern->potions[0].id=="mana"&&pattern->potions[0].cooldown.max==2000&&pattern->potions[0].chancePermille==1000);
    assert(pattern->skills[0].keycode==0x14&&pattern->skills[0].cooldown.min==3000&&pattern->skills[0].chancePermille==500);
    {std::string saved=readRawJson();assert(saved.find("\"jump\":\"SPACE\"")!=std::string::npos&&saved.find("\"every_ms\"")!=std::string::npos);}
    // Presets saved with the old batch keys keep their values and are rewritten with the new names.
    String legacyJson(R"({"layers":[{"keys":[{"steps":[{"type":"dynamic","pattern":{"id":"old","combos_per_side":[3,4],"sides":[5,6],"skills":[]}}]}]}]})");
    assert(saveRawJson(legacyJson,err));assert(loadConfig(cfg));
    pattern=cfg.layers[0].keys[0].steps[0].pattern();
    assert(pattern&&pattern->attacksPerSet.min==3&&pattern->attacksPerSet.max==4&&pattern->sets.min==5&&pattern->sets.max==6);
    assert(saveConfig(cfg));
    {std::string saved=readRawJson();assert(saved.find("\"attacks_per_set\"")!=std::string::npos&&saved.find("sides")==std::string::npos);}
    assert(pattern->tempoDriftPermille==0); // absent in older presets: no drift
    assert(pattern->jump.mods==0x04&&pattern->right.keycode==0x4F&&pattern->potions.empty());   // ...and the original keys
    String drifting(R"({"layers":[{"keys":[{"steps":[{"type":"dynamic","pattern":{"id":"d","tempo_drift":0.15,"skills":[]}}]}]}]})");
    assert(saveRawJson(drifting,err));assert(loadConfig(cfg));assert(saveConfig(cfg));assert(loadConfig(roundtrip));
    assert(roundtrip.layers[0].keys[0].steps[0].pattern()->tempoDriftPermille==150);
    // A skill's "use again after" is a range; an older single number means a fixed wait.
    String intervals(R"({"layers":[{"keys":[{"steps":[{"type":"dynamic","pattern":{"id":"iv","skills":[{"id":"a","key":"C","cooldown_ms":60000},{"id":"b","key":"H","cooldown_ms":[40000,70000]}]}}]}]}]})");
    assert(saveRawJson(intervals,err));assert(loadConfig(cfg));
    pattern=cfg.layers[0].keys[0].steps[0].pattern();
    assert(pattern->skills[0].cooldown.min==60000&&pattern->skills[0].cooldown.max==60000);
    assert(pattern->skills[1].cooldown.min==40000&&pattern->skills[1].cooldown.max==70000);
    assert(saveConfig(cfg));assert(loadConfig(roundtrip));
    assert(roundtrip.layers[0].keys[0].steps[0].pattern()->skills[1].cooldown.max==70000);
    auto good=readRawJson();
    const char* badPatterns[]={
      R"({"id":"p","jump_to_attack":[121,45],"skills":[]})",
      R"({"id":"p","turn_chance":1.1,"skills":[]})",
      R"({"id":"p","turn_chance":true,"skills":[]})",
      R"({"id":"p","tempo_drift":0.31,"skills":[]})",
      R"({"id":"p","sets":[0,12],"skills":[]})",
      R"({"id":"p","sides":[0,12],"skills":[]})",
      R"({"id":"p","combo_gap":[0,90001],"skills":[]})",
      R"({"id":"p","attack_to_jump_up":[50000,60000],"jump_up_to_attack_up":[50000,60000],"skills":[]})",
      R"({"id":"p","skills":[{"id":"c","key":"LEFT"}]})",
      R"({"id":"p","skills":[{"id":"c","key":"C","cooldown_ms":-1}]})",
      R"({"id":"p","skills":[{"id":"c","key":"C","cooldown_ms":[70000,40000]}]})",
      R"({"id":"p","skills":[{"id":"c","key":"C","cooldown_ms":[0,86400001]}]})",
      R"({"id":"p","skills":[{"id":"c","key":"C","repeats":[0,2]}]})",
      R"({"id":"p","skills":[{"id":"c","key":"C","chance":-0.1}]})",
      R"({"id":"p","skills":[{"id":"c","key":"C"},{"id":"c","key":"H"}]})",
      R"({"id":"p","keys":{"jump":"CTRL"},"skills":[]})",
      R"({"id":"p","keys":{"left":"ALT"},"skills":[]})",
      R"({"id":"p","keys":{"jump":"NOPE"},"skills":[]})",
      R"({"id":"p","keys":"ALT","skills":[]})",
      R"({"id":"p","keys":{"jump":"SPACE"},"skills":[{"id":"s","key":"SPACE"}]})",
      R"({"id":"p","potions":[{"id":"hp","key":"LEFT"}],"skills":[]})",
      R"({"id":"p","potions":[{"id":"elixir","key":"C"}],"skills":[]})",
      R"({"id":"p","potions":[{"id":"hp","key":"C"},{"id":"hp","key":"V"}],"skills":[]})",
      R"({"id":"p","potions":[{"id":"hp","key":"C","every_ms":[70000,40000]}],"skills":[]})"
    };
    for(auto bad:badPatterns){
      String raw(std::string("{\"layers\":[{\"keys\":[{\"steps\":[{\"type\":\"dynamic\",\"pattern\":")+bad+"}]}]}]}");
      assert(!saveRawJson(raw,err));assert(readRawJson()==good);assert(!LittleFS.exists(MACRO_TMP_FILE));
    }
    std::cout<<"workflow storage tests passed\n";
}
