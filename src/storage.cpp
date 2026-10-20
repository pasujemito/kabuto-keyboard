#include "storage.h"
#include "keymap.h"
#include <LittleFS.h>
#include <ArduinoJson.h>
#include <set>

bool storageBegin() {
    if (LittleFS.begin(false)) return true;
    // First boot: format then mount.
    return LittleFS.begin(true);
}

// --- parsing ---------------------------------------------------------------
static uint8_t parseMods(JsonVariantConst v) {
    uint8_t mods = 0;
    if (v.is<JsonArrayConst>()) {
        for (JsonVariantConst m : v.as<JsonArrayConst>())
            mods |= modifierFromName(String(m.as<const char*>()));
    } else if (v.is<const char*>()) {
        // allow "ctrl+shift"
        String s = v.as<const char*>();
        int start = 0;
        while (start < (int)s.length()) {
            int plus = s.indexOf('+', start);
            String tok = (plus < 0) ? s.substring(start) : s.substring(start, plus);
            mods |= modifierFromName(tok);
            if (plus < 0) break;
            start = plus + 1;
        }
    }
    return mods;
}

static bool parseStep(JsonObjectConst o, Step& step) {
    String type = o["type"] | "";
    type.toLowerCase();

    if (type == "key") {
        step.type = StepType::KEY;
        step.keycode = keycodeFromName(String((const char*)(o["key"] | "")));
        step.modifiers = parseMods(o["mods"]);
        step.value = o["hold"] | 0;
        return step.keycode != KC_NONE || step.modifiers != 0;
    }
    if (type == "down") {
        step.type = StepType::KEY_DOWN;
        step.keycode = keycodeFromName(String((const char*)(o["key"] | "")));
        step.modifiers = parseMods(o["mods"]);
        return step.keycode != KC_NONE || step.modifiers != 0;
    }
    if (type == "up") {
        step.type = StepType::KEY_UP;
        step.keycode = keycodeFromName(String((const char*)(o["key"] | "")));
        step.modifiers = parseMods(o["mods"]);   // allow releasing held modifiers
        return true;
    }
    if (type == "text") {
        step.type = StepType::TEXT;
        step.text = (const char*)(o["text"] | "");
        return true;
    }
    if (type == "media") {
        step.type = StepType::CONSUMER;
        step.value = consumerFromName(String((const char*)(o["media"] | "")));
        return step.value != 0;
    }
    if (type == "delay") {
        step.type = StepType::DELAY;
        step.value = o["ms"] | 0;
        return true;
    }
    if (type == "loop") {
        step.type = StepType::LOOP_START;
        step.value = o["count"] | 0;   // 0 = until stopped
        return true;
    }
    if (type == "endloop") {
        step.type = StepType::LOOP_END;
        return true;
    }
    if (type == "layer") {
        step.type = StepType::LAYER;
        step.value = o["layer"] | 0;
        return true;
    }
    if (type == "call") {
        step.type = StepType::CALL;
        step.text = (const char*)(o["workflow"] | "");
        return !step.text.empty();
    }
    if (type == "random") {
        step.type = StepType::RANDOM;
        int recent = o["avoidRecent"] | 0;
        if (recent < 0 || recent > 16) return false;
        step.avoidRecent = recent;
        JsonArrayConst choices = o["choices"].as<JsonArrayConst>();
        for (JsonObjectConst choice : choices) {
            if (step.choices.size() >= MAX_LAYERS * KEY_COUNT + 64) return false;
            MacroRef ref;
            ref.workflow = (const char*)(choice["workflow"] | "");
            int weight = choice["weight"] | 1;
            if (weight < 1 || weight > 1000) return false;
            ref.weight = weight;
            ref.layer = choice["layer"] | MAX_LAYERS;
            ref.key = choice["key"] | KEY_COUNT;
            if (ref.workflow.empty() && (ref.layer >= MAX_LAYERS || ref.key >= KEY_COUNT)) return false;
            step.choices.push_back(ref);
        }
        return !step.choices.empty();
    }
    return false;
}

// Validate new references before replacing the saved file. Existing v1 configs
// with only layer/key random steps remain supported.
static bool validateWorkflows(JsonDocument& doc, String& err) {
    std::set<std::string> ids;
    JsonVariantConst library = doc["workflows"];
    if (!library.isNull() && !library.is<JsonArrayConst>()) {
        err = "workflows must be an array"; return false;
    }
    JsonArrayConst workflows = library.as<JsonArrayConst>();
    if (workflows.size() > 64) { err = "maximum 64 workflows"; return false; }
    for (JsonObjectConst w : workflows) {
        std::string id = w["id"] | "";
        String kind = w["kind"] | "nano";
        if (id.empty() || id.size() > 48 || !ids.insert(id).second ||
            (kind != "nano" && kind != "micro")) {
            err = "workflow IDs must be unique (1-48 characters); kind must be nano or micro";
            return false;
        }
        if (!w["steps"].is<JsonArrayConst>() || w["steps"].size() > MAX_MACRO_STEPS) {
            err = "workflow requires steps (maximum 256)"; return false;
        }
    }
    auto checkSteps = [&](JsonArrayConst steps, bool strict) -> bool {
        int loops = 0;
        for (JsonObjectConst so : steps) {
            String type = so["type"] | "";
            type.toLowerCase();
            if (strict || type == "call" || type == "random") {
                Step step;
                if (!parseStep(so, step)) { err = "invalid workflow step or random choice"; return false; }
                if (step.type == StepType::CALL && !ids.count(step.text)) {
                    err = "call references a missing workflow"; return false;
                }
                for (const auto& ref : step.choices) {
                    if (!ref.workflow.empty() && !ids.count(ref.workflow)) {
                        err = "random choice references a missing workflow"; return false;
                    }
                }
            }
            if (type == "loop") ++loops;
            if (type == "endloop" && --loops < 0 && strict) {
                err = "unbalanced workflow loops"; return false;
            }
        }
        if (strict && loops) { err = "unbalanced workflow loops"; return false; }
        return true;
    };
    for (JsonObjectConst w : workflows)
        if (!checkSteps(w["steps"].as<JsonArrayConst>(), true)) return false;
    for (JsonObjectConst layer : doc["layers"].as<JsonArrayConst>())
        for (JsonObjectConst key : layer["keys"].as<JsonArrayConst>())
            if (!checkSteps(key["steps"].as<JsonArrayConst>(), false)) return false;
    return true;
}

static TriggerMode parseTrigger(const char* s) {
    String t = s ? s : "tap";
    t.toLowerCase();
    if (t == "toggle") return TriggerMode::TOGGLE;
    if (t == "hold")   return TriggerMode::HOLD;
    return TriggerMode::TAP;
}

bool loadConfig(Config& cfg) {
    cfg.layers.clear();
    cfg.workflows.clear();
    File f = LittleFS.open(MACRO_FILE, "r");
    if (!f) { cfg.ensureLayer(0); return false; }

    JsonDocument doc;
    DeserializationError e = deserializeJson(doc, f);
    f.close();
    if (e) { cfg.ensureLayer(0); return false; }

    String validationError;
    if (!validateWorkflows(doc, validationError)) { cfg.ensureLayer(0); return false; }
    for (JsonObjectConst wo : doc["workflows"].as<JsonArrayConst>()) {
        Workflow workflow;
        workflow.id = (const char*)(wo["id"] | "");
        workflow.name = (const char*)(wo["name"] | "");
        workflow.kind = (const char*)(wo["kind"] | "nano");
        for (JsonObjectConst so : wo["steps"].as<JsonArrayConst>()) {
            Step step;
            if (parseStep(so, step)) workflow.steps.push_back(step);
        }
        cfg.workflows.push_back(workflow);
    }
    cfg.randomizedDelay = doc["randomizedDelay"] | true;
    JsonArrayConst layers = doc["layers"].as<JsonArrayConst>();
    for (JsonObjectConst lo : layers) {
        Layer layer;
        layer.name = (const char*)(lo["name"] | "Layer");
        JsonArrayConst keys = lo["keys"].as<JsonArrayConst>();
        int idx = 0;
        for (JsonObjectConst ko : keys) {
            if (idx >= KEY_COUNT) break;
            KeyBinding& kb = layer.keys[idx++];
            kb.name = (const char*)(ko["name"] | "");
            kb.trigger = parseTrigger(ko["trigger"]);
            for (JsonObjectConst so : ko["steps"].as<JsonArrayConst>()) {
                if ((int)kb.steps.size() >= MAX_MACRO_STEPS) break;  // cap per macro
                Step step;
                if (parseStep(so, step)) kb.steps.push_back(step);
            }
        }
        cfg.layers.push_back(layer);
    }
    cfg.ensureLayer(0);
    return true;
}

// --- serializing -----------------------------------------------------------
static void modsToJson(uint8_t mods, JsonArray out) {
    if (mods & KM_LCTRL)  out.add("ctrl");
    if (mods & KM_RCTRL)  out.add("rctrl");
    if (mods & KM_LSHIFT) out.add("shift");
    if (mods & KM_RSHIFT) out.add("rshift");
    if (mods & KM_LALT)   out.add("alt");
    if (mods & KM_RALT)   out.add("altgr");
    if (mods & KM_LGUI)   out.add("gui");
    if (mods & KM_RGUI)   out.add("rgui");
}

static void stepToJson(const Step& s, JsonObject o) {
    switch (s.type) {
        case StepType::KEY:
            o["type"] = "key";
            o["key"]  = keyNameFromCode(s.keycode);
            if (s.modifiers) modsToJson(s.modifiers, o["mods"].to<JsonArray>());
            if (s.value) o["hold"] = s.value;
            break;
        case StepType::KEY_DOWN:
            o["type"] = "down";
            o["key"]  = keyNameFromCode(s.keycode);
            if (s.modifiers) modsToJson(s.modifiers, o["mods"].to<JsonArray>());
            break;
        case StepType::KEY_UP:
            o["type"] = "up";
            o["key"]  = keyNameFromCode(s.keycode);
            if (s.modifiers) modsToJson(s.modifiers, o["mods"].to<JsonArray>());
            break;
        case StepType::TEXT:
            o["type"] = "text";
            o["text"] = s.text;
            break;
        case StepType::CONSUMER:
            o["type"]  = "media";
            o["media"] = consumerNameFromUsage(s.value);
            break;
        case StepType::DELAY:
            o["type"] = "delay";
            o["ms"]   = s.value;
            break;
        case StepType::LOOP_START:
            o["type"]  = "loop";
            o["count"] = s.value;
            break;
        case StepType::LOOP_END:
            o["type"] = "endloop";
            break;
        case StepType::LAYER:
            o["type"]  = "layer";
            o["layer"] = s.value;
            break;
        case StepType::CALL:
            o["type"] = "call";
            o["workflow"] = s.text;
            break;
        case StepType::RANDOM: {
            o["type"] = "random";
            o["avoidRecent"] = s.avoidRecent;
            JsonArray choices = o["choices"].to<JsonArray>();
            for (const MacroRef& ref : s.choices) {
                JsonObject choice = choices.add<JsonObject>();
                if (!ref.workflow.empty()) choice["workflow"] = ref.workflow;
                else { choice["layer"] = ref.layer; choice["key"] = ref.key; }
                choice["weight"] = ref.weight;
            }
            break;
        }
    }
}

static const char* triggerName(TriggerMode t) {
    switch (t) {
        case TriggerMode::TOGGLE: return "toggle";
        case TriggerMode::HOLD:   return "hold";
        default:                  return "tap";
    }
}

static void buildDoc(const Config& cfg, JsonDocument& doc) {
    doc["version"] = cfg.workflows.empty() ? 1 : 2;
    doc["randomizedDelay"] = cfg.randomizedDelay;
    JsonArray workflows = doc["workflows"].to<JsonArray>();
    for (const auto& workflow : cfg.workflows) {
        JsonObject wo = workflows.add<JsonObject>();
        wo["id"] = workflow.id;
        wo["name"] = workflow.name;
        wo["kind"] = workflow.kind;
        JsonArray steps = wo["steps"].to<JsonArray>();
        for (const auto& step : workflow.steps) stepToJson(step, steps.add<JsonObject>());
    }
    JsonArray layers = doc["layers"].to<JsonArray>();
    for (const auto& layer : cfg.layers) {
        JsonObject lo = layers.add<JsonObject>();
        lo["name"] = layer.name;
        JsonArray keys = lo["keys"].to<JsonArray>();
        for (int i = 0; i < KEY_COUNT; i++) {
            const KeyBinding& kb = layer.keys[i];
            JsonObject ko = keys.add<JsonObject>();
            ko["name"] = kb.name;
            ko["trigger"] = triggerName(kb.trigger);
            JsonArray steps = ko["steps"].to<JsonArray>();
            for (const auto& s : kb.steps) stepToJson(s, steps.add<JsonObject>());
        }
    }
}

bool saveConfig(const Config& cfg) {
    JsonDocument doc;
    buildDoc(cfg, doc);
    File f = LittleFS.open(MACRO_FILE, "w");
    if (!f) return false;
    bool ok = serializeJson(doc, f) > 0;
    f.close();
    return ok;
}

bool saveRawJson(const String& json, String& err) {
    JsonDocument doc;
    DeserializationError e = deserializeJson(doc, json);
    if (e) { err = String("invalid json: ") + e.c_str(); return false; }
    if (!doc["layers"].is<JsonArrayConst>()) { err = "missing 'layers' array"; return false; }
    if (!validateWorkflows(doc, err)) return false;
    File f = LittleFS.open(MACRO_FILE, "w");
    if (!f) { err = "cannot open file for writing"; return false; }
    bool ok = serializeJson(doc, f) > 0;
    f.close();
    if (!ok) err = "write failed";
    return ok;
}

String readRawJson() {
    File f = LittleFS.open(MACRO_FILE, "r");
    if (!f) return "";
    String s = f.readString();
    f.close();
    return s;
}

void ensureDefaultConfig() {
    if (LittleFS.exists(MACRO_FILE)) return;
    Config cfg;
    cfg.ensureLayer(0);
    cfg.layers[0].name = "Base";
    // Leave all keys empty by default; the user fills them in via the web UI.
    saveConfig(cfg);
}
