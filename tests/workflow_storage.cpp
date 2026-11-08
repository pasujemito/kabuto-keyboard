#include <Arduino.h>
#include <LittleFS.h>
#include "../src/storage.h"
#include "../src/stats_logic.h"
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
                      R"("edge_margin":0.12,"stuck_after_ms":20000,"face_mobs":true,"smart":true,"home_range":0.1,"home_at":0.425,"auto_pause":0.3,"approach":true,"walk_hold":[300,700],"glide":0.6,"attack":false,"potions":[{"id":"mana","key":"V","below":35,"bar_max":5000,"per_tap":800,"every_ms":[1000,2000],"backup_keys":["B",{"key":"N","per_tap":300}]}],"skills":[{"id":"s","key":"Q","chance":0.5,"cooldown_ms":3000}]}}]}]}]})");
    assert(saveRawJson(customKeys,err));assert(loadConfig(cfg));assert(saveConfig(cfg));assert(loadConfig(roundtrip));
    pattern=roundtrip.layers[0].keys[0].steps[0].pattern();
    assert(pattern->jump.keycode==0x2C&&!pattern->jump.mods&&pattern->attack.keycode==0x1B&&pattern->left.keycode==0x04&&pattern->right.keycode==0x07);
    assert(pattern->potions.size()==1&&pattern->potions[0].id=="mana"&&pattern->potions[0].cooldown.max==2000&&pattern->potions[0].chancePermille==1000);
    assert(pattern->potions[0].belowPercent==35&&pattern->potions[0].barMax==5000&&pattern->potions[0].perTap==800);
    assert(pattern->potions[0].backupKeys.size()==2&&pattern->potions[0].backupKeys[0]==0x05&&pattern->potions[0].backupKeys[1]==0x11);   // B, N
    assert(pattern->potions[0].backupPerTap.size()==2&&pattern->potions[0].backupPerTap[0]==0&&pattern->potions[0].backupPerTap[1]==300);
    {std::string saved=readRawJson();assert(saved.find("{\"key\":\"N\",\"per_tap\":300}")!=std::string::npos);}
    assert(pattern->edgeMarginPermille==120&&pattern->stuckAfterMs==20000&&pattern->faceMobs&&pattern->smart&&pattern->homeRangePermille==100);
    assert(pattern->autoPausePermille==300&&pattern->approach&&pattern->walkHold.min==300&&pattern->walkHold.max==700&&pattern->glidePermille==600&&!pattern->attacking);
    {std::string saved=readRawJson();assert(saved.find("home_at")==std::string::npos);}   // 1.18.6's home_at: loads, ignored, dropped
    assert(pattern->skills[0].keycode==0x14&&pattern->skills[0].cooldown.min==3000&&pattern->skills[0].chancePermille==500);
    {std::string saved=readRawJson();assert(saved.find("\"jump\":\"SPACE\"")!=std::string::npos&&saved.find("\"every_ms\"")!=std::string::npos);}
    // Presets saved with the old batch keys keep their values and are rewritten with the new names.
    String legacyJson(R"({"layers":[{"keys":[{"steps":[{"type":"dynamic","pattern":{"id":"old","combos_per_side":[3,4],"sides":[5,6],"skills":[]}}]}]}]})");
    assert(saveRawJson(legacyJson,err));assert(loadConfig(cfg));
    pattern=cfg.layers[0].keys[0].steps[0].pattern();
    assert(pattern&&pattern->attacksPerSet.min==3&&pattern->attacksPerSet.max==4&&pattern->sets.min==5&&pattern->sets.max==6);
    assert(!pattern->autoPausePermille&&!pattern->approach&&pattern->walkHold.min==280&&pattern->walkHold.max==650&&!pattern->glidePermille&&pattern->attacking);   // saved before these: off, default strides, attacking
    assert(saveConfig(cfg));
    {std::string saved=readRawJson();assert(saved.find("\"attacks_per_set\"")!=std::string::npos&&saved.find("sides")==std::string::npos);}
    assert(pattern->tempoDriftPermille==0); // absent in older presets: no drift
    assert(pattern->jump.mods==0x04&&pattern->right.keycode==0x4F&&pattern->potions.empty());   // ...and the original keys
    assert(!pattern->edgeMarginPermille&&!pattern->stuckAfterMs&&!pattern->faceMobs);           // ...and no screen awareness
    String drifting(R"({"layers":[{"keys":[{"steps":[{"type":"dynamic","pattern":{"id":"d","tempo_drift":0.15,"skills":[]}}]}]}]})");
    assert(saveRawJson(drifting,err));assert(loadConfig(cfg));assert(saveConfig(cfg));assert(loadConfig(roundtrip));
    assert(roundtrip.layers[0].keys[0].steps[0].pattern()->tempoDriftPermille==150);
    // Screen reader keys on the pad: "tool" steps keep their key; unknown keys are refused.
    String tools(R"J({"layers":[{"keys":[{"steps":[{"type":"call","workflow":"m"}]}]}],"workflows":[{"id":"m","name":"Mark (F8)","steps":[{"type":"tool","key":"mark"}]},{"id":"h","steps":[{"type":"tool","key":"hide"}]}]})J");
    assert(saveRawJson(tools,err));assert(loadConfig(cfg));
    assert(cfg.workflows[0].steps[0].type==StepType::TOOL&&cfg.workflows[0].steps[0].value==TOOL_MARK&&cfg.workflows[1].steps[0].value==TOOL_HIDE);
    assert(saveConfig(cfg));{std::string saved=readRawJson();assert(saved.find("{\"type\":\"tool\",\"key\":\"mark\"}")!=std::string::npos);}
    {std::string before=readRawJson();
     assert(!saveRawJson(String(R"({"layers":[],"workflows":[{"id":"m","steps":[{"type":"tool","key":"f8"}]}]})"),err)&&readRawJson()==before);}
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
      R"({"id":"p","potions":[{"id":"hp","key":"C","every_ms":[70000,40000]}],"skills":[]})",
      R"({"id":"p","potions":[{"id":"hp","key":"C","below":101}],"skills":[]})",
      R"({"id":"p","potions":[{"id":"hp","key":"C","below":-5}],"skills":[]})",
      R"({"id":"p","potions":[{"id":"hp","key":"C","bar_max":5000}],"skills":[]})",
      R"({"id":"p","potions":[{"id":"hp","key":"C","bar_max":500,"per_tap":800}],"skills":[]})",
      R"({"id":"p","potions":[{"id":"hp","key":"C","bar_max":20000000,"per_tap":800}],"skills":[]})",
      R"({"id":"p","edge_margin":0.5,"skills":[]})",
      R"({"id":"p","stuck_after_ms":1000,"skills":[]})",
      R"({"id":"p","face_mobs":"yes","skills":[]})",
      R"({"id":"p","smart":1,"skills":[]})",
      R"({"id":"p","home_range":0.6,"skills":[]})",
      R"({"id":"p","auto_pause":0.95,"skills":[]})",
      R"({"id":"p","approach":"yes","skills":[]})",
      R"({"id":"p","walk_hold":[20,400],"skills":[]})",
      R"({"id":"p","walk_hold":[400,300],"skills":[]})",
      R"({"id":"p","walk_hold":[300,6000],"skills":[]})",
      R"({"id":"p","glide":1.5,"skills":[]})",
      R"({"id":"p","glide":true,"skills":[]})",
      R"({"id":"p","attack":"no","skills":[]})",
      R"({"id":"p","potions":[{"id":"hp","key":"C","backup_keys":["C"]}],"skills":[]})",
      R"({"id":"p","potions":[{"id":"hp","key":"C","backup_keys":["B","B"]}],"skills":[]})",
      R"({"id":"p","potions":[{"id":"hp","key":"C","backup_keys":["B","N","M","K"]}],"skills":[]})",
      R"({"id":"p","potions":[{"id":"hp","key":"C","backup_keys":["LEFT"]}],"skills":[]})",
      R"({"id":"p","potions":[{"id":"hp","key":"C","backup_keys":"B"}],"skills":[]})",
      R"({"id":"p","potions":[{"id":"hp","key":"C","backup_keys":[{"key":"B","per_tap":300}]}],"skills":[]})",
      R"({"id":"p","potions":[{"id":"hp","key":"C","bar_max":1000,"per_tap":500,"backup_keys":[{"key":"B","per_tap":2000}]}],"skills":[]})",
      R"({"id":"p","potions":[{"id":"hp","key":"C","bar_max":1000,"per_tap":500,"backup_keys":[{"key":"B","per_tap":"x"}]}],"skills":[]})"
    };
    for(auto bad:badPatterns){
      String raw(std::string("{\"layers\":[{\"keys\":[{\"steps\":[{\"type\":\"dynamic\",\"pattern\":")+bad+"}]}]}]}");
      assert(!saveRawJson(raw,err));assert(readRawJson()==good);assert(!LittleFS.exists(MACRO_TMP_FILE));
    }
    // Characters: keys, potions and skills set once; patterns take them with char_* flags.
    {String withCharacters(R"({"active_character":"mage","characters":[)"
        R"({"id":"war","name":"Warrior","keys":{"jump":"SPACE","attack":"X","left":"LEFT","right":"RIGHT"},"potions":[{"id":"hp","key":"C","below":40,"backup_keys":[{"key":"B","per_tap":0}]}],"skills":[{"id":"rage","key":"Q","chance":1,"cooldown_ms":[120000,120000]}],"shuffle_skills":false},)"
        R"({"id":"mage","name":"Mage","potions":[{"id":"mana","key":"V","below":30}],"skills":[]}],)"
        R"("layers":[{"keys":[{"steps":[{"type":"dynamic","pattern":{"id":"pp","char_keys":true,"char_potions":true,"skills":[]}}]}]}]})");
     assert(saveRawJson(withCharacters,err));Config c;assert(loadConfig(c));
     assert(c.characters.size()==2&&c.activeCharacter=="mage"&&c.character()->name=="Mage");
     const Character& war=c.characters[0];
     assert(war.name=="Warrior"&&war.jump.keycode==0x2C&&war.potions.size()==1&&war.potions[0].belowPercent==40&&war.potions[0].backupKeys.size()==1);
     assert(war.skills.size()==1&&war.skills[0].keycode==0x14&&!war.shuffleSkills);
     const DynamicPattern* pp=c.layers[0].keys[0].steps[0].pattern();assert(pp->charKeys&&pp->charPotions&&!pp->charSkills);
     DynamicPattern merged=withCharacter(*pp,&war);assert(merged.jump.keycode==0x2C&&merged.potions.size()==1&&merged.skills.empty());
     assert(saveConfig(c));Config again;assert(loadConfig(again));
     assert(again.characters.size()==2&&again.activeCharacter=="mage"&&again.characters[0].potions[0].backupKeys.size()==1&&again.characters[0].skills[0].cooldown.min==120000);
     assert(again.layers[0].keys[0].steps[0].pattern()->charPotions);
     c.activeCharacter="gone";assert(c.character()==&c.characters[0]);   // an unknown one: the first
     Config none;assert(none.character()==nullptr);
     auto kept=readRawJson();
     const char* badCharacters[]={
        R"({"characters":[{"id":"a","potions":[],"skills":[]}],"layers":[]})",                                      // no name
        R"({"characters":[{"id":"a","name":"A","skills":[]},{"id":"a","name":"B","skills":[]}],"layers":[]})",      // same id
        R"({"characters":[{"id":"a","name":"A","keys":{"jump":"ALT","attack":"ALT"},"skills":[]}],"layers":[]})",   // keys clash
        R"({"characters":[{"id":"a","name":"A","skills":[]},{"id":"b","name":"B","skills":[]},{"id":"c","name":"C","skills":[]},{"id":"d","name":"D","skills":[]},{"id":"e","name":"E","skills":[]}],"layers":[]})",
        R"({"characters":{"id":"a"},"layers":[]})",
        R"({"active_character":5,"layers":[]})",
        R"({"layers":[{"keys":[{"steps":[{"type":"dynamic","pattern":{"id":"pp","char_keys":"yes","skills":[]}}]}]}]})"};
     for(auto raw:badCharacters){assert(!saveRawJson(String(raw),err));assert(readRawJson()==kept);}}
    std::cout<<"workflow storage tests passed\n";
}
