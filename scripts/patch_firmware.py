#!/usr/bin/env python3
"""Apply WNRO + version patches to a user-supplied M-241 firmware backup.

The user MUST first dump their own M-241 firmware using dump_firmware.py.
This script never includes proprietary firmware bytes; it just rewrites
specific offsets in the user's own backup.

Usage:
    python3 patch_firmware.py firmware/original/m241_dump.bin \\
        firmware/patched/m241_v114_wnro.bin

The input is a dump of the firmware image (first byte = ARM vector table). The
author's image is 0x70000 bytes; any dump >= the header fw_size works for patching.

WHAT THIS PATCHES:
  1. Unix-epoch offset (file 0x402f4): +619315200 seconds (= +1024 weeks)
     Compensates for the 2nd GPS Week Number Rollover (2019-04-06).
  2. OLED version string (file 0x59c2c): 'V1.13' -> 'V1.14'

Verified on Holux M-241 with v1.13 firmware (sha256 prefix b832).
"""
from __future__ import annotations

import argparse
import hashlib
import struct
import sys
from pathlib import Path


# ---- Patch table ----------------------------------------------------------

EXPECTED_SHA256_PREFIX = "b83204e0cb4a1daa"

PATCHES = [
    {
        "offset": 0x402F4,
        "size": 4,
        "old": 315964800,        # = 0x12D53D80 (Unix time at GPS epoch 1980-01-06)
        "new": 935280000,        # = 0x37BF3D80 (= 315964800 + 619315200)
        "description": "WNRO fix: shift Unix epoch base forward by +1024 weeks (= +7168 days)",
    },
    {
        "offset": 0x59C2C,
        "size": 1,
        "old": 0x33,             # ASCII '3'
        "new": 0x34,             # ASCII '4'
        "description": "OLED version string: V1.13 -> V1.14",
    },
]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("input",  type=Path, help="User's M-241 firmware backup")
    p.add_argument("output", type=Path, help="Output patched firmware path")
    args = p.parse_args()

    if not args.input.exists():
        print(f"[!] input not found: {args.input}", file=sys.stderr)
        return 1
    fw = bytearray(args.input.read_bytes())
    orig = bytes(fw)

    # Structural checks instead of a fixed size / sha256 of the author's own dump.
    # (The author's image is 0x70000 bytes; a header-sized dump is 0x63458. Both are
    #  fine for patching, but the flasher needs a multiple of 0x100 - see flash_firmware.py.)
    if len(fw) < 0x59C30:
        print(f"[!] file too small ({len(fw)} bytes)", file=sys.stderr)
        return 2
    if fw[0x60:0x70] != b"THIS CODE is OK!" or fw[0x90:0x9B] != b"HOLUX_M-241":
        print("[!] header magic / family string not found - not an M-241 image "
              "(wrong --base-addr?)", file=sys.stderr)
        return 3
    fw_size = struct.unpack_from("<L", fw, 0xF4)[0]
    if len(fw) < fw_size:
        print(f"[!] file ({len(fw)}) is shorter than fw_size in header ({fw_size})", file=sys.stderr)
        return 3
    if fw[0x59C28:0x59C2D] != b"V1.13":
        print(f"[!] expected b'V1.13' at 0x59c28, got {bytes(fw[0x59C28:0x59C2D])!r} "
              "- different firmware version", file=sys.stderr)
        return 3

    sha = hashlib.sha256(orig).hexdigest()
    print(f"  input: {len(fw)} bytes, fw_size(header)={fw_size}, sha256={sha}")
    if sha.startswith(EXPECTED_SHA256_PREFIX):
        print("  (sha256 matches the author's verified image)")
    else:
        print("  (sha256 differs from the author's image - expected for a different dump length / unit;")
        print("   the structural checks above are what matter)")

    print()
    print(f"  applying {len(PATCHES)} patches:")
    for patch in PATCHES:
        off = patch["offset"]
        size = patch["size"]
        if size == 4:
            actual = struct.unpack("<I", fw[off:off + 4])[0]
            old_str = f"0x{patch['old']:08x}"
            new_str = f"0x{patch['new']:08x}"
        else:
            actual = fw[off]
            old_str = f"0x{patch['old']:02x}"
            new_str = f"0x{patch['new']:02x}"

        if actual != patch["old"]:
            # The original script skipped and still wrote an output file. Abort instead.
            print(f"  [!] file 0x{off:x}: expected {old_str}, got 0x{actual:x} - ABORTING, nothing written",
                  file=sys.stderr)
            return 4

        if size == 4:
            fw[off:off + 4] = struct.pack("<I", patch["new"])
        else:
            fw[off] = patch["new"]
        print(f"     file 0x{off:06x} {old_str} -> {new_str}  ({patch['description']})")

    diff = [i for i in range(len(fw)) if fw[i] != orig[i]]
    print(f"\n  changed bytes: {[hex(i) for i in diff]}")
    allowed = {0x402F6, 0x402F7, 0x59C2C}
    if set(diff) != allowed:
        print(f"[!] unexpected diff, expected exactly {[hex(i) for i in sorted(allowed)]}", file=sys.stderr)
        return 5

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(bytes(fw))
    out_sha = hashlib.sha256(bytes(fw)).hexdigest()
    print()
    print(f"  output: {args.output}")
    print(f"  output sha256: {out_sha}")
    print()
    print("  next: flash with flash_firmware.py. KEEP YOUR ORIGINAL BACKUP.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
