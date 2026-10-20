# Host workflow tests

Run from the repository root. The C++ tests use the production selection helper
and interpreter. Minimal adapters record HID output and provide a deterministic
clock/RNG; they do not simulate Bluetooth, FreeRTOS scheduling or ESP32 hardware.

```sh
g++ -std=c++11 -Wall -Wextra -Werror tests/workflow_selection.cpp -o /tmp/kabuto-selection-tests
/tmp/kabuto-selection-tests
g++ -std=c++11 -Wall -Wextra -Werror -I tests/stubs tests/workflow_engine.cpp src/macro_engine.cpp -o /tmp/kabuto-engine-tests
/tmp/kabuto-engine-tests
# After pio run has installed the ArduinoJson dependency:
g++ -std=c++11 -Wall -Wextra -Werror -I tests/stubs -I .pio/libdeps/esp32-s3-devkitc-1/ArduinoJson/src tests/workflow_storage.cpp src/storage.cpp src/keymap.cpp -o /tmp/kabuto-storage-tests
/tmp/kabuto-storage-tests
npm install --prefix /tmp/kabuto-ui-test --cache /tmp/kabuto-npm-cache --no-audit --no-fund jsdom@30.1.3
NODE_PATH=/tmp/kabuto-ui-test/node_modules node tests/workflow_editor.cjs
python3 tools/recorder.py --selftest
```

The editor test runs the actual page JavaScript with a mocked device API. It
checks creation, composition, selection weights, saving, deletion protection,
recorder targeting and compatibility with legacy random choices. It also checks
JSON previews, complete configuration backups, exact recording exports, copy
fallback, downloaded file contents and export without configuration changes. It does not
verify browser layout or live device responses.

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
