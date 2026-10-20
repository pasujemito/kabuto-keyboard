#pragma once
#include <Arduino.h>
#include "macro_engine.h"

// Mount LittleFS; returns false if the filesystem can't be mounted/formatted.
bool storageBegin();

// Parse MACRO_FILE into cfg. Returns false if the file is missing/invalid
// (cfg is left with a single empty layer so the device still runs).
bool loadConfig(Config& cfg);

// Serialize cfg to JSON and write MACRO_FILE.
bool saveConfig(const Config& cfg);

// Validate a raw JSON string and, if valid, write it to MACRO_FILE.
// Used by the web UI which edits the JSON directly. 'err' gets a message.
bool saveRawJson(const String& json, String& err);

// Read the raw MACRO_FILE contents (for the web UI GET). "" if absent.
String readRawJson();

// Write a minimal valid default config if none exists yet.
void ensureDefaultConfig();
