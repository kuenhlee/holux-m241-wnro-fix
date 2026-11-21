#!/usr/bin/env python3
"""Read-only probe for the Holux M-241 Boot ROM read path. NEVER writes.

Put this in the repo's scripts folder (next to mtk_proto.py) and run:
    python scripts/probe_read.py COM3 --header firmware/original/m241_header.bin
Put the device in the state dump_firmware.py needs (it resets it itself).
"""
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from mtk_proto import BASE_ADDR_FIRMWARE, MtkBootRom

def show(b, n=32):
    b = bytes(b)
    return b[:n].hex(" ") + ("" if len(b) <= n else " ...")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("port")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--base-addr", type=lambda x: int(x, 0), default=0x200000)
    p.add_argument("--fw-size", type=lambda x: int(x, 0), default=406616)
    p.add_argument("--header", type=Path, help="known-good 512-byte header dump to compare against")
    a = p.parse_args()

    brom = MtkBootRom(a.port, baud=a.baud, nmea_baud=None)
    print("[*] entering Boot ROM (~10s)...")
    brom.start()
    print("[*] Boot ROM ready\n")
    B = a.base_addr
    ok_all = True

    def rd(addr, n, swap=True):
        return bytes(brom.read(addr, n, byte_swap=swap))

    def check(name, addr, n, expect=None):
        nonlocal ok_all
        for swap in (True, False):
            try:
                d = rd(addr, n, swap)
            except Exception as e:
                print(f"[{name}] 0x{addr:08x} swap={swap}: ERROR {e}")
                continue
            tag = ""
            if expect is not None:
                good = d == expect
                tag = "  PASS" if good else "  FAIL"
                if swap and not good:
                    ok_all = False
            print(f"[{name}] 0x{addr:08x} swap={swap}: {show(d)}{tag}")
            if expect is not None and swap is True and d == expect:
                break  # swap=True is what dump_firmware uses; no need to show the other

    print("--- 1. known bytes from your own header dump (base 0x%x) ---" % B)
    check("vector table ", B + 0x00, 8,  bytes.fromhex("18f09fe518f09fe5"))
    check("magic string ", B + 0x60, 16, b"THIS CODE is OK!")
    check("family string", B + 0x90, 11, b"HOLUX_M-241")
    check("fw_size @F4  ", B + 0xF4, 4,  a.fw_size.to_bytes(4, "little"))
    check("release name ", B + 0x148, 6, b"B-core")

    print("\n--- 2. the address the failed full dump used (default BASE_ADDR_FIRMWARE) ---")
    print(f"BASE_ADDR_FIRMWARE = 0x{BASE_ADDR_FIRMWARE:08x}")
    check("default base ", BASE_ADDR_FIRMWARE, 16)

    print("\n--- 3. chunk-size consistency (one 256B read vs 16x16B reads) ---")
    big = rd(B + 0x400, 0x100)
    small = b"".join(rd(B + 0x400 + i, 16) for i in range(0, 0x100, 16))
    print("consistent:", big == small, "|", show(big, 16))
    ok_all &= big == small

    print("\n--- 4. data must vary across the image (not a constant fill) ---")
    for off in (0x1000, 0x10000, 0x402F4, 0x59C28, a.fw_size - 16):
        d = rd(B + off, 16)
        const = len(set(d[i:i+4] for i in range(0, 16, 4))) == 1
        print(f"  +0x{off:06x}: {show(d)}{'   <-- constant fill?' if const else ''}")

    if a.header:
        ref = a.header.read_bytes()
        got = rd(B, len(ref))
        same = got == ref
        print(f"\n--- 5. {len(ref)}-byte compare with {a.header.name}: {'IDENTICAL' if same else 'DIFFERENT'}")
        ok_all &= same

    print("\n--- 6. memory map (read-only; run last, an unmapped read may desync the link) ---")
    for label, addr in (("0x00000000 (author's MT3318 flash base)", 0x0),
                        ("0x00000c00 (upstream DA load)", 0xC00),
                        ("0x00100000 (BootROM scratch)", 0x100000),
                        ("0x00100800 (DA load used by repo)", 0x100800),
                        ("0x00200000 (your flash)", 0x200000),
                        ("0x00270000", 0x270000),
                        ("0x00280000 (end of 512KB flash?)", 0x280000),
                        ("0x20000000 (upstream MT333x flash)", 0x20000000)):
        try:
            d = rd(addr, 16)
            print(f"  {label:42s}: {show(d)}")
        except Exception as e:
            print(f"  {label:42s}: ERROR {e}")
            break

    print("\nRESULT:", "read path looks good" if ok_all else "read path is NOT trustworthy - do not dump/flash")
    print("[*] please RESET the device to exit Boot ROM mode")
    return 0 if ok_all else 1

if __name__ == "__main__":
    sys.exit(main())
