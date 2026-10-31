#!/usr/bin/env python3
"""
mob_frames.py - fetch your mobs' animation frames for the shape search.

Mobs animate, so one PNG per mob only matches them some of the time. This
fetches each mob's stand, move, fly and hit frames from maplestory.io for
every PNG listed in mobs/map.json, and saves them next to it as
mob.stand0.png, mob.move1.png ... (screen_stats.py counts them as frames of
mob.png). Files already there are kept, so run it again after adding maps.

    python mob_frames.py                    # mobs/map.json, GMS v83
    python mob_frames.py --version 92       # another game version
    python mob_frames.py --dry-run          # just list what it would fetch

A PNG is matched to a mob by name: red_snail.png -> Red Snail. If a name
isn't found, end it with the mob's ID instead: zombie_mushroom_2230101.png.

Run the self-test (no network needed):
    python mob_frames.py --selftest
"""
import argparse, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request

ANIMATIONS = ("stand", "move", "fly", "hit1")   # the poses mobs are seen in while you fight them

def norm(name):
    """Letters and digits only, lower case: "Jr. Necki" -> "jrnecki"."""
    return re.sub(r"[^a-z0-9]", "", name.lower())

def wanted(stem):
    """(name to search for, mob ID or None) from a PNG's name without .png."""
    m = re.match(r"^(.*?)_(\d{5,8})$", stem)
    if m:
        return m.group(1).replace("_", " "), int(m.group(2))
    return stem.replace("_", " "), None

def listed_pngs(sprites_dir):
    """The PNGs map.json lists (any of its forms), each once."""
    with open(os.path.join(sprites_dir, "map.json"), encoding="utf-8") as f:
        data = json.load(f)
    entries = data if isinstance(data, list) else [v if isinstance(v, dict) else {"mobs": v} for v in data.values()]
    files = []
    for entry in entries:
        for png in (entry.get("mobs") or []) if isinstance(entry, dict) else []:
            if isinstance(png, str) and png not in files:
                files.append(png)
    return files

class Api:
    """maplestory.io, politely: a short pause between calls and patience when
    it's busy (it answers 503 when asked too fast)."""
    def __init__(self, region="GMS", version="83", pause=0.3):
        self.base, self.pause = "https://maplestory.io/api/%s/%s/mob" % (region, version), pause

    def get(self, url):
        for wait in (3, 6, 12, 24, 48):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "kabuto-mob-frames/1.0"})
                data = urllib.request.urlopen(req, timeout=30).read()
                time.sleep(self.pause)
                return data
            except urllib.error.HTTPError as e:
                if e.code not in (429, 503):
                    raise
                time.sleep(wait)
        raise OSError("maplestory.io is still busy; try again later")

    def find(self, name):
        """The mob called `name` (any case or punctuation): its ID, or None."""
        last = name.split()[-1] if name.split() else name
        found = json.loads(self.get(self.base + "?searchFor=" + urllib.parse.quote(last) + "&count=500"))
        exact = [m for m in found if norm(m.get("name", "")) == norm(name)]
        return exact[0]["id"] if exact else None

    def frames(self, mob_id):
        """{animation: frame count} for the poses we want."""
        books = json.loads(self.get("%s/%d" % (self.base, mob_id))).get("framebooks", {})
        return {a: books[a] for a in ANIMATIONS if books.get(a)}

    def render(self, mob_id, animation, frame):
        return self.get("%s/%d/render/%s/%d" % (self.base, mob_id, animation, frame))

def fetch(sprites_dir, api, dry_run=False, say=print):
    """Fetches the missing frames for every PNG map.json lists. Returns
    (frames saved, names not found)."""
    saved, missing = 0, []
    for png in listed_pngs(sprites_dir):
        stem = os.path.splitext(png)[0]
        name, mob_id = wanted(stem)
        try:
            mob_id = mob_id or api.find(name)
            if not mob_id:
                missing.append(png)
                say("  %s: no mob called %r (end the file name with its ID, e.g. %s_1234567.png)" % (png, name.title(), stem))
                continue
            books = api.frames(mob_id)
        except OSError as e:
            say("  %s: %s" % (png, e)); missing.append(png); continue
        todo = [(a, i) for a, n in books.items() for i in range(n)
                if not os.path.exists(os.path.join(sprites_dir, "%s.%s%d.png" % (stem, a, i)))]
        say("  %s (mob %d): %d frames, %d to fetch" % (png, mob_id, sum(books.values()), len(todo)))
        for a, i in todo:
            if dry_run:
                continue
            with open(os.path.join(sprites_dir, "%s.%s%d.png" % (stem, a, i)), "wb") as f:
                f.write(api.render(mob_id, a, i))
            saved += 1
    return saved, missing

def selftest():
    import tempfile
    assert norm("Jr. Necki") == norm("jr necki") == "jrnecki"
    assert wanted("red_snail") == ("red snail", None) and wanted("zombie_mushroom_2230101") == ("zombie mushroom", 2230101)
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "map.json"), "w") as f:
            json.dump([{"name": "A", "mobs": ["snail.png", "red_snail.png"]}, {"name": "B", "mobs": ["snail.png", "jr_necki.png"]}], f)
        assert listed_pngs(d) == ["snail.png", "red_snail.png", "jr_necki.png"]
        with open(os.path.join(d, "map.json"), "w") as f:
            json.dump({"A": ["snail.png"], "B": {"mobs": ["slime.png"]}}, f)
        assert listed_pngs(d) == ["snail.png", "slime.png"]   # the older forms too
        open(os.path.join(d, "snail.stand0.png"), "wb").close()
        class FakeApi:
            calls = []
            def find(self, name): return {"snail": 100100, "slime": 210100}.get(name)
            def frames(self, mob_id): return {"stand": 1, "move": 2}
            def render(self, mob_id, a, i): self.calls.append((mob_id, a, i)); return b"png"
        api, said = FakeApi(), []
        assert fetch(d, api, say=said.append) == (5, [])          # snail.stand0 was there already
        assert sorted(api.calls) == [(100100, "move", 0), (100100, "move", 1), (210100, "move", 0), (210100, "move", 1),
                                     (210100, "stand", 0)], api.calls
        assert os.path.exists(os.path.join(d, "slime.move1.png")) and fetch(d, api, say=said.append) == (0, [])   # all there now
        with open(os.path.join(d, "map.json"), "w") as f:
            json.dump([{"name": "C", "mobs": ["mystery_blob.png"]}], f)
        assert fetch(d, api, say=said.append) == (0, ["mystery_blob.png"]) and "end the file name with its ID" in said[-1]
    print("selftest passed")

def main():
    ap = argparse.ArgumentParser(description="Fetch your mobs' animation frames for screen_stats.py's shape search.")
    ap.add_argument("--sprites", default="mobs", help="folder with map.json and the mob PNGs (default mobs)")
    ap.add_argument("--region", default="GMS", help="maplestory.io region (default GMS)")
    ap.add_argument("--version", default="83", help="game version (default 83)")
    ap.add_argument("--dry-run", action="store_true", help="list what would be fetched")
    ap.add_argument("--selftest", action="store_true", help="run built-in tests and exit")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not os.path.isfile(os.path.join(a.sprites, "map.json")):
        raise SystemExit("No %s: run this next to your mobs folder (or pass --sprites)" % os.path.join(a.sprites, "map.json"))
    print("Fetching frames for the mobs in %s from maplestory.io (%s v%s)..." % (os.path.join(a.sprites, "map.json"), a.region, a.version))
    saved, missing = fetch(a.sprites, Api(a.region, a.version), a.dry_run)
    print("Done: %d frames saved%s." % (saved, "; not found: " + ", ".join(missing) if missing else ""))

if __name__ == "__main__":
    main()
