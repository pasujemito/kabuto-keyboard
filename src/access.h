#pragma once
#include <Arduino.h>

// PIN protection for the editor when it's reached over your home network.
// Requests through the setup hotspot don't need it (the hotspot has its own
// Wi-Fi password). The PIN is stored salted and hashed, never as typed.

bool accessPinSet();
// Sets a new PIN and logs out every browser. False if it breaks the PIN rules.
bool accessSetPin(const String& pin);
// A session token for the cookie, or "" with `err` saying why.
String accessLogin(const String& pin, String& err);
// Whether a Cookie header carries a live session.
bool accessSessionValid(const String& cookieHeader);

#define ACCESS_COOKIE "kabuto_session"
