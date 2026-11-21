#!/usr/bin/env python3
"""Holux M-241 firmware dumper (read-only, safe).

Reads the M-241 SPI flash via the MTK BootROM protocol and writes it to
a file. **No writes ever.** The dump is performed twice and SHA256 of the
two passes is compared as a stability check.

Usage:
    python3 scripts/dump_firmware.py /dev/tty.usbserial-0001 m241_dump.bin

Options:
    --header-only   only the first 0x200 bytes (firmware metadata)
    --length N      explicit byte length (default: read from header)
    --no-verify     skip the 2nd dump pass (NOT recommended)
    --nmea-baud N   the device's current NMEA baud (only set if auto fails)
"""
from __future__ import annotations

import argparse
import hashlib
import struct
import sys
import time
from pathlib import Path

import serial  # noqa: F401  # pyserial の存在チェック

sys.path.insert(0, str(Path(__file__).parent))
from mtk_proto import (  # noqa: E402
    BASE_ADDR_FIRMWARE,
    BootRomError,
    MtkBootRom,
    parse_fw_header,
)


def dump_once(
    port: str,
    length: int | None,
    *,
    baud: int,
    nmea_baud: int | None,
    base_addr: int,
    no_swap: bool,
    skip_brom_start: bool = False,
) -> bytes:
    print(f"[*] open {port} @ {baud}", flush=True)
    brom = MtkBootRom(port, baud=baud, nmea_baud=nmea_baud)

    if skip_brom_start:
        print("[*] using existing Boot ROM session (skip start)", flush=True)
    else:
        print("[*] entering Boot ROM mode (this can take ~10s)...", flush=True)
        brom.start()
        print("[*] Boot ROM ready", flush=True)

    if length is None:
        # MT333x format: header at base+0xf4 has fw size. 0 = invalid.
        size_bytes = brom.read32(base_addr + 0xF4, 4)
        length = struct.unpack(">L", size_bytes)[0]
        if length == 0 or length > 0x400000:
            raise RuntimeError(
                f"firmware size from header is invalid (0x{length:x}). "
                "Specify --length manually (e.g. --length 0x100000 for 1MB)."
            )
        print(f"[*] firmware size from header: {length} (0x{length:x})", flush=True)

    out = bytearray()
    addr = base_addr
    remaining = length
    last_pct = -1
    started = time.time()
    while remaining:
        chunk = min(0x100, remaining)
        data = brom.read(addr, chunk, byte_swap=not no_swap)
        out.extend(data)
        addr += chunk
        remaining -= chunk
        pct = int((length - remaining) * 100 / length)
        if pct != last_pct:
            elapsed = time.time() - started
            sys.stdout.write(
                f"\r    {pct:3d}%  {length - remaining}/{length}  ({elapsed:.1f}s)"
            )
            sys.stdout.flush()
            last_pct = pct
    print()

    return bytes(out)


def looks_like_firmware(data: bytes) -> bool:
    """Reject constant fills: real firmware has many distinct 4-byte words."""
    words = {data[i:i + 4] for i in range(0, len(data) - 3, 4)}
    return len(words) > max(4, len(data) // 4096)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("port")
    p.add_argument("output", type=Path)
    p.add_argument("--header-only", action="store_true")
    p.add_argument("--length", type=lambda x: int(x, 0))
    p.add_argument("--no-verify", action="store_true")
    p.add_argument("--baud", type=int, default=115200, help="Boot ROM baud (default 115200)")
    p.add_argument("--nmea-baud", type=int, default=None, help="現 NMEA baud (default: auto)")
    p.add_argument(
        "--base-addr",
        type=lambda x: int(x, 0),
        default=BASE_ADDR_FIRMWARE,
        help=f"firmware base address (default 0x{BASE_ADDR_FIRMWARE:08x} for MT333x; "
        "use 0x00000000 for MT3318)",
    )
    p.add_argument(
        "--no-swap",
        action="store_true",
        help="32bit byte swap を行わない（MT3318 等で必要かも、要実験）",
    )
    p.add_argument(
        "--assume-brom",
        action="store_true",
        help="既に Boot ROM モードに居る前提で start() をスキップ",
    )
    args = p.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)

    length = 0x200 if args.header_only else args.length

    print("===== DUMP #1 =====")
    try:
        first = dump_once(
            args.port, length,
            baud=args.baud, nmea_baud=args.nmea_baud,
            base_addr=args.base_addr, no_swap=args.no_swap,
            skip_brom_start=args.assume_brom,
        )
    except (BootRomError, RuntimeError, serial.SerialException) as e:
        print(f"[!] dump failed: {e}", file=sys.stderr)
        return 1

    if not looks_like_firmware(first):
        print(
            "[!] dump looks like a constant/garbage fill, not firmware. "
            "Wrong --base-addr? (header dump used --base-addr 0x200000). Not saving.",
            file=sys.stderr,
        )
        return 4

    h1 = hashlib.sha256(first).hexdigest()
    print(f"[+] dump #1: {len(first)} bytes, sha256={h1}")

    args.output.write_bytes(first)
    print(f"[+] saved to {args.output}")

    if args.no_verify:
        print("[*] skipping verification (--no-verify)")
    else:
        print()
        print("[*] please RESET the device (power-cycle), then press ENTER for verify dump")
        try:
            input()
        except EOFError:
            pass

        print("===== DUMP #2 (verify) =====")
        try:
            second = dump_once(
                args.port, len(first),
                baud=args.baud, nmea_baud=args.nmea_baud,
                base_addr=args.base_addr, no_swap=args.no_swap,
            )
        except (BootRomError, RuntimeError, serial.SerialException) as e:
            print(f"[!] verify dump failed: {e}", file=sys.stderr)
            print("    first dump is preserved at:", args.output)
            return 2
        h2 = hashlib.sha256(second).hexdigest()
        print(f"[+] dump #2: {len(second)} bytes, sha256={h2}")
        if h1 != h2:
            mismatch = sum(a != b for a, b in zip(first, second))
            args.output.with_suffix(".second.bin").write_bytes(second)
            print(
                f"[!] HASHES DIFFER ({mismatch} bytes mismatched). "
                f"Second dump saved as {args.output.with_suffix('.second.bin')}",
                file=sys.stderr,
            )
            return 3
        print("[+] dumps match (read is stable)")

    # ヘッダ解析
    print()
    print("===== HEADER ANALYSIS =====")
    try:
        info = parse_fw_header(first[: 0xA00 if len(first) >= 0xA00 else 0x200])
        for k, v in info.items():
            print(f"    {k}: {v!r}")
    except Exception as e:
        print(f"[!] header parse failed: {e}")

    print()
    print("[*] please RESET the device to exit Boot ROM mode")
    return 0


if __name__ == "__main__":
    sys.exit(main())
