# 📝 Changelog

Newest first. Versions from 1.14.0 on are published automatically from `main`
and show up in the pad's **Updates** panel.

## 1.18.13

- 📖 **Every setting explains itself**: in the pattern editor each setting
  has a plain title (with its unit), one sentence on what it does, and bullet
  points for what its values mean (e.g. Distance boundary from home: 0%
  disabled, 20% narrow for platforms, 50% wide for flat ground). Each shows
  its default (what a new pattern gets) with a **↺ Default** button back to it
- 💤 **What isn't in use is greyed out, saying why**: no readings from the PC
  screen reader (screen awareness, home, bar-driven potions), Smart off (wait
  for respawn, walk to mobs), turn taps while Move while attacking is above
  0%, walking when nothing walks. It updates as you edit and as readings come
  and go; greyed settings can still be changed
- 🎯 **Facing mobs is automatic**: the separate "Turn to face mobs" switch is
  gone. With the screen reader seeing mobs, the pattern always faces the one
  in reach (it was already on for new and Smart patterns); the flip-direction
  % only decides when there's no mob to face
- 🏠 **Home on its own**: Home range has its own section and works with Smart
  off too: drift past it and the pattern walks back home, then carries on
  attacking (Smart off never waits for mobs). With Smart on it still hunts
  around home as before
- New skills start with the defaults shown

## 1.18.12

- 🔌 **Readings over the USB cable only**: over Wi-Fi the screen reader's
  readings flooded the pad (its one radio also carries the Bluetooth keys and
  your phone's page) until keys lagged and the page stopped loading. The
  pad's Wi-Fi reading routes are gone; the script finds the pad on the cable
  (a data cable) and says so if it can't. `--via`, `--host` and `--pin` are
  gone with them. **Update the PC script too**
- 📉 **Only what changes is sent**: a reading goes to the pad when something it
  fights with changes (mobs: sides, counts, the nearest's name, one coming
  into or out of reach; your place by 1%; HP or MP by 1%; the game's state;
  the map), plus one every 2 s, so it still reacts at once to a mob
- 📱 **The phone's dashboard asks every 2 s** (was 0.7 s), and not at all
  while the page is in the background

## 1.18.11

- 💥 **No more restarts on checking for updates** (and no stalls while it
  checks): each check verified the signature of every release listed, heavy
  maths done without a pause. With the list grown to 20 that took over 5 s,
  so the watchdog restarted the pad, and the page and Wi-Fi froze meanwhile
  (a check runs a minute after starting, every 6 hours and on Check now).
  Now only the newest 6 are checked, with a pause after each, and the list
  keeps the newest 8 (so pads on older versions stop restarting too). The
  firmware download (1.3 MB, 10-30 s of data) pauses a moment every 16 KB
  too, so it can't trip the watchdog either

## 1.18.10

- 🔄 **Check now shows what it's doing**: it said "Not checked yet" and
  nothing more, because the page looked 0.3 s after asking while the pad
  only picks the request up once a second, and then didn't look again for
  30 s. Now it says "Checking GitHub…" at once and follows the check to its
  result (the new releases, or why not) within a second or two of it ending

## 1.18.9

- 🐢➡️⚡ **Less Wi-Fi traffic, a quicker pad**: with the screen reader on
  Wi-Fi the pad was handling ~8 requests a second (a reading every 0.2 s, and
  a separate ask for its buttons ~3 times a second). Wi-Fi shares the radio
  with the Bluetooth keys, so keys lagged, the page loaded slowly and secure
  downloads ran short of memory. Now the buttons pressed come back in each
  reading's answer (no separate asking while readings flow), and readings go
  every 0.5 s over Wi-Fi (still 0.2 s over USB; `--interval` sets your own):
  about 2 requests a second. **Update the PC script too**, and use the USB
  cable when you can: it doesn't touch the radio
- 🩺 **The pad's health on the page**: under Home Wi-Fi, how long it has been
  up, its free memory (and how much in one piece) and the Wi-Fi signal,
  amber when too little is left for an update. A download that fails for lack
  of memory says so ("restart the pad and try again") instead of "Couldn't
  reach GitHub"

## 1.18.8

- 🌊 **Moving while attacking, not stepping**: a new **Move while
  attacking** setting (60% of sets for new patterns; older ones load with 0,
  as before: turn it up in the pattern) keeps the arrow held through the
  jump-attacks in that share of sets, so you drift through the air attacking
  left or right like a player instead of jumping on the spot. Turns are no
  longer a tap on the ground (the "step"): moving, it switches arrows;
  standing, the arrow is pressed in the air after take-off. Smart's walks run
  straight into attacking without stopping; skills are still cast standing
- 🏠 **Home shown in the game**: home is set by itself when any dynamic
  pattern starts (not only Smart ones), and the pad tells it back with each
  reading, so the game layer marks it on the minimap (a green line, the home
  range a band under it) with your dot, even with outlines (F10) off. The
  strip says where you are and which way home is ("you 41% · home 37% ◀",
  amber out of range). The dashboard shows home without a range too. A home
  taken from the minimap dot is set again once map positions come, instead
  of being compared with them
- 🗺 **F12: the map area by hand**: for a map whose minimap (or its name)
  isn't where it's looked for, F12 (or the pad's **Map area** button) marks
  the minimap's map picture by two corners and the map name by two more
  (Esc keeps either automatic). Saved for the map you're on, or the one you
  pick with F9 next; that map is then read from your marks, and recognised
  by its name in its own place
- 🔔 **Dashboard**: only the newest 4 notifications and 4 versions listed
- 🍁 **Setup layer slimmed down**: one layer (Mark, Skip, Which map, Map
  area, Outlines, Back) instead of Setup + Tune: Looser, Stricter and the
  Setup/Tune switches are gone (F6/F7 still work on the keyboard). Delete the
  old two layers and press **🍁 Setup layer** again to get it

### Screen reader (already on main, out with this release)

- 🕵️ **The Lie Detector mini-game counts as a test too**: its notice ("The
  Lie Detector Mini-game ... the mini-game will start soon", a blue panel in
  a light rim) stops the pad, shows under Notifications and chimes, like the
  test popup. Checked on your screenshot, with no false alarms on 294 frames
  of three Perion videos and the six scene screenshots

- 🔎 **Mobs searched for on every reading again**: replaying three Perion
  videos (with your name tag found right) showed following the mobs between
  searches every 0.5 s, and holding searches back mid-jump, made new mobs
  wait 0.1-0.25 s on average and up to 1 s (and missed some altogether);
  searching every reading reports each on the first reading that can see it.
  Mid-jump is searched too (as many mobs found in the air as on the ground).
  `"search_every"` (seconds, in `mobs`) brings back following in between for
  a slow PC. The rest after each reading is 0.05 s (was 0.15 s), so a slow
  reading isn't followed by a long pause

- 🎥 **Tuned on a real Perion video** (The Burnt Land III, 74 s, replayed at
  the reading rate):
  - mobs partly off the screen's edge were found but never followed (the
    follow window stopped at the edge): now padded like the search;
  - mobs being hit were let go (hit effects cover them): a mob just seen
    there needs 75% of the usual match to be followed, and one mostly under
    hit effects is kept;
  - the whole search is ~10% quicker for the same finds (the "not seen"
    mask on the screen's bytes, frames nowhere near skipped sooner, sums in
    place), and the test popup is looked for once a second, not every
    reading (~11 ms saved);
  - **run `python mob_frames.py`** if you haven't: with only fire_boar.png
    a walking boar matched some of the time; with its stand, walk and hit
    frames 68% more boars were found. Your setup's `"sight": 2.5` searches
    the whole screen width; 1.5 found every boar within reach for 15% less
    time
- ⚡ **Mobs followed between searches**: the whole mob search (about
  150-270 ms a reading) now runs every 0.5 s, and only once you've landed:
  the pattern jump-attacks all the time and the camera bobs with each jump,
  so a search mid-jump looked at the wrong height and missed mobs (in the
  air over 2 s, it searches anyway). In between, each mob found is looked for
  only in a small window round where it was (60 px either side, 50 px up and
  down), with only its own frames, the one it matched last first: a few ms a
  mob (on a test screen with 5 mobs of 3 kinds, 13 ms instead of 92 ms).
  Readings come every 0.2 s instead of 0.5 s, so the pad hears of a mob
  moving, turning or dying almost at once, and a respawn within about half a
  second. `--interval 0.5` sends fewer

## 1.18.7

- 🏠 **Home is where you press the button**: a smart pattern hunts around
  the spot you started it from (or where you arrive on a new map); to hunt
  somewhere else, walk there and press it again. 1.18.6's **Home at %** and
  F12 **Set home** are gone (patterns, `map.json` entries and pad buttons
  saved with them still load; the button does nothing now, and the Setup
  layer's Tune row has Outlines back). It still walks back home once
  there's nothing to fight nearby
- 🚶 **Walking like a player**: walking home or to mobs holds the arrow key
  down the whole way and hops (a quick jump) every so often, instead of
  separate taps with gaps. **Walking: hop every** (was Walking strides) sets
  the time between hops: 600-1300 ms for new patterns. The arrow is always
  let go before attacking, waiting or turning, and when you stop

## 1.18.6

- 🏠 **Set where home is, and hunt around it**: a smart pattern's home can
  be set as **Home at (% across the minimap)** in the pattern (for every
  map), or per map with **F12** in the game (or the pad's **Set home**
  button, on the Tune layer in place of Outlines): it saves your dot's place
  on that map's minimap as `"home"` in `mobs/map.json`, and the screen reader
  sends it with each reading (`hx`). A map's own home wins, then the
  pattern's, else where you started (as before). With a home, once there's
  nothing to fight it walks back there (when over 6% of the minimap away,
  until within 3%) instead of waiting where the last mob was, and
  auto-pause waits there too; mobs in reach on the way are still fought. A
  set home it can't reach in 10 s isn't moved: it tries again 10 s later
- 💀 **No more false deaths on changing maps**: dead used to mean the HP bar
  read 0% twice in a row (half a second), and a map's fade to black does just
  that, so the pad stopped and notified a death. Now dead means HP under 5%
  for 2 s with the minimap still showing (the fade hides it); without a
  minimap set up, with the Mana bar still showing. Disconnected (bars and
  minimap gone) waits 10 s, past any loading screen. `DEAD_HP`,
  `DEAD_HOLD_S` and `GONE_HOLD_S` in `screen_stats.py` tune it

## 1.18.5

- 🔑 **Stay logged in at `kabuto.local`**: once you've typed the PIN, the
  browser keeps the login for a year (it used to be lost when the browser
  closed), and the pad keeps logins across restarts and firmware updates
  (only their hashes, in its settings storage). It keeps 8 browsers, dropping
  the one unused the longest (it used to drop the oldest of 4), and the PC
  screen reader logs in to 2 slots of its own, so its reconnects no longer
  log your phone out. A new PIN still logs everyone out

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
- 🍁 **The game layer looks like MapleStory's own windows**: one row with
  a white rim and rounded bottom corners over a pane of 20% white (on Windows
  a faded window of its own behind the strip, click-through and left out of
  screen captures), bold text outlined in white and small drawn icons: a
  maple leaf, USB plug or Wi-Fi, a map pin, a mushroom for the mobs seen
  each side, a crosshair for the target, ▲ for XP per hour and a clock for
  the time to the next level. HP, MP and XP are just their % (your bars are
  at the bottom of the screen). Warnings are red tags. The strip has a fixed
  width and the changing parts fixed slots (long map names cut with "..."),
  so it no longer grows and shrinks; it keeps clear of the minimap. Setup
  steps show in a bubble under it; the keys show there for 20 s at start.
  F10 labels are name tags; the F9 map list is a light window with a title
  bar like the minimap's
- 🔔 **A soft chime when the game needs you**, on the PC and on the pad's
  page: two plucked notes made by the script (no sound files), rising
  ("pop-ding") as the test popup shows and every 10 s while it stays,
  falling once for a death or a disconnect, with a bubble on the game layer
  saying what happened. Your own sound instead: `kabuto-test.wav` (or
  `kabuto-dead.wav`, `kabuto-offline.wav`) next to the setup file. `--quiet`
  (or `"sound": false` in `kabuto-bars.json`) turns it off. The page chimes
  with a new notification once you've tapped it (browsers' rule)
- 📈 **XP per hour survives changing maps**: as the screen fades the XP bar
  was misread low (counted as a level-up), then the jump back counted as a
  huge gain (thousands of %/h). Now a rise of up to 10% counts at once; any
  drop or bigger rise only once the bar has stayed there 10 s, and only drops
  the game makes count (over half the bar: a level-up; up to 15%: a death).
  On the pad and on the strip

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
