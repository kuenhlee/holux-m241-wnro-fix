# Holux M-241 — GPS 週数ロールオーバー (WNRO) 修復

GPS 週数ロールオーバー (WNRO) で日付がおかしくなった Holux M-241 を、
2 バイトのファームパッチで蘇らせるプロジェクト。
Pure Python なので **JTAG 不要、GlobalTop 純正 `PowerFlash.exe` 不要**。

> Holux は 2019年に GPS 事業から撤退済。M-241 の時計は 2019-04-06 (第2 GPS WNRO)
> 以降ずっと壊れていて、何もしないと 2026年 を **2006年** として記録する。

[English README](README.md)

> **このフォークについて**: 読み取り専用の Boot ROM プローブ (`scripts/probe_read.py`)、
> より安全な dump / patch / flash スクリプト、そして 2 台目の個体 (HW V02, FW V1.13) を
> Windows + Tera Term で実施した記録を追加している。
> [`docs/04-hw-v02-findings.md`](docs/04-hw-v02-findings.md) と
> [`docs/05-procedure-windows-teraterm.md`](docs/05-procedure-windows-teraterm.md) を参照 (どちらも英語)。
> オリジナル: [NekobaTechnology/holux-m241-wnro-fix](https://github.com/NekobaTechnology/holux-m241-wnro-fix)

## 解説記事

📝 **[詳細ブログ記事 (catea.tech)](https://catea.tech/blog/holux-m241-wnro-fix)** — BootROM の逆解析過程、DA ロードアドレスの突き止め方、「`+1024` 直接書き換え」が効かなかった理由、未文書 PMTK aiding コマンド、ハマりどころと教訓まで全て解説。書いたのは [加藤 一葉 (二葉 / Futaba)](https://catea.tech/about) ([猫葉Tech](https://catea.tech))。

## このプロジェクトでできること

1. **MTK MT3318 BootROM プロトコルの Pure Python 実装**
   GlobalTop の Windows 専用 `PowerFlash.exe` 無しでチップと喋れる。
   `pyserial` が動く OS なら macOS / Linux / Windows どれでも。
2. **オリジナルファームの吸い出し** — 何かする前に必ず自分の機器のバックアップを取る。
3. **2 バイトの精密パッチ**
   - WNRO: Unix epoch 基準を +1024 週 (= +7168日) ずらす
   - 表示: OLED の `V1.13` を `V1.14` に上書き
4. **パッチ済イメージの書き戻し** — Holux 純正ツールが使うのと同じ MTK Download Agent (DA) プロトコル経由で。

書き戻し後、`$GPRMC` の UTC 日付が正しい現在日付になり、OLED もそれに追従する。

## 実機検証ステータス (オリジナル作者の個体)

| コンポーネント | ステータス |
|--------------|-----------|
| firmware ダンプ | ✅ macOS で動作確認済 |
| BootROM sync (PMTK180 → 0xa0/0x0a/0x50/0x05) | ✅ |
| DA ロード (アドレス `0x00100800`、Holux と同じ) | ✅ |
| DA flash プロトコル (0xD3 set-mem, 0xD5 write, 0x5A ACK) | ✅ |
| WNRO パッチ実機検証 | ✅ NMEA で正しい UTC 日付出力 |
| バージョン文字列 `V1.13 → V1.14` | ✅ OLED に反映 |
| PMTK aiding (715 / 716 / 717) | ✅ status=3 で ACK |

## 2 台目の個体での検証 (このフォーク)

| 項目 | 結果 |
|------|------|
| 個体 | Holux M-241、HW V02、FW V1.13。Windows + Tera Term (38400) |
| BootROM 読み出し / ダンプ | ✅ `--base-addr 0x200000` が必要 (flash は既定の `0x20000000` には無い) |
| Flash / DA | ✅ 512 KB MXIC `0xc2` / `0x22ba`、DA v3.8 を `0x100800` にロード |
| パッチ済イメージの書込 | ✅ `--start-addr 0x0` |
| バージョン表示 | ✅ `V1.14` |
| GPS 捕捉 | ✅ |
| 時間間隔ロギング (5 秒) | ✅ |
| ログ取得 (Holux Logger Utility) → KML → Google Earth | ✅ |
| `$GPRMC` / OLED の日付、ログのタイムスタンプ | ⏳ 未確認 (`docs/04` 参照) |

メモリマップやベースアドレスは個体によって異なるため、ダンプや書込の前に
`probe_read.py` を実行すること (クイックスタート参照)。

## ディレクトリ構成

```
.
├── docs/                     - 解析の経過 (時系列)
│   ├── 00-baseline.md         (壊れた挙動の記録)
│   ├── 01-protocol.md         (MTK BootROM プロトコル)
│   ├── 02-firmware-map.md     (M-241 ファーム構造)
│   ├── 03-brom-analysis.md    (フル逆解析)
│   ├── 04-hw-v02-findings.md  (2台目: メモリマップ、パッチ位置、結果)
│   └── 05-procedure-windows-teraterm.md (Windows + Tera Term の手順)
├── scripts/
│   ├── mtk_proto.py           (BootROM クライアント + DA ドライバ)
│   ├── probe_read.py          (読み取り専用の BootROM 読出し / メモリマップ確認)
│   ├── dump_firmware.py       (自分の M-241 を .bin にダンプ)
│   ├── patch_firmware.py      (2バイトパッチ適用)
│   └── flash_firmware.py      (.bin を DA 経由で書き戻し。--info-only で DA だけ試験)
└── requirements.txt
```

## このリポジトリに**含まれていない**もの (各自で用意)

著作権を尊重するため、proprietary バイナリは一切コミットしていない。
以下は自分で用意する必要がある:

| ファイル | 入手方法 |
|---------|---------|
| `DA_v3.8.4.bin` | Holux Logger Utility のインストーラ (`1597553.zip` 等) に同梱。MTK の DA で再配布不可。 |
| `m241_dump70.bin` | **自分の** M-241 から `scripts/dump_firmware.py` で吸い出す (`0x70000` バイト)。著作権は Holux/MTK のもの。`firmware/` と `*.bin` は `.gitignore` で除外。 |

## 必要なハードウェア

- **WNRO バグ持ちの Holux M-241** (2019年中頃以前に出荷された個体は全部該当)
- 付属 USB ケーブル、または `/dev/tty.usbserial-*` (macOS) / `/dev/ttyUSB*` (Linux) として認識される CP210x USB-UART ブリッジ
- Python 3.10+ と `pyserial` が動くホスト機。動作確認は macOS (オリジナル作者) と
  Windows (このフォーク: Tera Term + `COM3`、[`docs/05`](docs/05-procedure-windows-teraterm.md) 参照)。
  Linux でも動くはず (pyserial がクロスプラットフォームなので)。
- **きちんとしたバックアップ手順** (途中で電源が切れると文鎮化リスクあり)

## クイックスタート

`<PORT>` は `/dev/tty.usbserial-*` (macOS)、`/dev/ttyUSB0` (Linux)、`COM3` (Windows) など。
Windows の場合は [`docs/05-procedure-windows-teraterm.md`](docs/05-procedure-windows-teraterm.md) (英語) の手順に従うこと。
Boot ROM モードへの入り方や、スクリプト実行前に Tera Term を閉じる必要がある点も書いてある。

```bash
# 0) Python 依存をインストール
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 1) 自分の個体で flash がどこにマップされているか確認 (読み取りのみ)
#    正しいベースアドレスでは ARM のベクタテーブル (18 f0 9f e5 ...) が見える。
#    HW V02 の個体では 0x200000。既定の 0x20000000 は一定値の埋め草を返す。
#    probe が通るまでダンプも書込もしないこと。
python3 scripts/dump_firmware.py <PORT> firmware/original/m241_header.bin \
    --base-addr 0x200000 --header-only --no-verify
python3 scripts/probe_read.py <PORT> --base-addr 0x200000 \
    --header firmware/original/m241_header.bin

# 2) 0x70000 バイトのイメージをバックアップ (読み取りのみ。2回分のハッシュが一致すること)
python3 scripts/dump_firmware.py <PORT> firmware/original/m241_dump70.bin \
    --base-addr 0x200000 --length 0x70000

# 3) 2バイトパッチ + バージョン更新
python3 scripts/patch_firmware.py \
    firmware/original/m241_dump70.bin \
    firmware/patched/m241_v114_wnro.bin

# 4) flash に書かずに Download Agent だけ試験
python3 scripts/flash_firmware.py <PORT> \
    --da firmware/agents/DA_v3.8.4.bin \
    --fw firmware/patched/m241_v114_wnro.bin \
    --i-have-backup firmware/original/m241_dump70.bin \
    --start-addr 0x0 --info-only

# 5) 書込 (破壊的 — まず DISCLAIMER.md を読むこと)
python3 scripts/flash_firmware.py <PORT> \
    --da firmware/agents/DA_v3.8.4.bin \
    --fw firmware/patched/m241_v114_wnro.bin \
    --i-have-backup firmware/original/m241_dump70.bin \
    --start-addr 0x0
```

補足:

- フラッシャは、長さが `0x100` の倍数でないファーム、またはバックアップと
  パッチの 3 バイト以外が異なるファームの書込を拒否する。
- `--start-addr 0x0` は HW V02 の個体で動作した。書込確認を省略する `--yes` は
  例から意図的に外してある。
- 任意の「同一イメージ書込テスト」(未改造のバックアップを先に書き込み、再ダンプしてハッシュを比較) は
  `docs/05` に記載。

step 5 の後デバイスを電源 OFF/ON して:

- OLED に `V1.14` が出る
- (衛星捕捉後) `$GPRMC` が現在の正しい UTC 日付を返す

## パッチの仕組み

Holux M-241 のファームは内部 GPS 時刻を Unix 時刻に変換するときに、
`315964800` (= GPS epoch 1980-01-06 の Unix 時刻) というハードコード定数を
足している。これを `935280000` (= 元の値 + 619 315 200 秒 = +1024 週 = +7168日)
に書き換えると、すべての出力タイムスタンプが第2ロールオーバー後の正しい
時代にずれる。たった 4 バイト書き換えるだけで NMEA RMC の date が直る。
この定数はファーム内に 2 ヶ所ある (`0x402DC` と `0x402F4`)。書き換えるのは `0x402F4` だけで、
両方書き換えると日付が行き過ぎる。

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
