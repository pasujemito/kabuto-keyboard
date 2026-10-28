# 🪲 Kabuto guide

The full manual: wiring, flashing, recordings, dynamic patterns, backups and
updates. For the short version see the [README](../README.md); for what changed
when, the [changelog](../CHANGELOG.md).

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
pio run                       # compile firmware (the web UI is built in)
pio run -t upload             # flash firmware + web UI over USB
pio run -t uploadfs           # optional, first install: example macros.json
pio device monitor            # view the serial log (115200)
```

`uploadfs` is optional: it installs the example `macros.json`. Without it the
pad starts with an empty config. After that you only need `upload`.

### Keeping your patterns when you reflash

Your recordings and patterns live on the pad, in its LittleFS filesystem. The
web UI is built into the firmware (gzipped, ~33 KB), so `pio run -t upload`
updates firmware and UI together and never touches that filesystem. Nothing is
copied to your PC for a normal reflash. Firmware 1.13 also deletes the old copy
of the UI that earlier versions kept in the filesystem, freeing ~110 KB for
recordings.

Only `uploadfs` (writes a whole new filesystem) and `pio run -t erase` (wipes
all flash) can lose them. As a safety net, `tools/pio_keep_config.py` runs
before every `uploadfs`, over the same USB cable:

1. It reads the filesystem straight from the pad's flash with esptool (read
   only, works with whatever firmware is on it).
2. It saves a gzipped copy to `backups/macros-<date>-<time>.json.gz` and keeps
   only the newest 5. An 80 KB config with recordings packs to ~2 KB, so the
   folder stays tiny. It's ignored by git, so your patterns stay private.
3. It builds the new image with that config in place of `data/macros.json`.

If the pad can't be read (wrong port, cable unplugged), `uploadfs` stops instead
of overwriting anything. A blank pad just gets `data/macros.json`. The first run
installs `littlefs-python` into PlatformIO's Python. Options:

```bash
pio run -t backup                                    # backup only, no flashing
KABUTO_RESTORE=backups/macros-20261026-101500.json.gz pio run -t uploadfs   # flash a backup
KABUTO_SKIP_BACKUP=1 pio run -t uploadfs             # deliberately reset to data/macros.json
python tools/flash_backup.py backup --port COM5      # backup without PlatformIO
```

`KABUTO_RESTORE` takes `.json.gz` or plain `.json`, and also moves your setup to
a new board or back after `pio run -t erase`. Set environment variables in
PowerShell with `$env:KABUTO_RESTORE="backups\..."` before the `pio` command.
**Export JSON** in the web UI remains a quick manual backup. From a phone, it
lands wherever that phone saves and syncs downloads.

The pad can't back up to the cloud by itself: it runs its own Wi-Fi hotspot and
has no internet connection.

### Home Wi-Fi and kabuto.local

In **Recordings → Home Wi-Fi**, save your network. Kabuto can only join
**2.4 GHz** Wi-Fi; if your router has separate 2.4 and 5 GHz names, use the
2.4 GHz one. A failed join says why (not found, wrong password, refused, or no
answer). By default the pad joins only to check for updates.

Tick **Stay connected** and the editor is also at **http://kabuto.local** (or
the address shown in the panel) from any device on that Wi-Fi:

- It needs an **access PIN** (6+ characters), asked for once per browser over
  your home network. The Kabuto-Setup hotspot never asks: it has its own Wi-Fi
  password. Forgot the PIN? Set a new one from the hotspot.
- Changing the PIN or restarting the pad logs every browser out. After 5 wrong
  PINs, logins pause for 30 s, doubling up to 15 minutes.
- `kabuto.local` works on macOS, iOS, Windows 10+ and most Linux; if a browser
  (some Android ones) can't find it, use the IP address instead.
- Wi-Fi and Bluetooth share one radio, so staying connected can add a little
  timing jitter. Turn it off for the most precise playback.
- The hotspot stays on as a fallback, on your router's channel.
- The Wi-Fi password and a salted hash of the PIN are kept in the pad's
  settings storage, never in `macros.json` or exports, and never sent back to
  the browser.

### Live stats and screen awareness

The pad can't see your screen, so a small script on the game PC does the
looking. About once a second, `tools/screen_stats.py` samples a few small areas
and sends a handful of numbers: HP, Mana and XP (bar fill %), your position on
the minimap, which side mobs are on, and whether you're dead, disconnected or
on another map. No screenshots leave your PC and there's no text reading. All
the work happens on the PC; the pad only keeps a few numbers (about 20 bytes).

**Plug and play on a game laptop:**

1. Install Python 3 once (python.org, or `winget install Python.Python.3.12`
   on Windows; tick **Add to PATH**), then:
   `pip install mss pynput pyserial`
2. Copy `tools/screen_stats.py` onto the laptop (it's a single file:
   `https://raw.githubusercontent.com/pasujemito/kabuto-keyboard/main/tools/screen_stats.py`).
3. Pair the pad with the laptop over Bluetooth as usual (that's how keys get in).
4. Plug the pad into the laptop with a USB **data** cable (it powers the pad
   and carries the readings).
5. Run `python screen_stats.py` in the folder you copied it to. The first run
   walks you through setup (below) and saves `kabuto-bars.json` there; after
   that it finds the pad on the USB cable and starts sending.

Over USB there's no Wi-Fi, `kabuto.local` or PIN involved: having the pad
plugged in is the permission. Without a cable, it uses Wi-Fi instead.

```bash
python screen_stats.py                 # USB if plugged in, else kabuto.local
python screen_stats.py --pin 123456    # Wi-Fi with the PIN (or set KABUTO_PIN)
python screen_stats.py --setup         # redo setup
python screen_stats.py --dry-run       # check readings without sending
```

Setup marks things by hovering and pressing **F8** (**Esc** skips):

1. **Bars:** HP, then Mana, then XP; each bar's left end, then its right end.
   Do it with every bar at least partly filled: it learns each colour from the
   bar's left end.
2. **Minimap:** its top-left corner, its bottom-right corner, then your own dot
   on it (it learns your dot's colour).
3. **Mobs:** your character on screen, then up to 3 mobs of different kinds (it
   learns their colours). **Esc** when done.

Optionally, while that screen is showing, run `--mark death` (hover e.g. the
respawn button) or `--mark login` (e.g. the login box) for exact detection.
Everything goes in `kabuto-bars.json` (gitignored). If something reads wrong,
raise its `tolerance` there, or check Windows display scaling. `--dry-run`
prints readings without sending. **Restart the script after moving to a new
map**: it learns the minimap when it starts.

Without a USB cable, the PC reaches the pad at `kabuto.local` while it stays on
your home Wi-Fi (PIN needed), or join the PC to the Kabuto-Setup hotspot (no
PIN; use `--host 192.168.4.1`). `--via usb` or `--via wifi` picks one.

**On the pad:**

- The **Buttons** screen shows HP, MP and XP bars, with XP per hour, XP per
  minute (in % of a level), time to the next level and level-ups. The rate
  appears after a minute of readings; **Reset XP rate** starts it afresh. It
  counts through level-ups; small XP drops (death, a misread) are ignored.
- Each HP/Mana potion has **Drink below (%)**: HP defaults to 50%, Mana to
  30%. While fresh readings arrive, a potion drinks as soon as its bar is under
  that, even between attacks in a set, at most every 3 s. With no reading for
  5 s, a bar that isn't read, or 0%, the potion uses its timer as before.
- XP is a percentage of the bar, not points: exact XP numbers would need text
  reading (OCR), which isn't light.
- **Death, disconnects and map changes stop playback at once**, and a pattern
  won't start until the game is back. Dead means the HP bar reads 0% twice in
  a row (or the `--mark death` spot shows); disconnected means the bars and the
  minimap have gone (or the `--mark login` spot shows); a map change means the
  minimap looks different for three readings. The Buttons screen says why it
  stopped. Without a minimap set up, disconnects show up as death.
- Your **minimap position** shows on the Buttons screen, with ◀ ▶ when mobs are
  on that side.
- Each dynamic pattern has **Screen awareness** (on for new patterns, off for
  older ones):
  - **Turn at map edges (%)**, 12% by default: within that distance of the
    minimap's left or right edge, it turns back, even mid-set.
  - **Face mobs**: when mobs show on one side only, it turns to face them.
    Edges come first, then mobs, then the pattern's turn chance.
  - **Stuck after (s)**, 20 s by default: if your dot doesn't move for that
    long, it turns around; still stuck after another wait, it stops.
- The mob detector is colour-based: it looks for the sampled mob colours left
  and right of where your character was marked. It suits maps with one or two
  mob types; bright skill effects in the same colours can fool it, and when
  the camera stops following you at a map edge, your character isn't where it
  was marked.

### Updates from GitHub releases

Once set up, every push to `main` that changes the firmware is released
automatically: built, tested, signed and published. Every pad then shows
**Update available** in **Recordings → Updates**, and installs only when someone
taps **Install** and confirms. The same list offers earlier versions too.

**One-time setup**

1. Make the repository public, or publish releases from a public repo and set
   `UPDATE_REPO` in `src/config.h` to it. Pads download without logging in.
2. Create a signing key pair on your PC (OpenSSL ships with Git for Windows):

   ```bash
   openssl ecparam -name prime256v1 -genkey -noout -out kabuto-signing-key.pem
   openssl ec -in kabuto-signing-key.pem -pubout -out update_public_key.pem
   ```

   Commit `update_public_key.pem`. Put the whole contents of
   `kabuto-signing-key.pem` in a repository secret named `UPDATE_SIGNING_KEY`
   (GitHub → Settings → Secrets and variables → Actions). Then store the private
   key file somewhere safe off the repo; `*signing-key*.pem` is gitignored.
3. Flash the pad once over USB (`pio run -t upload`) so it has the public key.
4. In **Recordings → Home Wi-Fi**, enter your home Wi-Fi and press **Save Wi-Fi**.

**Releasing**

Push to `main`. `.github/workflows/release.yml` runs when `src/`, `web/`,
`platformio.ini`, `update_public_key.pem` or the build hooks change; edits to
docs, tests or `data/` don't announce an update. It:

1. Picks the version: `FIRMWARE_VERSION` in `src/config.h` is the base, so
   releases go 1.14.0, 1.14.1, 1.14.2... Raise the base (e.g. to `1.15.0`) for
   a bigger step; a base behind an existing release stops the workflow.
2. Builds with that version baked in (local builds report the base), runs the
   host tests (including the storage tests), and stops if anything fails.
3. Signs the build and publishes release `vX.Y.Z` with `firmware.bin` and
   `versions.json`, the signed list of the 20 most recent releases.

Pushes queue rather than race, and **Actions → Release firmware → Run
workflow** releases without a code change. Actions and releases are free for
public repositories. Anyone who can push to `main` can publish a release your
pads will trust, so keep write access to yourself (or protect `main`).

**On the pad**

- It checks a minute after starting and every 6 hours, joining your home Wi-Fi
  only for the check unless it stays connected (see above). Its own hotspot
  stays on, though a phone on it may drop for a moment. **Check now** checks straight away.
- Only releases signed with your key are listed. A download is installed only
  if its size and SHA-256 match the signed entry, so a tampered file is
  rejected even though the connection itself isn't certificate-checked.
- **Install** asks for confirmation and refuses while something is playing or
  recording. The pad restarts on the new version; reconnect to its Wi-Fi and
  reload the page. Your recordings and patterns are untouched.
- Older versions may not understand settings added later. Your saved config
  stays on the pad, and works again once you update.
- If a version fails to start three times within its first minute, the pad goes
  back to the previous one and says so in **Updates**.
- Versions from before 1.14 have no updater: flash 1.14 or later over USB once.
- Updates need the standard two-slot flash layout (the default), and a build
  must fit one slot: `pio run` reports that as flash usage.

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
[`examples/jump-combat-dynamic.json`](../examples/jump-combat-dynamic.json).

The device generates fresh sets while playing, using the ranges below. A
**set** is a run of jump-attacks facing one way; between sets, skills may fire
and the character may turn around.
It does not generate a large recording once and then repeat that file.
Timings and integer counts use a symmetric triangular distribution centred
between each minimum and maximum. This is a chosen random model, not evidence
of human behaviour or a guarantee against repetition/detection.

**Start from** offers three presets for movement and rhythm (skills are left
alone). New patterns start as Natural.

| Setting | Natural | Smooth | Flip |
| --- | --- | --- | --- |
| Alt down → Ctrl down | 45–120 ms | 75–105 ms | 45–120 ms |
| Ctrl down → Alt up | 30–120 ms | 60–90 ms | 30–120 ms |
| Alt up → Ctrl up | 16–80 ms | 40–65 ms | 16–80 ms |
| Gap after each attack | 510–760 ms | 580–680 ms | 510–700 ms |
| Direction hold | 85–195 ms | 100–150 ms | 85–150 ms |
| Gap after direction | 16–330 ms | 120–230 ms | 60–200 ms |
| Attacks per set | 2–10 | 4–7 | 1–3 |
| Sets per play | 8–12 | 8–12 | 20–30 |
| Turn around after a set | 85% | 100% | 95% |
| Tempo drift | 15% | 5% | 10% |

Natural is fitted to a recorded 57-second jump-attack run (62 jump-attacks).
Its timing ranges are that run's spread. Smooth keeps roughly the middle half
of each, and Flip turns after nearly every 1–3 attacks. The recording's short
delays fall on ~15 ms steps; that is the PC timer used for recording, not your
hands, so the presets don't copy it.

**Tempo drift** handles what independent random draws can't. In the recording,
the gap after each attack wandered: a slow gap tended to follow a slow one
(lag-1 correlation 0.34), and the average went from ~590 ms to ~700 ms over the
minute. The device keeps a slowly wandering tempo, within ±drift, and scales
each gap after an attack by it. At 15%, generated runs average a lag-1
correlation of 0.31 and similar slow/fast stretches. The press/release timings
inside a jump-attack showed no drift in the recording (lag-1 ≈ 0), so they stay
independent. Patterns saved before drift existed load with 0%.

Every jump-attack retains that exact press/release order. Directions are tapped
between sets, never mixed into an Alt/Ctrl chord. The initial facing is
chosen and actually tapped **before** the first attack, unlike the supplied
Python example which only tracked it in memory. After each set except the
last, change to the opposite direction with the configured probability;
otherwise tap the same direction. Nothing is tapped after the last set, so the
character doesn't take a final step. A 100% turn
chance gives strict alternation, and 0% keeps the initial facing. Direction
taps also move the character, so this is not position balancing or feedback.

**Keys.** Jump, attack, turn left and turn right default to Alt, Ctrl, ← and →.
Change them under **Keys**: jump and attack can be a modifier (Alt, Ctrl,
Shift) or any key, e.g. Space to jump and X to attack. Jump and attack must
differ, the two turn keys must differ from each other and from jump/attack,
and skills and potions can't use a movement key. Patterns saved before keys
were configurable keep Alt, Ctrl and the arrows.

**HP & Mana.** New patterns drink **HP on C every 40–70 s** and **Mana on V
every 25–45 s**, one tap each (hold 85–110 ms, then 400–700 ms). Each potion
has its own key, on/off switch, **every X–Y seconds** range, number of taps
and tap timing. A potion fires at the first gap between sets once its timer is
up, before any skills, and the next wait is drawn fresh each time. The first
drink comes after the first set. Kabuto can't see your health or mana bars, so
potions run on time, not when you're low. Patterns saved before potions
existed have both switched off.

**Skills.** Add up to eight independent skills; configure their key, chance
after each set, number of taps (a range, up to 10), hold/gap ranges and an
optional **use again after** range. Each tap holds, then waits its gap **after
release**, including the last tap, so start-to-start spacing includes both.
New skills start disabled, on a key nothing else in the pattern uses. Multiple skills
can run at the same boundary; their order can be shuffled. They run only after
all jump/attack inputs have been released.

**Use again after** is a wait measured from the end of the skill's previous
use. It is a range in seconds, and a new wait is drawn from it after every use,
so 40–70 s gives a different gap each time. With 100% chance the skill fires at
the first set boundary after the wait; it is not a deadline. The first
opportunity needs no wait. An interrupted use starts its wait too. In the JSON
it is `"cooldown_ms": [min, max]`; an older single number still loads as a
fixed wait. Timers
survive repeated activations and Toggle/Hold passes, but config reload/reboot
resets them. A copied/imported preset gets independent timer identities.

Common setups:

| You want | Set |
| --- | --- |
| Attack exactly twice, then turn | Attacks per set 2–2, turn around 100% |
| Usually turn after 1–3 attacks | Attacks per set 1–3, turn around 80% |
| A skill that fires now and then | Chance 10–30%, use again after 0–0 |
| A buff every 40–70 s, tapped 5–8 times | Chance 100%, taps 5–8, use again after 40–70 |
| HP every 30–50 s, two quick taps | HP every 30–50, taps 2–2 |
| Jump on Space, attack on X | Keys: jump SPACE, attack X |
| Rare, but never back to back | Chance 20%, use again after 20–45 |

Strict settings (2–2 at 100%) repeat exactly; ranges and chances below 100%
vary the rhythm.

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

In the JSON, sets are `"attacks_per_set"` and `"sets"`. Presets saved before
the rename (`"combos_per_side"`/`"sides"`) still load and are saved with the
new names.

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

Then load the file via the web UI (**Save to device**) or flash it with
`KABUTO_RESTORE=macros.json pio run -t uploadfs`.
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
  web_server.*        SoftAP + REST API + built-in UI
  updater.*           GitHub release checks, signed installs, rollback
  update_logic.h      version/signature payload/rollback rules (host-tested)
web/
  index.html          config UI (gzipped into the firmware at build time)
data/
  macros.json         example macros (first install via uploadfs)
tools/
  recorder.py         PC-side keyboard recorder -> macros.json
  flash_backup.py     read the saved config off the pad over USB
  pio_keep_config.py  uploadfs hook: back up + keep the saved config
  embed_web_ui.py     build hook: gzip web/index.html into the firmware
  embed_update_key.py build hook: bake update_public_key.pem into the firmware
  release_index.py    sign a build and add it to versions.json (release CI)
```
