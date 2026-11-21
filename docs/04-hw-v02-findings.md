# 04 - Findings from a second unit (HW V02, FW V1.13)

Notes from applying this project to a unit that differs from the original author's
in a few details. Everything here was observed on one device; treat it as
"worked / looked like this on one unit", not as a general guarantee.

No firmware bytes are reproduced here. Hashes are given only so others can compare.

## Unit under test

| Item | Value |
| --- | --- |
| Holux Logger Utility | Device Type `M-241`, `[FW][HW] = [V1.13][V02]` |
| `$PMTK705` reply | `$PMTK705,B-core_1.20,0043,01017-00F,1.0*72` |
| Header (`parse_fw_header`) | family `HOLUX_M-241`, device_type `01017-00F`, release `B-core` 1.20, build 67 (= `0x43`, matches the `0043` in `$PMTK705`), `fw_size` 406616 (`0x63458`) |
| Flash (from DA_INFO) | 524288 bytes, manufacturer `0x00c2` (MXIC), device code `0x22ba`, DA version `0x0308` |

`chip_guess` in `parse_fw_header` is only a lookup on `release_major`
(`{1: MT3329, 2: MT3339, 3: MT3333}`). It is **not** evidence of the chip. The chip
was not conclusively identified here.

## Boot ROM memory map on this unit (read-only probe, `scripts/probe_read.py`)

| Address | Contents |
| --- | --- |
| `0x00000000` | Boot ROM code (`ff ff ff ea`, `mrs r0,cpsr`, `mov r1,#0xc0`) - **not** flash |
| `0x00100000` | RAM / BootROM scratch (`02 02 20 42 00 00 aa 55 ...`) |
| `0x00100800` | RAM, reads zero - where the DA is loaded |
| `0x00200000`-`0x0027ffff` | SPI flash (512 KB); vector table at `0x200000` |
| `0x00280000` | wraps - same vector table as `0x200000` |
| `0x00270000` | ASCII data (looks like settings), outside the 0x70000 image |
| `0x20000000` | constant fill `02 02 20 42` (nothing mapped) |

### Consequences

* The dump **must** use `--base-addr 0x200000`. The default (`0x20000000`) returns the
  constant fill `02 02 20 42` for the whole length. This is *not* detected by the
  two-pass verify, because both passes read the same wrong address and agree.
  `dump_firmware.py` now rejects constant-fill dumps.
* `--base-addr 0x0` (suggested in the old help text for MT3318) reads Boot ROM, not
  flash, on this unit.
* The image the tools expect is `0x70000` bytes from `0x200000`
  (`--length 0x70000`). That is `fw_size` (`0x63458`) plus the unit's data up to the
  64 KB boundary. Dumping only `fw_size` bytes is not enough for flashing: the
  flasher sends fixed 256-byte packets, and `406616 % 256 = 88`. Rewriting only the
  firmware bytes could also leave the rest of an erase block unwritten.
* Byte order: `read(..., byte_swap=True)` (the dump default) is correct;
  `byte_swap=False` yields reversed words.

## Patch targets

Verified in a dump from this unit (file offset == address; the reset vector
literal is `0xa6c`):

* Unix epoch constant `315964800` (LE `80 3d d5 12`) appears **twice**: `0x402dc` and
  `0x402f4`. Each lives in a Thumb literal pool followed by `0x093a80` (604800, seconds
  per week) and is referenced by two functions. Patching both overshoots (see the
  author's write-up); patch only `0x402f4`.
* `V1.13` at `0x59c28`; the patch changes the `'3'` at `0x59c2c`.
* The patch changes exactly three bytes: `0x402f6`, `0x402f7` (epoch `0x12d53d80` ->
  `0x37bf3d80`, +619315200 s = 1024 weeks) and `0x59c2c`.

## Hashes (for comparison only)

| Item | sha256 |
| --- | --- |
| first 406616 bytes (initial dump) | `2b36d09aaf377ccba54128eb4858fd1413cae05a155793904e119160965b8255` |
| 0x70000 backup | `8099de5807ef3e66...` (16-char prefix; unit-specific) |
| patched 0x70000 image | `a4005a736bb68a48...` (16-char prefix) |
| author's verified image prefix | `b83204e0cb4a1daa` (does **not** match this unit's 0x70000 image) |

The author's hash check therefore fails on this unit even though the patch offsets
and old bytes match. `patch_firmware.py` now validates structure instead.

## Flash result and field test

* DA loaded at `0x100800` and reported the flash details above (`--info-only`).
* `flash_firmware.py ... --start-addr 0x0` wrote the patched 0x70000 image
  successfully; the Setting menu then showed `V1.14`. So `--start-addr 0x0` is the
  correct DA write address on this unit (flash offset, not the `0x200000` CPU address).
* After flashing the device came up with default settings; the erase function was
  exercised afterwards.
* Outdoor test (user-reported):
  * the updated unit obtained a GPS lock;
  * logging by time, interval 5 s, works and records data;
  * the log was downloaded with Holux Logger Utility, converted to KML and opened in
    Google Earth without problems.

## Still to confirm

Record the answers here once checked:

* [ ] `$GPRMC` date field (Tera Term, 38400) shows today's UTC date.
* [ ] OLED date/time shows the correct date.
* [ ] Timestamps of the downloaded log are correct **without** any +7168-day
      post-processing (e.g. in the KML / Google Earth time slider).
* [ ] Behaviour of a unit with a different HW revision or chip.

The procedure used on Windows is in [`05-procedure-windows-teraterm.md`](05-procedure-windows-teraterm.md).

## Script changes in this fork

| Script | Change |
| --- | --- |
| `probe_read.py` (new) | Read-only checks of the Boot ROM read path: known bytes, byte order, chunk consistency, data variation, optional header-file comparison, memory map. Never writes. |
| `dump_firmware.py` | Rejects a dump that is a constant fill (exit code 4) instead of saving it and "verifying" it. |
| `patch_firmware.py` | Structural validation (header magic, `fw_size`, `V1.13`, old bytes) instead of a fixed size + author's sha256; aborts without writing on any mismatch (it used to skip and still write); requires exactly three changed bytes. |
| `flash_firmware.py` | `--start-addr` required (help text and usage example disagreed); refuses a length that is not a multiple of 0x100; refuses firmware that differs from the backup other than by the 3 patch bytes (an identical image is allowed as an "identity test"); `--info-only` (loads DA, prints flash info, never writes flash); uses the same Boot ROM entry as `dump_firmware.py` by default, `--legacy-start` restores the old PMTK180 method. |
