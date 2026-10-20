#include "web_server.h"
#include "config.h"
#include "storage.h"
#include "macro_engine.h"
#include "hid_keyboard.h"
#include "keymap.h"
#include <WiFi.h>
#include <LittleFS.h>
#include <ESPAsyncWebServer.h>
#include <ArduinoJson.h>

static AsyncWebServer server(80);
static bool active_ = false;
static volatile bool recorderActive_ = false;
static volatile uint32_t recorderHeartbeatMs_ = 0;

bool webServerRecorderActive() {
    return recorderActive_ && (uint32_t)(millis() - recorderHeartbeatMs_) < 2500;
}

// Live debounced physical key state + diagnostics, defined in main.cpp.
extern volatile bool     g_keyLive[];
extern volatile uint32_t g_keyMask;
extern volatile int      g_lastKeyDown;
extern volatile uint32_t g_keyDownCount;

static void sendJson(AsyncWebServerRequest* req, int code, const String& body) {
    AsyncWebServerResponse* r = req->beginResponse(code, "application/json", body);
    r->addHeader("Cache-Control", "no-store");
    req->send(r);
}

static void handleGetConfig(AsyncWebServerRequest* req) {
    if (!LittleFS.exists(MACRO_FILE)) { sendJson(req, 200, "{\"version\":1,\"layers\":[]}"); return; }
    // Stream from flash: recordings make this file large, and copying it into
    // RAM can fail on a busy heap, sending the editor a truncated config.
    AsyncWebServerResponse* r = req->beginResponse(LittleFS, MACRO_FILE, "application/json");
    r->addHeader("Cache-Control", "no-store");
    req->send(r);
}

static void handleStorage(AsyncWebServerRequest* req) {
    StorageInfo info = storageInfo();
    JsonDocument d;
    d["fsTotal"]     = (uint32_t)info.totalBytes;
    d["fsUsed"]      = (uint32_t)info.usedBytes;
    d["configBytes"] = (uint32_t)info.configBytes;
    d["maxConfig"]   = MAX_CONFIG_BYTES;
    d["heapSize"]    = ESP.getHeapSize();
    d["heapFree"]    = ESP.getFreeHeap();
    d["heapLargest"] = ESP.getMaxAllocHeap();
    String out; serializeJson(d, out);
    sendJson(req, 200, out);
}

static void handleStatus(AsyncWebServerRequest* req) {
    JsonDocument d;
    d["firmware"]    = FIRMWARE_VERSION;
    d["connected"]   = Keyboard.isConnected();
    d["bonds"]       = Keyboard.bondCount();
    d["running"]     = Macros.isRunning();
    d["runningKey"]  = Macros.runningKey();
    d["activeLayer"] = Macros.activeLayer();
    d["layerCount"]  = (int)Macros.config().layers.size();
    // Physical key diagnostics for the live monitor.
    d["keyMask"]      = (uint32_t)g_keyMask;      // bitmask of keys down now
    d["lastKeyDown"]  = (int)g_lastKeyDown;       // last key index pressed
    d["keyDownCount"] = (uint32_t)g_keyDownCount; // total presses since boot
    String out; serializeJson(d, out);
    sendJson(req, 200, out);
}

static const char* stepTypeName(StepType type) {
    switch (type) {
        case StepType::KEY:        return "key";
        case StepType::KEY_DOWN:   return "down";
        case StepType::KEY_UP:     return "up";
        case StepType::TEXT:       return "text";
        case StepType::CONSUMER:   return "media";
        case StepType::DELAY:      return "delay";
        case StepType::LOOP_START: return "loop-start";
        case StepType::LOOP_END:   return "loop-end";
        case StepType::LAYER:      return "layer";
        case StepType::MOVE:       return "move";
        case StepType::COMBAT:     return "combat";
        case StepType::UTILITIES:  return "utilities";
        case StepType::CALL:       return "call";
        case StepType::RANDOM:     return "random";
    }
    return "unknown";
}

static bool queueLiveEvent(JsonObjectConst event) {
    String type = event["ev"] | "";
    String key = event["key"] | "";
    String mod = event["mod"] | "";
    String media = event["media"] | "";
    if (type == "down") return Macros.post(EngineCmd::LIVE_DOWN, keycodeFromName(key), 0);
    if (type == "up") return Macros.post(EngineCmd::LIVE_UP, keycodeFromName(key), 0);
    if (type == "moddown") return Macros.post(EngineCmd::LIVE_MODDOWN, 0, modifierFromName(mod));
    if (type == "modup") return Macros.post(EngineCmd::LIVE_MODUP, 0, modifierFromName(mod));
    if (type == "media") return Macros.post(EngineCmd::LIVE_MEDIA, consumerFromName(media), 0);
    if (type == "releaseall") return Macros.post(EngineCmd::LIVE_RELEASEALL, 0, 0);
    if (type == "text") return Macros.postText((event["text"] | ""));
    return false;
}

static void handleMacroLog(AsyncWebServerRequest* req) {
    MacroLogEntry entries[24];
    size_t count = Macros.copyLog(entries, 24);
    JsonDocument d;
    d["running"] = Macros.isRunning();
    d["runningKey"] = Macros.runningKey();
    d["elapsedMs"] = Macros.elapsedMs();
    JsonArray events = d["events"].to<JsonArray>();
    for (size_t index = 0; index < count; index++) {
        const MacroLogEntry& entry = entries[index];
        JsonObject event = events.add<JsonObject>();
        event["id"] = entry.id;
        event["elapsedMs"] = entry.elapsedMs;
        event["durationMs"] = entry.durationMs;
        event["run"] = entry.run;
        event["pass"] = entry.pass;
        event["step"] = entry.step;
        event["type"] = stepTypeName(entry.type);
        event["key"] = keyNameFromCode(entry.keycode);
        event["mods"] = entry.modifiers;
        event["value"] = entry.value;
        event["complete"] = entry.complete;
        if (entry.text[0]) event["text"] = entry.text;
        if (entry.loopPath[0]) event["loop"] = entry.loopPath;
        if (entry.type == StepType::CONSUMER)
            event["media"] = consumerNameFromUsage(entry.value);
    }
    String out; serializeJson(d, out);
    sendJson(req, 200, out);
}

static void handleMeta(AsyncWebServerRequest* req) {
    JsonDocument d;
    d["firmware"]  = FIRMWARE_VERSION;
    d["keyCount"]  = KEY_COUNT;
    d["rows"]      = MATRIX_ROWS;
    d["cols"]      = MATRIX_COLS;
    d["maxLayers"] = MAX_LAYERS;
    d["maxSteps"]  = MAX_MACRO_STEPS;
    JsonArray mods = d["modifiers"].to<JsonArray>();
    for (const char* m : {"ctrl","shift","alt","gui","rctrl","rshift","altgr","rgui"}) mods.add(m);
    JsonArray media = d["media"].to<JsonArray>();
    for (const char* m : {"PLAY","NEXT","PREV","STOP","MUTE","VOLUP","VOLDOWN"}) media.add(m);
    JsonArray keys = d["keys"].to<JsonArray>();
    for (char c = 'A'; c <= 'Z'; c++) keys.add(String(c));
    for (char c = '0'; c <= '9'; c++) keys.add(String(c));
    for (const char* k : {"ENTER","ESC","BACKSPACE","TAB","SPACE","CAPS","INSERT",
                          "DELETE","HOME","END","PAGEUP","PAGEDOWN","UP","DOWN",
                          "LEFT","RIGHT","PRINTSCREEN","F1","F2","F3","F4","F5",
                          "F6","F7","F8","F9","F10","F11","F12"}) keys.add(k);
    String out; serializeJson(d, out);
    sendJson(req, 200, out);
}

void webServerBegin() {
    WiFi.mode(WIFI_AP);
    WiFi.softAP(AP_SSID, AP_PASSWORD, AP_CHANNEL);
    delay(100);

    // Static SPA from LittleFS; API requests must reach their route handlers.
    server.serveStatic("/", LittleFS, "/")
        .setDefaultFile("index.html")
        .setFilter([](AsyncWebServerRequest* req) {
            return !req->url().startsWith("/api/");
        });

    server.on("/api/meta",   HTTP_GET, handleMeta);
    server.on("/api/status", HTTP_GET, handleStatus);
    server.on("/api/storage", HTTP_GET, handleStorage);
    server.on("/api/recording", HTTP_POST, [](AsyncWebServerRequest* req) {
        recorderActive_ = req->hasParam("active") && req->getParam("active")->value() == "1";
        recorderHeartbeatMs_ = millis();
        sendJson(req, 200, "{\"ok\":true}");
    });
    server.on("/api/log", HTTP_GET, handleMacroLog);
    server.on("/api/log/clear", HTTP_POST, [](AsyncWebServerRequest* req) {
        Macros.clearLog();
        sendJson(req, 200, "{\"ok\":true}");
    });
    server.on("/api/config", HTTP_GET, handleGetConfig);

    // Live physical key state for the key tester: {"keys":[false,true,...]}
    server.on("/api/keys", HTTP_GET, [](AsyncWebServerRequest* req) {
        String out = "{\"keys\":[";
        for (int i = 0; i < KEY_COUNT; i++) {
            if (i) out += ",";
            out += g_keyLive[i] ? "true" : "false";
        }
        out += "]}";
        sendJson(req, 200, out);
    });

    // Save full config JSON (body = JSON). The body is streamed to a temp file
    // instead of RAM, then validated and swapped in; the engine reloads after.
    server.on("/api/config", HTTP_POST,
        [](AsyncWebServerRequest* req) {},
        nullptr,
        [](AsyncWebServerRequest* req, uint8_t* data, size_t len, size_t index, size_t total) {
            static File upload;
            static bool writeFailed = false;
            if (index == 0) {
                if (upload) upload.close();
                writeFailed = false;
                if (total <= MAX_CONFIG_BYTES) upload = LittleFS.open(MACRO_TMP_FILE, "w");
                if (!upload) writeFailed = true;
            }
            if (!writeFailed && upload.write(data, len) != len) writeFailed = true;
            if (index + len != total) return;
            if (upload) upload.close();

            String err;
            int code = 400;
            if (total > MAX_CONFIG_BYTES) {
                err = "config too large"; code = 413;
            } else if (writeFailed) {
                err = "cannot write config (flash full?)"; code = 507;
                LittleFS.remove(MACRO_TMP_FILE);
            } else if (commitConfigFile(MACRO_TMP_FILE, err)) {
                Macros.post(EngineCmd::RELOAD);  // reload on the engine task
                sendJson(req, 200, "{\"ok\":true}");
                return;
            }
            JsonDocument d; d["ok"] = false; d["error"] = err;
            String out; serializeJson(d, out);
            sendJson(req, code, out);
        });

    // Trigger a macro for testing: /api/test?layer=0&key=2
    server.on("/api/test", HTTP_POST, [](AsyncWebServerRequest* req) {
        int layer = req->hasParam("layer") ? req->getParam("layer")->value().toInt() : Macros.activeLayer();
        int key   = req->hasParam("key")   ? req->getParam("key")->value().toInt()   : -1;
        if (!Keyboard.isConnected()) { sendJson(req, 409, "{\"ok\":false,\"error\":\"not connected to a host\"}"); return; }
        if (key < 0 || key >= KEY_COUNT) { sendJson(req, 400, "{\"ok\":false,\"error\":\"bad key\"}"); return; }
        Macros.post(EngineCmd::TEST, layer, key);   // run one pass on the engine task
        sendJson(req, 200, "{\"ok\":true}");
    });

    // Run-mode press/release from the grid: drives a pad key with its real
    // trigger behaviour (tap once / toggle / hold).
    server.on("/api/press", HTTP_POST, [](AsyncWebServerRequest* req) {
        int layer = req->hasParam("layer") ? req->getParam("layer")->value().toInt() : Macros.activeLayer();
        int key   = req->hasParam("key")   ? req->getParam("key")->value().toInt()   : -1;
        if (!Keyboard.isConnected()) { sendJson(req, 409, "{\"ok\":false,\"error\":\"not connected to a host\"}"); return; }
        if (key < 0 || key >= KEY_COUNT) { sendJson(req, 400, "{\"ok\":false,\"error\":\"bad key\"}"); return; }
        Macros.post(EngineCmd::KEYDOWN, key, layer);
        sendJson(req, 200, "{\"ok\":true}");
    });
    server.on("/api/release", HTTP_POST, [](AsyncWebServerRequest* req) {
        int layer = req->hasParam("layer") ? req->getParam("layer")->value().toInt() : Macros.activeLayer();
        int key   = req->hasParam("key")   ? req->getParam("key")->value().toInt()   : -1;
        if (key < 0 || key >= KEY_COUNT) { sendJson(req, 400, "{\"ok\":false,\"error\":\"bad key\"}"); return; }
        Macros.post(EngineCmd::KEYUP, key, layer);
        sendJson(req, 200, "{\"ok\":true}");
    });

    server.on("/api/stop", HTTP_POST, [](AsyncWebServerRequest* req) {
        Macros.post(EngineCmd::STOP);
        sendJson(req, 200, "{\"ok\":true}");
    });

    server.on("/api/layer", HTTP_POST, [](AsyncWebServerRequest* req) {
        int layer = req->hasParam("n") ? req->getParam("n")->value().toInt() : 0;
        Macros.post(EngineCmd::LAYER, layer);
        sendJson(req, 200, "{\"ok\":true}");
    });

    // Must be registered before /api/live, which also matches /api/live/* paths.
    server.on("/api/live/batch", HTTP_POST,
        [](AsyncWebServerRequest* req) {},
        nullptr,
        [](AsyncWebServerRequest* req, uint8_t* data, size_t len, size_t index, size_t total) {
            static String body;
            if (index == 0) body = "";
            body.concat((const char*)data, len);
            if (index + len != total) return;
            if (!Keyboard.isConnected()) {
                sendJson(req, 409, "{\"ok\":false,\"error\":\"not connected to a host\"}");
                body = "";
                return;
            }
            JsonDocument doc;
            DeserializationError error = deserializeJson(doc, body);
            JsonArrayConst events = doc.as<JsonArrayConst>();
            if (error || events.isNull() || events.size() > 24) {
                sendJson(req, 400, "{\"ok\":false,\"error\":\"invalid live event batch\"}");
                body = "";
                return;
            }
            bool queued = true;
            for (JsonObjectConst event : events)
                if (!queueLiveEvent(event)) { queued = false; break; }
            sendJson(req, queued ? 200 : 503,
                     queued ? "{\"ok\":true}" : "{\"ok\":false,\"error\":\"live queue full\"}");
            body = "";
        });

    // Live passthrough while recording: /api/live?ev=down&key=W etc.
    // Sends the key to the paired host in real time so you can see behaviour.
    server.on("/api/live", HTTP_POST, [](AsyncWebServerRequest* req) {
        if (!Keyboard.isConnected()) { sendJson(req, 409, "{\"ok\":false,\"error\":\"not connected to a host\"}"); return; }
        String ev  = req->hasParam("ev")    ? req->getParam("ev")->value()    : "";
        String key = req->hasParam("key")   ? req->getParam("key")->value()   : "";
        String mod = req->hasParam("mod")   ? req->getParam("mod")->value()   : "";
        String med = req->hasParam("media") ? req->getParam("media")->value() : "";
        String text = req->hasParam("text") ? req->getParam("text")->value() : "";
        if (ev == "down")           Macros.post(EngineCmd::LIVE_DOWN,  keycodeFromName(key), 0);
        else if (ev == "up")        Macros.post(EngineCmd::LIVE_UP,    keycodeFromName(key), 0);
        else if (ev == "moddown")   Macros.post(EngineCmd::LIVE_MODDOWN, 0, modifierFromName(mod));
        else if (ev == "modup")     Macros.post(EngineCmd::LIVE_MODUP,   0, modifierFromName(mod));
        else if (ev == "media")     Macros.post(EngineCmd::LIVE_MEDIA, consumerFromName(med), 0);
        else if (ev == "releaseall")Macros.post(EngineCmd::LIVE_RELEASEALL, 0, 0);
        else if (ev == "text")      Macros.postText(text.c_str());
        else { sendJson(req, 400, "{\"ok\":false,\"error\":\"bad ev\"}"); return; }
        sendJson(req, 200, "{\"ok\":true}");
    });

    server.on("/api/bonds/clear", HTTP_POST, [](AsyncWebServerRequest* req) {
        Keyboard.clearBonds();
        sendJson(req, 200, "{\"ok\":true}");
    });

    server.onNotFound([](AsyncWebServerRequest* req) {
        // SPA fallback
        if (LittleFS.exists("/index.html"))
            req->send(LittleFS, "/index.html", "text/html");
        else
            req->send(404, "text/plain", "not found");
    });

    server.begin();
    active_ = true;
}

bool webServerActive() { return active_; }
