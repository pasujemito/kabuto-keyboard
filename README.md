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

## Recordings and button assignments

The editor is laid out as a pad. **Buttons** shows the current layer's buttons
as large, evenly spaced keys; each shows its name (or its first recording's
name), a trigger icon (once, toggle, hold) and its playback mode. Give a button
a colour in **Assign** to tell buttons apart at a glance. The header dot shows
whether a host is connected; the icon buttons are Stop, Export JSON and Save (a
red dot means unsaved changes). Layers can be renamed or deleted with the icons
next to **Layers**; deleting a layer keeps its recordings, and is blocked while
another button switches to it.

**Recordings** groups recordings into *Not on a button* (marked New) and *On
buttons*, with a chip for each button that uses them; tap a chip to jump to
that button. Recordings on a button are locked: unlock one to edit or re-record
it. Deleting still requires removing it from its buttons first. Storage use is
collapsed into one line and opens itself when something is nearly full.

The interface has three areas: **Buttons**, **Recordings**, and the selected
button's assignment. On a phone, switch between them with the bottom tabs.

1. In **Recordings**, choose **New recording** and capture your keys with the
   existing on-screen or physical keyboard recorder.
2. Stop, then choose **Save recording**. Give the recording a useful name.
3. Select a button. Choose **One recording**, **In sequence**, or **Random
   choice**, then select the recordings to use.
4. Press the header **Save** to store your edits on the device.

**One recording** plays the selected recording. **In sequence** plays the list
in order; use the arrows to reorder it, and Remove to remove an entry. Repeated
entries are allowed in sequences. **Random choice** picks one distinct recording
each time the button plays. It has an optional **Avoid the same recording twice
in a row** setting; with two recordings that setting causes alternation.

Buttons can **Play once**, **Toggle** playback on/off, or play **While held**.
Toggle and Hold repeat the chosen sequence or make a fresh random selection
after each pass. **Test button** runs one pass. The header **Stop** releases all
inputs. Random playback changes recording selection; it does not rearrange the
captured presses inside a recording.

The **Add to button** action on a recording appends it to the selected button,
turning a single assignment into a sequence when necessary. In the button
editor, **Use recording** replaces the current single assignment. Recordings
are reusable across buttons. Re-recording updates all buttons using that
recording. A recording cannot be deleted while another button or stored macro
references it.

Captured fixed timings are replayed without the old global timing jitter.
Overlapping modifier/key holds remain intact. Long recordings are presented as
one item and split into internal storage parts automatically; key holds continue
across those parts. The library can run out of storage, in which case an edit
fails without discarding the previous recording.

The **Recordings** panel shows how much space is left: recording slots (64 in
total; long recordings use several), the size of the config the next Save will
upload (256 KB max), flash used on the device, and free device memory. Saves are
written to a temporary file and swapped in only once they validate, so a failed
or interrupted save keeps the previous configuration. If the editor can't load
the configuration from the device it shows an error with **Retry** instead of an
empty layout.

The shipped first layer contains **Sample gameplay**, based on the uploaded
97.927-second recording, assigned to button 1 with Play once. GUI and Escape
presses are excluded as requested; original recorded delays remain. The other
five buttons are unassigned. This replaces the generated combat preset in the
shipped defaults. The older combat example remains in
`examples/combat-layer-one.json` for reference.

Flash the updated firmware and upload the filesystem to install the shipped
preset. Back up device macros first: uploading the filesystem replaces the
saved configuration. Flashing firmware alone does not replace existing macros.
Existing configurations remain readable. Custom macros keep their behaviour;
**Move to Recordings** makes an existing button macro reusable without dropping
its steps. The editor no longer exposes nano/micro types, combat block controls
or cooldown settings.

### Editing a recording

**Edit** on a recording opens the whole recording as one step list, even when it
is stored in several internal parts. Each row shows when the step starts, so the
list doubles as a timeline preview. Select a step to change its type, key,
modifiers, hold time or delay, move it, duplicate it, delete it, or insert a
delay or key tap after it. **Apply changes** re-splits the recording into
storage parts; press the header **Save** to store it on the device. Closing with
unapplied changes asks before discarding them.

## Dynamic jump-attack patterns

In **Recordings**, choose **Dynamic pattern**. It creates a reusable preset
assigned to a button exactly like a recording: Once, Toggle, Hold, sequences
and random recording choices all work as before. Assigned items retain the
existing unlock-to-edit protection. Existing recordings and defaults are not
replaced automatically. An importable preset is in
[`examples/jump-combat-dynamic.json`](examples/jump-combat-dynamic.json).

The device generates fresh batches while playing, using the ranges below.
It does not generate a large recording once and then repeat that file.
Timings and integer counts use a symmetric triangular distribution centred
between each minimum and maximum. This is a chosen random model, not evidence
of human behaviour or a guarantee against repetition/detection.

| Setting | Default |
| --- | --- |
| Alt down → Ctrl down | 45–120 ms |
| Ctrl down → Alt up | 30–120 ms |
| Alt up → Ctrl up | 16–80 ms |
| Gap after each attack | 510–760 ms |
| Direction hold | 85–180 ms |
| Gap after direction | 16–330 ms |
| Attacks per batch | 2–10 |
| Batches per play | 8–12 |
| Change facing after a batch | 80% |

Every jump-attack retains that exact press/release order. Directions are tapped
between batches, never mixed into an Alt/Ctrl chord. The initial facing is
chosen and actually tapped **before** the first attack, unlike the supplied
Python example which only tracked it in memory. After each batch, change to
the opposite direction with the configured probability; otherwise tap the
same direction. A final direction tap has no following wait. A 100% turn
chance gives strict alternation, and 0% keeps the initial facing. Direction
taps also move the character, so this is not position balancing or feedback.

The default skill is **C**, enabled with a **10% chance after each batch**,
tapped twice. Each tap holds for 85–110 ms and has an 880–1130 ms gap **after
release**, including the last tap. Thus start-to-start spacing includes both
hold and gap. Add up to eight independent skills; configure their key,
probability, repeat-count range, hold/gap ranges and optional minimum interval.
New additional skills start disabled until configured/enabled. Multiple skills
can run at the same boundary; their order can be shuffled. They run only after
all jump/attack inputs have been released.

A skill's minimum interval is measured from completion of its previous burst;
it does not guarantee execution by a deadline. The first opportunity needs no
initial cooldown. An interrupted burst consumes its cooldown too. Timers
survive repeated activations and Toggle/Hold passes, but config reload/reboot
resets them. A copied/imported preset gets independent timer identities.

Explicit sampled timings are not modified again by global recording jitter.
Each wait is interruptible, and Stop releases arrows, skills, Alt and Ctrl.
Combined Alt or Ctrl hold bounds cannot exceed 90 seconds. Parameter bounds
and skill keys are validated before an uploaded config can replace the current
one. Playback streams one unit at a time, preserving the compact step storage
introduced in the recent memory improvements.

**Preview example JSON** creates one illustrative static sequence using fresh
cooldown history. It is not the next actual device run. Importing that example
stores a static recording; exporting the dynamic preset itself retains its
live generator definition. Very large static previews are limited to 12000
steps; the live generator does not buffer a full run. Apply edits, then use the
header **Save** to persist them. Install the new firmware and filesystem before
using dynamic definitions on a device.

## JSON import and export

**Import JSON** in Recordings accepts a recorded macro fragment with a `steps`
array, or a recording export with exactly one populated key. Captured key,
modifier, text, media and delay steps are supported. Full multi-button backups
and fragments containing workflow references are not recording imports.

Each recording's **JSON** action previews and exports its complete captured
steps, including long recordings. It can be imported back into Recordings.
The recorder also supports standalone JSON export after stopping. The header
**Export JSON** backs up the whole configuration, including all button
assignments. Copy falls back to selecting the text when clipboard permission
is unavailable on the device's HTTP page. Preview/export does not save changes
to the keyboard.

**Device activity** is collapsed by default. Its **Export log JSON** action
exports the latest 96-event firmware buffer, not a complete session trace.
Definitions and execution logs serve different purposes: a recording export
preserves captured actions; the activity log shows measured playback.

See `tests/README.md` for host, storage, editor and browser checks.

## Configuring macros

After flashing, join the device's **Kabuto-Setup** Wi-Fi network (default
password `macropad123`, configurable in `src/config.h`) and open
**http://192.168.4.1**. Create or import recordings, assign them to buttons, and
press **Save**. Test/Run requires a paired Bluetooth host.

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
