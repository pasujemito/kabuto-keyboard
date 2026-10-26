#pragma once
#include <Arduino.h>
#include <ArduinoJson.h>

// The pad's link to your home Wi-Fi. It joins briefly for update checks, or
// stays connected when you turn that on, so the editor is reachable at
// http://kabuto.local from your network (PIN-protected, see access.h). The
// setup hotspot keeps running either way.

void homeWifiBegin();
// Station work all happens on the updater's task: call these only from there.
void homeWifiTick();                  // keeps a stay-connected link up; every second
bool homeWifiAcquire(String& err);    // join for a job such as an update check
void homeWifiRelease();               // leave again, unless staying connected

// Safe from the web server.
String homeWifiSsid();
void homeWifiWriteStatus(JsonDocument& doc);
void homeWifiSave(const String& ssid, const String* password, bool stay);   // nullptr keeps the password
