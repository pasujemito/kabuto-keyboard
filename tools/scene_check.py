#!/usr/bin/env python3
"""
scene_check.py - replay game screenshots through the screen reader.

Each screenshot goes through screen_stats.py's reader exactly as in the game
(map name, minimap, your name tag, mobs by shape or colour), with your setup
file and mobs folder. It prints what was found and saves a copy with the F10
outlines drawn on, to see how well mobs are picked up on each map. Nothing is
sent to the pad. Needs Pillow (and numpy for the shape search).

    python scene_check.py scenes/*/*.png
    python scene_check.py --config kabuto-bars.json --sprites mobs --out checked scenes/perion/*.png
    python scene_check.py --map "Deep Valley II" shot.png    # whose mobs, if the name isn't recognised

A map whose name isn't recognised is guessed from the file name
(deep_valley_ii.png -> Deep Valley II). Screenshots must be at the
resolution the setup was made at; PNG keeps colours exact (JPEG roughly).

Run the self-test (no screenshots needed):
    python scene_check.py --selftest
"""
import argparse, difflib, glob, os, re, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import screen_stats as ss

class Shot:
    def __init__(self, rgb):
        self.rgb = rgb

class ImageScreen:
    """A screenshot standing in for the screen: grab() cuts from it."""
    def __init__(self, image):
        self.image = image.convert("RGB")
        w, h = self.image.size
        self.monitors = [{"left": 0, "top": 0, "width": w, "height": h}] * 2

    def grab(self, r):
        return Shot(self.image.crop((r["left"], r["top"], r["left"] + r["width"], r["top"] + r["height"])).tobytes())

def guess_map(path, names):
    """The map a screenshot's file name stands for: the closest map.json name."""
    stem = re.sub(r"[^a-z0-9]+", " ", os.path.splitext(os.path.basename(path))[0].lower()).strip()
    plain = {re.sub(r"[^a-z0-9]+", " ", n.lower()).strip(): n for n in names}
    close = difflib.get_close_matches(stem, list(plain), n=1, cutoff=0.6)
    return plain[close[0]] if close else None

def check(path, config, sprites, forced=None, out=None):
    """One screenshot through the reader: (summary line, readings, boxes)."""
    from PIL import Image, ImageDraw
    image = Image.open(path)
    screen = ss.Screen(ImageScreen(image), config, sprites)
    maps = ss.read_map_list(sprites)[0]
    screen.sizes, screen.map_mobs = ss.map_sizes(maps), {n: e.get("mobs") for n, e in maps.items()}
    seen = screen.map_name()
    name, how = seen, "recognised"
    if not seen:
        name, how = forced or guess_map(path, maps), "given" if forced else "guessed from the file name"
        screen.map_name = lambda: name   # stand in for an untaught map
    started = time.time()
    r = screen.read()
    took = time.time() - started
    you = "you at %d,%d (name tag)" % screen.you if screen.you else "you where you stood at setup"
    mobs = sorted(screen.boxes, key=lambda b: b[0])
    counted = [b for b in mobs if b[5]]
    line = "%s: map %s (%s) | %s | %s left, %s right | %s | %d ms" % (
        os.path.basename(path), name or "?", how, you, r.get("ml", "-"), r.get("mr", "-"),
        ", ".join("%s %d%%" % (b[4], round(b[6] * 100)) if b[6] is not None else str(b[4]) for b in counted) or "no mobs",
        took * 1000)
    if out:
        drawn = image.convert("RGB")
        draw = ImageDraw.Draw(drawn)
        for x0, y0, x1, y1, colour, label in ss.layer_shapes(config, screen.sct.monitors[0], screen.boxes, r, screen.box, screen.you):
            draw.rectangle([x0, y0, x1, y1], outline=colour, width=2)
            if label:
                draw.text((x0 + 2, max(0, y0 - 12)), label, fill=colour)
        os.makedirs(out, exist_ok=True)
        drawn.save(os.path.join(out, os.path.splitext(os.path.basename(path))[0] + ".png"))
    return line, r, screen.boxes

def selftest():
    assert guess_map("scenes/perion/deep_valley_ii.jpg", ["Deep Valley I", "Deep Valley II", "Damp Forest"]) == "Deep Valley II"
    assert guess_map("the_burned_land_v.png", ["The Burnt Land V", "The Burnt Land III"]) == "The Burnt Land V"
    assert guess_map("zzz.png", ["Damp Forest"]) is None
    try:
        from PIL import Image
    except ImportError:
        print("selftest passed (Pillow not installed: replay not tried)"); return
    shot = ImageScreen(Image.new("RGB", (40, 30), (10, 20, 30)))
    assert shot.grab({"left": 5, "top": 5, "width": 4, "height": 2}).rgb == bytes((10, 20, 30)) * 8
    print("selftest passed")

def main():
    ap = argparse.ArgumentParser(description="Replay game screenshots through the screen reader.")
    ap.add_argument("scenes", nargs="*", help="screenshots (PNG best)")
    ap.add_argument("--config", default=ss.CONFIG, help="setup file (default %s)" % ss.CONFIG)
    ap.add_argument("--sprites", default="mobs", help="mobs folder with map.json (default mobs)")
    ap.add_argument("--map", help="the map, when its name isn't recognised")
    ap.add_argument("--out", default="checked", help="where the annotated copies go (default checked)")
    ap.add_argument("--selftest", action="store_true", help="run built-in tests and exit")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    files = [f for pattern in a.scenes for f in (sorted(glob.glob(pattern)) or [pattern])]
    if not files:
        raise SystemExit("Give some screenshots, e.g. scenes/*/*.png")
    if not ss.numpy_or_none():
        print("(numpy isn't installed: mobs by colour only; pip install numpy for the shape search)")
    for path in files:
        config = ss.load_config(a.config)   # afresh each time: nothing carries over between shots
        print(check(path, config, a.sprites, a.map, a.out)[0])
    print("Annotated copies in %s/" % a.out)

if __name__ == "__main__":
    main()
