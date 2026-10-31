#!/usr/bin/env python3
"""
screen_stats.py - read your game screen and send what matters to Kabuto.

Runs on the PC with the game. Twice a second it samples a few small
areas of the screen and sends a handful of numbers to the pad: HP, Mana and
XP (bar fill %), your position on the minimap, the mobs around you (which
sides are in your reach, how many you can see each side, how near the nearest
is, its name), the map you're on, and whether you're dead or disconnected.
Nothing else leaves your PC: no screenshots, no reading text. All the work
happens here, so the pad only stores a few numbers.

Easiest: plug the pad into the game PC with a USB data cable, then
    pip install mss pynput pyserial pillow numpy scipy
    python screen_stats.py
The first run walks you through setup; after that it finds the pad on the
cable and starts sending. No Wi-Fi or PIN over USB. To redo setup:
    python screen_stats.py --setup
    # Mark things by hovering and pressing F8 (Esc skips): each bar's left and
    # right end; the minimap's top-left and bottom-right corners (and your dot
    # with --game other); the map's name; your character's head, feet and
    # attack reach (the hitbox mobs are looked for in); your name tag (so
    # you're followed wherever the camera puts you; --tag to redo just that).
With numpy, mobs are found by shape: every animation frame of the map's mobs
(mob.png plus mob.*.png; fetch them with mob_frames.py) matched along the band
level with your feet. scipy makes it several times faster.
MapleStory's bar and dot colours are built in (--game maplestory, the
default), so bars can be empty during setup. --game other samples them.

The game layer: a strip across the top of the game shows what's read and
sent, the map and the mobs, and each setup step, so you needn't leave the
game. F6-F11 work while the game has focus:
    F8   mark (during setup)     F9   which map is this? (pick it from map.json)
    F10  outlines on the game    F11  hide or show the layer
    F6   looser mob colours      F7   stricter mob colours (this map, saved)
Or press them on the pad: the editor's "Setup layer" (Recordings) gives two
pad layers: Setup (Mark, Skip, Which map, Outlines) and Tune (Looser,
Stricter, Outlines, Hide).
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

Run: it finds the pad on the USB cable by itself. Without a cable it uses
Wi-Fi: the pad on your home Wi-Fi with "Stay connected" (PIN needed), or this
PC joined to the Kabuto-Setup hotspot (no PIN, --host 192.168.4.1):
    python screen_stats.py                       # USB, else kabuto.local
    python screen_stats.py --pin 123456          # http://kabuto.local
    python screen_stats.py --host 192.168.1.42 --pin 123456
    python screen_stats.py --dry-run             # just print readings
Set KABUTO_PIN instead of --pin to keep the PIN out of your shell history.
A minimap that slides as you walk is followed, so your map position keeps up.

Run the self-test (no screen or pad needed):
    python screen_stats.py --selftest
"""
import argparse, http.cookiejar, json, os, queue, random, sys, threading, time, urllib.error, urllib.parse, urllib.request

BARS = (("hp", "HP"), ("mana", "Mana"), ("xp", "XP"))
CONFIG = "kabuto-bars.json"   # in the current folder (gitignored)

# Games whose colours never change: setup takes them from here instead of
# sampling the screen (so it works with an empty bar), and you only mark the
# minimap's corners, not your dot. The game is kept in the setup file.
GAMES = {
    "maplestory": {"label": "MapleStory", "icon": "\U0001F341",
                   "bars": {"hp": [248, 10, 0], "mana": [0, 120, 248], "xp": [206, 243, 0]},
                   "dot": [255, 221, 68]},
}

def apply_game(config):
    """The game's fixed colours over whatever setup sampled (in place)."""
    game = GAMES.get(config.get("game"))
    if game:
        for name, color in game["bars"].items():
            if name in config.get("bars", {}):
                config["bars"][name]["color"] = list(color)
        if config.get("minimap"):
            config["minimap"]["dot"] = list(game["dot"])
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

def find_dot(raw, w, h, color, tolerance=40, step=2):
    """Your dot on the minimap: the centre of the pixels matching its colour,
    as (x, y) percent of the minimap, or None. Checks every `step`th pixel."""
    t2, sx, sy, n = tolerance ** 2, 0, 0, 0
    for y in range(0, h, step):
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

def find_slide(prev, cur, w, h, max_dx, max_dy):
    """(dx, dy, mismatch) between two minimap views. Sideways first from
    column brightness, then up and down over the columns both views share,
    then sideways again over the shared rows. Mismatch: see overlap_mismatch."""
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
    its edge; left out with none) and "mn" (the nearest mob's name)."""
    near = {side: mobs[0] for side, mobs in view.items() if mobs}
    out = {"mobs": "".join(side for side in sorted(near, key=lambda s: (near[s][0], s)) if near[side][0] <= reach),
           "ml": len(view["L"]), "mr": len(view["R"])}
    for side, (d, _) in near.items():
        out["d" + side.lower()] = int(round(d * 100.0 / max(reach, 1)))
    nearest = min(near.values(), key=lambda m: m[0]) if near else None
    out["mn"] = nearest[1] if nearest else None
    return out

# ---- which map you're on: its name, read as a picture -----------------------
# No OCR: the game draws a map's name the same way every time, so its light
# pixels are kept as a fingerprint when you teach that map (--map) and
# compared after. Small shifts are allowed; a mostly matching name wins.

def text_rows(raw, w, h, light=170):
    """The map name area's light pixels (the name's letters), one int per row.
    Light means at least `light` and clearly brighter than the area itself
    (its middle brightness + 40), so a light title bar behind the name, as
    MapleStory's minimap has, isn't taken for letters."""
    lum = [raw[i] * 3 + raw[i + 1] * 6 + raw[i + 2] for i in range(0, w * h * 3, 3)]
    cut = min(2450, max(light * 10, sorted(lum)[len(lum) // 2] + 400)) if lum else light * 10
    rows = []
    for y in range(h):
        bits = 0
        for x in range(w):
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

class MapReader:
    """Which taught map this is, from its name: the best match scoring at least
    `min_score`, else "" (a map you haven't taught). Only rematched when the
    name area changes."""
    def __init__(self, maps, light=170, min_score=0.8):
        self.maps = {name: [int(r, 16) for r in m["rows"]] for name, m in maps.items() if m.get("rows")}
        self.light, self.min_score, self.last, self.name = light, min_score, None, ""

    def read(self, raw, w, h):
        rows = text_rows(raw, w, h, self.light)
        if rows != self.last:
            self.last = rows
            score, name = max([(rows_score(rows, m), n) for n, m in sorted(self.maps.items())] or [(0, "")])
            self.name = name if score >= self.min_score else ""
        return self.name

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

class GameState:
    """ok / dead / offline from the readings, needing a couple of
    agreeing readings so one odd frame doesn't stop the pad."""
    def __init__(self):
        self.zero_hp = self.gone = 0

    def update(self, hp, mana, dot_seen, minimap_used, watches):
        if watches.get("login"):
            return "offline"
        if watches.get("death"):
            return "dead"
        no_bars = (hp in (None, 0)) and (mana in (None, 0))
        self.gone = self.gone + 1 if no_bars and minimap_used and not dot_seen else 0
        self.zero_hp = self.zero_hp + 1 if hp == 0 else 0
        if self.gone >= 2:
            return "offline"          # no bars and no minimap: login screen or disconnected
        if self.zero_hp >= 2:
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
FIRST_PASS = 0.45     # share of a frame's pixels matching its colours for a closer look
EFFECT_BRIGHT = 200   # a pixel this bright (any channel, 0-255) not matching the mob may be a hit effect over it
VISIBLE_MIN = 0.6     # ...but at least this much of the mob must be seen
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

def strict_score(np, nears, parts, x, y, h, w, floor=0.08, hidden=None, loose=None, edges=None):
    """Every part must be there: a geometric mean of how much of each part
    matches, weighted by its size (but no part below `floor`), so a small
    flickering one (flames, sparkles) can't veto a match and scenery sharing
    some colours can't pass. With `hidden` (off screen, or where the screen is
    near white, yellow or orange), a mob's pixel that doesn't match there is
    taken as covered by a hit effect or damage number, or past the screen's
    edge: not seen rather than wrong, as long as most of the mob (VISIBLE_MIN)
    is still seen. A mob partly covered so (COVERED or more) has blurred
    outlines too: with `loose` (nears grown a px) and each part's `edges`, a
    pixel on a part's edge may then find its colour a px away."""
    total = sum(m.sum() for _, m in parts)
    hits = [near[y:y + h, x:x + w] for near in nears]
    covers = [None] * len(parts)
    if hidden is not None:
        b = hidden[y:y + h, x:x + w]
        covers = [m * b * (1 - hit) for hit, (_, m) in zip(hits, parts)]
        covered = sum(c.sum() for c in covers) / total
        if covered > 1 - VISIBLE_MIN:
            covers = [None] * len(parts)   # too little of it seen to say
        elif covered >= COVERED and loose is not None:   # outlines blur around effects
            hits = [hit + (grow[y:y + h, x:x + w] - hit) * edge for hit, grow, edge in zip(hits, loose, edges)]
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

class ShapeSearch:
    """A map's mob frames (both facings, near-duplicates dropped), searched for
    in your field of view: the screen either side of you (as far as `sight`),
    at your level. Walking mobs count with their feet level with yours (give
    or take `slack`); flying ones (in `flyers`) when they're at your height
    (`body` px above your feet); with view "screen", anything on screen. A
    fixed band size keeps each frame's FFT computed once."""
    def __init__(self, np, frames, sight, width=None, slack=FEET_SLACK, body=0, flyers=(), view="level", height=None):
        """`frames`: {mob: [rgba array, ...]}; `width`, `height`: the screen's."""
        self.np, self.sight, self.slack, self.frames, self.cache = np, sight, slack, [], {}
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
        self.bh = height if self.view == "screen" else self.h + (body if self.flyers else 0) + 2 * slack
        self.bw = min(2 * sight, width or 2 * sight) + self.w
        self.fft = (fast_len(self.bh + self.h), fast_len(self.bw + self.w))

    def search(self, screen, x, feet, tolerance=50, need=SHAPE_MIN):
        """Mobs level with you: [(score, mob, left, top, width, height)], best
        first, one per mob. `screen` is an (H, W, 3) array; x and feet are where
        you stand on it."""
        np = self.np
        H, W = screen.shape[:2]
        top = 0 if self.view == "screen" else feet + self.slack - self.bh
        left = max(-self.w, min(x - self.bw // 2, W + self.w - self.bw))   # centred on you, kept on the screen
        band = np.zeros((self.bh, self.bw, 3), np.float32)   # off screen: matches nothing
        y0, y1, x0, x1 = max(0, top), min(H, top + self.bh), max(0, left), min(W, left + self.bw)
        if y1 > y0 and x1 > x0:
            band[y0 - top:y1 - top, x0 - left:x1 - left] = screen[y0:y1, x0:x1]
        t2, near, loose, spectra, found = float(tolerance) ** 2, {}, {}, {}, []
        hidden = np.ones((self.bh, self.bw), np.float32)   # off screen: not seen
        if y1 > y0 and x1 > x0:
            hidden[y0 - top:y1 - top, x0 - left:x1 - left] = (band[y0 - top:y1 - top, x0 - left:x1 - left].max(axis=2) >= EFFECT_BRIGHT) \
                if EFFECT_BRIGHT else 0
        pp = (band * band).sum(axis=2)   # |p|^2 once: |p - c|^2 = |p|^2 - 2 p.c + |c|^2 per colour is then one product
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
                    spectra[key] = self.rfft(near[key], self.fft)
                if (i, j) not in self.cache:
                    self.cache[(i, j)] = self.rfft(m[::-1, ::-1], self.fft)
                product = spectra[key] * self.cache[(i, j)]
                F = product if F is None else F + product
            first = self.irfft(F, self.fft)[h - 1:self.bh, w - 1:self.bw] / big_total
            if self.view != "screen":   # at your level: feet level with yours, or (flying) at your height
                lowest = self.bh - h - 2 * self.slack - (self.body if mob in self.flyers else 0)
                first[:max(0, lowest)] = 0
            ys, xs = np.nonzero(first >= FIRST_PASS)
            looked, grown_nears = [], None
            if len(ys) and MATCH_SLACK:   # the strict check: edge pixels may find their colour a px away
                grown_nears = []
                for rgb, _ in parts:
                    key = tuple(int(c) // 16 for c in rgb)
                    if key not in loose:
                        loose[key] = grown(np, near[key], MATCH_SLACK)
                    grown_nears.append(loose[key])
            values = first[ys, xs]
            order = np.argpartition(-values, 2000)[:2000] if len(values) > 2000 else np.arange(len(values))
            for k in order[np.argsort(-values[order])]:   # the 12 best distinct spots (a strong one's neighbours don't crowd out the rest)
                cy, cx = int(ys[k]), int(xs[k])
                if any(abs(cx - lx) < w // 2 and abs(cy - ly) < h // 2 for lx, ly in looked):
                    continue
                if len(looked) == 12:
                    break
                looked.append((cx, cy))
                score = strict_score(np, nears, parts, cx, cy, h, w, hidden=hidden, loose=grown_nears, edges=edges)
                if score >= need:
                    found.append((score, mob, left + cx, top + cy, w, h, i))
        found.sort(key=lambda f: -f[0])
        kept = []
        for f in found:   # one per mob: overlapping finds are the same one
            if all(abs((f[2] + f[4] / 2.0) - (k[2] + k[4] / 2.0)) > min(f[4], k[4]) * 0.6 for k in kept):
                kept.append(f)
        return [f[:6] for f in kept]

class TagFinder:
    """You, by your name tag (marked at setup): its leaf, letters and box
    matched part by part, near where you were last (the whole screen when
    lost), so a tag half under your pet's still wins. Returns the tag's
    top-left and how sure (0-1)."""
    def __init__(self, np, rgb, window=(260, 160)):
        rgba = np.concatenate([rgb, np.full(rgb.shape[:2] + (1,), 255, rgb.dtype)], axis=2)
        self.np, self.parts, self.window = np, colour_parts(np, rgba), window
        self.rfft, self.irfft = ffts(np)
        self.h, self.w = rgb.shape[:2]
        self.last = None

    def find(self, screen, need=0.3, skip_bottom=80):
        np = self.np
        H, W = screen.shape[:2]
        spots = []
        if self.last:
            lx, ly = self.last
            spots.append((max(0, lx - self.window[0]), max(0, ly - self.window[1]),
                          min(W, lx + self.w + self.window[0]), min(H - skip_bottom, ly + self.h + self.window[1])))
        spots.append((0, 0, W, H - skip_bottom))   # lost: the whole screen but the HUD
        for x0, y0, x1, y1 in spots:
            area = screen[y0:y1, x0:x1].astype(np.float32)
            if area.shape[0] < self.h or area.shape[1] < self.w:
                continue
            size = (fast_len(area.shape[0] + self.h), fast_len(area.shape[1] + self.w))
            nears, F, total = [], None, sum(m.sum() for _, m in self.parts)
            for rgb, m in self.parts:
                near = (((area - np.array(rgb, np.float32)) ** 2).sum(axis=2) <= 2500).astype(np.float32)
                nears.append(near)
                product = self.rfft(near, size) * self.rfft(m[::-1, ::-1], size)
                F = product if F is None else F + product
            first = self.irfft(F, size)[self.h - 1:area.shape[0], self.w - 1:area.shape[1]] / total
            best, looked = (0.0, 0, 0), []
            for k in np.argsort(-first, axis=None)[:400]:
                y, x = divmod(int(k), first.shape[1])
                if any(abs(x - lx) < self.w // 2 and abs(y - ly) < self.h // 2 for lx, ly in looked):
                    continue
                looked.append((x, y))
                if len(looked) > 25:
                    break
                score = strict_score(np, nears, self.parts, x, y, self.h, self.w, floor=0.15)
                if score > best[0]:
                    best = (score, x + x0, y + y0)
            if best[0] >= need:
                self.last = (best[1], best[2])
                return best[1], best[2], best[0]
        return None

HOLD_SECONDS = 0.6    # a mob missed this soon after it was seen still counts (one missed reading)

class MobMemory:
    """Mobs seen a moment ago still count when a reading misses them: hit
    effects, skills and mist cover a mob for a frame or two mid-fight, and
    attacking shouldn't stop and start. A mob is held where it was last seen
    for `hold` seconds; a find of the same mob near there replaces it. A new
    map forgets everything."""
    def __init__(self, hold=HOLD_SECONDS):
        self.hold, self.seen, self.place = hold, [], None

    def update(self, found, now, place=None):
        """`found`: this reading's [(score, mob, left, top, width, height)].
        Returns them plus the held ones, each with a last field: True if held."""
        if place != self.place:
            self.seen, self.place = [], place
        def same(f, k):
            return f[1] == k[1] and abs((f[2] + f[4] / 2.0) - (k[2] + k[4] / 2.0)) <= max(f[4], k[4], 40)
        held = [k for t, k in self.seen if now - t <= self.hold and not any(same(f, k) for f in found)]
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

class Screen:
    """Everything read each tick, plus what's learned at start (the map)."""
    def __init__(self, sct, config, sprites_dir=None):
        mm = config.get("minimap") or {}
        self.sprites_dir, self.shapes = sprites_dir, {}
        self.sct, self.config, self.state = sct, config, GameState()
        self.minimap = MinimapTracker(threshold=mm.get("map_mismatch", 0.6))
        area = config.get("map_name")
        self.maps = MapReader(config.get("maps", {}), area.get("light", 170)) if area and config.get("maps") else None
        self.boxes = []   # the mobs last found, in screen coordinates (for the game layer)
        self.current = None   # the taught map you're on ("" untaught, None no map library)
        self.sizes = {}       # {map: its minimap size}, from map.json
        self.box = None       # the minimap box last read
        self.map_mobs = {}    # {map: its mob PNGs}, from map.json
        self.searches = {}    # {map: ShapeSearch}
        self.you = None       # (x, feet) where your name tag says you are, else None
        self.memory = MobMemory((config.get("mobs") or {}).get("hold", HOLD_SECONDS))
        self.clock = time.monotonic
        self.np, self.tag, self.pixels = numpy_or_none(), None, None
        tag = (config.get("mobs") or {}).get("tag")
        if self.np and tag:
            rgb = self.np.frombuffer(bytes.fromhex(tag["rgb"]), self.np.uint8).reshape(tag["h"], tag["w"], 3)
            self.tag = TagFinder(self.np, rgb)
        apply_game(config)

    def map_name(self):
        """The taught map you're on ("" for one you haven't taught), or None
        without a map library."""
        if not self.maps:
            return None
        a = self.config["map_name"]
        w, h = a["x2"] - a["x1"] + 1, a["y2"] - a["y1"] + 1
        return self.maps.read(grab(self.sct, a["x1"], a["y1"], w, h), w, h)

    def minimap_box(self, name):
        """The minimap's box on this map: the setup's, or this map's own size
        from map.json, from the same top-left corner (MapleStory's minimap
        stays there and grows or shrinks with the map)."""
        mm, size = self.config.get("minimap"), self.sizes.get(name) if name else None
        if not mm or not size:
            return mm
        return dict(mm, x2=mm["x1"] + size["width"] - 1, y2=mm["y1"] + size["height"] - 1)

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

    def screen(self):
        """The whole (primary) screen as an array, once per reading, for the
        name tag and the shape search; (array, left, top)."""
        if self.pixels is None:
            monitors = self.sct.monitors
            m = monitors[1] if len(monitors) > 1 else monitors[0]
            shot = grab(self.sct, m["left"], m["top"], m["width"], m["height"])
            self.pixels = (self.np.frombuffer(shot, self.np.uint8).reshape(m["height"], m["width"], 3), m["left"], m["top"])
        return self.pixels

    def find_you(self):
        """Where you stand: your name tag's place on screen if found, else
        where you stood at setup. Sets self.you (None when not tracked)."""
        mb = self.config.get("mobs") or {}
        self.you = None
        if self.tag:
            pixels, ox, oy = self.screen()
            found = self.tag.find(pixels)
            if found:
                self.you = (found[0] + ox - mb["tag"]["x"], found[1] + oy - mb["tag"]["y"])
        return self.you

    def shape_search(self, name):
        """The map's ShapeSearch: numpy, a taught map and its mob frames (from
        map.json); None otherwise."""
        if not self.np or not name or not self.sprites_dir or name not in self.map_mobs:
            return None
        if name not in self.searches:
            mb = self.config["mobs"]
            try:
                from PIL import Image
                frames = {}
                for mob, files in frame_files(self.sprites_dir, self.map_mobs[name] or []).items():
                    frames[mob] = [self.np.asarray(Image.open(os.path.join(self.sprites_dir, f)).convert("RGBA")) for f in files]
            except Exception:   # no Pillow, unreadable files
                frames = {}
            sight = int(mb.get("reach", 350) * mb.get("sight", SIGHT))
            monitors = self.sct.monitors
            m = monitors[1] if len(monitors) > 1 else monitors[0]
            files = frame_files(self.sprites_dir, self.map_mobs[name] or [])
            flyers = {mob for mob, names in files.items() if any(".fly" in n for n in names)}
            body = mb.get("bottom", mb["y"]) - mb.get("top", mb["y"])
            self.searches[name] = ShapeSearch(self.np, frames, sight, m["width"], body=body, flyers=flyers,
                                              view=mb.get("view", "level"), height=m["height"]) if frames else None
        return self.searches[name]

    def mobs(self, name):
        """Mob fields for the reading (see mob_fields): by shape with numpy and
        the map's frames; else with this map's colours when it's taught, or the
        ones from setup. {} without a mob detector."""
        self.boxes = []
        mb = self.config.get("mobs")
        if mb and "x" in mb and self.you:   # follow you: the box moves with your name tag
            height = mb.get("bottom", mb["y"]) - mb.get("top", mb["y"])
            mb = dict(mb, x=self.you[0], y=self.you[1] - height // 2, top=self.you[1] - height, bottom=self.you[1])
        search = self.shape_search(name) if mb else None
        if search:
            pixels, ox, oy = self.screen()
            x, feet = (self.you or (mb["x"], mb.get("bottom", mb["y"])))
            entry = self.config.get("maps", {}).get(name) or {}
            found = search.search(pixels, x - ox, feet - oy, mob_tolerance(self.config, name) + 10, entry.get("shape", SHAPE_MIN))
            found = [(score, mob, left + ox, top + oy, w, h) for score, mob, left, top, w, h in found]
            view = {"L": [], "R": []}
            for score, mob, left, top, w, h, held in self.memory.update(found, self.clock(), name):
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
        self.pixels = None   # a fresh screen this reading
        out = read_bars(self.sct, c.get("bars", {}))
        self.find_you()
        name = self.current = self.map_name()   # first: the map decides the minimap's size
        dot, world, mm = None, None, self.minimap_box(name)
        if mm:
            if mm != self.box:   # another size: the slide so far doesn't carry over
                self.box, self.minimap = mm, MinimapTracker(threshold=mm.get("map_mismatch", 0.6))
            w, h = mm["x2"] - mm["x1"] + 1, mm["y2"] - mm["y1"] + 1
            raw = grab(self.sct, mm["x1"], mm["y1"], w, h)
            dot = find_dot(raw, w, h, mm["dot"], mm.get("tolerance", 40))
            if dot:                      # a login or loading screen isn't the map
                self.minimap.update(raw, w, h)
                world = self.minimap.world(dot, w, h)
        found = self.mobs(name)
        mobs = found.pop("mobs", None)   # None: no mob detector, so the pad doesn't wait for mobs
        watches = {}
        for name, mark in c.get("watch", {}).items():
            watches[name] = patch_matches(grab(self.sct, mark["x"] - 2, mark["y"] - 2, 5, 5), bytes(mark["patch"]))
        out["state"] = self.state.update(out.get("hp"), out.get("mana"), dot is not None, bool(mm), watches)
        out["x"], out["y"] = dot if dot else (None, None)
        out["wx"], out["wy"] = world if world else (None, None)   # for stuck: moves even when the dot doesn't
        out["mobs"] = mobs
        out.update(found)                # ml/mr/dl/dr/mn: counts, distances, nearest mob's name
        if found.get("mn"):
            out["mn"] = safe_name(found["mn"])
        if name is not None:
            out["map"] = safe_name(name) if name else "-"   # "-": a map you haven't taught
        return out

# ---- setup --------------------------------------------------------------------

# ---- hotkeys that work while the game has focus -----------------------------
# A keyboard hook (pynput) only hears keys meant for programs at its own
# level: a game running as administrator, or its anti-cheat, keeps them from
# it, so F8 only worked with the terminal in front. On Windows the keys' state
# is read directly instead (GetAsyncKeyState), which needs no hook.

KEYS = {"f6": 0x75, "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "esc": 0x1B}   # Windows key codes

class KeyEdges:
    """Which keys went down since the last look, from the keys down now."""
    def __init__(self):
        self.down = set()

    def update(self, down_now):
        pressed = [k for k in KEYS if k in down_now and k not in self.down]
        self.down = set(down_now)
        return pressed

class Keys:
    """Calls on_key("f6" ... "f11" or "esc") on its own thread, wherever the
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
        fn(key)

# The pad's setup layer buttons ("tool" steps) and the keys they stand for.
PAD_KEYS = {"mark": "f8", "skip": "esc", "map": "f9", "outlines": "f10", "hide": "f11", "looser": "f6", "stricter": "f7"}

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

def mark_points(prompt, count):
    """Hover and press F8 to mark up to `count` points; Esc ends early (or skips)."""
    points, done = [], threading.Event()
    say(prompt, sticky=True)
    def on_key(name):
        if done.is_set():
            return
        if name == "esc":
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

def mob_area(mb, screen, sight=1.0):
    """The hitbox either side of your character, clipped to the screen: as
    tall as your character (head to feet, when marked; else `band` px above
    and below), `reach` px to each side (`sight` times that, to see mobs out of
    reach). Returns (left, top, width, height)."""
    reach = int(mb.get("reach", 350) * sight)
    top = mb["top"] if "top" in mb else mb["y"] - mb.get("band", 80)
    bottom = mb["bottom"] if "bottom" in mb else mb["y"] + mb.get("band", 80)
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
    hitbox: your character's head and feet, and how far your attack reaches."""
    listed = map_names(sprites_dir)
    # With maps listed, the PNGs in mobs are their shared library: each map
    # learns just its own (F9 / --map), so none are learned for every map here.
    sprites = {} if listed else load_sprites(sprites_dir)
    mobs = {"tolerance": 40}
    box = "Hitbox: hover YOUR character's HEAD, F8; its FEET, F8; then how far your attack reaches to one side, F8"
    if sprites or listed:
        if sprites:
            say("Found %d mob sprite(s) in %s." % (len(sprites), sprites_dir))
        pts = mark_points(box + " (Esc skips). Mobs nearby are fine.", 3)
        if len(pts) < 3:
            say("  skipped"); return
        mobs.update(hitbox(*pts), sight=SIGHT)
        say("  Hitbox: %d px tall, %d px to each side." % (mobs["bottom"] - mobs["top"], mobs["reach"]))
        mark_tag(sct, mobs)
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
        pts = mark_points(box + "; then up to 3 mobs (different kinds), F8 each; Esc when done", 6)
        if len(pts) < 4:
            say("  skipped"); return
        mobs.update(hitbox(*pts[:3]), colors=[pixel(sct, x, y) for x, y in pts[3:]])
    config["mobs"] = mobs

def mark_tag(sct, mobs):
    """Your name tag, so you're found wherever the camera puts you: its
    top-left and bottom-right corners, kept with where it sits from your feet."""
    pts = mark_points("Name tag: hover the TOP-LEFT corner of YOUR name tag (under your character), F8; "
                      "then its BOTTOM-RIGHT corner, F8 (Esc skips)", 2)
    if len(pts) < 2:
        say("  skipped: you're looked for where you stood at setup"); return
    (ax, ay), (bx, by) = pts
    x1, y1, x2, y2 = min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)
    if x2 - x1 < 10 or y2 - y1 < 6:
        say("  That's too small for a name tag: skipped"); return
    w, h = x2 - x1 + 1, y2 - y1 + 1
    mobs["tag"] = {"x": x1 - mobs["x"], "y": y1 - mobs["bottom"], "w": w, "h": h, "rgb": grab(sct, x1, y1, w, h).hex()}
    say("  Name tag kept (%d x %d px): you'll be followed wherever the camera puts you." % (w, h))

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

def mark_map_name(config):
    pts = mark_points("Map name: hover the TOP-LEFT of the map's name, F8; then its BOTTOM-RIGHT, a bit past where "
                      "the longest name would end, F8 (Esc skips)", 2)
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
    corner; F9 fills it in). Other keys are kept for later. The 1.17.1 form,
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
                                                                   for k in ("width", "height"))):
            problems.append('%s: %s\'s "minimap" should be {"width": px, "height": px}; the setup\'s is used' % (MAP_LIST, name))
            size = None
        maps[name] = {"mobs": files, "minimap": size and {"width": size["width"], "height": size["height"]}}
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
    path = os.path.join(sprites_dir, MAP_LIST)
    try:
        with open(path, encoding="utf-8") as f:
            entries = map_entries(json.load(f))
    except (OSError, ValueError):
        return False
    for entry in entries or []:
        if isinstance(entry, dict) and entry.get("name") == name:
            entry["minimap"] = {"width": width, "height": height}
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

def name_rows(sct, area):
    w, h = area["x2"] - area["x1"] + 1, area["y2"] - area["y1"] + 1
    return text_rows(grab(sct, area["x1"], area["y1"], w, h), w, h, area.get("light", 170))

def teach_map(sct, config, sprites_dir, name):
    """Teach the map you're standing on as `name`: its name's look, and its
    mobs (its PNGs in map.json), learned against this map. Updates `config`
    (the caller saves it). Returns why not, or None when taught."""
    mobs = config.get("mobs")
    if not mobs or "reach" not in mobs:
        return "Mark your hitbox first: python screen_stats.py --mobs"
    sprites = map_sprites(sprites_dir, name)
    if not sprites:
        return "No mob sprites for %s: list its PNGs in %s" % (name, os.path.join(sprites_dir, MAP_LIST))
    area = config.get("map_name") or mark_map_name(config)
    if not area:
        return "A map is told apart by its name, so mark where the name is"
    rows = name_rows(sct, area)
    if ones(rows) < 15:
        say("  Can't see a light name there (%d px). If the name is darker, lower \"light\" in map_name." % ones(rows))
    for other, m in sorted(config.get("maps", {}).items()):
        if other != name and rows_score(rows, [int(r, 16) for r in m["rows"]]) >= 0.8:
            say("  Careful: this name looks like %s's; mark just the name (--setup)." % other)
    entry = read_map_list(sprites_dir)[0].get(name) or {}
    if config.get("minimap") and entry.get("mobs") is not None and not entry.get("minimap"):
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
    learned["rows"] = ["%x" % r for r in rows]
    learned["taught_at"] = int(time.time())   # recent maps come first in the F9 list
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
    for name, label in BARS:
        pts = mark_points("%s bar: hover its LEFT end, F8; then its RIGHT end, F8 (Esc skips)" % label, 2)
        if len(pts) < 2:
            say("  skipped"); continue
        (x1, y), (x2, _) = pts
        x1, x2 = min(x1, x2), max(x1, x2)
        color = list(known["bars"][name]) if known else pixel(sct, x1 + 2, y)
        config["bars"][name] = {"x1": x1, "x2": x2, "y": y, "color": color, "tolerance": 60}
    if known:
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
    if names:
        say("Maps in %s: %s" % (MAP_LIST, ", ".join(names)))
        mark_map_name(config)
    setup_mobs(sct, config, sprites_dir)
    old = load_config(path, required=False)
    for keep in ("watch", "maps"):         # death/login marks from --mark, maps taught with F9 / --map
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

class Pad:
    """Posts readings to the pad, logging in with the PIN when it asks (401)."""
    def __init__(self, host, pin):
        self.base, self.pin = "http://" + host, pin
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def _post(self, path, fields):
        return self.opener.open(self.base + path, data=urllib.parse.urlencode(fields).encode(), timeout=3).read()

    def _call(self, path, fields):
        try:
            return self._post(path, fields)
        except urllib.error.HTTPError as e:
            if e.code != 401:
                raise
            if not self.pin:
                raise SystemExit("Kabuto wants its access PIN: pass --pin or set KABUTO_PIN")
            try:
                self._post("/api/login", {"pin": self.pin})   # sets the session cookie
            except urllib.error.HTTPError as login:
                raise SystemExit("Login failed: %s" % json.loads(login.read() or b"{}").get("error", login.code))
            return self._post(path, fields)

    def send(self, readings):
        self._call("/api/stats", form_fields(readings))

    def keys(self):
        """Setup buttons pressed on the pad since the last ask, or None if the
        pad doesn't know them (firmware from before them)."""
        try:
            return json.loads(self._call("/api/tool/keys", {}) or b"{}").get("keys", [])
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise

ESPRESSIF_VID = 0x303A   # the ESP32-S3's own USB port

class UsbPad:
    """Sends readings down the USB cable ("KABUTO stats <form>" lines), so a
    game laptop needs no Wi-Fi or PIN: plugging the pad in is the permission."""
    def __init__(self, port, version=None):
        self.port, self.version, self.lock = port, version, threading.Lock()

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
            if line.startswith("KABUTO ") and line != "KABUTO ok":
                self.version = line[7:]
                return self.version
        return None

    def send(self, readings):
        with self.lock:
            self.port.write(("KABUTO stats " + urllib.parse.urlencode(form_fields(readings)) + "\n").encode())
            waiting = getattr(self.port, "in_waiting", 0)
            if waiting:
                self.port.read(waiting)   # replies and the pad's log; just keep the buffer empty

    def keys(self, wait=1.0):
        """Setup buttons pressed on the pad since the last ask, or None if the
        pad doesn't answer (firmware from before them)."""
        with self.lock:
            self.port.write(b"KABUTO keys\n")
            end = time.time() + wait
            while time.time() < end:
                line = self.port.readline().decode("ascii", "replace").strip()
                if line == "KABUTO keys" or line.startswith("KABUTO keys "):
                    return [k for k in line[12:].split(",") if k]
        return None

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
                keys = pad.keys()
                if keys is None:
                    say("This pad's firmware has no setup buttons yet: update it to use them")
                    return
                for k in keys:
                    if k in PAD_KEYS:
                        press(PAD_KEYS[k])
                time.sleep(every if isinstance(pad, UsbPad) else max(every, 0.3))   # go easier on Wi-Fi
            except (urllib.error.URLError, OSError):
                if pad:
                    link.drop(pad)
                time.sleep(3)
            except SystemExit as e:   # e.g. a wrong PIN: the readings say so too
                print(e)
                return
    threading.Thread(target=loop, daemon=True).start()

def connect(args):
    """USB if a Kabuto is plugged in (unless --via wifi), otherwise Wi-Fi."""
    if args.via in ("auto", "usb"):
        pad = find_usb_pad()
        if pad:
            return pad
        if args.via == "usb":
            raise OSError("no Kabuto on USB (plug it in with a data cable)")
    pad = Pad(args.host, args.pin)
    pad.where = "Wi-Fi " + args.host
    return pad

def describe(r):
    parts = ["%s %5.1f%%" % (label, r[name]) for name, label in BARS if r.get(name) is not None]
    if r.get("x") is not None:
        parts.append("map %4.1f,%4.1f" % (r["x"], r["y"]))
    if r.get("mobs") is not None:
        parts.append("mobs " + (r["mobs"] or "-"))
    if r.get("mobs") is None and r.get("state", "ok") == "ok":
        parts.append("mobs: not looking" + (" (map not taught: F9)" if r.get("map") == "-" else ""))
    if r.get("ml") is not None:
        near = lambda side: "%d%%" % r["d" + side] if r.get("d" + side) is not None else "-"
        parts.append("seen L%d (%s) R%d (%s)" % (r["ml"], near("l"), r["mr"], near("r")) + (" " + r["mn"] if r.get("mn") else ""))
    if r.get("map") is not None:
        parts.append("map " + (r["map"] if r["map"] != "-" else "not taught"))
    if r.get("state", "ok") != "ok":
        parts.append("!! " + r["state"].upper())
    return "  ".join(parts)

def run(args):
    import mss
    sct, config = mss.mss(), load_config(args.config, required=False)
    if not (config.get("bars") or config.get("minimap") or config.get("mobs")):
        say("First run: let's mark your bars, minimap and mobs (hover, then F8).")
        setup(args.config, args.sprites, args.game or "maplestory")
        config = load_config(args.config)
    if args.game and config.get("game") != args.game:   # --game other: sampled colours again
        config["game"] = args.game
        save_config(args.config, config)
    screen, pad, link, map_list = Screen(sct, config, args.sprites), None, None, MapList(args.sprites)
    pads = None if args.dry_run else getattr(args, "pads", None) or PadLink(args)
    while True:
        maps = map_list.get()
        screen.sizes = map_sizes(maps)
        screen.map_mobs = {n: e.get("mobs") for n, e in maps.items()}
        if LAYER:
            LAYER.maps, LAYER.taught = sorted(maps), {n: m.get("taught_at", 0) for n, m in config.get("maps", {}).items()}
            LAYER.changed = {n for n in LAYER.taught if map_changed(args.sprites, maps, n, config["maps"][n])}
            while not LAYER.commands.empty():
                kind, value = LAYER.commands.get()
                if kind == "teach":   # F9: value is the map
                    problem = teach_map(sct, config, args.sprites, value)
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
        started = time.time()
        readings = screen.read()
        line = describe(readings) + "  %d ms" % ((time.time() - started) * 1000)   # how long a reading takes here
        try:
            pad = pads.get() if pads else None
            link = pad.where if pad else "dry run"
            if pad:
                pad.send(readings)
            print("\r" + line.ljust(70) + ("" if pad else "(dry run)"), end="", flush=True)
            wait = args.interval
        except (urllib.error.URLError, OSError) as e:   # serial errors are OSErrors too
            print("\r%s  can't reach Kabuto (%s), retrying..." % (line, getattr(e, "reason", e)), end="", flush=True)
            link = "can't reach Kabuto"
            if pad:
                pads.drop(pad)   # unplugged or out of range: look again
            wait = 3
        if LAYER:
            hint = "%s changed in %s: F9 to relearn" % (screen.current, MAP_LIST) if screen.current in LAYER.changed else None
            if screen.tag and not screen.you:
                hint = (hint + " \u00b7 " if hint else "") + "can't see your name tag"
            tol = mob_tolerance(config, screen.current) if readings.get("mobs") is not None else None
            LAYER.show(layer_status(readings, link, config.get("game"), LAYER.maps, hint, tol),
                       layer_shapes(config, sct.monitors[0], screen.boxes, readings, screen.box, screen.you))
        time.sleep(wait)

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

def layer_status(r, link, game=None, maps=(), hint=None, tol=None):
    """The strip's first line from a reading: [(text, colour), ...]."""
    known = GAMES.get(game)
    out = [("Kabuto" + (" \u00b7 " + ("MS" if game == "maplestory" else known["label"]) if known else ""), AMBER),
           (link or "starting", RED if link and link.startswith("can't") else DIM)]
    for name, label in BARS:
        if r.get(name) is not None:
            out.append(("%s %.0f%%" % ("MP" if name == "mana" else label, r[name]), BAR_COLORS[name]))
    if r.get("state", "ok") != "ok":
        out.append((r["state"].upper(), RED))
    if r.get("map") == "-":
        out.append(("new map, mobs not seen: F9" if maps else "map not taught", RED))
    elif r.get("map"):
        out.append((r["map"].replace("_", " "), INK))
    if hint:
        out.append((hint, AMBER))
    if r.get("ml") is not None:
        near = [(r["d" + side], side) for side in "lr" if r.get("d" + side) is not None]
        out.append(("\u25c0%d \u00b7 %d\u25b6" % (r["ml"], r["mr"]), INK))
        if near:
            d, side = min(near)
            out.append(("%s %s %d%%" % ("target" if d <= 100 else "nearest", r.get("mn") or ("left" if side == "l" else "right"), d),
                        RED if d <= 100 else DIM))
    elif r.get("mobs") is not None:
        out.append(("mobs " + (r["mobs"] or "-"), INK))
    elif r.get("map") != "-":   # nothing to say how many: smart can't stop for them
        out.append(("not looking for mobs" + (": F9 on this map" if maps else ""), RED))
    if tol is not None:   # how close a colour must be to a mob's (F6 looser, F7 stricter)
        out.append(("tolerance %d" % tol, DIM))
    out.append(("F6/F7 looser/stricter \u00b7 F9 map \u00b7 F10 outlines \u00b7 F11 hide", DIM))
    return out

def layer_shapes(config, monitor, boxes, r, mm=None, you=None):
    """Outlines over the game: [(x0, y0, x1, y1, colour, label), ...] in screen
    coordinates. The minimap (`mm`, else the setup's) and name area are drawn
    just outside what's read."""
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
    a = config.get("map_name")
    if a:
        out.append((a["x1"] - 2, a["y1"] - 2, a["x2"] + 2, a["y2"] + 2, "#c084fc", "map name"))
    return out

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
        w, h = (monitor["width"], monitor["height"]) if self.windows else (monitor["width"], 44)
        root.geometry("%dx%d+%d+%d" % (w, h, monitor["left"], monitor["top"]))
        bg = self.KEY if self.windows else "#16181d"
        if self.windows:
            root.attributes("-transparentcolor", self.KEY)
        self.canvas = tk.Canvas(root, width=w, height=h, bg=bg, highlightthickness=0)
        self.canvas.pack()
        root.update_idletasks()
        self.unseen = self._click_through() if self.windows else True
        root.report_callback_exception = self._error
        self.lock, self.commands, self.keys = threading.Lock(), queue.Queue(), queue.Queue()
        self.status, self.shapes, self.message, self.until = [("Kabuto", AMBER), ("starting", DIM)], [], "", 0
        self.outlines, self.hidden, self.finished, self.maps, self.taught, self.picker = self.windows, False, False, [], {}, None
        self.changed = set()
        self.unlisten = listen(self.keys.put)

    def _click_through(self):
        """Clicks pass through to the game, no taskbar button, never focused;
        and left out of screen captures. False if Windows can't leave it out."""
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(self.root.winfo_id())
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
        with self.lock:
            status, shapes = list(self.status), list(self.shapes)
            message = self.message if time.time() < self.until else ""
        if not self.unseen:   # captured with the game: only outlines drawn outside what's read
            shapes = [s for s in shapes if s[5] in ("minimap", "map name")]
        self._draw(status, shapes if self.outlines else [], message)
        if self.finished:
            self.root.after(4000 if message else 300, self.root.quit)
            self.finished = None
        self.root.after(150, self._refresh)

    def _draw(self, status, shapes, message):
        c, ox, oy = self.canvas, self.monitor["left"], self.monitor["top"]
        c.delete("all")
        if self.hidden:
            return
        for x0, y0, x1, y1, color, label in shapes:
            c.create_rectangle(x0 - ox, y0 - oy, x1 - ox, y1 - oy, outline=color, width=2)
            if label == "minimap":   # under it: the map name is usually just above
                c.create_text(x0 - ox + 3, y1 - oy + 2, text=label, fill=color, anchor="nw", font=("Segoe UI", 9, "bold"))
            elif label and label != "you":
                c.create_text(x0 - ox + 3, y0 - oy - 2, text=label, fill=color, anchor="sw", font=("Segoe UI", 9, "bold"))
        x, font = 0, ("Segoe UI", 10)
        items = []
        for text, color in status:
            item = c.create_text(x, 12, text=text, fill=color, anchor="w", font=font)
            items.append(item)
            x = c.bbox(item)[2] + 14
        if message:
            items.append(c.create_text(0, 32, text=message, fill=AMBER, anchor="w", font=font))
        right = max(c.bbox(i)[2] for i in items)
        shift = max(0, (int(c["width"]) - right) // 2)
        for i in items:
            c.move(i, shift, 0)
        bg = c.create_rectangle(shift - 10, 0, shift + right + 10, 44 if message else 24, fill="#16181d", outline="#2b2f39")
        c.tag_lower(bg)

    def _pick_map(self):
        """Which map (from map.json) this is: a searchable list. Type to
        narrow it, arrows to move, Enter or a double click to pick, Esc to close."""
        tk = self.tk
        if self.picker:
            self.picker.destroy()
        if not self.maps:
            self.say('List your maps in mobs/%s, e.g. [{"name": "Henesys", "mobs": ["snail.png"]}], with the PNGs in mobs, then F9' % MAP_LIST)
            return
        panel, field, font = "#1e2128", "#16181d", "Segoe UI"
        win = self.picker = tk.Toplevel(self.root)
        win.title("Which map is this?")
        win.attributes("-topmost", True)
        win.configure(bg=panel, padx=16, pady=14)
        w, h = 460, 540
        win.geometry("%dx%d+%d+%d" % (w, h, self.monitor["left"] + (self.monitor["width"] - w) // 2,
                                      self.monitor["top"] + max(40, (self.monitor["height"] - h) // 3)))
        tk.Label(win, text="Which map are you on?", bg=panel, fg=INK, font=(font, 14, "bold")).pack(anchor="w")
        tk.Label(win, text="Type to search  \u00b7  \u2191\u2193 to move  \u00b7  Enter picks  \u00b7  Esc closes",
                 bg=panel, fg=DIM, font=(font, 9)).pack(anchor="w", pady=(2, 10))
        query = tk.StringVar()
        entry = tk.Entry(win, textvariable=query, bg=field, fg=INK, insertbackground=INK, relief="flat", font=(font, 12),
                         highlightthickness=1, highlightbackground="#2b2f39", highlightcolor=AMBER)
        entry.pack(fill="x", ipady=7)
        box = tk.Frame(win, bg=panel)
        box.pack(fill="both", expand=True, pady=(10, 6))
        bar = tk.Scrollbar(box, orient="vertical")
        rows = tk.Listbox(box, bg=field, fg=INK, font=(font, 11), activestyle="none", relief="flat", highlightthickness=0,
                          selectbackground=AMBER, selectforeground=field, borderwidth=0, yscrollcommand=bar.set)
        bar.config(command=rows.yview)
        bar.pack(side="right", fill="y")
        rows.pack(side="left", fill="both", expand=True)
        foot = tk.Frame(win, bg=panel)
        foot.pack(fill="x")
        count = tk.Label(foot, bg=panel, fg=DIM, font=(font, 9))
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
                    rows.itemconfig(i, fg=AMBER if note.startswith("changed") else "#45d6b5")
            if shown:
                rows.selection_set(0); rows.see(0)
            total = len(self.maps)
            count.config(text=("%d of %d maps" % (len(shown), total) if query.get().strip() else "%d maps" % total)
                         + ("" if shown else "  \u00b7  no match"))
        tk.Button(foot, text="Cancel", command=close, bg=field, fg=INK, relief="flat", padx=12,
                  activebackground="#2b2f39", activeforeground=INK).pack(side="right")
        tk.Button(foot, text="Teach this map", command=choose, bg=AMBER, fg=field, relief="flat", padx=12,
                  activebackground="#ffc04d", activeforeground=field, font=(font, 10, "bold")).pack(side="right", padx=(0, 8))
        query.trace_add("write", refresh)
        for key, step in (("<Down>", 1), ("<Up>", -1), ("<Next>", 10), ("<Prior>", -10)):
            entry.bind(key, lambda e, s=step: move(s))
            rows.bind(key, lambda e, s=step: move(s))
        for widget in (entry, rows):
            widget.bind("<Return>", choose)
        rows.bind("<Double-Button-1>", choose)
        win.bind("<Escape>", close)
        self.pick = {"query": query, "rows": shown, "choose": choose, "move": move, "list": rows}   # for the self-test
        refresh()
        win.after(50, entry.focus_force)

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
            say("Stopped: %s" % e)
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
    # Minimap dot: found at its centre, absent when gone.
    yellow = (250, 220, 40)
    mm = canvas(101, 51, grey); paint(mm, 101, 20, 30, 24, 34, yellow)
    x, y = find_dot(mm, 101, 51, yellow)
    assert abs(x - 21.0) < 2 and abs(y - 63.0) < 3, (x, y)
    assert find_dot(canvas(101, 51, grey), 101, 51, yellow) is None
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
    assert mob_area(hb, {"left": 0, "top": 0, "width": 1920, "height": 1080}) == (0, 300, 800, 120)   # 800 x 120 px
    assert mob_area(hb, {"left": 0, "top": 0, "width": 700, "height": 1080}) == (0, 300, 700, 120)    # clipped to the screen
    assert mob_area({"x": 400, "y": 360}, {"left": 0, "top": 0, "width": 1920, "height": 1080}) == (50, 280, 700, 160)   # older setups
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
    assert mob_fields(seen, 200) == {"mobs": "R", "ml": 1, "mr": 3, "dr": 52, "dl": 192, "mn": "blob"}
    assert mob_fields(seen, 400) == {"mobs": "RL", "ml": 1, "mr": 3, "dr": 26, "dl": 96, "mn": "blob"}
    assert mob_fields({"L": [], "R": []}, 200) == {"mobs": "", "ml": 0, "mr": 0, "mn": None}   # none: no distances
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
    reader = MapReader({"Henesys": {"rows": ["%x" % r for r in a]}, "Ellinia": {"rows": ["%x" % r for r in text_rows(name_area(ellinia), 60, 14)]}})
    assert reader.read(name_area(henesys, 1), 60, 14) == "Henesys" and reader.read(name_area(ellinia), 60, 14) == "Ellinia"
    assert reader.read(name_area([(5, 3, 50, 11)]), 60, 14) == ""   # a map you haven't taught
    assert safe_name("Henesys Hunting Ground!") == "Henesys_Hunting_Ground_" and safe_name("Slime-2") == "Slime-2"
    # Marked patches.
    ref = bytes([10, 20, 30] * 25)
    assert patch_matches(bytes([12, 18, 33] * 25), ref) and not patch_matches(bytes([200, 200, 200] * 25), ref)
    assert not patch_matches(b"", ref)
    # Game state needs agreeing readings; marks win straight away.
    g = GameState()
    assert g.update(0, 50, True, True, {}) == "ok" and g.update(0, 50, True, True, {}) == "dead"
    assert g.update(70, 50, True, True, {}) == "ok"
    g = GameState(); g.update(0, 0, False, True, {})
    assert g.update(None, 0, False, True, {}) == "offline"
    assert GameState().update(80, 50, True, True, {"death": True}) == "dead"
    assert GameState().update(80, 50, True, True, {"login": True, "death": True}) == "offline"
    assert GameState().update(None, None, False, False, {}) == "ok"   # nothing set up: no false alarms
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
    assert abs(r["x"] - 26.4) < 2 and abs(r["y"] - 52.0) < 4, r
    paint(fake.px, 800, 100, 580, 250, 584, grey)            # HP gone: dead after two readings
    assert screen.read()["state"] == "ok" and screen.read()["state"] == "dead"
    paint(fake.px, 800, 100, 580, 250, 584, red)
    paint(fake.px, 800, 600, 10, 760, 90, (220, 220, 230))   # another map: no stop, the new view is followed
    paint(fake.px, 800, 680, 50, 684, 54, yellow)
    assert [screen.read()["state"] for _ in range(3)] == ["ok"] * 3
    assert "map" not in r and "ml" not in r   # no map library, an older mob setup: sides only

    # A taught map: its name picks its mobs, which are counted out of reach
    # too; an untaught map falls back to the setup's mobs.
    fake = FakeScreen()
    for x, y, x1, y1 in henesys:
        paint(fake.px, 800, 600 + x, 92 + y, 600 + x1, 92 + y1, white)
    stamp(fake.px, 800, 450, 310); stamp(fake.px, 800, 500, 310)   # mobs 54 and 104 px right of you
    config = {"map_name": {"x1": 600, "y1": 92, "x2": 659, "y2": 105},
              "maps": {"Henesys Field": {"rows": ["%x" % v for v in a], "colors": [[200, 40, 160]], "step_x": 2, "step_y": 2,
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
    assert r["map"] == "-" and r["mobs"] == "" and "ml" not in r and "not taught" in describe(r), r   # the setup's (green) mobs: none here
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
        # The current form: an object per map, with its minimap size; other keys are kept for later.
        write('[{"name": "Rocky Road II", "mobs": ["snail.png"], "minimap": {"width": 178, "height": 96}, "home": 0.3},'
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

    # Mobs missed for a moment (hit effects, mist) are held where they were seen.
    memory, snail = MobMemory(0.6), (0.9, "snail", 100, 50, 40, 30)
    assert memory.update([snail], 0.0, "A") == [snail + (False,)]
    assert memory.update([], 0.4, "A") == [snail + (True,)] and memory.update([], 0.7, "A") == []   # held 0.6 s, then gone
    moved = (0.8, "snail", 112, 50, 40, 30)
    memory.update([snail], 1.0, "A")
    assert memory.update([moved], 1.2, "A") == [moved + (False,)]                 # seen again nearby: not counted twice
    assert memory.update([(0.7, "slime", 110, 50, 40, 30)], 1.3, "A")[1] == moved + (True,)   # another mob there doesn't replace it
    assert memory.update([], 1.4, "B") == []                                       # another map forgets it
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
    strip = layer_status({"hp": 72.4, "mana": 40.0, "xp": 63.2, "map": "Henesys_Field", "mobs": "R", "ml": 1, "mr": 3, "dl": 192,
                          "dr": 52, "mn": "Blue_Snail", "state": "ok"}, "USB COM9", "maplestory", ["Henesys Field"])
    texts = [t for t, _ in strip]
    assert texts[:5] == ["Kabuto \u00b7 MS", "USB COM9", "HP 72%", "MP 40%", "XP 63%"] and "Henesys Field" in texts, texts
    assert "\u25c01 \u00b7 3\u25b6" in texts and ("target Blue_Snail 52%", RED) in strip, strip
    strip = layer_status({"hp": 0.0, "state": "dead", "map": "-", "ml": 0, "mr": 0}, "can't reach Kabuto", None, ["A"])
    assert ("DEAD", RED) in strip and ("new map, mobs not seen: F9", RED) in strip and strip[1][1] == RED and not any(t.startswith("target") for t, _ in strip)
    assert ("map not taught", RED) in layer_status({"map": "-"}, "USB", None, [])
    assert ("tolerance 45", DIM) in layer_status({"mobs": "R"}, "USB", tol=45) and not any(t.startswith("tolerance") for t, _ in layer_status({"mobs": "R"}, "USB"))
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
    assert labels["sight"] == (150, 300, 650, 340) and labels["reach"] == (300, 300, 500, 340) and labels["Blue Snail x2"] == (450, 310, 470, 330)
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
        def read(self, n): self.replies.clear(); return b""
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
    # The pad's setup buttons over USB: log lines and stats replies are skipped.
    kabuto.replies = [b"KABUTO ok\n", b"[ok] tap\n", b"KABUTO keys mark,map\n"]
    assert pad.keys() == ["mark", "map"] and kabuto.sent[-1] == b"KABUTO keys\n"
    kabuto.replies = [b"KABUTO keys\n"]
    assert pad.keys() == []
    kabuto.replies = []
    assert pad.keys(wait=0.05) is None   # older firmware doesn't answer
    assert find_usb_pad([Port("COM1", 0x1234)], opener=lambda d: 1 / 0) is None   # no Espressif port: not opened

    # Login on 401, then the readings go through.
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    seen = []
    class Fake(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"])).decode()
            authed = "kabuto_session=ok" in (self.headers.get("Cookie") or "")
            if self.path == "/api/login":
                good = body == "pin=246810"
                self.send_response(200 if good else 401)
                if good:
                    self.send_header("Set-Cookie", "kabuto_session=ok; Path=/; HttpOnly; SameSite=Strict")
                self.end_headers(); self.wfile.write(b'{"ok":true}' if good else b'{"error":"Wrong PIN"}')
                return
            if self.path == "/api/tool/keys":
                self.send_response(200 if authed else 401); self.end_headers(); self.wfile.write(b'{"keys":["skip"]}')
                return
            seen.append((authed, body))
            self.send_response(200 if authed else 401); self.end_headers(); self.wfile.write(b"{}")
    server = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host = "127.0.0.1:%d" % server.server_port
    pad = Pad(host, "246810")
    pad.send({"hp": 72.0, "mana": None, "xp": 63.2, "state": "ok", "mobs": ""})
    pad.send({"hp": 0.0, "mana": 40.0, "x": 41.5, "y": 70.0, "state": "dead", "mobs": "R"})
    assert seen == [(False, "hp=72.0&xp=63.2&mobs=&state=ok"), (True, "hp=72.0&xp=63.2&mobs=&state=ok"),
                    (True, "hp=0.0&mana=40.0&x=41.5&y=70.0&mobs=R&state=dead")], seen
    assert Pad(host, "246810").keys() == ["skip"]   # logs in first, like readings
    try:
        Pad(host, "000000").send({"hp": 1.0}); raise AssertionError("wrong PIN accepted")
    except SystemExit as e:
        assert "Wrong PIN" in str(e)
    server.shutdown()
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
    ap.add_argument("--mark", choices=["death", "login"], help="capture a spot only that screen has")
    ap.add_argument("--tag", action="store_true", help="mark just your name tag (so you're followed on screen)")
    ap.add_argument("--via", choices=["auto", "usb", "wifi"], default="auto",
                    help="how to reach the pad: USB cable if plugged in, else Wi-Fi (default auto)")
    ap.add_argument("--host", default="kabuto.local", help="the pad's Wi-Fi address (default kabuto.local)")
    ap.add_argument("--pin", default=os.environ.get("KABUTO_PIN"), help="access PIN (or set KABUTO_PIN)")
    ap.add_argument("--interval", type=float, default=0.5, help="seconds between readings (default 0.5)")
    ap.add_argument("--config", default=CONFIG, help="setup file (default %s)" % CONFIG)
    ap.add_argument("--dry-run", action="store_true", help="print readings without sending")
    ap.add_argument("--game", choices=sorted(GAMES) + ["other"],
                    help="the game's built-in colours (default maplestory for a new setup); other: sample them")
    ap.add_argument("--no-layer", action="store_true", help="no game layer over the game; the terminal only")
    ap.add_argument("--selftest", action="store_true", help="run built-in tests and exit")
    a = ap.parse_args()
    if a.selftest:
        selftest()
    elif a.map is not None:
        learn_map(a.config, a.sprites, a.map)   # asks in the terminal; in the game, F9 does this
    else:
        # The pad's setup buttons work from the start, setup included.
        a.pads = None if a.dry_run else PadLink(a)
        if a.pads:
            watch_pad_keys(a.pads)
        if a.setup:
            job = lambda: setup(a.config, a.sprites, a.game or "maplestory")
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
