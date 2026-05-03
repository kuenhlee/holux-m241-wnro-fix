# brom.dll 逆解析メモ

GlobalTop FlashTool 同梱の `brom.dll` を解析して、MTK GPS Boot ROM プロトコルを
ほぼ全容把握した結果。Mac で完全なフラッシュ実装を達成するには、もう少し情報が必要。

## 解析対象

- `/tmp/gtop_extract/GlobalTop FlashTool/brom.dll` (245 KB Win32 DLL, x86)
- 内部ソースパス: `F:\3329_MP_verify\Bromdll\brom_mt3301.cpp`
  → **MT3329 用に開発、後から MT3318/MT3339/MT3333 にも流用** された経緯が判る

## クラス構造

- 1つの `BRom_mt3301` クラスが MT3318/3329/3339 すべての通信を担当
- `BRom_Base` 派生 (`brom_base.cpp` も参照されている)
- vtable に 30+ メソッド、低位 6 個がチップ固有、残り 24 個が共通

## 実 vtable 構造 (BRom_mt3301)

ベース: `0x602836c` (struct `0x6028358 + 0x14`)

| Offset | 関数アドレス | 役割 (推定) |
|--------|------------|-----------|
| `+0x00` | 0x600bb60 | StartCmd (PMTK180送信→sync) |
| `+0x04` | 0x600c7c0 | チップ固有: BootStop |
| `+0x08` | 0x600bb20 | スタブ (xor eax,eax; ret) |
| `+0x0c` | 0x600c9d0 | **チップ固有 init (3レジスタ書込)** |
| `+0x10` | 0x600ca60 | チップ固有: 0x80210000 ← 0x431b |
| `+0x14` | 0x600bb30 | デストラクタ |
| `+0x18` | 0x6005580 | 共通 |
| `+0x1c` | 0x6005770 | 共通 |
| `+0x20` | 0x60058d0 | 共通 (Read16) |
| `+0x24` | 0x6005f80 | 共通 (Write16: opcode 0xa1) |
| `+0x28` | 0x6006140 | 共通 (Write32) |
| `+0x2c` | 0x6006300 | 共通 (DownloadData = chunked) |
| `+0x30` | 0x6006ad0 | 共通 |
| `+0x34` | 0x6006c70 | 共通 (Jump: opcode 0xa8) |
| `+0x38` | 0x6006d60 | 共通 (1byte send + echo verify) |
| `+0x3c` | 0x6006f90 | 共通 (4byte send) |
| `+0x40` | 0x60070c0 | 共通 |
| `+0x50` | 0x6008450 | 共通 (raw serial WriteFile) |
| ... | | |
| `+0x68` 以降 | 0x600ca90+ | チップ固有 (5関数) |

## Boot ROM プロトコル (確認済み)

### Sync シーケンス

1. NMEA モードから移行: `$PMTK180*3B\r\n` 送信 (0xd バイト)
2. 各種 baud (115200, 57600, ..., 4800) で sync byte `0xa0` 投げる
3. チップの応答は **「送信した bit の補数」**:
   - `~0xa0 = 0x5f`, `~0x0a = 0xf5`, `~0x50 = 0xaf`, `~0x05 = 0xfa`
4. 上記 4 バイトすべて補数応答が来たら sync 確立

### コマンド

- `0xa1` = WRITE16: opcode + addr(BE32) + count_words(BE32) + data
  - データは 10byte ごと送信、**byte_swap=True (16bit ペアで反転)**
  - 各 byte echo back あり
  - 最後に checksum 取得して比較 (大ブロックでは無意味、warning のみ)
- `0xa2` = READ16: opcode + addr + count_words → data
- `0xa4` = CHECKSUM: opcode + addr + count_words → 16bit XOR
- `0xa8` = JUMP: opcode + addr (BE32)
- `0xaf` = READ32

## DA ロードの詳細

### DA バイナリ (`MTK_AllInOne_DA_MT3318_v4.01.bin`)

```
0x0000: mov r0, r0      (NOP)
0x0004: mrs r0, apsr
0x0008: mov r1, #0xc0   (CPSR disable IRQ+FIQ)
0x000c: orr r0, r0, r1
0x0010: msr cpsr_fsxc, r0
0x0014: mov r1, #0x100000
0x0018: add r1, r1, #0x800   ; r1 = 0x100800
0x001c: sub r1, r1, #4       ; r1 = 0x1007fc
0x0020: mov sp, r1            ; SP = 0x1007fc
0x0024: ldr r3, [pc]          ; r3 = *(0x002c) = 0x0010173c
0x0028: bx r3                 ; jump to 0x0010173c (ARM mode)
0x002c: 3c 17 10 00          (entry address = 0x0010173c)
```

**ロードアドレス**: `0x101000` (絶対 jump 先 0x10173C - 0x73C オフセット = 0x101000)
**SP 設定**: 0x1007FC (DA より下、ブートローダの旧スタック領域)

### MT3301 チップ固有 init (vtable+0xc = 0x600c9d0)

DA ロード前に実行が必要:

```
write16(0x80210050, 0xa357)
write16(0x80210054, 0x67d2)
write16(0x80210000, 0x431f)
```

別関数 vtable+0x10 (0x600ca60) は:
```
write16(0x80210000, 0x431b)   ; mode 切替？
```

(`0x80210000` 系は MT3301 のチップ内 MMIO レジスタと推定)

## 試したこと vs 結果 (Mac 側)

| 試行 | 結果 |
|------|------|
| Sync シーケンス | ✅ 成立 |
| PMTK605 で `B-core_1.20` 取得 | ✅ |
| Read16 で flash dump | ✅ 全領域読み出し成功 |
| Write16 任意アドレスのテスト pattern | ✅ 0x101000 に書込→読戻し identity |
| DA を 0xc00 にロード (元実装) | ❌ 0xc00 は read-only/MMIO 用、書込無効 |
| DA を 0x100000 にロード | ❌ 4byte echo 後 chip クラッシュ (Boot ROM stack 衝突) |
| **DA を 0x101000 にロード (byte_swap=False)** | ✅ 全 15040 byte 書込成功、cksum 一致 |
| ↑ + jump 0x101000 | ❌ DA SYNC 期待 0xc0 ⇒ 0x1c 受信 |
| **+ チップ init (3 レジスタ)** | ❌ 同じ 0x1c |
| + 4レジスタ init | ❌ 同じ 0x1c |
| byte_swap=True で DA load | ❌ ARM 命令壊れ → 即クラッシュ (0byte) |

## 残る壁

### 1. DA ロードアドレスの矛盾

DA disasm から確定: **DA は 0x100000 ロード前提**
- 絶対 jump 先 0x10173C → DA byte 0x173C で `b 0x101798` (clean entry)
- (0x101000 ロード説は誤り。byte 0x73C は `cmpne r0, #0` = 関数中身)

しかし **0x100000 は Boot ROM のスタック領域** で、書き込むと 4 バイト echo 後にチップ無応答。
brom.dll の chip-init レジスタ書込 (`0x80210050/54/00`) を入れても回避されない。

### 2. DA 起動後の出力 `1c 00 e0 00` 繰り返し

0x101000 にロードしてジャンプした場合の chip 応答を捕捉:
```
1c 00 e0 00 1c 00 e0 00 1c 00 e0 00 1c 00 e0 00 1c 00 e0 00 ...(乱れる)
```
LE32 = `0x00e0001c` の繰り返し。意味不明。
DA 内に該当バイト列なし → DA が誤ったメモリを実行して出力してると推定。

### 3. MMIO チェックサム応答が常に 0x0202

レジスタ書込後の cksum 取得は値に関わらず `0x0202` を返す。
つまり cksum 経由で書込効果を確認する手段がない。

## 越えられなかった理由

PowerFlash.exe は brom.dll を使うが、おそらく **PowerFlash 本体内で brom と DA の間にもう1段階のセットアップ** を行っている。
それが `0x100000` 書込を可能にする「Boot ROM スタック退避」または「DRAM enable」のようなシーケンスの可能性。

### 追加で判明した壁（最終）

トランポリン戦略でも撃沈:
1. 0x101000 に「無限ループだけ」の最小トランポリン (16 bytes) を書込
2. 書込→読戻し完全一致確認 (writes が成功している)
3. jump 0x101000 を送る
4. → チップは無音にならず、`1c 00 e0 00` の繰り返しを出力

**つまりチップ CPU は 0x101000 から実行しない** ＝ 何らかのMPU/execute-permission がかかっている。
PowerFlash はおそらく **MPU 解除 or memory remap** のような追加 init をやっている。

### 真の必要事項

Mac で詰めきるには以下のいずれか:
1. PowerFlash.exe (1.4MB) の `Boot_FlashTool` 周辺を完全逆解析して隠れた初期化シーケンスを発見
2. Windows VM で PowerFlash 動作中の USB シリアル通信を全キャプチャ → 我々の Python 実装に反映
3. 中古調達した別個体で JTAG/SWD 直接接続 (基板要分解)

いずれもあと 1-2日コース、しかも保証なし。**現実解は Windows + PowerFlash 直接実行**。

仮説:
1. **PowerFlash 内に隠れた追加 init step がある**: `Brom_DownloadData` 経由で
   特殊な「DA load 専用」コマンドを使ってる可能性（解析未到達）
2. **DA は実行されているが我々の理解と違う応答プロトコル**を使っている
3. **必要な init レジスタが 0x80210000 系以外にもある**
4. **DA バイナリのバージョンが M-241 と不適合**
   - `MTK_AllInOne_DA_MT3318_v4.01.bin` は 2009年版
   - Holux Logger Utility (671105.zip, 2008年版) には `DA_v3.8.4.bin`
   - **古い M-241 用には v3.8.4 の方が正しい可能性大**

## 推奨する次の手

Mac で詰めきるには更に半日〜1日の調査が必要 (PowerFlash.exe 本体逆解析、または
USB スニフ で実プロトコル捕捉)。実用解は:

1. **Windows + PowerFlash**: 既に `windows_transfer.zip` 準備済
2. **Windows + Holux Logger Utility (671105.zip)**: 純正経路、`DA_v3.8.4.bin` で
   M-241 専用に最適化されてる可能性が高く最安全
3. **NMEA プロキシで運用**: ホスト側補正のみで OLED は妥協 (Stage 4 完成済)

## Mac 側で進歩した実装の保存先

- `scripts/mtk_proto.py` - MT3301 Boot ROM プロトコル Python 3 実装
  - DA load address 0x101000 (修正済)
  - `_init_mt3301_chip()` 追加 (4レジスタ書込)
  - 残り課題: DA SYNC 0xc0 を受信できる init シーケンスの完成

## 追加解析（2026-05-03 セッション）

### brom.dll 全エクスポート解析

**主要 DA load パスのエントリ群** (Holux brom.dll の場合):
```
HoluxLoggerUtility は ordinal で以下を import:
  ord 25 DA_Create
  ord 26 DA_Destroy
  ord 29 DA_SetStartAddr     ← DA load address はここで設定
  ord 31 DA_LoadByFilepath
  ord 33 DA_Unload
  ord 13 DL_Create
  ord 14 DL_Destroy
  ord 15 DL_LoadScatter
  ord 20 DL_Rom_LoadByFilepath
  ord 22 DL_Rom_Unload
  ord 47 DL_SetPacketLength
  ord 50 DL_Rom_SetEnableAttr
  ord 10 FlashDownload        ← 実際の flash 書込
```

DA_Load → 内部 0x6022ed0 → 0x6022dd0/0x6022d60/0x6022c90 → vtable+0x2c (DownloadData) → vtable+0x34 (Jump)

`Boot_FlashTool_Ex` → 0x6007580 (orchestrator) → 0x600c7c0 (vtable+0x04 = チップ固有 BootStop)
の中で:
1. `[ebx]` = vtable+0 (StartCmd / sync) を call
2. `[edx + 0x2c]` = vtable+0x2c (DownloadData) を call (DA を 0x100000 に書込)
3. `[edx + 0x34]` = vtable+0x34 (Jump) を call

**つまり sync 直後に何の追加 init もなく WRITE16 + JUMP するだけ**。MMIO init 等は見つからず。

### vtable+0x6c-0x78 の MMIO 書込関数 (BRom_mt3301 のみ存在)

```
vtable+0x6c (0x600caa0): write 0x80010010 ← arg
vtable+0x70 (0x600cad0): write 0x80010000 ← encoded value
vtable+0x74 (0x600cb70): write 0x80120004 ← arg
vtable+0x78 (0x600cba0): write 0x80130020 ← arg (via 0x6007ef0)
```

これらは brom.dll .text 内から **ゼロ呼出し**。PowerFlash.exe / HoluxLoggerUtility 側からも
辿った範囲では DA load フローでは呼ばれない。**多分 DA 独自プロトコル (CMD_*) の
実装で使うヘルパー** で、DA ロード後に DA 自身が叩くもの。

### vtable+0x4c (post-sync init, StartCmd 内)

```
StartCmd の sync ループ内 0x600c244-0x600c24d:
  push 0x80130020  ; ← debug log identifier (実際は MMIO 書込ではない)
  push esi         ; baud rate value
  push ebx         ; port handle
  call [edx + 0x4c]  ; vtable+0x4c
```

vtable+0x4c (0x6008330) の中身:
1. PurgeComm(handle, 0xf)        ; UART buffer clear
2. 0x6005c60 を call:
    - GetCommState (Windows)
    - SetCommState (新 baud rate, parity, etc)
    - EscapeCommFunction(SETRTS=3)
    - EscapeCommFunction(SETDTR=5)
3. Sleep(20ms)
4. PurgeComm 再度

つまり **Windows 側 COM port 設定変更** だけ。チップに対する MMIO 書込は無し。
0x80130020 は logging 用の identifier として渡されてるだけ。

### Holux brom.dll vs GlobalTop brom.dll

両方とも 245760 bytes、同日 (2008年3月)、export 数 83 個 (同名)。
全 export アドレス差 ≈ -0x260 bytes (Holux の方が前方にずれてる)。
**コードの差分は微小** (build 設定の違い程度と推定)。

### チップメモリレイアウト確認 (実機)

```
0x00000000-0x00000040: ARM IVT + reset code (eaffffff = b 0x4 etc)
0x00100000-0x00100020: BootROM scratchpad (42200202 + 55aa55aa magic)
0x00100024-0x0010003C: BootROM stack (saved LR like 0x0004dea9, 0x0004de80)
0x00100020-0x001007FC: BootROM 作業領域 (推定)
0x00101000+: 完全に空き RAM (zero init)
0x00800000+: 0x42200202 反復 (mirror or unmapped)
0x80000000+: MMIO 領域
```

**実証済 chip 挙動**:
- 0x00100000 への 4 バイト write → **チップ即死** (echo 4 バイトで停止)
- 0x00100020 への小 write (4-256 バイト) → echo OK だが **read 戻し値が常に変わる**
  (BootROM が即座に上書きしてる)
- 0x00100020 への大 write (4096+ バイト) → **チップ死亡**
- 0x00101000 への 14848 バイト write → **完全成功** (chip 生存、read 戻し正常)

### 仮説: なぜ brom.dll は 0x100000 に load できるのか

brom.dll が 0x100000 から書込開始しても:
- 0x100000-0x100003 への STR が IVT を破壊 → どんな割込でも data abort → 死亡
- 0x100024-0x1003FC への書込が現役 stack frame (saved LR等) を破壊 → BROM 復帰時に死亡

**なのに brom.dll が成功する理由は最後まで不明**。可能性:
1. brom.dll の WRITE16 は実は **0x100000 を書いてない** (Address translation かも)
2. brom.dll は **絶妙なタイミング** で BROM が ret する前に jump 命令を送る (race)
3. brom.dll は **HoluxLoggerUtility / PowerFlash の外側** に隠れた init を期待

### Mac 実装の現実解

DA を `0x101000` ロード + DA 内の絶対 literal 77 個を `+0x1000` relocate して起動する
workaround を試す価値はあるが、実機で chip が `0x101000` から実行可能な保証なし
(過去テストで `1c 00 e0 00` パターンが返って失敗した経緯あり)。

最終結論: **Mac 経路の DA ロードはあと一歩で詰みかけ**。実用解は Windows 経由 (PowerFlash か Holux Logger Utility) を試すか、NMEA proxy で運用するかの 2 択。

## 2026-05-04 セッション: HoluxLoggerUtility 解析で正規ロード先発見

### 決定的証拠

HoluxLoggerUtility.exe を逆アセンブル:
- `0x0040b7b0: push 0x00100800` ← DA_SetStartAddr の引数
- `0x0040b7b6: call DA_SetStartAddr` (= `DA_SetStartAddr(handle, 0x100800)`)

**正規 DA ロード先 = `0x100800`** (`0x100000` ではなかった)。

メモリ配置:
```
0x100000-0x1007FF: BootROM scratchpad/stack (書込不可、ここに書くと chip 死亡)
0x100800-0x104230: DA code (16KB) ← Holux 流の load 領域
0x104230+: DA's BSS/scratch
```

DA prelude の `bx r3 → 0x101718` は base=0x100800 では file offset 0xf18 にマップ:
- file 0xf18: `ldr r1, [pc, #0x64]; mov r0, #1; push {r4, lr}` ← real entry function ✓

### byte_swap=True が必須だった

WRITE16 プロトコルの実態:
- Wire は **BE16** (16-bit big-endian) 形式
- Chip は受信した 16-bit BE ワードを **LE16 in memory** に格納
- ARM CPU が memory を LE で読むと **元の DA file の通り** 解釈される

実証: `byte_swap=True` で書込 → memory[0x100800..3] が DA file の `[00, 00, a0, e1]` と
一致 → ARM が `mov r0, r0` を正しく実行。

### Read プロトコルの挙動

READ32 は memory の 32-bit LE 値を **BE32 で wire 送信** する。
そのため READ32 の戻り値は memory バイト順とは異なって見える (4 バイトリバースっぽい)。

### DA 起動成功

```
DA INFO: c0 03 08 49 00 08 00 00 00 c2 22 ba 00 00 00 00 00 30 40 00
- SYNC: 0xc0 ✓
- DA version: 0x0308 (= 3.8)
- Flash device id: 0x49
- Flash size: 0x00080000 = 512KB ✓ (M-241 の MXIC chip)
- Mfr: 0x00c2 (MXIC) Device: 0x22ba
```

### 残り課題: DA の flash protocol コマンド

DA 起動後、`OPCODE_MEM_CMD = 0xD3` 送ると:
- byte-by-byte echo は来る (各バイトをエコーしてる)
- echo 完了後 ACK (0x5a) を期待するが TIMEOUT

DA v3.8 のコマンドプロトコルが mt333x DA と微妙に違う模様。さらなる解析が必要。
HoluxLoggerUtility 側の FlashDownload 内部か、brom.dll 側の DownloadData 後の流れの解析が次の手。
