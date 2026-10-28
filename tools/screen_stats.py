#!/usr/bin/env python3
"""
screen_stats.py - read your game screen and send what matters to Kabuto.

Runs on the PC with the game. About once a second it samples a few small
areas of the screen and sends a handful of numbers to the pad: HP, Mana and
XP (bar fill %), your position on the minimap, which side mobs are on, and
whether you're dead, disconnected or on another map. Nothing else leaves
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
    # dot on it; your character, then up to 3 mobs (Esc when done).
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
Restart it after moving to a new map: it learns the map's minimap at start.
A minimap that slides as you walk is followed, so that isn't a new map.

Run the self-test (no screen or pad needed):
    python screen_stats.py --selftest
"""
import argparse, http.cookiejar, json, os, random, sys, time, urllib.error, urllib.parse, urllib.request

BARS = (("hp", "HP"), ("mana", "Mana"), ("xp", "XP"))
CONFIG = "kabuto-bars.json"   # in the current folder (gitignored)

# ---- pure screen maths (raw = RGB bytes, row by row) ------------------------

def near(raw, i, color, t2):
    return (raw[i] - color[0]) ** 2 + (raw[i + 1] - color[1]) ** 2 + (raw[i + 2] - color[2]) ** 2 <= t2

def fill_percent(row, color, tolerance=60, min_run=3):
    """How full a bar is, from one row of (r, g, b) pixels across it, left to
    right. Uses the end of the rightmost run of bar-coloured pixels, so numbers
    drawn over the middle of a bar don't make it look emptier."""
    if not row:
        return None
    end = run = 0
    for i, px in enumerate(row):
        if sum((a - b) ** 2 for a, b in zip(px, color)) <= tolerance ** 2:
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
    the middle while you walk). A view that two readings in a row can't line
    up with the last good one means a new map, teleport or respawn."""
    def __init__(self, threshold=0.6, max_slide=0.25):
        self.threshold, self.max_slide = threshold, max_slide
        self.prev, self.ox, self.oy, self.misses, self.changed = None, 0, 0, 0, False

    def update(self, raw, w, h):
        if self.prev is None:
            self.prev = raw
            return self.changed
        dx, dy, mismatch = find_slide(self.prev, raw, w, h, max(1, int(w * self.max_slide)), max(1, int(h * self.max_slide)))
        if mismatch > self.threshold:
            self.misses += 1                 # keep the last good view to compare against
            if self.misses >= 2:
                self.changed = True          # stays until the script restarts
        else:
            self.misses = 0
            self.ox += dx
            self.oy += dy
            self.prev = raw
        return self.changed

    def world(self, dot, w, h):
        """Your position on the whole map in tenths of a minimap width/height
        (can go below 0 or past 1000 as the minimap slides)."""
        x, y = dot
        return (round(self.ox * 1000.0 / max(w - 1, 1) + x * 10), round(self.oy * 1000.0 / max(h - 1, 1) + y * 10))

def mob_sides(raw, w, h, colors, tolerance=40, gap=40, mid=None, step_x=6, step_y=8, min_hits=3):
    """Which sides of you have mob-coloured pixels: 'L', 'R', 'LR' or ''.
    `mid` is your character's x in the area (default: its centre); `gap` px
    either side of it are skipped so your own character doesn't count."""
    t2, left, right = tolerance ** 2, 0, 0
    mid = w // 2 if mid is None else mid
    for y in range(0, h, step_y):
        for x in range(0, w, step_x):
            if abs(x - mid) <= gap:
                continue
            i = (y * w + x) * 3
            if any(near(raw, i, c, t2) for c in colors):
                if x < mid: left += 1
                else: right += 1
    return ("L" if left >= min_hits else "") + ("R" if right >= min_hits else "")

def patch_matches(raw, reference, tolerance=30):
    """Whether a small patch looks like the one captured with --mark."""
    if len(raw) != len(reference) or not raw:
        return False
    total = sum(abs(a - b) for a, b in zip(raw, reference))
    return total / len(raw) <= tolerance

class GameState:
    """ok / dead / offline / map from the readings, needing a couple of
    agreeing readings so one odd frame doesn't stop the pad."""
    def __init__(self):
        self.zero_hp = self.gone = 0

    def update(self, hp, mana, dot_seen, minimap_used, watches, map_changed):
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
        if map_changed:               # MinimapTracker already wants two readings
            return "map"
        return "ok"

# ---- screen access ----------------------------------------------------------

def grab(sct, left, top, width, height):
    return sct.grab({"left": left, "top": top, "width": width, "height": height}).rgb

def read_bars(sct, bars):
    readings = {}
    for name, bar in bars.items():
        raw = grab(sct, bar["x1"], bar["y"], bar["x2"] - bar["x1"] + 1, 1)
        row = [tuple(raw[i:i + 3]) for i in range(0, len(raw), 3)]
        readings[name] = fill_percent(row, bar["color"], bar.get("tolerance", 60))
    return readings

class Screen:
    """Everything read each tick, plus what's learned at start (the map)."""
    def __init__(self, sct, config):
        mm = config.get("minimap") or {}
        self.sct, self.config, self.state = sct, config, GameState()
        self.minimap = MinimapTracker(threshold=mm.get("map_mismatch", 0.6))   # "map_threshold" was the old check's: ignored

    def read(self):
        c = self.config
        out = read_bars(self.sct, c.get("bars", {}))
        dot, world, map_changed, mm = None, None, False, c.get("minimap")
        if mm:
            w, h = mm["x2"] - mm["x1"] + 1, mm["y2"] - mm["y1"] + 1
            raw = grab(self.sct, mm["x1"], mm["y1"], w, h)
            dot = find_dot(raw, w, h, mm["dot"], mm.get("tolerance", 40))
            # Only while your dot shows: a login or loading screen isn't the map.
            map_changed = self.minimap.update(raw, w, h) if dot else self.minimap.changed
            if dot:
                world = self.minimap.world(dot, w, h)
        mobs, mb = "", c.get("mobs")
        if mb and mb.get("colors"):
            # The area either side of your character, clipped to the screen.
            reach, band, screen = mb.get("reach", 350), mb.get("band", 80), self.sct.monitors[0]
            left, top = max(screen["left"], mb["x"] - reach), max(screen["top"], mb["y"] - band)
            right = min(screen["left"] + screen["width"], mb["x"] + reach)
            bottom = min(screen["top"] + screen["height"], mb["y"] + band)
            w, h = right - left, bottom - top
            raw = grab(self.sct, left, top, w, h)
            mobs = mob_sides(raw, w, h, mb["colors"], mb.get("tolerance", 40), mb.get("gap", 40), mid=mb["x"] - left)
        watches = {}
        for name, mark in c.get("watch", {}).items():
            watches[name] = patch_matches(grab(self.sct, mark["x"] - 2, mark["y"] - 2, 5, 5), bytes(mark["patch"]))
        out["state"] = self.state.update(out.get("hp"), out.get("mana"), dot is not None, bool(mm), watches, map_changed)
        out["x"], out["y"] = dot if dot else (None, None)
        out["wx"], out["wy"] = world if world else (None, None)   # for stuck: moves even when the dot doesn't
        out["mobs"] = mobs
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

def setup(path):
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
    pts = mark_points("Mobs: hover YOUR character, F8; then up to 3 mobs (different kinds), F8 each; Esc when done", 4)
    if len(pts) >= 2:
        (cx, cy), mobs = pts[0], pts[1:]
        config["mobs"] = {"x": cx, "y": cy, "reach": 350, "band": 80, "gap": 40, "tolerance": 40,
                          "colors": [pixel(sct, x, y) for x, y in mobs]}
    old = load_config(path, required=False)
    if old.get("watch"):
        config["watch"] = old["watch"]   # keep death/login marks from --mark
    save_config(path, config)
    print("Saved", path, "- if something reads wrong, raise its tolerance there.")

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
    """What to POST: unread values are left out, so the pad treats them as not read."""
    fields = {k: v for k, v in readings.items() if v is not None and k not in ("mobs", "state")}
    fields["state"] = readings.get("state", "ok")
    fields["mobs"] = readings.get("mobs", "")
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
    if r.get("mobs"):
        parts.append("mobs " + r["mobs"])
    if r.get("state", "ok") != "ok":
        parts.append("!! " + r["state"].upper())
    return "  ".join(parts)

def run(args):
    import mss
    config = load_config(args.config, required=False)
    if not (config.get("bars") or config.get("minimap") or config.get("mobs")):
        print("First run: let's mark your bars, minimap and mobs (hover, then F8).")
        setup(args.config)
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
        assert not t.update(raw, 100, 40), (ox, oy)
        d = find_dot(raw, 100, 40, yellow)
        positions.append(t.world(d, 100, 40))
    # Slides of 12, 18 and 25 px (and 4 down) are tracked: map position moves even though the dot doesn't.
    assert (t.ox, t.oy) == (55, 4), (t.ox, t.oy)
    assert positions[0][0] < positions[1][0] < positions[2][0] < positions[3][0], positions
    assert abs(positions[3][0] - positions[0][0] - round(55 * 1000 / 99)) <= 2
    # A far jump (300 px is more than a quarter of the minimap) can't be lined up: two of those = map changed.
    t2 = MinimapTracker()
    t2.update(view(0, 40, (50, 20)), 100, 40)
    t2.update(view(10, 40, (50, 20)), 100, 40)
    other_map = textured(400, 120, 999)
    assert not t2.update(view(10, 40, (50, 20), other_map), 100, 40)      # one odd reading: not yet
    assert not t2.update(view(14, 40, (50, 20)), 100, 40)                 # back to normal: forgiven
    assert t2.ox == 14 and t2.misses == 0
    assert not t2.update(view(0, 0, None, other_map), 100, 40)
    assert t2.update(view(4, 0, None, other_map), 100, 40) and t2.changed # two in a row: new map, latched
    assert t2.update(view(14, 40, (50, 20)), 100, 40)                     # stays until the script restarts
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
    # Character near the screen edge: the area is clipped, so "you" aren't in its middle.
    clipped = canvas(450, 160, grey); paint(clipped, 450, 80, 40, 120, 120, green); paint(clipped, 450, 300, 50, 340, 110, green)
    assert mob_sides(clipped, 450, 160, [green], mid=100) == "R"
    both = canvas(700, 160, grey); paint(both, 700, 50, 50, 90, 110, green); paint(both, 700, 600, 50, 640, 110, green)
    assert mob_sides(both, 700, 160, [(1, 2, 3), green]) == "LR"
    # Marked patches.
    ref = bytes([10, 20, 30] * 25)
    assert patch_matches(bytes([12, 18, 33] * 25), ref) and not patch_matches(bytes([200, 200, 200] * 25), ref)
    assert not patch_matches(b"", ref)
    # Game state needs agreeing readings; marks win straight away.
    g = GameState()
    assert g.update(0, 50, True, True, {}, False) == "ok" and g.update(0, 50, True, True, {}, False) == "dead"
    assert g.update(70, 50, True, True, {}, False) == "ok"
    g = GameState(); g.update(0, 0, False, True, {}, False)
    assert g.update(None, 0, False, True, {}, False) == "offline"
    assert GameState().update(80, 50, True, True, {}, True) == "map"   # the tracker already confirmed it
    assert GameState().update(80, 50, True, True, {"death": True}, False) == "dead"
    assert GameState().update(80, 50, True, True, {"login": True, "death": True}, False) == "offline"
    assert GameState().update(None, None, False, False, {}, False) == "ok"   # nothing set up: no false alarms
    # What's posted: unread values left out, state and mobs always sent.
    assert form_fields({"hp": 72.0, "mana": None, "xp": 63.2, "x": None, "y": None, "mobs": "", "state": "ok"}) == \
        {"hp": 72.0, "xp": 63.2, "state": "ok", "mobs": ""}
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
    paint(fake.px, 800, 600, 10, 760, 90, (40, 40, 40))      # minimap gone (loading): not compared, not a new map
    assert [screen.read()["state"] for _ in range(3)] == ["ok"] * 3
    paint(fake.px, 800, 600, 10, 760, 90, (220, 220, 230))   # a different minimap: map changed on the second reading
    paint(fake.px, 800, 680, 50, 684, 54, yellow)
    states = [screen.read()["state"] for _ in range(2)]
    assert states == ["ok", "map"], states

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
    assert kabuto.sent[-1] == b"KABUTO stats hp=0.0&x=41.5&y=70.0&state=dead&mobs=L\n", kabuto.sent
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
    assert seen == [(False, "hp=72.0&xp=63.2&state=ok&mobs="), (True, "hp=72.0&xp=63.2&state=ok&mobs="),
                    (True, "hp=0.0&mana=40.0&x=41.5&y=70.0&state=dead&mobs=R")], seen
    try:
        Pad(host, "000000").send({"hp": 1.0}); raise AssertionError("wrong PIN accepted")
    except SystemExit as e:
        assert "Wrong PIN" in str(e)
    server.shutdown()
    print("selftest passed")

def main():
    ap = argparse.ArgumentParser(description="Send what your game screen shows to Kabuto.")
    ap.add_argument("--setup", action="store_true", help="mark the bars, minimap and mobs")
    ap.add_argument("--mark", choices=["death", "login"], help="capture a spot only that screen has")
    ap.add_argument("--via", choices=["auto", "usb", "wifi"], default="auto",
                    help="how to reach the pad: USB cable if plugged in, else Wi-Fi (default auto)")
    ap.add_argument("--host", default="kabuto.local", help="the pad's Wi-Fi address (default kabuto.local)")
    ap.add_argument("--pin", default=os.environ.get("KABUTO_PIN"), help="access PIN (or set KABUTO_PIN)")
    ap.add_argument("--interval", type=float, default=1.0, help="seconds between readings (default 1)")
    ap.add_argument("--config", default=CONFIG, help="setup file (default %s)" % CONFIG)
    ap.add_argument("--dry-run", action="store_true", help="print readings without sending")
    ap.add_argument("--selftest", action="store_true", help="run built-in tests and exit")
    a = ap.parse_args()
    if a.selftest:
        selftest()
    elif a.setup:
        setup(a.config)
    elif a.mark:
        mark(a.config, a.mark)
    else:
        try:
            run(a)
        except KeyboardInterrupt:
            print()

if __name__ == "__main__":
    main()
