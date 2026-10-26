#!/usr/bin/env python3
"""
flash_backup.py - copy the pad's saved config off it over the USB cable.

`pio run -t uploadfs` writes a whole new filesystem image, which would replace
the /macros.json saved on the pad with the repo's data/macros.json. The
PlatformIO hook (tools/pio_keep_config.py) calls this before every uploadfs:
it reads the filesystem straight from flash, keeps a timestamped copy in
backups/, and puts your config into the image being flashed.

It reads flash with esptool, so it works with whatever firmware is on the pad,
and never writes to the pad itself.

Usage:
    pip install esptool littlefs-python      # PlatformIO installs these itself
    python tools/flash_backup.py backup                 # auto-detect the port
    python tools/flash_backup.py backup --port COM5     # or /dev/ttyACM0

Run the self-test (no pad needed):
    python tools/flash_backup.py --selftest
"""
import argparse, glob, gzip, json, os, struct, subprocess, sys, tempfile, time

PARTITION_TABLE_OFFSET = 0x8000
PARTITION_TABLE_SIZE = 0xC00
FS_BLOCK_SIZE = 4096                   # matches PlatformIO's mklittlefs image
CONFIG_NAME = "macros.json"            # MACRO_FILE in src/config.h
KEEP_BACKUPS = 5                       # newest gzipped copies kept (~2-20 KB each)

def find_fs_partition(table):
    """Return (offset, size) of the data partition holding LittleFS."""
    for i in range(0, len(table) - 31, 32):
        magic, ptype, subtype, offset, size = struct.unpack_from("<HBBII", table, i)
        if magic == 0xEBEB:            # MD5 row: skip
            continue
        if magic != 0x50AA:            # 0xFFFF marks the end of the table
            break
        if ptype == 0x01 and subtype in (0x82, 0x83):   # spiffs / littlefs
            return offset, size
    return None

def extract_config(image):
    """Return the bytes of /macros.json from a LittleFS image, or None if the
    image is blank, unreadable or has no saved config."""
    from littlefs import LittleFS, LittleFSError
    fs = LittleFS(block_size=FS_BLOCK_SIZE, block_count=len(image) // FS_BLOCK_SIZE,
                  read_size=256, prog_size=256, mount=False)
    fs.context.buffer[:] = image[:len(fs.context.buffer)]
    try:
        fs.mount()                     # read only: never format a dump
        with fs.open(CONFIG_NAME, "rb") as f:
            return f.read()
    except (LittleFSError, FileNotFoundError, OSError):
        return None

def read_flash(esptool, chip, port, baud, offset, size):
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "dump.bin")
        cmd = list(esptool) + ["--chip", chip] + (["--port", port] if port else []) + \
              ["--baud", str(baud), "read_flash", hex(offset), hex(size), out]
        subprocess.run(cmd, check=True)
        with open(out, "rb") as f:
            return f.read()

def fetch_config(esptool, chip="esp32s3", port=None, baud=460800):
    """Read the config saved on the pad. None means there isn't one yet."""
    table = read_flash(esptool, chip, port, baud, PARTITION_TABLE_OFFSET, PARTITION_TABLE_SIZE)
    part = find_fs_partition(table)
    if not part:
        raise RuntimeError("no LittleFS partition in the pad's partition table")
    return extract_config(read_flash(esptool, chip, port, baud, *part))

def save_backup(config, backup_dir, keep=KEEP_BACKUPS):
    """Write a timestamped gzipped copy, keep only the newest `keep`, and
    return its path. Raises if it isn't JSON."""
    json.loads(config.decode("utf-8"))
    os.makedirs(backup_dir, exist_ok=True)
    path = os.path.join(backup_dir, time.strftime("macros-%Y%m%d-%H%M%S.json.gz"))
    with open(path, "wb") as f:
        f.write(gzip.compress(config, 9))
    for old in sorted(glob.glob(os.path.join(backup_dir, "macros-*.json*")))[:-keep]:
        os.remove(old)
    return path

def load_backup(path):
    """Read a backup (.json.gz or plain .json). Raises if it isn't JSON."""
    with open(path, "rb") as f:
        config = f.read()
    if path.endswith(".gz"):
        config = gzip.decompress(config)
    json.loads(config.decode("utf-8"))
    return config

def selftest():
    row = lambda t, s, off, size, label: struct.pack("<HBBII16sI", 0x50AA, t, s, off, size, label, 0)
    table = (row(0, 0x10, 0x10000, 0x140000, b"app0") + row(1, 0x02, 0x9000, 0x5000, b"nvs") +
             row(1, 0x82, 0x290000, 0x160000, b"spiffs") + b"\xff" * 32)
    assert find_fs_partition(table) == (0x290000, 0x160000)
    assert find_fs_partition(struct.pack("<HBBII", 0xEBEB, 0, 0, 0, 0).ljust(32, b"\0") + table) == (0x290000, 0x160000)
    assert find_fs_partition(b"\xff" * 64) is None
    with tempfile.TemporaryDirectory() as tmp:
        path = save_backup(b'{"layers":[]}', tmp)
        assert os.path.basename(path).startswith("macros-") and load_backup(path) == b'{"layers":[]}'
        for i in range(7):             # only the newest KEEP_BACKUPS stay
            open(os.path.join(tmp, "macros-2000010%d-000000.json" % i), "w").write("{}")
        newest = save_backup(b"{}", tmp)
        kept = sorted(os.listdir(tmp))
        assert len(kept) == KEEP_BACKUPS and kept[-1] == os.path.basename(newest)
        try:
            save_backup(b"not json", tmp); raise AssertionError("invalid JSON was saved")
        except ValueError:
            pass
    try:
        from littlefs import LittleFS
    except ImportError:
        print("selftest passed (LittleFS extraction skipped: pip install littlefs-python)")
        return
    fs = LittleFS(block_size=FS_BLOCK_SIZE, block_count=16, read_size=256, prog_size=256)
    with fs.open(CONFIG_NAME, "wb") as f:
        f.write(b'{"version":2}')
    assert extract_config(bytes(fs.context.buffer)) == b'{"version":2}'
    assert extract_config(b"\xff" * FS_BLOCK_SIZE * 16) is None
    print("selftest passed")

def main():
    ap = argparse.ArgumentParser(description="Back up the config saved on the pad over USB.")
    ap.add_argument("command", nargs="?", choices=["backup"])
    ap.add_argument("--port", help="serial port (default: let esptool find it)")
    ap.add_argument("--baud", type=int, default=460800)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backups"),
                    help="backup folder (default: backups/ in the repo)")
    ap.add_argument("--selftest", action="store_true", help="run built-in tests and exit")
    a = ap.parse_args()
    if a.selftest:
        selftest(); return
    if a.command != "backup":
        ap.error("choose a command: backup")
    config = fetch_config([sys.executable, "-m", "esptool"], port=a.port, baud=a.baud)
    if config is None:
        sys.exit("No saved config on the pad yet - nothing to back up.")
    print("Saved", os.path.normpath(save_backup(config, a.out)))

if __name__ == "__main__":
    main()
