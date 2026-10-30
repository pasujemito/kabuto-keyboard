#!/usr/bin/env python3
"""
screen_stats.py - read your game screen and send what matters to Kabuto.

Runs on the PC with the game. Twice a second it samples a few small
areas of the screen and sends a handful of numbers to the pad: HP, Mana and
XP (bar fill %), your position on the minimap, the mobs around you (which
sides are in your reach, how many you can see each side, how near the nearest
is, its name), the map you're on, and whether you're dead or disconnected. Nothing else leaves
your PC: no screenshots, no reading text. All the work happens here, so the
pad only stores a few numbers.

Easiest: plug the pad into the game PC with a USB data cable, then
    pip install mss pynput pyserial
    python screen_stats.py
The first run walks you through setup; after that it finds the pad on the
cable and starts sending. No Wi-Fi or PIN over USB. To redo setup:
    python screen_stats.py --setup
    # Mark things by hovering and pressing F8 (Esc skips): each bar's left and
    # right end; the minimap's top-left and bottom-right corners, then your
    # dot on it; your character's head, feet and attack reach (the hitbox
    # mobs are looked for in), then up to 3 mobs (Esc when done).
Mob sprites: put PNGs with transparent backgrounds (a frame or two of each
mob) in a "mobs" folder here; setup learns their colours instead of asking
you to mark mobs (needs pip install pillow). After adding sprites:
    python screen_stats.py --mobs
Mobs per map: a folder per map in "mobs" (mobs/Henesys/*.png, ...). Setup
asks where the map's name is shown; then stand on each map and teach it:
    python screen_stats.py --map            # asks which folder
    python screen_stats.py --map Henesys
Its name is kept as a picture (no OCR), so whenever that name shows, that
map's mobs are looked for. A map you haven't taught uses the "mobs" folder's.
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
import argparse, http.cookiejar, json, os, random, sys, time, urllib.error, urllib.parse, urllib.request

BARS = (("hp", "HP"), ("mana", "Mana"), ("xp", "XP"))
CONFIG = "kabuto-bars.json"   # in the current folder (gitignored)

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
    """The checks that hit a mob colour: [((right side?, cell x, cell y), colour bits, x), ...]."""
    out = []
    for y in range(0, h, step):
        row = y * w
        for x in range(0, w, step):
            if abs(x - mid) <= gap:
                continue
            i = (row + x) * 3
            bits = table[raw[i] >> 3 << 10 | raw[i + 1] >> 3 << 5 | raw[i + 2] >> 3]
            if bits:
                out.append(((x >= mid, x // cell, y // cell), bits, x))
    return out

def patches(samples, mask=-1):
    """Hits per patch (2 x 2 cells, about a mob's size), from samples whose
    colour bits are in `mask`: {(side, cell x, cell y): (hits, nearest x)}."""
    cells = {}
    for key, bits, x in samples:
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

def mob_view(raw, w, h, colors, tolerance=40, gap=40, mid=None, step=6, min_hits=3, cell=16, names=None, mob_w=0):
    """Every mob in the area, each side nearest first: {"L": [(distance px,
    name), ...], "R": [...]}. A mob is a clump: patches with at least
    `min_hits` hits whose cells touch. A clump wider than one mob (`mob_w` px)
    counts as that many side by side. `names` (one per colour) name a mob after
    the sprite most of its hits came from; None without them."""
    mid = w // 2 if mid is None else mid
    samples = mob_samples(raw, w, h, color_table(colors, tolerance), gap, mid, step, cell)
    cells = {}
    for key, bits, x in samples:
        cells.setdefault(key, []).append((bits, x))
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
        xs = [x for _, x in hits]
        votes = {}
        for bits, _ in hits:
            for i, name in enumerate(names or []):
                if bits >> i & 1:
                    votes[name] = votes.get(name, 0) + 1
        name = max(sorted(votes), key=votes.get) if votes else None
        near = min(abs(x - mid) for x in xs)
        count = max(1, int(round((max(xs) - min(xs) + step) / float(mob_w)))) if mob_w else 1
        view["R" if group[0][0] else "L"] += [(near + k * mob_w, name) for k in range(count)]
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
    """The map name area's light pixels (the name's letters), one int per row."""
    rows = []
    for y in range(h):
        bits = 0
        for x in range(w):
            i = (y * w + x) * 3
            if raw[i] * 3 + raw[i + 1] * 6 + raw[i + 2] >= light * 10:
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
    share_on_map = [min([sum(1 for _, bits, _ in ss if bits >> i & 1) / total for ss in shots] or [0]) for i in range(len(colors))]
    kept = 0
    for name, owned in owners.items():
        for i, share in owned:
            if share_on_map[i] <= share / 4:
                kept |= 1 << i
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
            else:
                report.append("  %s: skipped %s (%d%% of it, but the map has it too: %.1f%%, up to %d hits in one patch)"
                              % (name, colors[i], share * 100, share_on_map[i] * 100, peak(1 << i)))
        if not mine:
            report.append("  %s: no colour of its own - it looks too much like the map to spot" % name)
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

def load_sprites(folder):
    """{file name: (width, height, rgba pixels)} for the images in `folder`.
    Files that can't be read are skipped with a reason, not fatal."""
    if not os.path.isdir(folder):
        return {}
    names = sorted(n for n in os.listdir(folder) if n.lower().endswith(SPRITE_TYPES))
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

class Screen:
    """Everything read each tick, plus what's learned at start (the map)."""
    def __init__(self, sct, config):
        mm = config.get("minimap") or {}
        self.sct, self.config, self.state = sct, config, GameState()
        self.minimap = MinimapTracker(threshold=mm.get("map_mismatch", 0.6))
        area = config.get("map_name")
        self.maps = MapReader(config.get("maps", {}), area.get("light", 170)) if area and config.get("maps") else None

    def map_name(self):
        """The taught map you're on ("" for one you haven't taught), or None
        without a map library."""
        if not self.maps:
            return None
        a = self.config["map_name"]
        w, h = a["x2"] - a["x1"] + 1, a["y2"] - a["y1"] + 1
        return self.maps.read(grab(self.sct, a["x1"], a["y1"], w, h), w, h)

    def mobs(self, name):
        """Mob fields for the reading (see mob_fields), with this map's colours
        when it's taught, else the ones from setup. {} without a mob detector."""
        mb = self.config.get("mobs")
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
        view = mob_view(grab(self.sct, left, top, w, h), w, h, found["colors"], mb.get("tolerance", 40), mb.get("gap", 40),
                        mid=mb["x"] - left, step=found.get("step_x", 6), min_hits=found.get("min_hits", 3),
                        cell=found["cell"], names=found.get("names"), mob_w=found.get("mob_w", 0))
        return mob_fields(view, mb.get("reach", 350))

    def read(self):
        c = self.config
        out = read_bars(self.sct, c.get("bars", {}))
        dot, world, mm = None, None, c.get("minimap")
        if mm:
            w, h = mm["x2"] - mm["x1"] + 1, mm["y2"] - mm["y1"] + 1
            raw = grab(self.sct, mm["x1"], mm["y1"], w, h)
            dot = find_dot(raw, w, h, mm["dot"], mm.get("tolerance", 40))
            if dot:                      # a login or loading screen isn't the map
                self.minimap.update(raw, w, h)
                world = self.minimap.world(dot, w, h)
        name = self.map_name()
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

def mark_points(prompt, count):
    """Hover and press F8 to mark up to `count` points; Esc ends early (or skips)."""
    from pynput import keyboard, mouse
    pointer, points = mouse.Controller(), []
    print(prompt)
    def on_press(key):
        if key == keyboard.Key.esc:
            return False
        if key == keyboard.Key.f8:
            points.append(tuple(int(v) for v in pointer.position))
            print("  marked", points[-1])
            if len(points) == count:
                return False
    with keyboard.Listener(on_press=on_press) as listener:
        listener.join()
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
    sprites = load_sprites(sprites_dir)
    mobs = {"tolerance": 40}
    box = "Hitbox: hover YOUR character's HEAD, F8; its FEET, F8; then how far your attack reaches to one side, F8"
    folders = map_folders(sprites_dir)
    if sprites or folders:
        if sprites:
            print("Found %d mob sprite(s) in %s." % (len(sprites), sprites_dir))
        pts = mark_points(box + " (Esc skips). Mobs nearby are fine.", 3)
        if len(pts) < 3:
            print("  skipped"); return
        mobs.update(hitbox(*pts), sight=SIGHT)
        print("  Hitbox: %d px tall, %d px to each side." % (mobs["bottom"] - mobs["top"], mobs["reach"]))
        learned = learn_here(sct, mobs, sprites) if sprites else None
        if learned:
            mobs.update(learned)
        elif not folders:
            print("  No usable mob colours: mob detection is off."); return
        else:   # the map folders bring their own colours (--map)
            print("  Mobs come from the map folders: teach each map with --map.")
    else:
        if os.path.isdir(sprites_dir) and any(n.lower().endswith(SPRITE_TYPES) for n in os.listdir(sprites_dir)):
            print("No readable sprites in %s, so mark mobs on screen instead." % sprites_dir)
        pts = mark_points(box + "; then up to 3 mobs (different kinds), F8 each; Esc when done", 6)
        if len(pts) < 4:
            print("  skipped"); return
        mobs.update(hitbox(*pts[:3]), colors=[pixel(sct, x, y) for x, y in pts[3:]])
    config["mobs"] = mobs

def learn_here(sct, mobs, sprites):
    """Mob settings for `sprites` against the map you're on, watched for 4 s
    over the area you look for mobs in. None if no colour of theirs is usable."""
    left, top, w, h = mob_area(mobs, sct.monitors[0], mobs.get("sight", SIGHT))
    print("  Looking at the map for 4 s...")
    shots = []
    for _ in range(5):
        shots.append(grab(sct, left, top, w, h))
        time.sleep(0.8)
    learned, report = learn_mob_colors(sprites, shots, w, h, mobs.get("tolerance", 40), mobs.get("gap", 40), mobs["x"] - left)
    print("\n".join(report))
    if not learned["colors"]:
        return None
    return {"colors": learned["colors"], "step_x": learned["step"], "step_y": learned["step"], "cell": learned["cell"],
            "min_hits": learned["min_hits"], "names": learned["names"], "mob_w": learned["mob_w"], "sprites": sorted(sprites)}

def mark_map_name(config):
    pts = mark_points("Map name: hover the TOP-LEFT of the map's name, F8; then its BOTTOM-RIGHT, a bit past where "
                      "the longest name would end, F8 (Esc skips)", 2)
    if len(pts) < 2:
        print("  skipped"); return None
    (ax, ay), (bx, by) = pts
    config["map_name"] = {"x1": min(ax, bx), "y1": min(ay, by), "x2": max(ax, bx), "y2": max(ay, by), "light": 170}
    return config["map_name"]

def map_folders(sprites_dir):
    """Folders in `sprites_dir`, one per map, named as you like (e.g. the map's name)."""
    if not os.path.isdir(sprites_dir):
        return []
    return sorted(d for d in os.listdir(sprites_dir) if os.path.isdir(os.path.join(sprites_dir, d)))

def learn_map(path, sprites_dir, name=""):
    """Teach the map you're standing on: its name's look, and the mobs in its
    folder (mobs/<map>/*.png), learned against this map."""
    import mss
    sct, config = mss.mss(), load_config(path)
    mobs = config.get("mobs")
    if not mobs or "reach" not in mobs:
        raise SystemExit("Mark your hitbox first: python screen_stats.py --mobs")
    folders = map_folders(sprites_dir)
    if not name:
        if not folders:
            raise SystemExit("Make a folder per map in %s (e.g. %s/Henesys) with that map's mob sprites" % (sprites_dir, sprites_dir))
        if len(folders) == 1:
            name = folders[0]
        else:
            for i, f in enumerate(folders, 1):
                print("  %d. %s%s" % (i, f, "  (taught)" if f in config.get("maps", {}) else ""))
            pick = input("Which map are you on? Number or folder name: ").strip()
            name = folders[int(pick) - 1] if pick.isdigit() and 1 <= int(pick) <= len(folders) else pick
    sprites = load_sprites(os.path.join(sprites_dir, name))
    if not sprites:
        raise SystemExit("No mob sprites in %s" % os.path.join(sprites_dir, name))
    area = config.get("map_name") or mark_map_name(config)
    if not area:
        raise SystemExit("A map is told apart by its name, so mark where the name is")
    w, h = area["x2"] - area["x1"] + 1, area["y2"] - area["y1"] + 1
    rows = text_rows(grab(sct, area["x1"], area["y1"], w, h), w, h, area.get("light", 170))
    if ones(rows) < 15:
        print("  Can't see a light name there (%d px). If the name is darker, lower \"light\" in %s's map_name." % (ones(rows), path))
    for other, m in sorted(config.get("maps", {}).items()):
        if other != name and rows_score(rows, [int(r, 16) for r in m["rows"]]) >= 0.8:
            print("  Careful: this name looks like %s's; move the marks so the area holds just the name." % other)
    print("Teaching %s with %d sprite(s)." % (name, len(sprites)))
    learned = learn_here(sct, mobs, sprites)
    if not learned:
        raise SystemExit("No usable mob colours for %s: nothing saved" % name)
    learned["rows"] = ["%x" % r for r in rows]
    config.setdefault("maps", {})[name] = learned
    save_config(path, config)
    print("Saved %s in %s: it switches to these mobs whenever this name shows." % (name, path))

def setup(path, sprites_dir="mobs"):
    import mss                         # first: on Windows this makes the process DPI-aware,
    sct, config = mss.mss(), {"bars": {}}   # so pointer positions and pixels agree
    for name, label in BARS:
        pts = mark_points("%s bar: hover its LEFT end, F8; then its RIGHT end, F8 (Esc skips)" % label, 2)
        if len(pts) < 2:
            print("  skipped"); continue
        (x1, y), (x2, _) = pts
        x1, x2 = min(x1, x2), max(x1, x2)
        config["bars"][name] = {"x1": x1, "x2": x2, "y": y, "color": pixel(sct, x1 + 2, y), "tolerance": 60}
    pts = mark_points("Minimap: hover its TOP-LEFT corner, F8; BOTTOM-RIGHT corner, F8; then YOUR dot, F8 (Esc skips)", 3)
    if len(pts) == 3:
        (ax, ay), (bx, by), (dx, dy) = pts
        config["minimap"] = {"x1": min(ax, bx), "y1": min(ay, by), "x2": max(ax, bx), "y2": max(ay, by),
                             "dot": pixel(sct, dx, dy), "tolerance": 40, "map_mismatch": 0.6}
    folders = map_folders(sprites_dir)
    if folders:
        print("Map folders in %s: %s" % (sprites_dir, ", ".join(folders)))
        mark_map_name(config)
    setup_mobs(sct, config, sprites_dir)
    old = load_config(path, required=False)
    for keep in ("watch", "maps"):         # death/login marks from --mark, maps from --map
        if old.get(keep):
            config[keep] = old[keep]
    if folders and "map_name" not in config and old.get("map_name"):
        config["map_name"] = old["map_name"]
    save_config(path, config)
    print("Saved", path, "- if something reads wrong, raise its tolerance there.")
    if folders:
        print("Now teach each map: stand on it and run  python screen_stats.py --map")

def relearn_mobs(path, sprites_dir):
    import mss
    config = load_config(path)
    setup_mobs(mss.mss(), config, sprites_dir)
    save_config(path, config)
    print("Saved", path)

def mark(path, what):
    import mss
    sct, config = mss.mss(), load_config(path, required=False)
    pts = mark_points("With the %s screen showing, hover something only it has (e.g. a button), F8 (Esc cancels)" % what, 1)
    if not pts:
        return
    x, y = pts[0]
    config.setdefault("watch", {})[what] = {"x": x, "y": y, "patch": list(grab(sct, x - 2, y - 2, 5, 5))}
    save_config(path, config)
    print("Saved the %s mark in %s" % (what, path))

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

    def send(self, readings):
        fields = form_fields(readings)
        try:
            self._post("/api/stats", fields)
        except urllib.error.HTTPError as e:
            if e.code != 401:
                raise
            if not self.pin:
                raise SystemExit("Kabuto wants its access PIN: pass --pin or set KABUTO_PIN")
            try:
                self._post("/api/login", {"pin": self.pin})   # sets the session cookie
            except urllib.error.HTTPError as login:
                raise SystemExit("Login failed: %s" % json.loads(login.read() or b"{}").get("error", login.code))
            self._post("/api/stats", fields)

ESPRESSIF_VID = 0x303A   # the ESP32-S3's own USB port

class UsbPad:
    """Sends readings down the USB cable ("KABUTO stats <form>" lines), so a
    game laptop needs no Wi-Fi or PIN: plugging the pad in is the permission."""
    def __init__(self, port, version=None):
        self.port, self.version = port, version

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
        self.port.write(("KABUTO stats " + urllib.parse.urlencode(form_fields(readings)) + "\n").encode())
        waiting = getattr(self.port, "in_waiting", 0)
        if waiting:
            self.port.read(waiting)   # replies and the pad's log; just keep the buffer empty

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
    config = load_config(args.config, required=False)
    if not (config.get("bars") or config.get("minimap") or config.get("mobs")):
        print("First run: let's mark your bars, minimap and mobs (hover, then F8).")
        setup(args.config, args.sprites)
        config = load_config(args.config)
    screen, pad = Screen(mss.mss(), config), None
    while True:
        readings = screen.read()
        line = describe(readings)
        try:
            if not args.dry_run and pad is None:
                pad = connect(args)
                print("\nSending to Kabuto over %s" % pad.where)
            if pad:
                pad.send(readings)
            print("\r" + line.ljust(70) + ("" if pad else "(dry run)"), end="", flush=True)
            time.sleep(args.interval)
        except (urllib.error.URLError, OSError) as e:   # serial errors are OSErrors too
            print("\r%s  can't reach Kabuto (%s), retrying..." % (line, getattr(e, "reason", e)), end="", flush=True)
            pad = None   # unplugged or out of range: look again
            time.sleep(3)

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
    assert not learned["colors"] and "looks too much like the map" in report[-1]
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
    assert form_fields({"hp": 1.0, "mobs": "R", "ml": 0, "mr": 2, "dr": 54, "mn": "blob", "map": "Henesys", "state": "ok"}) == \
        {"hp": 1.0, "mobs": "R", "ml": 0, "mr": 2, "dr": 54, "mn": "blob", "map": "Henesys", "state": "ok"}

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
    try:
        Pad(host, "000000").send({"hp": 1.0}); raise AssertionError("wrong PIN accepted")
    except SystemExit as e:
        assert "Wrong PIN" in str(e)
    server.shutdown()
    print("selftest passed")

def main():
    ap = argparse.ArgumentParser(description="Send what your game screen shows to Kabuto.")
    ap.add_argument("--setup", action="store_true", help="mark the bars, minimap and mobs")
    ap.add_argument("--mobs", action="store_true", help="redo just the mob detector (e.g. after adding sprites)")
    ap.add_argument("--sprites", default="mobs", help="folder of mob sprite PNGs (default mobs)")
    ap.add_argument("--map", nargs="?", const="", metavar="FOLDER",
                    help="teach the map you're on, with the mobs in its folder (mobs/FOLDER); asks which without one")
    ap.add_argument("--mark", choices=["death", "login"], help="capture a spot only that screen has")
    ap.add_argument("--via", choices=["auto", "usb", "wifi"], default="auto",
                    help="how to reach the pad: USB cable if plugged in, else Wi-Fi (default auto)")
    ap.add_argument("--host", default="kabuto.local", help="the pad's Wi-Fi address (default kabuto.local)")
    ap.add_argument("--pin", default=os.environ.get("KABUTO_PIN"), help="access PIN (or set KABUTO_PIN)")
    ap.add_argument("--interval", type=float, default=0.5, help="seconds between readings (default 0.5)")
    ap.add_argument("--config", default=CONFIG, help="setup file (default %s)" % CONFIG)
    ap.add_argument("--dry-run", action="store_true", help="print readings without sending")
    ap.add_argument("--selftest", action="store_true", help="run built-in tests and exit")
    a = ap.parse_args()
    if a.selftest:
        selftest()
    elif a.setup:
        setup(a.config, a.sprites)
    elif a.mobs:
        relearn_mobs(a.config, a.sprites)
    elif a.map is not None:
        learn_map(a.config, a.sprites, a.map)
    elif a.mark:
        mark(a.config, a.mark)
    else:
        try:
            run(a)
        except KeyboardInterrupt:
            print()

if __name__ == "__main__":
    main()
