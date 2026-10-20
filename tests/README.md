# Host workflow tests

Run from the repository root. The C++ tests use the production selection helper
and interpreter. Minimal adapters record HID output and provide a deterministic
clock/RNG; they do not simulate Bluetooth, FreeRTOS scheduling or ESP32 hardware.

```sh
g++ -std=c++11 -Wall -Wextra -Werror tests/workflow_selection.cpp -o /tmp/kabuto-selection-tests
/tmp/kabuto-selection-tests
g++ -std=c++11 -Wall -Wextra -Werror -I tests/stubs tests/workflow_engine.cpp src/macro_engine.cpp -o /tmp/kabuto-engine-tests
/tmp/kabuto-engine-tests
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
