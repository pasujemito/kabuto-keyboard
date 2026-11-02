# 📝 Changelog

Newest first. Versions from 1.14.0 on are published automatically from `main`
and show up in the pad's **Updates** panel.

## 1.18.4

- 🧩 **The game's test popup stops the pad**: the screen reader spots
  MapleStory's test window (the question only you can answer, bottom right:
  its teal panel in a dark window with a light rim) and sends `state=test`;
  the pad stops playing, as for a death, and the strip says **TEST POPUP:
  answer it**. Nothing answers it for you. `--mark test` watches another
  game's test window; `"test_popup": false` turns the check off
- 🔔 **Notifications** on the Buttons screen: each test popup, death and
  disconnect, newest first with how long ago, the one still on screen in red.
  A new one shows a message and buzzes the phone. The pad keeps the last 8;
  **Clear** empties them

## 1.18.3

- 📈 **XP per hour starts afresh at each level-up**: when the XP bar drops
  back to near 0 the rate restarts for the new level (its % are of a bigger
  level) instead of counting on through it; level-ups are still counted
- 📈 **XP per hour on the game layer's strip** (and the console), next to
  your XP: `+3.2%/h, level in 25.4h`, with the same rules

The rest is the screen reader, already on `main`:


- ⚡ **`"frames"`: how many of each mob's animation frames are searched**
  (in `mobs`; 5 by default, the mob's own PNG then the poses least like it;
  `0` = all). A reading drops from about 270 ms to 200 ms on 2 cores with the
  same results on the sample scenes; fewer frames are faster still but miss
  poses. Together with `"sight"` (how far either side is searched) it sets
  the speed: 5 frames at sight 1.5 is about 145 ms. See the guide's
  "Speed vs. what it sees"

## 1.18.2

- 🧪 **Potions tapped after the attack, like you would**: a potion that's
  due is tapped in the gap right after the next attack, before jumping
  again: quick taps (its hold, then 50-110 ms) that use up the gap's own
  time, as many as fit (at least one), the rest after the next attack. The
  attacks land exactly when they would without potions. (1.18.1 pressed it
  inside the jump instead.)

## 1.18.1

- 🧪 **Potions don't pause the attacks**: a potion that's due is pressed
  inside the next jump-attack (down with the jump, released as the attack
  goes down) instead of stopping between attacks to drink; a refill of
  several taps takes one jump-attack each. Live (screen-read) and timed
  potions alike

The rest is the screen reader (`tools/screen_stats.py`), already on `main`:

- 🦘 **Jumping keeps your field of view on your platform**: sight and reach
  follow you sideways, but only move up or down once you've settled
  somewhere new for 5 s (the minimap dot still; `"settle"` in `mobs`), so
  mobs on your platform stay counted mid-jump and a quick hop onto a ledge
  doesn't move it
- ⚡ **About twice as fast, and far lighter on memory**: on 2 cores a reading
  went from 0.74 s to about 0.38 s, the first on a new map from 3.4 s to
  about 1.2 s. Only the current map's frames stay in memory (capped at
  250 MB; before, every map visited added 350 MB or more), the name tag is
  looked for close by first, and a slow reading isn't followed by a full
  wait. Same results on the sample scenes (21 of 21)
- 🐛 **F9 works at start again**: the one-time questions (name tag, map name
  area) left F9 saying to list your maps until they were answered. The map
  list is now there from the start, and F9 during a question means "later":
  the picker opens, the map is taught, and the questions wait for next start
- 📍 **MapleStory's HP, MP and XP bars are found for you** at setup: its
  status bar is centred along the bottom, so they're placed there and kept
  when the HP bar is really there (otherwise you mark them as before)
- 🗺️ **Minimap: just its bottom-right corner to mark** (its top-left is
  the screen's corner in MapleStory; kept if your dot shows in the box)
- 🐛 **Your position on Perion maps was wrong**: the golden sun in the
  minimap's header shares your dot's colour and dragged it up and left (The
  Burnt Land V read 46% across with you at 98%). The dot is now looked for
  below the header; every sample screenshot reads within half a percent
- 🐛 **"Firmware has no setup buttons" on up-to-date pads**: over USB, one
  slow answer from the pad (busy playing, its log in the way) was taken for
  old firmware, and the pad's setup buttons stopped for the session. The
  pad's own version (1.17.0 or newer has them) now decides; a slow answer
  just means no presses that time
- 🐛 **F9's map picker could stop opening**: closing it with its X button
  (or Alt+F4) left the game layer stuck, and F9, F10 and F11 did nothing
  after. Its X now closes it properly, F9 brings an open picker to the
  front, and an error in the layer is printed once instead of stopping it
- 🐛 **`--setup` ended the script**, so "press F9 to teach each map" did
  nothing (F9 only said to list your maps). It now carries on into readings,
  and F9 works during setup too
- 🧯 **Errors are kept**: anything that goes wrong is written to
  `kabuto-error.txt` next to the setup file (and shown on the strip), and an
  error while handling a key no longer stops F8-F11 from working
- 🏷️ **Your name tag is found against any background**: its box is
  see-through, so its colour changes with whatever is behind you and the
  colour match lost it (against a bright sky, say). It's now matched by its
  pattern of light and dark: on the sample scenes 0.71-1.00 at your tag and
  0.27 at most anywhere else, and still found with the box 45% lighter. Also
  faster: about 8 ms near where it was, 50 ms when lost (was 80 and 585)
- 🐛 **Reach and sight at your head instead of your feet**: marking the
  name tag on its own (`--tag`, or the one-time question) measured where it
  sits from the feet marked at setup, but the camera has usually moved you
  since, so the boxes ended up off by about your height. Your feet now come
  from the tag itself (MapleStory draws it centred just under them), so
  setups like that are right again with nothing to redo
- 🎯 **Setup marks less**: no head or feet any more, just your name tag's
  two corners and your reach (every character is the same size)
- ⏱️ **A killed mob stops counting at once**: a mob missed by a reading was
  held for 0.6 s in case hit effects hid it, dead or not. Now it's held only
  if something of it still shows where it was, or the spot is covered in hit
  effects; a dead one leaves plain background and is let go in that reading
- ⚡ **Readings about a quarter faster** (2 cores: about 312 ms to 210-270):
  each spot is checked closely with the 3 frames the fast pass liked best
  there, not every frame of the mob, and the minimap's slide is tracked with
  numpy (37 ms to a few)
- 🧭 **Setup is just your name tag** in MapleStory: the bars, the minimap
  and the map's name are all found for you, and the hitbox is standard
  (your height plus 40 px above and below, 300 px each way; `"pad"` and
  `"reach"` to change it)
- 🗺️ **The minimap's size is found on every map** from its frame's edge
  line (about 2 ms), so F9 no longer asks for its corner; a size in
  `map.json` still wins, for maps where that goes wrong. The map's name is
  read from the header up to the minimap's edge: long names aren't cut off,
  and The Burnt Land III and V are told apart. Setups with a hand-marked
  name area are offered the switch once (maps are then taught again)

Update the pad (Recordings → Updates) and get the new `tools/screen_stats.py`.

## 1.18.0

- 🔍 **Mobs found by shape** (with numpy): every animation frame of the map's
  mobs is matched along the band level with your feet, part by part (outline,
  body, eye...). Works where colour can't, like Perion's brown stumps and
  boars on brown rock; only mobs on your platform count. scipy makes it
  several times faster
- 👀 **Your field of view**: walkers count on your platform, flyers at your
  height (`"view": "screen"` counts everything on screen); a mob hidden for a
  moment by hit effects or mist is held for 0.6 s, so attacks don't stutter
- ▶️ **One command**: `python screen_stats.py` offers what's missing when it
  starts (Pillow, numpy and scipy; frames for mobs without any; your name
  tag; a wider map-name area; maps to teach again), each asked once
- 🎞️ **`tools/mob_frames.py`** fetches each mob's stand, move, fly and hit
  frames from maplestory.io for everything in `map.json`
- 🏷️ **You're followed by your name tag**: mark it once (setup, or `--tag`),
  and the hitbox and search move with you wherever the camera puts you
- 🗺️ **Map names read reliably**: MapleStory's light title bar no longer
  counts as text, so different maps stop looking alike (teach maps again)
- 🧪 **`tools/scene_check.py`** replays screenshots through the reader and
  draws what it found; with an answer file next to a screenshot it's a test
  (missed, wrong, misnamed), and `--draft` starts one
- 💥 **Mobs under hit effects or past the screen's edge** still count: bright
  effect pixels and off-screen ones are taken as unseen, not wrong. All 21
  mobs in the 6 sample scenes are found and named right, nothing else counted
- 🐛 The search looks at the 12 best *distinct* spots, so a strong mob's
  neighbouring pixels no longer crowd out a weaker mob nearby
- 💬 A colour skipped for being too small a part of its mob now says so,
  instead of blaming the map; maps can be taught without colours (by shape)

## 1.17.3

- 🔎 **Searchable map picker**: F9 (Which map) opens a list you can type
  into: words in any order, any case, `2` finds `II`. Recently taught maps
  come first, taught ones are green and changed ones amber; ↑↓, Enter and
  Esc work, with a count of matches
- 🧩 **Shape check with your PNGs**: each clump of mob colour is confirmed by
  laying your sprites over it (facing either way). Scenery that only shares
  a colour (signs, fences, flowers) no longer counts as mobs, and two mobs
  side by side are counted by their shapes. F10 shows each match's % and
  greys out what was turned down
- 🎚️ **Looser / Stricter live**: F6 / F7, or the new *MS🍁 Tune* pad layer,
  move that map's colour tolerance by 5 and save it at once; the strip shows
  the value
- 👾 **Says when mobs aren't being counted**, and why (map not taught, no mob
  detection), on the dashboard and in red on the game strip. A smart pattern
  that can't see mobs, and so keeps attacking, shows "⚠ Can't see mobs"; a
  pattern with Smart off shows "Smart off"

## 1.17.2

- 🗺️ **`map.json` describes each map**: `[{"name": "Rocky Road II", "mobs":
  [...], "minimap": {"width": 178, "height": 96}}]`, room for more settings
  later. The 1.17.1 form still reads
- 📐 **Each map's own minimap size**: teaching a map asks you to Mark its
  minimap's bottom-right corner once and writes the size into `map.json`, so
  your position, edge margins and home range follow that map's real minimap
  instead of the box marked at setup

## 1.17.1

- 🗂️ **One mobs folder, one `map.json`**: every mob PNG is kept once in
  `mobs`, and `mobs/map.json` lists which are on each map
  (`{"Ellinia": ["slime.png", "snail.png"]}`), so a mob on several maps isn't
  copied around. F9 and `--map` list the maps from it; a changed list says
  to teach that map again; missing files and typos are reported. The older
  folder-per-map layout still works without `map.json`

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
