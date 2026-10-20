#pragma once
#include <Arduino.h>

// Start the Wi-Fi SoftAP + async web server that hosts the config UI and the
// REST API used to edit macros without reflashing. Call once from setup().
void webServerBegin();

// Whether the browser recorder has recently reported an active recording.
bool webServerRecorderActive();
