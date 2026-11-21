#!/usr/bin/env python3
"""Holux M-241 firmware flasher.

**DESTRUCTIVE AND IRREVERSIBLE.** This script writes a firmware image to
the M-241's SPI flash via the MTK Download Agent (DA). Before running:
  1. Dump your original firmware twice with dump_firmware.py and verify
     both SHA256 hashes match.
  2. Keep that backup somewhere safe.
  3. Read DISCLAIMER.md.

Usage:
    python3 scripts/flash_firmware.py /dev/tty.usbserial-0001 \\
        --da firmware/agents/DA_v3.8.4.bin \\
        --fw firmware/patched/m241_v114_wnro.bin \\
        --i-have-backup firmware/original/m241_dump.bin \\
        --start-addr 0x0 --yes

If anything goes wrong mid-flash, re-flash the original backup with the
same command, swapping --fw to point at it.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import time
from pathlib import Path

import serial

sys.path.insert(0, str(Path(__file__).parent))
from mtk_proto import (  # noqa: E402
    BootRomError,
    DownloadAgent,
    DownloadAgentError,
    MtkBootRom,
)


WARNING_BANNER = """
=============================================================
                      ⚠  DESTRUCTIVE ACTION  ⚠
        この操作は MTK チップの flash を上書きします。
        失敗するとデバイスは文鎮化する可能性があります。
=============================================================
"""


def progress(cnt: int, total: int) -> None:
    pct = int(cnt * 100 / total) if total else 100
    sys.stdout.write(f"\r    {pct:3d}%  {cnt}/{total}")
    sys.stdout.flush()
    if cnt == total:
        print()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("port")
    p.add_argument("--da", required=True, type=Path, help="MTK Download Agent バイナリ")
    p.add_argument("--fw", required=True, type=Path, help="書き込むファームウェア (パッチ済)")
    p.add_argument(
        "--i-have-backup",
        required=True,
        type=Path,
        help="バックアップ済オリジナルファームのパス（存在確認のみ）",
    )
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument(
        "--high-baud",
        type=int,
        default=None,
        choices=(230400, 460800, 912600),
        help="DA 起動後に切り替える高速 baud (任意)",
    )
    p.add_argument("--nmea-baud", type=int, default=None)
    p.add_argument(
        "--start-addr",
        type=lambda x: int(x, 0),
        required=True,
        help="DA write start address. UNVERIFIED for HW where BootROM maps flash at 0x200000 - "
        "do not guess; see notes. (docs example uses 0x0)",
    )
    p.add_argument(
        "--legacy-start",
        action="store_true",
        help="original behaviour: PMTK180 at several bauds, no RTS/DTR pulse. "
        "Default now matches dump_firmware.py (RTS/DTR pulse), which works on this unit.",
    )
    p.add_argument(
        "--info-only",
        action="store_true",
        help="load the DA, print flash info, restart. Never writes flash (still loads the DA into RAM).",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="確認プロンプトをスキップ（自動化用、通常は使わない）",
    )
    args = p.parse_args()

    # 入力ファイル検証
    for label, path in (("DA", args.da), ("FW", args.fw), ("BACKUP", args.i_have_backup)):
        if not path.exists():
            print(f"[!] {label} not found: {path}", file=sys.stderr)
            return 1

    fw_data = args.fw.read_bytes()
    backup_size = args.i_have_backup.stat().st_size
    fw_sha = hashlib.sha256(fw_data).hexdigest()
    backup_sha = hashlib.sha256(args.i_have_backup.read_bytes()).hexdigest()

    backup_data = args.i_have_backup.read_bytes()
    if not args.info_only:
        if len(fw_data) != len(backup_data):
            print(f"[!] FW ({len(fw_data)}) and backup ({len(backup_data)}) differ in size", file=sys.stderr)
            return 1
        if len(fw_data) % 0x100:
            print(f"[!] FW length {len(fw_data)} is not a multiple of 0x100 (DA packet size); "
                  "the last short packet would stall the DA. Re-dump with --length 0x70000.", file=sys.stderr)
            return 1
        diff = [i for i in range(len(fw_data)) if fw_data[i] != backup_data[i]]
        print(f"  bytes differing from backup: {[hex(i) for i in diff]}")
        if not set(diff) <= {0x402F6, 0x402F7, 0x59C2C} or len(diff) not in (0, 3):
            print("[!] FW must be either identical to the backup (identity test) or differ "
                  "by exactly the 3 expected bytes", file=sys.stderr)
            return 1
        print("  mode: " + ("IDENTITY TEST (rewrites the original image unchanged)" if not diff
                            else "PATCH (3 bytes changed)"))

    print(WARNING_BANNER)
    print(f"  port:       {args.port}")
    print(f"  DA:         {args.da}")
    print(f"  FW (write): {args.fw} ({len(fw_data)} bytes, sha256={fw_sha[:16]}...)")
    print(f"  Backup:     {args.i_have_backup} ({backup_size} bytes, sha256={backup_sha[:16]}...)")
    print(f"  Start addr: 0x{args.start_addr:08x}")
    if args.high_baud:
        print(f"  High baud:  {args.high_baud}")
    print()

    if not args.yes:
        print("Type 'WRITE' (uppercase) to proceed, anything else aborts:")
        try:
            answer = input("> ").strip()
        except EOFError:
            answer = ""
        if answer != "WRITE":
            print("[*] aborted")
            return 0

    # 実行
    print()
    print("[*] entering Boot ROM mode...")
    brom = MtkBootRom(args.port, baud=args.baud, nmea_baud=args.nmea_baud)
    try:
        # legacy mt3301 mode: PMTK180 で Boot ROM 移行 (RTS/DTR pulse 無効)
        if args.legacy_start:
            brom.start(use_rts_dtr=False, autoboot_polling=False)
        else:
            brom.start()
    except BootRomError as e:
        print(f"[!] could not enter Boot ROM: {e}", file=sys.stderr)
        return 2

    print("[*] loading Download Agent...")
    da = DownloadAgent(brom)
    da.set_progress(progress)
    try:
        da.start(str(args.da))
    except (BootRomError, DownloadAgentError) as e:
        print(f"[!] DA load failed: {e}", file=sys.stderr)
        return 3

    print()
    print(f"    DA version:        0x{da.info['da_version']:04x}")
    print(f"    Flash device id:   0x{da.info['flash_device_id']:02x}")
    print(f"    Flash size:        {da.info['flash_size']}")
    print(f"    Manufacturer code: 0x{da.info['flash_manufacturer_code']:04x}")
    print(f"    Device code:       0x{da.info['flash_device_code']:04x}")

    if da.info["flash_size"] and len(fw_data) > da.info["flash_size"]:
        print(
            f"[!] firmware ({len(fw_data)}) larger than flash ({da.info['flash_size']})",
            file=sys.stderr,
        )
        return 4

    if args.info_only:
        print("[*] --info-only: not writing. sending DA restart")
        da.restart()
        return 0

    if args.high_baud:
        print(f"[*] switching to {args.high_baud} baud")
        try:
            da.set_baud_rate(args.high_baud)
        except DownloadAgentError as e:
            print(f"[!] baud switch failed: {e}", file=sys.stderr)
            return 5

    print(f"[*] writing firmware to start=0x{args.start_addr:08x}...")
    started = time.time()
    try:
        da.write_firmware(fw_data, start=args.start_addr)
    except (DownloadAgentError, serial.SerialException) as e:
        print(f"[!] WRITE FAILED at unknown offset: {e}", file=sys.stderr)
        print("    DEVICE STATE IS UNDEFINED. Try re-flashing the original backup.")
        return 6

    elapsed = time.time() - started
    print(f"[+] write complete in {elapsed:.1f}s")

    print("[*] sending DA restart")
    da.restart()

    print()
    print("==== NEXT STEPS ====")
    print("  1. 端末を一度 OFF/ON してください")
    print("  2. NMEA 出力で日付が正しいか確認: ")
    print(f"     screen {args.port} 38400")
    print("  3. 端末 OLED の表示も確認")
    print("  4. 屋外で衛星 fix が取れることを確認")
    return 0


if __name__ == "__main__":
    sys.exit(main())
