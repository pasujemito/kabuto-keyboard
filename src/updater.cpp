#include "updater.h"
#include "config.h"
#include "update_logic.h"
#include "update_key.h"   // generated from update_public_key.pem by tools/embed_update_key.py
#include "macro_engine.h"
#include "web_server.h"
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <Update.h>
#include <Preferences.h>
#include <esp_ota_ops.h>
#include <mbedtls/md.h>
#include <mbedtls/pk.h>
#include <mbedtls/base64.h>
#include <vector>

// Release files are public GitHub assets. TLS certificates aren't checked:
// every listed version must carry a valid signature from update_public_key.pem
// and the download must match its signed SHA-256 and size, so a tampered list
// or firmware is rejected either way.

namespace {

struct Release { std::string version, date, sha256; uint32_t size; };

const uint32_t FIRST_CHECK_MS = 60000;               // let the pad settle after boot
const uint32_t CHECK_EVERY_MS = 6UL * 60 * 60 * 1000;
const char* PREFS = "update";                        // NVS namespace; not part of macros.json

SemaphoreHandle_t lock_ = nullptr;
volatile uint8_t joinReason_ = 0;   // last station disconnect reason, from the Wi-Fi event task
// Guarded by lock_.
std::vector<Release> releases_;
String state_ = "idle", error_, rolledBack_;
std::string installRequested_, installing_;
uint8_t progress_ = 0;
bool checked_ = false, checkRequested_ = false;
uint32_t lastCheckMs_ = 0;

struct Lock {
    Lock() { xSemaphoreTake(lock_, portMAX_DELAY); }
    ~Lock() { xSemaphoreGive(lock_); }
};

void setState(const char* state, const String& error = "") {
    Lock l; state_ = state; error_ = error;
}

bool verifySignature(const std::string& payload, const char* signatureB64) {
    if (!UPDATE_PUBLIC_KEY[0]) return false;
    uint8_t sig[128]; size_t sigLen = 0;
    if (mbedtls_base64_decode(sig, sizeof(sig), &sigLen, (const uint8_t*)signatureB64, strlen(signatureB64)) != 0)
        return false;
    uint8_t hash[32];
    if (mbedtls_md(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256),
                   (const uint8_t*)payload.data(), payload.size(), hash) != 0) return false;
    mbedtls_pk_context pk;
    mbedtls_pk_init(&pk);
    bool ok = mbedtls_pk_parse_public_key(&pk, (const uint8_t*)UPDATE_PUBLIC_KEY, sizeof(UPDATE_PUBLIC_KEY)) == 0 &&
              mbedtls_pk_verify(&pk, MBEDTLS_MD_SHA256, hash, sizeof(hash), sig, sigLen) == 0;
    mbedtls_pk_free(&pk);
    return ok;
}

bool connectWifi(String& err) {
    Preferences p; p.begin(PREFS, true);
    String ssid = p.getString("ssid", ""), pass = p.getString("pass", "");
    p.end();
    if (!ssid.length()) { err = "Add your home Wi-Fi to check for updates"; return false; }
    if (WiFi.status() == WL_CONNECTED) return true;
    // AP+STA: the setup hotspot stays up, but it follows the router's channel,
    // so a phone on it may drop for a moment while the pad joins.
    WiFi.mode(WIFI_AP_STA);
    joinReason_ = 0;
    WiFi.begin(ssid.c_str(), pass.c_str());
    for (uint32_t start = millis(); millis() - start < 20000;) {
        if (WiFi.status() == WL_CONNECTED) return true;
        vTaskDelay(pdMS_TO_TICKS(250));
    }
    uint8_t reason = joinReason_;
    err = "Couldn't join \"" + ssid + "\": " + wifiJoinProblem(reason).c_str();
    if (reason == 201) {
        // A visible network whose name differs only in capitals is the usual typo.
        WiFi.disconnect();
        for (int i = 0, n = WiFi.scanNetworks(); i < n; ++i)
            if (WiFi.SSID(i) != ssid && WiFi.SSID(i).equalsIgnoreCase(ssid)) { err += ". Did you mean \"" + WiFi.SSID(i) + "\"?"; break; }
        WiFi.scanDelete();
    }
    return false;
}

void disconnectWifi() {
    WiFi.disconnect(true);   // STA off; the setup hotspot keeps running
    WiFi.mode(WIFI_AP);
}

bool beginGet(HTTPClient& http, WiFiClientSecure& client, const String& url, String& err) {
    client.setInsecure();    // authenticity comes from the signatures, see above
    http.setFollowRedirects(HTTPC_FORCE_FOLLOW_REDIRECTS);   // GitHub redirects asset downloads
    http.setUserAgent("Kabuto/" FIRMWARE_VERSION);
    http.setTimeout(15000);
    if (!http.begin(client, url)) { err = "Couldn't reach GitHub"; return false; }
    int code = http.GET();
    if (code == 200) return true;
    err = code == 404 ? String("Not found on GitHub (no release published yet?)")
                      : code < 0 ? String("Couldn't reach GitHub") : "GitHub answered " + String(code);
    http.end();
    return false;
}

bool fetchReleases(std::vector<Release>& out, String& err) {
    WiFiClientSecure client; HTTPClient http;
    if (!beginGet(http, client, String("https://github.com/") + UPDATE_REPO + "/releases/latest/download/versions.json", err))
        return false;
    if (http.getSize() > 32768) { http.end(); err = "Release list too large"; return false; }
    String body = http.getString();
    http.end();
    JsonDocument doc;
    if (deserializeJson(doc, body)) { err = "Release list unreadable"; return false; }
    uint32_t parsed[3];
    for (JsonObjectConst v : doc["versions"].as<JsonArrayConst>()) {
        Release r{v["version"] | "", v["date"] | "", v["sha256"] | "", v["size"] | 0U};
        // Unsigned or malformed entries are never shown, let alone installed.
        if (!parseVersion(r.version, parsed) || !isSha256Hex(r.sha256) || !r.size ||
            !verifySignature(manifestPayload(r.version, r.size, r.sha256), v["signature"] | "")) continue;
        out.push_back(r);
    }
    return true;
}

bool download(const Release& r, String& err) {
    if (!esp_ota_get_next_update_partition(nullptr)) { err = "This flash layout has no room for updates"; return false; }
    WiFiClientSecure client; HTTPClient http;
    if (!beginGet(http, client, String("https://github.com/") + UPDATE_REPO + "/releases/download/v" +
                  r.version.c_str() + "/firmware.bin", err)) return false;
    if (http.getSize() != (int)r.size) { http.end(); err = "Download size doesn't match the signed release"; return false; }
    if (!Update.begin(r.size)) { http.end(); err = String("Can't start the update: ") + Update.errorString(); return false; }
    mbedtls_md_context_t md;
    mbedtls_md_init(&md);
    mbedtls_md_setup(&md, mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), 0);
    mbedtls_md_starts(&md);
    WiFiClient* stream = http.getStreamPtr();
    uint8_t buf[1024];
    uint32_t done = 0, lastData = millis();
    while (done < r.size) {
        size_t want = r.size - done, avail = stream->available();
        if (!avail) {
            if (millis() - lastData > 15000) { err = "Download stalled"; break; }
            vTaskDelay(1);
            continue;
        }
        if (want > avail) want = avail;
        if (want > sizeof(buf)) want = sizeof(buf);
        int n = stream->readBytes(buf, want);
        if (n <= 0) continue;
        lastData = millis();
        mbedtls_md_update(&md, buf, n);
        if (Update.write(buf, n) != (size_t)n) { err = String("Writing failed: ") + Update.errorString(); break; }
        done += n;
        Lock l; progress_ = (uint8_t)((uint64_t)done * 100 / r.size);
    }
    uint8_t hash[32];
    mbedtls_md_finish(&md, hash);
    mbedtls_md_free(&md);
    http.end();
    char hex[65];
    for (int i = 0; i < 32; ++i) snprintf(hex + i * 2, 3, "%02x", hash[i]);
    if (err.length() || r.sha256 != hex) {
        Update.abort();
        if (!err.length()) err = "Download doesn't match the signed checksum";
        return false;
    }
    // Validates the image and makes it the next boot partition.
    if (!Update.end()) { err = String("Update rejected: ") + Update.errorString(); return false; }
    Preferences p; p.begin(PREFS, false);
    p.putBool("trial", true); p.putUChar("tries", 0);
    p.end();
    return true;
}

void runCheck() {
    setState("checking");
    String err;
    std::vector<Release> found;
    bool ok = connectWifi(err) && fetchReleases(found, err);
    disconnectWifi();
    Lock l;
    checked_ = true; lastCheckMs_ = millis();
    if (ok) releases_ = found;
    state_ = ok ? "ready" : "error"; error_ = err;
}

void runInstall(const std::string& version) {
    Release target{};
    {
        Lock l;
        for (const auto& r : releases_) if (r.version == version) target = r;
        installing_ = version; progress_ = 0;
    }
    if (target.version.empty()) { setState("error", "That version is no longer listed"); Lock l; installing_.clear(); return; }
    setState("downloading");
    String err;
    bool ok = connectWifi(err) && download(target, err);
    disconnectWifi();
    if (!ok) { setState("error", err); Lock l; installing_.clear(); return; }
    setState("restarting");
    Serial.printf("[update] installed %s, restarting\n", version.c_str());
    vTaskDelay(pdMS_TO_TICKS(1500));   // let the UI see "restarting"
    ESP.restart();
}

void updaterTask(void*) {
    bool trial;
    { Preferences p; p.begin(PREFS, true); trial = p.getBool("trial", false); p.end(); }
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(1000));
        if (trial && millis() >= UPDATE_HEALTHY_AFTER_MS) {
            // Ran long enough: this version is good, and any rollback notice is stale.
            Preferences p; p.begin(PREFS, false);
            p.putBool("trial", false); p.putUChar("tries", 0); p.remove("badVer");
            p.end();
            trial = false;
            Lock l; rolledBack_ = "";
        }
        if (!UPDATE_PUBLIC_KEY[0]) continue;
        bool check; std::string install;
        {
            Lock l;
            uint32_t now = millis();
            check = checkRequested_ || (!checked_ && now >= FIRST_CHECK_MS) ||
                    (checked_ && now - lastCheckMs_ >= CHECK_EVERY_MS);
            install = installRequested_;
            checkRequested_ = false; installRequested_.clear();
        }
        if (!install.empty()) runInstall(install);
        else if (check) runCheck();
    }
}

}  // namespace

void updaterBootCheck() {
    Preferences p;
    if (!p.begin(PREFS, false)) return;
    bool trial = p.getBool("trial", false);
    uint8_t tries = trial ? p.getUChar("tries", 0) + 1 : 0;
    if (trial) p.putUChar("tries", tries);
    if (shouldRollBack(trial, tries)) {
        // The other OTA slot still holds the firmware we updated from.
        const esp_partition_t* previous = esp_ota_get_next_update_partition(nullptr);
        p.putString("badVer", FIRMWARE_VERSION);
        p.putBool("trial", false); p.putUChar("tries", 0);
        p.end();
        if (previous && esp_ota_set_boot_partition(previous) == ESP_OK) {
            Serial.printf("[update] %s failed to start %u times, rolling back\n", FIRMWARE_VERSION, (unsigned)tries - 1);
            ESP.restart();
        }
        return;
    }
    p.end();
}

void updaterBegin() {
    lock_ = xSemaphoreCreateMutex();
    { Preferences p; p.begin(PREFS, true); rolledBack_ = p.getString("badVer", ""); p.end(); }
    if (!UPDATE_PUBLIC_KEY[0]) state_ = "off";
    WiFi.onEvent([](WiFiEvent_t, WiFiEventInfo_t info) { joinReason_ = info.wifi_sta_disconnected.reason; },
                 ARDUINO_EVENT_WIFI_STA_DISCONNECTED);
    xTaskCreatePinnedToCore(updaterTask, "updater", 12288, nullptr, 1, nullptr, 0);
}

void updaterWriteStatus(JsonDocument& d) {
    Preferences p; p.begin(PREFS, true);
    String ssid = p.getString("ssid", "");
    p.end();
    Lock l;
    d["current"] = FIRMWARE_VERSION;
    d["repo"] = UPDATE_REPO;
    d["enabled"] = UPDATE_PUBLIC_KEY[0] != 0;
    d["wifi"] = ssid;   // the password is never sent back
    d["state"] = state_;
    d["error"] = error_;
    d["progress"] = progress_;
    d["installing"] = installing_.c_str();
    d["checkedAgoS"] = checked_ ? (int32_t)((millis() - lastCheckMs_) / 1000) : -1;
    d["rolledBack"] = rolledBack_;
    JsonArray list = d["releases"].to<JsonArray>();
    for (const auto& r : releases_) {
        JsonObject o = list.add<JsonObject>();
        o["version"] = r.version.c_str();
        o["date"] = r.date.c_str();
        o["newer"] = isNewerVersion(r.version, FIRMWARE_VERSION);
    }
}

void updaterSetWifi(const String& ssid, const String* password) {
    Preferences p; p.begin(PREFS, false);
    p.putString("ssid", ssid);
    if (password) p.putString("pass", *password);
    p.end();
    updaterRequestCheck();
}

void updaterRequestCheck() {
    Lock l; checkRequested_ = true;
}

String updaterRequestInstall(const String& version) {
    if (!UPDATE_PUBLIC_KEY[0]) return "Updates are off in this build";
    if (!canInstallNow(Macros.isRunning(), webServerRecorderActive()))
        return "Stop playback or recording first - the pad restarts after installing";
    Lock l;
    if (state_ == "checking" || state_ == "downloading" || state_ == "restarting") return "Busy - try again in a moment";
    if (version == FIRMWARE_VERSION) return "That version is already installed";
    for (const auto& r : releases_) {
        if (r.version != version.c_str()) continue;
        installRequested_ = r.version;
        return "";
    }
    return "Unknown version - check for updates first";
}
