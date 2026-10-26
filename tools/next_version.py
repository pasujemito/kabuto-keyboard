#!/usr/bin/env python3
"""
next_version.py - pick the version for an automatic release.

FIRMWARE_VERSION in src/config.h is the base you control. Releases use it as
is the first time, then count the patch number up: 1.14.0, 1.14.1, 1.14.2...
Raise the base (e.g. to 1.15.0) for a bigger step. A base that would release
something older than an existing tag is refused, since pads would offer it as
a downgrade instead of an update.

Usage:
    python tools/next_version.py 1.14.0 v1.14.0 v1.14.1     # prints 1.14.2
    python tools/next_version.py --selftest
"""
import re, sys

TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")

def parse(version):
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
    if not m:
        raise SystemExit("FIRMWARE_VERSION %r isn't MAJOR.MINOR.PATCH" % version)
    return tuple(int(x) for x in m.groups())

def next_version(base, tags):
    released = sorted(tuple(int(x) for x in m.groups()) for m in map(TAG.match, tags) if m)
    major, minor, patch = parse(base)
    same_line = [v[2] for v in released if v[:2] == (major, minor)]
    candidate = (major, minor, patch)
    if candidate in released:
        candidate = (major, minor, max(same_line) + 1)
    if released and candidate <= released[-1]:
        raise SystemExit("FIRMWARE_VERSION %s is behind the released v%s - raise it in src/config.h"
                         % (base, ".".join(map(str, released[-1]))))
    return ".".join(map(str, candidate))

def selftest():
    assert next_version("1.14.0", []) == "1.14.0"
    assert next_version("1.14.0", ["v1.14.0"]) == "1.14.1"
    assert next_version("1.14.0", ["v1.14.0", "v1.14.1", "v1.14.9", "v1.14.10"]) == "1.14.11"
    assert next_version("1.15.0", ["v1.14.0", "v1.14.3"]) == "1.15.0"
    assert next_version("1.14.7", ["v1.14.0", "v1.14.3"]) == "1.14.7"           # a manual jump is kept
    assert next_version("1.14.0", ["v1.14.0", "v1.14.2-test", "other"]) == "1.14.1"
    for base, tags in (("1.13.0", ["v1.14.0"]), ("1.14.2", ["v1.14.0", "v1.14.5"])):
        try:
            next_version(base, tags); raise AssertionError("released an older version")
        except SystemExit:
            pass
    print("selftest passed")

if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        selftest()
    elif len(sys.argv) >= 2:
        print(next_version(sys.argv[1], sys.argv[2:]))
    else:
        sys.exit(__doc__)
