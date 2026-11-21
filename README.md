# Holux M-241 — GPS Week Number Rollover Fix

Resurrect a Holux M-241 GPS logger from the GPS Week Number Rollover (WNRO) bug
with a 2-byte firmware patch. Pure Python toolchain — no JTAG, no GlobalTop
`PowerFlash.exe` required.

> Holux ceased GPS operations in 2019. The M-241's clock has been broken since
> 2019-04-06 (the 2nd GPS WNRO). Without this fix every fix shows a date in
> 2006 instead of 2026.

[日本語版 README は `README.ja.md`](README.ja.md)

> **About this fork.** Adds a read-only Boot ROM probe (`scripts/probe_read.py`),
> safer dump / patch / flash scripts, and notes from a second unit (HW V02, FW V1.13)
> run from Windows with Tera Term. See
> [`docs/04-hw-v02-findings.md`](docs/04-hw-v02-findings.md) and
> [`docs/05-procedure-windows-teraterm.md`](docs/05-procedure-windows-teraterm.md).
> Upstream: [NekobaTechnology/holux-m241-wnro-fix](https://github.com/NekobaTechnology/holux-m241-wnro-fix).

## Related write-up

📝 **[Detailed blog post in Japanese](https://catea.tech/blog/holux-m241-wnro-fix)** — full story, debugging notes, and FAQ on the [catea.tech (Catea Tech)](https://catea.tech) site by [Kazuha Kato (二葉 / Futaba)](https://catea.tech/about). Covers the BootROM reverse engineering walkthrough, why the obvious `+1024` patches failed, the DA load-address discovery, and the undocumented PMTK aiding commands.

## What this project does

1. **Reverses MTK MT3318 BootROM protocol** so you can talk to the chip
   from any OS that runs `pyserial`, without GlobalTop's Windows-only
   `PowerFlash.exe`.
2. **Dumps the original firmware** off your own device (so you have a known-good
   backup before anything risky happens).
3. **Patches the firmware** at two well-defined byte offsets:
   - WNRO: shift the Unix epoch base forward by 1024 weeks
   - Cosmetic: bump the OLED-displayed version `V1.13` → `V1.14`
4. **Flashes the patched image back** through the same MTK Download Agent
   (DA) protocol that Holux's official tool used.

After flashing the patched image, `$GPRMC` reports the correct UTC date again
and the OLED follows.

## Status (original author's unit)

| Component | Status |
|-----------|--------|
| Firmware dump | ✅ verified on macOS |
| BootROM sync (PMTK180 → 0xa0/0x0a/0x50/0x05) | ✅ |
| DA load at `0x00100800` (Holux's address) | ✅ |
| DA flash protocol (0xD3 set-mem, 0xD5 write, 0x5A ACK) | ✅ |
| WNRO patch verified on real device | ✅ NMEA shows correct UTC after fix |
| Version string `V1.13 → V1.14` | ✅ visible on OLED |
| PMTK aiding (715 / 716 / 717) | ✅ chip ACKs status=3 |

## Tested on a second unit (this fork)

| Item | Result |
|------|--------|
| Unit | Holux M-241, HW V02, FW V1.13; Windows + Tera Term (38400) |
| Boot ROM read / dump | ✅ needs `--base-addr 0x200000` (flash is not at the default `0x20000000`) |
| Flash / DA | ✅ 512 KB MXIC `0xc2` / `0x22ba`; DA v3.8 loaded at `0x100800` |
| Patched image flashed | ✅ with `--start-addr 0x0` |
| Version string | ✅ `V1.14` |
| GPS lock | ✅ |
| Logging by time (5 s) | ✅ |
| Log download (Holux Logger Utility) → KML → Google Earth | ✅ |
| `$GPRMC` / OLED date, log timestamps | ⏳ to be confirmed (see `docs/04`) |

The memory map and base addresses differ between units, so run `probe_read.py`
before dumping or flashing — see the Quick start.

## Repository contents

```
.
├── docs/                     - everything we learned, in order
│   ├── 00-baseline.md         (broken behaviour, evidence)
│   ├── 01-protocol.md         (MTK BootROM protocol notes)
│   ├── 02-firmware-map.md     (M-241 firmware structure)
│   ├── 03-brom-analysis.md    (full RE walkthrough)
│   ├── 04-hw-v02-findings.md  (second unit: memory map, patch offsets, results)
│   └── 05-procedure-windows-teraterm.md (step-by-step on Windows with Tera Term)
├── scripts/
│   ├── mtk_proto.py           (BootROM client + DA driver)
│   ├── probe_read.py          (read-only Boot ROM read-path / memory-map check)
│   ├── dump_firmware.py       (dump your own M-241 to a .bin)
│   ├── patch_firmware.py      (apply the 2-byte WNRO + version patch)
│   └── flash_firmware.py      (write a .bin back via DA; --info-only to test the DA)
└── requirements.txt
```

## What's NOT in this repo (and how to obtain)

To respect copyright, no proprietary binaries are committed. You need to
provide them yourself:

| File | How to obtain |
|------|---------------|
| `DA_v3.8.4.bin` | Inside the original Holux Logger Utility installer (search `1597553.zip` / `671105.zip`). MTK DA - do not redistribute. |
| `m241_dump70.bin` | Dumped from **your own** M-241 with `scripts/dump_firmware.py` (`0x70000` bytes). Copyright stays with Holux/MTK. `firmware/` and `*.bin` are git-ignored. |

## Hardware required

- A **Holux M-241** with the WNRO bug (any unit shipped before mid-2019).
- The bundled USB cable, or any CP210x USB-to-UART bridge that exposes
  `/dev/tty.usbserial-*` on macOS or `/dev/ttyUSB*` on Linux.
- A computer with Python 3.10+ and `pyserial`. Verified on macOS (original
  author) and Windows (this fork: Tera Term + `COM3`, see
  [`docs/05`](docs/05-procedure-windows-teraterm.md)); should also work on
  Linux (pyserial is cross-platform).
- **A working backup workflow** (because firmware flashing can brick the
  device if interrupted).

## Quick start

`<PORT>` is `/dev/tty.usbserial-*` (macOS), `/dev/ttyUSB0` (Linux) or `COM3` (Windows).
Windows users: follow [`docs/05-procedure-windows-teraterm.md`](docs/05-procedure-windows-teraterm.md),
which also covers entering Boot ROM mode and closing Tera Term before running the scripts.

```bash
# 0) Install Python deps
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 1) Check where flash is mapped on YOUR unit (read-only).
#    The right base address shows the ARM vector table (18 f0 9f e5 ...).
#    It is 0x200000 on the HW V02 unit; the default 0x20000000 returns a
#    constant fill there. Do not dump or flash until the probe passes.
python3 scripts/dump_firmware.py <PORT> firmware/original/m241_header.bin \
    --base-addr 0x200000 --header-only --no-verify
python3 scripts/probe_read.py <PORT> --base-addr 0x200000 \
    --header firmware/original/m241_header.bin

# 2) Back up the 0x70000-byte image (read-only). The two passes must match.
python3 scripts/dump_firmware.py <PORT> firmware/original/m241_dump70.bin \
    --base-addr 0x200000 --length 0x70000

# 3) Apply the 2-byte WNRO patch + version bump
python3 scripts/patch_firmware.py \
    firmware/original/m241_dump70.bin \
    firmware/patched/m241_v114_wnro.bin

# 4) Test the Download Agent without writing flash
python3 scripts/flash_firmware.py <PORT> \
    --da firmware/agents/DA_v3.8.4.bin \
    --fw firmware/patched/m241_v114_wnro.bin \
    --i-have-backup firmware/original/m241_dump70.bin \
    --start-addr 0x0 --info-only

# 5) Flash the patched image (DESTRUCTIVE — read DISCLAIMER.md first)
python3 scripts/flash_firmware.py <PORT> \
    --da firmware/agents/DA_v3.8.4.bin \
    --fw firmware/patched/m241_v114_wnro.bin \
    --i-have-backup firmware/original/m241_dump70.bin \
    --start-addr 0x0
```

Notes:

- The flasher refuses firmware whose length is not a multiple of `0x100`, or that
  differs from the backup by anything other than the three patch bytes.
- `--start-addr 0x0` worked on the HW V02 unit; the original `--yes` flag is
  deliberately left out of the example so you confirm the write.
- An optional "identity test" (flash your unmodified backup first and re-dump to
  compare hashes) is described in `docs/05`.

After step 5, power-cycle the device and verify:

- OLED shows `V1.14`.
- `$GPRMC` (once you have a fix) shows the correct UTC date.

## How the patch works

The Holux M-241 firmware converts internal GPS time to Unix time with a
hard-coded constant `315964800` (= Unix epoch at GPS epoch 1980-01-06).
We change it to `935280000` (= original + 619 315 200 seconds = +1024 weeks
= +7168 days). This single 4-byte change at file offset `0x402F4` cleanly
shifts every reported timestamp into the post-2nd-rollover era.
The constant appears twice in the firmware (`0x402DC` and `0x402F4`); only the one
at `0x402F4` is patched — patching both overshoots the date.

Why not patch the GPS week computation directly? We tried 4 separate
`movs r1, #1; lsls r1, r1, #10` (= "+1024 weeks") sites first — none of
them affected the NMEA RMC date. The epoch constant approach is one-line,
deterministic, and survives any code path that ultimately produces UTC.

## Risks

This is firmware modification on a device with no JTAG. Read
[`DISCLAIMER.md`](DISCLAIMER.md) before running anything destructive. The
project is provided as-is for educational and right-to-repair purposes.

## License

[MIT](LICENSE) for everything in this repo. Proprietary firmware files
that you supply yourself remain under their original copyright.

## Acknowledgements

- [`mt333x-fw-utils`](https://github.com/dimhoff/mt333x-fw-utils) by dimhoff
  for the original MTK GPS protocol reference.
- BT747 project for documenting MTK GPS quirks.
- Everyone who keeps abandonware running.

## How this was built

The reverse engineering, BootROM/DA driver implementation, firmware
disassembly and patch identification were carried out interactively with
[Claude Code](https://www.anthropic.com/claude-code) (Anthropic's AI
coding assistant). Every byte committed here was reviewed and tested on
real hardware by a human before publication.
