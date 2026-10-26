#pragma once
#include <Arduino.h>
#include <ArduinoJson.h>

// Firmware updates from this project's GitHub releases (UPDATE_REPO in
// config.h). The pad joins your home Wi-Fi to check for releases at boot and
// every 6 hours, shows them in the web UI, and only installs the version you
// confirm - newer or older. Releases must be signed (tools/release_index.py).

// Call first in setup(): a just-installed release that keeps failing to start
// is rolled back to the previous firmware.
void updaterBootCheck();

// Start the background update task. Call before webServerBegin().
void updaterBegin();

// For the web API.
void updaterWriteStatus(JsonDocument& doc);
void updaterSetWifi(const String& ssid, const String* password);  // nullptr keeps the saved password
void updaterRequestCheck();
// Empty on success, otherwise why the install can't start.
String updaterRequestInstall(const String& version);
