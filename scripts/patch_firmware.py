#!/usr/bin/env python3
"""Apply WNRO + version patches to a user-supplied M-241 firmware backup.

The user MUST first dump their own M-241 firmware using dump_firmware.py.
This script never includes proprietary firmware bytes; it just rewrites
specific offsets in the user's own backup.

Usage:
    python3 patch_firmware.py firmware/original/m241_dump.bin \\
        firmware/patched/m241_v114_wnro.bin

The expected input is a 458752-byte (= 0x70000) flash image starting at
flash offset 0 (matches what dump_firmware.py produces).

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

EXPECTED_SIZE = 458752  # 0x70000 bytes
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
    p.add_argument("input",  type=Path, help="User's M-241 firmware backup (458752 bytes)")
    p.add_argument("output", type=Path, help="Output patched firmware path")
    p.add_argument("--no-verify", action="store_true",
                   help="Skip SHA256 prefix check (use at own risk)")
    args = p.parse_args()

    if not args.input.exists():
        print(f"[!] input not found: {args.input}", file=sys.stderr)
        return 1
    fw = bytearray(args.input.read_bytes())

    if len(fw) != EXPECTED_SIZE:
        print(
            f"[!] unexpected size: {len(fw)} bytes "
            f"(expected {EXPECTED_SIZE})",
            file=sys.stderr,
        )
        return 2

    sha = hashlib.sha256(bytes(fw)).hexdigest()
    print(f"  input sha256: {sha}")
    if not args.no_verify and not sha.startswith(EXPECTED_SHA256_PREFIX):
        print(
            f"[!] sha256 prefix mismatch (expected {EXPECTED_SHA256_PREFIX}*)",
            file=sys.stderr,
        )
        print(
            "    This script is verified against the v1.13 firmware shipped with Holux M-241.\n"
            "    A different prefix means the firmware version differs - patch offsets may not match.\n"
            "    Pass --no-verify to override (use only if you know what you are doing).",
            file=sys.stderr,
        )
        return 3

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
            print(
                f"  [!] file 0x{off:x}: expected {old_str}, got 0x{actual:x} - SKIPPING",
                file=sys.stderr,
            )
            continue

        if size == 4:
            fw[off:off + 4] = struct.pack("<I", patch["new"])
        else:
            fw[off] = patch["new"]
        print(f"     file 0x{off:06x} {old_str} -> {new_str}  ({patch['description']})")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(bytes(fw))
    out_sha = hashlib.sha256(bytes(fw)).hexdigest()
    print()
    print(f"  output: {args.output}")
    print(f"  output sha256: {out_sha}")
    print()
    print(
        "  next: flash the patched image with flash_firmware.py.\n"
        "  KEEP YOUR ORIGINAL BACKUP. If anything goes wrong, you can\n"
        "  re-flash the unpatched dump to restore."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
