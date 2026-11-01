#!/usr/bin/env python3
"""Build sensor_isp_color.conf from a stock Anyka ISP tuning conf (gc20c3 style).

The file holds three records at fixed offsets: REC0 day, REC1 night, REC2
sensor-config. The night record's tuning is fully monochrome; we replace
each of its parameter blocks with the matching block from the day record
(same ids, same sizes) so the "night" ISP style renders in color. Output
stays the same size as the input; the converted record is re-parsed to
validate before writing.

Get the stock file off your cam (tftp put via tftpd_rw, or tftp get from
the PC once you have it on the card):   /usr/local/isp_gc20c3.conf
Then:   python3 make-isp-color.py isp_gc20c3.conf sensor_isp_color.conf

Format (reverse-engineered, validated on fw 6.2802.78.158 / isp 6.114-20250904):
  unused u32 header (observed 7, meaning unknown) | ver[16] | records: hdr
  at +0 (sensor id u32, size u32 at +0x10), blocks start at rec+0x1ec, each
  block [u16 id | u16 size-INCL-header][payload], ids 0x00..0x17 then 0x1c
  (0x1c = sensor cfg, must stay untouched).
"""
import struct, sys

REC0, REC1, REC2 = 0x14, 0x16fe0, 0x2dfac
HDR = 0x1ec  # record header length before first block
LAST_ID = 0x1c

def parse_blocks(d, rec, end):
    p, out = rec + HDR, []
    while p + 4 <= end:
        bid, bsz = struct.unpack_from('<HH', d, p)
        if bsz < 4 or bsz > 0x10000 or p + bsz > end:
            break
        out.append((p, bid, bsz))
        p += bsz
    if not out:
        sys.exit(f"FATAL: record @{rec:#x}: no blocks parsed")
    if out[-1][1] != LAST_ID:
        sys.exit(f"FATAL: record @{rec:#x} does not end with block 0x{LAST_ID:x}")
    return out

def main(src, dst):
    d = bytearray(open(src, 'rb').read())
    size = struct.unpack_from('<I', d, REC0 + 0x10)[0]
    if struct.unpack_from('<I', d, REC0)[0] != 0x20c3 or struct.unpack_from('<I', d, REC1)[0] != 0x20c3:
        sys.exit("FATAL: not a gc20c3-style record file (sensor id mismatch)")
    b0 = parse_blocks(d, REC0, REC0 + size)
    b1 = parse_blocks(d, REC1, REC1 + size)
    if [(i, s) for _, i, s in b0] != [(i, s) for _, i, s in b1]:
        sys.exit("FATAL: day/night block tables differ in ids/sizes - refusing")
    n = 0
    for (o0, i0, s0), (o1, i1, s1) in zip(b0, b1):
        if i0 == LAST_ID:
            continue
        d[o1:o1 + s1] = d[o0:o0 + s0]
        n += 1
    parse_blocks(d, REC1, REC1 + size)          # re-parse to validate
    assert d[REC2:] == bytearray(open(src, 'rb').read())[REC2:], "rec2 modified"
    open(dst, 'wb').write(d)
    print(f"OK: {n} night blocks := day twins, size unchanged ({len(d)} B) -> {dst}")
    print("Install on cam (SD hack): copy to card custom/configs/sensor_isp_color.conf")

if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
