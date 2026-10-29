#include "web_server.h"
#include "config.h"
#include "storage.h"
#include "macro_engine.h"
#include "hid_keyboard.h"
#include "keymap.h"
#include "updater.h"
#include "home_wifi.h"
#include "access.h"
#include "live_stats.h"
#include <WiFi.h>
#include <LittleFS.h>
#include <ESPAsyncWebServer.h>
#include <ArduinoJson.h>
#include <utility>
#include "web_ui.h"   // generated from web/index.html by tools/embed_web_ui.py

static AsyncWebServer server(80);

// The setup hotspot has its own Wi-Fi password, so its clients need no PIN.
// Anyone reaching the pad over your home network must log in with the PIN.
// Both ends must be on the hotspot's /24: the ESP32 accepts packets for any of
// its addresses on any interface, so a home-network device routing to
// 192.168.4.1 through the station link must not pass as a hotspot client.
static bool viaHotspot(AsyncWebServerRequest* req) {
    if (!req->client()) return false;
    IPAddress ap = WiFi.softAPIP(), local = req->client()->localIP(), remote = req->client()->remoteIP();
    return local == ap && remote[0] == ap[0] && remote[1] == ap[1] && remote[2] == ap[2];
}
static bool apiAllowed(AsyncWebServerRequest* req) {
    return viaHotspot(req) ||
           (req->hasHeader("Cookie") && accessSessionValid(req->getHeader("Cookie")->value()));
}
// Every /api route goes through here. The filter runs once the headers are in,
// so a refused request's body never reaches its handler (see onNotFound).
template <typename... Args> static AsyncWebHandler& api(Args&&... args) {
    return server.on(std::forward<Args>(args)...).setFilter(apiAllowed);
}

static volatile bool recorderActive_ = false;
static volatile uint32_t recorderHeartbeatMs_ = 0;

bool webServerRecorderActive() {
    return recorderActive_ && (uint32_t)(millis() - recorderHeartbeatMs_) < 2500;
}

// Physical key diagnostics, defined in main.cpp.
extern volatile uint32_t g_keyMask;
extern volatile int      g_lastKeyDown;
extern volatile uint32_t g_keyDownCount;

// The UI is built into the firmware, so flashing never needs to touch LittleFS.
static void sendWebUi(AsyncWebServerRequest* req) {
    AsyncWebServerResponse* r = req->beginResponse(200, "text/html", WEB_UI_GZ, WEB_UI_GZ_LEN);
    r->addHeader("Content-Encoding", "gzip");
    r->addHeader("Cache-Control", "no-cache");   // pick up a new UI after reflashing
    req->send(r);
}

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

static void handleUpdateStatus(AsyncWebServerRequest* req) {
    JsonDocument d;
    updaterWriteStatus(d);
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
    // Live bars from tools/screen_stats.py, in tenths of a percent (-1: not read).
    LiveStats live = liveStatsSnapshot();
    if (live.hp >= 0 || live.mana >= 0 || live.xp >= 0 || live.x >= 0 || live.state != LIVE_OK) {
        JsonObject l = d["live"].to<JsonObject>();
        l["hp"] = live.hp; l["mana"] = live.mana; l["xp"] = live.xp;
        l["x"] = live.x; l["y"] = live.y; l["mobs"] = live.mobs;
        if (const char* reason = liveStopReason(live.state)) l["stopped"] = reason;
        l["ageMs"] = live.ageMs; l["fresh"] = live.fresh;
        l["xpPerHour"] = live.xpPerHour; l["minutesToLevel"] = live.minutesToLevel; l["levels"] = live.levels;
    }
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
        case StepType::DYNAMIC:    return "dynamic";
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

    server.on("/", HTTP_GET, sendWebUi);   // the page itself holds no secrets
    server.on("/api/login", HTTP_POST, [](AsyncWebServerRequest* req) {
        String err, token = accessLogin(req->hasParam("pin", true) ? req->getParam("pin", true)->value() : String(), err);
        JsonDocument d; d["ok"] = token.length() > 0; if (err.length()) d["error"] = err;
        String out; serializeJson(d, out);
        AsyncWebServerResponse* r = req->beginResponse(token.length() ? 200 : 401, "application/json", out);
        r->addHeader("Cache-Control", "no-store");
        if (token.length()) r->addHeader("Set-Cookie", String(ACCESS_COOKIE "=") + token + "; Path=/; HttpOnly; SameSite=Strict");
        req->send(r);
    });

    api("/api/meta",   HTTP_GET, handleMeta);
    api("/api/status", HTTP_GET, handleStatus);
    api("/api/storage", HTTP_GET, handleStorage);
    api("/api/recording", HTTP_POST, [](AsyncWebServerRequest* req) {
        recorderActive_ = req->hasParam("active") && req->getParam("active")->value() == "1";
        recorderHeartbeatMs_ = millis();
        sendJson(req, 200, "{\"ok\":true}");
    });
    api("/api/log", HTTP_GET, handleMacroLog);
    api("/api/update", HTTP_GET, handleUpdateStatus);
    api("/api/network", HTTP_GET, [](AsyncWebServerRequest* req) {
        JsonDocument d;
        homeWifiWriteStatus(d);
        d["pinSet"] = accessPinSet();
        d["viaHotspot"] = viaHotspot(req);
        String out; serializeJson(d, out);
        sendJson(req, 200, out);
    });
    // Home Wi-Fi settings as a form body. A left-out password or PIN keeps the
    // saved one; staying connected needs a PIN so the network can't use the pad.
    api("/api/network", HTTP_POST, [](AsyncWebServerRequest* req) {
        auto field = [&](const char* name) { return req->hasParam(name, true) ? req->getParam(name, true)->value() : String(); };
        String ssid = field("ssid"), password = field("password"), pin = field("pin");
        bool stay = field("stay") == "1";
        const char* err = nullptr;
        if (pin.length() && !accessSetPin(pin)) err = "The PIN needs 6 to 32 characters";
        else if (stay && !ssid.length()) err = "Add your Wi-Fi name to stay connected";
        else if (stay && !accessPinSet()) err = "Set a PIN to stay connected";
        if (err) {
            JsonDocument d; d["ok"] = false; d["error"] = err;
            String out; serializeJson(d, out);
            sendJson(req, 400, out);
            return;
        }
        homeWifiSave(ssid, req->hasParam("password", true) ? &password : nullptr, stay);
        if (ssid.length()) updaterRequestCheck();
        sendJson(req, 200, "{\"ok\":true}");
    });
    api("/api/update/check", HTTP_POST, [](AsyncWebServerRequest* req) {
        updaterRequestCheck();
        sendJson(req, 200, "{\"ok\":true}");
    });
    api("/api/update/install", HTTP_POST, [](AsyncWebServerRequest* req) {
        String err = updaterRequestInstall(req->hasParam("version") ? req->getParam("version")->value() : String());
        JsonDocument d; d["ok"] = !err.length(); if (err.length()) d["error"] = err;
        String out; serializeJson(d, out);
        sendJson(req, err.length() ? 409 : 200, out);
    });
    // Readings from tools/screen_stats.py as a form body: hp, mana, xp and the
    // minimap x/y in percent (decimals allowed; missing or out of range = not
    // read), map position wx/wy (whole numbers, see stats_logic.h), state
    // (ok/dead/offline) and mobs (L, R, both nearest first: LR or RL, or empty). A state turning bad
    // stops playback at once.
    api("/api/stats", HTTP_POST, [](AsyncWebServerRequest* req) {
        auto field = [&](const char* name) { return req->hasParam(name, true) ? req->getParam(name, true)->value() : String(); };
        if (liveStatsUpdate(statsTenths(field("hp").c_str()), statsTenths(field("mana").c_str()), statsTenths(field("xp").c_str()),
                            statsState(field("state").c_str()), statsTenths(field("x").c_str()), statsTenths(field("y").c_str()),
                            req->hasParam("mobs", true) ? statsMobs(field("mobs").c_str()) : 0, statsPos(field("wx").c_str()), statsPos(field("wy").c_str())))
            Macros.post(EngineCmd::STOP);   // the engine also checks between attacks
        sendJson(req, 200, "{\"ok\":true}");
    });
    api("/api/stats/reset", HTTP_POST, [](AsyncWebServerRequest* req) {
        liveStatsReset();
        sendJson(req, 200, "{\"ok\":true}");
    });
    api("/api/log/clear", HTTP_POST, [](AsyncWebServerRequest* req) {
        Macros.clearLog();
        sendJson(req, 200, "{\"ok\":true}");
    });
    api("/api/config", HTTP_GET, handleGetConfig);

    // Save full config JSON (body = JSON). The body is streamed to a temp file
    // instead of RAM, then validated and swapped in; the engine reloads after.
    api("/api/config", HTTP_POST,
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
    api("/api/test", HTTP_POST, [](AsyncWebServerRequest* req) {
        int layer = req->hasParam("layer") ? req->getParam("layer")->value().toInt() : Macros.activeLayer();
        int key   = req->hasParam("key")   ? req->getParam("key")->value().toInt()   : -1;
        if (!Keyboard.isConnected()) { sendJson(req, 409, "{\"ok\":false,\"error\":\"not connected to a host\"}"); return; }
        if (key < 0 || key >= KEY_COUNT) { sendJson(req, 400, "{\"ok\":false,\"error\":\"bad key\"}"); return; }
        Macros.post(EngineCmd::TEST, layer, key);   // run one pass on the engine task
        sendJson(req, 200, "{\"ok\":true}");
    });

    // Run-mode press/release from the grid: drives a pad key with its real
    // trigger behaviour (tap once / toggle / hold).
    api("/api/press", HTTP_POST, [](AsyncWebServerRequest* req) {
        int layer = req->hasParam("layer") ? req->getParam("layer")->value().toInt() : Macros.activeLayer();
        int key   = req->hasParam("key")   ? req->getParam("key")->value().toInt()   : -1;
        if (!Keyboard.isConnected()) { sendJson(req, 409, "{\"ok\":false,\"error\":\"not connected to a host\"}"); return; }
        if (key < 0 || key >= KEY_COUNT) { sendJson(req, 400, "{\"ok\":false,\"error\":\"bad key\"}"); return; }
        Macros.post(EngineCmd::KEYDOWN, key, layer);
        sendJson(req, 200, "{\"ok\":true}");
    });
    api("/api/release", HTTP_POST, [](AsyncWebServerRequest* req) {
        int layer = req->hasParam("layer") ? req->getParam("layer")->value().toInt() : Macros.activeLayer();
        int key   = req->hasParam("key")   ? req->getParam("key")->value().toInt()   : -1;
        if (key < 0 || key >= KEY_COUNT) { sendJson(req, 400, "{\"ok\":false,\"error\":\"bad key\"}"); return; }
        Macros.post(EngineCmd::KEYUP, key, layer);
        sendJson(req, 200, "{\"ok\":true}");
    });

    api("/api/stop", HTTP_POST, [](AsyncWebServerRequest* req) {
        Macros.post(EngineCmd::STOP);
        sendJson(req, 200, "{\"ok\":true}");
    });

    api("/api/layer", HTTP_POST, [](AsyncWebServerRequest* req) {
        int layer = req->hasParam("n") ? req->getParam("n")->value().toInt() : 0;
        Macros.post(EngineCmd::LAYER, layer);
        sendJson(req, 200, "{\"ok\":true}");
    });

    // Live passthrough while recording: forwards captured keys to the host.
    api("/api/live/batch", HTTP_POST,
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

    server.onNotFound([](AsyncWebServerRequest* req) {
        // SPA fallback. API routes refused by apiAllowed land here too.
        if (!req->url().startsWith("/api/")) {
            if (req->method() == HTTP_GET) sendWebUi(req); else req->send(404, "text/plain", "not found");
        } else if (!apiAllowed(req)) {
            sendJson(req, 401, "{\"ok\":false,\"error\":\"PIN required\"}");
        } else {
            req->send(404, "text/plain", "not found");
        }
    });

    server.begin();
}
