#!/usr/bin/env python3
"""
screen_stats.py - read your game screen and send what matters to Kabuto.

Runs on the PC with the game. Five times a second it samples a few small
areas of the screen and sends a handful of numbers to the pad: HP, Mana and
XP (bar fill %), your position on the minimap, the mobs around you (which
sides are in your reach, how many you can see each side, how near the nearest
is, its name), the map you're on, and whether you're dead or disconnected.
Nothing else leaves your PC: no screenshots, no reading text. All the work
happens here, so the pad only stores a few numbers.

Easiest: plug the pad into the game PC with a USB data cable, then
    pip install mss pynput pyserial
    python screen_stats.py
The first run walks you through setup; after that it finds the pad on the
cable and starts sending (USB only: no Wi-Fi or PIN). Each start offers what's
missing, once: Pillow, numpy and scipy (mobs by shape), mobs' animation
frames, your name tag, maps to teach again. To redo setup:
    python screen_stats.py --setup
    # In MapleStory you mark just your name tag (hover, F8; Esc skips): the
    # bars, the minimap (its size found on every map) and the map's name are
    # found, your feet are just above the tag, and the hitbox is standard
    # (your height + 40 px above and 120 below, 300 px each way). Other games
    # (--game other): each bar's ends, the minimap's corners and your dot, the
    # map's name, then your name tag. --tag redoes just the tag.
With numpy, mobs are found by shape: every animation frame of the map's mobs
(mob.png plus mob.*.png; fetch them with mob_frames.py) matched along the band
level with your feet. scipy makes it several times faster.
MapleStory's bar and dot colours are built in (--game maplestory, the
default), and so is where its bars are. --game other samples them.

The game layer: a strip across the top of the game shows what's read and
sent, the map and the mobs, and each setup step, so you needn't leave the
game. F6-F12 work while the game has focus:
    F8   mark (during setup)     F9   which map is this? (pick it from map.json)
    F10  outlines on the game    F11  hide or show the layer
    F12  this map's minimap and name, marked by hand (over the automatic ones)
    F6   looser mob colours      F7   stricter mob colours (this map, saved)
Or press them on the pad: the editor's "Setup layer" (Recordings) gives a pad
layer: Mark, Skip, Which map, Map area, Outlines, Back.
With a pattern playing, the pad tells its home back: the layer marks it on
the minimap (and your dot, even with outlines off).
Each clump of mob colour is checked against your PNGs (MapleStory draws
sprites pixel for pixel), so scenery sharing a colour isn't counted.
The game must be windowed or borderless. --no-layer for the terminal only.
Mob sprites: put PNGs with transparent backgrounds (a frame or two of each
mob) in a "mobs" folder here; setup learns their colours instead of asking
you to mark mobs (needs pip install pillow). After adding sprites:
    python screen_stats.py --mobs
Mobs per map: every PNG once in "mobs", and mobs/map.json describing each
map (a mob on several maps is listed under each):
    [{"name": "Rocky Road II", "mobs": ["red-snail.png", "orange-mushroom.png"],
      "minimap": {"width": 178, "height": 96}}, ...]
"minimap" is that map's minimap size; teaching a map asks you to mark its
bottom-right corner and writes it in.
Setup asks where the map's name is shown; then on each new map press F9 in
the game and click the map (or, from the terminal):
    python screen_stats.py --map            # asks which map
    python screen_stats.py --map Henesys
Its name is kept as a picture (no OCR), so whenever that name shows, that
map's mobs are looked for. Changed a map's list? Teach it again.
Optional, while that screen is showing, for exact detection:
    python screen_stats.py --mark death    # e.g. hover the respawn button
    python screen_stats.py --mark login    # e.g. hover the login box
    python screen_stats.py --mark test     # another game's test window
MapleStory's test popup (a question only you can answer, bottom right) is
found by itself: the pad stops playing and lists it under Notifications.

Run: it finds the pad on the USB cable by itself (a data cable: a charge-only
one won't do). Readings go over the cable only, never Wi-Fi: over Wi-Fi they
flooded the pad, whose radio also carries its Bluetooth keys and your phone's
page. Only what changes for the fight is sent (mobs, your place, HP/MP, the
game's state, the map), plus one every 2 s:
    python screen_stats.py
    python screen_stats.py --dry-run             # just print readings
A minimap that slides as you walk is followed, so your map position keeps up.

Run the self-test (no screen or pad needed):
    python screen_stats.py --selftest
"""
import argparse, json, os, queue, random, re, sys, threading, time, urllib.error, urllib.parse, urllib.request, zlib

BARS = (("hp", "HP"), ("mana", "Mana"), ("xp", "XP"))
CONFIG = "kabuto-bars.json"   # in the current folder (gitignored)

# Games whose colours never change: setup takes them from here instead of
# sampling the screen (so it works with an empty bar), and you only mark the
# minimap's corners, not your dot. The game is kept in the setup file.
GAMES = {
    "maplestory": {"label": "MapleStory", "icon": "\U0001F341",
                   # Its minimap shows the whole map and never slides: your dot is your map position.
                   # (Following a slide that isn't there let one misjudged view shift every position
                   # from then on, saved homes included.)
                   "whole_map": True,
                   "bars": {"hp": [248, 10, 0], "mana": [0, 120, 248], "xp": [206, 243, 0]},
                   "dot": [255, 221, 68],
                   # Where its bars are: the status bar is centred along the bottom of the screen, so
                   # (left, right) px from the middle and y px from the bottom (measured at 1366 x 768).
                   "hud": {"hp": (-180, -78), "mana": (-72, 30), "xp": (41, 153), "y": -14},
                   # Its minimap's top-left corner, from the screen's (only its size changes with the map),
                   # and the header above the map picture (title, region icon, name) in px.
                   "minimap_at": (0, 0), "minimap_header": 72,
                   # The map's name in the header (from the minimap's corner): the line under the region's,
                   # from just past the region icon; read up to the minimap's right edge, wherever that is.
                   "name_area": (47, 43, 246, 56),
                   # Its test popup (find_test_popup) is looked for each reading ("test_popup": false in the
                   # setup file turns that off).
                   "test_popup": True},
}

def minimap_corner(game, monitor):
    """Where the game's minimap starts on this screen, or None if it moves."""
    at = (GAMES.get(game) or {}).get("minimap_at")
    return (monitor["left"] + at[0], monitor["top"] + at[1]) if at else None

def hud_bars(game, monitor):
    """The game's bars where its status bar puts them on this screen, or None
    for a game without a known layout."""
    hud = (GAMES.get(game) or {}).get("hud")
    if not hud:
        return None
    mid, y = monitor["left"] + monitor["width"] // 2, monitor["top"] + monitor["height"] + hud["y"]
    return {name: {"x1": mid + hud[name][0], "x2": mid + hud[name][1], "y": y, "color": list(GAMES[game]["bars"][name]),
                   "tolerance": 60} for name in ("hp", "mana", "xp")}

def apply_game(config):
    """The game's fixed colours over whatever setup sampled (in place)."""
    game = GAMES.get(config.get("game"))
    if game:
        for name, color in game["bars"].items():
            if name in config.get("bars", {}):
                config["bars"][name]["color"] = list(color)
        mm = config.get("minimap")
        if mm:
            mm["dot"] = list(game["dot"])
            if "header" not in mm and game.get("minimap_header") and mm.get("y1", 99) <= 2:
                mm["header"] = game["minimap_header"]   # a box from the screen's top: the dot is looked for below the header
            if "auto" not in mm and game.get("minimap_at") and mm.get("y1", 99) <= 2:
                mm["auto"] = True   # its size found on screen each reading (map.json's size, if any, still wins)
    return config

# Messages go to the console and, when it's up, the game layer's strip, so
# setup can be followed without leaving the game.
LAYER = None

def say(text, sticky=False):
    """`sticky`: stays on the strip until the next message (a setup step)."""
    print(text)
    if LAYER:
        LAYER.say(text.strip(), sticky)

# ---- pure screen maths (raw = RGB bytes, row by row) ------------------------

def near(raw, i, color, t2):
    return (raw[i] - color[0]) ** 2 + (raw[i + 1] - color[1]) ** 2 + (raw[i + 2] - color[2]) ** 2 <= t2

def fill_percent(row, color, tolerance=60, min_run=3, step=30):
    """How full a bar is, from one row of (r, g, b) pixels across it, left to
    right. Uses the end of the rightmost run of bar-coloured pixels, so numbers
    drawn over the middle of a bar don't make it look emptier. Bar-coloured
    means near `color` (learned at the bar's left end) or within `step` of the
    last bar pixel, so a bar that fades along its length (e.g. dark to light
    blue) is followed all the way; the empty part is a jump, not a fade."""
    if not row:
        return None
    end = run = 0
    last = color
    for i, px in enumerate(row):
        if (sum((a - b) ** 2 for a, b in zip(px, color)) <= tolerance ** 2
                or sum((a - b) ** 2 for a, b in zip(px, last)) <= step ** 2):
            last = px
            run += 1
            if run >= min_run:
                end = i + 1
        else:
            run = 0
    return round(100.0 * end / len(row), 1)

FRAME_SCAN = 400   # px right and down from the minimap's corner looked through for its frame

def find_minimap_frame(raw, w, h, header=72):
    """Where MapleStory's minimap ends, from a grab starting at its corner:
    (right, bottom) of its frame's near-white edge line, in px from the
    corner, or None. The line runs down the whole map picture, then across
    it, which nothing in the picture or the scenery around it does."""
    def white(x, y):
        i = (y * w + x) * 3
        return raw[i] >= 235 and raw[i + 1] >= 235 and raw[i + 2] >= 235
    rows = range(header + 4, min(h, header + 60), 4)
    right = next((x for x in range(40, w) if rows and sum(white(x, y) for y in rows) >= 0.9 * len(rows)), None)
    if right is None:
        return None
    cols = range(8, right - 4, 4)
    bottom = next((y for y in range(header + 20, h) if cols and sum(white(x, y) for x in cols) >= 0.9 * len(cols)), None)
    return (right, bottom) if bottom else None

def minimap_frame(sct, mm):
    """The minimap's frame on screen now: (right, bottom) in screen px, or None."""
    w, h = FRAME_SCAN, FRAME_SCAN
    found = find_minimap_frame(grab(sct, mm["x1"], mm["y1"], w, h), w, h, mm.get("header", 72))
    return (mm["x1"] + found[0], mm["y1"] + found[1]) if found else None

def auto_name_area(game, mm):
    """The game's map name area in an automatic minimap's header, or None."""
    at = (GAMES.get(game) or {}).get("name_area")
    if not at or not mm or not mm.get("auto"):
        return None
    return {"x1": mm["x1"] + at[0], "y1": mm["y1"] + at[1], "x2": mm["x1"] + at[2], "y2": mm["y1"] + at[3], "light": 170, "auto": True}

def name_limit(area, frame):
    """How many columns of the map name area are inside the minimap (None: all)."""
    return frame[0] - 2 - area["x1"] if frame and area.get("auto") else None

def find_dot(raw, w, h, color, tolerance=40, step=2, top=0):
    """Your dot on the minimap: the centre of the pixels matching its colour,
    as (x, y) percent of the minimap, or None. Checks every `step`th pixel,
    from `top` px down (below the header, whose region icon may share the
    dot's colour: Perion's golden sun)."""
    t2, sx, sy, n = tolerance ** 2, 0, 0, 0
    for y in range(top, h, step):
        for x in range(0, w, step):
            if near(raw, (y * w + x) * 3, color, t2):
                sx += x; sy += y; n += 1
    if not n:
        return None
    return round(100.0 * sx / n / max(w - 1, 1), 1), round(100.0 * sy / n / max(h - 1, 1), 1)

def col_profile(raw, w, x0, x1, y0, y1, step=2):
    """Average brightness (0-255) of each column x0..x1, over rows y0..y1."""
    rows = range(y0, y1, step)
    n = 3.0 * max(len(rows), 1)
    return [sum(raw[(y * w + x) * 3] + raw[(y * w + x) * 3 + 1] + raw[(y * w + x) * 3 + 2] for y in rows) / n
            for x in range(x0, x1)]

def row_profile(raw, w, x0, x1, y0, y1, step=2):
    """Average brightness (0-255) of each row y0..y1, over columns x0..x1."""
    cols = range(x0, x1, step)
    n = 3.0 * max(len(cols), 1)
    return [sum(raw[(y * w + x) * 3] + raw[(y * w + x) * 3 + 1] + raw[(y * w + x) * 3 + 2] for x in cols) / n
            for y in range(y0, y1)]

def spread(profile):
    """How much a profile varies (mean distance from its average)."""
    mean = sum(profile) / max(len(profile), 1)
    return sum(abs(v - mean) for v in profile) / max(len(profile), 1)

def best_shift(prev, cur, max_shift):
    """How far the minimap slid between two readings: the s where cur[i]
    best matches prev[i + s] (positive: the view moved right/down). Returns
    (s, mismatch) in brightness levels."""
    n, best = min(len(prev), len(cur)), None
    for s in range(-max_shift, max_shift + 1):
        lo, hi = max(0, -s), min(n, n - s)
        if hi - lo < n // 2:
            continue
        diff = sum(abs(prev[i + s] - cur[i]) for i in range(lo, hi)) / (hi - lo)
        score = diff + 0.01 * abs(s)   # on flat stretches, prefer "didn't slide"
        if best is None or score < best[0]:
            best = (score, s, diff)
    return (best[1], best[2]) if best else (0, float("inf"))

def overlap_mismatch(prev, cur, w, h, dx, dy, step=2):
    """How badly two views disagree where they overlap after sliding by
    (dx, dy), relative to the minimap's own contrast: near 0 for a real
    slide, about 1 or more for unrelated views. A plain minimap counts as
    having some contrast, so a little noise on it isn't a new map.
    Checks every `step`th pixel, in brightness."""
    diff, vals = 0, []
    for y in range(max(0, -dy), min(h, h - dy), step):
        for x in range(max(0, -dx), min(w, w - dx), step):
            i, j = (y * w + x) * 3, ((y + dy) * w + x + dx) * 3
            a, b = cur[i] + cur[i + 1] + cur[i + 2], prev[j] + prev[j + 1] + prev[j + 2]
            diff += abs(a - b)
            vals.append(a)
    if not vals:
        return float("inf")
    return diff / len(vals) / max(spread(vals), 45)   # 45 = 15 levels on each of R, G, B

def find_slide_np(np, prev, cur, w, h, max_dx, max_dy):
    """find_slide with numpy: the same sums, done at once (a few ms instead of
    tens on a slow PC)."""
    P, C = (np.frombuffer(r, np.uint8).reshape(h, w, 3).sum(axis=2, dtype=np.int64) for r in (prev, cur))
    def cols(L, y0, y1):
        rows = L[y0:y1:2]
        return rows.sum(axis=0) / (3.0 * max(len(rows), 1))
    def rows_(L, x0, x1):
        cs = L[:, x0:x1:2]
        return cs.sum(axis=1) / (3.0 * max(cs.shape[1], 1))
    def shift(a, b, max_shift):
        n, best = min(len(a), len(b)), None
        for s in range(-max_shift, max_shift + 1):
            lo, hi = max(0, -s), min(n, n - s)
            if hi - lo < n // 2:
                continue
            diff = float(np.abs(a[lo + s:hi + s] - b[lo:hi]).mean())
            score = diff + 0.01 * abs(s)
            if best is None or score < best[0]:
                best = (score, s)
        return best[1] if best else 0
    dx = dy = 0
    for _ in range(2):
        dx = shift(cols(P, max(0, dy), min(h, h + dy)), cols(C, max(0, -dy), min(h, h - dy)), max_dx)
        dy = shift(rows_(P, max(0, dx), min(w, w + dx)), rows_(C, max(0, -dx), min(w, w - dx)), max_dy)
    a = C[max(0, -dy):min(h, h - dy):2, max(0, -dx):min(w, w - dx):2]
    b = P[max(0, -dy) + dy:min(h, h - dy) + dy:2, max(0, -dx) + dx:min(w, w - dx) + dx:2]
    if not a.size:
        return dx, dy, float("inf")
    spread_ = float(np.abs(a - a.mean()).mean())
    return dx, dy, float(np.abs(a - b).mean()) / max(spread_, 45)

def find_slide(prev, cur, w, h, max_dx, max_dy):
    """(dx, dy, mismatch) between two minimap views. Sideways first from
    column brightness, then up and down over the columns both views share,
    then sideways again over the shared rows. Mismatch: see overlap_mismatch."""
    np = numpy_or_none()
    if np:
        return find_slide_np(np, prev, cur, w, h, max_dx, max_dy)
    dx = dy = 0
    for _ in range(2):
        py, cy = (max(0, dy), min(h, h + dy)), (max(0, -dy), min(h, h - dy))
        dx = best_shift(col_profile(prev, w, 0, w, *py), col_profile(cur, w, 0, w, *cy), max_dx)[0]
        px, cx = (max(0, dx), min(w, w + dx)), (max(0, -dx), min(w, w - dx))
        dy = best_shift(row_profile(prev, w, px[0], px[1], 0, h), row_profile(cur, w, cx[0], cx[1], 0, h), max_dy)[0]
    return dx, dy, overlap_mismatch(prev, cur, w, h, dx, dy)

class MinimapTracker:
    """Follows a minimap that slides as you walk. Keeps how far it has slid
    since the start, so your map position is slide + dot (the dot can sit in
    the middle while you walk). A view that can't be lined up (a teleport, a
    respawn, another map) adds no slide: the new view is just followed on."""
    def __init__(self, threshold=0.6, max_slide=0.25):
        self.threshold, self.max_slide = threshold, max_slide
        self.prev, self.ox, self.oy = None, 0, 0

    def update(self, raw, w, h):
        if self.prev is not None:
            dx, dy, mismatch = find_slide(self.prev, raw, w, h, max(1, int(w * self.max_slide)), max(1, int(h * self.max_slide)))
            if mismatch <= self.threshold:
                self.ox += dx
                self.oy += dy
        self.prev = raw

    def world(self, dot, w, h):
        """Your position on the whole map in tenths of a minimap width/height
        (can go below 0 or past 1000 as the minimap slides)."""
        x, y = dot
        return (round(self.ox * 1000.0 / max(w - 1, 1) + x * 10), round(self.oy * 1000.0 / max(h - 1, 1) + y * 10))

_tables = {}

def color_table(colors, tolerance=40):
    """For every colour at 5 bits per channel, a bitmask of which `colors` it's
    within `tolerance` of: checking a pixel is then one lookup, however many
    mob colours there are. Built once per colour set."""
    key = (tuple(map(tuple, colors)), tolerance)
    if key not in _tables:
        t2, table = tolerance ** 2, [0] * 32768
        for bit, (r, g, b) in enumerate(colors):
            span = lambda v: range(max(0, (v - tolerance) >> 3), min(31, (v + tolerance) >> 3) + 1)
            for r5 in span(r):
                for g5 in span(g):
                    for b5 in span(b):
                        if (r5 * 8 + 4 - r) ** 2 + (g5 * 8 + 4 - g) ** 2 + (b5 * 8 + 4 - b) ** 2 <= t2:
                            table[r5 << 10 | g5 << 5 | b5] |= 1 << bit
        _tables[key] = table
    return _tables[key]

def mob_samples(raw, w, h, table, gap, mid, step, cell):
    """The checks that hit a mob colour: [((right side?, cell x, cell y), colour bits, x, y), ...]."""
    out = []
    for y in range(0, h, step):
        row = y * w
        for x in range(0, w, step):
            if abs(x - mid) <= gap:
                continue
            i = (row + x) * 3
            bits = table[raw[i] >> 3 << 10 | raw[i + 1] >> 3 << 5 | raw[i + 2] >> 3]
            if bits:
                out.append(((x >= mid, x // cell, y // cell), bits, x, y))
    return out

def patches(samples, mask=-1):
    """Hits per patch (2 x 2 cells, about a mob's size), from samples whose
    colour bits are in `mask`: {(side, cell x, cell y): (hits, nearest x)}."""
    cells = {}
    for key, bits, x, _ in samples:
        if bits & mask:
            n, xs = cells.get(key, (0, []))
            cells[key] = (n + 1, xs + [x])
    out = {}
    for side, cx, cy in cells:
        parts = [cells[k] for k in ((side, cx + dx, cy + dy) for dx in (0, 1) for dy in (0, 1)) if k in cells]
        out[(side, cx, cy)] = (sum(n for n, _ in parts), [x for _, xs in parts for x in xs])
    return out

def mob_sides(raw, w, h, colors, tolerance=40, gap=40, mid=None, step_x=6, step_y=8, min_hits=3, cell=None):
    """Which sides of you have mobs: 'L', 'R', both nearest first ('LR': the
    left one is nearer, 'RL': the right one), or ''. `mid` is your
    character's x in the area (default: its centre); `gap` px either side of
    it are skipped so your own character doesn't count. With `cell`, hits are
    counted in patches about a mob's size, so it takes a clump of mob colour,
    not stray pixels spread over the scenery; without it (older setups), all
    of a side's hits count together, checked every step_x by step_y px."""
    mid = w // 2 if mid is None else mid
    table = color_table(colors, tolerance)
    if cell:
        found = {}
        for (side, _, _), (n, xs) in patches(mob_samples(raw, w, h, table, gap, mid, step_x, cell)).items():
            if n >= min_hits:
                d = min(abs(x - mid) for x in xs)
                found[side] = min(found.get(side, d), d)
    else:
        hits, found = {}, {}
        for y in range(0, h, step_y):
            for x in range(0, w, step_x):
                i = (y * w + x) * 3
                if abs(x - mid) > gap and table[raw[i] >> 3 << 10 | raw[i + 1] >> 3 << 5 | raw[i + 2] >> 3]:
                    side = x >= mid
                    hits[side] = hits.get(side, 0) + 1
                    found[side] = min(found.get(side, w), abs(x - mid))
        found = {side: d for side, d in found.items() if hits[side] >= min_hits}
    return "".join("R" if side else "L" for side in sorted(found, key=lambda s: (found[s], s)))

SIGHT = 2.5   # how far you look for mobs, in attack reaches either side

# ---- shape check: your PNGs laid over each clump ------------------------------
# Colour finds candidates; the shape decides. MapleStory draws sprites pixel
# for pixel, so where a clump of mob colour is, a mob's PNG (facing either
# way) should line up with what's on screen. Scenery that merely shares a
# colour doesn't, and is left out, so tolerance can be generous.

SHAPE_MIN = 0.6       # how well a sprite must match, 0-1 (per map: "shape"; 0 = no check)
SHAPE_POINTS = 160    # solid pixels compared per sprite, spread evenly over it

def sprite_shapes(sprites, table):
    """Your PNGs ready to lay over the screen: for each sprite and its mirror
    image, a grid of its solid pixels [(dx, dy, r, g, b, colour group)] (at
    most about SHAPE_POINTS; groups of near shades, the tiny ones left out),
    the box and centre of its mob colours (per `table`; the centre is lined up
    with a clump's) and its size. Sprites with none of the mob colours are
    left out."""
    out = []
    for name, (sw, sh, pixels) in sorted(sprites.items()):
        solid = [(x, y, tuple(pixels[y * sw + x][:3])) for y in range(sh) for x in range(sw) if pixels[y * sw + x][3] >= 200]
        keyed = [(x, y) for x, y, c in solid if table[c[0] >> 3 << 10 | c[1] >> 3 << 5 | c[2] >> 3]]
        if not keyed:
            continue
        grid = max(1, int((len(solid) / float(SHAPE_POINTS)) ** 0.5 + 0.999))
        points = [(x, y, c) for x, y, c in solid if x % grid == 0 and y % grid == 0]
        sizes = {}
        for _, _, c in points:
            sizes[(c[0] // 48, c[1] // 48, c[2] // 48)] = sizes.get((c[0] // 48, c[1] // 48, c[2] // 48), 0) + 1
        groups = {g: i for i, g in enumerate(sorted(g for g, n in sizes.items() if n >= max(3, len(points) // 20)))}
        points = [(x, y, c + (groups[(c[0] // 48, c[1] // 48, c[2] // 48)],)) for x, y, c in points
                  if (c[0] // 48, c[1] // 48, c[2] // 48) in groups]
        kx0, kx1 = min(x for x, _ in keyed), max(x for x, _ in keyed)
        ky0, ky1 = min(y for _, y in keyed), max(y for _, y in keyed)
        cx, cy = sum(x for x, _ in keyed) / float(len(keyed)), sum(y for _, y in keyed) / float(len(keyed))
        base = os.path.splitext(name)[0]
        out.append({"name": base, "points": [(x, y) + c for x, y, c in points], "key": (kx0, ky0, kx1, ky1),
                    "center": (cx, cy), "size": (sw, sh)})
        out.append({"name": base, "points": [(sw - 1 - x, y) + c for x, y, c in points],
                    "key": (sw - 1 - kx1, ky0, sw - 1 - kx0, ky1), "center": (sw - 1 - cx, cy), "size": (sw, sh)})
    return out

def shape_score(raw, w, h, points, ox, oy, t2):
    """How well a sprite matches the screen with its top-left at ox, oy, 0-1:
    for each of its colour groups (outline, body, feet...) the share of its
    pixels on screen within tolerance, combined so every part must be there
    (a geometric mean): scenery in some of its colours but without, say, its
    dark outline isn't it. 0 when less than half of it is on screen."""
    inside, hit = {}, {}
    for dx, dy, r, g, b, group in points:
        x, y = ox + dx, oy + dy
        if 0 <= x < w and 0 <= y < h:
            inside[group] = inside.get(group, 0) + 1
            i = (y * w + x) * 3
            if (raw[i] - r) ** 2 + (raw[i + 1] - g) ** 2 + (raw[i + 2] - b) ** 2 <= t2:
                hit[group] = hit.get(group, 0) + 1
    if sum(inside.values()) * 2 < len(points):
        return 0.0
    product = 1.0
    for g, n in inside.items():
        product *= hit.get(g, 0) / float(n) + 0.05
    return round(max(0.0, product ** (1.0 / len(inside)) - 0.05), 3)

def fit_shape(raw, w, h, shape, cx, cy, t2, step):
    """The best place for one sprite whose mob colours centre near cx, cy:
    (score, left, top). A coarse look within a step either way with a third of
    its pixels, then pixel by pixel around the best with all of them."""
    kcx, kcy = shape["center"]
    ox, oy = int(round(cx - kcx)), int(round(cy - kcy))
    spacing = max(1, step // 2)
    span = range(-step, step + 1, spacing)
    coarse = shape["points"][::3]
    _, bx, by = max((shape_score(raw, w, h, coarse, ox + dx, oy + dy, t2), ox + dx, oy + dy) for dx in span for dy in span)
    fine = range(-(spacing // 2 + 1), spacing // 2 + 2)
    return max((shape_score(raw, w, h, shape["points"], bx + dx, by + dy, t2), bx + dx, by + dy) for dx in fine for dy in fine)

def find_shapes(raw, w, h, shapes, hits, tolerance, step, need=SHAPE_MIN, prefer=None):
    """Where your sprites line up within one clump of mob colour (`hits`:
    [(x, y), ...]): ([(score, name, left, top, shape), ...] matching at least
    `need`, one per mob, best first; the best score of all). A clump wider than
    a mob is tried at each spot along it, so two mobs side by side are two
    matches and a fence beside a mob isn't another one."""
    t2, xs = tolerance ** 2, [x for x, _ in hits]
    width = max(1, min(s["key"][2] - s["key"][0] + 1 for s in shapes))
    lo, hi = min(xs), max(xs)
    if hi - lo <= width * 1.5:
        centres = [(lo + hi) / 2.0]
    else:
        centres = [lo + width / 2.0 + k * width / 2.0 for k in range(int((hi - lo - width) / (width / 2.0)) + 1)] + [hi - width / 2.0]
    tried = []
    for c in centres:
        near = [(x, y) for x, y in hits if abs(x - c) <= width / 2.0] or hits
        cx, cy = sum(x for x, _ in near) / float(len(near)), sum(y for _, y in near) / float(len(near))
        best = (0.0, None, 0, 0, None)
        for shape in sorted(shapes, key=lambda s: s["name"] != prefer):
            score, left, top = fit_shape(raw, w, h, shape, cx, cy, t2, step)
            if score > best[0]:
                best = (score, shape["name"], left, top, shape)
            if score >= need:
                break
        tried.append(best)
    found = []
    for match in sorted(tried, key=lambda m: -m[0]):
        if match[0] >= need and all(abs(match[2] - kept[2]) > width * 0.75 for kept in found):   # one per mob
            found.append(match)
    return found, max(m[0] for m in tried)

def mob_view(raw, w, h, colors, tolerance=40, gap=40, mid=None, step=6, min_hits=3, cell=16, names=None, mob_w=0, boxes=None,
             shapes=None, shape_min=SHAPE_MIN, shape_tolerance=None):
    """Every mob in the area, each side nearest first: {"L": [(distance px,
    name), ...], "R": [...]}. A mob is a clump: patches with at least
    `min_hits` hits whose cells touch. A clump wider than one mob (`mob_w` px)
    counts as that many side by side. `names` (one per colour) name a mob after
    the sprite most of its hits came from; None without them. With `shapes`
    (sprite_shapes), a clump counts only if a sprite lines up with it (at
    least `shape_min`; pixels within `shape_tolerance`, default tolerance +
    20), and is named after it. With a `boxes` list, each clump's (x0, y0, x1,
    y1, name, count, shape match or None) in the area is added to it; a clump
    the shapes turned down has count 0."""
    mid = w // 2 if mid is None else mid
    samples = mob_samples(raw, w, h, color_table(colors, tolerance), gap, mid, step, cell)
    cells = {}
    for key, bits, x, y in samples:
        cells.setdefault(key, []).append((bits, x, y))
    hot = set()
    for (side, cx, cy), (n, _) in patches(samples).items():
        if n >= min_hits:
            hot.update(k for k in ((side, cx + dx, cy + dy) for dx in (0, 1) for dy in (0, 1)) if k in cells)
    view = {"L": [], "R": []}
    while hot:
        todo, group = [hot.pop()], []
        while todo:
            side, cx, cy = todo.pop()
            group.append((side, cx, cy))
            for k in ((side, cx + dx, cy + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)):
                if k in hot:
                    hot.remove(k)
                    todo.append(k)
        hits = [hit for k in group for hit in cells[k]]
        xs = [x for _, x, _ in hits]
        votes = {}
        for bits, _, _ in hits:
            for i, name in enumerate(names or []):
                if bits >> i & 1:
                    votes[name] = votes.get(name, 0) + 1
        name = max(sorted(votes), key=votes.get) if votes else None
        rows = [cy for _, _, cy in group]
        outline = (min(xs), min(rows) * cell, max(xs) + step, (max(rows) + 1) * cell)
        side = "R" if group[0][0] else "L"
        if shapes:   # each mob is a sprite that lines up; none: mob colours, but no mob there
            found, best = find_shapes(raw, w, h, shapes, [(x, y) for _, x, y in hits], shape_tolerance or tolerance + 20,
                                      step, shape_min, name)
            if not found and boxes is not None:
                boxes.append(outline + (name, 0, best))
            for score, shaped, left, top, shape in found:
                x0, x1 = left + shape["key"][0], left + shape["key"][2]
                view[side].append((0 if x0 <= mid <= x1 else min(abs(x0 - mid), abs(x1 - mid)), shaped))
                if boxes is not None:
                    boxes.append((left, top, left + shape["size"][0], top + shape["size"][1], shaped, 1, score))
            continue
        near = min(abs(x - mid) for x in xs)
        count = max(1, int(round((max(xs) - min(xs) + step) / float(mob_w)))) if mob_w else 1
        view[side] += [(near + k * mob_w, name) for k in range(count)]
        if boxes is not None:
            boxes.append(outline + (name, count, None))
    for side in view:
        view[side].sort(key=lambda m: m[0])
    return view

def mob_fields(view, reach):
    """What the pad gets from a mob_view: "mobs" (sides with a mob in your
    reach, nearest first, as mob_sides gives), "ml"/"mr" (how many you can see
    each side), "dl"/"dr" (the nearest each side in % of your reach: 100 is
    its edge; left out with none), "ir" (how many are inside your reach, both
    sides) and "mn" (the nearest mob's name)."""
    near = {side: mobs[0] for side, mobs in view.items() if mobs}
    out = {"mobs": "".join(side for side in sorted(near, key=lambda s: (near[s][0], s)) if near[side][0] <= reach),
           "ml": len(view["L"]), "mr": len(view["R"]), "ir": sum(1 for mobs in view.values() for d, _ in mobs if d <= reach)}
    for side, (d, _) in near.items():
        out["d" + side.lower()] = int(round(d * 100.0 / max(reach, 1)))
    nearest = min(near.values(), key=lambda m: m[0]) if near else None
    out["mn"] = nearest[1] if nearest else None
    return out

# ---- which map you're on: its name, read as a picture -----------------------
# No OCR: the game draws a map's name the same way every time, so its light
# pixels are kept as a fingerprint when you teach that map (--map) and
# compared after. Small shifts are allowed; a mostly matching name wins.

def text_rows(raw, w, h, light=170, limit=None):
    """The map name area's light pixels (the name's letters), one int per row.
    Light means at least `light` and clearly brighter than the area itself
    (its middle brightness + 40), so a light title bar behind the name, as
    MapleStory's minimap has, isn't taken for letters. Columns from `limit`
    on (past the minimap's edge) are left out."""
    limit = w if limit is None else max(0, min(w, limit))
    lum = [raw[i] * 3 + raw[i + 1] * 6 + raw[i + 2] for i in range(0, w * h * 3, 3)]
    inside = [lum[y * w + x] for y in range(h) for x in range(limit)]
    cut = min(2450, max(light * 10, sorted(inside)[len(inside) // 2] + 400)) if inside else light * 10
    rows = []
    for y in range(h):
        bits = 0
        for x in range(limit):
            if lum[y * w + x] >= cut:
                bits |= 1 << x
        rows.append(bits)
    return rows

def ones(rows):
    return sum(bin(r).count("1") for r in rows)

def rows_score(a, b, shift=2):
    """How alike two names are, 0-1: light pixels in both over all of them
    (best over up to `shift` px either way)."""
    total = ones(a) + ones(b)
    if not total:
        return 0.0
    best = 0
    for dy in range(-shift, shift + 1):
        for dx in range(-shift, shift + 1):
            both = sum(bin(a[y] & (b[y + dy] >> dx if dx >= 0 else b[y + dy] << -dx)).count("1")
                       for y in range(len(a)) if 0 <= y + dy < len(b))
            best = max(best, both)
    return 2.0 * best / total

NAME_READING = 2      # how map names are read (2: from 1.18, light means clearly lighter than the area)

def name_taught(m):
    """A taught map whose name was read the current way (older ones need teaching again)."""
    return bool(m.get("rows")) and m.get("name_reading") == NAME_READING

class MapReader:
    """Which taught map this is, from its name: the best match scoring at least
    `min_score`, else "" (a map you haven't taught). Only rematched when the
    name area changes."""
    def __init__(self, maps, light=170, min_score=0.8):
        self.maps = {name: [int(r, 16) for r in m["rows"]] for name, m in maps.items() if name_taught(m)}
        self.light, self.min_score, self.last, self.name = light, min_score, None, ""
        self.mark, self.unnamed = "", {}   # a name it wasn't taught: its mark, and the ones seen so far

    def read(self, raw, w, h, limit=None):
        rows = text_rows(raw, w, h, self.light, limit)
        if rows != self.last:
            self.last = rows
            score, name = max([(rows_score(rows, m), n) for n, m in sorted(self.maps.items())] or [(0, "")])
            self.name = name if score >= self.min_score else ""
            self.mark = "" if self.name else self.unnamed_mark(rows, w if limit is None else max(0, min(w, limit)))
        return self.name

    def unnamed_mark(self, rows, width):
        """A stand-in name for a map it wasn't taught, from the name's own pixels
        ("unnamed-3fa2c1"), so the pad can still tell one map from another: a
        Set home made on one must never show up on the next. The same name
        gives the same mark (also one seen a pixel off, this run); "" when the
        area holds no writing (too few or too many light pixels)."""
        lit = ones(rows)
        if lit < UNNAMED_MIN_PIXELS or lit * 2 > width * len(rows):
            return ""
        for mark, seen in self.unnamed.items():
            if rows_score(rows, seen) >= self.min_score:
                return mark
        mark = UNNAMED + "%06x" % (zlib.crc32(",".join("%x" % r for r in rows).encode()) & 0xFFFFFF)
        if len(self.unnamed) < 64:
            self.unnamed[mark] = rows
        return mark

UNNAMED, UNNAMED_MIN_PIXELS = "unnamed-", 20
def untaught(name):
    """A map the script wasn't taught: "-" (no name read) or an unnamed mark."""
    return name == "-" or str(name or "").startswith(UNNAMED)

def safe_name(name):
    """A map or mob name as the pad keeps it: letters, digits, - and _ (spaces
    become _), at most 23 characters."""
    return "".join(c if c.isalnum() and c.isascii() or c in "-_" else "_" for c in name)[:23]

def plain(color):
    """Outline black, highlight white and greys: every sprite and map has them,
    so they can't tell a mob apart."""
    return max(color) < 50 or min(color) > 215 or max(color) - min(color) < 24

def sprite_palette(pixels, max_colors=5, min_share=0.03, bucket=24):
    """A sprite's main colours from its (r, g, b, a) pixels, leaving out
    transparent and plain ones and grouping near shades. Returns
    [(rgb, share of the sprite's solid pixels), ...], biggest first."""
    solid = [p[:3] for p in pixels if p[3] >= 200]
    groups = {}
    for c in solid:
        if not plain(c):
            g = groups.setdefault((c[0] // bucket, c[1] // bucket, c[2] // bucket), [0, 0, 0, 0])
            g[0] += c[0]; g[1] += c[1]; g[2] += c[2]; g[3] += 1
    out = []
    for g in sorted(groups.values(), key=lambda g: -g[3]):
        rgb, share = [g[0] // g[3], g[1] // g[3], g[2] // g[3]], g[3] / len(solid)
        if share < min_share or len(out) == max_colors:
            break
        if all(sum((a - b) ** 2 for a, b in zip(rgb, kept)) > 30 ** 2 for kept, _ in out):
            out.append((rgb, share))
    return out

def learn_mob_colors(sprites, backgrounds, w, h, tolerance=40, gap=40, mid=None):
    """Mob colours from sprites ({name: (width, height, rgba pixels)}) and a
    few shots of the area around you (`backgrounds`, taken a moment apart, so
    a mob walking through one shot doesn't count: each check takes the
    quietest shot). A colour must be at least 4x commoner on its mob than on
    the map. Then the map's busiest patch decides how many hits a patch needs
    to be a mob (twice that, and at least 3 more); while that's too many for
    the smallest mob to reach, the colour the map shows most is dropped.
    Returns (settings, report): colours, step, patch cell size, min hits."""
    smallest = min([min(sw, sh) for sw, sh, _ in sprites.values()] or [48])
    step, cell = max(2, min(6, smallest // 8)), max(8, smallest // 2)
    mid = w // 2 if mid is None else mid
    report, colors, owners = [], [], {}
    for name, (sw, sh, pixels) in sorted(sprites.items()):
        for rgb, share in sprite_palette(pixels):
            if rgb not in colors:
                colors.append(rgb)
            owners.setdefault(name, []).append((colors.index(rgb), share))
    table = color_table(colors, tolerance)
    shots = [mob_samples(bg, w, h, table, gap, mid, step, cell) for bg in backgrounds]
    total = max(1, len(range(0, h, step)) * len(range(0, w, step)))
    share_on_map = [min([sum(1 for _, bits, _, _ in ss if bits >> i & 1) / total for ss in shots] or [0]) for i in range(len(colors))]
    kept = 0
    for name, owned in owners.items():
        for i, share in owned:
            if share_on_map[i] <= share / 4:
                kept |= 1 << i
    own = kept   # the colours the map hasn't got: any dropped below were too little of their mob to spot
    # Checks landing on each sprite, as colour bits, and how many fit in one patch.
    fit = {name: min(1.0, (2 * cell) ** 2 / float(sw * sh)) for name, (sw, sh, _) in sprites.items()}
    on_sprite = {name: [table[p[0] >> 3 << 10 | p[1] >> 3 << 5 | p[2] >> 3] for y in range(0, sh, step) for x in range(0, sw, step)
                        for p in (pixels[y * sw + x],) if p[3] >= 200] for name, (sw, sh, pixels) in sprites.items()}
    peak = lambda mask: min([max([n for n, _ in patches(ss, mask).values()] or [0]) for ss in shots] or [0])
    while True:
        expected = {name: sum(1 for bits in on_sprite[name] if bits & kept & sum(1 << i for i, _ in owners[name])) * fit[name]
                    for name in owners}
        live = [e for e in expected.values() if e > 0]
        need = peak(kept) * 2 + 3
        if not live or need <= 0.6 * min(live):
            break
        worst = max((i for i in range(len(colors)) if kept >> i & 1), key=lambda i: peak(1 << i))
        kept &= ~(1 << worst)
    for name, owned in sorted(owners.items()):
        mine = [(colors[i], share) for i, share in owned if kept >> i & 1]
        for i, share in owned:
            if kept >> i & 1:
                report.append("  %s: %s (%d%% of it, %.1f%% of the map)" % (name, colors[i], share * 100, share_on_map[i] * 100))
            elif own >> i & 1:
                report.append("  %s: skipped %s (%d%% of it and not on the map, but too little of it to spot from afar)"
                              % (name, colors[i], share * 100))
            else:
                report.append("  %s: skipped %s (%d%% of it, but the map has it too: %.1f%%, up to %d hits in one patch)"
                              % (name, colors[i], share * 100, share_on_map[i] * 100, peak(1 << i)))
        if not mine:
            report.append("  %s: no colour of its own to spot it by%s" % (name, " (its shape still can, with numpy)" if numpy_or_none() else ""))
    chosen = [i for i in range(len(colors)) if kept >> i & 1]
    if chosen:
        report.append("  A mob needs %d hits in a %d px patch (the map's busiest patch had %d)" % (need, 2 * cell, peak(kept)))
    # Each colour is named after the sprite it's most of, so the nearest mob can be named.
    names = [os.path.splitext(max(owners, key=lambda n: (dict(owners[n]).get(i, 0), n)))[0] for i in chosen]
    widths = sorted(sw for sw, _, _ in sprites.values())
    return {"colors": [colors[i] for i in chosen], "step": step, "cell": cell, "min_hits": need, "names": names,
            "mob_w": widths[len(widths) // 2] if widths else 0}, report

SPRITE_TYPES = (".png", ".gif", ".webp", ".bmp")

def sniff(head):
    """What a file really is, from its first bytes, for a helpful message."""
    if not head:
        return "an empty file"
    if head.lstrip()[:1] == b"<":
        return "a web page, not an image (save the image itself, e.g. right-click > Save image as)"
    for magic, kind in ((b"\x89PNG", "PNG"), (b"GIF8", "GIF"), (b"\xff\xd8", "JPEG"), (b"BM", "BMP")):
        if head.startswith(magic):
            return "a damaged or cut-off %s (download it again)" % kind
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "a WebP that this Pillow can't read (pip install --upgrade pillow)"
    if head[4:12] in (b"ftypavif", b"ftypheic", b"ftypmif1"):
        return "an AVIF/HEIC image (re-save it as PNG)"
    return "not an image Pillow knows"

def load_sprites(folder, only=None):
    """{file name: (width, height, rgba pixels)} for the images in `folder`
    (just the files named in `only`, if given). Files that can't be read are
    skipped with a reason, not fatal."""
    if not os.path.isdir(folder):
        return {}
    if only is None:
        names = sorted(n for n in os.listdir(folder) if n.lower().endswith(SPRITE_TYPES))
    else:
        names = sorted(n for n in set(only) if os.path.isfile(os.path.join(folder, n)))
    if not names:
        return {}
    try:
        from PIL import Image
    except ImportError:
        raise SystemExit("Reading mob sprites needs Pillow: pip install pillow")
    out = {}
    for n in names:
        path = os.path.join(folder, n)
        try:
            with Image.open(path) as im:
                im = im.convert("RGBA")
                out[n] = (im.width, im.height, list(getattr(im, "get_flattened_data", im.getdata)()))
        except Exception:
            with open(path, "rb") as f:
                print("  skipped %s: it's %s" % (path, sniff(f.read(16))))
    return out

def patch_matches(raw, reference, tolerance=30):
    """Whether a small patch looks like the one captured with --mark."""
    if len(raw) != len(reference) or not raw:
        return False
    total = sum(abs(a - b) for a, b in zip(raw, reference))
    return total / len(raw) <= tolerance

# ---- the game's test windows ---------------------------------------------------
# Two kinds: the test popup (teal, below) and the Lie Detector mini-game's
# notice (a blue panel in a light rim, "The Lie Detector Mini-game ... the
# mini-game will start soon"). Either is state "test": the pad stops, says so
# under Notifications, and the PC chimes.
# Now and then MapleStory stops you with a test, a question only a person can
# answer ("Please find the beautiful Violetta wearing make-up. A correct answer
# will pass the test.", a mushroom beside it, bottom right). Its window is
# dark with a light rim and a teal panel at the top, and that panel framed so
# is what's looked for, anywhere on screen. Seen twice in a row the state is
# "test": the pad stops playing and lists it under Notifications. Nothing here
# answers it; that's for you. --mark test captures a spot of another test
# window to watch for instead (any game).
TEST_STEP = 6            # px between the samples looking for the teal panel
TEST_PANEL = (150, 40)   # px: the least width and height of the panel
TEST_FILL = 0.4          # share of the panel's box that must be its colour (text and pictures are the rest)
TEST_FRAME = 24          # px out from the panel's edge the window's dark band and light rim must be
TEST_EVERY_S = 1.0       # looked for this often (it stays up for long; a whole-screen look costs ~10 ms)

def test_teal(r, g, b):
    """The test panel's teal (dark blue-green at the top, lighter lower down)."""
    return r < 70 and 90 <= g <= 190 and 115 <= b <= 205 and b >= g - 15 and g - r >= 60

def lie_blue(r, g, b):
    """The Lie Detector mini-game window's blue panel (its notice, "The Lie
    Detector Mini-game ... the mini-game will start soon")."""
    return 45 <= r <= 110 and 100 <= g <= 160 and 150 <= b <= 220 and b - r >= 80 and g - r >= 30

# The test windows looked for: each one's panel colour, and whether its frame has a dark band
# inside the light rim (the test popup's does; the Lie Detector's rim is right round its panel).
TEST_PANELS = ((test_teal, True), (lie_blue, False))

def test_frame(raw, w, h, x, y, dx, dy, reach=TEST_FRAME, inside=test_teal, dark_band=True):
    """From a spot just inside the panel's edge, going out (dx, dy): the panel
    ends, then (if `dark_band`) the window's dark grey band, then its light rim."""
    px = lambda x, y: raw[(y * w + x) * 3:(y * w + x) * 3 + 3]
    while 0 <= x < w and 0 <= y < h and inside(*px(x, y)):
        x, y = x + dx, y + dy
    dark = False
    for _ in range(reach):
        if not (0 <= x < w and 0 <= y < h):
            return False
        r, g, b = px(x, y)
        hi, lo = max(r, g, b), min(r, g, b)
        if hi - lo <= 40 and lo >= 150:
            return dark or not dark_band
        dark = dark or (hi < 100 and hi - lo <= 30)
        x, y = x + dx, y + dy
    return False

def find_test_popup(raw, w, h, step=TEST_STEP, least=TEST_PANEL):
    """A test window's panel on screen (the test popup's teal, the Lie
    Detector's blue: TEST_PANELS), (x0, y0, x1, y1), or None."""
    for inside, dark_band in TEST_PANELS:
        box = find_panel(raw, w, h, inside, dark_band, step, least)
        if box:
            return box
    return None

def find_panel(raw, w, h, inside, dark_band, step=TEST_STEP, least=TEST_PANEL):
    """A panel of `inside`'s colour, at least `least` px, framed by a light
    rim (inside a dark band, if `dark_band`): (x0, y0, x1, y1), or None."""
    teal, stride = set(), 3 * step
    for gy in range(h // step):
        row = raw[gy * step * w * 3:(gy * step + 1) * w * 3]
        for gx, rgb in enumerate(zip(row[0::stride], row[1::stride], row[2::stride])):
            if inside(*rgb):
                teal.add((gx, gy))
    while teal:   # each clump of teal samples (gaps of a sample allowed: the text)
        todo, cells = [teal.pop()], []
        while todo:
            cx, cy = todo.pop()
            cells.append((cx, cy))
            for nx in range(cx - 2, cx + 3):
                for ny in range(cy - 2, cy + 3):
                    if (nx, ny) in teal:
                        teal.remove((nx, ny))
                        todo.append((nx, ny))
        xs, ys = [c[0] for c in cells], [c[1] for c in cells]
        gx0, gx1, gy0, gy1 = min(xs), max(xs), min(ys), max(ys)
        if (gx1 - gx0) * step < least[0] or (gy1 - gy0) * step < least[1]:
            continue
        if len(cells) < TEST_FILL * (gx1 - gx0 + 1) * (gy1 - gy0 + 1):
            continue
        # The window around it, from the rows (columns) whose teal reaches the
        # panel's edge (text can cut others short): two each side and the top.
        by_row, by_col = {}, {}
        for cx, cy in cells:
            by_row.setdefault(cy, []).append(cx)
            by_col.setdefault(cx, []).append(cy)
        def framed(lines, edge, start, dx, dy):
            found = 0
            for line, at in sorted(lines.items()):
                end = edge(at)
                if abs(end - start) <= 1:
                    x, y = (end, line) if dx else (line, end)
                    found += test_frame(raw, w, h, x * step, y * step, dx, dy, inside=inside, dark_band=dark_band)
                    if found >= 2:
                        return True
            return False
        if framed(by_row, min, gx0, -1, 0) and framed(by_row, max, gx1, 1, 0) and framed(by_col, min, gy0, 0, -1):
            return (gx0 * step, gy0 * step, gx1 * step, gy1 * step)
    return None

DEAD_HP = 5.0        # % of the HP bar: under it you may be dead...
DEAD_HOLD_S = 2.0    # ...once it has stayed there this long, with the minimap still showing
GONE_HOLD_S = 10.0   # no bars and no minimap for this long: disconnected or at the login screen

class GameState:
    """ok / dead / offline / test from the readings. Changing maps fades the
    screen to black: the HP bar reads near 0 and the minimap's dot goes too,
    so a low HP bar only means dead while the minimap still shows (or, with
    no minimap set up, the Mana bar), and only after DEAD_HOLD_S. Bars and
    minimap gone only means disconnected after GONE_HOLD_S: a loading screen
    is over by then. The test popup needs two readings in a row."""
    def __init__(self, clock=time.monotonic):
        self.low_since = self.gone_since = None
        self.tests, self.clock = 0, clock

    def update(self, hp, mana, dot_seen, minimap_used, watches, popup=False, now=None):
        now = self.clock() if now is None else now
        if watches.get("login"):
            return "offline"
        self.tests = self.tests + 1 if popup else 0
        if watches.get("test") or self.tests >= 2:
            return "test"
        if watches.get("death"):
            return "dead"
        fading = minimap_used and not dot_seen   # the minimap's dot gone with the bars: a fade or loading screen
        gone = fading and hp in (None, 0) and mana in (None, 0)
        low = hp is not None and hp < DEAD_HP and not fading and (minimap_used or mana is None or mana > 0)
        self.gone_since = (now if self.gone_since is None else self.gone_since) if gone else None
        self.low_since = (now if self.low_since is None else self.low_since) if low else None
        if self.gone_since is not None and now - self.gone_since >= GONE_HOLD_S:
            return "offline"
        if self.low_since is not None and now - self.low_since >= DEAD_HOLD_S:
            return "dead"
        return "ok"

# ---- screen access ----------------------------------------------------------

def grab(sct, left, top, width, height):
    return sct.grab({"left": left, "top": top, "width": width, "height": height}).rgb

def read_bars(sct, bars):
    readings = {}
    for name, bar in bars.items():
        raw = grab(sct, bar["x1"], bar["y"], bar["x2"] - bar["x1"] + 1, 1)
        row = [tuple(raw[i:i + 3]) for i in range(0, len(raw), 3)]
        readings[name] = fill_percent(row, bar["color"], bar.get("tolerance", 60), step=bar.get("fade", 30))
    return readings

# ---- shape search: your PNGs matched across the screen (numpy) -----------------
# Colour can't pick out mobs on maps that share their colours (Perion's brown
# stumps and boars on brown rock). With numpy (pip install numpy), every
# animation frame of the map's mobs is matched across a band level with your
# feet instead, each colour part of it (outline, body, axe...) checked where
# it should be: a fast pass over the band, then a strict check of the best
# spots. Frames: mob.png plus mob.<anything>.png (tools/mob_frames.py fetches
# the stand, move and hit frames). Without numpy, colours as before.

FEET_SLACK = 28       # px a mob's feet may be above or below yours and still count as on your platform
REACH_BELOW = 80      # px more below your feet that still counts ("below" in mobs): mid-jump, or the platform read a bit high
AIR_PX = 12           # px between your tag's feet and the platform's that means you're in the air (the reach below applies)
FIRST_PASS = 0.45     # share of a frame's pixels matching its colours for a closer look
FRAMES_PER_SPOT = 3   # a mob's frames looked at closely per spot: the ones the fast pass liked best there
EFFECT_BRIGHT = 230   # a pixel this bright (any channel, 0-255) not matching the mob may be a hit effect over it
VISIBLE_MIN = 0.6     # ...but at least this much of the mob must be seen
KERNEL_MB = 250       # memory kept for a map's frames between readings (more is made afresh each reading)
MATCH_SLACK = 1       # px: a partly covered mob's edge pixels may find their colour this far away
COVERED = 0.1         # ...when this much of it is covered (effects, the screen's edge)

def grown(np, a, r):
    """`a` (0/1) spread `r` px every way: the most of each pixel's neighbours."""
    out = a.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dy or dx:
                src = a[max(0, dy):a.shape[0] + min(0, dy), max(0, dx):a.shape[1] + min(0, dx)]
                dst = out[max(0, -dy):a.shape[0] + min(0, -dy), max(0, -dx):a.shape[1] + min(0, -dx)]
                np.maximum(dst, src, out=dst)
    return out

def numpy_or_none():
    try:
        import numpy
        return numpy
    except ImportError:
        return None

def ffts(np):
    """(rfft2, irfft2): scipy's when installed (several times faster, every
    core), else numpy's."""
    try:
        from scipy import fft
        return (lambda a, size: fft.rfft2(a, size, workers=-1)), (lambda a, size: fft.irfft2(a, size, workers=-1))
    except ImportError:
        return np.fft.rfft2, np.fft.irfft2

def frame_files(sprites_dir, files):
    """{mob: [file, ...]}: each listed PNG and its animation frames
    (snail.png, snail.move0.png, snail.hit10.png ...)."""
    out = {}
    names = sorted(os.listdir(sprites_dir)) if os.path.isdir(sprites_dir) else []
    for f in files:
        mob = os.path.splitext(f)[0]
        found = [n for n in names if n == f or (n.startswith(mob + ".") and n.lower().endswith(SPRITE_TYPES))]
        if found:
            out[mob] = found
    return out

FRAMES_PER_MOB = 5   # animation frames of each mob searched for ("frames" in mobs; 0 = all of them)

def pick_frames(np, images, n):
    """Up to `n` of a mob's frames (0: all), the first (its own PNG) then each
    time the one least like those kept (by its outline; another size counts as
    unlike): the poses that matter most, as each frame costs search time."""
    if not n or len(images) <= n:
        return list(images)
    masks = [img[..., 3] >= 200 for img in images]
    def unlike(i, j):
        a, b = masks[i], masks[j]
        return float((a != b).sum()) / max(int(a.sum()), 1) if a.shape == b.shape else 1.0
    kept, rest = [0], list(range(1, len(images)))
    while rest and len(kept) < n:
        far = max(rest, key=lambda i: min(unlike(i, k) for k in kept))
        kept.append(far)
        rest.remove(far)
    return [images[i] for i in kept]

def fast_len(n):
    """The next size FFTs are quick at (2, 3 and 5 only)."""
    while True:
        m = n
        for p in (2, 3, 5):
            while m % p == 0:
                m //= p
        if m == 1:
            return n
        n += 1

def colour_parts(np, rgba):
    """A frame's colour parts: [(mean rgb, mask)] for groups of near shades
    (3% of it or more): outline, body, eye..."""
    solid = rgba[..., 3] >= 200
    a = rgba.astype(np.int32)
    key = (a[..., 0] // 48) * 100 + (a[..., 1] // 48) * 10 + a[..., 2] // 48
    out = []
    values, counts = np.unique(key[solid], return_counts=True)
    for v, n in zip(values, counts):
        if n >= solid.sum() * 0.03:
            m = solid & (key == v)
            out.append((tuple(float(c) for c in a[..., :3][m].mean(axis=0)), m.astype(np.float32)))
    return out

def strict_score(np, nears, parts, x, y, h, w, floor=0.08, hidden=None, loose=None, edges=None, visible=None):
    """Every part must be there: a geometric mean of how much of each part
    matches, weighted by its size (but no part below `floor`), so a small
    flickering one (flames, sparkles) can't veto a match and scenery sharing
    some colours can't pass. With `hidden` (off screen, or where the screen is
    near white, yellow or orange), a mob's pixel that doesn't match there is
    taken as covered by a hit effect or damage number, or past the screen's
    edge: not seen rather than wrong, as long as most of the mob (VISIBLE_MIN)
    is still seen. A mob partly covered so (COVERED or more) has blurred
    outlines too: with `loose` (gives the nears grown a px) and each part's `edges`, a
    pixel on a part's edge may then find its colour a px away."""
    total = sum(m.sum() for _, m in parts)
    hits = [near[y:y + h, x:x + w] for near in nears]
    covers = [None] * len(parts)
    if hidden is not None:
        b = hidden[y:y + h, x:x + w]
        covers = [m * b * (1 - hit) for hit, (_, m) in zip(hits, parts)]
        covered = sum(c.sum() for c in covers) / total
        if covered > 1 - (VISIBLE_MIN if visible is None else visible):
            covers = [None] * len(parts)   # too little of it seen to say
        elif covered >= COVERED and loose is not None:   # outlines blur around effects
            hits = [hit + (grow[y:y + h, x:x + w] - hit) * edge for hit, grow, edge in zip(hits, loose(), edges)]
            covers = [m * b * (1 - hit) for hit, (_, m) in zip(hits, parts)]
    wsum = logs = 0.0
    for hit, (_, m), cover in zip(hits, parts, covers):
        seen = m.sum() - (cover.sum() if cover is not None else 0)
        if seen < 1:
            continue   # all of it covered: nothing to go by
        share = float((hit * m).sum() / seen)
        weight = max(m.sum() / total, floor) * seen / m.sum()   # what's seen of it counts
        wsum += weight
        logs += weight * np.log(share + 0.05)
    return round(float(np.exp(logs / wsum) - 0.05), 3)

def part_edges(np, m):
    """A part's edge: its pixels with a neighbour outside it."""
    return m * grown(np, 1 - m, 1)

FULL_SEARCH_S = 0.0   # the whole field of view searched this often ("search_every" in mobs); 0: every reading. In
                      # between, the mobs found are followed (track): quicker, but a new mob waits for the next
                      # search. Replayed videos: searching every reading spots mobs soonest; following in between
                      # cost 0.1-0.25 s on average, up to 1 s
TRACK_REACH = 60      # px either side of where a mob was that it's looked for when followed (its walk, the camera's)
TRACK_RISE = 50       # ...and above and below (a jump moves the camera up and down)
TRACK_NEED = 0.75     # a mob just seen there needs this share of the usual match to be followed (hit effects cover it)

def search_due(now, searched_at, following, every=FULL_SEARCH_S):
    """Whether this reading runs the whole mob search: nothing being followed,
    or `every` seconds since the last (0: every reading). Otherwise the mobs
    found are followed. (Mid-jump is searched too: replayed videos found as
    many mobs in the air as on the ground.)"""
    return not following or searched_at is None or now - searched_at >= every

class ShapeSearch:
    """A map's mob frames (both facings, near-duplicates dropped), searched for
    in your field of view: the screen either side of you (as far as `sight`),
    at your level. Walking mobs count with their feet level with yours (give
    or take `slack`); flying ones (in `flyers`) when they're at your height
    (`body` px above your feet); with view "screen", anything on screen. A
    fixed band size keeps each frame's FFT computed once."""
    def __init__(self, np, frames, sight, width=None, slack=FEET_SLACK, body=0, flyers=(), view="level", height=None, below=0):
        """`frames`: {mob: [rgba array, ...]}; `width`, `height`: the screen's. `below`:
        px more under your feet still looked at (a mob's feet that far lower counts)."""
        self.np, self.sight, self.slack, self.frames, self.cache, self.cached = np, sight, slack, [], {}, 0
        self.below = max(0, int(below))
        self.last, self.searched_at, self.traces = [], None, {}   # the mobs last found or followed (with their frame), and when searched
        self.body, self.flyers, self.view = body, set(flyers), ("screen" if view == "screen" and height else "level")
        self.rfft, self.irfft = ffts(np)
        for mob, images in sorted(frames.items()):
            seen = []
            for rgba in images:
                for flipped in (False, True):
                    r = np.ascontiguousarray(rgba[:, ::-1] if flipped else rgba)
                    solid = r[..., 3] >= 200
                    if any(sh.shape == solid.shape and (sh != solid).sum() < 0.1 * solid.sum() for sh in seen):
                        continue   # much the same frame again
                    seen.append(solid)
                    parts = colour_parts(np, r)
                    if not parts:
                        continue
                    sizes = [float(m.sum()) for _, m in parts]
                    # The fast pass looks at the bigger parts only (10%+, or the
                    # 3 biggest); the strict check at all of them.
                    big = [i for i, n in enumerate(sizes) if n >= 0.1 * sum(sizes)] or \
                          sorted(range(len(parts)), key=lambda i: -sizes[i])[:3]
                    self.frames.append((mob, parts, r.shape[0], r.shape[1], big, sum(sizes[i] for i in big),
                                        [part_edges(np, m) for _, m in parts]))
        self.h = max([f[2] for f in self.frames] or [1])
        self.w = max([f[3] for f in self.frames] or [1])
        self.bh = height if self.view == "screen" else self.h + (body if self.flyers else 0) + 2 * slack + self.below
        self.bw = min(2 * sight, width or 2 * sight) + self.w
        self.fft = (fast_len(self.bh), fast_len(self.bw))   # wrap-around only reaches the edge rows/columns thrown away

    def search(self, screen, x, feet, tolerance=50, need=SHAPE_MIN, look=()):
        """Mobs level with you: [(score, mob, left, top, width, height)], best
        first, one per mob. `screen` is an (H, W, 3) array; x and feet are where
        you stand on it. For each mob in `look` (as found before), self.traces
        gets how much of it is still at its spot (its best strict score
        there, 0-1): a mob under hit effects still shows, a dead one doesn't."""
        self.traces = {}
        np = self.np
        H, W = screen.shape[:2]
        top = 0 if self.view == "screen" else feet + self.slack + self.below - self.bh
        left = max(-self.w, min(x - self.bw // 2, W + self.w - self.bw))   # centred on you, kept on the screen
        band = np.zeros((self.bh, self.bw, 3), np.float32)   # off screen: matches nothing
        y0, y1, x0, x1 = max(0, top), min(H, top + self.bh), max(0, left), min(W, left + self.bw)
        if y1 > y0 and x1 > x0:
            band[y0 - top:y1 - top, x0 - left:x1 - left] = screen[y0:y1, x0:x1]
        t2, near, loose, spectra, found, spots = float(tolerance) ** 2, {}, {}, {}, [], []
        hidden = np.ones((self.bh, self.bw), np.float32)   # off screen: not seen
        if y1 > y0 and x1 > x0:
            hidden[y0 - top:y1 - top, x0 - left:x1 - left] = (screen[y0:y1, x0:x1].max(axis=2) >= EFFECT_BRIGHT) \
                if EFFECT_BRIGHT else 0   # (on the screen's bytes: several times quicker than on the float copy)
        pp = np.einsum("ijk,ijk->ij", band, band)   # |p|^2 once: |p - c|^2 = |p|^2 - 2 p.c + |c|^2 per colour is then one product
        for i, (mob, parts, h, w, big, big_total, edges) in enumerate(self.frames):
            nears, F = [], None
            for j, (rgb, m) in enumerate(parts):
                key = tuple(int(c) // 16 for c in rgb)   # near shades share one map
                if key not in near:
                    c = np.array(rgb, np.float32)
                    near[key] = (pp - 2 * (band @ c) <= t2 - float(c @ c)).astype(np.float32)
                nears.append(near[key])
                if j not in big:
                    continue
                if key not in spectra:
                    spectra[key] = self.rfft(near[key], self.fft).astype(np.complex64)
                kernel = self.cache.get((i, j))
                if kernel is None:   # kept for every reading (single precision), up to KERNEL_MB; past that made each time
                    kernel = self.rfft(m[::-1, ::-1], self.fft).astype(np.complex64)
                    if self.cached + kernel.nbytes <= KERNEL_MB * 1e6:
                        self.cache[(i, j)], self.cached = kernel, self.cached + kernel.nbytes
                if F is None:
                    F = spectra[key] * kernel
                else:
                    F += spectra[key] * kernel   # (in place: no new array per part)
            first = self.irfft(F, self.fft)[h - 1:self.bh, w - 1:self.bw]
            first /= big_total
            if self.view != "screen":   # at your level: feet level with yours, or (flying) at your height
                lowest = self.bh - h - 2 * self.slack - self.below - (self.body if mob in self.flyers else 0)   # feet from slack above yours to slack + below under
                first[:max(0, lowest)] = 0
            for k in look:   # a mob seen before: the best spot near where it was, checked closely
                if k[1] != mob:
                    continue
                cx, cy, rx, ry = k[2] - left, k[3] - top, max(6, k[4] // 4), max(4, k[5] // 4)
                win = first[max(0, cy - ry):max(0, cy + ry + 1), max(0, cx - rx):max(0, cx + rx + 1)]
                if win.size:
                    vy, vx = divmod(int(win.argmax()), win.shape[1])
                    trace = strict_score(np, nears, parts, max(0, cx - rx) + vx, max(0, cy - ry) + vy, h, w, hidden=hidden,
                                         visible=TRACE_VISIBLE)
                    spot = hidden[max(0, cy):max(0, cy + k[5]), max(0, cx):max(0, cx + k[4])]
                    if spot.size and spot.mean() >= 0.5:
                        trace = 1.0   # mostly hit effects there: something is being hit, not gone
                    self.traces[k] = max(self.traces.get(k, 0.0), trace)
            if first.max() < FIRST_PASS:   # most frames: nowhere near (cheaper than listing the spots)
                continue
            ys, xs = np.nonzero(first >= FIRST_PASS)
            values = first[ys, xs]
            if len(values) > 2000:
                best = np.argpartition(-values, 2000)[:2000]
                ys, xs, values = ys[best], xs[best], values[best]
            order = np.argsort(-values)
            ys, xs = ys[order], xs[order]
            def grown_nears(parts=parts):   # the strict check's edge allowance, made only when a mob is partly covered
                out = []
                for rgb, _ in parts:
                    key = tuple(int(c) // 16 for c in rgb)
                    if key not in loose:
                        loose[key] = grown(np, near[key], MATCH_SLACK)
                    out.append(loose[key])
                return out
            frame = (mob, parts, h, w, list(nears), edges, grown_nears)
            for _ in range(12):   # the 12 best distinct spots (a strong one's neighbours don't crowd out the rest)
                if not len(ys):
                    break
                cy, cx = int(ys[0]), int(xs[0])
                apart = (np.abs(xs - cx) >= w // 2) | (np.abs(ys - cy) >= h // 2)
                ys, xs = ys[apart], xs[apart]
                spots.append((float(first[cy, cx]), i, cx, cy, frame))
        # The strict check, per mob and spot, with just the frames the fast pass liked best there (several
        # frames of a mob tend to point at the same spot; checking them all cost several times as much).
        spots.sort(key=lambda c: -c[0])
        places = []   # [mob, cx, cy, w, h, frames checked]
        for value, i, cx, cy, (mob, parts, h, w, nears, edges, grown_nears) in spots:
            place = next((p for p in places if p[0] == mob and abs(p[1] - cx) < max(w, p[3]) // 2
                          and abs(p[2] - cy) < max(h, p[4]) // 2), None)
            if place is None:
                place = [mob, cx, cy, w, h, 0]
                places.append(place)
            if place[5] >= FRAMES_PER_SPOT:
                continue
            place[5] += 1
            score = strict_score(np, nears, parts, cx, cy, h, w, hidden=hidden,
                                 loose=grown_nears if MATCH_SLACK else None, edges=edges)
            if score >= need:
                found.append((score, mob, left + cx, top + cy, w, h, i))
        found.sort(key=lambda f: -f[0])
        kept = []
        for f in found:   # one per mob: overlapping finds are the same one
            if all(abs((f[2] + f[4] / 2.0) - (k[2] + k[4] / 2.0)) > min(f[4], k[4]) * 0.6 for k in kept):
                kept.append(f)
        self.last = kept
        return [f[:6] for f in kept]

    def track(self, screen, tolerance=50, need=SHAPE_MIN, reach=TRACK_REACH, rise=TRACK_RISE):
        """Follows the mobs last found: each looked for only in a small window
        round where it was, with only its own frames (it may have turned or
        moved on in its walk), so a reading takes a few ms a mob instead of a
        whole search. [(score, mob, left, top, width, height)] like search();
        one not found again (killed, gone off, hidden) is let go, and the next
        whole search finds whatever's new."""
        np, H, W, t2 = self.np, screen.shape[0], screen.shape[1], float(tolerance) ** 2
        kept = []
        if not hasattr(self, "track_kernels"):
            self.track_kernels = {}   # (frame, part, window shape) -> its spectrum: windows are mostly one size
        for _, mob, left, top, w, h, last_frame in self.last:
            # The window round where it was; past the screen's edge it's blank and "not seen", as in search(), so
            # a mob partly off the screen is still followed.
            x0, y0, x1, y1 = left - reach, top - rise, left + w + reach, top + h + rise
            sx0, sy0, sx1, sy1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
            if sx1 - sx0 < 4 or sy1 - sy0 < 4:
                continue   # gone off the screen
            win = np.zeros((y1 - y0, x1 - x0, 3), np.float32)
            win[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] = screen[sy0:sy1, sx0:sx1]
            bright = (win.max(axis=2) >= EFFECT_BRIGHT).astype(np.float32) if EFFECT_BRIGHT else np.zeros(win.shape[:2], np.float32)
            hidden = np.ones(win.shape[:2], np.float32)   # off the screen: not seen; on it, hit effects aren't either
            hidden[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] = bright[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0]
            pp, near, spectra, loose, best = (win * win).sum(axis=2), {}, {}, {}, None
            shape = (fast_len(y1 - y0), fast_len(x1 - x0))
            # The frame it matched last first: mostly it still does, and the rest needn't be tried.
            order = [last_frame] + [i for i, f in enumerate(self.frames) if f[0] == mob and i != last_frame]
            for i in order:
                other, parts, fh, fw, big, big_total, edges = self.frames[i]
                if other != mob or fh > y1 - y0 or fw > x1 - x0:
                    continue
                if best and i != last_frame and best[6] == last_frame:
                    break   # the last frame still matches: done with this mob
                nears, F = [], None
                for j, (rgb, m) in enumerate(parts):
                    key = tuple(int(c) // 16 for c in rgb)
                    if key not in near:
                        c = np.array(rgb, np.float32)
                        near[key] = (pp - 2 * (win @ c) <= t2 - float(c @ c)).astype(np.float32)
                    nears.append(near[key])
                    if j in big:
                        if key not in spectra:
                            spectra[key] = self.rfft(near[key], shape)
                        kernel = self.track_kernels.get((i, j, shape))
                        if kernel is None:
                            if len(self.track_kernels) > 4000:
                                self.track_kernels = {}
                            kernel = self.track_kernels[(i, j, shape)] = self.rfft(m[::-1, ::-1], shape).astype(np.complex64)
                        product = spectra[key] * kernel
                        F = product if F is None else F + product
                if F is None:
                    continue
                first = self.irfft(F, shape)[fh - 1:y1 - y0, fw - 1:x1 - x0] / big_total
                if not first.size:
                    continue
                cy, cx = divmod(int(first.argmax()), first.shape[1])
                if first[cy, cx] < FIRST_PASS:
                    continue
                def grown_nears(parts=parts):   # the edge allowance, as in search()
                    out = []
                    for rgb, _ in parts:
                        key = tuple(int(c) // 16 for c in rgb)
                        if key not in loose:
                            loose[key] = grown(np, near[key], MATCH_SLACK)
                        out.append(loose[key])
                    return out
                score = strict_score(np, nears, parts, cx, cy, fh, fw, hidden=hidden,
                                     loose=grown_nears if MATCH_SLACK else None, edges=edges)
                if score >= need * TRACK_NEED and (best is None or score > best[0]):
                    best = (score, mob, x0 + cx, y0 + cy, fw, fh, i)
            spot = bright[max(0, top - y0):top - y0 + h, max(0, left - x0):left - x0 + w]
            if not best and spot.size and spot.mean() >= 0.5:   # mostly under hit effects: being hit, not gone
                best = (need, mob, left, top, w, h, last_frame)
            if best and all(abs((best[2] + best[4] / 2.0) - (k[2] + k[4] / 2.0)) > min(best[4], k[4]) * 0.6 for k in kept):
                kept.append(best)   # two followed onto the same mob: one
        self.last, self.traces = kept, {}
        return [f[:6] for f in kept]

TAG_NEED = 0.5       # how alike (normalised correlation, 0-1) a spot must be to your name tag; elsewhere is ~0.3 at most

class TagFinder:
    """You, by your name tag (marked at setup), matched by its pattern of
    light and dark (letters, outline, medal) rather than its exact colours:
    MapleStory's tag box is see-through, so its colour changes with whatever
    is behind you, and a match on colours fails against a bright sky. Looked
    for near where you were last (it hardly moves between readings), then
    further, then on the whole screen but the HUD. Returns the tag's
    top-left and how alike (0-1)."""
    def __init__(self, np, rgb, window=(260, 160), near=(90, 80), coarse=True):
        t = rgb.astype(np.float64)
        self.np, self.window, self.near, self.kernels, self.last = np, window, near, {}, None
        # Lost, the whole screen is searched at half size first (4x less work), then confirmed at full size.
        self.half = TagFinder(np, halved(np, rgb), coarse=False) if coarse and min(rgb.shape[:2]) >= 12 else None
        self.rfft, self.irfft = ffts(np)
        self.h, self.w = rgb.shape[:2]
        self.chans = []   # (channel, its zero-mean template, the template's norm), flat channels left out
        for c in range(3):
            t0 = t[..., c] - t[..., c].mean()
            norm = float(np.sqrt((t0 * t0).sum()))
            if norm > 1:
                self.chans.append((c, t0, norm))

    def likeness(self, area):
        """How alike each spot of `area` (H, W, 3) is to the tag: (H-h+1, W-w+1), -1 to 1."""
        np, h, w = self.np, self.h, self.w
        size = (fast_len(area.shape[0]), fast_len(area.shape[1]))
        if size not in self.kernels:
            self.kernels = {size: [self.rfft(t0[::-1, ::-1], size) for _, t0, _ in self.chans]}
        out = 0
        for (c, _, norm), kernel in zip(self.chans, self.kernels[size]):
            a = area[..., c].astype(np.float64)
            corr = self.irfft(self.rfft(a, size) * kernel, size)[h - 1:a.shape[0], w - 1:a.shape[1]]
            sums = [np.pad(v, ((1, 0), (1, 0))).cumsum(0).cumsum(1) for v in (a, a * a)]   # box sums from running totals
            s1, s2 = [v[h:, w:] - v[:-h, w:] - v[h:, :-w] + v[:-h, :-w] for v in sums]
            spread = np.sqrt(np.maximum(s2 - s1 * s1 / (h * w), h * w))   # flat areas: at least 1 level of spread
            out = out + corr / (spread * norm)
        return out / max(len(self.chans), 1)

    def find(self, screen, need=TAG_NEED, skip_bottom=80):
        np = self.np
        H, W = screen.shape[:2]
        bottom = H - skip_bottom   # the HUD is left out (your name shows there too)
        if self.last:   # close by first (it hardly moves between readings), then further
            lx, ly = self.last
            for wx, wy in (self.near, self.window):
                found = self._best(screen, (lx - wx, ly - wy, lx + self.w + wx, ly + self.h + wy), bottom, need)
                if found:
                    return found
        if not self.half:   # lost: the whole screen
            return self._best(screen, (0, 0, W, bottom), bottom, need)
        alike = self.half.likeness(halved(np, screen[:bottom]))   # lost: the best spot at half size...
        y, x = divmod(int(alike.argmax()), alike.shape[1])
        if alike[y, x] < need * 0.8:
            return None
        return self._best(screen, (2 * x - 8, 2 * y - 8, 2 * x + self.w + 8, 2 * y + self.h + 8), bottom, need)   # ...looked at closely

    def _best(self, screen, box, bottom, need):
        """The most alike spot in `box` (clipped to the screen above `bottom`), if alike enough."""
        x0, y0 = max(0, box[0]), max(0, box[1])
        area = screen[y0:min(bottom, box[3]), x0:min(screen.shape[1], box[2])]
        if area.shape[0] < self.h or area.shape[1] < self.w or not self.chans:
            return None
        alike = self.likeness(area)
        y, x = divmod(int(alike.argmax()), alike.shape[1])
        if alike[y, x] < need:
            return None
        self.last = (x + x0, y + y0)
        return x + x0, y + y0, round(float(alike[y, x]), 3)

def halved(np, a):
    """`a` at half size, each pixel the mean of four."""
    h, w = a.shape[0] // 2 * 2, a.shape[1] // 2 * 2
    a = a[:h, :w].astype(np.float64)
    return (a[0::2, 0::2] + a[1::2, 0::2] + a[0::2, 1::2] + a[1::2, 1::2]) / 4

HOLD_SECONDS = 0.6    # a mob missed this soon after it was seen still counts (one missed reading)...
HOLD_TRACE = 0.35     # ...if this much of it still shows where it was (under hit effects); else it's gone at once
TRACE_VISIBLE = 0.3   # (that check allows a mob mostly covered by an effect: 30% of it seen is enough)

class MobMemory:
    """Mobs seen a moment ago still count when a reading misses them: hit
    effects, skills and mist cover a mob for a frame or two mid-fight, and
    attacking shouldn't stop and start. A mob is held where it was last seen
    for `hold` seconds, but only while something of it is still there (`still`
    says so: a dead one is let go at once); a find of the same mob near there
    replaces it. A new map forgets everything."""
    def __init__(self, hold=HOLD_SECONDS):
        self.hold, self.seen, self.place = hold, [], None

    def recent(self, now, place=None):
        """The mobs that could be held now: [(score, mob, left, top, width, height)]."""
        return [k for t, k in self.seen if now - t <= self.hold] if place == self.place else []

    def update(self, found, now, place=None, still=None):
        """`found`: this reading's [(score, mob, left, top, width, height)];
        `still(mob)`: whether a mob missed now is still partly there.
        Returns them plus the held ones, each with a last field: True if held."""
        if place != self.place:
            self.seen, self.place = [], place
        def same(f, k):
            return f[1] == k[1] and abs((f[2] + f[4] / 2.0) - (k[2] + k[4] / 2.0)) <= max(f[4], k[4], 40)
        held = [k for t, k in self.seen if now - t <= self.hold and not any(same(f, k) for f in found)
                and (still is None or still(k))]
        self.seen = [(now, f) for f in found] + [(t, k) for t, k in self.seen if k in held]
        return [tuple(f) + (False,) for f in found] + [tuple(k) + (True,) for k in held]

# ---- tuning live: looser / stricter mob colours ------------------------------

TOL_STEP, TOL_MIN, TOL_MAX = 5, 10, 100

def mob_tolerance(config, name):
    """How close a pixel's colour must be to a mob colour on this map: its own
    "tolerance" if tuned, else the setup's (40 by default)."""
    mb = config.get("mobs") or {}
    found = config.get("maps", {}).get(name) if name else None
    return (found or {}).get("tolerance", mb.get("tolerance", 40))

def tune_tolerance(config, name, step):
    """Looser (+1) or stricter (-1) mob colours on the map you're on (or, with
    no taught map, the setup's): tolerance moves TOL_STEP within TOL_MIN-TOL_MAX.
    Returns (what was tuned, new tolerance), or None with no mob colours here."""
    mb = config.get("mobs")
    found = config.get("maps", {}).get(name) if name else None
    target = found or mb
    if not mb or not target or not target.get("colors"):
        return None
    target["tolerance"] = min(TOL_MAX, max(TOL_MIN, mob_tolerance(config, name) + step * TOL_STEP))
    return (name if found else "every map"), target["tolerance"]

SETTLE_SECONDS = 5.0  # how long you must stand still somewhere new before you're looked for from there

class Ground:
    """The height you look for mobs at: your feet where you last stood. While
    you jump, climb or fall the minimap dot moves up and down, so the field of
    view stays on the platform you left (and follows you sideways); once the
    dot has been still for `settle` seconds you've settled, and it moves to
    wherever your feet are now (and follows them while you stay). A quick hop
    onto a ledge and back doesn't move it. The dot shows where you really are,
    whatever the camera does; without a dot, your name tag being still is
    used instead."""
    def __init__(self, settle=SETTLE_SECONDS, slack=1.0, tag_slack=4):
        self.settle, self.slack, self.tag_slack = settle, slack, tag_slack
        self.feet, self.last, self.since = None, None, None

    def update(self, you, dot_y=None, now=0.0):
        """`you`: (x, feet) from your name tag, or None; `dot_y`: the minimap
        dot's height in minimap pixels, or None; `now`: seconds. Returns
        (x, feet to look at), or None when you aren't found."""
        if not you:
            self.last = None
            return None
        x, feet = you
        same = False
        if self.last is not None:
            last_dot, last_feet = self.last
            if dot_y is not None and last_dot is not None:
                same = abs(dot_y - last_dot) <= self.slack           # the camera may move; the dot only moves with you
            else:
                same = abs(feet - last_feet) <= self.tag_slack
        if not same:
            self.since = now                                          # moving: the clock starts again
        self.last = (dot_y, feet)
        if self.feet is None or now - self.since >= self.settle:
            self.feet = feet
        return x, self.feet

    def reset(self):
        self.feet, self.last, self.since = None, None, None

def same_minimap(a, b, slack=4):
    """Two minimap boxes that are the same one, found a few pixels apart."""
    return bool(a and b) and all(abs(a[k] - b[k]) <= slack for k in ("x1", "y1", "x2", "y2"))

class Screen:
    """Everything read each tick, plus what's learned at start (the map)."""
    def __init__(self, sct, config, sprites_dir=None):
        mm = config.get("minimap") or {}
        self.sprites_dir, self.shapes = sprites_dir, {}
        self.sct, self.config, self.state = sct, config, GameState()
        self.minimap = MinimapTracker(threshold=mm.get("map_mismatch", 0.6))
        # A sliding minimap is only followed where the game has one ("sliding_minimap" in the
        # setup file says so either way); otherwise the dot is the map position, always the same.
        self.slides = bool(config.get("sliding_minimap", not (GAMES.get(config.get("game")) or {}).get("whole_map")))
        area, maps = config.get("map_name"), config.get("maps", {})
        usual = {n: m for n, m in maps.items() if not m.get("name_area")}
        self.maps = MapReader(usual, area.get("light", 170)) if area and maps else None
        # Maps whose name is somewhere else (F12): looked for there when the usual place has none.
        self.own_names = [(m["name_area"], MapReader({n: m}, m["name_area"].get("light", 170)))
                          for n, m in sorted(maps.items()) if m.get("name_area") and name_taught(m)]
        self.boxes = []   # the mobs last found, in screen coordinates (for the game layer)
        self.current = None   # the taught map you're on ("" untaught, None no map library)
        self.sizes = {}       # {map: its minimap size}, from map.json
        self.box = None       # the minimap box last read
        self.frames = {}      # {map: its minimap box as last found on screen}
        self.tracked = None   # the map the slide (map position) is counted on
        self.map_mobs = {}    # {map: its mob PNGs}, from map.json
        self.searches = {}    # {map: ShapeSearch}
        self.you = None       # (x, feet) where your name tag says you are, else None
        self.memory = MobMemory((config.get("mobs") or {}).get("hold", HOLD_SECONDS))
        self.ground = Ground((config.get("mobs") or {}).get("settle", SETTLE_SECONDS))
        self.seen = None   # where your name tag puts your feet right now
        self.clock = time.monotonic
        self.np, self.tag, self.pixels, self.frame_now, self.raw = numpy_or_none(), None, None, False, None
        self.popup = None     # the test popup's panel on screen last reading, else None
        self.popup_at = None  # when it was last looked for
        tag = (config.get("mobs") or {}).get("tag")
        if self.np and tag:
            rgb = self.np.frombuffer(bytes.fromhex(tag["rgb"]), self.np.uint8).reshape(tag["h"], tag["w"], 3)
            self.tag = TagFinder(self.np, rgb)
        apply_game(config)

    def frame(self):
        """The minimap's frame this reading ((right, bottom) on screen), for an
        automatic minimap; None otherwise or when it isn't on screen."""
        mm = self.config.get("minimap")
        if not mm or not mm.get("auto"):
            return None
        if self.frame_now is False:
            self.frame_now = minimap_frame(self.sct, mm)
        return self.frame_now

    def map_name(self):
        """The taught map you're on ("" for one you haven't taught), or None
        without a map library."""
        if not self.maps and not self.own_names:
            return None
        name = ""
        if self.maps:
            a = self.config["map_name"]
            w, h = a["x2"] - a["x1"] + 1, a["y2"] - a["y1"] + 1
            name = self.maps.read(grab(self.sct, a["x1"], a["y1"], w, h), w, h, name_limit(a, self.frame()))
        for a, reader in self.own_names if not name else ():
            w, h = a["x2"] - a["x1"] + 1, a["y2"] - a["y1"] + 1
            name = reader.read(grab(self.sct, a["x1"], a["y1"], w, h), w, h)
            if name:
                break
        return name

    def minimap_box(self, name):
        """The minimap's box on this map: this map's own size from map.json if
        it has one (from the minimap's top-left corner), else the minimap's
        frame as found on screen (automatic), else the setup's box."""
        mm, size = self.config.get("minimap"), self.sizes.get(name) if name else None
        if not mm:
            return mm
        if size:
            return map_box(mm, size)
        frame = self.frame()
        if frame:
            self.frames[name] = dict(mm, x2=frame[0] - 1, y2=frame[1] - 1)
            return self.frames[name]
        if name in self.frames:   # hidden for a moment (a window, a hit effect): this map's last one stands
            return self.frames[name]
        return mm

    def mob_shapes(self, name, found, tolerance):
        """The sprites to check clumps against on this map (sprite_shapes), from
        its PNGs; None without them (no sprites folder, Pillow or PNGs), when
        its "shape" is 0, or for colours marked by hand."""
        if not self.sprites_dir or not found.get("sprites") or not found.get("shape", SHAPE_MIN):
            return None
        key = (name, tolerance, tuple(map(tuple, found["colors"])))
        if key not in self.shapes:
            try:
                taught = set(found["sprites"])
                sprites = map_sprites(self.sprites_dir, name) if name else load_sprites(self.sprites_dir, taught)
                sprites = {n: v for n, v in sprites.items() if n in taught}
            except (SystemExit, Exception):   # no Pillow, unreadable files: colour only
                sprites = {}
            self.shapes[key] = sprite_shapes(sprites, color_table(found["colors"], tolerance)) or None
        return self.shapes[key]

    def shot(self):
        """The whole (primary) screen's pixels, grabbed once per reading:
        (rgb bytes, its monitor)."""
        if self.raw is None:
            monitors = self.sct.monitors
            m = monitors[1] if len(monitors) > 1 else monitors[0]
            self.raw = (grab(self.sct, m["left"], m["top"], m["width"], m["height"]), m)
        return self.raw

    def screen(self):
        """The whole (primary) screen as an array, once per reading, for the
        name tag and the shape search; (array, left, top)."""
        if self.pixels is None:
            shot, m = self.shot()
            self.pixels = (self.np.frombuffer(shot, self.np.uint8).reshape(m["height"], m["width"], 3), m["left"], m["top"])
        return self.pixels

    def test_popup(self):
        """The game's test popup's panel on screen (x0, y0, x1, y1), or None;
        only for a game whose popup is known, unless the setup turns it off."""
        if not (GAMES.get(self.config.get("game")) or {}).get("test_popup") or not self.config.get("test_popup", True):
            return None
        shot, m = self.shot()
        box = find_test_popup(shot, m["width"], m["height"])
        return box and (box[0] + m["left"], box[1] + m["top"], box[2] + m["left"], box[3] + m["top"])

    def find_you(self, dot_y=None):
        """Where you are: your name tag's place on screen (self.seen), and the
        field of view's place (self.you): that, but at the height of the
        platform you last stood on while you jump or climb (Ground). Both None
        when your tag isn't found (then the box from setup is used)."""
        mb = self.config.get("mobs") or {}
        self.seen = None
        if self.tag:
            pixels, ox, oy = self.screen()
            found = self.tag.find(pixels)
            if found:
                self.seen = tag_feet(found[0] + ox, found[1] + oy, mb["tag"]["w"])   # from the tag itself
        self.you = self.ground.update(self.seen, dot_y, self.clock())
        return self.you

    def shape_search(self, name, air=False):
        """The map's ShapeSearch: numpy, a taught map and its mob frames (from
        map.json); None otherwise. `air`: the one reaching REACH_BELOW ("below")
        px further under your feet, for readings where your name tag and the
        platform you stood on disagree (mid-jump, or the platform read a bit
        high): a taller band is about twice as slow, so not for every reading."""
        if not self.np or not name or not self.sprites_dir or name not in self.map_mobs:
            return None
        below = (self.config.get("mobs") or {}).get("below", REACH_BELOW) if air else 0
        if air and not below:
            air = False
        key = (name, air)
        if key not in self.searches:
            if not any(k[0] == name for k in self.searches):
                self.searches = {}   # only this map's: each holds its frames' spectra, too much to keep for every map
            mb = self.config["mobs"]
            try:
                from PIL import Image
                frames = {}
                for mob, files in frame_files(self.sprites_dir, self.map_mobs[name] or []).items():
                    files = sorted(files, key=lambda f: f != mob + ".png")   # your own PNG first
                    images = [self.np.asarray(Image.open(os.path.join(self.sprites_dir, f)).convert("RGBA")) for f in files]
                    frames[mob] = pick_frames(self.np, images, mb.get("frames", FRAMES_PER_MOB))
            except Exception:   # no Pillow, unreadable files
                frames = {}
            sight = int(mb.get("reach", 350) * mb.get("sight", SIGHT))
            monitors = self.sct.monitors
            m = monitors[1] if len(monitors) > 1 else monitors[0]
            files = frame_files(self.sprites_dir, self.map_mobs[name] or [])
            flyers = {mob for mob, names in files.items() if any(".fly" in n for n in names)}
            body = mb.get("bottom", mb["y"]) - mb.get("top", mb["y"])
            self.searches[key] = ShapeSearch(self.np, frames, sight, m["width"], body=body, flyers=flyers,
                                             view=mb.get("view", "level"), height=m["height"], below=below) if frames else None
        return self.searches[key]

    def mobs(self, name):
        """Mob fields for the reading (see mob_fields): by shape with numpy and
        the map's frames; else with this map's colours when it's taught, or the
        ones from setup. {} without a mob detector."""
        self.boxes = []
        mb = self.config.get("mobs")
        if mb and "x" in mb and self.you:   # follow you: the box moves with your name tag
            height = mb.get("bottom", mb["y"]) - mb.get("top", mb["y"])
            mb = dict(mb, x=self.you[0], y=self.you[1] - height // 2, top=self.you[1] - height, bottom=self.you[1])
        # Mid-jump or the platform read a little off (your tag's feet and the platform's apart):
        # reach REACH_BELOW further down for this reading; otherwise the quicker search.
        air = bool(self.seen and self.you and abs(self.seen[1] - self.you[1]) > AIR_PX)
        search = self.shape_search(name, air) if mb else None
        if search:
            pixels, ox, oy = self.screen()
            x, feet = (self.you or (mb["x"], mb.get("bottom", mb["y"])))
            entry = self.config.get("maps", {}).get(name) or {}
            now = self.clock()
            recent = self.memory.recent(now, name)
            look = [(sc, mob, left - ox, top - oy, w, h) for sc, mob, left, top, w, h in recent]
            tolerance, need = mob_tolerance(self.config, name) + 10, entry.get("shape", SHAPE_MIN)
            if search_due(now, search.searched_at, bool(search.last), mb.get("search_every", FULL_SEARCH_S)):
                found = search.search(pixels, x - ox, feet - oy, tolerance, need, look)
                search.searched_at = now
            else:
                found = search.track(pixels, tolerance, need)   # between whole searches: follow the ones found (fast)
            found = [(score, mob, left + ox, top + oy, w, h) for score, mob, left, top, w, h in found]
            traces = {r: search.traces.get(k, 0.0) for r, k in zip(recent, look)}
            still = lambda k: traces.get(k, 0.0) >= HOLD_TRACE   # partly covered, not gone
            view = {"L": [], "R": []}
            for score, mob, left, top, w, h, held in self.memory.update(found, now, name, still):
                near = 0 if left <= x <= left + w else min(abs(left - x), abs(left + w - x))
                view["R" if left + w / 2.0 >= x else "L"].append((near, mob))
                self.boxes.append((left, top, left + w, top + h, mob, 1, score, held))
            for side in view:
                view[side].sort(key=lambda m: m[0])
            return mob_fields(view, mb.get("reach", 350))
        found = self.config.get("maps", {}).get(name) if name else None
        found = found or mb
        if not mb or not found or not found.get("colors"):
            return {}
        if not found.get("cell"):   # older setups: sides only, in your reach
            left, top, w, h = mob_area(mb, self.sct.monitors[0])
            return {"mobs": mob_sides(grab(self.sct, left, top, w, h), w, h, found["colors"], mb.get("tolerance", 40),
                                      mb.get("gap", 40), mid=mb["x"] - left, step_x=found.get("step_x", 6),
                                      step_y=found.get("step_y", 8), min_hits=found.get("min_hits", 3))}
        left, top, w, h = mob_area(mb, self.sct.monitors[0], mb.get("sight", SIGHT))
        boxes, tolerance = [], mob_tolerance(self.config, name)
        view = mob_view(grab(self.sct, left, top, w, h), w, h, found["colors"], tolerance, mb.get("gap", 40),
                        mid=mb["x"] - left, step=found.get("step_x", 6), min_hits=found.get("min_hits", 3),
                        cell=found["cell"], names=found.get("names"), mob_w=found.get("mob_w", 0), boxes=boxes,
                        shapes=self.mob_shapes(name, found, tolerance), shape_min=found.get("shape", SHAPE_MIN))
        self.boxes = [(x0 + left, y0 + top, x1 + left, y1 + top) + tuple(rest) for x0, y0, x1, y1, *rest in boxes]
        return mob_fields(view, mb.get("reach", 350))

    def read(self):
        c = self.config
        self.pixels, self.frame_now, self.raw = None, False, None   # a fresh screen this reading
        out = read_bars(self.sct, c.get("bars", {}))
        name = self.map_name()   # first: the map decides the minimap's size
        if name != self.current:
            self.ground.reset()   # another map: no platform yet
        self.current = name
        dot, world, mm, dot_y = None, None, self.minimap_box(name), None
        if mm:
            if mm != self.box:
                if same_minimap(self.box, mm) and name == self.tracked:
                    self.minimap.prev = None   # the same minimap a pixel or two off: the slide (and home) carry on
                else:   # another map, or another size: the slide so far doesn't carry over
                    self.minimap = MinimapTracker(threshold=mm.get("map_mismatch", 0.6))
                self.box, self.tracked = mm, name
            w, h = mm["x2"] - mm["x1"] + 1, mm["y2"] - mm["y1"] + 1
            raw = grab(self.sct, mm["x1"], mm["y1"], w, h)
            dot = find_dot(raw, w, h, mm["dot"], mm.get("tolerance", 40), top=mm.get("header", 0))
            if dot:                      # a login or loading screen isn't the map
                if self.slides:
                    self.minimap.update(raw, w, h)
                    world = self.minimap.world(dot, w, h)
                else:
                    world = (round(dot[0] * 10), round(dot[1] * 10))
                dot_y = dot[1] * (h - 1) / 100.0   # minimap px: is it still? (Ground)
        self.find_you(dot_y)   # after the minimap: jumping, the field of view stays on your platform
        found = self.mobs(name)
        mobs = found.pop("mobs", None)   # None: no mob detector, so the pad doesn't wait for mobs
        watches = {}
        for what, mark in c.get("watch", {}).items():   # (not `name`: that's the map's)
            watches[what] = patch_matches(grab(self.sct, mark["x"] - 2, mark["y"] - 2, 5, 5), bytes(mark["patch"]))
        now = self.clock()
        if self.popup_at is None or now - self.popup_at >= TEST_EVERY_S or now < self.popup_at:
            self.popup, self.popup_at = self.test_popup(), now   # in between, the last look stands
        out["state"] = self.state.update(out.get("hp"), out.get("mana"), dot is not None, bool(mm), watches, self.popup is not None,
                                         self.clock())
        out["x"], out["y"] = dot if dot else (None, None)
        out["wx"], out["wy"] = world if world else (None, None)   # for stuck: moves even when the dot doesn't
        out["mobs"] = mobs
        out.update(found)                # ml/mr/dl/dr/mn: counts, distances, nearest mob's name
        if found.get("mn"):
            out["mn"] = safe_name(found["mn"])
        if name is not None:
            # A map you haven't taught: its mark (so the pad still knows it's another map), or "-" with no name to go by.
            out["map"] = safe_name(name) if name else (self.maps.mark if self.maps and self.maps.mark else "-")
        return out

# ---- setup --------------------------------------------------------------------

# ---- hotkeys that work while the game has focus -----------------------------
# A keyboard hook (pynput) only hears keys meant for programs at its own
# level: a game running as administrator, or its anti-cheat, keeps them from
# it, so F8 only worked with the terminal in front. On Windows the keys' state
# is read directly instead (GetAsyncKeyState), which needs no hook.

KEYS = {"f6": 0x75, "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B, "esc": 0x1B}   # Windows key codes

class KeyEdges:
    """Which keys went down since the last look, from the keys down now."""
    def __init__(self):
        self.down = set()

    def update(self, down_now):
        pressed = [k for k in KEYS if k in down_now and k not in self.down]
        self.down = set(down_now)
        return pressed

class Keys:
    """Calls on_key("f6" ... "f12" or "esc") on its own thread, wherever the
    focus is."""
    def __init__(self, on_key):
        self.on_key, self.stopped, self.listener = on_key, threading.Event(), None

    def start(self):
        if sys.platform == "win32":
            threading.Thread(target=self._poll, daemon=True).start()
        else:
            from pynput import keyboard
            names = {getattr(keyboard.Key, k): k for k in KEYS}
            self.listener = keyboard.Listener(on_press=lambda key: key in names and self.on_key(names[key]))
            self.listener.start()
        return self

    def _poll(self):
        import ctypes
        state, edges = ctypes.windll.user32.GetAsyncKeyState, KeyEdges()
        while not self.stopped.is_set():
            for name in edges.update({k for k, vk in KEYS.items() if state(vk) & 0x8000}):
                self.on_key(name)
            time.sleep(0.02)

    def close(self):
        self.stopped.set()
        if self.listener:
            self.listener.stop()

# Every key, from the keyboard or a pad button, goes to whoever is listening
# (a setup step waiting for F8, the game layer).
_listeners = []
_keyboard = []

def listen(fn):
    """Calls fn(key) for each key until the returned function is called."""
    _listeners.append(fn)
    if not _keyboard:   # the keyboard is watched once, from the first listener on
        try:
            _keyboard.append(Keys(press).start())
        except Exception as e:   # no keyboard access (e.g. no display): pad buttons still work
            _keyboard.append(None)
            print("(keyboard keys off: %s; the pad's setup buttons still work)" % e)
    return lambda: fn in _listeners and _listeners.remove(fn)

def press(key):
    for fn in list(_listeners):
        try:
            fn(key)
        except Exception as e:   # one listener's error mustn't stop the keys (their thread would die with it)
            report_error(e)

# The pad's setup layer buttons ("tool" steps) and the keys they stand for.
PAD_KEYS = {"mark": "f8", "skip": "esc", "map": "f9", "outlines": "f10", "hide": "f11", "looser": "f6", "stricter": "f7", "area": "f12"}

def pointer():
    """Where the mouse pointer is on the screen."""
    if sys.platform == "win32":
        import ctypes
        class Point(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        p = Point()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(p))
        return p.x, p.y
    from pynput import mouse
    return tuple(int(v) for v in mouse.Controller().position)

CANCELLED = [None]   # the key that ended the last mark_points early, if one did

def mark_points(prompt, count, cancel=("esc",)):
    """Hover and press F8 to mark up to `count` points; Esc (or any key in
    `cancel`) ends early (or skips)."""
    points, done = [], threading.Event()
    say(prompt, sticky=True)
    CANCELLED[0] = None
    def on_key(name):
        if done.is_set():
            return
        if name in cancel:
            CANCELLED[0] = name   # which key ended it (the one-time questions tell Esc from F9)
            done.set()
        elif name == "f8":
            points.append(pointer())
            say("  marked %d,%d" % points[-1] + ("" if len(points) == count else " - next: F8, or Esc"), sticky=len(points) < count)
            if len(points) == count:
                done.set()
    stop = listen(on_key)
    done.wait()
    stop()
    return points

def pixel(sct, x, y):
    return list(grab(sct, x, y, 1, 1)[:3])

REACH = 300        # px your attack reaches each way, by default ("reach" in mobs)
HITBOX_PAD = 40    # px the hitbox reaches above your head and below your feet ("pad" in mobs)

def mob_area(mb, screen, sight=1.0):
    """The hitbox either side of your character, clipped to the screen: as
    tall as your character (head to feet, when marked; else `band` px above
    and below), `reach` px to each side (`sight` times that, to see mobs out of
    reach), and REACH_BELOW ("below") px more under your feet. Returns (left,
    top, width, height)."""
    reach = int(mb.get("reach", REACH) * sight)
    pad = mb.get("pad", HITBOX_PAD) if "top" in mb else 0   # above your head and below your feet
    top = mb["top"] - pad if "top" in mb else mb["y"] - mb.get("band", 80)
    bottom = (mb["bottom"] + pad if "bottom" in mb else mb["y"] + mb.get("band", 80)) + mb.get("below", REACH_BELOW)
    left, top = max(screen["left"], mb["x"] - reach), max(screen["top"], top)
    right = min(screen["left"] + screen["width"], mb["x"] + reach)
    bottom = min(screen["top"] + screen["height"], bottom)
    return left, top, right - left, bottom - top

def hitbox(head, feet, reach_point):
    """Mob settings from your character's head and feet and how far your
    attack reaches to one side (all screen points)."""
    x, top, bottom = (head[0] + feet[0]) // 2, min(head[1], feet[1]), max(head[1], feet[1])
    return {"x": x, "y": (top + bottom) // 2, "top": top, "bottom": bottom,
            "reach": max(abs(reach_point[0] - x), 40), "gap": max(20, (bottom - top) // 3)}

def setup_mobs(sct, config, sprites_dir):
    """The mob detector: from sprite PNGs in `sprites_dir` if there are any,
    else from up to 3 mobs marked on screen. Either way it starts with your
    name tag (your feet are just above its middle, your head a character's
    height above them) and how far your attack reaches."""
    listed = map_names(sprites_dir)
    # With maps listed, the PNGs in mobs are their shared library: each map
    # learns just its own (F9 / --map), so none are learned for every map here.
    sprites = {} if listed else load_sprites(sprites_dir)
    mobs = {"tolerance": 40}
    box = "Name tag: hover the TOP-LEFT corner of YOUR name tag (its medal too), F8; then its BOTTOM-RIGHT corner, F8"
    if sprites or listed:
        if sprites:
            say("Found %d mob sprite(s) in %s." % (len(sprites), sprites_dir))
        pts = mark_points(box + " (Esc skips). Mobs nearby are fine.", 2)
        if len(pts) < 2:
            say("  skipped"); return
        if not set_hitbox(sct, mobs, *pts):
            return
        mobs["sight"] = SIGHT
        learned = learn_here(sct, mobs, sprites) if sprites else None
        if learned:
            mobs.update(learned)
        elif not listed:
            say("  No usable mob colours: mob detection is off."); return
        else:   # each map brings its own colours (F9 / --map)
            say("  Mobs come from %s: teach each map with F9 (or Which map on the pad)." % MAP_LIST)
    else:
        if os.path.isdir(sprites_dir) and any(n.lower().endswith(SPRITE_TYPES) for n in os.listdir(sprites_dir)):
            say("No readable sprites in %s, so mark mobs on screen instead." % sprites_dir)
        pts = mark_points(box + "; then up to 3 mobs (different kinds), F8 each; Esc when done", 5)
        if len(pts) < 3:
            say("  skipped"); return
        if not set_hitbox(sct, mobs, *pts[:2]):
            return
        mobs["colors"] = [pixel(sct, x, y) for x, y in pts[2:]]
    config["mobs"] = mobs

TAG_GAP = 7            # px from your feet down to the top of your name tag (MapleStory draws it there)
CHARACTER_HEIGHT = 73  # px from your feet to the top of your head: every character is the same size

def tag_feet(x1, y1, w):
    """Where your feet are, from your name tag's top-left and width: just above
    its middle (a medal beside the name is part of the tag, centred with it)."""
    return x1 + w // 2, y1 - TAG_GAP

def tag_box(a, b):
    """The tag's (x1, y1, x2, y2) from two corners, or None if too small for one."""
    x1, y1, x2, y2 = min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])
    return (x1, y1, x2, y2) if x2 - x1 >= 10 and y2 - y1 >= 6 else None

def keep_tag(sct, mobs, box):
    """Keeps the tag in `box` as your marker on screen."""
    x1, y1, x2, y2 = box
    w, h = x2 - x1 + 1, y2 - y1 + 1
    fx, fy = tag_feet(x1, y1, w)
    mobs["tag"] = {"x": x1 - fx, "y": y1 - fy, "w": w, "h": h, "rgb": grab(sct, x1, y1, w, h).hex()}
    say("  Name tag kept (%d x %d px): you'll be followed wherever the camera puts you." % (w, h))

def set_hitbox(sct, mobs, corner_a, corner_b, reach_point=None):
    """Your hitbox from your name tag's corners: your character's height (plus
    HITBOX_PAD above and below) and REACH px each way, or as far as
    `reach_point` if given (False if the tag's too small to be one)."""
    box = tag_box(corner_a, corner_b)
    if not box:
        say("  That's too small for a name tag: skipped"); return False
    fx, fy = tag_feet(box[0], box[1], box[2] - box[0] + 1)
    mobs.update(hitbox((fx, fy - CHARACTER_HEIGHT), (fx, fy), reach_point or (fx + REACH, fy)))
    keep_tag(sct, mobs, box)
    say("  Hitbox: your feet at %d,%d, %d px to each side." % (fx, fy, mobs["reach"]))
    return True

def mark_tag(sct, mobs, skip="Esc skips", cancel=("esc",)):
    """Your name tag, so you're found wherever the camera puts you (your feet
    are just above its middle, so they needn't be marked)."""
    pts = mark_points("Name tag: hover the TOP-LEFT corner of YOUR name tag (its medal too), F8; "
                      "then its BOTTOM-RIGHT corner, F8 (%s)" % skip, 2, cancel)
    if len(pts) < 2:
        say("  skipped: you're looked for where you stood at setup"); return
    box = tag_box(*pts)
    if not box:
        say("  That's too small for a name tag: skipped"); return
    keep_tag(sct, mobs, box)

def retag(path):
    """--tag: mark just your name tag, keeping the rest of the setup."""
    import mss
    config = load_config(path)
    mobs = config.get("mobs")
    if not mobs or "bottom" not in mobs:
        raise SystemExit("Mark your hitbox first: python screen_stats.py --mobs")
    mark_tag(mss.mss(), mobs)
    save_config(path, config)
    say("Saved %s" % path)

def learn_here(sct, mobs, sprites):
    """Mob settings for `sprites` against the map you're on, watched for 4 s
    over the area you look for mobs in. None if no colour of theirs is usable."""
    left, top, w, h = mob_area(mobs, sct.monitors[0], mobs.get("sight", SIGHT))
    say("  Looking at the map for 4 s...")
    shots = []
    for _ in range(5):
        shots.append(grab(sct, left, top, w, h))
        time.sleep(0.8)
    learned, report = learn_mob_colors(sprites, shots, w, h, mobs.get("tolerance", 40), mobs.get("gap", 40), mobs["x"] - left)
    say("\n".join(report))
    if not learned["colors"]:
        return None
    return {"colors": learned["colors"], "step_x": learned["step"], "step_y": learned["step"], "cell": learned["cell"],
            "min_hits": learned["min_hits"], "names": learned["names"], "mob_w": learned["mob_w"], "sprites": sorted(sprites)}

def mark_map_name(config, skip="Esc skips", cancel=("esc",)):
    pts = mark_points("Map name: hover the TOP-LEFT of the map's name, F8; then its BOTTOM-RIGHT, a bit past where "
                      "the longest name would end, F8 (%s)" % skip, 2, cancel)
    if len(pts) < 2:
        say("  skipped"); return None
    (ax, ay), (bx, by) = pts
    config["map_name"] = {"x1": min(ax, bx), "y1": min(ay, by), "x2": max(ax, bx), "y2": max(ay, by), "light": 170}
    return config["map_name"]

MAP_LIST = "map.json"   # in the mob sprites folder

def map_entries(data):
    """map.json in any of its forms as a list of maps, each {"name": ..., ...}
    in the file's order: a list of objects (the current form), or an object of
    names to objects or to mob lists (1.17.1). Anything else is kept as is."""
    if isinstance(data, list):
        return [dict(e) if isinstance(e, dict) else e for e in data]
    if isinstance(data, dict):
        return [dict({"name": n}, **(v if isinstance(v, dict) else {"mobs": v})) for n, v in data.items()]
    return None

def read_map_list(sprites_dir):
    """Your maps, from mobs/map.json, with the PNGs in mobs itself, so a mob
    found on several maps is kept once:

        [{"name": "Rocky Road II", "mobs": ["red-snail.png", "orange-mushroom.png"],
          "minimap": {"width": 178, "height": 96}}, ...]

    "minimap" is that map's minimap size in px (from the setup's top-left
    corner; F9 fills it in), or, marked by hand with F12, the map picture's
    own box: "left"/"top" px from the setup's corner, then its width and
    height. Other keys are kept for later. The 1.17.1 form,
    {"Rocky Road II": ["red-snail.png", ...]}, still reads.
    Returns ({map: {"mobs": [file, ...], "minimap": {...} or None}}, [problem,
    ...]); listed files that aren't there and bad entries are problems, not
    fatal. Without map.json, folders per map (mobs/<map>/*.png, the older
    layout) are the maps, each with mobs None: the whole folder."""
    path = os.path.join(sprites_dir, MAP_LIST)
    if not os.path.isfile(path):
        if not os.path.isdir(sprites_dir):
            return {}, []
        return {d: {"mobs": None, "minimap": None} for d in sorted(os.listdir(sprites_dir))
                if os.path.isdir(os.path.join(sprites_dir, d))}, []
    try:
        with open(path, encoding="utf-8") as f:
            entries = map_entries(json.load(f))
    except ValueError as e:
        return {}, ["%s isn't valid JSON: %s" % (path, e)]
    if entries is None:
        return {}, ['%s should be a list of maps: [{"name": "Map", "mobs": ["mob.png", ...]}, ...]' % path]
    maps, problems = {}, []
    for i, entry in enumerate(entries, 1):
        name = entry.get("name") if isinstance(entry, dict) else None
        if not isinstance(name, str) or not name:
            problems.append('%s: map %d needs a "name"' % (MAP_LIST, i)); continue
        if name in maps:
            problems.append("%s: %s is listed twice; the first counts" % (MAP_LIST, name)); continue
        files = entry.get("mobs")
        if not isinstance(files, list) or not all(isinstance(f, str) for f in files):
            problems.append('%s: %s\'s "mobs" should be a list of PNG file names' % (MAP_LIST, name)); continue
        missing = [f for f in files if not os.path.isfile(os.path.join(sprites_dir, f))]
        if missing:
            problems.append("%s: %s lists %s, not in %s" % (MAP_LIST, name, ", ".join(missing), sprites_dir))
        size = entry.get("minimap")
        if size is not None and not (isinstance(size, dict) and all(isinstance(size.get(k), int) and 8 <= size[k] <= 4000
                                                                   for k in ("width", "height"))
                                     and all(isinstance(size.get(k, 0), int) and -4000 <= size.get(k, 0) <= 4000 for k in ("left", "top"))):
            problems.append('%s: %s\'s "minimap" should be {"width": px, "height": px}; the setup\'s is used' % (MAP_LIST, name))
            size = None
        if size:
            size = dict({"width": size["width"], "height": size["height"]},
                        **({"left": size.get("left", 0), "top": size.get("top", 0)} if "left" in size or "top" in size else {}))
        maps[name] = {"mobs": files, "minimap": size}
    return maps, problems

def format_map_list(entries):
    """map.json text: one map per block, each value on one line."""
    def one(entry):
        if not isinstance(entry, dict):
            return "  " + json.dumps(entry, ensure_ascii=False)
        return "  {\n" + ",\n".join("    %s: %s" % (json.dumps(k, ensure_ascii=False), json.dumps(v, ensure_ascii=False))
                                     for k, v in entry.items()) + "\n  }"
    return "[\n" + ",\n".join(one(e) for e in entries) + "\n]\n"

def save_map_size(sprites_dir, name, width, height):
    """Writes map `name`'s minimap size into map.json (in the current form,
    keeping everything else). False without map.json or that map in it."""
    return save_map_value(sprites_dir, name, "minimap", {"width": width, "height": height})

def save_map_value(sprites_dir, name, key, value):
    """Sets `key` of map `name` in map.json (in the current form, keeping
    everything else). False without map.json or that map in it."""
    path = os.path.join(sprites_dir, MAP_LIST)
    try:
        with open(path, encoding="utf-8") as f:
            entries = map_entries(json.load(f))
    except (OSError, ValueError):
        return False
    for entry in entries or []:
        if isinstance(entry, dict) and entry.get("name") == name:
            entry[key] = value
            with open(path + ".tmp", "w", encoding="utf-8") as f:
                f.write(format_map_list(entries))
            os.replace(path + ".tmp", path)
            return True
    return False

class MapList:
    """map.json for the reading loop: read again when it changes, its problems
    said once each time."""
    def __init__(self, sprites_dir):
        self.dir, self.stamp, self.maps = sprites_dir, False, {}

    def get(self):
        path = os.path.join(self.dir, MAP_LIST)
        stamp = os.path.getmtime(path) if os.path.isfile(path) else None
        if stamp != self.stamp or stamp is None:   # the older folders: just list them again
            self.maps, problems = read_map_list(self.dir)
            if stamp != self.stamp:
                for problem in problems:
                    say(problem)
            self.stamp = stamp
        return self.maps

def map_names(sprites_dir):
    return sorted(read_map_list(sprites_dir)[0])

def map_sprites(sprites_dir, name):
    """The sprites of map `name`: its files in map.json (or its older folder)."""
    entry = read_map_list(sprites_dir)[0].get(name)
    if not entry:
        return {}
    return load_sprites(os.path.join(sprites_dir, name)) if entry["mobs"] is None else load_sprites(sprites_dir, entry["mobs"])

def map_sizes(maps):
    """{map: its minimap size} for the maps in map.json that have one."""
    return {name: entry["minimap"] for name, entry in maps.items() if entry.get("minimap")}

def map_changed(sprites_dir, maps, name, taught):
    """Whether map.json now lists other (existing) PNGs for `name` than it was taught with."""
    files = (maps.get(name) or {}).get("mobs")
    if not files or not taught:
        return False
    return sorted(f for f in set(files) if os.path.isfile(os.path.join(sprites_dir, f))) != taught.get("sprites")

def map_box(mm, size):
    """The minimap's box on a map with its own size in map.json: from the
    setup's top-left corner (with its header), or, marked by hand (F12, "left"
    and "top"), exactly the marked map picture, with no header."""
    if "left" in size:
        x1, y1 = mm["x1"] + size["left"], mm["y1"] + size["top"]
        return dict(mm, x1=x1, y1=y1, x2=x1 + size["width"] - 1, y2=y1 + size["height"] - 1, header=0, auto=False)
    return dict(mm, x2=mm["x1"] + size["width"] - 1, y2=mm["y1"] + size["height"] - 1)

def marked_box(mm, a, b):
    """map.json's "minimap" for a map picture marked by two corners (any
    order): {"left", "top", "width", "height"} from the setup's corner, or
    None if that's too small to be a minimap."""
    (ax, ay), (bx, by) = a, b
    x1, y1, x2, y2 = min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)
    if min(x2 - x1, y2 - y1) + 1 < 8:
        return None
    return {"width": x2 - x1 + 1, "height": y2 - y1 + 1, "left": x1 - mm["x1"], "top": y1 - mm["y1"]}

def marked_name_area(a, b, light=170):
    """A map name area from two corners (any order), or None if it's too thin."""
    (ax, ay), (bx, by) = a, b
    area = {"x1": min(ax, bx), "y1": min(ay, by), "x2": max(ax, bx), "y2": max(ay, by), "light": light}
    return area if area["x2"] - area["x1"] >= 8 and area["y2"] - area["y1"] >= 3 else None

def mark_map_area(config, cancel=("esc",)):
    """F12: mark this map's minimap and its name by hand, for a map where
    they aren't where they're looked for. Returns (map.json "minimap" or None,
    name area or None); Esc skips either."""
    mm, box, area = config.get("minimap"), None, None
    if mm:
        pts = mark_points("Map area (F12): hover the minimap's map picture TOP-LEFT corner (under its title), F8; "
                          "then its BOTTOM-RIGHT, F8 (Esc keeps the automatic minimap)", 2, cancel)
        box = marked_box(mm, *pts) if len(pts) == 2 else None
        say("  minimap: %s" % ("%d x %d px at %d,%d" % (box["width"], box["height"], pts[0][0], pts[0][1]) if box
                               else "kept as found" if len(pts) < 2 else "too small, kept as found"))
    pts = mark_points("Map name: hover the TOP-LEFT of the map's name, F8; then its BOTTOM-RIGHT, a bit past where the "
                      "longest name would end, F8 (Esc keeps the usual place)", 2, cancel)
    area = marked_name_area(*pts) if len(pts) == 2 else None
    say("  map name: %s" % ("marked" if area else "kept where it was"))
    return box, area

def save_map_area(sct, config, sprites_dir, name, box, area):
    """Saves a map's hand-marked minimap (map.json) and name area (taught
    again with it, in the setup file: the caller saves it). Returns why not, or None."""
    if box and not save_map_value(sprites_dir, name, "minimap", box):
        return "%s isn't in %s: its minimap wasn't saved" % (name, os.path.join(sprites_dir, MAP_LIST))
    if area:
        return teach_map(sct, config, sprites_dir, name, area)
    return None

def minimap_size(mm, corner):
    """The minimap's size from the setup's top-left corner to `corner`, or None
    if that's too small to be one."""
    width, height = corner[0] - mm["x1"] + 1, corner[1] - mm["y1"] + 1
    return (width, height) if min(width, height) >= 8 else None

def mark_minimap_size(mm, name):
    """This map's minimap size: its bottom-right corner, marked once (Esc keeps
    the setup's box)."""
    pts = mark_points("%s's minimap: hover its BOTTOM-RIGHT corner, F8 (Esc keeps the setup's)" % name, 1)
    if not pts:
        return None
    size = minimap_size(mm, pts[0])
    if not size:
        say("  That's not below and right of the minimap's top-left corner: the setup's box is kept.")
    return size

def name_rows(sct, area, mm=None):
    w, h = area["x2"] - area["x1"] + 1, area["y2"] - area["y1"] + 1
    frame = minimap_frame(sct, mm) if mm and mm.get("auto") and area.get("auto") else None
    return text_rows(grab(sct, area["x1"], area["y1"], w, h), w, h, area.get("light", 170), name_limit(area, frame))

def teach_map(sct, config, sprites_dir, name, area=None):
    """Teach the map you're standing on as `name`: its name's look, and its
    mobs (its PNGs in map.json), learned against this map. Updates `config`
    (the caller saves it). Returns why not, or None when taught. `area`: a name
    area of this map's own (F12), kept with it; one it already has is reused."""
    mobs = config.get("mobs")
    if not mobs or "reach" not in mobs:
        return "Mark your hitbox first: python screen_stats.py --mobs"
    sprites = map_sprites(sprites_dir, name)
    if not sprites:
        return "No mob sprites for %s: list its PNGs in %s" % (name, os.path.join(sprites_dir, MAP_LIST))
    own = area or (config.get("maps", {}).get(name) or {}).get("name_area")
    area = own or config.get("map_name") or mark_map_name(config)
    if not area:
        return "A map is told apart by its name, so mark where the name is"
    rows = name_rows(sct, area, config.get("minimap"))
    if ones(rows) < 15:
        say("  Can't see a light name there (%d px). If the name is darker, lower \"light\" in map_name." % ones(rows))
    for other, m in sorted(config.get("maps", {}).items()):
        if other != name and name_taught(m) and rows_score(rows, [int(r, 16) for r in m["rows"]]) >= 0.97:   # the same as far as can be told
            say("  Careful: this name looks like %s's; mark just the name (--setup)." % other)
    entry = read_map_list(sprites_dir)[0].get(name) or {}
    mm = config.get("minimap")
    if mm and entry.get("mobs") is not None and not entry.get("minimap") and not (mm.get("auto") and minimap_frame(sct, mm)):
        size = mark_minimap_size(config["minimap"], name)
        if size and save_map_size(sprites_dir, name, *size):
            say("  Saved %s's minimap size (%d x %d px) in %s." % ((name,) + size + (MAP_LIST,)))
    say("Teaching %s with %d sprite(s)." % (name, len(sprites)))
    learned = learn_here(sct, mobs, sprites)
    if not learned:
        if not numpy_or_none():
            return ("No usable mob colours for %s: nothing saved. pip install numpy to find these mobs by shape instead."
                    % name)
        say("  No colours of their own here: they'll be found by shape (numpy).")
        learned = {"sprites": sorted(sprites)}
    learned["rows"], learned["name_reading"] = ["%x" % r for r in rows], NAME_READING
    learned["taught_at"] = int(time.time())   # recent maps come first in the F9 list
    if own:
        learned["name_area"] = own   # read there, not in the usual place
    config.setdefault("maps", {})[name] = learned
    return None

def learn_map(path, sprites_dir, name=""):
    """--map from the terminal: asks which map when there are several."""
    import mss
    sct, config = mss.mss(), load_config(path)
    maps, problems = read_map_list(sprites_dir)
    for problem in problems:
        say(problem)
    names = sorted(maps)
    if not name:
        if not names:
            raise SystemExit('List your maps in %s, e.g. {"Henesys": ["snail.png", "blue_snail.png"]}, '
                             'with the PNGs in %s' % (os.path.join(sprites_dir, MAP_LIST), sprites_dir))
        if len(names) == 1:
            name = names[0]
        else:
            for i, f in enumerate(names, 1):
                say("  %d. %s%s" % (i, f, "  (taught)" if f in config.get("maps", {}) else ""))
            pick = input("Which map are you on? Number or name: ").strip()
            name = names[int(pick) - 1] if pick.isdigit() and 1 <= int(pick) <= len(names) else pick
    problem = teach_map(sct, config, sprites_dir, name)
    if problem:
        raise SystemExit(problem)
    save_config(path, config)
    say("Saved %s in %s: it switches to these mobs whenever this name shows." % (name, path))

def setup(path, sprites_dir="mobs", game="maplestory"):
    """Mark the bars, minimap and mobs. With a known `game` (GAMES) the colours
    are its own, so bars may be empty and your dot isn't marked."""
    import mss                         # first: on Windows this makes the process DPI-aware,
    sct, config = mss.mss(), {"bars": {}}   # so pointer positions and pixels agree
    known = GAMES.get(game)
    if known:
        config["game"] = game
        say("Setting up for %s (its bar and dot colours are built in)." % known["label"])
    monitors = sct.monitors
    placed = hud_bars(game, monitors[1] if len(monitors) > 1 else monitors[0])
    if placed:   # where the game puts them: kept if the HP bar is really there (it's only empty when you're dead)
        fill = read_bars(sct, placed)
        if fill.get("hp"):
            config["bars"] = placed
            say("Found the HP, MP and XP bars where %s puts them (HP %s%%, MP %s%%, XP %s%%): nothing to mark."
                % (known["label"], fill["hp"], fill["mana"], fill["xp"]))
        else:
            say("Couldn't see %s's HP bar at the bottom of the screen (windowed, or another layout?): mark the bars."
                % known["label"])
    for name, label in BARS:
        if name in config["bars"]:
            continue
        pts = mark_points("%s bar: hover its LEFT end, F8; then its RIGHT end, F8 (Esc skips)" % label, 2)
        if len(pts) < 2:
            say("  skipped"); continue
        (x1, y), (x2, _) = pts
        x1, x2 = min(x1, x2), max(x1, x2)
        color = list(known["bars"][name]) if known else pixel(sct, x1 + 2, y)
        config["bars"][name] = {"x1": x1, "x2": x2, "y": y, "color": color, "tolerance": 60}
    corner = minimap_corner(game, monitors[1] if len(monitors) > 1 else monitors[0])
    found = None
    if known and corner:   # its corner is known: its frame is looked for on screen (and kept if your dot shows in it)
        header = known.get("minimap_header", 0)
        frame = minimap_frame(sct, {"x1": corner[0], "y1": corner[1], "header": header})
        if frame:
            w, h = frame[0] - corner[0], frame[1] - corner[1]
            if find_dot(grab(sct, corner[0], corner[1], w, h), w, h, known["dot"], 40, top=header):
                found = frame
                config["minimap"] = {"x1": corner[0], "y1": corner[1], "x2": frame[0] - 1, "y2": frame[1] - 1, "dot": list(known["dot"]),
                                     "tolerance": 40, "map_mismatch": 0.6, "header": header, "auto": True}
                say("Found the minimap (%d x %d px here; its size is found again on every map): nothing to mark." % (w, h))
    if found:
        pts = []
    elif known and corner:   # its top-left is known: just the bottom-right, kept if your dot shows in the box
        pts = mark_points("Minimap: hover its BOTTOM-RIGHT corner, F8 (its top-left is the screen's corner; Esc skips)", 1)
        if pts:
            (bx, by), (cx, cy) = pts[0], corner
            w, h = bx - cx + 1, by - cy + 1
            top = known.get("minimap_header", 0)
            if w > 20 and h > top + 20 and find_dot(grab(sct, cx, cy, w, h), w, h, known["dot"], 40, top=top):
                pts = [corner, pts[0], None]
            else:
                say("  Couldn't see your dot in that box (the game windowed away from the corner?): mark both corners.")
                pts = mark_points("Minimap: hover its TOP-LEFT corner, F8; then its BOTTOM-RIGHT corner, F8 (Esc skips)", 2)
                pts = pts + [None] if len(pts) == 2 else []
    elif known:
        pts = mark_points("Minimap: hover its TOP-LEFT corner, F8; then its BOTTOM-RIGHT corner, F8 (Esc skips)", 2)
        pts = pts + [None] if len(pts) == 2 else []
    else:
        pts = mark_points("Minimap: hover its TOP-LEFT corner, F8; BOTTOM-RIGHT corner, F8; then YOUR dot, F8 (Esc skips)", 3)
    if len(pts) == 3:
        (ax, ay), (bx, by), dot = pts
        config["minimap"] = {"x1": min(ax, bx), "y1": min(ay, by), "x2": max(ax, bx), "y2": max(ay, by),
                             "dot": list(known["dot"]) if known else pixel(sct, *dot), "tolerance": 40, "map_mismatch": 0.6}
    maps, problems = read_map_list(sprites_dir)
    for problem in problems:
        say(problem)
    names = sorted(maps)
    if LAYER:   # F9 works during setup too (the map is taught once readings start)
        LAYER.maps, LAYER.taught = layer_maps(maps, load_config(path, required=False))
    if names:
        say("%d maps in %s (%s%s)" % (len(names), MAP_LIST, ", ".join(names[:3]), ", ..." if len(names) > 3 else ""))
        auto = auto_name_area(game, config.get("minimap"))
        if auto:
            config["map_name"] = auto
            say("The map's name is read from the minimap's header, up to its edge: nothing to mark.")
        else:
            mark_map_name(config)
    setup_mobs(sct, config, sprites_dir)
    old = load_config(path, required=False)
    for keep in ("watch", "maps", "not_now"):   # death/login marks from --mark, maps taught with F9 / --map, offers declined
        if old.get(keep):
            config[keep] = old[keep]
    if names and "map_name" not in config and old.get("map_name"):
        config["map_name"] = old["map_name"]
    save_config(path, config)
    say("Saved %s - if something reads wrong, raise its tolerance there." % path)
    if names:
        say("Now teach each map: stand on it and press F9 (or Which map on the pad)")

def relearn_mobs(path, sprites_dir):
    import mss
    config = load_config(path)
    setup_mobs(mss.mss(), config, sprites_dir)
    save_config(path, config)
    say("Saved %s" % path)

def mark(path, what):
    import mss
    sct, config = mss.mss(), load_config(path, required=False)
    pts = mark_points("With the %s screen showing, hover something only it has (e.g. a button), F8 (Esc cancels)" % what, 1)
    if not pts:
        return
    x, y = pts[0]
    config.setdefault("watch", {})[what] = {"x": x, "y": y, "patch": list(grab(sct, x - 2, y - 2, 5, 5))}
    save_config(path, config)
    say("Saved the %s mark in %s" % (what, path))

def load_config(path, required=True):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        if required:
            raise SystemExit("No %s yet - run with --setup first" % path)
        return {}

def save_config(path, config):
    with open(path, "w") as f:
        json.dump(config, f, indent=2)

# ---- talking to the pad -------------------------------------------------------

def form_fields(readings):
    """What to POST: unread values are left out, so the pad treats them as not
    read. "mobs" is sent (maybe empty) only with a mob detector set up."""
    fields = {k: v for k, v in readings.items() if v is not None and k != "state"}
    fields["state"] = readings.get("state", "ok")
    return fields

# ---- home, as the pad tells it --------------------------------------------------
# The pad answers each reading with the playing pattern's home (set where its
# button started it, or where you arrived on a new map): "home=1415&hm=1&hr=500"
# - in tenths of a percent of the minimap, hm=1 for a map position (the slide
# counted, like "wx") rather than the dot's x, hr the home range (0: none). The
# game layer marks it on the minimap. No answer, or no pattern playing: None.

def parse_home(form):
    """{"home": 1415, "map": True, "range": 500} from the pad's answer, or None."""
    fields = dict(urllib.parse.parse_qsl(form or ""))
    try:
        return {"home": int(fields["home"]), "map": fields.get("hm") == "1", "range": max(0, int(fields.get("hr", 0)))}
    except (KeyError, ValueError):
        return None

def answer_keys(form_or_list):
    """The pad buttons in a reading's answer: ["mark", "map"] from "mark,map"
    (or a list), or None when the answer has none at all (older firmware)."""
    if form_or_list is None:
        return None
    items = form_or_list if isinstance(form_or_list, list) else form_or_list.split(",")
    return [k for k in items if k]

class Answers:
    """What readings' answers carried: the pad buttons pressed since (kept
    until taken), and whether this firmware puts them there at all, so the
    separate polling for them can rest while readings flow."""
    def __init__(self):
        self.inbox, self.carries_keys, self.heard_at = [], False, 0.0

    def heard(self, keys):
        if keys is not None:
            self.carries_keys, self.heard_at = True, time.monotonic()
            self.inbox.extend(keys)

    def take_keys(self):
        keys, self.inbox = self.inbox, []
        return keys

    def polling_needed(self, now=None, quiet=2.5):
        """Poll for buttons only when answers don't bring them (older
        firmware) or no reading was answered lately (setup, a pause)."""
        return not self.carries_keys or (time.monotonic() if now is None else now) - self.heard_at > quiet

def home_place(r, home):
    """Where home is on the minimap in % across (it can be off the minimap's
    edge when the minimap slides), or None when it can't be told."""
    if not home or r.get("x") is None:
        return None
    if not home["map"]:
        return home["home"] / 10.0
    if r.get("wx") is None:
        return None
    return r["x"] + (home["home"] - r["wx"]) / 10.0   # the same slide as your dot

ESPRESSIF_VID = 0x303A   # the ESP32-S3's own USB port
PAD_KEYS_SINCE = (1, 17, 0)   # firmware with the setup buttons ("KABUTO keys")

def version_tuple(version):
    """(1, 18, 0) from "1.18.0" (anything after the numbers ignored), or None."""
    m = re.match(r"^v?(\d+)\.(\d+)(?:\.(\d+))?", version or "")
    return tuple(int(g or 0) for g in m.groups()) if m else None

class UsbPad:
    """Sends readings down the USB cable ("KABUTO stats <form>" lines), so a
    game laptop needs no Wi-Fi or PIN: plugging the pad in is the permission."""
    def __init__(self, port, version=None):
        self.port, self.version, self.lock, self.home, self.answers = port, version, threading.Lock(), None, Answers()

    def _heard(self, line):
        """The pad's answer to a reading ("KABUTO ok", maybe with the buttons
        pressed since and its home): kept."""
        if line == "KABUTO ok" or line.startswith("KABUTO ok "):
            fields = dict(urllib.parse.parse_qsl(line[10:], keep_blank_values=True))
            self.home = parse_home(line[10:])
            self.answers.heard(answer_keys(fields.get("keys")))
            return True
        return False

    @staticmethod
    def open(device):
        import serial
        port = serial.Serial()
        port.port, port.baudrate, port.timeout, port.write_timeout = device, 115200, 0.5, 2
        port.dtr = port.rts = False   # leave the reset lines alone so the pad doesn't restart
        port.open()
        return port

    def hello(self, wait=3.0):
        """The pad's firmware version, or None if this port isn't a Kabuto."""
        self.port.write(b"KABUTO hello\n")
        end = time.time() + wait
        while time.time() < end:
            line = self.port.readline().decode("ascii", "replace").strip()
            if line.startswith("KABUTO ") and line != "KABUTO ok" and not line.startswith("KABUTO ok "):
                self.version = line[7:]
                return self.version
        return None

    def send(self, readings):
        """Sends a reading; returns the pad's home from its latest answer (the
        one to the reading before: it isn't waited for), or None."""
        with self.lock:
            self.port.write(("KABUTO stats " + urllib.parse.urlencode(form_fields(readings)) + "\n").encode())
            waiting = getattr(self.port, "in_waiting", 0)
            if waiting:   # answers and the pad's log: the answers are kept, the rest dropped
                for line in self.port.read(waiting).decode("ascii", "replace").splitlines():
                    self._heard(line.strip())
            return self.home

    def keys(self, wait=1.0):
        """Setup buttons pressed on the pad since the last ask. None only for
        firmware from before them (its version says so); a pad that's slow to
        answer (busy playing, its log in the way) just gives none this time."""
        with self.lock:
            self.port.write(b"KABUTO keys\n")
            end = time.time() + wait
            while time.time() < end:
                line = self.port.readline().decode("ascii", "replace").strip()
                self._heard(line)   # an answer to a reading read here isn't lost
                if line == "KABUTO keys" or line.startswith("KABUTO keys "):
                    return self.answers.take_keys() + [k for k in line[12:].split(",") if k]
        old = version_tuple(self.version)
        return None if old and old < PAD_KEYS_SINCE else []

    @property
    def where(self):
        return "USB " + getattr(self.port, "port", "")

def find_usb_pad(ports=None, opener=None):
    """The first Espressif USB device that answers like a Kabuto, or None."""
    if ports is None:
        try:
            from serial.tools import list_ports
        except ImportError:
            return None
        ports = list_ports.comports()
    for info in ports:
        if getattr(info, "vid", None) != ESPRESSIF_VID:
            continue
        try:
            port = (opener or UsbPad.open)(info.device)
        except Exception:
            continue
        pad = UsbPad(port)
        if pad.hello():
            return pad
        port.close()
    return None

class PadLink:
    """The pad, shared by the readings and the setup-button watcher: connected
    on first use, dropped (and found again) when it stops answering."""
    def __init__(self, args):
        self.args, self.pad, self.lock = args, None, threading.Lock()

    def get(self):
        with self.lock:
            if self.pad is None:
                self.pad = connect(self.args)
                say("Connected to Kabuto over %s" % self.pad.where)
            return self.pad

    def drop(self, pad):
        with self.lock:
            if self.pad is pad:
                self.pad = None

def watch_pad_keys(link, every=0.15):
    """Passes the pad's setup buttons on as keys (mark = F8, ...), in the
    background, for as long as the script runs."""
    def loop():
        while True:
            pad = None
            try:
                pad = link.get()
                answers = getattr(pad, "answers", None)
                if answers and not answers.polling_needed():   # readings' answers bring them: no extra traffic
                    time.sleep(0.5)
                    continue
                keys = pad.keys()
                if keys is None:
                    say("This pad's firmware (%s) has no setup buttons: update it to %s or newer to use them"
                        % (getattr(pad, "version", None) or "an old one", ".".join(map(str, PAD_KEYS_SINCE))))
                    return
                for k in keys:
                    if k in PAD_KEYS:
                        press(PAD_KEYS[k])
                time.sleep(every)
            except (urllib.error.URLError, OSError):
                if pad:
                    link.drop(pad)
                time.sleep(3)
    threading.Thread(target=loop, daemon=True).start()

def connect(args):
    """The pad on the USB cable. Readings go over the cable only: over Wi-Fi
    they flooded the pad, whose radio also carries its Bluetooth keys and the
    phone's page."""
    pad = find_usb_pad()
    if pad:
        return pad
    raise OSError("no Kabuto on USB: plug it into this PC with a data cable (a charge-only cable won't do)")

STATE_TEXT = {"dead": "DEAD", "offline": "OFFLINE", "test": "TEST POPUP: answer it"}   # anything but ok

# ---- alert sounds -------------------------------------------------------------
# A soft chime on the PC when the game needs you, made here (no sound files):
# two plucked notes, rising for the test popup (as it shows, and again every
# TEST_REPEAT_S while it stays: it has a time limit), falling once for a death
# or a disconnect. Your own sound instead: kabuto-test.wav / kabuto-dead.wav /
# kabuto-offline.wav next to the setup file. --quiet, or "sound": false in the
# setup file, for none.
CHIMES = {"test": ((659.25, 0.0), (987.77, 0.12)),      # E5 then B5: "pop-ding"
          "dead": ((587.33, 0.0), (440.0, 0.14)),       # D5 then A4
          "offline": ((587.33, 0.0), (440.0, 0.14))}
ALERT_MESSAGES = {"test": "The game is testing you: answer the popup yourself (the pad has stopped)",
                  "dead": "You died: the pad has stopped", "offline": "The game is disconnected: the pad has stopped"}
TEST_REPEAT_S = 10
CHIME_VOLUME = 0.35   # 0-1

def chime_wav(notes, volume=CHIME_VOLUME, rate=22050):
    """A soft chime as WAV bytes: each (Hz, start s) a quick pluck that rings
    out (a sine with a little of its octave, fading fast)."""
    import io, math, struct, wave
    ring = 0.55
    n = int((max(start for _, start in notes) + ring) * rate)
    samples = [0.0] * n
    for hz, start in notes:
        first = int(start * rate)
        for i in range(min(int(ring * rate), n - first)):
            t = i / rate
            env = min(1.0, t / 0.005) * math.exp(-t * 8)
            samples[first + i] += env * (math.sin(2 * math.pi * hz * t) + 0.2 * math.sin(4 * math.pi * hz * t))
    peak = max(abs(v) for v in samples) or 1.0
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(v / peak * volume * 32767)) for v in samples))
    return out.getvalue()

class Alarm:
    """When to sound: update() each reading returns the state to sound for
    now, else None."""
    def __init__(self, repeat=TEST_REPEAT_S):
        self.state, self.last, self.repeat = "ok", 0.0, repeat

    def update(self, state, now):
        was, self.state = self.state, state
        if state not in CHIMES:
            return None
        if state != was or (state == "test" and now - self.last >= self.repeat):
            self.last = now
            return state
        return None

SOUND_FILES = {}   # state -> the WAV file played (made once per run)

def alert_sound(state, folder="."):
    """The WAV file for an alert: yours next to the setup file, else the chime
    made once into the temp folder."""
    own = os.path.join(folder, "kabuto-%s.wav" % state)
    if os.path.isfile(own):
        return own
    if state not in SOUND_FILES:
        import tempfile
        path = os.path.join(tempfile.gettempdir(), "kabuto-chime-%s.wav" % state)
        with open(path, "wb") as f:
            f.write(chime_wav(CHIMES.get(state, CHIMES["test"])))
        SOUND_FILES[state] = path
    return SOUND_FILES[state]

def play_alert(state, folder="."):
    """The alert's chime, without waiting for it to finish; and what happened
    in a bubble on the game layer."""
    say(ALERT_MESSAGES.get(state, state))
    try:
        path = alert_sound(state, folder)
        if sys.platform == "win32":
            import winsound
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        else:
            import shutil, subprocess
            player = shutil.which("afplay") or shutil.which("paplay") or shutil.which("aplay")
            if player:
                subprocess.Popen([player, path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                print("\a", end="", flush=True)
    except Exception:   # no sound device, no temp folder: the strip still says it
        pass

def describe(r, xp=""):
    parts = ["%s %5.1f%%" % (label, r[name]) for name, label in BARS if r.get(name) is not None]
    if xp:
        parts.append("XP " + xp)
    if r.get("x") is not None:
        parts.append("map %4.1f,%4.1f" % (r["x"], r["y"]))
    if r.get("mobs") is not None:
        parts.append("mobs " + (r["mobs"] or "-"))
    if r.get("mobs") is None and r.get("state", "ok") == "ok":
        parts.append("mobs: not looking" + (" (map not taught: F9)" if untaught(r.get("map")) else ""))
    if r.get("ml") is not None:
        near = lambda side: "%d%%" % r["d" + side] if r.get("d" + side) is not None else "-"
        parts.append("in reach %s (%d)" % (r["ir"] if r.get("ir") is not None else "?", r["ml"] + r["mr"]))
        parts.append("seen L%d (%s) R%d (%s)" % (r["ml"], near("l"), r["mr"], near("r")) + (" " + r["mn"] if r.get("mn") else ""))
    if r.get("map") is not None:
        parts.append("map " + (r["map"] if not untaught(r["map"]) else "not taught"))
    if r.get("state", "ok") != "ok":
        parts.append("!! " + STATE_TEXT.get(r["state"], r["state"].upper()))
    return "  ".join(parts)

# ---- getting ready: what this version needs, offered once at start ----------
# One command does it all: python screen_stats.py offers, in the terminal,
# the packages and frames the shape search needs, then in the game anything
# new to mark. A "no" is remembered ("not_now" in the setup file).

EXTRAS = (("pillow", "PIL"), ("numpy", "numpy"), ("scipy", "scipy"))   # (pip name, module) for the shape search
TOOLS_URL = "https://raw.githubusercontent.com/pasujemito/kabuto-keyboard/main/tools/"
NAME_MIN_W = 100      # px: a map name area narrower than this cuts longer names off

def ask(question, default=True):
    """Yes or no in the terminal (Enter: the default). With no terminal, no."""
    if not sys.stdin or not sys.stdin.isatty():
        return False
    try:
        answer = input("%s [%s] " % (question, "Y/n" if default else "y/N")).strip().lower()
    except EOFError:
        return False
    return answer.startswith("y") if answer else default

def importable(module):
    import importlib, importlib.util
    importlib.invalidate_caches()
    return importlib.util.find_spec(module) is not None

def pip_install(names):
    import subprocess
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install"] + list(names))
        return True
    except (OSError, subprocess.CalledProcessError):
        return False

def frames_tool(ask=ask):
    """mob_frames.py from next to this file; downloaded from GitHub first if
    it isn't there (asked). None without it."""
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    try:
        import mob_frames
        return mob_frames
    except ImportError:
        pass
    if not ask("Fetching frames needs mob_frames.py next to this file. Download it from GitHub?"):
        return None
    try:
        req = urllib.request.Request(TOOLS_URL + "mob_frames.py", headers={"User-Agent": "kabuto-screen-stats"})
        data = urllib.request.urlopen(req, timeout=30).read()
        with open(os.path.join(here, "mob_frames.py"), "wb") as f:
            f.write(data)
        import mob_frames
        return mob_frames
    except Exception as e:
        say("  Couldn't get it (%s): save %smob_frames.py next to this file" % (e, TOOLS_URL))
        return None

def get_ready(path, sprites_dir, ask=ask, install=pip_install, tool=frames_tool):
    """Before starting, in the terminal: offers what the shape search needs and
    isn't here yet (Pillow, numpy and scipy; the mobs' animation frames)."""
    config = load_config(path, required=False)
    skip = set(config.get("not_now", []))
    before = set(skip)
    need = [pip for pip, module in EXTRAS if not importable(module)]
    if need and "packages" not in skip:
        if ask("Mobs are found best by their shape, which needs %s. Install now?" % " and ".join(need)):
            if not install(need):
                say("  That didn't work. Try: python -m pip install %s" % " ".join(need))
            importable("numpy")   # fresh look at what's installed
        else:
            skip.add("packages")
            say("  OK (asked once). Later: python -m pip install %s" % " ".join(need))
    if numpy_or_none() and os.path.isfile(os.path.join(sprites_dir, MAP_LIST)) and "frames" not in skip:
        mf = tool(ask)
        todo = mf.needing_frames(sprites_dir) if mf else []
        if todo:
            shown = ", ".join(os.path.splitext(p)[0] for p in todo[:3]) + (", ..." if len(todo) > 3 else "")
            if ask("%d of your mobs have no animation frames yet (%s). Fetch them from maplestory.io?" % (len(todo), shown)):
                try:
                    saved, missing = mf.fetch(sprites_dir, mf.Api(), say=say, only=todo)
                    mf.remember_not_found(sprites_dir, missing)
                    say("  %d frames saved.%s" % (saved, " maplestory.io has no %s: they're matched by their PNG (add frames by hand as"
                                                   " name.<anything>.png)." % ", ".join(missing) if missing else ""))
                except Exception as e:   # no network, the site down: carry on without
                    say("  Couldn't fetch frames (%s): carrying on with what's there." % e)
            else:
                skip.add("frames")
                say("  OK (asked once). Later: python mob_frames.py")
    if skip != before:
        config["not_now"] = sorted(skip)
        save_config(path, config)

def get_ready_in_game(sct, config, path):
    """First thing in the game: anything new to mark (F8), and maps to teach
    again. Esc means not now (remembered, not asked again); F9 means later:
    the map picker opens and the rest waits for the next start. Returns True
    if the setup changed."""
    skip = set(config.get("not_now", []))
    before = json.dumps(config, sort_keys=True)
    mobs = config.get("mobs") or {}
    later = ("Esc: not now, F9: later", ("esc", "f9"))   # F9 still picks a map: never stuck here
    asked_later = lambda: CANCELLED[0] == "f9"
    if numpy_or_none() and "bottom" in mobs and not mobs.get("tag") and "tag" not in skip and not asked_later():
        say("One-time setup for this version: the mob search can follow you by your name tag.")
        mark_tag(sct, mobs, *later)
        if not mobs.get("tag") and not asked_later():
            skip.add("tag")
            say("  (asked once; --tag to mark it later)")
    area = config.get("map_name")
    if area and area["x2"] - area["x1"] + 1 < NAME_MIN_W and "map_name" not in skip and not asked_later():
        say("One-time setup for this version: the map name area is %d px wide, so longer names get cut off and look"
            " alike (The Burnt Land III and V)." % (area["x2"] - area["x1"] + 1))
        auto = auto_name_area(config.get("game"), config.get("minimap"))
        if auto:
            if mark_points("F8: read it from the minimap's header up to its edge, automatically (then teach maps again with F9); "
                           "Esc: keep yours, F9: later", 1, ("esc", "f9")):
                config["map_name"] = auto
                for m in config.get("maps", {}).values():
                    m.pop("name_reading", None)   # names read from the new area: teach each again
                say("  The map name is read automatically now: teach maps again with F9 as you get to them.")
        elif mark_map_name(config, *later):
            for m in config.get("maps", {}).values():
                m.pop("name_reading", None)   # names read from the new area: teach each again
        if not asked_later():
            skip.add("map_name")   # asked once, marked or not
    if asked_later():
        say("  OK, asked again next start.")
    old = sorted(n for n, m in config.get("maps", {}).items() if m.get("rows") and not name_taught(m))
    if old:
        say("%d map(s) need teaching again (names are read a new way): on each, press F9: %s"
            % (len(old), ", ".join(old[:4]) + (", ..." if len(old) > 4 else "")))
    if skip != set(config.get("not_now", [])):
        config["not_now"] = sorted(skip)
    if json.dumps(config, sort_keys=True) != before:
        save_config(path, config)
        return True
    return False

def layer_maps(maps, config):
    """For the F9 list: every map in map.json, and when each taught one was taught."""
    return sorted(maps), {n: m.get("taught_at", 0) for n, m in config.get("maps", {}).items() if name_taught(m)}

USB_INTERVAL = 0.2   # s between readings by default
HEARTBEAT_S = 2.0    # a reading is sent at least this often, changed or not (the pad treats 5 s without as stale)

def reading_interval(asked, pad=None):
    """--interval if given, else 0.2 s."""
    return asked if asked else USB_INTERVAL

def worth_sending(last, r, sent_at, now, heartbeat=HEARTBEAT_S):
    """Whether this reading changes anything the pad fights with, compared
    with the last one sent: the game's state, the map, mobs (sides, counts,
    the nearest's name, one coming into or out of reach, or 10% of your reach
    nearer or further), your place (0.5% of the minimap: the home zone's edge
    is judged from it), HP or MP (1%). XP
    alone waits for the heartbeat."""
    if last is None or now - sent_at >= heartbeat or now < sent_at:
        return True
    if any(last.get(k) != r.get(k) for k in ("state", "map", "mobs", "ml", "mr", "ir", "mn")):
        return True
    def moved(key, step):
        a, b = last.get(key), r.get(key)
        return (a is None) != (b is None) or (a is not None and abs(b - a) >= step)
    if any(moved(k, step) for k, step in (("x", 0.5), ("y", 2.0), ("wx", 5), ("wy", 20), ("hp", 1.0), ("mana", 1.0))):
        return True
    for k in ("dl", "dr"):
        a, b = last.get(k), r.get(k)
        if moved(k, 10) or (a is not None and b is not None and (a <= 100) != (b <= 100)):
            return True
    return False

REST = 0.05   # s: at least this between readings, so the game keeps some CPU (more: slower readings on a slow PC)

def run(args):
    import mss
    sct, config = mss.mss(), load_config(args.config, required=False)
    if not (config.get("bars") or config.get("minimap") or config.get("mobs")):
        say("First run: let's mark your bars, minimap and mobs (hover, then F8).")
        setup(args.config, args.sprites, args.game or "maplestory")
        config = load_config(args.config)
    map_list = MapList(args.sprites)
    if LAYER:   # F9 works from the start, the one-time questions below included (it's taught once readings begin)
        LAYER.maps, LAYER.taught = layer_maps(map_list.get(), config)
    get_ready_in_game(sct, config, args.config)
    if args.game and config.get("game") != args.game:   # --game other: sampled colours again
        config["game"] = args.game
        save_config(args.config, config)
    screen, pad, link, xp_rate, home = Screen(sct, config, args.sprites), None, None, XpRate(), None
    sent, sent_at = None, 0.0   # the last reading sent and when: only changes go, plus a heartbeat
    alarm = Alarm() if not getattr(args, "quiet", False) and config.get("sound", True) else None
    pads = None if args.dry_run else getattr(args, "pads", None) or PadLink(args)
    pending_area = None   # F12 on a map not recognised: saved with the map F9 picks next
    while True:
        maps = map_list.get()
        screen.sizes = map_sizes(maps)
        screen.map_mobs = {n: e.get("mobs") for n, e in maps.items()}
        if LAYER:
            LAYER.maps, LAYER.taught = layer_maps(maps, config)
            LAYER.changed = {n for n in LAYER.taught if map_changed(args.sprites, maps, n, config["maps"][n])}
            while not LAYER.commands.empty():
                kind, value = LAYER.commands.get()
                if kind == "teach":   # F9: value is the map
                    box, area = pending_area or (None, None)
                    pending_area = None
                    problem = save_map_area(sct, config, args.sprites, value, box, None) or teach_map(sct, config, args.sprites, value, area)
                    if problem:
                        say(problem)
                    else:
                        save_config(args.config, config)
                        screen = Screen(sct, config, args.sprites)
                        screen.sizes, screen.map_mobs = map_sizes(maps), {n: e.get("mobs") for n, e in maps.items()}
                        say("Taught %s: its mobs are looked for whenever this name shows." % value)
                elif kind == "tune":   # F6 / F7: value is +1 (looser) or -1 (stricter)
                    tuned = tune_tolerance(config, screen.current, value)
                    if tuned:
                        save_config(args.config, config)
                        say("%s: tolerance %d on %s (saved). Watch the outlines (F10)."
                            % ("Looser" if value > 0 else "Stricter", tuned[1], tuned[0]))
                    else:
                        say("No mob colours here to tune: teach this map first (F9)")
                elif kind == "area":   # F12: this map's minimap and name, marked by hand
                    box, area = mark_map_area(config)
                    if not box and not area:
                        say("Map area: nothing marked, nothing changed")
                    elif screen.current:   # a map it knows: saved (and its name taught again) now
                        here = screen.current
                        problem = save_map_area(sct, config, args.sprites, here, box, area)
                        if problem:
                            say(problem)
                        else:
                            save_config(args.config, config)
                            screen = Screen(sct, config, args.sprites)
                            screen.sizes, screen.map_mobs = map_sizes(maps), {n: e.get("mobs") for n, e in maps.items()}
                            say("Saved %s's own map area: used whenever you're on it." % here.replace("_", " "))
                    else:
                        pending_area = (box, area)
                        say("Now press F9 and pick this map: the marked area is saved with it")
        started = time.time()
        readings = screen.read()
        if alarm and alarm.update(readings.get("state", "ok"), started):
            play_alert(readings.get("state"), os.path.dirname(os.path.abspath(args.config)))
        if readings.get("state", "ok") == "ok":   # a death or login screen isn't XP news
            xp_rate.add(readings.get("xp"), started)
        line = describe(readings, xp_text(xp_rate)) + "  %d ms" % ((time.time() - started) * 1000)   # how long a reading takes here
        try:
            pad = pads.get() if pads else None
            link = pad.where if pad else "dry run"
            if pad and worth_sending(sent, readings, sent_at, started):
                home = pad.send(readings)
                sent, sent_at = readings, started
            elif not pad:
                home = None
            for k in pad.answers.take_keys() if pad and hasattr(pad, "answers") else ():
                if k in PAD_KEYS:
                    press(PAD_KEYS[k])
            print("\r" + line.ljust(70) + ("" if pad else "(dry run)"), end="", flush=True)
            wait = reading_interval(args.interval, pad)
        except (urllib.error.URLError, OSError) as e:   # serial errors are OSErrors too
            print("\r%s  can't reach Kabuto (%s), retrying..." % (line, getattr(e, "reason", e)), end="", flush=True)
            link = "can't reach Kabuto"
            if pad:
                pads.drop(pad)   # unplugged: look again
            sent = None
            wait = 3
        if LAYER:
            hint = "%s changed in %s: F9 to relearn" % (screen.current, MAP_LIST) if screen.current in LAYER.changed else None
            if screen.tag and not screen.you:
                hint = (hint + " \u00b7 " if hint else "") + "can't see your name tag"
            tol = mob_tolerance(config, screen.current) if readings.get("mobs") is not None else None
            LAYER.show(layer_status(readings, link, config.get("game"), LAYER.maps, hint, tol, xp_text(xp_rate), home),
                       layer_shapes(config, sct.monitors[0], screen.boxes, readings, screen.box, screen.you, home))
        time.sleep(max(wait - (time.time() - started), REST))   # a slow reading isn't followed by a full wait

# ---- the game layer -------------------------------------------------------------
# An always-on-top strip across the top of the game: what's being read and
# sent, the map, the mobs, and what to do next (setup steps show here too, so
# there's no switching to the terminal). F10 draws outlines over the game:
# where it looks for mobs, each mob it finds (named), the minimap and your
# dot, the map name area. F9 picks the map you're on from map.json.
# On Windows clicks go through to the game and the layer is left out of
# screen captures (Windows 10 2004+), so the reader never sees it. The game
# must be windowed or borderless: nothing draws over exclusive fullscreen.

INK, DIM, AMBER, RED = "#e8eaed", "#8b919e", "#ffb020", "#ff5d5d"
BAR_COLORS = {"hp": "#ff5d5d", "mana": "#4f8cff", "xp": "#cef300"}

ROMAN = {"1": "i", "2": "ii", "3": "iii", "4": "iv", "5": "v", "6": "vi", "7": "vii", "8": "viii", "9": "ix", "10": "x"}

def search_words(text):
    """Lower case, punctuation as spaces: "Rocky Road: II" -> ["rocky", "road", "ii"]."""
    return "".join(c.lower() if c.isalnum() else " " for c in text).split()

def pick_list(names, query="", taught=None, changed=()):
    """The F9 list: [(map, note), ...], best first. With a query, the maps that
    have every word of it somewhere in the name (any order or case; 2 also
    finds II), names starting with it first. Without one, the 5 most recently
    taught, then the rest A-Z. Notes: "changed: teach again", "recent",
    "taught" or ""."""
    taught = taught or {}
    recent = sorted((n for n in names if taught.get(n)), key=lambda n: -taught[n])[:5]
    def note(n):
        return "changed: teach again" if n in changed else "recent" if n in recent else "taught" if n in taught else ""
    words = search_words(query)
    if not words:
        return [(n, note(n)) for n in recent + sorted((n for n in names if n not in recent), key=str.lower)]
    def matches(name):
        have = search_words(name)
        return all(any(w in h or (w in ROMAN and h == ROMAN[w]) for h in have) for w in words)
    hits = [n for n in names if matches(n)]
    hits.sort(key=lambda n: (not " ".join(search_words(n)).startswith(" ".join(words)), n not in recent, n.lower()))
    return [(n, note(n)) for n in hits]

class XpRate:
    """XP per hour from the XP bar (% of a level per hour), worked out as the
    pad does (XpTracker, stats_logic.h): shown after a minute of readings. A
    rise of up to STEP % counts at once; anything else only once the bar has
    stayed there (within SLACK) for HOLD_S, so a bar misread as the screen
    fades between maps isn't a level-up and a huge gain. Then: a drop of over
    half the bar is a level-up (counted; the rate starts afresh), a drop of
    up to DROP (death) is where the bar is now, a bigger rise is gained, and a
    drop in between only starts afresh after RESET_S (another character?)."""
    MIN_S, STEP, DROP, SLACK, HOLD_S, RESET_S = 60, 10.0, 15.0, 2.0, 10, 60

    def __init__(self):
        self.last, self.start, self.at, self.gained, self.levels = None, 0.0, 0.0, 0.0, 0
        self.held = self.held_at = None   # a change waiting to hold

    def add(self, xp, now):
        if xp is None or not 0 <= xp <= 100:
            return
        if self.last is None:
            self.last, self.start, self.at = xp, now, now
            return
        self.at = now
        if 0 <= xp - self.last <= self.STEP:
            self.gained += xp - self.last
            self.last, self.held = xp, None
            return
        if self.held is None or abs(xp - self.held) > self.SLACK:
            self.held, self.held_at = xp, now
            return
        if now - self.held_at < self.HOLD_S:
            return
        to, drop = self.held, self.last - self.held   # it held: the bar went there, and has moved on to xp since
        if self.DROP < drop <= 50 and now - self.held_at < self.RESET_S:
            return   # no game event drops it so far: wait
        self.held = None
        if drop > self.DROP:   # a level up (or a reset): afresh
            self.levels += drop > 50
            self.gained, self.start = 0.0, now
        elif to > self.last:
            self.gained += to - self.last
        self.last = to
        if xp > self.last:
            self.gained += xp - self.last
            self.last = xp

    def per_hour(self):
        """% of a level per hour, or None until a minute of readings."""
        spent = self.at - self.start
        return self.gained * 3600.0 / spent if self.last is not None and spent >= self.MIN_S else None

    def to_level(self):
        """Hours to the next level at this rate, or None."""
        rate = self.per_hour()
        return (100 - self.last) / rate if rate else None

def xp_text(rate):
    """"+3.2%/h, level in 25h" for the strip and console ("" until there's a rate)."""
    per = rate.per_hour() if rate else None
    if per is None:
        return ""
    left = rate.to_level()
    when = "" if left is None else (", level in %dm" % round(left * 60) if left < 1 else ", level in %.1fh" % left)
    return "+%.1f%%/h%s" % (per, when)

def home_cell(r, home):
    """Where you are on the minimap and, with a pattern playing, where its home
    is: "you 41% · home 37% ◀" (the arrow: the way home), amber outside the
    home range; None without a position."""
    if r.get("x") is None:
        return None
    at = home_place(r, home)
    if at is None:
        return Cell("you %.0f%%" % r["x"], INK, 150, "home", "%.0f%%" % r["x"])
    off = r["x"] - at
    far = home["range"] and abs(off) * 10 > home["range"]
    way = "at home" if abs(off) < 1 else "home %.0f%% %s" % (at, "◀" if off > 0 else "▶")
    return Cell("you %.0f%% · %s" % (r["x"], way), AMBER if far else INK, 150, "home",
                "%.0f%% · %s" % (r["x"], "home" if abs(off) < 1 else "%.0f%%%s" % (at, "◀" if off > 0 else "▶")))

def layer_status(r, link, game=None, maps=(), hint=None, tol=None, xp="", home=None):
    """The strip's items from a reading: [(text, colour), ...], Cells with a
    fixed width where their text changes reading to reading, and an icon and
    a shorter text for the strip's one row."""
    known = GAMES.get(game)
    out = [Cell("Kabuto" + (" \u00b7 " + ("MS" if game == "maplestory" else known["label"]) if known else ""), AMBER)]
    if link and link.startswith("can't"):
        out.append(Cell(link, RED, 72, "warn", "no pad"))
    else:
        how, _, where = (link or "starting").partition(" ")
        out.append(Cell(link or "starting", DIM, 72, {"USB": "usb", "Wi-Fi": "wifi"}.get(how),
                        where if how in ("USB", "Wi-Fi") else None))
    for name, label in BARS:
        if r.get(name) is not None:
            out.append(Cell("%s %.0f%%" % ("MP" if name == "mana" else label, r[name]), BAR_COLORS[name], 52))
            if name == "xp":   # its slot even before there's a rate, so the rest keeps its place
                out.append(Cell(xp, BAR_COLORS["xp"], 136))
    if r.get("state", "ok") != "ok":   # first after the bars: the rest (mobs, map) may be cut
        out.append(Cell(STATE_TEXT.get(r["state"], r["state"].upper()), RED, None, "warn"))
    if untaught(r.get("map")):
        out.append(Cell("new map, mobs not seen: F9" if maps else "map not taught", RED, 186, "pin",
                        "new map: F9" if maps else "map not taught"))
    elif r.get("map"):
        out.append(Cell(r["map"].replace("_", " "), INK, 186, "pin"))
    place = home_cell(r, home)
    if place:
        out.append(place)
    if r.get("ml") is not None:
        near = [(r["d" + side], side) for side in "lr" if r.get("d" + side) is not None]
        seen = r["ml"] + r["mr"]   # in reach first, everything seen in brackets
        inside = r.get("ir") if r.get("ir") is not None else len(r.get("mobs") or "")
        out.append(Cell("in reach %d (%d)" % (inside, seen), RED if inside else INK, 104, "mob", "%d (%d)" % (inside, seen)))
        if near:
            d, side = min(near)
            who = (r.get("mn") or ("left" if side == "l" else "right")).replace("_", " ")
            out.append(Cell("%s %s %d%%" % ("target" if d <= 100 else "nearest", r.get("mn") or ("left" if side == "l" else "right"), d),
                            RED if d <= 100 else DIM, 156, "target", "%s %d%%" % (who, d)))
    elif r.get("mobs") is not None:
        out.append(Cell("mobs " + (r["mobs"] or "-"), INK, 60, "mob", r["mobs"] or "-"))
    elif not untaught(r.get("map")):   # nothing to say how many: smart can't stop for them
        out.append(Cell("not looking for mobs" + (": F9 on this map" if maps else ""), RED, None, "mob",
                        "no mobs" + (": F9" if maps else "")))
    if tol is not None:   # how close a colour must be to a mob's (F6 looser, F7 stricter)
        out.append(Cell("tolerance %d" % tol, DIM, 40, None, "\u00b1%d" % tol))
    if hint:
        out.append(Cell(hint, AMBER, None, "warn"))
    return out

HOME_COLOR = "#2f9e1f"
ALWAYS_SHOWN = ("you", "home", "home range")   # drawn even with the F10 outlines off

def layer_shapes(config, monitor, boxes, r, mm=None, you=None, home=None):
    """Outlines over the game: [(x0, y0, x1, y1, colour, label), ...] in screen
    coordinates. The minimap (`mm`, else the setup's) and name area are drawn
    just outside what's read. Your dot ("you") and the pad's home (a line down
    the minimap, its range a band along the bottom) show even without F10."""
    out = []
    mb = config.get("mobs")
    if mb and "x" in mb and you:   # where your name tag says you are
        height = mb.get("bottom", mb["y"]) - mb.get("top", mb["y"])
        mb = dict(mb, x=you[0], y=you[1] - height // 2, top=you[1] - height, bottom=you[1])
        out.append((you[0] - 5, you[1] - 5, you[0] + 5, you[1] + 5, "#00e5ff", ""))
    if mb and "x" in mb:
        if mb.get("cell") or config.get("maps"):   # mobs are looked for this far
            left, top, w, h = mob_area(mb, monitor, mb.get("sight", SIGHT))
            out.append((left, top, left + w, top + h, "#4f8cff", "sight"))
        left, top, w, h = mob_area(mb, monitor)
        out.append((left, top, left + w, top + h, RED, "reach"))
    for x0, y0, x1, y1, name, n, *match in boxes:
        score = " %d%%" % round(match[0] * 100) if match and match[0] is not None else ""
        score += " (held)" if len(match) > 1 and match[1] else ""   # missed just now, seen a moment ago
        if n:
            out.append((x0, y0, x1, y1, AMBER, (name or "mob").replace("_", " ") + (" x%d" % n if n > 1 else "") + score))
        else:   # mob colours the shape check turned down
            out.append((x0, y0, x1, y1, DIM, "not a mob" + score))
    mm = mm or config.get("minimap")
    if mm:
        out.append((mm["x1"] - 2, mm["y1"] - 2, mm["x2"] + 2, mm["y2"] + 2, "#45d6b5", "minimap"))   # labelled below
        if r.get("x") is not None:
            x = mm["x1"] + r["x"] * (mm["x2"] - mm["x1"]) / 100.0
            y = mm["y1"] + r["y"] * (mm["y2"] - mm["y1"]) / 100.0
            out.append((int(x) - 4, int(y) - 4, int(x) + 4, int(y) + 4, "#00e5ff", "you"))   # not the dot's own colour
        at = home_place(r, home)
        if at is not None:
            span, top = mm["x2"] - mm["x1"], mm["y1"] + mm.get("header", 0)
            px = lambda pct: int(round(mm["x1"] + min(max(pct, 0.0), 100.0) * span / 100.0))   # off the minimap: at its edge
            if home["range"]:
                out.append((px(at - home["range"] / 10.0), mm["y2"] - 3, px(at + home["range"] / 10.0), mm["y2"], HOME_COLOR, "home range"))
            out.append((px(at) - 1, top, px(at) + 1, mm["y2"], HOME_COLOR, "home"))
    a = config.get("map_name")
    if a:
        out.append((a["x1"] - 2, a["y1"] - 2, a["x2"] + 2, a["y2"] + 2, "#c084fc", "map name"))
    return out

# The layer's look is MapleStory's own windows: a white rim with rounded
# bottom corners around a pane of white at BACKDROP_ALPHA over the game, one
# row of small drawn icons and dark bold text outlined in white, an orange
# maple leaf, warnings on red tags, mob names on dark name tags. Tk can't fade
# part of a window, so on Windows the pane is a window of its own behind the
# layer (white, faded, click-through, rounded by a window region).
MS = {"rim": "#ffffff", "edge": "#6f767e", "ink": "#262626", "muted": "#55595e", "line": "#c3c7cc",
      "orange": "#f6921e", "orange_ink": "#3a1d00", "orange_edge": "#a85400", "alert": "#d8263a", "alert_edge": "#8c0f1c",
      "hp": "#d9202a", "mp": "#1b62d6", "xp": "#4a7000", "gold": "#a65a00", "tag": "#1a1c20", "green": "#2f9e1f",
      "title": "#5b7189", "title_top": "#93a9bf", "body": "#f1f3f5", "field": "#ffffff", "teal": "#1d93ab"}
BACKDROP_ALPHA = 0.2     # how white the pane behind the strip is (0 clear, 1 solid white)
UI_FONT = "Arial"        # what the game's windows use (small and bold)
STRIP_MARGIN = 240       # px kept clear either side of the strip: the minimap (and its map name) is at the top left
STRIP_WIDTH = 880        # px: the strip's width (at most the screen's less the margins); fixed, so it doesn't jump
STRIP_HEIGHT = 26        # px: its one row
GAUGE = re.compile(r"^(HP|MP|XP) (\d+)%$")
XP_RATE = re.compile(r"^\+([\d.]+%/h)(?:, level in (.+))?$")

class Cell(tuple):
    """One item on the strip: (text, colour), with the width it's given (px,
    None for as wide as it is) so its neighbours don't move as it changes, the
    icon drawn before it and, if shorter, the text shown."""
    def __new__(cls, text, color, slot=None, icon=None, show=None):
        cell = super().__new__(cls, (text, color))
        cell.slot, cell.icon, cell.show = slot, icon, show
        return cell

def mix(a, b, t):
    """The colour t (0-1) of the way from a to b ("#rrggbb")."""
    ca, cb = [int(a[i:i + 2], 16) for i in (1, 3, 5)], [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(ca, cb))

def fit(text, width, measure):
    """The text cut (with "...") to fit `width` px by `measure` (text -> px)."""
    if measure(text) <= width:
        return text
    while text and measure(text + "\u2026") > width:
        text = text[:-1]
    return text.rstrip() + "\u2026"

def round_rect(c, x0, y0, x1, y1, r, **kw):
    """A rectangle with rounded corners on a tk canvas (a polygon)."""
    r = max(0, min(r, (x1 - x0) // 2, (y1 - y0) // 2))
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r,
           x0, y0 + r, x0, y0]
    return c.create_polygon(pts, smooth=True, **kw)

def shade(c, x0, y0, x1, y1, top, bottom, tags=()):
    """A top-to-bottom gradient (the title bars)."""
    for y in range(y0, y1):
        c.create_line(x0, y, x1, y, fill=mix(top, bottom, (y - y0) / max(1, y1 - y0 - 1)), tags=tags)

LEAF = ((.50, 0), (.58, .18), (.70, .12), (.66, .36), (.86, .24), (.82, .36), (1, .42), (.86, .52), (.92, .60), (.62, .62),
        (.66, .74), (.53, .70), (.53, 1), (.47, 1), (.47, .70), (.34, .74), (.38, .62), (.08, .60), (.14, .52), (0, .42),
        (.18, .36), (.14, .24), (.34, .36), (.30, .12), (.42, .18))

def ms_leaf(c, x, y, size, fill="#f6921e", tags=()):
    """A maple leaf, its middle at (x, y) (drawn: Tk can't show emoji everywhere)."""
    pts = [v for px, py in LEAF for v in (x + (px - .5) * size, y + (py - .5) * size)]
    return c.create_polygon(pts, fill=fill, outline=mix(fill, "#000000", 0.45), tags=tags)

def outlined(c, x, y, text, fill, font, anchor="w", tags=(), halo="#ffffff"):
    """Text with a 1 px outline all round, as the game draws it over busy
    scenery; returns the text's item."""
    for dx, dy in ((-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)):
        c.create_text(x + dx, y + dy, text=text, fill=halo, anchor=anchor, font=font, tags=tags)
    return c.create_text(x, y, text=text, fill=fill, anchor=anchor, font=font, tags=tags)

ICON = 14   # px an icon takes, with the gap after it

def draw_icon(c, kind, x, y, color=None, tags=()):
    """A small icon (12 px) with its left edge at x, middle at y: usb, wifi,
    pin (the map), mob (a mushroom), target, up (XP rate), clock (to the next
    level), home, warn. Outlined dark so it shows on any scenery."""
    o = {"outline": "#2b2b2b", "tags": tags}
    if kind == "usb":
        c.create_line(x + 4, y - 6, x + 4, y - 2, fill="#2b2b2b", width=2, tags=tags)
        c.create_line(x + 8, y - 6, x + 8, y - 2, fill="#2b2b2b", width=2, tags=tags)
        c.create_rectangle(x + 2, y - 2, x + 10, y + 4, fill=color or "#8a96a3", **o)
        c.create_line(x + 6, y + 4, x + 6, y + 7, fill="#2b2b2b", width=2, tags=tags)
    elif kind == "wifi":
        for r in (3, 6, 9):
            c.create_arc(x + 6 - r, y + 5 - r, x + 6 + r, y + 5 + r, start=50, extent=80, style="arc", width=2,
                         outline=color or "#1b62d6", tags=tags)
        c.create_oval(x + 5, y + 4, x + 7, y + 6, fill=color or "#1b62d6", outline="", tags=tags)
    elif kind == "pin":
        c.create_polygon(x + 3, y - 1, x + 9, y - 1, x + 6, y + 7, fill=color or "#d9202a", **o)
        c.create_oval(x + 2, y - 7, x + 10, y + 1, fill=color or "#d9202a", **o)
        c.create_oval(x + 5, y - 4, x + 7, y - 2, fill="#ffffff", outline="", tags=tags)
    elif kind == "mob":
        c.create_rectangle(x + 4, y, x + 8, y + 6, fill="#f3e3c3", **o)
        c.create_arc(x, y - 6, x + 12, y + 6, start=0, extent=180, style="chord", fill=color or "#f08a24", **o)
        for dx, dy in ((3, -3), (7, -4), (9, -1)):
            c.create_oval(x + dx - 1, y + dy - 1, x + dx + 1, y + dy + 1, fill="#ffffff", outline="", tags=tags)
    elif kind == "target":
        ring = color or "#2b2b2b"
        c.create_oval(x + 1, y - 5, x + 11, y + 5, outline=ring, width=2, tags=tags)
        c.create_line(x + 6, y - 7, x + 6, y + 7, fill=ring, width=1, tags=tags)
        c.create_line(x - 1, y, x + 13, y, fill=ring, width=1, tags=tags)
    elif kind == "up":
        c.create_polygon(x + 1, y + 4, x + 6, y - 5, x + 11, y + 4, fill=color or MS["green"], **o)
    elif kind == "clock":
        c.create_oval(x + 1, y - 5, x + 11, y + 5, fill="#ffffff", **o)
        c.create_line(x + 6, y, x + 6, y - 3, fill="#2b2b2b", width=1, tags=tags)
        c.create_line(x + 6, y, x + 9, y, fill="#2b2b2b", width=1, tags=tags)
    elif kind == "home":
        c.create_polygon(x, y - 1, x + 6, y - 7, x + 12, y - 1, fill=color or MS["green"], **o)
        c.create_rectangle(x + 2, y - 1, x + 10, y + 6, fill="#ffffff", **o)
        c.create_rectangle(x + 5, y + 2, x + 7, y + 6, fill=color or MS["green"], outline="", tags=tags)
    elif kind == "warn":
        c.create_polygon(x, y + 5, x + 6, y - 6, x + 12, y + 5, fill=color or "#ffd34d", **o)
        c.create_text(x + 6, y + 1, text="!", fill="#2b2b2b", font=(UI_FONT, 7, "bold"), tags=tags)
    return x + ICON

def ms_tag(c, x, y, text, color, anchor, tags=()):
    """A name tag as the game puts under characters and mobs: dark, rounded,
    its text in the outline's colour."""
    item = c.create_text(x, y, text=text, fill=color, anchor=anchor, font=(UI_FONT, 8, "bold"), tags=tags)
    x0, y0, x1, y1 = c.bbox(item)
    back = round_rect(c, x0 - 4, y0, x1 + 4, y1, 4, fill=MS["tag"], outline=mix(color, MS["tag"], 0.5), tags=tags)
    c.tag_raise(item, back)

class Layer:
    KEY = "#010203"   # drawn in this colour = see-through (Windows)

    def __init__(self, monitor):
        import tkinter as tk
        self.tk, self.monitor = tk, monitor
        self.windows = sys.platform == "win32"
        self.root = root = tk.Tk()
        root.title("Kabuto layer")
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        # Windows: the whole screen, see-through but for what's drawn. Elsewhere
        # there's no see-through colour, so just the strip.
        w, h = (monitor["width"], monitor["height"]) if self.windows else (monitor["width"], 60)
        root.geometry("%dx%d+%d+%d" % (w, h, monitor["left"], monitor["top"]))
        bg = self.KEY if self.windows else MS["body"]
        if self.windows:
            root.attributes("-transparentcolor", self.KEY)
        self.canvas = tk.Canvas(root, width=w, height=h, bg=bg, highlightthickness=0)
        self.canvas.pack()
        root.update_idletasks()
        self.unseen = self._click_through(root) if self.windows else True
        self.backdrop, self.placed = None, None
        if self.windows:   # the strip's faded white pane: a window of its own, under the layer
            pane = self.backdrop = tk.Toplevel(root)
            pane.overrideredirect(True)
            pane.attributes("-topmost", True)
            pane.attributes("-alpha", BACKDROP_ALPHA)
            pane.configure(bg="#ffffff")
            pane.geometry("1x1+%d+%d" % (monitor["left"] - 10, monitor["top"] - 10))
            pane.update_idletasks()
            self._click_through(pane)
            root.lift()
        root.report_callback_exception = self._error
        self.lock, self.commands, self.keys = threading.Lock(), queue.Queue(), queue.Queue()
        self.status, self.shapes = [("Kabuto", AMBER), ("starting", DIM)], []
        self.message, self.until = "F9 map \u00b7 F10 outlines \u00b7 F11 hide \u00b7 F12 map area (by hand)", time.time() + 20
        self.outlines, self.hidden, self.finished, self.maps, self.taught, self.picker = self.windows, False, False, [], {}, None
        self.changed = set()
        self.unlisten = listen(self.keys.put)

    def _click_through(self, window):
        """Clicks pass through to the game, no taskbar button, never focused;
        and left out of screen captures. False if Windows can't leave it out."""
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(window.winfo_id())
        style = user32.GetWindowLongW(hwnd, -20)   # GWL_EXSTYLE
        user32.SetWindowLongW(hwnd, -20, style | 0x80000 | 0x20 | 0x80 | 0x8000000)   # layered, transparent, tool, no-activate
        return bool(user32.SetWindowDisplayAffinity(hwnd, 0x11))   # WDA_EXCLUDEFROMCAPTURE

    def _error(self, kind, value, tb):
        if issubclass(kind, KeyboardInterrupt):
            self.root.quit()
        else:
            import traceback
            traceback.print_exception(kind, value, tb)

    # Called from the reading thread.
    def say(self, text, sticky=False):
        with self.lock:
            self.message, self.until = text, (float("inf") if sticky else time.time() + 12)

    def show(self, status, shapes):
        with self.lock:
            self.status, self.shapes = status, shapes

    def finish(self):
        self.finished = True

    # The window's own thread.
    def run(self):
        self._refresh()
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            pass
        self.unlisten()
        self.root.destroy()

    def _refresh(self):
        try:
            self._tick()
        except Exception as e:   # never let one error stop the layer (and F9, F10, F11 with it)
            if not getattr(self, "failed", None):
                import traceback
                traceback.print_exc()
                self.failed = str(e)
        self.root.after(150, self._refresh)

    def _tick(self):
        while not self.keys.empty():
            key = self.keys.get()
            if key == "f9":
                self._pick_map()
            elif key == "f10":
                self.outlines = not self.outlines
            elif key == "f11":
                self.hidden = not self.hidden
            elif key in ("f6", "f7"):   # looser / stricter mob colours, done by the reading loop
                self.commands.put(("tune", 1 if key == "f6" else -1))
            elif key == "f12":   # mark this map's minimap and name by hand, done by the reading loop
                self.commands.put(("area", None))
        with self.lock:
            status, shapes = list(self.status), list(self.shapes)
            message = self.message if time.time() < self.until else ""
        if not self.unseen:   # captured with the game: only outlines drawn outside what's read
            shapes = [s for s in shapes if s[5] in ("minimap", "map name")]
        self._draw(status, shapes if self.outlines else [s for s in shapes if s[5] in ALWAYS_SHOWN], message)
        if self.finished:
            self.root.after(4000 if message else 300, self.root.quit)
            self.finished = None

    def _draw(self, status, shapes, message):
        c, ox, oy = self.canvas, self.monitor["left"], self.monitor["top"]
        c.delete("all")
        if self.hidden:
            if self.backdrop and self.placed:
                self.backdrop.geometry("1x1+%d+%d" % (self.monitor["left"] - 10, self.monitor["top"] - 10))
                self.placed = None
            return
        for x0, y0, x1, y1, color, label in shapes:
            c.create_rectangle(x0 - ox, y0 - oy, x1 - ox, y1 - oy, outline=color, width=2)
            if label == "minimap":   # under it: the map name is usually just above
                ms_tag(c, x0 - ox + 4, y1 - oy + 4, label, color, "nw")
            elif label == "home":   # under the minimap, beside its own label
                ms_tag(c, x0 - ox, y1 - oy + 22, label, color, "n")
            elif label and label not in ("you", "home range"):
                ms_tag(c, x0 - ox + 4, y0 - oy - 4, label, color, "sw")
        # The strip: one row hanging from the top of the screen, its width
        # fixed, clear of the minimap at the top left (and the game's windows
        # at the top right). Items with a slot keep their place; what doesn't
        # fit at the end is cut.
        margin = min(STRIP_MARGIN, int(c["width"]) // 6)
        width = min(STRIP_WIDTH, int(c["width"]) - 2 * margin)
        bold = (UI_FONT, 9, "bold")
        if not getattr(self, "measure", None):
            import tkinter.font as tkfont
            self.measure = tkfont.Font(root=self.root, family=UI_FONT, size=9, weight="bold").measure
        x, y = 0, STRIP_HEIGHT // 2
        for i, cell in enumerate(status):
            text, color = cell
            slot, icon, show = getattr(cell, "slot", None), getattr(cell, "icon", None), getattr(cell, "show", None)
            text, tags, start = text if show is None else show, "strip", x
            room = width - x - (ICON if icon else 0)
            if room < 30:
                break   # no room left on the row
            gauge, rate = GAUGE.match(text), XP_RATE.match(text)
            if i == 0:   # Kabuto: the maple leaf
                ms_leaf(c, x + 8, y, 16, tags=tags)
                x += 18
            elif gauge and color in BAR_COLORS.values():   # just the %: the game's own bars are at the bottom
                name = outlined(c, x, y, gauge.group(1), MS[gauge.group(1).lower()], bold, tags=tags)
                outlined(c, c.bbox(name)[2] + 3, y, gauge.group(2) + "%", MS["ink"], bold, tags=tags)
                x += slot or 54
            elif rate:   # XP per hour, then the time to the next level
                x = draw_icon(c, "up", x, y, tags=tags)
                x = c.bbox(outlined(c, x, y, rate.group(1), MS["xp"], bold, tags=tags))[2] + 6
                if rate.group(2):
                    x = draw_icon(c, "clock", x, y, tags=tags)
                    outlined(c, x, y, rate.group(2), MS["ink"], bold, tags=tags)
                x = start + (slot or 0) if slot else c.bbox("strip")[2]
            elif color == RED:   # what needs you: a red tag
                label = text if slot is None else fit(text, slot - 12 - (ICON if icon else 0), self.measure)
                label = fit(label, room - 12, self.measure)
                inner = x + 6
                right = (x + slot) if slot else inner + (ICON if icon else 0) + self.measure(label) + 6
                box = round_rect(c, x, y - 9, right, y + 9, 5, fill=MS["alert"], outline=MS["alert_edge"], tags=tags)
                if icon:
                    inner = draw_icon(c, icon, inner, y, "#ffd34d" if icon == "warn" else "#ffffff", tags=tags)
                c.tag_raise(c.create_text(inner, y, text=label, fill="#ffffff", anchor="w", font=bold, tags=tags), box)
                x = right
            else:
                if icon:
                    x = draw_icon(c, icon, x, y, tags=tags)
                ink = {DIM: MS["muted"], AMBER: MS["gold"], BAR_COLORS["xp"]: MS["xp"]}.get(color, MS["ink"])
                label = fit(text, min(slot - (x - start) if slot else room, room), self.measure)
                item = outlined(c, x, y, label, ink, bold, tags=tags)
                x = start + slot if slot else c.bbox(item)[2]
            x += 10
        shift = max(margin, (int(c["width"]) - width) // 2)
        c.move("strip", shift, 0)
        panes = [(shift - 12, 0, shift + width + 12, STRIP_HEIGHT + 4)]
        if message:   # what to do next: a bubble under the strip, while there is something to say
            text = fit(message, int(c["width"]) - 2 * margin - 24, self.measure)
            w = self.measure(text)
            x0 = (int(c["width"]) - w) // 2
            outlined(c, x0, STRIP_HEIGHT + 20, text, MS["gold"], bold, tags="bubble")
            panes.append((x0 - 12, STRIP_HEIGHT + 9, x0 + w + 12, STRIP_HEIGHT + 31))
        for i, (x0, y0, x1, y1) in enumerate(panes):   # the white rim (top corners off the screen for the strip)
            top = y0 - 10 if i == 0 else y0
            if not self.backdrop:   # no faded pane (not Windows): a solid one
                round_rect(c, x0, top, x1, y1, 8, fill=MS["body"], outline="", tags="pane")
            round_rect(c, x0 - 1, top - 1, x1 + 1, y1 + 1, 9, fill="", outline=MS["edge"], tags="pane")
            round_rect(c, x0, top, x1, y1, 8, fill="", outline=MS["rim"], width=2, tags="pane")
        c.tag_lower("pane")
        self._place_backdrop(panes)

    def _place_backdrop(self, panes):
        """The faded white pane behind the strip (and the bubble): one window,
        cut to their rounded shapes by a window region (Windows only)."""
        if not self.backdrop or panes == self.placed:
            return
        self.placed = panes
        import ctypes
        user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
        handle = ctypes.c_void_p   # 64-bit handles
        gdi32.CreateRoundRectRgn.restype = handle
        gdi32.CombineRgn.argtypes = (handle, handle, handle, ctypes.c_int)
        gdi32.DeleteObject.argtypes = (handle,)
        user32.SetWindowRgn.argtypes = (handle, handle, ctypes.c_bool)
        ox, oy = self.monitor["left"], self.monitor["top"]
        x0, y0 = min(p[0] for p in panes), min(p[1] for p in panes)
        x1, y1 = max(p[2] for p in panes), max(p[3] for p in panes)
        self.backdrop.geometry("%dx%d+%d+%d" % (x1 - x0 + 1, y1 - y0 + 1, ox + x0, oy + y0))
        self.backdrop.update_idletasks()
        region = None
        for i, (a, b, c_, d) in enumerate(panes):
            top = b - y0 - (10 if i == 0 else 0)   # the strip's top corners off the screen: square
            part = gdi32.CreateRoundRectRgn(a - x0, top, c_ - x0 + 1, d - y0 + 1, 16, 16)
            if region is None:
                region = part
            else:
                gdi32.CombineRgn(region, region, part, 2)   # RGN_OR
                gdi32.DeleteObject(part)
        user32.SetWindowRgn(user32.GetParent(self.backdrop.winfo_id()), region, True)   # Windows owns the region now

    def _pick_map(self):
        """Which map (from map.json) this is: a searchable list. Type to
        narrow it, arrows to move, Enter or a double click to pick, Esc to close."""
        tk = self.tk
        if self.picker:
            try:
                if self.picker.winfo_exists():   # already open: to the front
                    self.picker.deiconify(); self.picker.lift(); self.picker.focus_force()
                    return
            except tk.TclError:
                pass
            self.picker = None
        if not self.maps:
            self.say('List your maps in mobs/%s, e.g. [{"name": "Henesys", "mobs": ["snail.png"]}], with the PNGs in mobs, then F9' % MAP_LIST)
            return
        # Light, like the game's own windows: a title bar like the minimap's, a
        # white field to type in, the list on pale paper, orange to pick.
        body_bg, ink, font = MS["body"], MS["ink"], UI_FONT
        win = self.picker = tk.Toplevel(self.root)
        win.title("Which map is this?")
        win.attributes("-topmost", True)
        win.configure(bg=MS["edge"], padx=1, pady=1)
        w, h = 440, 540
        win.geometry("%dx%d+%d+%d" % (w, h, self.monitor["left"] + (self.monitor["width"] - w) // 2,
                                      self.monitor["top"] + max(40, (self.monitor["height"] - h) // 3)))
        title = tk.Canvas(win, height=22, bg=MS["title"], highlightthickness=0)
        title.pack(fill="x")
        title.bind("<Configure>", lambda e: (title.delete("all"), shade(title, 0, 0, e.width, 22, MS["title_top"], MS["title"]),
                                             ms_leaf(title, 14, 11, 12),
                                             title.create_text(26, 11, text="MAP LIST", fill="#ffffff", anchor="w",
                                                               font=(font, 9, "bold"))))
        body = tk.Frame(win, bg=body_bg, padx=12, pady=10)
        body.pack(fill="both", expand=True)
        tk.Label(body, text="Which map are you on?", bg=body_bg, fg=ink, font=(font, 12, "bold")).pack(anchor="w")
        tk.Label(body, text="Type to search  \u00b7  \u2191\u2193 to move  \u00b7  Enter picks  \u00b7  Esc closes",
                 bg=body_bg, fg=MS["muted"], font=(font, 8)).pack(anchor="w", pady=(2, 0))
        query = tk.StringVar()
        entry = tk.Entry(body, textvariable=query, bg=MS["field"], fg=ink, insertbackground=ink, relief="flat",
                         font=(font, 11), highlightthickness=1, highlightbackground=MS["edge"], highlightcolor=MS["orange"])
        entry.pack(fill="x", ipady=5, pady=(10, 0))
        box = tk.Frame(body, bg=MS["edge"], padx=1, pady=1)
        box.pack(fill="both", expand=True, pady=(8, 8))
        bar = tk.Scrollbar(box, orient="vertical", relief="flat", borderwidth=0)
        rows = tk.Listbox(box, bg=MS["field"], fg=ink, font=(font, 10), activestyle="none", relief="flat", highlightthickness=0,
                          selectbackground=MS["orange"], selectforeground=MS["orange_ink"], borderwidth=0,
                          yscrollcommand=bar.set)
        bar.config(command=rows.yview)
        bar.pack(side="right", fill="y")
        rows.pack(side="left", fill="both", expand=True)
        foot = tk.Frame(body, bg=body_bg)
        foot.pack(fill="x")
        count = tk.Label(foot, bg=body_bg, fg=MS["muted"], font=(font, 8))
        count.pack(side="left")
        shown = []
        def close(_=None):
            win.destroy()
            self.picker = None
        def choose(_=None):
            picked = rows.curselection()
            if picked:
                name = shown[picked[0]][0]
                close()
                self.commands.put(("teach", name))
            return "break"
        def move(step):
            if shown:
                at = min(max((rows.curselection() or (0,))[0] + step, 0), len(shown) - 1)
                rows.selection_clear(0, "end"); rows.selection_set(at); rows.activate(at); rows.see(at)
            return "break"
        def refresh(*_):
            shown[:] = pick_list(self.maps, query.get(), self.taught, self.changed)
            rows.delete(0, "end")
            for i, (name, note) in enumerate(shown):
                rows.insert("end", "  %s%s" % (name, "     " + note if note else ""))
                if note:
                    rows.itemconfig(i, fg=MS["gold"] if note.startswith("changed") else MS["teal"])
            if shown:
                rows.selection_set(0); rows.see(0)
            total = len(self.maps)
            count.config(text=("%d of %d maps" % (len(shown), total) if query.get().strip() else "%d maps" % total)
                         + ("" if shown else "  \u00b7  no match"))
        tk.Button(foot, text="Cancel", command=close, bg="#ffffff", fg=ink, relief="flat", padx=12, pady=2,
                  activebackground="#e4e7ea", activeforeground=ink, font=(font, 9, "bold"), cursor="hand2",
                  highlightthickness=1, highlightbackground=MS["edge"]).pack(side="right")
        tk.Button(foot, text="Teach this map", command=choose, bg=MS["orange"], fg=MS["orange_ink"], relief="flat", padx=12,
                  pady=2, activebackground="#ffb04d", activeforeground=MS["orange_ink"], font=(font, 9, "bold"),
                  cursor="hand2", highlightthickness=1, highlightbackground=MS["orange_edge"]).pack(side="right", padx=(0, 8))
        query.trace_add("write", refresh)
        for key, step in (("<Down>", 1), ("<Up>", -1), ("<Next>", 10), ("<Prior>", -10)):
            entry.bind(key, lambda e, s=step: move(s))
            rows.bind(key, lambda e, s=step: move(s))
        for widget in (entry, rows):
            widget.bind("<Return>", choose)
        rows.bind("<Double-Button-1>", choose)
        win.bind("<Escape>", close)
        win.protocol("WM_DELETE_WINDOW", close)   # its X button (or Alt+F4) too, so F9 opens it again
        self.pick = {"query": query, "rows": shown, "choose": choose, "move": move, "list": rows}   # for the self-test
        refresh()
        win.after(50, entry.focus_force)

ERROR_LOG = "kabuto-error.txt"   # next to the setup file: the details of anything that went wrong

def report_error(e):
    """An error's details into ERROR_LOG and the console, and a line on the strip."""
    import traceback
    details = "".join(traceback.format_exception(type(e), e, e.__traceback__))
    try:
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + details + "\n")
        where = " (details in %s)" % os.path.abspath(ERROR_LOG)
    except OSError:
        where = " (details in the console)"
    print(details, file=sys.stderr)
    say("Error: %s%s" % (e, where))

def with_layer(job, enabled=True):
    """Runs `job` with the game layer up (the job on its own thread; the
    window needs the main one). Without tkinter or a screen, just the job."""
    global LAYER
    if enabled:
        try:
            import mss
            monitors = mss.mss().monitors   # first: makes the process DPI-aware, so the layer lines up
            LAYER = Layer(monitors[1] if len(monitors) > 1 else monitors[0])
        except Exception as e:   # no tkinter, no display
            print("(game layer off: %s)" % e)
            LAYER = None
    if not LAYER:
        return job()
    ended = {}
    def work():
        try:
            job()
        except SystemExit as e:
            ended["exit"] = e
            if e.code and not isinstance(e.code, int):
                say(str(e.code))
        except Exception as e:
            ended["error"] = e
            report_error(e)
        finally:
            LAYER.finish()
    threading.Thread(target=work, daemon=True).start()
    LAYER.run()
    if "exit" in ended:
        raise ended["exit"]
    if "error" in ended:
        raise ended["error"]

# ---- self-test ---------------------------------------------------------------------

def selftest():
    red, grey, white = (200, 30, 30), (40, 40, 40), (255, 255, 255)
    assert fill_percent([red] * 100, red) == 100.0
    assert fill_percent([red] * 72 + [grey] * 28, red) == 72.0
    assert fill_percent([grey] * 100, red) == 0.0
    # Numbers drawn over the bar don't shorten it; a stray matching pixel doesn't lengthen it.
    assert fill_percent([red] * 30 + [white] * 10 + [red] * 20 + [grey] * 40, red) == 60.0
    assert fill_percent([red] * 50 + [grey] * 30 + [red] + [grey] * 19, red) == 50.0
    assert fill_percent([(190, 40, 35)] * 40 + [grey] * 60, red) == 40.0   # shading within tolerance
    assert fill_percent([], red) is None
    # A bar that fades along its length (dark to light blue) is followed to its end,
    # even past numbers drawn over it; the empty part after it isn't.
    fade = [(20 + i * 2, 50 + i * 2, 150 + i) for i in range(70)]
    assert fill_percent(fade + [grey] * 30, fade[0]) == 70.0
    assert fill_percent(fade[:35] + [white] * 8 + fade[43:] + [grey] * 30, fade[0]) == 70.0
    assert fill_percent(fade + [(25, 30, 60)] * 30, fade[0]) == 70.0   # dark-blue empty part

    def canvas(w, h, bg):
        return bytearray(bytes(bg) * (w * h))
    def paint(raw, w, x0, y0, x1, y1, color):
        for y in range(y0, y1):
            for x in range(x0, x1):
                raw[(y * w + x) * 3:(y * w + x) * 3 + 3] = bytes(color)
    np_ = numpy_or_none()
    if np_:   # the numpy slide finder agrees with the plain one
        rnd = random.Random(5)
        big = bytes(rnd.randrange(256) for _ in range(160 * 90 * 3))
        def view(ox, oy, w=100, h=50):
            return b"".join(big[((oy + y) * 160 + ox) * 3:((oy + y) * 160 + ox + w) * 3] for y in range(h))
        for (ax, ay), (bx, by) in (((20, 10), (27, 14)), ((30, 20), (24, 17)), ((10, 5), (10, 5))):
            p_, c_ = view(ax, ay), view(bx, by)
            fast = find_slide_np(np_, p_, c_, 100, 50, 25, 12)
            dx = dy = 0
            for _ in range(2):
                py, cy = (max(0, dy), min(50, 50 + dy)), (max(0, -dy), min(50, 50 - dy))
                dx = best_shift(col_profile(p_, 100, 0, 100, *py), col_profile(c_, 100, 0, 100, *cy), 25)[0]
                px, cx = (max(0, dx), min(100, 100 + dx)), (max(0, -dx), min(100, 100 - dx))
                dy = best_shift(row_profile(p_, 100, px[0], px[1], 0, 50), row_profile(c_, 100, cx[0], cx[1], 0, 50), 12)[0]
            plain = (dx, dy, overlap_mismatch(p_, c_, 100, 50, dx, dy))
            assert fast[:2] == plain[:2] and abs(fast[2] - plain[2]) < 1e-6, (fast, plain)
    # The minimap's frame: its near-white edge line, down the map picture and across it.
    frame_raw = canvas(300, 300, (30, 40, 50))
    paint(frame_raw, 300, 0, 0, 300, 72, (170, 190, 210))                       # the header
    paint(frame_raw, 300, 180, 72, 181, 251, (250, 250, 250))                   # its right edge line...
    paint(frame_raw, 300, 0, 250, 181, 251, (250, 250, 250))                    # ...and its bottom one
    for x, y in ((60, 100), (61, 101), (120, 150), (220, 90)):
        paint(frame_raw, 300, x, y, x + 1, y + 1, (255, 255, 255))              # white specks in the picture and around it
    paint(frame_raw, 300, 200, 72, 300, 300, (240, 240, 240))                   # bright sky right of the minimap
    assert find_minimap_frame(frame_raw, 300, 300) == (180, 250)
    assert find_minimap_frame(canvas(300, 300, (30, 40, 50)), 300, 300) is None # no minimap on screen
    area = {"x1": 47, "y1": 43, "x2": 246, "y2": 56, "auto": True}
    assert name_limit(area, (190, 230)) == 141 and name_limit(dict(area, auto=False), (190, 230)) is None
    assert auto_name_area("maplestory", {"x1": 0, "y1": 0, "auto": True})["x2"] == 246 and auto_name_area("maplestory", {"x1": 0, "y1": 0}) is None
    letters = canvas(20, 3, (60, 70, 90)); paint(letters, 20, 2, 1, 4, 2, (250, 250, 250)); paint(letters, 20, 15, 1, 17, 2, (250, 250, 250))
    assert text_rows(letters, 20, 3)[1] == 0b11 << 2 | 0b11 << 15 and text_rows(letters, 20, 3, limit=10)[1] == 0b11 << 2   # past the edge: left out
    # Minimap dot: found at its centre, absent when gone.
    yellow = (250, 220, 40)
    mm = canvas(101, 51, grey); paint(mm, 101, 20, 30, 24, 34, yellow)
    x, y = find_dot(mm, 101, 51, yellow)
    assert abs(x - 21.0) < 2 and abs(y - 63.0) < 3, (x, y)
    assert find_dot(canvas(101, 51, grey), 101, 51, yellow) is None
    paint(mm, 101, 60, 2, 80, 12, yellow)                                     # a dot-coloured icon in the header...
    assert find_dot(mm, 101, 51, yellow)[1] < 50                              # ...drags the dot up
    x, y = find_dot(mm, 101, 51, yellow, top=16)                             # looked for below the header: just the dot
    assert abs(x - 21.0) < 2 and abs(y - 63.0) < 3, (x, y)
    ms_mm = apply_game({"game": "maplestory", "minimap": {"x1": 0, "y1": 0, "x2": 138, "y2": 196}})["minimap"]
    assert ms_mm["header"] == 72 and "header" not in apply_game({"game": "maplestory", "minimap": {"x1": 0, "y1": 72, "x2": 138, "y2": 196}})["minimap"]
    # A minimap that slides as you walk: a 400x120 map seen through a 100x40
    # minimap. Mid-map the view slides and your dot stays in the middle; at the
    # map's edge the view stops and the dot moves instead.
    def textured(w, h, seed):
        rnd = random.Random(seed)
        cells = [[rnd.randrange(40, 200) for _ in range(w // 7 + 1)] for _ in range(h // 5 + 1)]
        out = bytearray()
        for y in range(h):
            for x in range(w):
                v = cells[y // 5][x // 7]
                out += bytes((v, v, v))
        return out
    world_map = textured(400, 120, 1)
    def view(ox, oy, dot=None, world=world_map, ww=400):
        raw = bytearray()
        for y in range(oy, oy + 40):
            raw += world[(y * ww + ox) * 3:(y * ww + ox + 100) * 3]
        if dot:
            paint(raw, 100, dot[0] - 2, dot[1] - 2, dot[0] + 2, dot[1] + 2, yellow)
        return raw
    t = MinimapTracker()
    positions = []
    for ox, oy, dot in ((0, 40, (50, 20)), (12, 40, (50, 20)), (30, 44, (50, 20)), (55, 44, (50, 20))):
        raw = view(ox, oy, dot)
        t.update(raw, 100, 40)
        d = find_dot(raw, 100, 40, yellow)
        positions.append(t.world(d, 100, 40))
    # Slides of 12, 18 and 25 px (and 4 down) are tracked: map position moves even though the dot doesn't.
    assert (t.ox, t.oy) == (55, 4), (t.ox, t.oy)
    assert positions[0][0] < positions[1][0] < positions[2][0] < positions[3][0], positions
    assert abs(positions[3][0] - positions[0][0] - round(55 * 1000 / 99)) <= 2
    # A view that can't be lined up (teleport, another map) adds no slide; the new view is followed on.
    t2 = MinimapTracker()
    t2.update(view(0, 40, (50, 20)), 100, 40)
    t2.update(view(10, 40, (50, 20)), 100, 40)
    t2.update(view(10, 40, (50, 20), textured(400, 120, 999)), 100, 40)
    assert (t2.ox, t2.oy) == (10, 0), (t2.ox, t2.oy)
    t2.update(view(14, 40, (50, 20), textured(400, 120, 999)), 100, 40)
    assert t2.ox == 14
    # At the map's edge the view stops sliding; the dot moving still moves you.
    t3 = MinimapTracker()
    for dot_x in (40, 60, 80):
        t3.update(view(300, 44, (dot_x, 20)), 100, 40)
    assert t3.ox == 0 and t3.world((80.0, 50.0), 100, 40)[0] == 800
    # Mobs: left, right, both, none; your own character in the middle is ignored.
    green = (60, 200, 60)
    for x0, want in ((50, "L"), (600, "R"), (None, "")):
        zone = canvas(700, 160, grey)
        paint(zone, 700, 330, 40, 370, 120, green)        # you, in the skipped middle
        if x0 is not None:
            paint(zone, 700, x0, 50, x0 + 40, 110, green)
        assert mob_sides(zone, 700, 160, [green]) == want, want
    # Hitbox: head and feet set its height, the reach point how far it goes each side.
    hb = hitbox((402, 300), (398, 420), (800, 410))
    assert hb == {"x": 400, "y": 360, "top": 300, "bottom": 420, "reach": 400, "gap": 40}, hb
    assert mob_area(hb, {"left": 0, "top": 0, "width": 1920, "height": 1080}) == (0, 260, 800, 280)   # 40 px above, 40 + 80 below: 800 x 280
    assert mob_area(hb, {"left": 0, "top": 0, "width": 700, "height": 1080}) == (0, 260, 700, 280)    # clipped to the screen
    assert mob_area(dict(hb, pad=0, below=0), {"left": 0, "top": 0, "width": 1920, "height": 1080}) == (0, 300, 800, 120)   # "pad": 0, "below": 0
    assert mob_area({"x": 400, "y": 360}, {"left": 0, "top": 0, "width": 1920, "height": 1080}) == (100, 280, 600, 240)   # older setups: reach 300
    # Character near the screen edge: the area is clipped, so "you" aren't in its middle.
    clipped = canvas(450, 160, grey); paint(clipped, 450, 80, 40, 120, 120, green); paint(clipped, 450, 300, 50, 340, 110, green)
    assert mob_sides(clipped, 450, 160, [green], mid=100) == "R"
    both = canvas(700, 160, grey); paint(both, 700, 50, 50, 90, 110, green); paint(both, 700, 600, 50, 640, 110, green)
    assert mob_sides(both, 700, 160, [(1, 2, 3), green]) == "RL"            # both: the right one is nearer (250 vs 260 px)
    paint(both, 700, 250, 50, 290, 110, green)
    assert mob_sides(both, 700, 160, [(1, 2, 3), green]) == "LR"            # a left one walks closer
    # Mob sprites: outline black and white left out, a colour much of the map
    # also has is dropped, and what's left finds the mob on the right side only.
    # A 20x20 sprite: transparent border, black outline, pink body, green feet.
    sprite = [(0, 0, 0, 0) if not (2 <= x < 18 and 2 <= y < 18) else (0, 0, 0, 255) if x in (2, 17) or y in (2, 17)
              else (60, 200, 60, 255) if y >= 14 else (200, 40, 160, 255) for y in range(20) for x in range(20)]
    palette = sprite_palette(sprite)
    assert [c for c, _ in palette] == [[200, 40, 160], [60, 200, 60]], palette
    field = canvas(300, 60, grey); paint(field, 300, 0, 50, 300, 60, green)   # grass along the bottom
    def put(raw, x0, y0):
        for y in range(20):
            for x in range(20):
                if sprite[y * 20 + x][3]:
                    raw[((y0 + y) * 300 + x0 + x) * 3:((y0 + y) * 300 + x0 + x + 1) * 3] = bytes(sprite[y * 20 + x][:3])
    # A mob walking through one of the setup shots doesn't spoil its colours.
    busy = bytearray(field); put(busy, 40, 20)
    learned, report = learn_mob_colors({"blob.png": (20, 20, sprite)}, [busy, field, field], 300, 60)
    assert learned["colors"] == [[200, 40, 160]] and learned["step"] == 2 and learned["cell"] == 10, (learned, report)
    assert any("skipped [60, 200, 60]" in r for r in report) and learned["min_hits"] == 3, report
    # Stray pink pixels over the map (about 2%): learned from the map, they
    # raise the hits a patch needs, so they aren't a mob; a real one still is.
    rnd, noisy = random.Random(4), bytearray(field)
    for k in range(300 * 50):
        if rnd.random() < 0.02:
            noisy[k * 3:k * 3 + 3] = bytes((200, 40, 160))
    learned, _ = learn_mob_colors({"blob.png": (20, 20, sprite)}, [noisy], 300, 60)
    sides = dict(colors=learned["colors"], step_x=2, step_y=2, min_hits=learned["min_hits"], cell=learned["cell"])
    assert learned["min_hits"] > 3 and mob_sides(noisy, 300, 60, **sides) == "", learned
    assert len(mob_sides(noisy, 300, 60, learned["colors"], step_x=2, step_y=2)) == 2   # the old way counted every stray
    put(noisy, 220, 30)
    assert mob_sides(noisy, 300, 60, **sides) == "R"
    assert sniff(b"") == "an empty file" and sniff(b"<!DOCTYPE html>").startswith("a web page")
    assert sniff(b"\x89PNG\r\n\x1a\n").startswith("a damaged") and sniff(b"RIFF\0\0\0\0WEBPVP8 ").startswith("a WebP")
    assert sniff(b"\0\0\0\x1cftypavif").startswith("an AVIF") and sniff(b"hello") == "not an image Pillow knows"
    learned, report = learn_mob_colors({"grass.png": (20, 20, [(60, 200, 60, 255)] * 400)}, [field], 300, 60)
    assert not learned["colors"] and "no colour of its own" in report[-1]
    # A colour the map hasn't got, but only a speck of the mob: dropped, and said why.
    speck = [(60, 200, 60, 255) if not (x < 2 and y < 2) else (200, 40, 160, 255) for y in range(20) for x in range(20)]
    learned, report = learn_mob_colors({"speck.png": (20, 20, speck)}, [field], 300, 60)
    assert not learned["colors"] and any("not on the map, but too little of it to spot" in r for r in report), report
    learned, _ = learn_mob_colors({"blob.png": (20, 20, sprite)}, [field], 300, 60)
    assert learned["names"] == ["blob"] and learned["mob_w"] == 20, learned   # colours named after their sprite
    # Every mob in sight: counted each side, nearest first, named; two side by
    # side make one clump twice a mob's width, so they count as two.
    def stamp(raw, w, x0, y0):
        for y in range(20):
            for x in range(20):
                if sprite[y * 20 + x][3]:
                    raw[((y0 + y) * w + x0 + x) * 3:((y0 + y) * w + x0 + x + 1) * 3] = bytes(sprite[y * 20 + x][:3])
    sight = canvas(1000, 30, grey)
    for x0 in (100, 600, 800, 820):
        stamp(sight, 1000, x0, 5)
    seen = mob_view(sight, 1000, 30, [[200, 40, 160]], gap=40, step=2, min_hits=3, cell=10, names=["blob"], mob_w=20)
    assert [d for d, _ in seen["R"]] == [104, 304, 324] and [d for d, _ in seen["L"]] == [384], seen
    assert {n for side in seen.values() for _, n in side} == {"blob"}
    assert mob_fields(seen, 200) == {"mobs": "R", "ml": 1, "mr": 3, "ir": 1, "dr": 52, "dl": 192, "mn": "blob"}   # 1 in reach of 4
    assert mob_fields(seen, 400) == {"mobs": "RL", "ml": 1, "mr": 3, "ir": 4, "dr": 26, "dl": 96, "mn": "blob"}
    assert mob_fields({"L": [], "R": []}, 200) == {"mobs": "", "ml": 0, "mr": 0, "ir": 0, "mn": None}   # none: no distances
    assert mob_view(canvas(1000, 30, grey), 1000, 30, [[200, 40, 160]], step=2, cell=10) == {"L": [], "R": []}
    assert [n for _, n in mob_view(sight, 1000, 30, [[200, 40, 160]], step=2, cell=10)["R"]] == [None, None]   # no names; no mob_w: 1 per clump
    # Map names as pictures: the same name matches even a pixel off; another doesn't.
    dark, white = (20, 20, 30), (240, 240, 240)
    def name_area(rects, dx=0):
        raw = canvas(60, 14, dark)
        for x0, y0, x1, y1 in rects:
            paint(raw, 60, x0 + dx, y0, x1 + dx, y1, white)
        return raw
    henesys, ellinia = [(2, 2, 6, 10), (8, 2, 10, 10), (12, 5, 18, 7), (22, 2, 24, 10)], [(2, 2, 30, 4), (40, 6, 58, 12)]
    a = text_rows(name_area(henesys), 60, 14)
    assert ones(a) == 4 * 8 + 2 * 8 + 6 * 2 + 2 * 8 and rows_score(a, a) == 1.0
    assert rows_score(a, text_rows(name_area(henesys, 1), 60, 14)) == 1.0
    assert rows_score(a, text_rows(name_area(ellinia), 60, 14)) < 0.5 and rows_score([0] * 14, [0] * 14) == 0.0
    reader = MapReader({"Henesys": {"rows": ["%x" % r for r in a], "name_reading": NAME_READING},
                        "Ellinia": {"rows": ["%x" % r for r in text_rows(name_area(ellinia), 60, 14)], "name_reading": NAME_READING},
                        "Old Map": {"rows": ["%x" % r for r in a]}})   # taught before names were read this way: not matched
    assert reader.read(name_area(henesys, 1), 60, 14) == "Henesys" and reader.read(name_area(ellinia), 60, 14) == "Ellinia"
    assert reader.read(name_area([(5, 3, 50, 11)]), 60, 14) == ""   # a map you haven't taught
    assert safe_name("Henesys Hunting Ground!") == "Henesys_Hunting_Ground_" and safe_name("Slime-2") == "Slime-2"
    # Marked patches.
    ref = bytes([10, 20, 30] * 25)
    assert patch_matches(bytes([12, 18, 33] * 25), ref) and not patch_matches(bytes([200, 200, 200] * 25), ref)
    assert not patch_matches(b"", ref)
    # The whole mob search: every reading by default; with "search_every", followed in between.
    assert search_due(5, 4.8, True) and search_due(0, None, False, 0.5) and search_due(5, 4.9, False, 0.5)
    assert not search_due(5, 4.7, True, 0.5) and search_due(5, 4.5, True, 0.5)
    # Game state needs agreeing readings; marks win straight away.
    # Dead: HP under 5% for 2 s with the minimap still showing.
    g = GameState()
    assert [g.update(hp, 50, True, True, {}, now=t) for t, hp in ((0, 3.0), (1, 0.0), (2, 0.0), (3, 70.0))] == ["ok", "ok", "dead", "ok"]
    assert [GameState().update(6.0, 50, True, True, {}, now=t) for t in (0, 5)] == ["ok", "ok"]   # 6%: low, not dead
    g = GameState()   # changing maps: the screen fades, HP reads 0 and the minimap's dot goes: not dead
    assert [g.update(0.0, 0.0, False, True, {}, now=t / 2) for t in range(12)] == ["ok"] * 12
    assert g.update(81.0, 82.0, True, True, {}, now=6) == "ok"
    g = GameState()   # no minimap set up: a dark screen empties both bars (not dead); dead keeps Mana
    assert [g.update(0.0, 0.0, False, False, {}, now=t) for t in range(5)] == ["ok"] * 5
    assert [g.update(0.0, 40.0, False, False, {}, now=t) for t in (5, 7)] == ["ok", "dead"]
    # Disconnected: no bars and no minimap for 10 s (a loading screen is over sooner).
    g = GameState()
    assert [g.update(None, 0, False, True, {}, now=t) for t in (0, 5, 9.9, 10)] == ["ok", "ok", "ok", "offline"]
    assert GameState().update(80, 50, True, True, {"death": True}) == "dead"
    assert GameState().update(80, 50, True, True, {"login": True, "death": True}) == "offline"
    assert GameState().update(None, None, False, False, {}) == "ok"   # nothing set up: no false alarms
    g = GameState()   # the test popup: two readings in a row; a mark at once; the login screen still wins
    assert [g.update(80, 50, True, True, {}, p) for p in (True, False, True, True, True)] == ["ok", "ok", "ok", "test", "test"]
    assert g.update(0, 50, True, True, {}) == "ok" and GameState().update(80, 50, True, True, {"test": True}) == "test"
    assert GameState().update(80, 50, True, True, {"login": True, "test": True}) == "offline"
    # The test popup: a teal panel (with text) in a dark window with a light rim.
    def popup(raw, w, x, y, rim=(220, 220, 222), band=(48, 48, 48)):
        paint(raw, w, x, y, x + 262, y + 188, rim)
        paint(raw, w, x + 4, y + 4, x + 258, y + 184, band)
        for k in range(17):   # the panel darkens to the top, as the game's does
            paint(raw, w, x + 12, y + 13 + k * 4, x + 252, y + 17 + k * 4, (30, 112 + k * 3, 142 + k * 2))
        for line in (24, 40, 56):   # its words
            for word in range(14, 230, 26):
                paint(raw, w, x + word, y + line, x + word + 20, y + line + 9, (250, 250, 250))
        paint(raw, w, x + 12, y + 90, x + 150, y + 175, (120, 120, 120))   # the box under it
    scene = canvas(800, 600, (150, 110, 60))
    assert find_test_popup(bytes(scene), 800, 600) is None
    popup(scene, 800, 520, 380)
    box = find_test_popup(bytes(scene), 800, 600)
    assert box and abs(box[0] - 532) <= TEST_STEP and abs(box[1] - 393) <= TEST_STEP and abs(box[2] - 768) <= TEST_STEP, box
    popup(scene, 800, 0, 0)   # anywhere on screen, even at its edge
    assert find_test_popup(bytes(scene), 800, 600)
    sea = canvas(800, 600, (150, 110, 60))
    paint(sea, 800, 100, 100, 700, 400, (30, 140, 170))   # teal water: no window around it
    assert find_test_popup(bytes(sea), 800, 600) is None
    paint(sea, 800, 90, 90, 710, 100, (48, 48, 48))       # a dark band but no light rim
    assert find_test_popup(bytes(sea), 800, 600) is None
    small = canvas(800, 600, (150, 110, 60))
    popup(small, 800, 100, 100)
    paint(small, 800, 100, 100, 362, 288, (150, 110, 60)); paint(small, 800, 100, 100, 200, 140, (220, 220, 222))
    paint(small, 800, 104, 104, 196, 136, (48, 48, 48)); paint(small, 800, 110, 110, 190, 130, (30, 130, 160))
    assert find_test_popup(bytes(small), 800, 600) is None   # a small teal box in a window: not the panel
    # The Lie Detector mini-game's notice: a blue panel with a light rim right round it (no dark band),
    # its words and pictures over a good part of it.
    lie = canvas(800, 600, (40, 70, 30))
    paint(lie, 800, 480, 360, 790, 590, (232, 250, 250))                 # light rim
    paint(lie, 800, 486, 366, 784, 584, (74, 130, 187))                  # blue panel
    for line in (380, 396, 412):
        for word in range(500, 760, 30):
            paint(lie, 800, word, line, word + 22, line + 8, (250, 250, 250))
    for x0 in (500, 590, 680):
        paint(lie, 800, x0, 460, x0 + 80, 540, (170, 150, 110))          # the three star pictures
    box = find_test_popup(bytes(lie), 800, 600)
    assert box and abs(box[0] - 486) <= TEST_STEP and abs(box[1] - 366) <= TEST_STEP, box
    sky = canvas(800, 600, (40, 70, 30)); paint(sky, 800, 100, 50, 700, 300, (74, 130, 187))   # blue sky: no rim
    assert find_test_popup(bytes(sky), 800, 600) is None
    # What's posted: unread values left out, state always sent, mobs (even
    # empty: "none around") only with a mob detector.
    assert form_fields({"hp": 72.0, "mana": None, "xp": 63.2, "x": None, "y": None, "mobs": "", "state": "ok"}) == \
        {"hp": 72.0, "xp": 63.2, "state": "ok", "mobs": ""}
    assert form_fields({"hp": 72.0, "mobs": None, "state": "ok"}) == {"hp": 72.0, "state": "ok"}
    assert form_fields({"hp": 0.0, "x": 41.5, "y": 70.0, "mobs": "L", "state": "dead"}) == \
        {"hp": 0.0, "x": 41.5, "y": 70.0, "state": "dead", "mobs": "L"}

    # A full read from a fake 800x600 screen: bars, minimap with your dot, a mob.
    class Shot:
        def __init__(self, rgb): self.rgb = rgb
    class FakeScreen:
        monitors = [{"left": 0, "top": 0, "width": 800, "height": 600}]
        def __init__(self): self.px = canvas(800, 600, grey)
        def grab(self, r):
            assert r["left"] >= 0 and r["top"] >= 0 and r["left"] + r["width"] <= 800 and r["top"] + r["height"] <= 600, r
            out = bytearray()
            for y in range(r["top"], r["top"] + r["height"]):
                i = (y * 800 + r["left"]) * 3
                out += self.px[i:i + r["width"] * 3]
            return Shot(bytes(out))
    fake, blue, map_bg = FakeScreen(), (40, 80, 230), (90, 110, 70)
    paint(fake.px, 800, 100, 580, 100 + 150, 584, red)       # HP 75% of a 200 px bar at x 100-299
    paint(fake.px, 800, 400, 580, 400 + 60, 584, blue)       # Mana 30%
    paint(fake.px, 800, 600, 10, 760, 90, map_bg)            # minimap at 600,10 - 759,89
    paint(fake.px, 800, 640, 50, 644, 54, yellow)            # your dot ~ 26% across, 52% down
    paint(fake.px, 800, 60, 300, 90, 340, green)             # a mob left of you (you're at x 30... clipped area)
    config = {"bars": {"hp": {"x1": 100, "x2": 299, "y": 581, "color": list(red)},
                       "mana": {"x1": 400, "x2": 599, "y": 581, "color": list(blue)}},
              "minimap": {"x1": 600, "y1": 10, "x2": 759, "y2": 89, "dot": list(yellow)},
              "mobs": {"x": 200, "y": 320, "colors": [list(green)]}}
    screen = Screen(fake, config)
    r = screen.read()
    assert r["hp"] == 75.0 and r["mana"] == 30.0 and r["state"] == "ok" and r["mobs"] == "L", r
    assert r["wx"] == round(r["x"] * 10) and r["wy"] == round(r["y"] * 10), r   # no slide yet: map position = dot
    # MapleStory's minimap shows the whole map: a slide is never counted (even one a changed
    # view would suggest), so a saved home means the same spot after any restart.
    fresh = lambda **more: Screen(fake, json.loads(json.dumps(dict(config, **more))))
    assert screen.slides and not fresh(game="maplestory").slides
    assert fresh(game="maplestory", sliding_minimap=True).slides and not fresh(sliding_minimap=False).slides
    whole = fresh(sliding_minimap=False)
    whole.minimap.ox = 40
    r2 = whole.read()
    assert r2["wx"] == round(r2["x"] * 10) and r2["wy"] == round(r2["y"] * 10), r2
    assert abs(r["x"] - 26.4) < 2 and abs(r["y"] - 52.0) < 4, r
    paint(fake.px, 800, 100, 580, 250, 584, grey)            # HP gone: dead once it has stayed 2 s
    clock = [100.0]
    screen.clock = lambda: clock[0]
    assert screen.read()["state"] == "ok"
    clock[0] += 2
    assert screen.read()["state"] == "dead"
    screen.clock = time.monotonic
    paint(fake.px, 800, 100, 580, 250, 584, red)
    paint(fake.px, 800, 600, 10, 760, 90, (220, 220, 230))   # another map: no stop, the new view is followed
    paint(fake.px, 800, 680, 50, 684, 54, yellow)
    assert [screen.read()["state"] for _ in range(3)] == ["ok"] * 3
    # MapleStory's test popup on screen: "test" from the second reading, then
    # "ok" once it's answered. A setup for another game doesn't look for it.
    popup(fake.px, 800, 520, 380)
    ms = Screen(fake, {"game": "maplestory"})
    tick = [0.0]
    ms.clock = lambda: tick[0]
    assert [ms.read()["state"] for _ in range(2)] == ["ok", "test"] and ms.popup, ms.popup
    assert screen.read()["state"] == "ok" and screen.popup is None
    assert Screen(fake, {"game": "maplestory", "test_popup": False}).test_popup() is None
    screen.map_name, screen.config["watch"] = (lambda: "Ellinia"), {"death": {"x": 10, "y": 10, "patch": [0] * 75}}
    named = screen.read()
    assert named["map"] == "Ellinia", named   # with a --mark spot set: still the map's own name, not the mark's
    del screen.map_name, screen.config["watch"]
    paint(fake.px, 800, 520, 380, 782, 568, grey)
    assert ms.read()["state"] == "test"                     # looked for once a second: still up till then
    tick[0] += TEST_EVERY_S
    assert ms.read()["state"] == "ok" and ms.popup is None
    # Alert sounds: the test popup as it shows and every 5 s while it stays; a death once.
    alarm = Alarm()
    heard = [alarm.update(state, t) for t, state in ((0, "ok"), (1, "test"), (2, "test"), (5.9, "test"), (6, "test"),
                                                     (7, "ok"), (8, "dead"), (20, "dead"), (21, "offline"), (22, "ok"))]
    assert heard == [None, "test", None, None, None, None, "dead", None, "offline", None], heard
    assert Alarm().update("test", 0) == "test" and [Alarm(10).update("test", t) for t in (0,)] == ["test"]
    a10 = Alarm(); a10.update("test", 0); assert a10.update("test", 9.9) is None and a10.update("test", 10) == "test"
    import io, tempfile, wave
    with wave.open(io.BytesIO(chime_wav(CHIMES["test"])), "rb") as w:   # the chime: short, soft, not clipped
        frames = w.readframes(w.getnframes())
        assert w.getframerate() == 22050 and 0.5 < w.getnframes() / 22050 < 1.0, w.getnframes()
        loudest = max(abs(int.from_bytes(frames[i:i + 2], "little", signed=True)) for i in range(0, len(frames), 2))
        assert 0.3 * 32767 < loudest <= CHIME_VOLUME * 32767 + 1, loudest
    with tempfile.TemporaryDirectory() as own:
        open(os.path.join(own, "kabuto-test.wav"), "wb").close()
        assert alert_sound("test", own) == os.path.join(own, "kabuto-test.wav")   # yours wins
        made = alert_sound("dead", own)
        assert made.endswith("kabuto-chime-dead.wav") and os.path.getsize(made) > 1000
    assert "!! TEST POPUP: answer it" in describe({"state": "test"}) and ("TEST POPUP: answer it", RED) in layer_status({"state": "test"}, "USB")
    assert "map" not in r and "ml" not in r   # no map library, an older mob setup: sides only

    # A taught map: its name picks its mobs, which are counted out of reach
    # too; an untaught map falls back to the setup's mobs.
    fake = FakeScreen()
    for x, y, x1, y1 in henesys:
        paint(fake.px, 800, 600 + x, 92 + y, 600 + x1, 92 + y1, white)
    stamp(fake.px, 800, 450, 310); stamp(fake.px, 800, 500, 310)   # mobs 54 and 104 px right of you
    config = {"map_name": {"x1": 600, "y1": 92, "x2": 659, "y2": 105},
              "maps": {"Henesys Field": {"rows": ["%x" % v for v in a], "name_reading": NAME_READING, "colors": [[200, 40, 160]], "step_x": 2, "step_y": 2,
                                         "cell": 10, "min_hits": 3, "names": ["blob"], "mob_w": 20}},
              "mobs": {"x": 400, "y": 320, "top": 300, "bottom": 340, "reach": 100, "gap": 20, "colors": [list(green)]}}
    screen = Screen(fake, config)
    r = screen.read()
    assert r["map"] == "Henesys_Field" and r["mobs"] == "R" and (r["ml"], r["mr"], r["dr"], r["mn"]) == (0, 2, 54, "blob"), r
    assert "dl" not in r and "seen L0 (-) R2 (54%) blob" in describe(r), describe(r)
    paint(fake.px, 800, 600, 92, 660, 106, dark)
    for x, y, x1, y1 in ellinia:
        paint(fake.px, 800, 600 + x, 92 + y, 600 + x1, 92 + y1, white)
    r = screen.read()
    assert untaught(r["map"]) and r["mobs"] == "" and "ml" not in r and "not taught" in describe(r), r   # the setup's (green) mobs: none here
    # A map it wasn't taught still gets a name of its own (from its name's pixels), so the pad can
    # tell it from the next one: a Set home made on one map must never show up on another.
    reader = MapReader({})
    name_a = [0b0111001110011100111, 0b0100101001010010100, 0b0111001110011100111, 0b0100101001010010100, 0b0100101001010010111]
    name_b = [0b1110000111000011100, 0b1010000101000010100, 0b1110011101110011100, 0b0010010100010010000, 0b1110011101110011100]
    mark_a, mark_b = reader.unnamed_mark(name_a, 60), reader.unnamed_mark(name_b, 60)
    assert mark_a.startswith(UNNAMED) and mark_b.startswith(UNNAMED) and mark_a != mark_b, (mark_a, mark_b)
    assert reader.unnamed_mark(name_a, 60) == mark_a and MapReader({}).unnamed_mark(name_a, 60) == mark_a   # the same after a restart
    assert reader.unnamed_mark([row << 1 for row in name_a], 60) == mark_a          # seen a pixel off: still that map
    assert reader.unnamed_mark([0, 0, 1, 0, 0], 60) == "" and reader.unnamed_mark([(1 << 60) - 1] * 5, 60) == ""   # no writing there
    assert untaught("-") and untaught(mark_a) and not untaught("Henesys") and safe_name(mark_a) == mark_a and len(mark_a) <= 23
    # A map with its own minimap size: read from the setup's top-left corner,
    # 100 x 50 here, so the same dot is further across; the outline follows.
    paint(fake.px, 800, 600, 92, 660, 106, dark)
    for x, y, x1, y1 in henesys:
        paint(fake.px, 800, 600 + x, 92 + y, 600 + x1, 92 + y1, white)
    paint(fake.px, 800, 600, 10, 760, 90, (220, 220, 230)); paint(fake.px, 800, 640, 50, 644, 54, yellow)
    config["minimap"] = {"x1": 600, "y1": 10, "x2": 759, "y2": 89, "dot": list(yellow)}
    screen = Screen(fake, config)
    whole = screen.read()["x"]
    screen.sizes = {"Henesys Field": {"width": 100, "height": 50}}
    r = screen.read()
    assert screen.box["x2"] == 699 and screen.box["y2"] == 59 and r["x"] > whole + 10, (whole, r["x"], screen.box)
    assert [shape[:4] for shape in layer_shapes(config, FakeScreen.monitors[0], [], r, screen.box) if shape[5] == "minimap"] == [(598, 8, 701, 61)]
    # Marked by hand (F12): exactly the map picture marked, no header, wherever it is.
    screen.sizes = {"Henesys Field": {"width": 60, "height": 40, "left": 30, "top": 30}}
    r = screen.read()
    assert (screen.box["x1"], screen.box["y1"], screen.box["x2"], screen.box["y2"], screen.box["header"]) == (630, 40, 689, 79, 0), screen.box
    assert abs(r["x"] - 20.3) < 3 and abs(r["y"] - 30.8) < 5, r
    assert marked_box({"x1": 600, "y1": 10}, (689, 79), (630, 40)) == {"width": 60, "height": 40, "left": 30, "top": 30}
    # The slide (map position, and home with it) isn't thrown away when the found minimap wobbles a pixel or two.
    box = {"x1": 0, "y1": 0, "x2": 199, "y2": 99}
    assert same_minimap(box, dict(box, x2=201)) and not same_minimap(box, dict(box, x2=230)) and not same_minimap(None, box)
    assert marked_box({"x1": 0, "y1": 0}, (5, 5), (9, 60)) is None   # too thin to be a minimap
    assert map_box({"x1": 0, "y1": 0, "header": 72}, {"width": 100, "height": 50}) == {"x1": 0, "y1": 0, "x2": 99, "y2": 49, "header": 72}
    assert marked_name_area((160, 213), (100, 200)) == {"x1": 100, "y1": 200, "x2": 160, "y2": 213, "light": 170}
    assert marked_name_area((100, 200), (104, 213)) is None
    # A map whose name is shown somewhere else (F12): read there when the usual place has no name it knows.
    paint(fake.px, 800, 600, 92, 660, 106, dark)
    for x, y, x1, y1 in ellinia:
        paint(fake.px, 800, 100 + x, 200 + y, 100 + x1, 200 + y1, white)
    config["maps"]["Ellinia"] = {"rows": ["%x" % v for v in text_rows(name_area(ellinia), 60, 14)], "name_reading": NAME_READING,
                                 "name_area": {"x1": 100, "y1": 200, "x2": 159, "y2": 213, "light": 170}}
    screen = Screen(fake, config)
    assert screen.read()["map"] == "Ellinia" and list(screen.maps.maps) == ["Henesys Field"]
    for x, y, x1, y1 in henesys:
        paint(fake.px, 800, 600 + x, 92 + y, 600 + x1, 92 + y1, white)
    assert screen.read()["map"] == "Henesys_Field"   # the usual place first
    del config["maps"]["Ellinia"]
    assert form_fields({"hp": 1.0, "mobs": "R", "ml": 0, "mr": 2, "dr": 54, "mn": "blob", "map": "Henesys", "state": "ok"}) == \
        {"hp": 1.0, "mobs": "R", "ml": 0, "mr": 2, "dr": 54, "mn": "blob", "map": "Henesys", "state": "ok"}

    # Maps and their mobs from mobs/map.json: PNGs kept once in mobs, listed
    # under each map they're on; missing files and bad JSON are said plainly.
    import tempfile
    with tempfile.TemporaryDirectory() as lib:
        for name in ("snail.png", "slime.png", "blue_snail.png"):
            open(os.path.join(lib, name), "wb").close()
        def write(text):
            with open(os.path.join(lib, MAP_LIST), "w", encoding="utf-8") as f:
                f.write(text)
        write('{"Henesys Hunting Ground": ["snail.png", "blue_snail.png"], "Ellinia": ["slime.png", "snail.png", "gone.png"]}')
        maps, problems = read_map_list(lib)   # the 1.17.1 form still reads
        assert maps == {"Henesys Hunting Ground": {"mobs": ["snail.png", "blue_snail.png"], "minimap": None},
                        "Ellinia": {"mobs": ["slime.png", "snail.png", "gone.png"], "minimap": None}}, maps
        assert problems == ["map.json: Ellinia lists gone.png, not in %s" % lib], problems
        assert map_names(lib) == ["Ellinia", "Henesys Hunting Ground"]
        # Taught with what's there; a changed list asks to teach again (a missing file alone doesn't).
        assert not map_changed(lib, maps, "Ellinia", {"sprites": ["slime.png", "snail.png"]})
        assert map_changed(lib, maps, "Henesys Hunting Ground", {"sprites": ["snail.png"]})
        assert not map_changed(lib, maps, "Lith Harbor", {"sprites": ["snail.png"]}) and not map_changed(lib, maps, "Ellinia", None)
        listed = MapList(lib)
        assert sorted(listed.get()) == ["Ellinia", "Henesys Hunting Ground"]
        write('{"Ellinia": "slime.png", "Perion": ["boar.png", 3]}')
        os.utime(os.path.join(lib, MAP_LIST), (1, 1))   # a different modification time: read again
        assert listed.get() == {}
        assert read_map_list(lib)[1] == ['map.json: Ellinia\'s "mobs" should be a list of PNG file names',
                                         'map.json: Perion\'s "mobs" should be a list of PNG file names']
        write('{"Ellinia": ["slime.png",]}')
        assert read_map_list(lib)[0] == {} and "isn't valid JSON" in read_map_list(lib)[1][0]
        write('"slime.png"')
        assert "should be a list of maps" in read_map_list(lib)[1][0]
        # The current form: an object per map, with its minimap size; other keys (1.18.6's "home") are kept for later.
        write('[{"name": "Rocky Road II", "mobs": ["snail.png"], "minimap": {"width": 178, "height": 96}, "home": 42.5},'
              ' {"name": "Ellinia", "mobs": ["slime.png"], "minimap": {"width": 4}}, {"mobs": ["slime.png"]},'
              ' {"name": "Ellinia", "mobs": []}, "stray"]')
        maps, problems = read_map_list(lib)
        assert maps == {"Rocky Road II": {"mobs": ["snail.png"], "minimap": {"width": 178, "height": 96}},
                        "Ellinia": {"mobs": ["slime.png"], "minimap": None}}, maps
        assert problems == ['map.json: Ellinia\'s "minimap" should be {"width": px, "height": px}; the setup\'s is used',
                            'map.json: map 3 needs a "name"', "map.json: Ellinia is listed twice; the first counts",
                            'map.json: map 5 needs a "name"'], problems
        assert map_sizes(maps) == {"Rocky Road II": {"width": 178, "height": 96}}
        # F9 writes a size in, turning a 1.17.1 file into the current form and keeping the rest.
        write('{"Henesys": ["snail.png", "blue_snail.png"], "Ellinia": {"mobs": ["slime.png"], "home": 0.3}}')
        assert save_map_size(lib, "Ellinia", 180, 90) and not save_map_size(lib, "Perion", 180, 90)
        with open(os.path.join(lib, MAP_LIST), encoding="utf-8") as f:
            text = f.read()
        assert text == ('[\n  {\n    "name": "Henesys",\n    "mobs": ["snail.png", "blue_snail.png"]\n  },\n'
                        '  {\n    "name": "Ellinia",\n    "mobs": ["slime.png"],\n    "home": 0.3,\n'
                        '    "minimap": {"width": 180, "height": 90}\n  }\n]\n'), text
        assert read_map_list(lib)[0]["Ellinia"]["minimap"] == {"width": 180, "height": 90}
        # F12 writes a hand-marked box: "left"/"top" from the setup's corner, kept when read.
        assert save_map_value(lib, "Ellinia", "minimap", {"width": 60, "height": 40, "left": 30, "top": -5})
        assert read_map_list(lib) == ({"Henesys": {"mobs": ["snail.png", "blue_snail.png"], "minimap": None},
                                       "Ellinia": {"mobs": ["slime.png"], "minimap": {"width": 60, "height": 40, "left": 30, "top": -5}}}, [])
        assert save_map_value(lib, "Ellinia", "minimap", {"width": 60, "height": 40, "left": "x"})
        assert read_map_list(lib)[0]["Ellinia"]["minimap"] is None and "should be" in read_map_list(lib)[1][0]
        assert save_map_area(None, {}, lib, "Ellinia", {"width": 60, "height": 40, "left": 0, "top": 0}, None) is None
        assert read_map_list(lib)[0]["Ellinia"]["minimap"] == {"width": 60, "height": 40, "left": 0, "top": 0}
        assert "isn't in" in save_map_area(None, {}, lib, "Perion", {"width": 60, "height": 40, "left": 0, "top": 0}, None)
        assert save_map_area(None, {}, lib, "Perion", None, None) is None   # nothing marked: nothing to do
        assert minimap_size({"x1": 20, "y1": 60}, (199, 155)) == (180, 96) and minimap_size({"x1": 20, "y1": 60}, (10, 155)) is None
        # No map.json: older folders per map still work, each meaning the whole folder.
        os.remove(os.path.join(lib, MAP_LIST)); os.mkdir(os.path.join(lib, "Perion"))
        assert read_map_list(lib) == ({"Perion": {"mobs": None, "minimap": None}}, []) and map_names(os.path.join(lib, "nowhere")) == []
        assert not save_map_size(lib, "Perion", 180, 90)   # no map.json to write to
        assert load_sprites(lib, []) == {} and load_sprites(lib, ["gone.png"]) == {}   # nothing listed there: no Pillow needed
    try:
        from PIL import Image
    except ImportError:
        Image = None
    if Image:   # one PNG shared by two maps loads for each
        with tempfile.TemporaryDirectory() as lib:
            Image.new("RGBA", (4, 4), (200, 40, 160, 255)).save(os.path.join(lib, "snail.png"))
            Image.new("RGBA", (4, 4), (60, 200, 60, 255)).save(os.path.join(lib, "slime.png"))
            with open(os.path.join(lib, MAP_LIST), "w") as f:
                json.dump({"Henesys": ["snail.png"], "Ellinia": ["slime.png", "snail.png"]}, f)
            assert list(map_sprites(lib, "Henesys")) == ["snail.png"] and sorted(map_sprites(lib, "Ellinia")) == ["slime.png", "snail.png"]
            assert map_sprites(lib, "Perion") == {}

    # Shape search: animation frames sit next to their PNG; FFT sizes are quick ones.
    with tempfile.TemporaryDirectory() as lib:
        for name in ("snail.png", "snail.move0.png", "snail.hit10.png", "snail_big.png", "snailx.png", "slime.png"):
            open(os.path.join(lib, name), "wb").close()
        assert frame_files(lib, ["snail.png", "slime.png", "gone.png"]) == {"snail": ["snail.hit10.png", "snail.move0.png", "snail.png"],
                                                                         "slime": ["slime.png"]}
    assert [fast_len(n) for n in (1, 7, 97, 243, 1601)] == [1, 8, 100, 243, 1620]
    np_ = numpy_or_none()
    if np_:   # a mob's most different frames: its own PNG, then the least alike each time
        def pose(w, h, cut):
            img = np_.zeros((h, w, 4), np_.uint8); img[:, :, 3] = 255; img[:cut, :, 3] = 0; return img
        poses = [pose(10, 10, 0), pose(10, 10, 1), pose(10, 10, 5), pose(12, 10, 0), pose(10, 10, 2)]
        picked = pick_frames(np_, poses, 3)
        assert picked[0] is poses[0] and any(p is poses[3] for p in picked) and any(p is poses[2] for p in picked) and len(picked) == 3
        assert len(pick_frames(np_, poses, 0)) == 5 and len(pick_frames(np_, poses, 9)) == 5
    np = numpy_or_none()
    if np:   # the shape search and name tag themselves (numpy isn't needed to run this file)
        rgba = np.array(sprite, np.uint8).reshape(20, 20, 4)
        world = np.full((120, 400, 3), 40, np.uint8)
        world[110:] = (60, 200, 60)                                           # grass
        for x0, flip in ((60, False), (300, True)):                          # blobs standing on it, facing each way
            r = rgba[:, ::-1] if flip else rgba
            world[90:110, x0:x0 + 20][r[..., 3] > 0] = r[..., :3][r[..., 3] > 0]
        world[93:107, 180:200] = (200, 40, 160)                              # a pink slab: a mob's colour, no mob
        world[20:40, 130:150][rgba[..., 3] > 0] = rgba[..., :3][rgba[..., 3] > 0]   # a blob up on a ledge: not level with you
        search = ShapeSearch(np, {"blob": [rgba]}, sight=200, width=400)
        found = search.search(world, 200, 109)                                # you stand at x 200, feet at 109
        assert sorted((f[1], f[2], f[3]) for f in found) == [("blob", 60, 90), ("blob", 300, 90)], found
        assert all(f[0] > 0.9 for f in found) and len(search.frames) == 1   # the blob is symmetric: its mirror is the same frame
        assert search.search(world, 200, 72) == []                          # feet half way up: neither level is yours
        assert [(f[2], f[3]) for f in search.search(world, 200, 39)] == [(130, 20)]   # up on the ledge: that one is
        # 80 px more below your feet (REACH_BELOW): mid-jump, or the platform read a bit high,
        # mobs on the ground under you still count; much lower ones don't.
        low = ShapeSearch(np, {"blob": [rgba]}, sight=200, width=400, below=REACH_BELOW)
        assert sorted((f[2], f[3]) for f in low.search(world, 200, 72)) == [(60, 90), (300, 90)]   # 37 px above the grass (the ledge is above you)
        assert sorted((f[2], f[3]) for f in low.search(world, 200, 39)) == [(60, 90), (130, 20), (300, 90)]   # 70 px above it
        assert [(f[2], f[3]) for f in low.search(world, 200, -25)] == [(130, 20)]                           # 135 px above: too far
        bat = rgba[..., [2, 0, 1, 3]].copy()                                  # another colour: a flying mob
        world[55:75, 240:260][bat[..., 3] > 0] = bat[..., :3][bat[..., 3] > 0]   # 35 px above your feet
        frames = {"blob": [rgba], "bat": [bat]}
        assert sorted((f[1], f[2]) for f in ShapeSearch(np, frames, 200, 400, body=40, flyers={"bat"}).search(world, 200, 109)) == \
            [("bat", 240), ("blob", 60), ("blob", 300)]                       # flyers count at your height, walkers at your feet
        assert "bat" not in [f[1] for f in ShapeSearch(np, frames, 200, 400, body=40).search(world, 200, 109)]
        hit = world.copy()
        hit[103:110, 60:80] = (255, 230, 80)                                 # a hit flash over a third of one blob
        hit[90:110, 0:14][rgba[:, 6:, 3] > 0] = rgba[:, 6:, :3][rgba[:, 6:, 3] > 0]   # another one partly past the screen's left edge
        found = [(f[1], f[2]) for f in ShapeSearch(np, {"blob": [rgba]}, 200, 400).search(hit, 200, 109)]
        assert ("blob", 60) in found and ("blob", -6) in found, found
        hit[93:110, 60:80] = (255, 230, 80)                                  # all but its top: too little seen to say
        assert ("blob", 60) not in [(f[1], f[2]) for f in ShapeSearch(np, {"blob": [rgba]}, 200, 400).search(hit, 200, 109)]
        # Followed between whole searches: each found mob in a small window round where it was.
        walked = world.copy()
        walked[90:110, 60:80] = 40                                            # the left blob walks 25 px right...
        walked[90:110, 85:105][rgba[..., 3] > 0] = rgba[..., :3][rgba[..., 3] > 0]
        walked[90:110, 300:320] = 40                                          # ...and the right one is killed
        search.search(world, 200, 109)                                       # found at your level: the two blobs
        assert sorted((f[1], f[2], f[3]) for f in search.track(walked)) == [("blob", 85, 90)]
        assert [(f[2], f[3]) for f in search.track(walked)] == [(85, 90)] and search.last[0][6] == 0   # still followed, its frame kept
        walked[90:110, 85:105] = 40; walked[90:110, 200:220][rgba[..., 3] > 0] = rgba[..., :3][rgba[..., 3] > 0]
        assert search.track(walked) == [] and search.last == []              # moved further than it could: let go (the next search finds it)
        assert sorted(f[2] for f in search.search(walked, 200, 109)) == [200]
        edge = world.copy()                                                   # one partly off the screen's right edge
        edge[90:110, 300:320] = 40; edge[90:110, 390:400][rgba[:, :10, 3] > 0] = rgba[:, :10, :3][rgba[:, :10, 3] > 0]
        assert ("blob", 390) in [(f[1], f[2]) for f in search.search(edge, 200, 109)]
        assert ("blob", 390) in [(f[1], f[2]) for f in search.track(edge)]  # still followed (the video lost these)
        flash = world.copy(); flash[88:112, 55:85] = (255, 240, 200)          # a hit effect all over one: kept, being hit
        search.search(world, 200, 109)
        assert ("blob", 60) in [(f[1], f[2]) for f in search.track(flash)]
        everything = ShapeSearch(np, frames, 200, 400, view="screen", height=120).search(world, 200, 109)
        assert sorted((f[1], f[2]) for f in everything) == [("bat", 240), ("blob", 60), ("blob", 130), ("blob", 300)], everything
        tag = np.zeros((10, 30, 3), np.uint8); tag[:] = (60, 30, 90); tag[2:8, 1:7] = (220, 40, 30); tag[3:7, 10:28] = (230, 200, 160)
        finder, shot = TagFinder(np, tag), np.full((200, 300, 3), (90, 140, 60), np.uint8)
        shot[60:70, 40:70] = tag
        assert finder.find(shot)[:2] == (40, 60) and finder.last == (40, 60)
        shot[60:70, 40:70] = (90, 140, 60); shot[30:40, 200:230] = tag      # moved (the camera, or you)
        assert finder.find(shot)[:2] == (200, 30)
        shot[30:40, 200:230] = (90, 140, 60); shot[150:160, 100:130] = tag  # down in the HUD's strip: not looked at
        assert finder.find(shot) is None
        shot[150:160, 100:130] = (90, 140, 60)
        seen = tag.astype(np.float64); box = seen.mean(axis=2) < 100
        seen[box] = seen[box] * 0.6 + 255 * 0.4                            # bright sky through the see-through box
        shot[80:90, 120:150] = seen.astype(np.uint8); finder.last = None
        assert finder.find(shot)[:2] == (120, 80)                          # still found: its pattern, not its colours

    # Jumping, the field of view stays on your platform until you've stood still somewhere new for 5 s.
    g = Ground(settle=5)
    assert g.update((700, 546), 120.0, 0) == (700, 546)                       # first sight: where you are
    assert g.update((705, 546), 120.0, 0.5) == (705, 546)                     # walking: follows you sideways
    assert g.update((710, 496), 116.0, 1.0) == (710, 546)                     # jumping: your tag rises, the view doesn't
    assert g.update((715, 470), 113.5, 1.5) == (715, 546)
    assert g.update((720, 546), 120.0, 2.0) == (720, 546)                     # landed where you were
    assert g.update((730, 480), 114.0, 2.5)[1] == 546                         # up onto a ledge...
    assert g.update((730, 480), 114.0, 5.0)[1] == 546                         # ...still there 2.5 s on: not yet
    assert g.update((730, 546), 120.0, 6.0)[1] == 546                         # hopped back down: never moved
    for t in (6.5, 8.0, 10.0):                                                # up again, and staying...
        assert g.update((730, 480), 114.0, t)[1] == 546
    assert g.update((730, 480), 114.0, 11.5) == (730, 480)                    # ...settled 5 s: looked for from there
    assert g.update((730, 500), 114.0, 12.0) == (730, 500)                    # the camera moving: the dot's still, so the view follows your feet
    assert g.update(None, 114.0, 12.5) is None and g.update((730, 500), 114.0, 13.0) == (730, 500)   # tag lost a moment: held
    g = Ground(settle=5)                                                      # no minimap: your tag being still decides
    assert [g.update((700, f), None, t)[1] for t, f in ((0, 546), (1, 500), (2, 546), (3, 480), (6, 480), (8.5, 480))] == \
        [546, 546, 546, 546, 546, 480]
    g.reset()
    assert g.update((700, 300), 50.0, 20) == (700, 300)                       # another map: starts afresh
    # Mobs missed for a moment (hit effects, mist) are held where they were seen.
    memory, snail = MobMemory(0.6), (0.9, "snail", 100, 50, 40, 30)
    assert memory.update([snail], 0.0, "A") == [snail + (False,)]
    assert memory.update([], 0.4, "A") == [snail + (True,)] and memory.update([], 0.7, "A") == []   # held 0.6 s, then gone
    moved = (0.8, "snail", 112, 50, 40, 30)
    memory.update([snail], 1.0, "A")
    assert memory.update([moved], 1.2, "A") == [moved + (False,)]                 # seen again nearby: not counted twice
    assert memory.update([(0.7, "slime", 110, 50, 40, 30)], 1.3, "A")[1] == moved + (True,)   # another mob there doesn't replace it
    assert memory.update([], 1.4, "B") == []                                       # another map forgets it
    memory.update([snail], 2.0, "B")
    assert memory.recent(2.3, "B") == [snail] and memory.recent(2.3, "C") == []
    assert memory.update([], 2.3, "B", still=lambda k: False) == []               # nothing of it left where it was: gone at once
    memory.update([snail], 3.0, "B")
    assert memory.update([], 3.3, "B", still=lambda k: True) == [snail + (True,)]  # still partly there (under effects): held
    # XP per hour on the strip: after a minute; a level up starts it afresh for the new level.
    rate = XpRate()
    rate.add(20.0, 0); rate.add(25.0, 30)
    assert rate.per_hour() is None and xp_text(rate) == ""
    rate.add(30.0, 60)
    assert abs(rate.per_hour() - 600) < 1e-9 and xp_text(rate) == "+600.0%/h, level in 7m"   # 70% left at 600%/h
    rate.add(28.0, 70); assert rate.levels == 0 and abs(rate.gained - 10) < 1e-9 and rate.last == 30.0   # a small drop: not yet
    rate.add(4.0, 71); rate.add(0.0, 72); rate.add(31.0, 73)   # changing maps: misread as the screen fades, then right
    assert rate.levels == 0 and abs(rate.gained - 11) < 1e-9 and rate.last == 31.0
    for t in range(74, 104):
        rate.add(0.0, t)                                       # a 30 s load reading 0%: no death or level does that
    rate.add(32.0, 104); assert rate.levels == 0 and abs(rate.gained - 12) < 1e-9
    for t, xp in ((110, 40.0), (120, 50.0), (130, 60.0), (140, 70.0), (150, 80.0), (160, 90.0), (170, 98.0)):
        rate.add(xp, t)
    rate.add(2.0, 180); assert rate.levels == 0                # a level up must hold...
    rate.add(2.0, 190)
    assert rate.levels == 1 and rate.per_hour() is None and rate.last == 2.0 and rate.gained == 0   # ...then afresh
    rate.add(3.0, 250); assert abs(rate.per_hour() - 60) < 1e-9 and "level in" in xp_text(rate)
    rate.add(None, 260); rate.add(140.0, 260); assert rate.last == 3.0                       # unread or impossible: ignored
    quest = XpRate(); quest.add(30.0, 0); quest.add(98.0, 1); quest.add(30.5, 2)             # misread high: not gained
    assert abs(quest.gained - 0.5) < 1e-9
    quest.add(60.0, 3); quest.add(60.5, 13); assert abs(quest.gained - 30.5) < 1e-9 and quest.last == 60.5   # a quest: gained
    assert ("+60.0%/h, level in 1.6h", BAR_COLORS["xp"]) in layer_status({"xp": 3.0}, "USB", xp=xp_text(rate))
    assert "XP +60.0%/h" in describe({"xp": 3.0}, xp_text(rate))
    # Getting ready: packages and frames offered once; a no is remembered.
    with tempfile.TemporaryDirectory() as d:
        path, lib = os.path.join(d, "kabuto-bars.json"), os.path.join(d, "mobs")
        os.mkdir(lib)
        answers, installed, asked = [], [], []
        def fake_ask(q, default=True):
            asked.append(q); return answers.pop(0)
        def frames_offered(lib, path, fake_ask, asked, answers):
            with open(os.path.join(lib, MAP_LIST), "w") as f:
                json.dump([{"name": "A", "mobs": ["snail.png"]}], f)
            class FakeFrames:
                fetched = []
                def needing_frames(self, sprites): return ["snail.png"]
                def Api(self): return None
                def fetch(self, sprites, api, say=None, only=None): self.fetched.append(only); return 3, []
                def remember_not_found(self, sprites, missing): pass
            frames, asked[:] = FakeFrames(), []
            answers[:] = [True]
            get_ready(path, lib, ask=fake_ask, install=None, tool=lambda ask: frames)
            assert frames.fetched == [["snail.png"]] and "1 of your mobs" in asked[-1]
            answers[:] = [False]
            get_ready(path, lib, ask=fake_ask, install=None, tool=lambda ask: frames)
            assert "frames" in load_config(path)["not_now"]
            get_ready(path, lib, ask=fake_ask, install=None, tool=lambda ask: frames)
            assert len(asked) == 2
        global EXTRAS
        saved_extras, EXTRAS = EXTRAS, (("kabuto-no-such-package", "kabuto_no_such_module"),)
        try:
            answers[:] = [False]
            get_ready(path, lib, ask=fake_ask, install=lambda names: installed.extend(names) or True, tool=lambda ask: None)
            assert installed == [] and load_config(path)["not_now"] == ["packages"] and "kabuto-no-such-package" in asked[0]
            get_ready(path, lib, ask=fake_ask, install=lambda names: installed.extend(names) or True, tool=lambda ask: None)
            assert len(asked) == 1                                            # not asked again
            os.remove(path); answers[:] = [True]
            get_ready(path, lib, ask=fake_ask, install=lambda names: installed.extend(names) or True, tool=lambda ask: None)
            assert installed == ["kabuto-no-such-package"] and not os.path.exists(path)   # yes: installed, nothing to remember
            EXTRAS = ()
            if numpy_or_none():   # frames: fetched for the mobs without any, once
                frames_offered(lib, path, fake_ask, asked, answers)
        finally:
            EXTRAS = saved_extras
        # In the game: maps taught before names were read this way are listed; a wide name area isn't asked about.
        config = {"map_name": {"x1": 0, "y1": 0, "x2": 199, "y2": 12}, "maps": {"Old": {"rows": ["1"]}, "New": {"rows": ["1"], "name_reading": NAME_READING}}}
        import contextlib, io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            assert get_ready_in_game(None, config, path) is False
        assert "1 map(s) need teaching again" in out.getvalue() and ": Old" in out.getvalue(), out.getvalue()
    assert ask("anything?") is False or sys.stdin.isatty()                   # no terminal: no
    # Your feet from your name tag: just above its middle; the hitbox from the tag and your reach.
    assert tag_feet(745, 553, 80) == (785, 546)                               # the sample scenes' tag (medal and name)
    assert tag_box((824, 570), (745, 553)) == (745, 553, 824, 570) and tag_box((10, 10), (15, 12)) is None
    marked = {}
    set_hitbox(type("Sct", (), {"grab": lambda self, r: type("S", (), {"rgb": b"\0" * r["width"] * r["height"] * 3})()})(),
               marked, (745, 553), (824, 570), (1163, 520))
    assert (marked["x"], marked["bottom"], marked["top"], marked["reach"]) == (785, 546, 546 - CHARACTER_HEIGHT, 378), marked
    assert (marked["tag"]["x"], marked["tag"]["y"], marked["tag"]["w"]) == (-40, 7, 80)
    # MapleStory's bars where its status bar puts them: centred along the bottom.
    hud = hud_bars("maplestory", {"left": 0, "top": 0, "width": 1366, "height": 768})
    assert [(hud[n]["x1"], hud[n]["x2"], hud[n]["y"]) for n in ("hp", "mana", "xp")] == [(503, 605, 754), (611, 713, 754), (724, 836, 754)]
    assert hud["xp"]["color"] == [206, 243, 0] and hud_bars("other", {"left": 0, "top": 0, "width": 800, "height": 600}) is None
    assert minimap_corner("maplestory", {"left": 1920, "top": 0, "width": 1920, "height": 1080}) == (1920, 0)
    assert minimap_corner("other", {"left": 0, "top": 0, "width": 800, "height": 600}) is None
    wide = hud_bars("maplestory", {"left": 1920, "top": 0, "width": 1920, "height": 1080})   # a second monitor, full HD
    assert (wide["hp"]["x1"], wide["hp"]["y"]) == (1920 + 960 - 180, 1066)
    # MapleStory's fixed colours replace sampled ones; other games keep theirs.
    ms = apply_game({"game": "maplestory", "bars": {"hp": {"color": [1, 2, 3]}, "xp": {"color": [1, 2, 3]}}, "minimap": {"dot": [9, 9, 9]}})
    assert ms["bars"]["hp"]["color"] == [248, 10, 0] and ms["bars"]["xp"]["color"] == [206, 243, 0] and ms["minimap"]["dot"] == [255, 221, 68]
    assert apply_game({"game": "other", "bars": {"hp": {"color": [1, 2, 3]}}})["bars"]["hp"]["color"] == [1, 2, 3]
    # Hotkeys fire once per press, however long the key is held.
    edges = KeyEdges()
    assert edges.update({"f8"}) == ["f8"] and edges.update({"f8"}) == [] and edges.update(set()) == [] and edges.update({"f8", "esc"}) == ["f8", "esc"]
    # Mob outlines: each clump's box in the area, named, with its count.
    boxes = []
    mob_view(sight, 1000, 30, [[200, 40, 160]], gap=40, step=2, min_hits=3, cell=10, names=["blob"], mob_w=20, boxes=boxes)
    assert sorted(boxes) == [(104, 0, 118, 20, "blob", 1, None), (604, 0, 618, 20, "blob", 1, None), (804, 0, 838, 20, "blob", 2, None)], sorted(boxes)
    # The shape check: the blob PNG (either way round) lines up with each real
    # blob; a slab of the same pink, or pink scattered on grass, doesn't.
    shapes = sprite_shapes({"blob.png": (20, 20, sprite)}, color_table([[200, 40, 160]], 40))
    assert len(shapes) == 2 and shapes[0]["key"] == (3, 3, 16, 13) and shapes[1]["key"] == (3, 3, 16, 13), shapes[0]["key"]
    assert 50 <= len(shapes[0]["points"]) <= 300 and sprite_shapes({"grass.png": (2, 2, [(60, 200, 60, 255)] * 4)}, color_table([[200, 40, 160]], 40)) == []
    fake_mobs = bytearray(sight)
    paint(fake_mobs, 1000, 300, 6, 340, 18, (200, 40, 160))              # a pink slab: colour, no shape
    paint(fake_mobs, 1000, 450, 2, 500, 28, (60, 200, 60))                # grass...
    for x in range(450, 500, 3):
        paint(fake_mobs, 1000, x, 8, x + 1, 22, (200, 40, 160))           # ...with pink flowers
    common = dict(gap=40, step=2, min_hits=3, cell=10, names=["blob"], mob_w=20)
    assert sum(map(len, mob_view(fake_mobs, 1000, 30, [[200, 40, 160]], **common).values())) == 7   # colour alone counts them all (the slab as two)
    boxes = []
    checked = mob_view(fake_mobs, 1000, 30, [[200, 40, 160]], boxes=boxes, shapes=shapes, **common)
    assert [d for d, _ in checked["R"]] == [103, 303, 323] and [d for d, _ in checked["L"]] == [384], checked   # the real blobs stay
    turned_down, kept = [b for b in boxes if b[5] == 0], [b for b in boxes if b[5]]
    assert len(turned_down) == 2 and all(b[6] < SHAPE_MIN for b in turned_down) and {b[0] for b in turned_down} == {300, 450}, boxes
    assert sorted(b[:4] for b in kept) == [(100, 5, 120, 25), (600, 5, 620, 25), (800, 5, 820, 25), (820, 5, 840, 25)], kept   # where each PNG lines up
    assert all(b[6] > 0.9 for b in kept), kept
    flipped = canvas(200, 30, grey)
    for y in range(20):
        for x in range(20):
            if sprite[y * 20 + x][3]:
                flipped[((5 + y) * 200 + 160 + 19 - x) * 3:((5 + y) * 200 + 160 + 20 - x) * 3] = bytes(sprite[y * 20 + x][:3])
    pink = [(x, y) for y in range(8, 19, 2) for x in range(163, 177, 2)]
    found, best = find_shapes(flipped, 200, 30, shapes, pink, 60, 2)   # facing the other way
    assert len(found) == 1 and found[0][2:4] == (160, 5) and best > 0.9, found
    assert find_shapes(canvas(200, 30, grey), 200, 30, shapes, pink, 60, 2) == ([], 0.0)
    assert shape_score(flipped, 200, 30, shapes[0]["points"], 195, 5, 3600) == 0.0   # mostly off screen: no verdict
    # Looser / stricter: the map's own tolerance moves in steps, within limits.
    tuned = {"mobs": {"tolerance": 40, "colors": [[1, 2, 3]]}, "maps": {"Henesys": {"colors": [[200, 40, 160]]}}}
    assert mob_tolerance(tuned, "Henesys") == 40 and tune_tolerance(tuned, "Henesys", 1) == ("Henesys", 45)
    assert mob_tolerance(tuned, "Henesys") == 45 and tuned["mobs"]["tolerance"] == 40   # just that map
    for _ in range(30):
        tune_tolerance(tuned, "Henesys", -1)
    assert mob_tolerance(tuned, "Henesys") == TOL_MIN and tune_tolerance(tuned, "", 1) == ("every map", 45)
    assert tune_tolerance({"mobs": {"x": 1}}, "", 1) is None and tune_tolerance({}, "Henesys", 1) is None
    # The F9 list: recently taught first, then A-Z; a search keeps maps with
    # every word (any order or case, 2 finds II), names starting with it first.
    names = ["Rocky Road II", "Rocky Road I", "Henesys Hunting Ground", "Ant Tunnel I", "Perion: Rocky Mountain", "ellinia"]
    taught = {"Henesys Hunting Ground": 100, "Ant Tunnel I": 300, "ellinia": 0}
    assert pick_list(names, "", taught, {"ellinia"}) == [("Ant Tunnel I", "recent"), ("Henesys Hunting Ground", "recent"),
        ("ellinia", "changed: teach again"), ("Perion: Rocky Mountain", ""), ("Rocky Road I", ""), ("Rocky Road II", "")]
    assert [n for n, _ in pick_list(names, "rocky")] == ["Rocky Road I", "Rocky Road II", "Perion: Rocky Mountain"]
    assert [n for n, _ in pick_list(names, "road 2")] == ["Rocky Road II"] and [n for n, _ in pick_list(names, "ROAD ii")] == ["Rocky Road II"]
    assert [n for n, _ in pick_list(names, "mountain perion")] == ["Perion: Rocky Mountain"]   # any order, punctuation ignored
    assert [n for n, _ in pick_list(names, "hun gro")] == ["Henesys Hunting Ground"] and pick_list(names, "zakum") == []
    assert search_words("Perion: Rocky-Mountain II") == ["perion", "rocky", "mountain", "ii"]

    # The game layer's strip and outlines.
    strip = layer_status({"hp": 72.4, "mana": 40.0, "xp": 63.2, "map": "Henesys_Field", "mobs": "R", "ml": 1, "mr": 3, "ir": 1, "dl": 192,
                          "dr": 52, "mn": "Blue_Snail", "state": "ok"}, "USB COM9", "maplestory", ["Henesys Field"])
    texts = [t for t, _ in strip]
    assert texts[:5] == ["Kabuto \u00b7 MS", "USB COM9", "HP 72%", "MP 40%", "XP 63%"] and "Henesys Field" in texts, texts
    assert ("in reach 1 (4)", RED) in strip and ("target Blue_Snail 52%", RED) in strip, strip   # in reach first, all seen in brackets
    assert ("in reach 0 (3)", INK) in layer_status({"mobs": "", "ml": 1, "mr": 2, "ir": 0}, "USB")
    assert ("in reach 2 (3)", RED) in layer_status({"mobs": "RL", "ml": 1, "mr": 2}, "USB")   # older pads' readings: the sides in reach
    assert "in reach 1 (4)" in describe({"mobs": "R", "ml": 1, "mr": 3, "ir": 1})
    strip = layer_status({"hp": 0.0, "state": "dead", "map": "-", "ml": 0, "mr": 0}, "can't reach Kabuto", None, ["A"])
    assert ("DEAD", RED) in strip and ("new map, mobs not seen: F9", RED) in strip and strip[1][1] == RED and not any(t.startswith("target") for t, _ in strip)
    assert ("map not taught", RED) in layer_status({"map": "-"}, "USB", None, [])
    # Home on the game layer: parsed from the pad's answer, placed on the minimap
    # (a map position follows your dot's slide), on the strip and as outlines.
    assert parse_home("home=415&hm=0&hr=60") == {"home": 415, "map": False, "range": 60}
    assert parse_home("") is None and parse_home(None) is None and parse_home("home=x") is None
    dot_home, map_home = {"home": 415, "map": False, "range": 60}, {"home": 1500, "map": True, "range": 0}
    assert home_place({"x": 50.0}, dot_home) == 41.5 and home_place({"x": 50.0, "wx": 1700}, map_home) == 30.0
    assert home_place({"x": 50.0}, map_home) is None and home_place({}, dot_home) is None and home_place({"x": 1.0}, None) is None
    assert ("you 50% \u00b7 home 42% \u25c0", AMBER) in layer_status({"x": 50.0}, "USB", home=dot_home)   # 8.5% off, range 6%
    assert ("you 44% \u00b7 home 42% \u25c0", INK) in layer_status({"x": 44.0}, "USB", home=dot_home)
    assert ("you 42% \u00b7 at home", INK) in layer_status({"x": 42.0}, "USB", home=dot_home)
    assert ("you 20% \u00b7 home 30% \u25b6", INK) in layer_status({"x": 20.0, "wx": 1400}, "USB", home=map_home)   # no range: never amber
    assert ("you 50%", INK) in layer_status({"x": 50.0}, "USB") and not any(t.startswith("you") for t, _ in layer_status({}, "USB"))
    box = {"x1": 0, "y1": 0, "x2": 200, "y2": 172, "header": 72}
    marks = {s[5]: s[:4] for s in layer_shapes({}, {}, [], {"x": 50.0, "y": 50.0}, box, home=dot_home)}
    assert marks["home"] == (82, 72, 84, 172) and marks["home range"] == (71, 169, 95, 172) and "you" in marks, marks
    marks = {s[5]: s[:4] for s in layer_shapes({}, {}, [], {"x": 5.0, "y": 50.0, "wx": 9000}, box, home=map_home)}
    assert marks["home"] == (-1, 72, 1, 172) and "home range" not in marks   # far off the left edge: at the edge
    assert set(ALWAYS_SHOWN) >= {"you", "home", "home range"}
    assert ("tolerance 45", DIM) in layer_status({"mobs": "R"}, "USB", tol=45) and not any(t.startswith("tolerance") for t, _ in layer_status({"mobs": "R"}, "USB"))
    # The layer's MapleStory look: colours mixed for its gradients; bars drawn as gauges.
    assert mix("#000000", "#ffffff", 0.5) == "#808080" and mix("#f6921e", "#f6921e", 0.3) == "#f6921e"
    assert GAUGE.match("HP 72%").groups() == ("HP", "72") and not GAUGE.match("+3.2%/h, level in 25.4h")
    assert [t for t, c in layer_status({"hp": 72.4, "mana": 40.0, "xp": 63.2}, "USB") if GAUGE.match(t)] == ["HP 72%", "MP 40%", "XP 63%"]
    # No mob readings on a taught map (or without maps): said in red, since smart can't stop for mobs then.
    assert ("not looking for mobs: F9 on this map", RED) in layer_status({"map": "Henesys", "mobs": None}, "USB", None, ["Henesys"])
    assert ("not looking for mobs", RED) in layer_status({"hp": 50.0}, "USB") and not any("not looking" in t for t, _ in layer_status({"mobs": ""}, "USB"))
    assert "mobs: not looking (map not taught: F9)" in describe({"map": "-", "state": "ok"}) and "not looking" not in describe({"mobs": "", "state": "ok"})
    shapes = layer_shapes({"mobs": {"x": 400, "y": 320, "top": 300, "bottom": 340, "reach": 100, "gap": 20, "cell": 10},
                           "minimap": {"x1": 600, "y1": 10, "x2": 760, "y2": 90}, "map_name": {"x1": 600, "y1": 92, "x2": 659, "y2": 105}},
                          {"left": 0, "top": 0, "width": 800, "height": 600},
                          [(450, 310, 470, 330, "Blue_Snail", 2), (100, 310, 120, 330, "Blue_Snail", 1, 0.83), (200, 310, 220, 330, "Blue_Snail", 0, 0.31)],
                          {"x": 50.0, "y": 50.0})
    labels = {label: (x0, y0, x1, y1) for x0, y0, x1, y1, _, label in shapes}
    assert labels["sight"] == (150, 260, 650, 460) and labels["reach"] == (300, 260, 500, 460) and labels["Blue Snail x2"] == (450, 310, 470, 330)   # 40 px above, 40 + 80 below
    assert labels["Blue Snail 83%"] == (100, 310, 120, 330) and labels["not a mob 31%"] == (200, 310, 220, 330)
    assert labels["minimap"] == (598, 8, 762, 92) and labels["you"] == (676, 46, 684, 54) and labels["map name"] == (598, 90, 661, 107), labels
    assert [c for *_, c, label in shapes if label == "you"] != ["#ffdd44"]   # never the dot's colour: the reader would see it

    # USB: finds the Espressif port that answers, sends one line per reading.
    class FakeSerial:
        def __init__(self, replies): self.replies, self.sent, self.closed, self.port = list(replies), [], False, "COM9"
        def write(self, data): self.sent.append(data)
        def readline(self): return self.replies.pop(0) if self.replies else b""
        @property
        def in_waiting(self): return len(b"".join(self.replies))
        def read(self, n): data = b"".join(self.replies); self.replies.clear(); return data
        def close(self): self.closed = True
    class Port:
        def __init__(self, device, vid): self.device, self.vid = device, vid
    silent, kabuto = FakeSerial([]), FakeSerial([b"[ok] ready\r\n", b"KABUTO 1.16.0\r\n"])
    opened = {"COM3": silent, "COM9": kabuto}
    pad = find_usb_pad([Port("COM1", 0x1234), Port("COM3", ESPRESSIF_VID), Port("COM9", ESPRESSIF_VID)],
                       opener=lambda d: opened[d])
    assert pad and pad.version == "1.16.0" and pad.where == "USB COM9" and silent.closed, pad
    kabuto.replies = [b"KABUTO ok\n"]
    pad.send({"hp": 0.0, "x": 41.5, "y": 70.0, "mobs": "L", "state": "dead"})
    assert kabuto.sent[-1] == b"KABUTO stats hp=0.0&x=41.5&y=70.0&mobs=L&state=dead\n", kabuto.sent
    # The pad's answer carries the playing pattern's home; a plain "ok" means none (any more).
    kabuto.replies = [b"[log] x\r\n", b"KABUTO ok home=415&hm=0&hr=60\r\n"]
    assert pad.send({"x": 41.5}) == {"home": 415, "map": False, "range": 60}
    assert pad.send({"x": 41.5}) == {"home": 415, "map": False, "range": 60}   # no answer yet: the last one stands
    kabuto.replies = [b"KABUTO ok\n"]
    assert pad.send({"x": 41.5}) is None
    kabuto.replies = [b"KABUTO ok home=1500&hm=1&hr=0\n", b"KABUTO keys\n"]
    assert pad.keys() == [] and pad.home == {"home": 1500, "map": True, "range": 0}   # heard while asking for keys
    pad.home = None
    # Firmware that puts the pad's buttons in each answer: taken from there, and the
    # separate polling rests while answers keep coming (less traffic on the pad).
    assert pad.answers.polling_needed()   # these answers had no "keys": older firmware, keep polling
    kabuto.replies = [b"KABUTO ok keys=mark,map&home=415&hm=0&hr=60\n"]
    assert pad.send({"x": 41.5}) == {"home": 415, "map": False, "range": 60}
    assert pad.answers.take_keys() == ["mark", "map"] and pad.answers.take_keys() == []
    assert not pad.answers.polling_needed() and pad.answers.polling_needed(time.monotonic() + 3)   # quiet longer than the heartbeat: poll again
    kabuto.replies = [b"KABUTO ok keys=\n"]
    assert pad.send({"x": 41.5}) is None and pad.answers.take_keys() == []
    kabuto.replies = [b"KABUTO ok keys=skip\n", b"KABUTO keys area\n"]
    assert pad.keys() == ["skip", "area"]   # one heard in an answer while polling isn't lost
    pad.answers = Answers()
    assert answer_keys(None) is None and answer_keys("") == [] and answer_keys(["hide", ""]) == ["hide"]
    assert reading_interval(None, pad) == USB_INTERVAL and reading_interval(0.3) == 0.3
    # Only readings that change something the pad fights with are sent, plus a heartbeat.
    base = {"hp": 80.0, "mana": 50.0, "xp": 10.0, "x": 40.0, "y": 60.0, "wx": 400, "wy": 600, "state": "ok", "mobs": "R",
            "ml": 0, "mr": 2, "dl": None, "dr": 150, "mn": "snail", "map": "Henesys"}
    assert worth_sending(None, base, 0, 0) and worth_sending(base, dict(base), 0, HEARTBEAT_S)
    assert not worth_sending(base, dict(base, xp=10.3, hp=80.4, x=40.4, dr=145), 0, 1.0)   # small drift: wait
    for change in ({"state": "dead"}, {"mobs": "RL"}, {"mr": 1}, {"mn": "pig"}, {"map": "-"}, {"x": 40.5}, {"wx": 405},
                   {"hp": 79.0}, {"mana": None}, {"dr": 99}, {"dr": 160}, {"dl": 120}):
        assert worth_sending(base, dict(base, **change), 0, 0.5), change
    assert worth_sending(dict(base, dr=101), dict(base, dr=100), 0, 0.5)   # coming into reach, however little
    # The pad's setup buttons over USB: log lines and stats replies are skipped.
    kabuto.replies = [b"KABUTO ok\n", b"[ok] tap\n", b"KABUTO keys mark,map\n"]
    assert pad.keys() == ["mark", "map"] and kabuto.sent[-1] == b"KABUTO keys\n"
    kabuto.replies = [b"KABUTO keys\n"]
    assert pad.keys() == []
    kabuto.replies = []
    assert pad.keys(wait=0.05) is None   # firmware from before the setup buttons (1.16.0 here) doesn't answer
    pad.version = "1.18.0"
    assert pad.keys(wait=0.05) == []     # newer firmware slow to answer: none this time, not "update"
    assert version_tuple("1.18.0") == (1, 18, 0) and version_tuple("v1.17") == (1, 17, 0) and version_tuple("dev") is None
    assert version_tuple("1.16.9") < PAD_KEYS_SINCE <= version_tuple("1.17.0") < version_tuple("1.18.2")
    assert find_usb_pad([Port("COM1", 0x1234)], opener=lambda d: 1 / 0) is None   # no Espressif port: not opened

    # Pad buttons stand in for the keys: a setup step takes two marks and the
    # pad's "mark" presses give them, at the pointer.
    class ButtonPad:
        where = "USB test"
        def __init__(self): self.batches = [[], ["mark"], ["outlines", "mark"]]
        def keys(self): return self.batches.pop(0) if self.batches else []
    class Link:
        def __init__(self): self.pad = ButtonPad()
        def get(self): return self.pad
        def drop(self, pad): pass
    global pointer
    real_pointer, pointer = pointer, lambda: (320, 240)
    _keyboard.append(None)   # no keyboard here: pad buttons only
    heard = []
    stop = listen(heard.append)
    watch_pad_keys(Link(), every=0.02)
    assert mark_points("Hover the thing, F8 (or press Mark on the pad)", 2) == [(320, 240), (320, 240)]
    stop()
    global ERROR_LOG
    saved_log, ERROR_LOG = ERROR_LOG, os.path.join(tempfile.mkdtemp(), "kabuto-error.txt")
    def broken(key): raise ValueError("a broken listener")
    stop_broken, heard_after = listen(broken), []
    stop_after = listen(heard_after.append)
    import contextlib, io
    with contextlib.redirect_stderr(io.StringIO()):
        press("f10")                                                          # the error is caught and logged...
    assert heard_after == ["f10"] and "a broken listener" in open(ERROR_LOG).read()   # ...and the next listener still hears it
    stop_broken(); stop_after()
    ERROR_LOG = saved_log
    threading.Timer(0.05, press, ("f9",)).start()                            # a one-time question: F9 means not now
    assert mark_points("Name tag... (Esc or F9: not now)", 2, ("esc", "f9")) == []
    if numpy_or_none():   # F9 during the one-time questions: the rest wait for next start, nothing remembered
        config = {"mobs": {"x": 400, "y": 300, "top": 260, "bottom": 340}, "map_name": {"x1": 0, "y1": 0, "x2": 50, "y2": 12}}
        threading.Timer(0.05, press, ("f9",)).start()
        rescue = threading.Timer(2.0, press, ("esc",)); rescue.start()      # a second question waiting would end here, and fail below
        with tempfile.TemporaryDirectory() as d:
            get_ready_in_game(None, config, os.path.join(d, "kabuto-bars.json"))
        rescue.cancel()
        assert "not_now" not in config and "tag" not in config["mobs"] and CANCELLED[0] == "f9", config
    assert layer_maps({"B": {}, "A": {}}, {"maps": {"A": {"rows": ["1"], "name_reading": NAME_READING, "taught_at": 5},
                                                    "B": {"rows": ["1"], "taught_at": 3}}}) == (["A", "B"], {"A": 5})
    pointer = real_pointer
    assert heard[:3] == ["f8", "f10", "f8"], heard
    print("selftest passed")

def main():
    ap = argparse.ArgumentParser(description="Send what your game screen shows to Kabuto.")
    ap.add_argument("--setup", action="store_true", help="mark the bars, minimap and mobs")
    ap.add_argument("--mobs", action="store_true", help="redo just the mob detector (e.g. after adding sprites)")
    ap.add_argument("--sprites", default="mobs", help="folder of mob sprite PNGs and map.json (default mobs)")
    ap.add_argument("--map", nargs="?", const="", metavar="MAP",
                    help="teach the map you're on, with its mobs from map.json; asks which without one")
    ap.add_argument("--mark", choices=["death", "login", "test"], help="capture a spot only that screen has")
    ap.add_argument("--tag", action="store_true", help="mark just your name tag (so you're followed on screen)")
    ap.add_argument("--interval", type=float, default=None,
                    help="seconds between readings (default 0.2; only changes are sent, plus one every 2 s)")
    ap.add_argument("--config", default=CONFIG, help="setup file (default %s)" % CONFIG)
    ap.add_argument("--dry-run", action="store_true", help="print readings without sending")
    ap.add_argument("--game", choices=sorted(GAMES) + ["other"],
                    help="the game's built-in colours (default maplestory for a new setup); other: sample them")
    ap.add_argument("--no-layer", action="store_true", help="no game layer over the game; the terminal only")
    ap.add_argument("--quiet", action="store_true", help="no sound when the game needs you (test popup, death, disconnect)")
    ap.add_argument("--selftest", action="store_true", help="run built-in tests and exit")
    a = ap.parse_args()
    global ERROR_LOG
    ERROR_LOG = os.path.join(os.path.dirname(os.path.abspath(a.config)), ERROR_LOG)   # next to the setup file
    if a.selftest:
        selftest()
    elif a.map is not None:
        learn_map(a.config, a.sprites, a.map)   # asks in the terminal; in the game, F9 does this
    else:
        # The pad's setup buttons work from the start, setup included.
        if not (a.setup or a.mobs or a.mark or a.tag):
            get_ready(a.config, a.sprites)   # what this version needs: asked in the terminal, before the game layer
        a.pads = None if a.dry_run else PadLink(a)
        if a.pads:
            watch_pad_keys(a.pads)
        if a.setup:   # then straight on to readings, so F9 can teach maps right away
            job = lambda: (setup(a.config, a.sprites, a.game or "maplestory"), run(a))
        elif a.mobs:
            job = lambda: relearn_mobs(a.config, a.sprites)
        elif a.mark:
            job = lambda: mark(a.config, a.mark)
        elif a.tag:
            job = lambda: retag(a.config)
        else:
            job = lambda: run(a)
        try:
            with_layer(job, not a.no_layer)
        except KeyboardInterrupt:
            print()

if __name__ == "__main__":
    main()
