"""MTK GPS チップの Boot ROM / Download Agent プロトコル (Python 3)。

`dimhoff/mt333x-fw-utils` (Python 2) を読み解いて Python 3 で再実装したもの。
バイト列・型付け回り以外のプロトコル仕様は upstream と同じ。

read 系（dump 用）が動作確認の優先対象。write 系（flash）は破壊的なので
最後にチェック多めで叩く想定。

メモリマップ:
    0x00000c00  RAM スクラッチパッド（DA ロード先）
    0x20000000  SPI Flash（ファームウェア本体）
    0x80000000  レジスタ
    0xA0000000  ROM
"""
from __future__ import annotations

import struct
import time
from typing import Callable, Optional

import serial


BASE_ADDR_FIRMWARE = 0x20000000
# RTS+DTR を High にしてチップを fresh BootROM 状態にすれば、本来の 0x100000 ロード
# が成立する（はず）。トランポリン不要。
BASE_ADDR_DA = 0x00100800  # HoluxLoggerUtility の正規ロード先 (DA_SetStartAddr で渡される値)
# Holux M-241 専用 DA を優先（PowerFlash 汎用 v4.01 より相性が良い前提）
DEFAULT_DA_PATH_HOLUX = "firmware/agents/DA_v3.8.4.bin"


def checksum_xor16(data: bytes) -> int:
    """`data` を 2バイトずつ XOR した 16bit チェックサム。"""
    cksum = 0
    for i in range(0, len(data) & ~1, 2):
        cksum ^= struct.unpack_from(">H", data, i)[0]
    if len(data) % 2:
        cksum ^= data[-1] << 8
    return cksum


class BootRomError(RuntimeError):
    pass


class MtkBootRom:
    """MTK GPS チップ Boot ROM クライアント。

    `start()` で Boot ROM モードに突入させてから read/write/jump を呼ぶ。
    """

    def __init__(
        self,
        port: str,
        *,
        baud: int = 115200,
        nmea_baud: Optional[int] = None,
        dtr_reset: bool = False,
    ) -> None:
        self._ser = serial.Serial(
            port, baud, timeout=1, xonxoff=False, rtscts=False, dsrdtr=False
        )
        # Boot ROM 自体は 115200 までしか対応しない（DA は超えられる）
        self._baud = min(baud, 115200)
        self._nmea_baud = nmea_baud
        self._dtr_reset = dtr_reset

    @property
    def serial(self) -> serial.Serial:
        return self._ser

    # ---- セットアップ -----------------------------------------------------

    def start(self, use_rts_dtr: bool = True, autoboot_polling: bool = True) -> None:
        """NMEA モードから Boot ROM モードへ移行させる。

        AutoBoot モード:
          1. RTS+DTR を pulse して chip reset
          2. PMTK180 は送らず polling のみ
          3. brom.dll BRom_AutoBoot::StartCmd と同等
        """
        import sys
        if use_rts_dtr:
            # 完全 transition を作る: low → high → low → high
            print("  [setup] pulse RTS+DTR for chip reset", file=sys.stderr)
            self._ser.rts = False
            self._ser.dtr = False
            time.sleep(0.1)
            self._ser.rts = True
            self._ser.dtr = True
            time.sleep(0.3)  # chip reboot 待ち
        if not autoboot_polling and not self._dtr_reset:
            # legacy mt3301 mode: PMTK180 を投げる
            bauds = [self._nmea_baud] if self._nmea_baud else [
                115200, 57600, 38400, 19200, 14400, 9600, 4800
            ]
            for b in bauds:
                try:
                    self._ser.baudrate = b
                    self._ser.write(b"$PMTK180*3B\r\n")
                    self._ser.flush()
                    time.sleep(0.1)
                except Exception:
                    pass

        self._ser.baudrate = self._baud
        self._ser.timeout = 0.005

        # BOOT_ROM_START_CMD1: \xa0 を返事来るまで連投（最大10秒）
        deadline = time.time() + 10
        c = b""
        while not c or c[0] != 0x5F:
            self._ser.write(b"\xa0")
            self._ser.flush()
            c = self._ser.read(1)
            if time.time() > deadline:
                raise BootRomError("timeout @ BOOT_ROM_START_CMD1 (no \\x5f)")

        self._ser.timeout = 1

        for send, expect, name in (
            (b"\x0a", 0xF5, "CMD2"),
            (b"\x50", 0xAF, "CMD3"),
            (b"\x05", 0xFA, "CMD4"),
        ):
            self._ser.write(send)
            r = self._ser.read(1)
            if not r:
                raise BootRomError(f"timeout @ BOOT_ROM_START_{name}")
            if r[0] != expect:
                raise BootRomError(
                    f"unexpected response @ BOOT_ROM_START_{name}: 0x{r[0]:02x}"
                )

    # ---- 基本コマンド -----------------------------------------------------

    def read32(self, address: int, length: int, byte_swap: bool = False) -> bytes:
        """32bit 単位読み出し。`length` はバイト数 (4の倍数)。"""
        if address % 4:
            raise ValueError("address must be 32-bit aligned")
        if length % 4:
            raise ValueError("length must be a multiple of 4")
        self._cmd_with_addr_count(b"\xaf", address, length // 4)
        data = self._read_exact(length)
        cksum = self.checksum(address, length)
        if cksum != checksum_xor16(data):
            raise BootRomError(
                f"read32 checksum mismatch: {cksum:04x} != {checksum_xor16(data):04x}"
            )
        return _byteswap32(data) if byte_swap else data

    def read16(self, address: int, length: int, byte_swap: bool = False) -> bytes:
        if address % 2:
            raise ValueError("address must be 16-bit aligned")
        if length % 2:
            raise ValueError("length must be a multiple of 2")
        self._cmd_with_addr_count(b"\xa2", address, length // 2)
        data = self._read_exact(length)
        cksum = self.checksum(address, length)
        if cksum != checksum_xor16(data):
            raise BootRomError(
                f"read16 checksum mismatch: {cksum:04x} != {checksum_xor16(data):04x}"
            )
        return _byteswap16(data) if byte_swap else data

    def read(self, address: int, length: int, byte_swap: bool = False) -> bytes:
        """任意のオフセット・長さで読む。内部で 32bit アライメント整形。"""
        out = bytearray()
        # 先頭非整列分
        if address % 4:
            head = self.read32(address & ~0x3, 4, byte_swap)
            head = head[address % 4 :]
            take = min(len(head), length)
            out.extend(head[:take])
            address += take
            length -= take
        # 32bit 単位の本体（256B チャンク）
        while length >= 4:
            chunk = min(length & ~0x3, 0x100)
            out.extend(self.read32(address, chunk, byte_swap))
            address += chunk
            length -= chunk
        # 末尾非整列分
        if length:
            tail = self.read32(address, 4, byte_swap)
            out.extend(tail[:length])
        return bytes(out)

    def checksum(self, address: int, length: int, verify_echo: bool = True) -> int:
        if address % 2:
            raise ValueError("address must be 16-bit aligned")
        if length % 2:
            raise ValueError("length must be a multiple of 2")
        if verify_echo:
            self._cmd_with_addr_count(b"\xa4", address, length // 2)
        else:
            # bulk write 後など chip が echo 出さない場合: 送りっぱなし
            self._ser.write(b"\xa4")
            self._ser.write(struct.pack(">L", address))
            self._ser.write(struct.pack(">L", length // 2))
            self._ser.flush()
            import time as _t
            _t.sleep(0.1)  # chip 処理待ち
            self._ser.reset_input_buffer()  # 入力バッファクリア (echo bytes 捨てる)
            # チェックサム発行: 別の Boot ROM コマンドが必要
            # ここは「チップが生きてるか」確認だけのため、書込側だけ
            return 0  # cksum 値は使わない
        r = self._read_exact(2)
        return struct.unpack(">H", r)[0]

    def jump(self, address: int, verify_echo: bool = True) -> None:
        if address % 4:
            raise ValueError("address must be 32-bit aligned")
        if verify_echo:
            self._checked_write(b"\xa8")
            self._checked_write(struct.pack(">L", address))
        else:
            self._ser.write(b"\xa8")
            self._ser.write(struct.pack(">L", address))
            self._ser.flush()

    def write16(
        self,
        address: int,
        data: bytes,
        byte_swap: bool = False,
        verify_echo: bool = True,
        skip_cksum: bool = False,
        progress_cb=None,
        byte_by_byte: bool = False,
    ) -> None:
        """16bit write - Single transaction (opcode+addr+count + ALL data + cksum).

        重要: brom.dll の DownloadData は opcode+addr+count を 1回だけ送り、
        その後全データを連続でストリーム。我々のチャンク毎リトライは間違い。

        byte_by_byte=True: chip にペース合わせて 1byte ずつ送って echo
        """
        if address % 2:
            raise ValueError("address must be 16-bit aligned")
        if len(data) % 2:
            raise ValueError("data length must be a multiple of 2")
        if byte_swap:
            data = _byteswap16(data)
        self._cmd_with_addr_count(b"\xa1", address, len(data) // 2)
        # ストリーム送信（setup は 1回のみ）
        sent = 0
        if byte_by_byte:
            # 1バイトずつ送信、各バイトで echo 確認 (chip pacing)
            for i, b in enumerate(data):
                self._ser.write(bytes([b]))
                if verify_echo:
                    echo = self._ser.read(1)
                    if not echo or echo[0] != b:
                        raise BootRomError(
                            f"write16 echo mismatch at byte {i}: sent=0x{b:02x} got={echo.hex() if echo else 'TIMEOUT'}"
                        )
                if progress_cb and (i + 1) % 32 == 0:
                    progress_cb(i + 1, len(data))
            sent = len(data)
            if progress_cb:
                progress_cb(sent, len(data))
        else:
            while sent < len(data):
                block = data[sent : sent + 10]
                is_last = (sent + len(block) >= len(data))
                self._ser.write(block)
                if verify_echo:
                    if is_last:
                        # 最終 chunk は chip が echo を返さない/壊すケースあり
                        # 寛容に: 受け取れた分だけ確認 → 残りは無視
                        old_to = self._ser.timeout
                        self._ser.timeout = 0.5
                        echo = self._ser.read(len(block))
                        self._ser.timeout = old_to
                        if echo != block:
                            import sys
                            print(
                                f"  [warn] last-chunk echo mismatch: sent={block.hex()} got={echo.hex()} (ignoring)",
                                file=sys.stderr,
                            )
                    else:
                        echo = self._read_exact(len(block))
                        if echo != block:
                            raise BootRomError(
                                f"write16 echo mismatch at offset {sent}: "
                                f"sent={block.hex()} got={echo.hex()}"
                            )
                sent += len(block)
                if progress_cb:
                    progress_cb(sent, len(data))
        if skip_cksum:
            import time as _t
            _t.sleep(0.05)
            return
        cksum = self.checksum(address, len(data))
        local = checksum_xor16(data)
        if cksum != local:
            import sys
            print(
                f"  [warn] write16 cksum mismatch chip={cksum:04x} local={local:04x} "
                f"@ 0x{address:x} (len={len(data)}) - continuing per upstream behaviour",
                file=sys.stderr,
            )

    # ---- 内部ユーティリティ -----------------------------------------------

    def _cmd_with_addr_count(self, opcode: bytes, address: int, count: int) -> None:
        self._checked_write(opcode)
        self._checked_write(struct.pack(">L", address))
        self._checked_write(struct.pack(">L", count))

    def _checked_write(self, data: bytes) -> None:
        for byte in data:
            self._ser.write(bytes([byte]))
        echo = self._read_exact(len(data))
        if echo != data:
            raise BootRomError(
                f"checked_write: echo mismatch send={data.hex()} echo={echo.hex()}"
            )

    def _read_exact(self, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = self._ser.read(n - len(buf))
            if not chunk:
                raise BootRomError(f"timeout reading {n} bytes (got {len(buf)})")
            buf.extend(chunk)
        return bytes(buf)


# Download Agent ----------------------------------------------------------

class DownloadAgentError(RuntimeError):
    pass


class DownloadAgent:
    """MTK Download Agent (DA) クライアント。

    `MtkBootRom` 経由で DA バイナリを `0xc00` にロード→jump して起動し、
    以後 DA 自身のプロトコルで flash 書き込みを行う。

    **書き込み系は破壊的**。Stage 6 まで触らない想定。
    """

    OPCODE_SET_BAUD = 0xD2
    OPCODE_MEM_CMD = 0xD3
    OPCODE_WRITE = 0xD5

    WRITE_PACKET_LEN = 0x100

    ACK = 0x5A
    NAK = 0xA5
    CONT = 0x69
    SYNC = 0xC0

    DA_INFO_REPORT_LEN = 20
    EXPECTED_DA_VERSION = 0x0308  # DA_v3.8.4 reports 0x0308 (version 3.8)

    def __init__(self, brom: MtkBootRom) -> None:
        self._brom = brom
        self._ser = brom.serial
        self._info: dict[str, int] = {}
        self._progress: Callable[[int, int], None] = lambda _c, _t: None

    @property
    def info(self) -> dict[str, int]:
        return dict(self._info)

    def set_progress(self, cb: Callable[[int, int], None] | None) -> None:
        self._progress = cb if cb else (lambda _c, _t: None)

    def _init_mt3301_chip(self) -> None:
        """MT3318/3329/3339 chip init: write magic values to 0x80210050/54/00."""
        import sys
        print('  [init] writing chip init MMIO 0x80210050/54/00', file=sys.stderr)
        for addr, value in [(0x80210050, 0xa357), (0x80210054, 0x67d2), (0x80210000, 0x431f)]:
            self._brom.write16(addr, value.to_bytes(2, 'big'),
                               byte_swap=False, verify_echo=True, skip_cksum=True)

    @staticmethod
    def _build_trampoline(src_addr: int, dst_addr: int, dst_jump: int, da_size_bytes: int) -> bytes:
        """ARM コードでトランポリン生成: DA を src→dst にコピー後、dst_jump へ ldr pc。

        Layout (各命令 4byte):
          0x00: mrs r0, cpsr
          0x04: orr r0, r0, #0xc0   (disable IRQ+FIQ)
          0x08: msr cpsr_c, r0
          0x0c: ldr r0, [pc, #0x18] (= src)
          0x10: ldr r1, [pc, #0x18] (= dst)
          0x14: ldr r2, [pc, #0x18] (= count words)
          0x18: copy_loop start
          0x18: ldr r3, [r0], #4
          0x1c: str r3, [r1], #4
          0x20: subs r2, r2, #1
          0x24: bne 0x18  (= -20 = 0xfffffb)
          0x28: ldr pc, [pc, #0x08]  (= jump target)
          0x2c: PADDING (4 bytes)
          0x30: src literal
          0x34: dst literal
          0x38: count literal
          0x3c: jump target literal
        """
        word_count = (da_size_bytes + 3) // 4
        return struct.pack(
            "<12I",
            0xe10f0000,  # mrs r0, cpsr
            0xe38000c0,  # orr r0, r0, #0xc0
            0xe121f000,  # msr cpsr_c, r0
            0xe59f0018,  # ldr r0, [pc, #0x18]
            0xe59f1018,  # ldr r1, [pc, #0x18]
            0xe59f2018,  # ldr r2, [pc, #0x18]
            0xe4903004,  # ldr r3, [r0], #4
            0xe4813004,  # str r3, [r1], #4
            0xe2522001,  # subs r2, r2, #1
            0x1afffffb,  # bne -20 (back to 0x18)
            0xe59ff008,  # ldr pc, [pc, #8]   ← skip src/dst literals
            0x00000000,  # padding to align literals
        ) + struct.pack("<4I", src_addr, dst_addr, word_count, dst_jump)

    def start(self, da_path: str) -> None:
        """DA を 0x100800 にロード→起動 (HoluxLoggerUtility と同じ正規手順)。

        🔑 鍵:
        - 0x100000-0x1007FF は BootROM の scratchpad/stack 領域で書込不可
        - DA は 0x100800 から始まる前提 (literal 0x101718 = base+0xf18 = real entry)
        - WRITE16 は 16-bit BE16-on-wire / LE16-in-memory 変換するので byte_swap=True 必須
        """
        with open(da_path, "rb") as f:
            da = f.read()
        import sys
        # 末尾 zero padding 削って echo mismatch 回避
        da_trim = da.rstrip(b'\x00')
        while len(da_trim) % 4:
            da_trim += b'\x00'
        print(f"  [da] size: {len(da)} (trim {len(da_trim)})", file=sys.stderr)
        print(f"  [da] writing to 0x{BASE_ADDR_DA:08x} (single shot, byte_swap=True)", file=sys.stderr)
        self._brom.write16(
            BASE_ADDR_DA, da_trim,
            byte_swap=True,  # WRITE16 protocol expects BE16 on wire
            verify_echo=True,
            skip_cksum=True,
            progress_cb=self._progress,
        )
        time.sleep(0.3)
        old_to = self._brom._ser.timeout
        self._brom._ser.timeout = 0.2
        while self._brom._ser.read(4096):
            pass
        self._brom._ser.timeout = old_to
        # echo drain
        time.sleep(0.3)
        old_to = self._brom._ser.timeout
        self._brom._ser.timeout = 0.2
        drained = b''
        for _ in range(20):
            chunk = self._brom._ser.read(64)
            if not chunk:
                break
            drained += chunk
        self._brom._ser.timeout = old_to
        if drained:
            print(f"  [da] drained {len(drained)} late bytes: {drained.hex(' ')[:60]}", file=sys.stderr)
        # 診断: chip alive
        try:
            probe = self._brom.read32(BASE_ADDR_DA, 4)
            print(f"  [diag] post-write read32: {probe.hex(' ')}", file=sys.stderr)
        except Exception as e:
            print(f"  [diag] read32 FAILED: {e}", file=sys.stderr)
            raise

        # echo verify ON で jump (DA へ)
        self._brom.jump(BASE_ADDR_DA, verify_echo=True)
        # 入力バッファに残る jump 自身のエコー (もしあれば) を読み捨て + DA 起動待ち
        import sys
        time.sleep(0.3)
        # まず生バイトを多めに観測
        diag = bytearray()
        deadline = time.time() + 5
        while len(diag) < 80 and time.time() < deadline:
            chunk = self._brom._ser.read(80 - len(diag))
            if chunk:
                diag.extend(chunk)
                deadline = time.time() + 0.5
        print(f"  [diag] received {len(diag)} bytes after jump:", file=sys.stderr)
        print(f"  [diag] hex: {bytes(diag).hex(' ')}", file=sys.stderr)
        # SYNC byte 0xc0 を探して、そこから 20 byte を DA_INFO とみなす
        sync_idx = -1
        for i, b in enumerate(diag):
            if b == self.SYNC:
                sync_idx = i
                break
        if sync_idx < 0:
            raise DownloadAgentError(f"DA SYNC byte 0xc0 not found in response, got: {bytes(diag[:32]).hex()}")
        if len(diag) - sync_idx < self.DA_INFO_REPORT_LEN:
            # Read more
            more = self._brom._read_exact(self.DA_INFO_REPORT_LEN - (len(diag) - sync_idx))  # type: ignore[attr-defined]
            diag.extend(more)
        info = bytes(diag[sync_idx:sync_idx + self.DA_INFO_REPORT_LEN])
        print(f"  [diag] DA_INFO from offset {sync_idx}: {info.hex(' ')}", file=sys.stderr)
        fields = (
            "sync_char", "da_version", "flash_device_id",
            "flash_size", "flash_manufacturer_code", "flash_device_code",
            "flash_ext_device_code1", "flash_ext_device_code2", "ext_sram_size",
        )
        self._info = dict(zip(fields, struct.unpack(">BHBLHHHHL", info)))

        if self._info["sync_char"] != self.SYNC:
            raise DownloadAgentError(
                f"DA SYNC mismatch: 0x{self._info['sync_char']:02x}"
            )
        if self._info["da_version"] != self.EXPECTED_DA_VERSION:
            raise DownloadAgentError(
                f"unsupported DA version: 0x{self._info['da_version']:04x}"
            )
        if self._info["flash_device_id"] == 0xFF:
            raise DownloadAgentError("unsupported flash type (id=0xff)")

    def set_baud_rate(self, baudrate: int) -> None:
        rates = {912600: 1, 460800: 2, 230400: 3}
        if baudrate not in rates:
            raise ValueError(f"invalid baud rate: {baudrate}")
        self._ser.write(struct.pack(">BBB", self.OPCODE_SET_BAUD, rates[baudrate], 0))
        self._expect(self.ACK)
        # DA v3.8 simpler protocol: ACK then immediate baud switch (no extra handshake)
        import time
        time.sleep(0.05)
        self._ser.baudrate = baudrate
        time.sleep(0.1)
        self._ser.reset_input_buffer()

    def write_firmware(self, fw: bytes, *, start: int = 0) -> None:
        """**破壊的**。Flash 書き込み。"""
        if len(fw) % 2:
            raise ValueError("fw length must be a multiple of 2")
        self._set_mem_block(start, len(fw))
        self._ser.write(struct.pack(">BL", self.OPCODE_WRITE, self.WRITE_PACKET_LEN))
        self._expect(self.ACK)
        self._expect(self.ACK)
        for i in range(0, len(fw), self.WRITE_PACKET_LEN):
            self._progress(i, len(fw))
            block = fw[i : i + self.WRITE_PACKET_LEN]
            chksum = sum(block) & 0xFFFF
            self._ser.write(block)
            self._ser.write(struct.pack(">H", chksum))
            r = self._ser.read(1)
            if not r or r[0] != self.CONT:
                raise DownloadAgentError(
                    f"DA did not return CONT at offset 0x{i:x}: {r!r}"
                )
        self._progress(len(fw), len(fw))
        self._expect(self.ACK)
        self._expect(self.ACK)

    def restart(self) -> None:
        self._ser.write(b"\xd9")

    # ---- 内部 -------------------------------------------------------------

    def _set_mem_block(self, start: int, length: int) -> None:
        if length % 2:
            raise ValueError("length must be a multiple of 2")
        end = start + length - 1
        # DA: send full 10-byte cmd in one go, then wait for response
        cmd = struct.pack(">BBLL", self.OPCODE_MEM_CMD, 1, start, end)
        self._ser.write(cmd)
        self._ser.flush()
        # Response: 1 byte ACK (0x5a) or NACK (0xa5), + 1 byte status
        r = self._ser.read(2)
        if not r or r[0] != self.ACK:
            raise DownloadAgentError(
                f"_set_mem_block(start=0x{start:x}, len=0x{length:x}): expected ACK, got {r.hex() if r else 'TIMEOUT'}"
            )

    def _expect(self, byte: int) -> None:
        r = self._ser.read(1)
        if not r or r[0] != byte:
            raise DownloadAgentError(
                f"expected 0x{byte:02x}, got {r.hex() if r else 'TIMEOUT'}"
            )


# モンキーパッチでブロックサイズを公開（DA upload 時に同じサイズで分割）
def _read_block_size_for_da(self: MtkBootRom) -> int:  # noqa: ARG001
    return DownloadAgent.WRITE_PACKET_LEN


MtkBootRom._read_block_size_for_da = _read_block_size_for_da  # type: ignore[attr-defined]


# ---- バイトオーダー変換 -------------------------------------------------

def _byteswap16(data: bytes) -> bytes:
    out = bytearray(len(data))
    for i in range(0, len(data), 2):
        out[i] = data[i + 1]
        out[i + 1] = data[i]
    return bytes(out)


def _byteswap32(data: bytes) -> bytes:
    out = bytearray(len(data))
    for i in range(0, len(data), 4):
        out[i] = data[i + 3]
        out[i + 1] = data[i + 2]
        out[i + 2] = data[i + 1]
        out[i + 3] = data[i]
    return bytes(out)


# ---- ファームウェアファイルヘッダ解析 -----------------------------------

def parse_fw_header(header: bytes) -> dict:
    """ファーム先頭 0xa00 バイトから設定情報を抽出 (mt333x_fw_file_info.py 由来)。"""
    if len(header) < 0x200:
        raise ValueError("header too short")
    info = {
        "firmware_family": header[0x90:0xB0].rstrip(b"\x00").decode("utf-8", "replace"),
        "device_type": header[0x1B0:0x1C0].rstrip(b"\x00").decode("utf-8", "replace"),
        "release_name": header[0x148:0x150].rstrip(b"\x00").decode("utf-8", "replace"),
        "release_major": header[0x15A],
        "release_minor": header[0x15B],
        "build_number": struct.unpack_from("<H", header, 0x108)[0],
        "fw_size": struct.unpack_from("<L", header, 0xF4)[0],
        "serial_port_string": header[0x190:0x1A0].rstrip(b"\x00").decode("utf-8", "replace"),
    }
    chip = {1: "MT3329", 2: "MT3339", 3: "MT3333"}.get(info["release_major"], "unknown")
    info["chip_guess"] = chip
    return info
