# Stage 2-3: Holux M-241 ファームウェア マップ

実機ダンプから得られたファームウェア構造の解析結果。

## メモリマップ（Boot ROM 視点）

| 領域 | アドレス範囲 | 内容 | サイズ |
|------|-------------|------|------|
| **Bootloader** | `0x000000 - 0x010000` | MTK 初期化コード（64KB の実体、`0x0000-0x07ffff` までエイリアス×8回） | 64KB |
| Bootloader バンクB | `0x080000 - 0x0fffff` | バンクA と完全同一（mirror） | 64KB |
| **Main Firmware** | `0x200000 - 0x263458` | `HOLUX_M-241 / B-core 1.20`（実 SHA256 b832...） | ~400KB |
| RAM | `0x100000 - 0x1fffff` | 1MB 領域、SP は `0x100800` に初期化される | 1MB |
| 不明/レジスタ | `0x80000000+` | アクセスすると Boot ROM プロトコルが壊れる | - |
| ROM | `0xA0000000+` | 同上、おそらく MTK のマスク ROM | - |

## ファームウェアヘッダ (0x200000)

mt333x-fw-utils 由来のフォーマットがそのまま適用可能:

```
firmware_family:     HOLUX_M-241
device_type:         01017-00F
release_name:        B-core
release_major:       1
release_minor:       20  (= "B-core_1.20" の 1.20)
build_number:        67
fw_size:             406616 bytes (0x63458)
serial_port_string:  SPP Slave
build_date string:   "Feb  9 2006 10:53:05" (__DATE__ __TIME__)
```

→ mt333x-fw-utils の `release_major=1` → MT3329 判定はミスリーディング。
  実際は **MT3318 ベースの Holux カスタムファーム**。

## アーキテクチャ確定

```
[GPS RF] → [MT3318 ARM7TDMI Thumb] ──UART 38400──> [CP2102] ──USB──> Host
                  │
                  ↓
            メインファーム (0x200000)
            ・GPS 計算 (mask ROM 連携)
            ・NMEA 生成 ($GPRMC, $GPZDA など)
            ・PMTK コマンド処理
            ・OLED 表示制御 (Setting/ShowTime/ShowTLog 等の C++ クラス)
            ・ボタン入力 (ProcessKeys)
            ・ログ書込 (HOLUXGR241LOGGER)
```

→ **「表示制御 MCU」は別チップではなく、MTK の Thumb コードがすべてやっている**。
  v1.13 表示と B-core_1.20 の食い違いは「アプリ層バージョン vs GPS エンジンバージョン」を別管理している、ファーム内のテキスト表示の都合と思われる（要追加調査）。

## WNRO バグの所在

### 確認した重要な定数 (LE32)

| 定数 | ファイル offset | 意味 | Thumb LDR refs |
|-----|----------------|------|---------------|
| `604800` (秒/週) | 0x4980, 0x5238, 0x5334, 0x6e3c | GPS week → seconds | 1+3+3+3 = 10 |
| `86400` (秒/日) | 0x523c, 0x5338, 0x6e40, 0x377c8 | seconds/day | 1+1+1 = 3 |
| `315964800` (Unix sec @ GPS epoch) | 0x402dc, 0x402f4 | GPS time → Unix time | 2+2 = 4 |
| days-per-month leap | 0x4de90 | カレンダー変換 | (要調査) |
| cumulative days table | 0x378ac | カレンダー変換 | (要調査) |
| `1980` | 0x5ad70 | GPS epoch year | (要調査) |

### `+1024` を week に加える箇所

`movs rN, #1; lsls rN, rN, #0xa` のパターンで **27箇所** ヒット。多くは flag 操作や境界比較だが、**真の WNRO 関連候補**:

| Offset | 関数 | 内容 | 推定意味 |
|--------|-----|------|--------|
| `0x51b2` | 0x5140 | `byte_d + 1024 → week` | 推定 week 計算（fine-tuneで±256） |
| `0x52b0` | 0x5240 | `byte_d + 1024 → week` | 同上の別バリアント |
| `0x14086` | 0x14078 付近 | `(byte<<2 \| byte>>6) + 1024` | **10-bit raw GPS week + 1024 base offset** |
| `0x40f52` | 0x40f44 付近 | 同パターン | 上記の別関数 |
| `0x3df88` | 0x3deb0 | `stored_week - 1024 → 書き戻し` | rollover 検出時の補正書込 |

→ **`+1024` は「GPS 1024週ロールオーバー後 (1999年8月以降) の base offset」を表す**。今は 2nd ロールオーバー (2019-04-06+) なので **`+2048` が正しい**。

### 単純パッチが効かない理由

候補が 4-5 箇所あり、全部書き換えると整合性が崩れる懸念。0x3deb0 の `stored_week - 1024` は rollover 検出ロジックの一部で、ここを `-2048` に変えるべきか不明。

### 推奨アプローチ

1. **まず Stage 4 NMEA プロキシで `+7168 日` ロジックを実機検証** ← 安全、可逆
2. プロキシで望む結果が得られたら:
   - **Option A (簡易)**: プロキシをそのまま長期解として運用（ただし端末 OLED は治らない）
   - **Option B (本命)**: 候補4-5箇所を全部 `+2048` に変更してダンプ→エミュレータ→実機の段階で検証
   - **Option C (最小侵襲)**: 候補のうち最終的に NMEA RMC date に効く１関数だけパッチ
3. パッチは Stage 5 のフローで NMEA プロキシ→Unicorn エミュ→フラッシュの順で検証

## 主要関数アドレス

| Address | 内容 |
|---------|------|
| 0x0000 (bootloader) | Reset vector |
| 0x4962 | `gps_time_seconds = accumulator + week*604800` 単純版 |
| 0x5140 | 完全な GPS time → date 変換（複雑） |
| 0x5240 | 同上の別バリアント（呼び出し規約違い？） |
| 0x6bdc | NMEA RMC ビルダ候補（ログ書込関連？） |
| 0x3deb0 | week 補正ストア関数 (`strh ?, [r2, #2]`) |
| 0x14078 | 10-bit week 組立 + 1024 base offset |
| 0x40f44 | 同上の別関数 |

ROM 関数（メインファーム外、おそらく MT3318 mask ROM）:
- `0x20a970`, `0x20b1e8`, `0x20b310`, `0x20b34c`, `0x20b974`, `0x20bc3c`, `0x20c27c`, `0x20c6ac`, `0x20c714`, `0x20c7b4`, `0x20c9b4`, `0x20ce24`
- `0x207524`, `0x207b14` (memory ops)
- 64-bit 演算系（add/mul/div）が多い

## 次の手順

1. **デバイス電源 OFF/ON** で Boot ROM モードを抜ける
2. NMEA プロキシ起動: `python3 tools/nmea-proxy/proxy.py /dev/tty.usbserial-0001 --offset-days 7168`
3. NMEA 出力で日付が `2026-05-03` 系に補正されることを確認
4. ホスト側ツール (gpsd, Google Earth) に通して実用性検証
5. 結果を `docs/03-patch-design.md` に記録、ファームパッチ設計に進むか判断
