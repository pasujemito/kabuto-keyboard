#!/usr/bin/env python3
"""
recorder.py - record your keyboard while you play, turn it into a MacroPad macro.

The MacroPad is a Bluetooth *output* device: it can't see your PC's keyboard.
So this companion runs on the PC, captures your own key presses with their real
timing, and writes a macros.json the pad can replay (optionally on a loop).

Timing is captured exactly as you played it and replayed verbatim - nothing is
randomised or altered. Keyboard only; mouse movement/clicks are not captured.

Usage:
    pip install pynput
    python recorder.py --out macros.json --loop 0 --trigger toggle
    # play; press the stop key (default F10) to finish.
    # then load macros.json via the pad's web UI, or `pio run -t uploadfs`.

Attach to a specific key without wiping the others:
    python recorder.py --into macros.json --key 4 --name "Combo"

Run the self-test (no keyboard, no pynput needed):
    python recorder.py --selftest
"""
import argparse, json, os, sys, time

# ---- key mapping ----------------------------------------------------------
# Names must match what the firmware understands (see src/keymap.cpp).
SPECIAL = {
    "space":"SPACE","enter":"ENTER","return":"ENTER","tab":"TAB",
    "backspace":"BACKSPACE","esc":"ESC","caps_lock":"CAPS","insert":"INSERT",
    "delete":"DELETE","home":"HOME","end":"END","page_up":"PAGEUP",
    "page_down":"PAGEDOWN","up":"UP","down":"DOWN","left":"LEFT","right":"RIGHT",
    "print_screen":"PRINTSCREEN",
    **{f"f{i}":f"F{i}" for i in range(1,13)},
}
MODS = {
    "shift":"shift","shift_l":"shift","shift_r":"rshift",
    "ctrl":"ctrl","ctrl_l":"ctrl","ctrl_r":"rctrl",
    "alt":"alt","alt_l":"alt","alt_r":"altgr","alt_gr":"altgr",
    "cmd":"gui","cmd_l":"gui","cmd_r":"gui","win":"gui",
}

def normalize_pynput(key):
    """Map a pynput key to ('key'|'mod', NAME) or None if unsupported."""
    # modifier / named keys arrive as pynput.keyboard.Key with a .name
    name = getattr(key, "name", None)
    if name is not None:
        if name in MODS:    return ("mod", MODS[name])
        if name in SPECIAL: return ("key", SPECIAL[name])
        return None
    # ordinary characters arrive as KeyCode with .char
    ch = getattr(key, "char", None)
    if not ch:
        return None
    ch = ch.upper()
    if ("A" <= ch <= "Z") or ("0" <= ch <= "9"):
        return ("key", ch)
    return None

# ---- conversion (pure, unit-tested) --------------------------------------
def events_to_steps(events, min_delay_ms=1):
    """
    events: list of (t_seconds, 'down'|'up', 'key'|'mod', name), in order.
    Returns the pad's step list, preserving overlapping holds and real gaps.
    """
    steps = []
    if not events:
        return steps
    last_t = events[0][0]
    for t, edge, kind, name in events:
        gap = int(round((t - last_t) * 1000))
        if gap >= min_delay_ms:
            steps.append({"type": "delay", "ms": gap})
        last_t = t
        if edge == "down":
            steps.append({"type": "down", "key": name} if kind == "key"
                         else {"type": "down", "mods": [name]})
        else:
            steps.append({"type": "up", "key": name} if kind == "key"
                         else {"type": "up", "mods": [name]})
    return steps

def wrap_loop(steps, count):
    """count == 1 -> no loop; otherwise wrap (0 = until stopped)."""
    if count == 1:
        return steps
    return [{"type": "loop", "count": count}] + steps + [{"type": "endloop"}]

def blank_key():
    return {"name": "", "trigger": "tap", "steps": []}

def build_config(steps, into_path, key_index, key_count, trigger, name):
    if into_path and os.path.exists(into_path):
        with open(into_path) as f:
            cfg = json.load(f)
    else:
        cfg = {"version": 1, "layers": [{"name": "Base", "keys": []}]}
    cfg.setdefault("layers", [])
    if not cfg["layers"]:
        cfg["layers"].append({"name": "Base", "keys": []})
    keys = cfg["layers"][0].setdefault("keys", [])
    while len(keys) < key_count:
        keys.append(blank_key())
    if key_index >= len(keys):
        raise SystemExit(f"key index {key_index} out of range (0..{len(keys)-1})")
    keys[key_index] = {"name": name, "trigger": trigger, "steps": steps}
    return cfg

# ---- live recording (needs pynput) ---------------------------------------
def record(stop_name):
    from pynput import keyboard  # imported here so --selftest needs no deps
    events, down = [], set()
    t0 = time.perf_counter()
    stop_name = stop_name.lower()

    def now():
        return time.perf_counter() - t0

    def on_press(key):
        kname = getattr(key, "name", None)
        if kname and kname.lower() == stop_name:
            return False  # stop; don't record the stop key
        m = normalize_pynput(key)
        if not m:
            return
        token = (m[0], m[1])
        if token in down:        # ignore OS auto-repeat while held
            return
        down.add(token)
        events.append((now(), "down", m[0], m[1]))

    def on_release(key):
        m = normalize_pynput(key)
        if not m:
            return
        token = (m[0], m[1])
        down.discard(token)
        events.append((now(), "up", m[0], m[1]))

    print(f"● recording - play normally, press {stop_name.upper()} to stop")
    with keyboard.Listener(on_press=on_press, on_release=on_release) as L:
        L.join()

    # release anything still held at stop, so the macro ends clean
    tend = now()
    for kind, name in list(down):
        events.append((tend, "up", kind, name))
    return events

# ---- self-test ------------------------------------------------------------
def selftest():
    ev = [
        (0.00, "down", "key", "W"),
        (0.50, "down", "mod", "shift"),
        (0.80, "up",  "key", "W"),
        (0.80, "up",  "mod", "shift"),
    ]
    steps = events_to_steps(ev)
    assert steps == [
        {"type":"down","key":"W"},
        {"type":"delay","ms":500},
        {"type":"down","mods":["shift"]},
        {"type":"delay","ms":300},
        {"type":"up","key":"W"},
        {"type":"up","mods":["shift"]},
    ], steps
    # loop wrapping
    assert wrap_loop([{"type":"delay","ms":1}], 1) == [{"type":"delay","ms":1}]
    looped = wrap_loop([{"type":"delay","ms":1}], 0)
    assert looped[0] == {"type":"loop","count":0} and looped[-1] == {"type":"endloop"}
    # build into a specific key, padding the rest
    cfg = build_config(steps, None, 4, 6, "toggle", "Combo")
    assert len(cfg["layers"][0]["keys"]) == 6
    assert cfg["layers"][0]["keys"][4]["name"] == "Combo"
    assert cfg["layers"][0]["keys"][0]["steps"] == []
    print("selftest OK")

# ---- cli ------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Record keyboard input into a MacroPad macro.")
    ap.add_argument("--out", default="macros.json", help="output file (default macros.json)")
    ap.add_argument("--into", help="merge the recording into this existing config, keeping other keys")
    ap.add_argument("--key", type=int, default=0, help="pad key index to attach the macro to (default 0)")
    ap.add_argument("--keys", type=int, default=6, help="total keys on the pad (default 6)")
    ap.add_argument("--loop", type=int, default=0, help="replay count; 0 = until stopped (default 0)")
    ap.add_argument("--trigger", default="toggle", choices=["tap","toggle","hold"],
                    help="trigger mode for the key (default toggle: press to start/stop)")
    ap.add_argument("--name", default="Recording", help="macro name shown in the UI")
    ap.add_argument("--stop-key", default="f10", help="key that ends recording (default f10)")
    ap.add_argument("--min-delay", type=int, default=1, help="ignore gaps shorter than this (ms)")
    ap.add_argument("--selftest", action="store_true", help="run built-in tests and exit")
    args = ap.parse_args()

    if args.selftest:
        selftest(); return

    events = record(args.stop_key)
    steps = wrap_loop(events_to_steps(events, args.min_delay), args.loop)
    target = args.into if args.into else None
    cfg = build_config(steps, target, args.key, args.keys, args.trigger, args.name)

    out = args.into if args.into else args.out
    with open(out, "w") as f:
        json.dump(cfg, f, indent=2)

    dur = events[-1][0] if events else 0
    print(f"✓ {len(events)} events over {dur:.1f}s -> key #{args.key} "
          f"({args.trigger}, loop={'∞' if args.loop==0 else args.loop})")
    print(f"✓ wrote {out}")
    print("  load it via the pad's web UI (Save to device) or `pio run -t uploadfs`.")

if __name__ == "__main__":
    main()
