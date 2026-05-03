# Holux M-241 — GPS Week Number Rollover Fix

Resurrect a Holux M-241 GPS logger from the GPS Week Number Rollover (WNRO) bug
with a 2-byte firmware patch, no JTAG and no Windows.

> Holux ceased GPS operations in 2019. The M-241's clock has been broken since
> 2019-04-06 (the 2nd GPS WNRO). Without this fix every fix shows a date in
> 2006 instead of 2026.

[日本語版 README は `README.ja.md`](README.ja.md)

## What this project does

1. **Reverses MTK MT3318 BootROM protocol on macOS/Linux** so you can talk
   to the chip without GlobalTop's Windows-only `PowerFlash.exe`.
2. **Dumps the original firmware** off your own device (so you have a known-good
   backup before anything risky happens).
3. **Patches the firmware** at two well-defined byte offsets:
   - WNRO: shift the Unix epoch base forward by 1024 weeks
   - Cosmetic: bump the OLED-displayed version `V1.13` → `V1.14`
4. **Flashes the patched image back** through the same MTK Download Agent
   (DA) protocol that Holux's official tool used.

After flashing the patched image, `$GPRMC` reports the correct UTC date again
and the OLED follows.

## Status

| Component | Status |
|-----------|--------|
| Firmware dump | ✅ verified on macOS |
| BootROM sync (PMTK180 → 0xa0/0x0a/0x50/0x05) | ✅ |
| DA load at `0x00100800` (Holux's address) | ✅ |
| DA flash protocol (0xD3 set-mem, 0xD5 write, 0x5A ACK) | ✅ |
| WNRO patch verified on real device | ✅ NMEA shows correct UTC after fix |
| Version string `V1.13 → V1.14` | ✅ visible on OLED |
| PMTK aiding (715 / 716 / 717) | ✅ chip ACKs status=3 |

## Repository contents

```
.
├── docs/                     - everything we learned, in order
│   ├── 00-baseline.md         (broken behaviour, evidence)
│   ├── 01-protocol.md         (MTK BootROM protocol notes)
│   ├── 02-firmware-map.md     (M-241 firmware structure)
│   └── 03-brom-analysis.md    (full RE walkthrough)
├── scripts/
│   ├── mtk_proto.py           (BootROM client + DA driver)
│   ├── dump_firmware.py       (dump your own M-241 to a .bin)
│   ├── patch_firmware.py      (apply the 2-byte WNRO + version patch)
│   └── flash_firmware.py      (write a .bin back via DA)
└── requirements.txt
```

## What's NOT in this repo (and how to obtain)

To respect copyright, no proprietary binaries are committed. You need to
provide them yourself:

| File | How to obtain |
|------|---------------|
| `DA_v3.8.4.bin` | Inside the original Holux Logger Utility installer (search `1597553.zip` / `671105.zip`). MTK DA - do not redistribute. |
| `m241_dump.bin` | Dumped from **your own** M-241 with `scripts/dump_firmware.py`. Copyright stays with Holux/MTK. |

## Hardware required

- A **Holux M-241** with the WNRO bug (any unit shipped before mid-2019).
- The bundled USB cable, or any CP210x USB-to-UART bridge that exposes
  `/dev/tty.usbserial-*` on macOS or `/dev/ttyUSB*` on Linux.
- A computer running macOS or Linux. **Windows not required.**
- **A working backup workflow** (because firmware flashing can brick the
  device if interrupted).

## Quick start

```bash
# 0) Install Python deps
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 1) Dump your own M-241 (SAFE — read-only)
python3 scripts/dump_firmware.py /dev/tty.usbserial-0001 \
    --da firmware/agents/DA_v3.8.4.bin \
    firmware/original/m241_dump.bin

# 2) Apply the 2-byte WNRO patch + version bump
python3 scripts/patch_firmware.py \
    firmware/original/m241_dump.bin \
    firmware/patched/m241_v114_wnro.bin

# 3) Flash the patched image (DESTRUCTIVE — read DISCLAIMER.md first)
python3 scripts/flash_firmware.py /dev/tty.usbserial-0001 \
    --da firmware/agents/DA_v3.8.4.bin \
    --fw firmware/patched/m241_v114_wnro.bin \
    --i-have-backup firmware/original/m241_dump.bin \
    --start-addr 0x0 \
    --yes
```

After step 3, power-cycle the device and verify:

- OLED shows `V1.14`.
- `$GPRMC` (once you have a fix) shows the correct UTC date.

## How the patch works

The Holux M-241 firmware converts internal GPS time to Unix time with a
hard-coded constant `315964800` (= Unix epoch at GPS epoch 1980-01-06).
We change it to `935280000` (= original + 619 315 200 seconds = +1024 weeks
= +7168 days). This single 4-byte change at file offset `0x402F4` cleanly
shifts every reported timestamp into the post-2nd-rollover era.

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
