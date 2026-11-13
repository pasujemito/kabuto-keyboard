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
| `src/dynamic_pattern.h` | pattern struct, characters (`Character`, `withCharacter`), triangular sampler (with a peak), tempo drift, hesitation, per-play wobble (pure) |
| `src/storage.*` | LittleFS + JSON parse/validate/save of `/macros.json` |
| `src/web_server.*` | REST API; serves the gzipped UI from firmware |
| `src/updater.*` | GitHub release checks, signed installs, rollback |
| `src/home_wifi.*` | home Wi-Fi station, stay connected, `kabuto.local` |
| `src/access.*` | access PIN (salted hash) and login sessions |
| `src/access_logic.h` | PIN rules, login lockout, cookie parsing (pure) |
| `src/update_logic.h` | version/payload/rollback rules (pure) |
| `src/live_stats.*` | latest readings from the PC (bars, game state incl. the test popup, minimap x/y and map position, mob sides/counts/distances, map name) and what a playing pattern is doing (dashboard) |
| `src/stats_logic.h` | XP rate, live potions, stop reasons, notifications, edge/mob facing, stuck, smart decisions, auto-pause, breaks and rests, mob-driven sets, session cap (pure) |
| `src/config.h` | pins, base `FIRMWARE_VERSION`, `UPDATE_REPO` |
| `web/index.html` | the whole web UI, one file, embedded at build time |
| `data/macros.json` | example config, only flashed by `uploadfs` |
| `tools/` | build hooks, backup, release signing, recorder, `screen_stats.py` (PC screen reader, game layer, MapleStory colours, shape search), `mob_frames.py` (animation frames), `scene_check.py` (replay screenshots; scored against `.json` answers next to them) |
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

Storage tests and the scenarios (`tests/scenarios.cpp`) need ArduinoJson from
`.pio/libdeps` (after one `pio run`). The release workflow runs all C++ and
Python tests. The scenarios are the behaviour contract: keep them passing, and
when a change means one should expect something else, change that expectation
deliberately and explain it in plain words (see tests/README.md).

## Conventions

- Match the surrounding code: the engine and UI are dense one-liners, the
  tools are plain readable Python.
- `executeSteps` (`macro_engine.cpp`) is recursive and its frame holds every
  local of the dynamic pattern case (about 3.3 KB in 2.1.0); it nests four deep
  when an arrow is let go of mid-delay. The macro task has
  `ENGINE_STACK_BYTES` (32 KB). After adding locals or lambdas there, build
  with `PLATFORMIO_BUILD_FLAGS=-fstack-usage` and read
  `.pio/build/*/src/macro_engine.cpp.su`: runMacro + 4 × executeSteps must
  stay under half the stack.
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
  Readings arrive over USB serial only (`KABUTO hello` / `KABUTO stats <form>`
  lines, `usbStatsPoll` in `main.cpp`; the Wi-Fi routes flooded the pad and are
  gone: don't add Wi-Fi traffic per reading), only when they change something
  (`worth_sending`) plus a 2 s heartbeat,
  parsed by `statsField` / `parseStatsForm` (`stats_logic.h`). The other way,
  `tool` steps (the pad's setup buttons) and the page's `/api/tool` (Teach this
  map, Settings' screen reader keys) queue the script's keys in `ToolKeys`
  (`stats_logic.h`); it collects them with `KABUTO keys`. Each reading's
  answer (`KABUTO ok keys=...&home=...`) carries the pad buttons pressed since (so the script
  only polls for them while readings aren't flowing) and the playing
  pattern's home (`homeReplyForm`) for the game layer. The page polls
  `/api/status` every 2 s, never while hidden. Maps are described in `mobs/map.json` (name, mobs, the
  map's minimap size; PNGs kept once in `mobs`): written by hand except
  `minimap`, which F9 teaching (size) or F12 (a hand-marked box with
  `left`/`top`) fills in. Machine-learned data (name pixels,
  mob colours) stays in `kabuto-bars.json`. Maps are told apart by the name's
  pixels (no OCR); the pad only gets the name, and an untaught map gets a
  stand-in name from those pixels (`unnamed-...`, `untaught()` / `untaughtMap`
  in the UI) so Set homes stay per map. MapleStory's minimap never slides
  (`whole_map`): there the dot is the map position. With numpy (optional, never
  required: CI has none), mobs are found by shape from their animation frames
  (`mob.png` + `mob.*.png`) and you by your name tag; numpy-only code must
  stay behind `numpy_or_none()` and its self-tests skip without it.
- Keep the README light. Details go in `docs/GUIDE.md`, changes in
  `CHANGELOG.md`.

## Releasing

Every push to `main` touching `src/`, `web/`, `platformio.ini`, the public key
or the build hooks runs `.github/workflows/release.yml`: picks the next version
(`tools/next_version.py`: base from `src/config.h`, patch counted up), builds,
tests, signs with the `UPDATE_SIGNING_KEY` secret and publishes `firmware.bin` +
`versions.json`. To release, add a `CHANGELOG.md` entry; raise the base in
`src/config.h` for a minor or major step.

### Which number goes up

Decide per pull request, before merging, and say which in the PR:

- **New feature or a significant change in what the pad does** (a new setting,
  panel, button or mode; a new kind of behaviour, such as Set home or
  characters): raise the **minor** number and reset the patch. Set
  `FIRMWARE_VERSION` in `src/config.h` to the next minor, e.g. `1.19.0` →
  `1.20.0`, and head the `CHANGELOG.md` entry `## 1.20.0`.
- **Small change, fix, or a change to existing logic** (tuning, a bug fix,
  wording, a rule refined within an existing feature, tests or docs): leave
  `src/config.h` alone. The release workflow counts the patch up by itself,
  `1.20.0` → `1.20.1` → `1.20.2`...; head the entry with that next number.
- **Major** (`2.0.0`) only when the user asks: something that breaks saved
  configs or needs a fresh setup.

When one pull request has both, the bigger step wins (a feature with fixes is
a minor release). If unsure, ask the user.
