# Holux M-241 — GPS 週数ロールオーバー (WNRO) 修復

GPS 週数ロールオーバー (WNRO) で日付がおかしくなった Holux M-241 を、
2 バイトのファームパッチで蘇らせるプロジェクト。
**JTAG 不要、Windows 不要**、Mac/Linux のみで完結する。

> Holux は 2019年に GPS 事業から撤退済。M-241 の時計は 2019-04-06 (第2 GPS WNRO)
> 以降ずっと壊れていて、何もしないと 2026年 を **2006年** として記録する。

[English README](README.md)

## このプロジェクトでできること

1. **MTK MT3318 BootROM プロトコルの macOS/Linux 実装**
   GlobalTop の Windows 専用 `PowerFlash.exe` 無しでチップと喋れる。
2. **オリジナルファームの吸い出し** — 何かする前に必ず自分の機器のバックアップを取る。
3. **2 バイトの精密パッチ**
   - WNRO: Unix epoch 基準を +1024 週 (= +7168日) ずらす
   - 表示: OLED の `V1.13` を `V1.14` に上書き
4. **パッチ済イメージの書き戻し** — Holux 純正ツールが使うのと同じ MTK Download Agent (DA) プロトコル経由で。

書き戻し後、`$GPRMC` の UTC 日付が正しい現在日付になり、OLED もそれに追従する。

## 実機検証ステータス

| コンポーネント | ステータス |
|--------------|-----------|
| firmware ダンプ | ✅ macOS で動作確認済 |
| BootROM sync (PMTK180 → 0xa0/0x0a/0x50/0x05) | ✅ |
| DA ロード (アドレス `0x00100800`、Holux と同じ) | ✅ |
| DA flash プロトコル (0xD3 set-mem, 0xD5 write, 0x5A ACK) | ✅ |
| WNRO パッチ実機検証 | ✅ NMEA で正しい UTC 日付出力 |
| バージョン文字列 `V1.13 → V1.14` | ✅ OLED に反映 |
| PMTK aiding (715 / 716 / 717) | ✅ status=3 で ACK |

## ディレクトリ構成

```
.
├── docs/                     - 解析の経過 (時系列)
│   ├── 00-baseline.md         (壊れた挙動の記録)
│   ├── 01-protocol.md         (MTK BootROM プロトコル)
│   ├── 02-firmware-map.md     (M-241 ファーム構造)
│   └── 03-brom-analysis.md    (フル逆解析)
├── scripts/
│   ├── mtk_proto.py           (BootROM クライアント + DA ドライバ)
│   ├── dump_firmware.py       (自分の M-241 を .bin にダンプ)
│   ├── patch_firmware.py      (2バイトパッチ適用)
│   └── flash_firmware.py      (.bin を DA 経由で書き戻し)
└── requirements.txt
```

## このリポジトリに**含まれていない**もの (各自で用意)

著作権を尊重するため、proprietary バイナリは一切コミットしていない。
以下は自分で用意する必要がある:

| ファイル | 入手方法 |
|---------|---------|
| `DA_v3.8.4.bin` | Holux Logger Utility のインストーラ (`1597553.zip` 等) に同梱。MTK の DA で再配布不可。 |
| `m241_dump.bin` | **自分の** M-241 から `scripts/dump_firmware.py` で吸い出す。著作権は Holux/MTK のもの。 |

## 必要なハードウェア

- **WNRO バグ持ちの Holux M-241** (2019年中頃以前に出荷された個体は全部該当)
- 付属 USB ケーブル、または `/dev/tty.usbserial-*` (macOS) / `/dev/ttyUSB*` (Linux) として認識される CP210x USB-UART ブリッジ
- macOS か Linux のホスト機。**Windows 不要**。
- **きちんとしたバックアップ手順** (途中で電源が切れると文鎮化リスクあり)

## クイックスタート

```bash
# 0) Python 依存をインストール
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 1) 自分の M-241 をダンプ (安全 — 読み取りのみ)
python3 scripts/dump_firmware.py /dev/tty.usbserial-0001 \
    --da firmware/agents/DA_v3.8.4.bin \
    firmware/original/m241_dump.bin

# 2) 2バイトパッチ適用
python3 scripts/patch_firmware.py \
    firmware/original/m241_dump.bin \
    firmware/patched/m241_v114_wnro.bin

# 3) 書込 (破壊的 — まず DISCLAIMER.md を読むこと)
python3 scripts/flash_firmware.py /dev/tty.usbserial-0001 \
    --da firmware/agents/DA_v3.8.4.bin \
    --fw firmware/patched/m241_v114_wnro.bin \
    --i-have-backup firmware/original/m241_dump.bin \
    --start-addr 0x0 \
    --yes
```

step 3 の後デバイスを電源 OFF/ON して:

- OLED に `V1.14` が出る
- (衛星捕捉後) `$GPRMC` が現在の正しい UTC 日付を返す

## パッチの仕組み

Holux M-241 のファームは内部 GPS 時刻を Unix 時刻に変換するときに、
`315964800` (= GPS epoch 1980-01-06 の Unix 時刻) というハードコード定数を
足している。これを `935280000` (= 元の値 + 619 315 200 秒 = +1024 週 = +7168日)
に書き換えると、すべての出力タイムスタンプが第2ロールオーバー後の正しい
時代にずれる。たった 4 バイト書き換えるだけで NMEA RMC の date が直る。

なぜ「GPS 週計算 +1024」を直接いじらないのか? 試した — 該当しそうな箇所
4 ヶ所を全部パッチしても **NMEA RMC date は変わらなかった**。Epoch 定数は
1ヶ所、決定論的で、UTC を出力するすべてのコードパスを通る。これが正解だった。

## リスク

JTAG の無いデバイスのファーム書換である。何か実行する前に必ず
[`DISCLAIMER.md`](DISCLAIMER.md) を読むこと。教育目的・修理権の文脈で
無保証で提供する。

## ライセンス

リポジトリ内のコード・ドキュメントは [MIT](LICENSE)。
各自が用意する proprietary ファームファイルは元の著作権者のもの。

## 謝辞

- [`mt333x-fw-utils`](https://github.com/dimhoff/mt333x-fw-utils) (dimhoff)
  — オリジナルの MTK GPS プロトコル参考実装。
- BT747 プロジェクト — MTK GPS の細かい挙動の文書化。
- 古いハードを動かし続けるすべての人へ。

## 制作プロセス

BootROM / DA プロトコルの逆解析、ファーム逆アセンブル、パッチ箇所の特定、
クライアント実装は、Anthropic の AI コーディング支援
[Claude Code](https://www.anthropic.com/claude-code) と対話しながら行った。
コミットされたすべてのバイトは公開前に人間が実機で動作確認している。
