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

// Validate the JSON file at 'path' and, if valid, atomically replace
// MACRO_FILE with it. The file at 'path' is removed either way.
bool commitConfigFile(const char* path, String& err);

// Filesystem usage for the web UI.
struct StorageInfo { size_t totalBytes; size_t usedBytes; size_t configBytes; };
StorageInfo storageInfo();

// Write a minimal valid default config if none exists yet.
void ensureDefaultConfig();
