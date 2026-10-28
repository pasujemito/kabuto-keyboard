#!/usr/bin/env python3
"""
screen_stats.py - read your HP, Mana and XP bars and send them to Kabuto.

Runs on the PC with the game. About once a second it grabs one pixel row
across each bar, works out how full it is, and sends three numbers to the
pad. Nothing else leaves your PC: no screenshots, no reading text.

Setup (once, with the game open and every bar at least partly filled):
    pip install mss pynput
    python tools/screen_stats.py --setup
    # hover over the LEFT end of each bar and press F8, then the RIGHT end
    # and press F8: HP, then Mana, then XP. Esc skips a bar.

Run (the pad on your home Wi-Fi with "Stay connected", or this PC joined to
the Kabuto-Setup hotspot, where no PIN is needed):
    python tools/screen_stats.py --pin 123456               # http://kabuto.local
    python tools/screen_stats.py --host 192.168.1.42 --pin 123456
    python tools/screen_stats.py --dry-run                  # just print readings
Set KABUTO_PIN instead of --pin to keep the PIN out of your shell history.

Run the self-test (no screen or pad needed):
    python tools/screen_stats.py --selftest
"""
import argparse, http.cookiejar, json, os, sys, time, urllib.error, urllib.parse, urllib.request

BARS = (("hp", "HP"), ("mana", "Mana"), ("xp", "XP"))
CONFIG = "kabuto-bars.json"   # in the current folder (gitignored)

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

def read_bars(sct, bars):
    readings = {}
    for name, bar in bars.items():
        shot = sct.grab({"left": bar["x1"], "top": bar["y"], "width": bar["x2"] - bar["x1"] + 1, "height": 1})
        raw = shot.rgb
        row = [tuple(raw[i:i + 3]) for i in range(0, len(raw), 3)]
        readings[name] = fill_percent(row, bar["color"], bar.get("tolerance", 60))
    return readings

def setup(path):
    import mss                       # first: on Windows this makes the process DPI-aware,
    from pynput import keyboard, mouse   # so pointer positions and pixels agree
    sct, pointer, bars = mss.mss(), mouse.Controller(), {}
    for name, label in BARS:
        print("%s: hover over the LEFT end of the bar and press F8, then the RIGHT end and press F8 (Esc skips)" % label)
        points = []
        def on_press(key):
            if key == keyboard.Key.esc:
                points.clear(); return False
            if key == keyboard.Key.f8:
                points.append(tuple(int(v) for v in pointer.position))
                print("  marked", points[-1])
                if len(points) == 2:
                    return False
        with keyboard.Listener(on_press=on_press) as listener:
            listener.join()
        if len(points) < 2:
            print("  skipped"); continue
        (x1, y), (x2, _) = points
        x1, x2 = min(x1, x2), max(x1, x2)
        # The bar's colour, just inside its left end (where any fill starts).
        color = list(sct.grab({"left": x1 + 2, "top": y, "width": 1, "height": 1}).rgb[:3])
        bars[name] = {"x1": x1, "x2": x2, "y": y, "color": color, "tolerance": 60}
        print("  %s: x %d-%d at y %d, colour %s" % (label, x1, x2, y, color))
    with open(path, "w") as f:
        json.dump({"bars": bars}, f, indent=2)
    print("Saved", path, "- if a bar reads wrong, raise its tolerance there (default 60).")

class Pad:
    """Posts readings to the pad, logging in with the PIN when it asks (401)."""
    def __init__(self, host, pin):
        self.base, self.pin = "http://" + host, pin
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def _post(self, path, fields):
        return self.opener.open(self.base + path, data=urllib.parse.urlencode(fields).encode(), timeout=3).read()

    def send(self, readings):
        fields = {k: v for k, v in readings.items() if v is not None}
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

def run(args):
    import mss
    try:
        with open(args.config) as f:
            bars = json.load(f)["bars"]
    except FileNotFoundError:
        raise SystemExit("No %s yet - run with --setup first" % args.config)
    if not bars:
        raise SystemExit("No bars set up - run with --setup")
    pad = None if args.dry_run else Pad(args.host, args.pin)
    sct = mss.mss()
    while True:
        readings = read_bars(sct, bars)
        line = "  ".join("%s %5.1f%%" % (label, readings[name]) for name, label in BARS if readings.get(name) is not None)
        try:
            if pad:
                pad.send(readings)
            print("\r" + line + ("" if pad else "  (dry run)"), end="", flush=True)
            time.sleep(args.interval)
        except (urllib.error.URLError, OSError) as e:
            print("\r%s  can't reach %s (%s), retrying..." % (line, args.host, getattr(e, "reason", e)), end="", flush=True)
            time.sleep(5)

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
    # Login on 401, then the readings go through; unread bars are left out.
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
    pad.send({"hp": 72.0, "mana": None, "xp": 63.2})
    pad.send({"hp": 70.5, "mana": 40.0, "xp": 63.3})
    assert seen == [(False, "hp=72.0&xp=63.2"), (True, "hp=72.0&xp=63.2"), (True, "hp=70.5&mana=40.0&xp=63.3")], seen
    try:
        Pad(host, "000000").send({"hp": 1.0}); raise AssertionError("wrong PIN accepted")
    except SystemExit as e:
        assert "Wrong PIN" in str(e)
    server.shutdown()
    print("selftest passed")

def main():
    ap = argparse.ArgumentParser(description="Send your HP, Mana and XP bars to Kabuto.")
    ap.add_argument("--setup", action="store_true", help="mark where the bars are")
    ap.add_argument("--host", default="kabuto.local", help="the pad's address (default kabuto.local)")
    ap.add_argument("--pin", default=os.environ.get("KABUTO_PIN"), help="access PIN (or set KABUTO_PIN)")
    ap.add_argument("--interval", type=float, default=1.0, help="seconds between readings (default 1)")
    ap.add_argument("--config", default=CONFIG, help="bar positions file (default %s)" % CONFIG)
    ap.add_argument("--dry-run", action="store_true", help="print readings without sending")
    ap.add_argument("--selftest", action="store_true", help="run built-in tests and exit")
    a = ap.parse_args()
    if a.selftest:
        selftest()
    elif a.setup:
        setup(a.config)
    else:
        try:
            run(a)
        except KeyboardInterrupt:
            print()

if __name__ == "__main__":
    main()
