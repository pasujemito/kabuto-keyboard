# Kabuto — ESP32-S3 BLE macro keyboard

A programmable Bluetooth HID keyboard built on an ESP32-S3. It pairs with any
host (Windows, macOS, Linux, iOS, Android) as a standard Bluetooth keyboard and
runs macros you assign to each physical key, edited from a browser — no
reflashing to change a macro.

## Features

- **Standard BLE HID keyboard** — bonds with multiple hosts; appears as an
  ordinary wireless keyboard.
- **Macro engine** with step types: tap key (with modifiers + hold time),
  key down / key up (for chords held across other steps), type text, media
  keys, fixed delay, **loops** (fixed repeat count or "until stopped"), layer
  switch, and random selection from existing macros.
- **Trigger modes per key**: Tap (run once), Toggle (press to start / press to
  stop), Hold (run while held).
- **Layers** — up to 8, each with its own key assignments.
- **Web config UI** served over a Wi-Fi access point; edits are saved to flash
  and reloaded live.
- **Config button**: hold the BOOT button 3 s to clear BLE pairings.

- **Keyboard recorder** (in the web UI) — tap keys on the virtual keyboard,
  capture physical laptop key events, or type into the phone capture field.
  Captured input is recorded with timing and can be forwarded through Kabuto to
  its paired BLE host. Key presses are recorded as down/up transitions;
  modifiers and held keys are preserved. Focus loss releases held keys. Phone
  text input is stored as text steps. Browser and OS-reserved shortcuts cannot
  be captured.
- **Live key monitor** (in the web UI) — shows the last physical key pressed,
  a running press count, and which keys are down right now, so you can diagnose
  wiring at a glance.
- **Macro execution log** — shows recent steps, measured key hold durations,
  macro passes, and nested loop iterations.
- **RGB status LED** — steady green when idle, slow blue breathing while a
  macro runs, slow yellow breathing while recording, and a triple red flash for
  warnings such as a disconnected BLE host or startup errors. Distinct rhythms
  make the states easier to tell apart without relying on color alone.

Randomized timing is enabled by default: timings under 2 seconds vary by +/-10
ms, while timings of 2 seconds or more vary by +/-1000 ms. Disable it in the
editor to replay configured timings exactly.

## Hardware

- An ESP32-S3 dev board (e.g. ESP32-S3-DevKitC-1). ~£10–18.
- Momentary switches wired as a matrix (defaults to 2 rows × 3 cols = 6 keys).
- Optional diodes (1N4148) per key if you want full N-key rollover; for a small
  pad without diodes, avoid pressing 3+ keys that share a row and column.

### Default wiring (`src/config.h`)

| Signal      | GPIO        |
|-------------|-------------|
| Rows (out)  | 4, 5        |
| Cols (in)   | 6, 7, 15    |
| BOOT button | 0           |
| RGB LED     | 48          |

Rows are driven LOW one at a time; columns use internal pull-ups, so each switch
connects one row pin to one column pin. Change the pins, `MATRIX_ROWS`,
`MATRIX_COLS` and the arrays in `config.h` to match your build.

**If keys are flaky or dead:** open the web UI and watch the **Live key
monitor** while pressing each switch. If the press count never moves, it's
wiring (or the matrix doesn't match your pins). If presses register but are
intermittent, raise `MATRIX_SETTLE_US` in `config.h` (try 60–80) — ESP32
internal pull-ups are weak, so column lines need time to settle between rows.
The monitor also shows which key *index* a switch maps to, so you can confirm
your wiring matches `(row * MATRIX_COLS + col)`.

## Build & flash (PlatformIO)

```bash
# install PlatformIO Core (once)
pip install platformio

# from the project root:
pio run                       # compile firmware
pio run -t upload             # flash firmware over USB
pio run -t uploadfs           # upload the web UI (data/) to the device
pio device monitor            # view the serial log (115200)
```

The first `uploadfs` installs the config UI and the example `macros.json`.

## Reusable nano and micro workflows

The editor's **+ nano** and **+ micro** buttons create named workflows without
using physical key slots. Select a workflow in the editor dropdown, name it,
and add steps. Nano workflows typically represent one action (walk, attack,
heal); micro workflows compose these actions with **Call workflow** steps.
These labels organize the library; both support the same steps and can call
other workflows. Calls execute once, independent of the entry key's trigger.

Select a physical key to build a controller with **Random workflow**. Select
its candidate workflows, set their relative weights, and choose how many
recent selections to exclude (0–16). A Toggle key repeats the controller until
pressed again; Hold runs until released. Save before testing. Named workflows
can be tested by calling them from a physical key; Stop releases held keys.

Random selection excludes recent choices **per random step**, across nested
calls and repeated Toggle/Hold passes within one key activation. Starting a
key again resets the history. Weights apply only to remaining candidates.
If no candidate remains, the step skips and logs the reason; it does not
relax the exclusion rule. Keep the exclusion window smaller than the number
of distinct non-empty candidates. Two choices excluding the previous one
will alternate, so use at least three choices for variety. Finite workflows
can still repeat longer patterns; randomness does not guarantee uniqueness.

A complete example is in [`examples/workflows.json`](examples/workflows.json):
three nano actions, three composed micro workflows, and a weighted Toggle
controller. Its bindings (`W`, `A`, `H`) are illustrative. To use it, back up
`data/macros.json`, copy the example there, then upload the filesystem. This
replaces the device configuration; normal editor saves retain existing keys.

The firmware sends keyboard input without observing game state. The example
heals when randomly selected, not when health is low. Health/enemy conditions are not implemented. The combat preset below adds
explicit timing ranges and cooldown-based utility checks; the existing global
timing variation remains available for fixed-duration steps.

The library supports up to 64 workflows, 256 steps each, and eight nested
calls. Missing references are rejected on save. Runtime cycles/depth overflow
skip with a log entry. Existing configs and layer/key random choices remain
supported. Workflow IDs stay stable when names change; remove references
before deleting a workflow in the editor. Config version 2 adds:

```json
{"type":"call", "workflow":"walk"}
```

```json
{"type":"random", "avoidRecent":1, "choices":[
  {"workflow":"approach", "weight":3},
  {"workflow":"burst", "weight":2},
  {"workflow":"recover", "weight":1}
]}
```

See [`tests/README.md`](tests/README.md) for host tests and firmware checks.

## Default first layer: combat baseline

The shipped `data/macros.json` now starts with **1 · Combat baseline** (firmware
layer index 0). The previous demonstration layer is retained as the second
layer. A copy is in `examples/combat-layer-one.json`. Build and flash the new
firmware before uploading the new filesystem; back up device macros first,
because `uploadfs` replaces the saved configuration. Existing device configs
are not migrated by flashing firmware alone.

| Physical key | Behaviour |
| --- | --- |
| 1 | Toggle combat on/off |
| 2 | Run one combat block |
| 3 | Combat while held |
| 4 | One short movement pulse, without Ctrl |
| 5 | Jump and pickup, without Ctrl |
| 6 | Check configured utility cooldowns |

Combat holds Ctrl for a randomly selected 25–85 seconds and chooses among six
weighted micro combinations, excluding the immediately preceding choice. They
vary movement/jump/pickup order, including movement while Z is held. These are
adaptations guided by the recording, not exact replays. Arrow pulses last
120–524 ms (163–322 ms during pickup), jump holds 120–194 ms, and pickup taps
72–130 ms. Pauses have independent explicit ranges. Ctrl stays held across
these actions; each arrow is released after its pulse. The engine caps combat
blocks at 90 seconds, interrupts nested waits at the block deadline, and
releases all inputs on completion or Stop. The cap is enforced cooperatively
by the firmware scheduler, not by a hardware timer.

Movement selection uses cumulative left/right pulse duration, favouring the
opposite side when necessary to keep the difference approximately within
600 ms. This is not position feedback or enemy detection, and does not
promise equal attack time facing each side. Collision, acceleration and game
mechanics can still cause drift. The balance resets when a new key activation
starts, but continues across repeated Toggle/Hold passes.

Explicit timing ranges override global jitter. The default disables global
jitter to avoid the old +/-1-second adjustment distorting longer waits. A
`delay` or `move` uses `ms` and optional `maxMs`; a `key` uses `hold` and optional
`maxHold`. Times are inclusive integer milliseconds. Delays/taps support up to
90000 ms; balanced movement supports 1–600 ms. Keep raw held direction keys out
of combat micros; use the bounded movement step instead. Text/media steps are
skipped inside combat blocks so they cannot introduce an uninterruptible
operation. Eight-level recursion/cycle protection still applies.

Pet food, healing and passive skill exist as **disabled, empty utility nanos**.
Assign their actual key steps in the editor, then enable **Occasional utility**.
Their initial minimum gaps are 30, 5 and 6 minutes respectively. The probability
settings are 50, 150 and 100 per thousand checks. Each enabled, non-empty action
gets an independent chance roll after its cooldown; at most one successful
candidate is selected at a check. These are minimum gaps, not deadlines.
The default checks only between attack blocks, after inputs are released.
The full cooldown must elapse from the first macro activation before first use,
and then from the previous utility's completion. Timers survive Stop/Start;
configuration reload or reboot resets them. They are volatile, not persisted
across power loss. This is timer-driven healing, not health-aware healing.

The execution log has **Export log JSON** for the latest observed actions,
selected combinations and measured timings. It is a snapshot of the firmware's
96-event ring buffer, not a complete session trace. Macro JSON exports contain
definitions, not simulated executions. Neither random selection nor finite
history exclusions guarantees absence of longer repeated patterns.

## Preview and export JSON

- **JSON / Export** in the editor previews the selected key or workflow,
  including unsaved changes. Call/random references remain references in this
  fragment; choose **Full configuration** to include all their targets.
- **Export JSON** in the header opens a full configuration backup, including
  workflows, relative weights, recent-choice exclusions and timing settings.
- After stopping a browser recording, **JSON / Export** in the recorder exports
  it without applying it to a key. This is a standalone `macros.json` with
  `randomizedDelay: false`, preserving captured key transitions and delays.
  Loading this recording configuration replaces existing macros; back them up
  first. Use **Use steps** instead to apply the recording within the editor.

Every preview is formatted, read-only JSON with **Copy JSON** and **Download
JSON**. If clipboard access is unavailable on the device's HTTP page, Copy
selects the text for the browser/device's Copy command. Export does not save
changes to the keyboard.

Use these definitions to inspect action order, repeated sequences, delays,
loops and selection weights. They are not expanded execution traces: random
choices and timing jitter are resolved during execution, and exports cannot
guarantee that a sequence will never repeat. The execution log remains the
place to inspect actions actually chosen and their measured timings.

## Configuring macros

1. After flashing, the device creates a Wi-Fi network:
  **SSID `Kabuto-Setup`**, password `macropad123` (change these in
   `config.h`).
2. Join it and open **http://192.168.4.1**.
3. Pick a layer, click a key in the grid, and build its macro from steps.
4. Set the key's trigger mode (Tap / Toggle / Hold) and press **Save to
   device**. Changes apply immediately.
5. **Test ▸** sends a key's macro to the paired host so you can check it without
   touching the hardware (requires a host to be connected).

### Pairing with a host

Put the host into "add Bluetooth device" mode; select **Kabuto**. Bonds are
stored, so it reconnects automatically. To pair a different host, connect from
that host, or hold BOOT for 3 s to clear all pairings and start fresh.

## Record & replay

Two ways to record, because the pad is a Bluetooth *output* device and can't see
your PC's keyboard directly:

1. **On-screen keyboard (in the web UI)** — click **Record with keyboard** on
   any key, tap out the sequence on the virtual keyboard, and hit **Use steps**.
   Timing is captured as you tap; modifiers latch for chords. Best for building
   or tweaking macros by hand on desktop or phone.
2. **PC recorder (`tools/recorder.py`)** — captures your *actual* key presses as
   you play, with their real timing. Best for recording live input.

### PC recorder

It runs on your PC, captures your own key presses with their real timing, and
writes a `macros.json` the pad replays.

```bash
pip install pynput
python tools/recorder.py --out macros.json --loop 0 --trigger toggle
# play; press F10 to stop.
```

Then load the file via the web UI (**Save to device**) or `pio run -t uploadfs`.
Bound to a key as **Toggle** with `--loop 0`, one press starts the replay and a
second press stops it.

- Captured timing is replayed exactly as you played it — nothing is randomised
  or adjusted.
- Held modifiers (Shift/Ctrl/Alt/Win) and overlapping key holds are preserved.
- **Keyboard only** — mouse movement and clicks are not captured or replayed
  (the firmware's HID is keyboard + media). Say the word if you want mouse
  support added; it needs a mouse HID report and new step types.

Attach a recording to one key without disturbing the others:

```bash
python tools/recorder.py --into macros.json --key 4 --name "Combo"
```

`python tools/recorder.py --selftest` runs the conversion tests with no
hardware or dependencies.

## Config file format

Macros live in `/macros.json` on the device (mirrored by `data/macros.json`).
The web UI reads and writes this file; you can also edit it directly:

```json
{
  "version": 1,
  "layers": [
    { "name": "Base",
      "keys": [
        { "name": "Save", "trigger": "tap",
          "steps": [ { "type": "key", "key": "S", "mods": ["ctrl"] } ] }
      ]
    }
  ]
}
```

Step types: `key` (`key`, `mods[]`, `hold` ms), `down`, `up`, `text` (`text`),
`media` (`media`: PLAY/NEXT/PREV/STOP/MUTE/VOLUP/VOLDOWN), `delay` (`ms`),
`loop` (`count`, 0 = until stopped), `endloop`, `layer` (`layer`), and `random`
(`choices`: an array of `{ "layer": n, "key": n }` macro references). A random
step runs one selected non-empty macro once; nested random selection is limited
to eight levels.

## Project layout

```
platformio.ini        build config + pinned library versions
src/
  config.h            pins, matrix size, AP credentials
  main.cpp            matrix scan + wiring
  hid_keyboard.*      BLE HID keyboard (keys + media), bonding
  keymap.*            keycode tables + name<->code resolution
  macro_engine.*      step model, loop execution, trigger modes
  storage.*           LittleFS + JSON load/save
  web_server.*        SoftAP + REST API + static UI host
data/
  index.html          config UI (uploaded with uploadfs)
  macros.json         example macros
tools/
  recorder.py         PC-side keyboard recorder -> macros.json
```

## What changed in 1.4

- **Edit / Run modes on the Keys grid.** A toggle on the Keys panel switches
  what a tap on a keycap does:
  - **Edit** (default): tap selects the key for editing (as before).
  - **Run**: tap *fires* that key's macro to the paired host, with its real
    trigger behaviour — tap runs once, toggle starts/stops, hold runs while you
    hold the cap. Use Stop to halt a running macro. Needs a connected host.

  This is the UI equivalent of pressing the physical key, so you can exercise a
  macro without touching the hardware. (The **Test ▸** button in the editor
  still runs a single one-shot preview.)

## What changed in 1.10

- **Status LED states:** steady green for idle, slow blue breathing for macro
  execution, slow yellow breathing during browser recording, and a triple red
  flash for warnings.
- **Forward-only Live Send:** virtual keyboard input can be sent to the paired
  BLE host without starting a recording. Press Record to capture and forward
  input together.

## What changed in 1.9

- **Browser keyboard capture:** the recorder can capture laptop key-down/up
  events or phone text input, record them into a macro, and forward them to the
  paired BLE host. The browser page must remain active; system/browser shortcuts
  may not be captured. When the interface is open on the same computer that is
  paired as the BLE host, use a different input device to avoid typing the
  forwarded keys back into the capture page.
- **Ordered live events:** captured key and modifier transitions are sent
  sequentially so press/release events reach the paired host in order.

## What changed in 1.3

- **Live send while recording:** in the recorder, tick **Live send** and each key
  you tap on the on-screen keyboard is also sent to the paired host in real time
  (via the ordered live-event endpoint), so you can see how the macro behaves in the target app as
  you build it. It still records normally at the same time. Needs a connected
  host; anything held is released when you stop or close the recorder.
- **Faithful hold capture:** press-and-hold on the virtual keyboard records the
  real hold duration (key-down → delay → key-up), with pointer capture so a hold
  isn't cut if your finger drifts, and auto-release of anything still held on
  stop.

## What changed in 1.2

- **Fixed a cross-task race:** web actions (save/reload, test, stop, layer
  switch) used to call the engine directly from the web-server task while the
  key scanner called it from the main task. They now go through a FreeRTOS
  queue and are applied on one task — no more concurrent mutation of the macro
  state.
- **Fixed macro starvation / watchdog risk:** a loop with no delay in it (e.g.
  `loop 0 { tap }`) could spin without ever yielding, starving key scanning so
  the key meant to stop it was never read. Loops now yield each iteration.
- **Test runs a single pass**, even for Toggle/Hold keys, so previewing a
  looping macro doesn't start it running forever (use Stop to end it).
- **Per-macro step cap** (`MAX_MACRO_STEPS`) is enforced on load.
- **Unsaved-changes indicator:** the Save button shows "Save •" when the config
  in the browser differs from what's on the device.

## Notes on verification

- The firmware **compiles cleanly** for `esp32-s3-devkitc-1` with PlatformIO
  (ESP32 Arduino core 6.9.x): RAM 15%, flash 31%.
- Loop/nesting/infinite-loop semantics of the macro engine are covered by a
  standalone logic test; the on-screen recorder's event→steps logic has its own.
- The example config validates against the parser's schema, and the web UI was
  rendered and exercised at phone-portrait, phone-landscape and desktop sizes.
- Not yet run against physical hardware — flash it and watch the serial log /
  Live key monitor as described above.
```
# kabuto-keyboard
