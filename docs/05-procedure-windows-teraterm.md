# 05 - Procedure used on Windows (Tera Term + Python)

How this fork's tooling was used on a Windows PC, which differs from the original
author's macOS / CP210x setup in these ways: connection is made with Tera Term at
38400 baud, Boot ROM is entered with a manual `$PMTK180*3B`, the memory map is probed
before dumping, and the flash start address is confirmed on the unit.

> **Destructive.** The device has no JTAG header. Read `DISCLAIMER.md`, keep your
> original backup, and keep the battery charged and USB connected throughout.
> Proprietary files (DA, dumps, patched image) are not part of this repository.

## 0. Prerequisites

* Windows PC, Python 3 and a virtual environment with `pyserial`
  (`pip install -r requirements.txt`).
* The Download Agent supplied by you at `firmware\agents\DA_v3.8.4.bin`.
* USB cable to the M-241. Find the COM port in Device Manager (examples use `COM3`).
* Holux Logger Utility (optional, to read the version before and after).

## 1. Identify the unit

1. Holux Logger Utility -> device information: note `[FW][HW] Version`
   (this unit: `[V1.13][V02]`).
2. Tera Term -> New connection -> Serial -> your COM port; Setup -> Serial port ->
   speed **38400**. NMEA sentences (`$GPRMC`, ...) should stream.
3. Send commands with Tera Term's **Control -> Broadcast Command** (menu names can
   differ slightly between versions). Each command needs a trailing CR+LF; the scripts
   in this repo send `\r\n`.
4. Query the firmware release:

   ```
   $PMTK605*31
   ```

   This unit replied:

   ```
   $PMTK705,B-core_1.20,0043,01017-00F,1.0*72
   ```

   Fields: release string `B-core_1.20`, build id `0043` (hex; `0x43` = 67, the same
   value `parse_fw_header` reads from the file header), product/OEM code `01017-00F`,
   version `1.0`. (Checksums above are verified: `31`, `72`.)

### What the reply does and does not tell you

The following explanation was obtained from an AI assistant and is reproduced for
reference. **It is not independently verified**:

> The response comes from the MediaTek MT3318 chipset (using the B-core 1.20 firmware
> branch). B-core_1.20 is the release string; 0043 is Holux's internal build number;
> 01017-00F is Holux's OEM hardware/firmware identifier; 1.0 is the SDK version.
> MT3318 is a 32-channel, L1 GPS-only chip with an ARM7EJ-S core. As an MT3318-based
> M-241 ("Hardware 02") it uses a Silicon Labs CP210x USB-to-UART bridge and works with
> GPSBabel and BT747. Because the firmware predates the April 2019 week-number
> rollover, logged dates are 1024 weeks (7,168 days) early unless a date-offset filter
> such as GPSBabel's `track,move=7168d` is applied on export.

Notes on that text:

* `$PMTK605` asks for the **firmware release**; the `$PMTK705` reply names a firmware
  branch, not the silicon. The M-241 is documented as MT3318-based in the original
  author's write-up, which is consistent with this reply, but the reply itself does not
  prove the chip. The chip was not independently identified in this fork.
* The CP210x bridge and the GPSBabel / BT747 compatibility were not tested here (this
  unit was read with Holux Logger Utility).
* The chip name does **not** give you the memory map. The older `dump_firmware.py` help
  text says to use base `0x0` for MT3318; on this unit `0x0` is Boot ROM and the flash
  is at `0x200000`. Always run `probe_read.py` (step 4) instead of trusting a chip label.
* The rollover description and the `+7168 d` log workaround are correct and apply to
  unpatched firmware.

## 2. Enter Boot ROM mode

1. In Tera Term send:

   ```
   $PMTK180*3B
   ```

   (checksum verified.) The device leaves NMEA output and waits in Boot ROM mode.
2. **Disconnect and close the serial port in Tera Term.** Windows lets only one program
   hold a COM port; if it is still open the scripts fail with
   `PermissionError(13, 'Access is denied.')` before sending any data. Also close
   Holux Logger Utility and any other serial software.
3. Continue from the command line. The scripts also pulse RTS/DTR themselves
   (`[setup] pulse RTS+DTR for chip reset`) when they connect, and the unit stayed
   usable this way. It was not tested whether the manual `$PMTK180` is strictly needed.
   If a script cannot enter Boot ROM, reset the device and repeat steps 2.1-2.3.
4. After every script the device remains in Boot ROM until you **reset / power-cycle** it
   when asked.

## 3. Header dump

```
python scripts\dump_firmware.py COM3 firmware\original\m241_header.bin --base-addr 0x200000 --header-only --no-verify
```

Expected header analysis for this unit: family `HOLUX_M-241`, device_type `01017-00F`,
release `B-core`, major 1, minor 20, build 67, `fw_size` 406616. (`chip_guess` is only a
lookup on the release number; ignore it.)

`--base-addr 0x200000` is required. The default `0x20000000` returns the constant
`02 02 20 42` for the whole length, and the two-pass verify still passes.

## 4. Probe the memory map (read-only)

```
python scripts\probe_read.py COM3 --header firmware\original\m241_header.bin
```

Expected: every check in sections 1 and 5 passes, data varies in section 4, and the last
line reads `RESULT: read path looks good`. Section 6 shows the map on this unit:

| Address | Meaning |
| --- | --- |
| `0x0` | Boot ROM code |
| `0x100800` | RAM (reads zero; DA load address) |
| `0x200000`-`0x27ffff` | 512 KB flash |
| `0x280000` | wraps to the same vector table as `0x200000` |
| `0x20000000` | constant fill (nothing mapped) |

If `0x200000` does not show the vector table (`18 f0 9f e5 ...`) on your unit, **stop**
and work out the flash base before dumping or flashing.

## 5. Full backup (twice)

```
python scripts\dump_firmware.py COM3 firmware\original\m241_dump70.bin --base-addr 0x200000 --length 0x70000
```

* Takes about a minute. Press Enter after power-cycling for the second pass.
* The two hashes **must match**, and the file must not be a constant fill (the script
  now refuses that).
* The image is `0x70000` bytes: the firmware (`fw_size` = `0x63458`) plus the unit's data
  up to a 64 KB boundary. Do not pad the tail with `FF`.
* Copy the file somewhere safe and note its sha256. This is your restore image.

## 6. Patch

```
python scripts\patch_firmware.py firmware\original\m241_dump70.bin firmware\patched\m241_v114_wnro.bin
```

Expected: two patches applied and `changed bytes: ['0x402f6', '0x402f7', '0x59c2c']`.
The "sha256 differs from the author's image" note is normal. If a check fails the script
aborts and writes nothing.

## 7. Test the Download Agent without writing

```
python scripts\flash_firmware.py COM3 --da firmware\agents\DA_v3.8.4.bin --fw firmware\patched\m241_v114_wnro.bin --i-have-backup firmware\original\m241_dump70.bin --start-addr 0x0 --info-only
```

It prints the confirmation banner and asks for `WRITE`; with `--info-only` nothing is
written to flash (the DA is loaded into RAM). Expected on this unit: DA version `0x0308`,
flash size `524288`, manufacturer `0x00c2`, device code `0x22ba`. Stop if these differ.

## 8. (Recommended) Identity test

Rewrite the original image unchanged to prove the write path and `--start-addr`:

```
python scripts\flash_firmware.py COM3 --da firmware\agents\DA_v3.8.4.bin --fw firmware\original\m241_dump70.bin --i-have-backup firmware\original\m241_dump70.bin --start-addr 0x0
```

Power-cycle, dump again to a new filename, and confirm the hash equals your backup.

## 9. Flash the patched image

Same command with `--fw firmware\patched\m241_v114_wnro.bin`. The flasher refuses to
run unless the length is a multiple of 0x100 and the file differs from the backup in
exactly the three patch bytes. Do not use `--high-baud` for a first attempt. Do not
disconnect during the write. `--start-addr 0x0` worked on this unit.

If the write fails partway, do not unplug and retry blindly: re-run the command with
`--fw` set to your backup image and keep the error output. Boot ROM mode is reported by
the original author to survive a bad write; that was not tested here.

## 10. Verify

1. Power-cycle. Setting menu should show `V1.14`.
2. Tera Term at 38400: read `$GPRMC` and check the date field is today's UTC date.
3. Outdoors, clear sky, cold start (allow 15+ minutes): confirm a fix.
4. Logging test: log by time at 5 s, download with Holux Logger Utility, convert to KML
   and check timestamps in Google Earth without any +7168-day shift.

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| Dump is `02 02 20 42` repeated | Missing `--base-addr 0x200000` |
| `Access is denied` opening the port | Tera Term / another program still holds the port; close it, re-plug USB, check the COM number |
| Old `patch_firmware.py` says size or sha256 mismatch | Use the fork's version (structural checks) |
| `probe_read.py` reports FAIL on a known-byte check | Re-read the output; do not dump or flash until the read path is trusted |
| DA load fails | Reset the device and retry; do not flash. Report the `[diag]` lines |
| Flash fails partway | Re-flash the original backup with the same command |
