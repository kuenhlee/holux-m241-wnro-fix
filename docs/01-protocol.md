# MTK GPS チップ プロトコル参照

`mt333x-fw-utils` のソースから読み解いた MTK チップ通信プロトコルのまとめ。M-241 にも同じ Boot ROM プロトコルが使えると期待。

## 1. 通常モード（NMEA + PMTK）

### 物理層
- USB → CP210x USB-UART → MTK チップの UART
- デフォルト 38400 baud, 8N1（M-241 のファーム設定による）

### NMEA 0183 出力
標準の `$GP*` センテンスが流れてくる。WNRO 検証は `$GPRMC` の date フィールドで行う。

### PMTK 拡張コマンド
NMEA と同形式の `$PMTK<command>,<data>*<chksum>\r\n`。チェックサムは `$` と `*` の間の XOR (1バイト, 16進2桁)。

| コマンド | 用途 | 期待される応答 |
|---------|------|--------------|
| `$PMTK000*32` | テスト（NoOp） | `$PMTK001,0,3*30` |
| `$PMTK605*31` | ファームウェアリリース取得 | `$PMTK705,...` |
| `$PMTK101*32` | Hot start | ACK |
| `$PMTK102*31` | Warm start | ACK |
| `$PMTK103*30` | Cold start | ACK |
| `$PMTK104*37` | Full cold start (factory reset) | ACK |
| `$PMTK180*3B` | **Boot ROM モードへ移行** | （即時切替、NMEA 停止） |
| `$PMTK220,1000*1F` | Update rate 1Hz | ACK |

## 2. Boot ROM モード

`$PMTK180*3B` 送信後、チップは生 UART プロトコルを話す Boot ROM に切り替わる。**Holux 純正ユーティリティで firmware update を始めるとこのモードに入る**ので、USB スニファでこの遷移を捕捉できる。

### エントリシーケンス
```
Host:   '\xa0' (繰り返し送信、最大10秒)
Target: '\x5f' (1度返ったら次へ)
Host:   '\x0a'
Target: '\xf5'
Host:   '\x50'
Target: '\xaf'
Host:   '\x05'
Target: '\xfa'
```

ここまで成功すると Boot ROM の対話モードに入る。

### Boot ROM コマンド（big-endian）

すべて「送ったバイトが echo back される」スタイル（`_checked_write`）。

| Opcode | コマンド | 引数 | 応答 |
|--------|---------|------|------|
| `\xa1` | write16 | addr(BE32), len_words(BE32), data(echo中継+chksum) | data echo |
| `\xa2` | read16 | addr(BE32), len_words(BE32) | data + chksum |
| `\xa4` | checksum | addr(BE32), len_words(BE32) | xor16(BE16) |
| `\xa8` | jump | addr(BE32) | 制御移行 |
| `\xaf` | read32 | addr(BE32), len_dwords(BE32) | data + chksum |

### メモリマップ（推定）

| アドレス | 用途 |
|---------|------|
| `0x00000c00` | RAM スクラッチパッド（Download Agent ロード先） |
| `0x20000000` | SPI Flash（ファームウェア本体） |
| `0x80000000` | レジスタ |
| `0xA0000000` | ROM |

## 3. Download Agent (DA) モード

Boot ROM 経由で `0xc00` に DA バイナリを書き込み `jump 0xc00` で起動。
DA 起動後は別プロトコルになる。

### 各種定数
- `OPCODE_SET_BAUD = 0xd2` - 高速 baud に切替（230400/460800/912600）
- `OPCODE_MEM_CMD  = 0xd3` - 書き込み範囲セット
- `OPCODE_WRITE    = 0xd5` - データ書き込み
- `ACK = 0x5a`, `NAK = 0xa5`, `CONT = 0x69`, `SYNC = 0xc0`
- 書き込みパケット長: `0x100` (256B)
- `restart()`: `\xd9` を送る

### DA 起動時に得られる情報（20バイト）
```
struct DA_INFO {
    uint8_t  sync_char;            // 0xc0
    uint16_t da_version;           // 期待値 0x0400
    uint8_t  flash_device_id;
    uint32_t flash_size;           // 重要：ダンプサイズ
    uint16_t flash_manufacturer_code;
    uint16_t flash_device_code;
    uint16_t flash_ext_device_code1;
    uint16_t flash_ext_device_code2;
    uint32_t ext_sram_size;
}
```

### 必要な DA バイナリ

チップ別。Holux M-241 が MT3329 と判明したら `MTK_AllInOne_DA_MT3329_v4.02.bin` (md5 `52724a12c7186bdede40ce65e0d81c5e`) が必要。

| Chipset | DA filename | MD5 |
|---------|-------------|-----|
| MT3318 | MTK_AllInOne_DA_MT3318_v4.01.bin | 7e6bd13492293cf1efb4e8b25caa8c80 |
| MT3329 | MTK_AllInOne_DA_MT3329_v4.02.bin | 52724a12c7186bdede40ce65e0d81c5e |
| MT3333 | MTK_AllInOne_DA_MT3333_MP.BIN | 028a2c42d1e39623c8aa148d8a0e6709 |
| MT3339 | MTK_AllInOne_DA_MT3339_E3.bin | 973d91e32b1cc37a332bfc9e235bc372 |

入手元: GlobalTop FlashTool に同梱（公式配布元、もしくは Web で MD5 照合して入手）。

## 4. ファームウェアファイルフォーマット

最初の `0xa00` バイトがヘッダ。以下は推定（mt333x_fw_file_info.py より）。

| Offset | サイズ | 内容 |
|--------|------|------|
| 0x5c | 4B | プログラミング時に書かれる magic（dump 時は剥がす） |
| 0x90 | 32B | firmware family 文字列 |
| 0xf4 | 4B (LE32) | firmware size |
| 0x108 | 2B (LE16) | build number |
| 0x11b | 1B | GPS datum |
| 0x11c | 1B | update rate |
| 0x120 | 1B | baud rate enum |
| 0x121 | 1B | LED no-fix |
| 0x122 | 1B | LED fix |
| 0x128-0x12f | 8B | NMEA sentence rate (GGA/GLL/?/GSV/GSA/VTG/RMC/GLL2) |
| 0x138 | 1B | rate ZDA |
| 0x148 | 8B | release name 文字列 |
| 0x15A | 1B | release major（1=MT3329, 2=MT3339, 3=MT3333） |
| 0x15B | 1B | release minor |
| 0x162 | 1B | bit2: NMEA precision (0=4 / 1=6 桁) |
| 0x182 | 1B | LOCUS type |
| 0x183 | 1B | LOCUS mode |
| 0x190 | 16B | serial port string |
| 0x1b0 | 16B | device type 文字列 |

## 5. 実用的な検証コマンド

```bash
# PMTK ACK のテスト
echo -en '$PMTK000*32\r\n' > /dev/tty.SLAB_USBtoUART

# ファーム release version 取得
echo -en '$PMTK605*31\r\n' > /dev/tty.SLAB_USBtoUART
```

`screen` で見ながら別ターミナルから打つのが楽。
