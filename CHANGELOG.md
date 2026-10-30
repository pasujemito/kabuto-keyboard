# 📝 Changelog

Newest first. Versions from 1.14.0 on are published automatically from `main`
and show up in the pad's **Updates** panel.

## 1.17.0

- 🍁 **Game layer**: a strip over the game with what the screen reader sees
  and each setup step; F9 picks a new map's mob folder, F10 outlines what it
  looks at and finds (mobs named), F11 hides it. No more alt-tabbing
- ⌨️ F8-F11 work **while the game has focus** (read directly on Windows, no
  keyboard hook for the game or anti-cheat to block)
- 🎛️ **Setup from the pad**: Recordings → 🍁 Setup layer adds a layer whose
  buttons are the screen reader's keys (Mark, Skip, Which map, Outlines, Hide,
  Back) and a button to reach it; they type nothing into the game
- 🍁 **MapleStory colours built in** (HP, MP, XP, minimap dot): setup works
  with empty bars and doesn't ask for your dot

## 1.16.0

- 📊 **Live HP, Mana and XP from your screen**: `tools/screen_stats.py` reads
  the bars on your PC (one pixel row each, twice a second, gradient bars
  included) and the pad shows them with XP per hour/minute and time to level
- 🩸 Potions can **drink below a %** of their live bar (HP 50%, Mana 30%), even
  mid-set, falling back to their timers when there's no reading
- 🧮 **Just enough potions**: set the bar's real total and what one tap
  restores, and it taps only as many as fit what's missing
- ⛔ **Stops at once on death and disconnects**, and won't start
  a pattern until the game is back
- 🗺️ **Minimap position**: turn back at map edges and turn around (then stop)
  when stuck. **Sliding minimaps** work: the script follows the slide, so a
  dot that stays centred while you walk isn't stuck
- 👾 **Mob detector**: turns to face mobs in your **hitbox** (your height,
  your attack's reach each side), the nearer side when both have mobs. Give
  it mob **sprites** (PNGs in a `mobs` folder) and it learns their colours,
  leaving out outlines and what the map itself has, and looks for clumps so
  stray pixels don't count
- 🧠 **Smart mode** for dynamic patterns: attacks towards the mobs, waits
  when there are none, and walks back to its home spot when it drifts
  (home range 50% by default; a new map is a new home)
- 🔭 **Mobs in sight**: the screen reader looks 2.5 reaches either side and
  sends how many mobs it sees each side, how near the nearest is and its name
- 🚶 **Walk to mobs** you can see but not reach, staying near home
- ⏸ **Auto-pause**: once most mobs nearby are killed, wait for respawn (up to
  20 s) instead of chasing the last few
- 🦶 **Human walking**: strides of a random length (280–650 ms by default)
  instead of fixed 250 ms taps
- 🗺️ **Mobs per map**: a sprite folder per map; the map is recognised by its
  name, compared as a picture (no OCR), so only that map's mobs are looked for
- 📟 **Dashboard** under the buttons: what the pattern is doing, facing, map,
  a mob radar with counts and the target mob, and the home range on the map
- ▶️ Buttons open in **Play**; switch to Edit to change them
- 🔌 **Plug and play**: the screen reader talks to the pad over the USB cable
  (no Wi-Fi or PIN) and sets itself up on first run

## 1.15.0

- ⌨️ **Choose your keys** for jump, attack and turning: Alt, Ctrl, Shift or any
  key, e.g. Space to jump and X to attack
- 🧪 **HP & Mana**: HP on C and Mana on V, each on its own every X–Y seconds
  timer with its own taps and timing, fired between sets before skills
- 🧩 Clashing keys are refused (same jump and attack, a skill on a movement
  key...); older patterns keep Alt, Ctrl and the arrows, with potions off

## 1.14.2

- 🏠 **Stay connected** to your home Wi-Fi and open the editor at
  **http://kabuto.local** from any device on it, protected by an access PIN
- 📶 Home Wi-Fi has its own panel, and errors say why: network not found
  (Kabuto only sees 2.4 GHz), wrong password, refused by the router or no
  answer, with the right name suggested when only the capitals differ

## 1.14.1

- 📚 Lighter README; the full manual moved to [docs/GUIDE.md](docs/GUIDE.md)
- 📝 This changelog, plus [AGENTS.md](AGENTS.md) for contributors

## 1.14.0

- 🔄 **Updates from GitHub releases.** The pad checks over your home Wi-Fi, shows
  **Update available**, and installs only the version you confirm, newer or older
- 🔏 Releases are signed; the pad rejects anything unsigned or tampered with
- ↩️ A version that keeps failing to start rolls back to the previous one
- 🤖 Every firmware change pushed to `main` is built, tested, signed and released
  automatically, with version numbers counted up for you

## 1.13.0

- 💾 The web editor is built into the firmware, so a normal reflash never
  touches your recordings and patterns
- 🧹 Frees ~110 KB of pad storage for recordings
- 🗜️ Backups taken before a filesystem reflash are compressed (~2 KB) and only
  the newest 5 are kept

## 1.12.0

- 🎛️ Dynamic pattern presets: **Natural**, **Smooth** and **Flip**
- 🌊 Tempo drift: the attack rhythm wanders slower and faster like a person's
- ⏱️ Skills can use a random "use again after" range, picked fresh each time
- 🔤 "Batches" are now **sets**: attacks per set and sets per play
- 👣 No stray step after the last set
- 💾 Reflashing the filesystem keeps your saved config (backed up over USB)

## 1.11.0

- 🎲 Dynamic jump-attack patterns with configurable ranges and skills

## 1.10.0

- 🚦 Status LED: steady green when idle, slow blue while playing, slow yellow
  while recording, triple red flash for warnings
- 📡 Live Send: forward keys to the paired device without recording

## 1.9.0

- ⌨️ Browser keyboard capture from a laptop keyboard or a phone's text field,
  recorded and forwarded to the paired device
- 🔀 Captured key presses reach the paired device in order

## 1.4.0

- ▶️ Edit / Run modes on the key grid: Run plays a key's macro on the paired
  device, just like pressing it

## 1.3.0

- 📡 Live send while recording
- ✋ Press-and-hold on the on-screen keyboard records the real hold time

## 1.2.0

- 🐛 Fixed a race between web actions and the key scanner
- 🐛 Loops with no delay no longer starve key scanning
- 🧪 Test plays a single pass, even for Toggle and Hold keys
- 💾 Save shows "Save •" when there are unsaved changes
