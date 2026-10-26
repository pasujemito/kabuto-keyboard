#include "home_wifi.h"
#include "config.h"
#include "update_logic.h"   // wifiJoinProblem
#include <WiFi.h>
#include <ESPmDNS.h>
#include <Preferences.h>

namespace {

const char* PREFS = "update";          // 1.14.x saved the Wi-Fi here; keep reading it
const uint32_t JOIN_TIMEOUT_MS = 20000;
const uint32_t RETRY_MS = 30000;       // stay connected: rejoin attempts after a drop

SemaphoreHandle_t lock_ = nullptr;     // guards error_, read by the web server
String error_;
volatile uint8_t joinReason_ = 0;      // last disconnect reason, from the Wi-Fi event task
volatile bool applyRequested_ = false; // settings changed; applied on the next tick
bool stay_ = false, mdnsUp_ = false, attempted_ = false;
uint32_t lastAttempt_ = 0;

void setError(const String& e) { xSemaphoreTake(lock_, portMAX_DELAY); error_ = e; xSemaphoreGive(lock_); }

void readSettings(String& ssid, String& pass, bool& stay) {
    Preferences p; p.begin(PREFS, true);
    ssid = p.getString("ssid", ""); pass = p.getString("pass", ""); stay = p.getBool("stay", false);
    p.end();
}

void startJoin(const String& ssid, const String& pass) {
    // AP+STA: the setup hotspot stays up, but it follows the router's channel,
    // so a phone on it may drop for a moment while the pad joins.
    WiFi.setHostname(MDNS_NAME);
    WiFi.mode(WIFI_AP_STA);
    joinReason_ = 0;
    WiFi.begin(ssid.c_str(), pass.c_str());
}

String explainFailure(const String& ssid, bool scan) {
    uint8_t reason = joinReason_;
    String err = "Couldn't join \"" + ssid + "\": " + wifiJoinProblem(reason).c_str();
    if (scan && reason == 201) {
        // A visible network whose name differs only in capitals is the usual typo.
        WiFi.disconnect();
        for (int i = 0, n = WiFi.scanNetworks(); i < n; ++i)
            if (WiFi.SSID(i) != ssid && WiFi.SSID(i).equalsIgnoreCase(ssid)) { err += ". Did you mean \"" + WiFi.SSID(i) + "\"?"; break; }
        WiFi.scanDelete();
    }
    return err;
}

void leave() {
    if (mdnsUp_) { MDNS.end(); mdnsUp_ = false; }
    WiFi.disconnect(true);   // station off; the setup hotspot keeps running
    WiFi.mode(WIFI_AP);
}

}  // namespace

void homeWifiBegin() {
    lock_ = xSemaphoreCreateMutex();
    WiFi.onEvent([](WiFiEvent_t, WiFiEventInfo_t info) { joinReason_ = info.wifi_sta_disconnected.reason; },
                 ARDUINO_EVENT_WIFI_STA_DISCONNECTED);
    applyRequested_ = true;   // join at boot if staying connected
}

void homeWifiTick() {
    if (applyRequested_) {
        applyRequested_ = false;
        String ssid, pass; bool stay;
        readSettings(ssid, pass, stay);
        bool wasStaying = stay_;
        stay_ = stay && ssid.length();
        attempted_ = false;
        if (wasStaying && !stay_) leave();
        else if (stay_ && WiFi.status() == WL_CONNECTED) WiFi.disconnect();   // rejoin with the new settings
    }
    if (!stay_) return;
    if (WiFi.status() == WL_CONNECTED) {
        if (!mdnsUp_ && (mdnsUp_ = MDNS.begin(MDNS_NAME))) {
            MDNS.addService("http", "tcp", 80);
            Serial.printf("[wifi] on home Wi-Fi as %s, http://%s.local\n", WiFi.localIP().toString().c_str(), MDNS_NAME);
        }
        setError("");
        return;
    }
    if (attempted_ && millis() - lastAttempt_ < RETRY_MS) return;
    String ssid, pass; bool stay;
    readSettings(ssid, pass, stay);
    if (attempted_) setError(explainFailure(ssid, false));
    startJoin(ssid, pass);
    lastAttempt_ = millis(); attempted_ = true;
}

bool homeWifiAcquire(String& err) {
    if (WiFi.status() == WL_CONNECTED) return true;
    String ssid, pass; bool stay;
    readSettings(ssid, pass, stay);
    if (!ssid.length()) { err = "Add your home Wi-Fi to check for updates"; return false; }
    startJoin(ssid, pass);
    for (uint32_t start = millis(); millis() - start < JOIN_TIMEOUT_MS;) {
        if (WiFi.status() == WL_CONNECTED) { setError(""); return true; }
        vTaskDelay(pdMS_TO_TICKS(250));
    }
    err = explainFailure(ssid, true);
    setError(err);
    return false;
}

void homeWifiRelease() {
    if (!stay_) leave();
}

String homeWifiSsid() {
    Preferences p; p.begin(PREFS, true);
    String ssid = p.getString("ssid", "");
    p.end();
    return ssid;
}

void homeWifiWriteStatus(JsonDocument& d) {
    String ssid, pass; bool stay;
    readSettings(ssid, pass, stay);
    bool up = WiFi.status() == WL_CONNECTED;
    d["ssid"] = ssid;   // the password is never sent back
    d["stay"] = stay;
    d["connected"] = up;
    d["ip"] = up ? WiFi.localIP().toString() : String();
    d["address"] = "http://" MDNS_NAME ".local";
    xSemaphoreTake(lock_, portMAX_DELAY); d["error"] = error_; xSemaphoreGive(lock_);
}

void homeWifiSave(const String& ssid, const String* password, bool stay) {
    Preferences p; p.begin(PREFS, false);
    p.putString("ssid", ssid);
    if (password) p.putString("pass", *password);
    p.putBool("stay", stay);
    p.end();
    setError("");
    applyRequested_ = true;
}
