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

Answers make it a test: next to a screenshot, a .json of the same name says
which map it is and which mobs are in your field of view (on your platform,
or flying at your height), by name and the x of their middle on screen:

    {"map": "Damp Forest", "mobs": {"octopus": [438, 547, 1160], "jr_necki": [710]}}

Each screenshot then says what was missed, counted wrongly or misnamed, and
the run ends with a total (and fails if anything was off). --draft writes an
answer file from what was found for screenshots without one: correct it
(an image viewer shows the x under the mouse) and it's a test from then on.

Run the self-test (no screenshots needed):
    python scene_check.py --selftest
"""
import argparse, difflib, glob, json, os, re, sys, time

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

def answers_path(path):
    return os.path.splitext(path)[0] + ".json"

def load_answers(path):
    """The screenshot's answer file: {"map": name, "mobs": {mob: [x, ...]}}, or None."""
    try:
        with open(answers_path(path), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None

def draft_answers(name, boxes):
    """An answer file's content from what was found (to correct by hand)."""
    mobs = {}
    for b in sorted(boxes, key=lambda b: b[0]):
        if b[5]:
            mobs.setdefault(b[4] or "mob", []).append(int(round((b[0] + b[2]) / 2.0)))
    return {"map": name, "mobs": mobs}

def answers_text(answers):
    """An answer file's text: one line per mob, easy to edit by hand."""
    mobs = answers.get("mobs") or {}
    lines = ['    %s: [%s]' % (json.dumps(mob), ", ".join(str(x) for x in xs)) for mob, xs in mobs.items()]
    body = "{\n" + ",\n".join(lines) + "\n  }" if lines else "{}"
    return '{\n  "map": %s,\n  "mobs": %s\n}\n' % (json.dumps(answers.get("map")), body)

def compare(answers, boxes):
    """(right, misnamed, missed, wrong): each a list of (mob, x). A find
    answers a mob when its middle is within half its width (30 px at least);
    misnamed holds (answer, x, name found)."""
    want = [(mob, x) for mob, xs in (answers.get("mobs") or {}).items() for x in xs]
    found = [((b[0] + b[2]) / 2.0, b[2] - b[0], b[4]) for b in boxes if b[5]]
    right, misnamed, missed = [], [], []
    for mob, x in sorted(want, key=lambda m: m[1]):
        near = [f for f in found if abs(f[0] - x) <= max(30, f[1] / 2.0)]
        if not near:
            missed.append((mob, x)); continue
        best = min(near, key=lambda f: (f[2] != mob, abs(f[0] - x)))
        found.remove(best)
        (right if best[2] == mob else misnamed).append((mob, x) if best[2] == mob else (mob, x, best[2]))
    return right, misnamed, missed, [(f[2], int(round(f[0]))) for f in found]

def verdict(result):
    right, misnamed, missed, wrong = result
    if not (misnamed or missed or wrong):
        return "all %d right" % len(right)
    bits = ["missed " + ", ".join("%s at %d" % m for m in missed)] if missed else []
    bits += ["wrongly counted " + ", ".join("%s at %d" % m for m in wrong)] if wrong else []
    bits += ["misnamed " + ", ".join("%s at %d as %s" % m for m in misnamed)] if misnamed else []
    return "; ".join(bits)

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
    boxes = [(100, 0, 140, 30, "snail", 1, 0.9), (300, 0, 340, 30, "slime", 1, 0.8), (600, 0, 640, 30, "snail", 1, 0.7),
             (800, 0, 840, 30, "snail", 0, 0.3)]   # the last turned down: not counted
    assert compare({"mobs": {"snail": [118, 400], "slime": [622]}}, boxes) == \
        ([("snail", 118)], [("slime", 622, "snail")], [("snail", 400)], [("slime", 320)])
    assert verdict(compare({"mobs": {"snail": [120, 620], "slime": [320]}}, boxes)) == "all 3 right"
    assert draft_answers("A", boxes) == {"map": "A", "mobs": {"snail": [120, 620], "slime": [320]}}
    assert json.loads(answers_text(draft_answers("A", boxes))) == draft_answers("A", boxes)
    assert '"snail": [120, 620]' in answers_text(draft_answers("A", boxes)) and json.loads(answers_text({"map": "B", "mobs": {}}))["mobs"] == {}
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
    ap.add_argument("--draft", action="store_true", help="write answer files from what was found, where there are none")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    files = [f for pattern in a.scenes for f in (sorted(glob.glob(pattern)) or [pattern])]
    if not files:
        raise SystemExit("Give some screenshots, e.g. scenes/*/*.png")
    if not ss.numpy_or_none():
        print("(numpy isn't installed: mobs by colour only; pip install numpy for the shape search)")
    totals, tested, perfect = [0, 0, 0, 0], 0, 0
    for path in files:
        config = ss.load_config(a.config)   # afresh each time: nothing carries over between shots
        answers = load_answers(path)
        line, r, boxes = check(path, config, a.sprites, a.map or (answers or {}).get("map"), a.out)
        print(line)
        if answers is not None:
            result = compare(answers, boxes)
            totals = [t + len(part) for t, part in zip(totals, result)]
            tested, perfect = tested + 1, perfect + (not any(result[1:]))
            print("  %s %s" % ("ok" if not any(result[1:]) else "XX", verdict(result)))
        elif a.draft:
            name = (re.search(r"map (.*?) \(", line) or [None, None])[1]
            with open(answers_path(path), "w", encoding="utf-8") as f:
                f.write(answers_text(draft_answers(name, boxes)))
            print("  answers drafted in %s: check them" % answers_path(path))
    print("Annotated copies in %s/" % a.out)
    if tested:
        right, misnamed, missed, wrong = totals
        print("Answers: %d of %d screenshots all right; mobs found %d of %d (%d misnamed), %d counted wrongly" % (
            perfect, tested, right + misnamed, right + misnamed + missed, misnamed, wrong))
        if perfect < tested:
            sys.exit(1)

if __name__ == "__main__":
    main()
