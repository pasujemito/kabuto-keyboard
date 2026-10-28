# Host workflow tests

Run from the repository root. The C++ tests use the production selection helper
and interpreter. Minimal adapters record HID output and provide a deterministic
clock/RNG; they do not simulate Bluetooth, FreeRTOS scheduling or ESP32 hardware.

```sh
g++ -std=c++11 -Wall -Wextra -Werror tests/dynamic_pattern.cpp -o /tmp/kabuto-dynamic-tests
/tmp/kabuto-dynamic-tests
g++ -std=c++11 -Wall -Wextra -Werror tests/update_logic.cpp -o /tmp/kabuto-update-tests
/tmp/kabuto-update-tests
g++ -std=c++11 -Wall -Wextra -Werror tests/access_logic.cpp -o /tmp/kabuto-access-tests
/tmp/kabuto-access-tests
g++ -std=c++11 -Wall -Wextra -Werror tests/stats_logic.cpp -o /tmp/kabuto-stats-tests
/tmp/kabuto-stats-tests
g++ -std=c++11 -Wall -Wextra -Werror tests/workflow_selection.cpp -o /tmp/kabuto-selection-tests
/tmp/kabuto-selection-tests
g++ -std=c++11 -Wall -Wextra -Werror -I tests/stubs tests/workflow_engine.cpp src/macro_engine.cpp src/live_stats.cpp -o /tmp/kabuto-engine-tests
/tmp/kabuto-engine-tests
# After pio run has installed the ArduinoJson dependency:
g++ -std=c++11 -Wall -Wextra -Werror -I tests/stubs -I .pio/libdeps/esp32-s3-devkitc-1/ArduinoJson/src tests/workflow_storage.cpp src/storage.cpp src/keymap.cpp -o /tmp/kabuto-storage-tests
/tmp/kabuto-storage-tests
npm install --prefix /tmp/kabuto-ui-test --cache /tmp/kabuto-npm-cache --no-audit --no-fund jsdom@30.1.3
NODE_PATH=/tmp/kabuto-ui-test/node_modules node tests/workflow_editor.cjs
python3 tools/recorder.py --selftest
python3 tools/flash_backup.py --selftest   # LittleFS part needs littlefs-python
python3 tools/release_index.py --selftest  # needs the openssl CLI
python3 tools/next_version.py --selftest
python3 tools/screen_stats.py --selftest     # screen maths, USB + Wi-Fi sending; no screen, pad or pyserial needed
```

The editor test runs the actual page JavaScript with a mocked device API. It
checks recording imports, single/sequence/random assignments, reordering,
removal, reusable references, long recordings and hidden storage parts,
re-recording, legacy button preservation, deletion protection, JSON export,
clipboard fallback, and failure without losing previous data.

For a real Chromium desktop/mobile smoke test (without a physical keyboard):

```sh
npm install --prefix /tmp/kabuto-ui-test --cache /tmp/kabuto-npm-cache --no-audit --no-fund playwright-core
NODE_PATH=/tmp/kabuto-ui-test/node_modules node tests/recordings_browser.cjs
```

This test uses `/usr/bin/chromium` by default (override with `CHROMIUM_PATH`). It
intercepts device requests, exercises assignments, verifies mobile tabs and
checks the layout fits a phone viewport. Screenshots go to `/tmp`. It does not
verify live device responses or BLE playback.

Also build the firmware and filesystem image with PlatformIO (`pio run -j 4`
and `pio run -t buildfs -j 4`). Upload and BLE behaviour require hardware.

Combat tests check Ctrl retention during pulses, both movement directions,
exact 90-second cutoffs in the deterministic host clock, interrupted nested
waits, Stop cleanup, inclusive timing bounds, cooldown eligibility/completion
anchors, persistence across key starts, disabled actions and clock wraparound.
Storage tests load and round-trip the shipped preset through the actual parser,
and reject invalid ranges and unassigned enabled utilities without replacing
the previous file. Hardware scheduling, game position and BLE timing still
require device tests.

Recording persistence tests round-trip the shipped library, hidden storage-part
metadata and button playback preferences. Interpreter tests ensure Ctrl holds
continue across internal parts and captured fixed delays use the configured
global jitter, with smaller variation on key holds, while existing custom
macros remain supported.

The browser test also covers loading errors (a truncated `/api/config` shows
Retry instead of an empty editor), the storage readout, and the recording
editor: all steps of a multi-part recording, timeline times, editing a delay,
insert/delete, the discard prompt, and re-splitting on Apply. Storage tests
check that uploads are committed through a temporary file that is removed on
failure.

Dynamic tests exercise the triangular sampler's endpoints, bounds and centre
weighting; live Alt/Ctrl ordering and actual hold times; fresh set counts;
0/100% turn probability; no direction tap after the last set; legacy
`combos_per_side`/`sides` keys; independent skill repeats/chances/cooldowns; ranged "use again after" waits
drawn per use (and older single-number intervals); tempo drift bounds and its
effect on the gap after each attack; the Natural/Smooth/Flip presets in Chromium;
Stop during direction, modifier and skill holds; definition persistence; and
rejection of invalid or unsafe bounds without replacing the saved config.
The UI tests cover the mobile settings dialog, multiple skills, invalid edits,
JSON previews, discard protection, export/import and independent timer IDs.
Chromium checks the new dialog on a phone viewport while retaining the existing
pad, storage, recording editor and assignment tests. Physical BLE/game behaviour
remains outside these host tests.

Update tests cover version ordering, the exact signed payload (pinned in both
`tests/update_logic.cpp` and `tools/release_index.py`), signing with a throwaway
key, rejecting a key that doesn't match the committed public key, carrying the
release list forward, and the Updates panel (announcement, confirm-to-install,
older-version warning, refusals, Wi-Fi form) in Chromium. Downloading and
flashing over Wi-Fi, signature checks with mbedtls and rollback need hardware.
The release workflow runs the C++ and Python tests on every release.
