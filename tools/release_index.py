#!/usr/bin/env python3
"""
release_index.py - sign a firmware build and add it to the release list.

The release workflow (.github/workflows/release.yml) runs this after building.
Each GitHub release carries versions.json, the signed list of recent releases
every pad reads (newest first) to offer updates and older versions:

    {"versions": [{"version": "1.14.0", "date": "2026-10-27", "size": 1234567,
                   "sha256": "...", "signature": "..."}, ...]}

Each signature is ECDSA P-256 over "version\\nsize\\nsha256\\n" (manifestPayload
in src/update_logic.h). Pads only list and install entries whose signature
matches update_public_key.pem, which is built into their firmware.

Usage:
    python tools/release_index.py firmware.bin --version 1.14.0 --date 2026-10-27 \\
        --key signing-key.pem --public update_public_key.pem \\
        --previous old/versions.json --out versions.json
    python tools/release_index.py --selftest     # needs the openssl CLI
"""
import argparse, base64, hashlib, json, os, subprocess, tempfile

KEEP_VERSIONS = 20      # keeps versions.json a few KB for the pad to parse

def payload(version, size, sha256_hex):
    return ("%s\n%d\n%s\n" % (version, size, sha256_hex)).encode()

def openssl(*args, data=None):
    return subprocess.run(["openssl", *args], input=data, check=True, capture_output=True).stdout

def verify(data, signature, public_path):
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(signature)
    try:
        subprocess.run(["openssl", "dgst", "-sha256", "-verify", public_path, "-signature", f.name],
                       input=data, check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError:
        return False
    finally:
        os.remove(f.name)

def make_entry(firmware, version, date, key_path, public_path):
    with open(firmware, "rb") as f:
        image = f.read()
    sha = hashlib.sha256(image).hexdigest()
    body = payload(version, len(image), sha)
    signature = openssl("dgst", "-sha256", "-sign", key_path, data=body)
    # Catch a secret that doesn't match the committed public key before
    # publishing: pads would ignore every release signed with it.
    if public_path and not verify(body, signature, public_path):
        raise SystemExit("Signature doesn't match %s - the signing key secret and the "
                         "committed public key are from different pairs." % public_path)
    return {"version": version, "date": date, "size": len(image), "sha256": sha,
            "signature": base64.b64encode(signature).decode()}

def build_index(entry, previous_path=None, keep=KEEP_VERSIONS):
    older = []
    if previous_path and os.path.exists(previous_path):
        with open(previous_path) as f:
            older = [v for v in json.load(f).get("versions", []) if v.get("version") != entry["version"]]
    return {"versions": ([entry] + older)[:keep]}

def selftest():
    # Must match manifestPayload() in src/update_logic.h (tests/update_logic.cpp pins the same string).
    assert payload("1.14.0", 1234, "f" * 64) == b"1.14.0\n1234\n" + b"f" * 64 + b"\n"
    with tempfile.TemporaryDirectory() as tmp:
        key, pub, other = (os.path.join(tmp, n) for n in ("key.pem", "pub.pem", "other.pem"))
        openssl("ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", key)
        openssl("ec", "-in", key, "-pubout", "-out", pub)
        openssl("ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", other)
        fw = os.path.join(tmp, "firmware.bin")
        with open(fw, "wb") as f:
            f.write(os.urandom(4096))
        e = make_entry(fw, "1.14.0", "2026-10-27", key, pub)
        sig = base64.b64decode(e["signature"])
        assert verify(payload("1.14.0", 4096, e["sha256"]), sig, pub)
        assert not verify(payload("9.9.9", 4096, e["sha256"]), sig, pub)   # version is signed
        try:
            make_entry(fw, "1.14.0", "2026-10-27", other, pub); raise AssertionError("mismatched key accepted")
        except SystemExit:
            pass
        # Newest first, a re-released version replaces its old entry, capped length.
        prev = os.path.join(tmp, "versions.json")
        with open(prev, "w") as f:
            json.dump({"versions": [{"version": "1.%d.0" % i} for i in range(13, -1, -1)] + [{"version": "1.14.0"}]}, f)
        idx = build_index(e, prev, keep=5)["versions"]
        assert [v["version"] for v in idx] == ["1.14.0", "1.13.0", "1.12.0", "1.11.0", "1.10.0"] and idx[0] is e
        assert build_index(e)["versions"] == [e]
    print("selftest passed")

def main():
    ap = argparse.ArgumentParser(description="Sign a firmware build and write versions.json.")
    ap.add_argument("firmware", nargs="?")
    ap.add_argument("--version")
    ap.add_argument("--date", help="release date shown on the pad, e.g. 2026-10-27")
    ap.add_argument("--key", help="ECDSA P-256 private key (PEM)")
    ap.add_argument("--public", help="public key to check the signature against before writing")
    ap.add_argument("--previous", help="versions.json from the previous release, if any")
    ap.add_argument("--out", default="versions.json")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest(); return
    if not (a.firmware and a.version and a.key):
        ap.error("firmware, --version and --key are required")
    index = build_index(make_entry(a.firmware, a.version, a.date or "", a.key, a.public), a.previous)
    with open(a.out, "w") as f:
        json.dump(index, f)
    print("Wrote %s (%d versions)" % (a.out, len(index["versions"])))

if __name__ == "__main__":
    main()
