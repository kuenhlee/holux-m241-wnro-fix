# Disclaimer / 免責事項

## English

This project rewrites the firmware of a Holux M-241 GPS logger via the MTK
BootROM and Download Agent (DA) protocols. **The procedure is destructive
and irreversible without a working backup.**

By using anything in this repository you accept that:

1. **You may permanently brick your device.** A failed flash, a power loss
   mid-write, a wrong start address, a typo, or a bug in this code can leave
   the chip unable to boot. The M-241 has no JTAG header — recovery from a
   hard brick may require chip-off rework or scrapping the unit.

2. **No warranty.** The code is provided AS IS. The authors are not liable
   for any damage to your device, your data, or anything else.

3. **You are responsible for backups.** Always run `dump_firmware.py`
   *twice*, verify the SHA256 of both dumps match, and keep the original
   `.bin` somewhere safe before running `flash_firmware.py`. The dumped
   bytes are your only path back.

4. **You are responsible for your own use of proprietary files.** Holux
   Logger Utility, GlobalTop FlashTool, `brom.dll`, `PowerFlash.exe`, and
   the various `DA_*.bin` files remain the copyright of their original
   authors. Obtain them yourself, lawfully.

5. **Holux is defunct (2019).** There is no manufacturer support. Anything
   you do with this firmware is your call.

6. **This is for repair / preservation / research.** Use it to keep your own
   device working. Don't use it to defraud (e.g., reselling a unit as
   "factory original" after modification).

If any of this makes you uncomfortable: **don't run the destructive scripts.**
A host-side NMEA proxy (rewriting `$GPRMC` dates on the fly) is a zero-risk
alternative if you only need correct dates on the host computer side.

## 日本語

このプロジェクトは Holux M-241 のファームを MTK BootROM と Download Agent
(DA) プロトコル経由で書き換える。**書込手順は破壊的で、バックアップ無しでは
取り返しがつかない。**

このリポジトリのコードを使うときは以下を理解・同意したものとする:

1. **デバイスが恒久的にブリックする可能性がある。** 書込失敗、書込中の電源喪失、
   start アドレスの間違い、typo、コードのバグ — どれか一つでもあるとチップが
   起動不能になる。M-241 には JTAG ヘッダが無いため、ハードブリックからの
   復旧にはチップ単位の作業 (= 事実上の廃棄) が必要になる場合がある。

2. **無保証。** コードは "AS IS" で提供する。デバイス・データ等への損害について
   作者は一切責任を負わない。

3. **バックアップは自己責任。** `flash_firmware.py` を走らせる前に、必ず
   `dump_firmware.py` を **2回** 実行して、両方の SHA256 が一致することを
   確認し、オリジナルの `.bin` を安全な場所に保管すること。ダンプしたバイト列が
   唯一の復旧手段。

4. **proprietary ファイルの利用は自己責任。** Holux Logger Utility、GlobalTop
   FlashTool、`brom.dll`、`PowerFlash.exe`、各種 `DA_*.bin` の著作権は元々の
   著作権者にある。各自で合法的に入手すること。

5. **Holux は 2019年に撤退済。** メーカーサポートは存在しない。このファームで
   何をするかはあなたの判断。

6. **修理・保全・研究目的での利用を想定している。** 自分のデバイスを
   動かし続けるために使うこと。改変済機を「未改造」と称して転売する等の
   詐欺目的に使ってはいけない。

これらが気になる人へ: **破壊的スクリプトを実行しないこと。**
ホスト側で `$GPRMC` の日付をリアルタイム補正する NMEA プロキシを別途用意すれば、
ファームを書き換えずホスト側だけで正しい日付を得られる (= ゼロリスク)。
