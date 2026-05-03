#!/usr/bin/env python3
"""Stage 6: Holux M-241 にパッチ済みファームウェアを書き込む。

**破壊的・不可逆**。Stage 0-5 を完了し、以下が満たされてから実行すること:
- Stage 2 でオリジナルファームを2回ダンプして SHA256 一致を確認
- Stage 3 でパッチ箇所を特定
- Stage 4 で NMEA プロキシによる補正ロジックの動作確認
- Stage 5 でパッチ済みファームをエミュレータで検証

使い方:
    python3 scripts/flash_firmware.py /dev/tty.SLAB_USBtoUART \\
        --da firmware/agents/MTK_AllInOne_DA_MT3329_v4.02.bin \\
        --fw firmware/patched/v1.13_wnro_fix.bin \\
        --i-have-backup firmware/original/dump.bin
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
        default=0,
        help="書込先 base アドレス (Holux M-241 のメインファームは 0x200000)",
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
        brom.start(use_rts_dtr=False, autoboot_polling=False)
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
