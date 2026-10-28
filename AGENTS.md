# 🤖 AGENTS.md

Context for contributors and AI coding agents. Users read the
[README](README.md); the full manual is [docs/GUIDE.md](docs/GUIDE.md).

## What this is

Kabuto is an ESP32-S3 Bluetooth (BLE HID) macro pad: a 2 × 3 key matrix,
macros edited from a phone over the pad's own Wi-Fi hotspot, and signed
firmware updates from this repo's GitHub releases.

## Map

| Path | What |
| --- | --- |
| `src/main.cpp` | setup/loop, key matrix scan, status LED |
| `src/macro_engine.*` | step model and playback (incl. dynamic patterns) |
| `src/dynamic_pattern.h` | pattern struct, triangular sampler, tempo drift (pure) |
| `src/storage.*` | LittleFS + JSON parse/validate/save of `/macros.json` |
| `src/web_server.*` | REST API; serves the gzipped UI from firmware |
| `src/updater.*` | GitHub release checks, signed installs, rollback |
| `src/home_wifi.*` | home Wi-Fi station, stay connected, `kabuto.local` |
| `src/access.*` | access PIN (salted hash) and login sessions |
| `src/access_logic.h` | PIN rules, login lockout, cookie parsing (pure) |
| `src/update_logic.h` | version/payload/rollback rules (pure) |
| `src/live_stats.*` | latest readings from the PC: bars, game state, minimap x/y, mob sides |
| `src/stats_logic.h` | XP rate, live potions, stop reasons, edge/mob facing, stuck (pure) |
| `src/config.h` | pins, base `FIRMWARE_VERSION`, `UPDATE_REPO` |
| `web/index.html` | the whole web UI, one file, embedded at build time |
| `data/macros.json` | example config, only flashed by `uploadfs` |
| `tools/` | build hooks, backup, release signing, recorder, `screen_stats.py` (PC bar reader) |
| `tests/` | host tests (C++ with Arduino stubs, Node/Chromium) |

## Build and test

```bash
pio run                     # build; prints flash use (app slot is 3.3 MB)
pio run -t upload           # flash firmware + UI; never touches saved patterns
```

Host tests (no hardware) are listed in [tests/README.md](tests/README.md). The
quick set:

```bash
g++ -std=c++11 -Wall -Wextra -Werror tests/dynamic_pattern.cpp -o /tmp/t && /tmp/t
g++ -std=c++11 -Wall -Wextra -Werror tests/update_logic.cpp -o /tmp/t && /tmp/t
g++ -std=c++11 -Wall -Wextra -Werror tests/access_logic.cpp -o /tmp/t && /tmp/t
g++ -std=c++11 -Wall -Wextra -Werror tests/stats_logic.cpp -o /tmp/t && /tmp/t
g++ -std=c++11 -Wall -Wextra -Werror -I tests/stubs tests/workflow_engine.cpp src/macro_engine.cpp src/live_stats.cpp -o /tmp/t && /tmp/t
python3 tools/next_version.py --selftest && python3 tools/release_index.py --selftest
```

Storage tests need ArduinoJson from `.pio/libdeps` (after one `pio run`). The
release workflow runs all C++ and Python tests.

## Conventions

- Match the surrounding code: the engine and UI are dense one-liners, the
  tools are plain readable Python.
- Put decisions in pure headers (`*_logic.h`, `dynamic_pattern.h`) so host
  tests can cover them.
- Config is validated twice, on the device (`storage.cpp`) and in the UI
  (`validateDynamicPattern` etc.). Change both together. Key clashes live in
  `dynamicKeyProblem` (`dynamic_pattern.h`), mirrored in the UI.
- Renaming a JSON key: keep reading the old one (see `legacy()` in
  `storage.cpp`, `normalizeDynamicPattern` in the UI). Saved patterns on pads
  must keep loading.
- Nothing may wipe `/macros.json` silently: `uploadfs` goes through
  `tools/pio_keep_config.py`, and firmware updates never touch LittleFS.
- The signed payload `version\nsize\nsha256\n` is pinned in both
  `tests/update_logic.cpp` and `tools/release_index.py`. Change both or neither.
- Every `/api` route is registered with `api()` in `web_server.cpp`, which
  requires the PIN session over the home network. Only `/api/login` and the
  page itself are open; hotspot clients need no PIN.
- Never commit private keys (`*signing-key*.pem` is gitignored). Only
  `update_public_key.pem` belongs in the repo.
- Screen reading stays on the PC (`tools/screen_stats.py`); the pad only gets
  a few numbers per reading. Keep it that way: the pad has little RAM.
- Keep the README light. Details go in `docs/GUIDE.md`, changes in
  `CHANGELOG.md`.

## Releasing

Every push to `main` touching `src/`, `web/`, `platformio.ini`, the public key
or the build hooks runs `.github/workflows/release.yml`: picks the next version
(`tools/next_version.py`: base from `src/config.h`, patch counted up), builds,
tests, signs with the `UPDATE_SIGNING_KEY` secret and publishes `firmware.bin` +
`versions.json`. To release, add a `CHANGELOG.md` entry; raise the base in
`src/config.h` for a minor or major step.
